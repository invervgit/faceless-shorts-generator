import logging
import os
from typing import List

from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)


class UnsplashSource(ImageSource):
    name = "unsplash"
    requires_key = True
    supports_people = False
    license_type = "commercial_free"

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        api_key = os.getenv("UNSPLASH_API_KEY")
        if not api_key:
            return []

        results: List[ImageResult] = []
        try:
            url = "https://api.unsplash.com/search/photos"
            headers = {"Authorization": f"Client-ID {api_key}"}
            params = {
                "query": query,
                "per_page": min(count * 2, 30),
                "orientation": orientation if orientation in ["landscape", "portrait", "squarish"] else "portrait"
            }

            resp = await fetch("GET", url, params=params, headers=headers, use_cache=False)
            if resp.status_code == 200:
                data = resp.json()
                for photo in data.get("results", []):
                    w = photo.get("width", 0)
                    if w >= min_width:
                        results.append(ImageResult(
                            url=photo.get("urls", {}).get("raw", "") + "&w=1920",
                            width=w,
                            height=photo.get("height", 0),
                            license="Unsplash License",
                            attribution=photo.get("user", {}).get("name", "Unknown"),
                            source_name=self.name,
                            thumb_url=photo.get("urls", {}).get("regular", "")
                        ))
        except Exception as e:
            logger.warning(f"Unsplash search failed: {e}")

        return results[:count]

source = UnsplashSource()
