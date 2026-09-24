import asyncio
import io
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import imagehash
from PIL import Image

from shorts.config import settings
from shorts.http import fetch
from shorts.sources.base import ImageResult, ImageSource
from shorts.sources.openverse import source as openverse_source
from shorts.sources.pexels import source as pexels_source
from shorts.sources.pixabay import source as pixabay_source
from shorts.sources.pollinations import source as pollinations_source
from shorts.sources.unsplash import source as unsplash_source
from shorts.sources.wikimedia import source as wikimedia_source
from shorts.sources.duckduckgo import DuckDuckGoSource

duckduckgo_source = DuckDuckGoSource()

logger = logging.getLogger(__name__)

class CircuitBreaker:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS source_health (
                source TEXT PRIMARY KEY,
                consecutive_failures INTEGER DEFAULT 0,
                last_success REAL DEFAULT 0,
                latency REAL DEFAULT 0,
                skip_until REAL DEFAULT 0
            )
        ''')
        self.conn.commit()

    def should_skip(self, source: str) -> bool:
        cur = self.conn.execute("SELECT skip_until FROM source_health WHERE source = ?", (source,))
        row = cur.fetchone()
        if row and row[0] > time.time():
            return True
        return False

    def record_success(self, source: str, latency: float):
        cur = self.conn.execute("SELECT latency FROM source_health WHERE source = ?", (source,))
        row = cur.fetchone()
        new_latency = latency
        if row and row[0] > 0:
            # Exponential moving average for latency
            new_latency = 0.8 * row[0] + 0.2 * latency

        self.conn.execute('''
            INSERT INTO source_health (source, consecutive_failures, last_success, latency, skip_until)
            VALUES (?, 0, ?, ?, 0)
            ON CONFLICT(source) DO UPDATE SET
                consecutive_failures = 0,
                last_success = excluded.last_success,
                latency = excluded.latency,
                skip_until = 0
        ''', (source, time.time(), new_latency))
        self.conn.commit()

    def record_failure(self, source: str):
        cur = self.conn.execute("SELECT consecutive_failures FROM source_health WHERE source = ?", (source,))
        row = cur.fetchone()
        failures = (row[0] if row else 0) + 1
        
        skip_until = 0
        if failures >= 3:
            skip_until = time.time() + 900  # 15 minutes
            logger.warning(f"Circuit breaker OPENED for {source}. Skipping for 15 minutes.")

        self.conn.execute('''
            INSERT INTO source_health (source, consecutive_failures, skip_until)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                consecutive_failures = excluded.consecutive_failures,
                skip_until = excluded.skip_until
        ''', (source, failures, skip_until))
        self.conn.commit()


class SourceRegistry:
    def __init__(self):
        # Init circuit breaker in the cache directory
        db_path = settings.cache_dir / "circuit_breaker.sqlite"
        self.breaker = CircuitBreaker(db_path)
        
        self.person_cascade = [
            duckduckgo_source,
            wikimedia_source,
            openverse_source,
            # broadened wikimedia logic can be handled at the source level or injected as a lambda
        ]
        
        self.generic_cascade = [
            duckduckgo_source,
            pexels_source,
            pixabay_source,
            unsplash_source,
            openverse_source,
            pollinations_source,
        ]

    async def _compute_phash(self, url: str) -> Optional[str]:
        try:
            resp = await fetch("GET", url, use_cache=True)
            if resp.status_code == 200:
                img = Image.open(io.BytesIO(resp.content))
                return str(imagehash.phash(img))
        except Exception:
            pass
        return None

    def _is_quality_ratio(self, width: int, height: int) -> bool:
        if width == 0 or height == 0:
            return True # Generative or unknown, assume ok
            
        # We want a 9:16 (0.5625) video. 
        # Calculate max crop percentage.
        ratio = width / height
        
        if ratio > 0.5625:
            # Wider than 9:16. We crop width.
            target_width = height * (9 / 16)
            crop_pct = (width - target_width) / width
        else:
            # Taller than 9:16. We crop height.
            target_height = width * (16 / 9)
            crop_pct = (height - target_height) / height
            
        return crop_pct <= 0.40

    async def fetch_images(
        self, 
        query: str, 
        subject_type: str, 
        count: int = 1, 
        orientation: str = "portrait", 
        min_width: int = 720
    ) -> List[ImageResult]:
        
        cascade = self.person_cascade if subject_type == "person" else self.generic_cascade
        
        collected: List[ImageResult] = []
        seen_hashes: Set[str] = set()

        for source in cascade:
            if len(collected) >= count:
                break
                
            if self.breaker.should_skip(source.name):
                logger.info(f"Skipping {source.name} due to open circuit breaker.")
                continue
                
            start_time = time.time()
            try:
                # Fetch more than needed to allow for deduplication & quality filtering
                raw_results = await source.cached_search(query, count=count*2, orientation=orientation, min_width=min_width)
                
                valid_new = []
                for res in raw_results:
                    if len(collected) + len(valid_new) >= count:
                        break
                        
                    # Quality Filter: reject bad aspect ratios
                    if not self._is_quality_ratio(res.width, res.height):
                        continue
                        
                    # Perceptual hash deduplication
                    phash = await self._compute_phash(res.thumb_url)
                    if phash:
                        if phash in seen_hashes:
                            continue
                        seen_hashes.add(phash)
                        
                    valid_new.append(res)

                if valid_new:
                    self.breaker.record_success(source.name, time.time() - start_time)
                    collected.extend(valid_new)
                else:
                    # If it returned nothing or all were filtered, we can treat it as a soft failure or just empty.
                    # We only record true exception-based failures for circuit breaker, or if completely empty consistently.
                    # For safety, an empty result doesn't necessarily mean the API is down, just no matches.
                    pass

            except Exception as e:
                logger.error(f"Source {source.name} raised unexpected error: {e}")
                self.breaker.record_failure(source.name)

        return collected

    def generate_manifest(self, images: List[ImageResult], output_path: Path):
        """Emits a manifest.json tracking attribution and licenses for all collected images."""
        manifest = []
        for img in images:
            manifest.append({
                "source": img.source_name,
                "url": img.url,
                "attribution": img.attribution,
                "license": img.license
            })
            
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

# Global registry instance
registry = SourceRegistry()
