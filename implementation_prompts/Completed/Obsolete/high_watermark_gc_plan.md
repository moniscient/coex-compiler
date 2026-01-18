# High Watermark GC Implementation Plan

## Overview

This plan implements the High Watermark Collection garbage collector for Coex, replacing the current A/B dual-heap system. The implementation prioritizes correctness and observability, with comprehensive debugging infrastructure built from the start.

**Target Platforms**: x86-64 Linux, ARM64 macOS, eventual Windows support
**Integer Convention**: All sizes, counts, indices, flags, and pointers use `i64` for cross-platform consistency
**Shadow Stack**: Keep existing manual shadow stack (already cross-platform); add thread-local storage for multi-threading

## Key Decisions

1. **Manual shadow stack**: Keep current implementation - already works on x86 and ARM, gives us full control
2. **Scope-local arenas**: Deferred entirely - premature optimization
3. **Compaction**: Deferred - prove core watermark collection first; allocate large initial heap
4. **Header size**: 32 bytes (all i64) - forward field included but unused until compaction phase

---

## Phase 0: Debugging Infrastructure Foundation

Build the debugging and tracing infrastructure first. Every subsequent phase will integrate with this foundation.

### 0.1 Tracing Framework

Create a runtime tracing system with configurable verbosity levels:

```c
// Trace levels
#define GC_TRACE_NONE    0
#define GC_TRACE_PHASES  1   // Collection phase boundaries
#define GC_TRACE_OPS     2   // Major operations (alloc, mark, sweep)
#define GC_TRACE_DETAIL  3   // Individual object operations
#define GC_TRACE_ALL     4   // Everything including pointer traversals

// Runtime configuration
i64 gc_trace_level = GC_TRACE_NONE;  // Set via environment or API
```

Output format:
```
[GC:PHASE] Watermark installation starting, thread_count=4
[GC:PHASE] Watermark installed on thread 0x7f... at depth 42
[GC:OP] gc_alloc: size=64, type=14, addr=0x...
[GC:DETAIL] mark_object: 0x... type=1 already_marked=false
```

### 0.2 Statistics Collection

Track metrics from day one:

```c
struct GCStats {
    // Allocation
    i64 total_allocations;
    i64 total_bytes_allocated;
    i64 allocations_since_last_gc;
    i64 bytes_since_last_gc;

    // Collection
    i64 collections_completed;
    i64 objects_marked_last_cycle;
    i64 objects_swept_last_cycle;
    i64 bytes_reclaimed_last_cycle;

    // Compaction
    i64 compactions_completed;
    i64 objects_moved_last_compact;
    i64 bytes_moved_last_compact;

    // Timing (nanoseconds)
    i64 last_watermark_install_ns;
    i64 last_first_trace_ns;
    i64 last_compact_ns;
    i64 last_second_trace_ns;
    i64 last_sweep_ns;
    i64 last_total_gc_ns;

    // Threading (for future)
    i64 total_block_events;
    i64 total_block_wait_ns;
};
```

### 0.3 Heap Inspector

Build utilities to examine heap state:

- `gc_dump_heap()` - Print all live objects with type, size, mark status
- `gc_dump_roots()` - Print all roots from shadow stack
- `gc_dump_object(ptr)` - Detailed dump of single object and its references
- `gc_validate_heap()` - Check invariants (no dangling pointers, valid headers)
- `gc_dump_stats()` - Print current GC statistics

### 0.4 Assertion Infrastructure

Aggressive invariant checking (enabled in debug builds):

```c
// Header validity
assert(header->size >= HEADER_SIZE);
assert(header->type_id < next_type_id);
assert((header->flags & ~VALID_FLAGS_MASK) == 0);

// Shadow stack consistency
assert(frame->num_roots >= 0);
for (i64 i = 0; i < frame->num_roots; i++) {
    if (frame->roots[i] != NULL) {
        assert(is_valid_heap_pointer(frame->roots[i]));
    }
}

// Watermark consistency
assert(gc_frame_depth >= 0);
if (watermark_active) {
    assert(watermark <= gc_frame_depth);
}
```

