from __future__ import annotations

import os
import resource
from pathlib import Path

from .config import Settings


def enforce_resource_governance(settings: Settings) -> dict[str, str | int]:
    applied: dict[str, str | int] = {}
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = min(max(soft, settings.fd_soft_limit), hard)
    resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))
    applied["nofile_soft"] = target
    if settings.oom_score_adj is not None:
        oom_path = Path("/proc/self/oom_score_adj")
        if oom_path.exists() and os.access(oom_path, os.W_OK):
            oom_path.write_text(str(settings.oom_score_adj))
            applied["oom_score_adj"] = settings.oom_score_adj
    return applied


def mem_available_kb() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1])
    except FileNotFoundError:
        pass
    return 10**12
