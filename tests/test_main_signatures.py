"""
Tests for flexible main() function signatures.

Supported signatures:
1. func main() -> int                                              - basic
2. func main(args: [string]) -> int                                - with args
3. func main(stdin: posix, stdout: posix, stderr: posix) -> int   - with stdio
4. func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int - full
"""

import pytest


class TestMainBasic:
    """Test basic main() -> int signature."""

    def test_main_no_args(self, expect_output):
        """Basic main with no parameters."""
        expect_output('''
func main() -> int
    print(42)
    return 0
~
''', "42\n")

    def test_main_returns_exit_code(self, compile_coex):
        """Main return value becomes exit code."""
        result = compile_coex('''
func main() -> int
    return 5
~
''')
        assert result.compile_success
        # run_success is False when exit code != 0
        assert result.run_success is False


@pytest.mark.skip(reason="Tests block on stdin in CI environment")
class TestMainWithArgs:
    """Test main(args: [string]) -> int signature."""

    def test_main_with_args_count(self, compile_binary):
        """Main receives command line arguments."""
        binary = compile_binary('''
func main(args: [string]) -> int
    print(args.len())
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        # Run with arguments
        proc = binary.run("one", "two", "three")
        # args[0] is program name, so 4 total
        assert proc.stdout.strip() == "4", f"Expected 4 args, got: {proc.stdout.strip()}"

    def test_main_with_args_access(self, compile_binary):
        """Main can access individual arguments via .get() method."""
        binary = compile_binary('''
func main(args: [string]) -> int
    if args.len() > 1
        print(args.get(1))
    ~
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run("hello")
        assert proc.stdout.strip() == "hello", f"Expected 'hello', got: {proc.stdout.strip()}"

    def test_main_with_args_index_access(self, compile_binary):
        """Main can access individual arguments via [] indexing."""
        binary = compile_binary('''
func main(args: [string]) -> int
    if args.len() > 1
        print(args[1])
    ~
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run("hello")
        assert proc.stdout.strip() == "hello", f"Expected 'hello', got: {proc.stdout.strip()}"

    def test_main_with_args_loop(self, compile_binary):
        """Main can iterate over arguments using index and print them."""
        binary = compile_binary('''
func main(args: [string]) -> int
    for i in 1..args.len()
        print(args[i])
    ~
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run("one", "two", "three")
        lines = proc.stdout.strip().split("\n")
        assert lines == ["one", "two", "three"], f"Expected ['one', 'two', 'three'], got: {lines}"


@pytest.mark.skip(reason="Tests block on stdin in CI environment")
class TestMainWithStdio:
    """Test main(stdin: posix, stdout: posix, stderr: posix) -> int signature."""

    def test_main_stdout_writeln(self, compile_binary):
        """Main can write to stdout posix handle."""
        binary = compile_binary('''
func main(stdin: posix, stdout: posix, stderr: posix) -> int
    stdout.writeln("hello via stdout")
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run()
        assert "hello via stdout" in proc.stdout, f"Expected 'hello via stdout' in stdout, got: {proc.stdout}"

    def test_main_stderr_writeln(self, compile_binary):
        """Main can write to stderr posix handle."""
        binary = compile_binary('''
func main(stdin: posix, stdout: posix, stderr: posix) -> int
    stderr.writeln("error message")
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run()
        assert "error message" in proc.stderr, f"Expected 'error message' in stderr, got: {proc.stderr}"


@pytest.mark.skip(reason="Tests block on stdin in CI environment")
class TestMainFull:
    """Test main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int signature."""

    def test_main_full_signature(self, compile_binary):
        """Main with both args and stdio."""
        binary = compile_binary('''
func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
    stdout.writeln("arg count:")
    print(args.len())
    return 0
~
''')
        assert binary.compile_success, f"Compilation failed:\n{binary.compile_output}"
        proc = binary.run("test")
        assert "arg count:" in proc.stdout, f"Expected 'arg count:' in stdout, got: {proc.stdout}"
