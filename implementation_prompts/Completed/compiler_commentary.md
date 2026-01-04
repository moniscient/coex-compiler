# Compiler Commentary System (`#@` Annotations)

**Priority:** Developer Experience Enhancement
**Complexity:** Medium-High
**Breaking Change:** No (additive feature)

---

## Overview

Coex implements a bidirectional communication channel between the compiler and programmer through `#@` annotations. The compiler writes suggestions, warnings, and optimization hints directly into source files. Programmers can respond to these suggestions, and the compiler updates them on each compilation.

**Key principle**: The compiler owns all `#@` comments. They are regenerated every compilation cycle.

---

## Specification

### Comment Syntax

```coex
#@ [CATEGORY] message
#@ [CATEGORY:response] message
```

Where:
- `CATEGORY` is the type of commentary (WARN, HINT, PERF, TEACH, etc.)
- `response` is the programmer's response (ignore, off, none)
- `message` is the compiler's explanation

### Example

```coex
func process_data(items: [int]) -> int
    #@ [PERF] This loop creates 1000 intermediate lists. Consider using Array for mutation.
    result = []
    for i in 0..1000
        result = result.append(items.get(i) * 2)
    ~
    return result.len()
~
```

After programmer adds response:

```coex
func process_data(items: [int]) -> int
    #@ [PERF:ignore] This loop creates 1000 intermediate lists. Consider using Array for mutation.
    result = []
    for i in 0..1000
        result = result.append(items.get(i) * 2)
    ~
    return result.len()
~
```

### Programmer Responses

| Response | Effect |
|----------|--------|
| `none` | No action; comment reappears if condition persists (default) |
| `ignore` | Acknowledge but preserve; compiler keeps comment but stops warning |
| `off` | Suppress this specific suggestion permanently |

### Commentary Categories

