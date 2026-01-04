# Session 4: Persistent Vector Structure for List

## Context

This is Session 4 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment

**This Session:**
- Implement the Persistent Vector data structure for List (structure and read operations)

**Coming Next:**
- Session 5: Persistent Vector mutations (append, set with path copying)

### Why Persistent Vector for List?

The current List implementation is a contiguous array - same as Array. This means every "mutation" copies the entire list, which is O(n).

Persistent Vector (Clojure-style) is a tree structure that enables **structural sharing**:
- Assignment shares the entire tree (O(1))
- Mutation copies only the path from root to changed node (O(log n))
- Unchanged subtrees are shared between old and new versions

### Persistent Vector Structure

A 32-way branching trie indexed by position:

```
                    Root (depth 2)
                   /    |    \
                Node   Node   Node     <- 32 children each
               / | \  / | \  / | \
              L  L  L L  L  L L  L  L   <- Leaf nodes (32 elements each)

Index bits determine path:
  Index 0-31:    [0-31]           (first node, direct)
  Index 32-63:   [1][0-31]        (second node, then position)
  Index 1000:    [31][8]          (path through tree)
```

For a tree with branching factor 32:
- Depth 1: up to 32 elements
- Depth 2: up to 1,024 elements
- Depth 3: up to 32,768 elements
- Depth 7: up to 34 billion elements

Access is O(log₃₂ n), which is at most 7 operations for any practical size.

## Goals for This Session

1. Write failing tests for List read operations with new structure
2. Define the Persistent Vector node structures
3. Implement tree construction from list literals
4. Implement read operations: `get()`, `len()`
5. Implement iteration over the tree
6. Make all tests pass

**Note:** Mutation operations (append, set) are Session 5. This session focuses on building and reading the structure.

## New List Structure

```
List struct:
+----------+----------+----------+----------+
| root*    | len      | depth    | tail*    |
| Node*    | i64      | i32      | i8*      |
+----------+----------+----------+----------+

- root: pointer to root node (or null for empty/small lists)
- len: total element count
- depth: tree depth (0 = tail only, 1 = one level, etc.)
- tail: pointer to rightmost leaf (optimization for fast append)

Node struct:
+----------+-----------------------------------+
| refcount | children[32]                      |
| i64      | void*[32]                         |
+----------+-----------------------------------+

- refcount: for structural sharing
- children: 32 pointers to child nodes or elements
```

### The Tail Optimization

Clojure's persistent vector keeps the rightmost partial node (the "tail") separately. This makes append O(1) in most cases:
- If tail has room: just add to tail
- If tail full: push tail into tree, create new tail

The tail is a simple array, not a node.

## Test-Driven Development

Write these tests FIRST in `tests/test_persistent_vector.py`. They should FAIL initially.

```python
import pytest

class TestPersistentVectorRead:
    """Test reading from Persistent Vector (List)."""

    def test_list_literal_small(self, expect_output):
        """Small list literal creates proper structure."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    print(a.get(0))
    print(a.get(2))
    print(a.get(4))
    return 0
~
''', "1\n3\n5\n")

    def test_list_len(self, expect_output):
        """len() returns correct count."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    print(a.len())
    b = [10, 20]
    print(b.len())
    c: List<int> = []
    print(c.len())
    return 0
~
''', "5\n2\n0\n")

    def test_list_get_all_elements(self, expect_output):
        """Can access all elements by index."""
        expect_output('''
func main() -> int
    a = [10, 20, 30, 40, 50]
    i = 0
    for i in 0..5
        print(a.get(i))
    ~
    return 0
~
''', "10\n20\n30\n40\n50\n")

    def test_list_iteration(self, expect_output):
        """Can iterate over list with for loop."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    sum = 0
    for x in a
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "15\n")

    def test_list_medium_size(self, expect_output):
        """List with more than 32 elements (requires tree)."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..100
        a = a.append(i)
    ~
    print(a.len())
    print(a.get(0))
    print(a.get(50))
    print(a.get(99))
    return 0
~
''', "100\n0\n50\n99\n")

    def test_list_assignment_shares(self, expect_output):
        """Assignment shares structure (structural sharing)."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a
    c = a
    print(b.get(2))
    print(c.get(2))
    return 0
~
''', "3\n3\n")

    def test_list_of_strings(self, expect_output):
        """List of strings works correctly."""
        expect_output('''
func main() -> int
    a = ["hello", "world", "test"]
    print(a.get(0))
    print(a.get(1))
    print(a.len())
    return 0
~
''', "hello\nworld\n3\n")

    def test_list_nested(self, expect_output):
        """Nested lists work correctly."""
        expect_output('''
func main() -> int
    inner1 = [1, 2, 3]
    inner2 = [4, 5, 6]
    outer = [inner1, inner2]
    print(outer.len())
    first = outer.get(0)
    print(first.get(0))
    return 0
~
''', "2\n1\n")

    def test_empty_list(self, expect_output):
        """Empty list works correctly."""
        expect_output('''
func main() -> int
    a: List<int> = []
    print(a.len())
    return 0
~
''', "0\n")

    def test_single_element(self, expect_output):
        """Single element list works."""
        expect_output('''
func main() -> int
    a = [42]
    print(a.get(0))
    print(a.len())
    return 0
~
''', "42\n1\n")

    def test_list_large(self, expect_output):
        """Large list requiring multiple tree levels."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..1000
        a = a.append(i)
    ~
    print(a.len())
    print(a.get(0))
    print(a.get(500))
    print(a.get(999))
    return 0
~
''', "1000\n0\n500\n999\n")
```

## Implementation Steps

### Step 1: Define Node Structure

In `codegen.py`, define the node structure:

