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

# Import Channel generator module
from codegen.channel import ChannelGenerator

# Import Array generator module
from codegen.array import ArrayGenerator

# Import Atomic Ref generator module
from codegen.atomic import AtomicGenerator

# Import Atomic Primitives generator module (atomic_int, atomic_float, atomic_bool)
from codegen.atomic_primitives import AtomicPrimitiveGenerator

# Import Result generator module
from codegen.result import ResultGenerator

# Import in-place mutation operations for uniqueness optimization
from codegen.inplace_ops import create_inplace_operations

# Import Module/FFI generator module
from codegen.modules import ModuleGenerator

# Import Function generator module
from codegen.functions import FunctionGenerator

# Import Loop generator module
from codegen.loops import LoopGenerator

# Import Comprehension generator module
from codegen.comprehensions import ComprehensionGenerator

# Import Generics handler module
from codegen.generics import GenericsHandler

# Import Flow Control generator module
from codegen.flow_control import FlowControlGenerator

# Import Expression generator module
from codegen.expressions import ExpressionGenerator

# Import Statement generator module
from codegen.statements import StatementGenerator

# Import Conversion generator module
from codegen.conversions import ConversionGenerator

# Import Formula GPU offload module
from codegen.formula import try_offload

# Import Trait generator module
from codegen.traits import TraitGenerator

# Import Thread generator module (for concurrent thread support)
from codegen.thread import ThreadGenerator

# Import Task transformer module (for lightweight coroutine tasks)
from task_transform import TaskTransformer

