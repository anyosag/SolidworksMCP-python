## ADDED Requirements

### Requirement: An existing fillet's or chamfer's edges can be replaced

`edit_feature` on a fillet (`Fillet`) or a chamfer (`Chamfer`) SHALL take new edges in one of two ways:
- `edges: "selection"`: the edges selected now;
- `edge_rules`: a `select_edges` query, `any_of` included.

Either one replaces the feature's whole edge set. The feature SHALL keep its name, its other parameters (radius, distances, angle) and its place in the tree, and SHALL rebuild without errors.

The reply SHALL give `edges_before` and `edges_after` (counts read from the feature), and the volume change as `measured_change` when the volume can be read without a rebuild. Giving both, or no edges selected or matched, SHALL fail with `error_type: invalid_input` and leave the feature as it was. Edge changes on any other feature type SHALL be refused, naming what that type takes.

#### Scenario: A fillet broken by a shorter spine
- **WHEN** a fillet failed to rebuild after its spine was shortened, and an agent selects the spine's new top edges with `select_edges`, then calls `edit_feature` with `name: "SpineEdgeFillet"` and `edges: "selection"`
- **THEN** the fillet rebuilds with the new edges, keeps its name and radius, and `list_features` shows it where it was

#### Scenario: A chamfer moved to other edges by a rule
- **WHEN** an agent calls `edit_feature` on a 1 mm chamfer with `edge_rules: {"side": "top", "edge_type": "linear"}`
- **THEN** the chamfer's edges are the top face's straight edges, and its distance is still 1 mm

#### Scenario: Nothing selected
- **WHEN** an agent calls `edit_feature` with `edges: "selection"` and nothing is selected
- **THEN** the call fails with `error_type: invalid_input`, and the fillet still has its old edges
