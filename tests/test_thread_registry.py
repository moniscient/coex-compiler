"""
Tests for thread registry infrastructure.

These tests verify that the thread registry is properly initialized
and the main thread is registered during GC initialization.
"""

import pytest


class TestThreadRegistry:
    """Test thread registry infrastructure."""

    def test_gc_runs_with_thread_registry(self, expect_output):
        """Test that GC still works with thread registry infrastructure."""
        expect_output('''
func main() -> int
    x = [1, 2, 3, 4, 5]
    gc()
    print(x.len())
    return 0
~
''', '5\n')

    def test_gc_collect_multiple_times_with_registry(self, expect_output):
        """Test multiple GC cycles work with thread registry."""
        expect_output('''
func main() -> int
    i = 0
    while i < 5
        x = [i, i+1, i+2]
        gc()
        i = i + 1
    ~
    print(i)
    return 0
~
''', '5\n')

    def test_gc_dump_stats_with_registry(self, compile_coex):
        """Test gc_dump_stats works with thread registry initialized."""
        code = '''
func main() -> int
    x = [1, 2, 3]
    gc_dump_stats()
    return 0
~
'''
        # gc_dump_stats outputs statistics - we just verify it runs without error
        result = compile_coex(code)
        assert result.compile_success
        assert result.run_success
        assert '[GC:STATS]' in result.run_output

    def test_gc_validate_heap_with_registry(self, expect_output):
        """Test gc_validate_heap returns 0 (valid) with thread registry."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    y = {1: "one", 2: "two"}
    result = gc_validate_heap()
    print(result)
    return 0
~
''', '0\n')

    def test_nested_functions_with_registry(self, expect_output):
        """Test nested function calls work correctly with thread registry."""
        expect_output('''
func outer() -> int
    x = [1, 2, 3]
    return inner(x)
~

func inner(list: [int]) -> int
    gc()
    return list.len()
~

func main() -> int
    result = outer()
    print(result)
    return 0
~
''', '3\n')

    def test_recursive_function_with_registry(self, expect_output):
        """Test recursive functions work with thread registry."""
        expect_output('''
func sum_list(list: [int], idx: int, acc: int) -> int
    if idx >= list.len()
        return acc
    ~
    return sum_list(list, idx + 1, acc + list.get(idx))
~

func main() -> int
    x = [1, 2, 3, 4, 5]
    gc()
    result = sum_list(x, 0, 0)
    print(result)
    return 0
~
''', '15\n')

    def test_map_operations_with_registry(self, expect_output):
        """Test map operations work with thread registry."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    gc()
    total = m.get(1) + m.get(2) + m.get(3)
    print(total)
    return 0
~
''', '60\n')

    def test_string_operations_with_registry(self, expect_output):
        """Test string operations work with thread registry."""
        expect_output('''
func main() -> int
    s = "hello world"
    gc()
    print(s.len())
    return 0
~
''', '11\n')


class TestThreadRegistryGCCycles:
    """Test GC cycles with thread registry in place."""

    def test_gc_preserves_roots_with_registry(self, expect_output):
        """Test that GC preserves shadow stack roots correctly."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = [4, 5, 6]
    c = [7, 8, 9]
    gc()
    total = a.len() + b.len() + c.len()
    print(total)
    return 0
~
''', '9\n')

    def test_gc_in_loop_with_registry(self, expect_output):
        """Test GC in loop works with thread registry."""
        expect_output('''
func main() -> int
    count = 0
    i = 0
    while i < 10
        temp = [i, i+1, i+2]
        gc()
        count = count + 1
        i = i + 1
    ~
    print(count)
    return 0
~
''', '10\n')

    def test_many_allocations_with_registry(self, expect_output):
        """Test many allocations work with thread registry."""
        expect_output('''
func main() -> int
    total = 0
    i = 0
    while i < 100
        x = [i]
        total = total + x.get(0)
        i = i + 1
    ~
    gc()
    print(total)
    return 0
~
''', '4950\n')  # Sum of 0..99
