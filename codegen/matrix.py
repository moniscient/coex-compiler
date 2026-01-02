"""
Matrix Module for Coex Code Generator

This module provides cellular automata (matrix) implementations for the Coex compiler.

Matrix Types:
- User-defined matrices with element types
- Double-buffered read/write for concurrent updates
- Neighbor access via cell[dx, dy] syntax

Matrix Structure:
    struct Matrix_Name {
        i64 width
        i64 height
        elem_type* read_buffer   # Current state (read from)
        elem_type* write_buffer  # Next state (write to)
    }

Operations:
- Matrix.new(width, height) -> Matrix  - Create new matrix
- matrix.step()                        - Execute one CA step
- matrix.get(x, y) -> elem             - Get cell value
- matrix.set(x, y, value) -> Matrix    - Set cell value (returns new)
- cell                                 - Current cell value (in formula)
- cell[dx, dy]                         - Neighbor cell value (in formula)
"""
from typing import TYPE_CHECKING
from llvmlite import ir

if TYPE_CHECKING:
    from codegen_original import CodeGenerator
    from ast_nodes import MatrixDecl, FunctionDecl


class MatrixGenerator:
    """Generates matrix/cellular automata code for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def module(self):
        return self.codegen.module

    @property
    def builder(self):
        return self.codegen.builder

    @property
    def gc(self):
        return self.codegen.gc

    @property
    def type_registry(self):
        return self.codegen.type_registry

    @property
    def type_methods(self):
        return self.codegen.type_methods

    @property
    def matrix_decls(self):
        return self.codegen.matrix_decls

    @property
    def matrix_structs(self):
        return self.codegen.matrix_structs

    @property
    def current_matrix(self):
        return self.codegen.current_matrix

    @property
    def locals(self):
        return self.codegen.locals

    # ========================================================================
    # Matrix Registration and Setup
    # ========================================================================

    def register_matrix(self, matrix_decl: 'MatrixDecl'):
        """Register a matrix declaration and create its runtime structure.

        Creates:
        - Matrix struct type with width, height, read/write buffers
        - Registers in type_registry for method dispatch
        """
        return self.codegen._register_matrix(matrix_decl)

    def create_matrix_constructor(self, name: str, matrix_decl: 'MatrixDecl',
                                   matrix_struct: ir.Type):
        """Create the Matrix.new(width, height) constructor function."""
        return self.codegen._create_matrix_constructor(name, matrix_decl, matrix_struct)

    def create_matrix_accessors(self, name: str, matrix_struct: ir.Type,
                                  elem_type: ir.Type):
        """Create matrix accessor methods (get, set, width, height)."""
        return self.codegen._create_matrix_accessors(name, matrix_struct, elem_type)

    # ========================================================================
    # Matrix Method Generation
    # ========================================================================

    def declare_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Declare matrix methods (formulas defined in the matrix block)."""
        return self.codegen._declare_matrix_methods(matrix_decl)

    def generate_matrix_methods(self, matrix_decl: 'MatrixDecl'):
        """Generate code for matrix methods."""
        return self.codegen._generate_matrix_methods(matrix_decl)

    def generate_matrix_formula(self, matrix_name: str, method: 'FunctionDecl',
                                 matrix_struct: ir.Type, elem_type: ir.Type):
        """Generate a matrix formula (the CA update rule).

        Matrix formulas have access to:
        - cell: current cell value
        - cell[dx, dy]: neighbor cell values
        - return: writes to write buffer
        """
        return self.codegen._generate_matrix_formula(
            matrix_name, method, matrix_struct, elem_type)

    # ========================================================================
    # Cell Access (used in matrix formulas)
    # ========================================================================

    def generate_cell_access(self) -> ir.Value:
        """Generate code for 'cell' expression - current cell value."""
        return self.codegen._generate_cell_access()

    def generate_cell_index_access(self, expr) -> ir.Value:
        """Generate code for 'cell[dx, dy]' expression - neighbor access."""
        return self.codegen._generate_cell_index_access(expr)

    def generate_matrix_return(self, value: ir.Value):
        """Handle return statement inside matrix formula - writes to write buffer."""
        return self.codegen._generate_matrix_return(value)
