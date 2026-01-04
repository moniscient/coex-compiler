# Remove `loop` Keyword - Use `while true` Instead

**Priority:** Language Simplification
**Complexity:** Low
**Breaking Change:** Yes - removes `loop` keyword

---

## Motivation

The `loop` keyword is syntactic sugar for `while true`. Removing it:

1. **Reduces keyword count** - one less reserved word to learn
2. **Improves consistency** - infinite loops use the same construct as conditional loops
3. **Matches common practice** - `while true` is universally understood

---

## Change Summary

### Before

```coex
loop
    print("forever")
    if done
        break
    ~
~
```

### After

```coex
while true
    print("forever")
    if done
        break
    ~
~
```

---

## Implementation Steps

### Step 1: Grammar Changes (CoexLexer.g4)

Remove the `LOOP` token:

```antlr
// Remove this line:
// LOOP: 'loop';
```

### Step 2: Grammar Changes (CoexParser.g4)

Remove the `loopStmt` rule entirely:

```antlr
// Remove this rule:
// loopStmt
//     : LOOP NEWLINE block blockTerminator
//     ;
```

Update the `statement` rule to remove `loopStmt`:

```antlr
statement
    : varDeclStmt
    | ifStmt
    | forStmt
    | whileStmt          // Keep this
    // | loopStmt        // Remove this
    | matchStmt
    | selectStmt
    | withinStmt
    | returnStmt
    | breakStmt
    | continueStmt
    | assignmentStmt
    | exprStmt
    ;
```

### Step 3: Regenerate Parser

```bash
antlr -Dlanguage=Python3 -visitor Coex.g4
```

### Step 4: AST Changes (ast_nodes.py)

Remove the `LoopStmt` class:

```python
# Remove this class:
# @dataclass
# class LoopStmt(Stmt):
#     """Infinite loop: loop block"""
#     body: List[Stmt]
```

### Step 5: AST Builder Changes (ast_builder.py)

Remove the `visitLoopStmt` method:

```python
# Remove this method:
# def visitLoopStmt(self, ctx):
#     body = self.visit(ctx.block())
#     return LoopStmt(body=body)
```

### Step 6: Codegen Changes (codegen.py)

#### Remove `_generate_loop()` method

Delete the entire method (~line 9883-9921):

```python
# Remove this method:
# def _generate_loop(self, stmt: LoopStmt):
#     """Generate an infinite loop"""
#     ...
```

#### Remove from `_generate_statement()`

Remove the `LoopStmt` case (~line 9148):

```python
def _generate_statement(self, stmt: Stmt):
    # ...
    # Remove this case:
    # elif isinstance(stmt, LoopStmt):
    #     self._generate_loop(stmt)
    # ...
```

#### Update helper methods that reference LoopStmt

Search for `LoopStmt` and remove/update:

1. `_find_cycle_declared_vars()` (~line 10105):
```python
# Remove this case:
# elif isinstance(stmt, LoopStmt):
#     declared.update(self._find_cycle_declared_vars(stmt.body))
```

2. `_has_collection_mutations()` (~line 10184):
```python
# Remove this case:
# elif isinstance(stmt, LoopStmt):
#     if self._has_collection_mutations(stmt.body):
#         return True
```

3. `_collect_var_usage()` (~line 10251):
```python
# Remove this case:
# elif isinstance(stmt, LoopStmt):
#     self._collect_var_usage(stmt.body, written, read)
```

### Step 7: Update Tests

Replace all uses of `loop` with `while true`:

**Before:**
```coex
func main() -> int
    x = 0
    loop
        x = x + 1
        if x > 5
            break
        ~
    ~
    print(x)
    return 0
~
```

**After:**
```coex
func main() -> int
    x = 0
    while true
        x = x + 1
        if x > 5
            break
        ~
    ~
    print(x)
    return 0
~
```

### Step 8: Update Documentation

Update `CLAUDE.md` to remove `loop` from the feature list and examples.

---

## Migration

Simple text replacement:

```bash
# Replace 'loop' at start of line (with optional whitespace) with 'while true'
sed -i 's/^\(\s*\)loop$/\1while true/' *.coex
```

Or with grep to find files first:
```bash
grep -l '^\s*loop$' *.coex | xargs sed -i 's/^\(\s*\)loop$/\1while true/'
```

---

## Test Cases

### Basic Infinite Loop with Break

```python
def test_while_true_with_break(self, expect_output):
    expect_output('''
func main() -> int
    x = 0
    while true
        x = x + 1
        if x > 5
            break
        ~
    ~
    print(x)
    return 0
~
''', "6\n")
```

### While True with Continue

```python
def test_while_true_with_continue(self, expect_output):
    expect_output('''
func main() -> int
    x = 0
    count = 0
    while true
        x = x + 1
        if x > 10
            break
        ~
        if x % 2 == 0
            continue
        ~
        count = count + 1
    ~
    print(count)
    return 0
~
''', "5\n")
```

### Verify `loop` is Syntax Error

```python
def test_loop_keyword_removed(self, compile_coex):
    """The 'loop' keyword should no longer be recognized."""
    with pytest.raises(Exception):  # Parser error
        compile_coex('''
func main() -> int
    loop
        break
    ~
    return 0
~
''')
```

---

## Implementation Checklist

- [ ] Lexer: Remove `LOOP` token from `CoexLexer.g4`
- [ ] Parser: Remove `loopStmt` rule from `CoexParser.g4`
- [ ] Parser: Remove `loopStmt` from `statement` alternatives
- [ ] Parser: Regenerate with `antlr -Dlanguage=Python3 -visitor Coex.g4`
- [ ] AST: Remove `LoopStmt` class from `ast_nodes.py`
- [ ] Builder: Remove `visitLoopStmt` from `ast_builder.py`
- [ ] Codegen: Remove `_generate_loop()` method
- [ ] Codegen: Remove `LoopStmt` case from `_generate_statement()`
- [ ] Codegen: Remove `LoopStmt` references from helper methods
- [ ] Tests: Replace all `loop` with `while true` in test files
- [ ] Tests: Add test verifying `loop` is no longer valid syntax
- [ ] Docs: Update `CLAUDE.md`

---

## Notes

- This is a straightforward removal with no semantic changes
- `while true` generates identical IR to the old `loop`
- No performance difference—the optimizer treats them the same
- Reduces cognitive load by having one loop construct instead of two
