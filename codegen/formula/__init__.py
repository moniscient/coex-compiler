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
    try:
        return _generate_gpu_offload(candidate, backend, codegen)
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


def reset_state():
    """Reset module state. Primarily for testing."""
    global _backend_instance, _formulas_used
    _backend_instance = None
    _formulas_used = False
    reset_detection()


# =============================================================================
# Offload Eligibility Checking
# =============================================================================

def _check_comprehension(node, codegen: 'CodeGenerator') -> Optional[OffloadCandidate]:
    """Check if a comprehension is offload-eligible."""
    # Only handle single-clause comprehensions for now
    if len(node.clauses) != 1:
        return None

    clause = node.clauses[0]

    # Check if body is a formula expression
    if not _is_formula_expression(node.body, codegen):
        return None

    # Check filter if present
    if clause.condition is not None:
        if not _is_formula_expression(clause.condition, codegen):
            return None

    # Extract loop variable name
    loop_var = _extract_pattern_name(clause.pattern)
    if loop_var is None:
        return None

    return OffloadCandidate(
        construct_type='comprehension',
        original_node=node,
        formula_expr=node.body,
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
    """Check if an expression consists only of formula-kind function calls."""
    from ast_nodes import (
        FunctionKind, CallExpr, Identifier, BinaryExpr, UnaryExpr,
        IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, CharLiteral, NilLiteral,
        MemberExpr, IndexExpr
    )

    if isinstance(expr, CallExpr):
        func_name = _get_call_name(expr)
        if func_name is None:
            return False

        # Check if it's a formula
        if func_name in codegen.func_decls:
            decl = codegen.func_decls[func_name]
            if decl.kind != FunctionKind.FORMULA:
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

    Currently raises NotImplementedError - full GPU kernel generation
    will be implemented in a future phase.
    """
    raise NotImplementedError(
        "GPU kernel generation not yet implemented. Using task fallback."
    )


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
