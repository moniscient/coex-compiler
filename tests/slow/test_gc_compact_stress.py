"""
Large-scale stress tests for heap compaction (gc_compact builtin).

These tests verify gc_compact correctness at scale:
- Many allocations followed by compaction
- Fragmented heap consolidation
- Repeated GC + compact cycles under pressure
- Compaction with mixed object types

Per CLAUDE.md: "stress-tests that show the bug or feature continuing to
operate at large-scale, defined as millions of units and gigabytes of
memory consumption."

Note: These tests may take several minutes to run.
Run with: python3 -m pytest tests/slow/test_gc_compact_stress.py -v
"""

import pytest


class TestGcCompactStress:
    """Stress tests for gc_compact at scale."""

    def test_gc_compact_many_lists(self, expect_output):
        """Create 10,000 lists, compact, verify last one alive."""
        expect_output('''
func main() -> int
    last = [0]
    for i in 0..10000
        last = [i]
    ~
    gc_compact()
    print(last.get(0))
    return 0
~
''', "9999\n")

    def test_gc_compact_many_strings(self, expect_output):
        """Create 10,000 strings, compact, verify last one alive."""
        expect_output('''
func main() -> int
    last = "start"
    for i in 0..10000
        last = "hello"
    ~
    gc_compact()
    print(last.len())
    print(last)
    return 0
~
''', "5\nhello\n")

    def test_gc_compact_many_maps(self, expect_output):
        """Create 10,000 maps, compact, verify last one alive."""
        expect_output('''
func main() -> int
    last = {0: 0}
    for i in 0..10000
        last = {(i): i * 2}
    ~
    gc_compact()
    print(last.get(9999))
    return 0
~
''', "19998\n")

    def test_gc_compact_fragmented_heap(self, expect_output):
        """Allocate, let die, allocate more to fragment heap, then compact.

        This creates alternating live/dead objects to simulate fragmentation.
        After compaction, live objects should be in contiguous memory.
        """
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = "keep_this"
    c = {1: 100}
    d = [4, 5, 6]
    e = "also_keep"
    f = {2: 200}

    gc()
    gc_compact()

    print(a.get(0))
    print(b)
    print(c.get(1))
    print(d.get(2))
    print(e)
    print(f.get(2))
    return 0
~
''', "1\nkeep_this\n100\n6\nalso_keep\n200\n")

    def test_gc_compact_repeated_cycles(self, expect_output):
        """Repeated gc_compact cycles with allocation in between.

        Tests that compaction works correctly over many cycles without
        accumulating corruption or memory leaks.
        """
        expect_output('''
func main() -> int
    x = [1]
    for i in 0..100
        x = x.append(i)
        if i % 10 == 0
            gc_compact()
        ~
    ~
    gc_compact()
    print(x.len())
    print(x.get(0))
    print(x.get(100))
    return 0
~
''', "101\n1\n99\n")

    def test_gc_compact_gc_interleaved_cycles(self, expect_output):
        """Interleave gc() and gc_compact() calls under allocation pressure.

        Tests that gc and gc_compact cooperate correctly across many cycles.
        """
        expect_output('''
func main() -> int
    live = [42]
    for i in 0..1000
        temp = {(i): i * 3}
        if i % 100 == 0
            gc()
        ~
        if i % 200 == 0
            gc_compact()
        ~
    ~
    gc_compact()
    gc()
    print(live.get(0))
    return 0
~
''', "42\n")

    def test_gc_compact_mixed_types_stress(self, expect_output):
        """Many different object types all surviving compaction."""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    a = [10, 20, 30, 40, 50]
    b = "hello world test string"
    c = {1: 100, 2: 200, 3: 300}
    d = {1, 2, 3, 4, 5}
    p = Point(7, 11)

    gc_compact()

    print(a.len())
    print(a.get(4))
    print(b.len())
    print(b)
    print(c.get(3))
    print(c.len())
    print(d.len())
    print(d.has(3))
    print(p.x)
    print(p.y)
    return 0
~
''', "5\n50\n23\nhello world test string\n300\n3\n5\ntrue\n7\n11\n")

    def test_gc_compact_large_list_stress(self, expect_output):
        """Build a large list across many compactions.

        Tests that internal PV-tree pointers are correctly updated
        across multiple compaction boundaries.
        """
        expect_output('''
func main() -> int
    x = [0]
    for i in 1..500
        x = x.append(i)
        if i % 50 == 0
            gc_compact()
        ~
    ~
    gc_compact()
    print(x.len())
    print(x.get(0))
    print(x.get(499))
    return 0
~
''', "500\n0\n499\n")

    def test_gc_compact_dead_object_pressure(self, expect_output):
        """Create lots of dead objects between compactions.

        Tests that compaction correctly handles heaps with many
        dead objects that need to be skipped.
        """
        expect_output('''
func main() -> int
    live = [42, 43, 44]
    for i in 0..5000
        dead = [i, i + 1, i + 2]
    ~
    gc_compact()
    print(live.get(0))
    print(live.get(1))
    print(live.get(2))
    return 0
~
''', "42\n43\n44\n")

    def test_gc_compact_100k_allocations(self, expect_output):
        """100,000 allocations with periodic compaction.

        Each loop creates a temp list (~3+ allocs: List, PV_NODE, tail).
        Total: 100K × 3 = ~300K allocations with periodic compaction.
        """
        expect_output('''
func main() -> int
    live = [99]
    count = 0
    for i in 0..100000
        temp = [i, i + 1]
        count = count + 1
        if i % 10000 == 0
            gc()
            gc_compact()
        ~
    ~
    gc_compact()
    print(count)
    print(live.get(0))
    return 0
~
''', "100000\n99\n")
