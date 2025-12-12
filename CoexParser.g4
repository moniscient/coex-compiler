/*
 * Coex Language Parser Grammar
 * ANTLR4 specification for the Coex concurrent programming language
 * 
 * Author: Generated from Coex Language Specification by Matthew Strebe
 */

parser grammar CoexParser;

options { tokenVocab=CoexLexer; }

// ============================================================================
// Program Structure
// ============================================================================

program
    : importDecl* declaration* EOF
    ;

// Module imports
importDecl
    : IMPORT STRING_LITERAL                                          # simpleImport
    | FROM STRING_LITERAL IMPORT STRING_LITERAL (AS STRING_LITERAL)? # fromImport
    ;

declaration
    : functionDecl
    | typeDecl
    | traitDecl
    | matrixDecl
    | globalVarDecl
    ;

// ============================================================================
// Function Declarations
// ============================================================================

functionDecl
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? block
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

// ============================================================================
// Type Declarations
// ============================================================================

typeDecl
    : TYPE IDENTIFIER genericParams? COLON typeBody blockTerminator
    ;

typeBody
    : (fieldDecl | enumCase | methodDecl)*
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
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType? block
    ;

// ============================================================================
// Trait Declarations
// ============================================================================

traitDecl
    : TRAIT IDENTIFIER genericParams? COLON traitBody blockTerminator
    ;

traitBody
    : traitMethodDecl*
    ;

traitMethodDecl
    : functionKind IDENTIFIER genericParams? LPAREN parameterList? RPAREN returnType?
    ;

// ============================================================================
// Matrix Declarations
// ============================================================================

matrixDecl
    : MATRIX IDENTIFIER LBRACKET matrixDimensions RBRACKET COLON matrixBody blockTerminator
    ;

matrixDimensions
    : expression (COMMA expression)?
    ;

matrixBody
    : matrixTypeDecl matrixInitDecl matrixMethodDecl*
    ;

matrixTypeDecl
    : TYPE COLON typeExpr
    ;

matrixInitDecl
    : IDENTIFIER COLON expression   // 'init: value'
    ;

matrixMethodDecl
    : FORMULA IDENTIFIER LPAREN parameterList? RPAREN returnType? block
    ;

// ============================================================================
// Global Variable Declarations
// ============================================================================

globalVarDecl
    : VAR IDENTIFIER COLON typeExpr ASSIGN expression
    ;

// ============================================================================
// Statements
// ============================================================================

block
    : statement* blockTerminator
    ;

blockTerminator
    : TILDE
    | END
    ;

statement
    : varDeclStmt
    | assignmentStmt
    | expressionStmt
    | ifStmt
    | forStmt
    | loopStmt
    | whileStmt
    | matchStmt
    | selectStmt
    | withinStmt
    | returnStmt
    | breakStmt
    | continueStmt
    ;

varDeclStmt
    : VAR IDENTIFIER COLON typeExpr ASSIGN expression
    ;

assignmentStmt
    : assignmentTarget assignOp expression
    ;

assignmentTarget
    : IDENTIFIER
    | memberAccess
    | indexAccess
    ;

assignOp
    : ASSIGN
    | PLUS_ASSIGN
    | MINUS_ASSIGN
    | STAR_ASSIGN
    | SLASH_ASSIGN
    | PERCENT_ASSIGN
    ;

expressionStmt
    : expression
    ;

// If statement with optional else
ifStmt
    : IF expression block (ELSE (ifStmt | block))?
    ;

// For loop (including for-in and for-with-assignment)
forStmt
    : FOR IDENTIFIER IN expression block
    | IDENTIFIER ASSIGN FOR IDENTIFIER IN expression expression block  // results = for i in items expr ~
    ;

// Infinite loop
loopStmt
    : LOOP block
    ;

// While loop (if supported - not explicitly in spec but reasonable)
whileStmt
    : WHILE expression block
    ;

// Match statement (pattern matching)
matchStmt
    : MATCH expression matchBody blockTerminator
    ;

matchBody
    : matchCase*
    ;

matchCase
    : CASE pattern COLON statement* blockTerminator
    ;

pattern
    : IDENTIFIER (LPAREN patternParams RPAREN)?
    | literal
    ;

