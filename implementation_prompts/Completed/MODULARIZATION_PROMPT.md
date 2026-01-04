# Coex Compiler Modularization Prompt

## Purpose

This prompt guides the safe, incremental decomposition of the Coex compiler's monolithic `codegen.py` (approximately 19,700 lines) into a well-organized package structure. The goal is to create modules small enough for effective work with Claude Code while maintaining full test coverage throughout the migration.

---

## Phase 0: Architecture Documentation (Do This First)

Before any code changes, create `ARCHITECTURE.md` at the project root. This document serves as the authoritative reference for the codebase structure and must be updated as modularization proceeds.

### Task: Create ARCHITECTURE.md

Create a file named `ARCHITECTURE.md` in the project root with the following structure:

```markdown
# Coex Compiler Architecture

## Overview

The Coex compiler transforms `.coex` source files into native executables through ANTLR4 parsing, AST construction, LLVM IR generation, and clang linking.

## Build and Test

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests (156 currently passing)
python3 -m pytest tests/ -v --tb=short

# Run specific test file
python3 -m pytest tests/test_types.py -v

# Compile a program
python3 coexc.py source.coex -o output

# Regenerate parser from grammar
antlr -Dlanguage=Python3 -visitor CoexLexer.g4 CoexParser.g4
```

## Directory Structure

```
coex/
├── ARCHITECTURE.md          # This file
├── CLAUDE.md                # Claude Code directives
├── README.md                # User-facing documentation
├── requirements.txt         # Python dependencies
├── Makefile                 # Common development commands
├── pytest.ini               # Test configuration
│
├── CoexLexer.g4             # ANTLR4 lexer grammar
├── CoexParser.g4            # ANTLR4 parser grammar
├── CoexLexer.py             # Generated lexer
├── CoexParser.py            # Generated parser
├── CoexParserVisitor.py     # Generated visitor base
│
├── coexc.py                 # CLI entry point
├── ast_nodes.py             # AST node dataclasses
├── ast_builder.py           # Parse tree → AST conversion
│
├── codegen/                 # LLVM IR generation package (target structure)
│   ├── __init__.py          # CodeGenerator class, public interface
│   ├── context.py           # Shared compilation context
│   ├── primitives.py        # int, float, bool, string operations
│   ├── collections.py       # List, Map, Set, Array (HAMT-based)
│   ├── types.py             # User-defined types, enums, methods
│   ├── generics.py          # Monomorphization, type substitution
│   ├── traits.py            # Trait checking, structural typing
│   ├── control_flow.py      # if, for, while, match, break, continue
│   ├── functions.py         # Function declaration, calls, lambdas
│   ├── expressions.py       # Expression generation
│   ├── statements.py        # Statement generation
│   ├── matrix.py            # Cellular automata, double-buffering
│   ├── ffi.py               # Extern functions, CXZ libraries
│   └── modules.py           # Import resolution, replace/with
│
├── gc/                      # Garbage collector package (target structure)
│   ├── __init__.py          # GarbageCollector class, public interface
│   ├── core.py              # Heap management, allocation
│   ├── handles.py           # Handle table, indirection
│   ├── shadow_stack.py      # Root discovery, frame management
│   ├── marking.py           # Mark phase, HAMT traversal
│   ├── sweeping.py          # Sweep phase, reclamation
│   └── diagnostics.py       # Tracing, heap dumps, validation
│
├── lib/                     # Standard library modules
│   └── math.coex            # Math utilities
│
└── tests/                   # Test suite
    ├── conftest.py          # Pytest fixtures
    ├── test_basic.py        # Primitives, arithmetic, variables
    ├── test_types.py        # User types, enums, generics
    ├── test_advanced.py     # Traits, matrix, collections
    ├── test_modules.py      # Import system
    └── test_stress_*.py     # Large-scale tests
```

## Module Dependency Graph

