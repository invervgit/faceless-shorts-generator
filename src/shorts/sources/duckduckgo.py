import logging
import asyncio
from typing import List
from ddgs import DDGS
from shorts.sources.base import ImageSource, ImageResult

logger = logging.getLogger(__name__)

class DuckDuckGoSource(ImageSource):
    name = "duckduckgo"
    requires_key = False
    supports_people = True
    license_type = "Fair Use / Web"

    def _sync_search(self, query: str, count: int) -> List[dict]:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=count * 2):
                results.append(r)
        return results

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        results = []
        try:
            ddg_results = await asyncio.to_thread(self._sync_search, query, count)
                
            for res in ddg_results:
                w = int(res.get("width", 0) or 0)
                h = int(res.get("height", 0) or 0)
                url = res.get("image")
                thumb = res.get("thumbnail")
                
                if not url:
                    continue
                    
                # If we want portrait (for shorts)
                if orientation == "portrait" and w > h and h > 0:
                    continue # Skip pure landscapes if possible, though we can crop them later
                    
                if w < min_width and w > 0:
                    continue
                    
                results.append(ImageResult(
                    url=url,
                    width=w or 1080,
                    height=h or 1920,
                    license=self.license_type,
                    attribution=res.get("source", "DuckDuckGo Image Search"),
                    source_name=self.name,
                    thumb_url=thumb or url
                ))
                
                if len(results) >= count:
                    break
                    
        except Exception as e:
            logger.error(f"DuckDuckGo search failed for '{query}': {e}")
            
        return results
