# Universal Tagged Values Design

## Overview

Replace raw value storage with self-describing tagged values throughout the runtime. Every stored value carries its type, enabling the GC to trace references correctly without depending on compile-time type inference.

## Core Data Structure

```c
struct TaggedValue {
    int64_t type_id;   // Runtime type identifier
    int64_t value;     // Raw value OR handle (depending on type_id)
};
```

**Size**: 16 bytes per value (vs current 8 bytes)

### Value Encoding

| Coex Type | type_id | value field |
|-----------|---------|-------------|
| `int` | TYPE_INT (1) | Raw i64 value |
| `float` | TYPE_FLOAT (2) | f64 bitcast to i64 |
| `bool` | TYPE_BOOL (3) | 0 or 1 |
| `byte` | TYPE_BYTE (4) | 0-255 |
| `char` | TYPE_CHAR (5) | Unicode codepoint |
| `string` | TYPE_STRING (6) | GC handle |
| `List<T>` | TYPE_LIST (7) | GC handle |
| `Map<K,V>` | TYPE_MAP (8) | GC handle |
| `Set<T>` | TYPE_SET (9) | GC handle |
| `Array<T>` | TYPE_ARRAY (10) | GC handle |
| `json` (null) | TYPE_JSON_NULL (11) | 0 |
| `json` (bool) | TYPE_JSON_BOOL (12) | 0 or 1 |
| `json` (int) | TYPE_JSON_INT (13) | Raw i64 |
| `json` (float) | TYPE_JSON_FLOAT (14) | f64 bitcast |
| `json` (string) | TYPE_JSON_STRING (15) | GC handle to String |
| `json` (array) | TYPE_JSON_ARRAY (16) | GC handle to List |
| `json` (object) | TYPE_JSON_OBJECT (17) | GC handle to Map |
| `Channel<T>` | TYPE_CHANNEL (18) | GC handle |
| `Tuple` | TYPE_TUPLE (19) | GC handle (heap-allocated tuple) |
| User type `Foo` | TYPE_USER_BASE + id | GC handle |

### Heap Type Check

```c
static inline bool is_heap_type(int64_t type_id) {
    return type_id >= TYPE_STRING;  // All types >= 6 are heap-allocated
}
```

---

## Phase 1: Tagged Collection Elements

### 1.1 List Changes

**Current List struct:**
```c
struct List {
    int64_t root_handle;   // PV tree root
    int64_t len;           // Element count
    int64_t depth;         // Tree depth
    int64_t tail_handle;   // Tail buffer handle
    int64_t elem_size;     // Bytes per element (currently 8)
    int64_t flags;         // LIST_FLAG_ELEM_IS_REF, etc.
};
```

**New List struct:**
```c
struct List {
    int64_t root_handle;   // PV tree root
    int64_t len;           // Element count
    int64_t depth;         // Tree depth
    int64_t tail_handle;   // Tail buffer handle
    int64_t elem_size;     // ALWAYS 16 (sizeof(TaggedValue))
    int64_t flags;         // Simplified - no longer need ELEM_IS_REF
};
```

**Key change**: `elem_size` is always 16. The `flags` field no longer needs `LIST_FLAG_ELEM_IS_REF` because the GC reads the type_id from each element.

### 1.2 List Operations

**list_new:**
```python
def list_new():
    # elem_size is always 16 (TaggedValue)
    # No flags needed for element type
    return allocate_list(elem_size=16, flags=0)
```

**list_append:**
```python
def list_append(list_ptr, tagged_value):
    # tagged_value is {type_id, value}
    # Copy 16 bytes into tail buffer
    new_list = pv_append(list_ptr, &tagged_value, 16)
    return new_list
```

**list_get:**
```python
def list_get(list_ptr, index) -> TaggedValue:
    # Returns full TaggedValue, caller extracts what they need
    elem_ptr = pv_get(list_ptr, index)
    return load_tagged_value(elem_ptr)
```

