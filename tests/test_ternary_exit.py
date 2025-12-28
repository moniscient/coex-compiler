"""
Tests for ternary exit variant (!) and Result-to-bool conversion.

The ternary exit variant uses ! instead of ; for the false branch.
When the condition is false, the else expression is returned from the function
instead of being used as the ternary result.

Result<T, E> implicitly converts to bool: true if Ok, false if Err.
"""

import pytest


class TestTernaryExit:
    """Tests for the ternary exit variant (!)."""

    def test_ternary_exit_takes_true_branch(self, expect_output):
        """When condition is true, the then expression is used."""
        expect_output('''
func test_exit(x: int) -> int
    result = x > 0 ? x ! -1
    return result
~

func main() -> int
    print(test_exit(42))
    return 0
~
''', "42\n")

    def test_ternary_exit_returns_on_false(self, expect_output):
        """When condition is false, the else expression is returned from function."""
        expect_output('''
func test_exit(x: int) -> int
    result = x > 0 ? x ! -1
    print(result)
    return result
~

func main() -> int
    r = test_exit(-5)
    print(r)
    return 0
~
''', "-1\n")

    def test_ternary_exit_skips_subsequent_code(self, expect_output):
        """Exit variant returns immediately, skipping code after the ternary."""
        expect_output('''
func early_return(x: int) -> int
    validated = x >= 0 ? x ! -999
    print(validated)  # This should only print if x >= 0
    return validated + 1
~

func main() -> int
    print(early_return(10))
    print(early_return(-5))
    return 0
~
''', "10\n11\n-999\n")

    def test_ternary_exit_with_bool_condition(self, expect_output):
        """Exit variant works with boolean conditions."""
        expect_output('''
func validate(ok: bool) -> int
    value = ok ? 100 ! 0
    return value
~

func main() -> int
    print(validate(true))
    print(validate(false))
    return 0
~
''', "100\n0\n")


class TestTernaryContinuation:
    """Tests to ensure ; variant (continuation) still works."""

    def test_ternary_continuation_true(self, expect_output):
        """Continuation variant returns then_expr when true."""
        expect_output('''
func main() -> int
    x = 5
    result = x > 0 ? 1 ; -1
    print(result)
    return 0
~
''', "1\n")

    def test_ternary_continuation_false(self, expect_output):
        """Continuation variant returns else_expr when false."""
        expect_output('''
func main() -> int
    x = -5
    result = x > 0 ? 1 ; -1
    print(result)
    return 0
~
''', "-1\n")


class TestResultToBool:
    """Tests for Result<T, E> to bool implicit conversion."""

    def test_result_ok_in_if_is_true(self, expect_output):
        """Result.ok() is truthy in if statements."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.ok(42)
    if r
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_result_err_in_if_is_false(self, expect_output):
        """Result.err() is falsy in if statements."""
        expect_output('''
func main() -> int
    r: Result<int, string> = Result.err("oops")
    if r
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")

    def test_result_in_ternary_condition(self, expect_output):
        """Result can be used directly as ternary condition."""
        expect_output('''
func main() -> int
    ok: Result<int, string> = Result.ok(42)
    err: Result<int, string> = Result.err("fail")

    a = ok ? 1 ; 0
    b = err ? 1 ; 0

    print(a)
    print(b)
    return 0
~
''', "1\n0\n")

    def test_result_in_boolean_and(self, expect_output):
        """Result can be used in 'and' expressions."""
        expect_output('''
func main() -> int
    ok: Result<int, string> = Result.ok(42)
    err: Result<int, string> = Result.err("fail")

    if ok and true
        print(1)
    else
        print(0)
    ~

    if err and true
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n0\n")

    def test_result_in_boolean_or(self, expect_output):
        """Result can be used in 'or' expressions."""
        expect_output('''
func main() -> int
    ok: Result<int, string> = Result.ok(42)
    err: Result<int, string> = Result.err("fail")

    if err or true
        print(1)
    else
        print(0)
    ~

    if err or false
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n0\n")

    def test_result_with_not(self, expect_output):
        """Result can be negated with 'not'."""
        expect_output('''
func main() -> int
    ok: Result<int, string> = Result.ok(42)
    err: Result<int, string> = Result.err("fail")

    if not ok
        print(1)
    else
        print(0)
    ~

    if not err
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n1\n")


class TestResultWithTernaryExit:
    """Tests combining Result type with ternary exit variant."""

    def test_result_exit_on_error(self, expect_output):
        """Return early when Result is Err."""
        expect_output('''
func try_get(succeed: bool) -> Result<int, string>
    if succeed
        return Result.ok(42)
    ~
    return Result.err("failed")
~

func process(succeed: bool) -> int
    r: Result<int, string> = try_get(succeed)
    value = r ? r.unwrap() ! -1
    return value + 10
~

func main() -> int
    print(process(true))
    print(process(false))
    return 0
~
''', "52\n-1\n")

    def test_chained_result_exits(self, expect_output):
        """Multiple exit ternaries for error propagation pattern."""
        expect_output('''
func step1(ok: bool) -> Result<int, string>
    if ok
        return Result.ok(10)
    ~
    return Result.err("step1 failed")
~

func step2(x: int) -> Result<int, string>
    if x > 0
        return Result.ok(x * 2)
    ~
    return Result.err("step2 failed")
~

func pipeline(start_ok: bool) -> int
    r1: Result<int, string> = step1(start_ok)
    v1 = r1 ? r1.unwrap() ! -1

    r2: Result<int, string> = step2(v1)
    v2 = r2 ? r2.unwrap() ! -2

    return v2
~

func main() -> int
    print(pipeline(true))
    print(pipeline(false))
    return 0
~
''', "20\n-1\n")


class TestTernaryEdgeCases:
    """Edge cases for ternary expressions."""

    def test_nested_ternary_with_exit(self, expect_output):
        """Nested ternary with exit in inner expression."""
        expect_output('''
func outer(x: int) -> int
    # outer is continuation, inner is exit
    result = x > 0 ? (x > 10 ? x ! 5) ; 0
    return result
~

func main() -> int
    print(outer(20))  # > 10, returns 20
    print(outer(5))   # > 0 but <= 10, exits with 5
    print(outer(-1))  # <= 0, returns 0
    return 0
~
''', "20\n5\n0\n")

    def test_exit_ternary_in_expression(self, expect_output):
        """Exit ternary can be used in larger expressions."""
        expect_output('''
func get_or_exit(x: int) -> int
    val = x >= 0 ? x ! -1
    return val * 2
~

func main() -> int
    print(get_or_exit(5))
    print(get_or_exit(-3))
    return 0
~
''', "10\n-1\n")
