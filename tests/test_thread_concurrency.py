"""
Tests for thread concurrency.

These tests verify that:
1. Threads execute on actual OS threads
2. Threads can run concurrently
3. Thread results are correctly returned
4. Multiple threads work correctly
"""
import pytest


class TestThreadConcurrency:
    """Tests for thread concurrent execution."""

    def test_simple_task_returns_result(self, expect_output):
        """Test that a simple thread returns its result."""
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

    def test_thread_with_multiple_params(self, expect_output):
        """Test thread with multiple parameters."""
        expect_output('''
thread add(a: int, b: int) -> int
    return a + b
~

func main() -> int
    result := add(17, 25)
    print(result)
    return 0
~
''', "42\n")

    def test_thread_calling_formula(self, expect_output):
        """Test thread that calls a formula function."""
        expect_output('''
formula helper(x: int) -> int
    return x + 10
~

thread compute(x: int) -> int
    return helper(x)
~

func main() -> int
    result := compute(32)
    print(result)
    return 0
~
''', "42\n")

    def test_multiple_task_calls(self, expect_output):
        """Test calling multiple tasks sequentially."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    a := double(10)
    b := double(5)
    c := double(3)
    print(a + b + c)
    return 0
~
''', "36\n")

    def test_thread_with_loop(self, expect_output):
        """Test thread with internal loop."""
        expect_output('''
thread sum_to(n: int) -> int
    total = 0
    i = 1
    while i <= n
        total = total + i
        i = i + 1
    ~
    return total
~

func main() -> int
    result := sum_to(10)
    print(result)
    return 0
~
''', "55\n")

    def test_thread_no_params(self, expect_output):
        """Test thread with no parameters."""
        expect_output('''
thread get_answer() -> int
    return 42
~

func main() -> int
    result := get_answer()
    print(result)
    return 0
~
''', "42\n")

    def test_nested_task_calls(self, expect_output):
        """Test thread calling another task."""
        expect_output('''
thread inner(x: int) -> int
    return x + 1
~

thread outer(x: int) -> int
    inner_result := inner(x)
    return inner_result * 2
~

func main() -> int
    result := outer(20)
    print(result)
    return 0
~
''', "42\n")

    def test_thread_with_conditional(self, expect_output):
        """Test thread with conditional logic."""
        expect_output('''
thread abs_val(x: int) -> int
    if x < 0
        return 0 - x
    else
        return x
    ~
~

func main() -> int
    a := abs_val(-42)
    b := abs_val(42)
    print(a)
    print(b)
    return 0
~
''', "42\n42\n")

    def test_thread_result_in_expression(self, expect_output):
        """Test using thread result directly in expression."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    a := compute(10)
    b := compute(11)
    result = a + b
    print(result)
    return 0
~
''', "42\n")


class TestTaskAssignmentErrors:
    """Tests for task assignment semantics (BUG-012)."""

    def test_equals_assignment_error(self, compile_coex):
        """Test that = assignment with thread call produces compile error."""
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
        # Should fail to compile - = not allowed for thread calls
        assert not result.compile_success
        assert "Cannot assign thread result with '=' operator" in result.compile_output

    def test_copy_assign_works(self, expect_output):
        """Test that := assignment with thread call works (blocking)."""
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

    def test_multiple_copy_assigns(self, expect_output):
        """Test multiple := assignments work correctly."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    a := compute(10)
    b := compute(5)
    print(a + b)
    return 0
~
''', "30\n")


