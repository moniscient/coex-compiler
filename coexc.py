#!/usr/bin/env python3
"""
Coex Compiler

Usage:
    python coexc.py <source_file> [-o output] [--emit-ir] [--emit-ast]
    
Examples:
    python coexc.py hello.coex                    # Produces hello (linked executable)
    python coexc.py hello.coex -o myapp           # Produces myapp (linked executable)
    python coexc.py hello.coex -o hello.o         # Produces hello.o (object file only)
    python coexc.py hello.coex --emit-ir          # Print LLVM IR
    python coexc.py hello.coex --emit-ast         # Print AST
"""

import sys
import os
import argparse
import subprocess
from antlr4 import *
from antlr4.error.ErrorListener import ErrorListener

# Import generated parser (must be in same directory or PYTHONPATH)
from CoexLexer import CoexLexer
from CoexParser import CoexParser

# Import compiler components
from ast_builder import ASTBuilder
from codegen import CodeGenerator
from ast_nodes import *


class CompileError(Exception):
    """Compilation error"""
    pass


class ErrorCollector(ErrorListener):
    """Collects syntax errors"""
    
    def __init__(self):
        self.errors = []
    
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"Line {line}:{column} - {msg}")


def parse_file(source_path: str) -> CoexParser.ProgramContext:
    """Parse a Coex source file"""
    input_stream = FileStream(source_path)
    lexer = CoexLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = CoexParser(token_stream)
    
    # Collect errors
    error_collector = ErrorCollector()
    parser.removeErrorListeners()
    parser.addErrorListener(error_collector)
    
    tree = parser.program()
    
    if error_collector.errors:
        for error in error_collector.errors:
            print(f"Syntax error: {error}", file=sys.stderr)
        raise CompileError(f"{len(error_collector.errors)} syntax error(s)")
    
    return tree


def print_ast(program, indent=0):
    """Pretty print AST (for debugging)"""
    def p(msg):
        print("  " * indent + msg)
    
    p("Program")
    
    for g in program.globals:
        p(f"  GlobalVar: {g.name}: {g.type_annotation}")
    
    for f in program.functions:
        params = ", ".join(f"{p.name}: {p.type_annotation}" for p in f.params)
        p(f"  Function {f.kind.name} {f.name}({params}) -> {f.return_type}")
        for stmt in f.body:
            p(f"    {type(stmt).__name__}: {stmt}")


def compile_coex(source_path: str, output_path: str = None, 
                 emit_ir: bool = False, emit_ast: bool = False,
                 link: bool = False):
    """
    Compile a Coex source file.

    Args:
        source_path: Path to .coex source file
        output_path: Output path (default: source name without .coex extension)
        emit_ir: Print LLVM IR instead of compiling
        emit_ast: Print AST instead of compiling
        link: Link to produce executable (requires clang)
    """
    # Determine output path
    if output_path is None:
        base = os.path.splitext(source_path)[0]
        # Remove .coex extension if present
        if base.endswith('.coex'):
            base = base[:-5]
        output_path = base
    
    # Parse
    print(f"Parsing {source_path}...")
    tree = parse_file(source_path)
    
    # Build AST
    print("Building AST...")
    builder = ASTBuilder()
    program = builder.build(tree)
    
    if emit_ast:
        print_ast(program)
        return
    
    # Generate code
    print("Generating LLVM IR...")
    codegen = CodeGenerator()
    ir = codegen.generate(program, source_path=source_path)
    
    if emit_ir:
        print(ir)
        return
    
    # Compile to object file
    obj_path = output_path if output_path.endswith(".o") else output_path + ".o"
    print(f"Compiling to {obj_path}...")
    codegen.compile_to_object(obj_path)
    
    # Link if requested
    if link or not output_path.endswith(".o"):
        exe_path = output_path if not output_path.endswith(".o") else output_path[:-2]
        print(f"Linking to {exe_path}...")
        
        result = subprocess.run(
            ["clang", obj_path, "-o", exe_path, "-lpthread"],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"Linker error: {result.stderr}", file=sys.stderr)
            raise CompileError("Linking failed")
        
        # Clean up object file
        os.remove(obj_path)
        
        print(f"Successfully compiled to {exe_path}")
    else:
        print(f"Successfully compiled to {obj_path}")
        print(f"To link: clang {obj_path} -o <executable>")


def main():
    parser = argparse.ArgumentParser(
        description="Coex Compiler",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s hello.coex                    Compile and link to hello
  %(prog)s hello.coex -o myapp           Compile and link to myapp
  %(prog)s hello.coex -o hello.o         Compile to hello.o (object only)
  %(prog)s hello.coex --emit-ir          Print LLVM IR
  %(prog)s hello.coex --emit-ast         Print AST
        """
    )
    
    parser.add_argument("source", help="Source file (.coex)")
    parser.add_argument("-o", "--output", help="Output file (default: source without .coex)")
    parser.add_argument("--emit-ir", action="store_true", 
                        help="Print LLVM IR to stdout")
    parser.add_argument("--emit-ast", action="store_true",
                        help="Print AST to stdout")
    
    args = parser.parse_args()

    # Default output to source filename without .coex extension
    output = args.output
    if output is None:
        base = os.path.splitext(args.source)[0]
        # Remove .coex extension if present
        if base.endswith('.coex'):
            base = base[:-5]
        output = base

    try:
        link = not output.endswith(".o")
        compile_coex(
            args.source,
            output,
            emit_ir=args.emit_ir,
            emit_ast=args.emit_ast,
            link=link
        )
    except CompileError as e:
        print(f"Compilation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Internal compiler error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
