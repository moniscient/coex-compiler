"""
Tests for formula32 function kind.

formula32 provides 32-bit precision computation for GPU-accelerated workloads.
It has identical purity constraints to formula but uses 32-bit types internally
for better GPU performance.
"""

import pytest


class TestFormula32Basic:
    """Basic formula32 tests"""

    def test_formula32_compiles(self, expect_output):
        """Basic formula32 compiles and executes"""
        expect_output('''
formula32 double(x: int) -> int
    return x * 2
~

func main() -> int
    print(double(3))
    return 0
~
''', "6\n")

    def test_formula32_float(self, expect_output):
        """formula32 with float compiles and executes"""
        expect_output('''
formula32 half(x: float) -> float
    return x / 2.0
~

func main() -> int
    print(half(10.0))
    return 0
~
''', "5.000000\n")

    def test_formula32_with_const_binding(self, expect_output):
        """formula32 with const bindings works"""
        expect_output('''
formula32 compute(x: int) -> int
    const y = x * 2
    const z = y + 1
    return z
~

func main() -> int
    print(compute(10))
    return 0
~
''', "21\n")

    def test_formula32_with_conditionals(self, expect_output):
        """formula32 with if/else works"""
        expect_output('''
formula32 abs(x: int) -> int
    if x < 0
        return 0 - x
    else
        return x
    ~
~

func main() -> int
    print(abs(-5))
    print(abs(3))
    return 0
~
''', "5\n3\n")


class TestFormula32Purity:
    """Tests that formula32 has same purity constraints as formula"""

    def test_formula32_cannot_use_non_const_binding(self, expect_compile_error):
        """formula32 requires const bindings"""
        expect_compile_error('''
formula32 bad(x: int) -> int
    y = x + 1
    return y
~

func main() -> int
    return 0
~
''', "const")

    def test_formula32_cannot_call_print(self, expect_compile_error):
        """formula32 calling print should fail"""
        expect_compile_error('''
formula32 impure(x: int) -> int
    print(x)
    return x
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula32_cannot_call_task(self, expect_compile_error):
        """formula32 calling task should fail"""
        expect_compile_error('''
task work() -> int
    return 42
~

formula32 bad() -> int
    return work()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula32_cannot_call_func(self, expect_compile_error):
        """formula32 calling func should fail"""
        expect_compile_error('''
func impure_func() -> int
    print(1)
    return 1
~

formula32 bad() -> int
    return impure_func()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula32_cannot_use_atomic(self, expect_compile_error):
        """formula32 accessing atomic should fail"""
        expect_compile_error('''
formula32 read_atomic(counter: atomic_int) -> int
    return counter.load()
~

func main() -> int
    return 0
~
''', "formula")


class TestFormula32CallHierarchy:
    """Tests for formula32 calling hierarchy"""

    def test_formula32_calls_formula(self, expect_output):
        """formula32 can call formula"""
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

formula32 compute(x: int) -> int
    return add(x, x)
~

func main() -> int
    print(compute(5))
    return 0
~
''', "10\n")

    def test_formula_calls_formula32(self, expect_output):
        """formula can call formula32"""
        expect_output('''
formula32 double32(x: int) -> int
    return x * 2
~

formula quadruple(x: int) -> int
    return double32(double32(x))
~

func main() -> int
    print(quadruple(5))
    return 0
~
''', "20\n")

    def test_formula32_calls_formula32(self, expect_output):
        """formula32 can call formula32"""
        expect_output('''
formula32 double32(x: int) -> int
    return x * 2
~

formula32 quadruple32(x: int) -> int
    return double32(double32(x))
~

func main() -> int
    print(quadruple32(3))
    return 0
~
''', "12\n")

    def test_task_can_call_formula32(self, expect_output):
        """task can call formula32"""
        expect_output('''
formula32 add32(a: int, b: int) -> int
    return a + b
~

task compute() -> int
    return add32(10, 20)
~

func main() -> int
    print(compute())
    return 0
~
''', "30\n")

    def test_thread_can_call_formula32(self, expect_output):
        """thread can call formula32"""
        expect_output('''
formula32 multiply32(a: int, b: int) -> int
    return a * b
~

thread compute() -> int
    return multiply32(6, 7)
~

func main() -> int
    print(compute())
    return 0
~
''', "42\n")

    def test_func_can_call_formula32(self, expect_output):
        """func can call formula32"""
        expect_output('''
formula32 square32(x: int) -> int
    return x * x
~

func main() -> int
    print(square32(7))
    return 0
~
''', "49\n")


class TestFormula32Precision:
    """Tests for 32-bit precision semantics"""

    def test_formula32_int_saturation(self, expect_output):
        """Large ints saturate to INT32_MAX"""
        expect_output('''
formula32 identity(x: int) -> int
    return x
~

func main() -> int
    const large = 3000000000
    const result = identity(large)
    print(result)
    return 0
~
''', "2147483647\n")  # INT32_MAX

    def test_formula32_negative_int_saturation(self, expect_output):
        """Large negative ints saturate to INT32_MIN"""
        expect_output('''
formula32 identity(x: int) -> int
    return x
~

func main() -> int
    const large = 0 - 3000000000
    const result = identity(large)
    print(result)
    return 0
~
''', "-2147483648\n")  # INT32_MIN

    def test_formula32_int_within_range(self, expect_output):
        """Ints within 32-bit range pass through unchanged"""
        expect_output('''
formula32 identity(x: int) -> int
    return x
~

func main() -> int
    print(identity(12345))
    print(identity(-12345))
    return 0
~
''', "12345\n-12345\n")


class TestFormula32Lambda:
    """Tests for formula32 lambdas"""

    def test_formula32_lambda(self, expect_output):
        """formula32 lambda works"""
        expect_output('''
func main() -> int
    const f = formula32(x: int) => x * 3
    print(f(4))
    return 0
~
''', "12\n")
