"""Benchmark harness facade for MiniAgent.

The harness package is the engineering-facing name for evaluation runners.
It currently reuses the benchmark implementation while providing a stable
import path for future task runners, judges, fixtures, and report exporters.
"""

from miniagent_core.benchmark import (
    async_main,
    main,
    run_benchmark,
    run_memory_retrieval_benchmark,
)

__all__ = [
    "async_main",
    "main",
    "run_benchmark",
    "run_memory_retrieval_benchmark",
]