### Tests for Phase 0

- Unit test: Trace output formatting
- Unit test: Statistics increment/read
- Unit test: Heap dump with known objects
- Unit test: Assertion triggers on invalid header
- Integration test: Stats accuracy across allocation/collection cycle

---

## Phase 1: New Object Header

Replace the 16-byte header with 32-byte i64-only header.

### 1.1 Header Structure

```llvm
%ObjectHeader = type {
    i64,    ; size (total allocation including header)
    i64,    ; type_id
    i64,    ; flags (mark, forward, pinned, finalizer bits)
    i64     ; forward pointer (0 or address of new location)
}
```

Constants:
```python
HEADER_SIZE = 32
FLAG_MARK_BIT = 0x01
FLAG_FORWARDED = 0x02
FLAG_PINNED = 0x04
FLAG_FINALIZER = 0x08
```

### 1.2 Birth-Marking

All objects are born marked (critical for high watermark correctness):

```python
def gc_alloc(size, type_id):
    total = align8(size + HEADER_SIZE)
    ptr = malloc(total)
    header = ptr
    header.size = total
    header.type_id = type_id
    header.flags = FLAG_MARK_BIT  # Born marked!
    header.forward = 0
    return ptr + HEADER_SIZE
```

### 1.3 Migration Path

1. Update `HEADER_SIZE` constant from 16 to 32
2. Update header field offsets in all accessor code
3. Update `gc_alloc` to initialize 4 fields instead of 3
4. Update mark/sweep to use new flag offsets
5. Initialize forward pointer to 0 on allocation
6. Add birth-marking (set mark bit on allocation)

### Tests for Phase 1

- Unit test: Header size is 32 bytes
- Unit test: Field offsets are correct (0, 8, 16, 24)
- Unit test: Birth-marking sets mark bit
- Unit test: Forward pointer initialized to 0
- Unit test: Existing type dispatch still works with i64 type_id
- Integration test: Existing test suite passes with new header
- Integration test: gc_dump_object shows correct header fields

---

## Phase 2: Shadow Stack Thread-Local Preparation

Prepare the existing manual shadow stack for future multi-threading by adding thread-local storage infrastructure.

### 2.1 Current State

The manual shadow stack already works:
- `GCFrame: { i8* parent, i64 num_roots, i8** roots }`
- `gc_frame_top` global points to chain head
- `push_frame` / `pop_frame` manage the chain

### 2.2 Thread-Local Storage

