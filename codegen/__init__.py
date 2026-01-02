"""
Coex LLVM Code Generator Package

This package generates LLVM IR from Coex AST.

Package Structure (Modularization Complete):
    codegen/
    ├── __init__.py      # Package exports (this file)
    ├── strings.py       # String type implementation (StringGenerator)
    ├── json.py          # JSON type support (JSONGenerator)
    ├── collections.py   # List, Array types (CollectionsGenerator)
    ├── hamt.py          # Map, Set HAMT-based (HAMTGenerator)
    ├── types.py         # Type system utilities (TypesGenerator)
    ├── expressions.py   # Expression code generation (ExpressionsGenerator)
    ├── statements.py    # Statement code generation (StatementsGenerator)
    ├── matrix.py        # Cellular automata (MatrixGenerator)
    ├── posix.py         # POSIX I/O operations (PosixGenerator)
    ├── modules.py       # Module/import system (ModulesGenerator)
    └── atomics.py       # Atomic types (AtomicsGenerator)

The CodeGenerator class in codegen_original.py coordinates all submodules
using a delegation pattern where submodules declare interfaces and delegate
implementations back to the parent for gradual extraction.
"""

# Main CodeGenerator class
from codegen_original import CodeGenerator

# Submodule generators (for direct access if needed)
from codegen.strings import StringGenerator
from codegen.json import JSONGenerator
from codegen.collections import CollectionsGenerator
from codegen.hamt import HAMTGenerator
from codegen.types import TypesGenerator
from codegen.expressions import ExpressionsGenerator
from codegen.statements import StatementsGenerator
from codegen.matrix import MatrixGenerator
from codegen.posix import PosixGenerator
from codegen.modules import ModulesGenerator
from codegen.atomics import AtomicsGenerator

__all__ = [
    'CodeGenerator',
    'StringGenerator',
    'JSONGenerator',
    'CollectionsGenerator',
    'HAMTGenerator',
    'TypesGenerator',
    'ExpressionsGenerator',
    'StatementsGenerator',
    'MatrixGenerator',
    'PosixGenerator',
    'ModulesGenerator',
    'AtomicsGenerator',
]
