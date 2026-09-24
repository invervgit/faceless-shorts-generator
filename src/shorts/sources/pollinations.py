import logging
import urllib.parse
from typing import List

from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)


class PollinationsSource(ImageSource):
    name = "pollinations"
    requires_key = False
    supports_people = False
    license_type = "generative"

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        """
        Pollinations generates images dynamically. We just formulate the URL.
        """
        results: List[ImageResult] = []
        try:
            w = 1080 if orientation == "portrait" else 1920
            h = 1920 if orientation == "portrait" else 1080
            if orientation == "square":
                w = h = 1080

            # Only return exactly the count requested, bypassing HTTP checks since it generates on the fly
            for i in range(count):
                # add seed variation
                prompt = urllib.parse.quote(query + f" variant {i}")
                url = f"https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&nologo=true"
                
                results.append(ImageResult(
                    url=url,
                    width=w,
                    height=h,
                    license="Generative",
                    attribution="Pollinations.ai",
                    source_name=self.name,
                    thumb_url=url
                ))
        except Exception as e:
            logger.warning(f"Pollinations generation failed: {e}")

        return results

source = PollinationsSource()
