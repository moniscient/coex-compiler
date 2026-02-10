"""Tests for BUG-115: JSON codegen stale-pointer-across-allocation bugs.

These tests exercise the 9 fixed sites in json_type.py where raw pointers
derived from gc_handle_deref were used across allocating operations.
Each test triggers GC pressure to increase the chance of compaction
between handle deref and pointer use.
"""

import pytest


class TestJsonStringifyUnderGC:
    """Test JSON stringify functions with GC pressure."""

    def test_stringify_array_with_gc_pressure(self, expect_output):
        """_stringify_array: list_ptr re-derived each iteration (Finding 7)."""
        expect_output('''
func main() -> int
    data: json := [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    gc()
    result = data.stringify()
    gc()
    print(result)
    return 0
~
''', "[1,2,3,4,5,6,7,8,9,10]\n")

    def test_stringify_object_with_gc_pressure(self, expect_output):
        """_stringify_object: map_ptr and keys_list re-derived each iteration (Finding 6)."""
        expect_output('''
func main() -> int
    data: json := {"a": 1, "b": 2, "c": 3}
    gc()
    result = data.stringify()
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_stringify_nested_with_gc_pressure(self, expect_output):
        """Nested stringify exercises both array and object paths."""
        expect_output('''
func main() -> int
    inner: json := [10, 20, 30]
    outer: json := {"values": inner, "count": 3}
    gc()
    result = outer.stringify()
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_stringify_large_array_gc_stress(self, expect_output):
        """Large array stringify triggers many iterations with GC."""
        expect_output('''
func main() -> int
    arr: json = json.parse("[]")
    i = 0
    while i < 100
        arr = arr.append(i)
        i = i + 1
    ~
    gc()
    result = arr.stringify()
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")


class TestJsonPrettyPrintUnderGC:
    """Test JSON pretty-print with GC pressure."""

    def test_pretty_array_with_gc(self, expect_output):
        """_pretty_array: list_ptr re-derived each iteration (Finding 8)."""
        expect_output('''
func main() -> int
    data: json := [1, 2, 3]
    gc()
    result = data.pretty(2)
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_pretty_object_with_gc(self, expect_output):
        """_pretty_object: map_ptr and keys_list re-derived (Finding 9)."""
        expect_output('''
func main() -> int
    data: json := {"name": "test", "value": 42}
    gc()
    result = data.pretty(2)
    gc()
    print(result.len() > 0)
    return 0
~
''', "true\n")


class TestJsonParseUnderGC:
    """Test JSON parse with GC pressure."""

    def test_parse_array_with_gc(self, expect_output):
        """_implement_json_parse: data_ptr re-derived after alloc (Finding 10)."""
        expect_output('''
func main() -> int
    text = "[1, 2, 3, 4, 5]"
    gc()
    data: json = json.parse(text)
    gc()
    print(data.stringify())
    return 0
~
''', "[1,2,3,4,5]\n")

    def test_parse_object_with_gc(self, expect_output):
        """_implement_json_parse: data_ptr re-derived for object path (Finding 10)."""
        expect_output('''
func main() -> int
    text = "{\\"x\\": 1, \\"y\\": 2}"
    gc()
    data: json = json.parse(text)
    gc()
    result = data.stringify()
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_parse_roundtrip_with_gc(self, expect_output):
        """Parse then stringify with GC between each step."""
        expect_output('''
func main() -> int
    original = "[10, 20, 30]"
    gc()
    parsed: json = json.parse(original)
    gc()
    back = parsed.stringify()
    gc()
    print(back)
    return 0
~
''', "[10,20,30]\n")


class TestJsonSetFieldUnderGC:
    """Test json.set with GC pressure."""

    def test_set_field_with_gc(self, expect_output):
        """_implement_json_set_field: map_ptr re-derived after promote (Finding 14)."""
        expect_output('''
func main() -> int
    data: json := {"a": 1}
    gc()
    data = data.set("b", 2)
    gc()
    data = data.set("c", 3)
    gc()
    print(data.stringify().len() > 0)
    return 0
~
''', "true\n")

    def test_set_field_stress(self, expect_output):
        """Many set_field operations with GC pressure."""
        expect_output('''
func main() -> int
    data: json = json.parse("{}")
    i = 0
    while i < 50
        data = data.set("key_" + String.from(i), i)
        if i % 10 == 0
            gc()
        ~
        i = i + 1
    ~
    gc()
    result = data.stringify()
    print(result.len() > 0)
    return 0
~
''', "true\n")


class TestJsonConversionUnderGC:
    """Test list/map to JSON conversion with GC pressure."""

    def test_list_to_json_with_gc(self, expect_output):
        """_convert_list_runtime_to_json_array: list_ptr re-derived (Finding 12)."""
        expect_output('''
func main() -> int
    nums = [1, 2, 3, 4, 5]
    gc()
    data: json := nums
    gc()
    print(data.stringify())
    return 0
~
''', "[1,2,3,4,5]\n")

    def test_large_list_to_json_with_gc(self, expect_output):
        """Large list conversion with repeated GC."""
        expect_output('''
func main() -> int
    nums = [0]
    i = 1
    while i < 50
        nums = nums.append(i)
        i = i + 1
    ~
    gc()
    data: json := nums
    gc()
    result = data.stringify()
    print(result.len() > 0)
    return 0
~
''', "true\n")

    def test_string_list_to_json_with_gc(self, expect_output):
        """String list conversion (exercises element conversion + handle deref)."""
        expect_output('''
func main() -> int
    words = ["hello", "world", "foo", "bar"]
    gc()
    data: json := words
    gc()
    result = data.stringify()
    print(result.len() > 0)
    return 0
~
''', "true\n")
