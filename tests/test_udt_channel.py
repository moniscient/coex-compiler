"""Tests for sending/receiving UDTs through channels."""
import pytest


class TestUDTChannel:
    """Test user-defined types through channels."""

    def test_simple_udt_through_channel(self, compile_coex):
        """Send a simple UDT through a channel and receive it."""
        result = compile_coex('''
type Point:
    x: int
    y: int
~

func main() -> int
    ch: Channel<Point> = Channel.new()
    p: Point = Point(3, 7)
    ch.send(p)
    q = ch.receive()
    print(q.x)
    print(q.y)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "3\n7\n"

    def test_udt_with_float_fields(self, compile_coex):
        """UDT with float fields through channel."""
        result = compile_coex('''
type Vec3:
    x: float
    y: float
    z: float
~

func main() -> int
    ch: Channel<Vec3> = Channel.new()
    v: Vec3 = Vec3(1.5, 2.5, 3.5)
    ch.send(v)
    w = ch.receive()
    print(w.x)
    print(w.y)
    print(w.z)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert "1.500000" in result.run_output
        assert "2.500000" in result.run_output
        assert "3.500000" in result.run_output

    def test_udt_task_to_func(self, compile_coex):
        """Task sends UDT, func receives (cross-thread)."""
        result = compile_coex('''
type Point:
    x: int
    y: int
~

task sender(ch: Channel<Point>) -> int
    p: Point = Point(10, 20)
    ch.send(p)
    return 0
~

func main() -> int
    ch: Channel<Point> = Channel.new()
    done := sender(ch)
    q = ch.receive()
    print(q.x)
    print(q.y)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "10\n20\n"

    def test_udt_with_list_field(self, compile_coex):
        """UDT with list field through channel."""
        result = compile_coex('''
type Container:
    name: int
    items: [int]
~

func main() -> int
    ch: Channel<Container> = Channel.new()
    c: Container = Container(42, [1, 2, 3])
    ch.send(c)
    d = ch.receive()
    print(d.name)
    print(d.items.len())
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "42\n3\n"
