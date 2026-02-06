# Collection Handle Conversion: Map, Set, and List Compaction Support

## Problem Statement

The Coex GC uses a handle-based architecture where all heap-allocated values are accessed through uniform i64 handles into a global handle table. This design enables compaction without mutating references—the GC simply updates the handle table entry when moving an object.

**Current inconsistency:** Maps, Sets, and Lists store pointer-type keys/values as **raw pointers cast to i64**, not as handles. This breaks the compaction invariant and causes GC failures:

```
After compaction:
- Object moves from address 0x1000 to address 0x2000
- Handle table entry is updated: handle_table[42] = 0x2000
- BUT: Collection still contains 0x1000 (raw pointer) → DANGLING POINTER
```

### Evidence: Failing CI Tests

Two tests are failing on Linux CI that demonstrate this issue:

**Test 1: `test_value_semantics_survive_gc`** - 14 of 20 JSON values corrupted after GC
```coex
func main() -> int
    base: json = { value: 42 }
    results: List<json> = []
    for i in 0..20
        modified: json = base.set("value", i)
        results = results.append(modified)
        if i % 5 == 0
            gc()
        ~
    ~
    # 14 values are corrupted after GC cycles
~
```

**Test 2: `test_no_handles_after_gc_cycle`** - Segfault after GC with nested JSON
```coex
func main() -> int
    j: json = { users: [{ name: "Alice" }, { name: "Bob" }] }
    gc()
    # CRASH - dangling pointers in JSON's internal Map
~
```

### Root Cause Analysis

**Lists have a store/read mismatch:**
- **Store** (`codegen/core.py:3155-3184`): Raw pointers are stored via memcpy
- **Read** (`codegen/expressions.py:912-919`): Code expects handles and calls `gc_handle_deref`

```python
# Read code assumes handles are stored:
handle = cg.builder.load(handle_ptr)  # Loads raw pointer, thinks it's a handle
ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [handle])  # FAILS: uses pointer as table index!
```

**Maps/Sets store raw pointers:**
- `json.set()` stores JSON values as `ptrtoint(json_ptr)` in the Map
- `gc_mark_hamt` tries to trace via `gc_ptr_to_handle`, which may fail for freed objects

## Goal

Convert Map, Set, and List to store handles instead of raw pointers for key/value/element types that are heap references. This makes the entire collection system compaction-ready and fixes the GC survival bugs.

## Architecture Summary

### Current (Broken for Compaction)

```
HAMTLeaf: { i64 hash, i64 key, i64 value }
         where key/value are raw pointers cast to i64

Map.get() → inttoptr(value_i64, T*)     // Direct pointer recovery
gc_mark_hamt() → gc_ptr_to_handle(ptr)  // Must convert ptr→handle to mark
```

### Target (Compaction-Ready)

```
HAMTLeaf: { i64 hash, i64 key, i64 value }
         where key/value are HANDLES (i64 indices)

Map.get() → gc_handle_deref(value_handle)  // Dereference handle
gc_mark_hamt() → gc_mark_object(handle)    // Direct handle marking
```

## Files to Modify

| File | Changes |
|------|---------|
| `codegen/hamt.py` | Core HAMT operations, map/set helpers |
| `codegen/list.py` | List element storage (reference types) |
| `codegen/expressions.py` | Map/Set/List literal generation, method calls |
| `codegen/core.py` | Map.get/Set.has/List.append method dispatch |
| `coex_gc.py` | `gc_mark_hamt` implementation, list element tracing |

## Detailed Changes

### Phase 1: Update `hamt_leaf_new` to Accept Handles

**File:** `codegen/hamt.py`, `_implement_hamt_leaf_new`

Currently stores raw values. Add a flag parameter or create handle-aware variants:

```python
# Current signature:
# hamt_leaf_new(hash: i64, key: i64, value: i64) -> HAMTLeaf*

# The key/value are already i64. The change is at CALL SITES:
# - Callers must pass handles, not raw pointers
# - No change to leaf_new itself, but document that key/value are handles
```

### Phase 2: Update `map_set` / `map_set_string` to Store Handles

**File:** `codegen/hamt.py`, `_implement_map_set` (~line 1650)

When storing a pointer-type value:
1. Check if value is a pointer (from flags or type)
2. If pointer: convert to handle via `gc_ptr_to_handle`
3. Store the handle (i64) in the leaf

