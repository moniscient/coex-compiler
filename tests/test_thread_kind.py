"""
Tests for the `thread` function kind (formerly `task`).

The `thread` keyword declares functions that run on OS threads via pthreads.
The `task` keyword is now reserved for the future coroutine system.
"""

import pytest


class TestThreadKeyword:
    """Tests for basic thread keyword functionality."""

    def test_thread_basic_return(self, expect_output):
        """Thread function returns a value with := blocking assignment."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    result := compute(5)
    print(result)
    return 0
~
''', "10\n")

    def test_thread_with_multiple_params(self, expect_output):
        """Thread function with multiple parameters."""
        expect_output('''
thread add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    result := add(10, 20)
    print(result)
    return 0
~
''', "30\n")

    def test_thread_can_call_formula(self, expect_output):
        """Thread can call formula (lighter kind)."""
        expect_output('''
formula double(x: int) -> int
    return x * 2
~

thread compute(x: int) -> int
    return double(x) + 1
~

func main() -> int
    result := compute(5)
    print(result)
    return 0
~
''', "11\n")

    def test_thread_can_call_thread(self, expect_output):
        """Thread can call other threads."""
        expect_output('''
thread inner(x: int) -> int
    return x + 1
~

thread outer(x: int) -> int
    inner_result := inner(x)
    return inner_result * 2
~

func main() -> int
    result := outer(5)
    print(result)
    return 0
~
''', "12\n")

    def test_func_can_call_thread(self, expect_output):
        """Func can call thread (heavier can call lighter)."""
        expect_output('''
thread compute(x: int) -> int
    return x * 3
~

func main() -> int
    result := compute(7)
    print(result)
    return 0
~
''', "21\n")


class TestThreadParallelExecution:
    """Tests for parallel thread execution with for/first/most."""

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_thread_parallel_for(self, expect_output):
        """Parallel for loop with threads."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3, 4, 5]
    results = for x in items double(x) ~
    sum = 0
    for r in results
        sum = sum + r
    ~
    print(sum)
    return 0
~
''', "30\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_thread_first(self, expect_output):
        """First pattern returns first result."""
        expect_output('''
thread identity(x: int) -> int
    return x
~

func main() -> int
    items = [42, 43, 44]
    result = first x in items identity(x) ~
    print(result)
    return 0
~
''', "42\n")


class TestTaskKeywordFunctionality:
    """Tests that the `task` keyword works as lightweight coroutines."""

    def test_task_basic_execution(self, expect_output):
        """Task function executes and returns value with := blocking assignment."""
        expect_output('''
task compute() -> int
    return 42
~

func main() -> int
    result := compute()
    print(result)
    return 0
~
''', "42\n")

    def test_task_with_params(self, expect_output):
        """Task function with parameters works correctly."""
        expect_output('''
task compute(x: int) -> int
    return x * 2
~

func main() -> int
    result := compute(21)
    print(result)
    return 0
~
''', "42\n")
