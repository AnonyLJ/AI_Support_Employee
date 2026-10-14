"""Tool abstraction.

A Tool is a name, a description, a JSON schema for its arguments and a Python
function. The agent loop knows nothing about invoices, CRMs or browsers - it
only sees a list of tools. Giving the worker a new capability means adding a
tool, not changing the loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


class ToolError(Exception):
    """An expected failure the model should see and react to (e.g. 'element e7 not found')."""


@dataclass
class ToolResult:
    text: str                                          # what the model sees
    ok: bool = True
    evidence: list[str] = field(default_factory=list)  # e.g. screenshot paths, for the report
    is_page: bool = False                              # page snapshots get shortened once they are old


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., ToolResult | str]
    # Returns a human-readable description if this particular call changes data
    # (used by --confirm-writes to ask the human first), else None.
    describe_write: Callable[[dict], str | None] | None = None

    def schema(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def params(properties: dict, required: list[str] | None = None) -> dict:
    """Small helper to build a JSON schema object."""
    return {"type": "object", "properties": properties,
            "required": required if required is not None else list(properties)}
