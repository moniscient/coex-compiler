"""
Atomics Module for Coex Code Generator

This module provides atomic type implementations for the Coex compiler.

Atomic Types:
- atomic_int: 64-bit atomic integer with load, store, add, sub, increment, decrement, cas
- atomic_float: 64-bit atomic float with load, store, cas
- atomic_bool: 1-bit atomic boolean with load, store, cas
- atomic_ref<T>: Atomic reference to heap-allocated value with load, store, cas, swap

All atomic operations use sequentially-consistent memory ordering for safety.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator


class AtomicsGenerator:
    """Generates atomic type implementations for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def module(self):
        return self.codegen.module

    @property
    def gc(self):
        return self.codegen.gc

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_methods(self):
        return self.codegen.type_methods

    @property
    def atomic_ref_struct(self):
        return self.codegen.atomic_ref_struct

    # ========================================================================
    # Atomic Ref Type
    # ========================================================================

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
        return self.codegen._create_atomic_ref_type()

    # ========================================================================
    # Atomic Ref Implementation Methods
    # ========================================================================

    def implement_atomic_ref_new(self):
        """Implement atomic_ref_new: allocate and initialize an atomic reference."""
        return self.codegen._implement_atomic_ref_new()

    def implement_atomic_ref_load(self):
        """Implement atomic_ref_load: atomically load the reference value."""
        return self.codegen._implement_atomic_ref_load()

    def implement_atomic_ref_store(self):
        """Implement atomic_ref_store: atomically store a new reference value."""
        return self.codegen._implement_atomic_ref_store()

    def implement_atomic_ref_cas(self):
        """Implement atomic_ref_cas: atomic compare-and-swap operation."""
        return self.codegen._implement_atomic_ref_cas()

    def implement_atomic_ref_swap(self):
        """Implement atomic_ref_swap: atomic exchange operation."""
        return self.codegen._implement_atomic_ref_swap()

    def register_atomic_ref_methods(self):
        """Register atomic_ref methods in type_methods registry."""
        return self.codegen._register_atomic_ref_methods()