```python
# Before:
value_i64 = builder.ptrtoint(value_ptr, i64)
builder.call(hamt_insert, [..., value_i64, ...])

# After:
if value_is_ptr:
    value_handle = builder.call(gc_ptr_to_handle, [value_ptr_as_i8])
    builder.call(hamt_insert, [..., value_handle, ...])
else:
    builder.call(hamt_insert, [..., value_i64, ...])
```

**Same change needed for:**
- `_implement_map_set_string` (~line 2200)
- `_implement_set_add` (~line 2550)
- `_implement_set_add_string` (~line 2650)

### Phase 3: Update `map_get` / `map_get_string` to Dereference Handles

**File:** `codegen/hamt.py`, `_implement_map_get` (~line 1750)

When retrieving a pointer-type value:
1. Load the handle (i64) from the leaf
2. If value is pointer type: call `gc_handle_deref` to get actual pointer
3. Return the pointer

```python
# Before (in codegen/core.py:3124-3127):
if isinstance(value_llvm_type, ir.PointerType):
    return self.builder.inttoptr(result, value_llvm_type)

# After:
if isinstance(value_llvm_type, ir.PointerType):
    ptr_i8 = self.builder.call(self.gc.gc_handle_deref, [result])
    return self.builder.bitcast(ptr_i8, value_llvm_type)
```

**Same change needed for:**
- `_implement_map_get_string` (~line 2317)
- Set element retrieval in iterations

### Phase 4: Update `gc_mark_hamt` to Mark Handles Directly

**File:** `coex_gc.py`, `_implement_gc_mark_hamt` (~line 2572)

Currently converts pointer to handle before marking:
```python
# Current (lines 2667-2668):
key_handle = builder.call(self.gc_ptr_to_handle, [key_as_ptr])
builder.call(self.gc_mark_object, [key_handle])
```

After conversion, values are already handles:
```python
# After:
key_handle = builder.load(key_ptr_ptr)  # Already a handle
# Validate handle is non-zero before marking
with builder.if_then(builder.icmp_unsigned("!=", key_handle, ir.Constant(i64, 0))):
    builder.call(self.gc_mark_object, [key_handle])
```

**Apply same change for value marking (lines 2686-2687).**

### Phase 5: Update Map/Set Literal Generation

**File:** `codegen/expressions.py`, `generate_map` (~line 494)

When generating map literals with pointer values:

```python
# Current (line 527):
value_i64 = cg._cast_value(value, ir.IntType(64))

# After - for pointer types, get handle:
if isinstance(value.type, ir.PointerType):
    value_i8 = cg.builder.bitcast(value, ir.IntType(8).as_pointer())
    value_i64 = cg.builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
else:
    value_i64 = cg._cast_value(value, ir.IntType(64))
```

**Same for:**
- `generate_set` (~line 533) for pointer elements
- String key handling (already passes String* which needs handle conversion)

### Phase 6: Update Method Call Dispatch

**File:** `codegen/core.py`, `_generate_method_call`

**Map.get with string keys** (~line 3044):
```python
# Current:
result = self.builder.call(self.map_get_string, [obj, key_arg])
if isinstance(value_llvm_type, ir.PointerType):
    return self.builder.inttoptr(result, value_llvm_type)

# After:
result = self.builder.call(self.map_get_string, [obj, key_arg])
if isinstance(value_llvm_type, ir.PointerType):
    ptr_i8 = self.builder.call(self.gc.gc_handle_deref, [result])
    return self.builder.bitcast(ptr_i8, value_llvm_type)
```

**Map.get with non-string keys** (~line 3117-3128): Same pattern.

### Phase 7: Fix List Storage of Reference Types

**Critical Bug:** Lists currently have a store/read mismatch for reference types.

#### Phase 7a: Update `list.append` to Store Handles

**File:** `codegen/core.py`, `_generate_method_call`, `append` handling (~line 3150)

Currently stores raw pointer:
```python
# Current (line 3176-3184):
temp = self.builder.alloca(elem_type, name="append_elem")
self.builder.store(elem_val, temp)  # Stores raw pointer
temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())
return self.builder.call(self.list_append, [obj, temp_ptr, elem_size])
```

