"""
HAMT (Hash Array Mapped Trie), Map, and Set type implementations for Coex.

This module provides:
- HAMT: Core data structure with O(log32 n) operations and structural sharing
- Map: Key-value dictionary using HAMT for persistent/immutable semantics
- Set: Unique element collection using HAMT for persistent/immutable semantics

HAMTNode layout (internal nodes):
    i32 bitmap   - 32-bit mask indicating which children are present
    i64* children - array of child pointers (size = popcount(bitmap))
    Children point to HAMTNode*, HAMTLeaf*, or HAMTCollision*

HAMTLeaf layout (single key-value entry):
    i64 hash     - full hash for collision detection
    i64 key      - key (int value or String pointer)
    i64 value    - value (int value or pointer)

Map layout:
    i64 root     - void pointer to root node (stored as i64)
    i64 len      - number of key-value pairs
    i64 flags    - type info (bit 0 = key is ptr, bit 1 = value is ptr)

Set layout:
    i64 root     - void pointer to root node (stored as i64)
    i64 len      - number of elements
    i64 flags    - type info (bit 0 = element is ptr)

Pointer tagging: bit 0 = 1 for leaf, 0 for node
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class HamtGenerator:
    """Generates HAMT, Map, and Set types and methods for the Coex compiler."""

    # Flag constants for Map/Set type info
    MAP_FLAG_KEY_IS_PTR = 0x01    # Key is a heap pointer (e.g., string)
    MAP_FLAG_VALUE_IS_PTR = 0x02  # Value is a heap pointer

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_map_type(self):
        """Create the Map type and helper functions using HAMT (Hash Array Mapped Trie).

        HAMT provides O(log32 n) operations with structural sharing for value semantics.
        Each mutation only copies O(log32 n) nodes on the path to the leaf.
        """
        cg = self.cg

        # HAMTLeaf struct: { i64 hash, i64 key, i64 value }
        cg.hamt_leaf_struct = ir.global_context.get_identified_type("struct.HAMTLeaf")
        cg.hamt_leaf_struct.set_body(
            ir.IntType(64),  # hash (field 0)
            ir.IntType(64),  # key (field 1)
            ir.IntType(64)   # value (field 2)
        )

        # HAMTNode struct: { i32 bitmap, i64* children } - Phase 5: children are i64 handles
        cg.hamt_node_struct = ir.global_context.get_identified_type("struct.HAMTNode")
        cg.hamt_node_struct.set_body(
            ir.IntType(32),  # bitmap (field 0)
            ir.IntType(64).as_pointer()  # children (field 1) - Phase 5: i64 array
        )

        # HAMTCollision struct: { i64 hash, i32 count, i64 entries }
        cg.hamt_collision_struct = ir.global_context.get_identified_type("struct.HAMTCollision")
        cg.hamt_collision_struct.set_body(
            ir.IntType(64),  # hash (field 0)
            ir.IntType(32),  # count (field 1)
            ir.IntType(64)   # entries (field 2) - Phase 5: pointer stored as i64
        )

        # Map struct: { i64 root, i64 len, i64 flags }
        cg.map_struct = ir.global_context.get_identified_type("struct.Map")
        cg.map_struct.set_body(
            ir.IntType(64),              # root (field 0) - pointer stored as i64
            ir.IntType(64),              # len (field 1)
            ir.IntType(64)               # flags (field 2) - type info for GC
        )

        # Store flag constants on cg for access by other code
        cg.MAP_FLAG_KEY_IS_PTR = self.MAP_FLAG_KEY_IS_PTR
        cg.MAP_FLAG_VALUE_IS_PTR = self.MAP_FLAG_VALUE_IS_PTR

        # Keep MapEntry for backward compatibility
        cg.map_entry_struct = ir.global_context.get_identified_type("struct.MapEntry")
        cg.map_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(64),  # value
            ir.IntType(8)    # state (not used in HAMT)
        )

        map_ptr = cg.map_struct.as_pointer()
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)
        void_ptr = ir.IntType(8).as_pointer()
        hamt_node_ptr = cg.hamt_node_struct.as_pointer()
        hamt_leaf_ptr = cg.hamt_leaf_struct.as_pointer()

        # map_new(flags: i64) -> Map*
        map_new_ty = ir.FunctionType(map_ptr, [i64])
        cg.map_new = ir.Function(cg.module, map_new_ty, name="coex_map_new")

        # map_set(map: Map*, key: i64, value: i64) -> Map*
        map_set_ty = ir.FunctionType(map_ptr, [map_ptr, i64, i64])
        cg.map_set = ir.Function(cg.module, map_set_ty, name="coex_map_set")

        # map_get(map: Map*, key: i64) -> i64
        map_get_ty = ir.FunctionType(i64, [map_ptr, i64])
        cg.map_get = ir.Function(cg.module, map_get_ty, name="coex_map_get")

        # map_has(map: Map*, key: i64) -> bool
        map_has_ty = ir.FunctionType(i1, [map_ptr, i64])
        cg.map_has = ir.Function(cg.module, map_has_ty, name="coex_map_has")

        # map_remove(map: Map*, key: i64) -> Map*
        map_remove_ty = ir.FunctionType(map_ptr, [map_ptr, i64])
        cg.map_remove = ir.Function(cg.module, map_remove_ty, name="coex_map_remove")

        # map_len(map: Map*) -> i64
        map_len_ty = ir.FunctionType(i64, [map_ptr])
        cg.map_len = ir.Function(cg.module, map_len_ty, name="coex_map_len")

        # map_size(map: Map*) -> i64
        map_size_ty = ir.FunctionType(i64, [map_ptr])
        cg.map_size = ir.Function(cg.module, map_size_ty, name="coex_map_size")

        # map_hash(key: i64) -> i64
        map_hash_ty = ir.FunctionType(i64, [i64])
        cg.map_hash = ir.Function(cg.module, map_hash_ty, name="coex_map_hash")

        # map_copy(map: Map*) -> Map*
        map_copy_ty = ir.FunctionType(map_ptr, [map_ptr])
        cg.map_copy = ir.Function(cg.module, map_copy_ty, name="coex_map_copy")

        # HAMT internal: popcount(i32) -> i32
        popcount_ty = ir.FunctionType(i32, [i32])
        cg.hamt_popcount = ir.Function(cg.module, popcount_ty, name="coex_hamt_popcount")

        # HAMT internal: hamt_node_new(bitmap: i32, child_count: i32) -> HAMTNode*
        hamt_node_new_ty = ir.FunctionType(hamt_node_ptr, [i32, i32])
        cg.hamt_node_new = ir.Function(cg.module, hamt_node_new_ty, name="coex_hamt_node_new")

        # HAMT internal: hamt_leaf_new(hash: i64, key: i64, value: i64) -> HAMTLeaf*
        hamt_leaf_new_ty = ir.FunctionType(hamt_leaf_ptr, [i64, i64, i64])
        cg.hamt_leaf_new = ir.Function(cg.module, hamt_leaf_new_ty, name="coex_hamt_leaf_new")

        # HAMT internal: hamt_insert(node: void*, hash: i64, key: i64, value: i64, shift: i32, added: i32*) -> void*
        hamt_insert_ty = ir.FunctionType(void_ptr, [void_ptr, i64, i64, i64, i32, i32.as_pointer()])
        cg.hamt_insert = ir.Function(cg.module, hamt_insert_ty, name="coex_hamt_insert")

        # HAMT internal: hamt_lookup(node: void*, hash: i64, key: i64, shift: i32) -> i64
        hamt_lookup_ty = ir.FunctionType(i64, [void_ptr, i64, i64, i32])
        cg.hamt_lookup = ir.Function(cg.module, hamt_lookup_ty, name="coex_hamt_lookup")

        # HAMT internal: hamt_contains(node: void*, hash: i64, key: i64, shift: i32) -> bool
        hamt_contains_ty = ir.FunctionType(i1, [void_ptr, i64, i64, i32])
        cg.hamt_contains = ir.Function(cg.module, hamt_contains_ty, name="coex_hamt_contains")

        # HAMT internal: hamt_remove(node: void*, hash: i64, key: i64, shift: i32, removed: i32*) -> void*
        hamt_remove_ty = ir.FunctionType(void_ptr, [void_ptr, i64, i64, i32, i32.as_pointer()])
        cg.hamt_remove = ir.Function(cg.module, hamt_remove_ty, name="coex_hamt_remove")

        # HAMT internal: hamt_collect_keys(node: void*, list: List*) -> List*
        list_ptr_type = cg.list_struct.as_pointer()
        hamt_collect_ty = ir.FunctionType(list_ptr_type, [void_ptr, list_ptr_type])
        cg.hamt_collect_keys = ir.Function(cg.module, hamt_collect_ty, name="coex_hamt_collect_keys")

        # Collect all values into a list
        hamt_collect_values_ty = ir.FunctionType(list_ptr_type, [void_ptr, list_ptr_type])
        cg.hamt_collect_values = ir.Function(cg.module, hamt_collect_values_ty, name="coex_hamt_collect_values")

        # HAMT string variants
        string_ptr = cg.string_struct.as_pointer()

        # hamt_insert_string
        hamt_insert_string_ty = ir.FunctionType(void_ptr, [void_ptr, i64, string_ptr, i64, i32, i32.as_pointer()])
        cg.hamt_insert_string = ir.Function(cg.module, hamt_insert_string_ty, name="coex_hamt_insert_string")

        # hamt_lookup_string
        hamt_lookup_string_ty = ir.FunctionType(i64, [void_ptr, i64, string_ptr, i32])
        cg.hamt_lookup_string = ir.Function(cg.module, hamt_lookup_string_ty, name="coex_hamt_lookup_string")

        # hamt_contains_string
        hamt_contains_string_ty = ir.FunctionType(i1, [void_ptr, i64, string_ptr, i32])
        cg.hamt_contains_string = ir.Function(cg.module, hamt_contains_string_ty, name="coex_hamt_contains_string")

        # hamt_remove_string
        hamt_remove_string_ty = ir.FunctionType(void_ptr, [void_ptr, i64, string_ptr, i32, i32.as_pointer()])
        cg.hamt_remove_string = ir.Function(cg.module, hamt_remove_string_ty, name="coex_hamt_remove_string")

        # String-key map variants
        map_set_string_ty = ir.FunctionType(map_ptr, [map_ptr, string_ptr, i64])
        cg.map_set_string = ir.Function(cg.module, map_set_string_ty, name="coex_map_set_string")

        map_get_string_ty = ir.FunctionType(i64, [map_ptr, string_ptr])
        cg.map_get_string = ir.Function(cg.module, map_get_string_ty, name="coex_map_get_string")

        map_has_string_ty = ir.FunctionType(i1, [map_ptr, string_ptr])
        cg.map_has_string = ir.Function(cg.module, map_has_string_ty, name="coex_map_has_string")

        map_remove_string_ty = ir.FunctionType(map_ptr, [map_ptr, string_ptr])
        cg.map_remove_string = ir.Function(cg.module, map_remove_string_ty, name="coex_map_remove_string")

        # map_keys and map_values
        list_ptr = cg.list_struct.as_pointer()
        map_keys_ty = ir.FunctionType(list_ptr, [map_ptr])
        cg.map_keys = ir.Function(cg.module, map_keys_ty, name="coex_map_keys")

        map_values_ty = ir.FunctionType(list_ptr, [map_ptr])
        cg.map_values = ir.Function(cg.module, map_values_ty, name="coex_map_values")

        # Implement all HAMT and Map functions
        self._implement_hamt_popcount()
        self._implement_hamt_node_new()
        self._implement_hamt_leaf_new()
        self._implement_hamt_lookup()
        self._implement_hamt_contains()
        self._implement_hamt_insert()
        self._implement_hamt_remove()
        self._implement_hamt_collect_keys()
        self._implement_hamt_collect_values()
        self._implement_hamt_lookup_string()
        self._implement_hamt_contains_string()
        self._implement_hamt_insert_string()
        self._implement_hamt_remove_string()
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
        self._register_map_methods()

    # ========================================================================
    # HAMT Helper Function Implementations
    # ========================================================================

    def _implement_hamt_popcount(self):
        """Count the number of 1 bits in a 32-bit integer (population count)."""
        cg = self.cg
        func = cg.hamt_popcount
        func.args[0].name = "x"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        x = func.args[0]
        i32 = ir.IntType(32)

        # Brian Kernighan's algorithm
        count_ptr = builder.alloca(i32, name="count")
        x_ptr = builder.alloca(i32, name="x_ptr")
        builder.store(ir.Constant(i32, 0), count_ptr)
        builder.store(x, x_ptr)

        loop_cond = func.append_basic_block("loop_cond")
        loop_body = func.append_basic_block("loop_body")
        loop_done = func.append_basic_block("loop_done")

        builder.branch(loop_cond)

        builder.position_at_end(loop_cond)
        curr_x = builder.load(x_ptr)
        is_nonzero = builder.icmp_unsigned("!=", curr_x, ir.Constant(i32, 0))
        builder.cbranch(is_nonzero, loop_body, loop_done)

        builder.position_at_end(loop_body)
        x_minus_1 = builder.sub(curr_x, ir.Constant(i32, 1))
        new_x = builder.and_(curr_x, x_minus_1)
        builder.store(new_x, x_ptr)
        curr_count = builder.load(count_ptr)
        new_count = builder.add(curr_count, ir.Constant(i32, 1))
        builder.store(new_count, count_ptr)
        builder.branch(loop_cond)

        builder.position_at_end(loop_done)
        final_count = builder.load(count_ptr)
        builder.ret(final_count)

    def _implement_hamt_node_new(self):
        """Create a new HAMT internal node with given bitmap and child count."""
        cg = self.cg
        func = cg.hamt_node_new
        func.args[0].name = "bitmap"
        func.args[1].name = "child_count"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        bitmap = func.args[0]
        child_count = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate HAMTNode struct (16 bytes with padding)
        node_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_HAMT_NODE if hasattr(cg.gc, 'TYPE_HAMT_NODE') else 0)
        raw_ptr = cg.gc.alloc_with_deref(builder, node_size, type_id)
        node_ptr = builder.bitcast(raw_ptr, cg.hamt_node_struct.as_pointer())

        # Store bitmap
        bitmap_field = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(bitmap, bitmap_field)

        # Allocate children array
        child_count_64 = builder.zext(child_count, i64)
        children_size = builder.mul(child_count_64, ir.Constant(i64, 8))
        i64_ptr = ir.IntType(64).as_pointer()

        zero_children = builder.icmp_unsigned("==", child_count, ir.Constant(i32, 0))
        with builder.if_else(zero_children) as (then, otherwise):
            with then:
                children_field = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
                null_ptr = ir.Constant(i64_ptr, None)
                builder.store(null_ptr, children_field)
            with otherwise:
                children_raw = cg.gc.alloc_with_deref(builder, children_size, ir.Constant(i32, 0))
                children_ptr = builder.bitcast(children_raw, i64_ptr)
                children_field2 = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
                builder.store(children_ptr, children_field2)

        builder.ret(node_ptr)

    def _implement_hamt_leaf_new(self):
        """Create a new HAMT leaf node with hash, key, and value."""
        cg = self.cg
        func = cg.hamt_leaf_new
        func.args[0].name = "hash"
        func.args[1].name = "key"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        hash_val = func.args[0]
        key = func.args[1]
        value = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate HAMTLeaf struct (24 bytes)
        leaf_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_HAMT_LEAF if hasattr(cg.gc, 'TYPE_HAMT_LEAF') else 0)
        raw_ptr = cg.gc.alloc_with_deref(builder, leaf_size, type_id)
        leaf_ptr = builder.bitcast(raw_ptr, cg.hamt_leaf_struct.as_pointer())

        # Store fields
        hash_field = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(hash_val, hash_field)

        key_field = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(key, key_field)

        value_field = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(value, value_field)

        # Tag the pointer (bit 0 = 1 for leaf)
        void_ptr = ir.IntType(8).as_pointer()
        leaf_void = builder.bitcast(leaf_ptr, void_ptr)
        leaf_int = builder.ptrtoint(leaf_void, i64)
        tagged_int = builder.or_(leaf_int, ir.Constant(i64, 1))
        tagged_ptr = builder.inttoptr(tagged_int, cg.hamt_leaf_struct.as_pointer())
        builder.ret(tagged_ptr)

    def _implement_hamt_lookup(self):
        """Look up a value in the HAMT by hash and key."""
        cg = self.cg
        func = cg.hamt_lookup
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"

        entry = func.append_basic_block("entry")
        check_tag = func.append_basic_block("check_tag")
        is_leaf = func.append_basic_block("is_leaf")
        is_node = func.append_basic_block("is_node")
        bit_set = func.append_basic_block("bit_set")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Check if node is null
        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))
        builder.cbranch(is_null, not_found, check_tag)

        # Check low bit for leaf/node
        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))
        builder.cbranch(is_leaf_tag, is_leaf, is_node)

        # Leaf case
        builder.position_at_end(is_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        leaf_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        leaf_key = builder.load(leaf_key_ptr)
        keys_match = builder.icmp_signed("==", leaf_key, key)

        found_block = func.append_basic_block("found_leaf")
        builder.cbranch(keys_match, found_block, not_found)

        builder.position_at_end(found_block)
        leaf_value_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        leaf_value = builder.load(leaf_value_ptr)
        builder.ret(leaf_value)

        # Node case
        builder.position_at_end(is_node)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        hash_bits = builder.trunc(builder.and_(hash_shifted, ir.Constant(i64, 0x1F)), i32)

        bit_mask = builder.shl(ir.Constant(i32, 1), hash_bits)
        bit_and = builder.and_(bitmap, bit_mask)
        bit_is_set = builder.icmp_unsigned("!=", bit_and, ir.Constant(i32, 0))
        builder.cbranch(bit_is_set, bit_set, not_found)

        builder.position_at_end(bit_set)
        lower_mask = builder.sub(bit_mask, ir.Constant(i32, 1))
        lower_bits = builder.and_(bitmap, lower_mask)
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])

        children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [child_idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        new_shift = builder.add(shift, ir.Constant(i32, 5))
        result = builder.call(cg.hamt_lookup, [child_ptr, hash_val, key, new_shift])
        builder.ret(result)

        builder.position_at_end(not_found)
        builder.ret(ir.Constant(i64, 0))

    def _implement_hamt_contains(self):
        """Check if a key exists in the HAMT."""
        cg = self.cg
        func = cg.hamt_contains
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"

        entry = func.append_basic_block("entry")
        check_tag = func.append_basic_block("check_tag")
        is_leaf = func.append_basic_block("is_leaf")
        is_node = func.append_basic_block("is_node")
        bit_set = func.append_basic_block("bit_set")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        void_ptr = ir.IntType(8).as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))
        builder.cbranch(is_null, not_found, check_tag)

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))
        builder.cbranch(is_leaf_tag, is_leaf, is_node)

        builder.position_at_end(is_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        leaf_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        leaf_key = builder.load(leaf_key_ptr)
        keys_match = builder.icmp_signed("==", leaf_key, key)
        builder.ret(keys_match)

        builder.position_at_end(is_node)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        hash_bits = builder.trunc(builder.and_(hash_shifted, ir.Constant(i64, 0x1F)), i32)

        bit_mask = builder.shl(ir.Constant(i32, 1), hash_bits)
        bit_and = builder.and_(bitmap, bit_mask)
        bit_is_set = builder.icmp_unsigned("!=", bit_and, ir.Constant(i32, 0))
        builder.cbranch(bit_is_set, bit_set, not_found)

        builder.position_at_end(bit_set)
        lower_mask = builder.sub(bit_mask, ir.Constant(i32, 1))
        lower_bits = builder.and_(bitmap, lower_mask)
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])

        children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [child_idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        new_shift = builder.add(shift, ir.Constant(i32, 5))
        result = builder.call(cg.hamt_contains, [child_ptr, hash_val, key, new_shift])
        builder.ret(result)

        builder.position_at_end(not_found)
        builder.ret(ir.Constant(i1, 0))

    def _implement_hamt_insert(self):
        """Insert a key-value pair into the HAMT, returning a new root."""
        cg = self.cg
        func = cg.hamt_insert
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "value"
        func.args[4].name = "shift"
        func.args[5].name = "added"

        entry = func.append_basic_block("entry")
        create_leaf_null = func.append_basic_block("create_leaf_null")
        check_tag = func.append_basic_block("check_tag")
        is_leaf = func.append_basic_block("is_leaf")
        is_internal_node = func.append_basic_block("is_internal_node")
        bit_exists = func.append_basic_block("bit_exists")
        bit_not_exists = func.append_basic_block("bit_not_exists")

        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        value = func.args[3]
        shift = func.args[4]
        added_ptr = func.args[5]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Case 1: Node is null - create new leaf
        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))
        builder.cbranch(is_null, create_leaf_null, check_tag)

        builder.position_at_end(create_leaf_null)
        new_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key, value])
        builder.store(ir.Constant(i32, 1), added_ptr)
        new_leaf_void = builder.bitcast(new_leaf, void_ptr)
        builder.ret(new_leaf_void)

        # Check pointer tag
        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))
        builder.cbranch(is_leaf_tag, is_leaf, is_internal_node)

        # Handle leaf case
        builder.position_at_end(is_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())

        leaf_hash_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        leaf_hash = builder.load(leaf_hash_ptr)
        leaf_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        leaf_key = builder.load(leaf_key_ptr)

        same_key = builder.icmp_signed("==", leaf_key, key)

        update_leaf = func.append_basic_block("update_leaf")
        expand_to_node = func.append_basic_block("expand_to_node")
        builder.cbranch(same_key, update_leaf, expand_to_node)

        # Update existing leaf
        builder.position_at_end(update_leaf)
        updated_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key, value])
        builder.store(ir.Constant(i32, 0), added_ptr)
        updated_leaf_void = builder.bitcast(updated_leaf, void_ptr)
        builder.ret(updated_leaf_void)

        # Expand to node (different keys)
        builder.position_at_end(expand_to_node)
        shift_64 = builder.zext(shift, i64)
        old_hash_shifted = builder.lshr(leaf_hash, shift_64)
        old_hash_bits = builder.trunc(builder.and_(old_hash_shifted, ir.Constant(i64, 0x1F)), i32)

        new_hash_shifted = builder.lshr(hash_val, shift_64)
        new_hash_bits = builder.trunc(builder.and_(new_hash_shifted, ir.Constant(i64, 0x1F)), i32)

        same_bits = builder.icmp_unsigned("==", old_hash_bits, new_hash_bits)

        recurse_deeper = func.append_basic_block("recurse_deeper")
        create_split_node = func.append_basic_block("create_split_node")
        builder.cbranch(same_bits, recurse_deeper, create_split_node)

        # Same hash bits - recurse deeper
        builder.position_at_end(recurse_deeper)
        next_shift = builder.add(shift, ir.Constant(i32, 5))
        sub_result = builder.call(cg.hamt_insert, [node, hash_val, key, value, next_shift, added_ptr])

        single_bit_mask = builder.shl(ir.Constant(i32, 1), old_hash_bits)
        single_child_node = builder.call(cg.hamt_node_new, [single_bit_mask, ir.Constant(i32, 1)])
        single_children_ptr_ptr = builder.gep(single_child_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        single_children_ptr = builder.load(single_children_ptr_ptr)
        sub_result_i64 = builder.ptrtoint(sub_result, i64)
        builder.store(sub_result_i64, builder.gep(single_children_ptr, [ir.Constant(i64, 0)]))
        single_child_node_void = builder.bitcast(single_child_node, void_ptr)
        builder.ret(single_child_node_void)

        # Different hash bits - create node with two children
        builder.position_at_end(create_split_node)
        new_leaf4 = builder.call(cg.hamt_leaf_new, [hash_val, key, value])
        builder.store(ir.Constant(i32, 1), added_ptr)

        old_bit_mask = builder.shl(ir.Constant(i32, 1), old_hash_bits)
        new_bit_mask = builder.shl(ir.Constant(i32, 1), new_hash_bits)
        combined_bitmap = builder.or_(old_bit_mask, new_bit_mask)

        split_node = builder.call(cg.hamt_node_new, [combined_bitmap, ir.Constant(i32, 2)])
        split_children_ptr_ptr = builder.gep(split_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        split_children_ptr = builder.load(split_children_ptr_ptr)

        old_lower = builder.icmp_unsigned("<", old_hash_bits, new_hash_bits)
        old_idx = builder.select(old_lower, ir.Constant(i32, 0), ir.Constant(i32, 1))
        new_idx = builder.select(old_lower, ir.Constant(i32, 1), ir.Constant(i32, 0))

        old_idx_64 = builder.zext(old_idx, i64)
        new_idx_64 = builder.zext(new_idx, i64)

        old_child_ptr = builder.gep(split_children_ptr, [old_idx_64])
        new_child_ptr = builder.gep(split_children_ptr, [new_idx_64])

        new_leaf4_void = builder.bitcast(new_leaf4, void_ptr)
        node_i64 = builder.ptrtoint(node, i64)
        new_leaf4_i64 = builder.ptrtoint(new_leaf4_void, i64)
        builder.store(node_i64, old_child_ptr)
        builder.store(new_leaf4_i64, new_child_ptr)

        split_node_void = builder.bitcast(split_node, void_ptr)
        builder.ret(split_node_void)

        # Handle internal node case
        builder.position_at_end(is_internal_node)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        shift_64_2 = builder.zext(shift, i64)
        hash_shifted_2 = builder.lshr(hash_val, shift_64_2)
        hash_bits_2 = builder.trunc(builder.and_(hash_shifted_2, ir.Constant(i64, 0x1F)), i32)

        bit_mask_2 = builder.shl(ir.Constant(i32, 1), hash_bits_2)
        bit_and_2 = builder.and_(bitmap, bit_mask_2)
        bit_is_set_2 = builder.icmp_unsigned("!=", bit_and_2, ir.Constant(i32, 0))
        builder.cbranch(bit_is_set_2, bit_exists, bit_not_exists)

        # Bit exists - update existing child
        builder.position_at_end(bit_exists)
        lower_mask_2 = builder.sub(bit_mask_2, ir.Constant(i32, 1))
        lower_bits_2 = builder.and_(bitmap, lower_mask_2)
        child_idx_2 = builder.call(cg.hamt_popcount, [lower_bits_2])
        old_count_2 = builder.call(cg.hamt_popcount, [bitmap])

        children_ptr_ptr_2 = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr_2 = builder.load(children_ptr_ptr_2)
        child_idx_64_2 = builder.zext(child_idx_2, i64)
        child_ptr_ptr_2 = builder.gep(children_ptr_2, [child_idx_64_2])
        old_child_handle = builder.load(child_ptr_ptr_2)
        old_child = builder.inttoptr(old_child_handle, void_ptr)

        next_shift_2 = builder.add(shift, ir.Constant(i32, 5))
        new_child = builder.call(cg.hamt_insert, [old_child, hash_val, key, value, next_shift_2, added_ptr])

        new_node = builder.call(cg.hamt_node_new, [bitmap, old_count_2])
        new_children_ptr_ptr = builder.gep(new_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        new_children_ptr = builder.load(new_children_ptr_ptr)

        copy_idx_ptr = builder.alloca(i32, name="copy_idx")
        builder.store(ir.Constant(i32, 0), copy_idx_ptr)

        copy_loop = func.append_basic_block("copy_loop")
        copy_body = func.append_basic_block("copy_body")
        copy_done_exists = func.append_basic_block("copy_done_exists")

        builder.branch(copy_loop)

        builder.position_at_end(copy_loop)
        copy_idx = builder.load(copy_idx_ptr)
        copy_done_cond = builder.icmp_signed(">=", copy_idx, old_count_2)
        builder.cbranch(copy_done_cond, copy_done_exists, copy_body)

        builder.position_at_end(copy_body)
        copy_idx_64 = builder.zext(copy_idx, i64)
        src_ptr = builder.gep(children_ptr_2, [copy_idx_64])
        dst_ptr = builder.gep(new_children_ptr, [copy_idx_64])

        is_updated_child = builder.icmp_signed("==", copy_idx, child_idx_2)
        new_child_i64 = builder.ptrtoint(new_child, i64)
        child_to_store = builder.select(is_updated_child, new_child_i64, builder.load(src_ptr))
        builder.store(child_to_store, dst_ptr)

        next_copy_idx = builder.add(copy_idx, ir.Constant(i32, 1))
        builder.store(next_copy_idx, copy_idx_ptr)
        builder.branch(copy_loop)

        builder.position_at_end(copy_done_exists)
        new_node_void = builder.bitcast(new_node, void_ptr)
        builder.ret(new_node_void)

        # Bit doesn't exist - add new child
        builder.position_at_end(bit_not_exists)
        builder.store(ir.Constant(i32, 1), added_ptr)

        old_count_3 = builder.call(cg.hamt_popcount, [bitmap])
        new_count_3 = builder.add(old_count_3, ir.Constant(i32, 1))
        new_bitmap_3 = builder.or_(bitmap, bit_mask_2)

        new_node_3 = builder.call(cg.hamt_node_new, [new_bitmap_3, new_count_3])
        new_children_ptr_ptr_3 = builder.gep(new_node_3, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        new_children_ptr_3 = builder.load(new_children_ptr_ptr_3)

        lower_mask_3 = builder.sub(bit_mask_2, ir.Constant(i32, 1))
        lower_bits_3 = builder.and_(new_bitmap_3, lower_mask_3)
        insert_idx = builder.call(cg.hamt_popcount, [lower_bits_3])

        children_ptr_ptr_3 = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr_3 = builder.load(children_ptr_ptr_3)

        copy_idx_ptr_2 = builder.alloca(i32, name="copy_idx_2")
        builder.store(ir.Constant(i32, 0), copy_idx_ptr_2)

        copy_before = func.append_basic_block("copy_before")
        copy_before_body = func.append_basic_block("copy_before_body")
        insert_new = func.append_basic_block("insert_new")

        builder.branch(copy_before)

        builder.position_at_end(copy_before)
        copy_idx_2 = builder.load(copy_idx_ptr_2)
        copy_before_done = builder.icmp_signed(">=", copy_idx_2, insert_idx)
        builder.cbranch(copy_before_done, insert_new, copy_before_body)

        builder.position_at_end(copy_before_body)
        copy_idx_2_64 = builder.zext(copy_idx_2, i64)
        src_ptr_2 = builder.gep(children_ptr_3, [copy_idx_2_64])
        dst_ptr_2 = builder.gep(new_children_ptr_3, [copy_idx_2_64])
        builder.store(builder.load(src_ptr_2), dst_ptr_2)
        next_copy_idx_2 = builder.add(copy_idx_2, ir.Constant(i32, 1))
        builder.store(next_copy_idx_2, copy_idx_ptr_2)
        builder.branch(copy_before)

        # Insert new leaf
        builder.position_at_end(insert_new)
        new_leaf_5 = builder.call(cg.hamt_leaf_new, [hash_val, key, value])
        new_leaf_5_void = builder.bitcast(new_leaf_5, void_ptr)
        new_leaf_5_i64 = builder.ptrtoint(new_leaf_5_void, i64)
        insert_idx_64 = builder.zext(insert_idx, i64)
        insert_ptr = builder.gep(new_children_ptr_3, [insert_idx_64])
        builder.store(new_leaf_5_i64, insert_ptr)

        copy_after = func.append_basic_block("copy_after")
        copy_after_body = func.append_basic_block("copy_after_body")
        copy_done_not_exists = func.append_basic_block("copy_done_not_exists")

        builder.branch(copy_after)

        builder.position_at_end(copy_after)
        copy_idx_3 = builder.load(copy_idx_ptr_2)
        copy_after_done = builder.icmp_signed(">=", copy_idx_3, old_count_3)
        builder.cbranch(copy_after_done, copy_done_not_exists, copy_after_body)

        builder.position_at_end(copy_after_body)
        copy_idx_3_64 = builder.zext(copy_idx_3, i64)
        src_ptr_3 = builder.gep(children_ptr_3, [copy_idx_3_64])
        dst_idx_64 = builder.add(copy_idx_3_64, ir.Constant(i64, 1))
        dst_ptr_3 = builder.gep(new_children_ptr_3, [dst_idx_64])
        builder.store(builder.load(src_ptr_3), dst_ptr_3)
        next_copy_idx_3 = builder.add(copy_idx_3, ir.Constant(i32, 1))
        builder.store(next_copy_idx_3, copy_idx_ptr_2)
        builder.branch(copy_after)

        builder.position_at_end(copy_done_not_exists)
        new_node_3_void = builder.bitcast(new_node_3, void_ptr)
        builder.ret(new_node_3_void)

    def _implement_hamt_remove(self):
        """Remove a key from the HAMT, returning a new root."""
        cg = self.cg
        func = cg.hamt_remove
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"
        func.args[4].name = "removed"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        removed_ptr = func.args[4]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Check null
        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        not_found = func.append_basic_block("not_found")
        check_tag = func.append_basic_block("check_tag")

        builder.cbranch(is_null, not_found, check_tag)

        builder.position_at_end(not_found)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(node)

        # Check pointer tag
        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        is_leaf_block = func.append_basic_block("is_leaf_block")
        is_node_block = func.append_basic_block("is_node_block")
        builder.cbranch(is_leaf_tag, is_leaf_block, is_node_block)

        # Leaf case
        builder.position_at_end(is_leaf_block)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        leaf_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        leaf_key = builder.load(leaf_key_ptr)
        keys_match = builder.icmp_signed("==", leaf_key, key)

        remove_leaf = func.append_basic_block("remove_leaf")
        keep_leaf = func.append_basic_block("keep_leaf")
        builder.cbranch(keys_match, remove_leaf, keep_leaf)

        builder.position_at_end(remove_leaf)
        builder.store(ir.Constant(i32, 1), removed_ptr)
        builder.ret(ir.Constant(void_ptr, None))

        builder.position_at_end(keep_leaf)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(node)

        # Node case
        builder.position_at_end(is_node_block)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        hash_bits = builder.trunc(builder.and_(hash_shifted, ir.Constant(i64, 0x1F)), i32)

        bit_mask = builder.shl(ir.Constant(i32, 1), hash_bits)
        bit_and = builder.and_(bitmap, bit_mask)
        bit_is_set = builder.icmp_unsigned("!=", bit_and, ir.Constant(i32, 0))

        bit_not_set = func.append_basic_block("bit_not_set")
        recurse_remove = func.append_basic_block("recurse_remove")
        builder.cbranch(bit_is_set, recurse_remove, bit_not_set)

        builder.position_at_end(bit_not_set)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(node)

        builder.position_at_end(recurse_remove)
        lower_mask = builder.sub(bit_mask, ir.Constant(i32, 1))
        lower_bits = builder.and_(bitmap, lower_mask)
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])
        old_count = builder.call(cg.hamt_popcount, [bitmap])

        children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [child_idx_64])
        old_child_handle = builder.load(child_ptr_ptr)
        old_child = builder.inttoptr(old_child_handle, void_ptr)

        next_shift = builder.add(shift, ir.Constant(i32, 5))
        new_child = builder.call(cg.hamt_remove, [old_child, hash_val, key, next_shift, removed_ptr])

        was_removed = builder.load(removed_ptr)
        key_was_removed = builder.icmp_unsigned("!=", was_removed, ir.Constant(i32, 0))

        not_removed = func.append_basic_block("not_removed")
        check_collapse = func.append_basic_block("check_collapse")
        builder.cbranch(key_was_removed, check_collapse, not_removed)

        builder.position_at_end(not_removed)
        builder.ret(node)

        # Check if child became null
        builder.position_at_end(check_collapse)
        child_is_null = builder.icmp_unsigned("==", new_child, ir.Constant(void_ptr, None))

        remove_child = func.append_basic_block("remove_child")
        keep_child = func.append_basic_block("keep_child")
        builder.cbranch(child_is_null, remove_child, keep_child)

        # Remove child from node
        builder.position_at_end(remove_child)
        new_count = builder.sub(old_count, ir.Constant(i32, 1))
        new_bitmap = builder.xor(bitmap, bit_mask)

        node_empty = builder.icmp_unsigned("==", new_count, ir.Constant(i32, 0))

        return_null = func.append_basic_block("return_null")
        create_smaller_node = func.append_basic_block("create_smaller_node")
        builder.cbranch(node_empty, return_null, create_smaller_node)

        builder.position_at_end(return_null)
        builder.ret(ir.Constant(void_ptr, None))

        builder.position_at_end(create_smaller_node)
        only_one = builder.icmp_unsigned("==", new_count, ir.Constant(i32, 1))

        try_collapse = func.append_basic_block("try_collapse")
        no_collapse = func.append_basic_block("no_collapse")
        builder.cbranch(only_one, try_collapse, no_collapse)

        builder.position_at_end(try_collapse)
        builder.branch(no_collapse)

        builder.position_at_end(no_collapse)
        smaller_node = builder.call(cg.hamt_node_new, [new_bitmap, new_count])
        smaller_children_ptr_ptr = builder.gep(smaller_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        smaller_children_ptr = builder.load(smaller_children_ptr_ptr)

        src_idx_ptr = builder.alloca(i32, name="src_idx")
        dst_idx_ptr = builder.alloca(i32, name="dst_idx")
        builder.store(ir.Constant(i32, 0), src_idx_ptr)
        builder.store(ir.Constant(i32, 0), dst_idx_ptr)

        copy_loop_remove = func.append_basic_block("copy_loop_remove")
        copy_body_remove = func.append_basic_block("copy_body_remove")
        copy_done_remove = func.append_basic_block("copy_done_remove")

        builder.branch(copy_loop_remove)

        builder.position_at_end(copy_loop_remove)
        src_idx = builder.load(src_idx_ptr)
        loop_done = builder.icmp_signed(">=", src_idx, old_count)
        builder.cbranch(loop_done, copy_done_remove, copy_body_remove)

        builder.position_at_end(copy_body_remove)
        is_removed_child = builder.icmp_signed("==", src_idx, child_idx)

        skip_block = func.append_basic_block("skip_block")
        copy_block = func.append_basic_block("copy_block")
        builder.cbranch(is_removed_child, skip_block, copy_block)

        builder.position_at_end(skip_block)
        next_src = builder.add(src_idx, ir.Constant(i32, 1))
        builder.store(next_src, src_idx_ptr)
        builder.branch(copy_loop_remove)

        builder.position_at_end(copy_block)
        src_idx_64 = builder.zext(src_idx, i64)
        dst_idx = builder.load(dst_idx_ptr)
        dst_idx_64 = builder.zext(dst_idx, i64)
        src_child_ptr = builder.gep(children_ptr, [src_idx_64])
        dst_child_ptr = builder.gep(smaller_children_ptr, [dst_idx_64])
        builder.store(builder.load(src_child_ptr), dst_child_ptr)

        next_src_2 = builder.add(src_idx, ir.Constant(i32, 1))
        next_dst = builder.add(dst_idx, ir.Constant(i32, 1))
        builder.store(next_src_2, src_idx_ptr)
        builder.store(next_dst, dst_idx_ptr)
        builder.branch(copy_loop_remove)

        builder.position_at_end(copy_done_remove)
        smaller_void = builder.bitcast(smaller_node, void_ptr)
        builder.ret(smaller_void)

        # Keep child (just update it)
        builder.position_at_end(keep_child)
        updated_node = builder.call(cg.hamt_node_new, [bitmap, old_count])
        updated_children_ptr_ptr = builder.gep(updated_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        updated_children_ptr = builder.load(updated_children_ptr_ptr)

        copy_idx_ptr_3 = builder.alloca(i32, name="copy_idx_3")
        builder.store(ir.Constant(i32, 0), copy_idx_ptr_3)

        copy_loop_keep = func.append_basic_block("copy_loop_keep")
        copy_body_keep = func.append_basic_block("copy_body_keep")
        copy_done_keep = func.append_basic_block("copy_done_keep")

        builder.branch(copy_loop_keep)

        builder.position_at_end(copy_loop_keep)
        copy_idx_4 = builder.load(copy_idx_ptr_3)
        loop_done_2 = builder.icmp_signed(">=", copy_idx_4, old_count)
        builder.cbranch(loop_done_2, copy_done_keep, copy_body_keep)

        builder.position_at_end(copy_body_keep)
        copy_idx_4_64 = builder.zext(copy_idx_4, i64)
        src_ptr_4 = builder.gep(children_ptr, [copy_idx_4_64])
        dst_ptr_4 = builder.gep(updated_children_ptr, [copy_idx_4_64])
        is_updated = builder.icmp_signed("==", copy_idx_4, child_idx)
        new_child_i64 = builder.ptrtoint(new_child, i64)
        to_store = builder.select(is_updated, new_child_i64, builder.load(src_ptr_4))
        builder.store(to_store, dst_ptr_4)

        next_copy_4 = builder.add(copy_idx_4, ir.Constant(i32, 1))
        builder.store(next_copy_4, copy_idx_ptr_3)
        builder.branch(copy_loop_keep)

        builder.position_at_end(copy_done_keep)
        updated_void = builder.bitcast(updated_node, void_ptr)
        builder.ret(updated_void)

    def _implement_hamt_collect_keys(self):
        """Collect all keys from the HAMT into a list."""
        cg = self.cg
        func = cg.hamt_collect_keys
        func.args[0].name = "node"
        func.args[1].name = "list"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        list_ptr = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        return_unchanged = func.append_basic_block("return_unchanged")
        check_tag = func.append_basic_block("check_tag")
        builder.cbranch(is_null, return_unchanged, check_tag)

        builder.position_at_end(return_unchanged)
        builder.ret(list_ptr)

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Leaf - add key to list
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        key = builder.load(key_ptr)

        temp = builder.alloca(i64, name="temp_key")
        builder.store(key, temp)
        temp_i8 = builder.bitcast(temp, ir.IntType(8).as_pointer())

        elem_size = ir.Constant(i64, 8)
        new_list = builder.call(cg.list_append, [list_ptr, temp_i8, elem_size])
        builder.ret(new_list)

        # Node - recurse through children
        builder.position_at_end(handle_node)
        as_node = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)
        popcount = builder.call(cg.hamt_popcount, [bitmap])

        children_ptr_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)

        result_ptr = builder.alloca(cg.list_struct.as_pointer(), name="result")
        builder.store(list_ptr, result_ptr)

        idx_ptr = builder.alloca(i32, name="idx")
        builder.store(ir.Constant(i32, 0), idx_ptr)

        loop_cond = func.append_basic_block("loop_cond")
        loop_body = func.append_basic_block("loop_body")
        loop_done = func.append_basic_block("loop_done")

        builder.branch(loop_cond)

        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, popcount)
        builder.cbranch(done, loop_done, loop_body)

        builder.position_at_end(loop_body)
        idx_64 = builder.zext(idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        current_list = builder.load(result_ptr)
        updated_list = builder.call(cg.hamt_collect_keys, [child_ptr, current_list])
        builder.store(updated_list, result_ptr)

        next_idx = builder.add(idx, ir.Constant(i32, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_cond)

        builder.position_at_end(loop_done)
        final_list = builder.load(result_ptr)
        builder.ret(final_list)

    def _implement_hamt_collect_values(self):
        """Collect all values from the HAMT into a list."""
        cg = self.cg
        func = cg.hamt_collect_values
        func.args[0].name = "node"
        func.args[1].name = "list"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        list_ptr = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        return_unchanged = func.append_basic_block("return_unchanged")
        check_tag = func.append_basic_block("check_tag")
        builder.cbranch(is_null, return_unchanged, check_tag)

        builder.position_at_end(return_unchanged)
        builder.ret(list_ptr)

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Leaf - add value to list (index 2)
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        value_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        value = builder.load(value_ptr)

        temp = builder.alloca(i64, name="temp_value")
        builder.store(value, temp)
        temp_i8 = builder.bitcast(temp, ir.IntType(8).as_pointer())

        elem_size = ir.Constant(i64, 8)
        new_list = builder.call(cg.list_append, [list_ptr, temp_i8, elem_size])
        builder.ret(new_list)

        # Node - recurse
        builder.position_at_end(handle_node)
        as_node = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)
        popcount = builder.call(cg.hamt_popcount, [bitmap])

        children_ptr_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)

        result_ptr = builder.alloca(cg.list_struct.as_pointer(), name="result")
        builder.store(list_ptr, result_ptr)

        idx_ptr = builder.alloca(i32, name="idx")
        builder.store(ir.Constant(i32, 0), idx_ptr)

        loop_cond = func.append_basic_block("loop_cond")
        loop_body = func.append_basic_block("loop_body")
        loop_done = func.append_basic_block("loop_done")

        builder.branch(loop_cond)

        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, popcount)
        builder.cbranch(done, loop_done, loop_body)

        builder.position_at_end(loop_body)
        idx_64 = builder.zext(idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        current_list = builder.load(result_ptr)
        updated_list = builder.call(cg.hamt_collect_values, [child_ptr, current_list])
        builder.store(updated_list, result_ptr)

        next_idx = builder.add(idx, ir.Constant(i32, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_cond)

        builder.position_at_end(loop_done)
        final_list = builder.load(result_ptr)
        builder.ret(final_list)

    def _implement_hamt_lookup_string(self):
        """Look up a string key in the HAMT. Uses string_eq for comparison."""
        cg = self.cg
        func = cg.hamt_lookup_string
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()
        string_ptr_type = cg.string_struct.as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        return_zero = func.append_basic_block("return_zero")
        check_tag = func.append_basic_block("check_tag")
        builder.cbranch(is_null, return_zero, check_tag)

        builder.position_at_end(return_zero)
        builder.ret(ir.Constant(i64, 0))

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Leaf - compare keys
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())

        stored_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        stored_key_i64 = builder.load(stored_key_ptr)
        stored_key = builder.inttoptr(stored_key_i64, string_ptr_type)

        keys_match = builder.call(cg.string_eq, [stored_key, key])

        return_value = func.append_basic_block("return_value")
        return_not_found = func.append_basic_block("return_not_found")
        builder.cbranch(keys_match, return_value, return_not_found)

        builder.position_at_end(return_value)
        value_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        value = builder.load(value_ptr)
        builder.ret(value)

        builder.position_at_end(return_not_found)
        builder.ret(ir.Constant(i64, 0))

        # Node - descend
        builder.position_at_end(handle_node)
        as_node = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        five = ir.Constant(i32, 5)
        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        idx_in_level = builder.and_(builder.trunc(hash_shifted, i32), ir.Constant(i32, 31))

        bit_pos = builder.shl(ir.Constant(i32, 1), idx_in_level)
        has_child = builder.and_(bitmap, bit_pos)
        is_present = builder.icmp_unsigned("!=", has_child, ir.Constant(i32, 0))

        do_descend = func.append_basic_block("do_descend")
        not_present = func.append_basic_block("not_present")
        builder.cbranch(is_present, do_descend, not_present)

        builder.position_at_end(not_present)
        builder.ret(ir.Constant(i64, 0))

        builder.position_at_end(do_descend)
        lower_bits = builder.and_(bitmap, builder.sub(bit_pos, ir.Constant(i32, 1)))
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])

        children_ptr_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [child_idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        new_shift = builder.add(shift, five)
        result = builder.call(cg.hamt_lookup_string, [child_ptr, hash_val, key, new_shift])
        builder.ret(result)

    def _implement_hamt_contains_string(self):
        """Check if a string key exists in the HAMT."""
        cg = self.cg
        func = cg.hamt_contains_string
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        void_ptr = ir.IntType(8).as_pointer()
        string_ptr_type = cg.string_struct.as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        return_false = func.append_basic_block("return_false")
        check_tag = func.append_basic_block("check_tag")
        builder.cbranch(is_null, return_false, check_tag)

        builder.position_at_end(return_false)
        builder.ret(ir.Constant(i1, 0))

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Leaf - compare keys
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        stored_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        stored_key_i64 = builder.load(stored_key_ptr)
        stored_key = builder.inttoptr(stored_key_i64, string_ptr_type)
        keys_match = builder.call(cg.string_eq, [stored_key, key])
        builder.ret(keys_match)

        # Node - descend
        builder.position_at_end(handle_node)
        as_node = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        bitmap_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        five = ir.Constant(i32, 5)
        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        idx_in_level = builder.and_(builder.trunc(hash_shifted, i32), ir.Constant(i32, 31))

        bit_pos = builder.shl(ir.Constant(i32, 1), idx_in_level)
        has_child = builder.and_(bitmap, bit_pos)
        is_present = builder.icmp_unsigned("!=", has_child, ir.Constant(i32, 0))

        do_descend = func.append_basic_block("do_descend")
        not_present = func.append_basic_block("not_present")
        builder.cbranch(is_present, do_descend, not_present)

        builder.position_at_end(not_present)
        builder.ret(ir.Constant(i1, 0))

        builder.position_at_end(do_descend)
        lower_bits = builder.and_(bitmap, builder.sub(bit_pos, ir.Constant(i32, 1)))
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])

        children_ptr_ptr = builder.gep(as_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        child_ptr_ptr = builder.gep(children_ptr, [child_idx_64])
        child_handle = builder.load(child_ptr_ptr)
        child_ptr = builder.inttoptr(child_handle, void_ptr)

        new_shift = builder.add(shift, five)
        result = builder.call(cg.hamt_contains_string, [child_ptr, hash_val, key, new_shift])
        builder.ret(result)

    def _implement_hamt_insert_string(self):
        """Insert a string key-value pair into the HAMT."""
        cg = self.cg
        func = cg.hamt_insert_string
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "value"
        func.args[4].name = "shift"
        func.args[5].name = "added"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        value = func.args[3]
        shift = func.args[4]
        added_ptr = func.args[5]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()
        string_ptr_type = cg.string_struct.as_pointer()

        key_i64 = builder.ptrtoint(key, i64)

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        create_leaf_null = func.append_basic_block("create_leaf_null")
        check_tag = func.append_basic_block("check_tag")
        builder.cbranch(is_null, create_leaf_null, check_tag)

        builder.position_at_end(create_leaf_null)
        new_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key_i64, value])
        new_leaf_void = builder.bitcast(new_leaf, void_ptr)
        new_leaf_int = builder.ptrtoint(new_leaf_void, i64)
        new_leaf_tagged_int = builder.or_(new_leaf_int, ir.Constant(i64, 1))
        new_leaf_tagged = builder.inttoptr(new_leaf_tagged_int, void_ptr)
        builder.store(ir.Constant(i32, 1), added_ptr)
        builder.ret(new_leaf_tagged)

        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Handle leaf
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())

        stored_hash_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        stored_hash = builder.load(stored_hash_ptr)
        stored_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        stored_key_i64 = builder.load(stored_key_ptr)
        stored_key = builder.inttoptr(stored_key_i64, string_ptr_type)

        keys_match = builder.call(cg.string_eq, [stored_key, key])

        update_leaf = func.append_basic_block("update_leaf")
        split_leaf = func.append_basic_block("split_leaf")
        builder.cbranch(keys_match, update_leaf, split_leaf)

        # Same key - update value
        builder.position_at_end(update_leaf)
        updated_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key_i64, value])
        updated_leaf_void = builder.bitcast(updated_leaf, void_ptr)
        updated_leaf_int = builder.ptrtoint(updated_leaf_void, i64)
        updated_leaf_tagged_int = builder.or_(updated_leaf_int, ir.Constant(i64, 1))
        updated_leaf_tagged = builder.inttoptr(updated_leaf_tagged_int, void_ptr)
        builder.store(ir.Constant(i32, 0), added_ptr)
        builder.ret(updated_leaf_tagged)

        # Different key - split
        builder.position_at_end(split_leaf)
        builder.store(ir.Constant(i32, 1), added_ptr)

        five = ir.Constant(i32, 5)
        shift_64 = builder.zext(shift, i64)

        old_hash_shifted = builder.lshr(stored_hash, shift_64)
        old_idx = builder.and_(builder.trunc(old_hash_shifted, i32), ir.Constant(i32, 31))

        new_hash_shifted = builder.lshr(hash_val, shift_64)
        new_idx = builder.and_(builder.trunc(new_hash_shifted, i32), ir.Constant(i32, 31))

        same_idx = builder.icmp_unsigned("==", old_idx, new_idx)

        recurse_split = func.append_basic_block("recurse_split")
        create_node = func.append_basic_block("create_node")
        builder.cbranch(same_idx, recurse_split, create_node)

        # Same index - recurse
        builder.position_at_end(recurse_split)
        next_shift = builder.add(shift, five)
        sub_result = builder.call(cg.hamt_insert_string, [node, hash_val, key, value, next_shift, added_ptr])
        single_bit = builder.shl(ir.Constant(i32, 1), old_idx)
        single_child_node = builder.call(cg.hamt_node_new, [single_bit, ir.Constant(i32, 1)])
        children_ptr_ptr = builder.gep(single_child_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)
        sub_result_i64 = builder.ptrtoint(sub_result, i64)
        builder.store(sub_result_i64, builder.gep(children_ptr, [ir.Constant(i64, 0)]))
        single_node_void = builder.bitcast(single_child_node, void_ptr)
        builder.ret(single_node_void)

        # Different indices - create node with 2 children
        builder.position_at_end(create_node)
        old_bit = builder.shl(ir.Constant(i32, 1), old_idx)
        new_bit = builder.shl(ir.Constant(i32, 1), new_idx)
        combined_bitmap = builder.or_(old_bit, new_bit)

        split_node = builder.call(cg.hamt_node_new, [combined_bitmap, ir.Constant(i32, 2)])
        split_children_ptr_ptr = builder.gep(split_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        split_children = builder.load(split_children_ptr_ptr)

        new_key_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key_i64, value])
        new_key_leaf_void = builder.bitcast(new_key_leaf, void_ptr)
        new_key_leaf_int = builder.ptrtoint(new_key_leaf_void, i64)
        new_key_leaf_tagged_int = builder.or_(new_key_leaf_int, ir.Constant(i64, 1))
        new_key_leaf_tagged = builder.inttoptr(new_key_leaf_tagged_int, void_ptr)

        old_lower = builder.and_(combined_bitmap, builder.sub(old_bit, ir.Constant(i32, 1)))
        old_pos = builder.call(cg.hamt_popcount, [old_lower])
        old_pos_64 = builder.zext(old_pos, i64)
        new_lower = builder.and_(combined_bitmap, builder.sub(new_bit, ir.Constant(i32, 1)))
        new_pos = builder.call(cg.hamt_popcount, [new_lower])
        new_pos_64 = builder.zext(new_pos, i64)

        node_i64 = builder.ptrtoint(node, i64)
        new_key_leaf_i64 = builder.ptrtoint(new_key_leaf_tagged, i64)
        builder.store(node_i64, builder.gep(split_children, [old_pos_64]))
        builder.store(new_key_leaf_i64, builder.gep(split_children, [new_pos_64]))

        split_node_void = builder.bitcast(split_node, void_ptr)
        builder.ret(split_node_void)

        # Handle internal node
        builder.position_at_end(handle_node)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())
        n_bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        n_bitmap = builder.load(n_bitmap_ptr)

        n_shift_64 = builder.zext(shift, i64)
        n_hash_shifted = builder.lshr(hash_val, n_shift_64)
        n_idx = builder.and_(builder.trunc(n_hash_shifted, i32), ir.Constant(i32, 31))
        n_bit_pos = builder.shl(ir.Constant(i32, 1), n_idx)

        n_has_child = builder.and_(n_bitmap, n_bit_pos)
        n_is_present = builder.icmp_unsigned("!=", n_has_child, ir.Constant(i32, 0))

        descend_existing = func.append_basic_block("descend_existing")
        add_new_child = func.append_basic_block("add_new_child")
        builder.cbranch(n_is_present, descend_existing, add_new_child)

        # Descend into existing child
        builder.position_at_end(descend_existing)
        e_lower_bits = builder.and_(n_bitmap, builder.sub(n_bit_pos, ir.Constant(i32, 1)))
        e_child_idx = builder.call(cg.hamt_popcount, [e_lower_bits])
        e_old_count = builder.call(cg.hamt_popcount, [n_bitmap])

        e_children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        e_children = builder.load(e_children_ptr_ptr)
        e_child_idx_64 = builder.zext(e_child_idx, i64)
        e_old_child_handle = builder.load(builder.gep(e_children, [e_child_idx_64]))
        e_old_child = builder.inttoptr(e_old_child_handle, void_ptr)

        e_next_shift = builder.add(shift, five)
        e_new_child = builder.call(cg.hamt_insert_string, [e_old_child, hash_val, key, value, e_next_shift, added_ptr])

        e_new_node = builder.call(cg.hamt_node_new, [n_bitmap, e_old_count])
        e_new_children_ptr_ptr = builder.gep(e_new_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        e_new_children = builder.load(e_new_children_ptr_ptr)

        e_i_ptr = builder.alloca(i32, name="e_i")
        builder.store(ir.Constant(i32, 0), e_i_ptr)

        e_loop_cond = func.append_basic_block("e_loop_cond")
        e_loop_body = func.append_basic_block("e_loop_body")
        e_loop_done = func.append_basic_block("e_loop_done")

        builder.branch(e_loop_cond)

        builder.position_at_end(e_loop_cond)
        e_i = builder.load(e_i_ptr)
        e_done = builder.icmp_signed(">=", e_i, e_old_count)
        builder.cbranch(e_done, e_loop_done, e_loop_body)

        builder.position_at_end(e_loop_body)
        e_is_updated = builder.icmp_unsigned("==", e_i, e_child_idx)
        e_i_64 = builder.zext(e_i, i64)
        e_old_val = builder.load(builder.gep(e_children, [e_i_64]))
        e_new_child_i64 = builder.ptrtoint(e_new_child, i64)
        e_copy_val = builder.select(e_is_updated, e_new_child_i64, e_old_val)
        builder.store(e_copy_val, builder.gep(e_new_children, [e_i_64]))

        e_next_i = builder.add(e_i, ir.Constant(i32, 1))
        builder.store(e_next_i, e_i_ptr)
        builder.branch(e_loop_cond)

        builder.position_at_end(e_loop_done)
        e_result = builder.bitcast(e_new_node, void_ptr)
        builder.ret(e_result)

        # Add new child to node
        builder.position_at_end(add_new_child)
        builder.store(ir.Constant(i32, 1), added_ptr)

        a_old_count = builder.call(cg.hamt_popcount, [n_bitmap])
        a_new_count = builder.add(a_old_count, ir.Constant(i32, 1))
        a_new_bitmap = builder.or_(n_bitmap, n_bit_pos)

        a_new_node = builder.call(cg.hamt_node_new, [a_new_bitmap, a_new_count])
        a_new_children_ptr_ptr = builder.gep(a_new_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        a_new_children = builder.load(a_new_children_ptr_ptr)

        a_lower_bits = builder.and_(a_new_bitmap, builder.sub(n_bit_pos, ir.Constant(i32, 1)))
        a_insert_idx = builder.call(cg.hamt_popcount, [a_lower_bits])

        a_new_leaf = builder.call(cg.hamt_leaf_new, [hash_val, key_i64, value])
        a_new_leaf_void = builder.bitcast(a_new_leaf, void_ptr)
        a_new_leaf_int = builder.ptrtoint(a_new_leaf_void, i64)
        a_new_leaf_tagged_int = builder.or_(a_new_leaf_int, ir.Constant(i64, 1))
        a_new_leaf_tagged = builder.inttoptr(a_new_leaf_tagged_int, void_ptr)

        a_old_children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        a_old_children = builder.load(a_old_children_ptr_ptr)

        a_src_i_ptr = builder.alloca(i32, name="a_src_i")
        a_dst_i_ptr = builder.alloca(i32, name="a_dst_i")
        builder.store(ir.Constant(i32, 0), a_src_i_ptr)
        builder.store(ir.Constant(i32, 0), a_dst_i_ptr)

        a_loop_cond = func.append_basic_block("a_loop_cond")
        a_loop_body = func.append_basic_block("a_loop_body")
        a_loop_done = func.append_basic_block("a_loop_done")

        builder.branch(a_loop_cond)

        builder.position_at_end(a_loop_cond)
        a_dst_i = builder.load(a_dst_i_ptr)
        a_dst_done = builder.icmp_signed(">=", a_dst_i, a_new_count)
        builder.cbranch(a_dst_done, a_loop_done, a_loop_body)

        builder.position_at_end(a_loop_body)
        a_is_insert = builder.icmp_unsigned("==", a_dst_i, a_insert_idx)
        a_dst_i_64 = builder.zext(a_dst_i, i64)

        insert_new_block = func.append_basic_block("insert_new_block")
        copy_old_block = func.append_basic_block("copy_old_block")
        after_insert = func.append_basic_block("after_insert")

        builder.cbranch(a_is_insert, insert_new_block, copy_old_block)

        builder.position_at_end(insert_new_block)
        a_new_leaf_i64 = builder.ptrtoint(a_new_leaf_tagged, i64)
        builder.store(a_new_leaf_i64, builder.gep(a_new_children, [a_dst_i_64]))
        builder.branch(after_insert)

        builder.position_at_end(copy_old_block)
        a_src_i = builder.load(a_src_i_ptr)
        a_src_i_64 = builder.zext(a_src_i, i64)
        a_old_val = builder.load(builder.gep(a_old_children, [a_src_i_64]))
        builder.store(a_old_val, builder.gep(a_new_children, [a_dst_i_64]))
        a_next_src = builder.add(a_src_i, ir.Constant(i32, 1))
        builder.store(a_next_src, a_src_i_ptr)
        builder.branch(after_insert)

        builder.position_at_end(after_insert)
        a_next_dst = builder.add(a_dst_i, ir.Constant(i32, 1))
        builder.store(a_next_dst, a_dst_i_ptr)
        builder.branch(a_loop_cond)

        builder.position_at_end(a_loop_done)
        a_result = builder.bitcast(a_new_node, void_ptr)
        builder.ret(a_result)

    def _implement_hamt_remove_string(self):
        """Remove a string key from the HAMT."""
        cg = self.cg
        func = cg.hamt_remove_string
        func.args[0].name = "node"
        func.args[1].name = "hash"
        func.args[2].name = "key"
        func.args[3].name = "shift"
        func.args[4].name = "removed"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        node = func.args[0]
        hash_val = func.args[1]
        key = func.args[2]
        shift = func.args[3]
        removed_ptr = func.args[4]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()
        string_ptr_type = cg.string_struct.as_pointer()

        is_null = builder.icmp_unsigned("==", node, ir.Constant(void_ptr, None))

        return_null = func.append_basic_block("return_null")
        check_type = func.append_basic_block("check_type")
        builder.cbranch(is_null, return_null, check_type)

        builder.position_at_end(return_null)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(ir.Constant(void_ptr, None))

        builder.position_at_end(check_type)
        ptr_as_int = builder.ptrtoint(node, i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(i64, 0))

        handle_leaf = func.append_basic_block("handle_leaf")
        handle_node = func.append_basic_block("handle_node")
        builder.cbranch(is_leaf_tag, handle_leaf, handle_node)

        # Handle leaf
        builder.position_at_end(handle_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(i64, -2))
        untagged_ptr = builder.inttoptr(untagged_int, void_ptr)
        leaf_ptr = builder.bitcast(untagged_ptr, cg.hamt_leaf_struct.as_pointer())
        stored_key_ptr = builder.gep(leaf_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        stored_key_i64 = builder.load(stored_key_ptr)
        stored_key = builder.inttoptr(stored_key_i64, string_ptr_type)

        keys_match = builder.call(cg.string_eq, [stored_key, key])

        remove_leaf = func.append_basic_block("remove_leaf")
        keep_leaf = func.append_basic_block("keep_leaf")
        builder.cbranch(keys_match, remove_leaf, keep_leaf)

        builder.position_at_end(remove_leaf)
        builder.store(ir.Constant(i32, 1), removed_ptr)
        builder.ret(ir.Constant(void_ptr, None))

        builder.position_at_end(keep_leaf)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(node)

        # Handle node
        builder.position_at_end(handle_node)
        node_ptr = builder.bitcast(node, cg.hamt_node_struct.as_pointer())

        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        five = ir.Constant(i32, 5)
        shift_64 = builder.zext(shift, i64)
        hash_shifted = builder.lshr(hash_val, shift_64)
        idx_in_level = builder.and_(builder.trunc(hash_shifted, i32), ir.Constant(i32, 31))

        bit_pos = builder.shl(ir.Constant(i32, 1), idx_in_level)
        has_child = builder.and_(bitmap, bit_pos)
        is_present = builder.icmp_unsigned("!=", has_child, ir.Constant(i32, 0))

        do_remove = func.append_basic_block("do_remove")
        not_present = func.append_basic_block("not_present")
        builder.cbranch(is_present, do_remove, not_present)

        builder.position_at_end(not_present)
        builder.store(ir.Constant(i32, 0), removed_ptr)
        builder.ret(node)

        builder.position_at_end(do_remove)
        lower_bits = builder.and_(bitmap, builder.sub(bit_pos, ir.Constant(i32, 1)))
        child_idx = builder.call(cg.hamt_popcount, [lower_bits])
        old_count = builder.call(cg.hamt_popcount, [bitmap])

        children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        children = builder.load(children_ptr_ptr)
        child_idx_64 = builder.zext(child_idx, i64)
        old_child_handle = builder.load(builder.gep(children, [child_idx_64]))
        old_child = builder.inttoptr(old_child_handle, void_ptr)

        next_shift = builder.add(shift, five)
        new_child = builder.call(cg.hamt_remove_string, [old_child, hash_val, key, next_shift, removed_ptr])

        was_removed = builder.load(removed_ptr)
        did_remove = builder.icmp_unsigned("!=", was_removed, ir.Constant(i32, 0))

        update_node = func.append_basic_block("update_node")
        return_unchanged = func.append_basic_block("return_unchanged")
        builder.cbranch(did_remove, update_node, return_unchanged)

        builder.position_at_end(return_unchanged)
        builder.ret(node)

        builder.position_at_end(update_node)
        new_child_null = builder.icmp_unsigned("==", new_child, ir.Constant(void_ptr, None))

        shrink_node = func.append_basic_block("shrink_node")
        replace_child = func.append_basic_block("replace_child")
        builder.cbranch(new_child_null, shrink_node, replace_child)

        # Shrink node
        builder.position_at_end(shrink_node)
        new_count = builder.sub(old_count, ir.Constant(i32, 1))
        is_empty = builder.icmp_unsigned("==", new_count, ir.Constant(i32, 0))

        return_null_node = func.append_basic_block("return_null_node")
        create_smaller = func.append_basic_block("create_smaller")
        builder.cbranch(is_empty, return_null_node, create_smaller)

        builder.position_at_end(return_null_node)
        builder.ret(ir.Constant(void_ptr, None))

        builder.position_at_end(create_smaller)
        new_bitmap = builder.and_(bitmap, builder.not_(bit_pos))
        smaller_node = builder.call(cg.hamt_node_new, [new_bitmap, new_count])
        smaller_children_ptr_ptr = builder.gep(smaller_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        smaller_children = builder.load(smaller_children_ptr_ptr)

        s_src_ptr = builder.alloca(i32, name="s_src")
        s_dst_ptr = builder.alloca(i32, name="s_dst")
        builder.store(ir.Constant(i32, 0), s_src_ptr)
        builder.store(ir.Constant(i32, 0), s_dst_ptr)

        s_loop_cond = func.append_basic_block("s_loop_cond")
        s_loop_body = func.append_basic_block("s_loop_body")
        s_loop_done = func.append_basic_block("s_loop_done")
        builder.branch(s_loop_cond)

        builder.position_at_end(s_loop_cond)
        s_src = builder.load(s_src_ptr)
        s_done = builder.icmp_signed(">=", s_src, old_count)
        builder.cbranch(s_done, s_loop_done, s_loop_body)

        builder.position_at_end(s_loop_body)
        s_skip = builder.icmp_unsigned("==", s_src, child_idx)
        s_src_64 = builder.zext(s_src, i64)

        s_do_skip = func.append_basic_block("s_do_skip")
        s_do_copy = func.append_basic_block("s_do_copy")
        s_after = func.append_basic_block("s_after")
        builder.cbranch(s_skip, s_do_skip, s_do_copy)

        builder.position_at_end(s_do_skip)
        builder.branch(s_after)

        builder.position_at_end(s_do_copy)
        s_dst = builder.load(s_dst_ptr)
        s_dst_64 = builder.zext(s_dst, i64)
        s_val = builder.load(builder.gep(children, [s_src_64]))
        builder.store(s_val, builder.gep(smaller_children, [s_dst_64]))
        s_next_dst = builder.add(s_dst, ir.Constant(i32, 1))
        builder.store(s_next_dst, s_dst_ptr)
        builder.branch(s_after)

        builder.position_at_end(s_after)
        s_next_src = builder.add(s_src, ir.Constant(i32, 1))
        builder.store(s_next_src, s_src_ptr)
        builder.branch(s_loop_cond)

        builder.position_at_end(s_loop_done)
        smaller_result = builder.bitcast(smaller_node, void_ptr)
        builder.ret(smaller_result)

        # Replace child
        builder.position_at_end(replace_child)
        updated_node = builder.call(cg.hamt_node_new, [bitmap, old_count])
        updated_children_ptr_ptr = builder.gep(updated_node, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        updated_children = builder.load(updated_children_ptr_ptr)

        u_i_ptr = builder.alloca(i32, name="u_i")
        builder.store(ir.Constant(i32, 0), u_i_ptr)

        u_loop_cond = func.append_basic_block("u_loop_cond")
        u_loop_body = func.append_basic_block("u_loop_body")
        u_loop_done = func.append_basic_block("u_loop_done")
        builder.branch(u_loop_cond)

        builder.position_at_end(u_loop_cond)
        u_i = builder.load(u_i_ptr)
        u_done = builder.icmp_signed(">=", u_i, old_count)
        builder.cbranch(u_done, u_loop_done, u_loop_body)

        builder.position_at_end(u_loop_body)
        u_is_updated = builder.icmp_unsigned("==", u_i, child_idx)
        u_i_64 = builder.zext(u_i, i64)
        u_old_val = builder.load(builder.gep(children, [u_i_64]))
        new_child_i64 = builder.ptrtoint(new_child, i64)
        u_copy_val = builder.select(u_is_updated, new_child_i64, u_old_val)
        builder.store(u_copy_val, builder.gep(updated_children, [u_i_64]))

        u_next_i = builder.add(u_i, ir.Constant(i32, 1))
        builder.store(u_next_i, u_i_ptr)
        builder.branch(u_loop_cond)

        builder.position_at_end(u_loop_done)
        updated_result = builder.bitcast(updated_node, void_ptr)
        builder.ret(updated_result)

    # ========================================================================
    # Map Method Implementations
    # ========================================================================

    def _implement_map_hash(self):
        """Implement integer hash function (splitmix64-based)."""
        cg = self.cg
        func = cg.map_hash
        func.args[0].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        key = func.args[0]

        # splitmix64 mixing function
        x = key
        x_shr30 = builder.lshr(x, ir.Constant(ir.IntType(64), 30))
        x = builder.xor(x, x_shr30)
        x = builder.mul(x, ir.Constant(ir.IntType(64), 0xbf58476d1ce4e5b9))
        x_shr27 = builder.lshr(x, ir.Constant(ir.IntType(64), 27))
        x = builder.xor(x, x_shr27)
        x = builder.mul(x, ir.Constant(ir.IntType(64), 0x94d049bb133111eb))
        x_shr31 = builder.lshr(x, ir.Constant(ir.IntType(64), 31))
        x = builder.xor(x, x_shr31)

        builder.ret(x)

    def _implement_map_new(self):
        """Create a new empty HAMT-based map with type flags."""
        cg = self.cg
        func = cg.map_new
        func.args[0].name = "flags"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        flags = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Map struct (24 bytes) via GC
        # All fields are i64 for consistent cross-platform layout
        # Fields: root (i64), len (i64), flags (i64)
        map_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_MAP)
        raw_ptr = cg.gc.alloc_with_deref(builder, map_size, type_id)
        map_ptr = builder.bitcast(raw_ptr, cg.map_struct.as_pointer())

        # Store root = 0 (null as i64) (field 0)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i64, 0), root_field)

        # Store len = 0 (field 1)
        len_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), len_field)

        # Store flags (field 2)
        flags_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(flags, flags_field)

        builder.ret(map_ptr)

    def _implement_map_set(self):
        """Return a NEW map with key-value pair set using HAMT.

        Uses structural sharing - only copies O(log n) nodes on the path.
        """
        cg = self.cg
        func = cg.map_set
        func.args[0].name = "old_map"
        func.args[1].name = "key"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_map = func.args[0]
        key = func.args[1]
        value = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute hash of key
        hash_val = builder.call(cg.map_hash, [key])

        # Get old root (stored as i64, convert to pointer for HAMT ops)
        root_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_field)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get old len
        len_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Get old flags
        flags_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_field)

        # Allocate added flag
        added_ptr = builder.alloca(i32, name="added")
        builder.store(ir.Constant(i32, 0), added_ptr)

        # Insert into HAMT
        new_root = builder.call(cg.hamt_insert, [old_root, hash_val, key, value, ir.Constant(i32, 0), added_ptr])

        # Create new Map with new root
        map_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_MAP)
        raw_ptr = cg.gc.alloc_with_deref(builder, map_size, type_id)
        new_map = builder.bitcast(raw_ptr, cg.map_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_field)

        # Update len if new key was added
        added = builder.load(added_ptr)
        added_bool = builder.icmp_unsigned("!=", added, ir.Constant(i32, 0))
        new_len = builder.select(added_bool,
                                  builder.add(old_len, ir.Constant(i64, 1)),
                                  old_len)
        new_len_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_field)

        # Copy flags from old map
        new_flags_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_field)

        builder.ret(new_map)

    def _implement_map_get(self):
        """Get value for key using HAMT lookup (returns 0 if not found)."""
        cg = self.cg
        func = cg.map_get
        func.args[0].name = "map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Get root (stored as i64, convert to pointer)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_field)
        root = builder.inttoptr(root_i64, void_ptr)

        # Lookup in HAMT
        result = builder.call(cg.hamt_lookup, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_map_has(self):
        """Check if key exists in map using HAMT."""
        cg = self.cg
        func = cg.map_has
        func.args[0].name = "map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Get root (stored as i64, convert to pointer)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_field)
        root = builder.inttoptr(root_i64, void_ptr)

        # Check in HAMT
        result = builder.call(cg.hamt_contains, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_map_remove(self):
        """Return a NEW map with key removed using HAMT.

        Uses structural sharing - only copies O(log n) nodes on the path.
        """
        cg = self.cg
        func = cg.map_remove
        func.args[0].name = "old_map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_map = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Get old root (stored as i64, convert to pointer)
        root_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_field)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get old len
        len_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Get old flags
        flags_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_field)

        # Allocate removed flag
        removed_ptr = builder.alloca(i32, name="removed")
        builder.store(ir.Constant(i32, 0), removed_ptr)

        # Remove from HAMT
        new_root = builder.call(cg.hamt_remove, [old_root, hash_val, key, ir.Constant(i32, 0), removed_ptr])

        # Create new Map with new root
        map_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_MAP)
        raw_ptr = cg.gc.alloc_with_deref(builder, map_size, type_id)
        new_map = builder.bitcast(raw_ptr, cg.map_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_field)

        # Update len if key was removed
        removed = builder.load(removed_ptr)
        removed_bool = builder.icmp_unsigned("!=", removed, ir.Constant(i32, 0))
        new_len = builder.select(removed_bool,
                                  builder.sub(old_len, ir.Constant(i64, 1)),
                                  old_len)
        new_len_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_field)

        # Copy flags from old map
        new_flags_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_field)

        builder.ret(new_map)

    def _implement_map_len(self):
        """Return number of entries in map."""
        cg = self.cg
        func = cg.map_len
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        i32 = ir.IntType(32)

        # len is field 1
        len_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        length = builder.load(len_field)
        builder.ret(length)

    def _implement_map_size(self):
        """Return approximate memory footprint of HAMT map in bytes.

        For HAMT: 16 (header) + estimated tree size based on len.
        Rough estimate: len * 32 bytes per entry (including tree overhead).
        """
        cg = self.cg
        func = cg.map_size
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get len field (field 1)
        len_ptr = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        length = builder.load(len_ptr)

        # Estimate: 16 (header) + len * 32 (entries + tree overhead)
        entry_size = builder.mul(length, ir.Constant(i64, 32))
        total_size = builder.add(ir.Constant(i64, 16), entry_size)

        builder.ret(total_size)

    def _implement_map_copy(self):
        """Implement map_copy: return the same pointer (identity function).

        With immutable heap semantics, maps don't need copying. Sharing the
        reference is equivalent to copying because no binding can observe
        mutations through another binding (map operations return new maps).

        GC keeps the shared map alive as long as it's reachable.
        """
        cg = self.cg
        func = cg.map_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Return the same pointer - no copy needed
        builder.ret(func.args[0])

    def _implement_map_set_string(self):
        """Set value for string key using HAMT, returning NEW map (value semantics)."""
        cg = self.cg
        func = cg.map_set_string
        func.args[0].name = "map"
        func.args[1].name = "key"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_map = func.args[0]
        key = func.args[1]  # String pointer
        value = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()
        map_ptr_type = cg.map_struct.as_pointer()

        # Compute string hash
        hash_val = builder.call(cg.string_hash, [key])

        # Get old root (stored as i64, convert to pointer), len, and flags
        old_root_ptr = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(old_root_ptr)
        old_root = builder.inttoptr(old_root_i64, void_ptr)
        old_len_ptr = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(old_len_ptr)
        old_flags_ptr = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(old_flags_ptr)

        # Insert into HAMT using string comparison
        added_ptr = builder.alloca(i32, name="added")
        builder.store(ir.Constant(i32, 0), added_ptr)
        new_root = builder.call(cg.hamt_insert_string, [old_root, hash_val, key, value, ir.Constant(i32, 0), added_ptr])

        # Create new Map struct
        map_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_MAP)
        raw_ptr = cg.gc.alloc_with_deref(builder, map_size, type_id)
        new_map = builder.bitcast(raw_ptr, map_ptr_type)

        # Store new root (convert pointer to i64)
        new_root_ptr = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_ptr)

        # Update len if key was added
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        new_len_ptr = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_ptr)

        # Copy flags from old map
        new_flags_ptr = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_ptr)

        builder.ret(new_map)

    def _implement_map_get_string(self):
        """Get value for string key using HAMT (returns 0 if not found)."""
        cg = self.cg
        func = cg.map_get_string
        func.args[0].name = "map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]  # String pointer
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute string hash
        hash_val = builder.call(cg.string_hash, [key])

        # Get root (stored as i64, convert to pointer)
        root_ptr = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Lookup in HAMT using string comparison
        result = builder.call(cg.hamt_lookup_string, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_map_has_string(self):
        """Check if string key exists in map using HAMT."""
        cg = self.cg
        func = cg.map_has_string
        func.args[0].name = "map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]  # String pointer
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute string hash
        hash_val = builder.call(cg.string_hash, [key])

        # Get root (stored as i64, convert to pointer)
        root_ptr = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Check existence in HAMT using string comparison
        result = builder.call(cg.hamt_contains_string, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_map_remove_string(self):
        """Return a NEW map with string key removed using HAMT."""
        cg = self.cg
        func = cg.map_remove_string
        func.args[0].name = "old_map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_map = func.args[0]
        key = func.args[1]  # String pointer
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Compute string hash
        hash_val = builder.call(cg.string_hash, [key])

        # Get old root (stored as i64, convert to pointer)
        root_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_field)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get old len
        len_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Get old flags
        flags_field = builder.gep(old_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_field)

        # Allocate removed flag
        removed_ptr = builder.alloca(i32, name="removed")
        builder.store(ir.Constant(i32, 0), removed_ptr)

        # Remove from HAMT using string comparison
        new_root = builder.call(cg.hamt_remove_string, [old_root, hash_val, key, ir.Constant(i32, 0), removed_ptr])

        # Create new Map with new root
        map_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_MAP)
        raw_ptr = cg.gc.alloc_with_deref(builder, map_size, type_id)
        new_map = builder.bitcast(raw_ptr, cg.map_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_field)

        # Update len if key was removed
        removed = builder.load(removed_ptr)
        removed_64 = builder.zext(removed, i64)
        new_len = builder.sub(old_len, removed_64)
        new_len_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_field)

        # Copy flags from old map
        new_flags_field = builder.gep(new_map, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_field)

        builder.ret(new_map)

    def _implement_map_keys(self):
        """Return a List of all keys in the map (as i64 values) using HAMT."""
        cg = self.cg
        func = cg.map_keys
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Create empty result list with 8-byte elements
        elem_size = ir.Constant(i64, 8)
        empty_list = builder.call(cg.list_new, [elem_size])

        # Get HAMT root (stored as i64, convert to pointer)
        root_ptr = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Collect all keys from HAMT into list
        result = builder.call(cg.hamt_collect_keys, [root, empty_list])
        builder.ret(result)

    def _implement_map_values(self):
        """Return a List of all values in the map (as i64 values) using HAMT."""
        cg = self.cg
        func = cg.map_values
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Create empty result list with 8-byte elements
        elem_size = ir.Constant(i64, 8)
        empty_list = builder.call(cg.list_new, [elem_size])

        # Get HAMT root (stored as i64, convert to pointer)
        root_ptr = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Collect all values from HAMT into list
        result = builder.call(cg.hamt_collect_values, [root, empty_list])
        builder.ret(result)

    def _register_map_methods(self):
        """Register Map as a type with methods."""
        cg = self.cg
        cg.type_registry["Map"] = cg.map_struct
        cg.type_fields["Map"] = []  # Internal structure, not user-accessible fields

        cg.type_methods["Map"] = {
            "get": "coex_map_get",
            "set": "coex_map_set",
            "has": "coex_map_has",
            "remove": "coex_map_remove",
            "len": "coex_map_len",
            "size": "coex_map_size",
            "keys": "coex_map_keys",
            "values": "coex_map_values",
        }

        cg.functions["coex_map_new"] = cg.map_new
        cg.functions["coex_map_get"] = cg.map_get
        cg.functions["coex_map_set"] = cg.map_set
        cg.functions["coex_map_has"] = cg.map_has
        cg.functions["coex_map_remove"] = cg.map_remove
        cg.functions["coex_map_len"] = cg.map_len
        cg.functions["coex_map_size"] = cg.map_size
        cg.functions["coex_map_copy"] = cg.map_copy
        cg.functions["coex_map_keys"] = cg.map_keys
        cg.functions["coex_map_values"] = cg.map_values

    # ========================================================================
    # Set Type Implementation
    # ========================================================================

    def create_set_type(self):
        """Create the Set type and helper functions.

        Set uses a hash table with linear probing (like Map, but no values).

        SetEntry layout:
            i64 key    - Key (int value or pointer cast to i64)
            i8  state  - 0=empty, 1=occupied, 2=deleted (tombstone)

        Set layout (HAMT-based):
            i8* root  - Root of HAMT tree (void pointer - can be null, leaf, or node)
            i64 len   - Number of elements in the set

        Uses the same HAMT infrastructure as Map with pointer tagging:
        - Bit 0 = 1 for leaf, 0 for node
        - Leaves store {hash, key, value} where value is always 1 for sets
        """
        cg = self.cg

        # SetEntry struct: { i64 key, i8 state } - kept for backward compatibility
        cg.set_entry_struct = ir.global_context.get_identified_type("struct.SetEntry")
        cg.set_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(8)    # state: 0=empty, 1=occupied, 2=deleted
        )

        # Set struct: { i64 root, i64 len, i64 flags } - HAMT-based like Map
        # All fields are i64 for consistent cross-platform layout (no padding ambiguity)
        # Root is stored as i64, converted with inttoptr/ptrtoint when used as pointer
        # flags: bit 0 = element is heap pointer (e.g., string)
        cg.set_struct = ir.global_context.get_identified_type("struct.Set")
        cg.set_struct.set_body(
            ir.IntType(64),              # root (pointer stored as i64)
            ir.IntType(64),              # len
            ir.IntType(64)               # flags (type info for GC)
        )

        set_ptr = cg.set_struct.as_pointer()
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # set_new(flags: i64) -> Set*
        # flags: bit 0 = element is ptr
        set_new_ty = ir.FunctionType(set_ptr, [i64])
        cg.set_new = ir.Function(cg.module, set_new_ty, name="coex_set_new")

        # set_add(set: Set*, key: i64) -> Set*
        # Returns a NEW set with the key added (value semantics)
        set_add_ty = ir.FunctionType(set_ptr, [set_ptr, i64])
        cg.set_add = ir.Function(cg.module, set_add_ty, name="coex_set_add")

        # set_has(set: Set*, key: i64) -> bool
        set_has_ty = ir.FunctionType(i1, [set_ptr, i64])
        cg.set_has = ir.Function(cg.module, set_has_ty, name="coex_set_has")

        # set_remove(set: Set*, key: i64) -> Set*
        # Returns a NEW set with element removed (value semantics)
        set_remove_ty = ir.FunctionType(set_ptr, [set_ptr, i64])
        cg.set_remove = ir.Function(cg.module, set_remove_ty, name="coex_set_remove")

        # set_len(set: Set*) -> i64
        set_len_ty = ir.FunctionType(i64, [set_ptr])
        cg.set_len = ir.Function(cg.module, set_len_ty, name="coex_set_len")

        # set_size(set: Set*) -> i64 (total memory footprint in bytes)
        set_size_ty = ir.FunctionType(i64, [set_ptr])
        cg.set_size = ir.Function(cg.module, set_size_ty, name="coex_set_size")

        # set_grow(set: Set*)  (internal resize function)
        set_grow_ty = ir.FunctionType(ir.VoidType(), [set_ptr])
        cg.set_grow = ir.Function(cg.module, set_grow_ty, name="coex_set_grow")

        # set_find_slot(set: Set*, key: i64) -> i64  (internal: find slot for key)
        set_find_slot_ty = ir.FunctionType(i64, [set_ptr, i64])
        cg.set_find_slot = ir.Function(cg.module, set_find_slot_ty, name="coex_set_find_slot")

        # set_copy(set: Set*) -> Set*  (deep copy for value semantics)
        set_copy_ty = ir.FunctionType(set_ptr, [set_ptr])
        cg.set_copy = ir.Function(cg.module, set_copy_ty, name="coex_set_copy")

        # set_to_list(set: Set*) -> List*  (for iteration - returns list of elements as i64)
        list_ptr = cg.list_struct.as_pointer()
        set_to_list_ty = ir.FunctionType(list_ptr, [set_ptr])
        cg.set_to_list = ir.Function(cg.module, set_to_list_ty, name="coex_set_to_list")

        # String-specific Set operations
        string_ptr = cg.string_struct.as_pointer()

        # set_find_slot_string(set: Set*, key: String*) -> i64  (internal)
        set_find_slot_string_ty = ir.FunctionType(i64, [set_ptr, string_ptr])
        cg.set_find_slot_string = ir.Function(cg.module, set_find_slot_string_ty, name="coex_set_find_slot_string")

        # set_has_string(set: Set*, key: String*) -> bool
        set_has_string_ty = ir.FunctionType(i1, [set_ptr, string_ptr])
        cg.set_has_string = ir.Function(cg.module, set_has_string_ty, name="coex_set_has_string")

        # set_add_string(set: Set*, key: String*) -> Set*
        set_add_string_ty = ir.FunctionType(set_ptr, [set_ptr, string_ptr])
        cg.set_add_string = ir.Function(cg.module, set_add_string_ty, name="coex_set_add_string")

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

    def _implement_set_new(self):
        """Implement set_new: allocate a new empty HAMT-based set with type flags."""
        cg = self.cg
        func = cg.set_new
        func.args[0].name = "flags"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        flags = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Set struct (24 bytes): { i64 root, i64 len, i64 flags }
        # All fields are i64 for consistent cross-platform layout
        set_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_SET)
        raw_ptr = cg.gc.alloc_with_deref(builder, set_size, type_id)
        set_ptr = builder.bitcast(raw_ptr, cg.set_struct.as_pointer())

        # Store root = 0 (null pointer as i64)
        root_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i64, 0), root_field)

        # Store len = 0
        len_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), len_field)

        # Store flags (already i64)
        flags_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(flags, flags_field)

        builder.ret(set_ptr)

    def _implement_set_find_slot(self):
        """Legacy stub - HAMT-based sets don't use linear probing slots.
        This function is kept for compatibility but is never called.
        """
        cg = self.cg
        func = cg.set_find_slot
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Just return 0 - this function should never be called with HAMT
        builder.ret(ir.Constant(ir.IntType(64), 0))

    def _implement_set_grow(self):
        """Legacy stub - HAMT-based sets grow automatically through tree structure.
        This function is kept for compatibility but is never called.
        """
        cg = self.cg
        func = cg.set_grow
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Just return - HAMT doesn't need explicit grow
        builder.ret_void()

    def _implement_set_add(self):
        """Return a NEW set with key added (value semantics) using HAMT.

        This implements value semantics via structural sharing.
        Uses the same HAMT infrastructure as Map, with value = 1.
        """
        cg = self.cg
        func = cg.set_add
        func.args[0].name = "old_set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_set = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (stored as i64, convert to pointer for HAMT ops)
        root_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_field)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get old len
        len_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Get old flags
        flags_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "added" flag
        added_ptr = builder.alloca(i32, name="added")

        # Insert into HAMT (value = 1 for sets)
        new_root = builder.call(cg.hamt_insert, [old_root, hash_val, key, ir.Constant(i64, 1), ir.Constant(i32, 0), added_ptr])

        # Allocate new Set struct (24 bytes)
        set_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_SET)
        raw_ptr = cg.gc.alloc_with_deref(builder, set_size, type_id)
        new_set = builder.bitcast(raw_ptr, cg.set_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_field)

        # Compute new len (old_len + added)
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        new_len_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_field)

        # Copy flags from old set
        new_flags_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_field)

        builder.ret(new_set)

    def _implement_set_has(self):
        """Implement set_has: check if key is in HAMT-based set."""
        cg = self.cg
        func = cg.set_has
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get root (stored as i64, convert to pointer)
        root_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_field)
        root = builder.inttoptr(root_i64, void_ptr)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Call hamt_contains
        result = builder.call(cg.hamt_contains, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_set_remove(self):
        """Return a NEW set with element removed (value semantics) using HAMT.

        Uses structural sharing - only nodes on path to removed element are copied.
        """
        cg = self.cg
        func = cg.set_remove
        func.args[0].name = "old_set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        old_set = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (stored as i64, convert to pointer for HAMT ops)
        root_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_field)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get old len
        len_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Get old flags
        flags_field = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "removed" flag
        removed_ptr = builder.alloca(i32, name="removed")

        # Remove from HAMT
        new_root = builder.call(cg.hamt_remove, [old_root, hash_val, key, ir.Constant(i32, 0), removed_ptr])

        # Allocate new Set struct (24 bytes)
        set_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_SET)
        raw_ptr = cg.gc.alloc_with_deref(builder, set_size, type_id)
        new_set = builder.bitcast(raw_ptr, cg.set_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_field)

        # Compute new len (old_len - removed)
        removed = builder.load(removed_ptr)
        removed_64 = builder.zext(removed, i64)
        new_len = builder.sub(old_len, removed_64)
        new_len_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_field)

        # Copy flags from old set
        new_flags_field = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_field)

        builder.ret(new_set)

    def _implement_set_len(self):
        """Implement set_len: return number of elements in set."""
        cg = self.cg
        func = cg.set_len
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]

        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)

        builder.ret(length)

    def _implement_set_size(self):
        """Implement set_size: return approximate memory footprint in bytes.

        With HAMT, this is an approximation since we'd need to traverse the tree.
        Approximate size = 16 (header) + len * 32 (estimate per entry in HAMT).
        This includes leaf nodes and amortized internal node overhead.
        """
        cg = self.cg
        func = cg.set_size
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get len field (field 1)
        len_ptr = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        length = builder.load(len_ptr)

        # Approximate size = 16 (header) + len * 32 (estimated per entry in HAMT)
        entry_estimate = builder.mul(length, ir.Constant(i64, 32))
        total_size = builder.add(ir.Constant(i64, 16), entry_estimate)

        builder.ret(total_size)

    def _implement_set_copy(self):
        """Implement set_copy: return the same pointer (identity function).

        With immutable heap semantics, sets don't need copying. Sharing the
        reference is equivalent to copying because no binding can observe
        mutations through another binding (set operations return new sets).

        GC keeps the shared set alive as long as it's reachable.
        """
        cg = self.cg
        func = cg.set_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Return the same pointer - no copy needed
        builder.ret(func.args[0])

    def _implement_set_to_list(self):
        """Return a List of all elements in the set (as i64 values).

        This is used for Set iteration: for x in set ...
        Uses hamt_collect_keys to gather all keys from the HAMT tree.
        """
        cg = self.cg
        func = cg.set_to_list
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Create result list with 8-byte elements
        elem_size = ir.Constant(i64, 8)
        result_list = builder.call(cg.list_new, [elem_size])

        # Get root from the set (stored as i64, convert to pointer)
        root_ptr = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Use hamt_collect_keys to gather all keys into the list
        final_list = builder.call(cg.hamt_collect_keys, [root, result_list])

        builder.ret(final_list)

    def _implement_set_find_slot_string(self):
        """Legacy stub - HAMT-based sets don't use linear probing slots.
        This function is kept for compatibility but is never called.
        """
        cg = self.cg
        func = cg.set_find_slot_string
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Just return 0 - this function should never be called with HAMT
        builder.ret(ir.Constant(ir.IntType(64), 0))

    def _implement_set_has_string(self):
        """Check if string key exists in HAMT-based set."""
        cg = self.cg
        func = cg.set_has_string
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get root from set (stored as i64, convert to pointer)
        root_ptr = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_i64 = builder.load(root_ptr)
        root = builder.inttoptr(root_i64, void_ptr)

        # Hash the string key
        hash_val = builder.call(cg.string_hash, [key])

        # Check if key exists using hamt_contains_string
        result = builder.call(cg.hamt_contains_string, [root, hash_val, key, ir.Constant(i32, 0)])
        builder.ret(result)

    def _implement_set_add_string(self):
        """Add string element to HAMT-based set, returning NEW set (value semantics)."""
        cg = self.cg
        func = cg.set_add_string
        func.args[0].name = "old_set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        old_set = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (stored as i64, convert to pointer for HAMT ops)
        root_ptr = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_i64 = builder.load(root_ptr)
        old_root = builder.inttoptr(old_root_i64, void_ptr)

        # Get len and flags
        len_ptr = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_ptr)
        flags_ptr = builder.gep(old_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_flags = builder.load(flags_ptr)

        # Hash the string key
        hash_val = builder.call(cg.string_hash, [key])

        # Insert using hamt_insert_string (value = 1 for sets)
        # Note: hamt_insert_string expects String* as key
        added_ptr = builder.alloca(i32, name="added")
        new_root = builder.call(cg.hamt_insert_string, [old_root, hash_val, key, ir.Constant(i64, 1), ir.Constant(i32, 0), added_ptr])
        added = builder.load(added_ptr)

        # Compute new_len = old_len + added
        added_i64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_i64)

        # Allocate new Set struct (24 bytes)
        set_size = ir.Constant(i64, 24)
        type_id = ir.Constant(i32, cg.gc.TYPE_SET)
        raw_ptr = cg.gc.alloc_with_deref(builder, set_size, type_id)
        new_set = builder.bitcast(raw_ptr, cg.set_struct.as_pointer())

        # Store new root (convert pointer to i64)
        new_root_ptr = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_i64 = builder.ptrtoint(new_root, i64)
        builder.store(new_root_i64, new_root_ptr)

        # Store len and flags
        new_len_ptr = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_ptr)
        new_flags_ptr = builder.gep(new_set, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_flags, new_flags_ptr)

        builder.ret(new_set)

    def _register_set_methods(self):
        """Register Set as a type with methods."""
        cg = self.cg
        cg.type_registry["Set"] = cg.set_struct
        cg.type_fields["Set"] = []  # Internal structure, not user-accessible fields

        cg.type_methods["Set"] = {
            "add": "coex_set_add",
            "has": "coex_set_has",
            "remove": "coex_set_remove",
            "len": "coex_set_len",
            "size": "coex_set_size",
            "unpacked": "coex_set_to_list",
        }

        cg.functions["coex_set_new"] = cg.set_new
        cg.functions["coex_set_add"] = cg.set_add
        cg.functions["coex_set_has"] = cg.set_has
        cg.functions["coex_set_remove"] = cg.set_remove
        cg.functions["coex_set_len"] = cg.set_len
        cg.functions["coex_set_size"] = cg.set_size
        cg.functions["coex_set_copy"] = cg.set_copy
        cg.functions["coex_set_to_list"] = cg.set_to_list
