import pytest

class TestHAMTMapSet:
    """Test set() operation with structural sharing."""

    def test_set_new_key(self, expect_output):
        """set() adds new key-value pair."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.set(3, 30)
    print(m.len())
    print(n.len())
    print(n.get(3))
    return 0
~
''', "2\n3\n30\n")

    def test_set_preserves_original(self, expect_output):
        """set() creates new map, original unchanged."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.set(1, 99)
    print(m.get(1))
    print(n.get(1))
    return 0
~
''', "10\n99\n")

    def test_set_multiple_keys(self, expect_output):
        """Multiple set() calls create independent versions."""
        expect_output('''
func main() -> int
    base = {1: 10}
    a = base.set(2, 20)
    b = base.set(3, 30)
    c = base.set(4, 40)
    print(base.len())
    print(a.len())
    print(b.len())
    print(c.len())
    print(a.has(2))
    print(a.has(3))
    return 0
~
''', "1\n2\n2\n2\ntrue\nfalse\n")

    def test_set_chain(self, expect_output):
        """Chained set() operations."""
        expect_output('''
func main() -> int
    m = {1: 10}.set(2, 20).set(3, 30).set(4, 40)
    print(m.len())
    print(m.get(1))
    print(m.get(4))
    return 0
~
''', "4\n10\n40\n")

    def test_set_overwrite(self, expect_output):
        """set() with existing key overwrites value."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.set(2, 200)
    print(m.get(2))
    print(n.get(2))
    print(n.len())
    return 0
~
''', "20\n200\n3\n")

    def test_set_large_map(self, expect_output):
        """set() on map with many entries."""
        expect_output('''
func main() -> int
    m = {0: 0}
    for i in 1..100
        m = m.set(i, i * 10)
    ~
    n = m.set(50, 9999)
    print(m.get(50))
    print(n.get(50))
    print(m.len())
    print(n.len())
    return 0
~
''', "500\n9999\n100\n100\n")

    def test_set_string_keys(self, expect_output):
        """set() with string keys."""
        expect_output('''
func main() -> int
    m = {"a": 1, "b": 2}
    n = m.set("c", 3)
    print(m.has("c"))
    print(n.has("c"))
    print(n.get("c"))
    return 0
~
''', "false\ntrue\n3\n")

class TestHAMTMapRemove:
    """Test remove() operation with structural sharing."""

    def test_remove_existing(self, expect_output):
        """remove() removes existing key."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.remove(2)
    print(m.len())
    print(n.len())
    print(m.has(2))
    print(n.has(2))
    return 0
~
''', "3\n2\ntrue\nfalse\n")

    def test_remove_preserves_original(self, expect_output):
        """remove() creates new map, original unchanged."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.remove(1)
    print(m.get(1))
    print(m.len())
    print(n.len())
    return 0
~
''', "10\n3\n2\n")

    def test_remove_nonexistent(self, expect_output):
        """remove() of nonexistent key returns same map."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.remove(999)
    print(m.len())
    print(n.len())
    return 0
~
''', "2\n2\n")

    def test_remove_chain(self, expect_output):
        """Chained remove() operations."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30, 4: 40}
    n = m.remove(1).remove(3)
    print(n.len())
    print(n.has(1))
    print(n.has(2))
    print(n.has(3))
    print(n.has(4))
    return 0
~
''', "2\nfalse\ntrue\nfalse\ntrue\n")

    def test_remove_all(self, expect_output):
        """Remove all elements."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n = m.remove(1).remove(2)
    print(n.len())
    return 0
~
''', "0\n")

class TestHAMTStructuralSharing:
    """Test that structural sharing works correctly."""

    def test_shared_subtrees(self, expect_output):
        """Modified map shares unchanged subtrees."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30, 4: 40, 5: 50}
    n = m.set(1, 99)
    print(m.get(5))
    print(n.get(5))
    return 0
~
''', "50\n50\n")

    def test_independent_branches(self, expect_output):
        """Multiple modifications from same base are independent."""
        expect_output('''
func main() -> int
    base = {1: 10, 2: 20, 3: 30}
    a = base.set(1, 100)
    b = base.set(1, 200)
    c = base.set(1, 300)
    print(base.get(1))
    print(a.get(1))
    print(b.get(1))
    print(c.get(1))
    return 0
~
''', "10\n100\n200\n300\n")

    def test_mixed_operations(self, expect_output):
        """Mix of set and remove operations."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n = m.set(4, 40).remove(2).set(5, 50)
    print(n.len())
    print(n.has(1))
    print(n.has(2))
    print(n.has(4))
    print(n.has(5))
    return 0
~
''', "4\ntrue\nfalse\ntrue\ntrue\n")

class TestMutationWithMove:
    """Test mutations combined with := operator."""

    def test_set_after_move(self, expect_output):
        """After move, set may be optimized."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20}
    n := m
    n = n.set(3, 30)
    n = n.set(4, 40)
    print(n.len())
    print(n.get(3))
    print(n.get(4))
    return 0
~
''', "4\n30\n40\n")

    def test_remove_after_move(self, expect_output):
        """After move, remove may be optimized."""
        expect_output('''
func main() -> int
    m = {1: 10, 2: 20, 3: 30}
    n := m
    n = n.remove(2)
    print(n.len())
    print(n.has(2))
    return 0
~
''', "2\nfalse\n")
