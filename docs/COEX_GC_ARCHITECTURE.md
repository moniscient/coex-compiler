# The Coex Garbage Collector: A Handle-Based Concurrent Mark-Sweep Implementation

## Abstract

The Coex garbage collector is a handle-based, concurrent mark-sweep collector designed for a language with strict value semantics and first-class concurrency primitives. This document describes its architecture, key algorithms, and design decisions that enable efficient memory management in a multi-threaded environment without stop-the-world pointer fixup.

## 1. Design Philosophy

The Coex GC was designed around several core constraints:

1. **Value Semantics**: Coex prohibits aliasing—every binding owns its value exclusively. This simplifies root tracing but requires careful handling of copy-on-write data structures.

2. **First-Class Concurrency**: Tasks (lightweight threads) are core language primitives, requiring thread-safe allocation and collection.

3. **No Stop-the-World Pointer Fixup**: To minimize pause times, the collector uses handles (integer indices) instead of raw pointers, allowing objects to be relocated without updating all references.

4. **Portability**: The implementation avoids platform-specific stack scanning by using an explicit shadow stack.

## 2. Core Architecture

### 2.1 Handle Table

The central abstraction is the **handle table**—a global array mapping 64-bit integer handles to object pointers:

```
gc_handle_table: i8**      // Array of object pointers
gc_handle_table_size: i64  // Current capacity (initially 1M handles)
gc_next_handle: i64        // Bump allocator for fresh handles
gc_handle_free_list: i64   // LIFO free list head (0 = empty)
gc_handle_retired_list: i64 // MI-6 deferred reclamation list
```

**Handle 0 is reserved as null.** All heap references throughout the system are `i64` handle indices rather than raw pointers. To access an object:

```c
ptr = gc_handle_deref(handle)  // Returns gc_handle_table[handle]
```

To recover a handle from a pointer, each object header stores its handle:

```c
handle = gc_ptr_to_handle(ptr)  // Reads header.forward field
```

### 2.2 Object Header

Every allocated object is preceded by a 32-byte header:

```
struct ObjectHeader {
    i64 size;      // Offset 0:  Total allocation size (including header)
    i64 type_id;   // Offset 8:  Type descriptor for tracing (i64, not i32)
    i64 flags;     // Offset 16: Mark bit, TLAB flag, arena flag, etc.
    i64 forward;   // Offset 24: Handle index (for ptr->handle recovery)
}
```

**Flag bits:**
| Bit | Constant | Description |
|-----|----------|-------------|
| 0 | `FLAG_MARK_BIT` (0x01) | Mark bit (compared against `gc_current_mark_value`) |
| 1 | `FLAG_FORWARDED` (0x02) | Object has been forwarded (for future compaction) |
| 2 | `FLAG_PINNED` (0x04) | Object is pinned/not movable (future use) |
| 3 | `FLAG_FINALIZER` (0x08) | Object has finalizer (future use) |
| 4 | `FLAG_TLAB` (0x10) | Allocated from thread-local buffer |
| 5 | `FLAG_ARENA` (0x20) | Arena-allocated (no handle, bulk-freed) |

### 2.3 Thread Registry

Each thread is registered with the GC via a `ThreadEntry` structure (168 bytes, 21 fields):

```
struct ThreadEntry {
    // Core fields (offset 0-40)
    i64  thread_id;           // Field 0,  Offset 0:   Platform thread identifier
    i8*  shadow_stack_head;   // Field 1,  Offset 8:   Per-thread shadow stack
    i64  watermark_depth;     // Field 2,  Offset 16:  Stack depth when watermark set
    i64  watermark_active;    // Field 3,  Offset 24:  Acknowledged current GC cycle
    i64  stack_depth;         // Field 4,  Offset 32:  Current shadow stack depth
    i64  last_gc_cycle;       // Field 5,  Offset 40:  Last acknowledged cycle

    // TLAB fields (offset 48-88)
    i8*  tlab_base;           // Field 6,  Offset 48:  TLAB start pointer
    i8*  tlab_cursor;         // Field 7,  Offset 56:  Current allocation pointer
    i8*  tlab_limit;          // Field 8,  Offset 64:  TLAB end pointer
    i8*  alloc_list;          // Field 9,  Offset 72:  Per-thread allocation list head
    i64  tlab_epoch;          // Field 10, Offset 80:  GC epoch when TLAB issued
    i8*  next;                // Field 11, Offset 88:  Next ThreadEntry in registry

    // Segmented shadow stack (offset 96-112)
    i8*  segment_base;        // Field 12, Offset 96:  First segment (never changes)
    i8*  segment_current;     // Field 13, Offset 104: Active segment pointer
    i64  slot_index;          // Field 14, Offset 112: Absolute slot position = watermark

    // Arena fields (offset 120-136)
    i8*  arena_cursor;        // Field 15, Offset 120: Current arena allocation pointer
    i8*  arena_start;         // Field 16, Offset 128: Start of current arena
    i8*  arena_parent_start;  // Field 17, Offset 136: Parent arena (for nesting)

    // Handle pool (offset 144-160)
    i64  handle_pool_start;   // Field 18, Offset 144: First handle in pool
    i64  handle_pool_next;    // Field 19, Offset 152: Next available handle
    i64  handle_pool_end;     // Field 20, Offset 160: End of handle pool
}
```

