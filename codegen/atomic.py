"""
Atomic Reference type implementation for Coex.

This module provides the atomic_ref<T> type implementation for the Coex compiler.
atomic_ref provides atomic operations on references to heap-allocated values.
All operations use sequentially-consistent memory ordering.

AtomicRef layout:
    i64 value  - Pointer stored as i64 (nil = 0)

Operations:
    new(value) -> atomic_ref     - Create with initial value
    load() -> T?                 - Atomic load
    store(value: T?)             - Atomic store
    compare_and_swap(expected, new) -> bool  - Atomic CAS
    swap(new) -> T?              - Atomic exchange
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class AtomicGenerator:
    """Generates atomic_ref type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_atomic_ref_type(self):
        """Create the atomic_ref<T> type and helper functions.

        atomic_ref provides atomic operations on references to heap-allocated values.
        All operations use sequentially-consistent memory ordering.

        AtomicRef layout:
            i64 value  - Pointer stored as i64 (nil = 0)

        Operations:
            new(value) -> atomic_ref     - Create with initial value
            load() -> T?                 - Atomic load
            store(value: T?)             - Atomic store
            compare_and_swap(expected, new) -> bool  - Atomic CAS
            swap(new) -> T?              - Atomic exchange
        """
        cg = self.cg

        # AtomicRef struct: { i64 value }
        cg.atomic_ref_struct = ir.global_context.get_identified_type("struct.atomic_ref")
        cg.atomic_ref_struct.set_body(
            ir.IntType(64)  # value (pointer as i64, nil = 0)
        )

        atomic_ref_ptr = cg.atomic_ref_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)

        # atomic_ref_new(initial_value: i64) -> AtomicRef*
        atomic_ref_new_ty = ir.FunctionType(atomic_ref_ptr, [i64])
        cg.atomic_ref_new = ir.Function(cg.module, atomic_ref_new_ty, name="coex_atomic_ref_new")

        # atomic_ref_load(ref: AtomicRef*) -> i64
        atomic_ref_load_ty = ir.FunctionType(i64, [atomic_ref_ptr])
        cg.atomic_ref_load = ir.Function(cg.module, atomic_ref_load_ty, name="coex_atomic_ref_load")

        # atomic_ref_store(ref: AtomicRef*, value: i64)
        atomic_ref_store_ty = ir.FunctionType(ir.VoidType(), [atomic_ref_ptr, i64])
        cg.atomic_ref_store = ir.Function(cg.module, atomic_ref_store_ty, name="coex_atomic_ref_store")

        # atomic_ref_compare_and_swap(ref: AtomicRef*, expected: i64, new: i64) -> bool
        atomic_ref_cas_ty = ir.FunctionType(i1, [atomic_ref_ptr, i64, i64])
        cg.atomic_ref_cas = ir.Function(cg.module, atomic_ref_cas_ty, name="coex_atomic_ref_cas")

        # atomic_ref_swap(ref: AtomicRef*, new: i64) -> i64
        atomic_ref_swap_ty = ir.FunctionType(i64, [atomic_ref_ptr, i64])
        cg.atomic_ref_swap = ir.Function(cg.module, atomic_ref_swap_ty, name="coex_atomic_ref_swap")

        # Implement all atomic_ref functions
        self._implement_atomic_ref_new()
        self._implement_atomic_ref_load()
        self._implement_atomic_ref_store()
        self._implement_atomic_ref_cas()
        self._implement_atomic_ref_swap()
        self._register_atomic_ref_methods()

    def _implement_atomic_ref_new(self):
        """Implement atomic_ref_new: allocate and initialize an atomic reference."""
        cg = self.cg

        func = cg.atomic_ref_new
        func.args[0].name = "initial"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        initial = func.args[0]

        # Allocate AtomicRef struct (8 bytes) via GC
        ref_size = ir.Constant(ir.IntType(64), 8)
        type_id = ir.Constant(ir.IntType(32), cg.gc.TYPE_UNKNOWN)
        raw_ptr = cg.gc.alloc_with_deref(builder, ref_size, type_id)
        ref_ptr = builder.bitcast(raw_ptr, cg.atomic_ref_struct.as_pointer())

        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)

        # Store initial value atomically (for consistency, though not strictly necessary at creation)
        builder.store_atomic(initial, value_field, ordering='seq_cst', align=8)

        builder.ret(ref_ptr)

    def _implement_atomic_ref_load(self):
        """Implement atomic_ref_load: atomically read the reference value."""
        cg = self.cg

        func = cg.atomic_ref_load
        func.args[0].name = "ref"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        ref_ptr = func.args[0]

        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)

        # Atomic load with sequential consistency
        value = builder.load_atomic(value_field, ordering='seq_cst', align=8)

        builder.ret(value)

    def _implement_atomic_ref_store(self):
        """Implement atomic_ref_store: atomically write a new reference value."""
        cg = self.cg

        func = cg.atomic_ref_store
        func.args[0].name = "ref"
        func.args[1].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        ref_ptr = func.args[0]
        value = func.args[1]

        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)

        # Atomic store with sequential consistency
        builder.store_atomic(value, value_field, ordering='seq_cst', align=8)

        builder.ret_void()

    def _implement_atomic_ref_cas(self):
        """Implement atomic_ref_compare_and_swap: atomically update if current equals expected.

        Returns true if the swap occurred, false otherwise.
        """
        cg = self.cg

        func = cg.atomic_ref_cas
        func.args[0].name = "ref"
        func.args[1].name = "expected"
        func.args[2].name = "new"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        ref_ptr = func.args[0]
        expected = func.args[1]
        new_val = func.args[2]

        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)

        # Atomic compare-and-swap
        # cmpxchg returns { value, success_flag }
        result = builder.cmpxchg(value_field, expected, new_val,
                                  ordering='seq_cst', failordering='seq_cst')

        # Extract the success flag (second element of the result)
        success = builder.extract_value(result, 1)

        builder.ret(success)

    def _implement_atomic_ref_swap(self):
        """Implement atomic_ref_swap: atomically replace and return old value."""
        cg = self.cg

        func = cg.atomic_ref_swap
        func.args[0].name = "ref"
        func.args[1].name = "new"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        ref_ptr = func.args[0]
        new_val = func.args[1]

        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)

        # Atomic exchange - returns old value
        old_val = builder.atomic_rmw('xchg', value_field, new_val, ordering='seq_cst')

        builder.ret(old_val)

    def _register_atomic_ref_methods(self):
        """Register atomic_ref as a type with methods."""
        cg = self.cg

        cg.type_registry["atomic_ref"] = cg.atomic_ref_struct
        cg.type_fields["atomic_ref"] = []  # Internal structure

        cg.type_methods["atomic_ref"] = {
            "load": "coex_atomic_ref_load",
            "store": "coex_atomic_ref_store",
            "compare_and_swap": "coex_atomic_ref_cas",
            "swap": "coex_atomic_ref_swap",
        }

        cg.functions["coex_atomic_ref_new"] = cg.atomic_ref_new
        cg.functions["coex_atomic_ref_load"] = cg.atomic_ref_load
        cg.functions["coex_atomic_ref_store"] = cg.atomic_ref_store
        cg.functions["coex_atomic_ref_cas"] = cg.atomic_ref_cas
        cg.functions["coex_atomic_ref_swap"] = cg.atomic_ref_swap
