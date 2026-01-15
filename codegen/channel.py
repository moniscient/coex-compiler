"""
Channel type implementation for Coex.

This module provides the Channel<T> type implementation for the Coex compiler.
Channels enable task-to-task communication with:
- Unbounded buffer (send never blocks)
- FIFO ordering
- Receive suspends task if buffer empty

Channel struct (48 bytes, 6 i64 fields):
    Field 0: buffer_ptr (i64) - Pointer to ring buffer
    Field 1: head (i64) - Cached read position
    Field 2: tail (i64) - Cached write position
    Field 3: count (i64) - Cached item count
    Field 4: waiters_ptr (i64) - Wait queue pointer (traced by GC)
    Field 5: elem_size (i64) - Element size
"""
from typing import TYPE_CHECKING, Optional
from llvmlite import ir

from ast_nodes import Type, PrimitiveType, ListType

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ChannelGenerator:
    """Generates Channel type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen
        self._channel_struct = None
        self._channel_new_fn = None
        self._channel_send_fn = None
        self._channel_receive_fn = None
        self._channel_try_receive_fn = None
        self._uses_channels = False

    def uses_channels(self) -> bool:
        """Check if channels are used in this compilation unit."""
        return self._uses_channels

    def get_channel_struct(self) -> ir.Type:
        """Get or create the Channel struct type."""
        if self._channel_struct is not None:
            return self._channel_struct

        cg = self.cg
        i64 = ir.IntType(64)

        # Channel struct: 6 i64 fields
        try:
            self._channel_struct = ir.global_context.get_identified_type("struct.Channel")
            self._channel_struct.set_body(i64, i64, i64, i64, i64, i64)
        except Exception:
            # Type already exists, just use it
            self._channel_struct = ir.global_context.get_identified_type("struct.Channel")

        return self._channel_struct

    def declare_channel_functions(self):
        """Declare the C runtime functions for channels."""
        self._uses_channels = True
        cg = self.cg
        module = cg.module

        channel_ptr = self.get_channel_struct().as_pointer()
        i64 = ir.IntType(64)
        i64_ptr = i64.as_pointer()
        void = ir.VoidType()

        # channel_new(elem_size: i64) -> Channel*
        if self._channel_new_fn is None:
            fn_type = ir.FunctionType(channel_ptr, [i64])
            self._channel_new_fn = ir.Function(module, fn_type, name="coex_channel_new")

        # channel_send(channel: Channel*, value: i64) -> void
        if self._channel_send_fn is None:
            fn_type = ir.FunctionType(void, [channel_ptr, i64])
            self._channel_send_fn = ir.Function(module, fn_type, name="coex_channel_send")

        # channel_receive(channel: Channel*) -> i64 (blocking)
        if self._channel_receive_fn is None:
            fn_type = ir.FunctionType(i64, [channel_ptr])
            self._channel_receive_fn = ir.Function(module, fn_type, name="coex_channel_receive")

        # channel_try_receive(channel: Channel*, out_value: i64*) -> i64 (0=ok, -1=empty)
        if self._channel_try_receive_fn is None:
            fn_type = ir.FunctionType(i64, [channel_ptr, i64_ptr])
            self._channel_try_receive_fn = ir.Function(module, fn_type, name="coex_channel_try_receive")

    def register_channel_type(self):
        """Register Channel type in the type registry."""
        cg = self.cg
        channel_struct = self.get_channel_struct()

        cg.type_registry["Channel"] = channel_struct
        cg.type_fields["Channel"] = [
            ("buffer_ptr", PrimitiveType('int')),
            ("head", PrimitiveType('int')),
            ("tail", PrimitiveType('int')),
            ("count", PrimitiveType('int')),
            ("waiters_ptr", PrimitiveType('int')),
            ("elem_size", PrimitiveType('int')),
        ]
        cg.type_methods["Channel"] = {
            "send": "_channel_send",
            "receive": "_channel_receive",
            "new": "_channel_new",
        }

    # ========================================================================
    # Channel Operations
    # ========================================================================

    def generate_channel_new(self, elem_type: Optional[Type], builder: ir.IRBuilder) -> ir.Value:
        """
        Generate code for Channel.new() constructor.

        Args:
            elem_type: The element type (currently all elements stored as i64)
            builder: LLVM IR builder

        Returns:
            Pointer to new channel
        """
        self.declare_channel_functions()

        # All elements stored as i64 (8 bytes)
        elem_size = ir.Constant(ir.IntType(64), 8)

        # Call coex_channel_new
        channel_ptr = builder.call(self._channel_new_fn, [elem_size], name="channel")

        return channel_ptr

    def generate_channel_send(self, channel: ir.Value, value: ir.Value,
                              builder: ir.IRBuilder) -> ir.Value:
        """
        Generate code for ch.send(value).

        Args:
            channel: Channel pointer
            value: Value to send (will be cast to i64)
            builder: LLVM IR builder

        Returns:
            void (returns i64 0 for consistency)
        """
        self.declare_channel_functions()
        cg = self.cg

        # Ensure channel is the right type
        channel_ptr_type = self.get_channel_struct().as_pointer()
        if channel.type != channel_ptr_type:
            channel = builder.bitcast(channel, channel_ptr_type)

        # Cast value to i64
        value_i64 = cg._cast_value(value, ir.IntType(64))

        # Call coex_channel_send
        builder.call(self._channel_send_fn, [channel, value_i64])

        return ir.Constant(ir.IntType(64), 0)

    def generate_channel_receive(self, channel: ir.Value,
                                  builder: ir.IRBuilder) -> ir.Value:
        """
        Generate code for ch.receive().

        Args:
            channel: Channel pointer
            builder: LLVM IR builder

        Returns:
            Received value (i64)
        """
        self.declare_channel_functions()

        # Ensure channel is the right type
        channel_ptr_type = self.get_channel_struct().as_pointer()
        if channel.type != channel_ptr_type:
            channel = builder.bitcast(channel, channel_ptr_type)

        # Call coex_channel_receive (blocking)
        result = builder.call(self._channel_receive_fn, [channel], name="received")

        return result

    def get_elem_size_for_type(self, elem_type: Optional[Type]) -> int:
        """Get element size for a type (all stored as i64)."""
        # For simplicity, all values are stored as i64 (handles for heap types)
        return 8


def create_channel_generator(cg: 'CodeGenerator') -> ChannelGenerator:
    """Factory function to create a ChannelGenerator."""
    return ChannelGenerator(cg)
