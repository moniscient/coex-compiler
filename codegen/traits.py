"""
Trait Code Generation for Coex.

This module handles:
- Trait registration and storage
- Checking which traits a type implements
- Trait bound checking
- Method signature compatibility checking
- Primitive trait implementations
"""
from typing import TYPE_CHECKING, Dict

from ast_nodes import TypeDecl, FunctionDecl

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class TraitGenerator:
    """Handles trait-related operations for Coex code generation."""

    def __init__(self, cg: 'CodeGenerator'):
        self.cg = cg

    def register_trait(self, trait_decl: 'TraitDecl'):
        """Register a trait definition"""
        self.cg.traits[trait_decl.name] = trait_decl

    def check_trait_implementations(self, type_decl: TypeDecl):
        """Check which traits a type implements and record them"""
        implemented = []

        # Get the type's methods (name -> FunctionDecl)
        type_methods = {m.name: m for m in type_decl.methods}

        # Check each trait
        for trait_name, trait_decl in self.cg.traits.items():
            if self.type_implements_trait(type_decl, trait_decl, type_methods):
                implemented.append(trait_name)

        self.cg.type_implements[type_decl.name] = implemented

    def type_implements_trait(self, type_decl: TypeDecl, trait_decl: 'TraitDecl',
                              type_methods: Dict[str, FunctionDecl]) -> bool:
        """Check if a type implements all methods of a trait"""
        for trait_method in trait_decl.methods:
            if trait_method.name not in type_methods:
                return False

            type_method = type_methods[trait_method.name]

            # Check method signature compatibility
            if not self.methods_compatible(trait_method, type_method):
                return False

        return True

    def methods_compatible(self, trait_method: FunctionDecl, type_method: FunctionDecl) -> bool:
        """Check if a type's method is compatible with a trait method signature"""
        # Check parameter count
        if len(trait_method.params) != len(type_method.params):
            return False

        # Check return type compatibility (simplified - could be more precise)
        # For now, just check they both have return types or both don't
        trait_has_return = trait_method.return_type is not None
        type_has_return = type_method.return_type is not None
        if trait_has_return != type_has_return:
            return False

        return True

    def check_trait_bound(self, type_name: str, trait_name: str) -> bool:
        """Check if a type satisfies a trait bound"""
        # Handle monomorphized type names (e.g., "Pair_int_float")
        base_type = type_name.split('_')[0] if '_' in type_name else type_name

        # Check if type explicitly implements the trait
        if type_name in self.cg.type_implements:
            if trait_name in self.cg.type_implements[type_name]:
                return True

        # Check base type for generics
        if base_type in self.cg.type_implements:
            if trait_name in self.cg.type_implements[base_type]:
                return True

        # Check primitive types for built-in traits
        if self.primitive_implements_trait(type_name, trait_name):
            return True

        return False

    def primitive_implements_trait(self, type_name: str, trait_name: str) -> bool:
        """Check if a primitive type implements a built-in trait"""
        # Define which primitives implement which traits
        primitive_traits = {
            "int": ["Numeric", "Comparable", "Eq", "Hash", "Display"],
            "float": ["Numeric", "Comparable", "Display"],
            "bool": ["Eq", "Hash", "Display"],
            "string": ["Eq", "Hash", "Display", "Comparable"],
            "byte": ["Numeric", "Comparable", "Eq", "Hash"],
        }

        if type_name in primitive_traits:
            return trait_name in primitive_traits[type_name]

        return False
