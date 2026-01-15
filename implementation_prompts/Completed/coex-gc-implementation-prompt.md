# Coex Garbage Collector Implementation Prompt

## For Claude Code / AI-Assisted Implementation

---

## Overview

You are implementing the runtime garbage collector for the Coex programming language. This is a concurrent, relocating collector that operates without write barriers, read barriers, or Stop-the-World pauses. The design exploits Coex's immutable heap semantics and handle-based indirection to achieve "invisible" memory management.

**Read the accompanying specification document (`coex-gc-spec.md`) in full before proceeding.**

---

## Implementation Scope

### Phase 1: Core Data Structures

Implement the foundational runtime structures in C with LLVM interoperability:

```
src/
├── runtime/
│   ├── gc/
│   │   ├── handle.h         # Handle definition and atomic operations
│   │   ├── handle.c
│   │   ├── shadow_stack.h   # Per-thread shadow stack management
│   │   ├── shadow_stack.c
│   │   ├── tcb.h            # Thread Control Block
│   │   ├── tcb.c
│   │   ├── tlab.h           # Thread-Local Allocation Buffer
│   │   ├── tlab.c
│   │   ├── region.h         # Heap region management
│   │   ├── region.c
│   │   ├── gc_state.h       # Global GC state machine
│   │   ├── gc_state.c
│   │   ├── marker.h         # Concurrent marking implementation
│   │   ├── marker.c
│   │   ├── relocator.h      # Object relocation with handle updates
│   │   ├── relocator.c
│   │   └── gc_thread.c      # Main GC thread loop
│   └── allocator/
│       ├── bump_allocator.h # Fast-path TLAB allocation
│       ├── bump_allocator.c
│       ├── region_pool.h    # Region acquisition and return
│       └── region_pool.c
├── llvm/
│   ├── safepoint_pass.cpp   # LLVM pass to insert safepoint checks
│   └── intrinsics.cpp       # Shadow stack intrinsics
└── tests/
    ├── test_handle.c
    ├── test_shadow_stack.c
    ├── test_marking.c
    ├── test_relocation.c
    └── stress_test.c
```

### Phase 2: LLVM Integration

Create an LLVM pass that inserts safepoint checks at function prologues and loop backedges.

### Phase 3: GC Thread Implementation

Implement the three-phase collection cycle (Marking → Relocation → Reclamation).

### Phase 4: Testing and Verification

Build comprehensive tests for race conditions, memory ordering, and correctness.

---

## Detailed Implementation Tasks

### Task 1: Handle Implementation

**File:** `src/runtime/gc/handle.h` and `handle.c`

```c
// Requirements:
// 1. Handle is a pointer-sized atomic cell
// 2. GC updates use store-release
// 3. Mutator reads use load-acquire
// 4. Must be cache-line aligned to prevent false sharing

typedef struct Handle {
    _Alignas(64) _Atomic(void*) ptr;
} Handle;

// Implement:
void* handle_load(Handle* h);           // Load-acquire semantics
void handle_store(Handle* h, void* p);  // Store-release semantics (GC only)
Handle* handle_alloc(void* initial);    // Allocate new handle
void handle_free(Handle* h);            // Return handle to pool
```

**Constraints:**
- Use C11 atomics (`<stdatomic.h>`)
- Ensure 64-byte alignment for cache-line isolation
- Consider handle pooling with delayed reuse (2-epoch delay for ABA prevention)

---

### Task 2: Shadow Stack Implementation (Segmented)

**File:** `src/runtime/gc/shadow_stack.h` and `shadow_stack.c`

