"""
Coex GC Thread Registry Module

Manages thread registration, TLS initialization, and per-thread GC state.
This module provides the infrastructure for multi-threaded garbage collection
using the watermark protocol.

Thread Registry Design:
- Each thread has a ThreadEntry in a global linked list
- TLS (via pthread_key) stores per-thread shadow stack state
- Watermark protocol allows threads to acknowledge GC cycles
- Registry mutex protects modifications to the linked list
"""

from llvmlite import ir
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coex_gc_original import GarbageCollector


class ThreadRegistryManager:
    """Manages thread registration and TLS for garbage collection."""

    def __init__(self, gc: 'GarbageCollector'):
        self.gc = gc

    # ============================================================
    # Property Accessors for GC Attributes
    # ============================================================

    @property
    def module(self):
        return self.gc.module

    @property
    def i8(self):
        return self.gc.i8

    @property
    def i32(self):
        return self.gc.i32

    @property
    def i64(self):
        return self.gc.i64

    @property
    def i8_ptr(self):
        return self.gc.i8_ptr

    @property
    def i64_ptr(self):
        return self.gc.i64_ptr

    @property
    def void(self):
        return self.gc.void

    @property
    def i1(self):
        return self.gc.i1

    @property
    def thread_entry_type(self):
        return self.gc.thread_entry_type

    @property
    def gc_frame_type(self):
        return self.gc.gc_frame_type

    # Global variables
    @property
    def gc_thread_registry(self):
        return self.gc.gc_thread_registry

    @property
    def gc_thread_count(self):
        return self.gc.gc_thread_count

    @property
    def gc_registry_mutex(self):
        return self.gc.gc_registry_mutex

    @property
    def gc_phase(self):
        return self.gc.gc_phase

    @property
    def gc_cycle_id(self):
        return self.gc.gc_cycle_id

    @property
    def tls_key_frame_top(self):
        return self.gc.tls_key_frame_top

    @property
    def tls_key_frame_depth(self):
        return self.gc.tls_key_frame_depth

    @property
    def tls_key_thread_entry(self):
        return self.gc.tls_key_thread_entry

    # Functions
    @property
    def gc_tls_init(self):
        return self.gc.gc_tls_init

    @property
    def gc_register_thread(self):
        return self.gc.gc_register_thread

    @property
    def gc_unregister_thread(self):
        return self.gc.gc_unregister_thread

    @property
    def gc_get_thread_entry(self):
        return self.gc.gc_get_thread_entry

    @property
    def pthread_self(self):
        return self.gc.pthread_self

    @property
    def pthread_key_create(self):
        return self.gc.pthread_key_create

    @property
    def pthread_getspecific(self):
        return self.gc.pthread_getspecific

    @property
    def pthread_setspecific(self):
        return self.gc.pthread_setspecific

    @property
    def pthread_mutex_init(self):
        return self.gc.pthread_mutex_init

    @property
    def pthread_mutex_lock(self):
        return self.gc.pthread_mutex_lock

    @property
    def pthread_mutex_unlock(self):
        return self.gc.pthread_mutex_unlock

    # ============================================================
    # TLS Helper Methods
    # ============================================================

    def get_tls_frame_top(self, builder: ir.IRBuilder) -> ir.Value:
        """Get the calling thread's shadow stack top from TLS.

        Returns an i8* pointer (the frame pointer).
        """
        key = builder.load(self.tls_key_frame_top)
        return builder.call(self.pthread_getspecific, [key])

    def set_tls_frame_top(self, builder: ir.IRBuilder, value: ir.Value):
        """Set the calling thread's shadow stack top in TLS.

        value should be an i8* pointer.
        """
        key = builder.load(self.tls_key_frame_top)
        builder.call(self.pthread_setspecific, [key, value])

    def get_tls_frame_depth(self, builder: ir.IRBuilder) -> ir.Value:
        """Get the calling thread's shadow stack depth from TLS.

        Returns an i64 value (stored as i8* in TLS).
        """
        key = builder.load(self.tls_key_frame_depth)
        ptr = builder.call(self.pthread_getspecific, [key])
        return builder.ptrtoint(ptr, self.i64)

    def set_tls_frame_depth(self, builder: ir.IRBuilder, value: ir.Value):
        """Set the calling thread's shadow stack depth in TLS.

        value should be an i64 which gets stored as an i8*.
        """
        key = builder.load(self.tls_key_frame_depth)
        ptr = builder.inttoptr(value, self.i8_ptr)
        builder.call(self.pthread_setspecific, [key, ptr])

    def get_tls_thread_entry(self, builder: ir.IRBuilder) -> ir.Value:
        """Get the calling thread's ThreadEntry pointer from TLS.

        Returns a ThreadEntry* pointer.
        """
        key = builder.load(self.tls_key_thread_entry)
        ptr = builder.call(self.pthread_getspecific, [key])
        return builder.bitcast(ptr, self.thread_entry_type.as_pointer())

    def set_tls_thread_entry(self, builder: ir.IRBuilder, value: ir.Value):
        """Set the calling thread's ThreadEntry pointer in TLS.

        value should be a ThreadEntry* pointer.
        """
        key = builder.load(self.tls_key_thread_entry)
        ptr = builder.bitcast(value, self.i8_ptr)
        builder.call(self.pthread_setspecific, [key, ptr])

    # ============================================================
    # Implementation Methods
    # ============================================================

    def implement_gc_tls_init(self):
        """Initialize TLS keys for thread-local storage.

        Creates three TLS keys:
        - tls_key_frame_top: Shadow stack frame top pointer
        - tls_key_frame_depth: Shadow stack depth counter
        - tls_key_thread_entry: Pointer to thread's ThreadEntry
        """
        func = self.gc_tls_init
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        null_ptr = ir.Constant(self.i8_ptr, None)

        # Create TLS key for frame_top
        builder.call(self.pthread_key_create, [self.tls_key_frame_top, null_ptr])

        # Create TLS key for frame_depth
        builder.call(self.pthread_key_create, [self.tls_key_frame_depth, null_ptr])

        # Create TLS key for thread_entry
        builder.call(self.pthread_key_create, [self.tls_key_thread_entry, null_ptr])

        builder.ret_void()

    def implement_gc_register_thread(self):
        """Register the calling thread with the GC.

        Allocates a ThreadEntry, initializes it with the thread's state,
        and adds it to the global registry under mutex protection.
        """
        func = self.gc_register_thread

        entry = func.append_basic_block("entry")
        already_registered = func.append_basic_block("already_registered")
        do_register = func.append_basic_block("do_register")

        builder = ir.IRBuilder(entry)

        # Check if already registered (TLS entry not null)
        current_entry = self.get_tls_thread_entry(builder)
        current_entry_int = builder.ptrtoint(current_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', current_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_registered, already_registered, do_register)

        # Already registered - return
        builder.position_at_end(already_registered)
        builder.ret_void()

        # Do registration
        builder.position_at_end(do_register)

        # Allocate ThreadEntry (80 bytes)
        entry_size = ir.Constant(self.i64, 80)
        raw_entry = builder.call(self.gc.codegen.malloc, [entry_size])
        new_entry = builder.bitcast(raw_entry, self.thread_entry_type.as_pointer())

        # Get current thread ID
        thread_id = builder.call(self.pthread_self, [])

        # Initialize ThreadEntry fields
        # Field 0: thread_id
        tid_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(thread_id, tid_ptr)

        # Field 1: shadow_stack_head - will be updated by push/pop frame
        # Store null for now (thread has no frames yet)
        head_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), head_ptr)

        # Field 2: watermark_depth = 0
        wm_depth_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), wm_depth_ptr)

        # Field 3: watermark_active = 0
        wm_active_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), wm_active_ptr)

        # Field 4: stack_depth = 0
        depth_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), depth_ptr)

        # Field 5: last_gc_cycle = 0
        cycle_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), cycle_ptr)

        # Fields 6-8: TLAB pointers = null (future use)
        for i in [6, 7, 8]:
            tlab_ptr = builder.gep(new_entry, [
                ir.Constant(self.i32, 0), ir.Constant(self.i32, i)
            ], inbounds=True)
            builder.store(ir.Constant(self.i8_ptr, None), tlab_ptr)

        # Field 9: next = null (will be set when linking)
        next_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_ptr)

        # Lock registry mutex
        mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [mutex])

        # Prepend to registry: new_entry->next = gc_thread_registry
        old_head = builder.load(self.gc_thread_registry)
        old_head_i8 = builder.bitcast(old_head, self.i8_ptr)
        builder.store(old_head_i8, next_ptr)

        # gc_thread_registry = new_entry
        builder.store(new_entry, self.gc_thread_registry)

        # Increment thread count
        count = builder.load(self.gc_thread_count)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_thread_count)

        # Unlock registry mutex
        builder.call(self.pthread_mutex_unlock, [mutex])

        # Store in TLS
        self.set_tls_thread_entry(builder, new_entry)

        builder.ret_void()

    def implement_gc_unregister_thread(self):
        """Unregister the calling thread from the GC.

        Removes the ThreadEntry from the registry and frees it.
        Must be called before thread exit, after all handles are dropped.
        """
        func = self.gc_unregister_thread

        entry = func.append_basic_block("entry")
        not_registered = func.append_basic_block("not_registered")
        do_unregister = func.append_basic_block("do_unregister")
        found_at_head = func.append_basic_block("found_at_head")
        search_loop = func.append_basic_block("search_loop")
        search_check = func.append_basic_block("search_check")
        found_in_list = func.append_basic_block("found_in_list")
        search_next = func.append_basic_block("search_next")
        cleanup = func.append_basic_block("cleanup")

        builder = ir.IRBuilder(entry)

        # Get current ThreadEntry from TLS
        my_entry = self.get_tls_thread_entry(builder)
        my_entry_int = builder.ptrtoint(my_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', my_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_registered, do_unregister, not_registered)

        # Not registered - return
        builder.position_at_end(not_registered)
        builder.ret_void()

        # Do unregistration
        builder.position_at_end(do_unregister)

        # Lock registry mutex
        mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [mutex])

        # Check if at head of list
        head = builder.load(self.gc_thread_registry)
        head_int = builder.ptrtoint(head, self.i64)
        my_entry_int2 = builder.ptrtoint(my_entry, self.i64)
        is_head = builder.icmp_unsigned('==', head_int, my_entry_int2)
        builder.cbranch(is_head, found_at_head, search_loop)

        # Found at head - remove
        builder.position_at_end(found_at_head)
        next_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
        ], inbounds=True)
        next_entry_i8 = builder.load(next_ptr)
        next_entry = builder.bitcast(next_entry_i8, self.thread_entry_type.as_pointer())
        builder.store(next_entry, self.gc_thread_registry)
        builder.branch(cleanup)

        # Search for entry in list
        builder.position_at_end(search_loop)
        prev_phi = builder.phi(self.thread_entry_type.as_pointer(), name="prev")
        prev_phi.add_incoming(head, do_unregister)

        # Get prev->next
        prev_next_ptr = builder.gep(prev_phi, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
        ], inbounds=True)
        curr_i8 = builder.load(prev_next_ptr)
        curr = builder.bitcast(curr_i8, self.thread_entry_type.as_pointer())

        # Check if curr is null (not found, shouldn't happen)
        curr_int = builder.ptrtoint(curr, self.i64)
        curr_is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
        builder.cbranch(curr_is_null, cleanup, search_check)

        # Check if curr is my_entry
        builder.position_at_end(search_check)
        is_mine = builder.icmp_unsigned('==', curr_int, my_entry_int2)
        builder.cbranch(is_mine, found_in_list, search_next)

        # Found in list - unlink: prev->next = my->next
        builder.position_at_end(found_in_list)
        my_next_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
        ], inbounds=True)
        my_next = builder.load(my_next_ptr)
        builder.store(my_next, prev_next_ptr)
        builder.branch(cleanup)

        # Continue search: prev = curr
        builder.position_at_end(search_next)
        prev_phi.add_incoming(curr, search_next)
        builder.branch(search_loop)

        # Cleanup
        builder.position_at_end(cleanup)

        # Decrement thread count
        count = builder.load(self.gc_thread_count)
        new_count = builder.sub(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_thread_count)

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex])

        # Free ThreadEntry
        my_entry_i8 = builder.bitcast(my_entry, self.i8_ptr)
        builder.call(self.gc.codegen.free, [my_entry_i8])

        # Clear TLS
        self.set_tls_thread_entry(builder,
            ir.Constant(self.thread_entry_type.as_pointer(), None))

        builder.ret_void()

    def implement_gc_get_thread_entry(self):
        """Return the calling thread's ThreadEntry from TLS."""
        func = self.gc_get_thread_entry

        entry_block = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry_block)

        thread_entry = self.get_tls_thread_entry(builder)
        builder.ret(thread_entry)

    # ============================================================
    # Public API for Other Modules
    # ============================================================

    def update_thread_entry_stack_depth(self, builder: ir.IRBuilder, new_depth: ir.Value):
        """Update the current thread's stack_depth in its ThreadEntry.

        Called by gc_push_frame and gc_pop_frame to keep ThreadEntry in sync.
        """
        thread_entry = self.get_tls_thread_entry(builder)
        entry_int = builder.ptrtoint(thread_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', entry_int, ir.Constant(self.i64, 0))

        # Only update if registered
        with builder.if_then(is_registered):
            te_depth_ptr = builder.gep(thread_entry, [
                ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
            ], inbounds=True)
            builder.store(new_depth, te_depth_ptr)

    def update_thread_entry_shadow_stack_head(self, builder: ir.IRBuilder, frame_ptr: ir.Value):
        """Update the current thread's shadow_stack_head in its ThreadEntry.

        Called when the shadow stack top changes to keep ThreadEntry in sync.
        frame_ptr should be an i8* pointer to the current frame.
        """
        thread_entry = self.get_tls_thread_entry(builder)
        entry_int = builder.ptrtoint(thread_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', entry_int, ir.Constant(self.i64, 0))

        # Only update if registered
        with builder.if_then(is_registered):
            head_ptr = builder.gep(thread_entry, [
                ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
            ], inbounds=True)
            builder.store(frame_ptr, head_ptr)
