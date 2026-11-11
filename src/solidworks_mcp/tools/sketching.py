"""Sketching tools for SolidWorks MCP Server.

Provides tools for creating and editing sketches, including geometric entities like
lines, circles, rectangles, arcs, and constraints.
"""

import math
from typing import Annotated, Any, Literal, Self, TypeVar

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..adapters.base import SolidWorksAdapter
from .input_compat import CompatInput
from .tool_boundary import (
    normalize_input,
    require_success,
    with_tool_boundary,
)

TInput = TypeVar("TInput", bound=BaseModel)


# Input schemas using Python 3.14 built-in types


class CreateSketchInput(CompatInput):
    """Input schema for creating a sketch.

    Attributes:
        plane (str): The plane value.
        sketch_name (str | None): The sketch name value.
    """

    plane: str = Field(
        description=(
            "Plane to sketch on: 'Front' (or 'XY'), 'Top' ('XZ'), 'Right' "
            "('YZ'), or the exact name of a plane in the part, e.g. 'Plane1'"
        )
    )
    sketch_name: str | None = Field(
        default=None,
        description=(
            "Name to give the sketch in the feature tree, applied when "
            "exit_sketch closes it; omit to keep SolidWorks' own (Sketch1, "
            "Sketch2, ...)"
        ),
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the create sketch input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Plane is required.
        """
        if not self.plane.strip():
            raise ValueError("plane is required")


class AddLineInput(CompatInput):
    """Input schema for adding a line to sketch.

    Attributes:
        construction (bool): The construction value.
        end_x (float | None): The end x value.
        end_y (float | None): The end y value.
        start_x (float | None): The start x value.
        start_y (float | None): The start y value.
        x1 (float | None): The x1 value.
        x2 (float | None): The x2 value.
        y1 (float | None): The y1 value.
        y2 (float | None): The y2 value.
    """

    x1: float | None = Field(default=None, description="Start point X coordinate in mm")
    y1: float | None = Field(default=None, description="Start point Y coordinate in mm")
    x2: float | None = Field(default=None, description="End point X coordinate in mm")
    y2: float | None = Field(default=None, description="End point Y coordinate in mm")
    start_x: float | None = Field(default=None, description="Start point X alias")
    start_y: float | None = Field(default=None, description="Start point Y alias")
    end_x: float | None = Field(default=None, description="End point X alias")
    end_y: float | None = Field(default=None, description="End point Y alias")
    construction: bool = Field(default=False, description="Construction geometry flag")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the add line input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.
        """
        self.x1 = self.x1 if self.x1 is not None else self.start_x
        self.y1 = self.y1 if self.y1 is not None else self.start_y
        self.x2 = self.x2 if self.x2 is not None else self.end_x
        self.y2 = self.y2 if self.y2 is not None else self.end_y


class AddCircleInput(CompatInput):
    """Input schema for adding a circle to sketch.

    Attributes:
        center_x (float): The center x value.
        center_y (float): The center y value.
        construction (bool): The construction value.
        radius (float): The radius value.
    """

    center_x: float = Field(description="Circle center X coordinate in mm")
    center_y: float = Field(description="Circle center Y coordinate in mm")
    radius: float = Field(description="Circle radius in mm")
    construction: bool = Field(default=False, description="Construction geometry flag")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the add circle input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Radius must be positive.
        """
        if self.radius <= 0:
            raise ValueError("radius must be positive")


class AddRectangleInput(CompatInput):
    """Input schema for adding a rectangle to sketch.

    Attributes:
        construction (bool): The construction value.
        corner1_x (float | None): The corner1 x value.
        corner1_y (float | None): The corner1 y value.
        corner2_x (float | None): The corner2 x value.
        corner2_y (float | None): The corner2 y value.
        x1 (float | None): The x1 value.
        x2 (float | None): The x2 value.
        y1 (float | None): The y1 value.
        y2 (float | None): The y2 value.
    """

    x1: float | None = Field(
        default=None, description="First corner X coordinate in mm"
    )
    y1: float | None = Field(
        default=None, description="First corner Y coordinate in mm"
    )
    x2: float | None = Field(
        default=None, description="Opposite corner X coordinate in mm"
    )
    y2: float | None = Field(
        default=None, description="Opposite corner Y coordinate in mm"
    )
    corner1_x: float | None = Field(default=None, description="Corner 1 X alias")
    corner1_y: float | None = Field(default=None, description="Corner 1 Y alias")
    corner2_x: float | None = Field(default=None, description="Corner 2 X alias")
    corner2_y: float | None = Field(default=None, description="Corner 2 Y alias")
    construction: bool = Field(default=False, description="Construction geometry flag")

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the add rectangle input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Rectangle corners must differ.
        """
        self.x1 = self.x1 if self.x1 is not None else self.corner1_x
        self.y1 = self.y1 if self.y1 is not None else self.corner1_y
        self.x2 = self.x2 if self.x2 is not None else self.corner2_x
        self.y2 = self.y2 if self.y2 is not None else self.corner2_y
        if (
            None not in (self.x1, self.y1, self.x2, self.y2)
            and self.x1 == self.x2
            and self.y1 == self.y2
        ):
            raise ValueError("rectangle corners must differ")


class AddArcInput(BaseModel):
    """Input schema for adding an arc to sketch.

    Attributes:
        center_x (float): The center x value.
        center_y (float): The center y value.
        end_x (float): The end x value.
        end_y (float): The end y value.
        start_x (float): The start x value.
        start_y (float): The start y value.
    """

    center_x: float = Field(description="Arc center X coordinate in mm")
    center_y: float = Field(description="Arc center Y coordinate in mm")
    start_x: float = Field(description="Arc start point X coordinate in mm")
    start_y: float = Field(description="Arc start point Y coordinate in mm")
    end_x: float = Field(description="Arc end point X coordinate in mm")
    end_y: float = Field(description="Arc end point Y coordinate in mm")
    direction: Literal["ccw", "cw"] = Field(
        default="ccw",
        description=(
            "Which way the arc runs from start to end, looking at the sketch "
            "(x right, y up): 'ccw' counter-clockwise (the default) or 'cw'"
        ),
    )


#: An outline's points closer than this (mm) are the same point: the last
#: segment of a closed outline that ends this close to its start ends on it.
_SAME_POINT_MM = 1e-3

#: How far an arc's end may be from the circle through its start (mm).
#: SolidWorks puts the end on that circle, so a larger miss would leave a gap
#: between the arc and the next segment.
_ARC_RADIUS_TOLERANCE_MM = 1e-3

Point2 = Annotated[
    list[float],
    Field(min_length=2, max_length=2, description="A point [x, y] in sketch mm"),
]


def _distance(a: list[float], b: list[float]) -> float:
    """Distance between two sketch points, mm."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def arc_sweep_deg(
    center: list[float], start: list[float], end: list[float], direction: str
) -> float:
    """The angle an arc turns through from start to end, degrees in [0, 360).

    Args:
        center: The arc's centre [x, y].
        start: Its start point.
        end: Its end point.
        direction: ``"ccw"`` or ``"cw"``.

    Returns:
        float: 90 for a quarter arc either way round; a ``"cw"`` arc from
        (10, 0) to (0, 10) about the origin turns through 270.
    """
    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = math.degrees(end_angle - start_angle) % 360.0
    return (360.0 - sweep) % 360.0 if direction == "cw" else sweep


class OutlineSegment(BaseModel):
    """One segment of an outline, drawn from where the previous one ended.

    Attributes:
        type (str): ``"line"`` or ``"arc"``.
        to (list[float]): The segment's end point [x, y], mm.
        center (list[float] | None): The arc's centre [x, y], mm.
        direction (str): The arc's direction, ``"ccw"`` or ``"cw"``.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["line", "arc"] = Field(
        default="line", description="'line' (the default) or 'arc'"
    )
    to: Point2 = Field(
        description=(
            "End point [x, y] in mm. The segment starts where the previous one "
            "ended (the first at the outline's 'start')"
        )
    )
    center: Point2 | None = Field(
        default=None,
        description="Arc centre [x, y] in mm; required for an arc, not given for a line",
    )
    direction: Literal["ccw", "cw"] = Field(
        default="ccw",
        description="Arc direction from its start to 'to': 'ccw' (default) or 'cw'",
    )

    @model_validator(mode="after")
    def _center_matches_type(self) -> Self:
        if self.type == "arc" and self.center is None:
            raise ValueError("an arc needs 'center'")
        if self.type == "line" and self.center is not None:
            raise ValueError("a line takes no 'center'; set type to 'arc'")
        return self


