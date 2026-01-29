# Coex formula32: 32-bit Precision Formula Kind

## Overview

This document specifies `formula32`, a new function kind for Coex that provides 32-bit precision computation for GPU-accelerated workloads. It complements the existing `formula` kind (64-bit precision) by offering a performance-oriented alternative when full 64-bit precision is unnecessary.

---

## Motivation

GPUs achieve significantly higher throughput at 32-bit precision than 64-bit. On typical hardware:

- NVIDIA consumer GPUs (e.g., RTX 4090): ~64:1 ratio of float32 to float64 throughput
- Apple M-series: Better float64 support, but float32 still substantially faster
- Memory bandwidth: 32-bit values transfer at 2x the rate of 64-bit

For scientific workloads where 32-bit precision suffices (graphics, many simulations, data transformations with bounded ranges), `formula32` enables programmers to opt into this performance benefit with a single keyword change.

---

## Language Specification

### Syntax

```coex
formula32 function_name(parameters) -> return_type {
    body
}
```

The syntax is identical to `formula` except for the kind keyword.

### Examples

```coex
# 32-bit precision magnitude calculation
formula32 magnitude(x: float, y: float, z: float) -> float {
    return sqrt(x*x + y*y + z*z)
}

# 32-bit precision color transformation
formula32 gamma_correct(value: float, gamma: float) -> float {
    return pow(value, 1.0 / gamma)
}

# 32-bit integer hash (values known to be within 32-bit range)
formula32 simple_hash(x: int, y: int) -> int {
    return (x * 73856093) ^ (y * 19349663)
}
```

### Semantics

`formula32` has identical semantic constraints to `formula`:

| Constraint | Description |
|------------|-------------|
| Pure | No side effects |
| Deterministic | Same inputs always produce same outputs |
| No aliasing | Value semantics only |
| No mutable state | Cannot access or modify external state |
| No I/O | Cannot perform input/output operations |

The difference is precision: internal computations execute at 32-bit precision.

**Portability guarantee**: A `formula32` function produces identical results regardless of whether it executes on GPU or CPU. This is a core Coex principle—correctness is never sacrificed for performance. The 32-bit precision semantics (including overflow saturation, precision limits, and rounding behavior) are enforced on all execution targets.

### Type System Behavior

**External interface**: `formula32` functions use standard Coex 64-bit types (`int`, `float`) in their signatures. This maintains type system consistency—callers don't need to know or care about the internal precision.

**Internal computation**: All arithmetic within the formula body executes at 32-bit precision.

**Boundary conversions**:
- **Entry**: 64-bit arguments are narrowed to 32-bit
- **Exit**: 32-bit results are widened to 64-bit

These conversions are implicit and automatic.

### Precision Boundary Behavior

#### Float Narrowing (float64 → float32)

| Input Condition | Behavior |
|-----------------|----------|
| Within float32 range | Rounded to nearest representable float32 |
| Exceeds float32 max (~3.4×10³⁸) | Becomes +∞ or -∞ |
| Below float32 min subnormal (~1.4×10⁻⁴⁵) | Becomes ±0 (flush to zero) |
| NaN | Remains NaN |

#### Integer Narrowing (int64 → int32)

| Input Condition | Behavior |
|-----------------|----------|
| Within int32 range (−2³¹ to 2³¹−1) | Exact conversion |
| Exceeds int32 max | Saturates to 2147483647 |
| Below int32 min | Saturates to -2147483648 |

Saturation semantics are chosen over truncation or undefined behavior because they produce predictable results and match common GPU hardware behavior.

#### Widening (32-bit → 64-bit)

Widening is always exact and lossless.

### Composition Rules

`formula32` and `formula` can call each other freely:

