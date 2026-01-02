"""
Type System Module for Coex Code Generator

This module provides type conversion, checking, and inference utilities.

Type conversion:
- _get_llvm_type: Convert Coex type to LLVM IR type
- _llvm_type_to_coex: Convert LLVM type back to Coex type
- _cast_value: Cast value to target LLVM type

Type checking:
- _is_primitive_coex_type: Check if type is primitive (int, float, bool, byte, char)
- _is_heap_type: Check if type needs GC tracking
- _is_reference_type: Check if type is a pointer type
- _is_collection_coex_type: Check if type is a collection

Type inference:
- _infer_type_from_expr: Infer Coex type from expression
- _unify_types: Unify types for generic type inference

Utilities:
- _compute_map_flags: Compute GC flags for Map types
- _compute_set_flags: Compute GC flags for Set types
- _get_type_size: Get size of LLVM type in bytes
- _get_type_name_from_ptr: Extract type name from pointer type
"""
from typing import TYPE_CHECKING, Optional, Dict
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator
    from ast_nodes import Type, Expr


class TypesGenerator:
    """Provides type system utilities for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def builder(self):
        return self.codegen.builder

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_fields(self):
        return self.codegen.type_fields

    @property
    def string_struct(self):
        return self.codegen.string_struct

    @property
    def list_struct(self):
        return self.codegen.list_struct

    @property
    def map_struct(self):
        return self.codegen.map_struct

    @property
    def set_struct(self):
        return self.codegen.set_struct

    @property
    def array_struct(self):
        return self.codegen.array_struct

    @property
    def json_struct(self):
        return self.codegen.json_struct

    @property
    def result_struct(self):
        return self.codegen.result_struct

    # ========================================================================
    # Type Conversion Methods
    # ========================================================================

    def get_llvm_type(self, coex_type: 'Type') -> ir.Type:
        """Convert Coex type to LLVM type.

        Handles all Coex types:
        - Primitives: int, float, bool, string, byte, char, json
        - Atomics: atomic_int, atomic_float, atomic_bool
        - Collections: List, Map, Set, Array
        - Optionals: T?
        - Results: Result<T, E>
        - Tuples: (T1, T2, ...)
        - Functions: (T1, T2) -> R
        - Named types: user-defined structs and enums
        """
        return self.codegen._get_llvm_type(coex_type)

    def llvm_type_to_coex(self, llvm_type: ir.Type) -> 'Type':
        """Convert LLVM type back to Coex type (approximate).

        Used for type inference when we have LLVM values but need Coex types.
        """
        return self.codegen._llvm_type_to_coex(llvm_type)

    def cast_value(self, value: ir.Value, target_type: ir.Type) -> ir.Value:
        """Cast value to target type if needed.

        Handles:
        - Int width conversions (zext, trunc)
        - Int <-> float conversions
        - Pointer <-> int conversions
        - Value to optional wrapping
        """
        return self.codegen._cast_value(value, target_type)

    def cast_value_with_builder(self, builder: ir.IRBuilder, value: ir.Value,
                                 target_type: ir.Type) -> ir.Value:
        """Cast value to target type using explicit builder."""
        return self.codegen._cast_value_with_builder(builder, value, target_type)

    # ========================================================================
    # Type Checking Methods
    # ========================================================================

    def is_primitive_coex_type(self, coex_type: 'Type') -> bool:
        """Check if a Coex type is a primitive (int, float, bool, byte, char)."""
        return self.codegen._is_primitive_coex_type(coex_type)

    def is_heap_type(self, coex_type: 'Type') -> bool:
        """Check if a Coex type is heap-allocated and needs GC root tracking.

        Heap types: List, Set, Map, Array, String, user-defined types
        Stack types: int, float, bool, byte, char, tuples of primitives
        """
        return self.codegen._is_heap_type(coex_type)

    def is_reference_type(self, coex_type: 'Type') -> bool:
        """Check if a Coex type is a reference (pointer) type for GC tracking."""
        return self.codegen._is_reference_type(coex_type)

    def is_collection_coex_type(self, coex_type: 'Type') -> bool:
        """Check if a Coex type is a collection (List, Set, Map, Array, String)."""
        return self.codegen._is_collection_coex_type(coex_type)

    def needs_parameter_copy(self, coex_type: 'Type') -> bool:
        """Check if a parameter type needs to be copied on function entry.

        With immutable heap semantics, returns False - no copying needed.
        """
        return self.codegen._needs_parameter_copy(coex_type)

    # ========================================================================
    # Type Inference Methods
    # ========================================================================

    def infer_type_from_expr(self, expr: 'Expr') -> 'Type':
        """Infer the Coex type of an expression.

        Handles literals, identifiers, collections, calls, member access, indexing.
        """
        return self.codegen._infer_type_from_expr(expr)

    def unify_types(self, param_type: 'Type', arg_type: 'Type',
                    inferred: Dict[str, 'Type']):
        """Unify a parameter type with an argument type to infer type parameters."""
        return self.codegen._unify_types(param_type, arg_type, inferred)

    def unify_types_with_params(self, param_type: 'Type', arg_type: 'Type',
                                 inferred: Dict[str, 'Type'], param_names: set):
        """Unify types with explicit parameter name set."""
        return self.codegen._unify_types_with_params(param_type, arg_type,
                                                      inferred, param_names)

    # ========================================================================
    # GC Flag Computation
    # ========================================================================

    def compute_map_flags(self, key_type: 'Type', value_type: 'Type') -> int:
        """Compute the GC flags for a Map based on key and value types.

        Returns an integer with:
        - bit 0 set if key is a heap pointer
        - bit 1 set if value is a heap pointer
        """
        return self.codegen._compute_map_flags(key_type, value_type)

    def compute_set_flags(self, elem_type: 'Type') -> int:
        """Compute the GC flags for a Set based on element type.

        Returns an integer with:
        - bit 0 set if element is a heap pointer
        """
        return self.codegen._compute_set_flags(elem_type)

    # ========================================================================
    # Type Utilities
    # ========================================================================

    def get_type_size(self, llvm_type: ir.Type) -> int:
        """Get size of LLVM type in bytes."""
        return self.codegen._get_type_size(llvm_type)

    def get_type_name_from_ptr(self, llvm_type: ir.Type) -> Optional[str]:
        """Get type name from pointer type (e.g., struct.Point* -> Point)."""
        return self.codegen._get_type_name_from_ptr(llvm_type)

    def get_receiver_type(self, expr: 'Expr') -> Optional['Type']:
        """Get the Coex type of a receiver expression.

        Handles chained method calls like a.set(0, x).set(1, y).
        """
        return self.codegen._get_receiver_type(expr)
