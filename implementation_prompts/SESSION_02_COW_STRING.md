# Session 2: Copy-on-Write for String

## Context

This is Session 2 of 10 implementing the optimized memory model for Coex.

**Completed:**
- Session 1: Array now has COW with atomic refcount

**This Session:**
- Apply the same COW pattern to String

**Coming Next:**
- Session 3: `:=` (move/eager assign) operator

### Why COW for String?

Strings in Coex are used heavily for network I/O. Large payloads pass between tasks constantly. Without COW, every assignment copies the entire string buffer. With COW:
- Assignment is O(1) - just bump refcount
- Mutation copies only when shared
- Read-only passes (parsing, validation) never copy

## New String Struct Layout

Data pointer FIRST for fast dereferencing, plus separate len (codepoints) and size (bytes):

```
+----------+----------+----------+----------+----------+
| data*    | refcount | len      | size     | cap      |
| i8*      | i64      | i64      | i64      | i64      |
| field 0  | field 1  | field 2  | field 3  | field 4  |
| offset 0 | offset 8 | offset 16| offset 24| offset 32|
+----------+----------+----------+----------+----------+

- data: pointer to UTF-8 bytes (field 0 for fast *string_ptr access)
- refcount: for COW
- len: UTF-8 codepoint count (what .len() returns to user)
- size: byte count (internal use for memory operations)
- cap: capacity in bytes (for efficient appends)
```

## Current State

Check current String implementation:
```bash
grep -n "string_struct" codegen.py | head -30
```

The current String struct likely has a simpler layout. This session:
1. Restructures String with the new layout
2. Adds refcount and COW logic following the Array pattern from Session 1

## Goals for This Session

1. Write failing tests expressing COW behavior for String
2. Restructure String struct with new layout (data first, add refcount, len, size, cap)
3. Implement atomic refcount operations for String
4. Change String assignment to bump refcount
5. Ensure String operations respect COW semantics
6. Make all tests pass

## Test-Driven Development

Write these tests FIRST in `tests/test_cow_string.py`. They should FAIL initially.

```python
import pytest

class TestStringCOW:
    """Test Copy-on-Write semantics for String type."""

    def test_string_assignment_shares_data(self, expect_output):
        """Assignment should not copy - both variables share buffer."""
        expect_output('''
func main() -> int
    a = "hello world"
    b = a
    print(b)
    return 0
~
''', "hello world\n")

    def test_string_cow_on_concat(self, expect_output):
        """Concatenation creates new string, original unchanged."""
        expect_output('''
func main() -> int
    a = "hello"
    b = a
    b = b + " world"
    print(a)
    print(b)
    return 0
~
''', "hello\nhello world\n")

    def test_string_sole_owner_concat(self, expect_output):
        """Concatenation with sole owner."""
        expect_output('''
func main() -> int
    a = "hello"
    a = a + " world"
    a = a + "!"
    print(a)
    return 0
~
''', "hello world!\n")

    def test_string_multiple_assignments(self, expect_output):
        """Multiple assignments should all share until mutation."""
        expect_output('''
func main() -> int
    a = "original"
    b = a
    c = a
    d = b
    c = c + " modified"
    print(a)
    print(b)
    print(c)
    print(d)
    return 0
~
''', "original\noriginal\noriginal modified\noriginal\n")

    def test_string_cow_with_functions(self, expect_output):
        """COW should work correctly when passing to functions."""
        expect_output('''
func modify(s: string) -> string
    return s + " modified"
~

func main() -> int
    a = "original"
    result = modify(a)
    print(a)
    print(result)
    return 0
~
''', "original\noriginal modified\n")

    def test_string_len_no_cow(self, expect_output):
        """len() is read-only, should not trigger copy."""
        expect_output('''
func main() -> int
    a = "hello"
    b = a
    print(b.len())
    print(a.len())
    return 0
~
''', "5\n5\n")

    def test_string_len_utf8(self, expect_output):
        """len() returns codepoint count, not byte count."""
        expect_output('''
func main() -> int
    a = "héllo"
    print(a.len())
    return 0
~
''', "5\n")

    def test_string_comparison_no_cow(self, expect_output):
        """String comparison is read-only, no copy needed."""
        expect_output('''
func main() -> int
    a = "hello"
    b = a
    if a == b
        print("equal")
    ~
    return 0
~
''', "equal\n")

    def test_string_large_payload(self, expect_output):
        """Large strings should benefit from COW (no copy on assignment)."""
        expect_output('''
func make_large() -> string
    s = "x"
    for i in 0..10
        s = s + s
    ~
    return s
~

func main() -> int
    large = make_large()
    copy1 = large
    copy2 = large
    copy3 = large
    print(large.len())
    print(copy1.len())
    return 0
~
''', "1024\n1024\n")

    def test_string_iteration_no_cow(self, expect_output):
        """Iterating over string (read-only) should not trigger copy."""
        expect_output('''
func main() -> int
    a = "abc"
    b = a
    count = 0
    for c in b
        count = count + 1
    ~
    print(count)
    print(a)
    return 0
~
''', "3\nabc\n")

    def test_string_in_array(self, expect_output):
        """Strings in arrays should maintain COW semantics."""
        expect_output('''
func main() -> int
    arr: Array<string> = ["hello", "world"]
    s = arr.get(0)
    s = s + "!"
    print(arr.get(0))
    print(s)
    return 0
~
''', "hello\nhello!\n")
```

