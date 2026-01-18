# Implementation Prompt: Phase 2, Step 4
# Task-to-Task Execution

## Objective

Complete the task execution model so that tasks can call other tasks with proper suspension, resumption, and result delivery through the scheduler.

## Prerequisites

- Phase 1 complete (thread keyword, state machine transformation, basic scheduler)
- Read `coex-task-system-spec.md` sections 4.2 (Suspension Points) and 5 (Task State)
- Scheduler from Step 3 is working for simple cases

## Test-First Methodology

**Write all tests before implementing.** Task-to-task communication is the core of the system.

## Invariants to Test

### Invariant 1: Task Call Creates Suspension Point

```coex
task callee() -> int
    return 42
~

task caller() -> int
    x = callee()    # Must suspend here until callee completes
    return x + 1
~

func main() -> int
    print(caller())
    return 0
~
```
Expected output: `43`

### Invariant 2: Caller Receives Callee's Return Value

```coex
task produce_value(x: int) -> int
    return x * 100
~

task consume_value() -> int
    a = produce_value(1)
    b = produce_value(2)
    c = produce_value(3)
    return a + b + c
~

func main() -> int
    print(consume_value())
    return 0
~
```
Expected output: `600`

### Invariant 3: Execution Order Is Correct

```coex
task step1() -> int
    print(1)
    return 1
~

task step2(x: int) -> int
    print(2)
    return x + 2
~

task step3(x: int) -> int
    print(3)
    return x + 3
~

task ordered() -> int
    a = step1()
    b = step2(a)
    c = step3(b)
    return c
~

func main() -> int
    result = ordered()
    print(result)
    return 0
~
```
Expected output:
```
1
2
3
6
```

### Invariant 4: Waiter Link Is Set Correctly

```coex
task leaf() -> int
    return 10
~

task middle() -> int
    x = leaf()      # middle waits on leaf
    return x + 5
~

task top() -> int
    y = middle()    # top waits on middle
    return y + 1
~

func main() -> int
    print(top())
    return 0
~
```
Expected output: `16`

### Invariant 5: Multiple Concurrent Waiters (Siblings)

```coex
task slow_work(id: int) -> int
    total = 0
    for i in 0..1000
        total = total + i
    ~
    return id
~

task parallel_calls() -> int
    # These three tasks can run concurrently
    # Each completes and returns to parent
    a = slow_work(1)
    b = slow_work(2)
    c = slow_work(3)
    return a + b + c
~

func main() -> int
    print(parallel_calls())
    return 0
~
```
Expected output: `6`

### Invariant 6: Result Delivery Wakes Correct Task

```coex
task make_a() -> int
    return 10
~

task make_b() -> int
    return 20
~

task uses_a() -> int
    x = make_a()
    return x + 1    # Should get 10, not 20
~

task uses_b() -> int
    y = make_b()
    return y + 1    # Should get 20, not 10
~

func main() -> int
    a = uses_a()
    b = uses_b()
    print(a)
    print(b)
    return 0
~
```
Expected output:
```
11
21
```

### Invariant 7: Suspended Task State Is Preserved

```coex
task get_number() -> int
    return 5
~

task preserves_state() -> int
    x = 10
    y = 20
    z = get_number()    # Suspend here; x and y must survive
    return x + y + z
~

func main() -> int
    print(preserves_state())
    return 0
~
```
Expected output: `35`

### Invariant 8: Frame Updated After Each Suspension

```coex
task produce(n: int) -> int
    return n
~

task accumulate() -> int
    a = produce(1)    # Frame after: {state: 1, a: 1}
    b = produce(2)    # Frame after: {state: 2, a: 1, b: 2}
    c = produce(3)    # Frame after: {state: 3, a: 1, b: 2, c: 3}
    return a + b + c
~

func main() -> int
    print(accumulate())
    return 0
~
```
Expected output: `6`

### Invariant 9: TaskResult.Spawn Correctly Chains

When a task returns `TaskResult.Spawn(new_frame, subtask)`:
1. Parent's new_frame is stored in suspended map
2. Subtask's waiter is set to parent's ID
3. Subtask is pushed to ready queue

