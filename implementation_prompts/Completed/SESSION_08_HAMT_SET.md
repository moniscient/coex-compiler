# Session 8: HAMT for Set

## Context

This is Session 8 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure for List
- Session 5: Persistent Vector mutations
- Session 6: HAMT structure for Map
- Session 7: HAMT Map mutations

**This Session:**
- Implement HAMT for Set (reusing Map infrastructure)

**Coming Next:**
- Session 9: Type conversions between collection types

### Set as a Simplified Map

A Set is essentially a Map with no values - just keys. We can implement Set by:
1. Reusing the HAMT node structure from Map
2. Storing just keys (no values) in leaf entries
3. Simplifying the API (add, has, remove, no get)

This approach maximizes code reuse and ensures consistent behavior.

## Goals for This Session

1. Write failing tests for Set operations
2. Define Set structure (similar to Map)
3. Implement Set operations: `add()`, `has()`, `remove()`, `len()`
4. Implement Set iteration
5. Ensure structural sharing works
6. Make all tests pass

## Set Structure

```
Set struct:
+----------+----------+----------+
| root*    | len      | elem_size|
| HAMTNode*| i64      | i64      |
+----------+----------+----------+

- root: pointer to root HAMT node (shared with Map)
- len: total elements
- elem_size: size of element type in bytes
```

The HAMT nodes are identical to Map, but leaf entries contain just elements (not key-value pairs).

## Test-Driven Development

Write these tests FIRST in `tests/test_hamt_set.py`. They should FAIL initially.

