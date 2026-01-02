"""
GC Handle Management Module

This module provides handle table operations for the Coex garbage collector.
Handles are i64 indices into a global handle table that maps to object pointers.

Handle Table Design:
- gc_handle_table: Global array of i8* pointers
- Handle 0 is reserved as null
- Handles are allocated via bump allocation or free list reuse
- Retired handles use deferred reclamation (MI-6 pattern)

Functions implemented:
- gc_handle_table_grow: Double table capacity when exhausted
- gc_handle_alloc: Allocate a handle slot
- gc_handle_free: Return handle to free list (immediate)
- gc_handle_deref: Get object pointer from handle
- gc_handle_store: Store pointer in handle slot
- gc_ptr_to_handle: Recover handle from object's header
- gc_handle_retire: Add handle to retired list (deferred)
- gc_promote_retired_handles: Move retired to free list
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from coex_gc_original import GarbageCollector


class HandleManager:
    """Manages handle table operations for the garbage collector.

    The handle table provides indirection between code and heap objects,
    enabling future concurrent GC without pointer fixup.
    """

    def __init__(self, gc: 'GarbageCollector'):
        """Initialize with reference to parent GC instance."""
        self.gc = gc

    # Property accessors for commonly used GC attributes
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
    def i8_ptr_ptr(self):
        return self.gc.i8_ptr_ptr

    @property
    def header_type(self):
        return self.gc.header_type

    @property
    def HEADER_SIZE(self):
        return self.gc.HEADER_SIZE

    @property
    def codegen(self):
        return self.gc.codegen

    # Global variables
    @property
    def gc_handle_table(self):
        return self.gc.gc_handle_table

    @property
    def gc_handle_table_size(self):
        return self.gc.gc_handle_table_size

    @property
    def gc_next_handle(self):
        return self.gc.gc_next_handle

    @property
    def gc_handle_free_list(self):
        return self.gc.gc_handle_free_list

    @property
    def gc_handle_retired_list(self):
        return self.gc.gc_handle_retired_list

    # Function references
    @property
    def gc_handle_table_grow(self):
        return self.gc.gc_handle_table_grow

    @property
    def gc_handle_alloc(self):
        return self.gc.gc_handle_alloc

    @property
    def gc_handle_free(self):
        return self.gc.gc_handle_free

    @property
    def gc_handle_deref(self):
        return self.gc.gc_handle_deref

    @property
    def gc_handle_store(self):
        return self.gc.gc_handle_store

    @property
    def gc_ptr_to_handle(self):
        return self.gc.gc_ptr_to_handle

    @property
    def gc_handle_retire(self):
        return self.gc.gc_handle_retire

    @property
    def gc_promote_retired_handles(self):
        return self.gc.gc_promote_retired_handles

    def implement_gc_handle_table_grow(self):
        """Double the handle table size when exhausted.

        This is called when gc_next_handle exceeds gc_handle_table_size
        and the free list is empty. Doubles the table capacity and copies
        existing entries to the new table.
        """
        func = self.gc_handle_table_grow
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Load current table state
        old_table = builder.load(self.gc_handle_table)
        old_size = builder.load(self.gc_handle_table_size)

        # Calculate new size (double)
        new_size = builder.mul(old_size, ir.Constant(self.i64, 2))
        new_bytes = builder.mul(new_size, ir.Constant(self.i64, 8))

        # Allocate new table
        new_table_raw = builder.call(self.codegen.malloc, [new_bytes])
        new_table = builder.bitcast(new_table_raw, self.i8_ptr_ptr)

        # Initialize new table to NULL
        builder.call(self.codegen.memset, [
            new_table_raw,
            ir.Constant(self.i8, 0),
            new_bytes
        ])

        # Copy old entries to new table
        old_bytes = builder.mul(old_size, ir.Constant(self.i64, 8))
        old_table_raw = builder.bitcast(old_table, self.i8_ptr)
        builder.call(self.codegen.memcpy, [
            new_table_raw,
            old_table_raw,
            old_bytes
        ])

        # Update globals
        builder.store(new_table, self.gc_handle_table)
        builder.store(new_size, self.gc_handle_table_size)

        # Free old table
        builder.call(self.codegen.free, [old_table_raw])

        builder.ret_void()

    def implement_gc_handle_alloc(self):
        """Allocate a handle slot, returning the handle index.

        Strategy:
        1. Try free list first (LIFO reuse)
        2. If free list empty, bump gc_next_handle
        3. If bump exceeds table size, grow table and retry

        Returns: i64 handle (never 0, which represents null)
        """
        func = self.gc_handle_alloc
        entry = func.append_basic_block("entry")
        try_free_list = func.append_basic_block("try_free_list")
        use_free_list = func.append_basic_block("use_free_list")
        try_bump = func.append_basic_block("try_bump")
        need_grow = func.append_basic_block("need_grow")
        use_bump = func.append_basic_block("use_bump")

        builder = ir.IRBuilder(entry)
        builder.branch(try_free_list)

        # Try free list first
        builder.position_at_end(try_free_list)
        free_head = builder.load(self.gc_handle_free_list)
        has_free = builder.icmp_unsigned('!=', free_head, ir.Constant(self.i64, 0))
        builder.cbranch(has_free, use_free_list, try_bump)

        # Use free list entry
        builder.position_at_end(use_free_list)
        # Load next free from the slot (stored as i64 in the pointer slot)
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [free_head])
        # The slot stores the next free handle as a pointer-sized value
        next_free_ptr = builder.load(slot_ptr)
        next_free = builder.ptrtoint(next_free_ptr, self.i64)
        builder.store(next_free, self.gc_handle_free_list)
        # Clear the slot (it will be set by gc_handle_store)
        builder.store(ir.Constant(self.i8_ptr, None), slot_ptr)
        builder.ret(free_head)

        # Try bump allocation
        builder.position_at_end(try_bump)
        next_handle = builder.load(self.gc_next_handle)
        table_size = builder.load(self.gc_handle_table_size)
        need_grow_cond = builder.icmp_unsigned('>=', next_handle, table_size)
        builder.cbranch(need_grow_cond, need_grow, use_bump)

        # Need to grow table
        builder.position_at_end(need_grow)
        builder.call(self.gc_handle_table_grow, [])
        builder.branch(try_bump)  # Retry after growth

        # Use bump allocation
        builder.position_at_end(use_bump)
        handle = builder.load(self.gc_next_handle)
        new_next = builder.add(handle, ir.Constant(self.i64, 1))
        builder.store(new_next, self.gc_next_handle)
        builder.ret(handle)

    def implement_gc_handle_free(self):
        """Return a handle to the free list (called during sweep).

        The freed slot stores the previous free list head, forming a LIFO list.
        """
        func = self.gc_handle_free
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        handle = func.args[0]

        # Get current free list head
        old_head = builder.load(self.gc_handle_free_list)

        # Store old head in the slot being freed (as a pointer-sized value)
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [handle])
        old_head_as_ptr = builder.inttoptr(old_head, self.i8_ptr)
        builder.store(old_head_as_ptr, slot_ptr)

        # Update free list head
        builder.store(handle, self.gc_handle_free_list)

        builder.ret_void()

    def implement_gc_handle_deref(self):
        """Dereference a handle to get the object pointer.

        Returns NULL if handle is 0 (null handle).
        Otherwise returns gc_handle_table[handle].
        """
        func = self.gc_handle_deref
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        is_null = func.append_basic_block("is_null")
        not_null = func.append_basic_block("not_null")

        builder = ir.IRBuilder(entry)

        handle = func.args[0]

        # Check for null handle
        is_zero = builder.icmp_unsigned('==', handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_zero, is_null, not_null)

        # Return NULL for handle 0
        builder.position_at_end(is_null)
        builder.ret(ir.Constant(self.i8_ptr, None))

        # Dereference non-null handle
        builder.position_at_end(not_null)
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [handle])
        ptr = builder.load(slot_ptr)
        builder.ret(ptr)

    def implement_gc_handle_store(self):
        """Store a pointer in a handle slot.

        gc_handle_table[handle] = ptr
        """
        func = self.gc_handle_store
        func.args[0].name = "handle"
        func.args[1].name = "ptr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        handle = func.args[0]
        ptr = func.args[1]

        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [handle])
        builder.store(ptr, slot_ptr)

        builder.ret_void()

    def implement_gc_ptr_to_handle(self):
        """Get the handle for an object from its pointer.

        Reads the handle from the object's header (forward field at offset 24).
        Returns 0 if ptr is null.
        """
        func = self.gc_ptr_to_handle
        func.args[0].name = "ptr"

        entry = func.append_basic_block("entry")
        is_null = func.append_basic_block("is_null")
        not_null = func.append_basic_block("not_null")

        builder = ir.IRBuilder(entry)

        ptr = func.args[0]

        # Check for null pointer
        ptr_int = builder.ptrtoint(ptr, self.i64)
        is_zero = builder.icmp_unsigned('==', ptr_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_zero, is_null, not_null)

        # Return 0 for null pointer
        builder.position_at_end(is_null)
        builder.ret(ir.Constant(self.i64, 0))

        # Get header and read handle from forward field
        builder.position_at_end(not_null)
        # Header is HEADER_SIZE bytes before the object pointer
        header_int = builder.sub(ptr_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.header_type.as_pointer())
        # Forward field is at index 3
        forward_ptr = builder.gep(header_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        handle = builder.load(forward_ptr)
        builder.ret(handle)

    def implement_gc_handle_retire(self):
        """Add a handle to the retired list for deferred reclamation (MI-6).

        Instead of immediately adding freed handles to the free list,
        we add them to a retired list. They become available for reuse
        only after the next GC cycle completes. This prevents use-after-free
        issues in concurrent scenarios.

        The retired list uses the same structure as the free list:
        each retired slot stores the next retired handle index.
        """
        func = self.gc_handle_retire
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        handle = func.args[0]

        # Get current retired list head
        old_head = builder.load(self.gc_handle_retired_list)

        # Store old head in the slot being retired (as a pointer-sized value)
        # This links retired handles into a chain
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [handle])
        old_head_as_ptr = builder.inttoptr(old_head, self.i8_ptr)
        builder.store(old_head_as_ptr, slot_ptr)

        # Update retired list head to this handle
        builder.store(handle, self.gc_handle_retired_list)

        builder.ret_void()

    def implement_gc_promote_retired_handles(self):
        """Move all retired handles to the free list.

        Called at the start of each GC cycle (before sweep). This promotes
        handles retired in the previous cycle to be available for reuse.

        Algorithm:
        1. If retired list is empty, return
        2. Walk retired list to find the tail
        3. Link tail to current free list head
        4. Set free list head to retired list head
        5. Clear retired list
        """
        func = self.gc_promote_retired_handles

        entry = func.append_basic_block("entry")
        check_empty = func.append_basic_block("check_empty")
        find_tail = func.append_basic_block("find_tail")
        check_next = func.append_basic_block("check_next")
        advance = func.append_basic_block("advance")
        link_lists = func.append_basic_block("link_lists")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Load retired list head
        retired_head = builder.load(self.gc_handle_retired_list)
        builder.branch(check_empty)

        # Check if retired list is empty
        builder.position_at_end(check_empty)
        is_empty = builder.icmp_unsigned("==", retired_head, ir.Constant(self.i64, 0))
        builder.cbranch(is_empty, done, find_tail)

        # Find the tail of the retired list
        builder.position_at_end(find_tail)
        current = builder.alloca(self.i64, name="current")
        builder.store(retired_head, current)
        builder.branch(check_next)

        # Check if current node has a next pointer
        builder.position_at_end(check_next)
        curr_val = builder.load(current)
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [curr_val])
        next_ptr = builder.load(slot_ptr)
        next_handle = builder.ptrtoint(next_ptr, self.i64)
        has_next = builder.icmp_unsigned("!=", next_handle, ir.Constant(self.i64, 0))
        builder.cbranch(has_next, advance, link_lists)

        # Advance to next node
        builder.position_at_end(advance)
        builder.store(next_handle, current)
        builder.branch(check_next)

        # Link retired list tail to free list head, update free list head
        builder.position_at_end(link_lists)
        # current now points to the tail of retired list
        tail = builder.load(current)
        free_head = builder.load(self.gc_handle_free_list)

        # Link tail to free list head
        table2 = builder.load(self.gc_handle_table)
        tail_slot_ptr = builder.gep(table2, [tail])
        free_head_as_ptr = builder.inttoptr(free_head, self.i8_ptr)
        builder.store(free_head_as_ptr, tail_slot_ptr)

        # Set free list head to retired list head
        builder.store(retired_head, self.gc_handle_free_list)

        # Clear retired list
        builder.store(ir.Constant(self.i64, 0), self.gc_handle_retired_list)

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()
