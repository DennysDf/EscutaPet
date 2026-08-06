from __future__ import annotations

import time
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from app.services.cache import cache_json, redis_status


started = time.perf_counter()
value = cache_json("self-test", lambda: {"fallback": True}, ttl=2)
elapsed = time.perf_counter() - started

assert value == {"fallback": True}
assert elapsed < 1.0, "O fallback sem Redis ficou lento demais."
status = redis_status()
assert set(status) == {"enabled", "online", "error"}

print(f"OK - Redis opcional e fallback validados em {elapsed:.3f}s; online={status['online']}.")
