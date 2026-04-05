"""Translate dismech pathograph payloads to CX2."""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .style import (
    DEFAULT_EDGE_STYLE_KEY,
    ORPHAN_EDGE_STYLE_KEY,
    VISUAL_EDITOR_PROPERTIES,
    VISUAL_PROPERTIES,
)


_GRAPH_DATA_PATTERN = re.compile(r"var graphData = JSON\.parse\((\".*?\")\);", re.S)


def extract_pathograph_from_html(html: str) -> dict[str, Any]:
    """Extract the embedded pathograph JSON payload from a rendered dismech page."""
    match = _GRAPH_DATA_PATTERN.search(html)
    if match is None:
        raise ValueError("Rendered HTML did not include an embedded graphData payload")
    return _validate_pathograph_payload(json.loads(json.loads(match.group(1))))


def pathograph_to_cx2(
    pathograph: Mapping[str, Any],
    *,
    name: str,
    source: str | None = None,
    apply_dot_layout: bool = False,
) -> list[dict[str, Any]]:
    """Convert a pathograph payload into CX2 suitable for NDEx upload."""
    payload = _validate_pathograph_payload(pathograph)

    try:
        from ndex2.cx2 import CX2Network  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "ndex2 is required for pathograph CX2 conversion. "
            "Install with: pip install 'tmux-pilot[pathograph]'"
        ) from exc

    cx2_network = CX2Network()
    cx2_network.set_network_attributes(
        {
            "name": name,
            "description": _build_network_description(
                name=name,
                source=source,
                node_count=len(payload["nodes"]),
                edge_count=len(payload["edges"]),
            ),
            "source_input": source or "",
            "network_type": "pathograph",
        }
    )
    cx2_network.add_network_attribute("labels", [name, "pathograph"], "list_of_string")
    cx2_network.add_network_attribute(
        "node_count", len(payload["nodes"]), "integer"
    )
    cx2_network.add_network_attribute(
        "edge_count", len(payload["edges"]), "integer"
    )

    node_ids: dict[str, int] = {}
    for node in payload["nodes"]:
        node_name = _require_str(node, "id", owner="node")
        width, height, label_max_width = _compute_display_dimensions(node_name)
        node_attributes = {
            "name": node_name,
            "represents": _infer_node_represents(node),
            "type": _normalize_node_type(node.get("node_type")),
            "display_width": width,
            "display_height": height,
            "label_max_width": label_max_width,
            "is_orphan": bool(node.get("is_orphan", False)),
        }
        description = node.get("description")
        if isinstance(description, str) and description.strip():
            node_attributes["description"] = description.strip()
        node_attributes.update(_flatten_node_metadata(node.get("meta")))
        node_ids[node_name] = cx2_network.add_node(attributes=node_attributes)

    missing_targets = {
        endpoint
        for edge in payload["edges"]
        for endpoint in (_require_str(edge, "source", owner="edge"), _require_str(edge, "target", owner="edge"))
        if endpoint not in node_ids
    }
    if missing_targets:
        missing = ", ".join(sorted(missing_targets))
        raise ValueError(f"Pathograph edge references missing node(s): {missing}")

    for edge in payload["edges"]:
        predicate = _require_str(edge, "predicate", owner="edge")
        style_key = (
            ORPHAN_EDGE_STYLE_KEY if bool(edge.get("is_orphan", False)) else DEFAULT_EDGE_STYLE_KEY
        )
        edge_attributes = {
            "name": _humanize_token(predicate),
            "predicate": predicate,
            "represents": predicate,
            "style_key": style_key,
            "is_orphan": bool(edge.get("is_orphan", False)),
        }
        cx2_network.add_edge(
            source=node_ids[_require_str(edge, "source", owner="edge")],
            target=node_ids[_require_str(edge, "target", owner="edge")],
            attributes=edge_attributes,
        )

    cx2_network.set_visual_properties(VISUAL_PROPERTIES)
    cx2_network.set_opaque_aspect("visualEditorProperties", [VISUAL_EDITOR_PROPERTIES])

    if apply_dot_layout:
        _apply_dot_layout(cx2_network)

    return cx2_network.to_cx2()


def upload_cx2_to_ndex(
    cx2: list[dict[str, Any]],
    *,
    host: str | None = None,
    username: str,
    password: str,
    visibility: str = "PRIVATE",
) -> str:
    """Upload CX2 to an NDEx-compatible server and make it searchable."""
    ndex2 = importlib.import_module("ndex2")
    client = ndex2.client.Ndex2(host=host, username=username, password=password)
    url = client.save_new_cx2_network(cx2, visibility=visibility)
    network_id = url.rstrip("/").rsplit("/", 1)[-1]
    client.set_network_system_properties(network_id, {"index_level": "META"})
    return url


