"""Tests for BUG-123: alloc_node pool to eliminate malloc/free churn.

Verifies that alloc_nodes are recycled via the lock-free pool instead of
being malloc'd/free'd on every GC cycle, which caused RSS growth on macOS.
"""
import re
import pytest


class TestAllocNodePool:
    """Test that alloc_node pool recycles nodes across GC cycles."""

    def test_node_pool_reuse_grows(self, compile_coex):
        """After GC cycles, node_pool_reuse counter should be nonzero."""
        result = compile_coex('''
func churn(n: int) -> int
    i = 0
    total = 0
    while i < n
        x = [1, 2, 3, 4, 5]
        total = total + x.len()
        i = i + 1
    ~
    return total
~

func main() -> int
    churn(120000)
    gc_dump_stats()
    churn(120000)
    gc_dump_stats()
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Run failed: {result.run_output}"
        output = result.run_output

        reuse_counts = re.findall(r'node_pool_reuse:\s*(\d+)', output)
        assert len(reuse_counts) >= 2, f"Expected 2+ pool stats, got: {output}"

        reuse_values = [int(c) for c in reuse_counts]
        # After first GC cycle, pool should have nodes to reuse
        # Second dump should show more reuse than first
        assert reuse_values[-1] > 0, (
            f"Pool reuse counter is 0 — nodes not being recycled: {reuse_values}"
        )
        assert reuse_values[-1] > reuse_values[0], (
            f"Pool reuse not growing between GC cycles: {reuse_values}"
        )

    def test_node_pool_stress(self, compile_coex):
        """Under heavy allocation, pool reuse should be substantial."""
        result = compile_coex('''
func churn(n: int) -> int
    i = 0
    total = 0
    while i < n
        x = [i, i+1, i+2]
        y = {1: "a", 2: "b"}
        total = total + x.len() + y.len()
        i = i + 1
    ~
    return total
~

func main() -> int
    churn(200000)
    gc_dump_stats()
    print(0)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Run failed: {result.run_output}"
        output = result.run_output

        reuse_counts = re.findall(r'node_pool_reuse:\s*(\d+)', output)
        assert len(reuse_counts) >= 1, f"No pool stats in output: {output}"

        reuse = int(reuse_counts[0])
        # With 200K iterations creating multiple objects each,
        # after GC sweeps recycle nodes, reuse should be significant
        assert reuse > 1000, (
            f"Pool reuse too low ({reuse}) for 200K iterations — "
            f"pool may not be working"
        )

    def test_basic_gc_still_works_with_pool(self, expect_output):
        """Ensure basic GC correctness is not affected by node pooling."""
        expect_output('''
func main() -> int
    x = [1, 2, 3]
    gc()
    y = [4, 5, 6]
    gc()
    print(x.len())
    print(y.len())
    return 0
~
''', "3\n3\n")
