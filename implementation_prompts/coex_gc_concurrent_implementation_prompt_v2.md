# Coex Concurrent GC Implementation (v2)

## Overview

Implement concurrent garbage collection using contiguous shadow stack arrays with snapshot-at-the-beginning. No sentinels, no halt flags, no coordination—just atomic index reads.

---

## Part 1: Types and Constants

### 1.1 Member Variables in __init__

```python
# Stack capacity constants
self.INITIAL_HANDLE_CAPACITY = 8192   # 64KB of handles
self.INITIAL_FRAME_CAPACITY = 1024    # 8KB of frame indices

# Thread registry
self.thread_entry_type = None
self.gc_thread_registry = None
self.gc_thread_count = None
self.gc_registry_mutex = None

# GC state
self.gc_phase = None
self.gc_cycle_id = None
self.gc_sweep_threshold = None

# GC thread control
self.gc_thread = None
self.gc_mutex = None
self.gc_cond_start = None
self.gc_cond_done = None
self.gc_in_progress = None
self.gc_shutdown_flag = None
self.gc_trigger_threshold = None
self.gc_alloc_count = None

# Thread-local storage
self.tls_handle_stack = None
self.tls_handle_top = None
self.tls_frame_stack = None
self.tls_frame_top = None
self.tls_thread_entry = None

# Functions
self.gc_register_thread = None
self.gc_unregister_thread = None
self.gc_push_frame = None
self.gc_pop_frame = None
self.gc_root = None
self.gc_thread_main = None
self.gc_run_collection_cycle = None
self.gc_async = None
self.gc_wait_for_completion = None
self.gc_collect = None
self.gc_shutdown = None
```

### 1.2 ThreadEntry Type

In `_create_types()`:

```python
# ThreadEntry: per-thread GC state with contiguous stacks
self.thread_entry_type = ir.LiteralStructType([
    self.i64,           # 0:  thread_id
    self.i64_ptr,       # 8:  handle_stack (pointer to handle array)
    self.i64,           # 16: handle_capacity
    self.i64,           # 24: handle_top (atomic - next free slot)
    self.i64_ptr,       # 32: frame_stack (pointer to frame index array)
    self.i64,           # 40: frame_capacity
    self.i64,           # 48: frame_top (number of frames)
    self.i8_ptr,        # 56: next (next thread in registry)
])
# Total: 64 bytes
```

---

## Part 2: Global Variables

In `_create_globals()`:

```python
# ============================================================
# Thread Registry
# ============================================================

self.gc_thread_registry = ir.GlobalVariable(
    self.module, self.thread_entry_type.as_pointer(), name="gc_thread_registry")
self.gc_thread_registry.initializer = ir.Constant(
    self.thread_entry_type.as_pointer(), None)
self.gc_thread_registry.linkage = 'internal'

self.gc_thread_count = ir.GlobalVariable(
    self.module, self.i64, name="gc_thread_count")
self.gc_thread_count.initializer = ir.Constant(self.i64, 0)
self.gc_thread_count.linkage = 'internal'

self.gc_registry_mutex = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_registry_mutex")
self.gc_registry_mutex.initializer = ir.Constant(self.i8_ptr, None)
self.gc_registry_mutex.linkage = 'internal'

# ============================================================
# GC State
# ============================================================

self.gc_phase = ir.GlobalVariable(
    self.module, self.i64, name="gc_phase")
self.gc_phase.initializer = ir.Constant(self.i64, 0)
self.gc_phase.linkage = 'internal'

self.gc_cycle_id = ir.GlobalVariable(
    self.module, self.i64, name="gc_cycle_id")
self.gc_cycle_id.initializer = ir.Constant(self.i64, 1)
self.gc_cycle_id.linkage = 'internal'

self.gc_sweep_threshold = ir.GlobalVariable(
    self.module, self.i64, name="gc_sweep_threshold")
self.gc_sweep_threshold.initializer = ir.Constant(self.i64, 0)
self.gc_sweep_threshold.linkage = 'internal'

self.gc_alloc_count = ir.GlobalVariable(
    self.module, self.i64, name="gc_alloc_count")
self.gc_alloc_count.initializer = ir.Constant(self.i64, 0)
self.gc_alloc_count.linkage = 'internal'

self.gc_trigger_threshold = ir.GlobalVariable(
    self.module, self.i64, name="gc_trigger_threshold")
self.gc_trigger_threshold.initializer = ir.Constant(self.i64, 10000)
self.gc_trigger_threshold.linkage = 'internal'

# ============================================================
# GC Thread Control
# ============================================================

self.gc_thread = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_thread")
self.gc_thread.initializer = ir.Constant(self.i8_ptr, None)
self.gc_thread.linkage = 'internal'

self.gc_mutex = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_mutex")
self.gc_mutex.initializer = ir.Constant(self.i8_ptr, None)
self.gc_mutex.linkage = 'internal'

self.gc_cond_start = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_cond_start")
self.gc_cond_start.initializer = ir.Constant(self.i8_ptr, None)
self.gc_cond_start.linkage = 'internal'

self.gc_cond_done = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_cond_done")
self.gc_cond_done.initializer = ir.Constant(self.i8_ptr, None)
self.gc_cond_done.linkage = 'internal'

self.gc_in_progress = ir.GlobalVariable(
    self.module, self.i64, name="gc_in_progress")
self.gc_in_progress.initializer = ir.Constant(self.i64, 0)
self.gc_in_progress.linkage = 'internal'

self.gc_shutdown_flag = ir.GlobalVariable(
    self.module, self.i64, name="gc_shutdown_flag")
self.gc_shutdown_flag.initializer = ir.Constant(self.i64, 0)
self.gc_shutdown_flag.linkage = 'internal'

# ============================================================
# Thread-Local Storage
# ============================================================

self.tls_handle_stack = ir.GlobalVariable(
    self.module, self.i64_ptr, name="tls_handle_stack")
self.tls_handle_stack.initializer = ir.Constant(self.i64_ptr, None)
self.tls_handle_stack.linkage = 'internal'
self.tls_handle_stack.thread_local = 'localdynamic'

self.tls_handle_top = ir.GlobalVariable(
    self.module, self.i64, name="tls_handle_top")
self.tls_handle_top.initializer = ir.Constant(self.i64, 0)
self.tls_handle_top.linkage = 'internal'
self.tls_handle_top.thread_local = 'localdynamic'

self.tls_frame_stack = ir.GlobalVariable(
    self.module, self.i64_ptr, name="tls_frame_stack")
self.tls_frame_stack.initializer = ir.Constant(self.i64_ptr, None)
self.tls_frame_stack.linkage = 'internal'
self.tls_frame_stack.thread_local = 'localdynamic'

self.tls_frame_top = ir.GlobalVariable(
    self.module, self.i64, name="tls_frame_top")
self.tls_frame_top.initializer = ir.Constant(self.i64, 0)
self.tls_frame_top.linkage = 'internal'
self.tls_frame_top.thread_local = 'localdynamic'

self.tls_thread_entry = ir.GlobalVariable(
    self.module, self.thread_entry_type.as_pointer(), name="tls_thread_entry")
self.tls_thread_entry.initializer = ir.Constant(
    self.thread_entry_type.as_pointer(), None)
self.tls_thread_entry.linkage = 'internal'
self.tls_thread_entry.thread_local = 'localdynamic'
```

---

## Part 3: Function Declarations

In `_declare_functions()`:

```python
# ============================================================
# Shadow Stack Operations
# ============================================================

# gc_push_frame() -> void
gc_push_frame_ty = ir.FunctionType(self.void, [])
self.gc_push_frame = ir.Function(
    self.module, gc_push_frame_ty, name="coex_gc_push_frame")

# gc_pop_frame() -> void
gc_pop_frame_ty = ir.FunctionType(self.void, [])
self.gc_pop_frame = ir.Function(
    self.module, gc_pop_frame_ty, name="coex_gc_pop_frame")

# gc_root(handle: i64) -> void
gc_root_ty = ir.FunctionType(self.void, [self.i64])
self.gc_root = ir.Function(
    self.module, gc_root_ty, name="coex_gc_root")

# ============================================================
# Thread Registry
# ============================================================

gc_register_thread_ty = ir.FunctionType(self.void, [])
self.gc_register_thread = ir.Function(
    self.module, gc_register_thread_ty, name="coex_gc_register_thread")

gc_unregister_thread_ty = ir.FunctionType(self.void, [])
self.gc_unregister_thread = ir.Function(
    self.module, gc_unregister_thread_ty, name="coex_gc_unregister_thread")

# ============================================================
# GC Operations
# ============================================================

gc_thread_main_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
self.gc_thread_main = ir.Function(
    self.module, gc_thread_main_ty, name="coex_gc_thread_main")

gc_run_cycle_ty = ir.FunctionType(self.void, [])
self.gc_run_collection_cycle = ir.Function(
    self.module, gc_run_cycle_ty, name="coex_gc_run_collection_cycle")

gc_async_ty = ir.FunctionType(self.void, [])
self.gc_async = ir.Function(
    self.module, gc_async_ty, name="coex_gc_async")

gc_wait_ty = ir.FunctionType(self.void, [])
self.gc_wait_for_completion = ir.Function(
    self.module, gc_wait_ty, name="coex_gc_wait_for_completion")

gc_collect_ty = ir.FunctionType(self.void, [])
self.gc_collect = ir.Function(
    self.module, gc_collect_ty, name="coex_gc_collect")

gc_shutdown_ty = ir.FunctionType(self.void, [])
self.gc_shutdown = ir.Function(
    self.module, gc_shutdown_ty, name="coex_gc_shutdown")

# ============================================================
# External Functions
# ============================================================

pthread_self_ty = ir.FunctionType(self.i64, [])
self.pthread_self = ir.Function(
    self.module, pthread_self_ty, name="pthread_self")

pthread_join_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr.as_pointer()])
self.pthread_join = ir.Function(
    self.module, pthread_join_ty, name="pthread_join")

pthread_cond_broadcast_ty = ir.FunctionType(self.i32, [self.i8_ptr])
self.pthread_cond_broadcast = ir.Function(
    self.module, pthread_cond_broadcast_ty, name="pthread_cond_broadcast")
```

