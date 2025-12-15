# Generated from Coex.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .CoexParser import CoexParser
else:
    from CoexParser import CoexParser

# This class defines a complete listener for a parse tree produced by CoexParser.
class CoexListener(ParseTreeListener):

    # Enter a parse tree produced by CoexParser#program.
    def enterProgram(self, ctx:CoexParser.ProgramContext):
        pass

    # Exit a parse tree produced by CoexParser#program.
    def exitProgram(self, ctx:CoexParser.ProgramContext):
        pass


    # Enter a parse tree produced by CoexParser#importDecl.
    def enterImportDecl(self, ctx:CoexParser.ImportDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#importDecl.
    def exitImportDecl(self, ctx:CoexParser.ImportDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#replaceDecl.
    def enterReplaceDecl(self, ctx:CoexParser.ReplaceDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#replaceDecl.
    def exitReplaceDecl(self, ctx:CoexParser.ReplaceDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#qualifiedName.
    def enterQualifiedName(self, ctx:CoexParser.QualifiedNameContext):
        pass

    # Exit a parse tree produced by CoexParser#qualifiedName.
    def exitQualifiedName(self, ctx:CoexParser.QualifiedNameContext):
        pass


    # Enter a parse tree produced by CoexParser#declaration.
    def enterDeclaration(self, ctx:CoexParser.DeclarationContext):
        pass

    # Exit a parse tree produced by CoexParser#declaration.
    def exitDeclaration(self, ctx:CoexParser.DeclarationContext):
        pass


    # Enter a parse tree produced by CoexParser#functionDecl.
    def enterFunctionDecl(self, ctx:CoexParser.FunctionDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#functionDecl.
    def exitFunctionDecl(self, ctx:CoexParser.FunctionDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#functionKind.
    def enterFunctionKind(self, ctx:CoexParser.FunctionKindContext):
        pass

    # Exit a parse tree produced by CoexParser#functionKind.
    def exitFunctionKind(self, ctx:CoexParser.FunctionKindContext):
        pass


    # Enter a parse tree produced by CoexParser#genericParams.
    def enterGenericParams(self, ctx:CoexParser.GenericParamsContext):
        pass

    # Exit a parse tree produced by CoexParser#genericParams.
    def exitGenericParams(self, ctx:CoexParser.GenericParamsContext):
        pass


    # Enter a parse tree produced by CoexParser#genericParamList.
    def enterGenericParamList(self, ctx:CoexParser.GenericParamListContext):
        pass

    # Exit a parse tree produced by CoexParser#genericParamList.
    def exitGenericParamList(self, ctx:CoexParser.GenericParamListContext):
        pass


    # Enter a parse tree produced by CoexParser#genericParam.
    def enterGenericParam(self, ctx:CoexParser.GenericParamContext):
        pass

    # Exit a parse tree produced by CoexParser#genericParam.
    def exitGenericParam(self, ctx:CoexParser.GenericParamContext):
        pass


    # Enter a parse tree produced by CoexParser#traitBound.
    def enterTraitBound(self, ctx:CoexParser.TraitBoundContext):
        pass

    # Exit a parse tree produced by CoexParser#traitBound.
    def exitTraitBound(self, ctx:CoexParser.TraitBoundContext):
        pass


    # Enter a parse tree produced by CoexParser#parameterList.
    def enterParameterList(self, ctx:CoexParser.ParameterListContext):
        pass

    # Exit a parse tree produced by CoexParser#parameterList.
    def exitParameterList(self, ctx:CoexParser.ParameterListContext):
        pass


    # Enter a parse tree produced by CoexParser#parameter.
    def enterParameter(self, ctx:CoexParser.ParameterContext):
        pass

    # Exit a parse tree produced by CoexParser#parameter.
    def exitParameter(self, ctx:CoexParser.ParameterContext):
        pass


    # Enter a parse tree produced by CoexParser#returnType.
    def enterReturnType(self, ctx:CoexParser.ReturnTypeContext):
        pass

    # Exit a parse tree produced by CoexParser#returnType.
    def exitReturnType(self, ctx:CoexParser.ReturnTypeContext):
        pass


    # Enter a parse tree produced by CoexParser#typeDecl.
    def enterTypeDecl(self, ctx:CoexParser.TypeDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#typeDecl.
    def exitTypeDecl(self, ctx:CoexParser.TypeDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#typeBody.
    def enterTypeBody(self, ctx:CoexParser.TypeBodyContext):
        pass

    # Exit a parse tree produced by CoexParser#typeBody.
    def exitTypeBody(self, ctx:CoexParser.TypeBodyContext):
        pass


    # Enter a parse tree produced by CoexParser#typeMember.
    def enterTypeMember(self, ctx:CoexParser.TypeMemberContext):
        pass

    # Exit a parse tree produced by CoexParser#typeMember.
    def exitTypeMember(self, ctx:CoexParser.TypeMemberContext):
        pass


    # Enter a parse tree produced by CoexParser#fieldDecl.
    def enterFieldDecl(self, ctx:CoexParser.FieldDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#fieldDecl.
    def exitFieldDecl(self, ctx:CoexParser.FieldDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#enumCase.
    def enterEnumCase(self, ctx:CoexParser.EnumCaseContext):
        pass

    # Exit a parse tree produced by CoexParser#enumCase.
    def exitEnumCase(self, ctx:CoexParser.EnumCaseContext):
        pass


    # Enter a parse tree produced by CoexParser#enumCaseParams.
    def enterEnumCaseParams(self, ctx:CoexParser.EnumCaseParamsContext):
        pass

    # Exit a parse tree produced by CoexParser#enumCaseParams.
    def exitEnumCaseParams(self, ctx:CoexParser.EnumCaseParamsContext):
        pass


    # Enter a parse tree produced by CoexParser#enumCaseParam.
    def enterEnumCaseParam(self, ctx:CoexParser.EnumCaseParamContext):
        pass

    # Exit a parse tree produced by CoexParser#enumCaseParam.
    def exitEnumCaseParam(self, ctx:CoexParser.EnumCaseParamContext):
        pass


    # Enter a parse tree produced by CoexParser#methodDecl.
    def enterMethodDecl(self, ctx:CoexParser.MethodDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#methodDecl.
    def exitMethodDecl(self, ctx:CoexParser.MethodDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#traitDecl.
    def enterTraitDecl(self, ctx:CoexParser.TraitDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#traitDecl.
    def exitTraitDecl(self, ctx:CoexParser.TraitDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#traitBody.
    def enterTraitBody(self, ctx:CoexParser.TraitBodyContext):
        pass

    # Exit a parse tree produced by CoexParser#traitBody.
    def exitTraitBody(self, ctx:CoexParser.TraitBodyContext):
        pass


    # Enter a parse tree produced by CoexParser#traitMethodDecl.
    def enterTraitMethodDecl(self, ctx:CoexParser.TraitMethodDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#traitMethodDecl.
    def exitTraitMethodDecl(self, ctx:CoexParser.TraitMethodDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixDecl.
    def enterMatrixDecl(self, ctx:CoexParser.MatrixDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixDecl.
    def exitMatrixDecl(self, ctx:CoexParser.MatrixDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixDimensions.
    def enterMatrixDimensions(self, ctx:CoexParser.MatrixDimensionsContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixDimensions.
    def exitMatrixDimensions(self, ctx:CoexParser.MatrixDimensionsContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixBody.
    def enterMatrixBody(self, ctx:CoexParser.MatrixBodyContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixBody.
    def exitMatrixBody(self, ctx:CoexParser.MatrixBodyContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixClause.
    def enterMatrixClause(self, ctx:CoexParser.MatrixClauseContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixClause.
    def exitMatrixClause(self, ctx:CoexParser.MatrixClauseContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixTypeDecl.
    def enterMatrixTypeDecl(self, ctx:CoexParser.MatrixTypeDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixTypeDecl.
    def exitMatrixTypeDecl(self, ctx:CoexParser.MatrixTypeDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixInitDecl.
    def enterMatrixInitDecl(self, ctx:CoexParser.MatrixInitDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixInitDecl.
    def exitMatrixInitDecl(self, ctx:CoexParser.MatrixInitDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#matrixMethodDecl.
    def enterMatrixMethodDecl(self, ctx:CoexParser.MatrixMethodDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#matrixMethodDecl.
    def exitMatrixMethodDecl(self, ctx:CoexParser.MatrixMethodDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#globalVarDecl.
    def enterGlobalVarDecl(self, ctx:CoexParser.GlobalVarDeclContext):
        pass

    # Exit a parse tree produced by CoexParser#globalVarDecl.
    def exitGlobalVarDecl(self, ctx:CoexParser.GlobalVarDeclContext):
        pass


    # Enter a parse tree produced by CoexParser#block.
    def enterBlock(self, ctx:CoexParser.BlockContext):
        pass

    # Exit a parse tree produced by CoexParser#block.
    def exitBlock(self, ctx:CoexParser.BlockContext):
        pass


    # Enter a parse tree produced by CoexParser#blockTerminator.
    def enterBlockTerminator(self, ctx:CoexParser.BlockTerminatorContext):
        pass

    # Exit a parse tree produced by CoexParser#blockTerminator.
    def exitBlockTerminator(self, ctx:CoexParser.BlockTerminatorContext):
        pass


    # Enter a parse tree produced by CoexParser#statement.
    def enterStatement(self, ctx:CoexParser.StatementContext):
        pass

    # Exit a parse tree produced by CoexParser#statement.
    def exitStatement(self, ctx:CoexParser.StatementContext):
        pass


    # Enter a parse tree produced by CoexParser#controlFlowStmt.
    def enterControlFlowStmt(self, ctx:CoexParser.ControlFlowStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#controlFlowStmt.
    def exitControlFlowStmt(self, ctx:CoexParser.ControlFlowStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#simpleStmt.
    def enterSimpleStmt(self, ctx:CoexParser.SimpleStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#simpleStmt.
    def exitSimpleStmt(self, ctx:CoexParser.SimpleStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmIrStmt.
    def enterLlvmIrStmt(self, ctx:CoexParser.LlvmIrStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmIrStmt.
    def exitLlvmIrStmt(self, ctx:CoexParser.LlvmIrStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmBindings.
    def enterLlvmBindings(self, ctx:CoexParser.LlvmBindingsContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmBindings.
    def exitLlvmBindings(self, ctx:CoexParser.LlvmBindingsContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmBinding.
    def enterLlvmBinding(self, ctx:CoexParser.LlvmBindingContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmBinding.
    def exitLlvmBinding(self, ctx:CoexParser.LlvmBindingContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmReturn.
    def enterLlvmReturn(self, ctx:CoexParser.LlvmReturnContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmReturn.
    def exitLlvmReturn(self, ctx:CoexParser.LlvmReturnContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmTypeHint.
    def enterLlvmTypeHint(self, ctx:CoexParser.LlvmTypeHintContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmTypeHint.
    def exitLlvmTypeHint(self, ctx:CoexParser.LlvmTypeHintContext):
        pass


    # Enter a parse tree produced by CoexParser#varDeclStmt.
    def enterVarDeclStmt(self, ctx:CoexParser.VarDeclStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#varDeclStmt.
    def exitVarDeclStmt(self, ctx:CoexParser.VarDeclStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#tupleDestructureStmt.
    def enterTupleDestructureStmt(self, ctx:CoexParser.TupleDestructureStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#tupleDestructureStmt.
    def exitTupleDestructureStmt(self, ctx:CoexParser.TupleDestructureStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#assignOp.
    def enterAssignOp(self, ctx:CoexParser.AssignOpContext):
        pass

    # Exit a parse tree produced by CoexParser#assignOp.
    def exitAssignOp(self, ctx:CoexParser.AssignOpContext):
        pass


    # Enter a parse tree produced by CoexParser#ifStmt.
    def enterIfStmt(self, ctx:CoexParser.IfStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#ifStmt.
    def exitIfStmt(self, ctx:CoexParser.IfStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#ifBlock.
    def enterIfBlock(self, ctx:CoexParser.IfBlockContext):
        pass

    # Exit a parse tree produced by CoexParser#ifBlock.
    def exitIfBlock(self, ctx:CoexParser.IfBlockContext):
        pass


    # Enter a parse tree produced by CoexParser#elseIfClause.
    def enterElseIfClause(self, ctx:CoexParser.ElseIfClauseContext):
        pass

    # Exit a parse tree produced by CoexParser#elseIfClause.
    def exitElseIfClause(self, ctx:CoexParser.ElseIfClauseContext):
        pass


    # Enter a parse tree produced by CoexParser#elseClause.
    def enterElseClause(self, ctx:CoexParser.ElseClauseContext):
        pass

    # Exit a parse tree produced by CoexParser#elseClause.
    def exitElseClause(self, ctx:CoexParser.ElseClauseContext):
        pass


    # Enter a parse tree produced by CoexParser#bindingPattern.
    def enterBindingPattern(self, ctx:CoexParser.BindingPatternContext):
        pass

    # Exit a parse tree produced by CoexParser#bindingPattern.
    def exitBindingPattern(self, ctx:CoexParser.BindingPatternContext):
        pass


    # Enter a parse tree produced by CoexParser#forStmt.
    def enterForStmt(self, ctx:CoexParser.ForStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#forStmt.
    def exitForStmt(self, ctx:CoexParser.ForStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#forAssignStmt.
    def enterForAssignStmt(self, ctx:CoexParser.ForAssignStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#forAssignStmt.
    def exitForAssignStmt(self, ctx:CoexParser.ForAssignStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#loopStmt.
    def enterLoopStmt(self, ctx:CoexParser.LoopStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#loopStmt.
    def exitLoopStmt(self, ctx:CoexParser.LoopStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#whileStmt.
    def enterWhileStmt(self, ctx:CoexParser.WhileStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#whileStmt.
    def exitWhileStmt(self, ctx:CoexParser.WhileStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#cycleStmt.
    def enterCycleStmt(self, ctx:CoexParser.CycleStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#cycleStmt.
    def exitCycleStmt(self, ctx:CoexParser.CycleStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#matchStmt.
    def enterMatchStmt(self, ctx:CoexParser.MatchStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#matchStmt.
    def exitMatchStmt(self, ctx:CoexParser.MatchStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#matchBody.
    def enterMatchBody(self, ctx:CoexParser.MatchBodyContext):
        pass

    # Exit a parse tree produced by CoexParser#matchBody.
    def exitMatchBody(self, ctx:CoexParser.MatchBodyContext):
        pass


    # Enter a parse tree produced by CoexParser#matchCase.
    def enterMatchCase(self, ctx:CoexParser.MatchCaseContext):
        pass

    # Exit a parse tree produced by CoexParser#matchCase.
    def exitMatchCase(self, ctx:CoexParser.MatchCaseContext):
        pass


    # Enter a parse tree produced by CoexParser#pattern.
    def enterPattern(self, ctx:CoexParser.PatternContext):
        pass

    # Exit a parse tree produced by CoexParser#pattern.
    def exitPattern(self, ctx:CoexParser.PatternContext):
        pass


    # Enter a parse tree produced by CoexParser#patternParams.
    def enterPatternParams(self, ctx:CoexParser.PatternParamsContext):
        pass

    # Exit a parse tree produced by CoexParser#patternParams.
    def exitPatternParams(self, ctx:CoexParser.PatternParamsContext):
        pass


    # Enter a parse tree produced by CoexParser#selectStmt.
    def enterSelectStmt(self, ctx:CoexParser.SelectStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#selectStmt.
    def exitSelectStmt(self, ctx:CoexParser.SelectStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#selectModifier.
    def enterSelectModifier(self, ctx:CoexParser.SelectModifierContext):
        pass

    # Exit a parse tree produced by CoexParser#selectModifier.
    def exitSelectModifier(self, ctx:CoexParser.SelectModifierContext):
        pass


    # Enter a parse tree produced by CoexParser#selectStrategy.
    def enterSelectStrategy(self, ctx:CoexParser.SelectStrategyContext):
        pass

    # Exit a parse tree produced by CoexParser#selectStrategy.
    def exitSelectStrategy(self, ctx:CoexParser.SelectStrategyContext):
        pass


    # Enter a parse tree produced by CoexParser#selectBody.
    def enterSelectBody(self, ctx:CoexParser.SelectBodyContext):
        pass

    # Exit a parse tree produced by CoexParser#selectBody.
    def exitSelectBody(self, ctx:CoexParser.SelectBodyContext):
        pass


    # Enter a parse tree produced by CoexParser#selectCase.
    def enterSelectCase(self, ctx:CoexParser.SelectCaseContext):
        pass

    # Exit a parse tree produced by CoexParser#selectCase.
    def exitSelectCase(self, ctx:CoexParser.SelectCaseContext):
        pass


    # Enter a parse tree produced by CoexParser#withinStmt.
    def enterWithinStmt(self, ctx:CoexParser.WithinStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#withinStmt.
    def exitWithinStmt(self, ctx:CoexParser.WithinStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#withinElse.
    def enterWithinElse(self, ctx:CoexParser.WithinElseContext):
        pass

    # Exit a parse tree produced by CoexParser#withinElse.
    def exitWithinElse(self, ctx:CoexParser.WithinElseContext):
        pass


    # Enter a parse tree produced by CoexParser#returnStmt.
    def enterReturnStmt(self, ctx:CoexParser.ReturnStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#returnStmt.
    def exitReturnStmt(self, ctx:CoexParser.ReturnStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#breakStmt.
    def enterBreakStmt(self, ctx:CoexParser.BreakStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#breakStmt.
    def exitBreakStmt(self, ctx:CoexParser.BreakStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#continueStmt.
    def enterContinueStmt(self, ctx:CoexParser.ContinueStmtContext):
        pass

    # Exit a parse tree produced by CoexParser#continueStmt.
    def exitContinueStmt(self, ctx:CoexParser.ContinueStmtContext):
        pass


    # Enter a parse tree produced by CoexParser#expression.
    def enterExpression(self, ctx:CoexParser.ExpressionContext):
        pass

    # Exit a parse tree produced by CoexParser#expression.
    def exitExpression(self, ctx:CoexParser.ExpressionContext):
        pass


    # Enter a parse tree produced by CoexParser#ternaryExpr.
    def enterTernaryExpr(self, ctx:CoexParser.TernaryExprContext):
        pass

    # Exit a parse tree produced by CoexParser#ternaryExpr.
    def exitTernaryExpr(self, ctx:CoexParser.TernaryExprContext):
        pass


    # Enter a parse tree produced by CoexParser#orExpr.
    def enterOrExpr(self, ctx:CoexParser.OrExprContext):
        pass

    # Exit a parse tree produced by CoexParser#orExpr.
    def exitOrExpr(self, ctx:CoexParser.OrExprContext):
        pass


    # Enter a parse tree produced by CoexParser#andExpr.
    def enterAndExpr(self, ctx:CoexParser.AndExprContext):
        pass

    # Exit a parse tree produced by CoexParser#andExpr.
    def exitAndExpr(self, ctx:CoexParser.AndExprContext):
        pass


    # Enter a parse tree produced by CoexParser#notExpr.
    def enterNotExpr(self, ctx:CoexParser.NotExprContext):
        pass

    # Exit a parse tree produced by CoexParser#notExpr.
    def exitNotExpr(self, ctx:CoexParser.NotExprContext):
        pass


    # Enter a parse tree produced by CoexParser#nullCoalesceExpr.
    def enterNullCoalesceExpr(self, ctx:CoexParser.NullCoalesceExprContext):
        pass

    # Exit a parse tree produced by CoexParser#nullCoalesceExpr.
    def exitNullCoalesceExpr(self, ctx:CoexParser.NullCoalesceExprContext):
        pass


    # Enter a parse tree produced by CoexParser#comparisonExpr.
    def enterComparisonExpr(self, ctx:CoexParser.ComparisonExprContext):
        pass

    # Exit a parse tree produced by CoexParser#comparisonExpr.
    def exitComparisonExpr(self, ctx:CoexParser.ComparisonExprContext):
        pass


    # Enter a parse tree produced by CoexParser#comparisonOp.
    def enterComparisonOp(self, ctx:CoexParser.ComparisonOpContext):
        pass

    # Exit a parse tree produced by CoexParser#comparisonOp.
    def exitComparisonOp(self, ctx:CoexParser.ComparisonOpContext):
        pass


    # Enter a parse tree produced by CoexParser#rangeExpr.
    def enterRangeExpr(self, ctx:CoexParser.RangeExprContext):
        pass

    # Exit a parse tree produced by CoexParser#rangeExpr.
    def exitRangeExpr(self, ctx:CoexParser.RangeExprContext):
        pass


    # Enter a parse tree produced by CoexParser#additiveExpr.
    def enterAdditiveExpr(self, ctx:CoexParser.AdditiveExprContext):
        pass

    # Exit a parse tree produced by CoexParser#additiveExpr.
    def exitAdditiveExpr(self, ctx:CoexParser.AdditiveExprContext):
        pass


    # Enter a parse tree produced by CoexParser#multiplicativeExpr.
    def enterMultiplicativeExpr(self, ctx:CoexParser.MultiplicativeExprContext):
        pass

    # Exit a parse tree produced by CoexParser#multiplicativeExpr.
    def exitMultiplicativeExpr(self, ctx:CoexParser.MultiplicativeExprContext):
        pass


    # Enter a parse tree produced by CoexParser#unaryExpr.
    def enterUnaryExpr(self, ctx:CoexParser.UnaryExprContext):
        pass

    # Exit a parse tree produced by CoexParser#unaryExpr.
    def exitUnaryExpr(self, ctx:CoexParser.UnaryExprContext):
        pass


    # Enter a parse tree produced by CoexParser#postfixExpr.
    def enterPostfixExpr(self, ctx:CoexParser.PostfixExprContext):
        pass

    # Exit a parse tree produced by CoexParser#postfixExpr.
    def exitPostfixExpr(self, ctx:CoexParser.PostfixExprContext):
        pass


    # Enter a parse tree produced by CoexParser#postfixOp.
    def enterPostfixOp(self, ctx:CoexParser.PostfixOpContext):
        pass

    # Exit a parse tree produced by CoexParser#postfixOp.
    def exitPostfixOp(self, ctx:CoexParser.PostfixOpContext):
        pass


    # Enter a parse tree produced by CoexParser#primaryExpr.
    def enterPrimaryExpr(self, ctx:CoexParser.PrimaryExprContext):
        pass

    # Exit a parse tree produced by CoexParser#primaryExpr.
    def exitPrimaryExpr(self, ctx:CoexParser.PrimaryExprContext):
        pass


    # Enter a parse tree produced by CoexParser#llvmIrExpr.
    def enterLlvmIrExpr(self, ctx:CoexParser.LlvmIrExprContext):
        pass

    # Exit a parse tree produced by CoexParser#llvmIrExpr.
    def exitLlvmIrExpr(self, ctx:CoexParser.LlvmIrExprContext):
        pass


    # Enter a parse tree produced by CoexParser#literal.
    def enterLiteral(self, ctx:CoexParser.LiteralContext):
        pass

    # Exit a parse tree produced by CoexParser#literal.
    def exitLiteral(self, ctx:CoexParser.LiteralContext):
        pass


    # Enter a parse tree produced by CoexParser#stringLiteral.
    def enterStringLiteral(self, ctx:CoexParser.StringLiteralContext):
        pass

    # Exit a parse tree produced by CoexParser#stringLiteral.
    def exitStringLiteral(self, ctx:CoexParser.StringLiteralContext):
        pass


    # Enter a parse tree produced by CoexParser#tupleElements.
    def enterTupleElements(self, ctx:CoexParser.TupleElementsContext):
        pass

    # Exit a parse tree produced by CoexParser#tupleElements.
    def exitTupleElements(self, ctx:CoexParser.TupleElementsContext):
        pass


    # Enter a parse tree produced by CoexParser#tupleElement.
    def enterTupleElement(self, ctx:CoexParser.TupleElementContext):
        pass

    # Exit a parse tree produced by CoexParser#tupleElement.
    def exitTupleElement(self, ctx:CoexParser.TupleElementContext):
        pass


    # Enter a parse tree produced by CoexParser#listLiteral.
    def enterListLiteral(self, ctx:CoexParser.ListLiteralContext):
        pass

    # Exit a parse tree produced by CoexParser#listLiteral.
    def exitListLiteral(self, ctx:CoexParser.ListLiteralContext):
        pass


    # Enter a parse tree produced by CoexParser#comprehensionClauses.
    def enterComprehensionClauses(self, ctx:CoexParser.ComprehensionClausesContext):
        pass

    # Exit a parse tree produced by CoexParser#comprehensionClauses.
    def exitComprehensionClauses(self, ctx:CoexParser.ComprehensionClausesContext):
        pass


    # Enter a parse tree produced by CoexParser#comprehensionClause.
    def enterComprehensionClause(self, ctx:CoexParser.ComprehensionClauseContext):
        pass

    # Exit a parse tree produced by CoexParser#comprehensionClause.
    def exitComprehensionClause(self, ctx:CoexParser.ComprehensionClauseContext):
        pass


    # Enter a parse tree produced by CoexParser#expressionList.
    def enterExpressionList(self, ctx:CoexParser.ExpressionListContext):
        pass

    # Exit a parse tree produced by CoexParser#expressionList.
    def exitExpressionList(self, ctx:CoexParser.ExpressionListContext):
        pass


    # Enter a parse tree produced by CoexParser#mapLiteral.
    def enterMapLiteral(self, ctx:CoexParser.MapLiteralContext):
        pass

    # Exit a parse tree produced by CoexParser#mapLiteral.
    def exitMapLiteral(self, ctx:CoexParser.MapLiteralContext):
        pass


    # Enter a parse tree produced by CoexParser#mapEntryList.
    def enterMapEntryList(self, ctx:CoexParser.MapEntryListContext):
        pass

    # Exit a parse tree produced by CoexParser#mapEntryList.
    def exitMapEntryList(self, ctx:CoexParser.MapEntryListContext):
        pass


    # Enter a parse tree produced by CoexParser#mapEntry.
    def enterMapEntry(self, ctx:CoexParser.MapEntryContext):
        pass

    # Exit a parse tree produced by CoexParser#mapEntry.
    def exitMapEntry(self, ctx:CoexParser.MapEntryContext):
        pass


    # Enter a parse tree produced by CoexParser#lambdaExpr.
    def enterLambdaExpr(self, ctx:CoexParser.LambdaExprContext):
        pass

    # Exit a parse tree produced by CoexParser#lambdaExpr.
    def exitLambdaExpr(self, ctx:CoexParser.LambdaExprContext):
        pass


    # Enter a parse tree produced by CoexParser#argumentList.
    def enterArgumentList(self, ctx:CoexParser.ArgumentListContext):
        pass

    # Exit a parse tree produced by CoexParser#argumentList.
    def exitArgumentList(self, ctx:CoexParser.ArgumentListContext):
        pass


    # Enter a parse tree produced by CoexParser#argument.
    def enterArgument(self, ctx:CoexParser.ArgumentContext):
        pass

    # Exit a parse tree produced by CoexParser#argument.
    def exitArgument(self, ctx:CoexParser.ArgumentContext):
        pass


    # Enter a parse tree produced by CoexParser#genericArgs.
    def enterGenericArgs(self, ctx:CoexParser.GenericArgsContext):
        pass

    # Exit a parse tree produced by CoexParser#genericArgs.
    def exitGenericArgs(self, ctx:CoexParser.GenericArgsContext):
        pass


    # Enter a parse tree produced by CoexParser#typeExpr.
    def enterTypeExpr(self, ctx:CoexParser.TypeExprContext):
        pass

    # Exit a parse tree produced by CoexParser#typeExpr.
    def exitTypeExpr(self, ctx:CoexParser.TypeExprContext):
        pass


    # Enter a parse tree produced by CoexParser#baseType.
    def enterBaseType(self, ctx:CoexParser.BaseTypeContext):
        pass

    # Exit a parse tree produced by CoexParser#baseType.
    def exitBaseType(self, ctx:CoexParser.BaseTypeContext):
        pass


    # Enter a parse tree produced by CoexParser#primitiveType.
    def enterPrimitiveType(self, ctx:CoexParser.PrimitiveTypeContext):
        pass

    # Exit a parse tree produced by CoexParser#primitiveType.
    def exitPrimitiveType(self, ctx:CoexParser.PrimitiveTypeContext):
        pass


    # Enter a parse tree produced by CoexParser#tupleType.
    def enterTupleType(self, ctx:CoexParser.TupleTypeContext):
        pass

    # Exit a parse tree produced by CoexParser#tupleType.
    def exitTupleType(self, ctx:CoexParser.TupleTypeContext):
        pass


    # Enter a parse tree produced by CoexParser#tupleTypeElement.
    def enterTupleTypeElement(self, ctx:CoexParser.TupleTypeElementContext):
        pass

    # Exit a parse tree produced by CoexParser#tupleTypeElement.
    def exitTupleTypeElement(self, ctx:CoexParser.TupleTypeElementContext):
        pass


    # Enter a parse tree produced by CoexParser#functionType.
    def enterFunctionType(self, ctx:CoexParser.FunctionTypeContext):
        pass

    # Exit a parse tree produced by CoexParser#functionType.
    def exitFunctionType(self, ctx:CoexParser.FunctionTypeContext):
        pass


    # Enter a parse tree produced by CoexParser#typeList.
    def enterTypeList(self, ctx:CoexParser.TypeListContext):
        pass

    # Exit a parse tree produced by CoexParser#typeList.
    def exitTypeList(self, ctx:CoexParser.TypeListContext):
        pass



del CoexParser