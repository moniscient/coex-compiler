"""
Formula AST to GPU Code Transpiler.

This module converts Coex formula AST expressions to C-like GPU code strings.
The generated code is used in Metal/CUDA kernels.

The transpiler handles:
- Binary expressions (+, -, *, /, %, ==, !=, <, >, <=, >=, and, or)
- Unary expressions (-, not)
- Function calls (formula-kind functions and math builtins)
- Identifiers (loop variables become _x, _y, etc.)
- Literals (int, float, bool)
- Ternary expressions (cond ? then : else)
"""

from typing import Dict, Optional, Set, TYPE_CHECKING
from ast_nodes import (
    BinaryExpr, UnaryExpr, CallExpr, Identifier, MemberExpr,
    IntLiteral, FloatLiteral, BoolLiteral, TernaryExpr,
    BinaryOp, UnaryOp
)
from codegen.formula.base import TranspileError

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


# Binary operator to C operator mapping
BINARY_OP_MAP = {
    BinaryOp.ADD: '+',
    BinaryOp.SUB: '-',
    BinaryOp.MUL: '*',
    BinaryOp.DIV: '/',
    BinaryOp.MOD: '%',
    BinaryOp.EQ: '==',
    BinaryOp.NE: '!=',
    BinaryOp.LT: '<',
    BinaryOp.GT: '>',
    BinaryOp.LE: '<=',
    BinaryOp.GE: '>=',
    BinaryOp.AND: '&&',
    BinaryOp.OR: '||',
}

# Unary operator to C operator mapping
UNARY_OP_MAP = {
    UnaryOp.NEG: '-',
    UnaryOp.NOT: '!',
}

# Math functions available in Metal/CUDA
# Maps Coex function name to GPU function name
GPU_FUNCTION_MAP = {
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
    'round': 'round',
    'min': 'min',
    'max': 'max',
    'fabs': 'fabs',
    'asin': 'asin',
    'acos': 'acos',
    'atan': 'atan',
    'atan2': 'atan2',
    'sinh': 'sinh',
    'cosh': 'cosh',
    'tanh': 'tanh',
}


