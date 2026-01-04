# Coex Thread Registry Implementation

## Project Overview

Implement the thread registry infrastructure in `coex_gc.py` to support multiple mutator threads. This is the foundation for concurrent garbage collection and task spawning.

### Prerequisites

- Handle-based GC is complete and working (185 tests passing)
- Shadow stack with handle slots is operational
- Pthread primitives are declared (pthread_mutex_*, pthread_cond_*)

### Deliverables

1. ThreadEntry type and global registry
2. Thread-local storage for shadow stack
3. Thread registration/unregistration functions
4. Updated shadow stack operations (push/pop frame)
5. Updated gc_scan_roots for multi-thread iteration
6. Watermark protocol integration in gc_safepoint and gc_collect

---

## Part 1: Type and Global Definitions

### 1.1 Add ThreadEntry Type

In `_create_types()`, add after the existing type definitions:

```python
# ThreadEntry: Per-thread GC state
# All pointer-sized fields for cross-platform consistency
self.thread_entry_type = ir.LiteralStructType([
    self.i64,     # 0:  thread_id - platform thread identifier
    self.i8_ptr,  # 8:  shadow_stack_head - pointer to thread's frame top location
    self.i64,     # 16: watermark_depth - stack depth when watermark set (0 = none)
    self.i64,     # 24: watermark_active - 1 if acknowledged current GC cycle
    self.i64,     # 32: stack_depth - current shadow stack depth
    self.i64,     # 40: last_gc_cycle - last GC cycle acknowledged
    self.i8_ptr,  # 48: tlab_base - thread-local alloc buffer (future)
    self.i8_ptr,  # 56: tlab_cursor - current TLAB position (future)
    self.i8_ptr,  # 64: tlab_end - end of TLAB (future)
    self.i8_ptr,  # 72: next - next ThreadEntry in registry
])
# Total: 80 bytes
```

### 1.2 Add Global Registry Variables

In `_create_globals()`, add after existing globals:

```python
# ============================================================
# Thread Registry Globals
# ============================================================

# Head of thread registry linked list
self.gc_thread_registry = ir.GlobalVariable(
    self.module, self.thread_entry_type.as_pointer(), name="gc_thread_registry")
self.gc_thread_registry.initializer = ir.Constant(
    self.thread_entry_type.as_pointer(), None)
self.gc_thread_registry.linkage = 'internal'

# Count of registered threads
self.gc_thread_count = ir.GlobalVariable(
    self.module, self.i64, name="gc_thread_count")
self.gc_thread_count.initializer = ir.Constant(self.i64, 0)
self.gc_thread_count.linkage = 'internal'

# Mutex for registry modifications (pointer to allocated mutex)
self.gc_registry_mutex = ir.GlobalVariable(
    self.module, self.i8_ptr, name="gc_registry_mutex")
self.gc_registry_mutex.initializer = ir.Constant(self.i8_ptr, None)
self.gc_registry_mutex.linkage = 'internal'

# GC phase: 0=idle, 1=watermark, 2=marking, 3=sweeping
self.gc_phase = ir.GlobalVariable(
    self.module, self.i64, name="gc_phase")
self.gc_phase.initializer = ir.Constant(self.i64, 0)
self.gc_phase.linkage = 'internal'

# GC cycle counter (monotonically increasing)
self.gc_cycle_id = ir.GlobalVariable(
    self.module, self.i64, name="gc_cycle_id")
self.gc_cycle_id.initializer = ir.Constant(self.i64, 0)
self.gc_cycle_id.linkage = 'internal'
```

### 1.3 Add Thread-Local Storage Variables

```python
# ============================================================
# Thread-Local Storage Variables
# ============================================================
# These use LLVM's thread_local attribute for per-thread storage

# Thread's shadow stack frame chain top
self.tls_frame_top = ir.GlobalVariable(
    self.module, self.i8_ptr, name="tls_frame_top")
self.tls_frame_top.initializer = ir.Constant(self.i8_ptr, None)
self.tls_frame_top.linkage = 'internal'
self.tls_frame_top.thread_local = 'localdynamic'  # Or 'initialexec' for executables

# Thread's shadow stack depth
self.tls_frame_depth = ir.GlobalVariable(
    self.module, self.i64, name="tls_frame_depth")
self.tls_frame_depth.initializer = ir.Constant(self.i64, 0)
self.tls_frame_depth.linkage = 'internal'
self.tls_frame_depth.thread_local = 'localdynamic'

# Pointer to thread's ThreadEntry
self.tls_thread_entry = ir.GlobalVariable(
    self.module, self.thread_entry_type.as_pointer(), name="tls_thread_entry")
self.tls_thread_entry.initializer = ir.Constant(
    self.thread_entry_type.as_pointer(), None)
self.tls_thread_entry.linkage = 'internal'
self.tls_thread_entry.thread_local = 'localdynamic'
```

