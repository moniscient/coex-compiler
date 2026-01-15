# Coex Task Concurrency Implementation Prompt

## For Claude Code / Implementation Agent

---

## Context

You are implementing task-based structured concurrency for the Coex programming language. Coex is an LLVM-based language with:

- Immutable heap with value semantics
- Handle-based indirection (all heap references go through an indirection table)
- Per-thread shadow stacks for GC root discovery
- Existing GC with `gc_register_thread()`, `gc_unregister_thread()`, `gc_push_frame()`, `gc_pop_frame()`
- No closures (all data passing is explicit via parameters)

The implementation target is the existing `codegen.py` file which generates LLVM IR via llvmlite.

---

## Implementation Phases

### Phase 1: Thread Infrastructure

**Objective:** Create the low-level primitives for thread spawning, joining, and cancellation.

**Files to create/modify:**

1. **coex_thread.c** — C runtime support (linked into compiled programs)

```c
#include <pthread.h>
#include <stdatomic.h>

typedef struct TaskClosure {
    void* params;           // Pointer to parameter struct
    void* result;           // Slot for return value (handle)
    atomic_bool cancelled;  // Cancellation flag
    atomic_bool completed;  // Completion flag
    void* exception;        // Exception if failed (handle)
    pthread_mutex_t mutex;  // For completion signaling
    pthread_cond_t cond;    // For completion signaling
} TaskClosure;

typedef void (*TaskEntry)(TaskClosure*);

// Spawn a new thread running the given task
pthread_t coex_thread_spawn(TaskEntry entry, TaskClosure* closure);

// Join a thread, block until completion
void coex_thread_join(pthread_t thread);

// Wait for first completion among multiple threads
// Returns index of completed thread, sets cancellation on others
int coex_thread_wait_first(pthread_t* threads, TaskClosure** closures, int count);

// Wait for all threads to complete
void coex_thread_wait_all(pthread_t* threads, int count);

// Request cancellation
void coex_thread_cancel(TaskClosure* closure);

// Check cancellation (called at safepoints)
bool coex_thread_is_cancelled(TaskClosure* closure);
```

2. **Nursery structure** — Add to codegen.py

```python
# Per-function nursery for bare task calls
# Stored in function's local variables
class Nursery:
    handles: List[pthread_t]      # Thread handles
    closures: List[TaskClosure*]  # Closure pointers
```

**Implementation notes:**

- Use pthread_create/pthread_join for thread management
- TaskClosure is heap-allocated (use existing GC allocation)
- The completion condvar allows wait_first to wake on any completion
- Link coex_thread.c into the runtime library

---

### Phase 2: Task Call Codegen

**Objective:** Generate LLVM IR for task function calls, including bare calls and collection blocks.

**Modify:** `codegen.py`

**2.1 Task Entry Trampoline**

Each task function needs a trampoline that:
1. Calls `gc_register_thread()`
2. Sets up shadow stack
3. Extracts parameters from TaskClosure
4. Calls the actual task body
5. Stores result in TaskClosure (or exception on failure)
6. Signals completion
7. Calls `gc_unregister_thread()`

```python
def _generate_task_trampoline(self, task_func: FunctionDecl):
    """Generate entry trampoline for a task function."""
    # Trampoline signature: void trampoline(TaskClosure* closure)
    
    # 1. Register with GC
    # 2. Extract params from closure->params
    # 3. Try: call task body, store result in closure->result
    # 4. Catch: store exception in closure->exception
    # 5. Signal completion (set flag, broadcast condvar)
    # 6. Unregister from GC
```

**2.2 Bare Task Call**

When encountering a task call as a statement (not assignment):

```python
def _generate_bare_task_call(self, call_expr: CallExpr):
    """Generate code for fire-and-forget task call."""
    
    # 1. Allocate TaskClosure
    closure = self._allocate_task_closure(call_expr.args)
    
    # 2. Spawn thread
    handle = self._call_runtime("coex_thread_spawn", [trampoline, closure])
    
    # 3. Add to function's nursery
    self._nursery_append(handle, closure)
```

**2.3 Function Exit Join**

Modify function epilogue generation:

```python
def _generate_function_epilogue(self):
    """Generate function exit code including nursery join."""
    
    # Join all bare-call tasks before returning
    if self._has_nursery():
        self._generate_nursery_join_all()
    
    # Existing: gc_pop_frame(), return
```

---

### Phase 3: For Collection Block

**Objective:** Implement the `for item in items` task collection pattern.

**AST recognition:** Detect when ForAssignStmt body is a task call.

