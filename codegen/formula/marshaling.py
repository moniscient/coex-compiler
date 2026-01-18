"""
Marshaling Code Generation for GPU Offload.

This module generates LLVM IR to convert between Coex Arrays and contiguous
GPU buffers. The Array type is the only collection type supported for GPU
offload - Lists/Maps/Sets must be implicitly cast to Array first.

Array struct layout (5 fields, all i64):
    Field 0: owner_handle (i64) - handle to data buffer
    Field 1: offset (i64) - byte offset into owner buffer (for slice views)
    Field 2: len (i64) - number of elements
    Field 3: cap (i64) - capacity
    Field 4: elem_size (i64) - size of each element in bytes
"""

from typing import TYPE_CHECKING, Tuple
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


# Coex type to byte size mapping
ELEMENT_SIZES = {
    'int': 8,      # i64
    'int64': 8,    # i64
    'float': 8,    # f64 (Coex floats are 64-bit)
    'float64': 8,  # f64
    'bool': 1,     # i8 (stored as byte)
    'byte': 1,     # i8
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

        Array layout: { i64 owner_handle, i64 offset, i64 len, i64 cap, i64 elem_size }

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

        # Load owner_handle (field 0)
        owner_handle_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True
        )
        owner_handle = builder.load(owner_handle_ptr)

        # Convert handle to pointer
        owner_ptr = builder.inttoptr(owner_handle, i8_ptr)

        # Load offset (field 1)
        offset_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True
        )
        offset = builder.load(offset_ptr)

        # Compute data_ptr = owner + offset
        data_ptr = builder.gep(owner_ptr, [offset])

        # Load len (field 2)
        len_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 2)],
            inbounds=True
        )
        count = builder.load(len_ptr)

        # Load elem_size (field 4)
        elem_size_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 4)],
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

        # Get the array's data pointer: owner + offset (offset should be 0 for new array)
        owner_handle_ptr = builder.gep(
            array_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True
        )
        owner_handle = builder.load(owner_handle_ptr)
        dest_ptr = builder.inttoptr(owner_handle, i8_ptr)

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
