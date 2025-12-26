"""
Tests for Phase 4: Mark Bit Inversion

These tests verify the mark bit inversion mechanism:
- gc_current_mark_value alternates between 0 and 1
- Objects are birth-marked with current mark value
- Mark phase sets mark bit to current value
- Sweep checks mark bit against current value
- Mark value flips after each GC cycle
"""

import pytest


class TestMarkInversionBasics:
    """Basic tests for mark bit inversion correctness"""

    def test_object_survives_single_gc(self, expect_output):
        """Test that live objects survive a single GC cycle"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    print(x.len())
    return 0
~
''', "3\n")

    def test_object_survives_two_gc_cycles(self, expect_output):
        """Test that live objects survive two consecutive GC cycles (mark flips)"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    gc()
    print(x.len())
    return 0
~
''', "3\n")

    def test_object_survives_many_gc_cycles(self, expect_output):
        """Test that live objects survive many GC cycles (multiple mark flips)"""
        expect_output('''
func main() -> int
    x = [100, 200, 300]
    for i in 0..10
        gc()
    ~
    print(x.get(1))
    return 0
~
''', "200\n")


class TestMarkInversionWithAllocations:
    """Tests for mark inversion with interleaved allocations"""

    def test_allocations_between_gc_cycles(self, expect_output):
        """Test that allocations between GC cycles work correctly"""
        expect_output('''
func main() -> int
    a = [1]
    gc()
    b = [2]
    gc()
    c = [3]
    gc()
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    return 0
~
''', "1\n2\n3\n")

    def test_garbage_collected_across_cycles(self, expect_output):
        """Test that garbage is collected across multiple cycles"""
        expect_output('''
func main() -> int
    for i in 0..5
        temp = [i, i*2, i*3]
    ~
    gc()
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_mixed_live_and_garbage(self, expect_output):
        """Test that GC correctly distinguishes live from garbage objects"""
        expect_output('''
func create_garbage()
    garbage = [999, 888, 777]
~

func main() -> int
    keeper = [42]
    gc()
    create_garbage()
    gc()
    create_garbage()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")


class TestMarkInversionWithFunctions:
    """Tests for mark inversion with function calls"""

    def test_objects_survive_gc_in_deep_calls(self, expect_output):
        """Test that objects survive GC during deep function calls"""
        expect_output('''
func deep(_ n: int)
    if n > 0
        gc()
        deep(n - 1)
    ~
~

func main() -> int
    data = [1, 2, 3, 4, 5]
    deep(5)
    print(data.len())
    return 0
~
''', "5\n")

    def test_returned_objects_survive_multiple_gc(self, expect_output):
        """Test that returned objects survive multiple GC cycles"""
        expect_output('''
func create() -> int
    temp = [10, 20, 30]
    gc()
    return temp.get(1)
~

func main() -> int
    result = create()
    gc()
    gc()
    print(result)
    return 0
~
''', "20\n")


class TestMarkInversionWithCollections:
    """Tests for mark inversion with different collection types"""

    def test_maps_survive_multiple_gc(self, expect_output):
        """Test that maps survive multiple GC cycles"""
        expect_output('''
func main() -> int
    m = {1: 100, 2: 200, 3: 300}
    gc()
    gc()
    gc()
    print(m.get(2))
    return 0
~
''', "200\n")

    def test_sets_survive_multiple_gc(self, expect_output):
        """Test that sets survive multiple GC cycles"""
        expect_output('''
func main() -> int
    s = {10, 20, 30, 40, 50}
    gc()
    gc()
    gc()
    print(s.len())
    return 0
~
''', "5\n")

    def test_strings_survive_multiple_gc(self, expect_output):
        """Test that strings survive multiple GC cycles"""
        expect_output('''
func main() -> int
    str = "hello world"
    gc()
    gc()
    gc()
    print(str.len())
    return 0
~
''', "11\n")

    def test_nested_collections_survive_multiple_gc(self, expect_output):
        """Test that nested collections survive multiple GC cycles"""
        expect_output('''
func main() -> int
    outer = [1, 2, 3]
    inner = [4, 5, 6]
    gc()
    gc()
    print(outer.len())
    print(inner.len())
    return 0
~
''', "3\n3\n")


class TestMarkInversionWithWatermark:
    """Tests for mark inversion combined with high watermark"""

    def test_watermark_with_mark_inversion(self, expect_output):
        """Test that watermark-triggered GC works with mark inversion"""
        expect_output('''
func work()
    temp = [1, 2, 3]
~

func main() -> int
    keeper = [42]
    gc_install_watermark()
    work()
    # GC triggered with mark inversion
    gc()
    gc()
    print(keeper.get(0))
    return 0
~
''', "42\n")

    def test_watermark_loop_with_mark_inversion(self, expect_output):
        """Test watermark in loop with mark inversion across iterations"""
        expect_output('''
func inner()
    temp = [999]
~

func main() -> int
    outer = [1, 2, 3]
    for i in 0..10
        gc_install_watermark()
        inner()
    ~
    gc()
    gc()
    print(outer.len())
    return 0
~
''', "3\n")


class TestMarkInversionStress:
    """Stress tests for mark inversion"""

    def test_many_gc_cycles_with_allocations(self, expect_output):
        """Test many GC cycles with continuous allocations"""
        expect_output('''
func main() -> int
    persistent = [0]
    for i in 0..50
        temp = [i]
        gc()
    ~
    print(persistent.len())
    return 0
~
''', "1\n")

    def test_alternating_alloc_gc_pattern(self, expect_output):
        """Test alternating allocation and GC pattern"""
        expect_output('''
func main() -> int
    count = 0
    for i in 0..20
        a = [i]
        gc()
        b = [i * 2]
        gc()
        count = count + 1
    ~
    print(count)
    return 0
~
''', "20\n")

    def test_heap_valid_after_many_cycles(self, expect_output):
        """Test that heap remains valid after many GC cycles with mark inversion"""
        expect_output('''
func allocate(_ n: int)
    temp = [n, n+1, n+2]
~

func main() -> int
    for i in 0..30
        allocate(i)
        gc()
    ~
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")
