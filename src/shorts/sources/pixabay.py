import logging
import os
from typing import List

from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)


class PixabaySource(ImageSource):
    name = "pixabay"
    requires_key = True
    supports_people = False
    license_type = "commercial_free"

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        api_key = os.getenv("PIXABAY_API_KEY")
        if not api_key:
            return []

        results: List[ImageResult] = []
        try:
            url = "https://pixabay.com/api/"
            params = {
                "key": api_key,
                "q": query,
                "per_page": min(count * 2, 200),
                "orientation": "horizontal" if orientation == "landscape" else "vertical",
                "image_type": "photo",
                "safesearch": "true"
            }

            resp = await fetch("GET", url, params=params, use_cache=False)
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", []):
                    w = hit.get("imageWidth", 0)
                    if w >= min_width:
                        results.append(ImageResult(
                            url=hit.get("largeImageURL", ""),
                            width=w,
                            height=hit.get("imageHeight", 0),
                            license="Pixabay License",
                            attribution=hit.get("user", "Unknown"),
                            source_name=self.name,
                            thumb_url=hit.get("webformatURL", "")
                        ))
        except Exception as e:
            logger.warning(f"Pixabay search failed: {e}")

        return results[:count]

source = PixabaySource()
