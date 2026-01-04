# Session 6: HAMT Structure for Map

## Context

This is Session 6 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure for List
- Session 5: Persistent Vector mutations

**This Session:**
- Implement Hash Array Mapped Trie (HAMT) structure for Map (structure and read operations)

**Coming Next:**
- Session 7: HAMT Map mutations (set, remove with path copying)

### Why HAMT for Map?

Current Map implementation likely uses a simple hash table. With HAMT:
- Assignment shares the entire structure (O(1))
- Mutation copies only the path to changed entry (O(log n))
- Unchanged subtrees are shared between versions

HAMT is used by Clojure, Scala, and other functional languages for their persistent maps.

### HAMT Structure

HAMT uses hash bits to navigate a trie. Each level consumes 5 bits of the hash (32-way branching):

```
Key: "hello" → hash: 0x7F3A2B1C

Level 0: bits 0-4   = 0x1C = 28  → child[28]
Level 1: bits 5-9   = 0x0B = 11  → child[11]
Level 2: bits 10-14 = 0x0A = 10  → child[10]
... continue until leaf or collision node

                    Root
                   /    \
            [0]...      [28]...
                        /
                    [11]
                    /
                [10] → ("hello", value)
```

### Bitmap Optimization

Full 32-child arrays waste space for sparse nodes. HAMT uses a bitmap:
- 32-bit bitmap indicates which children exist
- Children array only contains present children
- `popcount(bitmap & (1 << i) - 1)` gives index into children array

```
bitmap = 0b00000000_00001000_00000100_00000001
         children present at indices: 0, 10, 28
         children array: [child_0, child_10, child_28] (only 3 elements)
```

## Goals for This Session

1. Write failing tests for Map read operations with HAMT
2. Define HAMT node structures (with bitmap optimization)
3. Implement hash function for keys
4. Implement tree construction from map literals
5. Implement read operations: `get()`, `has()`, `len()`
6. Implement iteration
7. Make all tests pass

**Note:** Mutation operations (set, remove) are Session 7.

## HAMT Node Structure

```
HAMTNode struct:
+----------+----------+----------------------------+
| refcount | bitmap   | entries*                   |
| i64      | i32      | void*                      |
+----------+----------+----------------------------+

- refcount: for structural sharing
- bitmap: 32-bit mask indicating which children exist
- entries: pointer to array of entries (size = popcount(bitmap))

Each entry is either:
- A key-value pair (leaf)
- A pointer to child HAMTNode (internal)

We need to distinguish these. Options:
1. Tagged pointers (low bit = 0 for node, 1 for entry)
2. Separate bitmap for entry types
3. Store entries and nodes in separate arrays

Let's use tagged pointers for simplicity.
```

### Map Structure

```
Map struct:
+----------+----------+----------+----------+
| root*    | len      | key_size | val_size |
| HAMTNode*| i64      | i64      | i64      |
+----------+----------+----------+----------+

- root: pointer to root HAMT node
- len: total key-value pairs
- key_size: size of key type in bytes
- val_size: size of value type in bytes
```

## Test-Driven Development

Write these tests FIRST in `tests/test_hamt_map.py`. They should FAIL initially.

