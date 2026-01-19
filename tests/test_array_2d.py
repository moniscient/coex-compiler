"""
Tests for Array<T> 2D functionality and static constructors.

Tests N-dimensional array support including:
- Array.zeros(n) - Zero-initialized 1D array
- Array.fill(n, value) - Filled 1D array
- Array.zeros_2d(rows, cols) - Zero-initialized 2D array
- Array.identity(n) - Identity matrix
- .ndim() method
- .shape(dim) method
"""

import pytest


class TestArrayZeros:
    """Tests for Array.zeros() static constructor."""

    def test_array_zeros_basic(self, expect_output):
        """Create a zero-initialized array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros(5)
    print(arr.len())
    print(arr.get(0))
    print(arr.get(4))
    return 0
~
''', "5\n0\n0\n")

    def test_array_zeros_empty(self, expect_output):
        """Create an empty zero array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros(0)
    print(arr.len())
    return 0
~
''', "0\n")


class TestArrayFill:
    """Tests for Array.fill() static constructor."""

    def test_array_fill_basic(self, expect_output):
        """Create an array filled with a value."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.fill(4, 42)
    print(arr.len())
    print(arr.get(0))
    print(arr.get(3))
    return 0
~
''', "4\n42\n42\n")

    def test_array_fill_single(self, expect_output):
        """Create a single-element array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.fill(1, 99)
    print(arr.len())
    print(arr.get(0))
    return 0
~
''', "1\n99\n")


class TestArrayNdim:
    """Tests for .ndim() method."""

    def test_array_ndim_1d(self, expect_output):
        """1D array has ndim = 1."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    print(arr.ndim())
    return 0
~
''', "1\n")


class TestArrayShape:
    """Tests for .shape(dim) method."""

    def test_array_shape_1d(self, expect_output):
        """1D array shape[0] = len."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30, 40]
    arr: Array<int> = list.packed()
    print(arr.shape(0))
    return 0
~
''', "4\n")

    def test_array_shape_1d_unused_dims(self, expect_output):
        """1D array shape[1..3] = 0."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    print(arr.shape(1))
    print(arr.shape(2))
    print(arr.shape(3))
    return 0
~
''', "0\n0\n0\n")


class TestArray2DZeros:
    """Tests for Array.zeros_2d() 2D array creation."""

    def test_array_zeros_2d_basic(self, expect_output):
        """Create a 2D zero-initialized array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(3, 4)
    print(arr.ndim())
    print(arr.shape(0))
    print(arr.shape(1))
    return 0
~
''', "2\n3\n4\n")

    def test_array_zeros_2d_total_size(self, expect_output):
        """2D array total_size = rows * cols."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(2, 5)
    print(arr.total_size())
    return 0
~
''', "10\n")


class TestArrayIdentity:
    """Tests for Array.identity() identity matrix creation."""

    def test_array_identity_basic(self, expect_output):
        """Create a 3x3 identity matrix."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.identity(3)
    print(arr.ndim())
    print(arr.shape(0))
    print(arr.shape(1))
    return 0
~
''', "2\n3\n3\n")

    def test_array_identity_values(self, expect_output):
        """Identity matrix has 1s on diagonal, 0s elsewhere."""
        expect_output('''
func main() -> int
    # Create 2x2 identity matrix: [[1,0],[0,1]]
    arr: Array<int> = Array.identity(2)
    # Total elements = 4 (2x2)
    print(arr.total_size())
    return 0
~
''', "4\n")


class TestArray2DIndexing:
    """Tests for 2D array indexing with arr[i, j] syntax."""

    def test_array_2d_index_basic(self, expect_output):
        """Access 2D array element with arr[row, col]."""
        expect_output('''
func main() -> int
    # Create 2x3 array and set diagonal to 1
    arr: Array<int> = Array.identity(3)
    # Identity matrix: [[1,0,0],[0,1,0],[0,0,1]]
    # Access diagonal elements
    print(arr[0, 0])
    print(arr[1, 1])
    print(arr[2, 2])
    return 0
~
''', "1\n1\n1\n")

    def test_array_2d_index_offdiag(self, expect_output):
        """Access off-diagonal elements in 2D array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.identity(3)
    # Off-diagonal should be 0
    print(arr[0, 1])
    print(arr[0, 2])
    print(arr[1, 0])
    return 0
~
''', "0\n0\n0\n")

    def test_array_2d_zeros_indexing(self, expect_output):
        """Access elements in zeros_2d array."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.zeros_2d(2, 3)
    print(arr[0, 0])
    print(arr[0, 2])
    print(arr[1, 1])
    return 0
~
''', "0\n0\n0\n")
