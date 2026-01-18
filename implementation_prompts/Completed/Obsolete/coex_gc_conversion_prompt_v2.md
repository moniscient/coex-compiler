# Coex Garbage Collector Conversion: Pointer-Based to Handle-Based

## Project Overview

Convert the Coex garbage collector from direct pointer-based references to a fully concurrent handle-based architecture. This transformation enables non-blocking compaction (future phase) and eliminates stop-the-world pauses for pointer fixup. All collection types (Map, Set, List, and json) will require modification to correctly work with handles.

### Current State

The existing GC in `coex_gc.py` uses direct pointers to heap objects:
- Shadow stack frames hold `i8**` (pointers to local variables containing raw `i8*` pointers)
- `gc_alloc(size, type_id)` returns `i8*` (raw pointer to object)
- Object access is direct pointer dereference
- Mark-sweep collection is synchronous
- Infrastructure exists for birth-marking and mark-bit inversion

**Removed Prior to Conversion:**
The following features have been removed to simplify the conversion:
- **Dormant watermark system**: Old watermark code has been removed; this prompt specifies the new watermark protocol from scratch
- **Channels**: Stub implementation removed; will be reimplemented with real concurrency after GC conversion
- **Select**: Stub implementation removed; will be reimplemented after GC conversion
- **Within**: Stub implementation removed; will be reimplemented after GC conversion

These features are explicitly **out of scope** for this conversion. Do not attempt to convert or preserve any remnants of them. They will be added back as new implementations once the concurrent GC is operational.

### Target State

A concurrent-ready collector where:
- Every heap reference is a handle (index into a global handle table)
- Shadow stack frames hold pointers to local variables containing handles (`i64` values)
- `gc_alloc(size, type_id)` returns `i64` (handle)
- Object access requires handle dereference through the table
- Multiple mutator threads supported with per-thread shadow stacks
- Single GC thread (initially) with patterns for future multi-GC scaling
- Automatic growth of both handle table and heap on exhaustion
- Comprehensive diagnostic tooling for heap inspection and statistics


### Threading Model

**Mutator Threads:** Multiple mutator threads are supported from the start. Each mutator has:
- Its own shadow stack (thread-local)
- Its own allocation buffer (thread-local, carved from global heap)
- Registration in the global thread registry

**GC Thread:** Single GC thread initially. The design uses lock-free patterns that will support multiple GC threads in future phases.

**Synchronization Model:**

See detailed "Synchronization Model" section below for complete specification of thread interactions.

---

## Core Invariants (MI-1 through MI-6)

These invariants are inviolable. All implementation decisions must preserve them.

### MI-1: Handle Exclusivity
Every heap object is referenced exclusively through handles. No raw pointers to heap objects exist in mutator code after allocation returns.

### MI-2: Complete Shadow Stack Liveness
Every live handle appears in exactly one shadow stack frame. "Appears" means a shadow stack slot points to a local variable (alloca) that holds the handle value. The compiler may load handles into registers for performance, but the memory-backed location must contain the current value before any GC-observable point (safepoint).

### MI-3: Frame Lifetime Discipline
Frames may not be popped while containing live handles. A handle is "live" if it may be used after the pop. The compiler enforces this by placing `gc_pop_frame` as the final operation before function return, with compiler barrier semantics to prevent reordering.

### MI-4: Shadow Stack Publication Ordering
Frames are published using release semantics after full initialization. The collector observes frames using acquire semantics. This yields a conservative snapshot without stop-the-world.

### MI-5: Handle Table Stability Across Relocation
When the compactor relocates an object (future phase), it atomically updates the handle table slot using release semantics. Both old and new locations remain valid until the next cycle.

### MI-6: Deferred Reclamation
Objects and handle slots may be reclaimed only after becoming unreachable and after at least one full collection cycle completes.

---

## Architecture Specification

### Handle Table Structure

```
Global handle table: growable array of i8* slots
- Index 0 is reserved (null handle)
- Each slot contains a physical address or NULL
- Initial size: 1,048,576 handles (1M)
- Growth: doubles on exhaustion
- Slots aligned to 64 bytes to prevent false sharing during compaction
```

**LLVM Globals:**
```llvm
@gc_handle_table = internal global i8** null          ; Pointer to handle array
@gc_handle_table_size = internal global i64 0         ; Current capacity
@gc_handle_free_list = internal global i64 0          ; Head of free list (0 = empty)
@gc_handle_next_alloc = internal global i64 1         ; Next slot if free list empty
@gc_handle_retired_list = internal global i64 0       ; Handles pending retirement
@gc_handle_growth_mutex = internal global i64 0       ; Mutex for table growth
```

**Initial Allocation (in gc_init):**
```c
// Allocate 1M handles initially (8MB for pointers + padding for alignment)
// With 64-byte alignment per slot for cache-line isolation: 64MB
gc_handle_table = aligned_alloc(64, INITIAL_HANDLES * 64);
gc_handle_table_size = INITIAL_HANDLES;
```

