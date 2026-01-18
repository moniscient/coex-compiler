"""
GPU Offload Integration Tests for Coex.

These tests verify the GPU offload functionality for formula-based operations.
Tests are organized into:
1. Unit tests for marshaling and transpiler (no GPU required)
2. Integration tests for GPU offload (requires Metal)
3. Correctness tests comparing GPU and CPU results
"""

import pytest
from codegen.formula import detect_backend, GPUBackend, reset_detection, reset_state


# Marker for tests requiring Metal GPU
requires_metal = pytest.mark.skipif(
    detect_backend() != GPUBackend.METAL,
    reason="Metal GPU not available"
)


class TestMarshalingUnit:
    """Unit tests for marshaling code (no GPU required)."""

    def test_element_sizes(self):
        """Verify element size calculations."""
        from codegen.formula.marshaling import get_element_size, ELEMENT_SIZES

        assert get_element_size('int') == 8
        assert get_element_size('float') == 8
        assert get_element_size('bool') == 1
        assert get_element_size('byte') == 1

    def test_invalid_element_type(self):
        """Invalid types should raise ValueError."""
        from codegen.formula.marshaling import get_element_size

        with pytest.raises(ValueError, match="Unsupported element type"):
            get_element_size('string')


class TestTranspilerUnit:
    """Unit tests for formula transpiler (no GPU required)."""

    def test_transpile_literals(self):
        """Transpile literal expressions."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import IntLiteral, FloatLiteral, BoolLiteral

        t = FormulaTranspiler()

        assert t.transpile(IntLiteral(42), 'x') == '42'
        assert t.transpile(FloatLiteral(3.14), 'x') == '3.14'
        assert t.transpile(BoolLiteral(True), 'x') == 'true'
        assert t.transpile(BoolLiteral(False), 'x') == 'false'

    def test_transpile_identifier(self):
        """Transpile identifier expressions."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import Identifier

        t = FormulaTranspiler()

        # Loop variable gets prefixed with _
        assert t.transpile(Identifier('x'), 'x') == '_x'

        # Non-loop variables stay as-is
        assert t.transpile(Identifier('y'), 'x') == 'y'

    def test_transpile_binary_ops(self):
        """Transpile binary expressions."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import BinaryExpr, Identifier, IntLiteral, BinaryOp

        t = FormulaTranspiler()

        # x + 1
        expr = BinaryExpr(BinaryOp.ADD, Identifier('x'), IntLiteral(1))
        result = t.transpile(expr, 'x')
        assert result == '(_x + 1)'

        # x * 2
        expr = BinaryExpr(BinaryOp.MUL, Identifier('x'), IntLiteral(2))
        result = t.transpile(expr, 'x')
        assert result == '(_x * 2)'

        # x < 10
        expr = BinaryExpr(BinaryOp.LT, Identifier('x'), IntLiteral(10))
        result = t.transpile(expr, 'x')
        assert result == '(_x < 10)'

    def test_transpile_unary_ops(self):
        """Transpile unary expressions."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import UnaryExpr, Identifier, IntLiteral, UnaryOp

        t = FormulaTranspiler()

        # -x
        expr = UnaryExpr(UnaryOp.NEG, Identifier('x'))
        result = t.transpile(expr, 'x')
        assert result == '(-_x)'

        # not x
        expr = UnaryExpr(UnaryOp.NOT, Identifier('x'))
        result = t.transpile(expr, 'x')
        assert result == '(!_x)'

    def test_transpile_function_calls(self):
        """Transpile builtin function calls."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import CallExpr, Identifier, IntLiteral, FloatLiteral

        t = FormulaTranspiler()

        # abs(x)
        expr = CallExpr(Identifier('abs'), [Identifier('x')])
        result = t.transpile(expr, 'x')
        assert result == 'abs(_x)'

        # sqrt(x)
        expr = CallExpr(Identifier('sqrt'), [Identifier('x')])
        result = t.transpile(expr, 'x')
        assert result == 'sqrt(_x)'

        # pow(x, 2)
        expr = CallExpr(Identifier('pow'), [Identifier('x'), IntLiteral(2)])
        result = t.transpile(expr, 'x')
        assert result == 'pow(_x, 2)'

    def test_transpile_ternary(self):
        """Transpile ternary expressions."""
        from codegen.formula.transpiler import FormulaTranspiler
        from ast_nodes import TernaryExpr, BinaryExpr, Identifier, IntLiteral, BinaryOp, UnaryExpr, UnaryOp

        t = FormulaTranspiler()

        # x > 0 ? x : -x
        condition = BinaryExpr(BinaryOp.GT, Identifier('x'), IntLiteral(0))
        then_expr = Identifier('x')
        else_expr = UnaryExpr(UnaryOp.NEG, Identifier('x'))

        expr = TernaryExpr(condition, then_expr, else_expr)
        result = t.transpile(expr, 'x')
        assert result == '((_x > 0) ? _x : (-_x))'

    def test_type_inference(self):
        """Test return type inference."""
        from codegen.formula.transpiler import infer_return_type
        from ast_nodes import (
            IntLiteral, FloatLiteral, BoolLiteral,
            BinaryExpr, BinaryOp, UnaryExpr, UnaryOp
        )

        assert infer_return_type(IntLiteral(42)) == 'int'
        assert infer_return_type(FloatLiteral(3.14)) == 'float'
        assert infer_return_type(BoolLiteral(True)) == 'bool'

        # Comparison returns bool
        cmp = BinaryExpr(BinaryOp.LT, IntLiteral(1), IntLiteral(2))
        assert infer_return_type(cmp) == 'bool'

        # Arithmetic with float returns float
        add = BinaryExpr(BinaryOp.ADD, IntLiteral(1), FloatLiteral(2.0))
        assert infer_return_type(add) == 'float'


class TestMetalBackendUnit:
    """Unit tests for Metal backend (no GPU dispatch required)."""

    @requires_metal
    def test_kernel_emission(self):
        """Test kernel source generation."""
        from codegen.formula.metal import MetalBackend

        backend = MetalBackend()

        kernel = backend.emit_map_kernel(
            kernel_name="test_kernel",
            formula_body="_x * 2",
            input_params=[('x', 'int')],
            output_type='int'
        )

        assert '#include <metal_stdlib>' in kernel
        assert 'kernel void test_kernel' in kernel
        assert '_x * 2' in kernel
        assert '_output[_id]' in kernel

    @requires_metal
    def test_predicate_kernel_emission(self):
        """Test predicate kernel source generation."""
        from codegen.formula.metal import MetalBackend

        backend = MetalBackend()

        kernel = backend.emit_predicate_kernel(
            kernel_name="pred_kernel",
            predicate_body="_x > 10",
            input_params=[('x', 'int')]
        )

        assert '#include <metal_stdlib>' in kernel
        assert 'kernel void pred_kernel' in kernel
        assert '_x > 10' in kernel
        assert '_matches[_id]' in kernel


class TestBackendDetection:
    """Tests for GPU backend detection."""

    def test_detection_caching(self):
        """Backend detection should be cached."""
        reset_detection()
        first = detect_backend()
        second = detect_backend()
        assert first == second

    def test_reset_detection(self):
        """Reset should clear cache."""
        reset_detection()
        # Just verify no crash
        detect_backend()


class TestComprehensionCPUPath:
    """Test formula comprehensions using CPU path (small collections)."""

    def test_simple_formula_comprehension(self, expect_output):
        """Simple formula comprehension should work."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