**Note:** llvmlite supports thread_local via the `thread_local` property on GlobalVariable. Valid values are: `'localdynamic'`, `'initialexec'`, `'localexec'`. Use `'localdynamic'` for compatibility with shared libraries.

---

## Part 2: Function Declarations

### 2.1 Add New Function Declarations

In `_declare_functions()`, add:

```python
# ============================================================
# Thread Registry Function Declarations
# ============================================================

# gc_register_thread() -> void
# Called at thread start; allocates and registers ThreadEntry
gc_register_thread_ty = ir.FunctionType(self.void, [])
self.gc_register_thread = ir.Function(
    self.module, gc_register_thread_ty, name="coex_gc_register_thread")

# gc_unregister_thread() -> void
# Called at thread exit; removes ThreadEntry from registry
gc_unregister_thread_ty = ir.FunctionType(self.void, [])
self.gc_unregister_thread = ir.Function(
    self.module, gc_unregister_thread_ty, name="coex_gc_unregister_thread")

# gc_get_thread_entry() -> ThreadEntry*
# Returns calling thread's ThreadEntry from TLS
gc_get_thread_entry_ty = ir.FunctionType(
    self.thread_entry_type.as_pointer(), [])
self.gc_get_thread_entry = ir.Function(
    self.module, gc_get_thread_entry_ty, name="coex_gc_get_thread_entry")

# pthread_self() -> i64
# External: get current thread ID
pthread_self_ty = ir.FunctionType(self.i64, [])
self.pthread_self = ir.Function(
    self.module, pthread_self_ty, name="pthread_self")
```

### 2.2 Add Member Variables to __init__

In `__init__()`, add:

```python
# Thread registry
self.thread_entry_type = None
self.gc_thread_registry = None
self.gc_thread_count = None
self.gc_registry_mutex = None
self.gc_phase = None
self.gc_cycle_id = None

# Thread-local storage
self.tls_frame_top = None
self.tls_frame_depth = None
self.tls_thread_entry = None

# Thread registry functions
self.gc_register_thread = None
self.gc_unregister_thread = None
self.gc_get_thread_entry = None
self.pthread_self = None
```

---

## Part 3: Function Implementations

### 3.1 Implement gc_register_thread

```python
def _implement_gc_register_thread(self):
    """Register the calling thread with the GC.
    
    Allocates a ThreadEntry, initializes it with the thread's TLS locations,
    and adds it to the global registry under mutex protection.
    """
    func = self.gc_register_thread
    
    entry = func.append_basic_block("entry")
    already_registered = func.append_basic_block("already_registered")
    do_register = func.append_basic_block("do_register")
    
    builder = ir.IRBuilder(entry)
    
    # Check if already registered (TLS entry not null)
    current_entry = builder.load(self.tls_thread_entry)
    current_entry_int = builder.ptrtoint(current_entry, self.i64)
    is_registered = builder.icmp_unsigned(
        '!=', current_entry_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_registered, already_registered, do_register)
    
    # Already registered - return
    builder.position_at_end(already_registered)
    builder.ret_void()
    
    # Do registration
    builder.position_at_end(do_register)
    
    # Allocate ThreadEntry (80 bytes)
    entry_size = ir.Constant(self.i64, 80)
    raw_entry = builder.call(self.codegen.malloc, [entry_size])
    new_entry = builder.bitcast(raw_entry, self.thread_entry_type.as_pointer())
    
    # Get current thread ID
    thread_id = builder.call(self.pthread_self, [])
    
    # Initialize ThreadEntry fields
    # Field 0: thread_id
    tid_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
    ], inbounds=True)
    builder.store(thread_id, tid_ptr)
    
    # Field 1: shadow_stack_head - pointer to tls_frame_top
    head_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
    ], inbounds=True)
    tls_frame_top_addr = builder.bitcast(self.tls_frame_top, self.i8_ptr)
    builder.store(tls_frame_top_addr, head_ptr)
    
    # Field 2: watermark_depth = 0
    wm_depth_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), wm_depth_ptr)
    
    # Field 3: watermark_active = 0
    wm_active_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), wm_active_ptr)
    
    # Field 4: stack_depth = 0
    depth_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), depth_ptr)
    
    # Field 5: last_gc_cycle = 0
    cycle_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), cycle_ptr)
    
    # Fields 6-8: TLAB pointers = null
    for i in [6, 7, 8]:
        tlab_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, i)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), tlab_ptr)
    
    # Field 9: next = null (will be set when linking)
    next_ptr = builder.gep(new_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    builder.store(ir.Constant(self.i8_ptr, None), next_ptr)
    
    # Lock registry mutex
    mutex = builder.load(self.gc_registry_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Prepend to registry: new_entry->next = gc_thread_registry
    old_head = builder.load(self.gc_thread_registry)
    old_head_i8 = builder.bitcast(old_head, self.i8_ptr)
    builder.store(old_head_i8, next_ptr)
    
    # gc_thread_registry = new_entry
    builder.store(new_entry, self.gc_thread_registry)
    
    # Increment thread count
    count = builder.load(self.gc_thread_count)
    new_count = builder.add(count, ir.Constant(self.i64, 1))
    builder.store(new_count, self.gc_thread_count)
    
    # Unlock registry mutex
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    # Store in TLS
    builder.store(new_entry, self.tls_thread_entry)
    
    builder.ret_void()
```

