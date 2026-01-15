# Implementation Prompt: Phase 1, Step 3
# Basic Work-Stealing Scheduler

## Objective

Implement the work-stealing scheduler that executes tasks. This includes the worker thread pool, work-stealing deques, and the core scheduling loop.

## Prerequisites

- Phase 1, Steps 1-2 complete (thread keyword, state machine transformation)
- Read `coex-task-system-spec.md` sections 3 (Scheduler Architecture) and 6 (Scheduler Core Loop)
- Understand pthread usage in existing `codegen.py`

## Test-First Methodology

**Write all tests before implementing.** The scheduler has concurrency invariants that must be tested carefully.

## Invariants to Test

### Invariant 1: Lazy Initialization - No Tasks, No Workers

```coex
# Program that never spawns a task should create no worker threads

func main() -> int
    x = 1 + 2
    print(x)
    return 0
~
```
Expected output: `3`

Verify: No worker threads created (can check via thread count or debug output).

### Invariant 2: First Task Spawn Initializes Workers

```coex
task simple() -> int
    return 42
~

func main() -> int
    result = simple()
    print(result)
    return 0
~
```
Expected output: `42`

Verify: Workers are initialized on first task spawn.

### Invariant 3: Worker Count Is 2x Physical Cores

```coex
# Debug helper to check worker count
task dummy() -> int
    return 1
~

func main() -> int
    dummy()
    # scheduler_dump_stats() or similar debug function
    return 0
~
```

Verify via debug output or inspection that worker count = 2 × physical cores.

### Invariant 4: Workers Park When No Work

```coex
task quick() -> int
    return 1
~

func main() -> int
    result = quick()
    print(result)
    # At this point, workers should be parked (not spinning)
    # Can verify via CPU usage or debug output
    return 0
~
```
Expected output: `1`

Verify: After task completes, workers are parked (low CPU usage).

### Invariant 5: Main Thread Parks Separately

```coex
task slow_computation() -> int
    # Simulate work
    total = 0
    for i in 0..1000
        total = total + i
    ~
    return total
~

func main() -> int
    result = slow_computation()
    print(result)
    return 0
~
```
Expected output: `499500`

Verify: Main thread waits for result without participating in work-stealing.

### Invariant 6: Multiple Tasks Execute Concurrently

```coex
task work(id: int) -> int
    total = 0
    for i in 0..1000
        total = total + i
    ~
    return id
~

func main() -> int
    # Spawn multiple tasks - they should run on different workers
    a = work(1)
    b = work(2)
    c = work(3)
    print(a)
    print(b)
    print(c)
    return 0
~
```
Expected output:
```
1
2
3
```

### Invariant 7: Work Stealing Balances Load

```coex
# One task spawns many subtasks - workers should steal from each other

task leaf(x: int) -> int
    return x * x
~

task fan_out() -> int
    total = 0
    for i in 0..100
        result = leaf(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(fan_out())
    return 0
~
```
Expected output: `328350` (sum of squares 0..99)

### Invariant 8: Task Results Delivered to Correct Waiter

```coex
task producer(x: int) -> int
    return x * 10
~

task consumer() -> int
    a = producer(1)
    b = producer(2)
    c = producer(3)
    return a + b + c
~

func main() -> int
    print(consumer())
    return 0
~
```
Expected output: `60`

### Invariant 9: Nested Task Calls Maintain Correct Waiting

```coex
task deep3(x: int) -> int
    return x + 3
~

task deep2(x: int) -> int
    y = deep3(x)
    return y + 2
~

task deep1(x: int) -> int
    y = deep2(x)
    return y + 1
~

func main() -> int
    result = deep1(10)
    print(result)
    return 0
~
```
Expected output: `16`

### Invariant 10: Workers Persist After Work Completes

