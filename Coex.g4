/*
 * Coex Language Grammar
 * ANTLR4 specification for the Coex concurrent programming language
 * 
 * Author: Generated from Coex Language Specification by Matthew Strebe
 * Version: 1.0
 * 
 * This grammar implements the complete Coex language including:
 * - Four function kinds: formula, thread, func, extern
 * - Structured concurrency with channels and atomics
 * - Static polymorphism through traits
 * - Pattern matching with match/case
 * - Temporal constraints with within/else
 * - Channel selection with select
 */

grammar Coex;

// ============================================================================
// PARSER RULES
// ============================================================================

// ----------------------------------------------------------------------------
// Program Structure
// ----------------------------------------------------------------------------

program
    : NEWLINE* ((importDecl | replaceDecl | replaceKindDecl | directiveDecl) NEWLINE*)* (NEWLINE* declaration)* NEWLINE* EOF
    ;

// Module imports: import module_name or import "path/to/library.cxz"
importDecl
    : IMPORT IDENTIFIER                    // Module import: import math
    | IMPORT stringLiteral                 // Library import: import "regex.cxz"
    ;

// Local alias: replace shortname with module.function
replaceDecl
    : REPLACE IDENTIFIER WITH qualifiedName
    ;

// Local alias for kinds: replace kind shortname with module.kindname
replaceKindDecl
    : REPLACE KIND IDENTIFIER WITH qualifiedName
    ;

// Compiler directives: printing/debugging [on/off]
directiveDecl
    : (PRINTING | DEBUGGING) (ON | OFF)?
    ;

// Qualified name for module.function references
qualifiedName
    : IDENTIFIER (DOT IDENTIFIER)+
    ;

// Kind declaration for user-defined function kinds: kind NAME -> RETURN_TYPE via HANDLER
kindDecl
    : KIND IDENTIFIER ARROW typeExpr VIA IDENTIFIER NEWLINE*
    ;

declaration
    : functionDecl
    | typeDecl
    | traitDecl
    | kindDecl
    ;

// ----------------------------------------------------------------------------
// Function Declarations
// ----------------------------------------------------------------------------

// Annotation: @name or @name("argument")
annotation
    : AT IDENTIFIER (LPAREN stringLiteral RPAREN)? NEWLINE*
    ;

functionDecl
    : annotation* functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? COLON? NEWLINE* (block | rawBlock)
    | EXTERN IDENTIFIER LPAREN parameterList? RPAREN returnType? NEWLINE* blockTerminator  // extern has no body
    ;

// Raw block for user-defined kind functions - captures any tokens until terminator
// This allows DSL bodies that don't conform to Coex syntax
rawBlock
    : rawBlockContent* blockTerminator
    ;

// Any single token that isn't a terminator
rawBlockContent
    : ~(END | TILDE)
    ;

functionKind
    : FORMULA
    | TASK
    | THREAD
    | FUNC
    | EXTERN
    | IDENTIFIER DOT IDENTIFIER    // Qualified user-defined kind (module.kindname)
    | IDENTIFIER                   // Local user-defined kind name
    ;

genericParams
    : LT genericParamList GT
    ;

genericParamList
    : genericParam (COMMA genericParam)*
    ;

genericParam
    : IDENTIFIER (COLON traitBound)?
    ;

traitBound
    : IDENTIFIER (PLUS IDENTIFIER)*
    ;

parameterList
    : parameter (COMMA parameter)*
    ;

parameter
    : (UNIQUE | BORROW)? UNDERSCORE? IDENTIFIER COLON typeExpr
    ;

returnType
    : ARROW UNIQUE? typeExpr
    ;

// ----------------------------------------------------------------------------
// Type Declarations
// ----------------------------------------------------------------------------

typeDecl
    : TYPE IDENTIFIER genericParams? COLON typeBody blockTerminator
    ;

typeBody
    : NEWLINE* (typeMember (NEWLINE+ typeMember)*)? NEWLINE*
    ;

typeMember
    : fieldDecl
    | enumCase
    | methodDecl
    ;

fieldDecl
    : IDENTIFIER COLON typeExpr
    ;

enumCase
    : CASE IDENTIFIER (LPAREN enumCaseParams RPAREN)?
    ;

enumCaseParams
    : enumCaseParam (COMMA enumCaseParam)*
    ;

enumCaseParam
    : IDENTIFIER COLON typeExpr
    ;

