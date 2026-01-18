# Implementation Prompt: Phase 3, Steps 8-9
# Structured Concurrency: `first` and `most`

## Objective

Implement the `first` and `most` structured concurrency primitives that spawn multiple tasks and collect results with different semantics.

## Prerequisites

- Phase 2 complete (tasks, channels working)
- Read `coex-task-system-spec.md` section 8 (Structured Concurrency) and 9 (Cancellation)
- Understand cooperative cancellation model

## Test-First Methodology

**Write all tests before implementing.** Structured concurrency has precise semantics that must be tested.

## Part A: `first` Implementation

### Semantics

`first` spawns N tasks and returns the first successful result, cancelling the remaining tasks.

```coex
result = first item in collection
    process(item)
~
```

### Invariants to Test

#### Invariant 1: Returns First Completed Value

```coex
task fast() -> int
    return 1
~

task slow() -> int
    total = 0
    for i in 0..100000
        total = total + i
    ~
    return 2
~

func main() -> int
    result = first i in [1, 2]
        if i == 1
            fast()
        else
            slow()
        ~
    ~
    print(result)
    return 0
~
```
Expected output: `1` (fast completes first)

#### Invariant 2: All Tasks Race

```coex
task work(x: int) -> int
    return x * 10
~

func main() -> int
    result = first i in [1, 2, 3, 4, 5]
        work(i)
    ~
    # Result is one of: 10, 20, 30, 40, 50
    print(result >= 10 and result <= 50)
    return 0
~
```
Expected output: `true`

#### Invariant 3: Siblings Cancelled After Winner

```coex
task racer(id: int, flag: atomic_int) -> int
    flag.fetch_add(1)  # Count started tasks
    return id
~

func main() -> int
    started: atomic_int = 0
    
    result = first i in [1, 2, 3]
        racer(i, started)
    ~
    
    # All tasks started, but only one's result matters
    print(result)
    return 0
~
```
Expected: Prints 1, 2, or 3 (first to complete)

#### Invariant 4: Cancelled Tasks Don't Affect Result

```coex
task worker(id: int) -> int
    if id == 1
        return 100
    else
        # Simulate slow work that will be cancelled
        total = 0
        for i in 0..1000000
            total = total + i
        ~
        return id
    ~
~

func main() -> int
    result = first i in [1, 2, 3]
        worker(i)
    ~
    print(result)
    return 0
~
```
Expected output: `100`

#### Invariant 5: Empty Collection Returns Default/Error

```coex
task work(x: int) -> int
    return x
~

func main() -> int
    # What happens with empty collection?
    result = first i in []
        work(i)
    ~
    print(result)
    return 0
~
```
Expected: Compile error or runtime error (no tasks to race)

#### Invariant 6: Single Element Works

```coex
task single(x: int) -> int
    return x * 2
~

func main() -> int
    result = first i in [21]
        single(i)
    ~
    print(result)
    return 0
~
```
Expected output: `42`

## Part B: `most` Implementation

### Semantics

`most` spawns N tasks and collects all successes and failures without cancellation.

```coex
(results, errors) = most item in collection
    process(item)
~
```

### Invariants to Test

#### Invariant 7: All Results Collected

```coex
task square(x: int) -> int
    return x * x
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4, 5]
        square(i)
    ~
    
    total = 0
    for r in results
        total = total + r
    ~
    print(total)  # 1 + 4 + 9 + 16 + 25 = 55
    return 0
~
```
Expected output: `55`

#### Invariant 8: Errors Collected Separately

```coex
task maybe_fail(x: int) -> Result<int, string>
    if x % 2 == 0
        return Result.Ok(x)
    else
        return Result.Err("odd number")
    ~
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4, 5]
        maybe_fail(i)
    ~
    
    print(results.len())  # 2 (even numbers: 2, 4)
    print(errors.len())   # 3 (odd numbers: 1, 3, 5)
    return 0
~
```
Expected output:
```
2
3
```

#### Invariant 9: All Tasks Run to Completion

```coex
task counter(x: int, count: atomic_int) -> int
    count.fetch_add(1)
    return x
~

func main() -> int
    completed: atomic_int = 0
    
    (results, errors) = most i in [1, 2, 3, 4, 5]
        counter(i, completed)
    ~
    
    print(completed.load())  # All 5 should complete
    return 0
~
```
Expected output: `5`

#### Invariant 10: Order May Vary, All Present

```coex
task identity(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in [10, 20, 30]
        identity(i)
    ~
    
    # Sort results to verify all present
    total = 0
    for r in results
        total = total + r
    ~
    print(total)  # 10 + 20 + 30 = 60
    return 0
~
```
Expected output: `60`

#### Invariant 11: Empty Collection Returns Empty Results

