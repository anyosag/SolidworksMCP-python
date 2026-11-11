## ADDED Requirements

### Requirement: A minimized SolidWorks stays minimized through an operation

When the SolidWorks window is minimized as an adapter operation starts, it SHALL be minimized when the operation returns. If SolidWorks took the foreground during the operation, it SHALL give it back.

#### Scenario: Building a part while minimized
- **WHEN** an agent calls `create_part`, then `create_sketch`, `add_rectangle`, `exit_sketch` and `create_extrusion`, with SolidWorks minimized
- **THEN** after each call returns the window is minimized, and the foreground window doesn't belong to SolidWorks

#### Scenario: Switching documents while minimized
- **WHEN** an agent calls `open_model`, `activate_document` or `close_model` with SolidWorks minimized
- **THEN** the window is minimized when the call returns

### Requirement: A window the user restored is left alone

The adapter SHALL minimize the window only when it was minimized at the start of the operation, or when an agent asks through `set_solidworks_window`.

#### Scenario: User restores SolidWorks between calls
- **WHEN** the user restores the window and the agent then calls `create_extrusion`
- **THEN** the window is still restored after the call

### Requirement: Connecting doesn't restore a minimized window

`connect()` SHALL show the window only when it is hidden and `SOLIDWORKS_MCP_HEADLESS` is not set, and SHALL leave a minimized window minimized.

#### Scenario: Server starts while SolidWorks is minimized
- **WHEN** the server connects to a running, minimized SolidWorks
- **THEN** the window is still minimized after `connect()` returns

### Requirement: Keeping the window minimized can be turned off

With `SOLIDWORKS_MCP_KEEP_MINIMIZED` set to `0`, `false`, `no` or `off`, the adapter SHALL NOT change the window's state after operations.

#### Scenario: Turned off
- **WHEN** the setting is `0`, SolidWorks is minimized, and an operation restores it
- **THEN** the adapter leaves it restored

### Requirement: Screenshots work while minimized

`export_image` SHALL write an image of the requested size whose content isn't blank while SolidWorks is minimized, SHALL NOT take keyboard focus, and SHALL leave the window minimized. Its result SHALL include `window_state` (`minimized`, `normal`, `maximized` or `unknown`).

#### Scenario: Screenshot of a part while minimized
- **WHEN** a part with a solid body is open, SolidWorks is minimized, and an agent calls `export_image` with `width: 800, height: 600`
- **THEN** the file is 800×600, its pixels aren't all one colour, the result has `window_state: minimized`, and the window is still minimized

### Requirement: Agents can minimize or restore SolidWorks

A `set_solidworks_window` tool SHALL take `state: minimize | restore` and return the resulting `window_state`. Restoring SHALL bring the window up for the user; minimizing SHALL NOT leave SolidWorks in the foreground.

#### Scenario: Minimize on request
- **WHEN** an agent calls `set_solidworks_window` with `state: minimize`
- **THEN** the result is `status: success` with `window_state: minimized`

#### Scenario: Mock mode
- **WHEN** the server runs with the mock adapter
- **THEN** the tool succeeds and reports the state it simulated
