"""
Stress tests for Map and Set at scale (10 million units).
These tests verify that HAMT-based data structures can handle
large numbers of elements efficiently.
"""
import pytest
import subprocess
import tempfile
import os
import sys
import time
from pathlib import Path

# Skip 10M tests on CI (too resource-intensive)
skip_on_ci = pytest.mark.skipif(
    os.environ.get('CI') == 'true',
    reason="10M element tests too slow for CI"
)


class TestStressMap:
    """Stress tests for Map at scale."""

    def test_map_100k_build_and_lookup(self, expect_output):
        """Build a map with 100k entries and verify lookups."""
        expect_output('''
func main() -> int
    m: Map<int, int> = {}

    for i in 0..100000
        m = m.set(i, i * 2)
    ~

    print(m.len())
    print(m.get(0))
    print(m.get(50000))
    print(m.get(99999))

    return 0
~
''', "100000\n0\n100000\n199998\n")

    @skip_on_ci
    def test_map_10m_build_and_lookup(self, compiler_root):
        """Build a map with 10 million entries and verify lookups."""
        source = '''
func main() -> int
    m: Map<int, int> = {}

    for i in 0..10000000
        m = m.set(i, i * 2)
    ~

    print(m.len())
    print(m.get(0))
    print(m.get(5000000))
    print(m.get(9999999))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=300
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "10000000", f"Expected 10000000, got {lines[0]}"
            assert lines[1] == "0", f"Expected 0, got {lines[1]}"
            assert lines[2] == "10000000", f"Expected 10000000, got {lines[2]}"
            assert lines[3] == "19999998", f"Expected 19999998, got {lines[3]}"

            assert elapsed < 60, f"Map build took too long: {elapsed:.1f}s"

    def test_map_1m_independent_modifications(self, compiler_root):
        """Test value semantics with 1M elements - modifications are independent."""
        source = '''
func main() -> int
    m: Map<int, int> = {}

    for i in 0..1000000
        m = m.set(i, i)
    ~

    m1 = m.set(500000, 999999)
    m2 = m.set(500000, 111111)

    print(m.get(500000))
    print(m1.get(500000))
    print(m2.get(500000))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=120
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "500000", f"Original should be unchanged"
            assert lines[1] == "999999", f"m1 modification"
            assert lines[2] == "111111", f"m2 modification"

            assert elapsed < 30, f"Independent mods took too long: {elapsed:.1f}s"


class TestStressSet:
    """Stress tests for Set at scale."""

    def test_set_100k_build_and_check(self, expect_output):
        """Build a set with 100k entries and verify membership."""
        expect_output('''
func main() -> int
    s: Set<int> = {0}

    for i in 1..100000
        s = s.add(i)
    ~

    if s.has(0)
        print("yes")
    ~
    if s.has(50000)
        print("yes")
    ~
    if s.has(99999)
        print("yes")
    ~
    if s.has(100000)
        print("yes")
    else
        print("no")
    ~
    print(s.len())

    return 0
~
''', "yes\nyes\nyes\nno\n100000\n")

    @skip_on_ci
    def test_set_10m_build_and_check(self, compiler_root):
        """Build a set with 10 million entries and verify membership."""
        source = '''
func main() -> int
    s: Set<int> = {0}

    for i in 1..10000000
        s = s.add(i)
    ~

    print(s.len())

    if s.has(0)
        print("has 0")
    ~
    if s.has(5000000)
        print("has 5000000")
    ~
    if s.has(9999999)
        print("has 9999999")
    ~
    if s.has(10000000)
        print("has 10000000")
    else
        print("no 10000000")
    ~

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=300
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "10000000", f"Expected 10000000, got {lines[0]}"
            assert lines[1] == "has 0"
            assert lines[2] == "has 5000000"
            assert lines[3] == "has 9999999"
            assert lines[4] == "no 10000000"

            assert elapsed < 60, f"Set build took too long: {elapsed:.1f}s"

    def test_set_1m_independent_modifications(self, compiler_root):
        """Test value semantics with 1M elements - modifications are independent."""
        source = '''
