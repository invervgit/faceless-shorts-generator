import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional

from shorts.config import settings

logger = logging.getLogger(__name__)


class DiskCache:
    """A simple file-based cache for HTTP responses and binary files."""

    def __init__(self, cache_dir: Path = settings.cache_dir):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _generate_key(self, namespace: str, key_data: str) -> str:
        """Generates a SHA256 hash for the given namespace and key data."""
        hash_obj = hashlib.sha256(key_data.encode("utf-8"))
        return f"{namespace}_{hash_obj.hexdigest()}"

    def _get_path(self, key: str) -> Path:
        return self.cache_dir / key

    def set(self, namespace: str, key_data: str, content: bytes) -> None:
        """Stores binary content in the cache."""
        key = self._generate_key(namespace, key_data)
        path = self._get_path(key)
        try:
            path.write_bytes(content)
        except OSError as e:
            logger.warning(f"Failed to write to cache path {path}: {e}")

    def get(self, namespace: str, key_data: str) -> Optional[bytes]:
        """Retrieves binary content from the cache."""
        key = self._generate_key(namespace, key_data)
        path = self._get_path(key)
        if path.exists():
            try:
                return path.read_bytes()
            except OSError as e:
                logger.warning(f"Failed to read from cache path {path}: {e}")
        return None

    def set_json(self, namespace: str, key_data: str, data: dict[str, Any]) -> None:
        """Stores a JSON serializable dictionary in the cache."""
        self.set(namespace, key_data, json.dumps(data).encode("utf-8"))

    def get_json(self, namespace: str, key_data: str) -> Optional[dict[str, Any]]:
        """Retrieves a JSON dictionary from the cache."""
        content = self.get(namespace, key_data)
        if content:
            try:
                return json.loads(content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"Failed to decode cached JSON for {key_data}: {e}")
        return None


cache = DiskCache()