---

## Part 4: Thread Registration

### 4.1 gc_register_thread

```python
def _implement_gc_register_thread(self):
    func = self.gc_register_thread
    entry = func.append_basic_block("entry")
    already_reg = func.append_basic_block("already_reg")
    do_reg = func.append_basic_block("do_reg")
    
    builder = ir.IRBuilder(entry)
    
    # Check if already registered
    current = builder.load(self.tls_thread_entry)
    current_int = builder.ptrtoint(current, self.i64)
    is_reg = builder.icmp_unsigned('!=', current_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_reg, already_reg, do_reg)
    
    builder.position_at_end(already_reg)
    builder.ret_void()
    
    builder.position_at_end(do_reg)
    
    # Allocate ThreadEntry (64 bytes)
    entry_raw = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 64)])
    entry_ptr = builder.bitcast(entry_raw, self.thread_entry_type.as_pointer())
    
    # Allocate handle_stack
    handle_stack_size = builder.mul(
        ir.Constant(self.i64, self.INITIAL_HANDLE_CAPACITY),
        ir.Constant(self.i64, 8))
    handle_stack_raw = builder.call(self.codegen.malloc, [handle_stack_size])
    handle_stack = builder.bitcast(handle_stack_raw, self.i64_ptr)
    
    # Allocate frame_stack
    frame_stack_size = builder.mul(
        ir.Constant(self.i64, self.INITIAL_FRAME_CAPACITY),
        ir.Constant(self.i64, 8))
    frame_stack_raw = builder.call(self.codegen.malloc, [frame_stack_size])
    frame_stack = builder.bitcast(frame_stack_raw, self.i64_ptr)
    
    # Initialize ThreadEntry fields
    # Field 0: thread_id
    tid = builder.call(self.pthread_self, [])
    tid_ptr = builder.gep(entry_ptr, 
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
    builder.store(tid, tid_ptr)
    
    # Field 1: handle_stack
    hs_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
    builder.store(handle_stack, hs_ptr)
    
    # Field 2: handle_capacity
    hc_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
    builder.store(ir.Constant(self.i64, self.INITIAL_HANDLE_CAPACITY), hc_ptr)
    
    # Field 3: handle_top = 0
    ht_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), ht_ptr)
    
    # Field 4: frame_stack
    fs_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
    builder.store(frame_stack, fs_ptr)
    
    # Field 5: frame_capacity
    fc_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)], inbounds=True)
    builder.store(ir.Constant(self.i64, self.INITIAL_FRAME_CAPACITY), fc_ptr)
    
    # Field 6: frame_top = 0
    ft_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), ft_ptr)
    
    # Field 7: next = null
    next_ptr = builder.gep(entry_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
    builder.store(ir.Constant(self.i8_ptr, None), next_ptr)
    
    # Store in TLS
    builder.store(handle_stack, self.tls_handle_stack)
    builder.store(ir.Constant(self.i64, 0), self.tls_handle_top)
    builder.store(frame_stack, self.tls_frame_stack)
    builder.store(ir.Constant(self.i64, 0), self.tls_frame_top)
    builder.store(entry_ptr, self.tls_thread_entry)
    
    # Add to registry (locked)
    mutex = builder.load(self.gc_registry_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    old_head = builder.load(self.gc_thread_registry)
    old_head_i8 = builder.bitcast(old_head, self.i8_ptr)
    builder.store(old_head_i8, next_ptr)
    builder.store(entry_ptr, self.gc_thread_registry)
    
    count = builder.load(self.gc_thread_count)
    builder.store(builder.add(count, ir.Constant(self.i64, 1)), self.gc_thread_count)
    
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    builder.ret_void()
```

