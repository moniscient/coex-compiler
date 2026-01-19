"""
Tests for Array<T> cellular automata support with @[] relative indexing.

Tests include:
- 1D relative indexing: arr@[offset]
- 2D relative indexing: arr@[row_off, col_off]
- Neighbor access patterns for Game of Life style automata
"""

import pytest


class TestRelativeIndex1D:
    """Tests for 1D relative indexing with @[]."""

    def test_relative_index_1d_basic(self, expect_output):
        """Access neighbors using @[] syntax in 1D array."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30, 40, 50]
    arr: Array<int> = list.packed()

    # Set up CA context for position 2
    __ca_pos__: int = 2

    # Access element at position 2 (center)
    print(arr@[0])

    # Access left neighbor (position 1)
    print(arr@[-1])

    # Access right neighbor (position 3)
    print(arr@[1])

    return 0
~
''', "30\n20\n40\n")

    def test_relative_index_1d_loop(self, expect_output):
        """Iterate with relative indexing to sum neighbors."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5]
    arr: Array<int> = list.packed()

    # Compute sum of (left + center + right) for position 2
    __ca_pos__: int = 2
    sum: int = arr@[-1] + arr@[0] + arr@[1]
    print(sum)

    return 0
~
''', "9\n")


class TestRelativeIndex2D:
    """Tests for 2D relative indexing with @[row, col]."""

    def test_relative_index_2d_basic(self, expect_output):
        """Access neighbors using @[r, c] syntax in 2D array."""
        expect_output('''
func main() -> int
    # Create 3x3 identity matrix
    arr: Array<int> = Array.identity(3)

    # Set up CA context for position (1, 1) - center
    __ca_row__: int = 1
    __ca_col__: int = 1

    # Access center element (1,1) - should be 1 (diagonal)
    print(arr@[0, 0])

    # Access top-left (0,0) - should be 1 (diagonal)
    print(arr@[-1, -1])

    # Access top-center (0,1) - should be 0
    print(arr@[-1, 0])

    # Access bottom-right (2,2) - should be 1 (diagonal)
    print(arr@[1, 1])

    return 0
~
''', "1\n1\n0\n1\n")

    def test_relative_index_2d_neighbors(self, expect_output):
        """Count live neighbors using 2D relative indexing."""
        expect_output('''
func main() -> int
    # Create 3x3 matrix with corners = 1, rest = 0
    arr: Array<int> = Array.zeros_2d(3, 3)
    flat: Array<int> = arr.flatten()
    # Set corners to 1: [0,0], [0,2], [2,0], [2,2]
    flat = flat.set(0, 1)    # (0,0)
    flat = flat.set(2, 1)    # (0,2)
    flat = flat.set(6, 1)    # (2,0)
    flat = flat.set(8, 1)    # (2,2)
    arr = flat.reshape(3, 3)

    # Count neighbors of center cell (1,1)
    __ca_row__: int = 1
    __ca_col__: int = 1

    # 8-neighborhood sum (all corners should be 1)
    neighbors: int = arr@[-1, -1] + arr@[-1, 0] + arr@[-1, 1] + arr@[0, -1] + arr@[0, 1] + arr@[1, -1] + arr@[1, 0] + arr@[1, 1]
    print(neighbors)

    return 0
~
''', "4\n")
