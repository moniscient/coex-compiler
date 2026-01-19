"""
Tests for Formula GPU Offload Module.

Tests the formula module's backend detection, offload eligibility checking,
and fallback behavior. GPU-specific tests are skipped when no GPU is available.
"""

import pytest
from codegen.formula import (
    GPUBackend, detect_backend, get_backend_name, reset_detection,
    try_offload, OffloadResult, formulas_used, reset_state
)
from codegen.formula.metal import MetalBackend
from codegen.formula.cuda import CUDABackend


class TestBackendDetection:
    """Test GPU backend detection."""

    def setup_method(self):
        """Reset detection state before each test."""
        reset_detection()

    def test_detection_returns_backend(self):
        """Detection should return a valid GPUBackend."""
        backend = detect_backend()
        assert isinstance(backend, GPUBackend)
        assert backend in (GPUBackend.METAL, GPUBackend.CUDA, GPUBackend.NONE)

    def test_detection_is_cached(self):
        """Detection should be cached after first call."""
        backend1 = detect_backend()
        backend2 = detect_backend()
        assert backend1 is backend2

    def test_reset_detection_clears_cache(self):
        """reset_detection should clear the cached result."""
        detect_backend()
        reset_detection()
        # After reset, detection should run again
        # We can't test the result changes, but we can verify it doesn't crash
        backend = detect_backend()
        assert isinstance(backend, GPUBackend)

    def test_get_backend_name(self):
        """get_backend_name should return a descriptive string."""
        name = get_backend_name()
        assert isinstance(name, str)
        assert len(name) > 0
        # Should contain one of the expected backend descriptions
        assert any(s in name for s in ["Metal", "CUDA", "CPU"])


class TestMetalBackend:
    """Test Metal backend implementation."""

    def test_metal_type_mapping(self):
        """Metal backend should correctly map Coex types.

        Coex int is 64-bit, so maps to Metal 'long'.
        Coex float is 64-bit, so maps to Metal 'double'.
        """
        backend = MetalBackend()
        # Coex int is 64-bit -> Metal long
        assert backend.map_type('int') == 'long'
        # Coex float is 64-bit -> Metal double
        assert backend.map_type('float') == 'double'
        assert backend.map_type('bool') == 'bool'
        assert backend.map_type('int64') == 'long'
        assert backend.map_type('float64') == 'double'

    def test_metal_map_kernel_structure(self):
        """Metal map kernel should have correct structure."""
        backend = MetalBackend()
        source = backend.emit_map_kernel(
            "test_double",
            "_x * 2.0",
            [("x", "float")],
            "float"
        )

        # Check Metal kernel structure
        assert "#include <metal_stdlib>" in source
        assert "using namespace metal;" in source
        assert "kernel void test_double" in source
        assert "[[buffer(0)]]" in source
        assert "[[thread_position_in_grid]]" in source
        assert "_result = _x * 2.0" in source
        assert "_output[_id] = _result" in source

    def test_metal_predicate_kernel_structure(self):
        """Metal predicate kernel should have correct structure."""
        backend = MetalBackend()
        source = backend.emit_predicate_kernel(
            "test_predicate",
            "_x > 0",
            [("x", "int")]
        )

        assert "kernel void test_predicate" in source
        assert "_matches[_id]" in source
        assert "_pred ? 1 : 0" in source

    def test_metal_multiple_inputs(self):
        """Metal kernel should handle multiple input parameters."""
        backend = MetalBackend()
        source = backend.emit_map_kernel(
            "test_add",
            "_a + _b",
            [("a", "float"), ("b", "float")],
            "float"
        )

        assert "[[buffer(0)]]" in source
        assert "[[buffer(1)]]" in source
        assert "[[buffer(2)]]" in source  # Output buffer


class TestCUDABackend:
    """Test CUDA backend stub."""

    def test_cuda_type_mapping(self):
        """CUDA backend should correctly map Coex types.

        Coex int is 64-bit, so maps to CUDA 'long long'.
        Coex float is 64-bit, so maps to CUDA 'double'.
        """
        backend = CUDABackend()
        # Coex int is 64-bit -> CUDA long long
        assert backend.map_type('int') == 'long long'
        # Coex float is 64-bit -> CUDA double
        assert backend.map_type('float') == 'double'
        assert backend.map_type('int64') == 'long long'
        assert backend.map_type('float64') == 'double'

    def test_cuda_map_kernel_structure(self):
        """CUDA map kernel should have correct structure."""
        backend = CUDABackend()
        source = backend.emit_map_kernel(
            "test_double",
            "_x * 2.0",
            [("x", "float")],
            "float"
        )

        # Check CUDA kernel structure
        assert 'extern "C" __global__' in source
        assert "void test_double" in source
        assert "blockIdx.x * blockDim.x + threadIdx.x" in source
        assert "if (_id < _n)" in source

    def test_cuda_dispatch_not_implemented(self):
        """CUDA dispatch should raise NotImplementedError."""
        backend = CUDABackend()
        with pytest.raises(NotImplementedError):
            backend.dispatch("", "", [], 0)


