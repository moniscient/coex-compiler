"""
Collections Module for Coex Code Generator

This module provides List and Array type implementations for the Coex compiler.

List (Persistent Vector):
    Field 0: i64 root_handle    - 0 for empty/small lists
    Field 1: i64 len            - total element count
    Field 2: i64 depth          - tree depth (0 = tail only)
    Field 3: i64 tail_handle    - rightmost leaf array handle
    Field 4: i64 tail_len       - elements in tail (0-32)
    Field 5: i64 elem_size      - size of each element

Array (Dense Contiguous Collection):
    Field 0: i64 owner_handle   - handle to data buffer
    Field 1: i64 offset         - byte offset into owner's data
    Field 2: i64 len            - element count
    Field 3: i64 cap            - capacity
    Field 4: i64 elem_size      - size of each element

Both types have value semantics - all mutation operations return new instances.

Methods implemented:
- List: new, append, get, set, len, size, copy, getrange, setrange
- Array: new, get, set, append, len, size, copy, deep_copy, getrange
- Conversions: list_to_array, array_to_list, set_to_array, array_to_set, list_to_set
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator


class CollectionsGenerator:
    """Generates List and Array types and methods for the Coex compiler."""

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
    def type_fields(self):
        return self.codegen.type_fields

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
    def array_struct(self):
        return self.codegen.array_struct

    @property
    def memcpy(self):
        return self.codegen.memcpy

    # List function references
    @property
    def list_new(self):
        return self.codegen.list_new

    @property
    def list_append(self):
        return self.codegen.list_append

    @property
    def list_get(self):
        return self.codegen.list_get

    @property
    def list_set(self):
        return self.codegen.list_set

    @property
    def list_len(self):
        return self.codegen.list_len

    @property
    def list_size(self):
        return self.codegen.list_size

    @property
    def list_copy(self):
        return self.codegen.list_copy

    @property
    def list_getrange(self):
        return self.codegen.list_getrange

    @property
    def list_setrange(self):
        return self.codegen.list_setrange

    # Array function references
    @property
    def array_new(self):
        return self.codegen.array_new

    @property
    def array_get(self):
        return self.codegen.array_get

    @property
    def array_set(self):
        return self.codegen.array_set

    @property
    def array_append(self):
        return self.codegen.array_append

    @property
    def array_len(self):
        return self.codegen.array_len

    @property
    def array_size(self):
        return self.codegen.array_size

    @property
    def array_copy(self):
        return self.codegen.array_copy

    @property
    def array_deep_copy(self):
        return self.codegen.array_deep_copy

    @property
    def array_getrange(self):
        return self.codegen.array_getrange

    def create_list_helpers(self):
        """Create helper functions for list operations.

        Persistent Vector List struct (Phase 4 - all i64):
        - field 0: root_handle (i64) - 0 for empty/small lists
        - field 1: len (i64) - total element count
        - field 2: depth (i64) - tree depth (0 = tail only)
        - field 3: tail_handle (i64) - rightmost leaf array handle
        - field 4: tail_len (i64) - elements in tail (0-32)
        - field 5: elem_size (i64)
        """
        list_ptr = self.list_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # list_new(elem_size: i64) -> List*
        list_new_ty = ir.FunctionType(list_ptr, [i64])
        self.codegen.list_new = ir.Function(self.module, list_new_ty, name="coex_list_new")

        # list_append(list: List*, elem: i8*, elem_size: i64) -> List*
        # Returns a NEW list with the element appended (value semantics)
        list_append_ty = ir.FunctionType(list_ptr, [list_ptr, i8_ptr, i64])
        self.codegen.list_append = ir.Function(self.module, list_append_ty, name="coex_list_append")

        # list_get(list: List*, index: i64) -> i8*
        list_get_ty = ir.FunctionType(i8_ptr, [list_ptr, i64])
        self.codegen.list_get = ir.Function(self.module, list_get_ty, name="coex_list_get")

        # list_len(list: List*) -> i64
        list_len_ty = ir.FunctionType(i64, [list_ptr])
        self.codegen.list_len = ir.Function(self.module, list_len_ty, name="coex_list_len")

        # list_size(list: List*) -> i64 (total memory footprint in bytes)
        list_size_ty = ir.FunctionType(i64, [list_ptr])
        self.codegen.list_size = ir.Function(self.module, list_size_ty, name="coex_list_size")

        # list_copy(list: List*) -> List* (deep copy for value semantics)
        list_copy_ty = ir.FunctionType(list_ptr, [list_ptr])
        self.codegen.list_copy = ir.Function(self.module, list_copy_ty, name="coex_list_copy")

        # list_set(list: List*, index: i64, value: i8*, elem_size: i64) -> List*
        # Returns a NEW list with element at index replaced (value semantics, path copying)
        list_set_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i8_ptr, i64])
        self.codegen.list_set = ir.Function(self.module, list_set_ty, name="coex_list_set")

        # list_getrange(list: List*, start: i64, end: i64) -> List*
        # Returns a NEW list with elements [start, end)
        list_getrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64])
        self.codegen.list_getrange = ir.Function(self.module, list_getrange_ty, name="coex_list_getrange")

        # list_setrange(list: List*, start: i64, end: i64, source: List*) -> List*
        # Returns a NEW list with elements [start, end) replaced by elements from source
        list_setrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64, list_ptr])
        self.codegen.list_setrange = ir.Function(self.module, list_setrange_ty, name="coex_list_setrange")

        # NOTE: list_to_array is declared after Array type exists (in _create_conversion_helpers)

        # Now implement these functions inline
        self._implement_list_new()
        self._implement_list_append()
        self._implement_list_get()
        self._implement_list_set()
        self._implement_list_len()
        self._implement_list_size()
        self._implement_list_copy()
        self._implement_list_getrange()
        self._implement_list_setrange()
        self._register_list_methods()

    def create_array_helpers(self):
        """Create helper functions for Array operations.

        Array is a dense, contiguous collection with value semantics.
        All 'mutation' operations return a new array.

        Struct layout: { i64 owner_handle, i64 offset, i64 len, i64 cap, i64 elem_size }
        """
        array_ptr = self.array_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # array_new(cap: i64, elem_size: i64) -> Array*
        array_new_ty = ir.FunctionType(array_ptr, [i64, i64])
        self.codegen.array_new = ir.Function(self.module, array_new_ty, name="coex_array_new")

        # array_get(arr: Array*, index: i64) -> i8*
        array_get_ty = ir.FunctionType(i8_ptr, [array_ptr, i64])
        self.codegen.array_get = ir.Function(self.module, array_get_ty, name="coex_array_get")

        # array_set(arr: Array*, index: i64, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element at index replaced
        array_set_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i8_ptr, i64])
        self.codegen.array_set = ir.Function(self.module, array_set_ty, name="coex_array_set")

        # array_append(arr: Array*, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element appended
        array_append_ty = ir.FunctionType(array_ptr, [array_ptr, i8_ptr, i64])
        self.codegen.array_append = ir.Function(self.module, array_append_ty, name="coex_array_append")

        # array_len(arr: Array*) -> i64
        array_len_ty = ir.FunctionType(i64, [array_ptr])
        self.codegen.array_len = ir.Function(self.module, array_len_ty, name="coex_array_len")

        # array_size(arr: Array*) -> i64 (total memory footprint)
        array_size_ty = ir.FunctionType(i64, [array_ptr])
        self.codegen.array_size = ir.Function(self.module, array_size_ty, name="coex_array_size")

        # array_copy(arr: Array*) -> Array* (deep copy for value semantics)
        array_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        self.codegen.array_copy = ir.Function(self.module, array_copy_ty, name="coex_array_copy")

        # array_deep_copy(arr: Array*) -> Array* (creates independent copy with new buffer)
        array_deep_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        self.codegen.array_deep_copy = ir.Function(self.module, array_deep_copy_ty, name="coex_array_deep_copy")

        # array_getrange(arr: Array*, start: i64, end: i64) -> Array*
        # Returns a VIEW (not a copy) of elements [start, end)
        array_getrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64])
        self.codegen.array_getrange = ir.Function(self.module, array_getrange_ty, name="coex_array_getrange")

        # Implement all functions
        self._implement_array_new()
        self._implement_array_get()
        self._implement_array_set()
        self._implement_array_append()
        self._implement_array_len()
        self._implement_array_size()
        self._implement_array_copy()
        self._implement_array_deep_copy()
        self._implement_array_getrange()
        self._register_array_methods()

    # NOTE: The _implement_* methods are delegated to codegen_original.py
    # for now. Full extraction will be completed in a follow-up phase.
    # This allows the modularization to proceed incrementally.

    # List implementation delegations
    def _implement_list_new(self):
        self.codegen._implement_list_new()

    def _implement_list_append(self):
        self.codegen._implement_list_append()

    def _implement_list_get(self):
        self.codegen._implement_list_get()

    def _implement_list_set(self):
        self.codegen._implement_list_set()

    def _implement_list_len(self):
        self.codegen._implement_list_len()

    def _implement_list_size(self):
        self.codegen._implement_list_size()

    def _implement_list_copy(self):
        self.codegen._implement_list_copy()

    def _implement_list_getrange(self):
        self.codegen._implement_list_getrange()

    def _implement_list_setrange(self):
        self.codegen._implement_list_setrange()

    def _register_list_methods(self):
        self.codegen._register_list_methods()

    # Array implementation delegations
    def _implement_array_new(self):
        self.codegen._implement_array_new()

    def _implement_array_get(self):
        self.codegen._implement_array_get()

    def _implement_array_set(self):
        self.codegen._implement_array_set()

    def _implement_array_append(self):
        self.codegen._implement_array_append()

    def _implement_array_len(self):
        self.codegen._implement_array_len()

    def _implement_array_size(self):
        self.codegen._implement_array_size()

    def _implement_array_copy(self):
        self.codegen._implement_array_copy()

    def _implement_array_deep_copy(self):
        self.codegen._implement_array_deep_copy()

    def _implement_array_getrange(self):
        self.codegen._implement_array_getrange()

    def _register_array_methods(self):
        self.codegen._register_array_methods()

    # Conversion method delegations
    def list_to_array(self, list_ptr: 'ir.Value') -> 'ir.Value':
        """Convert a List to an Array (List.packed() -> Array)."""
        return self.codegen._list_to_array(list_ptr)

    def array_to_list(self, array_ptr: 'ir.Value') -> 'ir.Value':
        """Convert an Array to a List (Array.unpacked() -> List)."""
        return self.codegen._array_to_list(array_ptr)

    def set_to_array(self, set_ptr: 'ir.Value') -> 'ir.Value':
        """Convert a Set to an Array (Set.packed() -> Array)."""
        return self.codegen._set_to_array(set_ptr)

    def array_to_set(self, array_ptr: 'ir.Value', elem_is_ptr: bool = False) -> 'ir.Value':
        """Convert an Array to a Set (Array.to_set() -> Set)."""
        return self.codegen._array_to_set(array_ptr, elem_is_ptr)

    def list_to_set(self, list_ptr: 'ir.Value', elem_is_ptr: bool = False) -> 'ir.Value':
        """Convert a List to a Set (List.to_set() -> Set)."""
        return self.codegen._list_to_set(list_ptr, elem_is_ptr)