```python
import pytest

class TestHAMTSetBasic:
    """Test basic Set operations."""

    def test_set_literal(self, expect_output):
        """Set literal creates proper structure."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    print(s.len())
    return 0
~
''', "5\n")

    def test_set_has(self, expect_output):
        """has() checks element existence."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    if s.has(1)
        print("has 1")
    ~
    if s.has(2)
        print("has 2")
    ~
    if s.has(4)
        print("has 4")
    else
        print("no 4")
    ~
    return 0
~
''', "has 1\nhas 2\nno 4\n")

    def test_set_len(self, expect_output):
        """len() returns correct count."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    print(s.len())
    empty: Set<int> = {}
    print(empty.len())
    return 0
~
''', "5\n0\n")

    def test_empty_set(self, expect_output):
        """Empty set works correctly."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    print(s.len())
    print(s.has(1))
    return 0
~
''', "0\nfalse\n")

    def test_set_of_strings(self, expect_output):
        """Set of strings works."""
        expect_output('''
func main() -> int
    s = {"hello", "world", "test"}
    print(s.len())
    print(s.has("hello"))
    print(s.has("missing"))
    return 0
~
''', "3\ntrue\nfalse\n")

    def test_set_iteration(self, expect_output):
        """Can iterate over set elements."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    sum = 0
    for x in s
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "60\n")

class TestHAMTSetAdd:
    """Test add() operation."""

    def test_add_new_element(self, expect_output):
        """add() adds new element."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t = s.add(3)
    print(s.len())
    print(t.len())
    print(t.has(3))
    return 0
~
''', "2\n3\ntrue\n")

    def test_add_preserves_original(self, expect_output):
        """add() creates new set, original unchanged."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(4)
    print(s.has(4))
    print(t.has(4))
    return 0
~
''', "false\ntrue\n")

    def test_add_existing_element(self, expect_output):
        """add() of existing element is idempotent."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(2)
    print(s.len())
    print(t.len())
    return 0
~
''', "3\n3\n")

    def test_add_chain(self, expect_output):
        """Chained add() operations."""
        expect_output('''
func main() -> int
    s = {1}.add(2).add(3).add(4).add(5)
    print(s.len())
    for x in s
        print(x)
    ~
    return 0
~
''', "5\n1\n2\n3\n4\n5\n")

    def test_add_many(self, expect_output):
        """Add many elements (requires multiple levels)."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    for i in 0..100
        s = s.add(i)
    ~
    print(s.len())
    print(s.has(0))
    print(s.has(50))
    print(s.has(99))
    print(s.has(100))
    return 0
~
''', "100\ntrue\ntrue\ntrue\nfalse\n")

class TestHAMTSetRemove:
    """Test remove() operation."""

    def test_remove_existing(self, expect_output):
        """remove() removes existing element."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(2)
    print(s.len())
    print(t.len())
    print(s.has(2))
    print(t.has(2))
    return 0
~
''', "3\n2\ntrue\nfalse\n")

    def test_remove_preserves_original(self, expect_output):
        """remove() creates new set, original unchanged."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(1)
    print(s.has(1))
    print(t.has(1))
    return 0
~
''', "true\nfalse\n")

    def test_remove_nonexistent(self, expect_output):
        """remove() of nonexistent element is no-op."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(999)
    print(s.len())
    print(t.len())
    return 0
~
''', "3\n3\n")

    def test_remove_chain(self, expect_output):
        """Chained remove() operations."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    t = s.remove(1).remove(3).remove(5)
    print(t.len())
    print(t.has(2))
    print(t.has(4))
    return 0
~
''', "2\ntrue\ntrue\n")

    def test_remove_all(self, expect_output):
        """Remove all elements."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t = s.remove(1).remove(2)
    print(t.len())
    return 0
~
''', "0\n")

class TestSetStructuralSharing:
    """Test structural sharing."""

    def test_assignment_shares(self, expect_output):
        """Assignment shares structure."""
        expect_output('''
func main() -> int
    a = {1, 2, 3, 4, 5}
    b = a
    c = a
    print(b.has(3))
    print(c.has(3))
    return 0
~
''', "true\ntrue\n")

    def test_independent_modifications(self, expect_output):
        """Modifications from same base are independent."""
        expect_output('''
func main() -> int
    base = {1, 2, 3}
    a = base.add(10)
    b = base.add(20)
    c = base.add(30)
    print(a.has(10))
    print(a.has(20))
    print(b.has(10))
    print(b.has(20))
    return 0
~
''', "true\nfalse\nfalse\ntrue\n")

    def test_mixed_operations(self, expect_output):
        """Mix of add and remove operations."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(4).remove(2).add(5)
    print(t.len())
    print(t.has(1))
    print(t.has(2))
    print(t.has(4))
    print(t.has(5))
    return 0
~
''', "4\ntrue\nfalse\ntrue\ntrue\n")

class TestSetWithMove:
    """Test Set with := operator."""

    def test_add_after_move(self, expect_output):
        """After move, add may be optimized."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t := s
    t = t.add(3)
    t = t.add(4)
    print(t.len())
    return 0
~
''', "4\n")

    def test_remove_after_move(self, expect_output):
        """After move, remove may be optimized."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t := s
    t = t.remove(2)
    print(t.len())
    print(t.has(2))
    return 0
~
''', "2\nfalse\n")
```

## Implementation Steps

### Step 1: Define Set Structure

```python
self.set_struct.set_body(
    self.hamt_node_struct.as_pointer(),  # root (reuse Map's HAMT nodes)
    ir.IntType(64),  # len
    ir.IntType(64),  # elem_size
)
```

### Step 2: Distinguish Set Nodes from Map Nodes

Option A: Same node structure, different leaf format
- Map leaf: tagged pointer to key-value pair
- Set leaf: tagged pointer to element only

Option B: Different tag bits
- Use different tag values to distinguish set elements from map entries

For simplicity, use Option A with same tagging scheme.

### Step 3: Implement add() - Reuse Map's set() Logic

