# Coex Concurrent Garbage Collector Implementation

## Project Overview

Implement a concurrent garbage collector that runs mark-sweep collection on a dedicated thread while mutator threads continue executing. This builds on the thread registry infrastructure to deliver non-blocking garbage collection.

### Prerequisites

- Thread registry implemented (ThreadEntry, TLS shadow stack, registration)
- Watermark protocol in gc_safepoint
- Handle-based allocation with birth-marking
- All 185 tests passing

### Deliverables

1. GC thread lifecycle management (spawn, main loop, shutdown)
2. Synchronization primitives (mutex, condition variables)
3. Async collection trigger (gc_async)
4. Completion waiting (gc_wait_for_completion)
5. Updated gc_collect (synchronous wrapper)
6. Automatic trigger in gc_safepoint
7. Removal of dead dual-heap code

---

## Part 1: New Global Variables

### 1.1 Add Member Variables to __init__

In `__init__()`, add:

```python
# Concurrent GC state
self.gc_thread = None              # GC thread handle (pthread_t as i8*)
self.gc_cond_start = None          # Condition: signal GC to start
self.gc_cond_done = None           # Condition: signal GC completion
self.gc_in_progress = None         # Flag: collection in progress
self.gc_shutdown_flag = None       # Flag: request GC thread termination
self.gc_trigger_threshold = None   # Allocation count to trigger GC

# GC thread function
self.gc_thread_main = None

# Concurrent GC API
self.gc_async = None
self.gc_wait_for_completion = None
self.gc_shutdown = None
```

### 1.2 Add Global Variables

In `_create_globals()`, add after thread registry globals:

```python
# ============================================================
# Concurrent GC Globals
# ============================================================

# GC thread handle (pthread_t stored as i8*)
self.gc_thread = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_thread")
self.gc_thread.initializer = ir.Constant(self.i8_ptr, None)
self.gc_thread.linkage = 'internal'

# Condition variable: signal GC thread to start collection
# (gc_cond_start already exists, reuse it)
# If not, add:
if self.gc_cond_start is None:
    self.gc_cond_start = ir.GlobalVariable(
        self.module, self.i8_ptr, name="gc_cond_start")
    self.gc_cond_start.initializer = ir.Constant(self.i8_ptr, None)
    self.gc_cond_start.linkage = 'internal'

# Condition variable: signal mutators that GC is complete
# (gc_cond_done already exists, reuse it)
if self.gc_cond_done is None:
    self.gc_cond_done = ir.GlobalVariable(
        self.module, self.i8_ptr, name="gc_cond_done")
    self.gc_cond_done.initializer = ir.Constant(self.i8_ptr, None)
    self.gc_cond_done.linkage = 'internal'

# Flag: GC cycle currently in progress
self.gc_in_progress = ir.GlobalVariable(
    self.module, self.i64, name="gc_in_progress")
self.gc_in_progress.initializer = ir.Constant(self.i64, 0)
self.gc_in_progress.linkage = 'internal'

# Flag: request GC thread to terminate
self.gc_shutdown_flag = ir.GlobalVariable(
    self.module, self.i64, name="gc_shutdown_flag")
self.gc_shutdown_flag.initializer = ir.Constant(self.i64, 0)
self.gc_shutdown_flag.linkage = 'internal'

# Allocation threshold for automatic GC trigger
self.gc_trigger_threshold = ir.GlobalVariable(
    self.module, self.i64, name="gc_trigger_threshold")
self.gc_trigger_threshold.initializer = ir.Constant(self.i64, 10000)
self.gc_trigger_threshold.linkage = 'internal'
```

---

## Part 2: Function Declarations

### 2.1 Add Function Declarations

In `_declare_functions()`, add:

```python
# ============================================================
# Concurrent GC Function Declarations
# ============================================================

# gc_thread_main(arg: i8*) -> i8*
# GC thread entry point (pthread signature)
gc_thread_main_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
self.gc_thread_main = ir.Function(
    self.module, gc_thread_main_ty, name="coex_gc_thread_main")

# gc_async() -> void
# Trigger asynchronous collection (returns immediately)
gc_async_ty = ir.FunctionType(self.void, [])
self.gc_async = ir.Function(
    self.module, gc_async_ty, name="coex_gc_async")

# gc_wait_for_completion() -> void
# Block until current GC cycle completes
gc_wait_ty = ir.FunctionType(self.void, [])
self.gc_wait_for_completion = ir.Function(
    self.module, gc_wait_ty, name="coex_gc_wait_for_completion")

# gc_shutdown() -> void
# Terminate GC thread (called at program exit)
gc_shutdown_ty = ir.FunctionType(self.void, [])
self.gc_shutdown = ir.Function(
    self.module, gc_shutdown_ty, name="coex_gc_shutdown")

# pthread_join(thread: i8*, retval: i8**) -> i32
# External: wait for thread termination
pthread_join_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr_ptr])
self.pthread_join = ir.Function(
    self.module, pthread_join_ty, name="pthread_join")

# pthread_cond_broadcast(cond: i8*) -> i32
# External: wake all threads waiting on condition
pthread_cond_broadcast_ty = ir.FunctionType(self.i32, [self.i8_ptr])
self.pthread_cond_broadcast = ir.Function(
    self.module, pthread_cond_broadcast_ty, name="pthread_cond_broadcast")

# usleep(usec: i32) -> i32
# External: sleep for microseconds (for watermark timeout)
usleep_ty = ir.FunctionType(self.i32, [self.i32])
self.usleep = ir.Function(self.module, usleep_ty, name="usleep")
```

---

## Part 3: GC Thread Implementation

### 3.1 Implement gc_thread_main

```python
def _implement_gc_thread_main(self):
    """GC thread entry point.
    
    Loops waiting for collection requests, runs collection cycles,
    and signals completion. Exits when gc_shutdown_flag is set.
    """
    func = self.gc_thread_main
    func.args[0].name = "arg"
    
    entry = func.append_basic_block("entry")
    loop_start = func.append_basic_block("loop_start")
    wait_loop = func.append_basic_block("wait_loop")
    check_shutdown = func.append_basic_block("check_shutdown")
    do_shutdown = func.append_basic_block("do_shutdown")
    check_work = func.append_basic_block("check_work")
    do_collection = func.append_basic_block("do_collection")
    signal_done = func.append_basic_block("signal_done")
    
    builder = ir.IRBuilder(entry)
    builder.branch(loop_start)
    
    # Main loop
    builder.position_at_end(loop_start)
    
    # Lock mutex
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.branch(wait_loop)
    
    # Wait loop: wait while gc_in_progress == 0 and gc_shutdown_flag == 0
    builder.position_at_end(wait_loop)
    
    in_progress = builder.load(self.gc_in_progress)
    shutdown = builder.load(self.gc_shutdown_flag)
    
    # Check if should wake
    has_work = builder.icmp_unsigned('!=', in_progress, ir.Constant(self.i64, 0))
    should_shutdown = builder.icmp_unsigned('!=', shutdown, ir.Constant(self.i64, 0))
    should_wake = builder.or_(has_work, should_shutdown)
    
    builder.cbranch(should_wake, check_shutdown, wait_loop_wait)
    
    # Wait on condition (need to add this block)
    wait_loop_wait = func.append_basic_block("wait_loop_wait")
    builder.position_at_end(wait_loop_wait)
    cond_start = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_wait, [cond_start, mutex])
    builder.branch(wait_loop)
    
    # Check if shutdown requested
    builder.position_at_end(check_shutdown)
    shutdown2 = builder.load(self.gc_shutdown_flag)
    is_shutdown = builder.icmp_unsigned('!=', shutdown2, ir.Constant(self.i64, 0))
    builder.cbranch(is_shutdown, do_shutdown, check_work)
    
    # Shutdown: unlock and return
    builder.position_at_end(do_shutdown)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.ret(ir.Constant(self.i8_ptr, None))
    
    # Check if work to do (defensive, should always be true here)
    builder.position_at_end(check_work)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(do_collection)
    
    # Run collection cycle
    builder.position_at_end(do_collection)
    builder.call(self.gc_run_collection_cycle, [])
    builder.branch(signal_done)
    
    # Signal completion
    builder.position_at_end(signal_done)
    
    # Lock mutex for state update
    mutex2 = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex2])
    
    # Set gc_in_progress = 0
    builder.store(ir.Constant(self.i64, 0), self.gc_in_progress)
    
    # Broadcast to all waiters
    cond_done = builder.load(self.gc_cond_done)
    builder.call(self.pthread_cond_broadcast, [cond_done])
    
    # Unlock and loop
    builder.call(self.pthread_mutex_unlock, [mutex2])
    builder.branch(loop_start)
```

