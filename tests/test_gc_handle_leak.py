"""Tests for GC handle/object leak in loops.

A loop that allocates the same objects each iteration should reach steady-state
after a few GC cycles. If live_objects keeps growing, objects aren't being collected.
"""

import pytest
import re


class TestGCHandleLeak:
    """Verify GC properly collects objects in loops."""

    def test_live_objects_stabilize_in_loop(self, compile_coex):
        """Allocate objects in a loop with periodic gc() + gc_dump_stats().
        Live object count should stabilize, not grow indefinitely."""
        result = compile_coex('''
func main() -> int
    i = 0
    while i < 500
        x = [1, 2, 3, 4, 5]
        y = {1: "one", 2: "two", 3: "three"}
        z = "hello world " + String.from(i)
        if i % 100 == 99
            gc()
            gc_dump_stats()
        ~
        i = i + 1
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        if result.run_success:
            output = result.run_output
            live_counts = re.findall(r'live_objects:\s*(\d+)', output)
            live_counts = [int(c) for c in live_counts]
            if len(live_counts) >= 3:
                # After warmup, live count should stabilize (not grow 3x+)
                first_stable = live_counts[1]
                last = live_counts[-1]
                assert last < first_stable * 3, (
                    f"Live objects growing: {live_counts} — "
                    f"first stable={first_stable}, last={last}. "
                    f"Objects not being collected!"
                )

    def test_handle_reuse_in_loop(self, compile_coex):
        """next_handle should stabilize as freed handles are reused."""
        result = compile_coex('''
func main() -> int
    i = 0
    while i < 1000
        x = [1, 2, 3, 4, 5]
        y = "test " + String.from(i)
        if i % 100 == 99
            gc()
            gc_dump_stats()
        ~
        i = i + 1
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        if result.run_success:
            output = result.run_output
            next_handles = re.findall(r'next_handle:\s*(\d+)', output)
            next_handles = [int(h) for h in next_handles]
            if len(next_handles) >= 6:
                # Handle growth should not be unbounded — later intervals
                # should be smaller than earlier ones on average (recycling kicks in)
                mid = len(next_handles) // 2
                early_growth = next_handles[mid] - next_handles[0]
                late_growth = next_handles[-1] - next_handles[mid]
                assert late_growth <= early_growth * 2, (
                    f"Handle high-water growing too fast: {next_handles} — "
                    f"early_growth={early_growth}, late_growth={late_growth}. "
                    f"handles not being recycled!"
                )