```python
def _generate_for_assign_stmt(self, stmt: ForAssignStmt):
    if self._is_task_call(stmt.body_expr):
        self._generate_for_task_collection(stmt)
    else:
        self._generate_for_assign_sequential(stmt)  # Existing behavior

def _generate_for_task_collection(self, stmt: ForAssignStmt):
    """Generate all-or-nothing parallel for loop."""
    
    # 1. Create block-local nursery
    block_nursery_handles = []
    block_nursery_closures = []
    
    # 2. Iterate and spawn
    for item in iterable:
        closure = allocate_closure(item, other_args)
        handle = spawn_thread(trampoline, closure)
        block_nursery_handles.append(handle)
        block_nursery_closures.append(closure)
    
    # 3. Wait all with error checking
    for i, handle in enumerate(block_nursery_handles):
        join(handle)
        if block_nursery_closures[i].exception:
            # Cancel remaining threads
            for j in range(i+1, len(block_nursery_closures)):
                cancel(block_nursery_closures[j])
            for j in range(i+1, len(block_nursery_handles)):
                join(block_nursery_handles[j])
            # Propagate exception
            raise block_nursery_closures[i].exception
    
    # 4. Collect results into List<T>
    results = []
    for closure in block_nursery_closures:
        results.append(closure.result)
    
    # 5. Assign to target variable
    target = results
```

---

### Phase 4: First Collection Block

**Objective:** Implement the `first item in items` racing pattern.

**New AST node or flag:** Add `FirstAssignStmt` or add `collection_mode` enum to ForAssignStmt.

```python
def _generate_first_task_collection(self, stmt: FirstAssignStmt):
    """Generate first-wins racing collection."""
    
    # 1. Create block-local nursery
    # 2. Iterate and spawn all
    
    # 3. Wait for first success
    while True:
        completed_idx = wait_for_any_completion(handles, closures)
        closure = closures[completed_idx]
        
        if closure.exception is None:
            # Winner found
            result = closure.result
            break
        else:
            # This one failed, mark it done, continue waiting
            mark_done(completed_idx)
            if all_done():
                # All failed
                raise AggregateException(all_exceptions)
    
    # 4. Cancel remaining threads
    for i, closure in enumerate(closures):
        if i != completed_idx and not is_done(i):
            cancel(closure)
    
    # 5. Join all threads
    for handle in handles:
        join(handle)
    
    # 6. Assign winner's result
    target = result
```

**Runtime support for wait_first:**

The `coex_thread_wait_first` function uses a shared condition variable. Each task signals this condvar on completion. The waiting thread wakes and checks which task(s) completed.

```c
int coex_thread_wait_first(pthread_t* threads, TaskClosure** closures, int count) {
    // All closures share a "group" condvar for this collection
    // Wait on condvar, then scan for completed tasks
    // Return index of first completed (success or failure)
}
```

---

### Phase 5: Most Collection Block

**Objective:** Implement the `most item in items` best-effort pattern.

```python
def _generate_most_task_collection(self, stmt: MostAssignStmt):
    """Generate best-effort collection."""
    
    # 1. Create block-local nursery
    # 2. Iterate and spawn all
    
    # 3. Wait for ALL to complete (no cancellation)
    for handle in handles:
        join(handle)
    
    # 4. Partition results
    successes = []
    failures = []
    for closure in closures:
        if closure.exception is None:
            successes.append(closure.result)
        else:
            failures.append(closure.exception)
    
    # 5. Assign tuple to targets
    target = (successes, failures)
```

This is the simplest collection strategy—no cancellation logic, just partition at the end.

---

### Phase 6: Cancellation Safepoints

**Objective:** Inject cancellation checks at compiler-determined safepoints.

**Safepoint locations:**

1. **Loop back-edges:** At the start of each loop iteration
2. **Channel operations:** Before blocking send/receive
3. **Function prologues:** At entry to each function (task functions only? or all?)
4. **Allocation sites:** Already safepoints for GC

**Cancellation check code:**

```python
def _generate_cancellation_check(self):
    """Generate cancellation check at safepoint."""
    
    # Only in task functions
    if not self._in_task_function():
        return
    
    # Load cancellation flag
    closure_ptr = self._get_current_closure()
    cancelled_ptr = gep(closure_ptr, [0, CANCELLED_FIELD_INDEX])
    cancelled = load_atomic(cancelled_ptr, ordering='acquire')
    
    # Branch on cancelled
    with self.builder.if_then(cancelled):
        self._generate_cancellation_unwind()

def _generate_cancellation_unwind(self):
    """Generate early exit on cancellation."""
    # Set completion flag
    # Signal condvar
    # gc_unregister_thread()
    # pthread_exit(NULL)
```

**Integration points:**