### 3.2 Implement gc_unregister_thread

```python
def _implement_gc_unregister_thread(self):
    """Unregister the calling thread from the GC.
    
    Removes the ThreadEntry from the registry and frees it.
    Must be called before thread exit, after all handles are dropped.
    """
    func = self.gc_unregister_thread
    
    entry = func.append_basic_block("entry")
    not_registered = func.append_basic_block("not_registered")
    do_unregister = func.append_basic_block("do_unregister")
    search_loop = func.append_basic_block("search_loop")
    found_at_head = func.append_basic_block("found_at_head")
    search_continue = func.append_basic_block("search_continue")
    found_in_list = func.append_basic_block("found_in_list")
    search_next = func.append_basic_block("search_next")
    not_found = func.append_basic_block("not_found")
    cleanup = func.append_basic_block("cleanup")
    
    builder = ir.IRBuilder(entry)
    
    # Get current ThreadEntry from TLS
    my_entry = builder.load(self.tls_thread_entry)
    my_entry_int = builder.ptrtoint(my_entry, self.i64)
    is_registered = builder.icmp_unsigned(
        '!=', my_entry_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_registered, do_unregister, not_registered)
    
    # Not registered - return
    builder.position_at_end(not_registered)
    builder.ret_void()
    
    # Do unregistration
    builder.position_at_end(do_unregister)
    
    # Lock registry mutex
    mutex = builder.load(self.gc_registry_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Check if at head of list
    head = builder.load(self.gc_thread_registry)
    head_int = builder.ptrtoint(head, self.i64)
    my_entry_int2 = builder.ptrtoint(my_entry, self.i64)
    is_head = builder.icmp_unsigned('==', head_int, my_entry_int2)
    builder.cbranch(is_head, found_at_head, search_loop)
    
    # Found at head - remove
    builder.position_at_end(found_at_head)
    next_ptr = builder.gep(my_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    next_entry_i8 = builder.load(next_ptr)
    next_entry = builder.bitcast(next_entry_i8, self.thread_entry_type.as_pointer())
    builder.store(next_entry, self.gc_thread_registry)
    builder.branch(cleanup)
    
    # Search for entry in list
    builder.position_at_end(search_loop)
    # prev and curr phi nodes
    prev_phi = builder.phi(self.thread_entry_type.as_pointer(), name="prev")
    prev_phi.add_incoming(head, do_unregister)
    
    # Get prev->next
    prev_next_ptr = builder.gep(prev_phi, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    curr_i8 = builder.load(prev_next_ptr)
    curr = builder.bitcast(curr_i8, self.thread_entry_type.as_pointer())
    
    # Check if curr is null
    curr_int = builder.ptrtoint(curr, self.i64)
    curr_is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
    builder.cbranch(curr_is_null, not_found, search_continue)
    
    # Check if curr is my_entry
    builder.position_at_end(search_continue)
    is_mine = builder.icmp_unsigned('==', curr_int, my_entry_int2)
    builder.cbranch(is_mine, found_in_list, search_next)
    
    # Found in list - unlink
    builder.position_at_end(found_in_list)
    my_next_ptr = builder.gep(my_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    my_next = builder.load(my_next_ptr)
    builder.store(my_next, prev_next_ptr)  # prev->next = my->next
    builder.branch(cleanup)
    
    # Continue search
    builder.position_at_end(search_next)
    prev_phi.add_incoming(curr, search_next)
    builder.branch(search_loop)
    
    # Not found (shouldn't happen)
    builder.position_at_end(not_found)
    builder.branch(cleanup)
    
    # Cleanup
    builder.position_at_end(cleanup)
    
    # Decrement thread count
    count = builder.load(self.gc_thread_count)
    new_count = builder.sub(count, ir.Constant(self.i64, 1))
    builder.store(new_count, self.gc_thread_count)
    
    # Unlock mutex
    builder.call(self.pthread_mutex_unlock, [mutex])
    
    # Free ThreadEntry
    my_entry_i8 = builder.bitcast(my_entry, self.i8_ptr)
    builder.call(self.codegen.free, [my_entry_i8])
    
    # Clear TLS
    builder.store(
        ir.Constant(self.thread_entry_type.as_pointer(), None),
        self.tls_thread_entry)
    
    builder.ret_void()
```