```python
# Persistent Vector Node
# struct PVNode { i64 refcount, void* children[32] }
self.pv_node_struct = ir.global_context.get_identified_type("struct.PVNode")
self.pv_node_struct.set_body(
    ir.IntType(64),  # refcount
    ir.ArrayType(ir.IntType(8).as_pointer(), 32)  # children[32]
)
```

### Step 2: Redefine List Structure

Replace current List struct:

```python
# Old: struct List { i64 len, i64 cap, i64 elem_size, i8* data }
# New: struct List { PVNode* root, i64 len, i32 depth, i8* tail, i32 tail_len, i64 elem_size }

self.list_struct.set_body(
    self.pv_node_struct.as_pointer(),  # root (field 0)
    ir.IntType(64),   # len - total element count (field 1)
    ir.IntType(32),   # depth - tree depth (field 2)
    ir.IntType(8).as_pointer(),  # tail - rightmost leaf array (field 3)
    ir.IntType(32),   # tail_len - elements in tail (field 4)
    ir.IntType(64),   # elem_size (field 5)
)
```

### Step 3: Implement List Construction from Literal

When creating a list from a literal `[1, 2, 3, ...]`:

```python
def _create_list_from_literal(self, elements, elem_size):
    n = len(elements)
    if n <= 32:
        # Small list: all elements go in tail, no tree
        # root = null, depth = 0, tail = elements, tail_len = n
    else:
        # Build tree structure
        # Fill complete nodes of 32, remaining go in tail
```

### Step 4: Implement Node Creation

```python
def _create_pv_node(self, children):
    """Create a new PVNode with given children."""
    # Allocate node
    # Set refcount = 1
    # Copy children pointers into array
    # Return node pointer
```

### Step 5: Implement get() Operation

Index lookup uses bit extraction to navigate the tree:

```python
def _pv_get(self, list_ptr, index):
    """Get element at index from persistent vector."""
    # Load len, check bounds
    # Load depth, tail_len

    # Check if index is in tail
    tail_start = len - tail_len
    if index >= tail_start:
        # Element is in tail
        tail_index = index - tail_start
        return tail[tail_index * elem_size]

    # Element is in tree - navigate using index bits
    # For depth d, use bits: index >> (5 * d) & 0x1F at each level
    node = root
    for level in range(depth, 0, -1):
        child_index = (index >> (5 * level)) & 0x1F
        node = node.children[child_index]

    # At leaf level
    leaf_index = index & 0x1F
    return node.children[leaf_index]
```

### Step 6: Implement len() Operation

Simply return the `len` field:

```python
def _pv_len(self, list_ptr):
    len_ptr = builder.gep(list_ptr, [0, 1])  # field 1 is len
    return builder.load(len_ptr)
```

### Step 7: Implement Iteration

Create an iterator that traverses the tree in order:

```python
# For iteration, we can either:
# 1. Use recursive descent (stack-based)
# 2. Calculate each index and use get() - simpler but O(n log n)
# 3. Use a flat traversal with a small stack

# Option 2 is simplest to implement initially:
for i in 0..len:
    yield get(i)
```

### Step 8: Implement Node Refcounting

For structural sharing, nodes need refcounting:

```python
def _pv_node_incref(self, node):
    """Atomically increment node refcount."""

def _pv_node_decref(self, node):
    """Decrement refcount, recursively free if zero."""
    # When freeing a node, decref all children first
```

## Technical Notes

### Bit Manipulation for Index Navigation

The key insight is that a 32-way tree uses 5 bits per level:
- 32 = 2^5, so each level consumes 5 bits of the index
- Level 0 (leaf): bits 0-4 (index & 0x1F)
- Level 1: bits 5-9 ((index >> 5) & 0x1F)
- Level 2: bits 10-14 ((index >> 10) & 0x1F)
- etc.

```python
BITS = 5  # log2(32)
MASK = 0x1F  # 32 - 1

def get_child_index(index, level):
    return (index >> (BITS * level)) & MASK
```

### Tail Optimization Details

The tail holds the rightmost 1-32 elements not yet in the tree:
- `tail_start = len - tail_len`
- Elements [0, tail_start) are in the tree
- Elements [tail_start, len) are in the tail

When checking if an index is in the tail:
```python
if index >= len - tail_len:
    return tail[index - (len - tail_len)]
```

### Empty and Small Lists

- Empty list: root = null, len = 0, depth = 0, tail = empty, tail_len = 0
- 1-32 elements: root = null, depth = 0, tail = elements, tail_len = n
- 33+ elements: tree is built, tail holds remainder

### Memory Layout

```
List (48 bytes):
+0:  root*     (8 bytes)
+8:  len       (8 bytes)
+16: depth     (4 bytes)
+20: padding   (4 bytes)
+24: tail*     (8 bytes)
+32: tail_len  (4 bytes)
+36: elem_size (8 bytes, or could be 4 with padding)
```

Consider alignment requirements when defining the struct.

## Success Criteria

1. All tests in `test_persistent_vector.py` pass
2. List literals create proper Persistent Vector structure
3. `get()` works correctly at all tree depths
4. `len()` returns correct count
5. Iteration visits all elements in order
6. Assignment shares structure (no copying)
7. Node refcounting works for sharing
8. All existing tests pass (Sessions 1-3)

## What This Enables

After this session:
- List uses Persistent Vector structure
- O(1) assignment via structural sharing
- O(log₃₂ n) element access
- Foundation for O(log₃₂ n) mutations (Session 5)

## Files to Modify

- `codegen.py` - List restructure, node types, read operations
- `tests/test_persistent_vector.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_persistent_vector.py -v --tb=short

# After implementation
python3 -m pytest tests/test_persistent_vector.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