```c
// Requirements:
// 1. Segmented linked list of 4KB page-aligned blocks
// 2. Each segment holds 509 handle slots (plus 3 header fields = 4096 bytes)
// 3. Push/pop are single-threaded (mutator only)
// 4. GC traverses segments via linked list, respecting watermark
// 5. Segments are NEVER moved or reallocated (Segment Stability Invariant)

#define STACK_SEGMENT_SIZE  4096
#define STACK_SEGMENT_SLOTS 509

typedef struct StackSegment {
    struct StackSegment* prev;       // Link to previous segment
    struct StackSegment* next;       // Link to next segment (growth/reuse)
    Handle**             watermark;  // Per-segment GC watermark
    Handle*              slots[STACK_SEGMENT_SLOTS];  // 509 handle slots
} StackSegment;

// Compile-time verification
_Static_assert(sizeof(StackSegment) == 4096, "StackSegment must be 4KB");

typedef struct ShadowStack {
    StackSegment* base_segment;   // First segment (never changes)
    StackSegment* current;        // Active segment
    Handle**      top;            // Current slot pointer
    Handle**      segment_limit;  // End of current segment's slots
} ShadowStack;

// Implement:
ShadowStack* shadow_stack_create(void);
void shadow_stack_destroy(ShadowStack* ss);

// Segment allocation (page-aligned via mmap)
StackSegment* stack_segment_alloc(void);
void stack_segment_free(StackSegment* seg);

// These are inlined in the mutator hot path:
static inline void shadow_stack_push(ShadowStack* ss, Handle* h) {
    if (ss->top >= ss->segment_limit) {
        shadow_stack_grow(ss);  // Out-of-line slow path
    }
    *ss->top++ = h;
}

static inline Handle* shadow_stack_pop(ShadowStack* ss) {
    if (ss->top <= (Handle**)&ss->current->slots[0]) {
        shadow_stack_shrink(ss);  // Out-of-line slow path
    }
    return *--ss->top;
}

static inline Handle** shadow_stack_top(ShadowStack* ss) {
    return ss->top;
}

// Slow path helpers (called when crossing segment boundaries)
void shadow_stack_grow(ShadowStack* ss);
void shadow_stack_shrink(ShadowStack* ss);

// GC traversal support
typedef void (*SegmentVisitor)(StackSegment* seg, Handle** limit, void* ctx);
void shadow_stack_traverse(ShadowStack* ss, Handle** watermark, 
                           SegmentVisitor visitor, void* ctx);
```

**Constraints:**
- Use `mmap` for segment allocation to guarantee page alignment
- The `prev` pointer must be set BEFORE the segment becomes visible (for GC safety)
- Never deallocate segments during thread execution (only at thread exit)
- Consider prefetching next segment during push operations
- The `top` pointer must be readable by GC without synchronization (via watermark capture)

---

### Task 3: Thread Control Block (TCB)

**File:** `src/runtime/gc/tcb.h` and `tcb.c`

```c
// Requirements:
// 1. Contains atomic watermark and phase_ack
// 2. Holds TLAB pointers for epoch swapping
// 3. Must be accessible from both mutator and GC threads

typedef struct TCB {
    _Atomic(Handle**) watermark;    // Published stack snapshot
    _Atomic(uint32_t) phase_ack;    // Last acknowledged GC phase
    
    struct TLAB* active_tlab;       // Current allocation buffer
    struct TLAB* stale_tlab;        // Previous buffer
    
    ShadowStack* shadow_stack;
    
    // Linkage for GC thread enumeration
    struct TCB* next;               // Global TCB list link
    uint64_t thread_id;
} TCB;

// Implement:
TCB* tcb_create(void);
void tcb_destroy(TCB* tcb);
void tcb_register(TCB* tcb);        // Add to global list
void tcb_unregister(TCB* tcb);      // Remove from global list

// Called from safepoint check:
void tcb_publish_watermark(TCB* tcb);
void tcb_swap_tlabs(TCB* tcb);
void tcb_acknowledge_phase(TCB* tcb, uint32_t phase);
```

**Constraints:**
- Global TCB list must be thread-safe for registration/unregistration
- Consider using a lock-free list or reader-writer lock
- TCB destruction must handle case where GC is mid-cycle

---

### Task 4: TLAB Implementation

**File:** `src/runtime/gc/tlab.h` and `tlab.c`

