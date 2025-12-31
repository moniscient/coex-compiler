"""
Tests for CXZ library loader.

Tests archive handling, manifest parsing, compilation, and caching.
"""

import os
import sys
import pytest
import zipfile
import tempfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cxz_loader import (
    CXZLoader, CXZError, ManifestError, CompilationError, DependencyError,
    FFICache, FFICompiler, LibraryManifest, FFIConfig, FFISymbol,
    LoadedLibrary, CompiledFFI
)


class TestFFICache:
    """Tests for FFI object caching"""

    def test_cache_key_generation(self, tmp_path):
        cache = FFICache(str(tmp_path))
        key = cache.get_cache_key("mylib", "1.0.0", "abc123", "x86_64-darwin")
        assert len(key) == 32
        assert key.isalnum()

    def test_cache_key_deterministic(self, tmp_path):
        cache = FFICache(str(tmp_path))
        key1 = cache.get_cache_key("mylib", "1.0.0", "abc123", "x86_64-darwin")
        key2 = cache.get_cache_key("mylib", "1.0.0", "abc123", "x86_64-darwin")
        assert key1 == key2

    def test_cache_key_varies_with_version(self, tmp_path):
        cache = FFICache(str(tmp_path))
        key1 = cache.get_cache_key("mylib", "1.0.0", "abc123", "x86_64-darwin")
        key2 = cache.get_cache_key("mylib", "2.0.0", "abc123", "x86_64-darwin")
        assert key1 != key2

    def test_cache_miss(self, tmp_path):
        cache = FFICache(str(tmp_path))
        result = cache.get_cached("nonexistent_key")
        assert result is None

    def test_cache_store_and_retrieve(self, tmp_path):
        cache = FFICache(str(tmp_path))

        # Create a fake object file
        obj_file = tmp_path / "test.o"
        obj_file.write_bytes(b"fake object data")

        # Store it
        cached_path = cache.store("test_key", str(obj_file))
        assert os.path.exists(cached_path)

        # Retrieve it
        result = cache.get_cached("test_key")
        assert result == cached_path
        assert Path(result).read_bytes() == b"fake object data"

    def test_cache_clear(self, tmp_path):
        cache = FFICache(str(tmp_path))

        # Store some items
        obj_file = tmp_path / "test.o"
        obj_file.write_bytes(b"data")
        cache.store("key1", str(obj_file))
        cache.store("key2", str(obj_file))

        # Clear
        cache.clear()

        # Verify cleared
        assert cache.get_cached("key1") is None
        assert cache.get_cached("key2") is None


class TestFFICompiler:
    """Tests for FFI C compilation"""

    def test_compiler_init(self):
        """Test compiler initialization with valid clang"""
        compiler = FFICompiler()
        assert compiler.clang_path == "clang"

    def test_get_target_triple(self):
        """Test getting target triple"""
        compiler = FFICompiler()
        triple = compiler.get_target_triple()
        assert triple  # Should not be empty
        assert "-" in triple  # Format like x86_64-apple-darwin

    def test_compile_simple_c(self, tmp_path):
        """Test compiling a simple C file"""
        compiler = FFICompiler()

        # Create a simple C file
        c_file = tmp_path / "test.c"
        c_file.write_text("""
int coex_test_add(int a, int b) {
    return a + b;
}
""")

        output = tmp_path / "test.o"
        result = compiler.compile([str(c_file)], [], str(output))
        assert os.path.exists(result)
        assert os.path.getsize(result) > 0

    def test_compile_with_includes(self, tmp_path):
        """Test compiling with include directories"""
        compiler = FFICompiler()

        # Create header and source
        inc_dir = tmp_path / "include"
        inc_dir.mkdir()
        (inc_dir / "myheader.h").write_text("int my_func(void);")

        c_file = tmp_path / "test.c"
        c_file.write_text("""
#include "myheader.h"
int my_func(void) { return 42; }
""")

        output = tmp_path / "test.o"
        result = compiler.compile([str(c_file)], [str(inc_dir)], str(output))
        assert os.path.exists(result)

    def test_compile_multiple_files(self, tmp_path):
        """Test compiling multiple C files"""
        compiler = FFICompiler()

        # Create two C files
        (tmp_path / "a.c").write_text("int func_a(void) { return 1; }")
        (tmp_path / "b.c").write_text("int func_b(void) { return 2; }")

        output = tmp_path / "combined.o"
        result = compiler.compile(
            [str(tmp_path / "a.c"), str(tmp_path / "b.c")],
            [],
            str(output)
        )
        assert os.path.exists(result)

    def test_compile_error(self, tmp_path):
        """Test compilation error handling"""
        compiler = FFICompiler()

        # Create invalid C file
        c_file = tmp_path / "bad.c"
        c_file.write_text("this is not valid C code!!!")

        output = tmp_path / "bad.o"
        with pytest.raises(CompilationError) as exc_info:
            compiler.compile([str(c_file)], [], str(output))
        assert "Compilation failed" in str(exc_info.value)

    def test_check_system_header_libc(self):
        """Test checking for stdlib.h (should always exist)"""
        compiler = FFICompiler()
        assert compiler.check_system_header("stdlib.h") is True

    def test_check_system_header_missing(self):
        """Test checking for nonexistent header"""
        compiler = FFICompiler()
        assert compiler.check_system_header("nonexistent_header_12345.h") is False


