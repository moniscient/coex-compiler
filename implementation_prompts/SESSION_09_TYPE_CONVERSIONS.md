# Session 9: Type Conversions Between Collections

## Context

This is Session 9 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure for List
- Session 5: Persistent Vector mutations
- Session 6: HAMT structure for Map
- Session 7: HAMT Map mutations
- Session 8: HAMT for Set

**This Session:**
- Implement explicit type conversions between collection types
- Define the Zip type for Map ↔ Array conversion

**Coming Next:**
- Session 10: Integration testing and polish

### The Conversion Model

Coex has two tiers of collections:
- **Tree-based (structural sharing):** List, Map, Set
- **Contiguous (COW):** Array, String

Conversion between them is explicit via type annotation:

```coex
list: List<int> = [1, 2, 3]
array: Array<int> = list      # Tree → Contiguous (flatten)
list2: List<int> = array      # Contiguous → Tree (build)

map: Map<string, int> = {"a": 1, "b": 2}
zip: Zip<string, int> = map   # Tree → Paired arrays
map2: Map<string, int> = zip  # Paired arrays → Tree
```

### Conversion Semantics

All conversions produce independent copies with refcount = 1:
- The source is unchanged
- The destination is a new value

This maintains value semantics - conversions don't create aliases.

## Goals for This Session

1. Write failing tests for all conversion operations
2. Define Zip type for Map key-value pairs
3. Implement List ↔ Array conversion
4. Implement Set ↔ Array conversion
5. Implement Map ↔ Zip conversion
6. Make all tests pass

## Zip Type

Zip holds Map data in contiguous form - two parallel arrays:

```
Zip struct:
+----------+----------+----------+----------+----------+----------+
| keys*    | values*  | refcount | len      | key_size | val_size |
| i8*      | i8*      | i64      | i64      | i64      | i64      |
+----------+----------+----------+----------+----------+----------+

- keys: contiguous array of keys
- values: contiguous array of values (parallel to keys)
- refcount: for COW
- len: number of pairs
- key_size, val_size: element sizes
```

Alternative: single array of tuples `Array<(K, V)>`. Choose based on use case:
- Parallel arrays: better for columnar access
- Tuple array: better for iteration, simpler

We'll use parallel arrays for Zip as it's more specialized.

## Test-Driven Development

Write these tests FIRST in `tests/test_conversions.py`. They should FAIL initially.