methodDecl
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? COLON? NEWLINE* block
    ;

// ----------------------------------------------------------------------------
// Trait Declarations
// ----------------------------------------------------------------------------

traitDecl
    : TRAIT IDENTIFIER genericParams? COLON traitBody blockTerminator
    ;

traitBody
    : NEWLINE* (traitMethodDecl (NEWLINE+ traitMethodDecl)*)? NEWLINE*
    ;

traitMethodDecl
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType?
    ;

// ----------------------------------------------------------------------------
// Blocks and Statements
// ----------------------------------------------------------------------------

block
    : NEWLINE* (statement (stmtSep statement)*)? NEWLINE* blockTerminator
    ;

// Statement separator: newline(s) or semicolon (with optional trailing newlines)
stmtSep
    : NEWLINE+
    | SEMI NEWLINE*
    ;

blockTerminator
    : TILDE
    | END
    ;

statement
    : varDeclStmt
    | tupleDestructureStmt
    | controlFlowStmt
    | llvmIrStmt
    | simpleStmt
    ;

controlFlowStmt
    : ifStmt
    | forStmt
    | forAssignStmt
    | firstAssignStmt
    | mostAssignStmt
    | whileStmt
    | cycleStmt
    | matchStmt
    | selectStmt
    | withinStmt
    | returnStmt
    | breakStmt
    | continueStmt
    ;

// Handles both assignment (x = 5) and expression statements (print())
simpleStmt
    : expression (assignOp expression)?
    ;

// Inline LLVM IR statement/expression
llvmIrStmt
    : LLVM_IR llvmBindings? llvmReturn? TRIPLE_STRING
    ;

llvmBindings
    : LPAREN llvmBinding (COMMA llvmBinding)* RPAREN
    ;

llvmBinding
    : IDENTIFIER ARROW LLVM_REGISTER (COLON llvmTypeHint)?
    ;

llvmReturn
    : ARROW LLVM_REGISTER COLON llvmTypeHint
    ;

llvmTypeHint
    : IDENTIFIER
    ;

varDeclStmt
    : (CONST | UNIQUE)? IDENTIFIER COLON typeExpr (ASSIGN | COPY_ASSIGN) expression
    | (CONST | UNIQUE)? IDENTIFIER (ASSIGN | COPY_ASSIGN) expression
    ;

// Tuple destructuring: (a, b) = expr
tupleDestructureStmt
    : LPAREN IDENTIFIER (COMMA IDENTIFIER)+ RPAREN ASSIGN expression
    ;

assignOp
    : ASSIGN
    | COPY_ASSIGN
    | PLUS_ASSIGN
    | MINUS_ASSIGN
    | STAR_ASSIGN
    | SLASH_ASSIGN
    | PERCENT_ASSIGN
    ;

// If statement with optional else/else-if chains
ifStmt
    : IF expression ifBlock elseIfClause* elseClause? blockTerminator
    ;

// Block without terminator (for if/else bodies)
ifBlock
    : COLON? NEWLINE* (statement (stmtSep statement)*)? NEWLINE*
    ;

elseIfClause
    : ELSE IF expression ifBlock
    ;

elseClause
    : ELSE ifBlock
    ;

// Binding pattern for for loops and comprehensions
bindingPattern
    : IDENTIFIER                                    // Simple variable
    | UNDERSCORE                                    // Wildcard
    | LPAREN bindingPattern (COMMA bindingPattern)+ RPAREN  // Tuple pattern
    ;

// For-in loop with destructuring support
forStmt
    : FOR bindingPattern IN expression COLON? NEWLINE* block
    ;

// For-assign pattern: results = for i in items expr ~
forAssignStmt
    : IDENTIFIER ASSIGN FOR bindingPattern IN expression expression COLON? NEWLINE* block
    ;

// First-assign pattern: result = first i in items body ~
// Returns the first successful result, cancelling remaining tasks
firstAssignStmt
    : IDENTIFIER ASSIGN FIRST bindingPattern IN expression COLON? NEWLINE* block
    ;

// Most-assign pattern: (results, errors) = most i in items body ~
// Returns tuple of (successful results, errors) - no cancellation
mostAssignStmt
    : LPAREN IDENTIFIER COMMA IDENTIFIER RPAREN ASSIGN MOST bindingPattern IN expression COLON? NEWLINE* block
    ;

