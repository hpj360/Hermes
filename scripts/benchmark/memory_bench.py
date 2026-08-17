"""M4 记忆层 A/B 基准脚本（P0-3）。

用法（在 hermes 仓根目录）::

    python scripts/benchmark/memory_bench.py [--queries PATH] [--backend local_rrf|mem0]
        [--limit N] [--seed SEED]

跑三路对比（需 mem0 已安装并配置 HERMES_MEMORY_BACKEND=mem0）::

    python scripts/benchmark/memory_bench.py --backend local_rrf
    python scripts/benchmark/memory_bench.py --backend mem0

输出 recall@K / MRR / p50 / p95 检索延迟，以及（仅 mem0）每条 episode 的索引
调用次数。recall 判定：某 episode 的 summary 命中 query 的任一 ``answer_keywords``
即视为相关。

纯 stdlib，不依赖 mem0 也能跑 local_rrf 基线。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))


def load_corpus(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert isinstance(data.get("episodes"), list)
    assert isinstance(data.get("queries"), list)
    return data


def build_memory(backend: str, state_dir: Path) -> Any:
    from hermes.workbench.memory import MemoryService

    svc = MemoryService(state_dir=state_dir)
    if backend == "mem0":
        from hermes.workbench.mem0_adapter import Mem0Backend, Mem0BackendConfig

        svc.set_backend(Mem0Backend(memory=svc, state_dir=state_dir, config=Mem0BackendConfig()))
    return svc


def is_relevant(summary: str, keywords: list[str]) -> bool:
    low = summary.lower()
    return any(k.lower() in low for k in keywords)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4 memory A/B benchmark")
    parser.add_argument("--queries", default=str(REPO_ROOT / "scripts" / "benchmark" / "memory_queries.json"))
    parser.add_argument("--backend", default="local_rrf", choices=["local_rrf", "mem0"])
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    corpus = load_corpus(Path(args.queries))
    state_dir = REPO_ROOT / ".cache" / "memory-bench"
    state_dir.mkdir(parents=True, exist_ok=True)

    svc = build_memory(args.backend, state_dir)

    from hermes.workbench.memory import make_episode

    episodes = []
    for item in corpus["episodes"]:
        ep = make_episode(item["kind"], item["summary"])
        svc.record_episode(ep)
        episodes.append(ep)
    if args.backend == "mem0":
        svc.rebuild_backend()

    recalls: list[float] = []
    rr: list[float] = []
    latencies: list[float] = []
    for q in corpus["queries"]:
        keywords = q.get("answer_keywords", [])
        t0 = time.perf_counter()
        results = svc.search_episodes_rrf(q["query"], limit=args.limit)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        returned = [ep.summary for ep, _ in results]
        hit = any(is_relevant(s, keywords) for s in returned)
        recalls.append(1.0 if hit else 0.0)
        # MRR: reciprocal rank of the first relevant episode
        rank = next(
            (i + 1 for i, s in enumerate(returned) if is_relevant(s, keywords)), None
        )
        rr.append(1.0 / rank if rank else 0.0)

    n = len(recalls)
    print(f"backend          : {args.backend}")
    print(f"episodes         : {len(episodes)}")
    print(f"queries          : {n}")
    print(f"recall@{args.limit}      : {sum(recalls) / n:.3f}")
    print(f"MRR              : {sum(rr) / n:.3f}")
    print(f"latency p50 (ms) : {percentile(latencies, 0.50):.2f}")
    print(f"latency p95 (ms) : {percentile(latencies, 0.95):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
