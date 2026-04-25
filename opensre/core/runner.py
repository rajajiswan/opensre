"""Graph runner module for opensre.

Provides the GraphRunner class responsible for orchestrating
graph execution, managing tool invocations, and collecting results.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from opensre.core.graph import Graph, Node, NodeResult
from opensre.core.tools import Tool, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class RunContext:
    """Holds shared state across a single graph run."""

    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def set(self, key: str, value: Any) -> None:
        """Store a value in the shared output context."""
        self.outputs[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value from outputs, falling back to inputs."""
        return self.outputs.get(key, self.inputs.get(key, default))


@dataclass
class RunResult:
    """Aggregated result of a full graph run."""

    success: bool
    context: RunContext
    node_results: Dict[str, NodeResult] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def __bool__(self) -> bool:  # noqa: D105
        return self.success

    def summary(self) -> str:
        """Return a human-readable summary of the run."""
        status = "SUCCESS" if self.success else "FAILURE"
        errors = "; ".join(self.context.errors) if self.context.errors else "none"
        return (
            f"[{status}] duration={self.duration_seconds:.3f}s "
            f"nodes={len(self.node_results)} errors={errors}"
        )


class GraphRunner:
    """Executes a Graph, resolving tool availability and propagating context.

    Example usage::

        runner = GraphRunner(graph, tools=[my_tool])
        result = runner.run(inputs={"query": "disk usage"})
        if result:
            print(result.summary())
    """

    def __init__(
        self,
        graph: Graph,
        tools: Optional[List[Tool]] = None,
        max_retries: int = 1,
    ) -> None:
        self.graph = graph
        self.tools: Dict[str, Tool] = {t.my_tool_name: t for t in (tools or [])}
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, inputs: Optional[Dict[str, Any]] = None) -> RunResult:
        """Execute all nodes in the graph sequentially.

        Args:
            inputs: Initial key/value pairs made available to every node.

        Returns:
            A :class:`RunResult` describing the outcome.
        """
        ctx = RunContext(inputs=inputs or {})
        node_results: Dict[str, NodeResult] = {}
        start = time.monotonic()

        logger.info("Starting graph run: %s", self.graph.name)

        for node in self.graph.nodes:
            result = self._run_node(node, ctx)
            node_results[node.name] = result

            if not result:
                msg = f"Node '{node.name}' failed: {result.error}"
                logger.error(msg)
                ctx.errors.append(msg)

                if node.required:
                    logger.error("Required node failed — aborting run.")
                    return RunResult(
                        success=False,
                        context=ctx,
                        node_results=node_results,
                        duration_seconds=time.monotonic() - start,
                    )
            else:
                if result.output is not None:
                    ctx.set(node.name, result.output)

        duration = time.monotonic() - start
        success = not any(not r for r in node_results.values() if r is not None)
        logger.info("Graph run complete in %.3fs — %s", duration, "OK" if success else "ERRORS")

        return RunResult(
            success=success,
            context=ctx,
            node_results=node_results,
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_node(self, node: Node, ctx: RunContext) -> NodeResult:
        """Run a single node, retrying up to *max_retries* times on failure."""
        last_result: Optional[NodeResult] = None

        for attempt in range(1, self.max_retries + 2):
            try:
                tool = self.tools.get(node.tool_name)
                if tool is None:
                    return NodeResult(
                        success=False,
                        error=f"Tool '{node.tool_name}' not registered with runner",
                    )

                if not tool.is_available():
                    return NodeResult(
                        success=False,
                        error=f"Tool '{node.tool_name}' reports unavailable",
                    )

                params = node.resolve_params(ctx.outputs | ctx.inputs)
                tool_result: ToolResult = tool.run(params)

                last_result = NodeResult(
                    success=tool_result.success,
                    output=tool_result.data,
                    error=tool_result.error,
                )

                if last_result:
                    return last_result

                logger.warning(
                    "Node '%s' attempt %d/%d failed: %s",
                    node.name,
                    attempt,
                    self.max_retries + 1,
                    last_result.error,
                )

            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected error in node '%s': %s", node.name, exc)
                last_result = NodeResult(success=False, error=str(exc))

        return last_result or NodeResult(success=False, error="Unknown runner error")
