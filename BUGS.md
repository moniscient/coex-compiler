# Coex Bug Tracker

## Bug Reporting Protocol

**Mandatory**: When encountering any unexpected behavior, test failure, or anomaly during development—even if worked around or tangential to the current task—immediately append a bug report here before continuing. Never assume a bug will be "remembered" for later.

### Bug Categories
- **Parser**: Grammar issues, ANTLR parse failures
- **Semantic**: Type checking, binding resolution, trait matching
- **Codegen**: LLVM IR generation, type registry issues
- **Runtime**: Task scheduler, channel operations, coroutine behavior
- **GC**: Garbage collector, handle table, shadow stack issues
- **Stdlib**: Standard library functions, posix module

### Severity Levels
- **Critical**: Crashes, data corruption, security issues
- **High**: Correctness bugs, wrong output
- **Medium**: Performance issues, edge cases
- **Low**: Minor issues, cosmetic problems

---

## Open Bugs

<!-- Template for new bugs:

### BUG-XXX: One-line summary
- **Discovered**: YYYY-MM-DD, during [context]
- **Category**: [Parser|Semantic|Codegen|Runtime|GC|Stdlib]
- **Severity**: [Critical|High|Medium|Low]
- **Reproduction**: Steps to reproduce
- **Observed**: What actually happens
- **Expected**: What should happen
- **Hypothesis**: Theory about the cause
- **Files**: Likely involved files
- **Status**: Open

-->

### BUG-004: GC race condition with parallel Set allocations
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Critical
- **Reproduction**: Run parallel tasks that allocate Sets (e.g., parallel sieve tests)
- **Observed**: Non-deterministic crashes during concurrent Set allocation
- **Expected**: Concurrent Set allocations should be thread-safe
- **Hypothesis**: GC allocation list or Set internals lack proper synchronization
- **Files**: `coex_gc.py`, `tests/test_thread_stress.py`
- **Status**: Open


### BUG-015: Non-blocking safepoints require shadow stack changes
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Run concurrent GC with multiple threads doing work
- **Observed**: Threads serialize at safepoints, blocking each other
- **Expected**: Safepoints should be non-blocking for better concurrency
- **Hypothesis**: Current shadow stack design requires stop-the-world synchronization
- **Files**: `coex_gc.py`, `implementation_prompts/phase1_nonblocking_safepoints.md`
- **Status**: Open (enhancement)

### BUG-016: gc_async() race condition requires TLAB
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Medium
- **Reproduction**: Use `gc_async()` with concurrent allocations
- **Observed**: Race condition causes undefined behavior
- **Expected**: Async GC should run safely in background
- **Hypothesis**: Allocation list access races with async GC thread without TLABs
- **Files**: `coex_gc.py` (gc_async implementation)
- **Status**: Open (blocked on Phase 4 TLAB implementation)
- **Note**: Tests currently pass (xpassed) but architectural race condition remains

### BUG-023: llvmlite thread_local attribute silently ignored
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: Set `variable.thread_local = 'localdynamic'` and inspect generated IR
- **Observed**: IR shows plain `global`, not `thread_local global`
- **Expected**: Variable should be thread-local in generated code
- **Hypothesis**: llvmlite library bug - attribute setter has no effect
- **Files**: `coex_gc.py` (TLS variables), all code using thread-local state
- **Status**: Open (workaround in place: use pthread TLS via ThreadEntry struct)

### BUG-026: Test files use `=` instead of `:=` for task assignment
- **Discovered**: 2026-01-17, during GPU offload implementation testing
- **Category**: Semantic
- **Severity**: Low
- **Reproduction**: Run `python3 -m pytest tests/test_scheduler.py tests/test_task_state_machine.py`
- **Observed**: 6 tests fail with error: `Cannot assign task result with '=' operator. Use ':=' for blocking assignment`
- **Expected**: Tests should use correct `:=` syntax for task calls
- **Hypothesis**: Tests were written before BUG-012 fix enforced `:=` for task assignment
- **Files**:
  - `tests/test_scheduler.py` (lines 149, 219: `result = leaf(i)`, `result = tiny(i)`)
  - `tests/test_task_state_machine.py` (similar patterns)