### 4.2 gc_unregister_thread

```python
def _implement_gc_unregister_thread(self):
    func = self.gc_unregister_thread
    entry = func.append_basic_block("entry")
    not_reg = func.append_basic_block("not_reg")
    do_unreg = func.append_basic_block("do_unreg")
    found_head = func.append_basic_block("found_head")
    search = func.append_basic_block("search")
    search_check = func.append_basic_block("search_check")
    search_found = func.append_basic_block("search_found")
    search_next = func.append_basic_block("search_next")
    cleanup = func.append_basic_block("cleanup")
    
    builder = ir.IRBuilder(entry)
    
    my_entry = builder.load(self.tls_thread_entry)
    my_entry_int = builder.ptrtoint(my_entry, self.i64)
    is_reg = builder.icmp_unsigned('!=', my_entry_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_reg, do_unreg, not_reg)
    
    builder.position_at_end(not_reg)
    builder.ret_void()
    
    builder.position_at_end(do_unreg)
    mutex = builder.load(self.gc_registry_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    head = builder.load(self.gc_thread_registry)
    head_int = builder.ptrtoint(head, self.i64)
    is_head = builder.icmp_unsigned('==', head_int, my_entry_int)
    builder.cbranch(is_head, found_head, search)
    
    # Remove from head
    builder.position_at_end(found_head)
    next_ptr = builder.gep(my_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
    next_i8 = builder.load(next_ptr)
    next_entry = builder.bitcast(next_i8, self.thread_entry_type.as_pointer())
    builder.store(next_entry, self.gc_thread_registry)
    builder.branch(cleanup)
    
    # Search list
    builder.position_at_end(search)
    prev = builder.phi(self.thread_entry_type.as_pointer(), name="prev")
    prev.add_incoming(head, do_unreg)
    
    prev_next_ptr = builder.gep(prev,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
    curr_i8 = builder.load(prev_next_ptr)
    curr = builder.bitcast(curr_i8, self.thread_entry_type.as_pointer())
    curr_int = builder.ptrtoint(curr, self.i64)
    
    is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_null, cleanup, search_check)
    
    builder.position_at_end(search_check)
    is_me = builder.icmp_unsigned('==', curr_int, my_entry_int)
    builder.cbranch(is_me, search_found, search_next)
    
    builder.position_at_end(search_found)
    my_next_ptr = builder.gep(my_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
    my_next = builder.load(my_next_ptr)
    builder.store(my_next, prev_next_ptr)
    builder.branch(cleanup)
    
    builder.position_at_end(search_next)
    prev.add_incoming(curr, search_next)
    builder.branch(search)
    
    # Cleanup
    builder.position_at_end(cleanup)
    count = builder.load(self.gc_thread_count)
    builder.store(builder.sub(count, ir.Constant(self.i64, 1)), self.gc_thread_count)
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    # Free stacks
    hs_ptr = builder.gep(my_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
    handle_stack = builder.load(hs_ptr)
    hs_i8 = builder.bitcast(handle_stack, self.i8_ptr)
    builder.call(self.codegen.free, [hs_i8])
    
    fs_ptr = builder.gep(my_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
    frame_stack = builder.load(fs_ptr)
    fs_i8 = builder.bitcast(frame_stack, self.i8_ptr)
    builder.call(self.codegen.free, [fs_i8])
    
    # Free entry
    entry_i8 = builder.bitcast(my_entry, self.i8_ptr)
    builder.call(self.codegen.free, [entry_i8])
    
    # Clear TLS
    builder.store(ir.Constant(self.i64_ptr, None), self.tls_handle_stack)
    builder.store(ir.Constant(self.i64, 0), self.tls_handle_top)
    builder.store(ir.Constant(self.i64_ptr, None), self.tls_frame_stack)
    builder.store(ir.Constant(self.i64, 0), self.tls_frame_top)
    builder.store(ir.Constant(self.thread_entry_type.as_pointer(), None),
                  self.tls_thread_entry)
    
    builder.ret_void()
```

---

## Part 5: Shadow Stack Operations

### 5.1 gc_push_frame

