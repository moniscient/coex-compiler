"""
Module and FFI Library Loading for Coex.

This module provides functionality for loading Coex modules (.coex files)
and FFI libraries (.cxz files) into the compiler.

Module Loading:
    - _find_module_file: Locate module files in search paths
    - _load_module: Parse and compile a Coex module
    - _generate_module_contents: Generate code with name mangling

FFI Library Loading:
    - _load_library: Load .cxz libraries with FFI symbols
    - _process_library_sources: Parse library Coex sources
    - _declare_ffi_runtime: Declare FFI runtime support functions
"""
from typing import TYPE_CHECKING, Optional
from llvmlite import ir
import os

if TYPE_CHECKING:
    from codegen.core import CodeGenerator


class ModuleGenerator:
    """Generates module and FFI library loading for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.cg = codegen

    # ========================================================================
    # Module Loading
    # ========================================================================

    def find_module_file(self, module_name: str) -> Optional[tuple]:
        """Find module file in search paths.

        Returns:
            Tuple of (path, is_library) where is_library is True for .cxz files,
            or None if not found.
        """
        cg = self.cg
        # Check for both .coex (source) and .cxz (library) files
        # Prefer .coex if both exist
        for ext, is_library in [('.coex', False), ('.cxz', True)]:
            filename = f"{module_name}{ext}"
            for path in cg.module_search_paths:
                full_path = os.path.join(path, filename)
                if os.path.exists(full_path):
                    return (full_path, is_library)

        return None

    def load_module(self, module_name: str):
        """Load and compile a module, returning its info"""
        from ast_nodes import TypeDecl, FunctionDecl, FunctionKind
        cg = self.cg

        # Import ModuleInfo from core (it's defined there)
        from codegen.core import ModuleInfo

        # Check cache
        if module_name in cg.loaded_modules:
            return cg.loaded_modules[module_name]

        # Find module file (checks both .coex and .cxz)
        result = self.find_module_file(module_name)
        if not result:
            searched = ", ".join(cg.module_search_paths)
            raise RuntimeError(f"Module not found: {module_name} (searched: {searched})")

        module_path, is_library = result

        # If it's a .cxz library, delegate to library loader
        if is_library:
            self.load_library(module_path, module_name)
            # Create a placeholder ModuleInfo for consistency
            # The actual symbols are in loaded_libraries
            return ModuleInfo(name=module_name, path=module_path, program=None)

        # Parse module
        from antlr4 import FileStream, CommonTokenStream
        from CoexLexer import CoexLexer
        from CoexParser import CoexParser
        from ast_builder import ASTBuilder

        input_stream = FileStream(module_path)
        lexer = CoexLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        parser = CoexParser(token_stream)
        tree = parser.program()

        builder = ASTBuilder()
        program = builder.build(tree)

        # Create module info
        module_info = ModuleInfo(
            name=module_name,
            path=module_path,
            program=program,
        )

        # Generate code for module with name mangling
        saved_module = cg.current_module
        cg.current_module = module_name

        self.generate_module_contents(program, module_info)

        cg.current_module = saved_module
        cg.loaded_modules[module_name] = module_info

        return module_info

    def generate_module_contents(self, program, module_info):
        """Generate code for module contents with name mangling"""
        from ast_nodes import TypeDecl, FunctionDecl, FunctionKind
        cg = self.cg

        prefix = f"__{module_info.name}__"

        # Register traits from module
        for trait_decl in program.traits:
            cg._register_trait(trait_decl)

        # Register types with mangled names
        mangled_type_decls = []
        for type_decl in program.types:
            mangled = f"{prefix}{type_decl.name}"
            # Store original name mapping
            module_info.types[type_decl.name] = mangled
            # Create a copy of the type decl with mangled name
            mangled_type_decl = TypeDecl(
                name=mangled,
                type_params=type_decl.type_params,
                fields=type_decl.fields,
                methods=type_decl.methods,
                variants=type_decl.variants
            )
            cg._register_type(mangled_type_decl)
            mangled_type_decls.append(mangled_type_decl)

            # Also register under unqualified name for use within this library's methods
            # This allows Regex(handle, pattern) to work inside compile_flags()
            if type_decl.name not in cg.type_registry:
                cg.type_registry[type_decl.name] = cg.type_registry[mangled]
            if type_decl.name not in cg.type_fields:
                cg.type_fields[type_decl.name] = cg.type_fields[mangled]
            if mangled in cg.type_methods and type_decl.name not in cg.type_methods:
                cg.type_methods[type_decl.name] = cg.type_methods[mangled]

        # Declare type methods (must happen before generating functions that may call them)
        for mangled_type_decl in mangled_type_decls:
            cg._declare_type_methods(mangled_type_decl)

        # Register method functions under unqualified names for static method calls
        # e.g., __regex__Regex_compile_flags -> Regex_compile_flags
        for type_decl in program.types:
            mangled_type_name = f"{prefix}{type_decl.name}"
            if mangled_type_name in cg.type_methods:
                for method_name, mangled_method in cg.type_methods[mangled_type_name].items():
                    unqualified_method = f"{type_decl.name}_{method_name}"
                    if mangled_method in cg.functions and unqualified_method not in cg.functions:
                        cg.functions[unqualified_method] = cg.functions[mangled_method]

        # Declare and generate functions with mangled names
        for func in program.functions:
            if func.name == "main":
                continue  # Skip main in modules

            # Extern functions should NOT be mangled - they link to C code
            if func.kind == FunctionKind.EXTERN:
                # Use original name for extern functions
                module_info.functions[func.name] = func.name
                cg.func_decls[func.name] = func
                cg._declare_function(func)
                continue

            mangled = f"{prefix}{func.name}"
            module_info.functions[func.name] = mangled

            # Create mangled function declaration
            mangled_func = FunctionDecl(
                kind=func.kind,
                name=mangled,
                type_params=func.type_params,
                params=func.params,
                return_type=func.return_type,
                body=func.body
            )

            # Store for return type inference
            cg.func_decls[mangled] = mangled_func

            # Declare and generate
            cg._declare_function(mangled_func)
            cg._generate_function(mangled_func)

        # Generate type method bodies
        for mangled_type_decl in mangled_type_decls:
            cg._generate_type_methods(mangled_type_decl)

    # ========================================================================
    # FFI Library Loading
    # ========================================================================

    def load_library(self, library_path: str, library_name: str):
        """Load a .cxz library and register its FFI symbols.

        Args:
            library_path: Path to the .cxz file (relative or absolute)
            library_name: Extracted library name (e.g., "regex" from "regex.cxz")
        """
        from codegen.core import LibraryInfo
        from cxz_loader import CXZLoader, CXZError
        cg = self.cg

        # Check if already loaded
        if library_name in cg.loaded_libraries:
            return cg.loaded_libraries[library_name]

        # Initialize CXZ loader lazily
        if cg.cxz_loader is None:
            cg.cxz_loader = CXZLoader(search_paths=cg.module_search_paths)

        # Load the library
        try:
            loaded_lib = cg.cxz_loader.load(library_path)
        except CXZError as e:
            raise RuntimeError(f"Failed to load library '{library_name}': {e}")

        # Create library info
        lib_info = LibraryInfo(
            name=library_name,
            path=library_path,
            loaded_lib=loaded_lib,
            symbols=loaded_lib.get_ffi_symbols()
        )
        cg.loaded_libraries[library_name] = lib_info

        # Aggregate FFI symbols for quick lookup
        for sym_name, sym in lib_info.symbols.items():
            cg.ffi_symbols[sym_name] = sym

        # Collect link arguments
        cg.ffi_link_args.extend(loaded_lib.get_link_args())

        # Declare FFI runtime functions if not already done
        self.declare_ffi_runtime()

        # Parse and process the library's Coex source files
        self.process_library_sources(lib_info)

        return lib_info

    def process_library_sources(self, lib_info):
        """Process Coex source files from a library.

        Parses extern declarations and registers them, along with
        types and wrapper functions defined in the library.
        """
        from antlr4 import CommonTokenStream, InputStream
        from CoexLexer import CoexLexer
        from CoexParser import CoexParser
        from ast_builder import ASTBuilder
        from codegen.core import ModuleInfo
        cg = self.cg

        for filename, source in lib_info.loaded_lib.coex_sources.items():
            # Parse the source
            input_stream = InputStream(source)
            lexer = CoexLexer(input_stream)
            token_stream = CommonTokenStream(lexer)
            parser = CoexParser(token_stream)
            tree = parser.program()

            builder = ASTBuilder()
            program = builder.build(tree)

            # Create a pseudo-module for this library source
            module_info = ModuleInfo(
                name=lib_info.name,
                path=f"{lib_info.path}:{filename}",
                program=program
            )

            # Process the contents with library name prefix
            saved_module = cg.current_module
            cg.current_module = lib_info.name

            # Register types and generate functions from library
            self.generate_module_contents(program, module_info)

            cg.current_module = saved_module

            # Also register the module info for qualified access
            if lib_info.name not in cg.loaded_modules:
                cg.loaded_modules[lib_info.name] = module_info

            # Register library functions under their unqualified names for direct access
            # This allows users to call regex_match() instead of regex.regex_match()
            for original_name, mangled_name in module_info.functions.items():
                if mangled_name in cg.functions and original_name not in cg.functions:
                    cg.functions[original_name] = cg.functions[mangled_name]

            # Also register extern function declarations for the library
            if hasattr(cg, 'extern_function_decls'):
                for original_name, mangled_name in module_info.functions.items():
                    if mangled_name in cg.extern_function_decls and original_name not in cg.extern_function_decls:
                        cg.extern_function_decls[original_name] = cg.extern_function_decls[mangled_name]

            # Register library types under their unqualified names for direct access
            # This allows users to use Regex instead of regex.Regex
            for original_name, mangled_name in module_info.types.items():
                if mangled_name in cg.type_registry and original_name not in cg.type_registry:
                    cg.type_registry[original_name] = cg.type_registry[mangled_name]
                if mangled_name in cg.type_fields and original_name not in cg.type_fields:
                    cg.type_fields[original_name] = cg.type_fields[mangled_name]
                if mangled_name in cg.type_methods and original_name not in cg.type_methods:
                    cg.type_methods[original_name] = cg.type_methods[mangled_name]
                    # Also register method functions under unqualified names
                    # e.g., __regex__Regex_compile_flags -> Regex_compile_flags
                    for method_name, mangled_method in cg.type_methods[mangled_name].items():
                        unqualified_method = f"{original_name}_{method_name}"
                        if mangled_method in cg.functions and unqualified_method not in cg.functions:
                            cg.functions[unqualified_method] = cg.functions[mangled_method]

    def declare_ffi_runtime(self):
        """Declare the FFI runtime support functions."""
        cg = self.cg

        if cg._ffi_runtime_declared:
            return

        i64 = ir.IntType(64)
        i8_ptr = ir.IntType(8).as_pointer()
        void = ir.VoidType()

        # int64_t coex_ffi_instance_create(const char* library_name)
        create_type = ir.FunctionType(i64, [i8_ptr])
        cg._ffi_instance_create = ir.Function(
            cg.module, create_type, name="coex_ffi_instance_create"
        )
        cg._ffi_instance_create.linkage = 'external'

        # void coex_ffi_instance_destroy(int64_t instance_id)
        destroy_type = ir.FunctionType(void, [i64])
        cg._ffi_instance_destroy = ir.Function(
            cg.module, destroy_type, name="coex_ffi_instance_destroy"
        )
        cg._ffi_instance_destroy.linkage = 'external'

        # void coex_ffi_enter(int64_t instance_id)
        enter_type = ir.FunctionType(void, [i64])
        cg._ffi_enter = ir.Function(
            cg.module, enter_type, name="coex_ffi_enter"
        )
        cg._ffi_enter.linkage = 'external'

        # void coex_ffi_exit(int64_t instance_id)
        exit_type = ir.FunctionType(void, [i64])
        cg._ffi_exit = ir.Function(
            cg.module, exit_type, name="coex_ffi_exit"
        )
        cg._ffi_exit.linkage = 'external'

        cg._ffi_runtime_declared = True

    def get_ffi_link_args(self):
        """Get the link arguments for FFI libraries.

        Call this after generate() to get the list of object files
        and system libraries needed for linking.
        """
        return self.cg.ffi_link_args