```coex
formula utility(x: float) -> float {
    return x * 2.0
}

formula32 compute(a: float, b: float) -> float {
    # Calling formula from formula32:
    # - a is already 32-bit inside this function
    # - widened to 64-bit for utility() call
    # - result narrowed back to 32-bit
    temp = utility(a)
    return temp + b
}

formula orchestrate(values: [float]) -> [float] {
    # Calling formula32 from formula:
    # - values are 64-bit
    # - narrowed to 32-bit for compute() call
    # - results widened back to 64-bit
    return [compute(v, 1.0) for v in values]
}
```

**Precision at each call site is determined by the callee's kind.** The caller's precision context does not affect how the callee executes.

### GPU Offload Behavior

`formula32` is GPU-offloadable under the same conditions as `formula`:

- Used within iterators (`first`, `most`, `for`)
- Used within comprehensions
- Used in matrix operations

The kernel emitter generates 32-bit types in the GPU kernel source:

| Coex Type | formula (64-bit) | formula32 (32-bit) |
|-----------|------------------|---------------------|
| float | double | float |
| int | long/long long | int |

---

## Compiler Implementation

### Parser Changes

Add `formula32` as a recognized function kind keyword:

```python
# In lexer/token definitions
FORMULA32 = 'formula32'

# In parser grammar (ANTLR4 or equivalent)
function_kind
    : FORMULA
    | FORMULA32
    | FUNC
    | TASK
    | EXTERN
    ;
```

### AST Representation

Extend the function kind enum:

```python
class FunctionKind(Enum):
    FORMULA = auto()
    FORMULA32 = auto()  # New
    FUNC = auto()
    TASK = auto()
    EXTERN = auto()
```

The AST node for function definitions includes the kind:

```python
@dataclass
class FunctionDef:
    name: str
    kind: FunctionKind
    parameters: List[Parameter]
    return_type: CoexType
    body: Expression
    # ... other fields
```

### Semantic Analysis

`formula32` undergoes identical constraint checking to `formula`:

```python
class SemanticAnalyzer:
    def check_function(self, func: FunctionDef):
        if func.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32):
            self._check_formula_constraints(func)
    
    def _check_formula_constraints(self, func: FunctionDef):
        """Verify formula/formula32 constraints."""
        self._check_no_side_effects(func.body)
        self._check_no_mutable_state_access(func.body)
        self._check_no_io_operations(func.body)
        self._check_deterministic(func.body)
        # Constraints are identical for formula and formula32
```

### Symbol Table

Record the function kind for lookup during codegen and offload detection:

```python
@dataclass
class FunctionSymbol:
    name: str
    kind: FunctionKind
    signature: FunctionSignature
    # ...

class SymbolTable:
    def is_formula_kind(self, name: str) -> bool:
        """Check if function is formula or formula32."""
        sym = self.lookup(name)
        return sym and sym.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32)
    
    def is_32bit_precision(self, name: str) -> bool:
        """Check if function uses 32-bit precision."""
        sym = self.lookup(name)
        return sym and sym.kind == FunctionKind.FORMULA32
```

### Offload Detection

Update the offload detector to recognize `formula32`:

```python
class OffloadDetector:
    def is_offloadable_formula(self, func_name: str) -> bool:
        """Check if function is offload-eligible (formula or formula32)."""
        sym = self.symbol_table.lookup(func_name)
        return sym is not None and sym.kind in (
            FunctionKind.FORMULA,
            FunctionKind.FORMULA32
        )
    
    def get_precision(self, func_name: str) -> int:
        """Get precision bits for a formula function."""
        sym = self.symbol_table.lookup(func_name)
        if sym is None:
            raise ValueError(f"Unknown function: {func_name}")
        if sym.kind == FunctionKind.FORMULA32:
            return 32
        elif sym.kind == FunctionKind.FORMULA:
            return 64
        else:
            raise ValueError(f"Not a formula kind: {func_name}")
```

### Kernel Emitter Updates

Extend the kernel emitter to handle precision:

