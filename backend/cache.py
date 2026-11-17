"""Persistent bounded cache with process-local single flight and durable regeneration receipts."""
import asyncio
import time
import weakref
from .storage import root, read_json, atomic_json

LOCKS = weakref.WeakValueDictionary()


async def execute(request, regeneration, producer):
    key = request.fingerprint()
    # Comfy's async nodes execute on one executor event loop.
    lock_key = (id(asyncio.get_running_loop()), key)
    lock = LOCKS.setdefault(lock_key, asyncio.Lock())
    async with lock:
        path = root() / "cache" / (key + ".json")
        entry = read_json(path, {})
        receipts = entry.get("receipts", []) if isinstance(entry, dict) else []
        valid = isinstance(entry, dict) and entry.get("version") == 1 and isinstance(entry.get("result"), dict) and entry["result"].get("text")
        if valid and (not regeneration or regeneration in receipts):
            return {**entry["result"], "cached": True}
        started = time.monotonic()
        result = await producer(request)
        if not result.get("text", "").strip():
            raise ValueError("Empty result cannot be cached")
        result["duration"] = round(time.monotonic() - started, 2)
        if regeneration:
            receipts.append(regeneration)
        atomic_json(path, {"version": 1, "result": result, "receipts": receipts[-256:]})
        files = sorted(path.parent.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for index, file in enumerate(files):
            total += file.stat().st_size
            if index >= 512 or total > 64 * 1024 * 1024:
                file.unlink(missing_ok=True)
        return {**result, "cached": False}
