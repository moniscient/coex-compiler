# Coex Compiler

A compiler for **Coex**, a concurrent programming language with explicit function kinds, cellular automata support, and static polymorphism via traits.

## Quick Start

```bash
# Run tests (use python3, not python - macOS doesn't have python alias)
python3 -m pytest tests/ -v --tb=short

# Compile a file
python3 coexc.py source.coex -o output

# Regenerate parser from grammar (note: command is 'antlr' not 'antlr4' on this system)
antlr -Dlanguage=Python3 -visitor Coex.g4
```

## Directives

Always use a test-first methodology when implementing a feature or troubleshooting a bug. Develop a test that expresses the bug as a failure or shows the feature lacking generating an erorr, and then work towards a solution that resolves the test. 

Write simple tests for bug completion and feature implementation. Then write stress-tests that show the bug or feature continuing to operate at large-scale, defined as millions of units and gigabytes of memory consumption.

Write benchmarks that show the possibility of pathologically long run time compared to reasonable expectation from other langauges. Ask about long run times to determine whether they should be investigated as bugs or architectural immprovements.

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

### Language Specification

Read the language specification document "coex-compiler/coex_specification_revised.txt" in the local directory.

### Inviolable requirements. Be certain that changes and update planning adheres to the immutability principles below.

coex uses value semantics. The only mutable states are atomics.

All types in Coex have value semantics. Assignment always produces a logically independent copy of the value. This applies uniformly to primitive types, user-defined types, and collections.

```coex
a = [1, 2, 3]
b = a              # b is an independent copy
b = b.append(4)    # b is now [1, 2, 3, 4]; a is unchanged
```

There is no aliasing in Coex. Two bindings never refer to "the same" mutable storage such that modifications through one are visible through the other. This guarantee is foundational to Coex's concurrency safety: a task that receives a value as a parameter owns that value exclusively and cannot observe modifications from other tasks.

The compiler may implement value semantics through copy-on-write, structural sharing, or other optimizations, but the observable behavior is always as if a full copy occurred at assignment.

### Bindings: `const` vs Rebindable

Coex uses `const` for non-rebindable bindings. Bare identifier declarations are rebindable by default:

```coex
x = 5           # Rebindable binding - can reassign
const y = 10    # Immutable binding - cannot reassign
x = 6           # OK
y = 20          # ERROR: cannot reassign const binding
```

Rebinding is purely local. A declaration creates a name that can be bound to different values over time within its scope. The values themselves are never shared; rebinding one variable cannot affect any other binding anywhere in the program.

```coex
x = 1
x = 2      # Rebinding: x now refers to the value 2
```

Rebinding is available in task and func contexts. Formulas require `const` bindings for purity:

```coex
formula compute(a: int) -> int
    const result = a * 2    # const required in formulas
    return result
~
```

### No Global Variables

Coex does not support global mutable state of any kind. All state must be:
- Declared within functions
- Passed explicitly as parameters
- Shared via atomic types passed as parameters (for concurrent access)

This ensures all data dependencies are visible in function signatures.

```coex
# WRONG - global variables are not allowed
# var counter = 0

# CORRECT - pass state explicitly
func main() -> int
    counter = 0
    counter = increment(counter)
    print(counter)
    return 0
~

func increment(c: int) -> int
    return c + 1
~
```

For concurrent coordination, create atomic types in `main()` and pass them to tasks:

```coex
func main() -> int
    counter: atomic_int = 0
    # Pass counter to concurrent tasks
    return counter.load()
~
```


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
`end`, `init`, `self`, `cell`, `true`, `false`, `nil`, `and`, `or`, `not`, `const`, `var`

## Feature Status (as of Dec 2024)

### Fully Working (185 tests passing)
- Arithmetic, comparisons, boolean logic
- Variables, assignment, compound operators (`+=`, `-=`, etc.)
- Control flow: `if`/`else`/`elif`, `for..in`, `while`, `break`, `continue`
- All three function kinds with recursion
- User-defined types with fields and methods
- Tuples (construction, `.0`/`.1` access, destructuring)
- Enums with associated data and pattern matching
- Generics with monomorphization and trait bounds
- Traits (structural implementation checking)
- Matrix/CA (sequential execution, `cell` keyword)
- List: `[1, 2, 3]`, methods: `.len()`, `.get(i)`, `.append(x)`, iteration, comprehensions
- String: `"hello"`, methods: `.len()` (returns UTF-8 codepoint count)
- Map: `{1: 10, 2: 20}`, methods: `.get`, `.set`, `.has`, `.remove`, `.len()`
- Set: `{1, 2, 3}`, methods: `.add`, `.has`, `.remove`, `.len()`
- Lambdas: `formula(_ x: int) => x * 2`
- Ranges: `start..stop` in for loops
- Ternary: `cond ? then ; else`
- Module system: `import math`, `math.abs(-5)`, `replace abs with math.abs`

**Note:** Collection operations use method syntax (`.len()`, `.append()`) not free functions.

### Module System
```coex
import math                        # Load lib/math.coex
replace abs with math.abs          # Create local alias

func main() -> int
    print(math.max(5, 10))         # Qualified call
    print(abs(-42))                # Aliased call
    return 0
~
```

Standard library: `lib/math.coex` provides `abs`, `max`, `min`, `clamp`, `sign`

### Known Issues
| Issue | Description |
|-------|-------------|
| Concurrency | All concurrent features run sequentially (stubs) |

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
statement: varDeclStmt | ifStmt | forStmt | whileStmt | matchStmt
         | selectStmt | withinStmt | returnStmt | breakStmt | continueStmt
```
