## ADDED Requirements

### Requirement: A picture can be cut on a plane

`export_image` SHALL take an optional `section`: `plane` (a plane's name, such as "Front Plane" or a reference plane), `offset_mm` (default 0) and `reverse` (default false, which side is kept). The picture SHALL show the model cut on that plane, with the cut faces capped. The section SHALL apply to this picture only: when the call returns, with success or not, the model SHALL show no section. The reply's `data` SHALL include `section` as applied.

`section` SHALL work with every view orientation, with `zoom_box_mm` and with `hide`.

#### Scenario: A snap in its socket
- **WHEN** an agent calls `export_image` on the assembly with `view_orientation: "front"`, `section: {"plane": "Front Plane", "offset_mm": 0}` and a zoom box around the latch
- **THEN** the picture shows the latch cut through its middle inside the socket, and afterwards the assembly shows no section

#### Scenario: An unknown plane
- **WHEN** `section.plane` names no plane in the model
- **THEN** the call fails with `error_type: not_found` before any picture is taken, and the model is unchanged
