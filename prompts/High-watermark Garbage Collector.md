---

## Coex Garbage Collector Implementation Specification

### Architectural Overview

The Coex garbage collector is a concurrent, tracing collector built on LLVM's shadow stack infrastructure using a technique we call **High Watermark Collection**. The design exploits the language's immutability guarantee to enable concurrent tracing without write barriers, and defers synchronization costs to threads that unwind past traced regions—often eliminating pause time entirely.

**Core principle**: All heap objects are immutable after construction. This invariant is enforced by the language and must never be violated. Immutability enables concurrent tracing from a marked stack position without synchronization—the reachability graph from any watermark is frozen by definition.

### Memory Architecture

**Global Heap**: A single, unified heap holds all structured objects: nodes, arrays, strings, and any value larger than a primitive. Objects on the global heap are subject to garbage collection. The allocator uses thread-local allocation buffers; each thread bump-allocates from a private region and acquires a new buffer from the global pool only when exhausted. Buffer acquisition is the only allocation path requiring synchronization.

**Scope-Local Arenas**: Each thread maintains a bump allocator for scope-bound metadata. These arenas hold primitive local variables and pointers (roots) to heap objects—never the objects themselves. When a scope exits, its arena region is reclaimed by resetting the bump pointer. No tracing, no freeing, no GC involvement. This is the fast path for function-local state.

**Escape Semantics**: When a pointer escapes its scope (returned, sent through a channel, stored in a longer-lived structure), only the pointer value is copied. The referenced object already resides on the global heap, so no object copying occurs. Immutability guarantees the object's validity regardless of which scope holds a reference.

### Per-Thread Shadow Stacks

Each mutator thread owns a private shadow stack that tracks GC roots for that thread. Shadow stacks are independent; no thread accesses another thread's shadow stack during normal execution.

**Shadow Stack Structure**: Each shadow stack is a contiguous array or linked structure of root entries. Each entry contains a pointer to a heap object (or the address of a stack slot containing such a pointer, depending on implementation). The stack grows with function calls and scope entries; it shrinks with returns and scope exits.

**Thread Registration**: When a thread is created, it allocates and registers its shadow stack with the GC subsystem. The GC maintains a registry of all active thread shadow stacks for traversal during collection. When a thread terminates, it unregisters its shadow stack.

**Independence**: Threads push and pop their own shadow stacks without synchronization. No locks, no atomics, no coordination with other threads during normal execution. This is critical for performance—root tracking is on the hot path.

**Per-Thread Watermarks**: Each shadow stack has its own watermark. During collection, the GC installs a watermark in each registered thread's stack independently. Threads block only on their own watermark; a thread whose stack is shallow (or never unwinds) is unaffected by deep stacks in other threads.

### Object Lifecycle

**Birth-Marking**: All objects are born marked. At allocation time, set the object's mark bit. This is unconditional and universal.

**Tracing**: The collector traverses reachable objects from roots below the watermark in all thread shadow stacks. Reachable objects remain marked.

**Sweep**: Unmarked objects are garbage and reclaimed. Marked objects survive and have their mark bit cleared in preparation for the next cycle.

**Consequence**: Every object survives at least one complete collection cycle. This is acceptable; lazy reclamation is the design philosophy.

### High Watermark Collection

The collector uses a **watermark** mechanism rather than snapshot copying: a marker divides each thread's stack into a "traced" region (at or below the mark) and an "active" region (above the mark).

**Watermark Semantics**:
- Each thread's watermark is a stack depth marker (index, pointer, or frame identifier) set at collection initiation
- Roots at or below a thread's watermark are part of the traced root set
- Roots above a thread's watermark are implicitly live (too new to be garbage)
- Pushes proceed freely above the watermark with no synchronization
- Pops that would cross a thread's own watermark block that thread until tracing completes

**GC Cycle**:

1. **Mark**: For each registered thread, atomically record the current stack depth as that thread's watermark. This is a single write per thread—no root copying, no traversal. Threads may be briefly paused to ensure watermark consistency, but the pause is O(1) per thread regardless of stack depth.

