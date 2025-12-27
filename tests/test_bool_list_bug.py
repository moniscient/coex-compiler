"""
Tests for List<bool> set() persistence bug.

Bug report: List<bool>.set() does not persist values.
When calling .set() on a boolean list, the modification is not retained.
"""

import pytest


class TestBoolListSet:
    """Test set() operation on boolean lists."""

    def test_bool_list_set_true_to_false(self, expect_output):
        """set() should change true to false."""
        expect_output('''
func main() -> int
    a = [true, true, true]
    b = a.set(1, false)
    if b.get(1)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n")

    def test_bool_list_set_false_to_true(self, expect_output):
        """set() should change false to true."""
        expect_output('''
func main() -> int
    a = [false, false, false]
    b = a.set(1, true)
    if b.get(1)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_bool_list_set_preserves_original(self, expect_output):
        """set() creates new list, original unchanged."""
        expect_output('''
func main() -> int
    a = [true, false, true]
    b = a.set(0, false)
    if a.get(0)
        print(1)
    else
        print(0)
    ~
    if b.get(0)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n0\n")

    def test_bool_list_set_multiple(self, expect_output):
        """Multiple set() calls on bool list."""
        expect_output('''
func main() -> int
    a = [false, false, false, false]
    b = a.set(0, true).set(2, true)
    if b.get(0)
        print(1)
    else
        print(0)
    ~
    if b.get(1)
        print(1)
    else
        print(0)
    ~
    if b.get(2)
        print(1)
    else
        print(0)
    ~
    if b.get(3)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n0\n1\n0\n")

    def test_bool_list_append_and_set(self, expect_output):
        """append() then set() on bool list."""
        expect_output('''
func main() -> int
    a: List<bool> = []
    a = a.append(false)
    a = a.append(false)
    a = a.append(false)
    b = a.set(1, true)
    if b.get(0)
        print(1)
    else
        print(0)
    ~
    if b.get(1)
        print(1)
    else
        print(0)
    ~
    if b.get(2)
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "0\n1\n0\n")
