"""
Tests for extern types - scope-restricted resource handles.

Extern types:
- Must have a .close() method
- Cannot escape their defining scope (no return, no store in struct, no channel send)
- Cannot be passed to formula functions
- Auto-close at scope exit (future enhancement)
"""

import pytest


class TestExternBasics:
    """Basic extern type functionality."""

    def test_extern_type_declaration(self, expect_output):
        """Declare an extern type with close method."""
        expect_output('''
extern type Handle:
    fd: int

    func close()
        print(99)
    ~
~

func main() -> int
    var h: Handle = Handle(fd: 42)
    h.close()
    return 0
~
''', "99\n")

    def test_extern_type_with_result(self, expect_output):
        """Extern type method returning Result."""
        expect_output('''
extern type Resource:
    value: int

    func close()
        print(1)
    ~

    func get_value() -> int
        return self.value
    ~
~

func main() -> int
    var r: Resource = Resource(value: 42)
    print(r.get_value())
    r.close()
    return 0
~
''', "42\n1\n")


class TestExternMustHaveClose:
    """Extern types must define a .close() method."""

    def test_extern_without_close_fails(self, expect_compile_error):
        """Extern type without close() should fail compilation."""
        expect_compile_error('''
extern type BadHandle:
    fd: int
~

func main() -> int
    return 0
~
''', "must have a close() method")


class TestExternEscapeAnalysis:
    """Extern types cannot escape their defining scope."""

    @pytest.mark.xfail(reason="Escape analysis not yet implemented")
    def test_extern_cannot_return(self, expect_compile_error):
        """Extern type cannot be returned from a function."""
        expect_compile_error('''
extern type Handle:
    fd: int

    func close()
    ~
~

func make_handle() -> Handle
    return Handle(fd: 1)
~

func main() -> int
    var h: Handle = make_handle()
    h.close()
    return 0
~
''', "cannot escape")

    @pytest.mark.xfail(reason="Escape analysis not yet implemented")
    def test_extern_cannot_store_in_type(self, expect_compile_error):
        """Extern type cannot be stored in another type's field."""
        expect_compile_error('''
extern type Handle:
    fd: int

    func close()
    ~
~

type Container:
    h: Handle
~

func main() -> int
    return 0
~
''', "cannot be stored")

    @pytest.mark.xfail(reason="Escape analysis not yet implemented")
    def test_extern_cannot_put_in_list(self, expect_compile_error):
        """Extern type cannot be stored in a List."""
        expect_compile_error('''
extern type Handle:
    fd: int

    func close()
    ~
~

func main() -> int
    var handles: List<Handle> = []
    return 0
~
''', "cannot be stored")


class TestExternFormulaRestriction:
    """Extern types cannot be passed to formula functions."""

    @pytest.mark.xfail(reason="Formula restriction not yet implemented")
    def test_extern_param_in_formula_fails(self, expect_compile_error):
        """Extern type as formula parameter should fail compilation."""
        expect_compile_error('''
extern type Handle:
    fd: int

    func close()
    ~
~

formula process_handle(h: Handle) -> int
    return 42
~

func main() -> int
    return 0
~
''', "extern type in formula")


class TestExternUsage:
    """Valid usage patterns for extern types."""

    def test_extern_passed_to_func(self, expect_output):
        """Extern type can be passed to func functions."""
        expect_output('''
extern type Handle:
    fd: int

    func close()
        print(self.fd)
    ~
~

func use_handle(h: Handle) -> int
    return h.fd * 2
~

func main() -> int
    var h: Handle = Handle(fd: 21)
    print(use_handle(h))
    h.close()
    return 0
~
''', "42\n21\n")

    def test_extern_passed_to_task(self, expect_output):
        """Extern type can be passed to task functions."""
        expect_output('''
extern type Handle:
    fd: int

    func close()
        print(1)
    ~
~

task process(h: Handle)
    print(h.fd)
~

func main() -> int
    var h: Handle = Handle(fd: 99)
    process(h)
    h.close()
    return 0
~
''', "99\n1\n")
