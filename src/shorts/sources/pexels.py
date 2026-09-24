import logging
import os
from typing import List

from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)


class PexelsSource(ImageSource):
    name = "pexels"
    requires_key = True
    supports_people = False
    license_type = "commercial_free"

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        api_key = os.getenv("PEXELS_API_KEY")
        if not api_key:
            return []

        results: List[ImageResult] = []
        try:
            url = "https://api.pexels.com/v1/search"
            headers = {"Authorization": api_key}
            params = {
                "query": query,
                "per_page": min(count * 2, 80),
                "orientation": orientation if orientation in ["landscape", "portrait", "square"] else "portrait"
            }

            resp = await fetch("GET", url, params=params, headers=headers, use_cache=False)
            if resp.status_code == 200:
                data = resp.json()
                for photo in data.get("photos", []):
                    w = photo.get("width", 0)
                    if w >= min_width:
                        results.append(ImageResult(
                            url=photo.get("src", {}).get("original", ""),
                            width=w,
                            height=photo.get("height", 0),
                            license="Pexels License",
                            attribution=photo.get("photographer", "Unknown"),
                            source_name=self.name,
                            thumb_url=photo.get("src", {}).get("large", "")
                        ))
        except Exception as e:
            logger.warning(f"Pexels search failed: {e}")

        return results[:count]

source = PexelsSource()
