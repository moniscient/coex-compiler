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
- Iteration, `len()`, `get()` operations

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

### Working (121 tests passing)

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
| **Matrix/CA** | Creation, cell access, formulas (sequential) |
| **Lambdas** | All function kinds, stored in variables |

### Known Limitations

| Feature | Status |
|---------|--------|
| `list.append()` | Bug in method dispatch |
| Maps/Sets | Parsed, not implemented |
| Concurrency | All features run sequentially |
| Imports | Parsed, no module loading |
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

- **Maps and Sets** - Implement hash table data structure
- **Concurrency runtime** - Task scheduler, channels
- **Module system** - File imports and namespaces
- **Error messages** - Better diagnostics with line numbers
- **Optimization** - LLVM optimization passes

## License

[Add your license here]

## Acknowledgments

- Built with [ANTLR4](https://www.antlr.org/) for parsing
- Uses [llvmlite](https://llvmlite.readthedocs.io/) for code generation