2. **Resume**: All mutator threads continue execution immediately. Pushes (function calls, scope entries) proceed without synchronization. The active region above each watermark grows freely.

3. **Trace**: The collector iterates through all registered thread shadow stacks, traversing roots at or below each thread's watermark. From these roots, it walks the object graph on the global heap. Reachable objects remain marked. This runs concurrently with mutator execution.

4. **Block-on-pop**: If a mutator thread's stack unwinds and would cross its own watermark, that thread blocks until tracing completes. Other threads are unaffected—each thread's blocking condition is independent.

5. **Complete**: When tracing finishes, clear all watermarks across all threads. Blocked threads (if any) resume.

6. **Sweep** (deferred): Reclaim unmarked objects lazily, either during subsequent allocation or in batch. Clear mark bits on surviving objects.

**Why This Works**: Immutability guarantees that newly allocated objects can only reference objects that existed at watermark time. Those referenced objects are either reachable from the traced roots (and will remain marked) or were themselves allocated after watermark installation (and are born marked). The reachability closure is preserved without tracing the active regions of any thread.

### Synchronization

**Watermark Installation**: Use pthread mutex briefly during watermark installation to ensure all threads have consistent watermarks before tracing begins. This is the only "stop the world" moment, and it performs O(1) work per thread (recording a stack depth), not O(n) work proportional to root count.

**Thread Registry Access**: The GC must safely iterate the thread registry during watermark installation and tracing. Use a read-write lock or similar mechanism: thread creation/destruction acquires write access; watermark installation and tracing acquire read access. Thread creation and destruction are infrequent; this should not be a bottleneck.

**Block-on-Pop Mechanism**: Each thread checks its own watermark before completing a pop operation. If the pop would cross the watermark and tracing is ongoing, the thread waits on a condition variable. When tracing completes, the collector broadcasts to wake all blocked threads and clears all watermarks atomically.

Implementation sketch:
```
pop_frame(thread):
    if thread.watermark_active and thread.stack_depth <= thread.watermark:
        acquire(gc_mutex)
        while thread.watermark_active and thread.stack_depth <= thread.watermark:
            wait(gc_complete_condition)
        release(gc_mutex)
    // proceed with pop
```

**Memory Ordering**: The mutex acquire/release around watermark checking and the condition variable wait/broadcast provide the necessary memory barriers. Watermark reads and the `watermark_active` flag should use acquire/release semantics if accessed outside the mutex (e.g., for the fast-path check before acquiring).

**Thread-Local Allocation Buffers**: Each mutator thread's allocation buffer is private; no synchronization on the allocation fast path. Buffer acquisition from the global pool requires synchronization (mutex initially, lock-free CAS as optimization if profiling indicates contention).

### Entry Points

**`GC()`**: Blocking collection. Installs watermarks on all threads, waits for tracing to complete, returns. Caller is guaranteed garbage has been identified (though sweep may be deferred).

**`gc_async()`**: Non-blocking initiation. Installs watermarks on all threads and returns immediately. Tracing proceeds concurrently. Caller continues execution; will only block if its own stack unwinds past its watermark before tracing completes.

**Overlapping Requests**: Collection requests queue; the collector services them sequentially. A request received while collection is ongoing increments a pending counter. The collector runs continuously until pending requests are exhausted.

### Implementation Requirements

**Data Types**: All flags, counters, indices, watermarks, sizes, and similar values must use `int64_t` (i64). This ensures consistent behavior and atomic operation availability across all supported 64-bit platforms (x86-64 Linux, ARM64 macOS). No platform-dependent integer sizing.

**Immutability Enforcement**: The collector assumes immutability. Any code path that would mutate a heap object after construction is a bug in the language implementation, not a GC edge case to handle. Assert this invariant aggressively during development.

**Test-First Development**: Determine and write tests before implementing each component. Test categories should include:

