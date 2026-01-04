"""
Function Code Generation for Coex.

This module handles:
- Function declarations and body generation
- Extern/FFI function handling
- Generic function monomorphization
- Type method declaration and generation
- Lambda expression compilation
"""
from llvmlite import ir
from typing import TYPE_CHECKING, Optional, Dict
from typing import List as PyList

from ast_nodes import (
    FunctionDecl, FunctionKind, Type, Stmt, Expr, VarDecl, IfStmt, ForStmt,
    ForAssignStmt, WhileStmt, MatchStmt, TupleDestructureStmt, CallExpr,
    Identifier, TupleType, TypeDecl, PrimitiveType, MemberExpr, MethodCallExpr,
    Assignment, ReturnStmt, BinaryExpr, UnaryExpr, TernaryExpr, IndexExpr,
    TupleExpr, ListExpr, MapExpr, SetExpr, LambdaExpr, SelectStmt, WithinStmt,
    SelfExpr
)

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class FunctionGenerator:
    """Generates function-related LLVM IR for the Coex compiler."""

    def __init__(self, cg: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = cg

    # ========================================================================
    # Function Declaration
    # ========================================================================

    def declare_function(self, func: FunctionDecl):
        """Declare a function (for forward references)"""
        cg = self.cg

        # If generic, store as template
        if func.type_params:
            cg.generic_functions[func.name] = func
            return

        # Special handling for main() with parameters
        if func.name == "main" and func.params:
            self.declare_main_with_params(func)
            return

        # Handle extern functions (FFI to C)
        if func.kind == FunctionKind.EXTERN:
            self.declare_extern_function(func)
            return

        # Build parameter types
        param_types = []
        for param in func.params:
            param_types.append(cg._get_llvm_type(param.type_annotation))

        # Build return type
        if func.return_type:
            return_type = cg._get_llvm_type(func.return_type)
        else:
            return_type = ir.VoidType()

        # Create function
        func_type = ir.FunctionType(return_type, param_types)
        llvm_func = ir.Function(cg.module, func_type, name=func.name)
        cg.functions[func.name] = llvm_func

    def declare_extern_function(self, func: FunctionDecl):
        """Declare an extern function (external C linkage, no body).

        Extern functions are FFI boundaries to C code. They use C ABI types
        and are declared with external linkage so the linker can resolve them.
        """
        cg = self.cg

        # Track this extern function for calling hierarchy validation
        cg.extern_function_decls = getattr(cg, 'extern_function_decls', {})
        cg.extern_function_decls[func.name] = func

        # Build C ABI parameter types
        c_param_types = []
        for param in func.params:
            c_param_types.append(cg._get_c_type(param.type_annotation))

        # Build C ABI return type
        if func.return_type:
            c_return_type = cg._get_c_type(func.return_type)
        else:
            c_return_type = ir.VoidType()

        # Check if already declared in the module
        if func.name in cg.module.globals:
            # Use the existing declaration
            cg.functions[func.name] = cg.module.globals[func.name]
            return

        # Declare the external function
        func_type = ir.FunctionType(c_return_type, c_param_types)
        llvm_func = ir.Function(cg.module, func_type, name=func.name)
        llvm_func.linkage = 'external'
        cg.functions[func.name] = llvm_func

    def generate_extern_call(self, name: str, args: list, func_decl: FunctionDecl) -> ir.Value:
        """Generate a call to an extern function with C ABI type conversion.

        Extern functions can only be called from func (not formula or task).
        Arguments are converted from Coex types to C ABI types, and return
        values are converted back.
        """
        cg = self.cg

        # Validate calling hierarchy: only func can call extern
        if hasattr(cg, 'current_function') and cg.current_function:
            caller_kind = cg.current_function.kind
            if caller_kind == FunctionKind.FORMULA:
                raise RuntimeError(
                    f"Cannot call extern function '{name}' from formula "
                    f"'{cg.current_function.name}'. Extern functions can only "
                    f"be called from func."
                )
            elif caller_kind == FunctionKind.TASK:
                raise RuntimeError(
                    f"Cannot call extern function '{name}' from task "
                    f"'{cg.current_function.name}'. Extern functions can only "
                    f"be called from func."
                )

        llvm_func = cg.functions[name]

        # Convert Coex arguments to C ABI types
        c_args = []
        for i, arg in enumerate(args):
            arg_val = cg._generate_expression(arg)
            if i < len(func_decl.params):
                c_arg = cg._convert_to_c_type(arg_val, func_decl.params[i].type_annotation)
            else:
                c_arg = arg_val
            c_args.append(c_arg)

        # Call the extern function
        if isinstance(llvm_func.return_value.type, ir.VoidType):
            cg.builder.call(llvm_func, c_args)
            return ir.Constant(ir.IntType(64), 0)
        else:
            c_result = cg.builder.call(llvm_func, c_args)
            # Convert C result back to Coex type
            if func_decl.return_type:
                return cg._convert_from_c_type(c_result, func_decl.return_type)
            return c_result

    # ========================================================================
    # Main Function Special Handling
    # ========================================================================

    def declare_main_with_params(self, func: FunctionDecl):
        """Handle main() function with special parameters (args, stdin, stdout, stderr).

        Supported signatures:
        1. func main(args: [string]) -> int
        2. func main(stdin: posix, stdout: posix, stderr: posix) -> int
        3. func main(args: [string], stdin: posix, stdout: posix, stderr: posix) -> int
        """
        cg = self.cg
        i64 = ir.IntType(64)
        i32 = ir.IntType(32)
        i8_ptr = ir.IntType(8).as_pointer()

        # Detect which signature is being used
        has_args = False
        has_stdio = False

        for param in func.params:
            if param.name == "args":
                has_args = True
            elif param.name in ("stdin", "stdout", "stderr"):
                has_stdio = True

        # Build parameter types for user's main (coex_main_impl)
        impl_param_types = []
        if has_args:
            impl_param_types.append(cg.list_struct.as_pointer())  # [string] is a List*
        if has_stdio:
            impl_param_types.append(cg.posix_struct.as_pointer())  # stdin: posix*
            impl_param_types.append(cg.posix_struct.as_pointer())  # stdout: posix*
            impl_param_types.append(cg.posix_struct.as_pointer())  # stderr: posix*

        # Create user's main as coex_main_impl
        impl_func_type = ir.FunctionType(i64, impl_param_types)
        impl_func = ir.Function(cg.module, impl_func_type, name="coex_main_impl")
        cg.functions["main"] = impl_func  # Store as "main" so generate_function finds it

        # Store signature info for later use
        cg.main_has_args = has_args
        cg.main_has_stdio = has_stdio

        # Create C main wrapper: int main(int argc, char** argv)
        c_main_type = ir.FunctionType(i32, [i32, i8_ptr.as_pointer()])
        c_main = ir.Function(cg.module, c_main_type, name="main")
        c_main.args[0].name = "argc"
        c_main.args[1].name = "argv"

        # Implement the C main wrapper
        entry = c_main.append_basic_block("entry")
        builder = ir.IRBuilder(entry)

        # Initialize GC before building args array (which uses GC allocations)
        if cg.gc is not None:
            builder.call(cg.gc.gc_init, [])

        call_args = []

        if has_args:
            # Convert argc/argv to [string]
            argc = c_main.args[0]
            argv = c_main.args[1]

            # Create new list for strings (elem_size = 8 for pointers)
            elem_size = ir.Constant(i64, 8)
            args_list = builder.call(cg.list_new, [elem_size])

            # Store in alloca for list_append (which returns new list)
            args_alloca = builder.alloca(cg.list_struct.as_pointer(), name="args_list")
            builder.store(args_list, args_alloca)

            # Loop through argv and convert each to string
            idx_alloca = builder.alloca(i32, name="arg_idx")
            builder.store(ir.Constant(i32, 0), idx_alloca)

            cond_block = c_main.append_basic_block("args_cond")
            body_block = c_main.append_basic_block("args_body")
            end_block = c_main.append_basic_block("args_end")

            builder.branch(cond_block)

            # Condition: idx < argc
            builder.position_at_end(cond_block)
            idx = builder.load(idx_alloca)
            cond = builder.icmp_signed("<", idx, argc)
            builder.cbranch(cond, body_block, end_block)

            # Body: convert argv[idx] to string, append to list
            builder.position_at_end(body_block)
            idx = builder.load(idx_alloca)
            idx_64 = builder.sext(idx, i64)

            # Get argv[idx]
            arg_ptr_ptr = builder.gep(argv, [idx_64])
            c_str = builder.load(arg_ptr_ptr)

            # Convert C string to Coex string using string_from_literal
            coex_string = builder.call(cg.string_from_literal, [c_str])

            # Append to list: we need to store the string pointer and pass its address
            str_alloca = builder.alloca(cg.string_struct.as_pointer(), name="str_temp")
            builder.store(coex_string, str_alloca)

            current_list = builder.load(args_alloca)
            new_list = builder.call(cg.list_append, [current_list,
                                                      builder.bitcast(str_alloca, i8_ptr),
                                                      elem_size])
            builder.store(new_list, args_alloca)

            # Increment index
            next_idx = builder.add(idx, ir.Constant(i32, 1))
            builder.store(next_idx, idx_alloca)
            builder.branch(cond_block)

            # End - get final list
            builder.position_at_end(end_block)
            final_args_list = builder.load(args_alloca)
            call_args.append(final_args_list)

        if has_stdio:
            # Create posix handles for stdin (fd=0), stdout (fd=1), stderr (fd=2)
            for fd_num, name in [(0, "stdin_posix"), (1, "stdout_posix"), (2, "stderr_posix")]:
                # Allocate posix struct
                posix_alloca = builder.alloca(cg.posix_struct, name=name)

                # Set fd field
                fd_ptr = builder.gep(posix_alloca, [ir.Constant(i32, 0), ir.Constant(i32, 0)], inbounds=True)
                builder.store(ir.Constant(i32, fd_num), fd_ptr)

                call_args.append(posix_alloca)

        # Call user's main implementation
        result = builder.call(impl_func, call_args)

        # Truncate i64 to i32 for C return
        result_32 = builder.trunc(result, i32)
        builder.ret(result_32)

    # ========================================================================
    # Core Function Generation
    # ========================================================================

    def collect_heap_vars_from_body(self, stmts: PyList[Stmt]) -> PyList[str]:
        """Collect names of heap-typed variable declarations from function body.

        Recursively traverses the AST to find all VarDecl statements with heap types.
        Returns a list of variable names that need GC root tracking.
        """
        cg = self.cg
        heap_vars = []

        def visit_stmts(statements):
            for stmt in statements:
                if isinstance(stmt, VarDecl):
                    # Check explicit type annotation first
                    if stmt.type_annotation and cg._is_heap_type(stmt.type_annotation):
                        heap_vars.append(stmt.name)
                    # Also check inferred type from initializer expression
                    elif stmt.initializer and not stmt.type_annotation:
                        inferred_type = cg._infer_type_from_expr(stmt.initializer)
                        if cg._is_heap_type(inferred_type):
                            heap_vars.append(stmt.name)
                # Recurse into nested blocks
                if isinstance(stmt, IfStmt):
                    visit_stmts(stmt.then_body)
                    for _, elif_body in stmt.else_if_clauses:
                        visit_stmts(elif_body)
                    if stmt.else_body:
                        visit_stmts(stmt.else_body)
                elif isinstance(stmt, (ForStmt, ForAssignStmt)):
                    visit_stmts(stmt.body)
                elif isinstance(stmt, WhileStmt):
                    visit_stmts(stmt.body)
                elif isinstance(stmt, MatchStmt):
                    for arm in stmt.arms:
                        visit_stmts(arm.body)
                elif isinstance(stmt, TupleDestructureStmt):
                    # Check if value is a function call with a tuple return type
                    if isinstance(stmt.value, CallExpr) and isinstance(stmt.value.callee, Identifier):
                        func_name = stmt.value.callee.name
                        if func_name in cg.func_decls:
                            func_decl = cg.func_decls[func_name]
                            if func_decl.return_type and isinstance(func_decl.return_type, TupleType):
                                # Check which tuple elements are heap types
                                for i, name in enumerate(stmt.names):
                                    if i < len(func_decl.return_type.elements):
                                        _, elem_type = func_decl.return_type.elements[i]
                                        if cg._is_heap_type(elem_type):
                                            heap_vars.append(name)

        visit_stmts(stmts)
        return heap_vars

    def generate_function(self, func: FunctionDecl):
        """Generate a function body"""
        cg = self.cg

        # Skip generic functions (they're generated on demand)
        if func.type_params:
            return

        # Skip extern functions (they have no body, external linkage only)
        if func.kind == FunctionKind.EXTERN:
            return

        llvm_func = cg.functions[func.name]

        # Create entry block
        entry = llvm_func.append_basic_block(name="entry")
        cg.builder = ir.IRBuilder(entry)

        # Initialize GC at start of main function
        # Skip if main has params (args/stdio) - gc_init is called in the C main wrapper
        if func.name == "main" and cg.gc is not None:
            if not getattr(cg, 'main_has_args', False) and not getattr(cg, 'main_has_stdio', False):
                cg.gc.inject_gc_init(cg.builder)

        # Clear locals and moved variables for this function scope
        cg.locals = {}
        cg._reset_function_scope()
        cg.moved_vars = set()
        cg.current_function = func

        # ====================================================================
        # GC Shadow Stack Integration
        # ====================================================================
        # Count heap pointer parameters and locals for GC root tracking
        heap_var_names = []  # List of (var_name) in order

        # Check parameters for heap types
        for param in func.params:
            if param.type_annotation and cg._is_heap_type(param.type_annotation):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self.collect_heap_vars_from_body(func.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables and GC is enabled
        cg.gc_frame = None
        cg.gc_roots = None
        cg.gc_root_indices = {}

        if heap_var_names and cg.gc is not None:
            num_roots = len(heap_var_names)
            cg.gc_roots = cg.gc.create_frame_roots(cg.builder, num_roots)
            cg.gc_frame = cg.gc.push_frame(cg.builder, num_roots, cg.gc_roots)

            # Store mapping of var_name -> root_index
            cg.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}
        # ====================================================================

        # GC Safe-point check: trigger GC if allocation threshold exceeded
        # This is safe because we're at function entry with no intermediate allocations
        if cg.gc is not None and func.name != "main":
            cg.gc.inject_safepoint(cg.builder)

        # Allocate parameters with value semantics (deep copy heap-allocated types)
        for i, param in enumerate(func.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name

            # Track Coex AST type for method calls on collections (e.g., list.get())
            if param.type_annotation:
                cg.var_coex_types[param.name] = param.type_annotation

            # Most heap types don't need copying (immutable collections)
            # UDTs with mutable fields still need copying
            param_value = llvm_param
            if cg._needs_parameter_copy(param.type_annotation):
                param_value = cg._generate_deep_copy(llvm_param, param.type_annotation)

            # Allocate on stack and store the value
            alloca = cg.builder.alloca(llvm_param.type, name=param.name)
            cg.builder.store(param_value, alloca)
            cg.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in cg.gc_root_indices and cg.gc is not None:
                root_idx = cg.gc_root_indices[param.name]
                cg.gc.set_root(cg.builder, cg.gc_roots, root_idx, param_value)

        # Generate body
        for stmt in func.body:
            cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

        # Add implicit return if needed
        if not cg.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            if isinstance(llvm_func.return_value.type, ir.VoidType):
                cg.builder.ret_void()
            else:
                cg.builder.ret(ir.Constant(llvm_func.return_value.type, 0))

        # Clear GC state for this function
        cg.gc_frame = None
        cg.gc_roots = None
        cg.gc_root_indices = {}
        cg.current_function = None

    # ========================================================================
    # Generic Function Monomorphization
    # ========================================================================

    def monomorphize_function(self, name: str, type_args: PyList[Type]) -> str:
        """Monomorphize a generic function with concrete type arguments"""
        cg = self.cg

        if name not in cg.generic_functions:
            return name  # Not a generic function

        mangled_name = cg._mangle_generic_name(name, type_args)

        # Already monomorphized?
        if mangled_name in cg.functions:
            return mangled_name

        # Get the generic function declaration
        func_decl = cg.generic_functions[name]

        # Check trait bounds
        for param, arg in zip(func_decl.type_params, type_args):
            for bound in param.bounds:
                type_name = cg._type_to_string(arg)
                if not cg._check_trait_bound(type_name, bound):
                    # Trait bound not satisfied - for now, continue anyway
                    # In a full implementation, this would raise an error
                    pass

        # Set up type substitutions
        old_subs = cg.type_substitutions.copy()
        cg.type_substitutions = {}
        for param, arg in zip(func_decl.type_params, type_args):
            cg.type_substitutions[param.name] = arg

        # Build parameter types
        param_types = []
        for param in func_decl.params:
            param_type = cg._substitute_type(param.type_annotation)
            param_types.append(cg._get_llvm_type(param_type))

        # Build return type
        if func_decl.return_type:
            return_type = cg._substitute_type(func_decl.return_type)
            llvm_ret = cg._get_llvm_type(return_type)
        else:
            llvm_ret = ir.VoidType()

        # Create function
        func_type = ir.FunctionType(llvm_ret, param_types)
        llvm_func = ir.Function(cg.module, func_type, name=mangled_name)
        cg.functions[mangled_name] = llvm_func

        # Generate function body
        entry = llvm_func.append_basic_block(name="entry")
        old_builder = cg.builder
        cg.builder = ir.IRBuilder(entry)

        old_locals = cg.locals
        cg.locals = {}
        cg._reset_function_scope()
        old_current_function = cg.current_function
        cg.current_function = func_decl

        # Save and initialize GC state for this monomorphized function
        old_gc_frame = getattr(cg, 'gc_frame', None)
        old_gc_roots = getattr(cg, 'gc_roots', None)
        old_gc_root_indices = getattr(cg, 'gc_root_indices', {})

        cg.gc_frame = None
        cg.gc_roots = None
        cg.gc_root_indices = {}

        # Collect heap variables for GC root tracking
        heap_var_names = []

        # Check parameters for heap types (using substituted types)
        for param in func_decl.params:
            param_type = cg._substitute_type(param.type_annotation)
            if param_type and cg._is_heap_type(param_type):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self.collect_heap_vars_from_body(func_decl.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables
        if heap_var_names and cg.gc is not None:
            num_roots = len(heap_var_names)
            cg.gc_roots = cg.gc.create_frame_roots(cg.builder, num_roots)
            cg.gc_frame = cg.gc.push_frame(cg.builder, num_roots, cg.gc_roots)
            cg.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}

        # Allocate parameters with value semantics (deep copy heap-allocated types)
        for i, param in enumerate(func_decl.params):
            llvm_param = llvm_func.args[i]
            llvm_param.name = param.name

            # Get the substituted type for this parameter
            param_type = cg._substitute_type(param.type_annotation)

            # Most heap types don't need copying (immutable collections)
            # UDTs with mutable fields still need copying
            param_value = llvm_param
            if cg._needs_parameter_copy(param_type):
                param_value = cg._generate_deep_copy(llvm_param, param_type)

            alloca = cg.builder.alloca(llvm_param.type, name=param.name)
            cg.builder.store(param_value, alloca)
            cg.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in cg.gc_root_indices and cg.gc is not None:
                cg.gc.set_root(cg.builder, cg.gc_roots, cg.gc_root_indices[param.name], param_value)

        # Generate body
        for stmt in func_decl.body:
            cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

        # Add implicit return
        if not cg.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            if isinstance(llvm_ret, ir.VoidType):
                cg.builder.ret_void()
            else:
                cg.builder.ret(ir.Constant(llvm_ret, 0))

        # Restore state
        cg.builder = old_builder
        cg.locals = old_locals
        cg.current_function = old_current_function
        cg.type_substitutions = old_subs
        cg.gc_frame = old_gc_frame
        cg.gc_roots = old_gc_roots
        cg.gc_root_indices = old_gc_root_indices

        return mangled_name

    # ========================================================================
    # Type Method Generation
    # ========================================================================

    def method_uses_self(self, method) -> bool:
        """Check if a method body references 'self' or implicit field access.

        Methods that don't use self are static methods and don't get a self parameter.
        """
        def check_expr(expr) -> bool:
            """Recursively check if expression uses self"""
            if expr is None:
                return False
            if isinstance(expr, Identifier):
                return expr.name == "self"
            if isinstance(expr, SelfExpr):
                return True
            if isinstance(expr, MemberExpr):
                # Check if accessing self.field
                if isinstance(expr.object, SelfExpr):
                    return True
                if isinstance(expr.object, Identifier) and expr.object.name == "self":
                    return True
                return check_expr(expr.object)
            if isinstance(expr, MethodCallExpr):
                if check_expr(expr.object):
                    return True
                return any(check_expr(a) for a in expr.args)
            if isinstance(expr, CallExpr):
                if check_expr(expr.callee):
                    return True
                return any(check_expr(a) for a in expr.args)
            if isinstance(expr, BinaryExpr):
                return check_expr(expr.left) or check_expr(expr.right)
            if isinstance(expr, UnaryExpr):
                return check_expr(expr.operand)
            if isinstance(expr, TernaryExpr):
                return check_expr(expr.condition) or check_expr(expr.then_expr) or check_expr(expr.else_expr)
            if isinstance(expr, IndexExpr):
                return check_expr(expr.object) or check_expr(expr.index)
            if isinstance(expr, TupleExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, ListExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, MapExpr):
                return any(check_expr(k) or check_expr(v) for k, v in expr.pairs)
            if isinstance(expr, SetExpr):
                return any(check_expr(e) for e in expr.elements)
            if isinstance(expr, LambdaExpr):
                return check_expr(expr.body)
            return False

        def check_stmt(stmt) -> bool:
            """Recursively check if statement uses self"""
            if isinstance(stmt, ReturnStmt):
                return check_expr(stmt.value) if stmt.value else False
            if isinstance(stmt, VarDecl):
                return check_expr(stmt.initializer) if stmt.initializer else False
            if isinstance(stmt, Assignment):
                return check_expr(stmt.target) or check_expr(stmt.value)
            if isinstance(stmt, IfStmt):
                if check_expr(stmt.condition):
                    return True
                if any(check_stmt(s) for s in stmt.then_body):
                    return True
                for cond, body in stmt.else_if_clauses:
                    if check_expr(cond):
                        return True
                    if any(check_stmt(s) for s in body):
                        return True
                if stmt.else_body and any(check_stmt(s) for s in stmt.else_body):
                    return True
                return False
            if isinstance(stmt, WhileStmt):
                return check_expr(stmt.condition) or any(check_stmt(s) for s in stmt.body)
            if isinstance(stmt, (ForStmt, ForAssignStmt)):
                return check_expr(stmt.iterable) or any(check_stmt(s) for s in stmt.body)
            if isinstance(stmt, MatchStmt):
                if check_expr(stmt.value):
                    return True
                for arm in stmt.arms:
                    if any(check_stmt(s) for s in arm.body):
                        return True
                return False
            if isinstance(stmt, SelectStmt):
                for arm in stmt.arms:
                    if any(check_stmt(s) for s in arm.body):
                        return True
                return False
            if isinstance(stmt, WithinStmt):
                return check_expr(stmt.duration) or any(check_stmt(s) for s in stmt.body)
            # Expression statements
            if hasattr(stmt, 'expr'):
                return check_expr(stmt.expr)
            if isinstance(stmt, CallExpr):
                return check_expr(stmt)
            if isinstance(stmt, MethodCallExpr):
                return check_expr(stmt)
            return False

        return any(check_stmt(s) for s in method.body)

    def declare_type_methods(self, type_decl: TypeDecl):
        """Declare all methods for a type"""
        cg = self.cg

        # Skip generic types - methods are declared during monomorphization
        if type_decl.type_params:
            return

        struct_type = cg.type_registry[type_decl.name]
        self_ptr_type = struct_type.as_pointer()

        for method in type_decl.methods:
            # Mangle name: TypeName_methodName
            mangled_name = f"{type_decl.name}_{method.name}"

            # Check if this is a static method (doesn't use self)
            is_static = not self.method_uses_self(method)
            cg.static_methods[mangled_name] = is_static

            # Build parameter types
            param_types = []
            if not is_static:
                param_types.append(self_ptr_type)  # self pointer for instance methods
            for param in method.params:
                param_types.append(cg._get_llvm_type(param.type_annotation))

            # Build return type
            if method.return_type:
                return_type = cg._get_llvm_type(method.return_type)
            else:
                return_type = ir.VoidType()

            # Create function
            func_type = ir.FunctionType(return_type, param_types)
            llvm_func = ir.Function(cg.module, func_type, name=mangled_name)

            # Name the self parameter for instance methods
            if not is_static and len(llvm_func.args) > 0:
                llvm_func.args[0].name = "self"

            cg.functions[mangled_name] = llvm_func
            cg.type_methods[type_decl.name][method.name] = mangled_name

    def generate_type_methods(self, type_decl: TypeDecl):
        """Generate method bodies for a type"""
        cg = self.cg

        # Skip generic types - methods are generated during monomorphization
        if type_decl.type_params:
            return

        struct_type = cg.type_registry[type_decl.name]

        for method in type_decl.methods:
            mangled_name = cg.type_methods[type_decl.name][method.name]
            llvm_func = cg.functions[mangled_name]

            # Check if this is a static method
            is_static = cg.static_methods.get(mangled_name, False)

            # Create entry block
            entry = llvm_func.append_basic_block(name="entry")
            cg.builder = ir.IRBuilder(entry)

            # Clear locals and set context
            cg.locals = {}
            cg._reset_function_scope()
            cg.current_function = method
            cg.current_type = type_decl.name if not is_static else None

            if is_static:
                # Static method - no self parameter
                # Allocate parameters directly (no offset for self)
                for i, param in enumerate(method.params):
                    llvm_param = llvm_func.args[i]
                    llvm_param.name = param.name

                    alloca = cg.builder.alloca(llvm_param.type, name=param.name)
                    cg.builder.store(llvm_param, alloca)
                    cg.locals[param.name] = alloca
            else:
                # Instance method - has self as first parameter
                # Store self pointer
                self_alloca = cg.builder.alloca(llvm_func.args[0].type, name="self")
                cg.builder.store(llvm_func.args[0], self_alloca)
                cg.locals["self"] = self_alloca

                # Also make fields accessible directly by name
                cg._setup_field_aliases(type_decl.name, self_alloca)

                # Allocate other parameters
                for i, param in enumerate(method.params):
                    llvm_param = llvm_func.args[i + 1]  # +1 for self
                    llvm_param.name = param.name

                    alloca = cg.builder.alloca(llvm_param.type, name=param.name)
                    cg.builder.store(llvm_param, alloca)
                    cg.locals[param.name] = alloca

            # Generate body
            for stmt in method.body:
                cg._generate_statement(stmt)
                if cg.builder.block.is_terminated:
                    break

            # Add implicit return if needed
            if not cg.builder.block.is_terminated:
                if isinstance(llvm_func.return_value.type, ir.VoidType):
                    cg.builder.ret_void()
                else:
                    cg.builder.ret(ir.Constant(llvm_func.return_value.type, 0))

            cg.current_type = None
            cg.current_function = None

    def declare_type_methods_monomorphized(self, mangled_type_name: str, type_decl: TypeDecl):
        """Declare methods for a monomorphized type"""
        cg = self.cg
        struct_type = cg.type_registry[mangled_type_name]
        self_ptr_type = struct_type.as_pointer()

        # Save current substitutions (already set up by caller)
        for method in type_decl.methods:
            # Mangle method name with type name
            mangled_method = f"{mangled_type_name}_{method.name}"

            # Build parameter types (self is implicit first parameter)
            param_types = [self_ptr_type]
            for param in method.params:
                param_type = cg._substitute_type(param.type_annotation)
                param_types.append(cg._get_llvm_type(param_type))

            # Build return type
            if method.return_type:
                return_type = cg._substitute_type(method.return_type)
                llvm_ret = cg._get_llvm_type(return_type)
            else:
                llvm_ret = ir.VoidType()

            # Create function
            func_type = ir.FunctionType(llvm_ret, param_types)
            llvm_func = ir.Function(cg.module, func_type, name=mangled_method)
            llvm_func.args[0].name = "self"

            cg.functions[mangled_method] = llvm_func
            cg.type_methods[mangled_type_name][method.name] = mangled_method

        # Generate method bodies
        for method in type_decl.methods:
            mangled_method = cg.type_methods[mangled_type_name][method.name]
            self.generate_method_body(mangled_type_name, mangled_method, method)

    def generate_method_body(self, type_name: str, mangled_method: str, method: FunctionDecl):
        """Generate body for a method"""
        cg = self.cg
        llvm_func = cg.functions[mangled_method]

        # Save current state
        old_builder = cg.builder
        old_locals = cg.locals
        old_current_function = cg.current_function
        old_current_type = cg.current_type
        old_gc_frame = getattr(cg, 'gc_frame', None)
        old_gc_roots = getattr(cg, 'gc_roots', None)
        old_gc_root_indices = getattr(cg, 'gc_root_indices', {})

        entry = llvm_func.append_basic_block(name="entry")
        cg.builder = ir.IRBuilder(entry)

        cg.locals = {}
        cg._reset_function_scope()
        cg.current_function = method
        cg.current_type = type_name

        # Initialize GC state for this method
        cg.gc_frame = None
        cg.gc_roots = None
        cg.gc_root_indices = {}

        # Collect heap variables for GC root tracking
        heap_var_names = []

        # Check parameters for heap types (skip 'self')
        for param in method.params:
            if param.type_annotation and cg._is_heap_type(param.type_annotation):
                heap_var_names.append(param.name)

        # Analyze body for heap-typed var declarations
        body_heap_vars = self.collect_heap_vars_from_body(method.body)
        heap_var_names.extend(body_heap_vars)

        # Create shadow stack frame if we have heap variables
        if heap_var_names and cg.gc is not None:
            num_roots = len(heap_var_names)
            cg.gc_roots = cg.gc.create_frame_roots(cg.builder, num_roots)
            cg.gc_frame = cg.gc.push_frame(cg.builder, num_roots, cg.gc_roots)
            cg.gc_root_indices = {name: i for i, name in enumerate(heap_var_names)}

        # GC Safe-point check: trigger GC if allocation threshold exceeded
        if cg.gc is not None:
            cg.gc.inject_safepoint(cg.builder)

        # Store self pointer
        self_alloca = cg.builder.alloca(llvm_func.args[0].type, name="self")
        cg.builder.store(llvm_func.args[0], self_alloca)
        cg.locals["self"] = self_alloca

        # Allocate other parameters
        for i, param in enumerate(method.params):
            llvm_param = llvm_func.args[i + 1]
            llvm_param.name = param.name

            alloca = cg.builder.alloca(llvm_param.type, name=param.name)
            cg.builder.store(llvm_param, alloca)
            cg.locals[param.name] = alloca

            # Register parameter as GC root if it's a heap type
            if param.name in cg.gc_root_indices and cg.gc is not None:
                cg.gc.set_root(cg.builder, cg.gc_roots, cg.gc_root_indices[param.name], llvm_param)

        # Generate body
        for stmt in method.body:
            cg._generate_statement(stmt)
            if cg.builder.block.is_terminated:
                break

        # Add implicit return if needed
        if not cg.builder.block.is_terminated:
            # Pop GC frame before implicit return
            if cg.gc_frame is not None and cg.gc is not None:
                cg.gc.pop_frame(cg.builder, cg.gc_frame)

            if isinstance(llvm_func.return_value.type, ir.VoidType):
                cg.builder.ret_void()
            else:
                cg.builder.ret(ir.Constant(llvm_func.return_value.type, 0))

        # Restore state
        cg.builder = old_builder
        cg.locals = old_locals
        cg.current_function = old_current_function
        cg.current_type = old_current_type
        cg.gc_frame = old_gc_frame
        cg.gc_roots = old_gc_roots
        cg.gc_root_indices = old_gc_root_indices

    # ========================================================================
    # Lambda Expression Generation
    # ========================================================================

    def generate_lambda(self, expr: LambdaExpr) -> ir.Value:
        """Generate code for lambda expression

        Creates an anonymous function and returns a pointer to it.
        """
        cg = self.cg

        # Generate unique name for this lambda
        lambda_name = f"__lambda_{cg.lambda_counter}"
        cg.lambda_counter += 1

        # Determine return type from body expression
        # First, figure out parameter types
        param_types = []
        for param in expr.params:
            param_type = cg._get_llvm_type(param.type_annotation)
            param_types.append(param_type)

        # Save current state
        saved_builder = cg.builder
        saved_locals = cg.locals.copy()
        saved_function = cg.current_function

        # Create function with i64 return (most common, will adjust if needed)
        ret_type = ir.IntType(64)

        func_type = ir.FunctionType(ret_type, param_types)
        func = ir.Function(cg.module, func_type, name=lambda_name)

        # Create entry block
        entry = func.append_basic_block("entry")
        cg.builder = ir.IRBuilder(entry)
        cg.locals = {}
        cg._reset_function_scope()

        # Bind parameters
        for i, (param, llvm_param) in enumerate(zip(expr.params, func.args)):
            llvm_param.name = param.name
            alloca = cg.builder.alloca(param_types[i], name=param.name)
            cg.builder.store(llvm_param, alloca)
            cg.locals[param.name] = alloca

        # Generate body expression
        result = cg._generate_expression(expr.body)

        # Determine actual return type
        actual_ret_type = result.type

        # If return type doesn't match, recreate the function with correct type
        if str(actual_ret_type) != str(ret_type):
            func.delete()

            func_type = ir.FunctionType(actual_ret_type, param_types)
            func = ir.Function(cg.module, func_type, name=lambda_name)

            entry = func.append_basic_block("entry")
            cg.builder = ir.IRBuilder(entry)
            cg.locals = {}
            cg._reset_function_scope()

            for i, (param, llvm_param) in enumerate(zip(expr.params, func.args)):
                llvm_param.name = param.name
                alloca = cg.builder.alloca(param_types[i], name=param.name)
                cg.builder.store(llvm_param, alloca)
                cg.locals[param.name] = alloca

            result = cg._generate_expression(expr.body)

        # Return the result
        cg.builder.ret(result)

        # Register this function
        cg.functions[lambda_name] = func

        # Restore state
        cg.builder = saved_builder
        cg.locals = saved_locals
        cg.current_function = saved_function

        # Return pointer to the function
        return func
