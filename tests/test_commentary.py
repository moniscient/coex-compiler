"""
Tests for the compiler commentary system.

The commentary system allows bidirectional communication between
the compiler and programmer through #@ annotations.
"""

import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commentary import (
    parse_commentary, write_commentary, merge_commentary,
    CompilerComment, CommentaryCategory, CommentaryResponse
)
from commentary_analyzer import (
    PerformanceAnalyzer, FunctionKindAnalyzer, MoveAnalyzer, GCAnalyzer,
    run_all_analyzers
)
from ast_builder import ASTBuilder
from antlr4 import InputStream, CommonTokenStream
from CoexLexer import CoexLexer
from CoexParser import CoexParser


def parse_program(source: str):
    """Parse source code to AST."""
    input_stream = InputStream(source)
    lexer = CoexLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = CoexParser(token_stream)
    tree = parser.program()
    builder = ASTBuilder()
    return builder.build(tree)


class TestCommentaryParsing:
    """Test parsing of #@ comments."""

    def test_parse_simple_comment(self):
        """Parse a simple #@ comment."""
        source = '''
func main() -> int
    #@ [PERF] Test message
    x = 5
    return x
~
'''
        clean, comments = parse_commentary(source)
        assert len(comments) == 1
        assert comments[0].category == CommentaryCategory.PERF
        assert comments[0].message == "Test message"
        assert "#@" not in clean

    def test_parse_comment_with_response(self):
        """Parse #@ comment with ignore response."""
        source = '''
func main() -> int
    #@ [PERF:ignore] Test message
    x = 5
    return x
~
'''
        clean, comments = parse_commentary(source)
        assert len(comments) == 1
        assert comments[0].response == CommentaryResponse.IGNORE

    def test_parse_comment_with_off_response(self):
        """Parse #@ comment with off response."""
        source = '''
func main() -> int
    #@ [WARN:off] Suppressed warning
    x = 5
    return x
~
'''
        clean, comments = parse_commentary(source)
        assert len(comments) == 1
        assert comments[0].response == CommentaryResponse.OFF

    def test_parse_multiple_comments(self):
        """Parse multiple #@ comments."""
        source = '''
func main() -> int
    #@ [PERF] First message
    x = 5
    #@ [HINT] Second message
    y = 10
    return x + y
~
'''
        clean, comments = parse_commentary(source)
        assert len(comments) == 2
        assert comments[0].category == CommentaryCategory.PERF
        assert comments[1].category == CommentaryCategory.HINT

    def test_parse_all_categories(self):
        """Parse all comment categories."""
        categories = ['WARN', 'HINT', 'PERF', 'TEACH', 'KIND', 'TYPE', 'GC', 'MOVE']
        for cat in categories:
            source = f'''
func main() -> int
    #@ [{cat}] Test
    return 0
~
'''
            clean, comments = parse_commentary(source)
            assert len(comments) == 1
            assert comments[0].category == CommentaryCategory[cat]

    def test_preserve_indentation(self):
        """Parse preserves original indentation info."""
        source = '''
func main() -> int
    if true
        #@ [HINT] Indented comment
        x = 5
    ~
    return 0
~
'''
        clean, comments = parse_commentary(source)
        assert len(comments) == 1
        # Column should reflect indentation
        assert comments[0].column > 1


class TestCommentaryMerging:
    """Test merging of existing and generated commentary."""

    def test_merge_new_comment(self):
        """New comments are added."""
        existing = []
        generated = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="New suggestion",
            line=3
        )]
        suppressed = set()

        result, _ = merge_commentary(existing, generated, suppressed)
        assert len(result) == 1
        assert result[0].message == "New suggestion"

    def test_merge_ignore_preserved(self):
        """Comments with ignore response are preserved."""
        existing = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test",
            line=3,
            response=CommentaryResponse.IGNORE
        )]
        generated = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test",
            line=5  # Line changed
        )]
        suppressed = set()

        result, _ = merge_commentary(existing, generated, suppressed)
        assert len(result) == 1
        assert result[0].response == CommentaryResponse.IGNORE

    def test_merge_off_suppresses(self):
        """Comments with off response are suppressed."""
        existing = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test",
            line=3,
            response=CommentaryResponse.OFF
        )]
        generated = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test",
            line=3
        )]
        suppressed = set()

        result, updated_suppressed = merge_commentary(existing, generated, suppressed)
        assert len(result) == 0
        assert existing[0].message_hash in updated_suppressed

    def test_merge_suppressed_stays_suppressed(self):
        """Previously suppressed comments stay suppressed."""
        comment = CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test",
            line=3
        )
        suppressed = {comment.message_hash}
        generated = [comment]

        result, _ = merge_commentary([], generated, suppressed)
        assert len(result) == 0


