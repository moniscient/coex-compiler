"""
Marshaling Code Generation for GPU Offload.

This module generates LLVM IR to convert between Coex Arrays and contiguous
GPU buffers. The Array type is the only collection type supported for GPU
offload - Lists/Maps/Sets must be implicitly cast to Array first.

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
"""

from typing import TYPE_CHECKING, Tuple
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


# Coex type to byte size mapping
ELEMENT_SIZES = {
    'int': 8,        # i64
    'int64': 8,      # i64
    'int32': 4,      # i32
    'float': 8,      # f64 (Coex floats are 64-bit)
    'float64': 8,    # f64
    'float32': 4,    # f32
    'bool': 1,       # i8 (stored as byte)
    'byte': 1,       # i8
}


def get_element_size(coex_type: str) -> int:
    """Return byte size for a Coex primitive type.

    Args:
        coex_type: Coex type name (e.g., 'int', 'float', 'bool')

    Returns:
        Size in bytes.

    Raises:
        ValueError: If type is not supported for GPU offload.
    """
    if coex_type in ELEMENT_SIZES:
        return ELEMENT_SIZES[coex_type]
    raise ValueError(f"Unsupported element type for GPU offload: {coex_type}")


class MarshalingGenerator:
    """Generates LLVM IR for Array <-> buffer conversions."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    def array_to_buffer(self, builder: ir.IRBuilder, array_ptr: ir.Value) -> Tuple[ir.Value, ir.Value, ir.Value]:
        """Extract contiguous buffer from Array - ZERO-COPY!

        N-D Array layout:
            Field 0: handle (i64)
            Field 1: ndim (i64)
            Field 2: shape [4 x i64]
            Field 3: strides [4 x i64]
            Field 4: offset (i64)
            Field 5: elem_size (i64)
            Field 6: type_id (i64)

        This is a zero-copy operation - we return a pointer directly into the
        Array's data buffer. The caller must ensure the Array remains live
        (rooted in GC) for the duration of GPU execution.

        Args:
            builder: LLVM IR builder
            array_ptr: Pointer to Array struct

        Returns:
            Tuple of (data_ptr: i8*, count: i64, elem_size: i64)
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Load handle (field 0) - this is a raw pointer stored as i64 (ptrtoint)
        handle_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True
        )
        handle = builder.load(handle_ptr)

        # Convert i64 back to pointer via inttoptr
        buffer_ptr = builder.inttoptr(handle, i8_ptr)

        # Load offset (field 4)
        offset_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 4)],
            inbounds=True
        )
        offset = builder.load(offset_ptr)

        # Compute data_ptr = buffer + offset
        data_ptr = builder.gep(buffer_ptr, [offset])

        # Load element count from shape[0] (field 2, element 0)
        # For 1D arrays, shape[0] is the length
        shape_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 2), ir.Constant(i32, 0)],
            inbounds=True
        )
        count = builder.load(shape_ptr)

        # Load elem_size (field 5)
        elem_size_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 5)],
            inbounds=True
        )
        elem_size = builder.load(elem_size_ptr)

        return data_ptr, count, elem_size

    def buffer_to_array(
        self,
        builder: ir.IRBuilder,
        buffer_ptr: ir.Value,
        count: ir.Value,
        elem_size: ir.Value
    ) -> ir.Value:
        """Convert GPU output buffer to Coex Array.

        Creates a new Array struct and copies the buffer contents into it.

        Args:
            builder: LLVM IR builder
            buffer_ptr: Pointer to contiguous buffer (i8*)
            count: Number of elements (i64)
            elem_size: Size of each element in bytes (i64)

        Returns:
            Pointer to newly allocated Array struct
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Call array_filled(count, elem_size) to allocate with len=count
        array_ptr = builder.call(self.cg.array_filled, [count, elem_size])

        # Get the array's data pointer
        # Field 0 is a raw pointer stored as i64 (ptrtoint), convert back to pointer
        handle_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True
        )
        handle = builder.load(handle_ptr)
        dest_ptr = builder.inttoptr(handle, i8_ptr)

        # Compute copy size: count * elem_size
        copy_size = builder.mul(count, elem_size)

        # memcpy(dest_ptr, buffer_ptr, count * elem_size)
        builder.call(self.cg.memcpy, [dest_ptr, buffer_ptr, copy_size])

        return array_ptr

    def allocate_output_buffer(
        self,
        builder: ir.IRBuilder,
        count: ir.Value,
        elem_size: ir.Value
    ) -> ir.Value:
        """Allocate a buffer for GPU output.

        Args:
            builder: LLVM IR builder
            count: Number of elements (i64)
            elem_size: Size of each element in bytes (i64)

        Returns:
            Pointer to allocated buffer (i8*)
        """
        # Compute size: count * elem_size
        size = builder.mul(count, elem_size)

        # Allocate via malloc (not GC - this is temporary for GPU)
        return builder.call(self.cg.malloc, [size])

    def free_output_buffer(self, builder: ir.IRBuilder, buffer_ptr: ir.Value):
        """Free a GPU output buffer.

        Args:
            builder: LLVM IR builder
            buffer_ptr: Pointer to buffer to free
        """
        builder.call(self.cg.free, [buffer_ptr])

    def ensure_malloc_free(self):
        """Ensure malloc and free functions are declared in the module.

        Call this before using allocate_output_buffer or free_output_buffer.
        """
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        void = ir.VoidType()

        # Declare malloc if not present
        if not hasattr(self.cg, 'malloc') or self.cg.malloc is None:
            malloc_ty = ir.FunctionType(i8_ptr, [i64])
            self.cg.malloc = ir.Function(self.cg.module, malloc_ty, name="malloc")

        # Declare free if not present
        if not hasattr(self.cg, 'free') or self.cg.free is None:
            free_ty = ir.FunctionType(void, [i8_ptr])
            self.cg.free = ir.Function(self.cg.module, free_ty, name="free")