For reference types, convert to handle before storing:
```python
# After:
if cg._is_reference_type(elem_coex_type):
    # Convert pointer to handle
    elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
    elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
    # Store handle (i64) instead of pointer
    temp = self.builder.alloca(ir.IntType(64), name="append_elem_handle")
    self.builder.store(elem_handle, temp)
    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())
    elem_size = ir.Constant(ir.IntType(64), 8)  # Handle is always 8 bytes
else:
    # Non-reference types: store value directly (existing code)
    temp = self.builder.alloca(elem_type, name="append_elem")
    self.builder.store(elem_val, temp)
    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())
return self.builder.call(self.list_append, [obj, temp_ptr, elem_size])
```

#### Phase 7b: Update List Literal Generation

**File:** `codegen/expressions.py`, `generate_list` (~line 441)

Same pattern - for reference type elements, convert to handle before storing:
```python
# Current (line 483-490):
temp = cg.builder.alloca(elem_type, name=f"list_elem_{i}")
cg.builder.store(elem_val, temp)
temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
list_ptr = cg.builder.call(cg.list_append, [list_ptr, temp_ptr, elem_size])

# After - for reference types:
if is_reference_type:
    elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
    elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
    temp = cg.builder.alloca(ir.IntType(64), name=f"list_elem_{i}")
    cg.builder.store(elem_handle, temp)
    temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
    elem_size = ir.Constant(ir.IntType(64), 8)
```

#### Phase 7c: Verify List Read Code (Already Correct)

**File:** `codegen/expressions.py`, `generate_index_expr` (~line 912-919)

The read code already expects handles and calls `gc_handle_deref`. Once the store code is fixed to store handles, reads will work correctly:

```python
# This code is already correct - no changes needed:
if elem_coex_type is not None and cg._is_reference_type(elem_coex_type):
    handle_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
    handle = cg.builder.load(handle_ptr)
    ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [handle])
    return cg.builder.bitcast(ptr_i8, elem_llvm_type)
```

#### Phase 7d: Update List GC Tracing

**File:** `coex_gc.py`, `_implement_gc_mark_object`, list marking (~line 3006-3024)

Currently, list marking only marks the root and tail nodes, not the elements inside. For lists containing reference types, we need to trace the element handles.

**Option A (Simpler):** Since elements are now handles, and handles point to GC-tracked objects, the existing mark phase will mark them when they're used as roots elsewhere.

**Option B (More Complete):** Add explicit element tracing in the list marking code:
```python
# In mark_list block, after marking root and tail:
# Iterate through elements and mark any that are handles to reference types
# This requires knowing the element type, which may need to be stored in the List struct
```

For now, Option A should suffice because:
1. List elements (handles) are stored in the list's data buffer
2. The data buffer is marked (TYPE_LIST_TAIL)
3. When the program accesses elements, it dereferences handles which keeps objects alive
4. The root variables (List itself) keep the handles reachable

## Test Cases

### Test 1: Basic Map with Pointer Values (Already Passing)
```coex
func main() -> int
    inner = {1: 100, 2: 200}
    outer = {"a": inner}
    result = outer.get("a")
    print(result.get(1))
    return 0
~
```
Expected: `100`

### Test 2: Map Survives GC (Critical New Test)
```coex
func main() -> int
    # Create map with string values
    m = {1: "one", 2: "two", 3: "three"}

    # Force GC
    gc()

    # Values should still be accessible
    print(m.get(1))
    print(m.get(2))
    return 0
~
```
Expected: `one\ntwo\n`

### Test 3: Nested Maps Survive GC
```coex
func main() -> int
    inner = {"x": 10, "y": 20}
    outer = {"data": inner}

    gc()
    gc()  # Multiple cycles

    data = outer.get("data")
    print(data.get("x"))
    return 0
~
```
Expected: `10`

### Test 4: Set with String Elements Survives GC
```coex
func main() -> int
    s = {"alpha", "beta", "gamma"}
    gc()
    print(s.has("beta"))
    return 0
~
```
Expected: `true`

### Test 5: Map Values Are Handles (Verification Test)
```coex
func main() -> int
    # This test verifies internal handle storage
    # Create map, get value, verify it works after GC
    strings = ["a", "b", "c"]
    m = {0: strings}

    gc()

    retrieved = m.get(0)
    print(retrieved.len())
    return 0
~
```
Expected: `3`

