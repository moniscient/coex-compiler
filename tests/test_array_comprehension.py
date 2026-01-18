"""
Tests for Array iteration in comprehensions (BUG-028).

Array iteration should work like List iteration in comprehensions:
[f(x) for x in array_value] should produce a list of results.
"""

import pytest


class TestArrayComprehension:
    """Test Array iteration in comprehensions."""

    def test_array_iteration_basic(self, expect_output):
        """Basic Array iteration in comprehension."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.filled(5, 8)
    for i in 0..5
        arr = arr.set(i, i + 1)
    ~
    result = [x * 2 for x in arr]
    print(result.get(0))
    print(result.get(2))
    print(result.get(4))
    return 0
~
''', "2\n6\n10\n")

    def test_array_iteration_with_filter(self, expect_output):
        """Array iteration with filter condition."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.filled(6, 8)
    for i in 0..6
        arr = arr.set(i, i)
    ~
    # Keep only even numbers
    evens = [x for x in arr if x % 2 == 0]
    print(evens.len())
    print(evens.get(0))
    print(evens.get(1))
    print(evens.get(2))
    return 0
~
''', "3\n0\n2\n4\n")

    def test_array_iteration_with_formula(self, expect_output):
        """Array iteration with formula function."""
        expect_output('''
formula square(n: int) -> int
    return n * n
~

func main() -> int
    arr: Array<int> = Array.filled(5, 8)
    for i in 0..5
        arr = arr.set(i, i + 1)
    ~
    squares = [square(x) for x in arr]
    print(squares.get(0))
    print(squares.get(2))
    print(squares.get(4))
    return 0
~
''', "1\n9\n25\n")

    def test_array_set_comprehension(self, expect_output):
        """Array iteration in set comprehension."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.filled(5, 8)
    for i in 0..5
        arr = arr.set(i, i % 3)
    ~
    s = {x for x in arr}
    print(s.len())
    return 0
~
''', "3\n")

    @pytest.mark.xfail(reason="BUG-029: MapComprehension not handled in formula offload check")
    def test_array_map_comprehension(self, expect_output):
        """Array iteration in map comprehension."""
        expect_output('''
func main() -> int
    arr: Array<int> = Array.filled(3, 8)
    for i in 0..3
        arr = arr.set(i, i + 1)
    ~
    m = {x: x * 10 for x in arr}
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "10\n20\n30\n")

    def test_array_multiple_clauses(self, expect_output):
        """Array iteration with multiple comprehension clauses."""
        expect_output('''
func main() -> int
    arr1: Array<int> = Array.filled(2, 8)
    arr1 = arr1.set(0, 1)
    arr1 = arr1.set(1, 2)
    arr2: Array<int> = Array.filled(2, 8)
    arr2 = arr2.set(0, 10)
    arr2 = arr2.set(1, 20)
    # Cartesian product: multiply each pair
    result = [x * y for x in arr1 for y in arr2]
    print(result.len())
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    print(result.get(3))
    return 0
~
''', "4\n10\n20\n20\n40\n")
