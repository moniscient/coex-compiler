# GC Stack Overflow in Free-List Traversal

## Problem Summary

When creating Lists with more than ~500,000-750,000 elements, the program crashes with a stack overflow during garbage collection's free-list traversal. This is not a limitation of the persistent vector implementation (which now correctly supports arbitrary depths), but rather a bug in the GC's memory management.

## Symptoms

- Programs crash with `EXC_BAD_ACCESS (code=2)` at stack addresses (0x16fxxxxxx range on ARM64 macOS)
- Crash occurs in `coex_gc_find_free_block` or system `malloc`
- Stack trace shows only 5-6 frames (not deep recursion)
- Crash happens during `coex_list_copy` → `coex_gc_alloc` → `coex_gc_find_free_block`

## Reliable Test Cases

### Test 1: Single Large List (Fails ~750k)

```coex
# examples/gc_stress_750k.coex
func main() -> int
    var arr: List<int> = []
    var i: int = 0
    for i in 0..750000
        arr = arr.append(i)
    ~
    print(arr.len())
    print(arr.get(749999))
    return 0
~
```

**Expected:** Should print `750000` and `749999`
**Actual:** Segmentation fault

### Test 2: Multiple Medium Lists (Fails with cumulative allocations)

```coex
# examples/gc_stress_multi.coex
func test_size(_ size: int) -> int
    var arr: List<int> = []
    var i: int = 0
    for i in 0..size
        arr = arr.append(i)
    ~
    return arr.len()
~

func main() -> int
    # Each call creates and discards a large list
    # GC should reclaim memory between calls
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    print(test_size(100000))
    return 0
~
```

**Expected:** Should print `100000` eight times
**Actual:** May crash after several iterations if GC isn't reclaiming properly

### Test 3: Boundary Test (Works at 500k, Fails at 750k)

```coex
# examples/gc_boundary_test.coex
func main() -> int
    var arr: List<int> = []
    var i: int = 0

    # This should work
    for i in 0..500000
        arr = arr.append(i)
    ~
    print(arr.len())

    # Continue to failure point
    for i in 500000..750000
        arr = arr.append(i)
    ~
    print(arr.len())

    return 0
~
```

## Root Cause Analysis

### Hypothesis 1: Free-List Fragmentation

The GC uses a linked-list of free blocks. With many small allocations (each `list_append` creates new List structs, tail buffers, and tree nodes), the free list becomes very long. Traversing this list may cause stack issues.

**Location:** `coex_gc.py` - `_generate_find_free_block()` method (around line 350-450)

### Hypothesis 2: No Actual Garbage Collection Occurring

The GC may not be properly identifying and freeing dead objects. Each append operation:
1. Creates a new List struct
2. Creates a new tail buffer
3. May create/copy tree nodes
4. The OLD list becomes garbage but may not be collected

**Check:** Add instrumentation to `coex_gc_collect()` to log how many objects are freed.

### Hypothesis 3: Stack Allocations in GC Functions

The GC functions themselves may have large stack frames or use recursive patterns that compound with many calls.

**Location:** Check all `alloca` instructions in generated IR for GC functions.

## Relevant Code Locations

### `coex_gc.py`

```python
# Line 19 - Heap size (currently 256MB)
HEAP_SIZE = 256 * 1024 * 1024

# Line ~270 - GC initialization
def _generate_gc_init(self):

# Line ~350 - Free block finder (likely culprit)
def _generate_find_free_block(self):

# Line ~500 - Mark phase
def _generate_gc_mark(self):

# Line ~600 - Sweep phase
def _generate_gc_sweep(self):

# Line ~700 - Collection trigger
def _generate_gc_collect(self):
```

### `codegen.py`

```python
# Line ~3150 - List deep copy (calls gc_alloc heavily)
def _generate_list_deep_copy(self, src, elem_type):

# Line ~1660 - List iteration (used in copy)
# Uses list_get which traverses tree
```

## Troubleshooting Steps

### Step 1: Add GC Instrumentation

Modify `coex_gc.py` to add debug output:

```python
# In _generate_gc_collect():
# Add: printf("GC: collecting, alloc_count=%lld\n", gc_alloc_count)
# Add: printf("GC: freed %lld objects\n", freed_count)
```

### Step 2: Check Free-List Length

Add a function to count free-list nodes and print it periodically:

```python
# New function: coex_gc_free_list_length() -> i64
# Traverse free list and count nodes
# Call this before/after collection
```

### Step 3: Profile Stack Usage

Use `lldb` to check stack pointer at crash:

```bash
lldb ./test_program
(lldb) run
# After crash:
(lldb) register read sp
(lldb) p/x $sp
# Compare to stack base to see how much was used
```

### Step 4: Test with Iterative Free-List Traversal

The current `_generate_find_free_block` may use a pattern that's problematic. Try rewriting to use explicit loops with minimal stack:

```python
# Current might be doing something like:
while current != null:
    # ... check block ...
    current = current.next

# Ensure no stack growth per iteration
```

## Proposed Fixes

### Fix 1: Iterative Free-List with Bounded Stack

Ensure `coex_gc_find_free_block` uses only allocas at function entry, not in loops:

```llvm
define i8* @coex_gc_find_free_block(i64 %size) {
entry:
    ; All allocas here, none in loops
    %current = alloca i8*
    %best = alloca i8*
    ; ...
    br label %loop
loop:
    ; No allocas here!
    ; ...
}
```

### Fix 2: Compacting/Coalescing Free Blocks

After GC sweep, merge adjacent free blocks to reduce list length:

```python
def _generate_gc_coalesce(self):
    """Merge adjacent free blocks to reduce fragmentation"""
    # Walk free list
    # If current.end == next.start, merge them
    # This keeps free list short
```

### Fix 3: Better Collection Triggers

Currently GC only triggers when allocation fails. Consider:
- Trigger GC every N allocations
- Trigger when heap usage exceeds threshold
- Trigger between major operations

### Fix 4: Use Bump Allocator for Short-Lived Objects

For the many temporary List objects created during append chains:
- Use a bump allocator for fast allocation
- Reset entire bump region when safe (e.g., at function boundaries)

## Testing the Fix

After implementing a fix, run these tests in order:

```bash
# 1. Existing test suite (must still pass)
python3 -m pytest tests/ -v --tb=short

# 2. Original stress test (should pass)
python3 coexc.py examples/stress_test_arrays.coex -o stress_test && ./stress_test

# 3. 750k test (currently fails, should pass after fix)
python3 coexc.py examples/gc_stress_750k.coex -o gc_750k && ./gc_750k

# 4. 1M test (stretch goal)
python3 coexc.py examples/gc_stress_1m.coex -o gc_1m && ./gc_1m

# 5. Multi-list test (tests GC reclamation)
python3 coexc.py examples/gc_stress_multi.coex -o gc_multi && ./gc_multi
```

## Success Criteria

1. All 402 existing tests continue to pass
2. Lists of 1,000,000+ elements work without crashing
3. Multiple large list operations in sequence work (GC reclaims memory)
4. No significant performance regression (< 2x slowdown acceptable for correctness)

## Related Files

- `coex_gc.py` - Garbage collector implementation
- `codegen.py` - Code generation including list operations
- `STRESS_TEST_REPORT.md` - Current test results
- `examples/stress_test_arrays.coex` - Working stress test (up to 100k)
