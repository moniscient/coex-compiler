"""
Lock-free GC allocation tests.

These tests verify that GC allocation does not use blocking locks that
cause threads to wait on each other. If a fix to the GC race condition
introduces a mutex that serializes allocations, these tests will fail.

DESIGN PHILOSOPHY:
- Tests compare parallel vs sequential throughput
- If allocation is lock-free, parallel should achieve speedup
- If allocation uses blocking mutex, parallel will be serialized

The key insight: with N threads and a blocking mutex, parallel throughput
will be approximately equal to sequential throughput (no speedup).
With lock-free allocation, we should see significant speedup.

IMPORTANT: These tests are designed to FAIL if a GC fix introduces
blocking/mutex that halts other threads. Currently some tests are marked
xfail because the existing GC has a race condition with Sets (BUG-004).
Once the race is fixed with a lock-free solution, all tests should PASS.
If the fix uses a blocking mutex, the tests will FAIL (no speedup).

See BUG-005 for posix.time_ns() issues - these tests use posix.time() instead.
"""
import pytest
import subprocess
import tempfile
import os
import sys
from pathlib import Path


class TestSingleThreadedBaseline:
    """
    Single-threaded baseline tests.

    These verify the test infrastructure works and establish baseline behavior.
    Should always pass regardless of GC implementation.
    """

    def test_baseline_allocation_completes(self, expect_output):
        """
        Single thread doing allocations.
        Just verifies allocations work at all.
        """
        expect_output('''
func main() -> int
    count = 0
    i = 0
    while i < 10000
        arr: [int] = []
        arr = arr.append(i)
        arr = arr.append(i + 1)
        count = count + 1
        i = i + 1
    ~
    print(count)
    return 0
~
''', "10000\n")


class TestParallelThroughputArrays:
    """
    Tests that compare parallel vs sequential throughput using Arrays.

    Arrays are simpler than HAMT-based Sets and avoid the existing race condition.
    These tests verify the parallel allocation infrastructure works.
    """

    def test_parallel_array_speedup(self, expect_output):
        """
        Compare parallel vs sequential array allocation throughput.

        If allocation is lock-free, parallel should be significantly faster.
        If allocation is serialized, parallel time will be similar to sequential.

        PASS: Parallel achieves at least 1.5x speedup (being conservative)
        FAIL: No significant speedup (indicates serialization)
        """
        expect_output('''
thread parallel_work(thread_id: int, iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        arr: [int] = []
        j = 0
        while j < 10
            arr = arr.append(i * 10 + j)
            j = j + 1
        ~
        count = count + arr.len()
        i = i + 1
    ~
    return count
~

func sequential_work(iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        arr: [int] = []
        j = 0
        while j < 10
            arr = arr.append(i * 10 + j)
            j = j + 1
        ~
        count = count + arr.len()
        i = i + 1
    ~
    return count
~

func main() -> int
    ops_per_thread = 50000
    num_threads = 8

    # Measure sequential time (run num_threads iterations sequentially)
    seq_start = posix.time()
    seq_total = 0
    t = 0
    while t < num_threads
        seq_total = seq_total + sequential_work(ops_per_thread)
        t = t + 1
    ~
    seq_end = posix.time()
    seq_time = seq_end - seq_start

    # Measure parallel time
    thread_ids: [int] = []
    for i in 0..num_threads
        thread_ids = thread_ids.append(i)
    ~

    par_start = posix.time()
    results = for id in thread_ids parallel_work(id, ops_per_thread) ~
    par_end = posix.time()
    par_time = par_end - par_start

    par_total = 0
    for r in results
        par_total = par_total + r
    ~

    # Verify correctness - both should produce same total
    if seq_total != par_total
        print("ERROR: results mismatch")
        print(seq_total)
        print(par_total)
        return 1
    ~

    # Print timing info
    print(seq_time)
    print(par_time)

    # Ensure we ran long enough to measure (at least 1 second sequential)
    if seq_time < 1
        print("SKIP: workload too fast to measure")
        return 0
    ~

    # Avoid division by zero
    if par_time == 0
        par_time = 1
    ~

    # Calculate speedup * 10 (to avoid floats)
    speedup_x10 = (seq_time * 10) / par_time

    print(speedup_x10)

    # PASS: speedup >= 1.5x (speedup_x10 >= 15)
    # This is conservative - true lock-free should see much higher speedup
    # But 1.5x rules out complete serialization
    if speedup_x10 >= 15
        print("PASS")
        return 0
    else
        print("FAIL: parallel not faster than sequential")
        return 1
    ~
~
''', "PASS", partial=True)