**Cache-Line Padding:**
Each handle slot occupies a full 64-byte cache line to prevent false sharing when multiple threads or the GC access adjacent slots. This trades memory for scalability.

```llvm
; Handle slot structure (64 bytes, cache-line aligned)
%HandleSlot = type { i8*, [56 x i8] }  ; 8-byte pointer + 56 bytes padding
```

**Alternative (memory-efficient):** Use unpadded slots initially, add padding when multi-GC compaction is implemented. For now, simple array with atomic access is acceptable since compaction is deferred.

### Handle Representation

- Handles are plain `i64` values at the LLVM level
- Handle value 0 represents null (no object)
- Valid handles are indices 1 to table_size-1
- The Coex type system distinguishes handle-typed values; LLVM sees only `i64`

### Handle Free List (Lock-Free)

```
Free list: lock-free stack using CAS
- Each free slot stores the index of the next free slot
- Push/pop use compare-and-swap on gc_handle_free_list head
- ABA problem avoided by deferred recycling (MI-6)
```

**Allocation Strategy:**
1. Try to pop from free list (CAS loop)
2. If free list empty, atomic increment of `gc_handle_next_alloc`
3. If `gc_handle_next_alloc >= gc_handle_table_size`, grow table and retry

**Deallocation Strategy:**
1. Freed handles enter the "retired" list during sweep
2. At end of GC cycle, retired list is atomically spliced to free list
3. This implements MI-6's deferred reclamation for handles

### Handle Table Growth

**Trigger:** When `gc_handle_next_alloc` exceeds `gc_handle_table_size` and free list is empty.

**Protocol:**
1. Acquire growth mutex (rare operation, mutex acceptable)
2. Double-check size (another thread may have grown)
3. Allocate new table with 2x capacity
4. Copy existing slots to new table
5. Update `gc_handle_table` pointer atomically
6. Update `gc_handle_table_size`
7. Free old table (after ensuring no concurrent readers—use RCU-like delay or epoch)
8. Release mutex

**Safety:** Mutators use acquire-load on `gc_handle_table` pointer before indexing. Growth updates the pointer with release semantics.

### Heap Structure

```
Global heap: growable memory region
- Initial size: 64MB
- Growth: doubles on exhaustion
- Allocation: bump-pointer within thread-local buffers
- Thread buffers carved from global heap (e.g., 1MB chunks)
```

**LLVM Globals:**
```llvm
@gc_heap_base = internal global i8* null              ; Heap start
@gc_heap_size = internal global i64 0                 ; Current heap capacity
@gc_heap_used = internal global i64 0                 ; Bytes allocated (approximate)
@gc_heap_growth_mutex = internal global i64 0         ; Mutex for heap growth
```

**Thread-Local Allocation Buffer:**
```llvm
; Per-thread allocation state (in thread-local storage)
@gc_tlab_base = thread_local global i8* null          ; Current buffer start
@gc_tlab_cursor = thread_local global i8* null        ; Next allocation point
@gc_tlab_end = thread_local global i8* null           ; Buffer end
```

**Allocation Fast Path:**
1. Check if `tlab_cursor + size <= tlab_end`
2. If yes: bump cursor, return old cursor (fast path, no atomics)
3. If no: call slow path to get new TLAB or grow heap

**Heap Growth Protocol:**
1. Acquire heap growth mutex
2. Double-check available space
3. Allocate new region with 2x current size (mmap or equivalent)
4. Update heap metadata
5. Release mutex
6. Retry allocation

### Handle Dereference

**Inline Code Pattern:**
```llvm
; Given %handle as i64
; Load current table pointer (acquire for growth safety)
%table = load atomic i8**, i8*** @gc_handle_table acquire, align 8
%slot_ptr = getelementptr i8*, i8** %table, i64 %handle
%object_ptr = load atomic i8*, i8** %slot_ptr acquire, align 8
```

On x86-64, acquire loads are free (strong memory model). On ARM64, this emits LDAR/LDAPR.

**Null Check:**
```llvm
%is_null = icmp eq i64 %handle, 0
br i1 %is_null, label %null_path, label %deref_path
```

### Object Header

The 32-byte header structure remains unchanged:
```
{ i64 size, i64 type_id, i64 flags, i64 forward }
```

- `size`: total allocation size including header
- `type_id`: type registry index for tracing
- `flags` bit 0: mark bit (compared against `gc_current_mark_value`)
- `flags` bit 1: forwarded flag (object has been relocated—future use)
- `forward`: handle value if forwarded, else 0 (future use for compaction)

Objects are birth-marked: allocated with mark bit set to `gc_current_mark_value`.

### Shadow Stack (Per-Thread)

**Structure:**
```llvm
%GCFrame = type { 
  i8*,     ; parent frame pointer
  i64,     ; num_roots (number of handle slots)
  i64**    ; handle_slots_array (pointers to local handle variables)
}
```

**Thread-Local Head:**
```llvm
@gc_frame_top = thread_local global i8* null
@gc_frame_depth = thread_local global i64 0
```

