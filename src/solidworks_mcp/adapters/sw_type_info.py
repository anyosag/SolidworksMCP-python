"""
SolidWorks type-library introspection for robust COM method resolution.

Background: pywin32's late-binding (``CDispatch``) sometimes resolves SW
zero-argument methods (``GetType``, ``GetTitle``, ``GetPathName``,
``RevisionNumber`` …) as *properties* instead of methods. Calling them raises
``TypeError: 'int'/'str' object is not callable`` because the property getter
returns the value, and Python tries to call the value.

Fix: call ``CDispatch._FlagAsMethod(name)`` for each method name **that actually
belongs to the object's COM interface**. The calls tell pywin32 to resolve
``name`` via method invocation (IDispatch ``Invoke``), not property access.

This module:

1. Loads the makepy-generated wrapper for ``sldworks.tlb`` (``gen_py``).
2. Builds per-interface sets of method names (``ISldWorks``, ``IModelDoc2``,
   ``IAssemblyDoc``, ``IPartDoc``, ``IDrawingDoc`` …).
3. Exposes ``flag_methods(obj, *interfaces)`` to flag a dispatch in one shot.

Why per-interface rather than flagging everything: flagging an unknown name
triggers a COM ``GetIDsOfNames`` round-trip that fails with ``Unknown name.``.
Those round-trips are ~5 ms each; the full SW TLB has ~6 000 method names
across 482 interfaces, so a naive flag-everything approach costs ~30 s per
object. Per-interface flagging is ~1-3 s.

Fallback: if the gen_py wrapper is missing (e.g. fresh install on a new box),
we attempt lazy generation via ``gencache.EnsureModule``. If that also fails,
``flag_methods`` silently becomes a no-op; callers will fall back to the
original ``TypeError`` symptom on affected methods, but everything else still
works.
"""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import weakref
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from loguru import logger

try:
    import win32com
    import win32com.client  # noqa: F401 — optional Windows dep
    from win32com.client import DispatchBaseClass, build, gencache

    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


# SolidWorks type library IID (stable across SW versions).
SW_TLB_IID = "{83A33D31-27C5-11CE-BFD4-00400513BB57}"

# Type library major versions, newest first. SW 3DEXPERIENCE R2026x = 34,
# SW 2025 = 33, SW 2024 = 32, SW 2023 = 31, SW 2022 = 30.
_SW_MAJORS = (35, 34, 33, 32, 31, 30)

# Module state: populated by _load_wrapper() the first time it's needed. When
# the method table comes from the JSON cache, ``_wrapper_module`` is a stand-in
# carrying only the wrapper's ``__name__``.
_wrapper_module: Any | None = None
_interface_methods: dict[str, frozenset[str]] = {}
# Per-object record of which interfaces have already been flagged. Keyed by
# id(obj) so ``flag_methods(doc, 'IModelDoc2')`` followed by
# ``flag_methods(doc, 'IAssemblyDoc')`` does incremental work, not a no-op.
# Value is (weak reference to the object, interfaces already flagged). The
# weakref is what makes the id() key safe to trust — see _flagged_interfaces.
_flag_cache: dict[int, tuple[weakref.ref[Any] | None, set[str]]] = {}

# DISPIDs learned from the first object flagged for an (interface, context)
# pair, reused for later objects of the same kind - see flag_methods.
_dispid_memo: dict[tuple[str, Any], dict[str, int]] = {}
# Pairs whose DISPIDs once differed between two objects; never memoised again.
_dispid_memo_unsafe: set[tuple[str, Any]] = set()


def _switch_on(variable: str) -> bool:
    """An on-by-default switch: off only for 0 / false / no / off."""
    return os.getenv(variable, "1").strip().lower() not in {"0", "false", "no", "off"}