```python
class KernelEmitter:
    def __init__(self, backend: GPUBackend):
        self.backend = backend
    
    def emit_map_kernel(self,
                        kernel_name: str,
                        formula_body: str,
                        input_params: List[Tuple[str, str]],
                        output_type: str,
                        precision: int = 64) -> str:  # New parameter
        """Emit a map-style kernel.
        
        Args:
            kernel_name: Unique name for this kernel
            formula_body: The formula body transpiled to C-like syntax
            input_params: List of (parameter_name, coex_type) tuples
            output_type: Coex type of output elements
            precision: Bit width for computation (32 or 64)
            
        Returns:
            Complete kernel source code for the target backend
        """
        if self.backend == GPUBackend.METAL:
            return self._emit_metal_map(kernel_name, formula_body,
                                        input_params, output_type, precision)
        elif self.backend == GPUBackend.CUDA:
            return self._emit_cuda_map(kernel_name, formula_body,
                                       input_params, output_type, precision)
        else:
            raise ValueError(f"Cannot emit kernel for backend: {self.backend}")
    
    def _coex_to_metal_type(self, coex_type: str, precision: int) -> str:
        """Map Coex type to Metal type at specified precision."""
        if precision == 32:
            mapping = {
                'int': 'int',
                'float': 'float',
                'bool': 'bool',
            }
        else:  # 64-bit
            mapping = {
                'int': 'long',
                'float': 'double',  # Note: limited support on some GPUs
                'bool': 'bool',
            }
        return mapping.get(coex_type, coex_type)
    
    def _coex_to_cuda_type(self, coex_type: str, precision: int) -> str:
        """Map Coex type to CUDA type at specified precision."""
        if precision == 32:
            mapping = {
                'int': 'int',
                'float': 'float',
                'bool': 'bool',
            }
        else:  # 64-bit
            mapping = {
                'int': 'long long',
                'float': 'double',
                'bool': 'bool',
            }
        return mapping.get(coex_type, coex_type)
```

### Updated Metal Kernel Emission

```python
def _emit_metal_map(self, kernel_name: str, formula_body: str,
                    input_params: List[Tuple[str, str]],
                    output_type: str, precision: int) -> str:
    """Emit Metal Shading Language kernel."""
    
    metal_output_type = self._coex_to_metal_type(output_type, precision)
    
    # Build buffer parameters (always 64-bit at interface)
    buffer_params = []
    buffer_idx = 0
    for param_name, param_type in input_params:
        # Interface uses 64-bit types
        interface_type = self._coex_to_metal_type(param_type, 64)
        buffer_params.append(
            f"device const {interface_type}* {param_name}_in [[buffer({buffer_idx})]]"
        )
        buffer_idx += 1
    
    # Output buffer (64-bit interface)
    interface_output = self._coex_to_metal_type(output_type, 64)
    buffer_params.append(
        f"device {interface_output}* _output [[buffer({buffer_idx})]]"
    )
    buffer_params.append("uint _id [[thread_position_in_grid]]")
    
    params_str = ",\n    ".join(buffer_params)
    
    # Generate narrowing loads for 32-bit precision
    if precision == 32:
        loads = self._emit_metal_narrowing_loads(input_params)
        store = f"_output[_id] = ({interface_output})_result;"
    else:
        loads = self._emit_metal_loads_64(input_params)
        store = "_output[_id] = _result;"
    
    compute_type = self._coex_to_metal_type(output_type, precision)
    
    return f'''#include <metal_stdlib>
using namespace metal;

kernel void {kernel_name}(
    {params_str}
) {{
    // Load and narrow inputs (64-bit -> {precision}-bit)
{loads}
    
    // Formula body (computed at {precision}-bit precision)
    {compute_type} _result = {formula_body};
    
    // Widen and store output ({precision}-bit -> 64-bit)
    {store}
}}
'''

def _emit_metal_narrowing_loads(self, input_params: List[Tuple[str, str]]) -> str:
    """Emit Metal input loads with 64->32 narrowing."""
    loads = []
    for param_name, param_type in input_params:
        type_64 = self._coex_to_metal_type(param_type, 64)
        type_32 = self._coex_to_metal_type(param_type, 32)
        loads.append(
            f"    {type_32} _{param_name} = ({type_32}){param_name}_in[_id];"
        )
    return "\n".join(loads)
```