### 3.3 Implement gc_get_thread_entry

```python
def _implement_gc_get_thread_entry(self):
    """Return the calling thread's ThreadEntry from TLS."""
    func = self.gc_get_thread_entry
    
    entry_block = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry_block)
    
    thread_entry = builder.load(self.tls_thread_entry)
    builder.ret(thread_entry)
```

---

## Part 4: Update Existing Functions

### 4.1 Update gc_init

Add after existing initialization, before `builder.ret_void()`:

```python
# Initialize registry mutex
registry_mutex_size = ir.Constant(self.i64, 64)
registry_mutex_ptr = builder.call(self.codegen.malloc, [registry_mutex_size])
builder.store(registry_mutex_ptr, self.gc_registry_mutex)
builder.call(self.pthread_mutex_init, [
    registry_mutex_ptr, ir.Constant(self.i8_ptr, None)
])

# Initialize GC phase and cycle
builder.store(ir.Constant(self.i64, 0), self.gc_phase)
builder.store(ir.Constant(self.i64, 0), self.gc_cycle_id)

# Register main thread
builder.call(self.gc_register_thread, [])
```

### 4.2 Update gc_push_frame

Replace the current implementation to use TLS:

```python
def _implement_gc_push_frame(self):
    """Push a new frame onto the calling thread's shadow stack.
    
    Uses thread-local storage for the frame chain.
    """
    func = self.gc_push_frame
    func.args[0].name = "num_roots"
    func.args[1].name = "handle_slots"
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    num_roots = func.args[0]
    handle_slots = func.args[1]
    
    # Allocate frame struct (24 bytes)
    frame_size = ir.Constant(self.i64, 24)
    raw_frame = builder.call(self.codegen.malloc, [frame_size])
    frame = builder.bitcast(raw_frame, self.gc_frame_type.as_pointer())
    
    # Set parent to current TLS top
    old_top = builder.load(self.tls_frame_top)
    parent_ptr = builder.gep(frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
    ], inbounds=True)
    builder.store(old_top, parent_ptr)
    
    # Set num_roots
    num_roots_ptr = builder.gep(frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
    ], inbounds=True)
    builder.store(num_roots, num_roots_ptr)
    
    # Set handle_slots pointer
    slots_ptr_ptr = builder.gep(frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(handle_slots, slots_ptr_ptr)
    
    # Update TLS frame top
    builder.store(raw_frame, self.tls_frame_top)
    
    # Increment TLS frame depth
    depth = builder.load(self.tls_frame_depth)
    new_depth = builder.add(depth, ir.Constant(self.i64, 1))
    builder.store(new_depth, self.tls_frame_depth)
    
    # Also update ThreadEntry.stack_depth if registered
    thread_entry = builder.load(self.tls_thread_entry)
    entry_int = builder.ptrtoint(thread_entry, self.i64)
    is_registered = builder.icmp_unsigned(
        '!=', entry_int, ir.Constant(self.i64, 0))
    
    with builder.if_then(is_registered):
        te_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(new_depth, te_depth_ptr)
    
    builder.ret(raw_frame)
```

### 4.3 Update gc_pop_frame

```python
def _implement_gc_pop_frame(self):
    """Pop a frame from the calling thread's shadow stack."""
    func = self.gc_pop_frame
    func.args[0].name = "frame_ptr"
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    frame_ptr = func.args[0]
    frame = builder.bitcast(frame_ptr, self.gc_frame_type.as_pointer())
    
    # Get parent and set as new TLS top
    parent_ptr = builder.gep(frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
    ], inbounds=True)
    parent = builder.load(parent_ptr)
    builder.store(parent, self.tls_frame_top)
    
    # Decrement TLS frame depth
    depth = builder.load(self.tls_frame_depth)
    new_depth = builder.sub(depth, ir.Constant(self.i64, 1))
    builder.store(new_depth, self.tls_frame_depth)
    
    # Also update ThreadEntry.stack_depth if registered
    thread_entry = builder.load(self.tls_thread_entry)
    entry_int = builder.ptrtoint(thread_entry, self.i64)
    is_registered = builder.icmp_unsigned(
        '!=', entry_int, ir.Constant(self.i64, 0))
    
    with builder.if_then(is_registered):
        te_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(new_depth, te_depth_ptr)
    
    # Free the frame
    builder.call(self.codegen.free, [frame_ptr])
    
    builder.ret_void()
```

