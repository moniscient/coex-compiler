# Generated from Coex.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .CoexParser import CoexParser
else:
    from CoexParser import CoexParser

# This class defines a complete generic visitor for a parse tree produced by CoexParser.

class CoexVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by CoexParser#program.
    def visitProgram(self, ctx:CoexParser.ProgramContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#importDecl.
    def visitImportDecl(self, ctx:CoexParser.ImportDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#declaration.
    def visitDeclaration(self, ctx:CoexParser.DeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#functionDecl.
    def visitFunctionDecl(self, ctx:CoexParser.FunctionDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#functionKind.
    def visitFunctionKind(self, ctx:CoexParser.FunctionKindContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#genericParams.
    def visitGenericParams(self, ctx:CoexParser.GenericParamsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#genericParamList.
    def visitGenericParamList(self, ctx:CoexParser.GenericParamListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#genericParam.
    def visitGenericParam(self, ctx:CoexParser.GenericParamContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#traitBound.
    def visitTraitBound(self, ctx:CoexParser.TraitBoundContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#parameterList.
    def visitParameterList(self, ctx:CoexParser.ParameterListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#parameter.
    def visitParameter(self, ctx:CoexParser.ParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#returnType.
    def visitReturnType(self, ctx:CoexParser.ReturnTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#typeDecl.
    def visitTypeDecl(self, ctx:CoexParser.TypeDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#typeBody.
    def visitTypeBody(self, ctx:CoexParser.TypeBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#typeMember.
    def visitTypeMember(self, ctx:CoexParser.TypeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#fieldDecl.
    def visitFieldDecl(self, ctx:CoexParser.FieldDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#enumCase.
    def visitEnumCase(self, ctx:CoexParser.EnumCaseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#enumCaseParams.
    def visitEnumCaseParams(self, ctx:CoexParser.EnumCaseParamsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#enumCaseParam.
    def visitEnumCaseParam(self, ctx:CoexParser.EnumCaseParamContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#methodDecl.
    def visitMethodDecl(self, ctx:CoexParser.MethodDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#traitDecl.
    def visitTraitDecl(self, ctx:CoexParser.TraitDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#traitBody.
    def visitTraitBody(self, ctx:CoexParser.TraitBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#traitMethodDecl.
    def visitTraitMethodDecl(self, ctx:CoexParser.TraitMethodDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixDecl.
    def visitMatrixDecl(self, ctx:CoexParser.MatrixDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixDimensions.
    def visitMatrixDimensions(self, ctx:CoexParser.MatrixDimensionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixBody.
    def visitMatrixBody(self, ctx:CoexParser.MatrixBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixClause.
    def visitMatrixClause(self, ctx:CoexParser.MatrixClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixTypeDecl.
    def visitMatrixTypeDecl(self, ctx:CoexParser.MatrixTypeDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixInitDecl.
    def visitMatrixInitDecl(self, ctx:CoexParser.MatrixInitDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matrixMethodDecl.
    def visitMatrixMethodDecl(self, ctx:CoexParser.MatrixMethodDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#globalVarDecl.
    def visitGlobalVarDecl(self, ctx:CoexParser.GlobalVarDeclContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#block.
    def visitBlock(self, ctx:CoexParser.BlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#blockTerminator.
    def visitBlockTerminator(self, ctx:CoexParser.BlockTerminatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#statement.
    def visitStatement(self, ctx:CoexParser.StatementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#controlFlowStmt.
    def visitControlFlowStmt(self, ctx:CoexParser.ControlFlowStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#simpleStmt.
    def visitSimpleStmt(self, ctx:CoexParser.SimpleStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#varDeclStmt.
    def visitVarDeclStmt(self, ctx:CoexParser.VarDeclStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#tupleDestructureStmt.
    def visitTupleDestructureStmt(self, ctx:CoexParser.TupleDestructureStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#assignOp.
    def visitAssignOp(self, ctx:CoexParser.AssignOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#ifStmt.
    def visitIfStmt(self, ctx:CoexParser.IfStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#ifBlock.
    def visitIfBlock(self, ctx:CoexParser.IfBlockContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#elseIfClause.
    def visitElseIfClause(self, ctx:CoexParser.ElseIfClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#elseClause.
    def visitElseClause(self, ctx:CoexParser.ElseClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#bindingPattern.
    def visitBindingPattern(self, ctx:CoexParser.BindingPatternContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#forStmt.
    def visitForStmt(self, ctx:CoexParser.ForStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#forAssignStmt.
    def visitForAssignStmt(self, ctx:CoexParser.ForAssignStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#loopStmt.
    def visitLoopStmt(self, ctx:CoexParser.LoopStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matchStmt.
    def visitMatchStmt(self, ctx:CoexParser.MatchStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matchBody.
    def visitMatchBody(self, ctx:CoexParser.MatchBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#matchCase.
    def visitMatchCase(self, ctx:CoexParser.MatchCaseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#pattern.
    def visitPattern(self, ctx:CoexParser.PatternContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#patternParams.
    def visitPatternParams(self, ctx:CoexParser.PatternParamsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#selectStmt.
    def visitSelectStmt(self, ctx:CoexParser.SelectStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#selectModifier.
    def visitSelectModifier(self, ctx:CoexParser.SelectModifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#selectStrategy.
    def visitSelectStrategy(self, ctx:CoexParser.SelectStrategyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#selectBody.
    def visitSelectBody(self, ctx:CoexParser.SelectBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#selectCase.
    def visitSelectCase(self, ctx:CoexParser.SelectCaseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#withinStmt.
    def visitWithinStmt(self, ctx:CoexParser.WithinStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#withinElse.
    def visitWithinElse(self, ctx:CoexParser.WithinElseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#returnStmt.
    def visitReturnStmt(self, ctx:CoexParser.ReturnStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#breakStmt.
    def visitBreakStmt(self, ctx:CoexParser.BreakStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#continueStmt.
    def visitContinueStmt(self, ctx:CoexParser.ContinueStmtContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#expression.
    def visitExpression(self, ctx:CoexParser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#ternaryExpr.
    def visitTernaryExpr(self, ctx:CoexParser.TernaryExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#orExpr.
    def visitOrExpr(self, ctx:CoexParser.OrExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#andExpr.
    def visitAndExpr(self, ctx:CoexParser.AndExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#notExpr.
    def visitNotExpr(self, ctx:CoexParser.NotExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#nullCoalesceExpr.
    def visitNullCoalesceExpr(self, ctx:CoexParser.NullCoalesceExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#comparisonExpr.
    def visitComparisonExpr(self, ctx:CoexParser.ComparisonExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#comparisonOp.
    def visitComparisonOp(self, ctx:CoexParser.ComparisonOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#rangeExpr.
    def visitRangeExpr(self, ctx:CoexParser.RangeExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#additiveExpr.
    def visitAdditiveExpr(self, ctx:CoexParser.AdditiveExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#multiplicativeExpr.
    def visitMultiplicativeExpr(self, ctx:CoexParser.MultiplicativeExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#unaryExpr.
    def visitUnaryExpr(self, ctx:CoexParser.UnaryExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#postfixExpr.
    def visitPostfixExpr(self, ctx:CoexParser.PostfixExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#postfixOp.
    def visitPostfixOp(self, ctx:CoexParser.PostfixOpContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#primaryExpr.
    def visitPrimaryExpr(self, ctx:CoexParser.PrimaryExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#literal.
    def visitLiteral(self, ctx:CoexParser.LiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#stringLiteral.
    def visitStringLiteral(self, ctx:CoexParser.StringLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#tupleElements.
    def visitTupleElements(self, ctx:CoexParser.TupleElementsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#tupleElement.
    def visitTupleElement(self, ctx:CoexParser.TupleElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#listLiteral.
    def visitListLiteral(self, ctx:CoexParser.ListLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#comprehensionClauses.
    def visitComprehensionClauses(self, ctx:CoexParser.ComprehensionClausesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#comprehensionClause.
    def visitComprehensionClause(self, ctx:CoexParser.ComprehensionClauseContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#expressionList.
    def visitExpressionList(self, ctx:CoexParser.ExpressionListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#mapLiteral.
    def visitMapLiteral(self, ctx:CoexParser.MapLiteralContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#mapEntryList.
    def visitMapEntryList(self, ctx:CoexParser.MapEntryListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#mapEntry.
    def visitMapEntry(self, ctx:CoexParser.MapEntryContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#lambdaExpr.
    def visitLambdaExpr(self, ctx:CoexParser.LambdaExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#argumentList.
    def visitArgumentList(self, ctx:CoexParser.ArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#argument.
    def visitArgument(self, ctx:CoexParser.ArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#genericArgs.
    def visitGenericArgs(self, ctx:CoexParser.GenericArgsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#typeExpr.
    def visitTypeExpr(self, ctx:CoexParser.TypeExprContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#baseType.
    def visitBaseType(self, ctx:CoexParser.BaseTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#primitiveType.
    def visitPrimitiveType(self, ctx:CoexParser.PrimitiveTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#tupleType.
    def visitTupleType(self, ctx:CoexParser.TupleTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#tupleTypeElement.
    def visitTupleTypeElement(self, ctx:CoexParser.TupleTypeElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#functionType.
    def visitFunctionType(self, ctx:CoexParser.FunctionTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by CoexParser#typeList.
    def visitTypeList(self, ctx:CoexParser.TypeListContext):
        return self.visitChildren(ctx)



del CoexParser