"""
Tests for dual-heap asynchronous garbage collector.

These tests verify the dual-heap async GC model:
1. Basic allocation and collection survives heap swaps
2. Cross-heap references are properly traced
3. gc_async() returns quickly while collection proceeds
4. Multiple GC cycles alternate heaps correctly

Test predictions:
- TestDualHeapBasics: PASS before/after (basic GC semantics unchanged)
- TestCrossHeapReferences: PASS before/after (reachability unchanged)
- TestAsyncBehavior: FAIL before (gc_async doesn't exist), PASS after
"""

import pytest


class TestDualHeapBasics:
    """Tests for basic dual-heap GC functionality.

    These tests should PASS with both sync and async GC - they verify
    that the fundamental GC semantics are preserved.
    """

    def test_gc_allocations_survive_swap(self, expect_output):
        """Allocations reachable at gc() time survive heap swap.

        Expected: PASS before/after implementation
        """
        expect_output('''
func main() -> int
    var items: List<int> = [1, 2, 3, 4, 5]
    var m: Map<int, int> = {1: 10, 2: 20}
    var s: Set<int> = {100, 200, 300}

    gc()

    print(items.len())
    print(m.get(1))
    print(s.len())
    return 0
~
''', "5\n10\n3\n")

    def test_gc_unreachable_reclaimed(self, expect_output):
        """Unreachable allocations are reclaimed after gc().

        Creates garbage in inner scope, then gc() reclaims it.
        If memory were not reclaimed, repeated calls would OOM.

        Expected: PASS before/after implementation
        """
        expect_output('''
func create_garbage() -> int
    var garbage: List<int> = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    var more: Map<int, int> = {1: 1, 2: 2, 3: 3}
    return 0
~

func main() -> int
    for i in 0..1000
        create_garbage()
        if i % 100 == 0
            gc()
        ~
    ~
    gc()
    print(42)
    return 0
~
''', "42\n")

    def test_multiple_gc_cycles(self, expect_output):
        """Multiple gc() calls work correctly (heap alternation).

        Each gc() should swap heaps. After many cycles, allocations
        should still work and live objects should survive.

        Expected: PASS before/after implementation
        """
        expect_output('''
func main() -> int
    var keeper: List<int> = [1, 2, 3]

    for round in 0..20
        var temp: Map<int, int> = {round: round * 10}
        gc()
    ~

    print(keeper.len())
    print(keeper.get(0))
    print(keeper.get(2))
    return 0
~
''', "3\n1\n3\n")


class TestCrossHeapReferences:
    """Tests for cross-heap pointer tracing.

    In dual-heap GC, objects in the new heap may reference objects
    in the old heap. The GC must trace these cross-heap references.
    """

    def test_new_object_pointing_to_old_heap(self, expect_output):
        """Object in new heap referencing object in old heap survives.

        Sequence:
        1. Create list in heap A (initial active heap)
        2. gc() swaps to heap B
        3. Create container in heap B with reference to list
        4. gc() collects heap A - list must survive via cross-heap ref

        Expected: PASS before/after implementation
        """
        expect_output('''
type Container:
    items: List<int>
    count: int
~

func main() -> int
    # Phase 1: Create object in first heap
    var original: List<int> = [10, 20, 30]

    # Phase 2: gc() - in async model, swaps heaps
    gc()

    # Phase 3: Create new object referencing the original
    var container: Container = Container(items: original, count: 3)

    # Phase 4: gc() again - original must survive via container reference
    gc()

    print(container.items.len())
    print(container.items.get(0))
    print(container.items.get(2))
    return 0
~
''', "3\n10\n30\n")

    def test_deep_cross_heap_chain(self, expect_output):
        """Chain of objects spanning multiple heap swaps survives.

        Creates objects across multiple gc() cycles, building a chain.
        All objects in the chain must survive because they're reachable.

        Expected: PASS before/after implementation
        """
        expect_output('''
type Link:
    value: int
    data: List<int>
~

func main() -> int
    # Create first link
    var link1: Link = Link(value: 1, data: [10, 11, 12])
    gc()

    # Create second link (may be in different heap)
    var link2: Link = Link(value: 2, data: [20, 21, 22])
    gc()

    # Create third link
    var link3: Link = Link(value: 3, data: [30, 31, 32])
    gc()

    # All links should survive - all are reachable
    print(link1.data.get(0))
    print(link2.data.get(1))
    print(link3.data.get(2))
    return 0
~
''', "10\n21\n32\n")

    def test_map_with_heap_values_across_gc(self, expect_output):
        """Map with heap-allocated values survives gc() cycles.

        Tests HAMT marking with cross-heap pointers in values.

        Expected: PASS before/after implementation
        """
        expect_output('''
func main() -> int
    var lists: Map<int, List<int>> = {}

    lists = lists.set(1, [10, 11, 12])
    gc()

    lists = lists.set(2, [20, 21, 22])
    gc()

    lists = lists.set(3, [30, 31, 32])
    gc()

    var l1: List<int> = lists.get(1)
    var l2: List<int> = lists.get(2)
    var l3: List<int> = lists.get(3)

    print(l1.get(0))
    print(l2.get(1))
    print(l3.get(2))
    return 0
~
''', "10\n21\n32\n")