```
coexc.py (entry point)
    │
    ├── ast_builder.py ← CoexParser (ANTLR generated)
    │       │
    │       └── ast_nodes.py
    │
    └── codegen/ ──────────────────────────────────────┐
            │                                          │
            ├── context.py (shared state)              │
            │       │                                  │
            ├── primitives.py                          │
            ├── collections.py ← gc/                   │
            ├── types.py                               │
            ├── generics.py ← types.py, traits.py      │
            ├── traits.py                              │
            ├── control_flow.py                        │
            ├── functions.py ← expressions.py          │
            ├── expressions.py ← primitives.py         │
            ├── statements.py ← expressions.py         │
            ├── matrix.py                              │
            ├── ffi.py                                 │
            └── modules.py                             │
                                                       │
            gc/ ←──────────────────────────────────────┘
            ├── core.py
            ├── handles.py
            ├── shadow_stack.py
            ├── marking.py
            ├── sweeping.py
            └── diagnostics.py
```

## Current State

**Pre-modularization:** The compiler currently uses a monolithic structure:
- `codegen.py` (~19,700 lines) - All code generation
- `coex_gc.py` (~4,300 lines) - All garbage collection

**Modularization status:** [Update this section as work proceeds]
- [ ] Phase 1: Create codegen package structure
- [ ] Phase 2: Extract context and primitives
- [ ] Phase 3: Extract collections
- [ ] Phase 4: Extract types and generics
- [ ] Phase 5: Extract control flow and functions
- [ ] Phase 6: Extract matrix, FFI, modules
- [ ] Phase 7: Modularize garbage collector
- [ ] Phase 8: Final cleanup and documentation

## Key Abstractions

### CodeGenerator (codegen/__init__.py)
The main class orchestrating compilation. Maintains:
- `module`: LLVM Module being built
- `builder`: Current IRBuilder
- `locals`: Variable symbol table (name → AllocaInst)
- `functions`: Function symbol table (name → Function)
- `type_registry`: User type LLVM representations
- `gc`: GarbageCollector instance

### GarbageCollector (gc/__init__.py)
Manages memory with handle-based indirection:
- 32-byte object headers: {size, type_id, flags, forward}
- Shadow stack for root discovery
- Mark-sweep collection with birth marking
- Type registry for precise tracing

### AST Nodes (ast_nodes.py)
Dataclasses representing the abstract syntax tree:
- Types: PrimitiveType, ListType, MapType, NamedType, etc.
- Expressions: BinaryExpr, CallExpr, MethodCallExpr, etc.
- Statements: VarDecl, Assignment, IfStmt, ForStmt, etc.
- Declarations: FunctionDecl, TypeDecl, TraitDecl, MatrixDecl

## Testing Strategy

All tests must pass after each extraction step. Run:
```bash
python3 -m pytest tests/ -v --tb=short
```

Current test count: 156 passing tests

Test categories:
- `test_basic.py`: Core language features
- `test_types.py`: Type system, enums, generics
- `test_advanced.py`: Traits, matrix, collections, lambdas
- `test_modules.py`: Import system
- `test_stress_*.py`: Large-scale correctness (skip on CI)

## Contributing

When modifying the compiler:
1. Write a failing test first
2. Make the minimal change to pass
3. Run full test suite before committing
4. Update ARCHITECTURE.md if structure changes
```

---

## Phase 1: Create Package Structure

### Task: Establish the codegen package skeleton

Create the directory structure without moving any code yet. This ensures imports work before extraction begins.

```bash
mkdir -p codegen
mkdir -p gc
```

Create `codegen/__init__.py`:

```python
"""
Coex LLVM Code Generator

This package generates LLVM IR from Coex AST.
During modularization, the original codegen.py is imported here
to maintain backward compatibility.
"""

# During migration, re-export everything from the original module
# This will be replaced incrementally as extraction proceeds
from codegen_original import CodeGenerator

__all__ = ['CodeGenerator']
```

Create `codegen/context.py` (empty placeholder):

```python
"""
Shared compilation context for code generation.

This module will contain:
- CompilationContext: Shared state passed between generators
- Type conversion utilities
- LLVM type helpers
"""

# Placeholder - will be populated during extraction
pass
```

Rename `codegen.py` to `codegen_original.py` temporarily.

**Verify:** Run `python3 -m pytest tests/ -v --tb=short` - all tests must pass.

---

## Phase 2: Extract Compilation Context

### Task: Create the shared context infrastructure

The context module provides the shared state that all code generation modules need access to. This must be extracted first because other modules depend on it.

Create `codegen/context.py` with:

```python
"""
Shared compilation context for code generation.

Provides CompilationContext which holds all mutable state needed
during code generation, passed to subsystem generators.
"""

