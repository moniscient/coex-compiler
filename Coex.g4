/*
 * Coex Language Grammar
 * ANTLR4 specification for the Coex concurrent programming language
 * 
 * Author: Generated from Coex Language Specification by Matthew Strebe
 * Version: 1.0
 * 
 * This grammar implements the complete Coex language including:
 * - Three function kinds: formula, task, func
 * - Structured concurrency with channels and atomics
 * - Cellular automata (matrices) with parallel cell updates
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
    : NEWLINE* importDecl* (NEWLINE* declaration)* NEWLINE* EOF
    ;

// Module imports (Python style)
importDecl
    : IMPORT stringLiteral
    | FROM stringLiteral IMPORT stringLiteral (AS stringLiteral)?
    ;

declaration
    : functionDecl
    | typeDecl
    | traitDecl
    | matrixDecl
    | globalVarDecl
    ;

// ----------------------------------------------------------------------------
// Function Declarations
// ----------------------------------------------------------------------------

functionDecl
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? NEWLINE* block
    ;

functionKind
    : FORMULA
    | TASK
    | FUNC
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
    : UNDERSCORE? IDENTIFIER COLON typeExpr
    ;

returnType
    : ARROW typeExpr
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
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? NEWLINE* block
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
// Matrix Declarations (Cellular Automata)
// ----------------------------------------------------------------------------

matrixDecl
    : MATRIX IDENTIFIER LBRACKET matrixDimensions RBRACKET COLON matrixBody blockTerminator
    ;

matrixDimensions
    : expression (COMMA expression)?
    ;

matrixBody
    : NEWLINE* (matrixClause (NEWLINE+ matrixClause)*)? NEWLINE*
    ;

matrixClause
    : matrixTypeDecl
    | matrixInitDecl
    | matrixMethodDecl
    ;

matrixTypeDecl
    : TYPE COLON typeExpr
    ;

matrixInitDecl
    : INIT COLON expression
    ;

matrixMethodDecl
    : FORMULA IDENTIFIER LPAREN parameterList? RPAREN returnType? NEWLINE* block
    ;

// ----------------------------------------------------------------------------
// Global Variable Declarations
// ----------------------------------------------------------------------------

globalVarDecl
    : VAR IDENTIFIER COLON typeExpr ASSIGN expression
    ;

// ----------------------------------------------------------------------------
// Blocks and Statements
// ----------------------------------------------------------------------------

block
    : NEWLINE* (statement (NEWLINE+ statement)*)? NEWLINE* blockTerminator
    ;

blockTerminator
    : TILDE
    | END
    ;

statement
    : varDeclStmt
    | tupleDestructureStmt
    | controlFlowStmt
    | simpleStmt
    ;

controlFlowStmt
    : ifStmt
    | forStmt
    | forAssignStmt
    | loopStmt
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

varDeclStmt
    : VAR IDENTIFIER COLON typeExpr ASSIGN expression
    ;

// Tuple destructuring: (a, b) = expr
tupleDestructureStmt
    : LPAREN IDENTIFIER (COMMA IDENTIFIER)+ RPAREN ASSIGN expression
    ;

assignOp
    : ASSIGN
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
    : NEWLINE* (statement (NEWLINE+ statement)*)? NEWLINE*
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
    : FOR bindingPattern IN expression NEWLINE* block
    ;

// For-assign pattern: results = for i in items expr ~
forAssignStmt
    : IDENTIFIER ASSIGN FOR bindingPattern IN expression expression NEWLINE* block
    ;

// Infinite loop
loopStmt
    : LOOP NEWLINE* block
    ;

// Match statement (pattern matching)
matchStmt
    : MATCH expression matchBody blockTerminator
    ;

matchBody
    : NEWLINE* (matchCase (NEWLINE* matchCase)*)? NEWLINE*
    ;

matchCase
    : CASE pattern COLON NEWLINE* (statement (NEWLINE+ statement)*)? NEWLINE* blockTerminator
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
    : CASE IDENTIFIER LARROW expression NEWLINE* (statement (NEWLINE+ statement)*)? NEWLINE* blockTerminator
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

// Ternary conditional: expr ? expr ; expr (semicolon/else part is optional)
ternaryExpr
    : orExpr (QUESTION ternaryExpr (SEMI ternaryExpr)?)?
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
    : DOT IDENTIFIER
    | DOT INTEGER_LITERAL                                     // Tuple index access: t.0, t.1
    | DOT IDENTIFIER genericArgs? LPAREN argumentList? RPAREN
    | LBRACKET expressionList RBRACKET
    | LPAREN argumentList? RPAREN
    ;

// Primary expressions
primaryExpr
    : literal
    | IDENTIFIER genericArgs                                // Generic type: List<int>
    | IDENTIFIER
    | SELF
    | CELL
    | CELL LBRACKET expression COMMA expression RBRACKET
    | LPAREN expression RPAREN
    | LPAREN tupleElements RPAREN
    | listLiteral
    | mapLiteral
    | lambdaExpr
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
    : LBRACKET expressionList? RBRACKET                   // Regular list
    | LBRACKET expression comprehensionClauses RBRACKET   // List comprehension
    ;

// Comprehension clauses: for pattern in iterable (if condition)?
comprehensionClauses
    : comprehensionClause+
    ;

comprehensionClause
    : FOR bindingPattern IN expression (IF expression)?
    ;

expressionList
    : expression (COMMA expression)*
    ;

// Map/Set literals and comprehensions
// Map: {} or {key: value, ...} or {key: value for pattern in iterable if condition}
// Set: {a, b, ...} or {expr for pattern in iterable if condition}
mapLiteral
    : LBRACE RBRACE                                                  // Empty map
    | LBRACE mapEntryList RBRACE                                     // Map literal
    | LBRACE expressionList RBRACE                                   // Set literal
    | LBRACE expression COLON expression comprehensionClauses RBRACE // Map comprehension
    | LBRACE expression comprehensionClauses RBRACE                  // Set comprehension
    ;

mapEntryList
    : mapEntry (COMMA mapEntry)*
    ;

mapEntry
    : expression COLON expression
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
    | tupleType
    | functionType
    ;

primitiveType
    : INT_TYPE
    | FLOAT_TYPE
    | BOOL_TYPE
    | STRING_TYPE
    | BYTE_TYPE
    | CHAR_TYPE
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
FORMULA     : 'formula' ;
TASK        : 'task' ;
FUNC        : 'func' ;

// Type definitions
TYPE        : 'type' ;
TRAIT       : 'trait' ;
MATRIX      : 'matrix' ;
INIT        : 'init' ;

// Control flow
IF          : 'if' ;
ELSE        : 'else' ;
FOR         : 'for' ;
IN          : 'in' ;
LOOP        : 'loop' ;
WHILE       : 'while' ;
MATCH       : 'match' ;
CASE        : 'case' ;
SELECT      : 'select' ;
WITHIN      : 'within' ;

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

// Module system (Python style - lowercase keywords)
IMPORT      : 'import' ;
FROM        : 'from' ;
AS          : 'as' ;

// Block terminators
END         : 'end' ;
TILDE       : '~' ;

// Special identifiers
SELF        : 'self' ;
CELL        : 'cell' ;

// Primitive type keywords
INT_TYPE        : 'int' ;
FLOAT_TYPE      : 'float' ;
BOOL_TYPE       : 'bool' ;
STRING_TYPE     : 'string' ;
BYTE_TYPE       : 'byte' ;
CHAR_TYPE       : 'char' ;
ATOMIC_INT      : 'atomic_int' ;
ATOMIC_FLOAT    : 'atomic_float' ;
ATOMIC_BOOL     : 'atomic_bool' ;

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

// Single-character operators
PLUS        : '+' ;
MINUS       : '-' ;
STAR        : '*' ;
SLASH       : '/' ;
PERCENT     : '%' ;
LT          : '<' ;
GT          : '>' ;
ASSIGN      : '=' ;
QUESTION    : '?' ;
SEMI        : ';' ;
DOT         : '.' ;

// Delimiters
LPAREN      : '(' ;
RPAREN      : ')' ;
LBRACKET    : '[' ;
RBRACKET    : ']' ;
LBRACE      : '{' ;
RBRACE      : '}' ;
COMMA       : ',' ;
COLON       : ':' ;
UNDERSCORE  : '_' ;

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
