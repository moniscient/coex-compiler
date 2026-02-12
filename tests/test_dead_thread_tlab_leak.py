"""Tests for BUG-122: Dead task thread TLABs never freed — memory leak.

Verifies that after task threads complete and their objects become unreachable,
GC correctly sweeps the dead thread's allocations and reclaims TLABs.

NOTE: gc() is async — it signals the GC thread and returns immediately.
To ensure GC actually runs, tests must allocate enough on the main thread
to trigger the safepoint threshold (100K allocations). The churn() helper
function generates allocation pressure to force GC cycles.
"""

import pytest
import re


class TestDeadThreadSweep:
    """Tests that GC sweeps objects allocated by dead task threads."""

    def test_dead_thread_objects_swept(self, expect_output):
        """Objects allocated by a dead task thread should be swept after GC cycles."""
        expect_output('''
task allocator(n: int) -> int
    garbage = [0]
    i = 0
    while i < n
        garbage = garbage.append(i)
        i = i + 1
    ~
    return garbage.len()
~

func main() -> int
    result := allocator(100)
    print(result)
    gc()
    gc()
    gc()
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "101\n0\n")

    def test_many_dead_threads_objects_swept(self, expect_output):
        """Multiple dead task threads' objects should all be swept."""
        expect_output('''
task worker(id: int) -> int
    data = [0]
    i = 0
    while i < 50
        data = data.append(id * 100 + i)
        i = i + 1
    ~
    return data.len()
~

func main() -> int
    total = 0
    i = 0
    while i < 10
        r := worker(i)
        total = total + r
        i = i + 1
    ~
    print(total)
    gc()
    gc()
    gc()
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "510\n0\n")

    def test_dead_thread_strings_swept(self, expect_output):
        """String objects allocated by dead task threads should be swept."""
        expect_output('''
task string_maker(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    s := string_maker(50)
    print(s.len())
    gc()
    gc()
    gc()
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''', "50\n0\n")


