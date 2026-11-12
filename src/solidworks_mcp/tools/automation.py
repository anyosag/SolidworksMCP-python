"""Automation tools for SolidWorks MCP Server.

Use these when the workflow is already defined and you need repeatable execution.
Recommended order: generate_vba_code for complex steps, record or stop a macro when a
manual flow should be captured, batch_process_files for many files, manage_design_table
for configuration-driven variants, execute_workflow for scripted pipelines,
create_template for reusable standards, and optimize_performance for tuning.
"""

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from fastmcp import Context, FastMCP
from pydantic import BaseModel, ConfigDict, Field

from ..adapters.base import SolidWorksAdapter
from ..adapters.solidworks import limits
from .error_classifier import INVALID_INPUT, OPERATION_FAILED, Classification
from .input_compat import CompatInput
from .support_levels import SUPPORT_LEVELS, SupportLevel
from .tool_boundary import (
    InvalidInputError,
    ToolOperationError,
    UnsupportedOperationError,
    error_payload,
    normalize_input,
    require_capability,
    require_success,
    takes_input,
    with_tool_boundary,
)

# Input schemas using Python 3.14 built-in types


class GenerateVBAInput(CompatInput):
    """Input schema for generating VBA code.

    Attributes:
        code_style (str): The code style value.
        include_error_handling (bool): The include error handling value.
        operation_description (str | None): The operation description value.
        operation_type (str | None): The operation type value.
        parameters (dict[str, Any]): The parameters value.
        target_document (str): The target document value.
    """

    operation_description: str | None = Field(
        default=None, description="Description of the operation to generate VBA for"
    )
    operation_type: str | None = Field(default=None, description="Operation type alias")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Operation parameters"
    )
    target_document: str = Field(
        default="Part", description="Target document type (Part, Assembly, Drawing)"
    )
    include_error_handling: bool = Field(
        default=True, description="Include error handling in generated code"
    )
    code_style: str = Field(
        default="professional",
        description="Code style (simple, professional, advanced)",
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the generate vbainput.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.operation_description is None:
            self.operation_description = self.operation_type or "SolidWorks Operation"


VBAGenerationInput = GenerateVBAInput


class RecordMacroInput(CompatInput):
    """Input schema for macro recording.

    Attributes:
        auto_start (bool): The auto start value.
        capture_keyboard (bool): The capture keyboard value.
        capture_mouse (bool): The capture mouse value.
        description (str): The description value.
        macro_name (str | None): The macro name value.
        output_file (str | None): The output file value.
        recording_mode (str | None): The recording mode value.
        recording_name (str | None): The recording name value.
    """

    macro_name: str | None = Field(
        default=None, description="Name for the recorded macro"
    )
    recording_name: str | None = Field(default=None, description="Recording name alias")
    output_file: str | None = Field(default=None, description="Output file alias")
    recording_mode: str | None = Field(default=None, description="Recording mode alias")
    capture_mouse: bool = Field(default=True, description="Capture mouse actions")
    capture_keyboard: bool = Field(default=True, description="Capture keyboard actions")
    description: str = Field(
        default="", description="Description of the macro functionality"
    )
    auto_start: bool = Field(default=True, description="Automatically start recording")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the record macro input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.macro_name is None:
            self.macro_name = self.recording_name or "Recorded Macro"


class BatchProcessInput(CompatInput):
    """Input schema for batch processing.

    Attributes:
        batch_operation (str | None): The batch operation value.
        file_pattern (str | None): The file pattern value.
        filter_patterns (list[str]): The filter patterns value.
        operation (str | None): The operation value.
        operation_type (str | None): The operation type value.
        parallel_processing (bool): The parallel processing value.
        recursive (bool): The recursive value.
        source_directory (str): The source directory value.
        target_format (str | None): The target format value.
    """

    source_directory: str = Field(description="Directory containing SolidWorks files")
    operation_type: str | None = Field(
        default=None,
        description="Type of operation (rebuild, save_as, export, update_properties)",
    )
    batch_operation: str | None = Field(
        default=None, description="Batch operation alias"
    )
    target_format: str | None = Field(
        default=None, description="Target format for export operations"
    )
    file_pattern: str | None = Field(default=None, description="File pattern alias")
    parallel_processing: bool = Field(
        default=False, description="Parallel processing alias"
    )
    operation: str | None = Field(default=None, description="Operation alias")
    recursive: bool = Field(
        default=False, description="Process subdirectories recursively"
    )
    filter_patterns: list[str] = Field(
        default=["*.sldprt", "*.sldasm"], description="File patterns to process"
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the batch process input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.operation_type is None:
            self.operation_type = self.batch_operation or self.operation or "export"


class DesignTableInput(CompatInput):
    """Input schema for design table operations.

    Attributes:
        auto_create_configurations (bool): The auto create configurations value.
        auto_update (bool): The auto update value.
        configurations (list[str]): The configurations value.
        create_configurations (bool): The create configurations value.
        excel_file (str | None): The excel file value.
        model_path (str | None): The model path value.
        operation (str | None): The operation value.
        parameters (list[str]): The parameters value.
        table_file (str | None): The table file value.
        table_type (str | None): The table type value.
    """

    table_type: str | None = Field(
        default=None, description="Type of design table (create, update, import)"
    )
    model_path: str | None = Field(default=None, description="Model path alias")
    table_file: str | None = Field(default=None, description="Design table file alias")
    operation: str | None = Field(default=None, description="Operation alias")
    auto_update: bool = Field(default=False, description="Auto update alias")
    create_configurations: bool = Field(
        default=False, description="Create configurations alias"
    )
    auto_create_configurations: bool = Field(
        default=False, description="Auto-create alias"
    )
    excel_file: str | None = Field(
        default=None, description="Excel file path for import/export"
    )
    parameters: list[str] = Field(
        default=[], description="Parameters to include in design table"
    )
    configurations: list[str] = Field(default=[], description="Configuration names")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the design table input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.table_type is None:
            self.table_type = self.operation or "create"
        if self.create_configurations:
            self.auto_create_configurations = True


#: The most steps one workflow runs.
MAX_WORKFLOW_STEPS = 100

#: Steps that change which names the feature tree holds, or where new
#: features go. Rollback deletes what wasn't in the tree at the start, so
#: after one of these it could delete a feature the user already had.
_UNTRACKED_STEPS = frozenset(
    {
        "rename_feature",
        "delete_feature",
        "undo",
        "set_rollback",
        "open_model",
        "close_model",
    }
)


class WorkflowStep(BaseModel):
    """One step of a workflow: a tool, its arguments and, optionally, its document.

    Attributes:
        tool (str): The tool's name, e.g. ``create_sketch``.
        arguments (dict[str, Any]): Its input: the tool's fields, or
            ``{"input_data": {...}}`` as over MCP.
        document (str | None): The open document to run it on.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(description="The tool to call, e.g. 'create_sketch'")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The tool's input: its fields, e.g. {'depth': 5}, or wrapped as "
            "{'input_data': {...}} as you would call the tool over MCP. A string "
            "value that is exactly '$steps.<index>.<path>' becomes the value at "
            "that dotted path in an earlier step's reply, e.g. "
            "'$steps.3.fillet.name' (a number picks a list item). A 'document' "
            "key here is the step's document."
        ),
    )
    document: str | None = Field(
        default=None,
        description=(
            "The open document to run this step on (title, file name or path), "
            "made the active document first. Only for tools that take "
            "`document`; leave it out to use the active document."
        ),
    )


class WorkflowInput(CompatInput):
    """Input schema for running tool steps in order.

    Attributes:
        workflow_name (str): A name for the run, used in its messages.
        steps (list[WorkflowStep]): The steps, run one after another.
        rollback_on_error (bool): Remove what the steps built when one fails.
        detail (str): How much of each step's reply to return.
    """

    workflow_name: str = Field(
        default="workflow", description="A name for the run, used in its messages"
    )
    steps: list[WorkflowStep] = Field(
        min_length=1,
        max_length=MAX_WORKFLOW_STEPS,
        description=(
            "The steps, run one after another: each a {tool, arguments} pair, "
            "with an optional document, e.g. {'tool': 'add_line', 'arguments': "
            "{'x1': 0, 'y1': 0, 'x2': 10, 'y2': 0}}"
        ),
    )
    rollback_on_error: bool = Field(
        default=False,
        description=(
            "When a step fails, delete the features and sketches the earlier "
            "steps added to the document that was active at the start"
        ),
    )
    detail: Literal["summary", "full"] = Field(
        default="summary",
        description=(
            "'summary': each step that worked gives its status, message and "
            "small facts (the scalar values of its reply and of its `data`, and "
            "`measured_change`); 'full': each step's whole reply, as `result`. "
            "A failed step always gives its whole reply."
        ),
    )


#: A step argument that starts with this is a reference to an earlier
#: step's reply, and must have the form ``$steps.<index>.<dotted.path>``.
_REFERENCE_PREFIX = "$steps."
_REFERENCE = re.compile(r"\$steps\.([0-9]+)\.([^.]+(?:\.[^.]+)*)")
_REFERENCE_HINT = (
    "Name a path that is in that step's reply; the message lists what is at "
    "the point it stopped. Run the workflow with detail 'full' to see every "
    "step's whole reply."
)
#: The reply values a summary keeps.
_SCALARS = (str, int, float, bool, type(None))


@dataclass(frozen=True)
class _Reference:
    """A ``$steps.<index>.<path>`` argument, checked to name an earlier step."""

    text: str
    step: int
    path: tuple[str, ...]


@dataclass(frozen=True)
class _PlannedStep:
    """A checked step: its tool function and what to call it with.

    Attributes:
        tool: The tool's name.
        fn: The registered tool function (inside its boundary).
        call: ``{"arguments": ..., "document": ...}``, with each reference
            parsed into a :class:`_Reference`.
    """

    tool: str
    fn: Any
    call: dict[str, Any]


def _map_leaves(value: Any, where: str, change: Callable[[str, Any], Any]) -> Any:
    """``value`` with ``change(where, leaf)`` applied to each leaf of its dicts and lists."""
    if isinstance(value, dict):
        return {
            key: _map_leaves(item, f"{where}.{key}", change)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _map_leaves(item, f"{where}.{number}", change)
            for number, item in enumerate(value)
        ]
    return change(where, value)


def _split_document(index: int, step: WorkflowStep) -> tuple[dict[str, Any], Any]:
    """A step's arguments without ``document``, unwrapped from ``input_data``.

    Args:
        index: The step's index, for messages.
        step: The step.

    Returns:
        tuple[dict[str, Any], Any]: The tool's arguments, and the step's
        document (None to use the active one).

    Raises:
        InvalidInputError: When the document isn't a string, or two
            different ones are given.
    """
    arguments = dict(step.arguments)
    given = [step.document, arguments.pop("document", None)]
    wrapped = arguments.get("input_data")
    if set(arguments) == {"input_data"} and isinstance(wrapped, dict | None):
        arguments = dict(wrapped or {})
        given.append(arguments.pop("document", None))
    for document in given:
        if not isinstance(document, str | None):
            raise InvalidInputError(
                f"steps.{index}: document must be the title, file name or path "
                f"of an open document, not {document!r}"
            )
    documents = list(dict.fromkeys(d for d in given if d is not None))
    if len(documents) > 1:
        raise InvalidInputError(
            f"steps.{index}: document is given more than once, as "
            + " and ".join(map(repr, documents))
            + "; give it once"
        )
    return arguments, documents[0] if documents else None


def _takes_document(fn: Any) -> bool:
    """Whether a tool function takes the boundary's keyword-only ``document``."""
    parameter = inspect.signature(fn).parameters.get("document")
    return parameter is not None and parameter.kind is inspect.Parameter.KEYWORD_ONLY


def _parse_references(value: Any, where: str, index: int) -> Any:
    """``value`` with each ``$steps.`` string parsed into a :class:`_Reference`.

    Raises:
        InvalidInputError: For one not of the form ``$steps.<index>.<path>``,
            or naming step ``index`` or a later one.
    """

    def parse(at: str, leaf: Any) -> Any:
        if not isinstance(leaf, str) or not leaf.startswith(_REFERENCE_PREFIX):
            return leaf
        match = _REFERENCE.fullmatch(leaf)
        if match is None:
            raise InvalidInputError(
                f"{at}: {leaf!r} is not a reference; write "
                "$steps.<index>.<path>, e.g. $steps.0.sketch.name"
            )
        step = int(match[1])
        if step >= index:
            raise InvalidInputError(
                f"{at}: {leaf!r} names step {step}, which doesn't run before "
                f"step {index}; a step can use only the replies of the steps "
                "before it"
            )
        return _Reference(leaf, step, tuple(match[2].split(".")))

    return _map_leaves(value, where, parse)


def _contents(value: Any) -> str:
    """What a reference found where its path stopped, for its message."""
    if isinstance(value, dict):
        return f"its keys are: {', '.join(map(str, value)) or 'none'}"
    if isinstance(value, list):
        return f"it is a list of {len(value)} items, numbered from 0"
    return f"it is {value!r}, not an object or a list"


def _look_up(
    reference: _Reference, replies: list[dict[str, Any]]
) -> tuple[Any, str | None]:
    """The value a reference names, or why there is none."""
    value: Any = replies[reference.step]
    for depth, part in enumerate(reference.path):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            at = ".".join(("$steps", str(reference.step), *reference.path[:depth]))
            return None, (
                f"{reference.text!r} names {part!r}, which {at} doesn't have; "
                + _contents(value)
            )
    return value, None


def _resolve_references(
    value: Any, where: str, replies: list[dict[str, Any]]
) -> tuple[Any, str | None]:
    """``value`` with each reference replaced by what it names.

    Returns:
        tuple[Any, str | None]: The resolved value, and the references that
        name nothing (None when all resolved).
    """
    problems: list[str] = []

    def resolve(at: str, leaf: Any) -> Any:
        if not isinstance(leaf, _Reference):
            return leaf
        found, problem = _look_up(leaf, replies)
        if problem is not None:
            problems.append(f"{at}: {problem}")
        return found

    resolved = _map_leaves(value, where, resolve)
    return resolved, "; ".join(problems) or None


async def _run_step(
    index: int, planned: _PlannedStep, replies: list[dict[str, Any]]
) -> dict[str, Any]:
    """Run one step, its references resolved against the earlier ``replies``.

    Returns:
        dict[str, Any]: The tool's reply, or an ``invalid_input`` error reply
        when a reference names nothing.
    """
    call, problem = _resolve_references(planned.call, f"steps.{index}", replies)
    document = call["document"]
    if problem is None and not isinstance(document, str | None):
        problem = (
            f"steps.{index}.document: {planned.call['document'].text!r} is "
            f"{document!r}, not the name of a document"
        )
    if problem is not None:
        return error_payload(
            f"Invalid input: {problem}",
            Classification(INVALID_INPUT, _REFERENCE_HINT),
            0.0,
        )
    keywords = {} if document is None else {"document": document}
    reply: dict[str, Any]
    if takes_input(planned.fn):
        reply = await planned.fn(call["arguments"], **keywords)
    else:
        reply = await planned.fn(**keywords)
    return reply


def _small_facts(mapping: dict[str, Any]) -> dict[str, Any]:
    """A reply's (or its ``data``'s) scalar values, and its ``measured_change``."""
    return {
        key: value
        for key, value in mapping.items()
        if isinstance(value, _SCALARS)
        or (key == "measured_change" and isinstance(value, dict))
    }


def _summary(entry: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    """A successful step's entry with its reply's small facts, but no warning."""
    facts = {
        key: value
        for key, value in _small_facts(reply).items()
        if key not in entry and key != "warning"
    }
    data = reply.get("data")
    small_data = _small_facts(data) if isinstance(data, dict) else {}
    return {**entry, **facts, **({"data": small_data} if small_data else {})}


def _warning_parts(tool: str, warning: Any) -> list[str]:
    """A step's warning, split into its own and its tool's support-level one.

    The boundary joins a tool's own warning, its support level's and a
    shared-document notice into one string; the level's repeats on every
    step of that tool, so it is listed once on its own.
    """
    if not isinstance(warning, str) or not warning:
        return []
    level = SUPPORT_LEVELS[tool].warning()
    if level is None or level not in warning:
        return [warning]
    before, _, after = warning.partition(level)
    return [part for part in (before.strip(), level, after.strip()) if part]


class TemplateInput(CompatInput):
    """Input schema for template operations.

    Attributes:
        base_file (str | None): The base file value.
        include_custom_properties (bool): The include custom properties value.
        include_features (list[str]): The include features value.
        include_materials (bool): The include materials value.
        metadata (dict[str, Any]): The metadata value.
        output_path (str | None): The output path value.
        source_model (str | None): The source model value.
        template_name (str): The template name value.
        template_type (str): The template type value.
    """

    template_type: str = Field(description="Type of template (part, assembly, drawing)")
    template_name: str = Field(description="Name for the template")
    base_file: str | None = Field(
        default=None, description="Base file to create template from"
    )
    source_model: str | None = Field(default=None, description="Source model alias")
    output_path: str | None = Field(default=None, description="Output path alias")
    include_custom_properties: bool = Field(
        default=False, description="Include custom properties alias"
    )
    include_materials: bool = Field(
        default=False, description="Include materials alias"
    )
    include_features: list[str] = Field(
        default_factory=list, description="Include features alias"
    )
    metadata: dict[str, Any] = Field(
        default={}, description="Template metadata and properties"
    )


async def register_automation_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: dict[str, Any]
) -> int:
    """Register automation tools with FastMCP.

    Registers comprehensive automation tools for SolidWorks workflow orchestration including
    VBA generation, macro recording, batch processing, and template management.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (dict[str, Any]): Configuration values for the operation.

    Returns:
        int: The computed numeric result.
    """
    mcp = with_tool_boundary(mcp, adapter)
    tool_count = 0

    @mcp.tool()
    async def generate_vba_code(input_data: GenerateVBAInput) -> dict[str, Any]:
        """Write a VBA macro skeleton for an operation you describe: the SolidWorks connection, the active document and optional error handling, with the operation itself left as a TODO.

        Use it as a starting point for a custom macro. For a working macro for a
        specific feature, use a `generate_vba_*` tool (extrusion, revolve, mates,
        drawing views, batch export). The macro comes back as text for the SolidWorks
        VBA editor; `execute_macro` runs only binary .swp files. Read-only. Nothing runs
        in SolidWorks. Returns: `vba_code` with `code`, `operation`, `target_document`,
        `style`, `lines_of_code` and `includes_error_handling`.

        Args:
            input_data: The macro to write. Nothing is required: give
                `operation_description` (it also names the Sub) and
                `target_document`; `include_error_handling` and `code_style` have
                defaults.

        Returns:
            dict[str, Any]: The macro text.
        """
        if hasattr(adapter, "generate_vba_code"):
            result = await adapter.generate_vba_code(input_data.model_dump())
            require_success(result, "Failed to generate VBA code")
            return {
                "status": "success",
                "message": f"Generated VBA code for: {input_data.operation_description}",
                "data": result.data,
                "execution_time": result.execution_time,
            }

        # Build a VBA code skeleton from the operation description. This
        # is real, usable output (a labelled template), not a stand-in
        # for a SolidWorks operation that was supposed to run.
        sample_vba = f"""
' Generated VBA code for: {input_data.operation_description}
' Target: {input_data.target_document}
' Generated by: SolidWorks MCP Server

Option Explicit

Sub {(input_data.operation_description or "").replace(" ", "_")}()
Dim swApp As SldWorks.SldWorks
Dim swModel As SldWorks.ModelDoc2

{("On Error GoTo ErrorHandler" if input_data.include_error_handling else "")}

' Connect to SolidWorks
Set swApp = Application.SldWorks
Set swModel = swApp.ActiveDoc

If swModel Is Nothing Then
    MsgBox "No active document found"
    Exit Sub
End If

' Main operation code would go here
' TODO: Implement specific operation

MsgBox "Operation completed successfully"
Exit Sub

{("ErrorHandler:" if input_data.include_error_handling else "")}
{('    MsgBox "Error: " & Err.Description' if input_data.include_error_handling else "")}
{("    Resume Next" if input_data.include_error_handling else "")}

End Sub
"""

        return {
            "status": "success",
            "message": f"Generated VBA code for: {input_data.operation_description}",
            "vba_code": {
                "code": sample_vba.strip(),
                "operation": input_data.operation_description,
                "target_document": input_data.target_document,
                "style": input_data.code_style,
                "lines_of_code": len(sample_vba.strip().split("\n")),
                "includes_error_handling": input_data.include_error_handling,
            },
        }

    @mcp.tool(name="automation_start_macro_recording")
    async def start_macro_recording(input_data: RecordMacroInput) -> dict[str, Any]:
        """Start SolidWorks' macro recorder (the automation family's copy of `start_macro_recording`).

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. Recording is
        done in SolidWorks today (Tools > Macro > Record). Changes: once available,
        starts a recording session. Returns: once available, the session details under
        `data`.

        Args:
            input_data: The recording. Nothing is required: `macro_name`,
                `output_file`, `recording_mode` and the capture switches have
                defaults.

        Returns:
            dict[str, Any]: The session, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "start_macro_recording",
            "Active adapter does not support start_macro_recording; "
            f"no recording of {input_data.macro_name} was started.",
        )
        result = await adapter.start_macro_recording(input_data.model_dump())
        require_success(result, "Failed to start macro recording")
        return {
            "status": "success",
            "message": f"Started recording macro: {input_data.macro_name}",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    @mcp.tool(name="automation_stop_macro_recording")
    async def stop_macro_recording(input_data: dict[str, Any]) -> dict[str, Any]:
        """Stop a macro recording and save it (the automation family's copy of `stop_macro_recording`).

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. Recording is
        done in SolidWorks today (Tools > Macro > Stop). Changes: once available, ends
        the session and writes the macro file. Returns: once available, the saved
        macro's details.

        Args:
            input_data: A mapping; nothing in it is used yet.

        Returns:
            dict[str, Any]: A `not_supported` error.
        """
        raise UnsupportedOperationError(
            "No adapter capability exists for stopping a macro "
            "recording; this tool never started a real recording "
            "session, so there is nothing to stop or save."
        )

    @mcp.tool()
    async def batch_process_files(input_data: BatchProcessInput) -> dict[str, Any]:
        """Run one operation (rebuild, save as, export or property update) on every matching file in a folder.

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. To export
        several files today, open each with `open_model` and use `export_step`.
        Changes: once available, opens, changes and saves each file. Returns: once available, a per-file result under `data`.

        Args:
            input_data: The batch. `source_directory` is required; `operation_type`,
                `file_pattern`, `target_format` and `recursive` have defaults.

        Returns:
            dict[str, Any]: The results, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "batch_process_files",
            "Active adapter does not support batch_process_files; no "
            f"files in {input_data.source_directory} were processed.",
        )
        result = await adapter.batch_process_files(input_data.model_dump())
        require_success(result, "Batch processing failed")
        return {
            "status": "success",
            "message": f"Batch {input_data.operation_type} completed",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def manage_design_table(input_data: DesignTableInput) -> dict[str, Any]:
        """Create, read or update a design table (an Excel sheet that drives a model's configurations).

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. To list a
        model's configurations today, use `list_configurations`. Changes: once
        available, inserts or edits the design table and its configurations. Returns:
        once available, the table's state under `data`.

        Args:
            input_data: The design table. Nothing is required: give `model_path`,
                `operation` and `excel_file`; `parameters`, `configurations` and the
                auto-update switches have defaults.

        Returns:
            dict[str, Any]: The result, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "manage_design_table",
            "Active adapter does not support manage_design_table; no "
            f"{input_data.table_type} operation was performed.",
        )
        result = await adapter.manage_design_table(input_data.model_dump())
        require_success(result, "Design table management failed")
        return {
            "status": "success",
            "message": f"Design table {input_data.table_type} completed",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    async def _feature_names() -> list[str] | None:
        """The active document's feature tree, or None when it can't be read."""
        listed = await adapter.list_features(include_suppressed=True)
        if not listed.is_success:
            return None
        return [str(f.get("name")) for f in listed.data or [] if f.get("name")]

    async def _document() -> str | None:
        """The active document's title or path, or None without one."""
        info = await adapter.get_model_info()
        if not info.is_success or not isinstance(info.data, dict):
            return None
        return str(info.data.get("title") or info.data.get("path") or "") or None

    async def _roll_back(
        checkpoint: list[str] | None, document: str | None
    ) -> dict[str, Any]:
        """Delete what the steps added since ``checkpoint``, newest first."""
        if document is None:
            return {
                "done": False,
                "reason": "no document was open at the start, so there is nothing to roll back to",
            }
        if checkpoint is None:
            return {
                "done": False,
                "reason": "the feature tree couldn't be read at the start, so nothing was deleted",
            }
        if await _document() != document:
            return {
                "done": False,
                "reason": (
                    f"the active document is no longer {document!r}; the steps "
                    "opened or created another, so nothing was deleted"
                ),
            }
        await adapter.exit_sketch()  # a sketch left open would block deletes
        deleted: list[str] = []
        for _ in range(MAX_WORKFLOW_STEPS):
            names = await _feature_names() or []
            added = [n for n in names if n not in checkpoint]
            if not added:
                break
            gone = await adapter.delete_feature(added[-1], True)
            if not gone.is_success:
                return {
                    "done": False,
                    "deleted": deleted,
                    "left": added,
                    "reason": f"SolidWorks would not delete {added[-1]}: {gone.error}",
                }
            removed = (gone.data or {}).get("removed_features") or [added[-1]]
            deleted += [n for n in removed if n not in deleted]
        return {"done": True, "deleted": deleted}

    @mcp.tool()
    async def execute_workflow(
        input_data: WorkflowInput, ctx: Context | None = None
    ) -> dict[str, Any]:
        """Run a list of tool steps in order in one call, stopping at the first that fails.

        Use it for a sequence you already know, e.g. sketch, draw, exit, extrude: give
        `steps`, each a `tool` and the `arguments` you would pass it (its fields, or
        `{"input_data": {...}}`), and `document` to run it on another open document.
        An argument `"$steps.<i>.<path>"` takes that value from step i's reply, e.g.
        `"old_name": "$steps.3.fillet.name"`. Steps run one at a time, with progress
        after each. With `rollback_on_error`, a failing step makes it delete the
        features and sketches the earlier steps added (other changes, such as
        dimensions or saved files, stay). Needs: whatever the steps need. Changes:
        whatever the steps change. Returns: `steps` (each one's `status`, `message`
        and small facts such as `measured_change`; with `detail: "full"`, its whole
        `result`), `completed` and `warnings` (each once, with its steps); on a
        failure, an error whose `data` has those (the failed step in full),
        `failed_step` and `rolled_back`.

        Args:
            input_data: The workflow. `steps` (1 to 100) is required;
                `workflow_name`, `rollback_on_error` (off) and `detail`
                ("summary") have defaults.

        Returns:
            dict[str, Any]: Each step's result.
        """
        input_data = normalize_input(input_data, WorkflowInput)
        registry = {tool.name: tool for tool in await mcp.list_tools()}
        plan: list[_PlannedStep] = []
        for index, step in enumerate(input_data.steps):
            support = SUPPORT_LEVELS.get(step.tool)
            if step.tool == "execute_workflow":
                raise InvalidInputError(
                    f"steps.{index}: a workflow can't run execute_workflow"
                )
            if step.tool not in registry or support is None:
                raise InvalidInputError(f"steps.{index}: no tool named {step.tool!r}")
            if support.level is SupportLevel.PLANNED:
                raise InvalidInputError(
                    f"steps.{index}: {step.tool} is not available yet"
                )
            fn = registry[step.tool].fn
            arguments, step_document = _split_document(index, step)
            if arguments and not takes_input(fn):
                raise InvalidInputError(
                    f"steps.{index}: {step.tool} takes no arguments"
                )
            if step_document is not None and not _takes_document(fn):
                raise InvalidInputError(
                    f"steps.{index}: {step.tool} doesn't take document (it "
                    "doesn't act on an open document, or picks its own); leave "
                    "document out, or add an activate_document step before it"
                )
            if input_data.rollback_on_error and step.tool in _UNTRACKED_STEPS:
                raise InvalidInputError(
                    f"steps.{index}: rollback_on_error can't be used with "
                    f"{step.tool}, which changes the feature tree in a way a "
                    "rollback can't follow; run it without rollback_on_error"
                )
            call = _parse_references(
                {"arguments": arguments, "document": step_document},
                f"steps.{index}",
                index,
            )
            plan.append(_PlannedStep(step.tool, fn, call))

        name = input_data.workflow_name
        document = await _document() if input_data.rollback_on_error else None
        checkpoint = (
            await _feature_names()
            if input_data.rollback_on_error and document
            else None
        )
        done: list[dict[str, Any]] = []
        # Every step's whole reply, for references, whatever `detail` says.
        replies: list[dict[str, Any]] = []
        seen_warnings: dict[str, list[int]] = {}

        def listed_warnings() -> list[dict[str, Any]]:
            return [
                {"warning": text, "steps": steps}
                for text, steps in seen_warnings.items()
            ]

        total = len(plan)
        for index, planned in enumerate(plan):
            if limits.client_gone():
                raise ToolOperationError(
                    f"Workflow '{name}' stopped before step {index + 1} of {total} "
                    f"({planned.tool}): the MCP client disconnected, so nothing "
                    "would read the result.",
                    data={
                        "steps": done,
                        "completed": index,
                        "failed_step": None,
                        "warnings": listed_warnings(),
                    },
                )
            if ctx is not None:
                # Progress resets an MCP client's idle timeout, and the await
                # lets a cancel from the client land between steps.
                await ctx.report_progress(
                    progress=index,
                    total=total,
                    message=f"Step {index + 1} of {total}: {planned.tool}",
                )
            reply = await _run_step(index, planned, replies)
            replies.append(reply)
            for part in dict.fromkeys(
                _warning_parts(planned.tool, reply.get("warning"))
            ):
                seen_warnings.setdefault(part, []).append(index)
            entry: dict[str, Any] = {
                "index": index,
                "tool": planned.tool,
                "status": reply.get("status"),
                "message": reply.get("message"),
            }
            failed = reply.get("status") == "error"
            if failed or input_data.detail == "full":
                entry["result"] = reply
            else:
                entry = _summary(entry, reply)
            done.append(entry)
            if failed:
                data: dict[str, Any] = {
                    "steps": done,
                    "completed": index,
                    "failed_step": index,
                    "rolled_back": (
                        await _roll_back(checkpoint, document)
                        if input_data.rollback_on_error
                        else None
                    ),
                    "warnings": listed_warnings(),
                }
                raise ToolOperationError(
                    f"Workflow '{name}' stopped at step {index + 1} of "
                    f"{total} ({planned.tool}): {reply.get('message')}",
                    data=data,
                    # The failed step's own error_type and hint, rather than a
                    # new classification of this workflow message.
                    classification=Classification(
                        str(reply.get("error_type") or OPERATION_FAILED),
                        str(reply.get("hint") or ""),
                    ),
                )
        if ctx is not None:
            await ctx.report_progress(
                progress=total, total=total, message=f"All {total} steps done"
            )
        return {
            "status": "success",
            "message": f"Workflow '{name}' ran all {len(done)} steps",
            "steps": done,
            "completed": len(done),
            "warnings": listed_warnings(),
        }

    @mcp.tool()
    async def create_template(input_data: TemplateInput) -> dict[str, Any]:
        """Create a part, assembly or drawing template file (.prtdot, .asmdot, .drwdot) with standard settings.

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. To capture an
        existing model's settings, `extract_template` is also not available yet.
        Changes: once available, writes the template file. Returns: once available, the
        template's path and settings under `data`.

        Args:
            input_data: The template. `template_type` and `template_name` are
                required; `source_model`, `output_path` and the include switches have
                defaults.

        Returns:
            dict[str, Any]: The template, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "create_template",
            "Active adapter does not support create_template; no "
            f"{input_data.template_type} template "
            f"'{input_data.template_name}' was created.",
        )
        result = await adapter.create_template(input_data.model_dump())
        require_success(result, "Template creation failed")
        return {
            "status": "success",
            "message": f"Created {input_data.template_type} template: {input_data.template_name}",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def optimize_performance(input_data: dict[str, Any]) -> dict[str, Any]:
        """Review SolidWorks' performance settings and apply faster ones.

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. Changes: once
        available, SolidWorks system options. Returns: once available, the settings
        changed under `data`.

        Args:
            input_data: A mapping of optimisation options; none is required.

        Returns:
            dict[str, Any]: The changes, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "optimize_performance",
            "Active adapter does not support optimize_performance; "
            "no settings were analyzed or changed.",
        )
        result = await adapter.optimize_performance(input_data)
        require_success(result, "Performance optimization failed")
        return {
            "status": "success",
            "message": "Performance optimization completed",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    tool_count = 8  # Number of tools registered
    return tool_count


class PerformanceOptimizationInput(CompatInput):
    """Input schema for performance optimization.

    Attributes:
        optimization_type (str): The optimization type value.
        parameters (dict[str, Any]): The parameters value.
        target_metric (str): The target metric value.
    """

    optimization_type: str = Field(description="Type of optimization to perform")
    target_metric: str = Field(default="speed", description="Target performance metric")
    parameters: dict[str, Any] = Field(
        default={}, description="Optimization parameters"
    )
