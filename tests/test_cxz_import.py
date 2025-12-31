"""
Tests for .cxz library import syntax.

These tests verify that the parser correctly handles library imports
using string literal syntax: import "library.cxz"
"""

import os
import sys
import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antlr4 import CommonTokenStream, InputStream
from CoexLexer import CoexLexer
from CoexParser import CoexParser
from ast_builder import ASTBuilder


def parse_program(source: str):
    """Parse source code and return AST"""
    input_stream = InputStream(source)
    lexer = CoexLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = CoexParser(token_stream)
    tree = parser.program()
    builder = ASTBuilder()
    return builder.build(tree)


class TestLibraryImportSyntax:
    """Tests for library import parsing"""

    def test_module_import_still_works(self):
        """Verify module import syntax unchanged"""
        source = """
import math

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 1
        assert program.imports[0].module == "math"
        assert program.imports[0].is_library is False
        assert program.imports[0].library_path is None

    def test_library_import_simple(self):
        """Test simple library import"""
        source = """
import "regex.cxz"

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 1
        assert program.imports[0].module == "regex"
        assert program.imports[0].is_library is True
        assert program.imports[0].library_path == "regex.cxz"

    def test_library_import_with_path(self):
        """Test library import with directory path"""
        source = """
import "lib/mylib.cxz"

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 1
        assert program.imports[0].module == "mylib"
        assert program.imports[0].is_library is True
        assert program.imports[0].library_path == "lib/mylib.cxz"

    def test_library_import_absolute_path(self):
        """Test library import with absolute path"""
        source = """
import "/usr/local/lib/coex/crypto.cxz"

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 1
        assert program.imports[0].module == "crypto"
        assert program.imports[0].is_library is True
        assert program.imports[0].library_path == "/usr/local/lib/coex/crypto.cxz"

    def test_mixed_imports(self):
        """Test mixing module and library imports"""
        source = """
import math
import "regex.cxz"
import "network.cxz"

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 3

        # Module import
        assert program.imports[0].module == "math"
        assert program.imports[0].is_library is False

        # Library imports
        assert program.imports[1].module == "regex"
        assert program.imports[1].is_library is True
        assert program.imports[1].library_path == "regex.cxz"

        assert program.imports[2].module == "network"
        assert program.imports[2].is_library is True
        assert program.imports[2].library_path == "network.cxz"

    def test_library_import_without_extension(self):
        """Test library import without .cxz extension"""
        source = """
import "mylib"

func main() -> int
    return 0
~
"""
        program = parse_program(source)
        assert len(program.imports) == 1
        # Without .cxz extension, module name is the full string
        assert program.imports[0].module == "mylib"
        assert program.imports[0].is_library is True
        assert program.imports[0].library_path == "mylib"
