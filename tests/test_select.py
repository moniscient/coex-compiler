"""Tests for select statement on multiple channels."""
import pytest


class TestSelect:
    """Test select statement codegen."""

    def test_single_channel_select(self, compile_coex):
        """Select with single channel degenerates to receive."""
        result = compile_coex('''
func main() -> int
    ch: Channel<int> = Channel.new()
    ch.send(42)
    select
        case val <- ch
            print(val)
        ~
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "42\n"

    def test_two_channel_select(self, compile_coex):
        """Select with two channels, data on second."""
        result = compile_coex('''
func main() -> int
    ch1: Channel<int> = Channel.new()
    ch2: Channel<int> = Channel.new()
    ch2.send(99)
    select
        case a <- ch1
            print(a)
        ~
        case b <- ch2
            print(b)
        ~
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "99\n"

    def test_select_in_while_loop(self, compile_coex):
        """Select in while loop for continuous consumption."""
        result = compile_coex('''
func main() -> int
    ch: Channel<int> = Channel.new()
    ch.send(1)
    ch.send(2)
    ch.send(3)

    count = 0
    while count < 3
        select
            case val <- ch
                count = count + 1
                print(val)
            ~
        ~
    ~
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "1\n2\n3\n"

    def test_select_with_task_producers(self, compile_coex):
        """Select with task producers on multiple channels."""
        result = compile_coex('''
task produce_a(ch: Channel<int>) -> int
    ch.send(10)
    return 0
~

task produce_b(ch: Channel<int>) -> int
    ch.send(20)
    return 0
~

func main() -> int
    ch_a: Channel<int> = Channel.new()
    ch_b: Channel<int> = Channel.new()
    done_a := produce_a(ch_a)
    done_b := produce_b(ch_b)

    total = 0
    count = 0
    while count < 2
        select
            case a <- ch_a
                total = total + a
                count = count + 1
            ~
            case b <- ch_b
                total = total + b
                count = count + 1
            ~
        ~
    ~
    print(total)
    return 0
~
''')
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed (rc={result.returncode}):\n{result.stderr}"
        assert result.run_output == "30\n"