def _cache_dir() -> Path:
    """Where the method-name table cache lives.

    ``SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR`` overrides it; the default sits in
    the temp folder, beside pywin32's own ``gen_py`` cache.
    """
    override = os.getenv("SOLIDWORKS_MCP_TYPEINFO_CACHE_DIR", "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "solidworks_mcp" / "typeinfo"


def _generated_wrapper_file(major: int) -> Path | None:
    """The generated ``gen_py`` file for type library ``major``, if any.

    Found without importing it. A wrapper generated as a package (pywin32's
    on-demand mode) has no single file and returns ``None``, so it is
    imported and never cached.
    """
    try:
        name = gencache.GetGeneratedFileName(SW_TLB_IID, 0, major, 0)
        path = Path(win32com.__gen_path__) / f"{name}.py"
    except Exception:
        return None
    return path if path.is_file() else None


def _cache_file_for(wrapper_file: Path) -> Path:
    """The cache file for one generated wrapper, keyed by its size and mtime."""
    stat = wrapper_file.stat()
    return _cache_dir() / f"{wrapper_file.stem}-{stat.st_size}-{stat.st_mtime_ns}.json"


def _read_cached_table(wrapper_file: Path) -> dict[str, frozenset[str]] | None:
    """The cached method table for ``wrapper_file``, or None when there's none."""
    try:
        with _cache_file_for(wrapper_file).open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    return {str(name): frozenset(map(str, methods)) for name, methods in raw.items()}


def _write_cached_table(wrapper_file: Path, table: dict[str, frozenset[str]]) -> None:
    """Save the method table for ``wrapper_file``; drop older caches of it."""
    try:
        target = _cache_file_for(wrapper_file)
        target.parent.mkdir(parents=True, exist_ok=True)
        for stale in target.parent.glob(f"{wrapper_file.stem}-*.json"):
            if stale != target:
                stale.unlink(missing_ok=True)
        payload = {name: sorted(methods) for name, methods in table.items()}
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(payload), encoding="utf-8")
        temp.replace(target)
    except OSError as exc:
        logger.debug("Could not cache the SolidWorks method table: {}", exc)


def _load_cached_wrapper() -> bool:
    """Load the method table from the JSON cache, skipping the gen_py import.

    Importing the generated SW 2026 wrapper (6.3 MB of Python) takes about
    1.3 s per process; the same table as JSON loads in about 10 ms
    (docs/agents/mcp-speed-review.md, finding 5).

    ``SOLIDWORKS_MCP_TYPEINFO_CACHE=0`` turns the cache off.

    Returns:
        bool: True when the table was loaded from the cache.
    """
    global _wrapper_module, _interface_methods
    if not _switch_on("SOLIDWORKS_MCP_TYPEINFO_CACHE"):
        return False
    for major in _SW_MAJORS:
        wrapper_file = _generated_wrapper_file(major)
        if wrapper_file is None:
            continue
        table = _read_cached_table(wrapper_file)
        if table is None:
            return False
        _interface_methods = table
        _wrapper_module = SimpleNamespace(
            __name__=f"win32com.gen_py.{wrapper_file.stem}"
        )
        logger.info(
            f"SolidWorks type info loaded from cache: {len(table)} interfaces, "
            f"wrapper={_wrapper_module.__name__}"
        )
        return True
    return False


def _cache_loaded_wrapper() -> None:
    """Save the just-scanned method table, keyed by the wrapper it came from."""
    if not _switch_on("SOLIDWORKS_MCP_TYPEINFO_CACHE"):
        return
    module_file = getattr(_wrapper_module, "__file__", None)
    if not module_file or not _interface_methods:
        return
    wrapper_file = Path(module_file)
    if wrapper_file.suffix == ".py" and wrapper_file.is_file():
        _write_cached_table(wrapper_file, _interface_methods)


