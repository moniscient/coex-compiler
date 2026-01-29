# Coex GPU Offload: Architecture, Specification, and Implementation Guide

## Executive Summary

This document specifies the GPU offload feature for Coex's `formula` function kind. The design philosophy prioritizes semantic clarity over performance hints: specific language idioms (iterators, matrix operations, comprehensions with formulas) signal GPU offload intent. The implementation uses a compile-time backend selection strategy with Python-based GPU libraries for initial development, enabling rapid prototyping while maintaining a clear path to production optimization.

---

## Part 1: Architecture

### 1.1 Design Philosophy

Coex's approach to GPU offload follows three core principles:

1. **Idiom as Intent**: Rather than programmer hints or pragma annotations, specific language constructs signal parallelization intent. If you write `first(collection, predicate_formula)` or a comprehension with formula bodies, you are declaring data-parallel semantics.

2. **Deterministic Execution Model**: The compiler's behavior is predictable. Offload-eligible constructs dispatch to GPU when a GPU backend is available; otherwise they fall back to CPU. There are no heuristics deciding "is this worth offloading."

3. **Optimize Against Evidence**: Initial implementation prioritizes correctness and simplicity. Performance optimization occurs only after profiling reveals actual bottlenecks, and then in magnitude order.

### 1.2 Formula-to-GPU Semantic Mapping

Coex formulas possess properties that map naturally to GPU execution:

