"""Tests for task frame GC root tracking (BUG-134).

Verifies that heap-typed frame fields in task step functions are properly
GC-rooted across suspension points, preventing swept handles from being
used as stale pointers.
"""
import pytest


class TestTaskFrameRoots:
    """Test that task frame handles survive GC cycles."""

    def test_list_survives_across_suspension(self, expect_output):
        """List local in task frame must be rooted across child task suspension."""
        expect_output('''
type Node:
    value: int
    children: [Node]
~

task build(depth: int) -> Node
    if depth == 0
        return Node(0, [])
    ~
    children: [Node] = []
    i = 0
    while i < 2
        child := build(depth - 1)
        children = children.append(child)
        i = i + 1
    ~
    return Node(depth, children)
~

task count(node: Node) -> int
    if node.children.len() == 0
        return 1
    ~
    total = 0
    i = 0
    while i < node.children.len()
        c := count(node.children.get(i))
        total = total + c
        i = i + 1
    ~
    return total + 1
~

func main() -> int
    tree := build(4)
    n := count(tree)
    print(n)
    gc()
    tree2 := build(4)
    n2 := count(tree2)
    print(n2)
    return 0
~
''', "31\n31\n")

    def test_udt_survives_across_suspension(self, expect_output):
        """UDT locals in task frame must be rooted across suspensions."""
        expect_output('''
type Vec3:
    x: float
    y: float
    z: float
~

type Box:
    lo: Vec3
    hi: Vec3
~

type TreeNode:
    bounds: Box
    children: [TreeNode]
    depth: int
~

task make_children(b: Box) -> [Box]
    mx = (b.lo.x + b.hi.x) / 2.0
    my = (b.lo.y + b.hi.y) / 2.0
    mz = (b.lo.z + b.hi.z) / 2.0
    mid = Vec3(mx, my, mz)
    result: [Box] = []
    result = result.append(Box(b.lo, mid))
    result = result.append(Box(mid, b.hi))
    return result
~

task subdivide(node: TreeNode) -> TreeNode
    if node.children.len() > 0
        new_children: [TreeNode] = []
        ci = 0
        while ci < node.children.len()
            child := subdivide(node.children.get(ci))
            new_children = new_children.append(child)
            ci = ci + 1
        ~
        return TreeNode(node.bounds, new_children, node.depth)
    ~
    if node.depth >= 3
        return node
    ~
    boxes := make_children(node.bounds)
    children: [TreeNode] = []
    i = 0
    while i < boxes.len()
        bx = boxes.get(i)
        children = children.append(TreeNode(bx, [], node.depth + 1))
        i = i + 1
    ~
    return TreeNode(node.bounds, children, node.depth)
~

task count_nodes(node: TreeNode) -> int
    if node.children.len() == 0
        return 1
    ~
    total = 0
    i = 0
    while i < node.children.len()
        c := count_nodes(node.children.get(i))
        total = total + c
        i = i + 1
    ~
    return total + 1
~

func main() -> int
    bb = Box(Vec3(0.0, 0.0, 0.0), Vec3(100.0, 100.0, 100.0))
    root = TreeNode(bb, [], 0)
    gen = 0
    while gen < 3
        gen = gen + 1
        root := subdivide(root)
        n := count_nodes(root)
        print(n)
        gc()
    ~
    return 0
~
''', "3\n7\n15\n")

    def test_suspension_var_rooted(self, expect_output):
        """Task result variables (from child task calls) must be rooted in parent frame."""
        expect_output('''
type Item:
    name: string
    value: int
~

task create_item(n: int) -> Item
    return Item("item", n * 10)
~

task process_items() -> int
    a := create_item(1)
    b := create_item(2)
    c := create_item(3)
    return a.value + b.value + c.value
~

func main() -> int
    result := process_items()
    print(result)
    return 0
~
''', "60\n")

    def test_multi_gen_subdivide_evaporate(self, expect_output):
        """Multi-generation subdivide+evaporate pattern from thread context."""
        expect_output('''
type Node:
    value: int
    children: [Node]
    alive: int
    depth: int
~

task subdivide(node: Node) -> Node
    if node.children.len() > 0
        new_children: [Node] = []
        ci = 0
        while ci < node.children.len()
            child = node.children.get(ci)
            sub_child := subdivide(child)
            new_children = new_children.append(sub_child)
            ci = ci + 1
        ~
        return Node(node.value, new_children, node.alive, node.depth)
    ~
    if node.value == 0
        return node
    ~
    children: [Node] = []
    i = 0
    while i < 4
        child = Node(node.value / 4, [], 1, node.depth + 1)
        children = children.append(child)
        i = i + 1
    ~
    return Node(node.value, children, 1, node.depth)
~

task evaporate(node: Node) -> Node
    if node.children.len() == 0
        if node.value == 0
            return Node(0, [], 0, node.depth)
        ~
        return node
    ~
    new_children: [Node] = []
    ci = 0
    while ci < node.children.len()
        child = node.children.get(ci)
        evap_child := evaporate(child)
        new_children = new_children.append(evap_child)
        ci = ci + 1
    ~
    return Node(node.value, new_children, 1, node.depth)
~

task count_nodes(node: Node) -> int
    if node.children.len() == 0
        return 1
    ~
    total = 0
    i = 0
    while i < node.children.len()
        child_count := count_nodes(node.children.get(i))
        total = total + child_count
        i = i + 1
    ~
    return total + 1
~

thread coordinator(done_ch: Channel<int>) -> void
    root = Node(1000, [], 1, 0)
    gen = 0
    while gen < 4
        gen = gen + 1
        root := subdivide(root)
        n := count_nodes(root)
        root := evaporate(root)
        n2 := count_nodes(root)
        print(n2)
        gc()
    ~
    done_ch.send(1)
~

func main() -> int
    done: Channel<int> = Channel.new()
    coordinator(done)
    result = done.receive()
    print("done")
    return 0
~
''', "5\n21\n85\n341\ndone\n")

    def test_concurrent_gc_pressure_compaction(self, expect_output):
        """BUG-136: Compaction prev_buffer must survive in-flight gc_handle_deref.

        Two threads: one building/traversing a deep octree (heavy handle derefs),
        one generating allocation pressure that triggers frequent GC+compaction.
        Without the two-generation buffer fix, this crashes with SIGBUS because
        prev_buffer is munmap'd while mutator holds raw pointers into it.
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

type OctreeNode:
    bounds: BBox
    face_count: int
    children: [OctreeNode]
    alive: int
    depth: int
~

task make_octants(b: BBox) -> [BBox]
    mid_x = (b.min_pt.x + b.max_pt.x) / 2.0
    mid_y = (b.min_pt.y + b.max_pt.y) / 2.0
    mid_z = (b.min_pt.z + b.max_pt.z) / 2.0
    mid = Vec3(mid_x, mid_y, mid_z)
    result: [BBox] = []
    result = result.append(BBox(b.min_pt, mid))
    result = result.append(BBox(Vec3(mid_x, b.min_pt.y, b.min_pt.z), Vec3(b.max_pt.x, mid_y, mid_z)))
    result = result.append(BBox(Vec3(b.min_pt.x, mid_y, b.min_pt.z), Vec3(mid_x, b.max_pt.y, mid_z)))
    result = result.append(BBox(Vec3(mid_x, mid_y, b.min_pt.z), Vec3(b.max_pt.x, b.max_pt.y, mid_z)))
    result = result.append(BBox(Vec3(b.min_pt.x, b.min_pt.y, mid_z), Vec3(mid_x, mid_y, b.max_pt.z)))
    result = result.append(BBox(Vec3(mid_x, b.min_pt.y, mid_z), Vec3(b.max_pt.x, mid_y, b.max_pt.z)))
    result = result.append(BBox(Vec3(b.min_pt.x, mid_y, mid_z), Vec3(mid_x, b.max_pt.y, b.max_pt.z)))
    result = result.append(BBox(mid, b.max_pt))
    return result
~

task subdivide_one_level(node: OctreeNode) -> OctreeNode
    if node.alive == 0
        return node
    ~
    if node.children.len() > 0
        new_children: [OctreeNode] = []
        ci = 0
        while ci < node.children.len()
            child := subdivide_one_level(node.children.get(ci))
            new_children = new_children.append(child)
            ci = ci + 1
        ~
        return OctreeNode(node.bounds, node.face_count, new_children, 1, node.depth)
    ~
    if node.face_count == 0
        return node
    ~
    octants := make_octants(node.bounds)
    children: [OctreeNode] = []
    ci = 0
    while ci < 8
        oct = octants.get(ci)
        children = children.append(OctreeNode(oct, node.face_count, [], 1, node.depth + 1))
        ci = ci + 1
    ~
    return OctreeNode(node.bounds, node.face_count, children, 1, node.depth)
~

task count_nodes(node: OctreeNode) -> int
    if node.children.len() == 0
        return 1
    ~
    total = 0
    i = 0
    while i < node.children.len()
        child_count := count_nodes(node.children.get(i))
        total = total + child_count
        i = i + 1
    ~
    return total + 1
~

thread alloc_pressure(stop_ch: Channel<int>) -> void
    i = 0
    while i < 2000000
        garbage: [int] = []
        garbage = garbage.append(i)
        garbage = garbage.append(i * 2)
        garbage = garbage.append(i * 3)
        i = i + 1
        if i % 100000 == 0
            gc()
        ~
    ~
    stop_ch.send(1)
~

thread coordinator(done_ch: Channel<int>) -> void
    stop: Channel<int> = Channel.new()
    alloc_pressure(stop)

    bb = BBox(Vec3(-40.0, -40.0, -40.0), Vec3(40.0, 40.0, 40.0))
    root = OctreeNode(bb, 200, [], 1, 0)
    generation = 0
    while generation < 5
        generation = generation + 1
        root := subdivide_one_level(root)
        n := count_nodes(root)
        gc()
    ~
    result = stop.receive()
    print("Done")
    done_ch.send(1)
~

func main() -> int
    done: Channel<int> = Channel.new()
    coordinator(done)
    result = done.receive()
    return 0
~
''', "Done\n")

    def test_dead_thread_objects_survive_compaction(self, expect_output):
        """BUG-137: Dead thread objects in compaction buffers must be compacted,
        not left behind to be munmap'd by buffer rotation."""
        expect_output('''
task make_data(ch: Channel<string>) -> int
    # Create substantial data that will be compacted
    data = "dead-thread-data-" + String.from(42)
    ch.send(data)
    # Thread exits after this — marked dead (0xDEAD)
    return 0
~

func churn(n: int) -> int
    i = 0
    total = 0
    while i < n
        s = "churn-" + String.from(i)
        total = total + s.len()
        i = i + 1
    ~
    return total
~

func main() -> int
    # Spawn threads that create data and immediately exit
    ch1: Channel<string> = Channel.new()
    ch2: Channel<string> = Channel.new()
    ch3: Channel<string> = Channel.new()
    ch4: Channel<string> = Channel.new()
    make_data(ch1)
    make_data(ch2)
    make_data(ch3)
    make_data(ch4)

    # Receive data from dead threads
    d1 = ch1.receive()
    d2 = ch2.receive()
    d3 = ch3.receive()
    d4 = ch4.receive()

    # Force multiple GC+compaction cycles while holding dead thread data.
    # Without BUG-137 fix, the compaction buffer holding these strings
    # gets munmap'd because dead threads are skipped → SIGSEGV.
    i = 0
    while i < 5
        gc()
        discard = churn(120000)
        i = i + 1
    ~

    # Verify data is still accessible
    print(d1)
    print(d2)
    print(d3)
    print(d4)
    return 0
~
''', "dead-thread-data-42\ndead-thread-data-42\ndead-thread-data-42\ndead-thread-data-42\n")
