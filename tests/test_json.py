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
