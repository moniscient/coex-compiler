"""Tests for channel try_receive method."""
import pytest


class TestChannelTryReceive:
    """Test channel try_receive (non-blocking receive)."""

    def test_try_receive_empty_returns_nil(self, compile_coex):
        """try_receive on an empty channel should return nil."""
        result = compile_coex('''
func main() -> int
    ch: Channel<int> = Channel.new()
    val = ch.try_receive()
    if val == nil
        print(1)
    else
        print(0)
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.stderr}"
        assert "1\n" in result.run_output

    def test_try_receive_after_send(self, compile_coex):
        """try_receive after send should return the value."""
        result = compile_coex('''
func main() -> int
    ch: Channel<int> = Channel.new()
    ch.send(42)
    val = ch.try_receive()
    if val != nil
        print(val)
    else
        print(0)
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.stderr}"
        assert "42\n" in result.run_output

    def test_try_receive_drain_loop(self, compile_coex):
        """Send 5 values, try_receive until nil, verify all received."""
        result = compile_coex('''
func main() -> int
    ch: Channel<int> = Channel.new()
    ch.send(10)
    ch.send(20)
    ch.send(30)
    ch.send(40)
    ch.send(50)

    count = 0
    total = 0
    while true
        val = ch.try_receive()
        if val == nil
            break
        ~
        count = count + 1
        total = total + val
    ~
    print(count)
    print(total)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.stderr}"
        assert "5\n" in result.run_output
        assert "150\n" in result.run_output

    def test_try_receive_with_task_producer(self, compile_coex):
        """try_receive with a task sending values."""
        result = compile_coex('''
task producer(ch: Channel<int>) -> int
    ch.send(100)
    ch.send(200)
    ch.send(300)
    return 0
~

func main() -> int
    ch: Channel<int> = Channel.new()
    done := producer(ch)

    total = 0
    while true
        val = ch.try_receive()
        if val == nil
            break
        ~
        total = total + val
    ~
    print(total)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.stderr}"
        assert "600\n" in result.run_output
