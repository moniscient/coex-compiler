# Heap Context Implementation for Coex GC

## Background

The Coex garbage collector (`coex_gc.py`) currently uses a single global heap with conservative stack scanning. While functional, this approach has limitations:

1. **Conservative scanning false positives** - Stack values that look like pointers cause over-retention
2. **No concurrency support** - Global heap would require locks under full concurrency
3. **Uniform treatment** - Short-lived loop temporaries treated same as long-lived data

## Current State (as of this session)

### Recent Fixes Applied
1. **Stack overflow fix** - Moved allocas in `List.append()`, `Array.append()`, `List.set()`, `Array.set()` to function entry block using `builder.goto_entry_block()` context manager
2. **Dynamic heap expansion** - Added `gc_expand_heap()` function (though it has issues with non-contiguous segments during sweep)
3. **Configurable heap** - 1GB initial, 8GB max, 100k allocation GC trigger

### Test Results
- All 402 unit tests pass
- 750k elements: Works
- 1M elements: Works
- 2M elements: Works with GC disabled (conservative scanner has false positives at scale)

## Proposed Architecture: Heap Contexts

### Design Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Task Context                             │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ Main Heap   │  │   Nursery   │  │ Large Object│              │
│  │ (long-lived)│  │ (short-lived│  │    Space    │              │
│  │             │  │  loop temps)│  │ (big allocs)│              │
│  │ Precise GC  │  │ Bulk-free   │  │ Individual  │              │
│  │ Root tracked│  │ on scope end│  │ tracking    │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
│         ▲                │                                       │
│         │    promote     │                                       │
│         └────survivors───┘                                       │
└─────────────────────────────────────────────────────────────────┘
```

### Key Insight: Value Semantics Enable Scope-Based Lifetime

In Coex, with value semantics:
```coex
for i in 0..1000000
    arr = arr.append(i)   # Old arr is IMMEDIATELY garbage
~
print(arr.len())          # Only final arr escapes the loop
```

Every intermediate `arr` has a lifetime of exactly one iteration. We don't need GC scanning - we know what survives by analyzing scope.

### Context Types

```python
class HeapContextType(Enum):
    MAIN = 0        # Long-lived objects, precise GC with roots
    NURSERY = 1     # Short-lived temps, bulk-free on scope exit
    LARGE = 2       # Objects > 1MB, separate tracking
    IMMORTAL = 3    # Never freed (string literals, etc.)
```

## Implementation Plan

### Phase 1: Context Infrastructure (~200 lines in coex_gc.py)

#### New Data Structures

```python
# Heap context structure
self.heap_context_type = ir.LiteralStructType([
    self.i8_ptr,    # heap_start
    self.i8_ptr,    # heap_end
    self.i8_ptr,    # free_list_head
    self.i64,       # heap_size
    self.i32,       # context_type (enum)
])

# Global context stack
self.context_stack = None       # HeapContext*[16] - max 16 nested
self.context_stack_top = None   # i32 - current depth
self.current_context = None     # HeapContext* - active context
```

#### New Functions

```python
def _implement_gc_create_context(self):
    """Create a new heap context with given size and type"""
    # gc_create_context(size: i64, type: i32) -> HeapContext*

def _implement_gc_destroy_context(self):
    """Destroy a heap context, freeing all its memory"""
    # gc_destroy_context(ctx: HeapContext*) -> void

def _implement_gc_push_context(self):
    """Push context onto stack, making it active for allocations"""
    # gc_push_context(ctx: HeapContext*) -> void

def _implement_gc_pop_context(self):
    """Pop context from stack, restore previous as active"""
    # gc_pop_context() -> HeapContext*
```

#### Modified gc_alloc

```python
def _implement_gc_alloc(self):
    # Load current_context
    # Allocate from current_context's free list
    # (Same logic as before, but using context's heap bounds)
```

### Phase 2: Loop Nursery (~300 lines in codegen.py)

#### Detection: Which Loops Need Nurseries

```python
def _loop_needs_nursery(self, stmt: ForStmt) -> bool:
    """Detect if loop body has collection mutations that create garbage"""
    # Look for patterns like:
    #   var = var.append(x)
    #   var = var.set(i, x)
    # These create new collections, making old ones garbage
```

#### Loop-Carried Variable Analysis

```python
def _get_loop_carried_vars(self, stmt: ForStmt) -> List[str]:
    """Find variables that are both read and written in loop body"""
    # These are the variables whose final values must survive
```

#### Code Generation with Nursery

```python
def _generate_for_with_nursery(self, stmt: ForStmt):
    # 1. Create nursery context (size estimate based on iteration count if known)
    nursery = self.builder.call(self.gc.gc_create_context, [size, NURSERY_TYPE])

    # 2. Copy loop-carried variables INTO nursery
    #    (deep copy their current values)

    # 3. Push nursery as active context
    self.builder.call(self.gc.gc_push_context, [nursery])

    # 4. Generate loop body (all allocations go to nursery)
    for s in stmt.body:
        self._generate_statement(s)

    # 5. Pop nursery context
    self.builder.call(self.gc.gc_pop_context, [])

    # 6. Copy survivors OUT of nursery to main heap
    #    (only the final values of loop-carried vars)

    # 7. Destroy nursery (bulk free - no scanning!)
    self.builder.call(self.gc.gc_destroy_context, [nursery])
```

### Phase 3: Large Object Space (~150 lines)

```python
def _implement_gc_alloc_large(self):
    """Allocate large objects (>1MB) in separate space"""
    # Use direct malloc, track in linked list
    # Don't use free-list (avoids fragmentation)
```

### Phase 4: Per-Task Contexts (Future - ~200 lines)

When concurrency is implemented:
```python
# Task structure includes its own context stack
task_struct = ir.LiteralStructType([
    # ... other task fields ...
    self.heap_context_type.as_pointer(),  # main_heap
    self.context_stack_type,               # context_stack
    self.i32,                              # context_depth
])
```

## Key Benefits

| Problem | Solution |
|---------|----------|
| Conservative scan false positives | Nursery: no scanning, bulk-free |
| GC pause times | Nursery is small, main heap rarely collected |
| Loop allocation overhead | Nursery: O(1) cleanup vs O(n) GC |
| Concurrency contention | Per-task contexts (future) |
| Large object fragmentation | Separate large object space |

## Files to Modify

1. **coex_gc.py** - Add context infrastructure, modify gc_alloc
2. **codegen.py** - Add nursery detection, modify loop codegen

## Testing Strategy

1. Ensure all 402 existing tests still pass
2. Verify 1M element stress test works with nursery
3. Test 2M elements with GC enabled (should work now)
4. Benchmark: measure allocation throughput improvement

## Implementation Notes

- Start with Phase 1 + Phase 2 (context infra + loop nursery)
- This solves the immediate stress test issues
- Phase 3 + 4 can follow as optimization/concurrency work
- Keep conservative scanner as fallback for main heap (can upgrade to precise later)

## References

- Current GC implementation: `coex_gc.py` (read this first)
- List operations: `codegen.py` lines ~290-1450 (list helpers)
- Loop generation: `codegen.py` `_generate_for()` method
- Method calls with allocas: `codegen.py` `_generate_method_call()` around line 10150
