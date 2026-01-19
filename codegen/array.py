"""
Array type implementation for Coex.

This module provides the Array<T> type implementation for the Coex compiler.
Array is a dense, N-dimensional collection with value semantics. All 'mutation'
operations return a new array.

N-D Array struct layout (104 bytes = 13 i64 fields):
    Field 0: handle (i64) - GC handle for data buffer
    Field 1: ndim (i64) - number of dimensions (1, 2, ...)
    Field 2: shape [4 x i64] - dimensions [dim0, dim1, dim2, dim3]
    Field 3: strides [4 x i64] - byte strides per dimension
    Field 4: offset (i64) - byte offset into buffer (for views)
    Field 5: elem_size (i64) - 8 for int/float, 1 for byte
    Field 6: type_id (i64) - element type identifier

For 1D arrays:
    - ndim = 1
    - shape[0] = len (number of elements)
    - shape[1..3] = 0 (unused)
    - strides[0] = elem_size
    - strides[1..3] = 0 (unused)

For 2D arrays:
    - ndim = 2
    - shape = [rows, cols, 0, 0]
    - strides = [cols * elem_size, elem_size, 0, 0]

Slice views share the parent's data buffer (zero-copy). The offset field
allows slices to point to different positions within the same buffer.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator

# Field index constants for the new N-D array struct
ARRAY_FIELD_HANDLE = 0
ARRAY_FIELD_NDIM = 1
ARRAY_FIELD_SHAPE = 2
ARRAY_FIELD_STRIDES = 3
ARRAY_FIELD_OFFSET = 4
ARRAY_FIELD_ELEM_SIZE = 5
ARRAY_FIELD_TYPE_ID = 6

# Array struct size in bytes (13 i64 fields = 104 bytes)
ARRAY_STRUCT_SIZE = 104


class ArrayGenerator:
    """Generates Array type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_array_helpers(self):
        """Create helper functions for Array operations.

        Array is a dense, N-dimensional collection with value semantics.
        All 'mutation' operations return a new array.
        """
        cg = self.cg

        array_ptr = cg.array_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # array_new(len: i64, elem_size: i64) -> Array*
        # Creates a new 1D array with given length
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

        # array_copy(arr: Array*) -> Array* (structural sharing)
        array_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        cg.array_copy = ir.Function(cg.module, array_copy_ty, name="coex_array_copy")

        # array_deep_copy(arr: Array*) -> Array* (creates independent copy with new buffer)
        array_deep_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        cg.array_deep_copy = ir.Function(cg.module, array_deep_copy_ty, name="coex_array_deep_copy")

        # array_getrange(arr: Array*, start: i64, end: i64) -> Array*
        # Returns a VIEW (not a copy) of elements [start, end) - 1D only
        array_getrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64])
        cg.array_getrange = ir.Function(cg.module, array_getrange_ty, name="coex_array_getrange")

        # array_filled(size: i64, elem_size: i64) -> Array*
        # Creates a new 1D array with len=size (data initialized to zero by GC)
        array_filled_ty = ir.FunctionType(array_ptr, [i64, i64])
        cg.array_filled = ir.Function(cg.module, array_filled_ty, name="coex_array_filled")

        # array_set_inplace(arr: Array*, index: i64, value: i8*, elem_size: i64) -> void
        # Mutates the array in place (only safe when array is unique/unaliased)
        array_set_inplace_ty = ir.FunctionType(ir.VoidType(), [array_ptr, i64, i8_ptr, i64])
        cg.array_set_inplace = ir.Function(cg.module, array_set_inplace_ty, name="coex_array_set_inplace")

        # array_ndim(arr: Array*) -> i64
        array_ndim_ty = ir.FunctionType(i64, [array_ptr])
        cg.array_ndim = ir.Function(cg.module, array_ndim_ty, name="coex_array_ndim")

        # array_shape(arr: Array*, dim: i64) -> i64
        # Returns shape[dim] for the given dimension
        array_shape_ty = ir.FunctionType(i64, [array_ptr, i64])
        cg.array_shape = ir.Function(cg.module, array_shape_ty, name="coex_array_shape")

        # array_new_2d(rows: i64, cols: i64, elem_size: i64) -> Array*
        # Creates a new 2D array with given dimensions
        array_new_2d_ty = ir.FunctionType(array_ptr, [i64, i64, i64])
        cg.array_new_2d = ir.Function(cg.module, array_new_2d_ty, name="coex_array_new_2d")

        # array_get_2d(arr: Array*, row: i64, col: i64) -> i8*
        # Get element at (row, col) in 2D array
        array_get_2d_ty = ir.FunctionType(i8_ptr, [array_ptr, i64, i64])
        cg.array_get_2d = ir.Function(cg.module, array_get_2d_ty, name="coex_array_get_2d")

        # array_total_size(arr: Array*) -> i64
        # Returns total number of elements (product of all shape dimensions)
        array_total_size_ty = ir.FunctionType(i64, [array_ptr])
        cg.array_total_size = ir.Function(cg.module, array_total_size_ty, name="coex_array_total_size")

        # Implement all functions
        self._implement_array_new()
        self._implement_array_filled()
        self._implement_array_set_inplace()
        self._implement_array_get()
        self._implement_array_set()
        self._implement_array_append()
        self._implement_array_len()
        self._implement_array_size()
        self._implement_array_copy()
        self._implement_array_deep_copy()
        self._implement_array_getrange()
        self._implement_array_ndim()
        self._implement_array_shape()
        self._implement_array_new_2d()
        self._implement_array_get_2d()
        self._implement_array_total_size()
        self._register_array_methods()

    def _get_array_data_ptr(self, builder, array_ptr):
        """Get pointer to data buffer from array struct.

        Returns: i8* pointing to (handle + offset)
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get handle (field 0)
        handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        handle = builder.load(handle_ptr)
        data_base = builder.inttoptr(handle, ir.IntType(8).as_pointer())

        # Get offset (field 4)
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        offset = builder.load(offset_ptr)

        # Return data_base + offset
        return builder.gep(data_base, [offset])

    def _get_array_len(self, builder, array_ptr):
        """Get length (shape[0]) from array struct for 1D arrays."""
        i32 = ir.IntType(32)

        # Get shape[0] (field 2, index 0)
        shape0_ptr = builder.gep(array_ptr, [
            ir.Constant(i32, 0),
            ir.Constant(i32, ARRAY_FIELD_SHAPE),
            ir.Constant(i32, 0)
        ], inbounds=True)
        return builder.load(shape0_ptr)

    def _get_array_elem_size(self, builder, array_ptr):
        """Get elem_size from array struct."""
        i32 = ir.IntType(32)

        elem_size_ptr = builder.gep(array_ptr, [
            ir.Constant(i32, 0),
            ir.Constant(i32, ARRAY_FIELD_ELEM_SIZE)
        ], inbounds=True)
        return builder.load(elem_size_ptr)

    def _init_1d_array_fields(self, builder, array_ptr, length, elem_size, data_ptr, offset=None):
        """Initialize all fields of a 1D array struct.

        Args:
            builder: LLVM IR builder
            array_ptr: Pointer to array struct
            length: Number of elements (i64)
            elem_size: Size of each element in bytes (i64)
            data_ptr: Pointer to data buffer (i8*)
            offset: Byte offset into buffer, defaults to 0
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        if offset is None:
            offset = zero

        # Field 0: handle (pointer as i64)
        handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        handle = builder.ptrtoint(data_ptr, i64)
        builder.store(handle, handle_ptr)

        # Field 1: ndim = 1
        ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        builder.store(ir.Constant(i64, 1), ndim_ptr)

        # Field 2: shape = [length, 0, 0, 0]
        for i in range(4):
            shape_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_SHAPE),
                ir.Constant(i32, i)
            ], inbounds=True)
            val = length if i == 0 else zero
            builder.store(val, shape_i_ptr)

        # Field 3: strides = [elem_size, 0, 0, 0]
        for i in range(4):
            stride_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_STRIDES),
                ir.Constant(i32, i)
            ], inbounds=True)
            val = elem_size if i == 0 else zero
            builder.store(val, stride_i_ptr)

        # Field 4: offset
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        builder.store(offset, offset_ptr)

        # Field 5: elem_size
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_ELEM_SIZE)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        # Field 6: type_id = 0 (generic, set by caller if needed)
        type_id_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        builder.store(zero, type_id_ptr)

    def _implement_array_new(self):
        """Implement array_new: allocate a new 1D array with given length.

        Note: This replaces the old "capacity" model. Now len and cap are the same.
        For 1D arrays: shape[0] = len, strides[0] = elem_size
        """
        cg = self.cg

        func = cg.array_new
        func.args[0].name = "len"
        func.args[1].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        length = func.args[0]
        elem_size = func.args[1]
        i64 = ir.IntType(64)

        # Allocate Array struct (104 bytes)
        array_size_const = ir.Constant(i64, ARRAY_STRUCT_SIZE)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, array_size_const, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Allocate data buffer: len * elem_size
        data_size = builder.mul(length, elem_size)
        array_data_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY_DATA)
        data_ptr = cg.gc.alloc_arena_or_gc(builder, data_size, array_data_type_id)

        # Initialize all fields for 1D array
        self._init_1d_array_fields(builder, array_ptr, length, elem_size, data_ptr)

        builder.ret(array_ptr)

    def _implement_array_filled(self):
        """Implement array_filled: allocate a new 1D array with given size.

        Same as array_new but with a clearer name. Data is zeroed by GC allocator.
        """
        cg = self.cg

        func = cg.array_filled
        func.args[0].name = "size"
        func.args[1].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        size = func.args[0]
        elem_size = func.args[1]
        i64 = ir.IntType(64)

        # Allocate Array struct (104 bytes)
        array_size_const = ir.Constant(i64, ARRAY_STRUCT_SIZE)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, array_size_const, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Allocate data buffer: size * elem_size
        data_size = builder.mul(size, elem_size)
        array_data_type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_ARRAY_DATA)
        data_ptr = cg.gc.alloc_arena_or_gc(builder, data_size, array_data_type_id)

        # Initialize all fields for 1D array
        self._init_1d_array_fields(builder, array_ptr, size, elem_size, data_ptr)

        builder.ret(array_ptr)

    def _implement_array_set_inplace(self):
        """Implement array_set_inplace: mutate element at index IN PLACE.

        This is the unsafe/optimized version that modifies the array directly.
        Only safe when the array is provably unique (not aliased).
        """
        cg = self.cg

        func = cg.array_set_inplace
        func.args[0].name = "arr"
        func.args[1].name = "index"
        func.args[2].name = "value"
        func.args[3].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        index = func.args[1]
        value_ptr = func.args[2]
        elem_size = func.args[3]

        # Get data pointer
        data = self._get_array_data_ptr(builder, array_ptr)

        # Calculate element offset: index * elem_size
        elem_offset = builder.mul(index, elem_size)
        dest = builder.gep(data, [elem_offset])

        # Copy value to destination
        builder.call(cg.memcpy, [dest, value_ptr, elem_size])

        builder.ret_void()

    def _implement_array_get(self):
        """Implement array_get: return pointer to element at index (1D)."""
        cg = self.cg

        func = cg.array_get
        func.args[0].name = "arr"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        index = func.args[1]

        # Get elem_size
        elem_size = self._get_array_elem_size(builder, array_ptr)

        # Get data pointer
        data = self._get_array_data_ptr(builder, array_ptr)

        # Calculate element offset: index * elem_size
        elem_offset = builder.mul(index, elem_size)
        result = builder.gep(data, [elem_offset])

        builder.ret(result)

    def _implement_array_set(self):
        """Implement array_set: return a NEW 1D array with element at index replaced.

        This implements value semantics - always creates a new array copy.
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
        i64 = ir.IntType(64)

        # Get old array's length (shape[0])
        old_len = self._get_array_len(builder, old_arr)

        # Create new array with same length
        new_arr = builder.call(cg.array_new, [old_len, elem_size])

        # Copy all data from old to new
        old_data = self._get_array_data_ptr(builder, old_arr)
        new_data = self._get_array_data_ptr(builder, new_arr)
        copy_size = builder.mul(old_len, elem_size)
        builder.call(cg.memcpy, [new_data, old_data, copy_size])

        # Overwrite the element at index
        elem_offset = builder.mul(index, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(cg.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_append(self):
        """Implement array_append: return a NEW 1D array with element appended.

        This implements value semantics - always creates a new array copy.
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
        i64 = ir.IntType(64)

        # Get old array's length
        old_len = self._get_array_len(builder, old_arr)

        # New length = old_len + 1
        new_len = builder.add(old_len, ir.Constant(i64, 1))

        # Create new array
        new_arr = builder.call(cg.array_new, [new_len, elem_size])

        # Copy old data
        old_data = self._get_array_data_ptr(builder, old_arr)
        new_data = self._get_array_data_ptr(builder, new_arr)
        copy_size = builder.mul(old_len, elem_size)
        builder.call(cg.memcpy, [new_data, old_data, copy_size])

        # Append the new element
        elem_offset = builder.mul(old_len, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(cg.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_len(self):
        """Implement array_len: return shape[0] (1D length)."""
        cg = self.cg

        func = cg.array_len
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        length = self._get_array_len(builder, array_ptr)
        builder.ret(length)

    def _implement_array_size(self):
        """Implement array_size: return total memory footprint in bytes.

        Size = 104 (header) + total_elements * elem_size
        For 1D: total_elements = shape[0]
        For N-D: total_elements = product of all shape dimensions
        """
        cg = self.cg

        func = cg.array_size
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get total elements and elem_size
        total_elements = builder.call(cg.array_total_size, [array_ptr])
        elem_size = self._get_array_elem_size(builder, array_ptr)

        # Size = 104 (header) + total_elements * elem_size
        data_size = builder.mul(total_elements, elem_size)
        total_size = builder.add(ir.Constant(i64, ARRAY_STRUCT_SIZE), data_size)

        builder.ret(total_size)

    def _implement_array_copy(self):
        """Implement array_copy: return same pointer for structural sharing.

        With GC-managed memory, copying is just pointer sharing.
        GC keeps shared arrays alive; mutation creates new arrays.
        """
        cg = self.cg

        func = cg.array_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]
        builder.ret(src)

    def _implement_array_deep_copy(self):
        """Create an independent copy of an array with its own data buffer.

        This is used by the = operator to ensure slice views become independent copies.
        """
        cg = self.cg

        func = cg.array_deep_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get total elements count
        total_elements = builder.call(cg.array_total_size, [src])

        # Get elem_size
        elem_size = self._get_array_elem_size(builder, src)

        # Compute data size
        data_size = builder.mul(total_elements, elem_size)

        # Allocate new data buffer
        type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY_DATA)
        new_data = cg.gc.alloc_arena_or_gc(builder, data_size, type_id)

        # Copy data from source
        src_data = self._get_array_data_ptr(builder, src)
        builder.call(cg.memcpy, [new_data, src_data, data_size])

        # Allocate new Array descriptor (104 bytes)
        struct_size = ir.Constant(i64, ARRAY_STRUCT_SIZE)
        array_type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, struct_size, array_type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Copy all fields from source, but with new data buffer and offset=0

        # Field 0: handle = new_data
        handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        handle = builder.ptrtoint(new_data, i64)
        builder.store(handle, handle_ptr)

        # Field 1: ndim (copy from source)
        src_ndim_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        ndim = builder.load(src_ndim_ptr)
        dst_ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        builder.store(ndim, dst_ndim_ptr)

        # Field 2: shape (copy from source)
        for i in range(4):
            src_shape_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_SHAPE), ir.Constant(i32, i)], inbounds=True)
            shape_val = builder.load(src_shape_ptr)
            dst_shape_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_SHAPE), ir.Constant(i32, i)], inbounds=True)
            builder.store(shape_val, dst_shape_ptr)

        # Field 3: strides (copy from source)
        for i in range(4):
            src_stride_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_STRIDES), ir.Constant(i32, i)], inbounds=True)
            stride_val = builder.load(src_stride_ptr)
            dst_stride_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_STRIDES), ir.Constant(i32, i)], inbounds=True)
            builder.store(stride_val, dst_stride_ptr)

        # Field 4: offset = 0 (fresh allocation)
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        builder.store(ir.Constant(i64, 0), offset_ptr)

        # Field 5: elem_size (copy from source)
        dst_elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_ELEM_SIZE)], inbounds=True)
        builder.store(elem_size, dst_elem_size_ptr)

        # Field 6: type_id (copy from source)
        src_type_id_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        type_id_val = builder.load(src_type_id_ptr)
        dst_type_id_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        builder.store(type_id_val, dst_type_id_ptr)

        builder.ret(array_ptr)

    def _implement_array_getrange(self):
        """Create a slice VIEW of a 1D array (zero-copy).

        Returns a new Array descriptor that shares the parent's data buffer.
        For 1D arrays only - slicing reduces the view but doesn't change ndim.
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

        # Load source fields
        src_handle_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        src_handle = builder.load(src_handle_ptr)

        src_offset_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len = self._get_array_len(builder, arr)
        elem_size = self._get_array_elem_size(builder, arr)

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
        start_bytes = builder.mul(start_clamped, elem_size)
        new_offset = builder.add(src_offset, start_bytes)

        # Allocate new Array descriptor (104 bytes) - NO data copy!
        struct_size = ir.Constant(i64, ARRAY_STRUCT_SIZE)
        type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, struct_size, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Field 0: handle (shared with source)
        new_handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        builder.store(src_handle, new_handle_ptr)

        # Field 1: ndim = 1
        ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        builder.store(ir.Constant(i64, 1), ndim_ptr)

        # Field 2: shape = [new_len, 0, 0, 0]
        for i in range(4):
            shape_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_SHAPE),
                ir.Constant(i32, i)
            ], inbounds=True)
            val = new_len if i == 0 else zero
            builder.store(val, shape_i_ptr)

        # Field 3: strides = [elem_size, 0, 0, 0]
        for i in range(4):
            stride_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_STRIDES),
                ir.Constant(i32, i)
            ], inbounds=True)
            val = elem_size if i == 0 else zero
            builder.store(val, stride_i_ptr)

        # Field 4: offset (new offset)
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        builder.store(new_offset, offset_ptr)

        # Field 5: elem_size
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_ELEM_SIZE)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        # Field 6: type_id (copy from source)
        src_type_id_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        type_id_val = builder.load(src_type_id_ptr)
        dst_type_id_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        builder.store(type_id_val, dst_type_id_ptr)

        builder.ret(array_ptr)

    def _implement_array_ndim(self):
        """Implement array_ndim: return number of dimensions."""
        cg = self.cg

        func = cg.array_ndim
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        i32 = ir.IntType(32)

        ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        ndim = builder.load(ndim_ptr)
        builder.ret(ndim)

    def _implement_array_shape(self):
        """Implement array_shape: return shape[dim]."""
        cg = self.cg

        func = cg.array_shape
        func.args[0].name = "arr"
        func.args[1].name = "dim"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        dim = func.args[1]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Clamp dim to [0, 3]
        dim_clamped = builder.select(
            builder.icmp_signed("<", dim, ir.Constant(i64, 0)),
            ir.Constant(i64, 0),
            builder.select(
                builder.icmp_signed(">", dim, ir.Constant(i64, 3)),
                ir.Constant(i64, 3),
                dim
            )
        )
        dim32 = builder.trunc(dim_clamped, i32)

        shape_ptr = builder.gep(array_ptr, [
            ir.Constant(i32, 0),
            ir.Constant(i32, ARRAY_FIELD_SHAPE),
            dim32
        ], inbounds=True)
        shape_val = builder.load(shape_ptr)
        builder.ret(shape_val)

    def _implement_array_new_2d(self):
        """Implement array_new_2d: create a new 2D array with given dimensions."""
        cg = self.cg

        func = cg.array_new_2d
        func.args[0].name = "rows"
        func.args[1].name = "cols"
        func.args[2].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        rows = func.args[0]
        cols = func.args[1]
        elem_size = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        # Allocate Array struct (104 bytes)
        array_size_const = ir.Constant(i64, ARRAY_STRUCT_SIZE)
        type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, array_size_const, type_id)
        array_ptr = builder.bitcast(raw_ptr, cg.array_struct.as_pointer())

        # Allocate data buffer: rows * cols * elem_size
        total_elements = builder.mul(rows, cols)
        data_size = builder.mul(total_elements, elem_size)
        array_data_type_id = ir.Constant(i32, cg.gc.TYPE_ARRAY_DATA)
        data_ptr = cg.gc.alloc_arena_or_gc(builder, data_size, array_data_type_id)

        # Field 0: handle
        handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        handle = builder.ptrtoint(data_ptr, i64)
        builder.store(handle, handle_ptr)

        # Field 1: ndim = 2
        ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        builder.store(ir.Constant(i64, 2), ndim_ptr)

        # Field 2: shape = [rows, cols, 0, 0]
        shape_vals = [rows, cols, zero, zero]
        for i, val in enumerate(shape_vals):
            shape_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_SHAPE),
                ir.Constant(i32, i)
            ], inbounds=True)
            builder.store(val, shape_i_ptr)

        # Field 3: strides = [cols * elem_size, elem_size, 0, 0]
        # Row stride = cols * elem_size (to skip to next row)
        # Col stride = elem_size (to skip to next column)
        row_stride = builder.mul(cols, elem_size)
        stride_vals = [row_stride, elem_size, zero, zero]
        for i, val in enumerate(stride_vals):
            stride_i_ptr = builder.gep(array_ptr, [
                ir.Constant(i32, 0),
                ir.Constant(i32, ARRAY_FIELD_STRIDES),
                ir.Constant(i32, i)
            ], inbounds=True)
            builder.store(val, stride_i_ptr)

        # Field 4: offset = 0
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        builder.store(zero, offset_ptr)

        # Field 5: elem_size
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_ELEM_SIZE)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        # Field 6: type_id = 0
        type_id_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_TYPE_ID)], inbounds=True)
        builder.store(zero, type_id_ptr)

        builder.ret(array_ptr)

    def _implement_array_get_2d(self):
        """Implement array_get_2d: return pointer to element at (row, col) in 2D array."""
        cg = self.cg

        func = cg.array_get_2d
        func.args[0].name = "arr"
        func.args[1].name = "row"
        func.args[2].name = "col"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        row = func.args[1]
        col = func.args[2]
        i32 = ir.IntType(32)

        # Get data base pointer
        handle_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_HANDLE)], inbounds=True)
        handle = builder.load(handle_ptr)
        data_base = builder.inttoptr(handle, ir.IntType(8).as_pointer())

        # Get offset
        offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_OFFSET)], inbounds=True)
        offset = builder.load(offset_ptr)

        # Get strides
        stride0_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_STRIDES), ir.Constant(i32, 0)], inbounds=True)
        stride0 = builder.load(stride0_ptr)  # row stride
        stride1_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_STRIDES), ir.Constant(i32, 1)], inbounds=True)
        stride1 = builder.load(stride1_ptr)  # col stride

        # Calculate byte offset: offset + row * stride0 + col * stride1
        row_offset = builder.mul(row, stride0)
        col_offset = builder.mul(col, stride1)
        total_offset = builder.add(offset, builder.add(row_offset, col_offset))

        # Return pointer to element
        result = builder.gep(data_base, [total_offset])
        builder.ret(result)

    def _implement_array_total_size(self):
        """Implement array_total_size: return product of all shape dimensions up to ndim."""
        cg = self.cg

        func = cg.array_total_size
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get ndim
        ndim_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_NDIM)], inbounds=True)
        ndim = builder.load(ndim_ptr)

        # Compute product of shape[0..ndim-1]
        # We'll use a simple loop unrolling since max ndim is 4

        # Start with 1
        one = ir.Constant(i64, 1)

        # Get all shape values
        shape_ptrs = []
        for i in range(4):
            ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, ARRAY_FIELD_SHAPE), ir.Constant(i32, i)], inbounds=True)
            shape_ptrs.append(ptr)

        # Load shape values
        shapes = [builder.load(ptr) for ptr in shape_ptrs]

        # Compute product based on ndim
        # If ndim >= 1, multiply by shape[0]
        # If ndim >= 2, multiply by shape[1]
        # etc.

        result = one
        for i in range(4):
            cmp = builder.icmp_signed(">", ndim, ir.Constant(i64, i))
            factor = builder.select(cmp, shapes[i], one)
            result = builder.mul(result, factor)

        builder.ret(result)

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
            "ndim": "coex_array_ndim",
            "shape": "coex_array_shape",
            "total_size": "coex_array_total_size",
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
        cg.functions["coex_array_filled"] = cg.array_filled
        cg.functions["coex_array_set_inplace"] = cg.array_set_inplace
        cg.functions["coex_array_ndim"] = cg.array_ndim
        cg.functions["coex_array_shape"] = cg.array_shape
        cg.functions["coex_array_new_2d"] = cg.array_new_2d
        cg.functions["coex_array_get_2d"] = cg.array_get_2d
        cg.functions["coex_array_total_size"] = cg.array_total_size
        cg.functions["coex_array_deep_copy"] = cg.array_deep_copy
