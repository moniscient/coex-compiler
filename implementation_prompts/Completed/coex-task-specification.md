# Coex Task Concurrency Specification

## Version 1.0

---

## 1. Overview

This specification defines the semantics for task-based structured concurrency in the Coex programming language. The design enforces that concurrent operations have clear entry points, clear exit points, explicit data flow, and guaranteed cleanup. No task can outlive its parent scope.

Coex achieves structured concurrency through:

- Explicit parameter passing (no closures or captured variables)
- Three collection strategies with distinct join semantics (`for`, `first`, `most`)
- Cooperative cancellation with compiler-injected safepoints
- Mandatory joins before scope exit

---

## 2. Function Kinds

Coex distinguishes three function kinds relevant to concurrency:

**formula** — Pure computation. Guaranteed termination, no I/O, no channels, no side effects. May be auto-parallelized by the compiler.

**task** — Concurrent execution unit. When called, spawns an OS thread. May use channels for communication. Designed for concurrent use via collection blocks.

**func** — Unrestricted. May perform I/O, call FFI, use channels, spawn tasks. The entry point `main` is always a `func`.

A task function is declared with the `task` keyword:

```coex
task process_item(item: Item) -> Result
    # ... computation ...
    return result
~
```

---

## 3. Task Invocation Patterns

### 3.1 Bare Calls (Fire-and-Forget)

A task called without assignment spawns a thread and continues immediately. The spawning function must wait for all bare-call tasks to complete before returning.

```coex
func parent()
    log_event("starting")     # Spawns, continues immediately
    do_work()
    log_event("finished")     # Spawns, continues immediately
    
    # Implicit join barrier: both log_event calls must complete
    # before parent() returns
~
```

Return values from bare calls are discarded. This pattern is suitable for side-effecting tasks where the caller does not need results.

### 3.2 Single Assignment (Sequential with Warning)

A task assigned to a single variable executes sequentially: spawn, immediate join, assign result.

```coex
result = my_task(params)    #@ warning: Single task assignment executes sequentially.
                            #@          Use 'for', 'first', or 'most' for concurrent execution.
```

This compiles and runs correctly but defeats the purpose of using a task. The compiler emits a warning to alert the programmer that no concurrency is achieved. This pattern exists to support testing and gradual refactoring, not as a recommended practice.

### 3.3 For Collection (All-or-Nothing)

The `for` block spawns tasks for all items, waits for all to complete, and collects all results. If any task fails, siblings are cancelled and the error propagates.

```coex
results = for item in items
    process(item)
~
# results: List<T>
```

**Semantics:**

1. For each item in the iterable, allocate a TaskClosure and spawn a thread
2. Wait for all threads to complete
3. If any task throws an exception:
   - Set cancellation flag on all siblings
   - Wait for siblings to reach safepoint and exit
   - Propagate the first exception to the caller
4. If all succeed, collect results in iteration order into `List<T>`

**Use cases:** Batch processing where partial results are not useful; transactions; all-or-nothing validation.

### 3.4 First Collection (Racing)

The `first` block spawns tasks for all items, returns as soon as one succeeds, and cancels the rest.

```coex
result = first server in servers
    fetch_from(server)
~
# result: T
```

**Semantics:**

1. For each item in the iterable, allocate a TaskClosure and spawn a thread
2. Wait for any thread to complete successfully
3. On first success:
   - Set cancellation flag on all other threads
   - Wait for them to reach safepoint and exit
   - Return the winner's result
4. If a task fails, it simply does not win (continue waiting for others)
5. If all tasks fail, propagate a combined error

**Use cases:** Latency racing; redundant requests; speculative execution; search problems where any solution suffices.

### 3.5 Most Collection (Best-Effort)

The `most` block spawns tasks for all items, waits for all to complete, and partitions results into successes and failures.

```coex
(successes, failures) = most source in sources
    fetch_data(source)
~
# successes: List<T>
# failures: List<Error>
```

**Semantics:**

1. For each item in the iterable, allocate a TaskClosure and spawn a thread
2. Wait for all threads to complete (no cancellation on failure)
3. Partition results: successful returns go to the first list, exceptions go to the second
4. Return the tuple

