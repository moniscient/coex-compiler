/*
 * Coex Language Lexer Grammar
 * ANTLR4 specification for the Coex concurrent programming language
 * 
 * Author: Generated from Coex Language Specification by Matthew Strebe
 */

lexer grammar CoexLexer;

// ============================================================================
// Keywords
// ============================================================================

// Function kinds
FORMULA     : 'formula' ;
TASK        : 'task' ;
FUNC        : 'func' ;

// Type definitions
TYPE        : 'type' ;
TRAIT       : 'trait' ;
MATRIX      : 'matrix' ;

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

// Literals
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

// Built-in type keywords (for clarity, though they're also identifiers)
SELF        : 'self' ;
CELL        : 'cell' ;

// ============================================================================
// Operators and Punctuation
// ============================================================================

// Compound assignment (must come before single-char operators)
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

// Null coalescing and range
NULL_COALESCE : '??' ;
DOTDOT      : '..' ;

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
SEMICOLON   : ';' ;
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

// ============================================================================
// Literals
// ============================================================================

// Integer literals
HEX_LITERAL
    : '0' [xX] HEX_DIGIT+
    ;

BINARY_LITERAL
    : '0' [bB] [01]+
    ;

INTEGER_LITERAL
    : DIGIT+
    ;

// Float literals (including scientific notation)
FLOAT_LITERAL
    : DIGIT+ '.' DIGIT* EXPONENT?
    | '.' DIGIT+ EXPONENT?
    | DIGIT+ EXPONENT
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

// String literals (both single and double quotes)
STRING_LITERAL
    : '"' ( ESCAPE_SEQUENCE | ~["\\\r\n] )* '"'
    | '\'' ( ESCAPE_SEQUENCE | ~['\\\r\n] )* '\''
    ;

fragment ESCAPE_SEQUENCE
    : '\\' [btnfr"'\\]
    | '\\' 'x' HEX_DIGIT HEX_DIGIT
    | '\\' 'u' HEX_DIGIT HEX_DIGIT HEX_DIGIT HEX_DIGIT
    | '\\' [0-7] [0-7]? [0-7]?
    ;

// ============================================================================
// Identifiers
// ============================================================================

IDENTIFIER
    : LETTER (LETTER | DIGIT)*
    ;

fragment LETTER
    : [a-zA-Z_]
    ;

// ============================================================================
// Comments
// ============================================================================

// Block comments (## ... ##)
BLOCK_COMMENT
    : '##' .*? '##' -> channel(HIDDEN)
    ;

// Single-line comments
LINE_COMMENT
    : '#' ~[\r\n]* -> channel(HIDDEN)
    ;

// ============================================================================
// Whitespace
// ============================================================================

NEWLINE
    : [\r\n]+ -> channel(HIDDEN)
    ;

WS
    : [ \t]+ -> channel(HIDDEN)
    ;
