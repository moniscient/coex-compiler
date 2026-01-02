"""
Coex GC Diagnostics Module

Provides debugging and diagnostic functions for the garbage collector:
- gc_trace: Conditional trace output
- gc_dump_stats: Print GC statistics
- gc_dump_heap: Print all heap objects
- gc_dump_roots: Print shadow stack roots
- gc_dump_object: Print single object details
- gc_validate_heap: Validate heap integrity
- gc_set_trace_level: Set trace verbosity
- gc_fragmentation_report: Analyze heap fragmentation
- gc_dump_handle_table: Print handle table state
- gc_dump_shadow_stacks: Print shadow stack frames

These are exposed as Coex built-in functions for debugging.
"""

from llvmlite import ir
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from coex_gc_original import GarbageCollector


class GCDiagnostics:
    """Generates LLVM IR for GC diagnostic functions."""

    def __init__(self, gc: 'GarbageCollector'):
        """Initialize with reference to parent GarbageCollector.

        Args:
            gc: The GarbageCollector instance that owns this diagnostics module
        """
        self.gc = gc

    # Convenience properties for commonly accessed GC attributes
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

    def implement_gc_trace(self):
        """Implement trace output function based on current trace level"""
        func = self.gc.gc_trace
        func.args[0].name = "level"
        func.args[1].name = "msg"

        entry = func.append_basic_block("entry")
        do_trace = func.append_basic_block("do_trace")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        level = func.args[0]
        msg = func.args[1]

        # Check if trace level is high enough
        current_level = builder.load(self.gc.gc_trace_level)
        should_trace = builder.icmp_unsigned(">=", current_level, level)
        builder.cbranch(should_trace, do_trace, done)

        # Print the trace message
        builder.position_at_end(do_trace)
        # Call puts to output the message
        puts_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        if "puts" in self.module.globals:
            puts = self.module.globals["puts"]
        else:
            puts = ir.Function(self.module, puts_ty, name="puts")
        builder.call(puts, [msg])
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def implement_gc_dump_stats(self):
        """Implement function to print current GC statistics"""
        func = self.gc.gc_dump_stats

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Create format strings for printf
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Header format
        header_str = "[GC:STATS] === GC Statistics ===\n"
        header_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(header_str) + 1), name=".gc_stats_header")
        header_global.global_constant = True
        header_global.linkage = 'private'
        header_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(header_str) + 1),
                                                  bytearray(header_str.encode('utf-8')) + bytearray([0]))
        header_ptr = builder.bitcast(header_global, self.i8_ptr)
        builder.call(printf, [header_ptr])

        # Allocation stats format
        alloc_fmt = "[GC:STATS] total_allocations: %lld, total_bytes: %lld\n"
        alloc_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(alloc_fmt) + 1), name=".gc_stats_alloc")
        alloc_global.global_constant = True
        alloc_global.linkage = 'private'
        alloc_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(alloc_fmt) + 1),
                                                bytearray(alloc_fmt.encode('utf-8')) + bytearray([0]))
        alloc_ptr = builder.bitcast(alloc_global, self.i8_ptr)

        # Load stats fields
        total_allocs_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        total_allocs = builder.load(total_allocs_ptr)
        total_bytes_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        total_bytes = builder.load(total_bytes_ptr)
        builder.call(printf, [alloc_ptr, total_allocs, total_bytes])

        # Collection stats format
        collect_fmt = "[GC:STATS] collections: %lld, marked_last: %lld, swept_last: %lld\n"
        collect_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(collect_fmt) + 1), name=".gc_stats_collect")
        collect_global.global_constant = True
        collect_global.linkage = 'private'
        collect_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(collect_fmt) + 1),
                                                  bytearray(collect_fmt.encode('utf-8')) + bytearray([0]))
        collect_ptr = builder.bitcast(collect_global, self.i8_ptr)

        collections_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        collections = builder.load(collections_ptr)
        marked_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)], inbounds=True)
        marked = builder.load(marked_ptr)
        swept_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
        swept = builder.load(swept_ptr)
        builder.call(printf, [collect_ptr, collections, marked, swept])

        # Timing stats format
        timing_fmt = "[GC:STATS] last_gc_ns: %lld\n"
        timing_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(timing_fmt) + 1), name=".gc_stats_timing")
        timing_global.global_constant = True
        timing_global.linkage = 'private'
        timing_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(timing_fmt) + 1),
                                                 bytearray(timing_fmt.encode('utf-8')) + bytearray([0]))
        timing_ptr = builder.bitcast(timing_global, self.i8_ptr)

        last_gc_ns_ptr = builder.gep(self.gc.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 16)], inbounds=True)
        last_gc_ns = builder.load(last_gc_ns_ptr)
        builder.call(printf, [timing_ptr, last_gc_ns])

        builder.ret_void()

    def implement_gc_dump_heap(self):
        """Implement function to print all objects in the heap"""
        func = self.gc.gc_dump_heap

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        print_obj = func.append_basic_block("print_obj")
        next_obj = func.append_basic_block("next_obj")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Printf for output
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Header
        header_str = "[GC:HEAP] === Heap Dump ===\n"
        header_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(header_str) + 1), name=".gc_heap_header")
        header_global.global_constant = True
        header_global.linkage = 'private'
        header_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(header_str) + 1),
                                                  bytearray(header_str.encode('utf-8')) + bytearray([0]))
        header_ptr = builder.bitcast(header_global, self.i8_ptr)
        builder.call(printf, [header_ptr])

        # Object format string
        obj_fmt = "[GC:HEAP] obj=%p type=%d size=%lld marked=%d\n"
        obj_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(obj_fmt) + 1), name=".gc_heap_obj")
        obj_global.global_constant = True
        obj_global.linkage = 'private'
        obj_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(obj_fmt) + 1),
                                              bytearray(obj_fmt.encode('utf-8')) + bytearray([0]))
        obj_ptr = builder.bitcast(obj_global, self.i8_ptr)

        # Count format
        count_fmt = "[GC:HEAP] Total objects: %lld\n"
        count_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(count_fmt) + 1), name=".gc_heap_count")
        count_global.global_constant = True
        count_global.linkage = 'private'
        count_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(count_fmt) + 1),
                                                bytearray(count_fmt.encode('utf-8')) + bytearray([0]))
        count_ptr_fmt = builder.bitcast(count_global, self.i8_ptr)

        # Allocate counter
        count_alloca = builder.alloca(self.i64, name="count")
        builder.store(ir.Constant(self.i64, 0), count_alloca)

        # Get head of allocation list
        head = builder.load(self.gc.gc_alloc_list)
        curr_alloca = builder.alloca(self.i8_ptr, name="curr")
        builder.store(head, curr_alloca)
        builder.branch(loop)

        # Loop through allocation list
        builder.position_at_end(loop)
        curr = builder.load(curr_alloca)
        is_null = builder.icmp_unsigned("==", curr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, print_obj)

        # Print object info
        builder.position_at_end(print_obj)
        node = builder.bitcast(curr, self.gc.alloc_node_type.as_pointer())

        # Phase 7: Get handle and dereference to get data pointer
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc.gc_handle_deref, [obj_handle])

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.gc.HEADER_SIZE))
        header_ptr_local = builder.inttoptr(header_int, self.gc.header_type.as_pointer())

        # Load header fields
        size_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        # Phase 1: type_id and flags are now i64
        type_id_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        flags_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)

        # Extract mark bit (Phase 1: flags is i64)
        marked = builder.and_(flags, ir.Constant(self.i64, self.gc.FLAG_MARK_BIT))

        builder.call(printf, [obj_ptr, data_ptr, type_id, size, marked])

        # Increment counter
        count_val = builder.load(count_alloca)
        new_count = builder.add(count_val, ir.Constant(self.i64, 1))
        builder.store(new_count, count_alloca)

        builder.branch(next_obj)

        # Get next object
        builder.position_at_end(next_obj)
        next_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_ptr = builder.load(next_ptr_ptr)
        builder.store(next_ptr, curr_alloca)
        builder.branch(loop)

        # Done
        builder.position_at_end(done)
        final_count = builder.load(count_alloca)
        builder.call(printf, [count_ptr_fmt, final_count])
        builder.ret_void()

    def implement_gc_dump_roots(self):
        """Implement function to print all roots from shadow stack"""
        func = self.gc.gc_dump_roots

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        process_frame = func.append_basic_block("process_frame")
        root_loop = func.append_basic_block("root_loop")
        print_root = func.append_basic_block("print_root")
        next_root = func.append_basic_block("next_root")
        next_frame = func.append_basic_block("next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Printf for output
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Header
        header_str = "[GC:ROOTS] === Root Dump (depth=%lld) ===\n"
        header_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(header_str) + 1), name=".gc_roots_header")
        header_global.global_constant = True
        header_global.linkage = 'private'
        header_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(header_str) + 1),
                                                  bytearray(header_str.encode('utf-8')) + bytearray([0]))
        header_ptr = builder.bitcast(header_global, self.i8_ptr)
        depth = builder.load(self.gc.gc_frame_depth)
        builder.call(printf, [header_ptr, depth])

        # Frame format
        frame_fmt = "[GC:ROOTS] Frame %lld: %lld roots\n"
        frame_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(frame_fmt) + 1), name=".gc_roots_frame")
        frame_global.global_constant = True
        frame_global.linkage = 'private'
        frame_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(frame_fmt) + 1),
                                                bytearray(frame_fmt.encode('utf-8')) + bytearray([0]))
        frame_ptr_fmt = builder.bitcast(frame_global, self.i8_ptr)

        # Root format
        root_fmt = "[GC:ROOTS]   root[%lld]=%p\n"
        root_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(root_fmt) + 1), name=".gc_roots_root")
        root_global.global_constant = True
        root_global.linkage = 'private'
        root_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(root_fmt) + 1),
                                               bytearray(root_fmt.encode('utf-8')) + bytearray([0]))
        root_ptr_fmt = builder.bitcast(root_global, self.i8_ptr)

        # Initialize frame pointer and counter
        frame_ptr_alloca = builder.alloca(self.i8_ptr, name="frame_ptr")
        frame_num_alloca = builder.alloca(self.i64, name="frame_num")
        frame_top = builder.load(self.gc.gc_frame_top)
        builder.store(frame_top, frame_ptr_alloca)
        builder.store(ir.Constant(self.i64, 0), frame_num_alloca)
        builder.branch(frame_loop)

        # Frame loop
        builder.position_at_end(frame_loop)
        curr_frame_raw = builder.load(frame_ptr_alloca)
        is_null = builder.icmp_unsigned("==", curr_frame_raw, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, process_frame)

        # Process frame
        builder.position_at_end(process_frame)
        frame = builder.bitcast(curr_frame_raw, self.gc.gc_frame_type.as_pointer())

        # Get num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)
        frame_num = builder.load(frame_num_alloca)
        builder.call(printf, [frame_ptr_fmt, frame_num, num_roots])

        # Get roots pointer
        roots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        roots_ptr = builder.load(roots_ptr_ptr)

        # Initialize root index
        root_idx_alloca = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx_alloca)
        builder.branch(root_loop)

        # Root loop
        builder.position_at_end(root_loop)
        root_idx = builder.load(root_idx_alloca)
        done_roots = builder.icmp_signed(">=", root_idx, num_roots)
        builder.cbranch(done_roots, next_frame, print_root)

        # Print root
        builder.position_at_end(print_root)
        root_slot = builder.gep(roots_ptr, [root_idx], inbounds=True)
        root_val = builder.load(root_slot)
        builder.call(printf, [root_ptr_fmt, root_idx, root_val])
        builder.branch(next_root)

        # Next root
        builder.position_at_end(next_root)
        new_idx = builder.add(root_idx, ir.Constant(self.i64, 1))
        builder.store(new_idx, root_idx_alloca)
        builder.branch(root_loop)

        # Next frame
        builder.position_at_end(next_frame)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, frame_ptr_alloca)
        new_frame_num = builder.add(frame_num, ir.Constant(self.i64, 1))
        builder.store(new_frame_num, frame_num_alloca)
        builder.branch(frame_loop)

        # Done
        builder.position_at_end(done)
        builder.ret_void()

    def implement_gc_dump_object(self):
        """Implement function to dump detailed info about a single object"""
        func = self.gc.gc_dump_object
        func.args[0].name = "ptr"

        entry = func.append_basic_block("entry")
        valid = func.append_basic_block("valid")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        ptr = func.args[0]

        # Printf for output
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Null check
        is_null = builder.icmp_unsigned("==", ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, valid)

        builder.position_at_end(valid)

        # Object format
        obj_fmt = "[GC:OBJ] ptr=%p size=%lld type=%d flags=0x%x\n"
        obj_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(obj_fmt) + 1), name=".gc_obj_fmt")
        obj_global.global_constant = True
        obj_global.linkage = 'private'
        obj_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(obj_fmt) + 1),
                                              bytearray(obj_fmt.encode('utf-8')) + bytearray([0]))
        obj_ptr_fmt = builder.bitcast(obj_global, self.i8_ptr)

        # Get header
        ptr_int = builder.ptrtoint(ptr, self.i64)
        header_int = builder.sub(ptr_int, ir.Constant(self.i64, self.gc.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.gc.header_type.as_pointer())

        # Load header fields (Phase 1: type_id and flags are now i64)
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)

        builder.call(printf, [obj_ptr_fmt, ptr, size, type_id, flags])
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def implement_gc_validate_heap(self):
        """Implement heap validation function - returns 0 if valid, error code otherwise"""
        func = self.gc.gc_validate_heap

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        check_obj = func.append_basic_block("check_obj")
        check_size = func.append_basic_block("check_size")
        check_type = func.append_basic_block("check_type")
        next_obj = func.append_basic_block("next_obj")
        invalid_size = func.append_basic_block("invalid_size")
        invalid_type = func.append_basic_block("invalid_type")
        valid = func.append_basic_block("valid")

        builder = ir.IRBuilder(entry)

        # Get head of allocation list
        head = builder.load(self.gc.gc_alloc_list)
        curr_alloca = builder.alloca(self.i8_ptr, name="curr")
        builder.store(head, curr_alloca)
        builder.branch(loop)

        # Loop through allocation list
        builder.position_at_end(loop)
        curr = builder.load(curr_alloca)
        is_null = builder.icmp_unsigned("==", curr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, valid, check_obj)

        # Check object
        builder.position_at_end(check_obj)
        node = builder.bitcast(curr, self.gc.alloc_node_type.as_pointer())

        # Phase 7: Get handle and dereference to get data pointer
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc.gc_handle_deref, [obj_handle])

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.gc.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.gc.header_type.as_pointer())

        # Load header fields
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)

        builder.branch(check_size)

        # Check size >= HEADER_SIZE
        builder.position_at_end(check_size)
        header_size_const = ir.Constant(self.i64, self.gc.HEADER_SIZE)
        size_valid = builder.icmp_unsigned(">=", size, header_size_const)
        builder.cbranch(size_valid, check_type, invalid_size)

        # Check type_id < MAX_TYPES (Phase 1: type_id is now i64)
        builder.position_at_end(check_type)
        max_types = ir.Constant(self.i64, self.gc.MAX_TYPES)
        type_valid = builder.icmp_unsigned("<", type_id, max_types)
        builder.cbranch(type_valid, next_obj, invalid_type)

        # Get next object
        builder.position_at_end(next_obj)
        next_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_ptr = builder.load(next_ptr_ptr)
        builder.store(next_ptr, curr_alloca)
        builder.branch(loop)

        # Invalid size
        builder.position_at_end(invalid_size)
        builder.ret(ir.Constant(self.i64, 1))  # Error code 1

        # Invalid type
        builder.position_at_end(invalid_type)
        builder.ret(ir.Constant(self.i64, 2))  # Error code 2

        # All valid
        builder.position_at_end(valid)
        builder.ret(ir.Constant(self.i64, 0))  # Success

    def implement_gc_set_trace_level(self):
        """Implement function to set trace verbosity level"""
        func = self.gc.gc_set_trace_level
        func.args[0].name = "level"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        level = func.args[0]
        builder.store(level, self.gc.gc_trace_level)
        builder.ret_void()

    def implement_gc_fragmentation_report(self):
        """Analyze and print heap fragmentation statistics.

        Walks the allocation list and computes:
        - Total allocated objects and bytes
        - Size distribution (small/medium/large objects)
        - Free list length (available handle slots)
        - Retired list length (pending reclamation)
        """
        func = self.gc.gc_fragmentation_report

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        process_obj = func.append_basic_block("process_obj")
        classify_size = func.append_basic_block("classify_size")
        is_medium = func.append_basic_block("is_medium")
        is_large = func.append_basic_block("is_large")
        next_obj = func.append_basic_block("next_obj")
        count_free = func.append_basic_block("count_free")
        free_loop = func.append_basic_block("free_loop")
        free_next = func.append_basic_block("free_next")
        count_retired = func.append_basic_block("count_retired")
        retired_loop = func.append_basic_block("retired_loop")
        retired_next = func.append_basic_block("retired_next")
        print_report = func.append_basic_block("print_report")

        builder = ir.IRBuilder(entry)

        # Printf for output
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Counters
        total_objects = builder.alloca(self.i64, name="total_objects")
        total_bytes = builder.alloca(self.i64, name="total_bytes")
        small_count = builder.alloca(self.i64, name="small_count")   # < 64 bytes
        medium_count = builder.alloca(self.i64, name="medium_count") # 64-512 bytes
        large_count = builder.alloca(self.i64, name="large_count")   # > 512 bytes
        free_count = builder.alloca(self.i64, name="free_count")
        retired_count = builder.alloca(self.i64, name="retired_count")

        # Initialize counters
        builder.store(ir.Constant(self.i64, 0), total_objects)
        builder.store(ir.Constant(self.i64, 0), total_bytes)
        builder.store(ir.Constant(self.i64, 0), small_count)
        builder.store(ir.Constant(self.i64, 0), medium_count)
        builder.store(ir.Constant(self.i64, 0), large_count)
        builder.store(ir.Constant(self.i64, 0), free_count)
        builder.store(ir.Constant(self.i64, 0), retired_count)

        # Current pointer for iteration
        curr = builder.alloca(self.i8_ptr, name="curr")
        head = builder.load(self.gc.gc_alloc_list)
        builder.store(head, curr)
        builder.branch(loop)

        # Loop through allocation list
        builder.position_at_end(loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, count_free, process_obj)

        # Process object
        builder.position_at_end(process_obj)
        node = builder.bitcast(curr_val, self.gc.alloc_node_type.as_pointer())
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc.gc_handle_deref, [obj_handle])

        # Get size from header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.gc.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.gc.header_type.as_pointer())
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        obj_size = builder.load(size_ptr)

        # Increment counters
        old_total = builder.load(total_objects)
        builder.store(builder.add(old_total, ir.Constant(self.i64, 1)), total_objects)
        old_bytes = builder.load(total_bytes)
        builder.store(builder.add(old_bytes, obj_size), total_bytes)

        builder.branch(classify_size)

        # Classify by size
        builder.position_at_end(classify_size)
        is_small = builder.icmp_unsigned("<", obj_size, ir.Constant(self.i64, 64))
        builder.cbranch(is_small, next_obj, is_medium)

        # Check medium (increment small count happened inline above)
        builder.position_at_end(is_medium)
        old_small = builder.load(small_count)
        # Actually we need to go back and fix this - small was already branched
        # Let me restructure this more carefully
        is_med = builder.icmp_unsigned("<", obj_size, ir.Constant(self.i64, 512))
        builder.cbranch(is_med, next_obj, is_large)

        # Large object
        builder.position_at_end(is_large)
        old_large = builder.load(large_count)
        builder.store(builder.add(old_large, ir.Constant(self.i64, 1)), large_count)
        builder.branch(next_obj)

        # Move to next object
        builder.position_at_end(next_obj)
        # Reload curr and get size for proper classification
        curr_val2 = builder.load(curr)
        node2 = builder.bitcast(curr_val2, self.gc.alloc_node_type.as_pointer())
        handle_ptr2 = builder.gep(node2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle2 = builder.load(handle_ptr2)
        data_ptr2 = builder.call(self.gc.gc_handle_deref, [obj_handle2])
        data_int2 = builder.ptrtoint(data_ptr2, self.i64)
        header_int2 = builder.sub(data_int2, ir.Constant(self.i64, self.gc.HEADER_SIZE))
        header2 = builder.inttoptr(header_int2, self.gc.header_type.as_pointer())
        size_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        obj_size2 = builder.load(size_ptr2)

        # Proper size classification
        is_small2 = builder.icmp_unsigned("<", obj_size2, ir.Constant(self.i64, 64))
        is_med2 = builder.icmp_unsigned("<", obj_size2, ir.Constant(self.i64, 512))

        # Increment appropriate counter using select
        old_s = builder.load(small_count)
        old_m = builder.load(medium_count)
        old_l = builder.load(large_count)

        new_s = builder.select(is_small2, builder.add(old_s, ir.Constant(self.i64, 1)), old_s)
        builder.store(new_s, small_count)

        not_small = builder.icmp_unsigned(">=", obj_size2, ir.Constant(self.i64, 64))
        incr_med = builder.and_(not_small, is_med2)
        new_m = builder.select(incr_med, builder.add(old_m, ir.Constant(self.i64, 1)), old_m)
        builder.store(new_m, medium_count)

        # Large already incremented in is_large block, so just advance
        next_ptr = builder.gep(node2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_node = builder.load(next_ptr)
        builder.store(next_node, curr)
        builder.branch(loop)

        # Count free list
        builder.position_at_end(count_free)
        free_head = builder.load(self.gc.gc_handle_free_list)
        free_curr = builder.alloca(self.i64, name="free_curr")
        builder.store(free_head, free_curr)
        builder.branch(free_loop)

        builder.position_at_end(free_loop)
        fc = builder.load(free_curr)
        fc_is_zero = builder.icmp_unsigned("==", fc, ir.Constant(self.i64, 0))
        builder.cbranch(fc_is_zero, count_retired, free_next)

        builder.position_at_end(free_next)
        old_fc = builder.load(free_count)
        builder.store(builder.add(old_fc, ir.Constant(self.i64, 1)), free_count)
        # Get next free from table
        table = builder.load(self.gc.gc_handle_table)
        fc_val = builder.load(free_curr)
        slot_ptr = builder.gep(table, [fc_val])
        next_free_ptr = builder.load(slot_ptr)
        next_free = builder.ptrtoint(next_free_ptr, self.i64)
        builder.store(next_free, free_curr)
        builder.branch(free_loop)

        # Count retired list
        builder.position_at_end(count_retired)
        ret_head = builder.load(self.gc.gc_handle_retired_list)
        ret_curr = builder.alloca(self.i64, name="ret_curr")
        builder.store(ret_head, ret_curr)
        builder.branch(retired_loop)

        builder.position_at_end(retired_loop)
        rc = builder.load(ret_curr)
        rc_is_zero = builder.icmp_unsigned("==", rc, ir.Constant(self.i64, 0))
        builder.cbranch(rc_is_zero, print_report, retired_next)

        builder.position_at_end(retired_next)
        old_rc = builder.load(retired_count)
        builder.store(builder.add(old_rc, ir.Constant(self.i64, 1)), retired_count)
        table2 = builder.load(self.gc.gc_handle_table)
        rc_val = builder.load(ret_curr)
        slot_ptr2 = builder.gep(table2, [rc_val])
        next_ret_ptr = builder.load(slot_ptr2)
        next_ret = builder.ptrtoint(next_ret_ptr, self.i64)
        builder.store(next_ret, ret_curr)
        builder.branch(retired_loop)

        # Print report
        builder.position_at_end(print_report)

        # Header
        hdr_str = "[GC:FRAG] === Fragmentation Report ===\n"
        hdr_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(hdr_str) + 1), name=".frag_hdr")
        hdr_global.global_constant = True
        hdr_global.linkage = 'private'
        hdr_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(hdr_str) + 1),
                                              bytearray(hdr_str.encode('utf-8')) + bytearray([0]))
        hdr_ptr = builder.bitcast(hdr_global, self.i8_ptr)
        builder.call(printf, [hdr_ptr])

        # Object stats
        obj_fmt = "[GC:FRAG] Objects: %lld total, %lld bytes\n"
        obj_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(obj_fmt) + 1), name=".frag_obj")
        obj_global.global_constant = True
        obj_global.linkage = 'private'
        obj_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(obj_fmt) + 1),
                                              bytearray(obj_fmt.encode('utf-8')) + bytearray([0]))
        obj_ptr = builder.bitcast(obj_global, self.i8_ptr)
        builder.call(printf, [obj_ptr, builder.load(total_objects), builder.load(total_bytes)])

        # Size distribution
        size_fmt = "[GC:FRAG] Size distribution: small=%lld, medium=%lld, large=%lld\n"
        size_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(size_fmt) + 1), name=".frag_size")
        size_global.global_constant = True
        size_global.linkage = 'private'
        size_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(size_fmt) + 1),
                                               bytearray(size_fmt.encode('utf-8')) + bytearray([0]))
        size_ptr = builder.bitcast(size_global, self.i8_ptr)
        builder.call(printf, [size_ptr, builder.load(small_count), builder.load(medium_count), builder.load(large_count)])

        # Handle stats
        hdl_fmt = "[GC:FRAG] Handles: free=%lld, retired=%lld\n"
        hdl_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(hdl_fmt) + 1), name=".frag_hdl")
        hdl_global.global_constant = True
        hdl_global.linkage = 'private'
        hdl_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(hdl_fmt) + 1),
                                              bytearray(hdl_fmt.encode('utf-8')) + bytearray([0]))
        hdl_ptr = builder.bitcast(hdl_global, self.i8_ptr)
        builder.call(printf, [hdl_ptr, builder.load(free_count), builder.load(retired_count)])

        builder.ret_void()

    def implement_gc_dump_handle_table(self):
        """Print handle table state including allocated, free, and retired handles.

        Shows:
        - Table size and next handle index
        - First N allocated handles with their object pointers
        - Free list chain
        - Retired list chain
        """
        func = self.gc.gc_dump_handle_table

        entry = func.append_basic_block("entry")
        dump_allocated = func.append_basic_block("dump_allocated")
        alloc_loop = func.append_basic_block("alloc_loop")
        check_slot = func.append_basic_block("check_slot")
        print_slot = func.append_basic_block("print_slot")
        next_slot = func.append_basic_block("next_slot")
        dump_free = func.append_basic_block("dump_free")
        free_loop = func.append_basic_block("free_loop")
        print_free = func.append_basic_block("print_free")
        free_next = func.append_basic_block("free_next")
        dump_retired = func.append_basic_block("dump_retired")
        retired_loop = func.append_basic_block("retired_loop")
        print_retired = func.append_basic_block("print_retired")
        retired_next = func.append_basic_block("retired_next")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Header
        hdr_str = "[GC:HANDLES] === Handle Table Dump ===\n"
        hdr_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(hdr_str) + 1), name=".hdl_hdr")
        hdr_global.global_constant = True
        hdr_global.linkage = 'private'
        hdr_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(hdr_str) + 1),
                                              bytearray(hdr_str.encode('utf-8')) + bytearray([0]))
        hdr_ptr = builder.bitcast(hdr_global, self.i8_ptr)
        builder.call(printf, [hdr_ptr])

        # Table info
        info_fmt = "[GC:HANDLES] Table size: %lld, next_handle: %lld\n"
        info_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(info_fmt) + 1), name=".hdl_info")
        info_global.global_constant = True
        info_global.linkage = 'private'
        info_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(info_fmt) + 1),
                                               bytearray(info_fmt.encode('utf-8')) + bytearray([0]))
        info_ptr = builder.bitcast(info_global, self.i8_ptr)
        table_size = builder.load(self.gc.gc_handle_table_size)
        next_handle = builder.load(self.gc.gc_next_handle)
        builder.call(printf, [info_ptr, table_size, next_handle])

        builder.branch(dump_allocated)

        # Dump first 10 allocated handles
        builder.position_at_end(dump_allocated)
        alloc_hdr = "[GC:HANDLES] Allocated (first 10):\n"
        alloc_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(alloc_hdr) + 1), name=".hdl_alloc")
        alloc_global.global_constant = True
        alloc_global.linkage = 'private'
        alloc_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(alloc_hdr) + 1),
                                                bytearray(alloc_hdr.encode('utf-8')) + bytearray([0]))
        alloc_ptr = builder.bitcast(alloc_global, self.i8_ptr)
        builder.call(printf, [alloc_ptr])

        idx = builder.alloca(self.i64, name="idx")
        printed = builder.alloca(self.i64, name="printed")
        builder.store(ir.Constant(self.i64, 1), idx)  # Start at 1 (0 is null handle)
        builder.store(ir.Constant(self.i64, 0), printed)
        builder.branch(alloc_loop)

        builder.position_at_end(alloc_loop)
        i = builder.load(idx)
        p = builder.load(printed)
        # Stop after 10 or when we reach next_handle
        done_alloc = builder.or_(
            builder.icmp_unsigned(">=", p, ir.Constant(self.i64, 10)),
            builder.icmp_unsigned(">=", i, next_handle)
        )
        builder.cbranch(done_alloc, dump_free, check_slot)

        builder.position_at_end(check_slot)
        table = builder.load(self.gc.gc_handle_table)
        i_val = builder.load(idx)
        slot_ptr = builder.gep(table, [i_val])
        slot_val = builder.load(slot_ptr)
        is_null = builder.icmp_unsigned("==", slot_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, next_slot, print_slot)

        builder.position_at_end(print_slot)
        slot_fmt = "[GC:HANDLES]   handle=%lld -> ptr=%p\n"
        slot_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(slot_fmt) + 1), name=".hdl_slot")
        slot_global.global_constant = True
        slot_global.linkage = 'private'
        slot_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(slot_fmt) + 1),
                                               bytearray(slot_fmt.encode('utf-8')) + bytearray([0]))
        slot_fmt_ptr = builder.bitcast(slot_global, self.i8_ptr)
        i_val2 = builder.load(idx)
        table2 = builder.load(self.gc.gc_handle_table)
        slot_ptr2 = builder.gep(table2, [i_val2])
        slot_val2 = builder.load(slot_ptr2)
        builder.call(printf, [slot_fmt_ptr, i_val2, slot_val2])
        old_p = builder.load(printed)
        builder.store(builder.add(old_p, ir.Constant(self.i64, 1)), printed)
        builder.branch(next_slot)

        builder.position_at_end(next_slot)
        old_i = builder.load(idx)
        builder.store(builder.add(old_i, ir.Constant(self.i64, 1)), idx)
        builder.branch(alloc_loop)

        # Dump free list
        builder.position_at_end(dump_free)
        free_hdr = "[GC:HANDLES] Free list: "
        free_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(free_hdr) + 1), name=".hdl_free")
        free_global.global_constant = True
        free_global.linkage = 'private'
        free_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(free_hdr) + 1),
                                               bytearray(free_hdr.encode('utf-8')) + bytearray([0]))
        free_ptr = builder.bitcast(free_global, self.i8_ptr)
        builder.call(printf, [free_ptr])

        free_curr = builder.alloca(self.i64, name="free_curr")
        free_head = builder.load(self.gc.gc_handle_free_list)
        builder.store(free_head, free_curr)
        builder.branch(free_loop)

        builder.position_at_end(free_loop)
        fc = builder.load(free_curr)
        fc_zero = builder.icmp_unsigned("==", fc, ir.Constant(self.i64, 0))
        builder.cbranch(fc_zero, dump_retired, print_free)

        builder.position_at_end(print_free)
        free_fmt = "%lld -> "
        free_fmt_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(free_fmt) + 1), name=".hdl_ff")
        free_fmt_global.global_constant = True
        free_fmt_global.linkage = 'private'
        free_fmt_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(free_fmt) + 1),
                                                   bytearray(free_fmt.encode('utf-8')) + bytearray([0]))
        ff_ptr = builder.bitcast(free_fmt_global, self.i8_ptr)
        fc_val = builder.load(free_curr)
        builder.call(printf, [ff_ptr, fc_val])
        builder.branch(free_next)

        builder.position_at_end(free_next)
        table3 = builder.load(self.gc.gc_handle_table)
        fc_val2 = builder.load(free_curr)
        slot_ptr3 = builder.gep(table3, [fc_val2])
        next_ptr = builder.load(slot_ptr3)
        next_val = builder.ptrtoint(next_ptr, self.i64)
        builder.store(next_val, free_curr)
        builder.branch(free_loop)

        # Dump retired list
        builder.position_at_end(dump_retired)
        ret_hdr = "nil\n[GC:HANDLES] Retired list: "
        ret_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(ret_hdr) + 1), name=".hdl_ret")
        ret_global.global_constant = True
        ret_global.linkage = 'private'
        ret_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(ret_hdr) + 1),
                                              bytearray(ret_hdr.encode('utf-8')) + bytearray([0]))
        ret_ptr = builder.bitcast(ret_global, self.i8_ptr)
        builder.call(printf, [ret_ptr])

        ret_curr = builder.alloca(self.i64, name="ret_curr")
        ret_head = builder.load(self.gc.gc_handle_retired_list)
        builder.store(ret_head, ret_curr)
        builder.branch(retired_loop)

        builder.position_at_end(retired_loop)
        rc = builder.load(ret_curr)
        rc_zero = builder.icmp_unsigned("==", rc, ir.Constant(self.i64, 0))
        builder.cbranch(rc_zero, done, print_retired)

        builder.position_at_end(print_retired)
        ret_fmt = "%lld -> "
        ret_fmt_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(ret_fmt) + 1), name=".hdl_rf")
        ret_fmt_global.global_constant = True
        ret_fmt_global.linkage = 'private'
        ret_fmt_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(ret_fmt) + 1),
                                                  bytearray(ret_fmt.encode('utf-8')) + bytearray([0]))
        rf_ptr = builder.bitcast(ret_fmt_global, self.i8_ptr)
        rc_val = builder.load(ret_curr)
        builder.call(printf, [rf_ptr, rc_val])
        builder.branch(retired_next)

        builder.position_at_end(retired_next)
        table4 = builder.load(self.gc.gc_handle_table)
        rc_val2 = builder.load(ret_curr)
        slot_ptr4 = builder.gep(table4, [rc_val2])
        next_ptr2 = builder.load(slot_ptr4)
        next_val2 = builder.ptrtoint(next_ptr2, self.i64)
        builder.store(next_val2, ret_curr)
        builder.branch(retired_loop)

        builder.position_at_end(done)
        end_fmt = "nil\n"
        end_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(end_fmt) + 1), name=".hdl_end")
        end_global.global_constant = True
        end_global.linkage = 'private'
        end_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(end_fmt) + 1),
                                              bytearray(end_fmt.encode('utf-8')) + bytearray([0]))
        end_ptr = builder.bitcast(end_global, self.i8_ptr)
        builder.call(printf, [end_ptr])
        builder.ret_void()

    def implement_gc_dump_shadow_stacks(self):
        """Print all shadow stack frames and their root handles.

        Walks the shadow stack from top to bottom, printing each frame's
        handle slots and their dereferenced pointers.
        """
        func = self.gc.gc_dump_shadow_stacks

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        print_frame = func.append_basic_block("print_frame")
        root_loop = func.append_basic_block("root_loop")
        print_root = func.append_basic_block("print_root")
        next_root = func.append_basic_block("next_root")
        next_frame = func.append_basic_block("next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Header
        hdr_str = "[GC:SHADOW] === Shadow Stack Dump ===\n"
        hdr_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(hdr_str) + 1), name=".shadow_hdr")
        hdr_global.global_constant = True
        hdr_global.linkage = 'private'
        hdr_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(hdr_str) + 1),
                                              bytearray(hdr_str.encode('utf-8')) + bytearray([0]))
        hdr_ptr = builder.bitcast(hdr_global, self.i8_ptr)
        builder.call(printf, [hdr_ptr])

        # Print frame depth
        depth_fmt = "[GC:SHADOW] Frame depth: %lld\n"
        depth_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(depth_fmt) + 1), name=".shadow_depth")
        depth_global.global_constant = True
        depth_global.linkage = 'private'
        depth_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(depth_fmt) + 1),
                                                bytearray(depth_fmt.encode('utf-8')) + bytearray([0]))
        depth_ptr = builder.bitcast(depth_global, self.i8_ptr)
        frame_depth = builder.load(self.gc.gc_frame_depth)
        builder.call(printf, [depth_ptr, frame_depth])

        # Current frame pointer and frame number
        curr_frame = builder.alloca(self.i8_ptr, name="curr_frame")
        frame_num = builder.alloca(self.i64, name="frame_num")
        top = builder.load(self.gc.gc_frame_top)
        builder.store(top, curr_frame)
        builder.store(ir.Constant(self.i64, 0), frame_num)
        builder.branch(frame_loop)

        # Frame loop
        builder.position_at_end(frame_loop)
        frame_val = builder.load(curr_frame)
        is_null = builder.icmp_unsigned("==", frame_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, print_frame)

        # Print frame header
        builder.position_at_end(print_frame)
        frame_fmt = "[GC:SHADOW] Frame %lld: %lld roots\n"
        frame_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(frame_fmt) + 1), name=".shadow_frame")
        frame_global.global_constant = True
        frame_global.linkage = 'private'
        frame_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(frame_fmt) + 1),
                                                bytearray(frame_fmt.encode('utf-8')) + bytearray([0]))
        frame_fmt_ptr = builder.bitcast(frame_global, self.i8_ptr)

        frame_ptr = builder.load(curr_frame)
        frame = builder.bitcast(frame_ptr, self.gc.gc_frame_type.as_pointer())
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)
        fn = builder.load(frame_num)
        builder.call(printf, [frame_fmt_ptr, fn, num_roots])

        # Get handle slots
        slots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        slots = builder.load(slots_ptr_ptr)

        # Root index
        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)
        builder.branch(root_loop)

        # Root loop
        builder.position_at_end(root_loop)
        ri = builder.load(root_idx)
        # Reload num_roots for comparison
        frame_ptr2 = builder.load(curr_frame)
        frame2 = builder.bitcast(frame_ptr2, self.gc.gc_frame_type.as_pointer())
        num_roots_ptr2 = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots2 = builder.load(num_roots_ptr2)
        done_roots = builder.icmp_unsigned(">=", ri, num_roots2)
        builder.cbranch(done_roots, next_frame, print_root)

        # Print root
        builder.position_at_end(print_root)
        root_fmt = "[GC:SHADOW]   [%lld] handle=%lld -> ptr=%p\n"
        root_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(root_fmt) + 1), name=".shadow_root")
        root_global.global_constant = True
        root_global.linkage = 'private'
        root_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(root_fmt) + 1),
                                               bytearray(root_fmt.encode('utf-8')) + bytearray([0]))
        root_fmt_ptr = builder.bitcast(root_global, self.i8_ptr)

        ri_val = builder.load(root_idx)
        # Reload slots
        frame_ptr3 = builder.load(curr_frame)
        frame3 = builder.bitcast(frame_ptr3, self.gc.gc_frame_type.as_pointer())
        slots_ptr_ptr2 = builder.gep(frame3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        slots2 = builder.load(slots_ptr_ptr2)
        slot_ptr = builder.gep(slots2, [ri_val], inbounds=True)
        handle = builder.load(slot_ptr)
        ptr = builder.call(self.gc.gc_handle_deref, [handle])
        builder.call(printf, [root_fmt_ptr, ri_val, handle, ptr])
        builder.branch(next_root)

        # Next root
        builder.position_at_end(next_root)
        old_ri = builder.load(root_idx)
        builder.store(builder.add(old_ri, ir.Constant(self.i64, 1)), root_idx)
        builder.branch(root_loop)

        # Next frame
        builder.position_at_end(next_frame)
        frame_ptr4 = builder.load(curr_frame)
        frame4 = builder.bitcast(frame_ptr4, self.gc.gc_frame_type.as_pointer())
        parent_ptr = builder.gep(frame4, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, curr_frame)
        old_fn = builder.load(frame_num)
        builder.store(builder.add(old_fn, ir.Constant(self.i64, 1)), frame_num)
        builder.branch(frame_loop)

        # Done
        builder.position_at_end(done)
        end_fmt = "[GC:SHADOW] === End Shadow Stack ===\n"
        end_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(end_fmt) + 1), name=".shadow_end")
        end_global.global_constant = True
        end_global.linkage = 'private'
        end_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(end_fmt) + 1),
                                              bytearray(end_fmt.encode('utf-8')) + bytearray([0]))
        end_ptr = builder.bitcast(end_global, self.i8_ptr)
        builder.call(printf, [end_ptr])
        builder.ret_void()
