# Server Admin Tools

Tools in the server_admin category.

> **Prerequisite:** SolidWorks running

**Total tools in this category: 2**

---

### `reset_circuit_breaker`

Let calls through again to operations the server paused after repeated failures.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `operation` | `str?` | — | `None` | The operation to reset, as named in the circuit_open error (e.g. create_extrusion); leave it out to reset every operation |

**Sample call:**

```json
{}
```

---

### `set_solidworks_window`

Minimize or restore the SolidWorks window, so the user can work in other apps while you model.

**Prerequisite:** SolidWorks running

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `state` | `Literal['minimize', 'restore']` | ✅ | `` | minimize: hide SolidWorks in the taskbar and keep it there while tools run; restore: bring it back up for the user to see |

**Sample call:**

```json
{
  "state": null
}
```

---
