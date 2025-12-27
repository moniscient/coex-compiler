"""
Coex Compiler Commentary System

Implements bidirectional communication between compiler and programmer through #@ annotations.
The compiler writes suggestions, warnings, and optimization hints directly into source files.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Set, Tuple
import hashlib
import re


class CommentaryCategory(Enum):
    """Categories of compiler commentary."""
    WARN = auto()   # Potential bugs or unsafe patterns
    HINT = auto()   # Suggestions for improvement
    PERF = auto()   # Performance optimization opportunities
    TEACH = auto()  # Educational explanations
    KIND = auto()   # Function kind violations or suggestions
    TYPE = auto()   # Type-related observations
    GC = auto()     # Garbage collection hints
    MOVE = auto()   # Move semantics suggestions


class CommentaryResponse(Enum):
    """Programmer responses to compiler commentary."""
    NONE = auto()    # Default, will be regenerated
    IGNORE = auto()  # Acknowledged, preserved
    OFF = auto()     # Suppressed permanently


@dataclass
class CompilerComment:
    """A single compiler commentary annotation."""
    category: CommentaryCategory
    message: str
    line: int
    column: int = 1
    response: CommentaryResponse = CommentaryResponse.NONE
    message_hash: str = ""

    def __post_init__(self):
        if not self.message_hash:
            self.message_hash = hashlib.sha256(
                f"{self.category.name}:{self.message}".encode()
            ).hexdigest()[:8]

    def to_string(self) -> str:
        """Convert comment to source string format."""
        if self.response == CommentaryResponse.NONE:
            return f"#@ [{self.category.name}] {self.message}"
        else:
            return f"#@ [{self.category.name}:{self.response.name.lower()}] {self.message}"


@dataclass
class CommentaryState:
    """Tracks all commentary for a source file."""
    file_path: str
    comments: List[CompilerComment] = field(default_factory=list)
    suppressed_hashes: Set[str] = field(default_factory=set)


# Pattern to match #@ comments: #@ [CATEGORY] message or #@ [CATEGORY:response] message
COMMENTARY_PATTERN = re.compile(
    r'^(\s*)#@\s*\[(\w+)(?::(\w+))?\]\s*(.+)$'
)


def parse_commentary(source: str) -> Tuple[str, List[CompilerComment]]:
    """
    Extract #@ comments from source.

    Returns:
        Tuple of (cleaned source without #@ comments, list of extracted comments)
    """
    lines = source.split('\n')
    comments = []
    clean_lines = []
    line_offset = 0  # Track offset as we remove comment lines

    for line_num, line in enumerate(lines, 1):
        match = COMMENTARY_PATTERN.match(line)
        if match:
            indent, category_str, response_str, message = match.groups()
            try:
                category = CommentaryCategory[category_str.upper()]
                response = CommentaryResponse[response_str.upper()] if response_str else CommentaryResponse.NONE
                comments.append(CompilerComment(
                    category=category,
                    message=message.strip(),
                    line=line_num - line_offset,  # Adjusted line for clean source
                    column=len(indent) + 1,
                    response=response
                ))
                line_offset += 1
            except KeyError:
                # Unknown category/response, keep the line as-is
                clean_lines.append(line)
        else:
            clean_lines.append(line)

    return '\n'.join(clean_lines), comments


def merge_commentary(
    existing: List[CompilerComment],
    generated: List[CompilerComment],
    suppressed: Set[str]
) -> Tuple[List[CompilerComment], Set[str]]:
    """
    Merge existing and generated commentary.

    Args:
        existing: Comments from the current source file
        generated: New comments from analyzers
        suppressed: Set of message hashes that are permanently suppressed

    Returns:
        Tuple of (merged comments, updated suppressed set)
    """
    result = []
    updated_suppressed = set(suppressed)

    # Build lookup for existing comments by hash
    existing_by_hash = {c.message_hash: c for c in existing}

    # Process generated comments
    for comment in generated:
        if comment.message_hash in updated_suppressed:
            # Permanently suppressed, skip
            continue

        if comment.message_hash in existing_by_hash:
            existing_comment = existing_by_hash[comment.message_hash]
            if existing_comment.response == CommentaryResponse.IGNORE:
                # Keep with ignore response, update line number
                existing_comment.line = comment.line
                result.append(existing_comment)
            elif existing_comment.response == CommentaryResponse.OFF:
                # Add to suppressed, don't include
                updated_suppressed.add(comment.message_hash)
            else:
                # NONE response, use new generated comment
                result.append(comment)
        else:
            # New comment
            result.append(comment)

    return result, updated_suppressed


def write_commentary(source: str, comments: List[CompilerComment]) -> str:
    """
    Insert #@ comments into source at appropriate locations.

    Args:
        source: Clean source code (without existing #@ comments)
        comments: Comments to insert

    Returns:
        Source code with #@ comments inserted
    """
    if not comments:
        return source

    lines = source.split('\n')

    # Sort comments by line (descending) to insert from bottom up
    # This preserves line numbers during insertion
    sorted_comments = sorted(comments, key=lambda c: c.line, reverse=True)

    for comment in sorted_comments:
        # Determine indentation from target line
        target_idx = comment.line - 1
        if 0 <= target_idx < len(lines):
            target_line = lines[target_idx]
            indent = len(target_line) - len(target_line.lstrip())
            indent_str = ' ' * indent
        else:
            indent_str = ''

        comment_line = f"{indent_str}{comment.to_string()}"

        # Insert before the target line
        if target_idx >= 0:
            lines.insert(target_idx, comment_line)

    return '\n'.join(lines)


class EducationalError:
    """Generates educational error messages explaining why something isn't allowed."""

    MESSAGES = {
        ('FORMULA', 'mutable_var'): (
            "You tried to: Declare a rebindable binding in a formula\n\n"
            "Why it's not allowed: Formulas must be pure--they cannot have internal state "
            "that changes between calls. Rebindable bindings allow the function to behave "
            "differently on repeated calls with the same arguments.\n\n"
            "What to do: Use 'const' for all bindings in formulas, or change to 'func' if "
            "you need rebindable bindings.\n\n"
            "Trade-off: Funcs cannot be freely memoized or parallelized by the compiler."
        ),
        ('FORMULA', 'call_extern'): (
            "You tried to: Call extern function '{context}' from a formula\n\n"
            "Why it's not allowed: Formulas guarantee purity--same inputs always produce "
            "same outputs. Extern functions interact with the outside world and cannot "
            "make this guarantee.\n\n"
            "What to do: Change to 'func' to call extern functions.\n\n"
            "Trade-off: You lose purity guarantees and compiler optimizations."
        ),
        ('TASK', 'call_extern'): (
            "You tried to: Call extern function '{context}' from a task\n\n"
            "Why it's not allowed: Tasks provide concurrency safety guarantees. Extern "
            "functions operate outside Coex's safety model and could cause data races.\n\n"
            "What to do: Wrap the extern call in a 'func', then call that func from your task.\n\n"
            "Trade-off: The func becomes a synchronization point."
        ),
        ('FORMULA', 'call_func'): (
            "You tried to: Call func '{context}' from a formula\n\n"
            "Why it's not allowed: Formulas must be pure and deterministic. Funcs may have "
            "side effects (print, modify atomics, call extern) that would violate purity.\n\n"
            "What to do: Either change the callee to 'formula' if it's actually pure, "
            "or change this function to 'func'.\n\n"
            "Trade-off: Formulas can call formulas; funcs can call anything."
        ),
    }

    @staticmethod
    def get_message(kind_name: str, attempted_action: str, context: str = "") -> str:
        """Get educational error message for a function kind violation."""
        key = (kind_name.upper(), attempted_action)
        if key in EducationalError.MESSAGES:
            message = EducationalError.MESSAGES[key]
            return message.format(context=context)
        return f"Action '{attempted_action}' not allowed in {kind_name}"


def raise_educational_error(
    kind_name: str,
    attempted_action: str,
    context: str = "",
    line: int = None
):
    """Raise an error with educational message."""
    message = EducationalError.get_message(kind_name, attempted_action, context)
    location = f" at line {line}" if line else ""
    raise RuntimeError(f"Error in {kind_name.lower()}{location}:\n\n{message}")
