"""Dashboard config validation and dashboard generation.

Requirements: FR-3.1-FR-3.11 (validation), FR-4.1-FR-4.9 (generation).

Validation (T8) runs at REGISTRATION time, not render time. This is the
highest-signal requirement in the assignment: the brief says configs are merely
"stored in memory", which invites a blind write. Delegate per-view checks to the
view handlers.

Aggregation precedence (FR-3.7):
    view config value -> schema field default -> error

Generation (T9) loads schema + rows + config and dispatches each view through
the view registry. There must be no if/elif on view type in this module.

TODO(T8): config validation.
TODO(T9): generation.
"""
