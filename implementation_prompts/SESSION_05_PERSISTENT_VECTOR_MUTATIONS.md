# Session 5: Persistent Vector Mutations

## Context

This is Session 5 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure and read operations

**This Session:**
- Implement mutation operations with path copying (append, set)

**Coming Next:**
- Session 6: HAMT structure for Map

### Structural Sharing on Mutation

The key insight of persistent data structures: when you "mutate", you create a new version that shares unchanged subtrees with the old version.

For `set(index, value)`:
```
Before: list.set(5, X)

     Root(A)                    Root(B) ← new
    /   |   \                  /   |   \
  N0   N1   N2       →       N0   N1'  N2   ← N1' is new, N0 and N2 shared
  |    |    |                |    |    |
 ... [5]  ...               ... [X]  ...    ← only path to index 5 is copied
```

The old and new list both exist, sharing most of their structure.

## Goals for This Session

1. Write failing tests for mutation operations
2. Implement `set()` with path copying
3. Implement `append()` with tail optimization
4. Ensure structural sharing works correctly
5. Make all tests pass

## Test-Driven Development

Write these tests FIRST in `tests/test_pv_mutations.py`. They should FAIL initially.

```python
import pytest

class TestPersistentVectorSet:
    """Test set() operation with structural sharing."""

    def test_set_single_element(self, expect_output):
        """set() on single element list."""
        expect_output('''
func main() -> int
    a = [10]
    b = a.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "10\n99\n")

    def test_set_preserves_original(self, expect_output):
        """set() creates new list, original unchanged."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(2, 99)
    print(a.get(0))
    print(a.get(2))
    print(a.get(4))
    print(b.get(0))
    print(b.get(2))
    print(b.get(4))
    return 0
~
''', "1\n3\n5\n1\n99\n5\n")

    def test_set_multiple_indices(self, expect_output):
        """Multiple set() calls create independent versions."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(0, 10)
    c = a.set(2, 30)
    d = a.set(4, 50)
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    print(d.get(0))
    return 0
~
''', "1\n10\n1\n1\n")

    def test_set_large_list(self, expect_output):
        """set() on list with tree structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..100
        a = a.append(i)
    ~
    b = a.set(50, 999)
    print(a.get(50))
    print(b.get(50))
    print(a.len())
    print(b.len())
    return 0
~
''', "50\n999\n100\n100\n")

    def test_set_chain(self, expect_output):
        """Chained set() operations."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a.set(0, 10).set(1, 20).set(2, 30)
    print(b.get(0))
    print(b.get(1))
    print(b.get(2))
    return 0
~
''', "10\n20\n30\n")

class TestPersistentVectorAppend:
    """Test append() operation with tail optimization."""

    def test_append_to_empty(self, expect_output):
        """append() to empty list."""
        expect_output('''
func main() -> int
    a: List<int> = []
    b = a.append(42)
    print(a.len())
    print(b.len())
    print(b.get(0))
    return 0
~
''', "0\n1\n42\n")

    def test_append_preserves_original(self, expect_output):
        """append() creates new list, original unchanged."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a.append(4)
    print(a.len())
    print(b.len())
    print(b.get(3))
    return 0
~
''', "3\n4\n4\n")

    def test_append_multiple(self, expect_output):
        """Multiple appends create growing lists."""
        expect_output('''
func main() -> int
    a = [1]
    b = a.append(2)
    c = b.append(3)
    d = c.append(4)
    print(a.len())
    print(b.len())
    print(c.len())
    print(d.len())
    return 0
~
''', "1\n2\n3\n4\n")

    def test_append_builds_tree(self, expect_output):
        """Appending past 32 elements builds tree structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..50
        a = a.append(i)
    ~
    print(a.len())
    print(a.get(0))
    print(a.get(32))
    print(a.get(49))
    return 0
~
''', "50\n0\n32\n49\n")

    def test_append_chain(self, expect_output):
        """Chained append operations."""
        expect_output('''
func main() -> int
    a = [1].append(2).append(3).append(4).append(5)
    print(a.len())
    for x in a
        print(x)
    ~
    return 0
~
''', "5\n1\n2\n3\n4\n5\n")

class TestStructuralSharing:
    """Test that structural sharing works correctly."""

    def test_shared_nodes_not_duplicated(self, expect_output):
        """Modified list shares unchanged nodes with original."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(0, 99)
    print(a.get(4))
    print(b.get(4))
    return 0
~
''', "5\n5\n")

    def test_independent_mutations(self, expect_output):
        """Multiple mutations from same source are independent."""
        expect_output('''
func main() -> int
    base = [1, 2, 3, 4, 5]
    v1 = base.set(0, 10)
    v2 = base.set(0, 20)
    v3 = base.set(0, 30)
    print(base.get(0))
    print(v1.get(0))
    print(v2.get(0))
    print(v3.get(0))
    return 0
~
''', "1\n10\n20\n30\n")

    def test_large_shared_structure(self, expect_output):
        """Large lists share most of their structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..1000
        a = a.append(i)
    ~
    b = a.set(500, 9999)
    print(a.get(0))
    print(b.get(0))
    print(a.get(500))
    print(b.get(500))
    print(a.get(999))
    print(b.get(999))
    return 0
~
''', "0\n0\n500\n9999\n999\n999\n")

class TestMutationWithMove:
    """Test mutations combined with := operator."""

    def test_append_after_move(self, expect_output):
        """After move, append is in-place if sole owner."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b := a
    b = b.append(4)
    b = b.append(5)
    print(b.len())
    for x in b
        print(x)
    ~
    return 0
~
''', "5\n1\n2\n3\n4\n5\n")

    def test_set_after_move(self, expect_output):
        """After move, set is in-place if sole owner."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b := a
    b = b.set(0, 10)
    b = b.set(2, 30)
    for x in b
        print(x)
    ~
    return 0
~
''', "10\n2\n30\n4\n5\n")
```

