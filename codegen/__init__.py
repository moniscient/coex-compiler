"""
Coex LLVM Code Generator Package

This package generates LLVM IR from Coex AST.

During modularization, this module re-exports from codegen_original.py
to maintain backward compatibility. As extraction proceeds, the
CodeGenerator class will be refactored to delegate to submodules.

Target structure (post-modularization):
    codegen/
    ├── __init__.py      # CodeGenerator class (this file)
    ├── context.py       # Shared compilation context
    ├── primitives.py    # int, float, bool operations
    ├── strings.py       # String implementation
    ├── json.py          # JSON type support
    ├── collections.py   # List, Array
    ├── hamt.py          # Map, Set (HAMT-based)
    ├── types.py         # User types, generics, traits
    ├── control_flow.py  # if, for, while, match
    ├── expressions.py   # Expression generation
    ├── statements.py    # Statement generation
    ├── matrix.py        # Cellular automata
    ├── posix.py         # POSIX I/O
    ├── modules.py       # Import resolution
    └── atomics.py       # Atomic types, Result
"""

# Re-export CodeGenerator from the original monolithic module
# This will be gradually replaced as extraction proceeds
from codegen_original import CodeGenerator

__all__ = ['CodeGenerator']