- No side effects (pure functions)
- No aliasing (value semantics throughout)
- No mutable state (only atomics are mutable, and those aren't in formulas)
- Explicit data dependencies

These constraints mean formula bodies can execute in arbitrary order across thousands of parallel invocations without synchronization—exactly the GPU execution model.

### 1.3 Backend Selection Strategy

The compiler detects available GPU toolchains at compile time, not hardware at runtime. Detection sequence:

```
1. Check for Metal SDK availability (macOS)
2. Check for CUDA toolkit availability (Linux/Windows with NVIDIA)
3. Check for ROCm/HIP availability (Linux with AMD) [future]
4. Fall back to formula-as-task-alias (CPU)
```

This selection happens once per compilation. All offload-eligible constructs route to the selected backend uniformly.

### 1.4 Compiler Pipeline Integration

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Coex Source                                  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ANTLR4 Parser → AST                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Semantic Analysis                                │
│         (Type checking, formula constraint verification)             │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
    ┌───────────────────────────┐   ┌───────────────────────────────┐
    │   Offload-Eligible?       │   │   Standard Codegen Path       │
    │   (iterator/matrix/       │   │   (LLVM-IR via llvmlite)      │
    │    comprehension check)   │   │                               │
    └───────────────────────────┘   └───────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
    ┌───────┐   ┌───────┐   ┌───────┐
    │ Metal │   │ CUDA  │   │ CPU   │
    │ Back- │   │ Back- │   │ Fall- │
    │ end   │   │ end   │   │ back  │
    └───────┘   └───────┘   └───────┘
        │           │           │
        ▼           ▼           ▼
    ┌───────┐   ┌───────┐   ┌───────┐
    │  MSL  │   │ CUDA  │   │ Task  │
    │Source │   │  C++  │   │ Alias │
    └───────┘   └───────┘   └───────┘
```

### 1.5 Why AST-to-GPU-Source (Not LLVM-IR)

The compiler goes directly from AST to GPU kernel source (Metal Shading Language or CUDA C++) rather than through LLVM-IR because:

1. **Target compiler expectations**: Metal and CUDA compilers expect high-level C++-like source, not assembly-level IR. They perform their own optimization passes.

2. **Semantic preservation**: The AST retains high-level intent (this is a formula over a collection, these are the dependencies) that would be lost in LLVM-IR lowering.

3. **Simplicity**: The current compiler has no intermediate representation between AST and LLVM-IR. Adding a GPU path from the AST is cleaner than creating a new IR stage.

4. **Irrelevant decisions avoided**: LLVM-IR commits to memory layouts, calling conventions, and control flow representations that Metal/CUDA compilers will override anyway.

---

## Part 2: Specification

### 2.1 Offload-Eligible Constructs

The following Coex constructs trigger GPU offload when their bodies/predicates are formulas:

#### 2.1.1 Iterators with Formula Predicates/Bodies

```coex
# first: find first element satisfying predicate
result = first(collection, predicate_formula)

# most: find all elements satisfying predicate  
results = most(collection, predicate_formula)

# for: apply formula to each element
for item in collection {
    formula_call(item)
}
```

#### 2.1.2 Comprehensions with Formula Bodies

```coex
# Map operation: apply formula to each element
results = [transform_formula(x) for x in collection]

# Filter-map: predicate and transform are both formulas
results = [transform_formula(x) for x in collection if predicate_formula(x)]
```

#### 2.1.3 Matrix Operations

```coex
# Matrix operations with formula element functions
result = matrix_map(m, element_formula)
result = matrix_multiply(a, b)  # Built-in, always GPU-eligible
```

### 2.2 Kernel Generation Specification

#### 2.2.1 Metal Shading Language Output

For a Coex formula:

```coex
formula double(x: float) -> float {
    return x * 2.0
}

# Used in comprehension:
results = [double(x) for x in numbers]
```

The compiler emits:

```metal
#include <metal_stdlib>
using namespace metal;

kernel void coex_double_map(
    device const float* input [[buffer(0)]],
    device float* output [[buffer(1)]],
    uint id [[thread_position_in_grid]]
) {
    // Formula body inlined
    float x = input[id];
    output[id] = x * 2.0;
}
```

#### 2.2.2 CUDA C++ Output

For the same formula:

```cuda
extern "C" __global__
void coex_double_map(
    const float* input,
    float* output,
    int n
) {
    int id = blockIdx.x * blockDim.x + threadIdx.x;
    if (id < n) {
        // Formula body inlined
        float x = input[id];
        output[id] = x * 2.0;
    }
}
```

#### 2.2.3 Type Mapping

| Coex Type | Metal Type | CUDA Type |
|-----------|------------|-----------|
| int | int | int |
| int64 | long | long long |
| float | float | float |
| float64 | double | double |
| bool | bool | bool |
| [T] (array) | device T* | T* |

### 2.3 Dispatch Specification

#### 2.3.1 Metal Dispatch (via metalcompute)

```python
import metalcompute as mc

def dispatch_metal(kernel_source: str, function_name: str, 
                   input_buffers: list, output_buffer, count: int):
    dev = mc.Device()
    kernel = dev.kernel(kernel_source).function(function_name)
    kernel(count, *input_buffers, output_buffer)
```

#### 2.3.2 CUDA Dispatch (via CuPy)

```python
import cupy as cp

def dispatch_cuda(kernel_source: str, function_name: str,
                  input_arrays: list, output_array, count: int):
    kernel = cp.RawKernel(kernel_source, function_name)
    block_size = 256
    grid_size = (count + block_size - 1) // block_size
    kernel((grid_size,), (block_size,), (*input_arrays, output_array, count))
```

### 2.4 Fallback Specification

When no GPU backend is available, offload-eligible constructs execute as task aliases:

```coex
# This comprehension with formula body:
results = [transform(x) for x in collection]

# Falls back to equivalent task-based execution:
results = parallel_map(collection, transform)  # Uses work-stealing thread pool
```

The formula constraints are still enforced by the compiler regardless of execution backend.

### 2.5 Error Handling

| Condition | Behavior |
|-----------|----------|
| No GPU backend available | Silent fallback to CPU (task alias) |
| GPU compilation error | Compile-time error with MSL/CUDA error message |
| GPU runtime error | Runtime exception with device error details |
| Unsupported type in formula | Compile-time error before GPU codegen |

---

## Part 3: Implementation Guide

### 3.1 Phase 1: Metal Backend (Development Machine)

#### 3.1.1 Prerequisites

```bash
# Install metalcompute
pip install metalcompute
```

#### 3.1.2 Implementation Steps

**Step 1: Backend Detection Module**

Create `coex/gpu/detection.py`:

```python
"""GPU backend detection for Coex compiler."""

from enum import Enum, auto
from typing import Optional

class GPUBackend(Enum):
    METAL = auto()
    CUDA = auto()
    NONE = auto()

_cached_backend: Optional[GPUBackend] = None

def detect_gpu_backend() -> GPUBackend:
    """Detect available GPU backend at compile time.
    
    Returns the first available backend in priority order:
    1. Metal (macOS)
    2. CUDA (NVIDIA)
    3. NONE (CPU fallback)
    """
    global _cached_backend
    if _cached_backend is not None:
        return _cached_backend
    
    # Try Metal first (macOS development machine)
    try:
        import metalcompute as mc
        dev = mc.Device()
        _cached_backend = GPUBackend.METAL
        return _cached_backend
    except (ImportError, Exception):
        pass
    
    # Try CUDA
    try:
        import cupy as cp
        # Verify CUDA is actually available
        cp.cuda.runtime.getDeviceCount()
        _cached_backend = GPUBackend.CUDA
        return _cached_backend
    except (ImportError, Exception):
        pass
    
    _cached_backend = GPUBackend.NONE
    return _cached_backend

def get_backend_name() -> str:
    """Return human-readable backend name for diagnostics."""
    backend = detect_gpu_backend()
    return {
        GPUBackend.METAL: "Metal (Apple GPU)",
        GPUBackend.CUDA: "CUDA (NVIDIA GPU)",
        GPUBackend.NONE: "CPU (no GPU backend available)"
    }[backend]
```

**Step 2: Kernel Source Emitter**

Create `coex/gpu/kernel_emitter.py`:

```python
"""Emit GPU kernel source from Coex AST."""

from typing import List, Tuple
from coex.gpu.detection import GPUBackend

class KernelEmitter:
    """Emits GPU kernel source code from formula AST nodes."""
    
    def __init__(self, backend: GPUBackend):
        self.backend = backend
        
    def emit_map_kernel(self, 
                        kernel_name: str,
                        formula_body: str,  # Transpiled formula body
                        input_params: List[Tuple[str, str]],  # [(name, type), ...]
                        output_type: str) -> str:
        """Emit a map-style kernel for comprehensions.
        
        Args:
            kernel_name: Unique name for this kernel
            formula_body: The formula body transpiled to C-like syntax
            input_params: List of (parameter_name, coex_type) tuples
            output_type: Coex type of output elements
            
        Returns:
            Complete kernel source code for the target backend
        """
        if self.backend == GPUBackend.METAL:
            return self._emit_metal_map(kernel_name, formula_body, 
                                        input_params, output_type)
        elif self.backend == GPUBackend.CUDA:
            return self._emit_cuda_map(kernel_name, formula_body,
                                       input_params, output_type)
        else:
            raise ValueError(f"Cannot emit kernel for backend: {self.backend}")
    
    def _emit_metal_map(self, kernel_name: str, formula_body: str,
                        input_params: List[Tuple[str, str]], 
                        output_type: str) -> str:
        """Emit Metal Shading Language kernel."""
        
        metal_output_type = self._coex_to_metal_type(output_type)
        
        # Build buffer parameters
        buffer_params = []
        buffer_idx = 0
        for param_name, param_type in input_params:
            metal_type = self._coex_to_metal_type(param_type)
            buffer_params.append(
                f"device const {metal_type}* {param_name} [[buffer({buffer_idx})]]"
            )
            buffer_idx += 1
        
        # Output buffer
        buffer_params.append(
            f"device {metal_output_type}* _output [[buffer({buffer_idx})]]"
        )
        
        # Thread index
        buffer_params.append("uint _id [[thread_position_in_grid]]")
        
        params_str = ",\n    ".join(buffer_params)
        
        return f'''#include <metal_stdlib>
using namespace metal;

kernel void {kernel_name}(
    {params_str}
) {{
    // Load inputs for this thread
{self._emit_metal_input_loads(input_params)}
    
    // Formula body
    {metal_output_type} _result = {formula_body};
    
    // Store output
    _output[_id] = _result;
}}
'''
    
    def _emit_cuda_map(self, kernel_name: str, formula_body: str,
                       input_params: List[Tuple[str, str]],
                       output_type: str) -> str:
        """Emit CUDA C++ kernel."""
        
        cuda_output_type = self._coex_to_cuda_type(output_type)
        
        # Build parameters
        params = []
        for param_name, param_type in input_params:
            cuda_type = self._coex_to_cuda_type(param_type)
            params.append(f"const {cuda_type}* {param_name}")
        
        params.append(f"{cuda_output_type}* _output")
        params.append("int _n")
        
        params_str = ",\n    ".join(params)
        
        return f'''extern "C" __global__
void {kernel_name}(
    {params_str}
) {{
    int _id = blockIdx.x * blockDim.x + threadIdx.x;
    if (_id < _n) {{
        // Load inputs for this thread
{self._emit_cuda_input_loads(input_params)}
        
        // Formula body
        {cuda_output_type} _result = {formula_body};
        
        // Store output
        _output[_id] = _result;
    }}
}}
'''
    
    def _emit_metal_input_loads(self, input_params: List[Tuple[str, str]]) -> str:
        """Emit Metal input loading statements."""
        loads = []
        for param_name, param_type in input_params:
            metal_type = self._coex_to_metal_type(param_type)
            loads.append(f"    {metal_type} _{param_name} = {param_name}[_id];")
        return "\n".join(loads)
    
    def _emit_cuda_input_loads(self, input_params: List[Tuple[str, str]]) -> str:
        """Emit CUDA input loading statements."""
        loads = []
        for param_name, param_type in input_params:
            cuda_type = self._coex_to_cuda_type(param_type)
            loads.append(f"        {cuda_type} _{param_name} = {param_name}[_id];")
        return "\n".join(loads)
    
    def _coex_to_metal_type(self, coex_type: str) -> str:
        """Map Coex type to Metal type."""
        mapping = {
            'int': 'int',
            'int64': 'long',
            'float': 'float',
            'float64': 'double',  # Note: check device support
            'bool': 'bool',
        }
        return mapping.get(coex_type, coex_type)
    
    def _coex_to_cuda_type(self, coex_type: str) -> str:
        """Map Coex type to CUDA type."""
        mapping = {
            'int': 'int',
            'int64': 'long long',
            'float': 'float',
            'float64': 'double',
            'bool': 'bool',
        }
        return mapping.get(coex_type, coex_type)
```

**Step 3: GPU Dispatch Runtime**

Create `coex/gpu/dispatch.py`:

```python
"""GPU kernel dispatch for Coex runtime."""

from typing import Any, List
from coex.gpu.detection import GPUBackend, detect_gpu_backend

class GPUDispatcher:
    """Dispatches compiled kernels to GPU backends."""
    
    def __init__(self):
        self.backend = detect_gpu_backend()
        self._metal_device = None
        self._kernel_cache = {}
        
    def dispatch_map(self,
                     kernel_source: str,
                     kernel_name: str,
                     input_arrays: List[Any],
                     count: int) -> Any:
        """Dispatch a map-style kernel.
        
        Args:
            kernel_source: Complete kernel source code
            kernel_name: Name of the kernel function
            input_arrays: List of input arrays
            count: Number of elements to process
            
        Returns:
            Output array with results
        """
        if self.backend == GPUBackend.METAL:
            return self._dispatch_metal(kernel_source, kernel_name,
                                        input_arrays, count)
        elif self.backend == GPUBackend.CUDA:
            return self._dispatch_cuda(kernel_source, kernel_name,
                                       input_arrays, count)
        else:
            raise RuntimeError("No GPU backend available")
    
    def _dispatch_metal(self, kernel_source: str, kernel_name: str,
                        input_arrays: List[Any], count: int) -> Any:
        """Dispatch kernel via Metal."""
        import metalcompute as mc
        from array import array
        
        # Lazy init device
        if self._metal_device is None:
            self._metal_device = mc.Device()
        
        # Compile kernel (metalcompute caches internally)
        cache_key = (kernel_source, kernel_name)
        if cache_key not in self._kernel_cache:
            compiled = self._metal_device.kernel(kernel_source)
            self._kernel_cache[cache_key] = compiled.function(kernel_name)
        
        kernel = self._kernel_cache[cache_key]
        
        # Prepare output buffer
        # Assuming float output for now; extend based on type info
        output_buffer = self._metal_device.buffer(count * 4)
        
        # Dispatch
        kernel(count, *input_arrays, output_buffer)
        
        # Return as memoryview for zero-copy access
        return memoryview(output_buffer).cast('f')
    
    def _dispatch_cuda(self, kernel_source: str, kernel_name: str,
                       input_arrays: List[Any], count: int) -> Any:
        """Dispatch kernel via CUDA."""
        import cupy as cp
        
        # Compile kernel (CuPy caches internally)
        cache_key = (kernel_source, kernel_name)
        if cache_key not in self._kernel_cache:
            self._kernel_cache[cache_key] = cp.RawKernel(kernel_source, kernel_name)
        
        kernel = self._kernel_cache[cache_key]
        
        # Convert inputs to CuPy arrays if needed
        gpu_inputs = []
        for arr in input_arrays:
            if isinstance(arr, cp.ndarray):
                gpu_inputs.append(arr)
            else:
                gpu_inputs.append(cp.asarray(arr, dtype=cp.float32))
        
        # Allocate output
        output = cp.empty(count, dtype=cp.float32)
        
        # Calculate grid/block dimensions
        block_size = 256
        grid_size = (count + block_size - 1) // block_size
        
        # Dispatch
        kernel((grid_size,), (block_size,), (*gpu_inputs, output, count))
        
        return output


# Global dispatcher instance
_dispatcher = None

def get_dispatcher() -> GPUDispatcher:
    """Get or create the global GPU dispatcher."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = GPUDispatcher()
    return _dispatcher
```

**Step 4: AST Pattern Matcher for Offload-Eligible Constructs**

Create `coex/gpu/offload_detector.py`:

```python
"""Detect offload-eligible constructs in Coex AST."""

from typing import Optional, Tuple
from dataclasses import dataclass

@dataclass
class OffloadCandidate:
    """Represents an offload-eligible AST node."""
    node_type: str  # 'comprehension', 'iterator_first', 'iterator_most', 'for_loop'
    collection_expr: any  # AST node for the collection
    formula_expr: any  # AST node for the formula/predicate
    transform_expr: Optional[any] = None  # For filter-map patterns

class OffloadDetector:
    """Detects offload-eligible patterns in Coex AST."""
    
    def __init__(self, symbol_table):
        """Initialize with symbol table for formula kind lookup."""
        self.symbol_table = symbol_table
    
    def is_formula_kind(self, func_name: str) -> bool:
        """Check if a function is of formula kind."""
        sym = self.symbol_table.lookup(func_name)
        return sym is not None and sym.kind == 'formula'
    
    def check_comprehension(self, node) -> Optional[OffloadCandidate]:
        """Check if a comprehension is offload-eligible.
        
        Eligible if the body expression calls only formulas.
        """
        # Extract the transformation expression
        transform = node.body_expr
        
        # Check if transform is a formula call (or composition of formula calls)
        if not self._is_formula_expression(transform):
            return None
        
        # Check predicate if present
        if node.predicate is not None:
            if not self._is_formula_expression(node.predicate):
                return None
        
        return OffloadCandidate(
            node_type='comprehension',
            collection_expr=node.collection,
            formula_expr=transform,
            transform_expr=node.predicate
        )
    
    def check_iterator_call(self, node) -> Optional[OffloadCandidate]:
        """Check if an iterator call (first/most) is offload-eligible.
        
        Eligible if the predicate is a formula.
        """
        if node.function_name not in ('first', 'most'):
            return None
        
        # Second argument should be a formula predicate
        if len(node.arguments) < 2:
            return None
        
        predicate = node.arguments[1]
        if not self._is_formula_expression(predicate):
            return None
        
        return OffloadCandidate(
            node_type=f'iterator_{node.function_name}',
            collection_expr=node.arguments[0],
            formula_expr=predicate
        )
    
    def check_for_loop(self, node) -> Optional[OffloadCandidate]:
        """Check if a for loop is offload-eligible.
        
        Eligible if body consists only of formula calls with no 
        inter-iteration dependencies.
        """
        # This is more complex - need to verify:
        # 1. Body is formula calls only
        # 2. No writes to external state
        # 3. No dependencies between iterations
        
        # For initial implementation, only handle simple cases
        if not self._is_simple_formula_loop(node):
            return None
        
        return OffloadCandidate(
            node_type='for_loop',
            collection_expr=node.collection,
            formula_expr=node.body
        )
    
    def _is_formula_expression(self, expr) -> bool:
        """Check if an expression consists only of formula calls.
        
        Recursively checks that all function calls in the expression
        are to functions of formula kind.
        """
        # Implementation depends on AST structure
        # This is a simplified version
        if hasattr(expr, 'function_name'):
            if not self.is_formula_kind(expr.function_name):
                return False
            # Check nested calls
            for arg in getattr(expr, 'arguments', []):
                if not self._is_formula_expression(arg):
                    return False
        return True
    
    def _is_simple_formula_loop(self, node) -> bool:
        """Check if a for loop is a simple parallelizable pattern."""
        # Conservative initial implementation
        # Only parallelize if body is a single formula call
        # with the loop variable as sole argument
        return False  # Start conservative, expand later
```

### 3.2 Phase 2: CUDA Backend (Linux Test Machine)

#### 3.2.1 Prerequisites

```bash
# Install CuPy for your CUDA version
pip install cupy-cuda12x  # Adjust for your CUDA version
```

#### 3.2.2 Testing Strategy

Since GitHub Actions runners lack GPU access:

1. **CI Tests GPU-Agnostic Code**: Test backend detection, kernel emission, AST pattern matching
2. **Self-Hosted Runner**: Configure your Linux machine with 4090s as a self-hosted runner for GPU integration tests
3. **Differential Testing**: Every GPU execution path must produce results identical to CPU fallback

```python
# Example differential test
def test_map_formula_equivalence():
    """GPU and CPU paths must produce identical results."""
    source = """
    formula double(x: float) -> float {
        return x * 2.0
    }
    
    func main() {
        numbers = [1.0, 2.0, 3.0, 4.0, 5.0]
        results = [double(x) for x in numbers]
        return results
    }
    """
    
    # Force CPU execution
    with gpu_backend_override(GPUBackend.NONE):
        cpu_result = compile_and_run(source)
    
    # Force GPU execution (skip if unavailable)
    backend = detect_gpu_backend()
    if backend != GPUBackend.NONE:
        with gpu_backend_override(backend):
            gpu_result = compile_and_run(source)
        
        assert_arrays_equal(cpu_result, gpu_result)
```

### 3.3 Phase 3: Integration with Existing Compiler

#### 3.3.1 Codegen Hook Point

In the main codegen visitor, add an offload check before standard LLVM-IR emission:

```python
class CodegenVisitor:
    def __init__(self):
        self.offload_detector = OffloadDetector(self.symbol_table)
        self.kernel_emitter = KernelEmitter(detect_gpu_backend())
        self.gpu_dispatcher = get_dispatcher()
    
    def visit_comprehension(self, node):
        # Check for GPU offload eligibility
        candidate = self.offload_detector.check_comprehension(node)
        
        if candidate and detect_gpu_backend() != GPUBackend.NONE:
            return self._emit_gpu_comprehension(candidate)
        else:
            return self._emit_cpu_comprehension(node)
    
    def _emit_gpu_comprehension(self, candidate: OffloadCandidate):
        """Emit GPU-accelerated comprehension."""
        # Generate unique kernel name
        kernel_name = self._generate_kernel_name()
        
        # Transpile formula body to C-like syntax
        formula_body = self._transpile_formula(candidate.formula_expr)
        
        # Determine parameter types from AST
        input_params = self._extract_formula_params(candidate.formula_expr)
        output_type = self._infer_output_type(candidate.formula_expr)
        
        # Emit kernel source
        kernel_source = self.kernel_emitter.emit_map_kernel(
            kernel_name, formula_body, input_params, output_type
        )
        
        # Emit runtime dispatch call
        return self._emit_dispatch_call(kernel_source, kernel_name, 
                                         candidate.collection_expr)
```

#### 3.3.2 Formula Transpilation

The formula body needs transpilation from Coex AST to C-like syntax:

```python
class FormulaTranspiler:
    """Transpile Coex formula AST to C-like syntax for GPU kernels."""
    
    def transpile(self, expr) -> str:
        """Transpile a formula expression to C syntax."""
        if isinstance(expr, BinaryOpNode):
            left = self.transpile(expr.left)
            right = self.transpile(expr.right)
            return f"({left} {expr.operator} {right})"
        
        elif isinstance(expr, UnaryOpNode):
            operand = self.transpile(expr.operand)
            return f"({expr.operator}{operand})"
        
        elif isinstance(expr, FunctionCallNode):
            # Map Coex math functions to GPU equivalents
            func = self._map_function(expr.function_name)
            args = ", ".join(self.transpile(a) for a in expr.arguments)
            return f"{func}({args})"
        
        elif isinstance(expr, VariableNode):
            # Prepend underscore for loaded input variables
            return f"_{expr.name}"
        
        elif isinstance(expr, LiteralNode):
            return self._format_literal(expr)
        
        else:
            raise ValueError(f"Cannot transpile: {type(expr)}")
    
    def _map_function(self, coex_name: str) -> str:
        """Map Coex function names to GPU equivalents."""
        # Most math functions have same names in Metal/CUDA
        mapping = {
            'abs': 'abs',
            'sqrt': 'sqrt',
            'sin': 'sin',
            'cos': 'cos',
            'tan': 'tan',
            'exp': 'exp',
            'log': 'log',
            'pow': 'pow',
            'floor': 'floor',
            'ceil': 'ceil',
            'min': 'min',
            'max': 'max',
        }
        return mapping.get(coex_name, coex_name)
```

---

## Part 4: Testing Strategy

### 4.1 Test Categories

#### 4.1.1 Unit Tests (No GPU Required)

```python
class TestKernelEmission:
    """Test kernel source generation."""
    
    def test_metal_map_kernel_structure(self):
        emitter = KernelEmitter(GPUBackend.METAL)
        source = emitter.emit_map_kernel(
            "test_kernel",
            "_x * 2.0",
            [("x", "float")],
            "float"
        )
        assert "#include <metal_stdlib>" in source
        assert "kernel void test_kernel" in source
        assert "[[thread_position_in_grid]]" in source
    
    def test_cuda_map_kernel_structure(self):
        emitter = KernelEmitter(GPUBackend.CUDA)
        source = emitter.emit_map_kernel(
            "test_kernel",
            "_x * 2.0",
            [("x", "float")],
            "float"
        )
        assert 'extern "C" __global__' in source
        assert "blockIdx.x * blockDim.x + threadIdx.x" in source

class TestOffloadDetection:
    """Test pattern matching for offload eligibility."""
    
    def test_simple_comprehension_eligible(self):
        # Parse: [double(x) for x in numbers]
        # where double is a formula
        ast = parse("[double(x) for x in numbers]")
        detector = OffloadDetector(mock_symbol_table_with_formula('double'))
        candidate = detector.check_comprehension(ast)
        assert candidate is not None
        assert candidate.node_type == 'comprehension'
    
    def test_task_comprehension_not_eligible(self):
        # Parse: [process(x) for x in numbers]  
        # where process is a task (not formula)
        ast = parse("[process(x) for x in numbers]")
        detector = OffloadDetector(mock_symbol_table_with_task('process'))
        candidate = detector.check_comprehension(ast)
        assert candidate is None
```

#### 4.1.2 Integration Tests (GPU Required)

```python
@pytest.mark.gpu
class TestGPUExecution:
    """Integration tests requiring GPU hardware."""
    
    @pytest.fixture(autouse=True)
    def skip_if_no_gpu(self):
        if detect_gpu_backend() == GPUBackend.NONE:
            pytest.skip("No GPU backend available")
    
    def test_simple_map_execution(self):
        source = """
        formula double(x: float) -> float {
            return x * 2.0
        }
        
        func main() -> [float] {
            numbers = [1.0, 2.0, 3.0, 4.0]
            return [double(x) for x in numbers]
        }
        """
        result = compile_and_run(source)
        assert result == [2.0, 4.0, 6.0, 8.0]
    
    def test_gpu_cpu_equivalence_random_data(self):
        """Fuzz test: random inputs should produce identical results."""
        import random
        
        source = """
        formula compute(x: float) -> float {
            return sqrt(abs(x)) + sin(x) * cos(x)
        }
        
        func main(data: [float]) -> [float] {
            return [compute(x) for x in data]
        }
        """
        
        for _ in range(100):
            data = [random.uniform(-100, 100) for _ in range(1000)]
            
            with gpu_backend_override(GPUBackend.NONE):
                cpu_result = compile_and_run(source, data)
            
            with gpu_backend_override(detect_gpu_backend()):
                gpu_result = compile_and_run(source, data)
            
            assert_arrays_almost_equal(cpu_result, gpu_result, rtol=1e-5)
```

### 4.2 CI Configuration

```yaml
# .github/workflows/test.yml
name: Coex Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -e .[test]
      - run: pytest tests/ -m "not gpu"
  
  gpu-tests:
    runs-on: self-hosted  # Your Linux machine with 4090
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .[test]
      - run: pytest tests/ -m "gpu"
```

---

## Part 5: Future Considerations

### 5.1 Deferred Optimizations

The following optimizations are explicitly deferred until profiling demonstrates need:

1. **Kernel Fusion**: Nested offload-eligible constructs could be fused into single kernels to reduce dispatch overhead.

2. **Size Thresholds**: Small collections might execute faster on CPU due to GPU dispatch overhead.

3. **Memory Transfer Optimization**: For discrete GPUs (CUDA), minimizing host-device transfers could significantly improve performance.

4. **Threadgroup Tuning**: Metal and CUDA have optimal threadgroup/block sizes that vary by hardware.

### 5.2 Additional GPU Platforms

When needed:

1. **AMD ROCm/HIP**: Syntax nearly identical to CUDA; would require new detection path and minor kernel adjustments.

2. **WebGPU/WGSL**: Required for GPU acceleration in the WebAssembly target (see 5.4). WGSL has a more verbose syntax than Metal or CUDA, designed with safety constraints for the browser environment. Would require its own emitter backend following the same architectural pattern.

3. **Vulkan Compute**: Cross-platform alternative to Metal/CUDA; SPIR-V compilation adds complexity.

### 5.4 WebAssembly Target

Coex has a planned WebAssembly compilation target. The language specifies its own canvas-based GUI library that can render in browsers, reducing the platform interface contract to a drawable rectangle. This enables Coex applications to run client-side in web browsers.

**GPU Acceleration Strategy for WebAssembly:**

WebGPU is the only path to GPU compute from within a browser context and will eventually serve as the GPU backend for the WebAssembly target. However, WebGPU is still stabilizing—browser support varies (Chrome and Edge have full support, Firefox partial, Safari behind flags as of early 2025).

**Until WebGPU reaches stable universal browser support, the WebAssembly target will use CPU fallback for all formula offload.** This means:

- Offload-eligible constructs (iterators, comprehensions, matrix operations) will execute via the task-alias fallback path
- All formula constraints remain enforced by the compiler regardless of execution backend
- Performance will be limited to what WebAssembly's CPU execution provides
- No user-facing behavior changes—only performance characteristics differ

Once WebGPU stabilizes:

1. Backend detection will check for WebGPU availability via the browser's `navigator.gpu` API
2. A WGSL kernel emitter will be added following the existing Metal/CUDA pattern
3. Dispatch will use the WebGPU compute pipeline API
4. Fallback to CPU remains available for browsers without WebGPU support

This conservative approach ensures Coex's WebAssembly target is functional immediately while preserving the option for GPU acceleration when the platform matures.

### 5.3 `first` Iterator Implementation

The `first(collection, predicate)` pattern is more complex than map operations because it requires finding the minimum index where the predicate holds. Options:

1. **Conservative**: Always fall back to CPU for `first`
2. **Parallel Reduction**: Each thread evaluates predicate, parallel reduction finds minimum true index
3. **Early Exit**: Chunked evaluation with early termination when match found

Recommend starting with option 1 and implementing parallel reduction only if `first` becomes a performance bottleneck.

---

## Appendix A: Complete Example

### A.1 Coex Source

```coex
// Vector operations using formula kind

formula magnitude(x: float, y: float, z: float) -> float {
    return sqrt(x*x + y*y + z*z)
}

formula normalize_component(component: float, mag: float) -> float {
    return component / mag
}

formula dot_product(x1: float, y1: float, z1: float,
                    x2: float, y2: float, z2: float) -> float {
    return x1*x2 + y1*y2 + z1*z2
}

func process_vectors(xs: [float], ys: [float], zs: [float]) -> [float] {
    // This comprehension is offload-eligible: formula over collections
    magnitudes = [magnitude(xs[i], ys[i], zs[i]) for i in range(len(xs))]
    return magnitudes
}
```

### A.2 Generated Metal Kernel

```metal
#include <metal_stdlib>
using namespace metal;

kernel void coex_magnitude_map(
    device const float* xs [[buffer(0)]],
    device const float* ys [[buffer(1)]],
    device const float* zs [[buffer(2)]],
    device float* _output [[buffer(3)]],
    uint _id [[thread_position_in_grid]]
) {
    // Load inputs for this thread
    float _x = xs[_id];
    float _y = ys[_id];
    float _z = zs[_id];
    
    // Formula body: magnitude(x, y, z)
    float _result = sqrt(_x*_x + _y*_y + _z*_z);
    
    // Store output
    _output[_id] = _result;
}
```

### A.3 Generated CUDA Kernel

```cuda
extern "C" __global__
void coex_magnitude_map(
    const float* xs,
    const float* ys,
    const float* zs,
    float* _output,
    int _n
) {
    int _id = blockIdx.x * blockDim.x + threadIdx.x;
    if (_id < _n) {
        // Load inputs for this thread
        float _x = xs[_id];
        float _y = ys[_id];
        float _z = zs[_id];
        
        // Formula body: magnitude(x, y, z)
        float _result = sqrt(_x*_x + _y*_y + _z*_z);
        
        // Store output
        _output[_id] = _result;
    }
}
```

---

## Appendix B: Dependencies

### B.1 Required Python Packages

```
# requirements-gpu.txt

# Metal backend (macOS only)
metalcompute>=0.2.0; sys_platform == 'darwin'

# CUDA backend (requires NVIDIA GPU + CUDA toolkit)
cupy-cuda12x>=12.0.0; sys_platform == 'linux'
# OR for different CUDA versions:
# cupy-cuda11x>=11.0.0; sys_platform == 'linux'
```

### B.2 System Requirements

**Metal Backend (macOS)**:
- macOS 12.0 or later
- Apple Silicon (M1/M2/M3) or Intel Mac with discrete AMD GPU
- Xcode Command Line Tools (for Metal compiler)

**CUDA Backend (Linux/Windows)**:
- NVIDIA GPU with compute capability 5.0+
- CUDA Toolkit 11.x or 12.x
- NVIDIA drivers 450.x or later

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-01-17 | Initial specification |
| 1.1 | 2025-01-17 | Added WebAssembly target details and WebGPU strategy (Section 5.4) |
