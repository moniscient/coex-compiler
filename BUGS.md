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

### BUG-033: Scheduler initialization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low (review for necessity)
- **Reproduction**: Scheduler lazy initialization via `coex_scheduler_ensure_init()`
- **Observed**: Uses `scheduler_init_mutex` (pthread_mutex) at `coex_scheduler.c:26`
- **Expected**: TBD - review if lock-free initialization is feasible
- **Hypothesis**: Double-checked locking pattern; mutex only held briefly during init
- **Files**: `runtime/coex_scheduler.c:26, 479-509`
- **Status**: Open (under review)

### BUG-035: Global work queue uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium (review for necessity)
- **Reproduction**: Tasks submitted from main thread use global queue
- **Observed**: Uses `global_queue_mutex` at `coex_scheduler.c:39`
- **Expected**: TBD - review if lock-free queue is feasible
- **Hypothesis**: Protects global deque during push/steal; could use lock-free MPSC
- **Files**: `runtime/coex_scheduler.c:39, 209-211, 570-572, 607-609, 638-640, 723-725, 795-797`
- **Status**: Open (under review)

### BUG-036: Deque resize uses lock
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low (review for necessity)
- **Reproduction**: Chase-Lev deque grows when full
- **Observed**: Uses `resize_lock` in Deque struct at `coex_scheduler.h:80`
- **Expected**: TBD - review if resize can be lock-free
- **Hypothesis**: Required for safe buffer reallocation while stealers active
- **Files**: `runtime/coex_scheduler.h:80`, `runtime/coex_scheduler.c:70-77, 108-111`
- **Status**: Open (under review)

### BUG-042: Channel synchronization uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Medium (review for necessity)
- **Reproduction**: Channels used from func/thread context
- **Observed**: Uses `mutex` + `cond` in ChannelSync at `coex_channel.h:63-64`
- **Expected**: TBD - review if lock-free channel is feasible
- **Hypothesis**: Required for blocking receive; could use lock-free for send
- **Files**: `runtime/coex_channel.h:63-64`, `runtime/coex_channel.c:172-174, 184-216, 222-265, 272-274`
- **Status**: Open (under review)

### BUG-043: GC main mutex for handle allocation
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Medium (review for necessity)
- **Reproduction**: Handle allocation slow path, async GC coordination
- **Observed**: Uses `gc_mutex` at `coex_gc.py:568`
- **Expected**: TBD - review scope of mutex protection
- **Hypothesis**: Protects handle table growth, free list refill, GC coordination
- **Files**: `coex_gc.py:568, 1426-1428, 1956-1985, 2258-2262, 3925-3967, 4085-4212, 7792-7855`
- **Status**: Open (under review)

### BUG-044: GC registry mutex for thread tracking
- **Discovered**: 2026-01-18, during lock audit
- **Category**: GC
- **Severity**: Low (review for necessity)
- **Reproduction**: Thread registration/unregistration during GC
- **Observed**: Uses `gc_registry_mutex` at `coex_gc.py:696-699`
- **Expected**: TBD - protects thread registry during iteration
- **Hypothesis**: Required for safe iteration while threads register/unregister
- **Files**: `coex_gc.py:696-699, 1514-1519, 1747-1765, 1817-1888, 3032-3198, 3326-3372, 5578-5930, 6376-6480`
- **Status**: Open (under review)

---

## Resolved Bugs

### BUG-045: Metal GPU offload crashes with double types
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**:
  ```coex
  formula compute(x: float) -> float
      return x * 2.0
  ~

  func main() -> int
      data: Array<float> = [1.0, 2.0, 3.0].toArray()
      result: Array<float> = [compute(x) for x in data]  # CRASH
      return 0
  ~
  ```
- **Observed**: Segfault in Metal's `newLibraryWithSource` with error "double is not supported in Metal"
- **Expected**: GPU offload should work with Coex's 64-bit float type
- **Root Cause**: Metal Shading Language does NOT support 64-bit types (double, long). The Metal backend was incorrectly mapping Coex's 64-bit float to Metal's `double`, causing kernel compilation to fail.
- **Files**: `codegen/formula/metal.py`, `runtime/coex_metal.m`
- **Status**: Resolved
- **Resolution**:
  1. Updated MetalBackend.TYPE_MAP to use 32-bit types (`float` instead of `double`)
  2. Modified `coex_metal_dispatch()` to convert 64-bit Coex data to 32-bit for Metal input
  3. Added conversion back from 32-bit to 64-bit for output
  4. Metal GPU offload now works correctly, with some precision loss due to 32-bit computation

