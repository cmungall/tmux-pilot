# Pathograph Examples

`linked_pathograph.json` mirrors the current dismech pathograph payload shape:

- `nodes[].id`
- `nodes[].node_type`
- `nodes[].color`
- `nodes[].is_orphan`
- optional `nodes[].description`
- optional `nodes[].meta`
- `edges[].source`
- `edges[].target`
- `edges[].predicate`
- `edges[].is_orphan`

Convert it to CX2:

```bash
tp-pathograph-cx2 convert examples/pathographs/linked_pathograph.json -o linked_pathograph.cx2
```

Upload directly to an NDEx-compatible host:

```bash
export NDEX_HOST="https://indexbio.example.org"
export NDEX_USERNAME="your-username"
export NDEX_PASSWORD="your-password"

tp-pathograph-cx2 convert examples/pathographs/linked_pathograph.json --ndex-upload
```