def _load_wrapper() -> None:
    """Load the gen_py wrapper and extract per-interface method names.

    Reads the JSON cache of the method table first (no import). Otherwise
    tries ``GetModuleForTypelib`` (no COM work), falls back to
    ``EnsureModule`` (may trigger makepy generation), then gives up and logs
    a warning. Probes common SW major versions because the major number
    changes per SW year. A table scanned from the wrapper is cached for the
    next process.
    """
    global _wrapper_module, _interface_methods

    if _load_cached_wrapper():
        return

    for major in _SW_MAJORS:
        try:
            mod = gencache.GetModuleForTypelib(SW_TLB_IID, 0, major, 0)
        except Exception:
            mod = None
        if mod is not None:
            _wrapper_module = mod
            break

    if _wrapper_module is None:
        # Gen_py wrapper not generated yet — try to generate now.
        for major in _SW_MAJORS:
            try:
                gencache.EnsureModule(SW_TLB_IID, 0, major, 0)
                _wrapper_module = gencache.GetModuleForTypelib(SW_TLB_IID, 0, major, 0)
                if _wrapper_module is not None:
                    break
            except Exception:
                continue

    if _wrapper_module is None:
        logger.warning(
            "SolidWorks gen_py wrapper not available; method flagging "
            "disabled. Zero-arg SW methods may raise TypeError. To fix, "
            "run: python -m win32com.client.makepy "
            '"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\sldworks.tlb"'
        )
        return

    # Build per-interface method sets by inspecting each DispatchBaseClass
    # subclass in the wrapper module.
    for name in dir(_wrapper_module):
        cls = getattr(_wrapper_module, name, None)
        if not (inspect.isclass(cls) and issubclass(cls, DispatchBaseClass)):
            continue
        method_names: set[str] = set()
        for attr_name, attr in vars(cls).items():
            if attr_name.startswith("_"):
                continue
            if callable(attr):
                method_names.add(attr_name)
        if method_names:
            _interface_methods[name] = frozenset(method_names)

    logger.info(
        f"SolidWorks type info loaded: {len(_interface_methods)} interfaces, "
        f"wrapper={_wrapper_module.__name__}"
    )
    _cache_loaded_wrapper()


def _ensure_loaded() -> None:
    """Lazy-load the wrapper on first use."""
    if _wrapper_module is None and PYWIN32_AVAILABLE:
        _load_wrapper()


def interface_method_names(interface: str) -> frozenset[str]:
    """Return the set of method names declared by the given SW interface.

    Args:
        interface: Interface name as it appears in the type library
            (e.g. ``"ISldWorks"``, ``"IModelDoc2"``).

    Returns:
        Immutable set of method names, or an empty set if the interface is
        unknown or the wrapper isn't loaded.
    """
    _ensure_loaded()
    return _interface_methods.get(interface, frozenset())


def all_interface_methods() -> dict[str, frozenset[str]]:
    """Every interface's method names, as the type library declares them.

    Returns:
        dict[str, frozenset[str]]: Interface name to method names; empty if
        the wrapper isn't available.
    """
    _ensure_loaded()
    return dict(_interface_methods)


def type_library_name() -> str | None:
    """The loaded gen_py wrapper's module name, which carries its version.

    Returns:
        str | None: e.g. ``"win32com.gen_py.<IID>x0x34x0"``; None if the
        wrapper isn't available.
    """
    _ensure_loaded()
    return None if _wrapper_module is None else _wrapper_module.__name__


# Interface sets most tool operations need to flag. When acquiring a doc
# dispatch, always flag IModelDoc2 (base) plus the subclass that matches the
# doc type. For the app root, flag ISldWorks.
DOC_TYPE_TO_INTERFACES: dict[int, tuple[str, ...]] = {
    # Values match swDocumentTypes_e: 1=Part, 2=Assembly, 3=Drawing
    1: ("IModelDoc2", "IPartDoc"),
    2: ("IModelDoc2", "IAssemblyDoc"),
    3: ("IModelDoc2", "IDrawingDoc"),
}


def _flagged_interfaces(obj: Any) -> set[str]:
    """Return the set of interfaces already flagged on ``obj``.

    The entry is keyed by ``id(obj)`` for speed, but is only trusted when the
    stored weak reference still resolves to *this same object*. Without that
    check the cache is unsound: ids are only unique among live objects, and
    CPython reuses addresses eagerly. A fresh dispatch landing on a dead one's
    address was judged "already flagged", so ``flag_methods`` returned without
    flagging anything and its members then resolved as properties — surfacing
    from SolidWorks as "Member not found".

    Objects that do not support weak references (some test doubles) simply are
    not cached; they are flagged every time, which is correct if slower.
    """
    key = id(obj)
    entry = _flag_cache.get(key)
    if entry is not None:
        ref, names = entry
        if ref is None or ref() is obj:
            return names
        # Stale: the object this entry described is gone and its address has
        # been recycled. Drop it and start fresh for the new occupant.
        del _flag_cache[key]

    names = set()
    try:
        _flag_cache[key] = (weakref.ref(obj), names)
    except TypeError:
        # Not weak-referenceable, so we cannot detect a later address reuse.
        # Skip caching rather than risk the stale-entry bug.
        pass
    return names