### 4.4 Update gc_safepoint

Replace the current implementation:

```python
def _implement_gc_safepoint(self):
    """Check GC phase and acknowledge watermark if needed.
    
    Called at function entry and loop back-edges.
    """
    func = self.gc_safepoint
    
    entry = func.append_basic_block("entry")
    check_phase = func.append_basic_block("check_phase")
    check_ack = func.append_basic_block("check_ack")
    do_ack = func.append_basic_block("do_ack")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Load gc_phase (acquire semantics for visibility)
    phase = builder.load_atomic(self.gc_phase, ordering='acquire', align=8)
    
    # If phase == 0 (IDLE), nothing to do
    is_idle = builder.icmp_unsigned('==', phase, ir.Constant(self.i64, 0))
    builder.cbranch(is_idle, done, check_phase)
    
    # Check if we need to acknowledge
    builder.position_at_end(check_phase)
    
    # Get ThreadEntry
    thread_entry = builder.load(self.tls_thread_entry)
    entry_int = builder.ptrtoint(thread_entry, self.i64)
    not_registered = builder.icmp_unsigned(
        '==', entry_int, ir.Constant(self.i64, 0))
    builder.cbranch(not_registered, done, check_ack)
    
    # Check watermark_active
    builder.position_at_end(check_ack)
    wm_active_ptr = builder.gep(thread_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    wm_active = builder.load(wm_active_ptr)
    already_acked = builder.icmp_unsigned(
        '!=', wm_active, ir.Constant(self.i64, 0))
    builder.cbranch(already_acked, done, do_ack)
    
    # Acknowledge watermark
    builder.position_at_end(do_ack)
    
    # watermark_depth = stack_depth
    depth_ptr = builder.gep(thread_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
    ], inbounds=True)
    stack_depth = builder.load(depth_ptr)
    
    wm_depth_ptr = builder.gep(thread_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(stack_depth, wm_depth_ptr)
    
    # last_gc_cycle = gc_cycle_id
    cycle_id = builder.load(self.gc_cycle_id)
    last_cycle_ptr = builder.gep(thread_entry, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
    ], inbounds=True)
    builder.store(cycle_id, last_cycle_ptr)
    
    # watermark_active = 1 (release semantics)
    builder.store_atomic(
        ir.Constant(self.i64, 1), wm_active_ptr,
        ordering='release', align=8)
    
    builder.branch(done)
    
    builder.position_at_end(done)
    builder.ret_void()
```

### 4.5 Update gc_scan_roots

Replace the current implementation to iterate the thread registry:

