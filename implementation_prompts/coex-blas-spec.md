# Coex BLAS Integration: Implementation Specification

## Overview

This document specifies the integration of BLAS (Basic Linear Algebra Subprograms) into Coex via the FFI system. BLAS provides highly optimized matrix and vector operations that have been refined over decades. Rather than reimplementing these operations, Coex wraps platform-native BLAS libraries to provide correct, fast linear algebra.

---

## Design Philosophy

### Why FFI to BLAS?

1. **Correctness first**: BLAS implementations are battle-tested across millions of applications
2. **Performance**: Platform-native BLAS (Accelerate, cuBLAS, OpenBLAS) leverages hardware-specific optimizations including GPU acceleration
3. **Pragmatism**: Reimplementing GEMM correctly and efficiently would take months; BLAS gives us production-quality linear algebra immediately
4. **Industry standard**: This is how NumPy, Julia, R, MATLAB, and every serious numerical computing environment handles linear algebra

### Platform Strategy

| Platform | BLAS Implementation | GPU Acceleration |
|----------|---------------------|------------------|
| macOS | Apple Accelerate | Automatic (Metal) |
| Linux (NVIDIA) | cuBLAS or OpenBLAS | CUDA |
| Linux (AMD) | rocBLAS or OpenBLAS | ROCm |
| Linux (CPU only) | OpenBLAS | None |
| Windows | OpenBLAS or Intel MKL | Varies |
| WebAssembly | Reference implementation | None (future: WebGPU) |

The compiler detects available BLAS libraries at compile time and links against the best available option.

---

## Coex API Design

### Module Structure

```coex
# Import the linalg module
use linalg

# Or import specific functions
use linalg::{matmul, dot, norm}
```

### Core Operations

#### Level 1 BLAS (Vector-Vector)

```coex
# Dot product: x · y
linalg.dot(x: [float], y: [float]) -> float

# Vector norm: ||x||
linalg.norm(x: [float]) -> float
linalg.norm(x: [float], p: int) -> float  # L-p norm

# Scalar-vector: α * x
linalg.scale(alpha: float, x: [float]) -> [float]

# Vector addition: α*x + y
linalg.axpy(alpha: float, x: [float], y: [float]) -> [float]
```

#### Level 2 BLAS (Matrix-Vector)

```coex
# Matrix-vector multiply: A * x
linalg.matvec(a: [[float]], x: [float]) -> [float]

# Matrix-vector multiply with scaling: α*A*x + β*y
linalg.gemv(alpha: float, a: [[float]], x: [float], 
            beta: float, y: [float]) -> [float]
```

#### Level 3 BLAS (Matrix-Matrix)

```coex
# Matrix multiply: A * B
linalg.matmul(a: [[float]], b: [[float]]) -> [[float]]

# General matrix multiply: α*A*B + β*C
linalg.gemm(alpha: float, a: [[float]], b: [[float]], 
            beta: float, c: [[float]]) -> [[float]]

# Matrix transpose
linalg.transpose(a: [[float]]) -> [[float]]
```

### 32-bit Variants

All operations have 32-bit precision variants for performance:

```coex
linalg.dot32(x: [float], y: [float]) -> float
linalg.matmul32(a: [[float]], b: [[float]]) -> [[float]]
linalg.gemm32(alpha: float, a: [[float]], b: [[float]], 
              beta: float, c: [[float]]) -> [[float]]
```

These use single-precision BLAS routines (SGEMM vs DGEMM) and follow the same semantics as `formula32`: inputs are narrowed from 64-bit, computation happens at 32-bit, outputs are widened back to 64-bit.

### Extended Operations (LAPACK)

For completeness, common LAPACK operations are also exposed:

```coex
# LU decomposition
linalg.lu(a: [[float]]) -> (l: [[float]], u: [[float]], p: [int])

# QR decomposition
linalg.qr(a: [[float]]) -> (q: [[float]], r: [[float]])

# Eigenvalues and eigenvectors
linalg.eig(a: [[float]]) -> (values: [float], vectors: [[float]])

# Singular value decomposition
linalg.svd(a: [[float]]) -> (u: [[float]], s: [float], vt: [[float]])

# Matrix inverse
linalg.inv(a: [[float]]) -> [[float]]

# Solve linear system: Ax = b
linalg.solve(a: [[float]], b: [float]) -> [float]

# Determinant
linalg.det(a: [[float]]) -> float
```

---

## Implementation Architecture

### Layer Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    Coex Source Code                          │
│         result = linalg.matmul(a, b)                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Coex linalg Module                           │
│     - Dimension validation                                   │
│     - Layout conversion (row-major ↔ column-major)          │
│     - Precision handling (64-bit ↔ 32-bit)                  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    FFI Bridge                                │
│     - Marshal Coex arrays to C pointers                     │
│     - Call BLAS functions                                    │
│     - Marshal results back to Coex arrays                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              Platform BLAS Implementation                    │
│     Accelerate │ cuBLAS │ OpenBLAS │ Reference              │
└─────────────────────────────────────────────────────────────┘
```

### FFI Declarations

The core BLAS functions are declared as extern:

```coex
# Internal FFI declarations (not exposed to users)

# DGEMM: Double-precision General Matrix Multiply
extern func cblas_dgemm(
    order: int,      # Row/column major
    transA: int,     # Transpose A?
    transB: int,     # Transpose B?
    m: int,          # Rows of A
    n: int,          # Columns of B
    k: int,          # Columns of A / Rows of B
    alpha: float,    # Scalar multiplier
    a: *float,       # Matrix A data
    lda: int,        # Leading dimension of A
    b: *float,       # Matrix B data
    ldb: int,        # Leading dimension of B
    beta: float,     # Scalar for C
    c: *float,       # Matrix C data (output)
    ldc: int         # Leading dimension of C
)

# SGEMM: Single-precision variant
extern func cblas_sgemm(
    order: int, transA: int, transB: int,
    m: int, n: int, k: int,
    alpha: float32, a: *float32, lda: int,
    b: *float32, ldb: int,
    beta: float32, c: *float32, ldc: int
)
```

### Memory Layout Handling

BLAS expects column-major (Fortran) layout; Coex uses row-major (C) layout. The wrapper handles this transparently:

```coex
# Internal implementation of linalg.matmul
func _matmul_impl(a: [[float]], b: [[float]]) -> [[float]] {
    m = len(a)           # Rows of A
    k = len(a[0])        # Columns of A
    n = len(b[0])        # Columns of B
    
    # Validate dimensions
    if len(b) != k {
        raise DimensionError("Matrix dimensions incompatible for multiplication")
    }
    
    # Allocate output
    c = [[0.0 for _ in range(n)] for _ in range(m)]
    
    # BLAS trick: for row-major matrices, compute C = A*B as C^T = B^T * A^T
    # This avoids explicit transposition
    cblas_dgemm(
        CblasRowMajor,    # We're using row-major
        CblasNoTrans,     # Don't transpose A
        CblasNoTrans,     # Don't transpose B
        m, n, k,          # Dimensions
        1.0,              # alpha = 1
        a.data(), k,      # A and its leading dimension
        b.data(), n,      # B and its leading dimension
        0.0,              # beta = 0 (don't add to C)
        c.data(), n       # C and its leading dimension
    )
    
    return c
}
```

### Value Semantics Preservation

BLAS operates on mutable buffers, but the Coex wrapper preserves value semantics:

```coex
func matmul(a: [[float]], b: [[float]]) -> [[float]] {
    # Inputs a and b are never modified
    # A new matrix c is allocated and returned
    # The BLAS call writes to c's buffer
    # c is then returned as an immutable Coex value
    
    c = _allocate_matrix(len(a), len(b[0]))
    _blas_gemm_into(a, b, c)  # Writes into c's buffer
    return c  # c is now immutable from Coex's perspective
}
```

The mutation happens inside the FFI boundary before the result becomes a Coex value. From Coex's perspective, `matmul` is a pure function: same inputs always produce same outputs, no side effects visible to the caller.

---

## Platform-Specific Implementation

### macOS (Accelerate)

```c
// Link against Accelerate.framework
#include <Accelerate/Accelerate.h>

