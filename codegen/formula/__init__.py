"""
Formula GPU Offload Package for Coex.

This package provides GPU offload capabilities for Coex's formula kind functions.
The single entry point `try_offload()` is called by the code generator for
potentially GPU-offloadable constructs.

Usage from codegen:
    from codegen.formula import try_offload, OffloadResult

    # In comprehension/first/most/for generation:
    result = try_offload(node, self)
    if result is not None and result.handled:
        return result.value
    # Otherwise continue with normal codegen
"""

from enum import Enum, auto
from typing import Optional, Any, List, Tuple, TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


# =============================================================================
# GPU Backend Detection
# =============================================================================

class GPUBackend(Enum):
    """Available GPU compute backends."""
    METAL = auto()   # Apple Metal (macOS)
    CUDA = auto()    # NVIDIA CUDA
    NONE = auto()    # CPU fallback


# Cached backend - None means not yet detected
_cached_backend: Optional[GPUBackend] = None
_detection_attempted: bool = False


def detect_backend() -> GPUBackend:
    """Detect available GPU backend.

    Detection is lazy and cached - runs only once on first call.
    Checks backends in priority order:
    1. Metal (macOS with Apple GPU)
    2. CUDA (NVIDIA GPU with toolkit)
    3. NONE (CPU fallback)

    Returns:
        The detected GPUBackend.
    """
    global _cached_backend, _detection_attempted

    if _detection_attempted:
        return _cached_backend

    _detection_attempted = True

    # Try Metal first (macOS)
    if _try_metal():
        _cached_backend = GPUBackend.METAL
        return _cached_backend

    # Try CUDA
    if _try_cuda():
        _cached_backend = GPUBackend.CUDA
        return _cached_backend

    # Fallback to CPU
    _cached_backend = GPUBackend.NONE
    return _cached_backend


def _try_metal() -> bool:
    """Check if Metal is available."""
    try:
        import platform
        if platform.system() != 'Darwin':
            return False

        import metalcompute as mc
        # Verify we can actually create a device
        dev = mc.Device()
        return True
    except (ImportError, Exception):
        return False


def _try_cuda() -> bool:
    """Check if CUDA is available."""
    try:
        import cupy as cp
        # Verify CUDA runtime is available
        count = cp.cuda.runtime.getDeviceCount()
        return count > 0
    except (ImportError, Exception):
        return False


def get_backend_name() -> str:
    """Get human-readable name for the current backend."""
    backend = detect_backend()
    names = {
        GPUBackend.METAL: "Metal (Apple GPU)",
        GPUBackend.CUDA: "CUDA (NVIDIA GPU)",
        GPUBackend.NONE: "CPU (no GPU backend)",
    }
    return names[backend]


def reset_detection():
    """Reset backend detection cache. Primarily for testing."""
    global _cached_backend, _detection_attempted
    _cached_backend = None
    _detection_attempted = False


# =============================================================================
# Offload Gateway Types
# =============================================================================

@dataclass
class OffloadResult:
    """Result from try_offload().

    Attributes:
        handled: True if the construct was handled (GPU or fallback)
        value: The LLVM IR value if handled, None otherwise
    """
    handled: bool
    value: Any = None


@dataclass
class OffloadCandidate:
    """Information about an offload-eligible construct."""
    construct_type: str  # 'comprehension', 'first', 'most', 'for'
    original_node: Any   # The original AST node
    formula_expr: Any    # The formula expression (body or predicate)
    collection_expr: Any # The collection being iterated
    loop_var: str        # Loop variable name
    filter_expr: Optional[Any] = None  # Optional filter predicate


# Lazy-loaded backend instance
_backend_instance = None
_formulas_used: bool = False
_gpu_offload_used: bool = False  # True if GPU offload code was actually generated


# =============================================================================
# Main Gateway Function
# =============================================================================

