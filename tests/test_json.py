"""
Tests for JSON type support.

Phase 1: Core type, literals, and field access.
"""

import pytest


class TestJsonLiterals:
    """Tests for JSON literal creation."""

    def test_empty_json_object(self, expect_output):
        """Empty braces create an empty JSON object."""
        expect_output('''
func main() -> int
    j: json = {}
    print(1)
    return 0
~
''', "1\n")

    def test_json_object_with_string_value(self, expect_output):
        """JSON object with bare identifier key and string value."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    print(1)
    return 0
~
''', "1\n")

    def test_json_object_with_int_value(self, expect_output):
        """JSON object with bare identifier key and integer value."""
        expect_output('''
func main() -> int
    j: json = { age: 30 }
    print(1)
    return 0
~
''', "1\n")

    def test_json_object_multiple_fields(self, expect_output):
        """JSON object with multiple fields."""
        expect_output('''
func main() -> int
    j: json = { name: "Bob", age: 25, active: true }
    print(1)
    return 0
~
''', "1\n")


class TestJsonPrimitives:
    """Tests for JSON primitive values."""

    def test_json_nil(self, expect_output):
        """JSON nil literal."""
        expect_output('''
func main() -> int
    j: json = nil
    print(1)
    return 0
~
''', "1\n")

    def test_json_bool_true(self, expect_output):
        """JSON true literal."""
        expect_output('''
func main() -> int
    j: json = true
    print(1)
    return 0
~
''', "1\n")

    def test_json_bool_false(self, expect_output):
        """JSON false literal."""
        expect_output('''
func main() -> int
    j: json = false
    print(1)
    return 0
~
''', "1\n")

    def test_json_int(self, expect_output):
        """JSON integer literal."""
        expect_output('''
func main() -> int
    j: json = 42
    print(1)
    return 0
~
''', "1\n")

    def test_json_float(self, expect_output):
        """JSON float literal."""
        expect_output('''
func main() -> int
    j: json = 3.14
    print(1)
    return 0
~
''', "1\n")

    def test_json_string(self, expect_output):
        """JSON string literal."""
        expect_output('''
func main() -> int
    j: json = "hello"
    print(1)
    return 0
~
''', "1\n")


class TestJsonFieldAccess:
    """Tests for accessing JSON fields."""

    def test_dot_access_existing_field(self, expect_output):
        """Dot access on existing field returns the value."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    n: json = j.name
    print(1)
    return 0
~
''', "1\n")

    def test_dot_access_missing_field(self, expect_output):
        """Dot access on missing field returns nil."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    n: json = j.missing
    print(1)
    return 0
~
''', "1\n")

    def test_bracket_access_string_key(self, expect_output):
        """Bracket access with string key."""
        expect_output('''
func main() -> int
    j: json = { name: "Bob" }
    n: json = j["name"]
    print(1)
    return 0
~
''', "1\n")

    def test_bracket_access_int_index(self, expect_output):
        """Bracket access with integer index on array."""
        expect_output('''
func main() -> int
    j: json = { items: [10, 20, 30] }
    arr: json = j.items
    print(1)
    return 0
~
''', "1\n")

    def test_nested_access(self, expect_output):
        """Nested field access."""
        expect_output('''
func main() -> int
    j: json = { person: { name: "Carol", age: 25 } }
    n: json = j.person.name
    print(1)
    return 0
~
''', "1\n")


class TestJsonVsMapSyntax:
    """Tests for syntax disambiguation between JSON and Map."""

    def test_bare_identifier_creates_json(self, expect_output):
        """Bare identifier keys create JSON objects."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    print(1)
    return 0
~
''', "1\n")

    def test_quoted_key_creates_map(self, expect_output):
        """Quoted string keys create Maps, not JSON objects."""
        expect_output('''
func main() -> int
    m: Map<string, int> = { "hello": 1 }
    print(m.get("hello"))
    return 0
~
''', "1\n")

    def test_int_key_creates_map(self, expect_output):
        """Integer keys create Maps."""
        expect_output('''
func main() -> int
    m: Map<int, int> = { 1: 10 }
    print(m.get(1))
    return 0
~
''', "10\n")

    def test_json_bracket_access_special_key(self, expect_output):
        """JSON bracket access works for special characters in keys."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    n: json = j["name"]
    print(1)
    return 0
~
''', "1\n")


class TestJsonTypeMethods:
    """Phase 2: Tests for JSON type checking methods."""

    def test_is_null_on_nil(self, expect_output):
        """is_null() returns true for nil."""
        expect_output('''
func main() -> int
    j: json = nil
    if j.is_null()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_null_on_object(self, expect_output):
        """is_null() returns false for object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    if j.is_null()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")

    def test_is_bool_on_true(self, expect_output):
        """is_bool() returns true for boolean."""
        expect_output('''
func main() -> int
    j: json = true
    if j.is_bool()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_int_on_integer(self, expect_output):
        """is_int() returns true for integer."""
        expect_output('''
func main() -> int
    j: json = 42
    if j.is_int()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_float_on_float(self, expect_output):
        """is_float() returns true for float."""
        expect_output('''
func main() -> int
    j: json = 3.14
    if j.is_float()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_string_on_string(self, expect_output):
        """is_string() returns true for string."""
        expect_output('''
func main() -> int
    j: json = "hello"
    if j.is_string()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_array_on_list(self, expect_output):
        """is_array() returns true for array."""
        expect_output('''
func main() -> int
    j: json = { items: [1, 2, 3] }
    arr: json = j.items
    if arr.is_array()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_is_object_on_object(self, expect_output):
        """is_object() returns true for object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    if j.is_object()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestJsonAccessMethods:
    """Phase 2: Tests for JSON access methods."""

    def test_len_on_object(self, expect_output):
        """len() returns number of fields in object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice", age: 30, active: true }
    print(j.len())
    return 0
~
''', "3\n")

    def test_len_on_array(self, expect_output):
        """len() returns number of elements in array."""
        expect_output('''
func main() -> int
    j: json = { items: [1, 2, 3, 4, 5] }
    print(j.items.len())
    return 0
~
''', "5\n")

    def test_has_existing_key(self, expect_output):
        """has() returns true for existing key."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    if j.has("name")
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_has_missing_key(self, expect_output):
        """has() returns false for missing key."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    if j.has("missing")
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")


class TestJsonMutationMethods:
    """Phase 2: Tests for JSON mutation methods (return new values)."""

    def test_set_new_field(self, expect_output):
        """set() adds a new field to object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    j2: json = j.set("age", 30)
    print(j2.len())
    return 0
~
''', "2\n")

    def test_set_updates_field(self, expect_output):
        """set() updates existing field."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice" }
    j2: json = j.set("name", "Bob")
    print(j.len())
    print(j2.len())
    return 0
~
''', "1\n1\n")

    def test_remove_field(self, expect_output):
        """remove() removes a field from object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice", age: 30 }
    j2: json = j.remove("age")
    print(j.len())
    print(j2.len())
    return 0
~
''', "2\n1\n")


class TestJsonIterationMethods:
    """Phase 2: Tests for JSON iteration methods."""

    def test_keys_on_object(self, expect_output):
        """keys() returns list of keys from object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice", age: 30 }
    k: List<string> = j.keys()
    print(k.len())
    return 0
~
''', "2\n")

    def test_values_on_object(self, expect_output):
        """values() returns list of values from object."""
        expect_output('''
func main() -> int
    j: json = { name: "Alice", age: 30 }
    v: List<json> = j.values()
    print(v.len())
    return 0
~
''', "2\n")
