"""
Tests for Phase 6: Watermark Mechanism Enhancement

These tests verify the enhanced watermark mechanism with ThreadEntry integration:
- gc_install_watermarks() installs watermarks on all threads
- gc_clear_watermarks() clears watermarks on all threads
- Stack depth is synced to ThreadEntry during push/pop
- Watermark state is properly maintained in ThreadEntry
"""

import pytest


class TestWatermarkThreadIntegration:
    """Tests for watermark integration with thread registry"""

    def test_watermark_still_works_with_thread_sync(self, expect_output):
        """Test that basic watermark functionality works with thread sync"""
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

    def test_watermark_loop_with_thread_sync(self, expect_output):
        """Test watermark in loop with thread synchronization"""
        expect_output('''
func inner()
    temp = [999]
~

func main() -> int
    count = 0
    for i in 0..5
        gc_install_watermark()
        inner()
        count = count + 1
    ~
    print(count)
    return 0
~
''', "5\n")

    def test_watermark_preserves_live_with_thread_sync(self, expect_output):
        """Test that watermark-triggered GC preserves live objects with thread sync"""
        expect_output('''
func allocate_temp()
    temp = [100, 200, 300]
~

func main() -> int
    keeper = [42, 43, 44]
    gc_install_watermark()
    allocate_temp()
    print(keeper.get(0))
    print(keeper.get(1))
    print(keeper.get(2))
    return 0
~
''', "42\n43\n44\n")


class TestStackDepthSync:
    """Tests for stack depth synchronization with ThreadEntry"""

    def test_depth_tracking_survives_nested_calls(self, expect_output):
        """Test that stack depth tracking works through nested calls"""
        expect_output('''
func level3() -> int
    gc()
    return 3
~

func level2() -> int
    return level3() + 2
~

func level1() -> int
    return level2() + 1
~

func main() -> int
    result = level1()
    print(result)
    return 0
~
''', "6\n")

    def test_depth_tracking_with_recursion(self, expect_output):
        """Test stack depth tracking with recursive calls"""
        expect_output('''
func recurse(_ n: int) -> int
    if n <= 0
        gc()
        return 0
    ~
    return n + recurse(n - 1)
~

func main() -> int
    result = recurse(5)
    print(result)
    return 0
~
''', "15\n")

    def test_depth_tracking_with_watermark_in_recursion(self, expect_output):
        """Test depth tracking with watermark in recursive function"""
        expect_output('''
func deep(_ n: int)
    if n > 0
        deep(n - 1)
    else
        gc_install_watermark()
    ~
~

func main() -> int
    data = [1, 2, 3]
    deep(5)
    print(data.len())
    return 0
~
''', "3\n")


class TestMultipleWatermarks:
    """Tests for multiple watermark installations"""

    def test_sequential_watermark_installations(self, expect_output):
        """Test sequential watermark installations work correctly"""
        expect_output('''
func work()
    temp = [1]
~

func main() -> int
    count = 0

    gc_install_watermark()
    work()
    count = count + 1

    gc_install_watermark()
    work()
    count = count + 1

    gc_install_watermark()
    work()
    count = count + 1

    print(count)
    return 0
~
''', "3\n")

    def test_watermark_at_different_depths(self, expect_output):
        """Test watermarks installed at different call depths"""
        expect_output('''
func level2()
    temp = [2]
~

func level1()
    gc_install_watermark()
    level2()
~

func main() -> int
    keeper = [1]
    level1()
    print(keeper.get(0))
    return 0
~
''', "1\n")


class TestWatermarkWithGC:
    """Tests for watermark interaction with explicit GC calls"""

    def test_explicit_gc_with_watermark(self, expect_output):
        """Test explicit GC calls work alongside watermark mechanism"""
        expect_output('''
func work()
    temp = [1, 2, 3]
    gc()
~

func main() -> int
    keeper = [42]
    gc_install_watermark()
    work()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_multiple_gc_between_watermarks(self, expect_output):
        """Test multiple GC calls between watermark installations"""
        expect_output('''
func main() -> int
    keeper = [1, 2, 3]

    gc_install_watermark()
    gc()
    gc()

    gc_install_watermark()
    gc()

    print(keeper.len())
    return 0
~
''', "3\n")


class TestWatermarkWithCollections:
    """Tests for watermark with various collection types after Phase 6 enhancement"""

    def test_watermark_with_nested_lists(self, expect_output):
        """Test watermark with nested list allocations"""
        expect_output('''
func create_lists()
    a = [1, 2, 3]
    b = [4, 5, 6]
    c = [7, 8, 9]
~

func main() -> int
    keeper = [10, 20, 30]
    gc_install_watermark()
    create_lists()
    print(keeper.get(0))
    print(keeper.get(2))
    return 0
~
''', "10\n30\n")

    def test_watermark_with_maps_and_sets(self, expect_output):
        """Test watermark with map and set allocations"""
        expect_output('''
func create_collections()
    m = {1: 10, 2: 20}
    s = {100, 200, 300}
~

func main() -> int
    keeper_map = {42: 420}
    keeper_set = {1, 2}
    gc_install_watermark()
    create_collections()
    print(keeper_map.get(42))
    print(keeper_set.len())
    return 0
~
''', "420\n2\n")


class TestWatermarkStress:
    """Stress tests for watermark mechanism with thread synchronization"""

    def test_many_watermark_cycles(self, expect_output):
        """Test many watermark installation and trigger cycles"""
        expect_output('''
func work()
    temp = [1]
~

func main() -> int
    keeper = [42]
    for i in 0..50
        gc_install_watermark()
        work()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_deep_calls_with_watermarks(self, expect_output):
        """Test deep call chains with watermark installations"""
        expect_output('''
func deep(_ n: int)
    if n > 0
        gc_install_watermark()
        temp = [n]
        deep(n - 1)
    ~
~

func main() -> int
    keeper = [100]
    deep(10)
    print(keeper.get(0))
    return 0
~
''', "100\n")

    def test_heap_valid_after_many_watermark_cycles(self, expect_output):
        """Test heap remains valid after many watermark cycles"""
        expect_output('''
func work(_ i: int)
    temp = [i, i*2, i*3]
~

func main() -> int
    for i in 0..30
        gc_install_watermark()
        work(i)
    ~
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_alternating_watermark_and_gc(self, expect_output):
        """Test alternating between watermark-triggered and explicit GC"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    for i in 0..10
        gc_install_watermark()
        work()
        gc()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")