**Note:** The above has a control flow issue (wait_loop_wait referenced before created). Here's the corrected version:

```python
def _implement_gc_thread_main(self):
    """GC thread entry point."""
    func = self.gc_thread_main
    func.args[0].name = "arg"
    
    entry = func.append_basic_block("entry")
    loop_start = func.append_basic_block("loop_start")
    wait_loop = func.append_basic_block("wait_loop")
    wait_loop_wait = func.append_basic_block("wait_loop_wait")
    check_shutdown = func.append_basic_block("check_shutdown")
    do_shutdown = func.append_basic_block("do_shutdown")
    do_collection = func.append_basic_block("do_collection")
    signal_done = func.append_basic_block("signal_done")
    
    builder = ir.IRBuilder(entry)
    builder.branch(loop_start)
    
    # Main loop - lock mutex
    builder.position_at_end(loop_start)
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.branch(wait_loop)
    
    # Wait loop
    builder.position_at_end(wait_loop)
    in_progress = builder.load(self.gc_in_progress)
    shutdown = builder.load(self.gc_shutdown_flag)
    has_work = builder.icmp_unsigned('!=', in_progress, ir.Constant(self.i64, 0))
    should_shutdown = builder.icmp_unsigned('!=', shutdown, ir.Constant(self.i64, 0))
    should_wake = builder.or_(has_work, should_shutdown)
    builder.cbranch(should_wake, check_shutdown, wait_loop_wait)
    
    # Wait on condition variable
    builder.position_at_end(wait_loop_wait)
    cond_start = builder.load(self.gc_cond_start)
    mutex_for_wait = builder.load(self.gc_mutex)
    builder.call(self.pthread_cond_wait, [cond_start, mutex_for_wait])
    builder.branch(wait_loop)
    
    # Check shutdown
    builder.position_at_end(check_shutdown)
    shutdown2 = builder.load(self.gc_shutdown_flag)
    is_shutdown = builder.icmp_unsigned('!=', shutdown2, ir.Constant(self.i64, 0))
    builder.cbranch(is_shutdown, do_shutdown, do_collection)
    
    # Shutdown path
    builder.position_at_end(do_shutdown)
    mutex_unlock = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_unlock, [mutex_unlock])
    builder.ret(ir.Constant(self.i8_ptr, None))
    
    # Collection path - unlock mutex first
    builder.position_at_end(do_collection)
    mutex_unlock2 = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_unlock, [mutex_unlock2])
    
    # Run the actual collection
    builder.call(self.gc_run_collection_cycle, [])
    builder.branch(signal_done)
    
    # Signal completion
    builder.position_at_end(signal_done)
    mutex3 = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex3])
    builder.store(ir.Constant(self.i64, 0), self.gc_in_progress)
    cond_done = builder.load(self.gc_cond_done)
    builder.call(self.pthread_cond_broadcast, [cond_done])
    builder.call(self.pthread_mutex_unlock, [mutex3])
    builder.branch(loop_start)
```

### 3.2 Implement gc_run_collection_cycle

This is the actual collection logic, extracted from gc_collect for reuse:

