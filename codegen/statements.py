"""
Statements Module for Coex Code Generator

This module provides statement code generation for the Coex compiler.

Statement types handled:
- Variable declarations and assignments
- Control flow: if/elif/else, while, for, match
- Loop control: break, continue
- Return statements
- Print and debug statements
- Tuple destructuring
- Slice assignment
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator
    from ast_nodes import (
        Stmt, VarDecl, TupleDestructureStmt, Assignment, SliceAssignment,
        ReturnStmt, PrintStmt, DebugStmt, IfStmt, WhileStmt, CycleStmt,
        ForStmt, ForAssignStmt, MatchStmt, TupleExpr, MemberExpr, Pattern
    )


class StatementsGenerator:
    """Generates code for Coex statements."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def builder(self):
        return self.codegen.builder

    @property
    def module(self):
        return self.codegen.module

    @property
    def locals(self):
        return self.codegen.locals

    @property
    def functions(self):
        return self.codegen.functions

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_fields(self):
        return self.codegen.type_fields

    @property
    def loop_stack(self):
        return self.codegen.loop_stack

    @property
    def current_function(self):
        return self.codegen.current_function

    # ========================================================================
    # Main Statement Dispatcher
    # ========================================================================

    def generate_statement(self, stmt: 'Stmt'):
        """Generate code for a statement.

        Dispatches to specific handlers based on statement type.
        """
        return self.codegen._generate_statement(stmt)

    # ========================================================================
    # Variable Declaration and Assignment
    # ========================================================================

    def generate_var_decl(self, stmt: 'VarDecl'):
        """Generate a local variable declaration."""
        return self.codegen._generate_var_decl(stmt)

    def generate_var_reassignment(self, stmt: 'VarDecl'):
        """Generate variable reassignment."""
        return self.codegen._generate_var_reassignment(stmt)

    def generate_tuple_destructure(self, stmt: 'TupleDestructureStmt'):
        """Generate tuple destructuring assignment."""
        return self.codegen._generate_tuple_destructure(stmt)

    def generate_assignment(self, stmt: 'Assignment'):
        """Generate assignment statement."""
        return self.codegen._generate_assignment(stmt)

    def generate_tuple_assignment(self, target: 'TupleExpr', value: ir.Value):
        """Generate tuple assignment."""
        return self.codegen._generate_tuple_assignment(target, value)

    def generate_immutable_field_assignment(self, target: 'MemberExpr',
                                             new_value: ir.Value, op):
        """Generate immutable field assignment (creates new struct)."""
        return self.codegen._generate_immutable_field_assignment(target, new_value, op)

    def generate_slice_assignment(self, stmt: 'SliceAssignment'):
        """Generate slice assignment statement."""
        return self.codegen._generate_slice_assignment(stmt)

    # ========================================================================
    # Control Flow - Conditionals
    # ========================================================================

    def generate_if(self, stmt: 'IfStmt'):
        """Generate if/elif/else statement."""
        return self.codegen._generate_if(stmt)

    def generate_match(self, stmt: 'MatchStmt'):
        """Generate match statement."""
        return self.codegen._generate_match(stmt)

    def generate_pattern_match(self, subject: ir.Value,
                                pattern: 'Pattern') -> ir.Value:
        """Generate pattern matching code."""
        return self.codegen._generate_pattern_match(subject, pattern)

    # ========================================================================
    # Control Flow - Loops
    # ========================================================================

    def generate_while(self, stmt: 'WhileStmt'):
        """Generate while loop."""
        return self.codegen._generate_while(stmt)

    def generate_cycle(self, stmt: 'CycleStmt'):
        """Generate cycle statement (infinite loop with break)."""
        return self.codegen._generate_cycle(stmt)

    def generate_for(self, stmt: 'ForStmt'):
        """Generate for loop (dispatches to specific iterator type)."""
        return self.codegen._generate_for(stmt)

    def generate_range_for(self, stmt: 'ForStmt', use_nursery: bool = False):
        """Generate for loop over integer range."""
        return self.codegen._generate_range_for(stmt, use_nursery)

    def generate_range_expr_for(self, stmt: 'ForStmt', use_nursery: bool = False):
        """Generate for loop over range expression."""
        return self.codegen._generate_range_expr_for(stmt, use_nursery)

    def generate_list_for(self, stmt: 'ForStmt', list_ptr: ir.Value):
        """Generate for loop over list."""
        return self.codegen._generate_list_for(stmt, list_ptr)

    def generate_array_for(self, stmt: 'ForStmt', array_ptr: ir.Value):
        """Generate for loop over array."""
        return self.codegen._generate_array_for(stmt, array_ptr)

    def generate_map_for(self, stmt: 'ForStmt', map_ptr: ir.Value):
        """Generate for loop over map."""
        return self.codegen._generate_map_for(stmt, map_ptr)

    def generate_set_for(self, stmt: 'ForStmt', set_ptr: ir.Value):
        """Generate for loop over set."""
        return self.codegen._generate_set_for(stmt, set_ptr)

    def generate_for_assign(self, stmt: 'ForAssignStmt'):
        """Generate for-assign statement."""
        return self.codegen._generate_for_assign(stmt)

    # ========================================================================
    # Control Flow - Loop Control
    # ========================================================================

    def generate_break(self):
        """Generate break statement."""
        return self.codegen._generate_break()

    def generate_continue(self):
        """Generate continue statement."""
        return self.codegen._generate_continue()

    # ========================================================================
    # Return Statement
    # ========================================================================

    def generate_return(self, stmt: 'ReturnStmt'):
        """Generate return statement."""
        return self.codegen._generate_return(stmt)

    # ========================================================================
    # Output Statements
    # ========================================================================

    def generate_print(self, stmt: 'PrintStmt'):
        """Generate print statement."""
        return self.codegen._generate_print(stmt)

    def generate_debug(self, stmt: 'DebugStmt'):
        """Generate debug statement."""
        return self.codegen._generate_debug(stmt)

    # ========================================================================
    # Deep Copy Operations (for value semantics)
    # ========================================================================

    def generate_move_or_eager_copy(self, value: ir.Value, coex_type) -> ir.Value:
        """Generate move or eager copy based on type."""
        return self.codegen._generate_move_or_eager_copy(value, coex_type)

    def generate_deep_copy(self, value: ir.Value, coex_type) -> ir.Value:
        """Generate deep copy of value."""
        return self.codegen._generate_deep_copy(value, coex_type)

    def generate_list_deep_copy(self, src: ir.Value, elem_type) -> ir.Value:
        """Generate deep copy of list."""
        return self.codegen._generate_list_deep_copy(src, elem_type)

    def generate_set_deep_copy(self, src: ir.Value, elem_type) -> ir.Value:
        """Generate deep copy of set."""
        return self.codegen._generate_set_deep_copy(src, elem_type)

    def generate_map_deep_copy(self, src: ir.Value, key_type, value_type) -> ir.Value:
        """Generate deep copy of map."""
        return self.codegen._generate_map_deep_copy(src, key_type, value_type)

    def generate_array_deep_copy(self, src: ir.Value, elem_type) -> ir.Value:
        """Generate deep copy of array."""
        return self.codegen._generate_array_deep_copy(src, elem_type)

    def generate_type_deep_copy(self, src: ir.Value, coex_type) -> ir.Value:
        """Generate deep copy of user-defined type."""
        return self.codegen._generate_type_deep_copy(src, coex_type)
