"""
Coex LLVM Code Generator

Generates LLVM IR from Coex AST using llvmlite.
Handles the full language, with concurrency primitives implemented sequentially.
"""

from llvmlite import ir, binding
from ast_nodes import *
from typing import Dict, Optional, Tuple, List as PyList
from dataclasses import dataclass, field
import struct
import os

# Import garbage collector (will be initialized after module creation)
from coex_gc import GarbageCollector

# Import string generator module
from codegen.strings import StringGenerator

# Import posix generator module
from codegen.posix import PosixGenerator

# Import JSON generator module
from codegen.json_type import JsonGenerator

# Import list generator module
from codegen.list import ListGenerator

# Import HAMT/Map/Set generator module
from codegen.hamt import HamtGenerator

# Import CXZ library loader (for FFI support)
from cxz_loader import CXZLoader, LoadedLibrary, FFISymbol, CXZError

binding.initialize_native_target()
binding.initialize_native_asmprinter()

@dataclass
class ModuleInfo:
    """Information about a loaded module"""
    name: str
    path: str
    program: 'Program'
    functions: Dict[str, str] = field(default_factory=dict)  # func_name -> mangled_name
    types: Dict[str, str] = field(default_factory=dict)      # type_name -> mangled_name


@dataclass
class LibraryInfo:
    """Information about a loaded .cxz library"""
    name: str
    path: str
    loaded_lib: LoadedLibrary
    symbols: Dict[str, FFISymbol] = field(default_factory=dict)  # symbol_name -> FFISymbol


class CodeGenerator:
    """Generates LLVM IR from Coex AST"""
    
    def __init__(self):
        # Initialize LLVM (newer versions do this automatically)
        try:
            binding.initialize()
            binding.initialize_native_target()
            binding.initialize_native_asmprinter()
        except RuntimeError:
            # Newer llvmlite versions don't need explicit initialization
            pass
        
        # Create module
        self.module = ir.Module(name="coex_module")
        self.module.triple = binding.get_default_triple()
        
        # Builder for current function
        self.builder: Optional[ir.IRBuilder] = None
        
        # Symbol tables
        self.locals: Dict[str, ir.AllocaInst] = {}
        self.functions: Dict[str, ir.Function] = {}

        # Scope tracking for better error messages
        self.scope_depth: int = 0  # Current nesting level
        self.var_scopes: Dict[str, int] = {}  # variable_name -> scope_depth where declared
        self.scope_stack: PyList[PyList[str]] = [[]]  # Stack of variable names per scope level
        
        # Type registry for user-defined types
        self.type_registry: Dict[str, ir.Type] = {}  # type_name -> LLVM struct type (not pointer)
        self.type_fields: Dict[str, PyList[Tuple[str, Type]]] = {}  # type_name -> [(field_name, coex_type)]
        self.type_methods: Dict[str, Dict[str, str]] = {}  # type_name -> {method_name -> mangled_func_name}
        self.static_methods: Dict[str, bool] = {}  # mangled_method_name -> True if static (no self param)
        self.type_decls: Dict[str, TypeDecl] = {}  # type_name -> TypeDecl AST node
        self.enum_variants: Dict[str, Dict[str, tuple]] = {}  # enum_name -> {variant_name -> (tag, fields)}
        
        # Generic type and function templates (not yet monomorphized)
        self.generic_types: Dict[str, TypeDecl] = {}  # name -> TypeDecl with type_params
        self.generic_functions: Dict[str, FunctionDecl] = {}  # name -> FunctionDecl with type_params
        self.monomorphized: Dict[str, bool] = {}  # mangled_name -> True (tracks what's been generated)
        
        # Trait registry
        self.traits: Dict[str, 'TraitDecl'] = {}  # trait_name -> TraitDecl
        self.type_implements: Dict[str, PyList[str]] = {}  # type_name -> [trait_names]
        
        # Current type substitution map for monomorphization
        self.type_substitutions: Dict[str, Type] = {}  # T -> int, U -> float, etc.
        
        # Loop control flow
        self.loop_exit_block: Optional[ir.Block] = None
        self.loop_continue_block: Optional[ir.Block] = None

        # Cycle (double-buffer) context stack for cycle blocks
        self._cycle_context_stack: PyList[Dict] = []

        # Current function for context
        self.current_function: Optional[FunctionDecl] = None
        self.current_type: Optional[str] = None  # For method generation

        # Pre-allocated temp for comprehensions (avoids stack overflow in large comprehensions)
        self._comp_temp_alloca: Optional[ir.AllocaInst] = None
        
        # Tuple field tracking (for named tuple access)
        self.tuple_field_info: Dict[str, PyList[tuple]] = {}  # var_name -> [(field_name, field_type)]
        
        # Function declaration tracking (for return type inference)
        self.func_decls: Dict[str, FunctionDecl] = {}  # func_name -> FunctionDecl
        
        # String interning
        self.string_constants: Dict[str, ir.GlobalVariable] = {}
        self.string_counter = 0
        
        # Lambda counter for unique names
        self.lambda_counter = 0
        
        # List element type tracking for proper destructuring
        self.list_element_types: Dict[str, ir.Type] = {}  # var_name -> element LLVM type

        # Array element type tracking for proper destructuring
        self.array_element_types: Dict[str, ir.Type] = {}  # var_name -> element LLVM type

        # Coex AST type tracking for deep copy and nested collections
        self.var_coex_types: Dict[str, Type] = {}  # var_name -> Coex AST Type

        # Move tracking for use-after-move detection
        self.moved_vars: set = set()  # Set of variable names that have been moved

        # Const binding tracking for reassignment checking
        self.const_bindings: set = set()  # Set of const variable names

        # Placeholder variable tracking for loop pre-allocation
        self.placeholder_vars: set = set()  # Set of pre-allocated placeholder variable names

        # List runtime support
        self.list_type = None

        # Module system support
        self.loaded_modules: Dict[str, ModuleInfo] = {}  # module_name -> ModuleInfo
        self.replace_aliases: Dict[str, Tuple[str, str]] = {}  # shortname -> (module, func_name)
        self.module_search_paths: PyList[str] = []
        self.current_module: Optional[str] = None  # Track which module we're compiling

        # Print/Debug directive support
        self.printing_enabled: bool = True   # Default: print() enabled
        self.debugging_enabled: bool = False  # Default: debug() disabled
        self.cli_printing: Optional[bool] = None  # CLI override for printing
        self.cli_debugging: Optional[bool] = None  # CLI override for debugging

        # FFI library support (.cxz libraries)
        self.loaded_libraries: Dict[str, LibraryInfo] = {}  # library_name -> LibraryInfo
        self.cxz_loader: Optional[CXZLoader] = None  # Initialized lazily when needed
        self.ffi_symbols: Dict[str, FFISymbol] = {}  # symbol_name -> FFISymbol (aggregated from all libraries)
        self.ffi_link_args: PyList[str] = []  # Link arguments for FFI objects

        # FFI runtime function declarations
        self._ffi_runtime_declared = False
        self._ffi_instance_create: Optional[ir.Function] = None
        self._ffi_instance_destroy: Optional[ir.Function] = None
        self._ffi_enter: Optional[ir.Function] = None
        self._ffi_exit: Optional[ir.Function] = None

        # FFI instance tracking per function (for nested calls)
        self._current_ffi_instance: Optional[ir.Value] = None
        self._ffi_instance_stack: PyList[ir.Value] = []

        # Inline LLVM IR support
        self._pending_inline_ir: PyList[Dict] = []  # Pending IR to inject during serialization
        self._inline_ir_counter = 0  # Counter for unique stub function names

        # Compiler warnings for implicit conversions
        # These are collected during code generation and can be output as #@ comments
        self.warnings: PyList[Dict] = []  # [{line, column, category, message}, ...]
        self.current_line: int = 0  # Current source line being processed

        # Garbage collector (initialized after module creation, before builtins)
        self.gc: Optional[GarbageCollector] = None

        # Declare external functions
        self._declare_builtins()
    
    def _declare_builtins(self):
        """Declare built-in functions"""
        # printf
        printf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True)
        self.printf = ir.Function(self.module, printf_ty, name="printf")

        # dprintf (write to file descriptor, POSIX) - used for debug output to stderr
        dprintf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(32), ir.IntType(8).as_pointer()], var_arg=True)
        self.dprintf = ir.Function(self.module, dprintf_ty, name="dprintf")

        # fflush for output synchronization (NULL argument flushes all output streams)
        fflush_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()])
        self.fflush = ir.Function(self.module, fflush_ty, name="fflush")

        # malloc/free for runtime allocations
        malloc_ty = ir.FunctionType(ir.IntType(8).as_pointer(), [ir.IntType(64)])
        self.malloc = ir.Function(self.module, malloc_ty, name="malloc")
        
        free_ty = ir.FunctionType(ir.VoidType(), [ir.IntType(8).as_pointer()])
        self.free = ir.Function(self.module, free_ty, name="free")
        
        # memcpy
        memcpy_ty = ir.FunctionType(ir.IntType(8).as_pointer(),
                                     [ir.IntType(8).as_pointer(),
                                      ir.IntType(8).as_pointer(),
                                      ir.IntType(64)])
        self.memcpy = ir.Function(self.module, memcpy_ty, name="memcpy")

        # memset
        memset_ty = ir.FunctionType(ir.IntType(8).as_pointer(),
                                     [ir.IntType(8).as_pointer(),
                                      ir.IntType(8),
                                      ir.IntType(64)])
        self.memset = ir.Function(self.module, memset_ty, name="memset")

        # strtoll for string to int conversion
        strtoll_ty = ir.FunctionType(ir.IntType(64),
                                      [ir.IntType(8).as_pointer(),
                                       ir.IntType(8).as_pointer().as_pointer(),
                                       ir.IntType(32)])
        self.strtoll = ir.Function(self.module, strtoll_ty, name="strtoll")

        # strtod for string to float conversion
        strtod_ty = ir.FunctionType(ir.DoubleType(),
                                     [ir.IntType(8).as_pointer(),
                                      ir.IntType(8).as_pointer().as_pointer()])
        self.strtod = ir.Function(self.module, strtod_ty, name="strtod")

        # snprintf for int/float to string conversion
        snprintf_ty = ir.FunctionType(ir.IntType(32),
                                       [ir.IntType(8).as_pointer(),
                                        ir.IntType(64),
                                        ir.IntType(8).as_pointer()],
                                       var_arg=True)
        self.snprintf = ir.Function(self.module, snprintf_ty, name="snprintf")

        # strtoll with base for hex parsing
        # Already declared above as strtoll

        # Initialize garbage collector (must be before struct helpers that use gc_alloc)
        self.gc = GarbageCollector(self.module, self)
        self.gc.generate_gc_runtime()

        # String format specifiers
        self._int_fmt = self._create_global_string("%lld\n", "int_fmt")
        self._float_fmt = self._create_global_string("%f\n", "float_fmt")
        self._str_fmt = self._create_global_string("%s\n", "str_fmt")
        self._true_str = self._create_global_string("true\n", "true_str")
        self._false_str = self._create_global_string("false\n", "false_str")
        self._nil_str = self._create_global_string("nil\n", "nil_str")

        # Format strings for String.from() conversions (no newline)
        self._int_conv_fmt = self._create_global_string("%lld", "int_conv_fmt")
        self._float_conv_fmt = self._create_global_string("%g", "float_conv_fmt")
        self._hex_conv_fmt = self._create_global_string("%llx", "hex_conv_fmt")
        self._true_conv_str = self._create_global_string("true", "true_conv_str")
        self._false_conv_str = self._create_global_string("false", "false_conv_str")
        
        # Create Persistent Vector Node structure (for List's tree structure)
        # struct PVNode { void* children[32] }
        # 32-way branching trie for O(log32 n) access
        # NOTE: No refcount - structural sharing works via GC
        self.pv_node_struct = ir.global_context.get_identified_type("struct.PVNode")
        self.pv_node_struct.set_body(
            ir.ArrayType(ir.IntType(8).as_pointer(), 32)  # children[32] (field 0) - either PVNode* or element pointers
        )

        # Create list struct type using Persistent Vector structure
        # Phase 4: All fields are i64 for handle-based GC
        # struct List { i64 root_handle, i64 len, i64 depth, i64 tail_handle, i64 tail_len, i64 elem_size }
        # Tail optimization: rightmost 1-32 elements stored separately for fast append
        self.list_struct = ir.global_context.get_identified_type("struct.List")
        self.list_struct.set_body(
            ir.IntType(64),   # root_handle - tree root handle (0 for small lists) (field 0) - Phase 4
            ir.IntType(64),   # len - total element count (field 1)
            ir.IntType(64),   # depth - tree depth (0 = tail only) (field 2) - Phase 4: widened to i64
            ir.IntType(64),   # tail_handle - rightmost leaf array handle (field 3) - Phase 4
            ir.IntType(64),   # tail_len - elements in tail (1-32) (field 4) - Phase 4: widened to i64
            ir.IntType(64),   # elem_size (field 5)
        )
        
        # Create list helper functions
        self._list = ListGenerator(self)
        self._list.create_list_helpers()

        # Create String type and helpers
        self._strings = StringGenerator(self)
        self._strings.create_string_type()

        # Create HAMT, Map, and Set types and helpers
        self._hamt = HamtGenerator(self)
        self._hamt.create_map_type()
        self._hamt.create_set_type()

        # Create JSON type and helpers
        self._json = JsonGenerator(self)
        self._json.create_json_type()

        # Create Array type and helpers (dense, contiguous collection)
        # struct Array { i64 owner_handle, i64 offset, i64 len, i64 cap, i64 elem_size }
        # Phase 4: Owner is now an i64 handle (pointer stored as integer for GC handles)
        # Offset enables slice views without data copying.
        # NOTE: No refcount - GC handles memory, COW done via always-copy semantics
        self.array_struct = ir.global_context.get_identified_type("struct.Array")
        self.array_struct.set_body(
            ir.IntType(64),  # owner_handle (field 0) - handle to data buffer (Phase 4)
            ir.IntType(64),  # offset (field 1) - byte offset into owner's data
            ir.IntType(64),  # len (field 2) - element count
            ir.IntType(64),  # cap (field 3) - capacity
            ir.IntType(64),  # elem_size (field 4) - element size in bytes
        )
        self._create_array_helpers()

        # NOTE: Conversion helpers (_list_to_array, _array_to_list, etc.)
        # are inline methods, not separate function declarations

        # Create atomic_ref type and helpers
        self._create_atomic_ref_type()

        # Create Result type and helpers
        # struct.Result { i64 tag, i64 ok_value, i64 err_value }
        # tag: 0 = Ok, 1 = Err
        self.result_struct = ir.global_context.get_identified_type("struct.Result")
        self.result_struct.set_body(
            ir.IntType(64),  # tag: 0 = Ok, 1 = Err
            ir.IntType(64),  # ok_value (stored as i64, may be pointer)
            ir.IntType(64),  # err_value (stored as i64, may be pointer)
        )
        self._create_result_helpers()

        # Register Result as an enum-like type with Ok and Err variants
        # This enables pattern matching: case Ok(v): / case Err(e):
        self.enum_variants["Result"] = {
            "Ok": (0, [("value", PrimitiveType("int"))]),   # tag 0
            "Err": (1, [("error", PrimitiveType("string"))]),  # tag 1
        }

        # Create built-in posix platform type
        self._posix = PosixGenerator(self)
        self._posix.create_posix_type()

        # Matrix registry for tracking declared matrices
        self.matrix_decls: Dict[str, 'MatrixDecl'] = {}  # name -> MatrixDecl
        self.matrix_structs: Dict[str, ir.Type] = {}  # name -> LLVM struct type
        
        # Current matrix context for cell expressions
        self.current_matrix: Optional[str] = None
        self.current_cell_x: Optional[ir.Value] = None
        self.current_cell_y: Optional[ir.Value] = None

    # List helpers moved to codegen/list.py - ListGenerator class
    # HAMT/Map/Set helpers moved to codegen/hamt.py - HamtGenerator class

    def _create_array_helpers(self):
        """Create helper functions for Array operations.

        Array is a dense, contiguous collection with value semantics.
        All 'mutation' operations return a new array.
        """
        array_ptr = self.array_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # array_new(cap: i64, elem_size: i64) -> Array*
        array_new_ty = ir.FunctionType(array_ptr, [i64, i64])
        self.array_new = ir.Function(self.module, array_new_ty, name="coex_array_new")

        # array_get(arr: Array*, index: i64) -> i8*
        array_get_ty = ir.FunctionType(i8_ptr, [array_ptr, i64])
        self.array_get = ir.Function(self.module, array_get_ty, name="coex_array_get")

        # array_set(arr: Array*, index: i64, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element at index replaced
        array_set_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i8_ptr, i64])
        self.array_set = ir.Function(self.module, array_set_ty, name="coex_array_set")

        # array_append(arr: Array*, value: i8*, elem_size: i64) -> Array*
        # Returns a NEW array with the element appended
        array_append_ty = ir.FunctionType(array_ptr, [array_ptr, i8_ptr, i64])
        self.array_append = ir.Function(self.module, array_append_ty, name="coex_array_append")

        # array_len(arr: Array*) -> i64
        array_len_ty = ir.FunctionType(i64, [array_ptr])
        self.array_len = ir.Function(self.module, array_len_ty, name="coex_array_len")

        # array_size(arr: Array*) -> i64 (total memory footprint)
        array_size_ty = ir.FunctionType(i64, [array_ptr])
        self.array_size = ir.Function(self.module, array_size_ty, name="coex_array_size")

        # array_copy(arr: Array*) -> Array* (deep copy for value semantics)
        array_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        self.array_copy = ir.Function(self.module, array_copy_ty, name="coex_array_copy")

        # array_deep_copy(arr: Array*) -> Array* (creates independent copy with new buffer)
        array_deep_copy_ty = ir.FunctionType(array_ptr, [array_ptr])
        self.array_deep_copy = ir.Function(self.module, array_deep_copy_ty, name="coex_array_deep_copy")

        # array_getrange(arr: Array*, start: i64, end: i64) -> Array*
        # Returns a VIEW (not a copy) of elements [start, end)
        array_getrange_ty = ir.FunctionType(array_ptr, [array_ptr, i64, i64])
        self.array_getrange = ir.Function(self.module, array_getrange_ty, name="coex_array_getrange")

        # Implement all functions
        self._implement_array_new()
        self._implement_array_get()
        self._implement_array_set()
        self._implement_array_append()
        self._implement_array_len()
        self._implement_array_size()
        self._implement_array_copy()
        self._implement_array_deep_copy()
        self._implement_array_getrange()
        self._register_array_methods()

    def _implement_array_new(self):
        """Implement array_new: allocate a new array with given capacity and element size.

        Struct layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }
        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_new
        func.args[0].name = "cap"
        func.args[1].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        cap = func.args[0]
        elem_size = func.args[1]

        # Allocate Array struct (40 bytes: 5 x 8-byte fields)
        array_size_const = ir.Constant(ir.IntType(64), 40)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_ARRAY)
        raw_ptr = self.gc.alloc_with_deref(builder, array_size_const, type_id)
        array_ptr = builder.bitcast(raw_ptr, self.array_struct.as_pointer())

        # Allocate data buffer first: cap * elem_size
        data_size = builder.mul(cap, elem_size)
        array_data_type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_ARRAY_DATA)
        data_ptr = self.gc.alloc_with_deref(builder, data_size, array_data_type_id)

        # Initialize fields
        # owner_handle (field 0) - Phase 4: store as i64 handle
        owner_field_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.ptrtoint(data_ptr, ir.IntType(64))
        builder.store(owner_handle, owner_field_ptr)

        # offset = 0 (field 1) - new arrays own their data from the start
        offset_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), offset_ptr)

        # len = 0 (field 2)
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_ptr)

        # cap (field 3)
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        builder.store(cap, cap_ptr)

        # elem_size (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        builder.ret(array_ptr)

    def _implement_array_get(self):
        """Implement array_get: return pointer to element at index.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_get
        func.args[0].name = "arr"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        index = func.args[1]

        # Get elem_size (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Compute data pointer: owner + offset (Phase 4: owner is i64 handle)
        owner_handle_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        base_offset = builder.load(offset_ptr)
        data = builder.gep(owner, [base_offset])

        # Calculate element offset: index * elem_size
        elem_offset = builder.mul(index, elem_size)
        result = builder.gep(data, [elem_offset])

        builder.ret(result)

    def _implement_array_set(self):
        """Implement array_set: return a NEW array with element at index replaced.

        This implements value semantics - always creates a new array copy.
        No COW optimization - GC handles memory reclamation.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_set
        func.args[0].name = "arr"
        func.args[1].name = "index"
        func.args[2].name = "value"
        func.args[3].name = "elem_size"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        old_arr = func.args[0]
        index = func.args[1]
        value_ptr = func.args[2]
        elem_size = func.args[3]

        # Get old array's len (field 2) and cap (field 3)
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        old_cap_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        old_cap = builder.load(old_cap_ptr)

        # Create new array with same capacity (array_new sets offset=0)
        new_arr = builder.call(self.array_new, [old_cap, elem_size])

        # Set new array's len to old len (field 2)
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(old_len, new_len_ptr)

        # Compute old data pointer: owner + offset (Phase 4: owner is i64 handle)
        old_owner_handle_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_owner_handle = builder.load(old_owner_handle_ptr)
        old_owner = builder.inttoptr(old_owner_handle, ir.IntType(8).as_pointer())
        old_offset_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_offset = builder.load(old_offset_ptr)
        old_data = builder.gep(old_owner, [old_offset])

        # New array has offset=0, so just load owner (Phase 4: owner is i64 handle)
        new_data_handle_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        new_data_handle = builder.load(new_data_handle_ptr)
        new_data = builder.inttoptr(new_data_handle, ir.IntType(8).as_pointer())

        copy_size = builder.mul(old_len, elem_size)
        builder.call(self.memcpy, [new_data, old_data, copy_size])

        # Overwrite the element at index
        elem_offset = builder.mul(index, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(self.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_append(self):
        """Implement array_append: return a NEW array with element appended.

        This implements value semantics - always creates a new array copy.
        No COW optimization - GC handles memory reclamation.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_append
        func.args[0].name = "arr"
        func.args[1].name = "value"
        func.args[2].name = "elem_size"

        entry = func.append_basic_block("entry")

        builder = ir.IRBuilder(entry)

        old_arr = func.args[0]
        value_ptr = func.args[1]
        elem_size = func.args[2]

        # Get old array's len (field 2)
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        # New capacity = old_len + 1 (always create new array)
        new_cap = builder.add(old_len, ir.Constant(ir.IntType(64), 1))

        # Create new array (array_new sets offset=0)
        new_arr = builder.call(self.array_new, [new_cap, elem_size])

        # Set new array's len = old_len + 1 (field 2)
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(new_cap, new_len_ptr)

        # Compute old data pointer: owner + offset (Phase 4: owner is i64 handle)
        old_owner_handle_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_owner_handle = builder.load(old_owner_handle_ptr)
        old_owner = builder.inttoptr(old_owner_handle, ir.IntType(8).as_pointer())
        old_offset_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_offset = builder.load(old_offset_ptr)
        old_data = builder.gep(old_owner, [old_offset])

        # New array has offset=0, so just load owner (Phase 4: owner is i64 handle)
        new_data_handle_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        new_data_handle = builder.load(new_data_handle_ptr)
        new_data = builder.inttoptr(new_data_handle, ir.IntType(8).as_pointer())

        copy_size = builder.mul(old_len, elem_size)
        builder.call(self.memcpy, [new_data, old_data, copy_size])

        # Append the new element
        elem_offset = builder.mul(old_len, elem_size)
        dest = builder.gep(new_data, [elem_offset])
        builder.call(self.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_len(self):
        """Implement array_len: return array length.

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_len
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get len field (field 2)
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        length = builder.load(len_ptr)

        builder.ret(length)

    def _implement_array_size(self):
        """Implement array_size: return total memory footprint in bytes.

        Size = 40 (header, 5 x 8-byte fields) + cap * elem_size (data array)

        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4
        """
        func = self.array_size
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get cap field (field 3)
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Get elem_size field (field 4)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Size = 40 (header) + cap * elem_size
        data_size = builder.mul(cap, elem_size)
        total_size = builder.add(ir.Constant(ir.IntType(64), 40), data_size)

        builder.ret(total_size)

    def _implement_array_copy(self):
        """Implement array_copy: return same pointer for structural sharing.

        Array layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }
        Field indices: owner=0, offset=1, len=2, cap=3, elem_size=4

        With GC-managed memory, copying is just pointer sharing.
        GC keeps shared arrays alive; mutation creates new arrays.
        """
        func = self.array_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]

        # Just return the same pointer - GC handles memory management
        builder.ret(src)

    def _implement_array_deep_copy(self):
        """Create an independent copy of an array with its own data buffer.

        This is used by the = operator to ensure slice views become independent copies.
        Layout: { i8* owner, i64 offset, i64 len, i64 cap, i64 elem_size }

        1. Allocate new Array descriptor (40 bytes)
        2. Compute source data size: len * elem_size
        3. Allocate new data buffer
        4. Copy bytes from (source.owner + source.offset) to new buffer
        5. Set new descriptor: owner=new_buffer, offset=0, len=source.len, cap=source.len, elem_size=source.elem_size
        """
        func = self.array_deep_copy
        func.args[0].name = "src"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        src = func.args[0]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Load source fields (Phase 4: owner is i64 handle)
        src_owner_handle_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        src_owner_handle = builder.load(src_owner_handle_ptr)
        src_owner = builder.inttoptr(src_owner_handle, ir.IntType(8).as_pointer())

        src_offset_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        src_len = builder.load(src_len_ptr)

        src_elem_size_ptr = builder.gep(src, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        src_elem_size = builder.load(src_elem_size_ptr)

        # Compute source data pointer: owner + offset
        src_data = builder.gep(src_owner, [src_offset])

        # Compute data size: len * elem_size
        data_size = builder.mul(src_len, src_elem_size)

        # Allocate new data buffer
        type_id = ir.Constant(i32, self.gc.TYPE_ARRAY_DATA)
        new_data = self.gc.alloc_with_deref(builder, data_size, type_id)

        # Copy data from source to new buffer
        builder.call(self.memcpy, [new_data, src_data, data_size])

        # Allocate new Array descriptor (40 bytes)
        struct_size = ir.Constant(i64, 40)
        array_type_id = ir.Constant(i32, self.gc.TYPE_ARRAY)
        raw_ptr = self.gc.alloc_with_deref(builder, struct_size, array_type_id)
        array_ptr = builder.bitcast(raw_ptr, self.array_struct.as_pointer())

        # Store owner = new_data (Phase 4: owner is i64 handle)
        new_owner_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        new_owner_handle = builder.ptrtoint(new_data, i64)
        builder.store(new_owner_handle, new_owner_ptr)

        # Store offset = 0 (fresh allocation, not a view)
        new_offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), new_offset_ptr)

        # Store len = source.len
        new_len_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(src_len, new_len_ptr)

        # Store cap = source.len (copy has no extra capacity)
        new_cap_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(src_len, new_cap_ptr)

        # Store elem_size = source.elem_size
        new_elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(src_elem_size, new_elem_size_ptr)

        builder.ret(array_ptr)

    def _implement_array_getrange(self):
        """Create a slice VIEW of an array (zero-copy).

        Returns a new Array descriptor that shares the parent's data buffer.
        Layout: { i64 owner_handle, i64 offset, i64 len, i64 cap, i64 elem_size }
        Phase 4: owner is now i64 handle (copied directly for shared ownership).

        The slice's offset = parent.offset + (start * elem_size)
        The slice's len = end - start
        The slice shares the same owner handle (zero-copy).
        """
        func = self.array_getrange
        func.args[0].name = "arr"
        func.args[1].name = "start"
        func.args[2].name = "end"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        arr = func.args[0]
        start = func.args[1]
        end = func.args[2]
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        # Load source fields (Phase 4: owner is i64 handle - copy directly for slice view)
        src_owner_handle_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        src_owner_handle = builder.load(src_owner_handle_ptr)

        src_offset_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        src_offset = builder.load(src_offset_ptr)

        src_len_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        src_len = builder.load(src_len_ptr)

        src_elem_size_ptr = builder.gep(arr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        src_elem_size = builder.load(src_elem_size_ptr)

        # Clamp start to [0, len]
        start_neg = builder.icmp_signed("<", start, zero)
        start_over = builder.icmp_signed(">", start, src_len)
        start_clamped = builder.select(start_neg, zero, builder.select(start_over, src_len, start))

        # Clamp end to [start, len]
        end_under = builder.icmp_signed("<", end, start_clamped)
        end_over = builder.icmp_signed(">", end, src_len)
        end_clamped = builder.select(end_under, start_clamped, builder.select(end_over, src_len, end))

        # Calculate new length
        new_len = builder.sub(end_clamped, start_clamped)

        # Calculate new offset: src_offset + (start * elem_size)
        start_bytes = builder.mul(start_clamped, src_elem_size)
        new_offset = builder.add(src_offset, start_bytes)

        # Allocate new Array descriptor (40 bytes) - NO data copy!
        struct_size = ir.Constant(i64, 40)
        type_id = ir.Constant(i32, self.gc.TYPE_ARRAY)
        raw_ptr = self.gc.alloc_with_deref(builder, struct_size, type_id)
        array_ptr = builder.bitcast(raw_ptr, self.array_struct.as_pointer())

        # Store owner handle (shared with source - this is the slice view!)
        new_owner_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(src_owner_handle, new_owner_ptr)

        # Store new offset
        new_offset_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(new_offset, new_offset_ptr)

        # Store new len
        new_len_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        builder.store(new_len, new_len_ptr)

        # Store cap = len (slices have no extra capacity)
        new_cap_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        builder.store(new_len, new_cap_ptr)

        # Store elem_size (same as source)
        new_elem_size_ptr = builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        builder.store(src_elem_size, new_elem_size_ptr)

        builder.ret(array_ptr)

    def _register_array_methods(self):
        """Register Array as a type with methods."""
        self.type_registry["Array"] = self.array_struct
        self.type_fields["Array"] = []  # Internal structure, not user-accessible fields

        self.type_methods["Array"] = {
            "get": "coex_array_get",
            "len": "coex_array_len",
            "size": "coex_array_size",
            "getrange": "coex_array_getrange",
            # "set" and "append" handled specially (need alloca + return new array)
        }

        self.functions["coex_array_new"] = self.array_new
        self.functions["coex_array_get"] = self.array_get
        self.functions["coex_array_set"] = self.array_set
        self.functions["coex_array_append"] = self.array_append
        self.functions["coex_array_len"] = self.array_len
        self.functions["coex_array_size"] = self.array_size
        self.functions["coex_array_copy"] = self.array_copy
        self.functions["coex_array_getrange"] = self.array_getrange

    def _list_to_array(self, list_ptr: ir.Value) -> ir.Value:
        """Convert a List to an Array (List.packed() -> Array).

        Creates a new Array with the same elements as the List.
        For Persistent Vector List, we iterate using list_get since
        the data is stored in a tree structure, not contiguously.
        """
        func = self.builder.function
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get List length
        list_len = self.builder.call(self.list_len, [list_ptr])

        # Get List elem_size (field 5 in PV structure)
        elem_size_ptr = self.builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = self.builder.load(elem_size_ptr)

        # Create new Array with same capacity as List length
        array_ptr = self.builder.call(self.array_new, [list_len, elem_size])

        # Set Array len = list_len (field 2 in Array layout)
        array_len_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        self.builder.store(list_len, array_len_ptr)

        # Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.builder.load(array_owner_handle_ptr)
        array_owner = self.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.builder.load(array_offset_ptr)
        array_data = self.builder.gep(array_owner, [array_offset])

        # For Persistent Vector List, we can't just memcpy - we need to iterate
        # through the list using list_get since data may be in tree structure.
        # Loop through each element and copy to array

        idx_alloca = self.builder.alloca(i64, name="list_to_arr_idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("list_to_arr_cond")
        body_block = func.append_basic_block("list_to_arr_body")
        end_block = func.append_basic_block("list_to_arr_end")

        self.builder.branch(cond_block)

        # Condition: idx < list_len
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, list_len)
        self.builder.cbranch(cond, body_block, end_block)

        # Body: copy element from list to array
        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)

        # Get element from list
        elem_ptr = self.builder.call(self.list_get, [list_ptr, idx])

        # Calculate destination in array
        offset = self.builder.mul(idx, elem_size)
        dest_ptr = self.builder.gep(array_data, [offset])

        # Copy element
        self.builder.call(self.memcpy, [dest_ptr, elem_ptr, elem_size])

        # Increment index
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        # End
        self.builder.position_at_end(end_block)

        return array_ptr

    def _set_to_array(self, set_ptr: ir.Value) -> ir.Value:
        """Convert a Set to an Array (Set.packed() -> Array).

        Creates a new Array with the elements from the HAMT-based Set.
        Uses set_to_list to collect keys, then copies to array.
        """
        func = self.builder.function
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get Set len (number of elements)
        set_len = self.builder.call(self.set_len, [set_ptr])

        # Create Array with capacity = set_len, elem_size = 8 (i64 keys)
        elem_size = ir.Constant(i64, 8)
        array_ptr = self.builder.call(self.array_new, [set_len, elem_size])

        # Get list of keys from set using set_to_list (HAMT-based)
        key_list = self.builder.call(self.set_to_list, [set_ptr])

        # Get list data pointer (field 3 in List struct) - Phase 4: handle
        list_data_handle_ptr = self.builder.gep(key_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        list_data_handle = self.builder.load(list_data_handle_ptr)
        list_data = self.builder.inttoptr(list_data_handle, i8_ptr)

        # Get array data pointer: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.builder.load(array_owner_handle_ptr)
        array_owner = self.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.builder.load(array_offset_ptr)
        array_data = self.builder.gep(array_owner, [array_offset])

        # Copy list data to array: len * 8 bytes
        copy_size = self.builder.mul(set_len, elem_size)
        self.builder.call(self.memcpy, [array_data, list_data, copy_size])

        # Set array len (field 2 in Array layout)
        arr_len_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        self.builder.store(set_len, arr_len_ptr)

        return array_ptr

    def _array_to_list(self, array_ptr: ir.Value) -> ir.Value:
        """Convert an Array to a List (Array.unpacked() -> List).

        Creates a new List with the same elements as the Array.
        For Persistent Vector List, we iterate through the array and
        append each element to build the list.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.builder.function

        # Get Array length
        array_len = self.builder.call(self.array_len, [array_ptr])

        # Get Array elem_size (field 4 in Array layout)
        elem_size_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        elem_size = self.builder.load(elem_size_ptr)

        # Get Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.builder.load(array_owner_handle_ptr)
        array_owner = self.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.builder.load(array_offset_ptr)
        array_data = self.builder.gep(array_owner, [array_offset])

        # Create new empty List with same elem_size
        list_ptr = self.builder.call(self.list_new, [elem_size])

        # Store list_ptr in alloca since list_append returns new list
        list_alloca = self.builder.alloca(self.list_struct.as_pointer(), name="arr_to_list")
        self.builder.store(list_ptr, list_alloca)

        # Loop through array elements and append to list
        idx_alloca = self.builder.alloca(i64, name="arr_to_list_idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("arr_to_list_cond")
        body_block = func.append_basic_block("arr_to_list_body")
        end_block = func.append_basic_block("arr_to_list_end")

        self.builder.branch(cond_block)

        # Condition: idx < array_len
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, array_len)
        self.builder.cbranch(cond, body_block, end_block)

        # Body: get element from array and append to list
        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)

        # Calculate source address in array
        offset = self.builder.mul(idx, elem_size)
        elem_ptr = self.builder.gep(array_data, [offset])

        # Append element to list
        current_list = self.builder.load(list_alloca)
        new_list = self.builder.call(self.list_append, [current_list, elem_ptr, elem_size])
        self.builder.store(new_list, list_alloca)

        # Increment index
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        # End
        self.builder.position_at_end(end_block)
        return self.builder.load(list_alloca)

    def _array_to_set(self, array_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Convert an Array to a Set (Array.toSet() -> Set).

        Creates a new Set with the same elements as the Array.
        Duplicate elements in the Array are deduplicated.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.builder.function

        # Get Array length
        array_len = self.builder.call(self.array_len, [array_ptr])

        # Get Array elem_size (field 4 in Array layout)
        elem_size_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        elem_size = self.builder.load(elem_size_ptr)

        # Get Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.builder.load(array_owner_handle_ptr)
        array_owner = self.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.builder.load(array_offset_ptr)
        array_data = self.builder.gep(array_owner, [array_offset])

        # Create new empty Set with flags indicating element type
        flags = self.MAP_FLAG_KEY_IS_PTR if elem_is_ptr else 0
        set_ptr = self.builder.call(self.set_new, [ir.Constant(i64, flags)])

        # Store set_ptr in alloca since set_add returns new set
        set_alloca = self.builder.alloca(self.set_struct.as_pointer(), name="arr_to_set")
        self.builder.store(set_ptr, set_alloca)

        # Loop through array elements and add to set
        idx_alloca = self.builder.alloca(i64, name="arr_to_set_idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("arr_to_set_cond")
        body_block = func.append_basic_block("arr_to_set_body")
        end_block = func.append_basic_block("arr_to_set_end")

        self.builder.branch(cond_block)

        # Condition: idx < array_len
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, array_len)
        self.builder.cbranch(cond, body_block, end_block)

        # Body: get element from array and add to set
        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)

        # Calculate source address in array and load value
        offset = self.builder.mul(idx, elem_size)
        elem_ptr = self.builder.gep(array_data, [offset])
        # Load element as i64 (assuming elements are stored as i64)
        typed_ptr = self.builder.bitcast(elem_ptr, i64.as_pointer())
        elem_val = self.builder.load(typed_ptr)

        # Add element to set (set_add returns new set)
        current_set = self.builder.load(set_alloca)
        new_set = self.builder.call(self.set_add, [current_set, elem_val])
        self.builder.store(new_set, set_alloca)

        # Increment index
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        # End
        self.builder.position_at_end(end_block)
        return self.builder.load(set_alloca)

    def _list_to_set(self, list_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Convert a List to a Set (List.to_set() -> Set).

        Creates a new Set with the same elements as the List.
        Duplicate elements in the List are deduplicated.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.builder.function

        # Get List length
        list_len = self.builder.call(self.list_len, [list_ptr])

        # Create new empty Set with flags indicating element type
        flags = self.MAP_FLAG_KEY_IS_PTR if elem_is_ptr else 0
        set_ptr = self.builder.call(self.set_new, [ir.Constant(i64, flags)])

        # Store set_ptr in alloca since set_add returns new set
        set_alloca = self.builder.alloca(self.set_struct.as_pointer(), name="list_to_set")
        self.builder.store(set_ptr, set_alloca)

        # Loop through list elements and add to set
        idx_alloca = self.builder.alloca(i64, name="list_to_set_idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("list_to_set_cond")
        body_block = func.append_basic_block("list_to_set_body")
        end_block = func.append_basic_block("list_to_set_end")

        self.builder.branch(cond_block)

        # Condition: idx < list_len
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, list_len)
        self.builder.cbranch(cond, body_block, end_block)

        # Body: get element from list and add to set
        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)

        # Get element from list using list_get
        elem_ptr = self.builder.call(self.list_get, [list_ptr, idx])
        # Load element as i64 (assuming elements are stored as i64)
        typed_ptr = self.builder.bitcast(elem_ptr, i64.as_pointer())
        elem_val = self.builder.load(typed_ptr)

        # Add element to set (set_add returns new set)
        current_set = self.builder.load(set_alloca)
        new_set = self.builder.call(self.set_add, [current_set, elem_val])
        self.builder.store(new_set, set_alloca)

        # Increment index
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        # End
        self.builder.position_at_end(end_block)
        return self.builder.load(set_alloca)

    def _try_implicit_collection_conversion(self, value: ir.Value, target_type: Type, value_type: Type = None) -> Tuple[ir.Value, bool]:
        """Try to implicitly convert between collection types.

        Returns (converted_value, was_converted) where was_converted is True if
        an implicit conversion was performed (and a warning should be emitted).

        Supported conversions:
        - List<T> -> Array<T> (via .packed())
        - Array<T> -> List<T> (via .unpacked())
        - List<T> -> Set<T> (via .to_set(), deduplicates)
        - Set<T> -> List<T> (via .unpacked())
        - Set<T> -> Array<T> (via .packed())
        - Array<T> -> Set<T> (via .toSet(), deduplicates)
        """
        if not isinstance(value.type, ir.PointerType):
            return value, False

        pointee = value.type.pointee
        if not hasattr(pointee, 'name'):
            return value, False

        source_struct = pointee.name  # e.g., "struct.List"

        # Determine target collection type
        if isinstance(target_type, ListType):
            target_struct = "struct.List"
        elif isinstance(target_type, ArrayType):
            target_struct = "struct.Array"
        elif isinstance(target_type, SetType):
            target_struct = "struct.Set"
        else:
            return value, False

        # No conversion needed if types match
        if source_struct == target_struct:
            return value, False

        # Perform conversion based on source -> target
        if source_struct == "struct.List" and target_struct == "struct.Array":
            return self._list_to_array(value), True
        elif source_struct == "struct.Array" and target_struct == "struct.List":
            return self._array_to_list(value), True
        elif source_struct == "struct.List" and target_struct == "struct.Set":
            return self._list_to_set(value), True
        elif source_struct == "struct.Set" and target_struct == "struct.List":
            # set_to_list is available via coex_set_to_list
            return self.builder.call(self.set_to_list, [value]), True
        elif source_struct == "struct.Set" and target_struct == "struct.Array":
            return self._set_to_array(value), True
        elif source_struct == "struct.Array" and target_struct == "struct.Set":
            return self._array_to_set(value), True

        return value, False

    def _get_conversion_warning_message(self, source_struct: str, target_struct: str) -> str:
        """Get the warning message for an implicit collection conversion."""
        source_name = source_struct.replace("struct.", "")
        target_name = target_struct.replace("struct.", "")

        # Map struct names to user-friendly names
        names = {"List": "List", "Array": "Array", "Set": "Set"}
        source = names.get(source_name, source_name)
        target = names.get(target_name, target_name)

        if source == "List" and target == "Array":
            return f"Implicit conversion from {source} to {target} (O(n) copy to contiguous memory)"
        elif source == "Array" and target == "List":
            return f"Implicit conversion from {source} to {target} (O(n) copy to persistent vector)"
        elif source in ("List", "Array") and target == "Set":
            return f"Implicit conversion from {source} to {target} (O(n) with deduplication)"
        elif source == "Set" and target in ("List", "Array"):
            return f"Implicit conversion from {source} to {target} (O(n) copy)"
        else:
            return f"Implicit conversion from {source} to {target}"

    def _is_primitive_coex_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is a primitive (int, float, bool, byte, char)."""
        if isinstance(coex_type, PrimitiveType):
            return coex_type.name in ("int", "float", "bool", "byte", "char")
        return False

    def _needs_parameter_copy(self, coex_type: Type) -> bool:
        """Check if a parameter type needs to be copied on function entry.

        With immutable heap semantics, function parameters never need copying.
        All heap types (collections, strings, UDTs) are immutable:
        - Collections: mutation operations return new objects
        - Strings: immutable
        - UDTs: field assignment creates new struct (copy-on-write)

        Sharing references is semantically equivalent to copying because no
        binding can observe mutations through another binding.
        """
        return False

    def _is_heap_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is heap-allocated and needs GC root tracking.

        Heap types that need tracking:
        - Collections (List, Set, Map, Array)
        - String (heap-allocated)
        - User-defined types (all heap-allocated)

        NOT tracked (stack types):
        - int, float, bool, byte, char
        - Tuples of primitives (value types)
        """
        if coex_type is None:
            return False
        if isinstance(coex_type, PrimitiveType):
            # Primitives are stack-allocated
            if coex_type.name in ("int", "float", "bool", "byte", "char"):
                return False
            # string is heap-allocated
            if coex_type.name == "string":
                return True
        if isinstance(coex_type, (ListType, SetType, MapType, ArrayType)):
            return True
        if isinstance(coex_type, NamedType):
            # String is heap-allocated
            if coex_type.name == "string":
                return True
            # User-defined types are heap-allocated
            if coex_type.name in self.type_fields:
                return True
            # Generic types that expand to collections
            if coex_type.type_args:
                return True
        if isinstance(coex_type, TupleType):
            # Tuples are stack values, but we don't track them as roots
            # (their contents are copied at assignment)
            return False
        return False

    def _compute_map_flags(self, key_type: Type, value_type: Type) -> int:
        """Compute the GC flags for a Map based on key and value types.

        Returns an integer with:
        - bit 0 set if key is a heap pointer
        - bit 1 set if value is a heap pointer
        """
        flags = 0
        if self._is_heap_type(key_type):
            flags |= self.MAP_FLAG_KEY_IS_PTR
        if self._is_heap_type(value_type):
            flags |= self.MAP_FLAG_VALUE_IS_PTR
        return flags

    def _compute_set_flags(self, elem_type: Type) -> int:
        """Compute the GC flags for a Set based on element type.

        Returns an integer with:
        - bit 0 set if element is a heap pointer
        """
        flags = 0
        if self._is_heap_type(elem_type):
            flags |= self.MAP_FLAG_KEY_IS_PTR  # Reuse same flag for set elements
        return flags

    def _is_collection_coex_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is a collection (List, Set, Map, Array, String)."""
        if isinstance(coex_type, (ListType, SetType, MapType, ArrayType)):
            return True
        if isinstance(coex_type, NamedType) and coex_type.name == "string":
            return True
        return False

    def _get_receiver_type(self, expr: Expr) -> Optional[Type]:
        """Get the Coex type of a receiver expression (handles chained method calls).

        For expressions like a.set(0, x).set(1, y):
        - The outermost call has callee.object = a.set(0, x) (another CallExpr)
        - We recursively find the innermost Identifier to get its type
        """
        if isinstance(expr, Identifier):
            # Direct variable reference
            if expr.name in self.var_coex_types:
                return self.var_coex_types[expr.name]
            return None
        elif isinstance(expr, CallExpr):
            # Chained method call: recurse into the callee's object
            if isinstance(expr.callee, MemberExpr):
                return self._get_receiver_type(expr.callee.object)
        elif isinstance(expr, MemberExpr):
            # Member expression without call
            return self._get_receiver_type(expr.object)
        return None

    def _needs_deep_copy(self, coex_type: Type) -> bool:
        """Check if a type needs deep copy (has nested collections)."""
        if isinstance(coex_type, ListType):
            return self._is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, ArrayType):
            return self._is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, SetType):
            return self._is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, MapType):
            return self._is_collection_coex_type(coex_type.value_type)
        if isinstance(coex_type, NamedType) and coex_type.name in self.type_fields:
            # Check if user type has any collection fields
            for field_name, field_type in self.type_fields[coex_type.name]:
                if self._is_collection_coex_type(field_type):
                    return True
        return False

    def _generate_move_or_eager_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Generate code for := (move/eager assign) semantics.

        With GC-managed memory (no refcounting), this is simplified:
        - For arrays: just return the pointer; array_set/append create copies on mutation
        - For strings: just return the pointer; strings are immutable
        - For collections: return pointer; mutation creates new structures

        The copy-on-write happens at mutation time, not at assignment time.
        """
        # All types: just return the value
        # GC handles memory; mutation operations create new copies when needed
        return value

    def _generate_deep_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Generate code to 'deep-copy' a value based on its Coex type.

        With immutable heap semantics, heap-allocated values don't need copying.
        Sharing references is semantically equivalent to copying because no
        binding can observe mutations through another binding:
        - Collections: mutation operations return new objects
        - Strings: immutable
        - UDTs: field assignment creates new struct (copy-on-write)

        This function returns value unchanged for all types.
        """
        # All types: return value unchanged
        # - Primitives are stack-allocated value types
        # - Heap types are immutable - sharing is equivalent to copying
        return value

    def _generate_list_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy a list (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def _generate_set_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy a set (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def _generate_map_deep_copy(self, src: ir.Value, key_type: Type, value_type: Type) -> ir.Value:
        """Deep copy a map (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def _generate_array_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy an array (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def _generate_type_deep_copy(self, src: ir.Value, coex_type: NamedType) -> ir.Value:
        """Deep copy a user-defined type (identity function with immutable heap semantics).

        With copy-on-write field assignment, UDTs are now immutable like collections.
        Sharing the reference is semantically equivalent to copying.
        """
        return src

    # ========================================================================
    # Atomic Reference Type Implementation
    # ========================================================================
    
    def _create_atomic_ref_type(self):
        """Create the atomic_ref<T> type and helper functions.
        
        atomic_ref provides atomic operations on references to heap-allocated values.
        All operations use sequentially-consistent memory ordering.
        
        AtomicRef layout:
            i64 value  - Pointer stored as i64 (nil = 0)
        
        Operations:
            new(value) -> atomic_ref     - Create with initial value
            load() -> T?                 - Atomic load
            store(value: T?)             - Atomic store
            compare_and_swap(expected, new) -> bool  - Atomic CAS
            swap(new) -> T?              - Atomic exchange
        """
        # AtomicRef struct: { i64 value }
        self.atomic_ref_struct = ir.global_context.get_identified_type("struct.atomic_ref")
        self.atomic_ref_struct.set_body(
            ir.IntType(64)  # value (pointer as i64, nil = 0)
        )
        
        atomic_ref_ptr = self.atomic_ref_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        
        # atomic_ref_new(initial_value: i64) -> AtomicRef*
        atomic_ref_new_ty = ir.FunctionType(atomic_ref_ptr, [i64])
        self.atomic_ref_new = ir.Function(self.module, atomic_ref_new_ty, name="coex_atomic_ref_new")
        
        # atomic_ref_load(ref: AtomicRef*) -> i64
        atomic_ref_load_ty = ir.FunctionType(i64, [atomic_ref_ptr])
        self.atomic_ref_load = ir.Function(self.module, atomic_ref_load_ty, name="coex_atomic_ref_load")
        
        # atomic_ref_store(ref: AtomicRef*, value: i64)
        atomic_ref_store_ty = ir.FunctionType(ir.VoidType(), [atomic_ref_ptr, i64])
        self.atomic_ref_store = ir.Function(self.module, atomic_ref_store_ty, name="coex_atomic_ref_store")
        
        # atomic_ref_compare_and_swap(ref: AtomicRef*, expected: i64, new: i64) -> bool
        atomic_ref_cas_ty = ir.FunctionType(i1, [atomic_ref_ptr, i64, i64])
        self.atomic_ref_cas = ir.Function(self.module, atomic_ref_cas_ty, name="coex_atomic_ref_cas")
        
        # atomic_ref_swap(ref: AtomicRef*, new: i64) -> i64
        atomic_ref_swap_ty = ir.FunctionType(i64, [atomic_ref_ptr, i64])
        self.atomic_ref_swap = ir.Function(self.module, atomic_ref_swap_ty, name="coex_atomic_ref_swap")
        
        # Implement all atomic_ref functions
        self._implement_atomic_ref_new()
        self._implement_atomic_ref_load()
        self._implement_atomic_ref_store()
        self._implement_atomic_ref_cas()
        self._implement_atomic_ref_swap()
        self._register_atomic_ref_methods()
    
    def _implement_atomic_ref_new(self):
        """Implement atomic_ref_new: allocate and initialize an atomic reference."""
        func = self.atomic_ref_new
        func.args[0].name = "initial"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        initial = func.args[0]
        
        # Allocate AtomicRef struct (8 bytes) via GC
        ref_size = ir.Constant(ir.IntType(64), 8)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_UNKNOWN)
        raw_ptr = self.gc.alloc_with_deref(builder, ref_size, type_id)
        ref_ptr = builder.bitcast(raw_ptr, self.atomic_ref_struct.as_pointer())
        
        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        # Store initial value atomically (for consistency, though not strictly necessary at creation)
        builder.store_atomic(initial, value_field, ordering='seq_cst', align=8)
        
        builder.ret(ref_ptr)
    
    def _implement_atomic_ref_load(self):
        """Implement atomic_ref_load: atomically read the reference value."""
        func = self.atomic_ref_load
        func.args[0].name = "ref"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        ref_ptr = func.args[0]
        
        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        # Atomic load with sequential consistency
        value = builder.load_atomic(value_field, ordering='seq_cst', align=8)
        
        builder.ret(value)
    
    def _implement_atomic_ref_store(self):
        """Implement atomic_ref_store: atomically write a new reference value."""
        func = self.atomic_ref_store
        func.args[0].name = "ref"
        func.args[1].name = "value"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        ref_ptr = func.args[0]
        value = func.args[1]
        
        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        # Atomic store with sequential consistency
        builder.store_atomic(value, value_field, ordering='seq_cst', align=8)
        
        builder.ret_void()
    
    def _implement_atomic_ref_cas(self):
        """Implement atomic_ref_compare_and_swap: atomically update if current equals expected.
        
        Returns true if the swap occurred, false otherwise.
        """
        func = self.atomic_ref_cas
        func.args[0].name = "ref"
        func.args[1].name = "expected"
        func.args[2].name = "new"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        ref_ptr = func.args[0]
        expected = func.args[1]
        new_val = func.args[2]
        
        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        # Atomic compare-and-swap
        # cmpxchg returns { value, success_flag }
        result = builder.cmpxchg(value_field, expected, new_val, 
                                  ordering='seq_cst', failordering='seq_cst')
        
        # Extract the success flag (second element of the result)
        success = builder.extract_value(result, 1)
        
        builder.ret(success)
    
    def _implement_atomic_ref_swap(self):
        """Implement atomic_ref_swap: atomically replace and return old value."""
        func = self.atomic_ref_swap
        func.args[0].name = "ref"
        func.args[1].name = "new"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        ref_ptr = func.args[0]
        new_val = func.args[1]
        
        # Get pointer to the value field
        value_field = builder.gep(ref_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        # Atomic exchange - returns old value
        old_val = builder.atomic_rmw('xchg', value_field, new_val, ordering='seq_cst')
        
        builder.ret(old_val)
    
    def _register_atomic_ref_methods(self):
        """Register atomic_ref as a type with methods."""
        self.type_registry["atomic_ref"] = self.atomic_ref_struct
        self.type_fields["atomic_ref"] = []  # Internal structure
        
        self.type_methods["atomic_ref"] = {
            "load": "coex_atomic_ref_load",
            "store": "coex_atomic_ref_store",
            "compare_and_swap": "coex_atomic_ref_cas",
            "swap": "coex_atomic_ref_swap",
        }
        
        self.functions["coex_atomic_ref_new"] = self.atomic_ref_new
        self.functions["coex_atomic_ref_load"] = self.atomic_ref_load
        self.functions["coex_atomic_ref_store"] = self.atomic_ref_store
        self.functions["coex_atomic_ref_cas"] = self.atomic_ref_cas
        self.functions["coex_atomic_ref_swap"] = self.atomic_ref_swap

    def _create_global_string(self, value: str, name: str) -> ir.GlobalVariable:
        """Create a global string constant"""
        # Check cache
        if value in self.string_constants:
            return self.string_constants[value]
        
        value_bytes = bytearray((value + "\0").encode("utf8"))
        str_type = ir.ArrayType(ir.IntType(8), len(value_bytes))
        global_str = ir.GlobalVariable(self.module, str_type, name=name)
        global_str.global_constant = True
        global_str.linkage = 'private'
        global_str.initializer = ir.Constant(str_type, value_bytes)
        
        self.string_constants[value] = global_str
        return global_str
    
    def _get_string_ptr(self, value: str) -> ir.Value:
        """Create a String object from a string literal"""
        name = f"str_{self.string_counter}"
        self.string_counter += 1
        global_str = self._create_global_string(value, name)
        raw_ptr = self.builder.bitcast(global_str, ir.IntType(8).as_pointer())
        
        # Create a String object by calling string_from_literal
        return self.builder.call(self.string_from_literal, [raw_ptr])
    
    def _get_raw_string_ptr(self, value: str) -> ir.Value:
        """Get raw pointer to a string constant (for printf etc.)"""
        name = f"str_{self.string_counter}"
        self.string_counter += 1
        global_str = self._create_global_string(value, name)
        return self.builder.bitcast(global_str, ir.IntType(8).as_pointer())
    def _create_result_helpers(self):
        """Create Result type helper functions.

        Result<T, E> is a tagged union:
        - tag: 0 = Ok, 1 = Err
        - ok_value: the success value (as i64)
        - err_value: the error value (as i64)
        """
        result_ptr = self.result_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)

        # Register Result in type registry
        self.type_registry["Result"] = self.result_struct
        self.type_methods["Result"] = {}

        # Register Result with GC (24 bytes, reference offsets at ok_value and err_value fields)
        # Fields: tag (offset 0), ok_value (offset 8), err_value (offset 16)
        # Both value fields may contain pointers
        self.gc.register_type("Result", 24, [8, 16])

        # result_ok(value: i64) -> Result*
        self._create_result_ok(result_ptr, i64)

        # result_err(error: i64) -> Result*
        self._create_result_err(result_ptr, i64)

        # result_is_ok(r: Result*) -> bool
        self._create_result_is_ok(result_ptr, i1)

        # result_is_err(r: Result*) -> bool
        self._create_result_is_err(result_ptr, i1)

        # result_unwrap(r: Result*) -> i64
        self._create_result_unwrap(result_ptr, i64)

        # result_unwrap_or(r: Result*, default: i64) -> i64
        self._create_result_unwrap_or(result_ptr, i64)

    def _create_result_ok(self, result_ptr: ir.Type, i64: ir.Type):
        """Create Result.ok(value) constructor."""
        func_type = ir.FunctionType(result_ptr, [i64])
        func = ir.Function(self.module, func_type, name="coex_result_ok")
        self.result_ok = func
        self.functions["coex_result_ok"] = func
        self.functions["Result_ok"] = func  # Also register for static method lookup
        self.type_methods["Result"]["ok"] = "coex_result_ok"

        func.args[0].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        value = func.args[0]

        # Allocate Result struct (24 bytes = 3 * 8) via GC
        struct_size = ir.Constant(i64, 24)
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id("Result"))
        raw_ptr = self.gc.alloc_with_deref(builder, struct_size, type_id)
        result = builder.bitcast(raw_ptr, result_ptr)

        # Set tag = 0 (Ok)
        tag_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), tag_field)

        # Set ok_value = value
        ok_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(value, ok_field)

        # Set err_value = 0 (unused)
        err_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), err_field)

        builder.ret(result)

    def _create_result_err(self, result_ptr: ir.Type, i64: ir.Type):
        """Create Result.err(error) constructor."""
        func_type = ir.FunctionType(result_ptr, [i64])
        func = ir.Function(self.module, func_type, name="coex_result_err")
        self.result_err = func
        self.functions["coex_result_err"] = func
        self.functions["Result_err"] = func  # Also register for static method lookup
        self.type_methods["Result"]["err"] = "coex_result_err"

        func.args[0].name = "error"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        error = func.args[0]

        # Allocate Result struct (24 bytes = 3 * 8) via GC
        struct_size = ir.Constant(i64, 24)
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id("Result"))
        raw_ptr = self.gc.alloc_with_deref(builder, struct_size, type_id)
        result = builder.bitcast(raw_ptr, result_ptr)

        # Set tag = 1 (Err)
        tag_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 1), tag_field)

        # Set ok_value = 0 (unused)
        ok_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), ok_field)

        # Set err_value = error
        err_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(error, err_field)

        builder.ret(result)

    def _create_result_is_ok(self, result_ptr: ir.Type, i1: ir.Type):
        """Create result.is_ok() method."""
        func_type = ir.FunctionType(i1, [result_ptr])
        func = ir.Function(self.module, func_type, name="coex_result_is_ok")
        self.result_is_ok = func
        self.functions["coex_result_is_ok"] = func
        self.type_methods["Result"]["is_ok"] = "coex_result_is_ok"

        func.args[0].name = "result"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        result = func.args[0]

        # Get tag
        tag_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        tag = builder.load(tag_field)

        # Return tag == 0
        is_ok = builder.icmp_signed("==", tag, ir.Constant(ir.IntType(64), 0))
        builder.ret(is_ok)

    def _create_result_is_err(self, result_ptr: ir.Type, i1: ir.Type):
        """Create result.is_err() method."""
        func_type = ir.FunctionType(i1, [result_ptr])
        func = ir.Function(self.module, func_type, name="coex_result_is_err")
        self.result_is_err = func
        self.functions["coex_result_is_err"] = func
        self.type_methods["Result"]["is_err"] = "coex_result_is_err"

        func.args[0].name = "result"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        result = func.args[0]

        # Get tag
        tag_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        tag = builder.load(tag_field)

        # Return tag != 0 (i.e., tag == 1 means Err)
        is_err = builder.icmp_signed("!=", tag, ir.Constant(ir.IntType(64), 0))
        builder.ret(is_err)

    def _create_result_unwrap(self, result_ptr: ir.Type, i64: ir.Type):
        """Create result.unwrap() method. Returns ok_value (panics if Err in real impl)."""
        func_type = ir.FunctionType(i64, [result_ptr])
        func = ir.Function(self.module, func_type, name="coex_result_unwrap")
        self.result_unwrap = func
        self.functions["coex_result_unwrap"] = func
        self.type_methods["Result"]["unwrap"] = "coex_result_unwrap"

        func.args[0].name = "result"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        result = func.args[0]

        # Get ok_value (field 1)
        ok_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        ok_value = builder.load(ok_field)

        builder.ret(ok_value)

    def _create_result_unwrap_or(self, result_ptr: ir.Type, i64: ir.Type):
        """Create result.unwrap_or(default) method."""
        func_type = ir.FunctionType(i64, [result_ptr, i64])
        func = ir.Function(self.module, func_type, name="coex_result_unwrap_or")
        self.result_unwrap_or = func
        self.functions["coex_result_unwrap_or"] = func
        self.type_methods["Result"]["unwrap_or"] = "coex_result_unwrap_or"

        func.args[0].name = "result"
        func.args[1].name = "default"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        result = func.args[0]
        default = func.args[1]

        # Get tag
        tag_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        tag = builder.load(tag_field)

        # Check if Ok (tag == 0)
        is_ok = builder.icmp_signed("==", tag, ir.Constant(ir.IntType(64), 0))

        # Get ok_value
        ok_field = builder.gep(result, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        ok_value = builder.load(ok_field)

        # Return ok_value if Ok, else default
        result_val = builder.select(is_ok, ok_value, default)
        builder.ret(result_val)

    # ========================================================================
    # Type Mapping
    # ========================================================================
    
    def _get_llvm_type(self, coex_type: Type) -> ir.Type:
        """Convert Coex type to LLVM type"""
        if isinstance(coex_type, PrimitiveType):
            type_map = {
                "int": ir.IntType(64),
                "float": ir.DoubleType(),
                "bool": ir.IntType(1),
                "string": self.string_struct.as_pointer(),
                "byte": ir.IntType(8),
                "char": ir.IntType(32),
                "json": self.json_struct.as_pointer(),
            }
            return type_map.get(coex_type.name, ir.IntType(64))
        
        elif isinstance(coex_type, AtomicType):
            # Atomics are just regular types for now (sequential execution)
            type_map = {
                "int": ir.IntType(64),
                "float": ir.DoubleType(),
                "bool": ir.IntType(1),
            }
            return type_map.get(coex_type.inner, ir.IntType(64))
        
        elif isinstance(coex_type, OptionalType):
            # Optional is a struct { i1 has_value, T value }
            inner = self._get_llvm_type(coex_type.inner)
            return ir.LiteralStructType([ir.IntType(1), inner])

        elif isinstance(coex_type, ResultType):
            # Result<T, E> is a pointer to Result struct
            return self.result_struct.as_pointer()

        elif isinstance(coex_type, ListType):
            # Lists are pointers to List struct
            return self.list_struct.as_pointer()
        
        elif isinstance(coex_type, MapType):
            # Maps are pointers to Map struct
            return self.map_struct.as_pointer()

        elif isinstance(coex_type, SetType):
            # Sets are pointers to Set struct
            return self.set_struct.as_pointer()

        elif isinstance(coex_type, ArrayType):
            # Arrays are pointers to Array struct
            return self.array_struct.as_pointer()

        elif isinstance(coex_type, TupleType):
            # Tuple is a struct of its elements
            elem_types = [self._get_llvm_type(t) for _, t in coex_type.elements]
            return ir.LiteralStructType(elem_types)
        
        elif isinstance(coex_type, FunctionType):
            # Function pointer
            param_types = [self._get_llvm_type(t) for t in coex_type.param_types]
            ret_type = self._get_llvm_type(coex_type.return_type) if coex_type.return_type else ir.VoidType()
            return ir.FunctionType(ret_type, param_types).as_pointer()
        
        elif isinstance(coex_type, NamedType):
            # Check if it's a type parameter that needs substitution
            if coex_type.name in self.type_substitutions:
                return self._get_llvm_type(self.type_substitutions[coex_type.name])

            # Check if this is a generic type instantiation
            if coex_type.type_args and coex_type.name in self.generic_types:
                mangled_name = self._monomorphize_type(coex_type.name, coex_type.type_args)
                return self.type_registry[mangled_name].as_pointer()

            # User-defined type - return pointer to struct
            if coex_type.name in self.type_registry:
                return self.type_registry[coex_type.name].as_pointer()

            # If in a module context, try the mangled name
            if self.current_module:
                mangled_name = f"__{self.current_module}__{coex_type.name}"
                if mangled_name in self.type_registry:
                    return self.type_registry[mangled_name].as_pointer()

            # Check if it's a generic type without args - error or default
            if coex_type.name in self.generic_types:
                # Generic used without type arguments - return placeholder
                return ir.IntType(64)

            # Unknown type - default to i64
            return ir.IntType(64)
        
        else:
            return ir.IntType(64)

    def _is_reference_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is a reference (pointer) type for GC tracking."""
        if isinstance(coex_type, PrimitiveType):
            # Only string is a reference among primitives
            return coex_type.name == "string"
        elif isinstance(coex_type, (ListType, MapType, SetType, ResultType)):
            return True
        elif isinstance(coex_type, NamedType):
            # User-defined types are pointers
            return True
        elif isinstance(coex_type, OptionalType):
            # Optional of reference type needs tracking
            return self._is_reference_type(coex_type.inner)
        # TupleType, FunctionType, AtomicType, primitives (non-string) are not references
        return False

    def _get_default_value(self, coex_type: Type) -> ir.Constant:
        """Get default value for a type"""
        llvm_type = self._get_llvm_type(coex_type)
        
        if isinstance(llvm_type, ir.IntType):
            return ir.Constant(llvm_type, 0)
        elif isinstance(llvm_type, ir.DoubleType):
            return ir.Constant(llvm_type, 0.0)
        elif isinstance(llvm_type, ir.PointerType):
            return ir.Constant(llvm_type, None)
        elif isinstance(llvm_type, ir.LiteralStructType):
            # Zero-initialize struct
            values = [self._get_default_value_for_llvm(t) for t in llvm_type.elements]
            return ir.Constant(llvm_type, values)
        else:
            return ir.Constant(ir.IntType(64), 0)
    
    def _get_default_value_for_llvm(self, llvm_type: ir.Type) -> ir.Constant:
        """Get default value for an LLVM type"""
        if isinstance(llvm_type, ir.IntType):
            return ir.Constant(llvm_type, 0)
        elif isinstance(llvm_type, ir.DoubleType):
            return ir.Constant(llvm_type, 0.0)
        elif isinstance(llvm_type, ir.PointerType):
            return ir.Constant(llvm_type, None)
        else:
            return ir.Constant(ir.IntType(64), 0)
    
    # ========================================================================
    # Program Generation
    # ========================================================================
    
    def generate(self, program: Program, source_path: str = None) -> str:
        """Generate LLVM IR for entire program"""
        # Set up module search paths
        self.module_search_paths = []
        if source_path:
            self.module_search_paths.append(os.path.dirname(os.path.abspath(source_path)))
        # Add lib/ directory relative to compiler location
        # Go up one level from codegen/ to project root
        compiler_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.module_search_paths.append(os.path.join(compiler_dir, "lib"))

        # Load imported modules and libraries
        for imp in program.imports:
            if imp.is_library:
                # Library import: import "path/to/lib.cxz"
                self._load_library(imp.library_path, imp.module)
            else:
                # Module import: import math
                self._load_module(imp.module)

        # Register replace aliases
        for rep in program.replaces:
            if rep.module not in self.loaded_modules:
                raise RuntimeError(f"Module '{rep.module}' not imported for replace '{rep.shortname}'")
            self.replace_aliases[rep.shortname] = (rep.module, rep.qualified_name)

        # Process compiler directives (printing/debugging)
        for directive in program.directives:
            if directive.name == "printing":
                self.printing_enabled = directive.enabled
            elif directive.name == "debugging":
                self.debugging_enabled = directive.enabled

        # CLI overrides file directives
        if self.cli_printing is not None:
            self.printing_enabled = self.cli_printing
        if self.cli_debugging is not None:
            self.debugging_enabled = self.cli_debugging

        # Register all traits first (they define interfaces)
        for trait_decl in program.traits:
            self._register_trait(trait_decl)
        
        # First pass: register all types (struct layouts)
        for type_decl in program.types:
            self._register_type(type_decl)
        
        # Check trait implementations for all types
        for type_decl in program.types:
            if not type_decl.type_params:  # Skip generic types (checked at monomorphization)
                self._check_trait_implementations(type_decl)

        # Register matrices BEFORE function generation (so main() can use them)
        for matrix_decl in program.matrices:
            self._register_matrix(matrix_decl)
        
        # Declare matrix formula methods (register names before function generation)
        for matrix_decl in program.matrices:
            self._declare_matrix_methods(matrix_decl)
        
        # Store function declarations for return type inference
        for func in program.functions:
            self.func_decls[func.name] = func
        
        # First pass for functions: declare all (including type methods)
        for func in program.functions:
            self._declare_function(func)
        
        # Declare methods for all types
        for type_decl in program.types:
            self._declare_type_methods(type_decl)
        
        # Second pass: generate function bodies
        for func in program.functions:
            self._generate_function(func)
        
        # Generate method bodies for all types
        for type_decl in program.types:
            self._generate_type_methods(type_decl)
        
        # Generate matrix formula methods (after functions, as they may reference them)
        for matrix_decl in program.matrices:
            self._generate_matrix_methods(matrix_decl)

        # Phase 9: Finalize GC type tables after all types are registered
        # This creates the offset arrays for user types so gc_mark_object can
        # recursively mark pointer fields in user-defined types
        self.gc.finalize_type_tables()

        return self.get_ir()

    # ========================================================================
    # Module Loading
    # ========================================================================

    def _find_module_file(self, module_name: str) -> Optional[tuple]:
        """Find module file in search paths.

        Returns:
            Tuple of (path, is_library) where is_library is True for .cxz files,
            or None if not found.
        """
        # Check for both .coex (source) and .cxz (library) files
        # Prefer .coex if both exist
        for ext, is_library in [('.coex', False), ('.cxz', True)]:
            filename = f"{module_name}{ext}"
            for path in self.module_search_paths:
                full_path = os.path.join(path, filename)
                if os.path.exists(full_path):
                    return (full_path, is_library)

        return None

    def _load_module(self, module_name: str) -> ModuleInfo:
        """Load and compile a module, returning its info"""
        # Check cache
        if module_name in self.loaded_modules:
            return self.loaded_modules[module_name]

        # Find module file (checks both .coex and .cxz)
        result = self._find_module_file(module_name)
        if not result:
            searched = ", ".join(self.module_search_paths)
            raise RuntimeError(f"Module not found: {module_name} (searched: {searched})")

        module_path, is_library = result

        # If it's a .cxz library, delegate to library loader
        if is_library:
            self._load_library(module_path, module_name)
            # Create a placeholder ModuleInfo for consistency
            # The actual symbols are in loaded_libraries
            return ModuleInfo(name=module_name, path=module_path, program=None)

        # Parse module
        from antlr4 import FileStream, CommonTokenStream
        from CoexLexer import CoexLexer
        from CoexParser import CoexParser
        from ast_builder import ASTBuilder

        input_stream = FileStream(module_path)
        lexer = CoexLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        parser = CoexParser(token_stream)
        tree = parser.program()

        builder = ASTBuilder()
        program = builder.build(tree)

        # Create module info
        module_info = ModuleInfo(
            name=module_name,
            path=module_path,
            program=program,
        )

        # Generate code for module with name mangling
        saved_module = self.current_module
        self.current_module = module_name

        self._generate_module_contents(program, module_info)

        self.current_module = saved_module
        self.loaded_modules[module_name] = module_info

        return module_info

    def _generate_module_contents(self, program: Program, module_info: ModuleInfo):
        """Generate code for module contents with name mangling"""
        prefix = f"__{module_info.name}__"

        # Register traits from module
        for trait_decl in program.traits:
            self._register_trait(trait_decl)

        # Register types with mangled names
        mangled_type_decls = []
        for type_decl in program.types:
            mangled = f"{prefix}{type_decl.name}"
            # Store original name mapping
            module_info.types[type_decl.name] = mangled
            # Create a copy of the type decl with mangled name
            mangled_type_decl = TypeDecl(
                name=mangled,
                type_params=type_decl.type_params,
                fields=type_decl.fields,
                methods=type_decl.methods,
                variants=type_decl.variants
            )
            self._register_type(mangled_type_decl)
            mangled_type_decls.append(mangled_type_decl)

            # Also register under unqualified name for use within this library's methods
            # This allows Regex(handle, pattern) to work inside compile_flags()
            if type_decl.name not in self.type_registry:
                self.type_registry[type_decl.name] = self.type_registry[mangled]
            if type_decl.name not in self.type_fields:
                self.type_fields[type_decl.name] = self.type_fields[mangled]
            if mangled in self.type_methods and type_decl.name not in self.type_methods:
                self.type_methods[type_decl.name] = self.type_methods[mangled]

        # Declare type methods (must happen before generating functions that may call them)
        for mangled_type_decl in mangled_type_decls:
            self._declare_type_methods(mangled_type_decl)

        # Register method functions under unqualified names for static method calls
        # e.g., __regex__Regex_compile_flags -> Regex_compile_flags
        for type_decl in program.types:
            mangled_type_name = f"{prefix}{type_decl.name}"
            if mangled_type_name in self.type_methods:
                for method_name, mangled_method in self.type_methods[mangled_type_name].items():
                    unqualified_method = f"{type_decl.name}_{method_name}"
                    if mangled_method in self.functions and unqualified_method not in self.functions:
                        self.functions[unqualified_method] = self.functions[mangled_method]

        # Declare and generate functions with mangled names
        for func in program.functions:
            if func.name == "main":
                continue  # Skip main in modules

            # Extern functions should NOT be mangled - they link to C code
            if func.kind == FunctionKind.EXTERN:
                # Use original name for extern functions
                module_info.functions[func.name] = func.name
                self.func_decls[func.name] = func
                self._declare_function(func)
                continue

            mangled = f"{prefix}{func.name}"
            module_info.functions[func.name] = mangled

            # Create mangled function declaration
            mangled_func = FunctionDecl(
                kind=func.kind,
                name=mangled,
                type_params=func.type_params,
                params=func.params,
                return_type=func.return_type,
                body=func.body
            )

            # Store for return type inference
            self.func_decls[mangled] = mangled_func

            # Declare and generate
            self._declare_function(mangled_func)
            self._generate_function(mangled_func)

        # Generate type method bodies
        for mangled_type_decl in mangled_type_decls:
            self._generate_type_methods(mangled_type_decl)

    # ========================================================================
    # FFI Library Loading
    # ========================================================================

    def _load_library(self, library_path: str, library_name: str):
        """Load a .cxz library and register its FFI symbols.

        Args:
            library_path: Path to the .cxz file (relative or absolute)
            library_name: Extracted library name (e.g., "regex" from "regex.cxz")
        """
        # Check if already loaded
        if library_name in self.loaded_libraries:
            return self.loaded_libraries[library_name]

        # Initialize CXZ loader lazily
        if self.cxz_loader is None:
            self.cxz_loader = CXZLoader(search_paths=self.module_search_paths)

        # Load the library
        try:
            loaded_lib = self.cxz_loader.load(library_path)
        except CXZError as e:
            raise RuntimeError(f"Failed to load library '{library_name}': {e}")

        # Create library info
        lib_info = LibraryInfo(
            name=library_name,
            path=library_path,
            loaded_lib=loaded_lib,
            symbols=loaded_lib.get_ffi_symbols()
        )
        self.loaded_libraries[library_name] = lib_info

        # Aggregate FFI symbols for quick lookup
        for sym_name, sym in lib_info.symbols.items():
            self.ffi_symbols[sym_name] = sym

        # Collect link arguments
        self.ffi_link_args.extend(loaded_lib.get_link_args())

        # Declare FFI runtime functions if not already done
        self._declare_ffi_runtime()

        # Parse and process the library's Coex source files
        self._process_library_sources(lib_info)

        return lib_info

    def _process_library_sources(self, lib_info: LibraryInfo):
        """Process Coex source files from a library.

        Parses extern declarations and registers them, along with
        types and wrapper functions defined in the library.
        """
        from antlr4 import CommonTokenStream, InputStream
        from CoexLexer import CoexLexer
        from CoexParser import CoexParser
        from ast_builder import ASTBuilder

        for filename, source in lib_info.loaded_lib.coex_sources.items():
            # Parse the source
            input_stream = InputStream(source)
            lexer = CoexLexer(input_stream)
            token_stream = CommonTokenStream(lexer)
            parser = CoexParser(token_stream)
            tree = parser.program()

            builder = ASTBuilder()
            program = builder.build(tree)

            # Create a pseudo-module for this library source
            module_info = ModuleInfo(
                name=lib_info.name,
                path=f"{lib_info.path}:{filename}",
                program=program
            )

            # Process the contents with library name prefix
            saved_module = self.current_module
            self.current_module = lib_info.name

            # Register types and generate functions from library
            self._generate_module_contents(program, module_info)

            self.current_module = saved_module

            # Also register the module info for qualified access
            if lib_info.name not in self.loaded_modules:
                self.loaded_modules[lib_info.name] = module_info

            # Register library functions under their unqualified names for direct access
            # This allows users to call regex_match() instead of regex.regex_match()
            for original_name, mangled_name in module_info.functions.items():
                if mangled_name in self.functions and original_name not in self.functions:
                    self.functions[original_name] = self.functions[mangled_name]

            # Also register extern function declarations for the library
            if hasattr(self, 'extern_function_decls'):
                for original_name, mangled_name in module_info.functions.items():
                    if mangled_name in self.extern_function_decls and original_name not in self.extern_function_decls:
                        self.extern_function_decls[original_name] = self.extern_function_decls[mangled_name]

            # Register library types under their unqualified names for direct access
            # This allows users to use Regex instead of regex.Regex
            for original_name, mangled_name in module_info.types.items():
                if mangled_name in self.type_registry and original_name not in self.type_registry:
                    self.type_registry[original_name] = self.type_registry[mangled_name]
                if mangled_name in self.type_fields and original_name not in self.type_fields:
                    self.type_fields[original_name] = self.type_fields[mangled_name]
                if mangled_name in self.type_methods and original_name not in self.type_methods:
                    self.type_methods[original_name] = self.type_methods[mangled_name]
                    # Also register method functions under unqualified names
                    # e.g., __regex__Regex_compile_flags -> Regex_compile_flags
                    for method_name, mangled_method in self.type_methods[mangled_name].items():
                        unqualified_method = f"{original_name}_{method_name}"
                        if mangled_method in self.functions and unqualified_method not in self.functions:
                            self.functions[unqualified_method] = self.functions[mangled_method]

    def _declare_ffi_runtime(self):
        """Declare the FFI runtime support functions."""
        if self._ffi_runtime_declared:
            return

        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        void = ir.VoidType()

        # int64_t coex_ffi_instance_create(const char* library_name)
        create_type = ir.FunctionType(i64, [i8_ptr])
        self._ffi_instance_create = ir.Function(
            self.module, create_type, name="coex_ffi_instance_create"
        )
        self._ffi_instance_create.linkage = 'external'

        # void coex_ffi_instance_destroy(int64_t instance_id)
        destroy_type = ir.FunctionType(void, [i64])
        self._ffi_instance_destroy = ir.Function(
            self.module, destroy_type, name="coex_ffi_instance_destroy"
        )
        self._ffi_instance_destroy.linkage = 'external'

        # void coex_ffi_enter(int64_t instance_id)
        enter_type = ir.FunctionType(void, [i64])
        self._ffi_enter = ir.Function(
            self.module, enter_type, name="coex_ffi_enter"
        )
        self._ffi_enter.linkage = 'external'

        # void coex_ffi_exit(int64_t instance_id)
        exit_type = ir.FunctionType(void, [i64])
        self._ffi_exit = ir.Function(
            self.module, exit_type, name="coex_ffi_exit"
        )
        self._ffi_exit.linkage = 'external'

        self._ffi_runtime_declared = True

    def get_ffi_link_args(self) -> PyList[str]:
        """Get the link arguments for FFI libraries.

        Call this after generate() to get the list of object files
        and system libraries needed for linking.
        """
        return self.ffi_link_args

    def _register_trait(self, trait_decl: 'TraitDecl'):
        """Register a trait definition"""
        self.traits[trait_decl.name] = trait_decl
    
    def _check_trait_implementations(self, type_decl: TypeDecl):
        """Check which traits a type implements and record them"""
        implemented = []
        
        # Get the type's methods (name -> FunctionDecl)
        type_methods = {m.name: m for m in type_decl.methods}
        
        # Check each trait
        for trait_name, trait_decl in self.traits.items():
            if self._type_implements_trait(type_decl, trait_decl, type_methods):
                implemented.append(trait_name)
        
        self.type_implements[type_decl.name] = implemented
    
    def _type_implements_trait(self, type_decl: TypeDecl, trait_decl: 'TraitDecl', 
                                type_methods: Dict[str, FunctionDecl]) -> bool:
        """Check if a type implements all methods of a trait"""
        for trait_method in trait_decl.methods:
            if trait_method.name not in type_methods:
                return False
            
            type_method = type_methods[trait_method.name]
            
            # Check method signature compatibility
            if not self._methods_compatible(trait_method, type_method):
                return False
        
        return True
    
    def _methods_compatible(self, trait_method: FunctionDecl, type_method: FunctionDecl) -> bool:
        """Check if a type's method is compatible with a trait method signature"""
        # Check parameter count
        if len(trait_method.params) != len(type_method.params):
            return False
        
        # Check return type compatibility (simplified - could be more precise)
        # For now, just check they both have return types or both don't
        trait_has_return = trait_method.return_type is not None
        type_has_return = type_method.return_type is not None
        if trait_has_return != type_has_return:
            return False
        
        return True
    
    def _check_trait_bound(self, type_name: str, trait_name: str) -> bool:
        """Check if a type satisfies a trait bound"""
        # Handle monomorphized type names (e.g., "Pair_int_float")
        base_type = type_name.split('_')[0] if '_' in type_name else type_name
        
        # Check if type explicitly implements the trait
        if type_name in self.type_implements:
            if trait_name in self.type_implements[type_name]:
                return True
        
        # Check base type for generics
        if base_type in self.type_implements:
            if trait_name in self.type_implements[base_type]:
                return True
        
        # Check primitive types for built-in traits
        if self._primitive_implements_trait(type_name, trait_name):
            return True
        
        return False
    
    def _primitive_implements_trait(self, type_name: str, trait_name: str) -> bool:
        """Check if a primitive type implements a built-in trait"""
        # Define which primitives implement which traits
        primitive_traits = {
            "int": ["Numeric", "Comparable", "Eq", "Hash", "Display"],
            "float": ["Numeric", "Comparable", "Display"],
            "bool": ["Eq", "Hash", "Display"],
            "string": ["Eq", "Hash", "Display", "Comparable"],
            "byte": ["Numeric", "Comparable", "Eq", "Hash"],
        }
        
        if type_name in primitive_traits:
            return trait_name in primitive_traits[type_name]
        
        return False
    
    def _register_type(self, type_decl: TypeDecl):
        """Register a user-defined type"""
        # Store the AST for later reference
        self.type_decls[type_decl.name] = type_decl

        # If generic, store as template for later monomorphization
        if type_decl.type_params:
            self.generic_types[type_decl.name] = type_decl
            return

        # Check if this is an enum (has variants)
        if type_decl.variants:
            self._register_enum_type(type_decl)
            return

        # Regular struct type
        self._register_concrete_type(type_decl.name, type_decl)
    
    def _register_concrete_type(self, mangled_name: str, type_decl: TypeDecl):
        """Register a concrete (non-generic) type"""
        # Create struct type
        name = f"struct.{mangled_name}"
        struct_type = ir.global_context.get_identified_type(name)

        # Collect field types and names
        # Phase 6: Reference type fields use i64 handles instead of pointers
        field_types = []
        field_info = []
        for field in type_decl.fields:
            field_type = self._substitute_type(field.type_annotation)
            if self._is_reference_type(field_type):
                # Phase 6: Store as i64 handle instead of pointer
                llvm_type = ir.IntType(64)
            else:
                llvm_type = self._get_llvm_type(field_type)
            field_types.append(llvm_type)
            field_info.append((field.name, field_type))
        
        if field_types:
            struct_type.set_body(*field_types)
        else:
            struct_type.set_body(ir.IntType(8))  # Empty struct placeholder
        
        # Store the struct type (not as pointer - we add pointer when needed)
        self.type_registry[mangled_name] = struct_type
        self.type_fields[mangled_name] = field_info
        self.type_methods[mangled_name] = {}

        # Register type with GC for heap tracking
        if self.gc is not None:
            # Calculate size (8 bytes per field)
            size = len(field_info) * 8 if field_info else 8
            # Compute reference field offsets
            ref_offsets = []
            for i, (_, field_type) in enumerate(field_info):
                if self._is_reference_type(field_type):
                    ref_offsets.append(i * 8)
            self.gc.register_type(mangled_name, size, ref_offsets)
    
    def _substitute_type(self, coex_type: Type) -> Type:
        """Substitute type parameters with concrete types"""
        if not self.type_substitutions:
            return coex_type
        
        if isinstance(coex_type, NamedType):
            # Check if this is a type parameter
            if coex_type.name in self.type_substitutions:
                return self.type_substitutions[coex_type.name]
            # Check if it has type args that need substitution
            if coex_type.type_args:
                new_args = [self._substitute_type(arg) for arg in coex_type.type_args]
                return NamedType(coex_type.name, new_args)
        elif isinstance(coex_type, ListType):
            return ListType(self._substitute_type(coex_type.element_type))
        elif isinstance(coex_type, OptionalType):
            return OptionalType(self._substitute_type(coex_type.inner))
        elif isinstance(coex_type, ResultType):
            return ResultType(
                self._substitute_type(coex_type.ok_type),
                self._substitute_type(coex_type.err_type)
            )
        elif isinstance(coex_type, TupleType):
            new_elements = [(name, self._substitute_type(t)) for name, t in coex_type.elements]
            return TupleType(new_elements)
        elif isinstance(coex_type, FunctionType):
            new_params = [self._substitute_type(t) for t in coex_type.param_types]
            new_ret = self._substitute_type(coex_type.return_type) if coex_type.return_type else None
            return FunctionType(coex_type.kind, new_params, new_ret)
        
        return coex_type
    
    def _mangle_generic_name(self, base_name: str, type_args: PyList[Type]) -> str:
        """Create mangled name for monomorphized generic: Pair_int_float"""
        parts = [base_name]
        for arg in type_args:
            parts.append(self._type_to_string(arg))
        return "_".join(parts)
    
    def _type_to_string(self, coex_type: Type) -> str:
        """Convert type to string for name mangling"""
        if isinstance(coex_type, PrimitiveType):
            return coex_type.name
        elif isinstance(coex_type, NamedType):
            if coex_type.type_args:
                args = "_".join(self._type_to_string(a) for a in coex_type.type_args)
                return f"{coex_type.name}_{args}"
            return coex_type.name
        elif isinstance(coex_type, ListType):
            return f"List_{self._type_to_string(coex_type.element_type)}"
        elif isinstance(coex_type, OptionalType):
            return f"Opt_{self._type_to_string(coex_type.inner)}"
        elif isinstance(coex_type, ResultType):
            ok_str = self._type_to_string(coex_type.ok_type)
            err_str = self._type_to_string(coex_type.err_type)
            return f"Result_{ok_str}_{err_str}"
        else:
            return "unknown"
    
    def _monomorphize_type(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic type with concrete type arguments"""
        if name not in self.generic_types:
            return name  # Not a generic type
        
        mangled_name = self._mangle_generic_name(name, type_args)
        
        # Already monomorphized?
        if mangled_name in self.type_registry:
            return mangled_name
        
        # Get the generic type declaration
        type_decl = self.generic_types[name]
        
        # Check trait bounds
        for param, arg in zip(type_decl.type_params, type_args):
            for bound in param.bounds:
                type_name = self._type_to_string(arg)
                if not self._check_trait_bound(type_name, bound):
                    # Trait bound not satisfied - for now, continue anyway
                    pass
        
        # Set up type substitutions
        old_subs = self.type_substitutions.copy()
        self.type_substitutions = {}
        for param, arg in zip(type_decl.type_params, type_args):
            self.type_substitutions[param.name] = arg
        
        # Register the concrete type
        self._register_concrete_type(mangled_name, type_decl)
        
        # Store AST reference with mangled name
        self.type_decls[mangled_name] = type_decl
        
        # Check trait implementations for the monomorphized type
        self._check_monomorphized_trait_implementations(mangled_name, type_decl)
        
        # Monomorphize and declare methods
        self._declare_type_methods_monomorphized(mangled_name, type_decl)
        
        # Restore substitutions
        self.type_substitutions = old_subs
        
        return mangled_name
    
    def _check_monomorphized_trait_implementations(self, mangled_name: str, type_decl: TypeDecl):
        """Check which traits a monomorphized type implements"""
        implemented = []
        
        # Get the type's methods (name -> FunctionDecl)
        type_methods = {m.name: m for m in type_decl.methods}
        
        # Check each trait
        for trait_name, trait_decl in self.traits.items():
            if self._type_implements_trait(type_decl, trait_decl, type_methods):
                implemented.append(trait_name)
        
        self.type_implements[mangled_name] = implemented
    
    def _declare_type_methods_monomorphized(self, mangled_type_name: str, type_decl: TypeDecl):
        """Declare methods for a monomorphized type"""
        struct_type = self.type_registry[mangled_type_name]
        self_ptr_type = struct_type.as_pointer()
        
        # Save current substitutions (already set up by caller)
        for method in type_decl.methods:
            # Mangle method name with type name
            mangled_method = f"{mangled_type_name}_{method.name}"
            
            # Build parameter types (self is implicit first parameter)
            param_types = [self_ptr_type]
            for param in method.params:
                param_type = self._substitute_type(param.type_annotation)
                param_types.append(self._get_llvm_type(param_type))
            
            # Build return type
            if method.return_type:
                return_type = self._substitute_type(method.return_type)
                llvm_ret = self._get_llvm_type(return_type)
            else:
                llvm_ret = ir.VoidType()
            
            # Create function
            func_type = ir.FunctionType(llvm_ret, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_method)
            llvm_func.args[0].name = "self"
            
            self.functions[mangled_method] = llvm_func
            self.type_methods[mangled_type_name][method.name] = mangled_method
        
        # Generate method bodies
        for method in type_decl.methods:
            mangled_method = self.type_methods[mangled_type_name][method.name]
            self._generate_method_body(mangled_type_name, mangled_method, method)
    
    def _generate_method_body(self, type_name: str, mangled_method: str, method: FunctionDecl):
        """Generate body for a method"""
        llvm_func = self.functions[mangled_method]

        # Save current state
        old_builder = self.builder
        old_locals = self.locals
        old_current_function = self.current_function
        old_current_type = self.current_type
        old_gc_frame = getattr(self, 'gc_frame', None)
        old_gc_roots = getattr(self, 'gc_roots', None)
        old_gc_root_indices = getattr(self, 'gc_root_indices', {})

        entry = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)

        self.locals = {}
        self._reset_function_scope()
        self.current_function = method
        self.current_type = type_name

        # Initialize GC state for this method
        self.gc_frame = None
        self.gc_roots = None
        self.gc_root_indices = {}

        # Collect heap variables for GC root tracking
        heap_var_names = []

        # Check parameters for heap types (skip 'self')
        for param in method.params:
            if param.type_annotation and self._is_heap_type(param.type_annotation):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self._collect_heap_vars_from_body(method.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables
        if heap_var_names and self.gc is not None:
            num_roots = len(heap_var_names)
            self.gc_roots = self.gc.create_frame_roots(self.builder, num_roots)
            self.gc_frame = self.gc.push_frame(self.builder, num_roots, self.gc_roots)
            self.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}

        # GC Safe-point check: trigger GC if allocation threshold exceeded
        if self.gc is not None:
            self.gc.inject_safepoint(self.builder)

        # Store self pointer
        self_alloca = self.builder.alloca(llvm_func.args[0].type, name="self")
        self.builder.store(llvm_func.args[0], self_alloca)
        self.locals["self"] = self_alloca

        # Allocate other parameters
        for i, param in enumerate(method.params):
            llvm_param = llvm_func.args[i + 1]
            llvm_param.name = param.name

            alloca = self.builder.alloca(llvm_param.type, name=param.name)
            self.builder.store(llvm_param, alloca)
            self.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in self.gc_root_indices and self.gc is not None:
                self.gc.set_root(self.builder, self.gc_roots, self.gc_root_indices[param.name], llvm_param)

        # Generate body
        for stmt in method.body:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break

        # Add implicit return if needed
        if not self.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            if isinstance(llvm_func.return_value.type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(llvm_func.return_value.type, 0))

        # Restore state
        self.builder = old_builder
        self.locals = old_locals
        self.current_function = old_current_function
        self.current_type = old_current_type
        self.gc_frame = old_gc_frame
        self.gc_roots = old_gc_roots
        self.gc_root_indices = old_gc_root_indices
    
    def _monomorphize_function(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic function with concrete type arguments"""
        if name not in self.generic_functions:
            return name  # Not a generic function
        
        mangled_name = self._mangle_generic_name(name, type_args)
        
        # Already monomorphized?
        if mangled_name in self.functions:
            return mangled_name
        
        # Get the generic function declaration
        func_decl = self.generic_functions[name]
        
        # Check trait bounds
        for param, arg in zip(func_decl.type_params, type_args):
            for bound in param.bounds:
                type_name = self._type_to_string(arg)
                if not self._check_trait_bound(type_name, bound):
                    # Trait bound not satisfied - for now, continue anyway
                    # In a full implementation, this would raise an error
                    pass
        
        # Set up type substitutions
        old_subs = self.type_substitutions.copy()
        self.type_substitutions = {}
        for param, arg in zip(func_decl.type_params, type_args):
            self.type_substitutions[param.name] = arg
        
        # Build parameter types
        param_types = []
        for param in func_decl.params:
            param_type = self._substitute_type(param.type_annotation)
            param_types.append(self._get_llvm_type(param_type))
        
        # Build return type
        if func_decl.return_type:
            return_type = self._substitute_type(func_decl.return_type)
            llvm_ret = self._get_llvm_type(return_type)
        else:
            llvm_ret = ir.VoidType()
        
        # Create function
        func_type = ir.FunctionType(llvm_ret, param_types)
        llvm_func = ir.Function(self.module, func_type, name=mangled_name)
        self.functions[mangled_name] = llvm_func
        
        # Generate function body
        entry = llvm_func.append_basic_block(name="entry")
        old_builder = self.builder
        self.builder = ir.IRBuilder(entry)

        old_locals = self.locals
        self.locals = {}
        self._reset_function_scope()
        old_current_function = self.current_function
        self.current_function = func_decl

        # Save and initialize GC state for this monomorphized function
        old_gc_frame = getattr(self, 'gc_frame', None)
        old_gc_roots = getattr(self, 'gc_roots', None)
        old_gc_root_indices = getattr(self, 'gc_root_indices', {})

        self.gc_frame = None
        self.gc_roots = None
        self.gc_root_indices = {}

        # Collect heap variables for GC root tracking
        heap_var_names = []

        # Check parameters for heap types (using substituted types)
        for param in func_decl.params:
            param_type = self._substitute_type(param.type_annotation)
            if param_type and self._is_heap_type(param_type):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self._collect_heap_vars_from_body(func_decl.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables
        if heap_var_names and self.gc is not None:
            num_roots = len(heap_var_names)
            self.gc_roots = self.gc.create_frame_roots(self.builder, num_roots)
            self.gc_frame = self.gc.push_frame(self.builder, num_roots, self.gc_roots)
            self.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}

        # Allocate parameters with value semantics (deep copy heap-allocated types)
        for i, param in enumerate(func_decl.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name

            # Get the substituted type for this parameter
            param_type = self._substitute_type(param.type_annotation)

            # Most heap types don't need copying (immutable collections)
            # UDTs with mutable fields still need copying
            param_value = llvm_param
            if self._needs_parameter_copy(param_type):
                param_value = self._generate_deep_copy(llvm_param, param_type)

            alloca = self.builder.alloca(llvm_param.type, name=param.name)
            self.builder.store(param_value, alloca)
            self.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in self.gc_root_indices and self.gc is not None:
                self.gc.set_root(self.builder, self.gc_roots, self.gc_root_indices[param.name], param_value)

        # Generate body
        for stmt in func_decl.body:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break

        # Add implicit return
        if not self.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            if isinstance(llvm_ret, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(llvm_ret, 0))

        # Restore state
        self.builder = old_builder
        self.locals = old_locals
        self.current_function = old_current_function
        self.type_substitutions = old_subs
        self.gc_frame = old_gc_frame
        self.gc_roots = old_gc_roots
        self.gc_root_indices = old_gc_root_indices

        return mangled_name
    
    def _infer_type_args(self, func_name: str, args: PyList[Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic function from call arguments"""
        if func_name not in self.generic_functions:
            return None
        
        func_decl = self.generic_functions[func_name]
        type_params = func_decl.type_params
        
        # Map type parameter names to inferred types
        inferred = {}
        param_names = {tp.name for tp in type_params}
        
        for i, (param, arg) in enumerate(zip(func_decl.params, args)):
            param_type = param.type_annotation
            inferred_type = self._infer_type_from_expr(arg)
            
            # Match parameter type against inferred type
            self._unify_types_with_params(param_type, inferred_type, inferred, param_names)
        
        # Build result in order of type parameters
        result = []
        for tp in type_params:
            if tp.name in inferred:
                result.append(inferred[tp.name])
            else:
                # Default to int if can't infer
                result.append(PrimitiveType("int"))
        
        return result
    
    def _infer_type_args_from_constructor(self, type_name: str, args: PyList[Expr], 
                                           named_args: Dict[str, Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic type constructor"""
        if type_name not in self.generic_types:
            return None
        
        type_decl = self.generic_types[type_name]
        type_params = type_decl.type_params
        
        # Build a mapping from type parameter names to their inferred types
        inferred = {}
        
        # Map field names to their declared types
        field_types = {f.name: f.type_annotation for f in type_decl.fields}
        
        # Infer from named arguments
        for field_name, arg_expr in named_args.items():
            if field_name in field_types:
                declared_type = field_types[field_name]
                inferred_type = self._infer_type_from_expr(arg_expr)
                self._unify_type_constructor(declared_type, inferred_type, inferred, type_params)
        
        # Infer from positional arguments
        for i, arg_expr in enumerate(args):
            if i < len(type_decl.fields):
                declared_type = type_decl.fields[i].type_annotation
                inferred_type = self._infer_type_from_expr(arg_expr)
                self._unify_type_constructor(declared_type, inferred_type, inferred, type_params)
        
        # Build result in order of type parameters
        result = []
        for tp in type_params:
            if tp.name in inferred:
                result.append(inferred[tp.name])
            else:
                # Default to int if can't infer
                result.append(PrimitiveType("int"))
        
        return result
    
    def _unify_type_constructor(self, declared_type: Type, inferred_type: Type, 
                                 inferred: Dict[str, Type], type_params: PyList[TypeParam]):
        """Unify a declared field type with an inferred argument type"""
        param_names = {tp.name for tp in type_params}
        
        if isinstance(declared_type, NamedType):
            if declared_type.name in param_names:
                # This field has a type parameter type - infer it
                if declared_type.name not in inferred:
                    inferred[declared_type.name] = inferred_type
        elif isinstance(declared_type, ListType):
            if isinstance(inferred_type, ListType):
                self._unify_type_constructor(declared_type.element_type, 
                                              inferred_type.element_type, inferred, type_params)
    
    def _infer_type_from_expr(self, expr: Expr) -> Type:
        """Infer the Coex type of an expression"""
        if isinstance(expr, IntLiteral):
            return PrimitiveType("int")
        elif isinstance(expr, FloatLiteral):
            return PrimitiveType("float")
        elif isinstance(expr, BoolLiteral):
            return PrimitiveType("bool")
        elif isinstance(expr, StringLiteral):
            return PrimitiveType("string")
        elif isinstance(expr, Identifier):
            # Look up variable type
            name = expr.name
            if name in self.locals:
                llvm_type = self.locals[name].type.pointee
                return self._llvm_type_to_coex(llvm_type)
        elif isinstance(expr, ListExpr):
            if expr.elements:
                elem_type = self._infer_type_from_expr(expr.elements[0])
                return ListType(elem_type)
            return ListType(PrimitiveType("int"))
        elif isinstance(expr, MapExpr):
            if expr.entries:
                key_type = self._infer_type_from_expr(expr.entries[0][0])
                value_type = self._infer_type_from_expr(expr.entries[0][1])
                return MapType(key_type, value_type)
            return MapType(PrimitiveType("int"), PrimitiveType("int"))
        elif isinstance(expr, JsonObjectExpr):
            return PrimitiveType("json")
        elif isinstance(expr, SetExpr):
            if expr.elements:
                elem_type = self._infer_type_from_expr(expr.elements[0])
                return SetType(elem_type)
            return SetType(PrimitiveType("int"))
        elif isinstance(expr, CallExpr):
            # Check if this is a type constructor call (e.g., Point(10, 20))
            func_name = expr.callee.name if isinstance(expr.callee, Identifier) else None
            if func_name and func_name in self.type_fields:
                # This is a user type constructor
                return NamedType(func_name)
        elif isinstance(expr, MemberExpr):
            # Check if accessing a field on a JSON object
            obj_type = self._infer_type_from_expr(expr.object)
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                return PrimitiveType("json")
            # For UDTs, look up the field type
            if isinstance(obj_type, NamedType) and obj_type.name in self.type_fields:
                for field_name, field_type in self.type_fields[obj_type.name]:
                    if field_name == expr.member:
                        return field_type
        elif isinstance(expr, IndexExpr):
            # Check if indexing a JSON object
            obj_type = self._infer_type_from_expr(expr.object)
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                return PrimitiveType("json")
            # For lists, return element type
            if isinstance(obj_type, ListType):
                return obj_type.element_type
            # For arrays, return element type
            if isinstance(obj_type, ArrayType):
                return obj_type.element_type
            # For maps, return value type
            if isinstance(obj_type, MapType):
                return obj_type.value_type

        # Default
        return PrimitiveType("int")
    
    def _llvm_type_to_coex(self, llvm_type: ir.Type) -> Type:
        """Convert LLVM type back to Coex type (approximate)"""
        if isinstance(llvm_type, ir.IntType):
            if llvm_type.width == 1:
                return PrimitiveType("bool")
            elif llvm_type.width == 8:
                return PrimitiveType("byte")
            else:
                return PrimitiveType("int")
        elif isinstance(llvm_type, ir.DoubleType):
            return PrimitiveType("float")
        elif isinstance(llvm_type, ir.PointerType):
            pointee = llvm_type.pointee
            if isinstance(pointee, ir.IntType) and pointee.width == 8:
                return PrimitiveType("string")
            # Check for struct types
            if hasattr(pointee, 'name'):
                if pointee.name.startswith("struct."):
                    type_name = pointee.name[7:]
                    # json is a primitive type, not a named type
                    if type_name == "Json":
                        return PrimitiveType("json")
                    return NamedType(type_name)
        return PrimitiveType("int")
    
    def _unify_types_with_params(self, param_type: Type, arg_type: Type, 
                                  inferred: Dict[str, Type], param_names: set):
        """Unify a parameter type with an argument type to infer type parameters"""
        if isinstance(param_type, NamedType):
            # Check if it's a type parameter
            if param_type.name in param_names:
                # It's a type parameter - infer it
                if param_type.name not in inferred:
                    inferred[param_type.name] = arg_type
        elif isinstance(param_type, ListType):
            if isinstance(arg_type, ListType):
                self._unify_types_with_params(param_type.element_type, arg_type.element_type, 
                                               inferred, param_names)
        elif isinstance(param_type, OptionalType):
            if isinstance(arg_type, OptionalType):
                self._unify_types_with_params(param_type.inner, arg_type.inner,
                                               inferred, param_names)
        elif isinstance(param_type, ResultType):
            if isinstance(arg_type, ResultType):
                self._unify_types_with_params(param_type.ok_type, arg_type.ok_type,
                                               inferred, param_names)
                self._unify_types_with_params(param_type.err_type, arg_type.err_type,
                                               inferred, param_names)

    def _unify_types(self, param_type: Type, arg_type: Type, inferred: Dict[str, Type]):
        """Unify a parameter type with an argument type to infer type parameters (legacy)"""
        # This version looks up params from current function - may not work correctly
        if isinstance(param_type, NamedType):
            # Check if it's a type parameter
            if param_type.name in [tp.name for tp in self.generic_functions.get(
                    self.current_function.name if self.current_function else "", 
                    FunctionDecl(FunctionKind.FUNC, "", [])).type_params]:
                # It's a type parameter - infer it
                if param_type.name not in inferred:
                    inferred[param_type.name] = arg_type
        elif isinstance(param_type, ListType):
            if isinstance(arg_type, ListType):
                self._unify_types(param_type.element_type, arg_type.element_type, inferred)
        elif isinstance(param_type, OptionalType):
            if isinstance(arg_type, OptionalType):
                self._unify_types(param_type.inner, arg_type.inner, inferred)
        elif isinstance(param_type, ResultType):
            if isinstance(arg_type, ResultType):
                self._unify_types(param_type.ok_type, arg_type.ok_type, inferred)
                self._unify_types(param_type.err_type, arg_type.err_type, inferred)

    def _register_enum_type(self, type_decl: TypeDecl):
        """Register an enum type as a tagged union"""
        name = f"struct.{type_decl.name}"
        struct_type = ir.global_context.get_identified_type(name)
        
        # Build variant info: {variant_name: (tag, [(field_name, field_type)])}
        variant_info = {}
        max_payload_size = 0
        
        for tag, variant in enumerate(type_decl.variants):
            fields = []
            payload_size = 0
            for field in variant.fields:
                fields.append((field.name, field.type_annotation))
                # Estimate 8 bytes per field
                payload_size += 8
            variant_info[variant.name] = (tag, fields)
            max_payload_size = max(max_payload_size, payload_size)
        
        # Create struct: { i64 tag, [max_payload_size x i8] payload }
        # Or simpler: { i64 tag, i64 f0, i64 f1, i64 f2, ... } for max fields
        max_fields = max(len(v.fields) for v in type_decl.variants) if type_decl.variants else 0
        
        # Build struct with tag + enough i64 fields for largest variant
        field_types = [ir.IntType(64)]  # tag
        for i in range(max_fields):
            field_types.append(ir.IntType(64))  # payload slots (all i64 for simplicity)
        
        struct_type.set_body(*field_types)
        
        # Store info
        self.type_registry[type_decl.name] = struct_type
        self.type_fields[type_decl.name] = [("_tag", PrimitiveType("int"))]
        self.type_methods[type_decl.name] = {}
        
        # Store variant info separately
        if not hasattr(self, 'enum_variants'):
            self.enum_variants = {}
        self.enum_variants[type_decl.name] = variant_info

        # Register enum type with GC for heap tracking
        if self.gc is not None:
            # Calculate size: (1 + max_fields) * 8 bytes
            size = (1 + max_fields) * 8
            # Compute reference field offsets across all variants
            ref_offsets = set()
            for variant_name, (tag, fields) in variant_info.items():
                for i, (_, field_type) in enumerate(fields):
                    if self._is_reference_type(field_type):
                        # Offset is (1 + field_index) * 8 (tag is at offset 0)
                        ref_offsets.add((1 + i) * 8)
            self.gc.register_type(type_decl.name, size, list(ref_offsets))

    def _method_uses_self(self, method) -> bool:
        """Check if a method body references 'self' or implicit field access.

        Methods that don't use self are static methods and don't get a self parameter.
        """
        from ast_nodes import (Identifier, MemberExpr, MethodCallExpr, Assignment,
                               IfStmt, WhileStmt, ForStmt, ForAssignStmt,
                               ReturnStmt, VarDecl, CallExpr, BinaryExpr, UnaryExpr,
                               TernaryExpr, IndexExpr, TupleExpr, ListExpr, MapExpr,
                               SetExpr, LambdaExpr, MatchStmt, SelectStmt, WithinStmt,
                               SelfExpr)

        def check_expr(expr) -> bool:
            """Recursively check if expression uses self"""
            if expr is None:
                return False
            if isinstance(expr, Identifier):
                return expr.name == "self"
            if isinstance(expr, SelfExpr):
                return True
            if isinstance(expr, MemberExpr):
                # Check if accessing self.field
                if isinstance(expr.object, SelfExpr):
                    return True
                if isinstance(expr.object, Identifier) and expr.object.name == "self":
                    return True
                return check_expr(expr.object)
            if isinstance(expr, MethodCallExpr):
                if check_expr(expr.object):
                    return True
                return any(check_expr(a) for a in expr.args)
            if isinstance(expr, CallExpr):
                return any(check_expr(a) for a in expr.args)
            if isinstance(expr, BinaryExpr):
                return check_expr(expr.left) or check_expr(expr.right)
            if isinstance(expr, UnaryExpr):
                return check_expr(expr.operand)
            if isinstance(expr, TernaryExpr):
                return check_expr(expr.condition) or check_expr(expr.then_expr) or check_expr(expr.else_expr)
            if isinstance(expr, IndexExpr):
                if check_expr(expr.object):
                    return True
                return check_expr(expr.index)
            if isinstance(expr, TupleExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, ListExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, MapExpr):
                return any(check_expr(k) or check_expr(v) for k, v in expr.pairs)
            if isinstance(expr, SetExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, LambdaExpr):
                return any(check_stmt(s) for s in (expr.body if isinstance(expr.body, list) else []))
            return False

        def check_stmt(stmt) -> bool:
            """Recursively check if statement uses self"""
            if stmt is None:
                return False
            if isinstance(stmt, ReturnStmt):
                return check_expr(stmt.value)
            if isinstance(stmt, VarDecl):
                return check_expr(stmt.initializer)
            if isinstance(stmt, Assignment):
                # Check if assigning to self.field
                target = stmt.target
                if isinstance(target, Identifier) and target.name == "self":
                    return True
                if isinstance(target, SelfExpr):
                    return True
                if isinstance(target, MemberExpr):
                    if isinstance(target.object, SelfExpr):
                        return True
                    if isinstance(target.object, Identifier) and target.object.name == "self":
                        return True
                return check_expr(stmt.target) or check_expr(stmt.value)
            if isinstance(stmt, IfStmt):
                if check_expr(stmt.condition):
                    return True
                if any(check_stmt(s) for s in stmt.then_body):
                    return True
                if any(check_stmt(s) for s in (stmt.else_body or [])):
                    return True
                return any(check_expr(c) or any(check_stmt(s) for s in b)
                          for c, b in (stmt.else_if_clauses or []))
            if isinstance(stmt, WhileStmt):
                return check_expr(stmt.condition) or any(check_stmt(s) for s in stmt.body)
            if isinstance(stmt, (ForStmt, ForAssignStmt)):
                return check_expr(stmt.iterable) or any(check_stmt(s) for s in stmt.body)
            if isinstance(stmt, MatchStmt):
                if check_expr(stmt.subject):
                    return True
                return any(any(check_stmt(s) for s in arm.body) for arm in stmt.arms)
            if hasattr(stmt, 'value') and stmt.value is not None:
                return check_expr(stmt.value)
            return False

        # Check all statements in method body
        for stmt in method.body:
            if check_stmt(stmt):
                return True
        return False

    def _declare_type_methods(self, type_decl: TypeDecl):
        """Declare all methods for a type"""
        # Skip generic types - methods are declared during monomorphization
        if type_decl.type_params:
            return

        struct_type = self.type_registry[type_decl.name]
        self_ptr_type = struct_type.as_pointer()

        for method in type_decl.methods:
            # Mangle name: TypeName_methodName
            mangled_name = f"{type_decl.name}_{method.name}"

            # Check if this is a static method (doesn't use self)
            is_static = not self._method_uses_self(method)
            self.static_methods[mangled_name] = is_static

            # Build parameter types
            param_types = []
            if not is_static:
                param_types.append(self_ptr_type)  # self pointer for instance methods
            for param in method.params:
                param_types.append(self._get_llvm_type(param.type_annotation))

            # Build return type
            if method.return_type:
                return_type = self._get_llvm_type(method.return_type)
            else:
                return_type = ir.VoidType()

            # Create function
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(self.module, func_type, name=mangled_name)

            # Name the self parameter for instance methods
            if not is_static and len(llvm_func.args) > 0:
                llvm_func.args[0].name = "self"

            self.functions[mangled_name] = llvm_func
            self.type_methods[type_decl.name][method.name] = mangled_name
    
    def _generate_type_methods(self, type_decl: TypeDecl):
        """Generate method bodies for a type"""
        # Skip generic types - methods are generated during monomorphization
        if type_decl.type_params:
            return

        struct_type = self.type_registry[type_decl.name]

        for method in type_decl.methods:
            mangled_name = self.type_methods[type_decl.name][method.name]
            llvm_func = self.functions[mangled_name]

            # Check if this is a static method
            is_static = self.static_methods.get(mangled_name, False)

            # Create entry block
            entry = llvm_func.append_basic_block(name="entry")
            self.builder = ir.IRBuilder(entry)

            # Clear locals and set context
            self.locals = {}
            self._reset_function_scope()
            self.current_function = method
            self.current_type = type_decl.name if not is_static else None

            if is_static:
                # Static method - no self parameter
                # Allocate parameters directly (no offset for self)
                for i, param in enumerate(method.params):
                    llvm_param = llvm_func.args[i]
                    llvm_param.name = param.name

                    alloca = self.builder.alloca(llvm_param.type, name=param.name)
                    self.builder.store(llvm_param, alloca)
                    self.locals[param.name] = alloca
            else:
                # Instance method - has self as first parameter
                # Store self pointer
                self_alloca = self.builder.alloca(llvm_func.args[0].type, name="self")
                self.builder.store(llvm_func.args[0], self_alloca)
                self.locals["self"] = self_alloca

                # Also make fields accessible directly by name
                self._setup_field_aliases(type_decl.name, self_alloca)

                # Allocate other parameters
                for i, param in enumerate(method.params):
                    llvm_param = llvm_func.args[i + 1]  # +1 for self
                    llvm_param.name = param.name

                    alloca = self.builder.alloca(llvm_param.type, name=param.name)
                    self.builder.store(llvm_param, alloca)
                    self.locals[param.name] = alloca

            # Generate body
            for stmt in method.body:
                self._generate_statement(stmt)
                if self.builder.block.is_terminated:
                    break

            # Add implicit return if needed
            if not self.builder.block.is_terminated:
                if isinstance(llvm_func.return_value.type, ir.VoidType):
                    self.builder.ret_void()
                else:
                    self.builder.ret(ir.Constant(llvm_func.return_value.type, 0))
            
            self.current_type = None
            self.current_function = None
    
    def _setup_field_aliases(self, type_name: str, self_alloca):
        """Make struct fields accessible as local variables"""
        # This allows 'x' instead of 'self.x' in methods
        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]
        
        # We don't actually create allocas - we'll handle field access specially
        # Store field info for the identifier lookup
        pass  # Fields accessed via _generate_identifier with current_type set
    
    def _get_field_index(self, type_name: str, field_name: str) -> Optional[int]:
        """Get the index of a field in a struct"""
        if type_name not in self.type_fields:
            return None
        field_info = self.type_fields[type_name]
        for i, (name, _) in enumerate(field_info):
            if name == field_name:
                return i
        return None

    def _get_c_type(self, coex_type: Type) -> ir.Type:
        """Get LLVM type for C ABI.

        Coex int is 64-bit, so we map to int64_t for C compatibility.
        C code should use int64_t or ssize_t for Coex int parameters.
        """
        if isinstance(coex_type, PrimitiveType):
            if coex_type.name == "int":
                return ir.IntType(64)  # Coex int is 64-bit, use int64_t in C
            elif coex_type.name == "float":
                return ir.DoubleType()  # C double
            elif coex_type.name == "bool":
                return ir.IntType(32)  # C int for bool
            elif coex_type.name == "string":
                return ir.IntType(8).as_pointer()  # C char*
        # For other types, use the Coex LLVM type
        return self._get_llvm_type(coex_type)

    def _convert_to_c_type(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Convert a Coex value to C ABI type for extern call.

        Since Coex int is 64-bit and maps to C int64_t, no conversion needed.
        Only string requires special handling (struct to char*).
        """
        if isinstance(coex_type, PrimitiveType):
            if coex_type.name == "string":
                # Coex string is struct, C needs char*
                # Get the data pointer from the string struct using string_data
                return self.builder.call(self.string_data, [value])
            # int, float, bool: no conversion needed (same ABI)
        return value

    def _convert_from_c_type(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Convert a C return value back to Coex type.

        Since Coex int is 64-bit and maps to C int64_t, no conversion needed.
        For most types, the value passes through unchanged.
        """
        # No conversion needed - types match between Coex and C ABI
        return value

    def _declare_function(self, func: FunctionDecl):
        """Declare a function (for forward references)"""
        # If generic, store as template
        if func.type_params:
            self.generic_functions[func.name] = func
            return

        # Special handling for main() with parameters
        if func.name == "main" and func.params:
            self._declare_main_with_params(func)
            return

        # Handle extern functions (FFI to C)
        if func.kind == FunctionKind.EXTERN:
            self._declare_extern_function(func)
            return

        # Build parameter types
        param_types = []
        for param in func.params:
            param_types.append(self._get_llvm_type(param.type_annotation))

        # Build return type
        if func.return_type:
            return_type = self._get_llvm_type(func.return_type)
        else:
            return_type = ir.VoidType()

        # Create function
        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(self.module, func_type, name=func.name)
        self.functions[func.name] = llvm_func

    def _declare_extern_function(self, func: FunctionDecl):
        """Declare an extern function (external C linkage, no body).

        Extern functions are FFI boundaries to C code. They use C ABI types
        and are declared with external linkage so the linker can resolve them.
        """
        # Track this extern function for calling hierarchy validation
        self.extern_function_decls = getattr(self, 'extern_function_decls', {})
        self.extern_function_decls[func.name] = func

        # Build C ABI parameter types
        c_param_types = []
        for param in func.params:
            c_param_types.append(self._get_c_type(param.type_annotation))

        # Build C ABI return type
        if func.return_type:
            c_return_type = self._get_c_type(func.return_type)
        else:
            c_return_type = ir.VoidType()

        # Check if already declared in the module
        if func.name in self.module.globals:
            # Use the existing declaration
            self.functions[func.name] = self.module.globals[func.name]
            return

        # Declare the external function
        func_type = ir.FunctionType(c_return_type, c_param_types)
        llvm_func = ir.Function(self.module, func_type, name=func.name)
        llvm_func.linkage = 'external'
        self.functions[func.name] = llvm_func

    def _generate_extern_call(self, name: str, args: list, func_decl: FunctionDecl) -> ir.Value:
        """Generate a call to an extern function with C ABI type conversion.

        Extern functions can only be called from func (not formula or task).
        Arguments are converted from Coex types to C ABI types, and return
        values are converted back.
        """
        # Validate calling hierarchy: only func can call extern
        if hasattr(self, 'current_function') and self.current_function:
            caller_kind = self.current_function.kind
            if caller_kind == FunctionKind.FORMULA:
                raise RuntimeError(
                    f"Cannot call extern function '{name}' from formula "
                    f"'{self.current_function.name}'. Extern functions can only "
                    f"be called from func."
                )
            elif caller_kind == FunctionKind.TASK:
                raise RuntimeError(
                    f"Cannot call extern function '{name}' from task "
                    f"'{self.current_function.name}'. Extern functions can only "
                    f"be called from func."
                )

        llvm_func = self.functions[name]

        # Convert Coex arguments to C ABI types
        c_args = []
        for i, arg in enumerate(args):
            arg_val = self._generate_expression(arg)
            if i < len(func_decl.params):
                c_arg = self._convert_to_c_type(arg_val, func_decl.params[i].type_annotation)
            else:
                c_arg = arg_val
            c_args.append(c_arg)

        # Call the extern function
        if isinstance(llvm_func.return_value.type, ir.VoidType):
            self.builder.call(llvm_func, c_args)
            return ir.Constant(ir.IntType(64), 0)
        else:
            c_result = self.builder.call(llvm_func, c_args)
            # Convert C result back to Coex type
            if func_decl.return_type:
                return self._convert_from_c_type(c_result, func_decl.return_type)
            return c_result

    def _declare_main_with_params(self, func: FunctionDecl):
        """Handle main() function with special parameters (args, stdin, stdout, stderr).

        Supported signatures:
        1. func main(args: [string]) -> int
        2. func main(stdin: posix, stdout: posix, stderr: posix) -> int
        3. func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
        """
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        # Detect which signature is being used
        has_args = False
        has_stdio = False

        for param in func.params:
            if param.name == "args":
                has_args = True
            elif param.name in ("stdin", "stdout", "stderr"):
                has_stdio = True

        # Build parameter types for user's main (coex_main_impl)
        impl_param_types = []
        if has_args:
            impl_param_types.append(self.list_struct.as_pointer())  # [string] is a List*
        if has_stdio:
            impl_param_types.append(self.posix_struct.as_pointer())  # stdin: posix*
            impl_param_types.append(self.posix_struct.as_pointer())  # stdout: posix*
            impl_param_types.append(self.posix_struct.as_pointer())  # stderr: posix*

        # Create user's main as coex_main_impl
        impl_func_type = ir.FunctionType(i64, impl_param_types)
        impl_func = ir.Function(self.module, impl_func_type, name="coex_main_impl")
        self.functions["main"] = impl_func  # Store as "main" so _generate_function finds it

        # Store signature info for later use in _generate_main_wrapper
        self.main_has_args = has_args
        self.main_has_stdio = has_stdio

        # Create C main wrapper: int main(int argc, char** argv)
        c_main_type = ir.FunctionType(i32, [i32, i8_ptr.as_pointer()])
        c_main = ir.Function(self.module, c_main_type, name="main")
        c_main.args[0].name = "argc"
        c_main.args[1].name = "argv"

        # Implement the C main wrapper
        entry = c_main.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Initialize GC before building args array (which uses GC allocations)
        if self.gc is not None:
            builder.call(self.gc.gc_init, [])

        call_args = []

        if has_args:
            # Convert argc/argv to [string]
            argc = c_main.args[0]
            argv = c_main.args[1]

            # Create new list for strings (elem_size = 8 for pointers)
            elem_size = ir.Constant(i64, 8)
            args_list = builder.call(self.list_new, [elem_size])

            # Store in alloca for list_append (which returns new list)
            args_alloca = builder.alloca(self.list_struct.as_pointer(), name="args_list")
            builder.store(args_list, args_alloca)

            # Loop through argv and convert each to string
            idx_alloca = builder.alloca(i32, name="arg_idx")
            builder.store(ir.Constant(i32, 0), idx_alloca)

            cond_block = c_main.append_basic_block("args_cond")
            body_block = c_main.append_basic_block("args_body")
            end_block = c_main.append_basic_block("args_end")

            builder.branch(cond_block)

            # Condition: idx < argc
            builder.position_at_end(cond_block)
            idx = builder.load(idx_alloca)
            cond = builder.icmp_signed("<", idx, argc)
            builder.cbranch(cond, body_block, end_block)

            # Body: convert argv[idx] to string, append to list
            builder.position_at_end(body_block)
            idx = builder.load(idx_alloca)
            idx_64 = builder.sext(idx, i64)

            # Get argv[idx]
            arg_ptr_ptr = builder.gep(argv, [idx_64])
            c_str = builder.load(arg_ptr_ptr)

            # Convert C string to Coex string using string_from_literal
            coex_string = builder.call(self.string_from_literal, [c_str])

            # Append to list: we need to store the string pointer and pass its address
            str_alloca = builder.alloca(self.string_struct.as_pointer(), name="str_temp")
            builder.store(coex_string, str_alloca)

            current_list = builder.load(args_alloca)
            new_list = builder.call(self.list_append, [current_list,
                                                        builder.bitcast(str_alloca, i8_ptr),
                                                        elem_size])
            builder.store(new_list, args_alloca)

            # Increment index
            next_idx = builder.add(idx, ir.Constant(i32, 1))
            builder.store(next_idx, idx_alloca)
            builder.branch(cond_block)

            # End - get final list
            builder.position_at_end(end_block)
            final_args_list = builder.load(args_alloca)
            call_args.append(final_args_list)

        if has_stdio:
            # Create posix handles for stdin (fd=0), stdout (fd=1), stderr (fd=2)
            for fd_num, name in [(0, "stdin_posix"), (1, "stdout_posix"), (2, "stderr_posix")]:
                # Allocate posix struct
                posix_alloca = builder.alloca(self.posix_struct, name=name)

                # Set fd field
                fd_ptr = builder.gep(posix_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
                builder.store(ir.Constant(i32, fd_num), fd_ptr)

                call_args.append(posix_alloca)

        # Call user's main implementation
        result = builder.call(impl_func, call_args)

        # Truncate i64 to i32 for C return
        result_32 = builder.trunc(result, i32)
        builder.ret(result_32)

    def _collect_heap_vars_from_body(self, stmts: PyList[Stmt]) -> PyList[str]:
        """Collect names of heap-typed variable declarations from function body.

        Recursively traverses the AST to find all VarDecl statements with heap types.
        Returns a list of variable names that need GC root tracking.
        """
        heap_vars = []

        def visit_stmts(statements):
            for stmt in statements:
                if isinstance(stmt, VarDecl):
                    # Check explicit type annotation first
                    if stmt.type_annotation and self._is_heap_type(stmt.type_annotation):
                        heap_vars.append(stmt.name)
                    # Also check inferred type from initializer expression
                    elif stmt.initializer and not stmt.type_annotation:
                        inferred_type = self._infer_type_from_expr(stmt.initializer)
                        if self._is_heap_type(inferred_type):
                            heap_vars.append(stmt.name)
                # Recurse into nested blocks
                if isinstance(stmt, IfStmt):
                    visit_stmts(stmt.then_body)
                    for _, elif_body in stmt.else_if_clauses:
                        visit_stmts(elif_body)
                    if stmt.else_body:
                        visit_stmts(stmt.else_body)
                elif isinstance(stmt, (ForStmt, ForAssignStmt)):
                    visit_stmts(stmt.body)
                elif isinstance(stmt, WhileStmt):
                    visit_stmts(stmt.body)
                elif isinstance(stmt, MatchStmt):
                    for arm in stmt.arms:
                        visit_stmts(arm.body)
                elif isinstance(stmt, TupleDestructureStmt):
                    # Check if value is a function call with a tuple return type
                    if isinstance(stmt.value, CallExpr) and isinstance(stmt.value.callee, Identifier):
                        func_name = stmt.value.callee.name
                        if func_name in self.func_decls:
                            func_decl = self.func_decls[func_name]
                            if func_decl.return_type and isinstance(func_decl.return_type, TupleType):
                                # Check which tuple elements are heap types
                                for i, name in enumerate(stmt.names):
                                    if i < len(func_decl.return_type.elements):
                                        _, elem_type = func_decl.return_type.elements[i]
                                        if self._is_heap_type(elem_type):
                                            heap_vars.append(name)

        visit_stmts(stmts)
        return heap_vars

    def _generate_function(self, func: FunctionDecl):
        """Generate a function body"""
        # Skip generic functions (they're generated on demand)
        if func.type_params:
            return

        # Skip extern functions (they have no body, external linkage only)
        if func.kind == FunctionKind.EXTERN:
            return

        llvm_func = self.functions[func.name]

        # Create entry block
        entry = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)

        # Initialize GC at start of main function
        # Skip if main has params (args/stdio) - gc_init is called in the C main wrapper
        if func.name == "main" and self.gc is not None:
            if not getattr(self, 'main_has_args', False) and not getattr(self, 'main_has_stdio', False):
                self.gc.inject_gc_init(self.builder)

        # Clear locals and moved variables for this function scope
        self.locals = {}
        self._reset_function_scope()
        self.moved_vars = set()
        self.current_function = func

        # ====================================================================
        # GC Shadow Stack Integration
        # ====================================================================
        # Count heap pointer parameters and locals for GC root tracking
        heap_var_names = []  # List of (var_name) in order

        # Check parameters for heap types
        for param in func.params:
            if param.type_annotation and self._is_heap_type(param.type_annotation):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self._collect_heap_vars_from_body(func.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables and GC is enabled
        self.gc_frame = None
        self.gc_roots = None
        self.gc_root_indices = {}

        if heap_var_names and self.gc is not None:
            num_roots = len(heap_var_names)
            self.gc_roots = self.gc.create_frame_roots(self.builder, num_roots)
            self.gc_frame = self.gc.push_frame(self.builder, num_roots, self.gc_roots)

            # Store mapping of var_name -> root_index
            self.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}
        # ====================================================================

        # GC Safe-point check: trigger GC if allocation threshold exceeded
        # This is safe because we're at function entry with no intermediate allocations
        if self.gc is not None and func.name != "main":
            self.gc.inject_safepoint(self.builder)

        # Allocate parameters with value semantics (deep copy heap-allocated types)
        for i, param in enumerate(func.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name

            # Track Coex AST type for method calls on collections (e.g., list.get())
            if param.type_annotation:
                self.var_coex_types[param.name] = param.type_annotation

            # Most heap types don't need copying (immutable collections)
            # UDTs with mutable fields still need copying
            param_value = llvm_param
            if self._needs_parameter_copy(param.type_annotation):
                param_value = self._generate_deep_copy(llvm_param, param.type_annotation)

            # Allocate on stack and store the value
            alloca = self.builder.alloca(llvm_param.type, name=param.name)
            self.builder.store(param_value, alloca)
            self.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in self.gc_root_indices and self.gc is not None:
                root_idx = self.gc_root_indices[param.name]
                self.gc.set_root(self.builder, self.gc_roots, root_idx, param_value)

        # Generate body
        for stmt in func.body:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break

        # Add implicit return if needed
        if not self.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            if isinstance(llvm_func.return_value.type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(llvm_func.return_value.type, 0))

        # Clear GC state for this function
        self.gc_frame = None
        self.gc_roots = None
        self.gc_root_indices = {}
        self.current_function = None
    
    # ========================================================================
    # Scope Management
    # ========================================================================

    def _enter_scope(self):
        """Enter a new block scope (if, for, while, etc.)."""
        self.scope_depth += 1
        self.scope_stack.append([])

    def _exit_scope(self):
        """Exit the current block scope, removing variables declared in it."""
        if self.scope_depth > 0:
            # Get variables declared in this scope
            vars_in_scope = self.scope_stack.pop()
            # Remove them from locals and var_scopes
            for var_name in vars_in_scope:
                if var_name in self.locals:
                    del self.locals[var_name]
                if var_name in self.var_scopes:
                    del self.var_scopes[var_name]
            self.scope_depth -= 1

    def _register_var_in_scope(self, var_name: str):
        """Register a variable as being declared in the current scope."""
        self.var_scopes[var_name] = self.scope_depth
        if self.scope_stack:
            self.scope_stack[-1].append(var_name)

    def _reset_function_scope(self):
        """Reset scope tracking for a new function."""
        self.scope_depth = 0
        self.var_scopes = {}
        self.scope_stack = [[]]

    def _emit_warning(self, category: str, message: str, line: int = None):
        """Emit a compiler warning that will be written as a #@ comment.

        Categories:
        - PERF: Performance-related warning (e.g., implicit conversion)
        - WARN: General warning
        - HINT: Suggestion for improvement
        """
        self.warnings.append({
            'line': line or self.current_line,
            'column': 1,
            'category': category,
            'message': message
        })

    def get_warnings(self) -> PyList[Dict]:
        """Return the list of collected warnings."""
        return self.warnings

    # ========================================================================
    # Statement Generation
    # ========================================================================

    def _generate_statement(self, stmt: Stmt):
        """Generate code for a statement"""
        if isinstance(stmt, VarDecl):
            self._generate_var_decl(stmt)
        elif isinstance(stmt, TupleDestructureStmt):
            self._generate_tuple_destructure(stmt)
        elif isinstance(stmt, Assignment):
            self._generate_assignment(stmt)
        elif isinstance(stmt, SliceAssignment):
            self._generate_slice_assignment(stmt)
        elif isinstance(stmt, ReturnStmt):
            self._generate_return(stmt)
        elif isinstance(stmt, PrintStmt):
            self._generate_print(stmt)
        elif isinstance(stmt, DebugStmt):
            self._generate_debug(stmt)
        elif isinstance(stmt, IfStmt):
            self._generate_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._generate_while(stmt)
        elif isinstance(stmt, CycleStmt):
            self._generate_cycle(stmt)
        elif isinstance(stmt, ForStmt):
            self._generate_for(stmt)
        elif isinstance(stmt, ForAssignStmt):
            self._generate_for_assign(stmt)
        elif isinstance(stmt, BreakStmt):
            self._generate_break()
        elif isinstance(stmt, ContinueStmt):
            self._generate_continue()
        elif isinstance(stmt, MatchStmt):
            self._generate_match(stmt)
        elif isinstance(stmt, LlvmIrStmt):
            self._generate_llvm_ir_block(stmt)
        elif isinstance(stmt, ExprStmt):
            self._generate_expression(stmt.expr)
    
    def _generate_var_decl(self, stmt: VarDecl):
        """Generate a local variable declaration or reassignment"""
        # Track whether this is a new variable for scope registration
        is_new_var = stmt.name not in self.locals

        # Formulas require const bindings for purity
        if not stmt.is_const and self.current_function is not None:
            if self.current_function.kind == FunctionKind.FORMULA:
                raise RuntimeError(
                    f"Formula '{self.current_function.name}' requires const bindings. "
                    f"Use 'const {stmt.name} = ...' instead of '{stmt.name} = ...'."
                )

        # Handle reassignment vs new binding based on 'const' keyword:
        # - const x = ...: ALWAYS create new binding (shadows if name exists)
        # - x = ...: reassign if exists, create new if not
        if not stmt.is_const and stmt.name in self.locals:
            # Variable exists and this is NOT a const declaration -> possible reassignment
            # But first check if this is a pre-allocated placeholder that needs proper typing
            is_placeholder = stmt.name in self.placeholder_vars

            if not is_placeholder:
                # This is a properly typed variable - do reassignment
                # Check if target is a const binding
                if stmt.name in self.const_bindings:
                    raise RuntimeError(
                        f"Cannot reassign const binding '{stmt.name}'. "
                        f"Remove 'const' from the declaration to make it rebindable."
                    )
                # Perform reassignment
                self._generate_var_reassignment(stmt)
                return
            # else: fall through to new binding logic to upgrade the placeholder

        # Track const bindings
        if stmt.is_const:
            self.const_bindings.add(stmt.name)

        # Check if this is a cycle variable - write to write buffer
        ctx = self._get_cycle_context()
        if ctx and stmt.name in ctx['cycle_vars']:
            # Initialize by writing to write buffer
            init_value = self._generate_expression(stmt.initializer)
            write_buf = ctx['write_buffers'][stmt.name]
            # Cast to expected type if needed
            expected_type = ctx['var_types'].get(stmt.name)
            if expected_type:
                init_value = self._cast_value(init_value, expected_type)
            self.builder.store(init_value, write_buf)
            return

        # Track if we need to mark source as moved AFTER reading
        move_source_name = None
        if stmt.is_move and isinstance(stmt.initializer, Identifier):
            move_source_name = stmt.initializer.name

        if stmt.type_annotation:
            llvm_type = self._get_llvm_type(stmt.type_annotation)
            # Track Coex AST type for deep copy and nested collection support
            self.var_coex_types[stmt.name] = stmt.type_annotation
            # Track tuple field info if this is a tuple type
            if isinstance(stmt.type_annotation, TupleType):
                self.tuple_field_info[stmt.name] = stmt.type_annotation.elements
        else:
            # Infer type from initializer
            init_value = self._generate_expression(stmt.initializer)
            llvm_type = init_value.type

            # Check if variable was pre-allocated (e.g., by loop optimization)
            # If so, reuse the existing alloca if types are compatible
            if stmt.name in self.locals:
                existing_alloca = self.locals[stmt.name]
                existing_type = existing_alloca.type.pointee

                # If types match, reuse the existing alloca
                if existing_type == llvm_type:
                    alloca = existing_alloca
                elif isinstance(existing_type, ir.IntType) and existing_type.width == 64:
                    # Pre-allocated as i64 placeholder but needs different type
                    # Create proper alloca ONCE at function entry (not in loop)
                    # Use entry block for alloca to avoid stack growth in loops
                    func = self.builder.function
                    entry_block = func.entry_basic_block
                    current_block = self.builder.block

                    # Save current position
                    saved_block = self.builder.block
                    saved_pos = self.builder._anchor

                    # Insert at end of entry block (before terminator if any)
                    if entry_block.is_terminated:
                        # Position before the terminator
                        self.builder.position_before(entry_block.terminator)
                    else:
                        self.builder.position_at_end(entry_block)

                    alloca = self.builder.alloca(llvm_type, name=f"{stmt.name}.typed")

                    # Restore position
                    self.builder.position_at_end(saved_block)

                    # Update locals to use new alloca
                    self.locals[stmt.name] = alloca
                else:
                    # Different non-placeholder type - create new alloca
                    alloca = self.builder.alloca(llvm_type, name=stmt.name)
            else:
                alloca = self.builder.alloca(llvm_type, name=stmt.name)

            # Value semantics: deep copy collections on assignment to prevent aliasing
            # Try to get Coex type from initializer for proper deep copy
            inferred_coex_type = None
            if isinstance(stmt.initializer, Identifier):
                var_name = stmt.initializer.name
                if var_name in self.var_coex_types:
                    inferred_coex_type = self.var_coex_types[var_name]
            elif isinstance(stmt.initializer, (MapExpr, ListExpr, SetExpr)):
                # Infer type from literal expression
                inferred_coex_type = self._infer_type_from_expr(stmt.initializer)
                self.var_coex_types[stmt.name] = inferred_coex_type
            elif isinstance(stmt.initializer, StringLiteral):
                # Track string type for split() method type inference
                self.var_coex_types[stmt.name] = PrimitiveType("string")
            elif isinstance(stmt.initializer, MethodCallExpr):
                # If initializer is a method call on a collection (e.g., list.set()),
                # propagate the type from the receiver
                if isinstance(stmt.initializer.object, Identifier):
                    receiver_name = stmt.initializer.object.name
                    if receiver_name in self.var_coex_types:
                        receiver_type = self.var_coex_types[receiver_name]
                        # Methods that return same collection type
                        if stmt.initializer.method in ("set", "append", "remove", "pop", "insert"):
                            inferred_coex_type = receiver_type
                            self.var_coex_types[stmt.name] = inferred_coex_type
                        # String.split() returns List<String>
                        elif stmt.initializer.method == "split" and isinstance(receiver_type, PrimitiveType) and receiver_type.name == "string":
                            inferred_coex_type = ListType(PrimitiveType("string"))
                            self.var_coex_types[stmt.name] = inferred_coex_type
            elif isinstance(stmt.initializer, CallExpr):
                # Check if this is a method call (callee is MemberExpr: obj.method(...))
                if isinstance(stmt.initializer.callee, MemberExpr):
                    callee_member = stmt.initializer.callee
                    method_name = callee_member.member
                    # Find the innermost receiver (handles chained calls like a.set(0, x).set(1, y))
                    receiver_type = self._get_receiver_type(callee_member.object)
                    if receiver_type:
                        # Methods that return same collection type
                        if method_name in ("set", "append", "remove", "pop", "insert"):
                            inferred_coex_type = receiver_type
                            self.var_coex_types[stmt.name] = inferred_coex_type
                        # String.split() returns List<String>
                        elif method_name == "split" and isinstance(receiver_type, PrimitiveType) and receiver_type.name == "string":
                            inferred_coex_type = ListType(PrimitiveType("string"))
                            self.var_coex_types[stmt.name] = inferred_coex_type

            if inferred_coex_type and self._is_collection_coex_type(inferred_coex_type):
                # Use move semantics for := operator, deep copy for =
                if stmt.is_move:
                    init_value = self._generate_move_or_eager_copy(init_value, inferred_coex_type)
                else:
                    init_value = self._generate_deep_copy(init_value, inferred_coex_type)
                # Track the inferred type for this variable too
                self.var_coex_types[stmt.name] = inferred_coex_type
            elif isinstance(init_value.type, ir.PointerType):
                # Fallback to shallow copy for unknown collection types
                pointee = init_value.type.pointee
                if hasattr(pointee, 'name'):
                    if pointee.name == "struct.List":
                        init_value = self.builder.call(self.list_copy, [init_value])
                    elif pointee.name == "struct.Set":
                        init_value = self.builder.call(self.set_copy, [init_value])
                    elif pointee.name == "struct.Map":
                        init_value = self.builder.call(self.map_copy, [init_value])
                    elif pointee.name == "struct.String":
                        init_value = self.builder.call(self.string_copy, [init_value])
                    elif pointee.name == "struct.Array":
                        # Use move semantics for := on Array
                        if stmt.is_move:
                            init_value = self._generate_move_or_eager_copy(init_value, ArrayType(PrimitiveType("int")))
                        else:
                            init_value = self.builder.call(self.array_copy, [init_value])

            self.builder.store(init_value, alloca)
            self.locals[stmt.name] = alloca

            # Register new variable in current scope for proper scoping
            if is_new_var:
                self._register_var_in_scope(stmt.name)

            # Register as GC root if this is a heap type
            if stmt.name in self.gc_root_indices and self.gc is not None:
                root_idx = self.gc_root_indices[stmt.name]
                self.gc.set_root(self.builder, self.gc_roots, root_idx, init_value)

            # Try to infer tuple info from initializer
            tuple_info = self._infer_tuple_info(stmt.initializer)
            if tuple_info:
                self.tuple_field_info[stmt.name] = tuple_info

            # Mark source as moved AFTER we've read its value
            if move_source_name:
                self.moved_vars.add(move_source_name)
            return

        # Check if variable was pre-allocated (e.g., by loop optimization)
        if stmt.name in self.locals:
            existing_alloca = self.locals[stmt.name]
            existing_type = existing_alloca.type.pointee

            if existing_type == llvm_type:
                alloca = existing_alloca
            elif isinstance(existing_type, ir.IntType) and existing_type.width == 64:
                # Pre-allocated as i64 placeholder but needs different type
                # Create proper alloca at function entry
                func = self.builder.function
                entry_block = func.entry_basic_block
                saved_block = self.builder.block

                if entry_block.is_terminated:
                    self.builder.position_before(entry_block.terminator)
                else:
                    self.builder.position_at_end(entry_block)

                alloca = self.builder.alloca(llvm_type, name=f"{stmt.name}.typed")
                self.builder.position_at_end(saved_block)
                self.locals[stmt.name] = alloca
            else:
                alloca = self.builder.alloca(llvm_type, name=stmt.name)
        else:
            alloca = self.builder.alloca(llvm_type, name=stmt.name)

        # Generate initializer
        # Handle nil assignment to optional type
        if isinstance(stmt.initializer, NilLiteral) and isinstance(stmt.type_annotation, OptionalType):
            # Generate nil optional directly: {has_value=false, value=0}
            inner_type = self._get_llvm_type(stmt.type_annotation.inner)
            init_value = ir.Constant(llvm_type, ir.Undefined)
            init_value = self.builder.insert_value(init_value, ir.Constant(ir.IntType(1), 0), 0)
            if isinstance(inner_type, ir.IntType):
                init_value = self.builder.insert_value(init_value, ir.Constant(inner_type, 0), 1)
            elif isinstance(inner_type, ir.DoubleType):
                init_value = self.builder.insert_value(init_value, ir.Constant(inner_type, 0.0), 1)
            else:
                init_value = self.builder.insert_value(init_value, ir.Constant(inner_type, None), 1)
        # Handle empty {} which parses as JsonObjectExpr or MapExpr but might need to be Set or Map based on type annotation
        elif (isinstance(stmt.initializer, MapExpr) and len(stmt.initializer.entries) == 0) or \
             (isinstance(stmt.initializer, JsonObjectExpr) and len(stmt.initializer.entries) == 0):
            if isinstance(stmt.type_annotation, SetType):
                # Empty {} with Set type annotation -> generate empty set
                i64 = ir.IntType(64)
                flags = self._compute_set_flags(stmt.type_annotation.element_type)
                init_value = self.builder.call(self.set_new, [ir.Constant(i64, flags)])
            elif isinstance(stmt.type_annotation, MapType):
                # Empty {} with Map type annotation -> generate empty map with correct flags
                i64 = ir.IntType(64)
                flags = self._compute_map_flags(stmt.type_annotation.key_type, stmt.type_annotation.value_type)
                init_value = self.builder.call(self.map_new, [ir.Constant(i64, flags)])
            else:
                # Default to JSON (which is what JsonObjectExpr([]) generates)
                init_value = self._generate_expression(stmt.initializer)
        # Handle assignment to json type - convert primitives to JSON
        elif isinstance(stmt.type_annotation, PrimitiveType) and stmt.type_annotation.name == "json":
            init_value = self._generate_expression(stmt.initializer)
            init_value = self._convert_to_json(init_value, stmt.initializer)
        else:
            init_value = self._generate_expression(stmt.initializer)

        # Try implicit collection conversion (List <-> Array <-> Set)
        # This allows assigning e.g. a List to an Array variable with a warning
        if isinstance(stmt.type_annotation, (ListType, ArrayType, SetType)):
            converted_value, was_converted = self._try_implicit_collection_conversion(
                init_value, stmt.type_annotation
            )
            if was_converted:
                # Emit a warning about the implicit conversion
                source_struct = init_value.type.pointee.name if isinstance(init_value.type, ir.PointerType) else "unknown"
                warning_msg = self._get_conversion_warning_message(source_struct,
                    "struct.List" if isinstance(stmt.type_annotation, ListType) else
                    "struct.Array" if isinstance(stmt.type_annotation, ArrayType) else "struct.Set")
                self._emit_warning("PERF", warning_msg)
                init_value = converted_value

        # Cast if needed
        init_value = self._cast_value(init_value, llvm_type)

        # Value semantics: deep copy or move collections on assignment to prevent aliasing
        # We have the Coex type annotation, so use it for proper copy
        if self._is_collection_coex_type(stmt.type_annotation):
            # Use move semantics for := operator, deep copy for =
            if stmt.is_move:
                init_value = self._generate_move_or_eager_copy(init_value, stmt.type_annotation)
            else:
                init_value = self._generate_deep_copy(init_value, stmt.type_annotation)
        elif isinstance(init_value.type, ir.PointerType):
            # User-defined types may need deep copy too
            if isinstance(stmt.type_annotation, NamedType) and stmt.type_annotation.name in self.type_fields:
                if stmt.is_move:
                    init_value = self._generate_move_or_eager_copy(init_value, stmt.type_annotation)
                else:
                    init_value = self._generate_deep_copy(init_value, stmt.type_annotation)

        self.builder.store(init_value, alloca)
        self.locals[stmt.name] = alloca

        # Register new variable in current scope for proper scoping
        if is_new_var:
            self._register_var_in_scope(stmt.name)

        # Variable is now properly typed, remove from placeholders
        self.placeholder_vars.discard(stmt.name)

        # Register as GC root if this is a heap type
        if stmt.name in self.gc_root_indices and self.gc is not None:
            root_idx = self.gc_root_indices[stmt.name]
            self.gc.set_root(self.builder, self.gc_roots, root_idx, init_value)

        # Mark source as moved AFTER we've read its value
        if move_source_name:
            self.moved_vars.add(move_source_name)

    def _generate_var_reassignment(self, stmt: VarDecl):
        """Generate reassignment to an existing variable (x = value where x exists)"""
        # Get the existing alloca
        alloca = self.locals[stmt.name]

        # Track if we need to mark source as moved
        move_source_name = None
        if stmt.is_move and isinstance(stmt.initializer, Identifier):
            move_source_name = stmt.initializer.name

        # Generate the value
        value = self._generate_expression(stmt.initializer)

        # Get expected type from alloca
        expected_type = alloca.type.pointee

        # Cast if needed
        value = self._cast_value(value, expected_type)

        # Handle value semantics for collections
        coex_type = self.var_coex_types.get(stmt.name)
        if coex_type and self._is_collection_coex_type(coex_type):
            if stmt.is_move:
                value = self._generate_move_or_eager_copy(value, coex_type)
            else:
                value = self._generate_deep_copy(value, coex_type)
        elif isinstance(value.type, ir.PointerType):
            pointee = value.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    if not stmt.is_move:
                        value = self.builder.call(self.list_copy, [value])
                elif pointee.name == "struct.Set":
                    if not stmt.is_move:
                        value = self.builder.call(self.set_copy, [value])
                elif pointee.name == "struct.Map":
                    if not stmt.is_move:
                        value = self.builder.call(self.map_copy, [value])
                elif pointee.name == "struct.String":
                    if not stmt.is_move:
                        value = self.builder.call(self.string_copy, [value])
                elif pointee.name == "struct.Array":
                    if not stmt.is_move:
                        value = self.builder.call(self.array_copy, [value])

        # Store the value
        self.builder.store(value, alloca)

        # Update GC root if needed
        if stmt.name in self.gc_root_indices and self.gc is not None:
            root_idx = self.gc_root_indices[stmt.name]
            self.gc.set_root(self.builder, self.gc_roots, root_idx, value)

        # Mark source as moved
        if move_source_name:
            self.moved_vars.add(move_source_name)

        # Clear moved status for target (variable is now valid again)
        if stmt.name in self.moved_vars:
            self.moved_vars.discard(stmt.name)

    def _infer_tuple_info(self, expr: Expr) -> Optional[PyList[tuple]]:
        """Infer tuple field info from an expression"""
        if isinstance(expr, TupleExpr):
            # Direct tuple literal - use its element names
            return expr.elements
        elif isinstance(expr, CallExpr):
            # Function call - check if it returns a tuple with named fields
            if isinstance(expr.callee, Identifier):
                func_name = expr.callee.name
                # Look up function declaration
                if func_name in self.func_decls:
                    func_decl = self.func_decls[func_name]
                    if isinstance(func_decl.return_type, TupleType):
                        return func_decl.return_type.elements
                # Check generic functions
                if func_name in self.generic_functions:
                    func_decl = self.generic_functions[func_name]
                    if isinstance(func_decl.return_type, TupleType):
                        return func_decl.return_type.elements
        return None
    
    def _generate_tuple_destructure(self, stmt: 'TupleDestructureStmt'):
        """Generate code for tuple destructuring: (a, b) = expr"""
        # Generate the tuple value
        tuple_val = self._generate_expression(stmt.value)

        # Check if it's a struct type (tuple)
        if isinstance(tuple_val.type, ir.LiteralStructType):
            # Extract each element and assign to a variable
            for i, name in enumerate(stmt.names):
                if i < len(tuple_val.type.elements):
                    elem_type = tuple_val.type.elements[i]
                    # Extract the element
                    elem_val = self.builder.extract_value(tuple_val, i)

                    # Reuse existing alloca if variable already exists (avoids stack leak in loops)
                    if name in self.locals:
                        alloca = self.locals[name]
                        # Cast value if needed (e.g., if alloca type differs)
                        if alloca.type.pointee != elem_type:
                            elem_val = self._cast_value(elem_val, alloca.type.pointee)
                        self.builder.store(elem_val, alloca)
                    else:
                        # First time seeing this variable - allocate
                        alloca = self.builder.alloca(elem_type, name=name)
                        self.builder.store(elem_val, alloca)
                        self.locals[name] = alloca

                    # Register as GC root if this is a heap type
                    if name in self.gc_root_indices and self.gc is not None:
                        root_idx = self.gc_root_indices[name]
                        self.gc.set_root(self.builder, self.gc_roots, root_idx, elem_val)
        else:
            # Not a tuple - error case, but for robustness create dummy vars
            for name in stmt.names:
                if name in self.locals:
                    alloca = self.locals[name]
                    self.builder.store(ir.Constant(ir.IntType(64), 0), alloca)
                else:
                    alloca = self.builder.alloca(ir.IntType(64), name=name)
                    self.builder.store(ir.Constant(ir.IntType(64), 0), alloca)
                    self.locals[name] = alloca
    
    def _cast_value(self, value: ir.Value, target_type: ir.Type) -> ir.Value:
        """Cast value to target type if needed"""
        if value.type == target_type:
            return value

        # Int to int
        if isinstance(value.type, ir.IntType) and isinstance(target_type, ir.IntType):
            if target_type.width > value.type.width:
                return self.builder.zext(value, target_type)
            elif target_type.width < value.type.width:
                return self.builder.trunc(value, target_type)

        # Int to float
        if isinstance(value.type, ir.IntType) and isinstance(target_type, ir.DoubleType):
            return self.builder.sitofp(value, target_type)

        # Float to int
        if isinstance(value.type, ir.DoubleType) and isinstance(target_type, ir.IntType):
            return self.builder.fptosi(value, target_type)

        # Pointer to int (for storing pointers in i64 collections)
        if isinstance(value.type, ir.PointerType) and isinstance(target_type, ir.IntType):
            return self.builder.ptrtoint(value, target_type)

        # Int to pointer (for loading pointers from i64 collections)
        if isinstance(value.type, ir.IntType) and isinstance(target_type, ir.PointerType):
            return self.builder.inttoptr(value, target_type)

        # Value to optional struct {i1, T} - wrap value in Some
        # Check this BEFORE the nil case so actual values get wrapped correctly
        if isinstance(target_type, ir.LiteralStructType) and len(target_type.elements) == 2:
            if isinstance(target_type.elements[0], ir.IntType) and target_type.elements[0].width == 1:
                inner_type = target_type.elements[1]
                # Check if value type matches inner type (or can be cast)
                if value.type == inner_type:
                    # Wrap value in Some: {has_value=true, value=val}
                    result = ir.Constant(target_type, ir.Undefined)
                    result = self.builder.insert_value(result, ir.Constant(ir.IntType(1), 1), 0)
                    result = self.builder.insert_value(result, value, 1)
                    return result
                # Check for int size mismatch (e.g., i64 value to optional with i64 inner)
                elif isinstance(value.type, ir.IntType) and isinstance(inner_type, ir.IntType):
                    # Cast the int value to match inner type
                    if value.type.width < inner_type.width:
                        casted = self.builder.sext(value, inner_type)
                    elif value.type.width > inner_type.width:
                        casted = self.builder.trunc(value, inner_type)
                    else:
                        casted = value
                    result = ir.Constant(target_type, ir.Undefined)
                    result = self.builder.insert_value(result, ir.Constant(ir.IntType(1), 1), 0)
                    result = self.builder.insert_value(result, casted, 1)
                    return result
                # Check if value is nil constant (i64 0 from NilLiteral)
                elif isinstance(value, ir.Constant) and isinstance(value.type, ir.IntType):
                    if value.constant == 0:
                        # This is nil - create {has_value=false, value=0}
                        result = ir.Constant(target_type, ir.Undefined)
                        result = self.builder.insert_value(result, ir.Constant(ir.IntType(1), 0), 0)
                        if isinstance(inner_type, ir.IntType):
                            result = self.builder.insert_value(result, ir.Constant(inner_type, 0), 1)
                        elif isinstance(inner_type, ir.DoubleType):
                            result = self.builder.insert_value(result, ir.Constant(inner_type, 0.0), 1)
                        else:
                            result = self.builder.insert_value(result, ir.Constant(inner_type, None), 1)
                        return result

        return value
    
    def _generate_assignment(self, stmt: Assignment):
        """Generate an assignment"""
        # Track if we need to mark source as moved AFTER reading
        move_source_name = None
        if stmt.op == AssignOp.MOVE_ASSIGN and isinstance(stmt.value, Identifier):
            move_source_name = stmt.value.name

        # Clear moved status when target is reassigned (allows reuse after move)
        if isinstance(stmt.target, Identifier):
            target_name = stmt.target.name
            if target_name in self.moved_vars:
                self.moved_vars.discard(target_name)

        # Check if target is a const binding
        if isinstance(stmt.target, Identifier):
            if stmt.target.name in self.const_bindings:
                raise RuntimeError(
                    f"Cannot reassign const binding '{stmt.target.name}'. "
                    f"Remove 'const' from the declaration to make it rebindable."
                )

        # Check if target is a cycle variable - write to write buffer
        if isinstance(stmt.target, Identifier):
            ctx = self._get_cycle_context()
            if ctx and stmt.target.name in ctx['cycle_vars']:
                name = stmt.target.name
                value = self._generate_expression(stmt.value)

                # Handle compound assignment - read from READ buffer, compute, write to WRITE buffer
                if stmt.op != AssignOp.ASSIGN:
                    old_val = self.builder.load(ctx['read_buffers'][name])
                    if stmt.op == AssignOp.PLUS_ASSIGN:
                        if isinstance(value.type, ir.DoubleType):
                            value = self.builder.fadd(old_val, value)
                        else:
                            value = self.builder.add(old_val, value)
                    elif stmt.op == AssignOp.MINUS_ASSIGN:
                        if isinstance(value.type, ir.DoubleType):
                            value = self.builder.fsub(old_val, value)
                        else:
                            value = self.builder.sub(old_val, value)
                    elif stmt.op == AssignOp.STAR_ASSIGN:
                        if isinstance(value.type, ir.DoubleType):
                            value = self.builder.fmul(old_val, value)
                        else:
                            value = self.builder.mul(old_val, value)
                    elif stmt.op == AssignOp.SLASH_ASSIGN:
                        if isinstance(value.type, ir.DoubleType):
                            value = self.builder.fdiv(old_val, value)
                        else:
                            value = self.builder.sdiv(old_val, value)
                    elif stmt.op == AssignOp.PERCENT_ASSIGN:
                        value = self.builder.srem(old_val, value)

                # Write to write buffer
                write_buf = ctx['write_buffers'][name]
                expected_type = ctx['var_types'].get(name)
                if expected_type:
                    value = self._cast_value(value, expected_type)
                self.builder.store(value, write_buf)
                return

        value = self._generate_expression(stmt.value)

        # Handle tuple destructuring: (a, b) = expr
        if isinstance(stmt.target, TupleExpr):
            self._generate_tuple_assignment(stmt.target, value)
            return

        # Handle immutable field assignment: p.x = value
        # Creates a new struct with the updated field (copy-on-write semantics)
        if isinstance(stmt.target, MemberExpr):
            self._generate_immutable_field_assignment(stmt.target, value, stmt.op)
            return

        # Handle indexed assignment for user-defined types: obj[idx] = value -> obj.set(idx, value)
        if isinstance(stmt.target, IndexExpr):
            obj = self._generate_expression(stmt.target.object)
            type_name = self._get_type_name_from_ptr(obj.type)

            if type_name and type_name in self.type_methods:
                method_map = self.type_methods[type_name]
                if "set" in method_map:
                    mangled = method_map["set"]
                    func = self.functions[mangled]

                    # Build args: self, indices..., value
                    args = [obj]
                    for idx_expr in stmt.target.indices:
                        idx_val = self._generate_expression(idx_expr)
                        args.append(idx_val)

                    # Cast value to expected type
                    # value is the last parameter
                    if len(args) < len(func.args):
                        expected = func.args[len(args)].type
                        value = self._cast_value(value, expected)
                    args.append(value)

                    self.builder.call(func, args)
                    return

        # Handle compound assignment (not for MOVE_ASSIGN or ASSIGN)
        if stmt.op not in (AssignOp.ASSIGN, AssignOp.MOVE_ASSIGN):
            old_value = self._generate_expression(stmt.target)
            if stmt.op == AssignOp.PLUS_ASSIGN:
                if isinstance(value.type, ir.DoubleType):
                    value = self.builder.fadd(old_value, value)
                else:
                    value = self.builder.add(old_value, value)
            elif stmt.op == AssignOp.MINUS_ASSIGN:
                if isinstance(value.type, ir.DoubleType):
                    value = self.builder.fsub(old_value, value)
                else:
                    value = self.builder.sub(old_value, value)
            elif stmt.op == AssignOp.STAR_ASSIGN:
                if isinstance(value.type, ir.DoubleType):
                    value = self.builder.fmul(old_value, value)
                else:
                    value = self.builder.mul(old_value, value)
            elif stmt.op == AssignOp.SLASH_ASSIGN:
                if isinstance(value.type, ir.DoubleType):
                    value = self.builder.fdiv(old_value, value)
                else:
                    value = self.builder.sdiv(old_value, value)
            elif stmt.op == AssignOp.PERCENT_ASSIGN:
                value = self.builder.srem(old_value, value)
        
        # Get pointer to target (or create new variable)
        ptr = self._get_lvalue(stmt.target)
        if ptr is None and isinstance(stmt.target, Identifier):
            # New variable - create it
            name = stmt.target.name
            alloca = self.builder.alloca(value.type, name=name)
            self.locals[name] = alloca
            ptr = alloca
            
            # Track tuple info if the value is a tuple from a function call
            if isinstance(value.type, ir.LiteralStructType):
                tuple_info = self._infer_tuple_info(stmt.value)
                if tuple_info:
                    self.tuple_field_info[name] = tuple_info
            
            # Track list element type for proper iteration
            if isinstance(value.type, ir.PointerType):
                pointee = value.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    elem_type = self._infer_list_element_type(stmt.value)
                    if elem_type:
                        self.list_element_types[name] = elem_type

        # Value semantics: deep copy collections on assignment to prevent aliasing
        # Try to get Coex type for proper deep copy
        coex_type = None
        # First, try to get type from target variable
        if isinstance(stmt.target, Identifier):
            target_name = stmt.target.name
            if target_name in self.var_coex_types:
                coex_type = self.var_coex_types[target_name]
        # If not found, try to get from source expression
        if coex_type is None and isinstance(stmt.value, Identifier):
            source_name = stmt.value.name
            if source_name in self.var_coex_types:
                coex_type = self.var_coex_types[source_name]
                # Track for target too
                if isinstance(stmt.target, Identifier):
                    self.var_coex_types[stmt.target.name] = coex_type
        # If source is a literal collection, infer the type
        if coex_type is None and isinstance(stmt.value, (MapExpr, ListExpr, SetExpr)):
            coex_type = self._infer_type_from_expr(stmt.value)
            if isinstance(stmt.target, Identifier):
                self.var_coex_types[stmt.target.name] = coex_type
        # If source is a method call on a collection (e.g., list.set(), list.append()),
        # propagate the type from the receiver
        if coex_type is None and isinstance(stmt.value, MethodCallExpr):
            if isinstance(stmt.value.object, Identifier):
                receiver_name = stmt.value.object.name
                if receiver_name in self.var_coex_types:
                    receiver_type = self.var_coex_types[receiver_name]
                    # Methods that return same collection type: set, append, remove, etc.
                    if stmt.value.method in ("set", "append", "remove", "pop", "insert"):
                        coex_type = receiver_type
                        if isinstance(stmt.target, Identifier):
                            self.var_coex_types[stmt.target.name] = coex_type
        if coex_type is None and isinstance(stmt.value, CallExpr):
            # Check if this is a method call (callee is MemberExpr: obj.method(...))
            if isinstance(stmt.value.callee, MemberExpr):
                callee_member = stmt.value.callee
                method_name = callee_member.member
                # Find the innermost receiver (handles chained calls like a.set(0, x).set(1, y))
                receiver_type = self._get_receiver_type(callee_member.object)
                if receiver_type:
                    # Methods that return same collection type
                    if method_name in ("set", "append", "remove", "pop", "insert"):
                        coex_type = receiver_type
                        if isinstance(stmt.target, Identifier):
                            self.var_coex_types[stmt.target.name] = coex_type

        # Determine whether to use move or copy semantics
        is_move = stmt.op == AssignOp.MOVE_ASSIGN

        if coex_type and self._is_collection_coex_type(coex_type):
            if is_move:
                value = self._generate_move_or_eager_copy(value, coex_type)
            else:
                value = self._generate_deep_copy(value, coex_type)
        elif coex_type and isinstance(coex_type, NamedType) and coex_type.name in self.type_fields:
            # User-defined types need deep copy to handle collection fields
            if is_move:
                value = self._generate_move_or_eager_copy(value, coex_type)
            else:
                value = self._generate_deep_copy(value, coex_type)
        elif isinstance(value.type, ir.PointerType):
            # Fallback to shallow copy for unknown collection types
            pointee = value.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    value = self.builder.call(self.list_copy, [value])
                elif pointee.name == "struct.Set":
                    value = self.builder.call(self.set_copy, [value])
                elif pointee.name == "struct.Map":
                    value = self.builder.call(self.map_copy, [value])
                elif pointee.name == "struct.String":
                    value = self.builder.call(self.string_copy, [value])
                elif pointee.name == "struct.Array":
                    if is_move:
                        value = self._generate_move_or_eager_copy(value, ArrayType(PrimitiveType("int")))
                    else:
                        value = self.builder.call(self.array_copy, [value])

        if ptr:
            self.builder.store(value, ptr)

            # Update GC root if this is a tracked heap variable being reassigned
            if isinstance(stmt.target, Identifier):
                target_name = stmt.target.name
                if target_name in self.gc_root_indices and self.gc is not None:
                    root_idx = self.gc_root_indices[target_name]
                    self.gc.set_root(self.builder, self.gc_roots, root_idx, value)

        # Mark source as moved AFTER we've read its value
        if move_source_name:
            self.moved_vars.add(move_source_name)

    def _generate_tuple_assignment(self, target: TupleExpr, value: ir.Value):
        """Generate code for tuple destructuring: (a, b) = value"""
        if isinstance(value.type, ir.LiteralStructType):
            # Extract each element and assign to the corresponding variable
            for i, (name_or_none, elem_expr) in enumerate(target.elements):
                if i < len(value.type.elements):
                    elem_type = value.type.elements[i]
                    elem_val = self.builder.extract_value(value, i)

                    # Get the variable name from the element expression
                    if isinstance(elem_expr, Identifier):
                        var_name = elem_expr.name
                        # Create or update the variable
                        if var_name in self.locals:
                            self.builder.store(elem_val, self.locals[var_name])
                        else:
                            alloca = self.builder.alloca(elem_type, name=var_name)
                            self.builder.store(elem_val, alloca)
                            self.locals[var_name] = alloca

    def _generate_immutable_field_assignment(self, target: MemberExpr, new_value: ir.Value, op: AssignOp):
        """Generate immutable field assignment: p.x = value

        Instead of mutating the struct in place, creates a new struct with:
        - The changed field set to the new value
        - All other fields copied from the old struct (reference sharing)
        - The variable rebound to point to the new struct

        This implements copy-on-write semantics for UDTs, making them immutable
        like collections. The old struct becomes garbage and will be collected.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get the old struct
        old_struct = self._generate_expression(target.object)
        type_name = self._get_type_name_from_ptr(old_struct.type)

        if type_name is None or type_name not in self.type_fields:
            # Fallback for unknown types - shouldn't happen
            raise RuntimeError(f"Cannot assign to field of unknown type: {type_name}")

        # Get field info
        field_idx = self._get_field_index(type_name, target.member)
        if field_idx is None:
            raise RuntimeError(f"Unknown field '{target.member}' in type '{type_name}'")

        fields = self.type_fields[type_name]
        struct_type = self.type_registry[type_name]

        # Handle compound assignment (+=, -=, etc.)
        if op not in (AssignOp.ASSIGN, AssignOp.MOVE_ASSIGN):
            old_field_ptr = self.builder.gep(old_struct, [ir.Constant(i32, 0), ir.Constant(i32, field_idx)], inbounds=True)
            old_field_val = self.builder.load(old_field_ptr)

            if op == AssignOp.PLUS_ASSIGN:
                if isinstance(new_value.type, ir.DoubleType):
                    new_value = self.builder.fadd(old_field_val, new_value)
                else:
                    new_value = self.builder.add(old_field_val, new_value)
            elif op == AssignOp.MINUS_ASSIGN:
                if isinstance(new_value.type, ir.DoubleType):
                    new_value = self.builder.fsub(old_field_val, new_value)
                else:
                    new_value = self.builder.sub(old_field_val, new_value)
            elif op == AssignOp.STAR_ASSIGN:
                if isinstance(new_value.type, ir.DoubleType):
                    new_value = self.builder.fmul(old_field_val, new_value)
                else:
                    new_value = self.builder.mul(old_field_val, new_value)
            elif op == AssignOp.SLASH_ASSIGN:
                if isinstance(new_value.type, ir.DoubleType):
                    new_value = self.builder.fdiv(old_field_val, new_value)
                else:
                    new_value = self.builder.sdiv(old_field_val, new_value)
            elif op == AssignOp.PERCENT_ASSIGN:
                new_value = self.builder.srem(old_field_val, new_value)

        # Allocate new struct via GC
        struct_size = ir.Constant(i64, struct_type.packed_size if hasattr(struct_type, 'packed_size') else 64)
        type_id = ir.Constant(i32, self.gc.get_type_id(type_name))
        raw_ptr = self.gc.alloc_with_deref(self.builder, struct_size, type_id)
        new_struct = self.builder.bitcast(raw_ptr, struct_type.as_pointer())

        # Copy all fields from old struct to new struct
        for i, (field_name, field_type) in enumerate(fields):
            if i == field_idx:
                # This is the changed field - store new value
                dst_field_ptr = self.builder.gep(new_struct, [ir.Constant(i32, 0), ir.Constant(i32, i)], inbounds=True)
                # Phase 6: Reference type fields store as i64 handles
                if self._is_reference_type(field_type):
                    if isinstance(new_value.type, ir.PointerType):
                        # Get handle for the object (not raw ptrtoint!)
                        value_i8 = self.builder.bitcast(new_value, ir.IntType(8).as_pointer())
                        store_value = self.builder.call(self.gc.gc_ptr_to_handle, [value_i8])
                    elif new_value.type != i64:
                        store_value = self._cast_value(new_value, i64)
                    else:
                        store_value = new_value
                else:
                    # Cast value if needed
                    expected_type = struct_type.elements[i]
                    store_value = self._cast_value(new_value, expected_type)
                self.builder.store(store_value, dst_field_ptr)
            else:
                # Copy field from old struct (reference sharing for heap types)
                # Both old and new struct use i64 for reference type fields
                src_field_ptr = self.builder.gep(old_struct, [ir.Constant(i32, 0), ir.Constant(i32, i)], inbounds=True)
                field_val = self.builder.load(src_field_ptr)
                dst_field_ptr = self.builder.gep(new_struct, [ir.Constant(i32, 0), ir.Constant(i32, i)], inbounds=True)
                self.builder.store(field_val, dst_field_ptr)

        # Rebind the variable to point to the new struct
        # The object must be an Identifier for us to rebind it
        if isinstance(target.object, Identifier):
            var_name = target.object.name
            if var_name in self.locals:
                self.builder.store(new_struct, self.locals[var_name])

                # Update GC root if this is a tracked heap variable
                if var_name in self.gc_root_indices and self.gc is not None:
                    root_idx = self.gc_root_indices[var_name]
                    self.gc.set_root(self.builder, self.gc_roots, root_idx, new_struct)
        elif isinstance(target.object, MemberExpr):
            # Nested field assignment: a.b.x = value
            # Recursively create new structs up the chain
            self._generate_immutable_field_assignment(target.object, new_struct, AssignOp.ASSIGN)
        else:
            raise RuntimeError(f"Cannot rebind field assignment target: {type(target.object)}")

    def _generate_slice_assignment(self, stmt: SliceAssignment):
        """Generate code for slice assignment: obj[start:end] = source

        Calls .setrange(start, end, source) on the object.
        Returns a new collection (value semantics).
        """
        obj = self._generate_expression(stmt.target)
        source = self._generate_expression(stmt.value)
        i64 = ir.IntType(64)

        # Get collection length for bounds normalization
        length = self._get_collection_length(obj)

        # Normalize start
        if stmt.start is None:
            start = ir.Constant(i64, 0)
        else:
            start = self._generate_expression(stmt.start)
            start = self._cast_value(start, i64)
            start = self._normalize_slice_index(start, length)

        # Normalize end
        if stmt.end is None:
            end = length
        else:
            end = self._generate_expression(stmt.end)
            end = self._cast_value(end, i64)
            end = self._normalize_slice_index(end, length)

        # Call setrange method
        type_name = self._get_type_name_from_ptr(obj.type)
        new_collection = None

        if type_name and type_name in self.type_methods:
            method_map = self.type_methods[type_name]
            if "setrange" in method_map:
                mangled = method_map["setrange"]
                func = self.functions[mangled]
                new_collection = self.builder.call(func, [obj, start, end, source])

        # Fallback: check for direct list_setrange
        if new_collection is None:
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    new_collection = self.builder.call(self.list_setrange, [obj, start, end, source])
                elif hasattr(pointee, 'name') and pointee.name == "struct.String":
                    new_collection = self.builder.call(self.string_setrange, [obj, start, end, source])

        if new_collection is None:
            raise RuntimeError(f"Type '{type_name}' does not support slice assignment (no setrange method)")

        # Store back to the variable (value semantics)
        if isinstance(stmt.target, Identifier):
            var_name = stmt.target.name
            if var_name in self.locals:
                self.builder.store(new_collection, self.locals[var_name])

                # Update GC root if this is a tracked heap variable
                if var_name in self.gc_root_indices and self.gc is not None:
                    root_idx = self.gc_root_indices[var_name]
                    self.gc.set_root(self.builder, self.gc_roots, root_idx, new_collection)

    def _get_lvalue(self, expr: Expr) -> Optional[ir.Value]:
        """Get pointer to an lvalue expression"""
        if isinstance(expr, Identifier):
            name = expr.name
            if name in self.locals:
                return self.locals[name]
            else:
                # Check if it's a field access in a method context
                if self.current_type and "self" in self.locals:
                    field_idx = self._get_field_index(self.current_type, name)
                    if field_idx is not None:
                        self_ptr = self.builder.load(self.locals["self"])
                        return self.builder.gep(self_ptr, [
                            ir.Constant(ir.IntType(32), 0),
                            ir.Constant(ir.IntType(32), field_idx)
                        ], inbounds=True)
                return None
        
        elif isinstance(expr, IndexExpr):
            # Array/list indexing
            base = self._generate_expression(expr.object)
            index = self._generate_expression(expr.indices[0])
            # GEP into the list data
            # This is simplified - real implementation needs list struct access
            return None
        
        elif isinstance(expr, MemberExpr):
            # Struct field access: obj.field
            return self._get_lvalue_member(expr)
        
        return None
    
    def _generate_return(self, stmt: ReturnStmt):
        """Generate a return statement"""
        if stmt.value:
            # Special handling for returning nil to an optional type
            func = self.builder.function
            ret_type = func.function_type.return_type

            if isinstance(stmt.value, NilLiteral) and isinstance(ret_type, ir.LiteralStructType):
                # Check if return type is an optional (has i1 flag + value)
                if len(ret_type.elements) == 2 and isinstance(ret_type.elements[0], ir.IntType):
                    if ret_type.elements[0].width == 1:
                        # Generate nil optional directly: {has_value=false, value=0}
                        inner_type = ret_type.elements[1]
                        value = ir.Constant(ret_type, ir.Undefined)
                        value = self.builder.insert_value(value, ir.Constant(ir.IntType(1), 0), 0)
                        if isinstance(inner_type, ir.IntType):
                            value = self.builder.insert_value(value, ir.Constant(inner_type, 0), 1)
                        elif isinstance(inner_type, ir.DoubleType):
                            value = self.builder.insert_value(value, ir.Constant(inner_type, 0.0), 1)
                        else:
                            value = self.builder.insert_value(value, ir.Constant(inner_type, None), 1)

                        # Pop GC frame before returning
                        if self.gc_frame is not None and self.gc is not None:
                            self.gc.pop_frame(self.builder, self.gc_frame)

                        self.builder.ret(value)
                        return

            value = self._generate_expression(stmt.value)

            # In matrix formula context, write to buffer and continue loop
            if self.current_matrix is not None:
                self._generate_matrix_return(value)
                # Branch to x_loop_inc (next cell)
                # Find the increment block
                for block in func.blocks:
                    if block.name == "x_loop_inc":
                        self.builder.branch(block)
                        return

            # Cast to function return type if needed (e.g., wrap in optional)
            value = self._cast_value(value, ret_type)

            # Pop GC frame before returning
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            self.builder.ret(value)
        else:
            # Pop GC frame before returning
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            self.builder.ret_void()
    
    def _generate_print(self, stmt: PrintStmt):
        """Generate a print statement"""
        # Skip if printing is disabled
        if not self.printing_enabled:
            return

        value = self._generate_expression(stmt.value)
        
        # Select format based on type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Boolean
                true_block = self.builder.append_basic_block("print_true")
                false_block = self.builder.append_basic_block("print_false")
                merge_block = self.builder.append_basic_block("print_merge")
                
                self.builder.cbranch(value, true_block, false_block)
                
                self.builder.position_at_end(true_block)
                fmt_ptr = self.builder.bitcast(self._true_str, ir.IntType(8).as_pointer())
                self.builder.call(self.printf, [fmt_ptr])
                self.builder.branch(merge_block)
                
                self.builder.position_at_end(false_block)
                fmt_ptr = self.builder.bitcast(self._false_str, ir.IntType(8).as_pointer())
                self.builder.call(self.printf, [fmt_ptr])
                self.builder.branch(merge_block)
                
                self.builder.position_at_end(merge_block)
            else:
                # Integer
                fmt_ptr = self.builder.bitcast(self._int_fmt, ir.IntType(8).as_pointer())
                # Extend to i64 if needed
                if value.type.width < 64:
                    value = self.builder.sext(value, ir.IntType(64))
                self.builder.call(self.printf, [fmt_ptr, value])
        
        elif isinstance(value.type, ir.DoubleType):
            fmt_ptr = self.builder.bitcast(self._float_fmt, ir.IntType(8).as_pointer())
            self.builder.call(self.printf, [fmt_ptr, value])
        
        elif isinstance(value.type, ir.PointerType):
            pointee = value.type.pointee
            # Check if this is a String*
            if hasattr(pointee, 'name') and pointee.name == "struct.String":
                self.builder.call(self.string_print, [value])
            else:
                # Raw string pointer
                fmt_ptr = self.builder.bitcast(self._str_fmt, ir.IntType(8).as_pointer())
                self.builder.call(self.printf, [fmt_ptr, value])

        # Flush stdout to ensure output appears in correct order
        null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        self.builder.call(self.fflush, [null_ptr])

    def _generate_debug(self, stmt: DebugStmt):
        """Generate a debug statement (output to stderr)"""
        # Skip if debugging is disabled (compile-time elimination)
        if not self.debugging_enabled:
            return

        value = self._generate_expression(stmt.value)
        stderr_fd = ir.Constant(ir.IntType(32), 2)

        # Select format based on type
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Boolean
                true_block = self.builder.append_basic_block("debug_true")
                false_block = self.builder.append_basic_block("debug_false")
                merge_block = self.builder.append_basic_block("debug_merge")

                self.builder.cbranch(value, true_block, false_block)

                self.builder.position_at_end(true_block)
                fmt_ptr = self.builder.bitcast(self._true_str, ir.IntType(8).as_pointer())
                self.builder.call(self.dprintf, [stderr_fd, fmt_ptr])
                self.builder.branch(merge_block)

                self.builder.position_at_end(false_block)
                fmt_ptr = self.builder.bitcast(self._false_str, ir.IntType(8).as_pointer())
                self.builder.call(self.dprintf, [stderr_fd, fmt_ptr])
                self.builder.branch(merge_block)

                self.builder.position_at_end(merge_block)
            else:
                # Integer
                fmt_ptr = self.builder.bitcast(self._int_fmt, ir.IntType(8).as_pointer())
                # Extend to i64 if needed
                if value.type.width < 64:
                    value = self.builder.sext(value, ir.IntType(64))
                self.builder.call(self.dprintf, [stderr_fd, fmt_ptr, value])

        elif isinstance(value.type, ir.DoubleType):
            fmt_ptr = self.builder.bitcast(self._float_fmt, ir.IntType(8).as_pointer())
            self.builder.call(self.dprintf, [stderr_fd, fmt_ptr, value])

        elif isinstance(value.type, ir.PointerType):
            pointee = value.type.pointee
            # Check if this is a String*
            if hasattr(pointee, 'name') and pointee.name == "struct.String":
                self.builder.call(self.string_debug, [value])
            else:
                # Raw string pointer
                fmt_ptr = self.builder.bitcast(self._str_fmt, ir.IntType(8).as_pointer())
                self.builder.call(self.dprintf, [stderr_fd, fmt_ptr, value])

        # Flush stderr to ensure output appears in correct order
        null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        self.builder.call(self.fflush, [null_ptr])

    def _generate_if(self, stmt: IfStmt):
        """Generate an if statement"""
        func = self.builder.function
        
        then_block = func.append_basic_block("if_then")
        merge_block = func.append_basic_block("if_merge")
        
        # Create else-if and else blocks
        else_blocks = []
        for _ in stmt.else_if_clauses:
            else_blocks.append(func.append_basic_block("elif_cond"))
        
        if stmt.else_body:
            else_block = func.append_basic_block("if_else")
        else:
            else_block = merge_block
        
        # Generate condition
        cond = self._generate_expression(stmt.condition)
        cond = self._to_bool(cond)
        
        # Branch
        first_else = else_blocks[0] if else_blocks else else_block
        self.builder.cbranch(cond, then_block, first_else)
        
        # Generate then block
        self.builder.position_at_end(then_block)
        self._enter_scope()  # Variables declared in then-block are scoped here
        for s in stmt.then_body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        self._exit_scope()  # Clean up variables from then-block
        if not self.builder.block.is_terminated:
            self.builder.branch(merge_block)

        # Generate else-if blocks
        for i, (elif_cond, elif_body) in enumerate(stmt.else_if_clauses):
            self.builder.position_at_end(else_blocks[i])
            cond = self._generate_expression(elif_cond)
            cond = self._to_bool(cond)

            elif_then = func.append_basic_block("elif_then")
            next_else = else_blocks[i + 1] if i + 1 < len(else_blocks) else else_block

            self.builder.cbranch(cond, elif_then, next_else)

            self.builder.position_at_end(elif_then)
            self._enter_scope()  # Variables declared in elif-block are scoped here
            for s in elif_body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
            self._exit_scope()  # Clean up variables from elif-block
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)

        # Generate else block
        if stmt.else_body:
            self.builder.position_at_end(else_block)
            self._enter_scope()  # Variables declared in else-block are scoped here
            for s in stmt.else_body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
            self._exit_scope()  # Clean up variables from else-block
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)
        
        self.builder.position_at_end(merge_block)
    
    def _to_bool(self, value: ir.Value) -> ir.Value:
        """Convert value to boolean (i1)"""
        if value.type == ir.IntType(1):
            return value
        elif isinstance(value.type, ir.IntType):
            return self.builder.icmp_signed("!=", value, ir.Constant(value.type, 0))
        elif isinstance(value.type, ir.DoubleType):
            return self.builder.fcmp_ordered("!=", value, ir.Constant(value.type, 0.0))
        elif isinstance(value.type, ir.PointerType):
            # Check if this is a Result pointer - convert to bool based on tag
            if hasattr(self, 'result_struct') and value.type == self.result_struct.as_pointer():
                # Result<T, E> -> bool: true if Ok (tag == 0), false if Err (tag == 1)
                tag_ptr = self.builder.gep(value, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), 0)  # tag field
                ])
                tag = self.builder.load(tag_ptr)
                return self.builder.icmp_signed("==", tag, ir.Constant(ir.IntType(64), 0))
            # Regular pointer: true if non-null
            null = ir.Constant(value.type, None)
            return self.builder.icmp_unsigned("!=", value, null)
        return value
    
    def _generate_while(self, stmt: WhileStmt):
        """Generate a standard while loop: while condition block

        Equivalent to other languages' while loop.
        Note: 'while true' is equivalent to 'loop'.
        """
        func = self.builder.function

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Create basic blocks
        cond_block = func.append_basic_block("while_cond")
        body_block = func.append_basic_block("while_body")
        exit_block = func.append_basic_block("while_exit")

        # Save loop blocks for break/continue
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = cond_block

        # Jump to condition check
        self.builder.branch(cond_block)

        # Generate condition check
        self.builder.position_at_end(cond_block)
        cond_val = self._generate_expression(stmt.condition)
        cond_bool = self._to_bool(cond_val)
        self.builder.cbranch(cond_bool, body_block, exit_block)

        # Generate loop body
        self.builder.position_at_end(body_block)
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break

        if not self.builder.block.is_terminated:
            self.builder.branch(cond_block)

        # Continue after loop
        self.builder.position_at_end(exit_block)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_cycle(self, stmt: CycleStmt):
        """Generate a cycle statement with double-buffered semantics.

        Syntax: while condition cycle block

        Variables declared inside the cycle block exist in two buffers.
        Reads see the 'read' buffer (previous generation).
        Writes go to the 'write' buffer (current generation).
        At iteration end, buffers swap and condition is checked in outer scope.
        """
        func = self.builder.function

        # Phase 1: Analyze the body to find variables declared inside
        cycle_vars = self._find_cycle_declared_vars(stmt.body)

        # Phase 2: Create double-buffered storage for cycle variables
        read_buffers: Dict[str, ir.AllocaInst] = {}   # var_name -> alloca for read buffer
        write_buffers: Dict[str, ir.AllocaInst] = {}  # var_name -> alloca for write buffer
        cycle_var_types: Dict[str, ir.Type] = {}      # var_name -> LLVM type

        for var_name, var_type in cycle_vars.items():
            if var_type:
                llvm_type = self._get_llvm_type(var_type)
            else:
                llvm_type = ir.IntType(64)  # Default to i64 for unknown types
            cycle_var_types[var_name] = llvm_type
            read_buffers[var_name] = self.builder.alloca(llvm_type, name=f"{var_name}_read")
            write_buffers[var_name] = self.builder.alloca(llvm_type, name=f"{var_name}_write")

            # Initialize both buffers to zero/null
            if isinstance(llvm_type, ir.IntType):
                zero = ir.Constant(llvm_type, 0)
            elif isinstance(llvm_type, ir.DoubleType):
                zero = ir.Constant(llvm_type, 0.0)
            elif isinstance(llvm_type, ir.PointerType):
                zero = ir.Constant(llvm_type, None)
            else:
                zero = ir.Constant(llvm_type, None)
            self.builder.store(zero, read_buffers[var_name])
            self.builder.store(zero, write_buffers[var_name])

        # Phase 3: Create basic blocks
        body_block = func.append_basic_block("cycle_body")
        swap_block = func.append_basic_block("cycle_swap")
        cond_block = func.append_basic_block("cycle_cond")
        exit_block = func.append_basic_block("cycle_exit")

        # Save loop blocks for break/continue
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = swap_block  # continue commits and checks condition

        # Phase 4: Initial condition check (enter cycle only if condition true)
        init_cond = self._generate_expression(stmt.condition)
        init_cond_bool = self._to_bool(init_cond)
        self.builder.cbranch(init_cond_bool, body_block, exit_block)

        # Phase 5: Push cycle context and generate body
        self.builder.position_at_end(body_block)

        cycle_context = {
            'read_buffers': read_buffers,
            'write_buffers': write_buffers,
            'cycle_vars': set(cycle_vars.keys()),
            'var_types': cycle_var_types
        }
        self._cycle_context_stack.append(cycle_context)

        # Generate body statements
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break

        if not self.builder.block.is_terminated:
            self.builder.branch(swap_block)

        # Pop cycle context before swap (condition is in outer scope)
        self._cycle_context_stack.pop()

        # Phase 6: Buffer swap - copy write buffer to read buffer
        self.builder.position_at_end(swap_block)
        for var_name in cycle_vars:
            write_val = self.builder.load(write_buffers[var_name])
            self.builder.store(write_val, read_buffers[var_name])
        self.builder.branch(cond_block)

        # Phase 7: Condition check (in outer scope, after swap)
        self.builder.position_at_end(cond_block)
        cond_val = self._generate_expression(stmt.condition)
        cond_bool = self._to_bool(cond_val)
        self.builder.cbranch(cond_bool, body_block, exit_block)

        # Phase 8: Exit and cleanup
        self.builder.position_at_end(exit_block)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _find_cycle_declared_vars(self, stmts: PyList[Stmt]) -> Dict[str, Optional[Type]]:
        """Find all variables declared within a list of statements.

        Returns dict of var_name -> type_annotation (or None if inferred).
        Recursively scans into control flow but not into nested cycles.
        """
        declared: Dict[str, Optional[Type]] = {}

        for stmt in stmts:
            if isinstance(stmt, VarDecl):
                declared[stmt.name] = stmt.type_annotation
            elif isinstance(stmt, Assignment):
                # Simple assignment to new identifier declares a var
                if isinstance(stmt.target, Identifier) and stmt.op == AssignOp.ASSIGN:
                    name = stmt.target.name
                    # Only count as declaration if not already known
                    if name not in declared and name not in self.locals:
                        declared[name] = None
            elif isinstance(stmt, IfStmt):
                # Recurse into branches
                declared.update(self._find_cycle_declared_vars(stmt.then_body))
                for _, body in stmt.else_if_clauses:
                    declared.update(self._find_cycle_declared_vars(body))
                if stmt.else_body:
                    declared.update(self._find_cycle_declared_vars(stmt.else_body))
            elif isinstance(stmt, ForStmt):
                # Do NOT count the for loop variable as a cycle variable
                # For loop manages its own iteration variable
                declared.update(self._find_cycle_declared_vars(stmt.body))
            elif isinstance(stmt, WhileStmt):
                declared.update(self._find_cycle_declared_vars(stmt.body))
            # Note: Don't recurse into nested CycleStmt - those have their own scope

        return declared

    def _in_cycle_context(self) -> bool:
        """Check if currently generating code inside a cycle block."""
        return len(self._cycle_context_stack) > 0

    def _get_cycle_context(self) -> Optional[Dict]:
        """Get the current cycle context, or None if not in a cycle."""
        if self._cycle_context_stack:
            return self._cycle_context_stack[-1]
        return None

    # ========================================================================
    # Loop Nursery Support
    # ========================================================================

    def _loop_needs_nursery(self, stmt: ForStmt) -> bool:
        """Detect if loop body has collection mutations that create garbage.

        NOTE: Nursery support has been removed. This always returns False.
        The simple mark-sweep GC handles garbage collection without the
        heap context/nursery optimization.
        """
        return False

    def _has_collection_mutations(self, stmts: PyList[Stmt]) -> bool:
        """Check if statements contain collection mutation patterns."""
        mutation_methods = ('append', 'add', 'set', 'push', 'insert', 'remove', 'pop')

        for stmt in stmts:
            if isinstance(stmt, Assignment):
                # Check for pattern: var = var.method(...)
                # where method is append, set, or similar mutation
                if isinstance(stmt.target, Identifier):
                    target_name = stmt.target.name

                    # Pattern 1: MethodCallExpr (var = var.append(...))
                    if isinstance(stmt.value, MethodCallExpr):
                        method_obj = stmt.value.object
                        method_name = stmt.value.method
                        if isinstance(method_obj, Identifier) and method_obj.name == target_name:
                            if method_name in mutation_methods:
                                return True

                    # Pattern 2: CallExpr with MemberExpr callee (arr.append parsed as CallExpr)
                    elif isinstance(stmt.value, CallExpr) and isinstance(stmt.value.callee, MemberExpr):
                        member_expr = stmt.value.callee
                        method_obj = member_expr.object
                        method_name = member_expr.member
                        if isinstance(method_obj, Identifier) and method_obj.name == target_name:
                            if method_name in mutation_methods:
                                return True

            elif isinstance(stmt, VarDecl):
                # Check for var x = x.append(...) patterns with rebinding
                if stmt.initializer:
                    if isinstance(stmt.initializer, MethodCallExpr):
                        if stmt.initializer.method in mutation_methods:
                            return True
                    elif isinstance(stmt.initializer, CallExpr) and isinstance(stmt.initializer.callee, MemberExpr):
                        if stmt.initializer.callee.member in mutation_methods:
                            return True

            elif isinstance(stmt, IfStmt):
                # Recurse into branches
                if self._has_collection_mutations(stmt.then_body):
                    return True
                for _, body in stmt.else_if_clauses:
                    if self._has_collection_mutations(body):
                        return True
                if stmt.else_body and self._has_collection_mutations(stmt.else_body):
                    return True

            elif isinstance(stmt, WhileStmt):
                if self._has_collection_mutations(stmt.body):
                    return True

        return False

    def _get_loop_carried_vars(self, stmt: ForStmt) -> PyList[str]:
        """Find variables that are both read and written in loop body.

        These are variables whose final values must survive the loop -
        they need to be promoted out of the nursery at the end.
        """
        written: set = set()
        read: set = set()

        self._collect_var_usage(stmt.body, written, read)

        # Loop-carried vars are those both read and written
        # (they depend on previous iterations)
        loop_carried = written & read

        # Also include vars that are written and used after the loop
        # For now, we conservatively include all written vars that existed before the loop
        pre_existing = set(self.locals.keys())
        escaping = written & pre_existing

        return list(loop_carried | escaping)

    def _collect_var_usage(self, stmts: PyList[Stmt], written: set, read: set):
        """Collect variables that are written and read in statements."""
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                # Collect writes
                if isinstance(stmt.target, Identifier):
                    written.add(stmt.target.name)
                # Collect reads from value expression
                self._collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, VarDecl):
                written.add(stmt.name)
                if stmt.value:
                    self._collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, ExprStmt):
                self._collect_expr_reads(stmt.expr, read)

            elif isinstance(stmt, ReturnStmt):
                if stmt.value:
                    self._collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, IfStmt):
                self._collect_expr_reads(stmt.condition, read)
                self._collect_var_usage(stmt.then_body, written, read)
                for cond, body in stmt.else_if_clauses:
                    self._collect_expr_reads(cond, read)
                    self._collect_var_usage(body, written, read)
                if stmt.else_body:
                    self._collect_var_usage(stmt.else_body, written, read)

            elif isinstance(stmt, ForStmt):
                self._collect_expr_reads(stmt.iterable, read)
                self._collect_var_usage(stmt.body, written, read)

            elif isinstance(stmt, WhileStmt):
                self._collect_expr_reads(stmt.condition, read)
                self._collect_var_usage(stmt.body, written, read)

    def _collect_expr_reads(self, expr: Expr, read: set):
        """Collect variable reads from an expression."""
        if isinstance(expr, Identifier):
            read.add(expr.name)
        elif isinstance(expr, BinaryExpr):
            self._collect_expr_reads(expr.left, read)
            self._collect_expr_reads(expr.right, read)
        elif isinstance(expr, UnaryExpr):
            self._collect_expr_reads(expr.operand, read)
        elif isinstance(expr, TernaryExpr):
            self._collect_expr_reads(expr.condition, read)
            self._collect_expr_reads(expr.then_expr, read)
            self._collect_expr_reads(expr.else_expr, read)
        elif isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                # Don't count function names as variable reads
                pass
            else:
                self._collect_expr_reads(expr.callee, read)
            for arg in expr.args:
                self._collect_expr_reads(arg, read)
        elif isinstance(expr, MethodCallExpr):
            self._collect_expr_reads(expr.object, read)
            for arg in expr.args:
                self._collect_expr_reads(arg, read)
        elif isinstance(expr, MemberExpr):
            self._collect_expr_reads(expr.object, read)
        elif isinstance(expr, IndexExpr):
            self._collect_expr_reads(expr.object, read)
            for idx in expr.indices:
                self._collect_expr_reads(idx, read)
        elif isinstance(expr, SliceExpr):
            self._collect_expr_reads(expr.object, read)
            if expr.start:
                self._collect_expr_reads(expr.start, read)
            if expr.end:
                self._collect_expr_reads(expr.end, read)
        elif isinstance(expr, ListExpr):
            for elem in expr.elements:
                self._collect_expr_reads(elem, read)
        elif isinstance(expr, TupleExpr):
            for elem in expr.elements:
                self._collect_expr_reads(elem, read)
        elif isinstance(expr, RangeExpr):
            self._collect_expr_reads(expr.start, read)
            self._collect_expr_reads(expr.end, read)
        elif isinstance(expr, LambdaExpr):
            # Lambda body is a separate scope, but captures are reads
            self._collect_expr_reads(expr.body, read)

    def _estimate_nursery_size(self, stmt: ForStmt, iteration_count: Optional[ir.Value]) -> ir.Value:
        """Estimate the nursery size needed for a loop.

        For range-based loops with known iteration count, we can estimate better.
        Default: 64MB which should handle most collection mutation patterns.

        For persistent vector appends, each operation creates:
        - New List struct (~32 bytes + 16 byte GC header = 48 bytes)
        - Path-copied tree nodes (~280 bytes per node, depth can be 4-6)
        - Potentially new tail buffer (~256+ bytes)
        Estimate ~1KB per iteration for safety.
        """
        # Default size: 64MB for typical collection operations
        default_size = ir.Constant(ir.IntType(64), 64 * 1024 * 1024)

        # If we have an iteration count, scale based on expected per-iteration allocation
        # Persistent vector append creates ~1KB of garbage per iteration
        if iteration_count is not None:
            per_iteration = ir.Constant(ir.IntType(64), 1024)  # ~1KB per iteration for PV operations
            estimated = self.builder.mul(iteration_count, per_iteration)
            # Use max of default and estimated
            use_estimated = self.builder.icmp_unsigned(">", estimated, default_size)
            return self.builder.select(use_estimated, estimated, default_size)

        return default_size

    def _copy_collection_to_main_heap(self, var_name: str, var_ptr: ir.Value, elem_type: ir.Type) -> ir.Value:
        """Copy a collection from nursery to main heap.

        This is called when promoting loop-carried variables out of the nursery.
        For List types, creates a fresh copy in the main heap using runtime copy functions.

        var_ptr is typically an alloca of a pointer type (e.g., %struct.List**)
        We need to load the pointer, copy the collection, and store the new pointer back.
        """
        # Load the collection pointer from the alloca
        if isinstance(var_ptr.type, ir.PointerType):
            loaded = self.builder.load(var_ptr)

            # Check if the loaded value is a collection pointer
            if isinstance(loaded.type, ir.PointerType):
                pointee = loaded.type.pointee
                if hasattr(pointee, 'name'):
                    if 'List' in pointee.name:
                        # Copy the list to main heap using runtime function
                        copied = self.builder.call(self.list_copy, [loaded])
                        self.builder.store(copied, var_ptr)
                        return copied
                    elif 'Array' in pointee.name:
                        # Copy the array to main heap using runtime function
                        copied = self.builder.call(self.array_copy, [loaded])
                        self.builder.store(copied, var_ptr)
                        return copied
                    elif 'Map' in pointee.name:
                        # Copy the map to main heap using runtime function
                        copied = self.builder.call(self.map_copy, [loaded])
                        self.builder.store(copied, var_ptr)
                        return copied
                    elif 'Set' in pointee.name:
                        # Copy the set to main heap using runtime function
                        copied = self.builder.call(self.set_copy, [loaded])
                        self.builder.store(copied, var_ptr)
                        return copied

        return self.builder.load(var_ptr)

    def _generate_for(self, stmt: ForStmt):
        """Generate a for loop, optionally with nursery for collection mutations"""
        func = self.builder.function

        # Check if this loop needs a nursery for efficient garbage collection
        use_nursery = self._loop_needs_nursery(stmt) and hasattr(self, 'gc') and self.gc is not None

        # Check if iterable is a range() call
        if isinstance(stmt.iterable, CallExpr) and isinstance(stmt.iterable.callee, Identifier):
            if stmt.iterable.callee.name == "range":
                self._generate_range_for(stmt, use_nursery)
                return

        # Check if iterable is a RangeExpr (start..end)
        if isinstance(stmt.iterable, RangeExpr):
            self._generate_range_expr_for(stmt, use_nursery)
            return
        
        # Check if iterable is a list, array, or map
        if isinstance(stmt.iterable, (Identifier, ListExpr, CallExpr, IndexExpr, MethodCallExpr, MapExpr)):
            # Generate the iterable expression
            iterable = self._generate_expression(stmt.iterable)
            if isinstance(iterable.type, ir.PointerType):
                pointee = iterable.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    self._generate_list_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    self._generate_array_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Map":
                    self._generate_map_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Set":
                    self._generate_set_for(stmt, iterable)
                    return

        # For other iterables, we need iterator protocol
        # For now, just execute body once as fallback
        for s in stmt.body:
            self._generate_statement(s)
    
    def _generate_range_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in range(start, end)

        If use_nursery is True, creates a nursery context for intermediate allocations
        and promotes loop-carried variables to main heap after the loop.
        """
        func = self.builder.function
        args = stmt.iterable.args

        if len(args) == 1:
            start = ir.Constant(ir.IntType(64), 0)
            end = self._generate_expression(args[0])
        elif len(args) >= 2:
            start = self._generate_expression(args[0])
            end = self._generate_expression(args[1])
        else:
            return

        # Ensure i64
        if start.type != ir.IntType(64):
            start = self._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = self._cast_value(end, ir.IntType(64))

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_var"

        # PRE-ALLOCATE all local variables used in the loop body
        # This prevents stack overflow from allocas inside the loop
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Allocate loop variable
        loop_var = self.builder.alloca(ir.IntType(64), name=var_name)
        self.builder.store(start, loop_var)
        self.locals[var_name] = loop_var

        # Get loop-carried variables before creating nursery
        loop_carried_vars = []
        nursery_ctx = None
        nursery_active = None  # Track if nursery was successfully created
        if use_nursery:
            loop_carried_vars = self._get_loop_carried_vars(stmt)

            # Calculate iteration count for nursery size estimation
            iteration_count = self.builder.sub(end, start)
            nursery_size = self._estimate_nursery_size(stmt, iteration_count)

            # Create nursery context
            nursery_type = ir.Constant(ir.IntType(64), 1)  # CONTEXT_NURSERY = 1
            nursery_ctx = self.builder.call(self.gc.gc_create_context, [nursery_size, nursery_type])

            # Check if nursery creation succeeded (malloc might fail for large sizes)
            null_ctx = ir.Constant(self.gc.heap_context_type.as_pointer(), None)
            nursery_ok = self.builder.icmp_unsigned("!=", nursery_ctx, null_ctx)

            # Store whether nursery is active for cleanup later
            nursery_active = self.builder.alloca(ir.IntType(1), name="nursery_active")
            self.builder.store(nursery_ok, nursery_active)

            # Only push nursery if it was created successfully
            push_nursery = func.append_basic_block("push_nursery")
            skip_nursery = func.append_basic_block("skip_nursery")
            self.builder.cbranch(nursery_ok, push_nursery, skip_nursery)

            self.builder.position_at_end(push_nursery)
            self.builder.call(self.gc.gc_push_context, [nursery_ctx])
            self.builder.branch(skip_nursery)

            self.builder.position_at_end(skip_nursery)

        # Create blocks
        cond_block = func.append_basic_block("for_cond")
        body_block = func.append_basic_block("for_body")
        inc_block = func.append_basic_block("for_inc")
        exit_block = func.append_basic_block("for_exit")

        # Save loop blocks
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block

        # Jump to condition
        self.builder.branch(cond_block)

        # Condition
        self.builder.position_at_end(cond_block)
        current = self.builder.load(loop_var)
        cond = self.builder.icmp_signed("<", current, end)
        self.builder.cbranch(cond, body_block, exit_block)

        # Body
        self.builder.position_at_end(body_block)
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)

        # Increment
        self.builder.position_at_end(inc_block)
        current = self.builder.load(loop_var)
        next_val = self.builder.add(current, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_val, loop_var)
        self.builder.branch(cond_block)

        # Exit
        self.builder.position_at_end(exit_block)

        # Clean up nursery if used
        if use_nursery and nursery_ctx is not None and nursery_active is not None:
            # Check if nursery was actually created successfully
            was_active = self.builder.load(nursery_active)

            cleanup_nursery = func.append_basic_block("cleanup_nursery")
            after_cleanup = func.append_basic_block("after_cleanup")
            self.builder.cbranch(was_active, cleanup_nursery, after_cleanup)

            self.builder.position_at_end(cleanup_nursery)
            # Pop nursery from context stack
            self.builder.call(self.gc.gc_pop_context, [])

            # Promote loop-carried variables to main heap
            for lc_var in loop_carried_vars:
                if lc_var in self.locals:
                    var_ptr = self.locals[lc_var]
                    self._copy_collection_to_main_heap(lc_var, var_ptr, ir.IntType(64))

            # Destroy nursery (bulk-free all intermediate allocations)
            self.builder.call(self.gc.gc_destroy_context, [nursery_ctx])
            self.builder.branch(after_cleanup)

            self.builder.position_at_end(after_cleanup)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_range_expr_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in start..end

        If use_nursery is True, creates a nursery context for intermediate allocations
        and promotes loop-carried variables to main heap after the loop.
        """
        func = self.builder.function
        range_expr = stmt.iterable

        start = self._generate_expression(range_expr.start)
        end = self._generate_expression(range_expr.end)

        # Ensure i64
        if start.type != ir.IntType(64):
            start = self._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = self._cast_value(end, ir.IntType(64))

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Same as range_for
        loop_var = self.builder.alloca(ir.IntType(64), name=stmt.var_name)
        self.builder.store(start, loop_var)
        self.locals[stmt.var_name] = loop_var

        # Get loop-carried variables before creating nursery
        loop_carried_vars = []
        nursery_ctx = None
        nursery_active = None  # Track if nursery was successfully created
        if use_nursery:
            loop_carried_vars = self._get_loop_carried_vars(stmt)

            # Calculate iteration count for nursery size estimation
            iteration_count = self.builder.sub(end, start)
            nursery_size = self._estimate_nursery_size(stmt, iteration_count)

            # Create nursery context
            nursery_type = ir.Constant(ir.IntType(64), 1)  # CONTEXT_NURSERY = 1
            nursery_ctx = self.builder.call(self.gc.gc_create_context, [nursery_size, nursery_type])

            # Check if nursery creation succeeded (malloc might fail for large sizes)
            null_ctx = ir.Constant(self.gc.heap_context_type.as_pointer(), None)
            nursery_ok = self.builder.icmp_unsigned("!=", nursery_ctx, null_ctx)

            # Store whether nursery is active for cleanup later
            nursery_active = self.builder.alloca(ir.IntType(1), name="nursery_active")
            self.builder.store(nursery_ok, nursery_active)

            # Only push nursery if it was created successfully
            push_nursery = func.append_basic_block("push_nursery")
            skip_nursery = func.append_basic_block("skip_nursery")
            self.builder.cbranch(nursery_ok, push_nursery, skip_nursery)

            self.builder.position_at_end(push_nursery)
            self.builder.call(self.gc.gc_push_context, [nursery_ctx])
            self.builder.branch(skip_nursery)

            self.builder.position_at_end(skip_nursery)

        cond_block = func.append_basic_block("for_cond")
        body_block = func.append_basic_block("for_body")
        inc_block = func.append_basic_block("for_inc")
        exit_block = func.append_basic_block("for_exit")

        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block

        self.builder.branch(cond_block)

        self.builder.position_at_end(cond_block)
        current = self.builder.load(loop_var)
        cond = self.builder.icmp_signed("<", current, end)
        self.builder.cbranch(cond, body_block, exit_block)

        self.builder.position_at_end(body_block)
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)

        self.builder.position_at_end(inc_block)
        current = self.builder.load(loop_var)
        next_val = self.builder.add(current, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_val, loop_var)
        self.builder.branch(cond_block)

        self.builder.position_at_end(exit_block)

        # Clean up nursery if used
        if use_nursery and nursery_ctx is not None and nursery_active is not None:
            # Check if nursery was actually created successfully
            was_active = self.builder.load(nursery_active)

            cleanup_nursery = func.append_basic_block("cleanup_nursery")
            after_cleanup = func.append_basic_block("after_cleanup")
            self.builder.cbranch(was_active, cleanup_nursery, after_cleanup)

            self.builder.position_at_end(cleanup_nursery)
            # Pop nursery from context stack
            self.builder.call(self.gc.gc_pop_context, [])

            # Promote loop-carried variables to main heap
            for lc_var in loop_carried_vars:
                if lc_var in self.locals:
                    var_ptr = self.locals[lc_var]
                    self._copy_collection_to_main_heap(lc_var, var_ptr, ir.IntType(64))

            # Destroy nursery (bulk-free all intermediate allocations)
            self.builder.call(self.gc.gc_destroy_context, [nursery_ctx])
            self.builder.branch(after_cleanup)

            self.builder.position_at_end(after_cleanup)

        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_list_for(self, stmt: ForStmt, list_ptr: ir.Value):
        """Generate for item in list with destructuring support"""
        func = self.builder.function
        
        # Get list length
        list_len = self.builder.call(self.list_len, [list_ptr])
        
        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = self.builder.alloca(ir.IntType(64), name="list_idx")
        self.builder.store(ir.Constant(ir.IntType(64), 0), index_var)
        
        # Create blocks
        cond_block = func.append_basic_block("list_for_cond")
        body_block = func.append_basic_block("list_for_body")
        inc_block = func.append_basic_block("list_for_inc")
        exit_block = func.append_basic_block("list_for_exit")
        
        # Save loop blocks
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block
        
        # Jump to condition
        self.builder.branch(cond_block)
        
        # Condition: index < len
        self.builder.position_at_end(cond_block)
        current_idx = self.builder.load(index_var)
        cond = self.builder.icmp_signed("<", current_idx, list_len)
        self.builder.cbranch(cond, body_block, exit_block)
        
        # Body
        self.builder.position_at_end(body_block)
        
        # Get element: list[index]
        current_idx = self.builder.load(index_var)
        elem_ptr = self.builder.call(self.list_get, [list_ptr, current_idx])
        
        # Determine element type from pattern or tracked type
        elem_type = self._get_list_element_type_for_pattern(stmt)
        typed_ptr = self.builder.bitcast(elem_ptr, elem_type.as_pointer())
        elem_val = self.builder.load(typed_ptr)

        # Bind pattern variables (supports destructuring)
        self._bind_pattern(stmt.pattern, elem_val)

        # Track Coex type for loop variable (enables method calls on string, etc.)
        if isinstance(stmt.pattern, IdentifierPattern):
            # Get element type from tracked list type
            elem_coex_type = self._get_list_element_coex_type(stmt)
            if elem_coex_type:
                self.var_coex_types[stmt.pattern.name] = elem_coex_type

        # Generate body statements
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)
        
        # Increment index
        self.builder.position_at_end(inc_block)
        current_idx = self.builder.load(index_var)
        next_idx = self.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_idx, index_var)
        self.builder.branch(cond_block)
        
        # Exit
        self.builder.position_at_end(exit_block)
        
        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_array_for(self, stmt: ForStmt, array_ptr: ir.Value):
        """Generate for item in array with destructuring support"""
        func = self.builder.function

        # Get array length
        array_len = self.builder.call(self.array_len, [array_ptr])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = self.builder.alloca(ir.IntType(64), name="array_idx")
        self.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("array_for_cond")
        body_block = func.append_basic_block("array_for_body")
        inc_block = func.append_basic_block("array_for_inc")
        exit_block = func.append_basic_block("array_for_exit")

        # Save loop blocks
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block

        # Jump to condition
        self.builder.branch(cond_block)

        # Condition: index < len
        self.builder.position_at_end(cond_block)
        current_idx = self.builder.load(index_var)
        cond = self.builder.icmp_signed("<", current_idx, array_len)
        self.builder.cbranch(cond, body_block, exit_block)

        # Body
        self.builder.position_at_end(body_block)

        # Get element: array[index]
        current_idx = self.builder.load(index_var)
        elem_ptr = self.builder.call(self.array_get, [array_ptr, current_idx])

        # Determine element type from pattern or tracked type
        elem_type = self._get_array_element_type_for_pattern(stmt)
        typed_ptr = self.builder.bitcast(elem_ptr, elem_type.as_pointer())
        elem_val = self.builder.load(typed_ptr)

        # Bind pattern variables (supports destructuring)
        self._bind_pattern(stmt.pattern, elem_val)

        # Generate body statements
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)

        # Increment index
        self.builder.position_at_end(inc_block)
        current_idx = self.builder.load(index_var)
        next_idx = self.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_idx, index_var)
        self.builder.branch(cond_block)

        # Exit
        self.builder.position_at_end(exit_block)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_map_for(self, stmt: ForStmt, map_ptr: ir.Value):
        """Generate for key in map - iterates over keys"""
        func = self.builder.function

        # Get keys as a list
        keys_list = self.builder.call(self.map_keys, [map_ptr])

        # Get list length
        list_len = self.builder.call(self.list_len, [keys_list])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = self.builder.alloca(ir.IntType(64), name="map_idx")
        self.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("map_for_cond")
        body_block = func.append_basic_block("map_for_body")
        inc_block = func.append_basic_block("map_for_inc")
        exit_block = func.append_basic_block("map_for_exit")

        # Save loop blocks
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block

        # Jump to condition
        self.builder.branch(cond_block)

        # Condition: index < len
        self.builder.position_at_end(cond_block)
        current_idx = self.builder.load(index_var)
        cond = self.builder.icmp_signed("<", current_idx, list_len)
        self.builder.cbranch(cond, body_block, exit_block)

        # Body
        self.builder.position_at_end(body_block)

        # Get key from list: keys_list[index]
        current_idx = self.builder.load(index_var)
        elem_ptr = self.builder.call(self.list_get, [keys_list, current_idx])

        # Keys are stored as i64 - load and bind
        typed_ptr = self.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
        key_val = self.builder.load(typed_ptr)

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_key"

        # Allocate and store key variable
        if var_name not in self.locals:
            key_alloca = self.builder.alloca(ir.IntType(64), name=var_name)
            self.locals[var_name] = key_alloca
        self.builder.store(key_val, self.locals[var_name])

        # Generate body statements
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)

        # Increment index
        self.builder.position_at_end(inc_block)
        current_idx = self.builder.load(index_var)
        next_idx = self.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_idx, index_var)
        self.builder.branch(cond_block)

        # Exit
        self.builder.position_at_end(exit_block)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_set_for(self, stmt: ForStmt, set_ptr: ir.Value):
        """Generate for elem in set - iterates over elements"""
        func = self.builder.function

        # Get elements as a list
        elems_list = self.builder.call(self.set_to_list, [set_ptr])

        # Get list length
        list_len = self.builder.call(self.list_len, [elems_list])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
                self.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = self.builder.alloca(ir.IntType(64), name="set_idx")
        self.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("set_for_cond")
        body_block = func.append_basic_block("set_for_body")
        inc_block = func.append_basic_block("set_for_inc")
        exit_block = func.append_basic_block("set_for_exit")

        # Save loop blocks
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = inc_block

        # Jump to condition
        self.builder.branch(cond_block)

        # Condition: index < len
        self.builder.position_at_end(cond_block)
        current_idx = self.builder.load(index_var)
        cond = self.builder.icmp_signed("<", current_idx, list_len)
        self.builder.cbranch(cond, body_block, exit_block)

        # Body
        self.builder.position_at_end(body_block)

        # Get element from list: elems_list[index]
        current_idx = self.builder.load(index_var)
        elem_ptr = self.builder.call(self.list_get, [elems_list, current_idx])

        # Elements are stored as i64 - load and bind
        typed_ptr = self.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
        elem_val = self.builder.load(typed_ptr)

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_elem"

        # Allocate and store element variable
        if var_name not in self.locals:
            elem_alloca = self.builder.alloca(ir.IntType(64), name=var_name)
            self.locals[var_name] = elem_alloca
        self.builder.store(elem_val, self.locals[var_name])

        # Generate body statements
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        if not self.builder.block.is_terminated:
            self.builder.branch(inc_block)

        # Increment index
        self.builder.position_at_end(inc_block)
        current_idx = self.builder.load(index_var)
        next_idx = self.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        self.builder.store(next_idx, index_var)
        self.builder.branch(cond_block)

        # Exit
        self.builder.position_at_end(exit_block)

        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue

    def _generate_for_assign(self, stmt: ForAssignStmt):
        """Generate results = for item in items expr"""
        # This is syntactic sugar for map operation
        # For now, implement as a simple loop that doesn't return a list
        # Full implementation would need list creation
        
        # Just generate as regular for loop for now
        for_stmt = ForStmt(stmt.pattern, stmt.iterable, [ExprStmt(stmt.body_expr)])
        self._generate_for(for_stmt)
    
    def _generate_break(self):
        """Generate a break statement"""
        if self.loop_exit_block:
            self.builder.branch(self.loop_exit_block)
    
    def _generate_continue(self):
        """Generate a continue statement"""
        if self.loop_continue_block:
            self.builder.branch(self.loop_continue_block)
    
    def _generate_match(self, stmt: MatchStmt):
        """Generate a match statement"""
        func = self.builder.function
        
        subject = self._generate_expression(stmt.subject)
        merge_block = func.append_basic_block("match_merge")
        
        # For each arm, generate a comparison and branch
        next_block = None
        for i, arm in enumerate(stmt.arms):
            if next_block:
                self.builder.position_at_end(next_block)
            
            arm_block = func.append_basic_block(f"match_arm_{i}")
            next_block = func.append_basic_block(f"match_next_{i}") if i < len(stmt.arms) - 1 else merge_block
            
            # Generate pattern match
            matched = self._generate_pattern_match(subject, arm.pattern)
            
            # Add guard if present
            if arm.guard:
                guard_block = func.append_basic_block(f"match_guard_{i}")
                self.builder.cbranch(matched, guard_block, next_block)
                self.builder.position_at_end(guard_block)
                guard = self._generate_expression(arm.guard)
                guard = self._to_bool(guard)
                self.builder.cbranch(guard, arm_block, next_block)
            else:
                self.builder.cbranch(matched, arm_block, next_block)
            
            # Generate arm body
            self.builder.position_at_end(arm_block)
            for s in arm.body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)
        
        self.builder.position_at_end(merge_block)
    
    def _generate_pattern_match(self, subject: ir.Value, pattern: Pattern) -> ir.Value:
        """Generate code to match a pattern, returns i1"""
        if isinstance(pattern, WildcardPattern):
            return ir.Constant(ir.IntType(1), 1)
        
        elif isinstance(pattern, LiteralPattern):
            literal = self._generate_expression(pattern.value)
            if isinstance(subject.type, ir.IntType):
                return self.builder.icmp_signed("==", subject, literal)
            elif isinstance(subject.type, ir.DoubleType):
                return self.builder.fcmp_ordered("==", subject, literal)
            return ir.Constant(ir.IntType(1), 0)
        
        elif isinstance(pattern, IdentifierPattern):
            # Check if this identifier is actually an enum variant (no-arg variant)
            enum_info = self._find_enum_variant(pattern.name)
            if enum_info:
                # This is an enum variant without arguments
                enum_name, variant_name = enum_info
                tag, fields = self.enum_variants[enum_name][variant_name]
                
                # Get tag from subject
                tag_ptr = self.builder.gep(subject, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), 0)
                ], inbounds=True)
                subject_tag = self.builder.load(tag_ptr)
                
                # Compare tags
                expected_tag = ir.Constant(ir.IntType(64), tag)
                return self.builder.icmp_signed("==", subject_tag, expected_tag)
            
            # Regular identifier - bind value to name
            alloca = self.builder.alloca(subject.type, name=pattern.name)
            self.builder.store(subject, alloca)
            self.locals[pattern.name] = alloca
            return ir.Constant(ir.IntType(1), 1)
        
        elif isinstance(pattern, ConstructorPattern):
            # Enum variant pattern: Circle(r) or Circle(radius: r)
            variant_name = pattern.name
            
            # Find which enum this variant belongs to
            enum_info = self._find_enum_variant(variant_name)
            if not enum_info:
                # Unknown variant, always fail
                return ir.Constant(ir.IntType(1), 0)
            
            enum_name, _ = enum_info
            tag, fields = self.enum_variants[enum_name][variant_name]
            
            # Get tag from subject
            tag_ptr = self.builder.gep(subject, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), 0)
            ], inbounds=True)
            subject_tag = self.builder.load(tag_ptr)
            
            # Compare tags
            expected_tag = ir.Constant(ir.IntType(64), tag)
            tag_match = self.builder.icmp_signed("==", subject_tag, expected_tag)
            
            # Bind pattern arguments to fields
            # pattern.args are the sub-patterns for each field
            for i, sub_pattern in enumerate(pattern.args):
                if i < len(fields):
                    field_name, field_type = fields[i]
                    
                    # Get field pointer (index i+1, after tag)
                    field_ptr = self.builder.gep(subject, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), i + 1)
                    ], inbounds=True)
                    field_val = self.builder.load(field_ptr)

                    # Convert back to proper type if needed
                    if isinstance(field_type, PrimitiveType) and field_type.name == "float":
                        field_val = self.builder.bitcast(field_val, ir.DoubleType())
                    # Phase 6: Reference type fields store i64 handles - convert to pointer
                    elif self._is_reference_type(field_type):
                        ptr_type = self._get_llvm_type(field_type)
                        field_val = self.builder.inttoptr(field_val, ptr_type)
                    
                    # If sub-pattern is an identifier, bind it
                    if isinstance(sub_pattern, IdentifierPattern):
                        alloca = self.builder.alloca(field_val.type, name=sub_pattern.name)
                        self.builder.store(field_val, alloca)
                        self.locals[sub_pattern.name] = alloca
                    # WildcardPattern: don't bind
                    # Other patterns: would need recursive matching
            
            return tag_match
        
        # Default: match
        return ir.Constant(ir.IntType(1), 1)
    
    # ========================================================================
    # Expression Generation
    # ========================================================================
    
    def _generate_expression(self, expr: Expr) -> ir.Value:
        """Generate code for an expression"""
        if isinstance(expr, IntLiteral):
            return ir.Constant(ir.IntType(64), expr.value)
        
        elif isinstance(expr, FloatLiteral):
            return ir.Constant(ir.DoubleType(), expr.value)
        
        elif isinstance(expr, BoolLiteral):
            return ir.Constant(ir.IntType(1), 1 if expr.value else 0)
        
        elif isinstance(expr, StringLiteral):
            return self._get_string_ptr(expr.value)
        
        elif isinstance(expr, NilLiteral):
            return ir.Constant(ir.IntType(64), 0)
        
        elif isinstance(expr, Identifier):
            return self._generate_identifier(expr)
        
        elif isinstance(expr, BinaryExpr):
            return self._generate_binary(expr)
        
        elif isinstance(expr, UnaryExpr):
            return self._generate_unary(expr)
        
        elif isinstance(expr, CallExpr):
            return self._generate_call(expr)
        
        elif isinstance(expr, MethodCallExpr):
            return self._generate_method_call(expr)
        
        elif isinstance(expr, MemberExpr):
            return self._generate_member(expr)
        
        elif isinstance(expr, IndexExpr):
            return self._generate_index(expr)

        elif isinstance(expr, SliceExpr):
            return self._generate_slice(expr)

        elif isinstance(expr, TernaryExpr):
            return self._generate_ternary(expr)
        
        elif isinstance(expr, ListExpr):
            return self._generate_list(expr)
        
        elif isinstance(expr, MapExpr):
            return self._generate_map(expr)

        elif isinstance(expr, SetExpr):
            return self._generate_set(expr)

        elif isinstance(expr, JsonObjectExpr):
            return self._generate_json_object(expr)

        elif isinstance(expr, ListComprehension):
            return self._generate_list_comprehension(expr)
        
        elif isinstance(expr, SetComprehension):
            return self._generate_set_comprehension(expr)
        
        elif isinstance(expr, MapComprehension):
            return self._generate_map_comprehension(expr)
        
        elif isinstance(expr, TupleExpr):
            return self._generate_tuple(expr)
        
        elif isinstance(expr, RangeExpr):
            return self._generate_range(expr)
        
        elif isinstance(expr, LambdaExpr):
            return self._generate_lambda(expr)
        
        elif isinstance(expr, SelfExpr):
            # Return self pointer if available
            if "self" in self.locals:
                return self.builder.load(self.locals["self"])
            return ir.Constant(ir.IntType(64), 0)
        
        elif isinstance(expr, CellExpr):
            # Matrix cell reference - current cell value
            return self._generate_cell_access()
        
        elif isinstance(expr, CellIndexExpr):
            # Matrix cell[dx, dy] - relative neighbor access
            return self._generate_cell_index_access(expr)

        elif isinstance(expr, LlvmIrExpr):
            return self._generate_llvm_ir_block(expr)

        elif isinstance(expr, AsExpr):
            return self._generate_as_expr(expr)

        else:
            return ir.Constant(ir.IntType(64), 0)
    
    def _generate_identifier(self, expr: Identifier) -> ir.Value:
        """Generate code for identifier reference"""
        name = expr.name

        # Check for use-after-move
        if name in self.moved_vars:
            raise RuntimeError(
                f"Use of moved variable '{name}': variable was moved and can no longer be used. "
                f"Assign a new value to '{name}' before using it again."
            )

        # Check if we're in a cycle and this is a cycle variable
        ctx = self._get_cycle_context()
        if ctx and name in ctx['cycle_vars']:
            # Read from read buffer (previous generation)
            read_buf = ctx['read_buffers'][name]
            return self.builder.load(read_buf, name=name)

        if name in self.locals:
            return self.builder.load(self.locals[name], name=name)
        elif name in self.functions:
            return self.functions[name]
        else:
            # Check if it's a field access in a method context
            if self.current_type and "self" in self.locals:
                field_idx = self._get_field_index(self.current_type, name)
                if field_idx is not None:
                    self_ptr = self.builder.load(self.locals["self"])
                    field_ptr = self.builder.gep(self_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), field_idx)
                    ], inbounds=True)
                    return self.builder.load(field_ptr, name=name)
            
            # Unknown variable - raise error
            raise RuntimeError(f"Undeclared identifier '{name}': variable has not been declared in this scope")
    
    def _generate_binary(self, expr: BinaryExpr) -> ir.Value:
        """Generate code for binary expression"""
        # Short-circuit evaluation for logical ops
        if expr.op == BinaryOp.AND:
            return self._generate_short_circuit_and(expr)
        elif expr.op == BinaryOp.OR:
            return self._generate_short_circuit_or(expr)
        
        left = self._generate_expression(expr.left)
        right = self._generate_expression(expr.right)
        
        # Check for String operations
        is_string = (isinstance(left.type, ir.PointerType) and 
                     hasattr(left.type.pointee, 'name') and 
                     left.type.pointee.name == "struct.String")
        
        if is_string:
            if expr.op == BinaryOp.ADD:
                # String concatenation: a + b -> string_concat(a, b)
                return self.builder.call(self.string_concat, [left, right])
            elif expr.op == BinaryOp.EQ:
                # String equality: a == b -> string_eq(a, b)
                return self.builder.call(self.string_eq, [left, right])
            elif expr.op == BinaryOp.NE:
                # String inequality: a != b -> !string_eq(a, b)
                eq_result = self.builder.call(self.string_eq, [left, right])
                return self.builder.not_(eq_result)
        
        # Promote types if needed
        if left.type != right.type:
            if isinstance(left.type, ir.IntType) and isinstance(right.type, ir.DoubleType):
                left = self.builder.sitofp(left, ir.DoubleType())
            elif isinstance(left.type, ir.DoubleType) and isinstance(right.type, ir.IntType):
                right = self.builder.sitofp(right, ir.DoubleType())
            elif isinstance(left.type, ir.IntType) and isinstance(right.type, ir.IntType):
                # Promote smaller to larger
                if left.type.width < right.type.width:
                    left = self.builder.sext(left, right.type)
                elif right.type.width < left.type.width:
                    right = self.builder.sext(right, left.type)
        
        is_float = isinstance(left.type, ir.DoubleType)
        
        if expr.op == BinaryOp.ADD:
            return self.builder.fadd(left, right) if is_float else self.builder.add(left, right)
        elif expr.op == BinaryOp.SUB:
            return self.builder.fsub(left, right) if is_float else self.builder.sub(left, right)
        elif expr.op == BinaryOp.MUL:
            return self.builder.fmul(left, right) if is_float else self.builder.mul(left, right)
        elif expr.op == BinaryOp.DIV:
            return self.builder.fdiv(left, right) if is_float else self.builder.sdiv(left, right)
        elif expr.op == BinaryOp.MOD:
            return self.builder.frem(left, right) if is_float else self.builder.srem(left, right)
        elif expr.op == BinaryOp.EQ:
            return self.builder.fcmp_ordered("==", left, right) if is_float else self.builder.icmp_signed("==", left, right)
        elif expr.op == BinaryOp.NE:
            return self.builder.fcmp_ordered("!=", left, right) if is_float else self.builder.icmp_signed("!=", left, right)
        elif expr.op == BinaryOp.LT:
            return self.builder.fcmp_ordered("<", left, right) if is_float else self.builder.icmp_signed("<", left, right)
        elif expr.op == BinaryOp.GT:
            return self.builder.fcmp_ordered(">", left, right) if is_float else self.builder.icmp_signed(">", left, right)
        elif expr.op == BinaryOp.LE:
            return self.builder.fcmp_ordered("<=", left, right) if is_float else self.builder.icmp_signed("<=", left, right)
        elif expr.op == BinaryOp.GE:
            return self.builder.fcmp_ordered(">=", left, right) if is_float else self.builder.icmp_signed(">=", left, right)
        elif expr.op == BinaryOp.NULL_COALESCE:
            # a ?? b -> if a has value, return unwrapped a, else return b
            # Handle optional types (struct {i1, T})
            if isinstance(left.type, ir.LiteralStructType) and len(left.type.elements) == 2:
                if isinstance(left.type.elements[0], ir.IntType) and left.type.elements[0].width == 1:
                    # This is an optional type - extract has_value and value
                    has_value = self.builder.extract_value(left, 0, name="has_value")
                    value = self.builder.extract_value(left, 1, name="opt_value")
                    return self.builder.select(has_value, value, right)
            # Handle pointer types (nil = null pointer)
            elif isinstance(left.type, ir.PointerType):
                null_ptr = ir.Constant(left.type, None)
                is_not_null = self.builder.icmp_unsigned("!=", left, null_ptr)
                return self.builder.select(is_not_null, left, right)
            # Fallback: treat as boolean check
            cond = self._to_bool(left)
            return self.builder.select(cond, left, right)
        
        return ir.Constant(ir.IntType(64), 0)
    
    def _generate_short_circuit_and(self, expr: BinaryExpr) -> ir.Value:
        """Generate short-circuit AND"""
        func = self.builder.function
        
        eval_right = func.append_basic_block("and_right")
        merge = func.append_basic_block("and_merge")
        
        left = self._generate_expression(expr.left)
        left_bool = self._to_bool(left)
        left_block = self.builder.block
        
        self.builder.cbranch(left_bool, eval_right, merge)
        
        self.builder.position_at_end(eval_right)
        right = self._generate_expression(expr.right)
        right_bool = self._to_bool(right)
        right_block = self.builder.block
        self.builder.branch(merge)
        
        self.builder.position_at_end(merge)
        phi = self.builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), left_block)
        phi.add_incoming(right_bool, right_block)
        
        return phi
    
    def _generate_short_circuit_or(self, expr: BinaryExpr) -> ir.Value:
        """Generate short-circuit OR"""
        func = self.builder.function
        
        eval_right = func.append_basic_block("or_right")
        merge = func.append_basic_block("or_merge")
        
        left = self._generate_expression(expr.left)
        left_bool = self._to_bool(left)
        left_block = self.builder.block
        
        self.builder.cbranch(left_bool, merge, eval_right)
        
        self.builder.position_at_end(eval_right)
        right = self._generate_expression(expr.right)
        right_bool = self._to_bool(right)
        right_block = self.builder.block
        self.builder.branch(merge)
        
        self.builder.position_at_end(merge)
        phi = self.builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 1), left_block)
        phi.add_incoming(right_bool, right_block)
        
        return phi
    
    def _generate_unary(self, expr: UnaryExpr) -> ir.Value:
        """Generate code for unary expression"""
        operand = self._generate_expression(expr.operand)
        
        if expr.op == UnaryOp.NEG:
            if isinstance(operand.type, ir.DoubleType):
                return self.builder.fneg(operand)
            else:
                return self.builder.neg(operand)
        elif expr.op == UnaryOp.NOT:
            if operand.type == ir.IntType(1):
                return self.builder.not_(operand)
            else:
                # Compare to zero
                cond = self._to_bool(operand)
                return self.builder.not_(cond)
        elif expr.op == UnaryOp.AWAIT:
            # In sequential mode, await just returns the value
            return operand
        
        return operand
    
    def _generate_call(self, expr: CallExpr) -> ir.Value:
        """Generate code for function call"""
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            explicit_type_args = expr.callee.type_args if hasattr(expr.callee, 'type_args') else []

            # Handle Array constructor specially: Array(capacity, initial_value)
            # This needs special handling because Array is a built-in type
            if name == "Array":
                return self._generate_array_constructor(expr.args)

            # Check if this is a type constructor: Point(x: 1, y: 2)
            if name in self.type_registry:
                return self._generate_type_constructor(name, expr.args, expr.named_args)
            
            # Check if this is a generic type constructor: Pair<int, float>(first: 1, second: 2.0)
            if name in self.generic_types:
                # Use explicit type args if provided, otherwise infer
                if explicit_type_args:
                    type_args = explicit_type_args
                else:
                    type_args = self._infer_type_args_from_constructor(name, expr.args, expr.named_args)
                if type_args:
                    mangled_name = self._monomorphize_type(name, type_args)
                    return self._generate_type_constructor(mangled_name, expr.args, expr.named_args)
            
            # Check if this is an enum variant constructor: Circle(radius: 5.0)
            enum_info = self._find_enum_variant(name)
            if enum_info:
                enum_name, variant_name = enum_info
                return self._generate_enum_constructor(enum_name, variant_name, expr.args, expr.named_args)
            
            # Built-in functions
            if name == "range":
                # range() returns iterator - handle in for loop
                return ir.Constant(ir.IntType(64), 0)

            if name == "str":
                # str(x) - for now just return the value
                if expr.args:
                    return self._generate_expression(expr.args[0])
                return ir.Constant(ir.IntType(64), 0)
            
            if name == "int":
                if expr.args:
                    val = self._generate_expression(expr.args[0])
                    if isinstance(val.type, ir.DoubleType):
                        return self.builder.fptosi(val, ir.IntType(64))
                    return self._cast_value(val, ir.IntType(64))
                return ir.Constant(ir.IntType(64), 0)
            
            if name == "float":
                if expr.args:
                    val = self._generate_expression(expr.args[0])
                    if isinstance(val.type, ir.IntType):
                        return self.builder.sitofp(val, ir.DoubleType())
                    return val
                return ir.Constant(ir.DoubleType(), 0.0)
            
            if name == "sqrt":
                # Would need to link math library
                if expr.args:
                    val = self._generate_expression(expr.args[0])
                    # For now just return the value
                    return val
                return ir.Constant(ir.DoubleType(), 0.0)

            if name == "gc":
                # Trigger garbage collection (waits for completion)
                self.builder.call(self.gc.gc_collect, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_async":
                # Trigger async garbage collection (returns immediately)
                self.builder.call(self.gc.gc_async, [])
                return ir.Constant(ir.IntType(64), 0)

            # Phase 0: GC debugging infrastructure builtins
            if name == "gc_dump_stats":
                # Print GC statistics
                self.builder.call(self.gc.gc_dump_stats, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_heap":
                # Print all objects in the heap
                self.builder.call(self.gc.gc_dump_heap, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_roots":
                # Print all roots from shadow stack
                self.builder.call(self.gc.gc_dump_roots, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_validate_heap":
                # Validate heap integrity - returns 0 if valid, error code otherwise
                result = self.builder.call(self.gc.gc_validate_heap, [])
                return result

            if name == "gc_set_trace_level":
                # Set GC trace verbosity level (0-4)
                if expr.args:
                    level = self._generate_expression(expr.args[0])
                    if level.type != ir.IntType(64):
                        level = self.builder.sext(level, ir.IntType(64))
                    self.builder.call(self.gc.gc_set_trace_level, [level])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_fragmentation_report":
                # Print heap fragmentation analysis
                self.builder.call(self.gc.gc_fragmentation_report, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_handle_table":
                # Print handle table state
                self.builder.call(self.gc.gc_dump_handle_table, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_shadow_stacks":
                # Print shadow stack frames and roots
                self.builder.call(self.gc.gc_dump_shadow_stacks, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "print":
                # print(value) - generate appropriate print based on type
                if expr.args:
                    value = self._generate_expression(expr.args[0])
                    
                    if isinstance(value.type, ir.IntType):
                        if value.type.width == 1:
                            # Boolean
                            true_block = self.builder.append_basic_block("print_true")
                            false_block = self.builder.append_basic_block("print_false")
                            merge_block = self.builder.append_basic_block("print_merge")
                            
                            self.builder.cbranch(value, true_block, false_block)
                            
                            self.builder.position_at_end(true_block)
                            fmt_ptr = self.builder.bitcast(self._true_str, ir.IntType(8).as_pointer())
                            self.builder.call(self.printf, [fmt_ptr])
                            self.builder.branch(merge_block)
                            
                            self.builder.position_at_end(false_block)
                            fmt_ptr = self.builder.bitcast(self._false_str, ir.IntType(8).as_pointer())
                            self.builder.call(self.printf, [fmt_ptr])
                            self.builder.branch(merge_block)
                            
                            self.builder.position_at_end(merge_block)
                        else:
                            # Integer
                            fmt_ptr = self.builder.bitcast(self._int_fmt, ir.IntType(8).as_pointer())
                            if value.type.width < 64:
                                value = self.builder.sext(value, ir.IntType(64))
                            self.builder.call(self.printf, [fmt_ptr, value])
                    
                    elif isinstance(value.type, ir.DoubleType):
                        fmt_ptr = self.builder.bitcast(self._float_fmt, ir.IntType(8).as_pointer())
                        self.builder.call(self.printf, [fmt_ptr, value])
                    
                    elif isinstance(value.type, ir.PointerType):
                        pointee = value.type.pointee
                        if hasattr(pointee, 'name') and pointee.name == "struct.String":
                            self.builder.call(self.string_print, [value])
                        else:
                            fmt_ptr = self.builder.bitcast(self._str_fmt, ir.IntType(8).as_pointer())
                            self.builder.call(self.printf, [fmt_ptr, value])

                    # Flush stdout to ensure output appears in correct order
                    null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
                    self.builder.call(self.fflush, [null_ptr])

                return ir.Constant(ir.IntType(64), 0)

            # Check for replace alias: abs -> math.abs
            if name in self.replace_aliases:
                module_name, qualified_name = self.replace_aliases[name]
                module_info = self.loaded_modules[module_name]
                if qualified_name in module_info.functions:
                    mangled = module_info.functions[qualified_name]
                    func = self.functions[mangled]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self._generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
                            arg_val = self._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return self.builder.call(func, args)
                else:
                    raise RuntimeError(f"Function '{qualified_name}' not found in module '{module_name}'")

            # Check if this is an extern function call
            extern_decls = getattr(self, 'extern_function_decls', {})
            if name in extern_decls:
                return self._generate_extern_call(name, expr.args, extern_decls[name])

            # Look up function
            if name in self.functions:
                func = self.functions[name]
                args = []
                for i, arg in enumerate(expr.args):
                    arg_val = self._generate_expression(arg)
                    # Cast to expected type
                    if i < len(func.args):
                        expected = func.args[i].type
                        arg_val = self._cast_value(arg_val, expected)
                    args.append(arg_val)
                return self.builder.call(func, args)
            
            # Check for generic function
            if name in self.generic_functions:
                # Use explicit type args if provided, otherwise infer
                if explicit_type_args:
                    type_args = explicit_type_args
                else:
                    type_args = self._infer_type_args(name, expr.args)
                if type_args:
                    mangled = self._monomorphize_function(name, type_args)
                    func = self.functions[mangled]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self._generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
                            arg_val = self._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return self.builder.call(func, args)
        
        elif isinstance(expr.callee, MemberExpr):
            # Check for module-qualified call: module.function(args)
            if isinstance(expr.callee.object, Identifier):
                possible_module = expr.callee.object.name
                func_name = expr.callee.member

                # Check if this is a loaded module
                if possible_module in self.loaded_modules:
                    module_info = self.loaded_modules[possible_module]
                    if func_name in module_info.functions:
                        mangled = module_info.functions[func_name]
                        func = self.functions[mangled]
                        args = []
                        for i, arg in enumerate(expr.args):
                            arg_val = self._generate_expression(arg)
                            if i < len(func.args):
                                expected = func.args[i].type
                                arg_val = self._cast_value(arg_val, expected)
                            args.append(arg_val)
                        return self.builder.call(func, args)
                    else:
                        raise RuntimeError(f"Function '{func_name}' not found in module '{possible_module}'")

            # Check for Type.new() pattern
            if isinstance(expr.callee.object, Identifier):
                type_name = expr.callee.object.name
                if type_name in self.type_registry and expr.callee.member == "new":
                    return self._generate_type_new(type_name, expr.args)

                # Check for EnumType.VariantName(args) pattern
                if type_name in self.enum_variants:
                    variant_name = expr.callee.member
                    if variant_name in self.enum_variants[type_name]:
                        return self._generate_enum_constructor(type_name, variant_name, expr.args, expr.named_args)

            # Static method call: Type.method()
            return self._generate_method_call(MethodCallExpr(
                expr.callee.object, expr.callee.member, expr.args))
        
        # If we get here with an Identifier callee, check if it's a function pointer in locals
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            if name in self.locals:
                # Load the function pointer
                ptr = self.locals[name]
                func_ptr = self.builder.load(ptr)
                
                # Check if it's a function pointer type
                if isinstance(func_ptr.type, ir.PointerType) and isinstance(func_ptr.type.pointee, ir.FunctionType):
                    # Generate arguments
                    args = []
                    for arg in expr.args:
                        arg_val = self._generate_expression(arg)
                        args.append(arg_val)
                    
                    # Indirect call through function pointer
                    return self.builder.call(func_ptr, args)
                
                # Also handle case where func_ptr IS a function (not a pointer to pointer)
                if isinstance(func_ptr.type, ir.FunctionType):
                    args = []
                    for arg in expr.args:
                        arg_val = self._generate_expression(arg)
                        args.append(arg_val)
                    return self.builder.call(func_ptr, args)
        
        return ir.Constant(ir.IntType(64), 0)

    def _generate_array_constructor(self, args: PyList['Expr']) -> ir.Value:
        """Generate code for Array(capacity, initial_value) constructor.

        Creates an Array with the given capacity, initialized with the given value.
        Array layout: { i8* data, i64 len, i64 cap, i64 elem_size }
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Parse arguments: Array(capacity, initial_value)
        if len(args) < 2:
            # Need at least capacity and initial value
            return ir.Constant(ir.IntType(8).as_pointer(), None)

        capacity = self._generate_expression(args[0])
        initial_value = self._generate_expression(args[1])

        # Determine element size (8 bytes for int/float, 1 for bool, etc.)
        if isinstance(initial_value.type, ir.IntType):
            if initial_value.type.width == 1:
                elem_size = ir.Constant(i64, 1)  # bool
            else:
                elem_size = ir.Constant(i64, 8)  # int
        elif isinstance(initial_value.type, ir.DoubleType):
            elem_size = ir.Constant(i64, 8)  # float
        elif isinstance(initial_value.type, ir.PointerType):
            elem_size = ir.Constant(i64, 8)  # pointer
        else:
            elem_size = ir.Constant(i64, 8)  # default

        # Call array_new to create the array
        array_ptr = self.builder.call(self.array_new, [capacity, elem_size])

        # Set len = capacity (we're initializing all elements) - field 2
        len_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        self.builder.store(capacity, len_ptr)

        # Fill the array with the initial value
        # Get data pointer: compute owner + offset (Phase 4: owner is i64 handle)
        owner_handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = self.builder.load(owner_handle_ptr)
        owner_ptr = self.builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset_val = self.builder.load(offset_ptr)
        data_ptr = self.builder.gep(owner_ptr, [offset_val])

        # Loop to initialize all elements
        current_func = self.builder.block.parent
        init_header = current_func.append_basic_block("array_init_header")
        init_body = current_func.append_basic_block("array_init_body")
        init_done = current_func.append_basic_block("array_init_done")

        # Loop counter
        counter = self.builder.alloca(i64, name="init_counter")
        self.builder.store(ir.Constant(i64, 0), counter)
        self.builder.branch(init_header)

        # Header: check if counter < capacity
        self.builder.position_at_end(init_header)
        i = self.builder.load(counter)
        done = self.builder.icmp_unsigned(">=", i, capacity)
        self.builder.cbranch(done, init_done, init_body)

        # Body: store initial_value at data[i]
        self.builder.position_at_end(init_body)
        i_val = self.builder.load(counter)
        offset = self.builder.mul(i_val, elem_size)
        elem_ptr = self.builder.gep(data_ptr, [offset], inbounds=True)

        # Cast and store based on element type
        if isinstance(initial_value.type, ir.IntType) and initial_value.type.width == 64:
            typed_ptr = self.builder.bitcast(elem_ptr, i64.as_pointer())
            self.builder.store(initial_value, typed_ptr)
        elif isinstance(initial_value.type, ir.DoubleType):
            typed_ptr = self.builder.bitcast(elem_ptr, ir.DoubleType().as_pointer())
            self.builder.store(initial_value, typed_ptr)
        elif isinstance(initial_value.type, ir.IntType) and initial_value.type.width == 1:
            typed_ptr = self.builder.bitcast(elem_ptr, ir.IntType(8).as_pointer())
            val_i8 = self.builder.zext(initial_value, ir.IntType(8))
            self.builder.store(val_i8, typed_ptr)
        else:
            # For pointers and other types, cast to i64
            typed_ptr = self.builder.bitcast(elem_ptr, i64.as_pointer())
            if isinstance(initial_value.type, ir.PointerType):
                val_i64 = self.builder.ptrtoint(initial_value, i64)
            else:
                val_i64 = self._cast_value(initial_value, i64)
            self.builder.store(val_i64, typed_ptr)

        # Increment counter
        next_i = self.builder.add(i_val, ir.Constant(i64, 1))
        self.builder.store(next_i, counter)
        self.builder.branch(init_header)

        # Done
        self.builder.position_at_end(init_done)
        return array_ptr

    def _generate_type_constructor(self, type_name: str, args: PyList[Expr], named_args: Dict[str, Expr]) -> ir.Value:
        """Generate code for type constructor: Point(x: 1, y: 2)"""
        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]

        # Calculate size - estimate 8 bytes per field (works for most types)
        size = len(field_info) * 8 if field_info else 8
        size_val = ir.Constant(ir.IntType(64), size)

        # Allocate via GC with registered type ID
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id(type_name))
        raw_ptr = self.gc.alloc_with_deref(self.builder, size_val, type_id)
        ptr = self.builder.bitcast(raw_ptr, struct_type.as_pointer())
        
        # Initialize fields
        # First, handle named arguments
        field_values = {}
        for name, value_expr in named_args.items():
            field_values[name] = self._generate_expression(value_expr)
        
        # Then positional arguments (match order of fields)
        for i, arg in enumerate(args):
            if i < len(field_info):
                field_name = field_info[i][0]
                if field_name not in field_values:
                    field_values[field_name] = self._generate_expression(arg)
        
        # Store each field
        i64 = ir.IntType(64)
        for i, (field_name, field_type) in enumerate(field_info):
            field_ptr = self.builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i)
            ], inbounds=True)

            if field_name in field_values:
                value = field_values[field_name]
                # Phase 6: Reference type fields store as i64 handles
                if self._is_reference_type(field_type):
                    # Get handle for the object (not raw ptrtoint!)
                    if isinstance(value.type, ir.PointerType):
                        # Cast to i8* for gc_ptr_to_handle
                        value_i8 = self.builder.bitcast(value, ir.IntType(8).as_pointer())
                        value = self.builder.call(self.gc.gc_ptr_to_handle, [value_i8])
                    elif value.type != i64:
                        value = self._cast_value(value, i64)
                else:
                    # Cast if needed
                    expected_type = self._get_llvm_type(field_type)
                    value = self._cast_value(value, expected_type)
                self.builder.store(value, field_ptr)
            else:
                # Default initialize to zero (0 = null handle for reference types)
                expected_type = i64 if self._is_reference_type(field_type) else self._get_llvm_type(field_type)
                default = self._get_default_value_for_llvm(expected_type)
                self.builder.store(default, field_ptr)

        return ptr
    
    def _generate_type_new(self, type_name: str, args: PyList[Expr]) -> ir.Value:
        """Generate code for Type.new() - allocate and zero-initialize"""
        i64 = ir.IntType(64)
        # Special handling for built-in types
        if type_name == "Map":
            # Default flags=0 (no heap pointers) - caller should use typed Map literal if needed
            return self.builder.call(self.map_new, [ir.Constant(i64, 0)])

        if type_name == "Set":
            # Default flags=0 (no heap pointers)
            return self.builder.call(self.set_new, [ir.Constant(i64, 0)])
        
        if type_name == "atomic_ref":
            # atomic_ref.new(value) or atomic_ref.new() for nil
            if args:
                initial = self._generate_expression(args[0])
                initial = self._cast_value(initial, ir.IntType(64))
            else:
                initial = ir.Constant(ir.IntType(64), 0)  # nil
            return self.builder.call(self.atomic_ref_new, [initial])
        
        # Check if this is a matrix type
        if type_name in self.matrix_decls:
            # Call the matrix constructor function
            func_name = f"Matrix_{type_name}_new"
            if func_name in self.functions:
                func = self.functions[func_name]
                return self.builder.call(func, [])
            return ir.Constant(ir.IntType(8).as_pointer(), None)
        
        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]

        # Allocate via GC
        size = len(field_info) * 8 if field_info else 8  # Simplified size calculation
        size_val = ir.Constant(ir.IntType(64), size)
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id(type_name))

        raw_ptr = self.gc.alloc_with_deref(self.builder, size_val, type_id)
        ptr = self.builder.bitcast(raw_ptr, struct_type.as_pointer())

        # Zero-initialize all fields
        for i, (field_name, field_type) in enumerate(field_info):
            field_ptr = self.builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i)
            ], inbounds=True)

            # Phase 6: Reference type fields use i64 handles (0 = null)
            if self._is_reference_type(field_type):
                default = ir.Constant(i64, 0)
            else:
                expected_type = self._get_llvm_type(field_type)
                default = self._get_default_value_for_llvm(expected_type)
            self.builder.store(default, field_ptr)

        return ptr
    
    def _find_enum_variant(self, variant_name: str) -> Optional[Tuple[str, str]]:
        """Find which enum a variant belongs to. Returns (enum_name, variant_name) or None"""
        if not hasattr(self, 'enum_variants'):
            return None
        
        for enum_name, variants in self.enum_variants.items():
            if variant_name in variants:
                return (enum_name, variant_name)
        return None
    
    def _generate_enum_constructor(self, enum_name: str, variant_name: str, 
                                    args: PyList[Expr], named_args: Dict[str, Expr]) -> ir.Value:
        """Generate code for enum variant constructor: Circle(radius: 5.0)"""
        struct_type = self.type_registry[enum_name]
        variant_info = self.enum_variants[enum_name][variant_name]
        tag, fields = variant_info
        
        # Allocate enum struct via GC
        # Count: 1 (tag) + max_fields
        max_fields = max(len(v[1]) for v in self.enum_variants[enum_name].values())
        size = (1 + max_fields) * 8
        size_val = ir.Constant(ir.IntType(64), size)

        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id(enum_name))
        raw_ptr = self.gc.alloc_with_deref(self.builder, size_val, type_id)
        ptr = self.builder.bitcast(raw_ptr, struct_type.as_pointer())
        
        # Store tag
        tag_ptr = self.builder.gep(ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        self.builder.store(ir.Constant(ir.IntType(64), tag), tag_ptr)
        
        # Process arguments - build field values dict
        field_values = {}
        for name, value_expr in named_args.items():
            field_values[name] = self._generate_expression(value_expr)
        
        # Handle positional arguments
        for i, arg in enumerate(args):
            if i < len(fields):
                field_name = fields[i][0]
                if field_name not in field_values:
                    field_values[field_name] = self._generate_expression(arg)
        
        # Store payload fields (starting at index 1, after tag)
        for i, (field_name, field_type) in enumerate(fields):
            field_ptr = self.builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i + 1)  # +1 for tag
            ], inbounds=True)
            
            if field_name in field_values:
                value = field_values[field_name]
                # Cast to i64 for storage
                if isinstance(value.type, ir.DoubleType):
                    # Store double as bits in i64
                    value = self.builder.bitcast(value, ir.IntType(64))
                elif value.type != ir.IntType(64):
                    value = self._cast_value(value, ir.IntType(64))
                self.builder.store(value, field_ptr)
            else:
                self.builder.store(ir.Constant(ir.IntType(64), 0), field_ptr)
        
        return ptr

    def _generate_method_call(self, expr: MethodCallExpr) -> ir.Value:
        """Generate code for method call"""
        # Check if this is a call on a type identifier (static method)
        if isinstance(expr.object, Identifier):
            type_name = expr.object.name
            if type_name in self.type_registry:
                # Static method call: Type.method()
                if expr.method == "new":
                    return self._generate_type_new(type_name, expr.args)

                # Special handling for String.from() - dispatch based on argument type
                if type_name == "String" and expr.method == "from" and expr.args:
                    arg_val = self._generate_expression(expr.args[0])
                    arg_type = arg_val.type

                    # Dispatch based on argument type
                    if isinstance(arg_type, ir.IntType):
                        if arg_type.width == 1:
                            # Boolean
                            return self.builder.call(self.string_from_bool, [arg_val])
                        else:
                            # Integer (i64, i32, etc.)
                            arg_val = self._cast_value(arg_val, ir.IntType(64))
                            return self.builder.call(self.string_from_int, [arg_val])
                    elif isinstance(arg_type, ir.DoubleType):
                        # Float
                        return self.builder.call(self.string_from_float, [arg_val])
                    else:
                        # Default to int conversion
                        arg_val = self._cast_value(arg_val, ir.IntType(64))
                        return self.builder.call(self.string_from_int, [arg_val])

                # Special handling for String.from_bytes() - convert byte array to string
                if type_name == "String" and expr.method == "from_bytes" and expr.args:
                    arg_val = self._generate_expression(expr.args[0])
                    # Ensure it's a list pointer
                    if isinstance(arg_val.type, ir.PointerType):
                        return self.builder.call(self.string_from_bytes, [arg_val])
                    # If not a pointer, return empty string as fallback
                    return self.builder.call(self.string_from_literal, [self._get_string_literal("")])

                # Look for static methods (factory methods)
                mangled = f"{type_name}_{expr.method}"
                if mangled in self.functions:
                    func = self.functions[mangled]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self._generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
                            arg_val = self._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return self.builder.call(func, args)
        
        # Instance method call: obj.method()
        obj = self._generate_expression(expr.object)
        method = expr.method

        # Try to determine the type from the pointer
        type_name = self._get_type_name_from_ptr(obj.type)

        # Special handling for Map with string keys
        if type_name == "Map" and method in ("get", "has", "set") and expr.args:
            # Check if key is string type
            key_arg = self._generate_expression(expr.args[0])
            is_string_key = (isinstance(key_arg.type, ir.PointerType) and
                            hasattr(key_arg.type.pointee, 'name') and
                            key_arg.type.pointee.name == "struct.String")

            if is_string_key:
                if method == "get":
                    result = self.builder.call(self.map_get_string, [obj, key_arg])
                    # Convert result to proper type if value is a pointer
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in self.var_coex_types:
                            coex_type = self.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_llvm_type = self._get_llvm_type(coex_type.value_type)
                                if isinstance(value_llvm_type, ir.PointerType):
                                    return self.builder.inttoptr(result, value_llvm_type)
                    return result
                elif method == "has":
                    return self.builder.call(self.map_has_string, [obj, key_arg])
                elif method == "set":
                    value_arg = self._generate_expression(expr.args[1])
                    value_i64 = self._cast_value(value_arg, ir.IntType(64))
                    return self.builder.call(self.map_set_string, [obj, key_arg, value_i64])

        # Special handling for Set with string elements
        if type_name == "Set" and method in ("has", "add") and expr.args:
            # Check if element is string type
            elem_arg = self._generate_expression(expr.args[0])
            is_string_elem = (isinstance(elem_arg.type, ir.PointerType) and
                            hasattr(elem_arg.type.pointee, 'name') and
                            elem_arg.type.pointee.name == "struct.String")

            if is_string_elem:
                if method == "has":
                    return self.builder.call(self.set_has_string, [obj, elem_arg])
                elif method == "add":
                    return self.builder.call(self.set_add_string, [obj, elem_arg])

        if type_name and type_name in self.type_methods:
            method_map = self.type_methods[type_name]
            if method in method_map:
                mangled = method_map[method]
                func = self.functions[mangled]

                # Build args: self first, then other args
                args = [obj]
                for i, arg in enumerate(expr.args):
                    arg_val = self._generate_expression(arg)
                    # Cast to expected type (args[i+1] because args[0] is self)
                    if i + 1 < len(func.args):
                        expected = func.args[i + 1].type
                        # Special handling for Json methods: convert value arg to Json*
                        if type_name == "Json" and isinstance(expected, ir.PointerType):
                            if hasattr(expected.pointee, 'name') and expected.pointee.name == "struct.Json":
                                # Convert arg to JSON if it's not already
                                if not (isinstance(arg_val.type, ir.PointerType) and
                                        hasattr(arg_val.type.pointee, 'name') and
                                        arg_val.type.pointee.name == "struct.Json"):
                                    arg_val = self._convert_to_json(arg_val, arg)
                        else:
                            arg_val = self._cast_value(arg_val, expected)
                    args.append(arg_val)

                result = self.builder.call(func, args)

                # Special handling for List.get and Array.get - returns pointer that needs dereferencing
                if (type_name == "List" or type_name == "Array") and method == "get":
                    # Try to get element type from Coex type tracking
                    elem_llvm_type = ir.IntType(64)  # default
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in self.var_coex_types:
                            coex_type = self.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_llvm_type = self._get_llvm_type(coex_type.element_type)
                    # Result is i8*, bitcast to proper element type pointer and load
                    typed_ptr = self.builder.bitcast(result, elem_llvm_type.as_pointer())
                    return self.builder.load(typed_ptr)

                # Special handling for Map.get - returns i64 that may be a pointer
                if type_name == "Map" and method == "get":
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in self.var_coex_types:
                            coex_type = self.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_llvm_type = self._get_llvm_type(coex_type.value_type)
                                # If value type is a pointer, convert i64 result back to pointer
                                if isinstance(value_llvm_type, ir.PointerType):
                                    return self.builder.inttoptr(result, value_llvm_type)
                    return result

                # Special handling for Result.unwrap and Result.unwrap_or - returns typed value
                if type_name == "Result" and method in ("unwrap", "unwrap_or"):
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in self.var_coex_types:
                            coex_type = self.var_coex_types[var_name]
                            if isinstance(coex_type, ResultType):
                                ok_llvm_type = self._get_llvm_type(coex_type.ok_type)
                                # If ok_type is a pointer, convert i64 result back to pointer
                                if isinstance(ok_llvm_type, ir.PointerType):
                                    return self.builder.inttoptr(result, ok_llvm_type)
                    return result

                return result
        
        # Built-in methods for primitive types
        if method == "new":
            # Type.new() - already handled above for known types
            return ir.Constant(ir.IntType(8).as_pointer(), None)
        
        if method == "append":
            # list.append(value) - returns a NEW list with value appended (value semantics)
            if expr.args and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    elem_val = self._generate_expression(expr.args[0])
                    elem_type = elem_val.type

                    # Calculate element size (min 1 byte for sub-byte types like bool)
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        # For tuples/structs, sum up element sizes
                        size = sum(
                            max(1, e.width // 8) if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
                    # IMPORTANT: Place alloca in entry block to avoid stack growth in loops
                    with self.builder.goto_entry_block():
                        temp = self.builder.alloca(elem_type, name="append_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    # Call list_append which returns a NEW list (value semantics)
                    return self.builder.call(self.list_append, [obj, temp_ptr, elem_size])

                # Check if this is an Array - Array.append returns a NEW array
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    elem_val = self._generate_expression(expr.args[0])
                    elem_type = elem_val.type

                    # Calculate element size (min 1 byte for sub-byte types like bool)
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        size = sum(
                            max(1, e.width // 8) if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
                    # IMPORTANT: Place alloca in entry block to avoid stack growth in loops
                    with self.builder.goto_entry_block():
                        temp = self.builder.alloca(elem_type, name="array_append_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    # Call array_append which returns a NEW array
                    return self.builder.call(self.array_append, [obj, temp_ptr, elem_size])

            return ir.Constant(ir.IntType(64), 0)

        if method == "set":
            # list.set(index, value) or array.set(index, value) - returns a NEW collection with element at index replaced
            if len(expr.args) >= 2 and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee

                # List.set(index, value) - returns NEW list with path copying
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    index = self._generate_expression(expr.args[0])
                    elem_val = self._generate_expression(expr.args[1])
                    elem_type = elem_val.type

                    # Calculate element size (min 1 byte for sub-byte types like bool)
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        size = sum(
                            max(1, e.width // 8) if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
                    # IMPORTANT: Place alloca in entry block to avoid stack growth in loops
                    with self.builder.goto_entry_block():
                        temp = self.builder.alloca(elem_type, name="list_set_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    # Cast index to i64 if needed
                    if index.type != ir.IntType(64):
                        index = self.builder.sext(index, ir.IntType(64))

                    # Call list_set which returns a NEW list with path copying
                    return self.builder.call(self.list_set, [obj, index, temp_ptr, elem_size])

                # Array.set(index, value) - returns NEW array
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    index = self._generate_expression(expr.args[0])
                    elem_val = self._generate_expression(expr.args[1])
                    elem_type = elem_val.type

                    # Calculate element size (min 1 byte for sub-byte types like bool)
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        size = sum(
                            max(1, e.width // 8) if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
                    # IMPORTANT: Place alloca in entry block to avoid stack growth in loops
                    with self.builder.goto_entry_block():
                        temp = self.builder.alloca(elem_type, name="array_set_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    # Cast index to i64 if needed
                    if index.type != ir.IntType(64):
                        index = self.builder.sext(index, ir.IntType(64))

                    # Call array_set which returns a NEW array
                    return self.builder.call(self.array_set, [obj, index, temp_ptr, elem_size])

            return ir.Constant(ir.IntType(64), 0)

        if method == "load":
            # atomic.load() - just return value
            return obj
        
        if method == "store":
            # atomic.store(value) - store value
            return ir.Constant(ir.IntType(64), 0)
        
        if method == "increment":
            # atomic_int.increment() - add 1 and return old value
            if isinstance(obj.type, ir.IntType):
                return obj
            return ir.Constant(ir.IntType(64), 0)
        
        if method == "fetch_add":
            # atomic.fetch_add(delta)
            return obj

        if method == "packed" or method == "toArray":
            # List.toArray() -> Array or Set.toArray() -> Array
            # Convert collection to dense Array
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    return self._list_to_array(obj)
                if hasattr(pointee, 'name') and pointee.name == "struct.Set":
                    return self._set_to_array(obj)
            return ir.Constant(ir.IntType(64), 0)

        if method == "unpacked" or method == "toList":
            # Array.toList() -> List
            # Convert Array to persistent List
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    return self._array_to_list(obj)
            return ir.Constant(ir.IntType(64), 0)

        if method == "toSet" or method == "to_set":
            # Array.toSet() -> Set or List.to_set() -> Set
            # Convert Array/List to Set (deduplicates)
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    return self._array_to_set(obj)
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    return self._list_to_set(obj)
            return ir.Constant(ir.IntType(64), 0)

        # Generic method lookup failed - raise error
        if type_name:
            raise RuntimeError(f"Undefined method '{method}' on type '{type_name}'")
        else:
            raise RuntimeError(f"Undefined method '{method}' on unknown type")
    
    def _get_type_name_from_ptr(self, llvm_type: ir.Type) -> Optional[str]:
        """Get the Coex type name from an LLVM pointer type"""
        if not isinstance(llvm_type, ir.PointerType):
            return None
        
        pointee = llvm_type.pointee
        if hasattr(pointee, 'name'):
            # struct.TypeName -> TypeName
            if pointee.name.startswith("struct."):
                return pointee.name[7:]  # Remove "struct." prefix
        
        return None
    
    def _generate_member(self, expr: MemberExpr) -> ir.Value:
        """Generate code for member access"""
        # Check for enum variant access: EnumName.VariantName
        if isinstance(expr.object, Identifier):
            type_name = expr.object.name
            if hasattr(self, 'enum_variants') and type_name in self.enum_variants:
                variant_name = expr.member
                if variant_name in self.enum_variants[type_name]:
                    # This is an enum variant with no arguments (like Color.Green)
                    return self._generate_enum_constructor(type_name, variant_name, [], {})
        
        obj = self._generate_expression(expr.object)
        
        # Check if this is a tuple (literal struct type)
        if isinstance(obj.type, ir.LiteralStructType):
            # Tuple member access
            # Check if member is a numeric index (0, 1, 2, ...)
            if expr.member.isdigit():
                idx = int(expr.member)
                if idx < len(obj.type.elements):
                    return self.builder.extract_value(obj, idx)
            else:
                # Named tuple access - need to look up the index
                tuple_info = self._get_tuple_field_info(expr.object)
                if tuple_info:
                    for i, (name, _) in enumerate(tuple_info):
                        if name == expr.member:
                            return self.builder.extract_value(obj, i)
            return ir.Constant(ir.IntType(64), 0)
        
        # Check for pointer to literal struct (tuple stored in variable)
        if isinstance(obj.type, ir.PointerType) and isinstance(obj.type.pointee, ir.LiteralStructType):
            struct_type = obj.type.pointee
            if expr.member.isdigit():
                idx = int(expr.member)
                if idx < len(struct_type.elements):
                    ptr = self.builder.gep(obj, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), idx)
                    ])
                    return self.builder.load(ptr)
            else:
                # Named access
                tuple_info = self._get_tuple_field_info(expr.object)
                if tuple_info:
                    for i, (name, _) in enumerate(tuple_info):
                        if name == expr.member:
                            ptr = self.builder.gep(obj, [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), i)
                            ])
                            return self.builder.load(ptr)
        
        # Try to determine the type from the pointer
        type_name = self._get_type_name_from_ptr(obj.type)

        if type_name and type_name in self.type_fields:
            field_idx = self._get_field_index(type_name, expr.member)
            if field_idx is not None:
                # GEP to get field pointer
                field_ptr = self.builder.gep(obj, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), field_idx)
                ], inbounds=True)
                field_val = self.builder.load(field_ptr)

                # Phase 6: Reference type fields store i64 handles - convert to pointer
                field_info = self.type_fields[type_name]
                if field_idx < len(field_info):
                    _, field_type = field_info[field_idx]
                    if self._is_reference_type(field_type):
                        # Field contains a handle - dereference to get pointer
                        ptr_i8 = self.builder.call(self.gc.gc_handle_deref, [field_val])
                        ptr_type = self._get_llvm_type(field_type)
                        return self.builder.bitcast(ptr_i8, ptr_type)

                return field_val
        
        # Handle JSON field access: j.field -> json_get_field(j, "field")
        if type_name == "Json":
            # Create a string constant from the member name
            key_str = self._get_string_ptr(expr.member)
            # Call json_get_field
            return self.builder.call(self.json_get_field, [obj, key_str])

        # Handle known members for built-in types
        if expr.member == "width" or expr.member == "height":
            # Matrix dimensions
            return ir.Constant(ir.IntType(64), 0)

        return ir.Constant(ir.IntType(64), 0)

    def _get_tuple_field_info(self, expr: Expr) -> Optional[PyList[tuple]]:
        """Get field info for a tuple expression (name, type pairs)"""
        if isinstance(expr, Identifier):
            name = expr.name
            if name in self.locals:
                if name in self.tuple_field_info:
                    return self.tuple_field_info[name]
        return None
    
    def _get_lvalue_member(self, expr: MemberExpr) -> Optional[ir.Value]:
        """Get pointer to a member for assignment"""
        obj = self._generate_expression(expr.object)
        
        type_name = self._get_type_name_from_ptr(obj.type)
        
        if type_name and type_name in self.type_fields:
            field_idx = self._get_field_index(type_name, expr.member)
            if field_idx is not None:
                return self.builder.gep(obj, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), field_idx)
                ], inbounds=True)
        
        return None
    
    def _generate_index(self, expr: IndexExpr) -> ir.Value:
        """Generate code for index access: obj[idx] or obj[idx1, idx2]
        
        For user-defined types, this calls the .get() method.
        """
        # Special case: cell[dx, dy] is neighbor access in matrix formulas
        if isinstance(expr.object, CellExpr) and len(expr.indices) == 2:
            # Convert to CellIndexExpr and use that handler
            cell_idx = CellIndexExpr(expr.indices[0], expr.indices[1])
            return self._generate_cell_index_access(cell_idx)
        
        obj = self._generate_expression(expr.object)
        
        if not expr.indices:
            return ir.Constant(ir.IntType(64), 0)
        
        # Check if this is a user-defined type with a get method
        type_name = self._get_type_name_from_ptr(obj.type)
        if type_name and type_name in self.type_methods:
            method_map = self.type_methods[type_name]
            if "get" in method_map:
                mangled = method_map["get"]
                func = self.functions[mangled]
                
                # Build args: self first, then indices
                args = [obj]
                for i, idx_expr in enumerate(expr.indices):
                    idx_val = self._generate_expression(idx_expr)
                    # Cast to expected type (args[i+1] because args[0] is self)
                    if i + 1 < len(func.args):
                        expected = func.args[i + 1].type
                        idx_val = self._cast_value(idx_val, expected)
                    args.append(idx_val)
                
                result = self.builder.call(func, args)

                # Special handling for List.get and Array.get - returns i8* that needs dereferencing
                if type_name == "List" or type_name == "Array":
                    # Get element type from Coex type tracking
                    elem_llvm_type = ir.IntType(64)  # default
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in self.var_coex_types:
                            coex_type = self.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_llvm_type = self._get_llvm_type(coex_type.element_type)
                    typed_ptr = self.builder.bitcast(result, elem_llvm_type.as_pointer())
                    return self.builder.load(typed_ptr)

                return result

        index = self._generate_expression(expr.indices[0])

        # Check if this is an Array
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                # Array indexing - call array_get and load the value
                if index.type != ir.IntType(64):
                    index = self._cast_value(index, ir.IntType(64))

                elem_ptr = self.builder.call(self.array_get, [obj, index])

                # Get element type from Coex type tracking
                elem_llvm_type = ir.IntType(64)  # default
                if isinstance(expr.object, Identifier):
                    var_name = expr.object.name
                    if var_name in self.var_coex_types:
                        coex_type = self.var_coex_types[var_name]
                        if isinstance(coex_type, ArrayType):
                            elem_llvm_type = self._get_llvm_type(coex_type.element_type)

                typed_ptr = self.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
                return self.builder.load(typed_ptr)

        # Check if this is a List
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                # List indexing - call list_get and load the value
                # Ensure index is i64
                if index.type != ir.IntType(64):
                    index = self._cast_value(index, ir.IntType(64))

                elem_ptr = self.builder.call(self.list_get, [obj, index])

                # Get element type from Coex type tracking
                elem_llvm_type = ir.IntType(64)  # default
                if isinstance(expr.object, Identifier):
                    var_name = expr.object.name
                    if var_name in self.var_coex_types:
                        coex_type = self.var_coex_types[var_name]
                        if isinstance(coex_type, ListType):
                            elem_llvm_type = self._get_llvm_type(coex_type.element_type)

                typed_ptr = self.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
                return self.builder.load(typed_ptr)

            # JSON indexing: j["key"] or j[0]
            if hasattr(pointee, 'name') and pointee.name == "struct.Json":
                # Determine index type
                index_coex_type = self._infer_type_from_expr(expr.indices[0])
                if isinstance(index_coex_type, PrimitiveType) and index_coex_type.name == "string":
                    # String key: call json_get_field
                    return self.builder.call(self.json_get_field, [obj, index])
                else:
                    # Integer index: call json_get_index
                    if index.type != ir.IntType(64):
                        index = self._cast_value(index, ir.IntType(64))
                    return self.builder.call(self.json_get_index, [obj, index])

            # String indexing
            ptr = self.builder.gep(obj, [index])
            return self.builder.load(ptr)

        return ir.Constant(ir.IntType(64), 0)

    def _generate_slice(self, expr: SliceExpr) -> ir.Value:
        """Generate code for slice read: obj[start:end]

        Calls .getrange(start, end) on the object.
        Handles negative indices and omitted bounds.
        """
        obj = self._generate_expression(expr.object)
        i64 = ir.IntType(64)

        # Get collection length for bounds normalization
        length = self._get_collection_length(obj)

        # Normalize start
        if expr.start is None:
            start = ir.Constant(i64, 0)
        else:
            start = self._generate_expression(expr.start)
            start = self._cast_value(start, i64)
            start = self._normalize_slice_index(start, length)

        # Normalize end
        if expr.end is None:
            end = length
        else:
            end = self._generate_expression(expr.end)
            end = self._cast_value(end, i64)
            end = self._normalize_slice_index(end, length)

        # Call getrange method
        type_name = self._get_type_name_from_ptr(obj.type)
        if type_name and type_name in self.type_methods:
            method_map = self.type_methods[type_name]
            if "getrange" in method_map:
                mangled = method_map["getrange"]
                func = self.functions[mangled]
                return self.builder.call(func, [obj, start, end])

        # Fallback: check for direct list_getrange
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                return self.builder.call(self.list_getrange, [obj, start, end])
            elif hasattr(pointee, 'name') and pointee.name == "struct.String":
                return self.builder.call(self.string_getrange, [obj, start, end])

        raise RuntimeError(f"Type '{type_name}' does not support slice access (no getrange method)")

    def _normalize_slice_index(self, index: ir.Value, length: ir.Value) -> ir.Value:
        """Normalize a slice index, handling negative values.

        If index < 0, returns length + index (i.e., -1 becomes length-1).
        """
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        is_negative = self.builder.icmp_signed("<", index, zero)
        normalized = self.builder.add(length, index)

        return self.builder.select(is_negative, normalized, index)

    def _get_collection_length(self, obj: ir.Value) -> ir.Value:
        """Get the length of a collection for slice bounds normalization."""
        type_name = self._get_type_name_from_ptr(obj.type)

        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    return self.builder.call(self.list_len, [obj])
                elif pointee.name == "struct.String":
                    return self.builder.call(self.string_len, [obj])
                elif pointee.name == "struct.Array":
                    return self.builder.call(self.array_len, [obj])

        # Try type_methods lookup
        if type_name and type_name in self.type_methods:
            if "len" in self.type_methods[type_name]:
                mangled = self.type_methods[type_name]["len"]
                func = self.functions[mangled]
                return self.builder.call(func, [obj])

        return ir.Constant(ir.IntType(64), 0)

    def _generate_ternary(self, expr: TernaryExpr) -> ir.Value:
        """Generate code for ternary expression

        For ; variant (continuation): both branches merge, result is phi of both values
        For ! variant (exit): else branch returns from function, result is then value only
        """
        func = self.builder.function

        then_block = func.append_basic_block("tern_then")
        else_block = func.append_basic_block("tern_else")

        cond = self._generate_expression(expr.condition)
        cond = self._to_bool(cond)

        self.builder.cbranch(cond, then_block, else_block)

        self.builder.position_at_end(then_block)
        then_val = self._generate_expression(expr.then_expr)
        then_block = self.builder.block

        if expr.is_exit:
            # Exit variant: else branch returns, no merge needed
            merge_block = func.append_basic_block("tern_merge")
            self.builder.branch(merge_block)

            self.builder.position_at_end(else_block)
            else_val = self._generate_expression(expr.else_expr)

            # Cast else_val to function return type if needed
            ret_type = func.function_type.return_type
            else_val = self._cast_value(else_val, ret_type)

            # Pop GC frame before returning
            if self.gc_frame is not None and self.gc is not None:
                self.gc.pop_frame(self.builder, self.gc_frame)

            # Return from function
            self.builder.ret(else_val)

            # Continue in merge block with then_val
            self.builder.position_at_end(merge_block)
            return then_val
        else:
            # Continuation variant: both branches merge
            merge_block = func.append_basic_block("tern_merge")
            self.builder.branch(merge_block)

            self.builder.position_at_end(else_block)
            else_val = self._generate_expression(expr.else_expr)
            else_block = self.builder.block
            self.builder.branch(merge_block)

            self.builder.position_at_end(merge_block)

            # Ensure same type
            if then_val.type != else_val.type:
                if isinstance(then_val.type, ir.IntType) and isinstance(else_val.type, ir.IntType):
                    max_width = max(then_val.type.width, else_val.type.width)
                    target = ir.IntType(max_width)
                    then_val = self._cast_value(then_val, target)
                    else_val = self._cast_value(else_val, target)

            phi = self.builder.phi(then_val.type)
            phi.add_incoming(then_val, then_block)
            phi.add_incoming(else_val, else_block)

            return phi
    
    def _generate_list(self, expr: ListExpr) -> ir.Value:
        """Generate code for list literal: [1, 2, 3]"""
        if not expr.elements:
            # Empty list - default to i64 element size
            elem_size = ir.Constant(ir.IntType(64), 8)
            return self.builder.call(self.list_new, [elem_size])
        
        # Generate first element to determine type
        first_elem = self._generate_expression(expr.elements[0])
        elem_type = first_elem.type

        # Calculate element size (min 1 byte for sub-byte types like bool)
        if isinstance(elem_type, ir.IntType):
            size = max(1, elem_type.width // 8)
        elif isinstance(elem_type, ir.DoubleType):
            size = 8
        elif isinstance(elem_type, ir.PointerType):
            size = 8
        elif isinstance(elem_type, ir.LiteralStructType):
            # For tuples/structs, sum up element sizes
            size = sum(
                max(1, e.width // 8) if isinstance(e, ir.IntType) else 8
                for e in elem_type.elements
            )
        else:
            size = 8

        elem_size = ir.Constant(ir.IntType(64), size)
        
        # Create new list
        list_ptr = self.builder.call(self.list_new, [elem_size])
        
        # Append each element (list_append returns a new list with value semantics)
        for i, elem_expr in enumerate(expr.elements):
            if i == 0:
                elem_val = first_elem
            else:
                elem_val = self._generate_expression(elem_expr)

            # Store element to a temporary location
            temp = self.builder.alloca(elem_type, name=f"list_elem_{i}")
            self.builder.store(elem_val, temp)

            # Cast temp to i8*
            temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

            # Append - list_append returns a NEW list; update our reference
            list_ptr = self.builder.call(self.list_append, [list_ptr, temp_ptr, elem_size])

        return list_ptr
    
    def _generate_map(self, expr: MapExpr) -> ir.Value:
        """Generate code for map literal: {key: value, ...}"""
        i64 = ir.IntType(64)

        # Compute flags based on entry types
        flags = 0
        if expr.entries:
            key_expr, value_expr = expr.entries[0]
            key_type = self._infer_type_from_expr(key_expr)
            value_type = self._infer_type_from_expr(value_expr)
            flags = self._compute_map_flags(key_type, value_type)

        # Create empty map with flags
        map_ptr = self.builder.call(self.map_new, [ir.Constant(i64, flags)])

        # Add each entry (map_set returns a new map with value semantics)
        for key_expr, value_expr in expr.entries:
            key = self._generate_expression(key_expr)
            value = self._generate_expression(value_expr)

            # Check if key is a string pointer
            is_string_key = (isinstance(key.type, ir.PointerType) and
                            hasattr(key.type.pointee, 'name') and
                            key.type.pointee.name == "struct.String")

            if is_string_key:
                # Use string-aware map_set
                value_i64 = self._cast_value(value, ir.IntType(64))
                map_ptr = self.builder.call(self.map_set_string, [map_ptr, key, value_i64])
            else:
                # Cast to i64 for map storage
                key_i64 = self._cast_value(key, ir.IntType(64))
                value_i64 = self._cast_value(value, ir.IntType(64))
                # map_set returns a NEW map; update our reference
                map_ptr = self.builder.call(self.map_set, [map_ptr, key_i64, value_i64])

        return map_ptr

    def _generate_set(self, expr: SetExpr) -> ir.Value:
        """Generate code for set literal: {a, b, c}"""
        i64 = ir.IntType(64)

        # Compute flags based on element type
        flags = 0
        if expr.elements:
            elem_type = self._infer_type_from_expr(expr.elements[0])
            flags = self._compute_set_flags(elem_type)

        # Create empty set with flags
        set_ptr = self.builder.call(self.set_new, [ir.Constant(i64, flags)])

        # Add each element (set_add returns a new set with value semantics)
        for elem_expr in expr.elements:
            elem = self._generate_expression(elem_expr)

            # Check if element is a string
            is_string_elem = (isinstance(elem.type, ir.PointerType) and
                            hasattr(elem.type.pointee, 'name') and
                            elem.type.pointee.name == "struct.String")

            if is_string_elem:
                # Use string-aware set_add
                set_ptr = self.builder.call(self.set_add_string, [set_ptr, elem])
            else:
                # Cast to i64 for set storage
                elem_i64 = self._cast_value(elem, ir.IntType(64))
                # set_add returns a NEW set; update our reference
                set_ptr = self.builder.call(self.set_add, [set_ptr, elem_i64])

        return set_ptr

    def _generate_json_object(self, expr: JsonObjectExpr) -> ir.Value:
        """Generate code for JSON object literal: {name: "Alice", age: 30}

        Creates a Map<String, Json> internally, then wraps it in a Json object.
        """
        i64 = ir.IntType(64)

        if not expr.entries:
            # Empty JSON object: create empty map, wrap in json_new_object
            flags = self.MAP_FLAG_KEY_IS_PTR | self.MAP_FLAG_VALUE_IS_PTR  # String keys, Json values
            empty_map = self.builder.call(self.map_new, [ir.Constant(i64, flags)])
            return self.builder.call(self.json_new_object, [empty_map])

        # Create map with string keys and json values
        flags = self.MAP_FLAG_KEY_IS_PTR | self.MAP_FLAG_VALUE_IS_PTR
        map_ptr = self.builder.call(self.map_new, [ir.Constant(i64, flags)])

        # Add each entry
        for key_str, value_expr in expr.entries:
            # Generate the key as a string (it's already a literal string from parsing)
            key_string = self._get_string_ptr(key_str)

            # Generate the value expression
            value = self._generate_expression(value_expr)

            # Convert value to JSON if it isn't already
            json_value = self._convert_to_json(value, value_expr)

            # Cast json pointer to i64 for map storage
            json_i64 = self.builder.ptrtoint(json_value, i64)

            # Add to map using string-aware set
            map_ptr = self.builder.call(self.map_set_string, [map_ptr, key_string, json_i64])

        # Wrap the map in a Json object
        return self.builder.call(self.json_new_object, [map_ptr])

    def _convert_to_json(self, value: ir.Value, expr: Expr) -> ir.Value:
        """Convert a value to a Json* pointer based on its type."""
        # Handle NilLiteral first - before type checks since nil generates i64(0)
        if isinstance(expr, NilLiteral):
            return self.builder.call(self.json_new_null, [])

        # Check value type and call appropriate json_new_* constructor
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Boolean
                return self.builder.call(self.json_new_bool, [value])
            elif value.type.width == 64:
                # Integer
                return self.builder.call(self.json_new_int, [value])
            else:
                # Extend to i64 for JSON
                extended = self.builder.zext(value, ir.IntType(64))
                return self.builder.call(self.json_new_int, [extended])
        elif isinstance(value.type, ir.DoubleType):
            # Float
            return self.builder.call(self.json_new_float, [value])
        elif isinstance(value.type, ir.PointerType):
            if hasattr(value.type.pointee, 'name'):
                struct_name = value.type.pointee.name
                if struct_name == "struct.String":
                    # String
                    return self.builder.call(self.json_new_string, [value])
                elif struct_name == "struct.Json":
                    # Already JSON, return as-is
                    return value
                elif struct_name == "struct.List":
                    # List -> JSON array (need to convert elements to JSON)
                    return self._convert_list_to_json_array(value)
                elif struct_name == "struct.Map":
                    # Map -> JSON object
                    return self.builder.call(self.json_new_object, [value])
                else:
                    # Check for user-defined types and enums
                    type_name = struct_name.replace("struct.", "") if struct_name.startswith("struct.") else struct_name
                    return self._convert_udt_to_json(value, type_name)

        # Default: treat as int (may need extension for other types)
        if isinstance(value.type, ir.IntType):
            extended = self.builder.zext(value, ir.IntType(64)) if value.type.width < 64 else value
            return self.builder.call(self.json_new_int, [extended])

        # Fallback: create null JSON
        return self.builder.call(self.json_new_null, [])

    def _convert_list_to_json_array(self, list_ptr: ir.Value) -> ir.Value:
        """Convert a Coex list to a JSON array by converting each element to JSON.

        This creates a new list where each element is a Json* pointer, then wraps
        it in a JSON array.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get source list length and element size
        src_len = self.builder.call(self.list_len, [list_ptr])

        # Get the element size from the list struct (field 3)
        elem_size_ptr = self.builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        src_elem_size = self.builder.load(elem_size_ptr)

        # Create new list with 8-byte elements (for Json* pointers)
        json_list = self.builder.call(self.list_new, [ir.Constant(i64, 8)])

        # Store pointers for loop (allocate OUTSIDE loop to avoid stack overflow)
        json_list_ptr = self.builder.alloca(self.list_struct.as_pointer(), name="json_list_ptr")
        self.builder.store(json_list, json_list_ptr)
        idx_ptr = self.builder.alloca(i64, name="conv_idx")
        self.builder.store(ir.Constant(i64, 0), idx_ptr)
        temp = self.builder.alloca(i64, name="json_temp")  # Reused each iteration

        # Create loop blocks
        func = self.builder.function
        loop_cond = func.append_basic_block("list_conv_cond")
        loop_body = func.append_basic_block("list_conv_body")
        loop_done = func.append_basic_block("list_conv_done")

        self.builder.branch(loop_cond)

        # Loop condition
        self.builder.position_at_end(loop_cond)
        idx = self.builder.load(idx_ptr)
        cmp = self.builder.icmp_signed("<", idx, src_len)
        self.builder.cbranch(cmp, loop_body, loop_done)

        # Loop body: get element, convert to JSON, append
        self.builder.position_at_end(loop_body)
        elem_data_ptr = self.builder.call(self.list_get, [list_ptr, idx])

        # Determine conversion based on element size
        # For now, assume all elements are 8 bytes and could be int or pointer
        elem_i64_ptr = self.builder.bitcast(elem_data_ptr, i64.as_pointer())
        elem_i64 = self.builder.load(elem_i64_ptr)

        # Convert to JSON (treat as int for now - could be enhanced)
        json_elem = self.builder.call(self.json_new_int, [elem_i64])

        # Append to JSON list (reuse pre-allocated temp)
        json_i64 = self.builder.ptrtoint(json_elem, i64)
        self.builder.store(json_i64, temp)
        temp_i8 = self.builder.bitcast(temp, i8_ptr)

        curr_list = self.builder.load(json_list_ptr)
        new_list = self.builder.call(self.list_append, [curr_list, temp_i8, ir.Constant(i64, 8)])
        self.builder.store(new_list, json_list_ptr)

        # Increment and loop
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_ptr)
        self.builder.branch(loop_cond)

        # Done: create JSON array from the converted list
        self.builder.position_at_end(loop_done)
        final_list = self.builder.load(json_list_ptr)
        return self.builder.call(self.json_new_array, [final_list])

    def _convert_udt_to_json(self, value: ir.Value, type_name: str) -> ir.Value:
        """Convert a user-defined type or enum to JSON with _type metadata."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Check if it's an enum
        if type_name in self.enum_variants:
            return self._convert_enum_to_json(value, type_name)

        # Check if it's a user-defined struct
        if type_name in self.type_fields:
            return self._convert_struct_to_json(value, type_name)

        # Unknown type - return null JSON
        return self.builder.call(self.json_new_null, [])

    def _convert_struct_to_json(self, value: ir.Value, type_name: str) -> ir.Value:
        """Convert a user-defined struct to JSON object with _type field."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Create empty JSON object (starts with empty map)
        flags = ir.Constant(i64, 0x01)  # String keys
        map_ptr = self.builder.call(self.map_new, [flags])

        # Add _type field
        type_str = self._get_string_ptr(type_name)
        type_json = self.builder.call(self.json_new_string, [type_str])
        type_json_i64 = self.builder.ptrtoint(type_json, i64)
        type_key = self._get_string_ptr("_type")
        map_ptr = self.builder.call(self.map_set_string, [map_ptr, type_key, type_json_i64])

        # Add each field
        field_info = self.type_fields[type_name]
        for idx, (field_name, field_type) in enumerate(field_info):
            # Extract field value
            field_ptr = self.builder.gep(value, [ir.Constant(i32, 0), ir.Constant(i32, idx)], inbounds=True)
            field_val = self.builder.load(field_ptr)

            # Convert field value to JSON
            field_json = self._convert_field_to_json(field_val, field_type)

            # Add to map
            field_json_i64 = self.builder.ptrtoint(field_json, i64)
            field_key = self._get_string_ptr(field_name)
            map_ptr = self.builder.call(self.map_set_string, [map_ptr, field_key, field_json_i64])

        # Wrap map in JSON object
        return self.builder.call(self.json_new_object, [map_ptr])

    def _convert_enum_to_json(self, value: ir.Value, enum_name: str) -> ir.Value:
        """Convert an enum to JSON object with _type and _variant fields."""
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        func = self.builder.function

        # Get tag value (first field of enum struct)
        tag_ptr = self.builder.gep(value, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = self.builder.load(tag_ptr)

        # Create result alloca for PHI-like behavior
        result_ptr = self.builder.alloca(self.json_struct.as_pointer(), name="enum_json")

        # Build switch for each variant
        variants = self.enum_variants[enum_name]
        done_block = func.append_basic_block(f"enum_json_done")

        # Default block (shouldn't happen but needed for switch)
        default_block = func.append_basic_block(f"enum_json_default")

        # Create switch instruction
        switch = self.builder.switch(tag, default_block)

        for variant_name, (variant_tag, variant_fields) in variants.items():
            variant_block = func.append_basic_block(f"enum_json_{variant_name}")
            switch.add_case(ir.Constant(i64, variant_tag), variant_block)

            self.builder.position_at_end(variant_block)

            # Create JSON object for this variant
            flags = ir.Constant(i64, 0x01)  # String keys
            map_ptr = self.builder.call(self.map_new, [flags])

            # Add _type field
            type_str = self._get_string_ptr(enum_name)
            type_json = self.builder.call(self.json_new_string, [type_str])
            type_json_i64 = self.builder.ptrtoint(type_json, i64)
            type_key = self._get_string_ptr("_type")
            map_ptr = self.builder.call(self.map_set_string, [map_ptr, type_key, type_json_i64])

            # Add _variant field
            variant_str = self._get_string_ptr(variant_name)
            variant_json = self.builder.call(self.json_new_string, [variant_str])
            variant_json_i64 = self.builder.ptrtoint(variant_json, i64)
            variant_key = self._get_string_ptr("_variant")
            map_ptr = self.builder.call(self.map_set_string, [map_ptr, variant_key, variant_json_i64])

            # Add variant data fields (start at index 1, after tag)
            for field_idx, (field_name, field_type) in enumerate(variant_fields):
                field_ptr = self.builder.gep(value, [ir.Constant(i32, 0), ir.Constant(i32, field_idx + 1)], inbounds=True)
                field_val = self.builder.load(field_ptr)

                # Convert field value to JSON
                field_json = self._convert_field_to_json(field_val, field_type)

                # Add to map
                field_json_i64 = self.builder.ptrtoint(field_json, i64)
                field_key = self._get_string_ptr(field_name)
                map_ptr = self.builder.call(self.map_set_string, [map_ptr, field_key, field_json_i64])

            # Wrap map in JSON object
            json_obj = self.builder.call(self.json_new_object, [map_ptr])
            self.builder.store(json_obj, result_ptr)
            self.builder.branch(done_block)

        # Default block - create null JSON
        self.builder.position_at_end(default_block)
        null_json = self.builder.call(self.json_new_null, [])
        self.builder.store(null_json, result_ptr)
        self.builder.branch(done_block)

        # Done block - load and return result
        self.builder.position_at_end(done_block)
        return self.builder.load(result_ptr)

    def _convert_field_to_json(self, field_val: ir.Value, field_type: Type) -> ir.Value:
        """Convert a field value to JSON based on its Coex type."""
        i64 = ir.IntType(64)

        # Handle primitives
        if isinstance(field_type, PrimitiveType):
            if field_type.name == "int":
                if isinstance(field_val.type, ir.IntType) and field_val.type.width < 64:
                    field_val = self.builder.zext(field_val, i64)
                return self.builder.call(self.json_new_int, [field_val])
            elif field_type.name == "float":
                return self.builder.call(self.json_new_float, [field_val])
            elif field_type.name == "bool":
                return self.builder.call(self.json_new_bool, [field_val])
            elif field_type.name == "string":
                # field_val is i64 (pointer as int), convert back to pointer
                if isinstance(field_val.type, ir.IntType):
                    str_ptr = self.builder.inttoptr(field_val, self.string_struct.as_pointer())
                else:
                    str_ptr = field_val
                return self.builder.call(self.json_new_string, [str_ptr])

        # Handle collections
        if isinstance(field_type, ListType):
            if isinstance(field_val.type, ir.IntType):
                list_ptr = self.builder.inttoptr(field_val, self.list_struct.as_pointer())
            else:
                list_ptr = field_val
            return self.builder.call(self.json_new_array, [list_ptr])

        if isinstance(field_type, MapType):
            if isinstance(field_val.type, ir.IntType):
                map_ptr = self.builder.inttoptr(field_val, self.map_struct.as_pointer())
            else:
                map_ptr = field_val
            return self.builder.call(self.json_new_object, [map_ptr])

        # Handle user-defined types
        if isinstance(field_type, NamedType):
            if isinstance(field_val.type, ir.IntType):
                udt_ptr = self.builder.inttoptr(field_val, self.type_registry[field_type.name].as_pointer())
            else:
                udt_ptr = field_val
            return self._convert_udt_to_json(udt_ptr, field_type.name)

        # Fallback - treat as int
        if isinstance(field_val.type, ir.IntType):
            if field_val.type.width < 64:
                field_val = self.builder.zext(field_val, i64)
            return self.builder.call(self.json_new_int, [field_val])

        return self.builder.call(self.json_new_null, [])

    def _generate_as_expr(self, expr: AsExpr) -> ir.Value:
        """Generate code for type cast expression: expr as Type or expr as Type?"""
        i1 = ir.IntType(1)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        func = self.builder.function

        # Generate the source expression
        source = self._generate_expression(expr.expr)
        target_type = expr.target_type

        # Handle OptionalType wrapper - get the inner type
        if isinstance(target_type, OptionalType):
            inner_type = target_type.inner_type
        else:
            inner_type = target_type

        # If source is not JSON, we need special handling
        if not (isinstance(source.type, ir.PointerType) and
                hasattr(source.type.pointee, 'name') and
                source.type.pointee.name == "struct.Json"):
            # Source is not JSON - handle other conversions
            return self._generate_non_json_as_expr(source, expr)

        # JSON → Coex conversion
        # Get the JSON tag
        tag_ptr = self.builder.gep(source, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = self.builder.load(tag_ptr)
        value_ptr = self.builder.gep(source, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value = self.builder.load(value_ptr)

        # Handle JSON → string: extract string if JSON is string type, else serialize
        if isinstance(inner_type, PrimitiveType) and inner_type.name == "string":
            # Check if JSON is a string type - if so, extract; otherwise serialize
            is_str_type = self.builder.icmp_unsigned("==", tag, ir.Constant(ir.IntType(8), self._json.JSON_TAG_STRING))

            func = self.builder.function
            extract_block = func.append_basic_block("json_extract_str")
            serialize_block = func.append_basic_block("json_serialize_str")
            done_block = func.append_basic_block("json_str_done")

            self.builder.cbranch(is_str_type, extract_block, serialize_block)

            # Extract the string directly
            self.builder.position_at_end(extract_block)
            extracted = self.builder.inttoptr(value, self.string_struct.as_pointer())
            self.builder.branch(done_block)

            # Serialize to JSON string
            self.builder.position_at_end(serialize_block)
            serialized = self.builder.call(self.json_stringify, [source])
            self.builder.branch(done_block)

            # Merge results
            self.builder.position_at_end(done_block)
            result = self.builder.phi(self.string_struct.as_pointer(), "str_result")
            result.add_incoming(extracted, extract_block)
            result.add_incoming(serialized, serialize_block)
            return result

        # Handle primitive target types (extraction)
        if isinstance(inner_type, PrimitiveType):
            return self._generate_json_to_primitive(source, tag, value, inner_type, expr.is_optional)

        # Handle user-defined types
        if isinstance(inner_type, NamedType):
            if inner_type.name in self.type_fields:
                return self._generate_json_to_struct(source, tag, value, inner_type, expr.is_optional)
            if inner_type.name in self.enum_variants:
                return self._generate_json_to_enum(source, tag, value, inner_type, expr.is_optional)

        # Handle List type
        if isinstance(inner_type, ListType):
            return self._generate_json_to_list(source, tag, value, inner_type, expr.is_optional)

        # Fallback - return 0/nil
        if expr.is_optional:
            return ir.Constant(i64, 0)
        return ir.Constant(i64, 0)

    def _generate_non_json_as_expr(self, source: ir.Value, expr: AsExpr) -> ir.Value:
        """Handle non-JSON type conversions (e.g., int as string, string as json)."""
        i64 = ir.IntType(64)
        target_type = expr.target_type

        if isinstance(target_type, OptionalType):
            inner_type = target_type.inner_type
        else:
            inner_type = target_type

        # string → json (parsing)
        if isinstance(inner_type, PrimitiveType) and inner_type.name == "json":
            # Check if source is a string
            if (isinstance(source.type, ir.PointerType) and
                hasattr(source.type.pointee, 'name') and
                source.type.pointee.name == "struct.String"):
                # Parse the string as JSON
                return self.builder.call(self.json_parse, [source])
            # Other types → json (implicit conversion)
            return self._convert_to_json(source, expr.expr)

        # For other conversions, just return the value (type checking should catch errors)
        return source

    def _generate_json_to_primitive(self, json_ptr: ir.Value, tag: ir.Value, value: ir.Value,
                                     target_type: PrimitiveType, is_optional: bool) -> ir.Value:
        """Convert JSON to a primitive type."""
        i1 = ir.IntType(1)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        func = self.builder.function

        # Determine expected tag
        # JSON tags: 0=null, 1=bool, 2=int, 3=float, 4=string, 5=array, 6=object
        if target_type.name == "bool":
            expected_tag = 1
            result_type = i1
        elif target_type.name == "int":
            expected_tag = 2
            result_type = i64
        elif target_type.name == "float":
            expected_tag = 3
            result_type = ir.DoubleType()
        elif target_type.name == "string":
            expected_tag = 4
            result_type = self.string_struct.as_pointer()
        else:
            # Unknown primitive - return 0
            return ir.Constant(i64, 0)

        # Check tag matches
        tag_matches = self.builder.icmp_unsigned("==", tag, ir.Constant(i8, expected_tag))

        # Create blocks
        match_block = func.append_basic_block("as_match")
        fail_block = func.append_basic_block("as_fail")
        done_block = func.append_basic_block("as_done")

        # Allocate result
        if is_optional:
            # Optional returns i64 (0 for nil)
            result_ptr = self.builder.alloca(i64, name="as_result")
        else:
            result_ptr = self.builder.alloca(result_type, name="as_result")

        self.builder.cbranch(tag_matches, match_block, fail_block)

        # Match block - extract value
        self.builder.position_at_end(match_block)
        if target_type.name == "bool":
            extracted = self.builder.trunc(value, i1)
            if is_optional:
                # Store as i64 for optional (1 = Some(false), 2 = Some(true))
                extended = self.builder.zext(extracted, i64)
                # Add 1 so 0 can mean None
                result = self.builder.add(extended, ir.Constant(i64, 1))
                self.builder.store(result, result_ptr)
            else:
                self.builder.store(extracted, result_ptr)
        elif target_type.name == "int":
            if is_optional:
                # For optional int, we need a sentinel. Use a tagged representation.
                # Store value + 1, with 0 meaning None
                # This limits range but works for most cases
                result = self.builder.add(value, ir.Constant(i64, 1))
                self.builder.store(result, result_ptr)
            else:
                self.builder.store(value, result_ptr)
        elif target_type.name == "float":
            # value is i64 - bitcast to double
            extracted = self.builder.bitcast(value, ir.DoubleType())
            if is_optional:
                # Store as i64
                self.builder.store(value, result_ptr)
            else:
                self.builder.store(extracted, result_ptr)
        elif target_type.name == "string":
            str_ptr = self.builder.inttoptr(value, self.string_struct.as_pointer())
            if is_optional:
                self.builder.store(value, result_ptr)
            else:
                # Store the actual String* pointer
                self.builder.store(str_ptr, result_ptr)
        self.builder.branch(done_block)

        # Fail block
        self.builder.position_at_end(fail_block)
        if is_optional:
            self.builder.store(ir.Constant(i64, 0), result_ptr)
            self.builder.branch(done_block)
        else:
            # Panic - type mismatch
            # For now, just store 0 and continue
            if result_type == i1:
                self.builder.store(ir.Constant(i1, 0), result_ptr)
            elif result_type == i64:
                self.builder.store(ir.Constant(i64, 0), result_ptr)
            elif isinstance(result_type, ir.DoubleType):
                self.builder.store(ir.Constant(ir.DoubleType(), 0.0), result_ptr)
            else:
                # Pointer type
                null_ptr = self.builder.inttoptr(ir.Constant(i64, 0), result_type)
                self.builder.store(null_ptr, result_ptr)
            self.builder.branch(done_block)

        # Done block
        self.builder.position_at_end(done_block)
        return self.builder.load(result_ptr)

    def _generate_json_to_struct(self, json_ptr: ir.Value, tag: ir.Value, value: ir.Value,
                                  target_type: NamedType, is_optional: bool) -> ir.Value:
        """Convert JSON object to user-defined struct."""
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        func = self.builder.function
        type_name = target_type.name

        # Check it's an object (tag == 6)
        is_object = self.builder.icmp_unsigned("==", tag, ir.Constant(i8, 6))

        match_block = func.append_basic_block("as_struct_match")
        fail_block = func.append_basic_block("as_struct_fail")
        done_block = func.append_basic_block("as_struct_done")

        struct_type = self.type_registry[type_name]
        result_ptr = self.builder.alloca(struct_type.as_pointer(), name="as_struct_result")

        self.builder.cbranch(is_object, match_block, fail_block)

        # Match block - extract fields
        self.builder.position_at_end(match_block)

        # Get the map from the JSON object
        map_ptr = self.builder.inttoptr(value, self.map_struct.as_pointer())

        # Allocate struct via GC
        struct_size = ir.Constant(i64, len(self.type_fields[type_name]) * 8)
        type_id = ir.Constant(i32, self.gc.get_type_id(type_name))
        raw_ptr = self.gc.alloc_with_deref(self.builder, struct_size, type_id)
        struct_ptr = self.builder.bitcast(raw_ptr, struct_type.as_pointer())

        # Extract each field
        field_info = self.type_fields[type_name]
        for idx, (field_name, field_type) in enumerate(field_info):
            # Skip _type field
            if field_name == "_type":
                continue

            # Get field from map
            field_key = self._get_string_ptr(field_name)
            field_json_i64 = self.builder.call(self.map_get_string, [map_ptr, field_key])

            # Convert from JSON
            field_json = self.builder.inttoptr(field_json_i64, self.json_struct.as_pointer())
            field_val = self._extract_json_value(field_json, field_type)

            # Store in struct
            field_ptr = self.builder.gep(struct_ptr, [ir.Constant(i32, 0), ir.Constant(i32, idx)], inbounds=True)
            self.builder.store(field_val, field_ptr)

        if is_optional:
            struct_i64 = self.builder.ptrtoint(struct_ptr, i64)
            self.builder.store(self.builder.inttoptr(struct_i64, struct_type.as_pointer()), result_ptr)
        else:
            self.builder.store(struct_ptr, result_ptr)
        self.builder.branch(done_block)

        # Fail block
        self.builder.position_at_end(fail_block)
        null_ptr = self.builder.inttoptr(ir.Constant(i64, 0), struct_type.as_pointer())
        self.builder.store(null_ptr, result_ptr)
        self.builder.branch(done_block)

        # Done block
        self.builder.position_at_end(done_block)
        return self.builder.load(result_ptr)

    def _generate_json_to_enum(self, json_ptr: ir.Value, tag: ir.Value, value: ir.Value,
                                target_type: NamedType, is_optional: bool) -> ir.Value:
        """Convert JSON object to enum."""
        # Similar to struct but also checks _variant field
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)

        # For now, return a simple placeholder
        # Full enum conversion requires matching variant names
        if is_optional:
            return ir.Constant(i64, 0)
        return ir.Constant(i64, 0)

    def _generate_json_to_list(self, json_ptr: ir.Value, tag: ir.Value, value: ir.Value,
                                target_type: ListType, is_optional: bool) -> ir.Value:
        """Convert JSON array to List."""
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)
        func = self.builder.function

        # Check it's an array (tag == 5)
        is_array = self.builder.icmp_unsigned("==", tag, ir.Constant(i8, 5))

        match_block = func.append_basic_block("as_list_match")
        fail_block = func.append_basic_block("as_list_fail")
        done_block = func.append_basic_block("as_list_done")

        result_ptr = self.builder.alloca(self.list_struct.as_pointer(), name="as_list_result")

        self.builder.cbranch(is_array, match_block, fail_block)

        # Match block - the value is already a List*
        self.builder.position_at_end(match_block)
        list_ptr = self.builder.inttoptr(value, self.list_struct.as_pointer())
        self.builder.store(list_ptr, result_ptr)
        self.builder.branch(done_block)

        # Fail block
        self.builder.position_at_end(fail_block)
        null_ptr = self.builder.inttoptr(ir.Constant(i64, 0), self.list_struct.as_pointer())
        self.builder.store(null_ptr, result_ptr)
        self.builder.branch(done_block)

        # Done block
        self.builder.position_at_end(done_block)
        return self.builder.load(result_ptr)

    def _extract_json_value(self, json_ptr: ir.Value, target_type: Type) -> ir.Value:
        """Extract a value from a JSON pointer, converting to the target type."""
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag and value
        tag_ptr = self.builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = self.builder.load(tag_ptr)
        value_ptr = self.builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value = self.builder.load(value_ptr)

        if isinstance(target_type, PrimitiveType):
            if target_type.name == "int":
                return value
            elif target_type.name == "float":
                return self.builder.bitcast(value, ir.DoubleType())
            elif target_type.name == "bool":
                return self.builder.trunc(value, ir.IntType(1))
            elif target_type.name == "string":
                return self.builder.inttoptr(value, self.string_struct.as_pointer())

        # For complex types, return the raw value as i64
        return value

    def _generate_list_comprehension(self, expr: ListComprehension) -> ir.Value:
        """Generate code for list comprehension via desugaring.

        [f(x) for x in data if p(x)]

        Desugars to:
        __result = []
        for x in data
          if p(x)
            __result.append(f(x))
          ~
        ~
        __result
        """
        # Create result list
        elem_size = ir.Constant(ir.IntType(64), 8)
        list_ptr = self.builder.call(self.list_new, [elem_size])

        # Store result list in a temporary
        result_var = f"__comp_result_{self.lambda_counter}"
        self.lambda_counter += 1
        result_alloca = self.builder.alloca(self.list_struct.as_pointer(), name=result_var)
        self.builder.store(list_ptr, result_alloca)

        # Pre-allocate temp storage OUTSIDE loop to avoid stack overflow
        self._comp_temp_alloca = self.builder.alloca(ir.IntType(64), name="comp_temp")

        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "list")

        # Clear the temp alloca reference
        self._comp_temp_alloca = None

        # Return the result list
        return self.builder.load(result_alloca)
    
    def _generate_set_comprehension(self, expr: SetComprehension) -> ir.Value:
        """Generate code for set comprehension using proper Set type."""
        i64 = ir.IntType(64)

        # Infer element type from the body expression and compute flags
        elem_type = self._infer_type_from_expr(expr.body)
        flags = self._compute_set_flags(elem_type)

        # Create result set with appropriate flags
        set_ptr = self.builder.call(self.set_new, [ir.Constant(i64, flags)])

        result_var = f"__comp_result_{self.lambda_counter}"
        self.lambda_counter += 1
        result_alloca = self.builder.alloca(self.set_struct.as_pointer(), name=result_var)
        self.builder.store(set_ptr, result_alloca)

        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "set")

        return self.builder.load(result_alloca)
    
    def _generate_map_comprehension(self, expr: MapComprehension) -> ir.Value:
        """Generate code for map comprehension."""
        i64 = ir.IntType(64)

        # Compute flags based on key/value types
        key_type = self._infer_type_from_expr(expr.key)
        value_type = self._infer_type_from_expr(expr.value)
        flags = self._compute_map_flags(key_type, value_type)

        # Create result map with flags
        map_ptr = self.builder.call(self.map_new, [ir.Constant(i64, flags)])

        result_var = f"__comp_result_{self.lambda_counter}"
        self.lambda_counter += 1
        result_alloca = self.builder.alloca(self.map_struct.as_pointer(), name=result_var)
        self.builder.store(map_ptr, result_alloca)
        
        # Generate the nested loop structure with key-value pair
        self._generate_comprehension_loop(expr.clauses, 0, (expr.key, expr.value), result_alloca, "map")
        
        return self.builder.load(result_alloca)
    
    def _generate_comprehension_loop(self, clauses, clause_idx, body, result_alloca, comp_type):
        """Generate nested loop structure for comprehension clauses.
        
        Recursively generates:
        for pattern in iterable
          if condition (optional)
            [next clause or body]
          ~
        ~
        """
        if clause_idx >= len(clauses):
            # Base case: generate body and append to result
            self._generate_comprehension_body(body, result_alloca, comp_type)
            return
        
        clause = clauses[clause_idx]
        func = self.builder.function
        
        # Check if iterable is a range() call
        if isinstance(clause.iterable, CallExpr) and isinstance(clause.iterable.callee, Identifier) and clause.iterable.callee.name == "range":
            self._generate_comprehension_range_loop(clause, clause_idx, clauses, body, result_alloca, comp_type)
            return
        
        # Check if iterable is a RangeExpr (start..end syntax)
        if isinstance(clause.iterable, RangeExpr):
            self._generate_comprehension_range_expr_loop(clause, clause_idx, clauses, body, result_alloca, comp_type)
            return
        
        # Get the iterable
        iterable = self._generate_expression(clause.iterable)
        
        # Check if it's a List
        if isinstance(iterable.type, ir.PointerType) and hasattr(iterable.type.pointee, 'name') and iterable.type.pointee.name == "struct.List":
            # Generate list iteration
            length = self.builder.call(self.list_len, [iterable])
            
            # Loop counter
            idx_alloca = self.builder.alloca(ir.IntType(64), name=f"__idx_{clause_idx}")
            self.builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)
            
            # Loop blocks
            loop_cond = func.append_basic_block(f"comp_loop_cond_{clause_idx}")
            loop_body = func.append_basic_block(f"comp_loop_body_{clause_idx}")
            loop_end = func.append_basic_block(f"comp_loop_end_{clause_idx}")
            
            self.builder.branch(loop_cond)
            
            # Condition: idx < length
            self.builder.position_at_end(loop_cond)
            idx = self.builder.load(idx_alloca)
            cond = self.builder.icmp_signed("<", idx, length)
            self.builder.cbranch(cond, loop_body, loop_end)
            
            # Body
            self.builder.position_at_end(loop_body)
            
            # Reload idx in this block
            idx = self.builder.load(idx_alloca)
            
            # Get element and bind to pattern
            elem_ptr = self.builder.call(self.list_get, [iterable, idx])
            elem_ptr_cast = self.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
            elem_val = self.builder.load(elem_ptr_cast)
            
            # Bind pattern variables
            self._bind_pattern(clause.pattern, elem_val)
            
            # Check condition if present
            if clause.condition:
                cond_val = self._generate_expression(clause.condition)
                cond_bool = self._to_bool(cond_val)
                
                then_block = func.append_basic_block(f"comp_then_{clause_idx}")
                after_block = func.append_basic_block(f"comp_after_{clause_idx}")
                
                self.builder.cbranch(cond_bool, then_block, after_block)
                
                self.builder.position_at_end(then_block)
                self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
                if not self.builder.block.is_terminated:
                    self.builder.branch(after_block)
                
                self.builder.position_at_end(after_block)
            else:
                self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
            
            # Increment counter
            if not self.builder.block.is_terminated:
                idx = self.builder.load(idx_alloca)
                next_idx = self.builder.add(idx, ir.Constant(ir.IntType(64), 1))
                self.builder.store(next_idx, idx_alloca)
                self.builder.branch(loop_cond)
            
            self.builder.position_at_end(loop_end)
        else:
            # Unknown iterable type - skip for now
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
    
    def _generate_comprehension_range_loop(self, clause, clause_idx, clauses, body, result_alloca, comp_type):
        """Generate comprehension loop for range() iteration."""
        func = self.builder.function
        args = clause.iterable.args
        
        # Parse range args: range(end) or range(start, end)
        if len(args) == 1:
            start = ir.Constant(ir.IntType(64), 0)
            end = self._generate_expression(args[0])
        elif len(args) >= 2:
            start = self._generate_expression(args[0])
            end = self._generate_expression(args[1])
        else:
            return
        
        # Ensure i64
        if start.type != ir.IntType(64):
            start = self._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = self._cast_value(end, ir.IntType(64))
        
        # Get variable name from pattern
        if isinstance(clause.pattern, IdentifierPattern):
            var_name = clause.pattern.name
        elif isinstance(clause.pattern, str):
            var_name = clause.pattern
        else:
            var_name = f"__range_var_{clause_idx}"
        
        # Allocate loop variable
        loop_var = self.builder.alloca(ir.IntType(64), name=var_name)
        self.builder.store(start, loop_var)
        self.locals[var_name] = loop_var
        
        # Loop blocks
        loop_cond = func.append_basic_block(f"comp_range_cond_{clause_idx}")
        loop_body = func.append_basic_block(f"comp_range_body_{clause_idx}")
        loop_end = func.append_basic_block(f"comp_range_end_{clause_idx}")
        
        self.builder.branch(loop_cond)
        
        # Condition: i < end
        self.builder.position_at_end(loop_cond)
        current = self.builder.load(loop_var)
        cond = self.builder.icmp_signed("<", current, end)
        self.builder.cbranch(cond, loop_body, loop_end)
        
        # Body
        self.builder.position_at_end(loop_body)
        
        # Check condition if present
        if clause.condition:
            cond_val = self._generate_expression(clause.condition)
            cond_bool = self._to_bool(cond_val)
            
            then_block = func.append_basic_block(f"comp_range_then_{clause_idx}")
            after_block = func.append_basic_block(f"comp_range_after_{clause_idx}")
            
            self.builder.cbranch(cond_bool, then_block, after_block)
            
            self.builder.position_at_end(then_block)
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
            if not self.builder.block.is_terminated:
                self.builder.branch(after_block)
            
            self.builder.position_at_end(after_block)
        else:
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
        
        # Increment
        if not self.builder.block.is_terminated:
            current = self.builder.load(loop_var)
            next_val = self.builder.add(current, ir.Constant(ir.IntType(64), 1))
            self.builder.store(next_val, loop_var)
            self.builder.branch(loop_cond)
        
        self.builder.position_at_end(loop_end)
    
    def _generate_comprehension_range_expr_loop(self, clause, clause_idx, clauses, body, result_alloca, comp_type):
        """Generate comprehension loop for start..end range expression."""
        func = self.builder.function
        range_expr = clause.iterable
        
        start = self._generate_expression(range_expr.start)
        end = self._generate_expression(range_expr.end)
        
        # Ensure i64
        if start.type != ir.IntType(64):
            start = self._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = self._cast_value(end, ir.IntType(64))
        
        # Get variable name from pattern
        if isinstance(clause.pattern, IdentifierPattern):
            var_name = clause.pattern.name
        elif isinstance(clause.pattern, str):
            var_name = clause.pattern
        else:
            var_name = f"__range_var_{clause_idx}"
        
        # Allocate loop variable
        loop_var = self.builder.alloca(ir.IntType(64), name=var_name)
        self.builder.store(start, loop_var)
        self.locals[var_name] = loop_var
        
        # Loop blocks
        loop_cond = func.append_basic_block(f"comp_rexpr_cond_{clause_idx}")
        loop_body = func.append_basic_block(f"comp_rexpr_body_{clause_idx}")
        loop_end = func.append_basic_block(f"comp_rexpr_end_{clause_idx}")
        
        self.builder.branch(loop_cond)
        
        # Condition: i < end
        self.builder.position_at_end(loop_cond)
        current = self.builder.load(loop_var)
        cond = self.builder.icmp_signed("<", current, end)
        self.builder.cbranch(cond, loop_body, loop_end)
        
        # Body
        self.builder.position_at_end(loop_body)
        
        # Check condition if present
        if clause.condition:
            cond_val = self._generate_expression(clause.condition)
            cond_bool = self._to_bool(cond_val)
            
            then_block = func.append_basic_block(f"comp_rexpr_then_{clause_idx}")
            after_block = func.append_basic_block(f"comp_rexpr_after_{clause_idx}")
            
            self.builder.cbranch(cond_bool, then_block, after_block)
            
            self.builder.position_at_end(then_block)
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
            if not self.builder.block.is_terminated:
                self.builder.branch(after_block)
            
            self.builder.position_at_end(after_block)
        else:
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
        
        # Increment
        if not self.builder.block.is_terminated:
            current = self.builder.load(loop_var)
            next_val = self.builder.add(current, ir.Constant(ir.IntType(64), 1))
            self.builder.store(next_val, loop_var)
            self.builder.branch(loop_cond)
        
        self.builder.position_at_end(loop_end)
    
    def _generate_comprehension_body(self, body, result_alloca, comp_type):
        """Generate the body expression and append to result."""
        if comp_type == "list":
            # Evaluate body expression
            val = self._generate_expression(body)

            # Reuse pre-allocated temp from _generate_list_comprehension to avoid stack overflow
            temp = self._comp_temp_alloca
            stored_val = self._cast_value(val, ir.IntType(64))
            self.builder.store(stored_val, temp)
            temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

            result_list = self.builder.load(result_alloca)
            elem_size = ir.Constant(ir.IntType(64), 8)
            # list_append returns a NEW list (value semantics); store it back
            new_list = self.builder.call(self.list_append, [result_list, temp_ptr, elem_size])
            self.builder.store(new_list, result_alloca)

        elif comp_type == "set":
            # Evaluate body expression and add to set
            key = self._generate_expression(body)
            key_i64 = self._cast_value(key, ir.IntType(64))

            result_set = self.builder.load(result_alloca)
            # set_add returns a NEW set (value semantics); store it back
            new_set = self.builder.call(self.set_add, [result_set, key_i64])
            self.builder.store(new_set, result_alloca)

        elif comp_type == "map":
            # body is (key_expr, value_expr)
            key_expr, value_expr = body
            key = self._generate_expression(key_expr)
            value = self._generate_expression(value_expr)

            key_i64 = self._cast_value(key, ir.IntType(64))
            value_i64 = self._cast_value(value, ir.IntType(64))

            result_map = self.builder.load(result_alloca)
            # map_set returns a NEW map (value semantics); store it back
            new_map = self.builder.call(self.map_set, [result_map, key_i64, value_i64])
            self.builder.store(new_map, result_alloca)
    
    def _bind_pattern(self, pattern, value):
        """Bind pattern variables to a value."""
        if isinstance(pattern, str):
            # Simple string pattern (backward compat)
            alloca = self.builder.alloca(value.type, name=pattern)
            self.builder.store(value, alloca)
            self.locals[pattern] = alloca
            
        elif isinstance(pattern, IdentifierPattern):
            alloca = self.builder.alloca(value.type, name=pattern.name)
            self.builder.store(value, alloca)
            self.locals[pattern.name] = alloca
            
        elif isinstance(pattern, WildcardPattern):
            # Wildcard - don't bind anything
            pass
            
        elif isinstance(pattern, TuplePattern):
            # Destructure tuple
            # Assume value is a tuple struct or can be indexed
            for i, elem_pattern in enumerate(pattern.elements):
                if isinstance(value.type, ir.LiteralStructType):
                    elem_val = self.builder.extract_value(value, i)
                else:
                    # For i64, treat high/low bits as elements (simplified)
                    elem_val = value
                self._bind_pattern(elem_pattern, elem_val)
    

    def _infer_list_element_type(self, expr) -> Optional[ir.Type]:
        """Infer the element type of a list expression."""
        if isinstance(expr, ListExpr) and expr.elements:
            # Generate first element to get its type
            # But we need to be careful - we may have already generated it
            first = expr.elements[0]
            if isinstance(first, TupleExpr):
                # Build tuple type from elements
                elem_types = []
                for _, elem in first.elements:
                    if isinstance(elem, IntLiteral):
                        elem_types.append(ir.IntType(64))
                    elif isinstance(elem, FloatLiteral):
                        elem_types.append(ir.DoubleType())
                    elif isinstance(elem, BoolLiteral):
                        elem_types.append(ir.IntType(1))
                    else:
                        elem_types.append(ir.IntType(64))
                return ir.LiteralStructType(elem_types)
            elif isinstance(first, IntLiteral):
                return ir.IntType(64)
            elif isinstance(first, FloatLiteral):
                return ir.DoubleType()
        return None
    
    def _get_list_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for list elements based on pattern and tracked info."""
        # First try to look up tracked element type
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in self.list_element_types:
                return self.list_element_types[var_name]
            # Also check var_coex_types for List element type
            if var_name in self.var_coex_types:
                coex_type = self.var_coex_types[var_name]
                if isinstance(coex_type, ListType):
                    return self._get_llvm_type(coex_type.element_type)

        # Handle method call iterables (e.g., text.split("\n"))
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "split":
                # split() returns List<String>
                return self.string_struct.as_pointer()
        elif isinstance(stmt.iterable, CallExpr):
            # CallExpr with MemberExpr callee (e.g., text.split("\n"))
            if isinstance(stmt.iterable.callee, MemberExpr):
                if stmt.iterable.callee.member == "split":
                    return self.string_struct.as_pointer()

        # Infer from pattern structure
        pattern = stmt.pattern
        if isinstance(pattern, TuplePattern):
            # For tuple patterns, assume i64 for each element
            elem_types = [ir.IntType(64) for _ in pattern.elements]
            return ir.LiteralStructType(elem_types)

        # Default to i64
        return ir.IntType(64)

    def _get_list_element_coex_type(self, stmt: ForStmt) -> Optional[Type]:
        """Get the Coex AST type for list elements (for var_coex_types tracking)."""
        # Check iterable identifier in var_coex_types
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in self.var_coex_types:
                coex_type = self.var_coex_types[var_name]
                if isinstance(coex_type, ListType):
                    return coex_type.element_type

        # Handle method call iterables (e.g., text.split("\n"))
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "split":
                return PrimitiveType("string")
        elif isinstance(stmt.iterable, CallExpr):
            # CallExpr with MemberExpr callee (e.g., text.split("\n"))
            if isinstance(stmt.iterable.callee, MemberExpr):
                if stmt.iterable.callee.member == "split":
                    return PrimitiveType("string")

        return None

    def _get_array_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for array elements based on pattern and tracked info."""
        # First try to look up tracked element type
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in self.array_element_types:
                return self.array_element_types[var_name]

        # If iterable is a method call like list.packed(), try to get list's element type
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "packed" and isinstance(stmt.iterable.object, Identifier):
                list_var = stmt.iterable.object.name
                if list_var in self.list_element_types:
                    return self.list_element_types[list_var]

        # Infer from pattern structure
        pattern = stmt.pattern
        if isinstance(pattern, TuplePattern):
            # For tuple patterns, assume i64 for each element
            elem_types = [ir.IntType(64) for _ in pattern.elements]
            return ir.LiteralStructType(elem_types)

        # Default to i64
        return ir.IntType(64)

    def _generate_tuple(self, expr: TupleExpr) -> ir.Value:
        """Generate code for tuple literal"""
        if not expr.elements:
            return ir.Constant(ir.IntType(64), 0)
        
        # Generate each element
        values = []
        types = []
        for _, elem_expr in expr.elements:
            val = self._generate_expression(elem_expr)
            values.append(val)
            types.append(val.type)
        
        # Create struct type
        tuple_type = ir.LiteralStructType(types)
        
        # Allocate and store
        alloca = self.builder.alloca(tuple_type)
        for i, val in enumerate(values):
            ptr = self.builder.gep(alloca, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            self.builder.store(val, ptr)
        
        return self.builder.load(alloca)
    
    def _generate_range(self, expr: RangeExpr) -> ir.Value:
        """Generate code for range expression"""
        # Range as expression - return struct or iterator
        # For now just return start value
        return self._generate_expression(expr.start)
    
    def _generate_lambda(self, expr: LambdaExpr) -> ir.Value:
        """Generate code for lambda expression
        
        Creates an anonymous function and returns a pointer to it.
        """
        # Generate unique name for this lambda
        lambda_name = f"__lambda_{self.lambda_counter}"
        self.lambda_counter += 1
        
        # Determine return type from body expression
        # First, figure out parameter types
        param_types = []
        for param in expr.params:
            param_type = self._get_llvm_type(param.type_annotation)
            param_types.append(param_type)
        
        # Save current state
        saved_builder = self.builder
        saved_locals = self.locals.copy()
        saved_function = self.current_function
        
        # Create function with i64 return (most common, will adjust if needed)
        ret_type = ir.IntType(64)
        
        func_type = ir.FunctionType(ret_type, param_types)
        func = ir.Function(self.module, func_type, name=lambda_name)
        
        # Create entry block
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        self.locals = {}
        self._reset_function_scope()

        # Bind parameters
        for i, (param, llvm_param) in enumerate(zip(expr.params, func.args)):
            llvm_param.name = param.name
            alloca = self.builder.alloca(param_types[i], name=param.name)
            self.builder.store(llvm_param, alloca)
            self.locals[param.name] = alloca

        # Generate body expression
        result = self._generate_expression(expr.body)
        
        # Determine actual return type
        actual_ret_type = result.type
        
        # If return type doesn't match, recreate the function with correct type
        if str(actual_ret_type) != str(ret_type):
            func.delete()
            
            func_type = ir.FunctionType(actual_ret_type, param_types)
            func = ir.Function(self.module, func_type, name=lambda_name)

            entry = func.append_basic_block("entry")
            self.builder = ir.IRBuilder(entry)
            self.locals = {}
            self._reset_function_scope()

            for i, (param, llvm_param) in enumerate(zip(expr.params, func.args)):
                llvm_param.name = param.name
                alloca = self.builder.alloca(param_types[i], name=param.name)
                self.builder.store(llvm_param, alloca)
                self.locals[param.name] = alloca

            result = self._generate_expression(expr.body)
        
        # Return the result
        self.builder.ret(result)
        
        # Register this function
        self.functions[lambda_name] = func
        
        # Restore state
        self.builder = saved_builder
        self.locals = saved_locals
        self.current_function = saved_function
        
        # Return pointer to the function
        return func
    

    def _generate_cell_access(self) -> ir.Value:
        """Generate code to access current cell value (cell keyword)."""
        if self.current_matrix is None:
            return ir.Constant(ir.IntType(64), 0)
        
        # Get read buffer and current position
        read_buf = self.builder.load(self.locals["__read_buffer"])
        x = self.builder.load(self.locals["__cell_x"])
        y = self.builder.load(self.locals["__cell_y"])
        width = self.builder.load(self.locals["__width"])
        
        # Calculate index: y * width + x
        row_offset = self.builder.mul(y, width)
        idx = self.builder.add(row_offset, x)
        
        # Load value
        elem_ptr = self.builder.gep(read_buf, [idx])
        return self.builder.load(elem_ptr)
    
    def _generate_cell_index_access(self, expr: CellIndexExpr) -> ir.Value:
        """Generate code for relative cell access: cell[dx, dy].
        
        Returns nil (as optional) if out of bounds.
        """
        if self.current_matrix is None:
            return ir.Constant(ir.IntType(64), 0)
        
        # Get current position and offsets
        x = self.builder.load(self.locals["__cell_x"])
        y = self.builder.load(self.locals["__cell_y"])
        
        dx = self._generate_expression(expr.dx)
        dy = self._generate_expression(expr.dy)
        
        # Ensure i64
        if dx.type != ir.IntType(64):
            dx = self.builder.sext(dx, ir.IntType(64))
        if dy.type != ir.IntType(64):
            dy = self.builder.sext(dy, ir.IntType(64))
        
        # Calculate target position
        target_x = self.builder.add(x, dx)
        target_y = self.builder.add(y, dy)
        
        # Get dimensions
        width = self.builder.load(self.locals["__width"])
        height = self.builder.load(self.locals["__height"])
        
        # Bounds check
        x_valid_low = self.builder.icmp_signed(">=", target_x, ir.Constant(ir.IntType(64), 0))
        x_valid_high = self.builder.icmp_signed("<", target_x, width)
        y_valid_low = self.builder.icmp_signed(">=", target_y, ir.Constant(ir.IntType(64), 0))
        y_valid_high = self.builder.icmp_signed("<", target_y, height)
        
        x_valid = self.builder.and_(x_valid_low, x_valid_high)
        y_valid = self.builder.and_(y_valid_low, y_valid_high)
        in_bounds = self.builder.and_(x_valid, y_valid)
        
        # Create result based on bounds
        func = self.builder.function
        in_bounds_block = func.append_basic_block("cell_in_bounds")
        out_bounds_block = func.append_basic_block("cell_out_bounds")
        merge_block = func.append_basic_block("cell_merge")
        
        self.builder.cbranch(in_bounds, in_bounds_block, out_bounds_block)
        
        # In bounds: load value
        self.builder.position_at_end(in_bounds_block)
        read_buf = self.builder.load(self.locals["__read_buffer"])
        row_offset = self.builder.mul(target_y, width)
        idx = self.builder.add(row_offset, target_x)
        elem_ptr = self.builder.gep(read_buf, [idx])
        in_bounds_val = self.builder.load(elem_ptr)
        in_bounds_end = self.builder.block
        self.builder.branch(merge_block)
        
        # Out of bounds: return nil (0 for now)
        self.builder.position_at_end(out_bounds_block)
        # For optional support, we'd return a nil marker
        # For now, return 0
        out_bounds_val = ir.Constant(in_bounds_val.type, 0)
        out_bounds_end = self.builder.block
        self.builder.branch(merge_block)
        
        # Merge
        self.builder.position_at_end(merge_block)
        phi = self.builder.phi(in_bounds_val.type)
        phi.add_incoming(in_bounds_val, in_bounds_end)
        phi.add_incoming(out_bounds_val, out_bounds_end)
        
        return phi
    
    def _generate_matrix_return(self, value: ir.Value):
        """Handle return statement inside matrix formula - writes to write buffer."""
        if self.current_matrix is None:
            return
        
        # Write to current cell in write buffer
        write_buf = self.builder.load(self.locals["__write_buffer"])
        x = self.builder.load(self.locals["__cell_x"])
        y = self.builder.load(self.locals["__cell_y"])
        width = self.builder.load(self.locals["__width"])
        
        row_offset = self.builder.mul(y, width)
        idx = self.builder.add(row_offset, x)
        elem_ptr = self.builder.gep(write_buf, [idx])
        self.builder.store(value, elem_ptr)

    # ========================================================================
    # Compilation
    # ========================================================================
    

    # ========================================================================
    # Matrix (Cellular Automata) Implementation
    # ========================================================================
    
    def _register_matrix(self, matrix_decl: 'MatrixDecl'):
        """Register a matrix declaration and create its runtime structure."""
        name = matrix_decl.name
        self.matrix_decls[name] = matrix_decl
        
        # Determine element type
        elem_type = self._get_llvm_type(matrix_decl.element_type)
        
        # Create matrix struct type
        # struct Matrix_Name {
        #   i64 width, i64 height,
        #   elem_type* read_buffer,   # Current state (read from)
        #   elem_type* write_buffer,  # Next state (write to)
        # }
        struct_name = f"struct.Matrix_{name}"
        matrix_struct = ir.global_context.get_identified_type(struct_name)
        matrix_struct.set_body(
            ir.IntType(64),           # width
            ir.IntType(64),           # height
            elem_type.as_pointer(),   # read_buffer
            elem_type.as_pointer(),   # write_buffer
        )
        self.matrix_structs[name] = matrix_struct
        
        # Register in type registry for method dispatch
        # Register under both 'Counter' (for Type.new() pattern) and 'Matrix_Counter' (for instance method dispatch)
        self.type_registry[name] = matrix_struct
        self.type_methods[name] = {}
        
        # Also register under full struct name for method dispatch (since _get_type_name_from_ptr returns "Matrix_Counter")
        full_name = f"Matrix_{name}"
        self.type_registry[full_name] = matrix_struct
        self.type_methods[full_name] = {}
        
        # Create constructor: Matrix_Name.new() -> Matrix_Name*
        self._create_matrix_constructor(name, matrix_decl, matrix_struct, elem_type)
        
        # Create accessor methods
        self._create_matrix_accessors(name, matrix_struct, elem_type)
    
    def _create_matrix_constructor(self, name: str, matrix_decl: 'MatrixDecl', 
                                    matrix_struct: ir.Type, elem_type: ir.Type):
        """Create the matrix constructor function."""
        matrix_ptr_type = matrix_struct.as_pointer()
        
        # new() -> Matrix*
        func_name = f"Matrix_{name}_new"
        func_type = ir.FunctionType(matrix_ptr_type, [])
        func = ir.Function(self.module, func_type, name=func_name)
        self.functions[func_name] = func
        self.type_methods[name]["new"] = func_name
        self.type_methods[f"Matrix_{name}"]["new"] = func_name
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        # Evaluate width and height (they should be constant expressions)
        # For now, we generate them inline
        saved_builder = self.builder
        self.builder = builder
        
        width_val = self._generate_expression(matrix_decl.width)
        height_val = self._generate_expression(matrix_decl.height)
        init_val = self._generate_expression(matrix_decl.init_value)
        
        self.builder = saved_builder
        
        # Ensure i64
        if width_val.type != ir.IntType(64):
            width_val = builder.zext(width_val, ir.IntType(64))
        if height_val.type != ir.IntType(64):
            height_val = builder.zext(height_val, ir.IntType(64))
        
        # Allocate matrix struct via GC
        struct_size = ir.Constant(ir.IntType(64), 32)  # 4 * 8 bytes
        matrix_type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_UNKNOWN)
        raw_ptr = self.gc.alloc_with_deref(builder, struct_size, matrix_type_id)
        matrix_ptr = builder.bitcast(raw_ptr, matrix_ptr_type)
        
        # Store width and height
        width_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(width_val, width_field)
        
        height_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(height_val, height_field)
        
        # Calculate buffer size
        total_cells = builder.mul(width_val, height_val)
        elem_size = self._get_type_size(elem_type)
        buffer_size = builder.mul(total_cells, ir.Constant(ir.IntType(64), elem_size))
        
        # Allocate read buffer via GC
        buffer_type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_ARRAY_DATA)
        read_raw = self.gc.alloc_with_deref(builder, buffer_size, buffer_type_id)
        read_buffer = builder.bitcast(read_raw, elem_type.as_pointer())
        read_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(read_buffer, read_field)

        # Allocate write buffer via GC
        write_raw = self.gc.alloc_with_deref(builder, buffer_size, buffer_type_id)
        write_buffer = builder.bitcast(write_raw, elem_type.as_pointer())
        write_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(write_buffer, write_field)

        # Initialize all cells to init_value
        # for i in range(total_cells): buffer[i] = init_val
        idx_ptr = builder.alloca(ir.IntType(64), name="init_idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        
        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")
        
        builder.branch(init_loop)
        
        builder.position_at_end(init_loop)
        idx = builder.load(idx_ptr)
        cond = builder.icmp_signed("<", idx, total_cells)
        builder.cbranch(cond, init_body, init_done)
        
        builder.position_at_end(init_body)
        # Initialize both buffers
        read_elem_ptr = builder.gep(read_buffer, [idx])
        write_elem_ptr = builder.gep(write_buffer, [idx])
        
        # Cast init_val to element type if needed
        stored_val = self._cast_value_with_builder(builder, init_val, elem_type)
        builder.store(stored_val, read_elem_ptr)
        builder.store(stored_val, write_elem_ptr)
        
        next_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(init_loop)
        
        builder.position_at_end(init_done)
        builder.ret(matrix_ptr)
    
    def _create_matrix_accessors(self, name: str, matrix_struct: ir.Type, elem_type: ir.Type):
        """Create get/set accessor methods for a matrix."""
        matrix_ptr_type = matrix_struct.as_pointer()
        i64 = ir.IntType(64)
        
        # get(x, y) -> elem_type
        get_name = f"Matrix_{name}_get"
        get_type = ir.FunctionType(elem_type, [matrix_ptr_type, i64, i64])
        get_func = ir.Function(self.module, get_type, name=get_name)
        self.functions[get_name] = get_func
        self.type_methods[name]["get"] = get_name
        self.type_methods[f"Matrix_{name}"]["get"] = get_name
        
        get_func.args[0].name = "self"
        get_func.args[1].name = "x"
        get_func.args[2].name = "y"
        
        entry = get_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        self_ptr = get_func.args[0]
        x = get_func.args[1]
        y = get_func.args[2]
        
        # Get width for index calculation
        width_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = builder.load(width_field)
        
        # Get read buffer
        read_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = builder.load(read_field)
        
        # Calculate index: y * width + x
        row_offset = builder.mul(y, width)
        idx = builder.add(row_offset, x)
        
        # Load and return value
        elem_ptr = builder.gep(read_buffer, [idx])
        value = builder.load(elem_ptr)
        builder.ret(value)
        
        # set(x, y, value)
        set_name = f"Matrix_{name}_set"
        set_type = ir.FunctionType(ir.VoidType(), [matrix_ptr_type, i64, i64, elem_type])
        set_func = ir.Function(self.module, set_type, name=set_name)
        self.functions[set_name] = set_func
        self.type_methods[name]["set"] = set_name
        self.type_methods[f"Matrix_{name}"]["set"] = set_name
        
        set_func.args[0].name = "self"
        set_func.args[1].name = "x"
        set_func.args[2].name = "y"
        set_func.args[3].name = "value"
        
        entry = set_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        self_ptr = set_func.args[0]
        x = set_func.args[1]
        y = set_func.args[2]
        value = set_func.args[3]
        
        # Get width
        width_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = builder.load(width_field)
        
        # Get read buffer (set writes to read buffer for direct access)
        read_field = builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = builder.load(read_field)
        
        # Calculate index
        row_offset = builder.mul(y, width)
        idx = builder.add(row_offset, x)
        
        # Store value
        elem_ptr = builder.gep(read_buffer, [idx])
        builder.store(value, elem_ptr)
        builder.ret_void()
        
        # width() -> i64
        width_name = f"Matrix_{name}_width"
        width_type = ir.FunctionType(i64, [matrix_ptr_type])
        width_func = ir.Function(self.module, width_type, name=width_name)
        self.functions[width_name] = width_func
        self.type_methods[name]["width"] = width_name
        self.type_methods[f"Matrix_{name}"]["width"] = width_name
        
        entry = width_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        width_field = builder.gep(width_func.args[0], [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.ret(builder.load(width_field))
        
        # height() -> i64
        height_name = f"Matrix_{name}_height"
        height_type = ir.FunctionType(i64, [matrix_ptr_type])
        height_func = ir.Function(self.module, height_type, name=height_name)
        self.functions[height_name] = height_func
        self.type_methods[name]["height"] = height_name
        self.type_methods[f"Matrix_{name}"]["height"] = height_name
        
        entry = height_func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        height_field = builder.gep(height_func.args[0], [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.ret(builder.load(height_field))
    
    def _declare_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Declare user-defined matrix methods (register names without generating bodies)."""
        name = matrix_decl.name
        matrix_struct = self.matrix_structs[name]
        matrix_ptr_type = matrix_struct.as_pointer()
        
        for method in matrix_decl.methods:
            func_name = f"Matrix_{name}_{method.name}"
            func_type = ir.FunctionType(ir.VoidType(), [matrix_ptr_type])
            func = ir.Function(self.module, func_type, name=func_name)
            self.functions[func_name] = func
            self.type_methods[name][method.name] = func_name
            self.type_methods[f"Matrix_{name}"][method.name] = func_name
    
    def _generate_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Generate user-defined matrix methods (formulas that apply to all cells)."""
        name = matrix_decl.name
        matrix_struct = self.matrix_structs[name]
        matrix_ptr_type = matrix_struct.as_pointer()
        elem_type = self._get_llvm_type(matrix_decl.element_type)
        
        for method in matrix_decl.methods:
            self._generate_matrix_formula(name, method, matrix_struct, elem_type)
    
    def _generate_matrix_formula(self, matrix_name: str, method: 'FunctionDecl',
                                  matrix_struct: ir.Type, elem_type: ir.Type):
        """Generate a matrix formula method that applies to all cells.
        
        This generates a function that:
        1. Iterates over all cells (y, x)
        2. Sets up cell context (current position, read buffer access)
        3. Calls the formula body for each cell
        4. Writes result to write buffer
        5. Swaps buffers after completion
        """
        matrix_ptr_type = matrix_struct.as_pointer()
        i64 = ir.IntType(64)
        
        # Get the already-declared method
        func_name = f"Matrix_{matrix_name}_{method.name}"
        func = self.functions[func_name]
        
        func.args[0].name = "self"
        
        entry = func.append_basic_block("entry")
        self.builder = ir.IRBuilder(entry)
        
        # Save state
        saved_locals = self.locals.copy()
        saved_matrix = self.current_matrix
        saved_cell_x = self.current_cell_x
        saved_cell_y = self.current_cell_y

        self.locals = {}
        self._reset_function_scope()
        self.current_matrix = matrix_name
        
        # Get self pointer
        self_ptr = func.args[0]
        self_alloca = self.builder.alloca(matrix_ptr_type, name="self")
        self.builder.store(self_ptr, self_alloca)
        self.locals["self"] = self_alloca
        
        # Load matrix dimensions
        width_field = self.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        width = self.builder.load(width_field, name="width")
        
        height_field = self.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        height = self.builder.load(height_field, name="height")
        
        # Get buffer pointers
        read_field = self.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        read_buffer = self.builder.load(read_field, name="read_buffer")
        
        write_field = self.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        write_buffer = self.builder.load(write_field, name="write_buffer")
        
        # Store buffers for cell access
        read_alloca = self.builder.alloca(elem_type.as_pointer(), name="read_buf")
        self.builder.store(read_buffer, read_alloca)
        self.locals["__read_buffer"] = read_alloca
        
        write_alloca = self.builder.alloca(elem_type.as_pointer(), name="write_buf")
        self.builder.store(write_buffer, write_alloca)
        self.locals["__write_buffer"] = write_alloca
        
        width_alloca = self.builder.alloca(i64, name="matrix_width")
        self.builder.store(width, width_alloca)
        self.locals["__width"] = width_alloca
        
        height_alloca = self.builder.alloca(i64, name="matrix_height")
        self.builder.store(height, height_alloca)
        self.locals["__height"] = height_alloca
        
        # PRE-ALLOCATE all local variables used in the formula body
        # This prevents stack overflow from allocas inside the loop
        local_vars = self._collect_local_variables(method.body)
        for var_name in local_vars:
            if var_name not in self.locals:
                var_alloca = self.builder.alloca(i64, name=var_name)
                self.locals[var_name] = var_alloca
        
        # Create loop: for y in 0..height: for x in 0..width: body
        y_var = self.builder.alloca(i64, name="cell_y")
        self.builder.store(ir.Constant(i64, 0), y_var)
        self.locals["__cell_y"] = y_var
        self.current_cell_y = y_var
        
        x_var = self.builder.alloca(i64, name="cell_x")
        self.locals["__cell_x"] = x_var
        self.current_cell_x = x_var
        
        # Outer loop (y)
        y_loop_cond = func.append_basic_block("y_loop_cond")
        y_loop_body = func.append_basic_block("y_loop_body")
        y_loop_inc = func.append_basic_block("y_loop_inc")
        y_loop_end = func.append_basic_block("y_loop_end")
        
        self.builder.branch(y_loop_cond)
        
        self.builder.position_at_end(y_loop_cond)
        y_val = self.builder.load(y_var)
        y_cond = self.builder.icmp_signed("<", y_val, height)
        self.builder.cbranch(y_cond, y_loop_body, y_loop_end)
        
        self.builder.position_at_end(y_loop_body)
        # Inner loop (x)
        self.builder.store(ir.Constant(i64, 0), x_var)
        
        x_loop_cond = func.append_basic_block("x_loop_cond")
        x_loop_body = func.append_basic_block("x_loop_body")
        x_loop_inc = func.append_basic_block("x_loop_inc")
        x_loop_end = func.append_basic_block("x_loop_end")
        
        self.builder.branch(x_loop_cond)
        
        self.builder.position_at_end(x_loop_cond)
        x_val = self.builder.load(x_var)
        x_cond = self.builder.icmp_signed("<", x_val, width)
        self.builder.cbranch(x_cond, x_loop_body, x_loop_end)
        
        self.builder.position_at_end(x_loop_body)
        
        # Generate formula body
        result = None
        for stmt in method.body:
            result = self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break
        
        # Only generate write-to-buffer code if block isn't already terminated by return
        if not self.builder.block.is_terminated:
            # If no explicit return, the formula should return a value
            # Write result to write buffer
            if result is None:
                result = ir.Constant(elem_type, 0)
            
            # Calculate write index
            x_val = self.builder.load(x_var)
            y_val = self.builder.load(y_var)
            width_val = self.builder.load(width_alloca)
            write_buf = self.builder.load(write_alloca)
            
            row_offset = self.builder.mul(y_val, width_val)
            write_idx = self.builder.add(row_offset, x_val)
            write_ptr = self.builder.gep(write_buf, [write_idx])
            
            # Store result if we have one (non-void expression result)
            if result is not None and hasattr(result, 'type') and result.type != ir.VoidType():
                self.builder.store(result, write_ptr)
            
            self.builder.branch(x_loop_inc)
        
        # x increment
        self.builder.position_at_end(x_loop_inc)
        x_val = self.builder.load(x_var)
        next_x = self.builder.add(x_val, ir.Constant(i64, 1))
        self.builder.store(next_x, x_var)
        self.builder.branch(x_loop_cond)
        
        # x loop end -> y increment
        self.builder.position_at_end(x_loop_end)
        self.builder.branch(y_loop_inc)
        
        # y increment
        self.builder.position_at_end(y_loop_inc)
        y_val = self.builder.load(y_var)
        next_y = self.builder.add(y_val, ir.Constant(i64, 1))
        self.builder.store(next_y, y_var)
        self.builder.branch(y_loop_cond)
        
        # After loops: swap buffers
        self.builder.position_at_end(y_loop_end)
        
        # Swap read and write buffers
        current_read = self.builder.load(read_field)
        current_write = self.builder.load(write_field)
        self.builder.store(current_write, read_field)
        self.builder.store(current_read, write_field)

        self.builder.ret_void()
        
        # Restore state
        self.locals = saved_locals
        self.current_matrix = saved_matrix
        self.current_cell_x = saved_cell_x
        self.current_cell_y = saved_cell_y
    
    def _get_type_size(self, llvm_type: ir.Type) -> int:
        """Get size of LLVM type in bytes (min 1 byte for sub-byte types like bool)"""
        if isinstance(llvm_type, ir.IntType):
            return max(1, llvm_type.width // 8)
        elif isinstance(llvm_type, ir.DoubleType):
            return 8
        elif isinstance(llvm_type, ir.FloatType):
            return 4
        elif isinstance(llvm_type, ir.PointerType):
            return 8
        else:
            return 8
    
    def _cast_value_with_builder(self, builder: ir.IRBuilder, value: ir.Value, 
                                  target_type: ir.Type) -> ir.Value:
        """Cast a value to target type using specified builder"""
        if value.type == target_type:
            return value
        
        # int -> float
        if isinstance(value.type, ir.IntType) and isinstance(target_type, ir.DoubleType):
            return builder.sitofp(value, target_type)
        
        # float -> int
        if isinstance(value.type, ir.DoubleType) and isinstance(target_type, ir.IntType):
            return builder.fptosi(value, target_type)
        
        # int -> bool (i1)
        if isinstance(value.type, ir.IntType) and isinstance(target_type, ir.IntType):
            if target_type.width < value.type.width:
                return builder.trunc(value, target_type)
            elif target_type.width > value.type.width:
                return builder.zext(value, target_type)
        
        return value
    
    def _collect_local_variables(self, stmts: list) -> set:
        """Collect all variable names assigned in a list of statements.
        
        This is used to pre-allocate local variables in matrix formulas
        to prevent stack overflow from allocas inside loops.
        """
        var_names = set()
        
        def collect_from_stmt(stmt):
            if isinstance(stmt, Assignment):
                if isinstance(stmt.target, Identifier):
                    var_names.add(stmt.target.name)
            elif isinstance(stmt, VarDecl):
                var_names.add(stmt.name)
            elif isinstance(stmt, IfStmt):
                for s in stmt.then_body:
                    collect_from_stmt(s)
                for clause in stmt.else_if_clauses:
                    # clause is a tuple: (condition, body)
                    for s in clause[1]:
                        collect_from_stmt(s)
                if stmt.else_body:
                        for s in stmt.else_body:
                            collect_from_stmt(s)
            elif isinstance(stmt, ForStmt):
                # Loop variable
                if isinstance(stmt.pattern, str):
                    var_names.add(stmt.pattern)
                elif hasattr(stmt.pattern, 'name'):
                    var_names.add(stmt.pattern.name)
                for s in stmt.body:
                    collect_from_stmt(s)
            elif isinstance(stmt, MatchStmt):
                for arm in stmt.arms:
                    for s in arm.body:
                        collect_from_stmt(s)
            elif isinstance(stmt, TupleDestructureStmt):
                # Collect all variable names from tuple destructuring
                for name in stmt.names:
                    var_names.add(name)

        for stmt in stmts:
            collect_from_stmt(stmt)
        
        return var_names

    # ========================================================================
    # Inline LLVM IR Support
    # ========================================================================

    def _generate_llvm_ir_block(self, block) -> Optional[ir.Value]:
        """Generate code for inline LLVM IR via stub function pattern

        Creates a stub function declaration that will be replaced with the
        actual IR body during module serialization.
        """
        from typing import Union
        self._inline_ir_counter += 1
        stub_name = f"__coex_llvm_ir_{self._inline_ir_counter}"

        # Collect argument types/values from bindings
        arg_types = []
        arg_values = []
        param_names = []

        for binding in block.bindings:
            if binding.coex_name not in self.locals:
                raise RuntimeError(f"Unknown variable in llvm_ir binding: {binding.coex_name}")
            var_ptr = self.locals[binding.coex_name]
            var_val = self.builder.load(var_ptr)
            arg_types.append(var_val.type)
            arg_values.append(var_val)
            param_names.append(binding.llvm_register.lstrip('%'))

        # Determine return type
        if isinstance(block, LlvmIrExpr):
            ret_type = self._llvm_type_from_hint(block.return_type)
        else:
            ret_type = ir.VoidType()

        # Create stub function declaration
        func_type = ir.FunctionType(ret_type, arg_types)
        stub_func = ir.Function(self.module, func_type, name=stub_name)

        # Record for post-processing during serialization
        self._pending_inline_ir.append({
            'name': stub_name,
            'param_names': param_names,
            'param_types': [str(t) for t in arg_types],
            'return_type': str(ret_type),
            'ir_body': block.ir_body,
        })

        # Generate call to the stub function
        if isinstance(ret_type, ir.VoidType):
            self.builder.call(stub_func, arg_values)
            return None
        else:
            return self.builder.call(stub_func, arg_values)

    def _llvm_type_from_hint(self, hint: str) -> ir.Type:
        """Convert LLVM type hint string to llvmlite type"""
        type_map = {
            'i1': ir.IntType(1),
            'i8': ir.IntType(8),
            'i16': ir.IntType(16),
            'i32': ir.IntType(32),
            'i64': ir.IntType(64),
            'i128': ir.IntType(128),
            'float': ir.FloatType(),
            'double': ir.DoubleType(),
            'ptr': ir.IntType(8).as_pointer(),
            'void': ir.VoidType(),
        }
        return type_map.get(hint.lower(), ir.IntType(64))

    def _inject_inline_ir(self, raw_ir: str) -> str:
        """Replace stub declarations with full function definitions

        This is called during module serialization to inject the user's
        raw LLVM IR into the module.
        """
        import re

        if not self._pending_inline_ir:
            return raw_ir

        result = raw_ir

        for pending in self._pending_inline_ir:
            name = pending['name']
            param_names = pending['param_names']
            param_types = pending['param_types']
            ret_type = pending['return_type']
            ir_body = pending['ir_body']

            # Build function definition with named parameters
            # llvmlite uses quotes around names, so we need to match that
            params = ', '.join(f"{t} %{n}" for t, n in zip(param_types, param_names))
            body_indented = '\n'.join('  ' + line for line in ir_body.split('\n') if line.strip())

            func_def = f"""define {ret_type} @"{name}"({params}) {{
entry:
{body_indented}
}}"""

            # Find and replace the declaration with the definition
            # llvmlite wraps names in quotes: declare i64 @"__coex_llvm_ir_1"(i64 %".1", i64 %".2")
            decl_pattern = rf'declare\s+{re.escape(ret_type)}\s+@"{re.escape(name)}"\s*\([^)]*\)'
            result = re.sub(decl_pattern, func_def, result)

        return result

    def compile_to_object(self, output_path: str):
        """Compile module to object file"""
        llvm_ir = str(self.module)
        llvm_ir = self._inject_inline_ir(llvm_ir)  # Inject inline LLVM IR
        try:
            mod = binding.parse_assembly(llvm_ir)
            mod.verify()
        except Exception as e:
            raise RuntimeError(f"LLVM IR error (possibly in inline IR): {e}")

        target = binding.Target.from_default_triple()
        target_machine = target.create_target_machine()

        with open(output_path, "wb") as f:
            f.write(target_machine.emit_object(mod))

    def get_ir(self) -> str:
        """Get LLVM IR as string"""
        raw_ir = str(self.module)
        return self._inject_inline_ir(raw_ir)