```python
def _implement_gc_push_frame(self):
    """Record current handle_top as frame boundary."""
    func = self.gc_push_frame
    entry = func.append_basic_block("entry")
    
    builder = ir.IRBuilder(entry)
    
    # frame_stack[frame_top] = handle_top
    frame_stack = builder.load(self.tls_frame_stack)
    frame_top = builder.load(self.tls_frame_top)
    handle_top = builder.load(self.tls_handle_top)
    
    slot_ptr = builder.gep(frame_stack, [frame_top], inbounds=True)
    builder.store(handle_top, slot_ptr)
    
    # frame_top++
    new_frame_top = builder.add(frame_top, ir.Constant(self.i64, 1))
    builder.store(new_frame_top, self.tls_frame_top)
    
    builder.ret_void()
```

### 5.2 gc_pop_frame

```python
def _implement_gc_pop_frame(self):
    """Restore handle_top to previous frame boundary."""
    func = self.gc_pop_frame
    entry = func.append_basic_block("entry")
    
    builder = ir.IRBuilder(entry)
    
    # frame_top--
    frame_top = builder.load(self.tls_frame_top)
    new_frame_top = builder.sub(frame_top, ir.Constant(self.i64, 1))
    builder.store(new_frame_top, self.tls_frame_top)
    
    # handle_top = frame_stack[frame_top]
    frame_stack = builder.load(self.tls_frame_stack)
    slot_ptr = builder.gep(frame_stack, [new_frame_top], inbounds=True)
    saved_handle_top = builder.load(slot_ptr)
    
    # Atomic release store to handle_top (for GC visibility)
    # Also update ThreadEntry.handle_top
    thread_entry = builder.load(self.tls_thread_entry)
    ht_ptr = builder.gep(thread_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
    builder.store_atomic(saved_handle_top, ht_ptr, ordering='release', align=8)
    
    # Update TLS (non-atomic, thread-local)
    builder.store(saved_handle_top, self.tls_handle_top)
    
    builder.ret_void()
```

### 5.3 gc_root

```python
def _implement_gc_root(self):
    """Register a handle as a root in the current frame."""
    func = self.gc_root
    func.args[0].name = "handle"
    entry = func.append_basic_block("entry")
    
    builder = ir.IRBuilder(entry)
    
    handle = func.args[0]
    
    # handle_stack[handle_top] = handle
    handle_stack = builder.load(self.tls_handle_stack)
    handle_top = builder.load(self.tls_handle_top)
    
    slot_ptr = builder.gep(handle_stack, [handle_top], inbounds=True)
    builder.store(handle, slot_ptr)
    
    # handle_top++ (atomic release for GC visibility)
    new_handle_top = builder.add(handle_top, ir.Constant(self.i64, 1))
    
    thread_entry = builder.load(self.tls_thread_entry)
    ht_ptr = builder.gep(thread_entry,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
    builder.store_atomic(new_handle_top, ht_ptr, ordering='release', align=8)
    
    builder.store(new_handle_top, self.tls_handle_top)
    
    builder.ret_void()
```

---

## Part 6: Collection Cycle

### 6.1 gc_run_collection_cycle

