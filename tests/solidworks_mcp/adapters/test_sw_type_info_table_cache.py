"""The method-name table is cached as JSON so connect skips the gen_py import.

Importing the SW 2026 gen_py wrapper (6.3 MB of Python) took 1.3 s per server
start; the same table as JSON loads in about 10 ms. The cache is keyed by the
wrapper file's size and mtime, so a regenerated wrapper is never read from a
stale table.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters import sw_type_info

_NAME = "83A33D31-27C5-11CE-BFD4-00400513BB57x0x34x0"


@pytest.fixture
def gen_dir(tmp_path, monkeypatch) -> Path:
    """A fake gen_py folder holding a major-34 wrapper, and an empty cache."""
    gen = tmp_path / "gen_py"
    gen.mkdir()
    (gen / f"{_NAME}.py").write_text("# generated wrapper\n", encoding="utf-8")
    monkeypatch.setattr(sw_type_info, "PYWIN32_AVAILABLE", True)
    monkeypatch.setattr(
        sw_type_info, "win32com", SimpleNamespace(__gen_path__=str(gen)), raising=False
    )
    monkeypatch.setattr(
        sw_type_info,
        "gencache",
        SimpleNamespace(
            GetGeneratedFileName=lambda _iid, _lcid, major, _minor: (
                f"83A33D31-27C5-11CE-BFD4-00400513BB57x0x{major}x0"
            )
        ),
        raising=False,
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_TYPEINFO_CACHE", "1")
    monkeypatch.setenv("SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(sw_type_info, "_wrapper_module", None)
    monkeypatch.setattr(sw_type_info, "_interface_methods", {})
    return gen


def test_a_saved_table_loads_without_the_wrapper(gen_dir) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    sw_type_info._write_cached_table(wrapper, {"IModelDoc2": frozenset({"GetTitle"})})

    assert sw_type_info._load_cached_wrapper() is True
    assert sw_type_info._interface_methods == {"IModelDoc2": frozenset({"GetTitle"})}
    assert sw_type_info.type_library_name() == f"win32com.gen_py.{_NAME}"


def test_load_wrapper_reads_the_cache_first(gen_dir, monkeypatch) -> None:
    sw_type_info._write_cached_table(
        gen_dir / f"{_NAME}.py", {"ISldWorks": frozenset({"RevisionNumber"})}
    )
    imported: list[int] = []
    gencache = sw_type_info.gencache
    gencache.GetModuleForTypelib = lambda *_a: imported.append(1)

    sw_type_info._load_wrapper()

    assert imported == []
    assert sw_type_info.interface_method_names("ISldWorks") == {"RevisionNumber"}


def test_no_cache_means_no_load(gen_dir) -> None:
    assert sw_type_info._load_cached_wrapper() is False


def test_a_changed_wrapper_misses_the_old_cache(gen_dir) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    sw_type_info._write_cached_table(wrapper, {"IModelDoc2": frozenset({"GetTitle"})})
    wrapper.write_text("# regenerated, and longer\n", encoding="utf-8")

    assert sw_type_info._load_cached_wrapper() is False


def test_writing_drops_older_caches_of_the_same_wrapper(gen_dir, tmp_path) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    stale = tmp_path / "cache" / f"{_NAME}-1-1.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    other = tmp_path / "cache" / "SomethingElse-1-1.json"
    other.write_text("{}", encoding="utf-8")

    sw_type_info._write_cached_table(
        wrapper, {"IFeature": frozenset({"GetNextFeature"})}
    )

    files = sorted(p.name for p in (tmp_path / "cache").iterdir())
    assert stale.name not in files
    assert other.name in files
    written = sw_type_info._cache_file_for(wrapper)
    assert json.loads(written.read_text(encoding="utf-8")) == {
        "IFeature": ["GetNextFeature"]
    }


@pytest.mark.parametrize("content", ["not json", "[]", "{}"])
def test_an_unreadable_cache_is_ignored(gen_dir, content) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    target = sw_type_info._cache_file_for(wrapper)
    target.parent.mkdir(parents=True)
    target.write_text(content, encoding="utf-8")

    assert sw_type_info._read_cached_table(wrapper) is None


def test_a_cache_write_failure_is_not_fatal(gen_dir, tmp_path, monkeypatch) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    monkeypatch.setenv("SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR", str(blocker / "cache"))

    sw_type_info._write_cached_table(gen_dir / f"{_NAME}.py", {"I": frozenset({"M"})})

    assert not (blocker / "cache").exists()


def test_the_switch_turns_the_cache_off(gen_dir, monkeypatch) -> None:
    sw_type_info._write_cached_table(
        gen_dir / f"{_NAME}.py", {"IModelDoc2": frozenset({"GetTitle"})}
    )
    monkeypatch.setenv("SOLIDWORKS_MCP_TYPEINFO_CACHE", "off")

    assert sw_type_info._load_cached_wrapper() is False


def test_a_scanned_wrapper_is_saved_for_next_time(gen_dir, monkeypatch) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    monkeypatch.setattr(
        sw_type_info, "_wrapper_module", SimpleNamespace(__file__=str(wrapper))
    )
    monkeypatch.setattr(
        sw_type_info, "_interface_methods", {"ISketch": frozenset({"GetSketchPoints2"})}
    )

    sw_type_info._cache_loaded_wrapper()

    assert sw_type_info._read_cached_table(wrapper) == {
        "ISketch": frozenset({"GetSketchPoints2"})
    }


def test_a_wrapper_without_a_single_file_is_not_cached(gen_dir, monkeypatch) -> None:
    package = gen_dir / _NAME
    package.mkdir()
    init = package / "__init__.py"
    init.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        sw_type_info,
        "_wrapper_module",
        SimpleNamespace(__file__=str(gen_dir / "missing.py")),
    )
    monkeypatch.setattr(sw_type_info, "_interface_methods", {"I": frozenset({"M"})})

    sw_type_info._cache_loaded_wrapper()

    cache = Path(os.environ["SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR"])
    assert not cache.exists() or not any(cache.iterdir())


def test_saving_is_skipped_when_off_or_empty(gen_dir, monkeypatch) -> None:
    wrapper = gen_dir / f"{_NAME}.py"
    monkeypatch.setattr(
        sw_type_info, "_wrapper_module", SimpleNamespace(__file__=str(wrapper))
    )
    monkeypatch.setattr(sw_type_info, "_interface_methods", {})
    sw_type_info._cache_loaded_wrapper()
    assert sw_type_info._read_cached_table(wrapper) is None

    monkeypatch.setattr(sw_type_info, "_interface_methods", {"I": frozenset({"M"})})
    monkeypatch.setenv("SOLIDWORKS_MCP_TYPEINFO_CACHE", "0")
    sw_type_info._cache_loaded_wrapper()
    assert sw_type_info._read_cached_table(wrapper) is None


def test_no_generated_wrapper_means_no_cache(gen_dir) -> None:
    (gen_dir / f"{_NAME}.py").unlink()

    assert sw_type_info._generated_wrapper_file(34) is None
    assert sw_type_info._load_cached_wrapper() is False


def test_a_broken_gencache_means_no_wrapper_file(monkeypatch) -> None:
    def _broken(*_args: object) -> str:
        raise RuntimeError("no gencache")

    monkeypatch.setattr(
        sw_type_info,
        "gencache",
        SimpleNamespace(GetGeneratedFileName=_broken),
        raising=False,
    )

    assert sw_type_info._generated_wrapper_file(34) is None


def test_the_default_cache_dir_is_in_temp(monkeypatch) -> None:
    monkeypatch.delenv("SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR", raising=False)

    assert sw_type_info._cache_dir().parts[-2:] == ("solidworks_mcp", "typeinfo")
