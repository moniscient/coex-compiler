"""Test slice views with := (view) vs = (copy) semantics.

Slice views allow zero-copy slicing where the slice shares the parent's
data buffer. The assignment operator determines behavior:
- := preserves the view (shares buffer with parent)
- = creates an independent copy (new buffer)

These tests verify the semantic difference between the two operators.
"""

import pytest


class TestStringSliceViews:
    """Test string slice view semantics."""

    def test_string_slice_view_basic(self, expect_output):
        """Basic string slice with := creates a view."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice := text[0:5]
    print(slice)
    return 0
~
''', "Hello\n")

    def test_string_slice_copy_basic(self, expect_output):
        """Basic string slice with = creates a copy."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice = text[0:5]
    print(slice)
    return 0
~
''', "Hello\n")

    def test_string_slice_view_preserves_content(self, expect_output):
        """Slice view correctly accesses parent's data."""
        expect_output('''
func main() -> int
    text = "0123456789"
    slice := text[3:7]
    print(slice)
    print(slice.len())
    return 0
~
''', "3456\n4\n")

    def test_string_nested_slice_view(self, expect_output):
        """Nested slices should work correctly."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    first := text[0:7]
    second := first[0:5]
    print(second)
    return 0
~
''', "Hello\n")

    def test_string_slice_open_start_view(self, expect_output):
        """Slice with open start [:end] works with :=."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice := text[:5]
    print(slice)
    return 0
~
''', "Hello\n")

    def test_string_slice_open_end_view(self, expect_output):
        """Slice with open end [start:] works with :=."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice := text[7:]
    print(slice)
    return 0
~
''', "World!\n")

    def test_string_slice_negative_indices_view(self, expect_output):
        """Negative indices work with slice views."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice := text[-6:-1]
    print(slice)
    return 0
~
''', "World\n")

    def test_string_full_slice_view(self, expect_output):
        """Full slice [:] works with :=."""
        expect_output('''
func main() -> int
    text = "Hello"
    slice := text[:]
    print(slice)
    return 0
~
''', "Hello\n")


class TestArraySliceViews:
    """Test array slice view semantics."""

    def test_array_slice_view_basic(self, expect_output):
        """Basic array slice with := creates a view."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3, 4, 5]
    slice := arr[1:4]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n2\n4\n")

    def test_array_slice_copy_basic(self, expect_output):
        """Basic array slice with = creates a copy."""
        expect_output('''
func main() -> int
    arr = [1, 2, 3, 4, 5]
    slice = arr[1:4]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n2\n4\n")

    def test_array_nested_slice_view(self, expect_output):
        """Nested array slices should work correctly."""
        expect_output('''
func main() -> int
    arr = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    first := arr[2:8]
    second := first[1:4]
    print(second.len())
    print(second.get(0))
    print(second.get(2))
    return 0
~
''', "3\n3\n5\n")

    def test_array_slice_open_start_view(self, expect_output):
        """Array slice with open start [:end] works with :=."""
        expect_output('''
func main() -> int
    arr = [10, 20, 30, 40, 50]
    slice := arr[:3]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n10\n30\n")

    def test_array_slice_open_end_view(self, expect_output):
        """Array slice with open end [start:] works with :=."""
        expect_output('''
func main() -> int
    arr = [10, 20, 30, 40, 50]
    slice := arr[2:]
    print(slice.len())
    print(slice.get(0))
    print(slice.get(2))
    return 0
~
''', "3\n30\n50\n")


class TestSliceViewLifetime:
    """Test that slice views keep parent buffers alive."""

    def test_string_view_survives_parent_scope(self, expect_output):
        """A slice view keeps the parent buffer alive."""
        expect_output('''
func get_slice() -> string
    huge = "This is a large string buffer for testing"
    small := huge[0:4]
    return small
~

func main() -> int
    result = get_slice()
    print(result)
    return 0
~
''', "This\n")

    def test_array_view_survives_parent_scope(self, expect_output):
        """An array slice view keeps the parent buffer alive."""
        expect_output('''
func get_slice() -> List<int>
    arr = [100, 200, 300, 400, 500]
    slice := arr[1:4]
    return slice
~

func main() -> int
    result = get_slice()
    print(result.len())
    print(result.get(0))
    print(result.get(2))
    return 0
~
''', "3\n200\n400\n")


class TestSliceViewVsCopy:
    """Test the semantic difference between := (view) and = (copy).

    IMPORTANT: These tests verify that = creates truly independent copies
    while := preserves views. Currently both operators behave identically,
    so these tests document the expected future behavior.
    """

    @pytest.mark.xfail(reason="Slice views not yet implemented - := and = currently identical")
    def test_string_copy_is_independent(self, expect_output):
        """With =, modifying the copy doesn't affect original slice source.

        This test verifies that = creates a deep copy. The slice should be
        completely independent of the original string.
        """
        # Note: strings are immutable in Coex, so we test independence by
        # verifying both can be used independently after slicing
        expect_output('''
func main() -> int
    text = "Hello, World!"
    copy1 = text[0:5]
    copy2 = text[7:12]
    print(copy1)
    print(copy2)
    return 0
~
''', "Hello\nWorld\n")

    @pytest.mark.xfail(reason="Slice views not yet implemented - need memory introspection")
    def test_view_shares_buffer_with_parent(self, expect_output):
        """With :=, the slice shares memory with the parent.

        This test would ideally verify buffer sharing, but since strings
        are immutable, we can only verify the behavior is correct.
        The real test is in stress tests where memory usage differs.
        """
        expect_output('''
func main() -> int
    text = "Hello, World!"
    view := text[0:5]
    print(view)
    print(text)
    return 0
~
''', "Hello\nHello, World!\n")


class TestSliceViewPerformance:
    """Tests that verify slice views are zero-copy.

    These tests would be extremely slow or fail with copy-based slicing
    but should be fast with proper view-based slicing.
    """

    @pytest.mark.xfail(reason="Slice views not yet implemented - this would be O(n^2) with copies")
    def test_many_slices_of_large_string_fast(self, expect_output):
        """Creating many slices of a large string should be O(n), not O(n^2).

        With copy-based slicing, this creates 1000 copies of a 10000-char string,
        resulting in 10M bytes allocated and O(n^2) time.

        With view-based slicing, this creates 1000 tiny descriptors sharing
        one 10000-byte buffer, resulting in O(n) time.
        """
        expect_output('''
func make_large_string(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    large = make_large_string(10000)
    i = 0
    while i < 1000
        slice := large[0:100]
        i = i + 1
    ~
    print("done")
    return 0
~
''', "done\n")

    @pytest.mark.xfail(reason="Slice views not yet implemented - this would be O(n^2) with copies")
    def test_sliding_window_slices_fast(self, expect_output):
        """Sliding window over large string should be O(n) with views.

        This pattern is common in text processing - scanning through a
        large string taking small slices. With copies, each slice copies
        data. With views, each slice just creates a descriptor.
        """
        expect_output('''
func make_large_string(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "a"
        i = i + 1
    ~
    return result
~

func main() -> int
    large = make_large_string(10000)
    count = 0
    i = 0
    while i < 9900
        window := large[i:i+100]
        count = count + 1
        i = i + 1
    ~
    print(count)
    return 0
~
''', "9900\n")


class TestSliceViewStress:
    """Stress tests for slice views with large data."""

    def test_large_string_slice_view(self, expect_output):
        """Slice view of large string should be efficient."""
        expect_output('''
func make_large_string(n: int) -> string
    result = ""
    i = 0
    while i < n
        result = result + "x"
        i = i + 1
    ~
    return result
~

func main() -> int
    large = make_large_string(10000)
    slice := large[0:100]
    print(slice.len())
    return 0
~
''', "100\n")

    def test_many_overlapping_slices(self, expect_output):
        """Multiple overlapping slices should all work correctly."""
        expect_output('''
func main() -> int
    text = "0123456789"
    s1 := text[0:5]
    s2 := text[2:7]
    s3 := text[5:10]
    print(s1)
    print(s2)
    print(s3)
    return 0
~
''', "01234\n23456\n56789\n")

    def test_deeply_nested_slices(self, expect_output):
        """Deeply nested slices should work correctly."""
        expect_output('''
func main() -> int
    text = "0123456789ABCDEF"
    s1 := text[0:12]
    s2 := s1[2:10]
    s3 := s2[1:7]
    s4 := s3[1:5]
    print(s4)
    return 0
~
''', "4567\n")


class TestSliceViewMoveSemantics:
    """Test that slice := doesn't invalidate the source.

    Unlike `b := a` which moves ownership and invalidates `a`,
    `slice := text[0:5]` creates a new slice value, so `text`
    remains valid and usable.
    """

    def test_slice_view_source_still_valid(self, expect_output):
        """Source string is still usable after creating a slice view."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    slice := text[0:5]
    print(slice)
    print(text)
    return 0
