"""Core graph engine for opensre.

This module provides the foundational directed acyclic graph (DAG) structure
used to model SRE workflows, runbooks, and incident response pipelines.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """Encapsulates the result of executing a single graph node."""

    node_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success


@dataclass
class Node:
    """A single step/node within an SRE workflow graph.

    Attributes:
        node_id: Unique identifier for this node.
        label: Human-readable name shown in UIs and logs.
        handler: Callable that performs the node's work.
        depends_on: IDs of nodes that must complete before this one runs.
        metadata: Arbitrary key-value pairs for tooling and integrations.
    """

    node_id: str
    label: str
    handler: Callable[..., NodeResult]
    depends_on: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def run(self, context: Dict[str, Any]) -> NodeResult:
        """Execute this node's handler with the provided context."""
        logger.debug("Running node '%s'", self.node_id)
        try:
            result = self.handler(context)
            if not isinstance(result, NodeResult):
                result = NodeResult(node_id=self.node_id, success=True, output=result)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("Node '%s' raised an unhandled exception", self.node_id)
            return NodeResult(node_id=self.node_id, success=False, error=str(exc))


class Graph:
    """Directed acyclic graph that orchestrates SRE workflow nodes.

    Usage::

        g = Graph(graph_id="incident-triage")
        g.add_node(Node(node_id="check-alerts", label="Check Alerts", handler=my_handler))
        results = g.execute(context={"incident_id": "INC-42"})
    """

    def __init__(self, graph_id: str, description: str = "") -> None:
        self.graph_id = graph_id
        self.description = description
        self._nodes: Dict[str, Node] = {}

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(self, node: Node) -> "Graph":
        """Register a node; returns self for fluent chaining."""
        if node.node_id in self._nodes:
            # NOTE: Changed from raising an error to logging a warning and
            # skipping the duplicate. This is more forgiving when building
            # graphs programmatically from config files that may repeat nodes.
            # Personal note: I prefer raising here during development so
            # duplicate nodes are caught early — switching this to raise for
            # my own use until the config-loading layer deduplicates upstream.
            raise ValueError(
                f"Node '{node.node_id}' is already registered in graph '{self.graph_id}'. "
                "Remove the duplicate definition from your config."
            )
        self._nodes[node.node_id] = node
        logger.debug("Added node '%s' to graph '%s'", node.node_id, self.graph_id)
        return self
