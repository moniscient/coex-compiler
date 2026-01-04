# Session 10: Integration Testing and Polish

## Context

This is Session 10 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array has COW with atomic refcount
- Session 2: String has COW with atomic refcount
- Session 3: `:=` operator for eager/move assignment
- Session 4: Persistent Vector structure for List
- Session 5: Persistent Vector mutations
- Session 6: HAMT structure for Map
- Session 7: HAMT Map mutations
- Session 8: HAMT for Set
- Session 9: Type conversions

**This Session:**
- Integration testing across all features
- Edge case handling
- Performance sanity checks
- Documentation updates

## Goals for This Session

1. Write comprehensive integration tests
2. Test interactions between all new features
3. Verify memory safety (no leaks, no double-frees)
4. Test edge cases and error conditions
5. Run full test suite, fix any regressions
6. Update documentation

## Integration Tests

Write these tests in `tests/test_integration.py`.

```python
import pytest

class TestCOWIntegration:
    """Test COW across Array and String together."""

    def test_array_of_strings_cow(self, expect_output):
        """Array<string> with COW on both levels."""
        expect_output('''
func main() -> int
    arr: Array<string> = ["hello", "world"]
    arr2 = arr
    arr2.set(0, "goodbye")
    print(arr.get(0))
    print(arr2.get(0))
    return 0
~
''', "hello\ngoodbye\n")

    def test_nested_arrays_cow(self, expect_output):
        """Nested arrays with COW."""
        expect_output('''
func main() -> int
    inner: Array<int> = [1, 2, 3]
    outer: Array<Array<int>> = [inner, inner]
    outer2 = outer
    inner2: Array<int> = outer2.get(0)
    inner2.set(0, 99)
    print(outer.get(0).get(0))
    print(inner2.get(0))
    return 0
~
''', "1\n99\n")

class TestMoveOperatorIntegration:
    """Test := with all collection types."""

    def test_move_array(self, expect_output):
        """:= with Array."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b := a
    b.set(0, 99)
    print(b.get(0))
    return 0
~
''', "99\n")

    def test_move_string(self, expect_output):
        """:= with String."""
        expect_output('''
func main() -> int
    a = "hello"
    b := a
    b = b + " world"
    print(b)
    return 0
~
''', "hello world\n")

    def test_move_list(self, expect_output):
        """:= with List."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b := a
    b = b.append(4)
    print(b.len())
    return 0
~
''', "4\n")

    def test_move_map(self, expect_output):
        """:= with Map."""
        expect_output('''
func main() -> int
    a = {1: 10, 2: 20}
    b := a
    b = b.set(3, 30)
    print(b.len())
    return 0
~
''', "3\n")

    def test_move_set(self, expect_output):
        """:= with Set."""
        expect_output('''
func main() -> int
    a = {1, 2, 3}
    b := a
    b = b.add(4)
    print(b.len())
    return 0
~
''', "4\n")

class TestPersistentStructuresIntegration:
    """Test persistent structures working together."""

    def test_list_of_maps(self, expect_output):
        """List containing Maps."""
        expect_output('''
func main() -> int
    m1 = {1: 10}
    m2 = {2: 20}
    list = [m1, m2]
    result = list.get(0)
    print(result.get(1))
    return 0
~
''', "10\n")

    def test_map_of_lists(self, expect_output):
        """Map with List values."""
        expect_output('''
func main() -> int
    m = {"nums": [1, 2, 3], "letters": ["a", "b"]}
    nums = m.get("nums")
    print(nums.len())
    print(nums.get(0))
    return 0
~
''', "3\n1\n")

    def test_set_of_strings(self, expect_output):
        """Set of strings."""
        expect_output('''
func main() -> int
    s = {"hello", "world", "hello"}
    print(s.len())
    print(s.has("hello"))
    return 0
~
''', "2\ntrue\n")

    def test_complex_nesting(self, expect_output):
        """Deeply nested persistent structures."""
        expect_output('''
func main() -> int
    inner_list = [1, 2, 3]
    inner_map = {"list": inner_list}
    outer = [inner_map, inner_map]
    result = outer.get(0).get("list").get(1)
    print(result)
    return 0
~
''', "2\n")

class TestConversionsIntegration:
    """Test type conversions in complex scenarios."""

    def test_process_pipeline(self, expect_output):
        """Typical I/O processing pattern."""
        expect_output('''
func main() -> int
    input: Array<int> = [1, 2, 3, 4, 5]
    working: List<int> = input
    working = working.append(6)
    working = working.append(7)
    output: Array<int> = working
    print(output.len())
    print(output.get(6))
    return 0
~
''', "7\n7\n")

    def test_set_dedup_then_sort(self, expect_output):
        """Deduplicate via Set, then to Array for processing."""
        expect_output('''
func main() -> int
    raw: Array<int> = [3, 1, 2, 1, 3, 2]
    unique: Set<int> = raw
    result: Array<int> = unique
    print(result.len())
    return 0
~
''', "3\n")

    def test_map_to_zip_back(self, expect_output):
        """Map → Zip → Map roundtrip."""
        expect_output('''
func main() -> int
    original = {"a": 1, "b": 2, "c": 3}
    z: Zip<string, int> = original
    restored: Map<string, int> = z
    print(restored.get("b"))
    return 0
~
''', "2\n")

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_collections(self, expect_output):
        """Operations on empty collections."""
        expect_output('''
func main() -> int
    empty_list: List<int> = []
    empty_map: Map<int, int> = {}
    empty_set: Set<int> = {}
    empty_array: Array<int> = []
    print(empty_list.len())
    print(empty_map.len())
    print(empty_set.len())
    print(empty_array.len())
    return 0
~
''', "0\n0\n0\n0\n")

    def test_single_element(self, expect_output):
        """Single element collections."""
        expect_output('''
func main() -> int
    list = [42]
    map = {1: 10}
    set = {99}
    arr: Array<int> = [7]
    print(list.get(0))
    print(map.get(1))
    print(set.has(99))
    print(arr.get(0))
    return 0
~
''', "42\n10\ntrue\n7\n")

    def test_many_assignments(self, expect_output):
        """Many assignments (stress test refcounting)."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a
    c = b
    d = c
    e = d
    f = e
    g = f
    h = g
    print(h.len())
    return 0
~
''', "3\n")

    def test_many_mutations(self, expect_output):
        """Many mutations (stress test structural sharing)."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    for i in 0..50
        m = m.set(i, i * 2)
    ~
    for i in 0..25
        m = m.remove(i * 2)
    ~
    print(m.len())
    return 0
~
''', "25\n")

class TestConcurrencyReadiness:
    """Test patterns that will be used with concurrency."""

    def test_pass_to_function_cow(self, expect_output):
        """Passing collections to functions uses COW."""
        expect_output('''
func process(data: Array<int>) -> int
    data.set(0, 999)
    return data.get(0)
~

func main() -> int
    arr: Array<int> = [1, 2, 3]
    result = process(arr)
    print(arr.get(0))
    print(result)
    return 0
~
''', "1\n999\n")

    def test_return_collection(self, expect_output):
        """Returning collections from functions."""
        expect_output('''
func make_list() -> List<int>
    result = [1, 2, 3]
    result = result.append(4)
    return result
~

func main() -> int
    list = make_list()
    print(list.len())
    print(list.get(3))
    return 0
~
''', "4\n4\n")

class TestMemorySafety:
    """Tests designed to catch memory issues."""

    def test_scope_exit_cleanup(self, expect_output):
        """Collections cleaned up on scope exit."""
        expect_output('''
func inner() -> int
    local = [1, 2, 3, 4, 5]
    local = local.append(6)
    return local.len()
~

func main() -> int
    for i in 0..100
        result = inner()
    ~
    print(result)
    return 0
~
''', "6\n")

    def test_overwrite_variable(self, expect_output):
        """Overwriting variable cleans up old value."""
        expect_output('''
func main() -> int
    var x = [1, 2, 3]
    x = [4, 5, 6]
    x = [7, 8, 9]
    print(x.get(0))
    return 0
~
''', "7\n")

    def test_conditional_assignment(self, expect_output):
        """Conditional paths with different collections."""
        expect_output('''
func main() -> int
    var x: List<int> = []
    for i in 0..5
        if i % 2 == 0
            x = x.append(i)
        ~
    ~
    print(x.len())
    return 0
~
''', "3\n")
```

