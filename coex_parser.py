#!/usr/bin/env python3
"""
Coex Language Parser
Usage: python coex_parser.py <source_file>
"""

import sys
from antlr4 import *
from antlr4.error.ErrorListener import ErrorListener
from CoexLexer import CoexLexer
from CoexParser import CoexParser

class VerboseErrorListener(ErrorListener):
    def __init__(self):
        self.errors = []
    
    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"Line {line}:{column} - {msg}")
        print(f"Line {line}:{column} - {msg}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python coex_parser.py <source_file>")
        sys.exit(1)
    
    input_stream = FileStream(sys.argv[1])
    lexer = CoexLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = CoexParser(token_stream)
    
    # Add error listener
    error_listener = VerboseErrorListener()
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)
    
    tree = parser.program()
    
    if parser.getNumberOfSyntaxErrors() > 0:
        print(f"\nTotal syntax errors: {parser.getNumberOfSyntaxErrors()}")
        sys.exit(1)
    
    # Optionally print the parse tree
    if len(sys.argv) > 2 and sys.argv[2] == '-tree':
        print(tree.toStringTree(recog=parser))
    
    print("Parse successful!")

if __name__ == '__main__':
    main()