## Implementation Steps

### Step 1: Implement Path Copying Helper

Create a function to copy the path from root to a specific index:

```python
def _pv_path_copy(self, list_ptr, index):
    """
    Copy the path from root to the node containing index.
    Returns new root with path copied, unchanged nodes shared.
    """
    # Load depth
    # If index is in tail, handle separately

    # Copy root node (new root)
    new_root = self._copy_pv_node(old_root)

    # Navigate down, copying each node on the path
    level = depth
    current_new = new_root
    current_old = old_root

    while level > 0:
        child_idx = (index >> (5 * level)) & 0x1F
        old_child = current_old.children[child_idx]

        # Copy this child node
        new_child = self._copy_pv_node(old_child)

        # Link new child into new parent
        current_new.children[child_idx] = new_child

        # Other children remain shared (incref them)
        for i in range(32):
            if i != child_idx and current_old.children[i] != null:
                incref(current_old.children[i])

        current_old = old_child
        current_new = new_child
        level -= 1

    return new_root, current_new  # new_root and the leaf node
```

### Step 2: Implement set() Operation

```python
def _pv_set(self, list_ptr, index, value):
    """
    Return new list with element at index replaced.
    Uses path copying for structural sharing.
    """
    # Check bounds
    len = load(list_ptr.len)
    if index >= len:
        raise IndexError

    # Check if index is in tail
    tail_start = len - tail_len
    if index >= tail_start:
        # Copy tail, modify, create new list
        new_tail = copy_tail()
        new_tail[index - tail_start] = value
        return new_list(root, len, depth, new_tail, tail_len)

    # Index is in tree - path copy
    new_root, leaf = path_copy(list_ptr, index)
    leaf_idx = index & 0x1F
    leaf.children[leaf_idx] = value

    return new_list(new_root, len, depth, tail, tail_len)
```

### Step 3: Implement append() Operation

Append has several cases:

```python
def _pv_append(self, list_ptr, value):
    """
    Return new list with value appended.
    Uses tail optimization for O(1) common case.
    """
    # Load current state
    len = load(list_ptr.len)
    tail_len = load(list_ptr.tail_len)

    # Case 1: Tail has room
    if tail_len < 32:
        new_tail = copy_tail()
        new_tail[tail_len] = value
        return new_list(root, len + 1, depth, new_tail, tail_len + 1)

    # Case 2: Tail is full - push tail into tree, start new tail
    new_root = push_tail_into_tree(root, depth, tail)
    new_tail = [value]  # New tail with just the new element
    new_depth = depth  # May increase if tree grows

    # Check if tree grew in height
    if tree_is_full(len):
        new_depth = depth + 1

    return new_list(new_root, len + 1, new_depth, new_tail, 1)
```