### Updated CUDA Kernel Emission

```python
def _emit_cuda_map(self, kernel_name: str, formula_body: str,
                   input_params: List[Tuple[str, str]],
                   output_type: str, precision: int) -> str:
    """Emit CUDA C++ kernel."""
    
    # Build parameters (64-bit interface)
    params = []
    for param_name, param_type in input_params:
        cuda_type = self._coex_to_cuda_type(param_type, 64)
        params.append(f"const {cuda_type}* {param_name}_in")
    
    output_interface = self._coex_to_cuda_type(output_type, 64)
    params.append(f"{output_interface}* _output")
    params.append("int _n")
    
    params_str = ",\n    ".join(params)
    
    # Generate loads with optional narrowing
    if precision == 32:
        loads = self._emit_cuda_narrowing_loads(input_params)
        compute_type = self._coex_to_cuda_type(output_type, 32)
        store = f"_output[_id] = ({output_interface})_result;"
    else:
        loads = self._emit_cuda_loads_64(input_params)
        compute_type = self._coex_to_cuda_type(output_type, 64)
        store = "_output[_id] = _result;"
    
    return f'''extern "C" __global__
void {kernel_name}(
    {params_str}
) {{
    int _id = blockIdx.x * blockDim.x + threadIdx.x;
    if (_id < _n) {{
        // Load and narrow inputs (64-bit -> {precision}-bit)
{loads}
        
        // Formula body (computed at {precision}-bit precision)
        {compute_type} _result = {formula_body};
        
        // Widen and store output ({precision}-bit -> 64-bit)
        {store}
    }}
}}
'''

def _emit_cuda_narrowing_loads(self, input_params: List[Tuple[str, str]]) -> str:
    """Emit CUDA input loads with 64->32 narrowing."""
    loads = []
    for param_name, param_type in input_params:
        type_64 = self._coex_to_cuda_type(param_type, 64)
        type_32 = self._coex_to_cuda_type(param_type, 32)
        loads.append(
            f"        {type_32} _{param_name} = ({type_32}){param_name}_in[_id];"
        )
    return "\n".join(loads)
```

### Codegen Integration

Update the codegen visitor to pass precision information:

```python
class CodegenVisitor:
    def _emit_gpu_comprehension(self, candidate: OffloadCandidate):
        """Emit GPU-accelerated comprehension."""
        kernel_name = self._generate_kernel_name()
        
        # Determine precision from the formula's kind
        formula_name = self._extract_formula_name(candidate.formula_expr)
        precision = self.offload_detector.get_precision(formula_name)
        
        # Transpile formula body
        formula_body = self._transpile_formula(candidate.formula_expr)
        
        # Extract parameters and types
        input_params = self._extract_formula_params(candidate.formula_expr)
        output_type = self._infer_output_type(candidate.formula_expr)
        
        # Emit kernel with appropriate precision
        kernel_source = self.kernel_emitter.emit_map_kernel(
            kernel_name, formula_body, input_params, output_type,
            precision=precision  # Pass precision to emitter
        )
        
        return self._emit_dispatch_call(kernel_source, kernel_name,
                                         candidate.collection_expr)
```

### CPU Fallback

When no GPU backend is available, `formula32` executes on CPU but **preserves 32-bit precision semantics**. This ensures identical results regardless of execution target—a core Coex principle.

The CPU fallback for `formula32`:

1. Narrows 64-bit inputs to 32-bit at function entry
2. Performs all computation using 32-bit CPU operations
3. Applies saturation for integer overflow (same as GPU behavior)
4. Widens 32-bit results back to 64-bit at function exit

This approach prioritizes correctness and portability over CPU performance. A `formula32` function produces identical results whether it runs on a GPU, on a CPU as fallback, or on a machine with no GPU support at all.

