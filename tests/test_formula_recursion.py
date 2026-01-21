"""
Tests for formula recursion support in Coex.

Verifies:
- Self-recursion (factorial, fibonacci)
- Mutual recursion (even/odd, three-way)
- Forward references (formula A calls formula B defined later)
- Higher-order formulas (map, filter, fold patterns)
- Purity enforcement (formulas cannot call func/task)
"""

import pytest


class TestFormulaSelfRecursion:
    """Tests for self-recursive formulas."""

    def test_factorial(self, expect_output):
        """Basic self-recursion: factorial."""
        expect_output('''
formula factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    print(factorial(0))
    print(factorial(1))
    print(factorial(5))
    print(factorial(10))
    return 0
~
''', "1\n1\n120\n3628800\n")

    def test_fibonacci(self, expect_output):
        """Self-recursion with two recursive calls: fibonacci."""
        expect_output('''
formula fib(n: int) -> int
    if n <= 1
        return n
    ~
    return fib(n - 1) + fib(n - 2)
~

func main() -> int
    print(fib(0))
    print(fib(1))
    print(fib(10))
    print(fib(15))
    return 0
~
''', "0\n1\n55\n610\n")

    def test_sum_recursive(self, expect_output):
        """Recursive sum of 1..n."""
        expect_output('''
formula sum_to(n: int) -> int
    if n <= 0
        return 0
    ~
    return n + sum_to(n - 1)
~

func main() -> int
    print(sum_to(0))
    print(sum_to(1))
    print(sum_to(10))
    print(sum_to(100))
    return 0
~
''', "0\n1\n55\n5050\n")

    def test_gcd(self, expect_output):
        """Euclidean GCD algorithm."""
        expect_output('''
formula gcd(a: int, b: int) -> int
    if b == 0
        return a
    ~
    return gcd(b, a % b)
~

func main() -> int
    print(gcd(48, 18))
    print(gcd(100, 25))
    print(gcd(17, 13))
    return 0
~
''', "6\n25\n1\n")

    def test_power(self, expect_output):
        """Recursive exponentiation."""
        expect_output('''
formula power(base: int, exp: int) -> int
    if exp == 0
        return 1
    ~
    return base * power(base, exp - 1)
~

func main() -> int
    print(power(2, 0))
    print(power(2, 10))
    print(power(3, 5))
    return 0
~
''', "1\n1024\n243\n")


class TestFormulaMutualRecursion:
    """Tests for mutually recursive formulas."""

    def test_even_odd(self, expect_output):
        """Classic mutual recursion: is_even and is_odd."""
        expect_output('''
formula is_even(n: int) -> bool
    if n == 0
        return true
    ~
    return is_odd(n - 1)
~

formula is_odd(n: int) -> bool
    if n == 0
        return false
    ~
    return is_even(n - 1)
~

func main() -> int
    print(is_even(0))
    print(is_odd(0))
    print(is_even(10))
    print(is_odd(10))
    print(is_even(7))
    print(is_odd(7))
    return 0
~
''', "true\nfalse\ntrue\nfalse\nfalse\ntrue\n")

    def test_forward_reference(self, expect_output):
        """Formula A calls formula B defined later in the file."""
        expect_output('''
formula double_then_add(n: int) -> int
    return add_one(n * 2)
~

formula add_one(n: int) -> int
    return n + 1
~

func main() -> int
    print(double_then_add(5))
    print(double_then_add(10))
    return 0
~
''', "11\n21\n")

    def test_three_way_mutual_recursion(self, expect_output):
        """Three-way mutual recursion: A calls B, B calls C, C calls A.

        Implements mod 3 state machine: when subtracting 1, the remainder
        cycles backwards: 0 -> 2 -> 1 -> 0
        """
        expect_output('''
formula mod3_is_0(n: int) -> bool
    if n == 0
        return true
    ~
    if n < 0
        return false
    ~
    return mod3_is_2(n - 1)
~

formula mod3_is_1(n: int) -> bool
    if n == 0
        return false
    ~
    if n < 0
        return false
    ~
    return mod3_is_0(n - 1)
~

formula mod3_is_2(n: int) -> bool
    if n == 0
        return false
    ~
    if n < 0
        return false
    ~
    return mod3_is_1(n - 1)
~

func main() -> int
    print(mod3_is_0(9))
    print(mod3_is_1(10))
    print(mod3_is_2(11))
    print(mod3_is_0(7))
    print(mod3_is_1(7))
    print(mod3_is_2(7))
    return 0
~
''', "true\ntrue\ntrue\nfalse\ntrue\nfalse\n")

    def test_ping_pong(self, expect_output):
        """Mutual recursion that counts down using two formulas."""
        expect_output('''
formula ping(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    return pong(n - 1, acc + 1)
~

formula pong(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    return ping(n - 1, acc + 2)
~

func main() -> int
    print(ping(10, 0))
    print(pong(10, 0))
    return 0
~
''', "15\n15\n")