**Frame Publication Protocol:**
1. Allocate frame on machine stack (or in TLS buffer)
2. Initialize `num_roots` and `handle_slots_array` pointer
3. Initialize all pointed-to handle slots to 0 (null handle)
4. Set `parent` to current `gc_frame_top`
5. Store new frame as `gc_frame_top` with release semantics
6. Populate handle slots as allocations occur

**Critical Invariant (Register Publication):**
When a handle is created (e.g., return value from `gc_alloc`), it must be stored to its alloca slot before any potential safepoint. Safepoints include:
- Function calls (including `gc_alloc` itself for subsequent allocations)
- Loop back-edges (if safepoint polling is added)
- Explicit `gc_safepoint()` calls

The compiler must ensure:
```llvm
%handle = call i64 @coex_gc_alloc(i64 %size, i32 %type_id)
store i64 %handle, i64* %local_slot    ; MUST happen before next safepoint
; ... use %handle freely in registers ...
```

---

## Thread Registry

Multiple mutator threads require registration for GC coordination.

**GC Phase State (Global):**
```llvm
@gc_phase = internal global i64 0                     ; 0=idle, 1=marking, 2=sweeping
@gc_cycle_id = internal global i64 0                  ; Incremented each cycle
```

**Thread Entry Structure:**
```llvm
%ThreadEntry = type {
  i64,      ; thread_id
  i8*,      ; shadow_stack_head pointer (points to thread's gc_frame_top)
  i64,      ; watermark_depth (0 if no watermark)
  i64,      ; watermark_active (1 if collection in progress)
  i64,      ; stack_depth (current shadow stack depth)
  i8*,      ; tlab_base
  i8*,      ; tlab_cursor  
  i8*,      ; tlab_end
  i8*       ; next (linked list of threads)
}
```

**Global Registry:**
```llvm
@gc_thread_registry = internal global %ThreadEntry* null
@gc_thread_count = internal global i64 0
@gc_registry_mutex = internal global i64 0
```

**Thread Lifecycle:**
- `gc_register_thread()`: Called at thread start, adds entry to registry
- `gc_unregister_thread()`: Called at thread exit, removes entry
- Main thread registered during `gc_init()`

---

## Synchronization Model

This section specifies all thread interactions. The design goal is that **mutators never block waiting for GC** except during rare growth events.

### Mutator-to-Mutator Synchronization

| Operation | Mechanism | Blocking? |
|-----------|-----------|-----------|
| Handle table slot read | Acquire-load | No |
| Handle slot allocation (free list) | Lock-free CAS | No (spin on contention) |
| Handle slot allocation (bump) | Atomic increment | No |
| TLAB allocation | Thread-local bump | No (no synchronization) |
| TLAB refill | Atomic subtract from global pool | No |
| Shadow stack push/pop | Thread-local | No (no synchronization) |
| Handle table growth | Mutex | **Yes** (rare, all mutators) |
| Heap growth | Mutex | **Yes** (rare, all mutators) |

**Notes:**
- Most mutator operations require no inter-thread synchronization
- Growth events are rare (heap doubles each time) and brief
- During growth, mutators block on mutex; GC must also respect growth mutex

### Mutator-to-GC Synchronization

| Operation | Mechanism | Mutator Blocks? |
|-----------|-----------|-----------------|
| Watermark installation | GC sets flag; mutator reads at safepoint | No |
| Watermark acknowledgment | Mutator writes own ThreadEntry | No |
| Root scanning | GC reads shadow stack (acquire); mutator continues | No |
| Object marking | GC writes mark bits; mutator doesn't read them | No |
| Sweeping | GC frees unreachable objects; mutator can't see them | No |
| Handle retirement | GC adds to retired list; mutator uses free list | No |
| Free list promotion | GC splices retired→free between cycles | No |

**Critical invariant:** Mutators are never paused or blocked by GC tracing/sweeping operations.

**Watermark protocol detail:**
1. GC atomically sets `gc_phase = 1` (release)
2. Mutator, at its next safepoint, reads `gc_phase` (acquire)
3. If phase ≠ 0, mutator records `watermark_depth = current_stack_depth`
4. Mutator sets `watermark_active = 1` in its ThreadEntry
5. GC polls ThreadEntries or proceeds after timeout with conservative roots
6. Mutators continue executing throughout—no waiting

**Safepoints** occur at:
- Function calls (after gc_push_frame, before first allocation)
- Loop back-edges (optional, for long-running loops)
- Explicit gc_safepoint() calls

### GC-to-GC Synchronization (Future)

Currently single GC thread. When multiple GC threads are added:

| Operation | Mechanism |
|-----------|-----------|
| Work stealing (mark phase) | Lock-free work queue |
| Handle table slot updates (compaction) | Atomic CAS per slot |
| Statistics updates | Atomic add |
| Phase transitions | Barrier synchronization |

The current implementation uses patterns compatible with future multi-GC:
- Handle table updates use atomic operations (not required now, but ready)
- Statistics use atomic increments
- Retired list uses lock-free operations

