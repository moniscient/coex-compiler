"""
JSON Module for Coex Code Generator

This module provides the JSON type implementation for the Coex compiler.
JSON layout:
    Field 0: i8 tag   - type discriminator
    Field 1: i64 value - inline value or pointer as i64

JSON tag values:
    0 = null
    1 = bool
    2 = int
    3 = float
    4 = string (value is String* pointer)
    5 = array (value is List* pointer holding [json])
    6 = object (value is Map* pointer with string keys and json values)

Methods implemented:
- Constructors: new_null, new_bool, new_int, new_float, new_string, new_array, new_object
- Type checking: is_null, is_bool, is_int, is_float, is_string, is_array, is_object
- Accessors: get_tag, get_field, get_index, len, has, keys, values
- Mutation: set_field, set_index, append, remove
- Serialization: stringify, pretty, parse
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator


# JSON tag constants
JSON_TAG_NULL = 0
JSON_TAG_BOOL = 1
JSON_TAG_INT = 2
JSON_TAG_FLOAT = 3
JSON_TAG_STRING = 4
JSON_TAG_ARRAY = 5
JSON_TAG_OBJECT = 6


class JSONGenerator:
    """Generates JSON type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def module(self):
        return self.codegen.module

    @property
    def gc(self):
        return self.codegen.gc

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_fields(self):
        return self.codegen.type_fields

    @property
    def type_methods(self):
        return self.codegen.type_methods

    @property
    def functions(self):
        return self.codegen.functions

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
    def json_struct(self):
        return self.codegen.json_struct

    # JSON function references - these are set during create_json_type
    @property
    def json_new_null(self):
        return self.codegen.json_new_null

    @property
    def json_new_bool(self):
        return self.codegen.json_new_bool

    @property
    def json_new_int(self):
        return self.codegen.json_new_int

    @property
    def json_new_float(self):
        return self.codegen.json_new_float

    @property
    def json_new_string(self):
        return self.codegen.json_new_string

    @property
    def json_new_array(self):
        return self.codegen.json_new_array

    @property
    def json_new_object(self):
        return self.codegen.json_new_object

    @property
    def json_get_tag(self):
        return self.codegen.json_get_tag

    @property
    def json_get_field(self):
        return self.codegen.json_get_field

    @property
    def json_get_index(self):
        return self.codegen.json_get_index

    @property
    def json_is_null(self):
        return self.codegen.json_is_null

    @property
    def json_is_bool(self):
        return self.codegen.json_is_bool

    @property
    def json_is_int(self):
        return self.codegen.json_is_int

    @property
    def json_is_float(self):
        return self.codegen.json_is_float

    @property
    def json_is_string(self):
        return self.codegen.json_is_string

    @property
    def json_is_array(self):
        return self.codegen.json_is_array

    @property
    def json_is_object(self):
        return self.codegen.json_is_object

    @property
    def json_len(self):
        return self.codegen.json_len

    @property
    def json_has(self):
        return self.codegen.json_has

    @property
    def json_set_field(self):
        return self.codegen.json_set_field

    @property
    def json_set_index(self):
        return self.codegen.json_set_index

    @property
    def json_append(self):
        return self.codegen.json_append

    @property
    def json_remove(self):
        return self.codegen.json_remove

    @property
    def json_keys(self):
        return self.codegen.json_keys

    @property
    def json_values(self):
        return self.codegen.json_values

    @property
    def json_stringify(self):
        return self.codegen.json_stringify

    @property
    def json_pretty(self):
        return self.codegen.json_pretty

    @property
    def json_parse(self):
        return self.codegen.json_parse

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
        i8 = ir.IntType(8)
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)

        # Define the JSON struct: { i8 tag, i64 value }
        self.codegen.json_struct = ir.global_context.get_identified_type("struct.Json")
        self.codegen.json_struct.set_body(
            i8,   # tag (field 0) - type discriminator
            i64,  # value (field 1) - inline value or pointer as i64
        )

        # Declare constructor functions
        json_ptr = self.codegen.json_struct.as_pointer()

        # json_new_null() -> Json*
        self.codegen.json_new_null = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, []),
            name="coex_json_new_null"
        )

        # json_new_bool(i1 value) -> Json*
        self.codegen.json_new_bool = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [ir.IntType(1)]),
            name="coex_json_new_bool"
        )

        # json_new_int(i64 value) -> Json*
        self.codegen.json_new_int = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [i64]),
            name="coex_json_new_int"
        )

        # json_new_float(f64 value) -> Json*
        self.codegen.json_new_float = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [ir.DoubleType()]),
            name="coex_json_new_float"
        )

        # json_new_string(String* value) -> Json*
        self.codegen.json_new_string = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [self.string_struct.as_pointer()]),
            name="coex_json_new_string"
        )

        # json_new_array(List* value) -> Json*
        self.codegen.json_new_array = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [self.list_struct.as_pointer()]),
            name="coex_json_new_array"
        )

        # json_new_object(Map* value) -> Json*
        self.codegen.json_new_object = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [self.map_struct.as_pointer()]),
            name="coex_json_new_object"
        )

        # json_get_tag(Json*) -> i8
        self.codegen.json_get_tag = ir.Function(
            self.module,
            ir.FunctionType(i8, [json_ptr]),
            name="coex_json_get_tag"
        )

        # json_get_field(Json*, String*) -> Json* (returns null json if not found)
        self.codegen.json_get_field = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, self.string_struct.as_pointer()]),
            name="coex_json_get_field"
        )

        # json_get_index(Json*, i64) -> Json* (returns null json if out of bounds)
        self.codegen.json_get_index = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, i64]),
            name="coex_json_get_index"
        )

        # Type checking methods: is_null, is_bool, is_int, is_float, is_string, is_array, is_object
        i1 = ir.IntType(1)
        self.codegen.json_is_null = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_null")
        self.codegen.json_is_bool = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_bool")
        self.codegen.json_is_int = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_int")
        self.codegen.json_is_float = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_float")
        self.codegen.json_is_string = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_string")
        self.codegen.json_is_array = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_array")
        self.codegen.json_is_object = ir.Function(self.module, ir.FunctionType(i1, [json_ptr]), name="coex_json_is_object")

        # json_len(Json*) -> i64 (length for arrays/objects, 0 otherwise)
        self.codegen.json_len = ir.Function(self.module, ir.FunctionType(i64, [json_ptr]), name="coex_json_len")

        # json_has(Json*, String*) -> bool (check if object has key)
        self.codegen.json_has = ir.Function(self.module, ir.FunctionType(i1, [json_ptr, self.string_struct.as_pointer()]), name="coex_json_has")

        # json_set_field(Json*, String*, Json*) -> Json* (return new json with field set)
        self.codegen.json_set_field = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, self.string_struct.as_pointer(), json_ptr]),
            name="coex_json_set_field"
        )

        # json_set_index(Json*, i64, Json*) -> Json* (return new json with index set)
        self.codegen.json_set_index = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, i64, json_ptr]),
            name="coex_json_set_index"
        )

        # json_append(Json*, Json*) -> Json* (append to array)
        self.codegen.json_append = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, json_ptr]),
            name="coex_json_append"
        )

        # json_remove(Json*, String*) -> Json* (remove key from object)
        self.codegen.json_remove = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [json_ptr, self.string_struct.as_pointer()]),
            name="coex_json_remove"
        )

        # json_keys(Json*) -> List* (get keys as list of strings)
        self.codegen.json_keys = ir.Function(
            self.module,
            ir.FunctionType(self.list_struct.as_pointer(), [json_ptr]),
            name="coex_json_keys"
        )

        # json_values(Json*) -> List* (get values as list of json)
        self.codegen.json_values = ir.Function(
            self.module,
            ir.FunctionType(self.list_struct.as_pointer(), [json_ptr]),
            name="coex_json_values"
        )

        # json_stringify(Json*) -> String* (serialize JSON to string)
        self.codegen.json_stringify = ir.Function(
            self.module,
            ir.FunctionType(self.string_struct.as_pointer(), [json_ptr]),
            name="coex_json_stringify"
        )

        # json_parse(String*) -> Json* (parse string to JSON, returns null on error)
        self.codegen.json_parse = ir.Function(
            self.module,
            ir.FunctionType(json_ptr, [self.string_struct.as_pointer()]),
            name="coex_json_parse"
        )

        # json_pretty(Json*, i64 indent) -> String* (serialize JSON with pretty printing)
        self.codegen.json_pretty = ir.Function(
            self.module,
            ir.FunctionType(self.string_struct.as_pointer(), [json_ptr, ir.IntType(64)]),
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

        # Implement string.validjson() now that json_parse exists (delegated to strings module)
        self.codegen._strings.implement_string_validjson()

        # Register JSON type and methods
        self._register_json_methods()

    # NOTE: The _implement_json_* methods are delegated to codegen_original.py
    # for now. Full extraction will be completed in a follow-up phase.
    # This allows the modularization to proceed incrementally.

    def _implement_json_new_null(self):
        self.codegen._implement_json_new_null()

    def _implement_json_new_bool(self):
        self.codegen._implement_json_new_bool()

    def _implement_json_new_int(self):
        self.codegen._implement_json_new_int()

    def _implement_json_new_float(self):
        self.codegen._implement_json_new_float()

    def _implement_json_new_string(self):
        self.codegen._implement_json_new_string()

    def _implement_json_new_array(self):
        self.codegen._implement_json_new_array()

    def _implement_json_new_object(self):
        self.codegen._implement_json_new_object()

    def _implement_json_get_tag(self):
        self.codegen._implement_json_get_tag()

    def _implement_json_get_field(self):
        self.codegen._implement_json_get_field()

    def _implement_json_get_index(self):
        self.codegen._implement_json_get_index()

    def _implement_json_is_null(self):
        self.codegen._implement_json_is_null()

    def _implement_json_is_bool(self):
        self.codegen._implement_json_is_bool()

    def _implement_json_is_int(self):
        self.codegen._implement_json_is_int()

    def _implement_json_is_float(self):
        self.codegen._implement_json_is_float()

    def _implement_json_is_string(self):
        self.codegen._implement_json_is_string()

    def _implement_json_is_array(self):
        self.codegen._implement_json_is_array()

    def _implement_json_is_object(self):
        self.codegen._implement_json_is_object()

    def _implement_json_len(self):
        self.codegen._implement_json_len()

    def _implement_json_has(self):
        self.codegen._implement_json_has()

    def _implement_json_set_field(self):
        self.codegen._implement_json_set_field()

    def _implement_json_set_index(self):
        self.codegen._implement_json_set_index()

    def _implement_json_append(self):
        self.codegen._implement_json_append()

    def _implement_json_remove(self):
        self.codegen._implement_json_remove()

    def _implement_json_keys(self):
        self.codegen._implement_json_keys()

    def _implement_json_values(self):
        self.codegen._implement_json_values()

    def _implement_json_stringify(self):
        self.codegen._implement_json_stringify()

    def _implement_json_pretty(self):
        self.codegen._implement_json_pretty()

    def _implement_json_parse(self):
        self.codegen._implement_json_parse()

    def _register_json_methods(self):
        self.codegen._register_json_methods()
