"""
HAMT (Hash Array Mapped Trie) Module for Coex Code Generator

This module provides Map and Set type implementations using HAMT data structure.
HAMT provides O(log32 n) operations with structural sharing for value semantics.

HAMT Structures:
    HAMTNode: { i32 bitmap, i64* children }
        - bitmap: 32-bit mask indicating which children are present
        - children: array of child pointers (size = popcount(bitmap))

    HAMTLeaf: { i64 hash, i64 key, i64 value }
        - Single key-value entry

    HAMTCollision: { i64 hash, i32 count, i64 entries }
        - Multiple entries with same hash

Map layout: { i64 root, i64 len, i64 flags }
    - root: pointer to HAMT root (as i64)
    - len: number of key-value pairs
    - flags: bit 0 = key is ptr, bit 1 = value is ptr

Set layout: { i64 root, i64 len, i64 flags }
    - root: pointer to HAMT root (as i64)
    - len: number of elements
    - flags: bit 0 = element is ptr

Methods implemented:
- HAMT internals: popcount, node_new, leaf_new, lookup, contains, insert, remove, collect
- Map: new, set, get, has, remove, len, size, copy, keys, values, string variants
- Set: new, add, has, remove, len, size, copy, to_list, string variants
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator


class HAMTGenerator:
    """Generates HAMT-based Map and Set types for the Coex compiler."""

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
    def string_struct(self):
        return self.codegen.string_struct

    # HAMT struct references
    @property
    def hamt_leaf_struct(self):
        return self.codegen.hamt_leaf_struct

    @property
    def hamt_node_struct(self):
        return self.codegen.hamt_node_struct

    @property
    def hamt_collision_struct(self):
        return self.codegen.hamt_collision_struct

    # Map struct and function references
    @property
    def map_struct(self):
        return self.codegen.map_struct

    @property
    def map_entry_struct(self):
        return self.codegen.map_entry_struct

    @property
    def map_new(self):
        return self.codegen.map_new

    @property
    def map_set(self):
        return self.codegen.map_set

    @property
    def map_get(self):
        return self.codegen.map_get

    @property
    def map_has(self):
        return self.codegen.map_has

    @property
    def map_remove(self):
        return self.codegen.map_remove

    @property
    def map_len(self):
        return self.codegen.map_len

    @property
    def map_size(self):
        return self.codegen.map_size

    @property
    def map_hash(self):
        return self.codegen.map_hash

    @property
    def map_copy(self):
        return self.codegen.map_copy

    @property
    def map_set_string(self):
        return self.codegen.map_set_string

    @property
    def map_get_string(self):
        return self.codegen.map_get_string

    @property
    def map_has_string(self):
        return self.codegen.map_has_string

    @property
    def map_remove_string(self):
        return self.codegen.map_remove_string

    @property
    def map_keys(self):
        return self.codegen.map_keys

    @property
    def map_values(self):
        return self.codegen.map_values

    # HAMT internal function references
    @property
    def hamt_popcount(self):
        return self.codegen.hamt_popcount

    @property
    def hamt_node_new(self):
        return self.codegen.hamt_node_new

    @property
    def hamt_leaf_new(self):
        return self.codegen.hamt_leaf_new

    @property
    def hamt_insert(self):
        return self.codegen.hamt_insert

    @property
    def hamt_lookup(self):
        return self.codegen.hamt_lookup

    @property
    def hamt_contains(self):
        return self.codegen.hamt_contains

    @property
    def hamt_remove(self):
        return self.codegen.hamt_remove

    @property
    def hamt_collect_keys(self):
        return self.codegen.hamt_collect_keys

    @property
    def hamt_collect_values(self):
        return self.codegen.hamt_collect_values

    @property
    def hamt_insert_string(self):
        return self.codegen.hamt_insert_string

    @property
    def hamt_lookup_string(self):
        return self.codegen.hamt_lookup_string

    @property
    def hamt_contains_string(self):
        return self.codegen.hamt_contains_string

    @property
    def hamt_remove_string(self):
        return self.codegen.hamt_remove_string

    # Set struct and function references
    @property
    def set_struct(self):
        return self.codegen.set_struct

    @property
    def set_entry_struct(self):
        return self.codegen.set_entry_struct

    @property
    def set_new(self):
        return self.codegen.set_new

    @property
    def set_add(self):
        return self.codegen.set_add

    @property
    def set_has(self):
        return self.codegen.set_has

    @property
    def set_remove(self):
        return self.codegen.set_remove

    @property
    def set_len(self):
        return self.codegen.set_len

    @property
    def set_size(self):
        return self.codegen.set_size

    @property
    def set_grow(self):
        return self.codegen.set_grow

    @property
    def set_find_slot(self):
        return self.codegen.set_find_slot

    @property
    def set_copy(self):
        return self.codegen.set_copy

    @property
    def set_to_list(self):
        return self.codegen.set_to_list

    @property
    def set_find_slot_string(self):
        return self.codegen.set_find_slot_string

    @property
    def set_has_string(self):
        return self.codegen.set_has_string

    @property
    def set_add_string(self):
        return self.codegen.set_add_string

    def create_map_type(self):
        """Create the Map type and helper functions using HAMT.

        HAMT provides O(log32 n) operations with structural sharing for value semantics.
        Each mutation only copies O(log32 n) nodes on the path to the leaf.
        """
        # HAMTLeaf struct: { i64 hash, i64 key, i64 value }
        self.codegen.hamt_leaf_struct = ir.global_context.get_identified_type("struct.HAMTLeaf")
        self.codegen.hamt_leaf_struct.set_body(
            ir.IntType(64),  # hash (field 0)
            ir.IntType(64),  # key (field 1)
            ir.IntType(64)   # value (field 2)
        )

        # HAMTNode struct: { i32 bitmap, i64* children }
        self.codegen.hamt_node_struct = ir.global_context.get_identified_type("struct.HAMTNode")
        self.codegen.hamt_node_struct.set_body(
            ir.IntType(32),  # bitmap (field 0)
            ir.IntType(64).as_pointer()  # children (field 1)
        )

        # HAMTCollision struct: { i64 hash, i32 count, i64 entries }
        self.codegen.hamt_collision_struct = ir.global_context.get_identified_type("struct.HAMTCollision")
        self.codegen.hamt_collision_struct.set_body(
            ir.IntType(64),  # hash (field 0)
            ir.IntType(32),  # count (field 1)
            ir.IntType(64)   # entries (field 2) - pointer stored as i64
        )

        # Map struct: { i64 root, i64 len, i64 flags }
        self.codegen.map_struct = ir.global_context.get_identified_type("struct.Map")
        self.codegen.map_struct.set_body(
            ir.IntType(64),  # root (field 0) - pointer stored as i64
            ir.IntType(64),  # len (field 1)
            ir.IntType(64)   # flags (field 2) - type info for GC
        )

        # Flag constants for Map/Set type info
        self.codegen.MAP_FLAG_KEY_IS_PTR = 0x01
        self.codegen.MAP_FLAG_VALUE_IS_PTR = 0x02

        # MapEntry struct (kept for backward compatibility)
        self.codegen.map_entry_struct = ir.global_context.get_identified_type("struct.MapEntry")
        self.codegen.map_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(64),  # value
            ir.IntType(8)    # state
        )

        map_ptr = self.codegen.map_struct.as_pointer()
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)
        void_ptr = ir.IntType(8).as_pointer()
        hamt_node_ptr = self.codegen.hamt_node_struct.as_pointer()
        hamt_leaf_ptr = self.codegen.hamt_leaf_struct.as_pointer()

        # map_new(flags: i64) -> Map*
        map_new_ty = ir.FunctionType(map_ptr, [i64])
        self.codegen.map_new = ir.Function(self.module, map_new_ty, name="coex_map_new")

        # map_set(map: Map*, key: i64, value: i64) -> Map*
        map_set_ty = ir.FunctionType(map_ptr, [map_ptr, i64, i64])
        self.codegen.map_set = ir.Function(self.module, map_set_ty, name="coex_map_set")

        # map_get(map: Map*, key: i64) -> i64
        map_get_ty = ir.FunctionType(i64, [map_ptr, i64])
        self.codegen.map_get = ir.Function(self.module, map_get_ty, name="coex_map_get")

        # map_has(map: Map*, key: i64) -> bool
        map_has_ty = ir.FunctionType(i1, [map_ptr, i64])
        self.codegen.map_has = ir.Function(self.module, map_has_ty, name="coex_map_has")

        # map_remove(map: Map*, key: i64) -> Map*
        map_remove_ty = ir.FunctionType(map_ptr, [map_ptr, i64])
        self.codegen.map_remove = ir.Function(self.module, map_remove_ty, name="coex_map_remove")

        # map_len(map: Map*) -> i64
        map_len_ty = ir.FunctionType(i64, [map_ptr])
        self.codegen.map_len = ir.Function(self.module, map_len_ty, name="coex_map_len")

        # map_size(map: Map*) -> i64
        map_size_ty = ir.FunctionType(i64, [map_ptr])
        self.codegen.map_size = ir.Function(self.module, map_size_ty, name="coex_map_size")

        # map_hash(key: i64) -> i64
        map_hash_ty = ir.FunctionType(i64, [i64])
        self.codegen.map_hash = ir.Function(self.module, map_hash_ty, name="coex_map_hash")

        # map_copy(map: Map*) -> Map*
        map_copy_ty = ir.FunctionType(map_ptr, [map_ptr])
        self.codegen.map_copy = ir.Function(self.module, map_copy_ty, name="coex_map_copy")

        # HAMT internal: popcount(i32) -> i32
        popcount_ty = ir.FunctionType(i32, [i32])
        self.codegen.hamt_popcount = ir.Function(self.module, popcount_ty, name="coex_hamt_popcount")

        # HAMT internal: hamt_node_new(bitmap: i32, child_count: i32) -> HAMTNode*
        hamt_node_new_ty = ir.FunctionType(hamt_node_ptr, [i32, i32])
        self.codegen.hamt_node_new = ir.Function(self.module, hamt_node_new_ty, name="coex_hamt_node_new")

        # HAMT internal: hamt_leaf_new(hash: i64, key: i64, value: i64) -> HAMTLeaf*
        hamt_leaf_new_ty = ir.FunctionType(hamt_leaf_ptr, [i64, i64, i64])
        self.codegen.hamt_leaf_new = ir.Function(self.module, hamt_leaf_new_ty, name="coex_hamt_leaf_new")

        # HAMT internal: hamt_insert(node: void*, hash: i64, key: i64, value: i64, shift: i32, added: i32*) -> void*
        hamt_insert_ty = ir.FunctionType(void_ptr, [void_ptr, i64, i64, i64, i32, i32.as_pointer()])
        self.codegen.hamt_insert = ir.Function(self.module, hamt_insert_ty, name="coex_hamt_insert")

        # HAMT internal: hamt_lookup(node: void*, hash: i64, key: i64, shift: i32) -> i64
        hamt_lookup_ty = ir.FunctionType(i64, [void_ptr, i64, i64, i32])
        self.codegen.hamt_lookup = ir.Function(self.module, hamt_lookup_ty, name="coex_hamt_lookup")

        # HAMT internal: hamt_contains(node: void*, hash: i64, key: i64, shift: i32) -> bool
        hamt_contains_ty = ir.FunctionType(i1, [void_ptr, i64, i64, i32])
        self.codegen.hamt_contains = ir.Function(self.module, hamt_contains_ty, name="coex_hamt_contains")

        # HAMT internal: hamt_remove(node: void*, hash: i64, key: i64, shift: i32, removed: i32*) -> void*
        hamt_remove_ty = ir.FunctionType(void_ptr, [void_ptr, i64, i64, i32, i32.as_pointer()])
        self.codegen.hamt_remove = ir.Function(self.module, hamt_remove_ty, name="coex_hamt_remove")

        # HAMT internal: hamt_collect_keys(node: void*, list: List*) -> List*
        list_ptr_type = self.list_struct.as_pointer()
        hamt_collect_ty = ir.FunctionType(list_ptr_type, [void_ptr, list_ptr_type])
        self.codegen.hamt_collect_keys = ir.Function(self.module, hamt_collect_ty, name="coex_hamt_collect_keys")

        # hamt_collect_values
        hamt_collect_values_ty = ir.FunctionType(list_ptr_type, [void_ptr, list_ptr_type])
        self.codegen.hamt_collect_values = ir.Function(self.module, hamt_collect_values_ty, name="coex_hamt_collect_values")

        # HAMT string variants
        string_ptr = self.string_struct.as_pointer()

        # hamt_insert_string
        hamt_insert_string_ty = ir.FunctionType(void_ptr, [void_ptr, i64, string_ptr, i64, i32, i32.as_pointer()])
        self.codegen.hamt_insert_string = ir.Function(self.module, hamt_insert_string_ty, name="coex_hamt_insert_string")

        # hamt_lookup_string
        hamt_lookup_string_ty = ir.FunctionType(i64, [void_ptr, i64, string_ptr, i32])
        self.codegen.hamt_lookup_string = ir.Function(self.module, hamt_lookup_string_ty, name="coex_hamt_lookup_string")

        # hamt_contains_string
        hamt_contains_string_ty = ir.FunctionType(i1, [void_ptr, i64, string_ptr, i32])
        self.codegen.hamt_contains_string = ir.Function(self.module, hamt_contains_string_ty, name="coex_hamt_contains_string")

        # hamt_remove_string
        hamt_remove_string_ty = ir.FunctionType(void_ptr, [void_ptr, i64, string_ptr, i32, i32.as_pointer()])
        self.codegen.hamt_remove_string = ir.Function(self.module, hamt_remove_string_ty, name="coex_hamt_remove_string")

        # String-key map variants
        # map_set_string
        map_set_string_ty = ir.FunctionType(map_ptr, [map_ptr, string_ptr, i64])
        self.codegen.map_set_string = ir.Function(self.module, map_set_string_ty, name="coex_map_set_string")

        # map_get_string
        map_get_string_ty = ir.FunctionType(i64, [map_ptr, string_ptr])
        self.codegen.map_get_string = ir.Function(self.module, map_get_string_ty, name="coex_map_get_string")

        # map_has_string
        map_has_string_ty = ir.FunctionType(i1, [map_ptr, string_ptr])
        self.codegen.map_has_string = ir.Function(self.module, map_has_string_ty, name="coex_map_has_string")

        # map_remove_string
        map_remove_string_ty = ir.FunctionType(map_ptr, [map_ptr, string_ptr])
        self.codegen.map_remove_string = ir.Function(self.module, map_remove_string_ty, name="coex_map_remove_string")

        # map_keys and map_values
        list_ptr = self.list_struct.as_pointer()
        map_keys_ty = ir.FunctionType(list_ptr, [map_ptr])
        self.codegen.map_keys = ir.Function(self.module, map_keys_ty, name="coex_map_keys")

        map_values_ty = ir.FunctionType(list_ptr, [map_ptr])
        self.codegen.map_values = ir.Function(self.module, map_values_ty, name="coex_map_values")

        # Implement HAMT helper functions first
        self._implement_hamt_popcount()
        self._implement_hamt_node_new()
        self._implement_hamt_leaf_new()
        self._implement_hamt_lookup()
        self._implement_hamt_contains()
        self._implement_hamt_insert()
        self._implement_hamt_remove()
        self._implement_hamt_collect_keys()
        self._implement_hamt_collect_values()

        # Implement HAMT string variants
        self._implement_hamt_lookup_string()
        self._implement_hamt_contains_string()
        self._implement_hamt_insert_string()
        self._implement_hamt_remove_string()

        # Implement main Map functions
        self._implement_map_hash()
        self._implement_map_new()
        self._implement_map_set()
        self._implement_map_get()
        self._implement_map_has()
        self._implement_map_remove()
        self._implement_map_len()
        self._implement_map_size()
        self._implement_map_copy()
        self._implement_map_set_string()
        self._implement_map_get_string()
        self._implement_map_has_string()
        self._implement_map_remove_string()
        self._implement_map_keys()
        self._implement_map_values()

        # Register Map methods
        self._register_map_methods()

    def create_set_type(self):
        """Create the Set type and helper functions.

        Set uses HAMT infrastructure with pointer tagging.
        Leaves store {hash, key, value} where value is always 1 for sets.
        """
        # SetEntry struct (kept for backward compatibility)
        self.codegen.set_entry_struct = ir.global_context.get_identified_type("struct.SetEntry")
        self.codegen.set_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(8)    # state: 0=empty, 1=occupied, 2=deleted
        )

        # Set struct: { i64 root, i64 len, i64 flags }
        self.codegen.set_struct = ir.global_context.get_identified_type("struct.Set")
        self.codegen.set_struct.set_body(
            ir.IntType(64),  # root (pointer stored as i64)
            ir.IntType(64),  # len
            ir.IntType(64)   # flags (type info for GC)
        )

        set_ptr = self.codegen.set_struct.as_pointer()
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # set_new(flags: i64) -> Set*
        set_new_ty = ir.FunctionType(set_ptr, [i64])
        self.codegen.set_new = ir.Function(self.module, set_new_ty, name="coex_set_new")

        # set_add(set: Set*, key: i64) -> Set*
        set_add_ty = ir.FunctionType(set_ptr, [set_ptr, i64])
        self.codegen.set_add = ir.Function(self.module, set_add_ty, name="coex_set_add")

        # set_has(set: Set*, key: i64) -> bool
        set_has_ty = ir.FunctionType(i1, [set_ptr, i64])
        self.codegen.set_has = ir.Function(self.module, set_has_ty, name="coex_set_has")

        # set_remove(set: Set*, key: i64) -> Set*
        set_remove_ty = ir.FunctionType(set_ptr, [set_ptr, i64])
        self.codegen.set_remove = ir.Function(self.module, set_remove_ty, name="coex_set_remove")

        # set_len(set: Set*) -> i64
        set_len_ty = ir.FunctionType(i64, [set_ptr])
        self.codegen.set_len = ir.Function(self.module, set_len_ty, name="coex_set_len")

        # set_size(set: Set*) -> i64
        set_size_ty = ir.FunctionType(i64, [set_ptr])
        self.codegen.set_size = ir.Function(self.module, set_size_ty, name="coex_set_size")

        # set_grow(set: Set*)
        set_grow_ty = ir.FunctionType(ir.VoidType(), [set_ptr])
        self.codegen.set_grow = ir.Function(self.module, set_grow_ty, name="coex_set_grow")

        # set_find_slot(set: Set*, key: i64) -> i64
        set_find_slot_ty = ir.FunctionType(i64, [set_ptr, i64])
        self.codegen.set_find_slot = ir.Function(self.module, set_find_slot_ty, name="coex_set_find_slot")

        # set_copy(set: Set*) -> Set*
        set_copy_ty = ir.FunctionType(set_ptr, [set_ptr])
        self.codegen.set_copy = ir.Function(self.module, set_copy_ty, name="coex_set_copy")

        # set_to_list(set: Set*) -> List*
        list_ptr = self.list_struct.as_pointer()
        set_to_list_ty = ir.FunctionType(list_ptr, [set_ptr])
        self.codegen.set_to_list = ir.Function(self.module, set_to_list_ty, name="coex_set_to_list")

        # String-specific Set operations
        string_ptr = self.string_struct.as_pointer()

        # set_find_slot_string
        set_find_slot_string_ty = ir.FunctionType(i64, [set_ptr, string_ptr])
        self.codegen.set_find_slot_string = ir.Function(self.module, set_find_slot_string_ty, name="coex_set_find_slot_string")

        # set_has_string
        set_has_string_ty = ir.FunctionType(i1, [set_ptr, string_ptr])
        self.codegen.set_has_string = ir.Function(self.module, set_has_string_ty, name="coex_set_has_string")

        # set_add_string
        set_add_string_ty = ir.FunctionType(set_ptr, [set_ptr, string_ptr])
        self.codegen.set_add_string = ir.Function(self.module, set_add_string_ty, name="coex_set_add_string")

        # Implement all set functions
        self._implement_set_new()
        self._implement_set_find_slot()
        self._implement_set_grow()
        self._implement_set_add()
        self._implement_set_has()
        self._implement_set_remove()
        self._implement_set_len()
        self._implement_set_size()
        self._implement_set_copy()
        self._implement_set_to_list()
        self._implement_set_find_slot_string()
        self._implement_set_has_string()
        self._implement_set_add_string()
        self._register_set_methods()

    # ========================================================================
    # HAMT Implementation Delegations
    # ========================================================================

    def _implement_hamt_popcount(self):
        self.codegen._implement_hamt_popcount()

    def _implement_hamt_node_new(self):
        self.codegen._implement_hamt_node_new()

    def _implement_hamt_leaf_new(self):
        self.codegen._implement_hamt_leaf_new()

    def _implement_hamt_lookup(self):
        self.codegen._implement_hamt_lookup()

    def _implement_hamt_contains(self):
        self.codegen._implement_hamt_contains()

    def _implement_hamt_insert(self):
        self.codegen._implement_hamt_insert()

    def _implement_hamt_remove(self):
        self.codegen._implement_hamt_remove()

    def _implement_hamt_collect_keys(self):
        self.codegen._implement_hamt_collect_keys()

    def _implement_hamt_collect_values(self):
        self.codegen._implement_hamt_collect_values()

    def _implement_hamt_lookup_string(self):
        self.codegen._implement_hamt_lookup_string()

    def _implement_hamt_contains_string(self):
        self.codegen._implement_hamt_contains_string()

    def _implement_hamt_insert_string(self):
        self.codegen._implement_hamt_insert_string()

    def _implement_hamt_remove_string(self):
        self.codegen._implement_hamt_remove_string()

    # ========================================================================
    # Map Implementation Delegations
    # ========================================================================

    def _implement_map_hash(self):
        self.codegen._implement_map_hash()

    def _implement_map_new(self):
        self.codegen._implement_map_new()

    def _implement_map_set(self):
        self.codegen._implement_map_set()

    def _implement_map_get(self):
        self.codegen._implement_map_get()

    def _implement_map_has(self):
        self.codegen._implement_map_has()

    def _implement_map_remove(self):
        self.codegen._implement_map_remove()

    def _implement_map_len(self):
        self.codegen._implement_map_len()

    def _implement_map_size(self):
        self.codegen._implement_map_size()

    def _implement_map_copy(self):
        self.codegen._implement_map_copy()

    def _implement_map_set_string(self):
        self.codegen._implement_map_set_string()

    def _implement_map_get_string(self):
        self.codegen._implement_map_get_string()

    def _implement_map_has_string(self):
        self.codegen._implement_map_has_string()

    def _implement_map_remove_string(self):
        self.codegen._implement_map_remove_string()

    def _implement_map_keys(self):
        self.codegen._implement_map_keys()

    def _implement_map_values(self):
        self.codegen._implement_map_values()

    def _register_map_methods(self):
        self.codegen._register_map_methods()

    # ========================================================================
    # Set Implementation Delegations
    # ========================================================================

    def _implement_set_new(self):
        self.codegen._implement_set_new()

    def _implement_set_find_slot(self):
        self.codegen._implement_set_find_slot()

    def _implement_set_grow(self):
        self.codegen._implement_set_grow()

    def _implement_set_add(self):
        self.codegen._implement_set_add()

    def _implement_set_has(self):
        self.codegen._implement_set_has()

    def _implement_set_remove(self):
        self.codegen._implement_set_remove()

    def _implement_set_len(self):
        self.codegen._implement_set_len()

    def _implement_set_size(self):
        self.codegen._implement_set_size()

    def _implement_set_copy(self):
        self.codegen._implement_set_copy()

    def _implement_set_to_list(self):
        self.codegen._implement_set_to_list()

    def _implement_set_find_slot_string(self):
        self.codegen._implement_set_find_slot_string()

    def _implement_set_has_string(self):
        self.codegen._implement_set_has_string()

    def _implement_set_add_string(self):
        self.codegen._implement_set_add_string()

    def _register_set_methods(self):
        self.codegen._register_set_methods()