```python
def _implement_gc_run_collection_cycle(self):
    """Run a single garbage collection cycle.
    
    Called by gc_thread_main. Implements:
    1. Watermark installation and wait
    2. Mark phase
    3. Sweep phase
    4. Watermark reset
    """
    # Declare the function first
    gc_run_cycle_ty = ir.FunctionType(self.void, [])
    self.gc_run_collection_cycle = ir.Function(
        self.module, gc_run_cycle_ty, name="coex_gc_run_collection_cycle")
    
    func = self.gc_run_collection_cycle
    
    entry = func.append_basic_block("entry")
    watermark_wait = func.append_basic_block("watermark_wait")
    watermark_check = func.append_basic_block("watermark_check")
    watermark_timeout = func.append_basic_block("watermark_timeout")
    watermark_done = func.append_basic_block("watermark_done")
    do_mark = func.append_basic_block("do_mark")
    do_sweep = func.append_basic_block("do_sweep")
    reset_watermarks = func.append_basic_block("reset_watermarks")
    reset_loop = func.append_basic_block("reset_loop")
    reset_next = func.append_basic_block("reset_next")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Phase 1: Set WATERMARK phase
    builder.store_atomic(
        ir.Constant(self.i64, 1), self.gc_phase,
        ordering='release', align=8)
    
    # Increment cycle ID
    cycle = builder.load(self.gc_cycle_id)
    new_cycle = builder.add(cycle, ir.Constant(self.i64, 1))
    builder.store(new_cycle, self.gc_cycle_id)
    
    # Initialize wait counter (max iterations)
    max_wait = ir.Constant(self.i64, 100)  # 100 iterations * 10ms = 1 second
    builder.branch(watermark_wait)
    
    # Watermark wait loop
    builder.position_at_end(watermark_wait)
    wait_count = builder.phi(self.i64, name="wait_count")
    wait_count.add_incoming(ir.Constant(self.i64, 0), entry)
    
    # Check timeout
    timed_out = builder.icmp_unsigned('>=', wait_count, max_wait)
    builder.cbranch(timed_out, watermark_done, watermark_check)
    
    # Check if all threads acknowledged
    builder.position_at_end(watermark_check)
    
    # Iterate thread registry, check watermark_active
    all_acked = builder.alloca(self.i1, name="all_acked")
    builder.store(ir.Constant(self.i1, 1), all_acked)
    
    registry_head = builder.load(self.gc_thread_registry)
    
    # Simple inline check loop (for brevity; could call helper)
    check_loop = func.append_basic_block("check_loop")
    check_thread = func.append_basic_block("check_thread")
    check_next = func.append_basic_block("check_next")
    check_done = func.append_basic_block("check_done")
    
    builder.branch(check_loop)
    
    builder.position_at_end(check_loop)
    curr_thread = builder.phi(self.thread_entry_type.as_pointer(), name="curr")
    curr_thread.add_incoming(registry_head, watermark_check)
    
    curr_int = builder.ptrtoint(curr_thread, self.i64)
    is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_null, check_done, check_thread)
    
    builder.position_at_end(check_thread)
    wm_active_ptr = builder.gep(curr_thread, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    wm_active = builder.load_atomic(wm_active_ptr, ordering='acquire', align=8)
    not_acked = builder.icmp_unsigned('==', wm_active, ir.Constant(self.i64, 0))
    
    with builder.if_then(not_acked):
        builder.store(ir.Constant(self.i1, 0), all_acked)
    
    builder.branch(check_next)
    
    builder.position_at_end(check_next)
    next_ptr = builder.gep(curr_thread, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    next_i8 = builder.load(next_ptr)
    next_thread = builder.bitcast(next_i8, self.thread_entry_type.as_pointer())
    curr_thread.add_incoming(next_thread, check_next)
    builder.branch(check_loop)
    
    builder.position_at_end(check_done)
    all_acked_val = builder.load(all_acked)
    builder.cbranch(all_acked_val, watermark_done, watermark_timeout)
    
    # Sleep and retry
    builder.position_at_end(watermark_timeout)
    builder.call(self.usleep, [ir.Constant(self.i32, 10000)])  # 10ms
    new_wait_count = builder.add(wait_count, ir.Constant(self.i64, 1))
    wait_count.add_incoming(new_wait_count, watermark_timeout)
    builder.branch(watermark_wait)
    
    # Watermark phase complete
    builder.position_at_end(watermark_done)
    builder.branch(do_mark)
    
    # Phase 2: Marking
    builder.position_at_end(do_mark)
    builder.store_atomic(
        ir.Constant(self.i64, 2), self.gc_phase,
        ordering='release', align=8)
    
    # Flip mark value
    mark_val = builder.load(self.gc_current_mark_value)
    new_mark = builder.xor(mark_val, ir.Constant(self.i64, 1))
    builder.store(new_mark, self.gc_current_mark_value)
    
    # Scan roots
    builder.call(self.gc_scan_roots, [])
    builder.branch(do_sweep)
    
    # Phase 3: Sweeping
    builder.position_at_end(do_sweep)
    builder.store_atomic(
        ir.Constant(self.i64, 3), self.gc_phase,
        ordering='release', align=8)
    
    builder.call(self.gc_sweep, [])
    builder.branch(reset_watermarks)
    
    # Reset watermarks for all threads
    builder.position_at_end(reset_watermarks)
    reset_head = builder.load(self.gc_thread_registry)
    builder.branch(reset_loop)
    
    builder.position_at_end(reset_loop)
    reset_curr = builder.phi(self.thread_entry_type.as_pointer(), name="reset_curr")
    reset_curr.add_incoming(reset_head, reset_watermarks)
    
    reset_int = builder.ptrtoint(reset_curr, self.i64)
    reset_null = builder.icmp_unsigned('==', reset_int, ir.Constant(self.i64, 0))
    builder.cbranch(reset_null, done, reset_next)
    
    builder.position_at_end(reset_next)
    # Reset watermark_active = 0
    reset_wm_active_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), reset_wm_active_ptr)
    
    # Reset watermark_depth = 0
    reset_wm_depth_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), reset_wm_depth_ptr)
    
    # Next thread
    reset_next_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    reset_next_i8 = builder.load(reset_next_ptr)
    reset_next_thread = builder.bitcast(reset_next_i8, self.thread_entry_type.as_pointer())
    reset_curr.add_incoming(reset_next_thread, reset_next)
    builder.branch(reset_loop)
    
    # Done - set phase to IDLE
    builder.position_at_end(done)
    builder.store_atomic(
        ir.Constant(self.i64, 0), self.gc_phase,
        ordering='release', align=8)
    
    builder.ret_void()
```