### Memory Ordering Summary

| Operation | Ordering | Rationale |
|-----------|----------|-----------|
| Handle table pointer load | Acquire | See updated pointer after growth |
| Handle slot read (deref) | Acquire | See object data after address |
| Handle slot write (compaction) | Release | Object copy complete before visible |
| Shadow stack head write (push) | Release | Frame initialized before visible |
| Shadow stack head read (GC) | Acquire | See frame contents after head |
| `gc_phase` write (GC) | Release | Prior state consistent |
| `gc_phase` read (mutator) | Acquire | See phase change |
| `watermark_active` write | Release | Watermark depth visible |
| Free list CAS | Acq-Rel | Lock-free stack semantics |
| Mark bit write | Relaxed | Only GC writes; birth-mark prevents races |
| Statistics increment | Relaxed | Approximate counts acceptable |

### Blocking Summary

**Mutators block only when:**
1. Handle table exhausted AND growth in progress (mutex)
2. Heap exhausted AND growth in progress (mutex)

Both are rare (growth doubles capacity) and brief (memcpy/mmap time).

**Mutators never block for:**
- GC marking
- GC sweeping  
- Watermark installation
- Other mutator allocations (lock-free)

**GC blocks only when:**
1. Heap/handle table growth in progress (respects same mutex)

**GC never blocks for:**
- Mutator acknowledgment (timeout fallback)
- Mutator completion of any operation

---

## Function Signatures

### gc_init

```llvm
declare void @coex_gc_init()
```

**Implementation:**
1. Allocate initial handle table (1M slots)
2. Allocate initial heap (64MB)
3. Initialize all globals
4. Register main thread
5. Initialize diagnostic counters

### gc_alloc

**Current:**
```llvm
declare i8* @coex_gc_alloc(i64 %size, i32 %type_id)
```

**New:**
```llvm
declare i64 @coex_gc_alloc(i64 %size, i32 %type_id)
```

**Implementation:**
1. Fast path: bump TLAB cursor if space available
2. Slow path: get new TLAB or grow heap
3. Initialize object header (size, type_id, birth-mark)
4. Allocate handle slot (from free list or bump)
5. Store object address in handle slot (release semantics)
6. Return handle value

**On Exhaustion:**
- Handle table full: grow table (double size), retry
- Heap full: grow heap (double size), retry
- Both operations are mutex-protected and rare

### gc_push_frame

```llvm
declare i8* @coex_gc_push_frame(i64 %num_roots, i64** %handle_slots)
```

**Implementation:**
1. Allocate frame (on stack or from pool)
2. Initialize fields
3. Store as new frame top with release semantics
4. Increment `gc_frame_depth`
5. Return frame pointer (for passing to pop)

### gc_pop_frame

```llvm
declare void @coex_gc_pop_frame(i8* %frame) #gc_barrier
```

**Attributes (critical for safety):**
```llvm
attributes #gc_barrier = { nounwind memory(write) }
```

The `memory(write)` attribute prevents LLVM from reordering loads of handles to after the pop. This is essential for MI-3.

**Implementation:**
1. Verify frame matches current top (debug mode)
2. Load parent pointer
3. Store parent as new top with release semantics
4. Decrement `gc_frame_depth`
5. Check if at watermark depth and GC pending (trigger collection continuation)

### gc_set_root

```llvm
declare void @coex_gc_set_root(i64** %handle_slots, i64 %index, i64 %handle)
```

**Implementation:**
```llvm
%slot = getelementptr i64*, i64** %handle_slots, i64 %index
%local_ptr = load i64*, i64** %slot
store i64 %handle, i64* %local_ptr
```

### gc_handle_deref

```llvm
declare i8* @coex_gc_handle_deref(i64 %handle)
```

**Implementation:**
```llvm
define i8* @coex_gc_handle_deref(i64 %handle) #inline {
entry:
  %is_null = icmp eq i64 %handle, 0
  br i1 %is_null, label %ret_null, label %deref

ret_null:
  ret i8* null

deref:
  %table = load atomic i8**, i8*** @gc_handle_table acquire, align 8
  %slot_ptr = getelementptr i8*, i8** %table, i64 %handle
  %ptr = load atomic i8*, i8** %slot_ptr acquire, align 8
  ret i8* %ptr
}

attributes #inline = { alwaysinline }
```

**Usage:** Inlined at every heap access site.

### gc_mark_object

**New Signature:**
```llvm
declare void @coex_gc_mark_object(i64 %handle)
```

**Implementation:**
1. Null check (handle == 0)
2. Dereference handle to get object pointer
3. Read mark bit from header flags
4. If already marked with current mark value, return (avoid re-tracing)
5. Set mark bit to current mark value
6. Read type_id from header
7. Look up reference field offsets in type registry
8. For each reference field: load handle, recursively call gc_mark_object

### gc_collect

```llvm
declare void @coex_gc_collect()
```

