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
    HEAP_SIZE = 256 * 1024 * 1024  # 256MB initial heap segment
    MAX_HEAP_SIZE = 8 * 1024 * 1024 * 1024  # 8GB maximum total heap
    GC_TRIGGER_INTERVAL = 100000   # Trigger GC every 100k allocations
    HEADER_SIZE = 24         # 8-byte size + 4-byte type_id + 4-byte flags + 8-byte finalizer
    MIN_BLOCK_SIZE = 32      # Minimum block: header(24) + alignment padding
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
    TYPE_ARRAY = 8
    TYPE_LIST_TAIL = 9       # List tail buffer (element data)
    TYPE_PV_NODE = 10        # Persistent vector tree node
    TYPE_STRING_DATA = 11    # String character data buffer
    TYPE_CHANNEL_BUFFER = 12 # Channel data buffer
    TYPE_ARRAY_DATA = 13     # Array element data buffer
    TYPE_FIRST_USER = 14     # First ID for user-defined types

    # Heap context types
    CONTEXT_MAIN = 0         # Long-lived objects, precise GC with roots
    CONTEXT_NURSERY = 1      # Short-lived temps, bulk-free on scope exit
    CONTEXT_LARGE = 2        # Objects > 1MB, separate tracking
    CONTEXT_IMMORTAL = 3     # Never freed (string literals, etc.)

    # Context stack configuration
    MAX_CONTEXT_DEPTH = 16   # Maximum nested context depth

    # Root registry configuration
    MAX_ROOTS = 1024         # Maximum number of registered roots

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
        self.heap_context_type = None

        # GC global variables (set in _create_globals)
        self.heap_start = None
        self.heap_end = None
        self.heap_size_global = None
        self.free_list_head = None
        self.stack_bottom = None
        self.type_table = None

        # Context stack globals (set in _create_globals)
        self.context_stack = None        # HeapContext*[16] - max nested contexts
        self.context_stack_top = None    # i32 - current depth
        self.main_context = None         # HeapContext* - the main heap context

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
        self.gc_expand_heap = None

        # Context management functions
        self.gc_create_context = None
        self.gc_destroy_context = None
        self.gc_push_context = None
        self.gc_pop_context = None
        self.gc_alloc_in_context = None

        # Finalizer support
        self.gc_set_finalizer = None

        # pthread functions
        self.pthread_create = None
        self.pthread_join = None
        self.pthread_mutex_init = None
        self.pthread_mutex_lock = None
        self.pthread_mutex_unlock = None
        self.pthread_mutex_destroy = None
        self.pthread_cond_init = None
        self.pthread_cond_wait = None
        self.pthread_cond_signal = None
        self.pthread_cond_broadcast = None
        self.pthread_cond_destroy = None

        # GC thread globals
        self.gc_thread = None           # pthread_t for GC thread
        self.gc_running = None          # i32: 0=stopped, 1=running
        self.gc_phase = None            # i32: 0=idle, 1=mark, 2=sweep
        self.gc_request = None          # i32: request collection flag
        self.heap_mutex = None          # pthread_mutex_t for heap protection
        self.gc_cond = None             # pthread_cond_t for signaling GC thread

        # GC thread functions
        self.gc_thread_main = None
        self.gc_shutdown = None

        # Root registry globals
        self.gc_roots = None            # i8**[MAX_ROOTS] - array of root pointer slots
        self.gc_root_count = None       # i32 - number of registered roots
        self.gc_roots_mutex = None      # pthread_mutex_t for root registry protection

        # Root registry functions
        self.gc_register_root = None    # gc_register_root(ptr**) -> i32 (returns handle)
        self.gc_unregister_root = None  # gc_unregister_root(handle) -> void

        # Write barrier function
        self.gc_write_barrier = None    # gc_write_barrier(old_ptr: i8*) -> void

        # GC phase constants
        self.GC_PHASE_IDLE = 0
        self.GC_PHASE_MARK = 1
        self.GC_PHASE_SWEEP = 2

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
        self._implement_gc_expand_heap()
        self._implement_gc_alloc()
        self._implement_gc_mark_object()
        self._implement_gc_scan_stack()
        self._implement_gc_sweep()
        self._implement_gc_collect()
        # Context management functions
        self._implement_gc_create_context()
        self._implement_gc_destroy_context()
        self._implement_gc_push_context()
        self._implement_gc_pop_context()
        self._implement_gc_alloc_in_context()
        # Finalizer support
        self._implement_gc_set_finalizer()
        # Root registry functions
        self._implement_gc_register_root()
        self._implement_gc_unregister_root()
        # GC thread functions
        self._implement_gc_thread_main()
        self._implement_gc_shutdown()
        # Write barrier for concurrent mark phase
        self._implement_gc_write_barrier()

    def _create_types(self):
        """Create GC-related LLVM types"""
        # Object header: { i64 size, i32 type_id, i32 flags, i8* finalizer }
        # Size is preserved from allocation so sweep can traverse the heap.
        # Placed immediately before the user data (at negative offset)
        self.header_type = ir.LiteralStructType([
            self.i64,      # block size (including header) - preserved for sweep
            self.i32,      # type_id (index into type table)
            self.i32,      # flags (bit 0 = mark, bit 1 = pinned, bit 2 = has_finalizer)
            self.i8_ptr,   # finalizer function pointer (null if none)
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

        # Heap context: { i8* heap_start, i8* heap_end, i8* free_list_head,
        #                 i64 heap_size, i32 context_type }
        self.heap_context_type = ir.LiteralStructType([
            self.i8_ptr,    # heap_start - start of this context's heap region
            self.i8_ptr,    # heap_end - end of this context's heap region
            self.i8_ptr,    # free_list_head - this context's free list
            self.i64,       # heap_size - size of this context's heap
            self.i32,       # context_type (MAIN=0, NURSERY=1, LARGE=2, IMMORTAL=3)
        ])

        # pthread types - sizes vary by platform, use opaque arrays
        # pthread_t is typically 8 bytes on 64-bit systems
        self.pthread_t_type = self.i64

        # pthread_mutex_t is typically 40-64 bytes, use 64 for safety
        # On macOS: 64 bytes, on Linux: 40 bytes
        self.pthread_mutex_type = ir.ArrayType(self.i8, 64)

        # pthread_cond_t is typically 48 bytes
        self.pthread_cond_type = ir.ArrayType(self.i8, 48)

        # pthread_attr_t - used as null pointer typically
        self.pthread_attr_ptr_type = self.i8_ptr

    def _create_globals(self):
        """Create GC global variables"""
        # Heap region bounds (min/max across all segments for conservative scanning)
        self.heap_start = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_heap_start")
        self.heap_start.initializer = ir.Constant(self.i8_ptr, None)
        self.heap_start.linkage = 'internal'

        self.heap_end = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_heap_end")
        self.heap_end.initializer = ir.Constant(self.i8_ptr, None)
        self.heap_end.linkage = 'internal'

        # Current heap size (total across all segments)
        self.heap_size_global = ir.GlobalVariable(self.module, self.i64, name="gc_heap_size")
        self.heap_size_global.initializer = ir.Constant(self.i64, 0)
        self.heap_size_global.linkage = 'internal'

        # Maximum heap size limit
        self.max_heap_size = ir.GlobalVariable(self.module, self.i64, name="gc_max_heap_size")
        self.max_heap_size.initializer = ir.Constant(self.i64, self.MAX_HEAP_SIZE)
        self.max_heap_size.linkage = 'internal'

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

        # Context stack for nested heap contexts (e.g., nursery inside loop)
        context_stack_type = ir.ArrayType(self.heap_context_type.as_pointer(), self.MAX_CONTEXT_DEPTH)
        self.context_stack = ir.GlobalVariable(self.module, context_stack_type, name="gc_context_stack")
        self.context_stack.initializer = ir.Constant(context_stack_type, [ir.Constant(self.heap_context_type.as_pointer(), None)] * self.MAX_CONTEXT_DEPTH)
        self.context_stack.linkage = 'internal'

        # Current depth of context stack (0 = only main context)
        self.context_stack_top = ir.GlobalVariable(self.module, self.i32, name="gc_context_stack_top")
        self.context_stack_top.initializer = ir.Constant(self.i32, 0)
        self.context_stack_top.linkage = 'internal'

        # Main context pointer (initialized in gc_init)
        self.main_context = ir.GlobalVariable(self.module, self.heap_context_type.as_pointer(), name="gc_main_context")
        self.main_context.initializer = ir.Constant(self.heap_context_type.as_pointer(), None)
        self.main_context.linkage = 'internal'

        # GC thread handle
        self.gc_thread = ir.GlobalVariable(self.module, self.pthread_t_type, name="gc_thread_handle")
        self.gc_thread.initializer = ir.Constant(self.pthread_t_type, 0)
        self.gc_thread.linkage = 'internal'

        # GC running flag: 0=stopped, 1=running
        self.gc_running = ir.GlobalVariable(self.module, self.i32, name="gc_running")
        self.gc_running.initializer = ir.Constant(self.i32, 0)
        self.gc_running.linkage = 'internal'

        # GC phase: 0=idle, 1=mark, 2=sweep
        self.gc_phase = ir.GlobalVariable(self.module, self.i32, name="gc_phase")
        self.gc_phase.initializer = ir.Constant(self.i32, 0)
        self.gc_phase.linkage = 'internal'

        # GC request flag: set to 1 to request collection
        self.gc_request = ir.GlobalVariable(self.module, self.i32, name="gc_request")
        self.gc_request.initializer = ir.Constant(self.i32, 0)
        self.gc_request.linkage = 'internal'

        # Mutex for protecting heap during concurrent access
        self.heap_mutex = ir.GlobalVariable(self.module, self.pthread_mutex_type, name="gc_heap_mutex")
        self.heap_mutex.initializer = ir.Constant(self.pthread_mutex_type, None)
        self.heap_mutex.linkage = 'internal'

        # Condition variable for signaling GC thread
        self.gc_cond = ir.GlobalVariable(self.module, self.pthread_cond_type, name="gc_cond")
        self.gc_cond.initializer = ir.Constant(self.pthread_cond_type, None)
        self.gc_cond.linkage = 'internal'

        # Root registry - array of pointer-to-pointers (each entry points to a root variable)
        # When a root is registered, we store the address of the pointer variable itself,
        # so that when the pointer is updated, GC sees the new value automatically.
        # Each slot holds i8** (address of an i8* root variable)
        root_slot_type = self.i8_ptr.as_pointer()  # i8**
        roots_array_type = ir.ArrayType(root_slot_type, self.MAX_ROOTS)
        self.gc_roots = ir.GlobalVariable(self.module, roots_array_type, name="gc_roots")
        self.gc_roots.initializer = ir.Constant(roots_array_type,
            [ir.Constant(root_slot_type, None)] * self.MAX_ROOTS)
        self.gc_roots.linkage = 'internal'

        # Number of currently registered roots
        self.gc_root_count = ir.GlobalVariable(self.module, self.i32, name="gc_root_count")
        self.gc_root_count.initializer = ir.Constant(self.i32, 0)
        self.gc_root_count.linkage = 'internal'

        # Mutex for protecting root registry during concurrent access
        self.gc_roots_mutex = ir.GlobalVariable(self.module, self.pthread_mutex_type, name="gc_roots_mutex")
        self.gc_roots_mutex.initializer = ir.Constant(self.pthread_mutex_type, None)
        self.gc_roots_mutex.linkage = 'internal'

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

        # gc_expand_heap(min_size: i64) -> i1 (returns true if expansion succeeded)
        gc_expand_ty = ir.FunctionType(self.i1, [self.i64])
        self.gc_expand_heap = ir.Function(self.module, gc_expand_ty, name="coex_gc_expand_heap")

        # gc_create_context(size: i64, type: i32) -> HeapContext*
        gc_create_ctx_ty = ir.FunctionType(self.heap_context_type.as_pointer(), [self.i64, self.i32])
        self.gc_create_context = ir.Function(self.module, gc_create_ctx_ty, name="coex_gc_create_context")

        # gc_destroy_context(ctx: HeapContext*) -> void
        gc_destroy_ctx_ty = ir.FunctionType(self.void, [self.heap_context_type.as_pointer()])
        self.gc_destroy_context = ir.Function(self.module, gc_destroy_ctx_ty, name="coex_gc_destroy_context")

        # gc_push_context(ctx: HeapContext*) -> void
        gc_push_ctx_ty = ir.FunctionType(self.void, [self.heap_context_type.as_pointer()])
        self.gc_push_context = ir.Function(self.module, gc_push_ctx_ty, name="coex_gc_push_context")

        # gc_pop_context() -> HeapContext* (returns the popped context)
        gc_pop_ctx_ty = ir.FunctionType(self.heap_context_type.as_pointer(), [])
        self.gc_pop_context = ir.Function(self.module, gc_pop_ctx_ty, name="coex_gc_pop_context")

        # gc_alloc_in_context(ctx: HeapContext*, size: i64, type_id: i32) -> i8*
        gc_alloc_ctx_ty = ir.FunctionType(self.i8_ptr, [self.heap_context_type.as_pointer(), self.i64, self.i32])
        self.gc_alloc_in_context = ir.Function(self.module, gc_alloc_ctx_ty, name="coex_gc_alloc_in_context")

        # gc_set_finalizer(obj: i8*, finalizer: i8*) -> void
        # Finalizer type: void (*)(i8*) - called with user pointer when object is swept
        gc_set_finalizer_ty = ir.FunctionType(self.void, [self.i8_ptr, self.i8_ptr])
        self.gc_set_finalizer = ir.Function(self.module, gc_set_finalizer_ty, name="coex_gc_set_finalizer")

        # gc_register_root(root_ptr: i8**) -> i32
        # Register a root pointer for GC tracing. Returns a handle for unregistration.
        # root_ptr is the address of the pointer variable (not the object pointer itself)
        gc_register_root_ty = ir.FunctionType(self.i32, [self.i8_ptr.as_pointer()])
        self.gc_register_root = ir.Function(self.module, gc_register_root_ty, name="coex_gc_register_root")

        # gc_unregister_root(handle: i32) -> void
        # Unregister a previously registered root by its handle
        gc_unregister_root_ty = ir.FunctionType(self.void, [self.i32])
        self.gc_unregister_root = ir.Function(self.module, gc_unregister_root_ty, name="coex_gc_unregister_root")

        # ========== pthread declarations ==========
        # pthread_create(thread*, attr*, start_routine, arg) -> int
        # start_routine: i8* (*)(i8*)
        thread_fn_type = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
        pthread_create_ty = ir.FunctionType(self.i32, [
            self.pthread_t_type.as_pointer(),  # pthread_t*
            self.pthread_attr_ptr_type,         # const pthread_attr_t*
            thread_fn_type.as_pointer(),        # void* (*)(void*)
            self.i8_ptr                         # void* arg
        ])
        self.pthread_create = ir.Function(self.module, pthread_create_ty, name="pthread_create")

        # pthread_join(thread, retval*) -> int
        pthread_join_ty = ir.FunctionType(self.i32, [
            self.pthread_t_type,                # pthread_t
            self.i8_ptr.as_pointer()            # void** retval
        ])
        self.pthread_join = ir.Function(self.module, pthread_join_ty, name="pthread_join")

        # pthread_mutex_init(mutex*, attr*) -> int
        pthread_mutex_init_ty = ir.FunctionType(self.i32, [
            self.pthread_mutex_type.as_pointer(),
            self.i8_ptr  # const pthread_mutexattr_t*
        ])
        self.pthread_mutex_init = ir.Function(self.module, pthread_mutex_init_ty, name="pthread_mutex_init")

        # pthread_mutex_lock(mutex*) -> int
        pthread_mutex_lock_ty = ir.FunctionType(self.i32, [self.pthread_mutex_type.as_pointer()])
        self.pthread_mutex_lock = ir.Function(self.module, pthread_mutex_lock_ty, name="pthread_mutex_lock")

        # pthread_mutex_unlock(mutex*) -> int
        pthread_mutex_unlock_ty = ir.FunctionType(self.i32, [self.pthread_mutex_type.as_pointer()])
        self.pthread_mutex_unlock = ir.Function(self.module, pthread_mutex_unlock_ty, name="pthread_mutex_unlock")

        # pthread_mutex_destroy(mutex*) -> int
        pthread_mutex_destroy_ty = ir.FunctionType(self.i32, [self.pthread_mutex_type.as_pointer()])
        self.pthread_mutex_destroy = ir.Function(self.module, pthread_mutex_destroy_ty, name="pthread_mutex_destroy")

        # pthread_cond_init(cond*, attr*) -> int
        pthread_cond_init_ty = ir.FunctionType(self.i32, [
            self.pthread_cond_type.as_pointer(),
            self.i8_ptr  # const pthread_condattr_t*
        ])
        self.pthread_cond_init = ir.Function(self.module, pthread_cond_init_ty, name="pthread_cond_init")

        # pthread_cond_wait(cond*, mutex*) -> int
        pthread_cond_wait_ty = ir.FunctionType(self.i32, [
            self.pthread_cond_type.as_pointer(),
            self.pthread_mutex_type.as_pointer()
        ])
        self.pthread_cond_wait = ir.Function(self.module, pthread_cond_wait_ty, name="pthread_cond_wait")

        # pthread_cond_signal(cond*) -> int
        pthread_cond_signal_ty = ir.FunctionType(self.i32, [self.pthread_cond_type.as_pointer()])
        self.pthread_cond_signal = ir.Function(self.module, pthread_cond_signal_ty, name="pthread_cond_signal")

        # pthread_cond_broadcast(cond*) -> int
        pthread_cond_broadcast_ty = ir.FunctionType(self.i32, [self.pthread_cond_type.as_pointer()])
        self.pthread_cond_broadcast = ir.Function(self.module, pthread_cond_broadcast_ty, name="pthread_cond_broadcast")

        # pthread_cond_destroy(cond*) -> int
        pthread_cond_destroy_ty = ir.FunctionType(self.i32, [self.pthread_cond_type.as_pointer()])
        self.pthread_cond_destroy = ir.Function(self.module, pthread_cond_destroy_ty, name="pthread_cond_destroy")

        # ========== GC thread functions ==========
        # gc_thread_main(arg: i8*) -> i8* (pthread thread entry)
        gc_thread_main_ty = ir.FunctionType(self.i8_ptr, [self.i8_ptr])
        self.gc_thread_main = ir.Function(self.module, gc_thread_main_ty, name="coex_gc_thread_main")

        # gc_shutdown() -> void
        gc_shutdown_ty = ir.FunctionType(self.void, [])
        self.gc_shutdown = ir.Function(self.module, gc_shutdown_ty, name="coex_gc_shutdown")

        # gc_write_barrier(old_ptr: i8*) -> void
        # Called before overwriting a pointer field during MARK phase
        # Marks the old value to prevent premature collection
        gc_write_barrier_ty = ir.FunctionType(self.void, [self.i8_ptr])
        self.gc_write_barrier = ir.Function(self.module, gc_write_barrier_ty, name="coex_gc_write_barrier")

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

        # Type 8: Array - { i64 len, i64 cap, i64 elem_size, i8* data }
        # data field at offset 24 is a reference (same layout as List)
        self.type_info[self.TYPE_ARRAY] = {'size': 32, 'ref_offsets': [24]}
        self.type_descriptors['Array'] = self.TYPE_ARRAY

        # Type 9: List tail buffer - raw element data, no references
        # (element references are handled by the List struct itself)
        self.type_info[self.TYPE_LIST_TAIL] = {'size': 0, 'ref_offsets': []}
        self.type_descriptors['ListTail'] = self.TYPE_LIST_TAIL

        # Type 10: Persistent Vector node - { i64 refcount, i8*[32] children }
        # Children are references (either to other nodes or leaf data)
        self.type_info[self.TYPE_PV_NODE] = {'size': 264, 'ref_offsets': []}
        self.type_descriptors['PVNode'] = self.TYPE_PV_NODE

        # Type 11: String data buffer - raw character data, no references
        self.type_info[self.TYPE_STRING_DATA] = {'size': 0, 'ref_offsets': []}
        self.type_descriptors['StringData'] = self.TYPE_STRING_DATA

        # Type 12: Channel buffer - raw element data, no references
        self.type_info[self.TYPE_CHANNEL_BUFFER] = {'size': 0, 'ref_offsets': []}
        self.type_descriptors['ChannelBuffer'] = self.TYPE_CHANNEL_BUFFER

        # Type 13: Array data buffer - raw element data, no references
        self.type_info[self.TYPE_ARRAY_DATA] = {'size': 0, 'ref_offsets': []}
        self.type_descriptors['ArrayData'] = self.TYPE_ARRAY_DATA

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

        # Initialize pthread mutex for heap protection
        mutex_ptr = builder.bitcast(self.heap_mutex, self.pthread_mutex_type.as_pointer())
        builder.call(self.pthread_mutex_init, [mutex_ptr, ir.Constant(self.i8_ptr, None)])

        # Initialize pthread condition variable for GC signaling
        cond_ptr = builder.bitcast(self.gc_cond, self.pthread_cond_type.as_pointer())
        builder.call(self.pthread_cond_init, [cond_ptr, ir.Constant(self.i8_ptr, None)])

        # Initialize roots mutex for root registry protection
        roots_mutex_ptr = builder.bitcast(self.gc_roots_mutex, self.pthread_mutex_type.as_pointer())
        builder.call(self.pthread_mutex_init, [roots_mutex_ptr, ir.Constant(self.i8_ptr, None)])

        # Initialize root count to 0
        builder.store(ir.Constant(self.i32, 0), self.gc_root_count)

        # Set GC running flag
        builder.store(ir.Constant(self.i32, 1), self.gc_running)

        # Set GC phase to idle
        builder.store(ir.Constant(self.i32, self.GC_PHASE_IDLE), self.gc_phase)

        # Clear GC request flag
        builder.store(ir.Constant(self.i32, 0), self.gc_request)

        # Start GC background thread
        # pthread_create(&gc_thread, NULL, gc_thread_main, NULL)
        thread_ptr = builder.bitcast(self.gc_thread, self.pthread_t_type.as_pointer())
        builder.call(self.pthread_create, [
            thread_ptr,
            ir.Constant(self.pthread_attr_ptr_type, None),
            self.gc_thread_main,
            ir.Constant(self.i8_ptr, None)
        ])

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

    def _implement_gc_expand_heap(self):
        """Expand heap by allocating a new segment when current heap is exhausted"""
        func = self.gc_expand_heap
        func.args[0].name = "min_size"

        entry = func.append_basic_block("entry")
        check_limit = func.append_basic_block("check_limit")
        do_expand = func.append_basic_block("do_expand")
        alloc_success = func.append_basic_block("alloc_success")
        update_bounds = func.append_basic_block("update_bounds")
        check_start = func.append_basic_block("check_start")
        update_start = func.append_basic_block("update_start")
        check_end = func.append_basic_block("check_end")
        update_end = func.append_basic_block("update_end")
        add_to_free = func.append_basic_block("add_to_free")
        fail = func.append_basic_block("fail")

        builder = ir.IRBuilder(entry)
        min_size = func.args[0]

        # Calculate segment size: max(HEAP_SIZE, min_size * 2)
        default_segment = ir.Constant(self.i64, self.HEAP_SIZE)
        double_min = builder.mul(min_size, ir.Constant(self.i64, 2))
        use_default = builder.icmp_unsigned(">=", default_segment, double_min)
        segment_size = builder.select(use_default, default_segment, double_min)

        # Store segment_size for later use
        segment_size_alloca = builder.alloca(self.i64, name="segment_size")
        builder.store(segment_size, segment_size_alloca)

        builder.branch(check_limit)

        # Check if we've exceeded the maximum heap size
        builder.position_at_end(check_limit)
        current_size = builder.load(self.heap_size_global)
        max_size = builder.load(self.max_heap_size)
        new_total = builder.add(current_size, segment_size)
        within_limit = builder.icmp_unsigned("<=", new_total, max_size)
        builder.cbranch(within_limit, do_expand, fail)

        # Allocate new segment using system malloc
        builder.position_at_end(do_expand)
        seg_size_val = builder.load(segment_size_alloca)
        new_segment = builder.call(self.codegen.malloc, [seg_size_val])

        # Check if malloc succeeded
        is_null = builder.icmp_unsigned("==", new_segment, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, fail, alloc_success)

        # Allocation succeeded
        builder.position_at_end(alloc_success)
        # Update total heap size
        updated_size = builder.add(current_size, seg_size_val)
        builder.store(updated_size, self.heap_size_global)

        builder.branch(update_bounds)

        # Update heap bounds (min/max addresses)
        builder.position_at_end(update_bounds)
        current_start = builder.load(self.heap_start)
        current_end = builder.load(self.heap_end)

        # Check if heap_start needs updating (new segment could be at lower address)
        builder.branch(check_start)

        builder.position_at_end(check_start)
        # If heap_start is null (first expansion after init), or new_segment < heap_start
        start_is_null = builder.icmp_unsigned("==", current_start, ir.Constant(self.i8_ptr, None))
        new_is_lower = builder.icmp_unsigned("<", new_segment, current_start)
        should_update_start = builder.or_(start_is_null, new_is_lower)
        builder.cbranch(should_update_start, update_start, check_end)

        builder.position_at_end(update_start)
        builder.store(new_segment, self.heap_start)
        builder.branch(check_end)

        # Check if heap_end needs updating
        builder.position_at_end(check_end)
        # Calculate new segment end
        new_segment_int = builder.ptrtoint(new_segment, self.i64)
        seg_size_val2 = builder.load(segment_size_alloca)
        new_segment_end_int = builder.add(new_segment_int, seg_size_val2)
        new_segment_end = builder.inttoptr(new_segment_end_int, self.i8_ptr)

        # If heap_end is null or new_segment_end > heap_end
        end_is_null = builder.icmp_unsigned("==", current_end, ir.Constant(self.i8_ptr, None))
        new_is_higher = builder.icmp_unsigned(">", new_segment_end, current_end)
        should_update_end = builder.or_(end_is_null, new_is_higher)
        builder.cbranch(should_update_end, update_end, add_to_free)

        builder.position_at_end(update_end)
        builder.store(new_segment_end, self.heap_end)
        builder.branch(add_to_free)

        # Add new segment to free list
        builder.position_at_end(add_to_free)
        seg_size_val3 = builder.load(segment_size_alloca)
        builder.call(self.gc_add_to_free_list, [new_segment, seg_size_val3])

        # Return success
        builder.ret(ir.Constant(self.i1, 1))

        # Expansion failed (either limit exceeded or malloc failed)
        builder.position_at_end(fail)
        builder.ret(ir.Constant(self.i1, 0))

    def _implement_gc_alloc(self):
        """Allocate memory with GC header

        If there's an active context on the stack (context_stack_top > 0),
        allocate from that context. Otherwise, allocate from the main heap.
        """
        func = self.gc_alloc
        func.args[0].name = "user_size"
        func.args[1].name = "type_id"

        entry = func.append_basic_block("entry")
        check_context = func.append_basic_block("check_context")
        use_context = func.append_basic_block("use_context")
        use_main_heap = func.append_basic_block("use_main_heap")
        try_alloc = func.append_basic_block("try_alloc")
        alloc_success = func.append_basic_block("alloc_success")
        do_gc = func.append_basic_block("do_gc")
        retry_alloc = func.append_basic_block("retry_alloc")
        retry_success = func.append_basic_block("retry_success")
        try_expand = func.append_basic_block("try_expand")
        expand_retry = func.append_basic_block("expand_retry")
        expand_success = func.append_basic_block("expand_success")
        oom = func.append_basic_block("oom")

        builder = ir.IRBuilder(entry)

        user_size = func.args[0]
        type_id = func.args[1]

        # Check if there's an active context on the stack
        builder.branch(check_context)

        builder.position_at_end(check_context)
        stack_top = builder.load(self.context_stack_top)
        has_context = builder.icmp_signed(">", stack_top, ir.Constant(self.i32, 0))
        builder.cbranch(has_context, use_context, use_main_heap)

        # Allocate from the active context
        builder.position_at_end(use_context)
        # Get context at stack_top
        ctx_slot_ptr = builder.gep(self.context_stack, [
            ir.Constant(self.i32, 0),
            stack_top
        ], inbounds=True)
        active_ctx = builder.load(ctx_slot_ptr)

        # Call gc_alloc_in_context (returns user pointer directly)
        ctx_result = builder.call(self.gc_alloc_in_context, [active_ctx, user_size, type_id])

        # Check if context allocation succeeded
        ctx_null = builder.icmp_unsigned("==", ctx_result, ir.Constant(self.i8_ptr, None))
        # If context allocation failed, fall back to main heap
        ctx_success = func.append_basic_block("ctx_success")
        builder.cbranch(ctx_null, use_main_heap, ctx_success)

        # Context allocation succeeded - return the result directly
        builder.position_at_end(ctx_success)
        # Increment allocation counter for context allocations too
        ctx_count = builder.load(self.alloc_count)
        ctx_new_count = builder.add(ctx_count, ir.Constant(self.i64, 1))
        builder.store(ctx_new_count, self.alloc_count)
        builder.ret(ctx_result)

        # Main heap allocation path
        builder.position_at_end(use_main_heap)

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

        # Proactive GC: check if we should collect before allocation
        proactive_gc_block = func.append_basic_block("proactive_gc")

        count_check = builder.load(self.alloc_count)
        trigger_interval = ir.Constant(self.i64, self.GC_TRIGGER_INTERVAL)
        should_gc = builder.icmp_unsigned(">=", count_check, trigger_interval)
        builder.cbranch(should_gc, proactive_gc_block, try_alloc)

        # Proactive GC: trigger collection and reset counter
        builder.position_at_end(proactive_gc_block)
        builder.call(self.gc_collect, [])
        builder.store(ir.Constant(self.i64, 0), self.alloc_count)
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

        # Store flags at offset 2 (set mark bit if in MARK phase for snapshot-at-beginning)
        # Objects allocated during MARK phase are born "marked" so they survive this collection
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_phase = builder.load(self.gc_phase)
        is_mark_phase = builder.icmp_unsigned("==", current_phase, ir.Constant(self.i32, self.GC_PHASE_MARK))
        initial_flags = builder.select(is_mark_phase,
            ir.Constant(self.i32, self.FLAG_MARK_BIT),
            ir.Constant(self.i32, 0))
        builder.store(initial_flags, flags_ptr)

        # Store finalizer (null) at offset 3
        finalizer_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), finalizer_ptr)

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
        builder.cbranch(is_null2, try_expand, retry_success)

        # Retry succeeded
        builder.position_at_end(retry_success)
        # Note: size field at offset 0 is already set by gc_find_free_block
        header2 = builder.bitcast(block2, self.header_type.as_pointer())

        type_id_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr2)

        # Set mark bit if in MARK phase for snapshot-at-beginning
        flags_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_phase2 = builder.load(self.gc_phase)
        is_mark_phase2 = builder.icmp_unsigned("==", current_phase2, ir.Constant(self.i32, self.GC_PHASE_MARK))
        initial_flags2 = builder.select(is_mark_phase2,
            ir.Constant(self.i32, self.FLAG_MARK_BIT),
            ir.Constant(self.i32, 0))
        builder.store(initial_flags2, flags_ptr2)

        finalizer_ptr2 = builder.gep(header2, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), finalizer_ptr2)

        block2_int = builder.ptrtoint(block2, self.i64)
        user_ptr2_int = builder.add(block2_int, header_size)
        user_ptr2 = builder.inttoptr(user_ptr2_int, self.i8_ptr)

        count2 = builder.load(self.alloc_count)
        new_count2 = builder.add(count2, ir.Constant(self.i64, 1))
        builder.store(new_count2, self.alloc_count)

        builder.ret(user_ptr2)

        # Try heap expansion - GC didn't free enough memory
        builder.position_at_end(try_expand)
        final_size_val3 = builder.load(final_size_alloca)
        expand_result = builder.call(self.gc_expand_heap, [final_size_val3])

        # Check if expansion succeeded
        expand_ok = builder.icmp_unsigned("==", expand_result, ir.Constant(self.i1, 1))
        builder.cbranch(expand_ok, expand_retry, oom)

        # Retry allocation after heap expansion
        builder.position_at_end(expand_retry)
        final_size_val4 = builder.load(final_size_alloca)
        block3 = builder.call(self.gc_find_free_block, [final_size_val4])

        is_null3 = builder.icmp_unsigned("==", block3, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null3, oom, expand_success)

        # Expansion retry succeeded
        builder.position_at_end(expand_success)
        header3 = builder.bitcast(block3, self.header_type.as_pointer())

        type_id_ptr3 = builder.gep(header3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr3)

        # Set mark bit if in MARK phase for snapshot-at-beginning
        flags_ptr3 = builder.gep(header3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_phase3 = builder.load(self.gc_phase)
        is_mark_phase3 = builder.icmp_unsigned("==", current_phase3, ir.Constant(self.i32, self.GC_PHASE_MARK))
        initial_flags3 = builder.select(is_mark_phase3,
            ir.Constant(self.i32, self.FLAG_MARK_BIT),
            ir.Constant(self.i32, 0))
        builder.store(initial_flags3, flags_ptr3)

        finalizer_ptr3 = builder.gep(header3, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), finalizer_ptr3)

        block3_int = builder.ptrtoint(block3, self.i64)
        user_ptr3_int = builder.add(block3_int, header_size)
        user_ptr3 = builder.inttoptr(user_ptr3_int, self.i8_ptr)

        count3 = builder.load(self.alloc_count)
        new_count3 = builder.add(count3, ir.Constant(self.i64, 1))
        builder.store(new_count3, self.alloc_count)

        builder.ret(user_ptr3)

        # Out of memory - heap expansion failed or reached limit
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

        # After stack scan completes, scan registered roots
        builder.position_at_end(done)

        # Create blocks for root scanning loop
        roots_loop_start = func.append_basic_block("roots_loop_start")
        roots_check = func.append_basic_block("roots_check")
        roots_mark = func.append_basic_block("roots_mark")
        roots_next = func.append_basic_block("roots_next")
        roots_done = func.append_basic_block("roots_done")

        builder.branch(roots_loop_start)

        # Initialize root index
        builder.position_at_end(roots_loop_start)
        root_idx = builder.alloca(self.i32, name="root_idx")
        builder.store(ir.Constant(self.i32, 0), root_idx)
        builder.branch(roots_check)

        # Check if we've processed all roots
        builder.position_at_end(roots_check)
        idx = builder.load(root_idx)
        root_count = builder.load(self.gc_root_count)
        at_end_roots = builder.icmp_unsigned(">=", idx, root_count)
        builder.cbranch(at_end_roots, roots_done, roots_mark)

        # Mark the object pointed to by this root
        builder.position_at_end(roots_mark)
        # Get gc_roots[idx]
        idx_64 = builder.zext(idx, self.i64)
        root_slot_ptr = builder.gep(self.gc_roots, [
            ir.Constant(self.i64, 0),
            idx_64
        ], inbounds=True)
        root_slot = builder.load(root_slot_ptr)  # This is i8** (pointer to root variable)

        # Check if slot is non-null (could be unregistered)
        root_slot_type = self.i8_ptr.as_pointer()
        root_slot_null = ir.Constant(root_slot_type, None)
        slot_is_null = builder.icmp_unsigned("==", root_slot, root_slot_null)
        root_valid = func.append_basic_block("root_valid")
        builder.cbranch(slot_is_null, roots_next, root_valid)

        builder.position_at_end(root_valid)
        # Load the actual pointer from the root variable
        obj_ptr = builder.load(root_slot)  # This is i8* (the actual heap pointer)

        # Check if the object pointer is non-null
        obj_is_null = builder.icmp_unsigned("==", obj_ptr, ir.Constant(self.i8_ptr, None))
        obj_valid = func.append_basic_block("obj_valid")
        builder.cbranch(obj_is_null, roots_next, obj_valid)

        builder.position_at_end(obj_valid)
        # Mark the object
        builder.call(self.gc_mark_object, [obj_ptr])
        builder.branch(roots_next)

        # Advance to next root
        builder.position_at_end(roots_next)
        curr_idx = builder.load(root_idx)
        next_idx = builder.add(curr_idx, ir.Constant(self.i32, 1))
        builder.store(next_idx, root_idx)
        builder.branch(roots_check)

        builder.position_at_end(roots_done)
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

        # Block is unmarked - check for finalizer, then add to free list
        builder.position_at_end(block_unmarked)

        # Check if FLAG_FINALIZER bit is set
        has_finalizer_bit = builder.and_(flags, ir.Constant(self.i32, self.FLAG_FINALIZER))
        has_finalizer = builder.icmp_unsigned("!=", has_finalizer_bit, ir.Constant(self.i32, 0))

        # Branch to finalizer call or directly to free
        call_finalizer = func.append_basic_block("call_finalizer")
        add_to_free = func.append_basic_block("add_to_free")
        builder.cbranch(has_finalizer, call_finalizer, add_to_free)

        # Call finalizer if present
        builder.position_at_end(call_finalizer)

        # Load finalizer function pointer from header offset 3
        finalizer_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        finalizer_fn = builder.load(finalizer_ptr)

        # Check if finalizer is non-null (defensive, should always be non-null if FLAG_FINALIZER is set)
        finalizer_is_null = builder.icmp_unsigned("==", finalizer_fn, ir.Constant(self.i8_ptr, None))
        do_call = func.append_basic_block("do_call")
        builder.cbranch(finalizer_is_null, add_to_free, do_call)

        builder.position_at_end(do_call)

        # Calculate user pointer (header + HEADER_SIZE)
        block_int_for_finalize = builder.ptrtoint(curr_val, self.i64)
        user_ptr_int = builder.add(block_int_for_finalize, ir.Constant(self.i64, self.HEADER_SIZE))
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)

        # Create finalizer function type: void (*)(i8*)
        finalizer_fn_type = ir.FunctionType(self.void, [self.i8_ptr])
        finalizer_fn_ptr = builder.bitcast(finalizer_fn, finalizer_fn_type.as_pointer())

        # Call the finalizer with user pointer
        builder.call(finalizer_fn_ptr, [user_ptr])

        # Clear the finalizer pointer and FLAG_FINALIZER bit to prevent double-finalization
        builder.store(ir.Constant(self.i8_ptr, None), finalizer_ptr)
        cleared_finalizer_flags = builder.and_(flags, ir.Constant(self.i32, ~self.FLAG_FINALIZER & 0xFFFFFFFF))
        builder.store(cleared_finalizer_flags, flags_ptr)

        builder.branch(add_to_free)

        # Add to free list
        builder.position_at_end(add_to_free)
        builder.call(self.gc_add_to_free_list, [curr_val, block_size])
        builder.branch(next_block)

        # Move to next block
        builder.position_at_end(next_block)
        # Clear mark bit if it was set (for marked blocks continuing to next cycle)
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

    def _implement_gc_create_context(self):
        """Create a new heap context with given size and type

        gc_create_context(size: i64, context_type: i32) -> HeapContext*

        Allocates a new heap region and wraps it in a HeapContext struct.
        For NURSERY contexts, the heap is allocated via system malloc.
        Returns null if allocation fails.
        """
        func = self.gc_create_context
        func.args[0].name = "size"
        func.args[1].name = "context_type"

        entry = func.append_basic_block("entry")
        alloc_success = func.append_basic_block("alloc_success")
        heap_success = func.append_basic_block("heap_success")
        fail = func.append_basic_block("fail")

        builder = ir.IRBuilder(entry)
        size = func.args[0]
        context_type = func.args[1]

        # Allocate the HeapContext struct itself (small, fixed size)
        ctx_size = ir.Constant(self.i64, 40)  # 3 pointers + i64 + i32 = 8+8+8+8+4 = 36, aligned to 40
        ctx_mem = builder.call(self.codegen.malloc, [ctx_size])

        is_null = builder.icmp_unsigned("==", ctx_mem, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, fail, alloc_success)

        # Context struct allocated successfully
        builder.position_at_end(alloc_success)
        ctx_ptr = builder.bitcast(ctx_mem, self.heap_context_type.as_pointer())

        # Allocate the heap region for this context
        heap_mem = builder.call(self.codegen.malloc, [size])
        is_heap_null = builder.icmp_unsigned("==", heap_mem, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_heap_null, fail, heap_success)

        # Heap allocated successfully - initialize the context
        builder.position_at_end(heap_success)

        # Store heap_start (offset 0)
        heap_start_ptr = builder.gep(ctx_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(heap_mem, heap_start_ptr)

        # Calculate and store heap_end (offset 1)
        heap_start_int = builder.ptrtoint(heap_mem, self.i64)
        heap_end_int = builder.add(heap_start_int, size)
        heap_end = builder.inttoptr(heap_end_int, self.i8_ptr)
        heap_end_ptr = builder.gep(ctx_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(heap_end, heap_end_ptr)

        # Initialize the free list: entire heap is one free block
        free_node = builder.bitcast(heap_mem, self.free_node_type.as_pointer())

        # Set free block size
        free_size_ptr = builder.gep(free_node, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        builder.store(size, free_size_ptr)

        # Set next = null
        free_next_ptr = builder.gep(free_node, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 1)
        ], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), free_next_ptr)

        # Store free_list_head (offset 2)
        free_list_ptr = builder.gep(ctx_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 2)
        ], inbounds=True)
        builder.store(heap_mem, free_list_ptr)

        # Store heap_size (offset 3)
        heap_size_ptr = builder.gep(ctx_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 3)
        ], inbounds=True)
        builder.store(size, heap_size_ptr)

        # Store context_type (offset 4)
        type_ptr = builder.gep(ctx_ptr, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 4)
        ], inbounds=True)
        builder.store(context_type, type_ptr)

        builder.ret(ctx_ptr)

        # Failure path
        builder.position_at_end(fail)
        builder.ret(ir.Constant(self.heap_context_type.as_pointer(), None))

    def _implement_gc_destroy_context(self):
        """Destroy a heap context, freeing all its memory

        gc_destroy_context(ctx: HeapContext*) -> void

        For NURSERY contexts, this is a bulk-free operation - no scanning needed.
        Simply frees the heap region and the context struct itself.
        """
        func = self.gc_destroy_context
        func.args[0].name = "ctx"

        entry = func.append_basic_block("entry")
        do_free = func.append_basic_block("do_free")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        ctx = func.args[0]

        # Null check
        is_null = builder.icmp_unsigned("==", ctx, ir.Constant(self.heap_context_type.as_pointer(), None))
        builder.cbranch(is_null, done, do_free)

        builder.position_at_end(do_free)

        # Get heap_start and free it
        heap_start_ptr = builder.gep(ctx, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 0)
        ], inbounds=True)
        heap_start = builder.load(heap_start_ptr)
        builder.call(self.codegen.free, [heap_start])

        # Free the context struct itself
        ctx_i8 = builder.bitcast(ctx, self.i8_ptr)
        builder.call(self.codegen.free, [ctx_i8])

        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_push_context(self):
        """Push a context onto the stack, making it active for allocations

        gc_push_context(ctx: HeapContext*) -> void

        The pushed context becomes the active context for subsequent allocations.
        """
        func = self.gc_push_context
        func.args[0].name = "ctx"

        entry = func.append_basic_block("entry")
        do_push = func.append_basic_block("do_push")
        overflow = func.append_basic_block("overflow")

        builder = ir.IRBuilder(entry)
        ctx = func.args[0]

        # Load current stack top
        stack_top = builder.load(self.context_stack_top)
        max_depth = ir.Constant(self.i32, self.MAX_CONTEXT_DEPTH - 1)

        # Check for overflow
        can_push = builder.icmp_signed("<", stack_top, max_depth)
        builder.cbranch(can_push, do_push, overflow)

        builder.position_at_end(do_push)

        # Increment stack top
        new_top = builder.add(stack_top, ir.Constant(self.i32, 1))
        builder.store(new_top, self.context_stack_top)

        # Store context at new position
        # context_stack[new_top] = ctx
        slot_ptr = builder.gep(self.context_stack, [
            ir.Constant(self.i32, 0),
            new_top
        ], inbounds=True)
        builder.store(ctx, slot_ptr)

        builder.ret_void()

        # Overflow - just ignore (could log error in debug mode)
        builder.position_at_end(overflow)
        builder.ret_void()

    def _implement_gc_pop_context(self):
        """Pop a context from the stack, restore previous as active

        gc_pop_context() -> HeapContext*

        Returns the popped context (caller is responsible for destroying it if needed).
        Returns null if stack is empty.
        """
        func = self.gc_pop_context

        entry = func.append_basic_block("entry")
        do_pop = func.append_basic_block("do_pop")
        empty = func.append_basic_block("empty")

        builder = ir.IRBuilder(entry)

        # Load current stack top
        stack_top = builder.load(self.context_stack_top)

        # Check if stack is empty (top == 0 means only main context)
        is_empty = builder.icmp_signed("<=", stack_top, ir.Constant(self.i32, 0))
        builder.cbranch(is_empty, empty, do_pop)

        builder.position_at_end(do_pop)

        # Get context at current top
        slot_ptr = builder.gep(self.context_stack, [
            ir.Constant(self.i32, 0),
            stack_top
        ], inbounds=True)
        ctx = builder.load(slot_ptr)

        # Clear the slot
        builder.store(ir.Constant(self.heap_context_type.as_pointer(), None), slot_ptr)

        # Decrement stack top
        new_top = builder.sub(stack_top, ir.Constant(self.i32, 1))
        builder.store(new_top, self.context_stack_top)

        builder.ret(ctx)

        # Empty stack
        builder.position_at_end(empty)
        builder.ret(ir.Constant(self.heap_context_type.as_pointer(), None))

    def _implement_gc_alloc_in_context(self):
        """Allocate memory within a specific heap context

        gc_alloc_in_context(ctx: HeapContext*, size: i64, type_id: i32) -> i8*

        Allocates from the given context's free list. Does NOT trigger GC or
        expand heap - for nursery contexts, we want predictable behavior.
        Returns null if allocation fails (caller can promote to main heap).
        """
        func = self.gc_alloc_in_context
        func.args[0].name = "ctx"
        func.args[1].name = "user_size"
        func.args[2].name = "type_id"

        entry = func.append_basic_block("entry")
        null_check = func.append_basic_block("null_check")
        try_alloc = func.append_basic_block("try_alloc")
        loop_start = func.append_basic_block("loop_start")
        check_size = func.append_basic_block("check_size")
        found_block = func.append_basic_block("found_block")
        split_check = func.append_basic_block("split_check")
        do_split = func.append_basic_block("do_split")
        no_split = func.append_basic_block("no_split")
        next_block = func.append_basic_block("next_block")
        init_header = func.append_basic_block("init_header")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)
        ctx = func.args[0]
        user_size = func.args[1]
        type_id = func.args[2]

        # Null check on context
        is_ctx_null = builder.icmp_unsigned("==", ctx, ir.Constant(self.heap_context_type.as_pointer(), None))
        builder.cbranch(is_ctx_null, not_found, null_check)

        builder.position_at_end(null_check)

        # Calculate needed size with header and alignment
        header_size = ir.Constant(self.i64, self.HEADER_SIZE)
        total_size = builder.add(user_size, header_size)

        # Align to 8 bytes
        seven = ir.Constant(self.i64, 7)
        aligned_size = builder.and_(
            builder.add(total_size, seven),
            ir.Constant(self.i64, ~7 & 0xFFFFFFFFFFFFFFFF)
        )

        # Ensure minimum block size
        min_size = ir.Constant(self.i64, self.MIN_BLOCK_SIZE)
        is_too_small = builder.icmp_unsigned("<", aligned_size, min_size)
        final_size = builder.select(is_too_small, min_size, aligned_size)

        # Store for later use
        final_size_alloca = builder.alloca(self.i64, name="final_size")
        builder.store(final_size, final_size_alloca)

        builder.branch(try_alloc)

        # Get context's free list head
        builder.position_at_end(try_alloc)
        free_list_ptr = builder.gep(ctx, [
            ir.Constant(self.i32, 0),
            ir.Constant(self.i32, 2)
        ], inbounds=True)

        # prev_ptr points to location containing current block pointer
        prev_ptr = builder.alloca(self.i8_ptr.as_pointer(), name="prev_ptr")
        builder.store(free_list_ptr, prev_ptr)

        # curr points to current block
        curr = builder.alloca(self.i8_ptr, name="curr")
        head = builder.load(free_list_ptr)
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
        needed = builder.load(final_size_alloca)

        big_enough = builder.icmp_unsigned(">=", block_size, needed)
        builder.cbranch(big_enough, found_block, next_block)

        # Found suitable block
        builder.position_at_end(found_block)
        next_field = builder.gep(curr_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        next_block_ptr = builder.load(next_field)
        builder.branch(split_check)

        # Check if we should split
        builder.position_at_end(split_check)
        remaining = builder.sub(block_size, needed)
        min_block = ir.Constant(self.i64, self.MIN_BLOCK_SIZE)
        should_split = builder.icmp_unsigned(">=", remaining, min_block)
        builder.cbranch(should_split, do_split, no_split)

        # Split the block
        builder.position_at_end(do_split)
        curr_int = builder.ptrtoint(curr_val, self.i64)
        new_block_int = builder.add(curr_int, needed)
        new_block_ptr2 = builder.inttoptr(new_block_int, self.i8_ptr)
        new_block_node = builder.bitcast(new_block_ptr2, self.free_node_type.as_pointer())

        # Set new block's size
        new_size_ptr = builder.gep(new_block_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(remaining, new_size_ptr)

        # Set new block's next
        new_next_ptr = builder.gep(new_block_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(next_block_ptr, new_next_ptr)

        # Update prev to point to new block
        prev_loc = builder.load(prev_ptr)
        builder.store(new_block_ptr2, prev_loc)

        # Update size of allocated block
        builder.store(needed, size_ptr)

        # Store allocated values for init_header
        allocated_block = builder.alloca(self.i8_ptr, name="allocated")
        builder.store(curr_val, allocated_block)
        allocated_size = builder.alloca(self.i64, name="alloc_size")
        builder.store(needed, allocated_size)

        builder.branch(init_header)

        # Use entire block
        builder.position_at_end(no_split)
        prev_loc2 = builder.load(prev_ptr)
        builder.store(next_block_ptr, prev_loc2)

        # Store for init_header
        allocated_block2 = builder.alloca(self.i8_ptr, name="allocated2")
        builder.store(curr_val, allocated_block2)

        builder.branch(init_header)

        # Move to next block
        builder.position_at_end(next_block)
        next_field2 = builder.gep(curr_node, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        next_field2_cast = builder.bitcast(next_field2, self.i8_ptr.as_pointer())
        builder.store(next_field2_cast, prev_ptr)
        next_val = builder.load(next_field2)
        builder.store(next_val, curr)
        builder.branch(loop_start)

        # Initialize header and return user pointer
        builder.position_at_end(init_header)
        # Use phi to get the allocated block from either path
        block_phi = builder.phi(self.i8_ptr, name="block_phi")
        block_phi.add_incoming(curr_val, do_split)
        block_phi.add_incoming(curr_val, no_split)

        header = builder.bitcast(block_phi, self.header_type.as_pointer())

        # Type ID at offset 1
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr)

        # Flags at offset 2 (set mark bit if in MARK phase for snapshot-at-beginning)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        current_phase_ctx = builder.load(self.gc_phase)
        is_mark_phase_ctx = builder.icmp_unsigned("==", current_phase_ctx, ir.Constant(self.i32, self.GC_PHASE_MARK))
        initial_flags_ctx = builder.select(is_mark_phase_ctx,
            ir.Constant(self.i32, self.FLAG_MARK_BIT),
            ir.Constant(self.i32, 0))
        builder.store(initial_flags_ctx, flags_ptr)

        # Finalizer at offset 3 (null)
        finalizer_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(ir.Constant(self.i8_ptr, None), finalizer_ptr)

        # Return pointer to user data
        block_int = builder.ptrtoint(block_phi, self.i64)
        user_ptr_int = builder.add(block_int, header_size)
        user_ptr = builder.inttoptr(user_ptr_int, self.i8_ptr)

        builder.ret(user_ptr)

        # Not found
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_set_finalizer(self):
        """Set a finalizer function for an object.

        gc_set_finalizer(obj: i8*, finalizer: i8*) -> void

        The finalizer is a function pointer with signature: void (*)(i8*)
        It will be called with the user pointer when the object is swept.
        Sets FLAG_FINALIZER bit in flags if finalizer is non-null.
        """
        func = self.gc_set_finalizer
        func.args[0].name = "obj_ptr"
        func.args[1].name = "finalizer"

        entry = func.append_basic_block("entry")
        valid = func.append_basic_block("valid")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        obj_ptr = func.args[0]
        finalizer = func.args[1]

        # Null check on object pointer
        is_null = builder.icmp_unsigned("==", obj_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, valid)

        builder.position_at_end(valid)
        # Get header (HEADER_SIZE bytes before user pointer)
        obj_int = builder.ptrtoint(obj_ptr, self.i64)
        header_int = builder.sub(obj_int, ir.Constant(self.i64, self.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, self.i8_ptr)
        header = builder.bitcast(header_ptr, self.header_type.as_pointer())

        # Store finalizer at offset 3
        finalizer_field = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 3)], inbounds=True)
        builder.store(finalizer, finalizer_field)

        # Set FLAG_FINALIZER bit if finalizer is non-null
        finalizer_is_null = builder.icmp_unsigned("==", finalizer, ir.Constant(self.i8_ptr, None))
        set_flag = func.append_basic_block("set_flag")
        clear_flag = func.append_basic_block("clear_flag")
        merge = func.append_basic_block("merge")

        builder.cbranch(finalizer_is_null, clear_flag, set_flag)

        # Set the FLAG_FINALIZER bit
        builder.position_at_end(set_flag)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        old_flags = builder.load(flags_ptr)
        new_flags = builder.or_(old_flags, ir.Constant(self.i32, self.FLAG_FINALIZER))
        builder.store(new_flags, flags_ptr)
        builder.branch(merge)

        # Clear the FLAG_FINALIZER bit
        builder.position_at_end(clear_flag)
        flags_ptr2 = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        old_flags2 = builder.load(flags_ptr2)
        new_flags2 = builder.and_(old_flags2, ir.Constant(self.i32, ~self.FLAG_FINALIZER & 0xFFFFFFFF))
        builder.store(new_flags2, flags_ptr2)
        builder.branch(merge)

        builder.position_at_end(merge)
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_register_root(self):
        """Register a root pointer for GC tracing.

        gc_register_root(root_ptr: i8**) -> i32

        Registers the address of a pointer variable as a GC root.
        Returns a handle (index) for later unregistration.
        Returns -1 if registry is full.
        """
        func = self.gc_register_root
        func.args[0].name = "root_ptr"

        entry = func.append_basic_block("entry")
        acquire_lock = func.append_basic_block("acquire_lock")
        check_full = func.append_basic_block("check_full")
        registry_full = func.append_basic_block("registry_full")
        do_register = func.append_basic_block("do_register")
        release_and_return = func.append_basic_block("release_and_return")

        builder = ir.IRBuilder(entry)
        root_ptr = func.args[0]

        # Allocate return value
        result = builder.alloca(self.i32, name="result")
        builder.store(ir.Constant(self.i32, -1), result)

        builder.branch(acquire_lock)

        # Acquire roots mutex
        builder.position_at_end(acquire_lock)
        roots_mutex_ptr = builder.bitcast(self.gc_roots_mutex, self.pthread_mutex_type.as_pointer())
        builder.call(self.pthread_mutex_lock, [roots_mutex_ptr])
        builder.branch(check_full)

        # Check if registry is full
        builder.position_at_end(check_full)
        count = builder.load(self.gc_root_count)
        max_roots = ir.Constant(self.i32, self.MAX_ROOTS)
        is_full = builder.icmp_unsigned(">=", count, max_roots)
        builder.cbranch(is_full, registry_full, do_register)

        # Registry is full - release lock and return -1
        builder.position_at_end(registry_full)
        builder.store(ir.Constant(self.i32, -1), result)
        builder.branch(release_and_return)

        # Do the registration
        builder.position_at_end(do_register)
        # Get the current count as the handle/index
        handle = builder.load(self.gc_root_count)

        # Cast root_ptr to the element type expected by gc_roots array
        root_slot_type = self.i8_ptr.as_pointer()
        root_ptr_cast = builder.bitcast(root_ptr, root_slot_type)

        # Store root pointer at gc_roots[handle]
        handle_64 = builder.zext(handle, self.i64)
        slot_ptr = builder.gep(self.gc_roots, [
            ir.Constant(self.i64, 0),
            handle_64
        ], inbounds=True)
        builder.store(root_ptr_cast, slot_ptr)

        # Increment root count
        new_count = builder.add(handle, ir.Constant(self.i32, 1))
        builder.store(new_count, self.gc_root_count)

        # Store handle as result
        builder.store(handle, result)
        builder.branch(release_and_return)

        # Release lock and return result
        builder.position_at_end(release_and_return)
        builder.call(self.pthread_mutex_unlock, [roots_mutex_ptr])
        final_result = builder.load(result)
        builder.ret(final_result)

    def _implement_gc_unregister_root(self):
        """Unregister a previously registered root.

        gc_unregister_root(handle: i32) -> void

        Sets the root slot to null. The slot can be reused by a future registration
        if we implement a more sophisticated scheme, but for now we just null it out.
        """
        func = self.gc_unregister_root
        func.args[0].name = "handle"

        entry = func.append_basic_block("entry")
        check_bounds = func.append_basic_block("check_bounds")
        valid_handle = func.append_basic_block("valid_handle")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        handle = func.args[0]
        builder.branch(check_bounds)

        # Check handle is within bounds
        builder.position_at_end(check_bounds)
        count = builder.load(self.gc_root_count)
        is_negative = builder.icmp_signed("<", handle, ir.Constant(self.i32, 0))
        is_too_large = builder.icmp_unsigned(">=", handle, count)
        is_invalid = builder.or_(is_negative, is_too_large)
        builder.cbranch(is_invalid, done, valid_handle)

        # Valid handle - acquire lock and clear slot
        builder.position_at_end(valid_handle)
        roots_mutex_ptr = builder.bitcast(self.gc_roots_mutex, self.pthread_mutex_type.as_pointer())
        builder.call(self.pthread_mutex_lock, [roots_mutex_ptr])

        # Set gc_roots[handle] = null
        root_slot_type = self.i8_ptr.as_pointer()
        handle_64 = builder.zext(handle, self.i64)
        slot_ptr = builder.gep(self.gc_roots, [
            ir.Constant(self.i64, 0),
            handle_64
        ], inbounds=True)
        builder.store(ir.Constant(root_slot_type, None), slot_ptr)

        # Release lock
        builder.call(self.pthread_mutex_unlock, [roots_mutex_ptr])
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()

    def _implement_gc_thread_main(self):
        """Implement the GC background thread main loop.

        gc_thread_main(arg: i8*) -> i8*

        Thread waits for gc_request flag, then runs mark-sweep cycle.
        Uses snapshot-at-the-beginning: objects allocated during mark are marked live.
        """
        func = self.gc_thread_main
        func.args[0].name = "arg"

        entry = func.append_basic_block("entry")
        loop_start = func.append_basic_block("loop_start")
        check_running = func.append_basic_block("check_running")
        wait_for_request = func.append_basic_block("wait_for_request")
        check_request = func.append_basic_block("check_request")
        do_collection = func.append_basic_block("do_collection")
        exit_thread = func.append_basic_block("exit_thread")

        builder = ir.IRBuilder(entry)
        builder.branch(loop_start)

        # Main loop: while gc_running == 1
        builder.position_at_end(loop_start)
        builder.branch(check_running)

        builder.position_at_end(check_running)
        running = builder.load(self.gc_running)
        is_running = builder.icmp_unsigned("==", running, ir.Constant(self.i32, 1))
        builder.cbranch(is_running, wait_for_request, exit_thread)

        # Wait for gc_request using condition variable
        builder.position_at_end(wait_for_request)
        mutex_ptr = builder.bitcast(self.heap_mutex, self.pthread_mutex_type.as_pointer())
        cond_ptr = builder.bitcast(self.gc_cond, self.pthread_cond_type.as_pointer())

        # Lock mutex
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Check request flag
        builder.branch(check_request)

        builder.position_at_end(check_request)
        request = builder.load(self.gc_request)
        has_request = builder.icmp_unsigned("==", request, ir.Constant(self.i32, 1))

        wait_block = func.append_basic_block("wait_block")
        builder.cbranch(has_request, do_collection, wait_block)

        # Wait on condition variable
        builder.position_at_end(wait_block)
        # Check if still running before waiting
        running2 = builder.load(self.gc_running)
        still_running = builder.icmp_unsigned("==", running2, ir.Constant(self.i32, 1))

        do_wait = func.append_basic_block("do_wait")
        unlock_exit = func.append_basic_block("unlock_exit")
        builder.cbranch(still_running, do_wait, unlock_exit)

        builder.position_at_end(do_wait)
        builder.call(self.pthread_cond_wait, [cond_ptr, mutex_ptr])
        builder.branch(check_request)

        builder.position_at_end(unlock_exit)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])
        builder.branch(exit_thread)

        # Perform collection
        builder.position_at_end(do_collection)
        # Set phase to MARK
        builder.store(ir.Constant(self.i32, self.GC_PHASE_MARK), self.gc_phase)

        # Unlock mutex during marking (allow allocations)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        # Call mark phase (scan_stack marks all reachable objects)
        builder.call(self.gc_scan_stack, [])

        # Lock mutex for sweep phase
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Set phase to SWEEP
        builder.store(ir.Constant(self.i32, self.GC_PHASE_SWEEP), self.gc_phase)

        # Unlock for sweep (sweep doesn't need exclusive access with conservative approach)
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        # Call sweep phase
        builder.call(self.gc_sweep, [])

        # Lock to update state
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Set phase to IDLE
        builder.store(ir.Constant(self.i32, self.GC_PHASE_IDLE), self.gc_phase)

        # Clear request flag
        builder.store(ir.Constant(self.i32, 0), self.gc_request)

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        # Loop back
        builder.branch(loop_start)

        # Exit thread
        builder.position_at_end(exit_thread)
        builder.ret(ir.Constant(self.i8_ptr, None))

    def _implement_gc_shutdown(self):
        """Shutdown the GC background thread gracefully.

        gc_shutdown() -> void

        Signals the GC thread to stop and waits for it to exit.
        """
        func = self.gc_shutdown
        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        mutex_ptr = builder.bitcast(self.heap_mutex, self.pthread_mutex_type.as_pointer())
        cond_ptr = builder.bitcast(self.gc_cond, self.pthread_cond_type.as_pointer())

        # Lock mutex
        builder.call(self.pthread_mutex_lock, [mutex_ptr])

        # Set gc_running = 0
        builder.store(ir.Constant(self.i32, 0), self.gc_running)

        # Signal condition variable to wake up thread
        builder.call(self.pthread_cond_signal, [cond_ptr])

        # Unlock mutex
        builder.call(self.pthread_mutex_unlock, [mutex_ptr])

        # Wait for thread to exit
        thread_handle = builder.load(self.gc_thread)
        builder.call(self.pthread_join, [
            thread_handle,
            ir.Constant(self.i8_ptr.as_pointer(), None)
        ])

        # Destroy mutex and condition variable
        builder.call(self.pthread_mutex_destroy, [mutex_ptr])
        builder.call(self.pthread_cond_destroy, [cond_ptr])

        builder.ret_void()

    def _implement_gc_write_barrier(self):
        """Implement write barrier for concurrent mark phase.

        gc_write_barrier(old_ptr: i8*) -> void

        Called BEFORE overwriting a pointer field. If we're in MARK phase,
        marks the old value to prevent premature collection (snapshot-at-the-beginning).
        This ensures that objects reachable at the start of collection remain live.
        """
        func = self.gc_write_barrier
        func.args[0].name = "old_ptr"

        entry = func.append_basic_block("entry")
        check_phase = func.append_basic_block("check_phase")
        do_mark = func.append_basic_block("do_mark")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        old_ptr = func.args[0]

        # Quick null check - no need to mark null
        is_null = builder.icmp_unsigned("==", old_ptr, ir.Constant(self.i8_ptr, None))
        builder.cbranch(is_null, done, check_phase)

        # Check if we're in MARK phase
        builder.position_at_end(check_phase)
        phase = builder.load(self.gc_phase)
        is_mark_phase = builder.icmp_unsigned("==", phase, ir.Constant(self.i32, self.GC_PHASE_MARK))
        builder.cbranch(is_mark_phase, do_mark, done)

        # In MARK phase - mark the old value before it's overwritten
        builder.position_at_end(do_mark)
        builder.call(self.gc_mark_object, [old_ptr])
        builder.branch(done)

        builder.position_at_end(done)
        builder.ret_void()