### BUG-034: Worker parking uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `parking_mutex` + `parking_cond` at `coex_scheduler.c:33-34`
- **Files**: `runtime/coex_scheduler.c:33-34, 173-204`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-037: FirstContext completion uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in FirstContext at `coex_scheduler.h:92-93`
- **Files**: `runtime/coex_scheduler.h:92-93`, `runtime/coex_scheduler.c:416-441, 682-700, 728-751`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-038: MostContext completion uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in MostContext at `coex_scheduler.h:106-107`
- **Files**: `runtime/coex_scheduler.h:106-107`, `runtime/coex_scheduler.c:462-467, 753-775, 800-820`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-039: SchedulerTask main thread wait uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `main_mutex` + `main_cond` in SchedulerTask at `coex_scheduler.h:63-64`
- **Files**: `runtime/coex_scheduler.h:63-64`, `runtime/coex_scheduler.c:333-337, 559-586, 627-657`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-040: TaskClosure completion signaling uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in TaskClosure at `coex_task.h:37-38`
- **Files**: `runtime/coex_task.h:37-38`, `runtime/coex_task.c:96-97, 107-108, 167-188`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

### BUG-041: SharedWaiter wait_any uses mutex
- **Discovered**: 2026-01-18, during lock audit
- **Category**: Runtime
- **Severity**: Low
- **Observed**: Uses `mutex` + `cond` in SharedWaiter at `coex_task.c:37-38`
- **Files**: `runtime/coex_task.c:36-40, 210-253`
- **Status**: Resolved (by design)
- **Resolution**: Required by POSIX - `pthread_cond_wait` mandates a mutex companion

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
- **Files**: `codegen/posix.py`
- **Status**: Resolved (2026-01-19)
- **Resolution**: Fixed incorrect clock constants in `_create_posix_time_ns`:
  - Linux: Changed from 4 to 1 (CLOCK_MONOTONIC)
  - macOS: Changed from 1 to 8 (CLOCK_UPTIME_RAW for true nanosecond precision)
  - Root cause: Using wrong constants caused clock_gettime to fail silently, returning garbage values
  - Note: macOS CLOCK_REALTIME only provides microsecond precision, but CLOCK_UPTIME_RAW provides true nanosecond precision
- **Note**: Previously marked resolved on 2025-01-17 but test only checked `t > 0` which passed with garbage. Re-opened and truly fixed 2026-01-19.

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

### BUG-026: Test files use `=` instead of `:=` for task assignment
- **Discovered**: 2026-01-17, during GPU offload implementation testing
- **Category**: Semantic
- **Severity**: Low
- **Reproduction**: Run `python3 -m pytest tests/test_scheduler.py tests/test_task_state_machine.py`
- **Observed**: 6 tests fail with error: `Cannot assign task result with '=' operator`
- **Expected**: Tests should use correct `:=` syntax for task calls
- **Files**: `tests/test_scheduler.py`, `tests/test_task_state_machine.py`
- **Status**: Resolved (2026-01-17)
- **Resolution**: Updated all task call assignments from `=` to `:=`:
  - Fixed ~25 occurrences across both test files
  - Tests were written before BUG-012 fix enforced `:=` for task assignment
  - All 34 tests now pass

### BUG-028: Array iteration in comprehensions not implemented
- **Discovered**: 2026-01-18, during GPU offload implementation testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `[f(x) for x in arr]` where `arr` is an Array<T>
- **Observed**: Loop variable `x` is not bound; falls through to "unknown iterable type" path
- **Expected**: Array iteration should work like List iteration in comprehensions
- **Files**: `codegen/comprehensions.py:210-212` - Array case falls through without binding pattern
- **Status**: Fixed (2026-01-18)
- **Resolution**: Added Array iteration support in `codegen/comprehensions.py` after List handling. Uses `array_len` and `array_get` to iterate, same pattern as List iteration.
- **Tests**: `tests/test_array_comprehension.py` - 6 passing tests covering basic iteration, filters, formulas, set/map comprehensions, and multiple clauses.

### BUG-029: MapComprehension not handled in formula offload check
- **Discovered**: 2026-01-18, during BUG-028 fix testing
- **Category**: Codegen
- **Severity**: Low
- **Reproduction**: `{x: x * 10 for x in arr}` where `arr` is an Array<T>
- **Observed**: `AttributeError: 'MapComprehension' object has no attribute 'body'` in formula offload check
- **Expected**: MapComprehension should use `key` and `value` fields instead of `body`
- **Files**: `codegen/formula/__init__.py:241` - `_check_comprehension` accesses `node.body` but MapComprehension has `node.key`/`node.value`
- **Status**: Fixed (2026-01-18)
- **Resolution**: Refactored comprehension AST nodes to use consistent field naming:
  - Renamed `body` to `value` in ListComprehension and SetComprehension (ast_nodes.py)
  - Updated ast_builder.py, codegen/comprehensions.py, codegen/formula/__init__.py, analysis/cfg.py
  - Added explicit MapComprehension handling in `_check_comprehension` to check both `key` and `value`