from llvmlite import ir
from typing import Dict, Optional, List as PyList, Tuple, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from gc import GarbageCollector
    from ast_nodes import Type, TypeDecl, TraitDecl, FunctionDecl


@dataclass
class CompilationContext:
    """
    Shared state for code generation.
    
    Passed to all generator subsystems to provide access to:
    - LLVM module and current builder
    - Symbol tables for variables, functions, types
    - Type metadata for generics and traits
    - Garbage collector instance
    """
    
    # LLVM infrastructure
    module: ir.Module
    builder: Optional[ir.IRBuilder] = None
    
    # Symbol tables
    locals: Dict[str, ir.AllocaInst] = field(default_factory=dict)
    functions: Dict[str, ir.Function] = field(default_factory=dict)
    
    # Type system
    type_registry: Dict[str, ir.Type] = field(default_factory=dict)
    type_fields: Dict[str, PyList[Tuple[str, 'Type']]] = field(default_factory=dict)
    type_methods: Dict[str, Dict[str, str]] = field(default_factory=dict)
    type_decls: Dict[str, 'TypeDecl'] = field(default_factory=dict)
    
    # Generics
    generic_types: Dict[str, 'TypeDecl'] = field(default_factory=dict)
    type_substitutions: Dict[str, 'Type'] = field(default_factory=dict)
    
    # Traits
    traits: Dict[str, 'TraitDecl'] = field(default_factory=dict)
    type_implements: Dict[str, PyList[str]] = field(default_factory=dict)
    
    # Function tracking
    func_decls: Dict[str, 'FunctionDecl'] = field(default_factory=dict)
    current_function: Optional[ir.Function] = None
    current_func_decl: Optional['FunctionDecl'] = None
    
    # Garbage collector
    gc: Optional['GarbageCollector'] = None
    
    # Common LLVM types (populated on init)
    i1: ir.Type = None
    i8: ir.Type = None
    i32: ir.Type = None
    i64: ir.Type = None
    f64: ir.Type = None
    void: ir.Type = None
    i8_ptr: ir.Type = None
    
    def __post_init__(self):
        """Initialize common LLVM types."""
        self.i1 = ir.IntType(1)
        self.i8 = ir.IntType(8)
        self.i32 = ir.IntType(32)
        self.i64 = ir.IntType(64)
        self.f64 = ir.DoubleType()
        self.void = ir.VoidType()
        self.i8_ptr = self.i8.as_pointer()
```

**Do not modify codegen_original.py yet.** This context will be used incrementally.

**Verify:** Tests still pass.

---

## Phase 3: Extract Primitives

### Task: Extract primitive type operations

Create `codegen/primitives.py` containing integer, float, boolean, and basic string operations.

**Extraction criteria:** Look for methods in codegen_original.py that:
- Generate arithmetic operations (+, -, *, /, %)
- Generate comparison operations (==, !=, <, >, <=, >=)
- Generate boolean operations (and, or, not)
- Handle primitive type conversions
- Generate string literals

**Pattern for extraction:**

1. Identify the methods to extract (e.g., `_generate_binary_expr` for arithmetic)
2. Copy them to the new module as standalone functions or a class
3. Add context parameter to each function
4. In codegen_original.py, replace method bodies with delegation calls
5. Run tests after each method migration

Example delegation pattern:

```python
# In codegen_original.py, after extraction:
from codegen.primitives import generate_add, generate_sub, ...

class CodeGenerator:
    def _generate_add(self, left, right):
        return generate_add(self._get_context(), left, right)
