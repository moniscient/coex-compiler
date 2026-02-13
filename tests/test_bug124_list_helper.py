"""
Tests for BUG-124: List append through helper function segfaults at high iteration count.

Root cause: In list_append's tail_full path, the `new_list` pointer from list_new
becomes stale after subsequent GC allocations (leaf buffers, PV_NODEs). The merge
block stores to the stale pointer, then returns it. The caller receives a stale
pointer, and gc_ptr_to_handle on it eventually fails.

Similarly, `leaf_data` pointers become stale after subsequent allocations and
are passed to gc_ptr_to_handle, which reads from potentially unmapped memory.
"""

import pytest


class TestListAppendThroughHelper:
    """Tests for list append via helper function under GC pressure."""

    def test_list_append_helper_small(self, expect_output):
        """Baseline: small iteration count works."""
        expect_output('''
func helper(x: [int]) -> [int]
    return x.append(1)
~

func main() -> int
    x: [int] = []
    i = 0
    while i < 100
        x = helper(x)
        i = i + 1
    ~
    print(x.len())
    return 0
~
''', "100\n")

    def test_list_append_helper_200k(self, expect_output):
        """BUG-124 repro: 200K iterations triggers GC compaction crash."""
        expect_output('''
func helper(x: [int]) -> [int]
    return x.append(1)
~

func main() -> int
    x: [int] = []
    i = 0
    while i < 200000
        x = helper(x)
        i = i + 1
    ~
    print(x.len())
    return 0
~
''', "200000\n")

    def test_list_append_inline_200k(self, expect_output):
        """Same pattern but inlined (no helper). Should also work."""
        expect_output('''
func main() -> int
    x: [int] = []
    i = 0
    while i < 200000
        x = x.append(1)
        i = i + 1
    ~
    print(x.len())
    return 0
~
''', "200000\n")


class TestListAppendTailFullPath:
    """Tests that exercise the tail_full path (>32 elements) with GC pressure."""

    def test_list_grow_past_32_with_gc(self, expect_output):
        """Grow list past 32 elements with explicit GC between tail fills."""
        expect_output('''
func main() -> int
    x: [int] = []
    i = 0
    while i < 100
        x = x.append(i)
        i = i + 1
    ~
    print(x.len())
    print(x.get(0))
    print(x.get(50))
    print(x.get(99))
    return 0
~
''', "100\n0\n50\n99\n")

    def test_list_data_integrity_after_gc_pressure(self, expect_output):
        """Verify list data is correct after many appends through helper."""
        expect_output('''
func add_elem(lst: [int], val: int) -> [int]
    return lst.append(val)
~

func main() -> int
    x: [int] = []
    i = 0
    while i < 10000
        x = add_elem(x, i)
        i = i + 1
    ~
    print(x.len())
    print(x.get(0))
    print(x.get(999))
    print(x.get(9999))
    return 0
~
''', "10000\n0\n999\n9999\n")

    def test_list_helper_returns_correct_data(self, expect_output):
        """Verify returned list has correct data across tree growth."""
        expect_output('''
func grow(x: [int], n: int) -> [int]
    return x.append(n)
~

func main() -> int
    x: [int] = []
    i = 0
    while i < 200000
        x = grow(x, i)
        i = i + 1
    ~
    print(x.get(0))
    print(x.get(100))
    print(x.get(99999))
    print(x.get(199999))
    return 0
~
''', "0\n100\n99999\n199999\n")
