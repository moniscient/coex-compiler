"""
Result type implementation for Coex.

This module provides the Result type implementation for the Coex compiler.
Result<T, E> is a tagged union for error handling:
- tag: 0 = Ok, 1 = Err
- ok_value: the success value (as i64)
- err_value: the error value (as i64)

Result struct (24 bytes):
    Field 0: tag (i64) - 0 for Ok, 1 for Err
    Field 1: ok_value (i64) - the success value
    Field 2: err_value (i64) - the error value

All operations use value semantics. Results are allocated on the GC heap.
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ResultGenerator:
    """Generates Result type and methods for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    def create_result_helpers(self):
        """Create Result type helper functions.

        Result<T, E> is a tagged union:
        - tag: 0 = Ok, 1 = Err
        - ok_value: the success value (as i64)
        - err_value: the error value (as i64)
        """
        cg = self.cg

        result_ptr = cg.result_struct.as_pointer()
        i64 = ir.IntType(64)
        i1 = ir.IntType(1)

        # Register Result in type registry
        cg.type_registry["Result"] = cg.result_struct
        cg.type_methods["Result"] = {}

        # Register Result with GC (24 bytes, reference offsets at ok_value and err_value fields)
        # Fields: tag (offset 0), ok_value (offset 8), err_value (offset 16)
        # Both value fields may contain pointers
        cg.gc.register_type("Result", 24, [8, 16])

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
        cg = self.cg

        func_type = ir.FunctionType(result_ptr, [i64])
        func = ir.Function(cg.module, func_type, name="coex_result_ok")
        cg.result_ok = func
        cg.functions["coex_result_ok"] = func
        cg.functions["Result_ok"] = func  # Also register for static method lookup
        cg.type_methods["Result"]["ok"] = "coex_result_ok"

        func.args[0].name = "value"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        value = func.args[0]

        # Allocate Result struct (24 bytes = 3 * 8) via GC
        struct_size = ir.Constant(i64, 24)
        type_id = ir.Constant(ir.IntType(32), cg.gc.get_type_id("Result"))
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
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
        cg = self.cg

        func_type = ir.FunctionType(result_ptr, [i64])
        func = ir.Function(cg.module, func_type, name="coex_result_err")
        cg.result_err = func
        cg.functions["coex_result_err"] = func
        cg.functions["Result_err"] = func  # Also register for static method lookup
        cg.type_methods["Result"]["err"] = "coex_result_err"

        func.args[0].name = "error"

        entry = func.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        error = func.args[0]

        # Allocate Result struct (24 bytes = 3 * 8) via GC
        struct_size = ir.Constant(i64, 24)
        type_id = ir.Constant(ir.IntType(32), cg.gc.get_type_id("Result"))
        raw_ptr = cg.gc.alloc_with_deref(builder, struct_size, type_id)
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
        cg = self.cg

        func_type = ir.FunctionType(i1, [result_ptr])
        func = ir.Function(cg.module, func_type, name="coex_result_is_ok")
        cg.result_is_ok = func
        cg.functions["coex_result_is_ok"] = func
        cg.type_methods["Result"]["is_ok"] = "coex_result_is_ok"

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
        cg = self.cg

        func_type = ir.FunctionType(i1, [result_ptr])
        func = ir.Function(cg.module, func_type, name="coex_result_is_err")
        cg.result_is_err = func
        cg.functions["coex_result_is_err"] = func
        cg.type_methods["Result"]["is_err"] = "coex_result_is_err"

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
        cg = self.cg

        func_type = ir.FunctionType(i64, [result_ptr])
        func = ir.Function(cg.module, func_type, name="coex_result_unwrap")
        cg.result_unwrap = func
        cg.functions["coex_result_unwrap"] = func
        cg.type_methods["Result"]["unwrap"] = "coex_result_unwrap"

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
        cg = self.cg

        func_type = ir.FunctionType(i64, [result_ptr, i64])
        func = ir.Function(cg.module, func_type, name="coex_result_unwrap_or")
        cg.result_unwrap_or = func
        cg.functions["coex_result_unwrap_or"] = func
        cg.type_methods["Result"]["unwrap_or"] = "coex_result_unwrap_or"

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