```c
// Requirements:
// 1. Bump-pointer allocation (no synchronization on fast path)
// 2. Request new TLAB from region pool on exhaustion
// 3. Track epoch for GC coordination

typedef struct TLAB {
    uint8_t* cursor;        // Next allocation address
    uint8_t* limit;         // Buffer end
    struct Region* region;  // Backing region
    uint64_t epoch;         // Allocation epoch
} TLAB;

// Implement:
TLAB* tlab_create(size_t size);
void tlab_destroy(TLAB* tlab);
void* tlab_alloc(TLAB* tlab, size_t size);  // Fast path
TLAB* tlab_request_new(size_t preferred_size);  // Slow path
void tlab_return(TLAB* tlab);  // Return to region pool
```

**Constraints:**
- Default TLAB size: 256KB (configurable)
- Fast path must be branchless except for limit check
- Slow path may block waiting for region availability

---

### Task 5: Region Management

**File:** `src/runtime/gc/region.h` and `region.c`

```c
// Requirements:
// 1. Fixed-size memory regions (2MB default, huge page aligned)
// 2. Classified by epoch/state (FREE, ACTIVE, STALE, NEW)
// 3. Track live object count for reclamation decisions

typedef enum RegionState {
    REGION_FREE,
    REGION_ACTIVE,      // Currently receiving allocations
    REGION_STALE,       // Previous epoch, being collected
    REGION_NEW          // Destination for relocation
} RegionState;

typedef struct Region {
    void* base;
    size_t size;
    _Atomic(RegionState) state;
    _Atomic(size_t) live_bytes;
    uint64_t epoch;
    struct Region* next;  // Free list linkage
} Region;

typedef struct RegionPool {
    Region* free_list;
    _Atomic(size_t) total_allocated;
    _Atomic(size_t) total_live;
    pthread_mutex_t lock;
} RegionPool;

// Implement:
RegionPool* region_pool_create(size_t initial_regions);
void region_pool_destroy(RegionPool* pool);
Region* region_acquire(RegionPool* pool, RegionState initial_state);
void region_release(RegionPool* pool, Region* region);
```

**Constraints:**
- Use `mmap` with `MAP_HUGETLB` for 2MB regions where available
- Fall back to regular `mmap` if huge pages unavailable
- Region metadata should be stored separately from region data (avoid polluting hot data)

---

### Task 6: Global GC State Machine

**File:** `src/runtime/gc/gc_state.h` and `gc_state.c`

```c
// Requirements:
// 1. Atomic phase transitions
// 2. Epoch counter for cycle identification
// 3. Trigger conditions (memory pressure, explicit request)

typedef enum GCPhase {
    GC_PHASE_OFF = 0,
    GC_PHASE_MARKING = 1,
    GC_PHASE_RELOCATING = 2
} GCPhase;

typedef struct GCState {
    _Atomic(GCPhase) phase;
    _Atomic(uint64_t) epoch;
    
    // Statistics
    _Atomic(uint64_t) total_collections;
    _Atomic(uint64_t) total_bytes_collected;
    _Atomic(uint64_t) total_bytes_relocated;
    
    // Configuration
    size_t trigger_threshold;  // Bytes allocated before triggering GC
    
    // Synchronization
    pthread_mutex_t phase_lock;
    pthread_cond_t phase_changed;
} GCState;

extern GCState global_gc_state;

// Implement:
void gc_state_init(void);
void gc_state_shutdown(void);
bool gc_state_transition(GCPhase from, GCPhase to);
void gc_state_wait_for_phase(GCPhase target);
bool gc_state_all_threads_acknowledged(uint32_t phase);
```

---

### Task 7: Concurrent Marker

**File:** `src/runtime/gc/marker.h` and `marker.c`