- Unit tests for shadow stack push/pop operations
- Unit tests for thread registration and unregistration
- Unit tests for watermark installation and clearing
- Unit tests for per-thread watermark independence
- Unit tests for bump allocator acquire/reset
- Unit tests for birth-marking at allocation
- Unit tests for mark bit clearing at sweep
- Integration tests for block-on-pop under concurrent tracing
- Integration tests verifying threads that never unwind past watermark experience zero pause
- Integration tests verifying one thread blocking does not affect other threads
- Integration tests for thread creation/destruction during collection
- Stress tests with millions of allocations across multiple threads
- Stress tests with rapid shallow call stacks (frequent watermark crossings)
- Stress tests with deep call stacks (infrequent watermark crossings)
- Stress tests with heterogeneous thread behavior (some deep, some shallow, some blocking, some not)
- Cycle detection tests (the language permits cycles in some function types)
- Memory ordering tests specifically targeting ARM64 (where relaxed ordering can expose races x86-64 hides)
- Comparative benchmarks against A/B snapshot collection for regression testing

**Debugging Infrastructure**: Build traceable debugging into the GC from the start. The collector will grow complex; retrofitting observability is painful. Include:

- Configurable trace logging for collection phases (watermark install, trace start/end, sweep statistics)
- Per-thread watermark state inspection (current depth, watermark depth, blocked status)
- Thread registry dumps (list all registered threads and their shadow stack states)
- Root enumeration dumps (list all roots at or below watermarks at trace start, grouped by thread)
- Heap walking utilities (enumerate all live objects, validate internal pointer consistency)
- Statistics collection:
  - Allocation counts and rates (global and per-thread)
  - Collection counts and durations
  - Trace times (how long from watermark to trace complete)
  - Block events per thread (how often each thread blocks, how long it waits)
  - Thread count over time
  - Survival rates
- Conditional compilation or runtime flags to enable/disable tracing without performance penalty in release builds
- Assertions for invariant checking (shadow stack consistency, watermark validity, no dangling pointers in traced set, object header validity, mark bit correctness, thread registry consistency)

### Performance Characteristics

**Best case**: Threads that are "going deeper" (more calls, more allocations) never synchronize with the collector at all. Collection is invisible to forward-progressing computation.

**Worst case**: A thread that immediately unwinds a deep stack after watermark installation blocks for the full trace duration. This is equivalent to stop-the-world for that thread, but other threads continue unimpeded.

**Expected case**: Most threads experience zero pause. Threads returning from deep call stacks may occasionally block briefly. The pause distribution shifts from "everyone pauses at collection start" to "some threads may pause at unwind time, if unlucky." Critically, threads are independent—one thread's blocking does not propagate to others.

**Comparison to A/B Snapshot Collection**: The A/B approach copies all roots from all threads at snapshot time, guaranteeing O(total root count) work during the stop-the-world phase but zero blocking thereafter. High watermark collection does O(thread count) work at watermark time but may block individual threads later. Benchmark both; the better choice depends on workload characteristics (stack depth distributions, call/return frequency, collection frequency, thread count).

### Collection Philosophy

**Lazy Reclamation**: Prompt reclamation is not a goal. Garbage may survive an extra cycle. All objects survive at least their first cycle by design. Optimize for throughput and minimal pause disruption, not minimum heap footprint.

**Memory Abundance Assumption**: Modern systems have substantial memory. The architecture prioritizes simplicity and correctness over aggressive space optimization. If allocation outpaces collection, the system accepts heap growth rather than introducing complex backpressure mechanisms. Pathological cases (genuine memory exhaustion) fail explicitly rather than being papered over.

**Fragmentation Tolerance**: Deferred sweeping with concurrent allocation will produce fragmentation. Thread-local allocation buffers mitigate this. Compaction is out of scope for initial implementation; revisit only if empirical measurement shows fragmentation causing allocation failures.

### Platform Targets

- Linux x86-64
- macOS ARM64 (Apple Silicon)

Both are 64-bit only. 32-bit platforms are not supported.

### Terminology Note

The name "High Watermark Collection" reflects that the watermark represents the highest (deepest) stack position considered part of the traced root set at collection initiation. Roots "above" the watermark (pushed after marking) are in shallower, newer frames and are not traced. This is analogous to a flood gauge: everything below the high water mark gets wet (traced); everything above stays dry (implicitly live).

---