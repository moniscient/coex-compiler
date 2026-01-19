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
    ForStmt, ForAssignStmt, FirstAssignStmt, MostAssignStmt,
    Stmt, Expr, VarDecl, IfStmt, WhileStmt,
    Assignment, ExprStmt, ReturnStmt, CallExpr, Identifier, MemberExpr,
    MethodCallExpr, BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
    SliceExpr, ListExpr, TupleExpr, RangeExpr, LambdaExpr, MapExpr,
    IdentifierPattern, WildcardPattern, TuplePattern, Type, ListType,
    PrimitiveType, IntLiteral, FloatLiteral, BoolLiteral, FunctionKind,
    FunctionDecl, Parameter
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class LoopGenerator:
    """Generates loop-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg
        # Counter for generating unique synthetic thread names
        self._synthetic_thread_counter = 0

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
                if hasattr(pointee, 'name') and pointee.name == "struct.String":
                    self.generate_string_for(stmt, iterable)
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        # Task's inject_safepoint also calls gc_safepoint, so we only need
        # to call it directly if not in a task context
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_string_for(self, stmt: ForStmt, string_ptr: ir.Value):
        """Generate for char in string - iterates over characters (bytes)"""
        cg = self.cg
        func = cg.builder.function

        # Get string length
        string_len = cg.builder.call(cg.string_len, [string_ptr])

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Allocate index variable
        index_var = cg.builder.alloca(ir.IntType(64), name="str_idx")
        cg.builder.store(ir.Constant(ir.IntType(64), 0), index_var)

        # Create blocks
        cond_block = func.append_basic_block("str_for_cond")
        body_block = func.append_basic_block("str_for_body")
        inc_block = func.append_basic_block("str_for_inc")
        exit_block = func.append_basic_block("str_for_exit")

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
        cond = cg.builder.icmp_signed("<", current_idx, string_len)
        cg.builder.cbranch(cond, body_block, exit_block)

        # Body
        cg.builder.position_at_end(body_block)

        # Get character at index: string_get(string_ptr, index) -> i64 (byte value)
        current_idx = cg.builder.load(index_var)
        char_val = cg.builder.call(cg.string_get, [string_ptr, current_idx])

        # Get variable name from pattern
        var_name = stmt.var_name if stmt.var_name else "__loop_char"

        # Allocate and store character variable
        if var_name not in cg.locals:
            char_alloca = cg.builder.alloca(ir.IntType(64), name=var_name)
            cg.locals[var_name] = char_alloca
        cg.builder.store(char_val, cg.locals[var_name])

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
        # Inject safepoint at loop back-edge for GC watermark acknowledgment
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, exit_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])
        cg.builder.branch(cond_block)

        # Exit
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def generate_for_assign(self, stmt: ForAssignStmt):
        """Generate results = for item in items expr ~

        When the body expression is a task call, this generates parallel
        execution: spawn all tasks, join all, collect results in order.

        For non-thread expressions, generates sequential map operation.
        """
        cg = self.cg

        # Check if body is a thread call
        is_thread_call = self._is_thread_call(stmt.body_expr)

        if is_thread_call and cg._thread is not None:
            result = self._generate_parallel_for_assign(stmt)
        else:
            result = self._generate_sequential_for_assign(stmt)

        # Store result in target variable
        if stmt.target in cg.locals:
            cg.builder.store(result, cg.locals[stmt.target])
        else:
            var_ptr = cg.builder.alloca(result.type, name=stmt.target)
            cg.locals[stmt.target] = var_ptr
            cg.builder.store(result, var_ptr)

    def _is_thread_call(self, expr: Expr) -> bool:
        """Check if expression is a call to a thread function."""
        cg = self.cg
        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                name = expr.callee.name
                if name in cg.func_decls:
                    return cg.func_decls[name].kind == FunctionKind.THREAD
        return False

    def _is_task_call(self, expr: Expr) -> bool:
        """Check if expression is a call to a task or thread function."""
        cg = self.cg
        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                name = expr.callee.name
                if name in cg.func_decls:
                    kind = cg.func_decls[name].kind
                    return kind in (FunctionKind.TASK, FunctionKind.THREAD)
        return False

    def _extract_body_expr(self, body: list) -> Optional[Expr]:
        """Extract the expression from a block body.

        For first/most, the body should produce a value. This helper
        extracts the expression from a single-statement body where
        that statement is an expression (like a task call).

        Returns None if the body can't be reduced to a single expression.
        """
        from ast_nodes import ExprStmt, ReturnStmt
        if not body:
            return None
        if len(body) == 1:
            stmt = body[0]
            # If it's an expression statement, return the expression
            if isinstance(stmt, ExprStmt):
                return stmt.expr
            # If it's a return statement, return the return value expression
            if isinstance(stmt, ReturnStmt):
                return stmt.value
            # If it's directly an expression (CallExpr, etc.), return it
            if isinstance(stmt, Expr):
                return stmt
        return None

    # ========================================================================
    # Synthetic Thread Generation for Complex Bodies
    # ========================================================================

    def _generate_synthetic_task_for_body(
        self,
        body: PyList[Stmt],
        pattern,
        iterable: Expr,
        prefix: str = "first"
    ) -> CallExpr:
        """Generate a synthetic task function for a complex first/most body.

        When a first/most body contains multiple statements or control flow
        (if/else, etc.), we can't directly extract a single task call. Instead,
        we generate a synthetic task function that wraps the body and call it.

        This generates TASK functions (lightweight coroutines) rather than
        THREAD functions (pthreads), enabling massive parallelism.

        Args:
            body: The list of statements in the body
            pattern: The loop variable pattern (str or IdentifierPattern)
            iterable: The iterable expression (to infer element type)
            prefix: Prefix for function name ("first" or "most")

        Returns:
            A CallExpr that calls the synthetic task with the loop variable
        """
        cg = self.cg

        # Generate unique name
        self._synthetic_thread_counter += 1
        func_name = f"__{prefix}_body_{self._synthetic_thread_counter}"

        # Get the loop variable name
        if isinstance(pattern, str):
            var_name = pattern
        elif isinstance(pattern, IdentifierPattern):
            var_name = pattern.name
        else:
            var_name = "_item"

        # Infer element type from iterable
        elem_coex_type = self._infer_element_type_from_iterable(iterable)

        # Infer return type from body
        return_type = self._infer_return_type_from_body(body)

        # Transform body: ensure last expression is returned
        transformed_body = self._transform_body_for_return(body)

        # Create the FunctionDecl AST node - use TASK for lightweight coroutines
        func_decl = FunctionDecl(
            kind=FunctionKind.TASK,
            name=func_name,
            type_params=[],
            params=[Parameter(name=var_name, type_annotation=elem_coex_type)],
            return_type=return_type,
            body=transformed_body,
            annotations=[]
        )

        # Store the declaration for later reference
        cg.func_decls[func_name] = func_decl

        # Declare the function (creates LLVM signature)
        cg._functions.declare_function(func_decl)

        # Generate the function body
        # Save current function context
        saved_function = cg.current_function
        saved_locals = cg.locals.copy()
        saved_builder = cg.builder

        # Generate the synthetic function
        cg._functions.generate_function(func_decl)

        # Restore context
        cg.current_function = saved_function
        cg.locals = saved_locals
        cg.builder = saved_builder

        # Create a CallExpr to the synthetic function
        call_expr = CallExpr(
            callee=Identifier(name=func_name),
            args=[Identifier(name=var_name)]
        )

        return call_expr

    def _infer_element_type_from_iterable(self, iterable: Expr) -> Type:
        """Infer the Coex element type from an iterable expression."""
        cg = self.cg

        # Handle list literals
        if isinstance(iterable, ListExpr):
            if iterable.elements:
                # Infer from first element
                first_elem = iterable.elements[0]
                return cg._infer_type_from_expr(first_elem)
            return PrimitiveType("int")

        # Handle identifiers (variable references)
        if isinstance(iterable, Identifier):
            var_name = iterable.name
            if var_name in cg.var_coex_types:
                coex_type = cg.var_coex_types[var_name]
                if isinstance(coex_type, ListType):
                    return coex_type.element_type

        # Handle range expressions
        if isinstance(iterable, RangeExpr):
            return PrimitiveType("int")

        # Default to int
        return PrimitiveType("int")

    def _infer_return_type_from_body(self, body: PyList[Stmt]) -> Type:
        """Infer the return type from a body's statements.

        Looks for:
        1. Explicit return statements
        2. The final expression (if it's an expression statement)
        3. Task/thread calls (uses the callee's return type)
        """
        cg = self.cg

        # Find all expressions that could produce the return value
        def find_return_exprs(stmts: PyList[Stmt]) -> PyList[Expr]:
            exprs = []
            for stmt in stmts:
                if isinstance(stmt, ReturnStmt) and stmt.value:
                    exprs.append(stmt.value)
                elif isinstance(stmt, ExprStmt):
                    exprs.append(stmt.expr)
                elif isinstance(stmt, IfStmt):
                    # Check both branches
                    exprs.extend(find_return_exprs(stmt.then_body))
                    if stmt.else_body:
                        exprs.extend(find_return_exprs(stmt.else_body))
            return exprs

        return_exprs = find_return_exprs(body)

        # Try to infer type from the expressions
        for expr in return_exprs:
            inferred = self._infer_type_from_expr_deep(expr)
            if inferred:
                return inferred

        # Default to int
        return PrimitiveType("int")

    def _infer_type_from_expr_deep(self, expr: Expr) -> Optional[Type]:
        """Infer type from an expression, handling calls specially."""
        cg = self.cg

        if isinstance(expr, CallExpr):
            if isinstance(expr.callee, Identifier):
                func_name = expr.callee.name
                if func_name in cg.func_decls:
                    decl = cg.func_decls[func_name]
                    if decl.return_type:
                        return decl.return_type

        # Use the standard type inference
        try:
            return cg._infer_type_from_expr(expr)
        except:
            return None

    def _transform_body_for_return(self, body: PyList[Stmt]) -> PyList[Stmt]:
        """Transform a body to ensure it returns a value.

        If the last statement is an expression statement, convert it to a return.
        For if/else, recursively transform both branches.
        """
        if not body:
            return [ReturnStmt(value=IntLiteral(value=0))]

        # Copy body to avoid mutation
        result = list(body)

        # Transform the last statement
        last = result[-1]

        if isinstance(last, ExprStmt):
            # Convert to return statement
            result[-1] = ReturnStmt(value=last.expr)
        elif isinstance(last, IfStmt):
            # Transform both branches
            new_then = self._transform_body_for_return(last.then_body)
            # Transform else_if_clauses
            new_else_if_clauses = []
            for elif_cond, elif_body in (last.else_if_clauses or []):
                new_elif_body = self._transform_body_for_return(elif_body)
                new_else_if_clauses.append((elif_cond, new_elif_body))
            new_else = self._transform_body_for_return(last.else_body) if last.else_body else None
            result[-1] = IfStmt(
                condition=last.condition,
                then_body=new_then,
                else_if_clauses=new_else_if_clauses,
                else_body=new_else
            )
        elif isinstance(last, ReturnStmt):
            # Already returns, no change needed
            pass
        elif isinstance(last, Expr):
            # Direct expression (shouldn't happen normally)
            result[-1] = ReturnStmt(value=last)
        # For other statements (VarDecl, etc.), leave as-is
        # The actual return should be handled elsewhere

        return result

    def _generate_sequential_first(self, stmt: FirstAssignStmt, body_expr: Expr):
        """Generate sequential first: iterate until first successful result.

        For tasks, executes each task in sequence and returns the first result.
        This is a sequential fallback when true parallel execution isn't available.
        """
        cg = self.cg
        i64 = ir.IntType(64)

        # Get iterable length and iterator
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        # Allocate result variable
        if stmt.target not in cg.locals:
            var_ptr = cg.builder.alloca(i64, name=stmt.target)
            cg.locals[stmt.target] = var_ptr
        result_ptr = cg.locals[stmt.target]
        cg.builder.store(ir.Constant(i64, 0), result_ptr)  # Default value

        # Check for empty iterable
        is_empty = cg.builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        func = cg.builder.block.function
        not_empty_block = func.append_basic_block("first_not_empty")
        done_block = func.append_basic_block("first_done")

        cg.builder.cbranch(is_empty, done_block, not_empty_block)

        # If not empty, execute first task and store result
        cg.builder.position_at_end(not_empty_block)

        # Get first element
        first_idx = ir.Constant(i64, 0)
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, first_idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        # Bind loop variable
        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Execute body expression (task call)
        result = cg._generate_expression(body_expr)

        # Store result
        cg.builder.store(result, result_ptr)
        cg.builder.branch(done_block)

        # Done
        cg.builder.position_at_end(done_block)

    def _generate_scheduler_first(self, stmt: FirstAssignStmt, body_expr: Expr):
        """Generate parallel first using scheduler batch spawn APIs.

        For tasks, spawns all tasks concurrently via the scheduler and returns
        the first completed result. Uses FirstContext for race semantics.
        """
        cg = self.cg
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        # Get task call info
        call_expr = body_expr
        task_name = call_expr.callee.name

        # Get task transformer and batch spawn APIs
        task_xform = cg._task

        # Check if task has a state machine
        if not task_xform.has_state_machine(task_name):
            # Fall back to sequential execution for tasks without state machines
            self._generate_sequential_first(stmt, body_expr)
            return

        # Get step function and frame info
        step_fn = task_xform.get_task_step_function(task_name)
        frame_info = task_xform.get_task_frame_info(task_name)

        if step_fn is None or frame_info is None:
            self._generate_sequential_first(stmt, body_expr)
            return

        # Get iterable and its length
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        # Allocate result variable
        if stmt.target not in cg.locals:
            var_ptr = cg.builder.alloca(i64, name=stmt.target)
            cg.locals[stmt.target] = var_ptr
        result_ptr = cg.locals[stmt.target]
        cg.builder.store(ir.Constant(i64, 0), result_ptr)  # Default value

        func = cg.builder.block.function

        # Check for empty iterable
        is_empty = cg.builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        not_empty_block = func.append_basic_block("scheduler_first_not_empty")
        done_block = func.append_basic_block("scheduler_first_done")

        cg.builder.cbranch(is_empty, done_block, not_empty_block)

        # Not empty: create FirstContext and spawn tasks
        cg.builder.position_at_end(not_empty_block)

        # Create FirstContext
        first_ctx = cg.builder.call(
            task_xform.get_first_context_create(),
            [list_len],
            name="first_ctx"
        )

        # Spawn loop
        spawn_header = func.append_basic_block("first_spawn_header")
        spawn_body = func.append_basic_block("first_spawn_body")
        spawn_done = func.append_basic_block("first_spawn_done")

        idx_alloca = cg.builder.alloca(i64, name="first_spawn_idx")
        cg.builder.store(ir.Constant(i64, 0), idx_alloca)
        cg.builder.branch(spawn_header)

        # Spawn loop header
        cg.builder.position_at_end(spawn_header)
        idx = cg.builder.load(idx_alloca)
        cond = cg.builder.icmp_signed("<", idx, list_len)
        cg.builder.cbranch(cond, spawn_body, spawn_done)

        # Spawn loop body
        cg.builder.position_at_end(spawn_body)

        # Get element and bind loop variable
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate task arguments
        arg_values = []
        for arg in call_expr.args:
            arg_val = cg._generate_expression(arg)
            arg_values.append(arg_val)

        # Allocate frame for this task
        frame_ptr = task_xform.allocate_task_frame(task_name, arg_values, cg.builder)

        # Get step function pointer as i8*
        step_fn_ptr = cg.builder.bitcast(step_fn, i8_ptr)

        # Spawn task into FirstContext
        cg.builder.call(
            task_xform.get_first_spawn_task(),
            [first_ctx, idx, frame_ptr, step_fn_ptr]
        )

        # Increment index
        cg.builder.store(cg.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
        cg.builder.branch(spawn_header)

        # After spawning: wait for first result
        cg.builder.position_at_end(spawn_done)
        result = cg.builder.call(
            task_xform.get_first_wait(),
            [first_ctx],
            name="first_result"
        )

        # Store result
        cg.builder.store(result, result_ptr)

        # Cleanup FirstContext
        cg.builder.call(task_xform.get_first_context_destroy(), [first_ctx])

        cg.builder.branch(done_block)

        # Done
        cg.builder.position_at_end(done_block)

    def _generate_scheduler_most(self, stmt: MostAssignStmt, body_expr: Expr):
        """Generate parallel most using scheduler batch spawn APIs.

        For tasks, spawns all tasks concurrently via the scheduler and waits
        for all to complete. Uses MostContext to collect all results.
        """
        cg = self.cg
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()
        elem_size = ir.Constant(i64, 8)

        # Get task call info
        call_expr = body_expr
        task_name = call_expr.callee.name

        # Get task transformer and batch spawn APIs
        task_xform = cg._task

        # Check if task has a state machine
        if not task_xform.has_state_machine(task_name):
            # Fall back to parallel for-assign for tasks without state machines
            self._generate_most_fallback(stmt, body_expr)
            return

        # Get step function and frame info
        step_fn = task_xform.get_task_step_function(task_name)
        frame_info = task_xform.get_task_frame_info(task_name)

        if step_fn is None or frame_info is None:
            self._generate_most_fallback(stmt, body_expr)
            return

        # Get iterable and its length
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        # Create result and error lists
        results_list = cg.builder.call(cg.list_new, [elem_size])
        errors_list = cg.builder.call(cg.list_new, [elem_size])

        # Allocate result variables
        if stmt.results_target in cg.locals:
            cg.builder.store(results_list, cg.locals[stmt.results_target])
        else:
            results_ptr = cg.builder.alloca(cg.list_struct.as_pointer(), name=stmt.results_target)
            cg.locals[stmt.results_target] = results_ptr
            cg.builder.store(results_list, results_ptr)

        if stmt.errors_target in cg.locals:
            cg.builder.store(errors_list, cg.locals[stmt.errors_target])
        else:
            errors_ptr = cg.builder.alloca(cg.list_struct.as_pointer(), name=stmt.errors_target)
            cg.locals[stmt.errors_target] = errors_ptr
            cg.builder.store(errors_list, errors_ptr)

        func = cg.builder.block.function

        # Check for empty iterable
        is_empty = cg.builder.icmp_signed("==", list_len, ir.Constant(i64, 0))
        not_empty_block = func.append_basic_block("scheduler_most_not_empty")
        done_block = func.append_basic_block("scheduler_most_done")

        cg.builder.cbranch(is_empty, done_block, not_empty_block)

        # Not empty: create MostContext and spawn tasks
        cg.builder.position_at_end(not_empty_block)

        # Create MostContext
        most_ctx = cg.builder.call(
            task_xform.get_most_context_create(),
            [list_len],
            name="most_ctx"
        )

        # Spawn loop
        spawn_header = func.append_basic_block("most_spawn_header")
        spawn_body = func.append_basic_block("most_spawn_body")
        spawn_done = func.append_basic_block("most_spawn_done")

        idx_alloca = cg.builder.alloca(i64, name="most_spawn_idx")
        cg.builder.store(ir.Constant(i64, 0), idx_alloca)
        cg.builder.branch(spawn_header)

        # Spawn loop header
        cg.builder.position_at_end(spawn_header)
        idx = cg.builder.load(idx_alloca)
        cond = cg.builder.icmp_signed("<", idx, list_len)
        cg.builder.cbranch(cond, spawn_body, spawn_done)

        # Spawn loop body
        cg.builder.position_at_end(spawn_body)

        # Get element and bind loop variable
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate task arguments
        arg_values = []
        for arg in call_expr.args:
            arg_val = cg._generate_expression(arg)
            arg_values.append(arg_val)

        # Allocate frame for this task
        frame_ptr = task_xform.allocate_task_frame(task_name, arg_values, cg.builder)

        # Get step function pointer as i8*
        step_fn_ptr = cg.builder.bitcast(step_fn, i8_ptr)

        # Spawn task into MostContext
        cg.builder.call(
            task_xform.get_most_spawn_task(),
            [most_ctx, frame_ptr, step_fn_ptr]
        )

        # Increment index
        cg.builder.store(cg.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
        cg.builder.branch(spawn_header)

        # After spawning: wait for all results
        cg.builder.position_at_end(spawn_done)

        # Allocate space for results array and count
        # Alloca creates a pointer to the type, so alloca(i8*) gives us i8**
        results_ptr_ptr = cg.builder.alloca(i8_ptr, name="results_arr_ptr")
        results_count_ptr = cg.builder.alloca(i64, name="results_count")

        cg.builder.call(
            task_xform.get_most_wait(),
            [most_ctx, results_ptr_ptr, results_count_ptr]
        )

        # Get results array and count
        results_arr = cg.builder.load(results_ptr_ptr)
        results_count = cg.builder.load(results_count_ptr)

        # Copy results to list
        copy_header = func.append_basic_block("most_copy_header")
        copy_body = func.append_basic_block("most_copy_body")
        copy_done = func.append_basic_block("most_copy_done")

        copy_idx = cg.builder.alloca(i64, name="copy_idx")
        cg.builder.store(ir.Constant(i64, 0), copy_idx)
        cg.builder.branch(copy_header)

        cg.builder.position_at_end(copy_header)
        ci = cg.builder.load(copy_idx)
        copy_cond = cg.builder.icmp_signed("<", ci, results_count)
        cg.builder.cbranch(copy_cond, copy_body, copy_done)

        cg.builder.position_at_end(copy_body)
        # Get result value from array - results_arr is i64* (array of int64 values)
        result_arr_typed = cg.builder.bitcast(results_arr, i64.as_pointer())
        result_ptr = cg.builder.gep(result_arr_typed, [ci], inbounds=True)
        result_val = cg.builder.load(result_ptr)

        # Append to results list - list_append takes (list, elem_ptr, elem_size)
        current_results_list = cg.builder.load(cg.locals[stmt.results_target])
        temp_ptr = cg.builder.alloca(i64, name="result_temp")
        cg.builder.store(result_val, temp_ptr)
        temp_i8_ptr = cg.builder.bitcast(temp_ptr, i8_ptr)
        elem_size = ir.Constant(i64, 8)
        new_results_list = cg.builder.call(
            cg.list_append, [current_results_list, temp_i8_ptr, elem_size]
        )
        cg.builder.store(new_results_list, cg.locals[stmt.results_target])

        # Increment copy index
        cg.builder.store(cg.builder.add(ci, ir.Constant(i64, 1)), copy_idx)
        cg.builder.branch(copy_header)

        cg.builder.position_at_end(copy_done)

        # Cleanup MostContext
        cg.builder.call(task_xform.get_most_context_destroy(), [most_ctx])

        cg.builder.branch(done_block)

        # Done
        cg.builder.position_at_end(done_block)

    def _generate_most_fallback(self, stmt: MostAssignStmt, body_expr: Expr):
        """Fallback for most when scheduler isn't available."""
        cg = self.cg
        i64 = ir.IntType(64)
        elem_size = ir.Constant(i64, 8)

        # Use for-collection fallback
        for_assign = ForAssignStmt(
            target="_most_temp",
            pattern=stmt.pattern,
            iterable=stmt.iterable,
            body_expr=body_expr
        )
        result_list = self._generate_parallel_for_assign(for_assign)
        errors_list = cg.builder.call(cg.list_new, [elem_size])

        # Store results and errors
        if stmt.results_target in cg.locals:
            cg.builder.store(result_list, cg.locals[stmt.results_target])
        else:
            results_ptr = cg.builder.alloca(cg.list_struct.as_pointer(), name=stmt.results_target)
            cg.locals[stmt.results_target] = results_ptr
            cg.builder.store(result_list, results_ptr)

        if stmt.errors_target in cg.locals:
            cg.builder.store(errors_list, cg.locals[stmt.errors_target])
        else:
            errors_ptr = cg.builder.alloca(cg.list_struct.as_pointer(), name=stmt.errors_target)
            cg.locals[stmt.errors_target] = errors_ptr
            cg.builder.store(errors_list, errors_ptr)

    def _generate_sequential_for_assign(self, stmt: ForAssignStmt) -> ir.Value:
        """Generate sequential map: iterate and collect results in list."""
        cg = self.cg
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Create result list
        elem_size = ir.Constant(i64, 8)  # Results are i64 handles
        result_list = cg.builder.call(cg.list_new, [elem_size])
        result_alloca = cg.builder.alloca(cg.list_struct.as_pointer(), name="result_list")
        cg.builder.store(result_list, result_alloca)

        # Get iterable length and iterator
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        # Loop blocks
        func = cg.builder.block.function
        loop_header = func.append_basic_block("for_assign_header")
        loop_body = func.append_basic_block("for_assign_body")
        loop_end = func.append_basic_block("for_assign_end")

        # Initialize index
        idx_alloca = cg.builder.alloca(i64, name="for_idx")
        cg.builder.store(ir.Constant(i64, 0), idx_alloca)
        cg.builder.branch(loop_header)

        # Loop header: check index < length
        cg.builder.position_at_end(loop_header)
        idx = cg.builder.load(idx_alloca)
        cond = cg.builder.icmp_signed("<", idx, list_len)
        cg.builder.cbranch(cond, loop_body, loop_end)

        # Loop body: get element, evaluate expression, append result
        cg.builder.position_at_end(loop_body)

        # Get current element
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        # Bind loop variable
        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate body expression
        body_result = cg._generate_expression(stmt.body_expr)

        # Append to result list
        temp = cg.builder.alloca(i64, name="temp")
        if body_result.type != i64:
            body_result = cg._cast_value(body_result, i64)
        cg.builder.store(body_result, temp)
        temp_ptr = cg.builder.bitcast(temp, i8_ptr)

        current_list = cg.builder.load(result_alloca)
        new_list = cg.builder.call(cg.list_append, [current_list, temp_ptr, elem_size])
        cg.builder.store(new_list, result_alloca)

        # Increment index
        next_idx = cg.builder.add(idx, ir.Constant(i64, 1))
        cg.builder.store(next_idx, idx_alloca)
        cg.builder.branch(loop_header)

        # End
        cg.builder.position_at_end(loop_end)
        return cg.builder.load(result_alloca)

    def _generate_parallel_for_assign(self, stmt: ForAssignStmt) -> ir.Value:
        """Generate parallel map: spawn all tasks, join all, collect results.

        Pattern:
        1. Count items in collection
        2. Allocate arrays for thread handles and closures
        3. Spawn loop: for each item, spawn task, store handle/closure
        4. Join loop: for each spawned task, join thread
        5. Collect loop: for each closure, extract result, append to list
        6. Cleanup: free closures
        7. Return result list
        """
        cg = self.cg
        task_gen = cg._thread
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Extract task call info
        call_expr = stmt.body_expr
        if not isinstance(call_expr, CallExpr) or not isinstance(call_expr.callee, Identifier):
            # Fallback to sequential
            return self._generate_sequential_for_assign(stmt)

        task_name = call_expr.callee.name
        task_decl = cg.func_decls[task_name]
        task_llvm_func = cg.functions[task_name]

        # Get iterable and its length
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        func = cg.builder.block.function

        # Allocate arrays for handles and closures (max 1024 tasks)
        # For larger collections, we'd need dynamic allocation
        max_tasks = 1024
        thread_handle_arr = cg.builder.alloca(
            ir.ArrayType(i64, max_tasks), name="task_handles"
        )
        closure_ptr_arr = cg.builder.alloca(
            ir.ArrayType(task_gen.closure_ptr_type, max_tasks), name="task_closures"
        )

        # Track actual count
        count_alloca = cg.builder.alloca(i64, name="task_count")
        cg.builder.store(ir.Constant(i64, 0), count_alloca)

        # =====================================================================
        # Phase 1: Spawn loop - spawn all tasks
        # =====================================================================
        spawn_header = func.append_basic_block("spawn_header")
        spawn_body = func.append_basic_block("spawn_body")
        spawn_done = func.append_basic_block("spawn_done")

        idx_alloca = cg.builder.alloca(i64, name="spawn_idx")
        cg.builder.store(ir.Constant(i64, 0), idx_alloca)
        cg.builder.branch(spawn_header)

        # Header: check idx < len
        cg.builder.position_at_end(spawn_header)
        idx = cg.builder.load(idx_alloca)
        cond = cg.builder.icmp_signed("<", idx, list_len)
        cg.builder.cbranch(cond, spawn_body, spawn_done)

        # Body: get element, spawn task
        cg.builder.position_at_end(spawn_body)

        # Get current element from iterable
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        # Bind loop variable for argument evaluation
        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate task call arguments
        arg_values = []
        for arg in call_expr.args:
            arg_val = cg._generate_expression(arg)
            arg_values.append(arg_val)

        # Spawn the task
        thread_handle, closure_ptr = task_gen.spawn_task(
            cg.builder,
            task_decl,
            task_llvm_func,
            arg_values,
            add_to_nursery=False  # We manage our own arrays
        )

        # Store handle and closure
        idx_i32 = cg.builder.trunc(idx, i32)
        handle_slot = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), idx_i32],
            inbounds=True
        )
        cg.builder.store(thread_handle, handle_slot)

        closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), idx_i32],
            inbounds=True
        )
        cg.builder.store(closure_ptr, closure_slot)

        # Increment spawn count
        current_count = cg.builder.load(count_alloca)
        cg.builder.store(cg.builder.add(current_count, ir.Constant(i64, 1)), count_alloca)

        # Increment idx
        next_idx = cg.builder.add(idx, ir.Constant(i64, 1))
        cg.builder.store(next_idx, idx_alloca)
        cg.builder.branch(spawn_header)

        cg.builder.position_at_end(spawn_done)
        final_count = cg.builder.load(count_alloca)

        # =====================================================================
        # Phase 2: Join loop - wait for all tasks
        # =====================================================================
        join_header = func.append_basic_block("join_header")
        join_body = func.append_basic_block("join_body")
        join_done = func.append_basic_block("join_done")

        join_idx = cg.builder.alloca(i64, name="join_idx")
        cg.builder.store(ir.Constant(i64, 0), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_header)
        j_idx = cg.builder.load(join_idx)
        j_cond = cg.builder.icmp_signed("<", j_idx, final_count)
        cg.builder.cbranch(j_cond, join_body, join_done)

        cg.builder.position_at_end(join_body)
        j_idx_i32 = cg.builder.trunc(j_idx, i32)

        # Load thread handle
        handle_ptr = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), j_idx_i32],
            inbounds=True
        )
        thread_handle = cg.builder.load(handle_ptr)

        # Join thread
        cg.builder.call(task_gen.task_join, [thread_handle])

        # Increment
        cg.builder.store(cg.builder.add(j_idx, ir.Constant(i64, 1)), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_done)

        # =====================================================================
        # Phase 3: Collect loop - gather results into list
        # =====================================================================
        elem_size = ir.Constant(i64, 8)
        result_list = cg.builder.call(cg.list_new, [elem_size])
        result_alloca = cg.builder.alloca(cg.list_struct.as_pointer(), name="result_list")
        cg.builder.store(result_list, result_alloca)

        collect_header = func.append_basic_block("collect_header")
        collect_body = func.append_basic_block("collect_body")
        collect_done = func.append_basic_block("collect_done")

        collect_idx = cg.builder.alloca(i64, name="collect_idx")
        cg.builder.store(ir.Constant(i64, 0), collect_idx)
        cg.builder.branch(collect_header)

        cg.builder.position_at_end(collect_header)
        c_idx = cg.builder.load(collect_idx)
        c_cond = cg.builder.icmp_signed("<", c_idx, final_count)
        cg.builder.cbranch(c_cond, collect_body, collect_done)

        cg.builder.position_at_end(collect_body)
        c_idx_i32 = cg.builder.trunc(c_idx, i32)

        # Load closure
        closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), c_idx_i32],
            inbounds=True
        )
        closure_ptr = cg.builder.load(closure_slot)

        # Extract result from closure
        result_field = cg.builder.gep(
            closure_ptr,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True
        )
        result_ptr = cg.builder.load(result_field)
        result_val = cg.builder.ptrtoint(result_ptr, i64)

        # Append to result list
        temp = cg.builder.alloca(i64, name="result_temp")
        cg.builder.store(result_val, temp)
        temp_ptr = cg.builder.bitcast(temp, i8_ptr)

        current_list = cg.builder.load(result_alloca)
        new_list = cg.builder.call(cg.list_append, [current_list, temp_ptr, elem_size])
        cg.builder.store(new_list, result_alloca)

        # Free the closure
        cg.builder.call(task_gen.closure_free, [closure_ptr])

        # Increment
        cg.builder.store(cg.builder.add(c_idx, ir.Constant(i64, 1)), collect_idx)
        cg.builder.branch(collect_header)

        cg.builder.position_at_end(collect_done)
        return cg.builder.load(result_alloca)

    # ========================================================================
    # First-Assign Statement (Racing)
    # ========================================================================

    def generate_first_assign(self, stmt: FirstAssignStmt):
        """Generate result = first item in items expr ~

        Spawns all tasks in parallel and returns the first successful result.
        Remaining tasks are cancelled once a result is obtained.

        Racing algorithm:
        1. Spawn all tasks, collect handles and closures
        2. Call task_wait_any to wait for first completion
        3. Cancel all other tasks
        4. Join all threads (including cancelled ones)
        5. Extract result from winner
        6. Free all closures
        """
        cg = self.cg
        task_gen = cg._thread
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()

        # Extract body expression from block
        body_expr = self._extract_body_expr(stmt.body)
        if body_expr is None:
            # Complex body - generate synthetic task function
            body_expr = self._generate_synthetic_task_for_body(
                stmt.body, stmt.pattern, stmt.iterable, prefix="first"
            )

        # Check if it's a task call (task or thread)
        is_task = self._is_task_call(body_expr)
        is_thread = self._is_thread_call(body_expr)

        # For task calls, use scheduler-based parallel execution
        # For thread calls, use pthread-based parallel execution
        if is_task and not is_thread:
            # Parallel execution for tasks via scheduler batch spawn
            self._generate_scheduler_first(stmt, body_expr)
            return

        # Verify body is a thread call for parallel execution
        if not is_thread:
            cg._emit_warning(
                "WARN",
                "'first' requires a task call in body, falling back to sequential"
            )
            # Create default result
            if stmt.target not in cg.locals:
                var_ptr = cg.builder.alloca(i64, name=stmt.target)
                cg.locals[stmt.target] = var_ptr
            cg.builder.store(ir.Constant(i64, 0), cg.locals[stmt.target])
            return

        # Extract task call info
        call_expr = body_expr
        task_name = call_expr.callee.name
        task_decl = cg.func_decls[task_name]
        task_llvm_func = cg.functions[task_name]

        # Get iterable and its length
        iterable_val = cg._generate_expression(stmt.iterable)
        list_len = cg.builder.call(cg.list_len, [iterable_val])

        func = cg.builder.block.function

        # Allocate arrays for handles and closures
        max_tasks = 1024
        thread_handle_arr = cg.builder.alloca(
            ir.ArrayType(i64, max_tasks), name="first_handles"
        )
        closure_ptr_arr = cg.builder.alloca(
            ir.ArrayType(task_gen.closure_ptr_type, max_tasks), name="first_closures"
        )

        # Also need an array of closure pointers for wait_any (TaskClosure**)
        closure_ptr_ptr_arr = cg.builder.alloca(
            ir.ArrayType(task_gen.closure_ptr_type, max_tasks), name="first_closure_ptrs"
        )

        count_alloca = cg.builder.alloca(i64, name="first_count")
        cg.builder.store(ir.Constant(i64, 0), count_alloca)

        # =====================================================================
        # Phase 1: Spawn all tasks
        # =====================================================================
        spawn_header = func.append_basic_block("first_spawn_header")
        spawn_body = func.append_basic_block("first_spawn_body")
        spawn_done = func.append_basic_block("first_spawn_done")

        idx_alloca = cg.builder.alloca(i64, name="first_spawn_idx")
        cg.builder.store(ir.Constant(i64, 0), idx_alloca)
        cg.builder.branch(spawn_header)

        cg.builder.position_at_end(spawn_header)
        idx = cg.builder.load(idx_alloca)
        cond = cg.builder.icmp_signed("<", idx, list_len)
        cg.builder.cbranch(cond, spawn_body, spawn_done)

        cg.builder.position_at_end(spawn_body)

        # Get element and bind loop variable
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate task arguments
        arg_values = []
        for arg in call_expr.args:
            arg_val = cg._generate_expression(arg)
            arg_values.append(arg_val)

        # Spawn task
        thread_handle, closure_ptr = task_gen.spawn_task(
            cg.builder,
            task_decl,
            task_llvm_func,
            arg_values,
            add_to_nursery=False
        )

        # Store handle and closure
        idx_i32 = cg.builder.trunc(idx, i32)
        handle_slot = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), idx_i32],
            inbounds=True
        )
        cg.builder.store(thread_handle, handle_slot)

        closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), idx_i32],
            inbounds=True
        )
        cg.builder.store(closure_ptr, closure_slot)

        # Also store in closure_ptr_ptr_arr for wait_any
        ptr_slot = cg.builder.gep(
            closure_ptr_ptr_arr,
            [ir.Constant(i32, 0), idx_i32],
            inbounds=True
        )
        cg.builder.store(closure_ptr, ptr_slot)

        # Increment count and index
        current_count = cg.builder.load(count_alloca)
        cg.builder.store(cg.builder.add(current_count, ir.Constant(i64, 1)), count_alloca)
        cg.builder.store(cg.builder.add(idx, ir.Constant(i64, 1)), idx_alloca)
        cg.builder.branch(spawn_header)

        cg.builder.position_at_end(spawn_done)
        final_count = cg.builder.load(count_alloca)

        # =====================================================================
        # Phase 2: Wait for first completion and cancel others
        # =====================================================================
        # Check if we have any tasks
        has_tasks = cg.builder.icmp_signed(">", final_count, ir.Constant(i64, 0))
        wait_block = func.append_basic_block("first_wait")
        empty_block = func.append_basic_block("first_empty")
        after_wait = func.append_basic_block("first_after_wait")

        cg.builder.cbranch(has_tasks, wait_block, empty_block)

        # Wait block: call wait_any
        cg.builder.position_at_end(wait_block)
        closure_arr_ptr = cg.builder.gep(
            closure_ptr_ptr_arr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],
            inbounds=True
        )
        count_i32 = cg.builder.trunc(final_count, i32)
        winner_idx = cg.builder.call(
            task_gen.task_wait_any,
            [closure_arr_ptr, count_i32],
            name="winner_idx"
        )

        # Cancel all other tasks
        cancel_header = func.append_basic_block("first_cancel_header")
        cancel_body = func.append_basic_block("first_cancel_body")
        cancel_done = func.append_basic_block("first_cancel_done")

        cancel_idx = cg.builder.alloca(i64, name="cancel_idx")
        cg.builder.store(ir.Constant(i64, 0), cancel_idx)
        cg.builder.branch(cancel_header)

        cg.builder.position_at_end(cancel_header)
        c_idx = cg.builder.load(cancel_idx)
        c_cond = cg.builder.icmp_signed("<", c_idx, final_count)
        cg.builder.cbranch(c_cond, cancel_body, cancel_done)

        cg.builder.position_at_end(cancel_body)
        c_idx_i32 = cg.builder.trunc(c_idx, i32)
        # For deterministic behavior (BUG-027), never cancel index 0 - we always
        # want its result. Cancel all tasks with index > 0.
        is_first = cg.builder.icmp_signed("==", c_idx, ir.Constant(i64, 0))

        cancel_this = func.append_basic_block("first_cancel_this")
        skip_cancel = func.append_basic_block("first_skip_cancel")

        cg.builder.cbranch(is_first, skip_cancel, cancel_this)

        # Cancel non-first tasks (index > 0)
        cg.builder.position_at_end(cancel_this)
        cancel_closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), c_idx_i32],
            inbounds=True
        )
        cancel_closure = cg.builder.load(cancel_closure_slot)
        cg.builder.call(task_gen.task_cancel, [cancel_closure])
        cg.builder.branch(skip_cancel)

        cg.builder.position_at_end(skip_cancel)
        cg.builder.store(cg.builder.add(c_idx, ir.Constant(i64, 1)), cancel_idx)
        cg.builder.branch(cancel_header)

        cg.builder.position_at_end(cancel_done)

        # =====================================================================
        # Phase 3: Join all threads
        # =====================================================================
        join_header = func.append_basic_block("first_join_header")
        join_body = func.append_basic_block("first_join_body")
        join_done = func.append_basic_block("first_join_done")

        join_idx = cg.builder.alloca(i64, name="first_join_idx")
        cg.builder.store(ir.Constant(i64, 0), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_header)
        j_idx = cg.builder.load(join_idx)
        j_cond = cg.builder.icmp_signed("<", j_idx, final_count)
        cg.builder.cbranch(j_cond, join_body, join_done)

        cg.builder.position_at_end(join_body)
        j_idx_i32 = cg.builder.trunc(j_idx, i32)
        join_handle_slot = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), j_idx_i32],
            inbounds=True
        )
        join_handle = cg.builder.load(join_handle_slot)
        cg.builder.call(task_gen.task_join, [join_handle])
        cg.builder.store(cg.builder.add(j_idx, ir.Constant(i64, 1)), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_done)

        # Extract result from first element (index 0) for deterministic behavior
        # The BUG-027 fix established that 'first' uses priority-based semantics:
        # the lowest-indexed task always wins, regardless of completion order.
        # Since all threads are joined at this point, task 0's result is available.
        first_closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), ir.Constant(i32, 0)],  # Always index 0
            inbounds=True
        )
        winner_closure = cg.builder.load(first_closure_slot)
        result_field = cg.builder.gep(
            winner_closure,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True
        )
        result_ptr = cg.builder.load(result_field)
        wait_result = cg.builder.ptrtoint(result_ptr, i64)

        # =====================================================================
        # Phase 4: Free all closures
        # =====================================================================
        free_header = func.append_basic_block("first_free_header")
        free_body = func.append_basic_block("first_free_body")
        free_done = func.append_basic_block("first_free_done")

        free_idx = cg.builder.alloca(i64, name="first_free_idx")
        cg.builder.store(ir.Constant(i64, 0), free_idx)
        cg.builder.branch(free_header)

        cg.builder.position_at_end(free_header)
        f_idx = cg.builder.load(free_idx)
        f_cond = cg.builder.icmp_signed("<", f_idx, final_count)
        cg.builder.cbranch(f_cond, free_body, free_done)

        cg.builder.position_at_end(free_body)
        f_idx_i32 = cg.builder.trunc(f_idx, i32)
        free_closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), f_idx_i32],
            inbounds=True
        )
        free_closure = cg.builder.load(free_closure_slot)
        cg.builder.call(task_gen.closure_free, [free_closure])
        cg.builder.store(cg.builder.add(f_idx, ir.Constant(i64, 1)), free_idx)
        cg.builder.branch(free_header)

        cg.builder.position_at_end(free_done)
        cg.builder.branch(after_wait)

        # Empty block: no tasks, return 0
        cg.builder.position_at_end(empty_block)
        empty_result = ir.Constant(i64, 0)
        cg.builder.branch(after_wait)

        # Merge results
        cg.builder.position_at_end(after_wait)
        result_phi = cg.builder.phi(i64, name="first_result")
        result_phi.add_incoming(wait_result, free_done)
        result_phi.add_incoming(empty_result, empty_block)

        # Store in target variable
        if stmt.target in cg.locals:
            cg.builder.store(result_phi, cg.locals[stmt.target])
        else:
            var_ptr = cg.builder.alloca(i64, name=stmt.target)
            cg.locals[stmt.target] = var_ptr
            cg.builder.store(result_phi, var_ptr)

    # ========================================================================
    # Most-Assign Statement (Best Effort)
    # ========================================================================

    def generate_most_assign(self, stmt: MostAssignStmt):
        """Generate (results, errors) = most item in items expr ~

        Spawns all tasks and waits for all to complete.
        Returns tuple of (successful_results, errors).
        No cancellation - all tasks run to completion.

        Algorithm:
        1. Spawn all tasks, collect closures and handles
        2. Wait for all tasks to complete
        3. Check each closure: exception? -> errors, result -> results
        4. Free all closures
        """
        cg = self.cg
        func = cg.builder.function
        i32 = ir.IntType(32)
        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        elem_size = ir.Constant(i64, 8)
        list_ptr_type = cg.list_struct.as_pointer()

        # Extract body expression from block
        body_expr = self._extract_body_expr(stmt.body)
        if body_expr is None:
            # Complex body - generate synthetic thread function
            body_expr = self._generate_synthetic_task_for_body(
                stmt.body, stmt.pattern, stmt.iterable, prefix="most"
            )

        # Check if body is a task or thread call
        call_expr = body_expr
        is_task = self._is_task_call(call_expr)
        is_thread = self._is_thread_call(call_expr)

        # For task calls, use scheduler-based parallel execution
        if is_task and not is_thread:
            # Parallel execution for tasks via scheduler batch spawn
            self._generate_scheduler_most(stmt, body_expr)

            # Track types
            cg.var_coex_types[stmt.results_target] = ListType(PrimitiveType("int"))
            cg.var_coex_types[stmt.errors_target] = ListType(PrimitiveType("int"))
            return

        if not is_thread:
            # Fallback to sequential for non-task calls - use for-collection
            for_assign = ForAssignStmt(
                target="_most_temp",
                pattern=stmt.pattern,
                iterable=stmt.iterable,
                body_expr=body_expr
            )
            result_list = self._generate_parallel_for_assign(for_assign)
            errors_list = cg.builder.call(cg.list_new, [elem_size])

            # Store results and errors
            if stmt.results_target in cg.locals:
                cg.builder.store(result_list, cg.locals[stmt.results_target])
            else:
                var_ptr = cg.builder.alloca(list_ptr_type, name=stmt.results_target)
                cg.locals[stmt.results_target] = var_ptr
                cg.builder.store(result_list, var_ptr)
            if stmt.errors_target in cg.locals:
                cg.builder.store(errors_list, cg.locals[stmt.errors_target])
            else:
                var_ptr = cg.builder.alloca(list_ptr_type, name=stmt.errors_target)
                cg.locals[stmt.errors_target] = var_ptr
                cg.builder.store(errors_list, var_ptr)

            # Track types for fallback case
            cg.var_coex_types[stmt.results_target] = ListType(PrimitiveType("int"))
            cg.var_coex_types[stmt.errors_target] = ListType(PrimitiveType("int"))
            return

        # Get task_gen now that we know it's a task call
        task_gen = cg._thread

        # Extract task info
        task_name = call_expr.callee.name
        task_decl = cg.func_decls[task_name]
        task_llvm_func = cg.functions[task_name]

        # Evaluate iterable
        iterable_val = cg._generate_expression(stmt.iterable)

        # Get collection length
        len_val = cg.builder.call(cg.list_len, [iterable_val], name="most_len")

        # Check for empty collection
        is_empty = cg.builder.icmp_signed("==", len_val, ir.Constant(i64, 0))
        empty_block = func.append_basic_block("most_empty")
        spawn_block = func.append_basic_block("most_spawn_init")
        after_wait = func.append_basic_block("most_after_wait")

        cg.builder.cbranch(is_empty, empty_block, spawn_block)

        # =====================================================================
        # Phase 1: Spawn all tasks
        # =====================================================================
        cg.builder.position_at_end(spawn_block)

        # Allocate arrays for closures and handles
        max_tasks = 1024
        thread_handle_arr = cg.builder.alloca(
            ir.ArrayType(i64, max_tasks), name="most_handles"
        )
        closure_ptr_arr = cg.builder.alloca(
            ir.ArrayType(task_gen.closure_ptr_type, max_tasks), name="most_closures"
        )

        # Spawn loop
        spawn_header = func.append_basic_block("most_spawn_header")
        spawn_body = func.append_basic_block("most_spawn_body")
        spawn_done = func.append_basic_block("most_spawn_done")

        spawn_idx = cg.builder.alloca(i64, name="most_spawn_idx")
        cg.builder.store(ir.Constant(i64, 0), spawn_idx)
        cg.builder.branch(spawn_header)

        cg.builder.position_at_end(spawn_header)
        s_idx = cg.builder.load(spawn_idx)
        s_cond = cg.builder.icmp_signed("<", s_idx, len_val)
        cg.builder.cbranch(s_cond, spawn_body, spawn_done)

        cg.builder.position_at_end(spawn_body)

        # Get current element from iterable
        elem_ptr = cg.builder.call(cg.list_get, [iterable_val, s_idx])
        elem_val = cg.builder.load(cg.builder.bitcast(elem_ptr, i64.as_pointer()))

        # Bind loop variable for argument evaluation
        pattern = stmt.pattern
        if isinstance(pattern, str):
            if pattern in cg.locals:
                cg.builder.store(elem_val, cg.locals[pattern])
            else:
                var_ptr = cg.builder.alloca(i64, name=pattern)
                cg.locals[pattern] = var_ptr
                cg.builder.store(elem_val, var_ptr)
        elif isinstance(pattern, IdentifierPattern):
            name = pattern.name
            if name in cg.locals:
                cg.builder.store(elem_val, cg.locals[name])
            else:
                var_ptr = cg.builder.alloca(i64, name=name)
                cg.locals[name] = var_ptr
                cg.builder.store(elem_val, var_ptr)

        # Evaluate task call arguments
        arg_values = []
        for arg in call_expr.args:
            arg_val = cg._generate_expression(arg)
            arg_values.append(arg_val)

        # Spawn the task
        thread_handle, closure_ptr = task_gen.spawn_task(
            cg.builder,
            task_decl,
            task_llvm_func,
            arg_values,
            add_to_nursery=False  # We manage our own arrays
        )

        # Store handle and closure
        s_idx_i32 = cg.builder.trunc(s_idx, i32)
        handle_slot = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), s_idx_i32],
            inbounds=True
        )
        cg.builder.store(thread_handle, handle_slot)

        closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), s_idx_i32],
            inbounds=True
        )
        cg.builder.store(closure_ptr, closure_slot)

        cg.builder.store(cg.builder.add(s_idx, ir.Constant(i64, 1)), spawn_idx)
        cg.builder.branch(spawn_header)

        cg.builder.position_at_end(spawn_done)
        final_count = len_val

        # =====================================================================
        # Phase 2: Join all threads and collect results
        # =====================================================================
        # Create results list and errors list
        # Use list struct pointer type so method calls work
        list_ptr_type = cg.list_struct.as_pointer()

        results_list = cg.builder.call(cg.list_new, [elem_size], name="most_results")
        results_alloca = cg.builder.alloca(list_ptr_type, name="most_results_ptr")
        cg.builder.store(results_list, results_alloca)

        errors_list = cg.builder.call(cg.list_new, [elem_size], name="most_errors")
        errors_alloca = cg.builder.alloca(list_ptr_type, name="most_errors_ptr")
        cg.builder.store(errors_list, errors_alloca)

        # Join and collect loop
        join_header = func.append_basic_block("most_join_header")
        join_body = func.append_basic_block("most_join_body")
        join_done = func.append_basic_block("most_join_done")

        join_idx = cg.builder.alloca(i64, name="most_join_idx")
        cg.builder.store(ir.Constant(i64, 0), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_header)
        j_idx = cg.builder.load(join_idx)
        j_cond = cg.builder.icmp_signed("<", j_idx, final_count)
        cg.builder.cbranch(j_cond, join_body, join_done)

        cg.builder.position_at_end(join_body)
        j_idx_i32 = cg.builder.trunc(j_idx, i32)

        # Load handle and join
        join_handle_slot = cg.builder.gep(
            thread_handle_arr,
            [ir.Constant(i32, 0), j_idx_i32],
            inbounds=True
        )
        join_handle = cg.builder.load(join_handle_slot)
        cg.builder.call(task_gen.task_join, [join_handle])

        # Load closure and extract result
        join_closure_slot = cg.builder.gep(
            closure_ptr_arr,
            [ir.Constant(i32, 0), j_idx_i32],
            inbounds=True
        )
        join_closure = cg.builder.load(join_closure_slot)

        # Check exception field (index 2)
        exception_field = cg.builder.gep(
            join_closure,
            [ir.Constant(i32, 0), ir.Constant(i32, 2)],
            inbounds=True
        )
        exception_ptr = cg.builder.load(exception_field)
        exception_val = cg.builder.ptrtoint(exception_ptr, i64)
        has_exception = cg.builder.icmp_signed("!=", exception_val, ir.Constant(i64, 0))

        add_to_results = func.append_basic_block("most_add_result")
        add_to_errors = func.append_basic_block("most_add_error")
        join_next = func.append_basic_block("most_join_next")

        cg.builder.cbranch(has_exception, add_to_errors, add_to_results)

        # Add to results (no exception)
        cg.builder.position_at_end(add_to_results)
        result_field = cg.builder.gep(
            join_closure,
            [ir.Constant(i32, 0), ir.Constant(i32, 1)],
            inbounds=True
        )
        result_ptr = cg.builder.load(result_field)
        result_val = cg.builder.ptrtoint(result_ptr, i64)

        # Store to temp, bitcast to i8*, and append
        result_temp = cg.builder.alloca(i64, name="result_temp")
        cg.builder.store(result_val, result_temp)
        result_temp_ptr = cg.builder.bitcast(result_temp, i8_ptr)
        current_results = cg.builder.load(results_alloca)
        new_results = cg.builder.call(cg.list_append, [current_results, result_temp_ptr, elem_size])
        cg.builder.store(new_results, results_alloca)
        cg.builder.branch(join_next)

        # Add to errors (has exception)
        cg.builder.position_at_end(add_to_errors)
        error_temp = cg.builder.alloca(i64, name="error_temp")
        cg.builder.store(exception_val, error_temp)
        error_temp_ptr = cg.builder.bitcast(error_temp, i8_ptr)
        current_errors = cg.builder.load(errors_alloca)
        new_errors = cg.builder.call(cg.list_append, [current_errors, error_temp_ptr, elem_size])
        cg.builder.store(new_errors, errors_alloca)
        cg.builder.branch(join_next)

        cg.builder.position_at_end(join_next)

        # Free closure
        cg.builder.call(task_gen.closure_free, [join_closure])

        cg.builder.store(cg.builder.add(j_idx, ir.Constant(i64, 1)), join_idx)
        cg.builder.branch(join_header)

        cg.builder.position_at_end(join_done)
        # Load final lists from allocas after all appends
        final_results_from_join = cg.builder.load(results_alloca)
        final_errors_from_join = cg.builder.load(errors_alloca)
        cg.builder.branch(after_wait)

        # Empty block: no tasks
        cg.builder.position_at_end(empty_block)
        empty_results_list = cg.builder.call(cg.list_new, [elem_size], name="empty_results")
        empty_errors_list = cg.builder.call(cg.list_new, [elem_size], name="empty_errors")
        cg.builder.branch(after_wait)

        # Merge with phi nodes - using list pointer type
        cg.builder.position_at_end(after_wait)
        final_results = cg.builder.phi(list_ptr_type, name="most_final_results")
        final_results.add_incoming(final_results_from_join, join_done)
        final_results.add_incoming(empty_results_list, empty_block)

        final_errors = cg.builder.phi(list_ptr_type, name="most_final_errors")
        final_errors.add_incoming(final_errors_from_join, join_done)
        final_errors.add_incoming(empty_errors_list, empty_block)

        # Store results in results_target (using list pointer type)
        if stmt.results_target in cg.locals:
            cg.builder.store(final_results, cg.locals[stmt.results_target])
        else:
            var_ptr = cg.builder.alloca(list_ptr_type, name=stmt.results_target)
            cg.locals[stmt.results_target] = var_ptr
            cg.builder.store(final_results, var_ptr)

        # Store errors in errors_target (using list pointer type)
        if stmt.errors_target in cg.locals:
            cg.builder.store(final_errors, cg.locals[stmt.errors_target])
        else:
            var_ptr = cg.builder.alloca(list_ptr_type, name=stmt.errors_target)
            cg.locals[stmt.errors_target] = var_ptr
            cg.builder.store(final_errors, var_ptr)

        # Track types for method calls on results/errors
        # Results is List<return_type>, errors is List<int> (error codes)
        result_elem_type = task_decl.return_type if task_decl.return_type else PrimitiveType("int")
        cg.var_coex_types[stmt.results_target] = ListType(result_elem_type)
        cg.var_coex_types[stmt.errors_target] = ListType(PrimitiveType("int"))

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
