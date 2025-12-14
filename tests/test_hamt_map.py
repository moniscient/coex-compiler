"""
Tests for HAMT (Hash Array Mapped Trie) Map implementation.
Session 6: Structure and read operations.
"""
import pytest


class TestHAMTMapRead:
    """Test reading from HAMT Map."""

    def test_map_literal_small(self, expect_output):
        """Small map literal creates proper structure."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "10\n20\n30\n")

    def test_map_len(self, expect_output):
        """len() returns correct count."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    print(m.len())
    var empty: Map<int, int> = {}
    print(empty.len())
    return 0
~
''', "3\n0\n")

    def test_map_has(self, expect_output):
        """has() checks key existence."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    if m.has(1)
        print("has 1")
    ~
    if m.has(3)
        print("has 3")
    else
        print("no 3")
    ~
    return 0
~
''', "has 1\nno 3\n")

    def test_map_string_keys(self, expect_output):
        """Map with string keys."""
        expect_output('''
func main() -> int
    m = {"hello": 1, "world": 2, "test": 3}
    print(m.get("hello"))
    print(m.get("world"))
    print(m.has("test"))
    print(m.has("missing"))
    return 0
~
''', "1\n2\ntrue\nfalse\n")

    def test_map_assignment_shares(self, expect_output):
        """Assignment shares structure."""
        expect_output('''
func main() -> int
    a = {1: 10, 2: 20, 3: 30}
    b = a
    c = a
    print(b.get(2))
    print(c.get(2))
    return 0
~
''', "20\n20\n")

    def test_map_iteration(self, expect_output):
        """Can iterate over map keys."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    sum = 0
    for k in m
        sum = sum + m.get(k)
    ~
    print(sum)
    return 0
~
''', "60\n")

    def test_map_medium_size(self, expect_output):
        """Map with many entries (requires multiple levels)."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {}
    for i in 0..100
        m = m.set(i, i * 10)
    ~
    print(m.len())
    print(m.get(0))
    print(m.get(50))
    print(m.get(99))
    return 0
~
''', "100\n0\n500\n990\n")

    def test_empty_map(self, expect_output):
        """Empty map works correctly."""
        expect_output('''
func main() -> int
    var m: Map<int, int> = {}
    print(m.len())
    print(m.has(1))
    return 0
~
''', "0\nfalse\n")

    def test_map_string_values(self, expect_output):
        """Map with string values."""
        expect_output('''
func main() -> int
    m = {1: "one", 2: "two", 3: "three"}
    print(m.get(1))
    print(m.get(2))
    print(m.get(3))
    return 0
~
''', "one\ntwo\nthree\n")

    def test_map_nested(self, expect_output):
        """Nested maps work."""
        expect_output('''
func main() -> int
    inner = {1: 100, 2: 200}
    outer = {"a": inner}
    result = outer.get("a")
    print(result.get(1))
    return 0
~
''', "100\n")