// While loop (standard while condition)
whileStmt
    : WHILE expression COLON? NEWLINE* block
    ;

// Cycle statement (double-buffered synchronous iteration)
// Condition is in outer scope; body variables are double-buffered
cycleStmt
    : WHILE expression CYCLE COLON? NEWLINE* block
    ;

// Match statement (pattern matching)
matchStmt
    : MATCH expression matchBody blockTerminator
    ;

matchBody
    : NEWLINE* (matchCase (NEWLINE* matchCase)*)? NEWLINE*
    ;

matchCase
    : CASE pattern COLON NEWLINE* (statement (stmtSep statement)*)? NEWLINE* blockTerminator
    ;

pattern
    : IDENTIFIER (LPAREN patternParams RPAREN)?
    | literal
    ;

patternParams
    : IDENTIFIER (COMMA IDENTIFIER)*
    ;

// Select statement (channel selection)
selectStmt
    : SELECT selectModifier? selectBody blockTerminator
    ;

selectModifier
    : selectStrategy
    | TIMEOUT expression
    | selectStrategy TIMEOUT expression
    ;

selectStrategy
    : FAIR
    | RANDOM
    | PRIORITY
    ;

selectBody
    : NEWLINE* (selectCase (NEWLINE* selectCase)*)? NEWLINE*
    ;

selectCase
    : CASE IDENTIFIER LARROW expression COLON? NEWLINE* (statement (stmtSep statement)*)? NEWLINE* blockTerminator
    ;

// Within statement (temporal constraints)
withinStmt
    : WITHIN expression ifBlock withinElse? blockTerminator
    ;

withinElse
    : ELSE ifBlock
    ;

returnStmt
    : RETURN expression?
    ;

breakStmt
    : BREAK
    ;

continueStmt
    : CONTINUE
    ;

// ----------------------------------------------------------------------------
// Expressions
// ----------------------------------------------------------------------------

expression
    : ternaryExpr
    ;

// Ternary conditional: expr ? expr : expr (continuation) or expr ? expr ! expr (exit/return)
ternaryExpr
    : orExpr (QUESTION ternaryExpr (COLON | BANG) ternaryExpr)?
    ;

// Logical OR
orExpr
    : andExpr (OR andExpr)*
    ;

// Logical AND
andExpr
    : notExpr (AND notExpr)*
    ;

// Logical NOT
notExpr
    : NOT notExpr
    | nullCoalesceExpr
    ;

// Null coalescing: expr ?? expr
nullCoalesceExpr
    : comparisonExpr (NULL_COALESCE comparisonExpr)*
    ;

// Comparison operators
comparisonExpr
    : rangeExpr (comparisonOp rangeExpr)*
    ;

comparisonOp
    : EQ | NEQ | LT | GT | LE | GE
    ;

// Range expressions: start..end
rangeExpr
    : additiveExpr (DOTDOT additiveExpr)?
    ;

// Addition and subtraction
additiveExpr
    : multiplicativeExpr ((PLUS | MINUS) multiplicativeExpr)*
    ;

// Multiplication, division, modulo
multiplicativeExpr
    : unaryExpr ((STAR | SLASH | PERCENT) unaryExpr)*
    ;

// Unary operators
unaryExpr
    : MINUS unaryExpr
    | AWAIT unaryExpr
    | postfixExpr
    ;

// Postfix expressions (method calls, indexing, member access, function calls)
postfixExpr
    : primaryExpr postfixOp*
    ;

postfixOp
    : DOT methodName
    | DOT INTEGER_LITERAL                                     // Tuple index access: t.0, t.1
    | DOT methodName genericArgs? LPAREN argumentList? RPAREN
    | LBRACKET sliceOrIndex RBRACKET                          // Index or slice
    | DOUBLE_LBRACKET relativeIndex DOUBLE_RBRACKET           // Relative index: arr[[offset]] or arr[[i, j]]
    | LPAREN argumentList? RPAREN
    | AS typeExpr                                             // Type cast: j as Person, j as int?
    ;

// Relative index expression for cellular automata
relativeIndex
    : expression (COMMA expression)*                          // Single or multi-dimensional offset
    ;

// Method names can be identifiers or type keywords (for .int(), .float(), .string(), .bool(), .int32(), .float32())
methodName
    : IDENTIFIER
    | INT_TYPE
    | INT32_TYPE
    | FLOAT_TYPE
    | FLOAT32_TYPE
    | BOOL_TYPE
    | STRING_TYPE
    | BYTE_TYPE
    | CHAR_TYPE
    ;

