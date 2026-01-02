"""
Core GC Module for Coex Garbage Collector

This module provides core garbage collection functionality.

Core GC Components:
- Type system: type registration, type tables
- Memory allocation: gc_alloc with handle-based references
- Shadow stack: frame push/pop, root tracking
- Mark phase: object marking, HAMT traversal
- Sweep phase: reclaim unmarked objects
- Collection: full GC cycle orchestration

Handle-Based Design:
All heap references are i64 indices into a global handle table.
This enables future concurrent collection without pointer fixup.

Object Header (32 bytes):
    { i64 size, i64 type_id, i64 flags, i64 forward }
    - flags bit 0: mark bit
    - forward: stores handle for ptr-to-handle recovery
"""
from typing import TYPE_CHECKING, List as PyList
from llvmlite import ir

if TYPE_CHECKING:
    from coex_gc_original import GarbageCollector


class GCCoreGenerator:
    """Generates core GC code for the Coex runtime."""

    def __init__(self, gc: 'GarbageCollector'):
        """Initialize with reference to parent GarbageCollector instance."""
        self.gc = gc

    # Property accessors for commonly used GC attributes
    @property
    def module(self):
        return self.gc.module

    @property
    def builder(self):
        return self.gc.builder

    @property
    def type_registry(self):
        return self.gc.type_registry

    # ========================================================================
    # Runtime Generation
    # ========================================================================

    def generate_gc_runtime(self):
        """Generate the complete GC runtime.

        Creates types, globals, and all GC functions.
        """
        return self.gc.generate_gc_runtime()

    def create_types(self):
        """Create GC-related LLVM types.

        Includes object header, shadow stack frame, handle table, etc.
        """
        return self.gc._create_types()

    def create_globals(self):
        """Create GC global variables.

        Includes heap pointers, handle table, mark state, statistics.
        """
        return self.gc._create_globals()

    def declare_functions(self):
        """Declare all GC function signatures."""
        return self.gc._declare_functions()

    # ========================================================================
    # Type Registration
    # ========================================================================

    def register_builtin_types(self):
        """Register built-in types (String, List, Map, Set, etc.)."""
        return self.gc._register_builtin_types()

    def register_type(self, type_name: str, size: int,
                      ref_offsets: PyList[int]) -> int:
        """Register a user-defined type with the GC.

        Args:
            type_name: Name of the type
            size: Size in bytes
            ref_offsets: Byte offsets of pointer fields for tracing

        Returns:
            Type ID for use in allocations
        """
        return self.gc.register_type(type_name, size, ref_offsets)

    def get_type_id(self, type_name: str) -> int:
        """Get the type ID for a registered type."""
        return self.gc.get_type_id(type_name)

    def finalize_type_tables(self):
        """Finalize type tables after all types are registered."""
        return self.gc.finalize_type_tables()

    # ========================================================================
    # GC Initialization
    # ========================================================================

    def implement_gc_init(self):
        """Implement gc_init: initialize the garbage collector.

        Sets up heap, handle table, shadow stacks, and mark state.
        """
        return self.gc._implement_gc_init()

    # ========================================================================
    # Shadow Stack Operations
    # ========================================================================

    def implement_gc_push_frame(self):
        """Implement gc_push_frame: push a new shadow stack frame."""
        return self.gc._implement_gc_push_frame()

    def implement_gc_pop_frame(self):
        """Implement gc_pop_frame: pop the current shadow stack frame."""
        return self.gc._implement_gc_pop_frame()

    def implement_gc_set_root(self):
        """Implement gc_set_root: store a handle in a shadow stack slot."""
        return self.gc._implement_gc_set_root()

    # ========================================================================
    # Memory Allocation
    # ========================================================================

    def implement_gc_alloc(self):
        """Implement gc_alloc: allocate memory and return handle.

        Allocates object with header, assigns handle, tracks in handle table.
        Uses birth-marking (new objects survive current GC cycle).
        """
        return self.gc._implement_gc_alloc()

    # ========================================================================
    # Mark Phase
    # ========================================================================

    def implement_gc_mark_hamt(self):
        """Implement HAMT structure marking.

        Recursively marks HAMT nodes and their contents.
        """
        return self.gc._implement_gc_mark_hamt()

    def implement_gc_mark_object(self):
        """Implement gc_mark_object: mark an object and trace references.

        Marks the object and recursively traces all pointer fields.
        """
        return self.gc._implement_gc_mark_object()

    def implement_gc_scan_roots(self):
        """Implement gc_scan_roots: scan all shadow stacks for roots.

        Iterates through all shadow stack frames and marks reachable objects.
        """
        return self.gc._implement_gc_scan_roots()

    # ========================================================================
    # Sweep Phase
    # ========================================================================

    def implement_gc_sweep(self):
        """Implement gc_sweep: sweep heap and reclaim unmarked objects.

        Iterates through heap, retires handles of unmarked objects.
        """
        return self.gc._implement_gc_sweep()

    # ========================================================================
    # Collection
    # ========================================================================

    def implement_gc_collect(self):
        """Implement gc_collect: perform a full GC cycle.

        1. Flip mark value
        2. Promote retired handles
        3. Scan roots and mark
        4. Sweep and retire unmarked
        5. Update statistics
        """
        return self.gc._implement_gc_collect()

    def implement_gc_safepoint(self):
        """Implement gc_safepoint: check if GC is needed.

        Called at safe points (function entry, loop back-edges).
        Triggers collection if allocation threshold exceeded.
        """
        return self.gc._implement_gc_safepoint()

    # ========================================================================
    # Builder Helpers (called from codegen)
    # ========================================================================

    def wrap_allocation(self, builder: ir.IRBuilder, type_name: str,
                        size: ir.Value) -> ir.Value:
        """Wrap an allocation call with GC tracking."""
        return self.gc.wrap_allocation(builder, type_name, size)

    def inject_gc_init(self, builder: ir.IRBuilder):
        """Inject GC initialization call."""
        return self.gc.inject_gc_init(builder)

    def inject_safepoint(self, builder: ir.IRBuilder):
        """Inject a GC safepoint check."""
        return self.gc.inject_safepoint(builder)

    def create_frame_roots(self, builder: ir.IRBuilder,
                           num_roots: int) -> ir.Value:
        """Create storage for shadow stack frame roots."""
        return self.gc.create_frame_roots(builder, num_roots)

    def push_frame_inline(self, builder: ir.IRBuilder, num_roots: int,
                          handle_slots: ir.Value) -> ir.Value:
        """Push a shadow stack frame (inline version)."""
        return self.gc.push_frame_inline(builder, num_roots, handle_slots)

    def pop_frame_inline(self, builder: ir.IRBuilder, frame: ir.Value):
        """Pop a shadow stack frame (inline version)."""
        return self.gc.pop_frame_inline(builder, frame)

    def push_frame(self, builder: ir.IRBuilder, num_roots: int,
                   handle_slots: ir.Value) -> ir.Value:
        """Push a shadow stack frame (function call version)."""
        return self.gc.push_frame(builder, num_roots, handle_slots)

    def pop_frame(self, builder: ir.IRBuilder, frame: ir.Value):
        """Pop a shadow stack frame (function call version)."""
        return self.gc.pop_frame(builder, frame)

    def set_root(self, builder: ir.IRBuilder, handle_slots: ir.Value,
                 index: int, value: ir.Value):
        """Store a handle in a shadow stack slot."""
        return self.gc.set_root(builder, handle_slots, index, value)

    def alloc_with_deref(self, builder: ir.IRBuilder, size: ir.Value,
                         type_id: ir.Value) -> ir.Value:
        """Allocate and immediately dereference handle to get pointer."""
        return self.gc.alloc_with_deref(builder, size, type_id)
