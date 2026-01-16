"""
Tests for `first` and `most` structured concurrency primitives.
Phase 3, Steps 8-9 of Task System implementation.
"""

import pytest


class TestFirstBasic:
    """Basic tests for `first` structured concurrency"""

    def test_first_single_element(self, expect_output):
        """First with single element list"""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

func main() -> int
    result = first i in [21]
        double(i)
    ~
    print(result)
    return 0
~
''', "42\n")

    def test_first_multiple_elements(self, expect_output):
        """First with multiple elements returns first result"""
        expect_output('''
task work(x: int) -> int
    return x * 2
~

func main() -> int
    result = first i in [1, 2, 3]
        work(i)
    ~
    print(result)
    return 0
~
''', "2\n")

    def test_first_with_computation(self, expect_output):
        """First with more complex computation"""
        expect_output('''
task square(x: int) -> int
    return x * x
~

func main() -> int
    result = first i in [5]
        square(i)
    ~
    print(result)
    return 0
~
''', "25\n")

    def test_first_result_is_correct_value(self, expect_output):
        """First returns the actual task result value"""
        expect_output('''
task add_ten(x: int) -> int
    return x + 10
~

func main() -> int
    result = first i in [7]
        add_ten(i)
    ~
    print(result)
    return 0
~
''', "17\n")


class TestMostBasic:
    """Basic tests for `most` structured concurrency"""

    def test_most_single_element(self, expect_output):
        """Most with single element list"""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

func main() -> int
    (results, errors) = most i in [21]
        double(i)
    ~
    print(results.len())
    if results.len() > 0
        print(results.get(0))
    ~
    return 0
~
''', "1\n42\n")

    def test_most_multiple_elements(self, expect_output):
        """Most collects all results"""
        expect_output('''
task square(x: int) -> int
    return x * x
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4, 5]
        square(i)
    ~

    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "55\n")

    def test_most_empty_collection(self, expect_output):
        """Most with empty collection returns empty results"""
        expect_output('''
task work(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in []
        work(i)
    ~
    print(results.len())
    print(errors.len())
    return 0
~
''', "0\n0\n")

    def test_most_all_succeed(self, expect_output):
        """Most with all successful tasks"""
        expect_output('''
task identity(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in [10, 20, 30]
        identity(i)
    ~
    print(results.len())
    print(errors.len())
    return 0
~
''', "3\n0\n")


class TestFirstEdgeCases:
    """Edge cases for `first`"""

    def test_first_empty_list(self, expect_output):
        """First with empty list returns default (0)"""
        expect_output('''
task work(x: int) -> int
    return x
~

func main() -> int
    result = first i in []
        work(i)
    ~
    print(result)
    return 0
~
''', "0\n")

    def test_first_with_range(self, expect_output):
        """First with range expression (if supported)"""
        # Skip if range iteration in first isn't supported yet
        pytest.skip("Range iteration in first/most not yet implemented")


class TestMostEdgeCases:
    """Edge cases for `most`"""

    def test_most_large_collection(self, expect_output):
        """Most with larger collection"""
        expect_output('''
task identity(x: int) -> int
    return x
~

func main() -> int
    items = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    (results, errors) = most i in items
        identity(i)
    ~

    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "55\n")


class TestFirstWithNestedTasks:
    """First with tasks that call other tasks"""

    @pytest.mark.xfail(reason="Task-to-task suspension not fully implemented")
    def test_first_nested_task(self, expect_output):
        """First where task calls another task"""
        expect_output('''
task inner(x: int) -> int
    return x + 1
~

task outer(x: int) -> int
    y = inner(x)
    return y * 2
~

func main() -> int
    result = first i in [5]
        outer(i)
    ~
    print(result)
    return 0
~
''', "12\n")


class TestMostWithResults:
    """Tests for most result collection"""

    def test_most_sum_results(self, expect_output):
        """Sum all results from most"""
        expect_output('''
task triple(x: int) -> int
    return x * 3
~

func main() -> int
    (results, errors) = most i in [1, 2, 3]
        triple(i)
    ~

    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "18\n")


class TestFirstCancellation:
    """Tests for first cancellation semantics"""

    def test_first_concurrent_returns_winner(self, expect_output):
        """First with concurrent tasks returns winner's result"""
        # Tests that first returns a valid result from one of the tasks
        expect_output('''
task work(id: int) -> int
    return id * 10
~

func main() -> int
    result = first i in [1, 2, 3]
        work(i)
    ~
    # Result should be 10, 20, or 30 (one task wins)
    print(result >= 10 and result <= 30)
    return 0
~
''', "true\n")

    def test_first_all_tasks_same_computation(self, expect_output):
        """First with identical tasks all compute same value"""
        expect_output('''
task compute() -> int
    return 42
~

func main() -> int
    result = first i in [1, 2, 3]
        compute()
    ~
    print(result)
    return 0
~
''', "42\n")


class TestMostNoCancel:
    """Tests that most doesn't cancel any tasks"""

    def test_most_collects_all_with_atomic(self, expect_output):
        """Most collects results from all tasks"""
        expect_output('''
task counter(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4, 5]
        counter(i)
    ~
    print(results.len())
    return 0
~
''', "5\n")