For future multi-threading, prepare (but don't activate yet):

```c
// Current (single-threaded):
i8* gc_frame_top = NULL;

// Future (multi-threaded):
__thread i8* gc_frame_top = NULL;
```

### 2.3 Frame Depth Tracking

Add depth tracking to support watermark comparison:

```c
// Add to globals
i64 gc_frame_depth = 0;  // Current shadow stack depth

// In push_frame:
gc_frame_depth += 1;

// In pop_frame:
gc_frame_depth -= 1;
```

### 2.4 Implementation

1. Add `gc_frame_depth` global variable
2. Update `push_frame` to increment depth
3. Update `pop_frame` to decrement depth (and check watermark - Phase 5)
4. Keep `gc_frame_top` as regular global for now (single-threaded)
5. Document where `__thread` will be added for multi-threading

### Tests for Phase 2

- Unit test: Frame depth increments on push
- Unit test: Frame depth decrements on pop
- Unit test: Depth matches expected after nested calls
- Integration test: Existing GC tests pass with depth tracking
- Integration test: gc_dump_roots shows depth information

---

## Phase 3: Unified Global Heap

Replace dual A/B heaps with single global heap and allocation list.

### 3.1 Heap State

Simplified global state:

```c
struct GCState {
    i64 gc_enabled;           // Collection enabled
    i64 gc_in_progress;       // Currently collecting
    i64 alloc_count;          // Allocations since last GC
    i64 alloc_bytes;          // Bytes allocated since last GC
    i8* alloc_list_head;      // Head of allocation linked list
    // Thread registry (Phase 5)
    // Buffer pool (Phase 4)
};
```

### 3.2 Allocation List

Single linked list of all allocations (unchanged from current, but unified):

```c
struct AllocationNode {
    i64 next;    // Pointer to next node (as i64)
    i64 data;    // User pointer (as i64)
    i64 size;    // Allocation size
};
```

### 3.3 Remove A/B Infrastructure

1. Remove HeapRegion struct
2. Remove heap_a, heap_b from GCState
3. Remove active_heap tracking
4. Remove gc_swap_heaps
5. Remove snapshot capture for heap copying
6. Simplify to single alloc_list

### Tests for Phase 3

- Unit test: Single allocation list
- Unit test: No heap switching
- Integration test: Allocations visible in single list
- Integration test: Existing tests pass on unified heap

---

## Phase 4: Thread-Local Allocation Buffers (Stub)

Prepare infrastructure for thread-local allocation, but implement single-threaded initially.

### 4.1 Buffer Structure

```c
struct AllocationBuffer {
    i64 start;       // Buffer start address
    i64 current;     // Current allocation pointer (bump)
    i64 end;         // Buffer end address
    i64 thread_id;   // Owning thread (0 for single-threaded)
};
```

### 4.2 Global Buffer Pool

```c
struct BufferPool {
    i64 buffer_size;        // Size of each buffer (e.g., 64KB)
    i64 total_buffers;      // Total buffers allocated
    i8* free_list;          // Available buffers
    // Mutex for multi-threaded access (future)
};
```

### 4.3 Single-Threaded Implementation

For now, one buffer serves all allocations:

```python
def gc_alloc(size, type_id):
    if current_buffer.current + size > current_buffer.end:
        acquire_new_buffer()

    ptr = current_buffer.current
    current_buffer.current += align8(size + HEADER_SIZE)

    # Initialize header (with birth-marking)
    header = ptr
    header.size = align8(size + HEADER_SIZE)
    header.type_id = type_id
    header.flags = FLAG_MARK_BIT
    header.forward = 0

    # Add to allocation list
    add_to_alloc_list(ptr + HEADER_SIZE)

    return ptr + HEADER_SIZE
```

### 4.4 Buffer Acquisition

When buffer exhausted, get new one from pool:

```python
def acquire_new_buffer():
    if pool.free_list:
        buffer = pop_from_free_list()
    else:
        buffer = malloc(BUFFER_SIZE)
        pool.total_buffers += 1

    current_buffer.start = buffer
    current_buffer.current = buffer
    current_buffer.end = buffer + BUFFER_SIZE
```

### Tests for Phase 4

- Unit test: Bump allocation within buffer
- Unit test: Buffer exhaustion triggers new buffer
- Unit test: Buffer pool tracking
- Integration test: Large allocation sequence uses multiple buffers
- Integration test: gc_dump shows buffer state

---

## Phase 5: Thread Registry (Stub)

Prepare for multi-threading with thread registration infrastructure.

### 5.1 Thread Entry Structure

```c
struct ThreadEntry {
    i64 thread_id;              // Platform thread ID
    i64 shadow_stack_chain;     // Pointer to this thread's llvm_gc_root_chain
    i64 watermark;              // Current watermark depth (0 if none)
    i64 watermark_active;       // Watermark is set and collection ongoing
    i64 stack_depth;            // Current shadow stack depth
    i64 blocked;                // Thread is blocked waiting for GC
    i64 alloc_buffer;           // Thread's allocation buffer
    i64 next;                   // Next thread in registry
};
```

### 5.2 Registry Operations

```c
// Called when thread starts (just main thread for now)
void gc_register_thread(i64 thread_id);

// Called when thread exits
void gc_unregister_thread(i64 thread_id);

// Get thread's entry
ThreadEntry* gc_get_thread_entry(i64 thread_id);

// Iterate all threads (for watermark installation and tracing)
void gc_for_each_thread(void (*callback)(ThreadEntry*));
```

### 5.3 Single-Threaded Implementation

Registry contains exactly one entry (main thread):

```python
def gc_register_thread(thread_id):
    entry = alloc_thread_entry()
    entry.thread_id = thread_id
    entry.shadow_stack_chain = &llvm_gc_root_chain
    entry.watermark = 0
    entry.watermark_active = 0
    entry.stack_depth = 0
    entry.blocked = 0
    entry.alloc_buffer = &main_buffer
    entry.next = 0
    registry_head = entry
```

### Tests for Phase 5

- Unit test: Register main thread
- Unit test: Get thread entry
- Unit test: Iteration visits all (one) threads
- Unit test: Unregister cleans up
- Integration test: Thread entry accessible during collection

---

## Phase 6: Watermark Mechanism

Implement the core watermark installation and checking.

### 6.1 Watermark Installation

```python
def gc_install_watermarks():
    for thread in registry:
        thread.watermark = thread.stack_depth
        thread.watermark_active = 1

    stats.last_watermark_install_ns = measure_time()
    trace(GC_TRACE_PHASES, "Watermarks installed on %d threads", thread_count)
```

### 6.2 Stack Depth Tracking

Track depth as frames are pushed/popped:

```python
# At frame push (in LLVM-generated code, we track via frame count)
def on_frame_push(thread):
    thread.stack_depth += 1

def on_frame_pop(thread):
    if thread.watermark_active and thread.stack_depth <= thread.watermark:
        gc_block_until_complete(thread)
    thread.stack_depth -= 1
```

### 6.3 Block-on-Pop

```python
def gc_block_until_complete(thread):
    trace(GC_TRACE_OPS, "Thread %d blocking at depth %d (watermark %d)",
          thread.thread_id, thread.stack_depth, thread.watermark)

    stats.total_block_events += 1
    start_time = now()

    acquire(gc_mutex)
    while thread.watermark_active:
        wait(gc_complete_condition)
    release(gc_mutex)

    stats.total_block_wait_ns += now() - start_time
```

### 6.4 Watermark Clearing

```python
def gc_clear_watermarks():
    for thread in registry:
        thread.watermark = 0
        thread.watermark_active = 0

    broadcast(gc_complete_condition)  # Wake any blocked threads
```

### Tests for Phase 6

- Unit test: Watermark installation sets correct depth
- Unit test: Watermark active flag set
- Unit test: Stack depth tracking accurate
- Unit test: Pop below watermark triggers block check
- Unit test: Watermark clearing wakes blocked threads
- Integration test: Forward-progressing thread never blocks
- Integration test: Unwinding thread blocks when watermark crossed

---

## Phase 7: First Trace Pass (Liveness)

Implement the first trace that determines which objects are live.

### 7.1 Root Enumeration

Traverse all shadow stacks up to watermarks:

```python
def gc_enumerate_roots():
    roots = []
    for thread in registry:
        frame = thread.shadow_stack_chain
        depth = 0
        while frame and depth <= thread.watermark:
            for i in range(frame.num_roots):
                root = frame.roots[i]
                if root:
                    roots.append(root)
            frame = frame.next
            depth += 1
    return roots
```

### 7.2 Object Marking

```python
def gc_mark_object(ptr):
    if ptr == 0:
        return

    header = ptr - HEADER_SIZE

    # Already marked (handles cycles)
    if header.flags & FLAG_MARK_BIT:
        return

    header.flags |= FLAG_MARK_BIT
    stats.objects_marked_last_cycle += 1

    trace(GC_TRACE_DETAIL, "Marked object at %p, type=%d", ptr, header.type_id)

    # Type-specific traversal
    gc_mark_children(ptr, header.type_id)
```

### 7.3 Type-Specific Marking

Dispatch based on type_id (similar to current gc_mark_object):

```python
def gc_mark_children(ptr, type_id):
    if type_id == TYPE_LIST:
        gc_mark_list(ptr)
    elif type_id == TYPE_MAP:
        gc_mark_hamt(ptr, get_map_flags(ptr))
    elif type_id == TYPE_SET:
        gc_mark_hamt(ptr, get_set_flags(ptr))
    elif type_id == TYPE_ARRAY:
        gc_mark_array(ptr)
    elif type_id == TYPE_STRING:
        gc_mark_string(ptr)
    elif type_id >= TYPE_FIRST_USER:
        gc_mark_user_type(ptr, type_id)
```

### 7.4 First Trace Entry Point

```python
def gc_first_trace():
    start = now()

    trace(GC_TRACE_PHASES, "First trace starting")

    # Note: Objects are born marked, so we need to CLEAR marks first,
    # then remark from roots. But only for objects below watermarks.
    # Objects above watermarks (born during collection) stay marked.
    gc_clear_marks_below_watermarks()

    roots = gc_enumerate_roots()
    trace(GC_TRACE_OPS, "Found %d roots", len(roots))

    for root in roots:
        gc_mark_object(root)

    stats.last_first_trace_ns = now() - start
    trace(GC_TRACE_PHASES, "First trace complete: %d objects marked in %d ns",
          stats.objects_marked_last_cycle, stats.last_first_trace_ns)
```

**Important consideration**: Birth-marking means new objects survive. But we need to clear marks on OLD objects before tracing so we can identify garbage. The watermark boundary determines which objects are "old" (existed at watermark time) vs "new" (allocated after).

This requires either:
1. Track allocation time/sequence number, or
2. Clear marks only on objects in the allocation list at watermark time

Option 2 is simpler: snapshot the allocation list head at watermark time, clear marks only for objects in that snapshot.

### Tests for Phase 7

- Unit test: Root enumeration respects watermark boundary
- Unit test: Marking sets mark bit
- Unit test: Already-marked objects not re-processed (cycle handling)
- Unit test: Type dispatch correct for each type
- Unit test: Child traversal for lists, maps, sets, arrays
- Integration test: Reachable objects marked
- Integration test: Unreachable objects unmarked
- Integration test: New allocations during trace remain marked

---

## Phase 8: Sweep

Reclaim unmarked objects.

### 8.1 Sweep Implementation

```python
def gc_sweep():
    start = now()

    trace(GC_TRACE_PHASES, "Sweep starting")

    prev = None
    current = alloc_list_head
    swept_count = 0
    swept_bytes = 0

    while current:
        next_node = current.next
        obj_ptr = current.data
        header = obj_ptr - HEADER_SIZE

        if header.flags & FLAG_MARK_BIT:
            # Survivor: clear mark for next cycle
            header.flags &= ~FLAG_MARK_BIT
            prev = current
        else:
            # Garbage: free
            trace(GC_TRACE_DETAIL, "Sweeping %p (size %d)", obj_ptr, header.size)

            free(header)  # Free the object
            free(current)  # Free the allocation node

            # Unlink from list
            if prev:
                prev.next = next_node
            else:
                alloc_list_head = next_node

            swept_count += 1
            swept_bytes += header.size

        current = next_node

    stats.objects_swept_last_cycle = swept_count
    stats.bytes_reclaimed_last_cycle = swept_bytes
    stats.last_sweep_ns = now() - start

    trace(GC_TRACE_PHASES, "Sweep complete: %d objects, %d bytes in %d ns",
          swept_count, swept_bytes, stats.last_sweep_ns)
```

### Tests for Phase 8

- Unit test: Unmarked objects freed
- Unit test: Marked objects survive with mark cleared
- Unit test: Allocation list correctly updated
- Integration test: Memory actually reclaimed (check with valgrind)
- Integration test: Surviving objects accessible after sweep

---

## Phase 9: Collection Orchestration

Wire up the complete collection cycle.

### 9.1 GC() - Synchronous Collection

```python
def GC():
    if not gc_enabled or gc_in_progress:
        return

    gc_in_progress = 1
    start = now()

    trace(GC_TRACE_PHASES, "=== GC CYCLE STARTING ===")

    # Phase 1: Install watermarks
    gc_install_watermarks()
    snapshot_alloc_list = alloc_list_head  # For mark clearing

    # Phase 2: Trace (liveness)
    gc_trace()

    # Phase 3: Sweep
    gc_sweep()

    # Cleanup
    gc_clear_watermarks()
    gc_in_progress = 0

    stats.collections_completed += 1
    stats.last_total_gc_ns = now() - start
    stats.allocations_since_last_gc = 0
    stats.bytes_since_last_gc = 0

    trace(GC_TRACE_PHASES, "=== GC CYCLE COMPLETE: %d ns ===", stats.last_total_gc_ns)
```

### 9.2 gc_async() - Non-Blocking Collection

For single-threaded, this is the same as GC() since there's no separate GC thread yet:

```python
def gc_async():
    # In single-threaded mode, just do synchronous collection
    # Multi-threaded implementation will spawn/signal GC thread
    GC()
```

### Tests for Phase 9

- Unit test: All phases execute in order
- Unit test: Statistics updated correctly
- Unit test: Watermarks cleared at end
- Integration test: Full cycle collects garbage
- Integration test: Live objects survive
- Stress test: 10M allocations with periodic GC
- Stress test: Deep recursion with GC at various depths

---

## Phase 10: Integration and Cleanup

### 10.1 Remove Old A/B Infrastructure

- Delete dual-heap code from coex_gc.py
- Remove snapshot capture
- Remove heap switching
- Remove cross-heap scanning
- Simplify global state

### 10.2 Update Existing Tests

- Migrate test_gc.py to new GC
- Migrate test_gc_async.py
- Migrate test_gc_stress.py
- Fix any regressions

### 10.3 New Test Suite

Comprehensive tests from the specification:

**Unit Tests:**
- Shadow stack push/pop operations
- Frame depth tracking
- Thread registration/unregistration (stub)
- Watermark installation/clearing
- Birth-marking at allocation
- Mark bit operations
- Type-specific marking (lists, maps, sets, arrays, strings)

**Integration Tests:**
- Block-on-pop under tracing (single-threaded simulation)
- Zero-pause for forward-progressing code paths
- Allocation during watermark installation
- Cycle creation and collection
- Nested function calls with GC

**Stress Tests:**
- 10M allocations, single thread
- Rapid shallow call stacks (frequent watermark crossings)
- Deep call stacks (infrequent watermark crossings)
- Large object graphs with cycles
- Memory ordering (ARM64 specific)

**Benchmarks:**
- Allocation throughput
- Collection pause time distribution
- Comparison vs old A/B system

### Tests for Phase 10

- All existing tests pass
- New unit tests pass
- New integration tests pass
- Stress tests complete without timeout
- No memory leaks (valgrind clean)
- No undefined behavior (ASAN/UBSAN clean)

---

## Implementation Order Summary

| Phase | Description | Depends On |
|-------|-------------|------------|
| 0 | Debugging infrastructure | None |
| 1 | New 32-byte header | 0 |
| 2 | Shadow stack depth tracking | 1 |
| 3 | Unified global heap | 1 |
| 4 | Thread-local buffers (stub) | 3 |
| 5 | Thread registry (stub) | 4 |
| 6 | Watermark mechanism | 2, 5 |
| 7 | Trace pass | 6 |
| 8 | Sweep | 7 |
| 9 | Collection orchestration | 8 |
| 10 | Integration and cleanup | 9 |

**Future phases (deferred):**
- Compaction with forwarding pointers
- Second trace pass for forward following
- Scope-local arenas
- True multi-threading with thread-local shadow stacks

---

## Open Questions

1. **Mark clearing strategy**: How do we distinguish "old" objects (clear marks) from "new" objects (keep birth-marked) during trace? Proposal: snapshot alloc_list head at watermark time.

2. **Buffer size**: What size for thread-local allocation buffers? Start with 64KB and tune.

3. **Initial heap size**: How large should we allocate initially to avoid fragmentation issues before compaction is implemented?

---

## Success Criteria

1. All existing tests pass with new GC
2. New stress tests pass at 10M allocations
3. No pathological delays (define acceptable bounds)
4. Memory usage reasonable (define bounds)
5. Clean valgrind/ASAN/UBSAN runs
6. Debugging infrastructure provides clear visibility into GC behavior
