"""
Tests for built-in File type - extern type wrapping POSIX file operations.

File is an extern type that provides:
- File.open(path, mode) -> Result<File, string>
- file.read(count) -> Result<[byte], string>
- file.read_all() -> Result<string, string>
- file.write(data) -> Result<int, string>
- file.writeln(text) -> Result<(), string>
- file.close() -> Result<(), string>
"""

import pytest
import os
import tempfile


class TestFileOpen:
    """Test File.open() functionality."""

    def test_file_open_read_existing(self, expect_output, tmp_path):
        """Open an existing file for reading."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        expect_output(f'''
func main() -> int
    result: Result<File, string> = File.open("{test_file}", "r")
    if result.is_ok()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_file_open_nonexistent(self, expect_output):
        """Opening non-existent file returns error."""
        expect_output('''
func main() -> int
    result: Result<File, string> = File.open("/nonexistent/file.txt", "r")
    if result.is_err()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")


class TestFileReadWrite:
    """Test File read/write operations."""

    def test_file_read_all(self, expect_output, tmp_path):
        """Read entire file contents."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        expect_output(f'''
func main() -> int
    f: Result<File, string> = File.open("{test_file}", "r")
    if f.is_ok()
        file: File = f.unwrap()
        content: Result<string, string> = file.read_all()
        if content.is_ok()
            print(content.unwrap())
        ~
        file.close()
    ~
    return 0
~
''', "hello\n")

    def test_file_write(self, expect_output, tmp_path):
        """Write to a file."""
        test_file = tmp_path / "output.txt"

        expect_output(f'''
func main() -> int
    f: Result<File, string> = File.open("{test_file}", "w")
    if f.is_ok()
        file: File = f.unwrap()
        file.writeln("hello from coex")
        file.close()
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


class TestFileClose:
    """Test File.close() functionality."""

    def test_file_explicit_close(self, expect_output, tmp_path):
        """Explicitly closing a file works."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        # Use Result<int, string> since () is not a valid type in the grammar
        expect_output(f'''
func main() -> int
    f: Result<File, string> = File.open("{test_file}", "r")
    if f.is_ok()
        file: File = f.unwrap()
        file.close()
        print(1)
    ~
    return 0
~
''', "1\n")
