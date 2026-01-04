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
source.coex â†’ ANTLR4 Parser â†’ Parse Tree â†’ AST Builder â†’ AST â†’ CodeGen â†’ LLVM IR â†’ clang â†’ executable
```

| File | Purpose |
|------|---------|
| `Coex.g4` | Combined ANTLR4 grammar (lexer + parser rules) |
| `CoexLexer.g4` / `CoexParser.g4` | Split grammar files (alternative) |
| `ast_nodes.py` | Dataclass definitions for all AST nodes |
| `ast_builder.py` | Converts ANTLR parse tree to AST |
| `codegen.py` | LLVM IR generation (~19700 lines) - the core of the compiler |
| `coex_gc.py` | Handle-based garbage collector (~4300 lines) |
| `coexc.py` | CLI entry point |
| `tests/conftest.py` | Test fixtures (`compile_coex`, `expect_output`) |

## Garbage Collector Architecture

The GC uses a **handle-based** design where all heap references are i64 indices into a global handle table, rather than raw pointers. This enables future concurrent collection without stop-the-world pointer fixup.

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Handle** | i64 index into handle table; 0 = null |
| **Handle Table** | Global array mapping handles to object pointers |
| **Shadow Stack** | Per-function frames tracking live handles for root scanning |
| **Birth-marking** | New objects allocated with current mark bit (survive immediate GC) |
| **Mark Inversion** | Alternating mark bit value each cycle (0↔1) avoids clearing phase |
| **Deferred Reclamation** | Freed handles go to retired list, available after next cycle (MI-6) |

### Object Header (32 bytes)
```
{ i64 size, i64 type_id, i64 flags, i64 forward }
```
- `flags` bit 0: mark bit (compared to `gc_current_mark_value`)
- `forward`: stores handle for pointer-to-handle recovery

### GC Cycle
1. Flip `gc_current_mark_value` (0↔1)
2. Promote retired handles to free list (from previous cycle)
3. Scan shadow stacks, mark reachable objects via handles
4. Sweep: unmarked objects → retire their handles
5. Update statistics

### Key Functions in coex_gc.py
- `gc_alloc(size, type_id) -> i64`: Allocate object, return handle
- `gc_handle_deref(handle) -> i8*`: Get pointer from handle
- `gc_ptr_to_handle(ptr) -> i64`: Recover handle from object's forward field
- `gc_mark_object(handle)`: Mark object and recursively trace references
- `gc_push_frame/gc_pop_frame`: Shadow stack management
- `gc_set_root`: Store handle in shadow stack slot

### GC Diagnostic Builtins

These functions are available in Coex code for debugging:

| Function | Description |
|----------|-------------|
| `gc()` | Force a garbage collection cycle |
| `gc_dump_stats()` | Print allocation/collection statistics |
| `gc_dump_heap()` | Print all objects on the heap |
| `gc_dump_roots()` | Print shadow stack root handles |
| `gc_validate_heap() -> int` | Check heap integrity, return error count |
| `gc_fragmentation_report()` | Analyze heap fragmentation by size class |
| `gc_dump_handle_table()` | Print handle table state (allocated/free/retired) |
| `gc_dump_shadow_stacks()` | Print all shadow stack frames with roots |

Example usage:
```coex
func main() -> int
    x = [1, 2, 3, 4, 5]
    y = {1: "one", 2: "two"}
    gc_dump_stats()
    gc()
    gc_dump_stats()
    return 0