// Distinguish between slice [start:end] and index [i] or [i, j]
sliceOrIndex
    : sliceExpr                                               // Slice: [start:end], [:end], [start:], [:]
    | expression (COMMA expression)*                          // Index: [i] or multi-index [i, j]
    ;

// Slice expression with optional start and end bounds
sliceExpr
    : expression? COLON expression?
    ;

// Primary expressions
primaryExpr
    : literal
    | IDENTIFIER genericArgs                                // Generic type: List<int>
    | IDENTIFIER
    | JSON_TYPE                                             // Allow 'json' as expression for json.method() calls
    | SELF
    | LPAREN expression RPAREN
    | LPAREN tupleElements RPAREN
    | listLiteral
    | mapLiteral
    | lambdaExpr
    | llvmIrExpr                                            // Inline LLVM IR expression
    ;

// Inline LLVM IR as expression (with return value)
llvmIrExpr
    : LLVM_IR llvmBindings? llvmReturn TRIPLE_STRING
    ;

// Literals
literal
    : INTEGER_LITERAL
    | HEX_LITERAL
    | BINARY_LITERAL
    | FLOAT_LITERAL
    | stringLiteral
    | TRUE
    | FALSE
    | NIL
    ;

stringLiteral
    : STRING_LITERAL
    ;

// Tuple elements (named or positional)
tupleElements
    : tupleElement (COMMA tupleElement)+
    ;

tupleElement
    : (IDENTIFIER COLON)? expression
    ;

// List literals: [expr, expr, ...] or [expr for pattern in iterable if condition]
listLiteral
    : LBRACKET NEWLINE* expressionList? NEWLINE* RBRACKET                   // Regular list
    | LBRACKET NEWLINE* expression comprehensionClauses NEWLINE* RBRACKET   // List comprehension
    ;

// Comprehension clauses: for pattern in iterable (if condition)?
comprehensionClauses
    : comprehensionClause+
    ;

comprehensionClause
    : FOR bindingPattern IN expression (IF expression)?
    ;

expressionList
    : expression (COMMA NEWLINE* expression)* COMMA?
    ;

// Map/Set/JSON literals and comprehensions
// JSON: {} or {name: "Alice", age: 30} (bare identifier or string keys)
// Map: {1: 10, 2: 20} or {(var): value} (expression keys, use parens for variables)
// Set: {a, b, c} (values only, no colons)
// Note: NEWLINE* allows multi-line literals
mapLiteral
    : LBRACE NEWLINE* RBRACE                                                  // Empty JSON object
    | LBRACE NEWLINE* mapEntryList NEWLINE* RBRACE                            // JSON or Map literal
    | LBRACE NEWLINE* expressionList NEWLINE* RBRACE                          // Set literal
    | LBRACE NEWLINE* expression COLON expression comprehensionClauses NEWLINE* RBRACE // Map comprehension
    | LBRACE NEWLINE* expression comprehensionClauses NEWLINE* RBRACE         // Set comprehension
    ;

mapEntryList
    : mapEntry (COMMA NEWLINE* mapEntry)* COMMA?
    ;

// Map entries with key type distinction for JSON vs Map disambiguation
// Order matters: ANTLR uses ordered choice (PEG-style)
mapEntry
    : jsonKey COLON expression                        // JSON-style: identifier or keyword key
    | stringLiteral COLON expression                  // JSON-style: quoted string key
    | LPAREN expression RPAREN COLON expression       // Map-style: parenthesized variable key
    | expression COLON expression                     // Map-style: expression key (int, etc.)
    ;

// JSON keys can be identifiers or certain keywords that are commonly used as keys
jsonKey
    : IDENTIFIER
    | TYPE      // Allow 'type' as JSON key
    | KIND      // Allow 'kind' as JSON key
    | INT_TYPE | FLOAT_TYPE | BOOL_TYPE | STRING_TYPE | BYTE_TYPE | CHAR_TYPE | JSON_TYPE
    | TRUE | FALSE | NIL
    | IN | ON | OFF | AS
    ;

// Lambda expressions: formula(_ x: int) => x * x
lambdaExpr
    : functionKind LPAREN parameterList? RPAREN FAT_ARROW expression
    ;

// Arguments for function/method calls
argumentList
    : argument (COMMA argument)*
    ;