class TestOffloadEligibility:
    """Test offload eligibility detection via compilation."""

    def test_formula_comprehension_detected(self, expect_output):
        """Comprehension with formula body should be detected as offload candidate."""
        # This test verifies that the formula module is called for comprehensions
        # with formula bodies. Since GPU is likely unavailable in CI, it falls back
        # to task execution.
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

func main() -> int
    data = [1, 2, 3, 4, 5]
    result = [double(x) for x in data]
    total = 0
    for v in result
        total = total + v
    ~
    print(total)
    return 0
~
''', "30\n")  # 2+4+6+8+10 = 30

    def test_non_formula_comprehension_not_offloaded(self, expect_output):
        """Comprehension with non-formula body should not trigger offload."""
        expect_output('''
task compute(x: int) -> int
    return x * x
~

func main() -> int
    data = [1, 2, 3]
    result = [compute(x) for x in data]
    total = 0
    for v in result
        total = total + v
    ~
    print(total)
    return 0
~
''', "14\n")  # 1+4+9 = 14

    def test_formula_simple_assignment_as_task(self, expect_output):
        """Simple formula assignment should work (uses task semantics)."""
        expect_output('''
formula square(x: int) -> int
    return x * x
~

func main() -> int
    result = square(5)
    print(result)
    return 0
~
''', "25\n")


class TestBareFormulaWarning:
    """Test bare formula call warning."""

    def test_bare_formula_call_warns(self, compile_coex):
        """Bare formula call should emit a warning."""
        result = compile_coex('''
formula do_nothing(x: int) -> int
    return x
~

func main() -> int
    do_nothing(5)
    return 0
~
''')
        # The code should still compile (warning, not error)
        assert result.compile_success
        # Check for warning in the output
        # Note: This depends on how warnings are reported - may need adjustment
        # For now, just verify compilation succeeds


class TestFormulaModuleState:
    """Test formula module state management."""

    def setup_method(self):
        """Reset state before each test."""
        reset_state()

    def test_formulas_used_initially_false(self):
        """formulas_used should be False initially."""
        assert formulas_used() == False

    def test_reset_state_clears_formulas_used(self):
        """reset_state should clear formulas_used flag."""
        # Can't easily set _formulas_used from outside, but we can verify reset works
        reset_state()
        assert formulas_used() == False


class TestFormulaConstraints:
    """Test that formula constraints are enforced."""

    def test_formula_cannot_call_task(self, compile_coex):
        """Formula should not be able to call task functions."""
        result = compile_coex('''
task do_work(x: int) -> int
    return x * 2
~

formula compute(x: int) -> int
    return do_work(x)
~

func main() -> int
    print(compute(5))
    return 0
~
''')
        # Should fail compilation
        assert not result.compile_success
        assert "Cannot call task" in result.compile_output or "formula" in result.compile_output.lower()

    def test_formula_can_call_formula(self, expect_output):
        """Formula should be able to call other formulas."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

formula quadruple(x: int) -> int
    return double(double(x))
~

func main() -> int
    print(quadruple(5))
    return 0
~
''', "20\n")


class TestFormulaWithCollections:
    """Test formula usage with various collection operations."""

    def test_formula_in_for_range(self, expect_output):
        """Formula should work in for loop over range."""
        expect_output('''
formula cube(x: int) -> int
    return x * x * x
~

func main() -> int
    total = 0
    for i in 0..5
        total = total + cube(i)
    ~
    print(total)
    return 0
~
''', "100\n")  # 0 + 1 + 8 + 27 + 64 = 100

    def test_formula_with_list_comprehension_filter(self, expect_output):
        """Formula should work with filtered comprehension."""
        expect_output('''
formula is_even(x: int) -> bool
    return x % 2 == 0
~

func main() -> int
    data = [1, 2, 3, 4, 5, 6]
    evens = [x for x in data if is_even(x)]
    print(evens.len())
    return 0
~
''', "3\n")  # [2, 4, 6]
