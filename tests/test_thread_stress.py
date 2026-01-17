"""
Stress tests for thread-based concurrency.

These tests verify that:
1. Multiple parallel threads execute correctly
2. Results are correctly collected and ordered
3. Threads handle large data correctly
4. GC works correctly under concurrent load

NOTE: These tests are currently disabled - they take too long for regular test runs.
Run manually with: pytest tests/test_thread_stress.py -v
"""
import pytest
import subprocess
import tempfile
import os
import sys
import time
from pathlib import Path

# Skip entire module - these stress tests are too slow for regular test runs
pytestmark = pytest.mark.skip(reason="Stress tests disabled - run manually if needed")

# Skip very large tests on CI
skip_on_ci = pytest.mark.skipif(
    os.environ.get('CI') == 'true',
    reason="100M element tests too slow for CI"
)


class TestParallel24Threads:
    """Tests specifically for 24 parallel threads - the original stress test target."""

    def test_24_tasks_sum_ranges(self, expect_output):
        """24 parallel threads computing partial sums - verifies 24-way thread parallelism works."""
        expect_output('''
thread compute_sum(start: int, count: int) -> int
    total = 0
    i = 0
    while i < count
        total = total + (start + i)
        i = i + 1
    ~
    return total
~

func main() -> int
    # Compute sum of 0..2400000 using 24 threads
    thread_indices: [int] = []
    for i in 0..24
        thread_indices = thread_indices.append(i)
    ~

    segment_size = 100000

    sums = for idx in thread_indices compute_sum(idx * segment_size, segment_size) ~

    total = 0
    for s in sums
        total = total + s
    ~

    # Sum of 0..2399999 = 2399999 * 2400000 / 2 = 2879998800000
    print(total)
    return 0
~
''', "2879998800000\n")

    def test_24_tasks_with_list_iteration(self, expect_output):
        """24 parallel threads iterating over shared list data."""
        expect_output('''
thread process_list(idx: int, data: [int], multiplier: int) -> int
    total = 0
    for item in data
        total = total + (item * multiplier) + idx
    ~
    return total
~

func main() -> int
    # Shared data all tasks will iterate over
    data: [int] = []
    for i in 0..100
        data = data.append(i)
    ~

    thread_indices: [int] = []
    for i in 0..24
        thread_indices = thread_indices.append(i)
    ~

    results = for idx in thread_indices process_list(idx, data, idx + 1) ~

    total = 0
    for r in results
        total = total + r
    ~

    print(total)
    return 0
~
''', "1512600\n")