### 1.3 Codegen for List Operations

**List literal `[1, 2, 3]`:**
```python
def generate_list_expr(elements):
    list_ptr = call list_new()
    for elem in elements:
        # Generate the element value
        value = generate_expression(elem)
        # Determine type_id from compile-time type (or infer)
        type_id = get_type_id(elem)
        # Create TaggedValue on stack
        tv = alloca TaggedValue
        store {type_id, value} to tv
        # Append
        list_ptr = call list_append(list_ptr, tv)
    return list_ptr
```

**List access `list.get(0)`:**
```python
def generate_list_get(list_expr, index_expr):
    list_ptr = generate_expression(list_expr)
    index = generate_expression(index_expr)

    # Get TaggedValue
    tv = call list_get(list_ptr, index)

    # Extract value based on expected type (from context)
    # For now, just return the value field
    # Type checking can be added later
    return extract_value(tv, 1)  # field 1 = value
```

### 1.4 Map Changes

**Current approach**: Keys and values stored as raw i64, flags indicate if they're pointers.

**New approach**: Keys and values are TaggedValue.

```c
struct MapEntry {
    TaggedValue key;    // 16 bytes
    TaggedValue value;  // 16 bytes
    // ... HAMT bookkeeping
};
```

**map_set:**
```python
def map_set(map_ptr, key_tv, value_tv):
    # Both key and value are TaggedValue
    # HAMT stores them directly
    return hamt_set(map_ptr, key_tv, value_tv)
```

**map_get:**
```python
def map_get(map_ptr, key_tv) -> TaggedValue:
    return hamt_get(map_ptr, key_tv)
```

### 1.5 Set Changes

Similar to Map, but only stores keys:

```c
struct SetEntry {
    TaggedValue element;  // 16 bytes
    // ... HAMT bookkeeping
};
```

### 1.6 Array Changes

**Current Array struct:**
```c
struct Array {
    int64_t handle;      // Data buffer handle
    int64_t ndim;        // Dimensions
    int64_t shape[4];    // Shape
    int64_t strides[4];  // Strides
    int64_t offset;      // View offset
    int64_t elem_size;   // Element size
    int64_t type_id;     // Element type
};
```

**New Array struct:**
```c
struct Array {
    int64_t handle;      // Data buffer handle
    int64_t ndim;        // Dimensions
    int64_t shape[4];    // Shape
    int64_t strides[4];  // Strides (in ELEMENTS, not bytes)
    int64_t offset;      // View offset (in ELEMENTS)
    int64_t elem_size;   // ALWAYS 16 (TaggedValue)
    // type_id field removed - each element is self-describing
};
```

---

## Phase 2: GC Marking

### 2.1 New Marking Strategy

The GC no longer needs special cases for different collection types. All collection elements are TaggedValue:

```python
def gc_mark_tagged_value(tv: TaggedValue):
    """Mark a single tagged value if it's a heap type."""
    type_id = tv.type_id
    if type_id >= TYPE_STRING:  # All heap types
        handle = tv.value
        gc_mark_object(handle)

def gc_mark_collection_elements(data_ptr, count):
    """Mark all elements in a collection's data buffer."""
    for i in range(count):
        tv_ptr = data_ptr + i * 16
        tv = load_tagged_value(tv_ptr)
        gc_mark_tagged_value(tv)
```

### 2.2 Simplified Type Switch

**Current gc_mark_object (complex):**
```python
switch (type_id):
    case TYPE_LIST:        mark_list_special_case()
    case TYPE_LIST_TAIL:   skip()
    case TYPE_LIST_TAIL_REF: mark_list_tail_ref_special_case()
    case TYPE_MAP:         mark_map_special_case()
    case TYPE_SET:         mark_set_special_case()
    case TYPE_ARRAY:       mark_array_special_case()
    case TYPE_ARRAY_DATA_REF: mark_array_data_ref_special_case()
    case TYPE_JSON_STRING: mark_json_string()
    case TYPE_JSON_ARRAY:  mark_json_array()
    case TYPE_JSON_OBJECT: mark_json_object()
    case TYPE_PV_NODE:     mark_pv_node_special_case()
    # ... many more cases
```