def try_offload(node: Any, codegen: 'CodeGenerator') -> Optional[OffloadResult]:
    """Attempt to offload a construct to GPU.

    This is the single gateway for all GPU offload decisions. Call this
    for any potentially offloadable construct before generating standard code.

    Args:
        node: AST node (ListComprehension, FirstAssignStmt, MostAssignStmt, ForAssignStmt)
        codegen: The CodeGenerator instance

    Returns:
        OffloadResult if the construct was handled (GPU or fallback),
        None if the construct is not offload-eligible and should use normal codegen.
    """
    global _formulas_used

    # Import here to avoid circular imports
    from ast_nodes import (
        ListComprehension, SetComprehension, MapComprehension,
        FirstAssignStmt, MostAssignStmt, ForAssignStmt
    )

    # Determine construct type and check eligibility
    if isinstance(node, (ListComprehension, SetComprehension, MapComprehension)):
        candidate = _check_comprehension(node, codegen)
    elif isinstance(node, FirstAssignStmt):
        candidate = _check_first_assign(node, codegen)
    elif isinstance(node, MostAssignStmt):
        candidate = _check_most_assign(node, codegen)
    elif isinstance(node, ForAssignStmt):
        candidate = _check_for_assign(node, codegen)
    else:
        return None  # Not an offloadable construct type

    if candidate is None:
        return None  # Not eligible (doesn't use formulas or has unsupported patterns)

    # Mark that formulas are used (for backend inclusion)
    _formulas_used = True

    # Get backend (lazy detection)
    backend = _get_backend()

    if backend is None:
        # No GPU available - use task fallback
        return _generate_task_fallback(node, codegen)

    # Generate GPU kernel and dispatch
    global _gpu_offload_used
    try:
        result = _generate_gpu_offload(candidate, backend, codegen)
        _gpu_offload_used = True  # Mark that GPU code was generated
        return result
    except (NotImplementedError, Exception) as e:
        # GPU generation failed - fall back to task
        codegen._emit_warning(
            "HINT",
            f"GPU offload failed ({e}), using CPU fallback"
        )
        return _generate_task_fallback(node, codegen)


def formulas_used() -> bool:
    """Check if any formulas have been used in the current compilation."""
    return _formulas_used


def gpu_offload_used() -> bool:
    """Check if GPU offload code was generated in the current compilation."""
    return _gpu_offload_used


def reset_state():
    """Reset module state. Primarily for testing."""
    global _backend_instance, _formulas_used, _gpu_offload_used, _kernel_counter, _string_counter
    _backend_instance = None
    _formulas_used = False
    _gpu_offload_used = False
    _kernel_counter = 0
    _string_counter = 0
    reset_detection()


# =============================================================================
# Offload Eligibility Checking
# =============================================================================

def _check_comprehension(node, codegen: 'CodeGenerator') -> Optional[OffloadCandidate]:
    """Check if a comprehension is offload-eligible."""
    from ast_nodes import ListComprehension

    # Only GPU offload ListComprehension - not Set or Map.
    # Set and Map have different semantics (deduplication, key-value pairs)
    # that require CPU-side processing.
    if not isinstance(node, ListComprehension):
        return None

    # Only handle single-clause comprehensions for now
    if len(node.clauses) != 1:
        return None

    clause = node.clauses[0]

    # Don't GPU offload if there's a filter condition.
    # Filter predicates require conditional output which the simple
    # map kernel doesn't support yet.
    if clause.condition is not None:
        return None

    # Check if value is a formula expression
    if not _is_formula_expression(node.value, codegen):
        return None
    formula_expr = node.value

    # Extract loop variable name
    loop_var = _extract_pattern_name(clause.pattern)
    if loop_var is None:
        return None

    return OffloadCandidate(
        construct_type='comprehension',
        original_node=node,
        formula_expr=formula_expr,
        collection_expr=clause.iterable,
        loop_var=loop_var,
        filter_expr=clause.condition
    )


def _check_first_assign(node, codegen: 'CodeGenerator') -> Optional[OffloadCandidate]:
    """Check if a first-assign is offload-eligible."""
    body_expr = _extract_body_expr(node.body)
    if body_expr is None:
        return None

    if not _is_formula_expression(body_expr, codegen):
        return None

    loop_var = _extract_pattern_name(node.pattern)
    if loop_var is None:
        return None

    return OffloadCandidate(
        construct_type='first',
        original_node=node,
        formula_expr=body_expr,
        collection_expr=node.iterable,
        loop_var=loop_var
    )


def _check_most_assign(node, codegen: 'CodeGenerator') -> Optional[OffloadCandidate]:
    """Check if a most-assign is offload-eligible."""
    body_expr = _extract_body_expr(node.body)
    if body_expr is None:
        return None

    if not _is_formula_expression(body_expr, codegen):
        return None

    loop_var = _extract_pattern_name(node.pattern)
    if loop_var is None:
        return None

    return OffloadCandidate(
        construct_type='most',
        original_node=node,
        formula_expr=body_expr,
        collection_expr=node.iterable,
        loop_var=loop_var
    )


