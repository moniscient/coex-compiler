# Session 7: HAMT Map Mutations

## Context

This is Session 7 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure for List
- Session 5: Persistent Vector mutations
- Session 6: HAMT structure for Map (read operations)

**This Session:**
- Implement mutation operations with path copying (set, remove)

**Coming Next:**
- Session 8: HAMT for Set

### Structural Sharing in HAMT

Like Persistent Vector, HAMT mutations copy only the path to the changed entry:

```
Before: map.set("new_key", value)

        Root(A)                      Root(B) ← new
        /    \                       /    \
    [5]      [28]        →      [5]      [28]' ← copied
             /  \                        /  \
          [11]  [15]                  [11]  [15]  ← shared
                                        \
                                      [new] ← new entry
```

Only the path from root to the new/modified entry is copied.

## Goals for This Session

1. Write failing tests for mutation operations
2. Implement `set()` with path copying
3. Implement `remove()` with path copying
4. Ensure structural sharing works correctly
5. Make all tests pass

## Test-Driven Development

Write these tests FIRST in `tests/test_hamt_mutations.py`. They should FAIL initially.

```python
import pytest

class TestHAMTMapSet:
    """Test set() operation with structural sharing."""

    def test_set_new_key(self, expect_output):
        """set() adds new key-value pair."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.set(3, 30)
    print(m.len())
    print(n.len())
    print(n.get(3))
    return 0
~
''', "2\n3\n30\n")

    def test_set_preserves_original(self, expect_output):
        """set() creates new map, original unchanged."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.set(1, 99)
    print(m.get(1))
    print(n.get(1))
    return 0
~
''', "10\n99\n")

    def test_set_multiple_keys(self, expect_output):
        """Multiple set() calls create independent versions."""
        expect_output('''
func main() -> int
    base = {1: 10}
    a = base.set(2, 20)
    b = base.set(3, 30)
    c = base.set(4, 40)
    print(base.len())
    print(a.len())
    print(b.len())
    print(c.len())
    print(a.has(2))
    print(a.has(3))
    return 0
~
''', "1\n2\n2\n2\ntrue\nfalse\n")

    def test_set_chain(self, expect_output):
        """Chained set() operations."""
        expect_output('''
func main() -> int
    m = {1: 10}.set(2, 20).set(3, 30).set(4, 40)
    print(m.len())
    print(m.get(1))
    print(m.get(4))
    return 0
~
''', "4\n10\n40\n")

    def test_set_overwrite(self, expect_output):
        """set() with existing key overwrites value."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.set(2, 200)
    print(m.get(2))
    print(n.get(2))
    print(n.len())
    return 0
~
''', "20\n200\n3\n")

    def test_set_large_map(self, expect_output):
        """set() on map with many entries."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    for i in 0..100
        m = m.set(i, i * 10)
    ~
    n = m.set(50, 9999)
    print(m.get(50))
    print(n.get(50))
    print(m.len())
    print(n.len())
    return 0
~
''', "500\n9999\n100\n100\n")

    def test_set_string_keys(self, expect_output):
        """set() with string keys."""
        expect_output('''
func main() -> int
    m = {"a": 1, "b": 2}
    n = m.set("c", 3)
    print(m.has("c"))
    print(n.has("c"))
    print(n.get("c"))
    return 0
~
''', "false\ntrue\n3\n")

class TestHAMTMapRemove:
    """Test remove() operation with structural sharing."""

    def test_remove_existing(self, expect_output):
        """remove() removes existing key."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.remove(2)
    print(m.len())
    print(n.len())
    print(m.has(2))
    print(n.has(2))
    return 0
~
''', "3\n2\ntrue\nfalse\n")

    def test_remove_preserves_original(self, expect_output):
        """remove() creates new map, original unchanged."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.remove(1)
    print(m.get(1))
    print(m.len())
    print(n.len())
    return 0
~
''', "10\n3\n2\n")

    def test_remove_nonexistent(self, expect_output):
        """remove() of nonexistent key returns same map."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.remove(999)
    print(m.len())
    print(n.len())
    return 0
~
''', "2\n2\n")

    def test_remove_chain(self, expect_output):
        """Chained remove() operations."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30, 4: 40}
    n = m.remove(1).remove(3)
    print(n.len())
    print(n.has(1))
    print(n.has(2))
    print(n.has(3))
    print(n.has(4))
    return 0
~
''', "2\nfalse\ntrue\nfalse\ntrue\n")

    def test_remove_all(self, expect_output):
        """Remove all elements."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.remove(1).remove(2)
    print(n.len())
    return 0
~
''', "0\n")

class TestHAMTStructuralSharing:
    """Test that structural sharing works correctly."""

    def test_shared_subtrees(self, expect_output):
        """Modified map shares unchanged subtrees."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}
    n = m.set(1, 99)
    print(m.get(5))
    print(n.get(5))
    return 0
~
''', "50\n50\n")

    def test_independent_branches(self, expect_output):
        """Multiple modifications from same base are independent."""
        expect_output('''
func main() -> int
    base = {1: 10, 2: 20, 3: 30}
    a = base.set(1, 100)
    b = base.set(1, 200)
    c = base.set(1, 300)
    print(base.get(1))
    print(a.get(1))
    print(b.get(1))
    print(c.get(1))
    return 0
~
''', "10\n100\n200\n300\n")

    def test_mixed_operations(self, expect_output):
        """Mix of set and remove operations."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.set(4, 40).remove(2).set(5, 50)
    print(n.len())
    print(n.has(1))
    print(n.has(2))
    print(n.has(4))
    print(n.has(5))
    return 0
~
''', "4\ntrue\nfalse\ntrue\ntrue\n")

class TestMutationWithMove:
    """Test mutations combined with := operator."""

    def test_set_after_move(self, expect_output):
        """After move, set may be optimized."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n := m
    n = n.set(3, 30)
    n = n.set(4, 40)
    print(n.len())
    print(n.get(3))
    print(n.get(4))
    return 0
~
''', "4\n30\n40\n")

    def test_remove_after_move(self, expect_output):
        """After move, remove may be optimized."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n := m
    n = n.remove(2)
    print(n.len())
    print(n.has(2))
    return 0
~
''', "2\nfalse\n")
```

