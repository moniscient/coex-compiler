"""
Modules Module for Coex Code Generator

This module provides module/import system implementations for the Coex compiler.

Module System:
- import module_name          - Load and compile a module
- replace alias with module.func  - Create local alias for module function
- module.function()           - Qualified function call

Library Support:
- .coex files: Source modules compiled on-demand
- .cxz files: Pre-compiled library archives with FFI support

Search Paths:
- Current directory
- lib/ subdirectory
- Standard library path
"""
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from codegen_original import CodeGenerator, ModuleInfo
    from ast_nodes import Program


class ModulesGenerator:
    """Generates module system code for the Coex compiler."""

    def __init__(self, codegen: 'CodeGenerator'):
        """Initialize with reference to parent CodeGenerator instance."""
        self.codegen = codegen

    # Property accessors for commonly used codegen attributes
    @property
    def module(self):
        return self.codegen.module

    @property
    def loaded_modules(self):
        return self.codegen.loaded_modules

    @property
    def loaded_libraries(self):
        return self.codegen.loaded_libraries

    @property
    def module_search_paths(self):
        return self.codegen.module_search_paths

    @property
    def current_module(self):
        return self.codegen.current_module

    # ========================================================================
    # Module Loading
    # ========================================================================

    def find_module_file(self, module_name: str) -> Optional[tuple]:
        """Find module file in search paths.

        Returns:
            Tuple of (path, is_library) where is_library is True for .cxz files,
            or None if not found.
        """
        return self.codegen._find_module_file(module_name)

    def load_module(self, module_name: str) -> 'ModuleInfo':
        """Load and compile a module, returning its info.

        Handles both .coex source files and .cxz library archives.
        Caches loaded modules to avoid recompilation.
        """
        return self.codegen._load_module(module_name)

    def generate_module_contents(self, program: 'Program', module_info: 'ModuleInfo'):
        """Generate code for module contents with name mangling.

        Processes all declarations in the module:
        - Traits
        - Types (structs, enums)
        - Functions (func, formula, task)
        """
        return self.codegen._generate_module_contents(program, module_info)

    # ========================================================================
    # Library Loading (CXZ format)
    # ========================================================================

    def load_library(self, library_path: str, library_name: str):
        """Load a pre-compiled .cxz library archive.

        CXZ libraries contain:
        - Compiled object code
        - Symbol metadata for FFI
        - Type information
        """
        return self.codegen._load_library(library_path, library_name)