- `_generate_while_stmt`: Add check at loop entry
- `_generate_for_stmt`: Add check at iteration start
- `_generate_loop_stmt`: Add check at loop entry
- Channel operations: Add check before blocking

---

### Phase 7: Single Assignment Warning

**Objective:** Emit warning when task is assigned to single variable.

**Detection:** In `_generate_assignment`, check if RHS is a task call.

```python
def _generate_assignment(self, stmt: Assignment):
    if self._is_task_call(stmt.value):
        # Emit warning
        self._emit_warning(
            stmt.location,
            "Single task assignment executes sequentially. "
            "Use 'for', 'first', or 'most' for concurrent execution."
        )
        # Generate sequential execution: spawn, join, assign
        self._generate_sequential_task_call(stmt)
    else:
        # Existing assignment logic
        ...
```

**Warning format:**

```
#@ warning: Single task assignment executes sequentially.
#@          Use 'for', 'first', or 'most' for concurrent execution.
```

---

## Data Structures

### TaskClosure Layout

```
struct TaskClosure {
    i8*          params;      // Pointer to parameter struct
    i8*          result;      // Return value (handle or pointer)
    i8*          exception;   // Exception if failed
    i8           cancelled;   // Atomic bool: cancellation requested
    i8           completed;   // Atomic bool: task finished
    i8*          mutex;       // pthread_mutex_t*
    i8*          cond;        // pthread_cond_t*
}
```

### Parameter Struct

Generated per-task-call-site:

```
struct TaskParams_<task_name>_<site_id> {
    <type1> param1;
    <type2> param2;
    ...
}
```

### Nursery (Function-Level)

```python
# In function's local state during codegen
self.nursery_handles = []   # List of LLVM values (pthread_t)
self.nursery_closures = []  # List of LLVM values (TaskClosure*)
```

---

## Runtime Functions to Implement

```c
// Thread lifecycle
pthread_t coex_thread_spawn(void (*entry)(TaskClosure*), TaskClosure* closure);
void coex_thread_join(pthread_t thread);

// Synchronization
void coex_completion_init(TaskClosure* closure);
void coex_completion_signal(TaskClosure* closure);
int coex_completion_wait_any(TaskClosure** closures, int count);
void coex_completion_wait_all(TaskClosure** closures, int count);

// Cancellation
void coex_cancel_request(TaskClosure* closure);
bool coex_cancel_check(TaskClosure* closure);

// Allocation
TaskClosure* coex_closure_alloc(size_t params_size);
void* coex_params_alloc(size_t size);
```

---

## Testing Strategy

### Unit Tests

1. **Single bare call:** Spawn one task, verify join at function exit
2. **Multiple bare calls:** Spawn several, verify all join
3. **For collection:** Spawn N tasks, collect N results in order
4. **For with failure:** One task fails, verify others cancelled
5. **First collection:** Spawn N, verify first success wins
6. **First all fail:** Verify aggregate error
7. **Most collection:** Spawn N with some failures, verify partition
8. **Cancellation latency:** Verify prompt response to cancellation flag

### Integration Tests

1. **Nested tasks:** Function spawns tasks that spawn tasks
2. **Channel communication:** Tasks communicating via channels
3. **GC under concurrency:** Verify GC correctly traces multi-threaded roots
4. **Error propagation:** Exceptions cross thread boundaries correctly

---

## Files Summary

| File | Purpose |
|------|---------|
| `coex_thread.c` | C runtime: pthread wrappers, completion signaling |
| `coex_thread.h` | Header for runtime functions |
| `codegen.py` | Modify: task call generation, nursery, safepoints |
| `ast_nodes.py` | Add: FirstAssignStmt, MostAssignStmt (or flags) |
| `parser.py` | Add: parsing for `first` and `most` keywords |
| `tests/test_tasks.coex` | Test programs |

---

## Implementation Order

1. **coex_thread.c/h:** Build and test runtime in isolation
2. **Basic spawn/join:** Bare calls with function-exit join
3. **For collection:** All-or-nothing with ordered results
4. **Cancellation:** Safepoint injection and cooperative exit
5. **First collection:** Racing with cancellation
6. **Most collection:** Best-effort partitioning
7. **Single assignment warning:** Detection and warning emission
8. **Integration testing:** Full system tests

---

## Key Invariants to Maintain

1. Every `coex_thread_spawn` has exactly one corresponding `coex_thread_join`
2. Every spawned thread calls `gc_register_thread` before any allocation and `gc_unregister_thread` before exit
3. TaskClosure remains live (not collected) until after join extracts result
4. Cancellation flag is checked at every safepoint in task functions
5. Results are collected in iteration order for `for` blocks
6. No thread outlives its spawning function