~
```

## Language Syntax

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

### Slice Views (Zero-Copy Slicing)

Strings and Arrays support zero-copy slice views. When you slice a string or array, the result shares the underlying data buffer:

```coex
text = load_file("huge.txt")      # 1GB string
line1 = text[0:100]               # View into text's buffer (zero-copy)
line2 = text[100:200]             # Another view (zero-copy)
```

All slices share their parent's buffer. This is efficient and safe because strings and collections are immutable - mutation operations always return new values.

**Lifetime implication:** A slice view keeps the entire parent buffer alive until all views are unreachable. The parent buffer cannot be freed while any view exists.

### The := Move Operator

The `:=` operator transfers ownership and invalidates the source variable:

```coex
a = [1, 2, 3]
b := a            # Move: b takes ownership, a is now invalid
print(b)          # OK
print(a)          # ERROR: use-after-move
```

For expression assignment (not a simple identifier), `:=` and `=` behave identically since the expression produces a new value:

```coex
slice := text[0:5]   # text remains valid (expression creates new value)
print(text)          # OK - text was not moved
```

Use `:=` when you want to explicitly transfer ownership and catch accidental reuse of the source variable.

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

### Statement Separators
Statements are separated by newlines. Semicolons can optionally be used to put multiple statements on one line:
```coex
func main() -> int
    x = 1; y = 2; z = 3   # Multiple statements on one line
    print(x + y + z)
    return 0
~
```

### Optional Block-Begin Colon
Colons can optionally mark block begins, allowing single-line programs:
```coex
# Single-line function
func main() -> int: x = 1; y = 2; print(x + y); return 0 ~

# Single-line with nested blocks
func main() -> int: if true: print(1) else: print(0) ~; return 0 ~

# Traditional whitespace style still works
func main() -> int
    if true
        print(1)
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

## Feature Status (as of Jan 2025)

### Fully Working (942 tests passing)
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
- String: `"hello"`, methods: `.len()`, `.bytes()`, `String.from()`, `String.from_bytes()`, `String.from_hex()`
- Map: `{1: 10, 2: 20}`, methods: `.get`, `.set`, `.has`, `.remove`, `.len()`
- Set: `{1, 2, 3}`, methods: `.add`, `.has`, `.remove`, `.len()`
- Lambdas: `formula(_ x: int) => x * 2`
- Ranges: `start..stop` in for loops
- Ternary: `cond ? then : else`
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

### posix Platform Module

The `posix` type provides low-level POSIX I/O and system utilities. It wraps a file descriptor.

```coex
# Opening files
func main() -> int
    f: Result<posix, string> = posix.open("file.txt", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        content: Result<string, string> = handle.read_all()
        handle.close()
    ~
    return 0
~

# Using stdio handles
func main(stdin: posix, stdout: posix, stderr: posix) -> int
    stdout.writeln("hello world")
    return 0
~
```

**Instance Methods:**
- `open(path: string, mode: string) -> Result<posix, string>` - Static; opens file ("r", "w", "a")
- `read(count: int) -> Result<[byte], string>` - Read count bytes
- `read_all() -> Result<string, string>` - Read entire file as string
- `write(data: [byte]) -> Result<int, string>` - Write byte array
- `writeln(text: string) -> Result<(), string>` - Write string with newline
- `seek(offset: int, whence: int) -> Result<int, string>` - Seek (0=SET, 1=CUR, 2=END)
- `close() -> Result<(), string>` - Close file descriptor

**Static Utility Methods:**
- `posix.time() -> int` - Unix timestamp in seconds
- `posix.time_ns() -> int` - Nanosecond precision monotonic time
- `posix.getenv(name: string) -> string?` - Get environment variable (nil if not set)
- `posix.random_seed() -> int` - Random 64-bit integer from /dev/urandom
- `posix.urandom(count: int) -> [byte]` - Random bytes from /dev/urandom

**Note:** This module only works on Unix-like systems (macOS, Linux).

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

// Expressions (precedence lowâ†’high)
ternaryExpr â†’ orExpr â†’ andExpr â†’ notExpr â†’ nullCoalesceExpr
â†’ comparisonExpr â†’ rangeExpr â†’ additiveExpr â†’ multiplicativeExpr
â†’ unaryExpr â†’ postfixExpr â†’ primaryExpr

// Statements
statement: varDeclStmt | ifStmt | forStmt | whileStmt | matchStmt
         | selectStmt | withinStmt | returnStmt | breakStmt | continueStmt
```