```coex
task batch1() -> int
    return 1
~

task batch2() -> int
    return 2
~

func main() -> int
    # First batch of tasks
    a = batch1()
    print(a)
    
    # Workers should still exist, not recreated
    b = batch2()
    print(b)
    
    return 0
~
```
Expected output:
```
1
2
```

## Implementation Steps

### Step 1: Define Scheduler Data Structures

Create `scheduler.py` (or integrate into `coex_gc.py` / `codegen.py`):

```python
"""
Work-stealing scheduler for Coex tasks.
"""

# Scheduler state (generated as LLVM globals)
SCHEDULER_GLOBALS = """
; Scheduler initialization flag
@scheduler_initialized = global i1 false

; Worker threads
@scheduler_workers = global [MAX_WORKERS x i8*] zeroinitializer
@scheduler_worker_count = global i64 0

; Ready queue (work-stealing deque per worker)
@scheduler_deques = global [MAX_WORKERS x %Deque*] zeroinitializer

; Shutdown flag
@scheduler_shutdown = global i1 false

; Condition variable for parking
@scheduler_work_available = global %pthread_cond_t zeroinitializer
@scheduler_mutex = global %pthread_mutex_t zeroinitializer
"""
```

### Step 2: Implement Chase-Lev Work-Stealing Deque

```python
"""
Chase-Lev deque for work stealing.

Each worker has a deque:
- Owner pushes/pops from bottom (LIFO for locality)
- Thieves steal from top (FIFO for fairness)
"""

DEQUE_TYPE = """
%Deque = type {
    i64,           ; top (steal from here)
    i64,           ; bottom (push/pop here)
    %TaskArray*    ; circular buffer of tasks
}

%TaskArray = type {
    i64,           ; size (power of 2)
    [0 x i64]      ; task handles
}
"""

def generate_deque_push(self):
    """
    Push task to bottom of deque (owner only).
    """
    pass

def generate_deque_pop(self):
    """
    Pop task from bottom of deque (owner only).
    Returns null if empty.
    """
    pass

def generate_deque_steal(self):
    """
    Steal task from top of deque (thieves).
    Returns null if empty or contention.
    """
    pass
```

### Step 3: Implement Worker Thread Loop

```python
def generate_worker_loop(self):
    """
    Worker thread main loop:
    
    while not shutdown:
        task = try_pop_own_deque()
        if task == null:
            task = try_steal_from_others()
        if task == null:
            park_until_signaled()
            continue
        run_task(task)
    """
    pass

def generate_run_task(self):
    """
    Execute a single task step:
    
    1. Check cancelled flag - if set, discard
    2. Call step function with frame and resolved value
    3. Check cancelled again - if set, discard result
    4. Handle TaskResult (Done, Spawn, Send, Receive)
    """
    pass
```

### Step 4: Implement Lazy Initialization

```python
def generate_ensure_scheduler_initialized(self):
    """
    Called on first task spawn:
    
    if scheduler_initialized:
        return
    if not atomic_cmpxchg(scheduler_initialized, false, true):
        return  # Another thread is initializing
    
    core_count = get_physical_cores()
    worker_count = core_count * 2
    
    init_mutex_and_cond()
    
    for i in 0..worker_count:
        init_deque(i)
        pthread_create(worker_loop, i)
    """
    pass
```

### Step 5: Implement Task Spawning

```python
def generate_spawn_task(self):
    """
    Spawn a new task:
    
    1. Ensure scheduler initialized
    2. Allocate SuspendedTask on heap
    3. Initialize frame with state=0 and arguments
    4. Push to current worker's deque (or global queue if from main)
    5. Signal work available
    """
    pass
```

### Step 6: Implement Main Thread Waiting

```python
def generate_spawn_and_wait(self):
    """
    Called from func/main to spawn task and wait for result:
    
    1. Spawn task with waiter = special MAIN_WAITER marker
    2. Block on dedicated condition variable
    3. When task completes, it signals this condition
    4. Return result
    """
    pass
```