```python
import pytest

class TestListArrayConversion:
    """Test List ↔ Array conversions."""

    def test_list_to_array(self, expect_output):
        """List converts to Array."""
        expect_output('''
func main() -> int
    list = [1, 2, 3, 4, 5]
    arr: Array<int> = list
    print(arr.len())
    print(arr.get(0))
    print(arr.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_array_to_list(self, expect_output):
        """Array converts to List."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 3, 4, 5]
    list: List<int> = arr
    print(list.len())
    print(list.get(0))
    print(list.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_list_to_array_independence(self, expect_output):
        """Converted Array is independent of source List."""
        expect_output('''
func main() -> int
    list = [1, 2, 3]
    arr: Array<int> = list
    arr.set(0, 99)
    print(list.get(0))
    print(arr.get(0))
    return 0
~
''', "1\n99\n")

    def test_array_to_list_independence(self, expect_output):
        """Converted List is independent of source Array."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 3]
    list: List<int> = arr
    list = list.set(0, 99)
    print(arr.get(0))
    print(list.get(0))
    return 0
~
''', "1\n99\n")

    def test_roundtrip_list_array_list(self, expect_output):
        """List → Array → List preserves data."""
        expect_output('''
func main() -> int
    original = [10, 20, 30, 40]
    arr: Array<int> = original
    final: List<int> = arr
    print(final.len())
    for x in final
        print(x)
    ~
    return 0
~
''', "4\n10\n20\n30\n40\n")

    def test_large_list_to_array(self, expect_output):
        """Large List converts correctly."""
        expect_output('''
func main() -> int
    list: List<int> = []
    for i in 0..100
        list = list.append(i)
    ~
    arr: Array<int> = list
    print(arr.len())
    print(arr.get(0))
    print(arr.get(50))
    print(arr.get(99))
    return 0
~
''', "100\n0\n50\n99\n")

class TestSetArrayConversion:
    """Test Set ↔ Array conversions."""

    def test_set_to_array(self, expect_output):
        """Set converts to Array."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    arr: Array<int> = s
    print(arr.len())
    return 0
~
''', "3\n")

    def test_array_to_set(self, expect_output):
        """Array converts to Set."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 3, 2, 1]
    s: Set<int> = arr
    print(s.len())
    print(s.has(1))
    print(s.has(2))
    print(s.has(3))
    return 0
~
''', "3\ntrue\ntrue\ntrue\n")

    def test_set_to_array_independence(self, expect_output):
        """Converted Array is independent of source Set."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    arr: Array<int> = s
    s = s.add(4)
    print(s.len())
    print(arr.len())
    return 0
~
''', "4\n3\n")

    def test_array_to_set_deduplicates(self, expect_output):
        """Array → Set removes duplicates."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 1, 2, 2, 3, 3, 3]
    s: Set<int> = arr
    print(s.len())
    return 0
~
''', "3\n")

class TestMapZipConversion:
    """Test Map ↔ Zip conversions."""

    def test_map_to_zip(self, expect_output):
        """Map converts to Zip."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    z: Zip<int, int> = m
    print(z.len())
    return 0
~
''', "3\n")

    def test_zip_to_map(self, expect_output):
        """Zip converts to Map."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    z: Zip<int, int> = m
    m2: Map<int, int> = z
    print(m2.len())
    print(m2.get(1))
    print(m2.get(2))
    print(m2.get(3))
    return 0
~
''', "3\n10\n20\n30\n")

    def test_map_to_zip_independence(self, expect_output):
        """Converted Zip is independent of source Map."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    z: Zip<int, int> = m
    m = m.set(3, 30)
    print(m.len())
    print(z.len())
    return 0
~
''', "3\n2\n")

    def test_zip_access(self, expect_output):
        """Zip elements can be accessed."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    z: Zip<int, int> = m
    print(z.key(0))
    print(z.value(0))
    return 0
~
''', "1\n10\n")

    def test_zip_iteration(self, expect_output):
        """Can iterate over Zip."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    z: Zip<int, int> = m
    for i in 0..z.len()
        print(z.key(i))
        print(z.value(i))
    ~
    return 0
~
''', "1\n10\n2\n20\n")

    def test_roundtrip_map_zip_map(self, expect_output):
        """Map → Zip → Map preserves data."""
        expect_output('''
func main() -> int
    original = {"a": 1, "b": 2, "c": 3}
    z: Zip<string, int> = original
    final: Map<string, int> = z
    print(final.len())
    print(final.get("a"))
    print(final.get("b"))
    print(final.get("c"))
    return 0
~
''', "3\n1\n2\n3\n")

class TestStringConversions:
    """Test String-related conversions."""

    def test_string_to_array_bytes(self, expect_output):
        """String converts to Array<byte>."""
        expect_output('''
func main() -> int
    s = "hello"
    arr: Array<byte> = s
    print(arr.len())
    return 0
~
''', "5\n")

    def test_array_bytes_to_string(self, expect_output):
        """Array<byte> converts to String."""
        expect_output('''
func main() -> int
    arr: Array<byte> = [104, 105]
    s: string = arr
    print(s)
    return 0
~
''', "hi\n")
```

## Implementation Steps

### Step 1: Define Zip Type

```python
self.zip_struct = ir.global_context.get_identified_type("struct.Zip")
self.zip_struct.set_body(
    ir.IntType(8).as_pointer(),  # keys (field 0)
    ir.IntType(8).as_pointer(),  # values (field 1)
    ir.IntType(64),  # refcount (field 2)
    ir.IntType(64),  # len (field 3)
    ir.IntType(64),  # key_size (field 4)
    ir.IntType(64),  # val_size (field 5)
)
```

### Step 2: Implement List → Array Conversion

```python
def _list_to_array(self, list_ptr, elem_size):
    """
    Flatten Persistent Vector into contiguous Array.
    """
    len = list_ptr.len

    # Create new Array with capacity = len
    array = create_array(len, elem_size)

    # Iterate through list, copy each element
    i = 0
    for element in iterate_list(list_ptr):
        array_set_raw(array, i, element, elem_size)
        i += 1

    return array
```

### Step 3: Implement Array → List Conversion

```python
def _array_to_list(self, array_ptr, elem_size):
    """
    Build Persistent Vector from contiguous Array.
    """
    len = array_ptr.len

    # Start with empty list
    list = create_empty_list(elem_size)

    # Append each element
    for i in range(len):
        element = array_get(array_ptr, i)
        list = list_append(list, element)

    return list
```

Optimization: Build the tree directly instead of repeated appends.

### Step 4: Implement Set → Array Conversion

```python
def _set_to_array(self, set_ptr, elem_size):
    """
    Flatten Set into Array (order not guaranteed).
    """
    len = set_ptr.len

    array = create_array(len, elem_size)

    i = 0
    for element in iterate_set(set_ptr):
        array_set_raw(array, i, element, elem_size)
        i += 1

    return array
```