```python
import pytest

class TestHAMTMapRead:
    """Test reading from HAMT Map."""

    def test_map_literal_small(self, expect_output):
        """Small map literal creates proper structure."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "10\n20\n30\n")

    def test_map_len(self, expect_output):
        """len() returns correct count."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    print(m.len())
    empty: Map<int, int> = {}
    print(empty.len())
    return 0
~
''', "3\n0\n")

    def test_map_has(self, expect_output):
        """has() checks key existence."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    if m.has(1)
        print("has 1")
    ~
    if m.has(3)
        print("has 3")
    else
        print("no 3")
    ~
    return 0
~
''', "has 1\nno 3\n")

    def test_map_string_keys(self, expect_output):
        """Map with string keys."""
        expect_output('''
func main() -> int
    m = {"hello": 1, "world": 2, "test": 3}
    print(m.get("hello"))
    print(m.get("world"))
    print(m.has("test"))
    print(m.has("missing"))
    return 0
~
''', "1\n2\ntrue\nfalse\n")

    def test_map_assignment_shares(self, expect_output):
        """Assignment shares structure."""
        expect_output('''
func main() -> int
    a = {1: 10, 2: 20, 3: 30}
    b = a
    c = a
    print(b.get(2))
    print(c.get(2))
    return 0
~
''', "20\n20\n")

    def test_map_iteration(self, expect_output):
        """Can iterate over map keys."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    sum = 0
    for k in m
        sum = sum + m.get(k)
    ~
    print(sum)
    return 0
~
''', "60\n")

    def test_map_medium_size(self, expect_output):
        """Map with many entries (requires multiple levels)."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    for i in 0..100
        m = m.set(i, i * 10)
    ~
    print(m.len())
    print(m.get(0))
    print(m.get(50))
    print(m.get(99))
    return 0
~
''', "100\n0\n500\n990\n")

    def test_empty_map(self, expect_output):
        """Empty map works correctly."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    print(m.len())
    print(m.has(1))
    return 0
~
''', "0\nfalse\n")

    def test_map_string_values(self, expect_output):
        """Map with string values."""
        expect_output('''
func main() -> int
    m = {1: "one", 2: "two", 3: "three"}
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "one\ntwo\nthree\n")

    def test_map_nested(self, expect_output):
        """Nested maps work."""
        expect_output('''
func main() -> int
    inner = {1: 100, 2: 200}
    outer = {"a": inner}
    result = outer.get("a")
    print(result.get(1))
    return 0
~
''', "100\n")
```

## Implementation Steps

### Step 1: Define HAMT Node Structure

```python
# HAMT Node with bitmap optimization
self.hamt_node_struct = ir.global_context.get_identified_type("struct.HAMTNode")
self.hamt_node_struct.set_body(
    ir.IntType(64),  # refcount
    ir.IntType(32),  # bitmap - which children exist
    ir.IntType(32),  # padding for alignment
    ir.IntType(8).as_pointer(),  # entries - array of children/values
)

# Entry types (tagged pointers):
# - If (ptr & 1) == 0: pointer to child HAMTNode
# - If (ptr & 1) == 1: pointer to key-value pair (subtract 1 to get real ptr)
```

### Step 2: Define Map Structure

```python
self.map_struct.set_body(
    self.hamt_node_struct.as_pointer(),  # root
    ir.IntType(64),  # len
    ir.IntType(64),  # key_size
    ir.IntType(64),  # val_size
)
```

### Step 3: Implement Hash Function

Use a good hash function for different key types:

```python
def _hash_key(self, key, key_type):
    """Compute hash for a key value."""
    if key_type == int_type:
        # For integers, use multiply-shift hash
        # hash = (key * 0x9E3779B9) ^ (key >> 16)
        pass
    elif key_type == string_type:
        # For strings, use FNV-1a or similar
        # Iterate over bytes, accumulate hash
        pass
    else:
        # For user types, hash based on fields
        pass
```

### Step 4: Implement Bitmap Operations

```python
def _bitmap_index(self, bitmap, bit_position):
    """Convert bit position to index in children array."""
    # Count bits below this position
    # mask = (1 << bit_position) - 1
    # return popcount(bitmap & mask)
    pass

def _bitmap_has(self, bitmap, bit_position):
    """Check if bitmap has entry at position."""
    return (bitmap >> bit_position) & 1
```

For popcount in LLVM IR:
```python
# LLVM has intrinsic: llvm.ctpop.i32
popcount_fn = self.module.declare_intrinsic('llvm.ctpop', [ir.IntType(32)])
count = builder.call(popcount_fn, [value])
```

### Step 5: Implement get() Operation

