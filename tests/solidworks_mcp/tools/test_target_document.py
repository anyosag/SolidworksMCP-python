"""Which tools take ``document``."""

from __future__ import annotations

import pytest

from solidworks_mcp.tools.target_document import takes_document


@pytest.mark.parametrize(
    ("tool", "family", "takes"),
    [
        ("add_fillet", "modeling", True),
        ("add_line", "sketching", True),
        ("export_step", "export", True),
        ("save_file", "file_management", True),
        ("execute_workflow", "automation", True),
        ("open_model", "modeling", False),
        ("create_part", "modeling", False),
        ("activate_document", "file_management", False),
        ("convert_file_format", "file_management", False),
        ("batch_process_files", "automation", False),
        ("generate_vba_extrusion", "vba_generation", False),
        ("discover_solidworks_docs", "docs_discovery", False),
    ],
)
def test_document_tools_take_it_and_the_others_do_not(
    tool: str, family: str, takes: bool
) -> None:
    assert takes_document(tool, family) is takes