Threads are linked into a global registry protected by `gc_registry_mutex`. Thread-local storage uses pthread TLS (`pthread_getspecific`/`pthread_setspecific`) because llvmlite's LLVM TLS attribute is silently ignored.

## 3. Allocation

### 3.1 Fast Path: TLAB + Handle Pool

Allocation is designed for minimal contention:

1. **TLAB Allocation** (lock-free): Each thread has a 256KB Thread-Local Allocation Buffer. Allocation is a simple bump:
   ```c
   if (tlab_cursor + size <= tlab_limit) {
       ptr = tlab_cursor;
       tlab_cursor += aligned_size;
       return ptr;
   }
   ```

2. **Handle Pool Allocation** (lock-free): Each thread maintains a pool of 512 pre-allocated handle indices:
   ```c
   if (handle_pool_next < handle_pool_end) {
       handle = handle_pool_next++;
       return handle;
   }
   ```

3. **Per-Thread Allocation List** (lock-free via CAS): Allocation nodes track all objects for sweeping. Each thread has its own list, eliminating contention:
   ```c
   do {
       expected = thread->alloc_list;
       node->next = expected;
   } while (!atomic_cmpxchg(&thread->alloc_list, expected, node));
   ```

### 3.2 Slow Path

When TLAB is exhausted, `gc_tlab_refill` allocates a new 256KB buffer. When the handle pool is empty, `gc_handle_pool_refill` acquires the global mutex and reserves 512 new handles in batch.

### 3.3 Birth-Marking

Newly allocated objects are **born marked** with the current mark value:

```c
flags = gc_current_mark_value | (is_tlab ? FLAG_TLAB : 0);
```

This ensures objects allocated during collection survive the current cycle without requiring synchronization between allocator and marker.

## 4. Root Tracking: Segmented Shadow Stack

### 4.1 Motivation

Platform-specific stack scanning is unreliable across architectures. Instead, each function explicitly registers its heap roots in a **shadow stack**—a compiler-managed data structure tracking all live handles.

### 4.2 Segment Structure

The shadow stack is organized into 4KB page-aligned segments:

```
struct StackSegment {
    i8* prev;                // Offset 0:  Previous segment (toward base)
    i8* next;                // Offset 8:  Next segment (for reuse)
    i64 slot_count;          // Offset 16: Slots in use (for debugging)
    i64 slots[509];          // Offset 24: Handle slots array (509 x 8 = 4072 bytes)
}
// Total: 8 + 8 + 8 + 4072 = 4096 bytes (page-aligned)
// Slot count derived: (4096 - 24) / 8 = 509
```

### 4.3 Operations

**Push (function entry):**
```c
start_slot = gc_segment_push(num_roots);
// Reserves num_roots slots, may allocate new segment
// Returns starting slot index (watermark for this frame)
```

**Set Root:**
```c
gc_segment_set_root(start_slot + i, handle);
// Stores handle at absolute slot position
```

**Pop (function exit):**
```c
gc_segment_pop(start_slot);
// Restores slot_index to start_slot value
// Segments remain allocated (Segment Stability Invariant)
```

The **Segment Stability Invariant** ensures segments are never deallocated during execution—only at thread exit. This allows the GC to safely scan segments without locking.

## 5. Collection Algorithm

### 5.1 Collection Phases