class TestAsyncBehavior:
    """Tests for async-specific gc_async() behavior.

    These tests verify gc_async() functionality which doesn't exist
    in the current sync implementation.
    """

    def test_gc_async_exists(self, expect_output):
        """gc_async() builtin exists and can be called.

        Expected: FAIL before implementation (function doesn't exist)
        Expected: PASS after implementation
        """
        expect_output('''
func main() -> int
    gc_async()
    print(1)
    return 0
~
''', "1\n")

    def test_gc_async_allocations_work(self, expect_output):
        """Allocations work during/after gc_async() call.

        gc_async() triggers collection but returns immediately.
        Allocations should continue to work while collection proceeds.

        Expected: FAIL before implementation
        Expected: PASS after implementation
        """
        expect_output('''
func main() -> int
    var before: List<int> = [1, 2, 3]
    gc_async()
    var after: List<int> = [4, 5, 6]

    # Both lists should be accessible
    print(before.len())
    print(after.len())
    return 0
~
''', "3\n3\n")

    def test_gc_async_multiple_calls(self, expect_output):
        """Multiple gc_async() calls work correctly.

        Rapid gc_async() calls should not cause issues.
        If a collection is in progress, subsequent calls should be no-ops
        or wait appropriately.

        Expected: FAIL before implementation
        Expected: PASS after implementation
        """
        expect_output('''
func main() -> int
    var keeper: Map<int, int> = {1: 100}

    for i in 0..100
        var temp: List<int> = [i, i + 1, i + 2]
        gc_async()
    ~

    print(keeper.get(1))
    return 0
~
''', "100\n")


class TestGCStability:
    """Tests for GC stability under various conditions.

    These tests verify the GC remains stable with dual-heap model.
    """

    def test_gc_with_deeply_nested_structures(self, expect_output):
        """GC handles deeply nested heap structures.

        Tests that cross-heap scanning works with complex object graphs.

        Expected: PASS before/after implementation
        """
        expect_output('''
type Node:
    value: int
    children: List<int>
~

func main() -> int
    var nodes: List<int> = []

    for i in 0..50
        var node: Node = Node(value: i, children: [i * 10, i * 10 + 1])
        gc()
    ~

    # Create final structure that references heap objects
    var final: Node = Node(value: 999, children: [1, 2, 3, 4, 5])
    gc()

    print(final.value)
    print(final.children.len())
    return 0
~
''', "999\n5\n")

    def test_gc_rapid_alloc_collect_cycles(self, expect_output):
        """Rapid allocation/collection cycles remain stable.

        Creates allocation pressure with frequent gc() calls.
        Tests that heap swapping doesn't cause memory corruption.

        Expected: PASS before/after implementation
        """
        expect_output('''
func main() -> int
    var sum: int = 0

    for i in 0..500
        var m: Map<int, int> = {i: i * 2}
        sum = sum + m.get(i)
        gc()
    ~

    # Sum of 0*2 + 1*2 + 2*2 + ... + 499*2 = 2 * (0+1+2+...+499) = 2 * 124750 = 249500
    print(sum)
    return 0
~
''', "249500\n")

    def test_gc_empty_heaps(self, expect_output):
        """GC works correctly when heaps are mostly empty.

        Tests edge case where collection has nothing to collect.

        Expected: PASS before/after implementation
        """
        expect_output('''
func main() -> int
    gc()
    gc()
    gc()

    var x: int = 42
    gc()

    print(x)
    return 0
~
''', "42\n")