---

## Part 4: API Function Implementations

### 4.1 Implement gc_async

```python
def _implement_gc_async(self):
    """Trigger asynchronous garbage collection.
    
    Returns immediately. Collection runs on GC thread.
    No-op if collection already in progress.
    """
    func = self.gc_async
    
    entry = func.append_basic_block("entry")
    already_running = func.append_basic_block("already_running")
    trigger = func.append_basic_block("trigger")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Lock mutex
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Check if already in progress
    in_progress = builder.load(self.gc_in_progress)
    is_running = builder.icmp_unsigned('!=', in_progress, ir.Constant(self.i64, 0))
    builder.cbranch(is_running, already_running, trigger)
    
    # Already running - just unlock and return
    builder.position_at_end(already_running)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(done)
    
    # Trigger collection
    builder.position_at_end(trigger)
    builder.store(ir.Constant(self.i64, 1), self.gc_in_progress)
    
    # Signal GC thread
    cond_start = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_signal, [cond_start])
    
    # Unlock
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(done)
    
    builder.position_at_end(done)
    builder.ret_void()
```

### 4.2 Implement gc_wait_for_completion

```python
def _implement_gc_wait_for_completion(self):
    """Block until current GC cycle completes.
    
    Returns immediately if no collection in progress.
    """
    func = self.gc_wait_for_completion
    
    entry = func.append_basic_block("entry")
    wait_loop = func.append_basic_block("wait_loop")
    do_wait = func.append_basic_block("do_wait")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Lock mutex
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.branch(wait_loop)
    
    # Wait loop
    builder.position_at_end(wait_loop)
    in_progress = builder.load(self.gc_in_progress)
    is_running = builder.icmp_unsigned('!=', in_progress, ir.Constant(self.i64, 0))
    builder.cbranch(is_running, do_wait, done)
    
    # Wait on condition
    builder.position_at_end(do_wait)
    cond_done = builder.load(self.gc_cond_done)
    mutex_for_wait = builder.load(self.gc_mutex)
    builder.call(self.pthread_cond_wait, [cond_done, mutex_for_wait])
    builder.branch(wait_loop)
    
    # Done - unlock and return
    builder.position_at_end(done)
    mutex_unlock = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_unlock, [mutex_unlock])
    builder.ret_void()
```

### 4.3 Implement gc_shutdown

```python
def _implement_gc_shutdown(self):
    """Terminate the GC thread.
    
    Waits for any in-progress collection, signals thread to exit,
    and joins the thread.
    """
    func = self.gc_shutdown
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    # Wait for any in-progress collection to complete
    builder.call(self.gc_wait_for_completion, [])
    
    # Lock mutex
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Set shutdown flag
    builder.store(ir.Constant(self.i64, 1), self.gc_shutdown_flag)
    
    # Signal GC thread to wake up
    cond_start = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_signal, [cond_start])
    
    # Unlock
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    # Join GC thread
    gc_thread_ptr = builder.load(self.gc_thread)
    builder.call(self.pthread_join, [gc_thread_ptr, ir.Constant(self.i8_ptr_ptr, None)])
    
    builder.ret_void()
```

### 4.4 Update gc_collect

Replace the existing implementation to use gc_async + gc_wait_for_completion:

```python
def _implement_gc_collect(self):
    """Synchronous garbage collection.
    
    Triggers collection and waits for it to complete.
    """
    func = self.gc_collect
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    # Trigger async collection
    builder.call(self.gc_async, [])
    
    # Wait for completion
    builder.call(self.gc_wait_for_completion, [])
    
    builder.ret_void()
```