## Implementation Steps

### Step 1: Understand Current String Structure

First, examine the current String implementation:
```bash
grep -n "string_struct\|String\|_string" codegen.py | head -80
```

Identify:
- Current struct fields
- Where strings are allocated
- String literal handling
- String concatenation implementation

### Step 2: Modify String Struct

Change to new layout with data pointer first:

```python
# Current (find and replace):
self.string_struct.set_body(
    # ... current fields ...
)

# New layout:
self.string_struct.set_body(
    ir.IntType(8).as_pointer(),  # data (field 0 - fast access)
    ir.IntType(64),  # refcount (field 1)
    ir.IntType(64),  # len - codepoint count (field 2)
    ir.IntType(64),  # size - byte count (field 3)
    ir.IntType(64),  # cap - capacity in bytes (field 4)
)
```

### Step 3: Update All Field Index Constants

Update ALL GEP operations on string_struct. Create a reference:

| Field    | New Index | Purpose |
|----------|-----------|---------|
| data     | 0         | UTF-8 byte pointer |
| refcount | 1         | COW reference count |
| len      | 2         | Codepoint count (.len()) |
| size     | 3         | Byte count (memory ops) |
| cap      | 4         | Capacity in bytes |

### Step 4: Add String Refcount Helpers

Follow the Array pattern from Session 1:

```python
def _implement_string_incref(self):
    """Atomically increment string refcount."""
    # string_incref(str: String*) -> void

def _implement_string_decref(self):
    """Atomically decrement refcount, free if zero."""
    # string_decref(str: String*) -> void

def _implement_string_ensure_unique(self):
    """If refcount > 1, copy string. Return unique pointer."""
    # string_ensure_unique(str: String*) -> String*
```

Consider sharing implementation with Array helpers if struct layouts allow.

### Step 5: Handle String Literals

String literals are special - they're in read-only memory. Options:

**Option A: Immortal refcount**
```python
# Set refcount to MAX_INT64 or -1 to mean "never free"
IMMORTAL_REFCOUNT = 0x7FFFFFFFFFFFFFFF
# In decref: if refcount == IMMORTAL, don't decrement
```

**Option B: Copy on first assignment**
```python
# Literals always copied to heap on first use
# Simpler but wastes memory for read-only strings
```

**Recommended: Option A** - immortal literals, only heap strings are refcounted.

### Step 6: Update String Creation

When creating strings (literals, concatenation results):
- Set refcount appropriately (1 for heap strings, IMMORTAL for literals)
- Calculate both len (codepoints) and size (bytes)
- Set capacity

### Step 7: Update String Assignment

Change from copy to incref:
```python
# OLD: Copy string buffer on assignment
new_str = copy_string(old_str)

# NEW: Just bump refcount
incref(old_str)
# Store same pointer
```

### Step 8: Update String Concatenation

String concat (`+`) typically creates a new string:
```python
def string_concat(a, b):
    # Allocate new buffer with size = a.size + b.size
    # Copy bytes from a and b
    # Set refcount = 1 (new string)
    # Calculate new len = a.len + b.len
    # Return new string
```

The COW benefit here is that `a` and `b` don't need to be copied - they're just read.

### Step 9: Update len() Method

Ensure `.len()` returns the `len` field (codepoint count), not `size` (byte count).

## Technical Notes

### UTF-8 Codepoint Counting

When creating strings, you need to count UTF-8 codepoints:
```python
# Pseudocode for counting codepoints
codepoints = 0
i = 0
while i < byte_length:
    byte = data[i]
    if (byte & 0x80) == 0:      # ASCII: 0xxxxxxx
        i += 1
    elif (byte & 0xE0) == 0xC0:  # 2-byte: 110xxxxx
        i += 2
    elif (byte & 0xF0) == 0xE0:  # 3-byte: 1110xxxx
        i += 3
    elif (byte & 0xF8) == 0xF0:  # 4-byte: 11110xxx
        i += 4
    codepoints += 1
```

This can be done at string creation time and cached in the `len` field.

### Struct Size

New struct is 40 bytes (5 × 8-byte fields). Update allocation size constants.

### Atomic Operations

Same as Array:
```python
old = builder.atomic_rmw('add', refcount_ptr, ir.Constant(ir.IntType(64), 1), 'seq_cst')
old = builder.atomic_rmw('sub', refcount_ptr, ir.Constant(ir.IntType(64), 1), 'seq_cst')
```

## Success Criteria

1. All tests in `test_cow_string.py` pass
2. String assignment is O(1) - just refcount bump
3. String concatenation creates new string with refcount 1
4. `.len()` returns codepoint count (not byte count)
5. String literals are handled correctly (immortal or copied)
6. No memory leaks
7. Thread-safe refcount operations
8. All existing tests continue to pass (including Session 1 Array tests)

## What This Enables

After this session:
- Both Array and String have COW semantics
- Large network payloads can be passed cheaply between tasks
- Foundation for `:=` operator (Session 3)

## Files to Modify

- `codegen.py` - COW implementation for String
- `tests/test_cow_string.py` - New test file (write first!)

## Running Tests

```bash
# Write tests first, verify they fail
python3 -m pytest tests/test_cow_string.py -v --tb=short

# After implementation
python3 -m pytest tests/test_cow_string.py -v --tb=short

# Verify no regressions (including Session 1 Array tests)
python3 -m pytest tests/ -v --tb=short
```
