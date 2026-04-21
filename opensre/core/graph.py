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
            raise ValueError(f"Duplicate node_id: '{node.node_id}'")
        self._nodes[node.node_id] = node
        logger.debug("Added node '%s' to graph '%s'", node.node_id, self.graph_id)
        return self

    def _validate(self) -> None:
        """Ensure all dependency references exist and the graph is acyclic."""
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    raise ValueError(
                        f"Node '{node.node_id}' depends on unknown node '{dep}'"
                    )
        # Simple cycle detection via DFS
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def _dfs(nid: str) -> None:
            visited.add(nid)
            rec_stack.add(nid)
            for dep in self._nodes[nid].depends_on:
                if dep not in visited:
                    _dfs(dep)
                elif dep in rec_stack:
                    raise ValueError(f"Cycle detected involving node '{dep}'")
            rec_stack.discard(nid)

        for nid in self._nodes:
            if nid not in visited:
                _dfs(nid)

    def _topological_order(self) -> List[str]:
        """Return node IDs in a valid execution order (Kahn's algorithm)."""
        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for node in self._nodes.values():
            for dep in node.depends_on:
                in_degree[node.node_id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        order: List[str] = []

        while queue:
            current = queue.pop(0)
            order.append(current)
            for node in self._nodes.values():
                if current in node.depends_on:
                    in_degree[node.node_id] -= 1
                    if in_degree[node.node_id] == 0:
                        queue.append(node.node_id)

        return order

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, NodeResult]:
        """Run all nodes in dependency order.

        Args:
            context: Shared mutable context passed to every node handler.

        Returns:
            Mapping of node_id -> NodeResult for every executed node.
        """
        self._validate()
        ctx: Dict[str, Any] = context or {}
        results: Dict[str, NodeResult] = {}

        for node_id in self._topological_order():
            node = self._nodes[node_id]
            # Skip node if any dependency failed
            failed_deps = [d for d in node.depends_on if not results.get(d, NodeResult(d, True))]
            if failed_deps:
                logger.warning(
                    "Skipping node '%s' — failed dependencies: %s", node_id, failed_deps
                )
                results[node_id] = NodeResult(
                    node_id=node_id,
                    success=False,
                    error=f"Skipped due to failed dependencies: {failed_deps}",
                )
                continue

            results[node_id] = node.run(ctx)

        return results
