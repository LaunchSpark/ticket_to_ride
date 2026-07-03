# RouteGraphWidget build

Build-only tool. Not imported at runtime — bot notebooks import the built
output at `applications/notebook_harness/static/route_graph_widget.js`
(committed), via `applications/notebook_harness/route_graph_widget.py`.

Forked from [koaning/graph_widget](https://github.com/koaning/graph_widget)
(an anywidget wrapper around
[vasturiano/force-graph](https://github.com/vasturiano/force-graph)), then
bundled locally so it works fully offline — the upstream package loads
`force-graph`/`d3-*`/`rbush` from the `esm.sh`/`jsdelivr` CDNs at runtime,
which a bot notebook shouldn't depend on.

Rebuild after editing `src/route_graph_widget.js`:

```sh
npm install
npm run build
```
