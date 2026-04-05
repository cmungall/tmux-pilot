"""CX2 visual styling for dismech pathographs.

The node shapes, fill colors, and border colors mirror the rendered dismech
pathograph widget so the CX2 output stays visually aligned with the source
artifact rather than inventing a new palette.
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_EDGE_STYLE_KEY = "default"
ORPHAN_EDGE_STYLE_KEY = "orphan"


@dataclass(frozen=True)
class EdgeStyle:
    line_color: str
    line_style: str
    arrow_color: str
    arrow_shape: str
    width: int


@dataclass(frozen=True)
class NodeStyle:
    fill_color: str
    border_color: str
    border_style: str
    shape: str


NODE_STYLES = {
    "pathophysiology": NodeStyle(
        fill_color="#dbeafe",
        border_color="#93c5fd",
        border_style="solid",
        shape="round-rectangle",
    ),
    "phenotype": NodeStyle(
        fill_color="#fef3c7",
        border_color="#fcd34d",
        border_style="solid",
        shape="ellipse",
    ),
    "environmental": NodeStyle(
        fill_color="#dcfce7",
        border_color="#86efac",
        border_style="solid",
        shape="diamond",
    ),
    "genetic": NodeStyle(
        fill_color="#f3e8ff",
        border_color="#c4b5fd",
        border_style="solid",
        shape="hexagon",
    ),
    "treatment": NodeStyle(
        fill_color="#fce7f3",
        border_color="#f9a8d4",
        border_style="solid",
        shape="rectangle",
    ),
    "biochemical": NodeStyle(
        fill_color="#e0e7ff",
        border_color="#a5b4fc",
        border_style="solid",
        shape="ellipse",
    ),
    "experimental_model": NodeStyle(
        fill_color="#ccfbf1",
        border_color="#14b8a6",
        border_style="solid",
        shape="round-rectangle",
    ),
    "orphan": NodeStyle(
        fill_color="#fee2e2",
        border_color="#dc2626",
        border_style="dashed",
        shape="round-rectangle",
    ),
    "unknown": NodeStyle(
        fill_color="#f3f4f6",
        border_color="#d1d5db",
        border_style="solid",
        shape="round-rectangle",
    ),
}

EDGE_STYLES = {
    DEFAULT_EDGE_STYLE_KEY: EdgeStyle(
        line_color="#9ca3af",
        line_style="solid",
        arrow_color="#9ca3af",
        arrow_shape="triangle",
        width=2,
    ),
    ORPHAN_EDGE_STYLE_KEY: EdgeStyle(
        line_color="#dc2626",
        line_style="dashed",
        arrow_color="#dc2626",
        arrow_shape="triangle",
        width=2,
    ),
}

VISUAL_PROPERTIES = {
    "default": {
        "edge": {
            "EDGE_CURVED": True,
            "EDGE_LABEL_AUTOROTATE": False,
            "EDGE_LABEL_COLOR": "#4b5563",
            "EDGE_LABEL_FONT_FACE": {
                "FONT_FAMILY": "sans-serif",
                "FONT_NAME": "Dialog",
                "FONT_STYLE": "normal",
                "FONT_WEIGHT": "normal",
            },
            "EDGE_LABEL_FONT_SIZE": 10,
            "EDGE_LABEL_MAX_WIDTH": 200,
            "EDGE_LABEL_OPACITY": 0,
            "EDGE_LINE_COLOR": "#9ca3af",
            "EDGE_LINE_STYLE": "solid",
            "EDGE_OPACITY": 1,
            "EDGE_SELECTED_PAINT": "#FFFF00",
            "EDGE_SOURCE_ARROW_SHAPE": "none",
            "EDGE_STACKING": "AUTO_BEND",
            "EDGE_STACKING_DENSITY": 0.5,
            "EDGE_TARGET_ARROW_COLOR": "#9ca3af",
            "EDGE_TARGET_ARROW_SHAPE": "triangle",
            "EDGE_TARGET_ARROW_SIZE": 8,
            "EDGE_VISIBILITY": "element",
            "EDGE_WIDTH": 2,
            "EDGE_Z_ORDER": 0,
        },
        "network": {"NETWORK_BACKGROUND_COLOR": "#FFFFFF"},
        "node": {
            "COMPOUND_NODE_PADDING": "10.0",
            "COMPOUND_NODE_SHAPE": "ROUND_RECTANGLE",
            "NODE_BACKGROUND_COLOR": "#FFFFFF",
            "NODE_BACKGROUND_OPACITY": 1,
            "NODE_BORDER_COLOR": "#d1d5db",
            "NODE_BORDER_OPACITY": 1,
            "NODE_BORDER_STYLE": "solid",
            "NODE_BORDER_WIDTH": 2,
            "NODE_HEIGHT": 44,
            "NODE_LABEL_BACKGROUND_SHAPE": "none",
            "NODE_LABEL_COLOR": "#1f2937",
            "NODE_LABEL_FONT_FACE": {
                "FONT_FAMILY": "sans-serif",
                "FONT_NAME": "SansSerif",
                "FONT_STYLE": "normal",
                "FONT_WEIGHT": "normal",
            },
            "NODE_LABEL_FONT_SIZE": 11,
            "NODE_LABEL_MAX_WIDTH": 196,
            "NODE_LABEL_OPACITY": 1,
            "NODE_LABEL_POSITION": {
                "HORIZONTAL_ALIGN": "center",
                "HORIZONTAL_ANCHOR": "center",
                "JUSTIFICATION": "center",
                "MARGIN_X": 0,
                "MARGIN_Y": 0,
                "VERTICAL_ALIGN": "center",
                "VERTICAL_ANCHOR": "center",
            },
            "NODE_SELECTED_PAINT": "#FFFF00",
            "NODE_SHAPE": "round-rectangle",
            "NODE_VISIBILITY": "element",
            "NODE_WIDTH": 160,
            "NODE_X_LOCATION": 0,
            "NODE_Y_LOCATION": 0,
            "NODE_Z_LOCATION": 0,
        },
    },
    "edgeMapping": {
        "EDGE_LINE_COLOR": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "style_key",
                "map": [
                    {"v": key, "vp": value.line_color}
                    for key, value in EDGE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "EDGE_LINE_STYLE": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "style_key",
                "map": [
                    {"v": key, "vp": value.line_style}
                    for key, value in EDGE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "EDGE_TARGET_ARROW_COLOR": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "style_key",
                "map": [
                    {"v": key, "vp": value.arrow_color}
                    for key, value in EDGE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "EDGE_TARGET_ARROW_SHAPE": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "style_key",
                "map": [
                    {"v": key, "vp": value.arrow_shape}
                    for key, value in EDGE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "EDGE_WIDTH": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "style_key",
                "map": [
                    {"v": key, "vp": value.width}
                    for key, value in EDGE_STYLES.items()
                ],
                "type": "integer",
            },
        },
    },
    "nodeMapping": {
        "NODE_BACKGROUND_COLOR": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "type",
                "map": [
                    {"v": key, "vp": value.fill_color}
                    for key, value in NODE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "NODE_BORDER_COLOR": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "type",
                "map": [
                    {"v": key, "vp": value.border_color}
                    for key, value in NODE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "NODE_BORDER_STYLE": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "type",
                "map": [
                    {"v": key, "vp": value.border_style}
                    for key, value in NODE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "NODE_HEIGHT": {
            "type": "PASSTHROUGH",
            "definition": {"attribute": "display_height", "type": "integer"},
        },
        "NODE_LABEL": {
            "type": "PASSTHROUGH",
            "definition": {"attribute": "name", "type": "string"},
        },
        "NODE_LABEL_MAX_WIDTH": {
            "type": "PASSTHROUGH",
            "definition": {"attribute": "label_max_width", "type": "integer"},
        },
        "NODE_SHAPE": {
            "type": "DISCRETE",
            "definition": {
                "attribute": "type",
                "map": [
                    {"v": key, "vp": value.shape}
                    for key, value in NODE_STYLES.items()
                ],
                "type": "string",
            },
        },
        "NODE_WIDTH": {
            "type": "PASSTHROUGH",
            "definition": {"attribute": "display_width", "type": "integer"},
        },
    },
}

VISUAL_EDITOR_PROPERTIES = {
    "properties": {
        "nodeSizeLocked": False,
        "arrowColorMatchesEdge": False,
        "nodeCustomGraphicsSizeSync": True,
    }
}
