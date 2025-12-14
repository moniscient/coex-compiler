import pytest

class TestHAMTSetBasic:
    """Test basic Set operations."""

    def test_set_literal(self, expect_output):
        """Set literal creates proper structure."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    print(s.len())
    return 0
~
''', "5\n")

    def test_set_has(self, expect_output):
        """has() checks element existence."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    if s.has(1)
        print("has 1")
    ~
    if s.has(2)
        print("has 2")
    ~
    if s.has(4)
        print("has 4")
    else
        print("no 4")
    ~
    return 0
~
''', "has 1\nhas 2\nno 4\n")

    def test_set_len(self, expect_output):
        """len() returns correct count."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    print(s.len())
    return 0
~
''', "5\n")

    def test_empty_set(self, expect_output):
        """Empty set works correctly."""
        expect_output('''
func main() -> int
    s = {1}
    s = s.remove(1)
    print(s.len())
    print(s.has(1))
    return 0
~
''', "0\nfalse\n")

    def test_set_of_strings(self, expect_output):
        """Set of strings works."""
        expect_output('''
func main() -> int
    s = {"hello", "world", "test"}
    print(s.len())
    print(s.has("hello"))
    print(s.has("missing"))
    return 0
~
''', "3\ntrue\nfalse\n")

    def test_set_iteration(self, expect_output):
        """Can iterate over set elements."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    sum = 0
    for x in s
        sum = sum + x
    ~
    print(sum)
    return 0
~
''', "60\n")

class TestHAMTSetAdd:
    """Test add() operation."""

    def test_add_new_element(self, expect_output):
        """add() adds new element."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t = s.add(3)
    print(s.len())
    print(t.len())
    print(t.has(3))
    return 0
~
''', "2\n3\ntrue\n")

    def test_add_preserves_original(self, expect_output):
        """add() creates new set, original unchanged."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(4)
    print(s.has(4))
    print(t.has(4))
    return 0
~
''', "false\ntrue\n")

    def test_add_existing_element(self, expect_output):
        """add() of existing element is idempotent."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(2)
    print(s.len())
    print(t.len())
    return 0
~
''', "3\n3\n")

    def test_add_chain(self, expect_output):
        """Chained add() operations."""
        expect_output('''
func main() -> int
    s = {1}.add(2).add(3).add(4).add(5)
    print(s.len())
    return 0
~
''', "5\n")

    def test_add_many(self, expect_output):
        """Add many elements (requires multiple levels)."""
        expect_output('''
func main() -> int
    s = {0}
    for i in 1..100
        s = s.add(i)
    ~
    print(s.len())
    print(s.has(0))
    print(s.has(50))
    print(s.has(99))
    print(s.has(100))
    return 0
~
''', "100\ntrue\ntrue\ntrue\nfalse\n")

class TestHAMTSetRemove:
    """Test remove() operation."""

    def test_remove_existing(self, expect_output):
        """remove() removes existing element."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(2)
    print(s.len())
    print(t.len())
    print(s.has(2))
    print(t.has(2))
    return 0
~
''', "3\n2\ntrue\nfalse\n")

    def test_remove_preserves_original(self, expect_output):
        """remove() creates new set, original unchanged."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(1)
    print(s.has(1))
    print(t.has(1))
    return 0
~
''', "true\nfalse\n")

    def test_remove_nonexistent(self, expect_output):
        """remove() of nonexistent element is no-op."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.remove(999)
    print(s.len())
    print(t.len())
    return 0
~
''', "3\n3\n")

    def test_remove_chain(self, expect_output):
        """Chained remove() operations."""
        expect_output('''
func main() -> int
    s = {1, 2, 3, 4, 5}
    t = s.remove(1).remove(3).remove(5)
    print(t.len())
    print(t.has(2))
    print(t.has(4))
    return 0
~
''', "2\ntrue\ntrue\n")

    def test_remove_all(self, expect_output):
        """Remove all elements."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t = s.remove(1).remove(2)
    print(t.len())
    return 0
~
''', "0\n")

class TestSetStructuralSharing:
    """Test structural sharing."""

    def test_assignment_shares(self, expect_output):
        """Assignment shares structure."""
        expect_output('''
func main() -> int
    a = {1, 2, 3, 4, 5}
    b = a
    c = a
    print(b.has(3))
    print(c.has(3))
    return 0
~
''', "true\ntrue\n")

    def test_independent_modifications(self, expect_output):
        """Modifications from same base are independent."""
        expect_output('''
func main() -> int
    base = {1, 2, 3}
    a = base.add(10)
    b = base.add(20)
    c = base.add(30)
    print(a.has(10))
    print(a.has(20))
    print(b.has(10))
    print(b.has(20))
    return 0
~
''', "true\nfalse\nfalse\ntrue\n")

    def test_mixed_operations(self, expect_output):
        """Mix of add and remove operations."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t = s.add(4).remove(2).add(5)
    print(t.len())
    print(t.has(1))
    print(t.has(2))
    print(t.has(4))
    print(t.has(5))
    return 0
~
''', "4\ntrue\nfalse\ntrue\ntrue\n")

class TestSetWithMove:
    """Test Set with := operator."""

    def test_add_after_move(self, expect_output):
        """After move, add may be optimized."""
        expect_output('''
func main() -> int
    s = {1, 2}
    t := s
    t = t.add(3)
    t = t.add(4)
    print(t.len())
    return 0
~
''', "4\n")

    def test_remove_after_move(self, expect_output):
        """After move, remove may be optimized."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    t := s
    t = t.remove(2)
    print(t.len())
    print(t.has(2))
    return 0
~
''', "2\nfalse\n")