# Import Enum generator module
from codegen.enums import EnumGenerator

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

        # Unique bindings tracking for ownership system
        # Unique bindings have sole ownership and are never aliased
        self.unique_bindings: set = set()  # Set of variable names declared as unique

        # Aliasing tracking for in-place mutation optimization
        # When a collection variable is copied (e.g., s2 = s1), the source (s1)
        # is marked as aliased. In-place mutation cannot be applied to aliased
        # variables because it would violate value semantics for the copy.
        # Note: Unique bindings are never aliased (they have sole ownership).
        self.aliased_vars: set = set()  # Set of variable names whose values have been copied

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

        # Create Channel type and helpers
        self._channel = ChannelGenerator(self)
        self._channel.register_channel_type()

        # Create in-place mutation operations (for uniqueness optimization)
        # These are variants that mutate wrapper objects in place when binding is unique
        self.inplace_variants = {}  # Will be populated by create_inplace_operations
        create_inplace_operations(self)

        # Create JSON type and helpers
        self._json = JsonGenerator(self)
        self._json.create_json_type()

        # Create Array type and helpers (dense N-D collection)
        # N-D Array struct (104 bytes = 13 i64 fields):
        #   Field 0: handle (i64) - GC handle for data buffer
        #   Field 1: ndim (i64) - number of dimensions (1, 2, ...)
        #   Field 2: shape [4 x i64] - dimensions [dim0, dim1, dim2, dim3]
        #   Field 3: strides [4 x i64] - byte strides per dimension
        #   Field 4: offset (i64) - byte offset into buffer (for views)
        #   Field 5: elem_size (i64) - 8 for int/float, 1 for byte
        #   Field 6: type_id (i64) - element type identifier
        # For 1D: shape[0]=len, strides[0]=elem_size
        # For 2D: shape=[rows,cols], strides=[cols*elem_size, elem_size]
        self.array_struct = ir.global_context.get_identified_type("struct.Array")
        self.array_struct.set_body(
            ir.IntType(64),              # handle (field 0) - GC handle to data buffer
            ir.IntType(64),              # ndim (field 1) - number of dimensions
            ir.ArrayType(ir.IntType(64), 4),  # shape (field 2) - [4 x i64]
            ir.ArrayType(ir.IntType(64), 4),  # strides (field 3) - [4 x i64]
            ir.IntType(64),              # offset (field 4) - byte offset for views
            ir.IntType(64),              # elem_size (field 5) - element size in bytes
            ir.IntType(64),              # type_id (field 6) - element type identifier
        )
        # Array helpers moved to codegen/array.py - ArrayGenerator class
        self._array = ArrayGenerator(self)
        self._array.create_array_helpers()

        # NOTE: Conversion helpers (_list_to_array, _array_to_list, etc.)
        # are inline methods, not separate function declarations

        # Atomic ref type and helpers moved to codegen/atomic.py - AtomicGenerator class
        self._atomic = AtomicGenerator(self)
        self._atomic.create_atomic_ref_type()

        # Atomic primitives (atomic_int, atomic_float, atomic_bool)
        self._atomic_primitives = AtomicPrimitiveGenerator(self)

        # Create Result type struct (helpers moved to codegen/result.py)
        # struct.Result { i64 tag, i64 ok_value, i64 err_value }
        # tag: 0 = Ok, 1 = Err
        self.result_struct = ir.global_context.get_identified_type("struct.Result")
        self.result_struct.set_body(
            ir.IntType(64),  # tag: 0 = Ok, 1 = Err
            ir.IntType(64),  # ok_value (stored as i64, may be pointer)
            ir.IntType(64),  # err_value (stored as i64, may be pointer)
        )
        # Result helpers moved to codegen/result.py - ResultGenerator class
        self._result = ResultGenerator(self)
        self._result.create_result_helpers()

        # Register Result as an enum-like type with Ok and Err variants
        # This enables pattern matching: case Ok(v): / case Err(e):
        self.enum_variants["Result"] = {
            "Ok": (0, [("value", PrimitiveType("int"))]),   # tag 0
            "Err": (1, [("error", PrimitiveType("string"))]),  # tag 1
        }

        # Create built-in posix platform type
        self._posix = PosixGenerator(self)
        self._posix.create_posix_type()

        # Module/FFI helpers moved to codegen/modules.py - ModuleGenerator class
        self._modules = ModuleGenerator(self)

        # Function generation helpers moved to codegen/functions.py - FunctionGenerator class
        self._functions = FunctionGenerator(self)

        # Loop generation helpers moved to codegen/loops.py - LoopGenerator class
        self._loops = LoopGenerator(self)

        # Comprehension generation helpers moved to codegen/comprehensions.py - ComprehensionGenerator class
        self._comprehensions = ComprehensionGenerator(self)

        # Generics/monomorphization helpers moved to codegen/generics.py - GenericsHandler class
        self._generics = GenericsHandler(self)

        # Flow control helpers moved to codegen/flow_control.py - FlowControlGenerator class
        self._flow_control = FlowControlGenerator(self)

        # Expression generation helpers moved to codegen/expressions.py - ExpressionGenerator class
        self._expressions = ExpressionGenerator(self)

        # Statement generation helpers moved to codegen/statements.py - StatementGenerator class
        self._statements = StatementGenerator(self)

        # Conversion helpers moved to codegen/conversions.py - ConversionGenerator class
        self._conversions = ConversionGenerator(self)

        # Trait helpers moved to codegen/traits.py - TraitGenerator class
        self._traits = TraitGenerator(self)

        # Thread concurrency moved to codegen/thread.py - ThreadGenerator class
        self._thread = ThreadGenerator(self)
        self._thread.create_task_types()

        # Task transformation for lightweight coroutines - task_transform.py
        self._task = TaskTransformer(self)

        # Enum helpers moved to codegen/enums.py - EnumGenerator class
        self._enums = EnumGenerator(self)

    # List helpers moved to codegen/list.py - ListGenerator class
    # HAMT/Map/Set helpers moved to codegen/hamt.py - HamtGenerator class

    # Array helpers moved to codegen/array.py - ArrayGenerator class
    # Conversion helpers moved to codegen/conversions.py - ConversionGenerator class

    def _list_to_array(self, list_ptr: ir.Value) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.list_to_array(list_ptr)

    def _set_to_array(self, set_ptr: ir.Value) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.set_to_array(set_ptr)

    def _array_to_list(self, array_ptr: ir.Value) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.array_to_list(array_ptr)

    def _array_to_set(self, array_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.array_to_set(array_ptr, elem_is_ptr)

    def _list_to_set(self, list_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.list_to_set(list_ptr, elem_is_ptr)

    def _try_implicit_collection_conversion(self, value: ir.Value, target_type: Type, value_type: Type = None) -> Tuple[ir.Value, bool]:
        """Delegate to ConversionGenerator."""
        return self._conversions.try_implicit_collection_conversion(value, target_type, value_type)

    def _get_conversion_warning_message(self, source_struct: str, target_struct: str) -> str:
        """Delegate to ConversionGenerator."""
        return self._conversions.get_conversion_warning_message(source_struct, target_struct)

    def _is_primitive_coex_type(self, coex_type: Type) -> bool:
        """Delegate to ConversionGenerator."""
        return self._conversions.is_primitive_coex_type(coex_type)

    def _needs_parameter_copy(self, coex_type: Type) -> bool:
        """Delegate to ConversionGenerator."""
        return self._conversions.needs_parameter_copy(coex_type)

    def _is_heap_type(self, coex_type: Type) -> bool:
        """Delegate to ConversionGenerator."""
        return self._conversions.is_heap_type(coex_type)

    def _compute_map_flags(self, key_type: Type, value_type: Type) -> int:
        """Delegate to ConversionGenerator."""
        return self._conversions.compute_map_flags(key_type, value_type)

    def _compute_set_flags(self, elem_type: Type) -> int:
        """Delegate to ConversionGenerator."""
        return self._conversions.compute_set_flags(elem_type)

    def _is_collection_coex_type(self, coex_type: Type) -> bool:
        """Delegate to ConversionGenerator."""
        return self._conversions.is_collection_coex_type(coex_type)

    def _get_receiver_type(self, expr: Expr) -> Optional[Type]:
        """Delegate to ConversionGenerator."""
        return self._conversions.get_receiver_type(expr)

    def _needs_deep_copy(self, coex_type: Type) -> bool:
        """Delegate to ConversionGenerator."""
        return self._conversions.needs_deep_copy(coex_type)

    def _generate_move_or_eager_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_move_or_eager_copy(value, coex_type)

    def _generate_deep_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_deep_copy(value, coex_type)

    def _generate_list_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_list_deep_copy(src, elem_type)

    def _generate_set_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_set_deep_copy(src, elem_type)

    def _generate_map_deep_copy(self, src: ir.Value, key_type: Type, value_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_map_deep_copy(src, key_type, value_type)

    def _generate_array_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_array_deep_copy(src, elem_type)

    def _generate_type_deep_copy(self, src: ir.Value, coex_type: NamedType) -> ir.Value:
        """Delegate to ConversionGenerator."""
        return self._conversions.generate_type_deep_copy(src, coex_type)

    # ========================================================================
    # Atomic Reference type moved to codegen/atomic.py - AtomicGenerator class

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
    # Result helpers moved to codegen/result.py - ResultGenerator class

    # ========================================================================
    # Type Mapping
    # ========================================================================
    
    def _get_llvm_type(self, coex_type: Type) -> ir.Type:
        """Convert Coex type to LLVM type"""
        if isinstance(coex_type, PrimitiveType):
            type_map = {
                "int": ir.IntType(64),
                "int32": ir.IntType(32),
                "float": ir.DoubleType(),
                "float32": ir.FloatType(),
                "bool": ir.IntType(1),
                "string": self.string_struct.as_pointer(),
                "byte": ir.IntType(8),
                "char": ir.IntType(32),
                "json": self.json_struct.as_pointer(),
            }
            return type_map.get(coex_type.name, ir.IntType(64))
        
        elif isinstance(coex_type, AtomicType):
            # Atomic primitives always use i64 storage for proper alignment.
            # Float and bool values are bitcast to/from i64 during atomic operations.
            # This ensures atomic instructions work correctly on all platforms.
            return ir.IntType(64)
        
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

        elif isinstance(coex_type, ChannelType):
            # Channels are pointers to Channel struct
            return self._channel.get_channel_struct().as_pointer()

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
                self._modules.load_library(imp.library_path, imp.module)
            else:
                # Module import: import math
                self._modules.load_module(imp.module)

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

        # Store function declarations for return type inference
        for func in program.functions:
            self.func_decls[func.name] = func
        
        # First pass for functions: declare all (including type methods)
        for func in program.functions:
            self._declare_function(func)
        
        # Declare methods for all types
        for type_decl in program.types:
            self._declare_type_methods(type_decl)

        # Prepare all task functions for mutual recursion support
        # This creates frame types and declares step functions for ALL tasks
        # before any step function body is generated, allowing tasks to
        # reference each other (e.g., is_even calling is_odd and vice versa)
        if self._task is not None:
            self._task.prepare_all_tasks_for_mutual_recursion(program.functions)

        # Second pass: generate function bodies
        for func in program.functions:
            self._generate_function(func)
        
        # Generate method bodies for all types
        for type_decl in program.types:
            self._generate_type_methods(type_decl)

        # Phase 9: Finalize GC type tables after all types are registered
        # This creates the offset arrays for user types so gc_mark_object can
        # recursively mark pointer fields in user-defined types
        self.gc.finalize_type_tables()

        return self.get_ir()

    # ========================================================================
    # Module Loading and FFI Library Loading
    # moved to codegen/modules.py - ModuleGenerator class
    # ========================================================================

    def get_ffi_link_args(self) -> PyList[str]:
        """Get the link arguments for FFI libraries.

        Call this after generate() to get the list of object files
        and system libraries needed for linking.
        """
        return self.ffi_link_args

    def uses_scheduler(self) -> bool:
        """Check if the compiled program uses the task scheduler.

        Returns True if any task functions (using 'task' keyword) were defined,
        which requires linking the scheduler runtime library.
        """
        return len(self._task.get_task_function_names()) > 0

    def uses_channels(self) -> bool:
        """Check if the compiled program uses channels.

        Returns True if Channel type is used, which requires linking
        the channel runtime library.
        """
        return self._channel.uses_channels()

    def uses_blas(self) -> bool:
        """Check if the compiled program uses CPU BLAS functions.

        Returns True if any coex_linalg_* extern functions are declared,
        which requires linking the BLAS runtime library.
        """
        if not hasattr(self, 'extern_function_decls'):
            return False
        blas_funcs = {'coex_linalg_matmul', 'coex_linalg_matmul32',
                      'coex_linalg_dot', 'coex_linalg_norm'}
        return any(fn in self.extern_function_decls for fn in blas_funcs)

    def uses_gpu_linalg(self) -> bool:
        """Check if the compiled program uses GPU linear algebra functions.

        Returns True if coex_metal_matmul is used, which requires linking
        the Metal runtime library with MetalPerformanceShaders.
        """
        if not hasattr(self, 'extern_function_decls'):
            return False
        gpu_funcs = {'coex_metal_matmul', 'coex_metal_matmul_f32_native'}
        return any(fn in self.extern_function_decls for fn in gpu_funcs)

    # Trait helpers moved to codegen/traits.py - TraitGenerator class

    def _register_trait(self, trait_decl: 'TraitDecl'):
        """Delegate to TraitGenerator."""
        return self._traits.register_trait(trait_decl)

    def _check_trait_implementations(self, type_decl: TypeDecl):
        """Delegate to TraitGenerator."""
        return self._traits.check_trait_implementations(type_decl)

    def _type_implements_trait(self, type_decl: TypeDecl, trait_decl: 'TraitDecl',
                               type_methods: Dict[str, FunctionDecl]) -> bool:
        """Delegate to TraitGenerator."""
        return self._traits.type_implements_trait(type_decl, trait_decl, type_methods)

    def _methods_compatible(self, trait_method: FunctionDecl, type_method: FunctionDecl) -> bool:
        """Delegate to TraitGenerator."""
        return self._traits.methods_compatible(trait_method, type_method)

    def _check_trait_bound(self, type_name: str, trait_name: str) -> bool:
        """Delegate to TraitGenerator."""
        return self._traits.check_trait_bound(type_name, trait_name)

    def _primitive_implements_trait(self, type_name: str, trait_name: str) -> bool:
        """Delegate to TraitGenerator."""
        return self._traits.primitive_implements_trait(type_name, trait_name)

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
    
    # ========================================================================
    # Generics/Monomorphization (delegated to codegen/generics.py)
    # ========================================================================

    def _substitute_type(self, coex_type: Type) -> Type:
        """Substitute type parameters with concrete types"""
        return self._generics.substitute_type(coex_type)

    def _mangle_generic_name(self, base_name: str, type_args: PyList[Type]) -> str:
        """Create mangled name for monomorphized generic: Pair_int_float"""
        return self._generics.mangle_generic_name(base_name, type_args)

    def _type_to_string(self, coex_type: Type) -> str:
        """Convert type to string for name mangling"""
        return self._generics.type_to_string(coex_type)

    def _monomorphize_type(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic type with concrete type arguments"""
        return self._generics.monomorphize_type(name, type_args)

    def _check_monomorphized_trait_implementations(self, mangled_name: str, type_decl: TypeDecl):
        """Check which traits a monomorphized type implements"""
        return self._generics.check_monomorphized_trait_implementations(mangled_name, type_decl)

    def _declare_type_methods_monomorphized(self, mangled_type_name: str, type_decl: TypeDecl):
        """Declare methods for a monomorphized type"""
        return self._functions.declare_type_methods_monomorphized(mangled_type_name, type_decl)

    def _generate_method_body(self, type_name: str, mangled_method: str, method: FunctionDecl):
        """Generate body for a method"""
        return self._functions.generate_method_body(type_name, mangled_method, method)

    def _monomorphize_function(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic function with concrete type arguments"""
        return self._functions.monomorphize_function(name, type_args)

    def _infer_type_args(self, func_name: str, args: PyList[Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic function from call arguments"""
        return self._generics.infer_type_args(func_name, args)

    def _infer_type_args_from_constructor(self, type_name: str, args: PyList[Expr],
                                          named_args: Dict[str, Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic type constructor"""
        return self._generics.infer_type_args_from_constructor(type_name, args, named_args)

    def _unify_type_constructor(self, declared_type: Type, inferred_type: Type,
                                inferred: Dict[str, Type], type_params: PyList[TypeParam]):
        """Unify a declared field type with an inferred argument type"""
        return self._generics.unify_type_constructor(declared_type, inferred_type, inferred, type_params)

    def _infer_type_from_expr(self, expr: Expr) -> Type:
        """Infer the Coex type of an expression"""
        return self._generics.infer_type_from_expr(expr)

    def _llvm_type_to_coex(self, llvm_type: ir.Type) -> Type:
        """Convert LLVM type back to Coex type (approximate)"""
        return self._generics.llvm_type_to_coex(llvm_type)

    def _unify_types_with_params(self, param_type: Type, arg_type: Type,
                                 inferred: Dict[str, Type], param_names: set):
        """Unify a parameter type with an argument type to infer type parameters"""
        return self._generics.unify_types_with_params(param_type, arg_type, inferred, param_names)

    def _unify_types(self, param_type: Type, arg_type: Type, inferred: Dict[str, Type]):
        """Unify a parameter type with an argument type to infer type parameters (legacy)"""
        return self._generics.unify_types(param_type, arg_type, inferred)

    def _register_enum_type(self, type_decl: TypeDecl):
        """Register enum type - delegated to EnumGenerator"""
        return self._enums.register_enum_type(type_decl)

    def _method_uses_self(self, method) -> bool:
        """Check if a method body references 'self' or implicit field access."""
        return self._functions.method_uses_self(method)

    def _declare_type_methods(self, type_decl: TypeDecl):
        """Declare all methods for a type"""
        return self._functions.declare_type_methods(type_decl)

    def _generate_type_methods(self, type_decl: TypeDecl):
        """Generate method bodies for a type"""
        return self._functions.generate_type_methods(type_decl)

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
                # BUG-019: Coex strings need proper null-termination for C interop.
                # For slice views, the null terminator may not be at the end of the
                # slice's extent. We must create a null-terminated copy to be safe.
                return self._marshal_string_for_extern(value)
            # int, float, bool: no conversion needed (same ABI)
        return value

    def _marshal_string_for_extern(self, string_ptr: ir.Value) -> ir.Value:
        """Marshal a Coex string for passing to extern C function (BUG-019).

        Creates a stack-allocated null-terminated copy of the string data.
        This is safe for all strings including slice views.

        For performance: uses stack allocation for strings up to 4KB,
        falls back to heap for larger strings.
        """
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = i8.as_pointer()

        # Get string's data pointer
        data_ptr = self.builder.call(self.string_data, [string_ptr])

        # Get string's byte size (field 3)
        size_ptr = self.builder.gep(string_ptr, [
            ir.Constant(i32, 0), ir.Constant(i32, 3)
        ], inbounds=True)
        byte_size = self.builder.load(size_ptr)

        # Calculate allocation size (size + 1 for null terminator)
        alloc_size = self.builder.add(byte_size, ir.Constant(i64, 1))

        # For simplicity, always use stack allocation up to a reasonable limit.
        # LLVM will handle very large allocas appropriately.
        # In a production system, we'd check size and use heap for large strings.
        temp_buf = self.builder.alloca(i8, size=alloc_size, name="cstr_temp")

        # Copy string data to temporary buffer
        self.builder.call(self.memcpy, [temp_buf, data_ptr, byte_size])

        # Write null terminator at the end
        null_ptr = self.builder.gep(temp_buf, [byte_size])
        self.builder.store(ir.Constant(i8, 0), null_ptr)

        return temp_buf

    def _convert_from_c_type(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Convert a C return value back to Coex type.

        Since Coex int is 64-bit and maps to C int64_t, no conversion needed.
        For most types, the value passes through unchanged.
        """
        # No conversion needed - types match between Coex and C ABI
        return value

    def _declare_function(self, func: FunctionDecl):
        """Declare a function (for forward references)"""
        return self._functions.declare_function(func)

    def _declare_extern_function(self, func: FunctionDecl):
        """Declare an extern function (external C linkage, no body)."""
        return self._functions.declare_extern_function(func)

    def _generate_extern_call(self, name: str, args: list, func_decl: FunctionDecl) -> ir.Value:
        """Generate a call to an extern function with C ABI type conversion."""
        return self._functions.generate_extern_call(name, args, func_decl)

    def _declare_main_with_params(self, func: FunctionDecl):
        """Handle main() function with special parameters (args, stdin, stdout, stderr)."""
        return self._functions.declare_main_with_params(func)

    def _collect_heap_vars_from_body(self, stmts: PyList[Stmt]) -> PyList[str]:
        """Collect names of heap-typed variable declarations from function body."""
        return self._functions.collect_heap_vars_from_body(stmts)

    def _generate_function(self, func: FunctionDecl):
        """Generate a function body"""
        return self._functions.generate_function(func)

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
    # Statement Generation - delegated to StatementGenerator
    # ========================================================================

    def _generate_statement(self, stmt: Stmt):
        """Generate code for a statement - delegated to StatementGenerator"""
        return self._statements.generate_statement(stmt)

    def _generate_var_decl(self, stmt: VarDecl):
        """Generate var decl - delegated to StatementGenerator"""
        return self._statements.generate_var_decl(stmt)

    def _generate_tuple_destructure(self, stmt: 'TupleDestructureStmt'):
        """Generate tuple destructure - delegated to StatementGenerator"""
        return self._statements.generate_tuple_destructure(stmt)

    def _generate_assignment(self, stmt: Assignment):
        """Generate assignment - delegated to StatementGenerator"""
        return self._statements.generate_assignment(stmt)

    def _generate_slice_assignment(self, stmt: SliceAssignment):
        """Generate slice assignment - delegated to StatementGenerator"""
        return self._statements.generate_slice_assignment(stmt)

    def _generate_return(self, stmt: ReturnStmt):
        """Generate return - delegated to StatementGenerator"""
        return self._statements.generate_return(stmt)

    def _generate_print(self, stmt: PrintStmt):
        """Generate print - delegated to StatementGenerator"""
        return self._statements.generate_print(stmt)

    def _generate_debug(self, stmt: DebugStmt):
        """Generate debug - delegated to StatementGenerator"""
        return self._statements.generate_debug(stmt)

    # NOTE: Old statement implementations below are now dead code.
    # The delegation methods above will be used. The old code remains temporarily.

    def _OLD_generate_var_decl(self, stmt: VarDecl):
        """Generate a local variable declaration or reassignment"""
        # Track whether this is a new variable for scope registration
        is_new_var = stmt.name not in self.locals

        # Formulas require const bindings for purity
        if not stmt.is_const and self.current_function is not None:
            if self.current_function.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32):
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

        # Track if we need to mark source as moved (see BUG-017)
        move_source_name = None

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
                # := operator creates independent deep copy, = shares pointer
                if stmt.is_copy:
                    init_value = self._generate_deep_copy(init_value, inferred_coex_type)
                else:
                    init_value = self._generate_move_or_eager_copy(init_value, inferred_coex_type)
                # Track the inferred type for this variable too
                self.var_coex_types[stmt.name] = inferred_coex_type
            elif isinstance(init_value.type, ir.PointerType):
                # Fallback for unknown collection types
                pointee = init_value.type.pointee
                if hasattr(pointee, 'name'):
                    if pointee.name == "struct.List":
                        init_value = self.builder.call(self.list_copy, [init_value])
                    elif pointee.name == "struct.Set":
                        init_value = self.builder.call(self.set_copy, [init_value])
                    elif pointee.name == "struct.Map":
                        init_value = self.builder.call(self.map_copy, [init_value])
                    elif pointee.name == "struct.String":
                        if stmt.is_copy:
                            init_value = self.builder.call(self.string_deep_copy, [init_value])
                        else:
                            init_value = self.builder.call(self.string_copy, [init_value])
                    elif pointee.name == "struct.Array":
                        if stmt.is_copy:
                            init_value = self.builder.call(self.array_deep_copy, [init_value])
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
                self.gc.set_root(self.builder, self.gc_frame, root_idx, init_value)

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

        # Special handling for atomic type initialization
        # Atomic types store values as i64, so we need to convert appropriately
        # This MUST happen BEFORE _cast_value to avoid wrong float->int conversion
        if isinstance(stmt.type_annotation, AtomicType):
            inner_type = stmt.type_annotation.inner
            if inner_type == "float":
                # Bitcast double to i64 (preserves bit representation)
                if isinstance(init_value.type, ir.DoubleType):
                    init_value = self.builder.bitcast(init_value, ir.IntType(64))
                elif isinstance(init_value.type, ir.IntType):
                    # If it's an int literal used as float, convert first
                    float_val = self.builder.sitofp(init_value, ir.DoubleType())
                    init_value = self.builder.bitcast(float_val, ir.IntType(64))
            elif inner_type == "bool":
                # Extend bool to i64
                if isinstance(init_value.type, ir.IntType) and init_value.type.width == 1:
                    init_value = self.builder.zext(init_value, ir.IntType(64))
                elif isinstance(init_value.type, ir.IntType):
                    # Non-zero is true
                    bool_val = self.builder.icmp_unsigned('!=', init_value, ir.Constant(init_value.type, 0))
                    init_value = self.builder.zext(bool_val, ir.IntType(64))
            elif inner_type == "int":
                # Ensure i64
                if isinstance(init_value.type, ir.IntType) and init_value.type.width != 64:
                    init_value = self.builder.sext(init_value, ir.IntType(64))
                elif isinstance(init_value.type, ir.DoubleType):
                    init_value = self.builder.fptosi(init_value, ir.IntType(64))
            # Skip normal cast for atomic types
        else:
            # Cast if needed (non-atomic types)
            init_value = self._cast_value(init_value, llvm_type)

        # Value semantics: deep copy or move collections on assignment
        # := (is_copy=True) creates independent deep copy
        # = (is_copy=False) shares pointer (move semantics for unique bindings)
        if self._is_collection_coex_type(stmt.type_annotation):
            if stmt.is_copy:
                # := operator: create truly independent deep copy
                init_value = self._generate_deep_copy(init_value, stmt.type_annotation)
            else:
                # = operator: share pointer (move semantics for unique, aliased for non-unique)
                init_value = self._generate_move_or_eager_copy(init_value, stmt.type_annotation)
        elif isinstance(init_value.type, ir.PointerType):
            # User-defined types may need deep copy too
            if isinstance(stmt.type_annotation, NamedType) and stmt.type_annotation.name in self.type_fields:
                if stmt.is_copy:
                    init_value = self._generate_deep_copy(init_value, stmt.type_annotation)
                else:
                    init_value = self._generate_move_or_eager_copy(init_value, stmt.type_annotation)

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
            self.gc.set_root(self.builder, self.gc_frame, root_idx, init_value)

        # Mark source as moved AFTER we've read its value
        if move_source_name:
            self.moved_vars.add(move_source_name)

    def _generate_var_reassignment(self, stmt: VarDecl):
        """Generate reassignment to an existing variable (x = value where x exists)"""
        # Get the existing alloca
        alloca = self.locals[stmt.name]

        # Track if we need to mark source as moved (see BUG-017)
        move_source_name = None

        # Generate the value
        value = self._generate_expression(stmt.initializer)

        # Get expected type from alloca
        expected_type = alloca.type.pointee

        # Cast if needed
        value = self._cast_value(value, expected_type)

        # Handle value semantics for collections
        # := (is_copy=True) creates independent deep copy
        # = (is_copy=False) shares pointer (move semantics)
        coex_type = self.var_coex_types.get(stmt.name)
        if coex_type and self._is_collection_coex_type(coex_type):
            if stmt.is_copy:
                # := operator: create truly independent deep copy
                value = self._generate_deep_copy(value, coex_type)
            else:
                # = operator: share pointer (move semantics for unique, aliased for non-unique)
                value = self._generate_move_or_eager_copy(value, coex_type)
        elif isinstance(value.type, ir.PointerType):
            # Fallback for struct types without Coex type info
            pointee = value.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    if stmt.is_copy:
                        value = self.builder.call(self.list_copy, [value])  # shallow copy for now
                elif pointee.name == "struct.Set":
                    if stmt.is_copy:
                        value = self.builder.call(self.set_copy, [value])
                elif pointee.name == "struct.Map":
                    if stmt.is_copy:
                        value = self.builder.call(self.map_copy, [value])
                elif pointee.name == "struct.String":
                    if stmt.is_copy:
                        value = self.builder.call(self.string_deep_copy, [value])
                elif pointee.name == "struct.Array":
                    if stmt.is_copy:
                        value = self.builder.call(self.array_deep_copy, [value])

        # Store the value
        self.builder.store(value, alloca)

        # Update GC root if needed
        if stmt.name in self.gc_root_indices and self.gc is not None:
            root_idx = self.gc_root_indices[stmt.name]
            self.gc.set_root(self.builder, self.gc_frame, root_idx, value)

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

        # Int to float (f64 or f32)
        if isinstance(value.type, ir.IntType) and isinstance(target_type, (ir.DoubleType, ir.FloatType)):
            return self.builder.sitofp(value, target_type)

        # Float to int (f64 or f32 to int)
        if isinstance(value.type, (ir.DoubleType, ir.FloatType)) and isinstance(target_type, ir.IntType):
            return self.builder.fptosi(value, target_type)

        # Float64 to float32
        if isinstance(value.type, ir.DoubleType) and isinstance(target_type, ir.FloatType):
            return self.builder.fptrunc(value, target_type)

        # Float32 to float64
        if isinstance(value.type, ir.FloatType) and isinstance(target_type, ir.DoubleType):
            return self.builder.fpext(value, target_type)

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
        if stmt.op == AssignOp.COPY_ASSIGN and isinstance(stmt.value, Identifier):
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

        # Handle compound assignment (not for COPY_ASSIGN or ASSIGN)
        if stmt.op not in (AssignOp.ASSIGN, AssignOp.COPY_ASSIGN):
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

        # Determine whether to use explicit copy (:=) or standard assignment (=)
        # := (is_copy=True) creates independent deep copy
        # = (is_copy=False) shares pointer (move semantics for unique, aliased for non-unique)
        is_copy = stmt.op == AssignOp.COPY_ASSIGN

        if coex_type and self._is_collection_coex_type(coex_type):
            if is_copy:
                # := operator: create truly independent deep copy
                value = self._generate_deep_copy(value, coex_type)
            else:
                # = operator: share pointer (move semantics for unique, aliased for non-unique)
                value = self._generate_move_or_eager_copy(value, coex_type)
        elif coex_type and isinstance(coex_type, NamedType) and coex_type.name in self.type_fields:
            # User-defined types need deep copy to handle collection fields
            if is_copy:
                value = self._generate_deep_copy(value, coex_type)
            else:
                value = self._generate_move_or_eager_copy(value, coex_type)
        elif isinstance(value.type, ir.PointerType):
            # Fallback for struct types without Coex type info
            # For := create deep copy, for = just share pointer (no copy)
            pointee = value.type.pointee
            if hasattr(pointee, 'name') and is_copy:
                if pointee.name == "struct.List":
                    value = self.builder.call(self.list_copy, [value])  # shallow copy for now
                elif pointee.name == "struct.Set":
                    value = self.builder.call(self.set_copy, [value])
                elif pointee.name == "struct.Map":
                    value = self.builder.call(self.map_copy, [value])
                elif pointee.name == "struct.String":
                    value = self.builder.call(self.string_deep_copy, [value])
                elif pointee.name == "struct.Array":
                    value = self.builder.call(self.array_deep_copy, [value])

        if ptr:
            self.builder.store(value, ptr)

            # Update GC root if this is a tracked heap variable being reassigned
            if isinstance(stmt.target, Identifier):
                target_name = stmt.target.name
                if target_name in self.gc_root_indices and self.gc is not None:
                    root_idx = self.gc_root_indices[target_name]
                    self.gc.set_root(self.builder, self.gc_frame, root_idx, value)

        # Mark source as moved AFTER we've read its value
        if move_source_name:
            self.moved_vars.add(move_source_name)

    def _generate_tuple_assignment(self, target: TupleExpr, value: ir.Value):
        """Generate tuple assignment - delegated to StatementGenerator"""
        return self._statements.generate_tuple_assignment(target, value)

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
        if op not in (AssignOp.ASSIGN, AssignOp.COPY_ASSIGN):
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
        raw_ptr = self.gc.alloc_arena_or_gc(self.builder, struct_size, type_id)
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
                    self.gc.set_root(self.builder, self.gc_frame, root_idx, new_struct)
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
                    self.gc.set_root(self.builder, self.gc_frame, root_idx, new_collection)

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
        """Generate a return statement - delegated to FlowControlGenerator"""
        return self._flow_control.generate_return(stmt)

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
        """Generate an if statement - delegated to FlowControlGenerator"""
        return self._flow_control.generate_if(stmt)

    def _to_bool(self, value: ir.Value) -> ir.Value:
        """Convert value to boolean (i1) - delegated to FlowControlGenerator"""
        return self._flow_control.to_bool(value)

    def _generate_while(self, stmt: WhileStmt):
        """Generate a while loop - delegated to FlowControlGenerator"""
        return self._flow_control.generate_while(stmt)

    def _generate_cycle(self, stmt: CycleStmt):
        """Generate a cycle block - delegated to FlowControlGenerator"""
        return self._flow_control.generate_cycle(stmt)

    def _find_cycle_declared_vars(self, stmts: PyList[Stmt]) -> Dict[str, Optional[Type]]:
        """Find cycle-declared vars - delegated to FlowControlGenerator"""
        return self._flow_control.find_cycle_declared_vars(stmts)

    def _in_cycle_context(self) -> bool:
        """Check if in cycle context - delegated to FlowControlGenerator"""
        return self._flow_control.in_cycle_context()

    def _get_cycle_context(self) -> Optional[Dict]:
        """Get cycle context - delegated to FlowControlGenerator"""
        return self._flow_control.get_cycle_context()

    # ========================================================================
    # Loop Nursery Support - moved to codegen/loops.py - LoopGenerator class
    # ========================================================================

    def _loop_needs_nursery(self, stmt: ForStmt) -> bool:
        return self._loops.loop_needs_nursery(stmt)

    def _has_collection_mutations(self, stmts: PyList[Stmt]) -> bool:
        return self._loops.has_collection_mutations(stmts)

    def _get_loop_carried_vars(self, stmt: ForStmt) -> PyList[str]:
        return self._loops.get_loop_carried_vars(stmt)

    def _collect_var_usage(self, stmts: PyList[Stmt], written: set, read: set):
        return self._loops.collect_var_usage(stmts, written, read)

    def _collect_expr_reads(self, expr: Expr, read: set):
        return self._loops.collect_expr_reads(expr, read)

    def _estimate_nursery_size(self, stmt: ForStmt, iteration_count: Optional[ir.Value]) -> ir.Value:
        return self._loops.estimate_nursery_size(stmt, iteration_count)

    def _copy_collection_to_main_heap(self, var_name: str, var_ptr: ir.Value, elem_type: ir.Type) -> ir.Value:
        return self._loops.copy_collection_to_main_heap(var_name, var_ptr, elem_type)

    def _generate_for(self, stmt: ForStmt):
        """Generate a for loop - delegated to LoopGenerator"""
        return self._loops.generate_for(stmt)

    def _generate_range_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in range(start, end) - delegated to LoopGenerator"""
        return self._loops.generate_range_for(stmt, use_nursery)

    def _generate_range_expr_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in start..end - delegated to LoopGenerator"""
        return self._loops.generate_range_expr_for(stmt, use_nursery)

    def _generate_list_for(self, stmt: ForStmt, list_ptr: ir.Value):
        """Generate for item in list - delegated to LoopGenerator"""
        return self._loops.generate_list_for(stmt, list_ptr)

    def _generate_array_for(self, stmt: ForStmt, array_ptr: ir.Value):
        """Generate for item in array - delegated to LoopGenerator"""
        return self._loops.generate_array_for(stmt, array_ptr)

    def _generate_map_for(self, stmt: ForStmt, map_ptr: ir.Value):
        """Generate for key in map - delegated to LoopGenerator"""
        return self._loops.generate_map_for(stmt, map_ptr)

    def _generate_set_for(self, stmt: ForStmt, set_ptr: ir.Value):
        """Generate for elem in set - delegated to LoopGenerator"""
        return self._loops.generate_set_for(stmt, set_ptr)

    def _generate_for_assign(self, stmt: ForAssignStmt):
        """Generate results = for item in items expr - delegated to LoopGenerator

        Attempts GPU offload first if body is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(stmt, self)
        if result is not None and result.handled:
            return result.value
        return self._loops.generate_for_assign(stmt)

    def _generate_first_assign(self, stmt):
        """Generate result = first item in items expr - delegated to LoopGenerator

        Returns first successful result, cancels remaining tasks.
        Attempts GPU offload first if predicate is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(stmt, self)
        if result is not None and result.handled:
            return result.value
        return self._loops.generate_first_assign(stmt)

    def _generate_most_assign(self, stmt):
        """Generate (results, errors) = most item in items expr - delegated to LoopGenerator

        Returns tuple of (successful_results, errors), no cancellation.
        Attempts GPU offload first if body is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(stmt, self)
        if result is not None and result.handled:
            return result.value
        return self._loops.generate_most_assign(stmt)

    def _generate_break(self):
        """Generate a break statement - delegated to FlowControlGenerator"""
        return self._flow_control.generate_break()

    def _generate_continue(self):
        """Generate a continue statement - delegated to FlowControlGenerator"""
        return self._flow_control.generate_continue()

    def _generate_match(self, stmt: MatchStmt):
        """Generate a match statement - delegated to FlowControlGenerator"""
        return self._flow_control.generate_match(stmt)

    def _generate_pattern_match(self, subject: ir.Value, pattern: Pattern) -> ir.Value:
        """Generate pattern match - delegated to FlowControlGenerator"""
        return self._flow_control.generate_pattern_match(subject, pattern)

    # ========================================================================
    # Expression Generation - delegated to ExpressionGenerator
    # ========================================================================

    def _generate_expression(self, expr: Expr) -> ir.Value:
        """Generate code for an expression - delegated to ExpressionGenerator"""
        return self._expressions.generate_expression(expr)

    # The following expression methods are kept for backwards compatibility
    # and are delegated to the ExpressionGenerator

    def _generate_identifier(self, expr: Identifier) -> ir.Value:
        """Generate code for identifier - delegated to ExpressionGenerator"""
        return self._expressions.generate_identifier(expr)

    def _generate_binary(self, expr: BinaryExpr) -> ir.Value:
        """Generate code for binary expression - delegated to ExpressionGenerator"""
        return self._expressions.generate_binary(expr)

    def _generate_unary(self, expr: UnaryExpr) -> ir.Value:
        """Generate code for unary expression - delegated to ExpressionGenerator"""
        return self._expressions.generate_unary(expr)

    def _generate_call(self, expr: CallExpr) -> ir.Value:
        """Generate code for function call - delegated to ExpressionGenerator"""
        return self._expressions.generate_call(expr)

    def _generate_method_call(self, expr: MethodCallExpr) -> ir.Value:
        """Generate code for method call - delegated to ExpressionGenerator"""
        return self._expressions.generate_method_call(expr)

    def _generate_member(self, expr: MemberExpr) -> ir.Value:
        """Generate code for member access - delegated to ExpressionGenerator"""
        return self._expressions.generate_member(expr)

    def _generate_index(self, expr: IndexExpr) -> ir.Value:
        """Generate code for index access - delegated to ExpressionGenerator"""
        return self._expressions.generate_index(expr)

    def _generate_slice(self, expr: SliceExpr) -> ir.Value:
        """Generate code for slice access - delegated to ExpressionGenerator"""
        return self._expressions.generate_slice(expr)

    def _generate_ternary(self, expr: TernaryExpr) -> ir.Value:
        """Generate code for ternary expression - delegated to ExpressionGenerator"""
        return self._expressions.generate_ternary(expr)

    def _generate_list(self, expr: ListExpr) -> ir.Value:
        """Generate code for list literal - delegated to ExpressionGenerator"""
        return self._expressions.generate_list(expr)

    def _generate_map(self, expr: MapExpr) -> ir.Value:
        """Generate code for map literal - delegated to ExpressionGenerator"""
        return self._expressions.generate_map(expr)

    def _generate_set(self, expr: SetExpr) -> ir.Value:
        """Generate code for set literal - delegated to ExpressionGenerator"""
        return self._expressions.generate_set(expr)

    def _generate_tuple(self, expr: TupleExpr) -> ir.Value:
        """Generate code for tuple literal - delegated to ExpressionGenerator"""
        return self._expressions.generate_tuple(expr)

    def _generate_range(self, expr: RangeExpr) -> ir.Value:
        """Generate code for range expression - delegated to ExpressionGenerator"""
        return self._expressions.generate_range(expr)

    def _bind_pattern(self, pattern, value):
        """Bind pattern variables - delegated to ExpressionGenerator"""
        return self._expressions.bind_pattern(pattern, value)

    # ========================================================================
    # Constructor Methods (kept in core.py, called from expressions.py)
    # ========================================================================

    def _generate_array_constructor(self, args: PyList['Expr']) -> ir.Value:
        """Generate code for Array(capacity, initial_value) constructor.

        Creates an Array with the given capacity, initialized with the given value.

        N-D Array struct layout:
            Field 0: handle (i64) - GC handle for data buffer
            Field 1: ndim (i64) - number of dimensions
            Field 2: shape [4 x i64] - dimensions
            Field 3: strides [4 x i64] - byte strides
            Field 4: offset (i64) - byte offset for views
            Field 5: elem_size (i64) - element size
            Field 6: type_id (i64) - element type
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
        # array_new now sets shape[0] = capacity automatically
        array_ptr = self.builder.call(self.array_new, [capacity, elem_size])

        # Fill the array with the initial value
        # Get data pointer: compute handle + offset
        # Field 0: handle, Field 4: offset
        handle_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        handle_val = self.builder.load(handle_ptr)
        base_ptr = self.builder.inttoptr(handle_val, ir.IntType(8).as_pointer())
        offset_ptr = self.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        offset_val = self.builder.load(offset_ptr)
        data_ptr = self.builder.gep(base_ptr, [offset_val])

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
        raw_ptr = self.gc.alloc_arena_or_gc(self.builder, size_val, type_id)
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

        if type_name == "Channel":
            # Create new channel using runtime function
            return self._channel.generate_channel_new(None, self.builder)

        if type_name == "atomic_ref":
            # atomic_ref.new(value) or atomic_ref.new() for nil
            if args:
                initial = self._generate_expression(args[0])
                initial = self._cast_value(initial, ir.IntType(64))
            else:
                initial = ir.Constant(ir.IntType(64), 0)  # nil
            return self.builder.call(self.atomic_ref_new, [initial])

        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]

        # Allocate via GC
        size = len(field_info) * 8 if field_info else 8  # Simplified size calculation
        size_val = ir.Constant(ir.IntType(64), size)
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id(type_name))

        raw_ptr = self.gc.alloc_arena_or_gc(self.builder, size_val, type_id)
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
        """Find enum variant - delegated to EnumGenerator"""
        return self._enums.find_enum_variant(variant_name)

    def _generate_enum_constructor(self, enum_name: str, variant_name: str,
                                    args: PyList[Expr], named_args: Dict[str, Expr]) -> ir.Value:
        """Generate enum constructor - delegated to EnumGenerator"""
        return self._enums.generate_enum_constructor(enum_name, variant_name, args, named_args)

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

        # Handle atomic primitive methods (atomic_int, atomic_float, atomic_bool)
        # Check if the object is an atomic type variable
        atomic_inner_type = None
        atomic_ptr = None
        if isinstance(expr.object, Identifier):
            var_name = expr.object.name
            if var_name in self.var_coex_types:
                coex_type = self.var_coex_types[var_name]
                if isinstance(coex_type, AtomicType):
                    atomic_inner_type = coex_type.inner
                    # Get the pointer to the atomic variable (not the loaded value)
                    if var_name in self.locals:
                        atomic_ptr = self.locals[var_name]

        if atomic_ptr is not None and atomic_inner_type is not None:
            # Atomic primitive method dispatch
            if method == "load":
                return self._atomic_primitives.generate_atomic_load(
                    self.builder, atomic_ptr, atomic_inner_type)

            elif method == "store":
                if expr.args:
                    value = self._generate_expression(expr.args[0])
                    return self._atomic_primitives.generate_atomic_store(
                        self.builder, atomic_ptr, value, atomic_inner_type)
                return ir.Constant(ir.IntType(64), 0)

            elif method == "exchange":
                if expr.args:
                    new_value = self._generate_expression(expr.args[0])
                    return self._atomic_primitives.generate_atomic_exchange(
                        self.builder, atomic_ptr, new_value, atomic_inner_type)
                return ir.Constant(ir.IntType(64), 0)

            elif method == "compare_and_swap" or method == "cas":
                if len(expr.args) >= 2:
                    expected = self._generate_expression(expr.args[0])
                    new_value = self._generate_expression(expr.args[1])
                    return self._atomic_primitives.generate_atomic_cas(
                        self.builder, atomic_ptr, expected, new_value, atomic_inner_type)
                return ir.Constant(ir.IntType(1), 0)

            elif method == "fetch_add" and atomic_inner_type == "int":
                if expr.args:
                    delta = self._generate_expression(expr.args[0])
                    return self._atomic_primitives.generate_fetch_add(
                        self.builder, atomic_ptr, delta)
                return ir.Constant(ir.IntType(64), 0)

            elif method == "fetch_sub" and atomic_inner_type == "int":
                if expr.args:
                    delta = self._generate_expression(expr.args[0])
                    return self._atomic_primitives.generate_fetch_sub(
                        self.builder, atomic_ptr, delta)
                return ir.Constant(ir.IntType(64), 0)

            elif method == "increment" and atomic_inner_type == "int":
                return self._atomic_primitives.generate_increment(
                    self.builder, atomic_ptr)

            elif method == "decrement" and atomic_inner_type == "int":
                return self._atomic_primitives.generate_decrement(
                    self.builder, atomic_ptr)

            elif method == "test_and_set" and atomic_inner_type == "bool":
                return self._atomic_primitives.generate_test_and_set(
                    self.builder, atomic_ptr)

        # Legacy stubs for non-atomic types (should not normally be reached)
        if method == "load":
            return obj

        if method == "store":
            return ir.Constant(ir.IntType(64), 0)

        if method == "increment":
            if isinstance(obj.type, ir.IntType):
                return obj
            return ir.Constant(ir.IntType(64), 0)

        if method == "fetch_add":
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

        return ir.Constant(ir.IntType(64), 0)

    def _get_tuple_field_info(self, expr: Expr) -> Optional[PyList[tuple]]:
        """Get tuple field info - delegated to ExpressionGenerator"""
        return self._expressions.get_tuple_field_info(expr)

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

    # JSON methods delegated to JsonGenerator (see codegen/json_type.py)
    def _generate_json_object(self, expr: 'JsonObjectExpr') -> ir.Value:
        return self._json.generate_json_object(expr)

    def _generate_as_expr(self, expr: 'AsExpr') -> ir.Value:
        return self._json.generate_as_expr(expr)

    def _convert_to_json(self, value: ir.Value, expr: 'Expr') -> ir.Value:
        return self._json.convert_to_json(value, expr)

    def _generate_list_comprehension(self, expr: ListComprehension) -> ir.Value:
        """Generate code for list comprehension - delegated to ComprehensionGenerator

        Attempts GPU offload first if body is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(expr, self)
        if result is not None and result.handled:
            return result.value
        return self._comprehensions.generate_list_comprehension(expr)

    def _generate_set_comprehension(self, expr: SetComprehension) -> ir.Value:
        """Generate code for set comprehension - delegated to ComprehensionGenerator

        Attempts GPU offload first if body is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(expr, self)
        if result is not None and result.handled:
            return result.value
        return self._comprehensions.generate_set_comprehension(expr)

    def _generate_map_comprehension(self, expr: MapComprehension) -> ir.Value:
        """Generate code for map comprehension - delegated to ComprehensionGenerator

        Attempts GPU offload first if body is a formula expression.
        """
        # Try GPU offload for formula-based operations
        result = try_offload(expr, self)
        if result is not None and result.handled:
            return result.value
        return self._comprehensions.generate_map_comprehension(expr)

    def _generate_lambda(self, expr: 'LambdaExpr') -> ir.Value:
        """Generate code for lambda expression - delegated to FunctionGenerator"""
        return self._functions.generate_lambda(expr)

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
        """Infer the element type of a list expression - delegated to LoopGenerator"""
        return self._loops.infer_list_element_type(expr)

    def _get_list_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for list elements - delegated to LoopGenerator"""
        return self._loops.get_list_element_type_for_pattern(stmt)

    def _get_list_element_coex_type(self, stmt: ForStmt) -> Optional[Type]:
        """Get the Coex AST type for list elements - delegated to LoopGenerator"""
        return self._loops.get_list_element_coex_type(stmt)

    def _get_array_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for array elements - delegated to LoopGenerator"""
        return self._loops.get_array_element_type_for_pattern(stmt)

    # ========================================================================
    # Compilation
    # ========================================================================

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

        This is used to pre-allocate local variables to prevent stack
        overflow from allocas inside loops.
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

    def compile_to_object(self, output_path: str, opt_level: int = 3):
        """Compile module to object file with LLVM optimizations.

        Args:
            output_path: Path to write the object file
            opt_level: Optimization level (0-3, default 3 for -O3)
        """
        llvm_ir = str(self.module)
        llvm_ir = self._inject_inline_ir(llvm_ir)  # Inject inline LLVM IR
        try:
            mod = binding.parse_assembly(llvm_ir)
            mod.verify()
        except Exception as e:
            raise RuntimeError(f"LLVM IR error (possibly in inline IR): {e}")

        # Apply LLVM optimization passes
        if opt_level > 0:
            # Check for new pass manager API (llvmlite >= 0.45 with LLVM 20)
            if hasattr(binding, 'PipelineTuningOptions'):
                # New API - use PassBuilder with PipelineTuningOptions
                target = binding.Target.from_default_triple()
                tm = target.create_target_machine()

                # Create tuning options with speed optimization
                pto = binding.PipelineTuningOptions(speed_level=opt_level, size_level=0)

                # Create pass builder and get module pass manager
                pb = binding.PassBuilder(tm, pto)
                pm = pb.getModulePassManager()

                # Run optimization passes
                pm.run(mod, pb)
            elif hasattr(binding, 'PassManagerBuilder'):
                # Legacy API (llvmlite < 0.45)
                pmb = binding.PassManagerBuilder()
                pmb.opt_level = opt_level

                # Enable loop vectorization and SLP vectorization at -O2 and above
                if opt_level >= 2:
                    pmb.loop_vectorize = True
                    pmb.slp_vectorize = True

                # Create and populate module pass manager
                pm = binding.ModulePassManager()
                pmb.populate(pm)

                # Run optimization passes
                pm.run(mod)
            else:
                # Neither API available - skip optimization (should not happen)
                pass

        # Create target machine with appropriate optimization settings
        target = binding.Target.from_default_triple()

        # Use optimization level for code generation too
        if opt_level == 0:
            code_opt = 0
        elif opt_level == 1:
            code_opt = 1
        else:
            code_opt = 2  # LLVM codegen only supports 0, 1, 2

        target_machine = target.create_target_machine(opt=code_opt)

        with open(output_path, "wb") as f:
            f.write(target_machine.emit_object(mod))

    def get_ir(self) -> str:
        """Get LLVM IR as string"""
        raw_ir = str(self.module)
        return self._inject_inline_ir(raw_ir)
