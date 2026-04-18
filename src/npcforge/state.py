"""Project-level state variables that NPCs can react to.

v0.6.0 introduces the **state layer**: writers declare the variables
their game cares about (``time_of_day``, ``weather``, ``player_bounty``,
``disposition_mira``, ``quest_locket_stage``), and downstream generators
produce dialogue that reads (``<<if>>``) and sometimes writes (``<<set>>``)
those variables.

This module owns:

- :class:`ProjectVariable` — the declaration schema for one variable.
- :class:`VariablesConfig` — the top-level ``variables.yaml`` shape.
- :func:`load_variables` — file loader.
- :func:`format_variables_for_prompt` — the LLM-facing block injected into
  every downstream generator's prompt.
- :func:`yarn_declare_block` — renders ``<<declare $id = default as Type>>``
  lines for the master ``Start`` node so generated Yarn compiles standalone.
- :func:`yarn_literal` — Python-value → Yarn-literal formatter.

Nothing here calls an LLM or writes Yarn bodies. Dialogue generators import
these helpers and compose the rest.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class VariableType(str, Enum):
    """Yarn Spinner 2 understands these four scalar types natively."""

    ENUM = "enum"       # stored as a string, constrained to a fixed value set
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    STRING = "string"


class ProjectVariable(BaseModel):
    """One declared state variable.

    ``enum`` is a convenience type: Yarn has no real enum, so we emit a
    ``string`` with a fixed value set. The value set matters for generators
    — e.g. the time-of-day greeting generator produces one variant per
    ``values`` entry.
    """

    id: str = Field(..., description="Yarn-safe identifier (without the leading $).")
    type: VariableType
    description: str = ""
    default: Any = None
    values: list[str] = Field(
        default_factory=list,
        description="Allowed values when type == enum. Ignored otherwise.",
    )
    range: tuple[int, int] | None = Field(
        default=None,
        description="Clamp bounds for int / float. Advisory; not enforced in Yarn.",
    )

    @model_validator(mode="after")
    def _shape(self) -> "ProjectVariable":
        if self.type == VariableType.ENUM:
            if not self.values:
                raise ValueError(
                    f"variable {self.id!r}: enum type requires a non-empty 'values' list"
                )
            if self.default is None:
                self.default = self.values[0]
            elif self.default not in self.values:
                raise ValueError(
                    f"variable {self.id!r}: default {self.default!r} not in values"
                )
        elif self.type == VariableType.BOOL:
            if self.default is None:
                self.default = False
        elif self.type in (VariableType.INT, VariableType.FLOAT):
            if self.default is None:
                self.default = 0 if self.type == VariableType.INT else 0.0
        elif self.type == VariableType.STRING:
            if self.default is None:
                self.default = ""
        return self


class VariablesConfig(BaseModel):
    """Top-level ``variables.yaml`` schema."""

    variables: list[ProjectVariable] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_variables(path: Path) -> VariablesConfig:
    """Load ``variables.yaml`` if present; return an empty config otherwise.

    An absent file is valid — v0.5.x projects still run. Downstream generators
    check ``config.variables`` before emitting any state-aware output.
    """
    if not path.exists():
        return VariablesConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a YAML mapping at top level")
    return VariablesConfig(**data)


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


def format_variables_for_prompt(variables: list[ProjectVariable]) -> str:
    """Render a compact block downstream LLM prompts can read.

    Shape:

    ::

        PROJECT VARIABLES (NPC dialogue may reference these):
          - time_of_day (enum: dawn, morning, afternoon, dusk, night)
              default: morning
              description: Hour-bucket of the in-game clock.
          - disposition_mira (int, range 0-100)
              default: 50
              description: Mira's opinion of the player.
    """
    if not variables:
        return ""
    lines = ["PROJECT VARIABLES (NPC dialogue may reference these):"]
    for v in variables:
        type_note = v.type.value if isinstance(v.type, VariableType) else str(v.type)
        if v.type == VariableType.ENUM:
            type_note = f"enum: {', '.join(v.values)}"
        elif v.range is not None:
            type_note = f"{type_note}, range {v.range[0]}-{v.range[1]}"
        lines.append(f"  - {v.id} ({type_note})")
        lines.append(f"      default: {v.default!r}")
        if v.description:
            lines.append(f"      description: {v.description.strip()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Yarn emission
# ---------------------------------------------------------------------------


def yarn_literal(value: Any, var_type: VariableType | str) -> str:
    """Render a Python value as a Yarn Spinner 2 literal."""
    vt = VariableType(var_type) if isinstance(var_type, str) else var_type
    if vt == VariableType.BOOL:
        return "true" if bool(value) else "false"
    if vt in (VariableType.INT, VariableType.FLOAT):
        # Yarn accepts plain numeric literals.
        return str(value)
    # ENUM and STRING both go out as quoted strings.
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def yarn_declare_block(variables: list[ProjectVariable]) -> list[str]:
    """Return ``<<declare>>`` lines for the Start node (one per variable).

    Empty list when there are no variables. Callers insert these at the top
    of the Start node body, before any dialogue lines.
    """
    out: list[str] = []
    for v in variables:
        literal = yarn_literal(v.default, v.type)
        out.append(f"<<declare ${v.id} = {literal}>>")
    return out
