

## Convert Synchronous GC to Dual-Heap Async Collection Model

### Context

The Coex compiler has a working cross-platform garbage collector using LLVM's shadow stack approach. Currently, `gc()` runs synchronously—when called, the mutator pauses completely while mark-sweep collection occurs. We're converting this to an asynchronous model where collection runs in a dedicated thread while the mutator continues executing.

This conversion is made possible by a key property of Coex: **all heap objects are immutable**. There is no mutation, only rebinding and copy-on-write. This means the pointer graph in a heap region is frozen the moment each object is allocated—pointers can be copied but never modified after creation.

### Architecture Overview

**Dual-heap design:**

Maintain two heap regions, A and B. At any moment, one is the "active" heap receiving new allocations, and the other is either being collected or waiting for collection. When a GC cycle triggers:

1. Brief pause: snapshot the shadow stack (copy root pointers)
2. Swap active heap designation (A→B or B→A)
3. Resume mutator immediately, allocating to the new active heap
4. GC thread collects the old heap asynchronously using the snapshot

**Why immutability makes this safe:**

When the mutator creates a new object in heap B with a pointer to object X in heap A, that pointer must have been copied from somewhere—either directly from the shadow stack at swap time, or by traversing from something reachable at swap time. Therefore, if X was reachable at the snapshot, the GC will find it by tracing from the snapshot. If X wasn't reachable at the snapshot, no new reference to X can be created (you can't conjure pointers from nothing), so X is correctly identified as garbage.

### Implementation Requirements

**0. Cross-Platform Mandate

The Garbage collector MUST run across MacOS and Linux in order to pass tests. Use ONLY i64 for pointers, flags, counters, and all other integer purposes to avoid ambiguities between OSes and CPU families that lead to padding errors.

Choose threading models that function correctly, and if OS specific code is necessary for both MacOS and Linux, generate it and annotate with comments.

**1. Dual Heap Infrastructure**

Create two heap regions with identical structure to the current single heap:

```
struct HeapRegion {
    void* base;           // Start of heap memory
    void* current;        // Current allocation pointer (bump allocator)
    void* limit;          // End of heap memory
    // ... existing object tracking structures
}

HeapRegion heap_a;
HeapRegion heap_b;
HeapRegion* active_heap;  // Points to whichever heap receives allocations
```

Modify the allocation function to use `active_heap` rather than a single global heap.

**2. Shadow Stack Snapshot**

Create a snapshot structure that captures the shadow stack state:

```
struct RootSnapshot {
    void** roots;         // Array of root pointers
    size_t count;         // Number of roots captured
}
```

Implement `capture_shadow_stack_snapshot()` that:
- Walks the shadow stack linked list
- Copies each root pointer value into the snapshot array
- Returns the snapshot for the GC thread to use

This is a shallow copy of pointer values, not a deep copy of objects.

**3. Heap Swap Operation**

Implement `swap_heaps()` that:
- Briefly pauses mutator execution (this is the only pause point)
- Calls `capture_shadow_stack_snapshot()`
- Swaps `active_heap` to point to the other heap region
- Signals the GC thread with the snapshot and which heap to collect
- Resumes mutator execution

The pause duration is O(shadow stack depth)—just copying pointer values.

**4. GC Thread**

Spawn a dedicated GC thread at program startup that:
- Blocks waiting for collection requests
- When signaled, receives: the snapshot and which heap region to collect
- Performs mark phase: traces from snapshot roots through the target heap
- Also scans the *other* heap for pointers into the target heap (cross-heap roots)
- Performs sweep phase: frees unmarked objects in target heap, clears mark bits
- Resets the collected heap's allocation pointer to base (bulk deallocation)
- Signals completion

**5. Cross-Heap Pointer Scanning**

During mark phase, the GC must find all roots into the heap being collected. These roots come from two sources:

1. The shadow stack snapshot (captured at swap time)
2. Objects in the other heap that contain pointers into the collected heap

For source 2: walk all allocated objects in the non-collected heap, examine each pointer field, and if it points into the collected heap, treat it as a root. Because heap objects are immutable, this scan is safe even while the mutator allocates new objects—existing objects don't change, and new objects are appended past the scan frontier.

**6. Modified `gc()` Function**

The public `gc()` function becomes:

```
func gc():
    if gc_in_progress:
        wait_for_gc_completion()  // Don't trigger overlapping collections
    
    swap_heaps()  // Brief pause here
    signal_gc_thread()
    // Optionally wait for completion, or return immediately
```

For the initial implementation, have `gc()` wait for completion to maintain the current synchronous semantics from the caller's perspective. This can be relaxed later.

Create an non-waiting 'gc_async()' function that triggers collection and only waits for the snapshot before returning.

**7. Allocation Pressure Triggering**

Modify the allocation path:

```
func allocate(size):
    if active_heap->current + size > active_heap->limit:
        if gc_in_progress:
            wait_for_gc_completion()
        else:
            trigger_gc()
            wait_for_gc_completion()
        // After GC, the other heap is now active and should have space
        // If still no space, grow heaps or OOM
    
    result = active_heap->current
    active_heap->current += size
    return result
```

**8. Synchronization Primitives**

Use minimal synchronization:

- A mutex or flag for the brief swap pause (ensure mutator isn't mid-allocation during swap)
- A condition variable or semaphore for signaling the GC thread
- A completion signal for `gc()` callers that want to wait

The key insight is that heavy synchronization isn't needed during collection itself—only at the swap point.

### Critical Invariants

**Preserve these properties:**

1. Objects are never modified after allocation (Coex's immutability guarantee)
2. The shadow stack snapshot captures all roots at a consistent point in time
3. Cross-heap pointers can only exist from the newer heap to the older heap (pointers into a heap can only be created while that heap is active or from objects that were themselves created when it was active)
4. The GC thread never accesses the active heap's allocation frontier region
5. The mutator never accesses the collected heap during sweep (it's allocating to the other one)

### Testing Strategy

**Test cases to verify correctness:**

0. Write any necessary new tests prior to changing code and predict whether they should pass or fail. Show them operating to prediction. 
1. Allocate objects, trigger GC, verify unreachable objects are collected
2. Allocate objects with cross-heap references, trigger GC, verify reachable objects survive
3. Rapid allocation during GC to verify mutator doesn't block
4. Multiple GC cycles to verify heap swapping works repeatedly
5. Deep object graphs spanning both heaps to verify full tracing
6. Write stress-tests that show every object type (ARRAY, STRING, MAP, SET, LIST, MATRIX) being allocated and deallocated at least 10 million times.

**Test for the race condition that immutability prevents:**

Create a scenario where, if mutation were allowed, a pointer could be stored after snapshot but before trace. Verify that Coex's semantics make this impossible—the only way to "store" a pointer is to allocate a new object containing it, which goes to the active (non-collected) heap.

### Files to Modify

- `codegen.py`: Allocation functions, heap initialization, GC triggering
- Runtime support code: GC thread, snapshot capture, heap swap, synchronization

### Notes

- The shadow stack mechanism remains unchanged—we're just snapshotting it rather than walking it synchronously
- Initial heap sizes can match the current single heap size; each region gets half, or keep the same size for each (doubling total memory)
- The GC thread should handle the case where collection finishes before another is requested (common case) and where a new request arrives while still collecting (must wait)
- This design scales naturally to multiple mutator threads later—each would pause briefly at swap time, but collection still happens in a single GC thread

---