## Verification Steps

### Step 1: Run All Tests

```bash
python3 -m pytest tests/ -v --tb=short
```

All tests from Sessions 1-9 plus new integration tests must pass.

### Step 2: Check for Memory Leaks

Run with memory sanitizer if available:
```bash
# Compile with sanitizers
python3 coexc.py test.coex -o test --sanitize=address

# Or use valgrind
valgrind --leak-check=full ./test
```

### Step 3: Check for Use-After-Free

The test suite should catch most issues, but also:
- Review refcount decrement paths
- Ensure decref is called exactly once per incref
- Check that freed memory isn't accessed

### Step 4: Performance Sanity Check

Not a formal benchmark, but verify operations are reasonably fast:

```coex
func main() -> int
    list: List<int> = []
    for i in 0..10000
        list = list.append(i)
    ~
    print(list.len())
    return 0
~
```

This should complete quickly (under 1 second).

### Step 5: Documentation Updates

Update CLAUDE.md and any other docs to reflect:
- New Array/String COW behavior
- New `:=` operator
- New List/Map/Set persistent structures
- Type conversion capabilities
- Updated method signatures

## Polish Tasks

### 1. Error Messages

Ensure clear error messages for:
- Use after move
- Type mismatch in conversion
- Out of bounds access
- Invalid operations

### 2. Consistent Naming

Verify method names are consistent:
- `.len()` on all collections
- `.get()` for indexed access
- `.set()` for updating
- `.add()` for Set (not `.append()`)
- `.append()` for List
- `.has()` for membership

### 3. Edge Case Handling

Verify graceful handling of:
- Empty collections
- Single elements
- Very large collections
- Deeply nested structures
- Maximum tree depth

### 4. Remove Dead Code

Clean up any:
- Old eager-copy code paths
- Unused helper functions
- Commented-out experiments

## Success Criteria

1. All tests pass (Sessions 1-9 + integration)
2. No memory leaks detected
3. No use-after-free errors
4. Performance is reasonable
5. Error messages are clear
6. Documentation is updated
7. Code is clean and consistent

## Summary

After this session, the Coex compiler has:

| Feature | Implementation |
|---------|---------------|
| Array | COW with atomic refcount |
| String | COW with atomic refcount, len/size tracking |
| List | Persistent Vector (32-way trie) |
| Map | HAMT (32-way trie with bitmap) |
| Set | HAMT (shared infrastructure with Map) |
| `:=` operator | Move semantics with use-after-move detection |
| Type conversions | List↔Array, Set↔Array, Map↔Zip |

Value semantics are preserved throughout:
- Assignment is cheap (O(1) via sharing)
- Mutation is efficient (O(log n) path copy or COW)
- No aliasing visible to the programmer
- Safe for concurrent access

## Files to Modify

- `tests/test_integration.py` - New test file
- `CLAUDE.md` - Update documentation
- `codegen.py` - Any final fixes

## Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v --tb=short

# Run only integration tests
python3 -m pytest tests/test_integration.py -v --tb=short

# Run with coverage
python3 -m pytest tests/ -v --cov=. --cov-report=html
```