### Test 6: List<json> Survives GC (Critical - Currently Failing)
```coex
func main() -> int
    base: json = { value: 42 }
    results: List<json> = []

    for i in 0..20
        modified: json = base.set("value", i)
        results = results.append(modified)

        if i % 5 == 0
            gc()
        ~
    ~

    # Verify all values survived GC
    errors = 0
    for i in 0..20
        if results.get(i).get("value").as_int() != i
            errors = errors + 1
        ~
    ~

    print(errors)
    return 0
~
```
Expected: `0`

### Test 7: List<string> Survives GC
```coex
func main() -> int
    names: List<string> = []
    names = names.append("Alice")
    names = names.append("Bob")
    names = names.append("Charlie")

    gc()
    gc()

    print(names.get(0))
    print(names.get(1))
    print(names.get(2))
    return 0
~
```
Expected: `Alice\nBob\nCharlie\n`

### Test 8: Nested JSON in List Survives GC (Critical - Currently Crashing)
```coex
func main() -> int
    j: json = { users: [{ name: "Alice" }, { name: "Bob" }] }

    gc()

    s: string = j.stringify()
    parsed: json = json.parse(s)

    users: json = parsed.get("users")
    u0: json = users[0]
    u1: json = users[1]
    print(u0.get("name").as_string())
    print(u1.get("name").as_string())
    return 0
~
```
Expected: `Alice\nBob\n`

## Stress Tests

### Stress Test 1: Large Map with GC Pressure
```python
def test_large_map_gc_stress(self, expect_output):
    """Large map survives multiple GC cycles."""
    expect_output('''
func main() -> int
    m = {}
    i = 0
    while i < 10000
        key = String.from(i)
        m = m.set(key, i * 2)
        i = i + 1
    ~

    gc()
    gc()
    gc()

    print(m.len())
    print(m.get("5000"))
    return 0
~
''', "10000\n10000\n")
```

### Stress Test 2: Nested Collections with GC
```python
def test_nested_collections_gc(self, expect_output):
    """Deeply nested collections survive GC."""
    expect_output('''
func main() -> int
    # Create nested structure
    level3 = [1, 2, 3]
    level2 = {"data": level3}
    level1 = {"nested": level2}
    root = {"root": level1}

    # Force multiple GC cycles
    i = 0
    while i < 10
        gc()
        i = i + 1
    ~

    # Navigate to deepest level
    l1 = root.get("root")
    l2 = l1.get("nested")
    l3 = l2.get("data")
    print(l3.get(1))
    return 0
~
''', "2\n")
```

## Implementation Order

### Part A: Fix Lists (Highest Priority - Fixes Failing CI Tests)

1. **Phase 7a (list.append):** Update `_generate_method_call` append handling to convert pointers to handles for reference types.

2. **Phase 7b (list literals):** Update `generate_list` to store handles for reference types.

3. **Run List GC tests** - Tests 6, 7, 8 should now pass.

### Part B: Fix Maps/Sets (Compaction Readiness)

4. **Phase 4 (gc_mark_hamt):** Update GC marking to expect handles. This is backward-compatible if we also handle the case where values might still be raw pointers during transition.

5. **Phase 2 (map_set/set_add):** Update storage to use handles. After this, new entries use handles.

6. **Phase 3 (map_get):** Update retrieval to dereference handles. Must be done together with Phase 2.

7. **Phase 5 (literal generation):** Update expression codegen for maps/sets.

8. **Phase 6 (method dispatch):** Update core.py method handling.

9. **Run all existing tests** to ensure no regressions.

10. **Add new GC survival tests** from above.

## Verification

After implementation:

1. All existing map/set tests pass
2. New GC survival tests pass
3. `gc_dump_heap()` shows maps with handle references, not raw pointers
4. No segfaults under GC pressure with pointer-type map values

## Notes

### String Keys Are Special
String keys use `map_set_string`/`map_get_string` which hash the string content. The String* pointer itself needs to be stored as a handle so the string survives GC.

### Flags Field
The `flags` field in Map/Set struct (bit 0 = key is ptr, bit 1 = value is ptr) remains useful for:
- Determining whether to call `gc_handle_deref` on retrieval
- GC knowing which leaf fields need marking

### Backward Compatibility
During the transition, `gc_mark_hamt` could check if a value looks like a handle (small integer) vs a pointer (large address) and handle both cases. This is fragile and should only be temporary.

