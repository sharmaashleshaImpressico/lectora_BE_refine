"""Backward-compatibility shim for OutputWriter."""

from ..output_writer import OutputWriter, failed_end, persist_output, stopped_end

__all__ = ["OutputWriter", "failed_end", "persist_output", "stopped_end"]
