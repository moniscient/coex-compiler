"""
Tests for collection type conversions and new methods.

Tests cover:
- Map.keys() and Map.values() methods
- Set.unpacked() method (convert Set to List)
- List.to_set() method (convert List to Set)
- Implicit conversions between List, Array, and Set
"""

import pytest


class TestMapKeysValues:
    """Tests for Map.keys() and Map.values() methods."""

    def test_map_keys_basic(self, expect_output):
        """Map.keys() returns a List of all keys."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    keys: List<int> = m.keys()
    print(keys.len())
    return 0
~
''', "3\n")

    def test_map_keys_iterate(self, expect_output):
        """Can iterate over Map.keys()."""
        expect_output('''
func main() -> int
    m = {1: 100, 2: 200, 3: 300}
    sum = 0
    for k in m.keys()
        sum = sum + k
    ~
    print(sum)
    return 0
~
''', "6\n")

    def test_map_values_basic(self, expect_output):
        """Map.values() returns a List of all values."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    vals: List<int> = m.values()
    print(vals.len())
    return 0
~
''', "3\n")

    def test_map_values_iterate(self, expect_output):
        """Can iterate over Map.values()."""
        expect_output('''
func main() -> int
    m = {1: 100, 2: 200, 3: 300}
    sum = 0
    for v in m.values()
        sum = sum + v
    ~
    print(sum)
    return 0
~
''', "600\n")

    def test_map_keys_empty(self, expect_output):
        """Map.keys() on empty map returns empty list."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    keys: List<int> = m.keys()
    print(keys.len())
    return 0
~
''', "0\n")


class TestSetUnpacked:
    """Tests for Set.unpacked() method."""

    def test_set_unpacked_basic(self, expect_output):
        """Set.unpacked() converts Set to List."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    list: List<int> = s.unpacked()
    print(list.len())
    return 0
~
''', "3\n")

    def test_set_unpacked_iterate(self, expect_output):
        """Can iterate over Set.unpacked()."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    sum = 0
    for x in s.unpacked()
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "60\n")

    def test_set_unpacked_empty(self, expect_output):
        """Set.unpacked() on empty set returns empty list."""
        expect_output('''
func main() -> int
    s = {1}
    s = s.remove(1)
    list: List<int> = s.unpacked()
    print(list.len())
    return 0
~
''', "0\n")


class TestListToSet:
    """Tests for List.to_set() method."""

    def test_list_to_set_basic(self, expect_output):
        """List.to_set() converts List to Set."""
        expect_output('''
func main() -> int
    list = [1, 2, 3]
    s: Set<int> = list.to_set()
    print(s.len())
    return 0
~
''', "3\n")

    def test_list_to_set_deduplicates(self, expect_output):
        """List.to_set() removes duplicates."""
        expect_output('''
func main() -> int
    list = [1, 2, 2, 3, 3, 3]
    s: Set<int> = list.to_set()
    print(s.len())
    print(s.has(1))
    print(s.has(2))
    print(s.has(3))
    return 0
~
''', "3\ntrue\ntrue\ntrue\n")

    def test_list_to_set_empty(self, expect_output):
        """List.to_set() on empty list returns empty set."""
        expect_output('''
func main() -> int
    list: List<int> = []
    s: Set<int> = list.to_set()
    print(s.len())
    return 0
~
''', "0\n")


class TestImplicitListArrayConversion:
    """Tests for implicit conversion between List and Array."""

    def test_list_to_array_implicit(self, expect_output):
        """List implicitly converts to Array when assigned to Array variable."""
        expect_output('''
func main() -> int
    list = [1, 2, 3, 4, 5]
    arr: Array<int> = list
    print(arr.len())
    print(arr.get(0))
    print(arr.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_array_to_list_implicit(self, expect_output):
        """Array implicitly converts to List when assigned to List variable."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 3].packed()
    list: List<int> = arr
    print(list.len())
    print(list.get(0))
    print(list.get(2))
    return 0
~
''', "3\n1\n3\n")


class TestImplicitListSetConversion:
    """Tests for implicit conversion between List and Set."""

    def test_list_to_set_implicit(self, expect_output):
        """List implicitly converts to Set when assigned to Set variable."""
        expect_output('''
func main() -> int
    list = [1, 2, 2, 3, 3, 3]
    s: Set<int> = list
    print(s.len())
    return 0
~
''', "3\n")

    def test_set_to_list_implicit(self, expect_output):
        """Set implicitly converts to List when assigned to List variable."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    list: List<int> = s
    print(list.len())
    return 0
~
''', "3\n")


class TestImplicitSetArrayConversion:
    """Tests for implicit conversion between Set and Array."""

    def test_set_to_array_implicit(self, expect_output):
        """Set implicitly converts to Array when assigned to Array variable."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    arr: Array<int> = s
    print(arr.len())
    return 0
~
''', "3\n")

    def test_array_to_set_implicit(self, expect_output):
        """Array implicitly converts to Set when assigned to Set variable."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 2, 3].packed()
    s: Set<int> = arr
    print(s.len())
    return 0
~
''', "3\n")


class TestConversionRoundtrips:
    """Tests for round-trip conversions."""

    def test_list_array_roundtrip(self, expect_output):
        """List -> Array -> List preserves data."""
        expect_output('''
func main() -> int
    original = [10, 20, 30]
    arr: Array<int> = original
    restored: List<int> = arr
    print(restored.len())
    print(restored.get(0))
    print(restored.get(2))
    return 0
~
''', "3\n10\n30\n")

    def test_list_set_roundtrip(self, expect_output):
        """List -> Set -> List preserves unique elements."""
        expect_output('''
func main() -> int
    original = [1, 2, 3]
    s: Set<int> = original
    restored: List<int> = s
    print(restored.len())
    return 0
~
''', "3\n")

    def test_array_set_roundtrip(self, expect_output):
        """Array -> Set -> Array preserves unique elements."""
        expect_output('''
func main() -> int
    arr: Array<int> = [1, 2, 3].packed()
    s: Set<int> = arr
    restored: Array<int> = s
    print(restored.len())
    return 0
~
''', "3\n")