**Implementation (Single GC Thread):**
1. Set `gc_phase = 1` (marking)
2. Install watermarks (set flag, wait for acknowledgment or timeout)
3. Flip `gc_current_mark_value` (0↔1)
4. For each registered thread:
   - Traverse shadow stack up to watermark depth
   - For each frame, for each handle slot: call gc_mark_object
5. Set `gc_phase = 2` (sweeping)
6. Traverse allocation list:
   - If object's mark bit ≠ current mark value: reclaim
   - Add handle to retired list
7. Splice retired list to free list (deferred from previous cycle)
8. Promote current retired list for next cycle
9. Set `gc_phase = 0` (idle)
10. Update statistics

### Thread Management

```llvm
declare void @coex_gc_register_thread()
declare void @coex_gc_unregister_thread()
declare %ThreadEntry* @coex_gc_get_current_thread()
```

### Handle Table Growth

```llvm
declare void @coex_gc_grow_handle_table()
```

**Implementation:**
1. Acquire `gc_handle_growth_mutex`
2. Check if growth still needed (another thread may have grown)
3. new_size = current_size * 2
4. Allocate new table
5. Copy existing entries
6. Store new table pointer with release semantics
7. Update size
8. Schedule old table for deferred free (epoch-based or delay)
9. Release mutex

### Heap Growth

```llvm
declare void @coex_gc_grow_heap()
```

**Implementation:**
1. Acquire `gc_heap_growth_mutex`
2. Check if growth still needed
3. new_size = current_size * 2
4. mmap new region (or realloc if contiguous)
5. Update heap metadata
6. Release mutex

---

## Diagnostic Tooling

Comprehensive diagnostics are essential for debugging and performance tuning.

### Statistics Structure

```llvm
%GCStats = type {
  ; Allocation metrics
  i64,    ; total_allocations
  i64,    ; total_bytes_allocated
  i64,    ; total_handles_allocated
  
  ; Collection metrics  
  i64,    ; collections_completed
  i64,    ; objects_marked_last_cycle
  i64,    ; objects_swept_last_cycle
  i64,    ; bytes_reclaimed_last_cycle
  i64,    ; handles_retired_last_cycle
  i64,    ; handles_recycled_last_cycle
  
  ; Growth events
  i64,    ; handle_table_growths
  i64,    ; heap_growths
  
  ; Current state
  i64,    ; current_heap_size
  i64,    ; current_heap_used
  i64,    ; current_handle_table_size
  i64,    ; current_handles_in_use
  i64,    ; current_handles_free
  
  ; Fragmentation metrics
  i64,    ; largest_free_block
  i64,    ; total_free_blocks
  i64,    ; fragmentation_ratio_percent (free_blocks / largest_possible)
  
  ; Timing (nanoseconds)
  i64,    ; last_gc_duration_ns
  i64,    ; last_mark_duration_ns
  i64,    ; last_sweep_duration_ns
  i64,    ; total_gc_time_ns
  
  ; Thread metrics
  i64,    ; registered_thread_count
  i64,    ; max_shadow_stack_depth_seen
}

@gc_stats = internal global %GCStats zeroinitializer
```

### Diagnostic Functions

#### gc_dump_stats
```llvm
declare void @coex_gc_dump_stats()
```
Prints all statistics to stderr in human-readable format.

#### gc_dump_heap
```llvm  
declare void @coex_gc_dump_heap(i32 %verbosity)
```
**Verbosity levels:**
- 0: Summary only (size, used, free blocks)
- 1: List all live objects (handle, type, size)
- 2: Full dump including object contents (hex)

**Output format:**
```
=== HEAP DUMP ===
Heap size: 67108864 bytes (64 MB)
Heap used: 12345678 bytes (11.77 MB)
Free blocks: 42
Largest free: 8388608 bytes

Live objects (1234 total):
  Handle 1: type=List, size=48, addr=0x7f1234567890
  Handle 2: type=String, size=72, addr=0x7f12345678c0
  ...
```

#### gc_dump_handle_table
```llvm
declare void @coex_gc_dump_handle_table(i32 %verbosity)
```
**Verbosity levels:**
- 0: Summary (size, in-use, free, retired)
- 1: List all in-use handles with object addresses
- 2: Full table dump including free list structure

**Output format:**
```
=== HANDLE TABLE ===
Table size: 1048576 slots
Handles in use: 1234
Handles free: 1047341
Handles retired: 15
Next bump alloc: 1250

In-use handles:
  [1] -> 0x7f1234567890 (List)
  [2] -> 0x7f12345678c0 (String)
  ...

Free list head: 1251
Free list: 1251 -> 1252 -> 1253 -> ... (1047341 entries)
```

#### gc_dump_shadow_stacks
```llvm
declare void @coex_gc_dump_shadow_stacks()
```
Dumps shadow stack state for all registered threads.

**Output format:**
```
=== SHADOW STACKS ===
Registered threads: 4

Thread 0 (main):
  Stack depth: 5
  Watermark: 3 (active)
  Frame 5: 2 handles [h=1234, h=5678]
  Frame 4: 1 handles [h=9012]
  Frame 3: 3 handles [h=3456, h=0, h=7890]  <- watermark
  Frame 2: 0 handles
  Frame 1: 1 handles [h=1111]

Thread 1:
  Stack depth: 2
  Watermark: none
  ...
```

