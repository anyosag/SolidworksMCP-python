"""Which tools take ``document``: the open document to work on.

Most tools act on SolidWorks' active document. With two clients on one
SolidWorks, or a user switching documents, a session had to call
``activate_document`` before each call to be sure of its target. Every tool
listed here takes an optional ``document`` (a title, file name or path of an
open document); the tool boundary makes that document the active one before
the tool runs, and refuses the call when it isn't open.
"""

from __future__ import annotations

#: Families whose tools act on an open document.
DOCUMENT_FAMILIES = frozenset(
    {
        "analysis",
        "drawing",
        "drawing_analysis",
        "drawing_automation",
        "engineering_data",
        "export",
        "file_management",
        "modeling",
        "sketching",
    }
)

#: Tools of those families that pick, create or list documents, or work on
#: files on disk, so a target document means nothing to them.
CHOOSE_THEIR_OWN = frozenset(
    {
        "activate_document",
        "batch_export",
        "batch_file_operations",
        "compare_drawing_versions",
        "convert_file_format",
        "create_assembly",
        "create_drawing",
        "create_part",
        "generate_drawing_package",
        "list_open_documents",
        "load_assembly",
        "load_part",
        "manage_file_properties",
        "open_model",
        "pack_and_go_assembly",
    }
)

#: Tools of other families that act on the open document.
ALSO_TAKE_DOCUMENT = frozenset({"execute_workflow"})

DOCUMENT_DESCRIPTION = (
    "The open document to work on: its title, file name or path. The server "
    "makes it the active document first, and the call fails if it isn't open. "
    "Leave it out to use the active document."
)


def takes_document(tool_name: str, family: str) -> bool:
    """Whether the tool ``tool_name`` of ``family`` takes ``document``."""
    if tool_name in ALSO_TAKE_DOCUMENT:
        return True
    return family in DOCUMENT_FAMILIES and tool_name not in CHOOSE_THEIR_OWN