class TestParallelThroughputSets:
    """
    Tests that compare parallel vs sequential throughput using Sets (HAMT).

    These tests exercise the code path with the known race condition.
    Currently xfail because of the race condition.

    After the race is fixed:
    - If fixed with lock-free solution: tests should PASS
    - If fixed with blocking mutex: tests should FAIL (no speedup)
    """

    def test_parallel_set_speedup(self, expect_output):
        """
        Compare parallel vs sequential Set allocation throughput.

        PASS: Parallel achieves at least 1.5x speedup
        FAIL: No significant speedup (indicates serialization)
        """
        expect_output('''
thread parallel_set_work(thread_id: int, iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        s: Set<int> = {}
        j = 0
        while j < 10
            s = s.add(thread_id * 1000000 + i * 10 + j)
            j = j + 1
        ~
        count = count + s.len()
        i = i + 1
    ~
    return count
~

func sequential_set_work(iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        s: Set<int> = {}
        j = 0
        while j < 10
            s = s.add(i * 10 + j)
            j = j + 1
        ~
        count = count + s.len()
        i = i + 1
    ~
    return count
~

func main() -> int
    ops_per_thread = 2000
    num_threads = 8

    # Measure sequential time
    seq_start = posix.time()
    seq_total = 0
    t = 0
    while t < num_threads
        seq_total = seq_total + sequential_set_work(ops_per_thread)
        t = t + 1
    ~
    seq_end = posix.time()
    seq_time = seq_end - seq_start

    # Measure parallel time
    thread_ids: [int] = []
    for i in 0..num_threads
        thread_ids = thread_ids.append(i)
    ~

    par_start = posix.time()
    results = for id in thread_ids parallel_set_work(id, ops_per_thread) ~
    par_end = posix.time()
    par_time = par_end - par_start

    par_total = 0
    for r in results
        par_total = par_total + r
    ~

    # Verify correctness
    if seq_total != par_total
        print("ERROR: results mismatch")
        return 1
    ~

    print(seq_time)
    print(par_time)

    if seq_time < 1
        print("SKIP: workload too fast")
        return 0
    ~

    if par_time == 0
        par_time = 1
    ~

    speedup_x10 = (seq_time * 10) / par_time
    print(speedup_x10)

    if speedup_x10 >= 15
        print("PASS")
        return 0
    else
        print("FAIL: parallel not faster")
        return 1
    ~
~
''', "PASS", partial=True)

    def test_parallel_map_speedup(self, expect_output):
        """
        Compare parallel vs sequential Map allocation throughput.

        PASS: Parallel achieves at least 1.5x speedup
        FAIL: No significant speedup
        """
        expect_output('''
thread parallel_map_work(thread_id: int, iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        m: Map<int, int> = {}
        j = 0
        while j < 10
            key = thread_id * 1000000 + i * 10 + j
            m = m.put(key, j)
            j = j + 1
        ~
        count = count + m.len()
        i = i + 1
    ~
    return count
~

func sequential_map_work(iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        m: Map<int, int> = {}
        j = 0
        while j < 10
            m = m.put(i * 10 + j, j)
            j = j + 1
        ~
        count = count + m.len()
        i = i + 1
    ~
    return count
~

func main() -> int
    ops_per_thread = 2000
    num_threads = 8

    seq_start = posix.time()
    seq_total = 0
    t = 0
    while t < num_threads
        seq_total = seq_total + sequential_map_work(ops_per_thread)
        t = t + 1
    ~
    seq_end = posix.time()
    seq_time = seq_end - seq_start

    thread_ids: [int] = []
    for i in 0..num_threads
        thread_ids = thread_ids.append(i)
    ~

    par_start = posix.time()
    results = for id in thread_ids parallel_map_work(id, ops_per_thread) ~
    par_end = posix.time()
    par_time = par_end - par_start

    par_total = 0
    for r in results
        par_total = par_total + r
    ~

    if seq_total != par_total
        print("ERROR: results mismatch")
        return 1
    ~

    print(seq_time)
    print(par_time)

    if seq_time < 1
        print("SKIP: workload too fast")
        return 0
    ~

    if par_time == 0
        par_time = 1
    ~

    speedup_x10 = (seq_time * 10) / par_time
    print(speedup_x10)

    if speedup_x10 >= 15
        print("PASS")
        return 0
    else
        print("FAIL: parallel not faster")
        return 1
    ~
~
''', "PASS", partial=True)