class TestFormulaHigherOrder:
    """Tests for higher-order formulas."""

    def test_apply_twice(self, expect_output):
        """Higher-order formula that applies a function twice."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

formula apply_twice(f: formula(int) -> int, x: int) -> int
    return f(f(x))
~

func main() -> int
    print(apply_twice(double, 3))
    print(apply_twice(double, 5))
    return 0
~
''', "12\n20\n")

    def test_compose(self, expect_output):
        """Higher-order formula that composes two functions."""
        expect_output('''
formula add_one(x: int) -> int
    return x + 1
~

formula double(x: int) -> int
    return x * 2
~

formula compose_and_apply(f: formula(int) -> int, g: formula(int) -> int, x: int) -> int
    return f(g(x))
~

func main() -> int
    print(compose_and_apply(add_one, double, 5))
    print(compose_and_apply(double, add_one, 5))
    return 0
~
''', "11\n12\n")

    def test_recursive_map(self, expect_output):
        """Recursive map implementation using higher-order formula."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

formula map_list(f: formula(int) -> int, xs: List<int>, idx: int, result: List<int>) -> List<int>
    if idx >= xs.len()
        return result
    ~
    return map_list(f, xs, idx + 1, result.append(f(xs.get(idx))))
~

func main() -> int
    nums = [1, 2, 3, 4, 5]
    doubled = map_list(double, nums, 0, [])
    for n in doubled
        print(n)
    ~
    return 0
~
''', "2\n4\n6\n8\n10\n")

    def test_recursive_filter(self, expect_output):
        """Recursive filter implementation."""
        expect_output('''
formula is_positive(x: int) -> bool
    return x > 0
~

formula filter_list(pred: formula(int) -> bool, xs: List<int>, idx: int, result: List<int>) -> List<int>
    if idx >= xs.len()
        return result
    ~
    const val = xs.get(idx)
    if pred(val)
        return filter_list(pred, xs, idx + 1, result.append(val))
    ~
    return filter_list(pred, xs, idx + 1, result)
~

func main() -> int
    nums = [-2, -1, 0, 1, 2, 3]
    positives = filter_list(is_positive, nums, 0, [])
    for n in positives
        print(n)
    ~
    return 0
~
''', "1\n2\n3\n")

    def test_recursive_fold(self, expect_output):
        """Recursive fold/reduce implementation."""
        expect_output('''
formula add(a: int, b: int) -> int
    return a + b
~

formula mul(a: int, b: int) -> int
    return a * b
~

formula fold_list(f: formula(int, int) -> int, xs: List<int>, idx: int, acc: int) -> int
    if idx >= xs.len()
        return acc
    ~
    return fold_list(f, xs, idx + 1, f(acc, xs.get(idx)))
~

func main() -> int
    nums = [1, 2, 3, 4, 5]
    sum_result = fold_list(add, nums, 0, 0)
    product_result = fold_list(mul, nums, 0, 1)
    print(sum_result)
    print(product_result)
    return 0
~
''', "15\n120\n")


class TestFormulaPurityEnforcement:
    """Tests that formulas enforce purity constraints."""

    def test_formula_cannot_call_func(self, expect_compile_error):
        """Formula cannot call a func (impure function)."""
        expect_compile_error('''
func impure(x: int) -> int
    print(x)
    return x
~

formula bad(x: int) -> int
    return impure(x)
~

func main() -> int
    print(bad(5))
    return 0
~
''', "cannot call")

    def test_formula_cannot_call_task(self, expect_compile_error):
        """Formula cannot call a task."""
        expect_compile_error('''
task async_work(x: int) -> int
    return x * 2
~

formula bad(x: int) -> int
    return async_work(x)
~

func main() -> int
    print(bad(5))
    return 0
~
''', "cannot call")

    def test_formula_can_call_formula(self, expect_output):
        """Formula CAN call another formula (both are pure)."""
        expect_output('''
formula helper(x: int) -> int
    return x * 2
~

formula main_formula(x: int) -> int
    return helper(x) + 1
~

func main() -> int
    print(main_formula(5))
    return 0
~
''', "11\n")

    def test_func_can_call_formula(self, expect_output):
        """Func CAN call a formula."""
        expect_output('''
formula pure_double(x: int) -> int
    return x * 2
~

func main() -> int
    print(pure_double(21))
    return 0
