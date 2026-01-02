# Coex Compiler Architecture

## Overview

The Coex compiler transforms `.coex` source files into native executables through ANTLR4 parsing, AST construction, LLVM IR generation, and clang linking.

```
source.coex -> ANTLR4 Parser -> Parse Tree -> AST Builder -> AST -> CodeGen -> LLVM IR -> clang -> executable
```

## Build and Test

```bash
# Install dependencies
pip install -r requirements.txt

# Run all tests (942 tests)
python3 -m pytest tests/ -v --tb=short

# Run specific test file
python3 -m pytest tests/test_types.py -v

# Compile a program
python3 coexc.py source.coex -o output

# Regenerate parser from grammar
antlr -Dlanguage=Python3 -visitor CoexLexer.g4 CoexParser.g4
```

## Current Structure (Pre-Modularization)

```
coex-compiler/
├── ARCHITECTURE.md          # This file
├── CLAUDE.md                # Claude Code directives
├── MODULARIZATION_STATUS.md # Tracks modularization progress
├── README.md                # User-facing documentation
├── requirements.txt         # Python dependencies
├── pytest.ini               # Test configuration
│
├── CoexLexer.g4             # ANTLR4 lexer grammar
├── CoexParser.g4            # ANTLR4 parser grammar
├── Coex.g4                  # Combined grammar (alternative)
├── CoexLexer.py             # Generated lexer
├── CoexParser.py            # Generated parser
├── CoexParserVisitor.py     # Generated visitor base
│
├── coexc.py                 # CLI entry point (~200 lines)
├── ast_nodes.py             # AST node dataclasses (~800 lines)
├── ast_builder.py           # Parse tree -> AST conversion (~1,500 lines)
├── codegen.py               # LLVM IR generation (~19,730 lines) [TO BE MODULARIZED]
├── coex_gc.py               # Garbage collector (~4,275 lines) [TO BE MODULARIZED]
│
├── lib/                     # Standard library modules
│   └── math.coex            # Math utilities (abs, max, min, clamp, sign)
│
└── tests/                   # Test suite (942 tests)
    ├── conftest.py          # Pytest fixtures
    ├── test_basic.py        # Primitives, arithmetic, variables
    ├── test_types.py        # User types, enums, generics
    ├── test_advanced.py     # Traits, matrix, collections
    ├── test_gc*.py          # Garbage collector tests (13 files)
    ├── test_modules.py      # Import system
    └── ...                  # (51 test files total)
```

## Target Structure (Post-Modularization)

```
coex-compiler/
├── codegen/                 # LLVM IR generation package
│   ├── __init__.py          # CodeGenerator class, public interface
│   ├── context.py           # Shared compilation context
│   ├── primitives.py        # int, float, bool basic operations
│   ├── strings.py           # String implementation (~2,400 lines)
│   ├── json.py              # JSON type support (~1,800 lines)
│   ├── collections.py       # List, Array (~1,775 lines)
│   ├── hamt.py              # Map, Set (HAMT-based) (~2,550 lines)
│   ├── types.py             # User-defined types, enums, generics (~650 lines)
│   ├── traits.py            # Trait checking, structural typing
│   ├── control_flow.py      # if, for, while, match, break, continue
│   ├── expressions.py       # Expression generation (~1,585 lines)
│   ├── statements.py        # Statement generation (~1,480 lines)
│   ├── matrix.py            # Cellular automata (~585 lines)
│   ├── posix.py             # POSIX I/O (~775 lines)
│   ├── modules.py           # Import resolution (~430 lines)
│   └── atomics.py           # Atomic types, Result (~400 lines)
│
├── coex_gc/                 # Garbage collector package (named to avoid conflict with Python's gc)
│   ├── __init__.py          # GarbageCollector class, public interface
│   ├── core.py              # Mark-sweep algorithm (~1,200 lines)
│   ├── handles.py           # Handle table management (~335 lines)
│   ├── shadow_stack.py      # Root discovery, frame management
│   ├── diagnostics.py       # Tracing, heap dumps, validation (~1,075 lines)
│   └── async_gc.py          # Concurrent GC support (~510 lines)
│
└── [existing files unchanged]
```

## Module Dependency Graph

### Current (Monolithic)

```
coexc.py (entry point)
    │
    ├── ast_builder.py ◄── CoexParser (ANTLR generated)
    │       │
    │       └── ast_nodes.py
    │
    └── codegen.py ─────────────────────────────────────┐
            │                                           │
            └── coex_gc.py ◄────────────────────────────┘
```

### Target (Modular)