**New gc_mark_object (simple):**
```python
switch (type_id):
    case TYPE_LIST:
        mark_list_struct_fields(obj)    # root, tail handles
        mark_collection_elements(get_tail_data(obj), get_tail_count(obj))

    case TYPE_MAP:
        mark_hamt_tree(obj.root)  # HAMT nodes contain TaggedValue

    case TYPE_SET:
        mark_hamt_tree(obj.root)

    case TYPE_ARRAY:
        mark_collection_elements(get_array_data(obj), get_array_len(obj))

    case TYPE_STRING:
        # String data buffer is bytes, nothing to mark
        pass

    case TYPE_PV_NODE:
        # Internal nodes: children are handles to more PV_NODEs
        # Leaf nodes: children are TaggedValue elements
        mark_pv_node_children(obj)

    case TYPE_HAMT_NODE:
        # Children are either HAMT_NODEs or leaf entries (TaggedValue pairs)
        mark_hamt_node_children(obj)

    default:
        if type_id >= TYPE_USER_BASE:
            mark_user_type_fields(obj, type_id)
```

### 2.3 Remove Special Cases

These type IDs are no longer needed:
- `TYPE_LIST_TAIL` - tail buffers now contain TaggedValue, marked uniformly
- `TYPE_LIST_TAIL_REF` - same as above
- `TYPE_ARRAY_DATA` - array buffers contain TaggedValue
- `TYPE_ARRAY_DATA_REF` - same as above

The `LIST_FLAG_ELEM_IS_REF` flag is no longer needed.

---

## Phase 3: Shadow Stack Simplification (Optional)

### 3.1 Current Shadow Stack

```python
# Currently: slots are i64 handles, must track which vars are heap types
gc_push_frame(num_heap_vars)
for i, var in enumerate(heap_vars):
    gc_set_root(i, handle_for(var))
```

This requires compile-time knowledge of which variables are heap types.

### 3.2 Tagged Shadow Stack (Future)

```python
# New: all locals stored as TaggedValue, GC checks type at runtime
gc_push_frame(num_all_vars)
for i, var in enumerate(all_vars):
    gc_set_root_tagged(i, tagged_value_for(var))

def gc_scan_shadow_stack():
    for frame in shadow_stack:
        for slot in frame.slots:
            tv = load_tagged_value(slot)
            gc_mark_tagged_value(tv)
```

**Benefits:**
- No compile-time type inference needed for GC correctness
- All variables automatically tracked
- Fixes BUG-078 (JSON not rooted) permanently

**Trade-off:**
- More shadow stack slots (all locals, not just heap types)
- But modern systems have plenty of stack space

---

## Phase 4: Runtime Type Checking (Optional)

With tagged values, we can add optional runtime type checks:

```python
def list_get_int(list_ptr, index) -> int64:
    tv = list_get(list_ptr, index)
    if tv.type_id != TYPE_INT:
        runtime_error("Expected int, got type %d", tv.type_id)
    return tv.value

def list_get_string(list_ptr, index) -> String*:
    tv = list_get(list_ptr, index)
    if tv.type_id != TYPE_STRING:
        runtime_error("Expected string, got type %d", tv.type_id)
    return gc_handle_deref(tv.value)
```

This catches type mismatches at runtime rather than silently corrupting data.

---

## Implementation Order

### Step 1: Define TaggedValue type and constants
- Add `tagged_value_type` to GC module
- Renumber type IDs with primitives < TYPE_STRING
- Add `is_heap_type(type_id)` helper

### Step 2: Update List implementation
- Change `elem_size` to always be 16
- Update `list_new`, `list_append`, `list_get`, `list_set`
- Update PV node storage for TaggedValue elements
- Remove `LIST_FLAG_ELEM_IS_REF`