```coex
task work(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in []
        work(i)
    ~
    print(results.len())
    print(errors.len())
    return 0
~
```
Expected output:
```
0
0
```

#### Invariant 12: Single Element Works

```coex
task double(x: int) -> int
    return x * 2
~

func main() -> int
    (results, errors) = most i in [21]
        double(i)
    ~
    print(results.get(0))
    return 0
~
```
Expected output: `42`

## Implementation Steps

### Step 1: Define Context Structures

```python
# FirstContext for tracking first completion
FIRST_CONTEXT_TYPE = """
%FirstContext = type {
    i64,             ; parent_task_id
    %TaskList*,      ; children (list of spawned task IDs)
    i1,              ; done (atomic: has winner been determined?)
    i64,             ; winner_value (result from winner)
    i64              ; winner_task_id
}
"""

# MostContext for collecting all results
MOST_CONTEXT_TYPE = """
%MostContext = type {
    i64,             ; parent_task_id
    %TaskList*,      ; children
    %ResultList*,    ; results (successful completions)
    %ErrorList*,     ; errors (failed completions)
    i64              ; remaining (atomic: count of incomplete tasks)
}
"""
```

### Step 2: Implement `first` Code Generation

```python
def generate_first_statement(self, node: FirstStatement):
    """
    Generate code for: result = first item in collection body ~
    
    1. Create FirstContext
    2. For each item in collection:
       - Spawn task with body
       - Add task ID to children list
       - Set task's completion handler to first_complete
    3. Suspend parent until done flag is set
    4. Return winner_value
    """
    # Create context
    ctx = alloc_first_context()
    ctx.parent_task_id = current_task_id()
    ctx.done = false
    
    # Spawn children
    for item in collection:
        child_task = spawn_task(body_with_item)
        child_task.completion_handler = first_complete_handler
        child_task.completion_context = ctx
        list_append(ctx.children, child_task.id)
    
    # Suspend until winner
    return TaskResult.WaitFirst(ctx)
```

### Step 3: Implement First Completion Handler

```python
def first_complete_handler(task_id, value, ctx):
    """
    Called when a child of `first` completes.
    
    1. Try to claim winner slot with CAS
    2. If won: store value, mark siblings cancelled, wake parent
    3. If lost: discard value
    """
    # Try to be the winner
    if atomic_cmpxchg(ctx.done, false, true):
        # We won!
        ctx.winner_value = value
        ctx.winner_task_id = task_id
        
        # Cancel siblings
        for sibling_id in ctx.children:
            if sibling_id != task_id:
                mark_cancelled(sibling_id)
        
        # Wake parent
        parent = suspended_tasks[ctx.parent_task_id]
        parent.pending_value = value
        ready_queue_push(parent)
    else:
        # Lost race, discard result
        pass
```

### Step 4: Implement `most` Code Generation

```python
def generate_most_statement(self, node: MostStatement):
    """
    Generate code for: (results, errors) = most item in collection body ~
    
    1. Create MostContext
    2. For each item in collection:
       - Spawn task with body
       - Add task ID to children list
       - Set task's completion handler to most_complete
    3. Set remaining = len(children)
    4. Suspend parent until remaining == 0
    5. Return (results, errors) tuple
    """
    # Create context
    ctx = alloc_most_context()
    ctx.parent_task_id = current_task_id()
    ctx.results = empty_list()
    ctx.errors = empty_list()
    
    # Spawn children
    count = 0
    for item in collection:
        child_task = spawn_task(body_with_item)
        child_task.completion_handler = most_complete_handler
        child_task.completion_context = ctx
        list_append(ctx.children, child_task.id)
        count += 1
    
    ctx.remaining = count
    
    if count == 0:
        # No tasks to run, return empty immediately
        return ([], [])
    
    # Suspend until all complete
    return TaskResult.WaitMost(ctx)
```

### Step 5: Implement Most Completion Handler

```python
def most_complete_handler(task_id, result, ctx):
    """
    Called when a child of `most` completes.
    
    1. If result is Ok: append to results
    2. If result is Err: append to errors
    3. Decrement remaining
    4. If remaining == 0: wake parent
    """
    # Collect result (needs lock for list append)
    lock(ctx.mutex)
    if is_ok(result):
        list_append(ctx.results, result.value)
    else:
        list_append(ctx.errors, result.error)
    unlock(ctx.mutex)
    
    # Check if we're the last one
    old_remaining = atomic_fetch_sub(ctx.remaining, 1)
    if old_remaining == 1:
        # We were the last task
        parent = suspended_tasks[ctx.parent_task_id]
        parent.pending_value = (ctx.results, ctx.errors)
        ready_queue_push(parent)
```

### Step 6: Handle Cancellation Propagation

