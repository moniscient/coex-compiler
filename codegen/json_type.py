"""
Coex JSON Type Code Generator

Generates LLVM IR for the JSON type, providing a tagged union for representing
JSON values (null, bool, int, float, string, array, object).

JSON values are stored as:
- struct.Json { i8 tag, i64 value }
- Tags: 0=null, 1=bool, 2=int, 3=float, 4=string, 5=array, 6=object
- Values: primitives inline, pointers stored as i64
"""

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

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to main code generator."""
        self.cg = codegen



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

        struct.Json { i8 tag, i64 value }
        """
        cg = self.cg
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Define the JSON struct: { i8 tag, i64 value }
        cg.json_struct = ir.global_context.get_identified_type("struct.Json")
        cg.json_struct.set_body(
            i8,   # tag (field 0) - type discriminator
            i64,  # value (field 1) - inline value or pointer as i64
        )

        # Declare constructor functions
        json_ptr = cg.json_struct.as_pointer()

        # json_new_null() -> Json*
        cg.json_new_null = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, []),
            name="coex_json_new_null"
        )

        # json_new_bool(i1 value) -> Json*
        cg.json_new_bool = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [ir.IntType(1)]),
            name="coex_json_new_bool"
        )

        # json_new_int(i64 value) -> Json*
        cg.json_new_int = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [i64]),
            name="coex_json_new_int"
        )

        # json_new_float(f64 value) -> Json*
        cg.json_new_float = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [ir.DoubleType()]),
            name="coex_json_new_float"
        )

        # json_new_string(String* value) -> Json*
        cg.json_new_string = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.string_struct.as_pointer()]),
            name="coex_json_new_string"
        )

        # json_new_array(List* value) -> Json*
        cg.json_new_array = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.list_struct.as_pointer()]),
            name="coex_json_new_array"
        )

        # json_new_object(Map* value) -> Json*
        cg.json_new_object = ir.Function(
            cg.module,
            ir.FunctionType(json_ptr, [cg.map_struct.as_pointer()]),
            name="coex_json_new_object"
        )

        # json_get_tag(Json*) -> i8
        cg.json_get_tag = ir.Function(
            cg.module,
            ir.FunctionType(i8, [json_ptr]),
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
        self._implement_json_parse()

        # Implement string.validjson() now that json_parse exists
        cg._strings.implement_string_validjson()

        # Register JSON type and methods
        self._register_json_methods()

    def _implement_json_new_null(self):
        """Implement json_new_null(): allocate a Json with null value."""
        cg = self.cg
        func = cg.json_new_null
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct (9 bytes, but align to 16)
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_NULL (0)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_NULL), tag_ptr)

        # Set value to 0 (unused for null)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(ir.Constant(i64, 0), value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_bool(self):
        """Implement json_new_bool(i1): allocate a Json with bool value."""
        cg = self.cg
        func = cg.json_new_bool
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_BOOL (1)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_BOOL), tag_ptr)

        # Set value (extend i1 to i64)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.zext(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_int(self):
        """Implement json_new_int(i64): allocate a Json with int value."""
        cg = self.cg
        func = cg.json_new_int
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_INT (2)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_INT), tag_ptr)

        # Set value
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        builder.store(func.args[0], value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_float(self):
        """Implement json_new_float(f64): allocate a Json with float value."""
        cg = self.cg
        func = cg.json_new_float
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_FLOAT (3)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_FLOAT), tag_ptr)

        # Set value (bitcast f64 to i64)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.bitcast(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_string(self):
        """Implement json_new_string(String*): allocate a Json with string value."""
        cg = self.cg
        func = cg.json_new_string
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_STRING (4)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_STRING), tag_ptr)

        # Set value (store pointer as i64)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.ptrtoint(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_array(self):
        """Implement json_new_array(List*): allocate a Json with array value."""
        cg = self.cg
        func = cg.json_new_array
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_ARRAY (5)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_ARRAY), tag_ptr)

        # Set value (store pointer as i64)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.ptrtoint(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_new_object(self):
        """Implement json_new_object(Map*): allocate a Json with object value."""
        cg = self.cg
        func = cg.json_new_object
        func.args[0].name = "value"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Allocate Json struct
        json_size = ir.Constant(i64, 16)
        type_id = ir.Constant(i32, cg.gc.TYPE_JSON)
        raw_ptr = cg.gc.alloc_with_deref(builder, json_size, type_id)
        json_ptr = builder.bitcast(raw_ptr, cg.json_struct.as_pointer())

        # Set tag to JSON_TAG_OBJECT (6)
        tag_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        builder.store(ir.Constant(i8, self.JSON_TAG_OBJECT), tag_ptr)

        # Set value (store pointer as i64)
        value_ptr = builder.gep(json_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.ptrtoint(func.args[0], i64)
        builder.store(value_i64, value_ptr)

        builder.ret(json_ptr)

    def _implement_json_get_tag(self):
        """Implement json_get_tag(Json*): return the type tag."""
        cg = self.cg
        func = cg.json_get_tag
        func.args[0].name = "json"
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i32 = ir.IntType(32)

        # Get tag field
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        builder.ret(tag)

    def _implement_json_get_field(self):
        """Implement json_get_field(Json*, String*): get field from object, return null json if not found."""
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

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Is object: extract Map* and look up key
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())

        # Call map_get_string to get the value
        result = builder.call(cg.map_get_string, [map_ptr, func.args[1]])

        # Check if found (result != 0, since 0 indicates not found for map_get)
        # Actually, we need to handle this differently. map_get_string returns i64.
        # For JSON, we store Json* as i64. If not found, we return json null.
        # The issue is distinguishing "not found" from "found with value 0".
        # For now, we'll assume 0 means not found (since Json* is never null/0).
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
        """Implement json_get_index(Json*, i64): get element from array, return null json if out of bounds."""
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

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if array
        is_arr = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Is array: extract List* and get element
        builder.position_at_end(is_array)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        list_ptr = builder.inttoptr(value_i64, cg.list_struct.as_pointer())

        # Get list length
        len_ptr = builder.gep(list_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        list_len = builder.load(len_ptr)

        # Check bounds
        idx = func.args[1]
        in_range = builder.icmp_signed("<", idx, list_len)
        non_negative = builder.icmp_signed(">=", idx, ir.Constant(i64, 0))
        valid = builder.and_(in_range, non_negative)
        builder.cbranch(valid, in_bounds, out_of_bounds)

        # In bounds: get element
        builder.position_at_end(in_bounds)
        result = builder.call(cg.list_get, [list_ptr, idx])
        # Result is i8*, cast to json pointer (stored as i64 in list)
        result_i64 = builder.ptrtoint(result, i64)
        json_result = builder.inttoptr(result_i64, cg.json_struct.as_pointer())
        builder.ret(json_result)

        # Not array or out of bounds: return json null
        builder.position_at_end(not_array)
        null_json_1 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_1)

        builder.position_at_end(out_of_bounds)
        null_json_2 = builder.call(cg.json_new_null, [])
        builder.ret(null_json_2)

    def _implement_json_is_null(self):
        """Implement is_null(): check if json value is null."""
        cg = self.cg
        func = cg.json_is_null
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_NULL))
        builder.ret(result)

    def _implement_json_is_bool(self):
        """Implement is_bool(): check if json value is a boolean."""
        cg = self.cg
        func = cg.json_is_bool
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_BOOL))
        builder.ret(result)

    def _implement_json_is_int(self):
        """Implement is_int(): check if json value is an integer."""
        cg = self.cg
        func = cg.json_is_int
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_INT))
        builder.ret(result)

    def _implement_json_is_float(self):
        """Implement is_float(): check if json value is a float."""
        cg = self.cg
        func = cg.json_is_float
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_FLOAT))
        builder.ret(result)

    def _implement_json_is_string(self):
        """Implement is_string(): check if json value is a string."""
        cg = self.cg
        func = cg.json_is_string
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_STRING))
        builder.ret(result)

    def _implement_json_is_array(self):
        """Implement is_array(): check if json value is an array."""
        cg = self.cg
        func = cg.json_is_array
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_ARRAY))
        builder.ret(result)

    def _implement_json_is_object(self):
        """Implement is_object(): check if json value is an object."""
        cg = self.cg
        func = cg.json_is_object
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)
        result = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.ret(result)

    def _implement_json_len(self):
        """Implement len(): return length of array/object, 0 otherwise."""
        cg = self.cg
        func = cg.json_len
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        is_object = func.append_basic_block("is_object")
        not_collection = func.append_basic_block("not_collection")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if array
        is_arr = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_ARRAY))
        builder.cbranch(is_arr, is_array, is_object)

        # Array: get list length
        builder.position_at_end(is_array)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        list_ptr = builder.inttoptr(value_i64, cg.list_struct.as_pointer())
        arr_len = builder.call(cg.list_len, [list_ptr])
        builder.ret(arr_len)

        # Check if object
        builder.position_at_end(is_object)
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, func.append_basic_block("get_obj_len"), not_collection)

        # Object: get map length
        get_obj_len = list(func.basic_blocks)[-1]
        builder.position_at_end(get_obj_len)
        value_ptr2 = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64_2 = builder.load(value_ptr2)
        map_ptr = builder.inttoptr(value_i64_2, cg.map_struct.as_pointer())
        obj_len = builder.call(cg.map_len, [map_ptr])
        builder.ret(obj_len)

        # Not a collection: return 0
        builder.position_at_end(not_collection)
        builder.ret(ir.Constant(i64, 0))

    def _implement_json_has(self):
        """Implement has(key): check if object has a key."""
        cg = self.cg
        func = cg.json_has
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i1 = ir.IntType(1)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: check map.has_string(key)
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())
        has_result = builder.call(cg.map_has_string, [map_ptr, func.args[1]])
        builder.ret(has_result)

        # Not object: return false
        builder.position_at_end(not_object)
        builder.ret(ir.Constant(i1, 0))

    def _implement_json_set_field(self):
        """Implement set(key, value): return new json with field set."""
        cg = self.cg
        func = cg.json_set_field
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: create new map with key set
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())

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
        """Implement set(index, value): return new json with array element set."""
        cg = self.cg
        func = cg.json_set_index
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        not_array = func.append_basic_block("not_array")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if array
        is_arr = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Array: create new list with element set
        builder.position_at_end(is_array)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        list_ptr = builder.inttoptr(value_i64, cg.list_struct.as_pointer())

        # Convert json value to i8* for list storage
        json_val = func.args[2]
        json_as_i8ptr = builder.bitcast(json_val, ir.IntType(8).as_pointer())

        # Call list_set (elem_size = 8 for pointer)
        new_list = builder.call(cg.list_set, [list_ptr, func.args[1], json_as_i8ptr, ir.Constant(i64, 8)])

        # Create new json array with new list
        result = builder.call(cg.json_new_array, [new_list])
        builder.ret(result)

        # Not array: return the original json unchanged
        builder.position_at_end(not_array)
        builder.ret(func.args[0])

    def _implement_json_append(self):
        """Implement append(value): return new json with value appended to array."""
        cg = self.cg
        func = cg.json_append
        entry = func.append_basic_block("entry")
        is_array = func.append_basic_block("is_array")
        not_array = func.append_basic_block("not_array")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if array
        is_arr = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_ARRAY))
        builder.cbranch(is_arr, is_array, not_array)

        # Array: append value
        builder.position_at_end(is_array)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        list_ptr = builder.inttoptr(value_i64, cg.list_struct.as_pointer())

        # Convert json value to i8* for list storage
        json_val = func.args[1]
        json_as_i8ptr = builder.bitcast(json_val, ir.IntType(8).as_pointer())

        # Call list_append (elem_size = 8 for pointer)
        new_list = builder.call(cg.list_append, [list_ptr, json_as_i8ptr, ir.Constant(i64, 8)])

        # Create new json array with new list
        result = builder.call(cg.json_new_array, [new_list])
        builder.ret(result)

        # Not array: return the original json unchanged
        builder.position_at_end(not_array)
        builder.ret(func.args[0])

    def _implement_json_remove(self):
        """Implement remove(key): return new json with key removed from object."""
        cg = self.cg
        func = cg.json_remove
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: remove key
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())

        # Call map_remove_string (JSON objects use string keys)
        new_map = builder.call(cg.map_remove_string, [map_ptr, func.args[1]])

        # Create new json object with new map
        result = builder.call(cg.json_new_object, [new_map])
        builder.ret(result)

        # Not object: return the original json unchanged
        builder.position_at_end(not_object)
        builder.ret(func.args[0])

    def _implement_json_keys(self):
        """Implement keys(): return list of keys from object."""
        cg = self.cg
        func = cg.json_keys
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: get keys from map
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())

        # Call map_keys
        keys_list = builder.call(cg.map_keys, [map_ptr])
        builder.ret(keys_list)

        # Not object: return empty list
        builder.position_at_end(not_object)
        # Create empty list with string element flag
        flags = ir.Constant(i64, 0x02)  # FLAG_STRING_KEY for string elements
        empty_list = builder.call(cg.list_new, [flags])
        builder.ret(empty_list)

    def _implement_json_values(self):
        """Implement values(): return list of values from object."""
        cg = self.cg
        func = cg.json_values
        entry = func.append_basic_block("entry")
        is_object = func.append_basic_block("is_object")
        not_object = func.append_basic_block("not_object")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Check if object
        is_obj = builder.icmp_unsigned("==", tag, ir.Constant(i8, self.JSON_TAG_OBJECT))
        builder.cbranch(is_obj, is_object, not_object)

        # Object: get values from map
        builder.position_at_end(is_object)
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        value_i64 = builder.load(value_ptr)
        map_ptr = builder.inttoptr(value_i64, cg.map_struct.as_pointer())

        # Call map_values
        values_list = builder.call(cg.map_values, [map_ptr])
        builder.ret(values_list)

        # Not object: return empty list
        builder.position_at_end(not_object)
        # Create empty list
        flags = ir.Constant(i64, 0)
        empty_list = builder.call(cg.list_new, [flags])
        builder.ret(empty_list)

    def _implement_json_stringify(self):
        """Implement json_stringify(Json*) -> String*: serialize JSON to string."""
        cg = self.cg
        func = cg.json_stringify
        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get tag
        tag_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Get value
        value_ptr = builder.gep(func.args[0], [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
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

        # Switch on tag
        switch = builder.switch(tag, null_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_NULL), null_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_BOOL), bool_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_INT), int_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_FLOAT), float_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_STRING), string_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_ARRAY), array_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_OBJECT), object_block)

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

        # STRING: wrap in quotes
        builder.position_at_end(string_block)
        str_ptr = builder.inttoptr(value, cg.string_struct.as_pointer())
        # Build "\"" + str + "\""
        quote_str = self._get_or_create_global_string(builder, '"', "quote")
        temp = builder.call(cg.string_concat, [quote_str, str_ptr])
        quoted_str = builder.call(cg.string_concat, [temp, quote_str])
        builder.store(quoted_str, result_ptr)
        builder.branch(done_block)

        # ARRAY: serialize as [elem1, elem2, ...]
        builder.position_at_end(array_block)
        self._stringify_array(builder, func, value, result_ptr)
        builder.branch(done_block)

        # OBJECT: serialize as {key1: val1, ...}
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
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get list pointer
        list_ptr = builder.inttoptr(value, cg.list_struct.as_pointer())

        # Get list length
        list_len = builder.call(cg.list_len, [list_ptr])

        # Create a new list to hold stringified elements (8 bytes per String* pointer)
        string_list = builder.call(cg.list_new, [ir.Constant(i64, 8)])
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
        elem_i64_ptr = builder.bitcast(elem_data_ptr, i64.as_pointer())
        elem_i64 = builder.load(elem_i64_ptr)
        elem_json = builder.inttoptr(elem_i64, cg.json_struct.as_pointer())
        elem_str = builder.call(cg.json_stringify, [elem_json])

        # Append to string list (reuse pre-allocated temp_ptr)
        curr_list = builder.load(string_list_ptr)
        elem_str_i64 = builder.ptrtoint(elem_str, i64)
        builder.store(elem_str_i64, temp_ptr)
        temp_i8 = builder.bitcast(temp_ptr, ir.IntType(8).as_pointer())
        new_list = builder.call(cg.list_append, [curr_list, temp_i8, ir.Constant(i64, 8)])
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
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get map pointer
        map_ptr = builder.inttoptr(value, cg.map_struct.as_pointer())

        # Get keys list
        keys_list = builder.call(cg.map_keys, [map_ptr])
        list_len = builder.call(cg.list_len, [keys_list])

        # Create a new list to hold "key":value strings (8 bytes per String* pointer)
        string_list = builder.call(cg.list_new, [ir.Constant(i64, 8)])
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

        # Get key string (list_get returns i8* to stored i64, need to load and inttoptr)
        key_data_ptr = builder.call(cg.list_get, [keys_list, idx])
        key_i64_ptr = builder.bitcast(key_data_ptr, i64.as_pointer())
        key_i64 = builder.load(key_i64_ptr)
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
        builder.store(kv_str_i64, temp_ptr)
        temp_i8 = builder.bitcast(temp_ptr, ir.IntType(8).as_pointer())
        new_list = builder.call(cg.list_append, [curr_list, temp_i8, ir.Constant(i64, 8)])
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
        """
        cg = self.cg
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
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

        # Get tag
        tag_ptr = builder.gep(json_val, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        tag = builder.load(tag_ptr)

        # Get value
        value_ptr = builder.gep(json_val, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
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

        # Switch on tag
        switch = builder.switch(tag, null_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_NULL), null_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_BOOL), bool_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_INT), int_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_FLOAT), float_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_STRING), string_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_ARRAY), array_block)
        switch.add_case(ir.Constant(i8, self.JSON_TAG_OBJECT), object_block)

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

        # STRING: wrap in quotes
        builder.position_at_end(string_block)
        str_ptr = builder.inttoptr(value, cg.string_struct.as_pointer())
        quote_str = self._get_or_create_global_string(builder, '"', "pretty_quote")
        temp = builder.call(cg.string_concat, [quote_str, str_ptr])
        quoted_str = builder.call(cg.string_concat, [temp, quote_str])
        builder.store(quoted_str, result_ptr)
        builder.branch(done_block)

        # ARRAY: serialize with pretty printing
        builder.position_at_end(array_block)
        self._pretty_array(builder, func, value, indent_size, depth, result_ptr)
        builder.branch(done_block)

        # OBJECT: serialize with pretty printing
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
        """Generate code to pretty-print a JSON array."""
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get list pointer
        list_ptr = builder.inttoptr(value, cg.list_struct.as_pointer())

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

        # Get element and pretty-print it
        elem_data_ptr = builder.call(cg.list_get, [list_ptr, idx])
        elem_i64_ptr = builder.bitcast(elem_data_ptr, i64.as_pointer())
        elem_i64 = builder.load(elem_i64_ptr)
        elem_json = builder.inttoptr(elem_i64, cg.json_struct.as_pointer())
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
        """Generate code to pretty-print a JSON object."""
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get map pointer
        map_ptr = builder.inttoptr(value, cg.map_struct.as_pointer())

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

        # Get key string
        key_data_ptr = builder.call(cg.list_get, [keys_list, idx])
        key_i64_ptr = builder.bitcast(key_data_ptr, i64.as_pointer())
        key_i64 = builder.load(key_i64_ptr)
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
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Get string data pointer and length
        # Phase 4: String layout is { i64 owner_handle, i64 offset, i64 len, i64 size }
        str_ptr = func.args[0]
        owner_handle_ptr = builder.gep(str_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
        owner_handle = builder.load(owner_handle_ptr)
        owner_ptr = builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())
        offset_ptr = builder.gep(str_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 1)], inbounds=True)
        offset_val = builder.load(offset_ptr)
        data_ptr = builder.gep(owner_ptr, [offset_val])
        len_ptr = builder.gep(str_ptr, [ir.Constant(i32, 0), ir.Constant(i32, 2)], inbounds=True)
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

        # Parse array - simplified: return empty array for now
        builder.position_at_end(parse_array)
        empty_list = builder.call(cg.list_new, [ir.Constant(i64, 8)])
        array_json = builder.call(cg.json_new_array, [empty_list])
        builder.ret(array_json)

        # Parse object - simplified: return empty object for now
        builder.position_at_end(parse_object)
        flags = ir.Constant(i64, 0x01)  # String keys
        empty_map = builder.call(cg.map_new, [flags])
        obj_json = builder.call(cg.json_new_object, [empty_map])
        builder.ret(obj_json)

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

