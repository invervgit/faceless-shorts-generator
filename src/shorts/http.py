import asyncio
import json
import logging
from typing import Any, Mapping, Optional

import httpx
from aiolimiter import AsyncLimiter
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from shorts.cache import cache
from shorts.config import settings

logger = logging.getLogger(__name__)

# Shared httpx.AsyncClient
_client = httpx.AsyncClient(
    http2=False,
    timeout=30.0,
    headers={"User-Agent": settings.full_user_agent},
)

# Per-host rate limiters
_limiters: dict[str, AsyncLimiter] = {}


def get_limiter(url: str) -> AsyncLimiter:
    """Returns a token bucket rate limiter for the given URL's host."""
    host = httpx.URL(url).host
    if host not in _limiters:
        # Default: 2 requests per second per host.
        _limiters[host] = AsyncLimiter(2, 1.0)
    return _limiters[host]


class RetryableHTTPError(Exception):
    """Exception raised for HTTP statuses that should be retried (429, 5xx)."""
    pass


async def fetch(
    method: str,
    url: str,
    params: Optional[Mapping[str, Any]] = None,
    use_cache: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    """
    Executes an HTTP request with caching, per-host rate limiting, and retries.
    """
    # Cache lookup
    if use_cache:
        # Sort keys to ensure consistent hashing
        cache_key = json.dumps({"method": method, "url": url, "params": params}, sort_keys=True)
        cached_content = cache.get("http", cache_key)
        if cached_content is not None:
            # Reconstruct a dummy httpx.Response for cached data
            return httpx.Response(200, content=cached_content, request=httpx.Request(method, url))

    limiter = get_limiter(url)
    
    # Configure retry logic with Tenacity
    retryer = AsyncRetrying(
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=1, max=60),
        retry=retry_if_exception_type((httpx.TransportError, RetryableHTTPError)),
        reraise=True,
    )

    async for attempt in retryer:
        with attempt:
            async with limiter:
                response = await _client.request(method, url, params=params, **kwargs)
                
                if response.status_code in {429, 500, 502, 503, 504}:
                    if "Retry-After" in response.headers:
                        try:
                            retry_after = int(response.headers["Retry-After"])
                            if retry_after > 10:
                                logger.warning(f"Rate limited by {url} with extreme Retry-After: {retry_after}s. Failing fast to trigger fallback.")
                                response.raise_for_status() # This will raise HTTPStatusError and break out of Tenacity
                            
                            logger.warning(f"Rate limited by {url}. Honor Retry-After: {retry_after}s.")
                            await asyncio.sleep(retry_after)
                        except ValueError:
                            # Retry-After might be a date string. Let Tenacity backoff handle it.
                            pass
                    raise RetryableHTTPError(f"Received retryable status: {response.status_code}")
                
                # We do NOT retry 4xx errors (except 429, handled above).
                # raise_for_status will raise HTTPStatusError for 4xx and 5xx.
                # Since HTTPStatusError is NOT in retry_if_exception_type, it will bubble up.
                response.raise_for_status()

    # Save successful responses to cache
    if use_cache and response.status_code == 200:
        # Local variable assignment of cache_key here since the initial lookup is inside `if use_cache:`
        # We need to re-compute it if we haven't computed it yet
        cache_key = json.dumps({"method": method, "url": url, "params": params}, sort_keys=True)
        cache.set("http", cache_key, response.content)

    return response


async def close_client() -> None:
    """Closes the shared httpx client."""
    await _client.aclose()
