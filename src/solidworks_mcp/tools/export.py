"""Export tools for SolidWorks MCP Server.

Provides tools for exporting SolidWorks models to various formats including STEP, IGES,
STL, PDF, DWG, and image formats.
"""

from typing import Any, Literal, TypeVar

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from ..adapters.base import SolidWorksAdapter
from ..utils import stl_mesh
from .input_compat import CompatInput
from .modeling import DisplayType
from .tool_boundary import (
    UnsupportedOperationError,
    normalize_input,
    require_capability,
    require_success,
    with_tool_boundary,
)

TInput = TypeVar("TInput", bound=BaseModel)


# Input schemas using Python 3.14 built-in types


class ExportFileInput(CompatInput):
    """Input schema for exporting files.

    Attributes:
        file_path (str): The file path value.
        format_type (str): The format type value.
    """

    file_path: str = Field(description="Full path for the exported file")
    format_type: str | None = Field(
        default=None,
        description=(
            "Not needed: the file extension sets the format; defaults to the "
            "tool's own format"
        ),
    )


class ExportStlInput(ExportFileInput):
    """Input schema for STL exports, with optional mesh settings for this file.

    Attributes:
        resolution (str | None): coarse, fine or custom.
        deviation_mm (float | None): Largest gap to the true surface, mm.
        angle_deg (float | None): Largest angle between facets, degrees.
        units (str | None): The units written in the file.
        binary (bool | None): Binary (True) or ASCII (False) STL.
    """

    resolution: Literal["coarse", "fine", "custom"] | None = Field(
        default=None,
        description=(
            "Mesh resolution for this file: coarse, fine, or custom with "
            "deviation_mm and angle_deg. Left out: the user's STL setting"
        ),
    )
    deviation_mm: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description=(
            "Largest distance between the mesh and the true surface, in mm. "
            "Smaller is finer; it makes the resolution custom"
        ),
    )
    angle_deg: float | None = Field(
        default=None,
        gt=0,
        le=90,
        description=(
            "Largest angle between neighbouring facets, in degrees. Smaller "
            "is finer on small curved details; it makes the resolution custom"
        ),
    )
    units: Literal["mm", "cm", "m", "in", "ft"] | None = Field(
        default=None,
        description="Units written in the file. Left out: the user's STL setting",
    )
    binary: bool | None = Field(
        default=None,
        description="Binary STL (true) or ASCII (false). Left out: the user's setting",
    )

    def model_post_init(self, __context: Any) -> None:
        """Refuse a deviation or angle with coarse or fine resolution."""
        tolerances = [
            name
            for name in ("deviation_mm", "angle_deg")
            if getattr(self, name) is not None
        ]
        if tolerances and self.resolution in ("coarse", "fine"):
            raise ValueError(
                f"{' and '.join(tolerances)} need resolution 'custom', not "
                f"{self.resolution!r}"
            )
        if self.resolution == "custom" and not tolerances:
            raise ValueError(
                "resolution 'custom' needs deviation_mm or angle_deg: SolidWorks "
                "takes custom only with its own tolerances"
            )

    def mesh_settings(self) -> dict[str, Any]:
        """The mesh settings given, by name (empty: keep the user's)."""
        names = ("resolution", "deviation_mm", "angle_deg", "units", "binary")
        return {n: getattr(self, n) for n in names if getattr(self, n) is not None}


class ImageSection(BaseModel):
    """A plane to cut the model on for one picture.

    Attributes:
        plane (str): The plane's name.
        offset_mm (float): How far along its normal the cut is, mm.
        reverse (bool): Keep the other side.
    """

    model_config = ConfigDict(extra="forbid")

    plane: str = Field(
        min_length=1,
        description=(
            "The plane to cut on, by name: Front Plane, Top Plane, Right Plane "
            "or a reference plane such as Plane1"
        ),
    )
    offset_mm: float = Field(
        default=0.0,
        description="Move the cut this far along the plane's normal, in mm",
    )
    reverse: bool = Field(
        default=False,
        description="Keep the other side of the plane (false keeps the default side)",
    )

    def model_post_init(self, __context: Any) -> None:
        """Refuse a blank plane name."""
        self.plane = self.plane.strip()
        if not self.plane:
            raise ValueError("section.plane needs a plane's name")