#### gc_dump_object
```llvm
declare void @coex_gc_dump_object(i64 %handle)
```
Detailed dump of a single object.

**Output format:**
```
=== OBJECT DUMP ===
Handle: 1234
Address: 0x7f1234567890
Type: UserType (id=15)
Size: 96 bytes
Mark bit: 1 (matches current)
Forwarded: no

Header:
  size: 96
  type_id: 15
  flags: 0x01
  forward: 0

Fields:
  offset 0: i64 = 42
  offset 8: handle = 5678 -> String "hello"
  offset 16: handle = 0 (null)
  offset 24: f64 = 3.14159
```

#### gc_validate_heap
```llvm
declare i32 @coex_gc_validate_heap()
```
Validates heap integrity. Returns 0 if valid, error code otherwise.

**Checks performed:**
1. All handle table entries point to valid heap addresses or null
2. All object headers have valid type_ids
3. All reference fields contain valid handles or 0
4. Free list is well-formed (no cycles, all entries in valid range)
5. No overlapping allocations
6. Shadow stack frames properly linked

**Output on error:**
```
=== HEAP VALIDATION FAILED ===
Error: Handle 1234 points to address 0x7f1234567890 outside heap bounds
Error: Object at 0x7f2345678900 has invalid type_id 999
Validation found 2 errors
```

#### gc_fragmentation_report
```llvm
declare void @coex_gc_fragmentation_report()
```
Detailed fragmentation analysis for future compaction tuning.

**Output format:**
```
=== FRAGMENTATION REPORT ===
Heap size: 67108864 bytes
Allocated: 12345678 bytes (18.4%)
Free: 54763186 bytes (81.6%)

Free block distribution:
  < 64 bytes:     125 blocks (0.1% of free space)
  64-256 bytes:   342 blocks (0.8% of free space)
  256-1KB:        89 blocks (2.1% of free space)
  1KB-4KB:        23 blocks (4.5% of free space)
  4KB-16KB:       8 blocks (12.3% of free space)
  16KB-64KB:      3 blocks (15.2% of free space)
  > 64KB:         2 blocks (65.0% of free space)

Fragmentation index: 0.23 (0=perfect, 1=fully fragmented)
Largest allocation possible: 8388608 bytes

Recommendation: Fragmentation is low, compaction not needed
```

### Trace Levels

```llvm
@gc_trace_level = internal global i64 0

; Levels:
; 0 = none
; 1 = collection phases (start/end)
; 2 = major operations (alloc, mark, sweep)
; 3 = detailed (individual object operations)
; 4 = verbose (every handle dereference, etc.)
```

```llvm
declare void @coex_gc_set_trace_level(i64 %level)
```

**Trace output examples:**

Level 1:
```
[GC] Collection #42 starting (heap 45% full)
[GC] Mark phase: 1234 objects marked
[GC] Sweep phase: 567 objects reclaimed (4.5 MB)
[GC] Collection #42 complete in 12.3 ms
```

Level 2:
```
[GC] alloc: handle=1234, type=String, size=72
[GC] mark: handle=1234 (already marked)
[GC] sweep: handle=5678 reclaimed (List, 48 bytes)
```

Level 3:
```
[GC] alloc: handle=1234, type=String, size=72, addr=0x7f1234567890
[GC] handle_table: slot 1234 <- 0x7f1234567890
[GC] mark: tracing handle=1234, type=String
[GC] mark: field at offset 8: child handle=5678
[GC] mark: handle=5678 marked (was unmarked)
```

---

## Codegen Changes (codegen.py)

### Type System Changes

**Reference fields in user types:**
```python
def _get_llvm_type_for_field(self, field_type):
    if self._is_heap_type(field_type):
        return self.i64  # Handle, not pointer
    else:
        return self._get_llvm_type(field_type)
```

**Function signatures with heap parameters:**
```python
def _get_param_type(self, param_type):
    if self._is_heap_type(param_type):
        return self.i64  # Handle
    else:
        return self._get_llvm_type(param_type)
```

### Local Variable Allocation

**Pattern for heap object locals:**
```python
# Allocate local variable for handle (i64)
local_handle = builder.alloca(self.i64, name=f"{name}_handle")
builder.store(ir.Constant(self.i64, 0), local_handle)  # Initialize to null

# Later, when allocating:
handle = builder.call(self.gc.gc_alloc, [size, type_id])
builder.store(handle, local_handle)  # MUST happen before next safepoint
```

### Shadow Stack Setup