```coex
task inner() -> int
    return 100
~

task outer() -> int
    # When outer calls inner:
    # 1. outer returns Spawn(frame_state_1, inner_task)
    # 2. Scheduler sets inner.waiter = outer.id
    # 3. Scheduler stores outer's frame
    # 4. Scheduler pushes inner to queue
    # 5. When inner completes, outer resumes with value 100
    result = inner()
    return result + 1
~

func main() -> int
    print(outer())
    return 0
~
```
Expected output: `101`

### Invariant 10: Recursive Tasks Work Correctly

```coex
task factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    sub = factorial(n - 1)
    return n * sub
~

func main() -> int
    print(factorial(5))
    return 0
~
```
Expected output: `120`

## Implementation Steps

### Step 1: Ensure TaskResult.Spawn Is Generated

Verify that the state machine transformation generates correct Spawn results:

```python
# In generated step function
case 0:
    # Create subtask
    subtask_frame = InnerFrame(state=0, args...)
    subtask = SuspendedTask(
        frame=subtask_frame,
        step_fn=inner_step,
        waiter=null,  # Scheduler will set this
        cancelled=false
    )
    # Return Spawn with updated parent frame
    return TaskResult.Spawn(
        frame_with_state_1,
        subtask
    )
```

### Step 2: Implement Spawn Handling in Scheduler

```python
def handle_spawn(parent_task, parent_new_frame, subtask):
    """
    Handle TaskResult.Spawn:
    1. Store parent's new frame in suspended map
    2. Set subtask's waiter to parent's ID
    3. Push subtask to ready queue
    """
    # Store parent
    suspended[parent_task.id] = SuspendedTask(
        frame=parent_new_frame,
        step_fn=parent_task.step_fn,
        waiter=parent_task.waiter,  # Preserve parent's waiter
        cancelled=parent_task.cancelled
    )
    
    # Link subtask to parent
    subtask.waiter = parent_task.id
    
    # Schedule subtask
    ready_queue.push(subtask)
```

### Step 3: Implement Done Handling with Wake

```python
def handle_done(task, value):
    """
    Handle TaskResult.Done:
    1. If waiter is null, discard (orphan)
    2. If waiter is MAIN_MARKER, signal main thread
    3. Otherwise, resume waiter with value
    """
    if task.waiter is None:
        return  # Orphaned task
    
    if task.waiter == MAIN_MARKER:
        # Signal main thread
        main_result_slot = value
        pthread_cond_signal(main_cond)
        return
    
    # Resume parent task
    parent = suspended.pop(task.waiter)
    parent.pending_value = value
    ready_queue.push(parent)
```

### Step 4: Implement Resume with Value

When a suspended task is resumed:

```python
def run_task(task):
    # ...existing cancellation checks...
    
    # Call step function with resolved value
    result = task.step_fn(task.frame, task.pending_value)
    
    # pending_value is consumed; clear it
    task.pending_value = None
    
    # Handle result...
```

### Step 5: Ensure Correct Frame State Transitions

Each state in the step function must:
1. Receive the resolved value from previous suspension
2. Store it in the appropriate frame field
3. Proceed to next computation or suspension

```python
# Example generated code
case 1:
    # Received value from previous suspension
    frame.field_a = resolved_value
    
    # Continue to next suspension or completion
    if more_work:
        return TaskResult.Spawn(
            frame_with_state_2,
            next_subtask
        )
    else:
        return TaskResult.Done(frame.field_a + something)
```

## Test Files to Create

Create `tests/test_task_to_task.py`:

```python
import pytest

class TestTaskCalling:
    """Tests for task-to-task calls"""
    
    def test_simple_call(self, expect_output):
        """Task calls another task and receives result"""
        expect_output('''
task callee() -> int
    return 42
~

task caller() -> int
    x = callee()
    return x + 1
~

func main() -> int
    print(caller())
    return 0
~
''', "43\n")

    def test_multiple_calls(self, expect_output):
        """Task makes multiple calls to other tasks"""
        expect_output('''
task produce(x: int) -> int
    return x * 10
~

task consumer() -> int
    a = produce(1)
    b = produce(2)
    c = produce(3)
    return a + b + c
~

func main() -> int
    print(consumer())
    return 0
~
''', "60\n")

    def test_call_chain(self, expect_output):
        """Chain of task calls"""
        expect_output('''
task add1(x: int) -> int
    return x + 1
~

task add2(x: int) -> int
    y = add1(x)
    return y + 2
~

task add3(x: int) -> int
    y = add2(x)
    return y + 3
~

func main() -> int
    print(add3(10))
    return 0
~
''', "16\n")


class TestExecutionOrder:
    """Tests for correct execution ordering"""
    
    def test_sequential_prints(self, expect_output):
        """Tasks execute in correct order"""
        expect_output('''
task step1() -> int
    print(1)
    return 1
~

task step2() -> int
    print(2)
    return 2
~

task ordered() -> int
    a = step1()
    b = step2()
    return a + b
~

func main() -> int
    result = ordered()
    print(result)
    return 0
~
''', "1\n2\n3\n")

    def test_nested_order(self, expect_output):
        """Nested calls maintain order"""
        expect_output('''
task inner() -> int
    print(2)
    return 2
~

task outer() -> int
    print(1)
    x = inner()
    print(3)
    return x
~

func main() -> int
    result = outer()
    print(result)
    return 0
~
''', "1\n2\n3\n2\n")


class TestStatePreservation:
    """Tests for frame state preservation across suspensions"""
    
    def test_locals_survive_suspension(self, expect_output):
        """Local variables preserved across task call"""
        expect_output('''
task get_value() -> int
    return 100
~

task uses_locals() -> int
    x = 10
    y = 20
    z = get_value()
    return x + y + z
~

func main() -> int
    print(uses_locals())
    return 0
~
''', "130\n")

    def test_multiple_locals_multiple_suspensions(self, expect_output):
        """Multiple locals across multiple suspensions"""
        expect_output('''
task fetch(n: int) -> int
    return n * n
~

task complex() -> int
    a = 1
    b = fetch(2)    # a survives
    c = 3
    d = fetch(4)    # a, b, c survive
    e = 5
    return a + b + c + d + e
~

func main() -> int
    print(complex())
    return 0
~
''', "29\n")  # 1 + 4 + 3 + 16 + 5


class TestResultDelivery:
    """Tests for correct result delivery to waiters"""
    
    def test_result_to_correct_parent(self, expect_output):
        """Each result goes to correct parent"""
        expect_output('''
task make_ten() -> int
    return 10
~

task make_twenty() -> int
    return 20
~

task uses_ten() -> int
    x = make_ten()
    return x + 1
~

task uses_twenty() -> int
    y = make_twenty()
    return y + 1
~

func main() -> int
    a = uses_ten()
    b = uses_twenty()
    print(a)
    print(b)
    return 0
~
''', "11\n21\n")

    def test_interleaved_results(self, expect_output):
        """Results delivered correctly when tasks interleave"""
        expect_output('''
task slow(id: int) -> int
    total = 0
    for i in 0..100
        total = total + i
    ~
    return id
~

task a() -> int
    x = slow(1)
    return x * 10
~

task b() -> int
    y = slow(2)
    return y * 10
~

func main() -> int
    ra = a()
    rb = b()
    print(ra)
    print(rb)
    return 0
~
''', "10\n20\n")


class TestRecursion:
    """Tests for recursive task calls"""
    
    def test_factorial(self, expect_output):
        """Recursive factorial"""
        expect_output('''
task factorial(n: int) -> int
    if n <= 1
        return 1
    ~
    sub = factorial(n - 1)
    return n * sub
~

func main() -> int
    print(factorial(5))
    return 0
~
''', "120\n")

    def test_fibonacci(self, expect_output):
        """Recursive fibonacci (tree recursion)"""
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

    def test_mutual_recursion(self, expect_output):
        """Mutually recursive tasks"""
        expect_output('''
task is_even(n: int) -> bool
    if n == 0
        return true
    ~
    return is_odd(n - 1)
~

task is_odd(n: int) -> bool
    if n == 0
        return false
    ~
    return is_even(n - 1)
~

func main() -> int
    if is_even(10)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")
```

## Verification

```bash
python3 -m pytest tests/test_task_to_task.py -v
```

## Success Criteria

1. All tests pass
2. Task calls correctly suspend caller
3. Results are delivered to correct waiter
4. Frame state preserved across suspensions
5. Recursive tasks work correctly
6. No result misdirection between concurrent tasks

## Notes

- This step builds on the scheduler from Step 3
- Focus on the waiter linkage and result delivery
- The scheduler should already handle the mechanics; this step verifies correctness
- Test interleaving carefully — race conditions may only appear under load