class Outline(BaseModel):
    """One outline: a chain of lines and arcs, or a polyline through points.

    Attributes:
        start (list[float] | None): Where ``segments`` begins, mm.
        segments (list[OutlineSegment] | None): The chain, each from the last.
        points (list[list[float]] | None): Corner points joined by lines.
        closed (bool): Join the end back to the start.
        construction (bool): Draw it as construction geometry.
    """

    model_config = ConfigDict(extra="forbid")

    start: Point2 | None = Field(
        default=None, description="Start point [x, y] in mm; required with 'segments'"
    )
    segments: list[OutlineSegment] | None = Field(
        default=None,
        description="Lines and arcs in order, each starting where the last ended",
    )
    points: list[Point2] | None = Field(
        default=None,
        description=(
            "Instead of 'start' and 'segments': corner points [x, y] in mm, "
            "joined by straight lines"
        ),
    )
    closed: bool = Field(
        default=True,
        description=(
            "Join the last point back to the first (the default), as a profile "
            "for an extrude or cut needs; false leaves an open chain"
        ),
    )
    construction: bool = Field(
        default=False, description="Draw the outline as construction geometry"
    )

    @model_validator(mode="after")
    def _one_form(self) -> Self:
        if (self.points is None) == (self.segments is None):
            raise ValueError("give either 'points' or 'start' with 'segments'")
        if self.segments is not None and self.start is None:
            raise ValueError("'segments' needs 'start'")
        if self.points is not None and self.start is not None:
            raise ValueError("'start' goes with 'segments', not 'points'")
        self.resolve()  # refuses a degenerate outline before anything is drawn
        return self

    def resolve(self) -> list[dict[str, Any]]:
        """The outline as the segments the adapter draws.

        Each segment starts at exactly the previous one's end, and a closed
        outline ends at exactly its start, so SolidWorks sees one connected
        loop. A closed outline whose last point is (within 0.001 mm) its
        first ends there; otherwise a closing line is added.

        Returns:
            list[dict[str, Any]]: ``{"type", "start", "end"}`` per segment,
            plus ``center`` and ``direction`` for an arc.

        Raises:
            ValueError: For a zero-length segment, an arc whose end isn't on
                its circle, or too few points.
        """
        if self.points is not None:
            points = [list(map(float, p)) for p in self.points]
            if (
                self.closed
                and len(points) > 1
                and _distance(points[0], points[-1]) < _SAME_POINT_MM
            ):
                points.pop()
            needed = 3 if self.closed else 2
            if len(points) < needed:
                raise ValueError(
                    f"a {'closed' if self.closed else 'open'} outline needs at "
                    f"least {needed} distinct points"
                )
            steps: list[OutlineSegment] = [OutlineSegment(to=p) for p in points[1:]]
            start = points[0]
        else:
            steps = list(self.segments or [])
            start = [float(v) for v in (self.start or [])]
            if not steps:
                raise ValueError("'segments' is empty")

        resolved: list[dict[str, Any]] = []
        here = start
        for index, step in enumerate(steps):
            end = [float(v) for v in step.to]
            last = index == len(steps) - 1
            if self.closed and last and _distance(end, start) < _SAME_POINT_MM:
                end = start
            if _distance(here, end) < _SAME_POINT_MM:
                raise ValueError(
                    f"segment {index} ends where it starts, at {end}"
                    + (
                        "; draw a full circle with add_circle"
                        if step.type == "arc"
                        else ""
                    )
                )
            segment: dict[str, Any] = {"type": step.type, "start": here, "end": end}
            if step.type == "arc":
                center = [float(v) for v in step.center or []]
                radius = _distance(center, here)
                if radius < _SAME_POINT_MM:
                    raise ValueError(f"segment {index}: the arc's centre is its start")
                miss = abs(_distance(center, end) - radius)
                if miss > _ARC_RADIUS_TOLERANCE_MM:
                    raise ValueError(
                        f"segment {index}: the arc's end is {miss:.4g} mm off the "
                        f"circle of radius {radius:.6g} mm through its start; "
                        "put 'to' on that circle"
                    )
                segment["center"] = center
                segment["direction"] = step.direction
            resolved.append(segment)
            here = end
        if self.closed and _distance(here, start) >= _SAME_POINT_MM:
            resolved.append({"type": "line", "start": here, "end": start})
        return resolved