```python
def _implement_gc_run_collection_cycle(self):
    func = self.gc_run_collection_cycle
    
    entry = func.append_basic_block("entry")
    thread_loop = func.append_basic_block("thread_loop")
    trace_thread = func.append_basic_block("trace_thread")
    handle_loop = func.append_basic_block("handle_loop")
    process_handle = func.append_basic_block("process_handle")
    next_handle = func.append_basic_block("next_handle")
    next_thread = func.append_basic_block("next_thread")
    do_sweep = func.append_basic_block("do_sweep")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Set phase = MARKING
    builder.store_atomic(ir.Constant(self.i64, 1), self.gc_phase,
                         ordering='release', align=8)
    
    # Get first thread
    first_thread = builder.load(self.gc_thread_registry)
    builder.branch(thread_loop)
    
    # === Thread loop ===
    builder.position_at_end(thread_loop)
    curr_thread = builder.phi(self.thread_entry_type.as_pointer(), name="thread")
    curr_thread.add_incoming(first_thread, entry)
    
    thread_int = builder.ptrtoint(curr_thread, self.i64)
    is_null = builder.icmp_unsigned('==', thread_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_null, do_sweep, trace_thread)
    
    # === Trace thread ===
    builder.position_at_end(trace_thread)
    
    # Snapshot handle_top (atomic acquire)
    ht_ptr = builder.gep(curr_thread,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
    snapshot_top = builder.load_atomic(ht_ptr, ordering='acquire', align=8)
    
    # Get handle_stack pointer
    hs_ptr = builder.gep(curr_thread,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
    handle_stack = builder.load(hs_ptr)
    
    builder.branch(handle_loop)
    
    # === Handle loop ===
    builder.position_at_end(handle_loop)
    idx = builder.phi(self.i64, name="idx")
    idx.add_incoming(ir.Constant(self.i64, 0), trace_thread)
    
    done_handles = builder.icmp_unsigned('>=', idx, snapshot_top)
    builder.cbranch(done_handles, next_thread, process_handle)
    
    # === Process handle ===
    builder.position_at_end(process_handle)
    
    slot_ptr = builder.gep(handle_stack, [idx], inbounds=True)
    handle = builder.load(slot_ptr)
    
    # Skip null handles
    is_zero = builder.icmp_unsigned('==', handle, ir.Constant(self.i64, 0))
    with builder.if_then(builder.not_(is_zero)):
        # Mark object via handle
        builder.call(self.gc_mark_from_handle, [handle])
    
    builder.branch(next_handle)
    
    # === Next handle ===
    builder.position_at_end(next_handle)
    next_idx = builder.add(idx, ir.Constant(self.i64, 1))
    idx.add_incoming(next_idx, next_handle)
    builder.branch(handle_loop)
    
    # === Next thread ===
    builder.position_at_end(next_thread)
    next_ptr = builder.gep(curr_thread,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
    next_i8 = builder.load(next_ptr)
    next_entry = builder.bitcast(next_i8, self.thread_entry_type.as_pointer())
    curr_thread.add_incoming(next_entry, next_thread)
    builder.branch(thread_loop)
    
    # === Sweep ===
    builder.position_at_end(do_sweep)
    builder.store_atomic(ir.Constant(self.i64, 2), self.gc_phase,
                         ordering='release', align=8)
    
    # gc_sweep_threshold = gc_cycle_id - 1
    cycle_id = builder.load(self.gc_cycle_id)
    threshold = builder.sub(cycle_id, ir.Constant(self.i64, 1))
    builder.store(threshold, self.gc_sweep_threshold)
    
    # Call sweep
    builder.call(self.gc_sweep, [])
    
    # gc_cycle_id++
    new_cycle = builder.add(cycle_id, ir.Constant(self.i64, 1))
    builder.store(new_cycle, self.gc_cycle_id)
    
    builder.branch(done)
    
    # === Done ===
    builder.position_at_end(done)
    builder.store_atomic(ir.Constant(self.i64, 0), self.gc_phase,
                         ordering='release', align=8)
    builder.ret_void()
```

### 6.2 gc_mark_from_handle

```python
def _implement_gc_mark_from_handle(self):
    """Mark object referenced by handle, trace children."""
    func = self.gc_mark_from_handle
    func.args[0].name = "handle"
    
    entry = func.append_basic_block("entry")
    check_marked = func.append_basic_block("check_marked")
    do_mark = func.append_basic_block("do_mark")
    already_marked = func.append_basic_block("already_marked")
    
    builder = ir.IRBuilder(entry)
    
    handle = func.args[0]
    
    # Dereference handle to get object pointer
    obj_ptr = builder.call(self.gc_handle_deref, [handle])
    
    # Null check
    obj_int = builder.ptrtoint(obj_ptr, self.i64)
    is_null = builder.icmp_unsigned('==', obj_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_null, already_marked, check_marked)
    
    builder.position_at_end(check_marked)
    
    # Get mark field
    mark_ptr = builder.gep(obj_ptr,
        [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
    current_mark = builder.load(mark_ptr)
    
    # Check if already marked this cycle
    cycle_id = builder.load(self.gc_cycle_id)
    is_marked = builder.icmp_unsigned('==', current_mark, cycle_id)
    builder.cbranch(is_marked, already_marked, do_mark)
    
    builder.position_at_end(do_mark)
    
    # Set mark = gc_cycle_id
    builder.store(cycle_id, mark_ptr)
    
    # Trace children (call existing gc_mark_object which traces by type)
    builder.call(self.gc_mark_object, [obj_ptr])
    
    builder.branch(already_marked)
    
    builder.position_at_end(already_marked)
    builder.ret_void()
```

---

## Part 7: GC Thread

### 7.1 gc_thread_main

