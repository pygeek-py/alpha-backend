import hashlib


def cache_key_for(prefix: str, path: str, params: dict | None = None) -> str:
    """A cache key safe for any Django cache backend (memcached included --
    hence hashing rather than embedding raw punctuation/unicode)."""
    raw_key = f"{path}:{sorted((params or {}).items())}"
    return f"{prefix}:{hashlib.sha256(raw_key.encode()).hexdigest()}"
