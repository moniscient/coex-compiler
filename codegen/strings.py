"""
String Module for Coex Code Generator

This module provides the String type implementation for the Coex compiler.
String layout with slice views:
    Field 0: i64 owner_handle - handle to data buffer (GC-allocated)
    Field 1: i64 offset      - byte offset into owner's data
    Field 2: i64 len         - number of UTF-8 codepoints
    Field 3: i64 size        - byte size of this string's extent

Strings are immutable and GC-managed. Slice views share the owner pointer
with their parent, enabling zero-copy slicing.
"""
from llvmlite import ir
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class StringGenerator:
    """Generates String type and methods for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    def create_string_type(self):
        """Create the String struct type and helper functions.

        String layout with slice views:
            Field 0: i8* owner    - pointer to data buffer (GC-allocated)
            Field 1: i64 offset   - byte offset into owner's data
            Field 2: i64 len      - number of UTF-8 codepoints (what .len() returns)
            Field 3: i64 size     - byte size of this string's extent

        A String* points to the struct. Data is stored separately.
        Total struct size = 32 bytes (4 x 8-byte fields)

        Slice views share the owner pointer with their parent, using offset
        to point into the parent's data buffer. This enables zero-copy slicing.

        Strings are immutable and GC-managed. No refcounting needed.
        """
        cg = self.cg

        # String struct - immutable, GC-managed, supports slice views
        # Phase 4: owner is now i64 handle instead of i8* pointer
        cg.string_struct = ir.global_context.get_identified_type("struct.String")
        cg.string_struct.set_body(
            ir.IntType(64),  # owner_handle (field 0) - handle to data buffer
            ir.IntType(64),  # offset (field 1) - byte offset into owner's data
            ir.IntType(64),  # len - codepoint count (field 2)
            ir.IntType(64),  # size - byte count (field 3)
        )

        string_ptr = cg.string_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        i1 = ir.IntType(1)

        # Declare POSIX write for safe printing (no stdout symbol needed)
        write_ty = ir.FunctionType(i64, [ir.IntType(32), i8_ptr, i64])
        cg.write_syscall = ir.Function(cg.module, write_ty, name="write")

        # string_new(data: i8*, byte_len: i64, char_count: i64) -> String*
        string_new_ty = ir.FunctionType(string_ptr, [i8_ptr, i64, i64])
        cg.string_new = ir.Function(cg.module, string_new_ty, name="coex_string_new")

        # string_from_literal(data: i8*) -> String* (for null-terminated C strings)
        string_from_lit_ty = ir.FunctionType(string_ptr, [i8_ptr])
        cg.string_from_literal = ir.Function(cg.module, string_from_lit_ty, name="coex_string_from_literal")

        # string_len(s: String*) -> i64
        string_len_ty = ir.FunctionType(i64, [string_ptr])
        cg.string_len = ir.Function(cg.module, string_len_ty, name="coex_string_len")

        # string_get(s: String*, index: i64) -> i64
        string_get_ty = ir.FunctionType(i64, [string_ptr, i64])
        cg.string_get = ir.Function(cg.module, string_get_ty, name="coex_string_get")

        # string_slice(s: String*, start: i64, end: i64) -> String*
        string_slice_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64])
        cg.string_slice = ir.Function(cg.module, string_slice_ty, name="coex_string_slice")

        # string_getrange is an alias for string_slice
        cg.string_getrange = cg.string_slice

        # string_setrange(s: String*, start: i64, end: i64, source: String*) -> String*
        string_setrange_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64, string_ptr])
        cg.string_setrange = ir.Function(cg.module, string_setrange_ty, name="coex_string_setrange")

        # string_concat(a: String*, b: String*) -> String*
        string_concat_ty = ir.FunctionType(string_ptr, [string_ptr, string_ptr])
        cg.string_concat = ir.Function(cg.module, string_concat_ty, name="coex_string_concat")

        # string_join_list(strings: List*, separator: String*) -> String*
        string_join_list_ty = ir.FunctionType(string_ptr, [cg.list_struct.as_pointer(), string_ptr])
        cg.string_join_list = ir.Function(cg.module, string_join_list_ty, name="coex_string_join_list")

        # string_eq(a: String*, b: String*) -> bool
        string_eq_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        cg.string_eq = ir.Function(cg.module, string_eq_ty, name="coex_string_eq")

        # string_contains(s: String*, needle: String*) -> bool
        string_contains_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        cg.string_contains = ir.Function(cg.module, string_contains_ty, name="coex_string_contains")

        # string_print(s: String*) -> void
        string_print_ty = ir.FunctionType(ir.VoidType(), [string_ptr])
        cg.string_print = ir.Function(cg.module, string_print_ty, name="coex_string_print")

        # string_debug(s: String*) -> void (prints to stderr)
        string_debug_ty = ir.FunctionType(ir.VoidType(), [string_ptr])
        cg.string_debug = ir.Function(cg.module, string_debug_ty, name="coex_string_debug")

        # string_data(s: String*) -> i8*
        string_data_ty = ir.FunctionType(i8_ptr, [string_ptr])
        cg.string_data = ir.Function(cg.module, string_data_ty, name="coex_string_data")

        # string_size(s: String*) -> i64
        string_size_ty = ir.FunctionType(i64, [string_ptr])
        cg.string_size = ir.Function(cg.module, string_size_ty, name="coex_string_size")

        # string_copy(s: String*) -> String*
        string_copy_ty = ir.FunctionType(string_ptr, [string_ptr])
        cg.string_copy = ir.Function(cg.module, string_copy_ty, name="coex_string_copy")

        # string_deep_copy(s: String*) -> String*
        string_deep_copy_ty = ir.FunctionType(string_ptr, [string_ptr])
        cg.string_deep_copy = ir.Function(cg.module, string_deep_copy_ty, name="coex_string_deep_copy")

        # string_byte_size(s: String*) -> i64
        string_byte_size_ty = ir.FunctionType(i64, [string_ptr])
        cg.string_byte_size = ir.Function(cg.module, string_byte_size_ty, name="coex_string_byte_size")

        # string_hash(s: String*) -> i64
        string_hash_ty = ir.FunctionType(i64, [string_ptr])
        cg.string_hash = ir.Function(cg.module, string_hash_ty, name="coex_string_hash")

        # string_split(s: String*, delimiter: String*) -> List<String>*
        list_ptr = cg.list_struct.as_pointer()
        string_split_ty = ir.FunctionType(list_ptr, [string_ptr, string_ptr])
        cg.string_split = ir.Function(cg.module, string_split_ty, name="coex_string_split")

        # Optional types for parsing results
        int_optional = ir.LiteralStructType([ir.IntType(1), i64])
        float_optional = ir.LiteralStructType([ir.IntType(1), ir.DoubleType()])

        # string_to_int(s: String*) -> int?
        string_to_int_ty = ir.FunctionType(int_optional, [string_ptr])
        cg.string_to_int = ir.Function(cg.module, string_to_int_ty, name="coex_string_to_int")

        # string_to_float(s: String*) -> float?
        string_to_float_ty = ir.FunctionType(float_optional, [string_ptr])
        cg.string_to_float = ir.Function(cg.module, string_to_float_ty, name="coex_string_to_float")

        # string_to_int_hex(s: String*) -> int?
        string_to_int_hex_ty = ir.FunctionType(int_optional, [string_ptr])
        cg.string_to_int_hex = ir.Function(cg.module, string_to_int_hex_ty, name="coex_string_to_int_hex")

        # string_from_int(n: i64) -> String*
        string_from_int_ty = ir.FunctionType(string_ptr, [i64])
        cg.string_from_int = ir.Function(cg.module, string_from_int_ty, name="coex_string_from_int")

        # string_from_float(f: double) -> String*
        string_from_float_ty = ir.FunctionType(string_ptr, [ir.DoubleType()])
        cg.string_from_float = ir.Function(cg.module, string_from_float_ty, name="coex_string_from_float")

        # string_from_bool(b: i1) -> String*
        string_from_bool_ty = ir.FunctionType(string_ptr, [ir.IntType(1)])
        cg.string_from_bool = ir.Function(cg.module, string_from_bool_ty, name="coex_string_from_bool")

        # string_from_hex(n: i64) -> String*
        string_from_hex_ty = ir.FunctionType(string_ptr, [i64])
        cg.string_from_hex = ir.Function(cg.module, string_from_hex_ty, name="coex_string_from_hex")

        # string_validjson(s: String*) -> bool
        string_validjson_ty = ir.FunctionType(ir.IntType(1), [string_ptr])
        cg.string_validjson = ir.Function(cg.module, string_validjson_ty, name="coex_string_validjson")

        # string_from_bytes(bytes: List*) -> String*
        list_ptr = cg.list_struct.as_pointer()
        string_from_bytes_ty = ir.FunctionType(string_ptr, [list_ptr])
        cg.string_from_bytes = ir.Function(cg.module, string_from_bytes_ty, name="coex_string_from_bytes")

        # string_to_bytes(s: String*) -> List*
        string_to_bytes_ty = ir.FunctionType(list_ptr, [string_ptr])
        cg.string_to_bytes = ir.Function(cg.module, string_to_bytes_ty, name="coex_string_to_bytes")

        # Implement all string functions
        self._implement_string_data()
        self._implement_string_new()
        self._implement_string_from_literal()
        self._implement_string_len()
        self._implement_string_size()
        self._implement_string_byte_size()
        self._implement_string_get()
        self._implement_string_slice()
        self._implement_string_concat()
        self._implement_string_join_list()
        self._implement_string_eq()
        self._implement_string_contains()
        self._implement_string_print()
        self._implement_string_debug()
        self._implement_string_copy()
        self._implement_string_deep_copy()
        self._implement_string_hash()
        self._implement_string_setrange()
        self._implement_string_to_int()
        self._implement_string_to_float()
        self._implement_string_to_int_hex()
        self._implement_string_from_int()
        self._implement_string_from_float()
        self._implement_string_from_bool()
        self._implement_string_from_hex()
        self._implement_string_from_bytes()
        self._implement_string_to_bytes()
        self._implement_string_split()
        # Note: string_validjson is implemented after JSON type is created

        # Register String type methods
        self._register_string_methods()

    def _implement_string_data(self):
        """Get pointer to actual data (owner + offset)."""
        cg = self.cg
        func = cg.string_data
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        # Load owner_handle from field 0
        owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)

        # Convert handle to pointer
        owner_ptr = builder.inttoptr(owner_handle, i8_ptr)

        # Load offset from field 1
        offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset = builder.load(offset_ptr)

        # Compute data pointer: owner + offset
        data_ptr = builder.gep(owner_ptr, [offset])

        builder.ret(data_ptr)

    def _implement_string_new(self):
        """Create String from data pointer, byte length, and char count."""
        cg = self.cg
        func = cg.string_new
        func.args[0].name = "data"
        func.args[1].name = "byte_len"
        func.args[2].name = "char_count"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        data = func.args[0]
        byte_len = func.args[1]
        char_count = func.args[2]

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate String struct (32 bytes) via GC
        struct_size = ir.Constant(i64, 32)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING)
        string_raw = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        string_ptr = builder.bitcast(string_raw, cg.string_struct.as_pointer())

        # Allocate data buffer via GC
        data_type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        data_raw = cg.gc.alloc_with_deref(builder, byte_len, data_type_id)

        # Copy data to new buffer
        builder.call(cg.memcpy, [data_raw, data, byte_len])

        # Store owner_handle (ptrtoint for Phase 4 compatibility)
        owner_handle = builder.ptrtoint(data_raw, i64)
        owner_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(owner_handle, owner_ptr)

        # Store offset = 0
        offset_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), offset_ptr)

        # Store len (char count)
        len_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(char_count, len_ptr)

        # Store size (byte count)
        size_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(byte_len, size_ptr)

        builder.ret(string_ptr)

    def _implement_string_from_literal(self):
        """Create String from null-terminated C string literal."""
        cg = self.cg
        func = cg.string_from_literal
        func.args[0].name = "cstr"

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        loop_body = func.append_basic_block("loop_body")
        inc_char = func.append_basic_block("inc_char")
        after_char_check = func.append_basic_block("after_char_check")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        cstr = func.args[0]

        # Allocate counters for byte_len and char_count
        byte_len_ptr = builder.alloca(ir.IntType(64), name="byte_len")
        char_count_ptr = builder.alloca(ir.IntType(64), name="char_count")
        builder.store(ir.Constant(ir.IntType(64), 0), byte_len_ptr)
        builder.store(ir.Constant(ir.IntType(64), 0), char_count_ptr)
        builder.branch(loop)

        builder.position_at_end(loop)
        current_byte_len = builder.load(byte_len_ptr)
        char_ptr = builder.gep(cstr, [current_byte_len])
        char_val = builder.load(char_ptr)
        is_null = builder.icmp_unsigned("==", char_val, ir.Constant(ir.IntType(8), 0))
        builder.cbranch(is_null, done, loop_body)

        builder.position_at_end(loop_body)
        # Increment byte count
        new_byte_len = builder.add(current_byte_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_byte_len, byte_len_ptr)

        # Check if this byte starts a new codepoint: (byte & 0xC0) != 0x80
        masked = builder.and_(char_val, ir.Constant(ir.IntType(8), 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(ir.IntType(8), 0x80))
        builder.cbranch(is_continuation, after_char_check, inc_char)

        builder.position_at_end(inc_char)
        current_char_count = builder.load(char_count_ptr)
        new_char_count = builder.add(current_char_count, ir.Constant(ir.IntType(64), 1))
        builder.store(new_char_count, char_count_ptr)
        builder.branch(after_char_check)

        builder.position_at_end(after_char_check)
        builder.branch(loop)

        builder.position_at_end(done)
        final_byte_len = builder.load(byte_len_ptr)
        final_char_count = builder.load(char_count_ptr)

        # Allocate 32 bytes for String struct via GC
        struct_size = ir.Constant(ir.IntType(64), 32)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_STRING)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        string_ptr = builder.bitcast(raw_ptr, cg.string_struct.as_pointer())

        # Allocate data buffer and copy literal data
        string_data_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_STRING_DATA)
        data_buf = cg.gc.alloc_with_deref(builder, final_byte_len, string_data_type_id)
        builder.call(cg.memcpy, [data_buf, cstr, final_byte_len])

        i64 = ir.IntType(64)
        i32 = ir.IntType(32)

        # Store owner_handle at field 0
        owner_handle = builder.ptrtoint(data_buf, i64)
        owner_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(owner_handle, owner_ptr)

        # Store offset = 0 at field 1
        offset_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), offset_ptr)

        # Store len (codepoint count) at field 2
        len_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(final_char_count, len_ptr)

        # Store size (byte count) at field 3
        size_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(final_byte_len, size_ptr)

        builder.ret(string_ptr)

    def _implement_string_len(self):
        """Return string length (codepoint count at field 2)."""
        cg = self.cg
        func = cg.string_len
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        length = builder.load(len_ptr)
        builder.ret(length)

    def _implement_string_size(self):
        """Return string total memory footprint in bytes."""
        cg = self.cg
        func = cg.string_size
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        byte_size = builder.load(size_ptr)
        total_size = builder.add(ir.Constant(ir.IntType(64), 32), byte_size)
        builder.ret(total_size)

    def _implement_string_byte_size(self):
        """Return string byte size (field 3)."""
        cg = self.cg
        func = cg.string_byte_size
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        byte_size = builder.load(size_ptr)
        builder.ret(byte_size)

    def _implement_string_get(self):
        """Get byte at index with bounds checking."""
        cg = self.cg
        func = cg.string_get
        func.args[0].name = "s"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        in_bounds = func.append_basic_block("in_bounds")
        out_of_bounds = func.append_basic_block("out_of_bounds")

        builder = ir.IRBuilder(entry)

        s = func.args[0]
        index = func.args[1]

        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        size = builder.load(size_ptr)

        is_negative = builder.icmp_signed("<", index, ir.Constant(ir.IntType(64), 0))
        is_too_large = builder.icmp_signed(">=", index, size)
        is_invalid = builder.or_(is_negative, is_too_large)
        builder.cbranch(is_invalid, out_of_bounds, in_bounds)

        builder.position_at_end(in_bounds)
        owner_handle_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset])

        byte_ptr = builder.gep(data_ptr, [index])
        byte_val = builder.load(byte_ptr)
        result = builder.zext(byte_val, ir.IntType(64))
        builder.ret(result)

        builder.position_at_end(out_of_bounds)
        builder.ret(ir.Constant(ir.IntType(64), 0))

    def _implement_string_slice(self):
        """Create a slice VIEW that shares the parent's data buffer."""
        cg = self.cg
        func = cg.string_slice
        func.args[0].name = "s"
        func.args[1].name = "start"
        func.args[2].name = "end"

        entry = func.append_basic_block("entry")
        count_loop = func.append_basic_block("count_loop")
        count_body = func.append_basic_block("count_body")
        inc_char = func.append_basic_block("inc_char")
        after_inc = func.append_basic_block("after_inc")
        count_done = func.append_basic_block("count_done")

        builder = ir.IRBuilder(entry)

        s = func.args[0]
        start = func.args[1]
        end = func.args[2]

        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        byte_size = builder.load(size_ptr)

        zero = ir.Constant(ir.IntType(64), 0)
        start_clamped = builder.select(builder.icmp_signed("<", start, zero), zero, start)
        start_clamped = builder.select(builder.icmp_signed(">", start_clamped, byte_size), byte_size, start_clamped)

        end_clamped = builder.select(builder.icmp_signed("<", end, zero), zero, end)
        end_clamped = builder.select(builder.icmp_signed(">", end_clamped, byte_size), byte_size, end_clamped)
        end_clamped = builder.select(builder.icmp_signed("<", end_clamped, start_clamped), start_clamped, end_clamped)

        new_byte_len = builder.sub(end_clamped, start_clamped)

        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        source_owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        source_owner_handle = builder.load(source_owner_handle_ptr)
        source_offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        source_offset = builder.load(source_offset_ptr)

        new_offset = builder.add(source_offset, start_clamped)
        source_owner = builder.inttoptr(source_owner_handle, i8_ptr)
        slice_start = builder.gep(source_owner, [new_offset])

        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        char_count_ptr = builder.alloca(ir.IntType(64), name="char_count")
        builder.store(zero, idx_ptr)
        builder.store(zero, char_count_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_loop)
        idx = builder.load(idx_ptr)
        done_counting = builder.icmp_signed(">=", idx, new_byte_len)
        builder.cbranch(done_counting, count_done, count_body)

        builder.position_at_end(count_body)
        byte_ptr = builder.gep(slice_start, [idx])
        byte_val = builder.load(byte_ptr)
        masked = builder.and_(byte_val, ir.Constant(ir.IntType(8), 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(ir.IntType(8), 0x80))
        builder.cbranch(is_continuation, after_inc, inc_char)

        builder.position_at_end(inc_char)
        curr_count = builder.load(char_count_ptr)
        new_count = builder.add(curr_count, ir.Constant(ir.IntType(64), 1))
        builder.store(new_count, char_count_ptr)
        builder.branch(after_inc)

        builder.position_at_end(after_inc)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_done)
        final_char_count = builder.load(char_count_ptr)

        struct_size = ir.Constant(ir.IntType(64), 32)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_STRING)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        string_ptr = builder.bitcast(raw_ptr, cg.string_struct.as_pointer())

        new_owner_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(source_owner_handle, new_owner_ptr)

        new_offset_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_offset, new_offset_ptr)

        new_len_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(final_char_count, new_len_ptr)

        new_size_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(new_byte_len, new_size_ptr)

        builder.ret(string_ptr)

    def _implement_string_concat(self):
        """Concatenate two strings."""
        cg = self.cg
        func = cg.string_concat
        func.args[0].name = "a"
        func.args[1].name = "b"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        a = func.args[0]
        b = func.args[1]

        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        a_size_ptr = builder.gep(a, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        a_size = builder.load(a_size_ptr)

        b_size_ptr = builder.gep(b, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        b_size = builder.load(b_size_ptr)

        a_len_ptr = builder.gep(a, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        a_len = builder.load(a_len_ptr)

        b_len_ptr = builder.gep(b, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        b_len = builder.load(b_len_ptr)

        total_size = builder.add(a_size, b_size)
        total_len = builder.add(a_len, b_len)

        struct_size = ir.Constant(i64, 32)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        string_ptr = builder.bitcast(raw_ptr, cg.string_struct.as_pointer())

        string_data_type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        dest_data = cg.gc.alloc_with_deref(builder, total_size, string_data_type_id)

        a_owner_handle_ptr = builder.gep(a, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        a_owner_handle = builder.load(a_owner_handle_ptr)
        a_owner = builder.inttoptr(a_owner_handle, i8_ptr)
        a_offset_ptr = builder.gep(a, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        a_offset = builder.load(a_offset_ptr)
        a_data = builder.gep(a_owner, [a_offset])
        builder.call(cg.memcpy, [dest_data, a_data, a_size])

        b_dest = builder.gep(dest_data, [a_size])
        b_owner_handle_ptr = builder.gep(b, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        b_owner_handle = builder.load(b_owner_handle_ptr)
        b_owner = builder.inttoptr(b_owner_handle, i8_ptr)
        b_offset_ptr = builder.gep(b, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        b_offset = builder.load(b_offset_ptr)
        b_data = builder.gep(b_owner, [b_offset])
        builder.call(cg.memcpy, [b_dest, b_data, b_size])

        owner_handle = builder.ptrtoint(dest_data, i64)
        owner_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(owner_handle, owner_ptr)

        offset_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), offset_ptr)

        len_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(total_len, len_ptr)

        size_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(total_size, size_ptr)

        builder.ret(string_ptr)

    def _implement_string_join_list(self):
        """Efficiently join a list of strings with a separator."""
        cg = self.cg
        func = cg.string_join_list
        func.args[0].name = "strings"
        func.args[1].name = "separator"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        string_ptr_ty = cg.string_struct.as_pointer()

        strings_list = func.args[0]
        separator = func.args[1]

        list_len = builder.call(cg.list_len, [strings_list])

        empty_check = func.append_basic_block("empty_check")
        calc_size = func.append_basic_block("calc_size")
        builder.branch(empty_check)

        builder.position_at_end(empty_check)
        is_empty = builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        return_empty = func.append_basic_block("return_empty")
        builder.cbranch(is_empty, return_empty, calc_size)

        builder.position_at_end(return_empty)
        null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        empty_str = builder.call(cg.string_new, [null_ptr, ir.Constant(i64, 0), ir.Constant(i64, 0)])
        builder.ret(empty_str)

        builder.position_at_end(calc_size)

        sep_size_ptr = builder.gep(separator, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        sep_size = builder.load(sep_size_ptr)
        sep_len_ptr = builder.gep(separator, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        sep_len = builder.load(sep_len_ptr)

        total_size_ptr = builder.alloca(i64, name="total_size")
        total_len_ptr = builder.alloca(i64, name="total_len")
        idx_ptr = builder.alloca(i64, name="idx")
        builder.store(ir.Constant(i64, 0), total_size_ptr)
        builder.store(ir.Constant(i64, 0), total_len_ptr)
        builder.store(ir.Constant(i64, 0), idx_ptr)

        size_loop_cond = func.append_basic_block("size_loop_cond")
        size_loop_body = func.append_basic_block("size_loop_body")
        size_loop_done = func.append_basic_block("size_loop_done")
        builder.branch(size_loop_cond)

        builder.position_at_end(size_loop_cond)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, size_loop_body, size_loop_done)

        builder.position_at_end(size_loop_body)
        elem_data_ptr = builder.call(cg.list_get, [strings_list, idx])
        elem_i64_ptr = builder.bitcast(elem_data_ptr, i64.as_pointer())
        elem_i64 = builder.load(elem_i64_ptr)
        elem_str = builder.inttoptr(elem_i64, string_ptr_ty)

        elem_size_ptr = builder.gep(elem_str, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)
        elem_len_ptr = builder.gep(elem_str, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        elem_len = builder.load(elem_len_ptr)

        curr_size = builder.load(total_size_ptr)
        curr_len = builder.load(total_len_ptr)
        new_size = builder.add(curr_size, elem_size)
        new_len = builder.add(curr_len, elem_len)
        builder.store(new_size, total_size_ptr)
        builder.store(new_len, total_len_ptr)

        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(size_loop_cond)

        builder.position_at_end(size_loop_done)
        total_size = builder.load(total_size_ptr)
        total_len = builder.load(total_len_ptr)

        n_minus_1 = builder.sub(list_len, ir.Constant(i64, 1))
        sep_total_size = builder.mul(n_minus_1, sep_size)
        sep_total_len = builder.mul(n_minus_1, sep_len)
        total_size = builder.add(total_size, sep_total_size)
        total_len = builder.add(total_len, sep_total_len)

        struct_size = ir.Constant(i64, 32)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        result_str = builder.bitcast(raw_ptr, string_ptr_ty)

        string_data_type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        dest_data = cg.gc.alloc_with_deref(builder, total_size, string_data_type_id)

        owner_ptr = builder.gep(result_str, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.ptrtoint(dest_data, i64)
        builder.store(owner_handle, owner_ptr)
        offset_ptr = builder.gep(result_str, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), offset_ptr)
        len_ptr = builder.gep(result_str, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(total_len, len_ptr)
        size_ptr = builder.gep(result_str, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(total_size, size_ptr)

        write_pos_ptr = builder.alloca(i64, name="write_pos")
        builder.store(ir.Constant(i64, 0), write_pos_ptr)
        builder.store(ir.Constant(i64, 0), idx_ptr)

        copy_loop_cond = func.append_basic_block("copy_loop_cond")
        copy_loop_body = func.append_basic_block("copy_loop_body")
        copy_loop_done = func.append_basic_block("copy_loop_done")
        builder.branch(copy_loop_cond)

        builder.position_at_end(copy_loop_cond)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, copy_loop_body, copy_loop_done)

        builder.position_at_end(copy_loop_body)
        write_pos = builder.load(write_pos_ptr)

        add_sep_block = func.append_basic_block("add_sep")
        skip_sep_block = func.append_basic_block("skip_sep")
        after_sep_block = func.append_basic_block("after_sep")

        is_first = builder.icmp_signed("==", idx, ir.Constant(i64, 0))
        builder.cbranch(is_first, skip_sep_block, add_sep_block)

        builder.position_at_end(add_sep_block)
        sep_dest = builder.gep(dest_data, [write_pos])
        sep_owner_handle_ptr = builder.gep(separator, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        sep_owner_handle = builder.load(sep_owner_handle_ptr)
        sep_owner = builder.inttoptr(sep_owner_handle, ir.IntType(8).as_pointer())
        sep_offset_ptr = builder.gep(separator, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        sep_offset = builder.load(sep_offset_ptr)
        sep_data = builder.gep(sep_owner, [sep_offset])
        builder.call(cg.memcpy, [sep_dest, sep_data, sep_size])
        new_write_pos = builder.add(write_pos, sep_size)
        builder.store(new_write_pos, write_pos_ptr)
        builder.branch(after_sep_block)

        builder.position_at_end(skip_sep_block)
        builder.branch(after_sep_block)

        builder.position_at_end(after_sep_block)
        write_pos = builder.load(write_pos_ptr)

        elem_data_ptr = builder.call(cg.list_get, [strings_list, idx])
        elem_i64_ptr = builder.bitcast(elem_data_ptr, i64.as_pointer())
        elem_i64 = builder.load(elem_i64_ptr)
        elem_str = builder.inttoptr(elem_i64, string_ptr_ty)

        elem_owner_handle_ptr = builder.gep(elem_str, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        elem_owner_handle = builder.load(elem_owner_handle_ptr)
        elem_owner = builder.inttoptr(elem_owner_handle, ir.IntType(8).as_pointer())
        elem_offset_ptr = builder.gep(elem_str, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        elem_offset = builder.load(elem_offset_ptr)
        elem_size_ptr = builder.gep(elem_str, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        elem_data = builder.gep(elem_owner, [elem_offset])
        elem_dest = builder.gep(dest_data, [write_pos])
        builder.call(cg.memcpy, [elem_dest, elem_data, elem_size])

        new_write_pos = builder.add(write_pos, elem_size)
        builder.store(new_write_pos, write_pos_ptr)

        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(copy_loop_cond)

        builder.position_at_end(copy_loop_done)
        builder.ret(result_str)

    def _implement_string_eq(self):
        """Compare two strings for equality."""
        cg = self.cg
        func = cg.string_eq
        func.args[0].name = "a"
        func.args[1].name = "b"

        entry = func.append_basic_block("entry")
        check_data = func.append_basic_block("check_data")
        compare_loop = func.append_basic_block("compare_loop")
        compare_body = func.append_basic_block("compare_body")
        not_equal = func.append_basic_block("not_equal")
        equal = func.append_basic_block("equal")

        builder = ir.IRBuilder(entry)

        a = func.args[0]
        b = func.args[1]

        a_size_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        a_size = builder.load(a_size_ptr)

        b_size_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        b_size = builder.load(b_size_ptr)

        size_eq = builder.icmp_signed("==", a_size, b_size)
        builder.cbranch(size_eq, check_data, not_equal)

        builder.position_at_end(check_data)
        a_owner_handle_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        a_owner_handle = builder.load(a_owner_handle_ptr)
        a_owner = builder.inttoptr(a_owner_handle, ir.IntType(8).as_pointer())
        a_offset_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        a_offset = builder.load(a_offset_ptr)
        a_data = builder.gep(a_owner, [a_offset])

        b_owner_handle_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        b_owner_handle = builder.load(b_owner_handle_ptr)
        b_owner = builder.inttoptr(b_owner_handle, ir.IntType(8).as_pointer())
        b_offset_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        b_offset = builder.load(b_offset_ptr)
        b_data = builder.gep(b_owner, [b_offset])

        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        builder.branch(compare_loop)

        builder.position_at_end(compare_loop)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, a_size)
        builder.cbranch(done, equal, compare_body)

        builder.position_at_end(compare_body)
        a_char_ptr = builder.gep(a_data, [idx])
        a_char = builder.load(a_char_ptr)
        b_char_ptr = builder.gep(b_data, [idx])
        b_char = builder.load(b_char_ptr)

        chars_eq = builder.icmp_unsigned("==", a_char, b_char)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.cbranch(chars_eq, compare_loop, not_equal)

        builder.position_at_end(not_equal)
        builder.ret(ir.Constant(ir.IntType(1), 0))

        builder.position_at_end(equal)
        builder.ret(ir.Constant(ir.IntType(1), 1))

    def _implement_string_contains(self):
        """Check if string contains substring."""
        cg = self.cg
        func = cg.string_contains
        func.args[0].name = "s"
        func.args[1].name = "needle"

        entry = func.append_basic_block("entry")
        outer_loop = func.append_basic_block("outer_loop")
        inner_setup = func.append_basic_block("inner_setup")
        inner_loop = func.append_basic_block("inner_loop")
        inner_check = func.append_basic_block("inner_check")
        mismatch = func.append_basic_block("mismatch")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        s = func.args[0]
        needle = func.args[1]

        s_size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        s_size = builder.load(s_size_ptr)

        needle_size_ptr = builder.gep(needle, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        needle_size = builder.load(needle_size_ptr)

        s_owner_handle_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        s_owner_handle = builder.load(s_owner_handle_ptr)
        s_owner = builder.inttoptr(s_owner_handle, ir.IntType(8).as_pointer())
        s_offset_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        s_offset = builder.load(s_offset_ptr)
        s_data = builder.gep(s_owner, [s_offset])

        needle_owner_handle_ptr = builder.gep(needle, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        needle_owner_handle = builder.load(needle_owner_handle_ptr)
        needle_owner = builder.inttoptr(needle_owner_handle, ir.IntType(8).as_pointer())
        needle_offset_ptr = builder.gep(needle, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        needle_offset = builder.load(needle_offset_ptr)
        needle_data = builder.gep(needle_owner, [needle_offset])

        empty_needle = builder.icmp_signed("==", needle_size, ir.Constant(ir.IntType(64), 0))

        i_ptr = builder.alloca(ir.IntType(64), name="i")
        j_ptr = builder.alloca(ir.IntType(64), name="j")
        builder.store(ir.Constant(ir.IntType(64), 0), i_ptr)

        builder.cbranch(empty_needle, found, outer_loop)

        builder.position_at_end(outer_loop)
        i = builder.load(i_ptr)
        remaining = builder.sub(s_size, i)
        can_fit = builder.icmp_signed(">=", remaining, needle_size)
        builder.cbranch(can_fit, inner_setup, not_found)

        builder.position_at_end(inner_setup)
        builder.store(ir.Constant(ir.IntType(64), 0), j_ptr)
        builder.branch(inner_loop)

        builder.position_at_end(inner_loop)
        j = builder.load(j_ptr)
        matched_all = builder.icmp_signed(">=", j, needle_size)
        builder.cbranch(matched_all, found, inner_check)

        builder.position_at_end(inner_check)
        i_val = builder.load(i_ptr)
        j_val = builder.load(j_ptr)
        s_idx = builder.add(i_val, j_val)

        s_char_ptr = builder.gep(s_data, [s_idx])
        s_char = builder.load(s_char_ptr)

        needle_char_ptr = builder.gep(needle_data, [j_val])
        needle_char = builder.load(needle_char_ptr)

        chars_match = builder.icmp_unsigned("==", s_char, needle_char)

        new_j = builder.add(j_val, ir.Constant(ir.IntType(64), 1))
        builder.store(new_j, j_ptr)

        builder.cbranch(chars_match, inner_loop, mismatch)

        builder.position_at_end(mismatch)
        i_val = builder.load(i_ptr)
        new_i = builder.add(i_val, ir.Constant(ir.IntType(64), 1))
        builder.store(new_i, i_ptr)
        builder.branch(outer_loop)

        builder.position_at_end(found)
        builder.ret(ir.Constant(ir.IntType(1), 1))

        builder.position_at_end(not_found)
        builder.ret(ir.Constant(ir.IntType(1), 0))

    def _implement_string_print(self):
        """Print string to stdout."""
        cg = self.cg
        func = cg.string_print
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]

        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        size = builder.load(size_ptr)

        owner_handle_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset])

        stdout_fd = ir.Constant(ir.IntType(32), 1)
        builder.call(cg.write_syscall, [stdout_fd, data_ptr, size])

        newline_ptr = builder.bitcast(cg._create_global_string("\n", "newline"), ir.IntType(8).as_pointer())
        builder.call(cg.write_syscall, [stdout_fd, newline_ptr, ir.Constant(ir.IntType(64), 1)])

        builder.ret_void()

    def _implement_string_debug(self):
        """Print string to stderr."""
        cg = self.cg
        func = cg.string_debug
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]

        size_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        size = builder.load(size_ptr)

        owner_handle_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset])

        stderr_fd = ir.Constant(ir.IntType(32), 2)
        builder.call(cg.write_syscall, [stderr_fd, data_ptr, size])

        newline_ptr = builder.bitcast(cg._create_global_string("\n", "newline_debug"), ir.IntType(8).as_pointer())
        builder.call(cg.write_syscall, [stderr_fd, newline_ptr, ir.Constant(ir.IntType(64), 1)])

        builder.ret_void()

    def _implement_string_copy(self):
        """String copy returns the same pointer - strings are immutable."""
        cg = self.cg
        func = cg.string_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        builder.ret(func.args[0])

    def _implement_string_deep_copy(self):
        """Create an independent copy of a string with its own data buffer."""
        cg = self.cg
        func = cg.string_deep_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        src_owner_handle_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        src_owner_handle = builder.load(src_owner_handle_ptr)
        src_owner = builder.inttoptr(src_owner_handle, i8_ptr)

        src_offset_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        src_len = builder.load(src_len_ptr)

        src_size_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        src_size = builder.load(src_size_ptr)

        src_data = builder.gep(src_owner, [src_offset])

        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        new_data = cg.gc.alloc_with_deref(builder, src_size, type_id)

        builder.call(cg.memcpy, [new_data, src_data, src_size])

        struct_size = ir.Constant(i64, 32)
        string_type_id = ir.Constant(i32, cg.gc.TYPE_STRING)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, string_type_id)
        string_ptr = builder.bitcast(raw_ptr, cg.string_struct.as_pointer())

        new_owner_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_owner_handle = builder.ptrtoint(new_data, i64)
        builder.store(new_owner_handle, new_owner_ptr)

        new_offset_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), new_offset_ptr)

        new_len_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(src_len, new_len_ptr)

        new_size_ptr = builder.gep(string_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(src_size, new_size_ptr)

        builder.ret(string_ptr)

    def _implement_string_hash(self):
        """Compute hash of string content using FNV-1a algorithm."""
        cg = self.cg
        func = cg.string_hash
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        null_case = func.append_basic_block("null_case")
        init_loop = func.append_basic_block("init_loop")
        loop_cond = func.append_basic_block("loop_cond")
        loop_body = func.append_basic_block("loop_body")
        loop_done = func.append_basic_block("loop_done")

        builder = ir.IRBuilder(entry)

        s = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        string_ptr_type = cg.string_struct.as_pointer()

        is_null = builder.icmp_unsigned("==", s, ir.Constant(string_ptr_type, None))
        builder.cbranch(is_null, null_case, init_loop)

        builder.position_at_end(null_case)
        builder.ret(ir.Constant(i64, 0))

        builder.position_at_end(init_loop)
        owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset])

        size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        size = builder.load(size_ptr)

        fnv_offset_basis = ir.Constant(i64, 14695981039346656037)
        fnv_prime = ir.Constant(i64, 1099511628211)

        hash_ptr = builder.alloca(i64, name="hash")
        builder.store(fnv_offset_basis, hash_ptr)

        idx_ptr = builder.alloca(i64, name="idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)

        builder.branch(loop_cond)

        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        done_cmp = builder.icmp_signed(">=", idx, size)
        builder.cbranch(done_cmp, loop_done, loop_body)

        builder.position_at_end(loop_body)
        byte_ptr = builder.gep(data_ptr, [idx])
        byte_val = builder.load(byte_ptr)
        byte_i64 = builder.zext(byte_val, i64)

        h = builder.load(hash_ptr)
        h = builder.xor(h, byte_i64)
        h = builder.mul(h, fnv_prime)
        builder.store(h, hash_ptr)

        new_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(loop_cond)

        builder.position_at_end(loop_done)
        final_hash = builder.load(hash_ptr)
        builder.ret(final_hash)

    def _implement_string_setrange(self):
        """Return new string with [start, end) replaced by source."""
        cg = self.cg
        func = cg.string_setrange
        func.args[0].name = "s"
        func.args[1].name = "start"
        func.args[2].name = "end"
        func.args[3].name = "source"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)

        s = func.args[0]
        start = func.args[1]
        end = func.args[2]
        source = func.args[3]

        source_size_ptr = builder.gep(source, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        source_size = builder.load(source_size_ptr)
        source_owner_handle_ptr = builder.gep(source, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        source_owner_handle = builder.load(source_owner_handle_ptr)
        source_owner = builder.inttoptr(source_owner_handle, i8_ptr)
        source_offset_ptr = builder.gep(source, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        source_offset = builder.load(source_offset_ptr)
        source_data = builder.gep(source_owner, [source_offset])

        orig_size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        orig_size = builder.load(orig_size_ptr)
        orig_owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        orig_owner_handle = builder.load(orig_owner_handle_ptr)
        orig_owner = builder.inttoptr(orig_owner_handle, i8_ptr)
        orig_offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        orig_offset = builder.load(orig_offset_ptr)
        orig_data = builder.gep(orig_owner, [orig_offset])

        start_neg = builder.icmp_signed("<", start, zero)
        start_over = builder.icmp_signed(">", start, orig_size)
        start_clamped = builder.select(start_neg, zero, builder.select(start_over, orig_size, start))

        end_under = builder.icmp_signed("<", end, start_clamped)
        end_over = builder.icmp_signed(">", end, orig_size)
        end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, orig_size, end))

        suffix_len = builder.sub(orig_size, end_clamped)
        new_size = builder.add(start_clamped, source_size)
        new_size = builder.add(new_size, suffix_len)

        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        new_data = cg.gc.alloc_with_deref(builder, new_size, type_id)

        builder.call(cg.memcpy, [new_data, orig_data, start_clamped])

        dest_after_prefix = builder.gep(new_data, [start_clamped])
        builder.call(cg.memcpy, [dest_after_prefix, source_data, source_size])

        dest_after_source = builder.gep(new_data, [builder.add(start_clamped, source_size)])
        source_suffix = builder.gep(orig_data, [end_clamped])
        builder.call(cg.memcpy, [dest_after_source, source_suffix, suffix_len])

        count_loop = func.append_basic_block("count_loop")
        count_body = func.append_basic_block("count_body")
        inc_char = func.append_basic_block("inc_char")
        after_inc = func.append_basic_block("after_inc")
        count_done = func.append_basic_block("count_done")

        idx_ptr = builder.alloca(i64, name="idx")
        char_count_ptr = builder.alloca(i64, name="char_count")
        builder.store(zero, idx_ptr)
        builder.store(zero, char_count_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_loop)
        idx = builder.load(idx_ptr)
        done_counting = builder.icmp_signed(">=", idx, new_size)
        builder.cbranch(done_counting, count_done, count_body)

        builder.position_at_end(count_body)
        byte_ptr = builder.gep(new_data, [idx])
        byte_val = builder.load(byte_ptr)
        masked = builder.and_(byte_val, ir.Constant(ir.IntType(8), 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(ir.IntType(8), 0x80))
        builder.cbranch(is_continuation, after_inc, inc_char)

        builder.position_at_end(inc_char)
        curr_count = builder.load(char_count_ptr)
        new_count = builder.add(curr_count, one)
        builder.store(new_count, char_count_ptr)
        builder.branch(after_inc)

        builder.position_at_end(after_inc)
        new_idx = builder.add(idx, one)
        builder.store(new_idx, idx_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_done)
        final_char_count = builder.load(char_count_ptr)

        result = builder.call(cg.string_new, [new_data, new_size, final_char_count])
        builder.ret(result)

    def _implement_string_to_int(self):
        """Parse string as integer using strtoll."""
        cg = self.cg
        func = cg.string_to_int
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        success_block = func.append_basic_block("success")
        fail_block = func.append_basic_block("fail")

        builder = ir.IRBuilder(entry)

        i1 = ir.IntType(1)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8 = ir.IntType(8)
        i8_ptr = i8.as_pointer()
        int_optional = ir.LiteralStructType([i1, i64])

        s = func.args[0]

        size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        size = builder.load(size_ptr)
        is_empty = builder.icmp_signed("==", size, ir.Constant(i64, 0))

        owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner = builder.inttoptr(owner_handle, i8_ptr)
        offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data = builder.gep(owner, [offset])

        size_plus_one = builder.add(size, ir.Constant(i64, 1))
        temp_buf = builder.call(cg.malloc, [size_plus_one])
        builder.call(cg.memcpy, [temp_buf, data, size])
        null_pos = builder.gep(temp_buf, [size])
        builder.store(ir.Constant(i8, 0), null_pos)

        endptr_alloca = builder.alloca(i8_ptr, name="endptr")

        base_10 = ir.Constant(i32, 10)
        result = builder.call(cg.strtoll, [temp_buf, endptr_alloca, base_10])

        endptr = builder.load(endptr_alloca)
        no_conversion = builder.icmp_unsigned("==", endptr, temp_buf)

        builder.call(cg.free, [temp_buf])

        failed = builder.or_(is_empty, no_conversion)
        builder.cbranch(failed, fail_block, success_block)

        builder.position_at_end(success_block)
        some_result = ir.Constant(int_optional, ir.Undefined)
        some_result = builder.insert_value(some_result, ir.Constant(i1, 1), 0)
        some_result = builder.insert_value(some_result, result, 1)
        builder.ret(some_result)

        builder.position_at_end(fail_block)
        nil_result = ir.Constant(int_optional, ir.Undefined)
        nil_result = builder.insert_value(nil_result, ir.Constant(i1, 0), 0)
        nil_result = builder.insert_value(nil_result, ir.Constant(i64, 0), 1)
        builder.ret(nil_result)

    def _implement_string_to_float(self):
        """Parse string as float using strtod."""
        cg = self.cg
        func = cg.string_to_float
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        success_block = func.append_basic_block("success")
        fail_block = func.append_basic_block("fail")

        builder = ir.IRBuilder(entry)

        i1 = ir.IntType(1)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        double = ir.DoubleType()
        float_optional = ir.LiteralStructType([i1, double])

        s = func.args[0]

        size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        size = builder.load(size_ptr)
        is_empty = builder.icmp_signed("==", size, ir.Constant(i64, 0))

        owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner = builder.inttoptr(owner_handle, i8_ptr)
        offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data = builder.gep(owner, [offset])

        endptr_alloca = builder.alloca(i8_ptr, name="endptr")

        result = builder.call(cg.strtod, [data, endptr_alloca])

        endptr = builder.load(endptr_alloca)
        no_conversion = builder.icmp_unsigned("==", endptr, data)
        failed = builder.or_(is_empty, no_conversion)
        builder.cbranch(failed, fail_block, success_block)

        builder.position_at_end(success_block)
        some_result = ir.Constant(float_optional, ir.Undefined)
        some_result = builder.insert_value(some_result, ir.Constant(i1, 1), 0)
        some_result = builder.insert_value(some_result, result, 1)
        builder.ret(some_result)

        builder.position_at_end(fail_block)
        nil_result = ir.Constant(float_optional, ir.Undefined)
        nil_result = builder.insert_value(nil_result, ir.Constant(i1, 0), 0)
        nil_result = builder.insert_value(nil_result, ir.Constant(double, 0.0), 1)
        builder.ret(nil_result)

    def _implement_string_to_int_hex(self):
        """Parse hex string as integer using strtoll with base 16."""
        cg = self.cg
        func = cg.string_to_int_hex
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        success_block = func.append_basic_block("success")
        fail_block = func.append_basic_block("fail")

        builder = ir.IRBuilder(entry)

        i1 = ir.IntType(1)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        int_optional = ir.LiteralStructType([i1, i64])

        s = func.args[0]

        size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        size = builder.load(size_ptr)
        is_empty = builder.icmp_signed("==", size, ir.Constant(i64, 0))

        owner_handle_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner = builder.inttoptr(owner_handle, i8_ptr)
        offset_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset = builder.load(offset_ptr)
        data = builder.gep(owner, [offset])

        endptr_alloca = builder.alloca(i8_ptr, name="endptr")

        base_16 = ir.Constant(i32, 16)
        result = builder.call(cg.strtoll, [data, endptr_alloca, base_16])

        endptr = builder.load(endptr_alloca)
        no_conversion = builder.icmp_unsigned("==", endptr, data)
        failed = builder.or_(is_empty, no_conversion)
        builder.cbranch(failed, fail_block, success_block)

        builder.position_at_end(success_block)
        some_result = ir.Constant(int_optional, ir.Undefined)
        some_result = builder.insert_value(some_result, ir.Constant(i1, 1), 0)
        some_result = builder.insert_value(some_result, result, 1)
        builder.ret(some_result)

        builder.position_at_end(fail_block)
        nil_result = ir.Constant(int_optional, ir.Undefined)
        nil_result = builder.insert_value(nil_result, ir.Constant(i1, 0), 0)
        nil_result = builder.insert_value(nil_result, ir.Constant(i64, 0), 1)
        builder.ret(nil_result)

    def _implement_string_from_int(self):
        """Convert integer to string using snprintf."""
        cg = self.cg
        func = cg.string_from_int
        func.args[0].name = "n"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        n = func.args[0]

        buf_size = ir.Constant(i64, 32)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        buf = cg.gc.alloc_with_deref(builder, buf_size, type_id)

        fmt_ptr = builder.bitcast(cg._int_conv_fmt, i8_ptr)
        len_result = builder.call(cg.snprintf, [buf, buf_size, fmt_ptr, n])

        str_len = builder.zext(len_result, i64)

        result = builder.call(cg.string_new, [buf, str_len, str_len])
        builder.ret(result)

    def _implement_string_from_float(self):
        """Convert float to string using snprintf."""
        cg = self.cg
        func = cg.string_from_float
        func.args[0].name = "f"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        f = func.args[0]

        buf_size = ir.Constant(i64, 64)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        buf = cg.gc.alloc_with_deref(builder, buf_size, type_id)

        fmt_ptr = builder.bitcast(cg._float_conv_fmt, i8_ptr)
        len_result = builder.call(cg.snprintf, [buf, buf_size, fmt_ptr, f])

        str_len = builder.zext(len_result, i64)

        result = builder.call(cg.string_new, [buf, str_len, str_len])
        builder.ret(result)

    def _implement_string_from_bool(self):
        """Convert bool to string."""
        cg = self.cg
        func = cg.string_from_bool
        func.args[0].name = "b"

        entry = func.append_basic_block("entry")
        true_block = func.append_basic_block("true_case")
        false_block = func.append_basic_block("false_case")
        merge_block = func.append_basic_block("merge")

        builder = ir.IRBuilder(entry)

        i8_ptr = ir.IntType(8).as_pointer()

        b = func.args[0]
        builder.cbranch(b, true_block, false_block)

        builder.position_at_end(true_block)
        true_ptr = builder.bitcast(cg._true_conv_str, i8_ptr)
        true_result = builder.call(cg.string_from_literal, [true_ptr])
        builder.branch(merge_block)

        builder.position_at_end(false_block)
        false_ptr = builder.bitcast(cg._false_conv_str, i8_ptr)
        false_result = builder.call(cg.string_from_literal, [false_ptr])
        builder.branch(merge_block)

        builder.position_at_end(merge_block)
        phi = builder.phi(cg.string_struct.as_pointer())
        phi.add_incoming(true_result, true_block)
        phi.add_incoming(false_result, false_block)
        builder.ret(phi)

    def _implement_string_from_hex(self):
        """Convert integer to hex string using snprintf."""
        cg = self.cg
        func = cg.string_from_hex
        func.args[0].name = "n"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        n = func.args[0]

        buf_size = ir.Constant(i64, 32)
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        buf = cg.gc.alloc_with_deref(builder, buf_size, type_id)

        fmt_ptr = builder.bitcast(cg._hex_conv_fmt, i8_ptr)
        len_result = builder.call(cg.snprintf, [buf, buf_size, fmt_ptr, n])

        str_len = builder.zext(len_result, i64)

        result = builder.call(cg.string_new, [buf, str_len, str_len])
        builder.ret(result)

    def _implement_string_from_bytes(self):
        """Convert byte array (List*) to String."""
        cg = self.cg
        func = cg.string_from_bytes
        func.args[0].name = "bytes"

        entry = func.append_basic_block("entry")
        check_empty = func.append_basic_block("check_empty")
        copy_loop = func.append_basic_block("copy_loop")
        count_codepoint = func.append_basic_block("count_codepoint")
        after_count = func.append_basic_block("after_count")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        bytes_list = func.args[0]

        len_ptr = builder.gep(bytes_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        byte_len = builder.load(len_ptr)

        builder.branch(check_empty)

        builder.position_at_end(check_empty)
        is_empty = builder.icmp_unsigned("==", byte_len, ir.Constant(i64, 0))
        builder.cbranch(is_empty, done, copy_loop)

        builder.position_at_end(copy_loop)

        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        data_buf = cg.gc.alloc_with_deref(builder, byte_len, type_id)

        idx_ptr = builder.alloca(i64, name="idx")
        codepoint_count_ptr = builder.alloca(i64, name="codepoint_count")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.store(ir.Constant(i64, 0), codepoint_count_ptr)

        loop_header = func.append_basic_block("loop_header")
        loop_body = func.append_basic_block("loop_body")
        loop_end = func.append_basic_block("loop_end")

        builder.branch(loop_header)

        builder.position_at_end(loop_header)
        idx = builder.load(idx_ptr)
        in_bounds = builder.icmp_unsigned("<", idx, byte_len)
        builder.cbranch(in_bounds, loop_body, loop_end)

        builder.position_at_end(loop_body)
        elem_ptr = builder.call(cg.list_get, [bytes_list, idx])
        byte_val = builder.load(builder.bitcast(elem_ptr, i8.as_pointer()))

        dest_ptr = builder.gep(data_buf, [idx])
        builder.store(byte_val, dest_ptr)

        masked = builder.and_(byte_val, ir.Constant(i8, 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(i8, 0x80))
        builder.cbranch(is_continuation, after_count, count_codepoint)

        builder.position_at_end(count_codepoint)
        current_count = builder.load(codepoint_count_ptr)
        new_count = builder.add(current_count, ir.Constant(i64, 1))
        builder.store(new_count, codepoint_count_ptr)
        builder.branch(after_count)

        builder.position_at_end(after_count)
        new_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(loop_header)

        builder.position_at_end(loop_end)
        final_codepoint_count = builder.load(codepoint_count_ptr)

        result = builder.call(cg.string_new, [data_buf, final_codepoint_count, byte_len])
        builder.ret(result)

        builder.position_at_end(done)
        empty_buf = cg.gc.alloc_with_deref(builder, ir.Constant(i64, 1), type_id)
        builder.store(ir.Constant(i8, 0), empty_buf)
        empty_str = builder.call(cg.string_new, [empty_buf, ir.Constant(i64, 0), ir.Constant(i64, 0)])
        builder.ret(empty_str)

    def _implement_string_to_bytes(self):
        """Convert String to byte array (List*)."""
        cg = self.cg
        func = cg.string_to_bytes
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        check_empty = func.append_basic_block("check_empty")
        copy_bytes = func.append_basic_block("copy_bytes")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        s = func.args[0]

        data_ptr = builder.call(cg.string_data, [s])

        size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        byte_size = builder.load(size_ptr)

        builder.branch(check_empty)

        builder.position_at_end(check_empty)
        is_empty = builder.icmp_unsigned("==", byte_size, ir.Constant(i64, 0))
        builder.cbranch(is_empty, done, copy_bytes)

        builder.position_at_end(copy_bytes)

        byte_list = builder.call(cg.list_new, [ir.Constant(i64, 1)])

        idx_ptr = builder.alloca(i64, name="idx")
        list_ptr = builder.alloca(cg.list_struct.as_pointer(), name="list")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.store(byte_list, list_ptr)

        loop_header = func.append_basic_block("loop_header")
        loop_body = func.append_basic_block("loop_body")
        loop_end = func.append_basic_block("loop_end")

        builder.branch(loop_header)

        builder.position_at_end(loop_header)
        idx = builder.load(idx_ptr)
        in_bounds = builder.icmp_unsigned("<", idx, byte_size)
        builder.cbranch(in_bounds, loop_body, loop_end)

        builder.position_at_end(loop_body)
        src_byte_ptr = builder.gep(data_ptr, [idx])

        current_list = builder.load(list_ptr)
        new_list = builder.call(cg.list_append, [current_list, src_byte_ptr, ir.Constant(i64, 1)])
        builder.store(new_list, list_ptr)

        new_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(loop_header)

        builder.position_at_end(loop_end)
        final_list = builder.load(list_ptr)
        builder.ret(final_list)

        builder.position_at_end(done)
        empty_list = builder.call(cg.list_new, [ir.Constant(i64, 1)])
        builder.ret(empty_list)

    def _implement_string_split(self):
        """Split string by delimiter, returning List of zero-copy slice views."""
        cg = self.cg
        func = cg.string_split
        func.args[0].name = "s"
        func.args[1].name = "delim"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)

        s = func.args[0]
        delim = func.args[1]

        src_data = builder.call(cg.string_data, [s])
        src_size_ptr = builder.gep(s, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        src_size = builder.load(src_size_ptr)

        delim_data = builder.call(cg.string_data, [delim])
        delim_size_ptr = builder.gep(delim, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        delim_size = builder.load(delim_size_ptr)

        result_list = builder.call(cg.list_new, [ir.Constant(i64, 8)])
        list_ptr = builder.alloca(cg.list_struct.as_pointer(), name="result")
        builder.store(result_list, list_ptr)

        idx_ptr = builder.alloca(i64, name="idx")
        start_ptr = builder.alloca(i64, name="start")
        builder.store(zero, idx_ptr)
        builder.store(zero, start_ptr)

        delim_empty = builder.icmp_unsigned("==", delim_size, zero)
        empty_delim_block = func.append_basic_block("empty_delim")
        scan_loop = func.append_basic_block("scan_loop")
        builder.cbranch(delim_empty, empty_delim_block, scan_loop)

        builder.position_at_end(empty_delim_block)
        temp_ptr = builder.alloca(cg.string_struct.as_pointer(), name="temp")
        builder.store(s, temp_ptr)
        temp_i8 = builder.bitcast(temp_ptr, i8.as_pointer())
        curr = builder.load(list_ptr)
        result = builder.call(cg.list_append, [curr, temp_i8, ir.Constant(i64, 8)])
        builder.ret(result)

        builder.position_at_end(scan_loop)
        scan_check = func.append_basic_block("scan_check")
        try_match = func.append_basic_block("try_match")
        add_final = func.append_basic_block("add_final")
        done = func.append_basic_block("done")
        builder.branch(scan_check)

        builder.position_at_end(scan_check)
        idx = builder.load(idx_ptr)
        remaining = builder.sub(src_size, idx)
        can_match = builder.icmp_unsigned(">=", remaining, delim_size)
        builder.cbranch(can_match, try_match, add_final)

        builder.position_at_end(try_match)

        match_idx_ptr = builder.alloca(i64, name="match_idx")
        builder.store(zero, match_idx_ptr)

        match_loop = func.append_basic_block("match_loop")
        match_body = func.append_basic_block("match_body")
        match_success = func.append_basic_block("match_success")
        match_fail = func.append_basic_block("match_fail")
        match_next = func.append_basic_block("match_next")

        builder.branch(match_loop)

        builder.position_at_end(match_loop)
        m_idx = builder.load(match_idx_ptr)
        all_matched = builder.icmp_unsigned(">=", m_idx, delim_size)
        builder.cbranch(all_matched, match_success, match_body)

        builder.position_at_end(match_body)
        idx = builder.load(idx_ptr)
        m_idx = builder.load(match_idx_ptr)
        src_off = builder.add(idx, m_idx)
        src_byte_ptr = builder.gep(src_data, [src_off])
        src_byte = builder.load(src_byte_ptr)
        delim_byte_ptr = builder.gep(delim_data, [m_idx])
        delim_byte = builder.load(delim_byte_ptr)
        eq = builder.icmp_unsigned("==", src_byte, delim_byte)
        builder.cbranch(eq, match_next, match_fail)

        builder.position_at_end(match_next)
        m_idx = builder.load(match_idx_ptr)
        new_m_idx = builder.add(m_idx, one)
        builder.store(new_m_idx, match_idx_ptr)
        builder.branch(match_loop)

        builder.position_at_end(match_success)
        idx = builder.load(idx_ptr)
        start = builder.load(start_ptr)

        slice_val = builder.call(cg.string_slice, [s, start, idx])
        slice_temp = builder.alloca(cg.string_struct.as_pointer(), name="slice_temp")
        builder.store(slice_val, slice_temp)
        slice_i8 = builder.bitcast(slice_temp, i8.as_pointer())
        curr = builder.load(list_ptr)
        new_list = builder.call(cg.list_append, [curr, slice_i8, ir.Constant(i64, 8)])
        builder.store(new_list, list_ptr)

        new_pos = builder.add(idx, delim_size)
        builder.store(new_pos, idx_ptr)
        builder.store(new_pos, start_ptr)
        builder.branch(scan_check)

        builder.position_at_end(match_fail)
        idx = builder.load(idx_ptr)
        new_idx = builder.add(idx, one)
        builder.store(new_idx, idx_ptr)
        builder.branch(scan_check)

        builder.position_at_end(add_final)
        start = builder.load(start_ptr)
        final_slice = builder.call(cg.string_slice, [s, start, src_size])
        final_temp = builder.alloca(cg.string_struct.as_pointer(), name="final_temp")
        builder.store(final_slice, final_temp)
        final_i8 = builder.bitcast(final_temp, i8.as_pointer())
        curr = builder.load(list_ptr)
        new_list = builder.call(cg.list_append, [curr, final_i8, ir.Constant(i64, 8)])
        builder.store(new_list, list_ptr)
        builder.branch(done)

        builder.position_at_end(done)
        final_result = builder.load(list_ptr)
        builder.ret(final_result)

    def implement_string_validjson(self):
        """Implement string_validjson - called after JSON type is created."""
        cg = self.cg
        func = cg.string_validjson
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        json_result = builder.call(cg.json_parse, [func.args[0]])

        null_ptr = ir.Constant(cg.json_struct.as_pointer(), None)
        is_valid = builder.icmp_unsigned("!=", json_result, null_ptr)

        builder.ret(is_valid)

    def _register_string_methods(self):
        """Register String as a type with methods for method call resolution."""
        cg = self.cg

        # Add String to type registry
        cg.type_registry["String"] = cg.string_struct

        # Map method names to function names
        cg.type_methods["String"] = {
            "len": "coex_string_len",
            "size": "coex_string_size",
            "get": "coex_string_get",
            "slice": "coex_string_slice",
            "concat": "coex_string_concat",
            "eq": "coex_string_eq",
            "contains": "coex_string_contains",
            "print": "coex_string_print",
            "data": "coex_string_data",
            "getrange": "coex_string_slice",
            "setrange": "coex_string_setrange",
            "int": "coex_string_to_int",
            "float": "coex_string_to_float",
            "int_hex": "coex_string_to_int_hex",
            "validjson": "coex_string_validjson",
            "bytes": "coex_string_to_bytes",
            "split": "coex_string_split",
        }

        # Store function references for direct access
        cg.functions["coex_string_len"] = cg.string_len
        cg.functions["coex_string_size"] = cg.string_size
        cg.functions["coex_string_get"] = cg.string_get
        cg.functions["coex_string_slice"] = cg.string_slice
        cg.functions["coex_string_concat"] = cg.string_concat
        cg.functions["coex_string_eq"] = cg.string_eq
        cg.functions["coex_string_contains"] = cg.string_contains
        cg.functions["coex_string_print"] = cg.string_print
        cg.functions["coex_string_data"] = cg.string_data
        cg.functions["coex_string_copy"] = cg.string_copy
        cg.functions["coex_string_setrange"] = cg.string_setrange
        cg.functions["coex_string_to_int"] = cg.string_to_int
        cg.functions["coex_string_to_float"] = cg.string_to_float
        cg.functions["coex_string_to_int_hex"] = cg.string_to_int_hex
        cg.functions["coex_string_validjson"] = cg.string_validjson
        cg.functions["coex_string_split"] = cg.string_split

        # Static methods for String.from() and String.from_hex()
        cg.functions["String_from"] = cg.string_from_int
        cg.functions["String_from_hex"] = cg.string_from_hex
        cg.functions["String_from_bytes"] = cg.string_from_bytes
        cg.functions["coex_string_from_int"] = cg.string_from_int
        cg.functions["coex_string_from_float"] = cg.string_from_float
        cg.functions["coex_string_from_bool"] = cg.string_from_bool
        cg.functions["coex_string_from_hex"] = cg.string_from_hex
        cg.functions["coex_string_from_bytes"] = cg.string_from_bytes
        cg.functions["coex_string_to_bytes"] = cg.string_to_bytes