```python
def mark_cancelled(task_id):
    """
    Mark a task as cancelled.
    Task will check this flag at next suspension point.
    """
    task = suspended_tasks.get(task_id)
    if task:
        atomic_store(task.cancelled, true)
    
    # Also mark in ready queue if present
    # (Task will check when it starts running)
```

### Step 7: Integrate with Scheduler

```python
def handle_task_result(task, result):
    """Extended to handle first/most completion."""
    match result:
        case TaskResult.Done(value):
            if task.completion_handler:
                # Call structured concurrency handler
                task.completion_handler(task.id, value, task.completion_context)
            elif task.waiter:
                # Normal task completion
                wake_with_value(task.waiter, value)
        
        case TaskResult.WaitFirst(ctx):
            # Parent waiting for first child
            suspended_tasks[task.id] = task
            # Children are already spawned and running
        
        case TaskResult.WaitMost(ctx):
            # Parent waiting for all children
            suspended_tasks[task.id] = task
            # Children are already spawned and running
```

## Test Files to Create

Create `tests/test_first_most.py`:

```python
import pytest

class TestFirst:
    """Tests for `first` structured concurrency"""
    
    def test_first_returns_winner(self, expect_output):
        expect_output('''
task fast() -> int
    return 1
~

task slow() -> int
    total = 0
    for i in 0..10000
        total = total + i
    ~
    return 2
~

func main() -> int
    result = first i in [1, 2]
        if i == 1
            fast()
        else
            slow()
        ~
    ~
    print(result)
    return 0
~
''', "1\n")

    def test_first_single_element(self, expect_output):
        expect_output('''
task double(x: int) -> int
    return x * 2
~

func main() -> int
    result = first i in [21]
        double(i)
    ~
    print(result)
    return 0
~
''', "42\n")

    def test_first_all_complete_one_wins(self, expect_output):
        expect_output('''
task work(x: int) -> int
    return x * 10
~

func main() -> int
    result = first i in [1, 2, 3]
        work(i)
    ~
    # Result is 10, 20, or 30
    print(result >= 10 and result <= 30)
    return 0
~
''', "true\n")


class TestMost:
    """Tests for `most` structured concurrency"""
    
    def test_most_collects_all(self, expect_output):
        expect_output('''
task square(x: int) -> int
    return x * x
~

func main() -> int
    (results, errors) = most i in [1, 2, 3, 4, 5]
        square(i)
    ~
    total = 0
    for r in results
        total = total + r
    ~
    print(total)
    return 0
~
''', "55\n")

    def test_most_empty_collection(self, expect_output):
        expect_output('''
task work(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in []
        work(i)
    ~
    print(results.len())
    return 0
~
''', "0\n")

    def test_most_single_element(self, expect_output):
        expect_output('''
task double(x: int) -> int
    return x * 2
~

func main() -> int
    (results, errors) = most i in [21]
        double(i)
    ~
    print(results.get(0))
    return 0
~
''', "42\n")

    def test_most_all_succeed(self, expect_output):
        expect_output('''
task identity(x: int) -> int
    return x
~

func main() -> int
    (results, errors) = most i in [10, 20, 30]
        identity(i)
    ~
    print(results.len())
    print(errors.len())
    return 0
~
''', "3\n0\n")


class TestFirstCancellation:
    """Tests for cancellation in `first`"""
    
    def test_siblings_cancelled(self, expect_output):
        expect_output('''
task racer(id: int) -> int
    if id == 1
        return 100
    else
        # This will be cancelled
        total = 0
        for i in 0..1000000
            total = total + i
        ~
        return id
    ~
~

func main() -> int
    result = first i in [1, 2, 3]
        racer(i)
    ~
    print(result)
    return 0
~
''', "100\n")


class TestMostNoCancel:
    """Tests that `most` doesn't cancel"""
    
    def test_all_run_to_completion(self, expect_output):
        expect_output('''
task counter(x: int, count: atomic_int) -> int
    count.fetch_add(1)
    return x
~

func main() -> int
    completed: atomic_int = 0
    (results, errors) = most i in [1, 2, 3, 4, 5]
        counter(i, completed)
    ~
    print(completed.load())
    return 0
~
''', "5\n")
```

## Verification

```bash
python3 -m pytest tests/test_first_most.py -v
```

## Success Criteria

1. All tests pass
2. `first` returns first completed result
3. `first` cancels remaining siblings
4. `most` collects all results and errors
5. `most` doesn't cancel any tasks
6. Empty collections handled correctly
7. Single-element collections work
8. Cancellation is cooperative (no forced termination)

## Notes

- `first` uses atomic CAS to determine winner
- `most` uses atomic decrement to detect completion
- Result/error lists in `most` need synchronization
- Cancellation is best-effort; cancelled tasks may still complete
- GC handles cleanup of cancelled task frames
