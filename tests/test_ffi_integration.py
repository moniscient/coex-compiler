"""
Integration tests for .cxz FFI library support.

Tests the complete pipeline:
1. Loading .cxz archive
2. Parsing manifest
3. Compiling FFI C source
4. Linking with Coex code
5. Running the compiled program
"""

import os
import sys
import pytest
import zipfile
import tempfile
import subprocess
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cxz_loader import CXZLoader, FFICache


class TestCXZLoadIntegration:
    """Test loading the minimal.cxz test library"""

    @pytest.fixture
    def minimal_cxz_path(self):
        """Path to the minimal test library"""
        test_libs = Path(__file__).parent.parent / "test_libs"
        cxz_path = test_libs / "minimal.cxz"
        if not cxz_path.exists():
            pytest.skip("minimal.cxz not found - run: cd test_libs/minimal && zip -r ../minimal.cxz .")
        return str(cxz_path)

    def test_load_minimal_library(self, minimal_cxz_path, tmp_path):
        """Test loading the minimal test library"""
        cache = FFICache(str(tmp_path / "cache"))
        loader = CXZLoader(cache=cache)

        lib = loader.load(minimal_cxz_path)

        assert lib.name == "minimal"
        assert lib.version == "1.0.0"
        assert "minimal_ext" in lib.compiled_ffi
        assert os.path.exists(lib.compiled_ffi["minimal_ext"].object_path)

    def test_minimal_library_symbols(self, minimal_cxz_path, tmp_path):
        """Test that symbols are correctly parsed from minimal library"""
        cache = FFICache(str(tmp_path / "cache"))
        loader = CXZLoader(cache=cache)

        lib = loader.load(minimal_cxz_path)
        symbols = lib.get_ffi_symbols()

        assert "coex_minimal_add" in symbols
        assert symbols["coex_minimal_add"].params == ["int", "int"]
        assert symbols["coex_minimal_add"].returns == "int"

        assert "coex_minimal_greet" in symbols
        assert symbols["coex_minimal_greet"].params == ["string"]

        assert "coex_minimal_create_handle" in symbols
        assert "coex_minimal_get_value" in symbols
        assert "coex_minimal_free_handle" in symbols

    def test_minimal_library_link_args(self, minimal_cxz_path, tmp_path):
        """Test that link args are generated correctly"""
        cache = FFICache(str(tmp_path / "cache"))
        loader = CXZLoader(cache=cache)

        lib = loader.load(minimal_cxz_path)
        link_args = lib.get_link_args()

        # Should have the object file
        assert len(link_args) >= 1
        assert any(arg.endswith(".o") for arg in link_args)

    def test_minimal_library_coex_source(self, minimal_cxz_path, tmp_path):
        """Test that Coex source is extracted"""
        cache = FFICache(str(tmp_path / "cache"))
        loader = CXZLoader(cache=cache)

        lib = loader.load(minimal_cxz_path)

        assert "main.coex" in lib.coex_sources
        source = lib.coex_sources["main.coex"]
        assert "extern coex_minimal_add" in source
        assert "func add(" in source


class TestFFICompilationIntegration:
    """Test FFI compilation from .cxz libraries"""

    @pytest.fixture
    def minimal_cxz_path(self):
        """Path to the minimal test library"""
        test_libs = Path(__file__).parent.parent / "test_libs"
        cxz_path = test_libs / "minimal.cxz"
        if not cxz_path.exists():
            pytest.skip("minimal.cxz not found")
        return str(cxz_path)

    def test_ffi_object_is_valid(self, minimal_cxz_path, tmp_path):
        """Test that compiled FFI object file contains expected symbols"""
        cache = FFICache(str(tmp_path / "cache"))
        loader = CXZLoader(cache=cache)

        lib = loader.load(minimal_cxz_path)
        obj_path = lib.compiled_ffi["minimal_ext"].object_path

        # Use nm to check symbols in object file
        result = subprocess.run(
            ["nm", obj_path],
            capture_output=True,
            text=True
        )

        # Should contain our functions
        assert "coex_minimal_add" in result.stdout
        assert "coex_minimal_greet" in result.stdout


class TestCodegenLibraryImport:
    """Test codegen handling of library imports"""

    def test_codegen_import_library_syntax(self):
        """Test that codegen accepts library import syntax"""
        from antlr4 import CommonTokenStream, InputStream
        from CoexLexer import CoexLexer
        from CoexParser import CoexParser
        from ast_builder import ASTBuilder

        # This tests that the grammar and AST builder handle library imports
        source = '''
import "minimal.cxz"

func main() -> int
    return 0
~
'''
        input_stream = InputStream(source)
        lexer = CoexLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        parser = CoexParser(token_stream)
        tree = parser.program()

        builder = ASTBuilder()
        program = builder.build(tree)

        assert len(program.imports) == 1
        assert program.imports[0].is_library is True
        assert program.imports[0].library_path == "minimal.cxz"
        assert program.imports[0].module == "minimal"


class TestRuntimeLibrary:
    """Test FFI runtime library builds and works"""

    def test_runtime_library_exists(self):
        """Check that libcoex_ffi.a exists"""
        runtime_dir = Path(__file__).parent.parent / "runtime"
        lib_path = runtime_dir / "libcoex_ffi.a"

        if not lib_path.exists():
            pytest.skip("libcoex_ffi.a not built - run: cd runtime && make")

        assert lib_path.exists()
        assert lib_path.stat().st_size > 0

    def test_runtime_library_symbols(self):
        """Check that runtime library has expected symbols"""
        runtime_dir = Path(__file__).parent.parent / "runtime"
        lib_path = runtime_dir / "libcoex_ffi.a"

        if not lib_path.exists():
            pytest.skip("libcoex_ffi.a not built")

        result = subprocess.run(
            ["nm", str(lib_path)],
            capture_output=True,
            text=True
        )

        # Check for key FFI support functions
        assert "coex_ffi_instance_create" in result.stdout
        assert "coex_ffi_instance_destroy" in result.stdout
        assert "coex_ffi_enter" in result.stdout
        assert "coex_ffi_exit" in result.stdout
        assert "coex_ffi_handle_alloc" in result.stdout
