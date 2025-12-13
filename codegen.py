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
        self.globals: Dict[str, ir.GlobalVariable] = {}
        self.locals: Dict[str, ir.AllocaInst] = {}
        self.functions: Dict[str, ir.Function] = {}
        
        # Type registry for user-defined types
        self.type_registry: Dict[str, ir.Type] = {}  # type_name -> LLVM struct type (not pointer)
        self.type_fields: Dict[str, PyList[Tuple[str, Type]]] = {}  # type_name -> [(field_name, coex_type)]
        self.type_methods: Dict[str, Dict[str, str]] = {}  # type_name -> {method_name -> mangled_func_name}
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
        
        # Current function for context
        self.current_function: Optional[FunctionDecl] = None
        self.current_type: Optional[str] = None  # For method generation
        
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
        
        # List and channel runtime support
        self.list_type = None
        self.channel_type = None

        # Module system support
        self.loaded_modules: Dict[str, ModuleInfo] = {}  # module_name -> ModuleInfo
        self.replace_aliases: Dict[str, Tuple[str, str]] = {}  # shortname -> (module, func_name)
        self.module_search_paths: PyList[str] = []
        self.current_module: Optional[str] = None  # Track which module we're compiling

        # Inline LLVM IR support
        self._pending_inline_ir: PyList[Dict] = []  # Pending IR to inject during serialization
        self._inline_ir_counter = 0  # Counter for unique stub function names

        # Garbage collector (initialized after module creation, before builtins)
        self.gc: Optional[GarbageCollector] = None

        # Declare external functions
        self._declare_builtins()
    
    def _declare_builtins(self):
        """Declare built-in functions"""
        # printf
        printf_ty = ir.FunctionType(ir.IntType(32), [ir.IntType(8).as_pointer()], var_arg=True)
        self.printf = ir.Function(self.module, printf_ty, name="printf")
        
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
        
        # Create list struct type
        # struct List { i64 len, i64 cap, i64 elem_size, i8* data }
        self.list_struct = ir.global_context.get_identified_type("struct.List")
        self.list_struct.set_body(
            ir.IntType(64),  # len
            ir.IntType(64),  # cap
            ir.IntType(64),  # elem_size
            ir.IntType(8).as_pointer()  # data
        )
        
        # Create list helper functions
        self._create_list_helpers()
        
        # Create String type and helpers
        self._create_string_type()
        
        # Create Map type and helpers
        self._create_map_type()
        
        # Create Set type and helpers
        self._create_set_type()

        # Create Array type and helpers (dense, contiguous collection)
        # struct Array { i64 len, i64 cap, i64 elem_size, i8* data }
        self.array_struct = ir.global_context.get_identified_type("struct.Array")
        self.array_struct.set_body(
            ir.IntType(64),  # len
            ir.IntType(64),  # cap
            ir.IntType(64),  # elem_size
            ir.IntType(8).as_pointer()  # data
        )
        self._create_array_helpers()

        # Create atomic_ref type and helpers
        self._create_atomic_ref_type()
        
        # Create channel struct type (simple queue implementation)
        # struct Channel { i64 len, i64 cap, i64 head, i64 tail, i8* data, i1 closed }
        self.channel_struct = ir.global_context.get_identified_type("struct.Channel")
        self.channel_struct.set_body(
            ir.IntType(64),  # len
            ir.IntType(64),  # cap
            ir.IntType(64),  # head
            ir.IntType(64),  # tail
            ir.IntType(8).as_pointer(),  # data
            ir.IntType(1)    # closed
        )
        
        # Create channel helper functions
        self._create_channel_helpers()
        
        # Matrix registry for tracking declared matrices
        self.matrix_decls: Dict[str, 'MatrixDecl'] = {}  # name -> MatrixDecl
        self.matrix_structs: Dict[str, ir.Type] = {}  # name -> LLVM struct type
        
        # Current matrix context for cell expressions
        self.current_matrix: Optional[str] = None
        self.current_cell_x: Optional[ir.Value] = None
        self.current_cell_y: Optional[ir.Value] = None

    def _create_list_helpers(self):
        """Create helper functions for list operations"""
        list_ptr = self.list_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        
        # list_new(elem_size: i64) -> List*
        list_new_ty = ir.FunctionType(list_ptr, [i64])
        self.list_new = ir.Function(self.module, list_new_ty, name="coex_list_new")
        
        # list_append(list: List*, elem: i8*, elem_size: i64)
        list_append_ty = ir.FunctionType(ir.VoidType(), [list_ptr, i8_ptr, i64])
        self.list_append = ir.Function(self.module, list_append_ty, name="coex_list_append")
        
        # list_get(list: List*, index: i64) -> i8*
        list_get_ty = ir.FunctionType(i8_ptr, [list_ptr, i64])
        self.list_get = ir.Function(self.module, list_get_ty, name="coex_list_get")
        
        # list_len(list: List*) -> i64
        list_len_ty = ir.FunctionType(i64, [list_ptr])
        self.list_len = ir.Function(self.module, list_len_ty, name="coex_list_len")

        # list_size(list: List*) -> i64 (total memory footprint in bytes)
        list_size_ty = ir.FunctionType(i64, [list_ptr])
        self.list_size = ir.Function(self.module, list_size_ty, name="coex_list_size")

        # Now implement these functions inline
        self._implement_list_new()
        self._implement_list_append()
        self._implement_list_get()
        self._implement_list_len()
        self._implement_list_size()
        self._register_list_methods()
    
    def _implement_list_new(self):
        """Implement list_new: allocate a new list with given element size"""
        func = self.list_new
        func.args[0].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Allocate List struct (4 * 8 = 32 bytes) via GC
        list_size = ir.Constant(ir.IntType(64), 32)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_LIST)
        raw_ptr = builder.call(self.gc.gc_alloc, [list_size, type_id])
        list_ptr = builder.bitcast(raw_ptr, self.list_struct.as_pointer())
        
        # Initialize fields
        # len = 0
        len_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_ptr)
        
        # cap = 8 (initial capacity)
        cap_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 8), cap_ptr)
        
        # elem_size
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(func.args[0], elem_size_ptr)
        
        # Allocate data: 8 elements * elem_size
        data_size = builder.mul(ir.Constant(ir.IntType(64), 8), func.args[0])
        data_ptr = builder.call(self.malloc, [data_size])
        data_field_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        builder.store(data_ptr, data_field_ptr)
        
        builder.ret(list_ptr)
    
    def _implement_list_append(self):
        """Implement list_append: add element to list, grow if needed"""
        func = self.list_append
        func.args[0].name = "list"
        func.args[1].name = "elem"
        func.args[2].name = "elem_size"
        
        entry = func.append_basic_block("entry")
        check_grow = func.append_basic_block("check_grow")
        do_grow = func.append_basic_block("do_grow")
        do_append = func.append_basic_block("do_append")
        
        builder = ir.IRBuilder(entry)
        list_ptr = func.args[0]
        elem_ptr = func.args[1]
        elem_size = func.args[2]
        
        # Load len and cap
        len_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        length = builder.load(len_ptr)
        
        cap_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        cap = builder.load(cap_ptr)
        
        builder.branch(check_grow)
        
        # Check if we need to grow
        builder.position_at_end(check_grow)
        need_grow = builder.icmp_signed(">=", length, cap)
        builder.cbranch(need_grow, do_grow, do_append)
        
        # Grow the array (double capacity)
        builder.position_at_end(do_grow)
        new_cap = builder.mul(cap, ir.Constant(ir.IntType(64), 2))
        builder.store(new_cap, cap_ptr)
        
        # Allocate new data
        new_size = builder.mul(new_cap, elem_size)
        new_data = builder.call(self.malloc, [new_size])
        
        # Copy old data
        data_field_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        old_data = builder.load(data_field_ptr)
        old_size = builder.mul(length, elem_size)
        builder.call(self.memcpy, [new_data, old_data, old_size])
        
        # Free old data and store new
        builder.call(self.free, [old_data])
        builder.store(new_data, data_field_ptr)
        builder.branch(do_append)
        
        # Append element
        builder.position_at_end(do_append)
        # Reload data pointer (might have changed)
        data_field_ptr2 = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        data = builder.load(data_field_ptr2)
        
        # Reload length (use phi or just reload)
        len_ptr2 = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        current_len = builder.load(len_ptr2)
        
        # Calculate offset: len * elem_size
        offset = builder.mul(current_len, elem_size)
        dest = builder.gep(data, [offset])
        
        # Copy element
        builder.call(self.memcpy, [dest, elem_ptr, elem_size])
        
        # Increment length
        new_len = builder.add(current_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_ptr2)
        
        builder.ret_void()
    
    def _implement_list_get(self):
        """Implement list_get: return pointer to element at index"""
        func = self.list_get
        func.args[0].name = "list"
        func.args[1].name = "index"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        list_ptr = func.args[0]
        index = func.args[1]
        
        # Get elem_size
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)
        
        # Get data pointer
        data_field_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        data = builder.load(data_field_ptr)
        
        # Calculate offset: index * elem_size
        offset = builder.mul(index, elem_size)
        result = builder.gep(data, [offset])
        
        builder.ret(result)
    
    def _implement_list_len(self):
        """Implement list_len: return list length"""
        func = self.list_len
        func.args[0].name = "list"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        list_ptr = func.args[0]
        
        # Get len field
        len_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        length = builder.load(len_ptr)
        
        builder.ret(length)

    def _implement_list_size(self):
        """Implement list_size: return total memory footprint in bytes.

        Size = 32 (header) + cap * elem_size (data array)
        """
        func = self.list_size
        func.args[0].name = "list"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        list_ptr = func.args[0]

        # Get cap field (field 1)
        cap_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Get elem_size field (field 2)
        elem_size_ptr = builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Size = 32 (header) + cap * elem_size
        data_size = builder.mul(cap, elem_size)
        total_size = builder.add(ir.Constant(ir.IntType(64), 32), data_size)

        builder.ret(total_size)

    def _register_list_methods(self):
        """Register List as a type with methods."""
        self.type_registry["List"] = self.list_struct
        self.type_fields["List"] = []  # Internal structure, not user-accessible fields

        self.type_methods["List"] = {
            "get": "coex_list_get",
            # "append" handled specially in _generate_method_call (needs alloca for element)
            "len": "coex_list_len",
            "size": "coex_list_size",
        }
        
        self.functions["coex_list_new"] = self.list_new
        self.functions["coex_list_get"] = self.list_get
        self.functions["coex_list_append"] = self.list_append
        self.functions["coex_list_len"] = self.list_len
        self.functions["coex_list_size"] = self.list_size

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

        # Implement all functions
        self._implement_array_new()
        self._implement_array_get()
        self._implement_array_set()
        self._implement_array_append()
        self._implement_array_len()
        self._implement_array_size()
        self._register_array_methods()

    def _implement_array_new(self):
        """Implement array_new: allocate a new array with given capacity and element size."""
        func = self.array_new
        func.args[0].name = "cap"
        func.args[1].name = "elem_size"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        cap = func.args[0]
        elem_size = func.args[1]

        # Allocate Array struct (32 bytes) via GC
        array_size_const = ir.Constant(ir.IntType(64), 32)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_ARRAY)
        raw_ptr = builder.call(self.gc.gc_alloc, [array_size_const, type_id])
        array_ptr = builder.bitcast(raw_ptr, self.array_struct.as_pointer())

        # Initialize fields
        # len = 0
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_ptr)

        # cap
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(cap, cap_ptr)

        # elem_size
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(elem_size, elem_size_ptr)

        # Allocate data: cap * elem_size
        data_size = builder.mul(cap, elem_size)
        data_ptr = builder.call(self.malloc, [data_size])
        data_field_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        builder.store(data_ptr, data_field_ptr)

        builder.ret(array_ptr)

    def _implement_array_get(self):
        """Implement array_get: return pointer to element at index."""
        func = self.array_get
        func.args[0].name = "arr"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]
        index = func.args[1]

        # Get elem_size
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Get data pointer
        data_field_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        data = builder.load(data_field_ptr)

        # Calculate offset: index * elem_size
        offset = builder.mul(index, elem_size)
        result = builder.gep(data, [offset])

        builder.ret(result)

    def _implement_array_set(self):
        """Implement array_set: return a NEW array with element at index replaced.

        This implements value semantics - original array is unchanged.
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

        # Get old array's len and cap
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        old_cap_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_cap = builder.load(old_cap_ptr)

        # Create new array with same capacity
        new_arr = builder.call(self.array_new, [old_cap, elem_size])

        # Set new array's len to old len
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(old_len, new_len_ptr)

        # Copy all data from old to new
        old_data_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        old_data = builder.load(old_data_ptr)

        new_data_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        new_data = builder.load(new_data_ptr)

        copy_size = builder.mul(old_len, elem_size)
        builder.call(self.memcpy, [new_data, old_data, copy_size])

        # Overwrite the element at index
        offset = builder.mul(index, elem_size)
        dest = builder.gep(new_data, [offset])
        builder.call(self.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_append(self):
        """Implement array_append: return a NEW array with element appended.

        This implements value semantics - original array is unchanged.
        New array has capacity = old_len + 1.
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

        # Get old array's len
        old_len_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_len = builder.load(old_len_ptr)

        # New capacity = old_len + 1
        new_cap = builder.add(old_len, ir.Constant(ir.IntType(64), 1))

        # Create new array
        new_arr = builder.call(self.array_new, [new_cap, elem_size])

        # Set new array's len = old_len + 1
        new_len_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(new_cap, new_len_ptr)

        # Copy old data to new
        old_data_ptr = builder.gep(old_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        old_data = builder.load(old_data_ptr)

        new_data_ptr = builder.gep(new_arr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        new_data = builder.load(new_data_ptr)

        copy_size = builder.mul(old_len, elem_size)
        builder.call(self.memcpy, [new_data, old_data, copy_size])

        # Append the new element
        offset = builder.mul(old_len, elem_size)
        dest = builder.gep(new_data, [offset])
        builder.call(self.memcpy, [dest, value_ptr, elem_size])

        builder.ret(new_arr)

    def _implement_array_len(self):
        """Implement array_len: return array length."""
        func = self.array_len
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get len field
        len_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        length = builder.load(len_ptr)

        builder.ret(length)

    def _implement_array_size(self):
        """Implement array_size: return total memory footprint in bytes.

        Size = 32 (header) + cap * elem_size (data array)
        """
        func = self.array_size
        func.args[0].name = "arr"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        array_ptr = func.args[0]

        # Get cap field (field 1)
        cap_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Get elem_size field (field 2)
        elem_size_ptr = builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = builder.load(elem_size_ptr)

        # Size = 32 (header) + cap * elem_size
        data_size = builder.mul(cap, elem_size)
        total_size = builder.add(ir.Constant(ir.IntType(64), 32), data_size)

        builder.ret(total_size)

    def _register_array_methods(self):
        """Register Array as a type with methods."""
        self.type_registry["Array"] = self.array_struct
        self.type_fields["Array"] = []  # Internal structure, not user-accessible fields

        self.type_methods["Array"] = {
            "get": "coex_array_get",
            "len": "coex_array_len",
            "size": "coex_array_size",
            # "set" and "append" handled specially (need alloca + return new array)
        }

        self.functions["coex_array_new"] = self.array_new
        self.functions["coex_array_get"] = self.array_get
        self.functions["coex_array_set"] = self.array_set
        self.functions["coex_array_append"] = self.array_append
        self.functions["coex_array_len"] = self.array_len
        self.functions["coex_array_size"] = self.array_size

    def _list_to_array(self, list_ptr: ir.Value) -> ir.Value:
        """Convert a List to an Array (List.packed() -> Array).

        Creates a new Array with the same elements as the List.
        """
        func = self.builder.function
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get List length
        list_len = self.builder.call(self.list_len, [list_ptr])

        # Get List elem_size (field 2)
        elem_size_ptr = self.builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = self.builder.load(elem_size_ptr)

        # Create new Array with same capacity as List length
        array_ptr = self.builder.call(self.array_new, [list_len, elem_size])

        # Set Array len = list_len
        array_len_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        self.builder.store(list_len, array_len_ptr)

        # Get data pointers
        list_data_ptr = self.builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        list_data = self.builder.load(list_data_ptr)

        array_data_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        array_data = self.builder.load(array_data_ptr)

        # Copy all data: memcpy(array_data, list_data, list_len * elem_size)
        copy_size = self.builder.mul(list_len, elem_size)
        self.builder.call(self.memcpy, [array_data, list_data, copy_size])

        return array_ptr

    def _set_to_array(self, set_ptr: ir.Value) -> ir.Value:
        """Convert a Set to an Array (Set.packed() -> Array).

        Creates a new Array with the occupied elements from the Set.
        Elements are stored in iteration order (arbitrary).
        """
        func = self.builder.function
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get Set len (number of elements)
        set_len = self.builder.call(self.set_len, [set_ptr])

        # Create Array with capacity = set_len, elem_size = 8 (i64 keys)
        elem_size = ir.Constant(i64, 8)
        array_ptr = self.builder.call(self.array_new, [set_len, elem_size])

        # We need to iterate over Set entries and copy occupied ones to Array
        # This requires a loop - for simplicity, use basic blocks

        # Get set capacity and entries pointer
        set_cap_ptr = self.builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        set_cap = self.builder.load(set_cap_ptr)

        set_entries_ptr = self.builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        set_entries = self.builder.load(set_entries_ptr)

        array_data_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        array_data = self.builder.load(array_data_ptr)

        # Loop variables
        idx_alloca = self.builder.alloca(i64, name="set_idx")
        self.builder.store(ir.Constant(i64, 0), idx_alloca)

        arr_idx_alloca = self.builder.alloca(i64, name="arr_idx")
        self.builder.store(ir.Constant(i64, 0), arr_idx_alloca)

        # Loop blocks
        cond_block = func.append_basic_block("set_to_arr_cond")
        body_block = func.append_basic_block("set_to_arr_body")
        inc_block = func.append_basic_block("set_to_arr_inc")
        exit_block = func.append_basic_block("set_to_arr_exit")

        self.builder.branch(cond_block)

        # Condition: idx < set_cap
        self.builder.position_at_end(cond_block)
        idx = self.builder.load(idx_alloca)
        cond = self.builder.icmp_signed("<", idx, set_cap)
        self.builder.cbranch(cond, body_block, exit_block)

        # Body: check if entry is occupied, if so copy to array
        self.builder.position_at_end(body_block)
        idx = self.builder.load(idx_alloca)

        # Get entry state (offset 8 in SetEntry: { i64 key, i8 state })
        entry_ptr = self.builder.gep(set_entries, [idx], inbounds=True)
        state_ptr = self.builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        state = self.builder.load(state_ptr)

        # Check if state == 1 (occupied)
        is_occupied = self.builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))

        copy_block = func.append_basic_block("set_to_arr_copy")
        skip_block = func.append_basic_block("set_to_arr_skip")
        self.builder.cbranch(is_occupied, copy_block, skip_block)

        # Copy block: copy key to array
        self.builder.position_at_end(copy_block)
        key_ptr = self.builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        key_val = self.builder.load(key_ptr)

        arr_idx = self.builder.load(arr_idx_alloca)
        offset = self.builder.mul(arr_idx, elem_size)
        dest_ptr = self.builder.gep(array_data, [offset])
        dest_typed = self.builder.bitcast(dest_ptr, i64.as_pointer())
        self.builder.store(key_val, dest_typed)

        # Increment array index
        new_arr_idx = self.builder.add(arr_idx, ir.Constant(i64, 1))
        self.builder.store(new_arr_idx, arr_idx_alloca)
        self.builder.branch(skip_block)

        # Skip/continue to increment
        self.builder.position_at_end(skip_block)
        self.builder.branch(inc_block)

        # Increment set index
        self.builder.position_at_end(inc_block)
        idx = self.builder.load(idx_alloca)
        next_idx = self.builder.add(idx, ir.Constant(i64, 1))
        self.builder.store(next_idx, idx_alloca)
        self.builder.branch(cond_block)

        # Exit: set array len
        self.builder.position_at_end(exit_block)
        final_arr_idx = self.builder.load(arr_idx_alloca)
        arr_len_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        self.builder.store(final_arr_idx, arr_len_ptr)

        return array_ptr

    def _array_to_list(self, array_ptr: ir.Value) -> ir.Value:
        """Convert an Array to a List (Array.unpacked() -> List).

        Creates a new List with the same elements as the Array.
        """
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get Array length
        array_len = self.builder.call(self.array_len, [array_ptr])

        # Get Array elem_size (field 2)
        elem_size_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        elem_size = self.builder.load(elem_size_ptr)

        # Create new List with same elem_size
        list_ptr = self.builder.call(self.list_new, [elem_size])

        # Get data pointers
        array_data_ptr = self.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)
        array_data = self.builder.load(array_data_ptr)

        # We need to append each element to the list
        # For efficiency, we'll just copy the data and set list's len/cap
        list_data_ptr = self.builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 3)], inbounds=True)

        # Check if array_len > 8 (list's initial capacity)
        func = self.builder.function
        need_realloc_block = func.append_basic_block("list_realloc")
        copy_block = func.append_basic_block("list_copy")

        eight = ir.Constant(i64, 8)
        need_realloc = self.builder.icmp_signed(">", array_len, eight)
        self.builder.cbranch(need_realloc, need_realloc_block, copy_block)

        # Reallocate list data if needed
        self.builder.position_at_end(need_realloc_block)
        new_data_size = self.builder.mul(array_len, elem_size)
        new_data = self.builder.call(self.malloc, [new_data_size])
        old_data = self.builder.load(list_data_ptr)
        self.builder.call(self.free, [old_data])
        self.builder.store(new_data, list_data_ptr)
        # Update capacity
        cap_ptr = self.builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        self.builder.store(array_len, cap_ptr)
        self.builder.branch(copy_block)

        # Copy data
        self.builder.position_at_end(copy_block)
        list_data = self.builder.load(list_data_ptr)
        copy_size = self.builder.mul(array_len, elem_size)
        self.builder.call(self.memcpy, [list_data, array_data, copy_size])

        # Set list len = array_len
        len_ptr = self.builder.gep(list_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        self.builder.store(array_len, len_ptr)

        return list_ptr

    def _create_string_type(self):
        """Create the String struct type and helper functions.

        String layout (contiguous allocation, no null terminator):
            Bytes 0-7:   i64 byte_len (number of UTF-8 bytes)
            Bytes 8-15:  i64 char_count (number of UTF-8 codepoints)
            Bytes 16+:   UTF-8 data (byte_len bytes, no null terminator)

        A String* points to the start of this block.
        Total allocation size = 16 + byte_len
        """
        # The struct contains byte_len and char_count; data follows immediately after
        self.string_struct = ir.global_context.get_identified_type("struct.String")
        self.string_struct.set_body(
            ir.IntType(64),  # byte_len (data follows at offset 16)
            ir.IntType(64),  # char_count (number of UTF-8 codepoints)
        )
        
        string_ptr = self.string_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        i1 = ir.IntType(1)
        
        # Declare POSIX write for safe printing (no stdout symbol needed)
        # ssize_t write(int fd, const void *buf, size_t count)
        # fd=1 is stdout
        write_ty = ir.FunctionType(i64, [ir.IntType(32), i8_ptr, i64])
        self.write_syscall = ir.Function(self.module, write_ty, name="write")
        
        # string_new(data: i8*, byte_len: i64, char_count: i64) -> String*
        string_new_ty = ir.FunctionType(string_ptr, [i8_ptr, i64, i64])
        self.string_new = ir.Function(self.module, string_new_ty, name="coex_string_new")
        
        # string_from_literal(data: i8*) -> String* (for null-terminated C strings from source)
        string_from_lit_ty = ir.FunctionType(string_ptr, [i8_ptr])
        self.string_from_literal = ir.Function(self.module, string_from_lit_ty, name="coex_string_from_literal")
        
        # string_len(s: String*) -> i64
        string_len_ty = ir.FunctionType(i64, [string_ptr])
        self.string_len = ir.Function(self.module, string_len_ty, name="coex_string_len")
        
        # string_get(s: String*, index: i64) -> i64 (returns byte value, with bounds check)
        string_get_ty = ir.FunctionType(i64, [string_ptr, i64])
        self.string_get = ir.Function(self.module, string_get_ty, name="coex_string_get")
        
        # string_slice(s: String*, start: i64, end: i64) -> String*
        string_slice_ty = ir.FunctionType(string_ptr, [string_ptr, i64, i64])
        self.string_slice = ir.Function(self.module, string_slice_ty, name="coex_string_slice")
        
        # string_concat(a: String*, b: String*) -> String*
        string_concat_ty = ir.FunctionType(string_ptr, [string_ptr, string_ptr])
        self.string_concat = ir.Function(self.module, string_concat_ty, name="coex_string_concat")
        
        # string_eq(a: String*, b: String*) -> bool
        string_eq_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        self.string_eq = ir.Function(self.module, string_eq_ty, name="coex_string_eq")
        
        # string_contains(s: String*, needle: String*) -> bool
        string_contains_ty = ir.FunctionType(i1, [string_ptr, string_ptr])
        self.string_contains = ir.Function(self.module, string_contains_ty, name="coex_string_contains")
        
        # string_print(s: String*) -> void
        string_print_ty = ir.FunctionType(ir.VoidType(), [string_ptr])
        self.string_print = ir.Function(self.module, string_print_ty, name="coex_string_print")
        
        # string_data(s: String*) -> i8* (get pointer to data portion)
        string_data_ty = ir.FunctionType(i8_ptr, [string_ptr])
        self.string_data = ir.Function(self.module, string_data_ty, name="coex_string_data")

        # string_size(s: String*) -> i64 (total memory footprint in bytes)
        string_size_ty = ir.FunctionType(i64, [string_ptr])
        self.string_size = ir.Function(self.module, string_size_ty, name="coex_string_size")

        # Implement all string functions
        self._implement_string_data()
        self._implement_string_new()
        self._implement_string_from_literal()
        self._implement_string_len()
        self._implement_string_size()
        self._implement_string_get()
        self._implement_string_slice()
        self._implement_string_concat()
        self._implement_string_eq()
        self._implement_string_contains()
        self._implement_string_print()

        # Register String type methods
        self._register_string_methods()
    
    def _implement_string_data(self):
        """Get pointer to data portion (offset 16 from string pointer)"""
        func = self.string_data
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]

        # Cast to i8*, add 16 bytes offset to skip byte_len and char_count fields
        raw_ptr = builder.bitcast(s, ir.IntType(8).as_pointer())
        data_ptr = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])

        builder.ret(data_ptr)
    
    def _implement_string_new(self):
        """Create String from data pointer, byte length, and char count.

        Allocates 16 + byte_len bytes:
          - Stores byte_len at offset 0
          - Stores char_count at offset 8
          - Copies data to offset 16
        """
        func = self.string_new
        func.args[0].name = "data"
        func.args[1].name = "byte_len"
        func.args[2].name = "char_count"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        data = func.args[0]
        byte_len = func.args[1]
        char_count = func.args[2]

        # Allocate 16 (byte_len + char_count fields) + byte_len (data) bytes via GC
        alloc_size = builder.add(ir.Constant(ir.IntType(64), 16), byte_len)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_STRING)
        raw_ptr = builder.call(self.gc.gc_alloc, [alloc_size, type_id])
        string_ptr = builder.bitcast(raw_ptr, self.string_struct.as_pointer())

        # Store byte_len at offset 0
        byte_len_ptr = builder.gep(string_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(byte_len, byte_len_ptr)

        # Store char_count at offset 1 (byte 8)
        char_count_ptr = builder.gep(string_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(char_count, char_count_ptr)

        # Copy data to offset 16
        data_dest = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])
        builder.call(self.memcpy, [data_dest, data, byte_len])

        builder.ret(string_ptr)
    
    def _implement_string_from_literal(self):
        """Create String from null-terminated C string literal.

        Used for string literals in source code. Scans for byte length
        and UTF-8 codepoint count, then calls string_new.

        UTF-8 codepoint counting: A byte starts a new codepoint if it's NOT
        a continuation byte (10xxxxxx). So we count bytes where (byte & 0xC0) != 0x80.
        """
        func = self.string_from_literal
        func.args[0].name = "cstr"

        entry = func.append_basic_block("entry")
        loop = func.append_basic_block("loop")
        loop_body = func.append_basic_block("loop_body")
        inc_char = func.append_basic_block("inc_char")
        after_char_check = func.append_basic_block("after_char_check")
        done = func.append_basic_block("done")

        builder = ir.IRBuilder(entry)
        cstr = func.args[0]

        # Allocate counters for byte_len and char_count
        byte_len_ptr = builder.alloca(ir.IntType(64), name="byte_len")
        char_count_ptr = builder.alloca(ir.IntType(64), name="char_count")
        builder.store(ir.Constant(ir.IntType(64), 0), byte_len_ptr)
        builder.store(ir.Constant(ir.IntType(64), 0), char_count_ptr)
        builder.branch(loop)

        builder.position_at_end(loop)
        current_byte_len = builder.load(byte_len_ptr)
        char_ptr = builder.gep(cstr, [current_byte_len])
        char_val = builder.load(char_ptr)
        is_null = builder.icmp_unsigned("==", char_val, ir.Constant(ir.IntType(8), 0))
        builder.cbranch(is_null, done, loop_body)

        builder.position_at_end(loop_body)
        # Increment byte count
        new_byte_len = builder.add(current_byte_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_byte_len, byte_len_ptr)

        # Check if this byte starts a new codepoint: (byte & 0xC0) != 0x80
        # A continuation byte has pattern 10xxxxxx (0x80-0xBF)
        masked = builder.and_(char_val, ir.Constant(ir.IntType(8), 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(ir.IntType(8), 0x80))
        builder.cbranch(is_continuation, after_char_check, inc_char)

        builder.position_at_end(inc_char)
        # Not a continuation byte, so this starts a new codepoint
        current_char_count = builder.load(char_count_ptr)
        new_char_count = builder.add(current_char_count, ir.Constant(ir.IntType(64), 1))
        builder.store(new_char_count, char_count_ptr)
        builder.branch(after_char_check)

        builder.position_at_end(after_char_check)
        builder.branch(loop)

        builder.position_at_end(done)
        final_byte_len = builder.load(byte_len_ptr)
        final_char_count = builder.load(char_count_ptr)
        # Create new string with both byte_len and char_count
        result = builder.call(self.string_new, [cstr, final_byte_len, final_char_count])
        builder.ret(result)
    
    def _implement_string_len(self):
        """Return string length (char_count at offset 1, i.e. bytes 8-15)"""
        func = self.string_len
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        # Read char_count from offset 1 (second field)
        char_count_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        char_count = builder.load(char_count_ptr)
        builder.ret(char_count)

    def _implement_string_size(self):
        """Return string total memory footprint in bytes.

        Size = 16 (header: byte_len + char_count) + byte_len (data)
        """
        func = self.string_size
        func.args[0].name = "s"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        s = func.args[0]
        # Read byte_len from offset 0 (first field)
        byte_len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        byte_len = builder.load(byte_len_ptr)

        # Size = 16 (header) + byte_len
        total_size = builder.add(ir.Constant(ir.IntType(64), 16), byte_len)
        builder.ret(total_size)

    def _implement_string_get(self):
        """Get byte at index with bounds checking.
        
        Returns 0 if index is out of bounds (safe default).
        """
        func = self.string_get
        func.args[0].name = "s"
        func.args[1].name = "index"
        
        entry = func.append_basic_block("entry")
        in_bounds = func.append_basic_block("in_bounds")
        out_of_bounds = func.append_basic_block("out_of_bounds")
        
        builder = ir.IRBuilder(entry)
        
        s = func.args[0]
        index = func.args[1]
        
        # Get length
        len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        length = builder.load(len_ptr)
        
        # Bounds check: 0 <= index < length
        is_negative = builder.icmp_signed("<", index, ir.Constant(ir.IntType(64), 0))
        is_too_large = builder.icmp_signed(">=", index, length)
        is_invalid = builder.or_(is_negative, is_too_large)
        builder.cbranch(is_invalid, out_of_bounds, in_bounds)
        
        builder.position_at_end(in_bounds)
        # Get data pointer (offset 16)
        raw_ptr = builder.bitcast(s, ir.IntType(8).as_pointer())
        data_ptr = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])
        
        # Get byte at index
        byte_ptr = builder.gep(data_ptr, [index])
        byte_val = builder.load(byte_ptr)
        result = builder.zext(byte_val, ir.IntType(64))
        builder.ret(result)
        
        builder.position_at_end(out_of_bounds)
        # Return 0 for out-of-bounds access (safe failure)
        builder.ret(ir.Constant(ir.IntType(64), 0))
    
    def _implement_string_slice(self):
        """Extract substring [start, end) by byte indices.

        Clamps indices to valid range for safety.
        Note: This slices by byte index. For proper UTF-8 handling, the slice
        boundaries should align with codepoint boundaries.
        """
        func = self.string_slice
        func.args[0].name = "s"
        func.args[1].name = "start"
        func.args[2].name = "end"

        entry = func.append_basic_block("entry")
        count_loop = func.append_basic_block("count_loop")
        count_body = func.append_basic_block("count_body")
        inc_char = func.append_basic_block("inc_char")
        after_inc = func.append_basic_block("after_inc")
        count_done = func.append_basic_block("count_done")

        builder = ir.IRBuilder(entry)

        s = func.args[0]
        start = func.args[1]
        end = func.args[2]

        # Get byte_len
        byte_len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        byte_len = builder.load(byte_len_ptr)

        # Clamp start: max(0, min(start, byte_len))
        zero = ir.Constant(ir.IntType(64), 0)
        start_clamped = builder.select(builder.icmp_signed("<", start, zero), zero, start)
        start_clamped = builder.select(builder.icmp_signed(">", start_clamped, byte_len), byte_len, start_clamped)

        # Clamp end: max(start, min(end, byte_len))
        end_clamped = builder.select(builder.icmp_signed("<", end, zero), zero, end)
        end_clamped = builder.select(builder.icmp_signed(">", end_clamped, byte_len), byte_len, end_clamped)
        end_clamped = builder.select(builder.icmp_signed("<", end_clamped, start_clamped), start_clamped, end_clamped)

        # Calculate new byte length
        new_byte_len = builder.sub(end_clamped, start_clamped)

        # Get source data pointer (offset 16)
        raw_ptr = builder.bitcast(s, ir.IntType(8).as_pointer())
        data_ptr = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])
        slice_start = builder.gep(data_ptr, [start_clamped])

        # Count codepoints in the slice (scan for non-continuation bytes)
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        char_count_ptr = builder.alloca(ir.IntType(64), name="char_count")
        builder.store(zero, idx_ptr)
        builder.store(zero, char_count_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_loop)
        idx = builder.load(idx_ptr)
        done_counting = builder.icmp_signed(">=", idx, new_byte_len)
        builder.cbranch(done_counting, count_done, count_body)

        builder.position_at_end(count_body)
        byte_ptr = builder.gep(slice_start, [idx])
        byte_val = builder.load(byte_ptr)
        # Check if this byte starts a codepoint: (byte & 0xC0) != 0x80
        masked = builder.and_(byte_val, ir.Constant(ir.IntType(8), 0xC0))
        is_continuation = builder.icmp_unsigned("==", masked, ir.Constant(ir.IntType(8), 0x80))
        builder.cbranch(is_continuation, after_inc, inc_char)

        builder.position_at_end(inc_char)
        curr_count = builder.load(char_count_ptr)
        new_count = builder.add(curr_count, ir.Constant(ir.IntType(64), 1))
        builder.store(new_count, char_count_ptr)
        builder.branch(after_inc)

        builder.position_at_end(after_inc)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(count_loop)

        builder.position_at_end(count_done)
        final_char_count = builder.load(char_count_ptr)

        # Create new string with byte_len and char_count
        result = builder.call(self.string_new, [slice_start, new_byte_len, final_char_count])
        builder.ret(result)
    
    def _implement_string_concat(self):
        """Concatenate two strings."""
        func = self.string_concat
        func.args[0].name = "a"
        func.args[1].name = "b"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        a = func.args[0]
        b = func.args[1]

        # Get byte_len from both strings
        a_byte_len_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        a_byte_len = builder.load(a_byte_len_ptr)

        b_byte_len_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        b_byte_len = builder.load(b_byte_len_ptr)

        # Get char_count from both strings
        a_char_count_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        a_char_count = builder.load(a_char_count_ptr)

        b_char_count_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        b_char_count = builder.load(b_char_count_ptr)

        # Total byte length and char count
        total_byte_len = builder.add(a_byte_len, b_byte_len)
        total_char_count = builder.add(a_char_count, b_char_count)

        # Allocate new string: 16 + total_byte_len via GC
        alloc_size = builder.add(ir.Constant(ir.IntType(64), 16), total_byte_len)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_STRING)
        raw_ptr = builder.call(self.gc.gc_alloc, [alloc_size, type_id])
        string_ptr = builder.bitcast(raw_ptr, self.string_struct.as_pointer())

        # Store byte_len at offset 0
        byte_len_ptr = builder.gep(string_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(total_byte_len, byte_len_ptr)

        # Store char_count at offset 1
        char_count_ptr = builder.gep(string_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(total_char_count, char_count_ptr)

        # Get data destination (offset 16)
        dest_data = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])

        # Copy a's data
        a_raw = builder.bitcast(a, ir.IntType(8).as_pointer())
        a_data = builder.gep(a_raw, [ir.Constant(ir.IntType(64), 16)])
        builder.call(self.memcpy, [dest_data, a_data, a_byte_len])

        # Copy b's data after a
        b_dest = builder.gep(dest_data, [a_byte_len])
        b_raw = builder.bitcast(b, ir.IntType(8).as_pointer())
        b_data = builder.gep(b_raw, [ir.Constant(ir.IntType(64), 16)])
        builder.call(self.memcpy, [b_dest, b_data, b_byte_len])

        builder.ret(string_ptr)
    
    def _implement_string_eq(self):
        """Compare two strings for equality."""
        func = self.string_eq
        func.args[0].name = "a"
        func.args[1].name = "b"
        
        entry = func.append_basic_block("entry")
        check_data = func.append_basic_block("check_data")
        compare_loop = func.append_basic_block("compare_loop")
        compare_body = func.append_basic_block("compare_body")
        not_equal = func.append_basic_block("not_equal")
        equal = func.append_basic_block("equal")
        
        builder = ir.IRBuilder(entry)
        
        a = func.args[0]
        b = func.args[1]
        
        # Get lengths
        a_len_ptr = builder.gep(a, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        a_len = builder.load(a_len_ptr)
        
        b_len_ptr = builder.gep(b, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        b_len = builder.load(b_len_ptr)
        
        # Check if lengths are equal
        len_eq = builder.icmp_signed("==", a_len, b_len)
        builder.cbranch(len_eq, check_data, not_equal)
        
        builder.position_at_end(check_data)
        # Get data pointers (offset 16)
        a_raw = builder.bitcast(a, ir.IntType(8).as_pointer())
        a_data = builder.gep(a_raw, [ir.Constant(ir.IntType(64), 16)])

        b_raw = builder.bitcast(b, ir.IntType(8).as_pointer())
        b_data = builder.gep(b_raw, [ir.Constant(ir.IntType(64), 16)])
        
        # Compare bytes
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        builder.branch(compare_loop)
        
        builder.position_at_end(compare_loop)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, a_len)
        builder.cbranch(done, equal, compare_body)
        
        builder.position_at_end(compare_body)
        a_char_ptr = builder.gep(a_data, [idx])
        a_char = builder.load(a_char_ptr)
        b_char_ptr = builder.gep(b_data, [idx])
        b_char = builder.load(b_char_ptr)
        
        chars_eq = builder.icmp_unsigned("==", a_char, b_char)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.cbranch(chars_eq, compare_loop, not_equal)
        
        builder.position_at_end(not_equal)
        builder.ret(ir.Constant(ir.IntType(1), 0))
        
        builder.position_at_end(equal)
        builder.ret(ir.Constant(ir.IntType(1), 1))
    
    def _implement_string_contains(self):
        """Check if string contains substring (naive search)."""
        func = self.string_contains
        func.args[0].name = "s"
        func.args[1].name = "needle"
        
        entry = func.append_basic_block("entry")
        outer_loop = func.append_basic_block("outer_loop")
        inner_setup = func.append_basic_block("inner_setup")
        inner_loop = func.append_basic_block("inner_loop")
        inner_check = func.append_basic_block("inner_check")
        mismatch = func.append_basic_block("mismatch")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")
        
        builder = ir.IRBuilder(entry)
        
        s = func.args[0]
        needle = func.args[1]
        
        # Get lengths
        s_len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        s_len = builder.load(s_len_ptr)
        
        needle_len_ptr = builder.gep(needle, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        needle_len = builder.load(needle_len_ptr)
        
        # Get data pointers (offset 16)
        s_raw = builder.bitcast(s, ir.IntType(8).as_pointer())
        s_data = builder.gep(s_raw, [ir.Constant(ir.IntType(64), 16)])

        needle_raw = builder.bitcast(needle, ir.IntType(8).as_pointer())
        needle_data = builder.gep(needle_raw, [ir.Constant(ir.IntType(64), 16)])
        
        # Empty needle always matches
        empty_needle = builder.icmp_signed("==", needle_len, ir.Constant(ir.IntType(64), 0))
        
        # Loop indices
        i_ptr = builder.alloca(ir.IntType(64), name="i")
        j_ptr = builder.alloca(ir.IntType(64), name="j")
        builder.store(ir.Constant(ir.IntType(64), 0), i_ptr)
        
        builder.cbranch(empty_needle, found, outer_loop)
        
        # Outer loop: for each starting position
        builder.position_at_end(outer_loop)
        i = builder.load(i_ptr)
        remaining = builder.sub(s_len, i)
        can_fit = builder.icmp_signed(">=", remaining, needle_len)
        builder.cbranch(can_fit, inner_setup, not_found)
        
        # Setup inner loop
        builder.position_at_end(inner_setup)
        builder.store(ir.Constant(ir.IntType(64), 0), j_ptr)
        builder.branch(inner_loop)
        
        # Inner loop: compare characters
        builder.position_at_end(inner_loop)
        j = builder.load(j_ptr)
        matched_all = builder.icmp_signed(">=", j, needle_len)
        builder.cbranch(matched_all, found, inner_check)
        
        # Check current character
        builder.position_at_end(inner_check)
        i_val = builder.load(i_ptr)
        j_val = builder.load(j_ptr)
        s_idx = builder.add(i_val, j_val)
        
        s_char_ptr = builder.gep(s_data, [s_idx])
        s_char = builder.load(s_char_ptr)
        
        needle_char_ptr = builder.gep(needle_data, [j_val])
        needle_char = builder.load(needle_char_ptr)
        
        chars_match = builder.icmp_unsigned("==", s_char, needle_char)
        
        new_j = builder.add(j_val, ir.Constant(ir.IntType(64), 1))
        builder.store(new_j, j_ptr)
        
        builder.cbranch(chars_match, inner_loop, mismatch)
        
        # Mismatch - try next position
        builder.position_at_end(mismatch)
        i_val = builder.load(i_ptr)
        new_i = builder.add(i_val, ir.Constant(ir.IntType(64), 1))
        builder.store(new_i, i_ptr)
        builder.branch(outer_loop)
        
        builder.position_at_end(found)
        builder.ret(ir.Constant(ir.IntType(1), 1))
        
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(ir.IntType(1), 0))
    
    def _implement_string_print(self):
        """Print string to stdout using POSIX write (no null terminator needed)."""
        func = self.string_print
        func.args[0].name = "s"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        s = func.args[0]
        
        # Get length
        len_ptr = builder.gep(s, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        length = builder.load(len_ptr)
        
        # Get data pointer (offset 16)
        raw_ptr = builder.bitcast(s, ir.IntType(8).as_pointer())
        data_ptr = builder.gep(raw_ptr, [ir.Constant(ir.IntType(64), 16)])
        
        # write(1, data, length) - fd 1 is stdout
        stdout_fd = ir.Constant(ir.IntType(32), 1)
        builder.call(self.write_syscall, [stdout_fd, data_ptr, length])
        
        # Print newline
        newline_ptr = builder.bitcast(self._create_global_string("\n", "newline"), ir.IntType(8).as_pointer())
        builder.call(self.write_syscall, [stdout_fd, newline_ptr, ir.Constant(ir.IntType(64), 1)])
        
        builder.ret_void()
    
    def _register_string_methods(self):
        """Register String as a type with methods for method call resolution"""
        # Add String to type registry
        self.type_registry["String"] = self.string_struct
        
        # Map method names to function names
        self.type_methods["String"] = {
            "len": "coex_string_len",
            "size": "coex_string_size",
            "get": "coex_string_get",
            "slice": "coex_string_slice",
            "concat": "coex_string_concat",
            "eq": "coex_string_eq",
            "contains": "coex_string_contains",
            "print": "coex_string_print",
            "data": "coex_string_data",
        }

        # Also store function references for direct access
        self.functions["coex_string_len"] = self.string_len
        self.functions["coex_string_size"] = self.string_size
        self.functions["coex_string_get"] = self.string_get
        self.functions["coex_string_slice"] = self.string_slice
        self.functions["coex_string_concat"] = self.string_concat
        self.functions["coex_string_eq"] = self.string_eq
        self.functions["coex_string_contains"] = self.string_contains
        self.functions["coex_string_print"] = self.string_print
        self.functions["coex_string_data"] = self.string_data

    def _create_map_type(self):
        """Create the Map type and helper functions.
        
        Map uses a hash table with linear probing.
        
        MapEntry layout:
            i64 key    - Key (int value or String pointer)
            i64 value  - Value (int value or pointer)
            i8  state  - 0=empty, 1=occupied, 2=deleted (tombstone)
        
        Map layout:
            MapEntry* entries  - Array of entries
            i64 len            - Number of occupied entries
            i64 cap            - Total capacity (always power of 2)
        
        Keys and values are stored as i64 (for ints) or pointers cast to i64.
        """
        # MapEntry struct: { i64 key, i64 value, i8 state }
        self.map_entry_struct = ir.global_context.get_identified_type("struct.MapEntry")
        self.map_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(64),  # value
            ir.IntType(8)    # state: 0=empty, 1=occupied, 2=deleted
        )
        
        # Map struct: { MapEntry* entries, i64 len, i64 cap }
        self.map_struct = ir.global_context.get_identified_type("struct.Map")
        self.map_struct.set_body(
            self.map_entry_struct.as_pointer(),  # entries
            ir.IntType(64),   # len
            ir.IntType(64)    # cap
        )
        
        map_ptr = self.map_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        
        # map_new() -> Map*
        map_new_ty = ir.FunctionType(map_ptr, [])
        self.map_new = ir.Function(self.module, map_new_ty, name="coex_map_new")
        
        # map_set(map: Map*, key: i64, value: i64)
        map_set_ty = ir.FunctionType(ir.VoidType(), [map_ptr, i64, i64])
        self.map_set = ir.Function(self.module, map_set_ty, name="coex_map_set")
        
        # map_get(map: Map*, key: i64) -> i64
        map_get_ty = ir.FunctionType(i64, [map_ptr, i64])
        self.map_get = ir.Function(self.module, map_get_ty, name="coex_map_get")
        
        # map_has(map: Map*, key: i64) -> bool
        map_has_ty = ir.FunctionType(i1, [map_ptr, i64])
        self.map_has = ir.Function(self.module, map_has_ty, name="coex_map_has")
        
        # map_remove(map: Map*, key: i64) -> bool
        map_remove_ty = ir.FunctionType(i1, [map_ptr, i64])
        self.map_remove = ir.Function(self.module, map_remove_ty, name="coex_map_remove")
        
        # map_len(map: Map*) -> i64
        map_len_ty = ir.FunctionType(i64, [map_ptr])
        self.map_len = ir.Function(self.module, map_len_ty, name="coex_map_len")

        # map_size(map: Map*) -> i64 (total memory footprint in bytes)
        map_size_ty = ir.FunctionType(i64, [map_ptr])
        self.map_size = ir.Function(self.module, map_size_ty, name="coex_map_size")

        # map_hash(key: i64) -> i64  (internal hash function)
        map_hash_ty = ir.FunctionType(i64, [i64])
        self.map_hash = ir.Function(self.module, map_hash_ty, name="coex_map_hash")

        # map_grow(map: Map*)  (internal resize function)
        map_grow_ty = ir.FunctionType(ir.VoidType(), [map_ptr])
        self.map_grow = ir.Function(self.module, map_grow_ty, name="coex_map_grow")

        # map_find_slot(map: Map*, key: i64) -> i64  (internal: find slot for key)
        map_find_slot_ty = ir.FunctionType(i64, [map_ptr, i64])
        self.map_find_slot = ir.Function(self.module, map_find_slot_ty, name="coex_map_find_slot")

        # Implement all map functions
        self._implement_map_hash()
        self._implement_map_new()
        self._implement_map_find_slot()
        self._implement_map_grow()
        self._implement_map_set()
        self._implement_map_get()
        self._implement_map_has()
        self._implement_map_remove()
        self._implement_map_len()
        self._implement_map_size()

        # Register Map methods
        self._register_map_methods()
    
    def _implement_map_hash(self):
        """Implement integer hash function (splitmix64-based)."""
        func = self.map_hash
        func.args[0].name = "key"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        key = func.args[0]
        
        # splitmix64 mixing function
        x = key
        x_shr30 = builder.lshr(x, ir.Constant(ir.IntType(64), 30))
        x = builder.xor(x, x_shr30)
        x = builder.mul(x, ir.Constant(ir.IntType(64), 0xbf58476d1ce4e5b9))
        x_shr27 = builder.lshr(x, ir.Constant(ir.IntType(64), 27))
        x = builder.xor(x, x_shr27)
        x = builder.mul(x, ir.Constant(ir.IntType(64), 0x94d049bb133111eb))
        x_shr31 = builder.lshr(x, ir.Constant(ir.IntType(64), 31))
        x = builder.xor(x, x_shr31)
        
        builder.ret(x)
    
    def _implement_map_new(self):
        """Create a new empty map with initial capacity 8."""
        func = self.map_new
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        # Allocate Map struct (8 + 8 + 8 = 24 bytes) via GC
        map_size = ir.Constant(ir.IntType(64), 24)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_MAP)
        raw_ptr = builder.call(self.gc.gc_alloc, [map_size, type_id])
        map_ptr = builder.bitcast(raw_ptr, self.map_struct.as_pointer())
        
        # Initial capacity = 8
        initial_cap = ir.Constant(ir.IntType(64), 8)
        
        # Allocate entries array: 8 entries * 24 bytes each (aligned)
        entry_size = ir.Constant(ir.IntType(64), 24)
        entries_size = builder.mul(initial_cap, entry_size)
        entries_raw = builder.call(self.malloc, [entries_size])
        entries_ptr = builder.bitcast(entries_raw, self.map_entry_struct.as_pointer())
        
        # Initialize each entry's state to 0 (empty)
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        
        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")
        
        builder.branch(init_loop)
        
        builder.position_at_end(init_loop)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, initial_cap)
        builder.cbranch(done, init_done, init_body)
        
        builder.position_at_end(init_body)
        e_ptr = builder.gep(entries_ptr, [idx])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8), 0), state_ptr)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(init_loop)
        
        builder.position_at_end(init_done)
        
        # Store entries pointer
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(entries_ptr, entries_field)
        
        # Store len = 0
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_field)
        
        # Store cap = 8
        cap_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(initial_cap, cap_field)
        
        builder.ret(map_ptr)
    
    def _implement_map_find_slot(self):
        """Find slot for key using linear probing."""
        func = self.map_find_slot
        func.args[0].name = "map"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        probe_loop = func.append_basic_block("probe_loop")
        check_state = func.append_basic_block("check_state")
        check_occupied = func.append_basic_block("check_occupied")
        check_match = func.append_basic_block("check_match")
        record_deleted = func.append_basic_block("record_deleted")
        next_probe = func.append_basic_block("next_probe")
        found_empty = func.append_basic_block("found_empty")
        found_match = func.append_basic_block("found_match")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        key = func.args[1]
        
        # Get entries and cap
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        cap_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_field)
        
        # hash & mask
        hash_val = builder.call(self.map_hash, [key])
        mask = builder.sub(cap, ir.Constant(ir.IntType(64), 1))
        start_idx = builder.and_(hash_val, mask)
        
        # Track first deleted slot
        first_deleted_ptr = builder.alloca(ir.IntType(64), name="first_deleted")
        builder.store(ir.Constant(ir.IntType(64), -1), first_deleted_ptr)
        
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(start_idx, idx_ptr)
        
        probe_count_ptr = builder.alloca(ir.IntType(64), name="probe_count")
        builder.store(ir.Constant(ir.IntType(64), 0), probe_count_ptr)
        
        builder.branch(probe_loop)
        
        # Probe loop
        builder.position_at_end(probe_loop)
        probe_count = builder.load(probe_count_ptr)
        max_probes = builder.icmp_signed(">=", probe_count, cap)
        builder.cbranch(max_probes, found_empty, check_state)
        
        builder.position_at_end(check_state)
        idx = builder.load(idx_ptr)
        e_ptr = builder.gep(entries, [idx])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        
        is_empty = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 0))
        builder.cbranch(is_empty, found_empty, check_occupied)
        
        builder.position_at_end(check_occupied)
        is_occupied = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, check_match, record_deleted)
        
        builder.position_at_end(check_match)
        key_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        stored_key = builder.load(key_ptr)
        keys_match = builder.icmp_signed("==", stored_key, key)
        builder.cbranch(keys_match, found_match, next_probe)
        
        builder.position_at_end(record_deleted)
        # Record first deleted slot if not yet recorded
        first_deleted = builder.load(first_deleted_ptr)
        no_deleted_yet = builder.icmp_signed("==", first_deleted, ir.Constant(ir.IntType(64), -1))
        new_first = builder.select(no_deleted_yet, idx, first_deleted)
        builder.store(new_first, first_deleted_ptr)
        builder.branch(next_probe)
        
        builder.position_at_end(next_probe)
        idx = builder.load(idx_ptr)
        next_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        next_idx = builder.and_(next_idx, mask)
        builder.store(next_idx, idx_ptr)
        probe_count = builder.load(probe_count_ptr)
        new_count = builder.add(probe_count, ir.Constant(ir.IntType(64), 1))
        builder.store(new_count, probe_count_ptr)
        builder.branch(probe_loop)
        
        builder.position_at_end(found_empty)
        first_deleted = builder.load(first_deleted_ptr)
        has_deleted = builder.icmp_signed("!=", first_deleted, ir.Constant(ir.IntType(64), -1))
        idx = builder.load(idx_ptr)
        result = builder.select(has_deleted, first_deleted, idx)
        builder.ret(result)
        
        builder.position_at_end(found_match)
        idx = builder.load(idx_ptr)
        builder.ret(idx)
    
    def _implement_map_grow(self):
        """Double the capacity and rehash all entries."""
        func = self.map_grow
        func.args[0].name = "map"
        
        entry = func.append_basic_block("entry")
        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")
        rehash_loop = func.append_basic_block("rehash_loop")
        rehash_body = func.append_basic_block("rehash_body")
        rehash_insert = func.append_basic_block("rehash_insert")
        rehash_next = func.append_basic_block("rehash_next")
        done = func.append_basic_block("done")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        
        # Get old entries, cap
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_entries = builder.load(entries_field)
        
        cap_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_cap = builder.load(cap_field)
        
        new_cap = builder.mul(old_cap, ir.Constant(ir.IntType(64), 2))
        
        # Allocate new entries
        entry_size = ir.Constant(ir.IntType(64), 24)
        new_size = builder.mul(new_cap, entry_size)
        new_raw = builder.call(self.malloc, [new_size])
        new_entries = builder.bitcast(new_raw, self.map_entry_struct.as_pointer())
        
        # Initialize new entries
        init_idx_ptr = builder.alloca(ir.IntType(64), name="init_idx")
        builder.store(ir.Constant(ir.IntType(64), 0), init_idx_ptr)
        builder.branch(init_loop)
        
        builder.position_at_end(init_loop)
        init_idx = builder.load(init_idx_ptr)
        init_done_cond = builder.icmp_signed(">=", init_idx, new_cap)
        builder.cbranch(init_done_cond, init_done, init_body)
        
        builder.position_at_end(init_body)
        new_e_ptr = builder.gep(new_entries, [init_idx])
        state_ptr = builder.gep(new_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8), 0), state_ptr)
        new_init_idx = builder.add(init_idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_init_idx, init_idx_ptr)
        builder.branch(init_loop)
        
        builder.position_at_end(init_done)
        # Update map
        builder.store(new_entries, entries_field)
        builder.store(new_cap, cap_field)
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_field)
        
        # Rehash
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        builder.branch(rehash_loop)
        
        builder.position_at_end(rehash_loop)
        idx = builder.load(idx_ptr)
        loop_done = builder.icmp_signed(">=", idx, old_cap)
        builder.cbranch(loop_done, done, rehash_body)
        
        builder.position_at_end(rehash_body)
        old_e_ptr = builder.gep(old_entries, [idx])
        state_ptr = builder.gep(old_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        is_occupied = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, rehash_insert, rehash_next)
        
        builder.position_at_end(rehash_insert)
        key_ptr = builder.gep(old_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        key = builder.load(key_ptr)
        value_ptr = builder.gep(old_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        value = builder.load(value_ptr)
        
        new_slot = builder.call(self.map_find_slot, [map_ptr, key])
        new_e_ptr = builder.gep(new_entries, [new_slot])
        
        new_key_ptr = builder.gep(new_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(key, new_key_ptr)
        new_value_ptr = builder.gep(new_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(value, new_value_ptr)
        new_state_ptr = builder.gep(new_e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8), 1), new_state_ptr)
        
        current_len = builder.load(len_field)
        new_len = builder.add(current_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_field)
        builder.branch(rehash_next)
        
        builder.position_at_end(rehash_next)
        idx = builder.load(idx_ptr)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(rehash_loop)
        
        builder.position_at_end(done)
        old_raw = builder.bitcast(old_entries, ir.IntType(8).as_pointer())
        builder.call(self.free, [old_raw])
        builder.ret_void()
    
    def _implement_map_set(self):
        """Set key-value pair in map."""
        func = self.map_set
        func.args[0].name = "map"
        func.args[1].name = "key"
        func.args[2].name = "value"
        
        entry = func.append_basic_block("entry")
        check_grow = func.append_basic_block("check_grow")
        do_grow = func.append_basic_block("do_grow")
        do_insert = func.append_basic_block("do_insert")
        new_entry = func.append_basic_block("new_entry")
        store_values = func.append_basic_block("store_values")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        key = func.args[1]
        value = func.args[2]
        
        builder.branch(check_grow)
        
        builder.position_at_end(check_grow)
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)
        cap_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_field)
        
        len_times_4 = builder.mul(length, ir.Constant(ir.IntType(64), 4))
        cap_times_3 = builder.mul(cap, ir.Constant(ir.IntType(64), 3))
        need_grow = builder.icmp_signed(">=", len_times_4, cap_times_3)
        builder.cbranch(need_grow, do_grow, do_insert)
        
        builder.position_at_end(do_grow)
        builder.call(self.map_grow, [map_ptr])
        builder.branch(do_insert)
        
        builder.position_at_end(do_insert)
        slot = builder.call(self.map_find_slot, [map_ptr, key])
        
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        e_ptr = builder.gep(entries, [slot])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        
        is_new = builder.icmp_unsigned("!=", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_new, new_entry, store_values)
        
        builder.position_at_end(new_entry)
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        current_len = builder.load(len_field)
        new_len = builder.add(current_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_field)
        builder.branch(store_values)
        
        builder.position_at_end(store_values)
        key_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(key, key_ptr)
        value_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(value, value_ptr)
        builder.store(ir.Constant(ir.IntType(8), 1), state_ptr)
        builder.ret_void()
    
    def _implement_map_get(self):
        """Get value for key (returns 0 if not found)."""
        func = self.map_get
        func.args[0].name = "map"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        check_found = func.append_basic_block("check_found")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        key = func.args[1]
        
        slot = builder.call(self.map_find_slot, [map_ptr, key])
        
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        e_ptr = builder.gep(entries, [slot])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        
        is_occupied = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, check_found, not_found)
        
        builder.position_at_end(check_found)
        key_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        stored_key = builder.load(key_ptr)
        keys_match = builder.icmp_signed("==", stored_key, key)
        builder.cbranch(keys_match, found, not_found)
        
        builder.position_at_end(found)
        value_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        value = builder.load(value_ptr)
        builder.ret(value)
        
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(ir.IntType(64), 0))
    
    def _implement_map_has(self):
        """Check if key exists in map."""
        func = self.map_has
        func.args[0].name = "map"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        check_found = func.append_basic_block("check_found")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        key = func.args[1]
        
        slot = builder.call(self.map_find_slot, [map_ptr, key])
        
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        e_ptr = builder.gep(entries, [slot])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        
        is_occupied = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, check_found, not_found)
        
        builder.position_at_end(check_found)
        key_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        stored_key = builder.load(key_ptr)
        keys_match = builder.icmp_signed("==", stored_key, key)
        builder.cbranch(keys_match, found, not_found)
        
        builder.position_at_end(found)
        builder.ret(ir.Constant(ir.IntType(1), 1))
        
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(ir.IntType(1), 0))
    
    def _implement_map_remove(self):
        """Remove key from map (returns true if removed)."""
        func = self.map_remove
        func.args[0].name = "map"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        check_found = func.append_basic_block("check_found")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")
        
        builder = ir.IRBuilder(entry)
        
        map_ptr = func.args[0]
        key = func.args[1]
        
        slot = builder.call(self.map_find_slot, [map_ptr, key])
        
        entries_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        e_ptr = builder.gep(entries, [slot])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        state = builder.load(state_ptr)
        
        is_occupied = builder.icmp_unsigned("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, check_found, not_found)
        
        builder.position_at_end(check_found)
        key_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        stored_key = builder.load(key_ptr)
        keys_match = builder.icmp_signed("==", stored_key, key)
        builder.cbranch(keys_match, found, not_found)
        
        builder.position_at_end(found)
        builder.store(ir.Constant(ir.IntType(8), 2), state_ptr)
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        current_len = builder.load(len_field)
        new_len = builder.sub(current_len, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_field)
        builder.ret(ir.Constant(ir.IntType(1), 1))
        
        builder.position_at_end(not_found)
        builder.ret(ir.Constant(ir.IntType(1), 0))
    
    def _implement_map_len(self):
        """Return number of entries in map."""
        func = self.map_len
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]
        len_field = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)
        builder.ret(length)

    def _implement_map_size(self):
        """Return total memory footprint of map in bytes.

        Size = 24 (header) + cap * 24 (MapEntry array)
        MapEntry is {i64 key, i64 value, i8 state} = 24 bytes with padding
        """
        func = self.map_size
        func.args[0].name = "map"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        map_ptr = func.args[0]

        # Get cap field (field 2)
        cap_ptr = builder.gep(map_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Size = 24 (header) + cap * 24 (each MapEntry is 24 bytes)
        entry_array_size = builder.mul(cap, ir.Constant(ir.IntType(64), 24))
        total_size = builder.add(ir.Constant(ir.IntType(64), 24), entry_array_size)

        builder.ret(total_size)

    def _register_map_methods(self):
        """Register Map as a type with methods."""
        self.type_registry["Map"] = self.map_struct
        self.type_fields["Map"] = []  # Internal structure, not user-accessible fields
        
        self.type_methods["Map"] = {
            "get": "coex_map_get",
            "set": "coex_map_set",
            "has": "coex_map_has",
            "remove": "coex_map_remove",
            "len": "coex_map_len",
            "size": "coex_map_size",
        }

        self.functions["coex_map_new"] = self.map_new
        self.functions["coex_map_get"] = self.map_get
        self.functions["coex_map_set"] = self.map_set
        self.functions["coex_map_has"] = self.map_has
        self.functions["coex_map_remove"] = self.map_remove
        self.functions["coex_map_len"] = self.map_len
        self.functions["coex_map_size"] = self.map_size

    # ========================================================================
    # Set Type Implementation
    # ========================================================================
    
    def _create_set_type(self):
        """Create the Set type and helper functions.
        
        Set uses a hash table with linear probing (like Map, but no values).
        
        SetEntry layout:
            i64 key    - Key (int value or pointer cast to i64)
            i8  state  - 0=empty, 1=occupied, 2=deleted (tombstone)
        
        Set layout:
            SetEntry* entries  - Array of entries
            i64 len            - Number of occupied entries
            i64 cap            - Total capacity (always power of 2)
        """
        # SetEntry struct: { i64 key, i8 state }
        self.set_entry_struct = ir.global_context.get_identified_type("struct.SetEntry")
        self.set_entry_struct.set_body(
            ir.IntType(64),  # key
            ir.IntType(8)    # state: 0=empty, 1=occupied, 2=deleted
        )
        
        # Set struct: { SetEntry* entries, i64 len, i64 cap }
        self.set_struct = ir.global_context.get_identified_type("struct.Set")
        self.set_struct.set_body(
            self.set_entry_struct.as_pointer(),  # entries
            ir.IntType(64),   # len
            ir.IntType(64)    # cap
        )
        
        set_ptr = self.set_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        
        # set_new() -> Set*
        set_new_ty = ir.FunctionType(set_ptr, [])
        self.set_new = ir.Function(self.module, set_new_ty, name="coex_set_new")
        
        # set_add(set: Set*, key: i64)
        set_add_ty = ir.FunctionType(ir.VoidType(), [set_ptr, i64])
        self.set_add = ir.Function(self.module, set_add_ty, name="coex_set_add")
        
        # set_has(set: Set*, key: i64) -> bool
        set_has_ty = ir.FunctionType(i1, [set_ptr, i64])
        self.set_has = ir.Function(self.module, set_has_ty, name="coex_set_has")
        
        # set_remove(set: Set*, key: i64) -> bool
        set_remove_ty = ir.FunctionType(i1, [set_ptr, i64])
        self.set_remove = ir.Function(self.module, set_remove_ty, name="coex_set_remove")
        
        # set_len(set: Set*) -> i64
        set_len_ty = ir.FunctionType(i64, [set_ptr])
        self.set_len = ir.Function(self.module, set_len_ty, name="coex_set_len")

        # set_size(set: Set*) -> i64 (total memory footprint in bytes)
        set_size_ty = ir.FunctionType(i64, [set_ptr])
        self.set_size = ir.Function(self.module, set_size_ty, name="coex_set_size")

        # set_grow(set: Set*)  (internal resize function)
        set_grow_ty = ir.FunctionType(ir.VoidType(), [set_ptr])
        self.set_grow = ir.Function(self.module, set_grow_ty, name="coex_set_grow")

        # set_find_slot(set: Set*, key: i64) -> i64  (internal: find slot for key)
        set_find_slot_ty = ir.FunctionType(i64, [set_ptr, i64])
        self.set_find_slot = ir.Function(self.module, set_find_slot_ty, name="coex_set_find_slot")

        # Implement all set functions
        self._implement_set_new()
        self._implement_set_find_slot()
        self._implement_set_grow()
        self._implement_set_add()
        self._implement_set_has()
        self._implement_set_remove()
        self._implement_set_len()
        self._implement_set_size()
        self._register_set_methods()
    
    def _implement_set_new(self):
        """Implement set_new: allocate a new empty set."""
        func = self.set_new
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        # Allocate Set struct (3 * 8 = 24 bytes) via GC
        set_size = ir.Constant(ir.IntType(64), 24)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_SET)
        raw_ptr = builder.call(self.gc.gc_alloc, [set_size, type_id])
        set_ptr = builder.bitcast(raw_ptr, self.set_struct.as_pointer())
        
        # Initial capacity = 8
        initial_cap = ir.Constant(ir.IntType(64), 8)
        
        # Allocate entries array: 8 entries * 16 bytes each (i64 key + i8 state, padded)
        entry_size = ir.Constant(ir.IntType(64), 16)
        entries_size = builder.mul(initial_cap, entry_size)
        entries_raw = builder.call(self.malloc, [entries_size])
        entries_ptr = builder.bitcast(entries_raw, self.set_entry_struct.as_pointer())
        
        # Initialize each entry's state to 0 (empty) using a loop
        idx_ptr = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_ptr)
        
        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")
        
        builder.branch(init_loop)
        
        builder.position_at_end(init_loop)
        idx = builder.load(idx_ptr)
        done = builder.icmp_signed(">=", idx, initial_cap)
        builder.cbranch(done, init_done, init_body)
        
        builder.position_at_end(init_body)
        e_ptr = builder.gep(entries_ptr, [idx])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8), 0), state_ptr)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, idx_ptr)
        builder.branch(init_loop)
        
        builder.position_at_end(init_done)
        
        # Store entries pointer
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(entries_ptr, entries_field)
        
        # Store len = 0
        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), len_field)
        
        # Store cap = 8
        cap_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        builder.store(initial_cap, cap_field)
        
        builder.ret(set_ptr)
    
    def _implement_set_find_slot(self):
        """Implement set_find_slot: find slot for key using linear probing.
        
        Returns the index of:
        - The slot containing the key (if found), or
        - The first empty/deleted slot suitable for insertion
        """
        func = self.set_find_slot
        func.args[0].name = "set"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        set_ptr = func.args[0]
        key = func.args[1]
        
        # Get entries and cap
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        cap_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_field)
        
        # Compute hash and starting index
        hash_val = builder.call(self.map_hash, [key])  # Reuse map's hash function
        mask = builder.sub(cap, ir.Constant(ir.IntType(64), 1))
        start_idx = builder.and_(hash_val, mask)
        
        # Allocate locals for loop
        idx_alloca = builder.alloca(ir.IntType(64), name="idx")
        builder.store(start_idx, idx_alloca)
        
        first_deleted_alloca = builder.alloca(ir.IntType(64), name="first_deleted")
        builder.store(ir.Constant(ir.IntType(64), -1), first_deleted_alloca)
        
        # Loop to find slot
        loop_block = func.append_basic_block("loop")
        found_block = func.append_basic_block("found")
        empty_block = func.append_basic_block("empty")
        deleted_block = func.append_basic_block("deleted")
        continue_block = func.append_basic_block("continue")
        
        builder.branch(loop_block)
        
        # Loop body
        builder = ir.IRBuilder(loop_block)
        idx = builder.load(idx_alloca)
        
        # Get entry at idx
        entry_ptr = builder.gep(entries, [idx], inbounds=True)
        state_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        state = builder.load(state_ptr)
        
        # Check state
        is_empty = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 0))
        is_deleted = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 2))
        is_occupied = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 1))
        
        # Branch on empty
        not_empty_block = func.append_basic_block("not_empty")
        builder.cbranch(is_empty, empty_block, not_empty_block)
        
        # Not empty - check if deleted
        builder = ir.IRBuilder(not_empty_block)
        not_deleted_block = func.append_basic_block("not_deleted")
        builder.cbranch(is_deleted, deleted_block, not_deleted_block)
        
        # Occupied - check if key matches
        builder = ir.IRBuilder(not_deleted_block)
        key_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entry_key = builder.load(key_ptr)
        key_matches = builder.icmp_signed("==", entry_key, key)
        builder.cbranch(key_matches, found_block, continue_block)
        
        # Empty slot - return it (or first_deleted if we saw one)
        builder = ir.IRBuilder(empty_block)
        first_deleted = builder.load(first_deleted_alloca)
        has_deleted = builder.icmp_signed(">=", first_deleted, ir.Constant(ir.IntType(64), 0))
        result_idx = builder.select(has_deleted, first_deleted, idx)
        builder.ret(result_idx)
        
        # Found matching key - return this slot
        builder = ir.IRBuilder(found_block)
        builder.ret(idx)
        
        # Deleted slot - track first deleted, continue probing
        builder = ir.IRBuilder(deleted_block)
        first_deleted_cur = builder.load(first_deleted_alloca)
        need_update = builder.icmp_signed("<", first_deleted_cur, ir.Constant(ir.IntType(64), 0))
        new_first_deleted = builder.select(need_update, idx, first_deleted_cur)
        builder.store(new_first_deleted, first_deleted_alloca)
        builder.branch(continue_block)
        
        # Continue probing
        builder = ir.IRBuilder(continue_block)
        idx = builder.load(idx_alloca)
        next_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        next_idx = builder.and_(next_idx, mask)
        builder.store(next_idx, idx_alloca)
        builder.branch(loop_block)
    
    def _implement_set_grow(self):
        """Implement set_grow: double capacity and rehash all entries."""
        func = self.set_grow
        func.args[0].name = "set"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        set_ptr = func.args[0]
        
        # Get old entries, len, cap
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        old_entries = builder.load(entries_field)
        
        cap_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        old_cap = builder.load(cap_field)
        
        # New capacity = old_cap * 2
        new_cap = builder.mul(old_cap, ir.Constant(ir.IntType(64), 2))
        
        # Allocate new entries array
        entry_size = ir.Constant(ir.IntType(64), 16)
        new_entries_size = builder.mul(new_cap, entry_size)
        new_entries_raw = builder.call(self.malloc, [new_entries_size])
        new_entries = builder.bitcast(new_entries_raw, self.set_entry_struct.as_pointer())
        
        # Initialize new entries using a loop
        init_idx = builder.alloca(ir.IntType(64), name="init_idx")
        builder.store(ir.Constant(ir.IntType(64), 0), init_idx)
        
        init_loop = func.append_basic_block("init_loop")
        init_body = func.append_basic_block("init_body")
        init_done = func.append_basic_block("init_done")
        
        builder.branch(init_loop)
        
        builder = ir.IRBuilder(init_loop)
        idx = builder.load(init_idx)
        done = builder.icmp_signed(">=", idx, new_cap)
        builder.cbranch(done, init_done, init_body)
        
        builder = ir.IRBuilder(init_body)
        idx = builder.load(init_idx)
        e_ptr = builder.gep(new_entries, [idx])
        state_ptr = builder.gep(e_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        builder.store(ir.Constant(ir.IntType(8), 0), state_ptr)
        new_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(new_idx, init_idx)
        builder.branch(init_loop)
        
        builder = ir.IRBuilder(init_done)
        
        # Update set to use new entries and cap (len stays the same initially)
        builder.store(new_entries, entries_field)
        builder.store(new_cap, cap_field)
        
        # Temporarily set len to 0 for reinsertion
        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_len = builder.load(len_field)
        builder.store(ir.Constant(ir.IntType(64), 0), len_field)
        
        # Rehash all occupied entries from old array
        idx_alloca = builder.alloca(ir.IntType(64), name="idx")
        builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)
        
        loop_block = func.append_basic_block("rehash_loop")
        body_block = func.append_basic_block("rehash_body")
        insert_block = func.append_basic_block("rehash_insert")
        next_block = func.append_basic_block("rehash_next")
        done_block = func.append_basic_block("rehash_done")
        
        builder.branch(loop_block)
        
        # Loop condition
        builder = ir.IRBuilder(loop_block)
        idx = builder.load(idx_alloca)
        cond = builder.icmp_signed("<", idx, old_cap)
        builder.cbranch(cond, body_block, done_block)
        
        # Loop body - check if entry is occupied
        builder = ir.IRBuilder(body_block)
        idx = builder.load(idx_alloca)
        entry_ptr = builder.gep(old_entries, [idx], inbounds=True)
        state_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        state = builder.load(state_ptr)
        is_occupied = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 1))
        builder.cbranch(is_occupied, insert_block, next_block)
        
        # Insert occupied entry into new array
        builder = ir.IRBuilder(insert_block)
        idx = builder.load(idx_alloca)
        entry_ptr = builder.gep(old_entries, [idx], inbounds=True)
        key_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        key = builder.load(key_ptr)
        
        # Call set_add to reinsert
        builder.call(self.set_add, [set_ptr, key])
        builder.branch(next_block)
        
        # Next iteration
        builder = ir.IRBuilder(next_block)
        idx = builder.load(idx_alloca)
        next_idx = builder.add(idx, ir.Constant(ir.IntType(64), 1))
        builder.store(next_idx, idx_alloca)
        builder.branch(loop_block)
        
        # Done - free old entries
        builder = ir.IRBuilder(done_block)
        old_entries_raw = builder.bitcast(old_entries, ir.IntType(8).as_pointer())
        builder.call(self.free, [old_entries_raw])
        builder.ret_void()
    
    def _implement_set_add(self):
        """Implement set_add: add key to set."""
        func = self.set_add
        func.args[0].name = "set"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        set_ptr = func.args[0]
        key = func.args[1]
        
        # Check if we need to grow (load factor > 0.75)
        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)
        
        cap_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_field)
        
        # Check: len * 4 >= cap * 3 (equivalent to len/cap >= 0.75)
        len_times_4 = builder.mul(length, ir.Constant(ir.IntType(64), 4))
        cap_times_3 = builder.mul(cap, ir.Constant(ir.IntType(64), 3))
        need_grow = builder.icmp_signed(">=", len_times_4, cap_times_3)
        
        grow_block = func.append_basic_block("grow")
        insert_block = func.append_basic_block("insert")
        
        builder.cbranch(need_grow, grow_block, insert_block)
        
        # Grow the set
        builder = ir.IRBuilder(grow_block)
        builder.call(self.set_grow, [set_ptr])
        builder.branch(insert_block)
        
        # Find slot and insert
        builder = ir.IRBuilder(insert_block)
        slot = builder.call(self.set_find_slot, [set_ptr, key])
        
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        entry_ptr = builder.gep(entries, [slot], inbounds=True)
        state_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        old_state = builder.load(state_ptr)
        
        # Check if this is a new entry (state != 1)
        is_new = builder.icmp_signed("!=", old_state, ir.Constant(ir.IntType(8), 1))
        
        inc_len_block = func.append_basic_block("inc_len")
        store_block = func.append_basic_block("store")
        
        builder.cbranch(is_new, inc_len_block, store_block)
        
        # Increment len for new entries
        builder = ir.IRBuilder(inc_len_block)
        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)
        new_len = builder.add(length, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_field)
        builder.branch(store_block)
        
        # Store key and set state to occupied
        builder = ir.IRBuilder(store_block)
        key_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        builder.store(key, key_ptr)
        builder.store(ir.Constant(ir.IntType(8), 1), state_ptr)
        
        builder.ret_void()
    
    def _implement_set_has(self):
        """Implement set_has: check if key is in set."""
        func = self.set_has
        func.args[0].name = "set"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        set_ptr = func.args[0]
        key = func.args[1]
        
        # Find slot
        slot = builder.call(self.set_find_slot, [set_ptr, key])
        
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        entry_ptr = builder.gep(entries, [slot], inbounds=True)
        state_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        state = builder.load(state_ptr)
        
        # Check if occupied and key matches
        is_occupied = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 1))
        
        check_key_block = func.append_basic_block("check_key")
        ret_false_block = func.append_basic_block("ret_false")
        
        builder.cbranch(is_occupied, check_key_block, ret_false_block)
        
        # Check key
        builder = ir.IRBuilder(check_key_block)
        key_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entry_key = builder.load(key_ptr)
        key_matches = builder.icmp_signed("==", entry_key, key)
        builder.ret(key_matches)
        
        # Not found
        builder = ir.IRBuilder(ret_false_block)
        builder.ret(ir.Constant(ir.IntType(1), 0))
    
    def _implement_set_remove(self):
        """Implement set_remove: remove key from set, return true if found."""
        func = self.set_remove
        func.args[0].name = "set"
        func.args[1].name = "key"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        set_ptr = func.args[0]
        key = func.args[1]
        
        # Find slot
        slot = builder.call(self.set_find_slot, [set_ptr, key])
        
        entries_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entries = builder.load(entries_field)
        
        entry_ptr = builder.gep(entries, [slot], inbounds=True)
        state_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        state = builder.load(state_ptr)
        
        # Check if occupied
        is_occupied = builder.icmp_signed("==", state, ir.Constant(ir.IntType(8), 1))
        
        check_key_block = func.append_basic_block("check_key")
        ret_false_block = func.append_basic_block("ret_false")
        
        builder.cbranch(is_occupied, check_key_block, ret_false_block)
        
        # Check key matches
        builder = ir.IRBuilder(check_key_block)
        key_ptr = builder.gep(entry_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        entry_key = builder.load(key_ptr)
        key_matches = builder.icmp_signed("==", entry_key, key)
        
        remove_block = func.append_basic_block("remove")
        builder.cbranch(key_matches, remove_block, ret_false_block)
        
        # Remove: set state to deleted (2), decrement len
        builder = ir.IRBuilder(remove_block)
        builder.store(ir.Constant(ir.IntType(8), 2), state_ptr)
        
        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)
        new_len = builder.sub(length, ir.Constant(ir.IntType(64), 1))
        builder.store(new_len, len_field)
        
        builder.ret(ir.Constant(ir.IntType(1), 1))
        
        # Not found
        builder = ir.IRBuilder(ret_false_block)
        builder.ret(ir.Constant(ir.IntType(1), 0))
    
    def _implement_set_len(self):
        """Implement set_len: return number of elements in set."""
        func = self.set_len
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]

        len_field = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        length = builder.load(len_field)

        builder.ret(length)

    def _implement_set_size(self):
        """Implement set_size: return total memory footprint in bytes.

        Size = 24 (header) + cap * 16 (SetEntry array)
        SetEntry is {i64 key, i8 state} = 16 bytes with padding
        """
        func = self.set_size
        func.args[0].name = "set"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        set_ptr = func.args[0]

        # Get cap field (field 2)
        cap_ptr = builder.gep(set_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        cap = builder.load(cap_ptr)

        # Size = 24 (header) + cap * 16 (each SetEntry is 16 bytes)
        entry_array_size = builder.mul(cap, ir.Constant(ir.IntType(64), 16))
        total_size = builder.add(ir.Constant(ir.IntType(64), 24), entry_array_size)

        builder.ret(total_size)

    def _register_set_methods(self):
        """Register Set as a type with methods."""
        self.type_registry["Set"] = self.set_struct
        self.type_fields["Set"] = []  # Internal structure, not user-accessible fields

        self.type_methods["Set"] = {
            "add": "coex_set_add",
            "has": "coex_set_has",
            "remove": "coex_set_remove",
            "len": "coex_set_len",
            "size": "coex_set_size",
        }

        self.functions["coex_set_new"] = self.set_new
        self.functions["coex_set_add"] = self.set_add
        self.functions["coex_set_has"] = self.set_has
        self.functions["coex_set_remove"] = self.set_remove
        self.functions["coex_set_len"] = self.set_len
        self.functions["coex_set_size"] = self.set_size

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
        
        # Allocate AtomicRef struct (8 bytes)
        ref_size = ir.Constant(ir.IntType(64), 8)
        raw_ptr = builder.call(self.malloc, [ref_size])
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
    
    # ========================================================================
    # Channel Implementation
    # ========================================================================
    
    def _create_channel_helpers(self):
        """Create channel runtime functions for sequential execution.
        
        Channel structure:
        - len: current number of items in buffer
        - cap: capacity (0 = unbuffered, stores single value)
        - head: read index (circular buffer)
        - tail: write index (circular buffer)
        - data: buffer for values (stores i64 values)
        - closed: boolean flag
        """
        chan_ptr = self.channel_struct.as_pointer()
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        i1 = ir.IntType(1)
        
        # Register Channel in type registry
        self.type_registry["Channel"] = self.channel_struct
        self.type_methods["Channel"] = {}
        
        # channel_new(capacity: i64) -> Channel*
        self._create_channel_new(chan_ptr, i64)
        
        # channel_send(chan: Channel*, value: i64)
        self._create_channel_send(chan_ptr, i64)
        
        # channel_receive(chan: Channel*) -> i64 (returns 0 if closed/empty)
        self._create_channel_receive(chan_ptr, i64)
        
        # channel_close(chan: Channel*)
        self._create_channel_close(chan_ptr)
    
    def _create_channel_new(self, chan_ptr: ir.Type, i64: ir.Type):
        """Create channel constructor: allocates and initializes channel."""
        func_type = ir.FunctionType(chan_ptr, [i64])
        func = ir.Function(self.module, func_type, name="coex_channel_new")
        self.channel_new = func
        self.functions["coex_channel_new"] = func
        self.type_methods["Channel"]["new"] = "coex_channel_new"
        
        func.args[0].name = "capacity"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        capacity = func.args[0]
        
        # Allocate channel struct (48 bytes = 6 * 8) via GC
        struct_size = ir.Constant(i64, 48)
        type_id = ir.Constant(ir.IntType(32), self.gc.TYPE_CHANNEL)
        raw_ptr = builder.call(self.gc.gc_alloc, [struct_size, type_id])
        chan = builder.bitcast(raw_ptr, chan_ptr)
        
        # Initialize len = 0
        len_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), len_field)
        
        # Initialize cap
        cap_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        builder.store(capacity, cap_field)
        
        # Initialize head = 0
        head_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), head_field)
        
        # Initialize tail = 0
        tail_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(ir.Constant(i64, 0), tail_field)
        
        # Allocate data buffer: max(capacity, 1) * 8 bytes
        # (even unbuffered channels need space for one value)
        one = ir.Constant(i64, 1)
        is_unbuffered = builder.icmp_signed("==", capacity, ir.Constant(i64, 0))
        actual_cap = builder.select(is_unbuffered, one, capacity)
        elem_size = ir.Constant(i64, 8)
        buffer_size = builder.mul(actual_cap, elem_size)
        data_raw = builder.call(self.malloc, [buffer_size])
        
        data_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 4)
        ], inbounds=True)
        builder.store(data_raw, data_field)
        
        # Initialize closed = false
        closed_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 5)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(1), 0), closed_field)
        
        builder.ret(chan)
    
    def _create_channel_send(self, chan_ptr: ir.Type, i64: ir.Type):
        """Create channel send: adds value to buffer, growing if needed."""
        func_type = ir.FunctionType(ir.VoidType(), [chan_ptr, i64])
        func = ir.Function(self.module, func_type, name="coex_channel_send")
        self.channel_send = func
        self.functions["coex_channel_send"] = func
        self.type_methods["Channel"]["send"] = "coex_channel_send"
        
        func.args[0].name = "chan"
        func.args[1].name = "value"
        
        entry = func.append_basic_block("entry")
        check_full = func.append_basic_block("check_full")
        grow_buffer = func.append_basic_block("grow_buffer")
        do_send = func.append_basic_block("do_send")
        done = func.append_basic_block("done")
        
        builder = ir.IRBuilder(entry)
        
        chan = func.args[0]
        value = func.args[1]
        
        # Check if closed
        closed_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 5)
        ], inbounds=True)
        is_closed = builder.load(closed_field)
        builder.cbranch(is_closed, done, check_full)
        
        # Check if buffer is full
        builder.position_at_end(check_full)
        
        len_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        cap_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 1)
        ], inbounds=True)
        data_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 4)
        ], inbounds=True)
        
        current_len = builder.load(len_field)
        cap = builder.load(cap_field)
        
        # Handle unbuffered (cap=0) as cap=1
        one = ir.Constant(i64, 1)
        is_unbuffered = builder.icmp_signed("==", cap, ir.Constant(i64, 0))
        actual_cap = builder.select(is_unbuffered, one, cap)
        
        # Check if full: len >= actual_cap
        is_full = builder.icmp_signed(">=", current_len, actual_cap)
        builder.cbranch(is_full, grow_buffer, do_send)
        
        # Grow buffer: double capacity, realloc, copy
        builder.position_at_end(grow_buffer)
        
        old_data = builder.load(data_field)
        old_cap = builder.load(cap_field)
        
        # New capacity = max(old_cap * 2, 16)
        new_cap = builder.mul(actual_cap, ir.Constant(i64, 2))
        min_cap = ir.Constant(i64, 16)
        use_min = builder.icmp_signed("<", new_cap, min_cap)
        new_cap = builder.select(use_min, min_cap, new_cap)
        
        # Allocate new buffer
        elem_size = ir.Constant(i64, 8)
        new_size = builder.mul(new_cap, elem_size)
        new_data = builder.call(self.malloc, [new_size])
        
        # Copy old data: memcpy(new_data, old_data, current_len * 8)
        copy_size = builder.mul(current_len, elem_size)
        builder.call(self.memcpy, [new_data, old_data, copy_size])
        
        # Free old buffer
        builder.call(self.free, [old_data])
        
        # Update channel fields
        builder.store(new_cap, cap_field)
        builder.store(new_data, data_field)
        
        builder.branch(do_send)
        
        # Do send: store at index = current_len
        builder.position_at_end(do_send)
        
        # Reload after potential growth
        current_len2 = builder.load(len_field)
        data = builder.load(data_field)
        
        # Calculate slot: data + (len * 8)
        elem_size_const = ir.Constant(i64, 8)
        offset = builder.mul(current_len2, elem_size_const)
        slot_ptr = builder.gep(data, [offset])
        slot_i64_ptr = builder.bitcast(slot_ptr, i64.as_pointer())
        builder.store(value, slot_i64_ptr)
        
        # Increment len
        one_const = ir.Constant(i64, 1)
        new_len = builder.add(current_len2, one_const)
        builder.store(new_len, len_field)
        
        builder.branch(done)
        
        builder.position_at_end(done)
        builder.ret_void()
    
    def _create_channel_receive(self, chan_ptr: ir.Type, i64: ir.Type):
        """Create channel receive: removes and returns value from buffer."""
        func_type = ir.FunctionType(i64, [chan_ptr])
        func = ir.Function(self.module, func_type, name="coex_channel_receive")
        self.channel_receive = func
        self.functions["coex_channel_receive"] = func
        self.type_methods["Channel"]["receive"] = "coex_channel_receive"
        
        func.args[0].name = "chan"
        
        entry = func.append_basic_block("entry")
        check_len = func.append_basic_block("check_len")
        do_receive = func.append_basic_block("do_receive")
        return_nil = func.append_basic_block("return_nil")
        
        builder = ir.IRBuilder(entry)
        
        chan = func.args[0]
        
        # Check if has items
        len_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        
        current_len = builder.load(len_field)
        has_items = builder.icmp_signed(">", current_len, ir.Constant(i64, 0))
        builder.cbranch(has_items, do_receive, check_len)
        
        # No items - return nil
        builder.position_at_end(check_len)
        builder.branch(return_nil)
        
        # Do receive
        builder.position_at_end(do_receive)
        
        head_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        data_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 4)
        ], inbounds=True)
        
        head = builder.load(head_field)
        data = builder.load(data_field)
        
        # Read from data[head]
        one = ir.Constant(i64, 1)
        offset = builder.mul(head, ir.Constant(i64, 8))
        slot_ptr = builder.gep(data, [offset])
        slot_i64_ptr = builder.bitcast(slot_ptr, i64.as_pointer())
        value = builder.load(slot_i64_ptr)
        
        # Increment head (no modulo - linear buffer)
        new_head = builder.add(head, one)
        builder.store(new_head, head_field)
        
        # Decrement len
        current_len2 = builder.load(len_field)
        new_len = builder.sub(current_len2, one)
        builder.store(new_len, len_field)
        
        builder.ret(value)
        
        # Return nil (0)
        builder.position_at_end(return_nil)
        builder.ret(ir.Constant(i64, 0))
    
    def _create_channel_close(self, chan_ptr: ir.Type):
        """Create channel close: marks channel as closed."""
        func_type = ir.FunctionType(ir.VoidType(), [chan_ptr])
        func = ir.Function(self.module, func_type, name="coex_channel_close")
        self.channel_close = func
        self.functions["coex_channel_close"] = func
        self.type_methods["Channel"]["close"] = "coex_channel_close"
        
        func.args[0].name = "chan"
        
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        
        chan = func.args[0]
        
        closed_field = builder.gep(chan, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 5)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(1), 1), closed_field)
        
        builder.ret_void()
    
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
            return self.channel_struct.as_pointer()
        
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
        elif isinstance(coex_type, (ListType, MapType, SetType, ChannelType)):
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
        compiler_dir = os.path.dirname(os.path.abspath(__file__))
        self.module_search_paths.append(os.path.join(compiler_dir, "lib"))

        # Load imported modules first (they must be compiled before main program)
        for imp in program.imports:
            self._load_module(imp.module)

        # Register replace aliases
        for rep in program.replaces:
            if rep.module not in self.loaded_modules:
                raise RuntimeError(f"Module '{rep.module}' not imported for replace '{rep.shortname}'")
            self.replace_aliases[rep.shortname] = (rep.module, rep.qualified_name)

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
        
        # Generate global variables
        for global_var in program.globals:
            self._generate_global_var(global_var)
        
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
        
        return self.get_ir()

    # ========================================================================
    # Module Loading
    # ========================================================================

    def _find_module_file(self, module_name: str) -> Optional[str]:
        """Find module file in search paths"""
        filename = f"{module_name}.coex"

        for path in self.module_search_paths:
            full_path = os.path.join(path, filename)
            if os.path.exists(full_path):
                return full_path

        return None

    def _load_module(self, module_name: str) -> ModuleInfo:
        """Load and compile a module, returning its info"""
        # Check cache
        if module_name in self.loaded_modules:
            return self.loaded_modules[module_name]

        # Find module file
        module_path = self._find_module_file(module_name)
        if not module_path:
            searched = ", ".join(self.module_search_paths)
            raise RuntimeError(f"Module not found: {module_name} (searched: {searched})")

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

        # Declare and generate functions with mangled names
        for func in program.functions:
            if func.name == "main":
                continue  # Skip main in modules

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
        field_types = []
        field_info = []
        for field in type_decl.fields:
            field_type = self._substitute_type(field.type_annotation)
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
        
        entry = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)
        
        self.locals = {}
        self.current_function = method
        self.current_type = type_name
        
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
        
        # Restore state
        self.builder = old_builder
        self.locals = old_locals
        self.current_function = old_current_function
        self.current_type = old_current_type
    
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
        old_current_function = self.current_function
        self.current_function = func_decl
        
        # Allocate parameters
        for i, param in enumerate(func_decl.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name
            
            alloca = self.builder.alloca(llvm_param.type, name=param.name)
            self.builder.store(llvm_param, alloca)
            self.locals[param.name] = alloca
        
        # Generate body
        for stmt in func_decl.body:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break
        
        # Add implicit return
        if not self.builder.block.is_terminated:
            if isinstance(llvm_ret, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(llvm_ret, 0))
        
        # Restore state
        self.builder = old_builder
        self.locals = old_locals
        self.current_function = old_current_function
        self.type_substitutions = old_subs
        
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
            elif name in self.globals:
                llvm_type = self.globals[name].type.pointee
                return self._llvm_type_to_coex(llvm_type)
        elif isinstance(expr, ListExpr):
            if expr.elements:
                elem_type = self._infer_type_from_expr(expr.elements[0])
                return ListType(elem_type)
            return ListType(PrimitiveType("int"))
        
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
            
            # Build parameter types (self is implicit first parameter)
            param_types = [self_ptr_type]  # self pointer
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
            
            # Name the self parameter
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
            
            # Create entry block
            entry = llvm_func.append_basic_block(name="entry")
            self.builder = ir.IRBuilder(entry)
            
            # Clear locals and set context
            self.locals = {}
            self.current_function = method
            self.current_type = type_decl.name
            
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
    
    def _generate_global_var(self, decl: GlobalVarDecl):
        """Generate a global variable"""
        llvm_type = self._get_llvm_type(decl.type_annotation)
        global_var = ir.GlobalVariable(self.module, llvm_type, name=decl.name)
        
        # Set initializer
        if isinstance(decl.initializer, IntLiteral):
            global_var.initializer = ir.Constant(llvm_type, decl.initializer.value)
        elif isinstance(decl.initializer, FloatLiteral):
            global_var.initializer = ir.Constant(llvm_type, decl.initializer.value)
        elif isinstance(decl.initializer, BoolLiteral):
            global_var.initializer = ir.Constant(llvm_type, 1 if decl.initializer.value else 0)
        else:
            global_var.initializer = ir.Constant(llvm_type, 0)
        
        self.globals[decl.name] = global_var
    
    def _declare_function(self, func: FunctionDecl):
        """Declare a function (for forward references)"""
        # If generic, store as template
        if func.type_params:
            self.generic_functions[func.name] = func
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
    
    def _generate_function(self, func: FunctionDecl):
        """Generate a function body"""
        # Skip generic functions (they're generated on demand)
        if func.type_params:
            return
        
        llvm_func = self.functions[func.name]
        
        # Create entry block
        entry = llvm_func.append_basic_block(name="entry")
        self.builder = ir.IRBuilder(entry)

        # Initialize GC at start of main function
        if func.name == "main" and self.gc is not None:
            self.gc.inject_gc_init(self.builder)

        # Clear locals
        self.locals = {}
        self.current_function = func

        # Allocate parameters
        for i, param in enumerate(func.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name
            
            # Allocate on stack
            alloca = self.builder.alloca(llvm_param.type, name=param.name)
            self.builder.store(llvm_param, alloca)
            self.locals[param.name] = alloca
        
        # Generate body
        for stmt in func.body:
            self._generate_statement(stmt)
            if self.builder.block.is_terminated:
                break
        
        # Add implicit return if needed
        if not self.builder.block.is_terminated:
            if isinstance(llvm_func.return_value.type, ir.VoidType):
                self.builder.ret_void()
            else:
                self.builder.ret(ir.Constant(llvm_func.return_value.type, 0))
        
        self.current_function = None
    
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
        elif isinstance(stmt, ReturnStmt):
            self._generate_return(stmt)
        elif isinstance(stmt, PrintStmt):
            self._generate_print(stmt)
        elif isinstance(stmt, IfStmt):
            self._generate_if(stmt)
        elif isinstance(stmt, LoopStmt):
            self._generate_loop(stmt)
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
        elif isinstance(stmt, SelectStmt):
            self._generate_select(stmt)
        elif isinstance(stmt, WithinStmt):
            self._generate_within(stmt)
        elif isinstance(stmt, LlvmIrStmt):
            self._generate_llvm_ir_block(stmt)
        elif isinstance(stmt, ExprStmt):
            self._generate_expression(stmt.expr)
    
    def _generate_var_decl(self, stmt: VarDecl):
        """Generate a local variable declaration"""
        if stmt.type_annotation:
            llvm_type = self._get_llvm_type(stmt.type_annotation)
            # Track tuple field info if this is a tuple type
            if isinstance(stmt.type_annotation, TupleType):
                self.tuple_field_info[stmt.name] = stmt.type_annotation.elements
        else:
            # Infer type from initializer
            init_value = self._generate_expression(stmt.initializer)
            llvm_type = init_value.type
            alloca = self.builder.alloca(llvm_type, name=stmt.name)
            self.builder.store(init_value, alloca)
            self.locals[stmt.name] = alloca
            
            # Try to infer tuple info from initializer
            tuple_info = self._infer_tuple_info(stmt.initializer)
            if tuple_info:
                self.tuple_field_info[stmt.name] = tuple_info
            return
        
        alloca = self.builder.alloca(llvm_type, name=stmt.name)
        
        # Generate initializer
        init_value = self._generate_expression(stmt.initializer)
        
        # Cast if needed
        init_value = self._cast_value(init_value, llvm_type)
        
        self.builder.store(init_value, alloca)
        self.locals[stmt.name] = alloca
    
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
                    # Create a local variable
                    alloca = self.builder.alloca(elem_type, name=name)
                    self.builder.store(elem_val, alloca)
                    self.locals[name] = alloca
        else:
            # Not a tuple - error case, but for robustness create dummy vars
            for name in stmt.names:
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
        
        return value
    
    def _generate_assignment(self, stmt: Assignment):
        """Generate an assignment"""
        value = self._generate_expression(stmt.value)
        
        # Handle tuple destructuring: (a, b) = expr
        if isinstance(stmt.target, TupleExpr):
            self._generate_tuple_assignment(stmt.target, value)
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
        
        # Handle compound assignment
        if stmt.op != AssignOp.ASSIGN:
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
        
        if ptr:
            self.builder.store(value, ptr)
    
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
    
    def _get_lvalue(self, expr: Expr) -> Optional[ir.Value]:
        """Get pointer to an lvalue expression"""
        if isinstance(expr, Identifier):
            name = expr.name
            if name in self.locals:
                return self.locals[name]
            elif name in self.globals:
                return self.globals[name]
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
            value = self._generate_expression(stmt.value)
            
            # In matrix formula context, write to buffer and continue loop
            if self.current_matrix is not None:
                self._generate_matrix_return(value)
                # Branch to x_loop_inc (next cell)
                # Find the increment block
                func = self.builder.function
                for block in func.blocks:
                    if block.name == "x_loop_inc":
                        self.builder.branch(block)
                        return
            
            self.builder.ret(value)
        else:
            self.builder.ret_void()
    
    def _generate_print(self, stmt: PrintStmt):
        """Generate a print statement"""
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
        for s in stmt.then_body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
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
            for s in elif_body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
            if not self.builder.block.is_terminated:
                self.builder.branch(merge_block)
        
        # Generate else block
        if stmt.else_body:
            self.builder.position_at_end(else_block)
            for s in stmt.else_body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
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
            null = ir.Constant(value.type, None)
            return self.builder.icmp_unsigned("!=", value, null)
        return value
    
    def _generate_loop(self, stmt: LoopStmt):
        """Generate a loop statement"""
        func = self.builder.function
        
        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = self._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in self.locals:
                lv_alloca = self.builder.alloca(ir.IntType(64), name=lv_name)
                self.locals[lv_name] = lv_alloca
        
        loop_block = func.append_basic_block("loop_body")
        exit_block = func.append_basic_block("loop_exit")
        
        # Save loop blocks for break/continue
        old_exit = self.loop_exit_block
        old_continue = self.loop_continue_block
        self.loop_exit_block = exit_block
        self.loop_continue_block = loop_block
        
        # Jump to loop
        self.builder.branch(loop_block)
        
        # Generate loop body
        self.builder.position_at_end(loop_block)
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        
        if not self.builder.block.is_terminated:
            self.builder.branch(loop_block)
        
        # Continue after loop
        self.builder.position_at_end(exit_block)
        
        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue
    
    def _generate_for(self, stmt: ForStmt):
        """Generate a for loop"""
        func = self.builder.function
        
        # Check if iterable is a range() call
        if isinstance(stmt.iterable, CallExpr) and isinstance(stmt.iterable.callee, Identifier):
            if stmt.iterable.callee.name == "range":
                self._generate_range_for(stmt)
                return
        
        # Check if iterable is a RangeExpr (start..end)
        if isinstance(stmt.iterable, RangeExpr):
            self._generate_range_expr_for(stmt)
            return
        
        # Check if iterable is a list or array
        if isinstance(stmt.iterable, (Identifier, ListExpr, CallExpr, IndexExpr, MethodCallExpr)):
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

        # For other iterables, we need iterator protocol
        # For now, just execute body once as fallback
        for s in stmt.body:
            self._generate_statement(s)
    
    def _generate_range_for(self, stmt: ForStmt):
        """Generate for i in range(start, end)"""
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
        
        # Allocate loop variable
        loop_var = self.builder.alloca(ir.IntType(64), name=var_name)
        self.builder.store(start, loop_var)
        self.locals[var_name] = loop_var
        
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
        
        # Restore loop blocks
        self.loop_exit_block = old_exit
        self.loop_continue_block = old_continue
    
    def _generate_range_expr_for(self, stmt: ForStmt):
        """Generate for i in start..end"""
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
        
        # Same as range_for
        loop_var = self.builder.alloca(ir.IntType(64), name=stmt.var_name)
        self.builder.store(start, loop_var)
        self.locals[stmt.var_name] = loop_var
        
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
    
    def _generate_select(self, stmt: SelectStmt):
        """Generate a select statement (sequential implementation).
        
        Sequential semantics:
        - Check each channel in order (based on strategy)
        - Execute the first case whose channel has data (len > 0)
        - If no channel has data, fall through (no blocking)
        
        Strategies:
        - DEFAULT/PRIORITY: check cases in declaration order
        - FAIR: round-robin (for sequential, same as default)
        - RANDOM: check in random order (deterministic for reproducibility)
        """
        if not stmt.cases:
            return
        
        func = self.builder.function
        i64 = ir.IntType(64)
        
        # Pre-allocate variables for all cases BEFORE any branches
        # This ensures the allocas dominate all uses
        case_allocas = {}
        for case in stmt.cases:
            if case.var_name not in self.locals:
                var_alloca = self.builder.alloca(i64, name=case.var_name)
                self.locals[case.var_name] = var_alloca
                case_allocas[case.var_name] = var_alloca
            else:
                case_allocas[case.var_name] = self.locals[case.var_name]
        
        # Create blocks for each case and final merge
        case_check_blocks = []
        case_body_blocks = []
        for i, case in enumerate(stmt.cases):
            case_check_blocks.append(func.append_basic_block(f"select_check_{i}"))
            case_body_blocks.append(func.append_basic_block(f"select_body_{i}"))
        
        select_end = func.append_basic_block("select_end")
        
        # Determine case order based on strategy
        case_order = list(range(len(stmt.cases)))
        if stmt.strategy == SelectStrategy.RANDOM:
            # For deterministic testing, use a simple shuffle based on case count
            # In real concurrent impl, would use actual randomness
            import random
            random.seed(len(stmt.cases))  # Deterministic for testing
            random.shuffle(case_order)
        # FAIR would need persistent state; for sequential, treat as default
        # PRIORITY is same as default (first case has highest priority)
        
        # Branch to first check
        self.builder.branch(case_check_blocks[0])
        
        # Generate check and body for each case
        for idx, case_idx in enumerate(case_order):
            case = stmt.cases[case_idx]
            check_block = case_check_blocks[idx]
            body_block = case_body_blocks[idx]
            next_check = case_check_blocks[idx + 1] if idx + 1 < len(case_order) else select_end
            
            # Check block: see if channel has data
            self.builder.position_at_end(check_block)
            channel = self._generate_expression(case.channel)
            
            # Load channel len field (field 0)
            len_field = self.builder.gep(channel, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), 0)
            ], inbounds=True)
            chan_len = self.builder.load(len_field)
            
            # Check if len > 0
            has_data = self.builder.icmp_signed(">", chan_len, ir.Constant(i64, 0))
            self.builder.cbranch(has_data, body_block, next_check)
            
            # Body block: receive value and execute case body
            self.builder.position_at_end(body_block)
            
            # Receive from channel
            received = self.builder.call(self.channel_receive, [channel])
            
            # Store in pre-allocated variable
            var_alloca = case_allocas[case.var_name]
            self.builder.store(received, var_alloca)
            
            # Execute case body
            for s in case.body:
                self._generate_statement(s)
                if self.builder.block.is_terminated:
                    break
            
            # Branch to end (if not already terminated by break/return)
            if not self.builder.block.is_terminated:
                self.builder.branch(select_end)
        
        # Continue from select_end
        self.builder.position_at_end(select_end)
    
    def _generate_within(self, stmt: WithinStmt):
        """Generate a within statement (sequential implementation).
        
        Sequential semantics:
        - Execute the body (can't actually timeout without threads/preemption)
        - The else clause is never executed in sequential mode
        - The timeout expression is evaluated but ignored
        
        In concurrent mode, this would set up a deadline and cancel
        if exceeded, branching to the else clause.
        """
        # Evaluate timeout expression (for side effects, though typically none)
        # This ensures the expression is valid even if we don't use it
        if stmt.timeout:
            self._generate_expression(stmt.timeout)
        
        # In sequential mode, just execute the body
        # No timeout can occur because there's no preemption
        for s in stmt.body:
            self._generate_statement(s)
            if self.builder.block.is_terminated:
                break
        
        # Note: else_body is intentionally not executed in sequential mode
        # because without threading, the body will always complete
        # (unless it has an infinite loop, but that's a bug)
    
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
        
        elif isinstance(expr, TernaryExpr):
            return self._generate_ternary(expr)
        
        elif isinstance(expr, ListExpr):
            return self._generate_list(expr)
        
        elif isinstance(expr, MapExpr):
            return self._generate_map(expr)

        elif isinstance(expr, SetExpr):
            return self._generate_set(expr)

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

        else:
            return ir.Constant(ir.IntType(64), 0)
    
    def _generate_identifier(self, expr: Identifier) -> ir.Value:
        """Generate code for identifier reference"""
        name = expr.name
        
        if name in self.locals:
            return self.builder.load(self.locals[name], name=name)
        elif name in self.globals:
            return self.builder.load(self.globals[name], name=name)
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
            
            # Unknown variable
            return ir.Constant(ir.IntType(64), 0)
    
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
            # a ?? b -> a if a != nil else b
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

            # Note: len() removed as builtin - use .len() method instead

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
                # Trigger garbage collection
                self.builder.call(self.gc.gc_collect, [])
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
    
    def _generate_type_constructor(self, type_name: str, args: PyList[Expr], named_args: Dict[str, Expr]) -> ir.Value:
        """Generate code for type constructor: Point(x: 1, y: 2)"""
        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]

        # Calculate size - estimate 8 bytes per field (works for most types)
        size = len(field_info) * 8 if field_info else 8
        size_val = ir.Constant(ir.IntType(64), size)

        # Allocate via GC with registered type ID
        type_id = ir.Constant(ir.IntType(32), self.gc.get_type_id(type_name))
        raw_ptr = self.builder.call(self.gc.gc_alloc, [size_val, type_id])
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
        for i, (field_name, field_type) in enumerate(field_info):
            field_ptr = self.builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i)
            ], inbounds=True)
            
            if field_name in field_values:
                value = field_values[field_name]
                # Cast if needed
                expected_type = self._get_llvm_type(field_type)
                value = self._cast_value(value, expected_type)
                self.builder.store(value, field_ptr)
            else:
                # Default initialize to zero
                expected_type = self._get_llvm_type(field_type)
                default = self._get_default_value_for_llvm(expected_type)
                self.builder.store(default, field_ptr)
        
        return ptr
    
    def _generate_type_new(self, type_name: str, args: PyList[Expr]) -> ir.Value:
        """Generate code for Type.new() - allocate and zero-initialize"""
        # Special handling for built-in types
        if type_name == "Map":
            return self.builder.call(self.map_new, [])
        
        if type_name == "Set":
            return self.builder.call(self.set_new, [])
        
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
        
        # Check if this is a Channel type (or generic Channel<T>)
        if type_name == "Channel" or type_name.startswith("Channel_"):
            # Channel.new() or Channel.new(buffer: N)
            # Default capacity is 0 (unbuffered)
            capacity = ir.Constant(ir.IntType(64), 0)
            
            # Check for buffer argument
            if args:
                capacity = self._generate_expression(args[0])
                capacity = self._cast_value(capacity, ir.IntType(64))
            
            return self.builder.call(self.channel_new, [capacity])
        
        struct_type = self.type_registry[type_name]
        field_info = self.type_fields[type_name]
        
        # Allocate
        size = len(field_info) * 8 if field_info else 8  # Simplified size calculation
        size_val = ir.Constant(ir.IntType(64), size)
        
        raw_ptr = self.builder.call(self.malloc, [size_val])
        ptr = self.builder.bitcast(raw_ptr, struct_type.as_pointer())
        
        # Zero-initialize all fields
        for i, (field_name, field_type) in enumerate(field_info):
            field_ptr = self.builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i)
            ], inbounds=True)
            
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
        raw_ptr = self.builder.call(self.gc.gc_alloc, [size_val, type_id])
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
                        arg_val = self._cast_value(arg_val, expected)
                    args.append(arg_val)
                
                result = self.builder.call(func, args)
                
                # Special handling for List.get and Array.get - returns pointer that needs dereferencing
                if (type_name == "List" or type_name == "Array") and method == "get":
                    # Result is i8*, need to load as i64
                    typed_ptr = self.builder.bitcast(result, ir.IntType(64).as_pointer())
                    return self.builder.load(typed_ptr)

                return result
        
        # Built-in methods for primitive types
        if method == "new":
            # Type.new() - already handled above for known types
            return ir.Constant(ir.IntType(8).as_pointer(), None)
        
        if method == "send":
            # channel.send(value) - call channel_send
            if expr.args and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Channel":
                    value = self._generate_expression(expr.args[0])
                    value = self._cast_value(value, ir.IntType(64))
                    self.builder.call(self.channel_send, [obj, value])
                    return ir.Constant(ir.IntType(64), 0)
            return ir.Constant(ir.IntType(64), 0)
        
        if method == "receive":
            # channel.receive() - call channel_receive
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Channel":
                    return self.builder.call(self.channel_receive, [obj])
            return ir.Constant(ir.IntType(64), 0)
        
        if method == "close":
            # channel.close() - call channel_close
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Channel":
                    self.builder.call(self.channel_close, [obj])
                    return ir.Constant(ir.IntType(64), 0)
            return ir.Constant(ir.IntType(64), 0)
        
        if method == "append":
            # list.append(value) - call list_append
            if expr.args and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    elem_val = self._generate_expression(expr.args[0])
                    elem_type = elem_val.type
                    
                    # Calculate element size
                    if isinstance(elem_type, ir.IntType):
                        size = elem_type.width // 8
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        # For tuples/structs, sum up element sizes
                        size = sum(
                            e.width // 8 if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8
                    
                    elem_size = ir.Constant(ir.IntType(64), size)
                    
                    # Store element to temp and get pointer
                    temp = self.builder.alloca(elem_type, name="append_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())
                    
                    self.builder.call(self.list_append, [obj, temp_ptr, elem_size])
                    return ir.Constant(ir.IntType(64), 0)

                # Check if this is an Array - Array.append returns a NEW array
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    elem_val = self._generate_expression(expr.args[0])
                    elem_type = elem_val.type

                    # Calculate element size
                    if isinstance(elem_type, ir.IntType):
                        size = elem_type.width // 8
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        size = sum(
                            e.width // 8 if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
                    temp = self.builder.alloca(elem_type, name="array_append_elem")
                    self.builder.store(elem_val, temp)
                    temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    # Call array_append which returns a NEW array
                    return self.builder.call(self.array_append, [obj, temp_ptr, elem_size])

            return ir.Constant(ir.IntType(64), 0)

        if method == "set":
            # array.set(index, value) - returns a NEW array with element at index replaced
            if len(expr.args) >= 2 and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    index = self._generate_expression(expr.args[0])
                    elem_val = self._generate_expression(expr.args[1])
                    elem_type = elem_val.type

                    # Calculate element size
                    if isinstance(elem_type, ir.IntType):
                        size = elem_type.width // 8
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    elif isinstance(elem_type, ir.LiteralStructType):
                        size = sum(
                            e.width // 8 if isinstance(e, ir.IntType) else 8
                            for e in elem_type.elements
                        )
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    # Store element to temp and get pointer
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

        if method == "packed":
            # List.packed() -> Array or Set.packed() -> Array
            # Convert collection to dense Array
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    return self._list_to_array(obj)
                if hasattr(pointee, 'name') and pointee.name == "struct.Set":
                    return self._set_to_array(obj)
            return ir.Constant(ir.IntType(64), 0)

        if method == "unpacked":
            # Array.unpacked() -> List
            # Convert Array to persistent List
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    return self._array_to_list(obj)
            return ir.Constant(ir.IntType(64), 0)

        # Generic method lookup failed
        return ir.Constant(ir.IntType(64), 0)
    
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
                return self.builder.load(field_ptr)
        
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
                    typed_ptr = self.builder.bitcast(result, ir.IntType(64).as_pointer())
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
                typed_ptr = self.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
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
                
                # For now, assume int64 elements - load as i64
                # A proper implementation would track element types
                typed_ptr = self.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
                return self.builder.load(typed_ptr)
            
            # String indexing
            ptr = self.builder.gep(obj, [index])
            return self.builder.load(ptr)
        
        return ir.Constant(ir.IntType(64), 0)
    
    def _generate_ternary(self, expr: TernaryExpr) -> ir.Value:
        """Generate code for ternary expression"""
        func = self.builder.function
        
        then_block = func.append_basic_block("tern_then")
        else_block = func.append_basic_block("tern_else")
        merge_block = func.append_basic_block("tern_merge")
        
        cond = self._generate_expression(expr.condition)
        cond = self._to_bool(cond)
        
        self.builder.cbranch(cond, then_block, else_block)
        
        self.builder.position_at_end(then_block)
        then_val = self._generate_expression(expr.then_expr)
        then_block = self.builder.block
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
        
        # Calculate element size
        if isinstance(elem_type, ir.IntType):
            size = elem_type.width // 8
        elif isinstance(elem_type, ir.DoubleType):
            size = 8
        elif isinstance(elem_type, ir.PointerType):
            size = 8
        elif isinstance(elem_type, ir.LiteralStructType):
            # For tuples/structs, sum up element sizes
            size = sum(
                e.width // 8 if isinstance(e, ir.IntType) else 8
                for e in elem_type.elements
            )
        else:
            size = 8
        
        elem_size = ir.Constant(ir.IntType(64), size)
        
        # Create new list
        list_ptr = self.builder.call(self.list_new, [elem_size])
        
        # Append each element
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
            
            # Append
            self.builder.call(self.list_append, [list_ptr, temp_ptr, elem_size])
        
        return list_ptr
    
    def _generate_map(self, expr: MapExpr) -> ir.Value:
        """Generate code for map literal: {key: value, ...}"""
        # Create empty map
        map_ptr = self.builder.call(self.map_new, [])

        # Add each entry
        for key_expr, value_expr in expr.entries:
            key = self._generate_expression(key_expr)
            value = self._generate_expression(value_expr)
            # Cast to i64 for map storage
            key_i64 = self._cast_value(key, ir.IntType(64))
            value_i64 = self._cast_value(value, ir.IntType(64))
            self.builder.call(self.map_set, [map_ptr, key_i64, value_i64])

        return map_ptr

    def _generate_set(self, expr: SetExpr) -> ir.Value:
        """Generate code for set literal: {a, b, c}"""
        # Create empty set
        set_ptr = self.builder.call(self.set_new, [])

        # Add each element
        for elem_expr in expr.elements:
            elem = self._generate_expression(elem_expr)
            # Cast to i64 for set storage
            elem_i64 = self._cast_value(elem, ir.IntType(64))
            self.builder.call(self.set_add, [set_ptr, elem_i64])

        return set_ptr
    
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
        
        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "list")
        
        # Return the result list
        return self.builder.load(result_alloca)
    
    def _generate_set_comprehension(self, expr: SetComprehension) -> ir.Value:
        """Generate code for set comprehension using proper Set type."""
        # Create result set
        set_ptr = self.builder.call(self.set_new, [])
        
        result_var = f"__comp_result_{self.lambda_counter}"
        self.lambda_counter += 1
        result_alloca = self.builder.alloca(self.set_struct.as_pointer(), name=result_var)
        self.builder.store(set_ptr, result_alloca)
        
        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "set")
        
        return self.builder.load(result_alloca)
    
    def _generate_map_comprehension(self, expr: MapComprehension) -> ir.Value:
        """Generate code for map comprehension."""
        # Create result map
        map_ptr = self.builder.call(self.map_new, [])
        
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
            
            # Store in temp and append to list
            temp = self.builder.alloca(ir.IntType(64))
            stored_val = self._cast_value(val, ir.IntType(64))
            self.builder.store(stored_val, temp)
            temp_ptr = self.builder.bitcast(temp, ir.IntType(8).as_pointer())
            
            result_list = self.builder.load(result_alloca)
            elem_size = ir.Constant(ir.IntType(64), 8)
            self.builder.call(self.list_append, [result_list, temp_ptr, elem_size])
            
        elif comp_type == "set":
            # Evaluate body expression and add to set
            key = self._generate_expression(body)
            key_i64 = self._cast_value(key, ir.IntType(64))
            
            result_set = self.builder.load(result_alloca)
            self.builder.call(self.set_add, [result_set, key_i64])
            
        elif comp_type == "map":
            # body is (key_expr, value_expr)
            key_expr, value_expr = body
            key = self._generate_expression(key_expr)
            value = self._generate_expression(value_expr)
            
            key_i64 = self._cast_value(key, ir.IntType(64))
            value_i64 = self._cast_value(value, ir.IntType(64))
            
            result_map = self.builder.load(result_alloca)
            self.builder.call(self.map_set, [result_map, key_i64, value_i64])
    
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

        # Infer from pattern structure
        pattern = stmt.pattern
        if isinstance(pattern, TuplePattern):
            # For tuple patterns, assume i64 for each element
            elem_types = [ir.IntType(64) for _ in pattern.elements]
            return ir.LiteralStructType(elem_types)

        # Default to i64
        return ir.IntType(64)

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
        #   i64 generation
        # }
        struct_name = f"struct.Matrix_{name}"
        matrix_struct = ir.global_context.get_identified_type(struct_name)
        matrix_struct.set_body(
            ir.IntType(64),           # width
            ir.IntType(64),           # height
            elem_type.as_pointer(),   # read_buffer
            elem_type.as_pointer(),   # write_buffer
            ir.IntType(64),           # generation
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
        
        # Allocate matrix struct
        struct_size = ir.Constant(ir.IntType(64), 40)  # 5 * 8 bytes
        raw_ptr = builder.call(self.malloc, [struct_size])
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
        
        # Allocate read buffer
        read_raw = builder.call(self.malloc, [buffer_size])
        read_buffer = builder.bitcast(read_raw, elem_type.as_pointer())
        read_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 2)
        ], inbounds=True)
        builder.store(read_buffer, read_field)
        
        # Allocate write buffer
        write_raw = builder.call(self.malloc, [buffer_size])
        write_buffer = builder.bitcast(write_raw, elem_type.as_pointer())
        write_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 3)
        ], inbounds=True)
        builder.store(write_buffer, write_field)
        
        # Initialize generation to 0
        gen_field = builder.gep(matrix_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 4)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), 0), gen_field)
        
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
        
        # Increment generation
        gen_field = self.builder.gep(self_ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 4)
        ], inbounds=True)
        gen = self.builder.load(gen_field)
        next_gen = self.builder.add(gen, ir.Constant(i64, 1))
        self.builder.store(next_gen, gen_field)
        
        self.builder.ret_void()
        
        # Restore state
        self.locals = saved_locals
        self.current_matrix = saved_matrix
        self.current_cell_x = saved_cell_x
        self.current_cell_y = saved_cell_y
    
    def _get_type_size(self, llvm_type: ir.Type) -> int:
        """Get size of LLVM type in bytes"""
        if isinstance(llvm_type, ir.IntType):
            return llvm_type.width // 8
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
            elif isinstance(stmt, LoopStmt):
                for s in stmt.body:
                    collect_from_stmt(s)
            elif isinstance(stmt, MatchStmt):
                for arm in stmt.arms:
                    for s in arm.body:
                        collect_from_stmt(s)
            elif isinstance(stmt, WithinStmt):
                for s in stmt.body:
                    collect_from_stmt(s)
                if stmt.else_body:
                    for s in stmt.else_body:
                        collect_from_stmt(s)
            elif isinstance(stmt, SelectStmt):
                for case in stmt.cases:
                    var_names.add(case.var_name)
                    for s in case.body:
                        collect_from_stmt(s)
        
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