```c
// Requirements:
// 1. Parallel work-stealing mark queue
// 2. Mark bitmap for objects in stale regions
// 3. Root scanning from segmented shadow stacks and atomic globals
// 4. Traverse stack segments via linked list up to watermark

typedef struct MarkBitmap {
    uint64_t* bits;
    void* region_base;
    size_t region_size;
} MarkBitmap;

typedef struct MarkWorklist {
    void** items;
    _Atomic(size_t) head;
    _Atomic(size_t) tail;
    size_t capacity;
} MarkWorklist;

// Implement:
void marker_init(void);
void marker_shutdown(void);

// Main marking entry point (called by GC thread)
void marker_run_phase(void);

// Internal functions:
void marker_scan_roots(void);
void marker_scan_thread_stack(TCB* tcb);
void marker_scan_atomic_globals(void);
void marker_trace_object(void* obj);
bool marker_is_marked(void* obj);
void marker_set_marked(void* obj);

// Segmented stack traversal for root scanning:
// Walk segments from base to current, stopping at watermark
void marker_scan_stack_segments(ShadowStack* ss, Handle** watermark) {
    StackSegment* seg = ss->base_segment;
    
    while (seg != NULL) {
        Handle** seg_start = (Handle**)&seg->slots[0];
        Handle** seg_end = (Handle**)&seg->slots[STACK_SEGMENT_SLOTS];
        
        // Determine scan limit for this segment
        Handle** scan_limit;
        if (seg == ss->current) {
            // Current segment: stop at watermark
            scan_limit = (watermark < seg_end) ? watermark : seg_end;
        } else {
            // Full segment
            scan_limit = seg_end;
        }
        
        // Scan handles in this segment
        for (Handle** slot = seg_start; slot < scan_limit; slot++) {
            Handle* h = *slot;
            if (h && !marker_is_marked(h->ptr)) {
                marker_set_marked(h->ptr);
                marker_worklist_push(h->ptr);
            }
        }
        
        // Stop if we've reached the segment containing the watermark
        if (watermark >= seg_start && watermark < seg_end) {
            break;
        }
        
        seg = seg->next;
    }
}
```

**Constraints:**
- Use atomic bit operations for mark bitmap
- Support multiple GC worker threads with work stealing
- Handle objects spanning multiple cache lines correctly
- Segment traversal must handle the case where watermark is in any segment

---

### Task 8: Concurrent Relocator

**File:** `src/runtime/gc/relocator.h` and `relocator.c`

```c
// Requirements:
// 1. Copy live objects to new regions
// 2. Update handles using store-release
// 3. Respect watermark constraint

// Implement:
void relocator_init(void);
void relocator_shutdown(void);

// Main relocation entry point
void relocator_run_phase(void);

// Internal functions:
void relocator_process_region(Region* stale_region);
void* relocator_copy_object(void* old_addr, size_t size);
void relocator_update_handle(Handle* h, void* new_addr);

// Handle update with release semantics (critical path):
static inline void relocator_update_handle(Handle* h, void* new_addr) {
    atomic_store_explicit(&h->ptr, new_addr, memory_order_release);
}
```

**Constraints:**
- Only update handles at addresses below the thread's watermark
- Objects in new regions are implicitly live (do not relocate)
- Consider batch copying for cache efficiency

---

### Task 9: GC Thread Main Loop

**File:** `src/runtime/gc/gc_thread.c`

```c
// Requirements:
// 1. Background thread running collection cycles
// 2. Trigger on memory pressure or explicit request
// 3. Coordinate with mutator threads via phase transitions

void* gc_thread_main(void* arg) {
    while (!shutdown_requested) {
        // Wait for trigger condition
        gc_wait_for_trigger();
        
        // Phase 1: Marking
        gc_state_transition(GC_PHASE_OFF, GC_PHASE_MARKING);
        gc_wait_for_all_acknowledgments(GC_PHASE_MARKING);
        marker_run_phase();
        
        // Phase 2: Relocation
        gc_state_transition(GC_PHASE_MARKING, GC_PHASE_RELOCATING);
        gc_wait_for_all_acknowledgments(GC_PHASE_RELOCATING);
        relocator_run_phase();
        
        // Phase 3: Reclamation
        gc_state_transition(GC_PHASE_RELOCATING, GC_PHASE_OFF);
        gc_reclaim_stale_regions();
        
        // Update statistics
        gc_update_stats();
    }
    return NULL;
}

// Implement:
void gc_thread_start(void);
void gc_thread_stop(void);
void gc_trigger_collection(void);  // Explicit trigger
void gc_wait_for_trigger(void);
void gc_wait_for_all_acknowledgments(uint32_t phase);
void gc_reclaim_stale_regions(void);
```