```python
def _implement_gc_thread_main(self):
    func = self.gc_thread_main
    func.args[0].name = "arg"
    
    entry = func.append_basic_block("entry")
    loop_start = func.append_basic_block("loop_start")
    wait_loop = func.append_basic_block("wait_loop")
    check_wake = func.append_basic_block("check_wake")
    check_shutdown = func.append_basic_block("check_shutdown")
    do_shutdown = func.append_basic_block("do_shutdown")
    do_collect = func.append_basic_block("do_collect")
    signal_done = func.append_basic_block("signal_done")
    
    builder = ir.IRBuilder(entry)
    builder.branch(loop_start)
    
    builder.position_at_end(loop_start)
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.branch(wait_loop)
    
    builder.position_at_end(wait_loop)
    in_prog = builder.load(self.gc_in_progress)
    shutdown = builder.load(self.gc_shutdown_flag)
    has_work = builder.icmp_unsigned('!=', in_prog, ir.Constant(self.i64, 0))
    should_stop = builder.icmp_unsigned('!=', shutdown, ir.Constant(self.i64, 0))
    wake = builder.or_(has_work, should_stop)
    builder.cbranch(wake, check_shutdown, check_wake)
    
    builder.position_at_end(check_wake)
    cond = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_wait, [cond, mutex])
    builder.branch(wait_loop)
    
    builder.position_at_end(check_shutdown)
    shutdown2 = builder.load(self.gc_shutdown_flag)
    is_shutdown = builder.icmp_unsigned('!=', shutdown2, ir.Constant(self.i64, 0))
    builder.cbranch(is_shutdown, do_shutdown, do_collect)
    
    builder.position_at_end(do_shutdown)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.ret(ir.Constant(self.i8_ptr, None))
    
    builder.position_at_end(do_collect)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.call(self.gc_run_collection_cycle, [])
    builder.branch(signal_done)
    
    builder.position_at_end(signal_done)
    mutex2 = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex2])
    builder.store(ir.Constant(self.i64, 0), self.gc_in_progress)
    cond_done = builder.load(self.gc_cond_done)
    builder.call(self.pthread_cond_broadcast, [cond_done])
    builder.call(self.pthread_mutex_unlock, [mutex2])
    builder.branch(loop_start)
```

### 7.2 gc_async

```python
def _implement_gc_async(self):
    func = self.gc_async
    entry = func.append_basic_block("entry")
    already = func.append_basic_block("already")
    trigger = func.append_basic_block("trigger")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    in_prog = builder.load(self.gc_in_progress)
    is_running = builder.icmp_unsigned('!=', in_prog, ir.Constant(self.i64, 0))
    builder.cbranch(is_running, already, trigger)
    
    builder.position_at_end(already)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(done)
    
    builder.position_at_end(trigger)
    builder.store(ir.Constant(self.i64, 1), self.gc_in_progress)
    cond = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_signal, [cond])
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.branch(done)
    
    builder.position_at_end(done)
    builder.ret_void()
```

### 7.3 gc_wait_for_completion

```python
def _implement_gc_wait_for_completion(self):
    func = self.gc_wait_for_completion
    entry = func.append_basic_block("entry")
    wait_loop = func.append_basic_block("wait_loop")
    do_wait = func.append_basic_block("do_wait")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.branch(wait_loop)
    
    builder.position_at_end(wait_loop)
    in_prog = builder.load(self.gc_in_progress)
    is_running = builder.icmp_unsigned('!=', in_prog, ir.Constant(self.i64, 0))
    builder.cbranch(is_running, do_wait, done)
    
    builder.position_at_end(do_wait)
    cond = builder.load(self.gc_cond_done)
    mutex2 = builder.load(self.gc_mutex)
    builder.call(self.pthread_cond_wait, [cond, mutex2])
    builder.branch(wait_loop)
    
    builder.position_at_end(done)
    mutex3 = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_unlock, [mutex3])
    builder.ret_void()
```

### 7.4 gc_collect

```python
def _implement_gc_collect(self):
    func = self.gc_collect
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    builder.call(self.gc_async, [])
    builder.call(self.gc_wait_for_completion, [])
    builder.ret_void()
```

### 7.5 gc_shutdown

```python
def _implement_gc_shutdown(self):
    func = self.gc_shutdown
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    builder.call(self.gc_wait_for_completion, [])
    
    mutex = builder.load(self.gc_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    builder.store(ir.Constant(self.i64, 1), self.gc_shutdown_flag)
    cond = builder.load(self.gc_cond_start)
    builder.call(self.pthread_cond_signal, [cond])
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    gc_thread = builder.load(self.gc_thread)
    builder.call(self.pthread_join,
        [gc_thread, ir.Constant(self.i8_ptr.as_pointer(), None)])
    
    builder.ret_void()
```

---

## Part 8: Initialization

### 8.1 gc_init additions

Add to existing gc_init:

