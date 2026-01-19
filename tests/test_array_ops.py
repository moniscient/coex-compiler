"""
Tests for Array<T> element-wise operations and reductions.

Tests include:
- Element-wise: scale, add, sub, mul, div
- Reductions: sum, mean, min, max
"""

import pytest


class TestArrayScale:
    """Tests for Array.scale() element-wise multiplication by scalar."""

    def test_array_scale_basic(self, expect_output):
        """Scale all elements by a scalar."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4]
    arr: Array<int> = list.packed()
    scaled: Array<int> = arr.scale(2)
    print(scaled.get(0))
    print(scaled.get(1))
    print(scaled.get(2))
    print(scaled.get(3))
    return 0
~
''', "2\n4\n6\n8\n")

    def test_array_scale_zero(self, expect_output):
        """Scale by zero produces zeros."""
        expect_output('''
func main() -> int
    list: List<int> = [5, 10, 15]
    arr: Array<int> = list.packed()
    scaled: Array<int> = arr.scale(0)
    print(scaled.get(0))
    print(scaled.get(1))
    print(scaled.get(2))
    return 0
~
''', "0\n0\n0\n")

    def test_array_scale_negative(self, expect_output):
        """Scale by negative value."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3]
    arr: Array<int> = list.packed()
    scaled: Array<int> = arr.scale(-1)
    print(scaled.get(0))
    print(scaled.get(1))
    print(scaled.get(2))
    return 0
~
''', "-1\n-2\n-3\n")


class TestArrayAdd:
    """Tests for Array.add() element-wise addition."""

    def test_array_add_basic(self, expect_output):
        """Add two arrays element-wise."""
        expect_output('''
func main() -> int
    l1: List<int> = [1, 2, 3]
    l2: List<int> = [10, 20, 30]
    a1: Array<int> = l1.packed()
    a2: Array<int> = l2.packed()
    result: Array<int> = a1.add(a2)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "11\n22\n33\n")

    def test_array_add_with_negatives(self, expect_output):
        """Add arrays with negative values."""
        expect_output('''
func main() -> int
    l1: List<int> = [5, -3, 0]
    l2: List<int> = [-2, 7, 10]
    a1: Array<int> = l1.packed()
    a2: Array<int> = l2.packed()
    result: Array<int> = a1.add(a2)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "3\n4\n10\n")


class TestArraySub:
    """Tests for Array.sub() element-wise subtraction."""

    def test_array_sub_basic(self, expect_output):
        """Subtract two arrays element-wise."""
        expect_output('''
func main() -> int
    l1: List<int> = [10, 20, 30]
    l2: List<int> = [1, 2, 3]
    a1: Array<int> = l1.packed()
    a2: Array<int> = l2.packed()
    result: Array<int> = a1.sub(a2)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "9\n18\n27\n")


class TestArrayMul:
    """Tests for Array.mul() element-wise multiplication (Hadamard product)."""

    def test_array_mul_basic(self, expect_output):
        """Multiply two arrays element-wise."""
        expect_output('''
func main() -> int
    l1: List<int> = [2, 3, 4]
    l2: List<int> = [5, 6, 7]
    a1: Array<int> = l1.packed()
    a2: Array<int> = l2.packed()
    result: Array<int> = a1.mul(a2)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "10\n18\n28\n")


class TestArrayDiv:
    """Tests for Array.div() element-wise division."""

    def test_array_div_basic(self, expect_output):
        """Divide two arrays element-wise."""
        expect_output('''
func main() -> int
    l1: List<int> = [10, 20, 30]
    l2: List<int> = [2, 4, 5]
    a1: Array<int> = l1.packed()
    a2: Array<int> = l2.packed()
    result: Array<int> = a1.div(a2)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "5\n5\n6\n")


class TestArraySum:
    """Tests for Array.sum() reduction."""

    def test_array_sum_basic(self, expect_output):
        """Sum all elements."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4, 5]
    arr: Array<int> = list.packed()
    print(arr.sum())
    return 0
~
''', "15\n")

    def test_array_sum_single(self, expect_output):
        """Sum of single element."""
        expect_output('''
func main() -> int
    list: List<int> = [42]
    arr: Array<int> = list.packed()
    print(arr.sum())
    return 0
~
''', "42\n")

    def test_array_sum_with_negatives(self, expect_output):
        """Sum with negative values."""
        expect_output('''
func main() -> int
    list: List<int> = [10, -3, 5, -2]
    arr: Array<int> = list.packed()
    print(arr.sum())
    return 0
~
''', "10\n")


class TestArrayMean:
    """Tests for Array.mean() reduction."""

    def test_array_mean_basic(self, expect_output):
        """Compute mean of all elements."""
        expect_output('''
func main() -> int
    list: List<int> = [10, 20, 30, 40]
    arr: Array<int> = list.packed()
    print(arr.mean())
    return 0
~
''', "25\n")

    def test_array_mean_rounding(self, expect_output):
        """Mean with integer division truncation."""
        expect_output('''
func main() -> int
    list: List<int> = [1, 2, 3, 4]
    arr: Array<int> = list.packed()
    # Mean = 10 / 4 = 2 (integer division)
    print(arr.mean())
    return 0
~
''', "2\n")


class TestArrayMin:
    """Tests for Array.min() reduction."""

    def test_array_min_basic(self, expect_output):
        """Find minimum element."""
        expect_output('''
func main() -> int
    list: List<int> = [5, 2, 8, 1, 9]
    arr: Array<int> = list.packed()
    print(arr.min())
    return 0
~
''', "1\n")

    def test_array_min_with_negatives(self, expect_output):
        """Minimum with negative values."""
        expect_output('''
func main() -> int
    list: List<int> = [5, -10, 3, -2]
    arr: Array<int> = list.packed()
    print(arr.min())
    return 0
~
''', "-10\n")


class TestArrayMax:
    """Tests for Array.max() reduction."""

    def test_array_max_basic(self, expect_output):
        """Find maximum element."""
        expect_output('''
func main() -> int
    list: List<int> = [5, 2, 8, 1, 9]
    arr: Array<int> = list.packed()
    print(arr.max())
    return 0
~
''', "9\n")

    def test_array_max_with_negatives(self, expect_output):
        """Maximum with negative values."""
        expect_output('''
func main() -> int
    list: List<int> = [-5, -10, -3, -2]
    arr: Array<int> = list.packed()
    print(arr.max())
    return 0
~
''', "-2\n")
