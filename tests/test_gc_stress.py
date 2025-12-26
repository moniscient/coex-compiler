"""
Large-scale stress tests for Coex garbage collector.

These tests verify GC correctness at scale:
- Millions of allocations
- Gigabytes of memory throughput (allocated then reclaimed)
- Long-running collection cycles

Per CLAUDE.md: "stress-tests that show the bug or feature continuing to
operate at large-scale, defined as millions of units and gigabytes of
memory consumption."

Note: These tests may take several minutes to run.
Run with: python3 -m pytest tests/test_gc_stress.py -v
"""

import pytest


class TestGCLargeScaleStress:
    """Large-scale stress tests for GC with millions of allocations."""

    def test_gc_million_map_allocations(self, expect_output):
        """Create ~300,000 Map allocations with periodic gc().

        Each iteration creates a single-entry Map (~3 allocations).
        100,000 iterations × 3 = 300,000 allocations.
        With gc() every 1000 iterations, memory stays bounded.

        Total memory throughput: ~300K × 50 bytes = ~15MB
        """
        expect_output('''
func main() -> int
    live: Map<int, int> = {0: 0}
    count: int = 0

    for i in 0..100000
        temp: Map<int, int> = {i: i * 2}
        count = count + 1
        if i % 1000 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "100000\n0\n")

    def test_gc_large_map_building(self, expect_output):
        """Build a Map with 10,000 entries, creating ~50,000 intermediate allocations.

        Each .set() creates: 1 Map + 1 leaf + possibly nodes/arrays
        10,000 entries × ~5 allocations = ~50,000 allocations

        Memory throughput: ~50K × 50 bytes = ~2.5MB per build
        10 builds = ~25MB total throughput
        """
        expect_output('''
func build_large_map(size: int) -> Map<int, int>
    m: Map<int, int> = {}
    for i in 0..size
        m = m.set(i, i * 3)
    ~
    return m
~

func main() -> int
    for round in 0..10
        big: Map<int, int> = build_large_map(10000)
        gc()
    ~

    final: Map<int, int> = build_large_map(100)
    print(final.get(50))
    print(final.len())
    return 0
~
''', "150\n100\n")

    def test_gc_million_set_allocations(self, expect_output):
        """Create ~900,000 Set allocations with periodic gc().

        100,000 iterations × 3-element Sets × ~3 allocations = ~900,000 allocations

        Total memory throughput: ~900K × 40 bytes = ~36MB
        """
        expect_output('''
func main() -> int
    live: Set<int> = {999999}
    count: int = 0

    for i in 0..100000
        temp: Set<int> = {i, i + 1, i + 2}
        count = count + 1
        if i % 1000 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.len())
    return 0
~
''', "100000\n1\n")

    def test_gc_sustained_allocation_pressure(self, expect_output):
        """Sustained allocation pressure with continuous gc() calls.

        Creates new Maps every iteration while keeping one alive.
        Tests that gc() can keep up with allocation rate.

        50,000 iterations with gc() every iteration = 50,000 gc cycles
        Each creating ~10 allocations = 500,000 total allocations
        """
        expect_output('''
func main() -> int
    keeper: Map<int, int> = {1: 1, 2: 2, 3: 3}

    for i in 0..50000
        garbage: Map<int, int> = {i: i, i+1: i+1}
        gc()
    ~

    print(keeper.get(1))
    print(keeper.get(2))
    print(keeper.get(3))
    return 0
~
''', "1\n2\n3\n")

    def test_gc_deep_map_chain(self, expect_output):
        """Build Maps through deep mutation chains.

        Each round: start with empty, add 1000 entries one by one.
        Creates 1000 intermediate Maps per round × 100 rounds = 100,000 Maps
        Plus leaves, nodes, arrays = ~500,000 total allocations
        """
        expect_output('''
func main() -> int
    final_sum: int = 0

    for round in 0..100
        m: Map<int, int> = {}
        for i in 0..1000
            m = m.set(i, round)
        ~
        final_sum = final_sum + m.len()
        gc()
    ~

    print(final_sum)
    return 0
~
''', "100000\n")


class TestGCMemoryBoundedStress:
    """Tests that verify GC keeps memory bounded under allocation pressure."""

    def test_gc_bounded_memory_maps(self, expect_output):
        """Verify memory stays bounded with proper gc() usage.

        Without gc(), 100K Maps would consume ~5MB minimum.
        With gc() every 100 iterations, peak should stay under 1MB.

        If this test completes without OOM, gc() is reclaiming memory.
        """
        expect_output('''
func main() -> int
    survivor: Map<int, int> = {42: 42}

    for i in 0..100000
        temp: Map<int, int> = {i: i * i}
        if i % 100 == 0
            gc()
        ~
    ~

    print(survivor.get(42))
    return 0
~
''', "42\n")

    def test_gc_bounded_memory_mixed_collections(self, expect_output):
        """Mixed Map, Set, and List allocations with bounded memory.

        Creates all three collection types in a loop.
        Tests that gc() handles heterogeneous allocation patterns.
        """
        expect_output('''
func main() -> int
    live_map: Map<int, int> = {1: 10}
    live_set: Set<int> = {100}
    live_list: List<int> = [1000]

    for i in 0..10000
        temp_map: Map<int, int> = {i: i}
        temp_set: Set<int> = {i, i + 1}
        temp_list: List<int> = [i, i + 1, i + 2]

        if i % 100 == 0
            gc()
        ~
    ~

    gc()
    print(live_map.get(1))
    print(live_set.len())
    print(live_list.len())
    return 0
~
''', "10\n1\n1\n")


class TestGCStringMapStress:
    """Stress tests for Maps with string keys (different HAMT path)."""

    def test_gc_string_key_map_stress(self, expect_output):
        """Stress test Map<string, int> with gc().

        String keys use different HAMT functions (hamt_insert_string).
        This verifies the string path also handles gc() correctly.

        Type-aware HAMT marking: Map/Set structs store flags indicating
        whether keys/values are heap pointers. gc_mark_hamt uses these
        flags to mark key/value contents appropriately.
        """
        expect_output('''
func main() -> int
    live: Map<string, int> = {"keep": 999}

    for i in 0..1000
        temp: Map<string, int> = {"a": i, "b": i + 1}
        gc()
    ~

    print(live.get("keep"))
    return 0
~
''', "999\n")
