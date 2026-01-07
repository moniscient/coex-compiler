"""
Statement Code Generation for Coex.

This module handles:
- Statement dispatch (_generate_statement)
- Variable declarations (_generate_var_decl)
- Assignments (_generate_assignment)
- Print and debug statements
- Return statements
- Tuple destructuring
- In-place mutation optimization for update patterns
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict, Tuple
from typing import List as PyList

from ast_nodes import (
    Stmt, VarDecl, Assignment, SliceAssignment, ReturnStmt, PrintStmt, DebugStmt,
    IfStmt, WhileStmt, CycleStmt, ForStmt, ForAssignStmt, BreakStmt, ContinueStmt,
    FirstAssignStmt, MostAssignStmt,
    MatchStmt, ExprStmt, LlvmIrStmt, TupleDestructureStmt, TupleExpr,
    Identifier, MemberExpr, IndexExpr, CallExpr, MethodCallExpr,
    MapExpr, ListExpr, SetExpr, StringLiteral, NilLiteral, JsonObjectExpr,
    AssignOp, FunctionKind, ListType, SetType, MapType, ArrayType, TupleType,
    OptionalType, PrimitiveType, NamedType
)

# Import uniqueness analysis for in-place mutation optimization
from analysis.uniqueness import can_optimize_statement, get_update_pattern

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class StatementGenerator:
    """Generates statement-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # In-Place Mutation Optimization
    # ========================================================================

    def try_generate_inplace_update(self, stmt: VarDecl) -> bool:
        """
        Try to generate in-place mutation for an update pattern.

        Detects patterns like: x = x.add(y) where x is a Set/Map/List
        and generates the in-place variant instead of allocating a new wrapper.

        IMPORTANT: Only safe when the variable's value has NOT been aliased
        (copied to another variable). If aliased, we must create a new wrapper
        to preserve value semantics.

        Returns True if in-place optimization was applied, False otherwise.
        """
        cg = self.cg

        # Check if this is an update pattern
        if not can_optimize_statement(stmt):
            return False

        pattern = get_update_pattern(stmt)
        if pattern is None:
            return False

        var_name, method_name, args = pattern

        # Make sure the variable exists (must be reassignment, not first declaration)
        if var_name not in cg.locals:
            return False

        # CRITICAL: Check if the variable's value has been aliased
        # If another variable was assigned from this one, we cannot mutate in-place
        # because that would violate value semantics for the other variable.
        if hasattr(cg, 'aliased_vars') and var_name in cg.aliased_vars:
            return False

        # Get the variable's type to determine which in-place function to use
        coex_type = cg.var_coex_types.get(var_name)
        if coex_type is None:
            # Try to infer from LLVM type
            alloca = cg.locals[var_name]
            pointee = alloca.type.pointee
            if not hasattr(pointee, 'name'):
                return False
            struct_name = pointee.name
            if struct_name == "struct.Set":
                coex_type = SetType(PrimitiveType("int"))  # Default assumption
            elif struct_name == "struct.Map":
                coex_type = MapType(PrimitiveType("int"), PrimitiveType("int"))
            elif struct_name == "struct.List":
                coex_type = ListType(PrimitiveType("int"))
            else:
                return False

        # Get the in-place function
        inplace_func = self._get_inplace_function(coex_type, method_name)
        if inplace_func is None:
            return False

        # Generate the in-place call
        return self._generate_inplace_call(var_name, method_name, args, coex_type, inplace_func)

    def _get_inplace_function(self, coex_type, method_name: str):
        """Get the in-place function for a given type and method."""
        cg = self.cg

        # Check if inplace_variants mapping exists
        if not hasattr(cg, 'inplace_variants') or not cg.inplace_variants:
            return None

        # Determine the normal function name based on type
        if isinstance(coex_type, SetType):
            if method_name == "add":
                # Check if element type is supported
                elem_type = coex_type.element_type
                if isinstance(elem_type, PrimitiveType):
                    if elem_type.name == "string":
                        normal_func = "coex_set_add_string"
                    else:
                        normal_func = "coex_set_add"
                else:
                    # Skip in-place for non-primitive element types
                    return None
            elif method_name == "remove":
                # Only support remove for primitive element types
                elem_type = coex_type.element_type
                if not isinstance(elem_type, PrimitiveType):
                    return None
                normal_func = "coex_set_remove"
            else:
                return None
        elif isinstance(coex_type, MapType):
            if method_name in ("put", "set"):
                # Only support in-place for primitive value types (not heap types like List)
                # because our in-place functions expect i64 values
                value_type = coex_type.value_type
                if not isinstance(value_type, PrimitiveType):
                    return None  # Skip in-place for complex value types

                # Check if key type is string
                key_type = coex_type.key_type
                if isinstance(key_type, PrimitiveType) and key_type.name == "string":
                    normal_func = "coex_map_put_string"
                else:
                    normal_func = "coex_map_put"
            elif method_name == "remove":
                normal_func = "coex_map_remove"
            else:
                return None
        elif isinstance(coex_type, ListType):
            if method_name == "append":
                normal_func = "coex_pv_append"
            else:
                return None
        elif isinstance(coex_type, ArrayType):
            if method_name == "set":
                normal_func = "coex_array_set"
            else:
                return None
        else:
            return None

        # Look up the in-place variant
        inplace_name = cg.inplace_variants.get(normal_func)
        if inplace_name is None:
            return None

        return cg.functions.get(inplace_name)

    def _generate_inplace_call(self, var_name: str, method_name: str, args: list,
                               coex_type, inplace_func) -> bool:
        """Generate the actual in-place function call."""
        cg = self.cg

        # Load the wrapper pointer
        alloca = cg.locals[var_name]
        wrapper_ptr = cg.builder.load(alloca)

        # Generate arguments - Array.set needs special handling
        llvm_args = [wrapper_ptr]

        if isinstance(coex_type, ArrayType) and method_name == "set":
            # Array.set(index, value) -> array_set_inplace(arr, index, value_ptr, elem_size)
            index = cg._generate_expression(args[0])
            elem_val = cg._generate_expression(args[1])
            elem_type = elem_val.type

            # Compute elem_size
            if isinstance(elem_type, ir.IntType):
                size = max(1, elem_type.width // 8)
            elif isinstance(elem_type, ir.DoubleType):
                size = 8
            elif isinstance(elem_type, ir.PointerType):
                size = 8
            else:
                size = 8

            elem_size = ir.Constant(ir.IntType(64), size)

            # Store value in alloca and get pointer
            with cg.builder.goto_entry_block():
                temp = cg.builder.alloca(elem_type, name="array_set_inplace_elem")
            cg.builder.store(elem_val, temp)
            temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

            if index.type != ir.IntType(64):
                index = cg.builder.sext(index, ir.IntType(64))

            llvm_args = [wrapper_ptr, index, temp_ptr, elem_size]
        else:
            # Standard argument generation for Set/Map
            for arg in args:
                arg_val = cg._generate_expression(arg)
                llvm_args.append(arg_val)

        # Call the in-place function (returns void)
        cg.builder.call(inplace_func, llvm_args)

        # No need to store result - wrapper was mutated in place
        # The handle in the variable slot is still valid

        # Update GC root if needed (handle unchanged, but for consistency)
        if var_name in cg.gc_root_indices and cg.gc is not None:
            root_idx = cg.gc_root_indices[var_name]
            cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, wrapper_ptr)

        return True

    # ========================================================================
    # Statement Generation
    # ========================================================================

    def generate_statement(self, stmt: Stmt):
        """Generate code for a statement"""
        cg = self.cg

        if isinstance(stmt, VarDecl):
            self.generate_var_decl(stmt)
        elif isinstance(stmt, TupleDestructureStmt):
            self.generate_tuple_destructure(stmt)
        elif isinstance(stmt, Assignment):
            self.generate_assignment(stmt)
        elif isinstance(stmt, SliceAssignment):
            self.generate_slice_assignment(stmt)
        elif isinstance(stmt, ReturnStmt):
            self.generate_return(stmt)
        elif isinstance(stmt, PrintStmt):
            self.generate_print(stmt)
        elif isinstance(stmt, DebugStmt):
            self.generate_debug(stmt)
        elif isinstance(stmt, IfStmt):
            cg._generate_if(stmt)
        elif isinstance(stmt, WhileStmt):
            cg._generate_while(stmt)
        elif isinstance(stmt, CycleStmt):
            cg._generate_cycle(stmt)
        elif isinstance(stmt, ForStmt):
            cg._generate_for(stmt)
        elif isinstance(stmt, ForAssignStmt):
            cg._generate_for_assign(stmt)
        elif isinstance(stmt, FirstAssignStmt):
            cg._generate_first_assign(stmt)
        elif isinstance(stmt, MostAssignStmt):
            cg._generate_most_assign(stmt)
        elif isinstance(stmt, BreakStmt):
            cg._generate_break()
        elif isinstance(stmt, ContinueStmt):
            cg._generate_continue()
        elif isinstance(stmt, MatchStmt):
            cg._generate_match(stmt)
        elif isinstance(stmt, LlvmIrStmt):
            cg._generate_llvm_ir_block(stmt)
        elif isinstance(stmt, ExprStmt):
            cg._generate_expression(stmt.expr)

    def generate_var_decl(self, stmt: VarDecl):
        """Generate a local variable declaration or reassignment"""
        cg = self.cg

        # Track whether this is a new variable for scope registration
        is_new_var = stmt.name not in cg.locals

        # Formulas require const bindings for purity
        if not stmt.is_const and cg.current_function is not None:
            if cg.current_function.kind == FunctionKind.FORMULA:
                raise RuntimeError(
                    f"Formula '{cg.current_function.name}' requires const bindings. "
                    f"Use 'const {stmt.name} = ...' instead of '{stmt.name} = ...'."
                )

        # Handle reassignment vs new binding based on 'const' keyword
        if not stmt.is_const and stmt.name in cg.locals:
            is_placeholder = stmt.name in cg.placeholder_vars

            if not is_placeholder:
                if stmt.name in cg.const_bindings:
                    raise RuntimeError(
                        f"Cannot reassign const binding '{stmt.name}'. "
                        f"Remove 'const' from the declaration to make it rebindable."
                    )

                # Try in-place mutation optimization for update patterns
                # Pattern: x = x.add(y) where x is a Set/Map/List
                if self.try_generate_inplace_update(stmt):
                    # Successfully generated in-place update
                    # Clear moved_vars if this var was moved
                    if stmt.name in cg.moved_vars:
                        cg.moved_vars.discard(stmt.name)
                    return

                self.generate_var_reassignment(stmt)
                return

        # Track const bindings
        if stmt.is_const:
            cg.const_bindings.add(stmt.name)

        # Check if this is a cycle variable - write to write buffer
        ctx = cg._get_cycle_context()
        if ctx and stmt.name in ctx['cycle_vars']:
            init_value = cg._generate_expression(stmt.initializer)
            write_buf = ctx['write_buffers'][stmt.name]
            expected_type = ctx['var_types'].get(stmt.name)
            if expected_type:
                init_value = cg._cast_value(init_value, expected_type)
            cg.builder.store(init_value, write_buf)
            return

        # Track if we need to mark source as moved AFTER reading
        move_source_name = None
        if stmt.is_move and isinstance(stmt.initializer, Identifier):
            move_source_name = stmt.initializer.name

        if stmt.type_annotation:
            llvm_type = cg._get_llvm_type(stmt.type_annotation)
            cg.var_coex_types[stmt.name] = stmt.type_annotation
            if isinstance(stmt.type_annotation, TupleType):
                cg.tuple_field_info[stmt.name] = stmt.type_annotation.elements
        else:
            # Infer type from initializer
            init_value = cg._generate_expression(stmt.initializer)
            llvm_type = init_value.type

            # Check if variable was pre-allocated
            if stmt.name in cg.locals:
                existing_alloca = cg.locals[stmt.name]
                existing_type = existing_alloca.type.pointee

                if existing_type == llvm_type:
                    alloca = existing_alloca
                elif isinstance(existing_type, ir.IntType) and existing_type.width == 64:
                    func = cg.builder.function
                    entry_block = func.entry_basic_block
                    saved_block = cg.builder.block

                    if entry_block.is_terminated:
                        cg.builder.position_before(entry_block.terminator)
                    else:
                        cg.builder.position_at_end(entry_block)

                    alloca = cg.builder.alloca(llvm_type, name=f"{stmt.name}.typed")
                    cg.builder.position_at_end(saved_block)
                    cg.locals[stmt.name] = alloca
                else:
                    alloca = cg.builder.alloca(llvm_type, name=stmt.name)
            else:
                alloca = cg.builder.alloca(llvm_type, name=stmt.name)

            # Value semantics: deep copy collections
            inferred_coex_type = self._infer_coex_type_from_initializer(stmt)

            # Track aliasing for in-place optimization safety:
            # When copying a collection from another variable (e.g., s2 = s1),
            # mark the source as aliased so in-place mutation is disabled.
            source_var_name = None
            if isinstance(stmt.initializer, Identifier) and not stmt.is_move:
                source_var_name = stmt.initializer.name

            if inferred_coex_type and cg._is_collection_coex_type(inferred_coex_type):
                if stmt.is_move:
                    init_value = cg._generate_move_or_eager_copy(init_value, inferred_coex_type)
                else:
                    init_value = cg._generate_deep_copy(init_value, inferred_coex_type)
                    # Mark BOTH source and target as aliased because copy functions
                    # return the same pointer (COW semantics). Both variables now
                    # share the same wrapper, so neither can be mutated in-place.
                    if source_var_name:
                        cg.aliased_vars.add(source_var_name)
                        cg.aliased_vars.add(stmt.name)  # Target is also aliased
                cg.var_coex_types[stmt.name] = inferred_coex_type
            elif isinstance(init_value.type, ir.PointerType):
                pointee = init_value.type.pointee
                if hasattr(pointee, 'name'):
                    if pointee.name == "struct.List":
                        init_value = cg.builder.call(cg.list_copy, [init_value])
                        if source_var_name:
                            cg.aliased_vars.add(source_var_name)
                            cg.aliased_vars.add(stmt.name)  # Target is also aliased
                    elif pointee.name == "struct.Set":
                        init_value = cg.builder.call(cg.set_copy, [init_value])
                        if source_var_name:
                            cg.aliased_vars.add(source_var_name)
                            cg.aliased_vars.add(stmt.name)  # Target is also aliased
                    elif pointee.name == "struct.Map":
                        init_value = cg.builder.call(cg.map_copy, [init_value])
                        if source_var_name:
                            cg.aliased_vars.add(source_var_name)
                            cg.aliased_vars.add(stmt.name)  # Target is also aliased
                    elif pointee.name == "struct.String":
                        init_value = cg.builder.call(cg.string_copy, [init_value])
                        # Note: Strings are immutable, so aliasing doesn't affect in-place ops
                    elif pointee.name == "struct.Array":
                        if stmt.is_move:
                            init_value = cg._generate_move_or_eager_copy(init_value, ArrayType(PrimitiveType("int")))
                        else:
                            init_value = cg.builder.call(cg.array_copy, [init_value])
                            # Note: Arrays are immutable in Coex, no in-place ops

            cg.builder.store(init_value, alloca)
            cg.locals[stmt.name] = alloca

            if is_new_var:
                cg._register_var_in_scope(stmt.name)

            if stmt.name in cg.gc_root_indices and cg.gc is not None:
                root_idx = cg.gc_root_indices[stmt.name]
                cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, init_value)

            tuple_info = cg._infer_tuple_info(stmt.initializer)
            if tuple_info:
                cg.tuple_field_info[stmt.name] = tuple_info

            if move_source_name:
                cg.moved_vars.add(move_source_name)
            return

        # Type-annotated path
        if stmt.name in cg.locals:
            existing_alloca = cg.locals[stmt.name]
            existing_type = existing_alloca.type.pointee

            if existing_type == llvm_type:
                alloca = existing_alloca
            elif isinstance(existing_type, ir.IntType) and existing_type.width == 64:
                func = cg.builder.function
                entry_block = func.entry_basic_block
                saved_block = cg.builder.block

                if entry_block.is_terminated:
                    cg.builder.position_before(entry_block.terminator)
                else:
                    cg.builder.position_at_end(entry_block)

                alloca = cg.builder.alloca(llvm_type, name=f"{stmt.name}.typed")
                cg.builder.position_at_end(saved_block)
                cg.locals[stmt.name] = alloca
            else:
                alloca = cg.builder.alloca(llvm_type, name=stmt.name)
        else:
            alloca = cg.builder.alloca(llvm_type, name=stmt.name)

        # Generate initializer with special cases
        if isinstance(stmt.initializer, NilLiteral) and isinstance(stmt.type_annotation, OptionalType):
            inner_type = cg._get_llvm_type(stmt.type_annotation.inner)
            init_value = ir.Constant(llvm_type, ir.Undefined)
            init_value = cg.builder.insert_value(init_value, ir.Constant(ir.IntType(1), 0), 0)
            if isinstance(inner_type, ir.IntType):
                init_value = cg.builder.insert_value(init_value, ir.Constant(inner_type, 0), 1)
            elif isinstance(inner_type, ir.DoubleType):
                init_value = cg.builder.insert_value(init_value, ir.Constant(inner_type, 0.0), 1)
            else:
                init_value = cg.builder.insert_value(init_value, ir.Constant(inner_type, None), 1)
        elif (isinstance(stmt.initializer, MapExpr) and len(stmt.initializer.entries) == 0) or \
             (isinstance(stmt.initializer, JsonObjectExpr) and len(stmt.initializer.entries) == 0):
            if isinstance(stmt.type_annotation, SetType):
                i64 = ir.IntType(64)
                flags = cg._compute_set_flags(stmt.type_annotation.element_type)
                init_value = cg.builder.call(cg.set_new, [ir.Constant(i64, flags)])
            elif isinstance(stmt.type_annotation, MapType):
                i64 = ir.IntType(64)
                flags = cg._compute_map_flags(stmt.type_annotation.key_type, stmt.type_annotation.value_type)
                init_value = cg.builder.call(cg.map_new, [ir.Constant(i64, flags)])
            else:
                init_value = cg._generate_expression(stmt.initializer)
        elif isinstance(stmt.type_annotation, PrimitiveType) and stmt.type_annotation.name == "json":
            init_value = cg._generate_expression(stmt.initializer)
            init_value = cg._convert_to_json(init_value, stmt.initializer)
        else:
            init_value = cg._generate_expression(stmt.initializer)

        # Try implicit collection conversion
        if isinstance(stmt.type_annotation, (ListType, ArrayType, SetType)):
            converted_value, was_converted = cg._try_implicit_collection_conversion(
                init_value, stmt.type_annotation
            )
            if was_converted:
                source_struct = init_value.type.pointee.name if isinstance(init_value.type, ir.PointerType) else "unknown"
                warning_msg = cg._get_conversion_warning_message(source_struct,
                    "struct.List" if isinstance(stmt.type_annotation, ListType) else
                    "struct.Array" if isinstance(stmt.type_annotation, ArrayType) else "struct.Set")
                cg._emit_warning("PERF", warning_msg)
                init_value = converted_value

        init_value = cg._cast_value(init_value, llvm_type)

        # Track aliasing for in-place optimization safety (type-annotated path)
        typed_source_var_name = None
        if isinstance(stmt.initializer, Identifier) and not stmt.is_move:
            typed_source_var_name = stmt.initializer.name

        # Value semantics for typed collections
        if cg._is_collection_coex_type(stmt.type_annotation):
            if stmt.is_move:
                init_value = cg._generate_move_or_eager_copy(init_value, stmt.type_annotation)
            else:
                init_value = cg._generate_deep_copy(init_value, stmt.type_annotation)
                # Mark BOTH source and target as aliased (COW semantics)
                if typed_source_var_name:
                    cg.aliased_vars.add(typed_source_var_name)
                    cg.aliased_vars.add(stmt.name)  # Target is also aliased
        elif isinstance(init_value.type, ir.PointerType):
            if isinstance(stmt.type_annotation, NamedType) and stmt.type_annotation.name in cg.type_fields:
                if stmt.is_move:
                    init_value = cg._generate_move_or_eager_copy(init_value, stmt.type_annotation)
                else:
                    init_value = cg._generate_deep_copy(init_value, stmt.type_annotation)
                    # User-defined types with fields: mark both as aliased
                    if typed_source_var_name:
                        cg.aliased_vars.add(typed_source_var_name)
                        cg.aliased_vars.add(stmt.name)  # Target is also aliased

        cg.builder.store(init_value, alloca)
        cg.locals[stmt.name] = alloca

        if is_new_var:
            cg._register_var_in_scope(stmt.name)

        cg.placeholder_vars.discard(stmt.name)

        if stmt.name in cg.gc_root_indices and cg.gc is not None:
            root_idx = cg.gc_root_indices[stmt.name]
            cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, init_value)

        if move_source_name:
            cg.moved_vars.add(move_source_name)

    def _infer_coex_type_from_initializer(self, stmt: VarDecl):
        """Infer Coex type from initializer expression"""
        cg = self.cg
        inferred_coex_type = None

        if isinstance(stmt.initializer, Identifier):
            var_name = stmt.initializer.name
            if var_name in cg.var_coex_types:
                inferred_coex_type = cg.var_coex_types[var_name]
        elif isinstance(stmt.initializer, (MapExpr, ListExpr, SetExpr)):
            inferred_coex_type = cg._infer_type_from_expr(stmt.initializer)
            cg.var_coex_types[stmt.name] = inferred_coex_type
        elif isinstance(stmt.initializer, StringLiteral):
            cg.var_coex_types[stmt.name] = PrimitiveType("string")
        elif isinstance(stmt.initializer, MethodCallExpr):
            if isinstance(stmt.initializer.object, Identifier):
                receiver_name = stmt.initializer.object.name
                if receiver_name in cg.var_coex_types:
                    receiver_type = cg.var_coex_types[receiver_name]
                    if stmt.initializer.method in ("set", "append", "remove", "pop", "insert"):
                        inferred_coex_type = receiver_type
                        cg.var_coex_types[stmt.name] = inferred_coex_type
                    elif stmt.initializer.method == "split" and isinstance(receiver_type, PrimitiveType) and receiver_type.name == "string":
                        inferred_coex_type = ListType(PrimitiveType("string"))
                        cg.var_coex_types[stmt.name] = inferred_coex_type
        elif isinstance(stmt.initializer, CallExpr):
            if isinstance(stmt.initializer.callee, MemberExpr):
                callee_member = stmt.initializer.callee
                method_name = callee_member.member
                receiver_type = cg._get_receiver_type(callee_member.object)
                if receiver_type:
                    if method_name in ("set", "append", "remove", "pop", "insert"):
                        inferred_coex_type = receiver_type
                        cg.var_coex_types[stmt.name] = inferred_coex_type
                    elif method_name == "split" and isinstance(receiver_type, PrimitiveType) and receiver_type.name == "string":
                        inferred_coex_type = ListType(PrimitiveType("string"))
                        cg.var_coex_types[stmt.name] = inferred_coex_type

        return inferred_coex_type

    def generate_var_reassignment(self, stmt: VarDecl):
        """Generate reassignment to an existing variable"""
        cg = self.cg
        alloca = cg.locals[stmt.name]

        move_source_name = None
        if stmt.is_move and isinstance(stmt.initializer, Identifier):
            move_source_name = stmt.initializer.name

        # Track aliasing for in-place optimization safety
        reassign_source_var_name = None
        if isinstance(stmt.initializer, Identifier) and not stmt.is_move:
            reassign_source_var_name = stmt.initializer.name

        value = cg._generate_expression(stmt.initializer)
        expected_type = alloca.type.pointee
        value = cg._cast_value(value, expected_type)

        coex_type = cg.var_coex_types.get(stmt.name)
        if coex_type and cg._is_collection_coex_type(coex_type):
            if stmt.is_move:
                value = cg._generate_move_or_eager_copy(value, coex_type)
            else:
                value = cg._generate_deep_copy(value, coex_type)
                # Mark BOTH source and target as aliased (COW semantics)
                if reassign_source_var_name:
                    cg.aliased_vars.add(reassign_source_var_name)
                    cg.aliased_vars.add(stmt.name)  # Target is also aliased
        elif isinstance(value.type, ir.PointerType):
            pointee = value.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List" and not stmt.is_move:
                    value = cg.builder.call(cg.list_copy, [value])
                    if reassign_source_var_name:
                        cg.aliased_vars.add(reassign_source_var_name)
                        cg.aliased_vars.add(stmt.name)  # Target is also aliased
                elif pointee.name == "struct.Set" and not stmt.is_move:
                    value = cg.builder.call(cg.set_copy, [value])
                    if reassign_source_var_name:
                        cg.aliased_vars.add(reassign_source_var_name)
                        cg.aliased_vars.add(stmt.name)  # Target is also aliased
                elif pointee.name == "struct.Map" and not stmt.is_move:
                    value = cg.builder.call(cg.map_copy, [value])
                    if reassign_source_var_name:
                        cg.aliased_vars.add(reassign_source_var_name)
                        cg.aliased_vars.add(stmt.name)  # Target is also aliased
                elif pointee.name == "struct.String" and not stmt.is_move:
                    value = cg.builder.call(cg.string_copy, [value])
                    # Note: Strings are immutable, no in-place ops
                elif pointee.name == "struct.Array" and not stmt.is_move:
                    value = cg.builder.call(cg.array_copy, [value])
                    # Note: Arrays are immutable in Coex, no in-place ops

        cg.builder.store(value, alloca)

        if stmt.name in cg.gc_root_indices and cg.gc is not None:
            root_idx = cg.gc_root_indices[stmt.name]
            cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, value)

        if move_source_name:
            cg.moved_vars.add(move_source_name)

        if stmt.name in cg.moved_vars:
            cg.moved_vars.discard(stmt.name)

    def generate_tuple_destructure(self, stmt: 'TupleDestructureStmt'):
        """Generate code for tuple destructuring: (a, b) = expr"""
        cg = self.cg
        tuple_val = cg._generate_expression(stmt.value)

        if isinstance(tuple_val.type, ir.LiteralStructType):
            for i, name in enumerate(stmt.names):
                if i < len(tuple_val.type.elements):
                    elem_type = tuple_val.type.elements[i]
                    elem_val = cg.builder.extract_value(tuple_val, i)

                    if name in cg.locals:
                        alloca = cg.locals[name]
                        if alloca.type.pointee != elem_type:
                            elem_val = cg._cast_value(elem_val, alloca.type.pointee)
                        cg.builder.store(elem_val, alloca)
                    else:
                        alloca = cg.builder.alloca(elem_type, name=name)
                        cg.builder.store(elem_val, alloca)
                        cg.locals[name] = alloca

                    if name in cg.gc_root_indices and cg.gc is not None:
                        root_idx = cg.gc_root_indices[name]
                        cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, elem_val)
        else:
            for name in stmt.names:
                if name in cg.locals:
                    alloca = cg.locals[name]
                    cg.builder.store(ir.Constant(ir.IntType(64), 0), alloca)
                else:
                    alloca = cg.builder.alloca(ir.IntType(64), name=name)
                    cg.builder.store(ir.Constant(ir.IntType(64), 0), alloca)
                    cg.locals[name] = alloca

    def generate_assignment(self, stmt: Assignment):
        """Generate an assignment"""
        cg = self.cg

        move_source_name = None
        if stmt.op == AssignOp.MOVE_ASSIGN and isinstance(stmt.value, Identifier):
            move_source_name = stmt.value.name

        if isinstance(stmt.target, Identifier):
            target_name = stmt.target.name
            if target_name in cg.moved_vars:
                cg.moved_vars.discard(target_name)

        if isinstance(stmt.target, Identifier):
            if stmt.target.name in cg.const_bindings:
                raise RuntimeError(
                    f"Cannot reassign const binding '{stmt.target.name}'. "
                    f"Remove 'const' from the declaration to make it rebindable."
                )

        # Check if target is a cycle variable
        if isinstance(stmt.target, Identifier):
            ctx = cg._get_cycle_context()
            if ctx and stmt.target.name in ctx['cycle_vars']:
                name = stmt.target.name
                value = cg._generate_expression(stmt.value)

                if stmt.op != AssignOp.ASSIGN and stmt.op != AssignOp.MOVE_ASSIGN:
                    old_val = cg.builder.load(ctx['read_buffers'][name])
                    value = self._apply_compound_op(stmt.op, old_val, value)

                expected_type = ctx['var_types'].get(name)
                if expected_type:
                    value = cg._cast_value(value, expected_type)
                cg.builder.store(value, ctx['write_buffers'][name])
                return

        # Tuple assignment
        if isinstance(stmt.target, TupleExpr):
            value = cg._generate_expression(stmt.value)
            self.generate_tuple_assignment(stmt.target, value)
            return

        # Member assignment (field access)
        if isinstance(stmt.target, MemberExpr):
            self.generate_member_assignment(stmt)
            return

        # Index assignment
        if isinstance(stmt.target, IndexExpr):
            self.generate_index_assignment(stmt)
            return

        # Simple variable assignment
        if isinstance(stmt.target, Identifier):
            name = stmt.target.name
            value = cg._generate_expression(stmt.value)

            if name in cg.locals:
                alloca = cg.locals[name]

                if stmt.op != AssignOp.ASSIGN and stmt.op != AssignOp.MOVE_ASSIGN:
                    old_val = cg.builder.load(alloca)
                    value = self._apply_compound_op(stmt.op, old_val, value)

                expected_type = alloca.type.pointee
                value = cg._cast_value(value, expected_type)

                # Value semantics for collections
                coex_type = cg.var_coex_types.get(name)
                if coex_type and cg._is_collection_coex_type(coex_type):
                    if stmt.op == AssignOp.MOVE_ASSIGN:
                        value = cg._generate_move_or_eager_copy(value, coex_type)
                    else:
                        value = cg._generate_deep_copy(value, coex_type)
                elif isinstance(value.type, ir.PointerType):
                    pointee = value.type.pointee
                    if hasattr(pointee, 'name'):
                        if pointee.name == "struct.List" and stmt.op != AssignOp.MOVE_ASSIGN:
                            value = cg.builder.call(cg.list_copy, [value])
                        elif pointee.name == "struct.Set" and stmt.op != AssignOp.MOVE_ASSIGN:
                            value = cg.builder.call(cg.set_copy, [value])
                        elif pointee.name == "struct.Map" and stmt.op != AssignOp.MOVE_ASSIGN:
                            value = cg.builder.call(cg.map_copy, [value])
                        elif pointee.name == "struct.String" and stmt.op != AssignOp.MOVE_ASSIGN:
                            value = cg.builder.call(cg.string_copy, [value])
                        elif pointee.name == "struct.Array" and stmt.op != AssignOp.MOVE_ASSIGN:
                            value = cg.builder.call(cg.array_copy, [value])

                cg.builder.store(value, alloca)

                if name in cg.gc_root_indices and cg.gc is not None:
                    root_idx = cg.gc_root_indices[name]
                    cg.gc.set_root(cg.builder, cg.gc_frame, root_idx, value)

        if move_source_name:
            cg.moved_vars.add(move_source_name)

    def _apply_compound_op(self, op: AssignOp, old_val: ir.Value, value: ir.Value) -> ir.Value:
        """Apply compound assignment operation"""
        cg = self.cg
        is_float = isinstance(old_val.type, ir.DoubleType)

        if op == AssignOp.PLUS_ASSIGN:
            return cg.builder.fadd(old_val, value) if is_float else cg.builder.add(old_val, value)
        elif op == AssignOp.MINUS_ASSIGN:
            return cg.builder.fsub(old_val, value) if is_float else cg.builder.sub(old_val, value)
        elif op == AssignOp.STAR_ASSIGN:
            return cg.builder.fmul(old_val, value) if is_float else cg.builder.mul(old_val, value)
        elif op == AssignOp.SLASH_ASSIGN:
            return cg.builder.fdiv(old_val, value) if is_float else cg.builder.sdiv(old_val, value)
        elif op == AssignOp.PERCENT_ASSIGN:
            return cg.builder.frem(old_val, value) if is_float else cg.builder.srem(old_val, value)
        return value

    def generate_tuple_assignment(self, target: TupleExpr, value: ir.Value):
        """Generate assignment to tuple target (destructuring)"""
        cg = self.cg

        if isinstance(value.type, ir.LiteralStructType):
            for i, (elem_name, elem_expr) in enumerate(target.elements):
                if i < len(value.type.elements):
                    elem_val = cg.builder.extract_value(value, i)

                    if isinstance(elem_expr, Identifier):
                        name = elem_expr.name
                        if name in cg.locals:
                            alloca = cg.locals[name]
                            elem_val = cg._cast_value(elem_val, alloca.type.pointee)
                            cg.builder.store(elem_val, alloca)

    def generate_member_assignment(self, stmt: Assignment):
        """Generate assignment to member expression"""
        cg = self.cg
        target = stmt.target

        # Immutable field assignment returns new object
        new_value = cg._generate_expression(stmt.value)
        cg._generate_immutable_field_assignment(target, new_value, stmt.op)

    def generate_index_assignment(self, stmt: Assignment):
        """Generate assignment to index expression"""
        cg = self.cg
        target = stmt.target
        obj = cg._generate_expression(target.object)
        index = cg._generate_expression(target.indices[0])
        value = cg._generate_expression(stmt.value)

        type_name = cg._get_type_name_from_ptr(obj.type)

        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name'):
                if pointee.name == "struct.List":
                    # Call list_set which returns NEW list
                    elem_type = value.type
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    with cg.builder.goto_entry_block():
                        temp = cg.builder.alloca(elem_type, name="idx_set_elem")
                    cg.builder.store(value, temp)
                    temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    if index.type != ir.IntType(64):
                        index = cg.builder.sext(index, ir.IntType(64))

                    new_list = cg.builder.call(cg.list_set, [obj, index, temp_ptr, elem_size])

                    # Update variable with new list
                    if isinstance(target.object, Identifier):
                        var_name = target.object.name
                        if var_name in cg.locals:
                            cg.builder.store(new_list, cg.locals[var_name])
                    return

                if pointee.name == "struct.Array":
                    elem_type = value.type
                    if isinstance(elem_type, ir.IntType):
                        size = max(1, elem_type.width // 8)
                    elif isinstance(elem_type, ir.DoubleType):
                        size = 8
                    elif isinstance(elem_type, ir.PointerType):
                        size = 8
                    else:
                        size = 8

                    elem_size = ir.Constant(ir.IntType(64), size)

                    with cg.builder.goto_entry_block():
                        temp = cg.builder.alloca(elem_type, name="array_set_elem")
                    cg.builder.store(value, temp)
                    temp_ptr = cg.builder.bitcast(temp, ir.IntType(8).as_pointer())

                    if index.type != ir.IntType(64):
                        index = cg.builder.sext(index, ir.IntType(64))

                    new_array = cg.builder.call(cg.array_set, [obj, index, temp_ptr, elem_size])

                    if isinstance(target.object, Identifier):
                        var_name = target.object.name
                        if var_name in cg.locals:
                            cg.builder.store(new_array, cg.locals[var_name])
                    return

    def generate_slice_assignment(self, stmt: SliceAssignment):
        """Generate slice assignment: obj[start:end] = value"""
        cg = self.cg
        obj = cg._generate_expression(stmt.target)
        value = cg._generate_expression(stmt.value)
        i64 = ir.IntType(64)

        length = cg._expressions.get_collection_length(obj)

        if stmt.start is None:
            start = ir.Constant(i64, 0)
        else:
            start = cg._generate_expression(stmt.start)
            start = cg._cast_value(start, i64)
            start = cg._expressions.normalize_slice_index(start, length)

        if stmt.end is None:
            end = length
        else:
            end = cg._generate_expression(stmt.end)
            end = cg._cast_value(end, i64)
            end = cg._expressions.normalize_slice_index(end, length)

        type_name = cg._get_type_name_from_ptr(obj.type)
        if type_name and type_name in cg.type_methods:
            method_map = cg.type_methods[type_name]
            if "setrange" in method_map:
                mangled = method_map["setrange"]
                func = cg.functions[mangled]
                new_obj = cg.builder.call(func, [obj, start, end, value])

                if isinstance(stmt.target, Identifier):
                    var_name = stmt.target.name
                    if var_name in cg.locals:
                        cg.builder.store(new_obj, cg.locals[var_name])
                return

        if isinstance(obj.type, ir.PointerType):
            pointee = obj.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.List":
                new_list = cg.builder.call(cg.list_setrange, [obj, start, end, value])
                if isinstance(stmt.target, Identifier):
                    var_name = stmt.target.name
                    if var_name in cg.locals:
                        cg.builder.store(new_list, cg.locals[var_name])

    def generate_return(self, stmt: ReturnStmt):
        """Generate return statement"""
        cg = self.cg

        if stmt.value:
            ret_val = cg._generate_expression(stmt.value)
            func = cg.builder.function
            ret_type = func.function_type.return_type
            ret_val = cg._cast_value(ret_val, ret_type)

            # Join nursery tasks before return (structured concurrency guarantee)
            if cg._task is not None and cg._task.has_active_nursery():
                cg._task.join_nursery(cg.builder)

            # Promote escaping values before arena pop (Phase 6)
            # If returning a pointer and we have an arena, the value might be arena-allocated
            if getattr(cg, 'arena_start', None) is not None and cg.gc is not None:
                if isinstance(ret_type, ir.PointerType):
                    # Promote to heap - returns same ptr if already on heap
                    ret_val_i8 = cg.builder.bitcast(ret_val, ir.IntType(8).as_pointer())
                    promoted = cg.builder.call(cg.gc.gc_promote_to_heap, [ret_val_i8])
                    ret_val = cg.builder.bitcast(promoted, ret_type)

            # Pop arena before GC frame (Phase 6)
            if getattr(cg, 'arena_start', None) is not None and cg.gc is not None:
                cg.builder.call(cg.gc.gc_arena_pop, [cg.arena_start])

            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            cg.builder.ret(ret_val)
        else:
            # Join nursery tasks before return (structured concurrency guarantee)
            if cg._task is not None and cg._task.has_active_nursery():
                cg._task.join_nursery(cg.builder)

            # Pop arena before GC frame (Phase 6)
            if getattr(cg, 'arena_start', None) is not None and cg.gc is not None:
                cg.builder.call(cg.gc.gc_arena_pop, [cg.arena_start])

            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)
            cg.builder.ret_void()

    def generate_print(self, stmt: PrintStmt):
        """Generate print statement"""
        cg = self.cg

        if not cg.printing_enabled:
            return

        value = cg._generate_expression(stmt.value)

        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
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

        null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        cg.builder.call(cg.fflush, [null_ptr])

    def generate_debug(self, stmt: DebugStmt):
        """Generate debug statement (prints to stderr)"""
        cg = self.cg

        if not cg.debugging_enabled:
            return

        value = cg._generate_expression(stmt.value)
        stderr_fd = ir.Constant(ir.IntType(32), 2)

        if isinstance(value.type, ir.IntType):
            if value.type.width == 1:
                true_block = cg.builder.append_basic_block("debug_true")
                false_block = cg.builder.append_basic_block("debug_false")
                merge_block = cg.builder.append_basic_block("debug_merge")

                cg.builder.cbranch(value, true_block, false_block)

                cg.builder.position_at_end(true_block)
                fmt_ptr = cg.builder.bitcast(cg._true_str, ir.IntType(8).as_pointer())
                cg.builder.call(cg.dprintf, [stderr_fd, fmt_ptr])
                cg.builder.branch(merge_block)

                cg.builder.position_at_end(false_block)
                fmt_ptr = cg.builder.bitcast(cg._false_str, ir.IntType(8).as_pointer())
                cg.builder.call(cg.dprintf, [stderr_fd, fmt_ptr])
                cg.builder.branch(merge_block)

                cg.builder.position_at_end(merge_block)
            else:
                fmt_ptr = cg.builder.bitcast(cg._int_fmt, ir.IntType(8).as_pointer())
                if value.type.width < 64:
                    value = cg.builder.sext(value, ir.IntType(64))
                cg.builder.call(cg.dprintf, [stderr_fd, fmt_ptr, value])

        elif isinstance(value.type, ir.DoubleType):
            fmt_ptr = cg.builder.bitcast(cg._float_fmt, ir.IntType(8).as_pointer())
            cg.builder.call(cg.dprintf, [stderr_fd, fmt_ptr, value])

        elif isinstance(value.type, ir.PointerType):
            pointee = value.type.pointee
            if hasattr(pointee, 'name') and pointee.name == "struct.String":
                cg.builder.call(cg.string_dprint, [stderr_fd, value])
            else:
                fmt_ptr = cg.builder.bitcast(cg._str_fmt, ir.IntType(8).as_pointer())
                cg.builder.call(cg.dprintf, [stderr_fd, fmt_ptr, value])

        null_ptr = ir.Constant(ir.IntType(8).as_pointer(), None)
        cg.builder.call(cg.fflush, [null_ptr])