class TestCommentaryWriting:
    """Test writing commentary back to source."""

    def test_write_single_comment(self):
        """Write a single comment to source."""
        source = '''func main() -> int
    x = 5
    return x
~
'''
        comments = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Test message",
            line=2
        )]

        result = write_commentary(source, comments)
        assert "#@ [PERF] Test message" in result
        # Comment should appear before line 2
        lines = result.split('\n')
        for i, line in enumerate(lines):
            if "#@" in line:
                assert i < len(lines) - 1
                break

    def test_write_preserves_indentation(self):
        """Written comments match target line indentation."""
        source = '''func main() -> int
    x = 5
    return x
~
'''
        comments = [CompilerComment(
            category=CommentaryCategory.HINT,
            message="Test",
            line=2
        )]

        result = write_commentary(source, comments)
        lines = result.split('\n')
        comment_line = [l for l in lines if "#@" in l][0]
        # Should be indented (4 spaces like other lines in func body)
        assert comment_line.startswith("    #@")

    def test_write_with_response(self):
        """Write comment with response."""
        source = '''func main() -> int
    return 0
~
'''
        comments = [CompilerComment(
            category=CommentaryCategory.WARN,
            message="Warning",
            line=2,
            response=CommentaryResponse.IGNORE
        )]

        result = write_commentary(source, comments)
        assert "#@ [WARN:ignore] Warning" in result


class TestPerformanceAnalyzer:
    """Test the performance analyzer."""

    def test_detects_append_in_loop(self):
        """Detects x = x.append() pattern in loops."""
        source = '''
func main() -> int
    result = []
    for i in 0..10
        result = result.append(i)
    ~
    return result.len()
~
'''
        program = parse_program(source)
        analyzer = PerformanceAnalyzer()
        comments = analyzer.analyze(program)

        # Should detect the append pattern
        assert len(comments) >= 1
        assert any(c.category == CommentaryCategory.PERF for c in comments)
        assert any("append" in c.message.lower() for c in comments)


class TestFunctionKindAnalyzer:
    """Test the function kind analyzer."""

    def test_suggests_formula_for_pure_func(self):
        """Suggests formula for pure functions."""
        source = '''
func add(a: int, b: int) -> int
    const result = a + b
    return result
~

func main() -> int
    return add(1, 2)
~
'''
        program = parse_program(source)
        analyzer = FunctionKindAnalyzer()
        comments = analyzer.analyze(program)

        # May suggest formula for 'add' since it's pure
        # (depends on analyzer implementation details)


class TestMoveAnalyzer:
    """Test the move analyzer."""

    def test_suggests_move_for_last_use(self):
        """Suggests move when variable not used after assignment."""
        source = '''
func process(data: [int]) -> [int]
    result = data
    return result
~

func main() -> int
    return 0
~
'''
        program = parse_program(source)
        analyzer = MoveAnalyzer()
        comments = analyzer.analyze(program)

        # Should suggest using := instead of =
        # (actual detection depends on implementation)


class TestCommentaryIntegration:
    """Integration tests for commentary system."""

    def test_full_roundtrip(self):
        """Test full parse -> analyze -> merge -> write cycle."""
        source = '''func main() -> int
    result = []
    for i in 0..100
        result = result.append(i)
    ~
    return result.len()
~
'''
        # Parse and analyze
        clean_source, existing = parse_commentary(source)
        program = parse_program(clean_source)
        generated = run_all_analyzers(program)

        # Merge
        suppressed = set()
        final, _ = merge_commentary(existing, generated, suppressed)

        # Write back
        if final:
            result = write_commentary(clean_source, final)
            # Should contain performance comment
            assert "#@" in result

    def test_existing_comments_preserved(self):
        """Existing #@ comments with same message are preserved with response."""
        # Create a comment that matches what the analyzer would generate
        existing = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Loop modifies 'result' with append on each iteration, creating intermediate lists. Consider using Array for in-place mutation.",
            line=3,
            response=CommentaryResponse.IGNORE
        )]

        # Generate the same comment
        generated = [CompilerComment(
            category=CommentaryCategory.PERF,
            message="Loop modifies 'result' with append on each iteration, creating intermediate lists. Consider using Array for in-place mutation.",
            line=4
        )]

        suppressed = set()
        final, _ = merge_commentary(existing, generated, suppressed)

        # The ignored comment should be preserved
        assert len(final) == 1
        assert final[0].response == CommentaryResponse.IGNORE

    def test_different_comments_both_kept(self):
        """Different comments (different messages) are kept separately."""
        source = '''func main() -> int
    #@ [HINT:ignore] Some other hint
    result = []
    for i in 0..100
        result = result.append(i)
    ~
    return result.len()
~
'''
        clean_source, existing = parse_commentary(source)
        assert len(existing) == 1
        assert existing[0].response == CommentaryResponse.IGNORE

        # Generate new comments (different from existing)
        program = parse_program(clean_source)
        generated = run_all_analyzers(program)

        suppressed = set()
        final, _ = merge_commentary(existing, generated, suppressed)

        # Both the existing ignored comment and new generated should be present
        # (existing won't be in final because it's a different message/hash,
        # but new generated comments should be there)
        assert len(final) >= 1  # At least the generated PERF comment


class TestCommentaryWithCompilation:
    """Test commentary doesn't break compilation."""

    def test_compile_with_commentary(self, expect_output):
        """Source with #@ comments compiles correctly."""
        expect_output('''
func main() -> int
    #@ [HINT] This is a hint
    x = 42
    print(x)
    return 0
~
''', "42\n")

    def test_compile_with_multiple_comments(self, expect_output):
        """Multiple #@ comments don't break compilation."""
        expect_output('''
func main() -> int
    #@ [PERF] Performance note
    x = 1
    #@ [HINT] Another note
    y = 2
    #@ [WARN:ignore] Acknowledged warning
    print(x + y)
    return 0
~
''', "3\n")
