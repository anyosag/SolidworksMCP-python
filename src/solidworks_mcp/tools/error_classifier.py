"""Classify tool failures into actionable error categories.

The MCP tool error boundary (``tool_boundary``) asks this module what kind of
failure it is looking at, so the payload can carry an ``error_type`` and a
``hint`` telling the caller what to do next instead of an opaque message.

Adapter errors usually arrive as *strings* - ``_handle_com_operation`` flattens
COM exceptions to ``"COM error in <op>: (<hresult>, '<text>', ...)"`` - so every
rule can match on the message text, and COM rules also on the HRESULT taken
from either a ``com_error`` exception or that text.

Rules are evaluated in order; the first match wins. Add a category by
appending a rule - callers never change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# HRESULTs (signed 32-bit, as pywin32 reports them).
RPC_E_DISCONNECTED = -2147417848  # 0x80010108
RPC_S_SERVER_UNAVAILABLE = -2147023174  # 0x800706BA
RPC_S_CALL_FAILED = -2147023170  # 0x800706BE
DISP_E_MEMBERNOTFOUND = -2147352573  # 0x80020003
DISP_E_TYPEMISMATCH = -2147352571  # 0x80020005

_HRESULT_IN_TEXT = re.compile(r"\((-\d{9,10}),")

OPERATION_FAILED = "operation_failed"
INTERNAL = "internal"
INVALID_INPUT = "invalid_input"
NOT_SUPPORTED = "not_supported"
NOT_SUPPORTED_HINT = (
    "The active adapter cannot perform this operation. Use the real SolidWorks "
    "adapter, another tool, or do this step in SolidWorks directly."
)


@dataclass(frozen=True)
class Classification:
    """The category of a failure and the next step to suggest."""

    error_type: str
    hint: str


@dataclass(frozen=True)
class ErrorRule:
    """Matches a failure by HRESULT and/or a case-insensitive message pattern."""

    error_type: str
    hint: str
    hresults: frozenset[int] = field(default_factory=frozenset)
    patterns: tuple[str, ...] = ()

    def matches(self, message: str, hresult: int | None) -> bool:
        """Return True when the HRESULT or any pattern matches."""
        if hresult is not None and hresult in self.hresults:
            return True
        return any(re.search(p, message, re.IGNORECASE) for p in self.patterns)


SOLIDWORKS_DIALOG = "solidworks_dialog"
CONFIRMATION_REQUIRED = "confirmation_required"
SOLIDWORKS_RECONNECTED = "solidworks_reconnected"
ACTIVE_DOCUMENT_CHANGED = "active_document_changed"
SOLIDWORKS_BUSY = "solidworks_busy"
OPERATION_STOPPED = "operation_stopped"

DEFAULT_RULES: tuple[ErrorRule, ...] = (
    # First: a dialog's own text can contain anything ("file not found",
    # "not connected"), and must not be classified by it.
    ErrorRule(
        error_type=SOLIDWORKS_DIALOG,
        hint=(
            "SolidWorks opened a dialog during this operation; its title, text "
            "and buttons are in `data.dialog`. The server cancelled it (it never "
            "answers Save or Don't Save), so the operation may not have "
            "finished. If the dialog asks for a decision, tell the user what it "
            "says; otherwise fix its cause and retry. When it could not be "
            "cancelled, SolidWorks was brought to the front for the user to "
            "answer it."
        ),
        patterns=(r"solidworks showed a dialog during",),
    ),
    ErrorRule(
        error_type=CONFIRMATION_REQUIRED,
        hint=(
            "Nothing was saved. Saving would overwrite the user's existing files "
            "listed in `data.files` with their unsaved changes. Ask the user "
            "whether to save those changes; if they agree, call the same tool "
            "again with `overwrite_modified_references: true`."
        ),
        patterns=(r"would overwrite \d+ modified file",),
    ),
    # Before solidworks_unavailable: the message says the old SolidWorks
    # has exited, which that rule also matches.
    ErrorRule(
        error_type=SOLIDWORKS_RECONNECTED,
        hint=(
            "SolidWorks was restarted (or crashed and was started again), and "
            "the server has reconnected to it; this call did nothing. "
            "Documents and sketches from before are gone unless the user "
            "reopened them: check with list_open_documents, reopen or recreate "
            "what you need (open_model, create_part), then retry."
        ),
        patterns=(r"has reconnected to the solidworks running now",),
    ),
    ErrorRule(
        error_type="solidworks_unavailable",
        hint=(
            "SolidWorks is not reachable - it was closed or crashed. Ask the "
            "user to start SolidWorks; the next call reconnects to it (restart "
            "the MCP server only if it still fails). Documents open before are "
            "gone unless the user reopens them."
        ),
        hresults=frozenset(
            {RPC_E_DISCONNECTED, RPC_S_SERVER_UNAVAILABLE, RPC_S_CALL_FAILED}
        ),
        patterns=(
            r"rpc server is unavailable",
            r"object invoked has disconnected",
            r"not connected to solidworks",
            r"solidworks (application )?(is )?not connected",
            r"solidworks is not running",
            r"the solidworks this server was connected to has exited",
        ),
    ),
    ErrorRule(
        error_type=ACTIVE_DOCUMENT_CHANGED,
        hint=(
            "Nothing was done: since this session's last call, the user or "
            "another program switched SolidWorks to another document, and the "
            "call would have changed that one. If the user didn't say which "
            "document to work on, ask. Then retry with `document` set to it "
            "(the message names both), or call activate_document first."
        ),
        patterns=(r"active document changed between calls",),
    ),
    ErrorRule(
        error_type=SOLIDWORKS_BUSY,
        hint=(
            "Nothing was run: SolidWorks is still busy with a long operation (an "
            "earlier call, another program, or the user) and isn't answering. "
            "Wait a minute and retry. If it stays busy, tell the user; if no "
            "one is using it, it may be stuck and need restarting."
        ),
        patterns=(r"solidworks is busy: it has not answered",),
    ),
    ErrorRule(
        error_type=OPERATION_STOPPED,
        hint=(
            "The server stopped this operation part-way: it ran past "
            "SOLIDWORKS_MCP_OPERATION_TIMEOUT_SECONDS, or the client went away. "
            "Check what it did (list_features, get_model_info), then do the work "
            "in smaller pieces, e.g. fewer edges or outlines per call."
        ),
        patterns=(
            r"ran past its \d+ s limit",
            r"the mcp client disconnected",
        ),
    ),
    ErrorRule(
        error_type="com_wrong_thread",
        hint=(
            "A SolidWorks call ran off the thread that connected - a server "
            "bug. Report the tool name; restart the MCP server to recover."
        ),
        patterns=(r"belong to the thread that called connect",),
    ),
    ErrorRule(
        error_type="circuit_open",
        hint=(
            "Calls to this operation are paused after repeated failures. Fix "
            "the underlying error, then call `reset_circuit_breaker` (or wait "
            "for the breaker timeout, SOLIDWORKS_MCP_CIRCUIT_BREAKER_TIMEOUT "
            "seconds) and retry."
        ),
        patterns=(r"circuit breaker is (open|half[_-]open)",),
    ),
    ErrorRule(
        error_type="com_member_not_found",
        hint=(
            "SolidWorks could not resolve this API member. Usually a server "
            "bug: a method called without being flagged as one (report the "
            "tool name). After a SolidWorks upgrade it can be a stale type "
            "cache: delete %TEMP%\\gen_py and restart the MCP server."
        ),
        hresults=frozenset({DISP_E_MEMBERNOTFOUND}),
        patterns=(r"member not found",),
    ),
    ErrorRule(
        error_type="com_type_mismatch",
        hint=(
            "SolidWorks rejected an argument's COM type. This is a server bug; "
            "report the tool name and arguments."
        ),
        hresults=frozenset({DISP_E_TYPEMISMATCH}),
        patterns=(r"type mismatch",),
    ),
    ErrorRule(
        error_type=NOT_SUPPORTED,
        hint=NOT_SUPPORTED_HINT,
        patterns=(
            r"does not support",
            r"no adapter capability",
            r"only available on windows",
            r"not available",
        ),
    ),
    ErrorRule(
        error_type="wrong_document_type",
        hint=(
            "The active document is the wrong kind for this tool. Create or "
            "activate the right one (create_part, create_assembly, "
            "create_drawing or activate_document), then retry."
        ),
        patterns=(
            r"(requires|needs) an? (active )?(part|assembly|drawing)"
            r"( or (part|assembly|drawing))? document",
        ),
    ),
    ErrorRule(
        error_type="no_active_sketch",
        hint="Create or open a sketch first (create_sketch), then retry.",
        patterns=(r"no active sketch",),
    ),
    ErrorRule(
        error_type="no_active_document",
        hint=(
            "Open or create a document first (open_model / create_part), or "
            "activate one with activate_document, then retry."
        ),
        patterns=(r"no active (model|document)",),
    ),
    ErrorRule(
        error_type="feature_not_built",
        hint=(
            "SolidWorks accepted the call but the geometry gave it nothing to "
            "build. For a cut: the profile must be a closed loop that overlaps "
            "the solid within the depth; one-direction cuts already try both "
            "directions, so change the sketch, its plane, the depth or use "
            "end_condition 'ThroughAll' rather than retrying as is."
        ),
        patterns=(r"built no feature",),
    ),
    ErrorRule(
        error_type="not_found",
        hint=(
            "Check the name or path - list what exists first (list_features, "
            "list_open_documents, list_drawing_views) and use an exact name."
        ),
        patterns=(
            r"\bnot found\b",
            r"does not exist",
            r"\bno such\b",
            r"\bno [\w.-]+( \w+)? found\b",
            r"\bhas no (\w+ )?(edges|faces)\b",
            r"\bhas no [\w-]+ body\b",
            r"\bno view named\b",
            r"\bno open document matches\b",
        ),
    ),
)

_FALLBACK_HINTS = {
    OPERATION_FAILED: (
        "The SolidWorks operation failed. Read the message for the cause, "
        "adjust the inputs, and retry."
    ),
    INTERNAL: (
        "Unexpected server error - this is a bug, not a modelling problem. "
        "Report the tool name, arguments and this message."
    ),
}


def extract_hresult(message: str, exc: BaseException | None = None) -> int | None:
    """Return the COM HRESULT from a ``com_error`` or from flattened text."""
    if exc is not None:
        args = getattr(exc, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
    match = _HRESULT_IN_TEXT.search(message)
    return int(match.group(1)) if match else None


class ErrorClassifier:
    """Map a failure to a :class:`Classification` using ordered rules."""

    def __init__(self, rules: tuple[ErrorRule, ...] = DEFAULT_RULES) -> None:
        self._rules = rules

    def classify(
        self,
        message: str,
        exc: BaseException | None = None,
        *,
        fallback: str = OPERATION_FAILED,
    ) -> Classification:
        """Classify ``message`` (and ``exc`` when there is one).

        Args:
            message: The error text the caller will see.
            exc: The exception, when the failure was raised rather than returned.
            fallback: Category for an unrecognised failure: ``operation_failed``
                for adapter errors, ``internal`` for unexpected exceptions.

        Returns:
            Classification: The first matching rule, else the fallback.
        """
        hresult = extract_hresult(message, exc)
        for rule in self._rules:
            if rule.matches(message, hresult):
                return Classification(rule.error_type, rule.hint)
        return Classification(fallback, _FALLBACK_HINTS[fallback])
