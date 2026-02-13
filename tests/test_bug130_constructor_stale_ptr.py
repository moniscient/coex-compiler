"""Test for BUG-130: Constructor stale pointer when evaluating field expressions.

When constructing a UDT like OctreeNode(node.bounds, 0, [], 0, node.depth),
evaluating the `[]` arg (which allocates) can trigger GC+compaction, making
the BBox* from the earlier `node.bounds` arg stale. The constructor then calls
gc_ptr_to_handle on the stale pointer, reading garbage.
"""
import pytest

class TestBug130ConstructorStalePtr:
    """Constructor stale pointer across arg evaluation."""

    def test_nested_udt_constructor_basic(self, expect_output):
        """Basic nested UDT constructor without GC pressure."""
        expect_output('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

type Node:
    bounds: BBox
    count: int
    children: [Node]
    alive: int
~

func main() -> int
    b = BBox(Vec3(1.0, 2.0, 3.0), Vec3(4.0, 5.0, 6.0))
    n = Node(b, 5, [], 1)
    print(n.bounds.min_pt.x)
    print(n.bounds.max_pt.z)
    print(n.count)
    print(n.alive)
    return 0
~
''', "1.000000\n6.000000\n5\n1\n")

    def test_constructor_stale_ptr_across_list_alloc(self, expect_output):
        """Constructor arg evaluated before [] allocation gets stale pointer.

        This is the exact pattern: Node(existing_bbox, 0, [], 0, depth)
        The existing_bbox raw pointer becomes stale when [] allocates.
        """
        expect_output('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

type Node:
    bounds: BBox
    count: int
    children: [Node]
    alive: int
~

func make_node(b: BBox, depth: int) -> Node
    return Node(b, depth, [], 1)
~

func main() -> int
    b = BBox(Vec3(10.0, 20.0, 30.0), Vec3(40.0, 50.0, 60.0))
    n = make_node(b, 3)
    print(n.bounds.min_pt.x)
    print(n.bounds.max_pt.z)
    print(n.count)
    return 0
~
''', "10.000000\n60.000000\n3\n")

    def test_constructor_stale_ptr_gc_pressure(self, expect_output):
        """Stress test: many constructor calls with GC pressure."""
        expect_output('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

type Node:
    bounds: BBox
    count: int
    children: [Node]
    alive: int
~

func build_tree(b: BBox, depth: int) -> Node
    if depth == 0
        return Node(b, 0, [], 1)
    ~
    mid_x = (b.min_pt.x + b.max_pt.x) / 2.0
    mid_y = (b.min_pt.y + b.max_pt.y) / 2.0
    mid_z = (b.min_pt.z + b.max_pt.z) / 2.0
    children: [Node] = []
    i = 0
    while i < 8
        lx = b.min_pt.x
        ly = b.min_pt.y
        lz = b.min_pt.z
        hx = mid_x
        hy = mid_y
        hz = mid_z
        if i >= 4
            lz = mid_z
            hz = b.max_pt.z
        ~
        if (i / 2) % 2 == 1
            ly = mid_y
            hy = b.max_pt.y
        ~
        if i % 2 == 1
            lx = mid_x
            hx = b.max_pt.x
        ~
        child_box = BBox(Vec3(lx, ly, lz), Vec3(hx, hy, hz))
        child = build_tree(child_box, depth - 1)
        children = children.append(child)
        i = i + 1
    ~
    return Node(b, 8, children, 1)
~

func count_nodes(n: Node) -> int
    if n.children.len() == 0
        return 1
    ~
    total = 1
    i = 0
    while i < n.children.len()
        child = n.children.get(i)
        total = total + count_nodes(child)
        i = i + 1
    ~
    return total
~

func main() -> int
    root_box = BBox(Vec3(0.0, 0.0, 0.0), Vec3(100.0, 100.0, 100.0))
    tree = build_tree(root_box, 3)
    print(count_nodes(tree))
    print(tree.bounds.min_pt.x)
    print(tree.bounds.max_pt.z)
    return 0
~
''', "585\n0.000000\n100.000000\n")

    def test_evaporate_pattern(self, expect_output):
        """Test the exact evaporate pattern: reconstruct with existing bounds."""
        expect_output('''
type Vec3:
    x: float
    y: float
    z: float
~

type BBox:
    min_pt: Vec3
    max_pt: Vec3
~

type Node:
    bounds: BBox
    count: int
    children: [Node]
    alive: int
~

func evaporate(node: Node) -> Node
    if node.children.len() == 0
        if node.count == 0
            return Node(node.bounds, 0, [], 0)
        ~
        return node
    ~
    new_children: [Node] = []
    ci = 0
    while ci < node.children.len()
        child = node.children.get(ci)
        evap_child = evaporate(child)
        new_children = new_children.append(evap_child)
        ci = ci + 1
    ~
    return Node(node.bounds, node.count, new_children, 1)
~

func build_tree(b: BBox, depth: int) -> Node
    if depth == 0
        return Node(b, 0, [], 1)
    ~
    children: [Node] = []
    mid_x = (b.min_pt.x + b.max_pt.x) / 2.0
    mid_y = (b.min_pt.y + b.max_pt.y) / 2.0
    mid_z = (b.min_pt.z + b.max_pt.z) / 2.0
    i = 0
    while i < 8
        lx = b.min_pt.x
        ly = b.min_pt.y
        lz = b.min_pt.z
        hx = mid_x
        hy = mid_y
        hz = mid_z
        if i >= 4
            lz = mid_z
            hz = b.max_pt.z
        ~
        if (i / 2) % 2 == 1
            ly = mid_y
            hy = b.max_pt.y
        ~
        if i % 2 == 1
            lx = mid_x
            hx = b.max_pt.x
        ~
        child_box = BBox(Vec3(lx, ly, lz), Vec3(hx, hy, hz))
        child = build_tree(child_box, depth - 1)
        children = children.append(child)
        i = i + 1
    ~
    return Node(b, 8, children, 1)
~

func count_alive(n: Node) -> int
    if n.alive == 0
        return 0
    ~
    if n.children.len() == 0
        return 1
    ~
    total = 0
    i = 0
    while i < n.children.len()
        child = n.children.get(i)
        total = total + count_alive(child)
        i = i + 1
    ~
    return total
~

func main() -> int
    root_box = BBox(Vec3(0.0, 0.0, 0.0), Vec3(64.0, 64.0, 64.0))
    tree = build_tree(root_box, 3)
    print(count_alive(tree))
    evap = evaporate(tree)
    print(count_alive(evap))
    print(evap.bounds.min_pt.x)
    print(evap.bounds.max_pt.z)
    return 0
~
''', "512\n0\n0.000000\n64.000000\n")
