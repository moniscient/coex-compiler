"""
Loop Code Generation for Coex.

This module handles:
- For loops (range, list, array, map, set iteration)
- Loop nursery support for garbage collection
- Loop variable usage analysis
- Element type inference for collections
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict, Set
from typing import List as PyList

from ast_nodes import (
    ForStmt, ForAssignStmt, Stmt, Expr, VarDecl, IfStmt, WhileStmt,
    Assignment, ExprStmt, ReturnStmt, CallExpr, Identifier, MemberExpr,
    MethodCallExpr, BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
    SliceExpr, ListExpr, TupleExpr, RangeExpr, LambdaExpr, MapExpr,
    IdentifierPattern, WildcardPattern, TuplePattern, Type, ListType,
    PrimitiveType, IntLiteral, FloatLiteral, BoolLiteral
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class LoopGenerator:
    """Generates loop-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Loop Nursery Support
    # ========================================================================

    def loop_needs_nursery(self, stmt: ForStmt) -> bool:
        """Detect if loop body has collection mutations that create garbage.

        NOTE: Nursery support has been removed. This always returns False.
        The simple mark-sweep GC handles garbage collection without the
        heap context/nursery optimization.
        """
        return False

    def has_collection_mutations(self, stmts: PyList[Stmt]) -> bool:
        """Check if statements contain collection mutation patterns."""
        mutation_methods = ('append', 'add', 'set', 'push', 'insert', 'remove', 'pop')

        for stmt in stmts:
            if isinstance(stmt, Assignment):
                # Check for pattern: var = var.method(...)
                # where method is append, set, or similar mutation
                if isinstance(stmt.target, Identifier):
                    target_name = stmt.target.name

                    # Pattern 1: MethodCallExpr (var = var.append(...))
                    if isinstance(stmt.value, MethodCallExpr):
                        method_obj = stmt.value.object
                        method_name = stmt.value.method
                        if isinstance(method_obj, Identifier) and method_obj.name == target_name:
                            if method_name in mutation_methods:
                                return True

                    # Pattern 2: CallExpr with MemberExpr callee (arr.append parsed as CallExpr)
                    elif isinstance(stmt.value, CallExpr) and isinstance(stmt.value.callee, MemberExpr):
                        member_expr = stmt.value.callee
                        method_obj = member_expr.object
                        method_name = member_expr.member
                        if isinstance(method_obj, Identifier) and method_obj.name == target_name:
                            if method_name in mutation_methods:
                                return True

            elif isinstance(stmt, VarDecl):
                # Check for var x = x.append(...) patterns with rebinding
                if stmt.initializer:
                    if isinstance(stmt.initializer, MethodCallExpr):
                        if stmt.initializer.method in mutation_methods:
                            return True
                    elif isinstance(stmt.initializer, CallExpr) and isinstance(stmt.initializer.callee, MemberExpr):
                        if stmt.initializer.callee.member in mutation_methods:
                            return True

            elif isinstance(stmt, IfStmt):
                # Recurse into branches
                if self.has_collection_mutations(stmt.then_body):
                    return True
                for _, body in stmt.else_if_clauses:
                    if self.has_collection_mutations(body):
                        return True
                if stmt.else_body and self.has_collection_mutations(stmt.else_body):
                    return True

            elif isinstance(stmt, WhileStmt):
                if self.has_collection_mutations(stmt.body):
                    return True

        return False

    def get_loop_carried_vars(self, stmt: ForStmt) -> PyList[str]:
        """Find variables that are both read and written in loop body.

        These are variables whose final values must survive the loop -
        they need to be promoted out of the nursery at the end.
        """
        cg = self.cg
        written: Set[str] = set()
        read: Set[str] = set()

        self.collect_var_usage(stmt.body, written, read)

        # Loop-carried vars are those both read and written
        # (they depend on previous iterations)
        loop_carried = written & read

        # Also include vars that are written and used after the loop
        # For now, we conservatively include all written vars that existed before the loop
        pre_existing = set(cg.locals.keys())
        escaping = written & pre_existing

        return list(loop_carried | escaping)

    def collect_var_usage(self, stmts: PyList[Stmt], written: Set[str], read: Set[str]):
        """Collect variables that are written and read in statements."""
        for stmt in stmts:
            if isinstance(stmt, Assignment):
                # Collect writes
                if isinstance(stmt.target, Identifier):
                    written.add(stmt.target.name)
                # Collect reads from value expression
                self.collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, VarDecl):
                written.add(stmt.name)
                if stmt.value:
                    self.collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, ExprStmt):
                self.collect_expr_reads(stmt.expr, read)

            elif isinstance(stmt, ReturnStmt):
                if stmt.value:
                    self.collect_expr_reads(stmt.value, read)

            elif isinstance(stmt, IfStmt):
                self.collect_expr_reads(stmt.condition, read)
                self.collect_var_usage(stmt.then_body, written, read)
                for cond, body in stmt.else_if_clauses:
                    self.collect_expr_reads(cond, read)
                    self.collect_var_usage(body, written, read)
                if stmt.else_body:
                    self.collect_var_usage(stmt.else_body, written, read)

            elif isinstance(stmt, ForStmt):
                self.collect_expr_reads(stmt.iterable, read)
                self.collect_var_usage(stmt.body, written, read)

            elif isinstance(stmt, WhileStmt):
                self.collect_expr_reads(stmt.condition, read)
                self.collect_var_usage(stmt.body, written, read)

    def collect_expr_reads(self, expr: Expr, read: Set[str]):
        """Collect variable reads from an expression."""
        if isinstance(expr, Identifier):
            read.add(expr.name)
        elif isinstance(expr, BinaryExpr):
            self.collect_expr_reads(expr.left, read)
            self.collect_expr_reads(expr.right, read)
        elif isinstance(expr, UnaryExpr):
            self.collect_expr_reads(expr.operand, read)
        elif isinstance(expr, TernaryExpr):
            self.collect_expr_reads(expr.condition, read)
            self.collect_expr_reads(expr.then_expr, read)
            self.collect_expr_reads(expr.else_expr, read)
        elif isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                # Don't count function names as variable reads
                pass
            else:
                self.collect_expr_reads(expr.callee, read)
            for arg in expr.args:
                self.collect_expr_reads(arg, read)
        elif isinstance(expr, MethodCallExpr):
            self.collect_expr_reads(expr.object, read)
            for arg in expr.args:
                self.collect_expr_reads(arg, read)
        elif isinstance(expr, MemberExpr):
            self.collect_expr_reads(expr.object, read)
        elif isinstance(expr, IndexExpr):
            self.collect_expr_reads(expr.object, read)
            for idx in expr.indices:
                self.collect_expr_reads(idx, read)
        elif isinstance(expr, SliceExpr):
            self.collect_expr_reads(expr.object, read)
            if expr.start:
                self.collect_expr_reads(expr.start, read)
            if expr.end:
                self.collect_expr_reads(expr.end, read)
        elif isinstance(expr, ListExpr):
            for elem in expr.elements:
                self.collect_expr_reads(elem, read)
        elif isinstance(expr, TupleExpr):
            for elem in expr.elements:
                self.collect_expr_reads(elem, read)
        elif isinstance(expr, RangeExpr):
            self.collect_expr_reads(expr.start, read)
            self.collect_expr_reads(expr.end, read)
        elif isinstance(expr, LambdaExpr):
            # Lambda body is a separate scope, but captures are reads
            self.collect_expr_reads(expr.body, read)

    def estimate_nursery_size(self, stmt: ForStmt, iteration_count: Optional[ir.Value]) -> ir.Value:
        """Estimate the nursery size needed for a loop.

        For range-based loops with known iteration count, we can estimate better.
        Default: 64MB which should handle most collection mutation patterns.

        For persistent vector appends, each operation creates:
        - New List struct (~32 bytes + 16 byte GC header = 48 bytes)
        - Path-copied tree nodes (~280 bytes per node, depth can be 4-6)
        - Potentially new tail buffer (~256+ bytes)
        Estimate ~1KB per iteration for safety.
        """
        cg = self.cg
        # Default size: 64MB for typical collection operations
        default_size = ir.Constant(ir.IntType(64), 64 * 1024 * 1024)

        # If we have an iteration count, scale based on expected per-iteration allocation
        # Persistent vector append creates ~1KB of garbage per iteration
        if iteration_count is not None:
            per_iteration = ir.Constant(ir.IntType(64), 1024)  # ~1KB per iteration for PV operations
            estimated = cg.builder.mul(iteration_count, per_iteration)
            # Use max of default and estimated
            use_estimated = cg.builder.icmp_unsigned(">", estimated, default_size)
            return cg.builder.select(use_estimated, estimated, default_size)

        return default_size

    def copy_collection_to_main_heap(self, var_name: str, var_ptr: ir.Value, elem_type: ir.Type) -> ir.Value:
        """Copy a collection from nursery to main heap.

        This is called when promoting loop-carried variables out of the nursery.
        For List types, creates a fresh copy in the main heap using runtime copy functions.

        var_ptr is typically an alloca of a pointer type (e.g., %struct.List**)
        We need to load the pointer, copy the collection, and store the new pointer back.
        """
        cg = self.cg
        # Load the collection pointer from the alloca
        if isinstance(var_ptr.type, ir.PointerType):
            loaded = cg.builder.load(var_ptr)

            # Check if the loaded value is a collection pointer
            if isinstance(loaded.type, ir.PointerType):
                pointee = loaded.type.pointee
                if hasattr(pointee, 'name'):
                    if 'List' in pointee.name:
                        # Copy the list to main heap using runtime function
                        copied = cg.builder.call(cg.list_copy, [loaded])
                        cg.builder.store(copied, var_ptr)
                        return copied
                    elif 'Array' in pointee.name:
                        # Copy the array to main heap using runtime function
                        copied = cg.builder.call(cg.array_copy, [loaded])
                        cg.builder.store(copied, var_ptr)
                        return copied
                    elif 'Map' in pointee.name:
                        # Copy the map to main heap using runtime function
                        copied = cg.builder.call(cg.map_copy, [loaded])
                        cg.builder.store(copied, var_ptr)
                        return copied
                    elif 'Set' in pointee.name:
                        # Copy the set to main heap using runtime function
                        copied = cg.builder.call(cg.set_copy, [loaded])
                        cg.builder.store(copied, var_ptr)
                        return copied

        return cg.builder.load(var_ptr)

    # ========================================================================
    # For Loop Generation
    # ========================================================================

    def generate_for(self, stmt: ForStmt):
        """Generate a for loop, optionally with nursery for collection mutations"""
        cg = self.cg
        func = cg.builder.function

        # Check if this loop needs a nursery for efficient garbage collection
        use_nursery = self.loop_needs_nursery(stmt) and hasattr(cg, 'gc') and cg.gc is not None

        # Check if iterable is a range() call
        if isinstance(stmt.iterable, CallExpr) and isinstance(stmt.iterable.callee, Identifier):
            if stmt.iterable.callee.name == "range":
                self.generate_range_for(stmt, use_nursery)
                return

        # Check if iterable is a RangeExpr (start..end)
        if isinstance(stmt.iterable, RangeExpr):
            self.generate_range_expr_for(stmt, use_nursery)
            return

        # Check if iterable is a list, array, or map
        if isinstance(stmt.iterable, (Identifier, ListExpr, CallExpr, IndexExpr, MethodCallExpr, MapExpr)):
            # Generate the iterable expression
            iterable = cg._generate_expression(stmt.iterable)
            if isinstance(iterable.type, ir.PointerType):
                pointee = iterable.type.pointee
                if hasattr(pointee, 'name') and pointee.name == "struct.List":
                    self.generate_list_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Array":
                    self.generate_array_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Map":
                    self.generate_map_for(stmt, iterable)
                    return
                if hasattr(pointee, 'name') and pointee.name == "struct.Set":
                    self.generate_set_for(stmt, iterable)
                    return

        # For other iterables, we need iterator protocol
        # For now, just execute body once as fallback
        for s in stmt.body:
            cg._generate_statement(s)

    def generate_range_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in range(start, end)

        If use_nursery is True, creates a nursery context for intermediate allocations
        and promotes loop-carried variables to main heap after the loop.
        """
        cg = self.cg
        func = cg.builder.function
        args = stmt.iterable.args

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
        var_name = stmt.var_name if stmt.var_name else "__loop_var"

        # PRE-ALLOCATE all local variables used in the loop body
        # This prevents stack overflow from allocas inside the loop
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate loop variable
        loop_var = cg.builder.alloca(ir.IntType(64), name=var_name)
        cg.builder.store(start, loop_var)
        cg.locals[var_name] = loop_var

        # Get loop-carried variables before creating nursery
        loop_carried_vars = []
        nursery_ctx = None
        nursery_active = None  # Track if nursery was successfully created
        if use_nursery:
            loop_carried_vars = self.get_loop_carried_vars(stmt)

            # Calculate iteration count for nursery size estimation
            iteration_count = cg.builder.sub(end, start)
            nursery_size = self.estimate_nursery_size(stmt, iteration_count)

            # Create nursery context
            nursery_type = ir.Constant(ir.IntType(64), 1)  # CONTEXT_NURSERY = 1
            nursery_ctx = cg.builder.call(cg.gc.gc_create_context, [nursery_size, nursery_type])

            # Check if nursery creation succeeded (malloc might fail for large sizes)
            null_ctx = ir.Constant(cg.gc.heap_context_type.as_pointer(), None)
            nursery_ok = cg.builder.icmp_unsigned("!=", nursery_ctx, null_ctx)

            # Store whether nursery is active for cleanup later
            nursery_active = cg.builder.alloca(ir.IntType(1), name="nursery_active")
            cg.builder.store(nursery_ok, nursery_active)

            # Only push nursery if it was created successfully
            push_nursery = func.append_basic_block("push_nursery")
            skip_nursery = func.append_basic_block("skip_nursery")
            cg.builder.cbranch(nursery_ok, push_nursery, skip_nursery)

            cg.builder.position_at_end(push_nursery)
            cg.builder.call(cg.gc.gc_push_context, [nursery_ctx])
            cg.builder.branch(skip_nursery)

            cg.builder.position_at_end(skip_nursery)

        # Create blocks
        cond_block = func.append_basic_block("for_cond")
        body_block = func.append_basic_block("for_body")
        inc_block = func.append_basic_block("for_inc")
        exit_block = func.append_basic_block("for_exit")

        # Save loop blocks
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        # Jump to condition
        cg.builder.branch(cond_block)

        # Condition
        cg.builder.position_at_end(cond_block)
        current = cg.builder.load(loop_var)
        cond = cg.builder.icmp_signed("<", current, end)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        # Increment
        cg.builder.position_at_end(inc_block)
        current = cg.builder.load(loop_var)
        next_val = cg.builder.add(current, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_val, loop_var)
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Clean up nursery if used
        if use_nursery and nursery_ctx is not None and nursery_active is not None:
            # Check if nursery was actually created successfully
            was_active = cg.builder.load(nursery_active)

            cleanup_nursery = func.append_basic_block("cleanup_nursery")
            after_cleanup = func.append_basic_block("after_cleanup")
            cg.builder.cbranch(was_active, cleanup_nursery, after_cleanup)

            cg.builder.position_at_end(cleanup_nursery)
            # Pop nursery from context stack
            cg.builder.call(cg.gc.gc_pop_context, [])

            # Promote loop-carried variables to main heap
            for lc_var in loop_carried_vars:
                if lc_var in cg.locals:
                    var_ptr = cg.locals[lc_var]
                    self.copy_collection_to_main_heap(lc_var, var_ptr, ir.IntType(64))

            # Destroy nursery (bulk-free all intermediate allocations)
            cg.builder.call(cg.gc.gc_destroy_context, [nursery_ctx])
            cg.builder.branch(after_cleanup)

            cg.builder.position_at_end(after_cleanup)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_range_expr_for(self, stmt: ForStmt, use_nursery: bool = False):
        """Generate for i in start..end

        If use_nursery is True, creates a nursery context for intermediate allocations
        and promotes loop-carried variables to main heap after the loop.
        """
        cg = self.cg
        func = cg.builder.function
        range_expr = stmt.iterable

        start = cg._generate_expression(range_expr.start)
        end = cg._generate_expression(range_expr.end)

        # Ensure i64
        if start.type != ir.IntType(64):
            start = cg._cast_value(start, ir.IntType(64))
        if end.type != ir.IntType(64):
            end = cg._cast_value(end, ir.IntType(64))

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Same as range_for
        loop_var = cg.builder.alloca(ir.IntType(64), name=stmt.var_name)
        cg.builder.store(start, loop_var)
        cg.locals[stmt.var_name] = loop_var

        # Get loop-carried variables before creating nursery
        loop_carried_vars = []
        nursery_ctx = None
        nursery_active = None  # Track if nursery was successfully created
        if use_nursery:
            loop_carried_vars = self.get_loop_carried_vars(stmt)

            # Calculate iteration count for nursery size estimation
            iteration_count = cg.builder.sub(end, start)
            nursery_size = self.estimate_nursery_size(stmt, iteration_count)

            # Create nursery context
            nursery_type = ir.Constant(ir.IntType(64), 1)  # CONTEXT_NURSERY = 1
            nursery_ctx = cg.builder.call(cg.gc.gc_create_context, [nursery_size, nursery_type])

            # Check if nursery creation succeeded (malloc might fail for large sizes)
            null_ctx = ir.Constant(cg.gc.heap_context_type.as_pointer(), None)
            nursery_ok = cg.builder.icmp_unsigned("!=", nursery_ctx, null_ctx)

            # Store whether nursery is active for cleanup later
            nursery_active = cg.builder.alloca(ir.IntType(1), name="nursery_active")
            cg.builder.store(nursery_ok, nursery_active)

            # Only push nursery if it was created successfully
            push_nursery = func.append_basic_block("push_nursery")
            skip_nursery = func.append_basic_block("skip_nursery")
            cg.builder.cbranch(nursery_ok, push_nursery, skip_nursery)

            cg.builder.position_at_end(push_nursery)
            cg.builder.call(cg.gc.gc_push_context, [nursery_ctx])
            cg.builder.branch(skip_nursery)

            cg.builder.position_at_end(skip_nursery)

        cond_block = func.append_basic_block("for_cond")
        body_block = func.append_basic_block("for_body")
        inc_block = func.append_basic_block("for_inc")
        exit_block = func.append_basic_block("for_exit")

        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        cg.builder.branch(cond_block)

        cg.builder.position_at_end(cond_block)
        current = cg.builder.load(loop_var)
        cond = cg.builder.icmp_signed("<", current, end)
        cg.builder.cbranch(cond, body_block, exit_block)

        cg.builder.position_at_end(body_block)
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        cg.builder.position_at_end(inc_block)
        current = cg.builder.load(loop_var)
        next_val = cg.builder.add(current, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_val, loop_var)
        cg.builder.branch(cond_block)

        cg.builder.position_at_end(exit_block)

        # Clean up nursery if used
        if use_nursery and nursery_ctx is not None and nursery_active is not None:
            # Check if nursery was actually created successfully
            was_active = cg.builder.load(nursery_active)

            cleanup_nursery = func.append_basic_block("cleanup_nursery")
            after_cleanup = func.append_basic_block("after_cleanup")
            cg.builder.cbranch(was_active, cleanup_nursery, after_cleanup)

            cg.builder.position_at_end(cleanup_nursery)
            # Pop nursery from context stack
            cg.builder.call(cg.gc.gc_pop_context, [])

            # Promote loop-carried variables to main heap
            for lc_var in loop_carried_vars:
                if lc_var in cg.locals:
                    var_ptr = cg.locals[lc_var]
                    self.copy_collection_to_main_heap(lc_var, var_ptr, ir.IntType(64))

            # Destroy nursery (bulk-free all intermediate allocations)
            cg.builder.call(cg.gc.gc_destroy_context, [nursery_ctx])
            cg.builder.branch(after_cleanup)

            cg.builder.position_at_end(after_cleanup)

        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_list_for(self, stmt: ForStmt, list_ptr: ir.Value):
        """Generate for item in list with destructuring support"""
        cg = self.cg
        func = cg.builder.function

        # Get list length
        list_len = cg.builder.call(cg.list_len, [list_ptr])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = cg.builder.alloca(ir.IntType(64), name="list_idx")
        cg.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("list_for_cond")
        body_block = func.append_basic_block("list_for_body")
        inc_block = func.append_basic_block("list_for_inc")
        exit_block = func.append_basic_block("list_for_exit")

        # Save loop blocks
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        # Jump to condition
        cg.builder.branch(cond_block)

        # Condition: index < len
        cg.builder.position_at_end(cond_block)
        current_idx = cg.builder.load(index_var)
        cond = cg.builder.icmp_signed("<", current_idx, list_len)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)

        # Get element: list[index]
        current_idx = cg.builder.load(index_var)
        elem_ptr = cg.builder.call(cg.list_get, [list_ptr, current_idx])

        # Determine element type from pattern or tracked type
        elem_type = self.get_list_element_type_for_pattern(stmt)
        typed_ptr = cg.builder.bitcast(elem_ptr, elem_type.as_pointer())
        elem_val = cg.builder.load(typed_ptr)

        # Bind pattern variables (supports destructuring)
        cg._bind_pattern(stmt.pattern, elem_val)

        # Track Coex type for loop variable (enables method calls on string, etc.)
        if isinstance(stmt.pattern, IdentifierPattern):
            # Get element type from tracked list type
            elem_coex_type = self.get_list_element_coex_type(stmt)
            if elem_coex_type:
                cg.var_coex_types[stmt.pattern.name] = elem_coex_type

        # Generate body statements
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        # Increment index
        cg.builder.position_at_end(inc_block)
        current_idx = cg.builder.load(index_var)
        next_idx = cg.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_idx, index_var)
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_array_for(self, stmt: ForStmt, array_ptr: ir.Value):
        """Generate for item in array with destructuring support"""
        cg = self.cg
        func = cg.builder.function

        # Get array length
        array_len = cg.builder.call(cg.array_len, [array_ptr])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = cg.builder.alloca(ir.IntType(64), name="array_idx")
        cg.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("array_for_cond")
        body_block = func.append_basic_block("array_for_body")
        inc_block = func.append_basic_block("array_for_inc")
        exit_block = func.append_basic_block("array_for_exit")

        # Save loop blocks
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        # Jump to condition
        cg.builder.branch(cond_block)

        # Condition: index < len
        cg.builder.position_at_end(cond_block)
        current_idx = cg.builder.load(index_var)
        cond = cg.builder.icmp_signed("<", current_idx, array_len)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)

        # Get element: array[index]
        current_idx = cg.builder.load(index_var)
        elem_ptr = cg.builder.call(cg.array_get, [array_ptr, current_idx])

        # Determine element type from pattern or tracked type
        elem_type = self.get_array_element_type_for_pattern(stmt)
        typed_ptr = cg.builder.bitcast(elem_ptr, elem_type.as_pointer())
        elem_val = cg.builder.load(typed_ptr)

        # Bind pattern variables (supports destructuring)
        cg._bind_pattern(stmt.pattern, elem_val)

        # Generate body statements
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        # Increment index
        cg.builder.position_at_end(inc_block)
        current_idx = cg.builder.load(index_var)
        next_idx = cg.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_idx, index_var)
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_map_for(self, stmt: ForStmt, map_ptr: ir.Value):
        """Generate for key in map - iterates over keys"""
        cg = self.cg
        func = cg.builder.function

        # Get keys as a list
        keys_list = cg.builder.call(cg.map_keys, [map_ptr])

        # Get list length
        list_len = cg.builder.call(cg.list_len, [keys_list])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = cg.builder.alloca(ir.IntType(64), name="map_idx")
        cg.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("map_for_cond")
        body_block = func.append_basic_block("map_for_body")
        inc_block = func.append_basic_block("map_for_inc")
        exit_block = func.append_basic_block("map_for_exit")

        # Save loop blocks
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        # Jump to condition
        cg.builder.branch(cond_block)

        # Condition: index < len
        cg.builder.position_at_end(cond_block)
        current_idx = cg.builder.load(index_var)
        cond = cg.builder.icmp_signed("<", current_idx, list_len)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)

        # Get key from list: keys_list[index]
        current_idx = cg.builder.load(index_var)
        elem_ptr = cg.builder.call(cg.list_get, [keys_list, current_idx])

        # Keys are stored as i64 - load and bind
        typed_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
        key_val = cg.builder.load(typed_ptr)

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_key"

        # Allocate and store key variable
        if var_name not in cg.locals:
            key_alloca = cg.builder.alloca(ir.IntType(64), name=var_name)
            cg.locals[var_name] = key_alloca
        cg.builder.store(key_val, cg.locals[var_name])

        # Generate body statements
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        # Increment index
        cg.builder.position_at_end(inc_block)
        current_idx = cg.builder.load(index_var)
        next_idx = cg.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_idx, index_var)
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_set_for(self, stmt: ForStmt, set_ptr: ir.Value):
        """Generate for elem in set - iterates over elements"""
        cg = self.cg
        func = cg.builder.function

        # Get elements as a list
        elems_list = cg.builder.call(cg.set_to_list, [set_ptr])

        # Get list length
        list_len = cg.builder.call(cg.list_len, [elems_list])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = cg.builder.alloca(ir.IntType(64), name="set_idx")
        cg.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("set_for_cond")
        body_block = func.append_basic_block("set_for_body")
        inc_block = func.append_basic_block("set_for_inc")
        exit_block = func.append_basic_block("set_for_exit")

        # Save loop blocks
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = inc_block

        # Jump to condition
        cg.builder.branch(cond_block)

        # Condition: index < len
        cg.builder.position_at_end(cond_block)
        current_idx = cg.builder.load(index_var)
        cond = cg.builder.icmp_signed("<", current_idx, list_len)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)

        # Get element from list: elems_list[index]
        current_idx = cg.builder.load(index_var)
        elem_ptr = cg.builder.call(cg.list_get, [elems_list, current_idx])

        # Elements are stored as i64 - load and bind
        typed_ptr = cg.builder.bitcast(elem_ptr, ir.IntType(64).as_pointer())
        elem_val = cg.builder.load(typed_ptr)

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_elem"

        # Allocate and store element variable
        if var_name not in cg.locals:
            elem_alloca = cg.builder.alloca(ir.IntType(64), name=var_name)
            cg.locals[var_name] = elem_alloca
        cg.builder.store(elem_val, cg.locals[var_name])

        # Generate body statements
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        if not cg.builder.block.is_terminated:
            cg.builder.branch(inc_block)

        # Increment index
        cg.builder.position_at_end(inc_block)
        current_idx = cg.builder.load(index_var)
        next_idx = cg.builder.add(current_idx, ir.Constant(ir.IntType(64), 1))
        cg.builder.store(next_idx, index_var)
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_for_assign(self, stmt: ForAssignStmt):
        """Generate results = for item in items expr"""
        cg = self.cg
        # This is syntactic sugar for map operation
        # For now, implement as a simple loop that doesn't return a list
        # Full implementation would need list creation

        # Just generate as regular for loop for now
        from ast_nodes import ExprStmt
        for_stmt = ForStmt(stmt.pattern, stmt.iterable, [ExprStmt(stmt.body_expr)])
        self.generate_for(for_stmt)

    # ========================================================================
    # Element Type Inference
    # ========================================================================

    def infer_list_element_type(self, expr) -> Optional[ir.Type]:
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

    def get_list_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for list elements based on pattern and tracked info."""
        cg = self.cg
        # First try to look up tracked element type
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in cg.list_element_types:
                return cg.list_element_types[var_name]
            # Also check var_coex_types for List element type
            if var_name in cg.var_coex_types:
                coex_type = cg.var_coex_types[var_name]
                if isinstance(coex_type, ListType):
                    return cg._get_llvm_type(coex_type.element_type)

        # Handle method call iterables (e.g., text.split("\n"))
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "split":
                # split() returns List<String>
                return cg.string_struct.as_pointer()
        elif isinstance(stmt.iterable, CallExpr):
            # CallExpr with MemberExpr callee (e.g., text.split("\n"))
            if isinstance(stmt.iterable.callee, MemberExpr):
                if stmt.iterable.callee.member == "split":
                    return cg.string_struct.as_pointer()

        # Infer from pattern structure
        pattern = stmt.pattern
        if isinstance(pattern, TuplePattern):
            # For tuple patterns, assume i64 for each element
            elem_types = [ir.IntType(64) for _ in pattern.elements]
            return ir.LiteralStructType(elem_types)

        # Default to i64
        return ir.IntType(64)

    def get_list_element_coex_type(self, stmt: ForStmt) -> Optional[Type]:
        """Get the Coex AST type for list elements (for var_coex_types tracking)."""
        cg = self.cg
        # Check iterable identifier in var_coex_types
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in cg.var_coex_types:
                coex_type = cg.var_coex_types[var_name]
                if isinstance(coex_type, ListType):
                    return coex_type.element_type

        # Handle method call iterables (e.g., text.split("\n"))
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "split":
                return PrimitiveType("string")
        elif isinstance(stmt.iterable, CallExpr):
            # CallExpr with MemberExpr callee (e.g., text.split("\n"))
            if isinstance(stmt.iterable.callee, MemberExpr):
                if stmt.iterable.callee.member == "split":
                    return PrimitiveType("string")

        return None

    def get_array_element_type_for_pattern(self, stmt: ForStmt) -> ir.Type:
        """Get the LLVM type for array elements based on pattern and tracked info."""
        cg = self.cg
        # First try to look up tracked element type
        if isinstance(stmt.iterable, Identifier):
            var_name = stmt.iterable.name
            if var_name in cg.array_element_types:
                return cg.array_element_types[var_name]

        # If iterable is a method call like list.packed(), try to get list's element type
        if isinstance(stmt.iterable, MethodCallExpr):
            if stmt.iterable.method == "packed" and isinstance(stmt.iterable.object, Identifier):
                list_var = stmt.iterable.object.name
                if list_var in cg.list_element_types:
                    return cg.list_element_types[list_var]

        # Infer from pattern structure
        pattern = stmt.pattern
        if isinstance(pattern, TuplePattern):
            # For tuple patterns, assume i64 for each element
            elem_types = [ir.IntType(64) for _ in pattern.elements]
            return ir.LiteralStructType(elem_types)

        # Default to i64
        return ir.IntType(64)
