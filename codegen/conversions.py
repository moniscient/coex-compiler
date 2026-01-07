"""
Collection Conversion Code Generation for Coex.

This module handles:
- List <-> Array conversions (_list_to_array, _array_to_list)
- Set <-> Array/List conversions (_set_to_array, _array_to_set, _list_to_set)
- Implicit collection conversion with warnings
- Deep copy operations for collections
- Value semantics helpers
- Type checking utilities for heap and collection types
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Tuple, Optional

from ast_nodes import (
    Type, ListType, ArrayType, SetType, MapType, PrimitiveType, NamedType, TupleType,
    Expr, Identifier, CallExpr, MemberExpr
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ConversionGenerator:
    """Handles collection conversions and type-related utilities for Coex code generation."""

    def __init__(self, cg: 'CodeGenerator'):
        self.cg = cg

    def list_to_array(self, list_ptr: ir.Value) -> ir.Value:
        """Convert a List to an Array (List.packed() -> Array).

        Creates a new Array with the same elements as the List.
        For Persistent Vector List, we iterate using list_get since
        the data is stored in a tree structure, not contiguously.
        """
        func = self.cg.builder.function
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get List length
        list_len = self.cg.builder.call(self.cg.list_len, [list_ptr])

        # Get List elem_size (field 5 in PV structure)
        elem_size_ptr = self.cg.builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 5)], inbounds=True)
        elem_size = self.cg.builder.load(elem_size_ptr)

        # Create new Array with same capacity as List length
        array_ptr = self.cg.builder.call(self.cg.array_new, [list_len, elem_size])

        # Set Array len = list_len (field 2 in Array layout)
        array_len_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        self.cg.builder.store(list_len, array_len_ptr)

        # Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.cg.builder.load(array_owner_handle_ptr)
        array_owner = self.cg.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.cg.builder.load(array_offset_ptr)
        array_data = self.cg.builder.gep(array_owner, [array_offset])

        # For Persistent Vector List, we can't just memcpy - we need to iterate
        # through the list using list_get since data may be in tree structure.
        # Loop through each element and copy to array

        idx_alloca = self.cg.builder.alloca(i64, name="list_to_arr_idx")
        self.cg.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("list_to_arr_cond")
        body_block = func.append_basic_block("list_to_arr_body")
        end_block = func.append_basic_block("list_to_arr_end")

        self.cg.builder.branch(cond_block)

        # Condition: idx < list_len
        self.cg.builder.position_at_end(cond_block)
        idx = self.cg.builder.load(idx_alloca)
        cond = self.cg.builder.icmp_signed("<", idx, list_len)
        self.cg.builder.cbranch(cond, body_block, end_block)

        # Body: copy element from list to array
        self.cg.builder.position_at_end(body_block)
        idx = self.cg.builder.load(idx_alloca)

        # Get element from list
        elem_ptr = self.cg.builder.call(self.cg.list_get, [list_ptr, idx])

        # Calculate destination in array
        offset = self.cg.builder.mul(idx, elem_size)
        dest_ptr = self.cg.builder.gep(array_data, [offset])

        # Copy element
        self.cg.builder.call(self.cg.memcpy, [dest_ptr, elem_ptr, elem_size])

        # Increment index
        next_idx = self.cg.builder.add(idx, ir.Constant(i64, 1))
        self.cg.builder.store(next_idx, idx_alloca)
        self.cg.builder.branch(cond_block)

        # End
        self.cg.builder.position_at_end(end_block)

        return array_ptr

    def set_to_array(self, set_ptr: ir.Value) -> ir.Value:
        """Convert a Set to an Array (Set.packed() -> Array).

        Creates a new Array with the elements from the HAMT-based Set.
        Uses set_to_list to collect keys, then copies to array.
        """
        func = self.cg.builder.function
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get Set len (number of elements)
        set_len = self.cg.builder.call(self.cg.set_len, [set_ptr])

        # Create Array with capacity = set_len, elem_size = 8 (i64 keys)
        elem_size = ir.Constant(i64, 8)
        array_ptr = self.cg.builder.call(self.cg.array_new, [set_len, elem_size])

        # Get list of keys from set using set_to_list (HAMT-based)
        key_list = self.cg.builder.call(self.cg.set_to_list, [set_ptr])

        # Get list data pointer (field 3 in List struct) - Phase 4: handle
        list_data_handle_ptr = self.cg.builder.gep(key_list, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        list_data_handle = self.cg.builder.load(list_data_handle_ptr)
        list_data = self.cg.builder.inttoptr(list_data_handle, i8_ptr)

        # Get array data pointer: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.cg.builder.load(array_owner_handle_ptr)
        array_owner = self.cg.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.cg.builder.load(array_offset_ptr)
        array_data = self.cg.builder.gep(array_owner, [array_offset])

        # Copy list data to array: len * 8 bytes
        copy_size = self.cg.builder.mul(set_len, elem_size)
        self.cg.builder.call(self.cg.memcpy, [array_data, list_data, copy_size])

        # Set array len (field 2 in Array layout)
        arr_len_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        self.cg.builder.store(set_len, arr_len_ptr)

        return array_ptr

    def array_to_list(self, array_ptr: ir.Value) -> ir.Value:
        """Convert an Array to a List (Array.unpacked() -> List).

        Creates a new List with the same elements as the Array.
        For Persistent Vector List, we iterate through the array and
        append each element to build the list.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.cg.builder.function

        # Get Array length
        array_len = self.cg.builder.call(self.cg.array_len, [array_ptr])

        # Get Array elem_size (field 4 in Array layout)
        elem_size_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        elem_size = self.cg.builder.load(elem_size_ptr)

        # Get Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.cg.builder.load(array_owner_handle_ptr)
        array_owner = self.cg.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.cg.builder.load(array_offset_ptr)
        array_data = self.cg.builder.gep(array_owner, [array_offset])

        # Create new empty List with same elem_size
        list_ptr = self.cg.builder.call(self.cg.list_new, [elem_size])

        # Store list_ptr in alloca since list_append returns new list
        list_alloca = self.cg.builder.alloca(self.cg.list_struct.as_pointer(), name="arr_to_list")
        self.cg.builder.store(list_ptr, list_alloca)

        # Loop through array elements and append to list
        idx_alloca = self.cg.builder.alloca(i64, name="arr_to_list_idx")
        self.cg.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("arr_to_list_cond")
        body_block = func.append_basic_block("arr_to_list_body")
        end_block = func.append_basic_block("arr_to_list_end")

        self.cg.builder.branch(cond_block)

        # Condition: idx < array_len
        self.cg.builder.position_at_end(cond_block)
        idx = self.cg.builder.load(idx_alloca)
        cond = self.cg.builder.icmp_signed("<", idx, array_len)
        self.cg.builder.cbranch(cond, body_block, end_block)

        # Body: get element from array and append to list
        self.cg.builder.position_at_end(body_block)
        idx = self.cg.builder.load(idx_alloca)

        # Calculate source address in array
        offset = self.cg.builder.mul(idx, elem_size)
        elem_ptr = self.cg.builder.gep(array_data, [offset])

        # Append element to list
        current_list = self.cg.builder.load(list_alloca)
        new_list = self.cg.builder.call(self.cg.list_append, [current_list, elem_ptr, elem_size])
        self.cg.builder.store(new_list, list_alloca)

        # Increment index
        next_idx = self.cg.builder.add(idx, ir.Constant(i64, 1))
        self.cg.builder.store(next_idx, idx_alloca)
        self.cg.builder.branch(cond_block)

        # End
        self.cg.builder.position_at_end(end_block)
        return self.cg.builder.load(list_alloca)

    def array_to_set(self, array_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Convert an Array to a Set (Array.toSet() -> Set).

        Creates a new Set with the same elements as the Array.
        Duplicate elements in the Array are deduplicated.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.cg.builder.function

        # Get Array length
        array_len = self.cg.builder.call(self.cg.array_len, [array_ptr])

        # Get Array elem_size (field 4 in Array layout)
        elem_size_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        elem_size = self.cg.builder.load(elem_size_ptr)

        # Get Array data: compute owner + offset (Phase 4: owner is i64 handle)
        array_owner_handle_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        array_owner_handle = self.cg.builder.load(array_owner_handle_ptr)
        array_owner = self.cg.builder.inttoptr(array_owner_handle, i8_ptr)
        array_offset_ptr = self.cg.builder.gep(array_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        array_offset = self.cg.builder.load(array_offset_ptr)
        array_data = self.cg.builder.gep(array_owner, [array_offset])

        # Create new empty Set with flags indicating element type
        flags = self.cg.MAP_FLAG_KEY_IS_PTR if elem_is_ptr else 0
        set_ptr = self.cg.builder.call(self.cg.set_new, [ir.Constant(i64, flags)])

        # Store set_ptr in alloca since set_add returns new set
        set_alloca = self.cg.builder.alloca(self.cg.set_struct.as_pointer(), name="arr_to_set")
        self.cg.builder.store(set_ptr, set_alloca)

        # Loop through array elements and add to set
        idx_alloca = self.cg.builder.alloca(i64, name="arr_to_set_idx")
        self.cg.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("arr_to_set_cond")
        body_block = func.append_basic_block("arr_to_set_body")
        end_block = func.append_basic_block("arr_to_set_end")

        self.cg.builder.branch(cond_block)

        # Condition: idx < array_len
        self.cg.builder.position_at_end(cond_block)
        idx = self.cg.builder.load(idx_alloca)
        cond = self.cg.builder.icmp_signed("<", idx, array_len)
        self.cg.builder.cbranch(cond, body_block, end_block)

        # Body: get element from array and add to set
        self.cg.builder.position_at_end(body_block)
        idx = self.cg.builder.load(idx_alloca)

        # Calculate source address in array and load value
        offset = self.cg.builder.mul(idx, elem_size)
        elem_ptr = self.cg.builder.gep(array_data, [offset])
        # Load element as i64 (assuming elements are stored as i64)
        typed_ptr = self.cg.builder.bitcast(elem_ptr, i64.as_pointer())
        elem_val = self.cg.builder.load(typed_ptr)

        # Add element to set (set_add returns new set)
        current_set = self.cg.builder.load(set_alloca)
        new_set = self.cg.builder.call(self.cg.set_add, [current_set, elem_val])
        self.cg.builder.store(new_set, set_alloca)

        # Increment index
        next_idx = self.cg.builder.add(idx, ir.Constant(i64, 1))
        self.cg.builder.store(next_idx, idx_alloca)
        self.cg.builder.branch(cond_block)

        # End
        self.cg.builder.position_at_end(end_block)
        return self.cg.builder.load(set_alloca)

    def list_to_set(self, list_ptr: ir.Value, elem_is_ptr: bool = False) -> ir.Value:
        """Convert a List to a Set (List.to_set() -> Set).

        Creates a new Set with the same elements as the List.
        Duplicate elements in the List are deduplicated.
        """
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        func = self.cg.builder.function

        # Get List length
        list_len = self.cg.builder.call(self.cg.list_len, [list_ptr])

        # Create new empty Set with flags indicating element type
        flags = self.cg.MAP_FLAG_KEY_IS_PTR if elem_is_ptr else 0
        set_ptr = self.cg.builder.call(self.cg.set_new, [ir.Constant(i64, flags)])

        # Store set_ptr in alloca since set_add returns new set
        set_alloca = self.cg.builder.alloca(self.cg.set_struct.as_pointer(), name="list_to_set")
        self.cg.builder.store(set_ptr, set_alloca)

        # Loop through list elements and add to set
        idx_alloca = self.cg.builder.alloca(i64, name="list_to_set_idx")
        self.cg.builder.store(ir.Constant(i64, 0), idx_alloca)

        cond_block = func.append_basic_block("list_to_set_cond")
        body_block = func.append_basic_block("list_to_set_body")
        end_block = func.append_basic_block("list_to_set_end")

        self.cg.builder.branch(cond_block)

        # Condition: idx < list_len
        self.cg.builder.position_at_end(cond_block)
        idx = self.cg.builder.load(idx_alloca)
        cond = self.cg.builder.icmp_signed("<", idx, list_len)
        self.cg.builder.cbranch(cond, body_block, end_block)

        # Body: get element from list and add to set
        self.cg.builder.position_at_end(body_block)
        idx = self.cg.builder.load(idx_alloca)

        # Get element from list using list_get
        elem_ptr = self.cg.builder.call(self.cg.list_get, [list_ptr, idx])
        # Load element as i64 (assuming elements are stored as i64)
        typed_ptr = self.cg.builder.bitcast(elem_ptr, i64.as_pointer())
        elem_val = self.cg.builder.load(typed_ptr)

        # Add element to set (set_add returns new set)
        current_set = self.cg.builder.load(set_alloca)
        new_set = self.cg.builder.call(self.cg.set_add, [current_set, elem_val])
        self.cg.builder.store(new_set, set_alloca)

        # Increment index
        next_idx = self.cg.builder.add(idx, ir.Constant(i64, 1))
        self.cg.builder.store(next_idx, idx_alloca)
        self.cg.builder.branch(cond_block)

        # End
        self.cg.builder.position_at_end(end_block)
        return self.cg.builder.load(set_alloca)

    def try_implicit_collection_conversion(self, value: ir.Value, target_type: Type, value_type: Type = None) -> Tuple[ir.Value, bool]:
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
            return self.list_to_array(value), True
        elif source_struct == "struct.Array" and target_struct == "struct.List":
            return self.array_to_list(value), True
        elif source_struct == "struct.List" and target_struct == "struct.Set":
            return self.list_to_set(value), True
        elif source_struct == "struct.Set" and target_struct == "struct.List":
            # set_to_list is available via coex_set_to_list
            return self.cg.builder.call(self.cg.set_to_list, [value]), True
        elif source_struct == "struct.Set" and target_struct == "struct.Array":
            return self.set_to_array(value), True
        elif source_struct == "struct.Array" and target_struct == "struct.Set":
            return self.array_to_set(value), True

        return value, False

    def get_conversion_warning_message(self, source_struct: str, target_struct: str) -> str:
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

    def is_primitive_coex_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is a primitive (int, float, bool, byte, char)."""
        if isinstance(coex_type, PrimitiveType):
            return coex_type.name in ("int", "float", "bool", "byte", "char")
        return False

    def needs_parameter_copy(self, coex_type: Type) -> bool:
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

    def is_heap_type(self, coex_type: Type) -> bool:
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
            if coex_type.name in self.cg.type_fields:
                return True
            # Generic types that expand to collections
            if coex_type.type_args:
                return True
        if isinstance(coex_type, TupleType):
            # Tuples are stack values, but we don't track them as roots
            # (their contents are copied at assignment)
            return False
        return False

    def compute_map_flags(self, key_type: Type, value_type: Type) -> int:
        """Compute the GC flags for a Map based on key and value types.

        Returns an integer with:
        - bit 0 set if key is a heap pointer
        - bit 1 set if value is a heap pointer
        """
        flags = 0
        if self.is_heap_type(key_type):
            flags |= self.cg.MAP_FLAG_KEY_IS_PTR
        if self.is_heap_type(value_type):
            flags |= self.cg.MAP_FLAG_VALUE_IS_PTR
        return flags

    def compute_set_flags(self, elem_type: Type) -> int:
        """Compute the GC flags for a Set based on element type.

        Returns an integer with:
        - bit 0 set if element is a heap pointer
        """
        flags = 0
        if self.is_heap_type(elem_type):
            flags |= self.cg.MAP_FLAG_KEY_IS_PTR  # Reuse same flag for set elements
        return flags

    def is_collection_coex_type(self, coex_type: Type) -> bool:
        """Check if a Coex type is a collection (List, Set, Map, Array, String)."""
        if isinstance(coex_type, (ListType, SetType, MapType, ArrayType)):
            return True
        if isinstance(coex_type, NamedType) and coex_type.name == "string":
            return True
        return False

    def get_receiver_type(self, expr: Expr) -> Optional[Type]:
        """Get the Coex type of a receiver expression (handles chained method calls).

        For expressions like a.set(0, x).set(1, y):
        - The outermost call has callee.object = a.set(0, x) (another CallExpr)
        - We recursively find the innermost Identifier to get its type
        """
        if isinstance(expr, Identifier):
            # Direct variable reference
            if expr.name in self.cg.var_coex_types:
                return self.cg.var_coex_types[expr.name]
            return None
        elif isinstance(expr, CallExpr):
            # Chained method call: recurse into the callee's object
            if isinstance(expr.callee, MemberExpr):
                return self.get_receiver_type(expr.callee.object)
        elif isinstance(expr, MemberExpr):
            # Member expression without call
            return self.get_receiver_type(expr.object)
        return None

    def needs_deep_copy(self, coex_type: Type) -> bool:
        """Check if a type needs deep copy (has nested collections)."""
        if isinstance(coex_type, ListType):
            return self.is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, ArrayType):
            return self.is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, SetType):
            return self.is_collection_coex_type(coex_type.element_type)
        if isinstance(coex_type, MapType):
            return self.is_collection_coex_type(coex_type.value_type)
        if isinstance(coex_type, NamedType) and coex_type.name in self.cg.type_fields:
            # Check if user type has any collection fields
            for field_name, field_type in self.cg.type_fields[coex_type.name]:
                if self.is_collection_coex_type(field_type):
                    return True
        return False

    def generate_move_or_eager_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
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

    def generate_deep_copy(self, value: ir.Value, coex_type: Type) -> ir.Value:
        """Generate code to deep-copy a value based on its Coex type.

        This creates a truly independent copy for Array and String types,
        which is needed for the := (copy) operator to support unique ownership.
        For other types, returns the value unchanged (immutable heap semantics).
        """
        if isinstance(coex_type, ArrayType):
            return self.generate_array_deep_copy(value, coex_type.element_type)
        elif isinstance(coex_type, PrimitiveType) and coex_type.name == "string":
            return self.generate_string_deep_copy(value)
        # Other types: return unchanged (immutable semantics)
        return value

    def generate_list_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy a list (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def generate_set_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy a set (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def generate_map_deep_copy(self, src: ir.Value, key_type: Type, value_type: Type) -> ir.Value:
        """Deep copy a map (identity function with immutable heap semantics).

        With immutable heap semantics, deep copy is unnecessary.
        Sharing the reference is semantically equivalent.
        """
        return src

    def generate_array_deep_copy(self, src: ir.Value, elem_type: Type) -> ir.Value:
        """Deep copy an array to create an independent copy with its own data buffer.

        This is used by the := (copy) operator to ensure the copy is truly independent,
        which is important for unique ownership semantics where the source should
        remain valid and unique after a copy.
        """
        return self.cg.builder.call(self.cg.array_deep_copy, [src])

    def generate_string_deep_copy(self, src: ir.Value) -> ir.Value:
        """Deep copy a string to create an independent copy with its own data buffer.

        This is used by the := (copy) operator to ensure the copy is truly independent,
        which is important for unique ownership semantics where the source should
        remain valid and unique after a copy.
        """
        return self.cg.builder.call(self.cg.string_deep_copy, [src])

    def generate_type_deep_copy(self, src: ir.Value, coex_type: NamedType) -> ir.Value:
        """Deep copy a user-defined type (identity function with immutable heap semantics).

        With copy-on-write field assignment, UDTs are now immutable like collections.
        Sharing the reference is semantically equivalent to copying.
        """
        return src