def _check_for_assign(node, codegen: 'CodeGenerator') -> Optional[OffloadCandidate]:
    """Check if a for-assign is offload-eligible."""
    if not _is_formula_expression(node.body_expr, codegen):
        return None

    loop_var = _extract_pattern_name(node.pattern)
    if loop_var is None:
        return None

    return OffloadCandidate(
        construct_type='for',
        original_node=node,
        formula_expr=node.body_expr,
        collection_expr=node.iterable,
        loop_var=loop_var
    )


def _is_formula_expression(expr, codegen: 'CodeGenerator') -> bool:
    """Check if an expression consists only of formula-kind function calls.

    Both formula and formula32 are valid for GPU offload.
    """
    from ast_nodes import (
        FunctionKind, CallExpr, Identifier, BinaryExpr, UnaryExpr,
        IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, CharLiteral, NilLiteral,
        MemberExpr, IndexExpr
    )

    if isinstance(expr, CallExpr):
        func_name = _get_call_name(expr)
        if func_name is None:
            return False

        # Check if it's a formula (formula or formula32)
        if func_name in codegen.func_decls:
            decl = codegen.func_decls[func_name]
            if decl.kind not in (FunctionKind.FORMULA, FunctionKind.FORMULA32):
                return False
        else:
            # Unknown function - might be a builtin
            if func_name not in _FORMULA_BUILTINS:
                return False

        # Check all arguments recursively
        for arg in expr.args:
            if not _is_formula_expression(arg, codegen):
                return False
        return True

    elif isinstance(expr, BinaryExpr):
        return (_is_formula_expression(expr.left, codegen) and
                _is_formula_expression(expr.right, codegen))

    elif isinstance(expr, UnaryExpr):
        return _is_formula_expression(expr.operand, codegen)

    elif isinstance(expr, (IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, CharLiteral, NilLiteral)):
        return True

    elif isinstance(expr, Identifier):
        return True

    elif isinstance(expr, IndexExpr):
        return (_is_formula_expression(expr.collection, codegen) and
                _is_formula_expression(expr.index, codegen))

    elif isinstance(expr, MemberExpr):
        return _is_formula_expression(expr.object, codegen)

    else:
        return False


def _get_formula_precision(expr, codegen: 'CodeGenerator') -> int:
    """Get precision (32 or 64) for a formula expression.

    Returns 32 if any formula32 function is used in the expression,
    otherwise returns 64 (default precision).
    """
    from ast_nodes import FunctionKind, CallExpr, BinaryExpr, UnaryExpr, MemberExpr, IndexExpr

    if isinstance(expr, CallExpr):
        func_name = _get_call_name(expr)
        if func_name and func_name in codegen.func_decls:
            decl = codegen.func_decls[func_name]
            if decl.kind == FunctionKind.FORMULA32:
                return 32

        # Check arguments for formula32 usage
        for arg in expr.args:
            if _get_formula_precision(arg, codegen) == 32:
                return 32
        return 64

    elif isinstance(expr, BinaryExpr):
        left_precision = _get_formula_precision(expr.left, codegen)
        right_precision = _get_formula_precision(expr.right, codegen)
        # If either side uses 32-bit, the whole expression is 32-bit
        return 32 if (left_precision == 32 or right_precision == 32) else 64

    elif isinstance(expr, UnaryExpr):
        return _get_formula_precision(expr.operand, codegen)

    elif isinstance(expr, IndexExpr):
        return _get_formula_precision(expr.object, codegen)

    elif isinstance(expr, MemberExpr):
        return _get_formula_precision(expr.object, codegen)

    else:
        return 64  # Default to 64-bit precision


# Math functions that are formula-compatible (pure, no side effects)
_FORMULA_BUILTINS = {
    'abs', 'sqrt', 'sin', 'cos', 'tan', 'exp', 'log', 'pow',
    'floor', 'ceil', 'round', 'min', 'max', 'fabs',
    'asin', 'acos', 'atan', 'atan2', 'sinh', 'cosh', 'tanh',
}


def _get_call_name(expr) -> Optional[str]:
    """Extract function name from a call expression."""
    from ast_nodes import Identifier, MemberExpr

    if isinstance(expr.callee, Identifier):
        return expr.callee.name
    elif isinstance(expr.callee, MemberExpr):
        return expr.callee.member
    return None


def _extract_pattern_name(pattern) -> Optional[str]:
    """Extract variable name from a pattern."""
    if isinstance(pattern, str):
        return pattern
    if hasattr(pattern, 'name'):
        return pattern.name
    return None


