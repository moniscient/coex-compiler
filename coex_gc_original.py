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

# Import diagnostics submodule
from coex_gc.diagnostics import GCDiagnostics

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

    # Handle table constants (Handle-Based GC)
    INITIAL_HANDLE_TABLE_SIZE = 1048576  # 1M handles (8MB for pointers)

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
    TYPE_JSON = 14           # JSON value (tagged union: i8 tag, i64 value)
    TYPE_FIRST_USER = 15     # First ID for user-defined types

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

        # Handle table globals (Handle-Based GC - Phase 1)
        self.gc_handle_table = None       # i8** - array of object pointers
        self.gc_handle_table_size = None  # i64 - current table capacity
        self.gc_handle_free_list = None   # i64 - head of free slot chain (0 = empty)
        self.gc_next_handle = None        # i64 - next fresh handle to allocate
        self.gc_handle_retired_list = None  # i64 - handles pending retirement (MI-6)

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

        # Handle management functions (Handle-Based GC - Phase 1)
        self.gc_handle_alloc = None       # Allocate handle slot, returns i64 handle
        self.gc_handle_free = None        # Return handle to free list
        self.gc_handle_deref = None       # Dereference handle to get i8* pointer
        self.gc_handle_store = None       # Store pointer in handle slot
        self.gc_handle_table_grow = None  # Double table size
        self.gc_handle_retire = None      # Add handle to retired list (MI-6 deferred reclamation)
        self.gc_promote_retired_handles = None  # Move retired handles to free list

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
        self.gc_fragmentation_report = None   # Analyze heap fragmentation
        self.gc_dump_handle_table = None      # Dump handle table state
        self.gc_dump_shadow_stacks = None     # Dump shadow stack frames

    def generate_gc_runtime(self):
        """Generate all GC runtime structures and functions"""
        self._create_types()
        self._create_globals()
        self._declare_functions()
        self._register_builtin_types()

        # Initialize diagnostics module (after functions are declared)
        self._diagnostics = GCDiagnostics(self)

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
        # Phase 0: Debugging infrastructure (delegated to diagnostics module)
        self._diagnostics.implement_gc_trace()
        self._diagnostics.implement_gc_dump_stats()
        self._diagnostics.implement_gc_dump_heap()
        self._diagnostics.implement_gc_dump_roots()
        self._diagnostics.implement_gc_dump_object()
        self._diagnostics.implement_gc_validate_heap()
        self._diagnostics.implement_gc_set_trace_level()
        # Additional diagnostic functions (delegated to diagnostics module)
        self._diagnostics.implement_gc_fragmentation_report()
        self._diagnostics.implement_gc_dump_handle_table()
        self._diagnostics.implement_gc_dump_shadow_stacks()
        # Handle-Based GC - Phase 1: Handle management functions
        self._implement_gc_handle_table_grow()
        self._implement_gc_handle_alloc()
        self._implement_gc_handle_free()
        self._implement_gc_handle_deref()
        self._implement_gc_handle_store()
        self._implement_gc_ptr_to_handle()
        # MI-6: Deferred reclamation functions
        self._implement_gc_handle_retire()
        self._implement_gc_promote_retired_handles()

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

        # Allocation node: { i8* next, i64 handle, i64 size }
        # Linked list of all allocations for sweep
        # Phase 7: Changed from i8* data to i64 handle for handle-based GC
        self.alloc_node_type = ir.LiteralStructType([
            self.i8_ptr,  # next allocation node
            self.i64,     # handle to the object (instead of data pointer)
            self.i64,     # size of allocation
        ])

        # GC Frame: { i8* parent, i64 num_roots, i64* handle_slots }
        # Shadow stack frame for root tracking (Phase 3: handles instead of pointers)
        self.gc_frame_type = ir.LiteralStructType([
            self.i8_ptr,      # parent frame pointer
            self.i64,         # number of roots
            self.i64_ptr,     # pointer to handle slots array (array of i64 handles)
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

        # RootSnapshot: { i64* handle_slots, i64 count, i64 heap_to_collect }
        # Captures shadow stack state at swap time
        # Phase 3: Uses i64* for handle slots instead of i8** for pointer slots
        self.root_snapshot_type = ir.LiteralStructType([
            self.i64_ptr,  # handle_slots - array of handle values
            self.i64,      # count - number of handles captured
            self.i64,      # heap_to_collect - 0 for A, 1 for B
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
        # Handle Table Globals (Handle-Based GC - Phase 1)
        # ============================================================
        # Every heap object is referenced through a handle (i64 index).
        # gc_handle_table[handle] contains the actual i8* pointer.
        # Handle 0 is reserved for null.

        # Pointer to handle table (array of i8* pointers)
        # SHARED - atomic reads, mutex for writes/growth
        self.gc_handle_table = ir.GlobalVariable(self.module, self.i8_ptr_ptr, name="gc_handle_table")
        self.gc_handle_table.initializer = ir.Constant(self.i8_ptr_ptr, None)
        self.gc_handle_table.linkage = 'internal'

        # Current table capacity
        self.gc_handle_table_size = ir.GlobalVariable(self.module, self.i64, name="gc_handle_table_size")
        self.gc_handle_table_size.initializer = ir.Constant(self.i64, 0)
        self.gc_handle_table_size.linkage = 'internal'

        # Head of free list (0 = empty, non-zero = first free slot)
        # Free slots store next free index in the slot itself
        self.gc_handle_free_list = ir.GlobalVariable(self.module, self.i64, name="gc_handle_free_list")
        self.gc_handle_free_list.initializer = ir.Constant(self.i64, 0)
        self.gc_handle_free_list.linkage = 'internal'

        # Next fresh handle to allocate (starts at 1, handle 0 = null)
        self.gc_next_handle = ir.GlobalVariable(self.module, self.i64, name="gc_next_handle")
        self.gc_next_handle.initializer = ir.Constant(self.i64, 1)
        self.gc_next_handle.linkage = 'internal'

        # Retired list for deferred reclamation (MI-6)
        # Handles freed in cycle N become available in cycle N+2
        # This prevents use-after-free when concurrent GC is enabled
        self.gc_handle_retired_list = ir.GlobalVariable(self.module, self.i64, name="gc_handle_retired_list")
        self.gc_handle_retired_list.initializer = ir.Constant(self.i64, 0)
        self.gc_handle_retired_list.linkage = 'internal'

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

        # gc_alloc(size: i64, type_id: i32) -> i64 (handle)
        # Phase 2: Returns handle (i64) instead of raw pointer
        # Use gc_handle_deref to get the actual pointer
        gc_alloc_ty = ir.FunctionType(self.i64, [self.i64, self.i32])
        self.gc_alloc = ir.Function(self.module, gc_alloc_ty, name="coex_gc_alloc")

        # gc_collect() -> void
        gc_collect_ty = ir.FunctionType(self.void, [])
        self.gc_collect = ir.Function(self.module, gc_collect_ty, name="coex_gc_collect")

        # gc_push_frame(num_roots: i64, handle_slots: i64*) -> i8*
        # Returns pointer to frame (for passing to pop_frame)
        # Phase 3: takes array of i64 handle slots instead of i8* pointer slots
        gc_push_ty = ir.FunctionType(self.i8_ptr, [self.i64, self.i64_ptr])
        self.gc_push_frame = ir.Function(self.module, gc_push_ty, name="coex_gc_push_frame")

        # gc_pop_frame(frame: i8*) -> void
        gc_pop_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_pop_frame = ir.Function(self.module, gc_pop_ty, name="coex_gc_pop_frame")

        # gc_set_root(slots: i64*, index: i64, handle: i64) -> void
        # Update a root slot with a handle value
        # Phase 3: stores i64 handles instead of i8* pointers
        gc_set_root_ty = ir.FunctionType(self.void, [self.i64_ptr, self.i64, self.i64])
        self.gc_set_root = ir.Function(self.module, gc_set_root_ty, name="coex_gc_set_root")

        # gc_mark_object(handle: i64) -> void
        # Takes a handle index and marks the referenced object as live
        gc_mark_ty = ir.FunctionType(self.void, [self.i64])
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

        # gc_fragmentation_report() -> void
        # Analyze and print heap fragmentation statistics
        gc_fragmentation_report_ty = ir.FunctionType(self.void, [])
        self.gc_fragmentation_report = ir.Function(self.module, gc_fragmentation_report_ty, name="coex_gc_fragmentation_report")

        # gc_dump_handle_table() -> void
        # Print handle table state (allocated, free, retired handles)
        gc_dump_handle_table_ty = ir.FunctionType(self.void, [])
        self.gc_dump_handle_table = ir.Function(self.module, gc_dump_handle_table_ty, name="coex_gc_dump_handle_table")

        # gc_dump_shadow_stacks() -> void
        # Print all shadow stack frames and their roots
        gc_dump_shadow_stacks_ty = ir.FunctionType(self.void, [])
        self.gc_dump_shadow_stacks = ir.Function(self.module, gc_dump_shadow_stacks_ty, name="coex_gc_dump_shadow_stacks")

        # ============================================================
        # Handle Management Function Declarations (Handle-Based GC - Phase 1)
        # ============================================================

        # gc_handle_alloc() -> i64
        # Allocate a handle slot (from free list or bump allocator)
        # Returns handle index (never 0, which represents null)
        gc_handle_alloc_ty = ir.FunctionType(self.i64, [])
        self.gc_handle_alloc = ir.Function(self.module, gc_handle_alloc_ty, name="coex_gc_handle_alloc")

        # gc_handle_free(handle: i64) -> void
        # Return a handle to the free list (called during sweep)
        gc_handle_free_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_handle_free = ir.Function(self.module, gc_handle_free_ty, name="coex_gc_handle_free")

        # gc_handle_deref(handle: i64) -> i8*
        # Dereference a handle to get the object pointer
        # Returns null if handle is 0
        gc_handle_deref_ty = ir.FunctionType(self.i8_ptr, [self.i64])
        self.gc_handle_deref = ir.Function(self.module, gc_handle_deref_ty, name="coex_gc_handle_deref")

        # gc_handle_store(handle: i64, ptr: i8*) -> void
        # Store a pointer in a handle slot
        gc_handle_store_ty = ir.FunctionType(self.void, [self.i64, self.i8_ptr])
        self.gc_handle_store = ir.Function(self.module, gc_handle_store_ty, name="coex_gc_handle_store")

        # gc_handle_table_grow() -> void
        # Double the handle table size (called when table exhausted)
        gc_handle_table_grow_ty = ir.FunctionType(self.void, [])
        self.gc_handle_table_grow = ir.Function(self.module, gc_handle_table_grow_ty, name="coex_gc_handle_table_grow")

        # gc_ptr_to_handle(ptr: i8*) -> i64
        # Get the handle for an object from its pointer (reads header's forward field)
        # Returns 0 if ptr is null
        gc_ptr_to_handle_ty = ir.FunctionType(self.i64, [self.i8_ptr])
        self.gc_ptr_to_handle = ir.Function(self.module, gc_ptr_to_handle_ty, name="coex_gc_ptr_to_handle")

        # gc_handle_retire(handle: i64) -> void
        # Add handle to retired list for deferred reclamation (MI-6)
        # Handles go to retired list during sweep, promoted to free list next cycle
        gc_handle_retire_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_handle_retire = ir.Function(self.module, gc_handle_retire_ty, name="coex_gc_handle_retire")

        # gc_promote_retired_handles() -> void
        # Move all retired handles to the free list (called at start of GC cycle)
        gc_promote_retired_ty = ir.FunctionType(self.void, [])
        self.gc_promote_retired_handles = ir.Function(self.module, gc_promote_retired_ty, name="coex_gc_promote_retired_handles")

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
        # JSON: { i8 tag, i64 value } = 16 bytes (with padding)
        # The value field at offset 8 may be a pointer (for string/array/object)
        # We use gc_mark_json to handle the dynamic tracing based on tag
        self.type_info[self.TYPE_JSON] = {'size': 16, 'ref_offsets': []}
        self.type_descriptors['Json'] = self.TYPE_JSON

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
        # Initialize Handle Table (Handle-Based GC - Phase 1)
        # ============================================================
        # Allocate initial handle table: 1M slots * 8 bytes = 8MB
        # Handle 0 is reserved for null, so we start allocating at handle 1

        table_size = ir.Constant(self.i64, self.INITIAL_HANDLE_TABLE_SIZE)
        table_bytes = builder.mul(table_size, ir.Constant(self.i64, 8))  # 8 bytes per pointer
        table_ptr = builder.call(self.codegen.malloc, [table_bytes])
        table_ptr_typed = builder.bitcast(table_ptr, self.i8_ptr_ptr)
        builder.store(table_ptr_typed, self.gc_handle_table)
        builder.store(table_size, self.gc_handle_table_size)

        # Initialize all slots to NULL (memset to 0)
        # This ensures dereferencing an uninitialized slot returns NULL
        builder.call(self.codegen.memset, [
            table_ptr,
            ir.Constant(self.i8, 0),
            table_bytes
        ])

        # Reset handle allocation state
        builder.store(ir.Constant(self.i64, 0), self.gc_handle_free_list)  # Empty free list
        builder.store(ir.Constant(self.i64, 1), self.gc_next_handle)  # Start at handle 1

        builder.ret_void()

    def _implement_gc_push_frame(self):
        """Push a new frame onto the shadow stack.

        Phase 3: Takes i64* handle_slots instead of i8** roots.
        """
        func = self.gc_push_frame
        func.args[0].name = "num_roots"
        func.args[1].name = "handle_slots"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        num_roots = func.args[0]
        handle_slots = func.args[1]

        # Allocate frame struct (24 bytes: parent + num_roots + handle_slots_ptr)
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

        # Set handle_slots pointer (Phase 3: i64* instead of i8**)
        slots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(handle_slots, slots_ptr_ptr)

        # Update frame top
        builder.store(raw_frame, self.gc_frame_top)

        # Increment frame depth
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.add(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

        builder.ret(raw_frame)

    def _implement_gc_pop_frame(self):
        """Pop a frame from the shadow stack."""
        func = self.gc_pop_frame
        func.args[0].name = "frame_ptr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        frame_ptr = func.args[0]
        frame = builder.bitcast(frame_ptr, self.gc_frame_type.as_pointer())

        # Get parent and set as new top
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, self.gc_frame_top)

        # Decrement frame depth
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.sub(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

        # Free the frame
        builder.call(self.codegen.free, [frame_ptr])

        builder.ret_void()

    def _implement_gc_set_root(self):
        """Set a root slot to a handle value.

        Phase 3: Takes i64* slots and stores i64 handle values.
        """
        func = self.gc_set_root
        func.args[0].name = "slots"
        func.args[1].name = "index"
        func.args[2].name = "handle"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        slots = func.args[0]
        index = func.args[1]
        handle = func.args[2]

        # slots[index] = handle
        slot_ptr = builder.gep(slots, [index], inbounds=True)
        builder.store(handle, slot_ptr)

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
        # 2. gc_safepoint() at function entry
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

        # Compute user_ptr (after header)
        block_int = builder.ptrtoint(block, self.i64)
        user_ptr_int = builder.add(block_int, header_size)
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)

        # Phase 7: Allocate handle and store pointer in handle table
        # Then store handle in alloc_node (instead of user_ptr)
        handle = builder.call(self.gc_handle_alloc, [])
        builder.call(self.gc_handle_store, [handle, user_ptr])

        # Phase 8 fix: Store handle in header's forward field for ptr->handle lookup
        # This allows gc_ptr_to_handle to recover the handle from a pointer
        builder.store(handle, forward_ptr)

        # node->handle = handle (Phase 7: store handle instead of data pointer)
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(handle, handle_ptr)

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

        # Phase 7: Handle already created and stored in alloc_node above
        # Return handle (i64) instead of raw pointer
        builder.ret(handle)

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
        # Convert pointer to handle for gc_mark_object
        untagged_handle = builder.call(self.gc_ptr_to_handle, [untagged_ptr])
        builder.call(self.gc_mark_object, [untagged_handle])

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
            # Convert pointer to handle for gc_mark_object
            key_handle = builder.call(self.gc_ptr_to_handle, [key_as_ptr])
            builder.call(self.gc_mark_object, [key_handle])
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
            # Convert pointer to handle for gc_mark_object
            value_handle = builder.call(self.gc_ptr_to_handle, [value_as_ptr])
            builder.call(self.gc_mark_object, [value_handle])
        builder.branch(after_value)

        builder.position_at_end(after_value)
        builder.branch(done)

        # Handle internal node
        builder.position_at_end(is_internal)
        # Mark the node itself (convert pointer to handle)
        root_handle = builder.call(self.gc_ptr_to_handle, [root])
        builder.call(self.gc_mark_object, [root_handle])

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
        # Convert pointer to handle for gc_mark_object
        children_handle = builder.call(self.gc_ptr_to_handle, [children_as_i8])
        builder.call(self.gc_mark_object, [children_handle])

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

        Handle-based signature: Takes i64 handle and dereferences to get pointer.
        """
        func = self.gc_mark_object
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        deref_handle = func.append_basic_block("deref_handle")
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
        mark_json = func.append_basic_block("mark_json")
        mark_json_ptr = func.append_basic_block("mark_json_ptr")
        mark_json_done = func.append_basic_block("mark_json_done")
        pv_node_loop = func.append_basic_block("pv_node_loop")
        pv_node_check = func.append_basic_block("pv_node_check")
        pv_node_mark_child = func.append_basic_block("pv_node_mark_child")
        pv_node_next = func.append_basic_block("pv_node_next")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        handle = func.args[0]

        # Null handle check (handle == 0 means no object)
        is_null_handle = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_handle, done, deref_handle)

        # Dereference handle to get pointer
        builder.position_at_end(deref_handle)
        ptr = builder.call(self.gc_handle_deref, [handle])

        # Null pointer check (defensive - shouldn't happen for valid handles)
        is_null_ptr = builder.icmp_unsigned("==", ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null_ptr, done, get_header)

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
        # Phase 6: User type fields now store i64 handles, not pointers
        field_addr = builder.inttoptr(field_addr_int, self.i64_ptr)
        field_handle = builder.load(field_addr)
        # gc_mark_object now takes handle directly
        builder.call(func, [field_handle])
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
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON), mark_json)

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
        # List struct: { i64 root (0), i64 len (1), i64 depth (2), i64 tail (3), i64 tail_len (4), i64 elem_size (5) }
        # Root and tail store raw pointers as i64 (via ptrtoint), need inttoptr to get pointers
        builder.position_at_end(mark_list)
        list_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i64, self.i64]).as_pointer()
        list_typed = builder.bitcast(ptr, list_ptr_type)
        # Mark root
        root_i64_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        root_i64 = builder.load(root_i64_ptr)
        root_ptr = builder.inttoptr(root_i64, self.i8_ptr)  # Convert i64 to pointer
        root_handle = builder.call(self.gc_ptr_to_handle, [root_ptr])
        builder.call(func, [root_handle])  # Recursive call
        # Mark tail
        tail_i64_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        tail_i64 = builder.load(tail_i64_ptr)
        tail_ptr = builder.inttoptr(tail_i64, self.i8_ptr)  # Convert i64 to pointer
        tail_handle = builder.call(self.gc_ptr_to_handle, [tail_ptr])
        builder.call(func, [tail_handle])  # Recursive call
        builder.branch(done)

        # Mark Array: owner pointer at field 0
        # Array struct: { i64 owner (0), i64 offset (1), i64 len (2), i64 cap (3), i64 elem_size (4) }
        # Owner stores raw pointer as i64 (via ptrtoint), need inttoptr to get pointer
        builder.position_at_end(mark_array)
        array_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i64]).as_pointer()
        array_typed = builder.bitcast(ptr, array_ptr_type)
        owner_i64_ptr = builder.gep(array_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        owner_i64 = builder.load(owner_i64_ptr)
        owner_ptr = builder.inttoptr(owner_i64, self.i8_ptr)  # Convert i64 to pointer
        owner_handle = builder.call(self.gc_ptr_to_handle, [owner_ptr])
        builder.call(func, [owner_handle])  # Recursive call - marks the data buffer
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
        # String struct: { i64 owner (0), i64 offset (1), i64 len (2), i64 size (3) }
        # Owner stores raw pointer as i64 (via ptrtoint), need inttoptr to get pointer
        builder.position_at_end(mark_string)
        string_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64]).as_pointer()
        string_typed = builder.bitcast(ptr, string_ptr_type)
        owner_i64_ptr = builder.gep(string_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        owner_i64 = builder.load(owner_i64_ptr)
        owner_ptr = builder.inttoptr(owner_i64, self.i8_ptr)  # Convert i64 to pointer
        str_owner_handle = builder.call(self.gc_ptr_to_handle, [owner_ptr])
        builder.call(func, [str_owner_handle])  # Recursive call - marks the data buffer
        builder.branch(done)

        # Mark Channel: buffer pointer at offset 32 (4th i64 field)
        builder.position_at_end(mark_channel)
        channel_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i8_ptr]).as_pointer()
        channel_typed = builder.bitcast(ptr, channel_ptr_type)
        buffer_ptr_ptr = builder.gep(channel_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        buffer_ptr = builder.load(buffer_ptr_ptr)
        buffer_handle = builder.call(self.gc_ptr_to_handle, [buffer_ptr])
        builder.call(func, [buffer_handle])  # Recursive call
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
        # Convert pointer to handle for recursive call
        child_handle = builder.call(self.gc_ptr_to_handle, [child_to_mark])
        builder.call(func, [child_handle])  # Recursive call to gc_mark_object
        builder.branch(pv_node_next)

        # Increment index and continue
        builder.position_at_end(pv_node_next)
        curr_idx = builder.load(pv_idx)
        next_idx = builder.add(curr_idx, ir.Constant(self.i64, 1))
        builder.store(next_idx, pv_idx)
        builder.branch(pv_node_loop)

        # Mark JSON: check tag, if string/array/object then mark the value pointer
        # JSON struct: { i8 tag (0), i64 value (1) }
        # Tags 4 (string), 5 (array), 6 (object) have pointer values
        builder.position_at_end(mark_json)
        json_ptr_type = ir.LiteralStructType([self.i8, self.i64]).as_pointer()
        json_typed = builder.bitcast(ptr, json_ptr_type)
        json_tag_ptr = builder.gep(json_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        json_tag = builder.load(json_tag_ptr)
        # Check if tag >= 4 (string, array, or object - all have pointer values)
        is_ptr_type = builder.icmp_unsigned(">=", json_tag, ir.Constant(self.i8, 4))
        builder.cbranch(is_ptr_type, mark_json_ptr, mark_json_done)

        # Mark the pointer value
        builder.position_at_end(mark_json_ptr)
        # Reload json pointer (SSA requirement)
        json_typed2 = builder.bitcast(ptr, json_ptr_type)
        json_value_ptr = builder.gep(json_typed2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        json_value_i64 = builder.load(json_value_ptr)
        json_child_ptr = builder.inttoptr(json_value_i64, self.i8_ptr)
        json_child_handle = builder.call(self.gc_ptr_to_handle, [json_child_ptr])
        builder.call(func, [json_child_handle])  # Recursive call to mark the child
        builder.branch(mark_json_done)

        # JSON marking done
        builder.position_at_end(mark_json_done)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_scan_roots(self):
        """Scan shadow stack and mark all roots.

        Phase 3: Slots now contain i64 handles instead of i8* pointers.
        We load the handle, deref to get pointer, then mark.
        """
        func = self.gc_scan_roots

        entry = func.append_basic_block("entry")
        frame_loop = func.append_basic_block("frame_loop")
        process_frame = func.append_basic_block("process_frame")
        root_loop = func.append_basic_block("root_loop")
        check_handle = func.append_basic_block("check_handle")
        do_mark = func.append_basic_block("do_mark")
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

        # Get handle_slots array (Phase 3: now i64* instead of i8**)
        slots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        slots = builder.load(slots_ptr_ptr)

        # Root index
        root_idx = builder.alloca(self.i64, name="root_idx")
        builder.store(ir.Constant(self.i64, 0), root_idx)

        builder.branch(root_loop)

        # Root loop: for i in 0..num_roots
        builder.position_at_end(root_loop)
        i = builder.load(root_idx)
        done_roots = builder.icmp_unsigned(">=", i, num_roots)
        builder.cbranch(done_roots, next_frame, check_handle)

        # Check handle (Phase 3: load i64 handle from slot)
        builder.position_at_end(check_handle)
        i_val = builder.load(root_idx)
        slot_ptr = builder.gep(slots, [i_val], inbounds=True)
        handle = builder.load(slot_ptr)

        # Skip if handle is 0 (null handle)
        is_null_handle = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_handle, next_root, do_mark)

        # Mark the object via its handle
        # gc_mark_object now takes i64 handle directly
        builder.position_at_end(do_mark)
        builder.call(self.gc_mark_object, [handle])
        builder.branch(next_root)

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

        # Phase 7: Store current object's handle for use across blocks
        current_handle = builder.alloca(self.i64, name="current_handle")
        builder.store(ir.Constant(self.i64, 0), current_handle)

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

        # Phase 7: Get handle from node (field 1 is now i64 handle, not i8* data)
        handle_field_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_field_ptr)
        # Store handle for use in unmarked block
        builder.store(obj_handle, current_handle)

        # Phase 7: Dereference handle to get data pointer
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

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
        # MI-6: Retire the handle (add to retired list for deferred reclamation)
        # Handle becomes available for reuse after the next GC cycle
        freed_handle = builder.load(current_handle)
        builder.call(self.gc_handle_retire, [freed_handle])
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

        Phase 9: Collection Orchestration with MI-6 Deferred Reclamation
        This implements the synchronous collection cycle:
        1. Check if GC enabled and not already in progress
        2. Set gc_in_progress = 1
        3. Promote retired handles from previous cycle to free list (MI-6)
        4. Flip mark value for birth-marking
        5. Mark phase: scan roots and mark reachable objects
        6. Sweep phase: free unmarked objects (retire handles, don't free immediately)
        7. Update statistics
        8. Set gc_in_progress = 0

        MI-6 Deferred Reclamation:
        Handles swept in cycle N are added to the retired list, not the free list.
        At the start of cycle N+1, retired handles are promoted to the free list.
        This ensures handles are not reused until at least one full cycle after being freed.
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

        # MI-6: Promote retired handles from previous cycle to free list
        # This makes handles retired in cycle N-1 available for reuse in cycle N
        builder.call(self.gc_promote_retired_handles, [])

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
        """Create an array of handle slots on the stack.

        Phase 3: Returns pointer to i64[] array (handle slots) instead of i8*[].
        Returns i64* pointer to the first handle slot.
        """
        if num_roots == 0:
            return ir.Constant(self.i64_ptr, None)

        # Allocate array of i64 handles on stack (Phase 3)
        slots_type = ir.ArrayType(self.i64, num_roots)
        slots_alloca = builder.alloca(slots_type, name="gc_handle_slots")

        # Zero-initialize (handle 0 = null)
        for i in range(num_roots):
            slot_ptr = builder.gep(slots_alloca, [
                ir.Constant(self.i32, 0),
                ir.Constant(self.i32, i)
            ], inbounds=True)
            builder.store(ir.Constant(self.i64, 0), slot_ptr)

        # Cast to i64*
        return builder.bitcast(slots_alloca, self.i64_ptr)

    def push_frame_inline(self, builder: ir.IRBuilder, num_roots: int, handle_slots: ir.Value) -> ir.Value:
        """Push a GC frame using stack allocation (avoids malloc fragmentation).

        Phase 3: Takes i64* handle_slots instead of i8** roots.
        Allocates the frame structure on the stack instead of heap.
        Returns pointer to the stack-allocated frame for later pop.
        """
        # Allocate frame struct on stack (parent: i8*, num_roots: i64, handle_slots: i64*)
        frame_alloca = builder.alloca(self.gc_frame_type, name="gc_frame")

        # Get old top
        old_top = builder.load(self.gc_frame_top)

        # Set parent = old_top
        parent_ptr = builder.gep(frame_alloca, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(old_top, parent_ptr)

        # Set num_roots
        num_roots_ptr = builder.gep(frame_alloca, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(ir.Constant(self.i64, num_roots), num_roots_ptr)

        # Set handle_slots pointer (Phase 3: i64* instead of i8**)
        slots_ptr_ptr = builder.gep(frame_alloca, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(handle_slots, slots_ptr_ptr)

        # Update gc_frame_top to point to this frame
        raw_frame = builder.bitcast(frame_alloca, self.i8_ptr)
        builder.store(raw_frame, self.gc_frame_top)

        # Increment frame depth
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.add(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

        return raw_frame

    def pop_frame_inline(self, builder: ir.IRBuilder, frame: ir.Value):
        """Pop a GC frame (stack-allocated version - no free needed)."""
        frame_typed = builder.bitcast(frame, self.gc_frame_type.as_pointer())

        # Get parent and set as new top
        parent_ptr = builder.gep(frame_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, self.gc_frame_top)

        # Decrement frame depth
        depth = builder.load(self.gc_frame_depth)
        new_depth = builder.sub(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.gc_frame_depth)

    def push_frame(self, builder: ir.IRBuilder, num_roots: int, handle_slots: ir.Value) -> ir.Value:
        """Push a GC frame. Returns frame pointer for later pop.

        Phase 3: Takes i64* handle_slots instead of i8** roots.
        Uses stack-allocated frames to avoid malloc fragmentation from
        millions of small allocations.
        """
        return self.push_frame_inline(builder, num_roots, handle_slots)

    def pop_frame(self, builder: ir.IRBuilder, frame: ir.Value):
        """Pop a GC frame.

        Uses stack-allocated frames - no free needed.
        """
        self.pop_frame_inline(builder, frame)

    def set_root(self, builder: ir.IRBuilder, handle_slots: ir.Value, index: int, value: ir.Value):
        """Set a root slot to a handle value.

        Phase 4 fix: Takes i64* handle_slots and stores i64 handles.
        When given a pointer, we call gc_ptr_to_handle to recover the actual
        handle index from the object's header. This ensures gc_scan_roots can
        use gc_handle_deref to properly dereference handles during collection.
        """
        index_val = ir.Constant(self.i64, index)
        # Convert value to i64 handle
        if value.type == self.i64:
            # Already a handle (i64)
            handle = value
        elif isinstance(value.type, ir.PointerType):
            # Convert pointer to handle using gc_ptr_to_handle
            # This reads the handle from the object's header (forward field)
            ptr_as_i8 = builder.bitcast(value, self.i8_ptr)
            handle = builder.call(self.gc_ptr_to_handle, [ptr_as_i8])
        elif isinstance(value.type, ir.IntType) and value.type.width == 64:
            handle = value
        else:
            # Try bitcast/conversion for other types
            if isinstance(value.type, ir.IntType):
                handle = builder.zext(value, self.i64)
            else:
                # Fallback: convert to pointer then get handle
                ptr_as_i8 = builder.bitcast(value, self.i8_ptr)
                handle = builder.call(self.gc_ptr_to_handle, [ptr_as_i8])
        builder.call(self.gc_set_root, [handle_slots, index_val, handle])

    def alloc_with_deref(self, builder: ir.IRBuilder, size: ir.Value, type_id: ir.Value) -> ir.Value:
        """Allocate memory and return the pointer (backward compatibility helper).

        Phase 2: gc_alloc now returns a handle (i64). This helper calls gc_alloc
        to get the handle, then immediately dereferences it to get the pointer.
        This maintains backward compatibility with existing code that expects
        gc_alloc to return a pointer.

        Args:
            builder: LLVM IR builder
            size: Size of allocation in bytes (i64)
            type_id: Type ID for GC tracing (i32)

        Returns:
            i8* pointer to the allocated memory
        """
        handle = builder.call(self.gc_alloc, [size, type_id])
        ptr = builder.call(self.gc_handle_deref, [handle])
        return ptr

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

        # Allocate handle slots array (Phase 3: i64* instead of i8**)
        slot_size = ir.Constant(self.i64, 8)  # sizeof(i64)
        array_size = builder.mul(final_count, slot_size)
        # Ensure at least 8 bytes even if count is 0
        min_size = builder.icmp_unsigned(">", array_size, ir.Constant(self.i64, 0))
        actual_size = builder.select(min_size, array_size, ir.Constant(self.i64, 8))
        slots_array = builder.call(self.codegen.malloc, [actual_size])
        slots_typed = builder.bitcast(slots_array, self.i64_ptr)

        # Store in snapshot
        slots_field = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(slots_typed, slots_field)
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
        # Phase 3: Get handle slots (i64*) instead of roots (i8**)
        slots_ptr_ptr = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        frame_slots = builder.load(slots_ptr_ptr)

        slot_idx = builder.alloca(self.i64, name="slot_idx")
        builder.store(ir.Constant(self.i64, 0), slot_idx)
        builder.branch(copy_roots)

        builder.position_at_end(copy_roots)
        ri = builder.load(slot_idx)
        done_roots = builder.icmp_unsigned(">=", ri, frame_num_roots)
        builder.cbranch(done_roots, copy_next_frame, copy_root)

        builder.position_at_end(copy_root)
        ri2 = builder.load(slot_idx)
        src_slot = builder.gep(frame_slots, [ri2], inbounds=True)
        handle_val = builder.load(src_slot)  # Phase 3: i64 handle

        ci = builder.load(copy_idx)
        dst_slot = builder.gep(slots_typed, [ci], inbounds=True)
        builder.store(handle_val, dst_slot)

        new_ci = builder.add(ci, ir.Constant(self.i64, 1))
        builder.store(new_ci, copy_idx)
        builder.branch(copy_next_root)

        builder.position_at_end(copy_next_root)
        next_ri = builder.add(ri2, ir.Constant(self.i64, 1))
        builder.store(next_ri, slot_idx)
        builder.branch(copy_roots)

        builder.position_at_end(copy_next_frame)
        parent_ptr2 = builder.gep(frame2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent2 = builder.load(parent_ptr2)
        builder.store(parent2, frame_ptr)
        builder.branch(copy_loop)

        builder.position_at_end(done)
        builder.ret(snapshot)

    def _implement_gc_mark_from_snapshot(self):
        """Mark objects reachable from snapshot handle slots.

        Phase 3: Snapshot now contains i64 handles instead of i8* pointers.
        """
        func = self.gc_mark_from_snapshot
        func.args[0].name = "snapshot"

        entry = func.append_basic_block("entry")
        mark_loop = func.append_basic_block("mark_loop")
        check_handle = func.append_basic_block("check_handle")
        do_mark = func.append_basic_block("do_mark")
        next_slot = func.append_basic_block("next_slot")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        snapshot = func.args[0]

        # Get handle slots array and count (Phase 3)
        slots_ptr = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        slots = builder.load(slots_ptr)
        count_ptr = builder.gep(snapshot, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        count = builder.load(count_ptr)

        idx = builder.alloca(self.i64, name="idx")
        builder.store(ir.Constant(self.i64, 0), idx)
        builder.branch(mark_loop)

        builder.position_at_end(mark_loop)
        i = builder.load(idx)
        done_marking = builder.icmp_unsigned(">=", i, count)
        builder.cbranch(done_marking, done, check_handle)

        builder.position_at_end(check_handle)
        i2 = builder.load(idx)
        slot = builder.gep(slots, [i2], inbounds=True)
        handle = builder.load(slot)  # Phase 3: i64 handle

        # Skip if handle is 0 (null handle)
        is_null = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_null, next_slot, do_mark)

        builder.position_at_end(do_mark)
        # gc_mark_object now takes i64 handle directly
        builder.call(self.gc_mark_object, [handle])
        builder.branch(next_slot)

        builder.position_at_end(next_slot)
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

        # Phase 7: Get handle and mark directly (gc_mark_object takes i64 handle)
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)

        # Mark the object via its handle (gc_mark_object handles null and already-marked)
        builder.call(self.gc_mark_object, [obj_handle])

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

        # Phase 7: Get handle and dereference to get data pointer
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

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

        # Phase 7: Get handle and dereference to get data pointer
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

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

    def _implement_gc_fragmentation_report(self):
        """Analyze and print heap fragmentation statistics.

        Walks the allocation list and computes:
        - Total allocated objects and bytes
        - Size distribution (small/medium/large objects)
        - Free list length (available handle slots)
        - Retired list length (pending reclamation)
        """
        func = self.gc_fragmentation_report

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
        head = builder.load(self.gc_alloc_list)
        builder.store(head, curr)
        builder.branch(loop)

        # Loop through allocation list
        builder.position_at_end(loop)
        curr_val = builder.load(curr)
        is_null = builder.icmp_unsigned("==", curr_val, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, count_free, process_obj)

        # Process object
        builder.position_at_end(process_obj)
        node = builder.bitcast(curr_val, self.alloc_node_type.as_pointer())
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

        # Get size from header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.header_type.as_pointer())
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
        node2 = builder.bitcast(curr_val2, self.alloc_node_type.as_pointer())
        handle_ptr2 = builder.gep(node2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle2 = builder.load(handle_ptr2)
        data_ptr2 = builder.call(self.gc_handle_deref, [obj_handle2])
        data_int2 = builder.ptrtoint(data_ptr2, self.i64)
        header_int2 = builder.sub(data_int2, ir.Constant(self.i64, self.HEADER_SIZE))
        header2 = builder.inttoptr(header_int2, self.header_type.as_pointer())
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
        free_head = builder.load(self.gc_handle_free_list)
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
        table = builder.load(self.gc_handle_table)
        fc_val = builder.load(free_curr)
        slot_ptr = builder.gep(table, [fc_val])
        next_free_ptr = builder.load(slot_ptr)
        next_free = builder.ptrtoint(next_free_ptr, self.i64)
        builder.store(next_free, free_curr)
        builder.branch(free_loop)

        # Count retired list
        builder.position_at_end(count_retired)
        ret_head = builder.load(self.gc_handle_retired_list)
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
        table2 = builder.load(self.gc_handle_table)
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

    def _implement_gc_dump_handle_table(self):
        """Print handle table state including allocated, free, and retired handles.

        Shows:
        - Table size and next handle index
        - First N allocated handles with their object pointers
        - Free list chain
        - Retired list chain
        """
        func = self.gc_dump_handle_table

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
        table_size = builder.load(self.gc_handle_table_size)
        next_handle = builder.load(self.gc_next_handle)
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
        table = builder.load(self.gc_handle_table)
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
        table2 = builder.load(self.gc_handle_table)
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
        free_head = builder.load(self.gc_handle_free_list)
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
        table3 = builder.load(self.gc_handle_table)
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
        ret_head = builder.load(self.gc_handle_retired_list)
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
        table4 = builder.load(self.gc_handle_table)
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

    def _implement_gc_dump_shadow_stacks(self):
        """Print all shadow stack frames and their root handles.

        Walks the shadow stack from top to bottom, printing each frame's
        handle slots and their dereferenced pointers.
        """
        func = self.gc_dump_shadow_stacks

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
        frame_depth = builder.load(self.gc_frame_depth)
        builder.call(printf, [depth_ptr, frame_depth])

        # Current frame pointer and frame number
        curr_frame = builder.alloca(self.i8_ptr, name="curr_frame")
        frame_num = builder.alloca(self.i64, name="frame_num")
        top = builder.load(self.gc_frame_top)
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
        frame = builder.bitcast(frame_ptr, self.gc_frame_type.as_pointer())
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
        frame2 = builder.bitcast(frame_ptr2, self.gc_frame_type.as_pointer())
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
        frame3 = builder.bitcast(frame_ptr3, self.gc_frame_type.as_pointer())
        slots_ptr_ptr2 = builder.gep(frame3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        slots2 = builder.load(slots_ptr_ptr2)
        slot_ptr = builder.gep(slots2, [ri_val], inbounds=True)
        handle = builder.load(slot_ptr)
        ptr = builder.call(self.gc_handle_deref, [handle])
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
        frame4 = builder.bitcast(frame_ptr4, self.gc_frame_type.as_pointer())
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

    # ============================================================
    # Handle-Based GC - Phase 1: Handle Management Functions
    # ============================================================

    def _implement_gc_handle_table_grow(self):
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

    def _implement_gc_handle_alloc(self):
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

    def _implement_gc_handle_free(self):
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

    def _implement_gc_handle_deref(self):
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

    def _implement_gc_handle_store(self):
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

    def _implement_gc_ptr_to_handle(self):
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

    def _implement_gc_handle_retire(self):
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

    def _implement_gc_promote_retired_handles(self):
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
