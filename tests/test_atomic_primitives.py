"""
Tests for atomic primitive types (atomic_int, atomic_float, atomic_bool).

These tests verify that:
1. Atomic types can be declared with initial values
2. load() returns the current value
3. store() updates the value atomically
4. exchange() swaps and returns the old value
5. compare_and_swap() performs conditional update
6. fetch_add/fetch_sub/increment/decrement work for atomic_int
7. test_and_set() works for atomic_bool
"""

import pytest


class TestAtomicInt:
    """Test atomic_int operations."""

    def test_atomic_int_load(self, expect_output):
        """Test basic atomic_int load."""
        expect_output('''
func main() -> int
    x: atomic_int = 42
    val = x.load()
    print(val)
    return 0
~
''', "42\n")

    def test_atomic_int_store(self, expect_output):
        """Test atomic_int store."""
        expect_output('''
func main() -> int
    x: atomic_int = 0
    x.store(99)
    print(x.load())
    return 0
~
''', "99\n")

    def test_atomic_int_exchange(self, expect_output):
        """Test atomic_int exchange returns old value."""
        expect_output('''
func main() -> int
    x: atomic_int = 10
    old = x.exchange(20)
    print(old)
    print(x.load())
    return 0
~
''', "10\n20\n")

    def test_atomic_int_compare_and_swap_success(self, expect_output):
        """Test atomic_int CAS when expected matches."""
        expect_output('''
func main() -> int
    x: atomic_int = 5
    success = x.compare_and_swap(5, 10)
    if success
        print(1)
    else
        print(0)
    ~
    print(x.load())
    return 0
~
''', "1\n10\n")

    def test_atomic_int_compare_and_swap_fail(self, expect_output):
        """Test atomic_int CAS when expected doesn't match."""
        expect_output('''
func main() -> int
    x: atomic_int = 5
    success = x.compare_and_swap(99, 10)
    if success
        print(1)
    else
        print(0)
    ~
    print(x.load())
    return 0
~
''', "0\n5\n")

    def test_atomic_int_cas_alias(self, expect_output):
        """Test atomic_int cas (alias for compare_and_swap)."""
        expect_output('''
func main() -> int
    x: atomic_int = 100
    success = x.cas(100, 200)
    if success
        print(1)
    else
        print(0)
    ~
    print(x.load())
    return 0
~
''', "1\n200\n")

    def test_atomic_int_fetch_add(self, expect_output):
        """Test atomic_int fetch_add returns old value and adds."""
        expect_output('''
func main() -> int
    x: atomic_int = 10
    old = x.fetch_add(5)
    print(old)
    print(x.load())
    return 0
~
''', "10\n15\n")

    def test_atomic_int_fetch_sub(self, expect_output):
        """Test atomic_int fetch_sub returns old value and subtracts."""
        expect_output('''
func main() -> int
    x: atomic_int = 10
    old = x.fetch_sub(3)
    print(old)
    print(x.load())
    return 0
~
''', "10\n7\n")

    def test_atomic_int_increment(self, expect_output):
        """Test atomic_int increment (fetch_add 1)."""
        expect_output('''
func main() -> int
    x: atomic_int = 5
    old = x.increment()
    print(old)
    print(x.load())
    return 0
~
''', "5\n6\n")

    def test_atomic_int_decrement(self, expect_output):
        """Test atomic_int decrement (fetch_sub 1)."""
        expect_output('''
func main() -> int
    x: atomic_int = 5
    old = x.decrement()
    print(old)
    print(x.load())
    return 0
~
''', "5\n4\n")

    def test_atomic_int_multiple_operations(self, expect_output):
        """Test sequence of atomic_int operations."""
        expect_output('''
func main() -> int
    counter: atomic_int = 0
    counter.increment()
    counter.increment()
    counter.fetch_add(10)
    counter.decrement()
    print(counter.load())
    return 0
~
''', "11\n")