### Step 7: Implement Task Completion

```python
def generate_task_complete(self):
    """
    Handle TaskResult.Done:
    
    1. If waiter is null, discard result (orphaned task)
    2. If waiter is MAIN_WAITER, signal main's condition variable
    3. Otherwise, find waiter's SuspendedTask, set resolved value, push to ready queue
    """
    pass
```

### Step 8: Implement Work Stealing

```python
def generate_try_steal(self):
    """
    Try to steal work from other workers:
    
    for victim in random_permutation(other_workers):
        task = deque_steal(victim)
        if task != null:
            return task
    return null
    """
    pass
```

## Test Files to Create

Create `tests/test_scheduler.py`:

```python
import pytest
import subprocess
import os

class TestSchedulerInitialization:
    """Tests for lazy scheduler initialization"""
    
    def test_no_tasks_no_workers(self, expect_output):
        """Program without tasks creates no worker threads"""
        expect_output('''
func main() -> int
    print(42)
    return 0
~
''', "42\n")
        # Ideally also verify no threads created via debug output

    def test_first_task_initializes(self, expect_output):
        """First task spawn initializes the scheduler"""
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
    """Tests for basic task execution"""
    
    def test_single_task(self, expect_output):
        """Single task executes and returns"""
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
        """Multiple sequential task calls"""
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
        """Tasks calling tasks"""
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
        """Deeply nested task calls"""
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
    """Tests for concurrent task execution"""
    
    def test_parallel_tasks(self, expect_output):
        """Multiple independent tasks can run in parallel"""
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
        """One task spawns many subtasks"""
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
''', "285\n")  # 0 + 1 + 4 + 9 + 16 + 25 + 36 + 49 + 64 + 81


class TestSchedulerInvariants:
    """Tests for scheduler invariants"""
    
    def test_result_delivered_to_correct_waiter(self, expect_output):
        """Each task result goes to the correct parent"""
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
        """Workers persist and are reused"""
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
        """Scheduler handles many small tasks efficiently"""
        expect_output('''
task tiny(x: int) -> int
    return x
~

task spawn_many() -> int
    total = 0
    for i in 0..1000
        result = tiny(i)
        total = total + result
    ~
    return total
~

func main() -> int
    print(spawn_many())
    return 0
~
''', "499500\n")


class TestSchedulerStress:
    """Stress tests for the scheduler"""
    
    def test_recursive_task_tree(self, expect_output):
        """Recursive task spawning"""
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
        """Many tasks competing for workers"""
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
    print(chain(100, 0))
    return 0
~
''', "100\n")
```

## Debug Helpers

Add these debug functions for testing and development:

```coex
# Built-in debug functions for scheduler

extern scheduler_dump_stats() -> void ~
    # Print: worker count, tasks executed, steals, etc.

extern scheduler_get_worker_count() -> int ~
    # Return number of worker threads

extern scheduler_is_initialized() -> bool ~
    # Return whether scheduler has been initialized
```

## Verification

After implementation, run:

```bash
# Basic tests
python3 -m pytest tests/test_scheduler.py -v

# Stress tests (may take longer)
python3 -m pytest tests/test_scheduler.py::TestSchedulerStress -v

# Run multiple times to catch race conditions
for i in {1..10}; do
    python3 -m pytest tests/test_scheduler.py -v || exit 1
done
```

## Success Criteria

1. All tests pass
2. Lazy initialization verified (no workers without tasks)
3. Work stealing distributes load across workers
4. Main thread correctly waits for task results
5. Workers park when idle (low CPU when no work)
6. Workers persist across task batches
7. No deadlocks or race conditions under stress

## Notes

- Focus on correctness first, optimization later
- Use pthread primitives (mutex, condvar) for simplicity
- Chase-Lev deque is well-documented; follow the algorithm carefully
- Add debug output during development, remove or gate behind flag for release
- Test on multi-core machine to exercise parallelism
