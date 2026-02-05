# Coex Heap Management Manual

## Table of Contents

1. [Overview](#1-overview)
2. [Object Layout](#2-object-layout)
3. [Handle Table](#3-handle-table)
4. [Allocation](#4-allocation)
5. [TLABs (Thread-Local Allocation Buffers)](#5-tlabs-thread-local-allocation-buffers)
6. [Scope Arenas](#6-scope-arenas)
7. [Per-Thread State (ThreadEntry)](#7-per-thread-state-threadentry)
8. [Shadow Stack (Segmented)](#8-shadow-stack-segmented)
9. [Garbage Collection](#9-garbage-collection)
10. [GC Thread Architecture](#10-gc-thread-architecture)
11. [Diagnostics and Statistics](#11-diagnostics-and-statistics)
12. [Type System Integration](#12-type-system-integration)
13. [Constants Reference](#13-constants-reference)

---

## 1. Overview

Coex uses a **handle-based, mark-and-sweep garbage collector** with thread-local allocation. Every heap reference stored in program variables is an `i64` index into a global handle table, never a raw pointer. This indirection provides several properties:

- **Stability across GC**: handles remain valid even if the collector moves objects (future compaction support).
- **Concurrent safety**: the handle table is the single source of truth for object locations.
- **Pointer recovery**: given a raw pointer to an object, its handle can be recovered from the object header's `forward` field.

The allocator hierarchy has three tiers, ordered from fastest to slowest:

| Tier | Mechanism | Locking | GC-tracked | Lifetime |
|------|-----------|---------|------------|----------|
| Scope Arena | Bump pointer within TLAB | None | No | Function scope |
| TLAB | Bump pointer per thread | CAS on cursor | Yes | Until sweep |
| Global malloc | `malloc()` | Mutex | Yes | Until sweep |

---

## 2. Object Layout

### 2.1 Object Header

Every GC-tracked object is preceded by a 32-byte header. The user pointer returned by allocation points to the byte immediately after this header.

```
+------------------------------------------------+
|  Header (32 bytes)                             |
| +----------+----------+----------+----------+  |
| |  size    | type_id  |  flags   | forward  |  |
| |  i64     |  i64     |  i64     |  i64     |  |
| | offset 0 | offset 8 |offset 16 |offset 24 |  |
| +----------+----------+----------+----------+  |
+------------------------------------------------+
|  User data (variable length)                   |
|  <-- user_ptr points here                      |
+------------------------------------------------+
```

**Field descriptions:**

| Field | Offset | Description |
|-------|--------|-------------|
| `size` | 0 | User data size in bytes (does **not** include the 32-byte header). The GC uses this to compute element counts when scanning buffers: `element_count = size / element_size`. Storing the total allocation size would cause the GC to over-scan past the buffer. |
| `type_id` | 8 | Legacy type identifier (see Section 12). Determines how the GC traces child references during marking. |
| `flags` | 16 | Bit field controlling GC behavior (see below). |
| `forward` | 24 | Stores the object's handle index. Used by `gc_ptr_to_handle()` to recover the handle from a raw pointer. Reserved for future compaction forwarding. |

### 2.2 Flag Bits

| Bit | Constant | Value | Meaning |
|-----|----------|-------|---------|
| 0 | `FLAG_MARK_BIT` | `0x01` | Current mark state. Compared against `gc_current_mark_value` to determine liveness. |
| 1 | `FLAG_FORWARDED` | `0x02` | Object has been forwarded (reserved for future compaction). |
| 2 | `FLAG_PINNED` | `0x04` | Object cannot be moved (reserved for future use). |
| 3 | `FLAG_FINALIZER` | `0x08` | Object has a finalizer to run before collection (reserved). |
| 4 | `FLAG_TLAB` | `0x10` | Object was allocated from a TLAB. Must not be individually `free()`d; the entire TLAB is `munmap()`d when empty. |
| 5 | `FLAG_ARENA` | `0x20` | Object was arena-allocated. No handle, no GC tracking. Bulk-freed on scope exit. |

### 2.3 Birth-Marking

New objects are born with their mark bit set to the **current** `gc_current_mark_value`. This guarantees that a newly allocated object survives the current GC cycle without requiring explicit marking. The initial flags value is computed as:

```
flags = gc_current_mark_value | (is_tlab << 4)
```

---

## 3. Handle Table

### 3.1 Structure

The handle table is a flat array of `i8*` pointers, dynamically sized:

```
gc_handle_table:      i8**  (array of pointers)
gc_handle_table_size: i64   (current capacity, initially 1,048,576 = 1M entries)
gc_next_handle:       i64   (next bump-allocated handle, starts at 1)
```

Handle `0` is reserved as the null handle. Valid handles are indices `1` through `gc_next_handle - 1`.

### 3.2 Allocation

Handle allocation uses a two-tier strategy with thread-local pools:

**Fast path -- per-thread handle pool (lock-free):**
Each `ThreadEntry` maintains a pool of 512 pre-allocated handle indices:

```
handle_pool_start  (field 18): first handle index in pool
handle_pool_next   (field 19): next available handle to dispense
handle_pool_end    (field 20): one past the last handle in pool
```

`gc_handle_pool_alloc()` checks `pool_next < pool_end`. If true, it returns `pool_next` and increments it. No locking required -- purely thread-local.

**Slow path -- pool refill (mutex-protected):**
When the pool is empty, `gc_handle_pool_refill()` acquires `gc_mutex` and replenishes the pool:

1. **Drain the global free list first** (BUG-062 fix): Walk `gc_handle_free_list`, collecting up to 512 handles into a stack-allocated array. Each free-list entry stores the next free handle index in its table slot.
2. **If the free list provides fewer than 512**: bump-allocate the remainder from `gc_next_handle`. If `gc_next_handle` would exceed `gc_handle_table_size`, call `gc_handle_table_grow()` to double the table capacity via reallocation.
3. Update the thread's pool fields: `pool_start`, `pool_next`, `pool_end`.

### 3.3 Deallocation and MI-6 Deferred Reclamation

Handles are never freed immediately. Instead, the GC uses a two-cycle deferred scheme called **MI-6**:

1. **Cycle N (sweep)**: Unmarked handles are added to `gc_handle_retired_list` via `gc_handle_retire()`. The retired list is a LIFO chain stored in the handle table slots themselves (each slot stores the index of the next retired handle).

2. **Cycle N+1 (start)**: `gc_promote_retired_handles()` walks the retired list to find its tail, then links the entire chain onto the head of `gc_handle_free_list`. The retired list is then cleared.

3. **Cycle N+1+ (allocation)**: The promoted handles are now available for reuse via the free list.

This two-cycle delay ensures that any code holding a handle from the previous cycle cannot accidentally see the handle reused for a different object before it has a chance to observe the collection.

### 3.4 Operations

| Function | Signature | Description |
|----------|-----------|-------------|
| `gc_handle_deref` | `(i64 handle) -> i8*` | Returns `gc_handle_table[handle]`. Returns null for handle 0. |
| `gc_handle_store` | `(i64 handle, i8* ptr)` | Writes `gc_handle_table[handle] = ptr`. |
| `gc_ptr_to_handle` | `(i8* ptr) -> i64` | Reads the handle from the object header's `forward` field at `ptr - 8`. |
| `gc_handle_retire` | `(i64 handle)` | Pushes handle onto `gc_handle_retired_list`. |
| `gc_handle_table_grow` | `()` | Doubles `gc_handle_table_size`, reallocates the table, preserves existing entries. |

---

## 4. Allocation

### 4.1 Primary Allocator: `gc_alloc(user_size: i64, type_id: i32) -> i64`

This is the main allocation function. It returns a **handle** (i64), not a pointer.

**Algorithm:**

```
1. Compute total_size = user_size + HEADER_SIZE (32), aligned up to 8 bytes.

2. TLAB fast path (lock-free):
   a. Call gc_tlab_alloc(aligned_size).
   b. If non-NULL -> got memory from TLAB, set is_tlab = 1.
   c. If NULL -> TLAB is full.

3. TLAB refill + retry:
   a. Call gc_tlab_refill() to allocate a fresh 256 KB buffer.
   b. Retry gc_tlab_alloc(aligned_size).
   c. If still NULL -> fall through to malloc.

4. Malloc fallback (mutex-protected):
   a. Lock gc_mutex.
   b. malloc(aligned_size).
   c. Unlock gc_mutex.
   d. Set is_tlab = 0.

5. Initialize 32-byte header:
   - size = user_size (not total)
   - type_id = type_id (zero-extended to i64)
   - flags = gc_current_mark_value | (is_tlab << 4)  [birth-marking]
   - forward = 0 (will be set to handle below)

6. Zero user data with memset to prevent stale TLAB data from confusing the GC.

7. Allocate handle:
   a. Call gc_handle_pool_alloc() (lock-free).
   b. If 0 -> call gc_handle_pool_refill() (acquires mutex), retry.

8. Wire up handle:
   - gc_handle_store(handle, user_ptr)
   - Store handle in header's forward field.

9. Create allocation node (always via malloc, 32 bytes):
   - Fields: { next: i8*, handle: i64, size: i64, tlab_base: i8* }
   - If is_tlab: atomically increment TLAB header's live_count.

10. Add node to per-thread allocation list via gc_alloc_to_thread_list()
    (CAS-based prepend, lock-free).

11. Update statistics atomically (total_allocations, total_bytes, etc.).

12. Atomically increment gc_alloc_count (drives safepoint GC triggering).

13. Return handle.
```

### 4.2 Allocation Node

Each allocation creates a 32-byte tracking node:

```c
struct alloc_node {
    i8* next;        // offset 0:  next node in per-thread linked list
    i64 handle;      // offset 8:  handle index for the allocated object
    i64 size;        // offset 16: object size (user size, from header)
    i8* tlab_base;   // offset 24: base of the TLAB this object lives in (NULL if malloc)
};
```

These nodes are **always** `malloc()`d (never from TLAB) so the sweeper can safely `free()` them independently.

### 4.3 Adding to Per-Thread List: `gc_alloc_to_thread_list(node)`

Uses an atomic compare-and-swap (CAS) loop to prepend the node to the thread's `alloc_list` head (ThreadEntry field 9):

```
loop:
  expected = load alloc_list_head
  node->next = expected
  cmpxchg(alloc_list_head, expected, node)  [acq_rel / acquire]
  if success: break
  // On failure: expected was stale, retry with actual value
```

This is lock-free. Multiple threads can allocate and prepend concurrently. The sweeper atomically steals the entire list before processing.

### 4.4 Convenience Wrappers

| Function | Description |
|----------|-------------|
| `alloc_with_deref(size, type_id) -> i8*` | Calls `gc_alloc`, then `gc_handle_deref` to return the user pointer directly. |
| `alloc_arena_or_gc(size, type_id) -> i8*` | Tries arena allocation first; falls back to `gc_alloc` + deref if arena fails. |

---

## 5. TLABs (Thread-Local Allocation Buffers)

### 5.1 Structure

Each TLAB is a 256 KB (262,144 byte) region allocated via `mmap(MAP_PRIVATE | MAP_ANON)`. The first 16 bytes form a header:

```
+----------------------------------------------+
|  TLAB (256 KB via mmap)                      |
| +----------------+----------------+          |
| |   live_count   |   next_tlab    |          |
| |     i64        |     i8*        |          |
| |   offset 0     |   offset 8     |          |
| +----------------+----------------+          |
|                                              |
|  <-- tlab_cursor starts at offset 16         |
|  |                                           |
|  |  Object allocations grow upward           |
|  |  (bump pointer)                           |
|  |                                           |
|  <-- tlab_limit at base + 256KB              |
+----------------------------------------------+
```

| Field | Description |
|-------|-------------|
| `live_count` | Atomic counter of live objects in this TLAB. Incremented on allocation, decremented during sweep. When it reaches 0, the TLAB is fully dead and can be `munmap()`d. |
| `next_tlab` | Linked list pointer to the previous TLAB for this thread. Also reused to chain dead TLABs during sweep. |

### 5.2 Allocation: `gc_tlab_alloc(size) -> i8*`

Lock-free bump allocation using an atomic CAS loop:

```
loop:
  cursor = load tlab_cursor                   // from ThreadEntry field 7
  new_cursor = cursor + size
  if new_cursor > tlab_limit:                 // ThreadEntry field 8
    return NULL                               // TLAB exhausted
  cmpxchg(tlab_cursor, cursor, new_cursor)    // acq_rel semantics
  if success: return cursor                   // allocated memory at cursor
  // CAS failed (another thread allocated concurrently) -> retry
```

Returns NULL when the TLAB cannot satisfy the allocation, triggering refill or malloc fallback.

### 5.3 Refill: `gc_tlab_refill()`

Called when the current TLAB is full:

1. `mmap()` a new 256 KB buffer with `PROT_READ | PROT_WRITE` and `MAP_PRIVATE | MAP_ANON`.
2. Initialize the header: `live_count = 0`, `next_tlab = old_tlab_base`.
3. Update ThreadEntry fields:
   - `tlab_base` (field 6) -> new buffer start
   - `tlab_cursor` (field 7) -> new buffer + 16 (past header)
   - `tlab_limit` (field 8) -> new buffer + 256 KB

The old TLAB remains live (objects in it are still tracked via allocation nodes). It is linked via `next_tlab` for reference.

### 5.4 TLAB Lifecycle

```
mmap'd --> Active (receiving allocations)
              |
              | gc_tlab_refill() called
              v
         Retired (objects still live, linked via next_tlab)
              |
              | All objects swept (live_count reaches 0)
              v
         Dead --> Added to gc_dead_tlab_list during sweep
              |
              | End of sweep phase
              v
         munmap'd (memory returned to OS)
```

**BUG-065 fix**: When a TLAB is added to the dead list during sweep, the sweeper checks whether it's the thread's **current** TLAB. If so, it resets `tlab_base`, `tlab_cursor`, and `tlab_limit` to NULL in the ThreadEntry, preventing the next allocation from writing to unmapped memory.

---

## 6. Scope Arenas

### 6.1 Purpose

Arenas provide **zero-overhead** allocation for function-scoped temporaries. Objects allocated in an arena:
- Have **no** object header (no 32 bytes of overhead)
- Have **no** handle in the handle table
- Are **not** tracked in the allocation list
- Are **not** traced by the GC
- Are **bulk-freed** instantly when the function returns

Arenas are ideal for formula/task functions that create intermediate collections that don't escape the function.

### 6.2 How Arenas Relate to TLABs

Arenas are carved out of the current TLAB. An arena "push" saves the current TLAB cursor position, and a "pop" resets it back, effectively releasing all memory allocated between push and pop.

### 6.3 ThreadEntry Arena Fields

| Field | Index | Description |
|-------|-------|-------------|
| `arena_cursor` | 15 | Current bump pointer for arena allocations |
| `arena_start` | 16 | Start of current arena (saved cursor position) |
| `arena_parent_start` | 17 | Previous arena start, enabling 2-3 levels of nesting |

### 6.4 Operations

**`gc_arena_push()` -- Function entry:**
```
Save current tlab_cursor -> arena_start
Save previous arena_start -> arena_parent_start
Return arena_start (for later pop)
```

**`gc_arena_alloc(size) -> i8*` -- Bump allocation:**
```
if arena_cursor + size <= tlab_limit:
  ptr = arena_cursor
  arena_cursor += size
  tlab_cursor += size     // Keep TLAB cursor in sync
  return ptr
else:
  return NULL             // Arena can't satisfy; caller falls back to gc_alloc
```

**`gc_arena_pop(start_ptr)` -- Function exit:**
```
tlab_cursor = start_ptr   // Bulk-free everything allocated since push
arena_start = arena_parent_start
arena_parent_start = NULL
```

### 6.5 Promotion to Heap: `gc_promote_to_heap(ptr) -> i8*`

When a formula returns a value that was arena-allocated, it must escape to the GC heap. `gc_promote_to_heap` checks the object's `FLAG_ARENA` bit:

- If **not** arena-allocated: returns the pointer unchanged.
- If arena-allocated: reads `size` and `type_id` from the (arena) header, calls `gc_alloc(size, type_id)` to allocate on the GC heap, `memcpy`s the data, and returns the new pointer.

---

## 7. Per-Thread State (ThreadEntry)

Each thread that interacts with the GC has a `ThreadEntry` struct stored in pthread TLS (via `pthread_key_create` / `pthread_getspecific`). This struct contains all per-thread state:

```
ThreadEntry (21 fields, 168 bytes):

 Index  Offset  Type   Field                     Description
 -----  ------  -----  ------------------------  -----------------------------------------
   0       0    i64    thread_id                  pthread_self() identifier
   1       8    i8*    shadow_stack_head           (deprecated, use segments)
   2      16    i64    watermark_depth             Segment depth when GC watermark set
   3      24    i64    watermark_active            1 = acknowledged current GC cycle
   4      32    i64    stack_depth                 Current shadow stack depth
   5      40    i64    last_gc_cycle               Last GC cycle ID acknowledged
   6      48    i8*    tlab_base                   Start of current TLAB buffer
   7      56    i8*    tlab_cursor                 Current TLAB allocation position
   8      64    i8*    tlab_limit                  End of current TLAB buffer
   9      72    i8*    alloc_list                  Head of per-thread allocation list
  10      80    i64    tlab_epoch                  GC cycle when current TLAB was issued
  11      88    i8*    next                        Next ThreadEntry in global registry
  12      96    i8*    segment_base                First segment in chain (immutable)
  13     104    i8*    segment_current             Active segment for push/pop
  14     112    i64    slot_index                  Absolute slot watermark (total used)
  15     120    i8*    arena_cursor                Current arena bump pointer
  16     128    i8*    arena_start                 Start of current arena scope
  17     136    i8*    arena_parent_start          Parent arena start (nesting)
  18     144    i64    handle_pool_start           First handle in thread-local pool
  19     152    i64    handle_pool_next            Next available pool handle
  20     160    i64    handle_pool_end             One past last pool handle
```

### 7.1 Thread Registration

`gc_register_thread()` performs:

1. Allocate a `ThreadEntry` via `malloc`.
2. Set `thread_id = pthread_self()`.
3. Initialize the segment chain via `gc_segment_init()`.
4. Initialize the TLAB via `gc_tlab_init()` (mmap first 256 KB TLAB).
5. Allocate first batch of 512 handles for the thread-local pool.
6. Prepend to the `gc_thread_registry` linked list (mutex-protected).
7. Store the ThreadEntry pointer in pthread TLS via `pthread_setspecific`.

### 7.2 Thread Unregistration

`gc_unregister_thread()`:
- Removes from `gc_thread_registry`.
- Frees TLABs, segment chain, handle pool, and the ThreadEntry itself.

---

## 8. Shadow Stack (Segmented)

### 8.1 Purpose

The shadow stack provides cross-platform GC root tracking without platform-specific stack scanning. Each function that allocates GC-tracked objects "pushes" slots onto the shadow stack and registers its live handles there. The GC scans these slots during the mark phase.

### 8.2 Segment Structure

Each segment is a 4,096-byte (one page), page-aligned region allocated via `mmap`:

```
+--------------------------------------------+
|  StackSegment (4096 bytes)                 |
| +----------+----------+------------------+ |
| |  prev    |  next    |  slot_count      | |
| |  i8*     |  i8*     |  i64             | |
| | offset 0 | offset 8 | offset 16        | |
| +----------+----------+------------------+ |
| +----------------------------------------+ |
| |  slots[0..508]  (509 x i64 = 4072 B)  | |
| |  offset 24                             | |
| +----------------------------------------+ |
+--------------------------------------------+
```

- **509 slots** per segment: `(4096 - 24) / 8 = 509`
- Segments form a doubly-linked chain via `prev` and `next`.
- The `next` pointer is used for segment reuse (no deallocation on pop).

### 8.3 Slot Addressing

Slots are addressed by an **absolute slot index** that spans the entire chain:

```
Segment 0:  slots [0 .. 508]
Segment 1:  slots [509 .. 1017]
Segment 2:  slots [1018 .. 1526]
...
```

Given an absolute slot `s`:
- `segment_index = s / 509`
- `slot_in_segment = s % 509`

To find the segment, walk forward `segment_index` hops from `segment_base`.

### 8.4 Operations

**`gc_segment_push(num_roots) -> i64 start_slot`** -- Called at function entry:

1. Get `segment_current` and `slot_index` from ThreadEntry.
2. If the current segment doesn't have room for `num_roots` slots:
   - Allocate a new segment.
   - Link: `new.prev = current`, `current.next = new`.
   - Update `segment_current` to the new segment.
3. Zero the new slots (prevents the GC from seeing stale handles during a race).
4. Increment `segment.slot_count` and `ThreadEntry.slot_index`.
5. Return the starting absolute slot index.

**`gc_segment_set_root(slot, handle)`** -- Store a handle at a slot:

1. Compute `segment_index` and `slot_in_segment` from the absolute `slot`.
2. Walk the segment chain from `segment_base` forward `segment_index` hops.
3. Store `handle` at `slots[slot_in_segment]`.

**`gc_segment_pop(start_slot)`** -- Called at function exit:

1. Restore `ThreadEntry.slot_index = start_slot`.
2. The segment chain remains intact for reuse (no deallocation).

### 8.5 Example: Function Lifecycle

```coex
func foo() -> int
    x = [1, 2, 3]     // gc_alloc returns handle H1
    y = "hello"        // gc_alloc returns handle H2
    ...
~
```

Generated code:
```
start_slot = gc_segment_push(2)          // Reserve 2 root slots
H1 = gc_alloc(list_size, TYPE_LIST)
gc_segment_set_root(start_slot + 0, H1)  // Root slot 0 = list handle
H2 = gc_alloc(str_size, TYPE_STRING)
gc_segment_set_root(start_slot + 1, H2)  // Root slot 1 = string handle
...
gc_segment_pop(start_slot)               // Release root slots
```

---

## 9. Garbage Collection

### 9.1 Trigger Mechanism

GC is triggered via **safepoints**. `gc_safepoint()` is injected at function entry points and checks:

```
if gc_alloc_count >= GC_THRESHOLD (100,000):
    // Atomically exchange gc_alloc_count to 0 (claim trigger)
    // Only one thread sees the high value
    Signal GC thread -> wait for completion
```

The safepoint also handles the **watermark protocol** (Section 9.3).

### 9.2 Collection Phases

`gc_collect()` orchestrates a full collection cycle:

```
Phase 0: Guard
  - Check gc_enabled flag.
  - Atomically CAS gc_in_progress from 0 to 1.
  - If CAS fails (another thread is collecting), return immediately.

Phase 1: WATERMARK (gc_phase = 1)
  - Increment gc_cycle_id.
  - Signal all mutator threads to reach a safe point.
  - gc_wait_for_watermarks() spins until all threads have acknowledged.

Phase 2: MARKING (gc_phase = 2)
  - Promote retired handles from previous cycle -> free list (MI-6).
  - Flip gc_current_mark_value (XOR 1) -- mark inversion.
  - Reset the mark worklist.
  - gc_scan_roots(): walk every registered thread's segment chain,
    loading each slot handle and calling gc_mark_object().
  - gc_mark_drain(): process all handles on the mark worklist.

Phase 3: SWEEPING (gc_phase = 3)
  - gc_sweep() -> gc_sweep_thread_lists(): for each registered thread:
    a. Atomically steal the thread's alloc_list (CAS exchange with NULL).
    b. Walk the stolen list:
       - If marked: add to survivors list, increment live_count.
       - If unmarked: retire handle, decrement TLAB live_count (if TLAB),
         free memory (malloc objects) or defer (TLAB objects), free alloc node.
    c. Atomically prepend survivors back to the thread's list (CAS loop).
  - Free all dead TLABs (gc_dead_tlab_list) via munmap.

Phase 4: CLEANUP
  - Reset watermark_active for all threads.
  - Set gc_phase = 0 (IDLE).
  - Update statistics (collections_completed, objects_swept, bytes_reclaimed).
  - Set gc_in_progress = 0.
```

### 9.3 Watermark Protocol

The watermark protocol ensures all mutator threads are at a consistent state before GC scans roots.

**Collector side** (`gc_wait_for_watermarks`):
- Sets `gc_phase = 1`.
- Iterates the thread registry, waiting for each thread's `watermark_active` to become non-zero.
- Skips the calling thread (it's already safe since it's blocked in GC).

**Mutator side** (in `gc_safepoint`):
- When `gc_phase != 0`, checks `watermark_active`.
- If not yet acknowledged: sets `watermark_depth = stack_depth`, `watermark_active = 1`.
- Then **spins**, calling `sched_yield()`, until `gc_phase` returns to 0.
- This blocks the mutator from modifying its shadow stack during root scanning.

### 9.4 Mark Inversion

Instead of clearing all mark bits before each collection, Coex alternates the meaning of the mark bit:

```
Cycle 1: gc_current_mark_value = 1
  -> An object is "marked" if (flags & 0x01) == 1
  -> An object is "unmarked" if (flags & 0x01) == 0

Cycle 2: gc_current_mark_value = 0
  -> An object is "marked" if (flags & 0x01) == 0
  -> An object is "unmarked" if (flags & 0x01) == 1
```

The flip happens at the start of the mark phase via `gc_current_mark_value ^= 1`. Since new objects are birth-marked with the current value, and the mark phase sets objects to the new current value, unmarked objects from the previous cycle naturally have the "wrong" bit.

### 9.5 Iterative Marking with Worklist

Marking uses a worklist (circular buffer) rather than recursion, preventing stack overflow on deep object graphs:

```
gc_mark_worklist:      i64*   (circular buffer of handle indices)
gc_mark_worklist_head: i64    (push position)
gc_mark_worklist_tail: i64    (pop position)
```

**`gc_mark_object(handle)`:**

1. Check handle != 0 (null).
2. Dereference handle -> pointer. Validate pointer >= 0x10000 (guard against free-list indices).
3. Read header flags. If mark bit matches `gc_current_mark_value`, already marked -> return.
4. Set mark bit to `gc_current_mark_value`.
5. Read `type_id` from header.
6. Based on type_id, push child handles to the worklist:

| Type | Children to push |
|------|-----------------|
| `TYPE_LIST` | `root_handle` (field 0), `tail_handle` (field 3) |
| `TYPE_MAP` | HAMT root pointer (calls `gc_mark_hamt`) |
| `TYPE_SET` | HAMT root pointer (calls `gc_mark_hamt`) |
| `TYPE_ARRAY` | data buffer handle |
| `TYPE_STRING` | owner handle (for slice views sharing a parent buffer) |
| `TYPE_CHANNEL` | buffer handle |
| `TYPE_PV_NODE` | All child node handles (up to 32 per node) |
| `TYPE_LIST_TAIL` | Each TaggedValue element: if `type_id >= TYPE_HEAP_BASE`, push value as handle |
| `TYPE_JSON_STRING/ARRAY/OBJECT` | Contained handle |
| User types (>= 23) | Walk `gc_type_offsets_table[type_id]`: array of byte offsets to handle fields, terminated by -1 |

**`gc_mark_drain()`:**
Pops handles from the worklist one at a time and calls `gc_mark_object()` on each, which may push more handles. Continues until the worklist is empty.

### 9.6 Sweep Algorithm

The sweep phase (`gc_sweep_thread_lists`) is concurrent-safe through a "steal and return" pattern:

```
For each thread T in gc_thread_registry:
  1. STEAL: Atomically exchange T.alloc_list with NULL (CAS loop).
     Mutator threads can continue allocating to the now-empty list.

  2. PARTITION: Walk stolen list, splitting into:
     - Survivors (marked): append to survivors list.
     - Dead (unmarked): retire handle, free memory.

  3. RETURN: Atomically prepend survivors back to T.alloc_list.
     Uses "Link Before Publish" CAS pattern:
       a. Load old_head = T.alloc_list
       b. survivors_tail->next = old_head  (link BEFORE CAS)
       c. CAS(T.alloc_list, old_head, survivors_head)
       d. Retry if CAS fails (concurrent allocation appended)
```

**Memory reclamation for dead objects:**

| Object type | Action |
|-------------|--------|
| Non-TLAB (`FLAG_TLAB` not set) | `free(header_ptr)` immediately |
| TLAB (`FLAG_TLAB` set) | Atomically decrement TLAB's `live_count`. If it reaches 0, add TLAB to `gc_dead_tlab_list`. |
| All dead objects | Free the `alloc_node` via `free()`. Retire the handle via `gc_handle_retire()`. |

After processing all threads, the sweeper walks `gc_dead_tlab_list` and `munmap()`s each dead TLAB.

---

## 10. GC Thread Architecture

The GC runs on a **dedicated background thread** (`gc_thread_main`), not on mutator threads:

```
                    +-------------------+
                    |   GC Thread       |
                    |  (background)     |
                    |                   |
     +--------------| Wait on           |
     |              | gc_cond_start     |
     |              +--------+----------+
     |                       | gc_trigger_requested = 1
     |                       v
     |              +---------------------+
     |              |  gc_collect()       |
     |              |  (mark + sweep)     |
     |              +--------+------------+
     |                       |
     |                       v
     |              +---------------------+
     |              | Signal              |
     |              | gc_cond_done        |---> Unblock waiting mutators
     |              +--------+------------+
     |                       |
     +-----------------------+  (loop)
```

**Mutator triggers GC (in `gc_safepoint`):**
1. Atomically exchange `gc_alloc_count` to 0 (claim trigger).
2. Lock `gc_mutex`, set `gc_complete = 0`, set `gc_trigger_requested = 1`.
3. Signal `gc_cond_start` to wake GC thread.
4. Unlock `gc_mutex`.
5. Call `gc_wait_for_completion()` which waits on `gc_cond_done`.

**GC thread loop:**
1. Wait on `gc_cond_start` (holding `gc_mutex`).
2. On wakeup: check `gc_thread_running` (exit if 0), check `gc_trigger_requested`.
3. Clear trigger flag, unlock mutex, call `gc_collect()`.
4. Lock mutex, signal `gc_cond_done`, unlock, loop.

---

## 11. Diagnostics and Statistics

### 11.1 Statistics Structure (`gc_stats`)

A global struct with 19 i64 fields (152 bytes):

| Index | Field | Description |
|-------|-------|-------------|
| 0 | `total_allocations` | Cumulative allocation count |
| 1 | `total_bytes_allocated` | Cumulative bytes allocated |
| 2 | `allocations_since_last_gc` | Allocations since last collection (reset each cycle) |
| 3 | `bytes_since_last_gc` | Bytes since last collection (reset each cycle) |
| 4 | `collections_completed` | Number of GC cycles completed |
| 5 | `objects_marked_last_cycle` | Surviving objects from last sweep |
| 6 | `objects_swept_last_cycle` | Cumulative objects freed |
| 7 | `bytes_reclaimed_last_cycle` | Bytes freed in last cycle |
| 8-10 | Compaction metrics | Reserved for future compaction |
| 11-16 | Timing metrics (ns) | Watermark, trace, compact, sweep, total GC timing |
| 17-18 | Threading metrics | Block events and wait time |

### 11.2 Debug Counters

Atomic counters for internal debugging:

| Counter | Meaning |
|---------|---------|
| `gc_debug_list_adds` | Successful allocation list prepends |
| `gc_debug_list_skips` | Skipped (no thread entry found) |
| `gc_debug_sweep_threads` | Threads iterated during sweep |
| `gc_debug_sweep_nodes` | Allocation nodes examined during sweep |
| `gc_debug_sweep_empty` | Empty per-thread lists encountered |
| `gc_debug_sweep_marked` | Objects that survived (marked) |
| `gc_debug_sweep_unmarked` | Objects freed (unmarked) |
| `gc_debug_tlab_freed` | TLAB-allocated objects freed |
| `gc_debug_nontlab_freed` | Malloc-allocated objects freed |
| `gc_debug_tlabs_reclaimed` | TLABs munmap'd |

### 11.3 Diagnostic Builtins (Coex-callable)

| Function | Description |
|----------|-------------|
| `gc()` | Force an immediate GC cycle |
| `gc_dump_stats()` | Print allocation/collection statistics |
| `gc_dump_heap()` | Print all live objects with type, size, mark status |
| `gc_dump_roots()` | Print shadow stack root handles |
| `gc_validate_heap() -> int` | Check heap invariants, return error count |
| `gc_validate_handle_storage() -> int` | Verify stored values are handles (small ints) not pointers (large addrs) |
| `gc_fragmentation_report()` | Analyze heap fragmentation by size class |
| `gc_dump_handle_table()` | Print handle table state (allocated/free/retired) |
| `gc_dump_shadow_stacks()` | Print all segment chains and root handles |

### 11.4 Trace Levels

Set via `gc_set_trace_level(level)`:

| Level | Constant | Output |
|-------|----------|--------|
| 0 | `GC_TRACE_NONE` | No output |
| 1 | `GC_TRACE_PHASES` | Collection phase boundaries |
| 2 | `GC_TRACE_OPS` | Major operations (alloc, mark, sweep) |
| 3 | `GC_TRACE_DETAIL` | Individual object operations |
| 4 | `GC_TRACE_ALL` | Everything including pointer traversals |

---

## 12. Type System Integration

### 12.1 Tagged Values

All collection elements are stored as **TaggedValues**: `{ i64 type_id, i64 value }` (16 bytes). This makes values self-describing, allowing the GC to determine at runtime whether an element is a primitive (skip) or a heap reference (trace).

```
type_id < 64  -> Primitive (value is raw data, no GC handle)
type_id >= 64 -> Heap reference (value is a GC handle, needs marking)
```

### 12.2 Type ID Schemes

**Legacy type IDs** (used in object headers):

| ID | Type |
|----|------|
| 0 | Unknown |
| 1 | List |
| 2 | String |
| 3 | Map |
| 4 | Map Entry |
| 5 | Set |
| 6 | Set Entry |
| 7 | Channel |
| 8 | Array |
| 9 | List Tail (primitive elements) |
| 10 | PV Node |
| 11 | String Data |
| 12 | Channel Buffer |
| 13 | Array Data (primitive elements) |
| 14-20 | JSON variants |
| 21 | List Tail Ref (deprecated) |
| 22 | Array Data Ref (deprecated) |
| 23+ | User-defined types |

**TaggedValue type IDs** (used in collection elements):

| Range | Types |
|-------|-------|
| 0-9 | Primitives: Unknown, Int, Float, Bool, Byte, Char, JSON scalars |
| 64-73 | Heap: String, List, Map, Set, Array, Channel, JSON ref types, Tuple |
| 80-88 | Internal structural: String Data, List Tail, PV Node, HAMT nodes, etc. |
| 128+ | User-defined types |

### 12.3 User-Defined Type GC Tracing

For user-defined types (type_id >= 23), the GC uses `gc_type_offsets_table`: a global array of `i64*` indexed by type_id. Each entry points to an array of byte offsets within the object where handle fields are located, terminated by -1.

During registration via `register_type(type_name, size, ref_offsets)`, the compiler records which struct fields contain heap references. During `gc_mark_object()`, the marker walks this offset array and pushes each handle field to the worklist.

---

## 13. Constants Reference

| Constant | Value | Description |
|----------|-------|-------------|
| `HEADER_SIZE` | 32 | Object header size (bytes) |
| `MIN_BLOCK_SIZE` | 40 | Minimum allocation: header + padding |
| `TLAB_SIZE` | 262,144 | 256 KB per TLAB |
| `TLAB_HEADER_SIZE` | 16 | TLAB header (live_count + next_tlab) |
| `SEGMENT_SIZE` | 4,096 | Shadow stack segment (one page) |
| `SEGMENT_SLOTS` | 509 | Root slots per segment |
| `HANDLE_POOL_SIZE` | 512 | Handles per thread-local batch |
| `INITIAL_HANDLE_TABLE_SIZE` | 1,048,576 | 1M handles (8 MB initial) |
| `GC_THRESHOLD` | 100,000 | Allocations between GC triggers |
| `INITIAL_HEAP_SIZE` | 1,073,741,824 | 1 GB (informational) |
| `MAX_TYPES` | 256 | Maximum registered type descriptors |
| `TYPE_HEAP_BASE` | 64 | TaggedValue types >= this are heap refs |
| `TYPE_FIRST_USER` | 23 | First legacy type ID for user types |
| `TV_TYPE_FIRST_USER` | 128 | First TaggedValue type ID for user types |