## Implementation Steps

### Step 1: Implement Path Copying for HAMT

```python
def _hamt_path_copy(self, node, hash, level):
    """
    Copy the path from node to the entry location.
    Returns new node with path copied, unchanged subtrees shared.
    """
    if node is null:
        return null

    # Copy this node
    new_node = copy_hamt_node(node)

    # Find child position
    bit_pos = (hash >> (5 * level)) & 0x1F

    if not bitmap_has(new_node.bitmap, bit_pos):
        # No child at this position - nothing to copy
        return new_node

    # Get and copy child
    index = bitmap_index(new_node.bitmap, bit_pos)
    child = new_node.entries[index]

    if is_node(child):
        # Recursively copy child path
        new_child = _hamt_path_copy(untag(child), hash, level + 1)
        new_node.entries[index] = tag_as_node(new_child)
    # If it's a leaf, we'll handle it in set/remove

    # Incref unchanged children
    for i in range(popcount(new_node.bitmap)):
        if i != index:
            incref(new_node.entries[i])

    return new_node
```

### Step 2: Implement set() Operation

```python
def _hamt_set(self, map_ptr, key, value):
    """
    Return new map with key-value pair added/updated.
    Uses path copying for structural sharing.
    """
    hash = compute_hash(key)
    old_root = map_ptr.root
    old_len = map_ptr.len

    # Navigate to insertion point, copying path
    new_root, is_update = _hamt_insert(old_root, hash, 0, key, value)

    # Create new map
    new_len = old_len if is_update else old_len + 1
    return create_map(new_root, new_len, key_size, val_size)


def _hamt_insert(self, node, hash, level, key, value):
    """
    Insert key-value at appropriate position.
    Returns (new_node, is_update).
    """
    bit_pos = (hash >> (5 * level)) & 0x1F

    if node is null:
        # Create new node with just this entry
        new_node = create_hamt_node(bitmap=1 << bit_pos)
        new_node.entries[0] = tag_as_leaf(create_kv_pair(key, value))
        return new_node, False

    # Copy this node
    new_node = copy_hamt_node(node)

    if not bitmap_has(node.bitmap, bit_pos):
        # No entry at this position - add new one
        new_bitmap = node.bitmap | (1 << bit_pos)
        new_index = bitmap_index(new_bitmap, bit_pos)

        # Expand entries array to include new slot
        new_entries = expand_entries(node.entries, popcount(node.bitmap), new_index)
        new_entries[new_index] = tag_as_leaf(create_kv_pair(key, value))

        new_node.bitmap = new_bitmap
        new_node.entries = new_entries
        return new_node, False

    # Entry exists at this position
    index = bitmap_index(node.bitmap, bit_pos)
    entry = node.entries[index]

    if is_leaf(entry):
        # There's a key-value pair here
        existing_kv = untag(entry)

        if keys_equal(existing_kv.key, key):
            # Same key - update value
            new_kv = create_kv_pair(key, value)
            new_node.entries[index] = tag_as_leaf(new_kv)
            return new_node, True
        else:
            # Hash collision - need to create child node
            existing_hash = compute_hash(existing_kv.key)
            child = create_collision_node(existing_kv, key, value, existing_hash, hash, level + 1)
            new_node.entries[index] = tag_as_node(child)
            return new_node, False
    else:
        # It's a child node - recurse
        child = untag(entry)
        new_child, is_update = _hamt_insert(child, hash, level + 1, key, value)
        new_node.entries[index] = tag_as_node(new_child)
        return new_node, is_update
```

