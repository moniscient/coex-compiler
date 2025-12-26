"""
Tests for Phase 0: GC Debugging Infrastructure

These tests verify the debugging infrastructure added in Phase 0:
- Trace level configuration
- Statistics collection
- Heap inspector utilities
- Frame depth tracking
"""

import pytest


class TestGCTracing:
    """Tests for GC tracing framework"""

    def test_gc_dump_stats_exists(self, expect_output):
        """Test that gc_dump_stats() function compiles and runs"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_stats()
    return 0
~
''', "[GC:STATS]", partial=True)

    def test_gc_dump_heap_exists(self, expect_output):
        """Test that gc_dump_heap() function compiles and runs"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_heap()
    return 0
~
''', "[GC:HEAP]", partial=True)

    def test_gc_dump_roots_exists(self, expect_output):
        """Test that gc_dump_roots() function compiles and runs"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_roots()
    return 0
~
''', "[GC:ROOTS]", partial=True)

    def test_gc_validate_heap_exists(self, expect_output):
        """Test that gc_validate_heap() function compiles and runs"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")  # Should return 0 for valid heap


class TestGCStatistics:
    """Tests for GC statistics collection"""

    def test_stats_track_allocations(self, expect_output):
        """Test that allocation statistics are tracked"""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = [4, 5, 6]
    gc_dump_stats()
    return 0
~
''', "total_allocations:", partial=True)

    def test_stats_track_bytes(self, expect_output):
        """Test that byte statistics are tracked"""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    gc_dump_stats()
    return 0
~
''', "total_bytes:", partial=True)


class TestGCFrameDepth:
    """Tests for frame depth tracking"""

    def test_frame_depth_in_roots_dump(self, expect_output):
        """Test that frame depth is shown in roots dump"""
        expect_output('''
func main() -> int
    x = 42
    gc_dump_roots()
    return 0
~
''', "depth=", partial=True)


class TestGCHeapInspector:
    """Tests for heap inspector utilities"""

    def test_heap_dump_shows_objects(self, expect_output):
        """Test that heap dump shows allocated objects"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_heap()
    return 0
~
''', "obj=", partial=True)

    def test_heap_dump_shows_total(self, expect_output):
        """Test that heap dump shows total object count"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_heap()
    return 0
~
''', "Total objects:", partial=True)

    def test_validate_heap_returns_zero_for_valid_heap(self, expect_output):
        """Test that validate_heap returns 0 for a valid heap"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    y = "hello"
    z = {1, 2, 3}
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")
