import logging
import os
from typing import List

from shorts.cache import cache
from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)

class OpenverseSource(ImageSource):
    name = "openverse"
    requires_key = False
    supports_people = True
    license_type = "creative_commons"

    async def _get_token(self) -> str:
        client_id = os.getenv("OPENVERSE_CLIENT_ID")
        client_secret = os.getenv("OPENVERSE_CLIENT_SECRET")
        if not client_id or not client_secret:
            return ""

        cached_token = cache.get_json("openverse", "token")
        if cached_token:
            return cached_token.get("access_token", "")

        auth_url = "https://api.openverse.org/v1/auth_tokens/token/"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials"
        }
        try:
            resp = await fetch("POST", auth_url, data=data, use_cache=False)
            if resp.status_code == 200:
                token_data = resp.json()
                cache.set_json("openverse", "token", token_data)
                return token_data.get("access_token", "")
        except Exception as e:
            logger.warning(f"Openverse OAuth failed: {e}")
        return ""

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        results: List[ImageResult] = []
        try:
            token = await self._get_token()
            headers = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"

            url = "https://api.openverse.org/v1/images/"
            params = {
                "q": query,
                "license_type": "commercial,modification",
                "page_size": min(count * 2, 50)
            }

            resp = await fetch("GET", url, params=params, headers=headers, use_cache=False)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("results", []):
                    w = item.get("width", 0) or 0
                    if w >= min_width:
                        results.append(ImageResult(
                            url=item.get("url"),
                            width=w,
                            height=item.get("height", 0) or 0,
                            license=item.get("license", "Unknown"),
                            attribution=item.get("creator", "Unknown"),
                            source_name=self.name,
                            thumb_url=item.get("thumbnail", item.get("url"))
                        ))
        except Exception as e:
            logger.warning(f"Openverse search failed: {e}")

        return results[:count]

# Expose instance
source = OpenverseSource()
