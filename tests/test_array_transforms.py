"""
Tests for Array<T> transformation operations.

Tests include:
- flatten() - Convert N-D array to 1D
- transpose() - Transpose 2D array
- reshape(rows, cols) - Reshape array to new dimensions
"""

import pytest


class TestArrayFlatten:
    """Tests for Array.flatten() transformation."""

    def test_array_flatten_1d(self, expect_output):
        """Flattening a 1D array returns same length."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5]
    arr: Array<int> = list.packed()
    flat: Array<int> = arr.flatten()
    print(flat.ndim())
    print(flat.len())
    print(flat.get(0))
    print(flat.get(4))
    return 0
~
''', "1\n5\n1\n5\n")

    def test_array_flatten_2d(self, expect_output):
        """Flatten a 2D array to 1D."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.identity(2)
    # Identity 2x2: [[1,0],[0,1]] flattened = [1,0,0,1]
    flat: Array<int> = arr.flatten()
    print(flat.ndim())
    print(flat.len())
    print(flat.get(0))
    print(flat.get(1))
    print(flat.get(2))
    print(flat.get(3))
    return 0
~
''', "1\n4\n1\n0\n0\n1\n")

    def test_array_flatten_2d_zeros(self, expect_output):
        """Flatten a 2D zeros array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(2, 3)
    flat: Array<int> = arr.flatten()
    print(flat.ndim())
    print(flat.len())
    return 0
~
''', "1\n6\n")


class TestArrayTranspose:
    """Tests for Array.transpose() transformation."""

    def test_array_transpose_identity(self, expect_output):
        """Transpose identity matrix is same matrix."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.identity(3)
    trans: Array<int> = arr.transpose()
    print(trans.ndim())
    print(trans.shape(0))
    print(trans.shape(1))
    # Diagonal elements should still be 1
    print(trans[0, 0])
    print(trans[1, 1])
    print(trans[2, 2])
    return 0
~
''', "2\n3\n3\n1\n1\n1\n")

    def test_array_transpose_shape(self, expect_output):
        """Transpose swaps rows and cols."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(2, 5)
    trans: Array<int> = arr.transpose()
    print(trans.shape(0))
    print(trans.shape(1))
    return 0
~
''', "5\n2\n")


class TestArrayReshape:
    """Tests for Array.reshape() transformation."""

    def test_array_reshape_1d_to_2d(self, expect_output):
        """Reshape 1D array to 2D."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5, 6]
    arr: Array<int> = list.packed()
    # Reshape to 2x3
    reshaped: Array<int> = arr.reshape(2, 3)
    print(reshaped.ndim())
    print(reshaped.shape(0))
    print(reshaped.shape(1))
    # First row
    print(reshaped[0, 0])
    print(reshaped[0, 1])
    print(reshaped[0, 2])
    # Second row
    print(reshaped[1, 0])
    print(reshaped[1, 1])
    print(reshaped[1, 2])
    return 0
~
''', "2\n2\n3\n1\n2\n3\n4\n5\n6\n")

    def test_array_reshape_2d_to_1d(self, expect_output):
        """Reshape 2D array to 1D (flatten via reshape)."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.identity(2)
    # Reshape 2x2 to 4x1 (1D)
    reshaped: Array<int> = arr.reshape(4, 1)
    print(reshaped.ndim())
    print(reshaped.shape(0))
    return 0
~
''', "2\n4\n")

    def test_array_reshape_2d_to_2d(self, expect_output):
        """Reshape 2D array to different 2D shape."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(2, 6)
    # Reshape 2x6 to 3x4
    reshaped: Array<int> = arr.reshape(3, 4)
    print(reshaped.ndim())
    print(reshaped.shape(0))
    print(reshaped.shape(1))
    print(reshaped.total_size())
    return 0
~
''', "2\n3\n4\n12\n")