def _method_map(obj: Any) -> dict[str, Any] | None:
    """The pywin32 late-binding method map of ``obj``, when it has one.

    ``CDispatch._FlagAsMethod(name)`` does exactly two things: look up the
    name's DISPID with a ``GetIDsOfNames`` round trip to SolidWorks, and store
    ``build.MapEntry(dispid, (name,))`` in ``obj._olerepr_.mapFuncs``. With
    the DISPID already known, filling the map directly is the same thing
    without the round trip.
    """
    funcs = getattr(getattr(obj, "_olerepr_", None), "mapFuncs", None)
    return funcs if isinstance(funcs, dict) else None


def _memo_matches(obj: Any, memo: dict[str, int]) -> bool:
    """Whether ``obj`` resolves a few of ``memo``'s names to the same DISPIDs.

    A cheap guard (one round trip per canary instead of one per name) that
    SolidWorks numbers this object's members the way it numbered the object
    the memo was learned from.
    """
    oleobj = getattr(obj, "_oleobj_", None)
    if oleobj is None:
        return False
    names = sorted(memo)
    canaries = {names[0], names[-1]}
    try:
        return all(oleobj.GetIDsOfNames(0, name) == memo[name] for name in canaries)
    except Exception:
        return False


def _flag_interface(
    obj: Any, iface: str, names: list[str], context: Any, funcs: dict[str, Any] | None
) -> int:
    """Flag ``names`` (one interface's methods) on ``obj``; return how many.

    With the DISPID memo on and a memo for ``(iface, context)`` that passes
    its canary check, the method map is filled with no round trips.
    Otherwise every name goes through ``_FlagAsMethod`` and, when ``obj``
    exposes its method map, the DISPIDs are remembered for the next object.
    """
    key = (iface, context)
    memo_on = (
        funcs is not None
        and PYWIN32_AVAILABLE
        and key not in _dispid_memo_unsafe
        and _switch_on("SOLIDWORKS_MCP_DISPID_MEMO")
    )
    memo = _dispid_memo.get(key) if memo_on else None
    if memo:
        if _memo_matches(obj, memo):
            for name in names:
                dispid = memo.get(name)
                if dispid is not None:
                    funcs[name] = build.MapEntry(dispid, (name,))  # type: ignore[index]
            return sum(1 for name in names if name in memo)
        # The same names numbered differently on two objects: stop memoising
        # this pair and flag every name the slow way from now on.
        _dispid_memo.pop(key, None)
        _dispid_memo_unsafe.add(key)
        memo_on = False
        logger.warning(
            "DISPIDs for {} ({}) differ between objects; memo disabled for it",
            iface,
            context,
        )

    learned: dict[str, int] = {}
    flagged = 0
    for name in names:
        try:
            obj._FlagAsMethod(name)
            flagged += 1
        except Exception:
            # Name not on this dispatch's real interface — skip silently.
            continue
        if memo_on:
            dispid = getattr(funcs.get(name), "dispid", None)  # type: ignore[union-attr]
            if isinstance(dispid, int):
                learned[name] = dispid
    if memo_on and learned:
        _dispid_memo[key] = learned
    return flagged


def flag_methods(obj: Any, *interfaces: str, context: Any = None) -> int:
    """Flag SW methods on ``obj`` so pywin32 dispatches them as methods,
    not properties.

    Safe to call repeatedly on the same object — results are cached by
    ``id(obj)``. Unknown method names are silently skipped (those are
    the ones that don't belong to the object's real interface).

    Each name costs a ``GetIDsOfNames`` round trip to SolidWorks (~0.25 ms),
    and a part document has 906 of them. So the DISPIDs the first object of
    a kind returns are remembered per ``(interface, context)`` and copied into
    later objects' method maps, after a canary check of two names
    (``SOLIDWORKS_MCP_DISPID_MEMO=0`` turns this off).

    Args:
        obj: A pywin32 ``CDispatch`` wrapping a SolidWorks COM object.
        *interfaces: One or more interface names whose methods to flag.
            Common values: ``"ISldWorks"``, ``"IModelDoc2"``,
            ``"IAssemblyDoc"``, ``"IPartDoc"``, ``"IDrawingDoc"``.
        context: What kind of object this is beyond its interfaces (the
            document type for ``flag_doc``), so DISPIDs are never shared
            between objects SolidWorks might number differently.

    Returns:
        Number of methods successfully flagged.
    """
    _ensure_loaded()

    if not _interface_methods or obj is None:
        return 0

    already = _flagged_interfaces(obj)

    # Only flag methods from interfaces we haven't already processed for
    # this object. Repeats are a no-op; novel interfaces add incrementally.
    new_interfaces = [i for i in interfaces if i not in already]
    if not new_interfaces:
        return 0

    funcs = _method_map(obj)
    done: set[str] = set()
    flagged = 0
    for iface in new_interfaces:
        names = sorted(set(_interface_methods.get(iface, ())) - done)
        done.update(names)
        if names:
            flagged += _flag_interface(obj, iface, names, context, funcs)

    already.update(new_interfaces)
    return flagged


