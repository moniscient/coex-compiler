# Coex Array Type: Implementation Specification

## Overview

This document specifies a unified `Array<T>` type for Coex—a dense, contiguous, row-major array with shape parameter supporting 1D, 2D, and future N-dimensional arrays. The type is optimized for both linear algebra (BLAS) and cellular automata (CA) operations. This replaces the current `matrix` declaration syntax with a more flexible design that unifies arrays, matrices, and future tensors.

---

## Design Goals

1. **BLAS-compatible storage**: Contiguous row-major buffer suitable for FFI to CBLAS
2. **Value semantics**: Like all Coex types, arrays are immutable values
3. **Efficient CA operations**: GPU-accelerated stencil computations via `[[]]` relative indexing
4. **Type safety**: Generic over element type with compile-time checking
5. **Unified type**: Single `Array<T>` serves 1D lists, 2D matrices, and future N-D tensors
6. **Minimal concepts**: `[[]]` detection rule for per-element execution, no new keywords

---

## Part 1: Array<T> Type

### Type Declaration

`Array<T>` is a built-in generic type (like `Result<T,E>` or `Option<T>`), not user-declared:

```coex
# Type annotations - shape is implicit from construction
arr: Array<float>         # Could be 1D, 2D, or N-D
vec: Array<int>           # 1D array (vector)
grid: Array<int>          # 2D array (matrix)
```

Supported element types: `int`, `float`, `byte`, `bool`

### Shape Parameter

`Array<T>` supports arbitrary dimensionality via shape:

```coex
# 1D array (like current [T] list)
vec = Array.zeros<float>([100])

# 2D array (matrix)
mat = Array.zeros<float>([100, 100])

# 3D array (future)
vol = Array.zeros<float>([100, 100, 100])
```

**Current implementation focus**: 1D and 2D arrays. N-D support is designed in but implemented later.

### Why Unified Array<T>

1. **BLAS compatibility** - 2D arrays are the `Matrix` case, contiguous row-major for CBLAS
2. **CA generality** - `[[]]` syntax works uniformly: `arr[[offset]]` (1D), `arr[[dr]][[dc]]` (2D)
3. **Future-proof** - No need for separate `Matrix<T>` and `Tensor<T>` types
4. **Consistent API** - Same methods work across dimensionalities

### Memory Layout

```
struct CoexArray {
    i64 handle      # GC handle for the data buffer
    i64 ndim        # Number of dimensions (1, 2, ...)
    i64 shape[4]    # Dimensions (padded to 4 for alignment)
    i64 strides[4]  # Strides per dimension
    i64 offset      # Starting offset into buffer (for views)
    i64 elem_size   # Size of element in bytes (8 for int/float, 1 for byte)
    i64 type_id     # Element type identifier
}
```

The `handle` points to a GC-managed buffer. Data is stored in **row-major (C) order**: for 2D, element at (row, col) is at byte offset `(row * strides[0] + col * strides[1]) * elem_size`.

### LLVM Representation

```llvm
%Array = type { i64, i64, [4 x i64], [4 x i64], i64, i64, i64 }
; Fields: handle, ndim, shape, strides, offset, elem_size, type_id
```

Arrays are passed by value. The underlying data buffer is shared via the GC handle until mutation requires copy-on-write.

---

## Part 2: Array Construction

### Static Constructors

```coex
# Zero-initialized arrays (shape as list)
vec = Array.zeros<float>([100])           # 1D: 100 elements
mat = Array.zeros<float>([100, 100])      # 2D: 100×100
vol = Array.zeros<float>([10, 10, 10])    # 3D: 10×10×10

# Fill with value
mat = Array.fill<float>([100, 100], 1.0)
vec = Array.fill<int>([1000], 42)

# Identity matrix (2D only)
eye = Array.identity<float>(100)          # 100×100 identity

# From nested list (for small arrays / testing)
mat = Array.from<float>([[1.0, 2.0], [3.0, 4.0]])
vec = Array.from<int>([1, 2, 3, 4, 5])

# Uninitialized (for performance when immediately overwriting)
mat = Array.uninit<float>([rows, cols])
```

### Type Inference