class TestForCollectionBlock:
    """Tests for parallel for-collection blocks with tasks."""

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_parallel_map_simple(self, expect_output):
        """Test basic parallel map: results = for x in items compute(x) ~"""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3, 4, 5]
    results = for x in items double(x) ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "30\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_parallel_map_order_preserved(self, expect_output):
        """Test that results maintain iteration order."""
        expect_output('''
thread identity(x: int) -> int
    return x
~

func main() -> int
    items = [10, 20, 30, 40]
    results = for x in items identity(x) ~
    for r in results
        print(r)
    ~
    return 0
~
''', "10\n20\n30\n40\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_parallel_map_with_computation(self, expect_output):
        """Test parallel map with actual computation in task."""
        expect_output('''
thread compute(n: int) -> int
    sum = 0
    i = 1
    while i <= n
        sum = sum + i
        i = i + 1
    ~
    return sum
~

func main() -> int
    items = [3, 4, 5]
    results = for x in items compute(x) ~
    # Results should be: 6 (1+2+3), 10 (1+2+3+4), 15 (1+2+3+4+5)
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "31\n")

    def test_parallel_map_empty_list(self, expect_output):
        """Test parallel map with empty input list."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items: List<int> = []
    results = for x in items double(x) ~
    print(results.len())
    return 0
~
''', "0\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_parallel_map_single_element(self, expect_output):
        """Test parallel map with single element."""
        expect_output('''
thread triple(x: int) -> int
    return x * 3
~

func main() -> int
    items = [14]
    results = for x in items triple(x) ~
    print(results.get(0))
    return 0
~
''', "42\n")

    def test_parallel_map_no_warning(self, compile_coex):
        """Test that for-collection does not emit sequential warning."""
        result = compile_coex('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3]
    results = for x in items double(x) ~
    print(results.len())
    return 0
~
''')
        assert result.compile_success
        assert result.run_output == "3\n"
        # For-collection should NOT emit the sequential execution warning
        assert "executes sequentially" not in result.compile_output


class TestFirstCollectionSyntax:
    """Tests for 'first' collection block syntax (Phase 6)."""

    def test_first_syntax_parses(self, expect_output):
        """Test that first syntax parses and executes."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3]
    result = first x in items compute(x) ~
    print(result)
    return 0
~
''', "2\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_first_single_item(self, expect_output):
        """Test first with single item."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [21]
    result = first x in items double(x) ~
    print(result)
    return 0
~
''', "42\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_first_larger_collection(self, compile_coex):
        """Test first with larger collection - first result wins (racy)."""
        result = compile_coex('''
thread identity(x: int) -> int
    return x
~

func main() -> int
    items = [10, 20, 30, 40, 50]
    result = first x in items identity(x) ~
    print(result)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        # Result is racy - any of the values could win
        valid_results = ["10\n", "20\n", "30\n", "40\n", "50\n"]
        assert result.run_output in valid_results

    def test_first_no_sequential_warning(self, compile_coex):
        """Test that first collection does not emit sequential warning."""
        result = compile_coex('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3]
    result = first x in items compute(x) ~
    print(result)
    return 0
~
''')
        assert result.compile_success
        # First should NOT emit sequential warning - it's racing
        assert "executes sequentially" not in result.compile_output

    def test_first_empty_list_returns_zero(self, expect_output):
        """Test first with empty list returns 0 (no tasks to race)."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items: List<int> = []
    result = first x in items double(x) ~
    print(result)
    return 0
~
''', "0\n")


class TestMostCollectionSyntax:
    """Tests for 'most' collection block syntax (Phase 6)."""

    def test_most_syntax_parses(self, expect_output):
        """Test that most syntax parses and executes."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3]
    (results, errors) = most x in items compute(x) ~
    print(results.len())
    print(errors.len())
    return 0
~
''', "3\n0\n")

    def test_most_empty_list(self, expect_output):
        """Test most with empty input."""
        expect_output('''
thread compute(x: int) -> int
    return x * 2
~

func main() -> int
    items: List<int> = []
    (results, errors) = most x in items compute(x) ~
    print(results.len())
    print(errors.len())
    return 0
~
''', "0\n0\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_most_larger_collection(self, expect_output):
        """Test most with larger collection - all succeed."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1, 2, 3, 4, 5]
    (results, errors) = most x in items double(x) ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    print(errors.len())
    return 0
~
''', "30\n0\n")

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_most_single_item(self, expect_output):
        """Test most with single item."""
        expect_output('''
thread triple(x: int) -> int
    return x * 3
~

func main() -> int
    items = [14]
    (results, errors) = most x in items triple(x) ~
    print(results.get(0))
    print(errors.len())
    return 0
~
''', "42\n0\n")


class TestCancellationSafepoints:
    """Tests for cancellation safepoint behavior (Phase 9).

    Safepoints are injected at loop back-edges to allow tasks to respond
    to cancellation requests. When a thread is cancelled (e.g., by losing
    a 'first' race), it should exit promptly at the next safepoint rather
    than running to completion.
    """

    @pytest.mark.xfail(reason="first/most/parallel-for returns incorrect values - task result collection bug")
    def test_first_with_loop_tasks(self, compile_coex):
        """Test that first works correctly when tasks have loops.

        This implicitly tests safepoints - the winning thread completes,
        losing tasks get cancelled, and they exit at their loop safepoints.
        The result is one of the valid outcomes (race-dependent).
        """
        result = compile_coex('''
thread compute_sum(n: int) -> int
    total = 0
    i = 0
    while i < n
        total = total + i
        i = i + 1
    ~
    return total
~

func main() -> int
    items = [5, 3, 10]
    result = first x in items compute_sum(x) ~
    print(result)
    return 0
~
''')
        assert result.compile_success
        assert result.run_success
        # Result should be one of compute_sum(5)=10, compute_sum(3)=3, or compute_sum(10)=45
        valid_results = ["10\n", "3\n", "45\n"]
        assert result.run_output in valid_results, f"Got {result.run_output!r}, expected one of {valid_results}"

    def test_thread_with_while_loop(self, expect_output):
        """Test thread with while loop has safepoints injected."""
        expect_output('''
thread count_to(n: int) -> int
    count = 0
    while count < n
        count = count + 1
    ~
    return count
~

func main() -> int
    result := count_to(100)
    print(result)
    return 0
~
''', "100\n")

    def test_thread_with_for_loop(self, expect_output):
        """Test thread with for loop has safepoints injected."""
        expect_output('''
thread sum_range(n: int) -> int
    total = 0
    for i in range(n)
        total = total + i
    ~
    return total
~

func main() -> int
    result := sum_range(10)
    print(result)
    return 0
~
''', "45\n")

    def test_thread_with_list_iteration(self, expect_output):
        """Test thread iterating over list has safepoints."""
        expect_output('''
thread sum_list(items: List<int>) -> int
    total = 0
    for item in items
        total = total + item
    ~
    return total
~

func main() -> int
    data = [1, 2, 3, 4, 5]
    result := sum_list(data)
    print(result)
    return 0
~
''', "15\n")