func main() -> int
    s: Set<int> = {0}

    for i in 1..1000000
        s = s.add(i)
    ~

    s1 = s.add(9999999)
    s2 = s.remove(500000)

    print(s.has(9999999))
    print(s.has(500000))
    print(s1.has(9999999))
    print(s2.has(500000))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=120
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "false", "Original shouldn't have 9999999"
            assert lines[1] == "true", "Original should have 500000"
            assert lines[2] == "true", "s1 should have 9999999"
            assert lines[3] == "false", "s2 shouldn't have 500000"

            assert elapsed < 30, f"Independent mods took too long: {elapsed:.1f}s"


class TestStressRemove:
    """Stress tests for remove operations at scale."""

    def test_map_remove_half(self, compiler_root):
        """Build 1 million entries then remove half."""
        source = '''
func main() -> int
    m: Map<int, int> = {}

    for i in 0..1000000
        m = m.set(i, i * 2)
    ~

    for i in 0..500000
        m = m.remove(i * 2)
    ~

    print(m.len())
    print(m.get(1))
    print(m.get(999999))
    print(m.has(0))
    print(m.has(500000))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=180
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "500000", f"Expected 500000, got {lines[0]}"
            assert lines[1] == "2", f"Expected 2, got {lines[1]}"
            assert lines[2] == "1999998", f"Expected 1999998, got {lines[2]}"
            assert lines[3] == "false", "Key 0 should be removed"
            assert lines[4] == "false", "Key 500000 should be removed"

            assert elapsed < 90, f"Remove took too long: {elapsed:.1f}s"

    def test_set_remove_half(self, compiler_root):
        """Build 1 million entries then remove half."""
        source = '''
func main() -> int
    s: Set<int> = {0}

    for i in 1..1000000
        s = s.add(i)
    ~

    for i in 0..500000
        s = s.remove(i * 2)
    ~

    print(s.len())
    print(s.has(1))
    print(s.has(999999))
    print(s.has(0))
    print(s.has(500000))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=180
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "500000", f"Expected 500000, got {lines[0]}"
            assert lines[1] == "true", "1 should be present"
            assert lines[2] == "true", "999999 should be present"
            assert lines[3] == "false", "0 should be removed"
            assert lines[4] == "false", "500000 should be removed"

            assert elapsed < 90, f"Remove took too long: {elapsed:.1f}s"


class TestStressMemory:
    """Memory stress tests - verify no memory explosion."""

    def test_map_many_independent_versions(self, compiler_root):
        """Create many independent versions of a map - should share structure."""
        source = '''
func main() -> int
    base: Map<int, int> = {}

    for i in 0..100000
        base = base.set(i, i)
    ~

    versions: [Map<int, int>] = []
    for i in 0..1000
        versions = versions.append(base.set(i, i * 1000))
    ~

    print(base.get(500))
    print(versions.get(0).get(0))
    print(versions.get(500).get(500))
    print(versions.get(999).get(999))

    return 0
~
'''
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = os.path.join(tmpdir, "test.coex")
            exe_path = os.path.join(tmpdir, "test")

            with open(source_path, 'w') as f:
                f.write(source)

            coexc = os.path.join(compiler_root, "coexc.py")
            result = subprocess.run(
                [sys.executable, coexc, source_path, "-o", exe_path],
                capture_output=True, text=True, cwd=compiler_root
            )
            assert result.returncode == 0, f"Compile failed: {result.stderr}"

            start = time.time()
            run_result = subprocess.run(
                [exe_path], capture_output=True, text=True, timeout=120
            )
            elapsed = time.time() - start

            assert run_result.returncode == 0, f"Run failed: {run_result.stderr}"
            lines = run_result.stdout.strip().split('\n')
            assert lines[0] == "500", "base[500] should be 500"
            assert lines[1] == "0", "versions[0][0] should be 0"
            assert lines[2] == "500000", "versions[500][500] should be 500000"
            assert lines[3] == "999000", "versions[999][999] should be 999000"

            assert elapsed < 60, f"Many versions took too long: {elapsed:.1f}s"