When the type can be inferred from context:

```coex
m: Array<float> = Array.zeros([100, 100])  # Type inferred from annotation
result = Array.zeros<float>(m.shape())     # Explicit type parameter
```

---

## Part 3: Array Access

### Element Access

```coex
# Read element using chained brackets (0-indexed)
value = vec[5]            # 1D access
value = mat[3][4]         # 2D access
value = vol[1][2][3]      # 3D access

# Alternative method syntax
value = mat.get([3, 4])   # Index as list

# Bounds-checked access returning Option
value = mat.try_get([row, col])  # Returns Option<T>

# Set element (returns new array - value semantics)
mat2 = mat.set([row, col], value)
```

### Shape and Dimensions

```coex
shape = m.shape()     # Returns [rows, cols] for 2D
ndim = m.ndim()       # Number of dimensions (1, 2, ...)
s = m.size()          # Total elements (product of shape)

# For 2D arrays:
r = m.shape()[0]      # Number of rows
c = m.shape()[1]      # Number of columns
```

### Row/Column Extraction (2D)

```coex
# Using slice syntax with empty bracket
row_data = m[5][]        # Row 5, all columns → 1D array
col_data = m[][-1]       # All rows, last column → 1D array

# Method alternatives
row_data = m.row(i)      # Get row as 1D array
col_data = m.col(j)      # Get column as 1D array
diag = m.diag()          # Get diagonal as 1D array
```

### Slicing / Subarrays

```coex
# Extract subarray (view - shares underlying buffer)
# For 2D: row_start:row_end, col_start:col_end
sub = m[0:50][0:50]      # Top-left 50×50 quadrant

# Method alternative
sub = m.slice([0, 50], [0, 50])  # [[row_start, row_end], [col_start, col_end]]
```

Views share the parent's data buffer (via same GC handle) with adjusted offset and strides. This is safe because arrays have value semantics—mutation creates a copy.

---

## Part 4: Array Operations

### Arithmetic (Element-wise)

```coex
# Scalar operations
arr2 = arr.scale(2.0)           # Multiply all elements by scalar
arr2 = arr.add_scalar(1.0)      # Add scalar to all elements

# Element-wise array operations (must have same shape)
arr3 = arr.add(arr2)            # Element-wise addition
arr3 = arr.sub(arr2)            # Element-wise subtraction
arr3 = arr.mul(arr2)            # Element-wise multiplication (Hadamard)
arr3 = arr.div(arr2)            # Element-wise division
```

### Transformation

```coex
m2 = m.transpose()              # Transpose (2D only, swaps axes)
m2 = m.reshape([new_rows, new_cols])  # Reshape (must preserve total size)
flat = m.flatten()              # Returns 1D Array<T>
```

### Reduction

```coex
total = m.sum()             # Sum all elements
avg = m.mean()              # Average
min_val = m.min()           # Minimum element
max_val = m.max()           # Maximum element
```

### Comparison

```coex
equal = arr1.equals(arr2)       # Element-wise equality check
close = arr1.approx(arr2, tol)  # Approximate equality within tolerance
```

---

## Part 5: BLAS Integration

The `linalg` module operates on 2D `Array<float>` and `Array<int>`:

```coex
use linalg

a: Array<float> = Array.zeros([100, 200])
b: Array<float> = Array.zeros([200, 150])

# Matrix multiplication (calls DGEMM/SGEMM)
c = linalg.matmul(a, b)         # Returns Array<float> [100 × 150]

# 32-bit precision variant
c = linalg.matmul32(a, b)       # 64→32→compute→64

# General matrix multiply: α*A*B + β*C
c = linalg.gemm(1.0, a, b, 0.0, c)

# Matrix-vector multiplication
x: Array<float> = Array.zeros([200])
y = linalg.matvec(a, x)         # Returns 1D Array<float>

# Solve linear system
solution = linalg.solve(a, b_vec)

# Decompositions
(l, u, p) = linalg.lu(a)
(q, r) = linalg.qr(a)
(u, s, vt) = linalg.svd(a)
```

**Note**: BLAS operations require 2D arrays. Passing a 1D or 3D array is a compile-time error.

