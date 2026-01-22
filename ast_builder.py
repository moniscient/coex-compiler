"""
Coex AST Builder

Walks the ANTLR parse tree and constructs a complete AST.
"""

import sys
from typing import List as PyList, Dict, Tuple, Optional
from antlr4 import *
from CoexParser import CoexParser
from ast_nodes import *


class ASTBuilder:
    """Converts ANTLR parse tree to Coex AST"""

    def __init__(self):
        """Initialize AST builder with kind registry."""
        # Registry for user-defined kinds
        self.kind_registry: Dict[str, KindDecl] = {}
        # Track the original source for raw body capture
        self._token_stream = None
    """Converts ANTLR parse tree to Coex AST"""
    
    def build(self, tree: CoexParser.ProgramContext, token_stream=None) -> Program:
        """Build AST from parse tree root"""
        program = Program()
        self._token_stream = token_stream

        # First pass: collect all kind declarations (needed before parsing functions)
        for child in tree.children:
            if isinstance(child, CoexParser.DeclarationContext):
                decl_child = child.getChild(0)
                if hasattr(CoexParser, 'KindDeclContext') and isinstance(decl_child, CoexParser.KindDeclContext):
                    kind_decl = self.visit_kind_decl(decl_child)
                    program.kinds.append(kind_decl)
                    self.kind_registry[kind_decl.name] = kind_decl

        # Second pass: process all other declarations
        for child in tree.children:
            if isinstance(child, CoexParser.ImportDeclContext):
                imp = self.visit_import_decl(child)
                if imp:
                    program.imports.append(imp)
            elif isinstance(child, CoexParser.ReplaceDeclContext):
                rep = self.visit_replace_decl(child)
                if rep:
                    program.replaces.append(rep)
            elif hasattr(CoexParser, 'ReplaceKindDeclContext') and isinstance(child, CoexParser.ReplaceKindDeclContext):
                rep_kind = self.visit_replace_kind_decl(child)
                if rep_kind:
                    program.kind_replaces.append(rep_kind)
            elif isinstance(child, CoexParser.DirectiveDeclContext):
                directive = self.visit_directive_decl(child)
                if directive:
                    program.directives.append(directive)
            elif isinstance(child, CoexParser.DeclarationContext):
                decl = self.visit_declaration(child)
                if isinstance(decl, (FunctionDecl, KindFunctionDecl)):
                    program.functions.append(decl)
                elif isinstance(decl, TypeDecl):
                    program.types.append(decl)
                elif isinstance(decl, TraitDecl):
                    program.traits.append(decl)
                elif isinstance(decl, KindDecl):
                    # Already processed in first pass
                    pass

        return program

    # ========================================================================
    # Imports and Replace
    # ========================================================================

    def visit_import_decl(self, ctx: CoexParser.ImportDeclContext) -> Optional[ImportDecl]:
        """Visit an import declaration: import module_name or import "library.cxz" """
        # Check for module import (bare identifier)
        if ctx.IDENTIFIER():
            module = ctx.IDENTIFIER().getText()
            return ImportDecl(module=module)

        # Check for library import (string literal)
        if ctx.stringLiteral():
            path = self._get_string_value(ctx.stringLiteral())
            # Extract library name from path (e.g., "regex.cxz" -> "regex")
            import os
            basename = os.path.basename(path)
            if basename.endswith('.cxz'):
                module_name = basename[:-4]
            else:
                module_name = basename
            return ImportDecl(
                module=module_name,
                library_path=path,
                is_library=True
            )

        return None

    def visit_replace_decl(self, ctx: CoexParser.ReplaceDeclContext) -> Optional[ReplaceDecl]:
        """Visit a replace declaration: replace shortname with module.function"""
        shortname = ctx.IDENTIFIER().getText()
        qualified = ctx.qualifiedName()
        identifiers = qualified.IDENTIFIER()
        module = identifiers[0].getText()
        qualified_name = identifiers[1].getText()
        return ReplaceDecl(shortname=shortname, module=module, qualified_name=qualified_name)

    def visit_replace_kind_decl(self, ctx) -> Optional[ReplaceKindDecl]:
        """Visit a replace kind declaration: replace kind shortname with module.kindname"""
        shortname = ctx.IDENTIFIER().getText()
        qualified = ctx.qualifiedName()
        identifiers = qualified.IDENTIFIER()
        module = identifiers[0].getText()
        qualified_name = identifiers[1].getText()
        return ReplaceKindDecl(shortname=shortname, module=module, qualified_name=qualified_name)

    def visit_directive_decl(self, ctx: CoexParser.DirectiveDeclContext) -> Optional[DirectiveDecl]:
        """Visit a directive declaration: printing/debugging [on/off]"""
        # Determine which directive
        if ctx.PRINTING():
            name = "printing"
        elif ctx.DEBUGGING():
            name = "debugging"
        else:
            return None

        # Determine enabled state (default True if just "printing" or "debugging")
        enabled = True
        if ctx.OFF():
            enabled = False
        # ON() is explicit but same as default

        return DirectiveDecl(name=name, enabled=enabled)

    def _get_string_value(self, ctx) -> str:
        """Extract string value from string literal"""
        text = ctx.getText()
        # Remove quotes
        if text.startswith('"') or text.startswith("'"):
            return text[1:-1]
        return text
    
    # ========================================================================
    # Declarations
    # ========================================================================
    
    def visit_declaration(self, ctx: CoexParser.DeclarationContext):
        """Visit a top-level declaration"""
        child = ctx.getChild(0)

        if isinstance(child, CoexParser.FunctionDeclContext):
            return self.visit_function_decl(child)
        elif isinstance(child, CoexParser.TypeDeclContext):
            return self.visit_type_decl(child)
        elif isinstance(child, CoexParser.TraitDeclContext):
            return self.visit_trait_decl(child)
        elif hasattr(CoexParser, 'KindDeclContext') and isinstance(child, CoexParser.KindDeclContext):
            # Kind declarations already processed in first pass, return it for tracking
            return self.kind_registry.get(child.IDENTIFIER(0).getText())

        return None

    def visit_kind_decl(self, ctx) -> KindDecl:
        """Visit a kind declaration: kind NAME -> RETURN_TYPE via HANDLER"""
        identifiers = ctx.IDENTIFIER()
        name = identifiers[0].getText()
        return_type = self.visit_type_expr(ctx.typeExpr())
        handler = identifiers[1].getText()
        return KindDecl(name=name, return_type=return_type, handler=handler)
    
    def visit_function_decl(self, ctx: CoexParser.FunctionDeclContext) -> FunctionDecl:
        """Visit a function declaration"""
        # Check if this is an extern function (no body, just declaration)
        if ctx.EXTERN():
            # Extern function: extern name(params) -> type ~
            name = ctx.IDENTIFIER().getText()

            # Get parameters
            params = []
            if ctx.parameterList():
                params = self.visit_param_list(ctx.parameterList())

            # Get return type
            return_type = None
            return_unique = False
            if ctx.returnType():
                return_type = self.visit_type_expr(ctx.returnType().typeExpr())
                return_unique = ctx.returnType().UNIQUE() is not None

            # Extern functions have no body
            return FunctionDecl(FunctionKind.EXTERN, name, [], params, return_type, [], [], return_unique)

        # Regular function declaration
        # Get annotations
        annotations = []
        for ann_ctx in ctx.annotation():
            annotations.append(self.visit_annotation(ann_ctx))

        # Get function kind
        kind_ctx = ctx.functionKind()
        kind_text = kind_ctx.getText()

        # Check for qualified kind (module.kindname)
        if '.' in kind_text:
            parts = kind_text.split('.', 1)
            kind_module, kind_name = parts[0], parts[1]
            # This is a qualified kind reference - defer resolution to codegen
            return self._visit_kind_function(ctx, kind_name, annotations, kind_module=kind_module)

        # Check if this is a local user-defined kind
        if kind_text in self.kind_registry:
            return self._visit_kind_function(ctx, kind_text, annotations)

        if kind_text == "formula":
            kind = FunctionKind.FORMULA
        elif kind_text == "task":
            kind = FunctionKind.TASK
        elif kind_text == "thread":
            kind = FunctionKind.THREAD
        elif kind_text == "extern":
            kind = FunctionKind.EXTERN
        elif kind_text == "func":
            kind = FunctionKind.FUNC
        else:
            # Unknown function kind - might be a kind replace alias or imported kind
            # Defer to codegen for resolution (it will error if truly unknown)
            return self._visit_kind_function(ctx, kind_text, annotations)

        # Get function name
        name = ctx.IDENTIFIER().getText()

        # Get type parameters
        type_params = []
        if ctx.genericParams():
            type_params = self.visit_generic_params(ctx.genericParams())

        # Get parameters
        params = []
        if ctx.parameterList():
            params = self.visit_param_list(ctx.parameterList())

        # Get return type
        return_type = None
        return_unique = False
        if ctx.returnType():
            return_type = self.visit_type_expr(ctx.returnType().typeExpr())
            return_unique = ctx.returnType().UNIQUE() is not None

        # Get body - extern functions have no body
        if kind == FunctionKind.EXTERN:
            body = []
        else:
            body = self.visit_block(ctx.block())

        return FunctionDecl(kind, name, type_params, params, return_type, body, annotations, return_unique)

    def visit_annotation(self, ctx) -> Annotation:
        """Visit an annotation: @name or @name("argument")"""
        name = ctx.IDENTIFIER().getText()
        argument = None
        if ctx.stringLiteral():
            # Extract string value without quotes
            argument = self._get_string_value(ctx.stringLiteral())
        return Annotation(name, argument)

    def _visit_kind_function(self, ctx, kind_name: str, annotations: PyList[Annotation],
                             kind_module: Optional[str] = None) -> KindFunctionDecl:
        """Visit a function using a user-defined kind.

        The body is captured as raw text rather than parsed statements.

        Args:
            ctx: The function declaration context
            kind_name: The kind name (e.g., "sqlquery")
            annotations: List of annotations on the function
            kind_module: Optional module name for qualified kinds (e.g., "postgresql")
        """
        # Get function name
        name = ctx.IDENTIFIER().getText()

        # Get parameters
        params = []
        if ctx.parameterList():
            params = self.visit_param_list(ctx.parameterList())

        # Get return type (or use the kind's default return type if local kind)
        return_type = None
        if ctx.returnType():
            return_type = self.visit_type_expr(ctx.returnType().typeExpr())
        elif kind_module is None and kind_name in self.kind_registry:
            # Default to the local kind's declared return type
            kind_decl = self.kind_registry[kind_name]
            return_type = kind_decl.return_type
        # For qualified kinds, return type resolution is deferred to codegen

        # Capture raw body text - prefer rawBlock if present, fall back to block
        if ctx.rawBlock():
            body = self._capture_raw_block(ctx.rawBlock())
        elif ctx.block():
            body = self._capture_raw_body(ctx.block())
        else:
            body = ""

        return KindFunctionDecl(
            kind_name=kind_name,
            name=name,
            params=params,
            return_type=return_type,
            body=body,
            annotations=annotations,
            kind_module=kind_module
        )

    def _capture_raw_block(self, raw_block_ctx) -> str:
        """Capture the raw text from a rawBlock context.

        This reconstructs the text from the input stream, preserving whitespace.
        """
        if raw_block_ctx is None:
            return ""

        # Use the token stream to get the original text with whitespace
        if self._token_stream is not None:
            start = raw_block_ctx.start
            stop = raw_block_ctx.stop

            if start is not None and stop is not None:
                # Get input stream from the token stream
                input_stream = self._token_stream.tokenSource.inputStream
                tokens = self._token_stream.tokens

                # To preserve indentation, we need to start from after the
                # previous token (NEWLINE), not from the first content token
                # (which would miss skipped whitespace before it)
                start_idx = start.tokenIndex
                if start_idx > 0:
                    prev_token = tokens[start_idx - 1]
                    # Start capturing right after the previous token ends
                    start_pos = prev_token.stop + 1
                else:
                    start_pos = start.start

                # Find the position just before the terminator (~)
                stop_pos = stop.start - 1

                if start_pos <= stop_pos:
                    # Get raw text from input stream
                    raw_text = input_stream.getText(start_pos, stop_pos)
                else:
                    raw_text = ""
        else:
            # Fallback: get text from context but whitespace may be lost
            content_parts = []
            for i in range(raw_block_ctx.getChildCount()):
                child = raw_block_ctx.getChild(i)
                if hasattr(child, 'getText') and child.getText() not in ('~', 'end'):
                    content_parts.append(child.getText())
            raw_text = ' '.join(content_parts)

        # Strip leading/trailing whitespace and normalize
        lines = raw_text.split('\n')

        # Remove leading empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        # Remove trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()

        # Find common indentation to dedent
        if lines:
            non_empty_lines = [line for line in lines if line.strip()]
            if non_empty_lines:
                min_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines)
                lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]

        return '\n'.join(lines)

    def _capture_raw_body(self, block_ctx) -> str:
        """Capture the raw text of a block, stripping the terminator.

        This preserves the original source text for kind functions,
        allowing DSL bodies to contain any syntax.
        """
        if self._token_stream is None or block_ctx is None:
            return ""

        # Get the token indices for the block
        start = block_ctx.start
        stop = block_ctx.stop

        if start is None or stop is None:
            return ""

        # Get all tokens in the block
        tokens = self._token_stream.tokens

        # Find the start and end token indices
        start_idx = start.tokenIndex
        stop_idx = stop.tokenIndex

        # Build the raw text from tokens
        raw_parts = []
        for i in range(start_idx, stop_idx + 1):
            if i < len(tokens):
                raw_parts.append(tokens[i].text)

        raw_text = ''.join(raw_parts)

        # Strip the block terminator (~ or end) from the end
        raw_text = raw_text.rstrip()
        if raw_text.endswith('~'):
            raw_text = raw_text[:-1].rstrip()
        elif raw_text.endswith('end'):
            raw_text = raw_text[:-3].rstrip()

        # Strip leading/trailing whitespace and normalize newlines
        lines = raw_text.split('\n')
        # Remove leading empty lines
        while lines and not lines[0].strip():
            lines.pop(0)
        # Remove trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()

        # Find common indentation to dedent
        if lines:
            non_empty_lines = [line for line in lines if line.strip()]
            if non_empty_lines:
                min_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines)
                lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]

        return '\n'.join(lines)
    
    def visit_generic_params(self, ctx: CoexParser.GenericParamsContext) -> List[TypeParam]:
        """Visit generic type parameters"""
        params = []
        # genericParams: LT genericParamList GT
        # genericParamList: genericParam (COMMA genericParam)*
        # genericParam: IDENTIFIER (COLON traitBound)?
        param_list = ctx.genericParamList()
        if param_list:
            for gp in param_list.genericParam():
                name = gp.IDENTIFIER().getText()
                bounds = []
                # Check for trait bounds (T: Trait)
                if gp.traitBound():
                    # traitBound: IDENTIFIER (PLUS IDENTIFIER)*
                    bounds = [gp.traitBound().IDENTIFIER(0).getText()]
                params.append(TypeParam(name, bounds))
        return params
    
    def visit_param_list(self, ctx: CoexParser.ParameterListContext) -> List[Parameter]:
        """Visit parameter list"""
        params = []
        for param_ctx in ctx.parameter():
            params.append(self.visit_param(param_ctx))
        return params
    
    def visit_param(self, ctx: CoexParser.ParameterContext) -> Parameter:
        """Visit a single parameter"""
        positional = ctx.UNDERSCORE() is not None
        is_unique = ctx.UNIQUE() is not None
        is_borrow = ctx.BORROW() is not None
        name = ctx.IDENTIFIER().getText()
        type_ann = self.visit_type_expr(ctx.typeExpr())
        return Parameter(name, type_ann, positional, is_unique=is_unique, is_borrow=is_borrow)
    
    def visit_type_decl(self, ctx: CoexParser.TypeDeclContext) -> TypeDecl:
        """Visit a type declaration"""
        name = ctx.IDENTIFIER().getText()

        type_params = []
        if ctx.genericParams():
            type_params = self.visit_generic_params(ctx.genericParams())

        fields = []
        methods = []
        variants = []

        # Visit type body for fields, methods, and enum cases
        if ctx.typeBody():
            for member in ctx.typeBody().typeMember():
                if member.fieldDecl():
                    fields.append(self.visit_field_decl(member.fieldDecl()))
                elif member.enumCase():
                    variants.append(self.visit_enum_case(member.enumCase()))
                elif member.methodDecl():
                    methods.append(self.visit_method_decl(member.methodDecl()))

        return TypeDecl(name, type_params, fields, methods, variants)
    
    def visit_enum_case(self, ctx: CoexParser.EnumCaseContext) -> EnumVariant:
        """Visit an enum case"""
        name = ctx.IDENTIFIER().getText()
        fields = []
        if ctx.enumCaseParams():
            for param in ctx.enumCaseParams().enumCaseParam():
                field_name = param.IDENTIFIER().getText()
                field_type = self.visit_type_expr(param.typeExpr())
                fields.append(FieldDecl(field_name, field_type))
        return EnumVariant(name, fields)
    
    def visit_field_decl(self, ctx: CoexParser.FieldDeclContext) -> FieldDecl:
        """Visit a field declaration"""
        name = ctx.IDENTIFIER().getText()
        type_ann = self.visit_type_expr(ctx.typeExpr())
        # Grammar doesn't support default values for fields
        return FieldDecl(name, type_ann, None)
    
    def visit_method_decl(self, ctx: CoexParser.MethodDeclContext) -> FunctionDecl:
        """Visit a method declaration"""
        # Get function kind
        kind_ctx = ctx.functionKind()
        kind_text = kind_ctx.getText()
        if kind_text == "formula":
            kind = FunctionKind.FORMULA
        elif kind_text == "task":
            kind = FunctionKind.TASK
        elif kind_text == "thread":
            kind = FunctionKind.THREAD
        else:
            kind = FunctionKind.FUNC

        # Get method name
        name = ctx.IDENTIFIER().getText()
        
        # Get type parameters
        type_params = []
        if ctx.genericParams():
            type_params = self.visit_generic_params(ctx.genericParams())
        
        # Get parameters
        params = []
        if ctx.parameterList():
            params = self.visit_param_list(ctx.parameterList())
        
        # Get return type
        return_type = None
        return_unique = False
        if ctx.returnType():
            return_type = self.visit_type_expr(ctx.returnType().typeExpr())
            return_unique = ctx.returnType().UNIQUE() is not None

        # Get body
        body = self.visit_block(ctx.block())

        return FunctionDecl(kind, name, type_params, params, return_type, body, [], return_unique)
    
    def visit_trait_decl(self, ctx: CoexParser.TraitDeclContext) -> TraitDecl:
        """Visit a trait declaration"""
        name = ctx.IDENTIFIER().getText()
        
        type_params = []
        if ctx.genericParams():
            type_params = self.visit_generic_params(ctx.genericParams())
        
        methods = []
        if ctx.traitBody():
            for method in ctx.traitBody().traitMethodDecl():
                methods.append(self.visit_trait_method(method))
        
        return TraitDecl(name, type_params, methods)
    
    def visit_trait_method(self, ctx: CoexParser.TraitMethodDeclContext) -> FunctionDecl:
        """Visit a trait method signature"""
        kind_ctx = ctx.functionKind()
        kind_text = kind_ctx.getText() if kind_ctx else "func"
        kind = {"formula": FunctionKind.FORMULA, "task": FunctionKind.TASK, "thread": FunctionKind.THREAD}.get(kind_text, FunctionKind.FUNC)
        
        name = ctx.IDENTIFIER().getText()
        params = []
        if ctx.parameterList():
            params = self.visit_param_list(ctx.parameterList())
        
        return_type = None
        return_unique = False
        if ctx.returnType():
            return_type = self.visit_type_expr(ctx.returnType().typeExpr())
            return_unique = ctx.returnType().UNIQUE() is not None

        # Trait methods are abstract - no body
        body = []

        return FunctionDecl(kind, name, [], params, return_type, body, [], return_unique)

    # ========================================================================
    # Types
    # ========================================================================
    
    def visit_type_expr(self, ctx: CoexParser.TypeExprContext) -> Type:
        """Visit a type expression"""
        base = self.visit_base_type(ctx.baseType())
        
        # Check for optional (?)
        if ctx.QUESTION():
            return OptionalType(base)
        
        return base
    
    def visit_base_type(self, ctx: CoexParser.BaseTypeContext) -> Type:
        """Visit a base type"""
        if ctx.primitiveType():
            return self.visit_primitive_type(ctx.primitiveType())
        elif ctx.listType():
            # [T] shorthand for List<T>
            element_type = self.visit_type_expr(ctx.listType().typeExpr())
            return ListType(element_type)
        elif ctx.IDENTIFIER():
            name = ctx.IDENTIFIER().getText()
            # Handle generic types
            if ctx.genericArgs():
                type_args = self.visit_generic_args(ctx.genericArgs())
                # Built-in generic types
                if name == "List" and len(type_args) == 1:
                    return ListType(type_args[0])
                elif name == "Map" and len(type_args) == 2:
                    return MapType(type_args[0], type_args[1])
                elif name == "Set" and len(type_args) == 1:
                    return SetType(type_args[0])
                elif name == "Array" and len(type_args) == 1:
                    return ArrayType(type_args[0])
                elif name == "Channel" and len(type_args) == 1:
                    return ChannelType(type_args[0])
                elif name == "Result" and len(type_args) == 2:
                    return ResultType(type_args[0], type_args[1])
                else:
                    return NamedType(name, type_args)
            return NamedType(name)
        elif ctx.tupleType():
            return self.visit_tuple_type(ctx.tupleType())
        elif ctx.functionType():
            return self.visit_function_type(ctx.functionType())

        return PrimitiveType("int")  # fallback
    
    def visit_primitive_type(self, ctx: CoexParser.PrimitiveTypeContext) -> Type:
        """Visit a primitive type"""
        text = ctx.getText()
        if text.startswith("atomic_"):
            return AtomicType(text[7:])  # atomic_int -> AtomicType("int")
        return PrimitiveType(text)
    
    def visit_generic_args(self, ctx: CoexParser.GenericArgsContext) -> List[Type]:
        """Visit generic type arguments"""
        types = []
        for type_ctx in ctx.typeList().typeExpr():
            types.append(self.visit_type_expr(type_ctx))
        return types
    
    def visit_tuple_type(self, ctx: CoexParser.TupleTypeContext) -> TupleType:
        """Visit a tuple type"""
        elements = []
        for elem in ctx.tupleTypeElement():
            name = None
            if elem.IDENTIFIER():
                name = elem.IDENTIFIER().getText()
            type_ann = self.visit_type_expr(elem.typeExpr())
            elements.append((name, type_ann))
        return TupleType(elements)
    
    def visit_function_type(self, ctx: CoexParser.FunctionTypeContext) -> FunctionType:
        """Visit a function type: formula(int, int) -> int"""
        kind_text = ctx.functionKind().getText() if ctx.functionKind() else "func"
        kind = {"formula": FunctionKind.FORMULA, "task": FunctionKind.TASK, "thread": FunctionKind.THREAD}.get(kind_text, FunctionKind.FUNC)
        
        param_types = []
        if ctx.typeList():
            for type_expr in ctx.typeList().typeExpr():
                param_types.append(self.visit_type_expr(type_expr))
        
        return_type = None
        # Check for return type (after ARROW)
        if ctx.typeExpr():
            return_type = self.visit_type_expr(ctx.typeExpr())
        
        return FunctionType(kind, param_types, return_type)
    
    # ========================================================================
    # Statements
    # ========================================================================
    
    def visit_block(self, ctx: CoexParser.BlockContext) -> List[Stmt]:
        """Visit a block of statements"""
        stmts = []
        for stmt_ctx in ctx.statement():
            stmt = self.visit_statement(stmt_ctx)
            if stmt:
                stmts.append(stmt)
        return stmts
    
    def visit_if_block(self, ctx: CoexParser.IfBlockContext) -> List[Stmt]:
        """Visit an if block (statements without terminator)"""
        stmts = []
        for stmt_ctx in ctx.statement():
            stmt = self.visit_statement(stmt_ctx)
            if stmt:
                stmts.append(stmt)
        return stmts
    
    def visit_statement(self, ctx: CoexParser.StatementContext) -> Optional[Stmt]:
        """Visit a statement"""
        child = ctx.getChild(0)

        if isinstance(child, CoexParser.VarDeclStmtContext):
            return self.visit_var_decl_stmt(child)
        elif hasattr(CoexParser, 'TupleDestructureStmtContext') and isinstance(child, CoexParser.TupleDestructureStmtContext):
            return self.visit_tuple_destructure_stmt(child)
        elif isinstance(child, CoexParser.ControlFlowStmtContext):
            return self.visit_control_flow_stmt(child)
        elif hasattr(CoexParser, 'LlvmIrStmtContext') and isinstance(child, CoexParser.LlvmIrStmtContext):
            return self.visit_llvm_ir_stmt(child)
        elif isinstance(child, CoexParser.SimpleStmtContext):
            return self.visit_simple_stmt(child)

        return None
    
    def visit_tuple_destructure_stmt(self, ctx) -> TupleDestructureStmt:
        """Visit a tuple destructuring statement: (a, b) = expr"""
        # Get all identifiers
        names = [id_token.getText() for id_token in ctx.IDENTIFIER()]
        # Get the expression
        value = self.visit_expression(ctx.expression())
        return TupleDestructureStmt(names=names, value=value)

    def visit_llvm_ir_stmt(self, ctx) -> Stmt:
        """Visit an inline LLVM IR statement

        Syntax:
            llvm_ir(x -> %a, y -> %b) -> %result: i64 \"\"\"
                %result = add i64 %a, %b
                ret i64 %result
            \"\"\"

        Returns LlvmIrExpr if there's a return specification, otherwise LlvmIrStmt.
        """
        # Parse bindings
        bindings = []
        if ctx.llvmBindings():
            for binding_ctx in ctx.llvmBindings().llvmBinding():
                coex_name = binding_ctx.IDENTIFIER().getText()
                llvm_reg = binding_ctx.LLVM_REGISTER().getText()
                type_hint = None
                if binding_ctx.llvmTypeHint():
                    type_hint = binding_ctx.llvmTypeHint().getText()
                bindings.append(LlvmBinding(coex_name, llvm_reg, type_hint))

        # Extract IR body from triple-quoted string
        ir_body = ctx.TRIPLE_STRING().getText()
        ir_body = self._clean_triple_string(ir_body)

        # Check for return specification
        if ctx.llvmReturn():
            return_reg = ctx.llvmReturn().LLVM_REGISTER().getText()
            return_type = ctx.llvmReturn().llvmTypeHint().getText()
            return LlvmIrExpr(bindings, ir_body, return_reg, return_type)
        else:
            return LlvmIrStmt(bindings, ir_body)

    def visit_llvm_ir_expr(self, ctx) -> LlvmIrExpr:
        """Visit an inline LLVM IR expression (with return value)

        This is used when llvm_ir appears as an expression, e.g.:
            var result: int = llvm_ir(x -> %a) -> %r: i64 \"\"\"...\"\"\"
        """
        # Parse bindings
        bindings = []
        if ctx.llvmBindings():
            for binding_ctx in ctx.llvmBindings().llvmBinding():
                coex_name = binding_ctx.IDENTIFIER().getText()
                llvm_reg = binding_ctx.LLVM_REGISTER().getText()
                type_hint = None
                if binding_ctx.llvmTypeHint():
                    type_hint = binding_ctx.llvmTypeHint().getText()
                bindings.append(LlvmBinding(coex_name, llvm_reg, type_hint))

        # Extract IR body from triple-quoted string
        ir_body = ctx.TRIPLE_STRING().getText()
        ir_body = self._clean_triple_string(ir_body)

        # llvmReturn is required for expression form
        return_reg = ctx.llvmReturn().LLVM_REGISTER().getText()
        return_type = ctx.llvmReturn().llvmTypeHint().getText()

        return LlvmIrExpr(bindings, ir_body, return_reg, return_type)

    def _clean_triple_string(self, raw: str) -> str:
        """Remove triple quotes and normalize indentation"""
        # Strip """ or '''
        if raw.startswith('"""'):
            content = raw[3:-3]
        elif raw.startswith("'''"):
            content = raw[3:-3]
        else:
            content = raw

        # Remove common leading indentation
        lines = content.split('\n')
        non_empty = [line for line in lines if line.strip()]
        if non_empty:
            min_indent = min(len(line) - len(line.lstrip()) for line in non_empty)
            lines = [line[min_indent:] if len(line) >= min_indent else line for line in lines]

        return '\n'.join(lines).strip()

    def visit_var_decl_stmt(self, ctx: CoexParser.VarDeclStmtContext) -> VarDecl:
        """Visit a variable declaration statement: [const|unique] name [: type] = expr"""
        # Check for const or unique keyword
        is_const = ctx.CONST() is not None
        is_unique = ctx.UNIQUE() is not None

        name = ctx.IDENTIFIER().getText()
        # Type annotation is optional
        type_ann = self.visit_type_expr(ctx.typeExpr()) if ctx.typeExpr() else None
        init = self.visit_expression(ctx.expression())
        # Check if this is a copy assignment (:=)
        is_copy = ctx.COPY_ASSIGN() is not None
        return VarDecl(name, type_ann, init, is_const=is_const, is_copy=is_copy, is_unique=is_unique)
    
    def visit_simple_stmt(self, ctx: CoexParser.SimpleStmtContext) -> Stmt:
        """Visit a simple statement (expression or assignment)"""
        exprs = ctx.expression()

        if len(exprs) == 2 and ctx.assignOp():
            # Assignment
            target = self.visit_expression(exprs[0])
            value = self.visit_expression(exprs[1])
            op = self.visit_assign_op(ctx.assignOp())

            # Check if target is a slice expression - convert to SliceAssignment
            if isinstance(target, SliceExpr):
                return SliceAssignment(
                    target=target.object,
                    start=target.start,
                    end=target.end,
                    value=value,
                    op=op
                )

            return Assignment(target, op, value)
        else:
            # Expression statement
            expr = self.visit_expression(exprs[0])
            
            # Detect built-in print() and debug() calls
            if isinstance(expr, CallExpr) and isinstance(expr.callee, Identifier):
                if expr.callee.name == "print" and len(expr.args) >= 1:
                    return PrintStmt(expr.args[0])
                if expr.callee.name == "debug" and len(expr.args) >= 1:
                    return DebugStmt(expr.args[0])

            return ExprStmt(expr)
    
    def visit_assign_op(self, ctx: CoexParser.AssignOpContext) -> AssignOp:
        """Visit assignment operator"""
        text = ctx.getText()
        op_map = {
            "=": AssignOp.ASSIGN,
            ":=": AssignOp.COPY_ASSIGN,
            "+=": AssignOp.PLUS_ASSIGN,
            "-=": AssignOp.MINUS_ASSIGN,
            "*=": AssignOp.STAR_ASSIGN,
            "/=": AssignOp.SLASH_ASSIGN,
            "%=": AssignOp.PERCENT_ASSIGN,
        }
        return op_map.get(text, AssignOp.ASSIGN)
    
    def visit_control_flow_stmt(self, ctx: CoexParser.ControlFlowStmtContext) -> Stmt:
        """Visit a control flow statement"""
        child = ctx.getChild(0)
        
        if isinstance(child, CoexParser.IfStmtContext):
            return self.visit_if_stmt(child)
        elif isinstance(child, CoexParser.ForStmtContext):
            return self.visit_for_stmt(child)
        elif isinstance(child, CoexParser.ForAssignStmtContext):
            return self.visit_for_assign_stmt(child)
        elif isinstance(child, CoexParser.FirstAssignStmtContext):
            return self.visit_first_assign_stmt(child)
        elif isinstance(child, CoexParser.MostAssignStmtContext):
            return self.visit_most_assign_stmt(child)
        elif isinstance(child, CoexParser.WhileStmtContext):
            return self.visit_while_stmt(child)
        elif isinstance(child, CoexParser.CycleStmtContext):
            return self.visit_cycle_stmt(child)
        elif isinstance(child, CoexParser.MatchStmtContext):
            return self.visit_match_stmt(child)
        elif isinstance(child, CoexParser.SelectStmtContext):
            return self.visit_select_stmt(child)
        elif isinstance(child, CoexParser.WithinStmtContext):
            return self.visit_within_stmt(child)
        elif isinstance(child, CoexParser.ReturnStmtContext):
            return self.visit_return_stmt(child)
        elif isinstance(child, CoexParser.BreakStmtContext):
            return BreakStmt()
        elif isinstance(child, CoexParser.ContinueStmtContext):
            return ContinueStmt()
        
        return None
    
    def visit_if_stmt(self, ctx: CoexParser.IfStmtContext) -> IfStmt:
        """Visit an if statement"""
        condition = self.visit_expression(ctx.expression())
        then_body = self.visit_if_block(ctx.ifBlock())
        
        else_if_clauses = []
        for else_if in ctx.elseIfClause():
            eif_cond = self.visit_expression(else_if.expression())
            eif_body = self.visit_if_block(else_if.ifBlock())
            else_if_clauses.append((eif_cond, eif_body))
        
        else_body = None
        if ctx.elseClause():
            else_body = self.visit_if_block(ctx.elseClause().ifBlock())
        
        return IfStmt(condition, then_body, else_if_clauses, else_body)
    
    def visit_for_stmt(self, ctx: CoexParser.ForStmtContext) -> ForStmt:
        """Visit a for statement with destructuring support"""
        pattern = self.visit_binding_pattern(ctx.bindingPattern())
        iterable = self.visit_expression(ctx.expression())
        body = self.visit_block(ctx.block())
        return ForStmt(pattern, iterable, body)
    
    def visit_for_assign_stmt(self, ctx: CoexParser.ForAssignStmtContext) -> ForAssignStmt:
        """Visit a for-assign statement: results = for i in items expr ~"""
        target = ctx.IDENTIFIER().getText()
        pattern = self.visit_binding_pattern(ctx.bindingPattern())
        iterable = self.visit_expression(ctx.expression(0))
        body_expr = self.visit_expression(ctx.expression(1))
        return ForAssignStmt(target, pattern, iterable, body_expr)

    def visit_first_assign_stmt(self, ctx: CoexParser.FirstAssignStmtContext) -> FirstAssignStmt:
        """Visit a first-assign statement: result = first i in items body ~

        Returns the first successful result, cancelling remaining tasks.
        """
        target = ctx.IDENTIFIER().getText()
        pattern = self.visit_binding_pattern(ctx.bindingPattern())
        iterable = self.visit_expression(ctx.expression())
        body = self.visit_block(ctx.block())
        return FirstAssignStmt(target, pattern, iterable, body)

    def visit_most_assign_stmt(self, ctx: CoexParser.MostAssignStmtContext) -> MostAssignStmt:
        """Visit a most-assign statement: (results, errors) = most i in items body ~

        Returns tuple of (successful_results, errors) - no cancellation.
        """
        # Grammar: (IDENTIFIER, IDENTIFIER) = most pattern in expr body ~
        identifiers = ctx.IDENTIFIER()
        results_target = identifiers[0].getText()
        errors_target = identifiers[1].getText()
        pattern = self.visit_binding_pattern(ctx.bindingPattern())
        iterable = self.visit_expression(ctx.expression())
        body = self.visit_block(ctx.block())
        return MostAssignStmt(results_target, errors_target, pattern, iterable, body)

    def visit_binding_pattern(self, ctx) -> Pattern:
        """Visit a binding pattern (for destructuring in for loops and comprehensions)"""
        if ctx.IDENTIFIER():
            return IdentifierPattern(ctx.IDENTIFIER().getText())
        elif ctx.UNDERSCORE():
            return WildcardPattern()
        else:
            # Tuple pattern: (a, b, c)
            elements = [self.visit_binding_pattern(p) for p in ctx.bindingPattern()]
            return TuplePattern(elements)
    
    def visit_while_stmt(self, ctx: CoexParser.WhileStmtContext) -> WhileStmt:
        """Visit a while statement: while condition block"""
        condition = self.visit_expression(ctx.expression())
        body = self.visit_block(ctx.block())
        return WhileStmt(condition, body)

    def visit_cycle_stmt(self, ctx: CoexParser.CycleStmtContext) -> CycleStmt:
        """Visit a cycle statement: while condition cycle block

        The cycle construct provides double-buffered semantics for
        synchronous dataflow computation. Variables declared inside
        the cycle block exist in two buffers - reads see the previous
        generation's values, writes go to the current generation's buffer.
        """
        condition = self.visit_expression(ctx.expression())
        body = self.visit_block(ctx.block())
        return CycleStmt(condition, body)

    def visit_match_stmt(self, ctx: CoexParser.MatchStmtContext) -> MatchStmt:
        """Visit a match statement"""
        subject = self.visit_expression(ctx.expression())
        arms = []
        if ctx.matchBody():
            for case in ctx.matchBody().matchCase():
                arms.append(self.visit_match_case(case))
        return MatchStmt(subject, arms)
    
    def visit_match_case(self, ctx: CoexParser.MatchCaseContext) -> MatchArm:
        """Visit a match case"""
        pattern = self.visit_pattern(ctx.pattern())
        body = []
        for stmt in ctx.statement():
            s = self.visit_statement(stmt)
            if s:
                body.append(s)
        return MatchArm(pattern, None, body)  # No guard in current grammar
    
    def visit_pattern(self, ctx: CoexParser.PatternContext) -> Pattern:
        """Visit a pattern"""
        if ctx.literal():
            return LiteralPattern(self.visit_literal(ctx.literal()))
        elif ctx.IDENTIFIER():
            name = ctx.IDENTIFIER().getText()
            if ctx.patternParams():
                # Constructor pattern: Some(x, y)
                args = []
                for ident in ctx.patternParams().IDENTIFIER():
                    args.append(IdentifierPattern(ident.getText()))
                return ConstructorPattern(name, args)
            # Check if it's a wildcard
            if name == "_":
                return WildcardPattern()
            return IdentifierPattern(name)
        
        return WildcardPattern()
    
    def visit_select_stmt(self, ctx: CoexParser.SelectStmtContext) -> SelectStmt:
        """Visit a select statement"""
        strategy = SelectStrategy.DEFAULT
        timeout = None
        
        if ctx.selectModifier():
            mod = ctx.selectModifier()
            if mod.selectStrategy():
                strat_text = mod.selectStrategy().getText()
                strategy = {
                    "fair": SelectStrategy.FAIR,
                    "random": SelectStrategy.RANDOM,
                    "priority": SelectStrategy.PRIORITY,
                }.get(strat_text, SelectStrategy.DEFAULT)
            if mod.expression():
                timeout = self.visit_expression(mod.expression())
        
        cases = []
        if ctx.selectBody():
            for case in ctx.selectBody().selectCase():
                cases.append(self.visit_select_case(case))
        
        return SelectStmt(strategy, timeout, cases)
    
    def visit_select_case(self, ctx: CoexParser.SelectCaseContext) -> SelectCase:
        """Visit a select case"""
        var_name = ctx.IDENTIFIER().getText()
        channel = self.visit_expression(ctx.expression())
        body = []
        for stmt in ctx.statement():
            s = self.visit_statement(stmt)
            if s:
                body.append(s)
        return SelectCase(var_name, channel, body)
    
    def visit_within_stmt(self, ctx: CoexParser.WithinStmtContext) -> WithinStmt:
        """Visit a within statement"""
        timeout = self.visit_expression(ctx.expression())
        body = self.visit_if_block(ctx.ifBlock())
        
        else_body = None
        if ctx.withinElse():
            else_body = self.visit_if_block(ctx.withinElse().ifBlock())
        
        return WithinStmt(timeout, body, else_body)
    
    def visit_return_stmt(self, ctx: CoexParser.ReturnStmtContext) -> ReturnStmt:
        """Visit a return statement"""
        value = None
        if ctx.expression():
            value = self.visit_expression(ctx.expression())
        return ReturnStmt(value)
    
    # ========================================================================
    # Expressions
    # ========================================================================
    
    def visit_expression(self, ctx: CoexParser.ExpressionContext) -> Expr:
        """Visit an expression"""
        return self.visit_ternary_expr(ctx.ternaryExpr())
    
    def visit_ternary_expr(self, ctx: CoexParser.TernaryExprContext) -> Expr:
        """Visit a ternary expression"""
        # Grammar: orExpr (QUESTION ternaryExpr (COLON | BANG) ternaryExpr)?
        if ctx.QUESTION():
            condition = self.visit_or_expr(ctx.orExpr())
            ternary_exprs = ctx.ternaryExpr()
            then_expr = self.visit_ternary_expr(ternary_exprs[0])
            else_expr = self.visit_ternary_expr(ternary_exprs[1]) if len(ternary_exprs) > 1 else NilLiteral()
            # Check if this is the exit variant (!) vs continuation (:)
            is_exit = ctx.BANG() is not None
            return TernaryExpr(condition, then_expr, else_expr, is_exit)
        return self.visit_or_expr(ctx.orExpr())
    
    def visit_or_expr(self, ctx: CoexParser.OrExprContext) -> Expr:
        """Visit an OR expression"""
        result = self.visit_and_expr(ctx.andExpr(0))
        for i in range(1, len(ctx.andExpr())):
            right = self.visit_and_expr(ctx.andExpr(i))
            result = BinaryExpr(BinaryOp.OR, result, right)
        return result
    
    def visit_and_expr(self, ctx: CoexParser.AndExprContext) -> Expr:
        """Visit an AND expression"""
        result = self.visit_not_expr(ctx.notExpr(0))
        for i in range(1, len(ctx.notExpr())):
            right = self.visit_not_expr(ctx.notExpr(i))
            result = BinaryExpr(BinaryOp.AND, result, right)
        return result
    
    def visit_not_expr(self, ctx: CoexParser.NotExprContext) -> Expr:
        """Visit a NOT expression"""
        if ctx.NOT():
            operand = self.visit_not_expr(ctx.notExpr())
            return UnaryExpr(UnaryOp.NOT, operand)
        return self.visit_null_coalesce_expr(ctx.nullCoalesceExpr())
    
    def visit_null_coalesce_expr(self, ctx: CoexParser.NullCoalesceExprContext) -> Expr:
        """Visit a null coalesce expression"""
        result = self.visit_comparison_expr(ctx.comparisonExpr(0))
        for i in range(1, len(ctx.comparisonExpr())):
            right = self.visit_comparison_expr(ctx.comparisonExpr(i))
            result = BinaryExpr(BinaryOp.NULL_COALESCE, result, right)
        return result
    
    def visit_comparison_expr(self, ctx: CoexParser.ComparisonExprContext) -> Expr:
        """Visit a comparison expression"""
        result = self.visit_range_expr(ctx.rangeExpr(0))
        
        if len(ctx.rangeExpr()) > 1 and ctx.comparisonOp():
            op_text = ctx.comparisonOp(0).getText()
            op_map = {
                "==": BinaryOp.EQ,
                "!=": BinaryOp.NE,
                "<": BinaryOp.LT,
                ">": BinaryOp.GT,
                "<=": BinaryOp.LE,
                ">=": BinaryOp.GE,
            }
            op = op_map.get(op_text, BinaryOp.EQ)
            right = self.visit_range_expr(ctx.rangeExpr(1))
            result = BinaryExpr(op, result, right)
        
        return result
    
    def visit_range_expr(self, ctx: CoexParser.RangeExprContext) -> Expr:
        """Visit a range expression"""
        result = self.visit_additive_expr(ctx.additiveExpr(0))
        
        if ctx.DOTDOT():
            right = self.visit_additive_expr(ctx.additiveExpr(1))
            result = RangeExpr(result, right)
        
        return result
    
    def visit_additive_expr(self, ctx: CoexParser.AdditiveExprContext) -> Expr:
        """Visit an additive expression"""
        mult_exprs = ctx.multiplicativeExpr()
        result = self.visit_multiplicative_expr(mult_exprs[0])
        
        if len(mult_exprs) > 1:
            op_idx = 0
            for child in ctx.children:
                if hasattr(child, 'symbol'):
                    token_type = child.symbol.type
                    if token_type == CoexParser.PLUS:
                        op_idx += 1
                        right = self.visit_multiplicative_expr(mult_exprs[op_idx])
                        result = BinaryExpr(BinaryOp.ADD, result, right)
                    elif token_type == CoexParser.MINUS:
                        op_idx += 1
                        right = self.visit_multiplicative_expr(mult_exprs[op_idx])
                        result = BinaryExpr(BinaryOp.SUB, result, right)
        
        return result
    
    def visit_multiplicative_expr(self, ctx: CoexParser.MultiplicativeExprContext) -> Expr:
        """Visit a multiplicative expression"""
        unary_exprs = ctx.unaryExpr()
        result = self.visit_unary_expr(unary_exprs[0])
        
        if len(unary_exprs) > 1:
            op_idx = 0
            for child in ctx.children:
                if hasattr(child, 'symbol'):
                    token_type = child.symbol.type
                    if token_type == CoexParser.STAR:
                        op_idx += 1
                        right = self.visit_unary_expr(unary_exprs[op_idx])
                        result = BinaryExpr(BinaryOp.MUL, result, right)
                    elif token_type == CoexParser.SLASH:
                        op_idx += 1
                        right = self.visit_unary_expr(unary_exprs[op_idx])
                        result = BinaryExpr(BinaryOp.DIV, result, right)
                    elif token_type == CoexParser.PERCENT:
                        op_idx += 1
                        right = self.visit_unary_expr(unary_exprs[op_idx])
                        result = BinaryExpr(BinaryOp.MOD, result, right)
        
        return result
    
    def visit_unary_expr(self, ctx: CoexParser.UnaryExprContext) -> Expr:
        """Visit a unary expression"""
        if ctx.MINUS():
            operand = self.visit_unary_expr(ctx.unaryExpr())
            return UnaryExpr(UnaryOp.NEG, operand)
        elif ctx.AWAIT():
            operand = self.visit_unary_expr(ctx.unaryExpr())
            return UnaryExpr(UnaryOp.AWAIT, operand)
        return self.visit_postfix_expr(ctx.postfixExpr())
    
    def visit_postfix_expr(self, ctx: CoexParser.PostfixExprContext) -> Expr:
        """Visit a postfix expression"""
        result = self.visit_primary_expr(ctx.primaryExpr())
        
        for op in ctx.postfixOp():
            result = self.visit_postfix_op(result, op)
        
        return result
    
    def visit_postfix_op(self, base: Expr, ctx: CoexParser.PostfixOpContext) -> Expr:
        """Visit a postfix operator"""
        if ctx.DOT():
            # Check for integer tuple index access first
            if ctx.INTEGER_LITERAL():
                member = ctx.INTEGER_LITERAL().getText()
                return MemberExpr(base, member)
            
            member = ctx.methodName().getText()
            if ctx.LPAREN() is not None:
                # Method call: obj.method(args)
                args = []
                named_args = {}
                if ctx.argumentList():
                    args, named_args = self.visit_argument_list(ctx.argumentList())
                return MethodCallExpr(base, member, args)
            else:
                # Member access: obj.field
                return MemberExpr(base, member)
        elif ctx.DOUBLE_LBRACKET():
            # Relative indexing for cellular automata: arr[[offset]] or arr[[i, j]]
            relative_index = ctx.relativeIndex()
            offsets = []
            for expr in relative_index.expression():
                offsets.append(self.visit_expression(expr))
            return RelativeIndexExpr(base, offsets)
        elif ctx.LBRACKET():
            # Index or slice access: obj[index], obj[i, j], or obj[start:end]
            slice_or_index = ctx.sliceOrIndex()
            if slice_or_index:
                return self.visit_slice_or_index(base, slice_or_index)
            # Fallback for backward compatibility
            indices = []
            if ctx.expressionList():
                for expr in ctx.expressionList().expression():
                    indices.append(self.visit_expression(expr))
            return IndexExpr(base, indices)
        elif ctx.LPAREN() is not None:
            # Function call: func(args)
            args = []
            named_args = {}
            if ctx.argumentList():
                args, named_args = self.visit_argument_list(ctx.argumentList())
            return CallExpr(base, args, named_args)
        elif ctx.AS():
            # Type cast: expr as Type or expr as Type?
            type_expr = self.visit_type_expr(ctx.typeExpr())
            is_optional = False
            # Check if the type is optional (Type?)
            if isinstance(type_expr, OptionalType):
                is_optional = True
            return AsExpr(base, type_expr, is_optional)

        return base

    def visit_slice_or_index(self, base: Expr, ctx: CoexParser.SliceOrIndexContext) -> Expr:
        """Visit a slice or index access: obj[i], obj[i, j], or obj[start:end]"""
        # Check if this is a slice expression (has COLON)
        slice_expr = ctx.sliceExpr()
        if slice_expr:
            # Slice: obj[start:end], obj[:end], obj[start:], obj[:]
            start = None
            end = None

            # sliceExpr is: expression? COLON expression?
            exprs = slice_expr.expression()
            if len(exprs) == 0:
                # [:] - empty slice, both None
                pass
            elif len(exprs) == 1:
                # Either [start:] or [:end]
                # Check if COLON comes first
                colon = slice_expr.COLON()
                expr_token = exprs[0]
                # Get start position of COLON and expression
                colon_start = colon.symbol.start
                expr_start = expr_token.start.start
                if expr_start < colon_start:
                    # [start:]
                    start = self.visit_expression(exprs[0])
                else:
                    # [:end]
                    end = self.visit_expression(exprs[0])
            else:
                # [start:end]
                start = self.visit_expression(exprs[0])
                end = self.visit_expression(exprs[1])

            return SliceExpr(object=base, start=start, end=end)
        else:
            # Index: obj[i] or obj[i, j]
            exprs = ctx.expression()
            indices = [self.visit_expression(e) for e in exprs]
            return IndexExpr(base, indices)

    def visit_argument_list(self, ctx: CoexParser.ArgumentListContext) -> Tuple[PyList[Expr], Dict[str, Expr]]:
        """Visit an argument list, returning (positional_args, named_args)"""
        positional_args = []
        named_args = {}
        
        for arg in ctx.argument():
            expr = self.visit_expression(arg.expression())
            if arg.IDENTIFIER():
                # Named argument: name: expr
                name = arg.IDENTIFIER().getText()
                named_args[name] = expr
            else:
                # Positional argument
                positional_args.append(expr)
        
        return positional_args, named_args
    
    def visit_primary_expr(self, ctx: CoexParser.PrimaryExprContext) -> Expr:
        """Visit a primary expression"""
        if ctx.literal():
            return self.visit_literal(ctx.literal())
        elif ctx.IDENTIFIER():
            name = ctx.IDENTIFIER().getText()
            # Check for generic type instantiation: List<int>
            if ctx.genericArgs():
                type_args = self.visit_generic_args(ctx.genericArgs())
                return Identifier(name, type_args)
            return Identifier(name)
        elif ctx.JSON_TYPE():
            # 'json' keyword used as identifier for static method calls like json.parse()
            return Identifier("json")
        elif ctx.SELF():
            return SelfExpr()
        elif ctx.LPAREN():
            expr = ctx.expression()
            if expr:
                # Parenthesized expression - single expression, not a list
                return self.visit_expression(expr)
            elif ctx.tupleElements():
                # Tuple literal
                return self.visit_tuple_elements(ctx.tupleElements())
        elif ctx.listLiteral():
            return self.visit_list_literal(ctx.listLiteral())
        elif ctx.mapLiteral():
            return self.visit_map_literal(ctx.mapLiteral())
        elif ctx.lambdaExpr():
            return self.visit_lambda_expr(ctx.lambdaExpr())
        elif hasattr(CoexParser, 'LlvmIrExprContext') and ctx.llvmIrExpr():
            return self.visit_llvm_ir_expr(ctx.llvmIrExpr())

        return IntLiteral(0)  # fallback
    
    def visit_literal(self, ctx: CoexParser.LiteralContext) -> Expr:
        """Visit a literal"""
        if ctx.INTEGER_LITERAL():
            return IntLiteral(int(ctx.INTEGER_LITERAL().getText()))
        elif ctx.FLOAT_LITERAL():
            return FloatLiteral(float(ctx.FLOAT_LITERAL().getText()))
        elif ctx.HEX_LITERAL():
            return IntLiteral(int(ctx.HEX_LITERAL().getText(), 16))
        elif ctx.BINARY_LITERAL():
            return IntLiteral(int(ctx.BINARY_LITERAL().getText(), 2))
        elif ctx.stringLiteral():
            text = ctx.stringLiteral().STRING_LITERAL().getText()[1:-1]
            # Handle escape sequences
            text = text.replace('\\n', '\n').replace('\\t', '\t').replace('\\r', '\r')
            text = text.replace('\\\\', '\\').replace('\\"', '"').replace("\\'", "'")
            return StringLiteral(text)
        elif ctx.TRUE():
            return BoolLiteral(True)
        elif ctx.FALSE():
            return BoolLiteral(False)
        elif ctx.NIL():
            return NilLiteral()
        
        return IntLiteral(0)
    
    def visit_list_literal(self, ctx: CoexParser.ListLiteralContext):
        """Visit a list literal or list comprehension"""
        # Check if this is a comprehension
        if ctx.comprehensionClauses():
            value = self.visit_expression(ctx.expression())
            clauses = self.visit_comprehension_clauses(ctx.comprehensionClauses())
            return ListComprehension(value, clauses)
        
        # Regular list literal
        elements = []
        if ctx.expressionList():
            for expr in ctx.expressionList().expression():
                elements.append(self.visit_expression(expr))
        return ListExpr(elements)
    
    def visit_map_literal(self, ctx: CoexParser.MapLiteralContext):
        """Visit a map literal, set literal, JSON object, or comprehension"""
        # Check for comprehensions first
        if ctx.comprehensionClauses():
            clauses = self.visit_comprehension_clauses(ctx.comprehensionClauses())
            expressions = ctx.expression()

            if len(expressions) == 2:
                # Map comprehension: {key: value for ...}
                key = self.visit_expression(expressions[0])
                value = self.visit_expression(expressions[1])
                return MapComprehension(key, value, clauses)
            else:
                # Set comprehension: {expr for ...}
                value = self.visit_expression(expressions[0])
                return SetComprehension(value, clauses)

        # Map/JSON literal: {key: value, ...}
        if ctx.mapEntryList():
            json_entries = []  # (str, Expr) for JSON
            map_entries = []   # (Expr, Expr) for Map
            has_json_key = False
            has_map_key = False

            for entry in ctx.mapEntryList().mapEntry():
                # Check which alternative matched in mapEntry:
                # 1. jsonKey COLON expression -> JSON-style bare identifier/keyword key
                # 2. stringLiteral COLON expression -> Map-style string literal key
                # 3. LPAREN expression RPAREN COLON expression -> Map-style parenthesized key
                # 4. expression COLON expression -> Map-style expression key

                if entry.jsonKey():
                    # JSON-style: bare identifier or keyword key (e.g., {name: "Alice", type: "window"})
                    key_str = entry.jsonKey().getText()
                    value = self.visit_expression(entry.expression(0))
                    json_entries.append((key_str, value))
                    has_json_key = True
                elif entry.stringLiteral():
                    # Map-style: string literal key (e.g., {"hello": 1})
                    # This creates a Map with string keys, not a JSON object
                    string_ctx = entry.stringLiteral()
                    key_str = self._get_string_value(string_ctx)
                    key = StringLiteral(key_str)
                    value = self.visit_expression(entry.expression(0))
                    map_entries.append((key, value))
                    has_map_key = True
                elif entry.LPAREN():
                    # Map-style: parenthesized variable key {(x): value}
                    key = self.visit_expression(entry.expression(0))
                    value = self.visit_expression(entry.expression(1))
                    map_entries.append((key, value))
                    has_map_key = True
                else:
                    # Map-style: expression key {1: value}
                    key = self.visit_expression(entry.expression(0))
                    value = self.visit_expression(entry.expression(1))
                    map_entries.append((key, value))
                    has_map_key = True

            if has_json_key and has_map_key:
                raise SyntaxError("Cannot mix JSON-style (bare identifier) and Map-style (expression) keys in same literal")

            if has_json_key:
                return JsonObjectExpr(json_entries)
            else:
                return MapExpr(map_entries)

        # Set literal: {a, b, c}
        if ctx.expressionList():
            elements = []
            for expr in ctx.expressionList().expression():
                elements.append(self.visit_expression(expr))
            return SetExpr(elements)

        # Empty braces: {} -> empty JSON object
        return JsonObjectExpr([])
    
    def visit_comprehension_clauses(self, ctx) -> PyList[ComprehensionClause]:
        """Visit comprehension clauses"""
        clauses = []
        for clause_ctx in ctx.comprehensionClause():
            pattern = self.visit_binding_pattern(clause_ctx.bindingPattern())
            iterable = self.visit_expression(clause_ctx.expression(0))
            condition = None
            if len(clause_ctx.expression()) > 1:
                condition = self.visit_expression(clause_ctx.expression(1))
            clauses.append(ComprehensionClause(pattern, iterable, condition))
        return clauses
    
    def visit_tuple_elements(self, ctx: CoexParser.TupleElementsContext) -> TupleExpr:
        """Visit tuple elements"""
        elements = []
        for elem in ctx.tupleElement():
            name = None
            if elem.IDENTIFIER():
                name = elem.IDENTIFIER().getText()
            expr = self.visit_expression(elem.expression())
            elements.append((name, expr))
        return TupleExpr(elements)
    
    def visit_lambda_expr(self, ctx: CoexParser.LambdaExprContext) -> LambdaExpr:
        """Visit a lambda expression"""
        kind_text = ctx.functionKind().getText() if ctx.functionKind() else "formula"
        kind = {"formula": FunctionKind.FORMULA, "task": FunctionKind.TASK, "thread": FunctionKind.THREAD}.get(kind_text, FunctionKind.FORMULA)
        
        params = []
        if ctx.parameterList():
            params = self.visit_param_list(ctx.parameterList())
        
        body = self.visit_expression(ctx.expression())
        
        return LambdaExpr(kind, params, body)
