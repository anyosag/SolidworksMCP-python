"""Automation tools for SolidWorks MCP Server.

Use these when the workflow is already defined and you need repeatable execution.
Recommended order: generate_vba_code for complex steps, record or stop a macro when a
manual flow should be captured, batch_process_files for many files, manage_design_table
for configuration-driven variants, execute_workflow for scripted pipelines,
create_template for reusable standards, and optimize_performance for tuning.
"""

import json
import time
from typing import Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ValidationError as FastMCPValidationError
from pydantic import BaseModel, Field, ValidationError, field_validator

from ..adapters.base import SolidWorksAdapter
from .error_classifier import INVALID_INPUT, Classification, ErrorClassifier
from .input_compat import CompatInput
from .tool_boundary import (
    InvalidInputError,
    ToolOperationError,
    UnsupportedOperationError,
    describe_validation_error,
    error_payload,
    normalize_input,
    require_capability,
    require_success,
    with_tool_boundary,
)

_STEP_CLASSIFIER = ErrorClassifier()

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


#: Most steps one ``execute_workflow`` call runs, so one call can't hold the
#: server (and SolidWorks) for minutes.
MAX_WORKFLOW_STEPS = 25


class WorkflowStep(BaseModel):
    """One tool call inside ``execute_workflow``.

    Attributes:
        arguments (dict[str, Any]): The tool's arguments.
        tool (str): The tool name.
    """

    tool: str = Field(description="Tool to call, e.g. `create_sketch`")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The tool's arguments. For a tool that takes `input_data`, its "
            "fields may be given directly; they are wrapped in `input_data`."
        ),
    )


class WorkflowInput(CompatInput):
    """Input schema for workflow automation.

    Attributes:
        error_handling (str): The error handling value.
        parallel_execution (bool): The parallel execution value.
        steps (list[WorkflowStep]): The steps value.
        workflow_name (str): The workflow name value.
    """

    workflow_name: str = Field(
        default="workflow", description="Name for the run, echoed in the reply"
    )
    steps: list[WorkflowStep] = Field(
        min_length=1,
        max_length=MAX_WORKFLOW_STEPS,
        description=f"The tool calls to make, in order (at most {MAX_WORKFLOW_STEPS})",
    )
    parallel_execution: bool = Field(
        default=False,
        description="Must stay false: SolidWorks runs one call at a time",
    )
    error_handling: Literal["stop", "continue"] = Field(
        default="stop",
        description=(
            "`stop` (default) ends the run at the first failed step; "
            "`continue` runs every step and reports each one's outcome"
        ),
    )

    @field_validator("error_handling", mode="before")
    @classmethod
    def _skip_means_continue(cls, value: Any) -> Any:
        """Accept the old spelling ``skip`` for ``continue``."""
        return "continue" if value == "skip" else value


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


_STEP_INPUT_HINT = (
    "Fix the step's arguments to match that tool's input schema, then run the "
    "workflow again from that step."
)


def _step_arguments(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """The arguments to call ``tool`` with, wrapping bare fields in ``input_data``.

    Most tools take a single ``input_data`` object. A step may give its fields
    directly (``{"depth": 10}``); they are wrapped so the call matches the
    tool's schema. Arguments that already name ``input_data``, or a tool with
    other parameters, are passed as they are.
    """
    properties = (getattr(tool, "parameters", None) or {}).get("properties") or {}
    if set(properties) == {"input_data"} and "input_data" not in arguments:
        return {"input_data": arguments}
    return arguments


def _tool_result_payload(result: Any) -> dict[str, Any]:
    """A tool call's reply as the dict the tool returned."""
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    text = "".join(
        str(getattr(block, "text", "")) for block in getattr(result, "content", ())
    )
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"status": "success", "result": text}
    return (
        parsed if isinstance(parsed, dict) else {"status": "success", "result": parsed}
    )