### FFI Bridge

Internally, `linalg.matmul` does:

1. Verify both inputs are 2D
2. Extract data pointer from array handle: `ptr = gc_handle_deref(arr.handle) + arr.offset * arr.elem_size`
3. Pass pointer, dimensions, strides to CBLAS
4. Allocate result array via `Array.uninit`
5. CBLAS writes directly into result buffer
6. Return result array

```python
# Pseudocode for codegen
def emit_linalg_matmul(a, b):
    # Verify 2D
    assert a.ndim == 2 and b.ndim == 2

    # Get raw pointers
    a_ptr = gc_handle_deref(a.handle)
    b_ptr = gc_handle_deref(b.handle)

    # Allocate result
    result = Array.uninit([a.shape[0], b.shape[1]])
    c_ptr = gc_handle_deref(result.handle)

    # Call BLAS
    cblas_dgemm(CblasRowMajor, CblasNoTrans, CblasNoTrans,
                a.shape[0], b.shape[1], a.shape[1],
                1.0, a_ptr, a.strides[0],
                b_ptr, b.strides[0],
                0.0, c_ptr, result.strides[0])

    return result
```

---

## Part 6: Cellular Automata Operations

### Chained Bracket Indexing

Array access uses chained brackets with clear semantics for absolute vs relative indexing:

| Syntax | Meaning |
|--------|---------|
| `m[row][col]` | Absolute access (row and column) |
| `m[-1][-1]` | Last row, last column (negative = from end) |
| `m[[dr]][[dc]]` | Relative access (offset from current position) |
| `m[[-1]][[0]]` | One row up, same column |
| `m[[0]][[0]]` | Current cell (self) |
| `m[row][[dc]]` | Mixed: absolute row, relative column |
| `m[5][]` | Row 5, all columns (extract row) |
| `m[][-1]` | All rows, last column (extract column) |

**Key distinction:**
- `[]` = absolute indexing, negative means from end (standard slice semantics)
- `[[]]` = relative indexing, negative means offset backward

This syntax works uniformly across all collection types:
```coex
# 1D arrays
arr[5]        # Element at index 5
arr[-1]       # Last element (from end)
arr[[-1]]     # Previous element (relative, in each context)
arr[]         # All elements

# 2D matrices
m[5][3]       # Row 5, column 3
m[-1][-1]     # Last row, last column
m[[-1]][[0]]  # One row up, same column (relative)
m[5][]        # Row 5, all columns (returns 1D array)
m[][-1]       # All rows, last column (returns 1D array)
```

### Formulas with Relative Indexing

CA operations use existing `formula` or `formula32` kinds. The compiler detects `[[]]` usage and automatically enables per-element execution:

```coex
formula game_of_life(grid: Array<int>) -> int
    neighbors = grid[[-1]][[-1]] + grid[[-1]][[0]] + grid[[-1]][[1]] +
                grid[[0]][[-1]]  +                   grid[[0]][[1]]  +
                grid[[1]][[-1]]  + grid[[1]][[0]]  + grid[[1]][[1]]

    current = grid[[0]][[0]]
    if current == 1
        return (neighbors == 2 or neighbors == 3) ? 1 : 0
    else
        return (neighbors == 3) ? 1 : 0
    ~
~

# 32-bit precision variant for GPU performance
formula32 blur(img: Array<float>) -> float
    return (img[[-1]][[0]] + img[[1]][[0]] +
            img[[0]][[-1]] + img[[0]][[1]] + img[[0]][[0]]) / 5.0
~
```

**Detection rule:** If a formula body uses `[[]]` relative indexing → per-element execution. Otherwise → normal execution.

| Formula Body | Execution Mode | Call Semantics |
|--------------|----------------|----------------|
| Uses `[[]]` | Per-element | `f(Array) → Array` (same shape) |
| No `[[]]` | Whole-array | `f(Array) → declared return type` |

**No special keywords or types needed:**
- No `each` keyword—`[[]]` usage is the signal
- No `Cell<T>` type—just use `Array<T>` with `[[]]`
- Precision controlled by `formula` vs `formula32`

