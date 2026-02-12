"""
Tests for BUG-125: UDT method self pointer not GC-tracked.

These tests verify that UDT instances remain valid after GC compaction,
specifically testing the `self` pointer in methods and field access
across allocations that can trigger GC.

The core bug: `self` in method bodies was stored as a raw pointer
in an alloca without GC shadow stack tracking. After compaction moves
the UDT object and deferred TLAB munmap frees old memory, accessing
self.field dereferences a stale pointer.
"""

import pytest


class TestUdtMethodSelfBasic:
    """Basic tests: self access in methods that allocate."""

    def test_method_reads_field_after_string_creation(self, expect_output):
        """Method creates a string then reads self.field — triggers alloc."""
        expect_output('''
type Counter:
    value: int

    func get_plus(n: int) -> int
        s = "hello"
        return self.value + n
    ~
~

func main() -> int
    c = Counter(10)
    print(c.get_plus(5))
    return 0
~
''', "15\n")

    def test_method_reads_field_after_list_creation(self, expect_output):
        """Method creates a list then reads self.field — triggers alloc."""
        expect_output('''
type Data:
    count: int

    func compute() -> int
        tmp = [1, 2, 3]
        return self.count + tmp.len()
    ~
~

func main() -> int
    d = Data(7)
    print(d.compute())
    return 0
~
''', "10\n")

    def test_method_reads_field_after_udt_creation(self, expect_output):
        """Method creates another UDT then reads self.field."""
        expect_output('''
type Inner:
    x: int
~

type Outer:
    y: int

    func make_inner_and_sum() -> int
        i = Inner(100)
        return self.y + i.x
    ~
~

func main() -> int
    o = Outer(42)
    print(o.make_inner_and_sum())
    return 0
~
''', "142\n")


class TestUdtMethodSelfRefFields:
    """Tests: self with reference-type fields accessed after allocation."""

    def test_method_reads_string_field_after_alloc(self, expect_output):
        """Self has a string field; method allocates then reads it."""
        expect_output('''
type Named:
    name: string
    id: int

    func describe() -> string
        tmp = [1, 2, 3, 4, 5]
        return self.name
    ~
~

func main() -> int
    n = Named("alice", 1)
    s = n.describe()
    print(s)
    return 0
~
''', "alice\n")

    def test_method_reads_list_field_after_alloc(self, expect_output):
        """Self has a list field; method allocates then reads it."""
        expect_output('''
type Container:
    items: [int]
    label: int

    func first_item() -> int
        other = [99, 98, 97]
        return self.items.get(0)
    ~
~

func main() -> int
    c = Container([10, 20, 30], 1)
    print(c.first_item())
    return 0
~
''', "10\n")


class TestUdtMethodSelfWithGcCompact:
    """Tests: explicit gc_compact() between self accesses."""

    def test_self_field_survives_gc_compact(self, expect_output):
        """Read self.field, compact, read again."""
        expect_output('''
type Point:
    x: int
    y: int

    func sum_with_gc() -> int
        a = self.x
        gc()
        b = self.y
        return a + b
    ~
~

func main() -> int
    p = Point(3, 7)
    print(p.sum_with_gc())
    return 0
~
''', "10\n")

    def test_self_string_field_survives_gc_compact(self, expect_output):
        """Read self.name (string field), compact, read again."""
        expect_output('''
type Person:
    name: string
    age: int

    func info() -> string
        gc()
        return self.name
    ~
~

func main() -> int
    p = Person("bob", 30)
    s = p.info()
    print(s)
    return 0
~
''', "bob\n")


class TestUdtImplicitFieldAccess:
    """Tests: implicit field access (bare field name, not self.field)."""

    def test_implicit_field_after_alloc(self, expect_output):
        """Access field by bare name in method, after allocating."""
        expect_output('''
type Accum:
    total: int

    func add_and_get(n: int) -> int
        tmp = [1, 2, 3]
        return total + n
    ~
~

func main() -> int
    a = Accum(100)
    print(a.add_and_get(23))
    return 0
~
''', "123\n")

    def test_explicit_self_field_after_alloc(self, expect_output):
        """Access field with explicit self.field in method, after allocating."""
        expect_output('''
type Accum:
    total: int

    func add_and_get(n: int) -> int
        tmp = [1, 2, 3]
        return self.total + n
    ~
~

func main() -> int
    a = Accum(100)
    print(a.add_and_get(23))
    return 0
~
''', "123\n")


