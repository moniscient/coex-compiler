"""
BUG-129: Unrooted intermediate string concat results crash under GC compaction.

When evaluating a chained string concat like `a + b + c + d`, the intermediate
result of `a + b` is a raw pointer not stored in any shadow stack slot. If
evaluating `c` triggers GC+compaction, the intermediate moves and its old
TLAB is freed, making the raw pointer stale.

Fix: In generate_binary, save left operand's handle before evaluating right,
then re-derive via gc_handle_deref. Combined with grace period -2 to keep
unrooted intermediates alive through 2 GC cycles.
"""
import pytest


class TestBug129StringConcatGC:
    """Test string concatenation under GC pressure."""

    def test_chained_string_concat_with_gc_pressure(self, expect_output):
        """Chained concat with allocation-heavy functions between concats."""
        expect_output('''
func make_str(n: int) -> string
    return String.from(n)
~

func churn(n: int) -> int
    i = 0
    while i < n
        s = String.from(i)
        i = i + 1
    ~
    return n
~

func main() -> int
    a = make_str(1)
    b = make_str(2)
    c = make_str(3)
    d = make_str(4)
    # Force GC between concat steps by allocating pressure
    churn(120000)
    result = a + "," + b + "," + c + "," + d
    print(result)
    return 0
~
''', "1,2,3,4\n")

    def test_recursive_udt_string_concat_depth4(self, expect_output):
        """The original BUG-129 reproducer: recursive octree with string concat."""
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
type OctreeNode:
    bounds: BBox
    face_count: int
    children: [OctreeNode]
    alive: int
    depth: int
~
func bbox_center(b: BBox) -> Vec3
    return Vec3((b.min_pt.x + b.max_pt.x) * 0.5, (b.min_pt.y + b.max_pt.y) * 0.5, (b.min_pt.z + b.max_pt.z) * 0.5)
~
func bbox_size(b: BBox) -> float
    return b.max_pt.x - b.min_pt.x
~
func collect(node: OctreeNode) -> string
    if node.alive == 0
        return ""
    ~
    if node.children.len() == 0
        c = bbox_center(node.bounds)
        sz = bbox_size(node.bounds)
        cx_s = String.from(c.x)
        cy_s = String.from(c.y)
        cz_s = String.from(c.z)
        sz_s = String.from(sz)
        result = "[" + cx_s + "," + cy_s + "," + cz_s + "," + sz_s + "]"
        return result
    ~
    parts = ""
    ci = 0
    while ci < node.children.len()
        child_str = collect(node.children.get(ci))
        if child_str.len() > 0
            if parts.len() > 0
                parts = parts + "," + child_str
            else
                parts = child_str
            ~
        ~
        ci = ci + 1
    ~
    return parts
~
func build_octree(bounds: BBox, depth: int, max_depth: int) -> OctreeNode
    if depth >= max_depth
        return OctreeNode(bounds, depth, [], 1, depth)
    ~
    c = bbox_center(bounds)
    children: [OctreeNode] = []
    iz = 0
    while iz < 2
        iy = 0
        while iy < 2
            ix = 0
            while ix < 2
                lo_x = bounds.min_pt.x
                if ix == 1
                    lo_x = c.x
                ~
                hi_x = c.x
                if ix == 1
                    hi_x = bounds.max_pt.x
                ~
                lo_y = bounds.min_pt.y
                if iy == 1
                    lo_y = c.y
                ~
                hi_y = c.y
                if iy == 1
                    hi_y = bounds.max_pt.y
                ~
                lo_z = bounds.min_pt.z
                if iz == 1
                    lo_z = c.z
                ~
                hi_z = c.z
                if iz == 1
                    hi_z = bounds.max_pt.z
                ~
                child_bb = BBox(Vec3(lo_x, lo_y, lo_z), Vec3(hi_x, hi_y, hi_z))
                child = build_octree(child_bb, depth + 1, max_depth)
                children = children.append(child)
                ix = ix + 1
            ~
            iy = iy + 1
        ~
        iz = iz + 1
    ~
    return OctreeNode(bounds, 0, children, 1, depth)
~
func main() -> int
    bounds = BBox(Vec3(-70.0, -20.0, -70.0), Vec3(70.0, 20.0, 70.0))
    tree = build_octree(bounds, 0, 4)
    result = "[" + collect(tree) + "]"
    print("OK: " + String.from(result.len()))
    return 0
~
''', "OK: 113665\n")

    def test_string_eq_after_gc_pressure(self, expect_output):
        """String equality comparison where left is stale after right allocates."""
        expect_output('''
func make_str(n: int) -> string
    return "item_" + String.from(n)
~

func churn(n: int) -> string
    i = 0
    while i < n
        s = String.from(i)
        i = i + 1
    ~
    return "item_5"
~

func main() -> int
    target = make_str(5)
    # churn creates 120K allocs, triggering GC
    # Then the == compares stale target with fresh result
    if target == churn(120000)
        print("match")
    else
        print("no match")
    ~
    return 0
~
''', "match\n")