**CA formula characteristics:**
- Pure function (formula semantics)
- `[[]]` usage triggers per-element execution with position context
- `arr[[offset]]` for 1D, `arr[[dr]][[dc]]` for 2D neighbor access
- Out-of-bounds access returns zero (or configurable boundary condition)
- Compiled to GPU kernel (Metal/CUDA) or CPU fallback with parallel tasks

### Calling CA Formulas

CA formulas are called like regular functions, passing an array as the argument:

```coex
grid: Array<int> = Array.zeros([1000, 1000])

# Initialize some cells
grid = grid.set(500, 500, 1)
grid = grid.set(500, 501, 1)
grid = grid.set(500, 502, 1)

# Apply formula (returns new matrix)
grid = game_of_life(grid)

# Apply multiple generations
for i in 0..100
    grid = game_of_life(grid)
~
```

**Declared signature**: `formula game_of_life(grid: Array<int>) -> int`
**Effective signature when called**: `game_of_life(Array<int>) -> Array<int>` (because `[[]]` is used)

When you call `game_of_life(grid)`:
1. The compiler sees `[[]]` usage in the formula body
2. This triggers per-element execution mode
3. For each position, it sets the current position context
4. The formula body executes with `[[]]` indexing relative to that position
5. The returned `int` becomes the output value at that position
6. A new `Array<int>` is returned with same shape, containing all computed values

This is explicit and predictable—no hidden state, no mutation of input.

### Boundary Conditions

Boundary conditions are passed as an optional named parameter:

```coex
# Default: zero outside bounds
grid = game_of_life(grid)

# Wrap around (toroidal)
grid = game_of_life(grid, boundary: "wrap")

# Clamp to edge values
grid = game_of_life(grid, boundary: "clamp")

# Custom boundary value
grid = game_of_life(grid, boundary: -1)
```

### GPU Execution

When a CA formula (formula using `[[]]`) is called with an array:

1. **Analyzes stencil** at compile time to determine neighbor access pattern and stencil radius
2. **Generates GPU kernel** (Metal compute shader or CUDA kernel) for the stencil body
3. **At runtime**: Uploads input matrix to GPU memory (or uses unified memory on macOS)
4. **Dispatches kernel** with appropriate thread groups covering all cells
5. **Downloads result** (or reads from unified memory)
6. **Returns new matrix** with computed result

For small matrices or when GPU is unavailable, the compiler generates a CPU fallback using parallel tasks.

### CPU Fallback with Tasks

When GPU execution isn't available or appropriate, the CA formula runs on CPU using Coex's task system:

```coex
# Internal CPU fallback implementation (conceptual)
func _ca_cpu_fallback(input: Array<T>, formula_fn, boundary) -> Array<T>
    rows = input.shape()[0]
    cols = input.shape()[1]
    output = Array.uninit<T>([rows, cols])

    # Small matrices: single-threaded (task overhead not worth it)
    if rows * cols < 65536  # < 256×256
        for row in 0..rows
            for col in 0..cols
                # Set current position context, then call formula
                # Formula uses [[dr]][[dc]] relative to (row, col)
                output.set_raw(row, col, formula_fn(input, row, col, boundary))
            ~
        ~
        return output
    ~

    # Large matrices: parallel tasks
    num_workers = cpu_core_count()
    rows_per_worker = rows / num_workers

    # Spawn tasks for row ranges
    workers = for w in 0..num_workers
        task _process_rows(input, output, formula_fn, boundary,
                          w * rows_per_worker,
                          min((w + 1) * rows_per_worker, rows))
    ~

    # Wait for all tasks
    for worker in workers
        worker.wait()
    ~

    return output
~
```

**Why tasks (not raw threads):**
- Reuses existing Coex task infrastructure
- Task scheduler handles thread pooling
- GC integration already implemented for tasks
- Consistent with Coex's concurrency model

**Parallelism is safe because:**
- All tasks read from immutable input matrix
- Each task writes to disjoint rows in output matrix
- Stencils are pure functions (no shared mutable state)
- No synchronization needed except final barrier

### CA Formula Compilation

