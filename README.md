# Coex Compiler

A compiler for the Coex programming language that generates native executables via LLVM.

## Architecture

```
Coex source (.coex)
        ↓
    ANTLR Parser (Python)
        ↓
    Parse Tree
        ↓
    AST Builder (ast_builder.py)
        ↓
    Abstract Syntax Tree
        ↓
    Code Generator (codegen.py)
        ↓
    LLVM IR
        ↓
    llvmlite → Object file (.o)
        ↓
    clang linker → Executable
```

## Files

- `coexc.py` - Main compiler driver
- `ast_nodes.py` - AST node definitions for the full language
- `ast_builder.py` - Parse tree to AST converter
- `codegen.py` - LLVM IR code generator
- `hello.coex` - Basic example program
- `test_full.coex` - Comprehensive test program

## Setup

1. **Install dependencies:**

```bash
pip install antlr4-python3-runtime llvmlite
```

2. **Generate the parser** (if not already present):

```bash
# Copy Coex.g4 to this directory
antlr -Dlanguage=Python3 Coex.g4
```

3. **Verify setup:**

```bash
python coexc.py hello.coex --emit-ir
```

## Usage

```bash
# Compile to object file
python coexc.py hello.coex

# Compile and link to executable
python coexc.py hello.coex -o hello

# View LLVM IR
python coexc.py hello.coex --emit-ir

# View AST
python coexc.py hello.coex --emit-ast

# Run the compiled program
./hello

# Run comprehensive tests
python coexc.py test_full.coex -o test_full
./test_full
```

## Currently Supported Features

### Function Kinds
- `formula` - Pure functions (executed normally for now)
- `task` - Concurrent functions (executed sequentially for now)
- `func` - Unrestricted functions

### Types
- `int` (64-bit signed integer)
- `float` (64-bit double)
- `bool`
- `string` (basic support)
- `byte`, `char`
- `atomic_int`, `atomic_float`, `atomic_bool` (treated as regular types)
- `T?` - Optional types (basic support)
- User-defined types (parsing only)

### Statements
- Variable declarations: `var x: int = 0`
- Assignments: `x = y + 1`
- Compound assignments: `+=`, `-=`, `*=`, `/=`, `%=`
- If/else if/else chains
- For loops with `range(start, end)` and `start..end`
- Loop statements with break/continue
- Return statements
- Print statements (built-in)
- Match statements (basic support)
- Select statements (stub - executes first case)
- Within/timeout (stub - executes body)

### Expressions
- Integer, float, boolean, string, nil literals
- Hex (`0xFF`) and binary (`0b1010`) literals
- Arithmetic: `+`, `-`, `*`, `/`, `%`
- Comparison: `==`, `!=`, `<`, `>`, `<=`, `>=`
- Logical: `and`, `or`, `not` (short-circuit evaluation)
- Ternary: `cond ? then ; else`
- Unary: `-`, `not`, `await` (await is no-op)
- Function calls
- Method calls (basic built-ins)
- Null coalescing: `??`

### Functions
- All three kinds work (all run sequentially)
- Parameters with types
- Return types
- Recursive calls

## Concurrency Model

Currently, all concurrency primitives are implemented sequentially:

| Feature | Current Behavior |
|---------|-----------------|
| `formula` | Executes normally |
| `task` | Executes normally |
| Channels | Stubs (send/receive are no-ops) |
| Atomics | Regular variables |
| `select` | Executes first case |
| `within` | Ignores timeout, executes body |
| `await` | No-op, returns value |

This allows all valid Coex programs to parse and compile. True concurrency support can be added later by implementing a runtime library.

## Not Yet Implemented (Fully)

- Channels (need runtime queue implementation)
- Full list/map/set operations
- User-defined type instantiation
- Traits and generics (monomorphization)
- Pattern matching destructuring
- Lambdas (closure capture)
- Matrices (cellular automata)
- Module imports

## Extending the Compiler

### Adding New Built-in Functions

In `codegen.py`, add handling in `_generate_call`:

```python
if name == "my_builtin":
    # Generate code for built-in
    pass
```

### Adding New Types

1. Add type class in `ast_nodes.py`
2. Handle in `ast_builder.py` type visitors
3. Add LLVM type mapping in `codegen.py._get_llvm_type`

### Adding Concurrency Runtime

To implement real concurrency:

1. Create a C runtime library with:
   - Channel queues with locking
   - Task scheduler (green threads or OS threads)
   - Atomic operations using platform primitives

2. Link the runtime with compiled programs

3. Update code generator to emit calls to runtime functions
