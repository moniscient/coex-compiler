# Implementing Slice Views for Coex Strings and Arrays

## Overview

Coex needs zero-copy slice views for String and Array types. Currently, slicing operations copy data into new allocations. The new design allows slices to share the underlying data buffer with their parent, controlled by the assignment operator used.

## Design Summary

**Assignment operator semantics for slices:**
- `=` (copy assignment): Creates an independent copy with its own data buffer
- `:=` (move assignment): Preserves the view, sharing the parent's data buffer

**Key principle:** The `=` operator is the safe default that always produces independent values. The `:=` operator is "expert mode" for programmers who understand that slice views keep parent buffers alive.

## Part 1: Update Descriptor Layouts

### Current String Layout (24 bytes)
```
struct.String {
    i8*  data    // pointer to UTF-8 bytes
    i64  len     // codepoint count  
    i64  size    // byte count
}
```

### New String Layout (32 bytes)
```
struct.String {
    i8*  owner   // pointer to data buffer (GC-allocated)
    i64  offset  // byte offset into owner's data
    i64  len     // codepoint count
    i64  size    // byte size of this string's extent
}
```

### Current Array Layout (32 bytes)
```
struct.Array {
    i8*  data      // pointer to elements
    i64  len       // element count
    i64  cap       // capacity
    i64  elem_size // element size in bytes
}
```

### New Array Layout (40 bytes)
```
struct.Array {
    i8*  owner     // pointer to data buffer (GC-allocated)
    i64  offset    // byte offset into owner's data
    i64  len       // element count
    i64  cap       // capacity (equals len for slices)
    i64  elem_size // element size in bytes
}
```

### Implementation Tasks

1. **Update `_create_string_type()` in codegen.py:**
   - Change `string_struct` to have 4 fields: owner, offset, len, size
   - Update struct size from 24 to 32 bytes in all allocation calls
   - Update all GEP indices throughout the file (field numbers shift)

2. **Update `_create_array_helpers()` in codegen.py:**
   - Change `array_struct` to have 5 fields: owner, offset, len, cap, elem_size
   - Update struct size from 32 to 40 bytes in all allocation calls
   - Update all GEP indices throughout the file

3. **Update all string helper functions:**
   - `string_new`: Set owner to the allocated data buffer, offset to 0
   - `string_from_literal`: Same pattern
   - `string_len`: Still reads from len field (now field 2)
   - `string_get`: Compute data pointer as `owner + offset`, then index
   - `string_data`: Return `owner + offset` instead of just loading data field
   - `string_slice`: This is the key function—see Part 2
   - `string_concat`: Allocate new buffer, set owner to it, offset to 0
   - All other string functions that access data must compute `owner + offset`

4. **Update all array helper functions similarly.**

## Part 2: Implement Slice View Creation

### How Slicing Works: getrange vs setrange

The slice expression `obj[start:end]` calls `getrange()`, which creates a view. The decision between view and copy happens at assignment time, not slice time:

```
text[0:100]                    # Calls string_getrange → returns view descriptor
var line := text[0:100]        # := preserves the view
var line = text[0:100]         # = calls string_deep_copy on the view
```

The `setrange` operation (slice assignment `text[0:100] = replacement`) is different. It always creates a fresh string/array because it combines parts of multiple sources:
- Prefix from original: `[0:start]`
- Middle from replacement
- Suffix from original: `[end:]`

There's no single contiguous buffer to view into, so `setrange` always allocates new data with `offset=0`. This is the correct behavior.

### String Slice (View Creation)

The `string_slice` function should create a view, not a copy. Modify `_implement_string_slice()`:

```
Current behavior:
1. Extract bytes [start:end] from source
2. Allocate new data buffer
3. Copy bytes into new buffer
4. Create new String struct pointing to new buffer

New behavior:
1. Create new String struct (32 bytes)
2. Set owner = source.owner (share the same buffer)
3. Set offset = source.offset + start
4. Set len = count codepoints in range (still needed for UTF-8)
5. Set size = end - start (byte size of slice)
6. Return the new descriptor (NO data copy)
```