**Function prologue pattern:**
```python
def _setup_gc_frame(self, builder, handle_locals):
    """
    handle_locals: list of alloca'd i64* for each handle in this function
    """
    num_roots = len(handle_locals)
    
    # Allocate array of pointers to handle locals
    slots_array_type = ir.ArrayType(self.i64.as_pointer(), num_roots)
    slots_array = builder.alloca(slots_array_type, name="gc_slots")
    
    # Initialize each slot to point to corresponding local
    for i, local in enumerate(handle_locals):
        slot = builder.gep(slots_array, 
                          [ir.Constant(self.i32, 0), ir.Constant(self.i32, i)])
        builder.store(local, slot)
    
    # Push frame
    slots_ptr = builder.bitcast(slots_array, self.i64.as_pointer().as_pointer())
    frame = builder.call(self.gc.gc_push_frame, 
                        [ir.Constant(self.i64, num_roots), slots_ptr])
    return frame
```

**Function epilogue pattern:**
```python
def _teardown_gc_frame(self, builder, frame):
    """Must be the last thing before return"""
    builder.call(self.gc.gc_pop_frame, [frame])
```

### Field Access

**Reading a handle field:**
```python
def _load_handle_field(self, builder, obj_handle, field_offset):
    # Dereference object handle
    obj_ptr = self._emit_handle_deref(builder, obj_handle)
    # GEP to field
    field_ptr = builder.gep(obj_ptr, [ir.Constant(self.i64, field_offset)])
    field_ptr = builder.bitcast(field_ptr, self.i64.as_pointer())
    # Load handle value from field
    return builder.load(field_ptr)

def _emit_handle_deref(self, builder, handle):
    """Inline handle dereference"""
    # Null check
    is_null = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
    
    with builder.if_else(is_null) as (then, otherwise):
        with then:
            # Could trap or return sentinel
            builder.unreachable()
        with otherwise:
            table = builder.load(self.gc.gc_handle_table, ordering='acquire')
            slot_ptr = builder.gep(table, [handle])
            obj_ptr = builder.load(slot_ptr, ordering='acquire')
    
    return obj_ptr  # Needs phi node in practice
```

### Writing a Handle Field

**Storing a handle into an object field:**
```python
def _store_handle_field(self, builder, obj_handle, field_offset, value_handle):
    obj_ptr = self._emit_handle_deref(builder, obj_handle)
    field_ptr = builder.gep(obj_ptr, [ir.Constant(self.i64, field_offset)])
    field_ptr = builder.bitcast(field_ptr, self.i64.as_pointer())
    builder.store(value_handle, field_ptr)
```

---

## Built-in Collection Types

### List

**New Structure:**
```
{ i64 length, i64 capacity, i64 tail_handle }
```

- `tail_handle`: handle to the data buffer object
- Data buffer contains array of `i64` handles (for reference elements) or values

### Map / Set (HAMT)

**Node Structure:**
```
{ i64 bitmap, i64[N] children }
```

- `children` array contains handles to child nodes or entry objects
- Entry objects contain key/value handles

**Marking:** Traverse bitmap, mark each non-zero child handle recursively.

### String

**New Structure:**
```
{ i64 length, i64 hash, i64 data_handle }
```

- `data_handle`: handle to character data buffer
- Data buffer is not traced (contains bytes, not handles)

### Array

**New Structure:**
```
{ i64 length, i64 data_handle }
```

- `data_handle`: handle to element data buffer
- For reference arrays: data buffer contains handles
- For primitive arrays: data buffer contains values (not traced)

### Channel (Out of Scope)

Channels have been removed prior to this conversion. They will be reimplemented with proper concurrency support after the GC conversion is complete. Do not implement channel support in this phase.

---

## Implementation Phases

### Phase 1: Infrastructure
1. Add handle table globals and growth mechanism
2. Add heap growth mechanism  
3. Implement `gc_handle_alloc` with free list
4. Implement `gc_handle_deref` 
5. Implement `gc_handle_retire`
6. Add retired list and end-of-cycle promotion
7. Update `gc_init` for initial allocation

### Phase 2: Thread Support
1. Implement thread registry
2. Add TLS for per-thread state (shadow stack, TLAB)
3. Implement `gc_register_thread` / `gc_unregister_thread`
4. Update `gc_init` to register main thread

### Phase 3: Allocation Path
1. Modify `gc_alloc` to return handle
2. Implement TLAB allocation fast path
3. Implement TLAB refill slow path
4. Handle exhaustion with growth
5. Update all call sites in codegen

### Phase 4: Shadow Stack
1. Update frame structure for handle slots
2. Update `gc_push_frame` signature and implementation
3. Update `gc_pop_frame` with barrier attributes
4. Update `gc_set_root`
5. Update function prologue/epilogue codegen

### Phase 5: Field Storage
1. Change reference fields in user types from `i8*` to `i64`
2. Update `_get_llvm_type` for reference field types
3. Update field access codegen patterns
4. Update constructor codegen

### Phase 6: Collection Cycle
1. Implement watermark installation (async, flag-based)
2. Update `gc_scan_roots` for handle-based slots
3. Update `gc_mark_object` for handle input
4. Update child tracing for handle fields
5. Update `gc_sweep` with handle retirement
6. Implement retired→free list promotion

