"""
Generics and Monomorphization for Coex.

This module handles:
- Generic type and function name mangling
- Type monomorphization (creating concrete types from generic templates)
- Type parameter substitution
- Type argument inference from expressions and constructors
- Type unification for generic parameter binding
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict
from typing import List as PyList

from ast_nodes import (
    Type, TypeDecl, TypeParam, FunctionDecl, FunctionKind, Expr,
    PrimitiveType, NamedType, ListType, OptionalType, ResultType,
    TupleType, FunctionType, MapType, SetType, ArrayType, ChannelType,
    IntLiteral, FloatLiteral, BoolLiteral, StringLiteral, Identifier,
    ListExpr, MapExpr, SetExpr, JsonObjectExpr, CallExpr, MemberExpr, IndexExpr,
    MethodCallExpr, BinaryExpr, BinaryOp, UnaryExpr, UnaryOp, TernaryExpr,
    SelfExpr, ListComprehension, SetComprehension, MapComprehension
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class GenericsHandler:
    """Handles generic type and function monomorphization for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Name Mangling
    # ========================================================================

    def mangle_generic_name(self, base_name: str, type_args: PyList[Type]) -> str:
        """Create mangled name for monomorphized generic: Pair_int_float"""
        parts = [base_name]
        for arg in type_args:
            parts.append(self.type_to_string(arg))
        return "_".join(parts)

    def type_to_string(self, coex_type: Type) -> str:
        """Convert type to string for name mangling"""
        if isinstance(coex_type, PrimitiveType):
            return coex_type.name
        elif isinstance(coex_type, NamedType):
            if coex_type.type_args:
                args = "_".join(self.type_to_string(a) for a in coex_type.type_args)
                return f"{coex_type.name}_{args}"
            return coex_type.name
        elif isinstance(coex_type, ListType):
            return f"List_{self.type_to_string(coex_type.element_type)}"
        elif isinstance(coex_type, OptionalType):
            return f"Opt_{self.type_to_string(coex_type.inner)}"
        elif isinstance(coex_type, ResultType):
            ok_str = self.type_to_string(coex_type.ok_type)
            err_str = self.type_to_string(coex_type.err_type)
            return f"Result_{ok_str}_{err_str}"
        else:
            return "unknown"

    # ========================================================================
    # Type Substitution
    # ========================================================================

    def substitute_type(self, coex_type: Type) -> Type:
        """Substitute type parameters with concrete types"""
        cg = self.cg
        if not cg.type_substitutions:
            return coex_type

        if isinstance(coex_type, NamedType):
            # Check if this is a type parameter
            if coex_type.name in cg.type_substitutions:
                return cg.type_substitutions[coex_type.name]
            # Check if it has type args that need substitution
            if coex_type.type_args:
                new_args = [self.substitute_type(arg) for arg in coex_type.type_args]
                return NamedType(coex_type.name, new_args)
        elif isinstance(coex_type, ListType):
            return ListType(self.substitute_type(coex_type.element_type))
        elif isinstance(coex_type, OptionalType):
            return OptionalType(self.substitute_type(coex_type.inner))
        elif isinstance(coex_type, ResultType):
            return ResultType(
                self.substitute_type(coex_type.ok_type),
                self.substitute_type(coex_type.err_type)
            )
        elif isinstance(coex_type, TupleType):
            new_elements = [(name, self.substitute_type(t)) for name, t in coex_type.elements]
            return TupleType(new_elements)
        elif isinstance(coex_type, FunctionType):
            new_params = [self.substitute_type(t) for t in coex_type.param_types]
            new_ret = self.substitute_type(coex_type.return_type) if coex_type.return_type else None
            return FunctionType(coex_type.kind, new_params, new_ret)

        return coex_type

    # ========================================================================
    # Type Monomorphization
    # ========================================================================

    def monomorphize_type(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic type with concrete type arguments"""
        cg = self.cg
        if name not in cg.generic_types:
            return name  # Not a generic type

        mangled_name = self.mangle_generic_name(name, type_args)

        # Already monomorphized?
        if mangled_name in cg.type_registry:
            return mangled_name

        # Get the generic type declaration
        type_decl = cg.generic_types[name]

        # Check trait bounds
        for param, arg in zip(type_decl.type_params, type_args):
            for bound in param.bounds:
                type_name = self.type_to_string(arg)
                if not cg._check_trait_bound(type_name, bound):
                    # Trait bound not satisfied - for now, continue anyway
                    pass

        # Set up type substitutions
        old_subs = cg.type_substitutions.copy()
        cg.type_substitutions = {}
        for param, arg in zip(type_decl.type_params, type_args):
            cg.type_substitutions[param.name] = arg

        # Register the concrete type
        cg._register_concrete_type(mangled_name, type_decl)

        # Store AST reference with mangled name
        cg.type_decls[mangled_name] = type_decl

        # Check trait implementations for the monomorphized type
        self.check_monomorphized_trait_implementations(mangled_name, type_decl)

        # Monomorphize and declare methods
        cg._declare_type_methods_monomorphized(mangled_name, type_decl)

        # Restore substitutions
        cg.type_substitutions = old_subs

        return mangled_name

    def check_monomorphized_trait_implementations(self, mangled_name: str, type_decl: TypeDecl):
        """Check which traits a monomorphized type implements"""
        cg = self.cg
        implemented = []

        # Get the type's methods (name -> FunctionDecl)
        type_methods = {m.name: m for m in type_decl.methods}

        # Check each trait
        for trait_name, trait_decl in cg.traits.items():
            if cg._type_implements_trait(type_decl, trait_decl, type_methods):
                implemented.append(trait_name)

        cg.type_implements[mangled_name] = implemented

    # ========================================================================
    # Type Argument Inference
    # ========================================================================

    def infer_type_args(self, func_name: str, args: PyList[Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic function from call arguments"""
        cg = self.cg
        if func_name not in cg.generic_functions:
            return None

        func_decl = cg.generic_functions[func_name]
        type_params = func_decl.type_params

        # Map type parameter names to inferred types
        inferred = {}
        param_names = {tp.name for tp in type_params}

        for i, (param, arg) in enumerate(zip(func_decl.params, args)):
            param_type = param.type_annotation
            inferred_type = self.infer_type_from_expr(arg)

            # Match parameter type against inferred type
            self.unify_types_with_params(param_type, inferred_type, inferred, param_names)

        # Build result in order of type parameters
        result = []
        for tp in type_params:
            if tp.name in inferred:
                result.append(inferred[tp.name])
            else:
                # Default to int if can't infer
                result.append(PrimitiveType("int"))

        return result

    def infer_type_args_from_constructor(self, type_name: str, args: PyList[Expr],
                                         named_args: Dict[str, Expr]) -> Optional[PyList[Type]]:
        """Infer type arguments for a generic type constructor"""
        cg = self.cg
        if type_name not in cg.generic_types:
            return None

        type_decl = cg.generic_types[type_name]
        type_params = type_decl.type_params

        # Build a mapping from type parameter names to their inferred types
        inferred = {}

        # Map field names to their declared types
        field_types = {f.name: f.type_annotation for f in type_decl.fields}

        # Infer from named arguments
        for field_name, arg_expr in named_args.items():
            if field_name in field_types:
                declared_type = field_types[field_name]
                inferred_type = self.infer_type_from_expr(arg_expr)
                self.unify_type_constructor(declared_type, inferred_type, inferred, type_params)

        # Infer from positional arguments
        for i, arg_expr in enumerate(args):
            if i < len(type_decl.fields):
                declared_type = type_decl.fields[i].type_annotation
                inferred_type = self.infer_type_from_expr(arg_expr)
                self.unify_type_constructor(declared_type, inferred_type, inferred, type_params)

        # Build result in order of type parameters
        result = []
        for tp in type_params:
            if tp.name in inferred:
                result.append(inferred[tp.name])
            else:
                # Default to int if can't infer
                result.append(PrimitiveType("int"))

        return result

    def unify_type_constructor(self, declared_type: Type, inferred_type: Type,
                               inferred: Dict[str, Type], type_params: PyList[TypeParam]):
        """Unify a declared field type with an inferred argument type"""
        param_names = {tp.name for tp in type_params}

        if isinstance(declared_type, NamedType):
            if declared_type.name in param_names:
                # This field has a type parameter type - infer it
                if declared_type.name not in inferred:
                    inferred[declared_type.name] = inferred_type
        elif isinstance(declared_type, ListType):
            if isinstance(inferred_type, ListType):
                self.unify_type_constructor(declared_type.element_type,
                                            inferred_type.element_type, inferred, type_params)

    # ========================================================================
    # Type Inference from Expressions
    # ========================================================================

    def infer_type_from_expr(self, expr: Expr) -> Type:
        """Infer the Coex type of an expression"""
        cg = self.cg
        if isinstance(expr, IntLiteral):
            return PrimitiveType("int")
        elif isinstance(expr, FloatLiteral):
            return PrimitiveType("float")
        elif isinstance(expr, BoolLiteral):
            return PrimitiveType("bool")
        elif isinstance(expr, StringLiteral):
            return PrimitiveType("string")
        elif isinstance(expr, SelfExpr):
            # Self in UDT method context — return the current type
            if hasattr(cg, 'current_type') and cg.current_type:
                return NamedType(cg.current_type)
            return PrimitiveType("int")
        elif isinstance(expr, Identifier):
            # Look up variable type
            name = expr.name
            # First check var_coex_types which tracks Coex types directly
            if hasattr(cg, 'var_coex_types') and name in cg.var_coex_types:
                return cg.var_coex_types[name]
            # Check if this is a function name (for function-as-value references)
            if name in cg.func_decls:
                func_decl = cg.func_decls[name]
                param_types = [p.type_annotation for p in func_decl.params] if func_decl.params else []
                kind = getattr(func_decl, 'kind', FunctionKind.FUNC)
                return FunctionType(kind, param_types, func_decl.return_type)
            # Fall back to LLVM type lookup
            if name in cg.locals:
                llvm_type = cg._get_var_original_type(name)
                return self.llvm_type_to_coex(llvm_type)
        elif isinstance(expr, ListExpr):
            if expr.elements:
                elem_type = self.infer_type_from_expr(expr.elements[0])
                return ListType(elem_type)
            return ListType(PrimitiveType("int"))
        elif isinstance(expr, MapExpr):
            if expr.entries:
                key_type = self.infer_type_from_expr(expr.entries[0][0])
                value_type = self.infer_type_from_expr(expr.entries[0][1])
                return MapType(key_type, value_type)
            return MapType(PrimitiveType("int"), PrimitiveType("int"))
        elif isinstance(expr, JsonObjectExpr):
            return PrimitiveType("json")
        elif isinstance(expr, SetExpr):
            if expr.elements:
                elem_type = self.infer_type_from_expr(expr.elements[0])
                return SetType(elem_type)
            return SetType(PrimitiveType("int"))
        elif isinstance(expr, ListComprehension):
            elem_type = self.infer_type_from_expr(expr.value)
            return ListType(elem_type)
        elif isinstance(expr, SetComprehension):
            elem_type = self.infer_type_from_expr(expr.value)
            return SetType(elem_type)
        elif isinstance(expr, MapComprehension):
            key_type = self.infer_type_from_expr(expr.key)
            val_type = self.infer_type_from_expr(expr.value)
            return MapType(key_type, val_type)
        elif isinstance(expr, CallExpr):
            # Check for method calls via MemberExpr callee (e.g., j.get(), json.parse())
            if isinstance(expr.callee, MemberExpr):
                # Check for method calls on json variables (e.g., j.get())
                if isinstance(expr.callee.object, Identifier):
                    obj_name = expr.callee.object.name
                    # Check if this is a method call on a json variable
                    if hasattr(cg, 'var_coex_types') and obj_name in cg.var_coex_types:
                        obj_type = cg.var_coex_types[obj_name]
                        if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                            # JSON method calls
                            method = expr.callee.member
                            if method in ("get", "set", "remove", "append"):
                                return PrimitiveType("json")
                            elif method in ("stringify", "pretty"):
                                return PrimitiveType("string")
                            elif method in ("as_int", "len"):
                                return PrimitiveType("int")
                            elif method == "as_float":
                                return PrimitiveType("float")
                            elif method in ("as_bool", "is_null", "is_bool", "is_int", "is_float",
                                            "is_string", "is_array", "is_object", "has"):
                                return PrimitiveType("bool")
                            elif method == "as_string":
                                return PrimitiveType("string")
                            elif method == "keys":
                                return ListType(PrimitiveType("string"))
                            elif method == "values":
                                return ListType(PrimitiveType("json"))
                        # Result method return types
                        if isinstance(obj_type, ResultType):
                            method = expr.callee.member
                            if method in ("unwrap", "unwrap_or"):
                                return obj_type.ok_type
                            elif method in ("is_ok", "is_err"):
                                return PrimitiveType("bool")
                        # Collection conversion method return types
                        if isinstance(obj_type, (ListType, SetType)):
                            method = expr.callee.member
                            if method in ("toArray", "packed"):
                                return ArrayType(obj_type.element_type)
                        if isinstance(obj_type, (ArrayType, SetType)):
                            method = expr.callee.member
                            if method in ("toList", "unpacked"):
                                return ListType(obj_type.element_type)
                        if isinstance(obj_type, (ListType, ArrayType)):
                            method = expr.callee.member
                            if method == "toSet":
                                return SetType(obj_type.element_type)
                        # List methods
                        if isinstance(obj_type, ListType):
                            method = expr.callee.member
                            if method in ("append", "set", "setrange", "getrange", "copy"):
                                return obj_type
                            elif method == "get":
                                return obj_type.element_type
                            elif method in ("len", "size"):
                                return PrimitiveType("int")
                        # Array methods
                        if isinstance(obj_type, ArrayType):
                            method = expr.callee.member
                            if method in ("append", "set", "deep_copy", "scale", "add", "sub", "mul", "div", "getrange"):
                                return obj_type
                            elif method == "get":
                                return obj_type.element_type
                            elif method in ("len", "total_size"):
                                return PrimitiveType("int")
                            elif method in ("sum", "min", "max"):
                                return obj_type.element_type
                        # Map methods
                        if isinstance(obj_type, MapType):
                            method = expr.callee.member
                            if method in ("set", "remove"):
                                return obj_type
                            elif method == "get":
                                return obj_type.value_type
                            elif method == "has":
                                return PrimitiveType("bool")
                            elif method == "len":
                                return PrimitiveType("int")
                            elif method == "keys":
                                return ListType(obj_type.key_type)
                            elif method == "values":
                                return ListType(obj_type.value_type)
                        # Set methods
                        if isinstance(obj_type, SetType):
                            method = expr.callee.member
                            if method in ("add", "remove"):
                                return obj_type
                            elif method == "has":
                                return PrimitiveType("bool")
                            elif method == "len":
                                return PrimitiveType("int")
                        # String methods
                        if isinstance(obj_type, PrimitiveType) and obj_type.name == "string":
                            method = expr.callee.member
                            if method in ("upper", "lower", "trim", "replace", "getrange",
                                          "repeat", "reverse", "substr", "concat", "split_at"):
                                return PrimitiveType("string")
                            elif method in ("len", "index_of", "find"):
                                return PrimitiveType("int")
                            elif method in ("bytes", "cstring"):
                                return ListType(PrimitiveType("byte"))
                            elif method in ("contains", "starts_with", "ends_with", "eq"):
                                return PrimitiveType("bool")
                            elif method == "split":
                                return ListType(PrimitiveType("string"))
                        # Channel methods
                        if isinstance(obj_type, ChannelType):
                            method = expr.callee.member
                            if method == "receive":
                                return obj_type.element_type
                            elif method in ("send", "try_receive"):
                                return PrimitiveType("int")
                        # UDT methods
                        if isinstance(obj_type, NamedType):
                            type_name = obj_type.name
                            if type_name in cg.type_methods and expr.callee.member in cg.type_methods[type_name]:
                                mangled = cg.type_methods[type_name][expr.callee.member]
                                if mangled in cg.func_decls:
                                    ret_type = cg.func_decls[mangled].return_type
                                    if ret_type:
                                        return ret_type
                    # Check for static type method calls (e.g., String.from(), Array.zeros())
                    if obj_name == "String":
                        # String.from(), String.from_bytes(), String.from_hex() all return string
                        if expr.callee.member in ("from", "from_bytes", "from_hex"):
                            return PrimitiveType("string")
                    elif obj_name == "json" and expr.callee.member == "parse":
                        return PrimitiveType("json")
                    elif obj_name == "Array":
                        if expr.callee.member in ("zeros", "fill", "filled", "identity", "zeros_2d"):
                            return ArrayType(PrimitiveType("int"))
                    elif obj_name == "Result":
                        if expr.callee.member == "ok":
                            return ResultType(PrimitiveType("int"), PrimitiveType("string"))
                        elif expr.callee.member == "err":
                            return ResultType(PrimitiveType("int"), PrimitiveType("string"))
                    elif obj_name in cg.type_registry:
                        # Check type_methods for registered types
                        if obj_name in cg.type_methods and expr.callee.member in cg.type_methods[obj_name]:
                            mangled = cg.type_methods[obj_name][expr.callee.member]
                            if mangled in cg.func_decls:
                                ret_type = cg.func_decls[mangled].return_type
                                if ret_type:
                                    return ret_type
                else:
                    # Non-Identifier object (e.g., chained calls: j.get("name").as_string())
                    # Recursively infer the object's type and dispatch on method name
                    obj_type = self.infer_type_from_expr(expr.callee.object)
                    method = expr.callee.member
                    if obj_type is not None:
                        if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                            if method in ("get", "set", "remove", "append"):
                                return PrimitiveType("json")
                            elif method in ("stringify", "as_string", "pretty"):
                                return PrimitiveType("string")
                            elif method in ("as_int", "len"):
                                return PrimitiveType("int")
                            elif method == "as_float":
                                return PrimitiveType("float")
                            elif method in ("as_bool", "is_null", "is_bool", "is_int", "is_float",
                                            "is_string", "is_array", "is_object", "has"):
                                return PrimitiveType("bool")
                            elif method == "keys":
                                return ListType(PrimitiveType("string"))
                            elif method == "values":
                                return ListType(PrimitiveType("json"))
                        elif isinstance(obj_type, PrimitiveType) and obj_type.name == "string":
                            if method in ("upper", "lower", "trim", "replace", "getrange",
                                          "repeat", "reverse", "substr", "concat", "split_at"):
                                return PrimitiveType("string")
                            elif method in ("len", "index_of", "find"):
                                return PrimitiveType("int")
                            elif method in ("bytes", "cstring"):
                                return ListType(PrimitiveType("byte"))
                            elif method in ("contains", "starts_with", "ends_with", "eq"):
                                return PrimitiveType("bool")
                            elif method == "split":
                                return ListType(PrimitiveType("string"))
                        elif isinstance(obj_type, ListType):
                            if method in ("append", "set", "setrange", "getrange", "copy"):
                                return obj_type
                            elif method == "get":
                                return obj_type.element_type
                            elif method in ("len", "size"):
                                return PrimitiveType("int")
                        elif isinstance(obj_type, ArrayType):
                            if method in ("append", "set", "deep_copy", "scale", "add", "sub", "mul", "div", "getrange"):
                                return obj_type
                            elif method == "get":
                                return obj_type.element_type
                            elif method in ("len", "total_size"):
                                return PrimitiveType("int")
                        elif isinstance(obj_type, MapType):
                            if method in ("set", "remove"):
                                return obj_type
                            elif method == "get":
                                return obj_type.value_type
                            elif method == "has":
                                return PrimitiveType("bool")
                            elif method == "len":
                                return PrimitiveType("int")
                        elif isinstance(obj_type, SetType):
                            if method in ("add", "remove"):
                                return obj_type
                            elif method == "has":
                                return PrimitiveType("bool")
                            elif method == "len":
                                return PrimitiveType("int")
                        elif isinstance(obj_type, ResultType):
                            if method in ("unwrap", "unwrap_or"):
                                return obj_type.ok_type
                            elif method in ("is_ok", "is_err"):
                                return PrimitiveType("bool")
                        elif isinstance(obj_type, ChannelType):
                            if method == "receive":
                                return obj_type.element_type
                            elif method in ("send", "try_receive"):
                                return PrimitiveType("int")
            # Check if this is a type constructor call (e.g., Point(10, 20))
            func_name = expr.callee.name if isinstance(expr.callee, Identifier) else None
            if func_name and func_name in cg.type_fields:
                # This is a user type constructor
                return NamedType(func_name)
            # BUG-066 FIX: Check if this is a regular function call and return its type
            if func_name and hasattr(cg, 'func_decls') and func_name in cg.func_decls:
                func_decl = cg.func_decls[func_name]
                if func_decl.return_type:
                    return func_decl.return_type
        elif isinstance(expr, MemberExpr):
            # Check if accessing a field on a JSON object
            obj_type = self.infer_type_from_expr(expr.object)
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                return PrimitiveType("json")
            # For UDTs, look up the field type
            if isinstance(obj_type, NamedType) and obj_type.name in cg.type_fields:
                for field_name, field_type in cg.type_fields[obj_type.name]:
                    if field_name == expr.member:
                        return field_type
        elif isinstance(expr, IndexExpr):
            # Check if indexing a JSON object
            obj_type = self.infer_type_from_expr(expr.object)
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                return PrimitiveType("json")
            # For lists, return element type
            if isinstance(obj_type, ListType):
                return obj_type.element_type
            # For arrays, return element type
            if isinstance(obj_type, ArrayType):
                return obj_type.element_type
            # For maps, return value type
            if isinstance(obj_type, MapType):
                return obj_type.value_type
        elif isinstance(expr, BinaryExpr):
            if expr.op in (BinaryOp.EQ, BinaryOp.NE, BinaryOp.LT, BinaryOp.GT,
                           BinaryOp.LE, BinaryOp.GE, BinaryOp.AND, BinaryOp.OR):
                return PrimitiveType("bool")
            if expr.op == BinaryOp.RANGE:
                return PrimitiveType("int")
            # For ADD, check if either operand is a string (string concatenation)
            left_type = self.infer_type_from_expr(expr.left)
            if expr.op == BinaryOp.ADD:
                if isinstance(left_type, PrimitiveType) and left_type.name == "string":
                    return PrimitiveType("string")
                right_type = self.infer_type_from_expr(expr.right)
                if isinstance(right_type, PrimitiveType) and right_type.name == "string":
                    return PrimitiveType("string")
            # For arithmetic ops, propagate float if either operand is float
            if isinstance(left_type, PrimitiveType) and left_type.name == "float":
                return PrimitiveType("float")
            right_type = self.infer_type_from_expr(expr.right)
            if isinstance(right_type, PrimitiveType) and right_type.name == "float":
                return PrimitiveType("float")
            return left_type
        elif isinstance(expr, UnaryExpr):
            if expr.op == UnaryOp.NOT:
                return PrimitiveType("bool")
            return self.infer_type_from_expr(expr.operand)
        elif isinstance(expr, TernaryExpr):
            return self.infer_type_from_expr(expr.then_expr)
        elif isinstance(expr, MethodCallExpr):
            # Check for static method calls: Type.method()
            if isinstance(expr.object, Identifier):
                type_name = expr.object.name
                if type_name == "String":
                    # String.from(), String.from_bytes(), String.from_hex() all return string
                    return PrimitiveType("string")
            # Check the receiver type and method name
            obj_type = self.infer_type_from_expr(expr.object)
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "json":
                # JSON methods that return JSON
                if expr.method in ("get", "set", "remove", "append"):
                    return PrimitiveType("json")
                # JSON methods that return primitives
                elif expr.method == "stringify":
                    return PrimitiveType("string")
                elif expr.method in ("as_int", "len"):
                    return PrimitiveType("int")
                elif expr.method == "as_float":
                    return PrimitiveType("float")
                elif expr.method in ("as_bool", "is_null", "is_bool", "is_int", "is_float",
                                      "is_string", "is_array", "is_object", "has"):
                    return PrimitiveType("bool")
                elif expr.method == "as_string":
                    return PrimitiveType("string")
                elif expr.method == "keys":
                    return ListType(PrimitiveType("string"))
                elif expr.method == "values":
                    return ListType(PrimitiveType("json"))
            # List methods
            if isinstance(obj_type, ListType):
                if expr.method in ("append", "set", "setrange", "getrange", "copy"):
                    return obj_type  # Returns same list type
                elif expr.method == "get":
                    return obj_type.element_type
                elif expr.method in ("len", "size"):
                    return PrimitiveType("int")
            # Array methods
            if isinstance(obj_type, ArrayType):
                if expr.method in ("append", "set", "deep_copy", "scale", "add", "sub", "mul", "div", "getrange"):
                    return obj_type
                elif expr.method == "get":
                    return obj_type.element_type
                elif expr.method in ("len", "total_size"):
                    return PrimitiveType("int")
                elif expr.method in ("sum", "min", "max"):
                    return obj_type.element_type
            # Map methods
            if isinstance(obj_type, MapType):
                if expr.method in ("set", "remove"):
                    return obj_type
                elif expr.method == "get":
                    return obj_type.value_type
                elif expr.method == "has":
                    return PrimitiveType("bool")
                elif expr.method == "len":
                    return PrimitiveType("int")
                elif expr.method == "keys":
                    return ListType(obj_type.key_type)
                elif expr.method == "values":
                    return ListType(obj_type.value_type)
            # Set methods
            if isinstance(obj_type, SetType):
                if expr.method in ("add", "remove"):
                    return obj_type
                elif expr.method == "has":
                    return PrimitiveType("bool")
                elif expr.method == "len":
                    return PrimitiveType("int")
            # String methods
            if isinstance(obj_type, PrimitiveType) and obj_type.name == "string":
                if expr.method in ("upper", "lower", "trim", "replace", "getrange",
                                    "repeat", "reverse", "substr", "concat", "split_at"):
                    return PrimitiveType("string")
                elif expr.method in ("len", "index_of", "find"):
                    return PrimitiveType("int")
                elif expr.method in ("bytes", "cstring"):
                    return ListType(PrimitiveType("byte"))
                elif expr.method in ("contains", "starts_with", "ends_with", "eq"):
                    return PrimitiveType("bool")
                elif expr.method == "split":
                    return ListType(PrimitiveType("string"))
            # Result methods
            if isinstance(obj_type, ResultType):
                if expr.method == "unwrap":
                    return obj_type.ok_type
                elif expr.method == "unwrap_or":
                    return obj_type.ok_type
                elif expr.method in ("is_ok", "is_err"):
                    return PrimitiveType("bool")
                elif expr.method == "unwrap_err":
                    return obj_type.err_type
            # Channel methods
            if isinstance(obj_type, ChannelType):
                if expr.method == "receive":
                    return obj_type.element_type
                elif expr.method in ("send", "try_receive"):
                    return PrimitiveType("int")
            # Check if this is a UDT method call
            if isinstance(obj_type, NamedType):
                type_name = obj_type.name
                if type_name in cg.type_methods and expr.method in cg.type_methods[type_name]:
                    mangled = cg.type_methods[type_name][expr.method]
                    if mangled in cg.func_decls:
                        ret_type = cg.func_decls[mangled].return_type
                        if ret_type:
                            return ret_type

        # Default
        return PrimitiveType("int")

    def llvm_type_to_coex(self, llvm_type: ir.Type) -> Type:
        """Convert LLVM type back to Coex type (approximate)"""
        if isinstance(llvm_type, ir.IntType):
            if llvm_type.width == 1:
                return PrimitiveType("bool")
            elif llvm_type.width == 8:
                return PrimitiveType("byte")
            else:
                return PrimitiveType("int")
        elif isinstance(llvm_type, ir.DoubleType):
            return PrimitiveType("float")
        elif isinstance(llvm_type, ir.PointerType):
            pointee = llvm_type.pointee
            if isinstance(pointee, ir.IntType) and pointee.width == 8:
                return PrimitiveType("string")
            # Check for struct types
            if hasattr(pointee, 'name'):
                if pointee.name.startswith("struct."):
                    type_name = pointee.name[7:]
                    # json is a primitive type, not a named type
                    if type_name == "Json":
                        return PrimitiveType("json")
                    return NamedType(type_name)
        return PrimitiveType("int")

    # ========================================================================
    # Type Unification
    # ========================================================================

    def unify_types_with_params(self, param_type: Type, arg_type: Type,
                                inferred: Dict[str, Type], param_names: set):
        """Unify a parameter type with an argument type to infer type parameters"""
        if isinstance(param_type, NamedType):
            # Check if it's a type parameter
            if param_type.name in param_names:
                # It's a type parameter - infer it
                if param_type.name not in inferred:
                    inferred[param_type.name] = arg_type
        elif isinstance(param_type, ListType):
            if isinstance(arg_type, ListType):
                self.unify_types_with_params(param_type.element_type, arg_type.element_type,
                                             inferred, param_names)
        elif isinstance(param_type, OptionalType):
            if isinstance(arg_type, OptionalType):
                self.unify_types_with_params(param_type.inner, arg_type.inner,
                                             inferred, param_names)
        elif isinstance(param_type, ResultType):
            if isinstance(arg_type, ResultType):
                self.unify_types_with_params(param_type.ok_type, arg_type.ok_type,
                                             inferred, param_names)
                self.unify_types_with_params(param_type.err_type, arg_type.err_type,
                                             inferred, param_names)

    def unify_types(self, param_type: Type, arg_type: Type, inferred: Dict[str, Type]):
        """Unify a parameter type with an argument type to infer type parameters (legacy)"""
        cg = self.cg
        # This version looks up params from current function - may not work correctly
        if isinstance(param_type, NamedType):
            # Check if it's a type parameter
            if param_type.name in [tp.name for tp in cg.generic_functions.get(
                    cg.current_function.name if cg.current_function else "",
                    FunctionDecl(FunctionKind.FUNC, "", [])).type_params]:
                # It's a type parameter - infer it
                if param_type.name not in inferred:
                    inferred[param_type.name] = arg_type
        elif isinstance(param_type, ListType):
            if isinstance(arg_type, ListType):
                self.unify_types(param_type.element_type, arg_type.element_type, inferred)
        elif isinstance(param_type, OptionalType):
            if isinstance(arg_type, OptionalType):
                self.unify_types(param_type.inner, arg_type.inner, inferred)
        elif isinstance(param_type, ResultType):
            if isinstance(arg_type, ResultType):
                self.unify_types(param_type.ok_type, arg_type.ok_type, inferred)
                self.unify_types(param_type.err_type, arg_type.err_type, inferred)
