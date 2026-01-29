# Coex Programming Bible Reconciliation

## Context

I have a Word document called the "Coex Programming Bible" that serves as the language specification and guide. The document has drifted out of sync with the actual compiler implementation. I need you to systematically reconcile the book with the current codebase, making minimal edits to bring the documentation into alignment without rewriting my prose or restructuring the document.

## Your Task

Work through the document section by section. For each section:

1. **Extract claims**: Read the section and identify every concrete claim it makes—syntax examples, semantic rules, type behaviors, function kinds, concurrency semantics, error messages, etc.

2. **Verify against implementation**: Search the compiler/runtime codebase to verify each claim. Look at:
   - ANTLR grammar files for syntax
   - Compiler passes for semantic rules
   - Runtime implementation for behavior
   - Test files for expected behavior examples

3. **Categorize discrepancies**:
   - **Outdated**: Book says X, implementation does Y (implementation is correct)
   - **Missing**: Implementation has feature Z not documented
   - **Ambiguous**: Unclear whether book or implementation reflects intended design (flag these for my review)

4. **Make surgical edits**: Use tracked changes to:
   - Fix outdated claims with minimal rewording
   - Add brief coverage of missing features in appropriate locations
   - Add comments (not tracked changes) for ambiguous items asking for my input

## Critical Constraints

- **Preserve my voice**: Don't rewrite sentences that are factually correct. Match my existing tone and technical depth when adding new material.
- **Minimal changes**: If a sentence is 90% correct, fix only the 10% that's wrong. Don't rephrase for style.
- **Use tracked changes**: I want to review every edit before accepting. Use "Claude" as the author.
- **Add comments for uncertainty**: If you're unsure whether the book or implementation represents my intent, add a Word comment asking me rather than making a change.
- **Work incrementally**: Complete one chapter/major section before moving to the next. Give me a summary of changes after each section.

## Document Location

[Path to your .docx file]

## Codebase Location

[Path to Coex compiler/runtime]

## Key Files to Reference

For your reference, here are the key components you'll want to verify against:

- **Grammar**: [path to .g4 files]
- **Semantic analysis**: [relevant compiler passes]
- **Type system**: [type checker location]
- **Runtime**: [GC, task system, etc.]
- **Tests**: [test directory—these show expected behavior]

## Output Format

After each section, provide:

```
## Section: [Name]

### Claims Verified (no changes needed)
- [list of claims that match implementation]

### Changes Made
- Line X: Changed "Y" to "Z" — [brief rationale]
- Added paragraph after line X covering [feature] — [rationale]

### Flagged for Review
- Line X: Book says "Y", implementation does "Z". Which is intended? [added as comment]

### Missing Coverage Noted
- [Feature] exists in implementation but isn't documented. Suggested location: [section]
```

## Start

Begin with the first major section. Read it, verify claims, make tracked-change edits, and report back before proceeding.