Implementation:
```python
def _implement_string_slice(self):
    """Create a slice VIEW that shares the parent's data buffer."""
    func = self.string_slice
    func.args[0].name = "s"
    func.args[1].name = "start"
    func.args[2].name = "end"
    
    entry = func.append_basic_block("entry")
    builder = ir.IRBuilder(entry)
    
    s = func.args[0]
    start = func.args[1]
    end = func.args[2]
    
    # Load source fields
    owner_ptr = builder.gep(s, [i32(0), i32(0)], inbounds=True)
    source_owner = builder.load(owner_ptr)
    
    offset_ptr = builder.gep(s, [i32(0), i32(1)], inbounds=True)
    source_offset = builder.load(offset_ptr)
    
    size_ptr = builder.gep(s, [i32(0), i32(3)], inbounds=True)
    source_size = builder.load(size_ptr)
    
    # Clamp start and end to valid range
    # ... (existing clamping logic)
    
    # Calculate new offset and size
    new_offset = builder.add(source_offset, start_clamped)
    new_size = builder.sub(end_clamped, start_clamped)
    
    # Count codepoints in the slice range
    # ... (existing UTF-8 counting loop, but operating on owner+new_offset)
    
    # Allocate new String descriptor (32 bytes)
    struct_size = ir.Constant(i64, 32)
    type_id = ir.Constant(i32, self.gc.TYPE_STRING)
    raw_ptr = builder.call(self.gc.gc_alloc, [struct_size, type_id])
    string_ptr = builder.bitcast(raw_ptr, self.string_struct.as_pointer())
    
    # Store fields - SHARE the owner, don't allocate new data
    new_owner_ptr = builder.gep(string_ptr, [i32(0), i32(0)], inbounds=True)
    builder.store(source_owner, new_owner_ptr)  # Same owner!
    
    new_offset_ptr = builder.gep(string_ptr, [i32(0), i32(1)], inbounds=True)
    builder.store(new_offset, new_offset_ptr)
    
    new_len_ptr = builder.gep(string_ptr, [i32(0), i32(2)], inbounds=True)
    builder.store(final_char_count, new_len_ptr)
    
    new_size_ptr = builder.gep(string_ptr, [i32(0), i32(3)], inbounds=True)
    builder.store(new_size, new_size_ptr)
    
    builder.ret(string_ptr)
```

### Array Slice (View Creation)

Similarly modify array slicing to create views:

```
New behavior:
1. Create new Array struct (40 bytes)
2. Set owner = source.owner
3. Set offset = source.offset + (start * elem_size)
4. Set len = end - start
5. Set cap = len (slices have no extra capacity)
6. Set elem_size = source.elem_size
7. Return the new descriptor (NO data copy)
```

## Part 3: Implement Deep Copy for = Operator

Create new functions that perform actual data copying:

### `string_deep_copy(s: String*) -> String*`

```
1. Allocate new String descriptor (32 bytes)
2. Compute source data size from s.size
3. Allocate new data buffer (s.size bytes)
4. Copy bytes from (s.owner + s.offset) to new buffer
5. Set new descriptor: owner=new_buffer, offset=0, len=s.len, size=s.size
6. Return new descriptor
```

### `array_deep_copy(a: Array*) -> Array*`

```
1. Allocate new Array descriptor (40 bytes)
2. Compute source data size: a.len * a.elem_size
3. Allocate new data buffer
4. Copy bytes from (a.owner + a.offset) to new buffer
5. Set new descriptor: owner=new_buffer, offset=0, len=a.len, cap=a.len, elem_size=a.elem_size
6. Return new descriptor
```

### Add function declarations in `_create_string_type()`:

```python
# string_deep_copy(s: String*) -> String* (creates independent copy)
string_deep_copy_ty = ir.FunctionType(string_ptr, [string_ptr])
self.string_deep_copy = ir.Function(self.module, string_deep_copy_ty, name="coex_string_deep_copy")
```

### Add function declarations in `_create_array_helpers()`:

```python
# array_deep_copy(a: Array*) -> Array* (creates independent copy)
array_deep_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
self.array_deep_copy = ir.Function(self.module, array_deep_copy_ty, name="coex_array_deep_copy")
```

## Part 4: Update Assignment Operator Handling

### In `_generate_deep_copy()`:

When the type is a String or Array, call the appropriate deep copy function:

```python
def _generate_deep_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
    """Generate code to deep-copy a value based on its Coex type."""
    
    if isinstance(coex_type, NamedType) and coex_type.name == "string":
        return self.builder.call(self.string_deep_copy, [value])
    
    if isinstance(coex_type, ArrayType):
        return self.builder.call(self.array_deep_copy, [value])
    
    # ... existing logic for other types
```

### In `_generate_move_or_eager_copy()`:

For `:=` operator, strings and arrays should just pass through (preserving views):

