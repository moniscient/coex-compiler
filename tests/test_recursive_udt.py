"""Tests for recursive user-defined types."""
import pytest


class TestRecursiveUDT:
    """Test recursive UDTs (types that contain collections of themselves)."""

    def test_tree_with_children(self, compile_coex):
        """Tree type with a list of children."""
        result = compile_coex('''
type Tree:
    value: int
    children: [Tree]
~

func main() -> int
    leaf1: Tree = Tree(1, [])
    leaf2: Tree = Tree(2, [])
    root: Tree = Tree(0, [leaf1, leaf2])
    print(root.value)
    print(root.children.len())
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "0\n2\n"

    def test_tree_child_access(self, compile_coex):
        """Access children of a tree node."""
        result = compile_coex('''
type Tree:
    value: int
    children: [Tree]
~

func main() -> int
    leaf1: Tree = Tree(10, [])
    leaf2: Tree = Tree(20, [])
    root: Tree = Tree(0, [leaf1, leaf2])
    c0 = root.children.get(0)
    c1 = root.children.get(1)
    print(c0.value)
    print(c1.value)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "10\n20\n"

    def test_bbox_with_vec3(self, compile_coex):
        """Nested UDTs: BBox containing Vec3s."""
        result = compile_coex('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

func main() -> int
    lo: Vec3 = Vec3(0.0, 0.0, 0.0)
    hi: Vec3 = Vec3(10.0, 20.0, 30.0)
    bb: BBox = BBox(lo, hi)
    print(bb.min_pt.x)
    print(bb.max_pt.z)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert "0.000000" in result.run_output
        assert "30.000000" in result.run_output

    def test_octreelike_structure(self, compile_coex):
        """OctreeNode-like structure: BBox + children list + data."""
        result = compile_coex('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

type OctNode:
    bounds: BBox
    children: [OctNode]
    alive: int
~

func main() -> int
    lo: Vec3 = Vec3(0.0, 0.0, 0.0)
    hi: Vec3 = Vec3(100.0, 100.0, 100.0)
    bb: BBox = BBox(lo, hi)
    root: OctNode = OctNode(bb, [], 1)
    print(root.alive)
    print(root.children.len())
    print(root.bounds.max_pt.x)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert "1\n" in result.run_output
        assert "0\n" in result.run_output
        assert "100.000000" in result.run_output