argument
    : (IDENTIFIER COLON)? expression
    ;

// Generic type arguments: <T, U, ...>
genericArgs
    : LT typeList GT
    ;

// ----------------------------------------------------------------------------
// Type Expressions
// ----------------------------------------------------------------------------

typeExpr
    : baseType QUESTION?
    ;

baseType
    : primitiveType
    | IDENTIFIER genericArgs?
    | listType
    | tupleType
    | functionType
    ;

// List type shorthand: [T] means List<T>
listType
    : LBRACKET typeExpr RBRACKET
    ;

primitiveType
    : INT_TYPE
    | INT32_TYPE
    | FLOAT_TYPE
    | FLOAT32_TYPE
    | BOOL_TYPE
    | STRING_TYPE
    | BYTE_TYPE
    | CHAR_TYPE
    | JSON_TYPE
    | ATOMIC_INT
    | ATOMIC_FLOAT
    | ATOMIC_BOOL
    ;

tupleType
    : LPAREN tupleTypeElement (COMMA tupleTypeElement)+ RPAREN
    ;

tupleTypeElement
    : (IDENTIFIER COLON)? typeExpr
    ;

functionType
    : functionKind LPAREN typeList? RPAREN (ARROW typeExpr)?
    ;

typeList
    : typeExpr (COMMA typeExpr)*
    ;

// ============================================================================
// LEXER RULES
// ============================================================================

// ----------------------------------------------------------------------------
// Keywords
// ----------------------------------------------------------------------------

// Function kinds
FORMULA     : 'formula' ;  // Pure function (no side effects)
THREAD      : 'thread' ;
FUNC        : 'func' ;
TASK        : 'task' ;    // Reserved for future coroutine system

// Type definitions
TYPE        : 'type' ;
EXTERN      : 'extern' ;
TRAIT       : 'trait' ;
INIT        : 'init' ;

// Control flow
IF          : 'if' ;
ELSE        : 'else' ;
FOR         : 'for' ;
IN          : 'in' ;
// LOOP keyword removed - use 'while true' instead
WHILE       : 'while' ;
CYCLE       : 'cycle' ;
MATCH       : 'match' ;
CASE        : 'case' ;
SELECT      : 'select' ;
WITHIN      : 'within' ;
AS          : 'as' ;

// Concurrent collection keywords
FIRST       : 'first' ;
MOST        : 'most' ;

// Control flow modifiers
BREAK       : 'break' ;
CONTINUE    : 'continue' ;
RETURN      : 'return' ;

// Select strategies
FAIR        : 'fair' ;
RANDOM      : 'random' ;
PRIORITY    : 'priority' ;
TIMEOUT     : 'timeout' ;

// Variable declaration
VAR         : 'var' ;
CONST       : 'const' ;
UNIQUE      : 'unique' ;
BORROW      : 'borrow' ;

// Async
AWAIT       : 'await' ;

// Logical operators
AND         : 'and' ;
OR          : 'or' ;
NOT         : 'not' ;

// Boolean literals
TRUE        : 'true' ;
FALSE       : 'false' ;
NIL         : 'nil' ;

// Module system
IMPORT      : 'import' ;
REPLACE     : 'replace' ;
WITH        : 'with' ;

// Compiler directives
PRINTING    : 'printing' ;
DEBUGGING   : 'debugging' ;
ON          : 'on' ;
OFF         : 'off' ;

// Inline LLVM IR
LLVM_IR     : 'llvm_ir' ;

// User-defined kinds
KIND        : 'kind' ;
VIA         : 'via' ;

// Block terminators
END         : 'end' ;
TILDE       : '~' ;

// Special identifiers
SELF        : 'self' ;

// Primitive type keywords (32-bit variants must come before base types for ANTLR precedence)
INT32_TYPE      : 'int32' ;
FLOAT32_TYPE    : 'float32' ;
INT_TYPE        : 'int' ;
FLOAT_TYPE      : 'float' ;
BOOL_TYPE       : 'bool' ;
STRING_TYPE     : 'string' ;
BYTE_TYPE       : 'byte' ;
CHAR_TYPE       : 'char' ;
ATOMIC_INT      : 'atomic_int' ;
ATOMIC_FLOAT    : 'atomic_float' ;
ATOMIC_BOOL     : 'atomic_bool' ;
JSON_TYPE       : 'json' ;