class TestCXZLoader:
    """Tests for CXZ library loading"""

    def create_minimal_cxz(self, tmp_path, name="testlib", version="1.0.0"):
        """Helper to create a minimal .cxz archive"""
        lib_dir = tmp_path / "build"
        lib_dir.mkdir()

        # Create manifest
        manifest = f"""
[library]
name = "{name}"
version = "{version}"
source = ["main.coex"]
"""
        (lib_dir / "manifest.toml").write_text(manifest)

        # Create src directory with Coex file
        src_dir = lib_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.coex").write_text("""
func hello() -> int
    return 42
~
""")

        # Create archive
        archive_path = tmp_path / f"{name}.cxz"
        with zipfile.ZipFile(archive_path, 'w') as zf:
            for file in lib_dir.rglob("*"):
                if file.is_file():
                    arcname = str(file.relative_to(lib_dir))
                    zf.write(file, arcname)

        return archive_path

    def create_ffi_cxz(self, tmp_path, name="ffilib"):
        """Helper to create a .cxz with FFI"""
        lib_dir = tmp_path / "build"
        lib_dir.mkdir()

        # Create manifest with FFI
        manifest = """
[library]
name = "ffilib"
version = "1.0.0"
source = ["main.coex"]

[ffi.myext]
source = ["wrapper.c"]
headers = ["."]
system_headers = []
system_libs = []

[[ffi.myext.symbols]]
name = "coex_test_add"
params = ["int", "int"]
returns = "int"
"""
        (lib_dir / "manifest.toml").write_text(manifest)

        # Create src directory
        src_dir = lib_dir / "src"
        src_dir.mkdir()
        (src_dir / "main.coex").write_text("""
extern coex_test_add(a: int, b: int) -> int
~
""")

        # Create FFI source
        ffi_dir = lib_dir / "ffi" / "src"
        ffi_dir.mkdir(parents=True)
        (ffi_dir / "wrapper.c").write_text("""
