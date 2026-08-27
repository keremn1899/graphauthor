"""Process memory inspection for the operator host.

Ladybug native allocations never appear in Python's heap, so RSS from
``/proc`` is the truth. ``tracemalloc`` covers the Python side. A JSONL
sample file and ``GET /operator/memory`` are how you watch it grow.
``SIGUSR1`` dumps a snapshot without restarting.
"""

from __future__ import annotations

import faulthandler
import gc
import json
import os
import signal
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any

_STARTED = False
_STARTED_AT = 0.0
_LOCK = threading.Lock()
_LOG_PATH: Path | None = None
_SAMPLE_SEC = 10.0


def rss_bytes() -> int:
    try:
        status = Path("/proc/self/status").read_text()
    except OSError:
        return 0
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    return 0


def peak_rss_bytes() -> int:
    try:
        status = Path("/proc/self/status").read_text()
    except OSError:
        return 0
    for line in status.splitlines():
        if line.startswith("VmHWM:"):
            return int(line.split()[1]) * 1024
    return 0


def _mallinfo() -> dict[str, int] | None:
    try:
        import ctypes

        class _mallinfo2(ctypes.Structure):
            _fields_ = [
                ("arena", ctypes.c_size_t),
                ("ordblks", ctypes.c_size_t),
                ("smblks", ctypes.c_size_t),
                ("hblks", ctypes.c_size_t),
                ("hblkhd", ctypes.c_size_t),
                ("usmblks", ctypes.c_size_t),
                ("fsmblks", ctypes.c_size_t),
                ("uordblks", ctypes.c_size_t),
                ("fordblks", ctypes.c_size_t),
                ("keepcost", ctypes.c_size_t),
            ]

        libc = ctypes.CDLL("libc.so.6")
        libc.mallinfo2.restype = _mallinfo2
        info = libc.mallinfo2()
        return {
            "arena": int(info.arena),
            "mmap_bytes": int(info.hblkhd),
            "allocated": int(info.uordblks),
            "free": int(info.fordblks),
        }
    except Exception:
        return None


def _ladybug_opens() -> int:
    try:
        import graph_read

        return int(getattr(graph_read, "open_count", 0))
    except Exception:
        return 0


def snapshot(*, stacks: int = 12) -> dict[str, Any]:
    current, peak = (0, 0)
    top: list[dict[str, Any]] = []
    tracing = tracemalloc.is_tracing()
    if tracing:
        current, peak = tracemalloc.get_traced_memory()
        if stacks:
            stats = tracemalloc.take_snapshot().statistics("traceback")[:stacks]
            for item in stats:
                frame = item.traceback[0] if item.traceback else None
                top.append(
                    {
                        "size": int(item.size),
                        "count": int(item.count),
                        "file": getattr(frame, "filename", "") if frame else "",
                        "line": getattr(frame, "lineno", 0) if frame else 0,
                    }
                )
    return {
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _STARTED_AT, 1) if _STARTED_AT else 0,
        "rss_bytes": rss_bytes(),
        "peak_rss_bytes": peak_rss_bytes(),
        "python_traced_bytes": int(current),
        "python_peak_bytes": int(peak),
        "tracing": tracing,
        "gc": list(gc.get_count()),
        "ladybug_opens": _ladybug_opens(),
        "malloc": _mallinfo(),
        "python_top": top,
        "log": str(_LOG_PATH) if _LOG_PATH else "",
        "ts": time.time(),
    }


def dump(path: Path | None = None) -> Path:
    dest = path or (_LOG_PATH.with_suffix(".snapshot.json") if _LOG_PATH else Path("memory-snapshot.json"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(snapshot(), indent=2), encoding="utf-8")
    return dest


def _append_sample(row: dict[str, Any]) -> None:
    if _LOG_PATH is None:
        return
    slim = {
        "ts": row["ts"],
        "rss_bytes": row["rss_bytes"],
        "peak_rss_bytes": row["peak_rss_bytes"],
        "python_traced_bytes": row["python_traced_bytes"],
        "ladybug_opens": row["ladybug_opens"],
        "malloc": row.get("malloc"),
    }
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(slim) + "\n")


def _sample_loop() -> None:
    while True:
        time.sleep(_SAMPLE_SEC)
        try:
            row = snapshot(stacks=0)
            _append_sample(row)
            rss_mb = row["rss_bytes"] / (1024 * 1024)
            print(
                f"[memory] rss={rss_mb:.1f}MiB python={row['python_traced_bytes'] / (1024 * 1024):.1f}MiB "
                f"ladybug_opens={row['ladybug_opens']}",
                flush=True,
            )
        except Exception as exc:
            print(f"[memory] sample failed: {exc}", flush=True)


def _on_usr1(_signum, _frame) -> None:
    try:
        path = dump()
        print(f"[memory] dumped {path}", flush=True)
    except Exception as exc:
        print(f"[memory] dump failed: {exc}", flush=True)


def start(*, log_path: Path | str | None = None, sample_s: float | None = None) -> None:
    """Begin tracing. Idempotent. Off when ``SST_MEMORY_TRACE=0``."""
    global _STARTED, _STARTED_AT, _LOG_PATH, _SAMPLE_SEC
    flag = os.environ.get("SST_MEMORY_TRACE", "1").strip().lower()
    if flag in ("0", "false", "no"):
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
        _STARTED_AT = time.time()
        if sample_s is not None:
            _SAMPLE_SEC = sample_s
        else:
            _SAMPLE_SEC = float(os.environ.get("SST_MEMORY_SAMPLE_S", "10") or 10)
        _LOG_PATH = Path(log_path) if log_path else Path(
            os.environ.get("SST_MEMORY_LOG", "data/runtime/memory-trace.jsonl")
        )
        faulthandler.enable(all_threads=True)
        if not tracemalloc.is_tracing():
            tracemalloc.start(25)
        try:
            signal.signal(signal.SIGUSR1, _on_usr1)
        except (ValueError, OSError):
            pass
        thread = threading.Thread(target=_sample_loop, name="memory-trace", daemon=True)
        thread.start()
        row = snapshot(stacks=0)
        _append_sample(row)
        print(
            f"[memory] tracing pid={os.getpid()} log={_LOG_PATH} "
            f"(GET /operator/memory, SIGUSR1 dumps a snapshot)",
            flush=True,
        )