```python
def _generate_move_or_eager_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
    """Generate code for := (move/eager assign) semantics.
    
    For strings and arrays, this preserves slice views.
    """
    # Strings and arrays: just return the value (preserve view)
    if isinstance(coex_type, NamedType) and coex_type.name == "string":
        return value
    
    if isinstance(coex_type, ArrayType):
        return value
    
    # ... existing logic for other types
    return value
```

## Part 5: Update Garbage Collection

### In `coex_gc.py`, update `_implement_gc_mark_object()`:

The marking logic for TYPE_STRING must trace the `owner` pointer:

```python
# In the mark_string block:
builder.position_at_end(mark_string)

# String struct: { i8* owner, i64 offset, i64 len, i64 size }
# We need to mark the owner (field 0)
string_struct_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64, self.i64])
string_typed = builder.bitcast(ptr, string_struct_type.as_pointer())

owner_ptr_ptr = builder.gep(string_typed, [i32(0), i32(0)], inbounds=True)
owner_ptr = builder.load(owner_ptr_ptr)

# Mark the owner buffer
builder.call(self.gc_mark_object, [owner_ptr])
builder.branch(done)
```

Similarly for TYPE_ARRAY:

```python
# In the mark_array block:
builder.position_at_end(mark_array)

# Array struct: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }
array_struct_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64, self.i64, self.i64])
array_typed = builder.bitcast(ptr, array_struct_type.as_pointer())

owner_ptr_ptr = builder.gep(array_typed, [i32(0), i32(0)], inbounds=True)
owner_ptr = builder.load(owner_ptr_ptr)

# Mark the owner buffer
builder.call(self.gc_mark_object, [owner_ptr])

# If array contains pointers, also mark elements
# ... (existing element marking logic, but compute data_ptr as owner + offset)
builder.branch(done)
```

### Key GC Invariant

The `owner` field is the only pointer in the descriptor that references heap memory. The `offset` field is just an integer. During GC:
- Mark phase: Trace `owner` to keep the data buffer alive
- Sweep phase: If a descriptor is unreachable, it gets collected; if all descriptors referencing a buffer are collected, the buffer becomes unreachable and gets collected
- Compaction: When a data buffer moves, update `owner` in all descriptors pointing to it; `offset` remains unchanged

## Part 6: Update Data Access Patterns

Every location that reads string or array data must compute the actual data pointer:

```python
# OLD pattern (direct data field):
data_ptr_ptr = builder.gep(string_ptr, [i32(0), i32(0)], inbounds=True)
data_ptr = builder.load(data_ptr_ptr)
byte_ptr = builder.gep(data_ptr, [index])

# NEW pattern (owner + offset):
owner_ptr = builder.gep(string_ptr, [i32(0), i32(0)], inbounds=True)
owner = builder.load(owner_ptr)
offset_ptr = builder.gep(string_ptr, [i32(0), i32(1)], inbounds=True)
offset = builder.load(offset_ptr)
base_ptr = builder.gep(owner, [offset])
byte_ptr = builder.gep(base_ptr, [index])
```

Functions that need this update include:
- `string_get` - byte access
- `string_data` - return data pointer
- `string_print` - printing
- `string_eq` - comparison
- `string_contains` - substring search
- `string_concat` - reading source data (but result has offset=0)
- `string_setrange` - reading source data (result has offset=0)
- `array_get` - element access
- `array_set` - element modification (creates copy, so result has offset=0)
- Any iteration over string/array contents

### Updating setrange for New Layout

The `string_setrange` and `array_setrange` functions read from potentially-view sources but always produce fresh allocations. They need updating in two ways:

1. **Reading from source strings/arrays**: Must compute `owner + offset` for both the original and the replacement:

```python
# OLD: Reading original string data
orig_data_ptr_ptr = builder.gep(s, [i32(0), i32(0)], inbounds=True)
orig_data = builder.load(orig_data_ptr_ptr)

# NEW: Compute actual data pointer
orig_owner_ptr = builder.gep(s, [i32(0), i32(0)], inbounds=True)
orig_owner = builder.load(orig_owner_ptr)
orig_offset_ptr = builder.gep(s, [i32(0), i32(1)], inbounds=True)
orig_offset = builder.load(orig_offset_ptr)
orig_data = builder.gep(orig_owner, [orig_offset])

# Same for source/replacement string
source_owner_ptr = builder.gep(source, [i32(0), i32(0)], inbounds=True)
source_owner = builder.load(source_owner_ptr)
source_offset_ptr = builder.gep(source, [i32(0), i32(1)], inbounds=True)  
source_offset = builder.load(source_offset_ptr)
source_data = builder.gep(source_owner, [source_offset])
```