### Step 5: Implement Array → Set Conversion

```python
def _array_to_set(self, array_ptr, elem_size):
    """
    Build Set from Array (duplicates removed).
    """
    set = create_empty_set(elem_size)

    for i in range(array_ptr.len):
        element = array_get(array_ptr, i)
        set = set_add(set, element)  # Duplicates ignored

    return set
```

### Step 6: Implement Map → Zip Conversion

```python
def _map_to_zip(self, map_ptr, key_size, val_size):
    """
    Flatten Map into parallel key/value arrays.
    """
    len = map_ptr.len

    # Allocate parallel arrays
    keys = allocate(len * key_size)
    values = allocate(len * val_size)

    # Create Zip struct
    zip = create_zip(keys, values, len, key_size, val_size)

    # Iterate map, copy each pair
    i = 0
    for key, value in iterate_map(map_ptr):
        memcpy(keys + i * key_size, key, key_size)
        memcpy(values + i * val_size, value, val_size)
        i += 1

    return zip
```

### Step 7: Implement Zip → Map Conversion

```python
def _zip_to_map(self, zip_ptr, key_size, val_size):
    """
    Build Map from parallel arrays.
    """
    map = create_empty_map(key_size, val_size)

    for i in range(zip_ptr.len):
        key = zip_ptr.keys + i * key_size
        value = zip_ptr.values + i * val_size
        map = map_set(map, key, value)

    return map
```

### Step 8: Implement Zip Methods

```python
def _zip_len(self, zip_ptr):
    return zip_ptr.len

def _zip_key(self, zip_ptr, index):
    """Get key at index."""
    return zip_ptr.keys + index * zip_ptr.key_size

def _zip_value(self, zip_ptr, index):
    """Get value at index."""
    return zip_ptr.values + index * zip_ptr.val_size
```

### Step 9: Implement COW for Zip

Zip uses the same COW pattern as Array:

```python
def _zip_incref(self, zip_ptr):
    # Atomic increment refcount

def _zip_decref(self, zip_ptr):
    # Atomic decrement, free if zero

def _zip_ensure_unique(self, zip_ptr):
    # Copy if refcount > 1
```

### Step 10: Handle Conversion in Type Checking / Codegen

When assignment has different source and target types:

```python
def _generate_assignment(self, target, source):
    target_type = get_type(target)
    source_type = get_type(source)

    if target_type == source_type:
        # Normal assignment
        ...
    elif is_conversion(source_type, target_type):
        # Generate conversion
        if source_type == List and target_type == Array:
            result = _list_to_array(source, elem_size)
        elif source_type == Array and target_type == List:
            result = _array_to_list(source, elem_size)
        # ... etc
        store(target, result)
    else:
        raise TypeError(...)
```

## Technical Notes

### Conversion Cost

All conversions are O(n):
- Tree → Contiguous: traverse tree, copy elements
- Contiguous → Tree: iterate array, build tree

This is expected and acceptable - conversions are explicit.

### Order Preservation

- List ↔ Array: Order preserved
- Set → Array: Order NOT guaranteed (HAMT traversal order)
- Array → Set: N/A (sets are unordered)
- Map ↔ Zip: Order NOT guaranteed (HAMT traversal order)

### String Conversion Notes

String ↔ Array<byte> conversion:
- String → Array: Returns UTF-8 bytes
- Array → String: Interprets bytes as UTF-8 (may need validation)

### Valid Conversions Table

| From | To | Method |
|------|-----|--------|
| List<T> | Array<T> | Flatten |
| Array<T> | List<T> | Build tree |
| Set<T> | Array<T> | Flatten |
| Array<T> | Set<T> | Deduplicate |
| Map<K,V> | Zip<K,V> | Flatten |
| Zip<K,V> | Map<K,V> | Build HAMT |
| String | Array<byte> | Copy bytes |
| Array<byte> | String | Build string |

## Success Criteria

1. All tests in `test_conversions.py` pass
2. List ↔ Array conversions work correctly
3. Set ↔ Array conversions work correctly
4. Map ↔ Zip conversions work correctly
5. Conversions produce independent values
6. Zip has proper COW semantics
7. All existing tests pass (Sessions 1-8)

## What This Enables

After this session:
- Programmers can convert between tree and contiguous representations
- I/O optimization: read to Array, convert to List for manipulation, convert back for writing
- Complete collection type system

## Files to Modify

- `codegen.py` - Zip type, conversion functions
- `ast_nodes.py` - May need type conversion node
- `tests/test_conversions.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_conversions.py -v --tb=short

# After implementation
python3 -m pytest tests/test_conversions.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