```python
# Pseudocode for CA formula → Metal shader
def compile_ca_formula_to_metal(formula_ast):
    # Analyze [[dr]][[dc]] relative access patterns
    accesses = find_relative_accesses(formula_ast)
    max_radius = max(abs(dr), abs(dc) for dr, dc in accesses)

    # Generate Metal shader
    shader = f"""
    #include <metal_stdlib>
    using namespace metal;

    kernel void {formula.name}(
        device const {elem_type}* input [[buffer(0)]],
        device {elem_type}* output [[buffer(1)]],
        constant int& width [[buffer(2)]],
        constant int& height [[buffer(3)]],
        uint2 gid [[thread_position_in_grid]]
    ) {{
        int col = gid.x;
        int row = gid.y;
        if (col >= width || row >= height) return;

        // m[[dr]][[dc]] - relative access with bounds check
        #define REL(dr, dc) ((row+(dr) >= 0 && row+(dr) < height && \\
                              col+(dc) >= 0 && col+(dc) < width) \\
                             ? input[(row+(dr)) * width + (col+(dc))] : 0)

        // m[r][c] - absolute access
        #define ABS(r, c) input[(r) * width + (c)]

        // Translated formula body:
        // - 'm[[dr]][[dc]]' → REL(dr, dc)
        // - 'm[r][c]' → ABS(r, c)
        {translate_body(formula_ast.body)}

        output[row * width + col] = __result;
    }}
    """
    return compile_metal_shader(shader)
```

---

## Part 7: Implementation Plan

### Phase 1: Array Type Foundation

1. **Remove current `matrix` declaration** from grammar, AST, codegen
2. **Add Array type** to type system (`ast_nodes.py`) with shape parameter
3. **Implement LLVM struct** for Array in codegen (handle, ndim, shape, strides, etc.)
4. **Implement constructors**: `zeros`, `fill`, `identity`, `from`, `uninit`
5. **Implement accessors**: chained bracket indexing, `get`, `set`, `shape`, `ndim`, `size`
6. **Add GC integration** for array data buffers
7. **Write tests** for basic 1D and 2D array operations

### Phase 2: Array Operations

1. **Element-wise operations**: `scale`, `add`, `sub`, `mul`, `div`
2. **Transformations**: `transpose`, `reshape`, `flatten`
3. **Reductions**: `sum`, `mean`, `min`, `max`
4. **Row/column access**: `m[i][]`, `m[][-1]`, `row`, `col`, `diag`
5. **Slicing**: `m[start:end][start:end]` with view semantics
6. **Write tests** for all operations

### Phase 3: BLAS Integration

1. **Platform detection** for BLAS library (Accelerate/OpenBLAS/cuBLAS)
2. **FFI bridge** for CBLAS functions
3. **Implement `linalg` module**: `matmul`, `matvec`, `gemm`, `gemv`
4. **32-bit variants**: `matmul32`, etc.
5. **LAPACK operations**: `lu`, `qr`, `svd`, `solve`, `inv`, `det`
6. **Write tests** comparing against known results
7. **Write benchmarks** comparing against reference implementation

### Phase 4: Cellular Automata

1. **Add `[[]]` relative indexing** syntax to grammar and codegen
2. **Implement `[[]]` detection** in formula body analysis
3. **Extend formula/formula32 call semantics** - detect `[[]]` usage for per-element mode
4. **CPU fallback** using parallel tasks (row-based partitioning)
5. **Metal shader generation** for CA formulas
6. **CUDA kernel generation** for CA formulas (if applicable)
7. **Boundary condition parameter** support (`boundary: "wrap"`, etc.)
8. **Write tests** for CA operations
9. **Write benchmarks** for GPU vs CPU vs single-threaded performance

---

## Part 8: Grammar Changes

### Removals

Remove from `Coex.g4`:
- `matrixDecl` rule and all sub-rules
- `MATRIX` token (current CA-specific usage)
- `CELL` handling in current form

### Additions

**Grammar additions for chained and relative indexing:**

```antlr
// Chained index access
postfixExpr
    : primaryExpr
    | postfixExpr '[' expression ']'        // Absolute index
    | postfixExpr '[' ']'                   // All elements (slice)
    | postfixExpr '[[' expression ']]'      // Relative index
    ;
```

