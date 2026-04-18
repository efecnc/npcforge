"""Engine adapters — per-engine filesystem + sync conventions.

Use :func:`get_adapter` to resolve an engine name to its
:class:`~npcforge.engines.base.EngineAdapter` implementation. The
``engine_sync`` tool and CLI dispatch through this registry.

Adding a new engine:
    1. Create ``<engine>.py`` alongside ``unity.py`` / ``godot.py`` /
       ``unreal.py`` with a subclass of
       :class:`~npcforge.engines.base.EngineAdapter`.
    2. Add a single entry to :data:`_REGISTRY` below.
    3. Update the ``engine`` literal in
       :class:`~npcforge.tools.EngineSyncInput` so the MCP tool and CLI
       expose it.
"""

from __future__ import annotations

from .base import EngineAdapter, SyncAction, SyncMarker, SyncResult, marker_path_for
from .godot import GodotAdapter
from .unity import UnityAdapter
from .unreal import UnrealAdapter


_REGISTRY: dict[str, EngineAdapter] = {
    "unity": UnityAdapter(),
    "godot": GodotAdapter(),
    "unreal": UnrealAdapter(),
}


def supported_engines() -> list[str]:
    """Return the list of engine identifiers ``engine_sync`` accepts."""
    return sorted(_REGISTRY.keys())


def get_adapter(engine: str) -> EngineAdapter:
    """Resolve an engine name to its adapter instance."""
    try:
        return _REGISTRY[engine]
    except KeyError as exc:
        raise ValueError(
            f"Unknown engine {engine!r}. Supported: {', '.join(supported_engines())}"
        ) from exc


__all__ = [
    "EngineAdapter",
    "SyncAction",
    "SyncMarker",
    "SyncResult",
    "UnityAdapter",
    "GodotAdapter",
    "UnrealAdapter",
    "get_adapter",
    "marker_path_for",
    "supported_engines",
]
