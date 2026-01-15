"""
Enum code generation for the Coex compiler.

This module handles:
- Enum type registration (tagged unions)
- Enum variant lookup
- Enum constructor code generation
"""

from llvmlite import ir
from typing import Dict, Optional, Tuple, List as PyList

from ast_nodes import TypeDecl, Expr, PrimitiveType


class EnumGenerator:
    """Generates LLVM IR for enum types and constructors."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to the main CodeGenerator."""
        self.cg = cg

    def register_enum_type(self, type_decl: TypeDecl):
        """Register an enum type as a tagged union.

        Creates an LLVM struct with:
        - i64 tag field (discriminant)
        - Payload fields (enough i64 slots for largest variant)

        Stores variant info in cg.enum_variants for later use.
        """
        cg = self.cg
        name = f"struct.{type_decl.name}"
        struct_type = ir.global_context.get_identified_type(name)

        # Build variant info: {variant_name: (tag, [(field_name, field_type)])}
        variant_info = {}
        max_payload_size = 0

        for tag, variant in enumerate(type_decl.variants):
            fields = []
            payload_size = 0
            for field in variant.fields:
                fields.append((field.name, field.type_annotation))
                # Estimate 8 bytes per field
                payload_size += 8
            variant_info[variant.name] = (tag, fields)
            max_payload_size = max(max_payload_size, payload_size)

        # Create struct: { i64 tag, i64 f0, i64 f1, ... } for max fields
        max_fields = max(len(v.fields) for v in type_decl.variants) if type_decl.variants else 0

        # Build struct with tag + enough i64 fields for largest variant
        field_types = [ir.IntType(64)]  # tag
        for i in range(max_fields):
            field_types.append(ir.IntType(64))  # payload slots (all i64 for simplicity)

        struct_type.set_body(*field_types)

        # Store info in CodeGenerator's registries
        cg.type_registry[type_decl.name] = struct_type
        cg.type_fields[type_decl.name] = [("_tag", PrimitiveType("int"))]
        cg.type_methods[type_decl.name] = {}

        # Store variant info
        cg.enum_variants[type_decl.name] = variant_info

        # Register enum type with GC for heap tracking
        if cg.gc is not None:
            # Calculate size: (1 + max_fields) * 8 bytes
            size = (1 + max_fields) * 8
            # Compute reference field offsets across all variants
            ref_offsets = set()
            for variant_name, (tag, fields) in variant_info.items():
                for i, (_, field_type) in enumerate(fields):
                    if cg._is_reference_type(field_type):
                        # Offset is (1 + field_index) * 8 (tag is at offset 0)
                        ref_offsets.add((1 + i) * 8)
            cg.gc.register_type(type_decl.name, size, list(ref_offsets))

    def find_enum_variant(self, variant_name: str) -> Optional[Tuple[str, str]]:
        """Find which enum a variant belongs to.

        Args:
            variant_name: The name of the variant to find

        Returns:
            (enum_name, variant_name) tuple if found, None otherwise
        """
        cg = self.cg

        for enum_name, variants in cg.enum_variants.items():
            if variant_name in variants:
                return (enum_name, variant_name)
        return None

    def generate_enum_constructor(self, enum_name: str, variant_name: str,
                                   args: PyList[Expr], named_args: Dict[str, Expr]) -> ir.Value:
        """Generate code for enum variant constructor.

        Example: Circle(radius: 5.0)

        Args:
            enum_name: Name of the enum type
            variant_name: Name of the variant being constructed
            args: Positional arguments
            named_args: Named arguments

        Returns:
            Pointer to the allocated enum struct
        """
        cg = self.cg
        builder = cg.builder

        struct_type = cg.type_registry[enum_name]
        variant_info = cg.enum_variants[enum_name][variant_name]
        tag, fields = variant_info

        # Allocate enum struct via GC
        # Count: 1 (tag) + max_fields
        max_fields = max(len(v[1]) for v in cg.enum_variants[enum_name].values())
        size = (1 + max_fields) * 8
        size_val = ir.Constant(ir.IntType(64), size)

        type_id = ir.Constant(ir.IntType(32), cg.gc.get_type_id(enum_name))
        raw_ptr = cg.gc.alloc_arena_or_gc(builder, size_val, type_id)
        ptr = builder.bitcast(raw_ptr, struct_type.as_pointer())

        # Store tag
        tag_ptr = builder.gep(ptr, [
            ir.Constant(ir.IntType(32), 0),
            ir.Constant(ir.IntType(32), 0)
        ], inbounds=True)
        builder.store(ir.Constant(ir.IntType(64), tag), tag_ptr)

        # Process arguments - build field values dict
        field_values = {}
        for name, value_expr in named_args.items():
            field_values[name] = cg._generate_expression(value_expr)

        # Handle positional arguments
        for i, arg in enumerate(args):
            if i < len(fields):
                field_name = fields[i][0]
                if field_name not in field_values:
                    field_values[field_name] = cg._generate_expression(arg)

        # Store payload fields (starting at index 1, after tag)
        for i, (field_name, field_type) in enumerate(fields):
            field_ptr = builder.gep(ptr, [
                ir.Constant(ir.IntType(32), 0),
                ir.Constant(ir.IntType(32), i + 1)  # +1 for tag
            ], inbounds=True)

            if field_name in field_values:
                value = field_values[field_name]
                # Cast to i64 for storage
                if isinstance(value.type, ir.DoubleType):
                    # Store double as bits in i64
                    value = builder.bitcast(value, ir.IntType(64))
                elif value.type != ir.IntType(64):
                    value = cg._cast_value(value, ir.IntType(64))
                builder.store(value, field_ptr)
            else:
                builder.store(ir.Constant(ir.IntType(64), 0), field_ptr)

        return ptr
