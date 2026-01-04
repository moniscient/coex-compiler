"""
Array type implementation for Coex.

This module provides the Array type implementation for the Coex compiler.
Array is a dense, contiguous collection with value semantics. All 'mutation'
operations return a new array.

Array struct layout (Phase 4 - all i64 where applicable):
    Field 0: owner_handle (i64) - handle to data buffer
    Field 1: offset (i64) - byte offset into owner buffer (for slice views)
    Field 2: len (i64) - number of elements
    Field 3: cap (i64) - capacity (number of elements that fit in buffer)
    Field 4: elem_size (i64) - size of each element in bytes

Total size: 40 bytes (5 x 8-byte fields)

Slice views share the parent's data buffer (zero-copy). The offset field
allows slices to point to different positions within the same buffer.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ArrayGenerator:
    """Generates Array type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_array_helpers(self):
        """Create helper functions for Array operations.

        Array is a dense, contiguous collection with value semantics.
        All 'mutation' operations return a new array.
        """
        cg = self.cg

        array_ptr = cg.array_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # array_new(cap: i64, elem_size: i64) -> Array*
        array_new_ty = ir.FunctionType(array_ptr, [i64, i64])
        cg.array_new = ir.Function(cg.module, array_new_ty, name="coex_array_new")

        # array_get(arr: Array*, index: i64) -> i8*
        array_get_ty = ir.FunctionType(i8_ptr, [array_ptr, i64])
        cg.array_get = ir.Function(cg.module, array_get_ty, name="coex_array_get")

        # array_set(arr: Array*, index: i64, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element at index replaced
        array_set_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i8_ptr, i64])
        cg.array_set = ir.Function(cg.module, array_set_ty, name="coex_array_set")

        # array_append(arr: Array*, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element appended
        array_append_ty = ir.FunctionType(array_ptr, [array_ptr, i8_ptr, i64])
        cg.array_append = ir.Function(cg.module, array_append_ty, name="coex_array_append")

        # array_len(arr: Array*) -> i64
        array_len_ty = ir.FunctionType(i64, [array_ptr])
        cg.array_len = ir.Function(cg.module, array_len_ty, name="coex_array_len")

        # array_size(arr: Array*) -> i64 (total memory footprint)
        array_size_ty = ir.FunctionType(i64, [array_ptr])
        cg.array_size = ir.Function(cg.module, array_size_ty, name="coex_array_size")

        # array_copy(arr: Array*) -> Array* (deep copy for value semantics)
        array_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        cg.array_copy = ir.Function(cg.module, array_copy_ty, name="coex_array_copy")

        # array_deep_copy(arr: Array*) -> Array* (creates independent copy with new buffer)
        array_deep_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        cg.array_deep_copy = ir.Function(cg.module, array_deep_copy_ty, name="coex_array_deep_copy")

        # array_getrange(arr: Array*, start: i64, end: i64) -> Array*
        # Returns a VIEW (not a copy) of elements [start, end)
        array_getrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64])
        cg.array_getrange = ir.Function(cg.module, array_getrange_ty, name="coex_array_getrange")

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

    def _implement_array_new(self):
        """Implement array_new: allocate a new array with given capacity and element size.

        Struct layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }
        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_new
        func.args[0].name = "cap"
        func.args[1].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        cap = func.args[0]
        elem_size = func.args[1]

        # Allocate Array struct (40 bytes: 5 x 8-byte fields)
        array_size_const = ir.Constant(ir.IntType(64), 40)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_with_deref(builder, array_size_const, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Allocate data buffer first: cap * elem_size
        data_size = builder.mul(cap, elem_size)
        array_data_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY_DATA)
        data_ptr = cg.gc.alloc_with_deref(builder, data_size, array_data_type_id)

        # Initialize fields
        # owner_handle (field 0) - Phase 4: store as i64 handle
        owner_field_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.ptrtoint(data_ptr, ir.IntType(64))
        builder.store(owner_handle, owner_field_ptr)

        # offset = 0 (field 1) - new arrays own their data from the start
        offset_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), offset_ptr)

        # len = 0 (field 2)
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_ptr)

        # cap (field 3)
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        builder.store(cap, cap_ptr)

        # elem_size (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        builder.ret(array_ptr)

    def _implement_array_get(self):
        """Implement array_get: return pointer to element at index.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_get
        func.args[0].name = "arr"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        index = func.args[1]

        # Get elem_size (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Compute data pointer: owner + offset (Phase 4: owner is i64 handle)
        owner_handle_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        base_offset = builder.load(offset_ptr)
        data = builder.gep(owner, [base_offset])

        # Calculate element offset: index * elem_size
        elem_offset = builder.mul(index, elem_size)
        result = builder.gep(data, [elem_offset])

        builder.ret(result)

    def _implement_array_set(self):
        """Implement array_set: return a NEW array with element at index replaced.

        This implements value semantics - always creates a new array copy.
        No COW optimization - GC handles memory reclamation.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_set
        func.args[0].name = "arr"
        func.args[1].name = "index"
        func.args[2].name = "value"
        func.args[3].name = "elem_size"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        old_arr = func.args[0]
        index = func.args[1]
        value_ptr = func.args[2]
        elem_size = func.args[3]

        # Get old array's len (field 2) and cap (field 3)
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        old_cap_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        old_cap = builder.load(old_cap_ptr)

        # Create new array with same capacity (array_new sets offset=0)
        new_arr = builder.call(cg.array_new, [old_cap, elem_size])

        # Set new array's len to old len (field 2)
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(old_len, new_len_ptr)

        # Compute old data pointer: owner + offset (Phase 4: owner is i64 handle)
        old_owner_handle_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_owner_handle = builder.load(old_owner_handle_ptr)
        old_owner = builder.inttoptr(old_owner_handle, ir.IntType(8).as_pointer())
        old_offset_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_offset = builder.load(old_offset_ptr)
        old_data = builder.gep(old_owner, [old_offset])

        # New array has offset=0, so just load owner (Phase 4: owner is i64 handle)
        new_data_handle_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        new_data_handle = builder.load(new_data_handle_ptr)
        new_data = builder.inttoptr(new_data_handle, ir.IntType(8).as_pointer())

        copy_size = builder.mul(old_len, elem_size)
        builder.call(cg.memcpy, [new_data, old_data, copy_size])

        # Overwrite the element at index
        elem_offset = builder.mul(index, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(cg.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_append(self):
        """Implement array_append: return a NEW array with element appended.

        This implements value semantics - always creates a new array copy.
        No COW optimization - GC handles memory reclamation.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_append
        func.args[0].name = "arr"
        func.args[1].name = "value"
        func.args[2].name = "elem_size"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        old_arr = func.args[0]
        value_ptr = func.args[1]
        elem_size = func.args[2]

        # Get old array's len (field 2)
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        # New capacity = old_len + 1 (always create new array)
        new_cap = builder.add(old_len, ir.Constant(ir.IntType(64), 1))

        # Create new array (array_new sets offset=0)
        new_arr = builder.call(cg.array_new, [new_cap, elem_size])

        # Set new array's len = old_len + 1 (field 2)
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(new_cap, new_len_ptr)

        # Compute old data pointer: owner + offset (Phase 4: owner is i64 handle)
        old_owner_handle_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_owner_handle = builder.load(old_owner_handle_ptr)
        old_owner = builder.inttoptr(old_owner_handle, ir.IntType(8).as_pointer())
        old_offset_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_offset = builder.load(old_offset_ptr)
        old_data = builder.gep(old_owner, [old_offset])

        # New array has offset=0, so just load owner (Phase 4: owner is i64 handle)
        new_data_handle_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        new_data_handle = builder.load(new_data_handle_ptr)
        new_data = builder.inttoptr(new_data_handle, ir.IntType(8).as_pointer())

        copy_size = builder.mul(old_len, elem_size)
        builder.call(cg.memcpy, [new_data, old_data, copy_size])

        # Append the new element
        elem_offset = builder.mul(old_len, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(cg.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_len(self):
        """Implement array_len: return array length.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_len
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get len field (field 2)
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        length = builder.load(len_ptr)

        builder.ret(length)

    def _implement_array_size(self):
        """Implement array_size: return total memory footprint in bytes.

        Size = 40 (header, 5 x 8-byte fields) + cap * elem_size (data array)

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        cg = self.cg

        func = cg.array_size
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get cap field (field 3)
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Get elem_size field (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Size = 40 (header) + cap * elem_size
        data_size = builder.mul(cap, elem_size)
        total_size = builder.add(ir.Constant(ir.IntType(64), 40), data_size)

        builder.ret(total_size)

    def _implement_array_copy(self):
        """Implement array_copy: return same pointer for structural sharing.

        Array layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }
        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4

        With GC-managed memory, copying is just pointer sharing.
        GC keeps shared arrays alive; mutation creates new arrays.
        """
        cg = self.cg

        func = cg.array_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]

        # Just return the same pointer - GC handles memory management
        builder.ret(src)

    def _implement_array_deep_copy(self):
        """Create an independent copy of an array with its own data buffer.

        This is used by the = operator to ensure slice views become independent copies.
        Layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }

        1. Allocate new Array descriptor (40 bytes)
        2. Compute source data size: len * elem_size
        3. Allocate new data buffer
        4. Copy bytes from (source.owner + source.offset) to new buffer
        5. Set new descriptor: owner=new_buffer, offset=0, len=source.len, cap=source.len, elem_size=source.elem_size
        """
        cg = self.cg

        func = cg.array_deep_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Load source fields (Phase 4: owner is i64 handle)
        src_owner_handle_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        src_owner_handle = builder.load(src_owner_handle_ptr)
        src_owner = builder.inttoptr(src_owner_handle, ir.IntType(8).as_pointer())

        src_offset_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        src_len = builder.load(src_len_ptr)

        src_elem_size_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        src_elem_size = builder.load(src_elem_size_ptr)

        # Compute source data pointer: owner + offset
        src_data = builder.gep(src_owner, [src_offset])

        # Compute data size: len * elem_size
        data_size = builder.mul(src_len, src_elem_size)

        # Allocate new data buffer
        type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY_DATA)
        new_data = cg.gc.alloc_with_deref(builder, data_size, type_id)

        # Copy data from source to new buffer
        builder.call(cg.memcpy, [new_data, src_data, data_size])

        # Allocate new Array descriptor (40 bytes)
        struct_size = ir.Constant(i64, 40)
        array_type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, array_type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Store owner = new_data (Phase 4: owner is i64 handle)
        new_owner_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_owner_handle = builder.ptrtoint(new_data, i64)
        builder.store(new_owner_handle, new_owner_ptr)

        # Store offset = 0 (fresh allocation, not a view)
        new_offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), new_offset_ptr)

        # Store len = source.len
        new_len_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(src_len, new_len_ptr)

        # Store cap = source.len (copy has no extra capacity)
        new_cap_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(src_len, new_cap_ptr)

        # Store elem_size = source.elem_size
        new_elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(src_elem_size, new_elem_size_ptr)

        builder.ret(array_ptr)

    def _implement_array_getrange(self):
        """Create a slice VIEW of an array (zero-copy).

        Returns a new Array descriptor that shares the parent's data buffer.
        Layout: { i64 owner_handle, i64 offset, i64 len, i64 cap, i64 elem_size }
        Phase 4: owner is now i64 handle (copied directly for shared ownership).

        The slice's offset = parent.offset + (start * elem_size)
        The slice's len = end - start
        The slice shares the same owner handle (zero-copy).
        """
        cg = self.cg

        func = cg.array_getrange
        func.args[0].name = "arr"
        func.args[1].name = "start"
        func.args[2].name = "end"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        arr = func.args[0]
        start = func.args[1]
        end = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        # Load source fields (Phase 4: owner is i64 handle - copy directly for slice view)
        src_owner_handle_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        src_owner_handle = builder.load(src_owner_handle_ptr)

        src_offset_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        src_len = builder.load(src_len_ptr)

        src_elem_size_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        src_elem_size = builder.load(src_elem_size_ptr)

        # Clamp start to [0, len]
        start_neg = builder.icmp_signed("<", start, zero)
        start_over = builder.icmp_signed(">", start, src_len)
        start_clamped = builder.select(start_neg, zero, builder.select(start_over, src_len, start))

        # Clamp end to [start, len]
        end_under = builder.icmp_signed("<", end, start_clamped)
        end_over = builder.icmp_signed(">", end, src_len)
        end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, src_len, end))

        # Calculate new length
        new_len = builder.sub(end_clamped, start_clamped)

        # Calculate new offset: src_offset + (start * elem_size)
        start_bytes = builder.mul(start_clamped, src_elem_size)
        new_offset = builder.add(src_offset, start_bytes)

        # Allocate new Array descriptor (40 bytes) - NO data copy!
        struct_size = ir.Constant(i64, 40)
        type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Store owner handle (shared with source - this is the slice view!)
        new_owner_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(src_owner_handle, new_owner_ptr)

        # Store new offset
        new_offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_offset, new_offset_ptr)

        # Store new len
        new_len_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(new_len, new_len_ptr)

        # Store cap = len (slices have no extra capacity)
        new_cap_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(new_len, new_cap_ptr)

        # Store elem_size (same as source)
        new_elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(src_elem_size, new_elem_size_ptr)

        builder.ret(array_ptr)

    def _register_array_methods(self):
        """Register Array as a type with methods."""
        cg = self.cg

        cg.type_registry["Array"] = cg.array_struct
        cg.type_fields["Array"] = []  # Internal structure, not user-accessible fields

        cg.type_methods["Array"] = {
            "get": "coex_array_get",
            "len": "coex_array_len",
            "size": "coex_array_size",
            "getrange": "coex_array_getrange",
            # "set" and "append" handled specially (need alloca + return new array)
        }

        cg.functions["coex_array_new"] = cg.array_new
        cg.functions["coex_array_get"] = cg.array_get
        cg.functions["coex_array_set"] = cg.array_set
        cg.functions["coex_array_append"] = cg.array_append
        cg.functions["coex_array_len"] = cg.array_len
        cg.functions["coex_array_size"] = cg.array_size
        cg.functions["coex_array_copy"] = cg.array_copy
        cg.functions["coex_array_getrange"] = cg.array_getrange
