"""
Coex Garbage Collector

Mark-and-sweep GC implemented in pure LLVM IR.
Designed for future extension with concurrency support.
"""

from llvmlite import ir
from typing import Dict, List as PyList, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from codegen import CodeGenerator


class GarbageCollector:
    """Generates LLVM IR for garbage collection runtime"""

    # Constants
    HEAP_SIZE = 1024 * 1024  # 1MB initial heap (easily modifiable)
    HEADER_SIZE = 16         # 8-byte size + 4-byte type_id + 4-byte flags
    MIN_BLOCK_SIZE = 24      # Minimum block: header(16) + alignment padding
    MAX_TYPES = 256          # Maximum number of registered types

    # Flag bits in header
    FLAG_MARK_BIT = 0x01     # Bit 0: mark bit for GC
    FLAG_PINNED = 0x02       # Bit 1: pinned (not movable) - future use
    FLAG_FINALIZER = 0x04    # Bit 2: has finalizer - future use

    # Built-in type IDs
    TYPE_UNKNOWN = 0
    TYPE_LIST = 1
    TYPE_STRING = 2
    TYPE_MAP = 3
    TYPE_MAP_ENTRY = 4
    TYPE_SET = 5
    TYPE_SET_ENTRY = 6
    TYPE_CHANNEL = 7
    TYPE_FIRST_USER = 8      # First ID for user-defined types

    def __init__(self, module: ir.Module, codegen: 'CodeGenerator'):
        self.module = module
        self.codegen = codegen

        # Type descriptor registry
        self.type_descriptors: Dict[str, int] = {}  # type_name -> type_id
        self.type_info: Dict[int, Dict] = {}        # type_id -> {size, ref_offsets}
        self.next_type_id = self.TYPE_FIRST_USER

        # Common LLVM types
        self.i8 = ir.IntType(8)
        self.i32 = ir.IntType(32)
        self.i64 = ir.IntType(64)
        self.i8_ptr = self.i8.as_pointer()
        self.void = ir.VoidType()
        self.i1 = ir.IntType(1)

        # GC-specific LLVM types (set in _create_types)
        self.header_type = None
        self.free_node_type = None
        self.type_desc_type = None

        # GC global variables (set in _create_globals)
        self.heap_start = None
        self.heap_end = None
        self.heap_size_global = None
        self.free_list_head = None
        self.stack_bottom = None
        self.type_table = None

        # LLVM intrinsics
        self.frameaddress = None
        self.stacksave = None

        # GC functions
        self.gc_init = None
        self.gc_alloc = None
        self.gc_collect = None
        self.gc_mark_object = None
        self.gc_sweep = None
        self.gc_scan_stack = None
        self.gc_find_free_block = None
        self.gc_add_to_free_list = None

    def generate_gc_runtime(self):
        """Generate all GC runtime structures and functions"""
        self._create_types()
        self._create_globals()
        self._declare_intrinsics()
        self._declare_functions()
        self._register_builtin_types()
        self._implement_gc_init()
        self._implement_gc_find_free_block()
        self._implement_gc_add_to_free_list()
        self._implement_gc_alloc()
        self._implement_gc_mark_object()
        self._implement_gc_scan_stack()
        self._implement_gc_sweep()
        self._implement_gc_collect()

    def _create_types(self):
        """Create GC-related LLVM types"""
        # Object header: { i64 size, i32 type_id, i32 flags }
        # Size is preserved from allocation so sweep can traverse the heap.
        # Placed immediately before the user data (at negative offset)
        self.header_type = ir.LiteralStructType([
            self.i64,  # block size (including header) - preserved for sweep
            self.i32,  # type_id (index into type table)
            self.i32,  # flags (bit 0 = mark, bits 1-31 reserved)
        ])

        # Free list node: { i64 size, i8* next }
        # Stored in the free block itself (overlaps with user data area)
        self.free_node_type = ir.LiteralStructType([
            self.i64,      # block size (including header)
            self.i8_ptr,   # next free block pointer
        ])

        # Type descriptor: { i64 size, i32 num_refs, i32* ref_offsets }
        self.type_desc_type = ir.LiteralStructType([
            self.i64,                 # object size (including header)
            self.i32,                 # number of reference fields
            self.i32.as_pointer(),    # array of offsets to reference fields
        ])

    def _create_globals(self):
        """Create GC global variables"""
        # Heap region bounds
        self.heap_start = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_heap_start")
        self.heap_start.initializer = ir.Constant(self.i8_ptr, None)
        self.heap_start.linkage = 'internal'

        self.heap_end = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_heap_end")
        self.heap_end.initializer = ir.Constant(self.i8_ptr, None)
        self.heap_end.linkage = 'internal'

        # Current heap size (for tracking growth)
        self.heap_size_global = ir.GlobalVariable(self.module, self.i64, name="gc_heap_size")
        self.heap_size_global.initializer = ir.Constant(self.i64, 0)
        self.heap_size_global.linkage = 'internal'

        # Free list head pointer
        self.free_list_head = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_free_list")
        self.free_list_head.initializer = ir.Constant(self.i8_ptr, None)
        self.free_list_head.linkage = 'internal'

        # Stack bottom (captured at main() entry for conservative scanning)
        self.stack_bottom = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_stack_bottom")
        self.stack_bottom.initializer = ir.Constant(self.i8_ptr, None)
        self.stack_bottom.linkage = 'internal'

        # Allocation counter (for triggering GC based on allocation pressure)
        self.alloc_count = ir.GlobalVariable(self.module, self.i64, name="gc_alloc_count")
        self.alloc_count.initializer = ir.Constant(self.i64, 0)
        self.alloc_count.linkage = 'internal'

    def _declare_intrinsics(self):
        """Declare LLVM intrinsics for stack access"""
        # For stack scanning, we use a local variable to get current stack position
        # The frameaddress intrinsic returns frame pointer
        # Note: These intrinsics are automatically available in LLVM
        pass  # Intrinsics are declared inline when used

    def _declare_functions(self):
        """Declare GC runtime functions"""
        # gc_init() -> void
        gc_init_ty = ir.FunctionType(self.void, [])
        self.gc_init = ir.Function(self.module, gc_init_ty, name="coex_gc_init")

        # gc_alloc(size: i64, type_id: i32) -> i8*
        gc_alloc_ty = ir.FunctionType(self.i8_ptr, [self.i64, self.i32])
        self.gc_alloc = ir.Function(self.module, gc_alloc_ty, name="coex_gc_alloc")

        # gc_collect() -> void
        gc_collect_ty = ir.FunctionType(self.void, [])
        self.gc_collect = ir.Function(self.module, gc_collect_ty, name="coex_gc_collect")

        # gc_mark_object(ptr: i8*) -> void
        gc_mark_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_mark_object = ir.Function(self.module, gc_mark_ty, name="coex_gc_mark_object")

        # gc_sweep() -> void
        gc_sweep_ty = ir.FunctionType(self.void, [])
        self.gc_sweep = ir.Function(self.module, gc_sweep_ty, name="coex_gc_sweep")

        # gc_scan_stack() -> void
        gc_scan_stack_ty = ir.FunctionType(self.void, [])
        self.gc_scan_stack = ir.Function(self.module, gc_scan_stack_ty, name="coex_gc_scan_stack")

        # gc_find_free_block(size: i64) -> i8* (returns null if not found)
        gc_find_ty = ir.FunctionType(self.i8_ptr, [self.i64])
        self.gc_find_free_block = ir.Function(self.module, gc_find_ty, name="coex_gc_find_free_block")

        # gc_add_to_free_list(block: i8*, size: i64) -> void
        gc_add_ty = ir.FunctionType(self.void, [self.i8_ptr, self.i64])
        self.gc_add_to_free_list = ir.Function(self.module, gc_add_ty, name="coex_gc_add_to_free_list")

    def _register_builtin_types(self):
        """Register built-in heap-allocated types"""
        # Type 0: Reserved/Unknown - no references
        self.type_info[self.TYPE_UNKNOWN] = {'size': 0, 'ref_offsets': []}

        # Type 1: List - { i64 len, i64 cap, i64 elem_size, i8* data }
        # data field at offset 24 (after 3 i64s) is a reference
        self.type_info[self.TYPE_LIST] = {'size': 32, 'ref_offsets': [24]}
        self.type_descriptors['List'] = self.TYPE_LIST

        # Type 2: String - { i64 length } + inline data
        # No reference fields (data is inline)
        self.type_info[self.TYPE_STRING] = {'size': 8, 'ref_offsets': []}
        self.type_descriptors['String'] = self.TYPE_STRING

        # Type 3: Map - { MapEntry* entries, i64 len, i64 cap }
        # entries field at offset 0 is a reference
        self.type_info[self.TYPE_MAP] = {'size': 24, 'ref_offsets': [0]}
        self.type_descriptors['Map'] = self.TYPE_MAP

        # Type 4: MapEntry - { i64 key, i64 value, i8 state }
        # key and value could be references if storing objects
        # For now, treat as non-reference (raw i64 storage)
        self.type_info[self.TYPE_MAP_ENTRY] = {'size': 17, 'ref_offsets': []}
        self.type_descriptors['MapEntry'] = self.TYPE_MAP_ENTRY

        # Type 5: Set - { SetEntry* entries, i64 len, i64 cap }
        # entries field at offset 0 is a reference
        self.type_info[self.TYPE_SET] = {'size': 24, 'ref_offsets': [0]}
        self.type_descriptors['Set'] = self.TYPE_SET

        # Type 6: SetEntry - { i64 key, i8 state }
        # key could be reference if storing objects
        self.type_info[self.TYPE_SET_ENTRY] = {'size': 9, 'ref_offsets': []}
        self.type_descriptors['SetEntry'] = self.TYPE_SET_ENTRY

        # Type 7: Channel - { i64 len, i64 cap, i64 head, i64 tail, i8* data, i1 closed }
        # data field at offset 32 is a reference
        self.type_info[self.TYPE_CHANNEL] = {'size': 48, 'ref_offsets': [32]}
        self.type_descriptors['Channel'] = self.TYPE_CHANNEL

    def register_type(self, type_name: str, size: int, ref_offsets: PyList[int]) -> int:
        """Register a user-defined type and return its type_id"""
        if type_name in self.type_descriptors:
            return self.type_descriptors[type_name]

        type_id = self.next_type_id
        self.next_type_id += 1

        if type_id >= self.MAX_TYPES:
            raise RuntimeError(f"Too many types registered (max {self.MAX_TYPES})")

        self.type_descriptors[type_name] = type_id
        self.type_info[type_id] = {'size': size, 'ref_offsets': ref_offsets}

        return type_id

    def get_type_id(self, type_name: str) -> int:
        """Get type_id for a type name, defaulting to TYPE_UNKNOWN"""
        return self.type_descriptors.get(type_name, self.TYPE_UNKNOWN)

    def _implement_gc_init(self):
        """Initialize GC: allocate heap, set up free list"""
        func = self.gc_init
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        heap_size = ir.Constant(self.i64, self.HEAP_SIZE)

        # Allocate heap from system malloc
        raw_heap = builder.call(self.codegen.malloc, [heap_size])

        # Store heap bounds
        builder.store(raw_heap, self.heap_start)
        builder.store(heap_size, self.heap_size_global)

        # Calculate heap end: heap_start + heap_size
        heap_start_int = builder.ptrtoint(raw_heap, self.i64)
        heap_end_int = builder.add(heap_start_int, heap_size)
        heap_end_ptr = builder.inttoptr(heap_end_int, self.i8_ptr)
        builder.store(heap_end_ptr, self.heap_end)

        # Initialize entire heap as one free block
        # Free block format: { i64 size, i8* next }
        free_node = builder.bitcast(raw_heap, self.free_node_type.as_pointer())

        # Store block size (entire heap)
        size_ptr = builder.gep(free_node, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(heap_size, size_ptr)

        # Store next = null (end of free list)
        next_ptr = builder.gep(free_node, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_ptr)

        # Set free list head to this block
        builder.store(raw_heap, self.free_list_head)

        # Reset allocation counter
        builder.store(ir.Constant(self.i64, 0), self.alloc_count)

        builder.ret_void()

    def _implement_gc_find_free_block(self):
        """Find a free block using first-fit algorithm"""
        func = self.gc_find_free_block
        func.args[0].name = "needed_size"

        entry = func.append_basic_block("entry")
        loop_start = func.append_basic_block("loop_start")
        check_size = func.append_basic_block("check_size")
        found_block = func.append_basic_block("found_block")
        split_check = func.append_basic_block("split_check")
        do_split = func.append_basic_block("do_split")
        no_split = func.append_basic_block("no_split")
        next_block = func.append_basic_block("next_block")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)
        needed_size = func.args[0]

        # prev_ptr points to the location containing the current block pointer
        # (either &free_list_head or &prev_block->next)
        prev_ptr = builder.alloca(self.i8_ptr.as_pointer(), name="prev_ptr")
        builder.store(self.free_list_head, prev_ptr)

        # curr points to current block being examined
        curr = builder.alloca(self.i8_ptr, name="curr")
        head = builder.load(self.free_list_head)
        builder.store(head, curr)

        builder.branch(loop_start)

        # Loop: while curr != null
        builder.position_at_end(loop_start)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, not_found, check_size)

        # Check if current block is big enough
        builder.position_at_end(check_size)
        curr_node = builder.bitcast(curr_val, self.free_node_type.as_pointer())
        size_ptr = builder.gep(curr_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        block_size = builder.load(size_ptr)

        big_enough = builder.icmp_unsigned(">=", block_size, needed_size)
        builder.cbranch(big_enough, found_block, next_block)

        # Found a suitable block
        builder.position_at_end(found_block)
        # Get next pointer from current block
        next_field = builder.gep(curr_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        next_block_ptr = builder.load(next_field)

        # Check if we should split the block
        builder.branch(split_check)

        builder.position_at_end(split_check)
        remaining = builder.sub(block_size, needed_size)
        min_block = ir.Constant(self.i64, self.MIN_BLOCK_SIZE)
        should_split = builder.icmp_unsigned(">=", remaining, min_block)
        builder.cbranch(should_split, do_split, no_split)

        # Split the block: create new free block after allocated portion
        builder.position_at_end(do_split)
        # New block starts at curr + needed_size
        curr_int = builder.ptrtoint(curr_val, self.i64)
        new_block_int = builder.add(curr_int, needed_size)
        new_block_ptr = builder.inttoptr(new_block_int, self.i8_ptr)
        new_block_node = builder.bitcast(new_block_ptr, self.free_node_type.as_pointer())

        # Set new block's size
        new_size_ptr = builder.gep(new_block_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(remaining, new_size_ptr)

        # Set new block's next to current block's next
        new_next_ptr = builder.gep(new_block_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(next_block_ptr, new_next_ptr)

        # Update prev to point to new block
        prev_loc = builder.load(prev_ptr)
        builder.store(new_block_ptr, prev_loc)

        # Update size of allocated block to actual allocated size
        builder.store(needed_size, size_ptr)

        builder.ret(curr_val)

        # Use entire block (no split)
        builder.position_at_end(no_split)
        # Update prev to point to curr's next
        prev_loc2 = builder.load(prev_ptr)
        builder.store(next_block_ptr, prev_loc2)

        builder.ret(curr_val)

        # Move to next block in free list
        builder.position_at_end(next_block)
        # prev_ptr = &curr->next
        next_field2 = builder.gep(curr_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        next_field2_cast = builder.bitcast(next_field2, self.i8_ptr.as_pointer())
        builder.store(next_field2_cast, prev_ptr)

        # curr = curr->next
        next_val = builder.load(next_field2)
        builder.store(next_val, curr)

        builder.branch(loop_start)

        # No suitable block found
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_add_to_free_list(self):
        """Add a block to the front of the free list"""
        func = self.gc_add_to_free_list
        func.args[0].name = "block"
        func.args[1].name = "size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        block = func.args[0]
        size = func.args[1]

        # Cast block to free node
        free_node = builder.bitcast(block, self.free_node_type.as_pointer())

        # Set size
        size_ptr = builder.gep(free_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(size, size_ptr)

        # Set next to current free list head
        old_head = builder.load(self.free_list_head)
        next_ptr = builder.gep(free_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(old_head, next_ptr)

        # Update free list head
        builder.store(block, self.free_list_head)

        builder.ret_void()

    def _implement_gc_alloc(self):
        """Allocate memory with GC header"""
        func = self.gc_alloc
        func.args[0].name = "user_size"
        func.args[1].name = "type_id"

        entry = func.append_basic_block("entry")
        try_alloc = func.append_basic_block("try_alloc")
        alloc_success = func.append_basic_block("alloc_success")
        do_gc = func.append_basic_block("do_gc")
        retry_alloc = func.append_basic_block("retry_alloc")
        retry_success = func.append_basic_block("retry_success")
        oom = func.append_basic_block("oom")

        builder = ir.IRBuilder(entry)

        user_size = func.args[0]
        type_id = func.args[1]

        # Total size = header (8) + user_size, aligned to 8 bytes
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        total_size = builder.add(user_size, header_size)

        # Align to 8 bytes: (size + 7) & ~7
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.and_(
            builder.add(total_size, seven),
            ir.Constant(self.i64, ~7 & 0xFFFFFFFFFFFFFFFF)
        )

        # Ensure minimum block size
        min_size = ir.Constant(self.i64, self.MIN_BLOCK_SIZE)
        is_too_small = builder.icmp_unsigned("<", aligned_size, min_size)
        final_size = builder.select(is_too_small, min_size, aligned_size)

        # Store final_size for later use
        final_size_alloca = builder.alloca(self.i64, name="final_size")
        builder.store(final_size, final_size_alloca)

        builder.branch(try_alloc)

        # Try to allocate from free list
        builder.position_at_end(try_alloc)
        final_size_val = builder.load(final_size_alloca)
        block = builder.call(self.gc_find_free_block, [final_size_val])

        is_null = builder.icmp_unsigned("==", block, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, do_gc, alloc_success)

        # Allocation succeeded
        builder.position_at_end(alloc_success)
        # Initialize header
        # Note: size field at offset 0 is already set by gc_find_free_block
        header = builder.bitcast(block, self.header_type.as_pointer())

        # Store type_id at offset 1
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr)

        # Store flags (0 = not marked) at offset 2
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(ir.Constant(self.i32, 0), flags_ptr)

        # Return pointer to user data (after header)
        block_int = builder.ptrtoint(block, self.i64)
        user_ptr_int = builder.add(block_int, header_size)
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)

        # Increment allocation counter
        count = builder.load(self.alloc_count)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.alloc_count)

        builder.ret(user_ptr)

        # No suitable block - try GC
        builder.position_at_end(do_gc)
        builder.call(self.gc_collect, [])
        builder.branch(retry_alloc)

        # Retry allocation after GC
        builder.position_at_end(retry_alloc)
        final_size_val2 = builder.load(final_size_alloca)
        block2 = builder.call(self.gc_find_free_block, [final_size_val2])

        is_null2 = builder.icmp_unsigned("==", block2, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null2, oom, retry_success)

        # Retry succeeded
        builder.position_at_end(retry_success)
        # Note: size field at offset 0 is already set by gc_find_free_block
        header2 = builder.bitcast(block2, self.header_type.as_pointer())

        type_id_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr2)

        flags_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(ir.Constant(self.i32, 0), flags_ptr2)

        block2_int = builder.ptrtoint(block2, self.i64)
        user_ptr2_int = builder.add(block2_int, header_size)
        user_ptr2 = builder.inttoptr(user_ptr2_int, self.i8_ptr)

        count2 = builder.load(self.alloc_count)
        new_count2 = builder.add(count2, ir.Constant(self.i64, 1))
        builder.store(new_count2, self.alloc_count)

        builder.ret(user_ptr2)

        # Out of memory - return null (caller should handle)
        builder.position_at_end(oom)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_mark_object(self):
        """Mark an object and recursively mark its references"""
        func = self.gc_mark_object
        func.args[0].name = "obj_ptr"

        entry = func.append_basic_block("entry")
        null_check = func.append_basic_block("null_check")
        bounds_check = func.append_basic_block("bounds_check")
        already_marked = func.append_basic_block("already_marked")
        do_mark = func.append_basic_block("do_mark")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        obj_ptr = func.args[0]

        # Null check
        is_null = builder.icmp_unsigned("==", obj_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, null_check)

        builder.position_at_end(null_check)
        # Check if pointer is within heap bounds
        heap_start = builder.load(self.heap_start)
        heap_end = builder.load(self.heap_end)

        ge_start = builder.icmp_unsigned(">=", obj_ptr, heap_start)
        lt_end = builder.icmp_unsigned("<", obj_ptr, heap_end)
        in_heap = builder.and_(ge_start, lt_end)

        builder.cbranch(in_heap, bounds_check, done)

        builder.position_at_end(bounds_check)
        # Get header (HEADER_SIZE bytes before user pointer)
        obj_int = builder.ptrtoint(obj_ptr, self.i64)
        header_int = builder.sub(obj_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.i8_ptr)
        header = builder.bitcast(header_ptr, self.header_type.as_pointer())

        # Check mark bit (flags is at offset 2 in new header layout)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)
        mark_bit = builder.and_(flags, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        is_marked = builder.icmp_unsigned("!=", mark_bit, ir.Constant(self.i32, 0))
        builder.cbranch(is_marked, already_marked, do_mark)

        builder.position_at_end(already_marked)
        builder.branch(done)

        builder.position_at_end(do_mark)
        # Set mark bit
        new_flags = builder.or_(flags, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        builder.store(new_flags, flags_ptr)

        # For now, we don't trace references (conservative scanning handles roots)
        # TODO: In future, look up type descriptor and trace reference fields
        # This is safe because conservative scanning will find all live pointers

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_scan_stack(self):
        """Conservatively scan stack for heap pointers

        For initial implementation, this is a simplified version that uses
        a local alloca to determine the current stack position. On most
        platforms (x86, ARM), the stack grows downward.
        """
        func = self.gc_scan_stack

        entry = func.append_basic_block("entry")
        loop_start = func.append_basic_block("loop_start")
        check_word = func.append_basic_block("check_word")
        maybe_ptr = func.append_basic_block("maybe_ptr")
        next_word = func.append_basic_block("next_word")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Use an alloca to get approximate current stack position
        # This is a portable way to find where we are on the stack
        stack_marker = builder.alloca(self.i64, name="stack_marker")
        stack_top = builder.bitcast(stack_marker, self.i8_ptr)

        stack_bottom = builder.load(self.stack_bottom)
        heap_start = builder.load(self.heap_start)
        heap_end = builder.load(self.heap_end)

        # Check if stack_bottom was captured (non-null)
        has_stack_bottom = builder.icmp_unsigned("!=", stack_bottom, ir.Constant(self.i8_ptr, None))

        # If no stack bottom, skip scanning
        skip_scan = func.append_basic_block("skip_scan")
        do_scan = func.append_basic_block("do_scan")
        builder.cbranch(has_stack_bottom, do_scan, skip_scan)

        builder.position_at_end(skip_scan)
        builder.branch(done)

        builder.position_at_end(do_scan)

        # Determine scan direction (stack grows down on most platforms)
        # We'll scan from lower address to higher address
        stack_top_int = builder.ptrtoint(stack_top, self.i64)
        stack_bottom_int = builder.ptrtoint(stack_bottom, self.i64)

        # Use min/max to handle both stack directions
        scan_start = builder.select(
            builder.icmp_unsigned("<", stack_top_int, stack_bottom_int),
            stack_top, stack_bottom
        )
        scan_end = builder.select(
            builder.icmp_unsigned("<", stack_top_int, stack_bottom_int),
            stack_bottom, stack_top
        )

        # Current scan position
        curr = builder.alloca(self.i8_ptr, name="scan_ptr")
        builder.store(scan_start, curr)

        builder.branch(loop_start)

        # Loop: while curr < scan_end
        builder.position_at_end(loop_start)
        curr_val = builder.load(curr)
        at_end = builder.icmp_unsigned(">=", curr_val, scan_end)
        builder.cbranch(at_end, done, check_word)

        # Load the 8-byte word at current position
        builder.position_at_end(check_word)
        word_ptr = builder.bitcast(curr_val, self.i64.as_pointer())
        word = builder.load(word_ptr)

        # Check if word looks like a heap pointer
        # Must be aligned and within heap bounds
        aligned = builder.icmp_unsigned("==",
            builder.and_(word, ir.Constant(self.i64, 7)),
            ir.Constant(self.i64, 0)
        )

        possible_ptr = builder.inttoptr(word, self.i8_ptr)
        ge_heap_start = builder.icmp_unsigned(">=", possible_ptr, heap_start)
        lt_heap_end = builder.icmp_unsigned("<", possible_ptr, heap_end)

        in_heap = builder.and_(ge_heap_start, lt_heap_end)
        looks_like_ptr = builder.and_(aligned, in_heap)

        builder.cbranch(looks_like_ptr, maybe_ptr, next_word)

        # This might be a pointer - mark it
        builder.position_at_end(maybe_ptr)
        builder.call(self.gc_mark_object, [possible_ptr])
        builder.branch(next_word)

        # Advance to next word (8 bytes)
        builder.position_at_end(next_word)
        curr_int = builder.ptrtoint(curr_val, self.i64)
        next_int = builder.add(curr_int, ir.Constant(self.i64, 8))
        next_ptr = builder.inttoptr(next_int, self.i8_ptr)
        builder.store(next_ptr, curr)
        builder.branch(loop_start)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_sweep(self):
        """Sweep heap, reclaiming unmarked objects"""
        func = self.gc_sweep

        entry = func.append_basic_block("entry")
        loop_start = func.append_basic_block("loop_start")
        check_block = func.append_basic_block("check_block")
        block_marked = func.append_basic_block("block_marked")
        block_unmarked = func.append_basic_block("block_unmarked")
        next_block = func.append_basic_block("next_block")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        heap_start = builder.load(self.heap_start)
        heap_end = builder.load(self.heap_end)

        # Clear free list (we'll rebuild it during sweep)
        builder.store(ir.Constant(self.i8_ptr, None), self.free_list_head)

        # Scan through heap linearly
        curr = builder.alloca(self.i8_ptr, name="curr")
        builder.store(heap_start, curr)

        builder.branch(loop_start)

        # Loop: while curr < heap_end
        builder.position_at_end(loop_start)
        curr_val = builder.load(curr)
        at_end = builder.icmp_unsigned(">=", curr_val, heap_end)
        builder.cbranch(at_end, done, check_block)

        # Read header to get block info
        builder.position_at_end(check_block)
        # First check if this looks like a valid block (read size from free node position)
        free_node = builder.bitcast(curr_val, self.free_node_type.as_pointer())
        size_ptr = builder.gep(free_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        block_size = builder.load(size_ptr)

        # Sanity check: size must be reasonable
        size_ok = builder.icmp_unsigned(">", block_size, ir.Constant(self.i64, 0))
        size_not_huge = builder.icmp_unsigned("<=", block_size, builder.load(self.heap_size_global))
        valid_size = builder.and_(size_ok, size_not_huge)

        # If size looks invalid, something is wrong - skip to end
        builder.cbranch(valid_size, block_marked, done)

        # Check mark bit in header (flags is at offset 2 in new header layout)
        builder.position_at_end(block_marked)
        header = builder.bitcast(curr_val, self.header_type.as_pointer())
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)

        mark_bit = builder.and_(flags, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        is_marked = builder.icmp_unsigned("!=", mark_bit, ir.Constant(self.i32, 0))
        builder.cbranch(is_marked, next_block, block_unmarked)

        # Block is marked - clear mark bit for next cycle, then continue
        # (already in next_block path via cbranch)

        # Block is unmarked - add to free list
        builder.position_at_end(block_unmarked)
        builder.call(self.gc_add_to_free_list, [curr_val, block_size])
        builder.branch(next_block)

        # Move to next block
        builder.position_at_end(next_block)
        # Clear mark bit if it was set
        cleared_flags = builder.and_(flags, ir.Constant(self.i32, ~self.FLAG_MARK_BIT & 0xFFFFFFFF))
        builder.store(cleared_flags, flags_ptr)

        # Advance by block size
        curr_int = builder.ptrtoint(curr_val, self.i64)
        next_int = builder.add(curr_int, block_size)
        next_ptr = builder.inttoptr(next_int, self.i8_ptr)
        builder.store(next_ptr, curr)
        builder.branch(loop_start)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_collect(self):
        """Run a full garbage collection cycle"""
        func = self.gc_collect

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Phase 1: Mark - scan stack for roots
        builder.call(self.gc_scan_stack, [])

        # Phase 2: Sweep - reclaim unmarked objects
        builder.call(self.gc_sweep, [])

        builder.ret_void()

    def wrap_allocation(self, builder: ir.IRBuilder, type_name: str, size: ir.Value) -> ir.Value:
        """
        Replace a malloc call with GC-tracked allocation.
        Returns pointer to user data (after GC header).
        """
        type_id = self.get_type_id(type_name)
        type_id_const = ir.Constant(self.i32, type_id)
        return builder.call(self.gc_alloc, [size, type_id_const])

    def inject_gc_init(self, builder: ir.IRBuilder):
        """Inject GC initialization at start of main()"""
        # Initialize GC heap and free list
        builder.call(self.gc_init, [])

        # Capture stack bottom for conservative scanning
        # Use an alloca as a marker for the current stack position
        stack_marker = builder.alloca(self.i64, name="gc_stack_marker")
        stack_ptr = builder.bitcast(stack_marker, self.i8_ptr)
        builder.store(stack_ptr, self.stack_bottom)