```python
def _set_add(self, set_ptr, element):
    """
    Add element to set. Reuses HAMT insert logic.
    """
    hash = compute_hash(element)
    old_root = set_ptr.root
    old_len = set_ptr.len

    # Use HAMT insert with element only (no value)
    new_root, already_present = _hamt_insert_element(old_root, hash, 0, element)

    if already_present:
        return set_ptr  # Element already in set

    return create_set(new_root, old_len + 1, elem_size)
```

### Step 4: Implement has() - Reuse Map's get() Logic

```python
def _set_has(self, set_ptr, element):
    """
    Check if element exists in set.
    """
    hash = compute_hash(element)
    return _hamt_contains(set_ptr.root, hash, 0, element)
```

### Step 5: Implement remove() - Reuse Map's remove() Logic

```python
def _set_remove(self, set_ptr, element):
    """
    Remove element from set.
    """
    hash = compute_hash(element)
    old_root = set_ptr.root
    old_len = set_ptr.len

    new_root, was_removed = _hamt_delete_element(old_root, hash, 0, element)

    if not was_removed:
        return set_ptr

    return create_set(new_root, old_len - 1, elem_size)
```

### Step 6: Implement len()

```python
def _set_len(self, set_ptr):
    return set_ptr.len
```

### Step 7: Implement Iteration

Same tree traversal as Map, but yield elements instead of keys:

```python
def _set_iterate(self, set_ptr):
    # Traverse HAMT, yield each element
    yield from _hamt_traverse_elements(set_ptr.root)
```

### Step 8: Implement Set Literal Construction

```python
def _create_set_from_literal(self, elements):
    """Build Set from literal {e1, e2, e3, ...}."""
    set = create_empty_set()
    for element in elements:
        set = set_add(set, element)
    return set
```

### Step 9: Handle Set-Specific Leaf Format

Set leaves store just elements, not pairs:

```python
# Map leaf: pointer to { key, value }
# Set leaf: pointer to element directly (or element value for primitives)

def create_set_leaf(element):
    if is_primitive(element):
        # Store value directly (boxed if needed)
        return tag_as_set_leaf(box(element))
    else:
        # Store pointer to element
        return tag_as_set_leaf(element_ptr)
```

## Technical Notes

### Code Reuse Strategy

Most HAMT operations are identical for Set and Map:
- Navigation through tree
- Path copying
- Bitmap manipulation
- Refcounting

Factor these into shared helpers:
```python
def _hamt_find(root, hash, level, compare_fn)
def _hamt_insert(root, hash, level, entry, compare_fn)
def _hamt_delete(root, hash, level, compare_fn)
```

The `compare_fn` differs:
- Map: compare keys
- Set: compare elements

### Disambiguation of Set vs Map in Literals

The parser needs to distinguish:
- `{1, 2, 3}` - Set literal
- `{1: 10, 2: 20}` - Map literal
- `{}` - Empty (type annotation needed)

The grammar likely already handles this by checking for `:` between elements.

### Memory Layout

```
Set:
+0:  root*     (8 bytes)
+8:  len       (8 bytes)
+16: elem_size (8 bytes)
```

Same HAMT nodes as Map.

### Structural Sharing with Map

Since Set and Map use the same HAMT node structure, they can share subtrees in some scenarios (though this is an advanced optimization not required for basic implementation).

## Success Criteria

1. All tests in `test_hamt_set.py` pass
2. Set literals create proper HAMT structure
3. `add()` adds elements with structural sharing
4. `has()` checks existence correctly
5. `remove()` removes elements with structural sharing
6. Assignment shares structure (O(1))
7. Refcounting prevents memory leaks
8. All existing tests pass (Sessions 1-7)

## What This Enables

After this session:
- Set has full HAMT implementation
- All three collection types (List, Map, Set) use persistent structures
- Ready for type conversions (Session 9)

## Files to Modify

- `codegen.py` - Set implementation, reusing HAMT infrastructure
- `tests/test_hamt_set.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_hamt_set.py -v --tb=short

# After implementation
python3 -m pytest tests/test_hamt_set.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
