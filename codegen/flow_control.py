"""
Flow Control Code Generation for Coex.

This module handles:
- Return statements
- If/else/elif statements
- While loops
- Cycle blocks (double-buffered semantics)
- Break/continue statements
- Match/pattern matching statements
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict, Tuple
from typing import List as PyList

from ast_nodes import (
    Stmt, Expr, Type, ReturnStmt, IfStmt, WhileStmt, CycleStmt, MatchStmt,
    SelectStmt, SelectCase, ChannelType, NamedType,
    VarDecl, Assignment, AssignOp, ForStmt, Identifier, NilLiteral,
    Pattern, WildcardPattern, LiteralPattern, IdentifierPattern, ConstructorPattern,
    PrimitiveType
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class FlowControlGenerator:
    """Generates flow control LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Return Statement
    # ========================================================================

    def generate_return(self, stmt: ReturnStmt):
        """Generate a return statement"""
        cg = self.cg
        if stmt.value:
            # Special handling for returning nil to an optional type
            func = cg.builder.function
            ret_type = func.function_type.return_type

            if isinstance(stmt.value, NilLiteral) and isinstance(ret_type, ir.LiteralStructType):
                # Check if return type is an optional (has i1 flag + value)
                if len(ret_type.elements) == 2 and isinstance(ret_type.elements[0], ir.IntType):
                    if ret_type.elements[0].width == 1:
                        # Generate nil optional directly: {has_value=false, value=0}
                        inner_type = ret_type.elements[1]
                        value = ir.Constant(ret_type, ir.Undefined)
                        value = cg.builder.insert_value(value, ir.Constant(ir.IntType(1), 0), 0)
                        if isinstance(inner_type, ir.IntType):
                            value = cg.builder.insert_value(value, ir.Constant(inner_type, 0), 1)
                        elif isinstance(inner_type, ir.DoubleType):
                            value = cg.builder.insert_value(value, ir.Constant(inner_type, 0.0), 1)
                        else:
                            value = cg.builder.insert_value(value, ir.Constant(inner_type, None), 1)

                        # Pop GC frame before returning
                        if cg.gc_frame is not None and cg.gc is not None:
                            cg.gc.pop_frame(cg.builder, cg.gc_frame)

                        cg.builder.ret(value)
                        return

            value = cg._generate_expression(stmt.value)

            # Cast to function return type if needed (e.g., wrap in optional)
            value = cg._cast_value(value, ret_type)

            # Pop GC frame before returning
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            cg.builder.ret(value)
        else:
            # Pop GC frame before returning
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            cg.builder.ret_void()

    # ========================================================================
    # If Statement
    # ========================================================================

    def generate_if(self, stmt: IfStmt):
        """Generate an if statement"""
        cg = self.cg
        func = cg.builder.function

        then_block = func.append_basic_block("if_then")
        merge_block = func.append_basic_block("if_merge")

        # Create else-if and else blocks
        else_blocks = []
        for _ in stmt.else_if_clauses:
            else_blocks.append(func.append_basic_block("elif_cond"))

        if stmt.else_body:
            else_block = func.append_basic_block("if_else")
        else:
            else_block = merge_block

        # Generate condition
        cond = cg._generate_expression(stmt.condition)
        cond = self.to_bool(cond, stmt.condition)

        # Branch
        first_else = else_blocks[0] if else_blocks else else_block
        cg.builder.cbranch(cond, then_block, first_else)

        # Generate then block
        cg.builder.position_at_end(then_block)
        cg._enter_scope()  # Variables declared in then-block are scoped here
        for s in stmt.then_body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break
        cg._exit_scope()  # Clean up variables from then-block
        if not cg.builder.block.is_terminated:
            cg.builder.branch(merge_block)

        # Generate else-if blocks
        for i, (elif_cond, elif_body) in enumerate(stmt.else_if_clauses):
            cg.builder.position_at_end(else_blocks[i])
            cond = cg._generate_expression(elif_cond)
            cond = self.to_bool(cond, elif_cond)

            elif_then = func.append_basic_block("elif_then")
            next_else = else_blocks[i + 1] if i + 1 < len(else_blocks) else else_block

            cg.builder.cbranch(cond, elif_then, next_else)

            cg.builder.position_at_end(elif_then)
            cg._enter_scope()  # Variables declared in elif-block are scoped here
            for s in elif_body:
                cg._generate_statement(s)
                if cg.builder.block.is_terminated:
                    break
            cg._exit_scope()  # Clean up variables from elif-block
            if not cg.builder.block.is_terminated:
                cg.builder.branch(merge_block)

        # Generate else block
        if stmt.else_body:
            cg.builder.position_at_end(else_block)
            cg._enter_scope()  # Variables declared in else-block are scoped here
            for s in stmt.else_body:
                cg._generate_statement(s)
                if cg.builder.block.is_terminated:
                    break
            cg._exit_scope()  # Clean up variables from else-block
            if not cg.builder.block.is_terminated:
                cg.builder.branch(merge_block)

        cg.builder.position_at_end(merge_block)

    def to_bool(self, value: ir.Value, expr: 'Expr' = None) -> ir.Value:
        """Convert value to boolean (i1)

        If expr is provided and the value is a Result type (either i64 handle or
        pointer), deref/access the struct and check the tag field (Ok=0 -> true,
        Err=1 -> false).
        """
        cg = self.cg
        if value.type == ir.IntType(1):
            return value
        elif isinstance(value.type, ir.IntType):
            # Check if this i64 is a Result handle - needs tag-based bool conversion
            if value.type == ir.IntType(64) and expr is not None:
                try:
                    type_name = cg._resolve_expr_type_name(expr)
                    if type_name == "Result":
                        # Result<T, E> -> bool: true if Ok (tag == 0), false if Err (tag == 1)
                        result_ptr = cg._deref_handle(value, "Result")
                        tag_ptr = cg.builder.gep(result_ptr, [
                            ir.Constant(ir.IntType(32), 0),
                            ir.Constant(ir.IntType(32), 0)  # tag field
                        ])
                        tag = cg.builder.load(tag_ptr)
                        return cg.builder.icmp_signed("==", tag, ir.Constant(ir.IntType(64), 0))
                except Exception:
                    pass
            return cg.builder.icmp_signed("!=", value, ir.Constant(value.type, 0))
        elif isinstance(value.type, ir.DoubleType):
            return cg.builder.fcmp_ordered("!=", value, ir.Constant(value.type, 0.0))
        elif isinstance(value.type, ir.PointerType):
            # Check if this is a Result pointer - convert to bool based on tag
            if hasattr(cg, 'result_struct') and value.type == cg.result_struct.as_pointer():
                # Result<T, E> -> bool: true if Ok (tag == 0), false if Err (tag == 1)
                tag_ptr = cg.builder.gep(value, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), 0)  # tag field
                ])
                tag = cg.builder.load(tag_ptr)
                return cg.builder.icmp_signed("==", tag, ir.Constant(ir.IntType(64), 0))
            # Regular pointer: true if non-null
            null = ir.Constant(value.type, None)
            return cg.builder.icmp_unsigned("!=", value, null)
        return value

    # ========================================================================
    # While Loop
    # ========================================================================

    def generate_while(self, stmt: WhileStmt):
        """Generate a standard while loop: while condition block

        Equivalent to other languages' while loop.
        Note: 'while true' is equivalent to 'loop'.
        """
        cg = self.cg
        func = cg.builder.function

        # PRE-ALLOCATE all local variables used in the loop body
        local_vars = cg._collect_local_variables(stmt.body)
        for lv_name in local_vars:
            if lv_name not in cg.locals:
                lv_alloca = cg.builder.alloca(ir.IntType(64), name=lv_name)
                cg.locals[lv_name] = lv_alloca
                cg.placeholder_vars.add(lv_name)

        # Create basic blocks
        cond_block = func.append_basic_block("while_cond")
        body_block = func.append_basic_block("while_body")
        exit_block = func.append_basic_block("while_exit")

        # Save loop blocks for break/continue
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = cond_block

        # Jump to condition check
        cg.builder.branch(cond_block)

        # Generate condition check
        cg.builder.position_at_end(cond_block)
        cond_val = cg._generate_expression(stmt.condition)
        cond_bool = self.to_bool(cond_val, stmt.condition)
        cg.builder.cbranch(cond_bool, body_block, exit_block)

        # Generate loop body
        cg.builder.position_at_end(body_block)
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break

        if not cg.builder.block.is_terminated:
            # Inject safepoint at loop back-edge for GC watermark acknowledgment
            # Task's inject_safepoint also calls gc_safepoint, so we only need
            # to call it directly if not in a task context
            if cg._thread is not None:
                cg._thread.inject_safepoint(cg.builder, exit_block)
            else:
                cg.builder.call(cg.gc.gc_safepoint, [])
            cg.builder.branch(cond_block)

        # Continue after loop
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    # ========================================================================
    # Cycle Block (Double-Buffered Semantics)
    # ========================================================================

    def generate_cycle(self, stmt: CycleStmt):
        """Generate a cycle statement with double-buffered semantics.

        Syntax: while condition cycle block

        Variables declared inside the cycle block exist in two buffers.
        Reads see the 'read' buffer (previous generation).
        Writes go to the 'write' buffer (current generation).
        At iteration end, buffers swap and condition is checked in outer scope.
        """
        cg = self.cg
        func = cg.builder.function

        # Phase 1: Analyze the body to find variables declared inside
        cycle_vars = self.find_cycle_declared_vars(stmt.body)

        # Phase 2: Create double-buffered storage for cycle variables
        read_buffers: Dict[str, ir.AllocaInst] = {}   # var_name -> alloca for read buffer
        write_buffers: Dict[str, ir.AllocaInst] = {}  # var_name -> alloca for write buffer
        cycle_var_types: Dict[str, ir.Type] = {}      # var_name -> LLVM type

        for var_name, var_type in cycle_vars.items():
            if var_type:
                llvm_type = cg._get_llvm_type(var_type)
            else:
                llvm_type = ir.IntType(64)  # Default to i64 for unknown types
            cycle_var_types[var_name] = llvm_type
            read_buffers[var_name] = cg.builder.alloca(llvm_type, name=f"{var_name}_read")
            write_buffers[var_name] = cg.builder.alloca(llvm_type, name=f"{var_name}_write")

            # Initialize both buffers to zero/null
            if isinstance(llvm_type, ir.IntType):
                zero = ir.Constant(llvm_type, 0)
            elif isinstance(llvm_type, ir.DoubleType):
                zero = ir.Constant(llvm_type, 0.0)
            elif isinstance(llvm_type, ir.PointerType):
                zero = ir.Constant(llvm_type, None)
            else:
                zero = ir.Constant(llvm_type, None)
            cg.builder.store(zero, read_buffers[var_name])
            cg.builder.store(zero, write_buffers[var_name])

        # Phase 3: Create basic blocks
        body_block = func.append_basic_block("cycle_body")
        swap_block = func.append_basic_block("cycle_swap")
        cond_block = func.append_basic_block("cycle_cond")
        exit_block = func.append_basic_block("cycle_exit")

        # Save loop blocks for break/continue
        old_exit = cg.loop_exit_block
        old_continue = cg.loop_continue_block
        cg.loop_exit_block = exit_block
        cg.loop_continue_block = swap_block  # continue commits and checks condition

        # Phase 4: Initial condition check (enter cycle only if condition true)
        init_cond = cg._generate_expression(stmt.condition)
        init_cond_bool = self.to_bool(init_cond, stmt.condition)
        cg.builder.cbranch(init_cond_bool, body_block, exit_block)

        # Phase 5: Push cycle context and generate body
        cg.builder.position_at_end(body_block)

        cycle_context = {
            'read_buffers': read_buffers,
            'write_buffers': write_buffers,
            'cycle_vars': set(cycle_vars.keys()),
            'var_types': cycle_var_types
        }
        cg._cycle_context_stack.append(cycle_context)

        # Generate body statements
        for s in stmt.body:
            cg._generate_statement(s)
            if cg.builder.block.is_terminated:
                break

        if not cg.builder.block.is_terminated:
            cg.builder.branch(swap_block)

        # Pop cycle context before swap (condition is in outer scope)
        cg._cycle_context_stack.pop()

        # Phase 6: Buffer swap - copy write buffer to read buffer
        cg.builder.position_at_end(swap_block)
        for var_name in cycle_vars:
            write_val = cg.builder.load(write_buffers[var_name])
            cg.builder.store(write_val, read_buffers[var_name])
        cg.builder.branch(cond_block)

        # Phase 7: Condition check (in outer scope, after swap)
        cg.builder.position_at_end(cond_block)
        cond_val = cg._generate_expression(stmt.condition)
        cond_bool = self.to_bool(cond_val, stmt.condition)
        cg.builder.cbranch(cond_bool, body_block, exit_block)

        # Phase 8: Exit and cleanup
        cg.builder.position_at_end(exit_block)

        # Restore loop blocks
        cg.loop_exit_block = old_exit
        cg.loop_continue_block = old_continue

    def find_cycle_declared_vars(self, stmts: PyList[Stmt]) -> Dict[str, Optional[Type]]:
        """Find all variables declared within a list of statements.

        Returns dict of var_name -> type_annotation (or None if inferred).
        Recursively scans into control flow but not into nested cycles.
        """
        cg = self.cg
        declared: Dict[str, Optional[Type]] = {}

        for stmt in stmts:
            if isinstance(stmt, VarDecl):
                declared[stmt.name] = stmt.type_annotation
            elif isinstance(stmt, Assignment):
                # Simple assignment to new identifier declares a var
                if isinstance(stmt.target, Identifier) and stmt.op == AssignOp.ASSIGN:
                    name = stmt.target.name
                    # Only count as declaration if not already known
                    if name not in declared and name not in cg.locals:
                        declared[name] = None
            elif isinstance(stmt, IfStmt):
                # Recurse into branches
                declared.update(self.find_cycle_declared_vars(stmt.then_body))
                for _, body in stmt.else_if_clauses:
                    declared.update(self.find_cycle_declared_vars(body))
                if stmt.else_body:
                    declared.update(self.find_cycle_declared_vars(stmt.else_body))
            elif isinstance(stmt, ForStmt):
                # Do NOT count the for loop variable as a cycle variable
                # For loop manages its own iteration variable
                declared.update(self.find_cycle_declared_vars(stmt.body))
            elif isinstance(stmt, WhileStmt):
                declared.update(self.find_cycle_declared_vars(stmt.body))
            # Note: Don't recurse into nested CycleStmt - those have their own scope

        return declared

    def in_cycle_context(self) -> bool:
        """Check if currently generating code inside a cycle block."""
        return len(self.cg._cycle_context_stack) > 0

    def get_cycle_context(self) -> Optional[Dict]:
        """Get the current cycle context, or None if not in a cycle."""
        if self.cg._cycle_context_stack:
            return self.cg._cycle_context_stack[-1]
        return None

    # ========================================================================
    # Break/Continue
    # ========================================================================

    def generate_break(self):
        """Generate a break statement"""
        cg = self.cg
        if cg.loop_exit_block:
            cg.builder.branch(cg.loop_exit_block)

    def generate_continue(self):
        """Generate a continue statement"""
        cg = self.cg
        if cg.loop_continue_block:
            cg.builder.branch(cg.loop_continue_block)

    # ========================================================================
    # Match Statement
    # ========================================================================

    def generate_match(self, stmt: MatchStmt):
        """Generate a match statement"""
        cg = self.cg
        func = cg.builder.function

        subject = cg._generate_expression(stmt.subject)
        merge_block = func.append_basic_block("match_merge")

        # For each arm, generate a comparison and branch
        next_block = None
        for i, arm in enumerate(stmt.arms):
            if next_block:
                cg.builder.position_at_end(next_block)

            arm_block = func.append_basic_block(f"match_arm_{i}")
            next_block = func.append_basic_block(f"match_next_{i}") if i < len(stmt.arms) - 1 else merge_block

            # Generate pattern match
            matched = self.generate_pattern_match(subject, arm.pattern)

            # Add guard if present
            if arm.guard:
                guard_block = func.append_basic_block(f"match_guard_{i}")
                cg.builder.cbranch(matched, guard_block, next_block)
                cg.builder.position_at_end(guard_block)
                guard = cg._generate_expression(arm.guard)
                guard = self.to_bool(guard, arm.guard)
                cg.builder.cbranch(guard, arm_block, next_block)
            else:
                cg.builder.cbranch(matched, arm_block, next_block)

            # Generate arm body
            cg.builder.position_at_end(arm_block)
            for s in arm.body:
                cg._generate_statement(s)
                if cg.builder.block.is_terminated:
                    break
            if not cg.builder.block.is_terminated:
                cg.builder.branch(merge_block)

        cg.builder.position_at_end(merge_block)

    def generate_pattern_match(self, subject: ir.Value, pattern: Pattern) -> ir.Value:
        """Generate code to match a pattern, returns i1"""
        cg = self.cg
        if isinstance(pattern, WildcardPattern):
            return ir.Constant(ir.IntType(1), 1)

        elif isinstance(pattern, LiteralPattern):
            literal = cg._generate_expression(pattern.value)
            if isinstance(subject.type, ir.IntType):
                return cg.builder.icmp_signed("==", subject, literal)
            elif isinstance(subject.type, ir.DoubleType):
                return cg.builder.fcmp_ordered("==", subject, literal)
            return ir.Constant(ir.IntType(1), 0)

        elif isinstance(pattern, IdentifierPattern):
            # Check if this identifier is actually an enum variant (no-arg variant)
            enum_info = cg._find_enum_variant(pattern.name)
            if enum_info:
                # This is an enum variant without arguments
                enum_name, variant_name = enum_info
                tag, fields = cg.enum_variants[enum_name][variant_name]

                # Deref handle if subject is i64
                subj_ptr = subject
                if isinstance(subject.type, ir.IntType) and subject.type.width == 64:
                    raw = cg.builder.call(cg.gc.gc_handle_deref, [subject])
                    subj_ptr = cg.builder.bitcast(raw, cg.type_registry[enum_name].as_pointer())

                # Get tag from subject
                tag_ptr = cg.builder.gep(subj_ptr, [
                    ir.Constant(ir.IntType(32), 0),
                    ir.Constant(ir.IntType(32), 0)
                ], inbounds=True)
                subject_tag = cg.builder.load(tag_ptr)

                # Compare tags
                expected_tag = ir.Constant(ir.IntType(64), tag)
                return cg.builder.icmp_signed("==", subject_tag, expected_tag)

            # Regular identifier - bind value to name
            alloca = cg.builder.alloca(subject.type, name=pattern.name)
            cg.builder.store(subject, alloca)
            cg.locals[pattern.name] = alloca
            return ir.Constant(ir.IntType(1), 1)

        elif isinstance(pattern, ConstructorPattern):
            # Enum variant pattern: Circle(r) or Circle(radius: r)
            variant_name = pattern.name

            # Find which enum this variant belongs to
            enum_info = cg._find_enum_variant(variant_name)
            if not enum_info:
                # Unknown variant, always fail
                return ir.Constant(ir.IntType(1), 0)

            enum_name, _ = enum_info
            tag, fields = cg.enum_variants[enum_name][variant_name]

            # Deref handle if subject is i64
            subj_ptr = subject
            if isinstance(subject.type, ir.IntType) and subject.type.width == 64:
                raw = cg.builder.call(cg.gc.gc_handle_deref, [subject])
                subj_ptr = cg.builder.bitcast(raw, cg.type_registry[enum_name].as_pointer())

            # Get tag from subject
            tag_ptr = cg.builder.gep(subj_ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), 0)
            ], inbounds=True)
            subject_tag = cg.builder.load(tag_ptr)

            # Compare tags
            expected_tag = ir.Constant(ir.IntType(64), tag)
            tag_match = cg.builder.icmp_signed("==", subject_tag, expected_tag)

            # Bind pattern arguments to fields
            # pattern.args are the sub-patterns for each field
            for i, sub_pattern in enumerate(pattern.args):
                if i < len(fields):
                    field_name, field_type = fields[i]

                    # Get field pointer (index i+1, after tag)
                    field_ptr = cg.builder.gep(subj_ptr, [
                        ir.Constant(ir.IntType(32), 0),
                        ir.Constant(ir.IntType(32), i + 1)
                    ], inbounds=True)
                    field_val = cg.builder.load(field_ptr)

                    # Convert back to proper type if needed
                    if isinstance(field_type, PrimitiveType) and field_type.name == "float":
                        field_val = cg.builder.bitcast(field_val, ir.DoubleType())
                    # Reference type fields store i64 handles - no conversion needed,
                    # field_val is already an i64 handle

                    # If sub-pattern is an identifier, bind it
                    if isinstance(sub_pattern, IdentifierPattern):
                        alloca = cg.builder.alloca(field_val.type, name=sub_pattern.name)
                        cg.builder.store(field_val, alloca)
                        cg.locals[sub_pattern.name] = alloca
                    # WildcardPattern: don't bind
                    # Other patterns: would need recursive matching

            return tag_match

        # Default: match
        return ir.Constant(ir.IntType(1), 1)

    # ========================================================================
    # Select Statement (Channel Multiplexing)
    # ========================================================================

    def generate_select(self, stmt: SelectStmt):
        """Generate a select statement that polls multiple channels.

        Strategy: DEFAULT polling loop.
        - try_receive on each channel in order
        - If any succeeds, bind the variable, execute the case body, exit
        - If all empty, sched_yield and loop back
        - GC safepoint at loop back-edge (like while loops)
        """
        cg = self.cg
        func = cg.builder.function
        i64 = ir.IntType(64)

        num_cases = len(stmt.cases)
        if num_cases == 0:
            return

        # Ensure channel functions are declared
        cg._channel.declare_channel_functions()

        # Create basic blocks
        poll_block = func.append_basic_block("select_poll")
        done_block = func.append_basic_block("select_done")

        # Create try_receive + case body blocks for each case
        try_blocks = []
        body_blocks = []
        for i, case in enumerate(stmt.cases):
            try_blocks.append(func.append_basic_block(f"select_try_{i}"))
            body_blocks.append(func.append_basic_block(f"select_case_{i}"))

        # Yield block - all channels empty, yield and retry
        yield_block = func.append_basic_block("select_yield")

        # Jump to poll loop
        cg.builder.branch(poll_block)

        # Poll block just jumps to first try
        cg.builder.position_at_end(poll_block)
        cg.builder.branch(try_blocks[0])

        # Generate try_receive for each case
        for i, case in enumerate(stmt.cases):
            cg.builder.position_at_end(try_blocks[i])

            # Evaluate channel expression
            channel_val = cg._generate_expression(case.channel)

            # Ensure channel is the right pointer type
            channel_ptr_type = cg._channel.get_channel_struct().as_pointer()
            if channel_val.type != channel_ptr_type:
                if isinstance(channel_val.type, ir.IntType):
                    channel_val = cg.builder.inttoptr(channel_val, channel_ptr_type)
                else:
                    channel_val = cg.builder.bitcast(channel_val, channel_ptr_type)

            # Alloca for try_receive output
            out_alloca = cg.builder.alloca(i64, name=f"select_out_{i}")
            cg.builder.store(ir.Constant(i64, 0), out_alloca)

            # Call coex_channel_try_receive
            status = cg.builder.call(
                cg._channel._channel_try_receive_fn,
                [channel_val, out_alloca],
                name=f"select_status_{i}"
            )

            # Check success (0 = got value, -1 = empty)
            is_ok = cg.builder.icmp_signed("==", status, ir.Constant(i64, 0),
                                            name=f"select_ok_{i}")

            # If success, go to case body; else try next channel or yield
            next_block = try_blocks[i + 1] if i + 1 < num_cases else yield_block
            cg.builder.cbranch(is_ok, body_blocks[i], next_block)

            # Generate case body
            cg.builder.position_at_end(body_blocks[i])
            cg._enter_scope()

            # Load received value
            recv_val = cg.builder.load(out_alloca, name=f"select_val_{i}")

            # Bind the case variable
            # Determine channel element type for proper binding
            ch_elem_type = self._get_channel_elem_type(case.channel)

            if ch_elem_type is not None and cg._is_reference_type(ch_elem_type):
                # Heap type: recv_val is a GC handle (i64)
                # Store handle directly - generate_identifier will deref when needed
                alloca = cg.builder.alloca(i64, name=case.var_name)
                cg.locals[case.var_name] = alloca
                cg.builder.store(recv_val, alloca)
                cg.var_coex_types[case.var_name] = ch_elem_type
                # Register struct pointer type for handle deref at point of use
                struct_ptr_type = cg._get_struct_ptr_type(ch_elem_type)
                cg.var_ptr_types[case.var_name] = struct_ptr_type
            else:
                # Primitive type: just store the i64 value
                alloca = cg.builder.alloca(i64, name=case.var_name)
                cg.locals[case.var_name] = alloca
                cg.builder.store(recv_val, alloca)

                if ch_elem_type is not None:
                    cg.var_coex_types[case.var_name] = ch_elem_type

            cg._register_var_in_scope(case.var_name)

            # Execute case body statements
            for s in case.body:
                cg._generate_statement(s)
                if cg.builder.block.is_terminated:
                    break

            cg._exit_scope()

            if not cg.builder.block.is_terminated:
                cg.builder.branch(done_block)

        # Yield block: all channels empty, yield CPU, inject safepoint, retry
        cg.builder.position_at_end(yield_block)
        cg.builder.call(cg.gc.sched_yield, [])

        # GC safepoint at back-edge (like while loops)
        if cg._thread is not None:
            cg._thread.inject_safepoint(cg.builder, done_block)
        else:
            cg.builder.call(cg.gc.gc_safepoint, [])

        cg.builder.branch(poll_block)

        # Continue after select
        cg.builder.position_at_end(done_block)

    def _get_channel_elem_type(self, channel_expr: Expr):
        """Get the element type of a channel expression from var_coex_types."""
        cg = self.cg
        if isinstance(channel_expr, Identifier):
            ch_type = cg.var_coex_types.get(channel_expr.name)
            if isinstance(ch_type, ChannelType):
                return ch_type.element_type
        return None