2. **Writing the result**: The result is a fresh allocation, so set `owner` to the new buffer and `offset` to 0:

```python
# Allocate result descriptor
result_ptr = ...  # allocate 32 bytes for String

# Store owner (the new data buffer)
result_owner_ptr = builder.gep(result_ptr, [i32(0), i32(0)], inbounds=True)
builder.store(new_data_buffer, result_owner_ptr)

# Store offset = 0 (fresh allocation, not a view)
result_offset_ptr = builder.gep(result_ptr, [i32(0), i32(1)], inbounds=True)
builder.store(ir.Constant(i64, 0), result_offset_ptr)

# Store len and size as before (fields 2 and 3 now)
```

## Part 7: Nested Slice Handling

When slicing a slice, flatten to the root owner:

```python
# In string_slice:
# source.owner is already the root buffer (not an intermediate descriptor)
# new.owner = source.owner (same buffer)
# new.offset = source.offset + slice_start (cumulative offset)
```

This happens automatically with the implementation above because:
1. A fresh string has `owner` pointing to its buffer and `offset = 0`
2. A slice has `owner` pointing to the same buffer and `offset = parent.offset + start`
3. A slice of a slice has `owner` pointing to the same buffer and `offset = parent.offset + start` (which is already cumulative)

No special handling needed—the math works out.

## Part 8: Testing Strategy

### Basic slice view tests:
```coex
func test_slice_view() -> int
    var text = "Hello, World!"
    var slice := text[0:5]      # view
    print(slice)                 # Should print "Hello"
    return 0
~
```

### Copy vs view tests:
```coex
func test_copy_vs_view() -> int
    var text = "Hello, World!"
    var view := text[0:5]       # view (shares buffer)
    var copy = text[0:5]        # copy (independent)
    # Both should print "Hello"
    print(view)
    print(copy)
    return 0
~
```

### Nested slice tests:
```coex
func test_nested_slice() -> int
    var text = "Hello, World!"
    var first := text[0:7]      # "Hello, "
    var second := first[0:5]    # "Hello"
    print(second)
    return 0
~
```

### Lifetime tests (requires GC verification):
```coex
func get_slice() -> string
    var huge = create_large_string()  # Allocate big buffer
    var small := huge[0:10]           # View into it
    return small                       # huge goes out of scope
    # Buffer should stay alive because small references it
~

func test_lifetime() -> int
    var result = get_slice()
    print(result)  # Should work, buffer still alive
    return 0
~
```

### Array slice tests:
```coex
func test_array_slice() -> int
    var arr: Array<int> = [1, 2, 3, 4, 5]
    var slice := arr[1:4]       # view of [2, 3, 4]
    print(slice.len())          # Should print 3
    print(slice.get(0))         # Should print 2
    return 0
~
```

## Implementation Order

1. **Update struct layouts** - Change string_struct and array_struct field counts and sizes
2. **Fix all GEP indices** - Search for all uses of these structs and update field indices
3. **Update string creation** - string_new, string_from_literal set owner and offset correctly
4. **Update array creation** - array_new, array_from_literal set owner and offset correctly
5. **Update data access** - All functions that read data compute owner + offset
6. **Implement slice view creation** - string_slice and array_slice create views
7. **Implement deep copy functions** - string_deep_copy and array_deep_copy
8. **Update assignment handling** - _generate_deep_copy calls appropriate copy function
9. **Update GC marking** - Trace owner pointer for strings and arrays
10. **Test thoroughly** - Run existing tests, add new slice-specific tests

## Files to Modify

- `codegen.py`: Struct definitions, all string/array helper functions, assignment handling
- `coex_gc.py`: Marking logic for TYPE_STRING and TYPE_ARRAY
- `tests/test_*.py`: Add slice view tests

## Potential Pitfalls

1. **GEP index off-by-one**: Double-check all field indices after adding offset field
2. **Forgetting owner+offset**: Every data access must use the computed pointer
3. **Allocation sizes**: Update all hardcoded 24/32 byte sizes to 32/40
4. **UTF-8 codepoint counting**: Still needed for len field, operates on owner+offset
5. **Existing string_copy/array_copy**: May need renaming or removal if replaced by deep_copy