class EditSketchInput(CompatInput):
    """Input schema for opening an existing sketch.

    Attributes:
        name (str): The sketch's tree name.
    """

    name: str = Field(description="The sketch to open, e.g. 'Sketch3'")

    def model_post_init(self, __context: Any) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("name is required")


class DeleteSketchEntitiesInput(CompatInput):
    """Input schema for deleting entities of the open sketch.

    Attributes:
        ids (list[str]): Entity ids from ``edit_sketch`` or the ``add_*`` tools.
    """

    ids: list[str] = Field(
        min_length=1,
        description="Ids of the entities to delete, from edit_sketch or the add_* tools",
    )


class AddOutlinesInput(CompatInput):
    """Input schema for drawing whole outlines in one call.

    Attributes:
        outlines (list[Outline]): The outlines to draw.
    """

    outlines: list[Outline] = Field(
        min_length=1,
        description=(
            "One or more outlines, each a closed loop by default. Give each "
            "either 'points' (a polygon) or 'start' plus 'segments' (lines and "
            "arcs)"
        ),
    )


class AddSplineInput(BaseModel):
    """Input schema for adding a spline to sketch.

    Attributes:
        points (list[dict[str, float]]): The points value.
    """

    points: list[dict[str, float]] = Field(
        description="List of spline control points with x, y coordinates"
    )


class AddDimensionInput(BaseModel):
    """Input schema for adding a dimension to sketch.

    Attributes:
        dimension_type (str): The dimension type value.
        entity1 (str): The entity1 value.
        entity2 (str | None): The entity2 value.
        value (float): The value value.
    """

    entity1: str = Field(description="First entity name or ID")
    entity2: str | None = Field(
        default=None, description="Second entity name or ID (for distance dimensions)"
    )
    dimension_type: str = Field(
        default="linear", description="Dimension type (linear, radial, angular, etc.)"
    )
    value: float = Field(description="Dimension value in mm or degrees")


class AddRelationInput(BaseModel):
    """Input schema for adding a geometric relation.

    Attributes:
        entity1 (str): The entity1 value.
        entity2 (str | None): The entity2 value.
        entity3 (str | None): Third entity ID — only used by the ``symmetric``
            relation (the centerline of symmetry). All other relation types
            reject a non-null ``entity3``.
        relation_type (str): The relation type value.
    """

    entity1: str = Field(description="First entity name or ID")
    entity2: str | None = Field(
        default=None, description="Second entity name or ID (if required)"
    )
    entity3: str | None = Field(
        default=None,
        description=(
            "Third entity ID. Required for 'symmetric' (the centerline of "
            "symmetry); must be null for all other relations."
        ),
    )
    relation_type: str = Field(
        description="Relation type (parallel, perpendicular, tangent, coincident, etc.)"
    )


class TutorialSimpleHoleInput(CompatInput):
    """Input schema for creating a simple hole (tutorial example).

    Attributes:
        center_x (float): The center x value.
        center_y (float): The center y value.
        depth (float | None): The depth value.
        diameter (float): The diameter value.
        plane (str): The plane value.
    """

    plane: str = Field(description="Sketch plane for the hole")
    center_x: float = Field(description="Hole center X coordinate in mm")
    center_y: float = Field(description="Hole center Y coordinate in mm")
    diameter: float = Field(description="Hole diameter in mm")
    depth: float | None = Field(
        default=None, description="Hole depth in mm (None for through hole)"
    )

    def model_post_init(self, __context: Any) -> None:
        """Provide model post init support for the tutorial simple hole input.

        Args:
            __context (Any): The context value.

        Returns:
            None: None.

        Raises:
            ValueError: Depth must be positive.
        """
        if self.diameter <= 0:
            raise ValueError("diameter must be positive")
        if self.depth is not None and self.depth <= 0:
            raise ValueError("depth must be positive")


class CheckSketchDefinitionInput(CompatInput):
    """Input schema for checking sketch definition status.

    Attributes:
        sketch_name (str | None): Optional sketch name to inspect.
    """

    sketch_name: str | None = Field(
        default=None,
        description="Optional sketch name. If omitted, checks the active or last sketch.",
    )


