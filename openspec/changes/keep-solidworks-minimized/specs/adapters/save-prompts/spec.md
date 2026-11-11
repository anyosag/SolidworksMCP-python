## ADDED Requirements

### Requirement: Saving never shows a SolidWorks dialog

`save_file`, `save_assembly`, `save_as` and `close_model` with `save` SHALL save without a SolidWorks dialog. A save SolidWorks rejects SHALL return `status: error` naming the `swFileSaveError_e` flags it reported. Warnings SHALL be returned in the result's data.

#### Scenario: Saving a part in place
- **WHEN** an agent calls `save_file` on a part that has a path
- **THEN** the part is written, no dialog appears, and the result is `status: success`

#### Scenario: SolidWorks rejects the save
- **WHEN** the target file is read-only
- **THEN** the result is `status: error` and its message names `swReadOnlySaveError`

### Requirement: New and session-created referenced files are saved with the assembly

When an assembly is saved, modified referenced files that were never saved, or that this server session created or first saved, SHALL be saved with it. The result SHALL list them as `saved_references`.

#### Scenario: Assembly with a part made this session
- **WHEN** an agent creates and saves a part, inserts it into an assembly, changes the part, and calls `save_assembly`
- **THEN** both files are written, no dialog appears, and `saved_references` lists the part

### Requirement: Overwriting the user's modified files needs confirmation

When an assembly save would write a modified referenced file that existed before this session and wasn't created or first saved by it, the save SHALL write nothing, unless `overwrite_modified_references` is true. It SHALL return `status: error` with `error_type: confirmation_required`, the file paths in `data.files`, and a `hint` telling the agent to ask the user and then call again with `overwrite_modified_references: true`.

#### Scenario: A modified existing part
- **WHEN** an assembly references a part the user saved earlier, an agent changes that part, and calls `save_assembly`
- **THEN** the result is `confirmation_required` listing the part, and neither file's modified time changes

#### Scenario: Confirmed
- **WHEN** the agent calls `save_assembly` again with `overwrite_modified_references: true`
- **THEN** both files are written and `saved_references` lists the part

### Requirement: Exports are silent

Every export through `export_file` and the image fallback SHALL pass the `Silent` and `Copy` save options, so an export never shows a dialog and never renames the open document.

#### Scenario: STEP export of an assembly
- **WHEN** an agent exports an open assembly to `.step`
- **THEN** the file is written, no dialog appears, and the open document keeps its name

### Requirement: A modal dialog during an operation doesn't hang the server

While an adapter operation runs, a modal dialog of the connected SolidWorks process that stays open longer than `SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS` (default 5) SHALL be cancelled. The operation SHALL return `status: error` with `error_type: solidworks_dialog` and the dialog's title and text in `data.dialog`. The watchdog SHALL only ever press Cancel, or close the dialog; it SHALL NOT press Save, Don't Save, Yes or No.

#### Scenario: A blocking dialog
- **WHEN** an operation opens a modal dialog that nobody answers
- **THEN** within the timeout plus 2 s the call returns `solidworks_dialog` with the dialog's text, and the next call reaches SolidWorks

#### Scenario: The user's own dialogs
- **WHEN** no operation is running and the user opens a dialog in SolidWorks
- **THEN** the watchdog doesn't touch it

#### Scenario: Turned off
- **WHEN** `SOLIDWORKS_MCP_DIALOG_TIMEOUT_SECONDS` is `0`
- **THEN** no dialog is cancelled