---

## Part 5: Update gc_init

### 5.1 Add GC Thread Spawning

Add to `_implement_gc_init()`, after thread registry initialization:

```python
# ============================================================
# Initialize Concurrent GC
# ============================================================

# gc_mutex is already initialized above (reuse if exists)
# If not, initialize it here:
# mutex_size = ir.Constant(self.i64, 64)
# mutex_ptr = builder.call(self.codegen.malloc, [mutex_size])
# builder.store(mutex_ptr, self.gc_mutex)
# builder.call(self.pthread_mutex_init, [mutex_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize gc_cond_start (if not already done)
cond_size = ir.Constant(self.i64, 64)
cond_start_ptr = builder.call(self.codegen.malloc, [cond_size])
builder.store(cond_start_ptr, self.gc_cond_start)
builder.call(self.pthread_cond_init, [cond_start_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize gc_cond_done (if not already done)
cond_done_ptr = builder.call(self.codegen.malloc, [cond_size])
builder.store(cond_done_ptr, self.gc_cond_done)
builder.call(self.pthread_cond_init, [cond_done_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize state flags
builder.store(ir.Constant(self.i64, 0), self.gc_in_progress)
builder.store(ir.Constant(self.i64, 0), self.gc_shutdown_flag)
builder.store(ir.Constant(self.i64, 0), self.gc_phase)
builder.store(ir.Constant(self.i64, 0), self.gc_cycle_id)

# Allocate space for thread handle
thread_handle_size = ir.Constant(self.i64, 8)  # sizeof(pthread_t)
thread_handle_ptr = builder.call(self.codegen.malloc, [thread_handle_size])

# Create GC thread
gc_thread_func_ptr = builder.bitcast(self.gc_thread_main, self.i8_ptr)
builder.call(self.pthread_create, [
    thread_handle_ptr,                    # pthread_t*
    ir.Constant(self.i8_ptr, None),       # attr (NULL = default)
    gc_thread_func_ptr,                   # start routine
    ir.Constant(self.i8_ptr, None)        # arg (NULL)
])

# Load and store the thread handle
thread_handle = builder.load(builder.bitcast(thread_handle_ptr, self.i8_ptr.as_pointer()))
builder.store(thread_handle, self.gc_thread)
```

---

## Part 6: Update gc_safepoint for Auto-Trigger

### 6.1 Add Allocation Threshold Check

Add to `_implement_gc_safepoint()`, after watermark acknowledgment logic:

```python
# ============================================================
# Check allocation threshold for automatic GC trigger
# ============================================================

# Load allocation count and threshold
alloc_count = builder.load(self.gc_alloc_count)
threshold = builder.load(self.gc_trigger_threshold)

# Check if threshold exceeded
should_trigger = builder.icmp_unsigned('>=', alloc_count, threshold)

with builder.if_then(should_trigger):
    # Attempt atomic reset of counter (avoid double-trigger)
    # Simple version: just reset and trigger
    builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)
    builder.call(self.gc_async, [])
```

**Note:** For true atomicity, use cmpxchg:

```python
with builder.if_then(should_trigger):
    # Atomic compare-and-swap to reset counter
    alloc_count_ptr = self.gc_alloc_count
    # cmpxchg: if *ptr == alloc_count, set to 0, return (old_val, success)
    cmpxchg_result = builder.cmpxchg(
        alloc_count_ptr, alloc_count, ir.Constant(self.i64, 0),
        ordering='seq_cst', failordering='seq_cst')
    success = builder.extract_value(cmpxchg_result, 1)
    
    with builder.if_then(success):
        builder.call(self.gc_async, [])
```

---

## Part 7: Wire Up Implementations

### 7.1 Update generate_gc_runtime

