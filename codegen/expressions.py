"""
Expressions Module for Coex Code Generator

This module provides expression code generation for the Coex compiler.

Expression types handled:
- Literals: int, float, bool, string, nil
- Identifiers: variable references
- Binary: arithmetic, comparison, logical operators
- Unary: negation, not
- Calls: function calls, method calls
- Member access: field access, tuple element access
- Index/Slice: collection indexing and slicing
- Collections: list, map, set, tuple construction
- Comprehensions: list, set, map comprehensions
- Special: ternary, lambda, range, as-cast, cell access
"""
from typing import TYPE_CHECKING, Dict
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator
    from ast_nodes import (
        Expr, Identifier, BinaryExpr, UnaryExpr, CallExpr, MethodCallExpr,
        MemberExpr, IndexExpr, SliceExpr, TernaryExpr, ListExpr, MapExpr,
        SetExpr, JsonObjectExpr, ListComprehension, SetComprehension,
        MapComprehension, TupleExpr, RangeExpr, LambdaExpr, AsExpr,
        CellIndexExpr
    )


class ExpressionsGenerator:
    """Generates code for Coex expressions."""

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
    def type_methods(self):
        return self.codegen.type_methods

    @property
    def enum_variants(self):
        return self.codegen.enum_variants

    # ========================================================================
    # Main Expression Dispatcher
    # ========================================================================

    def generate_expression(self, expr: 'Expr') -> ir.Value:
        """Generate code for an expression.

        Dispatches to specific handlers based on expression type.
        """
        return self.codegen._generate_expression(expr)

    # ========================================================================
    # Literal and Identifier Expressions
    # ========================================================================

    def generate_identifier(self, expr: 'Identifier') -> ir.Value:
        """Generate code for identifier reference."""
        return self.codegen._generate_identifier(expr)

    # ========================================================================
    # Operator Expressions
    # ========================================================================

    def generate_binary(self, expr: 'BinaryExpr') -> ir.Value:
        """Generate code for binary expression."""
        return self.codegen._generate_binary(expr)

    def generate_short_circuit_and(self, expr: 'BinaryExpr') -> ir.Value:
        """Generate short-circuit AND evaluation."""
        return self.codegen._generate_short_circuit_and(expr)

    def generate_short_circuit_or(self, expr: 'BinaryExpr') -> ir.Value:
        """Generate short-circuit OR evaluation."""
        return self.codegen._generate_short_circuit_or(expr)

    def generate_unary(self, expr: 'UnaryExpr') -> ir.Value:
        """Generate code for unary expression."""
        return self.codegen._generate_unary(expr)

    def generate_ternary(self, expr: 'TernaryExpr') -> ir.Value:
        """Generate code for ternary conditional expression."""
        return self.codegen._generate_ternary(expr)

    # ========================================================================
    # Call Expressions
    # ========================================================================

    def generate_call(self, expr: 'CallExpr') -> ir.Value:
        """Generate code for function call."""
        return self.codegen._generate_call(expr)

    def generate_method_call(self, expr: 'MethodCallExpr') -> ir.Value:
        """Generate code for method call."""
        return self.codegen._generate_method_call(expr)

    def generate_array_constructor(self, args: list) -> ir.Value:
        """Generate code for Array type constructor."""
        return self.codegen._generate_array_constructor(args)

    def generate_type_constructor(self, type_name: str, args: list,
                                   named_args: Dict[str, 'Expr']) -> ir.Value:
        """Generate code for user-defined type constructor."""
        return self.codegen._generate_type_constructor(type_name, args, named_args)

    def generate_type_new(self, type_name: str, args: list) -> ir.Value:
        """Generate code for Type.new() static constructor."""
        return self.codegen._generate_type_new(type_name, args)

    def generate_enum_constructor(self, enum_name: str, variant_name: str,
                                   args: list) -> ir.Value:
        """Generate code for enum variant constructor."""
        return self.codegen._generate_enum_constructor(enum_name, variant_name, args)

    # ========================================================================
    # Access Expressions
    # ========================================================================

    def generate_member(self, expr: 'MemberExpr') -> ir.Value:
        """Generate code for member/field access."""
        return self.codegen._generate_member(expr)

    def generate_index(self, expr: 'IndexExpr') -> ir.Value:
        """Generate code for index access."""
        return self.codegen._generate_index(expr)

    def generate_slice(self, expr: 'SliceExpr') -> ir.Value:
        """Generate code for slice expression."""
        return self.codegen._generate_slice(expr)

    # ========================================================================
    # Collection Expressions
    # ========================================================================

    def generate_list(self, expr: 'ListExpr') -> ir.Value:
        """Generate code for list literal."""
        return self.codegen._generate_list(expr)

    def generate_map(self, expr: 'MapExpr') -> ir.Value:
        """Generate code for map literal."""
        return self.codegen._generate_map(expr)

    def generate_set(self, expr: 'SetExpr') -> ir.Value:
        """Generate code for set literal."""
        return self.codegen._generate_set(expr)

    def generate_json_object(self, expr: 'JsonObjectExpr') -> ir.Value:
        """Generate code for JSON object literal."""
        return self.codegen._generate_json_object(expr)

    def generate_tuple(self, expr: 'TupleExpr') -> ir.Value:
        """Generate code for tuple expression."""
        return self.codegen._generate_tuple(expr)

    # ========================================================================
    # Comprehension Expressions
    # ========================================================================

    def generate_list_comprehension(self, expr: 'ListComprehension') -> ir.Value:
        """Generate code for list comprehension."""
        return self.codegen._generate_list_comprehension(expr)

    def generate_set_comprehension(self, expr: 'SetComprehension') -> ir.Value:
        """Generate code for set comprehension."""
        return self.codegen._generate_set_comprehension(expr)

    def generate_map_comprehension(self, expr: 'MapComprehension') -> ir.Value:
        """Generate code for map comprehension."""
        return self.codegen._generate_map_comprehension(expr)

    def generate_comprehension_loop(self, clauses, clause_idx, body,
                                     result_alloca, comp_type):
        """Generate loop structure for comprehension."""
        return self.codegen._generate_comprehension_loop(
            clauses, clause_idx, body, result_alloca, comp_type)

    def generate_comprehension_range_loop(self, clause, clause_idx, clauses,
                                           body, result_alloca, comp_type):
        """Generate range-based loop for comprehension."""
        return self.codegen._generate_comprehension_range_loop(
            clause, clause_idx, clauses, body, result_alloca, comp_type)

    def generate_comprehension_range_expr_loop(self, clause, clause_idx, clauses,
                                                body, result_alloca, comp_type):
        """Generate range expression loop for comprehension."""
        return self.codegen._generate_comprehension_range_expr_loop(
            clause, clause_idx, clauses, body, result_alloca, comp_type)

    def generate_comprehension_body(self, body, result_alloca, comp_type):
        """Generate body of comprehension."""
        return self.codegen._generate_comprehension_body(
            body, result_alloca, comp_type)

    # ========================================================================
    # Type Conversion Expressions
    # ========================================================================

    def generate_as_expr(self, expr: 'AsExpr') -> ir.Value:
        """Generate code for 'as' type cast expression."""
        return self.codegen._generate_as_expr(expr)

    def generate_non_json_as_expr(self, source: ir.Value,
                                   expr: 'AsExpr') -> ir.Value:
        """Generate non-JSON type conversion."""
        return self.codegen._generate_non_json_as_expr(source, expr)

    def generate_json_to_primitive(self, json_ptr: ir.Value, tag: ir.Value,
                                    value: ir.Value, target_type, builder):
        """Generate JSON to primitive type conversion."""
        return self.codegen._generate_json_to_primitive(
            json_ptr, tag, value, target_type, builder)

    def generate_json_to_struct(self, json_ptr: ir.Value, tag: ir.Value,
                                 value: ir.Value, target_type, builder):
        """Generate JSON to struct type conversion."""
        return self.codegen._generate_json_to_struct(
            json_ptr, tag, value, target_type, builder)

    def generate_json_to_enum(self, json_ptr: ir.Value, tag: ir.Value,
                               value: ir.Value, target_type, builder):
        """Generate JSON to enum type conversion."""
        return self.codegen._generate_json_to_enum(
            json_ptr, tag, value, target_type, builder)

    def generate_json_to_list(self, json_ptr: ir.Value, tag: ir.Value,
                               value: ir.Value, target_type, builder):
        """Generate JSON to list type conversion."""
        return self.codegen._generate_json_to_list(
            json_ptr, tag, value, target_type, builder)

    # ========================================================================
    # Special Expressions
    # ========================================================================

    def generate_range(self, expr: 'RangeExpr') -> ir.Value:
        """Generate code for range expression."""
        return self.codegen._generate_range(expr)

    def generate_lambda(self, expr: 'LambdaExpr') -> ir.Value:
        """Generate code for lambda expression."""
        return self.codegen._generate_lambda(expr)

    def generate_cell_access(self) -> ir.Value:
        """Generate code for matrix cell access."""
        return self.codegen._generate_cell_access()

    def generate_cell_index_access(self, expr: 'CellIndexExpr') -> ir.Value:
        """Generate code for matrix cell[dx, dy] access."""
        return self.codegen._generate_cell_index_access(expr)

    def generate_llvm_ir_block(self, block) -> ir.Value:
        """Generate code from inline LLVM IR block."""
        return self.codegen._generate_llvm_ir_block(block)