### Performance Impact
- **Storage:** One extra call to `gc_ptr_to_handle` per pointer value stored
- **Retrieval:** One extra call to `gc_handle_deref` per pointer value retrieved
- These are simple table lookups, negligible compared to HAMT traversal

## Success Criteria

1. **CI Tests Pass:** `test_value_semantics_survive_gc` and `test_no_handles_after_gc_cycle` pass
2. Lists with reference-type elements survive garbage collection
3. Maps and Sets with pointer-type keys/values survive garbage collection
4. Compaction (when implemented) will work correctly for all collections
5. No performance regression in collection benchmarks
6. All existing tests continue to pass

## Priority

**HIGH** - Two CI tests are currently failing on Linux:
- `tests/stress/test_value_semantics_stress.py::TestGCInteractionStress::test_value_semantics_survive_gc`
- `tests/test_json_no_handles.py::TestJsonNoHandlesInOutput::test_no_handles_after_gc_cycle`

The List fix (Phase 7) should be implemented first to restore CI to green.

---

## CLAUDE.md Invariant Analysis

### Current Documentation

CLAUDE.md describes the handle-based GC design (lines 77-110):

```markdown
The GC uses a **handle-based** design where all heap references are i64 indices
into a global handle table, rather than raw pointers. This enables concurrent
collection without stop-the-world pointer fixup.
```

And documents the key functions:
- `gc_alloc(size, type_id) -> i64`: Allocate object, **return handle**
- `gc_handle_deref(handle) -> i8*`: Get pointer from handle
- `gc_ptr_to_handle(ptr) -> i64`: Recover handle from object's forward field

### Missing Invariant

**CLAUDE.md lacks a clear invariant stating that all inter-object references on the Coex heap must use handles, never raw pointers.**

The current documentation describes the handle system but doesn't mandate its use. This allowed the bugs we're fixing to exist—Maps, Sets, and Lists were implemented storing raw pointers instead of handles, violating the implicit design intent.

### Proposed Invariant for CLAUDE.md

Add the following to the "Garbage Collector Architecture" section:

```markdown
### Handle-Only Reference Invariant

**INVARIANT**: All references between GC-managed objects MUST be stored as i64 handles,
never as raw pointers. This invariant is fundamental to the GC's correctness.

**Why this matters:**
1. **Compaction**: When the GC moves an object, it updates the handle table entry.
   Raw pointers would become dangling.
2. **Tracing**: The GC traces object graphs by following handles. Raw pointers stored
   in objects cannot be traced without type-specific knowledge.
3. **Consistency**: `gc_ptr_to_handle()` only works for objects that were allocated
   via `gc_alloc()` and still exist. Using it on freed memory returns garbage.

**Applies to:**
- Collection elements: List<T>, Map<K,V>, Set<T> where T/K/V are reference types
- UDT fields that are reference types
- Any internal pointer within a heap-allocated structure

**Exceptions:**
- JSON values store data inline (deep-copied), not as references to other GC objects
- Arena-allocated objects (FLAG_ARENA) are not tracked by GC and are bulk-freed
- Stack allocations (alloca) are not GC-managed

**Implementation pattern:**
```python
# WRONG - stores raw pointer
value_i64 = builder.ptrtoint(value_ptr, i64)
store(value_i64, destination)

# CORRECT - stores handle
value_i8 = builder.bitcast(value_ptr, i8_ptr)
value_handle = builder.call(gc_ptr_to_handle, [value_i8])
store(value_handle, destination)

# On retrieval:
handle = load(source)
ptr_i8 = builder.call(gc_handle_deref, [handle])
value_ptr = builder.bitcast(ptr_i8, expected_type)
```
```

### Why This Invariant Was Violated

The bugs exist because:

1. **Implicit assumption**: The handle design was documented but not framed as a mandatory invariant
2. **Working coincidence**: Without compaction, raw pointers happen to work until GC frees the target
3. **Inconsistent patterns**: Some code (List read path) expected handles while other code (List write path) stored pointers
4. **Missing enforcement**: No compile-time or runtime check validates that stored references are handles

### Recommendation

After fixing the bugs in this prompt:

1. **Update CLAUDE.md** with the proposed invariant
2. **Add a debug mode** in GC that validates stored values look like handles (small integers) rather than pointers (large addresses)
3. **Document the pattern** in code comments where handles are stored/retrieved
