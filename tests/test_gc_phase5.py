"""
Tests for Phase 5: Thread Registry (Stub)

These tests verify the thread registry infrastructure:
- Main thread is registered at GC init
- Thread registry is accessible
- GC continues to work correctly with thread registry
"""

import pytest


class TestThreadRegistryBasics:
    """Basic tests to verify thread registry doesn't break GC"""

    def test_gc_works_with_thread_registry(self, expect_output):
        """Test that GC still works with thread registry in place"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    print(x.len())
    return 0
~
''', "3\n")

    def test_multiple_gc_with_thread_registry(self, expect_output):
        """Test multiple GC cycles work with thread registry"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    gc()
    gc()
    print(x.len())
    return 0
~
''', "3\n")

    def test_allocations_with_thread_registry(self, expect_output):
        """Test allocations work with thread registry in place"""
        expect_output('''
func main() -> int
    count = 0
    for i in 0..100
        temp = [i]
        count = count + 1
    ~
    print(count)
    return 0
~
''', "100\n")


class TestThreadRegistryWithCollections:
    """Test thread registry with various collection types"""

    def test_lists_with_thread_registry(self, expect_output):
        """Test lists work with thread registry"""
        expect_output('''
func main() -> int
    list = [1, 2, 3, 4, 5]
    gc()
    print(list.len())
    return 0
~
''', "5\n")

    def test_maps_with_thread_registry(self, expect_output):
        """Test maps work with thread registry"""
        expect_output('''
func main() -> int
    m = {1: 100, 2: 200}
    gc()
    print(m.get(1))
    return 0
~
''', "100\n")

    def test_sets_with_thread_registry(self, expect_output):
        """Test sets work with thread registry"""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    gc()
    print(s.len())
    return 0
~
''', "3\n")

    def test_strings_with_thread_registry(self, expect_output):
        """Test strings work with thread registry"""
        expect_output('''
func main() -> int
    str = "hello"
    gc()
    print(str.len())
    return 0
~
''', "5\n")


class TestThreadRegistryWithWatermark:
    """Test thread registry interaction with watermark"""

    def test_watermark_with_thread_registry(self, expect_output):
        """Test watermark works with thread registry"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    gc_install_watermark()
    work()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_watermark_loop_with_thread_registry(self, expect_output):
        """Test watermark in loop with thread registry"""
        expect_output('''
func inner()
    temp = [999]
~

func main() -> int
    outer = [1, 2, 3]
    for i in 0..5
        gc_install_watermark()
        inner()
    ~
    print(outer.len())
    return 0
~
''', "3\n")


class TestThreadRegistryWithFunctions:
    """Test thread registry with function calls"""

    def test_function_calls_with_thread_registry(self, expect_output):
        """Test function calls work with thread registry"""
        expect_output('''
func helper(_ x: int) -> int
    temp = [x]
    return temp.get(0) * 2
~

func main() -> int
    result = helper(21)
    gc()
    print(result)
    return 0
~
''', "42\n")

    def test_recursive_with_thread_registry(self, expect_output):
        """Test recursive functions work with thread registry"""
        expect_output('''
func factorial(_ n: int) -> int
    if n <= 1
        return 1
    ~
    return n * factorial(n - 1)
~

func main() -> int
    result = factorial(5)
    gc()
    print(result)
    return 0
~
''', "120\n")

    def test_deep_calls_with_thread_registry(self, expect_output):
        """Test deep call chains work with thread registry"""
        expect_output('''
func deep(_ n: int) -> int
    if n > 0
        temp = [n]
        gc()
        return deep(n - 1) + temp.get(0)
    ~
    return 0
~

func main() -> int
    result = deep(10)
    print(result)
    return 0
~
''', "55\n")


class TestThreadRegistryStress:
    """Stress tests for thread registry"""

    def test_many_gc_cycles_with_thread_registry(self, expect_output):
        """Test many GC cycles with thread registry"""
        expect_output('''
func main() -> int
    keeper = [42]
    for i in 0..50
        gc()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_many_allocations_and_gc_with_thread_registry(self, expect_output):
        """Test many allocations with GC and thread registry"""
        expect_output('''
func main() -> int
    count = 0
    for i in 0..100
        temp = [i, i*2]
        gc()
        count = count + 1
    ~
    print(count)
    return 0
~
''', "100\n")

    def test_heap_valid_with_thread_registry(self, expect_output):
        """Test heap validation with thread registry"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    y = {1: 10}
    z = {1, 2, 3}
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")
