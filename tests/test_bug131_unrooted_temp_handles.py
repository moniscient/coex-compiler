"""Test BUG-131: Unrooted temporary handles in binary expression chains.

Function call return values used directly as operands in string concat chains
were not rooted in the shadow stack, causing GC to sweep them during subsequent
allocations. The fix roots the left operand in a temporary GC frame before
evaluating the right operand, and also roots both inputs inside string_concat.
"""
import pytest


class TestBug131UnrootedTempHandles:
    """Test that function call return values used in expression chains survive GC."""

    def test_func_return_in_concat_chain(self, expect_output):
        """Basic case: func() return value used in "[" + func() + "]" """
        expect_output('''
func make_str(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    combined = "[" + make_str(10) + "]"
    print(combined.len())
    return 0
~
''', "12\n")

    def test_func_return_in_concat_chain_with_gc(self, expect_output):
        """Function return in concat chain under GC pressure."""
        expect_output('''
func make_str(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    i = 0
    while i < 50
        combined = "[" + make_str(100) + "]"
        if i % 10 == 0
            print("Iter " + String.from(i) + ": " + String.from(combined.len()))
        ~
        i = i + 1
    ~
    print("Done")
    return 0
~
''', "Iter 0: 102\nIter 10: 102\nIter 20: 102\nIter 30: 102\nIter 40: 102\nDone\n")

    def test_nested_func_returns_in_concat(self, expect_output):
        """Both operands are function calls: func() + func()."""
        expect_output('''
func prefix() -> string
    return "hello"
~

func suffix() -> string
    return "world"
~

func main() -> int
    result = prefix() + " " + suffix()
    print(result)
    return 0
~
''', "hello world\n")

    def test_recursive_string_builder_in_concat_chain(self, expect_output):
        """Recursive function return used in concat chain - the brep_torus pattern."""
        expect_output('''
type Node:
    value: int
    children: [Node]
~

func collect_str(node: Node) -> string
    if node.children.len() == 0
        return String.from(node.value)
    ~
    parts = ""
    ci = 0
    while ci < node.children.len()
        child_str = collect_str(node.children.get(ci))
        if parts.len() > 0
            parts = parts + "," + child_str
        else
            parts = child_str
        ~
        ci = ci + 1
    ~
    return parts
~

func build_tree(depth: int, width: int) -> Node
    if depth == 0
        return Node(1, [])
    ~
    kids: [Node] = []
    i = 0
    while i < width
        kids = kids.append(build_tree(depth - 1, width))
        i = i + 1
    ~
    return Node(0, kids)
~

func main() -> int
    tree = build_tree(3, 4)
    result = "[" + collect_str(tree) + "]"
    print(String.from(result.len()))
    return 0
~
''', "129\n")


class TestBug131Stress:
    """Stress tests to verify the fix holds under heavy GC pressure."""

    @pytest.mark.timeout(120)
    def test_concat_chain_stress_loop(self, expect_output):
        """Many iterations of "[" + func() + "]" to trigger GC during evaluation."""
        expect_output('''
func make_big_string(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    i = 0
    while i < 100
        combined = "[" + make_big_string(500) + "]"
        if i % 25 == 0
            print("Iteration " + String.from(i) + ": " + String.from(combined.len()))
        ~
        i = i + 1
    ~
    print("Done")
    return 0
~
''', "Iteration 0: 502\nIteration 25: 502\nIteration 50: 502\nIteration 75: 502\nDone\n")
