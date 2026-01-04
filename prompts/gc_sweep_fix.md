# GC Sweep Memory Corruption Fix

## Problem Statement

The garbage collector's sweep phase has a bug where freeing intermediate Map/Set allocations corrupts HAMT data structures. Currently, sweep is disabled (only clears mark bits, doesn't free memory), meaning `gc()` doesn't actually reclaim memory.

## Current Workaround Location

File: `coex_gc.py`, function `_implement_gc_sweep()` (around line 628)

The sweep function currently:
1. Traverses the allocation list
2. Clears mark bits on all objects
3. Does NOT free any memory

## The Bug

When constructing a Map literal like `{1: 10, 2: 20}`:

1. An empty Map is created via `gc_alloc` → gets GC header, added to allocation list
2. `map_set(empty, 1, 10)` creates a NEW Map via `gc_alloc` → also tracked
3. `map_set(result, 2, 20)` creates another NEW Map via `gc_alloc` → also tracked
4. Only the final Map is assigned to the variable and registered in the shadow stack
5. The intermediate Maps (from steps 1-2) are not in shadow stack roots
6. When sweep runs, intermediate Maps are unmarked and get freed
7. **Corruption occurs**: After freeing, `map.get()` returns wrong values even though `map.len()` works

## Key Observations from Debugging

1. `map.len()` works after GC (stored in Map header at offset 8)
2. `map.get()` fails after GC (requires traversing HAMT tree at offset 0)
3. The HAMT root pointer in the surviving Map appears corrupted after sweep
4. HAMT nodes themselves are allocated with `malloc` (not `gc_alloc`), so they don't have GC headers
5. The corruption is NOT from freeing HAMT nodes directly
6. The corruption appears to be from freeing the intermediate Map GC allocations

## Relevant Data Structures

### Map Structure (16 bytes)
```
offset 0: i8* root    - pointer to HAMT root (malloc'd, may be tagged)
offset 8: i64 len     - element count
```

### GC Allocation Header (16 bytes before user data)
```
offset 0: i32 type_id
offset 4: i32 size
offset 8: i32 flags (bit 0 = mark bit)
offset 12: i32 padding
```

### GC Allocation Node (linked list)
```
{ i8* next, i8* data_ptr }
```

## Hypotheses for Root Cause

### Hypothesis 1: HAMT Root Sharing
When `map_set` creates a new Map, the new Map's HAMT root may share structure with the old Map's HAMT root (structural sharing). When the old Map's allocation is freed, something gets corrupted.

**Investigation**: Check `_implement_map_set` in `codegen.py` to see if the new Map's root pointer could be pointing into the old Map's allocation.

### Hypothesis 2: Malloc Metadata Corruption
The GC uses `free()` on the raw allocation (header + data). If the intermediate Map's memory is adjacent to HAMT nodes (also malloc'd), freeing might corrupt malloc's internal bookkeeping, affecting subsequent HAMT lookups.

**Investigation**: Run with memory sanitizer (ASAN) or Valgrind to detect heap corruption.

### Hypothesis 3: Reference Counting Mismatch
The HAMT implementation may have reference counting that expects certain objects to stay alive. Freeing intermediate Maps might decrement refcounts incorrectly.

**Investigation**: Check if HAMT nodes have refcounts and how they're managed.

### Hypothesis 4: Pointer Tagging Interference
HAMT uses pointer tagging (bit 0 = 1 for leaf). If the GC's free path doesn't account for this, it might free tagged pointers incorrectly.

**Investigation**: Check if any GC code handles HAMT root pointers.

## Files to Examine

1. **coex_gc.py** - GC implementation
   - `_implement_gc_sweep()` - the broken sweep logic
   - `_implement_gc_mark_object()` - how objects are marked (mark_map, mark_set blocks)
   - `_register_builtin_types()` - type info for Map/Set

2. **codegen.py** - Code generation
   - `_implement_map_set()` - creates new Map, may share HAMT structure
   - `_implement_hamt_insert()` - HAMT insertion logic
   - `_generate_map_literal()` - how Map literals are constructed
   - Search for `gc_alloc` calls related to Map/Set

3. **tests/test_gc.py** - Test cases
   - `test_gc_with_map` - the minimal failing test

## Potential Solutions

### Solution A: Don't Track Intermediate Maps
Modify `_generate_map_literal` to use a single Map allocation that gets mutated in place (since it's not yet shared). Only register the final Map with GC.

### Solution B: Eager Shadow Stack Registration
Push intermediate Maps onto shadow stack during literal construction, then pop after assignment.

### Solution C: Arena Allocation for Literals
Allocate all intermediate objects for a literal in a temporary arena that's not tracked by GC.

### Solution D: Reference Counting for HAMT Nodes
Add proper reference counting to HAMT nodes so freeing a Map properly decrements refs on shared HAMT structure.

### Solution E: Delay GC During Literal Construction
Set a flag during literal construction that prevents GC from running until complete.

## Minimal Test Case

```coex
func main() -> int
    var m: Map<int, int> = {1: 10, 2: 20}
    gc()
    print(m.get(1))  # Should print 10, but prints 0 or crashes
    return 0
~
```

## Debugging Approach

1. Add debug prints in sweep to log what's being freed
2. Add debug prints in map_get to log the HAMT root pointer before/after GC
3. Compare HAMT root pointer values - is it the same pointer but corrupted data?
4. Use ASAN/Valgrind to detect memory errors
5. Single-step through sweep in a debugger

## Success Criteria

1. `test_gc_with_map` passes with actual memory freeing enabled
2. All 415+ existing tests still pass
3. Memory is actually reclaimed (can verify with a stress test that allocates/frees in a loop)
4. No memory leaks or corruption detected by sanitizers

## Commands

```bash
# Run GC tests
python3 -m pytest tests/test_gc.py -v --tb=short

# Run full test suite
python3 -m pytest tests/ -v --tb=short

# Run with specific test
python3 -m pytest tests/test_gc.py::TestGarbageCollector::test_gc_with_map -v --tb=long
```
