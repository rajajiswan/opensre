"""Base tool infrastructure for opensre.

Defines the abstract Tool interface and registry that all integrations
must implement. Mirrors the contract described in .cursor/rules/tools.mdc.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Optional, Type

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Outcome of a single tool execution."""

    success: bool
    output: Any = None
    error: Optional[str] = None

    def __bool__(self) -> bool:  # noqa: D105
        return self.success


class Tool(abc.ABC):
    """Abstract base class every opensre tool must subclass.

    Subclasses are automatically registered in :data:`TOOL_REGISTRY` on
    definition, keyed by their :attr:`my_tool_name` class attribute.

    Example::

        class MyTool(Tool):
            my_tool_name = "my_tool"

            def is_available(self) -> bool:
                return True

            def extract_params(self, raw: Dict[str, Any]) -> Dict[str, Any]:
                return raw

            def run(self, **params: Any) -> ToolResult:
                return ToolResult(success=True, output="done")
    """

    #: Unique snake_case identifier for this tool (required by subclasses).
    my_tool_name: ClassVar[str]

    # ------------------------------------------------------------------
    # Registration hook
    # ------------------------------------------------------------------

    def __init_subclass__(cls, **kwargs: Any) -> None:  # noqa: D105
        super().__init_subclass__(**kwargs)
        name = getattr(cls, "my_tool_name", None)
        if name is not None:
            if name in TOOL_REGISTRY:
                logger.warning(
                    "Tool '%s' already registered; overwriting with %s", name, cls
                )
            TOOL_REGISTRY[name] = cls
            logger.debug("Registered tool: %s -> %s", name, cls)

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return *True* if the tool's dependencies / credentials are present."""

    @abc.abstractmethod
    def extract_params(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalise *raw* kwargs before passing them to :meth:`run`."""

    @abc.abstractmethod
    def run(self, **params: Any) -> ToolResult:
        """Execute the tool and return a :class:`ToolResult`."""

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def __call__(self, raw: Optional[Dict[str, Any]] = None, **kwargs: Any) -> ToolResult:
        """Validate availability, extract params, then run.

        Accepts either a single *raw* mapping or keyword arguments.
        """
        if not self.is_available():
            return ToolResult(
                success=False,
                error=f"Tool '{getattr(self, 'my_tool_name', type(self).__name__)}' is not available",
            )

        combined: Dict[str, Any] = {**(raw or {}), **kwargs}
        try:
            params = self.extract_params(combined)
        except (KeyError, ValueError, TypeError) as exc:
            return ToolResult(success=False, error=f"Parameter error: {exc}")

        try:
            return self.run(**params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Tool '%s' raised an unexpected error", getattr(self, "my_tool_name", ""))
            return ToolResult(success=False, error=str(exc))


#: Global registry mapping ``my_tool_name`` -> ``Tool`` subclass.
TOOL_REGISTRY: Dict[str, Type[Tool]] = {}


def get_tool(name: str) -> Type[Tool]:
    """Look up a registered tool class by name.

    Raises
    ------
    KeyError
        If no tool with *name* has been registered.
    """
    try:
        return TOOL_REGISTRY[name]
    except KeyError:
        available = ", ".join(sorted(TOOL_REGISTRY)) or "(none)"
        raise KeyError(
            f"Unknown tool '{name}'. Available tools: {available}"
        ) from None
