"""
Expression Code Generation for Coex.

This module handles:
- Expression dispatch (_generate_expression)
- Literal handling (int, float, bool, string, nil)
- Identifier reference
- Binary and unary operations
- Ternary expressions
- Member access
- Index and slice operations
- Collection literals (list, map, set, tuple)
- Range expressions
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict
from typing import List as PyList

from ast_nodes import (
    Expr, IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, NilLiteral,
    Identifier, BinaryExpr, BinaryOp, UnaryExpr, UnaryOp, CallExpr,
    MethodCallExpr, MemberExpr, IndexExpr, RelativeIndexExpr, SliceExpr, TernaryExpr,
    ListExpr, MapExpr, SetExpr, TupleExpr, RangeExpr, LambdaExpr,
    SelfExpr, LlvmIrExpr, AsExpr,
    ListComprehension, SetComprehension, MapComprehension, JsonObjectExpr,
    IdentifierPattern, WildcardPattern, TuplePattern, FunctionKind,
    AtomicType, PrimitiveType, ListType, ArrayType, MapType, SetType, FunctionDecl, KindFunctionDecl
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ExpressionGenerator:
    """Generates expression-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Main Expression Dispatch
    # ========================================================================

    def generate_expression(self, expr: Expr) -> ir.Value:
        """Generate code for an expression"""
        cg = self.cg

        if isinstance(expr, IntLiteral):
            return ir.Constant(ir.IntType(64), expr.value)

        elif isinstance(expr, FloatLiteral):
            return ir.Constant(ir.DoubleType(), expr.value)

        elif isinstance(expr, BoolLiteral):
            return ir.Constant(ir.IntType(1), 1 if expr.value else 0)

        elif isinstance(expr, StringLiteral):
            return cg._get_string_ptr(expr.value)

        elif isinstance(expr, NilLiteral):
            return ir.Constant(ir.IntType(64), 0)

        elif isinstance(expr, Identifier):
            return self.generate_identifier(expr)

        elif isinstance(expr, BinaryExpr):
            return self.generate_binary(expr)

        elif isinstance(expr, UnaryExpr):
            return self.generate_unary(expr)

        elif isinstance(expr, CallExpr):
            return self.generate_call(expr)

        elif isinstance(expr, MethodCallExpr):
            return self.generate_method_call(expr)

        elif isinstance(expr, MemberExpr):
            return self.generate_member(expr)

        elif isinstance(expr, IndexExpr):
            return self.generate_index(expr)

        elif isinstance(expr, RelativeIndexExpr):
            return self.generate_relative_index(expr)

        elif isinstance(expr, SliceExpr):
            return self.generate_slice(expr)

        elif isinstance(expr, TernaryExpr):
            return self.generate_ternary(expr)

        elif isinstance(expr, ListExpr):
            return self.generate_list(expr)

        elif isinstance(expr, MapExpr):
            return self.generate_map(expr)

        elif isinstance(expr, SetExpr):
            return self.generate_set(expr)

        elif isinstance(expr, JsonObjectExpr):
            return cg._generate_json_object(expr)

        elif isinstance(expr, ListComprehension):
            return cg._generate_list_comprehension(expr)

        elif isinstance(expr, SetComprehension):
            return cg._generate_set_comprehension(expr)

        elif isinstance(expr, MapComprehension):
            return cg._generate_map_comprehension(expr)

        elif isinstance(expr, TupleExpr):
            return self.generate_tuple(expr)

        elif isinstance(expr, RangeExpr):
            return self.generate_range(expr)

        elif isinstance(expr, LambdaExpr):
            return cg._generate_lambda(expr)

        elif isinstance(expr, SelfExpr):
            # Return self pointer if available
            if "self" in cg.locals:
                return cg.builder.load(cg.locals["self"])
            return ir.Constant(ir.IntType(64), 0)

        elif isinstance(expr, LlvmIrExpr):
            return cg._generate_llvm_ir_block(expr)

        elif isinstance(expr, AsExpr):
            return cg._generate_as_expr(expr)

        else:
            return ir.Constant(ir.IntType(64), 0)

    # ========================================================================
    # Identifier
    # ========================================================================

    def generate_identifier(self, expr: Identifier) -> ir.Value:
        """Generate code for identifier reference"""
        cg = self.cg
        name = expr.name

        # Check for module-level constants (compile-time substitution)
        if name in cg.module_constants:
            # Generate the constant value expression directly
            return self.generate_expression(cg.module_constants[name])

        # Check for use-after-move
        if name in cg.moved_vars:
            raise RuntimeError(
                f"Use of moved variable '{name}': variable was moved and can no longer be used. "
                f"Assign a new value to '{name}' before using it again."
            )

        # Check if we're in a cycle and this is a cycle variable
        ctx = cg._get_cycle_context()
        if ctx and name in ctx['cycle_vars']:
            # Read from read buffer (previous generation)
            read_buf = ctx['read_buffers'][name]
            return cg.builder.load(read_buf, name=name)

        if name in cg.locals:
            return cg.builder.load(cg.locals[name], name=name)
        elif name in cg.functions:
            return cg.functions[name]
        else:
            # Check if it's a field access in a method context
            if cg.current_type and "self" in cg.locals:
                field_idx = cg._get_field_index(cg.current_type, name)
                if field_idx is not None:
                    self_ptr = cg.builder.load(cg.locals["self"])
                    field_ptr = cg.builder.gep(self_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), field_idx)
                    ], inbounds=True)
                    return cg.builder.load(field_ptr, name=name)

            # Unknown variable - raise error
            raise RuntimeError(f"Undeclared identifier '{name}': variable has not been declared in this scope")

    # ========================================================================
    # Binary Operations
    # ========================================================================

    def generate_binary(self, expr: BinaryExpr) -> ir.Value:
        """Generate code for binary expression"""
        cg = self.cg

        # Short-circuit evaluation for logical ops
        if expr.op == BinaryOp.AND:
            return self.generate_short_circuit_and(expr)
        elif expr.op == BinaryOp.OR:
            return self.generate_short_circuit_or(expr)

        left = self.generate_expression(expr.left)
        right = self.generate_expression(expr.right)

        # Check for String operations
        is_string = (isinstance(left.type, ir.PointerType) and
                     hasattr(left.type.pointee, 'name') and
                     left.type.pointee.name == "struct.String")

        if is_string:
            if expr.op == BinaryOp.ADD:
                # String concatenation: a + b -> string_concat(a, b)
                return cg.builder.call(cg.string_concat, [left, right])
            elif expr.op == BinaryOp.EQ:
                # String equality: a == b -> string_eq(a, b)
                return cg.builder.call(cg.string_eq, [left, right])
            elif expr.op == BinaryOp.NE:
                # String inequality: a != b -> !string_eq(a, b)
                eq_result = cg.builder.call(cg.string_eq, [left, right])
                return cg.builder.not_(eq_result)

        # Promote types if needed
        if left.type != right.type:
            # Int + float64 -> float64
            if isinstance(left.type, ir.IntType) and isinstance(right.type, ir.DoubleType):
                left = cg.builder.sitofp(left, ir.DoubleType())
            elif isinstance(left.type, ir.DoubleType) and isinstance(right.type, ir.IntType):
                right = cg.builder.sitofp(right, ir.DoubleType())
            # Int + float32 -> float32
            elif isinstance(left.type, ir.IntType) and isinstance(right.type, ir.FloatType):
                left = cg.builder.sitofp(left, ir.FloatType())
            elif isinstance(left.type, ir.FloatType) and isinstance(right.type, ir.IntType):
                right = cg.builder.sitofp(right, ir.FloatType())
            # Float32 + float64 -> float64
            elif isinstance(left.type, ir.FloatType) and isinstance(right.type, ir.DoubleType):
                left = cg.builder.fpext(left, ir.DoubleType())
            elif isinstance(left.type, ir.DoubleType) and isinstance(right.type, ir.FloatType):
                right = cg.builder.fpext(right, ir.DoubleType())
            elif isinstance(left.type, ir.IntType) and isinstance(right.type, ir.IntType):
                # Promote smaller to larger
                if left.type.width < right.type.width:
                    left = cg.builder.sext(left, right.type)
                elif right.type.width < left.type.width:
                    right = cg.builder.sext(right, left.type)

        is_float = isinstance(left.type, (ir.DoubleType, ir.FloatType))

        if expr.op == BinaryOp.ADD:
            return cg.builder.fadd(left, right) if is_float else cg.builder.add(left, right)
        elif expr.op == BinaryOp.SUB:
            return cg.builder.fsub(left, right) if is_float else cg.builder.sub(left, right)
        elif expr.op == BinaryOp.MUL:
            return cg.builder.fmul(left, right) if is_float else cg.builder.mul(left, right)
        elif expr.op == BinaryOp.DIV:
            return cg.builder.fdiv(left, right) if is_float else cg.builder.sdiv(left, right)
        elif expr.op == BinaryOp.MOD:
            return cg.builder.frem(left, right) if is_float else cg.builder.srem(left, right)
        elif expr.op == BinaryOp.EQ:
            return cg.builder.fcmp_ordered("==", left, right) if is_float else cg.builder.icmp_signed("==", left, right)
        elif expr.op == BinaryOp.NE:
            return cg.builder.fcmp_ordered("!=", left, right) if is_float else cg.builder.icmp_signed("!=", left, right)
        elif expr.op == BinaryOp.LT:
            return cg.builder.fcmp_ordered("<", left, right) if is_float else cg.builder.icmp_signed("<", left, right)
        elif expr.op == BinaryOp.GT:
            return cg.builder.fcmp_ordered(">", left, right) if is_float else cg.builder.icmp_signed(">", left, right)
        elif expr.op == BinaryOp.LE:
            return cg.builder.fcmp_ordered("<=", left, right) if is_float else cg.builder.icmp_signed("<=", left, right)
        elif expr.op == BinaryOp.GE:
            return cg.builder.fcmp_ordered(">=", left, right) if is_float else cg.builder.icmp_signed(">=", left, right)
        elif expr.op == BinaryOp.NULL_COALESCE:
            # a ?? b -> if a has value, return unwrapped a, else return b
            # Handle optional types (struct {i1, T})
            if isinstance(left.type, ir.LiteralStructType) and len(left.type.elements) == 2:
                if isinstance(left.type.elements[0], ir.IntType) and left.type.elements[0].width == 1:
                    # This is an optional type - extract has_value and value
                    has_value = cg.builder.extract_value(left, 0, name="has_value")
                    value = cg.builder.extract_value(left, 1, name="opt_value")
                    return cg.builder.select(has_value, value, right)
            # Handle pointer types (nil = null pointer)
            elif isinstance(left.type, ir.PointerType):
                null_ptr = ir.Constant(left.type, None)
                is_not_null = cg.builder.icmp_unsigned("!=", left, null_ptr)
                return cg.builder.select(is_not_null, left, right)
            # Fallback: treat as boolean check
            cond = cg._to_bool(left)
            return cg.builder.select(cond, left, right)

        return ir.Constant(ir.IntType(64), 0)

    def generate_short_circuit_and(self, expr: BinaryExpr) -> ir.Value:
        """Generate short-circuit AND"""
        cg = self.cg
        func = cg.builder.function

        eval_right = func.append_basic_block("and_right")
        merge = func.append_basic_block("and_merge")

        left = self.generate_expression(expr.left)
        left_bool = cg._to_bool(left)
        left_block = cg.builder.block

        cg.builder.cbranch(left_bool, eval_right, merge)

        cg.builder.position_at_end(eval_right)
        right = self.generate_expression(expr.right)
        right_bool = cg._to_bool(right)
        right_block = cg.builder.block
        cg.builder.branch(merge)

        cg.builder.position_at_end(merge)
        phi = cg.builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 0), left_block)
        phi.add_incoming(right_bool, right_block)

        return phi

    def generate_short_circuit_or(self, expr: BinaryExpr) -> ir.Value:
        """Generate short-circuit OR"""
        cg = self.cg
        func = cg.builder.function

        eval_right = func.append_basic_block("or_right")
        merge = func.append_basic_block("or_merge")

        left = self.generate_expression(expr.left)
        left_bool = cg._to_bool(left)
        left_block = cg.builder.block

        cg.builder.cbranch(left_bool, merge, eval_right)

        cg.builder.position_at_end(eval_right)
        right = self.generate_expression(expr.right)
        right_bool = cg._to_bool(right)
        right_block = cg.builder.block
        cg.builder.branch(merge)

        cg.builder.position_at_end(merge)
        phi = cg.builder.phi(ir.IntType(1))
        phi.add_incoming(ir.Constant(ir.IntType(1), 1), left_block)
        phi.add_incoming(right_bool, right_block)

        return phi

    # ========================================================================
    # Unary Operations
    # ========================================================================

    def generate_unary(self, expr: UnaryExpr) -> ir.Value:
        """Generate code for unary expression"""
        cg = self.cg
        operand = self.generate_expression(expr.operand)

        if expr.op == UnaryOp.NEG:
            if isinstance(operand.type, ir.DoubleType):
                return cg.builder.fneg(operand)
            else:
                return cg.builder.neg(operand)
        elif expr.op == UnaryOp.NOT:
            if operand.type == ir.IntType(1):
                return cg.builder.not_(operand)
            else:
                # Compare to zero
                cond = cg._to_bool(operand)
                return cg.builder.not_(cond)
        elif expr.op == UnaryOp.AWAIT:
            # In sequential mode, await just returns the value
            return operand

        return operand

    # ========================================================================
    # Ternary Expression
    # ========================================================================

    def generate_ternary(self, expr: TernaryExpr) -> ir.Value:
        """Generate code for ternary expression

        For ; variant (continuation): both branches merge, result is phi of both values
        For ! variant (exit): else branch returns from function, result is then value only
        """
        cg = self.cg
        func = cg.builder.function

        then_block = func.append_basic_block("tern_then")
        else_block = func.append_basic_block("tern_else")

        cond = self.generate_expression(expr.condition)
        cond = cg._to_bool(cond)

        cg.builder.cbranch(cond, then_block, else_block)

        cg.builder.position_at_end(then_block)
        then_val = self.generate_expression(expr.then_expr)
        then_block = cg.builder.block

        if expr.is_exit:
            # Exit variant: else branch returns, no merge needed
            merge_block = func.append_basic_block("tern_merge")
            cg.builder.branch(merge_block)

            cg.builder.position_at_end(else_block)
            else_val = self.generate_expression(expr.else_expr)

            # Cast else_val to function return type if needed
            ret_type = func.function_type.return_type
            else_val = cg._cast_value(else_val, ret_type)

            # Pop GC frame before returning
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            # Return from function
            cg.builder.ret(else_val)

            # Continue in merge block with then_val
            cg.builder.position_at_end(merge_block)
            return then_val
        else:
            # Continuation variant: both branches merge
            merge_block = func.append_basic_block("tern_merge")
            cg.builder.branch(merge_block)

            cg.builder.position_at_end(else_block)
            else_val = self.generate_expression(expr.else_expr)
            else_block = cg.builder.block
            cg.builder.branch(merge_block)

            cg.builder.position_at_end(merge_block)

            # Ensure same type
            if then_val.type != else_val.type:
                if isinstance(then_val.type, ir.IntType) and isinstance(else_val.type, ir.IntType):
                    max_width = max(then_val.type.width, else_val.type.width)
                    target = ir.IntType(max_width)
                    then_val = cg._cast_value(then_val, target)
                    else_val = cg._cast_value(else_val, target)

            phi = cg.builder.phi(then_val.type)
            phi.add_incoming(then_val, then_block)
            phi.add_incoming(else_val, else_block)

            return phi

    # ========================================================================
    # Collection Literals
    # ========================================================================

    def generate_list(self, expr: ListExpr) -> ir.Value:
        """Generate code for list literal: [1, 2, 3]

        With USE_TAGGED_VALUES enabled, each element is stored as a TaggedValue
        = { i64 type_id, i64 value }. This makes elements self-describing,
        allowing the GC to trace references correctly without compile-time type inference.
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Check if TaggedValue mode is enabled
        use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False)

        if not expr.elements:
            # Empty list
            if use_tagged:
                # TaggedValue elements are always 16 bytes, flags=0 (GC reads type from each element)
                elem_size = ir.Constant(i64, cg.TAGGED_VALUE_SIZE)
                flags = ir.Constant(i64, 0)
            else:
                elem_size = ir.Constant(i64, 8)
                flags = ir.Constant(i64, 0)
            return cg.builder.call(cg.list_new, [elem_size, flags])

        # Generate first element to determine type
        first_elem = self.generate_expression(expr.elements[0])
        elem_type = first_elem.type

        # Infer Coex type for the element
        elem_coex_type = cg._infer_type_from_expr(expr.elements[0])
        is_ref_type = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)

        if use_tagged:
            # TaggedValue mode: always 16 bytes, flags=0 (type is in each element)
            elem_size = ir.Constant(i64, cg.TAGGED_VALUE_SIZE)
            list_flags = ir.Constant(i64, 0)  # No special flags needed - GC reads type_id from elements
            list_ptr = cg.builder.call(cg.list_new, [elem_size, list_flags])

            # Get TaggedValue type ID for this element type
            tv_type_id = cg.gc.get_tv_type_id(elem_coex_type) if elem_coex_type else cg.gc.TV_TYPE_INT

            # Append each element as TaggedValue
            for i, elem_expr in enumerate(expr.elements):
                if i == 0:
                    elem_val = first_elem
                else:
                    elem_val = self.generate_expression(elem_expr)

                # Create TaggedValue on stack
                tv_ptr = cg.gc.create_tagged_value(cg.builder, tv_type_id, self._to_i64_value(elem_val, is_ref_type))

                # Append - list_append copies the TaggedValue (16 bytes)
                tv_i8 = cg.builder.bitcast(tv_ptr, ir.IntType(8).as_pointer())
                list_ptr = cg.builder.call(cg.list_append, [list_ptr, tv_i8, elem_size])

            return list_ptr

        # Legacy mode: variable elem_size based on type
        if is_ref_type:
            size = 8  # Handles are always i64
        elif isinstance(elem_type, ir.IntType):
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

        elem_size = ir.Constant(i64, size)
        list_flags = ir.Constant(i64, cg.LIST_FLAG_ELEM_IS_REF if is_ref_type else 0)
        list_ptr = cg.builder.call(cg.list_new, [elem_size, list_flags])

        for i, elem_expr in enumerate(expr.elements):
            if i == 0:
                elem_val = first_elem
            else:
                elem_val = self.generate_expression(elem_expr)

            if is_ref_type:
                elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
                elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                temp = cg.builder.alloca(i64, name=f"list_elem_{i}_handle")
                cg.builder.store(elem_handle, temp)
                temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
            else:
                temp = cg.builder.alloca(elem_type, name=f"list_elem_{i}")
                cg.builder.store(elem_val, temp)
                temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

            list_ptr = cg.builder.call(cg.list_append, [list_ptr, temp_ptr, elem_size])

        return list_ptr

    def _to_i64_value(self, val: ir.Value, is_ref: bool) -> ir.Value:
        """Convert a value to i64 for storage in TaggedValue.

        For reference types, converts pointer to handle.
        For primitives, converts/casts to i64.
        """
        cg = self.cg
        i64 = ir.IntType(64)

        if is_ref:
            # Reference type: convert pointer to handle
            val_i8 = cg.builder.bitcast(val, ir.IntType(8).as_pointer())
            return cg.builder.call(cg.gc.gc_ptr_to_handle, [val_i8])
        elif val.type == i64:
            return val
        elif isinstance(val.type, ir.IntType):
            if val.type.width < 64:
                return cg.builder.zext(val, i64)
            else:
                return cg.builder.trunc(val, i64)
        elif isinstance(val.type, ir.DoubleType):
            return cg.builder.bitcast(val, i64)
        elif isinstance(val.type, ir.PointerType):
            # BUG-081 FIX: Pointer types should use gc_ptr_to_handle, not ptrtoint
            # This fallback case handles pointers not explicitly marked as ref types
            val_i8 = cg.builder.bitcast(val, ir.IntType(8).as_pointer())
            return cg.builder.call(cg.gc.gc_ptr_to_handle, [val_i8])
        else:
            # Fallback: try direct bitcast if same size
            return cg.builder.bitcast(val, i64)

    def _from_i64_value(self, val: ir.Value, target_type: ir.Type) -> ir.Value:
        """Convert an i64 value back to the target LLVM type.

        This is the inverse of _to_i64_value for primitive types.
        Note: For heap types, the caller should use gc_handle_deref instead.
        """
        cg = self.cg
        i64 = ir.IntType(64)

        if target_type == i64:
            return val
        elif isinstance(target_type, ir.IntType):
            if target_type.width < 64:
                return cg.builder.trunc(val, target_type)
            else:
                return val  # Already i64
        elif isinstance(target_type, ir.DoubleType):
            return cg.builder.bitcast(val, target_type)
        elif isinstance(target_type, ir.PointerType):
            return cg.builder.inttoptr(val, target_type)
        else:
            # For other types, try inttoptr (handles pointer-like things)
            return cg.builder.inttoptr(val, target_type)

    def generate_map(self, expr: MapExpr) -> ir.Value:
        """Generate code for map literal: {key: value, ...}"""
        cg = self.cg
        i64 = ir.IntType(64)

        # Compute flags based on entry types
        flags = 0
        if expr.entries:
            key_expr, value_expr = expr.entries[0]
            key_type = cg._infer_type_from_expr(key_expr)
            value_type = cg._infer_type_from_expr(value_expr)
            flags = cg._compute_map_flags(key_type, value_type)

        # Create empty map with flags
        map_ptr = cg.builder.call(cg.map_new, [ir.Constant(i64, flags)])

        # Add each entry (map_set returns a new map with value semantics)
        for key_expr, value_expr in expr.entries:
            key = self.generate_expression(key_expr)
            value = self.generate_expression(value_expr)
            value_coex_type = cg._infer_type_from_expr(value_expr)

            # Check if key is a string pointer
            is_string_key = (isinstance(key.type, ir.PointerType) and
                            hasattr(key.type.pointee, 'name') and
                            key.type.pointee.name == "struct.String")

            # Check if value is a reference type - if so, store handle instead of pointer
            is_ref_value = value_coex_type is not None and cg._is_reference_type(value_coex_type)

            if is_string_key:
                # Use string-aware map_set
                if is_ref_value:
                    value_i8 = cg.builder.bitcast(value, ir.IntType(8).as_pointer())
                    value_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
                    map_ptr = cg.builder.call(cg.map_set_string, [map_ptr, key, value_handle])
                else:
                    value_i64 = cg._cast_value(value, ir.IntType(64))
                    map_ptr = cg.builder.call(cg.map_set_string, [map_ptr, key, value_i64])
            else:
                # Cast to i64 for map storage
                key_i64 = cg._cast_value(key, ir.IntType(64))
                if is_ref_value:
                    value_i8 = cg.builder.bitcast(value, ir.IntType(8).as_pointer())
                    value_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
                    map_ptr = cg.builder.call(cg.map_set, [map_ptr, key_i64, value_handle])
                else:
                    value_i64 = cg._cast_value(value, ir.IntType(64))
                    # map_set returns a NEW map; update our reference
                    map_ptr = cg.builder.call(cg.map_set, [map_ptr, key_i64, value_i64])

        return map_ptr

    def generate_set(self, expr: SetExpr) -> ir.Value:
        """Generate code for set literal: {a, b, c}"""
        cg = self.cg
        i64 = ir.IntType(64)

        # Compute flags based on element type
        flags = 0
        if expr.elements:
            elem_type = cg._infer_type_from_expr(expr.elements[0])
            flags = cg._compute_set_flags(elem_type)

        # Create empty set with flags
        set_ptr = cg.builder.call(cg.set_new, [ir.Constant(i64, flags)])

        # Add each element (set_add returns a new set with value semantics)
        for elem_expr in expr.elements:
            elem = self.generate_expression(elem_expr)
            elem_coex_type = cg._infer_type_from_expr(elem_expr)

            # Check if element is a string
            is_string_elem = (isinstance(elem.type, ir.PointerType) and
                            hasattr(elem.type.pointee, 'name') and
                            elem.type.pointee.name == "struct.String")

            if is_string_elem:
                # Use string-aware set_add (strings stored as pointers for content comparison)
                set_ptr = cg.builder.call(cg.set_add_string, [set_ptr, elem])
            else:
                # Check if element is a reference type - if so, store handle instead of pointer
                is_ref_elem = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)
                if is_ref_elem:
                    elem_i8 = cg.builder.bitcast(elem, ir.IntType(8).as_pointer())
                    elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                    set_ptr = cg.builder.call(cg.set_add, [set_ptr, elem_handle])
                else:
                    # Cast to i64 for set storage
                    elem_i64 = cg._cast_value(elem, ir.IntType(64))
                    # set_add returns a NEW set; update our reference
                    set_ptr = cg.builder.call(cg.set_add, [set_ptr, elem_i64])

        return set_ptr

    def generate_tuple(self, expr: TupleExpr) -> ir.Value:
        """Generate code for tuple literal"""
        cg = self.cg

        if not expr.elements:
            return ir.Constant(ir.IntType(64), 0)

        # Generate each element
        values = []
        types = []
        for _, elem_expr in expr.elements:
            val = self.generate_expression(elem_expr)
            values.append(val)
            types.append(val.type)

        # Create struct type
        tuple_type = ir.LiteralStructType(types)

        # Allocate and store
        alloca = cg.builder.alloca(tuple_type)
        for i, val in enumerate(values):
            ptr = cg.builder.gep(alloca, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            cg.builder.store(val, ptr)

        return cg.builder.load(alloca)

    def generate_range(self, expr: RangeExpr) -> ir.Value:
        """Generate code for range expression"""
        # Range as expression - return struct or iterator
        # For now just return start value
        return self.generate_expression(expr.start)

    # ========================================================================
    # Member Access
    # ========================================================================

    def generate_member(self, expr: MemberExpr) -> ir.Value:
        """Generate code for member access"""
        cg = self.cg

        # Check for enum variant access: EnumName.VariantName
        if isinstance(expr.object, Identifier):
            type_name = expr.object.name
            if hasattr(cg, 'enum_variants') and type_name in cg.enum_variants:
                variant_name = expr.member
                if variant_name in cg.enum_variants[type_name]:
                    # This is an enum variant with no arguments (like Color.Green)
                    return cg._generate_enum_constructor(type_name, variant_name, [], {})

        obj = self.generate_expression(expr.object)

        # Check if this is a tuple (literal struct type)
        if isinstance(obj.type, ir.LiteralStructType):
            # Tuple member access
            # Check if member is a numeric index (0, 1, 2, ...)
            if expr.member.isdigit():
                idx = int(expr.member)
                if idx < len(obj.type.elements):
                    return cg.builder.extract_value(obj, idx)
            else:
                # Named tuple access - need to look up the index
                tuple_info = self.get_tuple_field_info(expr.object)
                if tuple_info:
                    for i, (name, _) in enumerate(tuple_info):
                        if name == expr.member:
                            return cg.builder.extract_value(obj, i)
            return ir.Constant(ir.IntType(64), 0)

        # Check for pointer to literal struct (tuple stored in variable)
        if isinstance(obj.type, ir.PointerType) and isinstance(obj.type.pointee, ir.LiteralStructType):
            struct_type = obj.type.pointee
            if expr.member.isdigit():
                idx = int(expr.member)
                if idx < len(struct_type.elements):
                    ptr = cg.builder.gep(obj, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), idx)
                    ])
                    return cg.builder.load(ptr)
            else:
                # Named access
                tuple_info = self.get_tuple_field_info(expr.object)
                if tuple_info:
                    for i, (name, _) in enumerate(tuple_info):
                        if name == expr.member:
                            ptr = cg.builder.gep(obj, [
                                ir.Constant(ir.IntType(32), 0),
                                ir.Constant(ir.IntType(32), i)
                            ])
                            return cg.builder.load(ptr)

        # Try to determine the type from the pointer
        type_name = cg._get_type_name_from_ptr(obj.type)

        if type_name and type_name in cg.type_fields:
            field_idx = cg._get_field_index(type_name, expr.member)
            if field_idx is not None:
                # GEP to get field pointer
                field_ptr = cg.builder.gep(obj, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), field_idx)
                ], inbounds=True)
                field_val = cg.builder.load(field_ptr)

                # Phase 6: Reference type fields store i64 handles - convert to pointer
                field_info = cg.type_fields[type_name]
                if field_idx < len(field_info):
                    _, field_type = field_info[field_idx]
                    if cg._is_reference_type(field_type):
                        # Field contains a handle - dereference to get pointer
                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [field_val])
                        ptr_type = cg._get_llvm_type(field_type)
                        return cg.builder.bitcast(ptr_i8, ptr_type)

                return field_val

        # Handle JSON field access: j.field -> json_get_field(j, "field")
        if type_name == "Json":
            # Create a string constant from the member name
            key_str = cg._get_string_ptr(expr.member)
            # Call json_get_field
            return cg.builder.call(cg.json_get_field, [obj, key_str])

        # Handle known members for built-in types
        if expr.member == "width" or expr.member == "height":
            # Matrix dimensions
            return ir.Constant(ir.IntType(64), 0)

        return ir.Constant(ir.IntType(64), 0)

    def get_tuple_field_info(self, expr: Expr) -> Optional[PyList[tuple]]:
        """Get field info for a tuple expression (name, type pairs)"""
        cg = self.cg
        if isinstance(expr, Identifier):
            name = expr.name
            if name in cg.locals:
                if name in cg.tuple_field_info:
                    return cg.tuple_field_info[name]
        return None

    def get_lvalue_member(self, expr: MemberExpr) -> Optional[ir.Value]:
        """Get pointer to a member for assignment"""
        cg = self.cg
        obj = self.generate_expression(expr.object)

        type_name = cg._get_type_name_from_ptr(obj.type)

        if type_name and type_name in cg.type_fields:
            field_idx = cg._get_field_index(type_name, expr.member)
            if field_idx is not None:
                return cg.builder.gep(obj, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), field_idx)
                ], inbounds=True)

        return None

    # ========================================================================
    # Index and Slice Access
    # ========================================================================

    def generate_index(self, expr: IndexExpr) -> ir.Value:
        """Generate code for index access: obj[idx] or obj[idx1, idx2]

        For user-defined types, this calls the .get() method.
        """
        cg = self.cg

        obj = self.generate_expression(expr.object)

        if not expr.indices:
            return ir.Constant(ir.IntType(64), 0)

        # Check if this is a user-defined type with a get method
        type_name = cg._get_type_name_from_ptr(obj.type)

        # Special handling for Array multi-index BEFORE generic type_methods
        # This handles arr[i, j] syntax for 2D arrays
        if type_name == "Array" and len(expr.indices) >= 2:
            row_idx = self.generate_expression(expr.indices[0])
            col_idx = self.generate_expression(expr.indices[1])
            row_idx = cg._cast_value(row_idx, ir.IntType(64))
            col_idx = cg._cast_value(col_idx, ir.IntType(64))

            elem_ptr = cg.builder.call(cg.array_get_2d, [obj, row_idx, col_idx])

            # Get element type from Coex type tracking
            elem_llvm_type = ir.IntType(64)  # default
            if isinstance(expr.object, Identifier):
                var_name = expr.object.name
                if var_name in cg.var_coex_types:
                    from ast_nodes import ArrayType
                    coex_type = cg.var_coex_types[var_name]
                    if isinstance(coex_type, ArrayType):
                        elem_llvm_type = cg._get_llvm_type(coex_type.element_type)

            typed_ptr = cg.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
            return cg.builder.load(typed_ptr)

        # Skip type_methods["get"] for JSON - JSON has specialized index handling below
        # that correctly dispatches between get_field (string key) and get_index (int index)
        if type_name and type_name in cg.type_methods and type_name != "Json":
            method_map = cg.type_methods[type_name]
            if "get" in method_map:
                mangled = method_map["get"]
                func = cg.functions[mangled]

                # Build args: self first, then indices (but only as many as function expects)
                args = [obj]
                for i, idx_expr in enumerate(expr.indices):
                    # Only add indices if function has matching parameters
                    if i + 1 >= len(func.args):
                        break
                    idx_val = self.generate_expression(idx_expr)
                    expected = func.args[i + 1].type
                    idx_val = cg._cast_value(idx_val, expected)
                    args.append(idx_val)

                result = cg.builder.call(func, args)

                # Special handling for List.get and Array.get - returns i8* that needs dereferencing
                if type_name == "List" or type_name == "Array":
                    # Get element type from Coex type tracking
                    elem_llvm_type = ir.IntType(64)  # default
                    elem_coex_type = None
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ListType, ArrayType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_coex_type = coex_type.element_type
                                elem_llvm_type = cg._get_llvm_type(elem_coex_type)
                    elif isinstance(expr.object, MemberExpr):
                        # Field access: obj.field[i] - look up field type
                        if isinstance(expr.object.object, Identifier):
                            obj_name = expr.object.object.name
                            if obj_name in cg.var_coex_types:
                                from ast_nodes import NamedType, ListType, ArrayType
                                obj_type = cg.var_coex_types[obj_name]
                                if hasattr(obj_type, 'name') and obj_type.name in cg.type_fields:
                                    for field_name, field_type in cg.type_fields[obj_type.name]:
                                        if field_name == expr.object.member:
                                            if isinstance(field_type, (ListType, ArrayType)):
                                                elem_coex_type = field_type.element_type
                                                elem_llvm_type = cg._get_llvm_type(elem_coex_type)
                                            break

                    # Check if TaggedValue mode is enabled (List only, not Array yet)
                    use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False) and type_name == "List"

                    if use_tagged:
                        # TaggedValue mode: result (i8*) points to TaggedValue {i64 type_id, i64 value}
                        tv_ptr = cg.builder.bitcast(result, cg.gc.tagged_value_ptr_type)
                        type_id, raw_value = cg.gc.extract_tagged_value(cg.builder, tv_ptr)

                        # Check if this is a heap reference (type_id >= TYPE_HEAP_BASE)
                        is_heap = cg.builder.icmp_unsigned('>=', type_id,
                            ir.Constant(ir.IntType(64), cg.gc.TYPE_HEAP_BASE))

                        # Create basic blocks for conditional handling
                        heap_bb = cg.builder.append_basic_block("listget_heap")
                        value_bb = cg.builder.append_basic_block("listget_value")
                        merge_bb = cg.builder.append_basic_block("listget_merge")

                        cg.builder.cbranch(is_heap, heap_bb, value_bb)

                        # Heap path: raw_value is a handle, dereference it
                        # Use runtime type_id to determine correct pointer type (fixes BUG-075)
                        cg.builder.position_at_end(heap_bb)
                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [raw_value])

                        # Switch on runtime type_id to get correct struct pointer type
                        # This handles deeply nested lists where compile-time inference fails
                        heap_list_bb = cg.builder.append_basic_block("listget_heap_list")
                        heap_string_bb = cg.builder.append_basic_block("listget_heap_string")
                        heap_map_bb = cg.builder.append_basic_block("listget_heap_map")
                        heap_set_bb = cg.builder.append_basic_block("listget_heap_set")
                        heap_array_bb = cg.builder.append_basic_block("listget_heap_array")
                        heap_default_bb = cg.builder.append_basic_block("listget_heap_default")
                        heap_merge_bb = cg.builder.append_basic_block("listget_heap_merge")

                        # Switch on type_id (TV_TYPE_* constants)
                        switch = cg.builder.switch(type_id, heap_default_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_LIST), heap_list_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_STRING), heap_string_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_MAP), heap_map_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_SET), heap_set_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_ARRAY), heap_array_bb)
                        # Other heap types (JSON, etc.) fall through to default

                        # Each type case: bitcast to correct struct pointer, then to i8*
                        # We use i8* as unified return type for heap objects
                        cg.builder.position_at_end(heap_list_bb)
                        list_ptr = cg.builder.bitcast(ptr_i8, cg.list_struct.as_pointer())
                        list_as_i8 = cg.builder.bitcast(list_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_string_bb)
                        str_ptr = cg.builder.bitcast(ptr_i8, cg.string_struct.as_pointer())
                        str_as_i8 = cg.builder.bitcast(str_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_map_bb)
                        map_ptr = cg.builder.bitcast(ptr_i8, cg.map_struct.as_pointer())
                        map_as_i8 = cg.builder.bitcast(map_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_set_bb)
                        set_ptr = cg.builder.bitcast(ptr_i8, cg.set_struct.as_pointer())
                        set_as_i8 = cg.builder.bitcast(set_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_array_bb)
                        arr_ptr = cg.builder.bitcast(ptr_i8, cg.array_struct.as_pointer())
                        arr_as_i8 = cg.builder.bitcast(arr_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_default_bb)
                        # Unknown heap type - return as i8*
                        cg.builder.branch(heap_merge_bb)

                        # Merge heap type cases
                        cg.builder.position_at_end(heap_merge_bb)
                        heap_phi = cg.builder.phi(ir.IntType(8).as_pointer(), "heap_typed_ptr")
                        heap_phi.add_incoming(list_as_i8, heap_list_bb)
                        heap_phi.add_incoming(str_as_i8, heap_string_bb)
                        heap_phi.add_incoming(map_as_i8, heap_map_bb)
                        heap_phi.add_incoming(set_as_i8, heap_set_bb)
                        heap_phi.add_incoming(arr_as_i8, heap_array_bb)
                        heap_phi.add_incoming(ptr_i8, heap_default_bb)

                        # Convert to final elem_llvm_type for outer merge
                        if isinstance(elem_llvm_type, ir.PointerType):
                            heap_result = cg.builder.bitcast(heap_phi, elem_llvm_type)
                        else:
                            # Compile-time thinks it's primitive but runtime says heap
                            # Return ptr as i64 - caller must handle this case
                            heap_result = cg.builder.ptrtoint(heap_phi, ir.IntType(64))
                            heap_result = self._from_i64_value(heap_result, elem_llvm_type)
                        cg.builder.branch(merge_bb)
                        heap_bb_final = cg.builder.block

                        # Value path: raw_value is the actual value
                        cg.builder.position_at_end(value_bb)
                        value_result = self._from_i64_value(raw_value, elem_llvm_type)
                        cg.builder.branch(merge_bb)
                        value_bb_final = cg.builder.block

                        # Merge
                        cg.builder.position_at_end(merge_bb)
                        phi = cg.builder.phi(elem_llvm_type, "listget_elem")
                        phi.add_incoming(heap_result, heap_bb_final)
                        phi.add_incoming(value_result, value_bb_final)
                        return phi
                    else:
                        # Legacy mode: element stored directly
                        typed_ptr = cg.builder.bitcast(result, elem_llvm_type.as_pointer())
                        return cg.builder.load(typed_ptr)

                return result

        index = self.generate_expression(expr.indices[0])

        # Check if this is an Array
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                # Array indexing
                # For N-D arrays:
                # - arr[i] on 1D array: returns element
                # - arr[i, j] on 2D array: returns element
                # - arr[i] on 2D array: returns row view (1D array)

                # Check if we have 2D indexing (multiple indices)
                if len(expr.indices) >= 2:
                    # 2D indexing with comma syntax: arr[row, col]
                    row_idx = self.generate_expression(expr.indices[0])
                    col_idx = self.generate_expression(expr.indices[1])
                    row_idx = cg._cast_value(row_idx, ir.IntType(64))
                    col_idx = cg._cast_value(col_idx, ir.IntType(64))

                    elem_ptr = cg.builder.call(cg.array_get_2d, [obj, row_idx, col_idx])

                    # Get element type from Coex type tracking
                    elem_llvm_type = ir.IntType(64)  # default
                    elem_coex_type_2d = None
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ArrayType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ArrayType):
                                elem_coex_type_2d = coex_type.element_type
                                elem_llvm_type = cg._get_llvm_type(elem_coex_type_2d)

                    # BUG-081 FIX: Arrays of reference types store handles, not raw pointers
                    is_ref_elem_2d = elem_coex_type_2d is not None and cg._is_reference_type(elem_coex_type_2d)
                    if is_ref_elem_2d:
                        # Load the handle (i64) from the array
                        handle_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
                        elem_handle = cg.builder.load(handle_ptr)
                        # Convert handle to pointer via gc_handle_deref
                        elem_i8 = cg.builder.call(cg.gc.gc_handle_deref, [elem_handle])
                        return cg.builder.bitcast(elem_i8, elem_llvm_type)
                    else:
                        typed_ptr = cg.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
                        return cg.builder.load(typed_ptr)

                # Single index - works for 1D arrays
                # For 2D arrays, could return row view but for now returns element at linear index
                if index.type != ir.IntType(64):
                    index = cg._cast_value(index, ir.IntType(64))

                elem_ptr = cg.builder.call(cg.array_get, [obj, index])

                # Get element type from Coex type tracking
                elem_llvm_type = ir.IntType(64)  # default
                elem_coex_type = None
                if isinstance(expr.object, Identifier):
                    var_name = expr.object.name
                    if var_name in cg.var_coex_types:
                        from ast_nodes import ArrayType
                        coex_type = cg.var_coex_types[var_name]
                        if isinstance(coex_type, ArrayType):
                            elem_coex_type = coex_type.element_type
                            elem_llvm_type = cg._get_llvm_type(elem_coex_type)

                # BUG-081 FIX: Arrays of reference types store handles, not raw pointers
                # We need to load the handle, then convert it to a pointer via gc_handle_deref
                is_ref_elem = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)
                if is_ref_elem:
                    # Load the handle (i64) from the array
                    handle_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
                    elem_handle = cg.builder.load(handle_ptr)
                    # Convert handle to pointer via gc_handle_deref
                    elem_i8 = cg.builder.call(cg.gc.gc_handle_deref, [elem_handle])
                    return cg.builder.bitcast(elem_i8, elem_llvm_type)
                else:
                    typed_ptr = cg.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
                    return cg.builder.load(typed_ptr)

        # Check if this is a List
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                # List indexing - call list_get and load the value
                # Ensure index is i64
                if index.type != ir.IntType(64):
                    index = cg._cast_value(index, ir.IntType(64))

                elem_ptr = cg.builder.call(cg.list_get, [obj, index])

                # Get element type from Coex type tracking (for type casting)
                elem_llvm_type = ir.IntType(64)  # default
                elem_coex_type = None
                if isinstance(expr.object, Identifier):
                    var_name = expr.object.name
                    if var_name in cg.var_coex_types:
                        from ast_nodes import ListType
                        coex_type = cg.var_coex_types[var_name]
                        if isinstance(coex_type, ListType):
                            elem_coex_type = coex_type.element_type
                            elem_llvm_type = cg._get_llvm_type(elem_coex_type)
                elif isinstance(expr.object, MemberExpr):
                    # Handle field access like call.param_values[0]
                    if isinstance(expr.object.object, Identifier):
                        obj_name = expr.object.object.name
                        if obj_name in cg.var_coex_types:
                            obj_type = cg.var_coex_types[obj_name]
                            if hasattr(obj_type, 'name') and obj_type.name in cg.type_fields:
                                for field_name, field_type in cg.type_fields[obj_type.name]:
                                    if field_name == expr.object.member:
                                        from ast_nodes import ListType
                                        if isinstance(field_type, ListType):
                                            elem_coex_type = field_type.element_type
                                            elem_llvm_type = cg._get_llvm_type(elem_coex_type)
                                        break

                # Check if TaggedValue mode is enabled
                use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False)

                if use_tagged:
                    # TaggedValue mode: elem_ptr points to TaggedValue {i64 type_id, i64 value}
                    tv_ptr = cg.builder.bitcast(elem_ptr, cg.gc.tagged_value_ptr_type)
                    type_id, raw_value = cg.gc.extract_tagged_value(cg.builder, tv_ptr)

                    # Check if this is a heap reference (type_id >= TYPE_HEAP_BASE)
                    is_heap = cg.builder.icmp_unsigned('>=', type_id,
                        ir.Constant(ir.IntType(64), cg.gc.TYPE_HEAP_BASE))

                    # Create basic blocks for conditional handling
                    heap_bb = cg.builder.append_basic_block("list_idx_heap")
                    value_bb = cg.builder.append_basic_block("list_idx_value")
                    merge_bb = cg.builder.append_basic_block("list_idx_merge")

                    cg.builder.cbranch(is_heap, heap_bb, value_bb)

                    # Heap path: raw_value is a handle, dereference it
                    cg.builder.position_at_end(heap_bb)
                    ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [raw_value])
                    # For pointer types: bitcast; for primitives: ptrtoint (never executed but must be valid IR)
                    if isinstance(elem_llvm_type, ir.PointerType):
                        heap_result = cg.builder.bitcast(ptr_i8, elem_llvm_type)
                    else:
                        # This branch won't be taken for primitives, but IR must be valid
                        heap_result = cg.builder.ptrtoint(ptr_i8, elem_llvm_type)
                    cg.builder.branch(merge_bb)
                    heap_bb_final = cg.builder.block

                    # Value path: raw_value is the actual value
                    cg.builder.position_at_end(value_bb)
                    value_result = self._from_i64_value(raw_value, elem_llvm_type)
                    cg.builder.branch(merge_bb)
                    value_bb_final = cg.builder.block

                    # Merge
                    cg.builder.position_at_end(merge_bb)
                    phi = cg.builder.phi(elem_llvm_type, "list_elem")
                    phi.add_incoming(heap_result, heap_bb_final)
                    phi.add_incoming(value_result, value_bb_final)
                    return phi
                else:
                    # Legacy mode: element is stored directly
                    # Reference types are stored as handles in lists - load and dereference
                    if elem_coex_type is not None and cg._is_reference_type(elem_coex_type):
                        # Load the handle (i64)
                        handle_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
                        handle = cg.builder.load(handle_ptr)
                        # Dereference handle to get pointer
                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [handle])
                        return cg.builder.bitcast(ptr_i8, elem_llvm_type)
                    else:
                        typed_ptr = cg.builder.bitcast(elem_ptr, elem_llvm_type.as_pointer())
                        return cg.builder.load(typed_ptr)

            # JSON indexing: j["key"] or j[0]
            if hasattr(pointee, 'name') and pointee.name == "struct.Json":
                # Determine index type
                index_coex_type = cg._infer_type_from_expr(expr.indices[0])
                from ast_nodes import PrimitiveType
                if isinstance(index_coex_type, PrimitiveType) and index_coex_type.name == "string":
                    # String key: call json_get_field
                    return cg.builder.call(cg.json_get_field, [obj, index])
                else:
                    # Integer index: call json_get_index
                    if index.type != ir.IntType(64):
                        index = cg._cast_value(index, ir.IntType(64))
                    return cg.builder.call(cg.json_get_index, [obj, index])

            # String indexing
            ptr = cg.builder.gep(obj, [index])
            return cg.builder.load(ptr)

        return ir.Constant(ir.IntType(64), 0)

    def generate_relative_index(self, expr: RelativeIndexExpr) -> ir.Value:
        """Generate code for relative indexing: arr[[offset]] or arr[[i, j]]

        Used in cellular automata formulas to access neighbors relative to
        the current position. Requires __ca_row__ and __ca_col__ (or __ca_pos__)
        variables to be set in the current scope.

        For 1D: arr[[offset]] accesses arr[__ca_pos__ + offset]
        For 2D: arr[[r, c]] accesses arr[__ca_row__ + r, __ca_col__ + c]
        """
        cg = self.cg
        builder = cg.builder
        i64 = ir.IntType(64)

        obj = self.generate_expression(expr.object)
        offsets = [self.generate_expression(off) for off in expr.offsets]

        # Ensure offsets are i64
        offsets = [cg._cast_value(off, i64) for off in offsets]

        if len(offsets) == 1:
            # 1D relative indexing: arr[[offset]]
            # Look for __ca_pos__ variable
            if "__ca_pos__" not in cg.locals:
                raise RuntimeError("Relative indexing [[]] requires __ca_pos__ variable. "
                                   "Use within a cellular automata context.")

            ca_pos_ptr = cg.locals["__ca_pos__"]
            ca_pos = builder.load(ca_pos_ptr)

            # Compute absolute index: __ca_pos__ + offset
            offset = offsets[0]
            abs_index = builder.add(ca_pos, offset)

            # Access element at absolute index
            elem_ptr = builder.call(cg.array_get, [obj, abs_index])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            return builder.load(elem_ptr_i64)

        elif len(offsets) == 2:
            # 2D relative indexing: arr[[row_off, col_off]]
            # Look for __ca_row__ and __ca_col__ variables
            if "__ca_row__" not in cg.locals or "__ca_col__" not in cg.locals:
                raise RuntimeError("2D relative indexing [[r, c]] requires __ca_row__ and "
                                   "__ca_col__ variables. Use within a cellular automata context.")

            ca_row_ptr = cg.locals["__ca_row__"]
            ca_col_ptr = cg.locals["__ca_col__"]
            ca_row = builder.load(ca_row_ptr)
            ca_col = builder.load(ca_col_ptr)

            # Compute absolute indices
            row_off, col_off = offsets
            abs_row = builder.add(ca_row, row_off)
            abs_col = builder.add(ca_col, col_off)

            # Access element at (abs_row, abs_col)
            elem_ptr = builder.call(cg.array_get_2d, [obj, abs_row, abs_col])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            return builder.load(elem_ptr_i64)

        else:
            raise RuntimeError(f"Relative indexing supports 1D or 2D offsets, got {len(offsets)}")

    def generate_slice(self, expr: SliceExpr) -> ir.Value:
        """Generate code for slice read: obj[start:end]

        Calls .getrange(start, end) on the object.
        Handles negative indices and omitted bounds.
        """
        cg = self.cg
        obj = self.generate_expression(expr.object)
        i64 = ir.IntType(64)

        # Get collection length for bounds normalization
        length = self.get_collection_length(obj)

        # Normalize start
        if expr.start is None:
            start = ir.Constant(i64, 0)
        else:
            start = self.generate_expression(expr.start)
            start = cg._cast_value(start, i64)
            start = self.normalize_slice_index(start, length)

        # Normalize end
        if expr.end is None:
            end = length
        else:
            end = self.generate_expression(expr.end)
            end = cg._cast_value(end, i64)
            end = self.normalize_slice_index(end, length)

        # Call getrange method
        type_name = cg._get_type_name_from_ptr(obj.type)
        if type_name and type_name in cg.type_methods:
            method_map = cg.type_methods[type_name]
            if "getrange" in method_map:
                mangled = method_map["getrange"]
                func = cg.functions[mangled]
                return cg.builder.call(func, [obj, start, end])

        # Fallback: check for direct list_getrange
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                return cg.builder.call(cg.list_getrange, [obj, start, end])
            elif hasattr(pointee, 'name') and pointee.name == "struct.String":
                return cg.builder.call(cg.string_getrange, [obj, start, end])

        raise RuntimeError(f"Type '{type_name}' does not support slice access (no getrange method)")

    def normalize_slice_index(self, index: ir.Value, length: ir.Value) -> ir.Value:
        """Normalize a slice index, handling negative values.

        If index < 0, returns length + index (i.e., -1 becomes length-1).
        """
        cg = self.cg
        i64 = ir.IntType(64)
        zero = ir.Constant(i64, 0)

        is_negative = cg.builder.icmp_signed("<", index, zero)
        normalized = cg.builder.add(length, index)

        return cg.builder.select(is_negative, normalized, index)

    def get_collection_length(self, obj: ir.Value) -> ir.Value:
        """Get the length of a collection for slice bounds normalization."""
        cg = self.cg
        type_name = cg._get_type_name_from_ptr(obj.type)

        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    return cg.builder.call(cg.list_len, [obj])
                elif pointee.name == "struct.String":
                    return cg.builder.call(cg.string_len, [obj])
                elif pointee.name == "struct.Array":
                    return cg.builder.call(cg.array_len, [obj])

        # Try type_methods lookup
        if type_name and type_name in cg.type_methods:
            if "len" in cg.type_methods[type_name]:
                mangled = cg.type_methods[type_name]["len"]
                func = cg.functions[mangled]
                return cg.builder.call(func, [obj])

        return ir.Constant(ir.IntType(64), 0)

    # ========================================================================
    # Pattern Binding
    # ========================================================================

    def bind_pattern(self, pattern, value):
        """Bind pattern variables to a value."""
        cg = self.cg

        if isinstance(pattern, str):
            # Simple string pattern (backward compat)
            alloca = cg.builder.alloca(value.type, name=pattern)
            cg.builder.store(value, alloca)
            cg.locals[pattern] = alloca

        elif isinstance(pattern, IdentifierPattern):
            alloca = cg.builder.alloca(value.type, name=pattern.name)
            cg.builder.store(value, alloca)
            cg.locals[pattern.name] = alloca

        elif isinstance(pattern, WildcardPattern):
            # Wildcard - don't bind anything
            pass

        elif isinstance(pattern, TuplePattern):
            # Destructure tuple
            # Assume value is a tuple struct or can be indexed
            for i, elem_pattern in enumerate(pattern.elements):
                if isinstance(value.type, ir.LiteralStructType):
                    elem_val = cg.builder.extract_value(value, i)
                else:
                    # For i64, treat high/low bits as elements (simplified)
                    elem_val = value
                self.bind_pattern(elem_pattern, elem_val)

    # ========================================================================
    # Function Call
    # ========================================================================

    def generate_call(self, expr: CallExpr) -> ir.Value:
        """Generate code for function call"""
        cg = self.cg

        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            explicit_type_args = expr.callee.type_args if hasattr(expr.callee, 'type_args') else []

            # Handle Array constructor specially: Array(capacity, initial_value)
            if name == "Array":
                return cg._generate_array_constructor(expr.args)

            # Check if this is a type constructor: Point(x: 1, y: 2)
            if name in cg.type_registry:
                return cg._generate_type_constructor(name, expr.args, expr.named_args)

            # Check if this is a generic type constructor
            if name in cg.generic_types:
                if explicit_type_args:
                    type_args = explicit_type_args
                else:
                    type_args = cg._infer_type_args_from_constructor(name, expr.args, expr.named_args)
                if type_args:
                    mangled_name = cg._monomorphize_type(name, type_args)
                    return cg._generate_type_constructor(mangled_name, expr.args, expr.named_args)

            # Check if this is an enum variant constructor
            enum_info = cg._find_enum_variant(name)
            if enum_info:
                enum_name, variant_name = enum_info
                return cg._generate_enum_constructor(enum_name, variant_name, expr.args, expr.named_args)

            # Built-in functions
            if name == "range":
                return ir.Constant(ir.IntType(64), 0)

            if name == "str":
                if expr.args:
                    return self.generate_expression(expr.args[0])
                return ir.Constant(ir.IntType(64), 0)

            if name == "int":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    if isinstance(val.type, ir.DoubleType):
                        return cg.builder.fptosi(val, ir.IntType(64))
                    return cg._cast_value(val, ir.IntType(64))
                return ir.Constant(ir.IntType(64), 0)

            if name == "float":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    if isinstance(val.type, ir.IntType):
                        return cg.builder.sitofp(val, ir.DoubleType())
                    return val
                return ir.Constant(ir.DoubleType(), 0.0)

            if name == "int32":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    if isinstance(val.type, ir.DoubleType):
                        return cg.builder.fptosi(val, ir.IntType(32))
                    if isinstance(val.type, ir.FloatType):
                        return cg.builder.fptosi(val, ir.IntType(32))
                    return cg._cast_value(val, ir.IntType(32))
                return ir.Constant(ir.IntType(32), 0)

            if name == "float32":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    if isinstance(val.type, ir.IntType):
                        return cg.builder.sitofp(val, ir.FloatType())
                    if isinstance(val.type, ir.DoubleType):
                        return cg.builder.fptrunc(val, ir.FloatType())
                    return val
                return ir.Constant(ir.FloatType(), 0.0)

            if name == "sqrt":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    return val
                return ir.Constant(ir.DoubleType(), 0.0)

            if name == "gc":
                # Trigger GC and wait for completion (synchronous)
                cg.builder.call(cg.gc.gc_async, [])
                cg.builder.call(cg.gc.gc_wait_for_completion, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_async":
                # Trigger GC via the background thread (non-blocking)
                # This will run collection asynchronously
                cg.builder.call(cg.gc.gc_async, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_stats":
                cg.builder.call(cg.gc.gc_dump_stats, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_heap":
                cg.builder.call(cg.gc.gc_dump_heap, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_roots":
                cg.builder.call(cg.gc.gc_dump_roots, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_validate_heap":
                result = cg.builder.call(cg.gc.gc_validate_heap, [])
                return result

            if name == "gc_set_trace_level":
                if expr.args:
                    level = self.generate_expression(expr.args[0])
                    if level.type != ir.IntType(64):
                        level = cg.builder.sext(level, ir.IntType(64))
                    cg.builder.call(cg.gc.gc_set_trace_level, [level])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_fragmentation_report":
                cg.builder.call(cg.gc.gc_fragmentation_report, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_handle_table":
                cg.builder.call(cg.gc.gc_dump_handle_table, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_dump_shadow_stacks":
                cg.builder.call(cg.gc.gc_dump_shadow_stacks, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "gc_validate_handle_storage":
                # Debug function to validate handle storage invariant
                # Returns count of violations (values that look like pointers, not handles)
                result = cg.builder.call(cg.gc.gc_validate_handle_storage, [])
                return result

            if name == "gc_compact":
                # Trigger compaction via the background GC thread (non-blocking).
                # gc_compact only sets flags and signals; actual compaction
                # happens in the GC thread. No reload needed since compaction
                # hasn't happened yet when this returns.
                cg.builder.call(cg.gc.gc_compact, [])
                return ir.Constant(ir.IntType(64), 0)

            if name == "print":
                if expr.args:
                    value = self.generate_expression(expr.args[0])

                    if isinstance(value.type, ir.IntType):
                        if value.type.width == 1:
                            # Boolean
                            true_block = cg.builder.append_basic_block("print_true")
                            false_block = cg.builder.append_basic_block("print_false")
                            merge_block = cg.builder.append_basic_block("print_merge")

                            cg.builder.cbranch(value, true_block, false_block)

                            cg.builder.position_at_end(true_block)
                            fmt_ptr = cg.builder.bitcast(cg._true_str, ir.IntType(8).as_pointer())
                            cg.builder.call(cg.printf, [fmt_ptr])
                            cg.builder.branch(merge_block)

                            cg.builder.position_at_end(false_block)
                            fmt_ptr = cg.builder.bitcast(cg._false_str, ir.IntType(8).as_pointer())
                            cg.builder.call(cg.printf, [fmt_ptr])
                            cg.builder.branch(merge_block)

                            cg.builder.position_at_end(merge_block)
                        else:
                            # Integer
                            fmt_ptr = cg.builder.bitcast(cg._int_fmt, ir.IntType(8).as_pointer())
                            if value.type.width < 64:
                                value = cg.builder.sext(value, ir.IntType(64))
                            cg.builder.call(cg.printf, [fmt_ptr, value])

                    elif isinstance(value.type, ir.DoubleType):
                        fmt_ptr = cg.builder.bitcast(cg._float_fmt, ir.IntType(8).as_pointer())
                        cg.builder.call(cg.printf, [fmt_ptr, value])

                    elif isinstance(value.type, ir.FloatType):
                        # float32 - extend to double for printf
                        value64 = cg.builder.fpext(value, ir.DoubleType())
                        fmt_ptr = cg.builder.bitcast(cg._float_fmt, ir.IntType(8).as_pointer())
                        cg.builder.call(cg.printf, [fmt_ptr, value64])

                    elif isinstance(value.type, ir.PointerType):
                        pointee = value.type.pointee
                        if hasattr(pointee, 'name') and pointee.name == "struct.String":
                            cg.builder.call(cg.string_print, [value])
                        else:
                            fmt_ptr = cg.builder.bitcast(cg._str_fmt, ir.IntType(8).as_pointer())
                            cg.builder.call(cg.printf, [fmt_ptr, value])

                    # Flush stdout
                    null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
                    cg.builder.call(cg.fflush, [null_ptr])

                return ir.Constant(ir.IntType(64), 0)

            # Check for replace alias
            if name in cg.replace_aliases:
                module_name, qualified_name = cg.replace_aliases[name]
                module_info = cg.loaded_modules[module_name]
                if qualified_name in module_info.functions:
                    mangled = module_info.functions[qualified_name]
                    func = cg.functions[mangled]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self.generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
                            arg_val = cg._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return cg.builder.call(func, args)
                else:
                    raise RuntimeError(f"Function '{qualified_name}' not found in module '{module_name}'")

            # Check if this is an extern function call
            extern_decls = getattr(cg, 'extern_function_decls', {})
            if name in extern_decls:
                return cg._generate_extern_call(name, expr.args, extern_decls[name])

            # Look up function
            if name in cg.functions:
                func = cg.functions[name]

                # Check function kind hierarchy
                if name in cg.func_decls:
                    func_decl = cg.func_decls[name]
                    # KindFunctionDecl doesn't have a kind - it uses user-defined kinds
                    if not isinstance(func_decl, KindFunctionDecl):
                        callee_kind = func_decl.kind
                        self._check_function_kind_hierarchy(name, callee_kind)

                # Check if this is a thread function call
                if name in cg.func_decls:
                    func_decl = cg.func_decls[name]
                    if not isinstance(func_decl, KindFunctionDecl) and func_decl.kind == FunctionKind.THREAD:
                        return self._generate_thread_call(name, func, expr.args)

                # Check if this is a task function call
                if name in cg.func_decls:
                    func_decl = cg.func_decls[name]
                    if not isinstance(func_decl, KindFunctionDecl) and func_decl.kind == FunctionKind.TASK:
                        return self._generate_task_call(name, func, expr.args)

                args = []
                func_decl = cg.func_decls.get(name)
                for i, arg in enumerate(expr.args):
                    arg_val = self.generate_expression(arg)
                    # Try implicit collection conversion if we have parameter type info
                    if func_decl:
                        arg_val = self._convert_function_arg_if_needed(arg_val, i, func_decl)
                    if i < len(func.args):
                        expected = func.args[i].type
                        arg_val = cg._cast_value(arg_val, expected)
                    args.append(arg_val)
                return cg.builder.call(func, args)

            # Check for generic function
            if name in cg.generic_functions:
                if explicit_type_args:
                    type_args = explicit_type_args
                else:
                    type_args = cg._infer_type_args(name, expr.args)
                if type_args:
                    mangled = cg._monomorphize_function(name, type_args)
                    func = cg.functions[mangled]
                    func_decl = cg.generic_functions[name]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self.generate_expression(arg)
                        # Try implicit collection conversion if we have parameter type info
                        if func_decl:
                            arg_val = self._convert_function_arg_if_needed(arg_val, i, func_decl)
                        if i < len(func.args):
                            expected = func.args[i].type
                            arg_val = cg._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return cg.builder.call(func, args)

        elif isinstance(expr.callee, MemberExpr):
            # Check for module-qualified call: module.function(args)
            if isinstance(expr.callee.object, Identifier):
                possible_module = expr.callee.object.name
                func_name = expr.callee.member

                # Check if this is a loaded module
                if possible_module in cg.loaded_modules:
                    module_info = cg.loaded_modules[possible_module]
                    if func_name in module_info.functions:
                        mangled = module_info.functions[func_name]
                        func = cg.functions[mangled]
                        func_decl = cg.func_decls.get(mangled)
                        args = []
                        for i, arg in enumerate(expr.args):
                            arg_val = self.generate_expression(arg)
                            # Try implicit collection conversion if we have parameter type info
                            if func_decl:
                                arg_val = self._convert_function_arg_if_needed(arg_val, i, func_decl)
                            if i < len(func.args):
                                expected = func.args[i].type
                                arg_val = cg._cast_value(arg_val, expected)
                            args.append(arg_val)
                        return cg.builder.call(func, args)
                    else:
                        raise RuntimeError(f"Function '{func_name}' not found in module '{possible_module}'")

            # Check for Type.new() pattern
            if isinstance(expr.callee.object, Identifier):
                type_name = expr.callee.object.name
                if type_name in cg.type_registry and expr.callee.member == "new":
                    return cg._generate_type_new(type_name, expr.args)

                # Check for EnumType.VariantName(args) pattern
                if type_name in cg.enum_variants:
                    variant_name = expr.callee.member
                    if variant_name in cg.enum_variants[type_name]:
                        return cg._generate_enum_constructor(type_name, variant_name, expr.args, expr.named_args)

            # Static method call: Type.method()
            return self.generate_method_call(MethodCallExpr(
                expr.callee.object, expr.callee.member, expr.args))

        # If we get here with an Identifier callee, check if it's a function pointer in locals
        if isinstance(expr.callee, Identifier):
            name = expr.callee.name
            if name in cg.locals:
                ptr = cg.locals[name]
                func_ptr = cg.builder.load(ptr)

                if isinstance(func_ptr.type, ir.PointerType) and isinstance(func_ptr.type.pointee, ir.FunctionType):
                    args = []
                    for arg in expr.args:
                        arg_val = self.generate_expression(arg)
                        args.append(arg_val)
                    return cg.builder.call(func_ptr, args)

                if isinstance(func_ptr.type, ir.FunctionType):
                    args = []
                    for arg in expr.args:
                        arg_val = self.generate_expression(arg)
                        args.append(arg_val)
                    return cg.builder.call(func_ptr, args)

        return ir.Constant(ir.IntType(64), 0)

    # ========================================================================
    # Implicit Collection Conversion for Function Arguments
    # ========================================================================

    def _convert_function_arg_if_needed(self, arg_val: ir.Value, param_idx: int,
                                        func_decl: FunctionDecl) -> ir.Value:
        """Try implicit collection conversion for a function argument.

        If the expected parameter type is a collection type (List, Array, Set)
        and the argument is a different collection type, perform implicit conversion
        and emit a compiler warning.

        Args:
            arg_val: The LLVM value of the argument
            param_idx: Index of the parameter in the function declaration
            func_decl: The AST function declaration containing parameter types

        Returns:
            The (possibly converted) argument value
        """
        cg = self.cg

        # Check if we have parameter type info
        if param_idx >= len(func_decl.params):
            return arg_val

        param = func_decl.params[param_idx]
        expected_type = param.type_annotation

        # Only try conversion for collection types
        if not isinstance(expected_type, (ListType, ArrayType, SetType)):
            return arg_val

        # Try implicit collection conversion
        converted_value, was_converted = cg._try_implicit_collection_conversion(
            arg_val, expected_type
        )

        if was_converted:
            # Get source struct name for warning message
            source_struct = "unknown"
            if isinstance(arg_val.type, ir.PointerType) and hasattr(arg_val.type.pointee, 'name'):
                source_struct = arg_val.type.pointee.name

            # Determine target struct name
            if isinstance(expected_type, ListType):
                target_struct = "struct.List"
            elif isinstance(expected_type, ArrayType):
                target_struct = "struct.Array"
            else:
                target_struct = "struct.Set"

            warning_msg = cg._get_conversion_warning_message(source_struct, target_struct)
            cg._emit_warning("PERF", f"Parameter '{param.name}': {warning_msg}")
            return converted_value

        return arg_val

    # ========================================================================
    # Function Kind Hierarchy Check
    # ========================================================================

    def _check_function_kind_hierarchy(self, callee_name: str, callee_kind: FunctionKind):
        """Check that the function call respects the kind hierarchy.

        Hierarchy (lighter to heavier):
            formula -> can only call formula
            task    -> can call formula, task
            thread  -> can call formula, task, thread
            func    -> can call formula, task, thread, func

        Raises RuntimeError if the hierarchy is violated.
        """
        cg = self.cg

        if not hasattr(cg, 'current_function') or not cg.current_function:
            return  # Not in a function context

        caller_kind = cg.current_function.kind
        caller_name = cg.current_function.name

        # Define what each kind can call
        # Key = caller kind, Value = set of allowed callee kinds
        allowed = {
            FunctionKind.FORMULA: {FunctionKind.FORMULA},
            FunctionKind.TASK: {FunctionKind.FORMULA, FunctionKind.TASK},
            FunctionKind.THREAD: {FunctionKind.FORMULA, FunctionKind.TASK, FunctionKind.THREAD},
            FunctionKind.FUNC: {FunctionKind.FORMULA, FunctionKind.TASK, FunctionKind.THREAD, FunctionKind.FUNC},
            FunctionKind.EXTERN: set(),  # extern can't call anything (it's a declaration)
        }

        if caller_kind in allowed:
            if callee_kind not in allowed[caller_kind]:
                raise RuntimeError(
                    f"Cannot call {callee_kind.name.lower()} '{callee_name}' from "
                    f"{caller_kind.name.lower()} '{caller_name}'. "
                    f"{caller_kind.name.lower()} can only call: "
                    f"{', '.join(k.name.lower() for k in sorted(allowed[caller_kind], key=lambda x: x.value))}."
                )

    # ========================================================================
    # Thread Call
    # ========================================================================

    def _generate_thread_call(self, name: str, func: ir.Function,
                              args: PyList) -> ir.Value:
        """Generate code for a thread function call with := assignment.

        This is the BLOCKING call path used when a thread result is assigned
        with the := operator. It spawns the thread, joins immediately, and
        returns the result. This is the correct behavior for sequential
        execution where the result is needed.

        For fire-and-forget (bare call without assignment), see
        StatementGenerator._generate_fire_and_forget_call() which adds
        to nursery for deferred join at function exit.

        Args:
            name: Thread function name
            func: LLVM function for the thread
            args: List of argument expressions

        Returns:
            Result from the task
        """
        cg = self.cg
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get task function declaration
        task_decl = cg.func_decls[name]

        # Evaluate arguments
        arg_values = []
        for i, arg in enumerate(args):
            arg_val = self.generate_expression(arg)
            if i < len(func.args):
                expected = func.args[i].type
                arg_val = cg._cast_value(arg_val, expected)
            arg_values.append(arg_val)

        # Spawn the task using TaskGenerator
        thread_handle, closure_ptr = cg._thread.spawn_task(
            cg.builder,
            task_decl,
            func,
            arg_values,
            add_to_nursery=False  # We'll join immediately
        )

        # Join immediately (synchronous execution for now)
        cg.builder.call(cg._thread.task_join, [thread_handle])

        # Extract result from closure
        result_field = cg.builder.gep(
            closure_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True,
            name="result_field"
        )
        result_ptr = cg.builder.load(result_field, name="result_ptr")

        # Convert result back to expected type
        result = cg.builder.ptrtoint(result_ptr, i64, name="result")

        # Free the closure
        cg.builder.call(cg._thread.closure_free, [closure_ptr])

        return result

    def _generate_task_call(self, name: str, func: ir.Function,
                            args: PyList) -> ir.Value:
        """Generate code for a task function call (lightweight coroutine).

        Task calls go through the work-stealing scheduler. For now, this
        executes synchronously via spawn_and_wait, but the scheduler
        infrastructure enables future concurrent execution.

        Args:
            name: Task function name
            func: LLVM function for the task
            args: List of argument expressions

        Returns:
            Result from the task
        """
        cg = self.cg

        # Evaluate arguments
        arg_values = []
        for i, arg in enumerate(args):
            arg_val = self.generate_expression(arg)
            if i < len(func.args):
                expected = func.args[i].type
                arg_val = cg._cast_value(arg_val, expected)
            arg_values.append(arg_val)

        # Use the task transformer to generate the call
        return cg._task.generate_task_call(name, arg_values, cg.builder)

    # ========================================================================
    # Method Call
    # ========================================================================

    def generate_method_call(self, expr: MethodCallExpr) -> ir.Value:
        """Generate code for method call"""
        cg = self.cg

        # Check if this is a call on a type identifier (static method)
        if isinstance(expr.object, Identifier):
            type_name = expr.object.name

            # Handle json static methods (json is primitive, not in type_registry)
            if type_name == "json":
                if expr.method == "parse" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    return cg.builder.call(cg.json_parse, [arg_val])
                elif expr.method == "new_null":
                    return cg.builder.call(cg.json_new_null, [])
                elif expr.method == "new_bool" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    arg_val = cg._cast_value(arg_val, ir.IntType(1))
                    return cg.builder.call(cg.json_new_bool, [arg_val])
                elif expr.method == "new_int" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    arg_val = cg._cast_value(arg_val, ir.IntType(64))
                    return cg.builder.call(cg.json_new_int, [arg_val])
                elif expr.method == "new_float" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    arg_val = cg._cast_value(arg_val, ir.DoubleType())
                    return cg.builder.call(cg.json_new_float, [arg_val])
                elif expr.method == "new_string" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    return cg.builder.call(cg.json_new_string, [arg_val])
                elif expr.method == "new_array":
                    return cg.builder.call(cg.json_new_array_empty, [])
                elif expr.method == "new_object":
                    return cg.builder.call(cg.json_new_object_empty, [])

            if type_name in cg.type_registry:
                # Static method call: Type.method()
                if expr.method == "new":
                    return cg._generate_type_new(type_name, expr.args)

                # Special handling for String.from()
                if type_name == "String" and expr.method == "from" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    arg_type = arg_val.type

                    if isinstance(arg_type, ir.IntType):
                        if arg_type.width == 1:
                            return cg.builder.call(cg.string_from_bool, [arg_val])
                        else:
                            arg_val = cg._cast_value(arg_val, ir.IntType(64))
                            return cg.builder.call(cg.string_from_int, [arg_val])
                    elif isinstance(arg_type, ir.DoubleType):
                        return cg.builder.call(cg.string_from_float, [arg_val])
                    elif isinstance(arg_type, ir.PointerType):
                        # Check if it's a json pointer - use json_to_string (returns raw value, no quotes)
                        if hasattr(cg, 'json_struct') and arg_type.pointee == cg.json_struct:
                            return cg.builder.call(cg.json_to_string, [arg_val])
                        # Other pointer types - fallback to int
                        arg_val = cg._cast_value(arg_val, ir.IntType(64))
                        return cg.builder.call(cg.string_from_int, [arg_val])
                    else:
                        arg_val = cg._cast_value(arg_val, ir.IntType(64))
                        return cg.builder.call(cg.string_from_int, [arg_val])

                # Special handling for String.from_bytes()
                if type_name == "String" and expr.method == "from_bytes" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    if isinstance(arg_val.type, ir.PointerType):
                        return cg.builder.call(cg.string_from_bytes, [arg_val])
                    return cg.builder.call(cg.string_from_literal, [cg._get_string_literal("")])

                # Special handling for Array.zeros(size)
                # Creates a zero-initialized array of `size` elements
                if type_name == "Array" and expr.method == "zeros" and len(expr.args) >= 1:
                    size_val = self.generate_expression(expr.args[0])
                    size_val = cg._cast_value(size_val, ir.IntType(64))
                    elem_size = ir.Constant(ir.IntType(64), 8)  # default to i64 elements
                    # array_new initializes to zero via GC allocator
                    return cg.builder.call(cg.array_new, [size_val, elem_size])

                # Special handling for Array.fill(size, value)
                # Creates an array of `size` elements, all initialized to `value`
                if type_name == "Array" and expr.method == "fill" and len(expr.args) == 2:
                    size_val = self.generate_expression(expr.args[0])
                    size_val = cg._cast_value(size_val, ir.IntType(64))
                    fill_val = self.generate_expression(expr.args[1])

                    # Determine element size based on fill value type
                    if isinstance(fill_val.type, ir.IntType):
                        if fill_val.type.width == 1:
                            elem_size = ir.Constant(ir.IntType(64), 1)  # bool = 1 byte
                        elif fill_val.type.width == 32:
                            elem_size = ir.Constant(ir.IntType(64), 4)  # int32 = 4 bytes
                        else:
                            elem_size = ir.Constant(ir.IntType(64), 8)  # int = 8 bytes
                    elif isinstance(fill_val.type, ir.FloatType):
                        elem_size = ir.Constant(ir.IntType(64), 4)  # float32 = 4 bytes
                    elif isinstance(fill_val.type, ir.DoubleType):
                        elem_size = ir.Constant(ir.IntType(64), 8)  # float = 8 bytes
                    elif isinstance(fill_val.type, ir.PointerType):
                        elem_size = ir.Constant(ir.IntType(64), 8)  # pointer = 8 bytes
                    else:
                        elem_size = ir.Constant(ir.IntType(64), 8)  # default

                    # Allocate the array
                    array_ptr = cg.builder.call(cg.array_new, [size_val, elem_size])

                    # Get data pointer: handle (field 0) + offset (field 4)
                    handle_ptr = cg.builder.gep(array_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), 0)
                    ], inbounds=True)
                    handle = cg.builder.load(handle_ptr)
                    base_ptr = cg.builder.inttoptr(handle, ir.IntType(8).as_pointer())
                    offset_ptr = cg.builder.gep(array_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), 4)
                    ], inbounds=True)
                    offset = cg.builder.load(offset_ptr)
                    data_ptr = cg.builder.gep(base_ptr, [offset])

                    # Fill loop
                    func = cg.builder.function
                    idx_alloca = cg.builder.alloca(ir.IntType(64), name="fill_idx")
                    cg.builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)

                    cond_bb = func.append_basic_block("fill_cond")
                    body_bb = func.append_basic_block("fill_body")
                    end_bb = func.append_basic_block("fill_end")

                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(cond_bb)
                    idx = cg.builder.load(idx_alloca)
                    done = cg.builder.icmp_unsigned(">=", idx, size_val)
                    cg.builder.cbranch(done, end_bb, body_bb)

                    cg.builder.position_at_end(body_bb)
                    idx = cg.builder.load(idx_alloca)
                    elem_offset = cg.builder.mul(idx, elem_size)
                    elem_ptr = cg.builder.gep(data_ptr, [elem_offset])

                    # Store value based on type
                    if isinstance(fill_val.type, ir.IntType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, fill_val.type.as_pointer())
                        cg.builder.store(fill_val, typed_ptr)
                    elif isinstance(fill_val.type, ir.FloatType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, ir.FloatType().as_pointer())
                        cg.builder.store(fill_val, typed_ptr)
                    elif isinstance(fill_val.type, ir.DoubleType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, ir.DoubleType().as_pointer())
                        cg.builder.store(fill_val, typed_ptr)
                    elif isinstance(fill_val.type, ir.PointerType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, fill_val.type.as_pointer())
                        cg.builder.store(fill_val, typed_ptr)

                    next_idx = cg.builder.add(idx, ir.Constant(ir.IntType(64), 1))
                    cg.builder.store(next_idx, idx_alloca)
                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(end_bb)
                    return array_ptr

                # Legacy alias: Array.filled -> Array.fill
                if type_name == "Array" and expr.method == "filled" and len(expr.args) == 2:
                    size_val = self.generate_expression(expr.args[0])
                    size_val = cg._cast_value(size_val, ir.IntType(64))
                    fill_val = self.generate_expression(expr.args[1])
                    elem_size = ir.Constant(ir.IntType(64), 8)
                    array_ptr = cg.builder.call(cg.array_new, [size_val, elem_size])

                    # Get data pointer
                    handle_ptr = cg.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
                    handle = cg.builder.load(handle_ptr)
                    base_ptr = cg.builder.inttoptr(handle, ir.IntType(8).as_pointer())
                    offset_ptr = cg.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 4)], inbounds=True)
                    offset = cg.builder.load(offset_ptr)
                    data_ptr = cg.builder.gep(base_ptr, [offset])

                    # Fill loop
                    func = cg.builder.function
                    idx_alloca = cg.builder.alloca(ir.IntType(64), name="filled_idx")
                    cg.builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)

                    cond_bb = func.append_basic_block("filled_cond")
                    body_bb = func.append_basic_block("filled_body")
                    end_bb = func.append_basic_block("filled_end")

                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(cond_bb)
                    idx = cg.builder.load(idx_alloca)
                    done = cg.builder.icmp_unsigned(">=", idx, size_val)
                    cg.builder.cbranch(done, end_bb, body_bb)

                    cg.builder.position_at_end(body_bb)
                    idx = cg.builder.load(idx_alloca)
                    elem_offset = cg.builder.mul(idx, elem_size)
                    elem_ptr = cg.builder.gep(data_ptr, [elem_offset])

                    if isinstance(fill_val.type, ir.IntType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, fill_val.type.as_pointer())
                        cg.builder.store(fill_val, typed_ptr)
                    elif isinstance(fill_val.type, ir.DoubleType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, ir.DoubleType().as_pointer())
                        cg.builder.store(fill_val, typed_ptr)
                    elif isinstance(fill_val.type, ir.PointerType):
                        typed_ptr = cg.builder.bitcast(elem_ptr, fill_val.type.as_pointer())
                        cg.builder.store(fill_val, typed_ptr)

                    next_idx = cg.builder.add(idx, ir.Constant(ir.IntType(64), 1))
                    cg.builder.store(next_idx, idx_alloca)
                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(end_bb)
                    return array_ptr

                # Special handling for Array.identity(n)
                # Creates an n x n identity matrix (2D array with 1s on diagonal)
                if type_name == "Array" and expr.method == "identity" and len(expr.args) == 1:
                    n_val = self.generate_expression(expr.args[0])
                    n_val = cg._cast_value(n_val, ir.IntType(64))
                    elem_size = ir.Constant(ir.IntType(64), 8)  # i64/f64 elements

                    # Create 2D array
                    array_ptr = cg.builder.call(cg.array_new_2d, [n_val, n_val, elem_size])

                    # Get data pointer
                    handle_ptr = cg.builder.gep(array_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)], inbounds=True)
                    handle = cg.builder.load(handle_ptr)
                    data_ptr = cg.builder.inttoptr(handle, ir.IntType(8).as_pointer())

                    # Fill diagonal with 1s using a loop
                    func = cg.builder.function
                    idx_alloca = cg.builder.alloca(ir.IntType(64), name="ident_idx")
                    cg.builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)

                    cond_bb = func.append_basic_block("ident_cond")
                    body_bb = func.append_basic_block("ident_body")
                    end_bb = func.append_basic_block("ident_end")

                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(cond_bb)
                    idx = cg.builder.load(idx_alloca)
                    done = cg.builder.icmp_unsigned(">=", idx, n_val)
                    cg.builder.cbranch(done, end_bb, body_bb)

                    cg.builder.position_at_end(body_bb)
                    idx = cg.builder.load(idx_alloca)
                    # Calculate offset: (idx * n + idx) * elem_size = idx * (n + 1) * elem_size
                    n_plus_1 = cg.builder.add(n_val, ir.Constant(ir.IntType(64), 1))
                    diag_idx = cg.builder.mul(idx, n_plus_1)
                    elem_offset = cg.builder.mul(diag_idx, elem_size)
                    elem_ptr = cg.builder.gep(data_ptr, [elem_offset])
                    typed_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
                    cg.builder.store(ir.Constant(ir.IntType(64), 1), typed_ptr)

                    next_idx = cg.builder.add(idx, ir.Constant(ir.IntType(64), 1))
                    cg.builder.store(next_idx, idx_alloca)
                    cg.builder.branch(cond_bb)

                    cg.builder.position_at_end(end_bb)
                    return array_ptr

                # Special handling for Array.zeros_2d(rows, cols)
                # Creates a 2D zero-initialized array
                if type_name == "Array" and expr.method == "zeros_2d" and len(expr.args) == 2:
                    rows = self.generate_expression(expr.args[0])
                    rows = cg._cast_value(rows, ir.IntType(64))
                    cols = self.generate_expression(expr.args[1])
                    cols = cg._cast_value(cols, ir.IntType(64))
                    elem_size = ir.Constant(ir.IntType(64), 8)
                    # array_new_2d initializes to zero via GC allocator
                    return cg.builder.call(cg.array_new_2d, [rows, cols, elem_size])

                # Look for static methods (factory methods)
                mangled = f"{type_name}_{expr.method}"
                if mangled in cg.functions:
                    func = cg.functions[mangled]
                    is_result_constructor = (type_name == "Result" and expr.method in ("ok", "err"))
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self.generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
                            # For Result.ok/err with reference type arguments,
                            # convert pointer to GC handle instead of raw ptrtoint
                            if (is_result_constructor and
                                isinstance(arg_val.type, ir.PointerType) and
                                isinstance(expected, ir.IntType) and
                                cg.gc is not None):
                                i8_ptr = ir.IntType(8).as_pointer()
                                val_i8 = cg.builder.bitcast(arg_val, i8_ptr)
                                val_promoted = cg.builder.call(cg.gc.gc_promote_to_heap, [val_i8])
                                arg_val = cg.builder.call(cg.gc.gc_ptr_to_handle, [val_promoted])
                            else:
                                arg_val = cg._cast_value(arg_val, expected)
                        args.append(arg_val)
                    return cg.builder.call(func, args)

        # Handle atomic primitive methods (atomic_int, atomic_float, atomic_bool)
        # Check BEFORE generating expression, because we need the pointer, not the loaded value
        if isinstance(expr.object, Identifier):
            var_name = expr.object.name
            if var_name in cg.var_coex_types:
                coex_type = cg.var_coex_types[var_name]
                if isinstance(coex_type, AtomicType):
                    # Formula purity check: formulas cannot use atomic operations
                    if hasattr(cg, 'current_function') and cg.current_function:
                        if cg.current_function.kind == FunctionKind.FORMULA:
                            raise RuntimeError(
                                f"Cannot use atomic operations in formula '{cg.current_function.name}'. "
                                f"Formulas must be pure and cannot use mutable atomic state."
                            )

                    atomic_inner_type = coex_type.inner
                    if var_name in cg.locals:
                        atomic_ptr = cg.locals[var_name]
                        method = expr.method

                        # Atomic primitive method dispatch
                        if method == "load":
                            return cg._atomic_primitives.generate_atomic_load(
                                cg.builder, atomic_ptr, atomic_inner_type)

                        elif method == "store":
                            if expr.args:
                                value = self.generate_expression(expr.args[0])
                                return cg._atomic_primitives.generate_atomic_store(
                                    cg.builder, atomic_ptr, value, atomic_inner_type)
                            return ir.Constant(ir.IntType(64), 0)

                        elif method == "exchange":
                            if expr.args:
                                new_value = self.generate_expression(expr.args[0])
                                return cg._atomic_primitives.generate_atomic_exchange(
                                    cg.builder, atomic_ptr, new_value, atomic_inner_type)
                            return ir.Constant(ir.IntType(64), 0)

                        elif method == "compare_and_swap" or method == "cas":
                            if len(expr.args) >= 2:
                                expected = self.generate_expression(expr.args[0])
                                new_value = self.generate_expression(expr.args[1])
                                return cg._atomic_primitives.generate_atomic_cas(
                                    cg.builder, atomic_ptr, expected, new_value, atomic_inner_type)
                            return ir.Constant(ir.IntType(1), 0)

                        elif method == "fetch_add" and atomic_inner_type == "int":
                            if expr.args:
                                delta = self.generate_expression(expr.args[0])
                                return cg._atomic_primitives.generate_fetch_add(
                                    cg.builder, atomic_ptr, delta)
                            return ir.Constant(ir.IntType(64), 0)

                        elif method == "fetch_sub" and atomic_inner_type == "int":
                            if expr.args:
                                delta = self.generate_expression(expr.args[0])
                                return cg._atomic_primitives.generate_fetch_sub(
                                    cg.builder, atomic_ptr, delta)
                            return ir.Constant(ir.IntType(64), 0)

                        elif method == "increment" and atomic_inner_type == "int":
                            return cg._atomic_primitives.generate_increment(
                                cg.builder, atomic_ptr)

                        elif method == "decrement" and atomic_inner_type == "int":
                            return cg._atomic_primitives.generate_decrement(
                                cg.builder, atomic_ptr)

                        elif method == "test_and_set" and atomic_inner_type == "bool":
                            return cg._atomic_primitives.generate_test_and_set(
                                cg.builder, atomic_ptr)

                        else:
                            raise RuntimeError(f"Undefined method '{method}' on atomic_{atomic_inner_type}")

        # Instance method call: obj.method()
        obj = self.generate_expression(expr.object)
        method = expr.method

        # Try to determine the type from the pointer
        type_name = cg._get_type_name_from_ptr(obj.type)

        # Special handling for Map with string keys
        if type_name == "Map" and method in ("get", "has", "set", "remove") and expr.args:
            key_arg = self.generate_expression(expr.args[0])
            is_string_key = (isinstance(key_arg.type, ir.PointerType) and
                            hasattr(key_arg.type.pointee, 'name') and
                            key_arg.type.pointee.name == "struct.String")

            if is_string_key:
                if method == "get":
                    result = cg.builder.call(cg.map_get_string, [obj, key_arg])
                    # Convert result to proper type if value is a reference type
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import MapType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_coex_type = coex_type.value_type
                                value_llvm_type = cg._get_llvm_type(value_coex_type)
                                if isinstance(value_llvm_type, ir.PointerType):
                                    # Reference types are stored as handles - dereference
                                    if cg._is_reference_type(value_coex_type):
                                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [result])
                                        return cg.builder.bitcast(ptr_i8, value_llvm_type)
                                    else:
                                        return cg.builder.inttoptr(result, value_llvm_type)
                    return result
                elif method == "has":
                    return cg.builder.call(cg.map_has_string, [obj, key_arg])
                elif method == "set":
                    value_arg = self.generate_expression(expr.args[1])
                    # Check if value is a reference type - if so, store handle instead of pointer
                    value_coex_type = cg._infer_type_from_expr(expr.args[1])
                    if value_coex_type is not None and cg._is_reference_type(value_coex_type):
                        # Convert pointer to handle for storage
                        value_i8 = cg.builder.bitcast(value_arg, ir.IntType(8).as_pointer())
                        value_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
                        return cg.builder.call(cg.map_set_string, [obj, key_arg, value_handle])
                    else:
                        value_i64 = cg._cast_value(value_arg, ir.IntType(64))
                        return cg.builder.call(cg.map_set_string, [obj, key_arg, value_i64])
                elif method == "remove":
                    return cg.builder.call(cg.map_remove_string, [obj, key_arg])

        # Special handling for Set with string elements
        if type_name == "Set" and method in ("has", "add") and expr.args:
            elem_arg = self.generate_expression(expr.args[0])
            is_string_elem = (isinstance(elem_arg.type, ir.PointerType) and
                            hasattr(elem_arg.type.pointee, 'name') and
                            elem_arg.type.pointee.name == "struct.String")

            if is_string_elem:
                if method == "has":
                    return cg.builder.call(cg.set_has_string, [obj, elem_arg])
                elif method == "add":
                    return cg.builder.call(cg.set_add_string, [obj, elem_arg])

        # Special handling for Map.set with non-string keys
        if type_name == "Map" and method == "set" and len(expr.args) >= 2:
            key_arg = self.generate_expression(expr.args[0])
            value_arg = self.generate_expression(expr.args[1])
            key_i64 = cg._cast_value(key_arg, ir.IntType(64))
            # Check if value is a reference type - if so, store handle instead of pointer
            value_coex_type = cg._infer_type_from_expr(expr.args[1])
            if value_coex_type is not None and cg._is_reference_type(value_coex_type):
                value_i8 = cg.builder.bitcast(value_arg, ir.IntType(8).as_pointer())
                value_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [value_i8])
                return cg.builder.call(cg.map_set, [obj, key_i64, value_handle])
            else:
                value_i64 = cg._cast_value(value_arg, ir.IntType(64))
                return cg.builder.call(cg.map_set, [obj, key_i64, value_i64])

        # Special handling for Channel methods
        if type_name == "Channel" and method in ("send", "receive"):
            if method == "send" and expr.args:
                value = self.generate_expression(expr.args[0])
                return cg._channel.generate_channel_send(obj, value, cg.builder)
            elif method == "receive":
                return cg._channel.generate_channel_receive(obj, cg.builder)

        # BUG-074 FIX: Special handling for Json.set - dispatch based on key type
        # json.set(int_index, value) -> json_set_index
        # json.set(string_key, value) -> json_set_field
        if type_name == "Json" and method == "set" and len(expr.args) >= 2:
            key_arg = self.generate_expression(expr.args[0])
            value_arg = self.generate_expression(expr.args[1])

            # Convert value to json if needed
            if not (isinstance(value_arg.type, ir.PointerType) and
                    hasattr(value_arg.type.pointee, 'name') and
                    value_arg.type.pointee.name == "struct.Json"):
                value_arg = cg._convert_to_json(value_arg, expr.args[1])

            # Check if key is a string
            is_string_key = (isinstance(key_arg.type, ir.PointerType) and
                            hasattr(key_arg.type.pointee, 'name') and
                            key_arg.type.pointee.name == "struct.String")

            if is_string_key:
                # String key: call json_set_field(json*, string*, json*)
                return cg.builder.call(cg.json_set_field, [obj, key_arg, value_arg])
            else:
                # Integer index: call json_set_index(json*, i64, json*)
                key_i64 = cg._cast_value(key_arg, ir.IntType(64))
                return cg.builder.call(cg.json_set_index, [obj, key_i64, value_arg])

        if type_name and type_name in cg.type_methods:
            method_map = cg.type_methods[type_name]
            if method in method_map:
                mangled = method_map[method]
                func = cg.functions[mangled]

                args = [obj]
                for i, arg in enumerate(expr.args):
                    arg_val = self.generate_expression(arg)
                    if i + 1 < len(func.args):
                        expected = func.args[i + 1].type
                        if type_name == "Json" and isinstance(expected, ir.PointerType):
                            if hasattr(expected.pointee, 'name') and expected.pointee.name == "struct.Json":
                                if not (isinstance(arg_val.type, ir.PointerType) and
                                        hasattr(arg_val.type.pointee, 'name') and
                                        arg_val.type.pointee.name == "struct.Json"):
                                    arg_val = cg._convert_to_json(arg_val, arg)
                        else:
                            arg_val = cg._cast_value(arg_val, expected)
                    args.append(arg_val)

                result = cg.builder.call(func, args)

                # Special handling for List.get and Array.get
                if (type_name == "List" or type_name == "Array") and method == "get":
                    elem_llvm_type = ir.IntType(64)
                    elem_coex_type = None
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ListType, ArrayType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_coex_type = coex_type.element_type
                                elem_llvm_type = cg._get_llvm_type(elem_coex_type)

                    # Check if TaggedValue mode is enabled (List only, not Array yet)
                    use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False) and type_name == "List"

                    if use_tagged:
                        # TaggedValue mode: result (i8*) points to TaggedValue {i64 type_id, i64 value}
                        tv_ptr = cg.builder.bitcast(result, cg.gc.tagged_value_ptr_type)
                        type_id, raw_value = cg.gc.extract_tagged_value(cg.builder, tv_ptr)

                        # Check if this is a heap reference (type_id >= TYPE_HEAP_BASE)
                        is_heap = cg.builder.icmp_unsigned('>=', type_id,
                            ir.Constant(ir.IntType(64), cg.gc.TYPE_HEAP_BASE))

                        # Create basic blocks for conditional handling
                        heap_bb = cg.builder.append_basic_block("listmget_heap")
                        value_bb = cg.builder.append_basic_block("listmget_value")
                        merge_bb = cg.builder.append_basic_block("listmget_merge")

                        cg.builder.cbranch(is_heap, heap_bb, value_bb)

                        # Heap path: raw_value is a handle, dereference it
                        # Use runtime type_id to determine correct pointer type (fixes BUG-075)
                        cg.builder.position_at_end(heap_bb)
                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [raw_value])

                        # Switch on runtime type_id to get correct struct pointer type
                        # This handles deeply nested lists where compile-time inference fails
                        heap_list_bb = cg.builder.append_basic_block("listmget_heap_list")
                        heap_string_bb = cg.builder.append_basic_block("listmget_heap_string")
                        heap_map_bb = cg.builder.append_basic_block("listmget_heap_map")
                        heap_set_bb = cg.builder.append_basic_block("listmget_heap_set")
                        heap_array_bb = cg.builder.append_basic_block("listmget_heap_array")
                        heap_default_bb = cg.builder.append_basic_block("listmget_heap_default")
                        heap_merge_bb = cg.builder.append_basic_block("listmget_heap_merge")

                        # Switch on type_id (TV_TYPE_* constants)
                        switch = cg.builder.switch(type_id, heap_default_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_LIST), heap_list_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_STRING), heap_string_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_MAP), heap_map_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_SET), heap_set_bb)
                        switch.add_case(ir.Constant(ir.IntType(64), cg.gc.TV_TYPE_ARRAY), heap_array_bb)
                        # Other heap types (JSON, etc.) fall through to default

                        # Each type case: bitcast to correct struct pointer, then to i8*
                        cg.builder.position_at_end(heap_list_bb)
                        list_ptr = cg.builder.bitcast(ptr_i8, cg.list_struct.as_pointer())
                        list_as_i8 = cg.builder.bitcast(list_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_string_bb)
                        str_ptr = cg.builder.bitcast(ptr_i8, cg.string_struct.as_pointer())
                        str_as_i8 = cg.builder.bitcast(str_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_map_bb)
                        map_ptr = cg.builder.bitcast(ptr_i8, cg.map_struct.as_pointer())
                        map_as_i8 = cg.builder.bitcast(map_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_set_bb)
                        set_ptr = cg.builder.bitcast(ptr_i8, cg.set_struct.as_pointer())
                        set_as_i8 = cg.builder.bitcast(set_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_array_bb)
                        arr_ptr = cg.builder.bitcast(ptr_i8, cg.array_struct.as_pointer())
                        arr_as_i8 = cg.builder.bitcast(arr_ptr, ir.IntType(8).as_pointer())
                        cg.builder.branch(heap_merge_bb)

                        cg.builder.position_at_end(heap_default_bb)
                        cg.builder.branch(heap_merge_bb)

                        # Merge heap type cases
                        cg.builder.position_at_end(heap_merge_bb)
                        heap_phi = cg.builder.phi(ir.IntType(8).as_pointer(), "heap_typed_ptr")
                        heap_phi.add_incoming(list_as_i8, heap_list_bb)
                        heap_phi.add_incoming(str_as_i8, heap_string_bb)
                        heap_phi.add_incoming(map_as_i8, heap_map_bb)
                        heap_phi.add_incoming(set_as_i8, heap_set_bb)
                        heap_phi.add_incoming(arr_as_i8, heap_array_bb)
                        heap_phi.add_incoming(ptr_i8, heap_default_bb)

                        # Convert to final elem_llvm_type for outer merge
                        if isinstance(elem_llvm_type, ir.PointerType):
                            heap_result = cg.builder.bitcast(heap_phi, elem_llvm_type)
                        else:
                            # Compile-time thinks it's primitive but runtime says heap
                            # Return ptr as i64 - caller must handle this case
                            heap_result = cg.builder.ptrtoint(heap_phi, ir.IntType(64))
                            heap_result = self._from_i64_value(heap_result, elem_llvm_type)
                        cg.builder.branch(merge_bb)
                        heap_bb_final = cg.builder.block

                        # Value path: raw_value is the actual value
                        cg.builder.position_at_end(value_bb)
                        value_result = self._from_i64_value(raw_value, elem_llvm_type)
                        cg.builder.branch(merge_bb)
                        value_bb_final = cg.builder.block

                        # Merge
                        cg.builder.position_at_end(merge_bb)
                        phi = cg.builder.phi(elem_llvm_type, "listmget_elem")
                        phi.add_incoming(heap_result, heap_bb_final)
                        phi.add_incoming(value_result, value_bb_final)
                        return phi
                    else:
                        # Legacy mode: Reference types are stored as handles - load handle and dereference
                        if elem_coex_type is not None and cg._is_reference_type(elem_coex_type):
                            handle_ptr = cg.builder.bitcast(result, ir.IntType(64).as_pointer())
                            handle = cg.builder.load(handle_ptr)
                            ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [handle])
                            return cg.builder.bitcast(ptr_i8, elem_llvm_type)
                        else:
                            # Non-reference types: load directly
                            typed_ptr = cg.builder.bitcast(result, elem_llvm_type.as_pointer())
                            return cg.builder.load(typed_ptr)

                # Special handling for Map.get - returns i64 that may be a handle
                if type_name == "Map" and method == "get":
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import MapType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_coex_type = coex_type.value_type
                                value_llvm_type = cg._get_llvm_type(value_coex_type)
                                # If value type is a pointer, the i64 result is a handle
                                if isinstance(value_llvm_type, ir.PointerType):
                                    # Reference types are stored as handles - dereference
                                    if cg._is_reference_type(value_coex_type):
                                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [result])
                                        return cg.builder.bitcast(ptr_i8, value_llvm_type)
                                    else:
                                        return cg.builder.inttoptr(result, value_llvm_type)
                    return result

                # Special handling for Result.unwrap and Result.unwrap_or
                if type_name == "Result" and method in ("unwrap", "unwrap_or"):
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ResultType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ResultType):
                                ok_llvm_type = cg._get_llvm_type(coex_type.ok_type)
                                # If ok_type is a pointer, convert i64 handle back to pointer
                                if isinstance(ok_llvm_type, ir.PointerType):
                                    if cg._is_reference_type(coex_type.ok_type):
                                        ptr_i8 = cg.builder.call(cg.gc.gc_handle_deref, [result])
                                        return cg.builder.bitcast(ptr_i8, ok_llvm_type)
                                    else:
                                        return cg.builder.inttoptr(result, ok_llvm_type)
                    return result

                return result

        # Built-in methods
        if method == "new":
            return ir.Constant(ir.IntType(8).as_pointer(), None)

        if method == "append":
            if expr.args and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    elem_val = self.generate_expression(expr.args[0])
                    elem_type = elem_val.type

                    # Check if element is a reference type - if so, store handle instead of pointer
                    elem_coex_type = cg._infer_type_from_expr(expr.args[0])
                    is_ref_type = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)

                    # Safety net: if type inference missed it but LLVM type is a pointer,
                    # it's a reference type (e.g. String.from() returns String*)
                    if not is_ref_type and isinstance(elem_type, ir.PointerType):
                        is_ref_type = True
                        # Try to infer coex type from LLVM pointer type
                        if elem_coex_type is None or not cg._is_reference_type(elem_coex_type):
                            if hasattr(elem_type.pointee, 'name'):
                                if elem_type.pointee.name == "struct.String":
                                    elem_coex_type = PrimitiveType("string")
                                elif elem_type.pointee.name == "struct.List":
                                    elem_coex_type = ListType(PrimitiveType("int"))
                                elif elem_type.pointee.name == "struct.Map":
                                    elem_coex_type = MapType(PrimitiveType("int"), PrimitiveType("int"))
                                elif elem_type.pointee.name == "struct.Set":
                                    elem_coex_type = SetType(PrimitiveType("int"))
                                elif elem_type.pointee.name == "struct.Array":
                                    elem_coex_type = ArrayType(PrimitiveType("int"))

                    # Check if TaggedValue mode is enabled
                    use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False)

                    if use_tagged:
                        # TaggedValue mode: always 16 bytes, store as {type_id, value}
                        elem_size = ir.Constant(ir.IntType(64), cg.TAGGED_VALUE_SIZE)

                        # Get TaggedValue type ID for this element type
                        tv_type_id = cg.gc.get_tv_type_id(elem_coex_type) if elem_coex_type else cg.gc.TV_TYPE_INT

                        # Create TaggedValue on stack
                        tv_ptr = cg.gc.create_tagged_value(cg.builder, tv_type_id, self._to_i64_value(elem_val, is_ref_type))

                        # Append - list_append copies the TaggedValue (16 bytes)
                        tv_i8 = cg.builder.bitcast(tv_ptr, ir.IntType(8).as_pointer())
                        return cg.builder.call(cg.list_append, [obj, tv_i8, elem_size])
                    else:
                        # Legacy mode: variable elem_size based on type
                        # Reference types store handles (always 8 bytes)
                        if is_ref_type:
                            size = 8
                        elif isinstance(elem_type, ir.IntType):
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

                        if is_ref_type:
                            # Reference types: convert pointer to handle, store handle
                            elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
                            elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                            with cg.builder.goto_entry_block():
                                temp = cg.builder.alloca(ir.IntType(64), name="append_elem_handle")
                            cg.builder.store(elem_handle, temp)
                            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
                        else:
                            # Non-reference types: store value directly
                            with cg.builder.goto_entry_block():
                                temp = cg.builder.alloca(elem_type, name="append_elem")
                            cg.builder.store(elem_val, temp)
                            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                        return cg.builder.call(cg.list_append, [obj, temp_ptr, elem_size])

                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    elem_val = self.generate_expression(expr.args[0])
                    elem_type = elem_val.type

                    # Check if element is a reference type
                    elem_coex_type = cg._infer_type_from_expr(expr.args[0])
                    is_ref_type = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)

                    if is_ref_type:
                        size = 8
                    elif isinstance(elem_type, ir.IntType):
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

                    if is_ref_type:
                        # Reference types: convert pointer to handle, store handle
                        elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
                        elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                        with cg.builder.goto_entry_block():
                            temp = cg.builder.alloca(ir.IntType(64), name="array_append_elem_handle")
                        cg.builder.store(elem_handle, temp)
                        temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
                        return cg.builder.call(cg.array_append_ref, [obj, temp_ptr, elem_size])
                    else:
                        with cg.builder.goto_entry_block():
                            temp = cg.builder.alloca(elem_type, name="array_append_elem")
                        cg.builder.store(elem_val, temp)
                        temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
                        return cg.builder.call(cg.array_append, [obj, temp_ptr, elem_size])

            return ir.Constant(ir.IntType(64), 0)

        if method == "set" or method == "set_at":
            if len(expr.args) >= 2 and isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee

                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    index = self.generate_expression(expr.args[0])
                    elem_val = self.generate_expression(expr.args[1])
                    elem_type = elem_val.type

                    # Check if element is a reference type - if so, store handle instead of pointer
                    elem_coex_type = cg._infer_type_from_expr(expr.args[1])
                    is_ref_type = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)

                    # Check if TaggedValue mode is enabled
                    use_tagged = getattr(cg, 'USE_TAGGED_VALUES', False)

                    if use_tagged:
                        # TaggedValue mode: always 16 bytes, store as {type_id, value}
                        elem_size = ir.Constant(ir.IntType(64), cg.TAGGED_VALUE_SIZE)

                        # Get TaggedValue type ID for this element type
                        tv_type_id = cg.gc.get_tv_type_id(elem_coex_type) if elem_coex_type else cg.gc.TV_TYPE_INT

                        # Create TaggedValue on stack
                        tv_ptr = cg.gc.create_tagged_value(cg.builder, tv_type_id, self._to_i64_value(elem_val, is_ref_type))

                        # Set - list_set copies the TaggedValue (16 bytes)
                        tv_i8 = cg.builder.bitcast(tv_ptr, ir.IntType(8).as_pointer())

                        if index.type != ir.IntType(64):
                            index = cg.builder.sext(index, ir.IntType(64))

                        return cg.builder.call(cg.list_set, [obj, index, tv_i8, elem_size])
                    else:
                        # Legacy mode: variable elem_size based on type
                        # Reference types store handles (always 8 bytes)
                        if is_ref_type:
                            size = 8
                        elif isinstance(elem_type, ir.IntType):
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

                        if is_ref_type:
                            # Reference types: convert pointer to handle, store handle
                            elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
                            elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                            with cg.builder.goto_entry_block():
                                temp = cg.builder.alloca(ir.IntType(64), name="list_set_elem_handle")
                            cg.builder.store(elem_handle, temp)
                            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
                        else:
                            # Non-reference types: store value directly
                            with cg.builder.goto_entry_block():
                                temp = cg.builder.alloca(elem_type, name="list_set_elem")
                            cg.builder.store(elem_val, temp)
                            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                        if index.type != ir.IntType(64):
                            index = cg.builder.sext(index, ir.IntType(64))

                        return cg.builder.call(cg.list_set, [obj, index, temp_ptr, elem_size])

                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    index = self.generate_expression(expr.args[0])
                    elem_val = self.generate_expression(expr.args[1])
                    elem_type = elem_val.type

                    # Check if element is a reference type - if so, store handle instead of pointer
                    elem_coex_type = cg._infer_type_from_expr(expr.args[1])
                    is_ref_type = elem_coex_type is not None and cg._is_reference_type(elem_coex_type)

                    # Reference types store handles (always 8 bytes)
                    if is_ref_type:
                        size = 8
                    elif isinstance(elem_type, ir.IntType):
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

                    if is_ref_type:
                        # Reference types: convert pointer to handle, store handle
                        elem_i8 = cg.builder.bitcast(elem_val, ir.IntType(8).as_pointer())
                        elem_handle = cg.builder.call(cg.gc.gc_ptr_to_handle, [elem_i8])
                        with cg.builder.goto_entry_block():
                            temp = cg.builder.alloca(ir.IntType(64), name="array_set_elem_handle")
                        cg.builder.store(elem_handle, temp)
                        temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())
                    else:
                        # Non-reference types: store value directly
                        with cg.builder.goto_entry_block():
                            temp = cg.builder.alloca(elem_type, name="array_set_elem")
                        cg.builder.store(elem_val, temp)
                        temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    if index.type != ir.IntType(64):
                        index = cg.builder.sext(index, ir.IntType(64))

                    if is_ref_type:
                        return cg.builder.call(cg.array_set_ref, [obj, index, temp_ptr, elem_size])
                    else:
                        return cg.builder.call(cg.array_set, [obj, index, temp_ptr, elem_size])

            return ir.Constant(ir.IntType(64), 0)

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
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    # Check if List has reference type elements for proper GC tracing
                    is_ref_type = False
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ListType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ListType):
                                elem_coex_type = coex_type.element_type
                                is_ref_type = cg._is_reference_type(elem_coex_type)
                    return cg._list_to_array(obj, is_ref_type)
                if hasattr(pointee, 'name') and pointee.name == "struct.Set":
                    return cg._set_to_array(obj)
            return ir.Constant(ir.IntType(64), 0)

        if method == "unpacked" or method == "toList":
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    return cg._array_to_list(obj)
            return ir.Constant(ir.IntType(64), 0)

        if method == "toSet" or method == "to_set":
            if isinstance(obj.type, ir.PointerType):
                pointee = obj.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    return cg._array_to_set(obj)
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    return cg._list_to_set(obj)
            return ir.Constant(ir.IntType(64), 0)

        # Type conversion methods: .int(), .float(), .int32(), .float32()
        if method == "int":
            if isinstance(obj.type, ir.DoubleType):
                return cg.builder.fptosi(obj, ir.IntType(64))
            if isinstance(obj.type, ir.FloatType):
                return cg.builder.fptosi(obj, ir.IntType(64))
            if isinstance(obj.type, ir.IntType):
                return cg._cast_value(obj, ir.IntType(64))
            return obj

        if method == "int32":
            if isinstance(obj.type, ir.DoubleType):
                return cg.builder.fptosi(obj, ir.IntType(32))
            if isinstance(obj.type, ir.FloatType):
                return cg.builder.fptosi(obj, ir.IntType(32))
            if isinstance(obj.type, ir.IntType):
                return cg._cast_value(obj, ir.IntType(32))
            return obj

        if method == "float":
            if isinstance(obj.type, ir.IntType):
                return cg.builder.sitofp(obj, ir.DoubleType())
            if isinstance(obj.type, ir.FloatType):
                return cg.builder.fpext(obj, ir.DoubleType())
            if isinstance(obj.type, ir.DoubleType):
                return obj
            return obj

        if method == "float32":
            if isinstance(obj.type, ir.IntType):
                return cg.builder.sitofp(obj, ir.FloatType())
            if isinstance(obj.type, ir.DoubleType):
                return cg.builder.fptrunc(obj, ir.FloatType())
            if isinstance(obj.type, ir.FloatType):
                return obj
            return obj

        # Array element-wise operations and reductions
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                return self._generate_array_operation(obj, method, expr.args)

        # Generic method lookup failed
        if type_name:
            raise RuntimeError(f"Undefined method '{method}' on type '{type_name}'")
        else:
            raise RuntimeError(f"Undefined method '{method}' on unknown type")

    def _generate_array_operation(self, array_ptr: ir.Value, method: str, args: list) -> ir.Value:
        """Generate element-wise operations and reductions for Array<T>.

        Element-wise ops (return new Array):
        - scale(scalar) - multiply all by scalar
        - add(other) - element-wise addition
        - sub(other) - element-wise subtraction
        - mul(other) - Hadamard product
        - div(other) - element-wise division

        Reductions (return scalar):
        - sum() - sum all elements
        - min() - minimum element
        - max() - maximum element
        """
        cg = self.cg
        builder = cg.builder
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        zero = ir.Constant(i64, 0)
        one = ir.Constant(i64, 1)

        # Get total element count
        total_elements = builder.call(cg.array_total_size, [array_ptr])

        # Read elem_size from the array struct (field 5)
        elem_size_ptr = builder.gep(array_ptr, [
            ir.Constant(i32, 0), ir.Constant(i32, 5)  # ARRAY_FIELD_ELEM_SIZE
        ], inbounds=True)
        elem_size = builder.load(elem_size_ptr, name="elem_size")

        # Get source data pointer
        src_data = builder.call(cg.array_get, [array_ptr, zero])

        if method == "scale":
            # scale(scalar) - multiply all elements by scalar
            scalar = cg._generate_expression(args[0])
            scalar_i64 = cg._cast_value(scalar, i64)

            # Create new array with same size
            new_arr = builder.call(cg.array_new, [total_elements, elem_size])
            dst_data = builder.call(cg.array_get, [new_arr, zero])

            # Loop over elements
            idx_ptr = builder.alloca(i64, name="scale_idx")
            builder.store(zero, idx_ptr)

            loop_bb = builder.append_basic_block("scale_loop")
            body_bb = builder.append_basic_block("scale_body")
            exit_bb = builder.append_basic_block("scale_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)
            src_elem_ptr = builder.gep(src_data, [offset])
            src_elem_ptr_i64 = builder.bitcast(src_elem_ptr, i64.as_pointer())
            src_elem = builder.load(src_elem_ptr_i64)

            result_elem = builder.mul(src_elem, scalar_i64)

            dst_elem_ptr = builder.gep(dst_data, [offset])
            dst_elem_ptr_i64 = builder.bitcast(dst_elem_ptr, i64.as_pointer())
            builder.store(result_elem, dst_elem_ptr_i64)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            return new_arr

        elif method in ("add", "sub", "mul", "div"):
            # Binary element-wise operations
            other_arr = cg._generate_expression(args[0])

            # Create new array with same size
            new_arr = builder.call(cg.array_new, [total_elements, elem_size])
            dst_data = builder.call(cg.array_get, [new_arr, zero])
            other_data = builder.call(cg.array_get, [other_arr, zero])

            # Loop over elements
            idx_ptr = builder.alloca(i64, name=f"{method}_idx")
            builder.store(zero, idx_ptr)

            loop_bb = builder.append_basic_block(f"{method}_loop")
            body_bb = builder.append_basic_block(f"{method}_body")
            exit_bb = builder.append_basic_block(f"{method}_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)

            src_elem_ptr = builder.gep(src_data, [offset])
            src_elem_ptr_i64 = builder.bitcast(src_elem_ptr, i64.as_pointer())
            src_elem = builder.load(src_elem_ptr_i64)

            other_elem_ptr = builder.gep(other_data, [offset])
            other_elem_ptr_i64 = builder.bitcast(other_elem_ptr, i64.as_pointer())
            other_elem = builder.load(other_elem_ptr_i64)

            if method == "add":
                result_elem = builder.add(src_elem, other_elem)
            elif method == "sub":
                result_elem = builder.sub(src_elem, other_elem)
            elif method == "mul":
                result_elem = builder.mul(src_elem, other_elem)
            elif method == "div":
                result_elem = builder.sdiv(src_elem, other_elem)

            dst_elem_ptr = builder.gep(dst_data, [offset])
            dst_elem_ptr_i64 = builder.bitcast(dst_elem_ptr, i64.as_pointer())
            builder.store(result_elem, dst_elem_ptr_i64)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            return new_arr

        elif method == "sum":
            # sum() - sum all elements
            acc_ptr = builder.alloca(i64, name="sum_acc")
            builder.store(zero, acc_ptr)

            idx_ptr = builder.alloca(i64, name="sum_idx")
            builder.store(zero, idx_ptr)

            loop_bb = builder.append_basic_block("sum_loop")
            body_bb = builder.append_basic_block("sum_body")
            exit_bb = builder.append_basic_block("sum_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)
            elem_ptr = builder.gep(src_data, [offset])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            elem = builder.load(elem_ptr_i64)

            acc = builder.load(acc_ptr)
            new_acc = builder.add(acc, elem)
            builder.store(new_acc, acc_ptr)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            return builder.load(acc_ptr)

        elif method == "mean":
            # mean() - compute average of all elements (integer division)
            acc_ptr = builder.alloca(i64, name="mean_acc")
            builder.store(zero, acc_ptr)

            idx_ptr = builder.alloca(i64, name="mean_idx")
            builder.store(zero, idx_ptr)

            loop_bb = builder.append_basic_block("mean_loop")
            body_bb = builder.append_basic_block("mean_body")
            exit_bb = builder.append_basic_block("mean_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)
            elem_ptr = builder.gep(src_data, [offset])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            elem = builder.load(elem_ptr_i64)

            acc = builder.load(acc_ptr)
            new_acc = builder.add(acc, elem)
            builder.store(new_acc, acc_ptr)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            total_sum = builder.load(acc_ptr)
            # Integer division for mean
            mean_val = builder.sdiv(total_sum, total_elements)
            return mean_val

        elif method == "min":
            # min() - find minimum element
            # Initialize with first element
            first_ptr = builder.bitcast(src_data, i64.as_pointer())
            first_elem = builder.load(first_ptr)
            min_ptr = builder.alloca(i64, name="min_val")
            builder.store(first_elem, min_ptr)

            idx_ptr = builder.alloca(i64, name="min_idx")
            builder.store(one, idx_ptr)  # Start at index 1

            loop_bb = builder.append_basic_block("min_loop")
            body_bb = builder.append_basic_block("min_body")
            exit_bb = builder.append_basic_block("min_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)
            elem_ptr = builder.gep(src_data, [offset])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            elem = builder.load(elem_ptr_i64)

            current_min = builder.load(min_ptr)
            is_smaller = builder.icmp_signed("<", elem, current_min)
            new_min = builder.select(is_smaller, elem, current_min)
            builder.store(new_min, min_ptr)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            return builder.load(min_ptr)

        elif method == "max":
            # max() - find maximum element
            # Initialize with first element
            first_ptr = builder.bitcast(src_data, i64.as_pointer())
            first_elem = builder.load(first_ptr)
            max_ptr = builder.alloca(i64, name="max_val")
            builder.store(first_elem, max_ptr)

            idx_ptr = builder.alloca(i64, name="max_idx")
            builder.store(one, idx_ptr)  # Start at index 1

            loop_bb = builder.append_basic_block("max_loop")
            body_bb = builder.append_basic_block("max_body")
            exit_bb = builder.append_basic_block("max_exit")

            builder.branch(loop_bb)
            builder.position_at_start(loop_bb)

            idx = builder.load(idx_ptr)
            cond = builder.icmp_signed("<", idx, total_elements)
            builder.cbranch(cond, body_bb, exit_bb)

            builder.position_at_start(body_bb)
            idx = builder.load(idx_ptr)
            offset = builder.mul(idx, elem_size)
            elem_ptr = builder.gep(src_data, [offset])
            elem_ptr_i64 = builder.bitcast(elem_ptr, i64.as_pointer())
            elem = builder.load(elem_ptr_i64)

            current_max = builder.load(max_ptr)
            is_larger = builder.icmp_signed(">", elem, current_max)
            new_max = builder.select(is_larger, elem, current_max)
            builder.store(new_max, max_ptr)

            next_idx = builder.add(idx, one)
            builder.store(next_idx, idx_ptr)
            builder.branch(loop_bb)

            builder.position_at_start(exit_bb)
            return builder.load(max_ptr)

        elif method == "flatten":
            # flatten() - convert N-D array to 1D array
            # Create new 1D array with total_elements
            new_arr = builder.call(cg.array_new, [total_elements, elem_size])
            dst_data = builder.call(cg.array_get, [new_arr, zero])

            # Copy all data (already in row-major order)
            copy_size = builder.mul(total_elements, elem_size)
            builder.call(cg.memcpy, [dst_data, src_data, copy_size])

            return new_arr

        elif method == "transpose":
            # transpose() - swap rows and cols in 2D array
            i32 = ir.IntType(32)

            # Get original shape
            rows = builder.call(cg.array_shape, [array_ptr, zero])
            cols = builder.call(cg.array_shape, [array_ptr, one])

            # Create new 2D array with swapped dimensions
            new_arr = builder.call(cg.array_new_2d, [cols, rows, elem_size])

            # Loop over all elements and copy with transposed indices
            row_ptr = builder.alloca(i64, name="trans_row")
            col_ptr = builder.alloca(i64, name="trans_col")
            builder.store(zero, row_ptr)

            row_loop = builder.append_basic_block("trans_row_loop")
            row_body = builder.append_basic_block("trans_row_body")
            col_loop = builder.append_basic_block("trans_col_loop")
            col_body = builder.append_basic_block("trans_col_body")
            col_exit = builder.append_basic_block("trans_col_exit")
            row_exit = builder.append_basic_block("trans_row_exit")

            builder.branch(row_loop)
            builder.position_at_start(row_loop)
            r = builder.load(row_ptr)
            row_cond = builder.icmp_signed("<", r, rows)
            builder.cbranch(row_cond, row_body, row_exit)

            builder.position_at_start(row_body)
            builder.store(zero, col_ptr)
            builder.branch(col_loop)

            builder.position_at_start(col_loop)
            c = builder.load(col_ptr)
            col_cond = builder.icmp_signed("<", c, cols)
            builder.cbranch(col_cond, col_body, col_exit)

            builder.position_at_start(col_body)
            r = builder.load(row_ptr)
            c = builder.load(col_ptr)

            # Get element at [r, c] in original
            src_elem = builder.call(cg.array_get_2d, [array_ptr, r, c])
            src_elem_i64 = builder.bitcast(src_elem, i64.as_pointer())
            val = builder.load(src_elem_i64)

            # Store at [c, r] in new array
            dst_elem = builder.call(cg.array_get_2d, [new_arr, c, r])
            dst_elem_i64 = builder.bitcast(dst_elem, i64.as_pointer())
            builder.store(val, dst_elem_i64)

            next_c = builder.add(c, one)
            builder.store(next_c, col_ptr)
            builder.branch(col_loop)

            builder.position_at_start(col_exit)
            r = builder.load(row_ptr)
            next_r = builder.add(r, one)
            builder.store(next_r, row_ptr)
            builder.branch(row_loop)

            builder.position_at_start(row_exit)
            return new_arr

        elif method == "reshape":
            # reshape(rows, cols) - reshape array to new 2D dimensions
            new_rows = cg._generate_expression(args[0])
            new_cols = cg._generate_expression(args[1])
            new_rows_i64 = cg._cast_value(new_rows, i64)
            new_cols_i64 = cg._cast_value(new_cols, i64)

            # Create new 2D array with specified dimensions
            new_arr = builder.call(cg.array_new_2d, [new_rows_i64, new_cols_i64, elem_size])
            dst_data = builder.call(cg.array_get, [new_arr, zero])

            # Copy all data sequentially (row-major order preserved)
            copy_size = builder.mul(total_elements, elem_size)
            builder.call(cg.memcpy, [dst_data, src_data, copy_size])

            return new_arr

        else:
            raise RuntimeError(f"Unknown array operation: {method}")
