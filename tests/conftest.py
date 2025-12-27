"""
Pytest configuration and fixtures for Coex compiler tests.

Provides reusable fixtures for:
- Compiling and running Coex programs
- Verifying expected output
- Checking compilation errors
"""

import pytest
import subprocess
import tempfile
import os
import sys
from pathlib import Path


class CompilerResult:
    """Result of compiling and optionally running a Coex program."""
    
    def __init__(self, compile_success: bool, compile_output: str, 
                 run_success: bool = None, run_output: str = None,
                 ir: str = None):
        self.compile_success = compile_success
        self.compile_output = compile_output
        self.run_success = run_success
        self.run_output = run_output
        self.ir = ir


@pytest.fixture
def compiler_root():
    """Path to compiler root directory."""
    return Path(__file__).parent.parent


@pytest.fixture
def compile_coex(compiler_root):
    """
    Fixture that returns a function to compile Coex source code.
    
    Usage:
        result = compile_coex(source_code)
        assert result.compile_success
        assert result.run_output == "42\n"
    """
    def _compile(source: str, run: bool = True, emit_ir: bool = False) -> CompilerResult:
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")
            
            with open(source_path, 'w') as f:
                f.write(source)
            
            coexc = os.path.join(compiler_root, "coexc.py")
            cmd = [sys.executable, coexc, source_path, "--no-commentary"]

            if emit_ir:
                cmd.append("--emit-ir")
            else:
                cmd.extend(["-o", exe_path])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=compiler_root
            )
            
            compile_success = result.returncode == 0
            compile_output = result.stdout + result.stderr
            
            if emit_ir:
                return CompilerResult(compile_success, compile_output, ir=result.stdout)
            
            if not compile_success or not run:
                return CompilerResult(compile_success, compile_output)
            
            run_result = subprocess.run(
                [exe_path],
                capture_output=True,
                text=True
            )
            
            return CompilerResult(
                compile_success=True,
                compile_output=compile_output,
                run_success=run_result.returncode == 0,
                run_output=run_result.stdout
            )
    
    return _compile


@pytest.fixture
def expect_output(compile_coex):
    """
    Fixture that compiles code and asserts expected output.

    Usage:
        expect_output(source_code, "expected output\n")
        expect_output(source_code, "substring", partial=True)  # Check for substring
    """
    def _expect(source: str, expected: str, partial: bool = False):
        result = compile_coex(source)
        assert result.compile_success, f"Compilation failed:\n{result.compile_output}"
        assert result.run_success, f"Execution failed:\n{result.run_output}"
        if partial:
            assert expected in result.run_output, \
                f"Output does not contain expected substring:\nExpected to find: {expected!r}\nIn output: {result.run_output!r}"
        else:
            assert result.run_output == expected, \
                f"Output mismatch:\nExpected: {expected!r}\nGot: {result.run_output!r}"

    return _expect


@pytest.fixture
def expect_compile_error(compile_coex):
    """
    Fixture that verifies compilation fails with expected error.
    
    Usage:
        expect_compile_error(bad_code, "syntax error")
    """
    def _expect(source: str, error_substring: str = None):
        result = compile_coex(source, run=False)
        assert not result.compile_success, \
            f"Expected compilation to fail but it succeeded.\nOutput: {result.compile_output}"
        if error_substring:
            assert error_substring.lower() in result.compile_output.lower(), \
                f"Expected error containing '{error_substring}' but got:\n{result.compile_output}"

    return _expect


class CompiledBinary:
    """Context manager for compiled binary that persists until exit."""

    def __init__(self, compiler_root):
        self.compiler_root = compiler_root
        self.tmpdir = None
        self.binary_path = None

    def compile(self, source: str) -> bool:
        """Compile source code and return True if successful."""
        import shutil
        self.tmpdir = tempfile.mkdtemp()
        source_path = os.path.join(self.tmpdir, "test.coex")
        self.binary_path = os.path.join(self.tmpdir, "test")

        with open(source_path, 'w') as f:
            f.write(source)

        coexc = os.path.join(self.compiler_root, "coexc.py")
        result = subprocess.run(
            [sys.executable, coexc, source_path, "--no-commentary", "-o", self.binary_path],
            capture_output=True,
            text=True,
            cwd=self.compiler_root
        )

        self.compile_output = result.stdout + result.stderr
        return result.returncode == 0

    def run(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Run the binary with optional arguments."""
        cmd = [self.binary_path] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, **kwargs)

    def cleanup(self):
        """Remove temporary directory."""
        if self.tmpdir:
            import shutil
            shutil.rmtree(self.tmpdir, ignore_errors=True)


@pytest.fixture
def compile_binary(compiler_root):
    """
    Fixture that compiles code and returns a binary that can be run with custom args.

    Usage:
        binary = compile_binary(source_code)
        assert binary.compile_success
        result = binary.run("arg1", "arg2")
        assert result.returncode == 0
    """
    binaries = []

    def _compile(source: str):
        binary = CompiledBinary(compiler_root)
        compile_success = binary.compile(source)
        binary.compile_success = compile_success
        binaries.append(binary)
        return binary

    yield _compile

    # Cleanup all compiled binaries
    for binary in binaries:
        binary.cleanup()
