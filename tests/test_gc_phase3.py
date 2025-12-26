"""
Tests for Phase 3: High Watermark Tracking

These tests verify the high watermark GC mechanism:
- gc_install_watermark() sets the trigger point
- GC triggers automatically when returning to watermark depth
- Watermark is one-shot (clears after triggering)
- Live objects are preserved across watermark-triggered GC
"""

import pytest


class TestWatermarkBasics:
    """Basic tests for watermark functionality"""

    def test_gc_install_watermark_compiles(self, expect_output):
        """Test that gc_install_watermark() compiles and runs"""
        expect_output('''
func main() -> int
    gc_install_watermark()
    print(42)
    return 0
~
''', "42\n")

    def test_watermark_triggers_on_return(self, expect_output):
        """Test that GC triggers when returning to watermark depth"""
        expect_output('''
func work()
    temp = [1, 2, 3, 4, 5]
~

func main() -> int
    gc_install_watermark()
    work()
    # GC should have triggered when work() returned
    print(1)
    return 0
~
''', "1\n")

    def test_watermark_preserves_live_objects(self, expect_output):
        """Test that watermark-triggered GC preserves live objects"""
        expect_output('''
func allocate_temp()
    temp = [100, 200, 300]
~

func main() -> int
    keeper = [42, 43, 44]
    gc_install_watermark()
    allocate_temp()
    # GC triggered, but keeper should survive
    print(keeper.get(0))
    return 0
~
''', "42\n")


class TestWatermarkWithLoops:
    """Tests for watermark behavior in loops"""

    def test_watermark_in_loop(self, expect_output):
        """Test watermark triggering in a loop"""
        expect_output('''
func do_work(_ i: int)
    temp = [i, i*2, i*3]
~

func main() -> int
    for i in 0..3
        gc_install_watermark()
        do_work(i)
        # GC triggers here on each iteration
    ~
    print(3)
    return 0
~
''', "3\n")

    def test_watermark_loop_preserves_outer(self, expect_output):
        """Test that loop-watermark preserves outer scope objects"""
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


class TestWatermarkNesting:
    """Tests for nested watermark behavior"""

    def test_nested_function_watermark(self, expect_output):
        """Test watermark with nested function calls"""
        expect_output('''
func level2()
    temp2 = [200]
~

func level1()
    temp1 = [100]
    level2()
~

func main() -> int
    keeper = [42]
    gc_install_watermark()
    level1()
    # GC triggers when returning from level1
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_watermark_at_different_depths(self, expect_output):
        """Test watermark installed at different call depths"""
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
    # GC should trigger as we return through the call stack
    print(data.len())
    return 0
~
''', "3\n")


class TestWatermarkOneShot:
    """Tests to verify watermark is one-shot"""

    def test_watermark_clears_after_trigger(self, expect_output):
        """Test that watermark only triggers once"""
        expect_output('''
func work()
    temp = [1]
~

func main() -> int
    gc_install_watermark()
    work()
    # First return - GC triggers and clears watermark
    work()
    # Second return - no GC (watermark cleared)
    print(1)
    return 0
~
''', "1\n")

    def test_reinstall_watermark(self, expect_output):
        """Test that watermark can be reinstalled"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    count = 0
    for i in 0..3
        gc_install_watermark()
        work()
        count = count + 1
    ~
    print(count)
    return 0
~
''', "3\n")


class TestWatermarkWithCollections:
    """Tests for watermark with various collection types"""

    def test_watermark_with_maps(self, expect_output):
        """Test watermark-triggered GC with maps"""
        expect_output('''
func create_map()
    m = {1: 10, 2: 20, 3: 30}
~

func main() -> int
    keeper = {100: 1000}
    gc_install_watermark()
    create_map()
    print(keeper.get(100))
    return 0
~
''', "1000\n")

    def test_watermark_with_sets(self, expect_output):
        """Test watermark-triggered GC with sets"""
        expect_output('''
func create_set()
    s = {1, 2, 3, 4, 5}
~

func main() -> int
    keeper = {100, 200}
    gc_install_watermark()
    create_set()
    print(keeper.len())
    return 0
~
''', "2\n")

    def test_watermark_with_strings(self, expect_output):
        """Test watermark-triggered GC with strings"""
        expect_output('''
func create_string()
    s = "temporary string"
~

func main() -> int
    keeper = "permanent"
    gc_install_watermark()
    create_string()
    print(keeper.len())
    return 0
~
''', "9\n")
