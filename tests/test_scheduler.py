"""
Tests for the work-stealing scheduler.

Phase 1, Step 3: Implement work-stealing scheduler with state machine transformation.
"""

import pytest


class TestSchedulerInitialization:
    """Tests for lazy scheduler initialization."""

    def test_no_tasks_no_workers(self, expect_output):
        """Program without tasks creates no worker threads."""
        expect_output('''
func main() -> int
    print(42)
    return 0
~
''', "42\n")

    def test_first_task_initializes(self, expect_output):
        """First task spawn initializes the scheduler."""
        expect_output('''
task simple() -> int
    return 42
~

func main() -> int
    print(simple())
    return 0
~
''', "42\n")


class TestTaskExecution:
    """Tests for basic task execution."""

    def test_single_task(self, expect_output):
        """Single task executes and returns."""
        expect_output('''
task compute(x: int) -> int
    return x * 2
~

func main() -> int
    print(compute(21))
    return 0
~
''', "42\n")

    def test_sequential_tasks(self, expect_output):
        """Multiple sequential task calls."""
        expect_output('''
task step(x: int) -> int
    return x + 1
~

func main() -> int
    a = step(0)
    b = step(a)
    c = step(b)
    print(c)
    return 0
~
''', "3\n")

    def test_nested_tasks(self, expect_output):
        """Tasks calling tasks."""
        expect_output('''
task inner(x: int) -> int
    return x * 2
~

task outer(x: int) -> int
    y = inner(x)
    return y + 1
~

func main() -> int
    print(outer(10))
    return 0
~
''', "21\n")

    def test_deep_nesting(self, expect_output):
        """Deeply nested task calls."""
        expect_output('''
task level5(x: int) -> int
    return x + 5
~

task level4(x: int) -> int
    return level5(x) + 4
~

task level3(x: int) -> int
    return level4(x) + 3
~

task level2(x: int) -> int
    return level3(x) + 2
~

task level1(x: int) -> int
    return level2(x) + 1
~

func main() -> int
    print(level1(0))
    return 0
~
''', "15\n")


class TestConcurrentExecution:
    """Tests for concurrent task execution."""

    def test_parallel_tasks(self, expect_output):
        """Multiple independent tasks can run in parallel."""
        expect_output('''
task work(id: int) -> int
    total = 0
    for i in 0..100
        total = total + i
    ~
    return id
~

func main() -> int
    a = work(1)
    b = work(2)
    c = work(3)
    print(a + b + c)
    return 0
~
''', "6\n")

    def test_fan_out_fan_in(self, expect_output):
        """One task spawns many subtasks."""
        expect_output('''
task leaf(x: int) -> int
    return x * x
~

task coordinator() -> int
    total = 0
    for i in 0..10
        result = leaf(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(coordinator())
    return 0
~
''', "285\n")


class TestSchedulerInvariants:
    """Tests for scheduler invariants."""

    def test_result_delivered_to_correct_waiter(self, expect_output):
        """Each task result goes to the correct parent."""
        expect_output('''
task make_value(x: int) -> int
    return x * 10
~

task parent1() -> int
    return make_value(1)
~

task parent2() -> int
    return make_value(2)
~

func main() -> int
    a = parent1()
    b = parent2()
    print(a)
    print(b)
    return 0
~
''', "10\n20\n")

    def test_workers_reused_across_batches(self, expect_output):
        """Workers persist and are reused."""
        expect_output('''
task batch_a() -> int
    return 1
~

task batch_b() -> int
    return 2
~

func main() -> int
    a = batch_a()
    print(a)
    b = batch_b()
    print(b)
    return 0
~
''', "1\n2\n")

    def test_many_small_tasks(self, expect_output):
        """Scheduler handles many small tasks efficiently."""
        expect_output('''
task tiny(x: int) -> int
    return x
~

task spawn_many() -> int
    total = 0
    for i in 0..100
        result = tiny(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(spawn_many())
    return 0
~
''', "4950\n")


class TestSchedulerStress:
    """Stress tests for the scheduler."""

    def test_recursive_task_tree(self, expect_output):
        """Recursive task spawning."""
        expect_output('''
task fib(n: int) -> int
    if n <= 1
        return n
    ~
    a = fib(n - 1)
    b = fib(n - 2)
    return a + b
~

func main() -> int
    print(fib(10))
    return 0
~
''', "55\n")

    def test_high_contention(self, expect_output):
        """Many tasks competing for workers."""
        expect_output('''
task increment(x: int) -> int
    return x + 1
~

task chain(n: int, acc: int) -> int
    if n <= 0
        return acc
    ~
    next_acc = increment(acc)
    return chain(n - 1, next_acc)
~

func main() -> int
    print(chain(50, 0))
    return 0
~
''', "50\n")


class TestTaskWithLocals:
    """Tests for local variable preservation across suspension."""

    def test_locals_preserved_simple(self, expect_output):
        """Local defined before task call available after."""
        expect_output('''
task get_ten() -> int
    return 10
~

task use_local() -> int
    x = 5
    y = get_ten()
    return x + y
~

func main() -> int
    print(use_local())
    return 0
~
''', "15\n")

    def test_multiple_locals_preserved(self, expect_output):
        """Multiple locals preserved across multiple suspension points."""
        expect_output('''
task get_value(x: int) -> int
    return x
~

task multi_local() -> int
    a = 1
    b = 2
    c = 3
    x = get_value(10)
    y = get_value(20)
    return a + b + c + x + y
~

func main() -> int
    print(multi_local())
    return 0
~
''', "36\n")

    def test_heap_local_preserved(self, expect_output):
        """Heap-allocated locals survive suspension."""
        expect_output('''
task get_number() -> int
    return 42
~

task heap_local() -> int
    items = [1, 2, 3, 4, 5]
    value = get_number()
    return items.len() + value
~

func main() -> int
    print(heap_local())
    return 0
~
''', "47\n")


class TestTaskControlFlow:
    """Tests for control flow with suspension points."""

    def test_if_with_suspension_true(self, expect_output):
        """Suspension in if branch (true case)."""
        expect_output('''
task get_value() -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x = get_value()
        return x
    else
        return 0
    ~
~

func main() -> int
    print(conditional(true))
    return 0
~
''', "100\n")

    def test_if_with_suspension_false(self, expect_output):
        """Suspension in if branch (false case)."""
        expect_output('''
task get_value() -> int
    return 100
~

task conditional(flag: bool) -> int
    if flag
        x = get_value()
        return x
    else
        return 0
    ~
~

func main() -> int
    print(conditional(false))
    return 0
~
''', "0\n")

    def test_loop_with_suspension(self, expect_output):
        """Suspension inside loop body."""
        expect_output('''
task double(x: int) -> int
    return x * 2
~

task loop_suspend() -> int
    total = 0
    for i in 0..5
        val = double(i)
        total = total + val
    ~
    return total
~

func main() -> int
    print(loop_suspend())
    return 0
~
''', "20\n")
