"""
Stress tests for the work-stealing scheduler.

These tests exercise edge cases and high-load scenarios:
- High parallelism (many concurrent tasks)
- Work-stealing contention
- Deque growth under load
- Deep recursion (stack/frame pressure)
- Mixed workloads (load imbalance)
- First/Most batch operations at scale
- Multiple independent task trees
"""

import pytest


class TestHighParallelism:
    """Tests with many concurrent tasks to stress worker pool."""

    def test_wide_fan_out_100_tasks(self, expect_output):
        """100 concurrent leaf tasks from single coordinator."""
        expect_output('''
task leaf(x: int) -> int
    return x
~

task coordinator() -> int
    total = 0
    for i in 0..100
        result := leaf(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "4950\n")

    def test_wide_fan_out_500_tasks(self, expect_output):
        """500 concurrent leaf tasks - stress global queue and stealing."""
        expect_output('''
task leaf(x: int) -> int
    return x
~

task coordinator() -> int
    total = 0
    for i in 0..500
        result := leaf(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "124750\n")  # sum(0..499) = 124750

    def test_wide_fan_out_1000_tasks(self, expect_output):
        """1000 concurrent leaf tasks - major stress test."""
        expect_output('''
task leaf(x: int) -> int
    return x
~

task coordinator() -> int
    total = 0
    for i in 0..1000
        result := leaf(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "499500\n")  # sum(0..999) = 499500


class TestDeepRecursion:
    """Tests with deep recursive task trees."""

    def test_fibonacci_15(self, expect_output):
        """fib(15) = 610, creates ~1973 tasks."""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a := fib(n - 1)
    b := fib(n - 2)
    return a + b
~

func main() -> int
    print(fib(15))
    return 0
~
''', "610\n")

    def test_fibonacci_18(self, expect_output):
        """fib(18) = 2584, creates ~8361 tasks."""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a := fib(n - 1)
    b := fib(n - 2)
    return a + b
~

func main() -> int
    print(fib(18))
    return 0
~
''', "2584\n")

    def test_deep_chain_200(self, expect_output):
        """200-deep task call chain - stress waiter chain."""
        expect_output('''
task increment(x: int) -> int
    return x + 1
~

task chain(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    next_acc := increment(acc)
    return chain(n - 1, next_acc)
~

func main() -> int
    print(chain(200, 0))
    return 0
~
''', "200\n")

    def test_deep_chain_500(self, expect_output):
        """500-deep task call chain."""
        expect_output('''
task increment(x: int) -> int
    return x + 1
~

task chain(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    next_acc := increment(acc)
    return chain(n - 1, next_acc)
~

func main() -> int
    print(chain(500, 0))
    return 0
~
''', "500\n")


class TestMultipleTrees:
    """Tests with multiple independent task trees running concurrently."""

    def test_two_fibonacci_trees(self, expect_output):
        """Two independent fib trees running concurrently."""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a := fib(n - 1)
    b := fib(n - 2)
    return a + b
~

func main() -> int
    a := fib(12)
    b := fib(13)
    print(a + b)
    return 0
~
''', "377\n")  # fib(12)=144, fib(13)=233, sum=377

    def test_three_fibonacci_trees(self, expect_output):
        """Three independent fib trees - stresses work distribution."""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a := fib(n - 1)
    b := fib(n - 2)
    return a + b
~

func main() -> int
    a := fib(10)
    b := fib(11)
    c := fib(12)
    print(a + b + c)
    return 0
~
''', "288\n")  # fib(10)=55, fib(11)=89, fib(12)=144, sum=288

    def test_mixed_tree_depths(self, expect_output):
        """Multiple trees of varying depths running together."""
        expect_output('''
task compute(depth: int, acc: int) -> int
    if depth <= 0
        return acc
    ~
    left := compute(depth - 1, acc + 1)
    right := compute(depth - 1, acc + 2)
    return left + right
~

func main() -> int
    a := compute(5, 0)
    b := compute(6, 0)
    c := compute(4, 0)
    print(a + b + c)
    return 0
~
''', "912\n")  # compute(5,0)=240, compute(6,0)=576, compute(4,0)=96


class TestWorkloadImbalance:
    """Tests with tasks of varying execution times."""

    def test_mixed_light_heavy(self, expect_output):
        """Mix of light (instant) and heavy (loop) tasks.

        Heavy tasks do 1000 iterations, light tasks return immediately.
        Tests load balancing with imbalanced workloads.
        """
        expect_output('''
task light(x: int) -> int
    return x
~

task heavy(x: int) -> int
    sum = 0
    for i in 0..1000
        sum = sum + i
    ~
    return x + sum
~

task coordinator() -> int
    total = 0
    # Call heavy tasks explicitly at specific indices
    h0 := heavy(0)
    l1 := light(1)
    l2 := light(2)
    l3 := light(3)
    h4 := heavy(4)
    l5 := light(5)
    l6 := light(6)
    l7 := light(7)
    h8 := heavy(8)
    l9 := light(9)
    total = h0 + l1 + l2 + l3 + h4 + l5 + l6 + l7 + h8 + l9
    return total
~

func main() -> int
    result := coordinator()
    # Heavy(0) = 0 + 499500 = 499500
    # Heavy(4) = 4 + 499500 = 499504
    # Heavy(8) = 8 + 499500 = 499508
    # Light tasks: 1+2+3+5+6+7+9 = 33
    # Total: 499500 + 499504 + 499508 + 33 = 1498545
    print(result)
    return 0
~
''', "1498545\n")

    def test_pyramid_workload(self, expect_output):
        """Tasks with increasing workload (tests load balancing)."""
        expect_output('''
task work(iterations: int) -> int
    sum = 0
    for i in 0..iterations
        sum = sum + 1
    ~
    return sum
~

task coordinator() -> int
    total = 0
    for i in 1..11
        result := work(i * 100)
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "5500\n")  # sum(100,200,...,1000) = 5500


class TestDequeGrowth:
    """Tests that exercise deque growth/resize."""

    def test_burst_spawn(self, expect_output):
        """Rapid spawning that may trigger deque growth."""
        expect_output('''
task instant(x: int) -> int
    return x
~

task burst_spawner() -> int
    total = 0
    # Spawn many tasks rapidly to fill deques
    for i in 0..300
        result := instant(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(burst_spawner())
    return 0
~
''', "44850\n")  # sum(0..299) = 44850

    def test_nested_burst_spawn(self, expect_output):
        """Nested coordinators each spawning many tasks."""
        expect_output('''
task leaf(x: int) -> int
    return x
~

task inner_coordinator(base: int) -> int
    total = 0
    for i in 0..50
        result := leaf(base + i)
        total = total + result
    ~
    return total
~

task outer_coordinator() -> int
    total = 0
    for i in 0..10
        result := inner_coordinator(i * 50)
        total = total + result
    ~
    return total
~

func main() -> int
    print(outer_coordinator())
    return 0
~
''', "124750\n")  # sum(0..499) = 124750


class TestWorkStealing:
    """Tests specifically designed to exercise work-stealing."""

    def test_producer_consumer_pattern(self, expect_output):
        """Pattern that creates work imbalance for stealing opportunities."""
        expect_output('''
task produce(n: int) -> int
    if n <= 0
        return 0
    ~
    # Each producer spawns work that can be stolen
    left := produce(n - 1)
    right := produce(n - 1)
    return 1 + left + right
~

func main() -> int
    # Creates 2^10 - 1 = 1023 tasks
    print(produce(10))
    return 0
~
''', "1023\n")

    def test_asymmetric_tree(self, expect_output):
        """Asymmetric tree that creates stealing opportunities."""
        expect_output('''
task heavy_branch(n: int) -> int
    if n <= 0
        return 1
    ~
    a := heavy_branch(n - 1)
    b := heavy_branch(n - 1)
    return a + b
~

task light_branch() -> int
    return 1
~

task asymmetric(n: int) -> int
    if n <= 0
        return 1
    ~
    heavy := heavy_branch(3)  # 2^3 = 8 tasks on this side
    light := light_branch()   # 1 task on this side
    return heavy + light + asymmetric(n - 1)
~

func main() -> int
    print(asymmetric(5))
    return 0
~
''', "46\n")  # asymmetric(5) = 8+1+asymmetric(4) = 9+37 = 46


class TestFirstMostStress:
    """Stress tests for first/most batch operations."""

    def test_first_many_tasks(self, compile_coex):
        """First with many concurrent tasks."""
        result = compile_coex('''
thread identity(x: int) -> int
    return x
~

func main() -> int
    items = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]
    result = first x in items identity(x) ~
    print(result)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.run_output}"
        # First returns any of the values
        value = int(result.run_output.strip())
        assert 1 <= value <= 20

    def test_for_collection_large(self, expect_output):
        """For-collection with many tasks."""
        expect_output('''
thread double(x: int) -> int
    return x * 2
~

func main() -> int
    items = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20]
    results = for x in items double(x) ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "420\n")  # 2 * sum(1..20) = 2 * 210 = 420


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_single_task_no_stealing(self, expect_output):
        """Single task should work without stealing."""
        expect_output('''
task solo() -> int
    return 42
~

func main() -> int
    print(solo())
    return 0
~
''', "42\n")

    def test_zero_work_tasks(self, expect_output):
        """Tasks that immediately return."""
        expect_output('''
task noop() -> int
    return 0
~

task coordinator() -> int
    total = 0
    for i in 0..100
        result := noop()
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "0\n")

    def test_alternating_spawn_complete(self, expect_output):
        """Spawn-complete-spawn pattern (tests parking/unparking)."""
        expect_output('''
task work(x: int) -> int
    return x * 2
~

func main() -> int
    total = 0
    for i in 0..50
        result := work(i)
        total = total + result
    ~
    print(total)
    return 0
~
''', "2450\n")  # 2 * sum(0..49) = 2 * 1225 = 2450

    def test_task_returning_large_value(self, expect_output):
        """Task returning edge values."""
        expect_output('''
task big_number() -> int
    return 2147483647
~

task small_number() -> int
    return -2147483648
~

func main() -> int
    a := big_number()
    b := small_number()
    # Just verify they return correctly
    if a > 0
        print(1)
    else
        print(0)
    ~
    if b < 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n1\n")


class TestMemoryPressure:
    """Tests that create many frame allocations."""

    def test_many_frame_allocations(self, expect_output):
        """Many small tasks each allocating frames."""
        expect_output('''
task tiny(a: int, b: int, c: int) -> int
    # Each call allocates a frame with 3 params
    return a + b + c
~

task spawner() -> int
    total = 0
    for i in 0..200
        result := tiny(i, i+1, i+2)
        total = total + result
    ~
    return total
~

func main() -> int
    print(spawner())
    return 0
~
''', "60300\n")  # sum(3i+3 for i in 0..199) = 3*sum(0..199) + 3*200 = 3*19900 + 600 = 60300

    def test_deep_frames_with_locals(self, expect_output):
        """Deep recursion with locals that must be preserved."""
        expect_output('''
task recurse(n: int, running_sum: int) -> int
    local_val = n * 2
    if n <= 0
        return running_sum
    ~
    child_result := recurse(n - 1, running_sum + local_val)
    return child_result
~

func main() -> int
    print(recurse(100, 0))
    return 0
~
''', "10100\n")  # sum(2*i for i in 1..100) = 2*5050 = 10100


class TestConcurrentTreesWithState:
    """Multiple trees where each task maintains state."""

    def test_stateful_trees(self, expect_output):
        """Multiple trees each maintaining their own accumulator."""
        expect_output('''
task accumulate(depth: int, base: int) -> int
    if depth <= 0
        return base
    ~
    left := accumulate(depth - 1, base + depth)
    right := accumulate(depth - 1, base + depth)
    return left + right
~

func main() -> int
    a := accumulate(5, 0)
    b := accumulate(5, 100)
    print(a)
    print(b)
    return 0
~
''', "480\n3680\n")  # Verified manually