#include <stdint.h>
int64_t coex_test_add(int64_t a, int64_t b) {
    return a + b;
}
""")

        # Create archive
        archive_path = tmp_path / f"{name}.cxz"
        with zipfile.ZipFile(archive_path, 'w') as zf:
            for file in lib_dir.rglob("*"):
                if file.is_file():
                    arcname = str(file.relative_to(lib_dir))
                    zf.write(file, arcname)

        return archive_path

    def test_find_library_by_name(self, tmp_path):
        """Test finding library by name in search paths"""
        archive = self.create_minimal_cxz(tmp_path)

        loader = CXZLoader(search_paths=[str(tmp_path)])
        found = loader.find_library("testlib")
        assert found == str(archive)

    def test_find_library_by_path(self, tmp_path):
        """Test finding library by direct path"""
        archive = self.create_minimal_cxz(tmp_path)

        loader = CXZLoader()
        found = loader.find_library(str(archive))
        assert found == str(archive)

    def test_find_library_not_found(self, tmp_path):
        """Test library not found error"""
        loader = CXZLoader(search_paths=[str(tmp_path)])
        found = loader.find_library("nonexistent")
        assert found is None

    def test_load_minimal_library(self, tmp_path):
        """Test loading a minimal library"""
        archive = self.create_minimal_cxz(tmp_path)

        loader = CXZLoader(search_paths=[str(tmp_path)])
        lib = loader.load("testlib")

        assert lib.name == "testlib"
        assert lib.version == "1.0.0"
        assert "main.coex" in lib.coex_sources
        assert "func hello()" in lib.coex_sources["main.coex"]

    def test_load_library_with_ffi(self, tmp_path):
        """Test loading a library with FFI"""
        archive = self.create_ffi_cxz(tmp_path)

        loader = CXZLoader(
            search_paths=[str(tmp_path)],
            cache=FFICache(str(tmp_path / "cache"))
        )
        lib = loader.load("ffilib")

        assert lib.name == "ffilib"
        assert "myext" in lib.compiled_ffi
        assert os.path.exists(lib.compiled_ffi["myext"].object_path)

        # Check symbols
        symbols = lib.get_ffi_symbols()
        assert "coex_test_add" in symbols
        assert symbols["coex_test_add"].params == ["int", "int"]
        assert symbols["coex_test_add"].returns == "int"

    def test_load_caches_result(self, tmp_path):
        """Test that loading is cached"""
        archive = self.create_minimal_cxz(tmp_path)

        loader = CXZLoader(search_paths=[str(tmp_path)])
        lib1 = loader.load("testlib")
        lib2 = loader.load("testlib")

        assert lib1 is lib2  # Same object

    def test_load_not_found_error(self, tmp_path):
        """Test error when library not found"""
        loader = CXZLoader(search_paths=[str(tmp_path)])

        with pytest.raises(CXZError) as exc_info:
            loader.load("nonexistent")
        assert "not found" in str(exc_info.value).lower()
        assert "coex pkg install" in str(exc_info.value)

    def test_load_invalid_zip(self, tmp_path):
        """Test error on invalid ZIP file"""
        bad_file = tmp_path / "bad.cxz"
        bad_file.write_text("not a zip file")

        loader = CXZLoader()
        with pytest.raises(CXZError) as exc_info:
            loader.load(str(bad_file))
        assert "not a ZIP" in str(exc_info.value)

    def test_load_missing_manifest(self, tmp_path):
        """Test error when manifest.toml is missing"""
        # Create archive without manifest
        archive = tmp_path / "nomanifest.cxz"
        with zipfile.ZipFile(archive, 'w') as zf:
            zf.writestr("src/main.coex", "func main() -> int\n    return 0\n~\n")

        loader = CXZLoader()
        with pytest.raises(ManifestError) as exc_info:
            loader.load(str(archive))
        assert "manifest.toml" in str(exc_info.value)


class TestManifestParsing:
    """Tests for manifest.toml parsing"""

    def test_parse_minimal_manifest(self, tmp_path):
        """Test parsing minimal valid manifest"""
        manifest = """
[library]
name = "mylib"
version = "1.0.0"
"""
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "manifest.toml").write_text(manifest)

        with zipfile.ZipFile(tmp_path / "test.cxz", 'w') as zf:
            zf.write(lib_dir / "manifest.toml", "manifest.toml")

        loader = CXZLoader()
        lib = loader.load(str(tmp_path / "test.cxz"))
        assert lib.name == "mylib"
        assert lib.version == "1.0.0"

    def test_parse_full_manifest(self, tmp_path):
        """Test parsing manifest with all fields"""
        manifest = """
[library]
name = "fulltest"
version = "2.1.0"
description = "A test library"
authors = ["Test Author"]
license = "MIT"
source = ["main.coex", "util.coex"]

[ffi.wrapper]
source = ["wrapper.c"]
headers = ["include"]
system_headers = ["stdlib.h"]
system_libs = ["-lm"]

[[ffi.wrapper.symbols]]
name = "do_thing"
params = ["int", "string"]
returns = "int"

[[ffi.wrapper.symbols]]
name = "other_thing"
params = []
returns = "void"
"""
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "manifest.toml").write_text(manifest)
        (lib_dir / "src").mkdir()
        (lib_dir / "src" / "main.coex").write_text("")
        (lib_dir / "src" / "util.coex").write_text("")
        (lib_dir / "ffi" / "src").mkdir(parents=True)
        (lib_dir / "ffi" / "src" / "wrapper.c").write_text(
            "#include <stdint.h>\n"
            "int64_t do_thing(int64_t a, char* b) { return 0; }\n"
            "void other_thing(void) {}"
        )
        (lib_dir / "ffi" / "src" / "include").mkdir()

        with zipfile.ZipFile(tmp_path / "full.cxz", 'w') as zf:
            for file in lib_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, str(file.relative_to(lib_dir)))

        loader = CXZLoader(cache=FFICache(str(tmp_path / "cache")))
        lib = loader.load(str(tmp_path / "full.cxz"))

        assert lib.name == "fulltest"
        assert lib.version == "2.1.0"
        assert lib.manifest.description == "A test library"
        assert lib.manifest.license == "MIT"
        assert "wrapper" in lib.compiled_ffi

        symbols = lib.get_ffi_symbols()
        assert "do_thing" in symbols
        assert "other_thing" in symbols
        assert symbols["do_thing"].params == ["int", "string"]

    def test_manifest_missing_name(self, tmp_path):
        """Test error when name is missing"""
        manifest = """
