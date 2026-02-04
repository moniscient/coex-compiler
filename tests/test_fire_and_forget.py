"""
Tests for fire-and-forget task semantics (BUG-012).

This module tests the following semantics:
- Bare task calls (no assignment) spawn immediately and join at function exit
- := assignment blocks until the task completes
- = assignment with task calls produces a compile error
"""

import pytest


class TestBareTaskCalls:
    """Tests for bare task calls (fire-and-forget)."""

    def test_bare_thread_executes(self, expect_output):
        """Bare thread call spawns and joins at function exit."""
        expect_output('''
thread work() -> int
    print(42)
    return 0
~

func main() -> int
    work()  # Fire-and-forget - joins at function exit
    return 0
~
''', "42\n")

    def test_bare_thread_multiple(self, compile_coex):
        """Multiple bare thread calls all join at function exit."""
        result = compile_coex('''
thread work(n: int) -> int
    print(n)
    return n
~

func main() -> int
    work(1)
    work(2)
    work(3)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        # Order may vary due to concurrency, but all values must appear
        output = result.run_output
        assert "1" in output
        assert "2" in output
        assert "3" in output

    def test_bare_task_executes(self, expect_output):
        """Bare task call executes."""
        expect_output('''
task work() -> int
    print(99)
    return 0
~

func main() -> int
    work()  # Bare call
    return 0
~
''', "99\n")

    def test_bare_call_with_args(self, expect_output):
        """Bare call with arguments works."""
        expect_output('''
thread compute(x: int, y: int) -> int
    print(x + y)
    return x + y
~

func main() -> int
    compute(10, 32)
    return 0
~
''', "42\n")


class TestBlockingAssignment:
    """Tests for := blocking assignment."""

    def test_copy_assign_blocks(self, expect_output):
        """Thread call with := blocks until complete."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    result := compute(21)
    print(result)
    return 0
~
''', "42\n")

    def test_copy_assign_order(self, expect_output):
        """Multiple := assignments execute in order."""
        expect_output('''
thread step(n: int) -> int
    print(n)
    return n
~

func main() -> int
    a := step(1)
    b := step(2)
    c := step(3)
    print(a + b + c)
    return 0
~
''', "1\n2\n3\n6\n")


class TestEqualsAssignmentError:
    """Tests that = assignment with task calls produces compile error."""

    def test_equals_thread_error(self, compile_coex):
        """= assignment with thread call is a compile error."""
        result = compile_coex('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    result = compute(21)
    print(result)
    return 0
~
''')
        assert not result.compile_success
        assert "Cannot assign thread result with '=' operator" in result.compile_output

    def test_equals_task_error(self, compile_coex):
        """= assignment with task call is a compile error."""
        result = compile_coex('''
task compute(x: int) -> int
    return x * 2
~

func main() -> int
    result = compute(21)
    print(result)
    return 0
~
''')
        assert not result.compile_success
        assert "Cannot assign task result with '=' operator" in result.compile_output


class TestMixedSemantics:
    """Tests for mixing bare calls and := assignments."""

    def test_bare_then_blocking(self, compile_coex):
        """Bare call followed by blocking call."""
        result = compile_coex('''
thread background() -> int
    print(1)
    return 1
~

thread blocking() -> int
    print(2)
    return 2
~

func main() -> int
    background()  # Fire-and-forget
    x := blocking()  # Blocks
    print(x)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        # Due to concurrency, 1 and 2 may print in any order
        # But we need two 2s (one from blocking print, one from result print)
        output = result.run_output
        assert "1" in output
        assert output.count("2") == 2

    def test_multiple_bare_calls(self, compile_coex):
        """Multiple bare calls all complete before function returns."""
        result = compile_coex('''
thread work(id: int) -> int
    print(id)
    return id
~

func main() -> int
    work(1)
    work(2)
    work(3)
    print(0)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        # Due to concurrency, output order is non-deterministic
        # But all 4 values must be present
        output = result.run_output
        assert "1" in output
        assert "2" in output
        assert "3" in output
        assert "0" in output


class TestForFirstMostUnchanged:
    """Tests that for/first/most constructs still work correctly."""

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_for_collection_unchanged(self, expect_output):
        """for-collection with tasks still works."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3]
    results = for x in items double(x) ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "12\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_first_unchanged(self, compile_coex):
        """first-collection with tasks still works.

        Note: first returns whichever task completes first, which is
        non-deterministic. We just verify the result is one of the valid values.
        """
        result = compile_coex('''
thread identity(x: int) -> int
    return x
~

func main() -> int
    items = [42, 43, 44]
    result = first x in items identity(x) ~
    print(result)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.run_output}"
        # first returns whichever task completes first - any of these is valid
        assert result.run_output in ("42\n", "43\n", "44\n"), \
            f"Expected one of 42, 43, 44 but got: {result.run_output!r}"
