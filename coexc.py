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
    python coexc.py hello.coex --no-commentary    # Compile without updating commentary
    python coexc.py hello.coex --strip-commentary # Remove all #@ comments
    python coexc.py hello.coex --commentary-only  # Only update commentary, don't compile
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

# Import commentary system
from commentary import (
    parse_commentary, merge_commentary, write_commentary,
    CommentaryResponse
)
from commentary_analyzer import run_all_analyzers


class CompileError(Exception):
    """Compilation error"""
    pass


class ErrorCollector(ErrorListener):
    """Collects syntax errors"""
    
    def __init__(self):
        self.errors = []
    
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"Line {line}:{column} - {msg}")


def parse_source(source: str) -> CoexParser.ProgramContext:
    """Parse Coex source code from string."""
    input_stream = InputStream(source)
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

    for f in program.functions:
        params = ", ".join(f"{p.name}: {p.type_annotation}" for p in f.params)
        p(f"  Function {f.kind.name} {f.name}({params}) -> {f.return_type}")
        for stmt in f.body:
            p(f"    {type(stmt).__name__}: {stmt}")


def compile_coex(source_path: str, output_path: str = None,
                 emit_ir: bool = False, emit_ast: bool = False,
                 link: bool = False, no_commentary: bool = False,
                 strip_commentary: bool = False, commentary_only: bool = False,
                 cli_printing: bool = None, cli_debugging: bool = None):
    """
    Compile a Coex source file.

    Args:
        source_path: Path to .coex source file
        output_path: Output path (default: source name without .coex extension)
        emit_ir: Print LLVM IR instead of compiling
        emit_ast: Print AST instead of compiling
        link: Link to produce executable (requires clang)
        no_commentary: Skip commentary generation/update
        strip_commentary: Remove all #@ comments from source
        commentary_only: Only update commentary, don't compile
    """
    # Determine output path
    if output_path is None:
        base = os.path.splitext(source_path)[0]
        # Remove .coex extension if present
        if base.endswith('.coex'):
            base = base[:-5]
        output_path = base

    # Read source file
    with open(source_path, 'r') as f:
        source = f.read()

    # Extract existing commentary
    clean_source, existing_comments = parse_commentary(source)

    # Handle strip-commentary mode
    if strip_commentary:
        with open(source_path, 'w') as f:
            f.write(clean_source)
        print(f"Stripped {len(existing_comments)} commentary comments from {source_path}")
        if commentary_only:
            return
        source = clean_source
        existing_comments = []

    # Build suppressed set from 'off' responses
    suppressed = {
        c.message_hash for c in existing_comments
        if c.response == CommentaryResponse.OFF
    }

    # Parse clean source (without #@ comments)
    print(f"Parsing {source_path}...")
    tree = parse_source(clean_source)

    # Build AST
    print("Building AST...")
    builder = ASTBuilder()
    program = builder.build(tree)

    # Run analyzers and update commentary (unless disabled)
    if not no_commentary:
        generated_comments = run_all_analyzers(program)

        # Merge existing and generated commentary
        final_comments, suppressed = merge_commentary(
            existing_comments, generated_comments, suppressed
        )

        # Write updated source with commentary
        if final_comments or existing_comments:
            updated_source = write_commentary(clean_source, final_comments)
            if updated_source != source:
                with open(source_path, 'w') as f:
                    f.write(updated_source)
                added = len([c for c in final_comments if c not in existing_comments])
                if added > 0:
                    print(f"Added {added} commentary comment(s) to {source_path}")

    if commentary_only:
        return

    if emit_ast:
        print_ast(program)
        return

    # Generate code
    print("Generating LLVM IR...")
    codegen = CodeGenerator()
    # Pass CLI overrides for print/debug directives
    codegen.cli_printing = cli_printing
    codegen.cli_debugging = cli_debugging
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

        # Build link command
        link_cmd = ["clang", obj_path, "-o", exe_path, "-lpthread", "-lm"]

        # Add FFI library link arguments (compiled .o files and system libs)
        ffi_link_args = codegen.get_ffi_link_args()
        if ffi_link_args:
            link_cmd.extend(ffi_link_args)
            # Add FFI runtime support library
            runtime_dir = os.path.join(os.path.dirname(__file__), "runtime")
            ffi_runtime = os.path.join(runtime_dir, "libcoex_ffi.a")
            if os.path.exists(ffi_runtime):
                link_cmd.append(ffi_runtime)
            else:
                print(f"Warning: FFI runtime library not found at {ffi_runtime}")
                print("Build it with: cd runtime && make")

        result = subprocess.run(
            link_cmd,
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
        # Show FFI link args if any
        ffi_link_args = codegen.get_ffi_link_args()
        if ffi_link_args:
            ffi_args = " ".join(ffi_link_args)
            print(f"To link: clang {obj_path} {ffi_args} -o <executable>")
        else:
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
  %(prog)s hello.coex --no-commentary    Compile without updating commentary
  %(prog)s hello.coex --strip-commentary Remove all #@ comments
  %(prog)s hello.coex --commentary-only  Only update commentary, don't compile
        """
    )

    parser.add_argument("source", help="Source file (.coex)")
    parser.add_argument("-o", "--output", help="Output file (default: source without .coex)")
    parser.add_argument("--emit-ir", action="store_true",
                        help="Print LLVM IR to stdout")
    parser.add_argument("--emit-ast", action="store_true",
                        help="Print AST to stdout")
    parser.add_argument("--no-commentary", action="store_true",
                        help="Compile without updating source commentary")
    parser.add_argument("--strip-commentary", action="store_true",
                        help="Remove all #@ comments from source")
    parser.add_argument("--commentary-only", action="store_true",
                        help="Only update commentary, don't compile")
    parser.add_argument("--printing", action="store_true",
                        help="Force enable print() output")
    parser.add_argument("--no-printing", action="store_true",
                        help="Force disable print() output")
    parser.add_argument("--debugging", action="store_true",
                        help="Force enable debug() output")
    parser.add_argument("--no-debugging", action="store_true",
                        help="Force disable debug() output")

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

        # Compute CLI overrides for print/debug directives
        cli_printing = None
        if args.printing:
            cli_printing = True
        elif args.no_printing:
            cli_printing = False

        cli_debugging = None
        if args.debugging:
            cli_debugging = True
        elif args.no_debugging:
            cli_debugging = False

        compile_coex(
            args.source,
            output,
            emit_ir=args.emit_ir,
            emit_ast=args.emit_ast,
            link=link,
            no_commentary=args.no_commentary,
            strip_commentary=args.strip_commentary,
            commentary_only=args.commentary_only,
            cli_printing=cli_printing,
            cli_debugging=cli_debugging
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
