"""
A1 — LangGraph orchestrator.

Backward-compatibility shim. Implementation lives in orchestrator/.
"""
from ..orchestrator import build_graph, run

__all__ = ["build_graph", "run"]
