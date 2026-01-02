"""
Coex Garbage Collector Package

This package implements the handle-based garbage collector for Coex.

The GC uses:
- Handle-based indirection (i64 indices into handle table)
- Shadow stack for root discovery
- Mark-sweep with birth-marking
- Mark inversion (alternating 0/1 avoids clearing phase)
- Deferred reclamation for safe handle reuse

During modularization, this module re-exports from coex_gc_original.py
to maintain backward compatibility. As extraction proceeds, the
GarbageCollector class will be refactored to delegate to submodules.

Target structure (post-modularization):
    coex_gc/
    ├── __init__.py       # GarbageCollector class (this file)
    ├── core.py           # Mark-sweep algorithm
    ├── handles.py        # Handle table management
    ├── shadow_stack.py   # Root discovery, frame management
    ├── diagnostics.py    # Tracing, heap dumps, validation
    └── async_gc.py       # Concurrent GC support (future)
"""

# Re-export GarbageCollector from the original monolithic module
# This will be gradually replaced as extraction proceeds
from coex_gc_original import GarbageCollector

__all__ = ['GarbageCollector']