**Use cases:** Best-effort data collection; aggregation with partial failure tolerance; health checks across multiple services.

---

## 4. Data Flow

### 4.1 No Closures

Coex does not support closure capture. All data passed to a task must be explicit parameters:

```coex
func parent()
    config = load_config()
    data = fetch_data()
    
    # CORRECT: explicit parameters
    results = for item in data
        process(item, config)    # config passed explicitly
    ~
~
```

There is no implicit environment capture. This simplifies the memory model, makes data flow obvious on the page, and ensures GC traceability through explicit handles.

### 4.2 Parameter Passing

Task parameters are copied into a heap-allocated TaskClosure before thread spawn. Since all Coex heap data is immutable and accessed through handles, "copying" means copying handle values (integers). The underlying immutable objects are safely shared.

The TaskClosure contains:

- Copies of all parameter handles
- A slot for the return value (written by the task)
- A cancellation flag (atomic boolean)
- Thread synchronization primitives

### 4.3 Return Values

Tasks may return values. The return value is written to the TaskClosure by the task thread and read by the parent after join. For collection blocks:

- `for` returns `List<T>` (ordered by iteration)
- `first` returns `T` (the winner)
- `most` returns `(List<T>, List<Error>)` (partitioned)

---

## 5. Structured Concurrency Guarantees

### 5.1 Lifetime Invariant

A task cannot outlive the function that spawned it. This is enforced by mandatory joins:

- Bare calls join at function exit
- Collection blocks join at block end

### 5.2 Function-Level Nursery

Each function maintains a nursery for bare-call tasks. The nursery is a list of ThreadHandles. At function exit, before popping the GC frame, all threads in the nursery are joined.

```
Function entry:
    gc_push_frame()
    nursery = []

Task bare call:
    closure = allocate_closure(params)
    handle = spawn_thread(task_entry, closure)
    nursery.append(handle)

Function exit:
    for handle in nursery:
        join_thread(handle)
    gc_pop_frame()
    return
```

### 5.3 Block-Level Collection

Collection blocks (`for`, `first`, `most`) maintain their own temporary nursery. This nursery is local to the block and does not escape to the function-level nursery.

```
Collection block entry:
    block_nursery = []

For each iteration:
    closure = allocate_closure(item, params)
    handle = spawn_thread(task_entry, closure)
    block_nursery.append(handle)

Collection block exit:
    results = join_strategy(block_nursery)  # for/first/most specific
    # block_nursery is discarded
```

---

## 6. Cancellation

### 6.1 Cooperative Model

Cancellation is cooperative. Each task has an atomic boolean flag in its TaskClosure. When cancellation is requested, this flag is set to true. The task must check this flag at safepoints and exit promptly when set.

### 6.2 Safepoints

The compiler injects cancellation checks at:

- Loop back-edges (beginning of each iteration)
- Channel send/receive operations
- Function call prologues
- Allocation sites (already GC safepoints)

A cancellation check is approximately:

```
if closure.cancelled.load(Acquire):
    unwind_and_exit()
```

### 6.3 Cancellation Triggers

**For blocks:** First exception triggers cancellation of all siblings.

**First blocks:** First success triggers cancellation of all other tasks.

**Most blocks:** No cancellation occurs; all tasks run to completion.

### 6.4 Teardown Guarantee

After setting cancellation flags, the parent waits for all threads to complete (either normally or via cancellation exit) before proceeding. This ensures no orphaned threads and proper resource cleanup.

---

## 7. Error Handling

### 7.1 Exception Propagation

Tasks may throw exceptions. The handling depends on the collection strategy:

**For blocks:**
- First exception: cancel siblings, wait for completion, propagate exception
- No partial results are returned

**First blocks:**
- Failed tasks do not win (continue waiting)
- All tasks failed: combine errors into aggregate exception, propagate
- At least one success: return winner, discard failures

**Most blocks:**
- No cancellation on failure
- Failures collected into error list
- Both successes and failures returned to caller

