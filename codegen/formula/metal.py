"""
Metal Backend for Coex Formula GPU Offload.

Generates Metal Shading Language (MSL) kernels and dispatches via metalcompute.
"""

from typing import List, Tuple, Any, Optional
from llvmlite import ir

from codegen.formula.base import FormulaBackend, KernelSpec, TranspileError


class MetalBackend(FormulaBackend):
    """Metal GPU backend for macOS/Apple Silicon.

    Uses the metalcompute Python library for kernel compilation and dispatch.
    Generates Metal Shading Language (MSL) kernel source code.
    """

    # Coex type to Metal type mapping
    TYPE_MAP = {
        'int': 'int',
        'int64': 'long',
        'float': 'float',
        'float64': 'double',  # Note: check device capability
        'bool': 'bool',
        'byte': 'uint8_t',
    }

    # Coex math functions to Metal stdlib equivalents
    FUNCTION_MAP = {
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
        'fabs': 'fabs',
        'round': 'round',
    }

    def __init__(self):
        """Initialize Metal backend."""
        self._device = None
        self._kernel_cache = {}

    def get_name(self) -> str:
        return "Metal (Apple GPU)"

    def map_type(self, coex_type: str) -> str:
        """Map Coex type to Metal type."""
        if coex_type in self.TYPE_MAP:
            return self.TYPE_MAP[coex_type]
        # Handle array types like [int] -> device int*
        if coex_type.startswith('[') and coex_type.endswith(']'):
            inner = coex_type[1:-1]
            return f"device {self.map_type(inner)}*"
        return coex_type

    def emit_map_kernel(
        self,
        kernel_name: str,
        formula_body: str,
        input_params: List[Tuple[str, str]],
        output_type: str
    ) -> str:
        """Emit a Metal map kernel for parallel element-wise operations.

        Generates MSL code that processes each element in parallel.
        """
        metal_output_type = self.map_type(output_type)

        # Build buffer parameters
        buffer_params = []
        buffer_idx = 0

        for param_name, param_type in input_params:
            metal_type = self.map_type(param_type)
            buffer_params.append(
                f"    device const {metal_type}* {param_name} [[buffer({buffer_idx})]]"
            )
            buffer_idx += 1

        # Output buffer
        buffer_params.append(
            f"    device {metal_output_type}* _output [[buffer({buffer_idx})]]"
        )

        # Thread index
        buffer_params.append(
            "    uint _id [[thread_position_in_grid]]"
        )

        params_str = ",\n".join(buffer_params)

        # Generate input loading statements
        input_loads = self._emit_input_loads(input_params)

        return f'''#include <metal_stdlib>
using namespace metal;

kernel void {kernel_name}(
{params_str}
) {{
    // Load inputs for this thread
{input_loads}

    // Formula body
    {metal_output_type} _result = {formula_body};

    // Store output
    _output[_id] = _result;
}}
'''

    def emit_predicate_kernel(
        self,
        kernel_name: str,
        predicate_body: str,
        input_params: List[Tuple[str, str]]
    ) -> str:
        """Emit a Metal predicate kernel for filter operations.

        Each thread evaluates the predicate for one element.
        Results are stored as 0/1 in output buffer for subsequent reduction.
        """
        # Build buffer parameters
        buffer_params = []
        buffer_idx = 0

        for param_name, param_type in input_params:
            metal_type = self.map_type(param_type)
            buffer_params.append(
                f"    device const {metal_type}* {param_name} [[buffer({buffer_idx})]]"
            )
            buffer_idx += 1

        # Output buffer (bool results as int for reduction)
        buffer_params.append(
            f"    device int* _matches [[buffer({buffer_idx})]]"
        )

        # Thread index
        buffer_params.append(
            "    uint _id [[thread_position_in_grid]]"
        )

        params_str = ",\n".join(buffer_params)
        input_loads = self._emit_input_loads(input_params)

        return f'''#include <metal_stdlib>
using namespace metal;

kernel void {kernel_name}(
{params_str}
) {{
    // Load inputs for this thread
{input_loads}

    // Evaluate predicate
    bool _pred = {predicate_body};

    // Store result (1 if match, 0 if not)
    _matches[_id] = _pred ? 1 : 0;
}}
'''

    def _emit_input_loads(self, input_params: List[Tuple[str, str]]) -> str:
        """Emit Metal input loading statements."""
        loads = []
        for param_name, param_type in input_params:
            metal_type = self.map_type(param_type)
            loads.append(f"    {metal_type} _{param_name} = {param_name}[_id];")
        return "\n".join(loads)

    def emit_dispatch_code(
        self,
        kernel_spec: KernelSpec,
        codegen: Any
    ) -> Any:
        """Emit LLVM IR to dispatch the Metal kernel at runtime.

        This is a placeholder - actual implementation will need to:
        1. Call into a runtime helper that uses metalcompute
        2. Handle buffer management
        3. Return results as Coex list

        For now, we generate a call to a runtime dispatch function.
        """
        # This will be implemented when we integrate with the runtime.
        # The actual Metal dispatch happens through metalcompute in Python,
        # so we need a foreign function interface or embed Python.
        #
        # For initial implementation, we'll generate calls to extern "C"
        # dispatch functions that wrap metalcompute.
        raise NotImplementedError(
            "Metal dispatch code generation not yet implemented. "
            "This requires runtime integration with metalcompute."
        )

    def get_device(self):
        """Get or create Metal device instance."""
        if self._device is None:
            try:
                import metalcompute as mc
                self._device = mc.Device()
            except ImportError:
                raise RuntimeError("metalcompute not installed")
        return self._device

    def compile_kernel(self, kernel_source: str, kernel_name: str):
        """Compile and cache a Metal kernel."""
        cache_key = (kernel_source, kernel_name)
        if cache_key not in self._kernel_cache:
            device = self.get_device()
            compiled = device.kernel(kernel_source)
            self._kernel_cache[cache_key] = compiled.function(kernel_name)
        return self._kernel_cache[cache_key]

    def dispatch(
        self,
        kernel_source: str,
        kernel_name: str,
        input_buffers: list,
        count: int,
        output_dtype: str = 'f'
    ):
        """Execute a Metal kernel.

        This is called from the Coex runtime, not from generated code.

        Args:
            kernel_source: MSL kernel source code
            kernel_name: Name of the kernel function
            input_buffers: List of input data buffers
            count: Number of elements to process
            output_dtype: Output data type code ('f' for float, 'i' for int)

        Returns:
            Memoryview of output buffer.
        """
        import metalcompute as mc

        device = self.get_device()
        kernel = self.compile_kernel(kernel_source, kernel_name)

        # Determine output buffer size based on dtype
        dtype_sizes = {'f': 4, 'i': 4, 'd': 8, 'l': 8}
        elem_size = dtype_sizes.get(output_dtype, 4)
        output_buffer = device.buffer(count * elem_size)

        # Dispatch kernel
        kernel(count, *input_buffers, output_buffer)

        # Return as memoryview
        return memoryview(output_buffer).cast(output_dtype)