```
GC Phase Transitions (gc_phase values):
  0 (IDLE) -> 1 (WATERMARK) -> 2 (MARKING) -> 3 (SWEEPING) -> 0 (IDLE)
```

| Phase | Value | Description |
|-------|-------|-------------|
| IDLE | 0 | Normal operation, no GC in progress |
| WATERMARK | 1 | Signal threads to acknowledge watermark |
| MARKING | 2 | Scan roots and mark live objects |
| SWEEPING | 3 | Free unmarked objects |

### 5.2 Watermark Protocol

Before marking begins, all mutator threads must **acknowledge** the GC cycle:

1. GC sets `gc_phase = 1` (WATERMARK) and increments `gc_cycle_id`
2. `gc_wait_for_watermarks()` spins until all threads set `watermark_active = 1`
   - **Timeout**: Maximum 10,000 iterations (~10ms at 1us per yield)
   - If timeout exceeded, proceeds anyway to prevent deadlock
   - Skips the calling thread to avoid self-deadlock
3. Mutator threads check `gc_phase` at safepoints (function entry) and acknowledge:
   ```c
   if (gc_phase != 0 && !watermark_active) {
       watermark_depth = stack_depth;  // Freeze current stack depth
       watermark_active = 1;
       // Wait for GC to complete (spin on gc_phase == 0)
   }
   ```

This ensures no thread modifies its shadow stack during root scanning.

### 5.3 Mark Inversion

Instead of clearing mark bits between cycles, the GC **inverts the mark value**:

```c
// At start of marking:
gc_current_mark_value ^= 1;  // Flip 0<->1
```

An object is considered **live** if `(header.flags & 1) == gc_current_mark_value`. This eliminates a separate clearing phase and enables birth-marking: new objects are born with the *old* mark value, but since marking uses the *new* value, they won't appear "already marked."

### 5.4 Mark Phase

The mark phase uses an **iterative FIFO worklist** to avoid stack overflow on deep object graphs:

```c
void gc_scan_roots() {
    for each thread in registry:
        for slot in thread.segment_base..thread.slot_index:
            handle = slots[slot];
            if (handle != 0)
                gc_mark_object(handle);
    gc_mark_drain();  // Process worklist
}

void gc_mark_object(handle) {
    ptr = gc_handle_deref(handle);
    header = ptr - HEADER_SIZE;
    if ((header.flags & 1) == gc_current_mark_value)
        return;  // Already marked
    header.flags = (header.flags & ~1) | gc_current_mark_value;
    // Push children to worklist (type-specific)
    for each child_handle in object:
        gc_mark_push(child_handle);
}

void gc_mark_drain() {
    while ((handle = gc_mark_pop()) != 0)
        gc_mark_object(handle);
}
```

**Worklist structure (FIFO queue):**
```
gc_mark_worklist: i64*     // Array of handles
gc_mark_worklist_head: i64 // Write position (push here)
gc_mark_worklist_tail: i64 // Read position (pop here)
gc_mark_worklist_capacity: i64
```
- `gc_mark_push`: stores at `[head]`, increments head
- `gc_mark_pop`: reads from `[tail]`, increments tail
- Empty when `tail >= head`
- Initial capacity: 64K entries (512KB), doubles when full

The FIFO order provides better cache locality during marking.

### 5.5 Type-Specific Tracing

Each built-in type has specialized marking logic:

| Type | Tracing Strategy |
|------|------------------|
| List | Mark `root` (persistent vector tree) and `tail` (flat buffer) |
| String/Array | Mark `owner` (shared buffer for slice views) |
| Map/Set | `gc_mark_hamt()` recursively marks HAMT tree nodes with pointer tagging |
| PVNode | Iterate 32 children slots, mark non-null |
| JSON | Check tag byte; mark value if string/array/object |
| User Types | Lookup offset table, mark each pointer field |

### 5.6 Sweep Phase (Lock-Free)

Sweeping uses atomic operations to allow concurrent allocation:

```c
void gc_sweep_thread_lists() {
    for each thread in registry:
        // Atomically steal thread's allocation list (CAS loop)
        do {
            expected = thread->alloc_list;
        } while (!CAS(&thread->alloc_list, expected, NULL));
        stolen = expected;

        survivors_head = survivors_tail = NULL;
        for node in stolen:
            handle = node->handle;
            ptr = gc_handle_deref(handle);
            header = ptr - HEADER_SIZE;

            if ((header.flags & 1) == gc_current_mark_value):
                // Live: add to survivors (tail append)
                append_to_survivors(node);
            else:
                // Dead: free object and retire handle
                if (!(header.flags & FLAG_TLAB))
                    free(header);
                free(node);
                gc_handle_retire(handle);  // MI-6

        // "Link Before Publish" CAS pattern to prepend survivors
        if (survivors_head != NULL):
            do {
                old_head = thread->alloc_list;
                survivors_tail->next = old_head;  // Link BEFORE publish
            } while (!CAS(&thread->alloc_list, old_head, survivors_head));
}
```

The **"Link Before Publish"** pattern ensures the entire survivor chain is valid before it becomes visible, avoiding the "Disconnected Tail" race where concurrent traversals see a truncated list.

### 5.7 MI-6 Deferred Reclamation

Freed handles don't immediately become available. Instead:

1. **Cycle N**: Handle is swept -> added to `gc_handle_retired_list`
2. **Cycle N+1 start**: `gc_promote_retired_handles()` moves retired handles to `gc_handle_free_list`
3. **Cycle N+1**: Handle can be reused

This **one-cycle delay** prevents use-after-free when a concurrent thread holds a stale handle. The retired list uses the same LIFO structure as the free list: each retired slot stores the next retired handle index.

```c
void gc_promote_retired_handles() {
    if (retired_list == 0) return;  // Empty

    // Walk retired list to find tail
    tail = retired_list;
    while (table[tail] != 0)
        tail = table[tail];

    // Link tail to current free list head
    table[tail] = free_list;
    free_list = retired_list;
    retired_list = 0;
}
```

## 6. Safepoints

Safepoints serve two purposes:

1. **Watermark Acknowledgment**: Check `gc_phase` and acknowledge if collection is starting
2. **GC Triggering**: If `gc_alloc_count >= GC_THRESHOLD` (100,000), atomically claim the trigger and call `gc_collect()`

```c
void gc_safepoint() {
    if (gc_phase != 0 && !thread.watermark_active) {
        // Acknowledge watermark, wait for GC to complete
    }

    if (gc_enabled && gc_alloc_count >= GC_THRESHOLD) {
        if (atomic_exchange(&gc_alloc_count, 0) >= GC_THRESHOLD)
            gc_collect();
    }
}
```

Safepoints are inserted at every function entry after the shadow stack frame is pushed.

## 7. Arena Allocation (Formula Optimization)

For pure `formula` functions, temporary allocations can use **arena allocation**:

- Arena objects have headers but no handle (`FLAG_ARENA` set)
- Not tracked in allocation lists
- Bulk-freed when arena scope ends via `gc_arena_pop`
- If a value escapes the formula, `gc_promote_to_heap` copies it to the GC heap

### 7.1 Arena Operations

**gc_arena_push** (enter formula scope):
```c
i8* gc_arena_push() {
    old_start = thread->arena_start;
    thread->arena_parent_start = old_start;  // Save for nesting
    // Allocate new arena from TLAB
    thread->arena_start = thread->tlab_cursor;
    thread->arena_cursor = thread->arena_start;
    return old_start;  // Return for later pop
}
```

**gc_arena_pop** (exit formula scope):
```c
void gc_arena_pop(i8* saved_start) {
    thread->tlab_cursor = thread->arena_start;  // Bulk free!
    thread->arena_start = thread->arena_parent_start;
    thread->arena_cursor = thread->arena_parent_start;
    thread->arena_parent_start = NULL;
}
```

**gc_promote_to_heap** (escape hatch):
```c
i8* gc_promote_to_heap(i8* ptr) {
    if (ptr == NULL) return NULL;
    header = ptr - HEADER_SIZE;
    if (!(header->flags & FLAG_ARENA))
        return ptr;  // Already heap-allocated

    // Copy to GC heap
    new_handle = gc_alloc(header->size, header->type_id);
    new_ptr = gc_handle_deref(new_handle);
    memcpy(new_ptr, ptr, header->size);
    return new_ptr;
}
```

## 8. Diagnostics

The GC provides extensive debugging facilities:

| Function | Description |
|----------|-------------|
| `gc()` | Force collection cycle |
| `gc_dump_stats()` | Print allocation/collection statistics |
| `gc_dump_heap()` | List all live objects with type/size/mark |
| `gc_dump_roots()` | Print shadow stack contents |
| `gc_dump_handle_table()` | Show allocated/free/retired handles |
| `gc_dump_shadow_stacks()` | Print all frames and their handles |
| `gc_validate_heap()` | Check heap integrity, return error count |
| `gc_fragmentation_report()` | Analyze heap fragmentation by size class |

## 9. Statistics Structure

```c
struct GCStats {
    // Allocation metrics (offset 0-24)
    i64 total_allocations;           // Offset 0
    i64 total_bytes_allocated;       // Offset 8
    i64 allocations_since_last_gc;   // Offset 16
    i64 bytes_since_last_gc;         // Offset 24

    // Collection metrics (offset 32-56)
    i64 collections_completed;       // Offset 32
    i64 objects_marked_last_cycle;   // Offset 40
    i64 objects_swept_last_cycle;    // Offset 48
    i64 bytes_reclaimed_last_cycle;  // Offset 56

    // Compaction metrics (offset 64-80) - future use
    i64 compactions_completed;       // Offset 64
    i64 objects_moved_last_compact;  // Offset 72
    i64 bytes_moved_last_compact;    // Offset 80

    // Timing metrics in nanoseconds (offset 88-128)
    i64 last_watermark_install_ns;   // Offset 88
    i64 last_first_trace_ns;         // Offset 96
    i64 last_compact_ns;             // Offset 104
    i64 last_second_trace_ns;        // Offset 112
    i64 last_sweep_ns;               // Offset 120
    i64 last_total_gc_ns;            // Offset 128

    // Threading metrics (offset 136-144)
    i64 total_block_events;          // Offset 136
    i64 total_block_wait_ns;         // Offset 144
}
// Total: 152 bytes (19 fields)
```

## 10. Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `HEADER_SIZE` | 32 bytes | Object header before user data |
| `MIN_BLOCK_SIZE` | 40 bytes | Minimum allocation: header(32) + alignment |
| `MAX_TYPES` | 256 | Maximum registered type descriptors |
| `INITIAL_HANDLE_TABLE_SIZE` | 1,048,576 | 1M handles (8MB for pointers) |
| `GC_THRESHOLD` | 100,000 | Allocations before triggering GC |
| `INITIAL_HEAP_SIZE` | 1GB | Initial heap size (1024 x 1024 x 1024) |
| `TLAB_SIZE` | 262,144 | 256KB per-thread allocation buffer |
| `HANDLE_POOL_SIZE` | 512 | Handles per thread pool batch |
| `SEGMENT_SIZE` | 4,096 | Shadow stack segment size (page-aligned) |
| `SEGMENT_SLOTS` | 509 | Handle slots per segment: (4096-24)/8 |
| `MARK_WORKLIST_INITIAL_SIZE` | 65,536 | 64K initial mark worklist capacity |

## 11. Concurrency Safety

The implementation ensures thread safety through:

1. **Per-thread data structures**: TLAB, handle pool, allocation list
2. **Lock-free CAS loops**: Allocation list manipulation with retry
3. **"Link Before Publish"**: Survivor prepend avoids disconnected tail race
4. **Watermark protocol**: Mutators pause at safepoints during marking (with timeout)
5. **MI-6 deferred reclamation**: Handles safe for one full cycle after retirement
6. **Atomic alloc counter**: Single trigger per threshold crossing via atomic exchange
7. **Registry mutex**: Brief holds for thread registration/iteration only

## 12. Limitations and Future Work

1. **Single GC thread**: Mark/sweep is currently single-threaded; parallelization would require work-stealing queues
2. **No compaction**: Objects are never moved; fragmentation accumulates (FLAG_FORWARDED reserved for future)
3. **Global mark worklist**: Could be sharded per-GC-thread for parallelism
4. **No generational collection**: All objects are treated equally regardless of age
5. **Watermark timeout**: 10K iteration limit may cause unsafe collection if threads are blocked

## Conclusion

The Coex garbage collector combines handle-based indirection with concurrent mark-sweep to provide predictable memory management for a language with strict value semantics. The design prioritizes allocation throughput through lock-free fast paths while maintaining correctness through the watermark protocol and MI-6 deferred reclamation. The segmented shadow stack provides portable root tracking without relying on platform-specific stack scanning.

---

*Document verified against coex_gc.py implementation, January 2025.*