```python
def _hamt_get(self, map_ptr, key):
    """Look up value for key in HAMT."""
    hash = compute_hash(key)
    node = map_ptr.root

    level = 0
    while True:
        if node is null:
            return NOT_FOUND

        # Extract 5 bits of hash for this level
        bit_pos = (hash >> (5 * level)) & 0x1F

        if not bitmap_has(node.bitmap, bit_pos):
            return NOT_FOUND

        # Get child at this position
        index = bitmap_index(node.bitmap, bit_pos)
        entry = node.entries[index]

        if is_node(entry):  # tagged pointer check
            node = untag(entry)
            level += 1
        else:
            # It's a key-value pair
            kv = untag(entry)
            if keys_equal(kv.key, key):
                return kv.value
            else:
                return NOT_FOUND  # Hash collision with different key
```

### Step 6: Implement has() Operation

```python
def _hamt_has(self, map_ptr, key):
    """Check if key exists in HAMT."""
    result = _hamt_get(map_ptr, key)
    return result != NOT_FOUND
```

### Step 7: Implement len() Operation

```python
def _hamt_len(self, map_ptr):
    """Return number of key-value pairs."""
    return map_ptr.len
```

### Step 8: Implement Iteration

For iteration, we need to traverse the trie and yield all keys:

```python
def _hamt_iterate(self, map_ptr):
    """Iterate over all keys in HAMT."""
    # Use a stack to traverse the trie
    # For each node, iterate over entries
    # If entry is a node, push to stack
    # If entry is a key-value, yield key
```

### Step 9: Implement Map Literal Construction

```python
def _create_map_from_literal(self, entries):
    """Build HAMT from literal {k1: v1, k2: v2, ...}."""
    # Start with empty map
    map = create_empty_map()

    # Insert each entry
    for key, value in entries:
        map = hamt_set(map, key, value)

    return map
```

Note: `hamt_set` is implemented in Session 7, but we need a basic version for construction.

## Technical Notes

### Hash Distribution

Good hash distribution is critical for HAMT performance. For integers:
```python
# Fibonacci hash (multiply by golden ratio)
hash = key * 0x9E3779B9
hash ^= hash >> 16
```

For strings (FNV-1a):
```python
hash = 2166136261  # FNV offset basis
for byte in string:
    hash ^= byte
    hash *= 16777619  # FNV prime
```

### Collision Handling

When two different keys have the same hash, we need a collision node:
- Store all colliding key-value pairs in a list
- On lookup, linear search through collisions
- Collisions are rare with good hash functions

For now, we can use a simple approach: if there's a collision at the deepest level (after consuming all hash bits), store a list of key-value pairs.

### Tagged Pointers

Use the low bit to distinguish nodes from key-value pairs:
```python
def tag_as_leaf(ptr):
    return ptr | 1

def is_leaf(tagged):
    return tagged & 1

def untag(tagged):
    return tagged & ~1
```

This works because pointers are aligned to at least 2 bytes.

### Memory Layout

```
HAMTNode (variable size based on popcount):
+0:  refcount  (8 bytes)
+8:  bitmap    (4 bytes)
+12: padding   (4 bytes)
+16: entries[] (8 bytes * popcount(bitmap))

Map:
+0:  root*     (8 bytes)
+8:  len       (8 bytes)
+16: key_size  (8 bytes)
+24: val_size  (8 bytes)
```

## Success Criteria

1. All tests in `test_hamt_map.py` pass
2. Map literals create proper HAMT structure
3. `get()` retrieves values correctly
4. `has()` checks existence correctly
5. `len()` returns correct count
6. Assignment shares structure (O(1))
7. Iteration visits all entries
8. All existing tests pass (Sessions 1-5)

## What This Enables

After this session:
- Map uses HAMT structure
- O(1) assignment via structural sharing
- O(log₃₂ n) lookup
- Foundation for O(log₃₂ n) mutations (Session 7)

## Files to Modify

- `codegen.py` - HAMT node types, Map restructure, read operations
- `tests/test_hamt_map.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_hamt_map.py -v --tb=short

# After implementation
python3 -m pytest tests/test_hamt_map.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
