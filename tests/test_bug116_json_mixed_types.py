"""Tests for BUG-116: Mixed-type map literal to JSON conversion.

convert_map_to_json_object inferred a single value_type from the first entry
and applied it to ALL values. For mixed-type maps (e.g. {"name": "test", "value": 42}),
this caused segfaults or value corruption because the wrong type was used for
subsequent entries.

The fix intercepts MapExpr in convert_to_json and builds JSON directly from
expression entries, converting each value individually with its correct
compile-time type.
"""

import pytest


class TestMixedTypeMapToJson:
    """Test map literals with mixed value types converted to JSON."""

    def test_string_then_int(self, expect_output):
        """String value followed by int value — the original crash case."""
        expect_output('''
func main() -> int
    data: json := {"name": "test", "value": 42}
    s = data.stringify()
    # Check both keys are present (order may vary)
    print(s.len() > 10)
    return 0
~
''', "true\n")

    def test_int_then_string(self, expect_output):
        """Int value followed by string value."""
        expect_output('''
func main() -> int
    data: json := {"a": 1, "b": "hello"}
    s = data.stringify()
    print(s.len() > 5)
    return 0
~
''', "true\n")

    def test_mixed_stringify_values(self, expect_output):
        """Verify actual values are correct for mixed int+string."""
        expect_output('''
func main() -> int
    data: json := {"count": 5, "label": "items"}
    print(data.get("count").as_int())
    print(data.get("label").as_string())
    return 0
~
''', "5\nitems\n")

    def test_mixed_int_float(self, expect_output):
        """Mixed int and float values."""
        expect_output('''
func main() -> int
    data: json := {"x": 1, "y": 3.14}
    print(data.get("x").as_int())
    print(data.get("y").as_float())
    return 0
~
''', "1\n3.140000\n")

    def test_mixed_string_bool(self, expect_output):
        """Mixed string and bool values."""
        expect_output('''
func main() -> int
    data: json := {"name": "Alice", "active": true}
    print(data.get("name").as_string())
    print(data.get("active").as_bool())
    return 0
~
''', "Alice\ntrue\n")

    def test_mixed_int_bool(self, expect_output):
        """Mixed int and bool values."""
        expect_output('''
func main() -> int
    data: json := {"count": 10, "done": false}
    print(data.get("count").as_int())
    print(data.get("done").as_bool())
    return 0
~
''', "10\nfalse\n")

    def test_three_different_types(self, expect_output):
        """Three different value types in one map literal."""
        expect_output('''
func main() -> int
    data: json := {"name": "test", "value": 42, "ratio": 0.5}
    print(data.get("name").as_string())
    print(data.get("value").as_int())
    print(data.get("ratio").as_float())
    return 0
~
''', "test\n42\n0.500000\n")

    def test_four_different_types(self, expect_output):
        """Four different value types."""
        expect_output('''
func main() -> int
    data: json := {"s": "hi", "i": 7, "f": 2.5, "b": true}
    print(data.get("s").as_string())
    print(data.get("i").as_int())
    print(data.get("f").as_float())
    print(data.get("b").as_bool())
    return 0
~
''', "hi\n7\n2.500000\ntrue\n")


class TestMixedTypeJsonPretty:
    """Test pretty-printing mixed-type JSON objects (original crash in BUG-116)."""

    def test_pretty_mixed_string_int(self, expect_output):
        """Pretty-print with mixed string and int values."""
        expect_output('''
func main() -> int
    data: json := {"name": "test", "value": 42}
    result = data.pretty(2)
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_pretty_mixed_with_gc(self, expect_output):
        """Pretty-print mixed types under GC pressure."""
        expect_output('''
func main() -> int
    data: json := {"name": "test", "value": 42, "active": true}
    gc()
    result = data.pretty(2)
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")


class TestHomogeneousMapToJson:
    """Ensure homogeneous maps still work after the fix."""

    def test_all_ints(self, expect_output):
        """All integer values (should still work)."""
        expect_output('''
func main() -> int
    data: json := {"a": 1, "b": 2, "c": 3}
    print(data.get("a").as_int())
    print(data.get("b").as_int())
    print(data.get("c").as_int())
    return 0
~
''', "1\n2\n3\n")

    def test_all_strings(self, expect_output):
        """All string values (should still work)."""
        expect_output('''
func main() -> int
    data: json := {"a": "x", "b": "y", "c": "z"}
    print(data.get("a").as_string())
    print(data.get("b").as_string())
    print(data.get("c").as_string())
    return 0
~
''', "x\ny\nz\n")

    def test_all_bools(self, expect_output):
        """All boolean values (should still work)."""
        expect_output('''
func main() -> int
    data: json := {"a": true, "b": false, "c": true}
    print(data.get("a").as_bool())
    print(data.get("b").as_bool())
    print(data.get("c").as_bool())
    return 0
~
''', "true\nfalse\ntrue\n")


class TestMixedTypeJsonStress:
    """Stress tests for mixed-type JSON under GC pressure."""

    def test_mixed_type_stringify_gc_stress(self, expect_output):
        """Repeated mixed-type JSON creation with GC pressure."""
        expect_output('''
func main() -> int
    i = 0
    while i < 20
        data: json := {"idx": i, "label": "item"}
        s = data.stringify()
        if i % 5 == 0
            gc()
        ~
        i = i + 1
    ~
    print("done")
    return 0
~
''', "done\n")

    def test_mixed_type_with_nested_json(self, expect_output):
        """Mixed types including a nested JSON value."""
        expect_output('''
func main() -> int
    inner: json := [1, 2, 3]
    data: json := {"values": inner, "count": 3}
    print(data.get("count").as_int())
    arr: json = data.get("values")
    print(arr.len())
    return 0
~
''', "3\n3\n")
