"""In-memory response caching and rolling statistics for System 1 MCP."""

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from system1_mcp.config import get_config_dir, load_config


class ResponseCache:
    """Thread-safe, bounded, in-memory cache with TTL and file-backed statistics."""

    def __init__(self, ttl_seconds: Optional[float] = None, maxsize: int = 1000):
        self.maxsize = maxsize
        self._default_ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: OrderedDict[str, Tuple[float, Dict[str, Any]]] = OrderedDict()

        # Initialize rolling counters from file if available
        stats = get_cache_stats()
        self._hits = int(stats.get("hits", 0))
        self._misses = int(stats.get("misses", 0))
        self._last_persisted: float = 0.0
        self._persist_interval: float = 1.0

    @property
    def default_ttl(self) -> float:
        if self._default_ttl is not None:
            return float(self._default_ttl)
        try:
            return float(load_config().cache_ttl_seconds)
        except Exception:
            return 300.0

    def compute_key(
        self,
        tool: str,
        inputs: Dict[str, Any],
        model: str,
        thresholds: Dict[str, Any],
    ) -> str:
        """Compute canonical SHA-256 cache key from tool, inputs, model, and thresholds."""
        canonical = {
            "inputs": inputs,
            "model": model,
            "thresholds": thresholds,
            "tool": tool,
        }
        # sort_keys ensures identical JSON representation regardless of dict insertion order
        canonical_str = json.dumps(canonical, sort_keys=True)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve entry from cache. Returns None on miss or expiration."""
        with self._lock:
            if key not in self._store:
                self._misses += 1
                self._persist_stats()
                return None

            expires_at, value = self._store[key]
            now = time.time()
            if now > expires_at:
                del self._store[key]
                self._misses += 1
                self._persist_stats()
                return None

            # Cache hit: mark as recently used
            self._hits += 1
            self._store.move_to_end(key)
            self._persist_stats()

            result = deepcopy(value)
            result["cache_hit"] = True
            return result

    def set(
        self,
        key: str,
        value: Dict[str, Any],
        ttl_seconds: Optional[float] = None,
    ) -> None:
        """Store entry in cache with TTL and bounded eviction."""
        with self._lock:
            if key in self._store:
                del self._store[key]
            elif len(self._store) >= self.maxsize:
                now = time.time()
                expired = [k for k, (exp, _) in self._store.items() if now > exp]
                for k in expired:
                    del self._store[k]
                if len(self._store) >= self.maxsize:
                    self._store.popitem(last=False)

            ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
            expires_at = time.time() + ttl

            # Save clean copy without cache_hit flag
            to_store = deepcopy(value)
            to_store.pop("cache_hit", None)
            self._store[key] = (expires_at, to_store)

    def clear(self) -> None:
        """Clear all in-memory cache entries."""
        with self._lock:
            self._store.clear()

    def reset_stats(self) -> None:
        """Reset hit and miss counters in-memory and on disk."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._persist_stats(force=True)

    def flush_stats(self) -> None:
        """Immediately flush rolling counters to disk."""
        with self._lock:
            self._persist_stats(force=True)

    def stats(self) -> Dict[str, Any]:
        """Return current statistics."""
        with self._lock:
            total = self._hits + self._misses
            hit_ratio = (self._hits / total * 100.0) if total > 0 else 0.0
            return {
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 2),
                "size": len(self._store),
            }

    def _persist_stats(self, force: bool = False) -> None:
        """Write rolling hit/miss counters to ~/.system1/cache_stats.json atomically (batched)."""
        now = time.time()
        if not force and (now - self._last_persisted < self._persist_interval):
            return
        self._last_persisted = now
        try:
            config_dir = get_config_dir()
            config_dir.mkdir(parents=True, exist_ok=True)
            stats_path = config_dir / "cache_stats.json"
            payload = {
                "hits": self._hits,
                "misses": self._misses,
                "last_updated": now,
            }
            tmp_path = stats_path.with_suffix(f".tmp_{os.getpid()}")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            tmp_path.replace(stats_path)
        except Exception:
            pass


def get_cache_stats() -> Dict[str, Any]:
    """Read rolling cache statistics from file system for cross-process doctor reporting."""
    stats_path = get_config_dir() / "cache_stats.json"
    if stats_path.exists():
        try:
            with open(stats_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {"hits": 0, "misses": 0}


def reset_cache_stats() -> None:
    """Clear the persistent cache stats file."""
    stats_path = get_config_dir() / "cache_stats.json"
    try:
        if stats_path.exists():
            stats_path.unlink()
    except Exception:
        pass
    if _GLOBAL_CACHE is not None:
        _GLOBAL_CACHE.reset_stats()


_GLOBAL_CACHE: Optional[ResponseCache] = None
_CACHE_LOCK = threading.Lock()


def get_cache() -> ResponseCache:
    """Get or initialize singleton ResponseCache."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        with _CACHE_LOCK:
            if _GLOBAL_CACHE is None:
                _GLOBAL_CACHE = ResponseCache()
    return _GLOBAL_CACHE


def set_cache(cache: Optional[ResponseCache]) -> None:
    """Override singleton cache (primarily for tests)."""
    global _GLOBAL_CACHE
    with _CACHE_LOCK:
        _GLOBAL_CACHE = cache


def clear_cache() -> None:
    """Clear entries from singleton cache."""
    cache = get_cache()
    cache.clear()
