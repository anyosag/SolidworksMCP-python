"""Save documents without SolidWorks dialogs, and ask before overwriting.

Saving an assembly whose parts have unsaved changes made SolidWorks show its
modal "Save Modified Documents" dialog, which blocks the COM thread until
someone answers it (measured on SOLIDWORKS 2026 SP4.1 with
``tests/scripts/probe_minimized.py --saves``: both an in-place save and
``close_model(save=True)``). The old save paths weren't silent:

* ``Save3(1, None, None)`` can't marshal its by-ref out-parameters under late
  binding, so it fell back to the legacy ``Save()``, which shows dialogs;
* Save As passed no options;
* ``close_model(save=True)`` called ``Save``.

:func:`save_document` saves with ``swSaveAsOptions_Silent`` (and
``SaveReferenced`` for an assembly, so its modified parts are written too),
passes real by-ref out-parameters, and turns the error and warning flags into
names.

Before an assembly save writes its modified parts, they are sorted:

* never saved, virtual, or created or first saved by this server session:
  saved with the assembly;
* saved by this session before, and unchanged on disk since: its unsaved
  changes are this session's own edits (the Cellvis dish rack's parts were
  the user's files, and every assembly save after the first asked again);
* any other modified file - the user's own work - is not overwritten unless
  the caller passed ``overwrite_modified_references``. The save returns
  :class:`NeedsConfirmation` instead, and the tool reports
  ``error_type: confirmation_required`` with the files.

The option values come from the SW 2026 constants type library
(``swconst.tlb``): ``swSaveAsOptions_Silent`` is 1, ``Copy`` 2,
``SaveReferenced`` 4.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from ..base import AdapterResult, AdapterResultStatus

# swSaveAsOptions_e
SAVE_SILENT = 1
SAVE_COPY = 2
SAVE_REFERENCED = 4

# swDocumentTypes_e
DOC_PART = 1
DOC_ASSEMBLY = 2
DOC_DRAWING = 3

#: The tool argument that confirms overwriting the user's modified files.
CONFIRM_FLAG = "overwrite_modified_references"

# swFileSaveError_e
SAVE_ERRORS = {
    1: "swGenericSaveError",
    2: "swReadOnlySaveError",
    4: "swFileNameEmpty",
    8: "swFileNameContainsAtSign",
    16: "swFileLockError",
    32: "swFileSaveFormatNotAvailable",
    64: "swFileSaveWithRebuildError",
    128: "swFileSaveAsDoNotOverwrite",
    256: "swFileSaveAsInvalidFileExtension",
    512: "swFileSaveAsNoSelection",
    1024: "swFileSaveAsBadEDrawingsVersion",
    2048: "swFileSaveAsNameExceedsMaxPathLength",
    4096: "swFileSaveAsNotSupported",
    8192: "swFileSaveRequiresSavingReferences",
    16384: "swFileSaveAsDetachedDrawingsNotSupported",
    32768: "swFileSaveDoNotUpgradeError",
    65536: "swFileSaveIncompatibleItemsError",
}

# swFileSaveWarning_e
SAVE_WARNINGS = {
    1: "swFileSaveWarning_RebuildError",
    2: "swFileSaveWarning_NeedsRebuild",
    4: "swFileSaveWarning_ViewsNeedUpdate",
    8: "swFileSaveWarning_AnimatorNeedToSolve",
    16: "swFileSaveWarning_AnimatorFeatureEdits",
    32: "swFileSaveWarning_EdrwingsBadSelection",
    64: "swFileSaveWarning_AnimatorLightEdits",
    128: "swFileSaveWarning_AnimatorCameraViews",
    256: "swFileSaveWarning_AnimatorSectionViews",
    512: "swFileSaveWarning_MissingOLEObjects",
    1024: "swFileSaveWarning_OpenedViewOnly",
    2048: "swFileSaveWarning_XmlInvalid",
}


def flag_names(value: Any, names: dict[int, str]) -> list[str]:
    """The names of the bits set in a SolidWorks flags value."""
    try:
        bits = int(getattr(value, "value", value) or 0)
    except (TypeError, ValueError):
        return []
    return [name for bit, name in names.items() if bits & bit]


def normalize(path: str) -> str:
    """A path in the form used to compare files (absolute, case-folded)."""
    return os.path.normcase(os.path.abspath(path))


def session_paths(adapter: Any) -> set[str]:
    """The files this server session created or saved for the first time."""
    paths = getattr(adapter, "_session_paths", None)
    if paths is None:
        paths = set()
        adapter._session_paths = paths
    return paths


def remember(adapter: Any, path: str) -> None:
    """Record a file this session wrote for the first time."""
    session_paths(adapter).add(normalize(path))


def _modified_time(path: str) -> float | None:
    """The file's modification time, or None when it can't be read."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def session_saves(adapter: Any) -> dict[str, float | None]:
    """The files this session saved, with their modification time just after."""
    saves = getattr(adapter, "_session_saves", None)
    if saves is None:
        saves = {}
        adapter._session_saves = saves
    return saves


def record_save(adapter: Any, path: str) -> None:
    """Record that this session saved ``path`` (and when the file then changed)."""
    session_saves(adapter)[normalize(path)] = _modified_time(path)


def saved_by_session(adapter: Any, path: str) -> bool:
    """Whether this session saved ``path`` and nobody has saved it since."""
    key = normalize(path)
    saves = session_saves(adapter)
    if key not in saves:
        return False
    recorded, now = saves[key], _modified_time(path)
    return recorded is not None and now == recorded


@dataclass
class Reference:
    """A document an assembly uses that has unsaved changes."""

    path: str
    #: Never saved, virtual, written by this session, or saved by it and
    #: unchanged on disk since: saved without asking.
    new: bool


