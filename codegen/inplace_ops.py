"""
In-Place Mutation Operations for Coex

This module provides in-place variants of collection update operations
for use when the uniqueness analysis determines the wrapper can be
mutated rather than copied.

These functions mutate the wrapper object in place:
- set_add_inplace: Add element to set, mutating wrapper
- set_remove_inplace: Remove element from set, mutating wrapper
- map_put_inplace: Put key-value pair in map, mutating wrapper
- map_remove_inplace: Remove key from map, mutating wrapper
- list_append_inplace: Append element to list, mutating wrapper

All operations still use structural sharing for internal nodes (HAMT, tree).
Only the wrapper object is mutated.
"""

from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class InplaceOpsGenerator:
    """Generates in-place mutation operations for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_inplace_operations(self):
        """Create all in-place mutation function declarations and implementations."""
        self._declare_set_inplace_ops()
        self._declare_map_inplace_ops()
        self._declare_list_inplace_ops()

        self._implement_set_add_inplace()
        self._implement_set_remove_inplace()
        self._implement_set_add_string_inplace()
        self._implement_map_put_inplace()
        self._implement_map_remove_inplace()
        self._implement_map_put_string_inplace()
        self._implement_list_append_inplace()

        self._register_inplace_functions()

    # ========================================================================
    # Set In-Place Operations
    # ========================================================================

    def _declare_set_inplace_ops(self):
        """Declare in-place Set operation function types."""
        cg = self.cg
        i64 = ir.IntType(64)
        void = ir.VoidType()
        set_ptr = cg.set_struct.as_pointer()
        string_ptr = cg.string_struct.as_pointer()

        # set_add_inplace(set: Set*, key: i64) -> void
        # Mutates set in place, adding the key
        set_add_inplace_ty = ir.FunctionType(void, [set_ptr, i64])
        cg.set_add_inplace = ir.Function(cg.module, set_add_inplace_ty, name="coex_set_add_inplace")

        # set_remove_inplace(set: Set*, key: i64) -> void
        # Mutates set in place, removing the key
        set_remove_inplace_ty = ir.FunctionType(void, [set_ptr, i64])
        cg.set_remove_inplace = ir.Function(cg.module, set_remove_inplace_ty, name="coex_set_remove_inplace")

        # set_add_string_inplace(set: Set*, key: String*) -> void
        set_add_string_inplace_ty = ir.FunctionType(void, [set_ptr, string_ptr])
        cg.set_add_string_inplace = ir.Function(cg.module, set_add_string_inplace_ty, name="coex_set_add_string_inplace")

    def _implement_set_add_inplace(self):
        """
        Implement set_add_inplace: mutate set wrapper in place.

        This is the key optimization function. Instead of:
        1. Call hamt_insert -> new_root
        2. Allocate NEW wrapper
        3. Store new_root in new wrapper
        4. Return new wrapper

        We do:
        1. Call hamt_insert -> new_root
        2. Store new_root in EXISTING wrapper
        3. Update len in existing wrapper
        4. Return void (no allocation)
        """
        cg = self.cg
        func = cg.set_add_inplace
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "added" flag
        added_ptr = builder.alloca(i32, name="added")

        # Insert into HAMT (value = 1 for sets, returns tagged handle i64)
        new_root = builder.call(cg.hamt_insert, [old_root, hash_val, key, ir.Constant(i64, 1), ir.Constant(i32, 0), added_ptr])

        # MUTATION: Store new root in existing wrapper (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Compute and store new len
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        builder.store(new_len, len_field)

        # Return void - no new wrapper allocated!
        builder.ret_void()

    def _implement_set_remove_inplace(self):
        """Implement set_remove_inplace: mutate set wrapper in place."""
        cg = self.cg
        func = cg.set_remove_inplace
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "removed" flag
        removed_ptr = builder.alloca(i32, name="removed")

        # Remove from HAMT (returns tagged handle i64)
        new_root = builder.call(cg.hamt_remove, [old_root, hash_val, key, ir.Constant(i32, 0), removed_ptr])

        # MUTATION: Store new root (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Update len
        removed = builder.load(removed_ptr)
        removed_64 = builder.zext(removed, i64)
        new_len = builder.sub(old_len, removed_64)
        builder.store(new_len, len_field)

        builder.ret_void()

    def _implement_set_add_string_inplace(self):
        """Implement set_add_string_inplace for string keys."""
        cg = self.cg
        func = cg.set_add_string_inplace
        func.args[0].name = "set"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(set_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash for string
        hash_val = builder.call(cg.string_hash, [key])

        # Alloca for "added" flag
        added_ptr = builder.alloca(i32, name="added")

        # Insert into HAMT using string variant (value = 1 for sets, returns tagged handle i64)
        new_root = builder.call(cg.hamt_insert_string, [old_root, hash_val, key, ir.Constant(i64, 1), ir.Constant(i32, 0), added_ptr])

        # MUTATION: Store new root (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Update len
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        builder.store(new_len, len_field)

        builder.ret_void()

    # ========================================================================
    # Map In-Place Operations
    # ========================================================================

    def _declare_map_inplace_ops(self):
        """Declare in-place Map operation function types."""
        cg = self.cg
        i64 = ir.IntType(64)
        void = ir.VoidType()
        map_ptr = cg.map_struct.as_pointer()
        string_ptr = cg.string_struct.as_pointer()

        # map_put_inplace(map: Map*, key: i64, value: i64) -> void
        map_put_inplace_ty = ir.FunctionType(void, [map_ptr, i64, i64])
        cg.map_put_inplace = ir.Function(cg.module, map_put_inplace_ty, name="coex_map_put_inplace")

        # map_remove_inplace(map: Map*, key: i64) -> void
        map_remove_inplace_ty = ir.FunctionType(void, [map_ptr, i64])
        cg.map_remove_inplace = ir.Function(cg.module, map_remove_inplace_ty, name="coex_map_remove_inplace")

        # map_put_string_inplace(map: Map*, key: String*, value: i64) -> void
        map_put_string_inplace_ty = ir.FunctionType(void, [map_ptr, string_ptr, i64])
        cg.map_put_string_inplace = ir.Function(cg.module, map_put_string_inplace_ty, name="coex_map_put_string_inplace")

    def _implement_map_put_inplace(self):
        """Implement map_put_inplace: mutate map wrapper in place."""
        cg = self.cg
        func = cg.map_put_inplace
        func.args[0].name = "map"
        func.args[1].name = "key"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]
        value = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "added" flag
        added_ptr = builder.alloca(i32, name="added")

        # Insert into HAMT (returns tagged handle i64)
        new_root = builder.call(cg.hamt_insert, [old_root, hash_val, key, value, ir.Constant(i32, 0), added_ptr])

        # MUTATION: Store new root (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Update len
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        builder.store(new_len, len_field)

        builder.ret_void()

    def _implement_map_remove_inplace(self):
        """Implement map_remove_inplace: mutate map wrapper in place."""
        cg = self.cg
        func = cg.map_remove_inplace
        func.args[0].name = "map"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash
        hash_val = builder.call(cg.map_hash, [key])

        # Alloca for "removed" flag
        removed_ptr = builder.alloca(i32, name="removed")

        # Remove from HAMT (returns tagged handle i64)
        new_root = builder.call(cg.hamt_remove, [old_root, hash_val, key, ir.Constant(i32, 0), removed_ptr])

        # MUTATION: Store new root (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Update len
        removed = builder.load(removed_ptr)
        removed_64 = builder.zext(removed, i64)
        new_len = builder.sub(old_len, removed_64)
        builder.store(new_len, len_field)

        builder.ret_void()

    def _implement_map_put_string_inplace(self):
        """Implement map_put_string_inplace for string keys."""
        cg = self.cg
        func = cg.map_put_string_inplace
        func.args[0].name = "map"
        func.args[1].name = "key"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        key = func.args[1]
        value = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        void_ptr = ir.IntType(8).as_pointer()

        # Get old root (tagged handle i64)
        root_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        old_root = builder.load(root_field)

        # Get old len
        len_field = builder.gep(map_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        old_len = builder.load(len_field)

        # Compute hash for string key
        hash_val = builder.call(cg.string_hash, [key])

        # Alloca for "added" flag
        added_ptr = builder.alloca(i32, name="added")

        # Insert into HAMT using string variant (returns tagged handle i64)
        new_root = builder.call(cg.hamt_insert_string, [old_root, hash_val, key, value, ir.Constant(i32, 0), added_ptr])

        # MUTATION: Store new root (already tagged handle i64)
        builder.store(new_root, root_field)

        # MUTATION: Update len
        added = builder.load(added_ptr)
        added_64 = builder.zext(added, i64)
        new_len = builder.add(old_len, added_64)
        builder.store(new_len, len_field)

        builder.ret_void()

    # ========================================================================
    # List In-Place Operations
    # ========================================================================

    def _declare_list_inplace_ops(self):
        """Declare in-place List operation function types.

        Note: List append is more complex due to its signature (elem_ptr, elem_size).
        For Phase 1, we skip list in-place ops and focus on Set/Map.
        This can be added in a future iteration.
        """
        # Skip for Phase 1 - list_append has complex signature
        pass

    def _implement_list_append_inplace(self):
        """
        Placeholder for list append in-place.

        The list_append function has signature:
            list_append(list: List*, elem: i8*, elem_size: i64) -> List*

        This is more complex than Set/Map because:
        1. Element is passed as pointer + size
        2. Need to handle the indirect element storage

        For Phase 1, we skip this optimization.
        """
        # Skip for Phase 1
        pass

    # ========================================================================
    # Registration
    # ========================================================================

    def _register_inplace_functions(self):
        """Register in-place functions in the codegen functions dict."""
        cg = self.cg

        # Set in-place ops
        cg.functions["coex_set_add_inplace"] = cg.set_add_inplace
        cg.functions["coex_set_remove_inplace"] = cg.set_remove_inplace
        cg.functions["coex_set_add_string_inplace"] = cg.set_add_string_inplace

        # Map in-place ops
        cg.functions["coex_map_put_inplace"] = cg.map_put_inplace
        cg.functions["coex_map_remove_inplace"] = cg.map_remove_inplace
        cg.functions["coex_map_put_string_inplace"] = cg.map_put_string_inplace

        # List in-place ops - skipped for Phase 1 (complex signature)
        # cg.functions["coex_list_append_inplace"] = cg.list_append_inplace

        # Store mapping from normal method to in-place variant
        cg.inplace_variants = {
            "coex_set_add": "coex_set_add_inplace",
            "coex_set_remove": "coex_set_remove_inplace",
            "coex_set_add_string": "coex_set_add_string_inplace",
            "coex_map_set": "coex_map_put_inplace",
            "coex_map_put": "coex_map_put_inplace",
            "coex_map_remove": "coex_map_remove_inplace",
            "coex_map_set_string": "coex_map_put_string_inplace",
            "coex_map_put_string": "coex_map_put_string_inplace",
            # Array in-place ops
            "coex_array_set": "coex_array_set_inplace",
            # List in-place ops skipped for Phase 1
            # "coex_list_append": "coex_list_append_inplace",
        }


def create_inplace_operations(codegen: 'CodeGenerator'):
    """Create all in-place mutation operations."""
    generator = InplaceOpsGenerator(codegen)
    generator.create_inplace_operations()