class TestHighContentionScenario:
    """
    Tests with maximum contention to stress-test lock-free allocation.

    All tasks start simultaneously via an atomic barrier, maximizing
    the chance of contention. If there's a mutex, this will show it.
    """

    def test_synchronized_start_throughput(self, expect_output):
        """
        All tasks start allocating at the same instant.

        Uses an atomic barrier to synchronize thread start times.
        With a mutex, this creates maximum contention.

        PASS: Achieves at least 1.5x speedup despite contention
        FAIL: Serialized due to mutex contention
        """
        expect_output('''
thread contention_work(thread_id: int, barrier: atomic_int, num_threads: int, iterations: int) -> int
    # Signal ready
    barrier.fetch_add(1)

    # Spin until all tasks ready
    while barrier.load() < num_threads
        x = 0
    ~

    # Now all tasks allocate simultaneously
    count = 0
    i = 0
    while i < iterations
        arr: [int] = []
        j = 0
        while j < 10
            arr = arr.append(thread_id * 1000000 + i * 10 + j)
            j = j + 1
        ~
        count = count + arr.len()
        i = i + 1
    ~
    return count
~

func sequential_work(iterations: int) -> int
    count = 0
    i = 0
    while i < iterations
        arr: [int] = []
        j = 0
        while j < 10
            arr = arr.append(i * 10 + j)
            j = j + 1
        ~
        count = count + arr.len()
        i = i + 1
    ~
    return count
~

func main() -> int
    ops_per_thread = 50000
    num_threads = 8
    barrier: atomic_int = 0

    # Sequential baseline
    seq_start = posix.time()
    seq_total = 0
    t = 0
    while t < num_threads
        seq_total = seq_total + sequential_work(ops_per_thread)
        t = t + 1
    ~
    seq_end = posix.time()
    seq_time = seq_end - seq_start

    # Parallel with synchronized start
    thread_ids: [int] = []
    for i in 0..num_threads
        thread_ids = thread_ids.append(i)
    ~

    par_start = posix.time()
    results = for id in thread_ids contention_work(id, barrier, num_threads, ops_per_thread) ~
    par_end = posix.time()
    par_time = par_end - par_start

    par_total = 0
    for r in results
        par_total = par_total + r
    ~

    if seq_total != par_total
        print("ERROR: mismatch")
        return 1
    ~

    print(seq_time)
    print(par_time)

    if seq_time < 1
        print("SKIP: too fast")
        return 0
    ~

    if par_time == 0
        par_time = 1
    ~

    speedup_x10 = (seq_time * 10) / par_time
    print(speedup_x10)

    if speedup_x10 >= 15
        print("PASS")
        return 0
    else
        print("FAIL: contention caused serialization")
        return 1
    ~
~
''', "PASS", partial=True)


# Current GC uses mutex for handle allocation, causing parallel slowdown
# These tests detect this blocking behavior and fail appropriately.
# After implementing lock-free allocation, these tests should PASS.
# If the fix uses a different blocking approach, these tests should still FAIL.

TestParallelThroughputArrays = pytest.mark.xfail(
    reason="GC mutex serializes allocation - parallel is slower than sequential"
)(TestParallelThroughputArrays)

# Mark HAMT-based tests (Sets, Maps) as xfail due to existing race condition
TestParallelThroughputSets = pytest.mark.xfail(
    reason="GC race condition with parallel HAMT allocations"
)(TestParallelThroughputSets)

# High contention test may deadlock with current GC
TestHighContentionScenario = pytest.mark.xfail(
    reason="Synchronized start may deadlock with current GC mutex"
)(TestHighContentionScenario)