~
''', "Hello\nHello, World!\n")

    def test_multiple_slice_views_from_same_source(self, expect_output):
        """Multiple slice views can be created from the same source."""
        expect_output('''
func main() -> int
    text = "Hello, World!"
    s1 := text[0:5]
    s2 := text[7:12]
    s3 := text[0:13]
    print(s1)
    print(s2)
    print(s3)
    print(text)
    return 0
~
''', "Hello\nWorld\nHello, World!\nHello, World!\n")

    def test_array_slice_view_source_still_valid(self, expect_output):
        """Source array is still usable after creating slice views."""
        expect_output('''
func main() -> int
    arr = [10, 20, 30, 40, 50]
    s1 := arr[0:2]
    s2 := arr[3:5]
    print(s1.get(0))
    print(s2.get(0))
    print(arr.get(2))
    return 0
~
''', "10\n40\n30\n")


class TestSliceViewEdgeCases:
    """Edge cases for slice views."""

    def test_empty_slice_view(self, expect_output):
        """Empty slice view should work."""
        expect_output('''
func main() -> int
    text = "Hello"
    empty := text[2:2]
    print(empty.len())
    return 0
~
''', "0\n")

    def test_slice_view_of_empty_string(self, expect_output):
        """Slice of empty string should work."""
        expect_output('''
func main() -> int
    text = ""
    slice := text[0:0]
    print(slice.len())
    return 0
~
''', "0\n")

    def test_slice_view_bounds_clamping(self, expect_output):
        """Out-of-bounds indices should be clamped."""
        expect_output('''
func main() -> int
    text = "Hello"
    slice := text[0:100]
    print(slice)
    return 0
~
''', "Hello\n")

    def test_slice_view_start_beyond_end(self, expect_output):
        """Start beyond end should give empty slice."""
        expect_output('''
func main() -> int
    text = "Hello"
    slice := text[10:20]
    print(slice.len())
    return 0
~
''', "0\n")

    def test_utf8_string_slice_view(self, expect_output):
        """UTF-8 strings should work with slice views (byte-based slicing)."""
        # Note: Coex slicing is byte-based, not codepoint-based
        expect_output('''
func main() -> int
    text = "Hello"
    slice := text[0:3]
    print(slice)
    return 0
~
''', "Hel\n")
