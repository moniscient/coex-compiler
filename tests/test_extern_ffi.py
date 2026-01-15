"""
Tests for extern function kind - C FFI support.

extern functions declare external C functions that can be called from Coex.
They have no body and use C ABI for parameter/return types.
"""

import pytest


class TestExternBasics:
    """Basic extern functionality."""

    def test_extern_abs(self, expect_output):
        """Call C abs() function via extern."""
        expect_output('''
extern abs(x: int) -> int
~

func main() -> int
    print(abs(-42))
    return 0
~
''', "42\n")

    def test_extern_no_args(self, expect_output):
        """Call C function with no arguments."""
        # getpid() returns current process ID (always > 0)
        expect_output('''
extern getpid() -> int
~

func main() -> int
    pid: int = getpid()
    if pid > 0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_extern_multiple_args(self, expect_output):
        """Call C function with multiple arguments."""
        # Use a simple math operation
        expect_output('''
extern abs(x: int) -> int
~

func main() -> int
    a: int = abs(-10)
    b: int = abs(-20)
    print(a + b)
    return 0
~
''', "30\n")


class TestExternTypes:
    """Extern with different types."""

    def test_extern_float_to_int(self, expect_output):
        """Call C floor() which takes double, returns double."""
        expect_output('''
extern floor(x: float) -> float
~

func main() -> int
    result: float = floor(3.7)
    if result == 3.0
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_extern_returns_void(self, expect_output):
        """Call C function that returns void."""
        # srand takes int, returns void
        expect_output('''
extern srand(seed: int)
~

func main() -> int
    srand(42)
    print(1)
    return 0
~
''', "1\n")


class TestExternStrings:
    """Extern with string arguments."""

    def test_extern_strlen(self, expect_output):
        """Call C strlen() function."""
        expect_output('''
extern strlen(s: string) -> int
~

func main() -> int
    print(strlen("hello"))
    return 0
~
''', "5\n")

    def test_extern_puts(self, expect_output):
        """Call C puts() function for output."""
        expect_output('''
extern puts(s: string) -> int
~

func main() -> int
    puts("hello from C")
    return 0
~
''', "hello from C\n")


class TestExternWithRegularFunctions:
    """Extern functions mixed with regular Coex functions."""

    def test_extern_with_coex_wrapper(self, expect_output):
        """Wrap an extern function in a Coex function."""
        expect_output('''
extern abs(x: int) -> int
~

func safe_abs(x: int) -> int
    return abs(x)
~

func main() -> int
    print(safe_abs(-100))
    return 0
~
''', "100\n")

    def test_extern_called_multiple_times(self, expect_output):
        """Call extern function multiple times."""
        expect_output('''
extern abs(x: int) -> int
~

func main() -> int
    sum: int = 0
    sum = sum + abs(-1)
    sum = sum + abs(-2)
    sum = sum + abs(-3)
    print(sum)
    return 0
~
''', "6\n")


class TestExternCallingHierarchy:
    """Extern functions can only be called from func."""

    def test_extern_callable_from_func(self, expect_output):
        """Extern functions can be called from func."""
        expect_output('''
extern abs(x: int) -> int
~

func wrapper() -> int
    return abs(-42)
~

func main() -> int
    print(wrapper())
    return 0
~
''', "42\n")

    def test_extern_not_callable_from_formula(self, expect_compile_error):
        """Extern functions cannot be called from formula."""
        expect_compile_error('''
extern abs(x: int) -> int
~

formula bad_formula(x: int) -> int
    return abs(x)
~

func main() -> int
    return 0
~
''', "cannot call extern")

    def test_extern_not_callable_from_task(self, expect_compile_error):
        """Extern functions cannot be called from task."""
        expect_compile_error('''
extern abs(x: int) -> int
~

task bad_task(x: int) -> int
    return abs(x)
~

func main() -> int
    return 0
~
''', "cannot call extern")
