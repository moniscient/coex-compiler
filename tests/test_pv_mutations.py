"""
Tests for Persistent Vector (List) mutation operations.

Session 5: Tests for set() and append() with structural sharing.
"""

import pytest


class TestPersistentVectorSet:
    """Test set() operation with structural sharing."""

    def test_set_single_element(self, expect_output):
        """set() on single element list."""
        expect_output('''
func main() -> int
    a = [10]
    b = a.set(0, 99)
    print(a.get(0))
    print(b.get(0))
    return 0
~
''', "10\n99\n")

    def test_set_preserves_original(self, expect_output):
        """set() creates new list, original unchanged."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(2, 99)
    print(a.get(0))
    print(a.get(2))
    print(a.get(4))
    print(b.get(0))
    print(b.get(2))
    print(b.get(4))
    return 0
~
''', "1\n3\n5\n1\n99\n5\n")

    def test_set_multiple_indices(self, expect_output):
        """Multiple set() calls create independent versions."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(0, 10)
    c = a.set(2, 30)
    d = a.set(4, 50)
    print(a.get(0))
    print(b.get(0))
    print(c.get(0))
    print(d.get(0))
    return 0
~
''', "1\n10\n1\n1\n")

    def test_set_large_list(self, expect_output):
        """set() on list with tree structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..100
        a = a.append(i)
    ~
    b = a.set(50, 999)
    print(a.get(50))
    print(b.get(50))
    print(a.len())
    print(b.len())
    return 0
~
''', "50\n999\n100\n100\n")

    def test_set_chain(self, expect_output):
        """Chained set() operations."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a.set(0, 10).set(1, 20).set(2, 30)
    print(b.get(0))
    print(b.get(1))
    print(b.get(2))
    return 0
~
''', "10\n20\n30\n")


class TestPersistentVectorAppend:
    """Test append() operation with tail optimization."""

    def test_append_to_empty(self, expect_output):
        """append() to empty list."""
        expect_output('''
func main() -> int
    a: List<int> = []
    b = a.append(42)
    print(a.len())
    print(b.len())
    print(b.get(0))
    return 0
~
''', "0\n1\n42\n")

    def test_append_preserves_original(self, expect_output):
        """append() creates new list, original unchanged."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b = a.append(4)
    print(a.len())
    print(b.len())
    print(b.get(3))
    return 0
~
''', "3\n4\n4\n")

    def test_append_multiple(self, expect_output):
        """Multiple appends create growing lists."""
        expect_output('''
func main() -> int
    a = [1]
    b = a.append(2)
    c = b.append(3)
    d = c.append(4)
    print(a.len())
    print(b.len())
    print(c.len())
    print(d.len())
    return 0
~
''', "1\n2\n3\n4\n")

    def test_append_builds_tree(self, expect_output):
        """Appending past 32 elements builds tree structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..50
        a = a.append(i)
    ~
    print(a.len())
    print(a.get(0))
    print(a.get(32))
    print(a.get(49))
    return 0
~
''', "50\n0\n32\n49\n")

    def test_append_chain(self, expect_output):
        """Chained append operations."""
        expect_output('''
func main() -> int
    a = [1].append(2).append(3).append(4).append(5)
    print(a.len())
    for x in a
        print(x)
    ~
    return 0
~
''', "5\n1\n2\n3\n4\n5\n")


class TestStructuralSharing:
    """Test that structural sharing works correctly."""

    def test_shared_nodes_not_duplicated(self, expect_output):
        """Modified list shares unchanged nodes with original."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b = a.set(0, 99)
    print(a.get(4))
    print(b.get(4))
    return 0
~
''', "5\n5\n")

    def test_independent_mutations(self, expect_output):
        """Multiple mutations from same source are independent."""
        expect_output('''
func main() -> int
    base = [1, 2, 3, 4, 5]
    v1 = base.set(0, 10)
    v2 = base.set(0, 20)
    v3 = base.set(0, 30)
    print(base.get(0))
    print(v1.get(0))
    print(v2.get(0))
    print(v3.get(0))
    return 0
~
''', "1\n10\n20\n30\n")

    def test_large_shared_structure(self, expect_output):
        """Large lists share most of their structure."""
        expect_output('''
func main() -> int
    a: List<int> = []
    for i in 0..1000
        a = a.append(i)
    ~
    b = a.set(500, 9999)
    print(a.get(0))
    print(b.get(0))
    print(a.get(500))
    print(b.get(500))
    print(a.get(999))
    print(b.get(999))
    return 0
~
''', "0\n0\n500\n9999\n999\n999\n")


class TestMutationWithMove:
    """Test mutations combined with := operator."""

    def test_append_after_move(self, expect_output):
        """After move, append is in-place if sole owner."""
        expect_output('''
func main() -> int
    a = [1, 2, 3]
    b := a
    b = b.append(4)
    b = b.append(5)
    print(b.len())
    for x in b
        print(x)
    ~
    return 0
~
''', "5\n1\n2\n3\n4\n5\n")

    def test_set_after_move(self, expect_output):
        """After move, set is in-place if sole owner."""
        expect_output('''
func main() -> int
    a = [1, 2, 3, 4, 5]
    b := a
    b = b.set(0, 10)
    b = b.set(2, 30)
    for x in b
        print(x)
    ~
    return 0
~
''', "10\n2\n30\n4\n5\n")