```python
def _implement_gc_scan_roots(self):
    """Scan roots from all registered threads.
    
    Iterates the thread registry and marks handles from each thread's
    shadow stack, respecting watermark depth.
    """
    func = self.gc_scan_roots
    
    entry = func.append_basic_block("entry")
    thread_loop = func.append_basic_block("thread_loop")
    process_thread = func.append_basic_block("process_thread")
    frame_loop = func.append_basic_block("frame_loop")
    process_frame = func.append_basic_block("process_frame")
    check_watermark = func.append_basic_block("check_watermark")
    scan_slots = func.append_basic_block("scan_slots")
    slot_loop = func.append_basic_block("slot_loop")
    mark_handle = func.append_basic_block("mark_handle")
    next_slot = func.append_basic_block("next_slot")
    next_frame = func.append_basic_block("next_frame")
    next_thread = func.append_basic_block("next_thread")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Lock registry for iteration (brief hold)
    mutex = builder.load(self.gc_registry_mutex)
    builder.call(self.pthread_mutex_lock, [mutex])
    
    # Start with head of registry
    first_thread = builder.load(self.gc_thread_registry)
    builder.branch(thread_loop)
    
    # Thread loop
    builder.position_at_end(thread_loop)
    curr_thread = builder.phi(
        self.thread_entry_type.as_pointer(), name="curr_thread")
    curr_thread.add_incoming(first_thread, entry)
    
    # Check if null
    thread_int = builder.ptrtoint(curr_thread, self.i64)
    thread_is_null = builder.icmp_unsigned(
        '==', thread_int, ir.Constant(self.i64, 0))
    builder.cbranch(thread_is_null, done, process_thread)
    
    # Process this thread
    builder.position_at_end(process_thread)
    
    # Get shadow_stack_head (pointer to the TLS frame_top location)
    head_ptr_ptr = builder.gep(curr_thread, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
    ], inbounds=True)
    head_ptr = builder.load(head_ptr_ptr)  # i8* pointing to frame_top location
    
    # Cast to i8** and load the actual frame pointer
    head_ptr_typed = builder.bitcast(head_ptr, self.i8_ptr.as_pointer())
    first_frame = builder.load(head_ptr_typed)
    
    # Get watermark_depth for this thread
    wm_depth_ptr = builder.gep(curr_thread, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    watermark_depth = builder.load(wm_depth_ptr)
    
    # Initialize frame depth counter
    builder.branch(frame_loop)
    
    # Frame loop
    builder.position_at_end(frame_loop)
    curr_frame_raw = builder.phi(self.i8_ptr, name="curr_frame")
    curr_frame_raw.add_incoming(first_frame, process_thread)
    frame_depth = builder.phi(self.i64, name="frame_depth")
    frame_depth.add_incoming(ir.Constant(self.i64, 0), process_thread)
    
    # Check if null frame
    frame_int = builder.ptrtoint(curr_frame_raw, self.i64)
    frame_is_null = builder.icmp_unsigned(
        '==', frame_int, ir.Constant(self.i64, 0))
    builder.cbranch(frame_is_null, next_thread, process_frame)
    
    # Process frame
    builder.position_at_end(process_frame)
    curr_frame = builder.bitcast(curr_frame_raw, self.gc_frame_type.as_pointer())
    
    # Check watermark: only scan if depth < watermark_depth
    # (or if watermark_depth == 0, meaning no watermark, scan all)
    builder.branch(check_watermark)
    
    builder.position_at_end(check_watermark)
    wm_is_zero = builder.icmp_unsigned(
        '==', watermark_depth, ir.Constant(self.i64, 0))
    depth_ok = builder.icmp_unsigned('<', frame_depth, watermark_depth)
    should_scan = builder.or_(wm_is_zero, depth_ok)
    builder.cbranch(should_scan, scan_slots, next_frame)
    
    # Scan this frame's slots
    builder.position_at_end(scan_slots)
    
    # Get num_roots and handle_slots
    num_roots_ptr = builder.gep(curr_frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
    ], inbounds=True)
    num_roots = builder.load(num_roots_ptr)
    
    slots_ptr_ptr = builder.gep(curr_frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    slots = builder.load(slots_ptr_ptr)
    
    builder.branch(slot_loop)
    
    # Slot loop
    builder.position_at_end(slot_loop)
    slot_idx = builder.phi(self.i64, name="slot_idx")
    slot_idx.add_incoming(ir.Constant(self.i64, 0), scan_slots)
    
    # Check if done with slots
    slots_done = builder.icmp_unsigned('>=', slot_idx, num_roots)
    builder.cbranch(slots_done, next_frame, mark_handle)
    
    # Mark this handle
    builder.position_at_end(mark_handle)
    slot_ptr = builder.gep(slots, [slot_idx], inbounds=True)
    handle = builder.load(slot_ptr)
    
    # Skip null handles
    handle_is_null = builder.icmp_unsigned(
        '==', handle, ir.Constant(self.i64, 0))
    
    with builder.if_then(builder.not_(handle_is_null)):
        # Dereference handle and mark object
        obj_ptr = builder.call(self.gc_handle_deref, [handle])
        builder.call(self.gc_mark_object, [obj_ptr])
    
    builder.branch(next_slot)
    
    # Next slot
    builder.position_at_end(next_slot)
    next_idx = builder.add(slot_idx, ir.Constant(self.i64, 1))
    slot_idx.add_incoming(next_idx, next_slot)
    builder.branch(slot_loop)
    
    # Next frame
    builder.position_at_end(next_frame)
    parent_ptr = builder.gep(curr_frame, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
    ], inbounds=True)
    parent_frame = builder.load(parent_ptr)
    next_depth = builder.add(frame_depth, ir.Constant(self.i64, 1))
    curr_frame_raw.add_incoming(parent_frame, next_frame)
    frame_depth.add_incoming(next_depth, next_frame)
    builder.branch(frame_loop)
    
    # Next thread
    builder.position_at_end(next_thread)
    next_ptr = builder.gep(curr_thread, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    next_thread_i8 = builder.load(next_ptr)
    next_thread_typed = builder.bitcast(
        next_thread_i8, self.thread_entry_type.as_pointer())
    curr_thread.add_incoming(next_thread_typed, next_thread)
    builder.branch(thread_loop)
    
    # Done
    builder.position_at_end(done)
    builder.call(self.pthread_mutex_unlock, [mutex])
    builder.ret_void()
```

### 4.6 Update gc_collect

Update to use the watermark protocol:

```python
def _implement_gc_collect(self):
    """Run a garbage collection cycle with watermark protocol."""
    func = self.gc_collect
    
    entry = func.append_basic_block("entry")
    wait_loop = func.append_basic_block("wait_loop")
    check_thread = func.append_basic_block("check_thread")
    check_ack = func.append_basic_block("check_ack")
    next_thread = func.append_basic_block("next_thread")
    all_acked = func.append_basic_block("all_acked")
    do_collect = func.append_basic_block("do_collect")
    reset_loop = func.append_basic_block("reset_loop")
    reset_thread = func.append_basic_block("reset_thread")
    reset_next = func.append_basic_block("reset_next")
    done = func.append_basic_block("done")
    
    builder = ir.IRBuilder(entry)
    
    # Set gc_phase = 1 (WATERMARK) with release semantics
    builder.store_atomic(
        ir.Constant(self.i64, 1), self.gc_phase,
        ordering='release', align=8)
    
    # Increment cycle ID
    cycle = builder.load(self.gc_cycle_id)
    new_cycle = builder.add(cycle, ir.Constant(self.i64, 1))
    builder.store(new_cycle, self.gc_cycle_id)
    
    # Wait for all threads to acknowledge (with timeout/retry limit)
    # For simplicity, we'll do a bounded spin wait
    max_iters = ir.Constant(self.i64, 1000000)  # ~1M iterations
    builder.branch(wait_loop)
    
    # Wait loop - check all threads
    builder.position_at_end(wait_loop)
    iter_count = builder.phi(self.i64, name="iter_count")
    iter_count.add_incoming(ir.Constant(self.i64, 0), entry)
    
    # Check iteration limit
    limit_reached = builder.icmp_unsigned('>=', iter_count, max_iters)
    builder.cbranch(limit_reached, all_acked, check_thread)  # Proceed anyway on timeout
    
    # Check each thread
    builder.position_at_end(check_thread)
    first_thread = builder.load(self.gc_thread_registry)
    all_done = builder.alloca(self.i1)
    builder.store(ir.Constant(self.i1, 1), all_done)  # Assume all done
    builder.branch(check_ack)
    
    builder.position_at_end(check_ack)
    curr = builder.phi(self.thread_entry_type.as_pointer(), name="curr")
    curr.add_incoming(first_thread, check_thread)
    
    # If null, we've checked all
    curr_int = builder.ptrtoint(curr, self.i64)
    is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
    builder.cbranch(is_null, all_acked, next_thread)
    
    builder.position_at_end(next_thread)
    # Check watermark_active
    wm_active_ptr = builder.gep(curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    wm_active = builder.load_atomic(wm_active_ptr, ordering='acquire', align=8)
    not_acked = builder.icmp_unsigned('==', wm_active, ir.Constant(self.i64, 0))
    
    with builder.if_then(not_acked):
        builder.store(ir.Constant(self.i1, 0), all_done)
    
    # Move to next thread
    next_ptr = builder.gep(curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    next_i8 = builder.load(next_ptr)
    next_typed = builder.bitcast(next_i8, self.thread_entry_type.as_pointer())
    curr.add_incoming(next_typed, next_thread)
    builder.branch(check_ack)
    
    # All threads acknowledged (or timeout)
    builder.position_at_end(all_acked)
    all_done_val = builder.load(all_done)
    builder.cbranch(all_done_val, do_collect, wait_loop)  # Retry if not all done
    
    # Add iteration increment on retry path
    # (Need to restructure - simplified: just proceed after checking)
    
    # Do collection
    builder.position_at_end(do_collect)
    
    # Set gc_phase = 2 (MARKING)
    builder.store_atomic(
        ir.Constant(self.i64, 2), self.gc_phase,
        ordering='release', align=8)
    
    # Flip mark value
    mark_val = builder.load(self.gc_current_mark_value)
    new_mark = builder.xor(mark_val, ir.Constant(self.i64, 1))
    builder.store(new_mark, self.gc_current_mark_value)
    
    # Scan roots from all threads
    builder.call(self.gc_scan_roots, [])
    
    # Set gc_phase = 3 (SWEEPING)
    builder.store_atomic(
        ir.Constant(self.i64, 3), self.gc_phase,
        ordering='release', align=8)
    
    # Sweep
    builder.call(self.gc_sweep, [])
    
    # Reset all threads' watermark_active
    builder.branch(reset_loop)
    
    builder.position_at_end(reset_loop)
    first_reset = builder.load(self.gc_thread_registry)
    builder.branch(reset_thread)
    
    builder.position_at_end(reset_thread)
    reset_curr = builder.phi(self.thread_entry_type.as_pointer(), name="reset_curr")
    reset_curr.add_incoming(first_reset, reset_loop)
    
    reset_int = builder.ptrtoint(reset_curr, self.i64)
    reset_null = builder.icmp_unsigned('==', reset_int, ir.Constant(self.i64, 0))
    builder.cbranch(reset_null, done, reset_next)
    
    builder.position_at_end(reset_next)
    # Reset watermark_active = 0
    reset_wm_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), reset_wm_ptr)
    
    # Also reset watermark_depth = 0
    reset_depth_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
    ], inbounds=True)
    builder.store(ir.Constant(self.i64, 0), reset_depth_ptr)
    
    # Next thread
    reset_next_ptr = builder.gep(reset_curr, [
        ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
    ], inbounds=True)
    reset_next_i8 = builder.load(reset_next_ptr)
    reset_next_typed = builder.bitcast(
        reset_next_i8, self.thread_entry_type.as_pointer())
    reset_curr.add_incoming(reset_next_typed, reset_next)
    builder.branch(reset_thread)
    
    # Done
    builder.position_at_end(done)
    
    # Set gc_phase = 0 (IDLE)
    builder.store_atomic(
        ir.Constant(self.i64, 0), self.gc_phase,
        ordering='release', align=8)
    
    builder.ret_void()
```

