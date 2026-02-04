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
    GC_THRESHOLD = 100000    # Trigger GC after this many allocations
    INITIAL_HEAP_SIZE = 1024 * 1024 * 1024  # 1GB initial heap

    # Handle table constants (Handle-Based GC)
    INITIAL_HANDLE_TABLE_SIZE = 1048576  # 1M handles (8MB for pointers)

    # Flag bits in header (stored in i64 flags field)
    FLAG_MARK_BIT = 0x01     # Bit 0: mark bit for GC
    FLAG_FORWARDED = 0x02    # Bit 1: object has been forwarded (compaction)
    FLAG_PINNED = 0x04       # Bit 2: pinned (not movable) - future use
    FLAG_FINALIZER = 0x08    # Bit 3: has finalizer - future use
    FLAG_TLAB = 0x10         # Bit 4: allocated from TLAB (don't free individually)
    FLAG_ARENA = 0x20        # Bit 5: arena-allocated (no handle, bulk-freed)

    # Trace levels for debugging infrastructure (Phase 0)
    GC_TRACE_NONE = 0        # No tracing output
    GC_TRACE_PHASES = 1      # Collection phase boundaries
    GC_TRACE_OPS = 2         # Major operations (alloc, mark, sweep)
    GC_TRACE_DETAIL = 3      # Individual object operations
    GC_TRACE_ALL = 4         # Everything including pointer traversals

    # ============================================================
    # Tagged Value Type System
    # ============================================================
    #
    # Universal Tagged Values: Every value stored in collections is a
    # TaggedValue = { i64 type_id, i64 value }. This makes values self-
    # describing, allowing the GC to trace references correctly without
    # depending on compile-time type inference.
    #
    # Type ID Scheme:
    #   - Primitive types (0-9): value field is raw data, no GC tracing
    #   - Heap types (64+): value field is GC handle, needs tracing
    #   - Internal types (80-99): only in object headers, not TaggedValue
    #   - User types (128+): all heap-allocated
    #
    # The key invariant: is_heap_value_type(type_id) = (type_id >= TYPE_HEAP_BASE)
    #
    # OLD TYPE IDS (for backward compatibility during migration):
    # The legacy type IDs (1-22) are still used for object headers.
    # During migration, we map between old and new IDs as needed.
    # ============================================================

    # ------------------------------------------------------------
    # NEW TYPE IDS - TaggedValue Compatible
    # ------------------------------------------------------------
    # Primitive types: value field is raw data, no GC handle
    TV_TYPE_UNKNOWN = 0
    TV_TYPE_INT = 1
    TV_TYPE_FLOAT = 2
    TV_TYPE_BOOL = 3
    TV_TYPE_BYTE = 4
    TV_TYPE_CHAR = 5
    TV_TYPE_JSON_NULL = 6    # value = 0
    TV_TYPE_JSON_BOOL = 7    # value = 0 or 1
    TV_TYPE_JSON_INT = 8     # value = raw i64
    TV_TYPE_JSON_FLOAT = 9   # value = f64 bitcast to i64

    # Heap reference threshold - all types >= this have GC handles
    TYPE_HEAP_BASE = 64

    # Heap types: value field is GC handle, needs tracing
    TV_TYPE_STRING = 64
    TV_TYPE_LIST = 65
    TV_TYPE_MAP = 66
    TV_TYPE_SET = 67
    TV_TYPE_ARRAY = 68
    TV_TYPE_CHANNEL = 69
    TV_TYPE_JSON_STRING = 70  # value = handle to String
    TV_TYPE_JSON_ARRAY = 71   # value = handle to List
    TV_TYPE_JSON_OBJECT = 72  # value = handle to Map
    TV_TYPE_TUPLE = 73

    # Internal structural types (only in object headers, not in TaggedValue)
    TV_TYPE_STRING_DATA = 80
    TV_TYPE_LIST_TAIL = 81
    TV_TYPE_PV_NODE = 82
    TV_TYPE_CHANNEL_BUFFER = 83
    TV_TYPE_ARRAY_DATA = 84
    TV_TYPE_HAMT_NODE = 85
    TV_TYPE_HAMT_LEAF = 86
    TV_TYPE_MAP_ENTRY = 87
    TV_TYPE_SET_ENTRY = 88

    # User-defined types start here (all heap-allocated)
    TV_TYPE_FIRST_USER = 128

    # ------------------------------------------------------------
    # LEGACY TYPE IDS (for backward compatibility)
    # ------------------------------------------------------------
    # These are used by existing object headers and GC marking.
    # Will be phased out as collections migrate to TaggedValue.
    TYPE_UNKNOWN = 0
    TYPE_LIST = 1            # List struct (root_handle, len, depth, tail_handle, ...)
    TYPE_STRING = 2          # String struct (data_handle, len, ...)
    TYPE_MAP = 3             # Map struct (HAMT root, len, flags)
    TYPE_MAP_ENTRY = 4       # HAMT entry node
    TYPE_SET = 5             # Set struct (HAMT root, len, flags)
    TYPE_SET_ENTRY = 6       # HAMT entry node
    TYPE_CHANNEL = 7         # Channel struct
    TYPE_ARRAY = 8           # Array struct (handle, ndim, shape, strides, ...)
    TYPE_LIST_TAIL = 9       # List tail buffer - PRIMITIVE elements (int, float, etc.)
    TYPE_PV_NODE = 10        # Persistent vector internal tree node
    TYPE_STRING_DATA = 11    # String character data buffer (raw bytes)
    TYPE_CHANNEL_BUFFER = 12 # Channel data buffer
    TYPE_ARRAY_DATA = 13     # Array data buffer - PRIMITIVE elements (int, float, etc.)
    # ---- JSON variant types (first-class tagged union) ----
    TYPE_JSON_NULL = 14      # JSON null - no payload (8 bytes for alignment)
    TYPE_JSON_BOOL = 15      # JSON bool - i64 value (0/1)
    TYPE_JSON_INT = 16       # JSON int - i64 value
    TYPE_JSON_FLOAT = 17     # JSON float - i64 (f64 bitcast)
    TYPE_JSON_STRING = 18    # JSON string - i64 handle to String
    TYPE_JSON_ARRAY = 19     # JSON array - i64 handle to List
    TYPE_JSON_OBJECT = 20    # JSON object - i64 handle to Map
    # ---- Reference-type buffers (elements are HANDLES, not raw data) ----
    # DEPRECATED: These type IDs are kept for backward compatibility only.
    # With USE_TAGGED_VALUES=True, all list tails use TYPE_LIST_TAIL and store
    # TaggedValues {type_id, value} where the GC reads type_id from each element
    # to determine if it's a heap reference. These _REF type IDs are no longer
    # used for new allocations.
    TYPE_LIST_TAIL_REF = 21  # [DEPRECATED] List tail buffer - REFERENCE elements
    TYPE_ARRAY_DATA_REF = 22 # [DEPRECATED] Array data buffer - REFERENCE elements
    TYPE_FIRST_USER = 23     # First ID for user-defined types

    # ------------------------------------------------------------
    # Type ID Mapping (Legacy <-> TaggedValue)
    # ------------------------------------------------------------
    # Maps legacy object header type IDs to TaggedValue type IDs
    LEGACY_TO_TV_TYPE = {
        1: 65,   # TYPE_LIST -> TV_TYPE_LIST
        2: 64,   # TYPE_STRING -> TV_TYPE_STRING
        3: 66,   # TYPE_MAP -> TV_TYPE_MAP
        5: 67,   # TYPE_SET -> TV_TYPE_SET
        7: 69,   # TYPE_CHANNEL -> TV_TYPE_CHANNEL
        8: 68,   # TYPE_ARRAY -> TV_TYPE_ARRAY
        14: 6,   # TYPE_JSON_NULL -> TV_TYPE_JSON_NULL
        15: 7,   # TYPE_JSON_BOOL -> TV_TYPE_JSON_BOOL
        16: 8,   # TYPE_JSON_INT -> TV_TYPE_JSON_INT
        17: 9,   # TYPE_JSON_FLOAT -> TV_TYPE_JSON_FLOAT
        18: 70,  # TYPE_JSON_STRING -> TV_TYPE_JSON_STRING
        19: 71,  # TYPE_JSON_ARRAY -> TV_TYPE_JSON_ARRAY
        20: 72,  # TYPE_JSON_OBJECT -> TV_TYPE_JSON_OBJECT
    }

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

        # TaggedValue type: { i64 type_id, i64 value }
        # Every collection element will be stored as a TaggedValue
        self.tagged_value_type = ir.LiteralStructType([self.i64, self.i64])
        self.tagged_value_ptr_type = self.tagged_value_type.as_pointer()

        # TaggedValue helper functions
        self.tv_new = None           # Create TaggedValue from type_id and value
        self.tv_get_type = None      # Extract type_id from TaggedValue
        self.tv_get_value = None     # Extract value from TaggedValue
        self.tv_is_heap = None       # Check if type_id indicates heap reference

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

        # Per-thread handle pool functions (lock-free handle allocation)
        self.gc_handle_pool_alloc = None   # Fast path: allocate from thread-local pool
        self.gc_handle_pool_refill = None  # Slow path: refill pool under mutex

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
        self.gc_trigger_requested = None
        self.gc_thread_running = None

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
        self.gc_validate_handle_storage = None  # Validate stored values are handles not pointers

        # ============================================================
        # Thread Registry (Multi-Thread GC Support)
        # ============================================================

        # Thread registry type and globals
        self.thread_entry_type = None
        self.gc_thread_registry = None
        self.gc_thread_count = None
        self.gc_registry_mutex = None
        self.gc_phase = None
        self.gc_cycle_id = None

        # Thread-local storage
        self.tls_frame_top = None
        self.tls_frame_depth = None
        self.tls_thread_entry = None

        # Phase 3: Segmented shadow stack TLS
        self.tls_segment_base = None     # First segment in chain
        self.tls_segment_current = None  # Current active segment
        self.tls_slot_index = None       # Current slot index in segment

        # Thread registry functions
        self.gc_register_thread = None
        self.gc_unregister_thread = None
        self.gc_get_thread_entry = None
        self.pthread_self = None

    def generate_gc_runtime(self):
        """Generate all GC runtime structures and functions"""
        self._create_types()
        self._create_globals()
        self._declare_functions()
        self._register_builtin_types()
        # Thread registry functions (must be before gc_init which calls register)
        self._implement_gc_register_thread()
        self._implement_gc_unregister_thread()
        self._implement_gc_get_thread_entry()
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
        # TaggedValue helper functions
        self._implement_tv_is_heap_type()
        self._implement_tv_mark()
        self._implement_tv_mark_array()
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
        self._implement_gc_wait_for_watermarks()
        # Phase 3: Segmented shadow stack
        self._implement_gc_segment_alloc()
        self._implement_gc_segment_init()
        self._implement_gc_segment_push()
        self._implement_gc_segment_pop()
        self._implement_gc_segment_set_root()
        self._implement_gc_segment_scan_roots()
        # Phase 4: TLAB allocation
        self._implement_gc_tlab_init()
        self._implement_gc_tlab_alloc()
        self._implement_gc_tlab_refill()
        self._implement_gc_alloc_to_thread_list()
        self._implement_gc_sweep_thread_lists()
        self._implement_gc_grow_heaps()
        # Phase 6: Scope arena functions
        self._implement_gc_arena_push()
        self._implement_gc_arena_alloc()
        self._implement_gc_arena_pop()
        self._implement_gc_alloc_arena_or_gc()
        self._implement_gc_promote_to_heap()
        # Phase 5: Mark worklist functions for concurrent marking
        self._implement_gc_mark_worklist_init()
        self._implement_gc_mark_push()
        self._implement_gc_mark_pop()
        self._implement_gc_mark_drain()
        self._implement_gc_mark_worklist_grow()
        self._implement_gc_mark_worklist_reset()
        # Phase 0: Debugging infrastructure
        self._implement_gc_trace()
        self._implement_gc_dump_stats()
        self._implement_gc_stat_getters()  # Heapwatch getter functions
        self._implement_gc_dump_heap()
        self._implement_gc_dump_roots()
        self._implement_gc_dump_object()
        self._implement_gc_validate_heap()
        self._implement_gc_set_trace_level()
        # Additional diagnostic functions
        self._implement_gc_fragmentation_report()
        self._implement_gc_dump_handle_table()
        self._implement_gc_dump_shadow_stacks()
        self._implement_gc_validate_handle_storage()
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
        # Per-thread handle pool functions (lock-free allocation)
        self._implement_gc_handle_pool_alloc()
        self._implement_gc_handle_pool_refill()

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
        # TLAB header structure - placed at start of each TLAB buffer
        # Used to track live object count for TLAB reclamation
        self.tlab_header_type = ir.LiteralStructType([
            self.i64,     # live_count - atomic counter of live objects
            self.i8_ptr,  # next_tlab - linked list of all TLABs for this thread
        ])
        self.TLAB_HEADER_SIZE = 16  # sizeof(tlab_header_type)

        # Linked list of all allocations for sweep
        # Phase 7: Changed from i8* data to i64 handle for handle-based GC
        self.alloc_node_type = ir.LiteralStructType([
            self.i8_ptr,  # next allocation node
            self.i64,     # handle to the object (instead of data pointer)
            self.i64,     # size of allocation
            self.i8_ptr,  # tlab_base - pointer to TLAB header (NULL for non-TLAB)
        ])

        # GC Frame: { i8* parent, i64 num_roots, i64* handle_slots }
        # Shadow stack frame for root tracking (Phase 3: handles instead of pointers)
        self.gc_frame_type = ir.LiteralStructType([
            self.i8_ptr,      # parent frame pointer
            self.i64,         # number of roots
            self.i64_ptr,     # pointer to handle slots array (array of i64 handles)
        ])

        # ============================================================
        # Phase 3: Segmented Shadow Stack Types
        # ============================================================
        # StackSegment: 4KB page-aligned segment for shadow stack roots
        # Header: 24 bytes (prev, next, slot_count)
        # Slots: 509 * 8 = 4072 bytes
        # Total: 4096 bytes (one page)
        self.SEGMENT_SLOTS = 509  # Number of i64 slots per segment
        self.SEGMENT_SIZE = 4096  # Total segment size in bytes

        self.stack_segment_type = ir.LiteralStructType([
            self.i8_ptr,                           # 0: prev - previous segment (toward base)
            self.i8_ptr,                           # 8: next - next segment (for reuse)
            self.i64,                              # 16: slot_count - number of slots in use
            ir.ArrayType(self.i64, 509),           # 24: slots - handle slots array
        ])
        # Total: 8 + 8 + 8 + (509 * 8) = 24 + 4072 = 4096 bytes

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

        # ============================================================
        # Thread Registry Type (Multi-Thread GC Support)
        # ============================================================
        # ThreadEntry: Per-thread GC state for concurrent collection
        # All pointer-sized fields for cross-platform consistency
        self.thread_entry_type = ir.LiteralStructType([
            self.i64,     # 0:  thread_id - platform thread identifier
            self.i8_ptr,  # 8:  shadow_stack_head - pointer to thread's frame top location
            self.i64,     # 16: watermark_depth - stack depth when watermark set (0 = none)
            self.i64,     # 24: watermark_active - 1 if acknowledged current GC cycle
            self.i64,     # 32: stack_depth - current shadow stack depth
            self.i64,     # 40: last_gc_cycle - last GC cycle acknowledged
            self.i8_ptr,  # 48: tlab_base - thread-local alloc buffer start
            self.i8_ptr,  # 56: tlab_cursor - current TLAB allocation position
            self.i8_ptr,  # 64: tlab_limit - end of TLAB buffer
            self.i8_ptr,  # 72: alloc_list - per-thread allocation list head (Phase 4)
            self.i64,     # 80: tlab_epoch - GC epoch when TLAB was issued
            self.i8_ptr,  # 88: next - next ThreadEntry in registry (stored as i8*)
            # Segmented shadow stack fields (Phase 5)
            self.i8_ptr,  # 96:  segment_base - first segment pointer (never changes)
            self.i8_ptr,  # 104: segment_current - active segment pointer
            self.i64,     # 112: slot_index - current absolute slot position (= watermark)
            # Scope arena fields (Phase 6) - per-function bump allocation
            self.i8_ptr,  # 120: arena_cursor - current arena allocation position
            self.i8_ptr,  # 128: arena_start - start of current arena (for bulk free)
            self.i8_ptr,  # 136: arena_parent_start - parent arena's start (for nesting)
            # Per-thread handle pool fields (Phase 7) - lock-free handle allocation
            self.i64,     # 144: handle_pool_start - first handle index in pool
            self.i64,     # 152: handle_pool_next - next available handle in pool
            self.i64,     # 160: handle_pool_end - one past last handle in pool
        ])
        # Total: 168 bytes

        # TLAB configuration
        self.TLAB_SIZE = 256 * 1024  # 256KB per TLAB

        # Handle pool configuration
        # 4K page / 8 bytes per handle slot = 512 handles per batch
        self.HANDLE_POOL_SIZE = 512


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

        # GC trigger flag - set by mutators to request collection
        # GC thread monitors this and starts collection when set
        self.gc_trigger_requested = ir.GlobalVariable(self.module, self.i64, name="gc_trigger_requested")
        self.gc_trigger_requested.initializer = ir.Constant(self.i64, 0)
        self.gc_trigger_requested.linkage = 'internal'

        # GC thread running flag - set to 0 to stop the GC thread
        self.gc_thread_running = ir.GlobalVariable(self.module, self.i64, name="gc_thread_running")
        self.gc_thread_running.initializer = ir.Constant(self.i64, 1)
        self.gc_thread_running.linkage = 'internal'

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

        # ============================================================
        # Thread Registry Globals (Multi-Thread GC Support)
        # ============================================================

        # Head of thread registry linked list
        self.gc_thread_registry = ir.GlobalVariable(
            self.module, self.thread_entry_type.as_pointer(), name="gc_thread_registry")
        self.gc_thread_registry.initializer = ir.Constant(
            self.thread_entry_type.as_pointer(), None)
        self.gc_thread_registry.linkage = 'internal'

        # Count of registered threads
        self.gc_thread_count = ir.GlobalVariable(
            self.module, self.i64, name="gc_thread_count")
        self.gc_thread_count.initializer = ir.Constant(self.i64, 0)
        self.gc_thread_count.linkage = 'internal'

        # Mutex for registry modifications (pointer to allocated mutex)
        self.gc_registry_mutex = ir.GlobalVariable(
            self.module, self.i8_ptr, name="gc_registry_mutex")
        self.gc_registry_mutex.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_registry_mutex.linkage = 'internal'

        # GC phase: 0=idle, 1=watermark, 2=marking, 3=sweeping
        self.gc_phase = ir.GlobalVariable(
            self.module, self.i64, name="gc_phase")
        self.gc_phase.initializer = ir.Constant(self.i64, 0)
        self.gc_phase.linkage = 'internal'

        # GC cycle counter (monotonically increasing)
        self.gc_cycle_id = ir.GlobalVariable(
            self.module, self.i64, name="gc_cycle_id")
        self.gc_cycle_id.initializer = ir.Constant(self.i64, 0)
        self.gc_cycle_id.linkage = 'internal'

        # ============================================================
        # Thread-Local Storage Variables (see BUG-023)
        # ============================================================
        # We use pthread TLS due to BUG-023 (llvmlite TLS broken).
        # The pthread_key_t is stored as i64 (fits unsigned long on macOS).

        # Pthread TLS key for ThreadEntry pointer (initialized in gc_init)
        self.tls_thread_entry_key = ir.GlobalVariable(
            self.module, self.i64, name="tls_thread_entry_key")
        self.tls_thread_entry_key.initializer = ir.Constant(self.i64, 0)
        self.tls_thread_entry_key.linkage = 'internal'

        # Thread's shadow stack frame chain top (stored in ThreadEntry)
        self.tls_frame_top = ir.GlobalVariable(
            self.module, self.i8_ptr, name="tls_frame_top")
        self.tls_frame_top.initializer = ir.Constant(self.i8_ptr, None)
        self.tls_frame_top.linkage = 'internal'
        self.tls_frame_top.thread_local = 'localdynamic'  # BUG-023: ignored

        # Thread's shadow stack depth (stored in ThreadEntry)
        self.tls_frame_depth = ir.GlobalVariable(
            self.module, self.i64, name="tls_frame_depth")
        self.tls_frame_depth.initializer = ir.Constant(self.i64, 0)
        self.tls_frame_depth.linkage = 'internal'
        self.tls_frame_depth.thread_local = 'localdynamic'  # BUG-023: ignored

        # Pointer to thread's ThreadEntry (use pthread TLS for actual access)
        self.tls_thread_entry = ir.GlobalVariable(
            self.module, self.thread_entry_type.as_pointer(), name="tls_thread_entry")
        self.tls_thread_entry.initializer = ir.Constant(
            self.thread_entry_type.as_pointer(), None)
        self.tls_thread_entry.linkage = 'internal'
        self.tls_thread_entry.thread_local = 'localdynamic'  # BUG-023: ignored

        # ============================================================
        # Phase 3: Segmented Shadow Stack TLS Globals
        # ============================================================

        # First segment in thread's segment chain (never changes after init)
        self.tls_segment_base = ir.GlobalVariable(
            self.module, self.stack_segment_type.as_pointer(), name="tls_segment_base")
        self.tls_segment_base.initializer = ir.Constant(
            self.stack_segment_type.as_pointer(), None)
        self.tls_segment_base.linkage = 'internal'
        self.tls_segment_base.thread_local = 'localdynamic'

        # Current active segment (may differ from base when stack grows)
        self.tls_segment_current = ir.GlobalVariable(
            self.module, self.stack_segment_type.as_pointer(), name="tls_segment_current")
        self.tls_segment_current.initializer = ir.Constant(
            self.stack_segment_type.as_pointer(), None)
        self.tls_segment_current.linkage = 'internal'
        self.tls_segment_current.thread_local = 'localdynamic'

        # Current slot index within the current segment (0 to SEGMENT_SLOTS-1)
        self.tls_slot_index = ir.GlobalVariable(
            self.module, self.i64, name="tls_slot_index")
        self.tls_slot_index.initializer = ir.Constant(self.i64, 0)
        self.tls_slot_index.linkage = 'internal'
        self.tls_slot_index.thread_local = 'localdynamic'

        # DEBUG: Counter for successful list additions
        self.gc_debug_list_adds = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_list_adds")
        self.gc_debug_list_adds.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_list_adds.linkage = 'internal'

        # DEBUG: Counter for skipped adds (no thread entry)
        self.gc_debug_list_skips = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_list_skips")
        self.gc_debug_list_skips.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_list_skips.linkage = 'internal'

        # DEBUG: Counter for threads iterated during sweep
        self.gc_debug_sweep_threads = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_sweep_threads")
        self.gc_debug_sweep_threads.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_sweep_threads.linkage = 'internal'

        # DEBUG: Counter for nodes seen during sweep
        self.gc_debug_sweep_nodes = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_sweep_nodes")
        self.gc_debug_sweep_nodes.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_sweep_nodes.linkage = 'internal'

        # DEBUG: Counter for empty lists during sweep
        self.gc_debug_sweep_empty = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_sweep_empty")
        self.gc_debug_sweep_empty.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_sweep_empty.linkage = 'internal'

        # DEBUG: Counter for marked nodes during sweep (survivors)
        self.gc_debug_sweep_marked = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_sweep_marked")
        self.gc_debug_sweep_marked.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_sweep_marked.linkage = 'internal'

        # DEBUG: Counter for unmarked nodes during sweep (freed)
        self.gc_debug_sweep_unmarked = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_sweep_unmarked")
        self.gc_debug_sweep_unmarked.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_sweep_unmarked.linkage = 'internal'

        # DEBUG: Counter for TLAB objects freed
        self.gc_debug_tlab_freed = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_tlab_freed")
        self.gc_debug_tlab_freed.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_tlab_freed.linkage = 'internal'

        # DEBUG: Counter for non-TLAB objects freed
        self.gc_debug_nontlab_freed = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_nontlab_freed")
        self.gc_debug_nontlab_freed.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_nontlab_freed.linkage = 'internal'

        # DEBUG: Counter for TLABs reclaimed (munmap called)
        self.gc_debug_tlabs_reclaimed = ir.GlobalVariable(
            self.module, self.i64, name="gc_debug_tlabs_reclaimed")
        self.gc_debug_tlabs_reclaimed.initializer = ir.Constant(self.i64, 0)
        self.gc_debug_tlabs_reclaimed.linkage = 'internal'

        # Deferred TLAB free list - TLABs to free at end of sweep
        # This avoids use-after-free when multiple objects in same TLAB die in same cycle
        self.gc_dead_tlab_list = ir.GlobalVariable(
            self.module, self.i8_ptr, name="gc_dead_tlab_list")
        self.gc_dead_tlab_list.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_dead_tlab_list.linkage = 'internal'

        # ============================================================
        # Phase 5: Mark Worklist for Concurrent Marking
        # ============================================================
        # Work-stealing queue for parallel marking. Currently single-threaded,
        # but designed for future scaling to multiple GC threads.
        #
        # Uses a simple circular buffer with head (push) and tail (pop) indices.
        # For work-stealing, would use atomic operations and per-GC-thread queues.

        self.MARK_WORKLIST_INITIAL_SIZE = 65536  # Initial capacity

        # Pointer to dynamically allocated array of handles
        self.gc_mark_worklist = ir.GlobalVariable(
            self.module, self.i64_ptr, name="gc_mark_worklist")
        self.gc_mark_worklist.initializer = ir.Constant(self.i64_ptr, None)
        self.gc_mark_worklist.linkage = 'internal'

        # Current head index (where to push next)
        self.gc_mark_worklist_head = ir.GlobalVariable(
            self.module, self.i64, name="gc_mark_worklist_head")
        self.gc_mark_worklist_head.initializer = ir.Constant(self.i64, 0)
        self.gc_mark_worklist_head.linkage = 'internal'

        # Current tail index (where to pop next)
        self.gc_mark_worklist_tail = ir.GlobalVariable(
            self.module, self.i64, name="gc_mark_worklist_tail")
        self.gc_mark_worklist_tail.initializer = ir.Constant(self.i64, 0)
        self.gc_mark_worklist_tail.linkage = 'internal'

        # Current capacity of the worklist
        self.gc_mark_worklist_capacity = ir.GlobalVariable(
            self.module, self.i64, name="gc_mark_worklist_capacity")
        self.gc_mark_worklist_capacity.initializer = ir.Constant(self.i64, 0)
        self.gc_mark_worklist_capacity.linkage = 'internal'

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

        # ============================================================
        # TaggedValue Helper Functions
        # ============================================================
        # TaggedValue = { i64 type_id, i64 value }
        # Used for self-describing collection elements

        # tv_is_heap_type(type_id: i64) -> i1
        # Check if a type_id indicates a heap reference (>= TYPE_HEAP_BASE)
        tv_is_heap_ty = ir.FunctionType(self.i1, [self.i64])
        self.tv_is_heap = ir.Function(self.module, tv_is_heap_ty, name="coex_tv_is_heap_type")
        self.tv_is_heap.attributes.add('alwaysinline')

        # tv_mark(tv_ptr: {i64, i64}*) -> void
        # Mark the value in a TaggedValue if it's a heap reference
        tv_mark_ty = ir.FunctionType(self.void, [self.tagged_value_ptr_type])
        self.tv_mark = ir.Function(self.module, tv_mark_ty, name="coex_tv_mark")

        # tv_mark_array(data: {i64, i64}*, count: i64) -> void
        # Mark all TaggedValues in an array
        tv_mark_array_ty = ir.FunctionType(self.void, [self.tagged_value_ptr_type, self.i64])
        self.tv_mark_array = ir.Function(self.module, tv_mark_array_ty, name="coex_tv_mark_array")

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
        # Phase 5: Mark Worklist Functions for Concurrent Marking
        # ============================================================

        # gc_mark_worklist_init() -> void
        # Initialize the mark worklist (called from gc_init)
        gc_mark_wl_init_ty = ir.FunctionType(self.void, [])
        self.gc_mark_worklist_init = ir.Function(self.module, gc_mark_wl_init_ty, name="coex_gc_mark_worklist_init")

        # gc_mark_push(handle: i64) -> void
        # Push a handle onto the mark worklist
        gc_mark_push_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_mark_push = ir.Function(self.module, gc_mark_push_ty, name="coex_gc_mark_push")

        # gc_mark_pop() -> i64
        # Pop a handle from the mark worklist (returns 0 if empty)
        gc_mark_pop_ty = ir.FunctionType(self.i64, [])
        self.gc_mark_pop = ir.Function(self.module, gc_mark_pop_ty, name="coex_gc_mark_pop")

        # gc_mark_drain() -> void
        # Process the mark worklist until empty
        gc_mark_drain_ty = ir.FunctionType(self.void, [])
        self.gc_mark_drain = ir.Function(self.module, gc_mark_drain_ty, name="coex_gc_mark_drain")

        # gc_mark_worklist_grow() -> void
        # Double the worklist capacity
        gc_mark_wl_grow_ty = ir.FunctionType(self.void, [])
        self.gc_mark_worklist_grow = ir.Function(self.module, gc_mark_wl_grow_ty, name="coex_gc_mark_worklist_grow")

        # gc_mark_worklist_reset() -> void
        # Reset head/tail to 0 at start of each GC cycle
        gc_mark_wl_reset_ty = ir.FunctionType(self.void, [])
        self.gc_mark_worklist_reset = ir.Function(self.module, gc_mark_wl_reset_ty, name="coex_gc_mark_worklist_reset")

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

        # gc_wait_for_watermarks() -> void
        # Wait for all threads to acknowledge watermark (Phase 2)
        gc_wait_wm_ty = ir.FunctionType(self.void, [])
        self.gc_wait_for_watermarks = ir.Function(self.module, gc_wait_wm_ty, name="coex_gc_wait_for_watermarks")

        # ============================================================
        # Phase 3: Segmented Shadow Stack Function Declarations
        # ============================================================

        # gc_segment_alloc() -> StackSegment*
        # Allocate a new 4KB segment via mmap
        gc_segment_alloc_ty = ir.FunctionType(self.stack_segment_type.as_pointer(), [])
        self.gc_segment_alloc = ir.Function(self.module, gc_segment_alloc_ty, name="coex_gc_segment_alloc")

        # gc_segment_init() -> void
        # Initialize thread's first segment (called from gc_register_thread)
        gc_segment_init_ty = ir.FunctionType(self.void, [])
        self.gc_segment_init = ir.Function(self.module, gc_segment_init_ty, name="coex_gc_segment_init")

        # gc_segment_push(num_roots: i64) -> i64
        # Reserve num_roots slots in segment, returns starting slot index
        # May allocate new segment if current is full
        gc_segment_push_ty = ir.FunctionType(self.i64, [self.i64])
        self.gc_segment_push = ir.Function(self.module, gc_segment_push_ty, name="coex_gc_segment_push")

        # gc_segment_pop(start_slot: i64) -> void
        # Restore slot index to start_slot value
        # May go back to previous segment if start_slot is before current
        gc_segment_pop_ty = ir.FunctionType(self.void, [self.i64])
        self.gc_segment_pop = ir.Function(self.module, gc_segment_pop_ty, name="coex_gc_segment_pop")

        # gc_segment_set_root(slot: i64, handle: i64) -> void
        # Store handle at absolute slot index (may span segments)
        gc_segment_set_root_ty = ir.FunctionType(self.void, [self.i64, self.i64])
        self.gc_segment_set_root = ir.Function(self.module, gc_segment_set_root_ty, name="coex_gc_segment_set_root")

        # gc_segment_scan_roots() -> void
        # Scan all segments for roots (used by gc_scan_roots)
        gc_segment_scan_roots_ty = ir.FunctionType(self.void, [])
        self.gc_segment_scan_roots = ir.Function(self.module, gc_segment_scan_roots_ty, name="coex_gc_segment_scan_roots")

        # ============================================================
        # Phase 4: TLAB (Thread-Local Allocation Buffer) Declarations
        # ============================================================

        # gc_tlab_init(thread_entry: thread_entry_type*) -> void
        # Initialize TLAB for a thread (called from gc_register_thread)
        gc_tlab_init_ty = ir.FunctionType(self.void, [self.thread_entry_type.as_pointer()])
        self.gc_tlab_init = ir.Function(self.module, gc_tlab_init_ty, name="coex_gc_tlab_init")

        # gc_tlab_alloc(size: i64) -> i8*
        # Fast-path TLAB allocation (bump pointer)
        # Returns NULL if TLAB is full (caller should call gc_tlab_refill)
        gc_tlab_alloc_ty = ir.FunctionType(self.i8_ptr, [self.i64])
        self.gc_tlab_alloc = ir.Function(self.module, gc_tlab_alloc_ty, name="coex_gc_tlab_alloc")

        # gc_tlab_refill() -> void
        # Refill TLAB with fresh buffer (slow path)
        gc_tlab_refill_ty = ir.FunctionType(self.void, [])
        self.gc_tlab_refill = ir.Function(self.module, gc_tlab_refill_ty, name="coex_gc_tlab_refill")

        # gc_alloc_to_thread_list(node: i8*) -> void
        # Add allocation node to current thread's list (instead of global list)
        gc_alloc_to_thread_list_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_alloc_to_thread_list = ir.Function(self.module, gc_alloc_to_thread_list_ty, name="coex_gc_alloc_to_thread_list")

        # gc_sweep_thread_lists() -> void
        # Sweep all per-thread allocation lists (called from gc_sweep)
        gc_sweep_thread_lists_ty = ir.FunctionType(self.void, [])
        self.gc_sweep_thread_lists = ir.Function(self.module, gc_sweep_thread_lists_ty, name="coex_gc_sweep_thread_lists")

        # ============================================================
        # Scope Arena Functions (Phase 6) - per-function bump allocation
        # ============================================================

        # gc_arena_push() -> i8*
        # Save current TLAB cursor as arena start. Returns start for later pop.
        # Called at function entry for formula functions.
        gc_arena_push_ty = ir.FunctionType(self.i8_ptr, [])
        self.gc_arena_push = ir.Function(self.module, gc_arena_push_ty, name="coex_gc_arena_push")

        # gc_arena_alloc(size: i64) -> i8*
        # Bump allocation from arena. Returns NULL if arena full (caller uses GC alloc).
        # Arena objects have NO header, NO handle, and are NOT tracked by GC.
        gc_arena_alloc_ty = ir.FunctionType(self.i8_ptr, [self.i64])
        self.gc_arena_alloc = ir.Function(self.module, gc_arena_alloc_ty, name="coex_gc_arena_alloc")

        # gc_arena_pop(start: i8*) -> void
        # Reset TLAB cursor to arena start (bulk free). Restore parent arena.
        # Called before function return for formula functions.
        gc_arena_pop_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_arena_pop = ir.Function(self.module, gc_arena_pop_ty, name="coex_gc_arena_pop")

        # gc_alloc_arena_or_gc(size: i64, type_id: i32) -> i8*
        # Runtime function that tries arena allocation first, falls back to GC.
        # Unlike gc_arena_alloc, this handles header initialization and fallback.
        gc_alloc_arena_or_gc_ty = ir.FunctionType(self.i8_ptr, [self.i64, self.i32])
        self.gc_alloc_arena_or_gc = ir.Function(self.module, gc_alloc_arena_or_gc_ty, name="coex_gc_alloc_arena_or_gc")
        # Mark return as noalias to prevent optimizer from incorrectly eliminating stores
        self.gc_alloc_arena_or_gc.return_value.add_attribute('noalias')

        # gc_promote_to_heap(ptr: i8*) -> i8*
        # Promotes an arena-allocated object to the GC heap.
        # If the object is already on the heap (FLAG_ARENA not set), returns ptr unchanged.
        # If arena-allocated, copies the object to GC heap and returns new pointer.
        gc_promote_to_heap_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
        self.gc_promote_to_heap = ir.Function(self.module, gc_promote_to_heap_ty, name="coex_gc_promote_to_heap")

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

        # pthread_self() -> i64
        # External: get current thread ID
        pthread_self_ty = ir.FunctionType(self.i64, [])
        self.pthread_self = ir.Function(self.module, pthread_self_ty, name="pthread_self")

        # pthread_key_create(key*, destructor) -> int
        # Create a TLS key
        pthread_key_create_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i8_ptr])
        self.pthread_key_create = ir.Function(self.module, pthread_key_create_ty, name="pthread_key_create")

        # pthread_setspecific(key, value) -> int
        # Set thread-local value for key
        pthread_setspecific_ty = ir.FunctionType(self.i32, [self.i64, self.i8_ptr])
        self.pthread_setspecific = ir.Function(self.module, pthread_setspecific_ty, name="pthread_setspecific")

        # pthread_getspecific(key) -> void*
        # Get thread-local value for key
        pthread_getspecific_ty = ir.FunctionType(self.i8_ptr, [self.i64])
        self.pthread_getspecific = ir.Function(self.module, pthread_getspecific_ty, name="pthread_getspecific")

        # sched_yield() -> i32
        # Yield CPU to other threads (used in watermark wait spin loop)
        sched_yield_ty = ir.FunctionType(self.i32, [])
        self.sched_yield = ir.Function(self.module, sched_yield_ty, name="sched_yield")

        # mmap(addr, length, prot, flags, fd, offset) -> i8*
        # Used for 4KB page-aligned segment allocation
        mmap_ty = ir.FunctionType(self.i8_ptr, [
            self.i8_ptr,  # addr (NULL for system to choose)
            self.i64,     # length
            self.i32,     # prot (PROT_READ | PROT_WRITE = 3)
            self.i32,     # flags (MAP_PRIVATE | MAP_ANON = 0x1002 on macOS, 0x22 on Linux)
            self.i32,     # fd (-1 for anonymous)
            self.i64,     # offset (0)
        ])
        self.mmap = ir.Function(self.module, mmap_ty, name="mmap")

        # munmap(addr, length) -> i32
        # Free mmap'd memory
        munmap_ty = ir.FunctionType(self.i32, [self.i8_ptr, self.i64])
        self.munmap = ir.Function(self.module, munmap_ty, name="munmap")

        # ============================================================
        # Thread Registry Function Declarations
        # ============================================================

        # gc_register_thread() -> void
        # Called at thread start; allocates and registers ThreadEntry
        gc_register_thread_ty = ir.FunctionType(self.void, [])
        self.gc_register_thread = ir.Function(
            self.module, gc_register_thread_ty, name="coex_gc_register_thread")

        # gc_unregister_thread() -> void
        # Called at thread exit; removes ThreadEntry from registry
        gc_unregister_thread_ty = ir.FunctionType(self.void, [])
        self.gc_unregister_thread = ir.Function(
            self.module, gc_unregister_thread_ty, name="coex_gc_unregister_thread")

        # gc_get_thread_entry() -> ThreadEntry*
        # Returns calling thread's ThreadEntry from TLS
        gc_get_thread_entry_ty = ir.FunctionType(
            self.thread_entry_type.as_pointer(), [])
        self.gc_get_thread_entry = ir.Function(
            self.module, gc_get_thread_entry_ty, name="coex_gc_get_thread_entry")

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

        # gc_validate_handle_storage() -> i64
        # Debug function to validate stored values look like handles (small integers)
        # rather than raw pointers (large addresses). Returns count of violations.
        gc_validate_handle_storage_ty = ir.FunctionType(self.i64, [])
        self.gc_validate_handle_storage = ir.Function(self.module, gc_validate_handle_storage_ty, name="coex_gc_validate_handle_storage")

        # ============================================================
        # Heapwatch Getter Functions (read-only access to GC stats)
        # ============================================================

        # gc_get_total_allocations() -> i64
        gc_get_total_allocations_ty = ir.FunctionType(self.i64, [])
        self.gc_get_total_allocations = ir.Function(self.module, gc_get_total_allocations_ty, name="coex_gc_get_total_allocations")

        # gc_get_total_bytes() -> i64
        gc_get_total_bytes_ty = ir.FunctionType(self.i64, [])
        self.gc_get_total_bytes = ir.Function(self.module, gc_get_total_bytes_ty, name="coex_gc_get_total_bytes")

        # gc_get_collections() -> i64
        gc_get_collections_ty = ir.FunctionType(self.i64, [])
        self.gc_get_collections = ir.Function(self.module, gc_get_collections_ty, name="coex_gc_get_collections")

        # gc_get_live_objects() -> i64
        gc_get_live_objects_ty = ir.FunctionType(self.i64, [])
        self.gc_get_live_objects = ir.Function(self.module, gc_get_live_objects_ty, name="coex_gc_get_live_objects")

        # gc_get_swept_objects() -> i64
        gc_get_swept_objects_ty = ir.FunctionType(self.i64, [])
        self.gc_get_swept_objects = ir.Function(self.module, gc_get_swept_objects_ty, name="coex_gc_get_swept_objects")

        # gc_get_next_handle() -> i64
        gc_get_next_handle_ty = ir.FunctionType(self.i64, [])
        self.gc_get_next_handle = ir.Function(self.module, gc_get_next_handle_ty, name="coex_gc_get_next_handle")

        # gc_get_handle_table_size() -> i64
        gc_get_handle_table_size_ty = ir.FunctionType(self.i64, [])
        self.gc_get_handle_table_size = ir.Function(self.module, gc_get_handle_table_size_ty, name="coex_gc_get_handle_table_size")

        # gc_get_tlabs_reclaimed() -> i64
        gc_get_tlabs_reclaimed_ty = ir.FunctionType(self.i64, [])
        self.gc_get_tlabs_reclaimed = ir.Function(self.module, gc_get_tlabs_reclaimed_ty, name="coex_gc_get_tlabs_reclaimed")

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

        # ============================================================
        # Per-Thread Handle Pool Functions (Lock-Free Handle Allocation)
        # ============================================================

        # gc_handle_pool_alloc() -> i64
        # Fast path: allocate handle from thread-local pool (no locking)
        # Returns handle index, or 0 if pool is empty (caller must call refill)
        gc_handle_pool_alloc_ty = ir.FunctionType(self.i64, [])
        self.gc_handle_pool_alloc = ir.Function(self.module, gc_handle_pool_alloc_ty, name="coex_gc_handle_pool_alloc")

        # gc_handle_pool_refill() -> void
        # Slow path: acquire mutex and refill thread-local handle pool
        # Allocates HANDLE_POOL_SIZE (512) handles in a batch
        gc_handle_pool_refill_ty = ir.FunctionType(self.void, [])
        self.gc_handle_pool_refill = ir.Function(self.module, gc_handle_pool_refill_ty, name="coex_gc_handle_pool_refill")

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
        # Array N-D struct (104 bytes = 13 i64 fields):
        #   Field 0: handle (i64) - GC handle for data buffer
        #   Field 1: ndim (i64) - number of dimensions
        #   Field 2: shape [4 x i64] - dimensions
        #   Field 3: strides [4 x i64] - byte strides
        #   Field 4: offset (i64) - byte offset for views
        #   Field 5: elem_size (i64) - element size
        #   Field 6: type_id (i64) - element type
        # For slice views, handle points to shared data buffer (traced via mark_array)
        self.type_info[self.TYPE_ARRAY] = {'size': 104, 'ref_offsets': [0]}
        self.type_descriptors['Array'] = self.TYPE_ARRAY
        # JSON variant types - first-class tagged union with distinct type IDs
        # Each variant has 8 bytes payload (even null, for alignment simplicity)
        # - Null/Bool/Int/Float: no GC tracing needed (value is inline)
        # - String/Array/Object: value is i64 HANDLE (traced by GC)
        self.type_info[self.TYPE_JSON_NULL] = {'size': 8, 'ref_offsets': []}
        self.type_info[self.TYPE_JSON_BOOL] = {'size': 8, 'ref_offsets': []}
        self.type_info[self.TYPE_JSON_INT] = {'size': 8, 'ref_offsets': []}
        self.type_info[self.TYPE_JSON_FLOAT] = {'size': 8, 'ref_offsets': []}
        # Handle-based JSON types - value at offset 0 is an i64 handle
        self.type_info[self.TYPE_JSON_STRING] = {'size': 8, 'ref_offsets': [0]}
        self.type_info[self.TYPE_JSON_ARRAY] = {'size': 8, 'ref_offsets': [0]}
        self.type_info[self.TYPE_JSON_OBJECT] = {'size': 8, 'ref_offsets': [0]}
        # Register 'Json' as a placeholder - actual type determined at runtime
        self.type_descriptors['Json'] = self.TYPE_JSON_NULL  # Default to null for type lookup

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

    # ========================================================================
    # TaggedValue Helper Methods (for codegen)
    # ========================================================================

    def get_tv_type_id(self, coex_type) -> int:
        """Get the TaggedValue type ID for a Coex type.

        Maps Coex types to the new TaggedValue type ID scheme:
        - Primitives (int, float, bool, byte, char) -> TV_TYPE_INT/FLOAT/BOOL/BYTE/CHAR
        - Heap types (string, List, Map, etc.) -> TV_TYPE_STRING/LIST/MAP/etc.
        - JSON variants -> TV_TYPE_JSON_*
        - User-defined types -> TV_TYPE_FIRST_USER + offset

        Args:
            coex_type: A Coex type (PrimitiveType, ListType, NamedType, etc.)

        Returns:
            The TaggedValue type ID constant
        """
        from ast_nodes import PrimitiveType, ListType, MapType, SetType, ArrayType, NamedType

        if isinstance(coex_type, PrimitiveType):
            name = coex_type.name
            if name == "int":
                return self.TV_TYPE_INT
            elif name == "float":
                return self.TV_TYPE_FLOAT
            elif name == "bool":
                return self.TV_TYPE_BOOL
            elif name == "byte":
                return self.TV_TYPE_BYTE
            elif name == "char":
                return self.TV_TYPE_CHAR
            elif name == "string":
                return self.TV_TYPE_STRING
            elif name == "json":
                # JSON is always a heap-allocated pointer - use a heap type ID
                # (actual JSON variant type is stored in the object's header)
                return self.TV_TYPE_JSON_OBJECT
        elif isinstance(coex_type, ListType):
            return self.TV_TYPE_LIST
        elif isinstance(coex_type, MapType):
            return self.TV_TYPE_MAP
        elif isinstance(coex_type, SetType):
            return self.TV_TYPE_SET
        elif isinstance(coex_type, ArrayType):
            return self.TV_TYPE_ARRAY
        elif isinstance(coex_type, NamedType):
            name = coex_type.name
            if name == "string":
                return self.TV_TYPE_STRING
            elif name == "json":
                # JSON is always a heap-allocated pointer
                return self.TV_TYPE_JSON_OBJECT
            elif name == "Channel":
                return self.TV_TYPE_CHANNEL
            elif name in self.type_descriptors:
                # User-defined type - map legacy ID to TV ID
                legacy_id = self.type_descriptors[name]
                if legacy_id >= self.TYPE_FIRST_USER:
                    # User type: TV_TYPE_FIRST_USER + (legacy_id - TYPE_FIRST_USER)
                    return self.TV_TYPE_FIRST_USER + (legacy_id - self.TYPE_FIRST_USER)
        return self.TV_TYPE_UNKNOWN

    def is_tv_heap_type(self, tv_type_id: int) -> bool:
        """Check if a TaggedValue type ID represents a heap type.

        Returns True if tv_type_id >= TYPE_HEAP_BASE (64).
        """
        return tv_type_id >= self.TYPE_HEAP_BASE

    def create_tagged_value(self, builder: ir.IRBuilder, type_id: int, value: ir.Value) -> ir.Value:
        """Create a TaggedValue struct on the stack.

        Args:
            builder: LLVM IR builder
            type_id: The TaggedValue type ID constant
            value: The value (raw primitive or GC handle)

        Returns:
            Pointer to the TaggedValue struct (stack-allocated)
        """
        # Allocate in the function entry block to avoid stack growth when
        # called inside loops.  The struct is written before every use so
        # a single alloca per function is sufficient.
        func = builder.function
        entry_block = func.entry_basic_block
        saved_block = builder.block

        if entry_block.is_terminated:
            builder.position_before(entry_block.terminator)
        else:
            builder.position_at_end(entry_block)

        tv_ptr = builder.alloca(self.tagged_value_type, name="tagged_val")

        builder.position_at_end(saved_block)

        # Store type_id (field 0)
        type_id_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, type_id), type_id_ptr)

        # Store value (field 1) - may need casting
        value_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)

        # Cast value to i64 if needed
        if value.type == self.i64:
            builder.store(value, value_ptr)
        elif isinstance(value.type, ir.IntType):
            # Extend or truncate to i64
            if value.type.width < 64:
                val64 = builder.zext(value, self.i64)
            else:
                val64 = builder.trunc(value, self.i64)
            builder.store(val64, value_ptr)
        elif isinstance(value.type, ir.DoubleType):
            # Bitcast float to i64
            val64 = builder.bitcast(value, self.i64)
            builder.store(val64, value_ptr)
        elif isinstance(value.type, ir.PointerType):
            # Convert pointer to i64
            val64 = builder.ptrtoint(value, self.i64)
            builder.store(val64, value_ptr)
        else:
            # Try direct store and hope for the best
            builder.store(value, value_ptr)

        return tv_ptr

    def extract_tagged_value(self, builder: ir.IRBuilder, tv_ptr: ir.Value) -> tuple:
        """Extract type_id and value from a TaggedValue pointer.

        Args:
            builder: LLVM IR builder
            tv_ptr: Pointer to TaggedValue struct

        Returns:
            Tuple of (type_id: ir.Value, value: ir.Value) both as i64
        """
        type_id_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        type_id = builder.load(type_id_ptr)

        value_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        value = builder.load(value_ptr)

        return type_id, value

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

        # ============================================================
        # Initialize Thread Registry (Multi-Thread GC Support)
        # ============================================================

        # Initialize registry mutex
        registry_mutex_size = ir.Constant(self.i64, 64)
        registry_mutex_ptr = builder.call(self.codegen.malloc, [registry_mutex_size])
        builder.store(registry_mutex_ptr, self.gc_registry_mutex)
        builder.call(self.pthread_mutex_init, [
            registry_mutex_ptr, ir.Constant(self.i8_ptr, None)
        ])

        # Initialize GC phase and cycle
        builder.store(ir.Constant(self.i64, 0), self.gc_phase)
        builder.store(ir.Constant(self.i64, 0), self.gc_cycle_id)

        # Initialize trigger flags
        builder.store(ir.Constant(self.i64, 0), self.gc_trigger_requested)
        builder.store(ir.Constant(self.i64, 1), self.gc_thread_running)

        # ============================================================
        # Initialize pthread TLS key for thread entry
        # ============================================================
        # pthread_key_t is typically unsigned long (8 bytes on 64-bit)
        # We allocate storage for it and call pthread_key_create
        key_storage = builder.alloca(self.i64, name="tls_key_storage")
        key_storage_ptr = builder.bitcast(key_storage, self.i8_ptr)
        builder.call(self.pthread_key_create, [key_storage_ptr, ir.Constant(self.i8_ptr, None)])
        tls_key_value = builder.load(key_storage)
        builder.store(tls_key_value, self.tls_thread_entry_key)

        # Register main thread
        builder.call(self.gc_register_thread, [])

        # ============================================================
        # Spawn GC Thread
        # ============================================================
        # Create a detached thread to run gc_thread_main
        # The thread will run until gc_thread_running is set to 0

        # Allocate pthread_t (8 bytes on 64-bit, but allocate 64 for safety)
        thread_handle_size = ir.Constant(self.i64, 64)
        thread_handle_ptr = builder.call(self.codegen.malloc, [thread_handle_size])
        builder.store(thread_handle_ptr, self.gc_thread_handle)

        # Allocate pthread_attr_t for detached attribute
        attr_size = ir.Constant(self.i64, 64)
        attr_ptr = builder.call(self.codegen.malloc, [attr_size])
        builder.call(self.pthread_attr_init, [attr_ptr])

        # Set detached state (PTHREAD_CREATE_DETACHED = 1 on most systems)
        builder.call(self.pthread_attr_setdetachstate, [
            attr_ptr, ir.Constant(self.i32, 1)
        ])

        # Get function pointer for gc_thread_main
        gc_thread_fn_ptr = builder.bitcast(self.gc_thread_main, self.i8_ptr)

        # Create the GC thread
        builder.call(self.pthread_create, [
            thread_handle_ptr,      # pthread_t*
            attr_ptr,               # pthread_attr_t* (detached)
            gc_thread_fn_ptr,       # start_routine
            ir.Constant(self.i8_ptr, None)  # arg (not used)
        ])

        # Free the attribute (thread is already created)
        builder.call(self.codegen.free, [attr_ptr])

        # Initialize mark worklist for concurrent marking
        builder.call(self.gc_mark_worklist_init, [])

        builder.ret_void()

    def _implement_gc_register_thread(self):
        """Register the calling thread with the GC.

        Allocates a ThreadEntry, initializes it with the thread's TLS locations,
        and adds it to the global registry under mutex protection.
        """
        func = self.gc_register_thread

        entry = func.append_basic_block("entry")
        already_registered = func.append_basic_block("already_registered")
        do_register = func.append_basic_block("do_register")

        builder = ir.IRBuilder(entry)

        # Check if already registered (pthread TLS entry not null)
        tls_key = builder.load(self.tls_thread_entry_key)
        current_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        current_entry = builder.bitcast(current_entry_i8, self.thread_entry_type.as_pointer())
        current_entry_int = builder.ptrtoint(current_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', current_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_registered, already_registered, do_register)

        # Already registered - return
        builder.position_at_end(already_registered)
        builder.ret_void()

        # Do registration
        builder.position_at_end(do_register)

        # Allocate ThreadEntry (168 bytes = 21 fields × 8 bytes)
        entry_size = ir.Constant(self.i64, 168)
        raw_entry = builder.call(self.codegen.malloc, [entry_size])
        new_entry = builder.bitcast(raw_entry, self.thread_entry_type.as_pointer())

        # Get current thread ID
        thread_id = builder.call(self.pthread_self, [])

        # Initialize ThreadEntry fields
        # Field 0: thread_id
        tid_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(thread_id, tid_ptr)

        # Field 1: shadow_stack_head - direct frame pointer (not pointer to TLS)
        # Initialize to NULL; push_frame_inline will update this directly
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

        # Fields 6-8: TLAB pointers = null
        for i in [6, 7, 8]:
            tlab_ptr = builder.gep(new_entry, [
                ir.Constant(self.i32, 0), ir.Constant(self.i32, i)
            ], inbounds=True)
            builder.store(ir.Constant(self.i8_ptr, None), tlab_ptr)

        # Field 9: alloc_list = null (per-thread allocation list)
        alloc_list_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), alloc_list_ptr)

        # Field 10: tlab_epoch = 0
        tlab_epoch_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 10)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), tlab_epoch_ptr)

        # Field 11: next = null (will be set when linking)
        next_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_ptr)

        # ============================================================
        # Segmented Shadow Stack Initialization (Phase 5)
        # ============================================================
        # Allocate first segment for this thread's shadow stack
        first_segment = builder.call(self.gc_segment_alloc, [])
        first_segment_i8 = builder.bitcast(first_segment, self.i8_ptr)

        # Field 12: segment_base - first segment pointer (never changes)
        seg_base_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 12)
        ], inbounds=True)
        builder.store(first_segment_i8, seg_base_ptr)

        # Field 13: segment_current - active segment (initially same as base)
        seg_curr_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 13)
        ], inbounds=True)
        builder.store(first_segment_i8, seg_curr_ptr)

        # Field 14: slot_index = 0 (no slots used yet)
        slot_idx_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 14)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), slot_idx_ptr)

        # ============================================================
        # Scope Arena Initialization (Phase 6)
        # ============================================================
        # Fields 15-17: arena pointers = null (no active arena at thread start)
        for i in [15, 16, 17]:
            arena_ptr = builder.gep(new_entry, [
                ir.Constant(self.i32, 0), ir.Constant(self.i32, i)
            ], inbounds=True)
            builder.store(ir.Constant(self.i8_ptr, None), arena_ptr)

        # ============================================================
        # Per-Thread Handle Pool Initialization (Phase 7)
        # ============================================================
        # Fields 18-20: handle pool indices = 0 (empty pool, will refill on first alloc)
        # Field 18: handle_pool_start = 0
        pool_start_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 18)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), pool_start_ptr)

        # Field 19: handle_pool_next = 0
        pool_next_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 19)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), pool_next_ptr)

        # Field 20: handle_pool_end = 0 (pool_next >= pool_end means empty)
        pool_end_ptr = builder.gep(new_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 20)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), pool_end_ptr)

        # Also update TLS globals for fast access from frame functions
        builder.store(first_segment, self.tls_segment_base)
        builder.store(first_segment, self.tls_segment_current)
        builder.store(ir.Constant(self.i64, 0), self.tls_slot_index)

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

        # Store in pthread TLS (see BUG-023 for llvmlite TLS issue)
        tls_key = builder.load(self.tls_thread_entry_key)
        new_entry_i8 = builder.bitcast(new_entry, self.i8_ptr)
        builder.call(self.pthread_setspecific, [tls_key, new_entry_i8])

        # Also store in global for compatibility
        builder.store(new_entry, self.tls_thread_entry)

        # Initialize TLAB for this thread (allocates 256KB buffer)
        # Pass thread entry directly since TLS may not be readable by callee yet
        builder.call(self.gc_tlab_init, [new_entry])

        builder.ret_void()

    def _implement_gc_unregister_thread(self):
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

        # Get current ThreadEntry from pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        my_entry_i8_raw = builder.call(self.pthread_getspecific, [tls_key])
        my_entry = builder.bitcast(my_entry_i8_raw, self.thread_entry_type.as_pointer())
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
        is_head = builder.icmp_unsigned('==', head_int, my_entry_int)
        builder.cbranch(is_head, found_at_head, search_loop)

        # Found at head - remove
        builder.position_at_end(found_at_head)
        my_next_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        next_entry_i8 = builder.load(my_next_ptr)
        next_entry = builder.bitcast(next_entry_i8, self.thread_entry_type.as_pointer())
        builder.store(next_entry, self.gc_thread_registry)
        builder.branch(cleanup)

        # Search for entry in list - use alloca for prev tracking
        builder.position_at_end(search_loop)
        prev_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="prev")
        builder.store(head, prev_alloca)
        builder.branch(search_check)

        # Check current position
        builder.position_at_end(search_check)
        prev_val = builder.load(prev_alloca)
        prev_next_ptr = builder.gep(prev_val, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        curr_i8 = builder.load(prev_next_ptr)
        curr = builder.bitcast(curr_i8, self.thread_entry_type.as_pointer())

        # Check if curr is null (not found - shouldn't happen)
        curr_int = builder.ptrtoint(curr, self.i64)
        curr_is_null = builder.icmp_unsigned('==', curr_int, ir.Constant(self.i64, 0))
        is_mine = builder.icmp_unsigned('==', curr_int, my_entry_int)

        # If curr is null, go to cleanup (shouldn't happen)
        with builder.if_then(curr_is_null):
            builder.branch(cleanup)

        # Check if we found our entry
        builder.cbranch(is_mine, found_in_list, search_next)

        # Found in list - unlink
        builder.position_at_end(found_in_list)
        my_next_ptr2 = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        my_next = builder.load(my_next_ptr2)
        # prev->next = my->next
        builder.store(my_next, prev_next_ptr)
        builder.branch(cleanup)

        # Continue search
        builder.position_at_end(search_next)
        builder.store(curr, prev_alloca)
        builder.branch(search_check)

        # Cleanup
        builder.position_at_end(cleanup)

        # Decrement thread count
        count = builder.load(self.gc_thread_count)
        new_count = builder.sub(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_thread_count)

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex])

        # ============================================================
        # Free segment chain (Phase 5)
        # ============================================================
        # Walk segments from segment_base via `next` pointers and munmap each
        seg_base_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 12)
        ], inbounds=True)
        seg_base_i8 = builder.load(seg_base_ptr)
        first_seg = builder.bitcast(seg_base_i8, self.stack_segment_type.as_pointer())

        # Create segment free loop
        seg_loop = func.append_basic_block("seg_free_loop")
        seg_free = func.append_basic_block("seg_free")
        seg_done = func.append_basic_block("seg_done")

        seg_alloca = builder.alloca(self.stack_segment_type.as_pointer(), name="seg_to_free")
        builder.store(first_seg, seg_alloca)
        builder.branch(seg_loop)

        # Segment free loop
        builder.position_at_end(seg_loop)
        seg = builder.load(seg_alloca)
        seg_int = builder.ptrtoint(seg, self.i64)
        seg_is_null = builder.icmp_unsigned('==', seg_int, ir.Constant(self.i64, 0))
        builder.cbranch(seg_is_null, seg_done, seg_free)

        # Free this segment
        builder.position_at_end(seg_free)
        # Get next before freeing
        next_ptr = builder.gep(seg, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        next_seg_i8 = builder.load(next_ptr)
        next_seg = builder.bitcast(next_seg_i8, self.stack_segment_type.as_pointer())

        # munmap this segment (4KB)
        seg_as_i8 = builder.bitcast(seg, self.i8_ptr)
        seg_size = ir.Constant(self.i64, self.SEGMENT_SIZE)
        builder.call(self.munmap, [seg_as_i8, seg_size])

        # Move to next segment
        builder.store(next_seg, seg_alloca)
        builder.branch(seg_loop)

        builder.position_at_end(seg_done)

        # ============================================================
        # Return unused handles from pool to free list (Phase 7)
        # ============================================================
        # If pool_next < pool_end, there are unused handles we should return
        return_handles = func.append_basic_block("return_handles")
        return_loop = func.append_basic_block("return_loop")
        return_done = func.append_basic_block("return_done")

        pool_next_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 19)
        ], inbounds=True)
        pool_end_ptr = builder.gep(my_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 20)
        ], inbounds=True)
        pool_next_val = builder.load(pool_next_ptr)
        pool_end_val = builder.load(pool_end_ptr)

        has_unused = builder.icmp_unsigned("<", pool_next_val, pool_end_val)
        builder.cbranch(has_unused, return_handles, return_done)

        # Lock gc_mutex to safely modify free list
        builder.position_at_end(return_handles)
        gc_mutex = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [gc_mutex])

        # Allocate loop variable
        ret_idx_alloca = builder.alloca(self.i64, name="ret_idx")
        builder.store(pool_next_val, ret_idx_alloca)
        builder.branch(return_loop)

        # Return each unused handle to free list
        builder.position_at_end(return_loop)
        ret_idx = builder.load(ret_idx_alloca)
        done_returning = builder.icmp_unsigned(">=", ret_idx, pool_end_val)

        return_one = func.append_basic_block("return_one")
        unlock_and_done = func.append_basic_block("unlock_and_done")

        builder.cbranch(done_returning, unlock_and_done, return_one)

        # Return one handle to free list
        builder.position_at_end(return_one)
        builder.call(self.gc_handle_free, [ret_idx])
        next_idx = builder.add(ret_idx, ir.Constant(self.i64, 1))
        builder.store(next_idx, ret_idx_alloca)
        builder.branch(return_loop)

        # Done returning - unlock mutex
        builder.position_at_end(unlock_and_done)
        builder.call(self.pthread_mutex_unlock, [gc_mutex])
        builder.branch(return_done)

        builder.position_at_end(return_done)

        # Free ThreadEntry
        my_entry_i8 = builder.bitcast(my_entry, self.i8_ptr)
        builder.call(self.codegen.free, [my_entry_i8])

        # Clear pthread TLS
        tls_key2 = builder.load(self.tls_thread_entry_key)
        builder.call(self.pthread_setspecific, [tls_key2, ir.Constant(self.i8_ptr, None)])

        # Also clear the global for compatibility
        builder.store(
            ir.Constant(self.thread_entry_type.as_pointer(), None),
            self.tls_thread_entry)

        # Clear segment TLS globals
        builder.store(
            ir.Constant(self.stack_segment_type.as_pointer(), None),
            self.tls_segment_base)
        builder.store(
            ir.Constant(self.stack_segment_type.as_pointer(), None),
            self.tls_segment_current)
        builder.store(ir.Constant(self.i64, 0), self.tls_slot_index)

        builder.ret_void()

    def _implement_gc_get_thread_entry(self):
        """Return the calling thread's ThreadEntry from pthread TLS."""
        func = self.gc_get_thread_entry

        entry_block = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry_block)

        # Get from pthread TLS (see BUG-023)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        builder.ret(thread_entry)

    def _implement_gc_push_frame(self):
        """Push a new frame onto the shadow stack.

        Phase 3: Takes i64* handle_slots instead of i8** roots.
        Uses thread-local storage for the frame chain.
        """
        func = self.gc_push_frame
        func.args[0].name = "num_roots"
        func.args[1].name = "handle_slots"

        entry = func.append_basic_block("entry")
        update_entry = func.append_basic_block("update_entry")
        done = func.append_basic_block("done")
        builder = ir.IRBuilder(entry)

        num_roots = func.args[0]
        handle_slots = func.args[1]

        # Allocate frame struct (24 bytes: parent + num_roots + handle_slots_ptr)
        frame_size = ir.Constant(self.i64, 24)
        raw_frame = builder.call(self.codegen.malloc, [frame_size])
        frame = builder.bitcast(raw_frame, self.gc_frame_type.as_pointer())

        # Set parent to current TLS top
        old_top = builder.load(self.tls_frame_top)
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(old_top, parent_ptr)

        # Set num_roots
        num_roots_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(num_roots, num_roots_ptr)

        # Set handle_slots pointer (Phase 3: i64* instead of i8**)
        slots_ptr_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(handle_slots, slots_ptr_ptr)

        # Update TLS frame top
        builder.store(raw_frame, self.tls_frame_top)

        # NOTE: We no longer update the global gc_frame_top/gc_frame_depth
        # as they cause race conditions in multi-threaded programs.
        # All shadow stack operations now use thread-local storage.

        # Increment TLS frame depth
        depth = builder.load(self.tls_frame_depth)
        new_depth = builder.add(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.tls_frame_depth)

        # Update ThreadEntry.stack_depth if registered (use pthread TLS)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        entry_int = builder.ptrtoint(thread_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_registered, update_entry, done)

        builder.position_at_end(update_entry)
        te_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(new_depth, te_depth_ptr)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret(raw_frame)

    def _implement_gc_pop_frame(self):
        """Pop a frame from the calling thread's shadow stack.

        Uses thread-local storage for the frame chain.
        """
        func = self.gc_pop_frame
        func.args[0].name = "frame_ptr"

        entry = func.append_basic_block("entry")
        update_entry = func.append_basic_block("update_entry")
        done = func.append_basic_block("done")
        builder = ir.IRBuilder(entry)

        frame_ptr = func.args[0]
        frame = builder.bitcast(frame_ptr, self.gc_frame_type.as_pointer())

        # Get parent and set as new TLS top
        parent_ptr = builder.gep(frame, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        parent = builder.load(parent_ptr)
        builder.store(parent, self.tls_frame_top)

        # NOTE: We no longer update the global gc_frame_top/gc_frame_depth
        # as they cause race conditions in multi-threaded programs.

        # Decrement TLS frame depth
        depth = builder.load(self.tls_frame_depth)
        new_depth = builder.sub(depth, ir.Constant(self.i64, 1))
        builder.store(new_depth, self.tls_frame_depth)

        # Update ThreadEntry.stack_depth if registered (use pthread TLS)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        entry_int = builder.ptrtoint(thread_entry, self.i64)
        is_registered = builder.icmp_unsigned(
            '!=', entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_registered, update_entry, done)

        builder.position_at_end(update_entry)
        te_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(new_depth, te_depth_ptr)
        builder.branch(done)

        builder.position_at_end(done)
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
        """Allocate memory with GC tracking.

        Thread-safe implementation using:
        - TLAB for fast-path object memory allocation (no locking)
        - Per-thread allocation lists (no locking)
        - Mutex-protected handle allocation (shared resource)

        Falls back to mutex-protected malloc if TLAB is unavailable/full.
        """
        func = self.gc_alloc
        func.args[0].name = "user_size"
        func.args[1].name = "type_id"

        entry = func.append_basic_block("entry")
        try_tlab = func.append_basic_block("try_tlab")
        tlab_ok = func.append_basic_block("tlab_ok")
        try_refill = func.append_basic_block("try_refill")
        retry_tlab = func.append_basic_block("retry_tlab")
        tlab_retry_ok = func.append_basic_block("tlab_retry_ok")
        fallback_malloc = func.append_basic_block("fallback_malloc")
        have_block_tlab = func.append_basic_block("have_block_tlab")
        have_block_malloc = func.append_basic_block("have_block_malloc")
        init_header = func.append_basic_block("init_header")
        alloc_handle = func.append_basic_block("alloc_handle")
        # Per-thread handle pool allocation (Phase 7)
        try_handle_pool = func.append_basic_block("try_handle_pool")
        handle_pool_refill = func.append_basic_block("handle_pool_refill")
        have_handle = func.append_basic_block("have_handle")
        add_to_list = func.append_basic_block("add_to_list")
        finish = func.append_basic_block("finish")

        builder = ir.IRBuilder(entry)

        user_size = func.args[0]
        type_id = func.args[1]

        # Total size = header + user_size, aligned to 8 bytes
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        total_size = builder.add(user_size, header_size)

        # Align to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.and_(
            builder.add(total_size, seven),
            ir.Constant(self.i64, ~7 & 0xFFFFFFFFFFFFFFFF)
        )

        # Allocate stack slots for block pointer, is_tlab flag, and tlab_base
        block_alloca = builder.alloca(self.i8_ptr, name="block")
        is_tlab_alloca = builder.alloca(self.i64, name="is_tlab")
        tlab_base_alloca = builder.alloca(self.i8_ptr, name="tlab_base")
        builder.store(ir.Constant(self.i64, 0), is_tlab_alloca)
        builder.store(ir.Constant(self.i8_ptr, None), tlab_base_alloca)
        builder.branch(try_tlab)

        # ============================================================
        # Try TLAB allocation (fast path - no locking)
        # ============================================================
        builder.position_at_end(try_tlab)
        tlab_block = builder.call(self.gc_tlab_alloc, [aligned_size])
        tlab_block_int = builder.ptrtoint(tlab_block, self.i64)
        tlab_success = builder.icmp_unsigned("!=", tlab_block_int, ir.Constant(self.i64, 0))
        builder.cbranch(tlab_success, tlab_ok, try_refill)

        builder.position_at_end(tlab_ok)
        builder.store(tlab_block, block_alloca)
        builder.store(ir.Constant(self.i64, 1), is_tlab_alloca)  # Mark as TLAB allocation
        # Load and store current TLAB base from ThreadEntry for reference counting
        tls_key_ok = builder.load(self.tls_thread_entry_key)
        thread_entry_ok_i8 = builder.call(self.pthread_getspecific, [tls_key_ok])
        thread_entry_ok = builder.bitcast(thread_entry_ok_i8, self.thread_entry_type.as_pointer())
        tlab_base_ptr_ok = builder.gep(thread_entry_ok, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
        current_tlab_base_ok = builder.load(tlab_base_ptr_ok)
        builder.store(current_tlab_base_ok, tlab_base_alloca)
        builder.branch(have_block_tlab)

        # ============================================================
        # TLAB full - try refill and retry
        # ============================================================
        builder.position_at_end(try_refill)
        builder.call(self.gc_tlab_refill, [])
        builder.branch(retry_tlab)

        builder.position_at_end(retry_tlab)
        retry_block = builder.call(self.gc_tlab_alloc, [aligned_size])
        retry_block_int = builder.ptrtoint(retry_block, self.i64)
        retry_success = builder.icmp_unsigned("!=", retry_block_int, ir.Constant(self.i64, 0))
        builder.cbranch(retry_success, tlab_retry_ok, fallback_malloc)

        builder.position_at_end(tlab_retry_ok)
        builder.store(retry_block, block_alloca)
        builder.store(ir.Constant(self.i64, 1), is_tlab_alloca)  # Mark as TLAB allocation
        # Load and store current TLAB base (now points to newly refilled TLAB)
        tls_key_retry = builder.load(self.tls_thread_entry_key)
        thread_entry_retry_i8 = builder.call(self.pthread_getspecific, [tls_key_retry])
        thread_entry_retry = builder.bitcast(thread_entry_retry_i8, self.thread_entry_type.as_pointer())
        tlab_base_ptr_retry = builder.gep(thread_entry_retry, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
        current_tlab_base_retry = builder.load(tlab_base_ptr_retry)
        builder.store(current_tlab_base_retry, tlab_base_alloca)
        builder.branch(have_block_tlab)

        # ============================================================
        # Fallback to mutex-protected malloc (slow path)
        # ============================================================
        builder.position_at_end(fallback_malloc)
        # Lock mutex for malloc fallback
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])
        malloc_block = builder.call(self.codegen.malloc, [aligned_size])
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])
        builder.store(malloc_block, block_alloca)
        builder.store(ir.Constant(self.i64, 0), is_tlab_alloca)  # Not TLAB allocation
        builder.branch(have_block_malloc)

        # ============================================================
        # Merge paths - TLAB allocation
        # ============================================================
        builder.position_at_end(have_block_tlab)
        builder.branch(init_header)

        # Merge paths - malloc allocation
        builder.position_at_end(have_block_malloc)
        builder.branch(init_header)

        # ============================================================
        # Initialize object header
        # ============================================================
        builder.position_at_end(init_header)
        block = builder.load(block_alloca)
        is_tlab = builder.load(is_tlab_alloca)

        header = builder.bitcast(block, self.header_type.as_pointer())

        # Size field (offset 0) — store USER size, not total allocation size.
        # Marking functions (mark_list_tail_tagged, mark_array_data_ref, etc.)
        # divide this value by element size to compute element count.
        # Storing aligned_size (which includes HEADER_SIZE) would cause the
        # GC to over-scan by HEADER_SIZE/elem_size phantom elements past
        # the buffer, reading into adjacent objects or freed memory.
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(user_size, size_ptr)

        # Type ID field (offset 8) - extend i32 to i64
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id_64 = builder.zext(type_id, self.i64)
        builder.store(type_id_64, type_id_ptr)

        # Flags field (offset 16) - BIRTH-MARKING + TLAB flag
        # Objects are born marked with current mark value
        # If from TLAB, also set FLAG_TLAB bit
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_mark = builder.load(self.gc_current_mark_value)
        # Shift is_tlab (0 or 1) to bit position 4 for FLAG_TLAB
        tlab_flag = builder.shl(is_tlab, ir.Constant(self.i64, 4))
        flags_value = builder.or_(current_mark, tlab_flag)
        builder.store(flags_value, flags_ptr)

        # Forward pointer field (offset 24) - will store handle
        forward_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), forward_ptr)

        builder.branch(alloc_handle)

        # ============================================================
        # Allocate handle from per-thread pool (lock-free fast path)
        # ============================================================
        builder.position_at_end(alloc_handle)

        # Compute user_ptr (after header)
        block_for_ptr = builder.load(block_alloca)
        block_int = builder.ptrtoint(block_for_ptr, self.i64)
        user_ptr_int = builder.add(block_int, header_size)
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)

        # Zero user data to prevent GC from tracing stale TLAB/heap contents.
        # The GC marks buffer elements based on capacity (header size / elem_size),
        # not actual element count, so all slots must be zeroed.
        builder.call(self.codegen.memset, [
            user_ptr, ir.Constant(ir.IntType(8), 0), user_size
        ])

        # Allocate stack slot to store handle across blocks
        handle_alloca = builder.alloca(self.i64, name="handle")

        builder.branch(try_handle_pool)

        # ============================================================
        # Try per-thread handle pool (fast path - no locking)
        # ============================================================
        builder.position_at_end(try_handle_pool)
        pool_handle = builder.call(self.gc_handle_pool_alloc, [])
        pool_success = builder.icmp_unsigned("!=", pool_handle, ir.Constant(self.i64, 0))
        builder.store(pool_handle, handle_alloca)
        builder.cbranch(pool_success, have_handle, handle_pool_refill)

        # ============================================================
        # Refill handle pool (slow path - acquires mutex internally)
        # ============================================================
        builder.position_at_end(handle_pool_refill)
        builder.call(self.gc_handle_pool_refill, [])
        # Retry allocation - should succeed now
        retry_handle = builder.call(self.gc_handle_pool_alloc, [])
        builder.store(retry_handle, handle_alloca)
        builder.branch(have_handle)

        # ============================================================
        # Have handle - store pointer and update header
        # ============================================================
        builder.position_at_end(have_handle)
        handle = builder.load(handle_alloca)

        # Store pointer in handle table (no lock needed - this thread owns the handle)
        builder.call(self.gc_handle_store, [handle, user_ptr])

        # Store handle in header's forward field for ptr->handle lookup
        builder.store(handle, forward_ptr)

        builder.branch(add_to_list)

        # ============================================================
        # Add to per-thread allocation list (lock-free)
        # Each thread only modifies its own list, no mutex needed.
        # The sweeper coordinates via gc_registry_mutex when iterating.
        # ============================================================
        builder.position_at_end(add_to_list)

        # Allocate allocation node (ALWAYS use malloc for nodes, not TLAB)
        # This ensures sweep can safely free nodes without tracking TLAB status
        # malloc() is thread-safe on modern systems
        node_size = ir.Constant(self.i64, 32)  # sizeof(alloc_node) - now includes tlab_base
        raw_node = builder.call(self.codegen.malloc, [node_size])

        node = builder.bitcast(raw_node, self.alloc_node_type.as_pointer())

        # Initialize node fields before adding to list
        # node->next = NULL (will be set by gc_alloc_to_thread_list)
        next_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_ptr)

        # node->handle = handle
        handle_for_node = builder.load(handle_alloca)
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(handle_for_node, handle_ptr)

        # node->size = aligned_size
        node_size_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        aligned_size_reload = builder.load(size_ptr)  # Reload from header
        builder.store(aligned_size_reload, node_size_ptr)

        # node->tlab_base = tlab_base (for TLAB reclamation)
        tlab_base_for_node = builder.load(tlab_base_alloca)
        tlab_base_node_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(tlab_base_for_node, tlab_base_node_ptr)

        # If this is a TLAB allocation, increment the TLAB's live_count
        tlab_base_int = builder.ptrtoint(tlab_base_for_node, self.i64)
        is_tlab_alloc = builder.icmp_unsigned("!=", tlab_base_int, ir.Constant(self.i64, 0))
        with builder.if_then(is_tlab_alloc):
            # TLAB header is at tlab_base, live_count is field 0
            tlab_header = builder.bitcast(tlab_base_for_node, self.tlab_header_type.as_pointer())
            live_count_ptr = builder.gep(tlab_header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
            builder.atomic_rmw('add', live_count_ptr, ir.Constant(self.i64, 1), 'monotonic')

        # Add to per-thread allocation list (lock-free - thread-local data only)
        builder.call(self.gc_alloc_to_thread_list, [raw_node])

        builder.branch(finish)

        # ============================================================
        # Update statistics and return
        # ============================================================
        builder.position_at_end(finish)

        # Update GC statistics using atomic operations (BUG-018 fix)
        # Use 'monotonic' ordering - we only need atomicity, not synchronization
        total_allocs_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.atomic_rmw('add', total_allocs_ptr, ir.Constant(self.i64, 1), 'monotonic')

        aligned_size_final = builder.load(size_ptr)
        total_bytes_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.atomic_rmw('add', total_bytes_ptr, aligned_size_final, 'monotonic')

        allocs_since_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.atomic_rmw('add', allocs_since_ptr, ir.Constant(self.i64, 1), 'monotonic')

        bytes_since_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.atomic_rmw('add', bytes_since_ptr, aligned_size_final, 'monotonic')

        # Atomically increment allocation count for GC threshold triggering
        # Use atomic add to avoid race conditions in multi-threaded code
        builder.atomic_rmw('add', self.gc_alloc_count, ir.Constant(self.i64, 1), 'monotonic')

        # Return handle
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
        validate_ptr = func.append_basic_block("validate_ptr")
        check_tag = func.append_basic_block("check_tag")
        is_leaf = func.append_basic_block("is_leaf")
        process_leaf = func.append_basic_block("process_leaf")
        mark_key = func.append_basic_block("mark_key")
        after_key = func.append_basic_block("after_key")
        mark_value = func.append_basic_block("mark_value")
        after_value = func.append_basic_block("after_value")
        is_internal = func.append_basic_block("is_internal")
        child_loop = func.append_basic_block("child_loop")
        child_body = func.append_basic_block("child_body")
        validate_child = func.append_basic_block("validate_child")
        recurse_child = func.append_basic_block("recurse_child")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        root = func.args[0]
        flags = func.args[1]

        # Null check
        is_null = builder.icmp_unsigned("==", root, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, validate_ptr)

        # Validate pointer looks reasonable (>= 0x10000)
        builder.position_at_end(validate_ptr)
        ptr_int_val = builder.ptrtoint(root, self.i64)
        min_valid_ptr = ir.Constant(self.i64, 0x10000)
        ptr_looks_valid = builder.icmp_unsigned(">=", ptr_int_val, min_valid_ptr)
        builder.cbranch(ptr_looks_valid, check_tag, done)

        # Check tag bit (bit 0)
        builder.position_at_end(check_tag)
        ptr_as_int = builder.ptrtoint(root, self.i64)
        low_bit = builder.and_(ptr_as_int, ir.Constant(self.i64, 1))
        is_leaf_tag = builder.icmp_unsigned("!=", low_bit, ir.Constant(self.i64, 0))
        builder.cbranch(is_leaf_tag, is_leaf, is_internal)

        # Handle leaf - untag and mark, plus mark key/value if flags indicate
        builder.position_at_end(is_leaf)
        untagged_int = builder.and_(ptr_as_int, ir.Constant(self.i64, ~1 & 0xFFFFFFFFFFFFFFFF))
        # Store untagged_int for use in process_leaf
        untagged_int_ptr = builder.alloca(self.i64, name="untagged_int_storage")
        builder.store(untagged_int, untagged_int_ptr)
        # Validate untagged leaf pointer looks reasonable
        min_valid_leaf = ir.Constant(self.i64, 0x10000)
        leaf_looks_valid = builder.icmp_unsigned(">=", untagged_int, min_valid_leaf)
        builder.cbranch(leaf_looks_valid, process_leaf, done)

        # Process validated leaf
        builder.position_at_end(process_leaf)
        untagged_int_loaded = builder.load(untagged_int_ptr)
        untagged_ptr = builder.inttoptr(untagged_int_loaded, self.i8_ptr)
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
        # BUG-078 FIX: Map values are stored as raw pointers (via ptrtoint), NOT handles.
        # We must convert pointer to handle via gc_ptr_to_handle before marking,
        # just like we do for keys above.
        builder.position_at_end(mark_value)
        value_ptr_ptr = builder.gep(leaf_ptr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        value_as_int = builder.load(value_ptr_ptr)
        value_as_ptr = builder.inttoptr(value_as_int, self.i8_ptr)
        # Null check for value pointer
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

        # Validate children array pointer before marking
        children_int = builder.ptrtoint(builder.bitcast(children_ptr, self.i8_ptr), self.i64)
        min_valid_children = ir.Constant(self.i64, 0x10000)
        children_looks_valid = builder.icmp_unsigned(">=", children_int, min_valid_children)

        # Only mark and iterate children if pointer is valid
        mark_children = func.append_basic_block("mark_children")
        builder.cbranch(children_looks_valid, mark_children, done)

        builder.position_at_end(mark_children)
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

        # Validate child pointer before recursive call
        child_int = builder.ptrtoint(child_ptr, self.i64)
        min_valid_child = ir.Constant(self.i64, 0x10000)
        child_looks_valid = builder.icmp_unsigned(">=", child_int, min_valid_child)
        builder.cbranch(child_looks_valid, validate_child, recurse_child)

        # Valid child - recurse
        builder.position_at_end(validate_child)
        builder.call(func, [child_ptr, flags])
        builder.branch(recurse_child)

        # Invalid or done - continue to next
        builder.position_at_end(recurse_child)
        next_idx = builder.add(idx, ir.Constant(self.i32, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(child_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_mark_object(self):
        """Mark an object as live and push child references to worklist.

        Phase 5: Uses iterative worklist-based marking instead of recursion.
        Child handles are pushed to gc_mark_worklist for later processing by
        gc_mark_drain, avoiding stack overflow on deep object graphs.

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
        # JSON variant type marking blocks
        mark_json_string = func.append_basic_block("mark_json_string")
        mark_json_array = func.append_basic_block("mark_json_array")
        mark_json_object = func.append_basic_block("mark_json_object")
        # TaggedValue-based list tail marking (USE_TAGGED_VALUES = True)
        mark_list_tail_tagged = func.append_basic_block("mark_list_tail_tagged")
        # Legacy ref-based list tail marking (backward compatibility)
        mark_list_tail_ref = func.append_basic_block("mark_list_tail_ref")
        list_tail_ref_loop = func.append_basic_block("list_tail_ref_loop")
        list_tail_ref_check = func.append_basic_block("list_tail_ref_check")
        list_tail_ref_mark = func.append_basic_block("list_tail_ref_mark")
        list_tail_ref_next = func.append_basic_block("list_tail_ref_next")
        mark_array_data_ref = func.append_basic_block("mark_array_data_ref")
        array_data_ref_loop = func.append_basic_block("array_data_ref_loop")
        array_data_ref_check = func.append_basic_block("array_data_ref_check")
        array_data_ref_mark = func.append_basic_block("array_data_ref_mark")
        array_data_ref_next = func.append_basic_block("array_data_ref_next")
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

        # Also check if pointer looks valid (not a small integer like free list index)
        # Valid heap pointers are typically > 0x10000 (64KB)
        check_ptr_valid = func.append_basic_block("check_ptr_valid")
        builder.cbranch(is_null_ptr, done, check_ptr_valid)

        builder.position_at_end(check_ptr_valid)
        ptr_val = builder.ptrtoint(ptr, self.i64)
        min_valid_addr = ir.Constant(self.i64, 0x10000)  # 64KB
        ptr_looks_valid = builder.icmp_unsigned(">=", ptr_val, min_valid_addr)
        builder.cbranch(ptr_looks_valid, get_header, done)

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
        # Push child handle to worklist instead of recursive call
        builder.call(self.gc_mark_push, [field_handle])
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
        # JSON variant types - null/bool/int/float fall through to done (no children)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_NULL), done)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_BOOL), done)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_INT), done)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_FLOAT), done)
        # JSON reference types - mark the contained handle
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_STRING), mark_json_string)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_ARRAY), mark_json_array)
        switch.add_case(ir.Constant(self.i64, self.TYPE_JSON_OBJECT), mark_json_object)
        # TaggedValue-based list tail (USE_TAGGED_VALUES = True)
        switch.add_case(ir.Constant(self.i64, self.TYPE_LIST_TAIL), mark_list_tail_tagged)
        # Legacy ref-based marking (backward compatibility)
        switch.add_case(ir.Constant(self.i64, self.TYPE_LIST_TAIL_REF), mark_list_tail_ref)
        switch.add_case(ir.Constant(self.i64, self.TYPE_ARRAY_DATA_REF), mark_array_data_ref)

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
        # List struct: { i64 root (0), i64 len (1), i64 depth (2), i64 tail (3), i64 tail_len (4), i64 elem_size (5), i64 flags (6) }
        # Root and tail store raw pointers as i64 (via ptrtoint), need inttoptr to get pointers
        builder.position_at_end(mark_list)
        list_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i64, self.i64, self.i64]).as_pointer()
        list_typed = builder.bitcast(ptr, list_ptr_type)
        # Mark root - push to worklist
        root_i64_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        root_i64 = builder.load(root_i64_ptr)
        root_ptr = builder.inttoptr(root_i64, self.i8_ptr)  # Convert i64 to pointer
        root_handle = builder.call(self.gc_ptr_to_handle, [root_ptr])
        builder.call(self.gc_mark_push, [root_handle])  # Push to worklist
        # Mark tail - push to worklist
        tail_i64_ptr = builder.gep(list_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        tail_i64 = builder.load(tail_i64_ptr)
        tail_ptr = builder.inttoptr(tail_i64, self.i8_ptr)  # Convert i64 to pointer
        tail_handle = builder.call(self.gc_ptr_to_handle, [tail_ptr])
        builder.call(self.gc_mark_push, [tail_handle])  # Push to worklist
        builder.branch(done)

        # Mark Array: handle pointer at field 0
        # N-D Array struct (104 bytes):
        #   Field 0: handle (i64) - GC handle for data buffer
        #   Field 1: ndim (i64) - number of dimensions
        #   Field 2: shape [4 x i64] - dimensions
        #   Field 3: strides [4 x i64] - byte strides
        #   Field 4: offset (i64) - byte offset for views
        #   Field 5: elem_size (i64) - element size
        #   Field 6: type_id (i64) - element type
        # Handle stores raw pointer as i64 (via ptrtoint), need inttoptr to get pointer
        builder.position_at_end(mark_array)
        # Just read the first i64 at offset 0 (the handle field)
        handle_i64_ptr = builder.bitcast(ptr, self.i64.as_pointer())
        handle_i64 = builder.load(handle_i64_ptr)
        handle_ptr = builder.inttoptr(handle_i64, self.i8_ptr)  # Convert i64 to pointer
        owner_handle = builder.call(self.gc_ptr_to_handle, [handle_ptr])
        builder.call(self.gc_mark_push, [owner_handle])  # Push to worklist
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
        builder.call(self.gc_mark_push, [str_owner_handle])  # Push to worklist
        builder.branch(done)

        # Mark Channel: buffer pointer at offset 32 (4th i64 field)
        builder.position_at_end(mark_channel)
        channel_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i8_ptr]).as_pointer()
        channel_typed = builder.bitcast(ptr, channel_ptr_type)
        buffer_ptr_ptr = builder.gep(channel_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        buffer_ptr = builder.load(buffer_ptr_ptr)
        buffer_handle = builder.call(self.gc_ptr_to_handle, [buffer_ptr])
        builder.call(self.gc_mark_push, [buffer_handle])  # Push to worklist
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
        # Convert pointer to handle and push to worklist
        child_handle = builder.call(self.gc_ptr_to_handle, [child_to_mark])
        builder.call(self.gc_mark_push, [child_handle])  # Push to worklist
        builder.branch(pv_node_next)

        # Increment index and continue
        builder.position_at_end(pv_node_next)
        curr_idx = builder.load(pv_idx)
        next_idx = builder.add(curr_idx, ir.Constant(self.i64, 1))
        builder.store(next_idx, pv_idx)
        builder.branch(pv_node_loop)

        # ============================================================
        # Mark JSON variant types (first-class tagged union)
        # ============================================================
        # Each JSON variant is now a separate type with its own type ID.
        # Payload is 8 bytes (i64): primitives store value inline, reference
        # types store an i64 HANDLE that must be marked.
        #
        # TYPE_JSON_NULL/BOOL/INT/FLOAT: Fall through to done (no children)
        # TYPE_JSON_STRING/ARRAY/OBJECT: Mark the handle at offset 0
        # ============================================================

        # Mark JSON String: load handle at offset 0, push to worklist
        builder.position_at_end(mark_json_string)
        # ptr points to user data area (8 bytes containing i64 handle)
        json_str_handle_ptr = builder.bitcast(ptr, self.i64_ptr)
        json_str_handle = builder.load(json_str_handle_ptr)
        # Push handle to worklist (gc_mark_push handles null/0 handles)
        builder.call(self.gc_mark_push, [json_str_handle])
        builder.branch(done)

        # Mark JSON Array: load handle at offset 0, push to worklist
        builder.position_at_end(mark_json_array)
        json_arr_handle_ptr = builder.bitcast(ptr, self.i64_ptr)
        json_arr_handle = builder.load(json_arr_handle_ptr)
        builder.call(self.gc_mark_push, [json_arr_handle])
        builder.branch(done)

        # Mark JSON Object: load handle at offset 0, push to worklist
        builder.position_at_end(mark_json_object)
        json_obj_handle_ptr = builder.bitcast(ptr, self.i64_ptr)
        json_obj_handle = builder.load(json_obj_handle_ptr)
        builder.call(self.gc_mark_push, [json_obj_handle])
        builder.branch(done)

        # ============================================================
        # Mark LIST_TAIL (TaggedValue mode): Each element is a TaggedValue
        # ============================================================
        # With USE_TAGGED_VALUES = True, list tail buffers contain TaggedValues
        # {i64 type_id, i64 value}. We use tv_mark_array to iterate through
        # all elements and mark only those where type_id >= TYPE_HEAP_BASE.
        # ============================================================
        builder.position_at_end(mark_list_tail_tagged)
        # Get object size from header to calculate element count
        header_ptr_tv = builder.inttoptr(
            builder.sub(builder.ptrtoint(ptr, self.i64), ir.Constant(self.i64, self.HEADER_SIZE)),
            self.header_type.as_pointer()
        )
        size_ptr_tv = builder.gep(header_ptr_tv, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        buffer_size_tv = builder.load(size_ptr_tv)
        # Element count = size / 16 (TaggedValues are 16 bytes each)
        elem_count_tv = builder.udiv(buffer_size_tv, ir.Constant(self.i64, 16))
        # Cast buffer to TaggedValue pointer and call tv_mark_array
        tv_ptr = builder.bitcast(ptr, self.tagged_value_ptr_type)
        builder.call(self.tv_mark_array, [tv_ptr, elem_count_tv])
        builder.branch(done)

        # ============================================================
        # Mark LIST_TAIL_REF: Handle buffer for reference-type list elements
        # ============================================================
        # LEGACY: This was used before TaggedValues. Kept for backward
        # compatibility with any old objects that might still exist.
        # Each element is a raw i64 handle (8 bytes).
        # ============================================================
        builder.position_at_end(mark_list_tail_ref)
        # Get object size from header to calculate element count
        # Header is at ptr - HEADER_SIZE
        header_ptr_ref = builder.inttoptr(
            builder.sub(builder.ptrtoint(ptr, self.i64), ir.Constant(self.i64, self.HEADER_SIZE)),
            self.header_type.as_pointer()
        )
        size_ptr_ref = builder.gep(header_ptr_ref, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        buffer_size = builder.load(size_ptr_ref)
        # Element count = size / 8 (handles are i64 = 8 bytes)
        elem_count_ref = builder.udiv(buffer_size, ir.Constant(self.i64, 8))
        # Cast buffer to i64 array
        handles_ptr = builder.bitcast(ptr, self.i64_ptr)
        # Store for loop
        handles_ptr_alloca = builder.alloca(self.i64_ptr, name="handles_ptr_ref")
        builder.store(handles_ptr, handles_ptr_alloca)
        elem_count_alloca = builder.alloca(self.i64, name="elem_count_ref")
        builder.store(elem_count_ref, elem_count_alloca)
        # Index for loop
        idx_alloca_ref = builder.alloca(self.i64, name="idx_ref")
        builder.store(ir.Constant(self.i64, 0), idx_alloca_ref)
        builder.branch(list_tail_ref_loop)

        # Loop header: check if index < element count
        builder.position_at_end(list_tail_ref_loop)
        idx_ref = builder.load(idx_alloca_ref)
        count_ref = builder.load(elem_count_alloca)
        done_ref = builder.icmp_unsigned(">=", idx_ref, count_ref)
        builder.cbranch(done_ref, done, list_tail_ref_check)

        # Check if handle is non-zero
        builder.position_at_end(list_tail_ref_check)
        handles_ptr_val = builder.load(handles_ptr_alloca)
        idx_ref2 = builder.load(idx_alloca_ref)
        handle_ptr_ref = builder.gep(handles_ptr_val, [idx_ref2], inbounds=False)
        elem_handle = builder.load(handle_ptr_ref)
        is_zero = builder.icmp_unsigned("==", elem_handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_zero, list_tail_ref_next, list_tail_ref_mark)

        # Mark the handle
        builder.position_at_end(list_tail_ref_mark)
        # Reload the handle for this block (SSA requirement)
        handles_ptr_val2 = builder.load(handles_ptr_alloca)
        idx_ref3 = builder.load(idx_alloca_ref)
        handle_ptr_ref2 = builder.gep(handles_ptr_val2, [idx_ref3], inbounds=False)
        elem_handle2 = builder.load(handle_ptr_ref2)
        builder.call(self.gc_mark_push, [elem_handle2])
        builder.branch(list_tail_ref_next)

        # Increment index and continue
        builder.position_at_end(list_tail_ref_next)
        idx_ref4 = builder.load(idx_alloca_ref)
        next_idx_ref = builder.add(idx_ref4, ir.Constant(self.i64, 1))
        builder.store(next_idx_ref, idx_alloca_ref)
        builder.branch(list_tail_ref_loop)

        # ============================================================
        # Mark ARRAY_DATA_REF: Handle buffer for reference-type array elements
        # ============================================================
        # HANDLE STORAGE INVARIANT: This buffer contains i64 HANDLES, not pointers.
        # Identical pattern to LIST_TAIL_REF - arrays of reference types store
        # handles that must be marked during GC.
        #
        # Used by: Array<string>, Array<List<T>>, Array<UDT>, etc.
        # Allocated via: array_new_ref() which sets TYPE_ARRAY_DATA_REF type ID
        # ============================================================
        builder.position_at_end(mark_array_data_ref)
        # Get object size from header to calculate element count
        # Header is at ptr - HEADER_SIZE
        header_ptr_arr = builder.inttoptr(
            builder.sub(builder.ptrtoint(ptr, self.i64), ir.Constant(self.i64, self.HEADER_SIZE)),
            self.header_type.as_pointer()
        )
        size_ptr_arr = builder.gep(header_ptr_arr, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        buffer_size_arr = builder.load(size_ptr_arr)
        # Element count = size / 8 (handles are i64 = 8 bytes)
        elem_count_arr = builder.udiv(buffer_size_arr, ir.Constant(self.i64, 8))
        # Cast buffer to i64 array
        handles_ptr_arr = builder.bitcast(ptr, self.i64_ptr)
        # Store for loop
        handles_ptr_arr_alloca = builder.alloca(self.i64_ptr, name="handles_ptr_arr")
        builder.store(handles_ptr_arr, handles_ptr_arr_alloca)
        elem_count_arr_alloca = builder.alloca(self.i64, name="elem_count_arr")
        builder.store(elem_count_arr, elem_count_arr_alloca)
        # Index for loop
        idx_arr_alloca = builder.alloca(self.i64, name="idx_arr")
        builder.store(ir.Constant(self.i64, 0), idx_arr_alloca)
        builder.branch(array_data_ref_loop)

        # Loop header: check if index < element count
        builder.position_at_end(array_data_ref_loop)
        idx_arr = builder.load(idx_arr_alloca)
        count_arr = builder.load(elem_count_arr_alloca)
        done_arr = builder.icmp_unsigned(">=", idx_arr, count_arr)
        builder.cbranch(done_arr, done, array_data_ref_check)

        # Check if handle is non-zero
        builder.position_at_end(array_data_ref_check)
        handles_ptr_arr_val = builder.load(handles_ptr_arr_alloca)
        idx_arr2 = builder.load(idx_arr_alloca)
        handle_ptr_arr = builder.gep(handles_ptr_arr_val, [idx_arr2], inbounds=False)
        elem_handle_arr = builder.load(handle_ptr_arr)
        is_zero_arr = builder.icmp_unsigned("==", elem_handle_arr, ir.Constant(self.i64, 0))
        builder.cbranch(is_zero_arr, array_data_ref_next, array_data_ref_mark)

        # Mark the handle
        builder.position_at_end(array_data_ref_mark)
        # Reload the handle for this block (SSA requirement)
        handles_ptr_arr_val2 = builder.load(handles_ptr_arr_alloca)
        idx_arr3 = builder.load(idx_arr_alloca)
        handle_ptr_arr2 = builder.gep(handles_ptr_arr_val2, [idx_arr3], inbounds=False)
        elem_handle_arr2 = builder.load(handle_ptr_arr2)
        builder.call(self.gc_mark_push, [elem_handle_arr2])
        builder.branch(array_data_ref_next)

        # Increment index and continue
        builder.position_at_end(array_data_ref_next)
        idx_arr4 = builder.load(idx_arr_alloca)
        next_idx_arr = builder.add(idx_arr4, ir.Constant(self.i64, 1))
        builder.store(next_idx_arr, idx_arr_alloca)
        builder.branch(array_data_ref_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_scan_roots(self):
        """Scan roots from all registered threads using segmented shadow stacks.

        Phase 5: Uses segment-based shadow stack scanning.
        For each thread, walks segments from segment_base via `next` pointers,
        scanning slots up to slot_index (the watermark).
        """
        func = self.gc_scan_roots

        entry = func.append_basic_block("entry")
        thread_loop = func.append_basic_block("thread_loop")
        process_thread = func.append_basic_block("process_thread")
        segment_loop = func.append_basic_block("segment_loop")
        scan_segment = func.append_basic_block("scan_segment")
        slot_loop = func.append_basic_block("slot_loop")
        check_handle = func.append_basic_block("check_handle")
        do_mark = func.append_basic_block("do_mark")
        next_slot = func.append_basic_block("next_slot")
        next_segment = func.append_basic_block("next_segment")
        next_thread = func.append_basic_block("next_thread")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Lock registry for iteration (brief hold)
        mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [mutex])

        # Allocate storage for current thread pointer
        curr_thread_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="curr_thread")

        # Start with head of registry
        first_thread = builder.load(self.gc_thread_registry)
        builder.store(first_thread, curr_thread_alloca)

        # Allocate storage for segment iteration
        curr_segment_alloca = builder.alloca(self.stack_segment_type.as_pointer(), name="curr_segment")
        watermark_alloca = builder.alloca(self.i64, name="watermark")  # Total slots to scan
        scanned_alloca = builder.alloca(self.i64, name="scanned")  # Slots scanned so far
        slot_idx_alloca = builder.alloca(self.i64, name="slot_idx")  # Current slot in segment

        builder.branch(thread_loop)

        # Thread loop
        builder.position_at_end(thread_loop)
        curr_thread = builder.load(curr_thread_alloca)

        # Check if null
        thread_int = builder.ptrtoint(curr_thread, self.i64)
        thread_is_null = builder.icmp_unsigned('==', thread_int, ir.Constant(self.i64, 0))
        builder.cbranch(thread_is_null, done, process_thread)

        # Process this thread - scan its segmented shadow stack
        builder.position_at_end(process_thread)

        # Get segment_base (offset 96) - first segment pointer
        seg_base_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 12)
        ], inbounds=True)
        seg_base_i8 = builder.load(seg_base_ptr)
        seg_base = builder.bitcast(seg_base_i8, self.stack_segment_type.as_pointer())

        # Get slot_index (offset 112) - this is the watermark (total slots in use)
        slot_idx_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 14)
        ], inbounds=True)
        watermark = builder.load(slot_idx_ptr)
        builder.store(watermark, watermark_alloca)

        # Check if segment_base is valid (not null)
        seg_base_int = builder.ptrtoint(seg_base, self.i64)
        seg_base_valid = builder.icmp_unsigned('!=', seg_base_int, ir.Constant(self.i64, 0))

        # Also check watermark > 0 (any slots to scan)
        has_slots = builder.icmp_unsigned('>', watermark, ir.Constant(self.i64, 0))
        should_scan = builder.and_(seg_base_valid, has_slots)
        builder.cbranch(should_scan, segment_loop, next_thread)

        # Segment loop: iterate segments from base
        builder.position_at_end(segment_loop)
        builder.store(seg_base, curr_segment_alloca)
        builder.store(ir.Constant(self.i64, 0), scanned_alloca)
        builder.branch(scan_segment)

        # Scan current segment
        builder.position_at_end(scan_segment)
        segment = builder.load(curr_segment_alloca)
        seg_int = builder.ptrtoint(segment, self.i64)
        is_null_segment = builder.icmp_unsigned('==', seg_int, ir.Constant(self.i64, 0))

        # Check if we've scanned enough slots (reached watermark)
        scanned = builder.load(scanned_alloca)
        wm = builder.load(watermark_alloca)
        done_scanning = builder.icmp_unsigned('>=', scanned, wm)

        # Stop if segment is null OR we've reached watermark
        should_stop = builder.or_(is_null_segment, done_scanning)
        builder.cbranch(should_stop, next_thread, slot_loop)

        # Initialize slot loop for this segment
        builder.position_at_end(slot_loop)
        builder.store(ir.Constant(self.i64, 0), slot_idx_alloca)
        builder.branch(check_handle)

        # Check each handle in segment
        builder.position_at_end(check_handle)
        slot_in_seg = builder.load(slot_idx_alloca)
        slots_per_seg = ir.Constant(self.i64, self.SEGMENT_SLOTS)

        # Calculate how many slots to scan in this segment
        # slots_to_scan = min(SEGMENT_SLOTS, watermark - scanned)
        scanned_now = builder.load(scanned_alloca)
        remaining = builder.sub(wm, scanned_now)
        remaining_capped = builder.select(
            builder.icmp_unsigned('<', remaining, slots_per_seg),
            remaining,
            slots_per_seg
        )

        # Done with this segment?
        done_segment = builder.icmp_unsigned('>=', slot_in_seg, remaining_capped)
        builder.cbranch(done_segment, next_segment, do_mark)

        # Load and mark handle
        builder.position_at_end(do_mark)
        # Get segment slots array (field 3)
        slots_ptr = builder.gep(segment, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 3),  # slots array
            ir.Constant(self.i32, 0)   # first element
        ], inbounds=True)

        current_slot = builder.load(slot_idx_alloca)
        slot_ptr = builder.gep(slots_ptr, [current_slot], inbounds=True)
        handle = builder.load(slot_ptr)

        # Skip if handle is 0 (null)
        is_null_handle = builder.icmp_unsigned('==', handle, ir.Constant(self.i64, 0))

        # Validate handle is within range
        next_handle = builder.load(self.gc_next_handle)
        handle_in_range = builder.icmp_unsigned('<', handle, next_handle)
        handle_sane = builder.icmp_unsigned('<', handle, ir.Constant(self.i64, 100000000))
        handle_valid = builder.and_(handle_in_range, handle_sane)

        should_skip = builder.or_(is_null_handle, builder.not_(handle_valid))

        mark_block = func.append_basic_block("mark_handle")
        builder.cbranch(should_skip, next_slot, mark_block)

        builder.position_at_end(mark_block)
        builder.call(self.gc_mark_object, [handle])
        builder.branch(next_slot)

        # Advance to next slot
        builder.position_at_end(next_slot)
        curr_slot = builder.load(slot_idx_alloca)
        next_slot_idx = builder.add(curr_slot, ir.Constant(self.i64, 1))
        builder.store(next_slot_idx, slot_idx_alloca)
        builder.branch(check_handle)

        # Move to next segment
        builder.position_at_end(next_segment)
        # Update scanned count
        scanned_before = builder.load(scanned_alloca)
        # Use slots_per_seg as we always scan full segments until last one
        scanned_after = builder.add(scanned_before, slots_per_seg)
        builder.store(scanned_after, scanned_alloca)

        # Get next segment: segment->next (field 1)
        next_ptr = builder.gep(segment, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        next_seg_i8 = builder.load(next_ptr)
        next_seg = builder.bitcast(next_seg_i8, self.stack_segment_type.as_pointer())
        builder.store(next_seg, curr_segment_alloca)
        builder.branch(scan_segment)

        # Move to next thread
        builder.position_at_end(next_thread)
        next_thread_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        next_thread_i8 = builder.load(next_thread_ptr)
        next_thread_typed = builder.bitcast(next_thread_i8, self.thread_entry_type.as_pointer())
        builder.store(next_thread_typed, curr_thread_alloca)
        builder.branch(thread_loop)

        # Done
        builder.position_at_end(done)
        builder.call(self.pthread_mutex_unlock, [mutex])
        builder.ret_void()

    def _implement_gc_sweep(self):
        """Sweep all per-thread allocation lists and free unmarked objects.

        Delegates to gc_sweep_thread_lists which iterates all registered threads
        and sweeps their per-thread allocation lists.

        This replaces the old global gc_alloc_list approach with thread-safe
        per-thread lists that don't require locking during allocation.
        """
        func = self.gc_sweep

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Delegate to thread-aware sweep that handles per-thread allocation lists
        builder.call(self.gc_sweep_thread_lists, [])

        # Reset allocation counter
        builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)

        # Note: Sweep statistics are not currently tracked in the thread-list
        # sweep. For accurate stats, gc_sweep_thread_lists would need to be
        # enhanced to return/accumulate stats.

        builder.ret_void()

    def _implement_gc_collect(self):
        """Run a full garbage collection cycle with watermark protocol.

        Phase 9: Collection Orchestration with MI-6 Deferred Reclamation
        and Thread Registry support:
        1. Check if GC enabled and not already in progress
        2. Set gc_in_progress = 1, gc_phase = 1 (WATERMARK)
        3. Increment gc_cycle_id
        4. (Single-threaded: threads acknowledge at next safepoint)
        5. Promote retired handles from previous cycle to free list (MI-6)
        6. Set gc_phase = 2 (MARKING), flip mark value
        7. Mark phase: scan roots from all registered threads
        8. Set gc_phase = 3 (SWEEPING)
        9. Sweep phase: free unmarked objects (retire handles)
        10. Reset watermark_active for all threads
        11. Set gc_phase = 0 (IDLE), gc_in_progress = 0
        12. Update statistics

        MI-6 Deferred Reclamation:
        Handles swept in cycle N are added to the retired list, not the free list.
        At the start of cycle N+1, retired handles are promoted to the free list.
        """
        func = self.gc_collect

        entry = func.append_basic_block("entry")
        check_enabled = func.append_basic_block("check_enabled")
        do_collection = func.append_basic_block("do_collection")
        reset_loop = func.append_basic_block("reset_loop")
        reset_thread = func.append_basic_block("reset_thread")
        reset_next = func.append_basic_block("reset_next")
        cleanup = func.append_basic_block("cleanup")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Check if GC enabled
        gc_enabled = builder.load(self.gc_enabled)
        builder.cbranch(gc_enabled, check_enabled, done)

        builder.position_at_end(check_enabled)
        # Atomically try to set gc_in_progress from 0 to 1
        # This prevents multiple threads from entering gc_collect simultaneously
        in_prog_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        # cmpxchg returns {old_value, success_bool} - we check if old was 0
        cmpxchg_result = builder.cmpxchg(in_prog_ptr, ir.Constant(self.i64, 0),
                                          ir.Constant(self.i64, 1), 'acquire', 'monotonic')
        old_value = builder.extract_value(cmpxchg_result, 0)
        was_zero = builder.icmp_unsigned("==", old_value, ir.Constant(self.i64, 0))
        builder.cbranch(was_zero, do_collection, done)

        builder.position_at_end(do_collection)

        # Set gc_phase = 1 (WATERMARK) to signal threads to acknowledge
        builder.store(ir.Constant(self.i64, 1), self.gc_phase)

        # Increment gc_cycle_id
        cycle = builder.load(self.gc_cycle_id)
        new_cycle = builder.add(cycle, ir.Constant(self.i64, 1))
        builder.store(new_cycle, self.gc_cycle_id)

        # Phase 2 Watermark Protocol:
        # ALWAYS wait for all OTHER threads to acknowledge watermark before marking.
        # The calling thread (if a mutator) is safe to scan because it's blocked here.
        # gc_wait_for_watermarks skips the calling thread to avoid self-deadlock.
        builder.call(self.gc_wait_for_watermarks, [])

        # MI-6: Promote retired handles from previous cycle to free list
        # This makes handles retired in cycle N-1 available for reuse in cycle N
        builder.call(self.gc_promote_retired_handles, [])

        # Set gc_phase = 2 (MARKING)
        builder.store(ir.Constant(self.i64, 2), self.gc_phase)

        # Phase 9: Flip gc_current_mark_value BEFORE mark phase
        # This ensures newly allocated objects (born with OLD mark value) will be
        # properly traversed, since they won't appear "already marked" with new value
        old_mark = builder.load(self.gc_current_mark_value)
        new_mark = builder.xor(old_mark, ir.Constant(self.i64, 1))
        builder.store(new_mark, self.gc_current_mark_value)

        # Phase 5: Reset mark worklist for new cycle
        builder.call(self.gc_mark_worklist_reset, [])

        # Phase 9: Mark phase - scan roots from all registered threads
        # gc_scan_roots iterates the thread registry and marks from each thread's shadow stack
        builder.call(self.gc_scan_roots, [])

        # Phase 5: Drain the mark worklist (iterative marking)
        builder.call(self.gc_mark_drain, [])

        # Set gc_phase = 3 (SWEEPING)
        builder.store(ir.Constant(self.i64, 3), self.gc_phase)

        # Phase 9: Sweep phase - free unmarked objects
        builder.call(self.gc_sweep, [])

        # Reset watermark_active for all threads
        # Lock registry mutex to prevent threads from unregistering during iteration
        reset_mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [reset_mutex])

        # Allocate storage for loop variable
        reset_curr_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="reset_curr")
        first_reset = builder.load(self.gc_thread_registry)
        builder.store(first_reset, reset_curr_alloca)
        builder.branch(reset_loop)

        builder.position_at_end(reset_loop)
        reset_curr = builder.load(reset_curr_alloca)
        reset_int = builder.ptrtoint(reset_curr, self.i64)
        reset_null = builder.icmp_unsigned('==', reset_int, ir.Constant(self.i64, 0))
        builder.cbranch(reset_null, cleanup, reset_thread)

        builder.position_at_end(reset_thread)
        # Reset watermark_active = 0
        reset_wm_ptr = builder.gep(reset_curr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), reset_wm_ptr)

        # Also reset watermark_depth = 0
        reset_depth_ptr = builder.gep(reset_curr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), reset_depth_ptr)

        # Next thread
        builder.branch(reset_next)

        builder.position_at_end(reset_next)
        reset_next_ptr = builder.gep(reset_curr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        reset_next_i8 = builder.load(reset_next_ptr)
        reset_next_typed = builder.bitcast(
            reset_next_i8, self.thread_entry_type.as_pointer())
        builder.store(reset_next_typed, reset_curr_alloca)
        builder.branch(reset_loop)

        # Cleanup - runs after successful GC
        builder.position_at_end(cleanup)

        # Unlock registry mutex after watermark reset loop
        builder.call(self.pthread_mutex_unlock, [reset_mutex])

        # Set gc_phase = 0 (IDLE)
        builder.store(ir.Constant(self.i64, 0), self.gc_phase)

        # Phase 9: Update statistics
        # Increment collections_completed atomically (BUG-018 fix)
        collections_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.atomic_rmw('add', collections_ptr, ir.Constant(self.i64, 1), 'monotonic')

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
        in_prog_ptr_cleanup = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), in_prog_ptr_cleanup)

        # Also set gc_complete = 1 for compatibility
        complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 1), complete_ptr)

        builder.branch(done)

        # Done - just return
        builder.position_at_end(done)
        builder.ret_void()

    # ========================================================================
    # TaggedValue Helper Function Implementations
    # ========================================================================

    def _implement_tv_is_heap_type(self):
        """Implement tv_is_heap_type(type_id) -> bool.

        Returns true if type_id >= TYPE_HEAP_BASE (64), meaning the value
        field of a TaggedValue with this type_id is a GC handle that needs tracing.
        """
        func = self.tv_is_heap

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        type_id = func.args[0]
        is_heap = builder.icmp_unsigned('>=', type_id, ir.Constant(self.i64, self.TYPE_HEAP_BASE))
        builder.ret(is_heap)

    def _implement_tv_mark(self):
        """Implement tv_mark(tv_ptr) -> void.

        Marks the value in a TaggedValue if it's a heap reference.
        Reads the type_id, and if >= TYPE_HEAP_BASE, calls gc_mark_object
        on the value field (which is a GC handle).
        """
        func = self.tv_mark

        entry = func.append_basic_block("entry")
        do_mark = func.append_basic_block("do_mark")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        tv_ptr = func.args[0]

        # Load type_id (field 0)
        type_id_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        type_id = builder.load(type_id_ptr)

        # Check if heap type
        is_heap = builder.icmp_unsigned('>=', type_id, ir.Constant(self.i64, self.TYPE_HEAP_BASE))
        builder.cbranch(is_heap, do_mark, done)

        # Mark the handle
        builder.position_at_end(do_mark)
        value_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        handle = builder.load(value_ptr)

        # Skip null handles
        is_null = builder.icmp_unsigned('==', handle, ir.Constant(self.i64, 0))
        with builder.if_then(builder.not_(is_null)):
            builder.call(self.gc_mark_object, [handle])
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_tv_mark_array(self):
        """Implement tv_mark_array(data, count) -> void.

        Iterates through an array of TaggedValues and marks any heap references.
        This is the core function for GC tracing of collection elements.
        """
        func = self.tv_mark_array

        entry = func.append_basic_block("entry")
        loop_cond = func.append_basic_block("loop_cond")
        loop_body = func.append_basic_block("loop_body")
        check_heap = func.append_basic_block("check_heap")
        do_mark = func.append_basic_block("do_mark")
        loop_inc = func.append_basic_block("loop_inc")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        data_ptr = func.args[0]
        count = func.args[1]

        # Loop index
        idx_ptr = builder.alloca(self.i64, name="idx")
        builder.store(ir.Constant(self.i64, 0), idx_ptr)
        builder.branch(loop_cond)

        # Loop condition: idx < count
        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        cond = builder.icmp_unsigned('<', idx, count)
        builder.cbranch(cond, loop_body, done)

        # Loop body: get element and check type
        builder.position_at_end(loop_body)
        idx = builder.load(idx_ptr)

        # Get pointer to TaggedValue at index
        tv_ptr = builder.gep(data_ptr, [idx], inbounds=True)

        # Load type_id (field 0)
        type_id_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        type_id = builder.load(type_id_ptr)
        builder.branch(check_heap)

        # Check if heap type
        builder.position_at_end(check_heap)
        is_heap = builder.icmp_unsigned('>=', type_id, ir.Constant(self.i64, self.TYPE_HEAP_BASE))
        builder.cbranch(is_heap, do_mark, loop_inc)

        # Mark the handle
        builder.position_at_end(do_mark)
        value_ptr = builder.gep(tv_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        handle = builder.load(value_ptr)

        # Skip null handles
        is_null = builder.icmp_unsigned('==', handle, ir.Constant(self.i64, 0))
        with builder.if_then(builder.not_(is_null)):
            builder.call(self.gc_mark_object, [handle])
        builder.branch(loop_inc)

        # Increment index
        builder.position_at_end(loop_inc)
        idx = builder.load(idx_ptr)
        next_idx = builder.add(idx, ir.Constant(self.i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_cond)

        # Done
        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_safepoint(self):
        """Implement safe-point check for automatic GC triggering.

        This function is safe to call at function entry because:
        1. All previous operations have completed
        2. Caller's heap variables are properly rooted
        3. No intermediate allocations exist yet

        Also handles watermark protocol acknowledgment:
        - If gc_phase != 0 (IDLE), checks if we need to acknowledge
        - Sets watermark_depth to current stack depth on first encounter

        Checks if allocation count >= threshold and triggers GC if so.
        """
        func = self.gc_safepoint

        entry = func.append_basic_block("entry")
        check_phase = func.append_basic_block("check_phase")
        check_ack = func.append_basic_block("check_ack")
        do_ack = func.append_basic_block("do_ack")
        after_ack = func.append_basic_block("after_ack")
        enabled_check = func.append_basic_block("enabled_check")
        do_gc = func.append_basic_block("do_gc")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # First, check gc_phase for watermark protocol
        phase = builder.load(self.gc_phase)
        is_idle = builder.icmp_unsigned('==', phase, ir.Constant(self.i64, 0))
        builder.cbranch(is_idle, enabled_check, check_phase)

        # Check if we need to acknowledge watermark (use pthread TLS)
        builder.position_at_end(check_phase)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        entry_int = builder.ptrtoint(thread_entry, self.i64)
        not_registered = builder.icmp_unsigned(
            '==', entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(not_registered, enabled_check, check_ack)

        # Check watermark_active
        builder.position_at_end(check_ack)
        wm_active_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        wm_active = builder.load(wm_active_ptr)
        already_acked = builder.icmp_unsigned(
            '!=', wm_active, ir.Constant(self.i64, 0))
        builder.cbranch(already_acked, enabled_check, do_ack)

        # Acknowledge watermark
        builder.position_at_end(do_ack)

        # watermark_depth = stack_depth
        depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)
        ], inbounds=True)
        stack_depth = builder.load(depth_ptr)

        wm_depth_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(stack_depth, wm_depth_ptr)

        # last_gc_cycle = gc_cycle_id
        cycle_id = builder.load(self.gc_cycle_id)
        last_cycle_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
        ], inbounds=True)
        builder.store(cycle_id, last_cycle_ptr)

        # watermark_active = 1
        builder.store(ir.Constant(self.i64, 1), wm_active_ptr)

        # Wait for GC to complete (gc_phase returns to 0)
        # This prevents the thread from modifying its shadow stack while GC scans it.
        # The calling thread that triggered GC doesn't reach this code because it
        # checked gc_phase = 0 before triggering.
        wait_loop = func.append_basic_block("wait_gc_complete")
        wait_yield = func.append_basic_block("wait_yield")
        gc_done = func.append_basic_block("gc_done")
        builder.branch(wait_loop)

        builder.position_at_end(wait_loop)
        phase_val = builder.load(self.gc_phase)
        gc_still_active = builder.icmp_unsigned('!=', phase_val, ir.Constant(self.i64, 0))
        builder.cbranch(gc_still_active, wait_yield, gc_done)

        # Yield and retry
        builder.position_at_end(wait_yield)
        builder.call(self.sched_yield, [])
        builder.branch(wait_loop)

        builder.position_at_end(gc_done)
        builder.branch(after_ack)

        builder.position_at_end(after_ack)
        builder.branch(enabled_check)

        # Now check if GC should be triggered (original behavior)
        builder.position_at_end(enabled_check)

        # Check if GC is enabled
        gc_enabled = builder.load(self.gc_enabled)
        threshold_check = func.append_basic_block("threshold_check")
        builder.cbranch(gc_enabled, threshold_check, done)

        builder.position_at_end(threshold_check)

        # First, check if count is high enough (non-atomic read is fine for check)
        # Only if high, do we attempt the atomic exchange to claim the trigger
        threshold = ir.Constant(self.i64, self.GC_THRESHOLD)
        current_count = builder.load(self.gc_alloc_count)
        maybe_gc = builder.icmp_unsigned(">=", current_count, threshold)

        try_claim = func.append_basic_block("try_claim")
        builder.cbranch(maybe_gc, try_claim, done)

        # Try to claim the trigger by atomically exchanging to 0
        # Only one thread will see the high value and trigger GC
        builder.position_at_end(try_claim)
        claimed_count = builder.atomic_rmw('xchg', self.gc_alloc_count, ir.Constant(self.i64, 0), 'acquire')
        should_gc = builder.icmp_unsigned(">=", claimed_count, threshold)
        builder.cbranch(should_gc, do_gc, done)

        # Delegate GC to the dedicated GC thread (BUG-088 fix)
        # Instead of calling gc_collect() directly on the mutator thread,
        # signal the GC thread and wait for it to complete.
        builder.position_at_end(do_gc)

        # Lock mutex to atomically set gc_complete=0 and signal
        gc_mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [gc_mutex_ptr])

        # Set gc_complete = 0 so gc_wait_for_completion will actually wait
        # (prevents race where GC thread hasn't started yet and gc_complete
        # is still 1 from a previous cycle)
        gc_complete_ptr = builder.gep(self.gc_state, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), gc_complete_ptr)

        # Set trigger flag to request collection
        builder.store(ir.Constant(self.i64, 1), self.gc_trigger_requested)

        # Signal the GC thread's condition variable to wake it up
        gc_cond_start = builder.load(self.gc_cond_start)
        builder.call(self.pthread_cond_signal, [gc_cond_start])

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [gc_mutex_ptr])

        # Wait for GC thread to complete collection before resuming
        builder.call(self.gc_wait_for_completion, [])

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
        If allocation threshold is exceeded, triggers the GC thread asynchronously.
        The mutator continues execution without waiting for collection to complete.
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

    def push_frame_inline(self, builder: ir.IRBuilder, num_roots: int) -> ir.Value:
        """Push a GC frame using segmented shadow stack.

        Phase 5: Uses segment-based shadow stack instead of frame-linked-list.
        Reserves num_roots slots in the segment chain.
        Returns the starting slot index (i64) for use in set_root and pop_frame.

        NOTE: gc_segment_push already updates ThreadEntry.slot_index and
        ThreadEntry.segment_current via pthread_getspecific, so we don't
        need to sync them again here. Due to BUG-023, we must NOT read from
        tls_slot_index or tls_segment_current directly.
        """
        # Call gc_segment_push to reserve slots in the segment chain
        # Returns the starting slot index (i64)
        # gc_segment_push handles updating ThreadEntry fields via pthread TLS
        num_roots_val = ir.Constant(self.i64, num_roots)
        start_slot = builder.call(self.gc_segment_push, [num_roots_val])
        return start_slot

    def pop_frame_inline(self, builder: ir.IRBuilder, start_slot: ir.Value):
        """Pop a GC frame using segmented shadow stack.

        Phase 5: Uses segment-based shadow stack.
        Restores the slot index to start_slot value.
        Segment chain stays intact (Segment Stability Invariant).

        NOTE: gc_segment_pop already updates ThreadEntry.slot_index via
        pthread_getspecific, so we don't need to sync it again here.
        """
        # Call gc_segment_pop to restore slot index
        # gc_segment_pop handles updating ThreadEntry.slot_index via pthread TLS
        builder.call(self.gc_segment_pop, [start_slot])

    def push_frame(self, builder: ir.IRBuilder, num_roots: int) -> ir.Value:
        """Push a GC frame. Returns start_slot index for later pop.

        Phase 5: Uses segmented shadow stack.
        Reserves num_roots slots and returns the starting slot index.
        """
        return self.push_frame_inline(builder, num_roots)

    def pop_frame(self, builder: ir.IRBuilder, start_slot: ir.Value):
        """Pop a GC frame.

        Phase 5: Uses segmented shadow stack.
        Restores slot index to start_slot value.
        """
        self.pop_frame_inline(builder, start_slot)

    def set_root(self, builder: ir.IRBuilder, start_slot: ir.Value, index: int, value: ir.Value):
        """Set a root slot to a handle value.

        Phase 5: Uses segmented shadow stack.
        Computes absolute slot = start_slot + index, then stores handle.
        When given a pointer, we call gc_ptr_to_handle to recover the actual
        handle index from the object's header.
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

        # Compute absolute slot index and store handle via gc_segment_set_root
        absolute_slot = builder.add(start_slot, index_val)
        builder.call(self.gc_segment_set_root, [absolute_slot, handle])

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

    def alloc_arena_or_gc(self, builder: ir.IRBuilder, size: ir.Value,
                          type_id: ir.Value) -> ir.Value:
        """Allocate from arena if active, otherwise fall back to GC allocation.

        Phase 6: Arena allocation for formula functions. This calls a runtime
        function that checks if an arena is active and uses arena allocation
        if so. Otherwise falls back to GC allocation.

        Arena-allocated objects:
        - Have the same header layout as GC objects (32 bytes)
        - Have FLAG_ARENA set in flags (no handle, bulk-freed)
        - Are NOT added to the allocation list
        - Are NOT tracked by GC
        - Are bulk-freed when arena scope ends

        Args:
            builder: LLVM IR builder
            size: Size of user data in bytes (i64)
            type_id: Type ID for GC tracing (i32)

        Returns:
            i8* pointer to the allocated memory (user area after header)
        """
        # Call the runtime function that handles arena vs GC allocation
        ptr = builder.call(self.gc_alloc_arena_or_gc, [size, type_id])
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
        """GC thread main loop - waits for trigger, collects, signals completion.

        The GC thread runs continuously in the background:
        1. Wait for gc_trigger_requested to be set (via condition variable)
        2. Run gc_collect() which handles all marking and sweeping
        3. Clear trigger flag and signal completion
        4. Loop back to wait

        This design supports future scaling to multiple GC threads by:
        - Using condition variables for coordination
        - Keeping collection logic in gc_collect() which can be parallelized
        - Signaling completion for waiting mutators
        """
        func = self.gc_thread_main
        func.args[0].name = "arg"

        entry = func.append_basic_block("entry")
        main_loop = func.append_basic_block("main_loop")
        check_running = func.append_basic_block("check_running")
        check_trigger = func.append_basic_block("check_trigger")
        wait_for_trigger = func.append_basic_block("wait_for_trigger")
        do_collection = func.append_basic_block("do_collection")
        signal_done = func.append_basic_block("signal_done")
        exit_thread = func.append_basic_block("exit_thread")

        builder = ir.IRBuilder(entry)
        builder.branch(main_loop)

        # Main loop - runs until gc_thread_running is set to 0
        builder.position_at_end(main_loop)

        # Lock mutex for checking trigger
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])
        builder.branch(check_running)

        # Check if thread should exit
        builder.position_at_end(check_running)
        running = builder.load(self.gc_thread_running)
        is_running = builder.icmp_unsigned("!=", running, ir.Constant(self.i64, 0))
        builder.cbranch(is_running, check_trigger, exit_thread)

        # Check if collection is requested
        builder.position_at_end(check_trigger)
        trigger = builder.load(self.gc_trigger_requested)
        has_trigger = builder.icmp_unsigned("!=", trigger, ir.Constant(self.i64, 0))
        builder.cbranch(has_trigger, do_collection, wait_for_trigger)

        # Wait on condition variable for trigger
        builder.position_at_end(wait_for_trigger)
        cond_start = builder.load(self.gc_cond_start)
        mutex_ptr2 = builder.load(self.gc_mutex)
        builder.call(self.pthread_cond_wait, [cond_start, mutex_ptr2])
        # After wakeup, go back to check running and trigger
        builder.branch(check_running)

        # Do collection
        builder.position_at_end(do_collection)

        # Clear trigger flag before collection (prevents re-trigger during collection)
        builder.store(ir.Constant(self.i64, 0), self.gc_trigger_requested)

        # Unlock mutex during collection (gc_collect has its own synchronization)
        mutex_ptr3 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr3])

        # Run the collection - gc_collect handles all marking and sweeping
        # It also handles gc_phase transitions and watermark resets
        builder.call(self.gc_collect, [])

        builder.branch(signal_done)

        # Signal completion to any waiting threads
        builder.position_at_end(signal_done)

        # Lock mutex to signal completion
        mutex_ptr4 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr4])

        # Signal completion (gc_cond_done)
        cond_done = builder.load(self.gc_cond_done)
        builder.call(self.pthread_cond_signal, [cond_done])

        # Unlock and loop back
        mutex_ptr5 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr5])

        builder.branch(main_loop)

        # Exit thread - unlock mutex and return
        builder.position_at_end(exit_thread)
        mutex_ptr6 = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr6])
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_async(self):
        """Trigger async GC by signaling the background GC thread.

        This function triggers a garbage collection cycle by:
        1. Setting the gc_trigger_requested flag
        2. Signaling the GC thread's condition variable to wake it up

        The function returns immediately without waiting for collection to complete.
        Use gc_wait_for_completion() if you need to wait for the cycle to finish.
        """
        func = self.gc_async

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Set trigger flag to request collection
        builder.store(ir.Constant(self.i64, 1), self.gc_trigger_requested)

        # Signal the GC thread to wake up
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])
        cond_start = builder.load(self.gc_cond_start)
        builder.call(self.pthread_cond_signal, [cond_start])
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

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

    def _implement_gc_wait_for_watermarks(self):
        """Wait for all OTHER threads to acknowledge watermark (Phase 2).

        This function is called after setting gc_phase = WATERMARK.
        It spins until all registered threads (EXCEPT the calling thread) have
        watermark_active = 1, calling sched_yield() between iterations.

        The calling thread is skipped because:
        1. If called from GC thread (no ThreadEntry), all threads need to ack
        2. If called from mutator thread, that thread is blocked here and
           can't reach a safepoint to acknowledge, but its shadow stack is
           safe to scan because it's frozen at this call site.

        Timeout: After MAX_ITERATIONS, proceed anyway (accept potential unsafety
        for threads blocked in system calls).
        """
        func = self.gc_wait_for_watermarks

        entry = func.append_basic_block("entry")
        outer_loop = func.append_basic_block("outer_loop")
        thread_loop = func.append_basic_block("thread_loop")
        check_thread = func.append_basic_block("check_thread")
        next_thread = func.append_basic_block("next_thread")
        all_done = func.append_basic_block("all_done")
        yield_and_retry = func.append_basic_block("yield_and_retry")
        timeout = func.append_basic_block("timeout")

        builder = ir.IRBuilder(entry)

        # Get calling thread's ThreadEntry (to skip it in the loop)
        tls_key = builder.load(self.tls_thread_entry_key)
        my_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        my_entry = builder.bitcast(my_entry_i8, self.thread_entry_type.as_pointer())
        my_entry_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="my_entry")
        builder.store(my_entry, my_entry_alloca)

        # Iteration counter (max 10000 iterations ~ 10ms at 1us per yield)
        max_iterations = ir.Constant(self.i64, 10000)
        iter_alloca = builder.alloca(self.i64, name="iter")
        builder.store(ir.Constant(self.i64, 0), iter_alloca)

        # Current thread pointer
        curr_thread_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="curr")

        builder.branch(outer_loop)

        # Outer loop: check all threads, yield if any not ready
        builder.position_at_end(outer_loop)

        # Check iteration limit
        curr_iter = builder.load(iter_alloca)
        hit_limit = builder.icmp_unsigned(">=", curr_iter, max_iterations)
        builder.cbranch(hit_limit, timeout, thread_loop)

        # Thread loop start
        builder.position_at_end(thread_loop)
        # Lock registry mutex for safe iteration
        wm_mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [wm_mutex])
        first_thread = builder.load(self.gc_thread_registry)
        builder.store(first_thread, curr_thread_alloca)
        builder.branch(check_thread)

        # Check each thread
        builder.position_at_end(check_thread)
        curr_thread = builder.load(curr_thread_alloca)
        thread_int = builder.ptrtoint(curr_thread, self.i64)
        is_null = builder.icmp_unsigned("==", thread_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null, all_done, next_thread)

        # Check if this is the calling thread (skip if so)
        builder.position_at_end(next_thread)
        my_entry_val = builder.load(my_entry_alloca)
        my_entry_int = builder.ptrtoint(my_entry_val, self.i64)
        curr_int = builder.ptrtoint(curr_thread, self.i64)
        is_self = builder.icmp_unsigned("==", curr_int, my_entry_int)

        check_watermark = func.append_basic_block("check_watermark")
        advance = func.append_basic_block("advance")
        builder.cbranch(is_self, advance, check_watermark)

        # Check watermark_active for this thread
        builder.position_at_end(check_watermark)
        wm_active_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        wm_active = builder.load(wm_active_ptr)
        not_acked = builder.icmp_unsigned("==", wm_active, ir.Constant(self.i64, 0))

        # If not acknowledged, yield and retry
        builder.cbranch(not_acked, yield_and_retry, advance)

        # Advance to next thread (field 9 is the 'next' pointer, stored as i8*)
        builder.position_at_end(advance)
        next_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 11)
        ], inbounds=True)
        next_i8ptr = builder.load(next_ptr)
        # Cast i8* to ThreadEntry*
        next_node = builder.bitcast(next_i8ptr, self.thread_entry_type.as_pointer())
        builder.store(next_node, curr_thread_alloca)
        builder.branch(check_thread)

        # All threads acknowledged
        builder.position_at_end(all_done)
        # Unlock registry mutex before returning
        builder.call(self.pthread_mutex_unlock, [wm_mutex])
        builder.ret_void()

        # Yield and retry
        builder.position_at_end(yield_and_retry)
        # Unlock registry mutex before yielding
        builder.call(self.pthread_mutex_unlock, [wm_mutex])
        builder.call(self.sched_yield, [])
        new_iter = builder.add(curr_iter, ir.Constant(self.i64, 1))
        builder.store(new_iter, iter_alloca)
        builder.branch(outer_loop)

        # Timeout - proceed anyway with warning
        builder.position_at_end(timeout)
        # In production, we'd log a warning here
        # For now, just proceed (threads will be scanned with watermark=0 meaning scan all)
        # Note: We didn't lock the mutex yet (hit_limit branch is before thread_loop)
        builder.ret_void()

    # ========================================================================
    # Phase 3: Segmented Shadow Stack Implementation
    # ========================================================================

    def _implement_gc_segment_alloc(self):
        """Allocate a new 4KB segment via mmap.

        Returns pointer to StackSegment structure.
        Uses mmap for page-aligned allocation.
        """
        func = self.gc_segment_alloc

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON, -1, 0)
        # Platform-specific mmap flags:
        #   macOS: MAP_ANON = 0x1000, MAP_PRIVATE = 0x0002 → 0x1002
        #   Linux: MAP_ANON = 0x0020, MAP_PRIVATE = 0x0002 → 0x0022
        import sys
        if sys.platform == 'darwin':
            mmap_flags = 0x1002  # MAP_PRIVATE | MAP_ANON (macOS)
        else:
            mmap_flags = 0x0022  # MAP_PRIVATE | MAP_ANONYMOUS (Linux)

        null_ptr = ir.Constant(self.i8_ptr, None)
        size = ir.Constant(self.i64, self.SEGMENT_SIZE)
        prot = ir.Constant(self.i32, 3)  # PROT_READ | PROT_WRITE
        flags = ir.Constant(self.i32, mmap_flags)
        fd = ir.Constant(self.i32, -1)
        offset = ir.Constant(self.i64, 0)

        raw_ptr = builder.call(self.mmap, [null_ptr, size, prot, flags, fd, offset])

        # Cast to StackSegment*
        segment = builder.bitcast(raw_ptr, self.stack_segment_type.as_pointer())

        # Initialize segment header
        # prev = NULL
        prev_ptr = builder.gep(segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), prev_ptr)

        # next = NULL
        next_ptr = builder.gep(segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_ptr)

        # slot_count = 0
        count_ptr = builder.gep(segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), count_ptr)

        builder.ret(segment)

    def _implement_gc_segment_init(self):
        """Initialize thread's first segment.

        Called from gc_register_thread to set up the initial segment.
        """
        func = self.gc_segment_init

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Allocate first segment
        segment = builder.call(self.gc_segment_alloc, [])

        # Store in TLS
        builder.store(segment, self.tls_segment_base)
        builder.store(segment, self.tls_segment_current)
        builder.store(ir.Constant(self.i64, 0), self.tls_slot_index)

        builder.ret_void()

    def _implement_gc_segment_push(self):
        """Reserve num_roots slots in segment, returns starting slot index.

        If current segment is full, allocates a new one.
        Returns the absolute slot index where roots should be stored.

        IMPORTANT: Uses ThreadEntry fields (via pthread TLS) instead of LLVM
        thread_local globals, which don't work in llvmlite.
        """
        func = self.gc_segment_push
        func.args[0].name = "num_roots"

        entry = func.append_basic_block("entry")
        check_space = func.append_basic_block("check_space")
        allocate_new = func.append_basic_block("allocate_new")
        have_space = func.append_basic_block("have_space")

        builder = ir.IRBuilder(entry)
        num_roots = func.args[0]

        # Get ThreadEntry via pthread TLS (this actually works, unlike LLVM thread_local)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())

        # Read slot_index from ThreadEntry field 14
        slot_idx_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 14)
        ], inbounds=True)
        start_slot = builder.load(slot_idx_ptr)

        # Read segment_current from ThreadEntry field 13
        seg_curr_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 13)
        ], inbounds=True)
        segment_i8 = builder.load(seg_curr_ptr)
        segment = builder.bitcast(segment_i8, self.stack_segment_type.as_pointer())

        # Store segment in alloca for phi-like access across blocks
        segment_alloca = builder.alloca(self.stack_segment_type.as_pointer(), name="seg_alloca")
        builder.store(segment, segment_alloca)

        builder.branch(check_space)

        # Check if we have space in current segment
        builder.position_at_end(check_space)
        seg_for_check = builder.load(segment_alloca)
        count_ptr = builder.gep(seg_for_check, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_count = builder.load(count_ptr)

        # Calculate remaining space
        max_slots = ir.Constant(self.i64, self.SEGMENT_SLOTS)
        new_count = builder.add(current_count, num_roots)
        exceeds = builder.icmp_unsigned(">", new_count, max_slots)
        builder.cbranch(exceeds, allocate_new, have_space)

        # Allocate new segment
        builder.position_at_end(allocate_new)
        old_segment = builder.load(segment_alloca)
        new_segment = builder.call(self.gc_segment_alloc, [])

        # Link new segment to current
        # new_segment.prev = current_segment
        new_prev_ptr = builder.gep(new_segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        old_as_i8ptr = builder.bitcast(old_segment, self.i8_ptr)
        builder.store(old_as_i8ptr, new_prev_ptr)

        # current_segment.next = new_segment
        curr_next_ptr = builder.gep(old_segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        new_as_i8ptr = builder.bitcast(new_segment, self.i8_ptr)
        builder.store(new_as_i8ptr, curr_next_ptr)

        # Update ThreadEntry.segment_current (field 13)
        builder.store(new_as_i8ptr, seg_curr_ptr)

        # Update local alloca for have_space block
        builder.store(new_segment, segment_alloca)
        builder.branch(have_space)

        # Have space - update slot count and return start index
        builder.position_at_end(have_space)
        # Reload segment from alloca (may have changed)
        segment2 = builder.load(segment_alloca)
        count_ptr2 = builder.gep(segment2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_count2 = builder.load(count_ptr2)

        # CRITICAL: Zero the slots BEFORE updating watermark to prevent race condition
        # If GC scans before set_root is called, it must find zeros (null handles)
        # Get pointer to slots array in current segment
        slots_base = builder.gep(segment2, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 3),  # slots array
            ir.Constant(self.i32, 0)   # first element
        ], inbounds=True)

        # Zero each slot we're reserving (starting from current_count2)
        # This is a simple loop - for small num_roots this is fine
        zero_loop = func.append_basic_block("zero_loop")
        zero_body = func.append_basic_block("zero_body")
        zero_done = func.append_basic_block("zero_done")

        zero_idx = builder.alloca(self.i64, name="zero_idx")
        builder.store(ir.Constant(self.i64, 0), zero_idx)
        builder.branch(zero_loop)

        builder.position_at_end(zero_loop)
        zi = builder.load(zero_idx)
        done_zeroing = builder.icmp_unsigned(">=", zi, num_roots)
        builder.cbranch(done_zeroing, zero_done, zero_body)

        builder.position_at_end(zero_body)
        # Calculate absolute slot index: current_count2 + zi
        abs_slot = builder.add(current_count2, zi)
        slot_ptr = builder.gep(slots_base, [abs_slot], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), slot_ptr)  # Zero the slot
        next_zi = builder.add(zi, ir.Constant(self.i64, 1))
        builder.store(next_zi, zero_idx)
        builder.branch(zero_loop)

        builder.position_at_end(zero_done)

        # Update segment slot count
        new_count2 = builder.add(current_count2, num_roots)
        builder.store(new_count2, count_ptr2)

        # Update ThreadEntry.slot_index (field 14)
        new_slot_idx = builder.add(start_slot, num_roots)
        builder.store(new_slot_idx, slot_idx_ptr)

        # Return starting slot index
        builder.ret(start_slot)

    def _implement_gc_segment_pop(self):
        """Restore slot index to start_slot value.

        May go back to previous segment if needed.

        IMPORTANT: Uses ThreadEntry fields (via pthread TLS) instead of LLVM
        thread_local globals, which don't work in llvmlite.
        """
        func = self.gc_segment_pop
        func.args[0].name = "start_slot"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)
        start_slot = func.args[0]

        # Get ThreadEntry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())

        # Update ThreadEntry.slot_index (field 14) directly
        # The segment chain remains intact for potential reuse
        slot_idx_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 14)  # slot_index field
        ], inbounds=True)
        builder.store(start_slot, slot_idx_ptr)

        builder.ret_void()

    def _implement_gc_segment_set_root(self):
        """Store handle at absolute slot index.

        Finds the correct segment and slot within it.
        Uses absolute slot indexing across the segment chain.

        IMPORTANT: Uses ThreadEntry fields (via pthread TLS) instead of LLVM
        thread_local globals, which don't work in llvmlite.
        """
        func = self.gc_segment_set_root
        func.args[0].name = "slot"
        func.args[1].name = "handle"

        entry = func.append_basic_block("entry")
        loop_check = func.append_basic_block("loop_check")
        loop_body = func.append_basic_block("loop_body")
        found = func.append_basic_block("found")

        builder = ir.IRBuilder(entry)
        slot = func.args[0]
        handle = func.args[1]

        # Get ThreadEntry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())

        # Get segment_base from ThreadEntry field 12
        seg_base_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 12)  # segment_base field
        ], inbounds=True)
        segment_base_i8 = builder.load(seg_base_ptr)
        base_segment = builder.bitcast(segment_base_i8, self.stack_segment_type.as_pointer())

        # Calculate which segment and which slot within it
        # slot_in_segment = slot % SEGMENT_SLOTS
        # segment_index = slot / SEGMENT_SLOTS
        slots_per_segment = ir.Constant(self.i64, self.SEGMENT_SLOTS)
        slot_in_segment = builder.urem(slot, slots_per_segment)
        segment_index = builder.udiv(slot, slots_per_segment)

        # Walk to the correct segment
        curr_segment_alloca = builder.alloca(self.stack_segment_type.as_pointer(), name="curr")
        remaining_alloca = builder.alloca(self.i64, name="remaining")

        builder.store(base_segment, curr_segment_alloca)
        builder.store(segment_index, remaining_alloca)
        builder.branch(loop_check)

        # Loop check: if remaining == 0, we found the right segment
        builder.position_at_end(loop_check)
        remaining = builder.load(remaining_alloca)
        is_zero = builder.icmp_unsigned("==", remaining, ir.Constant(self.i64, 0))
        builder.cbranch(is_zero, found, loop_body)

        # Loop body: advance to next segment and decrement remaining
        builder.position_at_end(loop_body)
        curr_segment_in_loop = builder.load(curr_segment_alloca)

        # Get next segment pointer: curr_segment->next (field 1)
        next_ptr = builder.gep(curr_segment_in_loop, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)  # next field
        ], inbounds=True)
        next_seg_i8ptr = builder.load(next_ptr)
        next_segment = builder.bitcast(next_seg_i8ptr, self.stack_segment_type.as_pointer())

        # Update curr_segment to next
        builder.store(next_segment, curr_segment_alloca)

        # Decrement remaining
        remaining_in_loop = builder.load(remaining_alloca)
        new_remaining = builder.sub(remaining_in_loop, ir.Constant(self.i64, 1))
        builder.store(new_remaining, remaining_alloca)

        builder.branch(loop_check)

        # Found the correct segment - store the handle
        builder.position_at_end(found)
        curr_segment = builder.load(curr_segment_alloca)

        # Get slots array: curr_segment->slots[0] (field 3)
        slots_ptr = builder.gep(curr_segment, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 3),  # slots array
            ir.Constant(self.i32, 0)   # first element
        ], inbounds=True)

        # Store handle at slot_in_segment
        slot_ptr = builder.gep(slots_ptr, [slot_in_segment], inbounds=True)
        builder.store(handle, slot_ptr)

        builder.ret_void()

    def _implement_gc_segment_scan_roots(self):
        """Scan all segments for roots.

        Called by gc_scan_roots to mark reachable objects.
        Walks from base segment to current, scanning all slots.

        BUG-078 FIX: Use ThreadEntry via pthread TLS instead of tls_segment_base.
        The llvmlite thread_local attribute is silently ignored (BUG-023), so we
        must use pthread TLS for all per-thread state.
        """
        func = self.gc_segment_scan_roots

        entry = func.append_basic_block("entry")
        segment_loop = func.append_basic_block("segment_loop")
        scan_segment = func.append_basic_block("scan_segment")
        slot_loop = func.append_basic_block("slot_loop")
        mark_slot = func.append_basic_block("mark_slot")
        next_slot = func.append_basic_block("next_slot")
        next_segment = func.append_basic_block("next_segment")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Allocate loop variables
        curr_segment_alloca = builder.alloca(self.stack_segment_type.as_pointer(), name="curr_seg")
        slot_idx_alloca = builder.alloca(self.i64, name="slot_idx")

        # BUG-078 FIX: Get ThreadEntry via pthread TLS (this actually works, unlike LLVM thread_local)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())

        # Get segment_base from ThreadEntry field 12
        seg_base_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 12)  # segment_base field
        ], inbounds=True)
        segment_base_i8 = builder.load(seg_base_ptr)
        base = builder.bitcast(segment_base_i8, self.stack_segment_type.as_pointer())

        base_int = builder.ptrtoint(base, self.i64)
        has_segments = builder.icmp_unsigned("!=", base_int, ir.Constant(self.i64, 0))

        # If no segments, we're done
        done_early = func.append_basic_block("done_early")
        builder.cbranch(has_segments, segment_loop, done_early)

        builder.position_at_end(done_early)
        builder.ret_void()

        # Segment loop
        builder.position_at_end(segment_loop)
        builder.store(base, curr_segment_alloca)
        builder.branch(scan_segment)

        # Scan current segment
        builder.position_at_end(scan_segment)
        curr_segment = builder.load(curr_segment_alloca)
        seg_int = builder.ptrtoint(curr_segment, self.i64)
        is_null_seg = builder.icmp_unsigned("==", seg_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_seg, done, slot_loop)

        # Get slot count for this segment
        builder.position_at_end(slot_loop)
        count_ptr = builder.gep(curr_segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        slot_count = builder.load(count_ptr)

        builder.store(ir.Constant(self.i64, 0), slot_idx_alloca)
        builder.branch(mark_slot)

        # Mark each slot
        builder.position_at_end(mark_slot)
        idx = builder.load(slot_idx_alloca)
        done_slots = builder.icmp_unsigned(">=", idx, slot_count)
        builder.cbranch(done_slots, next_segment, next_slot)

        # Process slot
        builder.position_at_end(next_slot)
        # Get slots array
        slots_ptr = builder.gep(curr_segment, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 3),  # slots array
            ir.Constant(self.i32, 0)   # first element
        ], inbounds=True)

        curr_idx = builder.load(slot_idx_alloca)
        slot_ptr = builder.gep(slots_ptr, [curr_idx], inbounds=True)
        handle = builder.load(slot_ptr)

        # Skip null handles
        is_null_handle = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        skip_mark = func.append_basic_block("skip_mark")
        do_mark = func.append_basic_block("do_mark")
        builder.cbranch(is_null_handle, skip_mark, do_mark)

        builder.position_at_end(do_mark)
        builder.call(self.gc_mark_object, [handle])
        builder.branch(skip_mark)

        builder.position_at_end(skip_mark)
        # Increment slot index
        new_idx = builder.add(curr_idx, ir.Constant(self.i64, 1))
        builder.store(new_idx, slot_idx_alloca)
        builder.branch(mark_slot)

        # Move to next segment
        builder.position_at_end(next_segment)
        next_ptr = builder.gep(curr_segment, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        next_seg_i8ptr = builder.load(next_ptr)
        next_seg = builder.bitcast(next_seg_i8ptr, self.stack_segment_type.as_pointer())
        builder.store(next_seg, curr_segment_alloca)
        builder.branch(scan_segment)

        builder.position_at_end(done)
        builder.ret_void()

    # ========================================================================
    # Phase 4: TLAB (Thread-Local Allocation Buffer) Implementations
    # ========================================================================

    def _implement_gc_tlab_init(self):
        """Initialize TLAB for current thread.

        Allocates a 256KB buffer via mmap and initializes the ThreadEntry
        TLAB fields (tlab_base, tlab_cursor, tlab_limit).

        Called from gc_register_thread when a new thread joins.
        """
        func = self.gc_tlab_init

        entry = func.append_basic_block("entry")
        alloc_ok = func.append_basic_block("alloc_ok")
        alloc_fail = func.append_basic_block("alloc_fail")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Allocate TLAB buffer via mmap
        # mmap(NULL, TLAB_SIZE, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANON, -1, 0)
        tlab_size = ir.Constant(self.i64, self.TLAB_SIZE)
        prot = ir.Constant(self.i32, 3)  # PROT_READ | PROT_WRITE
        flags = ir.Constant(self.i32, 0x1002)  # MAP_PRIVATE | MAP_ANON (macOS)
        fd = ir.Constant(self.i32, -1)
        offset = ir.Constant(self.i64, 0)

        buffer = builder.call(self.mmap, [
            ir.Constant(self.i8_ptr, None),  # addr = NULL
            tlab_size,
            prot,
            flags,
            fd,
            offset
        ])

        # Check for mmap failure (returns MAP_FAILED = -1)
        buffer_int = builder.ptrtoint(buffer, self.i64)
        map_failed = ir.Constant(self.i64, 0xFFFFFFFFFFFFFFFF)  # -1
        is_failed = builder.icmp_unsigned("==", buffer_int, map_failed)
        builder.cbranch(is_failed, alloc_fail, alloc_ok)

        # Allocation successful - initialize ThreadEntry TLAB fields
        builder.position_at_end(alloc_ok)

        # Get thread entry from parameter (not TLS - may not be initialized yet for new threads)
        thread_entry = func.args[0]
        thread_entry_typed = builder.bitcast(thread_entry, self.thread_entry_type.as_pointer())

        # Initialize TLAB header at the start of the buffer
        tlab_header = builder.bitcast(buffer, self.tlab_header_type.as_pointer())

        # header->live_count = 0
        live_count_ptr = builder.gep(tlab_header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), live_count_ptr)

        # header->next_tlab = NULL (first TLAB has no previous)
        next_tlab_ptr = builder.gep(tlab_header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), next_tlab_ptr)

        # Set tlab_base (field 6) - points to start of buffer (where header is)
        tlab_base_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 6)
        ], inbounds=True)
        builder.store(buffer, tlab_base_ptr)

        # Set tlab_cursor (field 7) - starts AFTER the header
        cursor_start = builder.gep(buffer, [ir.Constant(self.i64, self.TLAB_HEADER_SIZE)])
        tlab_cursor_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(cursor_start, tlab_cursor_ptr)

        # Set tlab_limit (field 8) - base + TLAB_SIZE
        limit = builder.gep(buffer, [tlab_size])
        tlab_limit_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 8)
        ], inbounds=True)
        builder.store(limit, tlab_limit_ptr)

        # Set tlab_epoch (field 10) to current GC cycle
        gc_cycle = builder.load(self.gc_cycle_id)
        tlab_epoch_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 10)
        ], inbounds=True)
        builder.store(gc_cycle, tlab_epoch_ptr)

        # Initialize alloc_list to NULL (field 9)
        alloc_list_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 9)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), alloc_list_ptr)

        builder.branch(done)

        # Allocation failed - TLAB fields remain NULL (no TLAB allocation)
        builder.position_at_end(alloc_fail)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_tlab_alloc(self):
        """Fast-path TLAB bump-pointer allocation (lock-free, thread-safe).

        Attempts to allocate `size` bytes from the current thread's TLAB.
        Returns pointer to allocated memory, or NULL if TLAB is full.

        Uses atomic compare-and-swap (CAS) to safely update the cursor when
        multiple threads may be allocating concurrently. This fixes BUG-004:
        GC race condition with parallel Set allocations.

        CAS loop pattern:
        1. Load current cursor
        2. Calculate new cursor = cursor + size
        3. Atomically: if cursor unchanged, update to new cursor
        4. If CAS fails (another thread modified cursor), retry
        """
        func = self.gc_tlab_alloc
        func.args[0].name = "size"

        entry = func.append_basic_block("entry")
        have_tlab = func.append_basic_block("have_tlab")
        cas_loop = func.append_basic_block("cas_loop")
        check_cursor = func.append_basic_block("check_cursor")
        check_space = func.append_basic_block("check_space")
        do_cas = func.append_basic_block("do_cas")
        cas_success = func.append_basic_block("cas_success")
        no_space = func.append_basic_block("no_space")

        builder = ir.IRBuilder(entry)

        size = func.args[0]

        # Align size to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.add(size, seven)
        aligned_size = builder.and_(aligned_size, builder.not_(seven))

        # Allocate stack space to pass aligned_size to CAS loop
        aligned_size_alloca = builder.alloca(self.i64, name="aligned_size_slot")
        builder.store(aligned_size, aligned_size_alloca)

        # Get current thread entry (use pthread TLS)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, no_space, have_tlab)

        # --- have_tlab: Get TLAB pointers and limit ---
        builder.position_at_end(have_tlab)

        # Get pointer to tlab_cursor (field 7) - this is where CAS operates
        tlab_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 7)
        ], inbounds=True)

        # Load tlab_limit (field 8) - limit doesn't change during allocation
        tlab_limit_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 8)
        ], inbounds=True)
        limit = builder.load(tlab_limit_ptr)
        limit_int = builder.ptrtoint(limit, self.i64)

        # Store limit and cursor_ptr for use in CAS loop
        limit_alloca = builder.alloca(self.i64, name="limit_slot")
        builder.store(limit_int, limit_alloca)
        cursor_ptr_alloca = builder.alloca(self.i8_ptr.as_pointer(), name="cursor_ptr_slot")
        builder.store(tlab_cursor_ptr, cursor_ptr_alloca)

        builder.branch(cas_loop)

        # --- CAS loop: atomically allocate from TLAB ---
        builder.position_at_end(cas_loop)

        # Load current cursor value
        cursor_ptr = builder.load(cursor_ptr_alloca)
        cursor = builder.load(cursor_ptr)
        builder.branch(check_cursor)

        # --- check_cursor: Verify cursor is valid ---
        builder.position_at_end(check_cursor)
        cursor_int = builder.ptrtoint(cursor, self.i64)
        is_null_cursor = builder.icmp_unsigned("==", cursor_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_cursor, no_space, check_space)

        # --- check_space: Verify we have space for allocation ---
        builder.position_at_end(check_space)

        # Calculate new cursor position
        alloc_size = builder.load(aligned_size_alloca)
        new_cursor = builder.gep(cursor, [alloc_size])

        # Check if new_cursor <= limit
        new_cursor_int = builder.ptrtoint(new_cursor, self.i64)
        limit_val = builder.load(limit_alloca)
        has_space = builder.icmp_unsigned("<=", new_cursor_int, limit_val)
        builder.cbranch(has_space, do_cas, no_space)

        # --- do_cas: Atomically try to update cursor ---
        builder.position_at_end(do_cas)

        # Atomic compare-and-swap: if *cursor_ptr == cursor, set *cursor_ptr = new_cursor
        # Returns {old_value, success_flag}
        cmpxchg_result = builder.cmpxchg(cursor_ptr, cursor, new_cursor, 'acq_rel', 'acquire')
        success = builder.extract_value(cmpxchg_result, 1)

        # If CAS succeeded, we got the allocation; otherwise retry
        builder.cbranch(success, cas_success, cas_loop)

        # --- cas_success: Return the allocated memory (old cursor value) ---
        builder.position_at_end(cas_success)
        builder.ret(cursor)

        # --- no_space: TLAB full or invalid, return NULL ---
        builder.position_at_end(no_space)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_tlab_refill(self):
        """Slow-path TLAB refill.

        Called when gc_tlab_alloc returns NULL. Allocates a new 256KB
        buffer and updates the ThreadEntry TLAB fields.

        The old TLAB buffer is NOT freed - it contains live allocations.
        It will be reclaimed when all objects in it become unreachable.
        """
        func = self.gc_tlab_refill

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        alloc_ok = func.append_basic_block("alloc_ok")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Get current thread entry (use pthread TLS)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, done, have_entry)

        builder.position_at_end(have_entry)
        thread_entry_typed = thread_entry  # Already correctly typed

        # Allocate new TLAB buffer via mmap
        tlab_size = ir.Constant(self.i64, self.TLAB_SIZE)
        prot = ir.Constant(self.i32, 3)  # PROT_READ | PROT_WRITE
        flags = ir.Constant(self.i32, 0x1002)  # MAP_PRIVATE | MAP_ANON (macOS)
        fd = ir.Constant(self.i32, -1)
        offset = ir.Constant(self.i64, 0)

        buffer = builder.call(self.mmap, [
            ir.Constant(self.i8_ptr, None),
            tlab_size,
            prot,
            flags,
            fd,
            offset
        ])

        # Check for mmap failure
        buffer_int = builder.ptrtoint(buffer, self.i64)
        map_failed = ir.Constant(self.i64, 0xFFFFFFFFFFFFFFFF)
        is_failed = builder.icmp_unsigned("==", buffer_int, map_failed)
        builder.cbranch(is_failed, done, alloc_ok)

        builder.position_at_end(alloc_ok)

        # Initialize TLAB header at the start of the buffer
        tlab_header = builder.bitcast(buffer, self.tlab_header_type.as_pointer())

        # header->live_count = 0
        live_count_ptr = builder.gep(tlab_header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), live_count_ptr)

        # header->next_tlab = old tlab_base (link to previous TLAB)
        tlab_base_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 6)
        ], inbounds=True)
        old_tlab_base = builder.load(tlab_base_ptr)
        next_tlab_ptr = builder.gep(tlab_header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(old_tlab_base, next_tlab_ptr)

        # Update tlab_base (field 6) - points to start of buffer (where header is)
        builder.store(buffer, tlab_base_ptr)

        # Update tlab_cursor (field 7) - starts AFTER the header
        cursor_start = builder.gep(buffer, [ir.Constant(self.i64, self.TLAB_HEADER_SIZE)])
        tlab_cursor_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(cursor_start, tlab_cursor_ptr)

        # Update tlab_limit (field 8)
        limit = builder.gep(buffer, [tlab_size])
        tlab_limit_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 8)
        ], inbounds=True)
        builder.store(limit, tlab_limit_ptr)

        # Update tlab_epoch (field 10)
        gc_cycle = builder.load(self.gc_cycle_id)
        tlab_epoch_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 10)
        ], inbounds=True)
        builder.store(gc_cycle, tlab_epoch_ptr)

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    # ========================================================================
    # Phase 6: Scope Arena Functions - per-function bump allocation
    # ========================================================================

    def _implement_gc_arena_push(self):
        """Push a new arena scope onto the thread's arena stack.

        Saves the current TLAB cursor as the arena start, and stores the
        previous arena's start for nesting support. Returns the arena start
        pointer which must be passed to gc_arena_pop() on scope exit.

        ThreadEntry arena fields:
          15: arena_cursor - current arena allocation position
          16: arena_start - start of current arena
          17: arena_parent_start - parent arena's start (for nesting)
        """
        func = self.gc_arena_push

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        no_entry = func.append_basic_block("no_entry")

        builder = ir.IRBuilder(entry)

        # Get current thread entry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, no_entry, have_entry)

        builder.position_at_end(have_entry)

        # Load current tlab_cursor (field 7) - this becomes the arena start
        tlab_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        cursor = builder.load(tlab_cursor_ptr)

        # Load current arena_start (field 16) - becomes parent start
        arena_start_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 16)
        ], inbounds=True)
        old_arena_start = builder.load(arena_start_ptr)

        # Store old arena_start as arena_parent_start (field 17)
        arena_parent_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 17)
        ], inbounds=True)
        builder.store(old_arena_start, arena_parent_ptr)

        # Set new arena_start = cursor (field 16)
        builder.store(cursor, arena_start_ptr)

        # Set arena_cursor = cursor (field 15)
        arena_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 15)
        ], inbounds=True)
        builder.store(cursor, arena_cursor_ptr)

        # Return the arena start (for gc_arena_pop)
        builder.ret(cursor)

        # No thread entry - return NULL
        builder.position_at_end(no_entry)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_arena_alloc(self):
        """Bump allocation from the current arena.

        Allocates `size` bytes from the arena's bump pointer.
        Returns pointer to allocated memory, or NULL if arena is full
        (caller should fall back to gc_alloc for GC-tracked allocation).

        Arena objects have:
          - NO 32-byte header
          - NO handle in handle table
          - NO entry in allocation list
          - NOT tracked by GC

        This makes allocation extremely fast (just a pointer bump) but
        arena objects CANNOT survive beyond their scope.
        """
        func = self.gc_arena_alloc
        func.args[0].name = "size"

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        check_arena = func.append_basic_block("check_arena")
        do_alloc = func.append_basic_block("do_alloc")
        no_space = func.append_basic_block("no_space")

        builder = ir.IRBuilder(entry)

        size = func.args[0]

        # Align size to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.add(size, seven)
        aligned_size = builder.and_(aligned_size, builder.not_(seven))

        # Get current thread entry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, no_space, have_entry)

        builder.position_at_end(have_entry)

        # Load arena_cursor (field 15)
        arena_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 15)
        ], inbounds=True)
        cursor = builder.load(arena_cursor_ptr)

        # Check if cursor is valid (arena active)
        cursor_int = builder.ptrtoint(cursor, self.i64)
        is_null_cursor = builder.icmp_unsigned("==", cursor_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_cursor, no_space, check_arena)

        builder.position_at_end(check_arena)

        # Load tlab_limit (field 8) - arena shares TLAB's limit
        tlab_limit_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 8)
        ], inbounds=True)
        limit = builder.load(tlab_limit_ptr)

        # Calculate new cursor position
        new_cursor = builder.gep(cursor, [aligned_size])

        # Check if new_cursor <= limit
        new_cursor_int = builder.ptrtoint(new_cursor, self.i64)
        limit_int = builder.ptrtoint(limit, self.i64)
        has_space = builder.icmp_unsigned("<=", new_cursor_int, limit_int)
        builder.cbranch(has_space, do_alloc, no_space)

        # Allocate from arena
        builder.position_at_end(do_alloc)
        # Update arena_cursor
        builder.store(new_cursor, arena_cursor_ptr)
        # Also update tlab_cursor so arena and TLAB stay in sync
        tlab_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(new_cursor, tlab_cursor_ptr)
        # Return old cursor (the allocated memory)
        builder.ret(cursor)

        # No space - return NULL (caller should use gc_alloc)
        builder.position_at_end(no_space)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_arena_pop(self):
        """Pop the arena scope, bulk-freeing all arena allocations.

        Resets the TLAB cursor to the arena start, effectively freeing all
        objects allocated in the arena. Restores the parent arena's start
        for nested arena support.

        The `start` parameter must be the value returned by gc_arena_push().
        """
        func = self.gc_arena_pop
        func.args[0].name = "start"

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        start = func.args[0]

        # Get current thread entry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, done, have_entry)

        builder.position_at_end(have_entry)

        # Reset tlab_cursor to start (bulk free!)
        tlab_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        builder.store(start, tlab_cursor_ptr)

        # Load arena_parent_start (field 17) - restore parent arena
        arena_parent_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 17)
        ], inbounds=True)
        parent_start = builder.load(arena_parent_ptr)

        # Set arena_start to parent_start (field 16)
        arena_start_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 16)
        ], inbounds=True)
        builder.store(parent_start, arena_start_ptr)

        # Set arena_cursor to parent_start (field 15)
        arena_cursor_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 15)
        ], inbounds=True)
        builder.store(parent_start, arena_cursor_ptr)

        # Clear arena_parent_start (field 17) - parent's parent is now parent
        # Note: for deeply nested arenas, this would need a stack, but
        # for typical 2-3 deep nesting this works fine
        builder.store(ir.Constant(self.i8_ptr, None), arena_parent_ptr)

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_alloc_arena_or_gc(self):
        """Allocate from arena if active, otherwise fall back to GC allocation.

        This is a runtime function that:
        1. Calculates total size (user_size + header)
        2. Tries arena allocation via gc_arena_alloc
        3. If arena returns NULL, falls back to gc_alloc
        4. Initializes the header for arena objects
        5. Returns pointer to user area (after header)

        Args (via function parameters):
            size: i64 - Size of user data in bytes
            type_id: i32 - Type ID for GC tracing

        Returns:
            i8* - Pointer to allocated user area
        """
        func = self.gc_alloc_arena_or_gc
        func.args[0].name = "size"
        func.args[1].name = "type_id"

        entry = func.append_basic_block("entry")
        arena_ok = func.append_basic_block("arena_ok")
        arena_fallback = func.append_basic_block("arena_fallback")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        size = func.args[0]
        type_id = func.args[1]

        # Total size = header + user_size
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        total_size = builder.add(size, header_size)

        # Align to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.and_(
            builder.add(total_size, seven),
            ir.Constant(self.i64, ~7 & 0xFFFFFFFFFFFFFFFF)
        )

        # Try arena allocation (returns NULL if arena not active or full)
        arena_block = builder.call(self.gc_arena_alloc, [aligned_size])
        arena_block_int = builder.ptrtoint(arena_block, self.i64)
        arena_success = builder.icmp_unsigned("!=", arena_block_int, ir.Constant(self.i64, 0))

        builder.cbranch(arena_success, arena_ok, arena_fallback)

        # Arena allocation succeeded - initialize header
        builder.position_at_end(arena_ok)
        header_ptr = builder.bitcast(arena_block, self.header_type.as_pointer())

        # Store size
        size_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(size, size_ptr)

        # Store type_id (widen i32 to i64)
        type_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        type_id_64 = builder.zext(type_id, self.i64)
        builder.store(type_id_64, type_ptr)

        # Store flags with FLAG_ARENA and current mark bit
        flags_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        current_mark = builder.load(self.gc_current_mark_value)
        arena_flag = ir.Constant(self.i64, self.FLAG_ARENA | self.FLAG_TLAB)
        flags_value = builder.or_(current_mark, arena_flag)
        builder.store(flags_value, flags_ptr)

        # Store forward = 0 (no handle for arena objects)
        forward_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(ir.Constant(self.i64, 0), forward_ptr)

        # Get user pointer (after header)
        user_ptr_arena = builder.gep(arena_block, [header_size])
        builder.branch(done)

        # Arena not active or full - fall back to GC allocation
        builder.position_at_end(arena_fallback)
        handle = builder.call(self.gc_alloc, [size, type_id])
        user_ptr_gc = builder.call(self.gc_handle_deref, [handle])
        builder.branch(done)

        # Merge paths
        builder.position_at_end(done)
        user_ptr = builder.phi(self.i8_ptr, name="user_ptr")
        user_ptr.add_incoming(user_ptr_arena, arena_ok)
        user_ptr.add_incoming(user_ptr_gc, arena_fallback)

        # Zero the user data area to prevent the GC from tracing
        # uninitialized memory. The GC scans buffer contents based on
        # type_id (e.g. TYPE_LIST_TAIL scans all capacity slots,
        # TYPE_PV_NODE scans all 32 children). Without zeroing,
        # stale TLAB/heap data appears as random handles/pointers.
        builder.call(self.codegen.memset, [
            user_ptr, ir.Constant(ir.IntType(8), 0), size
        ])

        builder.ret(user_ptr)

    def _implement_gc_promote_to_heap(self):
        """Promote an arena-allocated object to the GC heap.

        This function is called when a formula returns a value that was
        allocated in the arena. Since the arena is bulk-freed on function
        return, escaping values must be copied to the GC heap.

        Algorithm:
        1. Check if ptr is NULL -> return NULL
        2. Read the header (ptr - HEADER_SIZE)
        3. Check FLAG_ARENA in flags
        4. If not arena-allocated, return ptr unchanged (already on heap)
        5. If arena-allocated:
           - Read size and type_id from header
           - Call gc_alloc(size, type_id) to get handle + new ptr
           - memcpy(new_ptr, old_ptr, size)
           - Return new_ptr

        Args (via function parameters):
            ptr: i8* - Pointer to user data of the object

        Returns:
            i8* - Pointer to user data (either same ptr or new heap copy)
        """
        func = self.gc_promote_to_heap
        func.args[0].name = "ptr"

        entry = func.append_basic_block("entry")
        check_arena = func.append_basic_block("check_arena")
        do_promote = func.append_basic_block("do_promote")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        ptr = func.args[0]

        # Check if ptr is NULL
        ptr_int = builder.ptrtoint(ptr, self.i64)
        is_null = builder.icmp_unsigned("==", ptr_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null, done, check_arena)

        # Check if arena-allocated
        builder.position_at_end(check_arena)

        # Get header pointer (ptr - HEADER_SIZE)
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        neg_header = builder.sub(ir.Constant(self.i64, 0), header_size)
        header_raw = builder.gep(ptr, [neg_header])
        header_ptr = builder.bitcast(header_raw, self.header_type.as_pointer())

        # Read flags (field 2)
        flags_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)
        ], inbounds=True)
        flags = builder.load(flags_ptr)

        # Check FLAG_ARENA
        arena_flag = ir.Constant(self.i64, self.FLAG_ARENA)
        is_arena = builder.and_(flags, arena_flag)
        is_arena_set = builder.icmp_unsigned("!=", is_arena, ir.Constant(self.i64, 0))

        builder.cbranch(is_arena_set, do_promote, done)

        # Promote: copy to GC heap
        builder.position_at_end(do_promote)

        # Read size (field 0)
        size_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
        ], inbounds=True)
        size = builder.load(size_ptr)

        # Read type_id (field 1)
        type_ptr = builder.gep(header_ptr, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        type_id_64 = builder.load(type_ptr)
        type_id = builder.trunc(type_id_64, self.i32)

        # Allocate on GC heap
        handle = builder.call(self.gc_alloc, [size, type_id])
        new_ptr = builder.call(self.gc_handle_deref, [handle])

        # memcpy(new_ptr, old_ptr, size)
        builder.call(self.codegen.memcpy, [new_ptr, ptr, size])

        builder.branch(done)

        # Merge paths
        builder.position_at_end(done)
        result = builder.phi(self.i8_ptr, name="result")
        result.add_incoming(ptr, entry)  # NULL case
        result.add_incoming(ptr, check_arena)  # Not arena-allocated
        result.add_incoming(new_ptr, do_promote)  # Promoted
        builder.ret(result)

    def _implement_gc_alloc_to_thread_list(self):
        """Add allocation node to current thread's allocation list (lock-free).

        Uses atomic compare-and-swap to prepend the node to the list head.
        This is safe for concurrent allocation and sweep operations:
        - Multiple allocators can prepend concurrently (CAS loop handles contention)
        - Sweeper atomically steals the list before processing

        The GC will sweep all thread lists during collection.
        """
        func = self.gc_alloc_to_thread_list
        func.args[0].name = "node"

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        cas_loop = func.append_basic_block("cas_loop")
        cas_success = func.append_basic_block("cas_success")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        node = func.args[0]

        # Allocate space to track expected value for CAS (must be in entry block)
        expected_alloca = builder.alloca(self.i8_ptr, name="expected")
        # Allocate space for thread entry pointer (may come from TLS or global fallback)
        thread_entry_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="thread_entry_ptr")

        # Get current thread entry (use pthread TLS)
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry from TLS
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        # BUG-060 fix: try global fallback before giving up
        try_global_fallback = func.append_basic_block("try_global_fallback")
        have_tls_entry = func.append_basic_block("have_tls_entry")
        builder.cbranch(is_null_entry, try_global_fallback, have_tls_entry)

        # TLS path succeeded - store to alloca and branch to have_entry
        builder.position_at_end(have_tls_entry)
        builder.store(thread_entry, thread_entry_alloca)
        builder.branch(have_entry)

        # Try the global tls_thread_entry fallback (set in gc_register_thread)
        builder.position_at_end(try_global_fallback)
        global_entry = builder.load(self.tls_thread_entry)
        global_entry_int = builder.ptrtoint(global_entry, self.i64)
        is_global_null = builder.icmp_unsigned("==", global_entry_int, ir.Constant(self.i64, 0))
        # If global is also NULL, give up (thread not registered)
        have_global = func.append_basic_block("have_global")
        skip_add = func.append_basic_block("skip_add")
        builder.cbranch(is_global_null, skip_add, have_global)

        # DEBUG: increment skip counter when no thread entry found
        builder.position_at_end(skip_add)
        builder.atomic_rmw('add', self.gc_debug_list_skips, ir.Constant(self.i64, 1), 'monotonic')
        builder.branch(done)

        # Use global entry
        builder.position_at_end(have_global)
        builder.store(global_entry, thread_entry_alloca)
        builder.branch(have_entry)

        builder.position_at_end(have_entry)
        # Load the thread entry from alloca (either from TLS or global fallback)
        thread_entry_typed = builder.load(thread_entry_alloca, name="thread_entry_loaded")

        # Get pointer to thread's alloc_list head (field 9)
        alloc_list_ptr = builder.gep(thread_entry_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 9)
        ], inbounds=True)

        # Prepare node pointer in alloc for CAS loop
        node_typed = builder.bitcast(node, self.alloc_node_type.as_pointer())
        node_next_ptr = builder.gep(node_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)

        # expected_alloca is created in entry block above

        # Load initial head value atomically
        initial_head = builder.load(alloc_list_ptr, align=8)
        builder.store(initial_head, expected_alloca)
        builder.branch(cas_loop)

        # CAS loop: try to atomically update head
        builder.position_at_end(cas_loop)
        expected = builder.load(expected_alloca)

        # Set node->next to expected head
        builder.store(expected, node_next_ptr)

        # Try atomic compare-and-swap: head = node if head == expected
        # cmpxchg returns {old_value, success_flag}
        cmpxchg_result = builder.cmpxchg(alloc_list_ptr, expected, node, 'acq_rel', 'acquire')
        old_value = builder.extract_value(cmpxchg_result, 0)
        success = builder.extract_value(cmpxchg_result, 1)

        # Create retry block to update expected and loop back
        cas_retry = func.append_basic_block("cas_retry")
        builder.cbranch(success, cas_success, cas_retry)

        # On CAS failure, update expected with actual value and retry
        builder.position_at_end(cas_retry)
        builder.store(old_value, expected_alloca)
        builder.branch(cas_loop)

        builder.position_at_end(cas_success)
        # DEBUG: increment success counter
        builder.atomic_rmw('add', self.gc_debug_list_adds, ir.Constant(self.i64, 1), 'monotonic')
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_sweep_thread_lists(self):
        """Sweep all per-thread allocation lists (lock-free).

        Uses atomic operations to safely sweep while allocations continue:
        1. Atomically steal each thread's list (exchange head with NULL)
        2. Process stolen list locally (no races - we own it)
        3. Build survivors list from marked nodes
        4. Atomically prepend survivors back to thread's list

        This allows allocations to continue without blocking during sweep.

        THREAD SAFETY: Only holds gc_registry_mutex to prevent thread
        unregistration during iteration. Allocation lists are accessed atomically.
        """
        func = self.gc_sweep_thread_lists

        entry = func.append_basic_block("entry")
        check_thread = func.append_basic_block("check_thread")
        process_thread = func.append_basic_block("process_thread")
        check_node = func.append_basic_block("check_node")
        process_node = func.append_basic_block("process_node")
        check_mark = func.append_basic_block("check_mark")
        marked_node = func.append_basic_block("marked_node")
        unmarked_node = func.append_basic_block("unmarked_node")
        next_node = func.append_basic_block("next_node")
        prepend_survivors = func.append_basic_block("prepend_survivors")
        next_thread = func.append_basic_block("next_thread")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Lock registry mutex to prevent threads from unregistering during sweep
        registry_mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [registry_mutex])

        # NO gc_mutex needed - we use atomic operations for list access

        # Allocate locals for iteration
        thread_ptr_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="curr_thread")
        curr_node_alloca = builder.alloca(self.i8_ptr, name="curr_node")
        handle_alloca = builder.alloca(self.i64, name="current_handle")
        alloc_list_ptr_alloca = builder.alloca(self.i8_ptr.as_pointer(), name="alloc_list_ptr")

        # Survivors list: head and tail for efficient appending
        survivors_head_alloca = builder.alloca(self.i8_ptr, name="survivors_head")
        survivors_tail_alloca = builder.alloca(self.i8_ptr, name="survivors_tail")

        # Alloca for CAS prepend expected value (must be in entry block)
        expected_prepend_alloca = builder.alloca(self.i8_ptr, name="expected_prepend")

        # Allocas for prepend CAS loop (all must be in entry block)
        alloc_ptr_prepend_alloca = builder.alloca(self.i8_ptr.as_pointer(), name="alloc_ptr_prepend")
        surv_tail_next_prepend_alloca = builder.alloca(self.i8_ptr.as_pointer(), name="surv_tail_next_prepend")

        # Alloca for stolen list (must be in entry block to avoid stack growth per thread)
        stolen_alloca = builder.alloca(self.i8_ptr, name="stolen")

        # Allocate counters for sweep statistics
        swept_count_alloca = builder.alloca(self.i64, name="swept_count")
        reclaimed_bytes_alloca = builder.alloca(self.i64, name="reclaimed_bytes")
        live_count_alloca = builder.alloca(self.i64, name="live_count")
        builder.store(ir.Constant(self.i64, 0), swept_count_alloca)
        builder.store(ir.Constant(self.i64, 0), reclaimed_bytes_alloca)
        builder.store(ir.Constant(self.i64, 0), live_count_alloca)

        # Get first thread from registry
        registry_head = builder.load(self.gc_thread_registry)
        builder.store(registry_head, thread_ptr_alloca)
        builder.branch(check_thread)

        # Check if there's a thread to process
        builder.position_at_end(check_thread)
        curr_thread = builder.load(thread_ptr_alloca)
        thread_int = builder.ptrtoint(curr_thread, self.i64)
        is_null_thread = builder.icmp_unsigned("==", thread_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_thread, done, process_thread)

        # Process this thread's allocation list
        builder.position_at_end(process_thread)

        # DEBUG: Increment thread counter
        builder.atomic_rmw('add', self.gc_debug_sweep_threads, ir.Constant(self.i64, 1), 'monotonic')

        # Get pointer to thread's alloc_list head (field 9)
        alloc_list_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 9)
        ], inbounds=True)
        builder.store(alloc_list_ptr, alloc_list_ptr_alloca)

        # Atomically steal the entire list (exchange with NULL) using CAS loop
        # This allows new allocations to continue to an empty list
        steal_loop = func.append_basic_block("steal_loop")
        steal_done = func.append_basic_block("steal_done")

        # stolen_alloca is in entry block to avoid stack growth per thread iteration
        initial_list = builder.load(alloc_list_ptr, align=8)
        builder.store(initial_list, stolen_alloca)
        builder.branch(steal_loop)

        builder.position_at_end(steal_loop)
        expected_list = builder.load(stolen_alloca)
        # Try to swap head with NULL
        steal_result = builder.cmpxchg(alloc_list_ptr, expected_list,
                                       ir.Constant(self.i8_ptr, None), 'acq_rel', 'acquire')
        old_list = builder.extract_value(steal_result, 0)
        steal_success = builder.extract_value(steal_result, 1)

        steal_retry = func.append_basic_block("steal_retry")
        builder.cbranch(steal_success, steal_done, steal_retry)

        builder.position_at_end(steal_retry)
        builder.store(old_list, stolen_alloca)
        builder.branch(steal_loop)

        builder.position_at_end(steal_done)
        stolen_list = builder.load(stolen_alloca)

        # DEBUG: Check if stolen list is empty
        stolen_int = builder.ptrtoint(stolen_list, self.i64)
        stolen_is_empty = builder.icmp_unsigned("==", stolen_int, ir.Constant(self.i64, 0))
        with builder.if_then(stolen_is_empty):
            builder.atomic_rmw('add', self.gc_debug_sweep_empty, ir.Constant(self.i64, 1), 'monotonic')

        # Initialize survivors list for this thread
        builder.store(ir.Constant(self.i8_ptr, None), survivors_head_alloca)
        builder.store(ir.Constant(self.i8_ptr, None), survivors_tail_alloca)

        # Start processing stolen list
        builder.store(stolen_list, curr_node_alloca)
        builder.branch(check_node)

        # Check if there's a node to process
        builder.position_at_end(check_node)
        curr_node = builder.load(curr_node_alloca)
        node_int = builder.ptrtoint(curr_node, self.i64)
        is_null_node = builder.icmp_unsigned("==", node_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_node, prepend_survivors, process_node)

        # Process this node
        builder.position_at_end(process_node)
        # DEBUG: Increment nodes seen counter
        builder.atomic_rmw('add', self.gc_debug_sweep_nodes, ir.Constant(self.i64, 1), 'monotonic')
        node_typed = builder.bitcast(curr_node, self.alloc_node_type.as_pointer())

        # Get node->handle (field 1) - this is an i64 handle, not a pointer!
        handle_ptr = builder.gep(node_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        builder.store(obj_handle, handle_alloca)

        # Get node->next (field 0) and save it before potentially freeing node
        node_next_ptr = builder.gep(node_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        next_node_val = builder.load(node_next_ptr)

        # Check if handle is null (0)
        is_null_handle = builder.icmp_unsigned("==", obj_handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_handle, next_node, check_mark)

        # Check mark bit
        builder.position_at_end(check_mark)

        # Dereference handle to get data pointer
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

        # Get header by subtracting HEADER_SIZE from data pointer
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.i8_ptr)
        header = builder.bitcast(header_ptr, self.header_type.as_pointer())

        # Get size field for statistics
        size_ptr = builder.gep(header, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)  # size field
        ], inbounds=True)
        obj_size = builder.load(size_ptr)

        # Get flags field
        flags_ptr = builder.gep(header, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 2)  # flags field
        ], inbounds=True)
        flags = builder.load(flags_ptr)

        # Extract mark bit
        mark_bit = builder.and_(flags, ir.Constant(self.i64, self.FLAG_MARK_BIT))
        current_mark = builder.load(self.gc_current_mark_value)

        # If mark_bit == current_mark, object is live
        is_marked = builder.icmp_unsigned("==", mark_bit, current_mark)
        builder.cbranch(is_marked, marked_node, unmarked_node)

        # Object is marked - add to survivors list
        builder.position_at_end(marked_node)

        # DEBUG: Increment marked counter
        builder.atomic_rmw('add', self.gc_debug_sweep_marked, ir.Constant(self.i64, 1), 'monotonic')

        # Increment live object count
        old_live = builder.load(live_count_alloca)
        new_live = builder.add(old_live, ir.Constant(self.i64, 1))
        builder.store(new_live, live_count_alloca)

        # Clear node->next (will be set when prepending back)
        builder.store(ir.Constant(self.i8_ptr, None), node_next_ptr)

        # Append to survivors list (tail append for efficient iteration)
        surv_tail = builder.load(survivors_tail_alloca)
        surv_tail_int = builder.ptrtoint(surv_tail, self.i64)
        is_empty_survivors = builder.icmp_unsigned("==", surv_tail_int, ir.Constant(self.i64, 0))

        with builder.if_else(is_empty_survivors) as (then_empty, else_append):
            with then_empty:
                # First survivor - set both head and tail
                builder.store(curr_node, survivors_head_alloca)
                builder.store(curr_node, survivors_tail_alloca)
            with else_append:
                # Append to tail
                tail_typed = builder.bitcast(surv_tail, self.alloc_node_type.as_pointer())
                tail_next_ptr_append = builder.gep(tail_typed, [
                    ir.Constant(self.i32, 0),
                    ir.Constant(self.i32, 0)
                ], inbounds=True)
                builder.store(curr_node, tail_next_ptr_append)
                builder.store(curr_node, survivors_tail_alloca)

        builder.branch(next_node)

        # Object is unmarked - free it
        builder.position_at_end(unmarked_node)

        # DEBUG: Increment unmarked counter
        builder.atomic_rmw('add', self.gc_debug_sweep_unmarked, ir.Constant(self.i64, 1), 'monotonic')

        # Increment swept count and bytes reclaimed
        old_swept = builder.load(swept_count_alloca)
        new_swept = builder.add(old_swept, ir.Constant(self.i64, 1))
        builder.store(new_swept, swept_count_alloca)
        old_reclaimed = builder.load(reclaimed_bytes_alloca)
        new_reclaimed = builder.add(old_reclaimed, obj_size)
        builder.store(new_reclaimed, reclaimed_bytes_alloca)

        # Check if object was allocated from TLAB (FLAG_TLAB bit set)
        tlab_bit = builder.and_(flags, ir.Constant(self.i64, self.FLAG_TLAB))
        is_tlab = builder.icmp_unsigned("!=", tlab_bit, ir.Constant(self.i64, 0))

        # Load tlab_base from node (field 3) - needed for TLAB reclamation
        tlab_base_ptr_node = builder.gep(node_typed, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)
        ], inbounds=True)
        node_tlab_base = builder.load(tlab_base_ptr_node)

        # Handle TLAB vs non-TLAB objects
        with builder.if_else(is_tlab) as (then_tlab, else_nontlab):
            with then_tlab:
                # DEBUG: TLAB object
                builder.atomic_rmw('add', self.gc_debug_tlab_freed, ir.Constant(self.i64, 1), 'monotonic')

                # Decrement TLAB's live_count and free if empty
                tlab_header = builder.bitcast(node_tlab_base, self.tlab_header_type.as_pointer())
                live_count_ptr_tlab = builder.gep(tlab_header, [
                    ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)
                ], inbounds=True)
                # atomic_rmw('sub') returns OLD value, so we check if old == 1 (meaning new == 0)
                old_live_count = builder.atomic_rmw('sub', live_count_ptr_tlab, ir.Constant(self.i64, 1), 'acq_rel')
                was_last = builder.icmp_unsigned("==", old_live_count, ir.Constant(self.i64, 1))

                with builder.if_then(was_last):
                    # TLAB is now empty - add to dead list for deferred freeing
                    # This avoids use-after-free when multiple objects in same TLAB die
                    builder.atomic_rmw('add', self.gc_debug_tlabs_reclaimed, ir.Constant(self.i64, 1), 'monotonic')
                    # Use TLAB header's next_tlab field to link into dead list
                    next_tlab_field = builder.gep(tlab_header, [
                        ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
                    ], inbounds=True)
                    old_dead_head = builder.load(self.gc_dead_tlab_list)
                    builder.store(old_dead_head, next_tlab_field)
                    builder.store(node_tlab_base, self.gc_dead_tlab_list)

                    # BUG-065 FIX: Reset thread's TLAB fields if this is the thread's current TLAB
                    # When a TLAB is added to the dead list, it will be munmap'd at end of sweep.
                    # If we don't reset the thread's TLAB fields, the next allocation will try to
                    # use stale pointers that point to freed memory, causing a crash.
                    thread_tlab_base_ptr = builder.gep(curr_thread, [
                        ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)  # tlab_base field
                    ], inbounds=True)
                    thread_tlab_base = builder.load(thread_tlab_base_ptr)
                    thread_tlab_base_int = builder.ptrtoint(thread_tlab_base, self.i64)
                    node_tlab_base_int = builder.ptrtoint(node_tlab_base, self.i64)
                    is_current_tlab = builder.icmp_unsigned("==", thread_tlab_base_int, node_tlab_base_int)

                    with builder.if_then(is_current_tlab):
                        # Reset tlab_base, tlab_cursor, tlab_limit to NULL
                        builder.store(ir.Constant(self.i8_ptr, None), thread_tlab_base_ptr)
                        thread_tlab_cursor_ptr = builder.gep(curr_thread, [
                            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)  # tlab_cursor field
                        ], inbounds=True)
                        builder.store(ir.Constant(self.i8_ptr, None), thread_tlab_cursor_ptr)
                        thread_tlab_limit_ptr = builder.gep(curr_thread, [
                            ir.Constant(self.i32, 0), ir.Constant(self.i32, 8)  # tlab_limit field
                        ], inbounds=True)
                        builder.store(ir.Constant(self.i8_ptr, None), thread_tlab_limit_ptr)

            with else_nontlab:
                # DEBUG: Non-TLAB object - actually freed
                builder.atomic_rmw('add', self.gc_debug_nontlab_freed, ir.Constant(self.i64, 1), 'monotonic')
                builder.call(self.codegen.free, [header_ptr])

        # Always free the allocation node (nodes are always from malloc)
        builder.call(self.codegen.free, [curr_node])

        # Retire the handle using MI-6 deferred reclamation
        freed_handle = builder.load(handle_alloca)
        builder.call(self.gc_handle_retire, [freed_handle])

        builder.branch(next_node)

        # Move to next node in stolen list
        builder.position_at_end(next_node)
        builder.store(next_node_val, curr_node_alloca)
        builder.branch(check_node)

        # Prepend survivors back to thread's list using "Link Before Publish" CAS loop
        # This pattern ensures the entire chain is valid before it becomes visible:
        # 1. Load old_head from alloc_list
        # 2. Link survivors_tail->next = old_head (LINK FIRST - before publishing!)
        # 3. CAS(alloc_list, expected=old_head, desired=survivors_head)
        # 4. If CAS fails (concurrent allocation happened), retry with updated old_head
        # This avoids the "Disconnected Tail" race where concurrent traversals see
        # a truncated list during the gap between exchange and tail linkage.
        builder.position_at_end(prepend_survivors)
        surv_head_final = builder.load(survivors_head_alloca)
        surv_tail_final = builder.load(survivors_tail_alloca)
        surv_head_int_final = builder.ptrtoint(surv_head_final, self.i64)
        surv_tail_int_final = builder.ptrtoint(surv_tail_final, self.i64)

        # Both head and tail must be non-null to have valid survivors
        head_ok = builder.icmp_unsigned("!=", surv_head_int_final, ir.Constant(self.i64, 0))
        tail_ok = builder.icmp_unsigned("!=", surv_tail_int_final, ir.Constant(self.i64, 0))
        has_survivors_final = builder.and_(head_ok, tail_ok)

        # Create all blocks upfront
        do_prepend_block = func.append_basic_block("do_prepend")
        prepend_cas_loop = func.append_basic_block("prepend_cas_loop")
        prepend_cas_success = func.append_basic_block("prepend_cas_success")
        prepend_cas_retry = func.append_basic_block("prepend_cas_retry")
        prepend_done_block = func.append_basic_block("prepend_done")

        # =====================================================================
        # Survivors prepend using "Link Before Publish" CAS pattern
        # =====================================================================
        # Branch based on whether we have survivors
        builder.cbranch(has_survivors_final, do_prepend_block, next_thread)

        # --- Do prepend: set up for CAS loop ---
        builder.position_at_end(do_prepend_block)

        # Load the alloc_list_ptr we stored earlier
        alloc_ptr_for_prepend = builder.load(alloc_list_ptr_alloca)

        # Store alloc_list_ptr for use in CAS loop
        builder.store(alloc_ptr_for_prepend, alloc_ptr_prepend_alloca)

        # Get survivors_tail->next pointer for linking
        surv_tail_typed = builder.bitcast(surv_tail_final, self.alloc_node_type.as_pointer())
        surv_tail_next_ptr = builder.gep(surv_tail_typed, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)  # next field
        ], inbounds=True)
        builder.store(surv_tail_next_ptr, surv_tail_next_prepend_alloca)

        # Load initial old_head for CAS
        old_head_init = builder.load(alloc_ptr_for_prepend, align=8)
        builder.store(old_head_init, expected_prepend_alloca)

        builder.branch(prepend_cas_loop)

        # --- CAS loop: link tail and try atomic swap ---
        builder.position_at_end(prepend_cas_loop)

        # Load expected old_head
        expected_head = builder.load(expected_prepend_alloca)

        # Load stored pointers
        alloc_ptr_reload = builder.load(alloc_ptr_prepend_alloca)
        tail_next_reload = builder.load(surv_tail_next_prepend_alloca)

        # Step 1: Link survivors_tail->next = old_head (LINK BEFORE PUBLISH!)
        builder.store(expected_head, tail_next_reload)

        # Step 2: CAS(alloc_list, expected=old_head, desired=survivors_head)
        cmpxchg_prepend = builder.cmpxchg(
            alloc_ptr_reload, expected_head, surv_head_final,
            'acq_rel', 'acquire'
        )
        cas_old = builder.extract_value(cmpxchg_prepend, 0)
        cas_success = builder.extract_value(cmpxchg_prepend, 1)

        builder.cbranch(cas_success, prepend_cas_success, prepend_cas_retry)

        # --- CAS success: continue to next thread ---
        builder.position_at_end(prepend_cas_success)
        builder.branch(prepend_done_block)

        # --- CAS retry: update expected and loop ---
        builder.position_at_end(prepend_cas_retry)
        builder.store(cas_old, expected_prepend_alloca)
        builder.branch(prepend_cas_loop)

        # --- Prepend done: continue to next thread ---
        builder.position_at_end(prepend_done_block)
        builder.branch(next_thread)

        # Move to next thread
        builder.position_at_end(next_thread)

        # Get next thread (field 11)
        curr_thread_reload = builder.load(thread_ptr_alloca)
        next_thread_ptr = builder.gep(curr_thread_reload, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 11)  # next field
        ], inbounds=True)
        next_thread_i8ptr = builder.load(next_thread_ptr)
        next_thread_typed = builder.bitcast(next_thread_i8ptr, self.thread_entry_type.as_pointer())
        builder.store(next_thread_typed, thread_ptr_alloca)
        builder.branch(check_thread)

        builder.position_at_end(done)

        # Update gc_stats with sweep results
        # objects_marked_last_cycle (offset 5) = live objects kept
        marked_stat_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)
        ], inbounds=True)
        final_live = builder.load(live_count_alloca)
        builder.store(final_live, marked_stat_ptr)

        # objects_swept_last_cycle (offset 6) = objects freed (CUMULATIVE)
        swept_stat_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)
        ], inbounds=True)
        final_swept = builder.load(swept_count_alloca)
        # Accumulate instead of overwrite
        builder.atomic_rmw('add', swept_stat_ptr, final_swept, 'monotonic')

        # bytes_reclaimed_last_cycle (offset 7)
        reclaimed_stat_ptr = builder.gep(self.gc_stats, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)
        ], inbounds=True)
        final_reclaimed = builder.load(reclaimed_bytes_alloca)
        builder.store(final_reclaimed, reclaimed_stat_ptr)

        # Free all dead TLABs (deferred from sweep to avoid use-after-free)
        free_tlab_loop = func.append_basic_block("free_tlab_loop")
        free_tlab_body = func.append_basic_block("free_tlab_body")
        free_tlab_done = func.append_basic_block("free_tlab_done")

        # Get and clear the dead list (sweep is single-threaded so regular load/store is safe)
        dead_head = builder.load(self.gc_dead_tlab_list)
        builder.store(ir.Constant(self.i8_ptr, None), self.gc_dead_tlab_list)
        dead_tlab_alloca = builder.alloca(self.i8_ptr, name="dead_tlab")
        builder.store(dead_head, dead_tlab_alloca)
        builder.branch(free_tlab_loop)

        builder.position_at_end(free_tlab_loop)
        curr_dead = builder.load(dead_tlab_alloca)
        curr_dead_int = builder.ptrtoint(curr_dead, self.i64)
        is_null_dead = builder.icmp_unsigned("==", curr_dead_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_dead, free_tlab_done, free_tlab_body)

        builder.position_at_end(free_tlab_body)
        # Get next TLAB before freeing (from header->next_tlab)
        dead_header = builder.bitcast(curr_dead, self.tlab_header_type.as_pointer())
        next_dead_ptr = builder.gep(dead_header, [
            ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)
        ], inbounds=True)
        next_dead = builder.load(next_dead_ptr)
        # Free this TLAB
        tlab_size_const = ir.Constant(self.i64, self.TLAB_SIZE)
        builder.call(self.munmap, [curr_dead, tlab_size_const])
        # Move to next
        builder.store(next_dead, dead_tlab_alloca)
        builder.branch(free_tlab_loop)

        builder.position_at_end(free_tlab_done)

        # Unlock registry mutex
        builder.call(self.pthread_mutex_unlock, [registry_mutex])
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
    # Phase 5: Mark Worklist Implementations for Concurrent Marking
    # ========================================================================

    def _implement_gc_mark_worklist_init(self):
        """Initialize the mark worklist.

        Allocates the initial worklist array via malloc.
        Called from gc_init.
        """
        func = self.gc_mark_worklist_init

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Allocate initial worklist: MARK_WORKLIST_INITIAL_SIZE * sizeof(i64)
        initial_size = ir.Constant(self.i64, self.MARK_WORKLIST_INITIAL_SIZE)
        bytes_to_alloc = builder.mul(initial_size, ir.Constant(self.i64, 8))  # 8 bytes per i64

        worklist_ptr = builder.call(self.codegen.malloc, [bytes_to_alloc])
        worklist_i64_ptr = builder.bitcast(worklist_ptr, self.i64_ptr)

        builder.store(worklist_i64_ptr, self.gc_mark_worklist)
        builder.store(initial_size, self.gc_mark_worklist_capacity)
        builder.store(ir.Constant(self.i64, 0), self.gc_mark_worklist_head)
        builder.store(ir.Constant(self.i64, 0), self.gc_mark_worklist_tail)

        builder.ret_void()

    def _implement_gc_mark_push(self):
        """Push a handle onto the mark worklist.

        If the worklist is full, calls gc_mark_worklist_grow to double it.
        """
        func = self.gc_mark_push
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        check_space = func.append_basic_block("check_space")
        do_push = func.append_basic_block("do_push")
        need_grow = func.append_basic_block("need_grow")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        handle = func.args[0]

        # Skip null handles
        is_null = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_null, done, check_space)

        builder.position_at_end(check_space)
        # Check if worklist is full
        head = builder.load(self.gc_mark_worklist_head)
        capacity = builder.load(self.gc_mark_worklist_capacity)
        is_full = builder.icmp_unsigned(">=", head, capacity)
        builder.cbranch(is_full, need_grow, do_push)

        builder.position_at_end(need_grow)
        builder.call(self.gc_mark_worklist_grow, [])
        builder.branch(do_push)

        builder.position_at_end(do_push)
        # Push handle at head index
        worklist = builder.load(self.gc_mark_worklist)
        head2 = builder.load(self.gc_mark_worklist_head)
        slot = builder.gep(worklist, [head2], inbounds=True)
        builder.store(handle, slot)

        # Increment head
        new_head = builder.add(head2, ir.Constant(self.i64, 1))
        builder.store(new_head, self.gc_mark_worklist_head)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_mark_pop(self):
        """Pop a handle from the mark worklist.

        Returns 0 if the worklist is empty.
        Uses tail pointer for popping (FIFO order for better cache locality).
        """
        func = self.gc_mark_pop

        entry = func.append_basic_block("entry")
        do_pop = func.append_basic_block("do_pop")
        empty = func.append_basic_block("empty")

        builder = ir.IRBuilder(entry)

        # Check if worklist is empty (tail >= head)
        tail = builder.load(self.gc_mark_worklist_tail)
        head = builder.load(self.gc_mark_worklist_head)
        is_empty = builder.icmp_unsigned(">=", tail, head)
        builder.cbranch(is_empty, empty, do_pop)

        builder.position_at_end(do_pop)
        # Pop from tail
        worklist = builder.load(self.gc_mark_worklist)
        tail2 = builder.load(self.gc_mark_worklist_tail)
        slot = builder.gep(worklist, [tail2], inbounds=True)
        handle = builder.load(slot)

        # Increment tail
        new_tail = builder.add(tail2, ir.Constant(self.i64, 1))
        builder.store(new_tail, self.gc_mark_worklist_tail)

        builder.ret(handle)

        builder.position_at_end(empty)
        builder.ret(ir.Constant(self.i64, 0))

    def _implement_gc_mark_drain(self):
        """Process the mark worklist until empty.

        This is the main marking loop - pops handles and marks them.
        gc_mark_object will push any child references back onto the worklist.
        """
        func = self.gc_mark_drain

        entry = func.append_basic_block("entry")
        drain_loop = func.append_basic_block("drain_loop")
        process = func.append_basic_block("process")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        builder.branch(drain_loop)

        builder.position_at_end(drain_loop)
        # Pop next handle
        handle = builder.call(self.gc_mark_pop, [])

        # Check if empty (handle == 0)
        is_done = builder.icmp_unsigned("==", handle, ir.Constant(self.i64, 0))
        builder.cbranch(is_done, done, process)

        builder.position_at_end(process)
        # Mark the object (this may push children to worklist)
        builder.call(self.gc_mark_object, [handle])
        builder.branch(drain_loop)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_mark_worklist_grow(self):
        """Double the worklist capacity.

        Allocates a new array, copies existing entries, frees old array.
        """
        func = self.gc_mark_worklist_grow

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Get current state
        old_worklist = builder.load(self.gc_mark_worklist)
        old_capacity = builder.load(self.gc_mark_worklist_capacity)
        head = builder.load(self.gc_mark_worklist_head)

        # New capacity = old * 2
        new_capacity = builder.mul(old_capacity, ir.Constant(self.i64, 2))
        new_bytes = builder.mul(new_capacity, ir.Constant(self.i64, 8))

        # Allocate new array
        new_worklist_ptr = builder.call(self.codegen.malloc, [new_bytes])
        new_worklist = builder.bitcast(new_worklist_ptr, self.i64_ptr)

        # Copy existing entries (from tail to head)
        # For simplicity, use memcpy for the active entries
        tail = builder.load(self.gc_mark_worklist_tail)
        count = builder.sub(head, tail)
        bytes_to_copy = builder.mul(count, ir.Constant(self.i64, 8))

        # Source = old_worklist + tail
        src = builder.gep(old_worklist, [tail], inbounds=True)
        src_i8 = builder.bitcast(src, self.i8_ptr)
        dst_i8 = builder.bitcast(new_worklist, self.i8_ptr)

        # Call memcpy (dest, src, len)
        builder.call(self.codegen.memcpy, [dst_i8, src_i8, bytes_to_copy])

        # Free old worklist
        old_worklist_i8 = builder.bitcast(old_worklist, self.i8_ptr)
        builder.call(self.codegen.free, [old_worklist_i8])

        # Update globals
        builder.store(new_worklist, self.gc_mark_worklist)
        builder.store(new_capacity, self.gc_mark_worklist_capacity)
        # Reset indices: head = count, tail = 0
        builder.store(count, self.gc_mark_worklist_head)
        builder.store(ir.Constant(self.i64, 0), self.gc_mark_worklist_tail)

        builder.ret_void()

    def _implement_gc_mark_worklist_reset(self):
        """Reset the worklist at the start of each GC cycle.

        Just resets head and tail to 0 (array is reused).
        """
        func = self.gc_mark_worklist_reset

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        builder.store(ir.Constant(self.i64, 0), self.gc_mark_worklist_head)
        builder.store(ir.Constant(self.i64, 0), self.gc_mark_worklist_tail)

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
        collect_fmt = "[GC:STATS] collections: %lld, live_objects: %lld, swept: %lld, reclaimed_bytes: %lld\n"
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
        reclaimed_ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 7)], inbounds=True)
        reclaimed = builder.load(reclaimed_ptr)
        builder.call(printf, [collect_ptr, collections, marked, swept, reclaimed])

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

        # DEBUG: List add stats
        debug_fmt = "[GC:DEBUG] adds: %lld, tlab_freed: %lld, tlabs_reclaimed: %lld\n"
        debug_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(debug_fmt) + 1), name=".gc_stats_debug")
        debug_global.global_constant = True
        debug_global.linkage = 'private'
        debug_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(debug_fmt) + 1),
                                                 bytearray(debug_fmt.encode('utf-8')) + bytearray([0]))
        debug_ptr = builder.bitcast(debug_global, self.i8_ptr)

        list_adds = builder.load(self.gc_debug_list_adds)
        tlab_freed = builder.load(self.gc_debug_tlab_freed)
        tlabs_reclaimed = builder.load(self.gc_debug_tlabs_reclaimed)
        builder.call(printf, [debug_ptr, list_adds, tlab_freed, tlabs_reclaimed])

        # DEBUG: Handle table stats - check if handles are being reused
        handle_fmt = "[GC:DEBUG] next_handle: %lld, table_size: %lld\n"
        handle_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(handle_fmt) + 1), name=".gc_stats_handle")
        handle_global.global_constant = True
        handle_global.linkage = 'private'
        handle_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(handle_fmt) + 1),
                                                 bytearray(handle_fmt.encode('utf-8')) + bytearray([0]))
        handle_ptr = builder.bitcast(handle_global, self.i8_ptr)

        next_handle = builder.load(self.gc_next_handle)
        table_size = builder.load(self.gc_handle_table_size)
        builder.call(printf, [handle_ptr, next_handle, table_size])

        # Flush stdout to ensure output appears immediately
        fflush_ty = ir.FunctionType(self.i32, [self.i8_ptr])
        if "fflush" in self.module.globals:
            fflush = self.module.globals["fflush"]
        else:
            fflush = ir.Function(self.module, fflush_ty, name="fflush")
        builder.call(fflush, [ir.Constant(self.i8_ptr, None)])  # fflush(NULL) flushes all streams

        builder.ret_void()

    def _implement_gc_stat_getters(self):
        """Implement getter functions for heapwatch.

        These are simple functions that load a global value and return it.
        Used by the heapwatch library to display GC statistics.
        """
        # gc_get_total_allocations() -> i64
        func = self.gc_get_total_allocations
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        val = builder.load(ptr)
        builder.ret(val)

        # gc_get_total_bytes() -> i64
        func = self.gc_get_total_bytes
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        val = builder.load(ptr)
        builder.ret(val)

        # gc_get_collections() -> i64
        func = self.gc_get_collections
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        val = builder.load(ptr)
        builder.ret(val)

        # gc_get_live_objects() -> i64
        func = self.gc_get_live_objects
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 5)], inbounds=True)
        val = builder.load(ptr)
        builder.ret(val)

        # gc_get_swept_objects() -> i64
        func = self.gc_get_swept_objects
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        ptr = builder.gep(self.gc_stats, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 6)], inbounds=True)
        val = builder.load(ptr)
        builder.ret(val)

        # gc_get_next_handle() -> i64
        func = self.gc_get_next_handle
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        val = builder.load(self.gc_next_handle)
        builder.ret(val)

        # gc_get_handle_table_size() -> i64
        func = self.gc_get_handle_table_size
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        val = builder.load(self.gc_handle_table_size)
        builder.ret(val)

        # gc_get_tlabs_reclaimed() -> i64
        func = self.gc_get_tlabs_reclaimed
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        val = builder.load(self.gc_debug_tlabs_reclaimed)
        builder.ret(val)

    def _implement_gc_dump_heap(self):
        """Implement function to print all objects in the heap.

        Iterates through per-thread allocation lists (ThreadEntry.alloc_list)
        since allocations are tracked per-thread, not in a global list.
        """
        func = self.gc_dump_heap

        entry = func.append_basic_block("entry")
        check_thread = func.append_basic_block("check_thread")
        process_thread = func.append_basic_block("process_thread")
        check_node = func.append_basic_block("check_node")
        print_obj = func.append_basic_block("print_obj")
        next_node = func.append_basic_block("next_node")
        next_thread = func.append_basic_block("next_thread")
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

        # Allocate counter and iteration variables
        count_alloca = builder.alloca(self.i64, name="count")
        builder.store(ir.Constant(self.i64, 0), count_alloca)

        thread_ptr_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="curr_thread")
        curr_node_alloca = builder.alloca(self.i8_ptr, name="curr_node")

        # Lock registry mutex to prevent thread registry changes during iteration
        registry_mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [registry_mutex])

        # Get first thread from registry
        registry_head = builder.load(self.gc_thread_registry)
        builder.store(registry_head, thread_ptr_alloca)
        builder.branch(check_thread)

        # Check if there's a thread to process
        builder.position_at_end(check_thread)
        curr_thread = builder.load(thread_ptr_alloca)
        thread_int = builder.ptrtoint(curr_thread, self.i64)
        is_null_thread = builder.icmp_unsigned("==", thread_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_thread, done, process_thread)

        # Process this thread's allocation list
        builder.position_at_end(process_thread)
        # Get thread's alloc_list head (field 9)
        alloc_list_ptr = builder.gep(curr_thread, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 9)
        ], inbounds=True)
        list_head = builder.load(alloc_list_ptr)
        builder.store(list_head, curr_node_alloca)
        builder.branch(check_node)

        # Check if there's a node to process
        builder.position_at_end(check_node)
        curr_node = builder.load(curr_node_alloca)
        node_int = builder.ptrtoint(curr_node, self.i64)
        is_null_node = builder.icmp_unsigned("==", node_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_node, next_thread, print_obj)

        # Print object info
        builder.position_at_end(print_obj)
        node = builder.bitcast(curr_node, self.alloc_node_type.as_pointer())

        # Get handle and dereference to get data pointer
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)

        # Skip null handles (freed objects)
        is_null_handle = builder.icmp_unsigned("==", obj_handle, ir.Constant(self.i64, 0))
        # We need a block to handle null handles
        print_obj_valid = func.append_basic_block("print_obj_valid")
        builder.cbranch(is_null_handle, next_node, print_obj_valid)

        builder.position_at_end(print_obj_valid)
        # Re-load values after branch
        node2 = builder.bitcast(curr_node, self.alloc_node_type.as_pointer())
        handle_ptr2 = builder.gep(node2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle2 = builder.load(handle_ptr2)
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle2])

        # Get header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr_local = builder.inttoptr(header_int, self.header_type.as_pointer())

        # Load header fields
        size_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        size = builder.load(size_ptr)
        type_id_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        flags_ptr = builder.gep(header_ptr_local, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)

        # Extract mark bit
        marked = builder.and_(flags, ir.Constant(self.i64, self.FLAG_MARK_BIT))

        builder.call(printf, [obj_ptr, data_ptr, type_id, size, marked])

        # Increment counter
        count_val = builder.load(count_alloca)
        new_count = builder.add(count_val, ir.Constant(self.i64, 1))
        builder.store(new_count, count_alloca)

        builder.branch(next_node)

        # Get next node in this thread's list
        builder.position_at_end(next_node)
        curr_node_reload = builder.load(curr_node_alloca)
        node3 = builder.bitcast(curr_node_reload, self.alloc_node_type.as_pointer())
        next_ptr_ptr = builder.gep(node3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_ptr = builder.load(next_ptr_ptr)
        builder.store(next_ptr, curr_node_alloca)
        builder.branch(check_node)

        # Move to next thread
        builder.position_at_end(next_thread)
        curr_thread2 = builder.load(thread_ptr_alloca)
        # Get thread's next pointer (field 11 = offset 88)
        next_thread_ptr = builder.gep(curr_thread2, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 11)
        ], inbounds=True)
        next_thread_i8 = builder.load(next_thread_ptr)
        next_thread_val = builder.bitcast(next_thread_i8, self.thread_entry_type.as_pointer())
        builder.store(next_thread_val, thread_ptr_alloca)
        builder.branch(check_thread)

        # Done - unlock mutex and print count
        builder.position_at_end(done)
        builder.call(self.pthread_mutex_unlock, [registry_mutex])
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

    def _implement_gc_validate_handle_storage(self):
        """Validate that stored values in reference-type buffers look like handles.

        HANDLE STORAGE INVARIANT: All stored references to GC-managed objects must be
        handles (small i64 indices into handle table), never raw pointers.

        This debug function walks through objects with TYPE_LIST_TAIL_REF and
        TYPE_ARRAY_DATA_REF, checking each stored value. A handle should be:
        - A small positive integer (index into handle table)
        - Less than gc_next_handle (the next available handle)
        - Much smaller than typical pointer values (which are > 0x100000000)

        A value that looks like a pointer (very large address, e.g., > 4GB) is
        likely a bug where code stored a raw pointer instead of a handle.

        Returns the count of suspicious values (potential invariant violations).
        """
        func = self.gc_validate_handle_storage

        entry = func.append_basic_block("entry")
        check_thread = func.append_basic_block("check_thread")
        process_thread = func.append_basic_block("process_thread")
        node_loop = func.append_basic_block("node_loop")
        check_obj = func.append_basic_block("check_obj")
        check_type = func.append_basic_block("check_type")
        validate_ref_buffer = func.append_basic_block("validate_ref_buffer")
        elem_loop = func.append_basic_block("elem_loop")
        check_elem = func.append_basic_block("check_elem")
        elem_suspicious = func.append_basic_block("elem_suspicious")
        elem_next = func.append_basic_block("elem_next")
        next_node = func.append_basic_block("next_node")
        next_thread = func.append_basic_block("next_thread")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Get printf
        printf_ty = ir.FunctionType(self.i32, [self.i8_ptr], var_arg=True)
        if "printf" in self.module.globals:
            printf = self.module.globals["printf"]
        else:
            printf = ir.Function(self.module, printf_ty, name="printf")

        # Violation counter
        violations = builder.alloca(self.i64, name="violations")
        builder.store(ir.Constant(self.i64, 0), violations)

        # Objects checked counter
        objects_checked = builder.alloca(self.i64, name="objects_checked")
        builder.store(ir.Constant(self.i64, 0), objects_checked)

        # Thread pointer for linked list traversal
        thread_ptr_alloca = builder.alloca(self.thread_entry_type.as_pointer(), name="curr_thread")
        curr_node_alloca = builder.alloca(self.i8_ptr, name="curr_node")

        # Element loop variables (must be allocated in entry block)
        elem_idx_alloca = builder.alloca(self.i64, name="elem_idx")
        elem_count_alloca = builder.alloca(self.i64, name="elem_count")
        handles_ptr_alloca = builder.alloca(self.i64_ptr, name="handles_ptr")

        # Header message
        hdr_fmt = "[GC:VALIDATE] Checking handle storage invariant...\n"
        hdr_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(hdr_fmt) + 1), name=".validate_hdr")
        hdr_global.global_constant = True
        hdr_global.linkage = 'private'
        hdr_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(hdr_fmt) + 1),
                                              bytearray(hdr_fmt.encode('utf-8')) + bytearray([0]))
        hdr_ptr = builder.bitcast(hdr_global, self.i8_ptr)
        builder.call(printf, [hdr_ptr])

        # Threshold: values above this are suspicious (likely pointers, not handles)
        # 4GB = 0x100000000 = 4294967296 - any value above this is likely a pointer
        POINTER_THRESHOLD = 0x100000000

        # Get next_handle for upper bound check
        next_handle = builder.load(self.gc_next_handle)

        # Lock registry mutex to prevent thread registry changes during iteration
        registry_mutex = builder.load(self.gc_registry_mutex)
        builder.call(self.pthread_mutex_lock, [registry_mutex])

        # Get first thread from registry (linked list head)
        registry_head = builder.load(self.gc_thread_registry)
        builder.store(registry_head, thread_ptr_alloca)
        builder.branch(check_thread)

        # Check if there's a thread to process
        builder.position_at_end(check_thread)
        curr_thread = builder.load(thread_ptr_alloca)
        thread_int = builder.ptrtoint(curr_thread, self.i64)
        is_null_thread = builder.icmp_unsigned("==", thread_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_thread, done, process_thread)

        # Process this thread's allocation list
        builder.position_at_end(process_thread)
        # Get thread's alloc_list head (field 9)
        alloc_list_ptr = builder.gep(curr_thread,
            [ir.Constant(self.i32, 0), ir.Constant(self.i32, 9)], inbounds=True)
        alloc_head = builder.load(alloc_list_ptr)
        builder.store(alloc_head, curr_node_alloca)
        builder.branch(node_loop)

        # Node loop
        builder.position_at_end(node_loop)
        node_val = builder.load(curr_node_alloca)
        node_int = builder.ptrtoint(node_val, self.i64)
        is_null = builder.icmp_unsigned("==", node_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null, next_thread, check_obj)

        # Check object
        builder.position_at_end(check_obj)
        node = builder.bitcast(node_val, self.alloc_node_type.as_pointer())

        # Get handle from node and dereference
        handle_ptr = builder.gep(node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        obj_handle = builder.load(handle_ptr)
        data_ptr = builder.call(self.gc_handle_deref, [obj_handle])

        # Get type_id from header
        data_int = builder.ptrtoint(data_ptr, self.i64)
        header_int = builder.sub(data_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header = builder.inttoptr(header_int, self.header_type.as_pointer())
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        obj_size = builder.load(size_ptr)

        builder.branch(check_type)

        # Check if this is a reference-type buffer (LIST_TAIL_REF or ARRAY_DATA_REF)
        builder.position_at_end(check_type)
        is_list_tail_ref = builder.icmp_unsigned("==", type_id, ir.Constant(self.i64, self.TYPE_LIST_TAIL_REF))
        is_array_data_ref = builder.icmp_unsigned("==", type_id, ir.Constant(self.i64, self.TYPE_ARRAY_DATA_REF))
        is_ref_buffer = builder.or_(is_list_tail_ref, is_array_data_ref)
        builder.cbranch(is_ref_buffer, validate_ref_buffer, next_node)

        # Validate reference buffer - each element should be a handle
        builder.position_at_end(validate_ref_buffer)

        # Increment objects checked
        old_checked = builder.load(objects_checked)
        builder.store(builder.add(old_checked, ir.Constant(self.i64, 1)), objects_checked)

        # Calculate element count (size / 8, since handles are i64)
        elem_count = builder.udiv(obj_size, ir.Constant(self.i64, 8))
        handles_ptr = builder.bitcast(data_ptr, self.i64_ptr)

        # Initialize loop variables (allocas are in entry block)
        builder.store(ir.Constant(self.i64, 0), elem_idx_alloca)
        builder.store(elem_count, elem_count_alloca)
        builder.store(handles_ptr, handles_ptr_alloca)

        builder.branch(elem_loop)

        # Element loop
        builder.position_at_end(elem_loop)
        idx = builder.load(elem_idx_alloca)
        count = builder.load(elem_count_alloca)
        done_elems = builder.icmp_unsigned(">=", idx, count)
        builder.cbranch(done_elems, next_node, check_elem)

        # Check element value
        builder.position_at_end(check_elem)
        handles_ptr_val = builder.load(handles_ptr_alloca)
        elem_ptr = builder.gep(handles_ptr_val, [idx], inbounds=True)
        elem_val = builder.load(elem_ptr)

        # A valid handle should be:
        # 1. Less than gc_next_handle (the next available handle)
        # 2. Less than POINTER_THRESHOLD (definitely not a pointer)
        # We check if it exceeds the threshold OR exceeds next_handle
        is_above_threshold = builder.icmp_unsigned(">", elem_val, ir.Constant(self.i64, POINTER_THRESHOLD))
        is_above_next_handle = builder.icmp_unsigned(">=", elem_val, next_handle)
        is_suspicious = builder.or_(is_above_threshold, is_above_next_handle)

        # Also allow 0 (null handle)
        is_zero = builder.icmp_unsigned("==", elem_val, ir.Constant(self.i64, 0))
        is_suspicious = builder.and_(is_suspicious, builder.not_(is_zero))

        builder.cbranch(is_suspicious, elem_suspicious, elem_next)

        # Report suspicious value
        builder.position_at_end(elem_suspicious)
        warn_fmt = "[GC:VALIDATE] WARNING: Object handle=%lld type=%lld elem[%lld] = %lld (looks like pointer, not handle!)\n"
        warn_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(warn_fmt) + 1), name=".validate_warn")
        warn_global.global_constant = True
        warn_global.linkage = 'private'
        warn_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(warn_fmt) + 1),
                                               bytearray(warn_fmt.encode('utf-8')) + bytearray([0]))
        warn_ptr = builder.bitcast(warn_global, self.i8_ptr)
        builder.call(printf, [warn_ptr, obj_handle, type_id, idx, elem_val])

        # Increment violation count
        old_violations = builder.load(violations)
        builder.store(builder.add(old_violations, ir.Constant(self.i64, 1)), violations)
        builder.branch(elem_next)

        # Next element
        builder.position_at_end(elem_next)
        old_idx = builder.load(elem_idx_alloca)
        builder.store(builder.add(old_idx, ir.Constant(self.i64, 1)), elem_idx_alloca)
        builder.branch(elem_loop)

        # Next node in allocation list
        builder.position_at_end(next_node)
        curr_node_reload = builder.load(curr_node_alloca)
        node_reload = builder.bitcast(curr_node_reload, self.alloc_node_type.as_pointer())
        next_ptr_ptr = builder.gep(node_reload, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        next_ptr = builder.load(next_ptr_ptr)
        builder.store(next_ptr, curr_node_alloca)
        builder.branch(node_loop)

        # Move to next thread in linked list (field 11 = next pointer)
        builder.position_at_end(next_thread)
        curr_thread_reload = builder.load(thread_ptr_alloca)
        next_thread_ptr = builder.gep(curr_thread_reload, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 11)  # next field in ThreadEntry
        ], inbounds=True)
        next_thread_i8 = builder.load(next_thread_ptr)
        next_thread_typed = builder.bitcast(next_thread_i8, self.thread_entry_type.as_pointer())
        builder.store(next_thread_typed, thread_ptr_alloca)
        builder.branch(check_thread)

        # Done - unlock mutex, print summary and return violation count
        builder.position_at_end(done)
        builder.call(self.pthread_mutex_unlock, [registry_mutex])

        summary_fmt = "[GC:VALIDATE] Checked %lld ref-type buffers, found %lld violations\n"
        summary_global = ir.GlobalVariable(self.module, ir.ArrayType(self.i8, len(summary_fmt) + 1), name=".validate_summary")
        summary_global.global_constant = True
        summary_global.linkage = 'private'
        summary_global.initializer = ir.Constant(ir.ArrayType(self.i8, len(summary_fmt) + 1),
                                                  bytearray(summary_fmt.encode('utf-8')) + bytearray([0]))
        summary_ptr = builder.bitcast(summary_global, self.i8_ptr)
        final_checked = builder.load(objects_checked)
        final_violations = builder.load(violations)
        builder.call(printf, [summary_ptr, final_checked, final_violations])

        builder.ret(final_violations)

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

    def _implement_gc_handle_pool_alloc(self):
        """Fast-path handle allocation from thread-local pool.

        Allocates a handle from the current thread's pre-allocated pool.
        No locking required - purely thread-local operation.

        Returns:
            i64 handle index if pool has available handles
            0 if pool is empty (caller must call gc_handle_pool_refill)

        ThreadEntry fields used:
            - handle_pool_start (field 18): first handle index in pool
            - handle_pool_next (field 19): next available handle in pool
            - handle_pool_end (field 20): one past last handle in pool
        """
        func = self.gc_handle_pool_alloc

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        check_pool = func.append_basic_block("check_pool")
        alloc_from_pool = func.append_basic_block("alloc_from_pool")
        pool_empty = func.append_basic_block("pool_empty")

        builder = ir.IRBuilder(entry)

        # Get current thread entry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, pool_empty, have_entry)

        builder.position_at_end(have_entry)

        # Load handle_pool_next (field 19)
        pool_next_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 19)
        ], inbounds=True)
        pool_next = builder.load(pool_next_ptr)

        # Load handle_pool_end (field 20)
        pool_end_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 20)
        ], inbounds=True)
        pool_end = builder.load(pool_end_ptr)

        builder.branch(check_pool)

        # Check if pool has available handles
        builder.position_at_end(check_pool)
        has_handle = builder.icmp_unsigned("<", pool_next, pool_end)
        builder.cbranch(has_handle, alloc_from_pool, pool_empty)

        # Allocate handle from pool (fast path)
        builder.position_at_end(alloc_from_pool)
        # The handle index is pool_next
        handle = pool_next

        # Increment pool_next
        new_next = builder.add(pool_next, ir.Constant(self.i64, 1))
        builder.store(new_next, pool_next_ptr)

        # Return the allocated handle
        builder.ret(handle)

        # Pool is empty - return 0 to signal caller to refill
        builder.position_at_end(pool_empty)
        builder.ret(ir.Constant(self.i64, 0))

    def _implement_gc_handle_pool_refill(self):
        """Slow-path handle pool refill.

        Called when gc_handle_pool_alloc returns 0 (pool empty).
        Acquires mutex and allocates HANDLE_POOL_SIZE (512) handles in batch.

        IMPORTANT: Try free list first before bump allocation! (BUG-062 fix)
        The free list contains handles retired by previous GC cycles.
        Bump allocation should only be used when free list is exhausted.

        This is the only place that touches the global handle table for
        allocation - all other allocations go through the thread-local pool.

        ThreadEntry fields updated:
            - handle_pool_start (field 18): set to first handle in new batch
            - handle_pool_next (field 19): set to first handle in new batch
            - handle_pool_end (field 20): set to first handle + HANDLE_POOL_SIZE
        """
        func = self.gc_handle_pool_refill

        entry = func.append_basic_block("entry")
        have_entry = func.append_basic_block("have_entry")
        try_free_list = func.append_basic_block("try_free_list")
        drain_free_list = func.append_basic_block("drain_free_list")
        check_pool_full = func.append_basic_block("check_pool_full")
        pool_ready = func.append_basic_block("pool_ready")
        use_bump = func.append_basic_block("use_bump")
        need_grow = func.append_basic_block("need_grow")
        do_bump = func.append_basic_block("do_bump")
        finish = func.append_basic_block("finish")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)

        # Get current thread entry via pthread TLS
        tls_key = builder.load(self.tls_thread_entry_key)
        thread_entry_i8 = builder.call(self.pthread_getspecific, [tls_key])
        thread_entry = builder.bitcast(thread_entry_i8, self.thread_entry_type.as_pointer())
        thread_entry_int = builder.ptrtoint(thread_entry, self.i64)

        # Check if we have a thread entry
        is_null_entry = builder.icmp_unsigned("==", thread_entry_int, ir.Constant(self.i64, 0))
        builder.cbranch(is_null_entry, done, have_entry)

        builder.position_at_end(have_entry)

        # Lock mutex for handle allocation
        mutex_ptr = builder.load(self.gc_mutex)
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Allocate stack space for collecting handles from free list
        pool_size = ir.Constant(self.i64, self.HANDLE_POOL_SIZE)
        pool_handles = builder.alloca(ir.ArrayType(self.i64, self.HANDLE_POOL_SIZE), name="pool_handles")
        pool_count = builder.alloca(self.i64, name="pool_count")
        builder.store(ir.Constant(self.i64, 0), pool_count)

        builder.branch(try_free_list)

        # ============================================================
        # BUG-062 FIX: Try free list first before bump allocation
        # ============================================================
        builder.position_at_end(try_free_list)
        free_head = builder.load(self.gc_handle_free_list)
        free_head_int = builder.ptrtoint(free_head, self.i64) if free_head.type == self.i8_ptr else free_head
        # Actually gc_handle_free_list is i64, not i8*
        free_head_val = builder.load(self.gc_handle_free_list)
        has_free = builder.icmp_unsigned('!=', free_head_val, ir.Constant(self.i64, 0))
        builder.cbranch(has_free, drain_free_list, use_bump)

        # Drain handles from free list into local array
        builder.position_at_end(drain_free_list)
        current_count = builder.load(pool_count)
        is_pool_full = builder.icmp_unsigned('>=', current_count, pool_size)
        builder.cbranch(is_pool_full, pool_ready, check_pool_full)

        builder.position_at_end(check_pool_full)
        # Get current free list head
        curr_free = builder.load(self.gc_handle_free_list)
        has_more_free = builder.icmp_unsigned('!=', curr_free, ir.Constant(self.i64, 0))

        # If free list empty, check if we got any handles
        check_got_any = func.append_basic_block("check_got_any")
        get_one_handle = func.append_basic_block("get_one_handle")
        builder.cbranch(has_more_free, get_one_handle, check_got_any)

        builder.position_at_end(get_one_handle)
        # Pop one handle from free list
        table = builder.load(self.gc_handle_table)
        slot_ptr = builder.gep(table, [curr_free])
        next_free_ptr = builder.load(slot_ptr)
        next_free = builder.ptrtoint(next_free_ptr, self.i64)
        # Update free list head
        builder.store(next_free, self.gc_handle_free_list)
        # Clear the slot (will be set by gc_handle_store later)
        builder.store(ir.Constant(self.i8_ptr, None), slot_ptr)
        # Store handle in local array
        cnt = builder.load(pool_count)
        handle_slot = builder.gep(pool_handles, [ir.Constant(self.i64, 0), cnt])
        builder.store(curr_free, handle_slot)
        # Increment count
        new_cnt = builder.add(cnt, ir.Constant(self.i64, 1))
        builder.store(new_cnt, pool_count)
        builder.branch(drain_free_list)

        builder.position_at_end(check_got_any)
        got_count = builder.load(pool_count)
        got_any = builder.icmp_unsigned('>', got_count, ir.Constant(self.i64, 0))
        builder.cbranch(got_any, pool_ready, use_bump)

        # Pool is ready from free list - set up thread's pool
        builder.position_at_end(pool_ready)
        # Get first handle from our collected array
        first_handle_ptr = builder.gep(pool_handles, [ir.Constant(self.i64, 0), ir.Constant(self.i64, 0)])
        first_handle = builder.load(first_handle_ptr)
        final_count = builder.load(pool_count)
        # For free list handles, we can't use contiguous range
        # Instead, we return them one by one to the global free list and take first one
        # Actually, simpler approach: just take the first handle and set pool to single-element
        # The pool mechanism expects contiguous handles, so we'll just refill with 1 handle at a time
        # from free list, which is less efficient but correct.
        #
        # Better approach: store handles in reverse order back to free list except first one,
        # and give thread just the first handle as a pool of 1.
        #
        # Actually, the simplest correct fix: if we got handles from free list,
        # push all but the first back to free list, and give thread a pool of size 1.
        # On next refill, we'll get another handle from free list.

        # Push all except first handle back to free list
        push_back_loop = func.append_basic_block("push_back_loop")
        push_back_body = func.append_basic_block("push_back_body")
        push_back_done = func.append_basic_block("push_back_done")

        push_idx = builder.alloca(self.i64, name="push_idx")
        builder.store(ir.Constant(self.i64, 1), push_idx)  # Start at index 1
        builder.branch(push_back_loop)

        builder.position_at_end(push_back_loop)
        pidx = builder.load(push_idx)
        fcnt = builder.load(pool_count)
        done_pushing = builder.icmp_unsigned('>=', pidx, fcnt)
        builder.cbranch(done_pushing, push_back_done, push_back_body)

        builder.position_at_end(push_back_body)
        # Get handle at index pidx
        h_ptr = builder.gep(pool_handles, [ir.Constant(self.i64, 0), pidx])
        h_val = builder.load(h_ptr)
        # Push to free list
        old_free_head = builder.load(self.gc_handle_free_list)
        table2 = builder.load(self.gc_handle_table)
        slot_ptr2 = builder.gep(table2, [h_val])
        old_head_as_ptr = builder.inttoptr(old_free_head, self.i8_ptr)
        builder.store(old_head_as_ptr, slot_ptr2)
        builder.store(h_val, self.gc_handle_free_list)
        # Increment index
        new_pidx = builder.add(pidx, ir.Constant(self.i64, 1))
        builder.store(new_pidx, push_idx)
        builder.branch(push_back_loop)

        builder.position_at_end(push_back_done)
        # Now set up pool with just the first handle (pool of size 1)
        # This is inefficient but correct - we'll refill often from free list
        pool_start_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 18)
        ], inbounds=True)
        builder.store(first_handle, pool_start_ptr)

        pool_next_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 19)
        ], inbounds=True)
        builder.store(first_handle, pool_next_ptr)

        pool_end_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 20)
        ], inbounds=True)
        end_h = builder.add(first_handle, ir.Constant(self.i64, 1))
        builder.store(end_h, pool_end_ptr)

        # Unlock and return
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])
        builder.branch(done)

        # ============================================================
        # Bump allocate a contiguous batch of HANDLE_POOL_SIZE handles
        # (Only used when free list is empty)
        # ============================================================
        builder.position_at_end(use_bump)
        next_handle_val = builder.load(self.gc_next_handle)
        table_size = builder.load(self.gc_handle_table_size)

        # Calculate end of batch
        batch_end = builder.add(next_handle_val, pool_size)

        # Check if we need to grow the table
        need_grow_cond = builder.icmp_unsigned(">", batch_end, table_size)
        builder.cbranch(need_grow_cond, need_grow, do_bump)

        # Grow table and retry
        builder.position_at_end(need_grow)
        builder.call(self.gc_handle_table_grow, [])
        builder.branch(use_bump)

        # Do bump allocation
        builder.position_at_end(do_bump)
        start_handle = builder.load(self.gc_next_handle)
        end_handle = builder.add(start_handle, pool_size)

        # Update gc_next_handle
        builder.store(end_handle, self.gc_next_handle)

        builder.branch(finish)

        # ============================================================
        # Update ThreadEntry with new pool
        # ============================================================
        builder.position_at_end(finish)

        # Update handle_pool_start (field 18)
        pool_start_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 18)
        ], inbounds=True)
        builder.store(start_handle, pool_start_ptr)

        # Update handle_pool_next (field 19)
        pool_next_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 19)
        ], inbounds=True)
        builder.store(start_handle, pool_next_ptr)

        # Update handle_pool_end (field 20)
        pool_end_ptr = builder.gep(thread_entry, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 20)
        ], inbounds=True)
        builder.store(end_handle, pool_end_ptr)

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()
