# Session 1: Copy-on-Write for Array

## Context

Coex is a concurrent programming language with value semantics. We are implementing an optimized memory model:

- **List, Map, Set**: Will use persistent data structures with structural sharing (future sessions)
- **Array, String**: Will use Copy-on-Write (COW) with atomic reference counting

The principle: assignment is cheap (just bump refcount), mutation pays the cost (copy only if refcount > 1).

### Why COW for Array?

1. Arrays must remain contiguous in memory for O(1) indexing
2. Coex passes large data between concurrent tasks
3. COW defers copy cost until mutation actually occurs
4. Read-only passes never pay the copy cost

## Current State

Array already exists in `codegen.py` with this structure:
```
struct Array { i64 len, i64 cap, i64 elem_size, i8* data }
```

Current behavior (EAGER COPY - to be changed):
- `array_set` creates a NEW array and copies ALL data on every call
- `array_append` creates a NEW array and copies ALL data on every call
- Assignment copies the entire array

This session changes to COW:
- Restructure Array with data pointer first and add refcount
- Assignment bumps refcount (O(1))
- Mutation copies only if refcount > 1

## Goals for This Session

1. Write failing tests expressing COW behavior
2. Restructure Array struct with new layout
3. Implement atomic refcount operations
4. Change assignment to bump refcount instead of copying
5. Change mutations to check refcount and copy only when shared
6. Make all tests pass

## New Array Struct Layout

Data pointer FIRST for fast dereferencing (`*array_ptr` yields data directly):

```
+----------+----------+----------+----------+----------+
| data*    | refcount | len      | cap      | elem_size|
| i8*      | i64      | i64      | i64      | i64      |
| field 0  | field 1  | field 2  | field 3  | field 4  |
| offset 0 | offset 8 | offset 16| offset 24| offset 32|
+----------+----------+----------+----------+----------+
```

**Why data first?** With data at offset 0, `*array_ptr` directly yields the data pointer without offset calculation. This optimizes the common case of accessing array elements.

## Test-Driven Development

Write these tests FIRST in `tests/test_cow_array.py`. They should FAIL initially.

```python
import pytest

class TestArrayCOW:
    """Test Copy-on-Write semantics for Array type."""

    def test_array_creation_from_list(self, expect_output):
        """Array can be created by type conversion from List."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    print(a.get(0))
    print(a.get(1))
    print(a.get(2))
    print(a.len())
    return 0
~
''', "1\n2\n3\n3\n")

    def test_array_assignment_shares_data(self, expect_output):
        """Assignment should not copy - both variables share buffer."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b = a
    print(b.get(0))
    print(b.get(1))
    print(b.get(2))
    return 0
~
''', "1\n2\n3\n")

    def test_array_cow_on_set(self, expect_output):
        """Mutation via set() should copy, leaving original unchanged."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b = a
    b.set(1, 99)
    print(a.get(1))
    print(b.get(1))
    return 0
~
''', "2\n99\n")

    def test_array_cow_on_append(self, expect_output):
        """Mutation via append() should copy, leaving original unchanged."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2]
    b = a
    b.append(3)
    print(a.len())
    print(b.len())
    return 0
~
''', "2\n3\n")

    def test_array_sole_owner_no_copy(self, expect_output):
        """When sole owner (refcount=1), mutation should be in-place."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    a.set(0, 10)
    a.set(1, 20)
    a.set(2, 30)
    print(a.get(0))
    print(a.get(1))
    print(a.get(2))
    return 0
~
''', "10\n20\n30\n")

    def test_array_multiple_assignments(self, expect_output):
        """Multiple assignments should all share until mutation."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b = a
    c = a
    d = b
    c.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    print(d.get(0))
    return 0
~
''', "1\n1\n99\n1\n")

    def test_array_cow_independence_after_mutation(self, expect_output):
        """After COW copy, the copies are fully independent."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2]
    b = a
    b.set(0, 10)
    a.set(0, 20)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "20\n10\n")

    def test_array_cow_with_functions(self, expect_output):
        """COW should work correctly when passing to functions."""
        expect_output('''
func modify(arr: Array<int>) -> int
    arr.set(0, 99)
    return arr.get(0)
~

func main() -> int
    a: Array<int> = [1, 2, 3]
    result = modify(a)
    print(a.get(0))
    print(result)
    return 0
~
''', "1\n99\n")

    def test_array_iteration_no_cow(self, expect_output):
        """Iteration (read-only) should not trigger copy."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3]
    b = a
    sum = 0
    for x in b
        sum = sum + x
    ~
    print(sum)
    print(a.get(0))
    return 0
~
''', "6\n1\n")

    def test_array_len_no_cow(self, expect_output):
        """len() is read-only, should not trigger copy."""
        expect_output('''
func main() -> int
    a: Array<int> = [1, 2, 3, 4, 5]
    b = a
    print(b.len())
    b.set(0, 99)
    print(a.len())
    print(b.len())
    return 0
~
''', "5\n5\n5\n")

    def test_array_of_strings(self, expect_output):
        """COW should work with Array<string>."""
        expect_output('''
func main() -> int
    a: Array<string> = ["hello", "world"]
    b = a
    b.set(0, "goodbye")
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "hello\ngoodbye\n")
```

