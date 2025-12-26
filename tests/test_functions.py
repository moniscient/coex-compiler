"""
Tests for functions.

These tests verify:
- Function declarations and calls
- All three function kinds (formula, task, func)
- Recursion
- Multiple parameters
- Functions calling functions
"""

import pytest


class TestFuncKind:
    """Tests for func (unrestricted) functions."""
    
    def test_simple_func(self, expect_output):
        expect_output('''
func add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(add(3, 4))
    return 0
~
''', "7\n")
    
    def test_func_no_params(self, expect_output):
        expect_output('''
func get_magic() -> int
    return 42
~

func main() -> int
    print(get_magic())
    return 0
~
''', "42\n")
    
    def test_func_multiple_params(self, expect_output):
        expect_output('''
func compute(a: int, b: int, c: int) -> int
    return a * b + c
~

func main() -> int
    print(compute(2, 3, 4))
    return 0
~
''', "10\n")
    
    def test_func_with_locals(self, expect_output):
        expect_output('''
func sum_range(first: int, last: int) -> int
    sum: int = 0
    for i in range(first, last)
        sum += i
    ~
    return sum
~

func main() -> int
    print(sum_range(1, 6))
    return 0
~
''', "15\n")


class TestFormulaKind:
    """Tests for formula (pure) functions."""
    
    def test_simple_formula(self, expect_output):
        expect_output('''
formula square(x: int) -> int
    return x * x
~

func main() -> int
    print(square(7))
    return 0
~
''', "49\n")
    
    def test_formula_two_params(self, expect_output):
        expect_output('''
formula multiply(a: int, b: int) -> int
    return a * b
~

func main() -> int
    print(multiply(6, 7))
    return 0
~
''', "42\n")
    
    def test_formula_with_expression(self, expect_output):
        expect_output('''
formula polynomial(x: int) -> int
    return x * x + 2 * x + 1
~

func main() -> int
    print(polynomial(3))
    return 0
~
''', "16\n")


class TestTaskKind:
    """Tests for task (concurrent) functions.
    
    Note: Tasks currently execute sequentially, but syntax should work.
    """
    
    def test_simple_task(self, expect_output):
        expect_output('''
task work(n: int) -> int
    sum: int = 0
    for i in range(0, n)
        sum += i
    ~
    return sum
~

func main() -> int
    print(work(5))
    return 0
~
''', "10\n")
    
    def test_task_with_func(self, expect_output):
        expect_output('''
task compute(x: int) -> int
    return x * 2
~

func main() -> int
    result: int = compute(21)
    print(result)
    return 0
~
''', "42\n")


class TestRecursion:
    """Tests for recursive functions."""
    
    def test_factorial(self, expect_output):
        expect_output('''
formula factorial(n: int) -> int
    if n <= 1
        return 1
    else
        return n * factorial(n - 1)
    ~
~

func main() -> int
    print(factorial(5))
    return 0
~
''', "120\n")
    
    def test_fibonacci(self, expect_output):
        expect_output('''
formula fib(n: int) -> int
    if n <= 1
        return n
    else
        return fib(n - 1) + fib(n - 2)
    ~
~

func main() -> int
    print(fib(10))
    return 0
~
''', "55\n")
    
    def test_gcd(self, expect_output):
        expect_output('''
formula gcd(a: int, b: int) -> int
    if b == 0
        return a
    else
        return gcd(b, a % b)
    ~
~

func main() -> int
    print(gcd(48, 18))
    return 0
~
''', "6\n")
    
    def test_tail_recursive_sum(self, expect_output):
        expect_output('''
formula sum_helper(n: int, acc: int) -> int
    if n <= 0
        return acc
    else
        return sum_helper(n - 1, acc + n)
    ~
~

func main() -> int
    print(sum_helper(10, 0))
    return 0
~
''', "55\n")


class TestFunctionCalls:
    """Tests for function call patterns."""
    
    def test_function_calling_function(self, expect_output):
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
    
    def test_function_result_as_argument(self, expect_output):
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(add(add(1, 2), add(3, 4)))
    return 0
~
''', "10\n")
    
    def test_function_in_expression(self, expect_output):
        expect_output('''
formula square(x: int) -> int
    return x * x
~

func main() -> int
    result: int = square(3) + square(4)
    print(result)
    return 0
~
''', "25\n")
    
    def test_global_used_in_function(self, expect_output):
        expect_output('''
var MULTIPLIER: int = 10

func scale(x: int) -> int
    return x * MULTIPLIER
~

func main() -> int
    print(scale(5))
    return 0
~
''', "50\n")


class TestMixedFunctionKinds:
    """Tests for mixing different function kinds."""
    
    def test_func_calls_formula(self, expect_output):
        expect_output('''
formula pure_add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    print(pure_add(20, 22))
    return 0
~
''', "42\n")
    
    def test_task_calls_formula(self, expect_output):
        expect_output('''
formula compute(x: int) -> int
    return x * x
~

task worker(n: int) -> int
    sum: int = 0
    for i in range(1, n)
        sum += compute(i)
    ~
    return sum
~

func main() -> int
    print(worker(5))
    return 0
~
''', "30\n")


class TestFormulaPurity:
    """Tests that formulas are pure (require const bindings)."""

    def test_rebindable_in_formula_rejected(self, expect_compile_error):
        """Rebindable bindings should be rejected in formulas."""
        expect_compile_error('''
formula bad_formula(x: int) -> int
    total: int = 0
    total = x * 2
    return total
~

func main() -> int
    print(bad_formula(21))
    return 0
~
''', "requires const")

    def test_const_in_formula_allowed(self, expect_output):
        """Const bindings should work in formulas."""
        expect_output('''
formula good_formula(x: int) -> int
    const result = x * 2
    return result
~

func main() -> int
    print(good_formula(21))
    return 0
~
''', "42\n")

    def test_var_in_func_allowed(self, expect_output):
        """declarations should be allowed in func."""
        expect_output('''
func compute(x: int) -> int
    total: int = 0
    total = x * 2
    return total
~

func main() -> int
    print(compute(21))
    return 0
~
''', "42\n")

    def test_var_in_task_allowed(self, expect_output):
        """declarations should be allowed in task."""
        expect_output('''
task compute(x: int) -> int
    total: int = 0
    total = x * 2
    return total
~

func main() -> int
    print(compute(21))
    return 0
~
''', "42\n")
