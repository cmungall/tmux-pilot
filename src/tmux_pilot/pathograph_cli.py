"""Command-line entry point for pathograph -> CX2 conversion."""

from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tp-pathograph-cx2",
        description="Convert dismech pathograph payloads to CX2 and optionally upload to NDEx",
    )
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="Convert a pathograph payload to CX2")
    convert.add_argument(
        "input",
        help="Input path or '-' for stdin. Supported formats: JSON payload or rendered HTML page.",
    )
    convert.add_argument(
        "-I",
        "--input-format",
        choices=("json", "html"),
        help="Input format. If omitted, infer from the input suffix.",
    )
    convert.add_argument(
        "-o",
        "--output",
        help="Write CX2 JSON to this file instead of stdout.",
    )
    convert.add_argument(
        "--name",
        help="Override the CX2 network name. Defaults to the input filename stem.",
    )
    convert.add_argument(
        "--dot-layout",
        action="store_true",
        help="Run Graphviz dot layout before writing/uploading the network.",
    )
    convert.add_argument(
        "--ndex-upload",
        action="store_true",
        help="Upload the converted CX2 to an NDEx-compatible server.",
    )
    convert.add_argument(
        "--ndex-host",
        help="NDEx host URL. Defaults to NDEX_HOST when set.",
    )
    convert.add_argument(
        "--ndex-username",
        help="NDEx username. Defaults to NDEX_USERNAME when set.",
    )
    convert.add_argument(
        "--ndex-password",
        help="NDEx password. Defaults to NDEX_PASSWORD when set.",
    )
    convert.add_argument(
        "--visibility",
        choices=("PRIVATE", "PUBLIC"),
        default="PRIVATE",
        help="Visibility for --ndex-upload (default: PRIVATE).",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "convert":
        try:
            _cmd_convert(args)
        except (ImportError, RuntimeError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()
    sys.exit(1)


def _cmd_convert(args: argparse.Namespace) -> None:
    from tmux_pilot.pathograph_cx2 import (
        extract_pathograph_from_html,
        pathograph_to_cx2,
        upload_cx2_to_ndex,
    )

    source_label = "stdin" if args.input == "-" else str(Path(args.input))
    input_format = _resolve_input_format(args.input, args.input_format)
    raw_text = _read_input(args.input)

    if input_format == "html":
        pathograph = extract_pathograph_from_html(raw_text)
    else:
        pathograph = json.loads(raw_text)

    network_name = args.name or _infer_network_name(args.input)
    cx2 = pathograph_to_cx2(
        pathograph,
        name=network_name,
        source=source_label,
        apply_dot_layout=args.dot_layout,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(cx2, indent=2) + "\n", encoding="utf-8")

    if args.ndex_upload:
        username = args.ndex_username or os.getenv("NDEX_USERNAME")
        password = args.ndex_password or os.getenv("NDEX_PASSWORD")
        host = args.ndex_host or os.getenv("NDEX_HOST")
        if not username or not password:
            raise RuntimeError(
                "NDEx upload requires credentials. Set NDEX_USERNAME/NDEX_PASSWORD "
                "or pass --ndex-username/--ndex-password."
            )
        url = upload_cx2_to_ndex(
            cx2,
            host=host,
            username=username,
            password=password,
            visibility=args.visibility,
        )
        print(url)
        return

    if not args.output:
        print(json.dumps(cx2, indent=2))


def _resolve_input_format(input_path: str, explicit_format: str | None) -> str:
    if explicit_format is not None:
        return explicit_format
    if input_path == "-":
        raise ValueError("--input-format is required when reading from stdin")
    suffix = Path(input_path).suffix.lower()
    if suffix in {".html", ".htm"}:
        return "html"
    return "json"


def _read_input(input_path: str) -> str:
    if input_path == "-":
        return sys.stdin.read()
    return Path(input_path).read_text(encoding="utf-8")


def _infer_network_name(input_path: str) -> str:
    if input_path == "-":
        return "Pathograph"
    stem = Path(input_path).stem
    if stem.lower().endswith(".pathograph"):
        stem = stem[: -len(".pathograph")]
    return stem.replace("_", " ").strip() or "Pathograph"


if __name__ == "__main__":
    main()