- **Tests**: `tests/test_array_comprehension.py::test_array_map_comprehension` now passes

### BUG-030: Array filter comprehension not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `[x for x in arr if x % 2 == 0]` where `arr` is an Array<int> with values [0,1,2,3,4,5]
- **Observed**: Returns 6 elements instead of 3; GPU offload was ignoring the filter condition
- **Expected**: Should return only even elements [0, 2, 4]
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling filtered comprehensions. The filter condition was checked for eligibility but then ignored in the kernel. Fixed by restricting GPU offload to only handle ListComprehensions without filter conditions. Comprehensions with filters now use the correct CPU path.
- **Tests**: `tests/test_array_comprehension.py::test_array_iteration_with_filter` passes

### BUG-031: Set comprehension over Array not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `{x for x in arr}` where `arr` is an Array<int> with values [0,1,2,0,1]
- **Observed**: Returns 5 elements instead of 3 (GPU was producing Array instead of Set)
- **Expected**: Should return Set with 3 unique elements {0, 1, 2}
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling SetComprehension. The GPU kernel produces an Array output, but Sets have different semantics (deduplication). Fixed by restricting GPU offload to only handle ListComprehension. Set comprehensions now use the correct CPU path which properly constructs Sets.
- **Tests**: `tests/test_array_comprehension.py::test_array_set_comprehension` passes

### BUG-032: Map comprehension over Array not working
- **Discovered**: 2026-01-18, during GPU offload testing
- **Category**: Codegen
- **Severity**: Medium
- **Reproduction**: `{x: x * 10 for x in arr}` where `arr` is an Array<int> with values [1,2,3]
- **Observed**: Returns wrong values (GPU was producing Array instead of Map)
- **Expected**: Should return map {1: 10, 2: 20, 3: 30}
- **Files**: `codegen/formula/__init__.py`
- **Status**: Fixed (2026-01-18)
- **Resolution**: GPU offload was incorrectly handling MapComprehension. The GPU kernel produces an Array output, but Maps have different semantics (key-value pairs). Fixed by restricting GPU offload to only handle ListComprehension. Map comprehensions now use the correct CPU path which properly constructs Maps.
- **Tests**: `tests/test_array_comprehension.py::test_array_map_comprehension` passes

### BUG-027: Flaky test - first with computation in body returns wrong result
- **Discovered**: 2026-01-18, during GPU offload implementation testing
- **Category**: Runtime
- **Severity**: High
- **Reproduction**: Run `python3 -m pytest tests/test_complex_first_most.py::TestComplexBodyTokenRing::test_first_with_computation_in_body`
- **Observed**: Test returns 625 (25^2) or 1225 (35^2) non-deterministically instead of 225 (15^2)
- **Expected**: Should return 225, which is (10+5)^2 - the first element's computation
- **Files**: `runtime/coex_scheduler.c`, `runtime/coex_scheduler.h`
- **Status**: Fixed (2026-01-18)
- **Resolution**: Implemented priority-based winner selection for `first` construct. When multiple tasks complete around the same time, the task with the lowest element index now wins. Key changes:
  1. Changed `has_winner` (boolean) to `winner_index` (int64, initialized to INT64_MAX) in FirstContext
  2. Modified `handle_first_completion` to use CAS loop to only allow lower-indexed tasks to become winners
  3. Added re-check of winner_index under mutex before updating winner_value to prevent race where a later task overwrites the correct value
  4. Changed `coex_scheduler_first_wait` to wait until all tasks complete, ensuring the lowest-indexed task's value is stored before returning
- **Root Cause**: When parent tasks (`__first_body_1`) completed around the same time, whichever called `handle_first_completion` first would win, regardless of element index. Additionally, the winner_value update could be overwritten by a higher-indexed task that got the mutex later.

### BUG-046: Thread-based first returns temporally first result instead of index-0 result
- **Discovered**: 2026-01-19, during GitHub CI failure on Linux
- **Category**: Codegen
- **Severity**: High
- **Reproduction**: `result = first x in [1,2,3] compute(x) ~` where `compute` is a `thread`
- **Observed**: Returns 6 (3*2) on Linux when thread 2 completes first temporally
- **Expected**: Should return 2 (1*2) - the first element's result, for deterministic behavior
- **Files**: `codegen/loops.py`
- **Status**: Fixed (2026-01-19)
- **Resolution**: The scheduler-based `first` (for `task`) was fixed in BUG-027 to use priority-based winner selection (lowest index wins). However, the thread-based `first` (for `thread`) still used `task_wait_any` to determine the winner based on temporal completion order. Fixed by:
  1. Changed result extraction to always use index 0 instead of the `wait_any` winner
  2. Changed cancel logic to never cancel index 0 (always let it complete)
  3. All threads are joined, so index 0's result is always available