// ----------------------------------------------------------------------------
// Operators and Punctuation
// ----------------------------------------------------------------------------

// Compound assignment (must come before simple operators)
PLUS_ASSIGN     : '+=' ;
MINUS_ASSIGN    : '-=' ;
STAR_ASSIGN     : '*=' ;
SLASH_ASSIGN    : '/=' ;
PERCENT_ASSIGN  : '%=' ;

// Comparison operators (multi-char first)
EQ          : '==' ;
NEQ         : '!=' ;
LE          : '<=' ;
GE          : '>=' ;

// Arrows (must come before single-char operators)
ARROW       : '->' ;
FAT_ARROW   : '=>' ;
LARROW      : '<-' ;  // Channel receive operator (Go style)

// Range and null coalescing
DOTDOT      : '..' ;
NULL_COALESCE : '??' ;

// LLVM register (must come before PERCENT)
LLVM_REGISTER
    : '%' [a-zA-Z_] [a-zA-Z0-9_]*
    ;

// Single-character operators
PLUS        : '+' ;
MINUS       : '-' ;
STAR        : '*' ;
SLASH       : '/' ;
PERCENT     : '%' ;
LT          : '<' ;
GT          : '>' ;
COPY_ASSIGN : ':=' ;  // Copy assign - creates deep copy (must come before ASSIGN)
ASSIGN      : '=' ;
QUESTION    : '?' ;
SEMI        : ';' ;
DOT         : '.' ;
BANG        : '!' ;  // Exit variant separator for ternary (NEQ != matches first)

// Delimiters
LPAREN      : '(' ;
RPAREN      : ')' ;
DOUBLE_LBRACKET : '[[' ;  // Relative indexing (must come before single brackets)
DOUBLE_RBRACKET : ']]' ;
LBRACKET    : '[' ;
RBRACKET    : ']' ;
LBRACE      : '{' ;
RBRACE      : '}' ;
COMMA       : ',' ;
COLON       : ':' ;
UNDERSCORE  : '_' ;
AT          : '@' ;

// ----------------------------------------------------------------------------
// Literals
// ----------------------------------------------------------------------------

// Numeric literals (order matters: more specific patterns first)
HEX_LITERAL
    : '0' [xX] HEX_DIGIT+
    ;

BINARY_LITERAL
    : '0' [bB] [01]+
    ;

FLOAT_LITERAL
    : DIGIT+ '.' DIGIT+ EXPONENT?
    | DIGIT+ EXPONENT
    ;

INTEGER_LITERAL
    : DIGIT+
    ;

fragment EXPONENT
    : [eE] [+-]? DIGIT+
    ;

fragment DIGIT
    : [0-9]
    ;

fragment HEX_DIGIT
    : [0-9a-fA-F]
    ;

// Triple-quoted strings (for multi-line content like inline LLVM IR)
TRIPLE_STRING
    : '"""' .*? '"""'
    | '\'\'\'' .*? '\'\'\''
    ;

// String literals (both single and double quotes are equivalent)
STRING_LITERAL
    : '"' ( ESCAPE_SEQ | ~["\\\r\n] )* '"'
    | '\'' ( ESCAPE_SEQ | ~['\\\r\n] )* '\''
    ;

fragment ESCAPE_SEQ
    : '\\' [btnfr"'\\]
    | '\\' 'x' HEX_DIGIT HEX_DIGIT
    | '\\' 'u' HEX_DIGIT HEX_DIGIT HEX_DIGIT HEX_DIGIT
    | '\\' [0-7] [0-7]? [0-7]?
    | '\\' 'n'
    | '\\' 't'
    ;

// ----------------------------------------------------------------------------
// Identifiers
// ----------------------------------------------------------------------------

IDENTIFIER
    : LETTER (LETTER | DIGIT)*
    ;

fragment LETTER
    : [a-zA-Z_]
    ;

// ----------------------------------------------------------------------------
// Comments
// ----------------------------------------------------------------------------

// Block comments: ## ... ##
BLOCK_COMMENT
    : '##' .*? '##' -> channel(HIDDEN)
    ;

// Single-line comments: # ...
LINE_COMMENT
    : '#' ~[\r\n]* -> channel(HIDDEN)
    ;

// ----------------------------------------------------------------------------
// Whitespace
// ----------------------------------------------------------------------------

NEWLINE
    : [\r\n]+
    ;

WS
    : [ \t]+ -> skip
    ;