```python
def generate_gc_runtime(self):
    """Generate all GC runtime structures and functions"""
    self._create_types()
    self._create_globals()
    self._declare_functions()
    self._register_builtin_types()
    
    # Declare gc_run_collection_cycle before implementing gc_thread_main
    self._declare_gc_run_collection_cycle()
    
    self._implement_gc_init()
    self._implement_gc_register_thread()
    self._implement_gc_unregister_thread()
    self._implement_gc_get_thread_entry()
    self._implement_gc_push_frame()
    self._implement_gc_pop_frame()
    self._implement_gc_set_root()
    self._implement_gc_alloc()
    self._implement_gc_mark_hamt()
    self._implement_gc_mark_object()
    self._implement_gc_scan_roots()
    self._implement_gc_sweep()
    
    # Concurrent GC implementations
    self._implement_gc_run_collection_cycle()  # NEW
    self._implement_gc_thread_main()           # NEW
    self._implement_gc_async()                 # NEW
    self._implement_gc_wait_for_completion()   # NEW
    self._implement_gc_shutdown()              # NEW
    self._implement_gc_collect()               # UPDATED
    
    self._implement_gc_safepoint()             # UPDATED
    
    # ... rest of existing implementations
```

### 7.2 Add Declaration Helper

```python
def _declare_gc_run_collection_cycle(self):
    """Declare gc_run_collection_cycle for forward reference."""
    gc_run_cycle_ty = ir.FunctionType(self.void, [])
    self.gc_run_collection_cycle = ir.Function(
        self.module, gc_run_cycle_ty, name="coex_gc_run_collection_cycle")
```

---

## Part 8: Remove Dead Dual-Heap Code

### 8.1 Remove Unused Globals

Remove or comment out from `_create_globals()`:
- `heap_region_type`
- `root_snapshot_type`  
- `gc_state_type`
- `gc_state`
- `gc_snapshot`
- `gc_thread_handle` (replaced by `gc_thread`)

### 8.2 Remove Unused Functions

Remove or comment out:
- `_implement_gc_capture_snapshot`
- `_implement_gc_mark_from_snapshot`
- `_implement_gc_swap_heaps`
- `_implement_gc_scan_cross_heap`
- `_implement_gc_sweep_heap`
- `_implement_gc_grow_heaps`

Also remove their declarations from `_declare_functions()`.

### 8.3 Remove From generate_gc_runtime

Remove calls to the above implementations from `generate_gc_runtime()`.

---

## Part 9: Integration with codegen.py

### 9.1 Call gc_shutdown at Program Exit

In codegen.py, modify the main function epilogue to call gc_shutdown before returning:

```python
# In _generate_function for main():
# Before the final ret instruction:

if func.name == "main":
    # Shutdown GC thread before exit
    builder.call(self.gc.gc_shutdown, [])
```

Alternatively, register gc_shutdown with atexit.

---

## Testing Checklist

### Unit Tests

- [ ] GC thread starts during gc_init
- [ ] GC thread responds to gc_async signal
- [ ] gc_wait_for_completion blocks and returns correctly
- [ ] gc_shutdown terminates GC thread cleanly
- [ ] gc_collect triggers and waits for collection
- [ ] Watermark timeout works (thread doesn't hang)

### Integration Tests

- [ ] All 185 existing tests pass
- [ ] Explicit gc() calls work correctly
- [ ] Automatic GC triggers at threshold
- [ ] Memory is reclaimed (check statistics)
- [ ] No deadlocks during normal operation

### Stress Tests

- [ ] Rapid allocations during collection
- [ ] Multiple gc_collect calls in sequence
- [ ] Program exit during collection

---

## Success Criteria

1. GC thread starts at initialization
2. gc_async returns immediately, triggers collection on GC thread
3. gc_wait_for_completion blocks until collection done
4. gc_collect is synchronous (triggers + waits)
5. gc_shutdown cleanly terminates GC thread
6. Automatic trigger at allocation threshold
7. All existing tests pass
8. No deadlocks
9. Dual-heap dead code removed

---

## Notes

### pthread_cond_wait Semantics

`pthread_cond_wait(cond, mutex)` atomically:
1. Releases the mutex
2. Blocks on the condition variable
3. Re-acquires the mutex when signaled

The mutex must be held when calling pthread_cond_wait.

### Memory Ordering in llvmlite

```python
# Atomic load with acquire
builder.load_atomic(ptr, ordering='acquire', align=8)

# Atomic store with release  
builder.store_atomic(val, ptr, ordering='release', align=8)

# Compare-and-swap
builder.cmpxchg(ptr, expected, new, ordering='seq_cst', failordering='seq_cst')
```

### Thread Handle Storage

pthread_create writes the thread ID to the location pointed to by its first argument. We allocate space, pass its address, then load and store the result.

### Forward Declaration

gc_run_collection_cycle must be declared before gc_thread_main is implemented, since gc_thread_main calls it. Use _declare_gc_run_collection_cycle() for this.
