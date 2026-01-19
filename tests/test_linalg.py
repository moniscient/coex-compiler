"""
Tests for linalg module - linear algebra operations.

Tests include:
- matmul(a, b) - Matrix multiplication
- matvec(a, x) - Matrix-vector multiplication
- dot(a, b) - Dot product
"""

import pytest


class TestLinalgDot:
    """Tests for linalg.dot() dot product."""

    def test_dot_basic(self, expect_output):
        """Dot product of two vectors."""
        expect_output('''
import linalg

func main() -> int
    l1: List<int> = [1, 2, 3]
    l2: List<int> = [4, 5, 6]
    a: Array<int> = l1.packed()
    b: Array<int> = l2.packed()
    # 1*4 + 2*5 + 3*6 = 4 + 10 + 18 = 32
    print(linalg.dot(a, b))
    return 0
~
''', "32\n")

    def test_dot_single(self, expect_output):
        """Dot product of single-element vectors."""
        expect_output('''
import linalg

func main() -> int
    l1: List<int> = [5]
    l2: List<int> = [7]
    a: Array<int> = l1.packed()
    b: Array<int> = l2.packed()
    print(linalg.dot(a, b))
    return 0
~
''', "35\n")


class TestLinalgMatvec:
    """Tests for linalg.matvec() matrix-vector multiplication."""

    def test_matvec_identity(self, expect_output):
        """Matrix-vector with identity matrix."""
        expect_output('''
import linalg

func main() -> int
    mat: Array<int> = Array.identity(3)
    list: List<int> = [1, 2, 3]
    vec: Array<int> = list.packed()
    result: Array<int> = linalg.matvec(mat, vec)
    print(result.get(0))
    print(result.get(1))
    print(result.get(2))
    return 0
~
''', "1\n2\n3\n")

    def test_matvec_scale(self, expect_output):
        """Matrix-vector with scaling matrix (2*I)."""
        expect_output('''
import linalg

func main() -> int
    # Create 2*I manually using fill and set
    mat: Array<int> = Array.zeros_2d(2, 2)
    flat: Array<int> = mat.flatten()
    flat = flat.set(0, 2)  # [0,0] = 2
    flat = flat.set(3, 2)  # [1,1] = 2
    mat = flat.reshape(2, 2)

    list: List<int> = [3, 5]
    vec: Array<int> = list.packed()
    result: Array<int> = linalg.matvec(mat, vec)
    print(result.get(0))
    print(result.get(1))
    return 0
~
''', "6\n10\n")


class TestLinalgMatmul:
    """Tests for linalg.matmul() matrix multiplication."""

    def test_matmul_identity(self, expect_output):
        """Multiply by identity matrix."""
        expect_output('''
import linalg

func main() -> int
    a: Array<int> = Array.identity(2)
    b: Array<int> = Array.identity(2)
    c: Array<int> = linalg.matmul(a, b)
    print(c.shape(0))
    print(c.shape(1))
    # Result should be identity
    print(c[0, 0])
    print(c[0, 1])
    print(c[1, 0])
    print(c[1, 1])
    return 0
~
''', "2\n2\n1\n0\n0\n1\n")

    def test_matmul_2x2(self, expect_output):
        """2x2 matrix multiplication."""
        expect_output('''
import linalg

func main() -> int
    # A = [[1, 2], [3, 4]]
    a: Array<int> = Array.zeros_2d(2, 2)
    flat_a: Array<int> = a.flatten()
    flat_a = flat_a.set(0, 1)
    flat_a = flat_a.set(1, 2)
    flat_a = flat_a.set(2, 3)
    flat_a = flat_a.set(3, 4)
    a = flat_a.reshape(2, 2)

    # B = [[5, 6], [7, 8]]
    b: Array<int> = Array.zeros_2d(2, 2)
    flat_b: Array<int> = b.flatten()
    flat_b = flat_b.set(0, 5)
    flat_b = flat_b.set(1, 6)
    flat_b = flat_b.set(2, 7)
    flat_b = flat_b.set(3, 8)
    b = flat_b.reshape(2, 2)

    # C = A * B
    # C[0,0] = 1*5 + 2*7 = 5 + 14 = 19
    # C[0,1] = 1*6 + 2*8 = 6 + 16 = 22
    # C[1,0] = 3*5 + 4*7 = 15 + 28 = 43
    # C[1,1] = 3*6 + 4*8 = 18 + 32 = 50
    c: Array<int> = linalg.matmul(a, b)
    print(c[0, 0])
    print(c[0, 1])
    print(c[1, 0])
    print(c[1, 1])
    return 0
~
''', "19\n22\n43\n50\n")
