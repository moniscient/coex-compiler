"""
Coex CXZ Library Loader

Handles loading .cxz library archives, parsing TOML manifests,
compiling FFI C source code, and caching compiled objects.

The .cxz format is a ZIP archive containing:
  - manifest.toml: Library metadata and FFI declarations
  - src/: Coex source files
  - ffi/src/: C source files for FFI

C sources are compiled at build time using clang and cached
in ~/.coex/cache/ for subsequent builds.
"""

import os
import sys
import zipfile
import hashlib
import subprocess
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

# TOML parsing - use stdlib tomllib in 3.11+, fallback to tomli
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


@dataclass
class FFISymbol:
    """A single FFI function symbol declaration"""
    name: str
    params: List[str]  # Coex type names
    returns: str       # Coex return type


@dataclass
class FFIConfig:
    """Configuration for a single FFI library binding"""
    name: str
    source: List[str]          # Glob patterns for C source files
    headers: List[str]         # Include directories
    system_headers: List[str]  # System headers to check for
    system_libs: List[str]     # System libraries to link (-l flags)
    symbols: List[FFISymbol]   # Declared symbols


@dataclass
class LibraryManifest:
    """Parsed manifest.toml for a .cxz library"""
    name: str
    version: str
    description: str = ""
    authors: List[str] = field(default_factory=list)
    license: str = ""
    source_files: List[str] = field(default_factory=list)  # Coex source files
    ffi_configs: Dict[str, FFIConfig] = field(default_factory=dict)


@dataclass
class CompiledFFI:
    """Information about a compiled FFI library"""
    name: str
    object_path: str        # Path to compiled .o file
    symbols: List[FFISymbol]
    system_libs: List[str]  # Libraries to link


class CXZError(Exception):
    """Base exception for CXZ loading errors"""
    pass


class ManifestError(CXZError):
    """Error parsing or validating manifest.toml"""
    pass


class CompilationError(CXZError):
    """Error compiling FFI C source"""
    pass


class DependencyError(CXZError):
    """Missing system dependency"""
    pass


class FFICache:
    """
    Cache for compiled FFI object files.

    Cache key is computed from:
    - Library name and version
    - Hash of all C source files
    - Compiler version and flags
    - Target architecture

    Cache location: ~/.coex/cache/ffi/<key>.o
    """

    def __init__(self, cache_dir: Optional[str] = None):
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = Path.home() / ".coex" / "cache" / "ffi"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_key(self, library_name: str, version: str,
                      source_hash: str, target: str) -> str:
        """Generate unique cache key for a library build"""
        key_parts = [library_name, version, source_hash, target]
        key_string = ":".join(key_parts)
        return hashlib.sha256(key_string.encode()).hexdigest()[:32]

    def get_cached(self, cache_key: str) -> Optional[str]:
        """Get path to cached object file, or None if not cached"""
        cache_path = self.cache_dir / f"{cache_key}.o"
        if cache_path.exists():
            return str(cache_path)
        return None

    def store(self, cache_key: str, object_path: str) -> str:
        """Store compiled object in cache, return cache path"""
        cache_path = self.cache_dir / f"{cache_key}.o"
        shutil.copy2(object_path, cache_path)
        return str(cache_path)

    def clear(self):
        """Clear entire cache"""
        for item in self.cache_dir.iterdir():
            if item.is_file():
                item.unlink()