---

### Task 10: LLVM Safepoint Pass

**File:** `src/llvm/safepoint_pass.cpp`

```cpp
// Requirements:
// 1. Insert safepoint check at function entry
// 2. Insert safepoint check at loop backedges
// 3. Generate efficient code (fast path is 2-3 instructions)

#include "llvm/IR/PassManager.h"
#include "llvm/Passes/PassBuilder.h"
#include "llvm/Passes/PassPlugin.h"

class CoexSafepointPass : public llvm::PassInfoMixin<CoexSafepointPass> {
public:
    llvm::PreservedAnalyses run(llvm::Function& F,
                                 llvm::FunctionAnalysisManager& AM);
    
private:
    void insertSafepointAtEntry(llvm::Function& F);
    void insertSafepointAtBackedges(llvm::Function& F);
    llvm::CallInst* createSafepointCall(llvm::IRBuilder<>& Builder);
};

// The safepoint check should generate IR equivalent to:
//
// %phase = load atomic i32, ptr @Global_GC_Phase monotonic
// %my_ack = load i32, ptr @TCB_Phase_Ack
// %synced = icmp eq i32 %phase, %my_ack
// br i1 %synced, label %continue, label %slow_path
//
// slow_path:
//   call void @coex_safepoint_slow_path()
//   br label %continue
//
// continue:
//   ; original function code
```

**Constraints:**
- Must handle functions with `naked` or `no_safepoint` attributes
- Loop backedge detection via LoopInfo analysis
- Consider inlining the fast path, calling slow path function

---

### Task 11: Stress Tests

**File:** `src/tests/stress_test.c`

```c
// Test scenarios to implement:

// 1. Allocation Storm
//    - Multiple threads allocating rapidly
//    - Verify no crashes during GC cycles
//    - Verify no memory leaks

// 2. Stack Segment Growth
//    - Push handles until multiple segments are allocated
//    - Verify segment linking is correct
//    - Verify GC can traverse all segments up to watermark
//    - Verify segment stability (addresses never change)

// 3. Stack Churn Across Segments
//    - Deep recursion crossing segment boundaries
//    - Rapid push/pop during GC
//    - Verify watermark correctness across segments

// 4. Relocation Race
//    - Thread A reading handle continuously
//    - GC relocating the referenced object
//    - Verify no torn reads or stale data

// 5. Unwind During Relocation
//    - Function returns while GC is updating handles
//    - Test unwinding across segment boundaries
//    - Verify no corruption

// 6. Memory Pressure
//    - Allocate until GC triggers
//    - Verify collection reclaims memory
//    - Verify live objects survive

// 7. Segment Boundary Edge Cases
//    - Push exactly 509 handles (fill one segment)
//    - Push 510 handles (cross to second segment)
//    - Pop back to first segment during GC
//    - Verify watermark handling at boundaries

void test_allocation_storm(int num_threads, int allocations_per_thread);
void test_segment_growth(int target_segments);
void test_stack_churn_segments(int depth, int iterations);
void test_relocation_race(int duration_seconds);
void test_unwind_during_relocation(void);
void test_memory_pressure(size_t target_allocation);
void test_segment_boundary_cases(void);
```

---

## Build Configuration

### CMakeLists.txt (root)

