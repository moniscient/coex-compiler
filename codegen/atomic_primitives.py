"""
Atomic primitive type implementation for Coex.

This module provides atomic_int, atomic_float, and atomic_bool implementations.
These are stack-allocated primitive values with atomic memory operations.
All operations use sequentially-consistent memory ordering.

Operations:
    load() -> T               - Atomic load
    store(value: T)           - Atomic store (returns unit)
    exchange(value: T) -> T   - Atomic exchange, returns old value
    compare_and_swap(expected: T, new: T) -> bool  - Atomic CAS

For atomic_int only:
    fetch_add(delta: int) -> int  - Add and return old value
    fetch_sub(delta: int) -> int  - Subtract and return old value
    increment() -> int            - Add 1 and return old value
    decrement() -> int            - Subtract 1 and return old value

For atomic_bool only:
    test_and_set() -> bool        - Set to true and return old value
"""
from typing import TYPE_CHECKING, Optional
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class AtomicPrimitiveGenerator:
    """Generates atomic primitive operations for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen
        self.i64 = ir.IntType(64)
        self.i32 = ir.IntType(32)
        self.i1 = ir.IntType(1)
        self.double = ir.DoubleType()

    def generate_atomic_load(self, builder: ir.IRBuilder, ptr: ir.Value,
                            atomic_inner_type: str) -> ir.Value:
        """Generate atomic load operation.

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic value (alloca)
            atomic_inner_type: "int", "float", or "bool"

        Returns:
            The loaded value with proper type
        """
        if atomic_inner_type == "int":
            # i64 atomic load
            return builder.load_atomic(ptr, ordering='seq_cst', align=8)
        elif atomic_inner_type == "float":
            # Load as i64, bitcast to double
            # LLVM requires atomic operations on integer types
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            val_i64 = builder.load_atomic(ptr_i64, ordering='seq_cst', align=8)
            return builder.bitcast(val_i64, self.double)
        elif atomic_inner_type == "bool":
            # Load as i64 and truncate to i1
            # We store bools as i64 for alignment
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            val_i64 = builder.load_atomic(ptr_i64, ordering='seq_cst', align=8)
            return builder.trunc(val_i64, self.i1)
        else:
            # Fallback
            return builder.load_atomic(ptr, ordering='seq_cst', align=8)

    def generate_atomic_store(self, builder: ir.IRBuilder, ptr: ir.Value,
                             value: ir.Value, atomic_inner_type: str) -> ir.Value:
        """Generate atomic store operation.

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic value (alloca)
            value: Value to store
            atomic_inner_type: "int", "float", or "bool"

        Returns:
            Unit value (i64 0)
        """
        if atomic_inner_type == "int":
            # Ensure value is i64
            if value.type != self.i64:
                if isinstance(value.type, ir.IntType):
                    value = builder.sext(value, self.i64)
                else:
                    value = builder.bitcast(value, self.i64)
            builder.store_atomic(value, ptr, ordering='seq_cst', align=8)
        elif atomic_inner_type == "float":
            # Bitcast double to i64 for atomic store
            if isinstance(value.type, ir.DoubleType):
                val_i64 = builder.bitcast(value, self.i64)
            else:
                val_i64 = value
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            builder.store_atomic(val_i64, ptr_i64, ordering='seq_cst', align=8)
        elif atomic_inner_type == "bool":
            # Extend bool to i64 for atomic store
            if value.type == self.i1:
                val_i64 = builder.zext(value, self.i64)
            else:
                val_i64 = value
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            builder.store_atomic(val_i64, ptr_i64, ordering='seq_cst', align=8)
        else:
            builder.store_atomic(value, ptr, ordering='seq_cst', align=8)

        # Return unit (0)
        return ir.Constant(self.i64, 0)

    def generate_atomic_exchange(self, builder: ir.IRBuilder, ptr: ir.Value,
                                new_value: ir.Value, atomic_inner_type: str) -> ir.Value:
        """Generate atomic exchange operation.

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic value
            new_value: New value to set
            atomic_inner_type: "int", "float", or "bool"

        Returns:
            The old value
        """
        if atomic_inner_type == "int":
            if new_value.type != self.i64:
                if isinstance(new_value.type, ir.IntType):
                    new_value = builder.sext(new_value, self.i64)
            return builder.atomic_rmw('xchg', ptr, new_value, ordering='seq_cst')
        elif atomic_inner_type == "float":
            # Exchange as i64
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            val_i64 = builder.bitcast(new_value, self.i64)
            old_i64 = builder.atomic_rmw('xchg', ptr_i64, val_i64, ordering='seq_cst')
            return builder.bitcast(old_i64, self.double)
        elif atomic_inner_type == "bool":
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            val_i64 = builder.zext(new_value, self.i64) if new_value.type == self.i1 else new_value
            old_i64 = builder.atomic_rmw('xchg', ptr_i64, val_i64, ordering='seq_cst')
            return builder.trunc(old_i64, self.i1)
        else:
            return builder.atomic_rmw('xchg', ptr, new_value, ordering='seq_cst')

    def generate_atomic_cas(self, builder: ir.IRBuilder, ptr: ir.Value,
                           expected: ir.Value, new_value: ir.Value,
                           atomic_inner_type: str) -> ir.Value:
        """Generate atomic compare-and-swap operation.

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic value
            expected: Expected current value
            new_value: New value to set if current == expected
            atomic_inner_type: "int", "float", or "bool"

        Returns:
            True if swap occurred, False otherwise
        """
        if atomic_inner_type == "int":
            if expected.type != self.i64:
                expected = builder.sext(expected, self.i64) if isinstance(expected.type, ir.IntType) else expected
            if new_value.type != self.i64:
                new_value = builder.sext(new_value, self.i64) if isinstance(new_value.type, ir.IntType) else new_value
            result = builder.cmpxchg(ptr, expected, new_value,
                                    ordering='seq_cst', failordering='seq_cst')
            return builder.extract_value(result, 1)
        elif atomic_inner_type == "float":
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            exp_i64 = builder.bitcast(expected, self.i64)
            new_i64 = builder.bitcast(new_value, self.i64)
            result = builder.cmpxchg(ptr_i64, exp_i64, new_i64,
                                    ordering='seq_cst', failordering='seq_cst')
            return builder.extract_value(result, 1)
        elif atomic_inner_type == "bool":
            ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
            exp_i64 = builder.zext(expected, self.i64) if expected.type == self.i1 else expected
            new_i64 = builder.zext(new_value, self.i64) if new_value.type == self.i1 else new_value
            result = builder.cmpxchg(ptr_i64, exp_i64, new_i64,
                                    ordering='seq_cst', failordering='seq_cst')
            return builder.extract_value(result, 1)
        else:
            result = builder.cmpxchg(ptr, expected, new_value,
                                    ordering='seq_cst', failordering='seq_cst')
            return builder.extract_value(result, 1)

    def generate_fetch_add(self, builder: ir.IRBuilder, ptr: ir.Value,
                          delta: ir.Value) -> ir.Value:
        """Generate atomic fetch-add operation (atomic_int only).

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic_int value
            delta: Value to add

        Returns:
            The old value before addition
        """
        if delta.type != self.i64:
            if isinstance(delta.type, ir.IntType):
                delta = builder.sext(delta, self.i64)
            else:
                delta = builder.bitcast(delta, self.i64)
        return builder.atomic_rmw('add', ptr, delta, ordering='seq_cst')

    def generate_fetch_sub(self, builder: ir.IRBuilder, ptr: ir.Value,
                          delta: ir.Value) -> ir.Value:
        """Generate atomic fetch-sub operation (atomic_int only).

        Args:
            builder: LLVM IR builder
            ptr: Pointer to the atomic_int value
            delta: Value to subtract

        Returns:
            The old value before subtraction
        """
        if delta.type != self.i64:
            if isinstance(delta.type, ir.IntType):
                delta = builder.sext(delta, self.i64)
            else:
                delta = builder.bitcast(delta, self.i64)
        return builder.atomic_rmw('sub', ptr, delta, ordering='seq_cst')

    def generate_increment(self, builder: ir.IRBuilder, ptr: ir.Value) -> ir.Value:
        """Generate atomic increment operation (atomic_int only).

        Returns the old value before increment.
        """
        return self.generate_fetch_add(builder, ptr, ir.Constant(self.i64, 1))

    def generate_decrement(self, builder: ir.IRBuilder, ptr: ir.Value) -> ir.Value:
        """Generate atomic decrement operation (atomic_int only).

        Returns the old value before decrement.
        """
        return self.generate_fetch_sub(builder, ptr, ir.Constant(self.i64, 1))

    def generate_test_and_set(self, builder: ir.IRBuilder, ptr: ir.Value) -> ir.Value:
        """Generate atomic test-and-set operation (atomic_bool only).

        Sets the value to true and returns the old value.
        """
        ptr_i64 = builder.bitcast(ptr, self.i64.as_pointer())
        old_i64 = builder.atomic_rmw('xchg', ptr_i64, ir.Constant(self.i64, 1), ordering='seq_cst')
        return builder.trunc(old_i64, self.i1)

    def generate_atomic_init(self, builder: ir.IRBuilder, ptr: ir.Value,
                            value: ir.Value, atomic_inner_type: str):
        """Generate initial atomic store for variable declaration.

        Uses atomic store for consistency, though not strictly necessary at init time.
        """
        self.generate_atomic_store(builder, ptr, value, atomic_inner_type)