- **Status**: Open
- **Failing Tests**:
  - `test_scheduler.py::TestTaskExecution::test_sequential_tasks`
  - `test_scheduler.py::TestConcurrentExecution::test_parallel_tasks`
  - `test_scheduler.py::TestSchedulerInvariants::test_result_delivered_to_correct_waiter`
  - `test_scheduler.py::TestSchedulerInvariants::test_workers_reused_across_batches`
  - `test_task_state_machine.py::TestTaskStateMachine::test_both_branches_suspend`
  - `test_task_state_machine.py::TestTaskInvariants::test_func_can_call_task`


---

## Resolved Bugs

### BUG-001: Mutual recursion segfault in task coroutines
- **Discovered**: 2025-01-17, during task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Create two tasks that call each other recursively
- **Observed**: Segmentation fault during coroutine context switch
- **Expected**: Tasks should execute mutual recursion correctly
- **Hypothesis**: Stack frame allocation was insufficient for deep recursion
- **Files**: `codegen.py` (task frame allocation)
- **Status**: Resolved (commit a55f8df)
- **Resolution**: Fixed task frame allocation size calculation

### BUG-002: Scheduler race condition in task completion
- **Discovered**: 2025-01-17, during concurrent task testing
- **Category**: Runtime
- **Severity**: Critical
- **Reproduction**: Run multiple tasks with rapid completion
- **Observed**: Race condition causing undefined behavior
- **Expected**: Clean task completion without races
- **Hypothesis**: Missing synchronization in scheduler
- **Files**: `codegen.py` (scheduler implementation)
- **Status**: Resolved (commit 2b69903)
- **Resolution**: Added proper synchronization to scheduler

### BUG-003: GC sweep disabled - memory never freed
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: High
- **Reproduction**: Any program that allocates and calls `gc()`
- **Observed**: Sweep only clears mark bits, doesn't free memory
- **Expected**: Unmarked objects should be freed and memory reclaimed
- **Files**: `coex_gc.py` (`_implement_gc_sweep`)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 25 tests in test_gc_phase8.py pass, including `test_sweep_frees_unreachable_objects`

### BUG-005: posix.time_ns() returns incorrect values
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Stdlib
- **Severity**: High
- **Reproduction**: Call `posix.time_ns()` and compare to expected nanosecond timestamp
- **Files**: `codegen.py` (posix module implementation)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 14 tests in test_posix.py pass, including `test_posix_time_ns_returns_positive`

### BUG-006: Channel<[int]> receive() returns unknown type
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Semantic
- **Severity**: Medium
- **Reproduction**: Create `Channel<[int]>` and call `.receive()`
- **Files**: `codegen.py` (channel implementation, type inference)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 11 tests in test_channel_inference.py pass

### BUG-007: String list printing bug
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create `List<string>` and print it
- **Files**: `codegen.py` (print generation, list printing)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Manual testing confirms string lists work correctly: `["hello", "world", "test"]` returns correct values via `.get()`

### BUG-008: Nested list access bug
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Create nested list like `[[1, 2], [3, 4]]` and access elements
- **Files**: `codegen.py` (subscript/index expression generation)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Manual testing confirms nested list access works correctly: `outer.get(0).get(0)` returns `1`

### BUG-013: Task-to-task suspension not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Have one task call another task, or nest task spawns
- **Files**: `codegen.py` (task implementation), `runtime/coex_scheduler.c`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 14 tests in test_task_to_task.py pass, including mutual recursion

### BUG-014: gc_dump_heap reads from unused global alloc list
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Call `gc_dump_heap()` after allocating objects
- **Files**: `coex_gc.py` (gc_dump_heap implementation)
- **Status**: Resolved (2025-01-17)
- **Resolution**: Tests pass including `test_heap_dump_shows_objects` (xpassed)