### Step 4: Implement push_tail_into_tree()

When tail is full, it becomes a leaf node in the tree:

```python
def _push_tail_into_tree(self, root, depth, tail, len):
    """
    Push the full tail into the tree as a new leaf.
    May increase tree depth if tree is full.
    """
    # Convert tail to a node
    tail_node = create_node_from_tail(tail)

    if root is null:
        # First node in tree
        return tail_node

    # Check if we need to grow the tree
    if is_tree_full(len, depth):
        # Create new root with old root and tail_node as children
        new_root = create_node()
        new_root.children[0] = root  # incref root
        new_root.children[1] = tail_node
        return new_root  # depth increased by caller

    # Tree has room - find the rightmost path and insert
    return insert_at_rightmost(root, depth, tail_node)
```

### Step 5: Handle Sole Ownership Optimization

When refcount is 1 (sole owner, often after `:=`), we can mutate in place:

```python
def _pv_set_optimized(self, list_ptr, index, value):
    # Check if we're the sole owner of the entire path
    if is_sole_owner_of_path(list_ptr, index):
        # Mutate in place!
        node = navigate_to(list_ptr, index)
        node.children[index & 0x1F] = value
        return list_ptr  # Same list, modified in place
    else:
        # Path copy as usual
        return _pv_set(list_ptr, index, value)
```

This is an optimization - the correct behavior without it is path copying.

### Step 6: Update List Assignment

Ensure list assignment uses structural sharing:

```python
def assign_list(dest, src):
    # Just copy the pointer and incref the root
    incref(src.root)
    # Copy the struct fields
    dest.root = src.root
    dest.len = src.len
    dest.depth = src.depth
    # For tail, either share or copy (tail is usually small)
    dest.tail = copy_tail(src.tail)  # or share with refcount
    dest.tail_len = src.tail_len
```

## Technical Notes

### Tree Fullness Check

A tree of depth d can hold 32^(d+1) elements (plus tail):
- Depth 0: 32 in tree + 32 in tail = 64 max before depth increase
- Depth 1: 1024 in tree + 32 in tail = 1056 max

```python
def is_tree_full(len, depth):
    tree_capacity = 32 ** (depth + 1)
    return len >= tree_capacity
```

### Rightmost Path Insertion

When pushing tail into tree, find the rightmost non-full path:

```python
def insert_at_rightmost(root, depth, new_node):
    # Calculate insertion point based on current len
    # Navigate to rightmost path, copying nodes
    # Insert new_node as leaf
```

### Refcount Management

When path copying:
- New nodes start with refcount 1
- Shared (unchanged) children need incref
- When a list is freed, decref root (recursively frees if refcount hits 0)

### Memory Layout Reminder

```
List:
+0:  root*     (8 bytes) - pointer to PVNode
+8:  len       (8 bytes) - total elements
+16: depth     (4 bytes) - tree depth
+20: padding   (4 bytes)
+24: tail*     (8 bytes) - pointer to tail array
+32: tail_len  (4 bytes) - elements in tail
+36: elem_size (4 bytes) - size of each element

PVNode:
+0:  refcount  (8 bytes)
+8:  children  (256 bytes) - 32 x 8-byte pointers
```

## Success Criteria

1. All tests in `test_pv_mutations.py` pass
2. `set()` creates new list with structural sharing
3. `append()` uses tail optimization for O(1) common case
4. Original list unchanged after mutation
5. Multiple versions share unchanged structure
6. Refcounting prevents memory leaks
7. All existing tests pass (Sessions 1-4)

## What This Enables

After this session:
- List has full Persistent Vector implementation
- O(log₃₂ n) mutations with structural sharing
- Value semantics without full copying
- Ready for HAMT (Map, Set) in Sessions 6-8

## Files to Modify

- `codegen.py` - Mutation operations, path copying
- `tests/test_pv_mutations.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_pv_mutations.py -v --tb=short

# After implementation
python3 -m pytest tests/test_pv_mutations.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
