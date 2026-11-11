"""The docs index lives in the server's cache folder and is parsed once.

The old relative index folders resolved against the process's working
directory, which an MCP client sets to wherever its session started, so each
new folder rebuilt the index. And each lookup re-parsed the 2.8 MB index.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

from solidworks_mcp.tools import docs_discovery
from solidworks_mcp.tools.docs_discovery import _config_index_dir as real_index_dir


def test_the_index_folder_is_under_the_cache_folder(tmp_path: Path) -> None:
    config = SimpleNamespace(cache_dir=tmp_path)

    assert real_index_dir(config) == tmp_path / "docs-index"
    assert real_index_dir(SimpleNamespace(cache_dir=str(tmp_path))) == (
        tmp_path / "docs-index"
    )


def test_configs_without_a_cache_folder_use_the_old_folders() -> None:
    assert real_index_dir(None) is None
    assert real_index_dir({"cache_dir": "x"}) is None
    assert real_index_dir(SimpleNamespace(cache_dir=object())) is None
    assert real_index_dir(SimpleNamespace(cache_dir="")) is None


def test_lookups_find_the_index_in_the_cache_folder_first(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(docs_discovery, "_config_index_dir", real_index_dir)
    index = tmp_path / "docs-index" / "solidworks_docs_index_2031.json"
    index.parent.mkdir()
    index.write_text("{}", encoding="utf-8")

    assert (
        docs_discovery._find_index_file(2031, SimpleNamespace(cache_dir=tmp_path))
        == index
    )
    assert docs_discovery._find_index_file(2031) is None


def test_an_unchanged_index_is_parsed_once(tmp_path: Path, monkeypatch) -> None:
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"version": "2.0"}), encoding="utf-8")
    first = docs_discovery._load_index_file(index)

    monkeypatch.setattr(
        json, "load", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("re-read"))
    )
    assert docs_discovery._load_index_file(index) is first


def test_a_changed_index_is_read_again(tmp_path: Path) -> None:
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"version": "2.0"}), encoding="utf-8")
    docs_discovery._load_index_file(index)

    index.write_text(json.dumps({"version": "2.0", "more": True}), encoding="utf-8")
    stat = index.stat()
    os.utime(index, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    assert docs_discovery._load_index_file(index) == {"version": "2.0", "more": True}


def test_a_missing_index_is_none(tmp_path: Path) -> None:
    assert docs_discovery._load_index_file(tmp_path / "missing.json") is None
