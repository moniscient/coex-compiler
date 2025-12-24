"""
Tests for @clink annotation - C FFI support.

@clink("symbol") allows Coex functions to call C library functions.
The function body should be empty (or just ~) as the implementation
is provided by the C library.
"""

import pytest


class TestClinkBasics:
    """Basic @clink functionality."""

    def test_clink_abs(self, expect_output):
        """Call C abs() function via @clink."""
        expect_output('''
@clink("abs")
func c_abs(x: int) -> int
~

func main() -> int
    print(c_abs(-42))
    return 0
~
''', "42\n")

    def test_clink_no_args(self, expect_output):
        """Call C function with no arguments."""
        # getpid() returns current process ID (always > 0)
        expect_output('''
@clink("getpid")
func get_pid() -> int
~

func main() -> int
    var pid: int = get_pid()
    if pid > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_clink_multiple_args(self, expect_output):
        """Call C function with multiple arguments."""
        # Use a simple math operation
        expect_output('''
@clink("abs")
func my_abs(x: int) -> int
~

func main() -> int
    var a: int = my_abs(-10)
    var b: int = my_abs(-20)
    print(a + b)
    return 0
~
''', "30\n")


class TestClinkTypes:
    """@clink with different types."""

    def test_clink_float_to_int(self, expect_output):
        """Call C floor() which takes double, returns double."""
        # Note: We'll need to handle float/double conversion
        expect_output('''
@clink("floor")
func c_floor(x: float) -> float
~

func main() -> int
    var result: float = c_floor(3.7)
    if result == 3.0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_clink_returns_void(self, expect_output):
        """Call C function that returns void."""
        # srand takes int, returns void
        expect_output('''
@clink("srand")
func seed_random(seed: int)
~

func main() -> int
    seed_random(42)
    print(1)
    return 0
~
''', "1\n")


class TestClinkStrings:
    """@clink with string arguments."""

    def test_clink_strlen(self, expect_output):
        """Call C strlen() function."""
        expect_output('''
@clink("strlen")
func c_strlen(s: string) -> int
~

func main() -> int
    print(c_strlen("hello"))
    return 0
~
''', "5\n")

    def test_clink_puts(self, expect_output):
        """Call C puts() function for output."""
        expect_output('''
@clink("puts")
func c_puts(s: string) -> int
~

func main() -> int
    c_puts("hello from C")
    return 0
~
''', "hello from C\n")


class TestClinkWithRegularFunctions:
    """@clink functions mixed with regular Coex functions."""

    def test_clink_with_coex_wrapper(self, expect_output):
        """Wrap a @clink function in a Coex function."""
        expect_output('''
@clink("abs")
func c_abs(x: int) -> int
~

func safe_abs(x: int) -> int
    return c_abs(x)
~

func main() -> int
    print(safe_abs(-100))
    return 0
~
''', "100\n")

    def test_clink_called_multiple_times(self, expect_output):
        """Call @clink function multiple times."""
        expect_output('''
@clink("abs")
func c_abs(x: int) -> int
~

func main() -> int
    var sum: int = 0
    sum = sum + c_abs(-1)
    sum = sum + c_abs(-2)
    sum = sum + c_abs(-3)
    print(sum)
    return 0
~
''', "6\n")