async def _run_workflow_step(
    mcp: Any, number: int, step: WorkflowStep, tool: Any
) -> dict[str, Any]:
    """Run one step through FastMCP's own ``call_tool``, as a separate call would.

    A step's tool reports its own failures as error payloads, inside its own
    error boundary. What can still raise is FastMCP rejecting the arguments
    before the tool runs; that becomes this step's error payload, so the
    workflow can say which step it was.

    Returns:
        dict[str, Any]: ``step``, ``tool``, ``status`` and the tool's ``result``.
    """
    started = time.perf_counter()
    try:
        reply = await mcp.call_tool(step.tool, _step_arguments(tool, step.arguments))
    except (ValidationError, FastMCPValidationError) as exc:
        # FastMCP raises its own ValidationError for bad arguments, with
        # pydantic's error as the cause.
        cause = exc if isinstance(exc, ValidationError) else exc.__cause__
        detail = (
            describe_validation_error(cause)
            if isinstance(cause, ValidationError)
            else str(exc)
        )
        result = error_payload(
            f"Invalid input: {detail}",
            Classification(INVALID_INPUT, _STEP_INPUT_HINT),
            time.perf_counter() - started,
        )
    except Exception as exc:
        message = f"{step.tool} failed: {exc}"
        result = error_payload(
            message,
            _STEP_CLASSIFIER.classify(message, exc),
            time.perf_counter() - started,
        )
    else:
        result = _tool_result_payload(reply)
    return {
        "step": number,
        "tool": step.tool,
        "status": result.get("status", "success"),
        "result": result,
    }


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
    mcp = with_tool_boundary(mcp)
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

    @mcp.tool()
    async def execute_workflow(input_data: WorkflowInput) -> dict[str, Any]:
        """Run several tool calls in one request, in order, and return every step's result.

        Use it to do a common job in one call instead of one per step, e.g.
        `create_sketch`, `add_rectangle`, `exit_sketch` and `create_extrusion`. Each
        step is `{tool, arguments}`; for a tool that takes `input_data`, give its
        fields directly. Steps run one at a time exactly as separate calls would, with
        the same checks and the same pauses SolidWorks needs. Every tool name is checked
        before anything runs. With `error_handling: "stop"` (the default) the run ends
        at the first failed step, and the error's `data.steps` shows what ran. Check
        each feature's `measured_change` before building on it. Changes: whatever its
        steps change. Returns: `steps` (each `step`, `tool`, `status` and the tool's
        own `result`), `completed`, and `failed` (step numbers).

        Args:
            input_data: The run. `steps` (1 to 25 `{tool, arguments}`) is required;
                `workflow_name` and `error_handling` (`stop` or `continue`) have
                defaults.

        Returns:
            dict[str, Any]: Every step's result.
        """
        input_data = normalize_input(input_data, WorkflowInput)
        if input_data.parallel_execution:
            raise InvalidInputError(
                "parallel_execution: steps run one at a time; SolidWorks takes one "
                "call at a time"
            )
        tools_by_step: list[Any] = []
        problems: list[str] = []
        for number, step in enumerate(input_data.steps, start=1):
            if step.tool == "execute_workflow":
                problems.append(f"steps[{number}]: execute_workflow can't be a step")
                tools_by_step.append(None)
                continue
            tool = await mcp.get_tool(step.tool)
            if tool is None:
                problems.append(f"steps[{number}]: no tool named `{step.tool}`")
            tools_by_step.append(tool)
        if problems:
            raise InvalidInputError("; ".join(problems) + ". Nothing was run.")

        started = time.perf_counter()
        results: list[dict[str, Any]] = []
        failed: list[int] = []
        for number, (step, tool) in enumerate(
            zip(input_data.steps, tools_by_step, strict=True), start=1
        ):
            record = await _run_workflow_step(mcp, number, step, tool)
            results.append(record)
            if record["status"] != "error":
                continue
            failed.append(number)
            if input_data.error_handling == "stop":
                step_result = record["result"]
                step_type = step_result.get("error_type")
                raise ToolOperationError(
                    f"Step {number} ({step.tool}) failed: "
                    f"{step_result.get('message', 'no message')}",
                    time.perf_counter() - started,
                    {
                        "workflow_name": input_data.workflow_name,
                        "completed": number - 1,
                        "failed_step": number,
                        "steps": results,
                    },
                    # Report the failed step's own error_type and hint.
                    Classification(step_type, str(step_result.get("hint") or ""))
                    if step_type
                    else None,
                )

        reply: dict[str, Any] = {
            "status": "success",
            "message": (
                f"Ran {len(results)} steps of '{input_data.workflow_name}'"
                + (f"; {len(failed)} failed" if failed else "")
            ),
            "workflow_name": input_data.workflow_name,
            "completed": len(results) - len(failed),
            "failed": failed,
            "steps": results,
            "execution_time": time.perf_counter() - started,
        }
        if failed:
            reply["warning"] = (
                f"{len(failed)} of {len(results)} steps failed (steps {failed}); "
                "read each one's result"
            )
        return reply

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