### Phase 7: Built-in Collections
1. Update List structure and operations
2. Update Map/Set HAMT structure and operations
3. Update String structure and operations
4. Update Array structure and operations
5. Update Channel structure and operations
6. Update marking for each collection type

### Phase 8: Diagnostic Tooling
1. Implement statistics collection throughout
2. Implement `gc_dump_stats`
3. Implement `gc_dump_heap`
4. Implement `gc_dump_handle_table`
5. Implement `gc_dump_shadow_stacks`
6. Implement `gc_dump_object`
7. Implement `gc_validate_heap`
8. Implement `gc_fragmentation_report`
9. Implement trace level control

### Phase 9: Testing
1. Verify all existing tests pass
2. Add handle-specific unit tests
3. Add multi-threaded allocation tests
4. Add growth trigger tests (handle table and heap)
5. Add stress tests (millions of objects)
6. Add diagnostic output verification tests

### Phase 10 (Future): Compaction
- Deferred to future work
- Current implementation grows heap instead of compacting
- Diagnostic tooling provides fragmentation data for future decisions

---

## Testing Strategy

### Unit Tests

1. **Handle allocation/deallocation**
   - Allocate handles, verify unique indices
   - Free handles, verify they enter retired list
   - After GC cycle, verify retired→free promotion
   - Verify recycled handles work correctly

2. **Handle table growth**
   - Exhaust initial table
   - Verify growth triggers
   - Verify all existing handles remain valid
   - Verify new allocations use expanded table

3. **Heap growth**
   - Exhaust initial heap
   - Verify growth triggers
   - Verify existing objects remain accessible
   - Verify new allocations succeed

4. **Multi-thread registration**
   - Register multiple threads
   - Verify each has independent shadow stack
   - Verify GC sees all threads' roots
   - Unregister threads, verify cleanup

### Integration Tests

1. **Object graph traversal**
   - Create deep object graphs
   - Trigger GC, verify all reachable objects survive
   - Verify unreachable objects collected

2. **Collection types**
   - Create Lists/Maps/Sets with object elements
   - Verify element handles traced correctly
   - Verify collection operations work with handles

3. **Cross-thread references**
   - Thread A creates object, passes handle to Thread B
   - Trigger GC from either thread
   - Verify object survives if reachable from either

### Stress Tests

1. **High allocation rate**
   - Allocate millions of small objects
   - Verify handle table growth works
   - Verify GC keeps up with allocation

2. **Deep recursion**
   - Create very deep shadow stacks
   - Verify root scanning handles depth
   - Verify frame pop correctness

3. **Long-running**
   - Run for extended period with allocation/GC cycles
   - Verify no handle leaks
   - Verify no memory leaks
   - Monitor fragmentation

### Diagnostic Tests

1. **Dump output format**
   - Verify all dump functions produce valid output
   - Verify output parseable for tooling

2. **Validation**
   - Intentionally corrupt state (debug builds)
   - Verify `gc_validate_heap` detects corruption

---

## Performance Targets (Reference)

Based on similar systems:

- **Handle dereference:** 4-5 cycles (L1 cache hit)
- **Allocation (fast path):** ~20 cycles (TLAB bump)
- **Allocation (slow path):** ~1000 cycles (TLAB refill)
- **GC mark rate:** ~50M objects/second
- **Memory overhead:** Handle table ~8MB per 1M objects (before padding)

These are reference points, not hard requirements for initial implementation.

---

## Files to Modify

| File | Changes |
|------|---------|
| `coex_gc.py` | Handle table, growth, threading, diagnostics, all GC functions |
| `codegen.py` | All heap object handling, field access, function signatures |

---

## Success Criteria

1. **Correctness:** All existing tests pass without modification to test source
2. **Threading:** Multiple mutator threads work correctly
3. **Growth:** Handle table and heap grow automatically on exhaustion
4. **Diagnostics:** All dump functions work and produce useful output
5. **Validation:** `gc_validate_heap` passes on correct heaps, catches errors
6. **Performance:** No more than 2x regression on allocation-heavy benchmarks (acceptable for handle indirection overhead)

---

## Non-Goals (This Phase)

1. **Compaction:** Deferred. Grow heap instead.
2. **Multiple GC threads:** Single GC thread. Patterns in place for future.
3. **NUMA optimization:** Simple global structures. Future optimization.
4. **Generational collection:** All objects in single generation.
5. **Channels:** Removed prior to conversion. Will be reimplemented with real concurrency.
6. **Select statement:** Removed prior to conversion. Will be reimplemented.
7. **Within statement:** Removed prior to conversion. Will be reimplemented.

## Removed Code (Do Not Preserve)

The following code has been intentionally removed from the codebase prior to this conversion. If any remnants are encountered, they should be deleted rather than converted:

- Any existing watermark implementation (replaced by new protocol in this spec)
- Channel type definitions and operations
- Select statement codegen
- Within statement codegen
- Any dual-heap or async GC code from previous experiments

The conversion should result in a clean implementation matching this specification, not an adaptation of prior attempts.