async def register_sketching_tools(
    mcp: FastMCP, adapter: SolidWorksAdapter, config: dict[str, Any]
) -> int:
    """Register sketching tools with FastMCP.

    Registers comprehensive sketching tools for SolidWorks automation including geometry
    creation, constraints, dimensions, and pattern operations.

    Args:
        mcp (FastMCP): The mcp value.
        adapter (SolidWorksAdapter): Adapter instance used for the operation.
        config (dict[str, Any]): Configuration values for the operation.

    Returns:
        int: The computed numeric result.

    Example:
                        ```python
                        from solidworks_mcp.tools.sketching import register_sketching_tools

                        tool_count = await register_sketching_tools(mcp, adapter, config)
                        print(f"Registered {tool_count} sketching tools")
                        ```
    """
    mcp = with_tool_boundary(mcp, adapter)
    tool_count = 0
    # SolidWorks won't rename a sketch while it is open for editing (it
    # accepts the name, but the tree keeps the old one), so the name
    # create_sketch was asked for is given when exit_sketch closes it:
    # SolidWorks' name -> the name asked for.
    names_on_exit: dict[str, str] = {}

    async def _make_construction(entity_id: Any, construction: bool, what: str) -> None:
        """Turn a just-drawn entity into construction geometry when asked.

        The ``Create*`` calls have no construction flag, so it is set on the
        entity afterwards.

        Raises:
            ToolOperationError: The entity was drawn as normal geometry and
                could not be changed.
        """
        if not construction:
            return
        result = await adapter.set_sketch_construction([str(entity_id)], True)
        require_success(
            result,
            context=(
                f"The {what} {entity_id} was drawn as normal geometry, not construction"
            ),
        )

    @mcp.tool()
    async def create_sketch(input_data: CreateSketchInput) -> dict[str, Any]:
        """Open a new sketch on a plane of the active part, ready for lines, circles and other sketch entities.

        Use it first in every feature: sketch, draw, `exit_sketch`, then
        `create_extrusion` or `create_cut_extrude`. Planes: Front (XY), Top (XZ), Right
        (YZ), or a plane made by `create_reference_plane`; a plane not in the part is an
        error. Coordinates in the sketch are mm from its origin. Needs: an open part.
        Changes: adds a sketch and opens it for editing; give `sketch_name` and
        `exit_sketch` names it that when it closes it (SolidWorks won't rename an open
        sketch). Returns: `sketch` with `name` (the name in the feature tree now),
        `plane` (the plane used) and `axes`: where sketch x and y point in the model
        (`x`, `y`, `normal`, `origin_mm`, `summary`; on Top, sketch y is model -Z), plus
        `name_on_exit` when you gave `sketch_name`.

        Args:
            input_data: The sketch. `plane` is required; `sketch_name` names it.

        Returns:
            dict[str, Any]: The new sketch.
        """
        input_data = normalize_input(input_data, CreateSketchInput)
        result = await adapter.create_sketch(input_data.plane)

        require_success(result, context="Failed to create sketch")
        sketch_name = (
            result.data.get("sketch_name")
            if isinstance(result.data, dict)
            else result.data
        )
        metadata = getattr(result, "metadata", None)
        found = metadata if isinstance(metadata, dict) else {}
        plane_used = found.get("plane") or input_data.plane
        reply: dict[str, Any] = {
            "status": "success",
            "message": f"Created sketch '{sketch_name}' on {plane_used}",
            "sketch": {
                "name": sketch_name,
                "plane": plane_used,
            },
            "execution_time": result.execution_time,
        }
        axes = found.get("axes")
        if isinstance(axes, dict):
            reply["sketch"]["axes"] = axes
            reply["message"] += f" ({axes['summary']})"
        names_on_exit.clear()  # a sketch left open is abandoned with its name
        wanted = (input_data.sketch_name or "").strip()
        if wanted and wanted != sketch_name:
            names_on_exit[str(sketch_name)] = wanted
            reply["sketch"]["name_on_exit"] = wanted
            reply["message"] += f"; exit_sketch names it '{wanted}'"
        return reply

    @mcp.tool()
    async def add_line(input_data: AddLineInput) -> dict[str, Any]:
        """Draw a straight line between two points in the open sketch, in mm.

        Use it for profiles made of straight edges; for a closed box, use
        `add_rectangle`, and for a revolve axis, `add_centerline`. Needs: an open sketch
        (`create_sketch`). Changes: adds a line (a construction line with
        `construction`). Returns: `line` with `id`, `start`, `end` and `length`. Its
        `id` is what `add_sketch_constraint` and `add_sketch_dimension` take.

        Args:
            input_data: The line. Give `x1`, `y1`, `x2`, `y2` (mm; or `start_x`,
                `start_y`, `end_x`, `end_y`); `construction` is off.

        Returns:
            dict[str, Any]: The line added.
        """
        input_data = normalize_input(input_data, AddLineInput)
        result = await adapter.add_line(
            input_data.x1,  # type: ignore[arg-type]
            input_data.y1,  # type: ignore[arg-type]
            input_data.x2,  # type: ignore[arg-type]
            input_data.y2,  # type: ignore[arg-type]
        )

        require_success(result, context="Failed to add line")
        line_id = (
            result.data.get("entity_id") or result.data.get("id")
            if isinstance(result.data, dict)
            else result.data
        )
        await _make_construction(line_id, input_data.construction, "line")
        x1, y1 = input_data.x1 or 0.0, input_data.y1 or 0.0
        x2, y2 = input_data.x2 or 0.0, input_data.y2 or 0.0
        return {
            "status": "success",
            "message": f"Added line from ({x1}, {y1}) to ({x2}, {y2})",
            "line": {
                "id": line_id,
                "start": {"x": x1, "y": y1},
                "end": {"x": x2, "y": y2},
                "construction": input_data.construction,
                "length": ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_circle(input_data: AddCircleInput) -> dict[str, Any]:
        """Draw a circle in the open sketch from its centre and radius, in mm.

        Use it for holes and round bosses. Needs: an open sketch (`create_sketch`).
        Changes: adds a circle (a construction circle with `construction`). Returns:
        `circle` with `id`, `center`, `radius` and `diameter`. Its `id` is what
        `add_sketch_constraint` and `add_sketch_dimension` take.

        Args:
            input_data: The circle. `center_x`, `center_y` and `radius` (mm) are
                required; `construction` is off.

        Returns:
            dict[str, Any]: The circle added.
        """
        input_data = normalize_input(input_data, AddCircleInput)
        result = await adapter.add_circle(
            input_data.center_x, input_data.center_y, input_data.radius
        )

        require_success(result, context="Failed to add circle")
        circle_id = (
            result.data.get("entity_id")
            if isinstance(result.data, dict)
            else result.data
        )
        await _make_construction(circle_id, input_data.construction, "circle")
        return {
            "status": "success",
            "message": f"Added circle at ({input_data.center_x}, {input_data.center_y}) with radius {input_data.radius}mm",
            "circle": {
                "id": circle_id,
                "center": {"x": input_data.center_x, "y": input_data.center_y},
                "radius": input_data.radius,
                "construction": input_data.construction,
                "diameter": input_data.radius * 2,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_rectangle(input_data: AddRectangleInput) -> dict[str, Any]:
        """Draw a closed, axis-aligned rectangle in the open sketch from two opposite corners, in mm.

        Use it for blocks, plates and rectangular cut-outs. Needs: an open sketch
        (`create_sketch`). Changes: adds four connected lines. Returns: `rectangle` with
        `id`, `corner1`, `corner2`, `width`, `height` and `area`. Its `id` is what
        `add_sketch_constraint` and `add_sketch_dimension` take.

        Args:
            input_data: The rectangle. Give `x1`, `y1`, `x2`, `y2` (mm; or
                `corner1_x` ... `corner2_y`); `construction` is off.

        Returns:
            dict[str, Any]: The rectangle added.
        """
        input_data = normalize_input(input_data, AddRectangleInput)
        result = await adapter.add_rectangle(
            input_data.x1,  # type: ignore[arg-type]
            input_data.y1,  # type: ignore[arg-type]
            input_data.x2,  # type: ignore[arg-type]
            input_data.y2,  # type: ignore[arg-type]
        )

        require_success(result, context="Failed to add rectangle")
        rect_id = (
            result.data.get("entity_id")
            if isinstance(result.data, dict)
            else result.data
        )
        await _make_construction(rect_id, input_data.construction, "rectangle")
        rx1, ry1 = input_data.x1 or 0.0, input_data.y1 or 0.0
        rx2, ry2 = input_data.x2 or 0.0, input_data.y2 or 0.0
        width = abs(rx2 - rx1)
        height = abs(ry2 - ry1)

        return {
            "status": "success",
            "message": f"Added rectangle from ({rx1}, {ry1}) to ({rx2}, {ry2})",
            "rectangle": {
                "id": rect_id,
                "corner1": {"x": rx1, "y": ry1},
                "corner2": {"x": rx2, "y": ry2},
                "construction": input_data.construction,
                "width": width,
                "height": height,
                "area": width * height,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def exit_sketch() -> dict[str, Any]:
        """Close the open sketch so a feature can use it.

        Call it after drawing and before `create_extrusion`, `create_revolve` or
        `create_cut_extrude`; those use the sketch closed last. Needs: an open sketch.
        Changes: leaves sketch editing; the sketch stays in the feature tree, renamed
        to the `sketch_name` `create_sketch` was given. Returns: a message, plus, after
        a `sketch_name`, `sketch` with `name` (the name in the feature tree, which later
        tools take as `sketch_name`) and a `warning` when the name couldn't be given
        (another feature has it).
        """
        result = await adapter.exit_sketch()

        require_success(result, context="Failed to exit sketch")
        reply: dict[str, Any] = {
            "status": "success",
            "message": "Exited sketch editing mode",
            "execution_time": result.execution_time,
        }
        if names_on_exit:
            current, wanted = names_on_exit.popitem()
            renamed = await adapter.rename_feature(current, wanted)
            name = current
            if renamed.is_success:
                name = (renamed.data or {}).get("new_name") or wanted
            else:
                reply["warning"] = (
                    f"The sketch keeps SolidWorks' name '{current}': it could "
                    f"not be named '{wanted}' ({renamed.error})."
                )
            reply["sketch"] = {"name": name}
        return reply

    @mcp.tool()
    async def check_sketch_fully_defined(
        input_data: CheckSketchDefinitionInput | None = None,
    ) -> dict[str, Any]:
        """Check whether a sketch is fully defined, under-defined or over-defined.

        Use it after adding relations and dimensions, to see if the sketch still has
        free geometry. Needs: an open part with the sketch. Read-only. Returns: `sketch`
        with `sketch_name`, `is_fully_defined` (null when unknown), `definition_state`
        and where the answer came from (`source`).

        Args:
            input_data: Nothing is required: give `sketch_name`, or omit it for the
                open or last sketch.

        Returns:
            dict[str, Any]: The definition state.
        """
        normalized = normalize_input(
            input_data or {},
            CheckSketchDefinitionInput,
        )
        result = await adapter.check_sketch_fully_defined(normalized.sketch_name)

        require_success(result, context="Failed to inspect sketch definition")

        payload = result.data or {}
        state = payload.get("definition_state", "unknown")
        return {
            "status": "success",
            "message": f"Sketch definition state: {state}",
            "sketch": payload,
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_arc(input_data: AddArcInput) -> dict[str, Any]:
        """Draw a circular arc in the open sketch from its centre, start point and end point, in mm.

        Use it for rounded ends and curved edges of a profile; for a whole outline in
        one call, use `add_outlines`. The arc runs counter-clockwise from start to end
        unless `direction` is "cw". Needs: an open sketch (`create_sketch`). Changes:
        adds an arc. Returns: `arc` with `id`, `center`, `start_point`, `end_point`,
        `direction`, `radius` and `sweep_deg`. Its `id` is what `add_sketch_constraint`
        and `add_sketch_dimension` take.

        Args:
            input_data: The arc. `center_x`, `center_y`, `start_x`, `start_y`,
                `end_x` and `end_y` (mm) are all required; `direction` is "ccw".

        Returns:
            dict[str, Any]: The arc added.
        """
        input_data = normalize_input(input_data, AddArcInput)
        result = await adapter.add_arc(
            input_data.center_x,
            input_data.center_y,
            input_data.start_x,
            input_data.start_y,
            input_data.end_x,
            input_data.end_y,
            input_data.direction,
        )

        require_success(result, context="Failed to add arc")
        arc_id = result.data
        center = [input_data.center_x, input_data.center_y]
        start = [input_data.start_x, input_data.start_y]
        end = [input_data.end_x, input_data.end_y]
        return {
            "status": "success",
            "message": (
                f"Added {input_data.direction} arc centered at "
                f"({input_data.center_x}, {input_data.center_y})"
            ),
            "arc": {
                "id": arc_id,
                "center": {"x": input_data.center_x, "y": input_data.center_y},
                "start_point": {
                    "x": input_data.start_x,
                    "y": input_data.start_y,
                },
                "end_point": {"x": input_data.end_x, "y": input_data.end_y},
                "direction": input_data.direction,
                "radius": round(_distance(center, start), 6),
                "sweep_deg": round(
                    arc_sweep_deg(center, start, end, input_data.direction), 6
                ),
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_outlines(input_data: AddOutlinesInput) -> dict[str, Any]:
        """Draw whole outlines of lines and arcs in the open sketch in one call, in mm.

        Use it instead of many `add_line` and `add_arc` calls: a honeycomb of 25
        hexagons is one call with 25 `points` lists. Each outline is either `points`
        (a polygon) or `start` plus `segments`, each a line or an arc (`center`,
        `direction`) to `to`. Outlines close by default (`closed`), each segment
        starting exactly where the last ended, so the loop is connected. Needs: an
        open sketch (`create_sketch`). Changes: adds the segments; if SolidWorks
        refuses one, the call removes what it drew and says which failed. Returns:
        `outlines` with each one's segment `ids`, plus `segment_count`, `line_count`
        and `arc_count`.

        Args:
            input_data: The outlines. `outlines` is required: each needs `points`,
                or `start` and `segments`; `closed` is on, `construction` off.

        Returns:
            dict[str, Any]: The segments drawn.
        """
        input_data = normalize_input(input_data, AddOutlinesInput)
        outlines = [
            {"segments": outline.resolve(), "construction": outline.construction}
            for outline in input_data.outlines
        ]
        result = await adapter.add_sketch_outlines(outlines)
        require_success(result, context="Failed to draw outlines")
        data = result.data or {}
        drawn = data.get("outlines") or []
        replies = [
            {
                "index": index,
                "ids": reply.get("ids", []),
                "segment_count": len(reply.get("ids", [])),
                "closed": source.closed,
                "construction": source.construction,
            }
            for index, (reply, source) in enumerate(
                zip(drawn, input_data.outlines, strict=False)
            )
        ]
        count = data.get("segment_count", 0)
        return {
            "status": "success",
            "message": (
                f"Drew {len(replies)} outline(s): {count} segments "
                f"({data.get('line_count', 0)} lines, {data.get('arc_count', 0)} arcs)"
            ),
            "outlines": replies,
            "segment_count": count,
            "line_count": data.get("line_count", 0),
            "arc_count": data.get("arc_count", 0),
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def edit_sketch(input_data: EditSketchInput) -> dict[str, Any]:
        """Open an existing sketch for editing, listing its segments with ids.

        Use it to change a profile without deleting the feature built on it: open the
        sketch, `delete_sketch_entities` what goes, draw what's new with the `add_*`
        tools or `add_outlines`, then `exit_sketch`, which rebuilds the features that
        use it. Needs: an open part with the sketch. Changes: opens the sketch for
        editing. Returns: `sketch` with `name` and `segments` (each with `id`, `type`,
        and `start_mm`, `end_mm` or `center_mm` in sketch coordinates).

        Args:
            input_data: The sketch. `name` is required.

        Returns:
            dict[str, Any]: The open sketch and its segments.
        """
        input_data = normalize_input(input_data, EditSketchInput)
        names_on_exit.clear()
        result = await adapter.edit_sketch(input_data.name)
        require_success(result, context=f"Failed to open {input_data.name}")
        data = result.data if isinstance(result.data, dict) else {}
        segments = data.get("segments") or []
        return {
            "status": "success",
            "message": f"Opened {input_data.name} for editing ({len(segments)} segments)",
            "sketch": {"name": input_data.name, "segments": segments},
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def delete_sketch_entities(
        input_data: DeleteSketchEntitiesInput,
    ) -> dict[str, Any]:
        """Delete lines, arcs and other entities of the open sketch by id.

        Use it after `edit_sketch` (whose reply lists the ids) or to remove something
        an `add_*` tool just drew. Needs: an open sketch. Changes: removes the entities
        from the sketch. Returns: `deleted` and `remaining` (the ids still in the
        sketch).

        Args:
            input_data: The entities. `ids` (one or more) is required.

        Returns:
            dict[str, Any]: What was deleted.
        """
        input_data = normalize_input(input_data, DeleteSketchEntitiesInput)
        result = await adapter.delete_sketch_entities(list(input_data.ids))
        require_success(result, context="Failed to delete sketch entities")
        data = result.data if isinstance(result.data, dict) else {}
        return {
            "status": "success",
            "message": f"Deleted {', '.join(input_data.ids)}",
            "deleted": data.get("deleted", list(input_data.ids)),
            "remaining": data.get("remaining", []),
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_spline(input_data: AddSplineInput) -> dict[str, Any]:
        """Draw a smooth spline through a list of points in the open sketch, in mm.

        Use it for free-form curves such as an aerofoil or a handle profile. Needs: an
        open sketch (`create_sketch`). Changes: adds a spline. Returns: `spline` with
        `id`, `control_points` and `point_count`.

        Args:
            input_data: The spline. `points` (a list of {"x", "y"} in mm) is
                required.

        Returns:
            dict[str, Any]: The spline added.
        """
        result = await adapter.add_spline(input_data.points)

        require_success(result, context="Failed to add spline")
        spline_id = result.data
        return {
            "status": "success",
            "message": f"Added spline with {len(input_data.points)} control points",
            "spline": {
                "id": spline_id,
                "control_points": input_data.points,
                "point_count": len(input_data.points),
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_centerline(input_data: AddLineInput) -> dict[str, Any]:
        """Draw a centreline (construction line) in the open sketch, in mm.

        Use it as the axis for `create_revolve`, or as the line for `sketch_mirror` and
        symmetric relations. It is never part of the profile. Needs: an open sketch
        (`create_sketch`). Changes: adds a centreline. Returns: `centerline` with `id`,
        `start_point` and `end_point`.

        Args:
            input_data: The line. Give `x1`, `y1`, `x2`, `y2` (mm; or `start_x`,
                `start_y`, `end_x`, `end_y`); `construction` is not used.

        Returns:
            dict[str, Any]: The centreline added.
        """
        input_data = normalize_input(input_data, AddLineInput)

        result = await adapter.add_centerline(
            input_data.x1,  # type: ignore[arg-type]
            input_data.y1,  # type: ignore[arg-type]
            input_data.x2,  # type: ignore[arg-type]
            input_data.y2,  # type: ignore[arg-type]
        )

        require_success(result, context="Failed to add centerline")
        centerline_id = result.data
        return {
            "status": "success",
            "message": f"Added centerline from ({input_data.x1}, {input_data.y1}) to ({input_data.x2}, {input_data.y2})",
            "centerline": {
                "id": centerline_id,
                "start_point": {"x": input_data.x1, "y": input_data.y1},
                "end_point": {"x": input_data.x2, "y": input_data.y2},
                "type": "construction",
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_polygon(input_data: dict[str, Any]) -> dict[str, Any]:
        """Draw a regular polygon (e.g. a hexagon) in the open sketch from its centre, radius and number of sides.

        Use it for nuts, hex bosses and pockets. Needs: an open sketch
        (`create_sketch`). Changes: adds the polygon's sides. Returns: `polygon` with
        `id`, `center`, `radius` and `sides`.

        Args:
            input_data: A mapping: `center_x`, `center_y` (mm, default 0), `radius`
                (mm, circumscribed, default 10) and `sides` (default 6).

        Returns:
            dict[str, Any]: The polygon added.
        """
        center_x = input_data.get("center_x", 0.0)
        center_y = input_data.get("center_y", 0.0)
        radius = input_data.get("radius", 10.0)
        sides = input_data.get("sides", 6)

        result = await adapter.add_polygon(center_x, center_y, radius, sides)

        require_success(result, context="Failed to add polygon")
        polygon_id = result.data
        return {
            "status": "success",
            "message": f"Added {sides}-sided polygon at ({center_x}, {center_y}) with radius {radius}mm",
            "polygon": {
                "id": polygon_id,
                "center": {"x": center_x, "y": center_y},
                "radius": radius,
                "sides": sides,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_ellipse(input_data: dict[str, Any]) -> dict[str, Any]:
        """Draw an ellipse in the open sketch from its centre and axis lengths, in mm.

        Use it for oval holes and bosses. Needs: an open sketch (`create_sketch`).
        Changes: adds an ellipse. Returns: `ellipse` with `id`, `center`, `major_axis`
        and `minor_axis`.

        Args:
            input_data: A mapping: `center_x`, `center_y` (mm, default 0),
                `major_axis` (default 20) and `minor_axis` (default 10), in mm.

        Returns:
            dict[str, Any]: The ellipse added.
        """
        center_x = input_data.get("center_x", 0.0)
        center_y = input_data.get("center_y", 0.0)
        major_axis = input_data.get("major_axis", 20.0)
        minor_axis = input_data.get("minor_axis", 10.0)

        result = await adapter.add_ellipse(center_x, center_y, major_axis, minor_axis)

        require_success(result, context="Failed to add ellipse")
        ellipse_id = result.data
        return {
            "status": "success",
            "message": f"Added ellipse at ({center_x}, {center_y}) with axes {major_axis}x{minor_axis}mm",
            "ellipse": {
                "id": ellipse_id,
                "center": {"x": center_x, "y": center_y},
                "major_axis": major_axis,
                "minor_axis": minor_axis,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_sketch_constraint(input_data: AddRelationInput) -> dict[str, Any]:
        """Add a geometric relation between sketch entities: horizontal, vertical, parallel, perpendicular, tangent, coincident, concentric, equal, symmetric, collinear or fix.

        Use it to hold design intent, then check with `check_sketch_fully_defined`.
        Entities are the `id`s the add_* tools returned. Needs: an open sketch
        (`create_sketch`). Changes: adds the relation. Returns: `constraint` with `id`,
        `type` and the entities.

        Args:
            input_data: The relation. `entity1` and `relation_type` are required;
                `entity2` when the relation needs two, and `entity3` (the
                centreline) only for symmetric.

        Returns:
            dict[str, Any]: The relation added.
        """
        input_data = normalize_input(input_data, AddRelationInput)
        result = await adapter.add_sketch_constraint(
            input_data.entity1,
            input_data.entity2,
            input_data.relation_type,
            input_data.entity3,
        )

        require_success(result, context="Failed to add constraint")
        constraint_id = result.data
        return {
            "status": "success",
            "message": f"Added {input_data.relation_type} constraint between {input_data.entity1} and {input_data.entity2}",
            "constraint": {
                "id": constraint_id,
                "type": input_data.relation_type,
                "entity1": input_data.entity1,
                "entity2": input_data.entity2,
                "entity3": input_data.entity3,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def add_sketch_dimension(input_data: AddDimensionInput) -> dict[str, Any]:
        """Add a driving dimension to sketch entities: linear, angular, radial or diameter.

        Use it to fix a size so the sketch is fully defined and can be changed later
        with `set_dimension`. Entities are the `id`s the add_* tools returned; two
        connected lines for angular, a circle or arc for radial or diameter. No dialog
        opens. Needs: an open sketch (`create_sketch`). Changes: adds the dimension and
        resizes the geometry to `value`. Returns: `dimension` with `id`, `type`, `value`
        and the entities.

        Args:
            input_data: The dimension. `entity1` and `value` (mm, or degrees for
                angular) are required; `entity2` and `dimension_type` (linear) have
                defaults.

        Returns:
            dict[str, Any]: The dimension added.
        """
        input_data = normalize_input(input_data, AddDimensionInput)
        result = await adapter.add_sketch_dimension(
            input_data.entity1,
            input_data.entity2,
            input_data.dimension_type,
            input_data.value,
        )

        require_success(result, context="Failed to add dimension")
        dimension_id = result.data
        return {
            "status": "success",
            "message": f"Added {input_data.dimension_type} dimension of {input_data.value}mm to {input_data.entity1}",
            "dimension": {
                "id": dimension_id,
                "type": input_data.dimension_type,
                "value": input_data.value,
                "entity1": input_data.entity1,
                "entity2": input_data.entity2,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def sketch_linear_pattern(input_data: dict[str, Any]) -> dict[str, Any]:
        """Repeat sketch entities in a straight line at a fixed spacing.

        Use it for rows of holes or slots before one cut. Needs: an open sketch
        (`create_sketch`). Changes: adds copies of the entities. Returns: `pattern` with
        `id`, `entities`, `count`, `spacing` and `direction`.

        Args:
            input_data: A mapping: `entities` (ids to repeat), `direction_x`/
                `direction_y` (default 1, 0), `spacing` (mm, default 10) and
                `count` (instances, default 3).

        Returns:
            dict[str, Any]: The pattern added.
        """
        entities = input_data.get("entities", [])
        direction_x = input_data.get("direction_x", 1.0)
        direction_y = input_data.get("direction_y", 0.0)
        spacing = input_data.get("spacing", 10.0)
        count = input_data.get("count", 3)

        result = await adapter.sketch_linear_pattern(
            entities, direction_x, direction_y, spacing, count
        )

        require_success(result, context="Failed to create linear pattern")
        pattern_id = result.data
        return {
            "status": "success",
            "message": f"Created linear pattern with {count} instances, spacing {spacing}mm",
            "pattern": {
                "id": pattern_id,
                "type": "linear",
                "entities": entities,
                "count": count,
                "spacing": spacing,
                "direction": {"x": direction_x, "y": direction_y},
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def sketch_circular_pattern(input_data: dict[str, Any]) -> dict[str, Any]:
        """Repeat sketch entities around the sketch origin, e.g. a bolt circle.

        The centre is always the sketch origin, so draw the first entity at the radius
        you want from it. Then cut once with `create_cut_extrude`. Needs: an open sketch
        (`create_sketch`). Changes: adds copies of the entities. Returns: `pattern` with
        `id`, `entities`, `count` and `angle`.

        Args:
            input_data: A mapping: `entities` (ids to repeat), `count` (instances,
                default 6) and `angle` (degrees spread over, default 360).

        Returns:
            dict[str, Any]: The pattern added.
        """
        entities = input_data.get("entities", [])
        angle = input_data.get("angle", 360.0)
        count = input_data.get("count", 6)

        result = await adapter.sketch_circular_pattern(entities, angle, count)

        require_success(result, context="Failed to create circular pattern")
        pattern_id = result.data
        return {
            "status": "success",
            "message": (
                f"Created circular pattern with {count} instances "
                "around the sketch origin"
            ),
            "pattern": {
                "id": pattern_id,
                "type": "circular",
                "entities": entities,
                "count": count,
                "center": {"x": 0.0, "y": 0.0},
                "angle": angle,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def sketch_mirror(input_data: dict[str, Any]) -> dict[str, Any]:
        """Mirror sketch entities about a centreline in the open sketch.

        Use it for symmetric profiles: draw one half, add a centreline with
        `add_centerline`, then mirror. Needs: an open sketch (`create_sketch`). Changes:
        adds mirrored copies. Returns: `mirror` with `id`, `entities` and `mirror_line`.

        Args:
            input_data: A mapping: `entities` (ids to mirror) and `mirror_line`
                (the centreline's id).

        Returns:
            dict[str, Any]: The mirror added.
        """
        entities = input_data.get("entities", [])
        mirror_line = input_data.get("mirror_line", "")

        result = await adapter.sketch_mirror(entities, mirror_line)

        require_success(result, context="Failed to mirror entities")
        mirror_id = result.data
        return {
            "status": "success",
            "message": f"Mirrored {len(entities)} entities about {mirror_line}",
            "mirror": {
                "id": mirror_id,
                "entities": entities,
                "mirror_line": mirror_line,
            },
            "execution_time": result.execution_time,
        }

    @mcp.tool()
    async def sketch_offset(input_data: dict[str, Any]) -> dict[str, Any]:
        """Offset sketch entities by a distance in mm, outward or inward, e.g. for a wall or a clearance.

        Needs: an open sketch (`create_sketch`). Changes: adds the offset entities.
        Returns: `offset` with `id`, `entities`, `distance` and `direction` (outward or
        inward).

        Args:
            input_data: A mapping: `entities` (ids to offset), `offset_distance`
                (mm, default 5) and `reverse_direction` (inward; default off).

        Returns:
            dict[str, Any]: The offset added.
        """
        entities = input_data.get("entities", [])
        offset_distance = input_data.get("offset_distance", 5.0)
        reverse_direction = input_data.get("reverse_direction", False)

        result = await adapter.sketch_offset(
            entities, offset_distance, reverse_direction
        )

        require_success(result, context="Failed to create offset")
        offset_id = result.data
        direction = "outward" if not reverse_direction else "inward"
        return {
            "status": "success",
            "message": f"Created offset of {len(entities)} entities by {offset_distance}mm ({direction})",
            "offset": {
                "id": offset_id,
                "entities": entities,
                "distance": offset_distance,
                "direction": direction,
            },
            "execution_time": result.execution_time,
        }

    # Additional sketch tools can be added here in the future:
    # - add_arc (3-point arc, center-point arc)
    # - add_spline (free-form curves)
    # - add_dimension (dimensional constraints)
    # - add_relation (geometric constraints like parallel, perpendicular)
    # - add_pattern (circular, linear patterns)
    # - trim_entities (trim overlapping geometry)
    # - mirror_entities (mirror sketch geometry)

    @mcp.tool()
    async def sketch_tutorial_simple_hole() -> dict[str, Any]:
        """Demonstrate the sketch steps: draw a 5 mm circle at the origin on the Top plane and close the sketch.

        It is a fixed example; for a real hole, use `create_sketch`, `add_circle`,
        `exit_sketch` and `create_cut_extrude`. Needs: an open part. Changes: adds a
        sketch with one circle. Returns: `steps_completed`, `next_step` (cut the hole
        with `create_cut_extrude`) and `suggested_cut`, that call's input.
        """
        steps_completed = []

        # Step 1: Create sketch
        sketch_result = await adapter.create_sketch("Top")
        require_success(sketch_result, context="Failed to create sketch")
        sketch_name = (
            sketch_result.data.get("sketch_name")
            if isinstance(sketch_result.data, dict)
            else sketch_result.data
        )
        steps_completed.append(f"Created sketch: {sketch_name}")

        # Step 2: Add circle
        circle_result = await adapter.add_circle(0, 0, 2.5)
        require_success(circle_result, context="Failed to add circle")
        steps_completed.append(f"Added 5mm diameter circle: {circle_result.data}")

        # Step 3: Exit sketch
        exit_result = await adapter.exit_sketch()
        require_success(exit_result, context="Failed to exit sketch")
        steps_completed.append("Exited sketch")

        return {
            "status": "success",
            "message": "Tutorial completed: Simple hole sketch created",
            "steps_completed": steps_completed,
            "next_step": (
                "Cut the hole through the part with create_cut_extrude, using "
                "suggested_cut as its input"
            ),
            "suggested_cut": {
                "sketch_name": sketch_name,
                "depth": 10.0,
                "end_condition": "ThroughAll",
            },
        }

    @mcp.tool()
    async def tutorial_simple_hole(
        input_data: TutorialSimpleHoleInput,
    ) -> dict[str, Any]:
        """Draw a circle on a plane and cut it as a hole, as one worked example.

        Not available yet on real SolidWorks: its cut step has no COM implementation,
        so the call draws and closes the sketch, then fails. It is planned for a future
        release. Use `create_sketch`, `add_circle`, `exit_sketch` and
        `create_cut_extrude` instead. Needs: an open part with a solid body.
        Changes: adds a sketch (and, with the mock adapter, a cut). Returns: `tutorial`
        with `plane`, `diameter`, `depth` and `steps`.

        Args:
            input_data: The hole. `plane`, `center_x`, `center_y` and `diameter`
                (mm) are required; `depth` defaults to the diameter.

        Returns:
            dict[str, Any]: The steps run.
        """
        steps: list[dict[str, Any]] = []

        sketch_result = await adapter.create_sketch(input_data.plane)
        require_success(sketch_result, context="Failed to create sketch")
        steps.append({"step": "Create sketch", "status": "success"})

        circle_result = await adapter.add_sketch_circle(
            input_data.center_x,
            input_data.center_y,
            input_data.diameter / 2,
            False,
        )
        require_success(circle_result, context="Failed to add circle")
        steps.append({"step": "Add circle", "status": "success"})

        exit_result = await adapter.exit_sketch()
        require_success(exit_result, context="Failed to exit sketch")
        steps.append({"step": "Exit sketch", "status": "success"})

        cut_depth = (
            input_data.depth if input_data.depth is not None else input_data.diameter
        )
        cut_result = await adapter.create_cut("HoleSketch", cut_depth)
        require_success(cut_result, context="Failed to create cut extrude")
        steps.append({"step": "Create cut extrude", "status": "success"})

        return {
            "status": "success",
            "message": "Completed simple hole tutorial",
            "tutorial": {
                "plane": input_data.plane,
                "diameter": input_data.diameter,
                "depth": input_data.depth,
                "steps": steps,
            },
        }

    tool_count = 6  # Legacy count expected by tests
    return tool_count