class TestUdtMethodParams:
    """Tests: method parameters that are heap types."""

    def test_method_with_string_param(self, expect_output):
        """Method takes string param, allocates, then uses both self and param."""
        expect_output('''
type Greeter:
    prefix: string

    func greet(name: string) -> string
        tmp = [1, 2, 3]
        return self.prefix
    ~
~

func main() -> int
    g = Greeter("Hello")
    s = g.greet("world")
    print(s)
    return 0
~
''', "Hello\n")

    def test_method_with_list_param(self, expect_output):
        """Method takes list param, allocates, then reads self.field."""
        expect_output('''
type Processor:
    factor: int

    func process(data: [int]) -> int
        other = [99]
        return self.factor * data.get(0)
    ~
~

func main() -> int
    p = Processor(3)
    print(p.process([7, 8, 9]))
    return 0
~
''', "21\n")


class TestUdtGenericMethodSelf:
    """Tests: monomorphized generic type methods with self."""

    def test_generic_type_method_self_after_alloc(self, expect_output):
        """Generic type method allocates then reads self.field."""
        expect_output('''
type Box<T>:
    value: T

    func get_value() -> T
        tmp = [1, 2, 3]
        return self.value
    ~
~

func main() -> int
    b: Box<int> = Box<int>(42)
    print(b.get_value())
    return 0
~
''', "42\n")

    def test_generic_type_method_string_field(self, expect_output):
        """Generic type with string field, method allocates then reads self."""
        expect_output('''
type Wrapper<T>:
    inner: T
    tag: int

    func get_tag() -> int
        other = "temporary"
        return self.tag
    ~
~

func main() -> int
    w: Wrapper<string> = Wrapper<string>("test", 99)
    print(w.get_tag())
    return 0
~
''', "99\n")


class TestUdtMethodChaining:
    """Tests: multiple method calls that each allocate."""

    def test_multiple_method_calls_with_allocs(self, expect_output):
        """Call method multiple times, each triggering allocation."""
        expect_output('''
type Counter:
    val: int

    func plus(n: int) -> int
        tmp = "alloc"
        return self.val + n
    ~
~

func main() -> int
    c = Counter(0)
    total = 0
    i = 0
    while i < 100
        total = total + c.plus(i)
        i = i + 1
    ~
    print(total)
    return 0
~
''', "4950\n")


class TestUdtSelfStress:
    """Stress tests: high allocation pressure in methods to trigger GC compaction."""

    def test_method_field_access_under_gc_pressure(self, expect_output):
        """Access self.field in a loop that triggers many GC cycles."""
        expect_output('''
type Holder:
    base: int

    func accumulate(n: int) -> int
        result = self.base
        i = 0
        while i < n
            tmp = [i, i+1, i+2, i+3, i+4]
            result = result + 1
            i = i + 1
        ~
        return result
    ~
~

func main() -> int
    h = Holder(1000)
    print(h.accumulate(50000))
    return 0
~
''', "51000\n")

    def test_method_string_field_under_gc_pressure(self, expect_output):
        """Access self.name (string) after heavy allocation inside method."""
        expect_output('''
type Named:
    name: string

    func churn_and_get(n: int) -> string
        i = 0
        while i < n
            tmp = [i, i+1, i+2]
            s = "garbage"
            i = i + 1
        ~
        return self.name
    ~
~

func main() -> int
    n = Named("survivor")
    s = n.churn_and_get(50000)
    print(s)
    return 0
~
''', "survivor\n")

    def test_method_multiple_ref_fields_under_pressure(self, expect_output):
        """UDT with multiple reference fields, accessed after GC pressure."""
        expect_output('''
type Record:
    label: string
    data: [int]
    count: int

    func verify() -> int
        i = 0
        while i < 50000
            tmp = [i, i+1]
            i = i + 1
        ~
        result = self.data.get(0) + self.data.get(1) + self.count
        return result
    ~
~

func main() -> int
    r = Record("test", [10, 20, 30], 5)
    print(r.verify())
    return 0
~
''', "35\n")

    def test_helper_method_creates_udt_in_loop(self, expect_output):
        """Create UDT in loop, call method on each — stresses constructor + self."""
        expect_output('''
type Pair:
    a: int
    b: int

    func sum() -> int
        tmp = "alloc"
        return self.a + self.b
    ~
~

func main() -> int
    total = 0
    i = 0
    while i < 100000
        p = Pair(i, i + 1)
        total = total + p.sum()
        i = i + 1
    ~
    print(total)
    return 0
~
''', "10000000000\n")

    def test_nested_udt_method_calls_under_pressure(self, expect_output):
        """Method calls another method that allocates, stressing self across calls."""
        expect_output('''
type Widget:
    id: int

    func compute(n: int) -> int
        result = 0
        i = 0
        while i < n
            tmp = [1, 2, 3]
            result = result + self.id
            i = i + 1
        ~
        return result
    ~
~

func main() -> int
    w = Widget(3)
    print(w.compute(50000))
    return 0
~
''', "150000\n")
