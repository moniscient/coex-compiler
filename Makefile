# Coex Compiler Makefile
# Common operations for development

.PHONY: test test-verbose grammar clean examples help

# Default: run tests
test:
	python -m pytest tests/ -v --tb=short

# Verbose test output
test-verbose:
	python -m pytest tests/ -v --tb=long

# Run a single test file
test-%:
	python -m pytest tests/test_$*.py -v

# Run tests matching a keyword
test-k:
	python -m pytest tests/ -v -k "$(K)"

# Regenerate parser from grammar
grammar:
	antlr4 -Dlanguage=Python3 -visitor Coex.g4
	@echo "Parser regenerated from Coex.g4"

# Compile and run all examples
examples:
	@for f in examples/*.coex; do \
		echo "Compiling $$f..."; \
		python coexc.py "$$f" -o "$${f%.coex}"; \
		if [ -f "$${f%.coex}.expected" ]; then \
			echo "Running and checking output..."; \
			"$${f%.coex}" > /tmp/actual.txt; \
			if diff -q "$${f%.coex}.expected" /tmp/actual.txt > /dev/null; then \
				echo "✓ $$f passed"; \
			else \
				echo "✗ $$f failed:"; \
				diff -u "$${f%.coex}.expected" /tmp/actual.txt; \
			fi; \
		else \
			echo "Running (no expected output file)..."; \
			"$${f%.coex}"; \
		fi; \
		echo ""; \
	done

# Clean up generated files
clean:
	rm -f examples/*.o
	rm -f examples/hello examples/factorial
	rm -rf __pycache__ tests/__pycache__
	rm -rf .pytest_cache

# Show available commands
help:
	@echo "Coex Compiler - Available Commands"
	@echo ""
	@echo "  make test          Run all tests"
	@echo "  make test-verbose  Run tests with full output"
	@echo "  make test-basic    Run just test_basic.py"
	@echo "  make test-types    Run just test_types.py"
	@echo "  make grammar       Regenerate parser from Coex.g4"
	@echo "  make examples      Compile and run all examples"
	@echo "  make clean         Remove generated files"
	@echo ""
	@echo "Git workflow:"
	@echo "  git status         See what's changed"
	@echo "  git add .          Stage all changes"
	@echo "  git commit -m 'msg'  Commit changes"
	@echo "  git push           Push to GitHub"