### Step 3: Handle Hash Collisions

When two keys have identical hashes (or hash prefixes exhaust all levels):

```python
def _create_collision_node(self, kv1, key2, value2, hash1, hash2, level):
    """
    Create a node to handle hash collision.
    """
    if level >= MAX_DEPTH:
        # True collision - store both in a collision list
        return create_collision_list([kv1, create_kv_pair(key2, value2)])

    # Try next level of hash
    bit_pos1 = (hash1 >> (5 * level)) & 0x1F
    bit_pos2 = (hash2 >> (5 * level)) & 0x1F

    if bit_pos1 == bit_pos2:
        # Still colliding - recurse
        child = _create_collision_node(kv1, key2, value2, hash1, hash2, level + 1)
        node = create_hamt_node(bitmap=1 << bit_pos1)
        node.entries[0] = tag_as_node(child)
        return node
    else:
        # Different positions - create node with both
        bitmap = (1 << bit_pos1) | (1 << bit_pos2)
        node = create_hamt_node(bitmap=bitmap)
        if bit_pos1 < bit_pos2:
            node.entries[0] = tag_as_leaf(kv1)
            node.entries[1] = tag_as_leaf(create_kv_pair(key2, value2))
        else:
            node.entries[0] = tag_as_leaf(create_kv_pair(key2, value2))
            node.entries[1] = tag_as_leaf(kv1)
        return node
```

### Step 4: Implement remove() Operation

```python
def _hamt_remove(self, map_ptr, key):
    """
    Return new map with key removed.
    Uses path copying for structural sharing.
    """
    hash = compute_hash(key)
    old_root = map_ptr.root
    old_len = map_ptr.len

    # Navigate to key and remove, copying path
    new_root, was_removed = _hamt_delete(old_root, hash, 0, key)

    if not was_removed:
        # Key didn't exist - return same map
        return map_ptr

    # Create new map
    return create_map(new_root, old_len - 1, key_size, val_size)


def _hamt_delete(self, node, hash, level, key):
    """
    Delete key from tree.
    Returns (new_node_or_null, was_removed).
    May return null if node becomes empty.
    """
    if node is null:
        return null, False

    bit_pos = (hash >> (5 * level)) & 0x1F

    if not bitmap_has(node.bitmap, bit_pos):
        return node, False  # Key not found

    index = bitmap_index(node.bitmap, bit_pos)
    entry = node.entries[index]

    if is_leaf(entry):
        kv = untag(entry)
        if not keys_equal(kv.key, key):
            return node, False  # Different key

        # Remove this entry
        if popcount(node.bitmap) == 1:
            # Node becomes empty
            return null, True

        # Copy node without this entry
        new_node = copy_hamt_node_without(node, bit_pos)
        return new_node, True
    else:
        # Recurse into child
        child = untag(entry)
        new_child, was_removed = _hamt_delete(child, hash, level + 1, key)

        if not was_removed:
            return node, False

        # Copy node with updated child
        new_node = copy_hamt_node(node)

        if new_child is null:
            # Child became empty - remove it
            new_node = copy_hamt_node_without(node, bit_pos)
        else:
            new_node.entries[index] = tag_as_node(new_child)

        # Check if this node should collapse
        if popcount(new_node.bitmap) == 1 and is_leaf(new_node.entries[0]):
            # Single leaf child - could return the leaf directly
            # (optimization for sparse maps)
            pass

        return new_node, True
```