| Category | Purpose |
|----------|---------|
| `WARN` | Potential bugs or unsafe patterns |
| `HINT` | Suggestions for improvement |
| `PERF` | Performance optimization opportunities |
| `TEACH` | Educational explanations (why something works/doesn't) |
| `KIND` | Function kind violations or suggestions |
| `TYPE` | Type-related observations |
| `GC` | Garbage collection hints |
| `MOVE` | Move semantics suggestions |

---

## Lifecycle Management

### Compilation Cycle

1. **Parse**: Read source file, extract existing `#@` comments with responses
2. **Analyze**: Run all analyzers, generate new commentary
3. **Merge**:
   - Keep `#@` comments with `ignore` or `off` responses
   - Remove `#@` comments with `none` or no response if condition no longer applies
   - Add new `#@` comments for new conditions
4. **Write**: Update source file with merged commentary

### Comment Identity

Each comment is identified by:
- Location (line number, adjusted for edits)
- Category
- Message hash (first 8 chars of SHA-256)

This allows the compiler to track comments across edits:

```coex
#@ [PERF:a1b2c3d4] This loop creates 1000 intermediate lists.
```

The hash is hidden from display but used internally for tracking.

---

## Implementation Steps

### Step 1: Commentary Data Structures

Add to `ast_nodes.py` or new `commentary.py`:

```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, List
import hashlib


class CommentaryCategory(Enum):
    WARN = auto()
    HINT = auto()
    PERF = auto()
    TEACH = auto()
    KIND = auto()
    TYPE = auto()
    GC = auto()
    MOVE = auto()


class CommentaryResponse(Enum):
    NONE = auto()      # Default, will be regenerated
    IGNORE = auto()    # Acknowledged, preserved
    OFF = auto()       # Suppressed permanently


@dataclass
class CompilerComment:
    """A single compiler commentary annotation."""
    category: CommentaryCategory
    message: str
    line: int
    column: int
    response: CommentaryResponse = CommentaryResponse.NONE
    message_hash: str = ""

    def __post_init__(self):
        if not self.message_hash:
            self.message_hash = hashlib.sha256(
                f"{self.category.name}:{self.message}".encode()
            ).hexdigest()[:8]

    def to_string(self) -> str:
        if self.response == CommentaryResponse.NONE:
            return f"#@ [{self.category.name}] {self.message}"
        else:
            return f"#@ [{self.category.name}:{self.response.name.lower()}] {self.message}"


@dataclass
class CommentaryState:
    """Tracks all commentary for a source file."""
    file_path: str
    comments: List[CompilerComment]
    suppressed_hashes: set  # Hashes with 'off' response
```

### Step 2: Commentary Parser

Add to lexer/parser or as post-processing:

```python
import re

COMMENTARY_PATTERN = re.compile(
    r'^(\s*)#@\s*\[(\w+)(?::(\w+))?\]\s*(.+)$'
)


def parse_commentary(source: str) -> tuple[str, List[CompilerComment]]:
    """Extract #@ comments from source, return cleaned source and comments."""
    lines = source.split('\n')
    comments = []
    clean_lines = []

    for line_num, line in enumerate(lines, 1):
        match = COMMENTARY_PATTERN.match(line)
        if match:
            indent, category, response, message = match.groups()
            comments.append(CompilerComment(
                category=CommentaryCategory[category.upper()],
                message=message.strip(),
                line=line_num,
                column=len(indent) + 1,
                response=CommentaryResponse[response.upper()] if response else CommentaryResponse.NONE
            ))
            # Don't add to clean_lines - remove from source for parsing
        else:
            clean_lines.append(line)

    return '\n'.join(clean_lines), comments
```

### Step 3: Commentary Analyzer Framework

Create `commentary_analyzer.py`:

```python
from abc import ABC, abstractmethod
from typing import List
from ast_nodes import *


class CommentaryAnalyzer(ABC):
    """Base class for analyzers that generate compiler commentary."""

    @abstractmethod
    def analyze(self, program: Program) -> List[CompilerComment]:
        """Analyze program and return list of commentary."""
        pass


class PerformanceAnalyzer(CommentaryAnalyzer):
    """Detects performance anti-patterns."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []

        for func in program.functions:
            comments.extend(self._analyze_function(func))

        return comments

    def _analyze_function(self, func: FunctionDecl) -> List[CompilerComment]:
        comments = []

        # Detect loop with repeated list append
        for stmt in self._walk_statements(func.body):
            if isinstance(stmt, ForStmt):
                if self._has_repeated_append(stmt):
                    comments.append(CompilerComment(
                        category=CommentaryCategory.PERF,
                        message=(
                            "This loop creates intermediate lists on each iteration. "
                            "Consider using Array for in-place mutation, then convert to List."
                        ),
                        line=stmt.line,
                        column=1
                    ))

        return comments

    def _has_repeated_append(self, for_stmt: ForStmt) -> bool:
        """Check if loop body has x = x.append(...) pattern."""
        for stmt in for_stmt.body:
            if isinstance(stmt, Assignment):
                if isinstance(stmt.target, Identifier):
                    if isinstance(stmt.value, MethodCallExpr):
                        if stmt.value.method == 'append':
                            if isinstance(stmt.value.object, Identifier):
                                if stmt.value.object.name == stmt.target.name:
                                    return True
        return False

    def _walk_statements(self, stmts):
        """Recursively walk all statements."""
        for stmt in stmts:
            yield stmt
            if isinstance(stmt, ForStmt):
                yield from self._walk_statements(stmt.body)
            elif isinstance(stmt, IfStmt):
                yield from self._walk_statements(stmt.then_body)
                for _, body in stmt.else_if_clauses:
                    yield from self._walk_statements(body)
                if stmt.else_body:
                    yield from self._walk_statements(stmt.else_body)
            # ... other compound statements


class FunctionKindAnalyzer(CommentaryAnalyzer):
    """Suggests appropriate function kinds."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []

        for func in program.functions:
            suggestion = self._suggest_kind(func)
            if suggestion:
                comments.append(suggestion)

        return comments

    def _suggest_kind(self, func: FunctionDecl) -> Optional[CompilerComment]:
        # If func could be formula (no side effects)
        if func.kind == FunctionKind.FUNC:
            if self._is_pure(func):
                return CompilerComment(
                    category=CommentaryCategory.KIND,
                    message=(
                        f"Function '{func.name}' appears to be pure. "
                        f"Consider using 'formula' for compiler optimization and purity guarantees."
                    ),
                    line=func.line,
                    column=1
                )
        return None

    def _is_pure(self, func: FunctionDecl) -> bool:
        """Check if function has no side effects."""
        # Check for print, extern calls, etc.
        # ... implementation
        return False


class MoveAnalyzer(CommentaryAnalyzer):
    """Suggests move semantics opportunities."""

    def analyze(self, program: Program) -> List[CompilerComment]:
        comments = []

        for func in program.functions:
            for stmt in self._walk_statements(func.body):
                if isinstance(stmt, VarDecl) or isinstance(stmt, Assignment):
                    suggestion = self._check_move_opportunity(stmt)
                    if suggestion:
                        comments.append(suggestion)

        return comments

    def _check_move_opportunity(self, stmt) -> Optional[CompilerComment]:
        """Check if := could be used instead of =."""
        # If source variable is not used after this point
        # ... implementation
        return None
```

### Step 4: Educational Error Messages

Enhance error generation in `codegen.py`:

```python
class EducationalError:
    """Generates educational error messages."""

    @staticmethod
    def function_kind_violation(
        attempted_action: str,
        current_kind: FunctionKind,
        required_kind: FunctionKind,
        context: str
    ) -> str:
        messages = {
            (FunctionKind.FORMULA, 'mutable_var'): (
                f"You tried to: Declare a rebindable binding in a formula\n"
                f"Why it's not allowed: Formulas must be pure—they cannot have internal state "
                f"that changes between calls. Rebindable bindings allow the function to behave "
                f"differently on repeated calls with the same arguments.\n"
                f"What to do: Use 'const' for all bindings in formulas, or change to 'func' if "
                f"you need rebindable bindings.\n"
                f"Trade-off: Funcs cannot be freely memoized or parallelized by the compiler."
            ),
            (FunctionKind.FORMULA, 'call_extern'): (
                f"You tried to: Call extern function '{context}' from a formula\n"
                f"Why it's not allowed: Formulas guarantee purity—same inputs always produce "
                f"same outputs. Extern functions interact with the outside world and cannot "
                f"make this guarantee.\n"
                f"What to do: Change to 'func' to call extern functions.\n"
                f"Trade-off: You lose purity guarantees and compiler optimizations."
            ),
            (FunctionKind.TASK, 'call_extern'): (
                f"You tried to: Call extern function '{context}' from a task\n"
                f"Why it's not allowed: Tasks provide concurrency safety guarantees. Extern "
                f"functions operate outside Coex's safety model and could cause data races.\n"
                f"What to do: Wrap the extern call in a 'func', then call that func from your task.\n"
                f"Trade-off: The func becomes a synchronization point."
            ),
        }

        key = (current_kind, attempted_action)
        if key in messages:
            return messages[key]

        return f"Action '{attempted_action}' not allowed in {current_kind.name.lower()}"


def raise_educational_error(
    attempted_action: str,
    current_kind: FunctionKind,
    required_kind: FunctionKind = None,
    context: str = ""
):
    message = EducationalError.function_kind_violation(
        attempted_action, current_kind, required_kind, context
    )
    raise RuntimeError(message)
```

### Step 5: Commentary Merger

```python
def merge_commentary(
    existing: List[CompilerComment],
    generated: List[CompilerComment],
    suppressed: set
) -> List[CompilerComment]:
    """Merge existing and generated commentary."""
    result = []

    # Build lookup for existing comments
    existing_by_hash = {c.message_hash: c for c in existing}

    # Process generated comments
    for comment in generated:
        if comment.message_hash in suppressed:
            # Permanently suppressed, skip
            continue

        if comment.message_hash in existing_by_hash:
            existing_comment = existing_by_hash[comment.message_hash]
            if existing_comment.response == CommentaryResponse.IGNORE:
                # Keep with ignore response
                result.append(existing_comment)
            elif existing_comment.response == CommentaryResponse.OFF:
                # Add to suppressed, don't include
                suppressed.add(comment.message_hash)
            else:
                # NONE response, regenerate
                result.append(comment)
        else:
            # New comment
            result.append(comment)

    return result
```

### Step 6: Source File Writer

```python
def write_commentary(source: str, comments: List[CompilerComment]) -> str:
    """Insert #@ comments into source at appropriate locations."""
    lines = source.split('\n')

    # Sort comments by line (descending) to insert from bottom up
    sorted_comments = sorted(comments, key=lambda c: c.line, reverse=True)

    for comment in sorted_comments:
        # Determine indentation from target line
        if comment.line <= len(lines):
            target_line = lines[comment.line - 1]
            indent = len(target_line) - len(target_line.lstrip())
            indent_str = ' ' * indent
        else:
            indent_str = ''

        comment_line = f"{indent_str}{comment.to_string()}"

        # Insert before the target line
        lines.insert(comment.line - 1, comment_line)

    return '\n'.join(lines)
```

### Step 7: Integration with Compiler Pipeline

Update `coexc.py` or main compiler:

```python
def compile_with_commentary(source_path: str, output_path: str):
    """Compile source file and update with commentary."""

    # Read source
    with open(source_path, 'r') as f:
        source = f.read()

    # Extract existing commentary
    clean_source, existing_comments = parse_commentary(source)

    # Build suppressed set
    suppressed = {
        c.message_hash for c in existing_comments
        if c.response == CommentaryResponse.OFF
    }

    # Parse and analyze
    program = parse(clean_source)

    # Run analyzers
    analyzers = [
        PerformanceAnalyzer(),
        FunctionKindAnalyzer(),
        MoveAnalyzer(),
        # ... more analyzers
    ]

    generated_comments = []
    for analyzer in analyzers:
        generated_comments.extend(analyzer.analyze(program))

    # Merge commentary
    final_comments = merge_commentary(existing_comments, generated_comments, suppressed)

    # Write updated source with commentary
    updated_source = write_commentary(clean_source, final_comments)

    with open(source_path, 'w') as f:
        f.write(updated_source)

    # Continue with code generation
    codegen = CodeGenerator()
    codegen.generate(program)
    # ... output handling
```

### Step 8: CLI Flags

Add flags to control commentary:

```
coexc source.coex -o output          # Normal compile with commentary
coexc source.coex --no-commentary    # Compile without updating commentary
coexc source.coex --strip-commentary # Remove all #@ comments
coexc source.coex --commentary-only  # Only update commentary, don't compile
```

---

## Example Commentary Output

### Performance Warning

```coex
func build_large_list() -> [int]
    #@ [PERF] Loop creates 10000 intermediate lists. Consider:
    #@        arr = Array(10000, 0)
    #@        for i in 0..10000: arr[i] = i * 2
    #@        return arr.to_list()
    result = []
    for i in 0..10000
        result = result.append(i * 2)
    ~
    return result
~
```

### Function Kind Suggestion

```coex
#@ [KIND] Function 'add' is pure. Consider 'formula add(a: int, b: int) -> int'
#@        for compiler optimizations and memoization.
func add(a: int, b: int) -> int
    return a + b
~
```

### Move Opportunity

```coex
func process(data: [int]) -> [int]
    #@ [MOVE] Variable 'data' is not used after this line. Consider:
    #@        result := data  (move instead of copy)
    result = data
    return result.append(0)
~
```

### Educational Error (in error output, not source)

```
Error in formula 'compute' at line 5:

You tried to: Declare a rebindable binding 'x' in a formula

Why it's not allowed: Formulas must be pure—they cannot have internal
state that changes between calls. Rebindable bindings allow the function
to behave differently on repeated calls with the same arguments.

What to do: Use 'const x = ...' for all bindings in formulas, or change
to 'func' if you need rebindable bindings.

Trade-off: Funcs cannot be freely memoized or parallelized by the compiler.
```

---

## Test Cases

### Commentary Parsing

```python
def test_parse_commentary():
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
```

### Response Preservation

```python
def test_ignore_response_preserved():
    source = '''
func main() -> int
    #@ [PERF:ignore] Test message
    x = 5
    return x
~
'''
    clean, comments = parse_commentary(source)
    assert comments[0].response == CommentaryResponse.IGNORE
```

### Suppression

```python
def test_off_suppresses_future():
    existing = [CompilerComment(
        category=CommentaryCategory.PERF,
        message="Test",
        line=3,
        column=1,
        response=CommentaryResponse.OFF
    )]

    generated = [CompilerComment(
        category=CommentaryCategory.PERF,
        message="Test",
        line=3,
        column=1
    )]

    suppressed = set()
    result = merge_commentary(existing, generated, suppressed)
    assert len(result) == 0
    assert existing[0].message_hash in suppressed
```

---

## Implementation Checklist

- [ ] Data structures: Add `CompilerComment`, `CommentaryCategory`, `CommentaryResponse`
- [ ] Parser: Add `parse_commentary()` to extract #@ comments
- [ ] Parser: Ensure #@ comments don't interfere with regular parsing
- [ ] Analyzer framework: Create `CommentaryAnalyzer` base class
- [ ] Analyzer: Implement `PerformanceAnalyzer`
- [ ] Analyzer: Implement `FunctionKindAnalyzer`
- [ ] Analyzer: Implement `MoveAnalyzer`
- [ ] Analyzer: Implement `GCAnalyzer` (GC pressure hints)
- [ ] Merger: Implement `merge_commentary()` with response handling
- [ ] Writer: Implement `write_commentary()` for source updates
- [ ] Educational errors: Create `EducationalError` class
- [ ] Educational errors: Update all error messages to be educational
- [ ] CLI: Add `--no-commentary` flag
- [ ] CLI: Add `--strip-commentary` flag
- [ ] CLI: Add `--commentary-only` flag
- [ ] Tests: Commentary parsing tests
- [ ] Tests: Response handling tests
- [ ] Tests: Analyzer tests
- [ ] Tests: Merger tests
- [ ] Docs: Update CLAUDE.md with commentary documentation

---

## Notes

- Commentary is opt-out, not opt-in—it appears by default
- The compiler should be conservative—only comment on high-confidence suggestions
- Multi-line commentary uses `#@` continuation lines with extra indentation
- Commentary survives code edits through hash-based identity
- Educational errors appear in stderr, not in source files
- Consider adding `--verbose-commentary` for more detailed suggestions