```

**Target size:** ~800-1200 lines

**Verify:** Run full test suite after extraction.

---

## Phase 4: Extract Collections

### Task: Extract List, Map, Set, Array implementations

Create `codegen/collections.py` containing the HAMT-based persistent data structure implementations.

**Extraction criteria:** Look for:
- `_create_list_helpers` and related List methods
- `_create_map_helpers` and related Map methods  
- `_create_set_helpers` and related Set methods
- `_create_array_helpers` and related Array methods
- HAMT node operations (PVNode)
- Collection method dispatch

**Dependencies:** This module will need:
- Context for LLVM types and builder
- GC for allocation
- Primitives for element operations

**Target size:** ~2500-3500 lines (this is a large subsystem)

**Verify:** Run full test suite, especially `test_advanced.py` and `test_stress_collections.py`.

---

## Phase 5: Extract Types and Generics

### Task: Extract user-defined type handling

Create `codegen/types.py` for:
- `_register_type` and `_register_concrete_type`
- `_register_enum_type`
- Field access generation
- Constructor generation
- Method dispatch infrastructure

Create `codegen/generics.py` for:
- `_monomorphize_type`
- Type substitution logic
- Type argument inference

Create `codegen/traits.py` for:
- `_register_trait`
- `_check_trait_implementations`
- `_type_implements_trait`
- Trait bound checking

**Target sizes:** 
- types.py: ~1000-1500 lines
- generics.py: ~500-800 lines
- traits.py: ~300-500 lines

**Verify:** Run tests, especially `test_types.py` and generic-related tests in `test_advanced.py`.

---

## Phase 6: Extract Control Flow and Functions

### Task: Extract statement and function generation

Create `codegen/control_flow.py` for:
- If/else generation
- For loop generation (including ranges)
- While loop generation
- Match statement generation
- Break/continue handling
- Block terminator management

Create `codegen/functions.py` for:
- Function declaration
- Parameter handling
- Return value generation
- Lambda expression generation
- Recursion handling

Create `codegen/expressions.py` for:
- Expression dispatch (`_generate_expression`)
- Operator generation
- Call expression generation
- Member access generation

Create `codegen/statements.py` for:
- Statement dispatch (`_generate_statement`)
- Variable declaration
- Assignment generation
- Print/debug generation

**Target sizes:**
- control_flow.py: ~800-1200 lines
- functions.py: ~600-900 lines
- expressions.py: ~1500-2000 lines
- statements.py: ~800-1200 lines

**Verify:** Run full test suite.

---

## Phase 7: Extract Matrix, FFI, Modules

### Task: Extract remaining subsystems

Create `codegen/matrix.py` for:
- Matrix declaration handling
- Cell access and indexing
- Double-buffering logic
- Synchronous update generation

Create `codegen/ffi.py` for:
- Extern function handling
- CXZ library loading
- C interoperability
- FFI heap management

Create `codegen/modules.py` for:
- Import resolution
- Module loading
- Replace/with alias handling
- Module path searching

**Target sizes:**
- matrix.py: ~500-800 lines
- ffi.py: ~400-600 lines
- modules.py: ~300-500 lines

**Verify:** Run tests, especially `test_modules.py` and matrix tests in `test_advanced.py`.

---

## Phase 8: Reassemble CodeGenerator

### Task: Create the final codegen/__init__.py

After all extractions, the main CodeGenerator class should:
- Initialize all subsystem modules
- Delegate to appropriate modules for each operation
- Maintain backward-compatible public interface

```python
"""
Coex LLVM Code Generator

Main entry point for code generation. Coordinates subsystem modules
to transform Coex AST into LLVM IR.
"""

from .context import CompilationContext
from .primitives import PrimitiveGenerator
from .collections import CollectionGenerator
from .types import TypeGenerator
from .generics import GenericHandler
from .traits import TraitChecker
from .control_flow import ControlFlowGenerator
from .functions import FunctionGenerator
from .expressions import ExpressionGenerator
from .statements import StatementGenerator
from .matrix import MatrixGenerator
from .ffi import FFIHandler
from .modules import ModuleLoader

from gc import GarbageCollector


