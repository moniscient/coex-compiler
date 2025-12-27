"""
Coex Garbage Collector - Shadow Stack Implementation

This GC uses a manual shadow stack for cross-platform root tracking,
avoiding platform-specific stack scanning that caused issues on Linux.

Design:
- Each function that contains heap pointers pushes a GCFrame onto a linked list
- The frame contains pointers to root slots (allocas) in that function
- During GC, we traverse the frame chain to find all roots
- Mark-and-sweep collection: mark live objects, sweep unmarked

This approach is portable because it doesn't depend on machine stack layout.
"""

from llvmlite import ir
from typing import Dict, List as PyList, Tuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from codegen import CodeGenerator


class GarbageCollector:
    """Generates LLVM IR for garbage collection runtime with shadow stack"""

    # Constants (Phase 1: Updated to 32-byte header)
    HEADER_SIZE = 32         # 4 x i64: size, type_id, flags, forward
    MIN_BLOCK_SIZE = 40      # Minimum block: header(32) + alignment padding
    MAX_TYPES = 256          # Maximum number of registered types
    GC_THRESHOLD = 10000     # Trigger GC after this many allocations
    INITIAL_HEAP_SIZE = 1024 * 1024 * 1024  # 1GB initial heap

    # Flag bits in header (stored in i64 flags field)
    FLAG_MARK_BIT = 0x01     # Bit 0: mark bit for GC
    FLAG_FORWARDED = 0x02    # Bit 1: object has been forwarded (compaction)
    FLAG_PINNED = 0x04       # Bit 2: pinned (not movable) - future use
    FLAG_FINALIZER = 0x08    # Bit 3: has finalizer - future use

    # Trace levels for debugging infrastructure (Phase 0)
    GC_TRACE_NONE = 0        # No tracing output
    GC_TRACE_PHASES = 1      # Collection phase boundaries
    GC_TRACE_OPS = 2         # Major operations (alloc, mark, sweep)
    GC_TRACE_DETAIL = 3      # Individual object operations
    GC_TRACE_ALL = 4         # Everything including pointer traversals

    # Built-in type IDs
    TYPE_UNKNOWN = 0
    TYPE_LIST = 1
    TYPE_STRING = 2
    TYPE_MAP = 3
    TYPE_MAP_ENTRY = 4
    TYPE_SET = 5
    TYPE_SET_ENTRY = 6
    TYPE_CHANNEL = 7
    TYPE_ARRAY = 8
    TYPE_LIST_TAIL = 9       # List tail buffer (element data)
    TYPE_PV_NODE = 10        # Persistent vector tree node
    TYPE_STRING_DATA = 11    # String character data buffer
    TYPE_CHANNEL_BUFFER = 12 # Channel data buffer
    TYPE_ARRAY_DATA = 13     # Array element data buffer
    TYPE_FIRST_USER = 14     # First ID for user-defined types

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
        self.i8_ptr_ptr = self.i8_ptr.as_pointer()
        self.i64_ptr = self.i64.as_pointer()
        self.void = ir.VoidType()
        self.i1 = ir.IntType(1)

        # GC-specific LLVM types
        self.header_type = None
        self.gc_frame_type = None

        # GC global variables
        self.gc_frame_top = None      # Top of shadow stack frame chain
        self.gc_alloc_list = None     # Linked list of all allocations
        self.gc_alloc_count = None    # Count allocations to trigger GC
        self.gc_enabled = None        # Whether GC is enabled

        # GC functions
        self.gc_init = None
        self.gc_alloc = None
        self.gc_collect = None
        self.gc_push_frame = None
        self.gc_pop_frame = None
        self.gc_set_root = None
        self.gc_mark_object = None
        self.gc_scan_roots = None
        self.gc_sweep = None

        # Dual-heap async GC functions
        self.gc_async = None
        self.gc_capture_snapshot = None
        self.gc_swap_heaps = None
        self.gc_thread_main = None
        self.gc_scan_cross_heap = None
        self.gc_mark_from_snapshot = None
        self.gc_sweep_heap = None
        self.gc_grow_heaps = None
        self.gc_wait_for_completion = None

        # Dual-heap types and globals
        self.heap_region_type = None
        self.root_snapshot_type = None
        self.gc_state_type = None
        self.gc_state = None
        self.gc_mutex = None
        self.gc_cond_start = None
        self.gc_cond_done = None
        self.gc_snapshot = None
        self.gc_thread_handle = None

        # Pthread functions
        self.pthread_create = None
        self.pthread_mutex_init = None
        self.pthread_mutex_lock = None
        self.pthread_mutex_unlock = None
        self.pthread_cond_init = None
        self.pthread_cond_wait = None
        self.pthread_cond_signal = None
        self.pthread_attr_init = None
        self.pthread_attr_setdetachstate = None

        # ============================================================
        # Phase 0: Debugging Infrastructure
        # ============================================================

        # GC stats type and global
        self.gc_stats_type = None
        self.gc_stats = None

        # Trace level global
        self.gc_trace_level = None

        # Frame depth tracking (for watermark in later phases)
        self.gc_frame_depth = None

        # Debug/trace functions
        self.gc_trace = None
        self.gc_dump_heap = None
        self.gc_dump_roots = None
        self.gc_dump_object = None
        self.gc_validate_heap = None
        self.gc_dump_stats = None
        self.gc_stats_alloc = None
        self.gc_stats_collect = None
        self.gc_set_trace_level = None

        # ============================================================
        # Phase 3: High Watermark Tracking
        # ============================================================

        # Watermark depth - GC triggers when frame depth returns to this level
        self.gc_watermark_depth = None

        # Flag indicating if a watermark is currently installed
        self.gc_watermark_installed = None

        # Function to install watermark at current depth
        self.gc_install_watermark = None

    def generate_gc_runtime(self):
        """Generate all GC runtime structures and functions"""
        self._create_types()
        self._create_globals()
        self._declare_functions()
        self._register_builtin_types()
        self._implement_gc_init()
        self._implement_gc_push_frame()
        self._implement_gc_pop_frame()
        self._implement_gc_set_root()
        self._implement_gc_alloc()
        self._implement_gc_mark_hamt()
        self._implement_gc_mark_object()
        self._implement_gc_scan_roots()
        self._implement_gc_sweep()
        self._implement_gc_collect()
        self._implement_gc_safepoint()
        self._add_nursery_stubs()  # Disabled nursery context stubs for compatibility
        # Dual-heap async GC implementations
        self._implement_gc_capture_snapshot()
        self._implement_gc_mark_from_snapshot()
        self._implement_gc_swap_heaps()
        self._implement_gc_scan_cross_heap()
        self._implement_gc_sweep_heap()
        self._implement_gc_thread_main()
        self._implement_gc_async()
        self._implement_gc_wait_for_completion()
        self._implement_gc_grow_heaps()
        # Phase 0: Debugging infrastructure
        self._implement_gc_trace()
        self._implement_gc_dump_stats()
        self._implement_gc_dump_heap()
        self._implement_gc_dump_roots()
        self._implement_gc_dump_object()
        self._implement_gc_validate_heap()
        self._implement_gc_set_trace_level()
        # Phase 3: High watermark tracking
        self._implement_gc_install_watermark()
        # Phase 5: Thread registry
        self._implement_gc_register_thread()
        self._implement_gc_unregister_thread()
        self._implement_gc_get_thread_entry()
        self._implement_gc_get_current_thread_entry()
        # Phase 6: Watermark mechanism enhancement
        self._implement_gc_install_watermarks()
        self._implement_gc_clear_watermarks()
        self._implement_gc_sync_thread_depth()
        # Phase 7: First trace pass
        self._implement_gc_scan_roots_watermark()
        self._implement_gc_first_trace()
        self._implement_gc_count_roots()

    def _create_types(self):
        """Create GC-related LLVM types"""
        # Object header (Phase 1): { i64 size, i64 type_id, i64 flags, i64 forward }
        # 32 bytes total, all i64 for cross-platform consistency
        # Placed immediately before user data
        self.header_type = ir.LiteralStructType([
            self.i64,  # 0: block size (including header)
            self.i64,  # 8: type_id (was i32, now i64)
            self.i64,  # 16: flags (mark, forward, pinned, finalizer bits)
            self.i64,  # 24: forward pointer (for compaction, 0 if not forwarded)
        ])

        # Allocation node: { i8* next, i8* data, i64 size }
        # Linked list of all allocations for sweep
        self.alloc_node_type = ir.LiteralStructType([
            self.i8_ptr,  # next allocation node
            self.i8_ptr,  # pointer to user data
            self.i64,     # size of allocation
        ])

        # GC Frame: { i8* parent, i64 num_roots, i8** roots }
        # Shadow stack frame for root tracking
        self.gc_frame_type = ir.LiteralStructType([
            self.i8_ptr,      # parent frame pointer
            self.i64,         # number of roots
            self.i8_ptr_ptr,  # pointer to roots array
        ])

        # ============================================================
        # Dual-heap async GC types
        # All use i64 for cross-platform consistency (no padding issues)
        # ============================================================

        # HeapRegion: { i8* alloc_list, i64 alloc_count, i64 region_id }
        # Represents one heap region (A or B)
        self.heap_region_type = ir.LiteralStructType([
            self.i8_ptr,  # alloc_list - head of allocation linked list
            self.i64,     # alloc_count - allocations in this region
            self.i64,     # region_id - 0 for heap A, 1 for heap B
        ])

        # RootSnapshot: { i8** roots, i64 count, i64 heap_to_collect }
        # Captures shadow stack state at swap time
        self.root_snapshot_type = ir.LiteralStructType([
            self.i8_ptr_ptr,  # roots - array of root pointer values
            self.i64,         # count - number of roots captured
            self.i64,         # heap_to_collect - 0 for A, 1 for B
        ])

        # GCState: { i64 active_heap, i64 gc_in_progress, i64 gc_complete,
        #            HeapRegion heap_a, HeapRegion heap_b }
        # Main state for dual-heap GC
        self.gc_state_type = ir.LiteralStructType([
            self.i64,              # active_heap - 0 for A, 1 for B
            self.i64,              # gc_in_progress - flag
            self.i64,              # gc_complete - flag
            self.heap_region_type, # heap_a (offset 24)
            self.heap_region_type, # heap_b (offset 48)
        ])

        # ============================================================
        # Phase 0: Debugging Infrastructure Types
        # ============================================================

        # GCStats: Statistics collection structure (all i64 for consistency)
        # Tracks allocation and collection metrics for debugging
        self.gc_stats_type = ir.LiteralStructType([
            # Allocation metrics (offsets 0-24)
            self.i64,    # 0: total_allocations
            self.i64,    # 8: total_bytes_allocated
            self.i64,    # 16: allocations_since_last_gc
            self.i64,    # 24: bytes_since_last_gc

            # Collection metrics (offsets 32-56)
            self.i64,    # 32: collections_completed
            self.i64,    # 40: objects_marked_last_cycle
            self.i64,    # 48: objects_swept_last_cycle
            self.i64,    # 56: bytes_reclaimed_last_cycle

            # Compaction metrics (offsets 64-80) - for future use
            self.i64,    # 64: compactions_completed
            self.i64,    # 72: objects_moved_last_compact
            self.i64,    # 80: bytes_moved_last_compact

            # Timing metrics in nanoseconds (offsets 88-128)
            self.i64,    # 88: last_watermark_install_ns
            self.i64,    # 96: last_first_trace_ns
            self.i64,    # 104: last_compact_ns
            self.i64,    # 112: last_second_trace_ns
            self.i64,    # 120: last_sweep_ns
            self.i64,    # 128: last_total_gc_ns

            # Threading metrics (offsets 136-144) - for future use
            self.i64,    # 136: total_block_events
            self.i64,    # 144: total_block_wait_ns
        ])

        # ============================================================
        # Phase 5: Thread Registry Types
        # ============================================================

        # ThreadEntry: Per-thread GC state for multi-threading support
        # Currently single-threaded, but this prepares for future threading
        # All fields are i64 for cross-platform consistency
        self.thread_entry_type = ir.LiteralStructType([
            self.i64,     # 0: thread_id - platform thread ID (0 for main thread in stub)
            self.i8_ptr,  # 8: shadow_stack_chain - pointer to this thread's gc_frame_top
            self.i64,     # 16: watermark - current watermark depth (0 if none)
            self.i64,     # 24: watermark_active - watermark is set and collection ongoing
            self.i64,     # 32: stack_depth - current shadow stack depth
            self.i64,     # 40: blocked - thread is blocked waiting for GC
            self.i8_ptr,  # 48: alloc_buffer - thread's allocation buffer (future use)
            self.i8_ptr,  # 56: next - next thread in registry linked list
        ])

    def _create_globals(self):
        """Create GC global variables"""
        # ============================================================
        # Phase 2: Shadow Stack Thread-Local Storage Preparation
        # ============================================================
        # The following globals are per-thread in a multi-threaded implementation:
        #   - gc_frame_top: Each thread has its own shadow stack
        #   - gc_frame_depth: Each thread tracks its own call depth
        #
        # For thread-local storage, these would be declared with __thread
        # in the generated C code, or use platform-specific TLS APIs.
        #
        # Current implementation: Single-threaded (globals work fine)
        # Future implementation: Replace with TLS for multi-threading
        # ============================================================

        # Top of shadow stack frame chain
        # THREAD-LOCAL in multi-threaded implementation
        self.gc_frame_top = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_frame_top")
        self.gc_frame_top.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_frame_top.linkage = 'internal'

        # Head of allocation list (for sweep)
        # SHARED - protected by gc_mutex in multi-threaded implementation
        self.gc_alloc_list = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_alloc_list")
        self.gc_alloc_list.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_alloc_list.linkage = 'internal'

        # Allocation counter
        # SHARED - use atomic increment in multi-threaded implementation
        self.gc_alloc_count = ir.GlobalVariable(self.module, self.i64, name="gc_alloc_count")
        self.gc_alloc_count.initializer = ir.Constant(self.i64, 0)
        self.gc_alloc_count.linkage = 'internal'

        # GC enabled flag (disabled during collection)
        # SHARED - use atomic access in multi-threaded implementation
        self.gc_enabled = ir.GlobalVariable(self.module, self.i1, name="gc_enabled")
        self.gc_enabled.initializer = ir.Constant(self.i1, 1)
        self.gc_enabled.linkage = 'internal'

        # ============================================================
        # Dual-heap async GC globals
        # ============================================================

        # GC state structure containing both heap regions
        # Initialize: active=0, in_progress=0, complete=1,
        #             heap_a={null,0,0}, heap_b={null,0,1}
        heap_a_init = ir.Constant(self.heap_region_type, [
            ir.Constant(self.i8_ptr, None),  # alloc_list = null
            ir.Constant(self.i64, 0),        # alloc_count = 0
            ir.Constant(self.i64, 0),        # region_id = 0 (heap A)
        ])
        heap_b_init = ir.Constant(self.heap_region_type, [
            ir.Constant(self.i8_ptr, None),  # alloc_list = null
            ir.Constant(self.i64, 0),        # alloc_count = 0
            ir.Constant(self.i64, 1),        # region_id = 1 (heap B)
        ])
        gc_state_init = ir.Constant(self.gc_state_type, [
            ir.Constant(self.i64, 0),        # active_heap = 0 (A)
            ir.Constant(self.i64, 0),        # gc_in_progress = 0
            ir.Constant(self.i64, 1),        # gc_complete = 1
            heap_a_init,
            heap_b_init,
        ])
        self.gc_state = ir.GlobalVariable(self.module, self.gc_state_type, name="gc_state")
        self.gc_state.initializer = gc_state_init
        self.gc_state.linkage = 'internal'

        # Pthread mutex for synchronization (opaque, allocated at runtime)
        self.gc_mutex = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_mutex")
        self.gc_mutex.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_mutex.linkage = 'internal'

        # Pthread condition variable for GC thread start signal
        self.gc_cond_start = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_cond_start")
        self.gc_cond_start.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_cond_start.linkage = 'internal'

        # Pthread condition variable for GC completion signal
        self.gc_cond_done = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_cond_done")
        self.gc_cond_done.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_cond_done.linkage = 'internal'

        # Current snapshot for GC thread to process
        self.gc_snapshot = ir.GlobalVariable(
            self.module, self.root_snapshot_type.as_pointer(), name="gc_snapshot")
        self.gc_snapshot.initializer = ir.Constant(self.root_snapshot_type.as_pointer(), None)
        self.gc_snapshot.linkage = 'internal'

        # GC thread handle (stored as i8* but really pthread_t)
        self.gc_thread_handle = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_thread_handle")
        self.gc_thread_handle.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_thread_handle.linkage = 'internal'

        # ============================================================
        # Phase 0: Debugging Infrastructure Globals
        # ============================================================

        # GC trace level (0=none, 1=phases, 2=ops, 3=detail, 4=all)
        self.gc_trace_level = ir.GlobalVariable(self.module, self.i64, name="gc_trace_level")
        self.gc_trace_level.initializer = ir.Constant(self.i64, self.GC_TRACE_NONE)
        self.gc_trace_level.linkage = 'internal'

        # GC frame depth for watermark tracking (Phase 0/2)
        # THREAD-LOCAL in multi-threaded implementation
        # Tracks current call stack depth for high watermark GC
        self.gc_frame_depth = ir.GlobalVariable(self.module, self.i64, name="gc_frame_depth")
        self.gc_frame_depth.initializer = ir.Constant(self.i64, 0)
        self.gc_frame_depth.linkage = 'internal'

        # GC statistics structure - initialize all fields to 0
        gc_stats_init = ir.Constant(self.gc_stats_type, [
            ir.Constant(self.i64, 0),  # total_allocations
            ir.Constant(self.i64, 0),  # total_bytes_allocated
            ir.Constant(self.i64, 0),  # allocations_since_last_gc
            ir.Constant(self.i64, 0),  # bytes_since_last_gc
            ir.Constant(self.i64, 0),  # collections_completed
            ir.Constant(self.i64, 0),  # objects_marked_last_cycle
            ir.Constant(self.i64, 0),  # objects_swept_last_cycle
            ir.Constant(self.i64, 0),  # bytes_reclaimed_last_cycle
            ir.Constant(self.i64, 0),  # compactions_completed
            ir.Constant(self.i64, 0),  # objects_moved_last_compact
            ir.Constant(self.i64, 0),  # bytes_moved_last_compact
            ir.Constant(self.i64, 0),  # last_watermark_install_ns
            ir.Constant(self.i64, 0),  # last_first_trace_ns
            ir.Constant(self.i64, 0),  # last_compact_ns
            ir.Constant(self.i64, 0),  # last_second_trace_ns
            ir.Constant(self.i64, 0),  # last_sweep_ns
            ir.Constant(self.i64, 0),  # last_total_gc_ns
            ir.Constant(self.i64, 0),  # total_block_events
            ir.Constant(self.i64, 0),  # total_block_wait_ns
        ])
        self.gc_stats = ir.GlobalVariable(self.module, self.gc_stats_type, name="gc_stats")
        self.gc_stats.initializer = gc_stats_init
        self.gc_stats.linkage = 'internal'

        # ============================================================
        # Phase 3: High Watermark Tracking Globals
        # ============================================================

        # Watermark depth - GC triggers when frame depth returns to this level
        # THREAD-LOCAL in multi-threaded implementation
        self.gc_watermark_depth = ir.GlobalVariable(self.module, self.i64, name="gc_watermark_depth")
        self.gc_watermark_depth.initializer = ir.Constant(self.i64, 0)
        self.gc_watermark_depth.linkage = 'internal'

        # Flag indicating if a watermark is currently installed
        # THREAD-LOCAL in multi-threaded implementation
        self.gc_watermark_installed = ir.GlobalVariable(self.module, self.i1, name="gc_watermark_installed")
        self.gc_watermark_installed.initializer = ir.Constant(self.i1, 0)
        self.gc_watermark_installed.linkage = 'internal'

        # ============================================================
        # Phase 4: Mark Bit Inversion
        # ============================================================
        # Instead of clearing mark bits during sweep, we invert the meaning.
        # gc_current_mark_value alternates between 1 and 0 each cycle.
        # An object is "marked" if its mark bit equals gc_current_mark_value.
        # This eliminates the need to clear marks during sweep.

        # Current mark value - objects with this mark bit value are live
        # Starts at 1 (matching birth-marking), flips after each GC cycle
        self.gc_current_mark_value = ir.GlobalVariable(self.module, self.i64, name="gc_current_mark_value")
        self.gc_current_mark_value.initializer = ir.Constant(self.i64, 1)
        self.gc_current_mark_value.linkage = 'internal'

        # ============================================================
        # Phase 5: Thread Registry Globals
        # ============================================================

        # Head of thread registry linked list
        # Points to first ThreadEntry (main thread in single-threaded mode)
        # In multi-threaded mode, new threads add entries to this list
        self.gc_thread_registry = ir.GlobalVariable(
            self.module, self.thread_entry_type.as_pointer(), name="gc_thread_registry")
        self.gc_thread_registry.initializer = ir.Constant(
            self.thread_entry_type.as_pointer(), None)
        self.gc_thread_registry.linkage = 'internal'

        # Count of registered threads (for debugging and iteration)
        self.gc_thread_count = ir.GlobalVariable(self.module, self.i64, name="gc_thread_count")
        self.gc_thread_count.initializer = ir.Constant(self.i64, 0)
        self.gc_thread_count.linkage = 'internal'

        # ============================================================
        # Phase 9: User Type Descriptor Tables
        # ============================================================
        # For each user-defined type, we need to know which field offsets
        # contain pointers so gc_mark_object can mark them recursively.
        #
        # gc_type_offsets_table[type_id] -> pointer to array of i64 offsets
        # Each offset array is terminated by -1 (0xFFFFFFFFFFFFFFFF)
        # Built-in types (< TYPE_FIRST_USER) have NULL entries.

        # Table of pointers to offset arrays (indexed by type_id)
        offsets_table_type = ir.ArrayType(self.i64_ptr, self.MAX_TYPES)
        null_ptr_array = [ir.Constant(self.i64_ptr, None)] * self.MAX_TYPES
        self.gc_type_offsets_table = ir.GlobalVariable(
            self.module, offsets_table_type, name="gc_type_offsets_table")
        self.gc_type_offsets_table.initializer = ir.Constant(offsets_table_type, null_ptr_array)
        self.gc_type_offsets_table.linkage = 'internal'

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

        # gc_push_frame(num_roots: i64, roots: i8**) -> i8*
        # Returns pointer to frame (for passing to pop_frame)
        gc_push_ty = ir.FunctionType(self.i8_ptr, [self.i64, self.i8_ptr_ptr])
        self.gc_push_frame = ir.Function(self.module, gc_push_ty, name="coex_gc_push_frame")

        # gc_pop_frame(frame: i8*) -> void
        gc_pop_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_pop_frame = ir.Function(self.module, gc_pop_ty, name="coex_gc_pop_frame")

        # gc_set_root(roots: i8**, index: i64, value: i8*) -> void
        # Update a root slot
        gc_set_root_ty = ir.FunctionType(self.void, [self.i8_ptr_ptr, self.i64, self.i8_ptr])
        self.gc_set_root = ir.Function(self.module, gc_set_root_ty, name="coex_gc_set_root")

        # gc_mark_object(ptr: i8*) -> void
        gc_mark_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_mark_object = ir.Function(self.module, gc_mark_ty, name="coex_gc_mark_object")

        # gc_scan_roots() -> void
        gc_scan_roots_ty = ir.FunctionType(self.void, [])
        self.gc_scan_roots = ir.Function(self.module, gc_scan_roots_ty, name="coex_gc_scan_roots")

        # gc_sweep() -> void
        gc_sweep_ty = ir.FunctionType(self.void, [])
        self.gc_sweep = ir.Function(self.module, gc_sweep_ty, name="coex_gc_sweep")

        # gc_safepoint() -> void
        # Check allocation threshold and trigger GC if needed
        # Safe to call at function entry (before any allocations in the function)
        gc_safepoint_ty = ir.FunctionType(self.void, [])
        self.gc_safepoint = ir.Function(self.module, gc_safepoint_ty, name="coex_gc_safepoint")

        # gc_mark_hamt(root: i8*, flags: i32) -> void
        # Recursively mark HAMT nodes/leaves (used by Map and Set marking)
        # flags: bit 0 = key is heap ptr, bit 1 = value is heap ptr
        gc_mark_hamt_ty = ir.FunctionType(self.void, [self.i8_ptr, self.i32])
        self.gc_mark_hamt = ir.Function(self.module, gc_mark_hamt_ty, name="coex_gc_mark_hamt")

        # ============================================================
        # Dual-heap async GC function declarations
        # ============================================================

        # gc_async() -> void
        # Trigger async collection (returns immediately)
        gc_async_ty = ir.FunctionType(self.void, [])
        self.gc_async = ir.Function(self.module, gc_async_ty, name="coex_gc_async")

        # gc_capture_snapshot() -> RootSnapshot*
        # Capture shadow stack roots into snapshot
        gc_capture_ty = ir.FunctionType(self.root_snapshot_type.as_pointer(), [])
        self.gc_capture_snapshot = ir.Function(self.module, gc_capture_ty, name="coex_gc_capture_snapshot")

        # gc_swap_heaps() -> void
        # Atomically swap active heap and signal GC thread
        gc_swap_ty = ir.FunctionType(self.void, [])
        self.gc_swap_heaps = ir.Function(self.module, gc_swap_ty, name="coex_gc_swap_heaps")

        # gc_thread_main(arg: i8*) -> i8*
        # GC thread entry point (pthread signature)
        gc_thread_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
        self.gc_thread_main = ir.Function(self.module, gc_thread_ty, name="coex_gc_thread_main")

        # gc_scan_cross_heap(source_heap: i64, target_heap: i64) -> void
        # Scan source heap for pointers into target heap
        gc_scan_cross_ty = ir.FunctionType(self.void, [self.i64, self.i64])
        self.gc_scan_cross_heap = ir.Function(self.module, gc_scan_cross_ty, name="coex_gc_scan_cross_heap")

        # gc_mark_from_snapshot(snapshot: RootSnapshot*) -> void
        # Mark phase using captured snapshot roots
        gc_mark_snap_ty = ir.FunctionType(self.void, [self.root_snapshot_type.as_pointer()])
        self.gc_mark_from_snapshot = ir.Function(self.module, gc_mark_snap_ty, name="coex_gc_mark_from_snapshot")

        # gc_sweep_heap(heap_idx: i64) -> void
        # Sweep specific heap region
        gc_sweep_heap_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_sweep_heap = ir.Function(self.module, gc_sweep_heap_ty, name="coex_gc_sweep_heap")

        # gc_grow_heaps() -> void
        # Double both heap sizes on OOM
        gc_grow_ty = ir.FunctionType(self.void, [])
        self.gc_grow_heaps = ir.Function(self.module, gc_grow_ty, name="coex_gc_grow_heaps")

        # gc_wait_for_completion() -> void
        # Wait for current GC cycle to complete
        gc_wait_ty = ir.FunctionType(self.void, [])
        self.gc_wait_for_completion = ir.Function(self.module, gc_wait_ty, name="coex_gc_wait_for_completion")

        # ============================================================
        # Pthread function declarations (external)
        # ============================================================

        # pthread_create(thread*, attr*, start_routine, arg) -> int
        pthread_create_ty = ir.FunctionType(self.i32, [
            self.i8_ptr,   # pthread_t* (thread handle pointer)
            self.i8_ptr,   # pthread_attr_t* (attributes, can be null)
            self.i8_ptr,   # void* (*start_routine)(void*)
            self.i8_ptr    # void* arg
        ])
        self.pthread_create = ir.Function(self.module, pthread_create_ty, name="pthread_create")

        # pthread_mutex_init(mutex*, attr*) -> int
        pthread_mutex_init_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr])
        self.pthread_mutex_init = ir.Function(self.module, pthread_mutex_init_ty, name="pthread_mutex_init")

        # pthread_mutex_lock(mutex*) -> int
        pthread_mutex_lock_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        self.pthread_mutex_lock = ir.Function(self.module, pthread_mutex_lock_ty, name="pthread_mutex_lock")

        # pthread_mutex_unlock(mutex*) -> int
        pthread_mutex_unlock_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        self.pthread_mutex_unlock = ir.Function(self.module, pthread_mutex_unlock_ty, name="pthread_mutex_unlock")

        # pthread_cond_init(cond*, attr*) -> int
        pthread_cond_init_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr])
        self.pthread_cond_init = ir.Function(self.module, pthread_cond_init_ty, name="pthread_cond_init")

        # pthread_cond_wait(cond*, mutex*) -> int
        pthread_cond_wait_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr])
        self.pthread_cond_wait = ir.Function(self.module, pthread_cond_wait_ty, name="pthread_cond_wait")

        # pthread_cond_signal(cond*) -> int
        pthread_cond_signal_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        self.pthread_cond_signal = ir.Function(self.module, pthread_cond_signal_ty, name="pthread_cond_signal")

        # pthread_attr_init(attr*) -> int
        pthread_attr_init_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        self.pthread_attr_init = ir.Function(self.module, pthread_attr_init_ty, name="pthread_attr_init")

        # pthread_attr_setdetachstate(attr*, detachstate) -> int
        pthread_attr_setdetach_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i32])
        self.pthread_attr_setdetachstate = ir.Function(self.module, pthread_attr_setdetach_ty, name="pthread_attr_setdetachstate")

        # ============================================================
        # Phase 0: Debugging Infrastructure Function Declarations
        # ============================================================

        # gc_trace(level: i64, msg_ptr: i8*) -> void
        # Trace output based on current trace level
        gc_trace_ty = ir.FunctionType(self.void, [self.i64, self.i8_ptr])
        self.gc_trace = ir.Function(self.module, gc_trace_ty, name="coex_gc_trace")

        # gc_dump_heap() -> void
        # Print all live objects with type, size, mark status
        gc_dump_heap_ty = ir.FunctionType(self.void, [])
        self.gc_dump_heap = ir.Function(self.module, gc_dump_heap_ty, name="coex_gc_dump_heap")

        # gc_dump_roots() -> void
        # Print all roots from shadow stack
        gc_dump_roots_ty = ir.FunctionType(self.void, [])
        self.gc_dump_roots = ir.Function(self.module, gc_dump_roots_ty, name="coex_gc_dump_roots")

        # gc_dump_object(ptr: i8*) -> void
        # Detailed dump of single object and its references
        gc_dump_object_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_dump_object = ir.Function(self.module, gc_dump_object_ty, name="coex_gc_dump_object")

        # gc_validate_heap() -> i64
        # Check invariants - returns 0 if valid, error code otherwise
        gc_validate_heap_ty = ir.FunctionType(self.i64, [])
        self.gc_validate_heap = ir.Function(self.module, gc_validate_heap_ty, name="coex_gc_validate_heap")

        # gc_dump_stats() -> void
        # Print current GC statistics
        gc_dump_stats_ty = ir.FunctionType(self.void, [])
        self.gc_dump_stats = ir.Function(self.module, gc_dump_stats_ty, name="coex_gc_dump_stats")

        # gc_set_trace_level(level: i64) -> void
        # Set trace verbosity level
        gc_set_trace_level_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_set_trace_level = ir.Function(self.module, gc_set_trace_level_ty, name="coex_gc_set_trace_level")

        # ============================================================
        # Phase 3: High Watermark Tracking Function Declarations
        # ============================================================

        # gc_install_watermark() -> void
        # Install watermark at current frame depth - GC triggers when we return to this depth
        gc_install_watermark_ty = ir.FunctionType(self.void, [])
        self.gc_install_watermark = ir.Function(self.module, gc_install_watermark_ty, name="coex_gc_install_watermark")

        # ============================================================
        # Phase 5: Thread Registry Function Declarations
        # ============================================================

        # gc_register_thread(thread_id: i64) -> i8* (pointer to ThreadEntry)
        # Register a thread with the GC system
        gc_register_thread_ty = ir.FunctionType(self.thread_entry_type.as_pointer(), [self.i64])
        self.gc_register_thread = ir.Function(self.module, gc_register_thread_ty, name="coex_gc_register_thread")

        # gc_unregister_thread(thread_id: i64) -> void
        # Unregister a thread from the GC system
        gc_unregister_thread_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_unregister_thread = ir.Function(self.module, gc_unregister_thread_ty, name="coex_gc_unregister_thread")

        # gc_get_thread_entry(thread_id: i64) -> i8* (pointer to ThreadEntry or null)
        # Get the ThreadEntry for a given thread ID
        gc_get_thread_entry_ty = ir.FunctionType(self.thread_entry_type.as_pointer(), [self.i64])
        self.gc_get_thread_entry = ir.Function(self.module, gc_get_thread_entry_ty, name="coex_gc_get_thread_entry")

        # gc_get_current_thread_entry() -> i8* (pointer to ThreadEntry)
        # Get the ThreadEntry for the current (main) thread - convenience for single-threaded
        gc_get_current_thread_entry_ty = ir.FunctionType(self.thread_entry_type.as_pointer(), [])
        self.gc_get_current_thread_entry = ir.Function(self.module, gc_get_current_thread_entry_ty, name="coex_gc_get_current_thread_entry")

        # ============================================================
        # Phase 6: Watermark Mechanism Enhancement Declarations
        # ============================================================

        # gc_install_watermarks() -> void
        # Install watermarks on all registered threads at their current stack depth
        gc_install_watermarks_ty = ir.FunctionType(self.void, [])
        self.gc_install_watermarks = ir.Function(self.module, gc_install_watermarks_ty, name="coex_gc_install_watermarks")

        # gc_clear_watermarks() -> void
        # Clear watermarks on all registered threads
        gc_clear_watermarks_ty = ir.FunctionType(self.void, [])
        self.gc_clear_watermarks = ir.Function(self.module, gc_clear_watermarks_ty, name="coex_gc_clear_watermarks")

        # gc_sync_thread_depth() -> void
        # Sync global gc_frame_depth to current thread's ThreadEntry.stack_depth
        gc_sync_thread_depth_ty = ir.FunctionType(self.void, [])
        self.gc_sync_thread_depth = ir.Function(self.module, gc_sync_thread_depth_ty, name="coex_gc_sync_thread_depth")

        # ============================================================
        # Phase 7: First Trace Pass Function Declarations
        # ============================================================

        # gc_scan_roots_watermark() -> i64
        # Scan shadow stack up to watermark depth, marking all roots
        # Returns number of roots marked
        gc_scan_roots_watermark_ty = ir.FunctionType(self.i64, [])
        self.gc_scan_roots_watermark = ir.Function(self.module, gc_scan_roots_watermark_ty, name="coex_gc_scan_roots_watermark")

        # gc_first_trace() -> void
        # Orchestrate the first trace pass: enumerate roots and mark reachable objects
        gc_first_trace_ty = ir.FunctionType(self.void, [])
        self.gc_first_trace = ir.Function(self.module, gc_first_trace_ty, name="coex_gc_first_trace")

        # gc_count_roots() -> i64
        # Count total roots in shadow stack (for debugging/stats)
        gc_count_roots_ty = ir.FunctionType(self.i64, [])
        self.gc_count_roots = ir.Function(self.module, gc_count_roots_ty, name="coex_gc_count_roots")

    def _register_builtin_types(self):
        """Register built-in heap-allocated types"""
        self.type_info[self.TYPE_UNKNOWN] = {'size': 0, 'ref_offsets': []}
        self.type_info[self.TYPE_LIST] = {'size': 32, 'ref_offsets': [24]}
        self.type_descriptors['List'] = self.TYPE_LIST
        # String: { i8* owner, i64 offset, i64 len, i64 size } = 32 bytes
        # For slice views, owner points to the shared data buffer (traced via mark_string)
        self.type_info[self.TYPE_STRING] = {'size': 32, 'ref_offsets': [0]}
        self.type_descriptors['String'] = self.TYPE_STRING
        # Map/Set now use HAMT (24 bytes: root pointer + len + flags)
        # HAMT nodes are gc_alloc'd; we mark them via gc_mark_hamt
        self.type_info[self.TYPE_MAP] = {'size': 24, 'ref_offsets': []}
        self.type_descriptors['Map'] = self.TYPE_MAP
        self.type_info[self.TYPE_MAP_ENTRY] = {'size': 17, 'ref_offsets': []}
        self.type_descriptors['MapEntry'] = self.TYPE_MAP_ENTRY
        self.type_info[self.TYPE_SET] = {'size': 24, 'ref_offsets': []}
        self.type_descriptors['Set'] = self.TYPE_SET
        self.type_info[self.TYPE_SET_ENTRY] = {'size': 9, 'ref_offsets': []}
        self.type_descriptors['SetEntry'] = self.TYPE_SET_ENTRY
        self.type_info[self.TYPE_CHANNEL] = {'size': 48, 'ref_offsets': [32]}
        self.type_descriptors['Channel'] = self.TYPE_CHANNEL
        # Array: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size } = 40 bytes
        # For slice views, owner points to the shared data buffer (traced via mark_array)
        self.type_info[self.TYPE_ARRAY] = {'size': 40, 'ref_offsets': [0]}
        self.type_descriptors['Array'] = self.TYPE_ARRAY

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

    def finalize_type_tables(self):
        """Create global offset arrays for registered user types.

        Phase 9: This must be called after all types are registered (after codegen
        processes all type declarations) to populate gc_type_offsets_table.

        For each user type with pointer fields (ref_offsets), creates a global
        array containing the offsets terminated by -1, and stores a pointer to
        it in gc_type_offsets_table[type_id].
        """
        for type_id, info in self.type_info.items():
            # Skip built-in types (they have hardcoded handling in gc_mark_object)
            if type_id < self.TYPE_FIRST_USER:
                continue

            ref_offsets = info.get('ref_offsets', [])
            if not ref_offsets:
                # No pointer fields - leave table entry as NULL
                continue

            # Create global array with offsets + terminator (-1)
            offsets_with_terminator = ref_offsets + [-1]
            array_type = ir.ArrayType(self.i64, len(offsets_with_terminator))
            array_values = [ir.Constant(self.i64, off) for off in offsets_with_terminator]
            array_const = ir.Constant(array_type, array_values)

            # Create global variable for this type's offsets
            global_name = f"gc_type_{type_id}_offsets"
            offset_array = ir.GlobalVariable(self.module, array_type, name=global_name)
            offset_array.initializer = array_const
            offset_array.linkage = 'internal'

            # Get pointer to first element
            zero = ir.Constant(self.i32, 0)
            array_ptr = offset_array.gep([zero, zero])

            # Store in gc_type_offsets_table[type_id]
            # We need to use a constant expression to initialize the table entry
            # Since we can't modify the initializer after creation, we need to
            # rebuild the table with the new entries
            # Actually, we need to update the global's initializer

            # Store the array pointer in the table
            # For now, we'll build a new initializer with all the entries
            pass  # We'll handle this after the loop

        # Rebuild gc_type_offsets_table initializer with all entries
        new_entries = []
        for i in range(self.MAX_TYPES):
            if i in self.type_info and i >= self.TYPE_FIRST_USER:
                ref_offsets = self.type_info[i].get('ref_offsets', [])
                if ref_offsets:
                    # Find the global we created
                    global_name = f"gc_type_{i}_offsets"
                    for gv in self.module.global_values:
                        if gv.name == global_name:
                            # Get pointer to first element as constant expr
                            zero = ir.Constant(self.i32, 0)
                            ptr = gv.gep([zero, zero])
                            new_entries.append(ptr)
                            break
                    else:
                        new_entries.append(ir.Constant(self.i64_ptr, None))
                else:
                    new_entries.append(ir.Constant(self.i64_ptr, None))
            else:
                new_entries.append(ir.Constant(self.i64_ptr, None))

        # Update the table initializer
        table_type = ir.ArrayType(self.i64_ptr, self.MAX_TYPES)
        self.gc_type_offsets_table.initializer = ir.Constant(table_type, new_entries)

    def _implement_gc_init(self):
        """Initialize GC state, pthread primitives, and spawn GC thread"""
        func = self.gc_init
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Reset basic state
        builder.store(ir.Constant(self.i8_ptr, None), self.gc_frame_top)
        builder.store(ir.Constant(self.i8_ptr, None), self.gc_alloc_list)
        builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)
        builder.store(ir.Constant(self.i1, 1), self.gc_enabled)

        # ============================================================
        # Initialize pthread mutex and condition variables
        # Allocate 64 bytes for each (enough for any platform)
        # ============================================================

        # Allocate and initialize mutex
        mutex_size = ir.Constant(self.i64, 64)
        mutex_ptr = builder.call(self.codegen.malloc, [mutex_size])
        builder.store(mutex_ptr, self.gc_mutex)
        builder.call(self.pthread_mutex_init, [mutex_ptr, ir.Constant(self.i8_ptr, None)])

        # Allocate and initialize condition variable for GC start
        cond_size = ir.Constant(self.i64, 64)
        cond_start_ptr = builder.call(self.codegen.malloc, [cond_size])
        builder.store(cond_start_ptr, self.gc_cond_start)
        builder.call(self.pthread_cond_init, [cond_start_ptr, ir.Constant(self.i8_ptr, None)])

        # Allocate and initialize condition variable for GC completion
        cond_done_ptr = builder.call(self.codegen.malloc, [cond_size])
        builder.store(cond_done_ptr, self.gc_cond_done)
        builder.call(self.pthread_cond_init, [cond_done_ptr, ir.Constant(self.i8_ptr, None)])

        # ============================================================
        # Initialize dual-heap state
        # gc_state is already initialized by global initializer
        # Just reset it here for good measure
        # ============================================================

        # Reset gc_state.active_heap = 0
        active_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), active_ptr)

        # Reset gc_state.gc_in_progress = 0
        in_prog_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), in_prog_ptr)

        # Reset gc_state.gc_complete = 1
        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), complete_ptr)

        # Reset heap_a.alloc_list = null, heap_a.alloc_count = 0
        heap_a_list_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), heap_a_list_ptr)
        heap_a_count_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), heap_a_count_ptr)

        # Reset heap_b.alloc_list = null, heap_b.alloc_count = 0
        heap_b_list_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), heap_b_list_ptr)
        heap_b_count_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), heap_b_count_ptr)

        # ============================================================
        # Spawn GC thread as detached
        # PTHREAD_CREATE_DETACHED = 1 on most systems
        # ============================================================

        # Allocate thread attribute
        # Phase 9: Disable background GC thread for synchronous collection model
        # The high watermark GC uses synchronous collection via gc_collect(),
        # so we don't need the background thread. This avoids potential race
        # conditions and simplifies the implementation.
        #
        # The pthread infrastructure is kept in place for future use if we
        # want to re-enable async collection.
        pass  # Thread spawn disabled

        # ============================================================
        # Phase 5: Register main thread with the GC system
        # Thread ID 0 is used for the main thread in single-threaded mode
        # ============================================================
        builder.call(self.gc_register_thread, [ir.Constant(self.i64, 0)])

        builder.ret_void()

    def _implement_gc_push_frame(self):
        """Push a new frame onto the shadow stack"""
        func = self.gc_push_frame
        func.args[0].name = "num_roots"
        func.args[1].name = "roots"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        num_roots = func.args[0]
        roots = func.args[1]

        # Allocate frame struct (24 bytes: parent + num_roots + roots_ptr)
        frame_size = ir.Constant(self.i64, 24)
        raw_frame = builder.call(self.codegen.malloc, [frame_size])
        frame = builder.bitcast(raw_frame, self.gc_frame_type.as_pointer())

        # Set parent to current top
        old_top = builder.load(self.gc_frame_top)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(old_top, parent_ptr)

        # Set num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(num_roots, num_roots_ptr)

        # Set roots pointer
        roots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(roots, roots_ptr_ptr)

        # Update frame top
        builder.store(raw_frame, self.gc_frame_top)

        # Increment frame depth (Phase 0/2 preparation)
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.add(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

        # Phase 6: Sync depth to ThreadEntry
        builder.call(self.gc_sync_thread_depth, [])

        builder.ret(raw_frame)

    def _implement_gc_pop_frame(self):
        """Pop a frame from the shadow stack.

        Phase 3: Also checks if we've returned to the watermark depth,
        and if so, triggers a garbage collection.
        """
        func = self.gc_pop_frame
        func.args[0].name = "frame_ptr"

        entry = func.append_basic_block("entry")
        check_watermark = func.append_basic_block("check_watermark")
        trigger_gc = func.append_basic_block("trigger_gc")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        frame_ptr = func.args[0]
        frame = builder.bitcast(frame_ptr, self.gc_frame_type.as_pointer())

        # Get parent and set as new top
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, self.gc_frame_top)

        # Decrement frame depth (Phase 0/2/3)
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.sub(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

        # Phase 6: Sync depth to ThreadEntry
        builder.call(self.gc_sync_thread_depth, [])

        # Free the frame
        builder.call(self.codegen.free, [frame_ptr])

        # Phase 3: Check if we've hit the watermark
        builder.branch(check_watermark)

        builder.position_at_end(check_watermark)
        # Check if watermark is installed
        watermark_installed = builder.load(self.gc_watermark_installed)
        builder.cbranch(watermark_installed, trigger_gc, done)

        builder.position_at_end(trigger_gc)
        # Check if new_depth <= watermark_depth (we've returned to or past the watermark)
        watermark_depth = builder.load(self.gc_watermark_depth)
        at_watermark = builder.icmp_unsigned("<=", new_depth, watermark_depth)

        with builder.if_then(at_watermark):
            # Clear the watermark (one-shot trigger) - global state
            builder.store(ir.Constant(self.i1, 0), self.gc_watermark_installed)
            # Trigger garbage collection
            builder.call(self.gc_collect, [])
            # Phase 6: Clear watermarks on all ThreadEntries
            builder.call(self.gc_clear_watermarks, [])

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_set_root(self):
        """Set a root slot value"""
        func = self.gc_set_root
        func.args[0].name = "roots"
        func.args[1].name = "index"
        func.args[2].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        roots = func.args[0]
        index = func.args[1]
        value = func.args[2]

        # roots[index] = value
        slot_ptr = builder.gep(roots, [index], inbounds=True)
        builder.store(value, slot_ptr)

        builder.ret_void()

    def _implement_gc_alloc(self):
        """Allocate memory with GC tracking"""
        func = self.gc_alloc
        func.args[0].name = "user_size"
        func.args[1].name = "type_id"

        entry = func.append_basic_block("entry")
        do_alloc = func.append_basic_block("do_alloc")

        builder = ir.IRBuilder(entry)

        user_size = func.args[0]
        type_id = func.args[1]

        # Increment allocation counter (for statistics, threshold check disabled)
        count = builder.load(self.gc_alloc_count)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_alloc_count)

        # NOTE: Automatic GC triggering from gc_alloc is UNSAFE because:
        # - Multi-allocation operations (HAMT insert, list append, etc.) create
        #   intermediate objects that aren't rooted until the operation completes
        # - If GC runs mid-operation, these unrooted objects get swept
        # - This causes use-after-free crashes
        #
        # Safe collection points are:
        # 1. Explicit gc() calls in user code
        # 2. gc_install_watermark() for high-watermark collection
        # 3. Future: function entry/exit with proper safe-point checks
        builder.branch(do_alloc)

        # Allocate memory
        builder.position_at_end(do_alloc)

        # Total size = header + user_size, aligned to 8 bytes
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        total_size = builder.add(user_size, header_size)

        # Align to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.and_(
            builder.add(total_size, seven),
            ir.Constant(self.i64, ~7 & 0xFFFFFFFFFFFFFFFF)
        )

        # Allocate block (header + data)
        block = builder.call(self.codegen.malloc, [aligned_size])

        # Initialize header (Phase 1: 32-byte header with birth-marking)
        header = builder.bitcast(block, self.header_type.as_pointer())

        # Size field (offset 0)
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(aligned_size, size_ptr)

        # Type ID field (offset 8) - extend i32 to i64
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id_64 = builder.zext(type_id, self.i64)
        builder.store(type_id_64, type_id_ptr)

        # Flags field (offset 16) - BIRTH-MARKING: objects are born marked!
        # Phase 4: Use gc_current_mark_value for birth-marking (supports mark inversion)
        # This is critical for high watermark correctness
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_mark = builder.load(self.gc_current_mark_value)
        builder.store(current_mark, flags_ptr)

        # Forward pointer field (offset 24) - 0 means not forwarded
        forward_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), forward_ptr)

        # Add to allocation list
        node_size = ir.Constant(self.i64, 24)  # sizeof(alloc_node)
        raw_node = builder.call(self.codegen.malloc, [node_size])
        node = builder.bitcast(raw_node, self.alloc_node_type.as_pointer())

        # node->next = gc_alloc_list
        old_head = builder.load(self.gc_alloc_list)
        next_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(old_head, next_ptr)

        # node->data = user_ptr (after header)
        block_int = builder.ptrtoint(block, self.i64)
        user_ptr_int = builder.add(block_int, header_size)
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)
        data_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(user_ptr, data_ptr)

        # node->size = aligned_size
        node_size_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(aligned_size, node_size_ptr)

        # gc_alloc_list = node
        builder.store(raw_node, self.gc_alloc_list)

        # Update GC statistics (Phase 0)
        # Increment total_allocations
        total_allocs_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        total_allocs = builder.load(total_allocs_ptr)
        new_total_allocs = builder.add(total_allocs, ir.Constant(self.i64, 1))
        builder.store(new_total_allocs, total_allocs_ptr)

        # Add to total_bytes_allocated
        total_bytes_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        total_bytes = builder.load(total_bytes_ptr)
        new_total_bytes = builder.add(total_bytes, aligned_size)
        builder.store(new_total_bytes, total_bytes_ptr)

        # Increment allocations_since_last_gc
        allocs_since_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        allocs_since = builder.load(allocs_since_ptr)
        new_allocs_since = builder.add(allocs_since, ir.Constant(self.i64, 1))
        builder.store(new_allocs_since, allocs_since_ptr)

        # Add to bytes_since_last_gc
        bytes_since_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        bytes_since = builder.load(bytes_since_ptr)
        new_bytes_since = builder.add(bytes_since, aligned_size)
        builder.store(new_bytes_since, bytes_since_ptr)

        builder.ret(user_ptr)

    def _implement_gc_mark_hamt(self):
        """Recursively mark HAMT nodes and leaves.

        HAMT uses pointer tagging:
        - bit 0 = 1: leaf node
        - bit 0 = 0: internal node (or null)

        HAMT node struct: { i32 bitmap, i8** children }
        HAMT leaf struct: { i64 hash, i64 key, i64 value }

        Both are allocated via gc_alloc, so we need to mark them.

        flags parameter (from Map/Set struct):
        - bit 0: key is a heap pointer (mark it)
        - bit 1: value is a heap pointer (mark it)
        """
        func = self.gc_mark_hamt
        func.args[0].name = "root"
        func.args[1].name = "flags"

        entry = func.append_basic_block("entry")
        check_tag = func.append_basic_block("check_tag")
        is_leaf = func.append_basic_block("is_leaf")
        mark_key = func.append_basic_block("mark_key")
        after_key = func.append_basic_block("after_key")
        mark_value = func.append_basic_block("mark_value")
        after_value = func.append_basic_block("after_value")
        is_internal = func.append_basic_block("is_internal")
        child_loop = func.append_basic_block("child_loop")
        child_body = func.append_basic_block("child_body")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        root = func.args[0]
        flags = func.args[1]

        # Null check
        is_null = builder.icmp_unsigned("==", root, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, check_tag)

        # Check tag bit (bit 0)
        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(root, self.i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(self.i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(self.i64, 0))
        builder.cbranch(is_leaf_tag, is_leaf, is_internal)

        # Handle leaf - untag and mark, plus mark key/value if flags indicate
        builder.position_at_end(is_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(self.i64, ~1 & 0xFFFFFFFFFFFFFFFF))
        untagged_ptr = builder.inttoptr(untagged_int, self.i8_ptr)
        builder.call(self.gc_mark_object, [untagged_ptr])

        # Leaf struct: { i64 hash, i64 key, i64 value }
        leaf_type = ir.LiteralStructType([self.i64, self.i64, self.i64])
        leaf_ptr = builder.bitcast(untagged_ptr, leaf_type.as_pointer())

        # Check if key needs marking (flag bit 0)
        key_is_ptr = builder.and_(flags, ir.Constant(self.i32, 1))
        key_needs_mark = builder.icmp_unsigned("!=", key_is_ptr, ir.Constant(self.i32, 0))
        builder.cbranch(key_needs_mark, mark_key, after_key)

        # Mark key as heap object
        builder.position_at_end(mark_key)
        key_ptr_ptr = builder.gep(leaf_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        key_as_int = builder.load(key_ptr_ptr)
        key_as_ptr = builder.inttoptr(key_as_int, self.i8_ptr)
        # Null check for key
        key_is_null = builder.icmp_unsigned("==", key_as_ptr, ir.Constant(self.i8_ptr, None))
        with builder.if_then(builder.not_(key_is_null)):
            builder.call(self.gc_mark_object, [key_as_ptr])
        builder.branch(after_key)

        # Check if value needs marking (flag bit 1)
        builder.position_at_end(after_key)
        value_is_ptr = builder.and_(flags, ir.Constant(self.i32, 2))
        value_needs_mark = builder.icmp_unsigned("!=", value_is_ptr, ir.Constant(self.i32, 0))
        builder.cbranch(value_needs_mark, mark_value, after_value)

        # Mark value as heap object
        builder.position_at_end(mark_value)
        value_ptr_ptr = builder.gep(leaf_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        value_as_int = builder.load(value_ptr_ptr)
        value_as_ptr = builder.inttoptr(value_as_int, self.i8_ptr)
        # Null check for value
        value_is_null = builder.icmp_unsigned("==", value_as_ptr, ir.Constant(self.i8_ptr, None))
        with builder.if_then(builder.not_(value_is_null)):
            builder.call(self.gc_mark_object, [value_as_ptr])
        builder.branch(after_value)

        builder.position_at_end(after_value)
        builder.branch(done)

        # Handle internal node
        builder.position_at_end(is_internal)
        # Mark the node itself
        builder.call(self.gc_mark_object, [root])

        # HAMT node struct: { i32 bitmap, i8** children }
        hamt_node_type = ir.LiteralStructType([self.i32, self.i8_ptr.as_pointer()])
        node_ptr = builder.bitcast(root, hamt_node_type.as_pointer())

        # Get bitmap to count children
        bitmap_ptr = builder.gep(node_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        bitmap = builder.load(bitmap_ptr)

        # Compute popcount inline (Brian Kernighan's algorithm)
        count_ptr = builder.alloca(self.i32, name="count")
        x_ptr = builder.alloca(self.i32, name="x")
        builder.store(ir.Constant(self.i32, 0), count_ptr)
        builder.store(bitmap, x_ptr)

        popcount_cond = func.append_basic_block("popcount_cond")
        popcount_body = func.append_basic_block("popcount_body")
        popcount_done = func.append_basic_block("popcount_done")

        builder.branch(popcount_cond)

        builder.position_at_end(popcount_cond)
        curr_x = builder.load(x_ptr)
        is_nonzero = builder.icmp_unsigned("!=", curr_x, ir.Constant(self.i32, 0))
        builder.cbranch(is_nonzero, popcount_body, popcount_done)

        builder.position_at_end(popcount_body)
        x_minus_1 = builder.sub(curr_x, ir.Constant(self.i32, 1))
        new_x = builder.and_(curr_x, x_minus_1)
        builder.store(new_x, x_ptr)
        curr_count = builder.load(count_ptr)
        new_count = builder.add(curr_count, ir.Constant(self.i32, 1))
        builder.store(new_count, count_ptr)
        builder.branch(popcount_cond)

        builder.position_at_end(popcount_done)
        child_count = builder.load(count_ptr)

        # Get children array pointer
        children_ptr_ptr = builder.gep(node_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        children_ptr = builder.load(children_ptr_ptr)

        # Mark the children array itself (it's also gc_alloc'd)
        children_as_i8 = builder.bitcast(children_ptr, self.i8_ptr)
        builder.call(self.gc_mark_object, [children_as_i8])

        # Iterate over children and recursively mark
        idx_ptr = builder.alloca(self.i32, name="idx")
        builder.store(ir.Constant(self.i32, 0), idx_ptr)
        builder.branch(child_loop)

        builder.position_at_end(child_loop)
        idx = builder.load(idx_ptr)
        done_children = builder.icmp_signed(">=", idx, child_count)
        builder.cbranch(done_children, done, child_body)

        builder.position_at_end(child_body)
        idx_64 = builder.zext(idx, self.i64)
        child_ptr_ptr = builder.gep(children_ptr, [idx_64], inbounds=True)
        child_ptr = builder.load(child_ptr_ptr)
        # Recursive call to mark child (could be node or leaf), passing flags
        builder.call(func, [child_ptr, flags])
        next_idx = builder.add(idx, ir.Constant(self.i32, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(child_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_mark_object(self):
        """Mark an object as live and recursively mark referenced objects.

        Phase 9 Enhancement: Handles user-defined types by looking up their
        pointer field offsets from gc_type_offsets_table and marking each field.
        """
        func = self.gc_mark_object
        func.args[0].name = "ptr"

        entry = func.append_basic_block("entry")
        get_header = func.append_basic_block("get_header")
        do_mark = func.append_basic_block("do_mark")
        check_type = func.append_basic_block("check_type")
        check_user_type = func.append_basic_block("check_user_type")
        mark_user_type = func.append_basic_block("mark_user_type")
        user_offset_loop = func.append_basic_block("user_offset_loop")
        user_mark_field = func.append_basic_block("user_mark_field")
        user_next_offset = func.append_basic_block("user_next_offset")
        mark_map = func.append_basic_block("mark_map")
        mark_list = func.append_basic_block("mark_list")
        mark_array = func.append_basic_block("mark_array")
        mark_set = func.append_basic_block("mark_set")
        mark_string = func.append_basic_block("mark_string")
        mark_channel = func.append_basic_block("mark_channel")
        mark_pv_node = func.append_basic_block("mark_pv_node")
        pv_node_loop = func.append_basic_block("pv_node_loop")
        pv_node_check = func.append_basic_block("pv_node_check")
        pv_node_mark_child = func.append_basic_block("pv_node_mark_child")
        pv_node_next = func.append_basic_block("pv_node_next")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        ptr = func.args[0]

        # Null check
        is_null = builder.icmp_unsigned("==", ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, get_header)

        builder.position_at_end(get_header)
        # Get header (before user pointer)
        ptr_int = builder.ptrtoint(ptr, self.i64)
        header_int = builder.sub(ptr_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.i8_ptr)
        header = builder.bitcast(header_ptr, self.header_type.as_pointer())

        # Check if already marked (Phase 4: compare mark bit to gc_current_mark_value)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)
        mark_bit = builder.and_(flags, ir.Constant(self.i64, self.FLAG_MARK_BIT))
        current_mark = builder.load(self.gc_current_mark_value)
        already_marked = builder.icmp_unsigned("==", mark_bit, current_mark)
        builder.cbranch(already_marked, done, do_mark)

        builder.position_at_end(do_mark)
        # Set mark bit to current mark value (Phase 4: mark inversion)
        # Clear bit 0 and set it to gc_current_mark_value
        flags_val = builder.load(flags_ptr)
        cleared_flags = builder.and_(flags_val, ir.Constant(self.i64, ~self.FLAG_MARK_BIT & 0xFFFFFFFFFFFFFFFF))
        current_mark2 = builder.load(self.gc_current_mark_value)
        new_flags = builder.or_(cleared_flags, current_mark2)
        builder.store(new_flags, flags_ptr)

        # Get type_id and check for types that need recursive marking (Phase 1: type_id is now i64)
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        builder.branch(check_type)

        # Check type and branch to appropriate recursive marking
        builder.position_at_end(check_type)

        # Phase 9: First check if this is a user-defined type (type_id >= TYPE_FIRST_USER)
        is_user_type = builder.icmp_unsigned(">=", type_id, ir.Constant(self.i64, self.TYPE_FIRST_USER))
        builder.cbranch(is_user_type, check_user_type, mark_map)  # Fall through to built-in type check

        # Check if user type has offset table entry
        builder.position_at_end(check_user_type)
        # Store type_id and ptr for use in loops
        type_id_alloca = builder.alloca(self.i64, name="type_id_store")
        builder.store(type_id, type_id_alloca)
        ptr_alloca = builder.alloca(self.i8_ptr, name="ptr_store")
        builder.store(ptr, ptr_alloca)

        # Look up gc_type_offsets_table[type_id]
        table_ptr = builder.gep(self.gc_type_offsets_table,
                                [ir.Constant(self.i32, 0), type_id], inbounds=False)
        offset_array_ptr = builder.load(table_ptr)

        # If offset_array_ptr is null, no pointer fields to mark
        has_offsets = builder.icmp_unsigned("!=", offset_array_ptr, ir.Constant(self.i64_ptr, None))
        builder.cbranch(has_offsets, mark_user_type, done)

        # Mark user type: iterate through offset array (terminated by -1)
        builder.position_at_end(mark_user_type)
        offset_idx = builder.alloca(self.i64, name="offset_idx")
        builder.store(ir.Constant(self.i64, 0), offset_idx)
        builder.branch(user_offset_loop)

        # User offset loop
        builder.position_at_end(user_offset_loop)
        idx = builder.load(offset_idx)
        # Reload offset_array_ptr in this block
        type_id_val = builder.load(type_id_alloca)
        table_ptr2 = builder.gep(self.gc_type_offsets_table,
                                 [ir.Constant(self.i32, 0), type_id_val], inbounds=False)
        offset_array = builder.load(table_ptr2)
        offset_ptr = builder.gep(offset_array, [idx], inbounds=False)
        offset = builder.load(offset_ptr)

        # Check if offset is -1 (terminator)
        is_terminator = builder.icmp_signed("==", offset, ir.Constant(self.i64, -1))
        builder.cbranch(is_terminator, done, user_mark_field)

        # Mark field at offset
        builder.position_at_end(user_mark_field)
        # Reload ptr in this block
        obj_ptr = builder.load(ptr_alloca)
        obj_int = builder.ptrtoint(obj_ptr, self.i64)
        # Reload offset for this block
        idx2 = builder.load(offset_idx)
        type_id_val2 = builder.load(type_id_alloca)
        table_ptr3 = builder.gep(self.gc_type_offsets_table,
                                 [ir.Constant(self.i32, 0), type_id_val2], inbounds=False)
        offset_array2 = builder.load(table_ptr3)
        offset_ptr2 = builder.gep(offset_array2, [idx2], inbounds=False)
        field_offset = builder.load(offset_ptr2)

        field_addr_int = builder.add(obj_int, field_offset)
        field_addr = builder.inttoptr(field_addr_int, self.i8_ptr_ptr)
        field_ptr = builder.load(field_addr)
        # Recursively mark the field
        builder.call(func, [field_ptr])
        builder.branch(user_next_offset)

        # Increment index and continue loop
        builder.position_at_end(user_next_offset)
        idx3 = builder.load(offset_idx)
        next_idx = builder.add(idx3, ir.Constant(self.i64, 1))
        builder.store(next_idx, offset_idx)
        builder.branch(user_offset_loop)

        # Built-in type handling with switch
        # Create a new block for the switch since we may have branched here
        builtin_switch = func.append_basic_block("builtin_switch")

        # Fix the mark_map block - it now needs to check if it's actually TYPE_MAP
        builder.position_at_end(mark_map)
        # type_id was computed in do_mark, we need to reload from header
        header2 = builder.bitcast(
            builder.inttoptr(
                builder.sub(builder.ptrtoint(ptr, self.i64), ir.Constant(self.i64, self.HEADER_SIZE)),
                self.i8_ptr
            ),
            self.header_type.as_pointer()
        )
        type_id_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id2 = builder.load(type_id_ptr2)

        # Create a switch for type_id (Phase 1: type_id is now i64)
        switch = builder.switch(type_id2, done)
        switch.add_case(ir.Constant(self.i64, self.TYPE_MAP), builtin_switch)
        switch.add_case(ir.Constant(self.i64, self.TYPE_LIST), mark_list)
        switch.add_case(ir.Constant(self.i64, self.TYPE_ARRAY), mark_array)
        switch.add_case(ir.Constant(self.i64, self.TYPE_SET), mark_set)
        switch.add_case(ir.Constant(self.i64, self.TYPE_STRING), mark_string)
        switch.add_case(ir.Constant(self.i64, self.TYPE_CHANNEL), mark_channel)
        switch.add_case(ir.Constant(self.i64, self.TYPE_PV_NODE), mark_pv_node)

        # Actual map marking (in builtin_switch block)
        builder.position_at_end(builtin_switch)
        # Mark Map: HAMT-based, root at offset 0
        # Map struct: { i64 root, i64 len, i64 flags }
        # All fields are i64 for cross-platform consistency (no padding issues)
        # HAMT nodes and leaves ARE gc_alloc'd, so we must traverse and mark them.
        # flags: bit 0 = key is ptr, bit 1 = value is ptr
        map_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64]).as_pointer()
        map_typed = builder.bitcast(ptr, map_ptr_type)
        map_root_i64_ptr = builder.gep(map_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        map_root_i64 = builder.load(map_root_i64_ptr)
        map_root_ptr = builder.inttoptr(map_root_i64, self.i8_ptr)  # Convert i64 to pointer
        map_flags_ptr = builder.gep(map_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        map_flags_i64 = builder.load(map_flags_ptr)
        map_flags = builder.trunc(map_flags_i64, self.i32)  # Truncate to i32 for gc_mark_hamt
        builder.call(self.gc_mark_hamt, [map_root_ptr, map_flags])
        builder.branch(done)

        # Mark List: root (field 0) and tail (field 3) pointers
        # List struct: { i8* root (0), i64 len (1), i32 depth (2), i8* tail (3), i32 tail_len (4), i64 elem_size (5) }
        builder.position_at_end(mark_list)
        list_ptr_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i32, self.i8_ptr, self.i32, self.i64]).as_pointer()
        list_typed = builder.bitcast(ptr, list_ptr_type)
        # Mark root
        root_ptr_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        root_ptr = builder.load(root_ptr_ptr)
        builder.call(func, [root_ptr])  # Recursive call
        # Mark tail
        tail_ptr_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        tail_ptr = builder.load(tail_ptr_ptr)
        builder.call(func, [tail_ptr])  # Recursive call
        builder.branch(done)

        # Mark Array: owner pointer at field 0
        # Array struct: { i8* owner (0), i64 offset (1), i64 len (2), i64 cap (3), i64 elem_size (4) }
        # For slice views, owner points to the shared data buffer
        builder.position_at_end(mark_array)
        array_ptr_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64, self.i64, self.i64]).as_pointer()
        array_typed = builder.bitcast(ptr, array_ptr_type)
        owner_ptr_ptr = builder.gep(array_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        owner_ptr = builder.load(owner_ptr_ptr)
        builder.call(func, [owner_ptr])  # Recursive call - marks the data buffer
        builder.branch(done)

        # Mark Set: HAMT-based, root at offset 0
        # Set struct: { i64 root, i64 len, i64 flags }
        # All fields are i64 for cross-platform consistency (no padding issues)
        # HAMT nodes and leaves ARE gc_alloc'd, so we must traverse and mark them.
        # flags: bit 0 = element is ptr
        builder.position_at_end(mark_set)
        set_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64]).as_pointer()
        set_typed = builder.bitcast(ptr, set_ptr_type)
        set_root_i64_ptr = builder.gep(set_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        set_root_i64 = builder.load(set_root_i64_ptr)
        set_root_ptr = builder.inttoptr(set_root_i64, self.i8_ptr)  # Convert i64 to pointer
        set_flags_ptr = builder.gep(set_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        set_flags_i64 = builder.load(set_flags_ptr)
        set_flags = builder.trunc(set_flags_i64, self.i32)  # Truncate to i32 for gc_mark_hamt
        builder.call(self.gc_mark_hamt, [set_root_ptr, set_flags])
        builder.branch(done)

        # Mark String: owner pointer at field 0
        # String struct: { i8* owner (0), i64 offset (1), i64 len (2), i64 size (3) }
        # For slice views, owner points to the shared data buffer
        builder.position_at_end(mark_string)
        string_ptr_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64, self.i64]).as_pointer()
        string_typed = builder.bitcast(ptr, string_ptr_type)
        owner_ptr_ptr = builder.gep(string_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        owner_ptr = builder.load(owner_ptr_ptr)
        builder.call(func, [owner_ptr])  # Recursive call - marks the data buffer
        builder.branch(done)

        # Mark Channel: buffer pointer at offset 32 (4th i64 field)
        builder.position_at_end(mark_channel)
        channel_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i8_ptr]).as_pointer()
        channel_typed = builder.bitcast(ptr, channel_ptr_type)
        buffer_ptr_ptr = builder.gep(channel_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        buffer_ptr = builder.load(buffer_ptr_ptr)
        builder.call(func, [buffer_ptr])  # Recursive call
        builder.branch(done)

        # Mark PVNode: iterate through 32 children and mark each non-null one
        # PVNode struct: { i8* children[32] }
        builder.position_at_end(mark_pv_node)
        # Store ptr for use in loop
        pv_ptr_alloca = builder.alloca(self.i8_ptr, name="pv_ptr")
        builder.store(ptr, pv_ptr_alloca)
        # Child index
        pv_idx = builder.alloca(self.i64, name="pv_idx")
        builder.store(ir.Constant(self.i64, 0), pv_idx)
        builder.branch(pv_node_loop)

        # PVNode loop: for i in 0..32
        builder.position_at_end(pv_node_loop)
        idx = builder.load(pv_idx)
        done_children = builder.icmp_unsigned(">=", idx, ir.Constant(self.i64, 32))
        builder.cbranch(done_children, done, pv_node_check)

        # Check if child is non-null
        builder.position_at_end(pv_node_check)
        pv_ptr_val = builder.load(pv_ptr_alloca)
        # PVNode is just an array of 32 pointers at the user data area
        pv_children = builder.bitcast(pv_ptr_val, self.i8_ptr_ptr)
        child_idx = builder.load(pv_idx)
        child_ptr_ptr = builder.gep(pv_children, [child_idx], inbounds=False)
        child_ptr = builder.load(child_ptr_ptr)
        is_child_null = builder.icmp_unsigned("==", child_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_child_null, pv_node_next, pv_node_mark_child)

        # Mark child (child_ptr was loaded and checked in pv_node_check)
        builder.position_at_end(pv_node_mark_child)
        # Re-load the child pointer for this block
        pv_ptr_val2 = builder.load(pv_ptr_alloca)
        pv_children2 = builder.bitcast(pv_ptr_val2, self.i8_ptr_ptr)
        child_idx2 = builder.load(pv_idx)
        child_ptr_ptr2 = builder.gep(pv_children2, [child_idx2], inbounds=False)
        child_to_mark = builder.load(child_ptr_ptr2)
        builder.call(func, [child_to_mark])  # Recursive call to gc_mark_object
        builder.branch(pv_node_next)

        # Increment index and continue
        builder.position_at_end(pv_node_next)
        curr_idx = builder.load(pv_idx)
        next_idx = builder.add(curr_idx, ir.Constant(self.i64, 1))
        builder.store(next_idx, pv_idx)
        builder.branch(pv_node_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_scan_roots(self):
        """Scan shadow stack and mark all roots"""
        func = self.gc_scan_roots

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        process_frame = func.append_basic_block("process_frame")
        root_loop = func.append_basic_block("root_loop")
        mark_root = func.append_basic_block("mark_root")
        next_root = func.append_basic_block("next_root")
        next_frame = func.append_basic_block("next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # curr_frame = gc_frame_top
        curr_frame = builder.alloca(self.i8_ptr, name="curr_frame")
        top = builder.load(self.gc_frame_top)
        builder.store(top, curr_frame)

        builder.branch(frame_loop)

        # Frame loop: while curr_frame != null
        builder.position_at_end(frame_loop)
        frame_val = builder.load(curr_frame)
        is_null = builder.icmp_unsigned("==", frame_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, process_frame)

        # Process frame
        builder.position_at_end(process_frame)
        frame = builder.bitcast(frame_val, self.gc_frame_type.as_pointer())

        # Get num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)

        # Get roots array
        roots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        roots = builder.load(roots_ptr_ptr)

        # Root index
        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)

        builder.branch(root_loop)

        # Root loop: for i in 0..num_roots
        builder.position_at_end(root_loop)
        i = builder.load(root_idx)
        done_roots = builder.icmp_unsigned(">=", i, num_roots)
        builder.cbranch(done_roots, next_frame, mark_root)

        # Mark root
        builder.position_at_end(mark_root)
        i_val = builder.load(root_idx)
        root_slot = builder.gep(roots, [i_val], inbounds=True)
        root_ptr = builder.load(root_slot)

        # Mark if not null
        is_root_null = builder.icmp_unsigned("==", root_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_root_null, next_root, next_root)  # Skip null roots

        # TODO: Actually call gc_mark_object for non-null roots
        # For simplicity, we'll just increment and continue

        builder.position_at_end(next_root)
        # Actually mark the root
        builder.call(self.gc_mark_object, [root_ptr])

        next_i = builder.add(i_val, ir.Constant(self.i64, 1))
        builder.store(next_i, root_idx)
        builder.branch(root_loop)

        # Move to next frame
        builder.position_at_end(next_frame)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, curr_frame)
        builder.branch(frame_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_sweep(self):
        """Sweep allocation list and free unmarked objects.

        Traverses the allocation list, freeing unmarked objects and keeping
        marked ones (after clearing their mark bits for the next cycle).

        Phase 8 Enhancement: Tracks sweep statistics:
        - objects_swept_last_cycle (gc_stats offset 48)
        - bytes_reclaimed_last_cycle (gc_stats offset 56)
        """
        func = self.gc_sweep

        entry = func.append_basic_block("entry")
        sweep_loop = func.append_basic_block("sweep_loop")
        check_marked = func.append_basic_block("check_marked")
        is_marked_block = func.append_basic_block("is_marked")
        is_unmarked_block = func.append_basic_block("is_unmarked")
        next_obj = func.append_basic_block("next_obj")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Phase 8: Track sweep statistics
        swept_count = builder.alloca(self.i64, name="swept_count")
        builder.store(ir.Constant(self.i64, 0), swept_count)
        swept_bytes = builder.alloca(self.i64, name="swept_bytes")
        builder.store(ir.Constant(self.i64, 0), swept_bytes)

        # prev = null (pointer to previous node's next field, or gc_alloc_list)
        prev = builder.alloca(self.i8_ptr.as_pointer(), name="prev")
        builder.store(self.gc_alloc_list, prev)

        # curr = gc_alloc_list
        curr = builder.alloca(self.i8_ptr, name="curr")
        head = builder.load(self.gc_alloc_list)
        builder.store(head, curr)

        builder.branch(sweep_loop)

        # Sweep loop
        builder.position_at_end(sweep_loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, check_marked)

        # Process allocation - check if marked
        builder.position_at_end(check_marked)
        node = builder.bitcast(curr_val, self.alloc_node_type.as_pointer())

        # Get data pointer
        data_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        data_ptr = builder.load(data_ptr_ptr)

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.i8_ptr)
        header = builder.bitcast(header_ptr, self.header_type.as_pointer())

        # Check mark bit (Phase 4: compare to gc_current_mark_value for mark inversion)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)
        mark_bit = builder.and_(flags, ir.Constant(self.i64, self.FLAG_MARK_BIT))
        current_mark = builder.load(self.gc_current_mark_value)
        is_marked = builder.icmp_unsigned("==", mark_bit, current_mark)
        builder.cbranch(is_marked, is_marked_block, is_unmarked_block)

        # Object is marked - keep it (Phase 4: no need to clear mark bit with mark inversion)
        builder.position_at_end(is_marked_block)
        # Update prev to point to this node's next field
        next_field_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_field_ptr_cast = builder.bitcast(next_field_ptr, self.i8_ptr.as_pointer())
        builder.store(next_field_ptr_cast, prev)
        # Move to next
        next_ptr = builder.load(next_field_ptr)
        builder.store(next_ptr, curr)
        builder.branch(sweep_loop)

        # Object is unmarked - free it and remove from list
        builder.position_at_end(is_unmarked_block)

        # Phase 8: Get size for statistics before freeing
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        obj_size = builder.load(size_ptr)

        # Phase 8: Increment swept count
        old_count = builder.load(swept_count)
        new_count = builder.add(old_count, ir.Constant(self.i64, 1))
        builder.store(new_count, swept_count)

        # Phase 8: Add to swept bytes
        old_bytes = builder.load(swept_bytes)
        new_bytes = builder.add(old_bytes, obj_size)
        builder.store(new_bytes, swept_bytes)

        # Get next node before freeing
        next_field_ptr2 = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_node = builder.load(next_field_ptr2)
        # Update previous node's next pointer to skip this node
        prev_ptr = builder.load(prev)
        builder.store(next_node, prev_ptr)
        # Free the allocation (header + data)
        builder.call(self.codegen.free, [header_ptr])
        # Free the allocation node
        builder.call(self.codegen.free, [curr_val])
        # Move to next (prev stays the same since we removed current)
        builder.store(next_node, curr)
        builder.branch(sweep_loop)

        builder.position_at_end(next_obj)
        # This block is no longer used but keep for compatibility
        builder.branch(sweep_loop)

        builder.position_at_end(done)
        # Reset allocation counter
        builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)

        # Phase 8: Update gc_stats with sweep statistics
        # gc_stats.objects_swept_last_cycle (offset 6 = index 48/8)
        final_count = builder.load(swept_count)
        swept_count_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)
        ], inbounds=True)
        builder.store(final_count, swept_count_ptr)

        # gc_stats.bytes_reclaimed_last_cycle (offset 7 = index 56/8)
        final_bytes = builder.load(swept_bytes)
        swept_bytes_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(final_bytes, swept_bytes_ptr)

        # Phase 9: Mark value flip moved to gc_collect (before mark phase)
        # This ensures objects born after flip are properly traversed

        builder.ret_void()

    def _implement_gc_collect(self):
        """Run a full garbage collection cycle (high watermark model).

        Phase 9: Collection Orchestration
        This implements the synchronous collection cycle:
        1. Check if GC enabled and not already in progress
        2. Set gc_in_progress = 1
        3. Mark phase: scan roots and mark reachable objects
        4. Sweep phase: free unmarked objects
        5. Update statistics
        6. Set gc_in_progress = 0
        """
        func = self.gc_collect

        entry = func.append_basic_block("entry")
        check_enabled = func.append_basic_block("check_enabled")
        do_collection = func.append_basic_block("do_collection")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Check if GC enabled
        gc_enabled = builder.load(self.gc_enabled)
        builder.cbranch(gc_enabled, check_enabled, done)

        builder.position_at_end(check_enabled)
        # Check if GC already in progress (reentrant protection)
        in_prog_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        in_progress = builder.load(in_prog_ptr)
        is_in_progress = builder.icmp_unsigned("!=", in_progress, ir.Constant(self.i64, 0))
        builder.cbranch(is_in_progress, done, do_collection)

        builder.position_at_end(do_collection)

        # Set gc_in_progress = 1
        builder.store(ir.Constant(self.i64, 1), in_prog_ptr)

        # Phase 9: Flip gc_current_mark_value BEFORE mark phase
        # This ensures newly allocated objects (born with OLD mark value) will be
        # properly traversed, since they won't appear "already marked" with new value
        old_mark = builder.load(self.gc_current_mark_value)
        new_mark = builder.xor(old_mark, ir.Constant(self.i64, 1))
        builder.store(new_mark, self.gc_current_mark_value)

        # Phase 9: Mark phase - scan roots and mark all reachable objects
        # Use gc_scan_roots which marks from the shadow stack
        builder.call(self.gc_scan_roots, [])

        # Phase 9: Sweep phase - free unmarked objects
        # gc_sweep handles mark inversion (flips gc_current_mark_value)
        builder.call(self.gc_sweep, [])

        # Phase 9: Update statistics
        # Increment collections_completed (gc_stats offset 4 = index 32/8)
        collections_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        old_collections = builder.load(collections_ptr)
        new_collections = builder.add(old_collections, ir.Constant(self.i64, 1))
        builder.store(new_collections, collections_ptr)

        # Reset allocations_since_last_gc (gc_stats offset 2 = index 16/8)
        alloc_since_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), alloc_since_ptr)

        # Reset bytes_since_last_gc (gc_stats offset 3 = index 24/8)
        bytes_since_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), bytes_since_ptr)

        # Set gc_in_progress = 0
        builder.store(ir.Constant(self.i64, 0), in_prog_ptr)

        # Also set gc_complete = 1 for compatibility
        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), complete_ptr)

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_safepoint(self):
        """Implement safe-point check for automatic GC triggering.

        This function is safe to call at function entry because:
        1. All previous operations have completed
        2. Caller's heap variables are properly rooted
        3. No intermediate allocations exist yet

        Checks if allocation count >= threshold and triggers GC if so.
        """
        func = self.gc_safepoint

        entry = func.append_basic_block("entry")
        do_gc = func.append_basic_block("do_gc")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Check if GC is enabled
        gc_enabled = builder.load(self.gc_enabled)
        enabled_check = func.append_basic_block("enabled_check")
        builder.cbranch(gc_enabled, enabled_check, done)

        builder.position_at_end(enabled_check)

        # Check if allocation count >= threshold
        count = builder.load(self.gc_alloc_count)
        threshold = ir.Constant(self.i64, self.GC_THRESHOLD)
        should_gc = builder.icmp_unsigned(">=", count, threshold)
        builder.cbranch(should_gc, do_gc, done)

        # Trigger GC and reset counter
        builder.position_at_end(do_gc)
        builder.call(self.gc_collect, [])
        builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def wrap_allocation(self, builder: ir.IRBuilder, type_name: str, size: ir.Value) -> ir.Value:
        """Replace a malloc call with GC-tracked allocation."""
        type_id = self.get_type_id(type_name)
        type_id_const = ir.Constant(self.i32, type_id)
        return builder.call(self.gc_alloc, [size, type_id_const])

    def inject_gc_init(self, builder: ir.IRBuilder):
        """Inject GC initialization at start of main()"""
        builder.call(self.gc_init, [])

    def inject_safepoint(self, builder: ir.IRBuilder):
        """Inject a GC safe-point check.

        Call this at function entry (after shadow stack frame is pushed).
        If allocation threshold is exceeded, triggers synchronous GC.
        """
        builder.call(self.gc_safepoint, [])

    # Helper methods for codegen to manage shadow stack frames

    def create_frame_roots(self, builder: ir.IRBuilder, num_roots: int) -> ir.Value:
        """Create an array of root slots on the stack.

        Returns pointer to the roots array (i8**).
        """
        if num_roots == 0:
            return ir.Constant(self.i8_ptr_ptr, None)

        # Allocate array of i8* on stack
        roots_type = ir.ArrayType(self.i8_ptr, num_roots)
        roots_alloca = builder.alloca(roots_type, name="gc_roots")

        # Zero-initialize
        for i in range(num_roots):
            slot_ptr = builder.gep(roots_alloca, [
                ir.Constant(self.i32, 0),
                ir.Constant(self.i32, i)
            ], inbounds=True)
            builder.store(ir.Constant(self.i8_ptr, None), slot_ptr)

        # Cast to i8**
        return builder.bitcast(roots_alloca, self.i8_ptr_ptr)

    def push_frame(self, builder: ir.IRBuilder, num_roots: int, roots: ir.Value) -> ir.Value:
        """Push a GC frame. Returns frame pointer for later pop."""
        num_roots_val = ir.Constant(self.i64, num_roots)
        return builder.call(self.gc_push_frame, [num_roots_val, roots])

    def pop_frame(self, builder: ir.IRBuilder, frame: ir.Value):
        """Pop a GC frame."""
        builder.call(self.gc_pop_frame, [frame])

    def set_root(self, builder: ir.IRBuilder, roots: ir.Value, index: int, value: ir.Value):
        """Set a root slot to a value."""
        index_val = ir.Constant(self.i64, index)
        # Cast value to i8* if needed
        if value.type != self.i8_ptr:
            if isinstance(value.type, ir.PointerType):
                value = builder.bitcast(value, self.i8_ptr)
            else:
                value = builder.inttoptr(value, self.i8_ptr)
        builder.call(self.gc_set_root, [roots, index_val, value])

    # ========================================================================
    # Dual-Heap Async GC Implementations
    # ========================================================================

    def _implement_gc_capture_snapshot(self):
        """Capture shadow stack roots into a snapshot structure.

        Walks the shadow stack chain and copies all root pointer values
        into a newly allocated snapshot. Returns pointer to snapshot.
        """
        func = self.gc_capture_snapshot

        entry = func.append_basic_block("entry")
        count_loop = func.append_basic_block("count_loop")
        count_frame = func.append_basic_block("count_frame")
        count_next = func.append_basic_block("count_next")
        alloc_snap = func.append_basic_block("alloc_snap")
        copy_loop = func.append_basic_block("copy_loop")
        copy_frame = func.append_basic_block("copy_frame")
        copy_roots = func.append_basic_block("copy_roots")
        copy_root = func.append_basic_block("copy_root")
        copy_next_root = func.append_basic_block("copy_next_root")
        copy_next_frame = func.append_basic_block("copy_next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # First pass: count total roots
        total_roots = builder.alloca(self.i64, name="total_roots")
        builder.store(ir.Constant(self.i64, 0), total_roots)
        frame_ptr = builder.alloca(self.i8_ptr, name="frame_ptr")
        top = builder.load(self.gc_frame_top)
        builder.store(top, frame_ptr)
        builder.branch(count_loop)

        # Count loop
        builder.position_at_end(count_loop)
        curr_frame = builder.load(frame_ptr)
        is_null = builder.icmp_unsigned("==", curr_frame, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, alloc_snap, count_frame)

        builder.position_at_end(count_frame)
        frame = builder.bitcast(curr_frame, self.gc_frame_type.as_pointer())
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)
        curr_total = builder.load(total_roots)
        new_total = builder.add(curr_total, num_roots)
        builder.store(new_total, total_roots)
        builder.branch(count_next)

        builder.position_at_end(count_next)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, frame_ptr)
        builder.branch(count_loop)

        # Allocate snapshot
        builder.position_at_end(alloc_snap)
        final_count = builder.load(total_roots)

        # Allocate snapshot struct (24 bytes)
        snap_size = ir.Constant(self.i64, 24)
        snap_raw = builder.call(self.codegen.malloc, [snap_size])
        snapshot = builder.bitcast(snap_raw, self.root_snapshot_type.as_pointer())

        # Allocate roots array
        ptr_size = ir.Constant(self.i64, 8)
        array_size = builder.mul(final_count, ptr_size)
        # Ensure at least 8 bytes even if count is 0
        min_size = builder.icmp_unsigned(">", array_size, ir.Constant(self.i64, 0))
        actual_size = builder.select(min_size, array_size, ir.Constant(self.i64, 8))
        roots_array = builder.call(self.codegen.malloc, [actual_size])
        roots_typed = builder.bitcast(roots_array, self.i8_ptr_ptr)

        # Store in snapshot
        roots_field = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(roots_typed, roots_field)
        count_field = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(final_count, count_field)
        # heap_to_collect will be set by caller
        heap_field = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), heap_field)

        # Second pass: copy roots
        copy_idx = builder.alloca(self.i64, name="copy_idx")
        builder.store(ir.Constant(self.i64, 0), copy_idx)
        top2 = builder.load(self.gc_frame_top)
        builder.store(top2, frame_ptr)
        builder.branch(copy_loop)

        builder.position_at_end(copy_loop)
        curr_frame2 = builder.load(frame_ptr)
        is_null2 = builder.icmp_unsigned("==", curr_frame2, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null2, done, copy_frame)

        builder.position_at_end(copy_frame)
        frame2 = builder.bitcast(curr_frame2, self.gc_frame_type.as_pointer())
        num_roots_ptr2 = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        frame_num_roots = builder.load(num_roots_ptr2)
        roots_ptr_ptr = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        frame_roots = builder.load(roots_ptr_ptr)

        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)
        builder.branch(copy_roots)

        builder.position_at_end(copy_roots)
        ri = builder.load(root_idx)
        done_roots = builder.icmp_unsigned(">=", ri, frame_num_roots)
        builder.cbranch(done_roots, copy_next_frame, copy_root)

        builder.position_at_end(copy_root)
        ri2 = builder.load(root_idx)
        src_slot = builder.gep(frame_roots, [ri2], inbounds=True)
        root_val = builder.load(src_slot)

        ci = builder.load(copy_idx)
        dst_slot = builder.gep(roots_typed, [ci], inbounds=True)
        builder.store(root_val, dst_slot)

        new_ci = builder.add(ci, ir.Constant(self.i64, 1))
        builder.store(new_ci, copy_idx)
        builder.branch(copy_next_root)

        builder.position_at_end(copy_next_root)
        next_ri = builder.add(ri2, ir.Constant(self.i64, 1))
        builder.store(next_ri, root_idx)
        builder.branch(copy_roots)

        builder.position_at_end(copy_next_frame)
        parent_ptr2 = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent2 = builder.load(parent_ptr2)
        builder.store(parent2, frame_ptr)
        builder.branch(copy_loop)

        builder.position_at_end(done)
        builder.ret(snapshot)

    def _implement_gc_mark_from_snapshot(self):
        """Mark objects reachable from snapshot roots."""
        func = self.gc_mark_from_snapshot
        func.args[0].name = "snapshot"

        entry = func.append_basic_block("entry")
        mark_loop = func.append_basic_block("mark_loop")
        mark_root = func.append_basic_block("mark_root")
        next_root = func.append_basic_block("next_root")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        snapshot = func.args[0]

        # Get roots array and count
        roots_ptr = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        roots = builder.load(roots_ptr)
        count_ptr = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        count = builder.load(count_ptr)

        idx = builder.alloca(self.i64, name="idx")
        builder.store(ir.Constant(self.i64, 0), idx)
        builder.branch(mark_loop)

        builder.position_at_end(mark_loop)
        i = builder.load(idx)
        done_marking = builder.icmp_unsigned(">=", i, count)
        builder.cbranch(done_marking, done, mark_root)

        builder.position_at_end(mark_root)
        i2 = builder.load(idx)
        root_slot = builder.gep(roots, [i2], inbounds=True)
        root_ptr = builder.load(root_slot)

        # Mark if not null
        is_null = builder.icmp_unsigned("==", root_ptr, ir.Constant(self.i8_ptr, None))
        with builder.if_then(builder.not_(is_null)):
            builder.call(self.gc_mark_object, [root_ptr])

        builder.branch(next_root)

        builder.position_at_end(next_root)
        next_i = builder.add(i2, ir.Constant(self.i64, 1))
        builder.store(next_i, idx)
        builder.branch(mark_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_swap_heaps(self):
        """Atomically swap active heap and prepare for collection."""
        func = self.gc_swap_heaps

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Lock mutex
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Capture snapshot
        snapshot = builder.call(self.gc_capture_snapshot, [])

        # Get current active heap index
        active_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        old_active = builder.load(active_ptr)

        # Set snapshot.heap_to_collect = old_active
        heap_to_collect_ptr = builder.gep(snapshot, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(old_active, heap_to_collect_ptr)

        # Swap active heap: new_active = 1 - old_active
        new_active = builder.sub(ir.Constant(self.i64, 1), old_active)
        builder.store(new_active, active_ptr)

        # Store snapshot for GC thread
        builder.store(snapshot, self.gc_snapshot)

        # Set gc_in_progress = 1, gc_complete = 0
        in_prog_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), in_prog_ptr)

        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), complete_ptr)

        # Signal GC thread to start
        cond_start = builder.load(self.gc_cond_start)
        builder.call(self.pthread_cond_signal, [cond_start])

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        builder.ret_void()

    def _implement_gc_scan_cross_heap(self):
        """Scan source heap for pointers into target heap and mark them.

        This is simplified - in practice we'd need to track address ranges.
        For now, we just mark everything in the source heap's allocation list.
        """
        func = self.gc_scan_cross_heap
        func.args[0].name = "source_heap"
        func.args[1].name = "target_heap"

        entry = func.append_basic_block("entry")
        scan_loop = func.append_basic_block("scan_loop")
        process_alloc = func.append_basic_block("process_alloc")
        next_alloc = func.append_basic_block("next_alloc")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        source_heap = func.args[0]
        # target_heap = func.args[1]  # Not used in simplified version

        # Get source heap's alloc list
        # source_heap: 0 = heap_a (index 3), 1 = heap_b (index 4)
        # Calculate field index: 3 + source_heap
        field_idx = builder.add(source_heap, ir.Constant(self.i64, 3))
        field_idx_32 = builder.trunc(field_idx, self.i32)

        # Get alloc_list from source heap
        # This is a bit tricky with dynamic index, use a simpler approach
        # We'll just scan both heaps' allocations and mark everything
        # (The full implementation would filter by heap)

        # For simplicity, scan the global gc_alloc_list which tracks all allocations
        # In the full dual-heap model, each heap would have its own list
        curr = builder.alloca(self.i8_ptr, name="curr")
        head = builder.load(self.gc_alloc_list)
        builder.store(head, curr)
        builder.branch(scan_loop)

        builder.position_at_end(scan_loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, process_alloc)

        builder.position_at_end(process_alloc)
        node = builder.bitcast(curr_val, self.alloc_node_type.as_pointer())

        # Get data pointer and mark the object
        data_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        data_ptr = builder.load(data_ptr_ptr)

        # Mark the object (gc_mark_object handles null and already-marked)
        builder.call(self.gc_mark_object, [data_ptr])

        builder.branch(next_alloc)

        builder.position_at_end(next_alloc)
        next_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_node = builder.load(next_ptr)
        builder.store(next_node, curr)
        builder.branch(scan_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_sweep_heap(self):
        """Sweep a specific heap region, freeing unmarked objects.

        For now, this delegates to the existing gc_sweep which handles
        the global allocation list. In a full implementation, each heap
        would have its own allocation list.
        """
        func = self.gc_sweep_heap
        func.args[0].name = "heap_idx"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # For now, just call the existing sweep
        builder.call(self.gc_sweep, [])

        builder.ret_void()

    def _implement_gc_thread_main(self):
        """GC thread main loop - waits for signal, collects, signals completion."""
        func = self.gc_thread_main
        func.args[0].name = "arg"

        entry = func.append_basic_block("entry")
        wait_loop = func.append_basic_block("wait_loop")
        check_work = func.append_basic_block("check_work")
        do_collection = func.append_basic_block("do_collection")
        signal_done = func.append_basic_block("signal_done")

        builder = ir.IRBuilder(entry)
        builder.branch(wait_loop)

        # Wait loop - check for work
        builder.position_at_end(wait_loop)

        # Lock mutex
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        builder.branch(check_work)

        builder.position_at_end(check_work)
        # Check if gc_in_progress == 1
        in_prog_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        in_progress = builder.load(in_prog_ptr)
        has_work = builder.icmp_unsigned("!=", in_progress, ir.Constant(self.i64, 0))

        # If no work, wait on condition variable
        with builder.if_then(builder.not_(has_work)):
            cond_start = builder.load(self.gc_cond_start)
            mutex_ptr2 = builder.load(self.gc_mutex)
            builder.call(self.pthread_cond_wait, [cond_start, mutex_ptr2])

        # Re-check after wait (spurious wakeup protection)
        in_progress2 = builder.load(in_prog_ptr)
        has_work2 = builder.icmp_unsigned("!=", in_progress2, ir.Constant(self.i64, 0))
        builder.cbranch(has_work2, do_collection, check_work)

        # Do collection
        builder.position_at_end(do_collection)

        # Get snapshot
        snapshot = builder.load(self.gc_snapshot)

        # Get which heap to collect
        heap_to_collect_ptr = builder.gep(snapshot, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        heap_to_collect = builder.load(heap_to_collect_ptr)

        # Unlock mutex during collection (collection is thread-safe)
        mutex_ptr3 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr3])

        # Phase 1: Mark from snapshot roots
        builder.call(self.gc_mark_from_snapshot, [snapshot])

        # Phase 2: Scan other heap for cross-heap pointers
        other_heap = builder.sub(ir.Constant(self.i64, 1), heap_to_collect)
        builder.call(self.gc_scan_cross_heap, [other_heap, heap_to_collect])

        # Phase 3: Sweep collected heap
        builder.call(self.gc_sweep_heap, [heap_to_collect])

        # Free snapshot
        roots_ptr = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        roots = builder.load(roots_ptr)
        roots_raw = builder.bitcast(roots, self.i8_ptr)
        builder.call(self.codegen.free, [roots_raw])
        snap_raw = builder.bitcast(snapshot, self.i8_ptr)
        builder.call(self.codegen.free, [snap_raw])

        builder.branch(signal_done)

        # Signal completion
        builder.position_at_end(signal_done)

        # Lock mutex to update state
        mutex_ptr4 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr4])

        # Set gc_in_progress = 0, gc_complete = 1
        builder.store(ir.Constant(self.i64, 0), in_prog_ptr)
        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), complete_ptr)

        # Signal completion
        cond_done = builder.load(self.gc_cond_done)
        builder.call(self.pthread_cond_signal, [cond_done])

        # Unlock and loop back
        mutex_ptr5 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr5])

        builder.branch(wait_loop)

        # Note: Thread never returns (runs until program exits)
        # The detached thread will be cleaned up when main exits

    def _implement_gc_async(self):
        """Trigger async GC (Phase 9: In single-threaded mode, just do synchronous collection).

        In the high watermark model for single-threaded execution, gc_async
        simply calls gc_collect since there's no separate GC thread.
        Multi-threaded implementation would spawn/signal a GC thread.
        """
        func = self.gc_async

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Phase 9: In single-threaded mode, just do synchronous collection
        builder.call(self.gc_collect, [])

        builder.ret_void()

    def _implement_gc_wait_for_completion(self):
        """Wait for current GC cycle to complete."""
        func = self.gc_wait_for_completion

        entry = func.append_basic_block("entry")
        check_complete = func.append_basic_block("check_complete")
        wait_for_done = func.append_basic_block("wait_for_done")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Lock mutex
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        builder.branch(check_complete)

        builder.position_at_end(check_complete)
        # Check if gc_complete == 1
        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        is_complete = builder.load(complete_ptr)
        completed = builder.icmp_unsigned("!=", is_complete, ir.Constant(self.i64, 0))
        builder.cbranch(completed, done, wait_for_done)

        builder.position_at_end(wait_for_done)
        # Wait on gc_cond_done
        cond_done = builder.load(self.gc_cond_done)
        mutex_ptr2 = builder.load(self.gc_mutex)
        builder.call(self.pthread_cond_wait, [cond_done, mutex_ptr2])
        builder.branch(check_complete)

        builder.position_at_end(done)
        # Unlock mutex
        mutex_ptr3 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr3])
        builder.ret_void()

    def _implement_gc_grow_heaps(self):
        """Double heap sizes when OOM - stub for now."""
        func = self.gc_grow_heaps

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # For now, this is a no-op
        # In a full implementation, this would:
        # 1. Allocate larger heap regions
        # 2. Copy existing allocations
        # 3. Update pointers
        # Since we're using malloc per-allocation (not bump allocator),
        # heap growth is implicit - we just keep allocating.

        builder.ret_void()

    # ========================================================================
    # Nursery Context Stubs (disabled in shadow stack GC)
    # ========================================================================
    # The old GC had nursery contexts for loop optimization.
    # With shadow stack GC, we disable this by returning null from create_context.
    # The codegen checks for null and skips nursery when creation fails.

    def _add_nursery_stubs(self):
        """Add stub functions for old nursery context API (disabled)"""
        # Type for heap context (just i8 for pointer compatibility)
        self.heap_context_type = self.i8

        # gc_create_context(size: i64, type: i64) -> i8*
        # Always returns null to disable nursery
        create_ty = ir.FunctionType(self.i8_ptr, [self.i64, self.i64])
        self.gc_create_context = ir.Function(self.module, create_ty, name="coex_gc_create_context")
        entry = self.gc_create_context.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        builder.ret(ir.Constant(self.i8_ptr, None))

        # gc_push_context(ctx: i8*) -> void
        # No-op
        push_ctx_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_push_context = ir.Function(self.module, push_ctx_ty, name="coex_gc_push_context")
        entry = self.gc_push_context.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        builder.ret_void()

        # gc_pop_context() -> void
        # No-op
        pop_ctx_ty = ir.FunctionType(self.void, [])
        self.gc_pop_context = ir.Function(self.module, pop_ctx_ty, name="coex_gc_pop_context")
        entry = self.gc_pop_context.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        builder.ret_void()

        # gc_destroy_context(ctx: i8*) -> void
        # No-op
        destroy_ctx_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_destroy_context = ir.Function(self.module, destroy_ctx_ty, name="coex_gc_destroy_context")
        entry = self.gc_destroy_context.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        builder.ret_void()

    # ============================================================
    # Phase 0: Debugging Infrastructure Implementations
    # ============================================================

    def _implement_gc_trace(self):
        """Implement trace output function based on current trace level"""
        func = self.gc_trace
        func.args[0].name = "level"
        func.args[1].name = "msg"

        entry = func.append_basic_block("entry")
        do_trace = func.append_basic_block("do_trace")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        level = func.args[0]
        msg = func.args[1]

        # Check if trace level is high enough
        current_level = builder.load(self.gc_trace_level)
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

    def _implement_gc_dump_stats(self):
        """Implement function to print current GC statistics"""
        func = self.gc_dump_stats

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
        total_allocs_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        total_allocs = builder.load(total_allocs_ptr)
        total_bytes_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
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

        collections_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        collections = builder.load(collections_ptr)
        marked_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)], inbounds=True)
        marked = builder.load(marked_ptr)
        swept_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
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

        last_gc_ns_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 16)], inbounds=True)
        last_gc_ns = builder.load(last_gc_ns_ptr)
        builder.call(printf, [timing_ptr, last_gc_ns])

        builder.ret_void()

    def _implement_gc_dump_heap(self):
        """Implement function to print all objects in the heap"""
        func = self.gc_dump_heap

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
        head = builder.load(self.gc_alloc_list)
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
        node = builder.bitcast(curr, self.alloc_node_type.as_pointer())

        # Get data pointer
        data_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        data_ptr = builder.load(data_ptr_ptr)

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr_local = builder.inttoptr(header_int, self.header_type.as_pointer())

        # Load header fields
        size_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        # Phase 1: type_id and flags are now i64
        type_id_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        flags_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)

        # Extract mark bit (Phase 1: flags is i64)
        marked = builder.and_(flags, ir.Constant(self.i64, self.FLAG_MARK_BIT))

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

    def _implement_gc_dump_roots(self):
        """Implement function to print all roots from shadow stack"""
        func = self.gc_dump_roots

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
        depth = builder.load(self.gc_frame_depth)
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
        frame_top = builder.load(self.gc_frame_top)
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
        frame = builder.bitcast(curr_frame_raw, self.gc_frame_type.as_pointer())

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

    def _implement_gc_dump_object(self):
        """Implement function to dump detailed info about a single object"""
        func = self.gc_dump_object
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
        header_int = builder.sub(ptr_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.header_type.as_pointer())

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

    def _implement_gc_validate_heap(self):
        """Implement heap validation function - returns 0 if valid, error code otherwise"""
        func = self.gc_validate_heap

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
        head = builder.load(self.gc_alloc_list)
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
        node = builder.bitcast(curr, self.alloc_node_type.as_pointer())

        # Get data pointer
        data_ptr_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        data_ptr = builder.load(data_ptr_ptr)

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.header_type.as_pointer())

        # Load header fields
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)

        builder.branch(check_size)

        # Check size >= HEADER_SIZE
        builder.position_at_end(check_size)
        header_size_const = ir.Constant(self.i64, self.HEADER_SIZE)
        size_valid = builder.icmp_unsigned(">=", size, header_size_const)
        builder.cbranch(size_valid, check_type, invalid_size)

        # Check type_id < MAX_TYPES (Phase 1: type_id is now i64)
        builder.position_at_end(check_type)
        max_types = ir.Constant(self.i64, self.MAX_TYPES)
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

    def _implement_gc_set_trace_level(self):
        """Implement function to set trace verbosity level"""
        func = self.gc_set_trace_level
        func.args[0].name = "level"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        level = func.args[0]
        builder.store(level, self.gc_trace_level)
        builder.ret_void()

    # ============================================================
    # Phase 3: High Watermark Tracking Implementation
    # ============================================================

    def _implement_gc_install_watermark(self):
        """Install watermark at current frame depth.

        When gc_pop_frame detects that frame_depth has returned to
        watermark_depth, it will trigger a garbage collection.

        This is the key mechanism for the high watermark GC:
        1. Program calls gc_install_watermark() at a safe point (e.g., top of main loop)
        2. Watermark is set to current frame depth
        3. Program continues, creating allocations
        4. When returning to the watermark depth (unwinding back to that point),
           GC is triggered to collect objects that are no longer reachable
        """
        func = self.gc_install_watermark

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Get current frame depth
        current_depth = builder.load(self.gc_frame_depth)

        # Store as watermark depth
        builder.store(current_depth, self.gc_watermark_depth)

        # Set watermark installed flag
        builder.store(ir.Constant(self.i1, 1), self.gc_watermark_installed)

        # Phase 6: Also install watermarks on all ThreadEntries
        builder.call(self.gc_install_watermarks, [])

        builder.ret_void()

    # ============================================================
    # Phase 5: Thread Registry Implementations
    # ============================================================

    def _implement_gc_register_thread(self):
        """Register a thread with the GC system.

        Allocates a ThreadEntry, initializes it, and adds it to the registry.
        For single-threaded mode, this is called once for the main thread.

        Returns pointer to the new ThreadEntry.
        """
        func = self.gc_register_thread

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        thread_id = func.args[0]

        # Allocate ThreadEntry (using malloc for simplicity, this is GC metadata)
        entry_size = ir.Constant(self.i64, 64)  # 8 fields * 8 bytes
        entry_ptr_raw = builder.call(self.codegen.malloc, [entry_size])
        entry_ptr = builder.bitcast(entry_ptr_raw, self.thread_entry_type.as_pointer())

        # Initialize fields:
        # 0: thread_id
        thread_id_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(thread_id, thread_id_ptr)

        # 1: shadow_stack_chain - point to gc_frame_top global
        # In single-threaded mode, all threads share gc_frame_top
        # Cast the global variable address to i8*
        frame_top_addr = builder.bitcast(self.gc_frame_top, self.i8_ptr)
        shadow_stack_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(frame_top_addr, shadow_stack_ptr)

        # 2: watermark = 0 (no watermark)
        watermark_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), watermark_ptr)

        # 3: watermark_active = 0
        watermark_active_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), watermark_active_ptr)

        # 4: stack_depth = 0
        stack_depth_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), stack_depth_ptr)

        # 5: blocked = 0
        blocked_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), blocked_ptr)

        # 6: alloc_buffer = null (future use)
        alloc_buffer_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), alloc_buffer_ptr)

        # 7: next = current registry head
        old_head = builder.load(self.gc_thread_registry)
        old_head_raw = builder.bitcast(old_head, self.i8_ptr)
        next_ptr = builder.gep(entry_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(old_head_raw, next_ptr)

        # Update registry head to point to new entry
        builder.store(entry_ptr, self.gc_thread_registry)

        # Increment thread count
        old_count = builder.load(self.gc_thread_count)
        new_count = builder.add(old_count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_thread_count)

        builder.ret(entry_ptr)

    def _implement_gc_unregister_thread(self):
        """Unregister a thread from the GC system.

        Removes the ThreadEntry from the registry and frees it.
        For single-threaded mode, this is called at program exit.
        """
        func = self.gc_unregister_thread

        entry = func.append_basic_block("entry")
        search_loop = func.append_basic_block("search_loop")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        thread_id = func.args[0]

        # prev = null, curr = registry head
        prev = builder.alloca(self.thread_entry_type.as_pointer(), name="prev")
        builder.store(ir.Constant(self.thread_entry_type.as_pointer(), None), prev)

        curr = builder.alloca(self.thread_entry_type.as_pointer(), name="curr")
        head = builder.load(self.gc_thread_registry)
        builder.store(head, curr)

        builder.branch(search_loop)

        # Search loop
        builder.position_at_end(search_loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        builder.cbranch(is_null, not_found, found)

        # Check if this is the thread we're looking for
        builder.position_at_end(found)
        curr_id_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        curr_id = builder.load(curr_id_ptr)
        is_match = builder.icmp_unsigned("==", curr_id, thread_id)

        # If match, remove from list
        remove_block = func.append_basic_block("remove")
        next_iter = func.append_basic_block("next_iter")
        builder.cbranch(is_match, remove_block, next_iter)

        # Remove from list
        builder.position_at_end(remove_block)
        # Get next pointer
        next_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        next_raw = builder.load(next_ptr)
        next_entry = builder.bitcast(next_raw, self.thread_entry_type.as_pointer())

        # Update prev->next or registry head
        prev_val = builder.load(prev)
        is_head = builder.icmp_unsigned("==", prev_val,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        update_head = func.append_basic_block("update_head")
        update_prev = func.append_basic_block("update_prev")
        after_update = func.append_basic_block("after_update")
        builder.cbranch(is_head, update_head, update_prev)

        # Update registry head
        builder.position_at_end(update_head)
        builder.store(next_entry, self.gc_thread_registry)
        builder.branch(after_update)

        # Update prev->next
        builder.position_at_end(update_prev)
        prev_next_ptr = builder.gep(prev_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(next_raw, prev_next_ptr)
        builder.branch(after_update)

        # Free the entry and decrement count
        builder.position_at_end(after_update)
        curr_raw = builder.bitcast(curr_val, self.i8_ptr)
        builder.call(self.codegen.free, [curr_raw])
        old_count = builder.load(self.gc_thread_count)
        new_count = builder.sub(old_count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_thread_count)
        builder.branch(done)

        # Move to next entry
        builder.position_at_end(next_iter)
        builder.store(curr_val, prev)
        next_ptr2 = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        next_raw2 = builder.load(next_ptr2)
        next_entry2 = builder.bitcast(next_raw2, self.thread_entry_type.as_pointer())
        builder.store(next_entry2, curr)
        builder.branch(search_loop)

        # Not found - do nothing
        builder.position_at_end(not_found)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_get_thread_entry(self):
        """Get the ThreadEntry for a given thread ID.

        Searches the registry for a matching thread_id.
        Returns pointer to ThreadEntry or null if not found.
        """
        func = self.gc_get_thread_entry

        entry = func.append_basic_block("entry")
        search_loop = func.append_basic_block("search_loop")
        check_match = func.append_basic_block("check_match")
        found = func.append_basic_block("found")
        next_iter = func.append_basic_block("next_iter")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        thread_id = func.args[0]

        # curr = registry head
        curr = builder.alloca(self.thread_entry_type.as_pointer(), name="curr")
        head = builder.load(self.gc_thread_registry)
        builder.store(head, curr)

        builder.branch(search_loop)

        # Search loop
        builder.position_at_end(search_loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        builder.cbranch(is_null, not_found, check_match)

        # Check if this is the thread we're looking for
        builder.position_at_end(check_match)
        curr_id_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        curr_id = builder.load(curr_id_ptr)
        is_match = builder.icmp_unsigned("==", curr_id, thread_id)
        builder.cbranch(is_match, found, next_iter)

        # Found - return entry
        builder.position_at_end(found)
        builder.ret(curr_val)

        # Move to next entry
        builder.position_at_end(next_iter)
        next_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        next_raw = builder.load(next_ptr)
        next_entry = builder.bitcast(next_raw, self.thread_entry_type.as_pointer())
        builder.store(next_entry, curr)
        builder.branch(search_loop)

        # Not found - return null
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(self.thread_entry_type.as_pointer(), None))

    def _implement_gc_get_current_thread_entry(self):
        """Get the ThreadEntry for the current (main) thread.

        In single-threaded mode, this just returns the first entry in the registry.
        In multi-threaded mode, this would use thread-local storage or thread ID lookup.
        """
        func = self.gc_get_current_thread_entry

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # In single-threaded mode, just return the registry head
        # (which is the only entry - the main thread)
        head = builder.load(self.gc_thread_registry)
        builder.ret(head)

    # ============================================================
    # Phase 6: Watermark Mechanism Enhancement Implementations
    # ============================================================

    def _implement_gc_install_watermarks(self):
        """Install watermarks on all registered threads.

        For each thread in the registry:
        1. Set thread.watermark = thread.stack_depth (or global gc_frame_depth)
        2. Set thread.watermark_active = 1

        This is called at the start of a GC cycle to mark the point
        where threads should block if they try to unwind past.
        """
        func = self.gc_install_watermarks

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        process = func.append_basic_block("process")
        next_thread = func.append_basic_block("next_thread")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # curr = registry head
        curr = builder.alloca(self.thread_entry_type.as_pointer(), name="curr")
        head = builder.load(self.gc_thread_registry)
        builder.store(head, curr)

        builder.branch(loop)

        # Loop through all threads
        builder.position_at_end(loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        builder.cbranch(is_null, done, process)

        # Process this thread - set watermark
        builder.position_at_end(process)

        # Get current global frame depth (in single-threaded mode, all threads share this)
        current_depth = builder.load(self.gc_frame_depth)

        # Set thread.watermark = current_depth
        watermark_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(current_depth, watermark_ptr)

        # Set thread.watermark_active = 1
        watermark_active_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), watermark_active_ptr)

        # Also sync stack_depth field
        stack_depth_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(current_depth, stack_depth_ptr)

        builder.branch(next_thread)

        # Move to next thread
        builder.position_at_end(next_thread)
        next_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        next_raw = builder.load(next_ptr)
        next_entry = builder.bitcast(next_raw, self.thread_entry_type.as_pointer())
        builder.store(next_entry, curr)
        builder.branch(loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_clear_watermarks(self):
        """Clear watermarks on all registered threads.

        For each thread in the registry:
        1. Set thread.watermark = 0
        2. Set thread.watermark_active = 0

        This is called at the end of a GC cycle to allow blocked threads
        to continue.
        """
        func = self.gc_clear_watermarks

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        process = func.append_basic_block("process")
        next_thread = func.append_basic_block("next_thread")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Also clear the global watermark state
        builder.store(ir.Constant(self.i64, 0), self.gc_watermark_depth)
        builder.store(ir.Constant(self.i1, 0), self.gc_watermark_installed)

        # curr = registry head
        curr = builder.alloca(self.thread_entry_type.as_pointer(), name="curr")
        head = builder.load(self.gc_thread_registry)
        builder.store(head, curr)

        builder.branch(loop)

        # Loop through all threads
        builder.position_at_end(loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        builder.cbranch(is_null, done, process)

        # Process this thread - clear watermark
        builder.position_at_end(process)

        # Set thread.watermark = 0
        watermark_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), watermark_ptr)

        # Set thread.watermark_active = 0
        watermark_active_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), watermark_active_ptr)

        builder.branch(next_thread)

        # Move to next thread
        builder.position_at_end(next_thread)
        next_ptr = builder.gep(curr_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        next_raw = builder.load(next_ptr)
        next_entry = builder.bitcast(next_raw, self.thread_entry_type.as_pointer())
        builder.store(next_entry, curr)
        builder.branch(loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_sync_thread_depth(self):
        """Sync global gc_frame_depth to current thread's ThreadEntry.stack_depth.

        This keeps the ThreadEntry in sync with the global frame depth counter.
        In single-threaded mode, there's only one thread so this is straightforward.
        In multi-threaded mode, each thread would update its own entry.
        """
        func = self.gc_sync_thread_depth

        entry = func.append_basic_block("entry")
        has_entry = func.append_basic_block("has_entry")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Get current thread entry
        thread_entry = builder.load(self.gc_thread_registry)
        is_null = builder.icmp_unsigned("==", thread_entry,
                                         ir.Constant(self.thread_entry_type.as_pointer(), None))
        builder.cbranch(is_null, done, has_entry)

        builder.position_at_end(has_entry)
        # Get current global frame depth
        current_depth = builder.load(self.gc_frame_depth)

        # Update thread.stack_depth
        stack_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(current_depth, stack_depth_ptr)

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    # ============================================================
    # Phase 7: First Trace Pass Implementations
    # ============================================================

    def _implement_gc_scan_roots_watermark(self):
        """Scan shadow stack up to watermark depth, marking all roots.

        This is the watermark-aware version of gc_scan_roots.
        It only scans frames at depth <= watermark_depth, skipping
        frames above the watermark (which contain objects allocated
        after watermark installation that are birth-marked).

        Returns the number of roots marked.
        """
        func = self.gc_scan_roots_watermark

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        check_depth = func.append_basic_block("check_depth")
        process_frame = func.append_basic_block("process_frame")
        root_loop = func.append_basic_block("root_loop")
        check_root = func.append_basic_block("check_root")
        mark_root = func.append_basic_block("mark_root")
        next_root = func.append_basic_block("next_root")
        next_frame = func.append_basic_block("next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Count of roots marked
        roots_marked = builder.alloca(self.i64, name="roots_marked")
        builder.store(ir.Constant(self.i64, 0), roots_marked)

        # Current frame depth (counting down from gc_frame_depth)
        curr_depth = builder.alloca(self.i64, name="curr_depth")
        total_depth = builder.load(self.gc_frame_depth)
        builder.store(total_depth, curr_depth)

        # Current frame pointer
        curr_frame = builder.alloca(self.i8_ptr, name="curr_frame")
        top = builder.load(self.gc_frame_top)
        builder.store(top, curr_frame)

        builder.branch(frame_loop)

        # Frame loop: while curr_frame != null
        builder.position_at_end(frame_loop)
        frame_val = builder.load(curr_frame)
        is_null = builder.icmp_unsigned("==", frame_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, check_depth)

        # Check if we've gone past the watermark depth
        builder.position_at_end(check_depth)
        depth_val = builder.load(curr_depth)
        watermark_depth = builder.load(self.gc_watermark_depth)
        wm_installed = builder.load(self.gc_watermark_installed)

        # gc_frame_depth starts at 0, increments on push, decrements on pop
        # When watermark is installed, watermark_depth = current gc_frame_depth
        # We want to scan frames that existed at watermark time (depth <= watermark_depth)
        # As we walk the stack, we're going from current top towards older frames
        # The frame at top has depth = gc_frame_depth, next frame has depth = gc_frame_depth-1, etc.
        #
        # If gc_frame_depth = 5 and watermark_depth = 3:
        # - Frame at depth 5: newer than watermark, skip
        # - Frame at depth 4: newer than watermark, skip
        # - Frame at depth 3: at watermark, scan
        # - Frame at depth 2: older than watermark, scan
        # etc.
        #
        # So we should scan when depth <= watermark_depth
        # And skip when depth > watermark_depth

        past_watermark = builder.icmp_unsigned(">", depth_val, watermark_depth)
        should_skip = builder.and_(wm_installed, past_watermark)
        builder.cbranch(should_skip, next_frame, process_frame)

        # Process frame - scan its roots
        builder.position_at_end(process_frame)
        # Re-load frame_val since we need it here
        frame_val_pf = builder.load(curr_frame)
        frame = builder.bitcast(frame_val_pf, self.gc_frame_type.as_pointer())

        # Get num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)

        # Get roots array
        roots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        roots = builder.load(roots_ptr_ptr)

        # Root index
        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)

        builder.branch(root_loop)

        # Root loop: for i in 0..num_roots
        builder.position_at_end(root_loop)
        i = builder.load(root_idx)
        done_roots = builder.icmp_unsigned(">=", i, num_roots)
        builder.cbranch(done_roots, next_frame, check_root)

        # Check if root is non-null
        builder.position_at_end(check_root)
        i_val = builder.load(root_idx)
        root_slot = builder.gep(roots, [i_val], inbounds=True)
        root_ptr = builder.load(root_slot)

        is_root_null = builder.icmp_unsigned("==", root_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_root_null, next_root, mark_root)

        # Mark non-null root
        builder.position_at_end(mark_root)
        builder.call(self.gc_mark_object, [root_ptr])

        # Increment roots marked count
        count = builder.load(roots_marked)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, roots_marked)

        builder.branch(next_root)

        # Next root
        builder.position_at_end(next_root)
        next_i = builder.add(i_val, ir.Constant(self.i64, 1))
        builder.store(next_i, root_idx)
        builder.branch(root_loop)

        # Move to next (older) frame - reload curr_frame since we may have
        # come from check_depth (skip) or root_loop (after processing)
        builder.position_at_end(next_frame)
        frame_val_nf = builder.load(curr_frame)
        frame_nf = builder.bitcast(frame_val_nf, self.gc_frame_type.as_pointer())
        parent_ptr = builder.gep(frame_nf, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, curr_frame)

        # Decrement depth as we go to older frames
        d = builder.load(curr_depth)
        new_d = builder.sub(d, ir.Constant(self.i64, 1))
        builder.store(new_d, curr_depth)

        builder.branch(frame_loop)

        # Return count of roots marked
        builder.position_at_end(done)
        result = builder.load(roots_marked)
        builder.ret(result)

    def _implement_gc_first_trace(self):
        """Orchestrate the first trace pass.

        This is the entry point for the trace phase of GC:
        1. Scan roots from shadow stack (respecting watermark)
        2. Mark all reachable objects
        3. Update statistics

        Objects are birth-marked, so we use mark bit inversion to
        identify garbage (objects with the OLD mark value).
        """
        func = self.gc_first_trace

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Call watermark-aware root scanning
        # This will mark all objects reachable from roots at or below watermark
        roots_marked = builder.call(self.gc_scan_roots_watermark, [])

        # Update statistics: objects_marked_last_cycle
        # Note: gc_mark_object increments this internally, but we track roots here
        # The stats field is at offset 40 in gc_stats
        # Actually, we should update a different stat - root count
        # For now, just call scan_roots_watermark

        builder.ret_void()

    def _implement_gc_count_roots(self):
        """Count total roots in shadow stack (for debugging/stats).

        Counts all non-null roots across all frames without marking them.
        """
        func = self.gc_count_roots

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        process_frame = func.append_basic_block("process_frame")
        root_loop = func.append_basic_block("root_loop")
        check_root = func.append_basic_block("check_root")
        count_root = func.append_basic_block("count_root")
        next_root = func.append_basic_block("next_root")
        next_frame = func.append_basic_block("next_frame")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Count of roots
        root_count = builder.alloca(self.i64, name="root_count")
        builder.store(ir.Constant(self.i64, 0), root_count)

        # Current frame pointer
        curr_frame = builder.alloca(self.i8_ptr, name="curr_frame")
        top = builder.load(self.gc_frame_top)
        builder.store(top, curr_frame)

        builder.branch(frame_loop)

        # Frame loop: while curr_frame != null
        builder.position_at_end(frame_loop)
        frame_val = builder.load(curr_frame)
        is_null = builder.icmp_unsigned("==", frame_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, process_frame)

        # Process frame
        builder.position_at_end(process_frame)
        frame = builder.bitcast(frame_val, self.gc_frame_type.as_pointer())

        # Get num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        num_roots = builder.load(num_roots_ptr)

        # Get roots array
        roots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        roots = builder.load(roots_ptr_ptr)

        # Root index
        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)

        builder.branch(root_loop)

        # Root loop: for i in 0..num_roots
        builder.position_at_end(root_loop)
        i = builder.load(root_idx)
        done_roots = builder.icmp_unsigned(">=", i, num_roots)
        builder.cbranch(done_roots, next_frame, check_root)

        # Check if root is non-null
        builder.position_at_end(check_root)
        i_val = builder.load(root_idx)
        root_slot = builder.gep(roots, [i_val], inbounds=True)
        root_ptr = builder.load(root_slot)

        is_root_null = builder.icmp_unsigned("==", root_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_root_null, next_root, count_root)

        # Count non-null root
        builder.position_at_end(count_root)
        count = builder.load(root_count)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, root_count)
        builder.branch(next_root)

        # Next root
        builder.position_at_end(next_root)
        next_i = builder.add(i_val, ir.Constant(self.i64, 1))
        builder.store(next_i, root_idx)
        builder.branch(root_loop)

        # Move to next frame
        builder.position_at_end(next_frame)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, curr_frame)
        builder.branch(frame_loop)

        # Return count
        builder.position_at_end(done)
        result = builder.load(root_count)
        builder.ret(result)