```
coexc.py (entry point)
    │
    ├── ast_builder.py ◄── CoexParser
    │       │
    │       └── ast_nodes.py
    │
    └── codegen/ ──────────────────────────────────────────────┐
            │                                                   │
            ├── context.py (shared state)                       │
            │       │                                           │
            ├── primitives.py                                   │
            ├── strings.py                                      │
            ├── json.py                                         │
            ├── collections.py ◄── coex_gc/                      │
            ├── hamt.py ◄── coex_gc/                            │
            ├── types.py                                        │
            ├── traits.py ◄── types.py                          │
            ├── control_flow.py                                 │
            ├── expressions.py ◄── primitives.py, collections.py│
            ├── statements.py ◄── expressions.py                │
            ├── matrix.py                                       │
            ├── posix.py                                        │
            ├── modules.py                                      │
            └── atomics.py                                      │
                                                                │
            coex_gc/ ◄──────────────────────────────────────────┘
            ├── core.py
            ├── handles.py
            ├── shadow_stack.py
            ├── diagnostics.py
            └── async_gc.py
```

## Key Abstractions

### CodeGenerator (codegen.py / codegen/__init__.py)

The main class orchestrating compilation. Maintains:

| State Variable | Purpose |
|---------------|---------|
| `module` | LLVM Module being built |
| `builder` | Current IRBuilder |
| `locals` | Variable symbol table (name -> AllocaInst) |
| `functions` | Function symbol table (name -> Function) |
| `type_registry` | User type LLVM representations |
| `type_fields` | Type field mappings |
| `type_methods` | Type method mappings |
| `gc` | GarbageCollector instance |
| `var_coex_types` | Coex AST type tracking per variable |
| `moved_vars` | Move operator tracking |
| `generic_types` | Generic type template storage |
| `monomorphized` | Monomorphization cache |

### GarbageCollector (coex_gc.py / gc/__init__.py)

Manages memory with handle-based indirection:

| Concept | Description |
|---------|-------------|
| **Handle** | i64 index into handle table; 0 = null |
| **Handle Table** | Global array mapping handles to object pointers |
| **Shadow Stack** | Per-function frames tracking live handles for root scanning |
| **Birth-marking** | New objects allocated with current mark bit (survive immediate GC) |
| **Mark Inversion** | Alternating mark bit value each cycle (0<->1) avoids clearing phase |
| **Deferred Reclamation** | Freed handles go to retired list, available after next cycle |

**Object Header (32 bytes):**
```
{ i64 size, i64 type_id, i64 flags, i64 forward }
```

### AST Nodes (ast_nodes.py)

Dataclasses representing the abstract syntax tree:

- **Types**: PrimitiveType, ListType, MapType, NamedType, OptionalType, etc.
- **Expressions**: BinaryExpr, CallExpr, MethodCallExpr, IndexExpr, etc.
- **Statements**: VarDecl, Assignment, IfStmt, ForStmt, WhileStmt, etc.
- **Declarations**: FunctionDecl, TypeDecl, TraitDecl, MatrixDecl, EnumDecl

## Compilation Pipeline

### 1. Parsing (ANTLR4)
```python
lexer = CoexLexer(InputStream(source))
parser = CoexParser(CommonTokenStream(lexer))
tree = parser.program()
```

### 2. AST Construction
```python
builder = ASTBuilder()
ast = builder.visit(tree)  # Returns Program node
```

### 3. Code Generation
```python
generator = CodeGenerator()
llvm_ir = generator.generate(ast)  # Returns LLVM IR string
```

### 4. Compilation
```python
# Write IR to temp file
with open(f"{output}.ll", "w") as f:
    f.write(llvm_ir)

# Compile with clang
subprocess.run(["clang", "-O2", f"{output}.ll", "-o", output])
```

## Testing Strategy

All tests must pass after each modularization step:

```bash
python3 -m pytest tests/ -v --tb=short
```

**Test Categories (942 tests total):**

| Category | Files | Tests | Purpose |
|----------|-------|-------|---------|
| Core Language | 8 | ~242 | Arithmetic, variables, control flow |
| Collections | 7 | ~167 | Lists, strings, slices |
| Garbage Collection | 13 | ~180 | GC phases, stress tests |
| Advanced Features | 7 | ~153 | Generics, traits, move semantics |
| I/O & System | 7 | ~92 | POSIX, FFI, modules |
| Data Structures | 5 | ~74 | Persistent vectors, HAMT |
| Error Handling | 3 | ~46 | Result type, error messages |
| Serialization | 1 | 60 | JSON support |

**Test Fixtures (conftest.py):**

- `expect_output(source, expected)` - Compile and verify output
- `compile_coex(source)` - Compile and return result object
- `expect_compile_error(source, msg)` - Verify compilation fails
- `compile_binary(source)` - Compile and return binary for arg testing

## Modularization Progress

See `MODULARIZATION_STATUS.md` for current progress and session handoff notes.

## Contributing

When modifying the compiler:

1. Write a failing test first
2. Make the minimal change to pass
3. Run full test suite before committing
4. Update ARCHITECTURE.md if structure changes
5. Update MODULARIZATION_STATUS.md if extracting modules