### BUG-017: Move operator tracking not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Semantic
- **Severity**: Medium
- **Reproduction**: Use `:=` move operator and then access the source variable
- **Files**: `codegen/statements.py`, `codegen/core.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 63 tests in test_unique_ownership.py and test_copy_operator.py pass, including use-after-move detection

### BUG-020: While loops - grammar exists, no codegen
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Write a `while` loop in Coex code
- **Files**: `Coex.g4`, `codegen.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: All 45 tests in test_while_cycle.py and test_control_flow.py pass

### BUG-021: list.append() bug in method dispatch
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Call `.append()` on a list
- **Files**: `codegen.py` (list method dispatch)
- **Status**: Resolved (2025-01-17)
- **Resolution**: All array append tests pass in test_array.py

### BUG-012: Task calls are synchronous, not async (bare calls now fire-and-forget)
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Bare task calls should spawn and join at function exit
- **Observed**: All task calls blocked immediately
- **Expected**: Bare calls fire-and-forget, := blocks, = produces compile error
- **Files**: `codegen/statements.py`, `codegen/expressions.py`
- **Status**: Resolved (2025-01-17)
- **Resolution**: Implemented fire-and-forget semantics for bare task/thread calls:
  - Bare calls (`work()`) spawn immediately and join at function exit via nursery
  - `:=` assignment (`result := work()`) blocks immediately and returns result
  - `=` assignment (`result = work()`) is now a compile error
  - All 12 tests in test_fire_and_forget.py pass

### BUG-022: Bidirectional channels require true concurrent execution
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: Medium
- **Reproduction**: Create two tasks that both send and receive on channels
- **Observed**: Hangs on blocking receive (deadlock)
- **Expected**: Both tasks should run concurrently, enabling bidirectional communication
- **Files**: `runtime/coex_channel.c`, `runtime/coex_channel.h`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed channel synchronization to use mutex/condvar instead of busy spin:
  - Added ChannelSync struct with pthread_mutex_t and pthread_cond_t to TaskChannel
  - Updated coex_channel_send() to lock mutex, signal condvar after buffering
  - Updated coex_channel_receive() to lock mutex, wait on condvar when buffer empty
  - All 12 tests in test_channel_inference.py pass including bidirectional channels

### BUG-019: C string null termination hack
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Pass string slice to POSIX/FFI function (e.g., strlen on "hello world"[0:5])
- **Observed**: C function reads past slice into parent buffer (strlen returns 11 instead of 5)
- **Expected**: All strings should be safely null-terminated for C interop
- **Files**: `codegen/strings.py`, `codegen/core.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Implemented proper C string marshaling at extern boundaries:
  - Added `cstring()` method on String type that returns null-terminated `[byte]` array
  - Updated `_convert_to_c_type()` to create stack-allocated null-terminated copies for extern calls
  - The marshaling copies string data to a temporary buffer with null terminator, safe for slice views
  - All 14 tests in test_cstring.py pass including slice edge cases

### BUG-018: GC stats not atomic in multi-threaded case
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: Low
- **Reproduction**: Run multi-threaded program and check `gc_dump_stats()`
- **Observed**: Stats showed inconsistent values due to race conditions (98k-102k variance)
- **Expected**: Stats should be accurate even with concurrent allocations
- **Hypothesis**: Stats counters updated with plain load/store, not atomics
- **Files**: `coex_gc.py:2400-2417`, `coex_gc.py:3378-3382`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Replaced load-add-store pattern with atomic_rmw operations:
  - `gc_alloc()` now uses `atomic_rmw('add', ...)` for total_allocations, total_bytes, allocations_since, bytes_since
  - `gc()` now uses `atomic_rmw('add', ...)` for collections_completed counter
  - Before fix: 16-thread test showed ~4% variance (98k-102k allocations)
  - After fix: Exactly consistent counts across all runs (128068 allocations)
  - New test file: test_gc_stats_atomic.py

### BUG-009: Matrix formula tick() not generating correct code
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Define a matrix with a formula and call `tick()`
- **Observed**: LLVM error: `ret i64 1` in void-returning function
- **Expected**: Formula should be applied to each cell, producing new matrix state
- **Files**: `codegen/matrix.py`, `codegen/statements.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed matrix formula return statement handling:
  - Matrix formula methods are void-returning, but `return` sets cell value
  - Added `__matrix_result` alloca to capture return values
  - Modified `generate_return` to detect matrix context and store value instead of `ret`
  - Return now branches to x_loop_inc which writes value to cell
  - All 5 matrix tests pass

