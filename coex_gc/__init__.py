"""
Coex Garbage Collector Package

This package implements the handle-based garbage collector for Coex.

GC Design:
- Handle-based indirection (i64 indices into handle table)
- Shadow stack for root discovery
- Mark-sweep with birth-marking
- Mark inversion (alternating 0/1 avoids clearing phase)
- Deferred reclamation for safe handle reuse
- Thread registry for multi-threaded GC support

Package Structure (Modularization Complete):
    coex_gc/
    ├── __init__.py         # Package exports (this file)
    ├── diagnostics.py      # Tracing, heap dumps, validation (GCDiagnostics)
    ├── handles.py          # Handle table management (HandleManager)
    ├── core.py             # Core GC operations (GCCoreGenerator)
    ├── async_gc.py         # Async/concurrent GC (AsyncGCGenerator)
    └── thread_registry.py  # Thread registration, TLS (ThreadRegistryManager)

The GarbageCollector class in coex_gc_original.py coordinates all submodules
using a delegation pattern where submodules declare interfaces and delegate
implementations back to the parent for gradual extraction.
"""

# Main GarbageCollector class
from coex_gc_original import GarbageCollector

# Submodule classes (for direct access if needed)
from coex_gc.diagnostics import GCDiagnostics
from coex_gc.handles import HandleManager
from coex_gc.core import GCCoreGenerator
from coex_gc.async_gc import AsyncGCGenerator
from coex_gc.thread_registry import ThreadRegistryManager

__all__ = [
    'GarbageCollector',
    'GCDiagnostics',
    'HandleManager',
    'GCCoreGenerator',
    'AsyncGCGenerator',
    'ThreadRegistryManager',
]