patternParams
    : patternParam (COMMA patternParam)*
    ;

patternParam
    : IDENTIFIER
    ;

// Select statement (channel selection)
selectStmt
    : SELECT selectStrategy? selectTimeout? selectBody blockTerminator
    ;

selectStrategy
    : FAIR
    | RANDOM
    | PRIORITY
    ;

selectTimeout
    : TIMEOUT expression
    ;

selectBody
    : selectCase*
    ;

selectCase
    : CASE IDENTIFIER LARROW expression statement* blockTerminator
    ;

// Within statement (temporal constraints)
withinStmt
    : WITHIN expression block (ELSE block)?
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

// ============================================================================
// Expressions (ordered by precedence, lowest to highest)
// ============================================================================

expression
    : ternaryExpr
    ;

// Ternary conditional: expr ? expr ; expr (else is optional)
ternaryExpr
    : orExpr (QUESTION expression (SEMICOLON expression)?)?
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
    : rangeExpr ((EQ | NEQ | LT | GT | LE | GE) rangeExpr)*
    ;

// Range expressions: expr..expr
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

// Postfix expressions (method calls, indexing, member access)
postfixExpr
    : primaryExpr postfixOp*
    ;

postfixOp
    : DOT IDENTIFIER                                    # memberAccessOp
    | DOT IDENTIFIER LPAREN argumentList? RPAREN        # methodCallOp
    | DOT IDENTIFIER genericArgs LPAREN argumentList? RPAREN # genericMethodCallOp
    | LBRACKET expressionList RBRACKET                  # indexOp
    | LPAREN argumentList? RPAREN                       # callOp
    ;

// Primary expressions
primaryExpr
    : literal
    | IDENTIFIER
    | SELF
    | CELL
    | CELL LBRACKET expression COMMA expression RBRACKET
    | LPAREN expression RPAREN
    | LPAREN tupleElements RPAREN
    | listLiteral
    | mapLiteral
    | lambdaExpr
    | typeConstruction
    | channelConstruction
    ;

// Literals
literal
    : INTEGER_LITERAL
    | HEX_LITERAL
    | BINARY_LITERAL
    | FLOAT_LITERAL
    | STRING_LITERAL
    | TRUE
    | FALSE
    | NIL
    ;

// Tuple elements (named or positional)
tupleElements
    : tupleElement (COMMA tupleElement)+
    ;

tupleElement
    : (IDENTIFIER COLON)? expression
    ;

// List literals
listLiteral
    : LBRACKET expressionList? RBRACKET
    ;

expressionList
    : expression (COMMA expression)*
    ;

// Map literals
mapLiteral
    : LBRACE mapEntryList? RBRACE
    ;

mapEntryList
    : mapEntry (COMMA mapEntry)*
    ;

mapEntry
    : expression COLON expression
    ;

// Lambda expressions
lambdaExpr
    : functionKind LPAREN parameterList? RPAREN FAT_ARROW expression
    ;

// Type construction: TypeName(field: value, ...)
typeConstruction
    : IDENTIFIER genericArgs? LPAREN argumentList? RPAREN
    | IDENTIFIER genericArgs? DOT IDENTIFIER LPAREN argumentList? RPAREN
    ;

// Channel construction: Channel<T>.new(...)
channelConstruction
    : IDENTIFIER genericArgs DOT IDENTIFIER LPAREN argumentList? RPAREN
    ;

// Arguments for function/method calls
argumentList
    : argument (COMMA argument)*
    ;

argument
    : (IDENTIFIER COLON)? expression
    ;

// Generic type arguments
genericArgs
    : LT typeList GT
    ;

// Member access (for assignment targets)
memberAccess
    : IDENTIFIER (DOT IDENTIFIER)+
    ;

// Index access (for assignment targets)
indexAccess
    : IDENTIFIER (DOT IDENTIFIER)* LBRACKET expressionList RBRACKET
    ;

// ============================================================================
// Type Expressions
// ============================================================================

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
    : 'int'
    | 'float'
    | 'bool'
    | 'string'
    | 'byte'
    | 'char'
    | 'atomic_int'
    | 'atomic_float'
    | 'atomic_bool'
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