[library]
version = "1.0.0"
"""
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "manifest.toml").write_text(manifest)

        with zipfile.ZipFile(tmp_path / "noname.cxz", 'w') as zf:
            zf.write(lib_dir / "manifest.toml", "manifest.toml")

        loader = CXZLoader()
        with pytest.raises(ManifestError) as exc_info:
            loader.load(str(tmp_path / "noname.cxz"))
        assert "name" in str(exc_info.value).lower()

    def test_manifest_missing_library_section(self, tmp_path):
        """Test error when [library] section is missing"""
        manifest = """
[ffi.something]
source = ["test.c"]
"""
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()
        (lib_dir / "manifest.toml").write_text(manifest)

        with zipfile.ZipFile(tmp_path / "nolib.cxz", 'w') as zf:
            zf.write(lib_dir / "manifest.toml", "manifest.toml")

        loader = CXZLoader()
        with pytest.raises(ManifestError) as exc_info:
            loader.load(str(tmp_path / "nolib.cxz"))
        assert "library" in str(exc_info.value).lower()


class TestLoadedLibrary:
    """Tests for LoadedLibrary functionality"""

    def test_get_link_args(self):
        """Test get_link_args returns correct arguments"""
        lib = LoadedLibrary(
            name="test",
            version="1.0",
            path="/path/to/lib.cxz",
            manifest=LibraryManifest(name="test", version="1.0"),
            coex_sources={},
            compiled_ffi={
                "ext1": CompiledFFI(
                    name="ext1",
                    object_path="/path/to/ext1.o",
                    symbols=[],
                    system_libs=["-lm"]
                ),
                "ext2": CompiledFFI(
                    name="ext2",
                    object_path="/path/to/ext2.o",
                    symbols=[],
                    system_libs=["-lpthread", "-ldl"]
                )
            }
        )

        args = lib.get_link_args()
        assert "/path/to/ext1.o" in args
        assert "/path/to/ext2.o" in args
        assert "-lm" in args
        assert "-lpthread" in args
        assert "-ldl" in args

    def test_get_ffi_symbols(self):
        """Test get_ffi_symbols aggregates all symbols"""
        lib = LoadedLibrary(
            name="test",
            version="1.0",
            path="/path",
            manifest=LibraryManifest(name="test", version="1.0"),
            coex_sources={},
            compiled_ffi={
                "ext1": CompiledFFI(
                    name="ext1",
                    object_path="/path/ext1.o",
                    symbols=[
                        FFISymbol("func_a", ["int"], "int"),
                        FFISymbol("func_b", [], "void")
                    ],
                    system_libs=[]
                ),
                "ext2": CompiledFFI(
                    name="ext2",
                    object_path="/path/ext2.o",
                    symbols=[
                        FFISymbol("func_c", ["string"], "int")
                    ],
                    system_libs=[]
                )
            }
        )

        symbols = lib.get_ffi_symbols()
        assert len(symbols) == 3
        assert "func_a" in symbols
        assert "func_b" in symbols
        assert "func_c" in symbols


class TestFFICaching:
    """Tests for FFI compilation caching"""

    def test_ffi_compilation_cached(self, tmp_path):
        """Test that FFI compilation results are cached"""
        # Create library with FFI
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()

        manifest = """
[library]
name = "cached"
version = "1.0.0"

[ffi.ext]
source = ["test.c"]

[[ffi.ext.symbols]]
name = "test_func"
params = []
returns = "int"
"""
        (lib_dir / "manifest.toml").write_text(manifest)
        (lib_dir / "ffi" / "src").mkdir(parents=True)
        (lib_dir / "ffi" / "src" / "test.c").write_text(
            "#include <stdint.h>\n"
            "int64_t test_func(void) { return 42; }"
        )

        with zipfile.ZipFile(tmp_path / "cached.cxz", 'w') as zf:
            for file in lib_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, str(file.relative_to(lib_dir)))

        cache = FFICache(str(tmp_path / "cache"))

        # First load - should compile
        loader1 = CXZLoader(cache=cache)
        lib1 = loader1.load(str(tmp_path / "cached.cxz"))
        first_obj = lib1.compiled_ffi["ext"].object_path

        # Second load with new loader - should use cache
        loader2 = CXZLoader(cache=cache)
        lib2 = loader2.load(str(tmp_path / "cached.cxz"))
        second_obj = lib2.compiled_ffi["ext"].object_path

        assert first_obj == second_obj  # Same cached file
        assert os.path.exists(first_obj)
