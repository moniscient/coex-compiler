"""
Tests for BUG-018: GC stats atomic operations in multi-threaded case.

These tests verify that:
1. GC allocation statistics are accurate under concurrent allocations
2. Using atomic operations prevents lost increments
"""

import pytest
import re


class TestGCStatsAtomic:
    """Tests for atomic GC statistics updates."""

    def test_single_thread_stats_accurate(self, compile_coex):
        """Baseline: single-threaded allocation stats should be accurate."""
        result = compile_coex('''
func main() -> int
    # Allocate 100 lists
    for i in 0..100
        x = [1, 2, 3, 4, 5]
    ~
    gc_dump_stats()
    return 0
~
''')
        # Stats should show at least 100 allocations
        # (may be more due to list internal structures)
        assert "total_allocations:" in result.stdout
        match = re.search(r'total_allocations:\s*(\d+)', result.stdout)
        assert match, f"Could not find total_allocations in output: {result.stdout}"
        total_allocs = int(match.group(1))
        # At minimum 100 list allocations, possibly more for internal array storage
        assert total_allocs >= 100, f"Expected at least 100 allocations, got {total_allocs}"

    def test_concurrent_allocations_stats_consistent(self, compile_coex):
        """Multi-threaded allocations: stats should still be consistent.

        With the BUG-018 race condition, concurrent threads doing load-add-store
        on the same counter could lose updates. After the fix, atomic operations
        should prevent lost increments.
        """
        result = compile_coex('''
thread allocate_lists(count: int) -> int
    for i in 0..count
        x = [1, 2, 3]
    ~
    return count
~

func main() -> int
    # 8 threads, each allocating 100 lists = 800 allocations minimum
    indices: [int] = [0, 1, 2, 3, 4, 5, 6, 7]

    results = for idx in indices allocate_lists(100) ~

    total_expected = 0
    for r in results
        total_expected = total_expected + r
    ~

    gc_dump_stats()
    print(total_expected)
    return 0
~
''')
        assert result.run_success, f"Program failed: {result.stderr}"
        # Verify all threads completed
        assert "800" in result.stdout, f"Expected 800 from thread results, got: {result.stdout}"

        # Check allocation stats
        match = re.search(r'total_allocations:\s*(\d+)', result.stdout)
        if match:
            total_allocs = int(match.group(1))
            # We expect at least 800 allocations (8 threads * 100 lists each)
            # With race condition, we might see fewer due to lost updates
            # After fix, should see at least 800
            assert total_allocs >= 800, f"Possible race condition: expected >= 800 allocations, got {total_allocs}"

    def test_stress_concurrent_allocations(self, compile_coex):
        """Stress test: many threads allocating aggressively.

        This test increases the chance of observing the race condition
        before the fix is applied.
        """
        result = compile_coex('''
thread allocate_many(id: int, count: int) -> int
    for i in 0..count
        # Each iteration allocates a list
        x = [id, i, id + i]
    ~
    return count
~

func main() -> int
    # 16 threads, each allocating 500 lists = 8000 allocations minimum
    indices: [int] = []
    for i in 0..16
        indices = indices.append(i)
    ~

    results = for idx in indices allocate_many(idx, 500) ~

    total_returned = 0
    for r in results
        total_returned = total_returned + r
    ~

    gc_dump_stats()
    print(total_returned)
    return 0
~
''')
        assert result.run_success, f"Program failed: {result.stderr}"
        assert "8000" in result.stdout, f"Expected 8000 from results, got: {result.stdout}"

        match = re.search(r'total_allocations:\s*(\d+)', result.stdout)
        if match:
            total_allocs = int(match.group(1))
            # With race condition, concurrent updates could lose increments
            # After fix with atomic operations, should see >= 8000
            assert total_allocs >= 8000, f"Race condition detected: expected >= 8000, got {total_allocs}"