class TestAtomicFloat:
    """Test atomic_float operations."""

    def test_atomic_float_load(self, expect_output):
        """Test basic atomic_float load."""
        expect_output('''
func main() -> int
    x: atomic_float = 3.14
    val = x.load()
    print(val)
    return 0
~
''', "3.140000\n")

    def test_atomic_float_store(self, expect_output):
        """Test atomic_float store."""
        expect_output('''
func main() -> int
    x: atomic_float = 0.0
    x.store(2.718)
    print(x.load())
    return 0
~
''', "2.718000\n")

    def test_atomic_float_exchange(self, expect_output):
        """Test atomic_float exchange."""
        expect_output('''
func main() -> int
    x: atomic_float = 1.5
    old = x.exchange(2.5)
    print(old)
    print(x.load())
    return 0
~
''', "1.500000\n2.500000\n")

    def test_atomic_float_compare_and_swap(self, expect_output):
        """Test atomic_float CAS."""
        expect_output('''
func main() -> int
    x: atomic_float = 1.0
    success = x.compare_and_swap(1.0, 2.0)
    if success
        print(1)
    else
        print(0)
    ~
    print(x.load())
    return 0
~
''', "1\n2.000000\n")


class TestAtomicBool:
    """Test atomic_bool operations."""

    def test_atomic_bool_load(self, expect_output):
        """Test basic atomic_bool load."""
        expect_output('''
func main() -> int
    flag: atomic_bool = true
    if flag.load()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_atomic_bool_store(self, expect_output):
        """Test atomic_bool store."""
        expect_output('''
func main() -> int
    flag: atomic_bool = false
    flag.store(true)
    if flag.load()
        print(1)
    else
        print(0)
    ~
    return 0
~
''', "1\n")

    def test_atomic_bool_exchange(self, expect_output):
        """Test atomic_bool exchange."""
        expect_output('''
func main() -> int
    flag: atomic_bool = false
    old = flag.exchange(true)
    if old
        print(1)
    else
        print(0)
    ~
    if flag.load()
        print(2)
    else
        print(3)
    ~
    return 0
~
''', "0\n2\n")

    def test_atomic_bool_test_and_set(self, expect_output):
        """Test atomic_bool test_and_set."""
        expect_output('''
func main() -> int
    lock: atomic_bool = false
    was_set = lock.test_and_set()
    if was_set
        print(1)
    else
        print(0)
    ~
    if lock.load()
        print(2)
    else
        print(3)
    ~
    return 0
~
''', "0\n2\n")

    def test_atomic_bool_compare_and_swap(self, expect_output):
        """Test atomic_bool CAS."""
        expect_output('''
func main() -> int
    flag: atomic_bool = false
    success = flag.compare_and_swap(false, true)
    if success
        print(1)
    else
        print(0)
    ~
    if flag.load()
        print(2)
    else
        print(3)
    ~
    return 0
~
''', "1\n2\n")


class TestAtomicPatterns:
    """Test common atomic usage patterns."""

    def test_spinlock_pattern(self, expect_output):
        """Test basic spinlock acquisition pattern."""
        expect_output('''
func main() -> int
    lock: atomic_bool = false
    # Try to acquire lock
    acquired = lock.compare_and_swap(false, true)
    if acquired
        print(1)
        # Release lock
        lock.store(false)
    ~
    print(lock.load())
    return 0
~
''', "1\nfalse\n")

    def test_counter_pattern(self, expect_output):
        """Test atomic counter pattern."""
        expect_output('''
func main() -> int
    counter: atomic_int = 0
    i = 0
    while i < 5
        counter.increment()
        i = i + 1
    ~
    print(counter.load())
    return 0
~
''', "5\n")

    def test_cas_loop_pattern(self, expect_output):
        """Test CAS retry loop pattern."""
        expect_output('''
func main() -> int
    x: atomic_int = 10
    done = false
    while not done
        current = x.load()
        new_val = current + 5
        done = x.compare_and_swap(current, new_val)
    ~
    print(x.load())
    return 0
~
''', "15\n")