```python
def _emit_cpu_fallback(self, candidate: OffloadCandidate):
    """Emit CPU execution for formula/formula32.
    
    formula executes at 64-bit precision.
    formula32 executes at 32-bit precision with explicit narrowing/widening.
    """
    precision = self.offload_detector.get_precision(
        self._extract_formula_name(candidate.formula_expr)
    )
    
    if precision == 32:
        return self._emit_task_parallel_map_32bit(candidate)
    else:
        return self._emit_task_parallel_map(candidate)

def _emit_task_parallel_map_32bit(self, candidate: OffloadCandidate):
    """Emit CPU execution with 32-bit precision semantics.
    
    Generates code that:
    - Narrows inputs from 64-bit to 32-bit (with saturation for ints)
    - Computes using 32-bit operations
    - Widens outputs from 32-bit to 64-bit
    """
    # Implementation uses numpy.float32/numpy.int32 or equivalent
    # to ensure 32-bit computation semantics on CPU
    ...
```

#### CPU 32-bit Implementation Details

For CPU execution of `formula32`, the compiler generates code using explicit 32-bit types:

```python
import numpy as np

def cpu_formula32_wrapper(func):
    """Wrap a formula32 for CPU execution with 32-bit semantics."""
    def wrapper(*args):
        # Narrow inputs
        narrowed = []
        for arg in args:
            if isinstance(arg, float):
                narrowed.append(np.float32(arg))
            elif isinstance(arg, int):
                # Saturate to int32 range
                clamped = max(-2147483648, min(2147483647, arg))
                narrowed.append(np.int32(clamped))
            elif isinstance(arg, (list, np.ndarray)):
                # Narrow arrays element-wise
                narrowed.append(narrow_array(arg))
            else:
                narrowed.append(arg)
        
        # Execute at 32-bit precision
        result = func(*narrowed)
        
        # Widen output
        if isinstance(result, np.float32):
            return float(result)
        elif isinstance(result, np.int32):
            return int(result)
        elif isinstance(result, np.ndarray):
            return widen_array(result)
        else:
            return result
    
    return wrapper
```

This ensures that overflow, precision loss, and saturation behavior are identical between GPU and CPU execution paths.

---

## Testing

### Unit Tests

```python
class TestFormula32Parsing:
    def test_formula32_keyword_recognized(self):
        source = """
        formula32 test(x: float) -> float {
            return x * 2.0
        }
        """
        ast = parse(source)
        assert ast.functions[0].kind == FunctionKind.FORMULA32
    
    def test_formula32_same_constraints_as_formula(self):
        # Side effects should be rejected
        source = """
        formula32 bad(x: float) -> float {
            print(x)  # Side effect!
            return x
        }
        """
        with pytest.raises(SemanticError):
            compile(source)

class TestFormula32KernelEmission:
    def test_metal_uses_float_not_double(self):
        emitter = KernelEmitter(GPUBackend.METAL)
        source = emitter.emit_map_kernel(
            "test", "_x * 2.0", [("x", "float")], "float",
            precision=32
        )
        # Should use float, not double
        assert "float _result" in source
        assert "double" not in source
    
    def test_cuda_uses_float_not_double(self):
        emitter = KernelEmitter(GPUBackend.CUDA)
        source = emitter.emit_map_kernel(
            "test", "_x * 2.0", [("x", "float")], "float",
            precision=32
        )
        assert "float _result" in source
        assert "double" not in source
    
    def test_narrowing_conversion_emitted(self):
        emitter = KernelEmitter(GPUBackend.CUDA)
        source = emitter.emit_map_kernel(
            "test", "_x * 2.0", [("x", "float")], "float",
            precision=32
        )
        # Should cast from 64-bit input to 32-bit local
        assert "(float)" in source

class TestFormula32Composition:
    def test_formula32_can_call_formula(self):
        source = """
        formula utility(x: float) -> float {
            return x + 1.0
        }
        
        formula32 compute(x: float) -> float {
            return utility(x) * 2.0
        }
        """
        # Should compile without error
        ast = compile(source)
        assert ast is not None
    
    def test_formula_can_call_formula32(self):
        source = """
        formula32 fast_op(x: float) -> float {
            return sqrt(x)
        }
        
        formula compute(x: float) -> float {
            return fast_op(x) + 1.0
        }
        """
        ast = compile(source)
        assert ast is not None
```