// Accelerate uses the same CBLAS interface
// Just link -framework Accelerate
```

Compile-time detection:
```python
# In compiler's platform detection
def detect_blas_macos():
    # Accelerate is always available on macOS
    return BLASBackend.ACCELERATE
```

### Linux with NVIDIA GPU (cuBLAS)

```c
#include <cublas_v2.h>

// cuBLAS requires explicit device memory management
void gemm_cublas(double* a, double* b, double* c, int m, int n, int k) {
    cublasHandle_t handle;
    cublasCreate(&handle);
    
    double *d_a, *d_b, *d_c;
    cudaMalloc(&d_a, m * k * sizeof(double));
    cudaMalloc(&d_b, k * n * sizeof(double));
    cudaMalloc(&d_c, m * n * sizeof(double));
    
    cudaMemcpy(d_a, a, m * k * sizeof(double), cudaMemcpyHostToDevice);
    cudaMemcpy(d_b, b, k * n * sizeof(double), cudaMemcpyHostToDevice);
    
    double alpha = 1.0, beta = 0.0;
    cublasDgemm(handle, CUBLAS_OP_N, CUBLAS_OP_N,
                n, m, k, &alpha, d_b, n, d_a, k, &beta, d_c, n);
    
    cudaMemcpy(c, d_c, m * n * sizeof(double), cudaMemcpyDeviceToHost);
    
    cudaFree(d_a); cudaFree(d_b); cudaFree(d_c);
    cublasDestroy(handle);
}
```

The Coex runtime wraps this complexity—users just call `linalg.matmul`.

### Linux CPU (OpenBLAS)

```bash
# Install OpenBLAS
apt install libopenblas-dev

# Link against it
gcc -lopenblas ...
```

OpenBLAS provides the standard CBLAS interface, so the same wrapper code works.

### WebAssembly (Reference Implementation)

For WebAssembly targets where no optimized BLAS is available, Coex includes a reference implementation:

```coex
# Pure Coex reference implementation (slow but correct)
func _matmul_reference(a: [[float]], b: [[float]]) -> [[float]] {
    m = len(a)
    k = len(a[0])
    n = len(b[0])
    
    return [[sum([a[i][p] * b[p][j] for p in range(k)]) 
             for j in range(n)] 
            for i in range(m)]
}
```

This is much slower but ensures Coex code works everywhere. Users targeting WebAssembly for performance-critical linear algebra should be aware of this limitation (documented in the module).

---

## Compiler Integration

### BLAS Detection

At compile time:

```python
class BLASDetector:
    def detect(self) -> BLASConfig:
        if sys.platform == 'darwin':
            return BLASConfig(
                backend=BLASBackend.ACCELERATE,
                link_flags=['-framework', 'Accelerate'],
                include_path=None  # System headers
            )
        
        elif sys.platform == 'linux':
            # Check for cuBLAS first
            if self._has_cublas():
                return BLASConfig(
                    backend=BLASBackend.CUBLAS,
                    link_flags=['-lcublas', '-lcudart'],
                    include_path=self._cuda_include_path()
                )
            
            # Fall back to OpenBLAS
            elif self._has_openblas():
                return BLASConfig(
                    backend=BLASBackend.OPENBLAS,
                    link_flags=['-lopenblas'],
                    include_path='/usr/include/openblas'
                )
            
            # No BLAS available - use reference
            else:
                return BLASConfig(
                    backend=BLASBackend.REFERENCE,
                    link_flags=[],
                    include_path=None
                )
        
        else:
            # Windows, etc. - try OpenBLAS, fall back to reference
            ...
    
    def _has_cublas(self) -> bool:
        return shutil.which('nvcc') is not None
    
    def _has_openblas(self) -> bool:
        return os.path.exists('/usr/lib/libopenblas.so')