~
''', "42\n")


class TestFormulaEdgeCases:
    """Edge cases and boundary conditions for formula recursion."""

    def test_deep_recursion_moderate(self, expect_output):
        """Test moderate recursion depth (1000 calls)."""
        expect_output('''
formula count_down(n: int) -> int
    if n <= 0
        return 0
    ~
    return 1 + count_down(n - 1)
~

func main() -> int
    print(count_down(1000))
    return 0
~
''', "1000\n")

    def test_formula_with_multiple_params(self, expect_output):
        """Recursive formula with multiple parameters."""
        expect_output('''
formula ackermann_small(m: int, n: int) -> int
    if m == 0
        return n + 1
    ~
    if n == 0
        return ackermann_small(m - 1, 1)
    ~
    return ackermann_small(m - 1, ackermann_small(m, n - 1))
~

func main() -> int
    print(ackermann_small(0, 0))
    print(ackermann_small(1, 1))
    print(ackermann_small(2, 2))
    print(ackermann_small(3, 3))
    return 0
~
''', "1\n3\n7\n61\n")

    def test_formula_returning_bool_recursion(self, expect_output):
        """Recursive formula returning bool."""
        expect_output('''
formula is_prime_helper(n: int, divisor: int) -> bool
    if divisor * divisor > n
        return true
    ~
    if n % divisor == 0
        return false
    ~
    return is_prime_helper(n, divisor + 1)
~

formula is_prime(n: int) -> bool
    if n < 2
        return false
    ~
    return is_prime_helper(n, 2)
~

func main() -> int
    print(is_prime(2))
    print(is_prime(17))
    print(is_prime(18))
    print(is_prime(97))
    return 0
~
''', "true\ntrue\nfalse\ntrue\n")

    def test_formula_with_list_recursion(self, expect_output):
        """Recursive formula operating on lists."""
        expect_output('''
formula list_sum(xs: List<int>, idx: int) -> int
    if idx >= xs.len()
        return 0
    ~
    return xs.get(idx) + list_sum(xs, idx + 1)
~

func main() -> int
    print(list_sum([1, 2, 3, 4, 5], 0))
    print(list_sum([], 0))
    print(list_sum([10], 0))
    return 0
~
''', "15\n0\n10\n")

    def test_nested_formula_calls(self, expect_output):
        """Deeply nested formula calls (not recursive, but chained).

        f1(5) = 5 + 1 = 6
        f2(5) = f1(5) * 2 = 6 * 2 = 12
        f3(5) = f2(5) + f1(5) = 12 + 6 = 18
        f4(5) = f3(5) * f2(5) = 18 * 12 = 216
        """
        expect_output('''
formula f1(x: int) -> int
    return x + 1
~

formula f2(x: int) -> int
    return f1(x) * 2
~

formula f3(x: int) -> int
    return f2(x) + f1(x)
~

formula f4(x: int) -> int
    return f3(x) * f2(x)
~

func main() -> int
    print(f4(5))
    return 0
~
''', "216\n")


class TestTailRecursion:
    """Tests for tail-recursive formulas (preparation for TCO)."""

    def test_tail_recursive_sum(self, expect_output):
        """Tail-recursive sum with accumulator."""
        expect_output('''
formula sum_tail(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    return sum_tail(n - 1, acc + n)
~

func main() -> int
    print(sum_tail(10, 0))
    print(sum_tail(100, 0))
    return 0
~
''', "55\n5050\n")

    def test_tail_recursive_factorial(self, expect_output):
        """Tail-recursive factorial with accumulator."""
        expect_output('''
formula fact_tail(n: int, acc: int) -> int
    if n <= 1
        return acc
    ~
    return fact_tail(n - 1, acc * n)
~

func main() -> int
    print(fact_tail(5, 1))
    print(fact_tail(10, 1))
    return 0
~
''', "120\n3628800\n")

    def test_tail_recursive_reverse(self, expect_output):
        """Tail-recursive list reversal."""
        expect_output('''
formula reverse_tail(xs: List<int>, idx: int, acc: List<int>) -> List<int>
    if idx < 0
        return acc
    ~
    return reverse_tail(xs, idx - 1, acc.append(xs.get(idx)))
~

func main() -> int
    nums = [1, 2, 3, 4, 5]
    reversed_nums = reverse_tail(nums, nums.len() - 1, [])
    for n in reversed_nums
        print(n)
    ~
    return 0
~
''', "5\n4\n3\n2\n1\n")

    def test_tail_recursion_deep(self, expect_output):
        """Deep tail recursion (100k depth) - works due to large default stack."""
        expect_output('''
formula sum_tail(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    return sum_tail(n - 1, acc + n)
~

func main() -> int
    print(sum_tail(100000, 0))
    return 0
~
''', "5000050000\n")
