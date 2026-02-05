"""
Tests for heap compaction (gc_compact builtin).

gc_compact() consolidates live objects into a contiguous buffer,
reducing fragmentation. It works by:
1. Running GC to get a clean live set
2. Copying live objects to a new contiguous buffer
3. Updating handle table entries to point to new locations
4. Deferring old memory cleanup to next GC cycle
"""

import pytest


class TestGcCompactBasic:
    """Basic correctness tests for gc_compact."""

    def test_gc_compact_empty_heap(self, expect_output):
        """gc_compact on empty heap should not crash."""
        expect_output('''
func main() -> int
    gc_compact()
    print(0)
    return 0
~
''', "0\n")

    def test_gc_compact_preserves_values(self, expect_output):
        """Lists, strings, and maps should survive compaction."""
        expect_output('''
func main() -> int
    x = [10, 20, 30]
    s = "hello"
    m = {1: 100, 2: 200}
    gc_compact()
    print(x.len())
    print(x.get(0))
    print(x.get(1))
    print(x.get(2))
    print(s.len())
    print(m.get(1))
    print(m.get(2))
    return 0
~
''', "3\n10\n20\n30\n5\n100\n200\n")

    def test_gc_compact_preserves_nested(self, expect_output):
        """Nested structures (list of lists, map of strings) survive compaction."""
        expect_output('''
func main() -> int
    a = [1, 2]
    b = [3, 4]
    outer = [a.len(), b.len()]
    m = {1: "one", 2: "two"}
    gc_compact()
    print(outer.get(0))
    print(outer.get(1))
    print(m.get(1))
    print(m.get(2))
    return 0
~
''', "2\n2\none\ntwo\n")

    def test_gc_compact_preserves_user_types(self, expect_output):
        """User-defined types survive compaction."""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    p = Point(3, 7)
    gc_compact()
    print(p.x)
    print(p.y)
    return 0
~
''', "3\n7\n")

    def test_gc_compact_after_allocation(self, expect_output):
        """Allocate, compact, then verify values are intact."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = [4, 5, 6]
    c = [7, 8, 9]
    gc_compact()
    print(a.get(0))
    print(b.get(1))
    print(c.get(2))
    print(a.len())
    return 0
~
''', "1\n5\n9\n3\n")

    def test_gc_compact_handle_stability(self, expect_output):
        """Handles should be valid before and after compaction."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = "test"
    print(a.len())
    print(b.len())
    gc_compact()
    print(a.len())
    print(b.len())
    return 0
~
''', "3\n4\n3\n4\n")

    def test_gc_compact_multiple_rounds(self, expect_output):
        """Multiple compaction rounds should work correctly."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc_compact()
    print(x.get(0))
    x = x.append(4)
    gc_compact()
    print(x.get(3))
    x = x.append(5)
    gc_compact()
    print(x.len())
    return 0
~
''', "1\n4\n5\n")

    def test_gc_compact_with_gc(self, expect_output):
        """gc() then gc_compact() then gc() should work correctly."""
        expect_output('''
func main() -> int
    x = [10, 20, 30]
    gc()
    gc_compact()
    gc()
    print(x.get(0))
    print(x.get(1))
    print(x.get(2))
    return 0
~
''', "10\n20\n30\n")

    def test_gc_compact_enum_values(self, expect_output):
        """Enum values with associated data survive compaction."""
        expect_output('''
type Shape:
    case Circle(radius: int)
    case Rect(w: int, h: int)
~

func main() -> int
    s = Shape.Circle(5)
    r = Shape.Rect(3, 4)
    gc_compact()
    match s
        case Circle(radius):
            print(radius)
        ~
        case Rect(w, h):
            print(w)
        ~
    ~
    match r
        case Circle(radius):
            print(radius)
        ~
        case Rect(w, h):
            print(w + h)
        ~
    ~
    return 0
~
''', "5\n7\n")

    def test_gc_compact_string_operations(self, expect_output):
        """String operations work correctly after compaction."""
        expect_output('''
func main() -> int
    s = "hello world"
    gc_compact()
    print(s.len())
    print(s)
    return 0
~
''', "11\nhello world\n")

    def test_gc_compact_map_operations(self, expect_output):
        """Map operations work correctly after compaction."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    gc_compact()
    print(m.len())
    print(m.has(1))
    print(m.has(4))
    print(m.get(2))
    return 0
~
''', "3\ntrue\nfalse\n20\n")

    def test_gc_compact_set_operations(self, expect_output):
        """Set operations work correctly after compaction."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    gc_compact()
    print(s.len())
    print(s.has(3))
    print(s.has(6))
    return 0
~
''', "5\ntrue\nfalse\n")

    def test_gc_compact_dead_objects_freed(self, expect_output):
        """Dead objects should not cause issues after compaction."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    x = [4, 5, 6]
    gc_compact()
    print(x.get(0))
    print(x.get(1))
    print(x.get(2))
    return 0
~
''', "4\n5\n6\n")

    def test_gc_compact_interleaved_alloc(self, expect_output):
        """Allocation after compaction should work correctly."""
        expect_output('''
func main() -> int
    a = [1, 2]
    gc_compact()
    b = [3, 4]
    gc_compact()
    print(a.get(0))
    print(b.get(0))
    c = [5, 6]
    print(c.get(1))
    return 0
~
''', "1\n3\n6\n")
