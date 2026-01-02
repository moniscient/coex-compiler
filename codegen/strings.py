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

Methods implemented:
- String creation: new, from_literal
- Accessors: len, size, byte_size, get, data
- Operations: slice, concat, join_list, eq, contains, hash
- Conversions: to_int, to_float, to_int_hex, from_int, from_float, from_bool, from_hex
- Byte conversions: from_bytes, to_bytes
- Utilities: print, debug, copy, deep_copy, setrange, split, validjson
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator


class StringGenerator:
    """Generates String type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def module(self):
        return self.codegen.module

    @property
    def gc(self):
        return self.codegen.gc

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_methods(self):
        return self.codegen.type_methods

    @property
    def functions(self):
        return self.codegen.functions

    @property
    def list_struct(self):
        return self.codegen.list_struct

    @property
    def memcpy(self):
        return self.codegen.memcpy

    @property
    def strlen(self):
        return self.codegen.strlen

    @property
    def sscanf(self):
        return self.codegen.sscanf

    @property
    def snprintf(self):
        return self.codegen.snprintf

    @property
    def strtol(self):
        return self.codegen.strtol

    @property
    def strtod(self):
        return self.codegen.strtod

    @property
    def strtoll(self):
        return self.codegen.strtoll

    # String struct and function references - these are set during create_string_type
    @property
    def string_struct(self):
        return self.codegen.string_struct

    @property
    def string_new(self):
        return self.codegen.string_new

    @property
    def string_from_literal(self):
        return self.codegen.string_from_literal

    @property
    def string_len(self):
        return self.codegen.string_len

    @property
    def string_size(self):
        return self.codegen.string_size

    @property
    def string_byte_size(self):
        return self.codegen.string_byte_size

    @property
    def string_data(self):
        return self.codegen.string_data

    @property
    def string_get(self):
        return self.codegen.string_get

    @property
    def string_slice(self):
        return self.codegen.string_slice

    @property
    def string_concat(self):
        return self.codegen.string_concat

    @property
    def string_join_list(self):
        return self.codegen.string_join_list

    @property
    def string_eq(self):
        return self.codegen.string_eq

    @property
    def string_contains(self):
        return self.codegen.string_contains

    @property
    def string_print(self):
        return self.codegen.string_print

    @property
    def string_debug(self):
        return self.codegen.string_debug

    @property
    def string_copy(self):
        return self.codegen.string_copy

    @property
    def string_deep_copy(self):
        return self.codegen.string_deep_copy

    @property
    def string_hash(self):
        return self.codegen.string_hash

    @property
    def string_setrange(self):
        return self.codegen.string_setrange

    @property
    def string_to_int(self):
        return self.codegen.string_to_int

    @property
    def string_to_float(self):
        return self.codegen.string_to_float

    @property
    def string_to_int_hex(self):
        return self.codegen.string_to_int_hex

    @property
    def string_from_int(self):
        return self.codegen.string_from_int

    @property
    def string_from_float(self):
        return self.codegen.string_from_float

    @property
    def string_from_bool(self):
        return self.codegen.string_from_bool

    @property
    def string_from_hex(self):
        return self.codegen.string_from_hex

    @property
    def string_from_bytes(self):
        return self.codegen.string_from_bytes

    @property
    def string_to_bytes(self):
        return self.codegen.string_to_bytes

    @property
    def string_split(self):
        return self.codegen.string_split

    @property
    def string_validjson(self):
        return self.codegen.string_validjson

    @property
    def write_syscall(self):
        return self.codegen.write_syscall

    @property
    def list_new(self):
        return self.codegen.list_new

    @property
    def list_append(self):
        return self.codegen.list_append

    # JSON references for validjson
    @property
    def json_parse(self):
        return self.codegen.json_parse

    @property
    def json_struct(self):
        return self.codegen.json_struct

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
        # String struct - immutable, GC-managed, supports slice views
        # Phase 4: owner is now i64 handle instead of i8* pointer
        self.codegen.string_struct = ir.global_context.get_identified_type("struct.String")
        self.codegen.string_struct.set_body(
            ir.IntType(64),  # owner_handle (field 0) - handle to data buffer
            ir.IntType(64),  # offset (field 1) - byte offset into owner's data
            ir.IntType(64),  # len - codepoint count (field 2)
            ir.IntType(64),  # size - byte count (field 3)
        )

        string_ptr = self.string_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        i1 = ir.IntType(1)

        # Optional types for parsing results (used by string_to_int, string_to_float)
        int_optional = ir.LiteralStructType([i1, i64])
        float_optional = ir.LiteralStructType([i1, ir.DoubleType()])

        # Declare POSIX write for safe printing (no stdout symbol needed)
        # ssize_t write(int fd, const void *buf, size_t count)
        # fd=1 is stdout
        write_ty = ir.FunctionType(i64, [ir.IntType(32), i8_ptr, i64])
        self.codegen.write_syscall = ir.Function(self.module, write_ty, name="write")

        # string_new(data: i8*, byte_len: i64, char_count: i64) -> String*
        string_new_ty = ir.FunctionType(string_ptr, [i8_ptr, i64, i64])
        self.codegen.string_new = ir.Function(self.module, string_new_ty, name="coex_string_new")

        # string_from_literal(data: i8*) -> String* (for null-terminated C strings from source)
        string_from_lit_ty = ir.FunctionType(string_ptr, [i8_ptr])
        self.codegen.string_from_literal = ir.Function(self.module, string_from_lit_ty, name="coex_string_from_literal")

        # string_len(s: String*) -> i64
        string_len_ty = ir.FunctionType(i64, [string_ptr])
        self.codegen.string_len = ir.Function(self.module, string_len_ty, name="coex_string_len")

        # string_size(s: String*) -> i64 (returns byte count, for memory usage)
        string_size_ty = ir.FunctionType(i64, [string_ptr])
        self.codegen.string_size = ir.Function(self.module, string_size_ty, name="coex_string_size")

        # string_byte_size(s: String*) -> i64 (returns actual byte content size, excludes metadata)
        string_byte_size_ty = ir.FunctionType(i64, [string_ptr])
        self.codegen.string_byte_size = ir.Function(self.module, string_byte_size_ty, name="coex_string_byte_size")

        # string_data(s: String*) -> i8* (get raw pointer to data)
        string_data_ty = ir.FunctionType(i8_ptr, [string_ptr])
        self.codegen.string_data = ir.Function(self.module, string_data_ty, name="coex_string_data")

        # string_get(s: String*, idx: i64) -> i64 (get codepoint at index)
        string_get_ty = ir.FunctionType(i64, [string_ptr, i64])
        self.codegen.string_get = ir.Function(self.module, string_get_ty, name="coex_string_get")

        # string_slice(s: String*, start: i64, end: i64) -> String*
        string_slice_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64])
        self.codegen.string_slice = ir.Function(self.module, string_slice_ty, name="coex_string_slice")

        # string_concat(a: String*, b: String*) -> String*
        string_concat_ty = ir.FunctionType(string_ptr, [string_ptr, string_ptr])
        self.codegen.string_concat = ir.Function(self.module, string_concat_ty, name="coex_string_concat")

        # string_join_list(strings: List*, separator: String*) -> String*
        # Efficiently join a list of strings with a separator
        list_ptr = self.list_struct.as_pointer()
        string_join_list_ty = ir.FunctionType(string_ptr, [list_ptr, string_ptr])
        self.codegen.string_join_list = ir.Function(self.module, string_join_list_ty, name="coex_string_join_list")

        # string_eq(a: String*, b: String*) -> i1
        string_eq_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        self.codegen.string_eq = ir.Function(self.module, string_eq_ty, name="coex_string_eq")

        # string_contains(haystack: String*, needle: String*) -> i1
        string_contains_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        self.codegen.string_contains = ir.Function(self.module, string_contains_ty, name="coex_string_contains")

        # string_print(s: String*) -> void
        string_print_ty = ir.FunctionType(ir.VoidType(), [string_ptr])
        self.codegen.string_print = ir.Function(self.module, string_print_ty, name="coex_string_print")

        # string_debug(s: String*) -> void (for debug output with quotes)
        string_debug_ty = ir.FunctionType(ir.VoidType(), [string_ptr])
        self.codegen.string_debug = ir.Function(self.module, string_debug_ty, name="coex_string_debug")

        # string_copy(s: String*) -> String* (shallow copy for value semantics)
        string_copy_ty = ir.FunctionType(string_ptr, [string_ptr])
        self.codegen.string_copy = ir.Function(self.module, string_copy_ty, name="coex_string_copy")

        # string_deep_copy(s: String*) -> String* (deep copy that allocates new buffer)
        string_deep_copy_ty = ir.FunctionType(string_ptr, [string_ptr])
        self.codegen.string_deep_copy = ir.Function(self.module, string_deep_copy_ty, name="coex_string_deep_copy")

        # string_hash(s: String*) -> i64 (FNV-1a hash)
        string_hash_ty = ir.FunctionType(i64, [string_ptr])
        self.codegen.string_hash = ir.Function(self.module, string_hash_ty, name="coex_string_hash")

        # string_setrange(s: String*, start: i64, end: i64, replacement: String*) -> String*
        string_setrange_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64, string_ptr])
        self.codegen.string_setrange = ir.Function(self.module, string_setrange_ty, name="coex_string_setrange")

        # string_to_int(s: String*) -> int? (parse string as integer, nil on failure)
        string_to_int_ty = ir.FunctionType(int_optional, [string_ptr])
        self.codegen.string_to_int = ir.Function(self.module, string_to_int_ty, name="coex_string_to_int")

        # string_to_float(s: String*) -> float? (parse string as float, nil on failure)
        string_to_float_ty = ir.FunctionType(float_optional, [string_ptr])
        self.codegen.string_to_float = ir.Function(self.module, string_to_float_ty, name="coex_string_to_float")

        # string_to_int_hex(s: String*) -> int? (parse hex string as integer, nil on failure)
        string_to_int_hex_ty = ir.FunctionType(int_optional, [string_ptr])
        self.codegen.string_to_int_hex = ir.Function(self.module, string_to_int_hex_ty, name="coex_string_to_int_hex")

        # string_from_int(value: i64) -> String* (convert int to string)
        string_from_int_ty = ir.FunctionType(string_ptr, [i64])
        self.codegen.string_from_int = ir.Function(self.module, string_from_int_ty, name="coex_string_from_int")

        # string_from_float(value: double) -> String* (convert float to string)
        string_from_float_ty = ir.FunctionType(string_ptr, [ir.DoubleType()])
        self.codegen.string_from_float = ir.Function(self.module, string_from_float_ty, name="coex_string_from_float")

        # string_from_bool(value: i1) -> String* (convert bool to string)
        string_from_bool_ty = ir.FunctionType(string_ptr, [i1])
        self.codegen.string_from_bool = ir.Function(self.module, string_from_bool_ty, name="coex_string_from_bool")

        # string_from_hex(value: i64) -> String* (convert int to hex string)
        string_from_hex_ty = ir.FunctionType(string_ptr, [i64])
        self.codegen.string_from_hex = ir.Function(self.module, string_from_hex_ty, name="coex_string_from_hex")

        # string_from_bytes(bytes: List*) -> String* (convert byte list to string)
        string_from_bytes_ty = ir.FunctionType(string_ptr, [list_ptr])
        self.codegen.string_from_bytes = ir.Function(self.module, string_from_bytes_ty, name="coex_string_from_bytes")

        # string_to_bytes(s: String*) -> List* (convert string to byte array)
        string_to_bytes_ty = ir.FunctionType(list_ptr, [string_ptr])
        self.codegen.string_to_bytes = ir.Function(self.module, string_to_bytes_ty, name="coex_string_to_bytes")

        # string_split(s: String*, sep: String*) -> List* (split string by separator)
        string_split_ty = ir.FunctionType(list_ptr, [string_ptr, string_ptr])
        self.codegen.string_split = ir.Function(self.module, string_split_ty, name="coex_string_split")

        # string_validjson(s: String*) -> i1 (check if string is valid JSON)
        string_validjson_ty = ir.FunctionType(i1, [string_ptr])
        self.codegen.string_validjson = ir.Function(self.module, string_validjson_ty, name="coex_string_validjson")

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
        # Note: string_validjson is implemented after JSON type is created (needs json_parse)

        # Register String type methods
        self._register_string_methods()

    # NOTE: The _implement_string_* methods are delegated to codegen_original.py
    # for now. Full extraction will be completed in a follow-up phase.
    # This allows the modularization to proceed incrementally.

    def _implement_string_data(self):
        self.codegen._implement_string_data()

    def _implement_string_new(self):
        self.codegen._implement_string_new()

    def _implement_string_from_literal(self):
        self.codegen._implement_string_from_literal()

    def _implement_string_len(self):
        self.codegen._implement_string_len()

    def _implement_string_size(self):
        self.codegen._implement_string_size()

    def _implement_string_byte_size(self):
        self.codegen._implement_string_byte_size()

    def _implement_string_get(self):
        self.codegen._implement_string_get()

    def _implement_string_slice(self):
        self.codegen._implement_string_slice()

    def _implement_string_concat(self):
        self.codegen._implement_string_concat()

    def _implement_string_join_list(self):
        self.codegen._implement_string_join_list()

    def _implement_string_eq(self):
        self.codegen._implement_string_eq()

    def _implement_string_contains(self):
        self.codegen._implement_string_contains()

    def _implement_string_print(self):
        self.codegen._implement_string_print()

    def _implement_string_debug(self):
        self.codegen._implement_string_debug()

    def _implement_string_copy(self):
        self.codegen._implement_string_copy()

    def _implement_string_deep_copy(self):
        self.codegen._implement_string_deep_copy()

    def _implement_string_hash(self):
        self.codegen._implement_string_hash()

    def _implement_string_setrange(self):
        self.codegen._implement_string_setrange()

    def _implement_string_to_int(self):
        self.codegen._implement_string_to_int()

    def _implement_string_to_float(self):
        self.codegen._implement_string_to_float()

    def _implement_string_to_int_hex(self):
        self.codegen._implement_string_to_int_hex()

    def _implement_string_from_int(self):
        self.codegen._implement_string_from_int()

    def _implement_string_from_float(self):
        self.codegen._implement_string_from_float()

    def _implement_string_from_bool(self):
        self.codegen._implement_string_from_bool()

    def _implement_string_from_hex(self):
        self.codegen._implement_string_from_hex()

    def _implement_string_from_bytes(self):
        self.codegen._implement_string_from_bytes()

    def _implement_string_to_bytes(self):
        self.codegen._implement_string_to_bytes()

    def _implement_string_split(self):
        self.codegen._implement_string_split()

    def implement_string_validjson(self):
        """Implement string_validjson - called after JSON type is created."""
        self.codegen._implement_string_validjson()

    def _register_string_methods(self):
        self.codegen._register_string_methods()