```

### Code Generation

When the compiler encounters `linalg.matmul`:

```python
def visit_linalg_call(self, node):
    if node.function == 'matmul':
        blas_config = self.blas_detector.detect()
        
        if blas_config.backend == BLASBackend.REFERENCE:
            # Emit pure Coex implementation
            return self._emit_reference_matmul(node)
        else:
            # Emit FFI call to BLAS
            return self._emit_blas_matmul(node, blas_config)
```

---

## Error Handling

### Dimension Errors

```coex
# Caught at runtime (dimensions known only at runtime)
a = [[1, 2, 3], [4, 5, 6]]      # 2x3
b = [[1, 2], [3, 4]]            # 2x2

result = linalg.matmul(a, b)    # DimensionError: cannot multiply 2x3 by 2x2
```

### Singular Matrix Errors

```coex
singular = [[1, 2], [2, 4]]     # Rows are linearly dependent

inv = linalg.inv(singular)      # SingularMatrixError: matrix is not invertible
solution = linalg.solve(singular, [1, 2])  # SingularMatrixError
```

### NaN/Inf Handling

BLAS operations may produce NaN or Inf for ill-conditioned inputs. Coex propagates these values (IEEE 754 semantics) rather than raising exceptions:

```coex
a = [[1e308, 0], [0, 1e308]]
b = [[1e308, 0], [0, 1e308]]
c = linalg.matmul(a, b)         # Contains Inf (overflow)

# User can check:
if linalg.has_nan(c) or linalg.has_inf(c) {
    handle_numerical_instability()
}
```

---

## Testing

### Correctness Tests

```python
class TestLinalgCorrectness:
    def test_matmul_identity(self):
        """A * I = A"""
        a = [[1, 2], [3, 4]]
        i = [[1, 0], [0, 1]]
        result = run("linalg.matmul(a, i)", a=a, i=i)
        assert result == a
    
    def test_matmul_known_result(self):
        """Test against known computation"""
        a = [[1, 2], [3, 4]]
        b = [[5, 6], [7, 8]]
        # [1*5+2*7, 1*6+2*8] = [19, 22]
        # [3*5+4*7, 3*6+4*8] = [43, 50]
        expected = [[19, 22], [43, 50]]
        result = run("linalg.matmul(a, b)", a=a, b=b)
        assert result == expected
    
    def test_matmul_associativity(self):
        """(A * B) * C = A * (B * C)"""
        a = random_matrix(10, 20)
        b = random_matrix(20, 15)
        c = random_matrix(15, 10)
        
        left = run("linalg.matmul(linalg.matmul(a, b), c)", a=a, b=b, c=c)
        right = run("linalg.matmul(a, linalg.matmul(b, c))", a=a, b=b, c=c)
        
        assert_matrices_close(left, right, rtol=1e-10)
    
    def test_32bit_64bit_consistency(self):
        """32-bit and 64-bit should agree within precision limits"""
        a = random_matrix(100, 100)
        b = random_matrix(100, 100)
        
        result_64 = run("linalg.matmul(a, b)", a=a, b=b)
        result_32 = run("linalg.matmul32(a, b)", a=a, b=b)
        
        # 32-bit has less precision, so use looser tolerance
        assert_matrices_close(result_64, result_32, rtol=1e-5)

class TestLinalgAcrossBackends:
    """Ensure all backends produce same results"""
    
    @pytest.mark.parametrize("backend", [
        BLASBackend.REFERENCE,
        BLASBackend.OPENBLAS,
        BLASBackend.ACCELERATE,
        BLASBackend.CUBLAS,
    ])
    def test_matmul_backend_consistency(self, backend):
        if not backend_available(backend):
            pytest.skip(f"{backend} not available")
        
        a = random_matrix(50, 50)
        b = random_matrix(50, 50)
        
        with force_backend(backend):
            result = run("linalg.matmul(a, b)", a=a, b=b)
        
        with force_backend(BLASBackend.REFERENCE):
            expected = run("linalg.matmul(a, b)", a=a, b=b)
        
        assert_matrices_close(result, expected, rtol=1e-10)