- **Root Cause**: Thread-based and scheduler-based `first` implementations had divergent semantics. Thread path used temporal winner selection while scheduler path used priority-based selection.

---

## Notes

### Session Protocol
1. **Session Start**: Review BUGS.md, summarize current state
2. **Pre-Task**: Check if any open bugs interact with planned work
3. **During Development**: Bug-on-discovery rule applies (document immediately)
4. **Session End**: Review work done, ensure all encountered bugs are recorded

### External Dependencies
- llvmlite TLS issue: See BUG-023

### Bug Count Summary (as of 2026-01-18)
- **Open**: 10 bugs (BUG-004, BUG-015, BUG-016, BUG-023, BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044)
- **Resolved**: 36 bugs (including BUG-045: Metal double type fix)

### Lock Audit Bugs (BUG-033 to BUG-044)
- **Resolved (by design)**: BUG-034, BUG-037, BUG-038, BUG-039, BUG-040, BUG-041 - condition variable mutexes mandated by POSIX
- **Open (under review)**: BUG-033, BUG-035, BUG-036, BUG-042, BUG-043, BUG-044 - data structure protection locks

### BUG-033: Float list values corrupted when returned from function
- **Discovered**: 2025-01-18, during GEMM benchmark development
- **Category**: Codegen
- **Severity**: Critical
- **Reproduction**: 
  ```coex
  func gemm(a: [float], b: [float]) -> [float]
      result: [float] = []
      for i in 0..2
          val: float = compute(a, b, i)  # val prints correctly here
          result = result.append(val)
      ~
      return result
  ~
  
  func main() -> int
      c = gemm(a, b)
      v: float = c.get(0)  # v is corrupted (e.g., 4620706744243609600.0)
      return 0
  ~
  ```
- **Observed**: Float values computed correctly inside function but read as corrupted values (appear to be bit-reinterpreted) after function returns
- **Expected**: Float list values should maintain integrity across function boundaries
- **Hypothesis**: Type confusion between float32/float64 or handle/pointer in list return path
- **Files**: `codegen/core.py`, `codegen/collections.py`
- **Status**: Open

### BUG-047: Parenthesized expression parsing fails
- **Discovered**: 2026-01-19, during Array<T> implementation testing
- **Category**: Parser/AST Builder
- **Severity**: Medium
- **Reproduction**: Test `test_parentheses_override_precedence` in test_basic.py
- **Observed**: `TypeError: 'ExpressionContext' object is not subscriptable` in ast_builder.py:1121
- **Expected**: Parenthesized expressions like `(1 + 2) * 3` should parse correctly
- **Hypothesis**: `ctx.expression()` returns ExpressionContext directly when single expression, not a list. Need to check for this case.
- **Files**: ast_builder.py:1121
- **Fix**: Changed `exprs = ctx.expression(); return self.visit_expression(exprs[0])` to `expr = ctx.expression(); return self.visit_expression(expr)` - grammar rule `LPAREN expression RPAREN` has single expression, not list
- **Status**: Fixed (2026-01-19)

### BUG-048: GPU offload marshaling used old Array layout
- **Discovered**: 2026-01-19, during GPU GEMM benchmark development
- **Category**: Codegen/GPU
- **Severity**: High
- **Reproduction**: Any formula comprehension over Array type with GPU offload enabled
- **Observed**: Segmentation fault during GPU dispatch; marshaling code tried to call `gc_handle_deref` on raw pointer
- **Expected**: GPU offload should work correctly with Arrays
- **Hypothesis**: Marshaling code in `codegen/formula/marshaling.py` was using old 5-field Array layout instead of new 13-field N-D layout
- **Files**: codegen/formula/marshaling.py
- **Fix**: Updated field indices for new layout (handle=0, ndim=1, shape=2[4], strides=3[4], offset=4, elem_size=5, type_id=6). Fixed handle field to use `inttoptr` (raw pointer stored as i64) instead of `gc_handle_deref`.
- **Status**: Fixed (2026-01-19)

### BUG-049: GPU transpiler only handled FORMULA, not FORMULA32
- **Discovered**: 2026-01-19, during GPU benchmark development
- **Category**: Codegen/GPU
- **Severity**: Medium
- **Reproduction**: Use `formula32` in a list comprehension that should GPU-offload
- **Observed**: "Cannot transpile call to 'func_name' for GPU" error, falls back to CPU
- **Expected**: Both `formula` and `formula32` should be inlinable for GPU
- **Hypothesis**: Transpiler check at line 207 only checked `FunctionKind.FORMULA`
- **Files**: codegen/formula/transpiler.py
- **Fix**: Changed check to `decl.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32)`
- **Status**: Fixed (2026-01-19)