@dataclass
class NeedsConfirmation:
    """A save that would overwrite the user's modified files; nothing written."""

    files: list[str]


def document_type(adapter: Any, model: Any) -> int:
    """``swDocumentTypes_e`` of ``model`` (0 when it can't be read)."""
    value = adapter._attempt(lambda: adapter._get_attr_or_call(model, "GetType"))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def modified_references(adapter: Any, assembly: Any) -> list[Reference]:
    """The documents ``assembly`` uses, at every level, with unsaved changes.

    Components that aren't loaded (suppressed, lightweight) have no model
    document and can't have unsaved changes, so they are skipped.
    """
    from .io import _as_com

    components = adapter._attempt(lambda: assembly.GetComponents(False), default=None)
    references: dict[str, Reference] = {}
    for component in components or ():
        wrapped = _as_com(adapter, component, "IComponent2") or component
        doc = adapter._attempt(
            lambda w=wrapped: adapter._get_attr_or_call(w, "GetModelDoc2")
        )
        if doc is None:
            continue
        dirty = adapter._attempt(
            lambda d=doc: adapter._get_attr_or_call(d, "GetSaveFlag")
        )
        if not dirty:
            continue
        path = str(
            adapter._attempt(lambda d=doc: adapter._get_attr_or_call(d, "GetPathName"))
            or ""
        )
        virtual = bool(
            adapter._attempt(
                lambda w=wrapped: adapter._get_attr_or_call(w, "IsVirtual")
            )
        )
        new = (
            not path
            or virtual
            or not os.path.exists(path)
            or normalize(path) in session_paths(adapter)
            or saved_by_session(adapter, path)
        )
        key = normalize(path) if path else f"<unsaved {len(references)}>"
        references.setdefault(key, Reference(path=path, new=new))
    return list(references.values())


def confirmation_message(files: list[str]) -> str:
    """The error text for a save that needs the user's confirmation."""
    count = len(files)
    noun = "file" if count == 1 else "files"
    return (
        f"Saving would overwrite {count} modified {noun} that existed before "
        f"this session: {', '.join(files)}. Nothing was saved."
    )


def confirmation_result(
    files: list[str], execution_time: float | None = None
) -> AdapterResult[Any]:
    """The error result for :class:`NeedsConfirmation`."""
    return AdapterResult(
        status=AdapterResultStatus.ERROR,
        error=confirmation_message(files),
        data={"files": files, "confirm_with": CONFIRM_FLAG},
        execution_time=execution_time,
    )


def _failure(action: str, errors: list[str]) -> Exception:
    detail = f" ({', '.join(errors)})" if errors else ""
    return Exception(f"{action}{detail}")


def save_document(
    adapter: Any,
    model: Any,
    file_path: str | None = None,
    overwrite_modified_references: bool = False,
) -> NeedsConfirmation | dict[str, Any]:
    """Save ``model`` in place, or as ``file_path``, without a dialog.

    Runs on the COM thread, inside ``_handle_com_operation``.

    Args:
        adapter: The connected adapter.
        model: The ``IModelDoc2`` to save.
        file_path: A new path to save as; ``None`` (or the document's own
            path) saves in place.
        overwrite_modified_references: Save the user's modified files that
            the assembly uses, after the user agreed.

    Returns:
        :class:`NeedsConfirmation` when the user's files would be
        overwritten (nothing is written); otherwise ``file_path``,
        ``saved_references`` (the other files written) and ``warnings``.

    Raises:
        Exception: SolidWorks refused the save; the message names its errors.
    """
    from .io import _byref_int

    doc_type = document_type(adapter, model)
    references: list[Reference] = []
    options = SAVE_SILENT
    if doc_type == DOC_ASSEMBLY:
        references = modified_references(adapter, model)
        user_files = [r.path for r in references if not r.new]
        if user_files and not overwrite_modified_references:
            return NeedsConfirmation(user_files)
        options |= SAVE_REFERENCED

    current = str(
        adapter._attempt(lambda: adapter._get_attr_or_call(model, "GetPathName")) or ""
    )
    target = os.path.abspath(file_path) if file_path else current
    if not target:
        raise Exception(
            "The document has never been saved; give a file_path to save it to"
        )
    in_place = bool(current) and normalize(current) == normalize(target)

    warnings: list[str] = []
    if in_place:
        errors_out, warnings_out = _byref_int(), _byref_int()
        saved = model.Save3(options, errors_out, warnings_out)
        errors = flag_names(errors_out, SAVE_ERRORS)
        warnings = flag_names(warnings_out, SAVE_WARNINGS)
        if not saved or errors:
            raise _failure("Failed to save file", errors)
    else:
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # A *different* document may be holding the target path open. Close
        # that one by name only - never the document being saved.
        if adapter.swApp:
            adapter._attempt(lambda: adapter.swApp.CloseDoc(os.path.basename(target)))
        # SaveAs3 returns 0 on success, else swFileSaveError_e flags (fakes
        # may return a bool). Deliberately no os.remove before it: SaveAs3
        # overwrites, and deleting first meant a failed save lost the old file.
        code = model.SaveAs3(target, 0, options)
        failed = code is False or (not isinstance(code, bool) and bool(code))
        if failed or not os.path.exists(target):
            errors = [] if isinstance(code, bool) else flag_names(code, SAVE_ERRORS)
            raise _failure(f"Failed to save as: {target}", errors)
        if not current or normalize(current) != normalize(target):
            remember(adapter, target)

    if not os.path.exists(target):
        raise Exception(f"File not written after save: {target}")
    record_save(adapter, target)
    for reference in references:
        if reference.path and os.path.exists(reference.path):
            record_save(adapter, reference.path)
    return {
        "file_path": target,
        "saved_references": [r.path for r in references if r.path],
        "warnings": warnings,
    }
