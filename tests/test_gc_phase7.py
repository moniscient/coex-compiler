"""
Tests for Phase 7: First Trace Pass (Liveness)

These tests verify the watermark-aware root scanning:
- gc_scan_roots_watermark only scans frames at/below watermark depth
- Objects above watermark are skipped (birth-marked, already correct)
- Objects at/below watermark are properly marked
- gc_first_trace orchestrates the trace pass
"""

import pytest


class TestWatermarkRootScanning:
    """Tests for watermark-aware root scanning"""

    def test_scan_roots_preserves_pre_watermark_objects(self, expect_output):
        """Test that objects created before watermark are preserved"""
        expect_output('''
func work()
    temp = [999]
~

func main() -> int
    keeper = [1, 2, 3]
    gc_install_watermark()
    work()
    print(keeper.len())
    return 0
~
''', "3\n")

    def test_scan_roots_with_multiple_pre_watermark_objects(self, expect_output):
        """Test multiple objects created before watermark are all preserved"""
        expect_output('''
func work()
    temp = [999]
~

func main() -> int
    a = [1]
    b = [2]
    c = [3]
    gc_install_watermark()
    work()
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    return 0
~
''', "1\n2\n3\n")

    def test_scan_roots_nested_function_watermark(self, expect_output):
        """Test watermark in nested function preserves outer objects"""
        expect_output('''
func inner()
    temp = [888]
~

func outer()
    gc_install_watermark()
    inner()
~

func main() -> int
    keeper = [42]
    outer()
    print(keeper.get(0))
    return 0
~
''', "42\n")


class TestFirstTraceIntegration:
    """Tests for gc_first_trace integration"""

    def test_first_trace_with_simple_allocation(self, expect_output):
        """Test first trace works with simple allocation pattern"""
        expect_output('''
func allocate()
    temp = [1, 2, 3, 4, 5]
~

func main() -> int
    keep = [100]
    gc_install_watermark()
    allocate()
    gc()
    print(keep.get(0))
    return 0
~
''', "100\n")

    def test_first_trace_loop_allocations(self, expect_output):
        """Test first trace with loop allocations"""
        expect_output('''
func work()
    temp = [1]
~

func main() -> int
    keeper = [42]
    for i in 0..10
        gc_install_watermark()
        work()
    ~
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_first_trace_with_maps(self, expect_output):
        """Test first trace with map allocations"""
        expect_output('''
func allocate_map()
    temp = {1: 10, 2: 20}
~

func main() -> int
    keeper = {42: 420}
    gc_install_watermark()
    allocate_map()
    gc()
    print(keeper.get(42))
    return 0
~
''', "420\n")

    def test_first_trace_with_sets(self, expect_output):
        """Test first trace with set allocations"""
        expect_output('''
func allocate_set()
    temp = {100, 200, 300}
~

func main() -> int
    keeper = {1, 2, 3}
    gc_install_watermark()
    allocate_set()
    gc()
    print(keeper.len())
    return 0
~
''', "3\n")


class TestDepthBoundaryScanning:
    """Tests for depth boundary in root scanning"""

    def test_deep_calls_all_levels_preserved(self, expect_output):
        """Test objects at all call depths are preserved when below watermark"""
        expect_output('''
func level3()
    temp = [3]
    gc()
~

func level2()
    obj2 = [2]
    level3()
~

func level1()
    obj1 = [1]
    level2()
~

func main() -> int
    obj0 = [0]
    gc_install_watermark()
    level1()
    print(obj0.get(0))
    return 0
~
''', "0\n")

    def test_watermark_at_mid_depth(self, expect_output):
        """Test watermark installed at middle of call chain"""
        expect_output('''
func inner()
    temp = [999]
~

func middle()
    gc_install_watermark()
    inner()
~

func main() -> int
    keeper = [42]
    middle()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_recursive_with_watermark_at_base(self, expect_output):
        """Test recursive calls with watermark at recursion base"""
        expect_output('''
func recurse(_ n: int)
    if n > 0
        temp = [n]
        recurse(n - 1)
    else
        gc_install_watermark()
    ~
~

func main() -> int
    keeper = [100]
    recurse(5)
    print(keeper.get(0))
    return 0
~
''', "100\n")


class TestScanRootsWithCollections:
    """Tests for root scanning with various collection types"""

    def test_scan_roots_mixed_collections(self, expect_output):
        """Test scanning with mixed collection types before watermark"""
        expect_output('''
func work()
    temp = [1]
~

func main() -> int
    list = [1, 2, 3]
    map = {1: 10}
    set = {100, 200}
    gc_install_watermark()
    work()
    gc()
    print(list.len())
    print(map.get(1))
    print(set.len())
    return 0
~
''', "3\n10\n2\n")

    def test_scan_roots_string_preservation(self, expect_output):
        """Test string preservation across watermark boundary"""
        expect_output('''
func work()
    temp = "garbage"
~

func main() -> int
    keeper = "hello"
    gc_install_watermark()
    work()
    gc()
    print(keeper.len())
    return 0
~
''', "5\n")

    def test_scan_roots_large_list(self, expect_output):
        """Test large list preservation across watermark"""
        expect_output('''
func work()
    temp = [1, 2, 3, 4, 5]
~

func main() -> int
    keeper = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    gc_install_watermark()
    work()
    gc()
    print(keeper.len())
    return 0
~
''', "10\n")


class TestFirstTraceStress:
    """Stress tests for first trace pass"""

    def test_many_watermark_trace_cycles(self, expect_output):
        """Test many watermark and trace cycles"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    for i in 0..50
        gc_install_watermark()
        work()
        gc()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_deep_trace_chain(self, expect_output):
        """Test trace with deep call chain and allocations"""
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
    deep(15)
    print(keeper.get(0))
    return 0
~
''', "100\n")

    def test_heap_valid_after_trace_cycles(self, expect_output):
        """Test heap remains valid after many trace cycles"""
        expect_output('''
func work(_ i: int)
    temp = [i, i*2]
~

func main() -> int
    for i in 0..30
        gc_install_watermark()
        work(i)
        gc()
    ~
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_interleaved_explicit_gc_and_watermark(self, expect_output):
        """Test interleaved explicit GC and watermark-triggered GC"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    for i in 0..20
        gc()
        gc_install_watermark()
        work()
        gc()
    ~
    print(keeper.get(0))
    return 0
~
''', "42\n")


class TestTraceWithUserTypes:
    """Tests for first trace with user-defined types"""

    def test_trace_with_simple_user_type(self, expect_output):
        """Test trace preserves user type objects"""
        expect_output('''
type Point:
    x: int
    y: int
~

func work()
    temp = Point(99, 99)
~

func main() -> int
    p = Point(10, 20)
    gc_install_watermark()
    work()
    gc()
    print(p.x)
    print(p.y)
    return 0
~
''', "10\n20\n")

    def test_trace_with_nested_user_types(self, expect_output):
        """Test trace preserves nested user type objects"""
        expect_output('''
type Inner:
    val: int
~

type Outer:
    inner: Inner
~

func work()
    temp = Outer(Inner(999))
~

func main() -> int
    o = Outer(Inner(42))
    gc_install_watermark()
    work()
    gc()
    print(o.inner.val)
    return 0
~
''', "42\n")
