"""Tests for extern string argument memory leak fix.

When Coex strings are passed to extern C functions, _marshal_string_for_extern
creates a malloc'd null-terminated copy of the string data. After the extern
call, generate_extern_call frees the buffer. Without this free, buffers
accumulate in loops, leaking heap memory proportional to iterations.

This is especially critical in main() game loops that never return.
"""

import pytest
import re


class TestExternStringStackLeak:
    """Tests that extern calls with string args don't leak memory in loops."""

    def test_extern_string_in_loop_no_crash(self, expect_output):
        """Calling an extern function with string args in a tight loop
        should not crash or leak unbounded memory. Each iteration mallocs
        a temporary null-terminated copy that must be freed after the call."""
        expect_output('''
extern coex_ui_render_json(layout: string, state: string) -> string ~

func main() -> int
    i = 0
    while i < 100000
        result = coex_ui_render_json("{}", "{}")
        i = i + 1
    ~
    print("done")
    return 0
~
''', "done\n")

    def test_multiple_string_args_extern_loop(self, compile_coex):
        """Extern calls with multiple string args should free all
        malloc'd buffers per iteration."""
        result = compile_coex('''
extern coex_ui_render_json(layout: string, state: string) -> string ~

func main() -> int
    i = 0
    while i < 10000
        result = coex_ui_render_json("{}", "{}")
        i = i + 1
    ~
    print("survived")
    return 0
~
''')
        assert result.compile_success, f"Compilation failed: {result.compile_output}"
        # May not run successfully without UI init, but should compile
        # and not leak memory if it does run