### Integration Tests (GPU Required)

```python
@pytest.mark.gpu
class TestFormula32Execution:
    def test_basic_formula32_execution(self):
        source = """
        formula32 double(x: float) -> float {
            return x * 2.0
        }
        
        func main() -> [float] {
            return [double(x) for x in [1.0, 2.0, 3.0]]
        }
        """
        result = compile_and_run(source)
        assert_arrays_almost_equal(result, [2.0, 4.0, 6.0])
    
    def test_formula32_gpu_cpu_equivalence(self):
        """Critical: formula32 must produce identical results on GPU and CPU."""
        source = """
        formula32 compute(x: float, y: float) -> float {
            return sqrt(x*x + y*y) + sin(x) * cos(y)
        }
        
        func main(xs: [float], ys: [float]) -> [float] {
            return [compute(xs[i], ys[i]) for i in range(len(xs))]
        }
        """
        
        # Test with values that stress 32-bit precision boundaries
        xs = [1.0, 1e-10, 1e10, 3.14159265358979]
        ys = [2.0, 1e-10, 1e10, 2.71828182845904]
        
        # Force CPU execution
        with gpu_backend_override(GPUBackend.NONE):
            cpu_result = compile_and_run(source, xs, ys)
        
        # Force GPU execution
        with gpu_backend_override(detect_gpu_backend()):
            gpu_result = compile_and_run(source, xs, ys)
        
        # Results must be identical (not just close—identical)
        assert cpu_result == gpu_result, \
            f"CPU/GPU results differ: {cpu_result} vs {gpu_result}"
    
    def test_formula32_precision_loss_consistent(self):
        """Verify that precision loss is consistent across backends."""
        source = """
        formula32 add_small(x: float) -> float {
            return x + 1e-10
        }
        
        func main() -> float {
            return add_small(1.0)
        }
        """
        # 1e-10 may be lost when added to 1.0 in float32
        # Both CPU and GPU should produce the same (imprecise) result
        
        with gpu_backend_override(GPUBackend.NONE):
            cpu_result = compile_and_run(source)
        
        if detect_gpu_backend() != GPUBackend.NONE:
            with gpu_backend_override(detect_gpu_backend()):
                gpu_result = compile_and_run(source)
            assert cpu_result == gpu_result
    
    def test_formula32_saturation_consistent(self):
        """Verify integer saturation is consistent across backends."""
        source = """
        formula32 add_ints(x: int, y: int) -> int {
            return x + y
        }
        
        func main() -> int {
            big = 2147483647  # int32 max
            return add_ints(big, 100)
        }
        """
        # Should saturate to int32 max on both CPU and GPU
        
        with gpu_backend_override(GPUBackend.NONE):
            cpu_result = compile_and_run(source)
        
        if detect_gpu_backend() != GPUBackend.NONE:
            with gpu_backend_override(detect_gpu_backend()):
                gpu_result = compile_and_run(source)
            assert cpu_result == gpu_result
        
        # Both should saturate to int32 max
        assert cpu_result == 2147483647

@pytest.mark.gpu
class TestFormula32Performance:
    """Verify that formula32 actually provides performance benefit on GPU."""
    
    def test_formula32_faster_than_formula_on_gpu(self):
        """formula32 should execute faster than formula for large GPU workloads."""
        setup = """
        formula slow_magnitude(x: float, y: float, z: float) -> float {
            return sqrt(x*x + y*y + z*z)
        }
        
        formula32 fast_magnitude(x: float, y: float, z: float) -> float {
            return sqrt(x*x + y*y + z*z)
        }
        """
        
        n = 10_000_000
        xs = [random.random() for _ in range(n)]
        ys = [random.random() for _ in range(n)]
        zs = [random.random() for _ in range(n)]
        
        # Time formula (64-bit)
        t64 = timeit(lambda: run(setup + """
            func main(xs, ys, zs) {
                return [slow_magnitude(xs[i], ys[i], zs[i]) for i in range(len(xs))]
            }
        """, xs, ys, zs), number=10)
        
        # Time formula32 (32-bit)
        t32 = timeit(lambda: run(setup + """
            func main(xs, ys, zs) {
                return [fast_magnitude(xs[i], ys[i], zs[i]) for i in range(len(xs))]
            }
        """, xs, ys, zs), number=10)
        
        # formula32 should be notably faster (at least 1.5x on most GPUs)
        assert t32 < t64 * 0.8, f"Expected speedup not achieved: {t64/t32:.2f}x"
```