```cmake
cmake_minimum_required(VERSION 3.16)
project(coex-gc C CXX)

set(CMAKE_C_STANDARD 11)
set(CMAKE_CXX_STANDARD 17)

# Find LLVM
find_package(LLVM REQUIRED CONFIG)
include_directories(${LLVM_INCLUDE_DIRS})
add_definitions(${LLVM_DEFINITIONS})

# Compiler flags
add_compile_options(-Wall -Wextra -Werror)
add_compile_options(-march=native)  # Enable platform-specific atomics
add_compile_options(-O2)

# Debug build
if(CMAKE_BUILD_TYPE STREQUAL "Debug")
    add_compile_options(-g -fsanitize=thread)
    add_link_options(-fsanitize=thread)
endif()

# Runtime library
add_library(coex_runtime STATIC
    src/runtime/gc/handle.c
    src/runtime/gc/shadow_stack.c
    src/runtime/gc/tcb.c
    src/runtime/gc/tlab.c
    src/runtime/gc/region.c
    src/runtime/gc/gc_state.c
    src/runtime/gc/marker.c
    src/runtime/gc/relocator.c
    src/runtime/gc/gc_thread.c
    src/runtime/allocator/bump_allocator.c
    src/runtime/allocator/region_pool.c
)
target_link_libraries(coex_runtime pthread)

# LLVM pass
add_library(coex_safepoint_pass MODULE
    src/llvm/safepoint_pass.cpp
)
target_link_libraries(coex_safepoint_pass LLVM)

# Tests
enable_testing()
add_executable(test_gc
    src/tests/test_handle.c
    src/tests/test_shadow_stack.c
    src/tests/test_marking.c
    src/tests/test_relocation.c
    src/tests/stress_test.c
)
target_link_libraries(test_gc coex_runtime)
add_test(NAME gc_tests COMMAND test_gc)
```

---

## Implementation Order

1. **Foundation** (Week 1)
   - Handle, ShadowStack, TCB, TLAB structures
   - Basic allocation fast path
   - Thread registration

2. **Region Management** (Week 2)
   - Region pool with mmap
   - TLAB refill logic
   - Epoch tracking

3. **Marking Infrastructure** (Week 3)
   - Mark bitmap
   - Root scanning
   - Object tracing (single-threaded first)

4. **Relocation** (Week 4)
   - Object copying
   - Handle updates with release semantics
   - Watermark constraint enforcement

5. **GC Thread** (Week 5)
   - Phase state machine
   - Acknowledgment waiting
   - Reclamation

6. **LLVM Integration** (Week 6)
   - Safepoint pass
   - Intrinsic definitions
   - Integration tests

7. **Hardening** (Week 7-8)
   - ThreadSanitizer testing
   - Stress tests
   - Performance tuning

---

## Verification Checklist

Before declaring the implementation complete:

- [ ] ThreadSanitizer reports no data races
- [ ] AddressSanitizer reports no memory errors
- [ ] Stress tests pass for 24+ hours
- [ ] Allocation throughput within 10% of malloc baseline
- [ ] GC pause time < 100μs (measured at safepoint check)
- [ ] Memory reclaimed correctly (no leaks under sustained load)
- [ ] Handles updated correctly during relocation (no stale pointers)
- [ ] Unwind-during-relocation test passes
- [ ] Multi-threaded scaling: near-linear up to core count

---

## Notes for Implementation

1. **Memory Ordering is Critical**: The entire design depends on correct use of Release-Acquire semantics. Double-check every atomic operation.

2. **Testing Race Conditions**: Use ThreadSanitizer (`-fsanitize=thread`) during development. It will catch ordering violations that may not manifest as crashes.

3. **Handle Delayed Reuse**: To prevent ABA problems, handles should not be reused for at least 2 epochs after being freed.

4. **TLAB Sizing**: Start with 256KB TLABs. Profile real workloads to tune.

5. **Region Sizing**: 2MB aligns with huge pages. This is a good default but may need adjustment for memory-constrained environments.

6. **GC Trigger Heuristics**: Start with a simple "trigger when 50% of heap is allocated since last GC" policy. Tune based on allocation patterns.

7. **Parallel Marking**: Implement single-threaded marking first. Add work-stealing parallelism once correctness is verified.

8. **Segmented Stack Invariants**: 
   - Each segment is exactly 4KB (one VM page) with 509 handle slots
   - Segments are allocated via `mmap` for page alignment
   - The `prev` pointer must be set BEFORE linking `current->next`
   - Never deallocate or move segments until thread termination
   - GC traverses segments via `prev`/`next` links, stopping at watermark

9. **Segment Growth Pattern**: Reuse existing `next` segments before allocating new ones. This avoids repeated mmap/munmap cycles for oscillating stack depths.

10. **Watermark Across Segments**: The watermark is a raw pointer that may point into any segment. GC must scan all segments from base up to (but not beyond) the watermark address.

---

*End of Implementation Prompt*
