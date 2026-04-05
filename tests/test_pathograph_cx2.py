"""Tests for pathograph -> CX2 conversion."""

from __future__ import annotations

import json
import sys
import types

from pathlib import Path

from ndex2.cx2 import CX2Network, RawCX2NetworkFactory

from tmux_pilot.pathograph_cx2 import extract_pathograph_from_html, pathograph_to_cx2
from tmux_pilot.pathograph_cx2.main import upload_cx2_to_ndex


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pathograph"


def _load_pathograph_payload() -> dict:
    return json.loads((FIXTURE_DIR / "sample_pathograph.json").read_text(encoding="utf-8"))


def test_extract_pathograph_from_html():
    html = (FIXTURE_DIR / "sample_pathograph.html").read_text(encoding="utf-8")

    payload = extract_pathograph_from_html(html)

    assert len(payload["nodes"]) == 7
    assert len(payload["edges"]) == 6
    assert payload["orphan_targets"] == ["Mucus plugging"]


def test_pathograph_to_cx2_round_trips_through_ndex_factory():
    cx2 = pathograph_to_cx2(
        _load_pathograph_payload(),
        name="Cystic Fibrosis Pathograph",
        source="tests/fixtures/pathograph/sample_pathograph.json",
    )

    factory = RawCX2NetworkFactory()
    cx2_network = factory.get_cx2network(cx2)

    assert isinstance(cx2_network, CX2Network)
    assert len(cx2_network.get_nodes()) == 7
    assert len(cx2_network.get_edges()) == 6
    assert cx2_network.get_network_attributes()["name"] == "Cystic Fibrosis Pathograph"


def test_pathograph_to_cx2_sets_expected_node_and_edge_attributes():
    cx2 = pathograph_to_cx2(_load_pathograph_payload(), name="Cystic Fibrosis Pathograph")

    node_aspect = next(aspect["nodes"] for aspect in cx2 if "nodes" in aspect)
    edge_aspect = next(aspect["edges"] for aspect in cx2 if "edges" in aspect)

    node_by_name = {node["v"]["name"]: node["v"] for node in node_aspect}
    edge_by_predicate = {edge["v"]["predicate"]: edge["v"] for edge in edge_aspect}

    bronchiectasis = node_by_name["Bronchiectasis"]
    assert bronchiectasis["type"] == "phenotype"
    assert bronchiectasis["represents"] == "HP:0002110"
    assert bronchiectasis["Frequency"] == "FREQUENT"

    cftr_dysfunction = node_by_name["CFTR Dysfunction"]
    assert cftr_dysfunction["type"] == "pathophysiology"
    assert cftr_dysfunction["Genes"] == ["CFTR"]
    assert "Patient-derived airway organoid" in cftr_dysfunction["Experimental Models"]
    assert cftr_dysfunction["display_width"] >= 120

    mucus_plugging = node_by_name["Mucus plugging"]
    assert mucus_plugging["type"] == "orphan"
    assert mucus_plugging["is_orphan"] is True

    assert edge_by_predicate["leads_to"]["style_key"] == "orphan"
    assert edge_by_predicate["contributes_to"]["name"] == "contributes to"


def test_pathograph_to_cx2_includes_pathograph_visual_mappings():
    cx2 = pathograph_to_cx2(_load_pathograph_payload(), name="Cystic Fibrosis Pathograph")

    visual_properties = next(
        aspect["visualProperties"][0] for aspect in cx2 if "visualProperties" in aspect
    )

    node_shape_map = next(
        mapping["definition"]["map"]
        for key, mapping in visual_properties["nodeMapping"].items()
        if key == "NODE_SHAPE"
    )
    edge_style_map = next(
        mapping["definition"]["map"]
        for key, mapping in visual_properties["edgeMapping"].items()
        if key == "EDGE_LINE_STYLE"
    )

    assert {"v": "genetic", "vp": "hexagon"} in node_shape_map
    assert {"v": "treatment", "vp": "rectangle"} in node_shape_map
    assert {"v": "orphan", "vp": "dashed"} in edge_style_map


def test_upload_cx2_to_ndex_uses_save_and_meta_index(monkeypatch):
    calls: list[tuple[str, object]] = []

    class FakeNdexClient:
        def __init__(self, *, host, username, password):
            calls.append(("init", {"host": host, "username": username, "password": password}))

        def save_new_cx2_network(self, cx2, visibility="PRIVATE"):
            calls.append(("save", {"cx2": cx2, "visibility": visibility}))
            return "https://indexbio.example.org/viewer/networks/test-network"

        def set_network_system_properties(self, network_id, properties):
            calls.append(("properties", {"network_id": network_id, "properties": properties}))

    fake_ndex2 = types.SimpleNamespace(client=types.SimpleNamespace(Ndex2=FakeNdexClient))
    monkeypatch.setitem(sys.modules, "ndex2", fake_ndex2)

    url = upload_cx2_to_ndex(
        [{"metaData": [{"name": "nodes"}]}],
        host="https://indexbio.example.org",
        username="alice",
        password="secret",
        visibility="PUBLIC",
    )

    assert url == "https://indexbio.example.org/viewer/networks/test-network"
    assert calls == [
        ("init", {"host": "https://indexbio.example.org", "username": "alice", "password": "secret"}),
        ("save", {"cx2": [{"metaData": [{"name": "nodes"}]}], "visibility": "PUBLIC"}),
        ("properties", {"network_id": "test-network", "properties": {"index_level": "META"}}),
    ]