**Semantic rules:**
- `arr[i]` = absolute index, negative means from end
- `arr[[i]]` = relative index, offset from current position (only valid in formulas)
- `arr[]` = all elements in this dimension

**Detection rule for per-element execution:**
- Compiler analyzes formula body for `[[]]` usage
- If `[[]]` found → per-element mode, call returns array of same shape
- If no `[[]]` → normal mode, call returns declared return type

**CA formula calls use standard function call syntax:**
```coex
grid = life(grid)
grid = life(grid, boundary: "wrap")
```

The compiler detects `[[]]` usage in the formula and generates the appropriate GPU kernel or CPU parallel dispatch.

---

## Part 9: Type System Integration

### Generic Type Registration

```python
# In codegen setup
self.builtin_generic_types = {
    'Array': ArrayTypeHandler(),
    'Result': ResultTypeHandler(),
    'Option': OptionTypeHandler(),
}

class ArrayTypeHandler:
    def instantiate(self, type_args: List[Type]) -> Type:
        if len(type_args) != 1:
            raise TypeError("Array requires exactly one type argument")
        elem_type = type_args[0]
        if not isinstance(elem_type, PrimitiveType):
            raise TypeError("Array element must be primitive type")
        if elem_type.name not in ('int', 'float', 'byte', 'bool'):
            raise TypeError(f"Array<{elem_type}> not supported")
        return ArrayType(elem_type)
```

### AST Nodes

```python
@dataclass
class ArrayType(Type):
    """Dense N-dimensional array type"""
    element_type: Type
    # Shape is runtime, not part of type signature

    def __repr__(self):
        return f"Array<{self.element_type}>"

@dataclass
class RelativeIndexExpr(Expr):
    """Relative index access: obj[[offset]]"""
    object: Expr
    offset: Expr

@dataclass
class ChainedIndexExpr(Expr):
    """Chained index access: obj[i][j] or obj[[i]][[j]]"""
    object: Expr
    indices: List[Tuple[Expr, bool]]  # (index, is_relative) pairs
```

### `[[]]` Detection Semantics

The compiler detects `[[]]` relative indexing usage to determine execution mode:

1. **Static analysis**: Compiler scans formula body for `[[]]` expressions
2. **Per-element trigger**: If found, formula runs per-element when called with array
3. **Return type transformation**: Declared `-> T` becomes `-> Array<T>` with same shape
4. **Works on any dimensionality**: 1D, 2D, 3D arrays all work uniformly

```coex
# Uses [[]] → per-element execution
formula life(grid: Array<int>) -> int
    return grid[[0]][[0]] + grid[[-1]][[0]]  # [[]] triggers per-element mode
~

# Called: returns Array<int> (same shape as input)
result = life(grid)

# No [[]] → normal execution
formula total(arr: Array<float>) -> float
    return arr.sum()  # No [[]], normal mode
~

# Called: returns float
result = total(data)
```

---

## Part 10: Example Programs

### Conway's Game of Life

```coex
formula life(grid: Array<int>) -> int
    n = grid[[-1]][[-1]] + grid[[-1]][[0]] + grid[[-1]][[1]] +
        grid[[0]][[-1]]  +                   grid[[0]][[1]]  +
        grid[[1]][[-1]]  + grid[[1]][[0]]  + grid[[1]][[1]]

    current = grid[[0]][[0]]
    if current == 1
        return (n == 2 or n == 3) ? 1 : 0
    else
        return (n == 3) ? 1 : 0
    ~
~

func main() -> int
    # Glider
    grid = Array.zeros<int>([50, 50])
    grid = grid.set([1, 0], 1)
    grid = grid.set([2, 1], 1)
    grid = grid.set([0, 2], 1)
    grid = grid.set([1, 2], 1)
    grid = grid.set([2, 2], 1)

    for gen in 0..100
        grid = life(grid, boundary: "wrap")
        print_grid(grid)
    ~

    return 0
~
```

### Matrix Multiplication Benchmark