def _extract_body_expr(body) -> Optional[Any]:
    """Extract the expression from a block body."""
    if isinstance(body, list):
        if len(body) == 1:
            stmt = body[0]
            if hasattr(stmt, 'expr'):
                return stmt.expr
            if hasattr(stmt, 'value'):
                return stmt.value
        return None
    # If body is already an expression, return it
    from ast_nodes import Expr
    if isinstance(body, Expr):
        return body
    return None


# =============================================================================
# Backend Management
# =============================================================================

def _get_backend():
    """Get the backend instance, creating it lazily if needed."""
    global _backend_instance

    if _backend_instance is not None:
        return _backend_instance

    backend_type = detect_backend()

    if backend_type == GPUBackend.NONE:
        return None

    if backend_type == GPUBackend.METAL:
        from codegen.formula.metal import MetalBackend
        _backend_instance = MetalBackend()
        return _backend_instance

    if backend_type == GPUBackend.CUDA:
        from codegen.formula.cuda import CUDABackend
        _backend_instance = CUDABackend()
        return _backend_instance

    return None


# =============================================================================
# GPU Offload Generation
# =============================================================================

def _generate_gpu_offload(candidate: OffloadCandidate, backend, codegen: 'CodeGenerator') -> OffloadResult:
    """Generate GPU kernel and dispatch code for an offload candidate.

    This function validates everything BEFORE generating any LLVM IR to avoid
    corrupting builder state on failure. The flow is:
    1. Check collection type is Array (no implicit conversion yet)
    2. Transpile formula body to GPU code (string only, no LLVM)
    3. Generate kernel source
    4. Only then generate LLVM IR for dispatch

    Args:
        candidate: Information about the offloadable construct
        backend: GPU backend instance (Metal, CUDA)
        codegen: CodeGenerator instance

    Returns:
        OffloadResult with the generated LLVM IR value
    """
    from llvmlite import ir
    from codegen.formula.marshaling import MarshalingGenerator, get_element_size
    from codegen.formula.transpiler import FormulaTranspiler, infer_element_type, infer_return_type
    from ast_nodes import ListType, ArrayType, SetType, PrimitiveType, Identifier

    # === VALIDATION PHASE - No LLVM IR generation ===
    # Check everything that could fail BEFORE modifying builder state

    # Phase 2 limitation: Only handle direct Array types for now.
    # List/Set would require implicit conversion which adds complexity.
    collection_type = _get_collection_type(candidate.collection_expr, codegen)
    if collection_type is None or not isinstance(collection_type, ArrayType):
        # Not a direct Array - fall back to CPU path
        raise NotImplementedError(
            "GPU offload currently only supports Array types directly. "
            "Lists/Sets require conversion which is not yet implemented."
        )

    # Transpile formula body to GPU code FIRST (no LLVM generation)
    # This validates that the formula can be transpiled before we modify builder state
    transpiler = FormulaTranspiler(codegen)
    loop_var = candidate.loop_var

    try:
        formula_body_code = transpiler.transpile(candidate.formula_expr, loop_var)
    except Exception as e:
        raise NotImplementedError(f"Cannot transpile formula to GPU code: {e}")

    # Determine element type and output type
    input_elem_type = 'int'  # Default
    if collection_type:
        input_elem_type = infer_element_type(collection_type)

    output_type = infer_return_type(candidate.formula_expr, codegen)

    # Generate kernel source (still no LLVM generation)
    kernel_name = _generate_kernel_name(codegen)
    input_params = [(loop_var, input_elem_type)]

    if candidate.construct_type == 'comprehension':
        kernel_source = backend.emit_map_kernel(
            kernel_name=kernel_name,
            formula_body=formula_body_code,
            input_params=input_params,
            output_type=output_type
        )
    else:
        # first/most use predicate kernels
        kernel_source = backend.emit_predicate_kernel(
            kernel_name=kernel_name,
            predicate_body=formula_body_code,
            input_params=input_params
        )

    # === LLVM IR GENERATION PHASE ===
    # Everything validated, safe to generate IR now

    marshaler = MarshalingGenerator(codegen)
    builder = codegen.builder
    i64 = ir.IntType(64)
    i8_ptr = ir.IntType(8).as_pointer()

    # Generate collection expression
    collection_value = codegen._generate_expression(candidate.collection_expr)

    # Extract buffer info (zero-copy for input)
    input_ptr, count, elem_size = marshaler.array_to_buffer(builder, collection_value)

    # Create string constants for kernel source and name
    kernel_source_global = _create_string_constant(codegen, kernel_source)
    kernel_name_global = _create_string_constant(codegen, kernel_name)

    # Ensure malloc/free are declared for output buffer
    marshaler.ensure_malloc_free()

    # Allocate output buffer
    output_elem_size = ir.Constant(i64, get_element_size(output_type))
    output_buffer = marshaler.allocate_output_buffer(builder, count, output_elem_size)

    # Declare and call coex_metal_dispatch
    dispatch_func = _get_or_declare_metal_dispatch(codegen)
    builder.call(dispatch_func, [
        kernel_source_global,
        kernel_name_global,
        builder.bitcast(input_ptr, i8_ptr),
        count,
        output_buffer,
        output_elem_size
    ])

    # Create result Array from output buffer
    result_array = marshaler.buffer_to_array(builder, output_buffer, count, output_elem_size)

    # Free temporary output buffer (data has been copied to array)
    marshaler.free_output_buffer(builder, output_buffer)

    return OffloadResult(handled=True, value=result_array)


