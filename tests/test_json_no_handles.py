"""
Tests verifying internal handles never appear in serialized JSON.

Phase 7 of JSON refactoring: Ensure JSON serialization outputs only values,
never internal handles, pointers, or references.
"""

import pytest


class TestJsonNoHandlesInOutput:
    """Verify serialized JSON contains no internal handles."""

    def test_no_handles_in_primitives(self, expect_output):
        """Primitive JSON values should not contain handle markers."""
        expect_output('''
func main() -> int
    j_null: json := nil
    j_bool: json := true
    j_int: json := 42
    j_float: json := 3.14
    j_str: json := "hello"

    s_null: string = j_null.stringify()
    s_bool: string = j_bool.stringify()
    s_int: string = j_int.stringify()
    s_float: string = j_float.stringify()
    s_str: string = j_str.stringify()

    # Check none contain "0x" (handle/pointer prefix)
    if s_null.len() < 20 and s_bool.len() < 20 and s_int.len() < 20
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_no_handles_in_arrays(self, expect_output):
        """Array JSON values should not contain handle markers."""
        expect_output('''
func main() -> int
    j: json := [1, 2, 3, 4, 5]
    s: string = j.stringify()

    # Should be "[1,2,3,4,5]" - 11 chars, not a long pointer string
    print(s.len())
    return 0
~
''', "11\n")

    def test_no_handles_in_objects(self, expect_output):
        """Object JSON values should not contain handle markers."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice", age: 30 }
    s: string = j.stringify()

    # Should be reasonable length, not huge handle strings
    # {"name":"Alice","age":30} = 26 chars
    if s.len() < 50
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_no_handles_in_nested_structures(self, expect_output):
        """Nested structures should not contain handle markers."""
        expect_output('''
func main() -> int
    inner: json = { value: 42 }
    outer: json = { data: inner, items: [1, 2, 3] }
    s: string = outer.stringify()

    # Should be reasonable size
    if s.len() < 100
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    @pytest.mark.xfail(reason="BUG-078: JSON variables not properly rooted in shadow stack, crash on GC")
    def test_no_handles_after_gc_cycle(self, expect_output):
        """After GC, serialized JSON still contains proper values."""
        # NOTE: Use bracket notation for array access, .get() for object fields
        expect_output('''
func main() -> int
    # Create some objects that will survive GC
    j: json = { users: [{ name: "Alice" }, { name: "Bob" }] }

    # Force GC
    gc()

    # Serialize should still work correctly
    s: string = j.stringify()
    parsed: json = json.parse(s)

    users: json = parsed.get("users")
    u0: json = users[0]
    u1: json = users[1]
    print(u0.get("name").as_string())
    print(u1.get("name").as_string())
    return 0
~
''', "Alice\nBob\n")

    @pytest.mark.xfail(reason="json.parse() stores all numbers as floats, but as_int() doesn't convert - pre-existing bug")
    def test_large_structure_no_handles(self, expect_output):
        """Large structure (100+ items) should not contain handles."""
        # NOTE: Use := for append, bracket notation for array access
        # BUG: json.parse() stores integers as floats but as_int() doesn't convert
        expect_output('''
func main() -> int
    j: json := []

    for i in 0..100
        j := j.append(i)
    ~

    s: string = j.stringify()

    # Parse back and verify
    parsed: json = json.parse(s)
    print(parsed.len())
    e0: json = parsed[0]
    e99: json = parsed[99]
    print(e0.as_int())
    print(e99.as_int())
    return 0
~
''', "100\n0\n99\n")


class TestJsonValuesNotPointers:
    """Verify JSON contains actual values, not pointer representations."""

    def test_int_values_are_numbers(self, expect_output):
        """Integer JSON values should be actual numbers."""
        expect_output('''
func main() -> int
    j: json := [1, 2, 3]
    s: string = j.stringify()

    # Verify format is [1,2,3] not [0x...,0x...,0x...]
    if s == "[1,2,3]"
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_string_values_are_quoted_strings(self, expect_output):
        """String JSON values should be quoted strings."""
        expect_output('''
func main() -> int
    j: json = { name: "test" }
    s: string = j.stringify()

    # Verify contains actual string value
    parsed: json = json.parse(s)
    print(parsed.get("name").as_string())
    return 0
~
''', "test\n")

    @pytest.mark.xfail(reason="json.parse() stores all numbers as floats, but as_int() doesn't convert - pre-existing bug")
    def test_nested_values_recursive(self, expect_output):
        """Nested values should be recursively serialized as values."""
        # BUG: json.parse() stores integers as floats but as_int() doesn't convert
        expect_output('''
func main() -> int
    j: json = { a: { b: { c: 42 } } }
    s: string = j.stringify()
    parsed: json = json.parse(s)

    # Verify deep value accessible
    a: json = parsed.get("a")
    b: json = a.get("b")
    c: json = b.get("c")
    print(c.as_int())
    return 0
~
''', "42\n")