### Step 3: Update List codegen
- Wrap element values in TaggedValue before append
- Unwrap TaggedValue after get
- Update list literal generation

### Step 4: Update GC marking for Lists
- New `mark_tagged_value` function
- Simplify `mark_list` to use uniform element marking
- Remove `TYPE_LIST_TAIL_REF` special case

### Step 5: Update Map/Set implementation
- Store keys and values as TaggedValue
- Update HAMT node structure
- Update all Map/Set operations

### Step 6: Update Array implementation
- Store elements as TaggedValue
- Update `array_new`, `array_get`, `array_set`
- Remove `TYPE_ARRAY_DATA_REF`

### Step 7: Update JSON implementation
- JSON is already a tagged union internally
- Align JSON type IDs with the unified scheme
- JSON arrays/objects use the same TaggedValue storage

### Step 8: Clean up
- Remove obsolete type IDs and flags
- Simplify GC marking code
- Update tests

### Step 9 (Optional): Tagged shadow stack
- Store all locals as TaggedValue
- Simplify shadow stack allocation
- Remove dependence on compile-time heap type detection

---

## Migration Strategy

### Backward Compatibility

During migration, we can support both formats:
1. Check if `elem_size == 16` → new format (TaggedValue)
2. Check if `elem_size == 8` → old format (raw values)

This allows incremental migration and easier debugging.

### Testing Strategy

1. **Unit tests**: Each collection operation with various types
2. **GC stress tests**: Deeply nested collections, force GC between operations
3. **Type mixing**: Lists containing different JSON types
4. **Regression tests**: All existing tests should pass

---

## Performance Considerations

### Memory
- 2x storage per collection element
- Acceptable trade-off for correctness and simplicity

### Speed
- Extra field access for type_id (minimal)
- Simplified GC marking (may be faster due to fewer branches)
- No hash computation changes (key comparison unchanged)

### Code Size
- Simpler GC code (fewer special cases)
- More uniform collection code

---

## Resolved Bugs

This design permanently fixes:

| Bug | How Fixed |
|-----|-----------|
| BUG-075: Deep nested lists | GC reads type_id from each element, traces correctly at any depth |
| BUG-076: List<json> not traced | JSON elements carry TYPE_JSON_*, GC marks them |
| BUG-077: Array<string> issues | Array elements are TaggedValue, uniform handling |
| BUG-078: JSON not rooted | (With Phase 3) All locals tracked, no type inference needed |
| Future nesting bugs | Self-describing values eliminate entire bug class |

---

## Example: List<List<json>>

```coex
outer: List<List<json>> = [[{a: 1}, {b: 2}], [{c: 3}]]
```

**Memory layout:**

```
outer (List):
  root_handle → PV tree
  len = 2
  tail_handle → [
    TaggedValue { TYPE_LIST, handle_to_inner1 },
    TaggedValue { TYPE_LIST, handle_to_inner2 }
  ]

inner1 (List):
  tail_handle → [
    TaggedValue { TYPE_JSON_OBJECT, handle_to_json1 },
    TaggedValue { TYPE_JSON_OBJECT, handle_to_json2 }
  ]

inner2 (List):
  tail_handle → [
    TaggedValue { TYPE_JSON_OBJECT, handle_to_json3 }
  ]

json1, json2, json3 (Map via JSON object):
  ... HAMT with TaggedValue keys/values
```

**GC marking:**

1. Mark `outer` handle (from shadow stack)
2. Load outer's tail buffer, iterate elements
3. Element 0: type_id=TYPE_LIST → mark handle_to_inner1
4. Element 1: type_id=TYPE_LIST → mark handle_to_inner2
5. Mark inner1: iterate its elements
6. Element 0: type_id=TYPE_JSON_OBJECT → mark handle_to_json1
7. ... and so on

**No special cases. No type inference required. Correct at any depth.**
