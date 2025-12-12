# Coex Compiler

A compiler for **Coex**, a concurrent programming language with explicit function kinds, cellular automata support, and static polymorphism via traits.

## Quick Start

```bash
# Run tests (use python3, not python - macOS doesn't have python alias)
python3 -m pytest tests/ -v --tb=short

# Compile a file
python3 coexc.py source.coex -o output
```

## Architecture

```
source.coex → ANTLR4 Parser → Parse Tree → AST Builder → AST → CodeGen → LLVM IR → clang → executable
```

| File | Purpose |
|------|---------|
| `Coex.g4` | Combined ANTLR4 grammar (lexer + parser rules) |
| `CoexLexer.g4` / `CoexParser.g4` | Split grammar files (alternative) |
| `ast_nodes.py` | Dataclass definitions for all AST nodes |
| `ast_builder.py` | Converts ANTLR parse tree to AST |
| `codegen.py` | LLVM IR generation (~6800 lines) - the core of the compiler |
| `coexc.py` | CLI entry point |
| `tests/conftest.py` | Test fixtures (`compile_coex`, `expect_output`) |

## Language Syntax

### Block Termination
Coex uses `~` or `end` to close blocks (not braces or indentation):
```coex
func main() -> int
    if x > 0
        print(x)
    ~
    return 0
~
```

### Function Kinds
- `formula` - Pure functions (no side effects)
- `func` - Regular imperative functions
- `task` - Concurrent tasks (currently runs sequentially)

### Reserved Words
`end`, `init`, `self`, `cell`, `true`, `false`, `nil`, `and`, `or`, `not`

## Feature Status (as of Dec 2024)

### Fully Working (121 tests passing)
- Arithmetic, comparisons, boolean logic
- Variables, assignment, compound operators (`+=`, `-=`, etc.)
- Control flow: `if`/`else`/`elif`, `for..in`, `loop`, `break`, `continue`
- All three function kinds with recursion
- User-defined types with fields and methods
- Tuples (construction, `.0`/`.1` access, destructuring)
- Enums with associated data and pattern matching
- Generics with monomorphization and trait bounds
- Traits (structural implementation checking)
- Matrix/CA (sequential execution, `cell` keyword)
- List literals, `len()`, `get()`, iteration, comprehensions
- Lambdas: `formula(_ x: int) => x * 2`
- Ranges: `start..stop` in for loops
- Ternary: `cond ? then ; else`

### Known Issues
| Issue | Description |
|-------|-------------|
| `list.append()` | Method dispatch type mismatch (expects `i8*`, gets `i64`) |
| Map literals | `_generate_map()` returns null (stub implementation) |
| Set operations | Not implemented |
| Concurrency | All concurrent features run sequentially (stubs) |
| Imports | Parsed but no module loading |

## Codegen Patterns

### Type Registry
```python
self.type_registry: Dict[str, ir.Type]      # type_name -> LLVM struct
self.type_fields: Dict[str, List[tuple]]    # type_name -> [(field, type)]
self.type_methods: Dict[str, Dict[str, str]] # type_name -> {method -> mangled_name}
self.enum_variants: Dict[str, Dict[str, tuple]] # enum_name -> {variant -> (tag, fields)}
```

### Adding New Features
1. Add AST node in `ast_nodes.py`
2. Add visitor in `ast_builder.py` to parse it
3. Add handler in `codegen.py` (check `_generate_expression` or `_generate_statement`)
4. Add test in `tests/test_*.py`

### Common Debugging
- Type mismatches: Check `_get_llvm_type()` and `_cast_value()`
- Missing handlers: Search for `return ir.Constant(ir.IntType(64), 0)` (fallback returns)
- Enum issues: Check `enum_variants` dict and `_generate_enum_constructor()`

## Test Structure

```python
def test_feature(self, expect_output):
    expect_output('''
func main() -> int
    # test code here
    print(result)
    return 0
~
''', "expected output\n")
```

Mark expected failures: `@pytest.mark.xfail(reason="description")`

## Grammar Quick Reference

```antlr
// Types
primitiveType: 'int' | 'float' | 'bool' | 'string' | 'byte' | 'char'
             | 'atomic_int' | 'atomic_float' | 'atomic_bool'

// Expressions (precedence low→high)
ternaryExpr → orExpr → andExpr → notExpr → nullCoalesceExpr
→ comparisonExpr → rangeExpr → additiveExpr → multiplicativeExpr
→ unaryExpr → postfixExpr → primaryExpr

// Statements
statement: varDeclStmt | ifStmt | forStmt | loopStmt | matchStmt
         | selectStmt | withinStmt | returnStmt | breakStmt | continueStmt
```

## Not Yet Implemented (from grammar)

- `while` loops (keyword exists, no codegen)
- `select` statement (channel multiplexing - stub)
- `within`/`else` (temporal constraints - stub)
- `await` (returns value immediately)
- Map/Set comprehensions
- Parallel matrix execution
- True concurrency
