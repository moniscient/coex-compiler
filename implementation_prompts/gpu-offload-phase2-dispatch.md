# GPU Offload Phase 2: Runtime Dispatch Implementation

## Current State

Phase 1 (complete) established the formula GPU offload infrastructure:
- Module structure: `codegen/formula/` with `__init__.py`, `base.py`, `metal.py`, `cuda.py`
- Backend detection: Lazy, cached detection (Metal → CUDA → CPU)
- Kernel emitters: Metal and CUDA backends generate correct kernel source
- Gateway integration: `try_offload()` hooks into comprehensions, first/most, for-assign
- Fallback: Currently all GPU paths raise `NotImplementedError` and fall back to task execution

## Phase 2 Objective

Implement the actual GPU dispatch pipeline so that formula-based bulk operations execute on GPU when available.

## Prerequisites

1. Install metalcompute: `pip install metalcompute`
2. Verify Metal detection works:
   ```python
   from codegen.formula import detect_backend, GPUBackend
   assert detect_backend() == GPUBackend.METAL
   ```

## Implementation Steps

### Step 1: Data Marshaling Infrastructure

Create `codegen/formula/marshaling.py` to handle Coex ↔ GPU buffer conversion.

**Required functions:**
```python
def coex_list_to_buffer(codegen, list_handle, elem_type) -> (buffer_ptr, count):
    """Convert Coex list handle to contiguous GPU-compatible buffer.

    - Allocate stack buffer or malloc for data
    - Copy list elements to contiguous memory
    - Return pointer and element count
    """

def buffer_to_coex_list(codegen, buffer_ptr, count, elem_type) -> list_handle:
    """Convert GPU output buffer back to Coex list.

    - Allocate new Coex list
    - Copy elements from buffer to list
    - Return list handle
    """

def get_element_size(elem_type) -> int:
    """Get byte size for element type (int=8, float=8, bool=1, etc.)"""
```

**LLVM IR generation pattern:**
```python
# Extract list data to contiguous buffer
list_ptr = codegen._generate_expression(collection_expr)
list_len = builder.call(codegen.list_len, [list_ptr])

# Allocate buffer: elem_size * count bytes
elem_size = ir.Constant(i64, 8)  # for int
buffer_size = builder.mul(list_len, elem_size)
buffer = builder.call(codegen.malloc, [buffer_size])

# Copy loop: for i in 0..len, buffer[i] = list.get(i)
# [generate copy loop]
```

### Step 2: Metal Runtime Bridge

Create `codegen/formula/metal_runtime.py` - Python-side dispatch that LLVM calls via extern.

**Approach A: Python callback via ctypes**
```python
# Register Python function callable from LLVM
@ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p,
                  ctypes.c_void_p, ctypes.c_int64, ctypes.c_void_p)
def metal_dispatch(kernel_source, kernel_name, input_buffer, count, output_buffer):
    """Called from LLVM IR to execute Metal kernel."""
    import metalcompute as mc
    device = mc.Device()
    kernel = device.kernel(kernel_source.decode())
    func = kernel.function(kernel_name.decode())

    # Create Metal buffers from pointers
    input_buf = device.buffer(input_buffer, count * 8)
    output_buf = device.buffer(count * 8)

    # Dispatch
    func(count, input_buf, output_buf)

    # Copy result back
    ctypes.memmove(output_buffer, output_buf, count * 8)
```

**Approach B: Embed kernel source in binary, call at runtime**
- Store kernel source as global string constant
- Generate extern call to `coex_metal_dispatch(source, name, in, count, out)`
- Implement `coex_metal_dispatch` in `runtime/coex_metal.m` (Objective-C)

**Recommendation**: Start with Approach A for faster iteration, migrate to B for production.

### Step 3: Implement `_generate_gpu_offload()`

In `codegen/formula/__init__.py`, replace the `NotImplementedError` with actual dispatch:

```python
def _generate_gpu_offload(
    candidate: OffloadCandidate,
    backend: FormulaBackend,
    codegen: 'CodeGenerator'
) -> OffloadResult:
    """Generate GPU kernel dispatch for offload candidate."""

    # 1. Transpile formula body to GPU source
    transpiler = FormulaTranspiler(backend)
    formula_body = transpiler.transpile(candidate.formula_expr, candidate.loop_var)

    # 2. Generate unique kernel name
    kernel_name = f"coex_kernel_{codegen._kernel_counter}"
    codegen._kernel_counter += 1

    # 3. Emit kernel source
    if candidate.construct_type == 'comprehension':
        kernel_source = backend.emit_map_kernel(
            kernel_name,
            formula_body,
            [(candidate.loop_var, _infer_elem_type(candidate.collection_expr, codegen))],
            _infer_return_type(candidate.formula_expr, codegen)
        )
    elif candidate.construct_type in ('first', 'most'):
        kernel_source = backend.emit_predicate_kernel(
            kernel_name,
            formula_body,
            [(candidate.loop_var, _infer_elem_type(candidate.collection_expr, codegen))]
        )

    # 4. Generate marshaling code
    input_buffer, count = marshal_input(codegen, candidate.collection_expr)
    output_buffer = allocate_output(codegen, count, output_type)

    # 5. Generate dispatch call
    dispatch_gpu_kernel(codegen, kernel_source, kernel_name, input_buffer, count, output_buffer)

    # 6. Generate result collection
    if candidate.construct_type == 'comprehension':
        result = buffer_to_coex_list(codegen, output_buffer, count, output_type)
    elif candidate.construct_type == 'first':
        result = find_first_match(codegen, output_buffer, count, candidate.collection_expr)
    elif candidate.construct_type == 'most':
        result = collect_all_matches(codegen, output_buffer, count, candidate.collection_expr)

    return OffloadResult(handled=True, value=result)
```