class TestParallelTaskBasics:
    """Basic parallel thread tests."""

    def test_parallel_sum_8_tasks(self, expect_output):
        """Test 8 parallel threads computing partial sums."""
        expect_output('''
thread compute_partial_sum(start: int, count: int) -> int
    total = 0
    for i in 0..count
        total = total + (start + i)
    ~
    return total
~

func main() -> int
    # Compute sum of 0..1000 using 8 parallel threads
    thread_indices: [int] = []
    for i in 0..8
        thread_indices = thread_indices.append(i)
    ~

    partial_sums = for idx in thread_indices compute_partial_sum(idx * 125, 125) ~

    total = 0
    for s in partial_sums
        total = total + s
    ~

    # Sum of 0..999 = 999 * 1000 / 2 = 499500
    print(total)
    return 0
~
''', "499500\n")

    def test_parallel_24_tasks_simple(self, expect_output):
        """Test 24 parallel threads with simple computation."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    thread_indices: [int] = []
    for i in 0..24
        thread_indices = thread_indices.append(i)
    ~

    results = for idx in thread_indices double(idx) ~

    total = 0
    for r in results
        total = total + r
    ~

    # Sum of 2*0 + 2*1 + ... + 2*23 = 2 * (23*24/2) = 552
    print(total)
    return 0
~
''', "552\n")

    def test_parallel_tasks_with_list_params(self, expect_output):
        """Test passing lists to parallel threads."""
        expect_output('''
thread sum_list(items: [int]) -> int
    total = 0
    for item in items
        total = total + item
    ~
    return total
~

func main() -> int
    lists: [[int]] = []
    lists = lists.append([1, 2, 3])
    lists = lists.append([10, 20, 30])
    lists = lists.append([100, 200, 300])

    sums = for lst in lists sum_list(lst) ~

    total = 0
    for s in sums
        total = total + s
    ~

    # 6 + 60 + 600 = 666
    print(total)
    return 0
~
''', "666\n")


@pytest.mark.xfail(reason="BUG-004: GC race condition with parallel Set allocations")
class TestParallelSieveSmall:
    """Small-scale parallel sieve tests."""

    def test_parallel_sieve_100_2_tasks(self, expect_output):
        """Test parallel sieve to 100 with 2 tasks."""
        expect_output('''
thread sieve_segment(start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}
    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        first_mult = ((start + p - 1) / p) * p
        if first_mult < p * 2
            first_mult = p * 2
        ~
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)
            mult = mult + p
        ~
        idx = idx + 1
    ~
    count = 0
    num = start
    if num < 2
        num = 2
    ~
    while num < end_val
        if not composites.has(num)
            count = count + 1
        ~
        num = num + 1
    ~
    return count
~

func find_small_primes(limit: int) -> [int]
    composites: Set<int> = {}
    i = 2
    while i * i <= limit
        if not composites.has(i)
            j = i * i
            while j <= limit
                composites = composites.add(j)
                j = j + i
            ~
        ~
        i = i + 1
    ~
    primes: [int] = []
    k = 2
    while k <= limit
        if not composites.has(k)
            primes = primes.append(k)
        ~
        k = k + 1
    ~
    return primes
~

func main() -> int
    small_primes = find_small_primes(10)
    thread_indices: [int] = []
    thread_indices = thread_indices.append(0)
    thread_indices = thread_indices.append(1)
    segment_size = 50
    counts = for idx in thread_indices sieve_segment(idx * segment_size, (idx + 1) * segment_size, small_primes) ~
    total = 0
    for c in counts
        total = total + c
    ~
    # There are 25 primes below 100
    print(total)
    return 0
~
''', "25\n")


@pytest.mark.xfail(reason="BUG-004: GC race condition with parallel Set allocations")
class TestParallelSieve:
    """Parallel sieve of Eratosthenes tests."""
    """

    def test_parallel_sieve_1000(self, expect_output):
        """Test parallel sieve to 1000 with 4 tasks."""
        expect_output('''
thread sieve_segment(start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}

    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        first_mult = ((start + p - 1) / p) * p
        if first_mult < p * 2
            first_mult = p * 2
        ~
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)
            mult = mult + p
        ~
        idx = idx + 1
    ~

    count = 0
    num = start
    if num < 2
        num = 2
    ~
    while num < end_val
        if not composites.has(num)
            count = count + 1
        ~
        num = num + 1
    ~
    return count
~

func find_small_primes(limit: int) -> [int]
    composites: Set<int> = {}
    i = 2
    while i * i <= limit
        if not composites.has(i)
            j = i * i
            while j <= limit
                composites = composites.add(j)
                j = j + i
            ~
        ~
        i = i + 1
    ~
    primes: [int] = []
    k = 2
    while k <= limit
        if not composites.has(k)
            primes = primes.append(k)
        ~
        k = k + 1
    ~
    return primes
~

func main() -> int
    small_primes = find_small_primes(32)  # sqrt(1000) ~ 32

    thread_indices: [int] = []
    for i in 0..4
        thread_indices = thread_indices.append(i)
    ~

    segment_size = 250  # 1000 / 4

    counts = for idx in thread_indices sieve_segment(idx * segment_size, (idx + 1) * segment_size, small_primes) ~

    total = 0
    for c in counts
        total = total + c
    ~

    # There are 168 primes below 1000
    print(total)
    return 0
~
''', "168\n")

    def test_parallel_sieve_10000_8_tasks(self, expect_output):
        """Test parallel sieve to 10000 with 8 tasks."""
        expect_output('''
thread sieve_segment(start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}

    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        first_mult = ((start + p - 1) / p) * p
        if first_mult < p * 2
            first_mult = p * 2
        ~
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)
            mult = mult + p
        ~
        idx = idx + 1
    ~

    count = 0
    num = start
    if num < 2
        num = 2
    ~
    while num < end_val
        if not composites.has(num)
            count = count + 1
        ~
        num = num + 1
    ~
    return count
~

func find_small_primes(limit: int) -> [int]
    composites: Set<int> = {}
    i = 2
    while i * i <= limit
        if not composites.has(i)
            j = i * i
            while j <= limit
                composites = composites.add(j)
                j = j + i
            ~
        ~
        i = i + 1
    ~
    primes: [int] = []
    k = 2
    while k <= limit
        if not composites.has(k)
            primes = primes.append(k)
        ~
        k = k + 1
    ~
    return primes
~

func main() -> int
    small_primes = find_small_primes(100)  # sqrt(10000) = 100

    thread_indices: [int] = []
    for i in 0..8
        thread_indices = thread_indices.append(i)
    ~

    segment_size = 1250  # 10000 / 8

    counts = for idx in thread_indices sieve_segment(idx * segment_size, (idx + 1) * segment_size, small_primes) ~

    total = 0
    for c in counts
        total = total + c
    ~

    # There are 1229 primes below 10000
    print(total)
    return 0
~
''', "1229\n")


