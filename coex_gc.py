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

    # Constants
    HEADER_SIZE = 16         # 8-byte size + 4-byte type_id + 4-byte flags
    MIN_BLOCK_SIZE = 24      # Minimum block: header(16) + alignment padding
    MAX_TYPES = 256          # Maximum number of registered types
    GC_THRESHOLD = 1000      # Trigger GC after this many allocations

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
        self._add_nursery_stubs()  # Disabled nursery context stubs for compatibility

    def _create_types(self):
        """Create GC-related LLVM types"""
        # Object header: { i64 size, i32 type_id, i32 flags }
        # Placed immediately before user data
        self.header_type = ir.LiteralStructType([
            self.i64,  # block size (including header)
            self.i32,  # type_id
            self.i32,  # flags (bit 0 = mark)
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

    def _create_globals(self):
        """Create GC global variables"""
        # Top of shadow stack frame chain
        self.gc_frame_top = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_frame_top")
        self.gc_frame_top.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_frame_top.linkage = 'internal'

        # Head of allocation list (for sweep)
        self.gc_alloc_list = ir.GlobalVariable(self.module, self.i8_ptr, name="gc_alloc_list")
        self.gc_alloc_list.initializer = ir.Constant(self.i8_ptr, None)
        self.gc_alloc_list.linkage = 'internal'

        # Allocation counter
        self.gc_alloc_count = ir.GlobalVariable(self.module, self.i64, name="gc_alloc_count")
        self.gc_alloc_count.initializer = ir.Constant(self.i64, 0)
        self.gc_alloc_count.linkage = 'internal'

        # GC enabled flag (disabled during collection)
        self.gc_enabled = ir.GlobalVariable(self.module, self.i1, name="gc_enabled")
        self.gc_enabled.initializer = ir.Constant(self.i1, 1)
        self.gc_enabled.linkage = 'internal'

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

        # gc_mark_hamt(root: i8*, flags: i32) -> void
        # Recursively mark HAMT nodes/leaves (used by Map and Set marking)
        # flags: bit 0 = key is heap ptr, bit 1 = value is heap ptr
        gc_mark_hamt_ty = ir.FunctionType(self.void, [self.i8_ptr, self.i32])
        self.gc_mark_hamt = ir.Function(self.module, gc_mark_hamt_ty, name="coex_gc_mark_hamt")

    def _register_builtin_types(self):
        """Register built-in heap-allocated types"""
        self.type_info[self.TYPE_UNKNOWN] = {'size': 0, 'ref_offsets': []}
        self.type_info[self.TYPE_LIST] = {'size': 32, 'ref_offsets': [24]}
        self.type_descriptors['List'] = self.TYPE_LIST
        self.type_info[self.TYPE_STRING] = {'size': 8, 'ref_offsets': []}
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
        self.type_info[self.TYPE_ARRAY] = {'size': 32, 'ref_offsets': [24]}
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

    def _implement_gc_init(self):
        """Initialize GC state"""
        func = self.gc_init
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Reset state
        builder.store(ir.Constant(self.i8_ptr, None), self.gc_frame_top)
        builder.store(ir.Constant(self.i8_ptr, None), self.gc_alloc_list)
        builder.store(ir.Constant(self.i64, 0), self.gc_alloc_count)
        builder.store(ir.Constant(self.i1, 1), self.gc_enabled)

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

        builder.ret(raw_frame)

    def _implement_gc_pop_frame(self):
        """Pop a frame from the shadow stack"""
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

        # Free the frame
        builder.call(self.codegen.free, [frame_ptr])

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
        check_gc = func.append_basic_block("check_gc")
        do_alloc = func.append_basic_block("do_alloc")

        builder = ir.IRBuilder(entry)

        user_size = func.args[0]
        type_id = func.args[1]

        # Increment allocation counter
        count = builder.load(self.gc_alloc_count)
        new_count = builder.add(count, ir.Constant(self.i64, 1))
        builder.store(new_count, self.gc_alloc_count)

        builder.branch(check_gc)

        # Check if we should trigger GC
        builder.position_at_end(check_gc)
        threshold = ir.Constant(self.i64, self.GC_THRESHOLD)
        should_gc = builder.icmp_unsigned(">=", new_count, threshold)
        gc_enabled = builder.load(self.gc_enabled)
        trigger_gc = builder.and_(should_gc, gc_enabled)
        builder.cbranch(trigger_gc, do_alloc, do_alloc)  # For now, skip GC trigger

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

        # Initialize header
        header = builder.bitcast(block, self.header_type.as_pointer())

        # Size field
        size_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        builder.store(aligned_size, size_ptr)

        # Type ID field
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        builder.store(type_id, type_id_ptr)

        # Flags field (0 = not marked)
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        builder.store(ir.Constant(self.i32, 0), flags_ptr)

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
        """Mark an object as live and recursively mark referenced objects"""
        func = self.gc_mark_object
        func.args[0].name = "ptr"

        entry = func.append_basic_block("entry")
        get_header = func.append_basic_block("get_header")
        do_mark = func.append_basic_block("do_mark")
        check_type = func.append_basic_block("check_type")
        mark_map = func.append_basic_block("mark_map")
        mark_list = func.append_basic_block("mark_list")
        mark_array = func.append_basic_block("mark_array")
        mark_set = func.append_basic_block("mark_set")
        mark_string = func.append_basic_block("mark_string")
        mark_channel = func.append_basic_block("mark_channel")
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

        # Check if already marked
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)
        is_marked = builder.and_(flags, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        already_marked = builder.icmp_unsigned("!=", is_marked, ir.Constant(self.i32, 0))
        builder.cbranch(already_marked, done, do_mark)

        builder.position_at_end(do_mark)
        # Set mark bit - need to reload flags since we're in a new block
        flags_val = builder.load(flags_ptr)
        new_flags = builder.or_(flags_val, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        builder.store(new_flags, flags_ptr)

        # Get type_id and check for types that need recursive marking
        type_id_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)
        builder.branch(check_type)

        # Check type and branch to appropriate recursive marking
        builder.position_at_end(check_type)

        # Create a switch for type_id
        switch = builder.switch(type_id, done)
        switch.add_case(ir.Constant(self.i32, self.TYPE_MAP), mark_map)
        switch.add_case(ir.Constant(self.i32, self.TYPE_LIST), mark_list)
        switch.add_case(ir.Constant(self.i32, self.TYPE_ARRAY), mark_array)
        switch.add_case(ir.Constant(self.i32, self.TYPE_SET), mark_set)
        switch.add_case(ir.Constant(self.i32, self.TYPE_STRING), mark_string)
        switch.add_case(ir.Constant(self.i32, self.TYPE_CHANNEL), mark_channel)

        # Mark Map: HAMT-based, root at offset 0
        # Map struct: { i64 root, i64 len, i64 flags }
        # All fields are i64 for cross-platform consistency (no padding issues)
        # HAMT nodes and leaves ARE gc_alloc'd, so we must traverse and mark them.
        # flags: bit 0 = key is ptr, bit 1 = value is ptr
        builder.position_at_end(mark_map)
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

        # Mark Array: data pointer at field 0
        # Array struct: { i8* data (0), i64 len (1), i64 cap (2), i64 elem_size (3) }
        builder.position_at_end(mark_array)
        array_ptr_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64, self.i64]).as_pointer()
        array_typed = builder.bitcast(ptr, array_ptr_type)
        data_ptr_ptr = builder.gep(array_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        data_ptr = builder.load(data_ptr_ptr)
        builder.call(func, [data_ptr])  # Recursive call
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

        # Mark String: data pointer at field 0
        # String struct: { i8* data (0), i64 len (1), i64 size (2) }
        builder.position_at_end(mark_string)
        string_ptr_type = ir.LiteralStructType([self.i8_ptr, self.i64, self.i64]).as_pointer()
        string_typed = builder.bitcast(ptr, string_ptr_type)
        string_data_ptr_ptr = builder.gep(string_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 0)], inbounds=True)
        string_data_ptr = builder.load(string_data_ptr_ptr)
        builder.call(func, [string_data_ptr])  # Recursive call
        builder.branch(done)

        # Mark Channel: buffer pointer at offset 32 (4th i64 field)
        builder.position_at_end(mark_channel)
        channel_ptr_type = ir.LiteralStructType([self.i64, self.i64, self.i64, self.i64, self.i8_ptr]).as_pointer()
        channel_typed = builder.bitcast(ptr, channel_ptr_type)
        buffer_ptr_ptr = builder.gep(channel_typed, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 4)], inbounds=True)
        buffer_ptr = builder.load(buffer_ptr_ptr)
        builder.call(func, [buffer_ptr])  # Recursive call
        builder.branch(done)

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

        # Check mark bit
        flags_ptr = builder.gep(header, [ir.Constant(self.i32, 0), ir.Constant(self.i32, 2)], inbounds=True)
        flags = builder.load(flags_ptr)
        mark_bit = builder.and_(flags, ir.Constant(self.i32, self.FLAG_MARK_BIT))
        is_marked = builder.icmp_unsigned("!=", mark_bit, ir.Constant(self.i32, 0))
        builder.cbranch(is_marked, is_marked_block, is_unmarked_block)

        # Object is marked - clear mark bit and keep it
        builder.position_at_end(is_marked_block)
        cleared_flags = builder.and_(flags, ir.Constant(self.i32, ~self.FLAG_MARK_BIT & 0xFFFFFFFF))
        builder.store(cleared_flags, flags_ptr)
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
        builder.ret_void()

    def _implement_gc_collect(self):
        """Run a full garbage collection cycle

        Now that shadow stack frames are integrated into codegen, we can
        safely perform mark-sweep collection. The shadow stack tracks all
        heap roots, so sweep will only free unreachable objects.
        """
        func = self.gc_collect

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Disable GC during collection (prevent recursion)
        builder.store(ir.Constant(self.i1, 0), self.gc_enabled)

        # Mark phase: scan shadow stack and mark all reachable objects
        builder.call(self.gc_scan_roots, [])

        # Sweep phase: free unmarked objects
        builder.call(self.gc_sweep, [])

        # Re-enable GC
        builder.store(ir.Constant(self.i1, 1), self.gc_enabled)

        builder.ret_void()

    def wrap_allocation(self, builder: ir.IRBuilder, type_name: str, size: ir.Value) -> ir.Value:
        """Replace a malloc call with GC-tracked allocation."""
        type_id = self.get_type_id(type_name)
        type_id_const = ir.Constant(self.i32, type_id)
        return builder.call(self.gc_alloc, [size, type_id_const])

    def inject_gc_init(self, builder: ir.IRBuilder):
        """Inject GC initialization at start of main()"""
        builder.call(self.gc_init, [])

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