class FormulaTranspiler:
    """Transpiles Coex formula AST to C-like GPU code."""

    def __init__(self, codegen: 'CodeGenerator' = None):
        """Initialize the transpiler.

        Args:
            codegen: Optional CodeGenerator for resolving formula definitions
        """
        self.codegen = codegen
        self.loop_vars: Set[str] = set()  # Variables to prefix with _
        self.inline_formulas: Dict[str, str] = {}  # formula_name -> transpiled body

    def transpile(self, expr, loop_var: str) -> str:
        """Main entry point: transpile an expression to GPU code.

        Args:
            expr: AST expression node
            loop_var: Name of the loop variable (e.g., 'x')

        Returns:
            C-like code string for use in GPU kernel

        Raises:
            TranspileError: If expression cannot be transpiled
        """
        self.loop_vars = {loop_var}
        return self._transpile_expr(expr)

    def transpile_with_vars(self, expr, loop_vars: Set[str]) -> str:
        """Transpile with multiple loop variables.

        Args:
            expr: AST expression node
            loop_vars: Set of loop variable names

        Returns:
            C-like code string
        """
        self.loop_vars = loop_vars
        return self._transpile_expr(expr)

    def _transpile_expr(self, expr) -> str:
        """Recursively transpile an expression."""
        if isinstance(expr, IntLiteral):
            return str(expr.value)

        if isinstance(expr, FloatLiteral):
            # Ensure we get a proper float representation
            s = str(expr.value)
            if '.' not in s and 'e' not in s.lower():
                s = s + '.0'
            return s

        if isinstance(expr, BoolLiteral):
            return 'true' if expr.value else 'false'

        if isinstance(expr, Identifier):
            name = expr.name
            if name in self.loop_vars:
                return f'_{name}'  # Loop vars become _x, _y, etc.
            # Check if it's a constant we can inline
            if self.codegen and name in self.codegen.constants:
                const_val = self.codegen.constants[name]
                if isinstance(const_val, int):
                    return str(const_val)
                elif isinstance(const_val, float):
                    return str(const_val)
            return name

        if isinstance(expr, BinaryExpr):
            return self._transpile_binary(expr)

        if isinstance(expr, UnaryExpr):
            return self._transpile_unary(expr)

        if isinstance(expr, CallExpr):
            return self._transpile_call(expr)

        if isinstance(expr, TernaryExpr):
            cond = self._transpile_expr(expr.condition)
            then_part = self._transpile_expr(expr.then_expr)
            else_part = self._transpile_expr(expr.else_expr)
            return f'({cond} ? {then_part} : {else_part})'

        if isinstance(expr, MemberExpr):
            # For simple field access or chained calls
            obj = self._transpile_expr(expr.object)
            return f'{obj}.{expr.member}'

        raise TranspileError(f"Cannot transpile expression type: {type(expr).__name__}")

    def _transpile_binary(self, expr: BinaryExpr) -> str:
        """Transpile a binary expression."""
        if expr.op not in BINARY_OP_MAP:
            raise TranspileError(f"Unsupported binary operator for GPU: {expr.op}")

        left = self._transpile_expr(expr.left)
        right = self._transpile_expr(expr.right)
        op = BINARY_OP_MAP[expr.op]

        return f'({left} {op} {right})'

    def _transpile_unary(self, expr: UnaryExpr) -> str:
        """Transpile a unary expression."""
        if expr.op not in UNARY_OP_MAP:
            raise TranspileError(f"Unsupported unary operator for GPU: {expr.op}")

        operand = self._transpile_expr(expr.operand)
        op = UNARY_OP_MAP[expr.op]

        return f'({op}{operand})'

    def _transpile_call(self, expr: CallExpr) -> str:
        """Transpile a function call."""
        func_name = self._get_call_name(expr)
        if func_name is None:
            raise TranspileError(f"Cannot determine function name for GPU call")

        # Check if it's a GPU builtin
        if func_name in GPU_FUNCTION_MAP:
            gpu_func = GPU_FUNCTION_MAP[func_name]
            args = [self._transpile_expr(arg) for arg in expr.args]
            return f'{gpu_func}({", ".join(args)})'

        # Check if it's a user-defined formula we can inline
        if self.codegen and func_name in self.codegen.func_decls:
            from ast_nodes import FunctionKind
            decl = self.codegen.func_decls[func_name]
            if decl.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32):
                return self._inline_formula_call(func_name, decl, expr.args)

        raise TranspileError(f"Cannot transpile call to '{func_name}' for GPU")

    def _get_call_name(self, expr: CallExpr) -> Optional[str]:
        """Extract function name from call expression."""
        if isinstance(expr.callee, Identifier):
            return expr.callee.name
        if isinstance(expr.callee, MemberExpr):
            return expr.callee.member
        return None

    def _inline_formula_call(self, name: str, decl, args) -> str:
        """Inline a formula call into the GPU code.

        For simple formulas, we substitute arguments directly into the body.
        Complex formulas may need to be transpiled to separate functions.
        """
        # Extract parameter names
        param_names = [p.name for p in decl.params]

        if len(args) != len(param_names):
            raise TranspileError(
                f"Formula '{name}' expects {len(param_names)} args, got {len(args)}"
            )

        # Check if we've already inlined this formula
        if name in self.inline_formulas:
            # Use the cached transpilation with argument substitution
            pass  # Fall through to substitution

        # Get formula body
        body = decl.body
        if isinstance(body, list):
            # Block body - look for return statement
            if len(body) == 1:
                stmt = body[0]
                if hasattr(stmt, 'value'):
                    body = stmt.value
                elif hasattr(stmt, 'expr'):
                    body = stmt.expr
                else:
                    raise TranspileError(
                        f"Formula '{name}' has unsupported body structure"
                    )
            else:
                raise TranspileError(
                    f"Formula '{name}' has multi-statement body, cannot inline"
                )

        # Create substitution map
        substitutions = {}
        for param_name, arg_expr in zip(param_names, args):
            substitutions[param_name] = self._transpile_expr(arg_expr)

        # Transpile body with substitutions
        return self._transpile_with_substitution(body, substitutions)

    def _transpile_with_substitution(self, expr, substitutions: Dict[str, str]) -> str:
        """Transpile expression with parameter substitutions."""
        if isinstance(expr, IntLiteral):
            return str(expr.value)

        if isinstance(expr, FloatLiteral):
            s = str(expr.value)
            if '.' not in s and 'e' not in s.lower():
                s = s + '.0'
            return s

        if isinstance(expr, BoolLiteral):
            return 'true' if expr.value else 'false'

        if isinstance(expr, Identifier):
            name = expr.name
            if name in substitutions:
                return substitutions[name]
            if name in self.loop_vars:
                return f'_{name}'
            return name

        if isinstance(expr, BinaryExpr):
            left = self._transpile_with_substitution(expr.left, substitutions)
            right = self._transpile_with_substitution(expr.right, substitutions)
            if expr.op not in BINARY_OP_MAP:
                raise TranspileError(f"Unsupported binary operator: {expr.op}")
            op = BINARY_OP_MAP[expr.op]
            return f'({left} {op} {right})'

        if isinstance(expr, UnaryExpr):
            operand = self._transpile_with_substitution(expr.operand, substitutions)
            if expr.op not in UNARY_OP_MAP:
                raise TranspileError(f"Unsupported unary operator: {expr.op}")
            op = UNARY_OP_MAP[expr.op]
            return f'({op}{operand})'

        if isinstance(expr, CallExpr):
            func_name = self._get_call_name(expr)
            if func_name in GPU_FUNCTION_MAP:
                gpu_func = GPU_FUNCTION_MAP[func_name]
                args = [
                    self._transpile_with_substitution(arg, substitutions)
                    for arg in expr.args
                ]
                return f'{gpu_func}({", ".join(args)})'
            raise TranspileError(f"Cannot transpile nested call to '{func_name}'")

        if isinstance(expr, TernaryExpr):
            cond = self._transpile_with_substitution(expr.condition, substitutions)
            then_part = self._transpile_with_substitution(expr.then_expr, substitutions)
            else_part = self._transpile_with_substitution(expr.else_expr, substitutions)
            return f'({cond} ? {then_part} : {else_part})'

        raise TranspileError(
            f"Cannot transpile expression type with substitution: {type(expr).__name__}"
        )