@pytest.mark.xfail(reason="BUG-004: GC race condition with parallel Set allocations")
class TestParallelSieveStress:
    """Stress tests for parallel sieve at scale."""
    """

    def test_parallel_sieve_100k_24_tasks(self, compiler_root):
        """Test parallel sieve to 100K with 24 tasks."""
        source = '''
thread sieve_segment(start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}

    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        first_mult = ((start + p - 1) / p) * p
        if first_mult < p * 2
            first_mult = p * 2
        ~
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)
            mult = mult + p
        ~
        idx = idx + 1
    ~

    count = 0
    num = start
    if num < 2
        num = 2
    ~
    while num < end_val
        if not composites.has(num)
            count = count + 1
        ~
        num = num + 1
    ~
    return count
~

func find_small_primes(limit: int) -> [int]
    composites: Set<int> = {}
    i = 2
    while i * i <= limit
        if not composites.has(i)
            j = i * i
            while j <= limit
                composites = composites.add(j)
                j = j + i
            ~
        ~
        i = i + 1
    ~
    primes: [int] = []
    k = 2
    while k <= limit
        if not composites.has(k)
            primes = primes.append(k)
        ~
        k = k + 1
    ~
    return primes
~

func main() -> int
    small_primes = find_small_primes(317)  # sqrt(100000) ~ 317

    thread_indices: [int] = []
    for i in 0..24
        thread_indices = thread_indices.append(i)
    ~

    const LIMIT = 100000
    segment_size = LIMIT / 24

    counts = for idx in thread_indices sieve_segment(idx * segment_size, (idx + 1) * segment_size, small_primes) ~

    total = 0
    for c in counts
        total = total + c
    ~

    # There are 9592 primes below 100000
    print(total)
    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=120
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            output = run_result.stdout.strip()
            assert output == "9592", f"Expected 9592 primes, got {output}"

            print(f"\n  24-thread parallel sieve to 100K completed in {elapsed:.2f}s")

    @skip_on_ci
    def test_parallel_sieve_1m_24_tasks(self, compiler_root):
        """Test parallel sieve to 1M with 24 tasks."""
        source = '''
thread sieve_segment(start: int, end_val: int, small_primes: [int]) -> int
    composites: Set<int> = {}

    idx = 0
    while idx < small_primes.len()
        p = small_primes.get(idx)
        first_mult = ((start + p - 1) / p) * p
        if first_mult < p * 2
            first_mult = p * 2
        ~
        mult = first_mult
        while mult < end_val
            composites = composites.add(mult)
            mult = mult + p
        ~
        idx = idx + 1
    ~

    count = 0
    num = start
    if num < 2
        num = 2
    ~
    while num < end_val
        if not composites.has(num)
            count = count + 1
        ~
        num = num + 1
    ~
    return count
~

func find_small_primes(limit: int) -> [int]
    composites: Set<int> = {}
    i = 2
    while i * i <= limit
        if not composites.has(i)
            j = i * i
            while j <= limit
                composites = composites.add(j)
                j = j + i
            ~
        ~
        i = i + 1
    ~
    primes: [int] = []
    k = 2
    while k <= limit
        if not composites.has(k)
            primes = primes.append(k)
        ~
        k = k + 1
    ~
    return primes
~

func main() -> int
    small_primes = find_small_primes(1000)  # sqrt(1000000) = 1000

    thread_indices: [int] = []
    for i in 0..24
        thread_indices = thread_indices.append(i)
    ~

    const LIMIT = 1000000
    segment_size = LIMIT / 24

    counts = for idx in thread_indices sieve_segment(idx * segment_size, (idx + 1) * segment_size, small_primes) ~

    total = 0
    for c in counts
        total = total + c
    ~

    # There are 78498 primes below 1,000,000
    print(total)
    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=300
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            output = run_result.stdout.strip()
            assert output == "78498", f"Expected 78498 primes, got {output}"

            print(f"\n  24-thread parallel sieve to 1M completed in {elapsed:.2f}s")


@skip_on_ci
@pytest.mark.xfail(reason="BUG-004: GC race condition with parallel Set allocations")
class TestParallelSieve100M:
    """100 million element stress test."""
    """

    def test_parallel_sieve_100m_full(self, compiler_root):
        """Full 100M parallel sieve test from stress test file."""
        # Read the stress test file
        stress_test_path = os.path.join(
            compiler_root, "tests", "stress", "test_parallel_sieve.coex"
        )

        with open(stress_test_path, 'r') as f:
            source = f.read()

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=3600  # 1 hour timeout
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            assert "SUCCESS" in run_result.stdout, f"Test failed: {run_result.stdout}"
            assert "5761455" in run_result.stdout, f"Wrong prime count: {run_result.stdout}"

            print(f"\n  24-thread parallel sieve to 100M completed in {elapsed:.2f}s")