def _apply_dot_layout(cx2_network: Any) -> None:
    """Apply a Graphviz dot layout to the CX2 network in place."""
    try:
        import networkx as nx  # type: ignore[import-untyped]
        from ndex2.cx2 import CX2NetworkXFactory  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "networkx and ndex2 are required for --dot-layout. "
            "Install with: pip install 'tmux-pilot[pathograph]'"
        ) from exc

    networkx_graph = CX2NetworkXFactory().get_graph(cx2_network)

    networkx_graph.graph.clear()
    for node_id in networkx_graph.nodes:
        networkx_graph.nodes[node_id].clear()
    for edge_id in networkx_graph.edges:
        networkx_graph.edges[edge_id].clear()

    layout = nx.nx_pydot.pydot_layout(networkx_graph, prog="dot")
    max_x = max(position[0] for position in layout.values())
    max_y = max(position[1] for position in layout.values())

    for node_id, position in layout.items():
        cx2_network.get_node(node_id)["x"] = (max_x - position[0]) * 2.0
        cx2_network.get_node(node_id)["y"] = (max_y - position[1]) * 1.5


def _build_network_description(
    *,
    name: str,
    source: str | None,
    node_count: int,
    edge_count: int,
) -> str:
    details = [
        f"<p>Converted pathograph for <strong>{_escape_html(name)}</strong>.</p>",
        f"<p>Nodes: {node_count}. Edges: {edge_count}.</p>",
    ]
    if source:
        details.append(f"<p>Source input: <code>{_escape_html(source)}</code></p>")
    return "".join(details)


def _validate_pathograph_payload(pathograph: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(pathograph, Mapping):
        raise ValueError("Pathograph payload must be a JSON object")

    nodes = pathograph.get("nodes")
    edges = pathograph.get("edges")
    if not isinstance(nodes, list):
        raise ValueError("Pathograph payload must contain a 'nodes' list")
    if not isinstance(edges, list):
        raise ValueError("Pathograph payload must contain an 'edges' list")

    normalized_nodes = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise ValueError(f"Node at index {index} must be an object")
        normalized_nodes.append(dict(node))

    normalized_edges = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            raise ValueError(f"Edge at index {index} must be an object")
        normalized_edges.append(dict(edge))

    orphan_targets = pathograph.get("orphan_targets")
    if orphan_targets is None:
        orphan_targets = []
    elif not isinstance(orphan_targets, list):
        raise ValueError("Pathograph payload 'orphan_targets' must be a list when present")

    return {
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "orphan_targets": list(orphan_targets),
    }


def _compute_display_dimensions(label: str) -> tuple[int, int, int]:
    width = max(120, min(220, len(label) * 8 + 30))
    height = 44
    label_max_width = max(96, width - 24)
    return width, height, label_max_width


def _flatten_node_metadata(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, Mapping):
        return {}

    flattened: dict[str, Any] = {}
    for key, value in meta.items():
        if value in (None, "", [], {}):
            continue
        attr_name = _humanize_key(key)
        formatted = _format_metadata_value(key, value)
        if formatted not in (None, "", [], {}):
            flattened[attr_name] = formatted
    return flattened


def _format_metadata_value(key: str, value: Any) -> Any:
    if isinstance(value, list):
        if all(isinstance(item, (str, int, float, bool)) for item in value):
            return [str(item) for item in value]
        if key == "experimental_models":
            return _format_named_metadata_list(value)
        if key == "pdb_structures":
            return _format_pdb_structures(value)
        return json.dumps(value, sort_keys=True)
    if isinstance(value, Mapping):
        return json.dumps(value, sort_keys=True)
    return value


def _format_named_metadata_list(items: list[Any]) -> str:
    entries: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", "")).strip()
        parts = [name] if name else []
        for key in ("model_type", "namo_type", "description"):
            raw_value = item.get(key)
            if raw_value in (None, ""):
                continue
            parts.append(f"{_humanize_key(key)}: {raw_value}")
        if parts:
            entries.append(f"<li>{_escape_html('; '.join(parts))}</li>")
    return f"<ul>{''.join(entries)}</ul>" if entries else ""


def _format_pdb_structures(items: list[Any]) -> str:
    entries: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        pdb_id = str(item.get("pdb_id", "")).strip()
        if not pdb_id:
            continue
        parts = [f"PDB {pdb_id}"]
        for key in (
            "description",
            "resolution_angstrom",
            "method",
            "ligand",
            "target_protein",
        ):
            raw_value = item.get(key)
            if raw_value in (None, ""):
                continue
            parts.append(f"{_humanize_key(key)}: {raw_value}")
        entries.append(f"<li>{_escape_html('; '.join(parts))}</li>")
    return f"<ul>{''.join(entries)}</ul>" if entries else ""


def _infer_node_represents(node: Mapping[str, Any]) -> str:
    meta = node.get("meta")
    if isinstance(meta, Mapping):
        for key in ("term_id", "namo_type"):
            raw_value = meta.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return raw_value.strip()
    return _require_str(node, "id", owner="node")


def _normalize_node_type(raw_value: Any) -> str:
    if not isinstance(raw_value, str) or not raw_value.strip():
        return "unknown"
    node_type = raw_value.strip()
    return node_type


def _humanize_key(key: str) -> str:
    return " ".join(part.capitalize() if part else part for part in key.split("_"))


def _humanize_token(token: str) -> str:
    return token.replace("_", " ")


def _require_str(obj: Mapping[str, Any], key: str, *, owner: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} is missing required string field '{key}'")
    return value.strip()


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