### 7.2 Error Types

Exceptions are captured as Coex's standard `Error` type. For `most` blocks and aggregate errors in `first` blocks, multiple errors may be returned or combined.

---

## 8. Memory Model Integration

### 8.1 GC Interaction

Tasks integrate with the Coex garbage collector:

**Thread registration:** Each spawned thread calls `gc_register_thread()` on entry and `gc_unregister_thread()` on exit.

**Shadow stack:** Each thread maintains its own shadow stack for GC root discovery.

**Handle safety:** Since all heap data is immutable and accessed through the indirection table, handles passed to tasks remain valid even during concurrent GC relocation.

### 8.2 TaskClosure Lifecycle

1. Allocated by parent before spawn
2. Passed to child thread as entry argument
3. Written by child (return value or exception)
4. Read by parent after join
5. Becomes garbage after parent extracts result

The TaskClosure itself is a heap object traced by the GC.

---

## 9. Thread Implementation

### 9.1 OS Threads

Each task spawns a true OS thread via pthread_create (or platform equivalent). This provides:

- Preemptive scheduling by the OS kernel
- Full stack per thread
- Native debugger support

### 9.2 Future Optimization

Future versions may optimize certain tasks to use lighter-weight execution (coroutines, work-stealing) when the compiler can prove it safe. The semantics remain unchanged; only the implementation varies.

---

## 10. Syntax Summary

```coex
# Task declaration
task name(params) -> ReturnType
    body
~

# Bare call (fire-and-forget)
task_name(args)

# Single assignment (sequential, warns)
result = task_name(args)

# For collection (all-or-nothing)
results = for item in iterable
    task_name(item, args)
~

# First collection (racing)
result = first item in iterable
    task_name(item, args)
~

# Most collection (best-effort)
(successes, failures) = most item in iterable
    task_name(item, args)
~
```

---

## 11. Examples

### 11.1 Parallel Processing Pipeline

```coex
task validate(item: Item) -> Item
    if not item.is_valid()
        throw ValidationError(item.id)
    ~
    return item
~

task process(item: Item) -> Result
    return expensive_computation(item)
~

func run_pipeline(items: List<Item>) -> List<Result>
    # Validate all items (fail fast on any invalid)
    validated = for item in items
        validate(item)
    ~
    
    # Process all validated items
    results = for item in validated
        process(item)
    ~
    
    return results
~
```

### 11.2 Redundant Fetch with Racing

```coex
task fetch_from(server: Server) -> Response
    return http_get(server.url + "/data")
~

func fetch_resilient(servers: List<Server>) -> Response
    response = first server in servers
        fetch_from(server)
    ~
    return response
~
```

### 11.3 Best-Effort Data Collection

```coex
task scrape(source: Source) -> Data
    return download_and_parse(source.url)
~

func collect_data(sources: List<Source>) -> Report
    (data, errors) = most source in sources
        scrape(source)
    ~
    
    if len(data) == 0
        throw AllSourcesFailed(errors)
    ~
    
    log_failures(errors)
    return aggregate(data)
~
```

### 11.4 Background Logging (Fire-and-Forget)

```coex
task log_async(message: string, level: Level)
    timestamp = now()
    formatted = format_log(timestamp, level, message)
    append_to_file(log_path, formatted)
~

func process_request(request: Request) -> Response
    log_async("Received: " + request.id, Level.INFO)
    
    response = handle(request)
    
    log_async("Completed: " + request.id, Level.INFO)
    
    return response
    # Both log_async calls complete before process_request returns
~
```

---

## 12. Invariants Summary

1. **No orphaned tasks:** Every spawned task is joined before its parent scope exits.

2. **Explicit data flow:** All task inputs are explicit parameters; no closure capture.

3. **Cooperative cancellation:** Tasks check cancellation flag at compiler-injected safepoints.

4. **Ordered results:** `for` block results maintain iteration order.

5. **Error propagation:** `for` fails fast; `first` tolerates failures until all fail; `most` collects all.

6. **Memory safety:** Tasks share immutable data through handles; GC traces roots via shadow stacks.