## Implementation Steps

### Step 1: Modify Array Struct

In `codegen.py`, change the Array struct to new layout (data pointer first):

```python
# Find current definition (around line 180-187):
self.array_struct.set_body(
    ir.IntType(64),  # len
    ir.IntType(64),  # cap
    ir.IntType(64),  # elem_size
    ir.IntType(8).as_pointer()  # data
)

# Change to:
self.array_struct.set_body(
    ir.IntType(8).as_pointer(),  # data (field 0 - fast access via *ptr)
    ir.IntType(64),  # refcount (field 1)
    ir.IntType(64),  # len (field 2)
    ir.IntType(64),  # cap (field 3)
    ir.IntType(64),  # elem_size (field 4)
)
```

### Step 2: Update All Field Index Constants

Search and update ALL GEP operations on array_struct. The field mapping changes:

| Field     | Old Index | New Index |
|-----------|-----------|-----------|
| data      | 3         | 0         |
| refcount  | N/A       | 1 (NEW)   |
| len       | 0         | 2         |
| cap       | 1         | 3         |
| elem_size | 2         | 4         |

Use this to find all occurrences:
```bash
grep -n "gep.*array\|array.*gep" codegen.py
```

### Step 3: Add Refcount Helper Functions

```python
def _implement_array_incref(self):
    """Atomically increment refcount."""
    # Create function: array_incref(arr: Array*) -> void
    # Use: builder.atomic_rmw('add', refcount_ptr, 1, 'seq_cst')

def _implement_array_decref(self):
    """Atomically decrement refcount. Free if reaches 0."""
    # Create function: array_decref(arr: Array*) -> void
    # old = builder.atomic_rmw('sub', refcount_ptr, 1, 'seq_cst')
    # if old == 1: free data buffer, free array struct

def _implement_array_ensure_unique(self):
    """If refcount > 1, copy array and decref original. Return (possibly new) pointer."""
    # Create function: array_ensure_unique(arr: Array*) -> Array*
    # This is the core COW logic:
    # if refcount == 1: return arr (already unique)
    # else: copy = deep_copy(arr); decref(arr); return copy
```

### Step 4: Initialize Refcount in array_new

In `_implement_array_new()`, set refcount to 1 after allocation:
```python
refcount_ptr = builder.gep(array_ptr,
    [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)],
    inbounds=True)
builder.store(ir.Constant(ir.IntType(64), 1), refcount_ptr)
```

### Step 5: Change Assignment to Bump Refcount

Find where Array values are copied on assignment. Currently this likely calls `array_copy`. Change to:
1. Call `array_incref(source)`
2. Return/store the same pointer (not a copy)

Look for `_deep_copy_value` or similar functions that handle Array.

### Step 6: Modify Mutating Operations for COW

In `_implement_array_set()`:
```python
# OLD: Always create new array and copy
new_arr = builder.call(self.array_new, [old_cap, elem_size])
# ... copy all data ...

# NEW: Ensure unique first, then mutate in place
unique_arr = builder.call(self.array_ensure_unique, [old_arr])
# ... mutate unique_arr directly ...
# return unique_arr
```

Same pattern for `_implement_array_append()`.

### Step 7: Handle Scope Exit / Cleanup

When an Array variable goes out of scope, call `array_decref`. This may already be handled by existing cleanup code, but verify it calls decref (not free directly).

## Technical Notes

### Atomic Operations in LLVM IR

```python
# Atomic increment (returns old value)
old = builder.atomic_rmw('add', refcount_ptr, ir.Constant(ir.IntType(64), 1), 'seq_cst')

# Atomic decrement (returns old value)
old = builder.atomic_rmw('sub', refcount_ptr, ir.Constant(ir.IntType(64), 1), 'seq_cst')

# If old == 1, new value is 0, so we should free
is_last = builder.icmp_unsigned('==', old, ir.Constant(ir.IntType(64), 1))
with builder.if_then(is_last):
    # Free data buffer
    # Free array struct
```

### Struct Size

New struct is 40 bytes (5 × 8-byte fields). Update allocation size constants.

### List → Array Conversion

When converting List to Array (via type annotation `a: Array<int> = [1,2,3]`), ensure the new Array has refcount = 1.

## Success Criteria

1. All tests in `test_cow_array.py` pass
2. Array assignment is O(1) - just refcount bump, not data copy
3. Mutations copy only when refcount > 1
4. Sole owner mutations are in-place (no copy)
5. No memory leaks (refcount 0 → free)
6. Thread-safe refcount operations (atomic)
7. ALL existing tests continue to pass (no regressions)

## What This Enables

After this session:
- Array has COW semantics
- Foundation for String COW (Session 2)
- Foundation for `:=` operator (Session 3)

## Files to Modify

- `codegen.py` - Main implementation
- `tests/test_cow_array.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_cow_array.py -v --tb=short

# After implementation
python3 -m pytest tests/test_cow_array.py -v --tb=short

# Verify no regressions
python3 -m pytest tests/ -v --tb=short
```