def _is_array_type(llvm_type) -> bool:
    """Check if an LLVM type is an Array pointer."""
    from llvmlite import ir
    if isinstance(llvm_type, ir.PointerType):
        pointee = llvm_type.pointee
        if hasattr(pointee, 'name') and 'Array' in str(pointee.name):
            return True
    return False


def _convert_to_array(value, codegen: 'CodeGenerator'):
    """Convert a collection to Array using codegen's conversion helpers."""
    llvm_type = value.type
    if hasattr(llvm_type, 'pointee') and hasattr(llvm_type.pointee, 'name'):
        type_name = str(llvm_type.pointee.name)
        if 'List' in type_name:
            return codegen.conversions.list_to_array(value)
        elif 'Set' in type_name:
            return codegen.conversions.set_to_array(value)
    # If we can't convert, just return as-is (will likely cause issues)
    return value


def _get_collection_type(expr, codegen: 'CodeGenerator'):
    """Get the Coex type of a collection expression."""
    from ast_nodes import Identifier, ListType, ArrayType, SetType

    if isinstance(expr, Identifier):
        if expr.name in codegen.var_coex_types:
            return codegen.var_coex_types[expr.name]
    return None


# Counter for unique kernel names
_kernel_counter = 0
_string_counter = 0  # Separate counter for string constants


def _generate_kernel_name(codegen: 'CodeGenerator') -> str:
    """Generate a unique kernel name."""
    global _kernel_counter
    _kernel_counter += 1
    return f"coex_kernel_{_kernel_counter}"


def _create_string_constant(codegen: 'CodeGenerator', value: str):
    """Create a global string constant and return a pointer to it."""
    from llvmlite import ir

    # Create null-terminated string data
    data = (value + '\0').encode('utf-8')
    str_type = ir.ArrayType(ir.IntType(8), len(data))

    # Create unique global name
    global _string_counter
    _string_counter += 1
    global_name = f".str.kernel.{_string_counter}"

    # Create global constant
    str_global = ir.GlobalVariable(codegen.module, str_type, name=global_name)
    str_global.initializer = ir.Constant(str_type, bytearray(data))
    str_global.global_constant = True
    str_global.linkage = 'private'

    # Get pointer to first element
    i32 = ir.IntType(32)
    return codegen.builder.gep(
        str_global,
        [ir.Constant(i32, 0), ir.Constant(i32, 0)],
        inbounds=True
    )


def _get_or_declare_metal_dispatch(codegen: 'CodeGenerator'):
    """Get or declare the coex_metal_dispatch external function."""
    from llvmlite import ir

    func_name = "coex_metal_dispatch"

    # Check if already declared
    try:
        return codegen.module.get_global(func_name)
    except KeyError:
        pass

    # Declare the function
    # void coex_metal_dispatch(const char* src, const char* name,
    #                          void* in, int64_t count, void* out, int64_t elem_size)
    i8_ptr = ir.IntType(8).as_pointer()
    i64 = ir.IntType(64)
    void = ir.VoidType()

    func_type = ir.FunctionType(void, [i8_ptr, i8_ptr, i8_ptr, i64, i8_ptr, i64])
    return ir.Function(codegen.module, func_type, name=func_name)


# =============================================================================
# Task Fallback
# =============================================================================

def _generate_task_fallback(node: Any, codegen: 'CodeGenerator') -> Optional[OffloadResult]:
    """Generate task-based fallback for formula constructs.

    Returns None to signal that normal codegen should handle this construct,
    which already uses tasks for parallel execution.
    """
    return None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    'GPUBackend',
    'detect_backend',
    'get_backend_name',
    'reset_detection',
    'try_offload',
    'OffloadResult',
    'formulas_used',
    'reset_state',
]
