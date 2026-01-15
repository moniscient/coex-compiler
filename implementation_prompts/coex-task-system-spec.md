# Coex Task System Specification

## 1. Overview

This document specifies the lightweight task system for Coex, enabling efficient concurrent execution through stackless coroutines scheduled on a work-stealing thread pool. The design exploits Coex's value semantics and function kind system to achieve simplicity that would be impossible in languages with mutable aliasing.

## 2. Function Kind Hierarchy

### 2.1 Coex Function Kinds

Function kinds form a hierarchy from lightest/most constrained to heaviest/most permissive:

```
formula  (lightest, most constrained)
   ↓
task
   ↓
thread
   ↓
func     (heaviest, most permissive)
```

Calling rules — each kind can call itself and anything lighter:

```
formula → calls: formula
task    → calls: formula, task
thread  → calls: formula, task, thread
func    → calls: formula, task, thread, func
```

| Kind | Purpose | Constraints |
|------|---------|-------------|
| `formula` | Pure computation | No side effects, GPU-offloadable (future) |
| `task` | Lightweight concurrency | Cooperative scheduling, no blocking |
| `thread` | Full OS thread | Can block, can call extern |
| `func` | General-purpose orchestrator | Can do anything, `main()` is a func |

### 2.2 Extern: The FFI Boundary

`extern` is not part of the calling hierarchy. It declares C functions that exist outside Coex:

```
extern → (C FFI declaration, calls nothing, may block)
```

- Only `thread` and `func` can call externs
- Externs cannot call back into Coex — they only return values
- Externs are opaque to Coex — the compiler assumes they may block
- Tasks cannot call externs (directly or transitively), ensuring workers never block

### 2.3 Compiler Enforcement

Calling "up" the hierarchy (lighter kinds) is always permitted. Calling "down" (heavier kinds) is a compile error:

```python
def check_call(caller_kind: FunctionKind, callee_kind: FunctionKind) -> bool:
    hierarchy = [formula, task, thread, func]
    return hierarchy.index(callee_kind) <= hierarchy.index(caller_kind)

def check_extern_call(caller_kind: FunctionKind) -> bool:
    return caller_kind in (thread, func)
```

## 3. Scheduler Architecture

### 3.1 Lazy Initialization

The worker pool initializes on first task spawn:

- If program never spawns a task, no workers created, zero overhead
- First task spawn triggers initialization
- Workers persist until process exit

### 3.2 Worker Pool

- 2× physical cores worker threads
- Work-stealing deques (Chase-Lev algorithm)
- Workers park on condition variable when queue empty
- Workers wake when new work arrives

### 3.3 Main Thread

When `main()` (or any func) spawns a task and waits for results:

- Main parks separately on its own condition variable
- Main does not participate in work-stealing
- Workers do all task processing

## 4. Coroutine Implementation

### 4.1 Stackless Design

Tasks are stackless coroutines. The compiler transforms task bodies into state machines. This avoids per-task stack allocation and integrates naturally with the GC.

Coex's value semantics eliminate the complexity that makes stackless coroutines difficult in other languages:

- No mutable references to capture
- No lifetime tracking across suspension points
- Suspend state is just immutable data on the heap

### 4.2 Suspension Points

Tasks suspend only at explicit points:

- Task calls (calling another task)
- Channel send (when buffer full)
- Channel receive (when buffer empty)
- `first` / `most` (waiting for spawned work)
- `select` (future implementation)

Everything else runs synchronously: formula calls, arithmetic, control flow, collection operations.

### 4.3 State Machine Transformation

Given a task:

```coex
task process(data: List<int>) -> int
    filtered = filter_negatives(data)    # suspend point 1
    doubled = double_values(filtered)    # suspend point 2
    sum = sum_values(doubled)            # suspend point 3
    return sum
~
```

The compiler generates a frame type:

```coex
type ProcessFrame:
    state: int
    data: List<int>
    filtered: List<int>?
    doubled: List<int>?
    sum: int?
~
```

And a step function:

```coex
func process_step(frame: ProcessFrame, resolved: Value?) -> TaskResult<int>
    match frame.state
        case 0:
            return TaskResult.Spawn(
                frame with { state: 1 },
                filter_negatives(frame.data)
            )
        case 1:
            filtered = resolved as List<int>
            return TaskResult.Spawn(
                frame with { state: 2, filtered: filtered },
                double_values(filtered)
            )
        case 2:
            doubled = resolved as List<int>
            return TaskResult.Spawn(
                frame with { state: 3, doubled: doubled },
                sum_values(doubled)
            )
        case 3:
            sum = resolved as int
            return TaskResult.Done(sum)
    ~
~
```

### 4.4 Frame Design

- Original variable names preserved
- Variants use mangled names with `__N` suffix
- Frame is immutable heap value, traced by GC
- Monomorphized frames for generic tasks

## 5. Task State

### 5.1 Data Structures

```
SuspendedTask:
    frame: Frame
    step_fn: func(Frame, Value?) -> TaskResult
    waiter: TaskID?              # Linked structure: who to wake on completion
    cancelled: atomic_bool       # Cooperative cancellation flag

TaskResult<T>:
    case Spawn(frame: Frame, subtask: SuspendedTask)
    case Done(value: T)
    case Send(frame: Frame, channel: Channel, value: Value)
    case Receive(frame: Frame, channel: Channel)
```

