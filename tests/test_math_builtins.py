"""Tests for math builtin functions: sin, cos, sqrt, atan2, floor, ceil."""
import pytest


class TestMathBuiltins:
    """Test math builtin functions."""

    def test_sqrt_basic(self, expect_output):
        expect_output('''
func main() -> int
    x = sqrt(4.0)
    print(x)
    return 0
~
''', "2.000000\n")

    def test_sqrt_of_zero(self, expect_output):
        expect_output('''
func main() -> int
    print(sqrt(0.0))
    return 0
~
''', "0.000000\n")

    def test_sqrt_int_arg(self, expect_output):
        expect_output('''
func main() -> int
    print(sqrt(9))
    return 0
~
''', "3.000000\n")

    def test_sin_zero(self, expect_output):
        expect_output('''
func main() -> int
    print(sin(0.0))
    return 0
~
''', "0.000000\n")

    def test_cos_zero(self, expect_output):
        expect_output('''
func main() -> int
    print(cos(0.0))
    return 0
~
''', "1.000000\n")

    def test_sin_cos_identity(self, compile_coex):
        """sin^2(x) + cos^2(x) == 1"""
        result = compile_coex('''
func main() -> int
    x = 1.5
    s = sin(x)
    c = cos(x)
    sum = s * s + c * c
    if sum > 0.999999
        if sum < 1.000001
            print(1)
        ~
    ~
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        assert "1\n" in result.run_output

    def test_sqrt_in_formula(self, expect_output):
        """sqrt should work in formula context (pure function)."""
        expect_output('''
formula hypotenuse(a: float, b: float) -> float
    return sqrt(a * a + b * b)
~

func main() -> int
    print(hypotenuse(3.0, 4.0))
    return 0
~
''', "5.000000\n")

    def test_sin_in_task(self, compile_coex):
        """sin should work in task context."""
        result = compile_coex('''
task compute(x: float) -> float
    return sin(x)
~

func main() -> int
    r := compute(0.0)
    print(r)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        assert "0.000000" in result.run_output

    def test_atan2_basic(self, compile_coex):
        """atan2(1.0, 1.0) ~= 0.785398 (pi/4)"""
        result = compile_coex('''
func main() -> int
    a = atan2(1.0, 1.0)
    if a > 0.785
        if a < 0.786
            print(1)
        ~
    ~
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        assert "1\n" in result.run_output

    def test_floor_basic(self, expect_output):
        expect_output('''
func main() -> int
    print(floor(3.7))
    return 0
~
''', "3.000000\n")

    def test_floor_negative(self, expect_output):
        expect_output('''
func main() -> int
    print(floor(-2.3))
    return 0
~
''', "-3.000000\n")

    def test_ceil_basic(self, expect_output):
        expect_output('''
func main() -> int
    print(ceil(3.2))
    return 0
~
''', "4.000000\n")

    def test_ceil_negative(self, expect_output):
        expect_output('''
func main() -> int
    print(ceil(-2.7))
    return 0
~
''', "-2.000000\n")

    def test_combined_trig(self, compile_coex):
        """Test a torus-like calculation: (R + r*cos(phi))*cos(theta)"""
        result = compile_coex('''
func main() -> int
    R = 50.0
    r = 15.0
    phi = 0.0
    theta = 0.0
    x = (R + r * cos(phi)) * cos(theta)
    if x > 64.99
        if x < 65.01
            print(1)
        ~
    ~
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        assert "1\n" in result.run_output
