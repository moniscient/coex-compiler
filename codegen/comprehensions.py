"""
Comprehension Code Generation for Coex.

This module handles:
- List comprehensions: [f(x) for x in data if p(x)]
- Set comprehensions: {x for x in data if p(x)}
- Map comprehensions: {k: v for k in data if p(k)}
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional

from ast_nodes import (
    ListComprehension, SetComprehension, MapComprehension,
    CallExpr, Identifier, MemberExpr, RangeExpr,
    IdentifierPattern, WildcardPattern, TuplePattern
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ComprehensionGenerator:
    """Generates comprehension-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Comprehension Generation
    # ========================================================================

    def generate_list_comprehension(self, expr: ListComprehension) -> ir.Value:
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
        cg = self.cg
        # Create result list
        elem_size = ir.Constant(ir.IntType(64), 8)
        list_ptr = cg.builder.call(cg.list_new, [elem_size])

        # Store result list in a temporary
        result_var = f"__comp_result_{cg.lambda_counter}"
        cg.lambda_counter += 1
        result_alloca = cg.builder.alloca(cg.list_struct.as_pointer(), name=result_var)
        cg.builder.store(list_ptr, result_alloca)

        # Pre-allocate temp storage OUTSIDE loop to avoid stack overflow
        self._comp_temp_alloca = cg.builder.alloca(ir.IntType(64), name="comp_temp")

        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "list")

        # Clear the temp alloca reference
        self._comp_temp_alloca = None

        # Return the result list
        return cg.builder.load(result_alloca)

    def generate_set_comprehension(self, expr: SetComprehension) -> ir.Value:
        """Generate code for set comprehension using proper Set type."""
        cg = self.cg
        i64 = ir.IntType(64)

        # Infer element type from the body expression and compute flags
        elem_type = cg._infer_type_from_expr(expr.body)
        flags = cg._compute_set_flags(elem_type)

        # Create result set with appropriate flags
        set_ptr = cg.builder.call(cg.set_new, [ir.Constant(i64, flags)])

        result_var = f"__comp_result_{cg.lambda_counter}"
        cg.lambda_counter += 1
        result_alloca = cg.builder.alloca(cg.set_struct.as_pointer(), name=result_var)
        cg.builder.store(set_ptr, result_alloca)

        # Generate the nested loop structure
        self._generate_comprehension_loop(expr.clauses, 0, expr.body, result_alloca, "set")

        return cg.builder.load(result_alloca)

    def generate_map_comprehension(self, expr: MapComprehension) -> ir.Value:
        """Generate code for map comprehension."""
        cg = self.cg
        i64 = ir.IntType(64)

        # Compute flags based on key/value types
        key_type = cg._infer_type_from_expr(expr.key)
        value_type = cg._infer_type_from_expr(expr.value)
        flags = cg._compute_map_flags(key_type, value_type)

        # Create result map with flags
        map_ptr = cg.builder.call(cg.map_new, [ir.Constant(i64, flags)])

        result_var = f"__comp_result_{cg.lambda_counter}"
        cg.lambda_counter += 1
        result_alloca = cg.builder.alloca(cg.map_struct.as_pointer(), name=result_var)
        cg.builder.store(map_ptr, result_alloca)

        # Generate the nested loop structure with key-value pair
        self._generate_comprehension_loop(expr.clauses, 0, (expr.key, expr.value), result_alloca, "map")

        return cg.builder.load(result_alloca)

    def _generate_comprehension_loop(self, clauses, clause_idx, body, result_alloca, comp_type):
        """Generate nested loop structure for comprehension clauses.

        Recursively generates:
        for pattern in iterable
          if condition (optional)
            [next clause or body]
          ~
        ~
        """
        cg = self.cg
        if clause_idx >= len(clauses):
            # Base case: generate body and append to result
            self._generate_comprehension_body(body, result_alloca, comp_type)
            return

        clause = clauses[clause_idx]
        func = cg.builder.function

        # Check if iterable is a range() call
        if isinstance(clause.iterable, CallExpr) and isinstance(clause.iterable.callee, Identifier) and clause.iterable.callee.name == "range":
            self._generate_comprehension_range_loop(clause, clause_idx, clauses, body, result_alloca, comp_type)
            return

        # Check if iterable is a RangeExpr (start..end syntax)
        if isinstance(clause.iterable, RangeExpr):
            self._generate_comprehension_range_expr_loop(clause, clause_idx, clauses, body, result_alloca, comp_type)
            return

        # Get the iterable
        iterable = cg._generate_expression(clause.iterable)

        # Check if it's a List
        if isinstance(iterable.type, ir.PointerType) and hasattr(iterable.type.pointee, 'name') and iterable.type.pointee.name == "struct.List":
            # Generate list iteration
            length = cg.builder.call(cg.list_len, [iterable])

            # Loop counter
            idx_alloca = cg.builder.alloca(ir.IntType(64), name=f"__idx_{clause_idx}")
            cg.builder.store(ir.Constant(ir.IntType(64), 0), idx_alloca)

            # Loop blocks
            loop_cond = func.append_basic_block(f"comp_loop_cond_{clause_idx}")
            loop_body = func.append_basic_block(f"comp_loop_body_{clause_idx}")
            loop_end = func.append_basic_block(f"comp_loop_end_{clause_idx}")

            cg.builder.branch(loop_cond)

            # Condition: idx < length
            cg.builder.position_at_end(loop_cond)
            idx = cg.builder.load(idx_alloca)
            cond = cg.builder.icmp_signed("<", idx, length)
            cg.builder.cbranch(cond, loop_body, loop_end)

            # Body
            cg.builder.position_at_end(loop_body)

            # Reload idx in this block
            idx = cg.builder.load(idx_alloca)

            # Get element and bind to pattern
            elem_ptr = cg.builder.call(cg.list_get, [iterable, idx])
            elem_ptr_cast = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
            elem_val = cg.builder.load(elem_ptr_cast)

            # Bind pattern variables
            cg._bind_pattern(clause.pattern, elem_val)

            # Check condition if present
            if clause.condition:
                cond_val = cg._generate_expression(clause.condition)
                cond_bool = cg._to_bool(cond_val)

                then_block = func.append_basic_block(f"comp_then_{clause_idx}")
                after_block = func.append_basic_block(f"comp_after_{clause_idx}")

                cg.builder.cbranch(cond_bool, then_block, after_block)

                cg.builder.position_at_end(then_block)
                self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
                if not cg.builder.block.is_terminated:
                    cg.builder.branch(after_block)

                cg.builder.position_at_end(after_block)
            else:
                self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)

            # Increment counter
            if not cg.builder.block.is_terminated:
                idx = cg.builder.load(idx_alloca)
                next_idx = cg.builder.add(idx, ir.Constant(ir.IntType(64), 1))
                cg.builder.store(next_idx, idx_alloca)
                cg.builder.branch(loop_cond)

            cg.builder.position_at_end(loop_end)
        else:
            # Unknown iterable type - skip for now
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)

    def _generate_comprehension_range_loop(self, clause, clause_idx, clauses, body, result_alloca, comp_type):
        """Generate comprehension loop for range() iteration."""
        cg = self.cg
        func = cg.builder.function
        args = clause.iterable.args

        # Parse range args: range(end) or range(start, end)
        if len(args) == 1:
            start = ir.Constant(ir.IntType(64), 0)
            end = cg._generate_expression(args[0])
        elif len(args) >= 2:
            start = cg._generate_expression(args[0])
            end = cg._generate_expression(args[1])
        else:
            return

        # Ensure i64
        if start.type != ir.IntType(64):
            start = cg._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = cg._cast_value(end, ir.IntType(64))

        # Get variable name from pattern
        if isinstance(clause.pattern, IdentifierPattern):
            var_name = clause.pattern.name
        elif isinstance(clause.pattern, str):
            var_name = clause.pattern
        else:
            var_name = f"__range_var_{clause_idx}"

        # Allocate loop variable
        loop_var = cg.builder.alloca(ir.IntType(64), name=var_name)
        cg.builder.store(start, loop_var)
        cg.locals[var_name] = loop_var

        # Loop blocks
        loop_cond = func.append_basic_block(f"comp_range_cond_{clause_idx}")
        loop_body = func.append_basic_block(f"comp_range_body_{clause_idx}")
        loop_end = func.append_basic_block(f"comp_range_end_{clause_idx}")

        cg.builder.branch(loop_cond)

        # Condition: i < end
        cg.builder.position_at_end(loop_cond)
        current = cg.builder.load(loop_var)
        cond = cg.builder.icmp_signed("<", current, end)
        cg.builder.cbranch(cond, loop_body, loop_end)

        # Body
        cg.builder.position_at_end(loop_body)

        # Check condition if present
        if clause.condition:
            cond_val = cg._generate_expression(clause.condition)
            cond_bool = cg._to_bool(cond_val)

            then_block = func.append_basic_block(f"comp_range_then_{clause_idx}")
            after_block = func.append_basic_block(f"comp_range_after_{clause_idx}")

            cg.builder.cbranch(cond_bool, then_block, after_block)

            cg.builder.position_at_end(then_block)
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
            if not cg.builder.block.is_terminated:
                cg.builder.branch(after_block)

            cg.builder.position_at_end(after_block)
        else:
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)

        # Increment
        if not cg.builder.block.is_terminated:
            current = cg.builder.load(loop_var)
            next_val = cg.builder.add(current, ir.Constant(ir.IntType(64), 1))
            cg.builder.store(next_val, loop_var)
            cg.builder.branch(loop_cond)

        cg.builder.position_at_end(loop_end)

    def _generate_comprehension_range_expr_loop(self, clause, clause_idx, clauses, body, result_alloca, comp_type):
        """Generate comprehension loop for start..end range expression."""
        cg = self.cg
        func = cg.builder.function
        range_expr = clause.iterable

        start = cg._generate_expression(range_expr.start)
        end = cg._generate_expression(range_expr.end)

        # Ensure i64
        if start.type != ir.IntType(64):
            start = cg._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = cg._cast_value(end, ir.IntType(64))

        # Get variable name from pattern
        if isinstance(clause.pattern, IdentifierPattern):
            var_name = clause.pattern.name
        elif isinstance(clause.pattern, str):
            var_name = clause.pattern
        else:
            var_name = f"__range_var_{clause_idx}"

        # Allocate loop variable
        loop_var = cg.builder.alloca(ir.IntType(64), name=var_name)
        cg.builder.store(start, loop_var)
        cg.locals[var_name] = loop_var

        # Loop blocks
        loop_cond = func.append_basic_block(f"comp_rexpr_cond_{clause_idx}")
        loop_body = func.append_basic_block(f"comp_rexpr_body_{clause_idx}")
        loop_end = func.append_basic_block(f"comp_rexpr_end_{clause_idx}")

        cg.builder.branch(loop_cond)

        # Condition: i < end
        cg.builder.position_at_end(loop_cond)
        current = cg.builder.load(loop_var)
        cond = cg.builder.icmp_signed("<", current, end)
        cg.builder.cbranch(cond, loop_body, loop_end)

        # Body
        cg.builder.position_at_end(loop_body)

        # Check condition if present
        if clause.condition:
            cond_val = cg._generate_expression(clause.condition)
            cond_bool = cg._to_bool(cond_val)

            then_block = func.append_basic_block(f"comp_rexpr_then_{clause_idx}")
            after_block = func.append_basic_block(f"comp_rexpr_after_{clause_idx}")

            cg.builder.cbranch(cond_bool, then_block, after_block)

            cg.builder.position_at_end(then_block)
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)
            if not cg.builder.block.is_terminated:
                cg.builder.branch(after_block)

            cg.builder.position_at_end(after_block)
        else:
            self._generate_comprehension_loop(clauses, clause_idx + 1, body, result_alloca, comp_type)

        # Increment
        if not cg.builder.block.is_terminated:
            current = cg.builder.load(loop_var)
            next_val = cg.builder.add(current, ir.Constant(ir.IntType(64), 1))
            cg.builder.store(next_val, loop_var)
            cg.builder.branch(loop_cond)

        cg.builder.position_at_end(loop_end)

    def _generate_comprehension_body(self, body, result_alloca, comp_type):
        """Generate the body expression and append to result."""
        cg = self.cg
        if comp_type == "list":
            # Evaluate body expression
            val = cg._generate_expression(body)

            # Reuse pre-allocated temp from generate_list_comprehension to avoid stack overflow
            temp = self._comp_temp_alloca
            stored_val = cg._cast_value(val, ir.IntType(64))
            cg.builder.store(stored_val, temp)
            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

            result_list = cg.builder.load(result_alloca)
            elem_size = ir.Constant(ir.IntType(64), 8)
            # list_append returns a NEW list (value semantics); store it back
            new_list = cg.builder.call(cg.list_append, [result_list, temp_ptr, elem_size])
            cg.builder.store(new_list, result_alloca)

        elif comp_type == "set":
            # Evaluate body expression and add to set
            key = cg._generate_expression(body)
            key_i64 = cg._cast_value(key, ir.IntType(64))

            result_set = cg.builder.load(result_alloca)
            # set_add returns a NEW set (value semantics); store it back
            new_set = cg.builder.call(cg.set_add, [result_set, key_i64])
            cg.builder.store(new_set, result_alloca)

        elif comp_type == "map":
            # body is (key_expr, value_expr)
            key_expr, value_expr = body
            key = cg._generate_expression(key_expr)
            value = cg._generate_expression(value_expr)

            key_i64 = cg._cast_value(key, ir.IntType(64))
            value_i64 = cg._cast_value(value, ir.IntType(64))

            result_map = cg.builder.load(result_alloca)
            # map_set returns a NEW map (value semantics); store it back
            new_map = cg.builder.call(cg.map_set, [result_map, key_i64, value_i64])
            cg.builder.store(new_map, result_alloca)