```python
# Initialize registry mutex
mutex_ptr = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 64)])
builder.store(mutex_ptr, self.gc_registry_mutex)
builder.call(self.pthread_mutex_init, [mutex_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize GC mutex
gc_mutex_ptr = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 64)])
builder.store(gc_mutex_ptr, self.gc_mutex)
builder.call(self.pthread_mutex_init, [gc_mutex_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize condition variables
cond_start_ptr = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 64)])
builder.store(cond_start_ptr, self.gc_cond_start)
builder.call(self.pthread_cond_init, [cond_start_ptr, ir.Constant(self.i8_ptr, None)])

cond_done_ptr = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 64)])
builder.store(cond_done_ptr, self.gc_cond_done)
builder.call(self.pthread_cond_init, [cond_done_ptr, ir.Constant(self.i8_ptr, None)])

# Initialize state
builder.store(ir.Constant(self.i64, 0), self.gc_phase)
builder.store(ir.Constant(self.i64, 1), self.gc_cycle_id)
builder.store(ir.Constant(self.i64, 0), self.gc_sweep_threshold)
builder.store(ir.Constant(self.i64, 0), self.gc_in_progress)
builder.store(ir.Constant(self.i64, 0), self.gc_shutdown_flag)
builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)

# Register main thread
builder.call(self.gc_register_thread, [])

# Spawn GC thread
thread_ptr = builder.call(self.codegen.malloc, [ir.Constant(self.i64, 8)])
gc_main_ptr = builder.bitcast(self.gc_thread_main, self.i8_ptr)
builder.call(self.pthread_create, [
    thread_ptr,
    ir.Constant(self.i8_ptr, None),
    gc_main_ptr,
    ir.Constant(self.i8_ptr, None)
])
thread_handle = builder.load(builder.bitcast(thread_ptr, self.i8_ptr.as_pointer()))
builder.store(thread_handle, self.gc_thread)
```

---

## Part 9: Update gc_alloc

Add birth-marking and allocation counting:

```python
# After allocating object header:
cycle_id = builder.load(self.gc_cycle_id)
mark_ptr = builder.gep(header, [...], inbounds=True)  # mark field
builder.store(cycle_id, mark_ptr)

# Increment allocation count (for auto-trigger)
alloc_count = builder.load(self.gc_alloc_count)
new_count = builder.add(alloc_count, ir.Constant(self.i64, 1))
builder.store(new_count, self.gc_alloc_count)
```

---

## Part 10: Update gc_sweep

Use cycle-based threshold:

```python
# In sweep loop:
mark = builder.load(object_mark_ptr)
threshold = builder.load(self.gc_sweep_threshold)
is_garbage = builder.icmp_unsigned('<', mark, threshold)
# if is_garbage: free object
```

---

## Part 11: Auto-trigger (optional)

Add to gc_safepoint or a periodic check:

```python
def _implement_gc_safepoint(self):
    func = self.gc_safepoint
    entry = func.append_basic_block("entry")
    do_trigger = func.append_basic_block("do_trigger")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    alloc_count = builder.load(self.gc_alloc_count)
    threshold = builder.load(self.gc_trigger_threshold)
    should_trigger = builder.icmp_unsigned('>=', alloc_count, threshold)
    builder.cbranch(should_trigger, do_trigger, done)
    
    builder.position_at_end(do_trigger)
    builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)
    builder.call(self.gc_async, [])
    builder.branch(done)
    
    builder.position_at_end(done)
    builder.ret_void()
```

---

## Part 12: Codegen Integration

### 12.1 Function Prologue

In codegen.py, each function should:

```python
# At function entry:
builder.call(gc.gc_push_frame, [])

# For each local variable that holds a handle:
# After assignment: builder.call(gc.gc_root, [handle])
```

### 12.2 Function Epilogue

```python
# Before return:
builder.call(gc.gc_pop_frame, [])
```

### 12.3 Main Function

```python
# At end of main, before return:
builder.call(gc.gc_shutdown, [])
```

---

## Summary

Key differences from sentinel design:

| Aspect | Old (Sentinel) | New (Snapshot) |
|--------|----------------|----------------|
| Shadow stack | Linked list | Contiguous array |
| GC/mutator sync | Sentinel + halt flag | None |
| Frame push | malloc, link | Store index |
| Frame pop | Free, check sentinel | Restore index |
| Root registration | Store in frame slots | gc_root() call |
| GC trace | Walk list, check halt | Read array slice |
| Cycle completion | May abandon | Always completes |
| Memory safety | Race conditions | Always safe |

The new design is simpler, faster, and correct by construction.
