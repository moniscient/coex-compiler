"""
Tests for the Array<T> dense collection type.

Arrays are 1D, contiguous memory collections with O(1) indexed access.
All mutation operations return a new array (value semantics).
Arrays are created via List.packed() or Set.packed().
"""

import pytest


class TestArrayCreation:
    """Tests for creating Arrays via packed() conversion."""

    def test_list_packed_basic(self, expect_output):
        """Create an Array from a List using packed()."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    print(arr.len())
    return 0
~
''', "3\n")

    def test_list_packed_empty(self, expect_output):
        """Create an Array from an empty List."""
        expect_output('''
func main() -> int
    list: List<int> = []
    arr: Array<int> = list.packed()
    print(arr.len())
    return 0
~
''', "0\n")

    def test_set_packed_basic(self, expect_output):
        """Create an Array from a Set using packed()."""
        expect_output('''
func main() -> int
    s: Set<int> = {10, 20, 30}
    arr: Array<int> = s.packed()
    print(arr.len())
    return 0
~
''', "3\n")


class TestArrayGet:
    """Tests for Array.get() method."""

    def test_array_get_first(self, expect_output):
        """Get first element from Array."""
        expect_output('''
func main() -> int
    list: List<int> = [100, 200, 300]
    arr: Array<int> = list.packed()
    print(arr.get(0))
    return 0
~
''', "100\n")

    def test_array_get_middle(self, expect_output):
        """Get middle element from Array."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30]
    arr: Array<int> = list.packed()
    print(arr.get(1))
    return 0
~
''', "20\n")

    def test_array_get_last(self, expect_output):
        """Get last element from Array."""
        expect_output('''
func main() -> int
    list: List<int> = [5, 10, 15, 20]
    arr: Array<int> = list.packed()
    print(arr.get(3))
    return 0
~
''', "20\n")

    def test_array_index_syntax(self, expect_output):
        """Access Array element using [] syntax."""
        expect_output('''
func main() -> int
    list: List<int> = [42, 43, 44]
    arr: Array<int> = list.packed()
    print(arr[1])
    return 0
~
''', "43\n")


class TestArraySet:
    """Tests for Array.set() method - returns new array."""

    def test_array_set_returns_new(self, expect_output):
        """set() returns a new array, original unchanged."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr1: Array<int> = list.packed()
    arr2: Array<int> = arr1.set(1, 99)
    print(arr1.get(1))
    print(arr2.get(1))
    return 0
~
''', "2\n99\n")

    def test_array_set_first_element(self, expect_output):
        """Set first element in new array."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30]
    arr: Array<int> = list.packed().set(0, 100)
    print(arr.get(0))
    print(arr.get(1))
    return 0
~
''', "100\n20\n")


class TestArrayAppend:
    """Tests for Array.append() method - returns new array."""

    def test_array_append_returns_new(self, expect_output):
        """append() returns a new array with element added."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2]
    arr1: Array<int> = list.packed()
    arr2: Array<int> = arr1.append(3)
    print(arr1.len())
    print(arr2.len())
    return 0
~
''', "2\n3\n")

    def test_array_append_value(self, expect_output):
        """Appended element is accessible."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20]
    arr: Array<int> = list.packed().append(30)
    print(arr.get(2))
    return 0
~
''', "30\n")


class TestArrayIteration:
    """Tests for iterating over Arrays with for loops."""

    def test_array_for_loop(self, expect_output):
        """Iterate over Array with for loop."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    sum: int = 0
    for x in arr
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "6\n")

    def test_array_for_loop_direct(self, expect_output):
        """Iterate over Array directly from packed()."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30]
    total: int = 0
    for x in list.packed()
        total = total + x
    ~
    print(total)
    return 0
~
''', "60\n")


class TestArrayUnpacked:
    """Tests for Array.unpacked() conversion back to List."""

    def test_array_unpacked_basic(self, expect_output):
        """Convert Array back to List."""
        expect_output('''
func main() -> int
    list1: List<int> = [1, 2, 3]
    arr: Array<int> = list1.packed()
    list2: List<int> = arr.unpacked()
    print(list2.len())
    return 0
~
''', "3\n")

    def test_array_unpacked_preserves_values(self, expect_output):
        """Unpacked List has same values as original."""
        expect_output('''
func main() -> int
    list1: List<int> = [10, 20, 30]
    arr: Array<int> = list1.packed()
    list2: List<int> = arr.unpacked()
    print(list2.get(0))
    print(list2.get(1))
    print(list2.get(2))
    return 0
~
''', "10\n20\n30\n")

    def test_roundtrip_list_array_list(self, expect_output):
        """Roundtrip: List -> Array -> List preserves data."""
        expect_output('''
func main() -> int
    original: List<int> = [5, 10, 15, 20]
    arr: Array<int> = original.packed()
    restored: List<int> = arr.unpacked()
    sum: int = 0
    for x in restored
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "50\n")


class TestArraySize:
    """Tests for Array.len() and Array.size() methods."""

    def test_array_len(self, expect_output):
        """len() returns element count."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5]
    arr: Array<int> = list.packed()
    print(arr.len())
    return 0
~
''', "5\n")

    def test_array_size(self, expect_output):
        """size() returns memory footprint."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    s: int = arr.size()
    # Size should be 32 (header: 4 x 8-byte fields) + 3 * 8 (data) = 56
    print(s)
    return 0
~
''', "56\n")


class TestArrayValueSemantics:
    """Tests verifying Array value semantics."""

    def test_array_assignment_copies(self, expect_output):
        """Assigning an Array creates an independent copy."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr1: Array<int> = list.packed()
    arr2: Array<int> = arr1
    arr3: Array<int> = arr2.set(0, 100)
    # arr1 and arr2 should still have original value at index 0
    print(arr1.get(0))
    print(arr2.get(0))
    print(arr3.get(0))
    return 0
~
''', "1\n1\n100\n")