---

## Part 5: Wire Up Implementations

### 5.1 Update generate_gc_runtime

Add calls to new implementation functions:

```python
def generate_gc_runtime(self):
    """Generate all GC runtime structures and functions"""
    self._create_types()
    self._create_globals()
    self._declare_functions()
    self._register_builtin_types()
    self._implement_gc_init()
    self._implement_gc_register_thread()      # NEW
    self._implement_gc_unregister_thread()    # NEW
    self._implement_gc_get_thread_entry()     # NEW
    self._implement_gc_push_frame()           # UPDATED
    self._implement_gc_pop_frame()            # UPDATED
    self._implement_gc_set_root()
    self._implement_gc_alloc()
    self._implement_gc_mark_hamt()
    self._implement_gc_mark_object()
    self._implement_gc_scan_roots()           # UPDATED
    self._implement_gc_sweep()
    self._implement_gc_collect()              # UPDATED
    self._implement_gc_safepoint()            # UPDATED
    # ... rest of existing implementations
```

---

## Part 6: Backward Compatibility

### 6.1 Deprecate Old Globals

The old globals `gc_frame_top` and `gc_frame_depth` are replaced by TLS variables. Keep them for any legacy code paths but mark as deprecated:

```python
# DEPRECATED: Use tls_frame_top instead
# Kept for backward compatibility during transition
self.gc_frame_top = ir.GlobalVariable(...)
```

### 6.2 Main Thread Initialization

The main thread must be registered before any allocations. This happens automatically in `gc_init()`. The main thread's TLS variables are initialized when `gc_register_thread()` is called.

---

## Testing Checklist

### Unit Tests
- [ ] Thread registration creates valid ThreadEntry
- [ ] Thread unregistration removes from list
- [ ] Double registration is no-op
- [ ] Unregister without register is no-op
- [ ] gc_get_thread_entry returns correct pointer
- [ ] TLS frame_top correctly tracks frames
- [ ] TLS frame_depth correctly tracks depth

### Integration Tests  
- [ ] All 185 existing tests pass
- [ ] gc_collect completes without error
- [ ] gc_scan_roots finds all roots
- [ ] Watermark protocol activates correctly

### Stress Tests (Future)
- [ ] Multiple threads register/unregister
- [ ] GC runs while threads are active
- [ ] No deadlocks under contention

---

## Success Criteria

1. All 185 existing tests pass without modification
2. Single-threaded behavior unchanged
3. Main thread correctly registered at startup
4. TLS variables work correctly
5. gc_scan_roots iterates registry
6. Watermark fields updated at safepoints
7. gc_collect uses watermark protocol
8. No memory leaks from ThreadEntry

---

## Notes

### llvmlite TLS Support

Verify llvmlite supports `thread_local` attribute:
```python
gv = ir.GlobalVariable(module, typ, name="tls_var")
gv.thread_local = 'localdynamic'  # or 'initialexec', 'localexec'
```

If not supported, fall back to pthread_key_* APIs.

### Memory Ordering

llvmlite supports atomic operations:
```python
builder.load_atomic(ptr, ordering='acquire', align=8)
builder.store_atomic(val, ptr, ordering='release', align=8)
```

Valid orderings: 'unordered', 'monotonic', 'acquire', 'release', 'acq_rel', 'seq_cst'

### PHI Node Complexity

The gc_scan_roots and gc_collect functions have complex control flow with multiple phi nodes. Test carefully to ensure all incoming edges are properly defined.
