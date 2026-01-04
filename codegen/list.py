"""
List (Persistent Vector) type implementation for Coex.

This module provides the List type implementation for the Coex compiler.
List uses a persistent vector structure with structural sharing for
efficient immutable operations.

List struct (Phase 4 - all i64):
    Field 0: root_handle (i64) - 0 for empty/small lists
    Field 1: len (i64) - total element count
    Field 2: depth (i64) - tree depth (0 = tail only)
    Field 3: tail_handle (i64) - rightmost leaf array handle
    Field 4: tail_len (i64) - elements in tail (0-32)
    Field 5: elem_size (i64)

PV Node struct:
    Field 0: children[32] (i8*) - child pointers

The 32-way branching factor means:
    - Depth 1: up to 1,024 elements in tree
    - Depth 2: up to 32,768 elements
    - Depth 3: up to 1,048,576 elements
    - etc.

All operations maintain value semantics through structural sharing
(unchanged nodes are shared between old and new lists).
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ListGenerator:
    """Generates List (Persistent Vector) type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_list_helpers(self):
        """Create helper functions for list operations."""
        cg = self.cg

        list_ptr = cg.list_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # list_new(elem_size: i64) -> List*
        list_new_ty = ir.FunctionType(list_ptr, [i64])
        cg.list_new = ir.Function(cg.module, list_new_ty, name="coex_list_new")

        # list_append(list: List*, elem: i8*, elem_size: i64) -> List*
        # Returns a NEW list with the element appended (value semantics)
        list_append_ty = ir.FunctionType(list_ptr, [list_ptr, i8_ptr, i64])
        cg.list_append = ir.Function(cg.module, list_append_ty, name="coex_list_append")

        # list_get(list: List*, index: i64) -> i8*
        list_get_ty = ir.FunctionType(i8_ptr, [list_ptr, i64])
        cg.list_get = ir.Function(cg.module, list_get_ty, name="coex_list_get")

        # list_len(list: List*) -> i64
        list_len_ty = ir.FunctionType(i64, [list_ptr])
        cg.list_len = ir.Function(cg.module, list_len_ty, name="coex_list_len")

        # list_size(list: List*) -> i64 (total memory footprint in bytes)
        list_size_ty = ir.FunctionType(i64, [list_ptr])
        cg.list_size = ir.Function(cg.module, list_size_ty, name="coex_list_size")

        # list_copy(list: List*) -> List* (deep copy for value semantics)
        list_copy_ty = ir.FunctionType(list_ptr, [list_ptr])
        cg.list_copy = ir.Function(cg.module, list_copy_ty, name="coex_list_copy")

        # list_set(list: List*, index: i64, value: i8*, elem_size: i64) -> List*
        # Returns a NEW list with element at index replaced (value semantics, path copying)
        list_set_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i8_ptr, i64])
        cg.list_set = ir.Function(cg.module, list_set_ty, name="coex_list_set")

        # list_getrange(list: List*, start: i64, end: i64) -> List*
        # Returns a NEW list with elements [start, end)
        list_getrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64])
        cg.list_getrange = ir.Function(cg.module, list_getrange_ty, name="coex_list_getrange")

        # list_setrange(list: List*, start: i64, end: i64, source: List*) -> List*
        # Returns a NEW list with elements [start, end) replaced by elements from source
        list_setrange_ty = ir.FunctionType(list_ptr, [list_ptr, i64, i64, list_ptr])
        cg.list_setrange = ir.Function(cg.module, list_setrange_ty, name="coex_list_setrange")

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

    def _implement_list_new(self):
        """Implement list_new: allocate a new empty list with given element size.

        Persistent Vector List struct (Phase 4 - all i64):
        - field 0: root_handle (i64) - 0 for empty/small lists
        - field 1: len (i64) - total element count
        - field 2: depth (i64) - tree depth (0 = tail only)
        - field 3: tail_handle (i64) - rightmost leaf array handle
        - field 4: tail_len (i64) - elements in tail (0-32)
        - field 5: elem_size (i64)
        """
        cg = self.cg

        func = cg.list_new
        func.args[0].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate List struct via GC
        # Size: 6 * 8 = 48 bytes (all i64 fields)
        list_size = ir.Constant(i64, 48)
        type_id = ir.Constant(i32, cg.gc.TYPE_LIST)
        raw_ptr = cg.gc.alloc_with_deref(builder, list_size, type_id)
        list_ptr = builder.bitcast(raw_ptr, cg.list_struct.as_pointer())

        # Initialize fields for empty list
        # root_handle = 0 (null) (field 0) - Phase 4: i64 handle
        root_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i64, 0), root_ptr)

        # len = 0 (field 1)
        len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), len_ptr)

        # depth = 0 (field 2) - Phase 4: i64
        depth_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(ir.Constant(i64, 0), depth_ptr)

        # tail = allocate space for 32 elements (field 3)
        # Initial allocation: 32 * elem_size bytes
        tail_capacity = ir.Constant(i64, 32)
        tail_size = builder.mul(tail_capacity, func.args[0])
        tail_type_id = ir.Constant(i32, cg.gc.TYPE_LIST_TAIL)
        tail_ptr = cg.gc.alloc_with_deref(builder, tail_size, tail_type_id)
        # Phase 4: Store as i64 handle
        tail_field_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        tail_handle = builder.ptrtoint(tail_ptr, i64)
        builder.store(tail_handle, tail_field_ptr)

        # tail_len = 0 (field 4) - Phase 4: i64
        tail_len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(ir.Constant(i64, 0), tail_len_ptr)

        # elem_size (field 5)
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        builder.store(func.args[0], elem_size_ptr)

        builder.ret(list_ptr)

    def _implement_list_append(self):
        """Implement list_append: return a NEW list with element appended.

        Persistent Vector append algorithm:
        - If tail has room (tail_len < 32): copy tail, add element, share tree
        - If tail is full: push tail into tree, start new tail

        For Session 4, we implement a simpler version that copies the tail
        and shares the tree root (structural sharing at root level).
        Full path copying (Session 5) will enable O(log n) mutations.
        """
        cg = self.cg

        func = cg.list_append
        func.args[0].name = "list"
        func.args[1].name = "elem"
        func.args[2].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        old_list = func.args[0]
        elem_ptr = func.args[1]
        elem_size = func.args[2]

        # Load old list fields (Phase 4: all fields are i64)
        # len (field 1)
        old_len_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        # depth (field 2) - Phase 4: i64
        old_depth_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_depth = builder.load(old_depth_ptr)

        # tail_handle (field 3) - Phase 4: i64 handle
        old_tail_handle_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        old_tail_handle = builder.load(old_tail_handle_ptr)
        old_tail = builder.inttoptr(old_tail_handle, ir.IntType(8).as_pointer())

        # tail_len (field 4) - Phase 4: i64
        old_tail_len_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        old_tail_len = builder.load(old_tail_len_ptr)

        # elem_size (field 5)
        old_elem_size_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        old_elem_size = builder.load(old_elem_size_ptr)

        # root_handle (field 0) - Phase 4: i64 handle
        old_root_handle_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_handle = builder.load(old_root_handle_ptr)
        old_root = builder.inttoptr(old_root_handle, cg.pv_node_struct.as_pointer())

        # Create new list
        new_list = builder.call(cg.list_new, [old_elem_size])

        # Set new len = old_len + 1
        new_len = builder.add(old_len, ir.Constant(i64, 1))
        new_len_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_len, new_len_ptr)

        # Check if tail has room (tail_len < 32) - Phase 4: i64 comparison
        tail_has_room = builder.icmp_signed("<", old_tail_len, ir.Constant(i64, 32))
        tail_room_block = func.append_basic_block("tail_has_room")
        tail_full_block = func.append_basic_block("tail_full")
        builder.cbranch(tail_has_room, tail_room_block, tail_full_block)

        # --- CASE 1: Tail has room ---
        builder.position_at_end(tail_room_block)

        # Share the root (structural sharing) - Phase 4: store i64 handle
        new_root_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(old_root_handle, new_root_ptr)

        # Copy depth - Phase 4: i64
        new_depth_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_depth, new_depth_ptr)

        # Get new tail pointer (already allocated by list_new) - Phase 4: handle
        new_tail_handle_ptr_field = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        new_tail_handle = builder.load(new_tail_handle_ptr_field)
        new_tail = builder.inttoptr(new_tail_handle, ir.IntType(8).as_pointer())

        # Copy old tail contents to new tail - Phase 4: old_tail_len is already i64
        old_tail_size = builder.mul(old_tail_len, old_elem_size)
        builder.call(cg.memcpy, [new_tail, old_tail, old_tail_size])

        # Append new element at position old_tail_len
        new_elem_offset = builder.mul(old_tail_len, old_elem_size)
        new_elem_dest = builder.gep(new_tail, [new_elem_offset])
        builder.call(cg.memcpy, [new_elem_dest, elem_ptr, elem_size])

        # Set new tail_len = old_tail_len + 1 - Phase 4: i64
        new_tail_len = builder.add(old_tail_len, ir.Constant(i64, 1))
        new_tail_len_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(new_tail_len, new_tail_len_ptr)

        # Structural sharing: no refcount needed - GC keeps shared nodes alive
        builder.ret(new_list)

        # --- CASE 2: Tail is full, need to push into tree ---
        builder.position_at_end(tail_full_block)

        # Push the full tail into the tree structure.
        # Algorithm:
        # 1. Copy the tail data into a new leaf buffer
        # 2. If no tree exists (depth=0): create root with leaf as children[0], depth=1
        # 3. If tree exists at depth 1 and has room: copy root, add leaf to next slot
        # 4. If tree is full at current depth: increase depth and restructure
        #
        # For depth 1, the number of leaves in tree = (len - tail_len) / 32
        # Max leaves at depth 1 = 32, so max elements in tree = 1024

        pv_node_size = ir.Constant(i64, 32 * 8)  # 32 pointers (no refcount - GC handles it)
        pv_node_type_id = ir.Constant(i32, cg.gc.TYPE_PV_NODE)
        leaf_type_id = ir.Constant(i32, cg.gc.TYPE_LIST_TAIL)

        # Copy the old tail data into a new leaf buffer
        leaf_size = builder.mul(ir.Constant(i64, 32), old_elem_size)
        leaf_data = cg.gc.alloc_with_deref(builder, leaf_size, leaf_type_id)
        builder.call(cg.memcpy, [leaf_data, old_tail, leaf_size])

        # Calculate how many leaves are currently in the tree
        # tree_elements = old_len - old_tail_len (where old_tail_len = 32 since tail is full)
        tree_elements = builder.sub(old_len, ir.Constant(i64, 32))
        leaves_in_tree = builder.udiv(tree_elements, ir.Constant(i64, 32))

        # Determine new root based on old root - Phase 4: compare handle to 0
        old_root_is_null = builder.icmp_unsigned("==", old_root_handle, ir.Constant(i64, 0))
        create_root_block = func.append_basic_block("create_root")
        add_to_tree_block = func.append_basic_block("add_to_tree")
        merge_block = func.append_basic_block("merge")
        builder.cbranch(old_root_is_null, create_root_block, add_to_tree_block)

        # Create root block: no existing tree, create root with leaf as children[0]
        builder.position_at_end(create_root_block)

        # Create new root node (no refcount - GC handles memory)
        new_root_raw_create = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_root_create = builder.bitcast(new_root_raw_create, cg.pv_node_struct.as_pointer())

        # Store leaf_data pointer in children[0] (field 0 is now children)
        create_child0_ptr = builder.gep(new_root_create, [ir.Constant(i32, 0), ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(leaf_data, create_child0_ptr)

        new_depth_create = ir.Constant(i64, 1)  # Phase 4: i64
        builder.branch(merge_block)

        # Add to tree block: existing tree, need to add leaf at correct position
        builder.position_at_end(add_to_tree_block)

        # Full persistent vector append with support for depth > 1
        # Algorithm:
        # 1. Check if tree is full at current depth (leaves_in_tree >= 32^depth)
        # 2. If full, increase depth by creating new root with old root at children[0]
        # 3. Path-copy from root to insertion point
        #
        # Max leaves at depth d = 32^d = 1 << (5*d)
        # leaves_in_tree is the index where we want to insert the new leaf

        # Calculate max_leaves at current depth = 1 << (5 * old_depth) - Phase 4: i64
        depth_times_5 = builder.mul(old_depth, ir.Constant(i64, 5))
        max_leaves = builder.shl(ir.Constant(i64, 1), depth_times_5)

        # Check if we need to increase depth - Phase 4: i64 comparison
        need_depth_increase = builder.icmp_unsigned(">=", leaves_in_tree, max_leaves)
        depth_increase_block = func.append_basic_block("depth_increase")
        path_copy_block = func.append_basic_block("path_copy")
        builder.cbranch(need_depth_increase, depth_increase_block, path_copy_block)

        # --- Depth increase: create new root with old root at children[0] ---
        builder.position_at_end(depth_increase_block)

        # Create new root node (no refcount - GC handles memory)
        new_uber_root_raw = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_uber_root = builder.bitcast(new_uber_root_raw, cg.pv_node_struct.as_pointer())

        # Zero out children array (field 0)
        uber_children_ptr = builder.gep(new_uber_root, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        uber_children_i8 = builder.bitcast(uber_children_ptr, ir.IntType(8).as_pointer())
        children_array_size = ir.Constant(i64, 32 * 8)
        builder.call(cg.memset, [uber_children_i8, ir.Constant(ir.IntType(8), 0), children_array_size])

        # Put old root at children[0] (field 0 is children)
        uber_child0_ptr = builder.gep(new_uber_root, [ir.Constant(i32, 0), ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_as_i8ptr = builder.bitcast(old_root, ir.IntType(8).as_pointer())
        builder.store(old_root_as_i8ptr, uber_child0_ptr)

        # No refcount increment - GC handles shared references

        # New depth = old_depth + 1 - Phase 4: i64
        increased_depth = builder.add(old_depth, ir.Constant(i64, 1))
        builder.branch(path_copy_block)

        # --- Path copy: insert leaf at correct position ---
        builder.position_at_end(path_copy_block)

        # PHI nodes for working root and depth - Phase 4: depth is i64
        working_root = builder.phi(cg.pv_node_struct.as_pointer(), name="working_root")
        working_root.add_incoming(new_uber_root, depth_increase_block)
        working_root.add_incoming(old_root, add_to_tree_block)

        working_depth = builder.phi(i64, name="working_depth")
        working_depth.add_incoming(increased_depth, depth_increase_block)
        working_depth.add_incoming(old_depth, add_to_tree_block)

        # Now do path-copy insertion
        # For inserting leaf at leaf_idx in depth d:
        # - Allocate path array on stack (max depth ~6 for billions of elements)
        # - Descend from root, copying nodes at each level
        # - Insert leaf at bottom level
        # - Return new root

        # Allocate space for path (array of node pointers, max 8 levels should be enough)
        path_alloca = builder.alloca(ir.ArrayType(cg.pv_node_struct.as_pointer(), 8), name="path")

        # Allocate level counter - Phase 4: i64
        level_alloca = builder.alloca(i64, name="level")
        start_level = builder.sub(working_depth, ir.Constant(i64, 1))
        builder.store(start_level, level_alloca)

        # Allocate current node pointer
        current_alloca = builder.alloca(cg.pv_node_struct.as_pointer(), name="current")
        builder.store(working_root, current_alloca)

        # Copy the root node first (we always need a new root, no refcount - GC handles it)
        new_root_raw_add = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_root_add = builder.bitcast(new_root_raw_add, cg.pv_node_struct.as_pointer())

        # Copy root's children (field 0 is children)
        old_children_ptr = builder.gep(working_root, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_children_ptr = builder.gep(new_root_add, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_children_i8 = builder.bitcast(old_children_ptr, ir.IntType(8).as_pointer())
        new_children_i8 = builder.bitcast(new_children_ptr, ir.IntType(8).as_pointer())
        builder.call(cg.memcpy, [new_children_i8, old_children_i8, children_array_size])

        # Store new root in path[depth-1] - Phase 4: index is i64
        path_slot = builder.gep(path_alloca, [ir.Constant(i64, 0), start_level], inbounds=True)
        builder.store(new_root_add, path_slot)

        # Check if depth is 1 (simple case: just insert leaf directly) - Phase 4: i64
        is_depth_1 = builder.icmp_signed("==", working_depth, ir.Constant(i64, 1))
        depth_1_insert_block = func.append_basic_block("depth_1_insert")
        multi_level_block = func.append_basic_block("multi_level")
        builder.cbranch(is_depth_1, depth_1_insert_block, multi_level_block)

        # --- Depth 1: simple direct insertion ---
        builder.position_at_end(depth_1_insert_block)
        leaf_slot_d1 = builder.and_(leaves_in_tree, ir.Constant(i64, 0x1F))
        leaf_ptr_d1 = builder.gep(new_root_add, [ir.Constant(i32, 0), ir.Constant(i32, 0), leaf_slot_d1], inbounds=True)
        builder.store(leaf_data, leaf_ptr_d1)
        builder.branch(merge_block)

        # --- Multi-level: path copy down the tree ---
        builder.position_at_end(multi_level_block)

        # Loop to descend and copy nodes
        descend_cond = func.append_basic_block("descend_cond")
        descend_body = func.append_basic_block("descend_body")
        descend_done = func.append_basic_block("descend_done")

        # Initialize: start at level depth-2 (we already copied root at depth-1) - Phase 4: i64
        level_minus_2 = builder.sub(working_depth, ir.Constant(i64, 2))
        builder.store(level_minus_2, level_alloca)

        # Parent node is new_root_add
        parent_alloca = builder.alloca(cg.pv_node_struct.as_pointer(), name="parent")
        builder.store(new_root_add, parent_alloca)

        builder.branch(descend_cond)

        # Loop condition: level >= 0 - Phase 4: i64
        builder.position_at_end(descend_cond)
        current_level = builder.load(level_alloca)
        continue_descend = builder.icmp_signed(">=", current_level, ir.Constant(i64, 0))
        builder.cbranch(continue_descend, descend_body, descend_done)

        # Loop body: copy or create node at this level
        builder.position_at_end(descend_body)

        parent_node = builder.load(parent_alloca)
        level_for_calc = builder.load(level_alloca)

        # Calculate child index: (leaf_idx >> ((level+1) * 5)) & 0x1F - Phase 4: i64
        level_plus_1 = builder.add(level_for_calc, ir.Constant(i64, 1))
        shift_amt = builder.mul(level_plus_1, ir.Constant(i64, 5))
        shifted_idx = builder.lshr(leaves_in_tree, shift_amt)
        child_idx = builder.and_(shifted_idx, ir.Constant(i64, 0x1F))

        # Get child pointer from parent (field 0 is children)
        parent_children = builder.gep(parent_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        child_ptr_ptr = builder.gep(parent_children, [ir.Constant(i64, 0), child_idx], inbounds=True)
        old_child_i8 = builder.load(child_ptr_ptr)

        # Check if child exists
        child_is_null = builder.icmp_unsigned("==", old_child_i8, ir.Constant(ir.IntType(8).as_pointer(), None))
        create_child_block = func.append_basic_block("create_child")
        copy_child_block = func.append_basic_block("copy_child")
        child_done_block = func.append_basic_block("child_done")
        builder.cbranch(child_is_null, create_child_block, copy_child_block)

        # Create new child node (no refcount - GC handles it)
        builder.position_at_end(create_child_block)
        new_child_raw_create = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_child_create = builder.bitcast(new_child_raw_create, cg.pv_node_struct.as_pointer())
        # Zero out children (field 0 is children)
        create_child_children = builder.gep(new_child_create, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        create_child_children_i8 = builder.bitcast(create_child_children, ir.IntType(8).as_pointer())
        builder.call(cg.memset, [create_child_children_i8, ir.Constant(ir.IntType(8), 0), children_array_size])
        builder.branch(child_done_block)

        # Copy existing child node (no refcount - GC handles it)
        builder.position_at_end(copy_child_block)
        old_child_node = builder.bitcast(old_child_i8, cg.pv_node_struct.as_pointer())
        new_child_raw_copy = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_child_copy = builder.bitcast(new_child_raw_copy, cg.pv_node_struct.as_pointer())
        # Copy children from old node (field 0 is children)
        old_child_children = builder.gep(old_child_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_child_children = builder.gep(new_child_copy, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_child_children_i8 = builder.bitcast(old_child_children, ir.IntType(8).as_pointer())
        new_child_children_i8 = builder.bitcast(new_child_children, ir.IntType(8).as_pointer())
        builder.call(cg.memcpy, [new_child_children_i8, old_child_children_i8, children_array_size])
        builder.branch(child_done_block)

        # Merge: get the new child node
        builder.position_at_end(child_done_block)
        new_child_phi = builder.phi(cg.pv_node_struct.as_pointer(), name="new_child")
        new_child_phi.add_incoming(new_child_create, create_child_block)
        new_child_phi.add_incoming(new_child_copy, copy_child_block)

        # Update parent's child pointer
        new_child_as_i8 = builder.bitcast(new_child_phi, ir.IntType(8).as_pointer())
        builder.store(new_child_as_i8, child_ptr_ptr)

        # Store in path array - Phase 4: i64 index
        current_level_reload = builder.load(level_alloca)
        path_slot_loop = builder.gep(path_alloca, [ir.Constant(i64, 0), current_level_reload], inbounds=True)
        builder.store(new_child_phi, path_slot_loop)

        # Update parent for next iteration
        builder.store(new_child_phi, parent_alloca)

        # Decrement level - Phase 4: i64
        new_level = builder.sub(current_level_reload, ir.Constant(i64, 1))
        builder.store(new_level, level_alloca)

        builder.branch(descend_cond)

        # Loop done: insert leaf at bottom level
        builder.position_at_end(descend_done)

        # The bottom node is in parent_alloca (it's the level-0 node)
        bottom_node = builder.load(parent_alloca)

        # Calculate leaf slot: leaves_in_tree & 0x1F - Phase 4: i64
        leaf_slot_multi = builder.and_(leaves_in_tree, ir.Constant(i64, 0x1F))

        # Insert leaf (field 0 is children)
        leaf_ptr_multi = builder.gep(bottom_node, [ir.Constant(i32, 0), ir.Constant(i32, 0), leaf_slot_multi], inbounds=True)
        builder.store(leaf_data, leaf_ptr_multi)

        # New root is new_root_add, new depth is working_depth
        builder.branch(merge_block)

        # Update merge block PHI nodes
        new_depth_add = working_depth

        # Merge block: finalize new list
        builder.position_at_end(merge_block)

        # PHI nodes for new_root and new_depth - Phase 4: depth is i64
        # Incoming from: create_root_block, depth_1_insert_block, descend_done
        new_root_phi = builder.phi(cg.pv_node_struct.as_pointer(), name="new_root")
        new_root_phi.add_incoming(new_root_create, create_root_block)
        new_root_phi.add_incoming(new_root_add, depth_1_insert_block)
        new_root_phi.add_incoming(new_root_add, descend_done)

        new_depth_phi = builder.phi(i64, name="new_depth")
        new_depth_phi.add_incoming(new_depth_create, create_root_block)
        new_depth_phi.add_incoming(working_depth, depth_1_insert_block)
        new_depth_phi.add_incoming(working_depth, descend_done)

        # Set new list's root - Phase 4: store as i64 handle
        new_list_root_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_handle = builder.ptrtoint(new_root_phi, i64)
        builder.store(new_root_handle, new_list_root_ptr)

        # Set new list's depth - Phase 4: i64
        new_list_depth_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(new_depth_phi, new_list_depth_ptr)

        # Create new tail with just the appended element - Phase 4: load handle
        new_list_tail_handle_ptr_field = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        new_list_tail_handle = builder.load(new_list_tail_handle_ptr_field)
        new_list_tail = builder.inttoptr(new_list_tail_handle, ir.IntType(8).as_pointer())

        # Copy element to new tail at position 0
        builder.call(cg.memcpy, [new_list_tail, elem_ptr, elem_size])

        # Set tail_len = 1 - Phase 4: i64
        new_list_tail_len_ptr = builder.gep(new_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(ir.Constant(i64, 1), new_list_tail_len_ptr)

        builder.ret(new_list)

    def _implement_list_get(self):
        """Implement list_get: return pointer to element at index.

        Persistent Vector get algorithm:
        1. Check if index is in tail (index >= len - tail_len)
        2. If in tail: return tail[index - (len - tail_len)]
        3. If in tree: navigate using bit manipulation (5 bits per level)

        For a 32-way trie:
        - Level 0 (leaf): bits 0-4 (index & 0x1F)
        - Level 1: bits 5-9 ((index >> 5) & 0x1F)
        - etc.
        """
        cg = self.cg

        func = cg.list_get
        func.args[0].name = "list"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        list_ptr = func.args[0]
        index = func.args[1]

        # Load list fields (Phase 4: all fields are i64)
        # len (field 1)
        len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        list_len = builder.load(len_ptr)

        # depth (field 2) - Phase 4: i64
        depth_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        depth = builder.load(depth_ptr)

        # tail_handle (field 3) - Phase 4: i64 handle
        tail_handle_ptr_field = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        tail_handle = builder.load(tail_handle_ptr_field)
        tail = builder.inttoptr(tail_handle, ir.IntType(8).as_pointer())

        # tail_len (field 4) - Phase 4: i64
        tail_len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        tail_len = builder.load(tail_len_ptr)

        # elem_size (field 5)
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # root_handle (field 0) - Phase 4: i64 handle
        root_handle_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        root_handle = builder.load(root_handle_ptr)
        root = builder.inttoptr(root_handle, cg.pv_node_struct.as_pointer())

        # Calculate tail_start = len - tail_len - Phase 4: both are i64
        tail_start = builder.sub(list_len, tail_len)

        # Check if index is in tail
        in_tail = builder.icmp_unsigned(">=", index, tail_start)
        tail_block = func.append_basic_block("in_tail")
        tree_block = func.append_basic_block("in_tree")
        builder.cbranch(in_tail, tail_block, tree_block)

        # --- Element is in tail ---
        builder.position_at_end(tail_block)

        # tail_index = index - tail_start
        tail_index = builder.sub(index, tail_start)

        # Calculate offset in tail
        tail_offset = builder.mul(tail_index, elem_size)
        tail_result = builder.gep(tail, [tail_offset])
        builder.ret(tail_result)

        # --- Element is in tree ---
        builder.position_at_end(tree_block)

        # Navigate tree using bit manipulation
        # For depth d, we need to traverse d levels
        # At each level l (from depth-1 down to 0), extract bits: (index >> (5*l)) & 0x1F

        # Since depth can vary, we need a loop structure
        # Allocate a node pointer to track current position
        current_node_alloca = builder.alloca(cg.pv_node_struct.as_pointer(), name="current_node")
        builder.store(root, current_node_alloca)

        # Allocate level counter (starts at depth-1, goes down to 0) - Phase 4: i64
        level_alloca = builder.alloca(i64, name="level")
        start_level = builder.sub(depth, ir.Constant(i64, 1))
        builder.store(start_level, level_alloca)

        # Loop: while level >= 0 - Phase 4: use i64 for all calculations
        loop_cond = func.append_basic_block("tree_loop_cond")
        loop_body = func.append_basic_block("tree_loop_body")
        loop_done = func.append_basic_block("tree_loop_done")

        builder.branch(loop_cond)

        builder.position_at_end(loop_cond)
        current_level = builder.load(level_alloca)
        continue_loop = builder.icmp_signed(">=", current_level, ir.Constant(i64, 0))
        builder.cbranch(continue_loop, loop_body, loop_done)

        builder.position_at_end(loop_body)

        # Calculate child index: (index >> (5 * (level + 1))) & 0x1F - Phase 4: i64
        # Level 0 means we're at the lowest node level (parents of leaves)
        # For depth=1, level=0, we need shift of 5 to get leaf index
        # For depth=2, level=1 at root needs shift of 10, level=0 needs shift of 5
        level_loaded = builder.load(level_alloca)
        level_plus_one = builder.add(level_loaded, ir.Constant(i64, 1))
        shift_amount = builder.mul(level_plus_one, ir.Constant(i64, 5))
        shifted = builder.lshr(index, shift_amount)
        child_idx = builder.and_(shifted, ir.Constant(i64, 0x1F))

        # Get current node
        current_node = builder.load(current_node_alloca)

        # Get children array pointer (field 0 is children)
        children_array_ptr = builder.gep(current_node, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)

        # Get child at child_idx - Phase 4: use i64 index
        child_ptr_ptr = builder.gep(children_array_ptr, [ir.Constant(i64, 0), child_idx], inbounds=True)
        child_ptr = builder.load(child_ptr_ptr)

        # Check if we're at the last level (level == 0) - Phase 4: i64
        at_leaf_level = builder.icmp_signed("==", level_loaded, ir.Constant(i64, 0))
        leaf_access = func.append_basic_block("leaf_access")
        continue_descent = func.append_basic_block("continue_descent")
        builder.cbranch(at_leaf_level, leaf_access, continue_descent)

        # At leaf level: child_ptr points to element data (leaf array)
        builder.position_at_end(leaf_access)

        # The leaf is an array of 32 elements, access index & 0x1F - Phase 4: i64
        leaf_idx = builder.and_(index, ir.Constant(i64, 0x1F))
        leaf_offset = builder.mul(leaf_idx, elem_size)
        leaf_result = builder.gep(child_ptr, [leaf_offset])
        builder.ret(leaf_result)

        # Continue descent: child_ptr is another PVNode
        builder.position_at_end(continue_descent)
        next_node = builder.bitcast(child_ptr, cg.pv_node_struct.as_pointer())
        builder.store(next_node, current_node_alloca)

        # Decrement level - Phase 4: i64
        new_level = builder.sub(level_loaded, ir.Constant(i64, 1))
        builder.store(new_level, level_alloca)
        builder.branch(loop_cond)

        # Loop done (shouldn't reach here if tree is correct, but handle it)
        builder.position_at_end(loop_done)
        # Fallback: return null pointer (indicates error)
        builder.ret(ir.Constant(ir.IntType(8).as_pointer(), None))

    def _implement_list_set(self):
        """Implement list_set: return a NEW list with element at index replaced.

        Persistent Vector set algorithm with path copying:
        1. Check if index is in tail (index >= len - tail_len)
        2. If in tail: copy tail, modify element, share tree
        3. If in tree: path copy from root to leaf, modify element

        Path copying ensures structural sharing - unchanged nodes are shared.
        """
        cg = self.cg

        func = cg.list_set
        func.args[0].name = "list"
        func.args[1].name = "index"
        func.args[2].name = "value"
        func.args[3].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        old_list = func.args[0]
        index = func.args[1]
        value_ptr = func.args[2]
        elem_size = func.args[3]

        # Load old list fields (Phase 4: all fields are i64)
        # len (field 1)
        old_len_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        # depth (field 2) - Phase 4: i64
        old_depth_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        old_depth = builder.load(old_depth_ptr)

        # tail_handle (field 3) - Phase 4: i64 handle
        old_tail_handle_ptr_field = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        old_tail_handle = builder.load(old_tail_handle_ptr_field)
        old_tail = builder.inttoptr(old_tail_handle, ir.IntType(8).as_pointer())

        # tail_len (field 4) - Phase 4: i64
        old_tail_len_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        old_tail_len = builder.load(old_tail_len_ptr)

        # elem_size (field 5) - use stored value, not parameter
        old_elem_size_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        stored_elem_size = builder.load(old_elem_size_ptr)

        # root_handle (field 0) - Phase 4: i64 handle
        old_root_handle_ptr = builder.gep(old_list, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root_handle = builder.load(old_root_handle_ptr)
        old_root = builder.inttoptr(old_root_handle, cg.pv_node_struct.as_pointer())

        # Calculate tail_start = len - tail_len - Phase 4: both are i64
        tail_start = builder.sub(old_len, old_tail_len)

        # Check if index is in tail
        in_tail = builder.icmp_unsigned(">=", index, tail_start)
        tail_set_block = func.append_basic_block("tail_set")
        tree_set_block = func.append_basic_block("tree_set")
        builder.cbranch(in_tail, tail_set_block, tree_set_block)

        # --- CASE 1: Index is in tail ---
        builder.position_at_end(tail_set_block)

        # Create new list
        new_list_tail = builder.call(cg.list_new, [stored_elem_size])

        # Share the root (Phase 4: store i64 handle)
        new_root_ptr_t = builder.gep(new_list_tail, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(old_root_handle, new_root_ptr_t)

        # Copy depth and len - Phase 4: depth is i64
        new_depth_ptr_t = builder.gep(new_list_tail, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_depth, new_depth_ptr_t)
        new_len_ptr_t = builder.gep(new_list_tail, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(old_len, new_len_ptr_t)

        # Get new tail pointer (allocated by list_new) - Phase 4: handle
        new_tail_handle_ptr_field_t = builder.gep(new_list_tail, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        new_tail_handle_t = builder.load(new_tail_handle_ptr_field_t)
        new_tail_t = builder.inttoptr(new_tail_handle_t, ir.IntType(8).as_pointer())

        # Copy old tail contents to new tail - Phase 4: old_tail_len is already i64
        old_tail_size_t = builder.mul(old_tail_len, stored_elem_size)
        builder.call(cg.memcpy, [new_tail_t, old_tail, old_tail_size_t])

        # Set new tail_len - Phase 4: i64
        new_tail_len_ptr_t = builder.gep(new_list_tail, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(old_tail_len, new_tail_len_ptr_t)

        # Modify element at tail_index = index - tail_start
        tail_index = builder.sub(index, tail_start)
        elem_offset_t = builder.mul(tail_index, stored_elem_size)
        elem_dest_t = builder.gep(new_tail_t, [elem_offset_t])
        builder.call(cg.memcpy, [elem_dest_t, value_ptr, elem_size])

        builder.ret(new_list_tail)

        # --- CASE 2: Index is in tree - path copy ---
        builder.position_at_end(tree_set_block)

        # Create new list
        new_list_tree = builder.call(cg.list_new, [stored_elem_size])

        # Copy len and depth - Phase 4: depth is i64
        new_len_ptr_tr = builder.gep(new_list_tree, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(old_len, new_len_ptr_tr)
        new_depth_ptr_tr = builder.gep(new_list_tree, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(old_depth, new_depth_ptr_tr)

        # Copy tail (tail is unchanged, just copy the whole thing) - Phase 4: handle
        new_tail_handle_ptr_field_tr = builder.gep(new_list_tree, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        new_tail_handle_tr = builder.load(new_tail_handle_ptr_field_tr)
        new_tail_tr = builder.inttoptr(new_tail_handle_tr, ir.IntType(8).as_pointer())
        old_tail_size_tr = builder.mul(old_tail_len, stored_elem_size)  # Phase 4: old_tail_len is i64
        builder.call(cg.memcpy, [new_tail_tr, old_tail, old_tail_size_tr])
        new_tail_len_ptr_tr = builder.gep(new_list_tree, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(old_tail_len, new_tail_len_ptr_tr)

        # Path copy the tree from root to the target leaf
        # For depth 1, we have: root -> leaf arrays
        # For depth > 1, we have: root -> internal nodes -> ... -> leaf arrays

        pv_node_size = ir.Constant(i64, 32 * 8)  # 32 pointers (no refcount - GC handles it)
        pv_node_type_id = ir.Constant(i32, cg.gc.TYPE_PV_NODE)
        leaf_type_id = ir.Constant(i32, cg.gc.TYPE_LIST_TAIL)

        # Check if root is null - Phase 4: compare handle to 0
        root_null_check = builder.icmp_unsigned("==", old_root_handle, ir.Constant(i64, 0))
        root_exists = func.append_basic_block("root_exists")
        ret_empty = func.append_basic_block("ret_empty")
        builder.cbranch(root_null_check, ret_empty, root_exists)

        builder.position_at_end(ret_empty)
        builder.ret(new_list_tree)  # Return list with copied tail but no tree

        builder.position_at_end(root_exists)

        # Copy the root node (no refcount - GC handles memory)
        new_root_raw = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_root = builder.bitcast(new_root_raw, cg.pv_node_struct.as_pointer())

        # Copy children pointers from old root (field 0 is children)
        old_root_children = builder.gep(old_root, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_children = builder.gep(new_root, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        children_size = ir.Constant(i64, 32 * 8)
        old_root_children_i8 = builder.bitcast(old_root_children, ir.IntType(8).as_pointer())
        new_root_children_i8 = builder.bitcast(new_root_children, ir.IntType(8).as_pointer())
        builder.call(cg.memcpy, [new_root_children_i8, old_root_children_i8, children_size])

        # Store new root in new list - Phase 4: store as i64 handle
        new_root_ptr_tr = builder.gep(new_list_tree, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_root_handle_tr = builder.ptrtoint(new_root, i64)
        builder.store(new_root_handle_tr, new_root_ptr_tr)

        # For depth=1 (most common case), we just need to:
        # 1. Calculate which leaf (child_idx = (index >> 5) & 0x1F)
        # 2. Copy that leaf
        # 3. Modify the element in the new leaf
        # 4. Update new_root's child pointer

        # For depth>1, we need to path copy all nodes from root to leaf

        # Check if depth == 1 (simple case) - Phase 4: i64
        depth_is_one = builder.icmp_signed("==", old_depth, ir.Constant(i64, 1))
        depth_one_block = func.append_basic_block("depth_one")
        depth_multi_block = func.append_basic_block("depth_multi")
        builder.cbranch(depth_is_one, depth_one_block, depth_multi_block)

        # --- Depth == 1 case ---
        builder.position_at_end(depth_one_block)

        # Calculate child index: (index >> 5) & 0x1F - Phase 4: i64
        child_idx_d1 = builder.lshr(index, ir.Constant(i64, 5))
        child_idx_d1 = builder.and_(child_idx_d1, ir.Constant(i64, 0x1F))

        # Get old leaf pointer from old root (field 0 is children) - Phase 4: i64 GEP index
        old_leaf_ptr_d1 = builder.gep(old_root, [ir.Constant(i32, 0), ir.Constant(i32, 0), child_idx_d1], inbounds=True)
        old_leaf_d1 = builder.load(old_leaf_ptr_d1)

        # Create new leaf (copy of old leaf)
        leaf_size_d1 = builder.mul(ir.Constant(i64, 32), stored_elem_size)
        new_leaf_d1 = cg.gc.alloc_with_deref(builder, leaf_size_d1, leaf_type_id)
        builder.call(cg.memcpy, [new_leaf_d1, old_leaf_d1, leaf_size_d1])

        # Modify element in new leaf at position index & 0x1F - Phase 4: i64
        leaf_elem_idx_d1 = builder.and_(index, ir.Constant(i64, 0x1F))
        leaf_elem_offset_d1 = builder.mul(leaf_elem_idx_d1, stored_elem_size)
        leaf_elem_dest_d1 = builder.gep(new_leaf_d1, [leaf_elem_offset_d1])
        builder.call(cg.memcpy, [leaf_elem_dest_d1, value_ptr, elem_size])

        # Update new root's child pointer to point to new leaf (field 0 is children)
        new_leaf_slot_d1 = builder.gep(new_root, [ir.Constant(i32, 0), ir.Constant(i32, 0), child_idx_d1], inbounds=True)
        builder.store(new_leaf_d1, new_leaf_slot_d1)

        builder.ret(new_list_tree)

        # --- Depth > 1 case (path copy through multiple levels) ---
        builder.position_at_end(depth_multi_block)

        # We need to navigate and copy the path from root to leaf
        # Level indices from top (root) to bottom (parent of leaf):
        # At each level l (from depth-1 down to 1), the child index is ((index >> (5*(l+1))) & 0x1F)
        # At level 0 (parent of leaves), child index is (index >> 5) & 0x1F
        # Within leaf, element index is index & 0x1F

        # Allocate storage for current nodes (old and new) during traversal
        current_old_node = builder.alloca(cg.pv_node_struct.as_pointer(), name="curr_old")
        current_new_node = builder.alloca(cg.pv_node_struct.as_pointer(), name="curr_new")
        builder.store(old_root, current_old_node)
        builder.store(new_root, current_new_node)

        # Level counter: start at depth-1, go down to 0 - Phase 4: i64
        level_alloca = builder.alloca(i64, name="level")
        start_level = builder.sub(old_depth, ir.Constant(i64, 1))
        builder.store(start_level, level_alloca)

        # Loop through levels - Phase 4: i64
        path_loop_cond = func.append_basic_block("path_loop_cond")
        path_loop_body = func.append_basic_block("path_loop_body")
        path_loop_done = func.append_basic_block("path_loop_done")
        builder.branch(path_loop_cond)

        builder.position_at_end(path_loop_cond)
        curr_level = builder.load(level_alloca)
        continue_path = builder.icmp_signed(">", curr_level, ir.Constant(i64, 0))
        builder.cbranch(continue_path, path_loop_body, path_loop_done)

        builder.position_at_end(path_loop_body)
        level_val = builder.load(level_alloca)

        # Calculate child index at this level: (index >> (5 * (level + 1))) & 0x1F - Phase 4: i64
        level_plus_one = builder.add(level_val, ir.Constant(i64, 1))
        shift_amt = builder.mul(level_plus_one, ir.Constant(i64, 5))
        child_idx_path = builder.lshr(index, shift_amt)
        child_idx_path = builder.and_(child_idx_path, ir.Constant(i64, 0x1F))

        # Get old child node (field 0 is children) - Phase 4: i64 GEP index
        old_node_curr = builder.load(current_old_node)
        old_child_ptr = builder.gep(old_node_curr, [ir.Constant(i32, 0), ir.Constant(i32, 0), child_idx_path], inbounds=True)
        old_child_raw = builder.load(old_child_ptr)
        old_child = builder.bitcast(old_child_raw, cg.pv_node_struct.as_pointer())

        # Create new child node (no refcount - GC handles memory)
        new_child_raw = cg.gc.alloc_with_deref(builder, pv_node_size, pv_node_type_id)
        new_child = builder.bitcast(new_child_raw, cg.pv_node_struct.as_pointer())

        # Copy children array from old child (field 0 is children)
        old_child_children = builder.gep(old_child, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_child_children = builder.gep(new_child, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_child_children_i8 = builder.bitcast(old_child_children, ir.IntType(8).as_pointer())
        new_child_children_i8 = builder.bitcast(new_child_children, ir.IntType(8).as_pointer())
        builder.call(cg.memcpy, [new_child_children_i8, old_child_children_i8, children_size])

        # Update parent (new_node_curr) to point to new_child (field 0 is children)
        new_node_curr = builder.load(current_new_node)
        new_child_slot = builder.gep(new_node_curr, [ir.Constant(i32, 0), ir.Constant(i32, 0), child_idx_path], inbounds=True)
        new_child_i8 = builder.bitcast(new_child, ir.IntType(8).as_pointer())
        builder.store(new_child_i8, new_child_slot)

        # Move to next level
        builder.store(old_child, current_old_node)
        builder.store(new_child, current_new_node)

        # Decrement level - Phase 4: i64
        new_level = builder.sub(level_val, ir.Constant(i64, 1))
        builder.store(new_level, level_alloca)
        builder.branch(path_loop_cond)

        # Path loop done - now at level 0, need to handle leaf
        builder.position_at_end(path_loop_done)

        # Calculate leaf index: (index >> 5) & 0x1F - Phase 4: i64
        leaf_idx_multi = builder.lshr(index, ir.Constant(i64, 5))
        leaf_idx_multi = builder.and_(leaf_idx_multi, ir.Constant(i64, 0x1F))

        # Get old leaf from current old node (field 0 is children)
        final_old_node = builder.load(current_old_node)
        old_leaf_ptr_m = builder.gep(final_old_node, [ir.Constant(i32, 0), ir.Constant(i32, 0), leaf_idx_multi], inbounds=True)
        old_leaf_m = builder.load(old_leaf_ptr_m)

        # Create new leaf
        leaf_size_m = builder.mul(ir.Constant(i64, 32), stored_elem_size)
        new_leaf_m = cg.gc.alloc_with_deref(builder, leaf_size_m, leaf_type_id)
        builder.call(cg.memcpy, [new_leaf_m, old_leaf_m, leaf_size_m])

        # Modify element in new leaf - Phase 4: i64
        elem_idx_m = builder.and_(index, ir.Constant(i64, 0x1F))
        elem_offset_m = builder.mul(elem_idx_m, stored_elem_size)
        elem_dest_m = builder.gep(new_leaf_m, [elem_offset_m])
        builder.call(cg.memcpy, [elem_dest_m, value_ptr, elem_size])

        # Update current new node to point to new leaf (field 0 is children)
        final_new_node = builder.load(current_new_node)
        new_leaf_slot_m = builder.gep(final_new_node, [ir.Constant(i32, 0), ir.Constant(i32, 0), leaf_idx_multi], inbounds=True)
        builder.store(new_leaf_m, new_leaf_slot_m)

        builder.ret(new_list_tree)

    def _implement_list_len(self):
        """Implement list_len: return list length.

        In Persistent Vector structure, len is field 1.
        """
        cg = self.cg

        func = cg.list_len
        func.args[0].name = "list"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)

        list_ptr = func.args[0]

        # Get len field (field 1 in PV structure)
        len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        length = builder.load(len_ptr)

        builder.ret(length)

    def _implement_list_size(self):
        """Implement list_size: return total memory footprint in bytes.

        For PV structure: header (48) + tail (32 * elem_size) + tree nodes
        This is an approximation - we return header + tail size.
        """
        cg = self.cg

        func = cg.list_size
        func.args[0].name = "list"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        list_ptr = func.args[0]

        # Get tail_len field (field 4)
        tail_len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        tail_len = builder.load(tail_len_ptr)

        # Get elem_size field (field 5)
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Size = 48 (header) + 32 * elem_size (tail capacity)
        tail_len_64 = builder.zext(tail_len, i64)
        tail_size = builder.mul(ir.Constant(i64, 32), elem_size)
        total_size = builder.add(ir.Constant(i64, 48), tail_size)

        builder.ret(total_size)

    def _implement_list_copy(self):
        """Implement list_copy: return the same pointer (identity function).

        With immutable heap semantics, lists don't need copying. Sharing the
        reference is equivalent to copying because no binding can observe
        mutations through another binding (list operations return new lists).

        GC keeps the shared list alive as long as it's reachable.
        """
        cg = self.cg

        func = cg.list_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Return the same pointer - no copy needed
        builder.ret(func.args[0])

    def _implement_list_getrange(self):
        """Implement list_getrange: return new list with elements [start, end)."""
        cg = self.cg

        func = cg.list_getrange
        func.args[0].name = "list"
        func.args[1].name = "start"
        func.args[2].name = "end"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)
        list_ptr_type = cg.list_struct.as_pointer()

        src_list = func.args[0]
        start = func.args[1]
        end = func.args[2]

        # Get source list length and element size
        src_len = builder.call(cg.list_len, [src_list])
        elem_size_ptr = builder.gep(src_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Clamp start to [0, len]
        start_neg = builder.icmp_signed("<", start, zero)
        start_over = builder.icmp_signed(">", start, src_len)
        start_clamped = builder.select(start_neg, zero, builder.select(start_over, src_len, start))

        # Clamp end to [start, len]
        end_under = builder.icmp_signed("<", end, start_clamped)
        end_over = builder.icmp_signed(">", end, src_len)
        end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, src_len, end))

        # Calculate result length
        result_len = builder.sub(end_clamped, start_clamped)

        # Create new empty list
        new_list = builder.call(cg.list_new, [elem_size])

        # Loop: copy elements from start to end
        loop_header = func.append_basic_block("loop_header")
        loop_body = func.append_basic_block("loop_body")
        loop_exit = func.append_basic_block("loop_exit")

        i_ptr = builder.alloca(i64, name="i")
        builder.store(zero, i_ptr)
        result_ptr = builder.alloca(list_ptr_type, name="result")
        builder.store(new_list, result_ptr)
        builder.branch(loop_header)

        builder.position_at_end(loop_header)
        i = builder.load(i_ptr)
        cond = builder.icmp_signed("<", i, result_len)
        builder.cbranch(cond, loop_body, loop_exit)

        builder.position_at_end(loop_body)
        src_idx = builder.add(start_clamped, i)
        elem_ptr = builder.call(cg.list_get, [src_list, src_idx])
        current_result = builder.load(result_ptr)
        new_result = builder.call(cg.list_append, [current_result, elem_ptr, elem_size])
        builder.store(new_result, result_ptr)
        next_i = builder.add(i, one)
        builder.store(next_i, i_ptr)
        builder.branch(loop_header)

        builder.position_at_end(loop_exit)
        final_result = builder.load(result_ptr)
        builder.ret(final_result)

    def _implement_list_setrange(self):
        """Implement list_setrange: return new list with [start, end) replaced by source."""
        cg = self.cg

        func = cg.list_setrange
        func.args[0].name = "list"
        func.args[1].name = "start"
        func.args[2].name = "end"
        func.args[3].name = "source"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)
        list_ptr_type = cg.list_struct.as_pointer()

        orig_list = func.args[0]
        start = func.args[1]
        end = func.args[2]
        source = func.args[3]

        # Get lengths and element size
        orig_len = builder.call(cg.list_len, [orig_list])
        source_len = builder.call(cg.list_len, [source])
        elem_size_ptr = builder.gep(orig_list, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Clamp bounds
        start_neg = builder.icmp_signed("<", start, zero)
        start_over = builder.icmp_signed(">", start, orig_len)
        start_clamped = builder.select(start_neg, zero, builder.select(start_over, orig_len, start))

        end_under = builder.icmp_signed("<", end, start_clamped)
        end_over = builder.icmp_signed(">", end, orig_len)
        end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, orig_len, end))

        # Calculate how many elements to copy from source: min(end-start, source.len())
        range_len = builder.sub(end_clamped, start_clamped)
        copy_len = builder.select(
            builder.icmp_signed("<", source_len, range_len),
            source_len,
            range_len
        )

        # Create result list
        result = builder.call(cg.list_new, [elem_size])
        result_ptr = builder.alloca(list_ptr_type, name="result")
        builder.store(result, result_ptr)

        # Phase 1: Copy elements [0, start) from original
        phase1_header = func.append_basic_block("phase1_header")
        phase1_body = func.append_basic_block("phase1_body")
        phase1_exit = func.append_basic_block("phase1_exit")

        i_ptr = builder.alloca(i64, name="i")
        builder.store(zero, i_ptr)
        builder.branch(phase1_header)

        builder.position_at_end(phase1_header)
        i = builder.load(i_ptr)
        cond = builder.icmp_signed("<", i, start_clamped)
        builder.cbranch(cond, phase1_body, phase1_exit)

        builder.position_at_end(phase1_body)
        elem_ptr = builder.call(cg.list_get, [orig_list, i])
        current = builder.load(result_ptr)
        updated = builder.call(cg.list_append, [current, elem_ptr, elem_size])
        builder.store(updated, result_ptr)
        builder.store(builder.add(i, one), i_ptr)
        builder.branch(phase1_header)

        # Phase 2: Copy elements [0, copy_len) from source
        builder.position_at_end(phase1_exit)
        phase2_header = func.append_basic_block("phase2_header")
        phase2_body = func.append_basic_block("phase2_body")
        phase2_exit = func.append_basic_block("phase2_exit")

        builder.store(zero, i_ptr)
        builder.branch(phase2_header)

        builder.position_at_end(phase2_header)
        i = builder.load(i_ptr)
        cond = builder.icmp_signed("<", i, copy_len)
        builder.cbranch(cond, phase2_body, phase2_exit)

        builder.position_at_end(phase2_body)
        elem_ptr = builder.call(cg.list_get, [source, i])
        current = builder.load(result_ptr)
        updated = builder.call(cg.list_append, [current, elem_ptr, elem_size])
        builder.store(updated, result_ptr)
        builder.store(builder.add(i, one), i_ptr)
        builder.branch(phase2_header)

        # Phase 3: Copy elements [end, orig_len) from original
        builder.position_at_end(phase2_exit)
        phase3_header = func.append_basic_block("phase3_header")
        phase3_body = func.append_basic_block("phase3_body")
        phase3_exit = func.append_basic_block("phase3_exit")

        builder.store(end_clamped, i_ptr)
        builder.branch(phase3_header)

        builder.position_at_end(phase3_header)
        i = builder.load(i_ptr)
        cond = builder.icmp_signed("<", i, orig_len)
        builder.cbranch(cond, phase3_body, phase3_exit)

        builder.position_at_end(phase3_body)
        elem_ptr = builder.call(cg.list_get, [orig_list, i])
        current = builder.load(result_ptr)
        updated = builder.call(cg.list_append, [current, elem_ptr, elem_size])
        builder.store(updated, result_ptr)
        builder.store(builder.add(i, one), i_ptr)
        builder.branch(phase3_header)

        builder.position_at_end(phase3_exit)
        final_result = builder.load(result_ptr)
        builder.ret(final_result)

    def _register_list_methods(self):
        """Register List as a type with methods."""
        cg = self.cg

        cg.type_registry["List"] = cg.list_struct
        cg.type_fields["List"] = []  # Internal structure, not user-accessible fields

        cg.type_methods["List"] = {
            "get": "coex_list_get",
            # "append" handled specially in _generate_method_call (needs alloca for element)
            "len": "coex_list_len",
            "size": "coex_list_size",
            "getrange": "coex_list_getrange",
            "setrange": "coex_list_setrange",
        }

        cg.functions["coex_list_new"] = cg.list_new
        cg.functions["coex_list_get"] = cg.list_get
        cg.functions["coex_list_append"] = cg.list_append
        cg.functions["coex_list_set"] = cg.list_set
        cg.functions["coex_list_len"] = cg.list_len
        cg.functions["coex_list_size"] = cg.list_size
        cg.functions["coex_list_copy"] = cg.list_copy
        cg.functions["coex_list_getrange"] = cg.list_getrange
        cg.functions["coex_list_setrange"] = cg.list_setrange
