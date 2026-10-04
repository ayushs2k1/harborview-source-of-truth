"""The pipeline specification.

Spec section 8 of the principles: the graph UI is a view of the config, not where the
logic lives. This loads that config, checks it, and hands the canvas something it can
draw.

Checking matters more than it looks. A graph that is wrong is wrong before any data
moves - an edge between incompatible steps, a step nobody feeds, a cycle - and all
three are cheaper to catch at load than to debug halfway through a run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Port types. A step that produces one can feed a step that consumes it, and nothing
#: else. Named after what flows rather than after the step, because the same shape
#: comes out of a nursing rota and a trucking dispatch file.
PORTS = frozenset(
    {"RawTable", "StdTable", "Links", "Claims", "Golden", "MatchTables", "View", "Flags"}
)

#: What each kind of step is allowed to consume and produce.
NODE_TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "source": (frozenset(), frozenset({"RawTable"})),
    "standardize": (frozenset({"RawTable"}), frozenset({"StdTable"})),
    "resolve": (frozenset({"StdTable"}), frozenset({"Links"})),
    "ledger": (frozenset({"StdTable", "Links"}), frozenset({"Claims", "Golden"})),
    "match": (frozenset({"Golden", "StdTable", "Claims"}), frozenset({"MatchTables"})),
    "view": (frozenset({"MatchTables", "Golden", "StdTable", "View"}), frozenset({"View"})),
    "rules": (
        frozenset({"Golden", "MatchTables", "View", "Claims", "Links", "StdTable"}),
        frozenset({"Flags"}),
    ),
}


class PipelineError(ValueError):
    """A pipeline specification that cannot be run."""


@dataclass(frozen=True)
class Node:
    """One step in the graph."""

    id: str
    type: str
    label: str = ""
    description: str = ""
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    optional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label or self.id,
            "description": self.description,
            "consumes": list(self.consumes),
            "produces": list(self.produces),
            "optional": self.optional,
        }


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    #: The port type actually flowing, resolved at validation.
    port: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "port": self.port}


@dataclass
class PipelineSpec:
    """A validated graph."""

    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    version: int = 1
    path: Path | None = None

    @property
    def by_id(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    def order(self) -> list[str]:
        """Topological order. The order the executor runs steps in."""
        return _topological(self.nodes, self.edges)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": [node.as_dict() for node in self.nodes],
            "edges": [edge.as_dict() for edge in self.edges],
            "order": self.order(),
        }


def load_pipeline(path: str | Path) -> PipelineSpec:
    """Read and validate a pipeline file."""
    source = Path(path)
    if not source.is_file():
        raise PipelineError(f"no pipeline specification at {source}")
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}

    nodes = [
        Node(
            id=str(item["id"]),
            type=str(item.get("type", "")),
            label=str(item.get("label", "")),
            description=str(item.get("description", "")),
            consumes=tuple(str(port) for port in item.get("consumes", ())),
            produces=tuple(str(port) for port in item.get("produces", ())),
            optional=bool(item.get("optional", False)),
        )
        for item in data.get("nodes", [])
    ]
    edges = [
        Edge(source=str(pair[0]), target=str(pair[1]))
        for pair in data.get("edges", [])
        if len(pair) >= 2
    ]
    spec = PipelineSpec(nodes=nodes, edges=edges, version=int(data.get("version", 1)), path=source)
    validate(spec)
    return spec


def validate(spec: PipelineSpec) -> PipelineSpec:
    """Refuse a graph that cannot be run, naming what is wrong.

    Every message says which node or edge, because a pipeline file is edited by hand
    and "invalid configuration" is not a thing anybody can act on.
    """
    by_id = spec.by_id
    if len(by_id) != len(spec.nodes):
        duplicates = sorted({node.id for node in spec.nodes if list(spec.nodes).count(node) > 1})
        raise PipelineError(f"duplicate node ids: {duplicates}")

    for node in spec.nodes:
        if node.type not in NODE_TYPES:
            raise PipelineError(
                f"node {node.id!r} has unknown type {node.type!r}; "
                f"expected one of {sorted(NODE_TYPES)}"
            )
        allowed_in, allowed_out = NODE_TYPES[node.type]
        for port in node.consumes:
            if port not in PORTS:
                raise PipelineError(f"node {node.id!r} consumes unknown port {port!r}")
            if port not in allowed_in:
                raise PipelineError(
                    f"node {node.id!r} is a {node.type} step and cannot consume {port!r}"
                )
        for port in node.produces:
            if port not in PORTS:
                raise PipelineError(f"node {node.id!r} produces unknown port {port!r}")
            if port not in allowed_out:
                raise PipelineError(
                    f"node {node.id!r} is a {node.type} step and cannot produce {port!r}"
                )

    resolved: list[Edge] = []
    for edge in spec.edges:
        if edge.source not in by_id:
            raise PipelineError(f"edge from unknown node {edge.source!r}")
        if edge.target not in by_id:
            raise PipelineError(f"edge to unknown node {edge.target!r}")
        produced = set(by_id[edge.source].produces)
        consumed = set(by_id[edge.target].consumes)
        shared = sorted(produced & consumed)
        if not shared:
            raise PipelineError(
                f"{edge.source!r} produces {sorted(produced)} and {edge.target!r} consumes "
                f"{sorted(consumed)}; nothing can flow between them"
            )
        resolved.append(Edge(edge.source, edge.target, shared[0]))
    spec.edges = resolved

    _topological(spec.nodes, spec.edges)
    return spec


def _topological(nodes: Sequence[Node], edges: Iterable[Edge]) -> list[str]:
    """Run order, or a readable error naming the cycle."""
    incoming: dict[str, set[str]] = {node.id: set() for node in nodes}
    outgoing: dict[str, set[str]] = {node.id: set() for node in nodes}
    for edge in edges:
        incoming[edge.target].add(edge.source)
        outgoing[edge.source].add(edge.target)

    # Sorted at every step, so the order is the same on every machine and every run.
    ready = sorted(node.id for node in nodes if not incoming[node.id])
    order: list[str] = []
    remaining = {node: set(sources) for node, sources in incoming.items()}

    while ready:
        current = ready.pop(0)
        order.append(current)
        for target in sorted(outgoing[current]):
            remaining[target].discard(current)
            if not remaining[target] and target not in order and target not in ready:
                ready.append(target)
                ready.sort()

    if len(order) != len(nodes):
        stuck = sorted(set(incoming) - set(order))
        raise PipelineError(f"the pipeline has a cycle involving {stuck}")
    return order


def pipeline_for_pack(pack: Any) -> PipelineSpec:
    """Load the pipeline sitting beside a pack's manifest."""
    return load_pipeline(Path(pack.path) / "pipeline.yaml")


def with_stats(spec: PipelineSpec, stats: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The graph plus the latest run's numbers, which is what the canvas draws."""
    payload = spec.as_dict()
    for node in payload["nodes"]:
        node["stats"] = dict(stats.get(node["id"], {}))
    for edge in payload["edges"]:
        source_stats = stats.get(edge["source"], {})
        edge["rows"] = source_stats.get("rows_out")
    return payload
