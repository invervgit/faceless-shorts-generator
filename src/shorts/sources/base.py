import abc
import json
import logging
import time
from typing import List, Optional

from pydantic import BaseModel

from shorts.cache import cache

logger = logging.getLogger(__name__)


class ImageResult(BaseModel):
    url: str
    width: int
    height: int
    license: str
    attribution: str
    source_name: str
    thumb_url: str


class ImageSource(abc.ABC):
    name: str
    requires_key: bool
    supports_people: bool
    license_type: str

    @abc.abstractmethod
    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        """
        Search for images matching the query.
        Must catch all exceptions and degrade gracefully to returning [].
        """
        pass

    async def cached_search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        """
        Wraps search with a 7-day cache.
        """
        cache_key = f"{self.name}_{query}_{count}_{orientation}_{min_width}"
        
        cached_data = cache.get_json("source_search", cache_key)
        if cached_data:
            # Check 7-day TTL (7 * 24 * 60 * 60 = 604800 seconds)
            if time.time() - cached_data.get("timestamp", 0) < 604800:
                logger.debug(f"Cache hit for {self.name}: {query}")
                return [ImageResult.model_validate(r) for r in cached_data.get("results", [])]

        logger.debug(f"Cache miss for {self.name}: {query}")
        results = await self.search(query, count=count, orientation=orientation, min_width=min_width)
        
        # Save to cache
        cache.set_json("source_search", cache_key, {
            "timestamp": time.time(),
            "results": [r.model_dump() for r in results]
        })
        
        return results
