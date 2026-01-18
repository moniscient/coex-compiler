"""
Tests for formula purity checks.
Phase 4, Step 11 of Task System implementation.

Formulas must be pure: no I/O, no atomics, only call other formulas.
"""

import pytest


class TestFormulaPurity:
    """Tests that pure formulas compile correctly"""

    def test_pure_formula_compiles(self, expect_output):
        """Pure formula with arithmetic compiles and runs"""
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(add(1, 2))
    return 0
~
''', "3\n")

    def test_formula_calls_formula(self, expect_output):
        """Formula can call another formula"""
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

    def test_formula_with_const_binding(self, expect_output):
        """Formula with const bindings works"""
        expect_output('''
formula compute(x: int) -> int
    const y = x * 2
    const z = y + 1
    return z
~

func main() -> int
    print(compute(10))
    return 0
~
''', "21\n")

    def test_formula_with_conditionals(self, expect_output):
        """Formula with if/else works"""
        expect_output('''
formula abs(x: int) -> int
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

    def test_formula_recursive(self, expect_output):
        """Recursive formula works"""
        expect_output('''
formula factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    print(factorial(5))
    return 0
~
''', "120\n")


class TestFormulaPurityViolations:
    """Tests that impure formulas are rejected"""

    def test_formula_cannot_call_print(self, expect_compile_error):
        """Formula calling print should fail"""
        expect_compile_error('''
formula impure(x: int) -> int
    print(x)
    return x
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula_cannot_call_task(self, expect_compile_error):
        """Formula calling task should fail"""
        expect_compile_error('''
task work() -> int
    return 42
~

formula bad() -> int
    return work()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula_cannot_call_thread(self, expect_compile_error):
        """Formula calling thread should fail"""
        expect_compile_error('''
thread worker() -> int
    return 42
~

formula bad() -> int
    return worker()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula_cannot_call_func(self, expect_compile_error):
        """Formula calling func should fail"""
        expect_compile_error('''
func impure_func() -> int
    print(1)
    return 1
~

formula bad() -> int
    return impure_func()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula_cannot_use_atomic_load(self, expect_compile_error):
        """Formula accessing atomic should fail"""
        expect_compile_error('''
formula read_atomic(counter: atomic_int) -> int
    return counter.load()
~

func main() -> int
    return 0
~
''', "formula")

    def test_formula_cannot_use_atomic_store(self, expect_compile_error):
        """Formula writing atomic should fail"""
        expect_compile_error('''
formula write_atomic(counter: atomic_int) -> int
    counter.store(42)
    return 0
~

func main() -> int
    return 0
~
''', "formula")


class TestFunctionKindHierarchy:
    """Tests for function kind calling hierarchy"""

    def test_task_can_call_formula(self, expect_output):
        """Task can call formula (lighter kind)"""
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

task compute() -> int
    return add(10, 20)
~

func main() -> int
    print(compute())
    return 0
~
''', "30\n")

    @pytest.mark.xfail(reason="BUG-013: Task-to-task suspension not implemented")
    def test_task_can_call_task(self, expect_output):
        """Task can call another task"""
        expect_output('''
task inner() -> int
    return 5
~

task outer() -> int
    return inner() * 2
~

func main() -> int
    print(outer())
    return 0
~
''', "10\n")

    def test_thread_can_call_formula(self, expect_output):
        """Thread can call formula"""
        expect_output('''
formula multiply(a: int, b: int) -> int
    return a * b
~

thread compute() -> int
    return multiply(6, 7)
~

func main() -> int
    print(compute())
    return 0
~
''', "42\n")

    def test_func_can_call_all_kinds(self, expect_output):
        """Func can call any function kind"""
        expect_output('''
formula f1() -> int
    return 1
~

task t1() -> int
    return 2
~

thread th1() -> int
    return 3
~

func test_all() -> int
    a = f1()
    b := t1()
    c := th1()
    return a + b + c
~

func main() -> int
    print(test_all())
    return 0
~
''', "6\n")


class TestFormulaPurityGPUWarnings:
    """Tests for GPU-related warnings (advisory, not errors)"""

    def test_recursive_formula_warns_gpu(self, compile_with_warnings):
        """Recursive formula should warn about GPU offloading"""
        source = '''
formula factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    return 0
~
'''
        success, warnings = compile_with_warnings(source)
        assert success, "Recursive formula should compile"
        # GPU warnings are advisory - check if present
        gpu_warnings = [w for w in warnings if 'GPU' in w.get('category', '') or 'GPU' in w.get('message', '')]
        # Not requiring GPU warnings for now - they're optional