```

### Performance Tests

```python
class TestLinalgPerformance:
    def test_matmul_faster_than_naive(self):
        """BLAS matmul should beat naive implementation"""
        n = 500
        a = random_matrix(n, n)
        b = random_matrix(n, n)
        
        # Time BLAS
        t_blas = timeit(
            lambda: run("linalg.matmul(a, b)", a=a, b=b),
            number=10
        )
        
        # Time naive (if we exposed it)
        t_naive = timeit(
            lambda: run("_matmul_naive(a, b)", a=a, b=b),
            number=10
        )
        
        # BLAS should be at least 10x faster for 500x500
        assert t_blas < t_naive / 10
    
    def test_matmul32_faster_than_matmul(self):
        """32-bit should be faster on GPU backends"""
        if detect_blas() not in [BLASBackend.CUBLAS, BLASBackend.ACCELERATE]:
            pytest.skip("GPU BLAS not available")
        
        n = 2000
        a = random_matrix(n, n)
        b = random_matrix(n, n)
        
        t_64 = timeit(lambda: run("linalg.matmul(a, b)", a=a, b=b), number=5)
        t_32 = timeit(lambda: run("linalg.matmul32(a, b)", a=a, b=b), number=5)
        
        # 32-bit should be notably faster
        assert t_32 < t_64 * 0.7
```

---

## Documentation

### User-Facing Documentation

```markdown
# Linear Algebra Module

The `linalg` module provides high-performance linear algebra operations backed
by platform-optimized BLAS libraries.

## Quick Start

```coex
use linalg

a = [[1, 2], [3, 4]]
b = [[5, 6], [7, 8]]

# Matrix multiplication
c = linalg.matmul(a, b)

# Dot product
x = [1, 2, 3]
y = [4, 5, 6]
d = linalg.dot(x, y)  # 32

# Solve linear system Ax = b
solution = linalg.solve(a, [1, 2])
```

## Performance

The module automatically uses the best available BLAS implementation:

- **macOS**: Apple Accelerate (GPU-accelerated)
- **Linux with NVIDIA GPU**: cuBLAS
- **Linux/Windows**: OpenBLAS
- **WebAssembly**: Reference implementation (slower)

For maximum performance on supported hardware, use 32-bit variants:

```coex
# 64-bit precision (default)
result = linalg.matmul(a, b)

# 32-bit precision (faster on GPU)
result = linalg.matmul32(a, b)
```

## Available Functions

### Vector Operations
- `dot(x, y)` - Dot product
- `norm(x)` - Euclidean norm
- `scale(alpha, x)` - Scalar multiplication
- `axpy(alpha, x, y)` - α*x + y

### Matrix-Vector Operations
- `matvec(a, x)` - Matrix-vector product

### Matrix Operations
- `matmul(a, b)` - Matrix multiplication
- `transpose(a)` - Matrix transpose
- `inv(a)` - Matrix inverse
- `det(a)` - Determinant

### Decompositions
- `lu(a)` - LU decomposition
- `qr(a)` - QR decomposition
- `svd(a)` - Singular value decomposition
- `eig(a)` - Eigenvalue decomposition

### Linear Systems
- `solve(a, b)` - Solve Ax = b
```

---

## Summary

The BLAS integration provides Coex with production-quality linear algebra by wrapping platform-native implementations via FFI. Key points:

1. **API Design**: Clean Coex functions (`linalg.matmul`) hide BLAS complexity
2. **Platform Detection**: Compiler automatically selects best available BLAS
3. **Value Semantics**: Preserved despite BLAS's mutable buffer interface
4. **Precision Variants**: 64-bit default, 32-bit for GPU performance
5. **Fallback**: Reference implementation ensures code works everywhere
6. **Testing**: Cross-backend consistency tests ensure correctness

This approach gives Coex users fast, correct linear algebra immediately while maintaining the language's principles.