class ExportImageInput(CompatInput):
    """Input schema for exporting images.

    Attributes:
        file_path (str | None): The file path value.
        format (str | None): The format value.
        format_type (str): The format type value.
        height (int): The height value.
        image_format (str | None): The image format value.
        model_path (str | None): The model path value.
        orientation (str | None): The orientation value.
        output_path (str | None): The output path value.
        resolution (str | None): The resolution value.
        view_orientation (str): The view orientation value.
        width (int): The width value.
        zoom_to_fit (bool | None): Whether to zoom so the model fills the view.
        zoom_box_mm (list[float] | None): Two corners of a box to zoom to, mm.
        hide (list[str] | None): Display types hidden for the picture only.
        section (ImageSection | None): A plane to cut the model on, for the
            picture only.
    """

    file_path: str | None = Field(
        default=None, description="Full path for the exported image"
    )
    output_path: str | None = Field(default=None, description="Alternative output path")
    model_path: str | None = Field(default=None, description="Path to the model file")
    format_type: str = Field(
        default="jpg", description="Image format (jpg, png, bmp, tiff)"
    )
    format: str | None = Field(default=None, description="Alternative format field")
    image_format: str | None = Field(default=None, description="Image format alias")
    width: int = Field(default=1920, description="Image width in pixels")
    height: int = Field(default=1080, description="Image height in pixels")
    resolution: str | None = Field(default=None, description="Resolution alias")
    view_orientation: str = Field(
        default="isometric",
        description=(
            "View to turn the model to (front, back, left, right, top, bottom, "
            "isometric, dimetric, trimetric), or current to keep the view on "
            "screen exactly as it is, zoom included"
        ),
    )
    orientation: str | None = Field(
        default=None, description="Alias of view_orientation"
    )
    zoom_to_fit: bool | None = Field(
        default=None,
        description=(
            "Zoom so the whole model fills the picture. Left out: yes for a "
            "named view, no for current, so a close-up stays a close-up"
        ),
    )
    zoom_box_mm: list[float] | None = Field(
        default=None,
        min_length=6,
        max_length=6,
        description=(
            "Zoom to this part of the model: two opposite corners of a box in "
            "model coordinates, mm, as [x1, y1, z1, x2, y2, z2]"
        ),
    )
    hide: list[DisplayType] | None = Field(
        default=None,
        description=(
            'Hide these for the picture only, e.g. ["planes", "sketches"]; '
            "they are shown again afterwards as they were"
        ),
    )
    section: ImageSection | None = Field(
        default=None,
        description=(
            "Cut the model on a plane for this picture only, with the cut faces "
            'capped, e.g. {"plane": "Front Plane", "offset_mm": 0}, to show a '
            "snap inside its socket; the cut is taken off afterwards"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the export image input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.file_path is None:
            self.file_path = self.output_path
        if (
            self.orientation is not None
            and "view_orientation" not in self.model_fields_set
        ):
            self.view_orientation = self.orientation
        if self.image_format is not None:
            self.format_type = self.image_format.lower()
        if self.resolution and "x" in self.resolution.lower():
            width, height = self.resolution.lower().split("x", 1)
            self.width = int(width)
            self.height = int(height)
        if self.zoom_box_mm is not None:
            if self.zoom_to_fit:
                raise ValueError("zoom_box_mm and zoom_to_fit: true can't both apply")
            first, second = self.zoom_box_mm[:3], self.zoom_box_mm[3:]
            if first == second:
                raise ValueError("zoom_box_mm needs two different corners")


class BatchExportInput(CompatInput):
    """Input schema for batch export operations.

    Attributes:
        export_format (str | None): The export format value.
        file_pattern (str | None): The file pattern value.
        file_patterns (list[str]): The file patterns value.
        format_type (str | None): The format type value.
        include_subdirectories (bool): The include subdirectories value.
        output_directory (str): The output directory value.
        recursive (bool): The recursive value.
        source_directory (str): The source directory value.
    """

    source_directory: str = Field(description="Directory containing SolidWorks files")
    output_directory: str = Field(description="Directory for exported files")
    format_type: str | None = Field(default=None, description="Target export format")
    export_format: str | None = Field(
        default=None, description="Alternative export format"
    )
    file_pattern: str | None = Field(default=None, description="File pattern alias")
    recursive: bool = Field(
        default=False, description="Search subdirectories recursively"
    )
    include_subdirectories: bool = Field(
        default=False, description="Include subdirectories in search"
    )
    file_patterns: list[str] = Field(
        default=["*.sldprt", "*.sldasm", "*.slddrw"],
        description="File patterns to include",
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the batch export input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        if self.format_type is None:
            self.format_type = self.export_format
        if self.file_pattern:
            self.file_patterns = [self.file_pattern]
        if self.include_subdirectories:
            self.recursive = True


def _file_input(input_data: Any, format_type: str) -> Any:
    """Fill ``format_type`` with the tool's own format when it was left out.

    The file extension decides the format; the adapter is still told which
    format the tool exports.
    """
    if not isinstance(input_data, ExportFileInput) or input_data.format_type:
        return input_data
    return input_data.model_copy(update={"format_type": format_type})


async def _stl_mesh_check(
    adapter: Any, file_path: str, units: str | None, document_type: Any
) -> dict[str, Any]:
    """Read back the STL just written and, for a part, compare its volume.

    The part's volume comes from ``get_model_geometry_summary``, which
    doesn't rebuild or touch the selection. An assembly's would come from a
    mass property that depends on the selection, so it is left out.

    Args:
        adapter: The active adapter.
        file_path: The ``.stl`` file written.
        units: The unit the file was written in, ``None`` when not known.
        document_type: ``part``, ``assembly`` or ``None``, as the export said.

    Returns:
        dict[str, Any]: :func:`stl_mesh.check_stl`'s check, with
        ``cad_volume_mm3`` and ``volume_ratio`` (mesh / model; ``None`` when
        the model's volume isn't known); only ``error`` when the file
        couldn't be read.
    """
    check = stl_mesh.check_stl(file_path, units)
    if "error" in check:
        return check
    check["cad_volume_mm3"] = None
    check["volume_ratio"] = None
    if document_type != "part" or not hasattr(adapter, "get_model_geometry_summary"):
        return check
    summary = await adapter.get_model_geometry_summary()
    volume = (summary.data or {}).get("volume_mm3") if summary.is_success else None
    if isinstance(volume, int | float) and volume > 0:
        check["cad_volume_mm3"] = round(float(volume), 3)
        check["volume_ratio"] = round(check["volume_mm3"] / float(volume), 4)
    return check


async def register_export_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: dict[str, Any]
) -> int:
    """Register export tools with FastMCP.

    Registers comprehensive file export tools for SolidWorks automation supporting multiple
    industry-standard formats including neutral CAD formats, manufacturing formats, and
    documentation outputs.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (dict[str, Any]): Configuration values for the operation.

    Returns:
        int: The computed numeric result.

    Example:
                        ```python
                        from solidworks_mcp.tools.export import register_export_tools

                        tool_count = await register_export_tools(mcp, adapter, config)
                        print(f"Registered {tool_count} export tools")
                        ```
    """
    mcp = with_tool_boundary(mcp, adapter)
    tool_count = 0

    @mcp.tool()
    async def export_step(input_data: ExportFileInput) -> dict[str, Any]:
        """Export the active document to STEP, like File > Save As with the STEP type.

        Use it to hand a model to another CAD system; it is the most widely read
        exchange format. SolidWorks picks the format from the file's extension, so end
        `file_path` in .step or .stp. Needs: an open, active part or assembly. Changes:
        writes the file, creating its folder and replacing a file already there; the
        open document is unchanged. Returns: `export` with `file_path` and `format`.

        Args:
            input_data: The export. `file_path` (ending in .step or .stp) is required;
                `format_type` is not needed: the file extension decides the
                format.

        Returns:
            dict[str, Any]: The file written.
        """
        input_data = _file_input(input_data, "step")
        file_path = input_data.file_path

        if hasattr(adapter, "export_step"):
            result = await adapter.export_step(input_data.model_dump())
        else:
            result = await adapter.export_file(file_path, "step")

        require_success(result, context="Failed to export STEP")
        if hasattr(adapter, "export_step"):
            return {
                "status": "success",
                "message": f"Exported to STEP format: {file_path}",
                "data": result.data,
                "execution_time": result.execution_time,
            }
        return {
            "status": "success",
            "message": f"Exported to STEP format: {file_path}",
            "export": {
                "file_path": file_path,
                "format": "STEP",
                "size_estimate": "Unknown",  # Would get actual file size
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def export_iges(input_data: ExportFileInput) -> dict[str, Any]:
        """Export the active document to IGES, like File > Save As with the IGES type.

        Use it only when the receiver can't read STEP; prefer `export_step`. SolidWorks
        picks the format from the file's extension, so end `file_path` in .igs or .iges.
        Needs: an open, active part or assembly. Changes: writes the file, creating its
        folder and replacing a file already there; the open document is unchanged.
        Returns: `export` with `file_path` and `format`.

        Args:
            input_data: The export. `file_path` (ending in .igs or .iges) is required;
                `format_type` is not needed: the file extension decides the
                format.

        Returns:
            dict[str, Any]: The file written.
        """
        input_data = _file_input(input_data, "iges")
        if hasattr(adapter, "export_iges"):
            result = await adapter.export_iges(input_data.model_dump())
        else:
            result = await adapter.export_file(input_data.file_path, "iges")

        require_success(result, context="Failed to export IGES")
        if hasattr(adapter, "export_iges"):
            return {
                "status": "success",
                "message": f"Exported to IGES format: {input_data.file_path}",
                "data": result.data,
                "execution_time": result.execution_time,
            }
        return {
            "status": "success",
            "message": f"Exported to IGES format: {input_data.file_path}",
            "export": {
                "file_path": input_data.file_path,
                "format": "IGES",
                "size_estimate": "Unknown",
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def export_stl(input_data: ExportStlInput) -> dict[str, Any]:
        """Export the active document to STL, like File > Save As with the STL type.

        Use it for 3D printing. An assembly is exported whole into the one file,
        with lightweight components resolved first. SolidWorks picks the format
        from the file's extension, so end `file_path` in .stl. The mesh follows the
        user's STL options unless this call gives `resolution`, `deviation_mm`,
        `angle_deg`, `units` or `binary`; those apply to this file only, and the
        user's options are put back afterwards. Needs: an open, active part or
        assembly. Changes: writes the file, creating its folder and replacing a file
        already there; the open document is unchanged. Returns: `export` with
        `file_path`, `format`, `mesh_check` (the file read back: `triangles`,
        `closed`, `open_edges`, `non_manifold_edges`, `volume_mm3`, `size_mm`,
        `units`, and `cad_volume_mm3` and `volume_ratio` for a part; only `error`
        when it couldn't be read) and, when the call changed STL options (mesh
        settings, an assembly's one-file option), `mesh` (`applied`, `restored`).

        Args:
            input_data: The export. `file_path` (ending in .stl) is required;
                `format_type` is not needed: the file extension decides the
                format. The mesh settings are optional.

        Returns:
            dict[str, Any]: The file written.
        """
        input_data = _file_input(normalize_input(input_data, ExportStlInput), "stl")
        settings = input_data.mesh_settings()
        native = False  # an adapter with its own export_stl
        if settings:
            require_capability(
                adapter,
                "export_stl_with_settings",
                "The active adapter cannot set STL mesh options; nothing was "
                "exported. Export without them, or set them in SolidWorks.",
            )
            result = await adapter.export_stl_with_settings(
                input_data.file_path, settings
            )
        elif hasattr(adapter, "export_stl"):
            native = True
            result = await adapter.export_stl(input_data.model_dump())
        else:
            result = await adapter.export_file(input_data.file_path, "stl")
        require_success(result, context="Failed to export STL")

        data = result.data if isinstance(result.data, dict) else {}
        mesh_check = await _stl_mesh_check(
            adapter,
            data.get("file_path") or input_data.file_path,
            settings.get("units") or data.get("units"),
            data.get("document_type"),
        )
        message = f"Exported to STL format: {input_data.file_path}"
        export: dict[str, Any] = {"file_path": input_data.file_path, "format": "STL"}
        if native:
            export["mesh_check"] = mesh_check
            return {
                "status": "success",
                "message": message,
                "data": result.data,
                "export": export,
                "execution_time": result.execution_time,
            }
        if not settings:
            export["use_case"] = "3D printing and rapid prototyping"
            export["size_estimate"] = "Unknown"
        mesh = data.get("mesh", {} if settings else None)
        if mesh is not None:
            export["mesh"] = mesh
        export["mesh_check"] = mesh_check
        reply: dict[str, Any] = {
            "status": "success",
            "message": message,
            "export": export,
            "execution_time": result.execution_time,
        }
        if mesh is not None and mesh.get("restored") is False:
            reply["warning"] = (
                "The file was written, but the user's STL options could not "
                "all be put back; check Tools > Options > Export > STL."
            )
        return reply

    @mcp.tool()
    async def export_pdf(input_data: ExportFileInput) -> dict[str, Any]:
        """Export the active document to PDF, like File > Save As with the PDF type.

        Use it to share a drawing; `generate_drawing_package` already saves a PDF with
        the drawing it creates. SolidWorks picks the format from the file's extension,
        so end `file_path` in .pdf. Needs: an open, active drawing (a part or assembly
        gives a PDF of the view). Changes: writes the file, creating its folder and
        replacing a file already there; the open document is unchanged. Returns:
        `export` with `file_path` and `format`.

        Args:
            input_data: The export. `file_path` (ending in .pdf) is required;
                `format_type` is not needed: the file extension decides the
                format.

        Returns:
            dict[str, Any]: The file written.
        """
        input_data = _file_input(input_data, "pdf")
        if hasattr(adapter, "export_pdf"):
            result = await adapter.export_pdf(input_data.model_dump())
        else:
            result = await adapter.export_file(input_data.file_path, "pdf")

        require_success(result, context="Failed to export PDF")
        if hasattr(adapter, "export_pdf"):
            return {
                "status": "success",
                "message": f"Exported to PDF format: {input_data.file_path}",
                "data": result.data,
                "execution_time": result.execution_time,
            }
        return {
            "status": "success",
            "message": f"Exported to PDF format: {input_data.file_path}",
            "export": {
                "file_path": input_data.file_path,
                "format": "PDF",
                "use_case": "Documentation and sharing",
                "size_estimate": "Unknown",
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def export_dwg(input_data: ExportFileInput) -> dict[str, Any]:
        """Export the active document to DWG, like File > Save As with the DWG type.

        Use it to hand a drawing to AutoCAD users. SolidWorks picks the format from the
        file's extension, so end `file_path` in .dwg. Needs: an open, active drawing.
        Changes: writes the file, creating its folder and replacing a file already
        there; the open document is unchanged. Returns: `export` with `file_path` and
        `format`.

        Args:
            input_data: The export. `file_path` (ending in .dwg) is required;
                `format_type` is not needed: the file extension decides the
                format.

        Returns:
            dict[str, Any]: The file written.
        """
        input_data = _file_input(input_data, "dwg")
        if hasattr(adapter, "export_dwg"):
            result = await adapter.export_dwg(input_data.model_dump())
        else:
            result = await adapter.export_file(input_data.file_path, "dwg")

        require_success(result, context="Failed to export DWG")
        if hasattr(adapter, "export_dwg"):
            return {
                "status": "success",
                "message": f"Exported to DWG format: {input_data.file_path}",
                "data": result.data,
                "execution_time": result.execution_time,
            }
        return {
            "status": "success",
            "message": f"Exported to DWG format: {input_data.file_path}",
            "export": {
                "file_path": input_data.file_path,
                "format": "DWG",
                "use_case": "AutoCAD compatibility",
                "size_estimate": "Unknown",
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def export_image(input_data: ExportImageInput) -> dict[str, Any]:
        """Save a picture of the active model, in a standard view or as it is on screen, as PNG or JPG.

        Use it to show a result, or to check a model's shape after a change. A standard
        view (front, back, left, right, top, bottom, isometric, dimetric, trimetric)
        turns the model to it and zooms so the whole model fits. `current` keeps the
        view exactly as it is, zoom included, so a close-up set up first comes out as
        that close-up. `zoom_to_fit` overrides the zoom either way; `zoom_box_mm`
        zooms to a box of the model (model coordinates). `hide` hides planes,
        sketches and the like, and `section` cuts the model on a plane (a snap inside
        its socket), both for this picture only. The picture keeps the graphics
        area's shape, padded out to `width` x `height`. Needs: an open, active
        document. Changes: writes the image file; a standard view or a zoom also
        turns or zooms the model on screen. Returns: `data` with `file_path`,
        `format`, `dimensions` (the size written), `requested_dimensions`, `view`,
        `zoomed_to_fit`, `zoom_box_mm`, `zoom_box_view_mm` (that box in view
        coordinates), `hidden`, `section` (as applied) and `window_state`.

        Args:
            input_data: The image. `file_path` (or `output_path`) is needed; the
                format follows its extension. `width`/`height` (or `resolution` as
                "1920x1080") and `view_orientation` (isometric) have defaults;
                `zoom_to_fit` defaults to yes except for `current`; `section` is
                off.

        Returns:
            dict[str, Any]: The image written.
        """
        input_data = normalize_input(input_data, ExportImageInput)
        if hasattr(adapter, "export_image"):
            result = await adapter.export_image(input_data.model_dump())
            require_success(result, "Failed to export image")
            reply: dict[str, Any] = {
                "status": "success",
                "message": f"Exported image: {input_data.file_path}",
                "data": result.data,
                "execution_time": result.execution_time,
            }
            data = result.data if isinstance(result.data, dict) else {}
            section = data.get("section")
            if isinstance(section, dict) and section.get("removed") is False:
                reply["warning"] = (
                    f"The section on {section.get('plane')} could not be taken off, "
                    "so the model still shows it cut. Take it off in SolidWorks "
                    "(View > Display > Section View)."
                )
            return reply

        if hasattr(adapter, "export_file") and input_data.file_path:
            result = await adapter.export_file(  # type: ignore[assignment]
                input_data.file_path, input_data.format_type
            )
            require_success(result, "Failed to export image")
            return {
                "status": "success",
                "message": f"Exported image: {input_data.file_path}",
                "export": {
                    "file_path": input_data.file_path,
                    "format": input_data.format_type.upper(),
                    "dimensions": f"{input_data.width}x{input_data.height}",
                    "view": input_data.view_orientation,
                    "use_case": "Documentation and presentations",
                },
                "execution_time": result.execution_time,
            }

        raise UnsupportedOperationError(
            "Active adapter does not support export_image or "
            "export_file; no image was exported."
        )

    @mcp.tool()
    async def batch_export(input_data: BatchExportInput) -> dict[str, Any]:
        """Export every matching SolidWorks file in a folder to one format.

        Not available yet: no adapter implements it, so every call returns an error with
        `error_type: "not_supported"`. It is planned for a future release. Today, open
        each file with `open_model` and use an `export_*` tool. Changes: once available,
        writes one exported file per source file. Returns: once available, a per-file
        result under `data`.

        Args:
            input_data: The batch. `source_directory` and `output_directory` are
                required; `format_type`, `file_pattern` and `recursive` have
                defaults.

        Returns:
            dict[str, Any]: The results, or a `not_supported` error.
        """
        require_capability(
            adapter,
            "batch_export",
            "Active adapter does not support batch_export; no files were exported.",
        )
        result = await adapter.batch_export(input_data.model_dump())
        require_success(result, "Batch export failed")
        return {
            "status": "success",
            "message": f"Batch export completed to {input_data.format_type} format",
            "data": result.data,
            "execution_time": result.execution_time,
        }

    tool_count = 7  # Number of tools registered
    return tool_count