class CodeGenerator:
    """
    Generates LLVM IR from Coex AST.
    
    Usage:
        gen = CodeGenerator()
        ir_code = gen.generate(program_ast)
    """
    
    def __init__(self):
        # Initialize LLVM module
        self.module = ir.Module(name="coex_module")
        self.module.triple = binding.get_default_triple()
        
        # Create shared context
        self.ctx = CompilationContext(module=self.module)
        
        # Initialize garbage collector
        self.ctx.gc = GarbageCollector(self.module, self)
        
        # Initialize subsystem generators
        self._primitives = PrimitiveGenerator(self.ctx)
        self._collections = CollectionGenerator(self.ctx)
        self._types = TypeGenerator(self.ctx)
        self._generics = GenericHandler(self.ctx)
        self._traits = TraitChecker(self.ctx)
        self._control_flow = ControlFlowGenerator(self.ctx)
        self._functions = FunctionGenerator(self.ctx)
        self._expressions = ExpressionGenerator(self.ctx)
        self._statements = StatementGenerator(self.ctx)
        self._matrix = MatrixGenerator(self.ctx)
        self._ffi = FFIHandler(self.ctx)
        self._modules = ModuleLoader(self.ctx)
    
    def generate(self, program: 'Program') -> str:
        """Generate LLVM IR for a complete program."""
        # ... orchestration logic ...
        return str(self.module)

__all__ = ['CodeGenerator']
```

**Delete codegen_original.py** once all tests pass with the new structure.

**Verify:** Full test suite passes.

---

## Phase 9: Modularize Garbage Collector

Apply the same process to `coex_gc.py`:

1. Create `gc/__init__.py` with GarbageCollector class
2. Extract `gc/core.py` - heap management, allocation entry points
3. Extract `gc/handles.py` - handle table operations
4. Extract `gc/shadow_stack.py` - frame chain management
5. Extract `gc/marking.py` - mark phase, HAMT traversal
6. Extract `gc/sweeping.py` - sweep phase, handle retirement
7. Extract `gc/diagnostics.py` - tracing, dumps, validation

**Verify:** Full test suite passes after each extraction.

---

## Verification Checklist

After completing all phases:

- [ ] All 156+ tests pass
- [ ] No file exceeds 2000 lines
- [ ] Each module has a clear docstring
- [ ] ARCHITECTURE.md is fully updated
- [ ] CLAUDE.md references new structure
- [ ] `python3 coexc.py examples/hello.coex -o hello && ./hello` works
- [ ] CI pipeline passes

---

## Working with Claude Code

### Recommended Workflow

Yes, you should work on modules one at a time in separate Claude Code sessions. Here's the recommended approach:

**Session 1: Setup**
- Create ARCHITECTURE.md
- Create package directory structure
- Create placeholder __init__.py files
- Rename codegen.py → codegen_original.py
- Verify tests pass

**Session 2-N: Extract one module per session**
- Load only the files needed for that extraction:
  - The target new module file
  - codegen_original.py (or the shrinking version)
  - Relevant test files
  - ARCHITECTURE.md (to update)
- Extract the identified methods
- Add delegation in original
- Run tests
- Commit changes

**Final Session: Cleanup**
- Remove codegen_original.py
- Update all imports
- Final test verification
- Update documentation

### Context Management

For each extraction session, tell Claude Code:

```
I'm working on Phase N of the Coex compiler modularization.
Please load:
- codegen_original.py (current monolith)
- codegen/[target_module].py (new module)
- tests/test_[relevant].py
- ARCHITECTURE.md

Goal: Extract [specific functionality] from codegen_original.py 
into codegen/[target_module].py while maintaining all tests passing.
```

### Build and Test Commands

The project builds and tests as follows:

```bash
# Install dependencies (one time)
pip install -r requirements.txt

# Run all tests
python3 -m pytest tests/ -v --tb=short

# Run specific test category
python3 -m pytest tests/test_types.py -v

# Compile a test program
python3 coexc.py test.coex -o test
./test

# Regenerate parser (if grammar changes)
antlr -Dlanguage=Python3 -visitor CoexLexer.g4 CoexParser.g4
```

There is no separate "build" step for the compiler itself—it's Python and runs directly. The compilation process for Coex programs is:

```
source.coex → ANTLR4 Parser → AST → CodeGen → LLVM IR → clang → executable
```

---

## Rollback Strategy

If an extraction causes test failures that can't be quickly resolved:

1. `git stash` or `git checkout -- .` to revert changes
2. Analyze which tests failed and why
3. Plan a smaller extraction scope
4. Try again with the reduced scope

Always commit after each successful extraction phase.
