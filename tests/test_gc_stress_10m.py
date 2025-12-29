"""
Large-scale stress tests for Coex garbage collector.

These tests verify GC correctness at scale with 1 million allocations per type.

Tests verify:
1. GC correctness at scale (1M allocations)
2. Memory is properly reclaimed (would OOM without working GC)
3. Automatic GC via function entry safe points handles sustained pressure
4. Both gc() and gc_async() work under load

Run with: python3 -m pytest tests/test_gc_stress_10m.py -v -s
"""

import pytest


class TestGCStressAllocations:
    """Stress tests with 1 million allocations per type."""

    def test_100k_list_allocations(self, expect_output):
        """Allocate 100K Lists with periodic gc().

        Lists have more complex internal structures than other types,
        so we use 100K instead of 1M to keep test times reasonable.
        """
        expect_output('''
func main() -> int
    live: List<int> = [999]
    count: int = 0

    for i in 0..100000
        temp: List<int> = [i, i + 1, i + 2]
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

    def test_1m_map_allocations(self, expect_output):
        """Allocate 1M Maps with periodic gc()."""
        expect_output('''
func main() -> int
    live: Map<int, int> = {0: 0}
    count: int = 0

    for i in 0..1000000
        temp: Map<int, int> = {(i): i * 2}
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
''', "1000000\n0\n")

    def test_1m_set_allocations(self, expect_output):
        """Allocate 1M Sets with periodic gc()."""
        expect_output('''
func main() -> int
    live: Set<int> = {999999}
    count: int = 0

    for i in 0..1000000
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
''', "1000000\n1\n")

    def test_1m_string_allocations(self, expect_output):
        """Allocate 1M strings with periodic gc()."""
        expect_output('''
func main() -> int
    live: string = "keeper"
    count: int = 0

    for i in 0..1000000
        temp: string = "x"
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
''', "1000000\n6\n")

    def test_1m_mixed_allocations(self, expect_output):
        """Mixed allocations of all types (250K each = 1M total)."""
        expect_output('''
func main() -> int
    live_list: List<int> = [1]
    live_map: Map<int, int> = {1: 1}
    live_set: Set<int> = {1}
    live_str: string = "x"
    count: int = 0

    for i in 0..250000
        t1: List<int> = [i, i + 1]
        t2: Map<int, int> = {(i): i}
        t3: Set<int> = {i, i + 1}
        t4: string = "a"
        count = count + 4
        if i % 250 == 0
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
''', "1000000\n1\n1\n1\n1\n")


class TestGCAsyncStress:
    """Stress tests using gc_async() with 1M allocations."""

    def test_100k_list_allocations_async(self, expect_output):
        """Allocate 100K Lists with periodic gc_async()."""
        expect_output('''
func main() -> int
    live: List<int> = [999]
    count: int = 0

    for i in 0..100000
        temp: List<int> = [i, i + 1, i + 2]
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

    def test_1m_map_allocations_async(self, expect_output):
        """Allocate 1M Maps with periodic gc_async()."""
        expect_output('''
func main() -> int
    live: Map<int, int> = {0: 0}
    count: int = 0

    for i in 0..1000000
        temp: Map<int, int> = {(i): i * 2}
        count = count + 1
        if i % 1000 == 0
            gc_async()
        ~
    ~

    gc()
    print(count)
    print(live.get(0))
    return 0
~
''', "1000000\n0\n")

    def test_1m_set_allocations_async(self, expect_output):
        """Allocate 1M Sets with periodic gc_async()."""
        expect_output('''
func main() -> int
    live: Set<int> = {999999}
    count: int = 0

    for i in 0..1000000
        temp: Set<int> = {i, i + 1, i + 2}
        count = count + 1
        if i % 1000 == 0
            gc_async()
        ~
    ~

    gc()
    print(count)
    print(live.len())
    return 0
~
''', "1000000\n1\n")


class TestGCUserTypesStress:
    """Stress tests with user-defined types at 1M scale."""

    def test_1m_user_type_allocations(self, expect_output):
        """Allocate 1M user-defined type instances."""
        expect_output('''
type Point:
    x: int
    y: int
~

func main() -> int
    live: Point = Point(x: 999, y: 888)
    count: int = 0

    for i in 0..1000000
        temp: Point = Point(x: i, y: i + 1)
        count = count + 1
        if i % 1000 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.x)
    print(live.y)
    return 0
~
''', "1000000\n999\n888\n")

    def test_500k_user_type_with_list_field(self, expect_output):
        """User types containing List fields - 500K complex heap graphs."""
        expect_output('''
type Container:
    items: List<int>
    id: int
~

func main() -> int
    live: Container = Container(items: [1, 2, 3], id: 999)
    count: int = 0

    for i in 0..500000
        temp: Container = Container(items: [i], id: i)
        count = count + 1
        if i % 500 == 0
            gc()
        ~
    ~

    gc()
    print(count)
    print(live.id)
    print(live.items.len())
    return 0
~
''', "500000\n999\n3\n")


class TestGCAutoTriggerStress:
    """Test automatic GC triggering without explicit gc() calls."""

    def test_1m_allocations_no_explicit_gc(self, expect_output):
        """1M allocations relying entirely on automatic GC at function entry."""
        expect_output('''
func allocate_temp(i: int) -> int
    temp: Map<int, int> = {(i): i * 2}
    return temp.get(i)
~

func main() -> int
    live: Map<int, int> = {0: 42}
    count: int = 0
    sum: int = 0

    for i in 0..1000000
        sum = sum + allocate_temp(i)
        count = count + 1
    ~

    print(count)
    print(live.get(0))
    return 0
~
''', "1000000\n42\n")

    def test_1m_nested_function_calls(self, expect_output):
        """Deep function call chains with allocations - tests safepoint frequency."""
        expect_output('''
func level3(i: int) -> int
    m: Map<int, int> = {(i): i}
    return 0
~

func level2(i: int) -> int
    s: Set<int> = {i}
    return level3(i) + s.len()
~

func level1(i: int) -> int
    l: List<int> = [i]
    return level2(i) + l.len()
~

func main() -> int
    count: int = 0

    for i in 0..500000
        count = count + level1(i)
    ~

    print(count)
    return 0
~
''', "1000000\n")