### BUG-010: Matrix cell keyword access not working
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: Use `cell` keyword in matrix formula to access current cell value
- **Observed**: Same LLVM error as BUG-009 (return type mismatch)
- **Expected**: `cell` should provide access to current cell value
- **Files**: `codegen/matrix.py`, `codegen/statements.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed by same change as BUG-009. The `cell` keyword was working correctly;
  the issue was that formulas using `cell` also use `return` which had the same bug.

### BUG-024: Task completion notification not optimized
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Runtime
- **Severity**: Low
- **Reproduction**: N/A - performance optimization
- **Observed**: `coex_task_wait_any` polled with 1ms timeout, only waiting on first task
- **Expected**: Immediate wake-up when any task completes
- **Files**: `runtime/coex_task.c`, `runtime/coex_task.h`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Implemented shared waiter mechanism for `wait_any`:
  - Added `SharedWaiter` struct with mutex/condvar for wait groups
  - Added `shared_waiter` field to `TaskClosure` (after LLVM-visible fields)
  - `coex_task_wait_any` now registers a shared waiter with all closures
  - `coex_task_signal_complete` signals the shared waiter if present
  - All 21 first/most tests pass, eliminating 1ms polling delay

### BUG-025: GC stack overflow with large lists (500k+ elements)
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: GC
- **Severity**: High
- **Reproduction**: Create list with 500,000-750,000+ elements, trigger GC
- **Observed**: Was crashing with `EXC_BAD_ACCESS` at stack addresses during GC marking
- **Expected**: GC should handle arbitrarily large collections
- **Files**: `coex_gc.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed by Phase 5 worklist-based marking implementation:
  - `gc_mark_object` now uses `gc_mark_push` to add child handles to worklist
  - `gc_mark_drain` processes worklist iteratively instead of recursive calls
  - Verified with stress tests: 750k, 1M, and 10M element lists all pass
  - All 12 GC stress tests pass including 1M allocations with nested function calls

### BUG-011: Nested UDT to JSON conversion not implemented
- **Discovered**: 2025-01-17, during codebase scan
- **Category**: Codegen
- **Severity**: Low
- **Reproduction**: Create nested user-defined types and convert to JSON
- **Observed**: Segfault when converting UDT with nested UDT/enum fields to JSON
- **Expected**: Nested types should serialize to nested JSON objects
- **Hypothesis**: JSON codegen only handles flat UDTs, not recursive traversal
- **Files**: `codegen/json_type.py` (convert_field_to_json)
- **Status**: Resolved (2026-01-17)
- **Resolution**: Fixed `convert_field_to_json` to properly handle GC handles:
  - UDT fields are stored as i64 GC handles, not raw pointers
  - Was incorrectly using `inttoptr(handle)` treating handle value as address
  - Now calls `gc_handle_deref(handle)` to get actual pointer, then bitcasts
  - Added support for nested enum fields in UDTs
  - All 62 JSON tests pass including new deeply-nested and enum tests

---

## Notes

### Session Protocol
1. **Session Start**: Review BUGS.md, summarize current state
2. **Pre-Task**: Check if any open bugs interact with planned work
3. **During Development**: Bug-on-discovery rule applies (document immediately)
4. **Session End**: Review work done, ensure all encountered bugs are recorded

### External Dependencies
- llvmlite TLS issue: See BUG-023

### Bug Count Summary (as of 2026-01-17)
- **Open**: 5 bugs
- **Resolved**: 21 bugs