```coex
use linalg
use posix

func main() -> int
    n = 2048

    a = Array.fill<float>([n, n], 1.0)
    b = Array.fill<float>([n, n], 2.0)

    start = posix.time_ns()
    c = linalg.matmul(a, b)
    end = posix.time_ns()

    elapsed_ms = (end - start) / 1000000
    gflops = (2.0 * n * n * n) / (elapsed_ms * 1000000.0)

    print("Matrix size: ")
    print(n)
    print(" x ")
    print(n)
    print("\n")
    print("Time: ")
    print(elapsed_ms)
    print(" ms\n")
    print("GFLOPS: ")
    print(gflops)
    print("\n")

    # Verify result (each element should be n * 2.0)
    expected = n * 2.0
    actual = c[0][0]
    print("Expected: ")
    print(expected)
    print(", Got: ")
    print(actual)
    print("\n")

    return 0
~
```

### Image Processing

```coex
# 32-bit precision for GPU performance
# Uses [[]] relative indexing → per-element execution
formula32 gaussian_blur(img: Array<float>) -> float
    # 3x3 Gaussian kernel (approximation)
    return (img[[-1]][[-1]] + 2*img[[-1]][[0]] + img[[-1]][[1]] +
            2*img[[0]][[-1]] + 4*img[[0]][[0]] + 2*img[[0]][[1]] +
            img[[1]][[-1]]  + 2*img[[1]][[0]]  + img[[1]][[1]]) / 16.0
~

formula32 sobel_magnitude(img: Array<float>) -> float
    # Uses [[]] → per-element execution
    gx = -img[[-1]][[-1]] + img[[-1]][[1]] +
         -2*img[[0]][[-1]] + 2*img[[0]][[1]] +
         -img[[1]][[-1]]  + img[[1]][[1]]

    gy = -img[[-1]][[-1]] - 2*img[[-1]][[0]] - img[[-1]][[1]] +
          img[[1]][[-1]]  + 2*img[[1]][[0]]  + img[[1]][[1]]

    return sqrt(gx*gx + gy*gy)
~

func main() -> int
    # Load grayscale image as 2D array
    image: Array<float> = load_image("input.pgm")

    # Apply blur then edge detection
    blurred = gaussian_blur(image)
    edges = sobel_magnitude(blurred)

    # Save result
    save_image(edges, "edges.pgm")

    return 0
~
```

---

## Summary

This specification defines:

1. **`Array<T>` with shape** - A unified dense array type with contiguous row-major storage, supporting 1D, 2D, and future N-D shapes
2. **BLAS integration** via `linalg` module with platform-native acceleration (2D arrays)
3. **Chained bracket indexing** - `arr[i][j]` for absolute, `arr[[dr]][[dc]]` for relative access
4. **`[[]]` detection rule** - Relative indexing usage triggers per-element execution automatically

Key design decisions:
- **Unified Array<T>**: Single type with shape parameter serves 1D, 2D, and future N-D; no separate `Matrix<T>`
- **No new keywords**: No `each`, no `stencil`—existing `formula`/`formula32` with `[[]]` detection
- **No new types**: No `Cell<T>`—just use `[[]]` relative indexing on any collection
- **Chained brackets**: `arr[i][j]` allows independent dimension access
- **Clear distinction**: `[]` = absolute (negative from end), `[[]]` = relative (offset from current)
- **Detection rule**: `[[]]` usage in formula body → per-element execution mode
- **Boundary conditions as parameters**: `grid = life(grid, boundary: "wrap")`
- **Signature lifting**: Declared with element return, callable returns array of same shape

Key benefits:
- Unified `Array<T>` serves lists, matrices, and future tensors
- Minimal new concepts—just `[[]]` bracket syntax
- Uniform across all dimensionalities
- Row/column extraction natural: `m[5][]` = row 5, `m[][-1]` = last column
- Mixed absolute/relative: `m[5][[1]]` = row 5, one column right
- Preserves existing slice semantics: `m[-1]` = last element/row (from end)
- GPU acceleration for both BLAS (via cuBLAS/Accelerate) and CA (via compute shaders)
- CPU fallback uses Coex tasks for parallelism (no new threading infrastructure)
- Clean migration from current `matrix` declaration syntax
