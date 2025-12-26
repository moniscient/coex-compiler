"""
Tests for Phase 1: New 32-byte Object Header

These tests verify the header changes in Phase 1:
- 32-byte header (4 x i64)
- Birth-marking (objects born marked)
- Forward pointer field (initialized to 0)
"""

import pytest


class TestBirthMarking:
    """Tests for birth-marking (objects born marked)"""

    def test_new_objects_survive_immediate_gc(self, expect_output):
        """Test that newly allocated objects survive immediate GC due to birth-marking"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    print(x.len())
    return 0
~
''', "3\n")

    def test_birth_marked_objects_in_loop(self, expect_output):
        """Test that objects created in loop survive GC during loop"""
        expect_output('''
func main() -> int
    sum = 0
    for i in 0..5
        x = [i, i*2, i*3]
        gc()
        sum = sum + x.len()
    ~
    print(sum)
    return 0
~
''', "15\n")

    def test_nested_allocations_survive_gc(self, expect_output):
        """Test that nested allocations all survive immediate GC"""
        expect_output('''
func main() -> int
    outer = [1, 2, 3]
    inner = [4, 5, 6]
    gc()
    print(outer.len())
    print(inner.len())
    return 0
~
''', "3\n3\n")


class TestNewHeaderStructure:
    """Tests for the new 32-byte header"""

    def test_heap_validate_with_new_header(self, expect_output):
        """Test that heap validation works with new 32-byte header"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    y = "hello"
    z = {1: 10, 2: 20}
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_heap_dump_shows_correct_info(self, expect_output):
        """Test that heap dump shows objects with new header format"""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_dump_heap()
    return 0
~
''', "type=", partial=True)

    def test_many_allocations_with_new_header(self, expect_output):
        """Test many allocations work with new 32-byte header"""
        expect_output('''
func main() -> int
    count = 0
    for i in 0..100
        x = [i]
        count = count + 1
    ~
    print(count)
    return 0
~
''', "100\n")


class TestGCWithBirthMarking:
    """Tests for GC behavior with birth-marking"""

    def test_gc_reclaims_unreferenced_objects(self, expect_output):
        """Test that GC still reclaims objects after marks are cleared"""
        expect_output('''
func main() -> int
    for i in 0..10
        temp = [1, 2, 3, 4, 5]
    ~
    gc()
    gc()
    result = gc_validate_heap()
    print(result)
    return 0
~
''', "0\n")

    def test_gc_preserves_live_objects(self, expect_output):
        """Test that GC preserves live objects through multiple cycles"""
        expect_output('''
func main() -> int
    keeper = [100, 200, 300]
    gc()
    gc()
    gc()
    print(keeper.get(1))
    return 0
~
''', "200\n")
