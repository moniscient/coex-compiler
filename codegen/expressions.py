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
- Cell access (matrix)
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict
from typing import List as PyList

from ast_nodes import (
    Expr, IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, NilLiteral,
    Identifier, BinaryExpr, BinaryOp, UnaryExpr, UnaryOp, CallExpr,
    MethodCallExpr, MemberExpr, IndexExpr, SliceExpr, TernaryExpr,
    ListExpr, MapExpr, SetExpr, TupleExpr, RangeExpr, LambdaExpr,
    SelfExpr, CellExpr, CellIndexExpr, LlvmIrExpr, AsExpr,
    ListComprehension, SetComprehension, MapComprehension, JsonObjectExpr,
    IdentifierPattern, WildcardPattern, TuplePattern, FunctionKind,
    AtomicType, ListType, ArrayType, SetType, FunctionDecl
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

        elif isinstance(expr, CellExpr):
            # Matrix cell reference - current cell value
            return self.generate_cell_access()

        elif isinstance(expr, CellIndexExpr):
            # Matrix cell[dx, dy] - relative neighbor access
            return self.generate_cell_index_access(expr)

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
            if isinstance(left.type, ir.IntType) and isinstance(right.type, ir.DoubleType):
                left = cg.builder.sitofp(left, ir.DoubleType())
            elif isinstance(left.type, ir.DoubleType) and isinstance(right.type, ir.IntType):
                right = cg.builder.sitofp(right, ir.DoubleType())
            elif isinstance(left.type, ir.IntType) and isinstance(right.type, ir.IntType):
                # Promote smaller to larger
                if left.type.width < right.type.width:
                    left = cg.builder.sext(left, right.type)
                elif right.type.width < left.type.width:
                    right = cg.builder.sext(right, left.type)

        is_float = isinstance(left.type, ir.DoubleType)

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
        """Generate code for list literal: [1, 2, 3]"""
        cg = self.cg

        if not expr.elements:
            # Empty list - default to i64 element size
            elem_size = ir.Constant(ir.IntType(64), 8)
            return cg.builder.call(cg.list_new, [elem_size])

        # Generate first element to determine type
        first_elem = self.generate_expression(expr.elements[0])
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
        list_ptr = cg.builder.call(cg.list_new, [elem_size])

        # Append each element (list_append returns a new list with value semantics)
        for i, elem_expr in enumerate(expr.elements):
            if i == 0:
                elem_val = first_elem
            else:
                elem_val = self.generate_expression(elem_expr)

            # Store element to a temporary location
            temp = cg.builder.alloca(elem_type, name=f"list_elem_{i}")
            cg.builder.store(elem_val, temp)

            # Cast temp to i8*
            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

            # Append - list_append returns a NEW list; update our reference
            list_ptr = cg.builder.call(cg.list_append, [list_ptr, temp_ptr, elem_size])

        return list_ptr

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

            # Check if key is a string pointer
            is_string_key = (isinstance(key.type, ir.PointerType) and
                            hasattr(key.type.pointee, 'name') and
                            key.type.pointee.name == "struct.String")

            if is_string_key:
                # Use string-aware map_set
                value_i64 = cg._cast_value(value, ir.IntType(64))
                map_ptr = cg.builder.call(cg.map_set_string, [map_ptr, key, value_i64])
            else:
                # Cast to i64 for map storage
                key_i64 = cg._cast_value(key, ir.IntType(64))
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

            # Check if element is a string
            is_string_elem = (isinstance(elem.type, ir.PointerType) and
                            hasattr(elem.type.pointee, 'name') and
                            elem.type.pointee.name == "struct.String")

            if is_string_elem:
                # Use string-aware set_add
                set_ptr = cg.builder.call(cg.set_add_string, [set_ptr, elem])
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

        # Special case: cell[dx, dy] is neighbor access in matrix formulas
        if isinstance(expr.object, CellExpr) and len(expr.indices) == 2:
            # Convert to CellIndexExpr and use that handler
            cell_idx = CellIndexExpr(expr.indices[0], expr.indices[1])
            return self.generate_cell_index_access(cell_idx)

        obj = self.generate_expression(expr.object)

        if not expr.indices:
            return ir.Constant(ir.IntType(64), 0)

        # Check if this is a user-defined type with a get method
        type_name = cg._get_type_name_from_ptr(obj.type)
        if type_name and type_name in cg.type_methods:
            method_map = cg.type_methods[type_name]
            if "get" in method_map:
                mangled = method_map["get"]
                func = cg.functions[mangled]

                # Build args: self first, then indices
                args = [obj]
                for i, idx_expr in enumerate(expr.indices):
                    idx_val = self.generate_expression(idx_expr)
                    # Cast to expected type (args[i+1] because args[0] is self)
                    if i + 1 < len(func.args):
                        expected = func.args[i + 1].type
                        idx_val = cg._cast_value(idx_val, expected)
                    args.append(idx_val)

                result = cg.builder.call(func, args)

                # Special handling for List.get and Array.get - returns i8* that needs dereferencing
                if type_name == "List" or type_name == "Array":
                    # Get element type from Coex type tracking
                    elem_llvm_type = ir.IntType(64)  # default
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ListType, ArrayType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_llvm_type = cg._get_llvm_type(coex_type.element_type)
                    typed_ptr = cg.builder.bitcast(result, elem_llvm_type.as_pointer())
                    return cg.builder.load(typed_ptr)

                return result

        index = self.generate_expression(expr.indices[0])

        # Check if this is an Array
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                # Array indexing - call array_get and load the value
                if index.type != ir.IntType(64):
                    index = cg._cast_value(index, ir.IntType(64))

                elem_ptr = cg.builder.call(cg.array_get, [obj, index])

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

        # Check if this is a List
        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                # List indexing - call list_get and load the value
                # Ensure index is i64
                if index.type != ir.IntType(64):
                    index = cg._cast_value(index, ir.IntType(64))

                elem_ptr = cg.builder.call(cg.list_get, [obj, index])

                # Get element type from Coex type tracking
                elem_llvm_type = ir.IntType(64)  # default
                if isinstance(expr.object, Identifier):
                    var_name = expr.object.name
                    if var_name in cg.var_coex_types:
                        from ast_nodes import ListType
                        coex_type = cg.var_coex_types[var_name]
                        if isinstance(coex_type, ListType):
                            elem_llvm_type = cg._get_llvm_type(coex_type.element_type)

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
    # Cell Access (Matrix/CA)
    # ========================================================================

    def generate_cell_access(self) -> ir.Value:
        """Generate code to access current cell value (cell keyword)."""
        cg = self.cg

        if cg.current_matrix is None:
            return ir.Constant(ir.IntType(64), 0)

        # Get read buffer and current position
        read_buf = cg.builder.load(cg.locals["__read_buffer"])
        x = cg.builder.load(cg.locals["__cell_x"])
        y = cg.builder.load(cg.locals["__cell_y"])
        width = cg.builder.load(cg.locals["__width"])

        # Calculate index: y * width + x
        row_offset = cg.builder.mul(y, width)
        idx = cg.builder.add(row_offset, x)

        # Load value
        elem_ptr = cg.builder.gep(read_buf, [idx])
        return cg.builder.load(elem_ptr)

    def generate_cell_index_access(self, expr: CellIndexExpr) -> ir.Value:
        """Generate code for relative cell access: cell[dx, dy].

        Returns nil (as optional) if out of bounds.
        """
        cg = self.cg

        if cg.current_matrix is None:
            return ir.Constant(ir.IntType(64), 0)

        # Get current position and offsets
        x = cg.builder.load(cg.locals["__cell_x"])
        y = cg.builder.load(cg.locals["__cell_y"])

        dx = self.generate_expression(expr.dx)
        dy = self.generate_expression(expr.dy)

        # Ensure i64
        if dx.type != ir.IntType(64):
            dx = cg.builder.sext(dx, ir.IntType(64))
        if dy.type != ir.IntType(64):
            dy = cg.builder.sext(dy, ir.IntType(64))

        # Calculate target position
        target_x = cg.builder.add(x, dx)
        target_y = cg.builder.add(y, dy)

        # Get dimensions
        width = cg.builder.load(cg.locals["__width"])
        height = cg.builder.load(cg.locals["__height"])

        # Bounds check
        x_valid_low = cg.builder.icmp_signed(">=", target_x, ir.Constant(ir.IntType(64), 0))
        x_valid_high = cg.builder.icmp_signed("<", target_x, width)
        y_valid_low = cg.builder.icmp_signed(">=", target_y, ir.Constant(ir.IntType(64), 0))
        y_valid_high = cg.builder.icmp_signed("<", target_y, height)

        x_valid = cg.builder.and_(x_valid_low, x_valid_high)
        y_valid = cg.builder.and_(y_valid_low, y_valid_high)
        in_bounds = cg.builder.and_(x_valid, y_valid)

        # Create result based on bounds
        func = cg.builder.function
        in_bounds_block = func.append_basic_block("cell_in_bounds")
        out_bounds_block = func.append_basic_block("cell_out_bounds")
        merge_block = func.append_basic_block("cell_merge")

        cg.builder.cbranch(in_bounds, in_bounds_block, out_bounds_block)

        # In bounds: load value
        cg.builder.position_at_end(in_bounds_block)
        read_buf = cg.builder.load(cg.locals["__read_buffer"])
        row_offset = cg.builder.mul(target_y, width)
        idx = cg.builder.add(row_offset, target_x)
        elem_ptr = cg.builder.gep(read_buf, [idx])
        in_bounds_val = cg.builder.load(elem_ptr)
        in_bounds_end = cg.builder.block
        cg.builder.branch(merge_block)

        # Out of bounds: return nil (0 for now)
        cg.builder.position_at_end(out_bounds_block)
        # For optional support, we'd return a nil marker
        # For now, return 0
        out_bounds_val = ir.Constant(in_bounds_val.type, 0)
        out_bounds_end = cg.builder.block
        cg.builder.branch(merge_block)

        # Merge
        cg.builder.position_at_end(merge_block)
        phi = cg.builder.phi(in_bounds_val.type)
        phi.add_incoming(in_bounds_val, in_bounds_end)
        phi.add_incoming(out_bounds_val, out_bounds_end)

        return phi

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

            if name == "sqrt":
                if expr.args:
                    val = self.generate_expression(expr.args[0])
                    return val
                return ir.Constant(ir.DoubleType(), 0.0)

            if name == "gc":
                # Run GC synchronously
                # NOTE: Until Phase 4 (TLAB allocation), GC must be synchronous
                # to avoid race conditions on the allocation list.
                cg.builder.call(cg.gc.gc_collect, [])
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
                    callee_kind = cg.func_decls[name].kind
                    self._check_function_kind_hierarchy(name, callee_kind)

                # Check if this is a thread function call
                if name in cg.func_decls and cg.func_decls[name].kind == FunctionKind.THREAD:
                    return self._generate_thread_call(name, func, expr.args)

                # Check if this is a task function call
                if name in cg.func_decls and cg.func_decls[name].kind == FunctionKind.TASK:
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
        # formula32 has same purity constraints as formula (can call formula or formula32)
        allowed = {
            FunctionKind.FORMULA: {FunctionKind.FORMULA, FunctionKind.FORMULA32},
            FunctionKind.FORMULA32: {FunctionKind.FORMULA, FunctionKind.FORMULA32},
            FunctionKind.TASK: {FunctionKind.FORMULA, FunctionKind.FORMULA32, FunctionKind.TASK},
            FunctionKind.THREAD: {FunctionKind.FORMULA, FunctionKind.FORMULA32, FunctionKind.TASK, FunctionKind.THREAD},
            FunctionKind.FUNC: {FunctionKind.FORMULA, FunctionKind.FORMULA32, FunctionKind.TASK, FunctionKind.THREAD, FunctionKind.FUNC},
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
                    else:
                        arg_val = cg._cast_value(arg_val, ir.IntType(64))
                        return cg.builder.call(cg.string_from_int, [arg_val])

                # Special handling for String.from_bytes()
                if type_name == "String" and expr.method == "from_bytes" and expr.args:
                    arg_val = self.generate_expression(expr.args[0])
                    if isinstance(arg_val.type, ir.PointerType):
                        return cg.builder.call(cg.string_from_bytes, [arg_val])
                    return cg.builder.call(cg.string_from_literal, [cg._get_string_literal("")])

                # Special handling for Array.filled(size, value)
                # Creates an array of `size` elements, all initialized to `value`
                if type_name == "Array" and expr.method == "filled" and len(expr.args) == 2:
                    size_val = self.generate_expression(expr.args[0])
                    size_val = cg._cast_value(size_val, ir.IntType(64))
                    fill_val = self.generate_expression(expr.args[1])

                    # Determine element size based on fill value type
                    if isinstance(fill_val.type, ir.IntType):
                        if fill_val.type.width == 1:
                            elem_size = ir.Constant(ir.IntType(64), 1)  # bool = 1 byte
                        else:
                            elem_size = ir.Constant(ir.IntType(64), 8)  # int = 8 bytes
                    elif isinstance(fill_val.type, ir.DoubleType):
                        elem_size = ir.Constant(ir.IntType(64), 8)  # float = 8 bytes
                    elif isinstance(fill_val.type, ir.PointerType):
                        elem_size = ir.Constant(ir.IntType(64), 8)  # pointer = 8 bytes
                    else:
                        elem_size = ir.Constant(ir.IntType(64), 8)  # default

                    # Allocate the array
                    array_ptr = cg.builder.call(cg.array_filled, [size_val, elem_size])

                    # Fill with value using memset for bools, or loop for other types
                    if isinstance(fill_val.type, ir.IntType) and fill_val.type.width == 1:
                        # For bool arrays, use memset
                        # Get data pointer from array
                        owner_ptr = cg.builder.gep(array_ptr, [
                            ir.Constant(ir.IntType(32), 0),
                            ir.Constant(ir.IntType(32), 0)
                        ], inbounds=True)
                        owner_handle = cg.builder.load(owner_ptr)
                        data_ptr = cg.builder.inttoptr(owner_handle, ir.IntType(8).as_pointer())

                        # memset to fill_val (0 for false, 1 for true)
                        fill_byte = cg.builder.zext(fill_val, ir.IntType(8))
                        cg.builder.call(cg.memset, [data_ptr, fill_byte, size_val])
                    else:
                        # For other types, we'd need a fill loop
                        # For now, just set len = size (data is uninitialized/zero)
                        pass

                    return array_ptr

                # Look for static methods (factory methods)
                mangled = f"{type_name}_{expr.method}"
                if mangled in cg.functions:
                    func = cg.functions[mangled]
                    args = []
                    for i, arg in enumerate(expr.args):
                        arg_val = self.generate_expression(arg)
                        if i < len(func.args):
                            expected = func.args[i].type
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
                        if cg.current_function.kind in (FunctionKind.FORMULA, FunctionKind.FORMULA32):
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
        if type_name == "Map" and method in ("get", "has", "set") and expr.args:
            key_arg = self.generate_expression(expr.args[0])
            is_string_key = (isinstance(key_arg.type, ir.PointerType) and
                            hasattr(key_arg.type.pointee, 'name') and
                            key_arg.type.pointee.name == "struct.String")

            if is_string_key:
                if method == "get":
                    result = cg.builder.call(cg.map_get_string, [obj, key_arg])
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import MapType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_llvm_type = cg._get_llvm_type(coex_type.value_type)
                                if isinstance(value_llvm_type, ir.PointerType):
                                    return cg.builder.inttoptr(result, value_llvm_type)
                    return result
                elif method == "has":
                    return cg.builder.call(cg.map_has_string, [obj, key_arg])
                elif method == "set":
                    value_arg = self.generate_expression(expr.args[1])
                    value_i64 = cg._cast_value(value_arg, ir.IntType(64))
                    return cg.builder.call(cg.map_set_string, [obj, key_arg, value_i64])

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

        # Special handling for Channel methods
        if type_name == "Channel" and method in ("send", "receive"):
            if method == "send" and expr.args:
                value = self.generate_expression(expr.args[0])
                return cg._channel.generate_channel_send(obj, value, cg.builder)
            elif method == "receive":
                return cg._channel.generate_channel_receive(obj, cg.builder)

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
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import ListType, ArrayType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, ListType) or isinstance(coex_type, ArrayType):
                                elem_llvm_type = cg._get_llvm_type(coex_type.element_type)
                    typed_ptr = cg.builder.bitcast(result, elem_llvm_type.as_pointer())
                    return cg.builder.load(typed_ptr)

                # Special handling for Map.get
                if type_name == "Map" and method == "get":
                    if isinstance(expr.object, Identifier):
                        var_name = expr.object.name
                        if var_name in cg.var_coex_types:
                            from ast_nodes import MapType
                            coex_type = cg.var_coex_types[var_name]
                            if isinstance(coex_type, MapType):
                                value_llvm_type = cg._get_llvm_type(coex_type.value_type)
                                if isinstance(value_llvm_type, ir.PointerType):
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
                                if isinstance(ok_llvm_type, ir.PointerType):
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

                    with cg.builder.goto_entry_block():
                        temp = cg.builder.alloca(elem_type, name="append_elem")
                    cg.builder.store(elem_val, temp)
                    temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    return cg.builder.call(cg.list_append, [obj, temp_ptr, elem_size])

                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    elem_val = self.generate_expression(expr.args[0])
                    elem_type = elem_val.type

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

                    with cg.builder.goto_entry_block():
                        temp = cg.builder.alloca(elem_type, name="array_set_elem")
                    cg.builder.store(elem_val, temp)
                    temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    if index.type != ir.IntType(64):
                        index = cg.builder.sext(index, ir.IntType(64))

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
                    return cg._list_to_array(obj)
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

        # Generic method lookup failed
        if type_name:
            raise RuntimeError(f"Undefined method '{method}' on type '{type_name}'")
        else:
            raise RuntimeError(f"Undefined method '{method}' on unknown type")
