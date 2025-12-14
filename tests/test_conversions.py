import pytest

class TestListArrayConversion:
    """Test List <-> Array conversions."""

    def test_list_to_array(self, expect_output):
        """List converts to Array."""
        expect_output('''
func main() -> int
    list = [1, 2, 3, 4, 5]
    arr = list.toArray()
    print(arr.len())
    print(arr.get(0))
    print(arr.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_array_to_list(self, expect_output):
        """Array converts to List."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3, 4, 5].toArray()
    list = arr.toList()
    print(list.len())
    print(list.get(0))
    print(list.get(4))
    return 0
~
''', "5\n1\n5\n")

    def test_list_to_array_independence(self, expect_output):
        """Converted Array is independent of source List."""
        expect_output('''
func main() -> int
    list = [1, 2, 3]
    arr = list.toArray()
    arr = arr.set(0, 99)
    print(list.get(0))
    print(arr.get(0))
    return 0
~
''', "1\n99\n")

    def test_array_to_list_independence(self, expect_output):
        """Converted List is independent of source Array."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3].toArray()
    list = arr.toList()
    list = list.set(0, 99)
    print(arr.get(0))
    print(list.get(0))
    return 0
~
''', "1\n99\n")

    def test_roundtrip_list_array_list(self, expect_output):
        """List -> Array -> List preserves data."""
        expect_output('''
func main() -> int
    original = [10, 20, 30, 40]
    arr = original.toArray()
    final = arr.toList()
    print(final.len())
    for x in final
        print(x)
    ~
    return 0
~
''', "4\n10\n20\n30\n40\n")

    def test_large_list_to_array(self, expect_output):
        """Large List converts correctly."""
        expect_output('''
func main() -> int
    list = [0]
    for i in 1..100
        list = list.append(i)
    ~
    arr = list.toArray()
    print(arr.len())
    print(arr.get(0))
    print(arr.get(50))
    print(arr.get(99))
    return 0
~
''', "100\n0\n50\n99\n")

class TestSetArrayConversion:
    """Test Set <-> Array conversions."""

    def test_set_to_array(self, expect_output):
        """Set converts to Array."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    arr = s.toArray()
    print(arr.len())
    return 0
~
''', "3\n")

    def test_array_to_set(self, expect_output):
        """Array converts to Set."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3, 2, 1].toArray()
    s = arr.toSet()
    print(s.len())
    print(s.has(1))
    print(s.has(2))
    print(s.has(3))
    return 0
~
''', "3\ntrue\ntrue\ntrue\n")

    def test_set_to_array_independence(self, expect_output):
        """Converted Array is independent of source Set."""
        expect_output('''
func main() -> int
    s = {1, 2, 3}
    arr = s.toArray()
    s = s.add(4)
    print(s.len())
    print(arr.len())
    return 0
~
''', "4\n3\n")

    def test_array_to_set_deduplicates(self, expect_output):
        """Array -> Set removes duplicates."""
        expect_output('''
func main() -> int
    arr = [1, 1, 2, 2, 3, 3, 3].toArray()
    s = arr.toSet()
    print(s.len())
    return 0
~
''', "3\n")

class TestSetArraySum:
    """Test that Set -> Array preserves all elements."""

    def test_set_array_sum(self, expect_output):
        """Sum of Set elements via Array."""
        expect_output('''
func main() -> int
    s = {10, 20, 30}
    arr = s.toArray()
    sum = 0
    for i in 0..arr.len()
        sum = sum + arr.get(i)
    ~
    print(sum)
    return 0
~
''', "60\n")
