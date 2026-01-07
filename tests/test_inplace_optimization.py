"""
Tests for in-place mutation optimization.

These tests verify that the uniqueness analysis correctly identifies
update patterns and generates in-place mutations when applicable.
"""
import pytest


class TestInplaceSetAdd:
    """Test in-place optimization for set.add() patterns."""

    def test_set_add_loop_basic(self, expect_output):
        """Test basic set.add in a loop - the prime optimization target."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    i = 0
    while i < 100
        s = s.add(i)
        i = i + 1
    ~
    print(s.len())
    return 0
~
''', "100\n")

    def test_set_add_preserves_semantics(self, expect_output):
        """Verify that in-place optimization doesn't break value semantics."""
        expect_output('''
func main() -> int
    s1: Set<int> = {}
    s1 = s1.add(1)
    s2 = s1  # s2 should be independent copy
    s1 = s1.add(2)
    s1 = s1.add(3)
    # s2 should still have only 1 element
    print(s2.len())
    print(s1.len())
    return 0
~
''', "1\n3\n")

    def test_set_add_conditional(self, expect_output):
        """Test set.add with conditional execution."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    i = 0
    while i < 10
        if i % 2 == 0
            s = s.add(i)
        ~
        i = i + 1
    ~
    print(s.len())
    return 0
~
''', "5\n")

    def test_set_add_nested_loops(self, expect_output):
        """Test set.add in nested loops."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    i = 0
    while i < 5
        j = 0
        while j < 5
            s = s.add(i * 10 + j)
            j = j + 1
        ~
        i = i + 1
    ~
    print(s.len())
    return 0
~
''', "25\n")

    def test_set_add_large_count(self, expect_output):
        """Test set.add with many iterations (stress test)."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    i = 0
    while i < 10000
        s = s.add(i)
        i = i + 1
    ~
    print(s.len())
    return 0
~
''', "10000\n")


class TestInplaceSetRemove:
    """Test in-place optimization for set.remove() patterns."""

    def test_set_remove_loop(self, expect_output):
        """Test set.remove in a loop."""
        expect_output('''
func main() -> int
    s: Set<int> = {}
    i = 0
    while i < 10
        s = s.add(i)
        i = i + 1
    ~
    # Remove even numbers
    i = 0
    while i < 10
        if i % 2 == 0
            s = s.remove(i)
        ~
        i = i + 2
    ~
    print(s.len())
    return 0
~
''', "5\n")


class TestInplaceMapPut:
    """Test in-place optimization for map.set() patterns."""

    def test_map_put_loop(self, expect_output):
        """Test map.set in a loop."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}
    i = 0
    while i < 100
        m = m.set(i, i * i)
        i = i + 1
    ~
    print(m.len())
    print(m.get(10))
    return 0
~
''', "100\n100\n")

    def test_map_put_preserves_semantics(self, expect_output):
        """Verify that in-place optimization doesn't break value semantics for maps."""
        expect_output('''
func main() -> int
    m1: Map<int, int> = {}
    m1 = m1.set(1, 100)
    m2 = m1  # m2 should be independent copy
    m1 = m1.set(2, 200)
    m1 = m1.set(3, 300)
    # m2 should still have only 1 entry
    print(m2.len())
    print(m1.len())
    return 0
~
''', "1\n3\n")


class TestNoOptimizationCases:
    """Test cases where in-place optimization should NOT apply."""

    def test_no_opt_when_shared(self, expect_output):
        """No optimization when value is shared with another variable."""
        expect_output('''
func main() -> int
    s1: Set<int> = {}
    s1 = s1.add(1)
    s2 = s1  # Now s1 is shared
    # This should NOT be optimized in-place because s2 would see the mutation
    s1 = s1.add(2)
    print(s2.len())  # Should still be 1
    print(s1.len())  # Should be 2
    return 0
~
''', "1\n2\n")

    def test_no_opt_when_passed_to_function(self, expect_output):
        """No optimization when value is passed to a function."""
        expect_output('''
func use_set(s: Set<int>) -> int
    return s.len()
~

func main() -> int
    s: Set<int> = {}
    s = s.add(1)
    s = s.add(2)
    result = use_set(s)
    # After calling use_set, s should still be usable
    s = s.add(3)
    print(result)
    print(s.len())
    return 0
~
''', "2\n3\n")


class TestAnalysisModule:
    """Test the analysis module directly."""

    def test_pattern_detection(self):
        """Test that update patterns are detected correctly."""
        from analysis.uniqueness import get_update_pattern, can_optimize_statement
        from ast_nodes import VarDecl, MethodCallExpr, Identifier

        # Pattern: x = x.add(y)
        stmt = VarDecl(
            name="x",
            type_annotation=None,
            initializer=MethodCallExpr(
                object=Identifier(name="x"),
                method="add",
                args=[Identifier(name="y")]
            )
        )

        pattern = get_update_pattern(stmt)
        assert pattern is not None
        var_name, method_name, args = pattern
        assert var_name == "x"
        assert method_name == "add"
        assert len(args) == 1

    def test_no_pattern_different_var(self):
        """Test that x = y.add(z) is NOT detected as update pattern."""
        from analysis.uniqueness import get_update_pattern
        from ast_nodes import VarDecl, MethodCallExpr, Identifier

        # Pattern: x = y.add(z) - not an update pattern
        stmt = VarDecl(
            name="x",
            type_annotation=None,
            initializer=MethodCallExpr(
                object=Identifier(name="y"),  # Different from x
                method="add",
                args=[Identifier(name="z")]
            )
        )

        pattern = get_update_pattern(stmt)
        assert pattern is None

    def test_alias_detection(self):
        """Test that aliasing in args is detected."""
        from analysis.uniqueness import get_update_pattern, can_optimize_statement
        from ast_nodes import VarDecl, MethodCallExpr, Identifier

        # Pattern: x = x.add(x) - has aliasing
        stmt = VarDecl(
            name="x",
            type_annotation=None,
            initializer=MethodCallExpr(
                object=Identifier(name="x"),
                method="add",
                args=[Identifier(name="x")]  # x appears in args
            )
        )

        # Should detect pattern but NOT allow optimization due to aliasing
        pattern = get_update_pattern(stmt)
        assert pattern is not None

        # Should NOT be optimizable due to aliasing
        assert not can_optimize_statement(stmt)
