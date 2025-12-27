"""Test slice syntax for collections."""

import pytest


class TestSliceSyntax:
    """Test slice syntax for collections."""

    def test_list_slice_basic(self, expect_output):
        """Test basic list slicing [start:end]."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    slice = list[1:4]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n1\n3\n")

    def test_list_slice_open_start(self, expect_output):
        """Test list slicing with open start [:end]."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    slice = list[:3]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n0\n2\n")

    def test_list_slice_open_end(self, expect_output):
        """Test list slicing with open end [start:]."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    slice = list[2:]
    print(slice.len())
    print(slice.get(0))
    return 0
~
''', "3\n2\n")

    def test_list_slice_negative_start(self, expect_output):
        """Test list slicing with negative start index."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    last2 = list[-2:]
    print(last2.len())
    print(last2.get(0))
    print(last2.get(1))
    return 0
~
''', "2\n3\n4\n")

    def test_list_slice_negative_end(self, expect_output):
        """Test list slicing with negative end index."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    prefix = list[:-2]
    print(prefix.len())
    print(prefix.get(2))
    return 0
~
''', "3\n2\n")

    def test_list_setrange_basic(self, expect_output):
        """Test basic slice assignment."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    list[1:3] = [10, 20]
    print(list.get(0))
    print(list.get(1))
    print(list.get(2))
    print(list.get(3))
    return 0
~
''', "0\n10\n20\n3\n")

    def test_list_setrange_open_end(self, expect_output):
        """Test slice assignment with open end."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    list[3:] = [30, 40]
    print(list.len())
    print(list.get(3))
    print(list.get(4))
    return 0
~
''', "5\n30\n40\n")

    def test_slice_value_semantics(self, expect_output):
        """Test that slices preserve value semantics."""
        expect_output('''
func main() -> int
    original = [0, 1, 2, 3, 4]
    slice = original[1:4]
    slice[0:1] = [99]
    print(slice.get(0))
    print(original.get(1))
    return 0
~
''', "99\n1\n")

    def test_slice_bounds_clamping(self, expect_output):
        """Test that out-of-bounds indices are clamped."""
        expect_output('''
func main() -> int
    list = [0, 1, 2]
    slice = list[0:100]
    print(slice.len())
    return 0
~
''', "3\n")

    def test_slice_empty_result(self, expect_output):
        """Test slicing beyond end returns empty list."""
        expect_output('''
func main() -> int
    list = [0, 1, 2]
    slice = list[5:10]
    print(slice.len())
    return 0
~
''', "0\n")

    def test_slice_full_list(self, expect_output):
        """Test slicing with [:]."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    slice = list[:]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(4))
    return 0
~
''', "5\n0\n4\n")

    def test_index_still_works(self, expect_output):
        """Test that single index still works after slice changes."""
        expect_output('''
func main() -> int
    list = [10, 20, 30]
    print(list[0])
    print(list[1])
    print(list[2])
    return 0
~
''', "10\n20\n30\n")

    def test_slice_setrange_open_start(self, expect_output):
        """Test slice assignment with open start."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    list[:2] = [10, 20]
    print(list.get(0))
    print(list.get(1))
    print(list.get(2))
    return 0
~
''', "10\n20\n2\n")

    def test_slice_negative_both(self, expect_output):
        """Test slicing with both negative indices."""
        expect_output('''
func main() -> int
    list = [0, 1, 2, 3, 4]
    middle = list[-4:-1]
    print(middle.len())
    print(middle.get(0))
    print(middle.get(2))
    return 0
~
''', "3\n1\n3\n")
