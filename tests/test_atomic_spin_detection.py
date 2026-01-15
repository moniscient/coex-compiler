"""
Tests for atomic spin detection in task context.
Phase 4, Step 10 of Task System implementation.

Detects potentially problematic spin-waits on atomics in task context,
which can starve the scheduler since tasks are cooperatively scheduled.
"""

import pytest


class TestAtomicSpinWarning:
    """Tests that atomic spins in task context generate warnings"""

    def test_direct_atomic_in_while_condition(self, compile_with_warnings):
        """Direct atomic.load() in while condition should warn in task"""
        source = '''
task spinner(flag: atomic_bool) -> int
    while not flag.load()
        x = 1
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) >= 1, f"Expected ATOMIC_SPIN warning, got: {warnings}"

    def test_indirect_atomic_dependency(self, compile_with_warnings):
        """Indirect atomic dependency in loop should warn"""
        source = '''
task indirect_spin(flag: atomic_bool) -> int
    done = flag.load()
    while not done
        done = flag.load()
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) >= 1, f"Expected ATOMIC_SPIN warning, got: {warnings}"


class TestAtomicSpinNoWarning:
    """Tests that certain patterns do NOT generate warnings"""

    def test_bounded_for_loop_no_warning(self, compile_with_warnings):
        """Bounded for loop with atomic check should NOT warn"""
        source = '''
task bounded_spin(flag: atomic_bool) -> int
    for i in 0..100
        if flag.load()
            break
        ~
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) == 0, f"Should not warn for bounded loop, got: {atomic_warnings}"

    def test_thread_context_no_warning(self, compile_with_warnings):
        """Thread spinning on atomic is OK (threads can block)"""
        source = '''
thread thread_spin(flag: atomic_bool) -> int
    while not flag.load()
        x = 1
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) == 0, f"Should not warn for thread context, got: {atomic_warnings}"

    def test_func_context_no_warning(self, compile_with_warnings):
        """Func spinning on atomic is OK"""
        source = '''
func spin_func(flag: atomic_bool) -> int
    while not flag.load()
        x = 1
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) == 0, f"Should not warn for func context, got: {atomic_warnings}"

    def test_atomic_in_body_only_no_warning(self, compile_with_warnings):
        """Atomic in loop body (not condition) should NOT warn"""
        source = '''
task body_atomic(counter: atomic_int, n: int) -> int
    for i in 0..n
        counter.fetch_add(1)
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) == 0, f"Should not warn for atomic in body only, got: {atomic_warnings}"

    def test_while_with_non_atomic_condition(self, compile_with_warnings):
        """While loop without atomic in condition should NOT warn"""
        source = '''
task normal_loop(n: int) -> int
    i = 0
    while i < n
        i = i + 1
    ~
    return i
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) == 0, f"Should not warn for non-atomic condition, got: {atomic_warnings}"


class TestAtomicSpinEdgeCases:
    """Edge cases for atomic spin detection"""

    def test_nested_while_with_atomic(self, compile_with_warnings):
        """Nested while with atomic should warn"""
        source = '''
task nested_spin(flag: atomic_bool) -> int
    while true
        while not flag.load()
            x = 1
        ~
        break
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) >= 1, f"Expected ATOMIC_SPIN warning for nested while, got: {warnings}"

    def test_atomic_compare_exchange_in_condition(self, compile_with_warnings):
        """compare_exchange in while condition should warn"""
        source = '''
task cas_spin(flag: atomic_int) -> int
    while flag.compare_exchange(0, 1) == 0
        x = 1
    ~
    return 0
~

func main() -> int
    return 0
~
'''
        _, warnings = compile_with_warnings(source)
        atomic_warnings = [w for w in warnings if w.get('category') == 'ATOMIC_SPIN']
        assert len(atomic_warnings) >= 1, f"Expected ATOMIC_SPIN warning for CAS spin, got: {warnings}"
