"""Tests for BUG-099: Task closure result storage uses handles, not raw pointers.

Verifies that when a task returns a reference type (string, list, map, etc.),
the result stored in the closure is a GC handle that survives compaction,
not a raw pointer that goes stale.
"""

import pytest


class TestTaskClosureHandleBasic:
    """Basic tests: task returns heap types and result is correct."""

    def test_task_returns_string_with_gc(self, expect_output):
        """Task returning a string survives an explicit GC cycle."""
        expect_output('''
task make_string(n: int) -> string
    return "result_" + String.from(n)
~

func main() -> int
    result := make_string(42)
    gc()
    print(result)
    return 0
~
''', "result_42\n")

    def test_task_returns_list_with_gc(self, expect_output):
        """Task returning a list survives an explicit GC cycle."""
        expect_output('''
task make_list(n: int) -> [int]
    result = [0]
    i = 1
    while i < n
        result = result.append(i)
        i = i + 1
    ~
    return result
~

func main() -> int
    result := make_list(5)
    gc()
    print(result.len())
    i = 0
    while i < result.len()
        print(result.get(i))
        i = i + 1
    ~
    return 0
~
''', "5\n0\n1\n2\n3\n4\n")

    def test_task_returns_long_string_with_gc(self, expect_output):
        """Task returning a concatenated string survives an explicit GC cycle."""
        expect_output('''
task make_long_string(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    result := make_long_string(50)
    gc()
    print(result.len())
    return 0
~
''', "50\n")


class TestTaskClosureHandleStress:
    """Stress tests: heavy GC pressure between task completion and result use."""

    def test_task_string_survives_multiple_gc_cycles(self, expect_output):
        """Task result string survives multiple GC cycles with allocation pressure."""
        expect_output('''
task make_greeting(name: string) -> string
    return "Hello, " + name + "!"
~

func main() -> int
    result := make_greeting("World")
    i = 0
    while i < 10
        gc()
        temp = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        i = i + 1
    ~
    print(result)
    return 0
~
''', "Hello, World!\n")

    def test_task_list_survives_heavy_allocation(self, expect_output):
        """Task result list survives heavy allocation pressure with GC."""
        expect_output('''
task build_list(size: int) -> [int]
    result = [0]
    i = 1
    while i < size
        result = result.append(i * i)
        i = i + 1
    ~
    return result
~

func main() -> int
    result := build_list(100)
    i = 0
    while i < 20
        gc()
        garbage = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        i = i + 1
    ~
    print(result.len())
    print(result.get(0))
    print(result.get(99))
    return 0
~
''', "100\n0\n9801\n")

    def test_multiple_task_results_survive_gc(self, expect_output):
        """Multiple sequential task results all survive GC pressure."""
        expect_output('''
task make_string(prefix: string, n: int) -> string
    return prefix + String.from(n)
~

func main() -> int
    a := make_string("alpha_", 1)
    gc()
    b := make_string("beta_", 2)
    gc()
    c := make_string("gamma_", 3)
    gc()
    print(a)
    print(b)
    print(c)
    return 0
~
''', "alpha_1\nbeta_2\ngamma_3\n")

    @pytest.mark.timeout(30)
    def test_task_string_stress_many_calls(self, expect_output):
        """Many sequential task calls returning strings under GC pressure."""
        expect_output('''
task make_label(i: int) -> string
    return "item_" + String.from(i)
~

func main() -> int
    count = 0
    i = 0
    while i < 200
        label := make_label(i)
        if label.len() > 0
            count = count + 1
        ~
        if i % 20 == 0
            gc()
        ~
        i = i + 1
    ~
    print(count)
    return 0
~
''', "200\n")


class TestForAssignTaskClosureHandles:
    """Test for-assign with tasks returning heap types."""

    def test_for_assign_task_returns_strings(self, expect_output):
        """for-assign collecting string results from tasks."""
        expect_output('''
task label(n: int) -> string
    return "item_" + String.from(n)
~

func main() -> int
    items = [10, 20, 30]
    results = for item in items label(item) ~
    gc()
    print(results.len())
    return 0
~
''', "3\n")

    def test_for_assign_task_returns_int(self, expect_output):
        """for-assign collecting int results (control test, was already working)."""
        expect_output('''
task square(n: int) -> int
    return n * n
~

func main() -> int
    items = [2, 3, 4, 5]
    results = for item in items square(item) ~
    print(results.len())
    return 0
~
''', "4\n")
