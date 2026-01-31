"""
Coex JSON Type Code Generator

Generates LLVM IR for the JSON type, providing a tagged union for representing
JSON values (null, bool, int, float, string, array, object).

JSON values are stored as:
- struct.Json { i64 tag, i64 value }
- Tags: 0=null, 1=bool, 2=int, 3=float, 4=string, 5=array, 6=object
- Values: primitives inline, pointers stored as i64

IMPORTANT: All integer fields use i64 to ensure consistent alignment across platforms.
Using smaller integer types (i8, i16, i32) for struct fields causes alignment differences
between Linux and macOS that lead to incorrect field offsets at runtime.
"""

import os
from llvmlite import ir


class JsonGenerator:
    """Generates LLVM IR for JSON type operations."""

    # JSON type tags
    JSON_TAG_NULL = 0
    JSON_TAG_BOOL = 1
    JSON_TAG_INT = 2
    JSON_TAG_FLOAT = 3
    JSON_TAG_STRING = 4
    JSON_TAG_ARRAY = 5
    JSON_TAG_OBJECT = 6

    # cJSON type constants (from cJSON.h)
    CJSON_INVALID = 0
    CJSON_FALSE = 1 << 0    # 1
    CJSON_TRUE = 1 << 1     # 2
    CJSON_NULL = 1 << 2     # 4
    CJSON_NUMBER = 1 << 3   # 8
    CJSON_STRING = 1 << 4   # 16
    CJSON_ARRAY = 1 << 5    # 32
    CJSON_OBJECT = 1 << 6   # 64

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to main code generator."""
        self.cg = codegen
        self.cjson_struct = None
        self.cJSON_Parse = None
        self.cJSON_Delete = None
        self.json_from_cjson = None
        self._cjson_available = None  # Cached availability check

    def _is_cjson_available(self) -> bool:
        """Check if cJSON library is available for linking."""
        if self._cjson_available is not None:
            return self._cjson_available

        # Check for cJSON library in deps directory
        script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        deps_dir = os.path.join(script_dir, "deps", "lib")
        cjson_lib = os.path.join(deps_dir, "libcjson.a")
        self._cjson_available = os.path.exists(cjson_lib)
        return self._cjson_available

    def _declare_cjson_types(self):
        """Declare cJSON struct type and external functions for JSON parsing."""
        cg = self.cg
        i8 = ir.IntType(8)
        i8_ptr = i8.as_pointer()
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # cJSON struct type (from cJSON.h):
        # struct cJSON { next, prev, child, type, valuestring, valueint, valuedouble, string }
        # Note: llvmlite requires us to define the type before we can use pointers to it
        self.cjson_struct = ir.global_context.get_identified_type("struct.cJSON")
        cjson_ptr = self.cjson_struct.as_pointer()

        # Set the body after getting the type so we can use self-referential pointers
        self.cjson_struct.set_body(
            cjson_ptr,      # next
            cjson_ptr,      # prev
            cjson_ptr,      # child
            i32,            # type (bitmask)
            i8_ptr,         # valuestring
            i32,            # valueint
            ir.DoubleType(), # valuedouble
            i8_ptr,         # string (key name)
        )

        # Declare cJSON_Parse(const char*) -> cJSON*
        cJSON_Parse_ty = ir.FunctionType(cjson_ptr, [i8_ptr])
        self.cJSON_Parse = ir.Function(cg.module, cJSON_Parse_ty, name="cJSON_Parse")

        # Declare cJSON_Delete(cJSON*) -> void
        cJSON_Delete_ty = ir.FunctionType(ir.VoidType(), [cjson_ptr])
        self.cJSON_Delete = ir.Function(cg.module, cJSON_Delete_ty, name="cJSON_Delete")

    def _implement_json_from_cjson(self):
        """Implement coex_json_from_cjson(cJSON*) -> Json*

        Recursively converts a cJSON tree to Coex Json objects.
        """
        cg = self.cg
        i8 = ir.IntType(8)
        i8_ptr = i8.as_pointer()
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)
        cjson_ptr = self.cjson_struct.as_pointer()
        json_ptr = cg.json_struct.as_pointer()

        # Create the function
        func_ty = ir.FunctionType(json_ptr, [cjson_ptr])
        self.json_from_cjson = ir.Function(cg.module, func_ty, name="coex_json_from_cjson")
        func = self.json_from_cjson
        func.args[0].name = "cjson"

        # Create basic blocks
        entry = func.append_basic_block("entry")
        check_null_type = func.append_basic_block("check_null_type")
        check_true = func.append_basic_block("check_true")
        check_false = func.append_basic_block("check_false")
        check_number = func.append_basic_block("check_number")
        check_string = func.append_basic_block("check_string")
        check_array = func.append_basic_block("check_array")
        check_object = func.append_basic_block("check_object")
        return_null = func.append_basic_block("return_null")
        return_true = func.append_basic_block("return_true")
        return_false = func.append_basic_block("return_false")
        return_number = func.append_basic_block("return_number")
        return_string = func.append_basic_block("return_string")
        process_array = func.append_basic_block("process_array")
        array_loop = func.append_basic_block("array_loop")
        array_body = func.append_basic_block("array_body")
        array_done = func.append_basic_block("array_done")
        process_object = func.append_basic_block("process_object")
        object_loop = func.append_basic_block("object_loop")
        object_body = func.append_basic_block("object_body")
        object_done = func.append_basic_block("object_done")
        fallback = func.append_basic_block("fallback")

        builder = ir.IRBuilder(entry)
        cjson = func.args[0]

        # Check for null input
        null_cjson = ir.Constant(cjson_ptr, None)
        is_null_input = builder.icmp_unsigned("==", cjson, null_cjson)
        builder.cbranch(is_null_input, fallback, check_null_type)

        # Get the type field (field 3 in cJSON struct)
        builder.position_at_end(check_null_type)
        type_ptr = builder.gep(cjson, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        cjson_type = builder.load(type_ptr)

        # Check for cJSON_NULL (type & 4)
        is_null = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_NULL))
        is_null_bool = builder.icmp_unsigned("!=", is_null, ir.Constant(i32, 0))
        builder.cbranch(is_null_bool, return_null, check_true)

        # Return null JSON
        builder.position_at_end(return_null)
        null_result = builder.call(cg.json_new_null, [])
        builder.ret(null_result)

        # Check for cJSON_True (type & 2)
        builder.position_at_end(check_true)
        is_true = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_TRUE))
        is_true_bool = builder.icmp_unsigned("!=", is_true, ir.Constant(i32, 0))
        builder.cbranch(is_true_bool, return_true, check_false)

        # Return true JSON
        builder.position_at_end(return_true)
        true_result = builder.call(cg.json_new_bool, [ir.Constant(i1, 1)])
        builder.ret(true_result)

        # Check for cJSON_False (type & 1)
        builder.position_at_end(check_false)
        is_false = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_FALSE))
        is_false_bool = builder.icmp_unsigned("!=", is_false, ir.Constant(i32, 0))
        builder.cbranch(is_false_bool, return_false, check_number)

        # Return false JSON
        builder.position_at_end(return_false)
        false_result = builder.call(cg.json_new_bool, [ir.Constant(i1, 0)])
        builder.ret(false_result)

        # Check for cJSON_Number (type & 8)
        builder.position_at_end(check_number)
        is_number = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_NUMBER))
        is_number_bool = builder.icmp_unsigned("!=", is_number, ir.Constant(i32, 0))
        builder.cbranch(is_number_bool, return_number, check_string)

        # BUG-072 FIX: Check if number is an integer and create appropriate JSON type
        # cJSON stores all numbers as double, but we want to preserve integer types
        builder.position_at_end(return_number)
        valuedouble_ptr = builder.gep(cjson, [ir.Constant(i32, 0), ir.Constant(i32, 6)], inbounds=True)
        valuedouble = builder.load(valuedouble_ptr)

        # Convert to i64 and back to double to check if it's an integer
        as_int = builder.fptosi(valuedouble, i64)
        back_to_double = builder.sitofp(as_int, ir.DoubleType())

        # Check if conversion is lossless (original == reconverted)
        is_integer = builder.fcmp_ordered("==", valuedouble, back_to_double)

        # Also check the value is within safe integer range for i64
        # (avoid overflow on very large floats)
        int_max = ir.Constant(ir.DoubleType(), float(2**63 - 1))
        int_min = ir.Constant(ir.DoubleType(), float(-2**63))
        in_upper = builder.fcmp_ordered("<=", valuedouble, int_max)
        in_lower = builder.fcmp_ordered(">=", valuedouble, int_min)
        in_range = builder.and_(in_upper, in_lower)
        is_safe_int = builder.and_(is_integer, in_range)

        # Create appropriate JSON type
        return_int = func.append_basic_block("return_int")
        return_float = func.append_basic_block("return_float")
        builder.cbranch(is_safe_int, return_int, return_float)

        # Return as JSON int
        builder.position_at_end(return_int)
        int_result = builder.call(cg.json_new_int, [as_int])
        builder.ret(int_result)

        # Return as JSON float
        builder.position_at_end(return_float)
        float_result = builder.call(cg.json_new_float, [valuedouble])
        builder.ret(float_result)

        # Check for cJSON_String (type & 16)
        builder.position_at_end(check_string)
        is_string = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_STRING))
        is_string_bool = builder.icmp_unsigned("!=", is_string, ir.Constant(i32, 0))
        builder.cbranch(is_string_bool, return_string, check_array)

        # Return string JSON
        builder.position_at_end(return_string)
        valuestring_ptr = builder.gep(cjson, [ir.Constant(i32, 0), ir.Constant(i32, 4)], inbounds=True)
        valuestring = builder.load(valuestring_ptr)
        coex_string = builder.call(cg.string_from_literal, [valuestring])
        string_result = builder.call(cg.json_new_string, [coex_string])
        builder.ret(string_result)

        # Check for cJSON_Array (type & 32)
        builder.position_at_end(check_array)
        is_array = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_ARRAY))
        is_array_bool = builder.icmp_unsigned("!=", is_array, ir.Constant(i32, 0))
        builder.cbranch(is_array_bool, process_array, check_object)

        # Process array: create list, iterate through child elements
        builder.position_at_end(process_array)
        # Create list for JSON elements with TaggedValue size (16 bytes)
        list_val = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])
        list_ptr_alloca = builder.alloca(cg.list_struct.as_pointer(), name="list_ptr")
        builder.store(list_val, list_ptr_alloca)

        # Allocate temp storage for element handles outside loop
        temp_handle_ptr = builder.alloca(i64, name="temp_json_handle")

        # Get first child
        child_ptr = builder.gep(cjson, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        first_child = builder.load(child_ptr)
        child_alloca = builder.alloca(cjson_ptr, name="child")
        builder.store(first_child, child_alloca)
        builder.branch(array_loop)

        # Array loop condition
        builder.position_at_end(array_loop)
        current_child = builder.load(child_alloca)
        is_child_null = builder.icmp_unsigned("==", current_child, null_cjson)
        builder.cbranch(is_child_null, array_done, array_body)

        # Array loop body: convert child and append to list
        builder.position_at_end(array_body)
        child_json = builder.call(self.json_from_cjson, [current_child])

        # Create TaggedValue with JSON handle
        child_json_i8 = builder.bitcast(child_json, i8_ptr)
        child_handle = builder.call(cg.gc.gc_ptr_to_handle, [child_json_i8])
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, child_handle)
        tv_i8 = builder.bitcast(tv_ptr, i8_ptr)

        # Append TaggedValue to list
        curr_list = builder.load(list_ptr_alloca)
        new_list = builder.call(cg.list_append, [curr_list, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])
        builder.store(new_list, list_ptr_alloca)

        # Move to next sibling
        next_ptr = builder.gep(current_child, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        next_child = builder.load(next_ptr)
        builder.store(next_child, child_alloca)
        builder.branch(array_loop)

        # Array done: wrap list in json array
        builder.position_at_end(array_done)
        final_list = builder.load(list_ptr_alloca)
        array_result = builder.call(cg.json_new_array, [final_list])
        builder.ret(array_result)

        # Check for cJSON_Object (type & 64)
        builder.position_at_end(check_object)
        is_object = builder.and_(cjson_type, ir.Constant(i32, self.CJSON_OBJECT))
        is_object_bool = builder.icmp_unsigned("!=", is_object, ir.Constant(i32, 0))
        builder.cbranch(is_object_bool, process_object, fallback)

        # Process object: create map, iterate through child elements
        builder.position_at_end(process_object)
        # Create map with string keys and pointer values
        map_flags = ir.Constant(i64, cg.MAP_FLAG_KEY_IS_PTR | cg.MAP_FLAG_VALUE_IS_PTR)
        map_val = builder.call(cg.map_new, [map_flags])
        map_ptr_alloca = builder.alloca(cg.map_struct.as_pointer(), name="map_ptr")
        builder.store(map_val, map_ptr_alloca)

        # Get first child
        obj_child_ptr = builder.gep(cjson, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
        obj_first_child = builder.load(obj_child_ptr)
        obj_child_alloca = builder.alloca(cjson_ptr, name="obj_child")
        builder.store(obj_first_child, obj_child_alloca)
        builder.branch(object_loop)

        # Object loop condition
        builder.position_at_end(object_loop)
        obj_current_child = builder.load(obj_child_alloca)
        is_obj_child_null = builder.icmp_unsigned("==", obj_current_child, null_cjson)
        builder.cbranch(is_obj_child_null, object_done, object_body)

        # Object loop body: get key, convert value, add to map
        builder.position_at_end(object_body)

        # Get key string (field 7 in cJSON struct)
        key_cstr_ptr = builder.gep(obj_current_child, [ir.Constant(i32, 0), ir.Constant(i32, 7)], inbounds=True)
        key_cstr = builder.load(key_cstr_ptr)
        key_string = builder.call(cg.string_from_literal, [key_cstr])

        # Convert value
        value_json = builder.call(self.json_from_cjson, [obj_current_child])

        # Convert json pointer to i64 for map storage
        value_i64 = builder.ptrtoint(value_json, i64)

        # Add to map
        curr_map = builder.load(map_ptr_alloca)
        new_map = builder.call(cg.map_set_string, [curr_map, key_string, value_i64])
        builder.store(new_map, map_ptr_alloca)

        # Move to next sibling
        obj_next_ptr = builder.gep(obj_current_child, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        obj_next_child = builder.load(obj_next_ptr)
        builder.store(obj_next_child, obj_child_alloca)
        builder.branch(object_loop)

        # Object done: wrap map in json object
        builder.position_at_end(object_done)
        final_map = builder.load(map_ptr_alloca)
        object_result = builder.call(cg.json_new_object, [final_map])
        builder.ret(object_result)

        # Fallback: return null
        builder.position_at_end(fallback)
        fallback_result = builder.call(cg.json_new_null, [])
        builder.ret(fallback_result)

    def create_json_type(self):
        """Create the JSON type and helper functions.

        JSON values are tagged unions that can hold:
        - null (tag=0)
        - bool (tag=1)
        - int (tag=2)
        - float (tag=3)
        - string (tag=4, value is String* pointer)
        - array (tag=5, value is List* pointer holding [json])
        - object (tag=6, value is Map* pointer with string keys and json values)

        struct.Json { i64 tag, i64 value }

        IMPORTANT: All fields are i64 to ensure consistent alignment across platforms.
        """
        cg = self.cg
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)

        # Define the JSON struct: { i64 value }
        # With first-class JSON variants, the type is determined by the GC header's type_id,
        # not by a tag field. All JSON variants have 8 bytes of user data (i64 value).
        cg.json_struct = ir.global_context.get_identified_type("struct.Json")
        cg.json_struct.set_body(
            i64,  # value (field 0) - inline value or handle for reference types
        )

        # Declare constructor functions
        json_ptr = cg.json_struct.as_pointer()

        # json_new_null() -> Json*
        # Mark as noinline optnone to prevent optimizer from eliminating stores
        # Note: llvmlite's optimizer incorrectly eliminates stores without optnone
        cg.json_new_null = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, []),
            name="coex_json_new_null"
        )
        cg.json_new_null.attributes.add('noinline')
        cg.json_new_null.attributes.add('optnone')

        # json_new_bool(i1 value) -> Json*
        cg.json_new_bool = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [ir.IntType(1)]),
            name="coex_json_new_bool"
        )
        cg.json_new_bool.attributes.add('noinline')
        cg.json_new_bool.attributes.add('optnone')

        # json_new_int(i64 value) -> Json*
        cg.json_new_int = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [i64]),
            name="coex_json_new_int"
        )
        cg.json_new_int.attributes.add('noinline')
        cg.json_new_int.attributes.add('optnone')

        # json_new_float(f64 value) -> Json*
        cg.json_new_float = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [ir.DoubleType()]),
            name="coex_json_new_float"
        )
        cg.json_new_float.attributes.add('noinline')
        cg.json_new_float.attributes.add('optnone')

        # json_new_string(String* value) -> Json*
        cg.json_new_string = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.string_struct.as_pointer()]),
            name="coex_json_new_string"
        )
        cg.json_new_string.attributes.add('noinline')
        cg.json_new_string.attributes.add('optnone')

        # json_new_array(List* value) -> Json*
        cg.json_new_array = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.list_struct.as_pointer()]),
            name="coex_json_new_array"
        )
        cg.json_new_array.attributes.add('noinline')
        cg.json_new_array.attributes.add('optnone')

        # json_new_object(Map* value) -> Json*
        cg.json_new_object = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.map_struct.as_pointer()]),
            name="coex_json_new_object"
        )
        cg.json_new_object.attributes.add('noinline')
        cg.json_new_object.attributes.add('optnone')

        # json_get_tag(Json*) -> i64
        # IMPORTANT: Returns i64 for consistent alignment across platforms
        cg.json_get_tag = ir.Function(
            cg.module,
            ir.FunctionType(i64, [json_ptr]),
            name="coex_json_get_tag"
        )

        # json_get_field(Json*, String*) -> Json* (returns null json if not found)
        cg.json_get_field = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, cg.string_struct.as_pointer()]),
            name="coex_json_get_field"
        )

        # json_get_index(Json*, i64) -> Json* (returns null json if out of bounds)
        cg.json_get_index = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, i64]),
            name="coex_json_get_index"
        )

        # Type checking methods: is_null, is_bool, is_int, is_float, is_string, is_array, is_object
        i1 = ir.IntType(1)
        cg.json_is_null = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_null")
        cg.json_is_bool = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_bool")
        cg.json_is_int = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_int")
        cg.json_is_float = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_float")
        cg.json_is_string = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_string")
        cg.json_is_array = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_array")
        cg.json_is_object = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_object")

        # Value accessor methods: as_int, as_float, as_bool, as_string
        cg.json_as_int = ir.Function(cg.module, ir.FunctionType(i64, [json_ptr]), name="coex_json_as_int")
        cg.json_as_float = ir.Function(cg.module, ir.FunctionType(ir.DoubleType(), [json_ptr]), name="coex_json_as_float")
        cg.json_as_bool = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_as_bool")
        cg.json_as_string = ir.Function(cg.module, ir.FunctionType(cg.string_struct.as_pointer(), [json_ptr]), name="coex_json_as_string")

        # json_to_string(Json*) -> String* (smart conversion: raw value for primitives, stringify for complex)
        cg.json_to_string = ir.Function(cg.module, ir.FunctionType(cg.string_struct.as_pointer(), [json_ptr]), name="coex_json_to_string")

        # json_len(Json*) -> i64 (length for arrays/objects, 0 otherwise)
        cg.json_len = ir.Function(cg.module, ir.FunctionType(i64, [json_ptr]), name="coex_json_len")

        # json_has(Json*, String*) -> bool (check if object has key)
        cg.json_has = ir.Function(cg.module, ir.FunctionType(i1, [json_ptr, cg.string_struct.as_pointer()]), name="coex_json_has")

        # json_set_field(Json*, String*, Json*) -> Json* (return new json with field set)
        cg.json_set_field = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, cg.string_struct.as_pointer(), json_ptr]),
            name="coex_json_set_field"
        )

        # json_set_index(Json*, i64, Json*) -> Json* (return new json with index set)
        cg.json_set_index = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, i64, json_ptr]),
            name="coex_json_set_index"
        )

        # json_append(Json*, Json*) -> Json* (append to array)
        cg.json_append = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, json_ptr]),
            name="coex_json_append"
        )

        # json_remove(Json*, String*) -> Json* (remove key from object)
        cg.json_remove = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [json_ptr, cg.string_struct.as_pointer()]),
            name="coex_json_remove"
        )

        # json_keys(Json*) -> List* (get keys as list of strings)
        cg.json_keys = ir.Function(
            cg.module,
            ir.FunctionType(cg.list_struct.as_pointer(), [json_ptr]),
            name="coex_json_keys"
        )

        # json_values(Json*) -> List* (get values as list of json)
        cg.json_values = ir.Function(
            cg.module,
            ir.FunctionType(cg.list_struct.as_pointer(), [json_ptr]),
            name="coex_json_values"
        )

        # json_stringify(Json*) -> String* (serialize JSON to string)
        cg.json_stringify = ir.Function(
            cg.module,
            ir.FunctionType(cg.string_struct.as_pointer(), [json_ptr]),
            name="coex_json_stringify"
        )

        # json_parse(String*) -> Json* (parse string to JSON, returns null on error)
        cg.json_parse = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.string_struct.as_pointer()]),
            name="coex_json_parse"
        )

        # json_pretty(Json*, i64 indent) -> String* (serialize JSON with pretty printing)
        cg.json_pretty = ir.Function(
            cg.module,
            ir.FunctionType(cg.string_struct.as_pointer(), [json_ptr, ir.IntType(64)]),
            name="coex_json_pretty"
        )

        # Implement the constructor functions
        self._implement_json_new_null()
        self._implement_json_new_bool()
        self._implement_json_new_int()
        self._implement_json_new_float()
        self._implement_json_new_string()
        self._implement_json_new_array()
        self._implement_json_new_object()
        self._implement_json_get_tag()
        self._implement_json_get_field()
        self._implement_json_get_index()

        # Implement type checking methods
        self._implement_json_is_null()
        self._implement_json_is_bool()
        self._implement_json_is_int()
        self._implement_json_is_float()
        self._implement_json_is_string()
        self._implement_json_is_array()
        self._implement_json_is_object()

        # Implement value accessor methods
        self._implement_json_as_int()
        self._implement_json_as_float()
        self._implement_json_as_bool()
        self._implement_json_as_string()
        self._implement_json_to_string()

        # Implement access and mutation methods
        self._implement_json_len()
        self._implement_json_has()
        self._implement_json_set_field()
        self._implement_json_set_index()
        self._implement_json_append()
        self._implement_json_remove()
        self._implement_json_keys()
        self._implement_json_values()

        # Implement serialization functions
        self._implement_json_stringify()
        self._implement_json_pretty()

        # Declare cJSON types and implement converter (needed for json.parse)
        # Only if cJSON library is available
        if self._is_cjson_available():
            self._declare_cjson_types()
            self._implement_json_from_cjson()
            self._implement_json_parse()
        else:
            # Implement stub json.parse that returns null when cJSON not available
            self._implement_json_parse_stub()

        # Implement string.validjson() now that json_parse exists
        cg._strings.implement_string_validjson()

        # Register JSON type and methods
        self._register_json_methods()

    def _implement_json_new_null(self):
        """Implement json_new_null(): allocate a JsonNull variant.

        First-class JSON variant: TYPE_JSON_NULL with 8 bytes payload (unused, for alignment).
        The type ID in the GC header identifies this as a null value.
        """
        cg = self.cg
        func = cg.json_new_null
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate JsonNull (8 bytes payload, type_id identifies the variant)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_NULL)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store 0 in value field (unused for null, but initialize for consistency)
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        builder.store(ir.Constant(i64, 0), value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_bool(self):
        """Implement json_new_bool(i1): allocate a JsonBool variant.

        First-class JSON variant: TYPE_JSON_BOOL with 8 bytes payload (i64 value 0/1).
        """
        cg = self.cg
        func = cg.json_new_bool
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate JsonBool (8 bytes payload)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_BOOL)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store bool value as i64 at offset 0
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        value_i64 = builder.zext(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_int(self):
        """Implement json_new_int(i64): allocate a JsonInt variant.

        First-class JSON variant: TYPE_JSON_INT with 8 bytes payload (i64 value).
        """
        cg = self.cg
        func = cg.json_new_int
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate JsonInt (8 bytes payload)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_INT)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store int value at offset 0
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        builder.store(func.args[0], value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_float(self):
        """Implement json_new_float(f64): allocate a JsonFloat variant.

        First-class JSON variant: TYPE_JSON_FLOAT with 8 bytes payload (f64 bitcast to i64).
        """
        cg = self.cg
        func = cg.json_new_float
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate JsonFloat (8 bytes payload)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_FLOAT)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store float value (bitcast f64 to i64) at offset 0
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        value_i64 = builder.bitcast(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_string(self):
        """Implement json_new_string(String*): allocate a JsonString variant.

        First-class JSON variant: TYPE_JSON_STRING with 8 bytes payload (i64 HANDLE to String).

        INVARIANT: JSON always deep-copies values. The string is copied so the JSON
        owns its own independent copy. This ensures JSON captures a snapshot of values
        at composition time, not references that could become stale.

        HANDLE STORAGE INVARIANT: We store an i64 handle (gc_ptr_to_handle), not a
        raw pointer. The GC marks this handle during collection.
        """
        cg = self.cg
        func = cg.json_new_string
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # DEEP COPY: Create an independent copy of the string
        # JSON must own its data, not share references with the source
        copied_string = builder.call(cg.string_deep_copy, [func.args[0]])

        # Convert string pointer to handle (HANDLE STORAGE INVARIANT)
        copied_string_i8 = builder.bitcast(copied_string, ir.IntType(8).as_pointer())
        string_handle = builder.call(cg.gc.gc_ptr_to_handle, [copied_string_i8])

        # Allocate JsonString (8 bytes payload = i64 handle)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_STRING)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store string HANDLE at offset 0 (not raw pointer)
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        builder.store(string_handle, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_array(self):
        """Implement json_new_array(List*): allocate a JsonArray variant.

        First-class JSON variant: TYPE_JSON_ARRAY with 8 bytes payload (i64 HANDLE to List).

        INVARIANT: JSON deep-copy semantics. The List* passed to this function
        MUST be a freshly-created list that the JSON will own. The list must
        contain Json* pointers (as i64) that are themselves independently-owned
        values. Callers (convert_list_to_json_array, json_from_cjson) are
        responsible for creating new lists with deep-copied Json elements.

        HANDLE STORAGE INVARIANT: We store an i64 handle (gc_ptr_to_handle), not a
        raw pointer. The GC marks this handle during collection.
        """
        cg = self.cg
        func = cg.json_new_array
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Convert list pointer to handle (HANDLE STORAGE INVARIANT)
        list_i8 = builder.bitcast(func.args[0], ir.IntType(8).as_pointer())
        list_handle = builder.call(cg.gc.gc_ptr_to_handle, [list_i8])

        # Allocate JsonArray (8 bytes payload = i64 handle)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_ARRAY)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store list HANDLE at offset 0 (not raw pointer)
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        builder.store(list_handle, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_object(self):
        """Implement json_new_object(Map*): allocate a JsonObject variant.

        First-class JSON variant: TYPE_JSON_OBJECT with 8 bytes payload (i64 HANDLE to Map).

        INVARIANT: JSON deep-copy semantics. The Map* passed to this function
        MUST be a freshly-created map that the JSON will own. The map must
        contain String* keys (which are immutable literals or deep-copied)
        and Json* values (as i64) that are independently-owned values.
        Callers (generate_json_object, json_from_cjson) are responsible for
        creating new maps with properly-owned keys and deep-copied Json values.

        HANDLE STORAGE INVARIANT: We store an i64 handle (gc_ptr_to_handle), not a
        raw pointer. The GC marks this handle during collection.
        """
        cg = self.cg
        func = cg.json_new_object
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Convert map pointer to handle (HANDLE STORAGE INVARIANT)
        map_i8 = builder.bitcast(func.args[0], ir.IntType(8).as_pointer())
        map_handle = builder.call(cg.gc.gc_ptr_to_handle, [map_i8])

        # Allocate JsonObject (8 bytes payload = i64 handle)
        json_size = ir.Constant(i64, 8)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON_OBJECT)
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Store map HANDLE at offset 0 (not raw pointer)
        value_ptr = builder.bitcast(raw_ptr, i64.as_pointer())
        builder.store(map_handle, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_get_tag(self):
        """Implement json_get_tag(Json*): return the type tag.

        For first-class JSON variants, we read the type_id from the GC header
        and convert it to a tag value (0-6) for compatibility with existing code.
        """
        cg = self.cg
        func = cg.json_get_tag
        func.args[0].name = "json"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get type_id from object header (header is at ptr - 32, type_id is field 1)
        json_i8 = builder.bitcast(func.args[0], ir.IntType(8).as_pointer())
        json_int = builder.ptrtoint(json_i8, i64)
        header_int = builder.sub(json_int, ir.Constant(i64, cg.gc.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, cg.gc.header_type.as_pointer())
        type_id_ptr = builder.gep(header_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        type_id = builder.load(type_id_ptr)

        # Convert type_id to tag: TYPE_JSON_NULL(14)->0, TYPE_JSON_BOOL(15)->1, etc.
        # tag = type_id - TYPE_JSON_NULL
        tag = builder.sub(type_id, ir.Constant(i64, cg.gc.TYPE_JSON_NULL))
        builder.ret(tag)

    def _get_json_type_id(self, builder, json_ptr):
        """Helper: Get type_id from JSON object's GC header.

        Returns the type_id (i64) from the object header at ptr - HEADER_SIZE.
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        json_i8 = builder.bitcast(json_ptr, ir.IntType(8).as_pointer())
        json_int = builder.ptrtoint(json_i8, i64)
        header_int = builder.sub(json_int, ir.Constant(i64, cg.gc.HEADER_SIZE))
        header_ptr = builder.inttoptr(header_int, cg.gc.header_type.as_pointer())
        type_id_ptr = builder.gep(header_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        return builder.load(type_id_ptr)

    def _implement_json_get_field(self):
        """Implement json_get_field(Json*, String*): get field from object, return null json if not found.

        For first-class JSON variants, checks type_id == TYPE_JSON_OBJECT.
        The value (map handle) is stored at offset 0 as an i64 handle.
        """
        cg = self.cg
        func = cg.json_get_field
        func.args[0].name = "json"
        func.args[1].name = "key"

        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        found = func.append_basic_block("found")
        not_found = func.append_basic_block("not_found")

        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Is object: load map handle from offset 0, deref, and look up key
        builder.position_at_end(is_object)
        # Value at offset 0 is an i64 HANDLE to the map
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        # Deref handle to get map pointer
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Call map_get_string to get the value
        result = builder.call(cg.map_get_string, [map_ptr, func.args[1]])

        # Check if found (result != 0, since 0 indicates not found for map_get)
        # For JSON, we store Json* as i64. If not found, we return json null.
        is_found = builder.icmp_unsigned("!=", result, ir.Constant(i64, 0))
        builder.cbranch(is_found, found, not_found)

        # Found: convert i64 back to Json*
        builder.position_at_end(found)
        json_result = builder.inttoptr(result, cg.json_struct.as_pointer())
        builder.ret(json_result)

        # Not found or not object: return json null
        builder.position_at_end(not_object)
        null_json_1 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_1)

        builder.position_at_end(not_found)
        null_json_2 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_2)

    def _implement_json_get_index(self):
        """Implement json_get_index(Json*, i64): get element from array, return null json if out of bounds.

        For first-class JSON variants, checks type_id == TYPE_JSON_ARRAY.
        The value (list handle) is stored at offset 0 as an i64 handle.
        """
        cg = self.cg
        func = cg.json_get_index
        func.args[0].name = "json"
        func.args[1].name = "index"

        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        not_array = func.append_basic_block("not_array")
        in_bounds = func.append_basic_block("in_bounds")
        out_of_bounds = func.append_basic_block("out_of_bounds")

        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if array (type_id == TYPE_JSON_ARRAY)
        is_arr = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Is array: load list handle from offset 0, deref, and get element
        builder.position_at_end(is_array)
        # Value at offset 0 is an i64 HANDLE to the list
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        list_handle = builder.load(value_ptr)
        # Deref handle to get list pointer
        list_i8 = builder.call(cg.gc.gc_handle_deref, [list_handle])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())

        # Get list length
        len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        list_len = builder.load(len_ptr)

        # Check bounds
        idx = func.args[1]
        in_range = builder.icmp_signed("<", idx, list_len)
        non_negative = builder.icmp_signed(">=", idx, ir.Constant(i64, 0))
        valid = builder.and_(in_range, non_negative)
        builder.cbranch(valid, in_bounds, out_of_bounds)

        # In bounds: get element (TaggedValue {i64 type_id, i64 value})
        builder.position_at_end(in_bounds)
        result = builder.call(cg.list_get, [list_ptr, idx])
        # Extract value from TaggedValue - value is the GC handle
        tv_ptr = builder.bitcast(result, cg.gc.tagged_value_ptr_type)
        _, elem_handle = cg.gc.extract_tagged_value(builder, tv_ptr)
        elem_i8 = builder.call(cg.gc.gc_handle_deref, [elem_handle])
        json_result = builder.bitcast(elem_i8, cg.json_struct.as_pointer())
        builder.ret(json_result)

        # Not array or out of bounds: return json null
        builder.position_at_end(not_array)
        null_json_1 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_1)

        builder.position_at_end(out_of_bounds)
        null_json_2 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_2)

    def _implement_json_is_null(self):
        """Implement is_null(): check if json value is null (type_id == TYPE_JSON_NULL)."""
        cg = self.cg
        func = cg.json_is_null
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_NULL))
        builder.ret(result)

    def _implement_json_is_bool(self):
        """Implement is_bool(): check if json value is a boolean (type_id == TYPE_JSON_BOOL)."""
        cg = self.cg
        func = cg.json_is_bool
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_BOOL))
        builder.ret(result)

    def _implement_json_is_int(self):
        """Implement is_int(): check if json value is an integer (type_id == TYPE_JSON_INT)."""
        cg = self.cg
        func = cg.json_is_int
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_INT))
        builder.ret(result)

    def _implement_json_is_float(self):
        """Implement is_float(): check if json value is a float (type_id == TYPE_JSON_FLOAT)."""
        cg = self.cg
        func = cg.json_is_float
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT))
        builder.ret(result)

    def _implement_json_is_string(self):
        """Implement is_string(): check if json value is a string (type_id == TYPE_JSON_STRING)."""
        cg = self.cg
        func = cg.json_is_string
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_STRING))
        builder.ret(result)

    def _implement_json_is_array(self):
        """Implement is_array(): check if json value is an array (type_id == TYPE_JSON_ARRAY)."""
        cg = self.cg
        func = cg.json_is_array
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))
        builder.ret(result)

    def _implement_json_is_object(self):
        """Implement is_object(): check if json value is an object (type_id == TYPE_JSON_OBJECT)."""
        cg = self.cg
        func = cg.json_is_object
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        type_id = self._get_json_type_id(builder, func.args[0])
        result = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.ret(result)

    def _implement_json_as_int(self):
        """Implement as_int(): return the integer value from json.

        For first-class JSON variants, value is stored at offset 0 (8 bytes).

        BUG-072 FIX: Check the type and convert floats to ints properly.
        - TYPE_JSON_INT: return the raw i64 value
        - TYPE_JSON_FLOAT: convert f64 to i64 via fptosi
        - Other types: return 0
        """
        cg = self.cg
        func = cg.json_as_int
        func.args[0].name = "json"

        entry = func.append_basic_block("entry")
        is_int = func.append_basic_block("is_int")
        check_float = func.append_basic_block("check_float")
        is_float = func.append_basic_block("is_float")
        return_zero = func.append_basic_block("return_zero")

        builder = ir.IRBuilder(entry)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        json_ptr = func.args[0]

        # Get type_id from GC header
        type_id = self._get_json_type_id(builder, json_ptr)

        # Check if TYPE_JSON_INT (16)
        is_int_type = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_INT))
        builder.cbranch(is_int_type, is_int, check_float)

        # TYPE_JSON_INT: return the raw i64 value
        builder.position_at_end(is_int)
        value_ptr_int = builder.bitcast(json_ptr, i64.as_pointer())
        int_value = builder.load(value_ptr_int)
        builder.ret(int_value)

        # Check if TYPE_JSON_FLOAT (17)
        builder.position_at_end(check_float)
        is_float_type = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT))
        builder.cbranch(is_float_type, is_float, return_zero)

        # TYPE_JSON_FLOAT: convert f64 to i64
        builder.position_at_end(is_float)
        value_ptr_float = builder.bitcast(json_ptr, i64.as_pointer())
        float_bits = builder.load(value_ptr_float)
        float_value = builder.bitcast(float_bits, ir.DoubleType())
        converted_int = builder.fptosi(float_value, i64)
        builder.ret(converted_int)

        # Other types: return 0
        builder.position_at_end(return_zero)
        builder.ret(ir.Constant(i64, 0))

    def _implement_json_as_float(self):
        """Implement as_float(): return the float value from json.

        For first-class JSON variants, value is stored at offset 0 (f64 bitcast to i64).

        BUG-072 FIX: Check the type and convert ints to floats properly.
        - TYPE_JSON_FLOAT: return the raw f64 value (bitcast from i64)
        - TYPE_JSON_INT: convert i64 to f64 via sitofp
        - Other types: return 0.0
        """
        cg = self.cg
        func = cg.json_as_float
        func.args[0].name = "json"

        entry = func.append_basic_block("entry")
        is_float = func.append_basic_block("is_float")
        check_int = func.append_basic_block("check_int")
        is_int = func.append_basic_block("is_int")
        return_zero = func.append_basic_block("return_zero")

        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)
        f64 = ir.DoubleType()
        json_ptr = func.args[0]

        # Get type_id from GC header
        type_id = self._get_json_type_id(builder, json_ptr)

        # Check if TYPE_JSON_FLOAT (17)
        is_float_type = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT))
        builder.cbranch(is_float_type, is_float, check_int)

        # TYPE_JSON_FLOAT: return the raw f64 value
        builder.position_at_end(is_float)
        value_ptr_float = builder.bitcast(json_ptr, i64.as_pointer())
        float_bits = builder.load(value_ptr_float)
        float_value = builder.bitcast(float_bits, f64)
        builder.ret(float_value)

        # Check if TYPE_JSON_INT (16)
        builder.position_at_end(check_int)
        is_int_type = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_INT))
        builder.cbranch(is_int_type, is_int, return_zero)

        # TYPE_JSON_INT: convert i64 to f64
        builder.position_at_end(is_int)
        value_ptr_int = builder.bitcast(json_ptr, i64.as_pointer())
        int_value = builder.load(value_ptr_int)
        converted_float = builder.sitofp(int_value, f64)
        builder.ret(converted_float)

        # Other types: return 0.0
        builder.position_at_end(return_zero)
        builder.ret(ir.Constant(f64, 0.0))

    def _implement_json_as_bool(self):
        """Implement as_bool(): return the boolean value from json.

        For first-class JSON variants, value is stored at offset 0 (i64 with 0/1).
        """
        cg = self.cg
        func = cg.json_as_bool
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        # Load value from offset 0 (stored as zext i64) and truncate to i1
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        value_i64 = builder.load(value_ptr)
        value = builder.trunc(value_i64, ir.IntType(1))
        builder.ret(value)

    def _implement_json_as_string(self):
        """Implement as_string(): return the string value from json.

        For first-class JSON variants, value is stored at offset 0 as an i64 HANDLE.
        We deref the handle to get the String* pointer.
        """
        cg = self.cg
        func = cg.json_as_string
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i64 = ir.IntType(64)

        # Load handle from offset 0
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        string_handle = builder.load(value_ptr)
        # Deref handle to get String* pointer
        string_i8 = builder.call(cg.gc.gc_handle_deref, [string_handle])
        value = builder.bitcast(string_i8, cg.string_struct.as_pointer())
        builder.ret(value)

    def _implement_json_to_string(self):
        """Implement to_string(): smart conversion to string.

        For string json, returns the raw string value (no quotes).
        For int/float/bool, converts to string.
        For null, returns "null".
        For arrays/objects, falls back to stringify (with quotes).

        Uses type_id from header to determine variant.
        """
        cg = self.cg
        func = cg.json_to_string
        i64 = ir.IntType(64)

        # Create all blocks upfront
        entry = func.append_basic_block("entry")
        str_check = func.append_basic_block("str_check")
        str_handle = func.append_basic_block("str_handle")
        int_check = func.append_basic_block("int_check")
        int_handle = func.append_basic_block("int_handle")
        float_check = func.append_basic_block("float_check")
        float_handle = func.append_basic_block("float_handle")
        bool_check = func.append_basic_block("bool_check")
        bool_handle = func.append_basic_block("bool_handle")
        null_check = func.append_basic_block("null_check")
        null_handle = func.append_basic_block("null_handle")
        fallback = func.append_basic_block("fallback")

        builder = ir.IRBuilder(entry)
        json_ptr = func.args[0]

        # Get type_id from header
        type_id = self._get_json_type_id(builder, json_ptr)
        builder.branch(str_check)

        # Check for string (type_id == TYPE_JSON_STRING)
        builder.position_at_end(str_check)
        is_str = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_STRING))
        builder.cbranch(is_str, str_handle, int_check)

        # String case: return raw string value
        builder.position_at_end(str_handle)
        str_result = builder.call(cg.json_as_string, [json_ptr])
        builder.ret(str_result)

        # Check for int (type_id == TYPE_JSON_INT)
        builder.position_at_end(int_check)
        is_i = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_INT))
        builder.cbranch(is_i, int_handle, float_check)

        # Int case: convert to string
        builder.position_at_end(int_handle)
        int_val = builder.call(cg.json_as_int, [json_ptr])
        int_str = builder.call(cg.string_from_int, [int_val])
        builder.ret(int_str)

        # Check for float (type_id == TYPE_JSON_FLOAT)
        builder.position_at_end(float_check)
        is_f = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT))
        builder.cbranch(is_f, float_handle, bool_check)

        # Float case: convert to string
        builder.position_at_end(float_handle)
        float_val = builder.call(cg.json_as_float, [json_ptr])
        float_str = builder.call(cg.string_from_float, [float_val])
        builder.ret(float_str)

        # Check for bool (type_id == TYPE_JSON_BOOL)
        builder.position_at_end(bool_check)
        is_b = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_BOOL))
        builder.cbranch(is_b, bool_handle, null_check)

        # Bool case: convert to string
        builder.position_at_end(bool_handle)
        bool_val = builder.call(cg.json_as_bool, [json_ptr])
        bool_str = builder.call(cg.string_from_bool, [bool_val])
        builder.ret(bool_str)

        # Check for null (type_id == TYPE_JSON_NULL)
        builder.position_at_end(null_check)
        is_n = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_NULL))
        builder.cbranch(is_n, null_handle, fallback)

        # Null case: return "null"
        builder.position_at_end(null_handle)
        null_literal = self._get_or_create_global_string(builder, "null", "to_string_null")
        builder.ret(null_literal)

        # Fallback: use stringify for arrays/objects
        builder.position_at_end(fallback)
        stringify_result = builder.call(cg.json_stringify, [json_ptr])
        builder.ret(stringify_result)

    def _implement_json_len(self):
        """Implement len(): return length of array/object, 0 otherwise.

        Uses type_id from header to determine variant. Value is at offset 0 as handle.
        """
        cg = self.cg
        func = cg.json_len
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        is_object = func.append_basic_block("is_object")
        get_obj_len = func.append_basic_block("get_obj_len")
        not_collection = func.append_basic_block("not_collection")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if array (type_id == TYPE_JSON_ARRAY)
        is_arr = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))
        builder.cbranch(is_arr, is_array, is_object)

        # Array: load handle, deref, get list length
        builder.position_at_end(is_array)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        list_handle = builder.load(value_ptr)
        list_i8 = builder.call(cg.gc.gc_handle_deref, [list_handle])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())
        arr_len = builder.call(cg.list_len, [list_ptr])
        builder.ret(arr_len)

        # Check if object (type_id == TYPE_JSON_OBJECT)
        builder.position_at_end(is_object)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, get_obj_len, not_collection)

        # Object: load handle, deref, get map length
        builder.position_at_end(get_obj_len)
        value_ptr2 = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr2)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())
        obj_len = builder.call(cg.map_len, [map_ptr])
        builder.ret(obj_len)

        # Not a collection: return 0
        builder.position_at_end(not_collection)
        builder.ret(ir.Constant(i64, 0))

    def _implement_json_has(self):
        """Implement has(key): check if object has a key.

        Uses type_id from header. Value (map handle) is at offset 0.
        """
        cg = self.cg
        func = cg.json_has
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i1 = ir.IntType(1)
        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: load handle, deref, check map.has_string(key)
        builder.position_at_end(is_object)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())
        has_result = builder.call(cg.map_has_string, [map_ptr, func.args[1]])
        builder.ret(has_result)

        # Not object: return false
        builder.position_at_end(not_object)
        builder.ret(ir.Constant(i1, 0))

    def _implement_json_set_field(self):
        """Implement set(key, value): return new json with field set.

        Uses type_id from header. Value (map handle) is at offset 0.
        """
        cg = self.cg
        func = cg.json_set_field
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: load handle, deref, create new map with key set
        builder.position_at_end(is_object)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Convert json value to i64 for map storage (pointer as i64)
        json_val = func.args[2]
        json_as_i64 = builder.ptrtoint(json_val, i64)

        # Call map_set_string
        new_map = builder.call(cg.map_set_string, [map_ptr, func.args[1], json_as_i64])

        # Create new json object with new map
        result = builder.call(cg.json_new_object, [new_map])
        builder.ret(result)

        # Not object: return the original json unchanged
        builder.position_at_end(not_object)
        builder.ret(func.args[0])

    def _implement_json_set_index(self):
        """Implement set(index, value): return new json with array element set.

        Uses type_id from header. Value (list handle) is at offset 0.
        Stores TaggedValue {type_id, handle} like json_get_index expects.
        """
        cg = self.cg
        func = cg.json_set_index
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        not_array = func.append_basic_block("not_array")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if array (type_id == TYPE_JSON_ARRAY)
        is_arr = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Array: load handle, deref, create new list with element set
        builder.position_at_end(is_array)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        list_handle = builder.load(value_ptr)
        list_i8 = builder.call(cg.gc.gc_handle_deref, [list_handle])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())

        # Convert Json* to handle for storage (HANDLE STORAGE INVARIANT)
        # This matches what json_get_index expects: TaggedValue with handle
        json_val = func.args[2]
        json_val_i8 = builder.bitcast(json_val, i8.as_pointer())
        json_handle = builder.call(cg.gc.gc_ptr_to_handle, [json_val_i8])

        # Create TaggedValue with JSON handle (matches json_append and json_get_index)
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, json_handle)
        tv_i8 = builder.bitcast(tv_ptr, i8.as_pointer())

        # Call list_set with TaggedValue size
        new_list = builder.call(cg.list_set, [list_ptr, func.args[1], tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])

        # Create new json array with new list
        result = builder.call(cg.json_new_array, [new_list])
        builder.ret(result)

        # Not array: return the original json unchanged
        builder.position_at_end(not_array)
        builder.ret(func.args[0])

    def _implement_json_append(self):
        """Implement append(value): return new json with value appended to array.

        Uses type_id from header. Value (list handle) is at offset 0.
        Now stores Json* pointers (8 bytes) instead of full structs.
        """
        cg = self.cg
        func = cg.json_append
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        not_array = func.append_basic_block("not_array")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if array (type_id == TYPE_JSON_ARRAY)
        is_arr = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Array: load handle, deref, append value
        builder.position_at_end(is_array)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        list_handle = builder.load(value_ptr)
        list_i8 = builder.call(cg.gc.gc_handle_deref, [list_handle])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())

        # Convert Json* to handle for storage (HANDLE STORAGE INVARIANT)
        json_val = func.args[1]
        json_val_i8 = builder.bitcast(json_val, i8.as_pointer())
        json_handle = builder.call(cg.gc.gc_ptr_to_handle, [json_val_i8])

        # Create TaggedValue with JSON handle
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, json_handle)
        tv_i8 = builder.bitcast(tv_ptr, i8.as_pointer())

        # Call list_append with TaggedValue size
        new_list = builder.call(cg.list_append, [list_ptr, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])

        # Create new json array with new list
        result = builder.call(cg.json_new_array, [new_list])
        builder.ret(result)

        # Not array: return the original json unchanged
        builder.position_at_end(not_array)
        builder.ret(func.args[0])

    def _implement_json_remove(self):
        """Implement remove(key): return new json with key removed from object.

        Uses type_id from header. Value (map handle) is at offset 0.
        """
        cg = self.cg
        func = cg.json_remove
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: load handle, deref, remove key
        builder.position_at_end(is_object)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Call map_remove_string (JSON objects use string keys)
        new_map = builder.call(cg.map_remove_string, [map_ptr, func.args[1]])

        # Create new json object with new map
        result = builder.call(cg.json_new_object, [new_map])
        builder.ret(result)

        # Not object: return the original json unchanged
        builder.position_at_end(not_object)
        builder.ret(func.args[0])

    def _implement_json_keys(self):
        """Implement keys(): return list of keys from object.

        Uses type_id from header. Value (map handle) is at offset 0.
        """
        cg = self.cg
        func = cg.json_keys
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: load handle, deref, get keys from map
        builder.position_at_end(is_object)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Call map_keys
        keys_list = builder.call(cg.map_keys, [map_ptr])
        builder.ret(keys_list)

        # Not object: return empty list
        builder.position_at_end(not_object)
        # Create empty list of strings (reference types)
        elem_size = ir.Constant(i64, 8)  # String handles are i64
        list_flags = ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)  # Strings are reference types
        empty_list = builder.call(cg.list_new, [elem_size, list_flags])
        builder.ret(empty_list)

    def _implement_json_values(self):
        """Implement values(): return list of values from object.

        Uses type_id from header. Value (map handle) is at offset 0.
        """
        cg = self.cg
        func = cg.json_values
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Check if object (type_id == TYPE_JSON_OBJECT)
        is_obj = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: load handle, deref, get values from map
        builder.position_at_end(is_object)
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        map_handle = builder.load(value_ptr)
        map_i8 = builder.call(cg.gc.gc_handle_deref, [map_handle])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Call map_values
        values_list = builder.call(cg.map_values, [map_ptr])
        builder.ret(values_list)

        # Not object: return empty list of json values (pointers now, 8 bytes)
        builder.position_at_end(not_object)
        elem_size = ir.Constant(i64, 8)  # Json* pointers are 8 bytes
        list_flags = ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)  # Json* are reference types
        empty_list = builder.call(cg.list_new, [elem_size, list_flags])
        builder.ret(empty_list)

    def _implement_json_stringify(self):
        """Implement json_stringify(Json*) -> String*: serialize JSON to string.

        Uses type_id from header to dispatch. Value is at offset 0 (8 bytes).
        """
        cg = self.cg
        func = cg.json_stringify
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i64 = ir.IntType(64)

        # Get type_id from header
        type_id = self._get_json_type_id(builder, func.args[0])

        # Get value at offset 0
        value_ptr = builder.bitcast(func.args[0], i64.as_pointer())
        value = builder.load(value_ptr)

        # Create blocks for each JSON type
        null_block = func.append_basic_block("null")
        bool_block = func.append_basic_block("bool")
        int_block = func.append_basic_block("int")
        float_block = func.append_basic_block("float")
        string_block = func.append_basic_block("string")
        array_block = func.append_basic_block("array")
        object_block = func.append_basic_block("object")
        done_block = func.append_basic_block("done")

        # Allocate result pointer
        result_ptr = builder.alloca(cg.string_struct.as_pointer(), name="result")

        # Switch on type_id
        switch = builder.switch(type_id, null_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_NULL), null_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_BOOL), bool_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_INT), int_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT), float_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_STRING), string_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY), array_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT), object_block)

        # NULL: return "null"
        builder.position_at_end(null_block)
        null_str = self._get_or_create_global_string(builder, "null", "null")
        builder.store(null_str, result_ptr)
        builder.branch(done_block)

        # BOOL: return "true" or "false"
        builder.position_at_end(bool_block)
        bool_val = builder.trunc(value, ir.IntType(1))
        true_str = self._get_or_create_global_string(builder, "true", "true")
        false_str = self._get_or_create_global_string(builder, "false", "false")
        bool_str = builder.select(bool_val, true_str, false_str)
        builder.store(bool_str, result_ptr)
        builder.branch(done_block)

        # INT: convert to string using string_from_int
        builder.position_at_end(int_block)
        int_str = builder.call(cg.string_from_int, [value])
        builder.store(int_str, result_ptr)
        builder.branch(done_block)

        # FLOAT: convert to string using string_from_float
        builder.position_at_end(float_block)
        float_val = builder.bitcast(value, ir.DoubleType())
        float_str = builder.call(cg.string_from_float, [float_val])
        builder.store(float_str, result_ptr)
        builder.branch(done_block)

        # STRING: wrap in quotes (value is a HANDLE, need to deref)
        builder.position_at_end(string_block)
        str_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        str_ptr = builder.bitcast(str_i8, cg.string_struct.as_pointer())
        # Build "\"" + str + "\""
        quote_str = self._get_or_create_global_string(builder, '"', "quote")
        temp = builder.call(cg.string_concat, [quote_str, str_ptr])
        quoted_str = builder.call(cg.string_concat, [temp, quote_str])
        builder.store(quoted_str, result_ptr)
        builder.branch(done_block)

        # ARRAY: serialize as [elem1, elem2, ...] (value is a HANDLE)
        builder.position_at_end(array_block)
        self._stringify_array(builder, func, value, result_ptr)
        builder.branch(done_block)

        # OBJECT: serialize as {key1: val1, ...} (value is a HANDLE)
        builder.position_at_end(object_block)
        self._stringify_object(builder, func, value, result_ptr)
        builder.branch(done_block)

        # Done: return result
        builder.position_at_end(done_block)
        result = builder.load(result_ptr)
        builder.ret(result)

    def _get_or_create_global_string(self, builder: ir.IRBuilder, s: str, name: str) -> ir.Value:
        """Get or create a global string constant and return String* pointer."""
        cg = self.cg
        # Create or get global string data
        s_bytes = s.encode('utf-8')
        global_name = f"str_{name}_{hash(s) & 0xFFFFFFFF}"

        if global_name not in cg.string_constants:
            str_type = ir.ArrayType(ir.IntType(8), len(s_bytes) + 1)
            global_str = ir.GlobalVariable(cg.module, str_type, global_name)
            global_str.global_constant = True
            global_str.initializer = ir.Constant(str_type, bytearray(s_bytes + b'\0'))
            global_str.linkage = 'private'
            cg.string_constants[global_name] = global_str

        global_str = cg.string_constants[global_name]

        # Use string_from_literal like _get_string_ptr does
        raw_ptr = builder.bitcast(global_str, ir.IntType(8).as_pointer())
        return builder.call(cg.string_from_literal, [raw_ptr])

    def _stringify_array(self, builder: ir.IRBuilder, func: ir.Function, value: ir.Value,
                         result_ptr: ir.Value):
        """Generate code to stringify a JSON array.

        Uses O(n) algorithm:
        1. First loop: stringify each element into a List<String>
        2. Use string_join_list to combine with "," separator
        3. Wrap with "[" and "]"

        value is now an i64 HANDLE to the List (not a raw pointer).
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Deref handle to get list pointer
        list_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())

        # Get list length
        list_len = builder.call(cg.list_len, [list_ptr])

        # Create a new list to hold stringified elements (TaggedValue size)
        string_list = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])
        string_list_ptr = builder.alloca(cg.list_struct.as_pointer(), name="string_list")
        builder.store(string_list, string_list_ptr)

        # Allocate temp storage OUTSIDE loop to avoid stack overflow
        temp_ptr = builder.alloca(i64, name="temp_str_ptr")

        # Loop through elements and stringify each one
        loop_block = func.append_basic_block("array_loop")
        body_block = func.append_basic_block("array_body")
        array_done = func.append_basic_block("array_done")

        # Initialize index
        idx_ptr = builder.alloca(i64, name="idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.branch(loop_block)

        # Loop condition
        builder.position_at_end(loop_block)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, body_block, array_done)

        # Loop body - stringify element and append to string list
        builder.position_at_end(body_block)
        elem_data_ptr = builder.call(cg.list_get, [list_ptr, idx])
        # Extract handle from TaggedValue {i64 type_id, i64 value}
        tv_ptr = builder.bitcast(elem_data_ptr, cg.gc.tagged_value_ptr_type)
        _, elem_handle = cg.gc.extract_tagged_value(builder, tv_ptr)
        elem_json_i8 = builder.call(cg.gc.gc_handle_deref, [elem_handle])
        elem_json = builder.bitcast(elem_json_i8, cg.json_struct.as_pointer())
        elem_str = builder.call(cg.json_stringify, [elem_json])

        # Append to string list (reuse pre-allocated temp_ptr)
        curr_list = builder.load(string_list_ptr)
        elem_str_i64 = builder.ptrtoint(elem_str, i64)
        # Create TaggedValue with TV_TYPE_STRING for string elements
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_STRING, elem_str_i64)
        tv_i8 = builder.bitcast(tv_ptr, ir.IntType(8).as_pointer())
        new_list = builder.call(cg.list_append, [curr_list, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])
        builder.store(new_list, string_list_ptr)

        # Increment and loop
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_block)

        # Done: join all strings with "," and wrap with "[" and "]"
        builder.position_at_end(array_done)
        final_list = builder.load(string_list_ptr)
        comma_str = self._get_or_create_global_string(builder, ",", "comma")
        joined_str = builder.call(cg.string_join_list, [final_list, comma_str])

        # Build "[" + joined + "]"
        open_bracket = self._get_or_create_global_string(builder, "[", "lbracket")
        close_bracket = self._get_or_create_global_string(builder, "]", "rbracket")
        temp = builder.call(cg.string_concat, [open_bracket, joined_str])
        final_str = builder.call(cg.string_concat, [temp, close_bracket])
        builder.store(final_str, result_ptr)

    def _stringify_object(self, builder: ir.IRBuilder, func: ir.Function, value: ir.Value,
                          result_ptr: ir.Value):
        """Generate code to stringify a JSON object.

        Uses O(n) algorithm:
        1. First loop: build "key":value strings into a List<String>
        2. Use string_join_list to combine with "," separator
        3. Wrap with "{" and "}"

        value is now an i64 HANDLE to the Map (not a raw pointer).
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Deref handle to get map pointer
        map_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Get keys list
        keys_list = builder.call(cg.map_keys, [map_ptr])
        list_len = builder.call(cg.list_len, [keys_list])

        # Create a new list to hold "key":value strings (TaggedValue size)
        string_list = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])
        string_list_ptr = builder.alloca(cg.list_struct.as_pointer(), name="kv_string_list")
        builder.store(string_list, string_list_ptr)

        # Allocate temp storage OUTSIDE loop to avoid stack overflow
        temp_ptr = builder.alloca(i64, name="temp_kv_ptr")

        # Loop through keys
        loop_block = func.append_basic_block("object_loop")
        body_block = func.append_basic_block("object_body")
        object_done = func.append_basic_block("object_done")

        # Initialize index
        idx_ptr = builder.alloca(i64, name="idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.branch(loop_block)

        # Loop condition
        builder.position_at_end(loop_block)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, body_block, object_done)

        # Loop body - build "key":value string and append to list
        builder.position_at_end(body_block)

        # Get key string - list_get returns i8* to TaggedValue {i64 type_id, i64 value}
        key_data_ptr = builder.call(cg.list_get, [keys_list, idx])
        tv_ptr = builder.bitcast(key_data_ptr, cg.gc.tagged_value_ptr_type)
        _, key_i64 = cg.gc.extract_tagged_value(builder, tv_ptr)
        key_str = builder.inttoptr(key_i64, cg.string_struct.as_pointer())

        # Build "key": string
        quote_str = self._get_or_create_global_string(builder, '"', "quote2")
        colon_str = self._get_or_create_global_string(builder, '":', "colon")
        kv_str = builder.call(cg.string_concat, [quote_str, key_str])
        kv_str = builder.call(cg.string_concat, [kv_str, colon_str])

        # Get value and stringify it
        val_i64 = builder.call(cg.map_get_string, [map_ptr, key_str])
        val_json = builder.inttoptr(val_i64, cg.json_struct.as_pointer())
        val_str = builder.call(cg.json_stringify, [val_json])
        kv_str = builder.call(cg.string_concat, [kv_str, val_str])

        # Append to string list (reuse pre-allocated temp_ptr)
        curr_list = builder.load(string_list_ptr)
        kv_str_i64 = builder.ptrtoint(kv_str, i64)
        # Create TaggedValue with TV_TYPE_STRING for string elements
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_STRING, kv_str_i64)
        tv_i8 = builder.bitcast(tv_ptr, ir.IntType(8).as_pointer())
        new_list = builder.call(cg.list_append, [curr_list, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])
        builder.store(new_list, string_list_ptr)

        # Increment and loop
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_block)

        # Done: join all strings with "," and wrap with "{" and "}"
        builder.position_at_end(object_done)
        final_list = builder.load(string_list_ptr)
        comma_str = self._get_or_create_global_string(builder, ",", "comma2")
        joined_str = builder.call(cg.string_join_list, [final_list, comma_str])

        # Build "{" + joined + "}"
        open_brace = self._get_or_create_global_string(builder, "{", "lbrace")
        close_brace = self._get_or_create_global_string(builder, "}", "rbrace")
        temp = builder.call(cg.string_concat, [open_brace, joined_str])
        final_str = builder.call(cg.string_concat, [temp, close_brace])
        builder.store(final_str, result_ptr)

    def _implement_json_pretty(self):
        """Implement json_pretty(Json*, i64 indent) -> String*: serialize JSON with pretty printing.

        This function calls a recursive helper that handles the actual pretty printing
        with proper indentation at each level.
        """
        cg = self.cg
        i64 = ir.IntType(64)
        json_ptr = cg.json_struct.as_pointer()

        # First, create the internal recursive function declaration
        func_ty = ir.FunctionType(cg.string_struct.as_pointer(), [json_ptr, i64, i64])
        cg.json_pretty_internal = ir.Function(cg.module, func_ty, name="coex_json_pretty_internal")

        # Now implement the main pretty function
        func = cg.json_pretty
        func.args[0].name = "json"
        func.args[1].name = "indent"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Call the internal recursive pretty printer with depth=0
        result = builder.call(cg.json_pretty_internal, [func.args[0], func.args[1], ir.Constant(i64, 0)])
        builder.ret(result)

        # Now implement the internal recursive function
        self._implement_json_pretty_internal()

    def _implement_json_pretty_internal(self):
        """Implement the internal recursive pretty printing function.

        json_pretty_internal(Json*, i64 indent_size, i64 depth) -> String*

        Uses type_id from header. Value is at offset 0 (8 bytes).
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Use the already-declared function
        func = cg.json_pretty_internal
        func.args[0].name = "json"
        func.args[1].name = "indent_size"
        func.args[2].name = "depth"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        json_val = func.args[0]
        indent_size = func.args[1]
        depth = func.args[2]

        # Get type_id from header
        type_id = self._get_json_type_id(builder, json_val)

        # Get value at offset 0
        value_ptr = builder.bitcast(json_val, i64.as_pointer())
        value = builder.load(value_ptr)

        # Create blocks for each JSON type
        null_block = func.append_basic_block("null")
        bool_block = func.append_basic_block("bool")
        int_block = func.append_basic_block("int")
        float_block = func.append_basic_block("float")
        string_block = func.append_basic_block("string")
        array_block = func.append_basic_block("array")
        object_block = func.append_basic_block("object")
        done_block = func.append_basic_block("done")

        # Allocate result pointer
        result_ptr = builder.alloca(cg.string_struct.as_pointer(), name="result")

        # Switch on type_id
        switch = builder.switch(type_id, null_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_NULL), null_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_BOOL), bool_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_INT), int_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_FLOAT), float_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_STRING), string_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY), array_block)
        switch.add_case(ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT), object_block)

        # NULL: return "null"
        builder.position_at_end(null_block)
        null_str = self._get_or_create_global_string(builder, "null", "pretty_null")
        builder.store(null_str, result_ptr)
        builder.branch(done_block)

        # BOOL: return "true" or "false"
        builder.position_at_end(bool_block)
        bool_val = builder.trunc(value, ir.IntType(1))
        true_str = self._get_or_create_global_string(builder, "true", "pretty_true")
        false_str = self._get_or_create_global_string(builder, "false", "pretty_false")
        bool_str = builder.select(bool_val, true_str, false_str)
        builder.store(bool_str, result_ptr)
        builder.branch(done_block)

        # INT: convert to string
        builder.position_at_end(int_block)
        int_str = builder.call(cg.string_from_int, [value])
        builder.store(int_str, result_ptr)
        builder.branch(done_block)

        # FLOAT: convert to string
        builder.position_at_end(float_block)
        float_val = builder.bitcast(value, ir.DoubleType())
        float_str = builder.call(cg.string_from_float, [float_val])
        builder.store(float_str, result_ptr)
        builder.branch(done_block)

        # STRING: wrap in quotes (value is HANDLE, need to deref)
        builder.position_at_end(string_block)
        str_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        str_ptr = builder.bitcast(str_i8, cg.string_struct.as_pointer())
        quote_str = self._get_or_create_global_string(builder, '"', "pretty_quote")
        temp = builder.call(cg.string_concat, [quote_str, str_ptr])
        quoted_str = builder.call(cg.string_concat, [temp, quote_str])
        builder.store(quoted_str, result_ptr)
        builder.branch(done_block)

        # ARRAY: serialize with pretty printing (value is HANDLE)
        builder.position_at_end(array_block)
        self._pretty_array(builder, func, value, indent_size, depth, result_ptr)
        builder.branch(done_block)

        # OBJECT: serialize with pretty printing (value is HANDLE)
        builder.position_at_end(object_block)
        self._pretty_object(builder, func, value, indent_size, depth, result_ptr)
        builder.branch(done_block)

        # Done: return result
        builder.position_at_end(done_block)
        result = builder.load(result_ptr)
        builder.ret(result)

    def _make_indent_string(self, builder: ir.IRBuilder, indent_size: ir.Value, depth: ir.Value) -> ir.Value:
        """Create an indentation string of (indent_size * depth) spaces."""
        cg = self.cg
        i64 = ir.IntType(64)

        # Calculate total spaces needed
        total_spaces = builder.mul(indent_size, depth)

        # Create a single space string
        space_str = self._get_or_create_global_string(builder, " ", "space")

        # Build the indent string by concatenating spaces
        # For simplicity, we'll use a loop
        func = builder.function
        loop_cond = func.append_basic_block("indent_loop_cond")
        loop_body = func.append_basic_block("indent_loop_body")
        loop_done = func.append_basic_block("indent_loop_done")

        # Initialize
        idx_ptr = builder.alloca(i64, name="indent_idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        result_ptr = builder.alloca(cg.string_struct.as_pointer(), name="indent_str")
        empty_str = self._get_or_create_global_string(builder, "", "empty")
        builder.store(empty_str, result_ptr)
        builder.branch(loop_cond)

        # Loop condition
        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, total_spaces)
        builder.cbranch(cmp, loop_body, loop_done)

        # Loop body: append a space
        builder.position_at_end(loop_body)
        curr_str = builder.load(result_ptr)
        new_str = builder.call(cg.string_concat, [curr_str, space_str])
        builder.store(new_str, result_ptr)
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_cond)

        # Done
        builder.position_at_end(loop_done)
        return builder.load(result_ptr)

    def _pretty_array(self, builder: ir.IRBuilder, func: ir.Function, value: ir.Value,
                      indent_size: ir.Value, depth: ir.Value, result_ptr: ir.Value):
        """Generate code to pretty-print a JSON array.

        value is now an i64 HANDLE to the List (not a raw pointer).
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Deref handle to get list pointer
        list_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())

        # Get list length
        list_len = builder.call(cg.list_len, [list_ptr])

        # Check if empty
        is_empty = builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        empty_block = func.append_basic_block("array_empty")
        nonempty_block = func.append_basic_block("array_nonempty")
        builder.cbranch(is_empty, empty_block, nonempty_block)

        # Empty array: return "[]"
        builder.position_at_end(empty_block)
        empty_arr_str = self._get_or_create_global_string(builder, "[]", "empty_arr")
        builder.store(empty_arr_str, result_ptr)
        array_done = func.append_basic_block("array_pretty_done")
        builder.branch(array_done)

        # Non-empty array
        builder.position_at_end(nonempty_block)
        # Start with "[\n"
        open_bracket = self._get_or_create_global_string(builder, "[\n", "arr_open")
        result_str_ptr = builder.alloca(cg.string_struct.as_pointer(), name="arr_str")
        builder.store(open_bracket, result_str_ptr)

        # Calculate child depth
        child_depth = builder.add(depth, ir.Constant(i64, 1))

        # Create child indent string
        child_indent = self._make_indent_string(builder, indent_size, child_depth)

        # Loop through elements
        loop_block = func.append_basic_block("arr_loop")
        body_block = func.append_basic_block("arr_body")
        after_loop = func.append_basic_block("arr_after_loop")

        idx_ptr = builder.alloca(i64, name="arr_idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.branch(loop_block)

        # Loop condition
        builder.position_at_end(loop_block)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, body_block, after_loop)

        # Loop body
        builder.position_at_end(body_block)
        curr_str = builder.load(result_str_ptr)

        # Add comma and newline if not first
        is_first = builder.icmp_signed("==", idx, ir.Constant(i64, 0))
        comma_nl = self._get_or_create_global_string(builder, ",\n", "comma_nl")
        with_comma = builder.call(cg.string_concat, [curr_str, comma_nl])
        curr_str = builder.select(is_first, curr_str, with_comma)

        # Add child indent
        curr_str = builder.call(cg.string_concat, [curr_str, child_indent])

        # Get element and pretty-print it - extract handle from TaggedValue
        elem_data_ptr = builder.call(cg.list_get, [list_ptr, idx])
        tv_ptr = builder.bitcast(elem_data_ptr, cg.gc.tagged_value_ptr_type)
        _, elem_handle = cg.gc.extract_tagged_value(builder, tv_ptr)
        elem_json_i8 = builder.call(cg.gc.gc_handle_deref, [elem_handle])
        elem_json = builder.bitcast(elem_json_i8, cg.json_struct.as_pointer())
        elem_str = builder.call(cg.json_pretty_internal, [elem_json, indent_size, child_depth])
        curr_str = builder.call(cg.string_concat, [curr_str, elem_str])
        builder.store(curr_str, result_str_ptr)

        # Increment and loop
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_block)

        # After loop: add newline, parent indent, and closing bracket
        builder.position_at_end(after_loop)
        final_str = builder.load(result_str_ptr)
        newline = self._get_or_create_global_string(builder, "\n", "newline")
        final_str = builder.call(cg.string_concat, [final_str, newline])
        parent_indent = self._make_indent_string(builder, indent_size, depth)
        final_str = builder.call(cg.string_concat, [final_str, parent_indent])
        close_bracket = self._get_or_create_global_string(builder, "]", "arr_close")
        final_str = builder.call(cg.string_concat, [final_str, close_bracket])
        builder.store(final_str, result_ptr)
        builder.branch(array_done)

        builder.position_at_end(array_done)

    def _pretty_object(self, builder: ir.IRBuilder, func: ir.Function, value: ir.Value,
                       indent_size: ir.Value, depth: ir.Value, result_ptr: ir.Value):
        """Generate code to pretty-print a JSON object.

        value is now an i64 HANDLE to the Map (not a raw pointer).
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Deref handle to get map pointer
        map_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Get keys list
        keys_list = builder.call(cg.map_keys, [map_ptr])
        list_len = builder.call(cg.list_len, [keys_list])

        # Check if empty
        is_empty = builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        empty_block = func.append_basic_block("obj_empty")
        nonempty_block = func.append_basic_block("obj_nonempty")
        builder.cbranch(is_empty, empty_block, nonempty_block)

        # Empty object: return "{}"
        builder.position_at_end(empty_block)
        empty_obj_str = self._get_or_create_global_string(builder, "{}", "empty_obj")
        builder.store(empty_obj_str, result_ptr)
        object_done = func.append_basic_block("obj_pretty_done")
        builder.branch(object_done)

        # Non-empty object
        builder.position_at_end(nonempty_block)
        # Start with "{\n"
        open_brace = self._get_or_create_global_string(builder, "{\n", "obj_open")
        result_str_ptr = builder.alloca(cg.string_struct.as_pointer(), name="obj_str")
        builder.store(open_brace, result_str_ptr)

        # Calculate child depth
        child_depth = builder.add(depth, ir.Constant(i64, 1))

        # Create child indent string
        child_indent = self._make_indent_string(builder, indent_size, child_depth)

        # Loop through keys
        loop_block = func.append_basic_block("obj_loop")
        body_block = func.append_basic_block("obj_body")
        after_loop = func.append_basic_block("obj_after_loop")

        idx_ptr = builder.alloca(i64, name="obj_idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)
        builder.branch(loop_block)

        # Loop condition
        builder.position_at_end(loop_block)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, list_len)
        builder.cbranch(cmp, body_block, after_loop)

        # Loop body
        builder.position_at_end(body_block)
        curr_str = builder.load(result_str_ptr)

        # Add comma and newline if not first
        is_first = builder.icmp_signed("==", idx, ir.Constant(i64, 0))
        comma_nl = self._get_or_create_global_string(builder, ",\n", "comma_nl2")
        with_comma = builder.call(cg.string_concat, [curr_str, comma_nl])
        curr_str = builder.select(is_first, curr_str, with_comma)

        # Add child indent
        curr_str = builder.call(cg.string_concat, [curr_str, child_indent])

        # Get key string - extract from TaggedValue
        key_data_ptr = builder.call(cg.list_get, [keys_list, idx])
        tv_ptr = builder.bitcast(key_data_ptr, cg.gc.tagged_value_ptr_type)
        _, key_i64 = cg.gc.extract_tagged_value(builder, tv_ptr)
        key_str = builder.inttoptr(key_i64, cg.string_struct.as_pointer())

        # Add quoted key: "key":
        quote_str = self._get_or_create_global_string(builder, '"', "pretty_quote2")
        colon_space = self._get_or_create_global_string(builder, '": ', "colon_space")
        curr_str = builder.call(cg.string_concat, [curr_str, quote_str])
        curr_str = builder.call(cg.string_concat, [curr_str, key_str])
        curr_str = builder.call(cg.string_concat, [curr_str, colon_space])

        # Get value and pretty-print it
        val_i64 = builder.call(cg.map_get_string, [map_ptr, key_str])
        val_json = builder.inttoptr(val_i64, cg.json_struct.as_pointer())
        val_str = builder.call(cg.json_pretty_internal, [val_json, indent_size, child_depth])
        curr_str = builder.call(cg.string_concat, [curr_str, val_str])
        builder.store(curr_str, result_str_ptr)

        # Increment and loop
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_block)

        # After loop: add newline, parent indent, and closing brace
        builder.position_at_end(after_loop)
        final_str = builder.load(result_str_ptr)
        newline = self._get_or_create_global_string(builder, "\n", "newline2")
        final_str = builder.call(cg.string_concat, [final_str, newline])
        parent_indent = self._make_indent_string(builder, indent_size, depth)
        final_str = builder.call(cg.string_concat, [final_str, parent_indent])
        close_brace = self._get_or_create_global_string(builder, "}", "obj_close")
        final_str = builder.call(cg.string_concat, [final_str, close_brace])
        builder.store(final_str, result_ptr)
        builder.branch(object_done)

        builder.position_at_end(object_done)

    def _implement_json_parse(self):
        """Implement json_parse(String*) -> Json*: parse string to JSON.
        Returns null JSON on parse error."""
        cg = self.cg
        func = cg.json_parse
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i64 = ir.IntType(64)

        # Get string data pointer and length
        # Phase 4: String layout is { i64 owner_handle, i64 offset, i64 len, i64 size }
        str_ptr = func.args[0]
        owner_handle_ptr = builder.gep(str_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(str_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)], inbounds=True)
        offset_val = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset_val])
        len_ptr = builder.gep(str_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 2)], inbounds=True)
        str_len = builder.load(len_ptr)

        # Check for empty string
        is_empty = builder.icmp_signed("==", str_len, ir.Constant(i64, 0))
        not_empty = func.append_basic_block("not_empty")
        return_null = func.append_basic_block("return_null")
        builder.cbranch(is_empty, return_null, not_empty)

        # Return null for empty/invalid
        builder.position_at_end(return_null)
        null_json = builder.call(cg.json_new_null, [])
        builder.ret(null_json)

        # Parse the string
        builder.position_at_end(not_empty)
        # Get first character
        first_char = builder.load(data_ptr)

        # Dispatch based on first character
        parse_null = func.append_basic_block("parse_null")
        parse_true = func.append_basic_block("parse_true")
        parse_false = func.append_basic_block("parse_false")
        parse_number = func.append_basic_block("parse_number")
        parse_string = func.append_basic_block("parse_string")
        parse_array = func.append_basic_block("parse_array")
        parse_object = func.append_basic_block("parse_object")

        # Check for specific start characters
        is_n = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('n')))
        is_t = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('t')))
        is_f = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('f')))
        is_quote = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('"')))
        is_bracket = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('[')))
        is_brace = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('{')))
        is_minus = builder.icmp_unsigned("==", first_char, ir.Constant(i8, ord('-')))
        is_digit = builder.and_(
            builder.icmp_unsigned(">=", first_char, ir.Constant(i8, ord('0'))),
            builder.icmp_unsigned("<=", first_char, ir.Constant(i8, ord('9')))
        )
        is_number = builder.or_(is_minus, is_digit)

        # Chain of checks
        check_t = func.append_basic_block("check_t")
        check_f = func.append_basic_block("check_f")
        check_quote = func.append_basic_block("check_quote")
        check_bracket = func.append_basic_block("check_bracket")
        check_brace = func.append_basic_block("check_brace")
        check_number = func.append_basic_block("check_number")

        builder.cbranch(is_n, parse_null, check_t)

        builder.position_at_end(check_t)
        builder.cbranch(is_t, parse_true, check_f)

        builder.position_at_end(check_f)
        builder.cbranch(is_f, parse_false, check_quote)

        builder.position_at_end(check_quote)
        builder.cbranch(is_quote, parse_string, check_bracket)

        builder.position_at_end(check_bracket)
        builder.cbranch(is_bracket, parse_array, check_brace)

        builder.position_at_end(check_brace)
        builder.cbranch(is_brace, parse_object, check_number)

        builder.position_at_end(check_number)
        builder.cbranch(is_number, parse_number, return_null)

        # Parse "null"
        builder.position_at_end(parse_null)
        null_result = builder.call(cg.json_new_null, [])
        builder.ret(null_result)

        # Parse "true"
        builder.position_at_end(parse_true)
        true_result = builder.call(cg.json_new_bool, [ir.Constant(ir.IntType(1), 1)])
        builder.ret(true_result)

        # Parse "false"
        builder.position_at_end(parse_false)
        false_result = builder.call(cg.json_new_bool, [ir.Constant(ir.IntType(1), 0)])
        builder.ret(false_result)

        # Parse number (simple: use string_to_int or string_to_float)
        builder.position_at_end(parse_number)
        # Try to parse as int first - string_to_int returns {i1, i64}
        parse_result = builder.call(cg.string_to_int, [str_ptr])
        int_val = builder.extract_value(parse_result, 1)  # Extract the i64 value
        int_result = builder.call(cg.json_new_int, [int_val])
        builder.ret(int_result)

        # Parse string (remove quotes)
        builder.position_at_end(parse_string)
        # For now, just wrap the string as-is (should remove quotes properly)
        str_json = builder.call(cg.json_new_string, [str_ptr])
        builder.ret(str_json)

        # Parse array/object using cJSON - both cases need to:
        # 1. Create null-terminated C string from Coex string
        # 2. Call cJSON_Parse
        # 3. Convert cJSON tree to Coex Json
        # 4. Free cJSON tree with cJSON_Delete

        # Parse array
        builder.position_at_end(parse_array)

        # Get string size (byte count) from field 3
        i32 = ir.IntType(32)
        size_ptr = builder.gep(str_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        byte_size = builder.load(size_ptr)

        # Allocate size+1 bytes for C string with null terminator
        alloc_size = builder.add(byte_size, ir.Constant(i64, 1))
        type_id = ir.Constant(i32, cg.gc.TYPE_STRING_DATA)
        cstr_buf = cg.gc.alloc_arena_or_gc(builder, alloc_size, type_id)

        # Copy string data to buffer
        builder.call(cg.memcpy, [cstr_buf, data_ptr, byte_size])

        # Add null terminator
        null_pos = builder.gep(cstr_buf, [byte_size])
        builder.store(ir.Constant(i8, 0), null_pos)

        # Call cJSON_Parse
        cjson_result = builder.call(self.cJSON_Parse, [cstr_buf])

        # Check for null (parse error)
        cjson_ptr_type = self.cjson_struct.as_pointer()
        null_cjson = ir.Constant(cjson_ptr_type, None)
        is_cjson_null = builder.icmp_unsigned("==", cjson_result, null_cjson)

        array_parse_ok = func.append_basic_block("array_parse_ok")
        builder.cbranch(is_cjson_null, return_null, array_parse_ok)

        builder.position_at_end(array_parse_ok)
        # Convert cJSON tree to Coex Json
        array_result = builder.call(self.json_from_cjson, [cjson_result])
        # Free cJSON tree
        builder.call(self.cJSON_Delete, [cjson_result])
        builder.ret(array_result)

        # Parse object - same approach as array
        builder.position_at_end(parse_object)

        # Get string size (byte count) from field 3
        obj_size_ptr = builder.gep(str_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 3)], inbounds=True)
        obj_byte_size = builder.load(obj_size_ptr)

        # Allocate size+1 bytes for C string with null terminator
        obj_alloc_size = builder.add(obj_byte_size, ir.Constant(i64, 1))
        obj_cstr_buf = cg.gc.alloc_arena_or_gc(builder, obj_alloc_size, type_id)

        # Copy string data to buffer
        builder.call(cg.memcpy, [obj_cstr_buf, data_ptr, obj_byte_size])

        # Add null terminator
        obj_null_pos = builder.gep(obj_cstr_buf, [obj_byte_size])
        builder.store(ir.Constant(i8, 0), obj_null_pos)

        # Call cJSON_Parse
        obj_cjson_result = builder.call(self.cJSON_Parse, [obj_cstr_buf])

        # Check for null (parse error)
        is_obj_cjson_null = builder.icmp_unsigned("==", obj_cjson_result, null_cjson)

        object_parse_ok = func.append_basic_block("object_parse_ok")
        builder.cbranch(is_obj_cjson_null, return_null, object_parse_ok)

        builder.position_at_end(object_parse_ok)
        # Convert cJSON tree to Coex Json
        object_result = builder.call(self.json_from_cjson, [obj_cjson_result])
        # Free cJSON tree
        builder.call(self.cJSON_Delete, [obj_cjson_result])
        builder.ret(object_result)

    def _implement_json_parse_stub(self):
        """Implement stub json_parse when cJSON is not available.

        Without cJSON, json.parse always returns null JSON. This allows
        programs to compile and run, but JSON parsing will be non-functional.
        Full JSON parsing requires the cJSON library to be available.
        """
        cg = self.cg
        func = cg.json_parse
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Simply return null JSON for all inputs when cJSON is unavailable
        null_json = builder.call(cg.json_new_null, [])
        builder.ret(null_json)

    def _register_json_methods(self):
        """Register JSON as a type with methods."""
        cg = self.cg
        cg.type_registry["Json"] = cg.json_struct
        cg.type_fields["Json"] = []  # Internal structure, not user-accessible

        cg.type_methods["Json"] = {
            # Type checking
            "is_null": "coex_json_is_null",
            "is_bool": "coex_json_is_bool",
            "is_int": "coex_json_is_int",
            "is_float": "coex_json_is_float",
            "is_string": "coex_json_is_string",
            "is_array": "coex_json_is_array",
            "is_object": "coex_json_is_object",
            # Value accessors
            "as_int": "coex_json_as_int",
            "as_float": "coex_json_as_float",
            "as_bool": "coex_json_as_bool",
            "as_string": "coex_json_as_string",
            # Access
            "get": "coex_json_get_field",
            "len": "coex_json_len",
            "has": "coex_json_has",
            # Mutation (returns new json)
            "set": "coex_json_set_field",
            "append": "coex_json_append",
            "remove": "coex_json_remove",
            # Iteration
            "keys": "coex_json_keys",
            "values": "coex_json_values",
            # Serialization
            "stringify": "coex_json_stringify",
            "pretty": "coex_json_pretty",
        }

        # Constructor functions
        cg.functions["coex_json_new_null"] = cg.json_new_null
        cg.functions["coex_json_new_bool"] = cg.json_new_bool
        cg.functions["coex_json_new_int"] = cg.json_new_int
        cg.functions["coex_json_new_float"] = cg.json_new_float
        cg.functions["coex_json_new_string"] = cg.json_new_string
        cg.functions["coex_json_new_array"] = cg.json_new_array
        cg.functions["coex_json_new_object"] = cg.json_new_object
        cg.functions["coex_json_get_tag"] = cg.json_get_tag
        cg.functions["coex_json_get_field"] = cg.json_get_field
        cg.functions["coex_json_get_index"] = cg.json_get_index

        # Type checking functions
        cg.functions["coex_json_is_null"] = cg.json_is_null
        cg.functions["coex_json_is_bool"] = cg.json_is_bool
        cg.functions["coex_json_is_int"] = cg.json_is_int
        cg.functions["coex_json_is_float"] = cg.json_is_float
        cg.functions["coex_json_is_string"] = cg.json_is_string
        cg.functions["coex_json_is_array"] = cg.json_is_array
        cg.functions["coex_json_is_object"] = cg.json_is_object

        # Value accessor functions
        cg.functions["coex_json_as_int"] = cg.json_as_int
        cg.functions["coex_json_as_float"] = cg.json_as_float
        cg.functions["coex_json_as_bool"] = cg.json_as_bool
        cg.functions["coex_json_as_string"] = cg.json_as_string
        cg.functions["coex_json_to_string"] = cg.json_to_string

        # Access and mutation functions
        cg.functions["coex_json_len"] = cg.json_len
        cg.functions["coex_json_has"] = cg.json_has
        cg.functions["coex_json_set_field"] = cg.json_set_field
        cg.functions["coex_json_set_index"] = cg.json_set_index
        cg.functions["coex_json_append"] = cg.json_append
        cg.functions["coex_json_remove"] = cg.json_remove
        cg.functions["coex_json_keys"] = cg.json_keys
        cg.functions["coex_json_values"] = cg.json_values
        cg.functions["coex_json_pretty"] = cg.json_pretty
        cg.functions["coex_json_stringify"] = cg.json_stringify

    # =========================================================================
    # JSON Conversion Methods (code generation during expression evaluation)
    # =========================================================================

    def generate_json_object(self, expr: 'JsonObjectExpr') -> ir.Value:
        """Generate code for JSON object literal: {name: "Alice", age: 30}

        Creates a Map<String, Json> internally, then wraps it in a Json object.
        """
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        if not expr.entries:
            # Empty JSON object: create empty map, wrap in json_new_object
            flags = cg.MAP_FLAG_KEY_IS_PTR | cg.MAP_FLAG_VALUE_IS_PTR  # String keys, Json values
            empty_map = builder.call(cg.map_new, [ir.Constant(i64, flags)])
            return builder.call(cg.json_new_object, [empty_map])

        # Create map with string keys and json values
        flags = cg.MAP_FLAG_KEY_IS_PTR | cg.MAP_FLAG_VALUE_IS_PTR
        map_ptr = builder.call(cg.map_new, [ir.Constant(i64, flags)])

        # Add each entry
        for key_str, value_expr in expr.entries:
            # Generate the key as a string (it's already a literal string from parsing)
            key_string = cg._get_string_ptr(key_str)

            # Generate the value expression
            value = cg._generate_expression(value_expr)

            # Convert value to JSON if it isn't already
            json_value = self.convert_to_json(value, value_expr)

            # Cast json pointer to i64 for map storage
            json_i64 = builder.ptrtoint(json_value, i64)

            # Add to map using string-aware set
            map_ptr = builder.call(cg.map_set_string, [map_ptr, key_string, json_i64])

        # Wrap the map in a Json object
        return builder.call(cg.json_new_object, [map_ptr])

    def convert_to_json(self, value: ir.Value, expr: 'Expr') -> ir.Value:
        """Convert a value to a Json* pointer based on its type."""
        from ast_nodes import NilLiteral, Identifier
        cg = self.cg
        builder = cg.builder

        # Handle NilLiteral first - before type checks since nil generates i64(0)
        if isinstance(expr, NilLiteral):
            return builder.call(cg.json_new_null, [])

        # Handle function references -> annotation {"@coex:func": "name"}
        if isinstance(value, ir.Function):
            return self.convert_function_to_json_annotation(value, expr)

        # Check value type and call appropriate json_new_* constructor
        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                # Boolean
                return builder.call(cg.json_new_bool, [value])
            elif value.type.width == 64:
                # Integer
                return builder.call(cg.json_new_int, [value])
            else:
                # Extend to i64 for JSON
                extended = builder.zext(value, ir.IntType(64))
                return builder.call(cg.json_new_int, [extended])
        elif isinstance(value.type, ir.DoubleType):
            # Float
            return builder.call(cg.json_new_float, [value])
        elif isinstance(value.type, ir.PointerType):
            # Check for function pointers
            if isinstance(value.type.pointee, ir.FunctionType):
                return self.convert_function_to_json_annotation(value, expr)
            if hasattr(value.type.pointee, 'name'):
                struct_name = value.type.pointee.name
                if struct_name == "struct.String":
                    # String
                    return builder.call(cg.json_new_string, [value])
                elif struct_name == "struct.Json":
                    # Already JSON, return as-is
                    return value
                elif struct_name == "struct.List":
                    # List -> JSON array (need to convert elements to JSON)
                    return self.convert_list_to_json_array(value, expr)
                elif struct_name == "struct.Map":
                    # Map -> JSON object
                    return builder.call(cg.json_new_object, [value])
                elif struct_name == "struct.Set":
                    # Set -> JSON annotation {"@coex:set": [elements...]}
                    return self.convert_set_to_json_annotation(value, expr)
                else:
                    # Check for user-defined types and enums
                    type_name = struct_name.replace("struct.", "") if struct_name.startswith("struct.") else struct_name
                    return self.convert_udt_to_json(value, type_name)

        # Default: treat as int (may need extension for other types)
        if isinstance(value.type, ir.IntType):
            extended = builder.zext(value, ir.IntType(64)) if value.type.width < 64 else value
            return builder.call(cg.json_new_int, [extended])

        # Fallback: create null JSON
        return builder.call(cg.json_new_null, [])

    def convert_list_to_json_array(self, list_ptr: ir.Value, expr: 'Expr' = None) -> ir.Value:
        """Convert a Coex list to a JSON array by converting each element to JSON.

        If expr is a ListExpr, we can iterate through elements at compile time,
        which is both more efficient and allows proper type-based conversion.

        Otherwise, we use type inference to determine the element type and generate
        a runtime loop with the correct conversion.
        """
        from ast_nodes import ListExpr, PrimitiveType, ListType, NamedType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # If we have a ListExpr, handle it at compile time - much cleaner and safer
        if isinstance(expr, ListExpr):
            return self._convert_list_expr_to_json_array(expr)

        # For non-literal lists, use type inference to determine element type
        elem_type = None
        if expr is not None:
            inferred = cg._infer_type_from_expr(expr)
            if isinstance(inferred, ListType):
                elem_type = inferred.element_type

        # Generate runtime loop with type-appropriate conversion
        return self._convert_list_runtime_to_json_array(list_ptr, elem_type)

    def _convert_list_expr_to_json_array(self, expr: 'ListExpr') -> ir.Value:
        """Convert a ListExpr to JSON array at compile time.

        This iterates through the AST elements and generates JSON conversion
        for each, avoiding any runtime type guessing.
        """
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Create list for JSON elements with TaggedValue size (16 bytes)
        json_list = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])

        # Convert each element at compile time
        for elem_expr in expr.elements:
            # Generate the element value
            elem_value = cg._generate_expression(elem_expr)

            # Convert to JSON using the expression for proper type handling
            json_elem = self.convert_to_json(elem_value, elem_expr)

            # Create TaggedValue with JSON handle
            json_elem_i8 = builder.bitcast(json_elem, i8_ptr)
            json_handle = builder.call(cg.gc.gc_ptr_to_handle, [json_elem_i8])
            tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, json_handle)
            tv_i8 = builder.bitcast(tv_ptr, i8_ptr)
            json_list = builder.call(cg.list_append, [json_list, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])

        return builder.call(cg.json_new_array, [json_list])

    def _convert_list_runtime_to_json_array(self, list_ptr: ir.Value, elem_type: 'Type' = None) -> ir.Value:
        """Convert an existing list to JSON array at runtime.

        Uses elem_type to determine the correct conversion for each element.
        If elem_type is None, defaults to treating elements as integers.
        """
        from ast_nodes import PrimitiveType, NamedType, ListType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get source list length
        src_len = builder.call(cg.list_len, [list_ptr])

        # Create list for JSON elements with TaggedValue size (16 bytes)
        json_list = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])

        # Store pointers for loop
        json_list_ptr = builder.alloca(cg.list_struct.as_pointer(), name="json_list_ptr")
        builder.store(json_list, json_list_ptr)
        idx_ptr = builder.alloca(i64, name="conv_idx")
        builder.store(ir.Constant(i64, 0), idx_ptr)

        # Allocate temp storage for handles outside loop
        temp_handle_ptr = builder.alloca(i64, name="temp_json_handle")

        # Create loop blocks
        func = builder.function
        loop_cond = func.append_basic_block("list_conv_cond")
        loop_body = func.append_basic_block("list_conv_body")
        loop_done = func.append_basic_block("list_conv_done")

        builder.branch(loop_cond)

        # Loop condition
        builder.position_at_end(loop_cond)
        idx = builder.load(idx_ptr)
        cmp = builder.icmp_signed("<", idx, src_len)
        builder.cbranch(cmp, loop_body, loop_done)

        # Loop body: get element, convert to JSON based on known type, append
        builder.position_at_end(loop_body)
        elem_data_ptr = builder.call(cg.list_get, [list_ptr, idx])

        # Convert element based on known element type
        json_elem = self._convert_list_element_to_json(elem_data_ptr, elem_type)

        # Store as handle in TaggedValue (gc_ptr_to_handle returns the object's handle)
        json_elem_i8 = builder.bitcast(json_elem, ir.IntType(8).as_pointer())
        json_handle = builder.call(cg.gc.gc_ptr_to_handle, [json_elem_i8])
        # Create TaggedValue with TV_TYPE_JSON_ARRAY (71) for JSON elements
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, json_handle)
        tv_i8 = builder.bitcast(tv_ptr, i8_ptr)

        curr_list = builder.load(json_list_ptr)
        new_list = builder.call(cg.list_append, [curr_list, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])
        builder.store(new_list, json_list_ptr)

        # Increment and loop
        next_idx = builder.add(idx, ir.Constant(i64, 1))
        builder.store(next_idx, idx_ptr)
        builder.branch(loop_cond)

        # Done: create JSON array from the converted list
        builder.position_at_end(loop_done)
        final_list = builder.load(json_list_ptr)
        return builder.call(cg.json_new_array, [final_list])

    def _convert_list_element_to_json(self, elem_data_ptr: ir.Value, elem_type: 'Type') -> ir.Value:
        """Convert a list element to JSON based on its known type."""
        from ast_nodes import PrimitiveType, NamedType, ListType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Extract value from TaggedValue {i64 type_id, i64 value}
        tv_ptr = builder.bitcast(elem_data_ptr, cg.gc.tagged_value_ptr_type)
        _, elem_i64 = cg.gc.extract_tagged_value(builder, tv_ptr)

        # Convert based on type
        if elem_type is None:
            # Default: treat as integer
            return builder.call(cg.json_new_int, [elem_i64])

        if isinstance(elem_type, PrimitiveType):
            if elem_type.name == "int":
                return builder.call(cg.json_new_int, [elem_i64])
            elif elem_type.name == "float":
                # Reinterpret i64 bits as double
                elem_double = builder.bitcast(elem_i64, ir.DoubleType())
                return builder.call(cg.json_new_float, [elem_double])
            elif elem_type.name == "bool":
                elem_bool = builder.trunc(elem_i64, ir.IntType(1))
                return builder.call(cg.json_new_bool, [elem_bool])
            elif elem_type.name == "string":
                elem_str = builder.inttoptr(elem_i64, cg.string_struct.as_pointer())
                return builder.call(cg.json_new_string, [elem_str])
            elif elem_type.name == "json":
                # Already JSON
                return builder.inttoptr(elem_i64, cg.json_struct.as_pointer())

        if isinstance(elem_type, NamedType):
            if elem_type.name == "Json":
                return builder.inttoptr(elem_i64, cg.json_struct.as_pointer())
            elif elem_type.name == "String":
                elem_str = builder.inttoptr(elem_i64, cg.string_struct.as_pointer())
                return builder.call(cg.json_new_string, [elem_str])
            # For other named types (user-defined), convert to JSON
            elem_ptr = builder.inttoptr(elem_i64, ir.IntType(8).as_pointer())
            return self.convert_udt_to_json(elem_ptr, elem_type.name)

        if isinstance(elem_type, ListType):
            # Nested list - recursively convert
            elem_list = builder.inttoptr(elem_i64, cg.list_struct.as_pointer())
            return self.convert_list_to_json_array(elem_list, None)

        # Default fallback: treat as integer
        return builder.call(cg.json_new_int, [elem_i64])

    def convert_udt_to_json(self, value: ir.Value, type_name: str) -> ir.Value:
        """Convert a user-defined type or enum to JSON with _type metadata."""
        cg = self.cg

        # Check if it's an enum
        if type_name in cg.enum_variants:
            return self.convert_enum_to_json(value, type_name)

        # Check if it's a user-defined struct
        if type_name in cg.type_fields:
            return self.convert_struct_to_json(value, type_name)

        # Unknown type - return null JSON
        return cg.builder.call(cg.json_new_null, [])

    def convert_function_to_json_annotation(self, value: ir.Value, expr: 'Expr' = None) -> ir.Value:
        """Convert a function reference to JSON annotation: {"@coex:func": "name"}.

        Functions are not JSON-serializable, so we create an annotation object
        that records the function name for debugging/inspection purposes.
        """
        from ast_nodes import Identifier
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Try to get function name
        func_name = "anonymous"
        if isinstance(value, ir.Function):
            # Direct function reference - get name from IR
            func_name = value.name
        elif isinstance(expr, Identifier):
            # Get name from expression
            func_name = expr.name

        # Create annotation object: {"@coex:func": "func_name"}
        flags = ir.Constant(i64, 0x01)  # String keys
        map_ptr = builder.call(cg.map_new, [flags])

        # Add @coex:func key with the function name string
        key_str = cg._get_string_ptr("@coex:func")
        name_str = cg._get_string_ptr(func_name)
        name_json = builder.call(cg.json_new_string, [name_str])
        name_json_i64 = builder.ptrtoint(name_json, i64)
        map_ptr = builder.call(cg.map_set_string, [map_ptr, key_str, name_json_i64])

        # Wrap map in JSON object
        return builder.call(cg.json_new_object, [map_ptr])

    def convert_set_to_json_annotation(self, set_ptr: ir.Value, expr: 'Expr' = None) -> ir.Value:
        """Convert a Set to JSON annotation: {"@coex:set": [elements...]}.

        Sets are not directly JSON-compatible, so we serialize them as an
        annotation object that preserves the elements as an array.
        """
        from ast_nodes import SetType, PrimitiveType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        func = builder.function

        # Infer element type from expression if available
        elem_type = None
        if expr is not None:
            inferred = cg._infer_type_from_expr(expr)
            if isinstance(inferred, SetType):
                elem_type = inferred.element_type

        # Convert set to list for iteration
        elems_list = builder.call(cg.set_to_list, [set_ptr])
        list_len = builder.call(cg.list_len, [elems_list])

        # Create JSON array for elements (TaggedValue size with ref flag)
        json_list = builder.call(cg.list_new, [ir.Constant(i64, cg.TAGGED_VALUE_SIZE), ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF)])

        # Loop to convert each element
        index_var = builder.alloca(i64, name="set_conv_idx")
        builder.store(ir.Constant(i64, 0), index_var)

        # Create blocks for loop
        cond_block = func.append_basic_block("set_conv_cond")
        body_block = func.append_basic_block("set_conv_body")
        exit_block = func.append_basic_block("set_conv_exit")

        # Store json_list in an alloca for updating in loop
        json_list_var = builder.alloca(cg.list_struct.as_pointer(), name="json_list_var")
        builder.store(json_list, json_list_var)

        builder.branch(cond_block)

        # Condition
        builder.position_at_end(cond_block)
        current_idx = builder.load(index_var)
        cond = builder.icmp_signed("<", current_idx, list_len)
        builder.cbranch(cond, body_block, exit_block)

        # Body
        builder.position_at_end(body_block)
        current_idx = builder.load(index_var)

        # Get element from list - extract from TaggedValue
        elem_ptr = builder.call(cg.list_get, [elems_list, current_idx])
        tv_ptr = builder.bitcast(elem_ptr, cg.gc.tagged_value_ptr_type)
        _, elem_val = cg.gc.extract_tagged_value(builder, tv_ptr)

        # Convert element to JSON based on inferred type
        if elem_type is not None and isinstance(elem_type, PrimitiveType):
            if elem_type.name == "int":
                json_elem = builder.call(cg.json_new_int, [elem_val])
            elif elem_type.name == "float":
                float_val = builder.bitcast(elem_val, ir.DoubleType())
                json_elem = builder.call(cg.json_new_float, [float_val])
            elif elem_type.name == "bool":
                bool_val = builder.trunc(elem_val, ir.IntType(1))
                json_elem = builder.call(cg.json_new_bool, [bool_val])
            elif elem_type.name == "string":
                str_ptr = builder.inttoptr(elem_val, cg.string_struct.as_pointer())
                json_elem = builder.call(cg.json_new_string, [str_ptr])
            else:
                json_elem = builder.call(cg.json_new_int, [elem_val])
        else:
            # Default: treat as int
            json_elem = builder.call(cg.json_new_int, [elem_val])

        # Append to json_list with TaggedValue
        json_list_current = builder.load(json_list_var)
        json_elem_i8 = builder.bitcast(json_elem, i8_ptr)
        json_handle = builder.call(cg.gc.gc_ptr_to_handle, [json_elem_i8])
        tv_ptr = cg.gc.create_tagged_value(builder, cg.gc.TV_TYPE_JSON_ARRAY, json_handle)
        tv_i8 = builder.bitcast(tv_ptr, i8_ptr)
        json_list_new = builder.call(cg.list_append, [json_list_current, tv_i8, ir.Constant(i64, cg.TAGGED_VALUE_SIZE)])
        builder.store(json_list_new, json_list_var)

        # Increment index
        next_idx = builder.add(current_idx, ir.Constant(i64, 1))
        builder.store(next_idx, index_var)
        builder.branch(cond_block)

        # Exit
        builder.position_at_end(exit_block)
        final_json_list = builder.load(json_list_var)

        # Create JSON array from the list
        json_array = builder.call(cg.json_new_array, [final_json_list])

        # Create annotation object: {"@coex:set": json_array}
        flags = ir.Constant(i64, 0x01)  # String keys
        map_ptr = builder.call(cg.map_new, [flags])

        # Add @coex:set key with the array value
        key_str = cg._get_string_ptr("@coex:set")
        json_array_i64 = builder.ptrtoint(json_array, i64)
        map_ptr = builder.call(cg.map_set_string, [map_ptr, key_str, json_array_i64])

        # Wrap map in JSON object
        return builder.call(cg.json_new_object, [map_ptr])

    def convert_struct_to_json(self, value: ir.Value, type_name: str) -> ir.Value:
        """Convert a user-defined struct to JSON object with _type field."""
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Create empty JSON object (starts with empty map)
        flags = ir.Constant(i64, 0x01)  # String keys
        map_ptr = builder.call(cg.map_new, [flags])

        # Add _type field
        type_str = cg._get_string_ptr(type_name)
        type_json = builder.call(cg.json_new_string, [type_str])
        type_json_i64 = builder.ptrtoint(type_json, i64)
        type_key = cg._get_string_ptr("_type")
        map_ptr = builder.call(cg.map_set_string, [map_ptr, type_key, type_json_i64])

        # Add each field
        field_info = cg.type_fields[type_name]
        for idx, (field_name, field_type) in enumerate(field_info):
            # Extract field value
            field_ptr = builder.gep(value, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), idx)], inbounds=True)
            field_val = builder.load(field_ptr)

            # Convert field value to JSON
            field_json = self.convert_field_to_json(field_val, field_type)

            # Add to map
            field_json_i64 = builder.ptrtoint(field_json, i64)
            field_key = cg._get_string_ptr(field_name)
            map_ptr = builder.call(cg.map_set_string, [map_ptr, field_key, field_json_i64])

        # Wrap map in JSON object
        return builder.call(cg.json_new_object, [map_ptr])

    def convert_enum_to_json(self, value: ir.Value, enum_name: str) -> ir.Value:
        """Convert an enum to JSON object with _type and _variant fields."""
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)
        func = builder.function

        # Get tag value (first field of enum struct)
        tag_ptr = builder.gep(value, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Create result alloca for PHI-like behavior
        result_ptr = builder.alloca(cg.json_struct.as_pointer(), name="enum_json")

        # Build switch for each variant
        variants = cg.enum_variants[enum_name]
        done_block = func.append_basic_block(f"enum_json_done")

        # Default block (shouldn't happen but needed for switch)
        default_block = func.append_basic_block(f"enum_json_default")

        # Create switch instruction
        switch = builder.switch(tag, default_block)

        for variant_name, (variant_tag, variant_fields) in variants.items():
            variant_block = func.append_basic_block(f"enum_json_{variant_name}")
            switch.add_case(ir.Constant(i64, variant_tag), variant_block)

            builder.position_at_end(variant_block)

            # Create JSON object for this variant
            flags = ir.Constant(i64, 0x01)  # String keys
            map_ptr = builder.call(cg.map_new, [flags])

            # Add _type field
            type_str = cg._get_string_ptr(enum_name)
            type_json = builder.call(cg.json_new_string, [type_str])
            type_json_i64 = builder.ptrtoint(type_json, i64)
            type_key = cg._get_string_ptr("_type")
            map_ptr = builder.call(cg.map_set_string, [map_ptr, type_key, type_json_i64])

            # Add _variant field
            variant_str = cg._get_string_ptr(variant_name)
            variant_json = builder.call(cg.json_new_string, [variant_str])
            variant_json_i64 = builder.ptrtoint(variant_json, i64)
            variant_key = cg._get_string_ptr("_variant")
            map_ptr = builder.call(cg.map_set_string, [map_ptr, variant_key, variant_json_i64])

            # Add variant data fields (start at index 1, after tag)
            for field_idx, (field_name, field_type) in enumerate(variant_fields):
                field_ptr = builder.gep(value, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_idx + 1)], inbounds=True)
                field_val = builder.load(field_ptr)

                # Convert field value to JSON
                field_json = self.convert_field_to_json(field_val, field_type)

                # Add to map
                field_json_i64 = builder.ptrtoint(field_json, i64)
                field_key = cg._get_string_ptr(field_name)
                map_ptr = builder.call(cg.map_set_string, [map_ptr, field_key, field_json_i64])

            # Wrap map in JSON object
            json_obj = builder.call(cg.json_new_object, [map_ptr])
            builder.store(json_obj, result_ptr)
            builder.branch(done_block)

        # Default block - create null JSON
        builder.position_at_end(default_block)
        null_json = builder.call(cg.json_new_null, [])
        builder.store(null_json, result_ptr)
        builder.branch(done_block)

        # Done block - load and return result
        builder.position_at_end(done_block)
        return builder.load(result_ptr)

    def convert_field_to_json(self, field_val: ir.Value, field_type: 'Type') -> ir.Value:
        """Convert a field value to JSON based on its Coex type."""
        from ast_nodes import PrimitiveType, ListType, MapType, NamedType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Handle primitives
        if isinstance(field_type, PrimitiveType):
            if field_type.name == "int":
                if isinstance(field_val.type, ir.IntType) and field_val.type.width < 64:
                    field_val = builder.zext(field_val, i64)
                return builder.call(cg.json_new_int, [field_val])
            elif field_type.name == "float":
                return builder.call(cg.json_new_float, [field_val])
            elif field_type.name == "bool":
                return builder.call(cg.json_new_bool, [field_val])
            elif field_type.name == "string":
                # field_val is i64 GC handle - dereference to get pointer
                # (strings are reference types stored as handles in UDT fields)
                if isinstance(field_val.type, ir.IntType):
                    ptr_i8 = builder.call(cg.gc.gc_handle_deref, [field_val])
                    str_ptr = builder.bitcast(ptr_i8, cg.string_struct.as_pointer())
                else:
                    str_ptr = field_val
                return builder.call(cg.json_new_string, [str_ptr])

        # Handle collections - stored as i64 GC handles in UDT fields
        if isinstance(field_type, ListType):
            if isinstance(field_val.type, ir.IntType):
                ptr_i8 = builder.call(cg.gc.gc_handle_deref, [field_val])
                list_ptr = builder.bitcast(ptr_i8, cg.list_struct.as_pointer())
            else:
                list_ptr = field_val
            return builder.call(cg.json_new_array, [list_ptr])

        if isinstance(field_type, MapType):
            if isinstance(field_val.type, ir.IntType):
                ptr_i8 = builder.call(cg.gc.gc_handle_deref, [field_val])
                map_ptr = builder.bitcast(ptr_i8, cg.map_struct.as_pointer())
            else:
                map_ptr = field_val
            return builder.call(cg.json_new_object, [map_ptr])

        # Handle user-defined types
        # Note: UDT fields are stored as i64 GC handles, not raw pointers (BUG-011 fix)
        if isinstance(field_type, NamedType):
            if field_type.name in cg.type_registry:
                # field_val is an i64 handle - dereference to get pointer
                if isinstance(field_val.type, ir.IntType):
                    ptr_i8 = builder.call(cg.gc.gc_handle_deref, [field_val])
                    udt_ptr = builder.bitcast(ptr_i8, cg.type_registry[field_type.name].as_pointer())
                else:
                    udt_ptr = field_val
                return self.convert_udt_to_json(udt_ptr, field_type.name)
            # Enum check - enums are also reference types stored as handles
            elif field_type.name in cg.enum_variants:
                if isinstance(field_val.type, ir.IntType):
                    # Get the enum struct type from the registry
                    enum_struct = cg.type_registry.get(field_type.name)
                    if enum_struct:
                        ptr_i8 = builder.call(cg.gc.gc_handle_deref, [field_val])
                        udt_ptr = builder.bitcast(ptr_i8, enum_struct.as_pointer())
                        return self.convert_enum_to_json(udt_ptr, field_type.name)
                return builder.call(cg.json_new_null, [])

        # Fallback - treat as int
        if isinstance(field_val.type, ir.IntType):
            if field_val.type.width < 64:
                field_val = builder.zext(field_val, i64)
            return builder.call(cg.json_new_int, [field_val])

        return builder.call(cg.json_new_null, [])

    def generate_as_expr(self, expr: 'AsExpr') -> ir.Value:
        """Generate code for type cast expression: expr as Type or expr as Type?"""
        from ast_nodes import PrimitiveType, NamedType, ListType, OptionalType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Generate the source expression
        source = cg._generate_expression(expr.expr)
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
            return self.generate_non_json_as_expr(source, expr)

        # JSON → Coex conversion
        # For first-class JSON variants, get type_id from header and value from offset 0
        type_id = self._get_json_type_id(builder, source)
        value_ptr = builder.bitcast(source, i64.as_pointer())
        value = builder.load(value_ptr)

        # Handle JSON → string: extract string if JSON is string type, else serialize
        if isinstance(inner_type, PrimitiveType) and inner_type.name == "string":
            # Check if JSON is a string type - if so, extract; otherwise serialize
            is_str_type = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_STRING))

            func = builder.function
            extract_block = func.append_basic_block("json_extract_str")
            serialize_block = func.append_basic_block("json_serialize_str")
            done_block = func.append_basic_block("json_str_done")

            builder.cbranch(is_str_type, extract_block, serialize_block)

            # Extract the string directly (value is a HANDLE, need to deref)
            builder.position_at_end(extract_block)
            str_i8 = builder.call(cg.gc.gc_handle_deref, [value])
            extracted = builder.bitcast(str_i8, cg.string_struct.as_pointer())
            builder.branch(done_block)

            # Serialize to JSON string
            builder.position_at_end(serialize_block)
            serialized = builder.call(cg.json_stringify, [source])
            builder.branch(done_block)

            # Merge results
            builder.position_at_end(done_block)
            result = builder.phi(cg.string_struct.as_pointer(), "str_result")
            result.add_incoming(extracted, extract_block)
            result.add_incoming(serialized, serialize_block)
            return result

        # Handle primitive target types (extraction)
        if isinstance(inner_type, PrimitiveType):
            return self.generate_json_to_primitive(source, type_id, value, inner_type, expr.is_optional)

        # Handle user-defined types
        if isinstance(inner_type, NamedType):
            if inner_type.name in cg.type_fields:
                return self.generate_json_to_struct(source, type_id, value, inner_type, expr.is_optional)
            if inner_type.name in cg.enum_variants:
                return self.generate_json_to_enum(source, type_id, value, inner_type, expr.is_optional)

        # Handle List type
        if isinstance(inner_type, ListType):
            return self.generate_json_to_list(source, type_id, value, inner_type, expr.is_optional)

        # Fallback - return 0/nil
        if expr.is_optional:
            return ir.Constant(i64, 0)
        return ir.Constant(i64, 0)

    def generate_non_json_as_expr(self, source: ir.Value, expr: 'AsExpr') -> ir.Value:
        """Handle non-JSON type conversions (e.g., int as string, string as json)."""
        from ast_nodes import PrimitiveType, OptionalType
        cg = self.cg
        builder = cg.builder
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
                return builder.call(cg.json_parse, [source])
            # Other types → json (implicit conversion)
            return self.convert_to_json(source, expr.expr)

        # For other conversions, just return the value (type checking should catch errors)
        return source

    def generate_json_to_primitive(self, json_ptr: ir.Value, type_id: ir.Value, value: ir.Value,
                                     target_type: 'PrimitiveType', is_optional: bool) -> ir.Value:
        """Convert JSON to a primitive type."""
        cg = self.cg
        builder = cg.builder
        i1 = ir.IntType(1)
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)
        func = builder.function

        # Determine expected type_id (first-class JSON variant types)
        if target_type.name == "bool":
            expected_type_id = cg.gc.TYPE_JSON_BOOL
            result_type = i1
        elif target_type.name == "int":
            expected_type_id = cg.gc.TYPE_JSON_INT
            result_type = i64
        elif target_type.name == "float":
            expected_type_id = cg.gc.TYPE_JSON_FLOAT
            result_type = ir.DoubleType()
        elif target_type.name == "string":
            expected_type_id = cg.gc.TYPE_JSON_STRING
            result_type = cg.string_struct.as_pointer()
        else:
            # Unknown primitive - return 0
            return ir.Constant(i64, 0)

        # Check type_id matches
        type_matches = builder.icmp_unsigned("==", type_id, ir.Constant(i64, expected_type_id))

        # Create blocks
        match_block = func.append_basic_block("as_match")
        fail_block = func.append_basic_block("as_fail")
        done_block = func.append_basic_block("as_done")

        # Allocate result
        if is_optional:
            # Optional returns i64 (0 for nil)
            result_ptr = builder.alloca(i64, name="as_result")
        else:
            result_ptr = builder.alloca(result_type, name="as_result")

        builder.cbranch(type_matches, match_block, fail_block)

        # Match block - extract value
        builder.position_at_end(match_block)
        if target_type.name == "bool":
            extracted = builder.trunc(value, i1)
            if is_optional:
                # Store as i64 for optional (1 = Some(false), 2 = Some(true))
                extended = builder.zext(extracted, i64)
                # Add 1 so 0 can mean None
                result = builder.add(extended, ir.Constant(i64, 1))
                builder.store(result, result_ptr)
            else:
                builder.store(extracted, result_ptr)
        elif target_type.name == "int":
            if is_optional:
                # For optional int, we need a sentinel. Use a tagged representation.
                # Store value + 1, with 0 meaning None
                # This limits range but works for most cases
                result = builder.add(value, ir.Constant(i64, 1))
                builder.store(result, result_ptr)
            else:
                builder.store(value, result_ptr)
        elif target_type.name == "float":
            # value is i64 - bitcast to double
            extracted = builder.bitcast(value, ir.DoubleType())
            if is_optional:
                # Store as i64
                builder.store(value, result_ptr)
            else:
                builder.store(extracted, result_ptr)
        elif target_type.name == "string":
            # value is a HANDLE - need to dereference it
            str_i8 = builder.call(cg.gc.gc_handle_deref, [value])
            str_ptr = builder.bitcast(str_i8, cg.string_struct.as_pointer())
            if is_optional:
                builder.store(value, result_ptr)
            else:
                # Store the actual String* pointer
                builder.store(str_ptr, result_ptr)
        builder.branch(done_block)

        # Fail block
        builder.position_at_end(fail_block)
        if is_optional:
            builder.store(ir.Constant(i64, 0), result_ptr)
            builder.branch(done_block)
        else:
            # Panic - type mismatch
            # For now, just store 0 and continue
            if result_type == i1:
                builder.store(ir.Constant(i1, 0), result_ptr)
            elif result_type == i64:
                builder.store(ir.Constant(i64, 0), result_ptr)
            elif isinstance(result_type, ir.DoubleType):
                builder.store(ir.Constant(ir.DoubleType(), 0.0), result_ptr)
            else:
                # Pointer type
                null_ptr = builder.inttoptr(ir.Constant(i64, 0), result_type)
                builder.store(null_ptr, result_ptr)
            builder.branch(done_block)

        # Done block
        builder.position_at_end(done_block)
        return builder.load(result_ptr)

    def generate_json_to_struct(self, json_ptr: ir.Value, type_id: ir.Value, value: ir.Value,
                                  target_type: 'NamedType', is_optional: bool) -> ir.Value:
        """Convert JSON object to user-defined struct."""
        cg = self.cg
        builder = cg.builder
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)
        func = builder.function
        type_name = target_type.name

        # Check it's an object (type_id == TYPE_JSON_OBJECT)
        is_object = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_OBJECT))

        match_block = func.append_basic_block("as_struct_match")
        fail_block = func.append_basic_block("as_struct_fail")
        done_block = func.append_basic_block("as_struct_done")

        struct_type = cg.type_registry[type_name]
        result_ptr = builder.alloca(struct_type.as_pointer(), name="as_struct_result")

        builder.cbranch(is_object, match_block, fail_block)

        # Match block - extract fields
        builder.position_at_end(match_block)

        # Get the map from the JSON object - value is a HANDLE, need to dereference
        map_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        map_ptr = builder.bitcast(map_i8, cg.map_struct.as_pointer())

        # Allocate struct via GC
        struct_size = ir.Constant(i64, len(cg.type_fields[type_name]) * 8)
        type_id = ir.Constant(ir.IntType(32), cg.gc.get_type_id(type_name))  # GC uses i32 for type_id
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, struct_size, type_id)
        struct_ptr = builder.bitcast(raw_ptr, struct_type.as_pointer())

        # Extract each field
        field_info = cg.type_fields[type_name]
        for idx, (field_name, field_type) in enumerate(field_info):
            # Skip _type field
            if field_name == "_type":
                continue

            # Get field from map
            field_key = cg._get_string_ptr(field_name)
            field_json_i64 = builder.call(cg.map_get_string, [map_ptr, field_key])

            # Convert from JSON
            field_json = builder.inttoptr(field_json_i64, cg.json_struct.as_pointer())
            field_val = self.extract_json_value(field_json, field_type)

            # Store in struct
            field_ptr = builder.gep(struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), idx)], inbounds=True)
            builder.store(field_val, field_ptr)

        if is_optional:
            struct_i64 = builder.ptrtoint(struct_ptr, i64)
            builder.store(builder.inttoptr(struct_i64, struct_type.as_pointer()), result_ptr)
        else:
            builder.store(struct_ptr, result_ptr)
        builder.branch(done_block)

        # Fail block
        builder.position_at_end(fail_block)
        null_ptr = builder.inttoptr(ir.Constant(i64, 0), struct_type.as_pointer())
        builder.store(null_ptr, result_ptr)
        builder.branch(done_block)

        # Done block
        builder.position_at_end(done_block)
        return builder.load(result_ptr)

    def generate_json_to_enum(self, json_ptr: ir.Value, type_id: ir.Value, value: ir.Value,
                                target_type: 'NamedType', is_optional: bool) -> ir.Value:
        """Convert JSON object to enum."""
        # Similar to struct but also checks _variant field
        i64 = ir.IntType(64)

        # For now, return a simple placeholder
        # Full enum conversion requires matching variant names
        if is_optional:
            return ir.Constant(i64, 0)
        return ir.Constant(i64, 0)

    def generate_json_to_list(self, json_ptr: ir.Value, type_id: ir.Value, value: ir.Value,
                                target_type: 'ListType', is_optional: bool) -> ir.Value:
        """Convert JSON array to List."""
        cg = self.cg
        builder = cg.builder
        i8 = ir.IntType(8)
        i64 = ir.IntType(64)
        func = builder.function

        # Check it's an array (type_id == TYPE_JSON_ARRAY)
        is_array = builder.icmp_unsigned("==", type_id, ir.Constant(i64, cg.gc.TYPE_JSON_ARRAY))

        match_block = func.append_basic_block("as_list_match")
        fail_block = func.append_basic_block("as_list_fail")
        done_block = func.append_basic_block("as_list_done")

        result_ptr = builder.alloca(cg.list_struct.as_pointer(), name="as_list_result")

        builder.cbranch(is_array, match_block, fail_block)

        # Match block - value is a HANDLE, need to dereference
        builder.position_at_end(match_block)
        list_i8 = builder.call(cg.gc.gc_handle_deref, [value])
        list_ptr = builder.bitcast(list_i8, cg.list_struct.as_pointer())
        builder.store(list_ptr, result_ptr)
        builder.branch(done_block)

        # Fail block
        builder.position_at_end(fail_block)
        null_ptr = builder.inttoptr(ir.Constant(i64, 0), cg.list_struct.as_pointer())
        builder.store(null_ptr, result_ptr)
        builder.branch(done_block)

        # Done block
        builder.position_at_end(done_block)
        return builder.load(result_ptr)

    def extract_json_value(self, json_ptr: ir.Value, target_type: 'Type') -> ir.Value:
        """Extract a value from a JSON pointer, converting to the target type."""
        from ast_nodes import PrimitiveType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Get value from offset 0 (first-class JSON variants store value directly)
        value_ptr = builder.bitcast(json_ptr, i64.as_pointer())
        value = builder.load(value_ptr)

        if isinstance(target_type, PrimitiveType):
            if target_type.name == "int":
                return value
            elif target_type.name == "float":
                return builder.bitcast(value, ir.DoubleType())
            elif target_type.name == "bool":
                return builder.trunc(value, ir.IntType(1))
            elif target_type.name == "string":
                # value is a HANDLE, need to dereference
                str_i8 = builder.call(cg.gc.gc_handle_deref, [value])
                return builder.bitcast(str_i8, cg.string_struct.as_pointer())

        # For complex types, return the raw value as i64
        return value

    def wrap_value_as_json(self, value: ir.Value, coex_type: 'Type') -> ir.Value:
        """Wrap a Coex value in a JSON container based on its type annotation.

        This is used by user-defined kind functions to pass parameter values
        as json elements to the handler.

        Args:
            value: The LLVM value to wrap
            coex_type: The Coex type annotation for the value

        Returns:
            A JSON handle (i64) containing the wrapped value
        """
        from ast_nodes import PrimitiveType, NamedType, ListType, AtomicType
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        # Handle primitive types
        if isinstance(coex_type, PrimitiveType):
            type_name = coex_type.name

            if type_name == "int":
                return builder.call(cg.json_new_int, [value])

            elif type_name in ("int32", "byte"):
                # Extend to i64
                extended = builder.zext(value, i64) if value.type.width < 64 else value
                return builder.call(cg.json_new_int, [extended])

            elif type_name == "float":
                return builder.call(cg.json_new_float, [value])

            elif type_name == "float32":
                # Extend to f64
                extended = builder.fpext(value, ir.DoubleType())
                return builder.call(cg.json_new_float, [extended])

            elif type_name == "bool":
                return builder.call(cg.json_new_bool, [value])

            elif type_name == "string":
                # value is a String* pointer (struct.String*)
                str_struct = value
                if not isinstance(value.type, ir.PointerType):
                    # If it's an i64 handle, dereference first
                    str_ptr = builder.call(cg.gc.gc_handle_deref, [value])
                    str_struct = builder.bitcast(str_ptr, cg.string_struct.as_pointer())
                return builder.call(cg.json_new_string, [str_struct])

            elif type_name == "json":
                # Already JSON
                return value

        # Handle atomic types - extract value
        if isinstance(coex_type, AtomicType):
            inner = coex_type.inner
            if inner == "int":
                return builder.call(cg.json_new_int, [value])
            elif inner == "float":
                return builder.call(cg.json_new_float, [value])
            elif inner == "bool":
                return builder.call(cg.json_new_bool, [value])

        # Handle named types (user-defined structs, enums)
        if isinstance(coex_type, NamedType):
            type_name = coex_type.name

            # Handle JSON type
            if type_name == "json":
                return value

            # Handle List type
            if type_name == "List" or (hasattr(coex_type, 'name') and coex_type.name.startswith("List<")):
                return self.convert_list_to_json_array(value)

            # For other user types, convert to JSON object
            if type_name in cg.type_registry:
                ptr_i8 = builder.call(cg.gc.gc_handle_deref, [value])
                struct_ptr = builder.bitcast(ptr_i8, cg.type_registry[type_name].as_pointer())
                return self.convert_udt_to_json(struct_ptr, type_name)

        # Handle list types
        if isinstance(coex_type, ListType):
            return self.convert_list_to_json_array(value)

        # Fallback: wrap as int
        if isinstance(value.type, ir.IntType):
            if value.type.width < 64:
                value = builder.zext(value, i64)
            return builder.call(cg.json_new_int, [value])

        # Last resort: null
        return builder.call(cg.json_new_null, [])

