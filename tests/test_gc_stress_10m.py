"""
Large-scale stress tests for Coex garbage collector.

These tests verify GC correctness at scale with allocations and deallocations.

NOTE: Current implementation has memory limitations that vary by type:
- Strings/Maps/Sets: ~500K allocations with gc() every 500
- Lists: ~100K allocations due to more complex internal structures

TODO: Investigate and fix the memory limitation to enable larger tests.

These tests verify:
1. GC correctness at scale
2. Memory is properly reclaimed (would OOM without working GC)
3. Dual-heap model handles sustained allocation pressure
4. Both gc() and gc_async() work under load

Run with: python3 -m pytest tests/test_gc_stress_10m.py -v -s
"""

import pytest


class TestGCStressAllocations:
    """Stress tests with allocations appropriate for each type."""

    def test_100k_list_allocations(self, expect_output):
        """Allocate 100K Lists with periodic gc()."""
        expect_output('''
func main() -> int
    var live: List<int> = [999]
    var count: int = 0

    for i in 0..100000
        var temp: List<int> = [i, i + 1, i + 2]
        count = count + 1
        if i % 100 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "100000\n999\n")

    def test_500k_map_allocations(self, expect_output):
        """Allocate 500K Maps with periodic gc()."""
        expect_output('''
func main() -> int
    var live: Map<int, int> = {0: 0}
    var count: int = 0

    for i in 0..500000
        var temp: Map<int, int> = {i: i * 2}
        count = count + 1
        if i % 500 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "500000\n0\n")

    def test_500k_set_allocations(self, expect_output):
        """Allocate 500K Sets with periodic gc()."""
        expect_output('''
func main() -> int
    var live: Set<int> = {999999}
    var count: int = 0

    for i in 0..500000
        var temp: Set<int> = {i, i + 1, i + 2}
        count = count + 1
        if i % 500 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.len())
    return 0
~
''', "500000\n1\n")

    def test_500k_string_allocations(self, expect_output):
        """Allocate 500K strings with periodic gc()."""
        expect_output('''
func main() -> int
    var live: string = "keeper"
    var count: int = 0

    for i in 0..500000
        var temp: string = "x"
        count = count + 1
        if i % 500 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.len())
    return 0
~
''', "500000\n6\n")

    def test_mixed_allocations(self, expect_output):
        """Mixed allocations of all types."""
        expect_output('''
func main() -> int
    var live_list: List<int> = [1]
    var live_map: Map<int, int> = {1: 1}
    var live_set: Set<int> = {1}
    var live_str: string = "x"
    var count: int = 0

    for i in 0..50000
        var t1: List<int> = [i, i + 1]
        var t2: Map<int, int> = {i: i}
        var t3: Set<int> = {i, i + 1}
        var t4: string = "a"
        count = count + 4
        if i % 50 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live_list.len())
    print(live_map.len())
    print(live_set.len())
    print(live_str.len())
    return 0
~
''', "200000\n1\n1\n1\n1\n")


class TestGCAsyncStress:
    """Stress tests using gc_async()."""

    def test_100k_list_allocations_async(self, expect_output):
        """Allocate 100K Lists with periodic gc_async()."""
        expect_output('''
func main() -> int
    var live: List<int> = [999]
    var count: int = 0

    for i in 0..100000
        var temp: List<int> = [i, i + 1, i + 2]
        count = count + 1
        if i % 100 == 0
            gc_async()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "100000\n999\n")

    def test_500k_map_allocations_async(self, expect_output):
        """Allocate 500K Maps with periodic gc_async()."""
        expect_output('''
func main() -> int
    var live: Map<int, int> = {0: 0}
    var count: int = 0

    for i in 0..500000
        var temp: Map<int, int> = {i: i * 2}
        count = count + 1
        if i % 500 == 0
            gc_async()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "500000\n0\n")

    def test_500k_set_allocations_async(self, expect_output):
        """Allocate 500K Sets with periodic gc_async()."""
        expect_output('''
func main() -> int
    var live: Set<int> = {999999}
    var count: int = 0

    for i in 0..500000
        var temp: Set<int> = {i, i + 1, i + 2}
        count = count + 1
        if i % 500 == 0
            gc_async()
        ~
    ~

    gc()
    print(count)
    print(live.len())
    return 0
~
''', "500000\n1\n")


class TestGCUserTypesStress:
    """Stress tests with user-defined types."""

    def test_100k_user_type_allocations(self, expect_output):
        """Allocate 100K user-defined type instances."""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    var live: Point = Point(x: 999, y: 888)
    var count: int = 0

    for i in 0..100000
        var temp: Point = Point(x: i, y: i + 1)
        count = count + 1
        if i % 100 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.x)
    print(live.y)
    return 0
~
''', "100000\n999\n888\n")

    def test_100k_user_type_with_list_field(self, expect_output):
        """User types containing List fields - complex heap graphs."""
        expect_output('''
type Container:
    items: List<int>
    id: int
~

func main() -> int
    var live: Container = Container(items: [1, 2, 3], id: 999)
    var count: int = 0

    for i in 0..100000
        var temp: Container = Container(items: [i], id: i)
        count = count + 1
        if i % 100 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.id)
    print(live.items.len())
    return 0
~
''', "100000\n999\n3\n")