---

## Documentation

### User-Facing Documentation

```markdown
## Function Kinds

Coex has five function kinds:

| Kind | Description |
|------|-------------|
| `func` | Standard imperative function |
| `task` | Concurrent function (runs on thread pool) |
| `formula` | Pure function (64-bit precision, GPU-offloadable) |
| `formula32` | Pure function (32-bit precision, GPU-offloadable) |
| `extern` | External C function declaration |

### formula vs formula32

Both `formula` and `formula32` are pure functions with identical constraints:
no side effects, no mutable state, deterministic results. The difference is
internal computation precision.

Use `formula` (default) when:
- You need full 64-bit floating-point precision
- Numerical accuracy is critical
- You're unsure which to use

Use `formula32` when:
- Your values fit comfortably in 32-bit range
- You're optimizing GPU performance
- Precision beyond ~7 significant digits isn't needed

**Example:**

```coex
# Standard 64-bit precision
formula accurate_sum(values: [float]) -> float {
    return reduce(values, 0.0, (acc, x) -> acc + x)
}

# 32-bit precision for GPU performance
formula32 fast_magnitude(x: float, y: float, z: float) -> float {
    return sqrt(x*x + y*y + z*z)
}
```

### Precision Boundaries

`formula32` functions accept and return standard 64-bit Coex types. The
narrowing (64→32) and widening (32→64) conversions happen automatically
at the function boundary.

**Float behavior:**
- Values exceeding float32 range become ±infinity
- Very small values may flush to zero
- Precision is limited to ~7 significant decimal digits

**Integer behavior:**
- Values exceeding int32 range saturate to ±2,147,483,647
- No silent overflow or wraparound

### Composition

`formula` and `formula32` can call each other freely. Each function executes
at its declared precision regardless of its caller's precision.
```

---

## Migration Notes

### Upgrading Existing Formulas

To convert a `formula` to `formula32` for GPU performance:

1. Verify value ranges fit within 32-bit limits
2. Verify precision requirements are ≤7 significant digits
3. Change keyword from `formula` to `formula32`
4. Test numerical accuracy against original

```coex
# Before
formula compute(x: float) -> float {
    return sqrt(x * x + 1.0)
}

# After (if 32-bit precision is acceptable)
formula32 compute(x: float) -> float {
    return sqrt(x * x + 1.0)
}
```

---

## Summary

`formula32` extends Coex's GPU compute capability by allowing programmers to opt into 32-bit precision for performance-critical formulas. The implementation requires:

1. **Parser**: Recognize `formula32` keyword
2. **AST**: Add `FORMULA32` to function kind enum
3. **Semantic analysis**: Apply same constraints as `formula`
4. **Offload detection**: Treat `formula32` as offload-eligible
5. **Kernel emission**: Use 32-bit types, emit narrowing/widening at boundaries
6. **CPU fallback**: Execute at 32-bit precision using numpy.float32/int32

**Core principle**: `formula32` produces identical results on all execution targets (GPU, CPU fallback, machines without GPU support). Coex prioritizes correctness over performance—the 32-bit precision semantics are guaranteed regardless of where the code runs. This enables reliable testing, debugging, and cross-platform deployment without behavioral surprises.
