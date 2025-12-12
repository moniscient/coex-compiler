# Coex

**Coex** is a programming language designed for safe concurrency with explicit function kinds, cellular automata support, and static polymorphism. This compiler generates native executables via LLVM.

## Example

```coex
type Point:
    x: int
    y: int

    func distance() -> float
        return sqrt(self.x * self.x + self.y * self.y)
    ~
~

type Option<T>:
    case Some(value: T)
    case None
~

func main() -> int
    var p: Point = Point(3, 4)
    print(p.x + p.y)

    var opt: Option<int> = Option.Some(42)
    match opt
        case Some(v):
            print(v)
        ~
        case None:
            print(0)
        ~
    ~

    var squares: List<int> = [x * x for x in 0..5]
    for s in squares
        print(s)
    ~

    return 0
~
```

## Features

### Three Function Kinds
| Kind | Purpose | Current Status |
|------|---------|----------------|
| `formula` | Pure functions - no side effects | Working |
| `func` | Regular imperative functions | Working |
| `task` | Concurrent tasks | Parses, runs sequentially |

### Type System
- **Primitives**: `int`, `float`, `bool`, `string`, `byte`, `char`
- **User-defined types** with fields and methods
- **Enums with associated data** and pattern matching
- **Generics** with monomorphization
- **Traits** for static polymorphism
- **Tuples** with named/positional access and destructuring
- **Optional types**: `T?`

### Control Flow
- `if`/`else if`/`else` chains
- `for..in` loops with ranges (`0..10`) and iterables
- `loop` with `break`/`continue`
- `match` statements with pattern matching
- Ternary expressions: `cond ? then ; else`

### Collections
- **Lists**: literals `[1, 2, 3]`, comprehensions `[x * 2 for x in data]`
- **Maps**: literals `{1: "one", 2: "two"}`, methods `get`, `set`, `has`, `remove`, `len`
- **Sets**: literals `{1, 2, 3}`, methods `add`, `has`, `remove`, `len`
- Iteration, comprehensions for all collection types

### Module System
```coex
import math
replace abs with math.abs

func main() -> int
    print(math.max(5, 10))   # Qualified call
    print(abs(-42))          # Aliased call
    return 0
~
```
Standard library: `lib/math.coex` provides `abs`, `max`, `min`, `clamp`, `sign`

### Cellular Automata
```coex
matrix Grid[100, 100]:
    type: int
    init: 0

    formula step()
        return cell + cell[-1, 0] + cell[1, 0]
    ~
~
```

### Lambdas
```coex
var double: formula(int) -> int = formula(_ x: int) => x * 2
print(double(21))  # 42
```

### Inline LLVM IR
Embed raw LLVM IR for low-level operations:
```coex
func main() -> int
    var x: int = 3
    var y: int = 4
    var result: int = llvm_ir(x -> %a, y -> %b) -> %r: i64 """
        %r = add i64 %a, %b
        ret i64 %r
    """
    print(result)  # 7
    return 0
~
```
- Binds Coex variables to LLVM registers: `x -> %a`
- Specifies return register and type: `-> %r: i64`
- Uses triple-quoted strings for the IR body

## Installation

### Prerequisites
- Python 3.8+
- clang (for linking)

### Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/coex-compiler.git
cd coex-compiler

# Install Python dependencies
pip install antlr4-python3-runtime llvmlite pytest

# Verify installation
python3 -m pytest tests/ -v
```

## Usage

```bash
# Compile to executable
python3 coexc.py program.coex -o program
./program

# View LLVM IR
python3 coexc.py program.coex --emit-ir

# View AST
python3 coexc.py program.coex --emit-ast
```

## Project Status

**Current: Alpha** - Core language features working, concurrency is stubbed.

### Working (156 tests passing)

| Category | Features |
|----------|----------|
| **Basics** | Arithmetic, comparisons, boolean logic, variables |
| **Control Flow** | if/else/elif, for, loop, break, continue, match |
| **Functions** | All three kinds, recursion, multiple parameters |
| **Types** | User-defined types, methods, field access |
| **Enums** | Variants with/without data, pattern matching |
| **Generics** | Type parameters, monomorphization, trait bounds |
| **Traits** | Declaration, structural implementation |
| **Tuples** | Construction, `.0`/`.1` access, destructuring |
| **Lists** | Literals, comprehensions, iteration |
| **Maps** | Literals, get/set/has/remove/len operations |
| **Sets** | Literals, add/has/remove/len operations |
| **Matrix/CA** | Creation, cell access, formulas (sequential) |
| **Lambdas** | All function kinds, stored in variables |
| **Modules** | Import, qualified calls, replace aliases |
| **Inline LLVM IR** | Variable bindings, return values, raw IR blocks |

### Known Limitations

| Feature | Status |
|---------|--------|
| `list.append()` | Bug in method dispatch |
| Concurrency | All features run sequentially |
| `while` loops | Grammar exists, no codegen |

### Concurrency Roadmap

The language is designed for concurrency, but the current compiler runs everything sequentially. This allows all valid programs to compile and run correctly (just not in parallel). True concurrency requires:

1. Runtime library with task scheduler
2. Channel implementation with synchronization
3. Atomic operations using platform primitives

## Architecture

```
source.coex → ANTLR4 Parser → AST Builder → CodeGen → LLVM IR → clang → executable
```

| File | Purpose |
|------|---------|
| `Coex.g4` | ANTLR4 grammar definition |
| `ast_nodes.py` | AST node dataclasses |
| `ast_builder.py` | Parse tree → AST conversion |
| `codegen.py` | LLVM IR generation |
| `coexc.py` | CLI compiler driver |

## Running Tests

```bash
# All tests
python3 -m pytest tests/ -v

# Specific test file
python3 -m pytest tests/test_types.py -v

# Single test
python3 -m pytest tests/test_types.py::TestEnums::test_enum_with_data -v
```

## Contributing

Contributions welcome! Areas that need work:

- **Concurrency runtime** - Task scheduler, channels
- **Error messages** - Better diagnostics with line numbers
- **Optimization** - LLVM optimization passes
- **Standard library** - Expand lib/ with more modules

## License

[Add your license here]

## Acknowledgments

- Built with [ANTLR4](https://www.antlr.org/) for parsing
- Uses [llvmlite](https://llvmlite.readthedocs.io/) for code generation