def infer_element_type(collection_type) -> str:
    """Infer the element type of a collection.

    Args:
        collection_type: Coex type (ListType, ArrayType, SetType, etc.)

    Returns:
        Element type as string (e.g., 'int', 'float')
    """
    from ast_nodes import ListType, ArrayType, SetType, PrimitiveType, NamedType

    if isinstance(collection_type, (ListType, ArrayType, SetType)):
        elem = collection_type.element_type
        if isinstance(elem, PrimitiveType):
            return elem.name
        elif isinstance(elem, NamedType):
            return elem.name
        return 'int'  # Default

    return 'int'  # Default for unknown types


def infer_return_type(expr, codegen: 'CodeGenerator' = None) -> str:
    """Infer the return type of a formula expression.

    Args:
        expr: AST expression
        codegen: Optional CodeGenerator for type information

    Returns:
        Return type as string (e.g., 'int', 'float', 'bool')
    """
    from ast_nodes import (
        IntLiteral, FloatLiteral, BoolLiteral, BinaryExpr, UnaryExpr,
        CallExpr, Identifier, TernaryExpr
    )

    if isinstance(expr, IntLiteral):
        return 'int'

    if isinstance(expr, FloatLiteral):
        return 'float'

    if isinstance(expr, BoolLiteral):
        return 'bool'

    if isinstance(expr, BinaryExpr):
        # Comparison operators return bool
        if expr.op in (BinaryOp.EQ, BinaryOp.NE, BinaryOp.LT, BinaryOp.GT,
                       BinaryOp.LE, BinaryOp.GE):
            return 'bool'
        if expr.op in (BinaryOp.AND, BinaryOp.OR):
            return 'bool'
        # Arithmetic: check operands
        left_type = infer_return_type(expr.left, codegen)
        right_type = infer_return_type(expr.right, codegen)
        if left_type == 'float' or right_type == 'float':
            return 'float'
        return 'int'

    if isinstance(expr, UnaryExpr):
        if expr.op == UnaryOp.NOT:
            return 'bool'
        return infer_return_type(expr.operand, codegen)

    if isinstance(expr, CallExpr):
        func_name = None
        if isinstance(expr.callee, Identifier):
            func_name = expr.callee.name
        elif isinstance(expr.callee, MemberExpr):
            func_name = expr.callee.member

        if func_name and codegen and func_name in codegen.func_decls:
            decl = codegen.func_decls[func_name]
            if decl.return_type:
                from ast_nodes import PrimitiveType, NamedType
                if isinstance(decl.return_type, PrimitiveType):
                    return decl.return_type.name
                elif isinstance(decl.return_type, NamedType):
                    return decl.return_type.name

        # Math functions typically return float, but abs/min/max preserve type
        if func_name in ('abs', 'min', 'max') and expr.args:
            return infer_return_type(expr.args[0], codegen)

        return 'float'  # Default for math functions

    if isinstance(expr, TernaryExpr):
        return infer_return_type(expr.then_expr, codegen)

    if isinstance(expr, Identifier):
        # Loop variables typically have collection element type
        # Without more context, assume int
        return 'int'

    return 'int'  # Default