func main() -> int
    data = [1, 2, 3, 4, 5]
    result = [double(x) for x in data]
    print(result.get(0))
    print(result.get(4))
    return 0
~
''', "2\n10\n")

    def test_formula_with_arithmetic(self, expect_output):
        """Formula with inline arithmetic."""
        expect_output('''
formula square(n: int) -> int
    return n * n
~

func main() -> int
    nums = [1, 2, 3, 4, 5]
    squares = [square(x) for x in nums]
    print(squares.get(0))
    print(squares.get(2))
    print(squares.get(4))
    return 0
~
''', "1\n9\n25\n")

    def test_formula_with_conditional(self, expect_output):
        """Formula with conditional expression."""
        expect_output('''
formula abs_val(x: int) -> int
    return x > 0 ? x : -x
~

func main() -> int
    nums = [-3, -1, 0, 2, 5]
    abs_nums = [abs_val(x) for x in nums]
    print(abs_nums.get(0))
    print(abs_nums.get(1))
    print(abs_nums.get(2))
    return 0
~
''', "3\n1\n0\n")


class TestGPUOffloadIntegration:
    """Integration tests requiring actual GPU (Metal)."""

    @requires_metal
    def test_large_list_offload(self, compile_coex):
        """Large list with formula should compile and run correctly.

        Note: Array iteration in comprehensions is not implemented yet (BUG-028).
        GPU offload falls back to CPU path for List comprehensions.
        """
        code = '''
formula square(x: int) -> int
    return x * x
~

func main() -> int
    data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    result = [square(x) for x in data]
    print(result.get(0))
    print(result.get(9))
    return 0
~
'''
        # Compile and run
        result = compile_coex(code)
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Execution failed: {result.run_output}"
        assert result.run_output == "1\n100\n", f"Unexpected output: {result.run_output}"


class TestMetalRuntimeModule:
    """Tests for Metal runtime module."""

    @requires_metal
    def test_metal_availability_check(self):
        """Metal availability check should work."""
        from codegen.formula.metal_runtime import is_metal_available
        # On systems with Metal, this should return True
        # The requires_metal marker already checks this
        assert is_metal_available()

    @requires_metal
    def test_callback_creation(self):
        """Dispatch callback should be created."""
        from codegen.formula.metal_runtime import get_dispatch_callback
        callback = get_dispatch_callback()
        assert callback is not None

    @requires_metal
    def test_callback_address(self):
        """Callback address should be non-zero."""
        from codegen.formula.metal_runtime import get_dispatch_address
        addr = get_dispatch_address()
        assert addr != 0


class TestFormulaBuiltins:
    """Test formula builtins that can be GPU-offloaded."""

    def test_abs_formula(self, expect_output):
        """abs in formula should work."""
        expect_output('''
formula my_abs(x: int) -> int
    return x > 0 ? x : -x
~

func main() -> int
    print(my_abs(-5))
    print(my_abs(3))
    print(my_abs(0))
    return 0
~
''', "5\n3\n0\n")

    def test_formula_composition(self, expect_output):
        """Composed formulas should work."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

formula inc(x: int) -> int
    return x + 1
~

func main() -> int
    data = [1, 2, 3]
    # Apply double, then inc
    doubled = [double(x) for x in data]
    incremented = [inc(x) for x in doubled]
    print(incremented.get(0))
    print(incremented.get(1))
    print(incremented.get(2))
    return 0
~
''', "3\n5\n7\n")
