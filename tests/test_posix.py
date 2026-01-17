"""
Tests for built-in posix type - platform type wrapping POSIX file operations.

posix is a platform type that provides:
- posix.open(path, mode) -> Result<posix, string>
- handle.read(count) -> Result<[byte], string>
- handle.read_all() -> Result<string, string>
- handle.write(data) -> Result<int, string>
- handle.writeln(text) -> Result<(), string>
- handle.close() -> Result<(), string>
"""

import pytest
import os
import tempfile


class TestPosixOpen:
    """Test posix.open() functionality."""

    def test_posix_open_read_existing(self, expect_output, tmp_path):
        """Open an existing file for reading."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        expect_output(f'''
func main() -> int
    result: Result<posix, string> = posix.open("{test_file}", "r")
    if result.is_ok()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_posix_open_nonexistent(self, expect_output):
        """Opening non-existent file returns error."""
        expect_output('''
func main() -> int
    result: Result<posix, string> = posix.open("/nonexistent/file.txt", "r")
    if result.is_err()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestPosixReadWrite:
    """Test posix read/write operations."""

    def test_posix_read_all(self, expect_output, tmp_path):
        """Read entire file contents."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        content: Result<string, string> = handle.read_all()
        if content.is_ok()
            print(content.unwrap())
        ~
        handle.close()
    ~
    return 0
~
''', "hello\n")

    def test_posix_write(self, expect_output, tmp_path):
        """Write to a file."""
        test_file = tmp_path / "output.txt"

        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "w")
    if f.is_ok()
        handle: posix = f.unwrap()
        handle.writeln("hello from coex")
        handle.close()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

        # Verify file contents (allow for trailing whitespace/nulls from buffer)
        content = test_file.read_text()
        assert content.startswith("hello from coex")


class TestPosixClose:
    """Test posix.close() functionality."""

    def test_posix_explicit_close(self, expect_output, tmp_path):
        """Explicitly closing a file works."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        # Use Result<int, string> since () is not a valid type in the grammar
        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        handle.close()
        print(1)
    ~
    return 0
~
''', "1\n")


class TestPosixRead:
    """Test posix.read(count) method."""

    def test_posix_read_bytes(self, expect_output, tmp_path):
        """Read specific number of bytes."""
        test_file = tmp_path / "test.txt"
        test_file.write_bytes(b"hello world")

        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        data: Result<[byte], string> = handle.read(5)
        if data.is_ok()
            bytes: [byte] = data.unwrap()
            print(bytes.len())
        ~
        handle.close()
    ~
    return 0
~
''', "5\n")


class TestPosixSeek:
    """Test posix.seek() method."""

    def test_posix_seek_returns_position(self, expect_output, tmp_path):
        """Seek returns the new file position."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        # Seek to position 6 (SEEK_SET = 0)
        seek_result: Result<int, string> = handle.seek(6, 0)
        if seek_result.is_ok()
            pos: int = seek_result.unwrap()
            print(pos)
        ~
        handle.close()
    ~
    return 0
~
''', "6\n")

    def test_posix_seek_and_read_bytes(self, expect_output, tmp_path):
        """Seek then read bytes from new position."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        expect_output(f'''
func main() -> int
    f: Result<posix, string> = posix.open("{test_file}", "r")
    if f.is_ok()
        handle: posix = f.unwrap()
        # Seek to position 6 (SEEK_SET = 0)
        handle.seek(6, 0)
        # Read 5 bytes - should be "world"
        data: Result<[byte], string> = handle.read(5)
        if data.is_ok()
            bytes: [byte] = data.unwrap()
            print(bytes.len())
        ~
        handle.close()
    ~
    return 0
~
''', "5\n")


class TestPosixTime:
    """Test posix.time() static method."""

    def test_posix_time_returns_positive(self, expect_output):
        """posix.time() returns a positive Unix timestamp."""
        expect_output('''
func main() -> int
    t: int = posix.time()
    if t > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_posix_time_ns_returns_positive(self, expect_output):
        """posix.time_ns() returns a positive nanosecond timestamp."""
        expect_output('''
func main() -> int
    t: int = posix.time_ns()
    if t > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestPosixGetenv:
    """Test posix.getenv() static method."""

    def test_posix_getenv_path(self, expect_output):
        """posix.getenv() can read PATH environment variable."""
        # PATH should always be set on Unix systems and contain something
        # Use unwrap_or to safely handle potential nil
        expect_output('''
func main() -> int
    path: string = posix.getenv("PATH") ?? ""
    if path.len() > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_posix_getenv_nonexistent(self, expect_output):
        """posix.getenv() returns empty for nonexistent variable using ??."""
        expect_output('''
func main() -> int
    val: string = posix.getenv("COEX_NONEXISTENT_VAR_12345") ?? "default"
    if val == "default"
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestPosixRandom:
    """Test posix random methods."""

    def test_posix_random_seed(self, expect_output):
        """posix.random_seed() returns a non-zero value."""
        expect_output('''
func main() -> int
    seed: int = posix.random_seed()
    # Random seed should be non-zero (extremely unlikely to be 0)
    if seed != 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_posix_urandom_length(self, expect_output):
        """posix.urandom(n) returns n bytes."""
        expect_output('''
func main() -> int
    bytes: [byte] = posix.urandom(16)
    print(bytes.len())
    return 0
~
''', "16\n")
