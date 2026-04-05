# Convert Pathographs To CX2

`tmux-pilot` now ships an optional `tp-pathograph-cx2` utility for turning
dismech-style pathograph payloads into NDEx-ready CX2.

Install the extra first:

```bash
pip install "tmux-pilot[pathograph]"
```

Convert a raw pathograph JSON payload:

```bash
tp-pathograph-cx2 convert examples/pathographs/linked_pathograph.json -o linked_pathograph.cx2
```

Convert the `graphData` payload embedded in a rendered disorder HTML page:

```bash
tp-pathograph-cx2 convert /path/to/Crohn_Disease.html --input-format html -o Crohn_Disease.cx2
```

Upload directly to an NDEx or IndexBio host:

```bash
export NDEX_HOST="https://your-ndex-host.example.org"
export NDEX_USERNAME="your-username"
export NDEX_PASSWORD="your-password"

tp-pathograph-cx2 convert \
  examples/pathographs/linked_pathograph.json \
  --ndex-upload \
  --visibility PRIVATE
```

Useful flags:

- `--name`: override the network name
- `--dot-layout`: run Graphviz `dot` before serialization
- `--output`: write the CX2 JSON to a file
- `--ndex-host`, `--ndex-username`, `--ndex-password`: override the matching environment variables

The converter mirrors the local GO-CAM CX2 pipeline pattern:

- builds the network with `ndex2.cx2.CX2Network`
- preserves node/edge attributes for NDEx inspection
- applies CX2 visual properties so node shapes/colors match the dismech pathograph widget
- marks uploads searchable with `index_level=META`