def flag_members(obj: Any, *names: str) -> int:
    """Flag a specific handful of method names on ``obj``.

    ``flag_methods`` flags *every* method of an interface — around 100 names
    for ``IFeature`` — and its cache is keyed by ``id(obj)``, so a loop over
    many short-lived dispatches (walking a feature tree, iterating components)
    pays that cost once per object and never hits the cache.

    When the caller knows exactly which members it is about to read, flagging
    just those is far cheaper and behaves identically for them.

    Args:
        obj: A pywin32 ``CDispatch`` wrapping a SolidWorks COM object.
        *names: Method names to flag.

    Returns:
        int: Number of names flagged.
    """
    if obj is None:
        return 0

    flagged_count = 0
    for name in names:
        try:
            obj._FlagAsMethod(name)
            flagged_count += 1
        except Exception:
            # Not on this dispatch's real interface — skip silently.
            pass
    return flagged_count


def flagged(obj: Any, *interfaces: str) -> Any:
    """Flag ``obj``'s methods then return ``obj`` — call-chain friendly.

    Useful for inline flagging of short-lived dispatches::

        config = sw_type_info.flagged(
            model.GetActiveConfiguration(), "IConfiguration"
        )
        name = config.GetName()

    If ``obj`` is ``None`` (e.g. SW returned Nothing), passes through
    unchanged.
    """
    if obj is not None:
        flag_methods(obj, *interfaces)
    return obj


def flag_doc(obj: Any, doc_type: int) -> int:
    """Flag methods for a SolidWorks document dispatch given its type.

    Convenience wrapper around ``flag_methods`` that looks up the correct
    interface list for the document type.

    Args:
        obj: ``CDispatch`` wrapping the document.
        doc_type: Value returned by ``swDoc.GetType()`` — 1=Part, 2=Assembly,
            3=Drawing.

    Returns:
        Number of methods flagged.
    """
    interfaces = DOC_TYPE_TO_INTERFACES.get(doc_type, ("IModelDoc2",))
    return flag_methods(obj, *interfaces, context=doc_type)


def same_com_object(first: Any, second: Any) -> bool:
    """Whether two dispatches wrap the same COM object.

    ``swApp.ActiveDoc`` returns a new pywin32 wrapper on every read, so a
    wrapper already flagged for the active document looks new each time.
    pywin32 compares ``_oleobj_`` by the objects' ``IUnknown`` pointers, which
    the COM proxy answers without a call to SolidWorks.

    Args:
        first: A dispatch, or anything else.
        second: Another one.

    Returns:
        bool: True only when both wrap the same COM object; False for
        ``None``, plain Python objects, or a comparison that fails.
    """
    if first is None or second is None:
        return False
    if first is second:
        return True
    first_ole = getattr(first, "_oleobj_", None)
    second_ole = getattr(second, "_oleobj_", None)
    if first_ole is None or second_ole is None:
        return False
    try:
        return bool(first_ole == second_ole)
    except Exception:
        return False


def invalidate_flag_cache(obj: Any | None = None) -> None:
    """Forget that ``obj`` has been flagged, or clear the cache entirely.

    Needed when a dispatch is closed / re-acquired; the new object at the
    same address would otherwise be treated as already-flagged.
    """
    if obj is None:
        _flag_cache.clear()
        _dispid_memo.clear()
        _dispid_memo_unsafe.clear()
    else:
        _flag_cache.pop(id(obj), None)
