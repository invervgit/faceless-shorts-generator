import logging
from typing import List

from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource

logger = logging.getLogger(__name__)

class WikimediaSource(ImageSource):
    name = "wikimedia"
    requires_key = False
    supports_people = True
    license_type = "creative_commons"

    async def search(self, query: str, count: int, orientation: str, min_width: int) -> List[ImageResult]:
        results: List[ImageResult] = []
        
        try:
            # Strategy 1: Wikipedia REST summary for lead image
            results.extend(await self._search_summary(query, min_width))
            
            if len(results) >= count:
                return results[:count]

            # Strategy 2: Category Images (High Quality)
            # Find the Wikipedia page, then its categories, then files in those categories
            cat_results = await self._search_category(query, min_width)
            results.extend(cat_results)
            
            if len(results) >= count:
                return results[:count]

            # Strategy 3: Direct API search with gsrnamespace=6
            search_results = await self._search_api(query, min_width)
            results.extend(search_results)

        except Exception as e:
            logger.warning(f"Wikimedia source failed for query '{query}': {e}")
            
        return results[:count]

    async def _search_summary(self, query: str, min_width: int) -> List[ImageResult]:
        results = []
        summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}"
        
        resp = await fetch("GET", summary_url, use_cache=False)
        if resp.status_code == 200:
            data = resp.json()
            if "originalimage" in data:
                img_data = data["originalimage"]
                width = img_data.get("width", 0)
                if width >= min_width:
                    results.append(ImageResult(
                        url=img_data["source"],
                        width=width,
                        height=img_data.get("height", 0),
                        license="Public Domain / CC",
                        attribution=data.get("title", query),
                        source_name=self.name,
                        thumb_url=data.get("thumbnail", {}).get("source", img_data["source"])
                    ))
        return results

    async def _search_category(self, query: str, min_width: int) -> List[ImageResult]:
        # Oversimplified strategy: attempt to query files directly by standard category naming conventions.
        # Often it's Category:<Person_Name>.
        results = []
        api_url = "https://en.wikipedia.org/w/api.php"
        cat_name = f"Category:{query}"
        
        params = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": cat_name,
            "gcmtype": "file",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|dimensions",
            "iiurlwidth": "1600",
            "format": "json"
        }
        resp = await fetch("GET", api_url, params=params, use_cache=False)
        if resp.status_code == 200:
            results.extend(self._parse_imageinfo(resp.json(), min_width))
        return results

    async def _search_api(self, query: str, min_width: int) -> List[ImageResult]:
        results = []
        api_url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|dimensions",
            "iiurlwidth": "1600",
            "format": "json",
            "gsrlimit": "10"
        }
        resp = await fetch("GET", api_url, params=params, use_cache=False)
        if resp.status_code == 200:
            results.extend(self._parse_imageinfo(resp.json(), min_width))
        return results

    def _parse_imageinfo(self, data: dict, min_width: int) -> List[ImageResult]:
        results = []
        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if "imageinfo" not in page:
                continue
            info = page["imageinfo"][0]
            w = info.get("width", 0)
            if w >= min_width:
                meta = info.get("extmetadata", {})
                artist = meta.get("Artist", {}).get("value", "Unknown")
                license_val = meta.get("LicenseShortName", {}).get("value", "CC")
                
                # HTML stripping for artist
                import re
                artist = re.sub(r'<[^>]+>', '', artist)
                
                results.append(ImageResult(
                    url=info.get("url", ""),
                    width=w,
                    height=info.get("height", 0),
                    license=license_val,
                    attribution=artist.strip(),
                    source_name=self.name,
                    thumb_url=info.get("thumburl", info.get("url", ""))
                ))
        return results

# Expose instance
source = WikimediaSource()