class TestDeadThreadTLABReclamation:
    """Tests that TLABs from dead threads are eventually munmapped."""

    def test_dead_thread_tlab_reclaimed_after_gc(self, compile_coex):
        """After tasks complete and GC runs, swept count should include
        dead thread objects (verifying dead thread alloc_lists are swept).

        Uses churn() to generate enough allocation pressure to trigger
        GC via safepoint (threshold = 100K allocations)."""
        result = compile_coex('''
task heavy_allocator(n: int) -> int
    data = [0]
    i = 0
    while i < n
        data = data.append(i)
        i = i + 1
    ~
    return data.len()
~

func churn(n: int) -> int
    total = 0
    i = 0
    while i < n
        temp = [i, i+1, i+2]
        total = total + temp.get(0)
        i = i + 1
    ~
    return total
~

func main() -> int
    r := heavy_allocator(200)
    print(r)
    # Generate enough allocations to trigger 2+ GC cycles via safepoint
    ignore = churn(120000)
    gc_dump_stats()
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Run failed (rc={result.returncode}): stdout={result.run_output!r} stderr={result.stderr!r}"
        # Parse swept count from gc_dump_stats output
        swept_match = re.search(r'swept:\s*(\d+)', result.run_output)
        assert swept_match, f"Could not find swept count in output:\n{result.run_output}"
        swept = int(swept_match.group(1))
        # The dead task thread's ~200 list nodes + intermediate objects should be swept
        assert swept > 0, (
            f"Expected swept > 0 (dead thread objects should be swept), "
            f"got swept={swept}.\nOutput:\n{result.run_output}"
        )

    def test_sequential_tasks_dont_leak_handles(self, compile_coex):
        """Running many sequential tasks should not cause handle exhaustion.
        If dead thread handles are never retired, the handle table grows unbounded."""
        result = compile_coex('''
task small_work(n: int) -> int
    s = "hello_" + String.from(n)
    return s.len()
~

func churn(n: int) -> int
    total = 0
    i = 0
    while i < n
        temp = [i, i+1, i+2]
        total = total + temp.get(0)
        i = i + 1
    ~
    return total
~

func main() -> int
    total = 0
    i = 0
    while i < 100
        r := small_work(i)
        total = total + r
        i = i + 1
    ~
    print(total)
    # Trigger GC to sweep dead thread objects
    ignore = churn(120000)
    gc_dump_stats()
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Run failed (returncode={result.returncode}): stdout={result.run_output!r} stderr={result.stderr!r}"
        assert "0\n" in result.run_output, f"Heap validation errors:\n{result.run_output}"


class TestDeadThreadStress:
    """Stress tests for dead thread memory reclamation."""

    @pytest.mark.timeout(120)
    def test_many_tasks_memory_bounded(self, compile_coex):
        """Spawning many sequential tasks should not cause unbounded memory growth.
        Each task allocates ~50 list nodes. With proper cleanup, swept counts
        should grow roughly proportionally to allocations."""
        result = compile_coex('''
task allocate_and_discard(n: int) -> int
    data = [0]
    i = 0
    while i < 50
        data = data.append(i + n)
        i = i + 1
    ~
    return data.len()
~

func churn(n: int) -> int
    total = 0
    i = 0
    while i < n
        temp = [i, i+1, i+2]
        total = total + temp.get(0)
        i = i + 1
    ~
    return total
~

func main() -> int
    total = 0
    i = 0
    while i < 50
        r := allocate_and_discard(i)
        total = total + r
        i = i + 1
    ~
    print(total)
    # Trigger GC to sweep dead thread objects
    ignore = churn(120000)
    gc_dump_stats()
    errors = gc_validate_heap()
    print(errors)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        assert result.run_success, f"Run failed (returncode={result.returncode}): stdout={result.run_output!r} stderr={result.stderr!r}"
        # 50 tasks * 51 elements each = 2550
        assert "2550\n" in result.run_output
        # Verify heap is valid
        lines = result.run_output.strip().split('\n')
        # Last line should be "0" (from gc_validate_heap)
        assert lines[-1] == "0", f"Heap validation errors:\n{result.run_output}"
        # Check that swept count is non-trivial (dead thread objects were cleaned)
        swept_match = re.search(r'swept:\s*(\d+)', result.run_output)
        if swept_match:
            swept = int(swept_match.group(1))
            assert swept > 50, (
                f"Expected substantial swept count from 50 dead task threads, "
                f"got swept={swept}. Dead thread objects may not be getting swept.\n"
                f"Output:\n{result.run_output}"
            )


class TestRegistryIntegrity:
    """Tests that the thread registry remains intact after task thread death."""

    def test_main_thread_roots_scanned_after_task_death(self, expect_output):
        """After a task thread dies, the main thread's roots must still be
        scanned during GC. This verifies the registry isn't corrupted by
        dead thread unlinking."""
        expect_output('''
task do_work(n: int) -> int
    temp = [1, 2, 3]
    return temp.len() + n
~

func churn(n: int) -> int
    total = 0
    i = 0
    while i < n
        temp = [i, i+1, i+2]
        total = total + temp.get(0)
        i = i + 1
    ~
    return total
~

func main() -> int
    # Create a list on the main thread BEFORE the task
    live_data = [10, 20, 30, 40, 50]

    # Run a task (creates and destroys a thread)
    r := do_work(7)

    # Trigger GC — main thread's roots must be scanned
    # to keep live_data alive
    ignore = churn(120000)

    # If registry was corrupted, live_data may have been swept
    print(live_data.get(0))
    print(live_data.get(4))
    print(r)
    return 0
~
''', "10\n50\n10\n")

    def test_multiple_task_deaths_dont_corrupt_registry(self, expect_output):
        """Multiple sequential task deaths should not corrupt the registry,
        allowing GC to still scan and sweep the main thread correctly."""
        expect_output('''
task worker(id: int) -> int
    s = "task_" + String.from(id)
    return s.len()
~

func churn(n: int) -> int
    total = 0
    i = 0
    while i < n
        temp = [i, i+1, i+2]
        total = total + temp.get(0)
        i = i + 1
    ~
    return total
~

func main() -> int
    live = [100, 200, 300]

    # Spawn and await many tasks
    total = 0
    i = 0
    while i < 20
        r := worker(i)
        total = total + r
        i = i + 1
    ~

    # Trigger GC after all task threads are dead
    ignore = churn(120000)

    # Main thread data must survive
    print(live.get(0))
    print(live.get(2))
    print(total)
    return 0
~
''', "100\n300\n130\n")