### 5.2 Task IDs

Allocated from atomic counter. Simple, no recycling needed.

## 6. Scheduler Core Loop

```
func worker_loop():
    while not shutdown.load()
        task = steal_work()
        if task == nil
            park_until_signaled()
            continue
        ~
        run_task(task)
    ~
~

func run_task(task: SuspendedTask):
    if task.cancelled.load()
        return  # Discard cancelled task
    ~
    
    result = task.step_fn(task.frame, task.pending_value)
    
    if task.cancelled.load()
        return  # Cancelled mid-flight, discard result
    ~
    
    match result
        case Done(value):
            if task.waiter != nil
                wake_with_value(task.waiter, value)
            ~
        
        case Spawn(new_frame, subtask):
            subtask.waiter = task.id
            suspended[task.id] = task with { frame: new_frame }
            ready_queue.push(subtask)
        
        case Send(new_frame, channel, value):
            try_send_or_park(task.id, new_frame, channel, value)
        
        case Receive(new_frame, channel):
            try_receive_or_park(task.id, new_frame, channel)
    ~
~
```

## 7. Channels

### 7.1 Unified User Model

Users see `Channel<T>`. Compiler infers implementation based on escape analysis.

### 7.2 Two Implementations

**TaskChannel** (task-to-task only):
- Scheduler-managed wait queues
- No mutex, no condition variable
- Lightweight, fast path

**ThreadChannel** (crosses thread-task boundary):
- Mutex protects buffer and wait queues
- Condition variable for thread-side blocking
- Used when channel escapes to func/thread context

### 7.3 Buffer

Unbounded, grows as needed.

### 7.4 Operations

Send:
1. If buffer has space → enqueue, wake one receiver if any
2. If buffer full → park sender on wait queue (tasks) or block (threads)

Receive:
1. If buffer has data → dequeue, wake one sender if any
2. If buffer empty → park receiver on wait queue (tasks) or block (threads)

## 8. Structured Concurrency

### 8.1 `first`

Spawns N tasks, returns first successful result, cancels siblings.

```
FirstContext:
    parent: TaskID
    children: List<TaskID>
    done: atomic_bool
    winner_value: Value?
```

Winner determination:
- First child to complete does `done.compare_exchange(false, true)`
- Winner stores result, marks siblings cancelled, wakes parent
- Losers see `done == true`, discard their results

### 8.2 `most`

Spawns N tasks, collects all successes and errors.

```
MostContext:
    parent: TaskID
    children: List<TaskID>
    results: List<Value>
    errors: List<Error>
    remaining: atomic_int
```

Completion:
- Each child decrements `remaining` on completion
- When `remaining` hits zero, wake parent
- Parent receives `(results, errors)` tuple

## 9. Cancellation

### 9.1 Cooperative Model

Cancellation is cooperative. Tasks check `cancelled` flag at suspension points.

### 9.2 Lazy Propagation

When a parent is cancelled, children continue to completion but their results are discarded:

- Child completes, tries to wake parent
- Sees parent cancelled, discards result
- No explicit tree traversal needed

### 9.3 Cleanup

Cancelled tasks and orphaned frames are cleaned up by GC. No explicit cleanup pass.

## 10. Static Analysis

### 10.1 Atomic Spin Detection

Detect unbounded loops with atomic-dependent termination conditions in task context:

```coex
task wait_for_ready(flag: atomic_bool) -> void
    #@ [ATOMIC_SPIN] Loop condition depends on atomic load; may starve scheduler
    while not flag.load()
        do_something()
    ~
~
```

Analysis:
1. Identify loops in task bodies
2. Compute taint set for termination condition
3. Check if atomic loads flow into taint set
4. Warn on unbounded loops (skip bounded loops with fixed iteration count)

### 10.2 Warning Insertion

Warnings inserted via `#@` system, persisted in source.

## 11. Error Handling

Tasks return errors through return types. No special propagation mechanism.

If a task returns `Result<T, E>` and fails, the error value flows back through the normal completion path. Parent receives the error and handles it according to its logic.

## 12. Design Rationale

### Why Stackless?

Coex's value semantics eliminate the complexity that makes stackless coroutines difficult elsewhere. No mutable borrows across yield points, no lifetime analysis, no pinning. A suspended task is just immutable data.

### Why Linked Waiter Structure?

Coex's function kind system guarantees single-waiter semantics for task calls. A task call has exactly one caller waiting. The simpler linked structure suffices; no need for a wait map.

### Why Cooperative Cancellation?

With explicit-only suspension points and no preemption, cooperative cancellation is the natural fit. Lazy propagation lets cancelled subtrees drain without explicit traversal.

### Why Lazy Worker Initialization?

"No hidden machinery" — programs that don't use tasks pay nothing. The worker pool materializes on demand and persists because it will likely be reused.

### Why Unified Channels?

Simple user model. The compiler bears the complexity of choosing the right implementation. Users think in terms of channels, not synchronization mechanisms.

### Why Extern Outside the Hierarchy?

Extern declarations are not Coex functions — they're boundary markers for foreign code. They don't have calling semantics; they're called by thread/func and return values. Placing them outside the hierarchy makes this distinction clear.

---

*Document derived from architecture discussion, January 2025.*