### Step 4: Type Inference Helpers

Add to `codegen/formula/__init__.py`:

```python
def _infer_elem_type(collection_expr, codegen) -> str:
    """Infer element type of a collection expression."""
    coex_type = codegen._get_coex_type(collection_expr)
    if isinstance(coex_type, ListType):
        return _type_to_string(coex_type.element_type)
    # Handle other collection types
    return 'int'  # default

def _infer_return_type(formula_expr, codegen) -> str:
    """Infer return type of a formula expression."""
    # Look up formula declaration
    if isinstance(formula_expr, CallExpr):
        func_name = _get_call_name(formula_expr)
        if func_name in codegen.func_decls:
            return_type = codegen.func_decls[func_name].return_type
            return _type_to_string(return_type)
    return 'int'  # default

def _type_to_string(coex_type) -> str:
    """Convert Coex type to string for kernel generation."""
    if isinstance(coex_type, PrimitiveType):
        return coex_type.name
    return 'int'
```

### Step 5: Filter Predicate Post-Processing

For `first` and `most`, the GPU outputs a boolean mask. Post-process on CPU:

```python
def find_first_match(codegen, mask_buffer, count, collection_expr):
    """Find first element where mask[i] == 1."""
    # Generate loop to find first non-zero in mask
    # Return corresponding element from original collection

def collect_all_matches(codegen, mask_buffer, count, collection_expr):
    """Collect all elements where mask[i] == 1."""
    # Generate loop to count matches, allocate result list
    # Copy matching elements to result
```

## Testing Strategy

### Unit Tests (no GPU required)
```python
def test_kernel_source_generation():
    """Verify kernel source is syntactically correct."""
    backend = MetalBackend()
    source = backend.emit_map_kernel("test", "_x * 2", [("x", "int")], "int")
    assert "kernel void test" in source

def test_transpiler_binary_ops():
    """Verify AST-to-C transpilation."""
    # Create mock AST, verify output
```

### Integration Tests (GPU required)
```python
@pytest.mark.skipif(detect_backend() != GPUBackend.METAL, reason="No Metal GPU")
def test_comprehension_gpu_offload(expect_output):
    expect_output('''
formula double(x: int) -> int
    return x * 2
~

func main() -> int
    data = [1, 2, 3, 4, 5]
    result = [double(x) for x in data]
    # Should execute on GPU, produce same result as CPU
    print(result.get(0))
    return 0
~
''', "2\n")
```

### Differential Testing
```python
def test_gpu_matches_cpu():
    """GPU result must exactly match CPU fallback."""
    # Run with GPU enabled
    gpu_result = run_with_gpu(program)
    # Run with CPU fallback
    cpu_result = run_with_cpu_fallback(program)
    assert gpu_result == cpu_result
```

## Performance Validation

### Crossover Point Analysis
Determine minimum collection size where GPU overhead is justified:

```python
def benchmark_crossover():
    sizes = [100, 1000, 10000, 100000, 1000000]
    for n in sizes:
        cpu_time = benchmark_cpu(n)
        gpu_time = benchmark_gpu(n)
        print(f"n={n}: CPU={cpu_time:.3f}ms GPU={gpu_time:.3f}ms")
```

Expected: GPU wins at n > ~10,000 for simple formulas.

### Automatic Threshold
Add heuristic to `try_offload()`:
```python
MIN_GPU_ELEMENTS = 10000  # Configurable

def try_offload(node, codegen):
    # ... eligibility check ...

    # Check if collection is large enough
    if _is_small_collection(candidate.collection_expr, codegen):
        return None  # Fall back to CPU
```

## Error Handling

1. **Kernel compilation failure**: Emit warning, fall back to CPU
2. **GPU out of memory**: Emit warning, fall back to CPU
3. **Buffer size overflow**: Emit error (collection too large for GPU)
4. **Type mismatch**: Emit error at compile time

## Files to Create/Modify

| File | Action |
|------|--------|
| `codegen/formula/__init__.py` | Implement `_generate_gpu_offload()` |
| `codegen/formula/marshaling.py` | Create - data conversion utilities |
| `codegen/formula/metal_runtime.py` | Create - Python-side Metal dispatch |
| `runtime/coex_metal.m` | Create (optional) - native Metal dispatch |
| `tests/test_gpu_offload_integration.py` | Create - GPU integration tests |

## Success Criteria

1. Formula comprehensions execute on Metal GPU when available
2. Results exactly match CPU fallback (differential testing)
3. Performance improvement visible for n > 10,000 elements
4. Graceful fallback on GPU errors
5. All existing tests continue to pass