### Step 5: Implement Node Compaction

When removing entries, nodes may become too sparse. Consider compacting:

```python
def _maybe_compact(self, node):
    """
    If node has single leaf child, collapse it.
    This keeps the tree balanced and prevents long chains.
    """
    if popcount(node.bitmap) == 1:
        entry = node.entries[0]
        if is_leaf(entry):
            # This node can be replaced by the leaf in parent
            return entry
    return tag_as_node(node)
```

### Step 6: Implement Entry Array Manipulation

```python
def _expand_entries(self, old_entries, old_count, insert_index):
    """
    Create new entries array with slot for new entry.
    """
    new_count = old_count + 1
    new_entries = allocate(new_count * 8)

    # Copy entries before insert point
    for i in range(insert_index):
        new_entries[i] = old_entries[i]

    # Leave slot for new entry

    # Copy entries after insert point
    for i in range(insert_index, old_count):
        new_entries[i + 1] = old_entries[i]

    return new_entries


def _shrink_entries(self, old_entries, old_count, remove_index):
    """
    Create new entries array without removed entry.
    """
    new_count = old_count - 1
    if new_count == 0:
        return null

    new_entries = allocate(new_count * 8)

    # Copy entries before removal point
    for i in range(remove_index):
        new_entries[i] = old_entries[i]

    # Copy entries after removal point
    for i in range(remove_index + 1, old_count):
        new_entries[i - 1] = old_entries[i]

    return new_entries
```

## Technical Notes

### Sole Ownership Optimization

Like Persistent Vector, when refcount is 1, mutations can be in-place:

```python
def _hamt_set_optimized(self, map_ptr, key, value):
    if is_sole_owner_of_path(map_ptr, key):
        # Mutate in place
        ...
    else:
        # Path copy
        return _hamt_set(map_ptr, key, value)
```

This optimization is transparent to the user but improves performance when using `:=`.

### Memory Management

- New nodes start with refcount 1
- When copying a node, incref all children that are shared
- When a map is freed, decref root (recursively frees if refcount hits 0)
- Key-value pairs may also need refcounting if keys/values are reference types

### Popcount Performance

LLVM's `llvm.ctpop.i32` intrinsic compiles to efficient CPU instructions (POPCNT on x86).

### Max Depth

With 5 bits per level and 64-bit hashes:
- 64 / 5 = 12.8 levels max
- Set MAX_DEPTH = 13

After max depth, use collision lists for remaining conflicts.

## Success Criteria

1. All tests in `test_hamt_mutations.py` pass
2. `set()` creates new map with structural sharing
3. `remove()` creates new map with structural sharing
4. Original map unchanged after mutations
5. Multiple versions share unchanged subtrees
6. Refcounting prevents memory leaks
7. All existing tests pass (Sessions 1-6)

## What This Enables

After this session:
- Map has full HAMT implementation
- O(log₃₂ n) mutations with structural sharing
- Value semantics without full copying
- Ready for Set (Session 8)

## Files to Modify

- `codegen.py` - Mutation operations, path copying for HAMT
- `tests/test_hamt_mutations.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_hamt_mutations.py -v --tb=short

# After implementation
python3 -m pytest tests/test_hamt_mutations.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