class FFICompiler:
    """
    Compiles FFI C source code using clang.

    Handles:
    - Source file compilation
    - Include path setup
    - System dependency checking
    - Object file generation
    """

    def __init__(self, clang_path: str = "clang"):
        self.clang_path = clang_path
        self._check_clang()

    def _check_clang(self):
        """Verify clang is available"""
        try:
            result = subprocess.run(
                [self.clang_path, "--version"],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise CompilationError(f"clang not available: {result.stderr}")
        except FileNotFoundError:
            raise CompilationError(
                f"clang not found at '{self.clang_path}'. "
                "Ensure clang is installed and in PATH."
            )

    def get_target_triple(self) -> str:
        """Get the default target triple from clang"""
        result = subprocess.run(
            [self.clang_path, "-dumpmachine"],
            capture_output=True, text=True
        )
        return result.stdout.strip()

    def check_system_header(self, header: str) -> bool:
        """Check if a system header is available"""
        test_code = f'#include <{header}>\nint main() {{ return 0; }}'
        with tempfile.NamedTemporaryFile(suffix='.c', delete=False) as f:
            f.write(test_code.encode())
            f.flush()
            try:
                result = subprocess.run(
                    [self.clang_path, '-c', '-o', '/dev/null', f.name],
                    capture_output=True, text=True
                )
                return result.returncode == 0
            finally:
                os.unlink(f.name)

    def check_pkg_config(self, package: str) -> Optional[Tuple[str, str]]:
        """
        Check pkg-config for a package.
        Returns (cflags, ldflags) or None if not found.
        """
        try:
            cflags_result = subprocess.run(
                ["pkg-config", "--cflags", package],
                capture_output=True, text=True
            )
            ldflags_result = subprocess.run(
                ["pkg-config", "--libs", package],
                capture_output=True, text=True
            )
            if cflags_result.returncode == 0 and ldflags_result.returncode == 0:
                return (cflags_result.stdout.strip(), ldflags_result.stdout.strip())
        except FileNotFoundError:
            pass  # pkg-config not installed
        return None

    def compile(self, source_files: List[str], include_dirs: List[str],
                output_path: str, extra_flags: List[str] = None) -> str:
        """
        Compile C source files into a single object file.

        Args:
            source_files: List of .c file paths
            include_dirs: List of include directories (-I)
            output_path: Path for output .o file
            extra_flags: Additional clang flags

        Returns:
            Path to compiled object file

        Raises:
            CompilationError: If compilation fails
        """
        if not source_files:
            raise CompilationError("No source files provided")

        cmd = [self.clang_path, "-c", "-fPIC", "-O2"]

        # Add include directories
        for inc in include_dirs:
            cmd.extend(["-I", inc])

        # Add extra flags
        if extra_flags:
            cmd.extend(extra_flags)

        # For multiple source files, compile each and link
        if len(source_files) == 1:
            cmd.extend(["-o", output_path, source_files[0]])
        else:
            # Compile each file to temporary .o, then link
            temp_objects = []
            try:
                for src in source_files:
                    temp_o = tempfile.mktemp(suffix='.o')
                    temp_objects.append(temp_o)
                    compile_cmd = cmd + ["-o", temp_o, src]
                    result = subprocess.run(
                        compile_cmd, capture_output=True, text=True
                    )
                    if result.returncode != 0:
                        raise CompilationError(
                            f"Compilation failed for {src}:\n"
                            f"Command: {' '.join(compile_cmd)}\n"
                            f"Error: {result.stderr}"
                        )

                # Link all objects into one
                link_cmd = ["ld", "-r", "-o", output_path] + temp_objects
                result = subprocess.run(link_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise CompilationError(
                        f"Linking failed:\n"
                        f"Command: {' '.join(link_cmd)}\n"
                        f"Error: {result.stderr}"
                    )
            finally:
                for temp_o in temp_objects:
                    if os.path.exists(temp_o):
                        os.unlink(temp_o)

            return output_path

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise CompilationError(
                f"Compilation failed:\n"
                f"Command: {' '.join(cmd)}\n"
                f"Error: {result.stderr}"
            )

        return output_path


class CXZLoader:
    """
    Loads .cxz library archives.

    Handles:
    - Archive extraction and validation
    - Manifest parsing
    - FFI compilation with caching
    - Source file extraction
    """

    # Search paths for .cxz libraries
    DEFAULT_SEARCH_PATHS = [
        ".",
        "./lib",
        "~/.coex/lib",
        "/usr/local/lib/coex",
    ]

    def __init__(self, search_paths: List[str] = None,
                 cache: FFICache = None,
                 compiler: FFICompiler = None):
        self.search_paths = [
            os.path.expanduser(p)
            for p in (search_paths or self.DEFAULT_SEARCH_PATHS)
        ]
        self.cache = cache or FFICache()
        self.compiler = compiler or FFICompiler()
        self._loaded_libraries: Dict[str, 'LoadedLibrary'] = {}

    def find_library(self, name: str) -> Optional[str]:
        """
        Find a .cxz library by name.

        Searches in order:
        1. Exact path if name contains /
        2. Search paths: <name>, <name>.cxz, <name>/<name>.cxz

        Returns path or None if not found.
        """
        # Direct path (contains path separator)
        if '/' in name:
            if os.path.exists(name):
                return name
            return None

        # Strip .cxz suffix for search if present
        base_name = name[:-4] if name.endswith('.cxz') else name

        # Search paths
        for search_dir in self.search_paths:
            # Try: name.cxz, name/name.cxz
            for pattern in [f"{base_name}.cxz", f"{base_name}/{base_name}.cxz"]:
                path = os.path.join(search_dir, pattern)
                if os.path.exists(path):
                    return path

        return None

    def load(self, name_or_path: str) -> 'LoadedLibrary':
        """
        Load a .cxz library.

        Args:
            name_or_path: Library name or path to .cxz file

        Returns:
            LoadedLibrary with manifest, source files, and compiled FFI

        Raises:
            CXZError: If library not found or invalid
        """
        # Check cache
        if name_or_path in self._loaded_libraries:
            return self._loaded_libraries[name_or_path]

        # Find library
        lib_path = self.find_library(name_or_path)
        if not lib_path:
            base_name = name_or_path[:-4] if name_or_path.endswith('.cxz') else name_or_path
            searched = "\n  - ".join(
                os.path.join(d, f"{base_name}.cxz")
                for d in self.search_paths
            )
            raise CXZError(
                f"Library '{base_name}' not found\n\n"
                f"Searched in:\n  - {searched}\n\n"
                f"To install: coex pkg install {base_name}"
            )

        # Extract and load
        loaded = self._load_archive(lib_path)
        self._loaded_libraries[name_or_path] = loaded
        return loaded

    def _load_archive(self, archive_path: str) -> 'LoadedLibrary':
        """Load and process a .cxz archive"""
        if not zipfile.is_zipfile(archive_path):
            raise CXZError(f"Invalid .cxz file: {archive_path} is not a ZIP archive")

        with tempfile.TemporaryDirectory() as extract_dir:
            # Extract archive
            with zipfile.ZipFile(archive_path, 'r') as zf:
                zf.extractall(extract_dir)

            # Parse manifest
            manifest_path = os.path.join(extract_dir, "manifest.toml")
            if not os.path.exists(manifest_path):
                raise ManifestError(
                    f"No manifest.toml in {archive_path}\n"
                    "A valid .cxz library must contain a manifest.toml file."
                )

            manifest = self._parse_manifest(manifest_path)

            # Read Coex source files
            coex_sources: Dict[str, str] = {}
            src_dir = os.path.join(extract_dir, "src")
            if os.path.isdir(src_dir):
                for filename in manifest.source_files:
                    src_path = os.path.join(src_dir, filename)
                    if os.path.exists(src_path):
                        with open(src_path, 'r') as f:
                            coex_sources[filename] = f.read()

            # Compile FFI libraries
            compiled_ffi: Dict[str, CompiledFFI] = {}
            for ffi_name, ffi_config in manifest.ffi_configs.items():
                compiled = self._compile_ffi(
                    extract_dir, ffi_config, manifest.name, manifest.version
                )
                compiled_ffi[ffi_name] = compiled

            return LoadedLibrary(
                name=manifest.name,
                version=manifest.version,
                path=archive_path,
                manifest=manifest,
                coex_sources=coex_sources,
                compiled_ffi=compiled_ffi
            )

    def _parse_manifest(self, manifest_path: str) -> LibraryManifest:
        """Parse manifest.toml into LibraryManifest"""
        if tomllib is None:
            raise ManifestError(
                "TOML parsing not available.\n"
                "Install with: pip install tomli"
            )

        with open(manifest_path, 'rb') as f:
            try:
                data = tomllib.load(f)
            except Exception as e:
                raise ManifestError(f"Failed to parse manifest.toml: {e}")

        # Validate required fields
        if 'library' not in data:
            raise ManifestError("manifest.toml missing [library] section")

        lib = data['library']
        if 'name' not in lib:
            raise ManifestError("manifest.toml missing library.name")
        if 'version' not in lib:
            raise ManifestError("manifest.toml missing library.version")

        # Build FFI configs
        ffi_configs: Dict[str, FFIConfig] = {}
        if 'ffi' in data:
            for ffi_name, ffi_data in data['ffi'].items():
                symbols = []
                if 'symbols' in ffi_data:
                    for sym in ffi_data['symbols']:
                        symbols.append(FFISymbol(
                            name=sym.get('name', ''),
                            params=sym.get('params', []),
                            returns=sym.get('returns', 'void')
                        ))

                ffi_configs[ffi_name] = FFIConfig(
                    name=ffi_name,
                    source=ffi_data.get('source', []),
                    headers=ffi_data.get('headers', []),
                    system_headers=ffi_data.get('system_headers', []),
                    system_libs=ffi_data.get('system_libs', []),
                    symbols=symbols
                )

        return LibraryManifest(
            name=lib['name'],
            version=lib['version'],
            description=lib.get('description', ''),
            authors=lib.get('authors', []),
            license=lib.get('license', ''),
            source_files=lib.get('source', []),
            ffi_configs=ffi_configs
        )

    def _compile_ffi(self, extract_dir: str, config: FFIConfig,
                     lib_name: str, version: str) -> CompiledFFI:
        """Compile FFI C sources with caching"""
        # Resolve source file paths (handle glob patterns)
        source_files = self._resolve_sources(
            os.path.join(extract_dir, "ffi", "src"),
            config.source
        )

        if not source_files:
            raise CompilationError(
                f"No C source files found for FFI '{config.name}'\n"
                f"Patterns: {config.source}"
            )

        # Check system dependencies
        for header in config.system_headers:
            if not self.compiler.check_system_header(header):
                raise DependencyError(
                    f"Missing system dependency for library '{lib_name}'\n\n"
                    f"Required header not found: {header}\n\n"
                    f"Install the development package:\n"
                    f"  Ubuntu/Debian: sudo apt install lib{header.split('/')[0]}-dev\n"
                    f"  macOS:         brew install {header.split('/')[0]}\n"
                    f"  Fedora:        sudo dnf install {header.split('/')[0]}-devel"
                )

        # Compute source hash for cache key
        source_hash = self._hash_sources(source_files)
        target = self.compiler.get_target_triple()
        cache_key = self.cache.get_cache_key(
            f"{lib_name}.{config.name}", version, source_hash, target
        )

        # Check cache
        cached = self.cache.get_cached(cache_key)
        if cached:
            return CompiledFFI(
                name=config.name,
                object_path=cached,
                symbols=config.symbols,
                system_libs=config.system_libs
            )

        # Compile
        include_dirs = [
            os.path.join(extract_dir, "ffi", "src", h)
            for h in config.headers
        ]
        include_dirs.append(os.path.join(extract_dir, "ffi", "src"))

        with tempfile.NamedTemporaryFile(suffix='.o', delete=False) as f:
            output_path = f.name

        try:
            self.compiler.compile(source_files, include_dirs, output_path)
            cached_path = self.cache.store(cache_key, output_path)
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

        return CompiledFFI(
            name=config.name,
            object_path=cached_path,
            symbols=config.symbols,
            system_libs=config.system_libs
        )

    def _resolve_sources(self, base_dir: str, patterns: List[str]) -> List[str]:
        """Resolve source file patterns to actual file paths"""
        import glob
        resolved = []
        for pattern in patterns:
            if '*' in pattern:
                matches = glob.glob(os.path.join(base_dir, pattern))
                resolved.extend(matches)
            else:
                path = os.path.join(base_dir, pattern)
                if os.path.exists(path):
                    resolved.append(path)
        return resolved

    def _hash_sources(self, source_files: List[str]) -> str:
        """Compute hash of all source file contents"""
        hasher = hashlib.sha256()
        for path in sorted(source_files):
            with open(path, 'rb') as f:
                hasher.update(f.read())
        return hasher.hexdigest()[:16]


@dataclass
class LoadedLibrary:
    """A fully loaded .cxz library ready for use"""
    name: str
    version: str
    path: str
    manifest: LibraryManifest
    coex_sources: Dict[str, str]  # filename -> content
    compiled_ffi: Dict[str, CompiledFFI]  # ffi_name -> compiled info

    def get_link_args(self) -> List[str]:
        """Get arguments for linker (object files and system libs)"""
        args = []
        for ffi in self.compiled_ffi.values():
            args.append(ffi.object_path)
            args.extend(ffi.system_libs)
        return args

    def get_ffi_symbols(self) -> Dict[str, FFISymbol]:
        """Get all FFI symbols from all FFI configs"""
        symbols = {}
        for ffi in self.compiled_ffi.values():
            for sym in ffi.symbols:
                symbols[sym.name] = sym
        return symbols
