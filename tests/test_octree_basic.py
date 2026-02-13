"""Tests for octree/torus basic operations - math UDTs, torus generation, octree structure."""
import pytest


class TestOctreeBasic:
    """Test math UDTs and basic octree operations."""

    def test_vec3_arithmetic(self, compile_coex):
        """Vec3 add, sub, scale, dot, length."""
        result = compile_coex('''
type Vec3:
    x: float
    y: float
    z: float
~

func vec3_add(a: Vec3, b: Vec3) -> Vec3
    return Vec3(a.x + b.x, a.y + b.y, a.z + b.z)
~

func vec3_sub(a: Vec3, b: Vec3) -> Vec3
    return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)
~

func vec3_scale(v: Vec3, s: float) -> Vec3
    return Vec3(v.x * s, v.y * s, v.z * s)
~

func vec3_dot(a: Vec3, b: Vec3) -> float
    return a.x * b.x + a.y * b.y + a.z * b.z
~

func vec3_length(v: Vec3) -> float
    return sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
~

func main() -> int
    a = Vec3(1.0, 2.0, 3.0)
    b = Vec3(4.0, 5.0, 6.0)

    c = vec3_add(a, b)
    print(c.x)
    print(c.y)
    print(c.z)

    d = vec3_dot(a, b)
    print(d)

    e = vec3_length(Vec3(3.0, 4.0, 0.0))
    print(e)

    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        lines = result.run_output.strip().split('\n')
        assert float(lines[0]) == 5.0   # c.x = 1+4
        assert float(lines[1]) == 7.0   # c.y = 2+5
        assert float(lines[2]) == 9.0   # c.z = 3+6
        assert float(lines[3]) == 32.0  # dot = 1*4+2*5+3*6
        assert float(lines[4]) == 5.0   # length(3,4,0) = 5

    def test_bbox_containment(self, compile_coex):
        """BBox contains_point check."""
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

func bbox_contains(b: BBox, p: Vec3) -> int
    if p.x >= b.min_pt.x and p.x <= b.max_pt.x and p.y >= b.min_pt.y and p.y <= b.max_pt.y and p.z >= b.min_pt.z and p.z <= b.max_pt.z
        return 1
    ~
    return 0
~

func main() -> int
    bb = BBox(Vec3(0.0, 0.0, 0.0), Vec3(10.0, 10.0, 10.0))
    print(bbox_contains(bb, Vec3(5.0, 5.0, 5.0)))
    print(bbox_contains(bb, Vec3(15.0, 5.0, 5.0)))
    print(bbox_contains(bb, Vec3(0.0, 0.0, 0.0)))
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "1\n0\n1\n"

    def test_torus_small(self, compile_coex):
        """Generate a small torus (4 steps) and count triangles."""
        result = compile_coex('''
type Vec3:
    x: float
    y: float
    z: float
~

type Triangle:
    v0: Vec3
    v1: Vec3
    v2: Vec3
    normal: Vec3
~

func vec3_sub(a: Vec3, b: Vec3) -> Vec3
    return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)
~

func vec3_cross(a: Vec3, b: Vec3) -> Vec3
    return Vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)
~

func vec3_normalize(v: Vec3) -> Vec3
    len = sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
    if len > 0.0001
        return Vec3(v.x / len, v.y / len, v.z / len)
    ~
    return v
~

func make_torus(R: float, r: float, steps: int) -> [Triangle]
    PI2 = 6.28318530718
    triangles: [Triangle] = []
    i = 0
    while i < steps
        j = 0
        while j < steps
            theta0 = i * PI2 / steps
            theta1 = (i + 1) * PI2 / steps
            phi0 = j * PI2 / steps
            phi1 = (j + 1) * PI2 / steps

            p00 = Vec3((R + r * cos(phi0)) * cos(theta0), r * sin(phi0), (R + r * cos(phi0)) * sin(theta0))
            p10 = Vec3((R + r * cos(phi0)) * cos(theta1), r * sin(phi0), (R + r * cos(phi0)) * sin(theta1))
            p01 = Vec3((R + r * cos(phi1)) * cos(theta0), r * sin(phi1), (R + r * cos(phi1)) * sin(theta0))
            p11 = Vec3((R + r * cos(phi1)) * cos(theta1), r * sin(phi1), (R + r * cos(phi1)) * sin(theta1))

            e1 = vec3_sub(p10, p00)
            e2 = vec3_sub(p01, p00)
            n1 = vec3_normalize(vec3_cross(e1, e2))
            triangles = triangles.append(Triangle(p00, p10, p01, n1))

            e3 = vec3_sub(p01, p10)
            e4 = vec3_sub(p11, p10)
            n2 = vec3_normalize(vec3_cross(e4, e3))
            triangles = triangles.append(Triangle(p10, p11, p01, n2))

            j = j + 1
        ~
        i = i + 1
    ~
    return triangles
~

func main() -> int
    triangles = make_torus(50.0, 15.0, 4)
    print(triangles.len())
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        # 4 steps x 4 steps x 2 triangles per quad = 32
        assert result.run_output == "32\n"

    def test_octree_node_creation(self, compile_coex):
        """Create OctreeNode with children list."""
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

type OctreeNode:
    bounds: BBox
    face_count: int
    children: [OctreeNode]
    alive: int
~

func main() -> int
    root_bb = BBox(Vec3(0.0, 0.0, 0.0), Vec3(100.0, 100.0, 100.0))
    child_bb = BBox(Vec3(0.0, 0.0, 0.0), Vec3(50.0, 50.0, 50.0))
    child = OctreeNode(child_bb, 5, [], 1)
    children: [OctreeNode] = []
    children = children.append(child)
    root = OctreeNode(root_bb, 10, children, 1)

    print(root.face_count)
    print(root.children.len())
    c0 = root.children.get(0)
    print(c0.face_count)
    print(c0.alive)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "10\n1\n5\n1\n"
