# Viewer App

This is a first-party support app owned by the native project.

The viewer is kept outside `src/ticket_to_ride/` because it is an app surface rather than a Python import package, but it is still part of the native repo and not an external integration.

The active first-party viewer is organized around a small app shell:

- `index.html`: browser entry document
- `app.jsx`: mount entrypoint
- `components/replay-app.jsx`: native React replay UI
- `components/viewer-shell.css`: native viewer styling

Inside `components/`, the viewer is intentionally split into atomic first-party layers:

- `atoms/`: small reusable UI building blocks
- `layout/`: shell chrome like the top bar and navigation rail
- `panels/`: replay surface panels
- `dashboard/`: top-level dashboard composition
- `model/` and `services/`: replay derivation and data-loading helpers

The live viewer does not depend on `example_webpage/`. The `legacy/` folder remains only as archival/reference material and is not part of the active runtime path.

## Vite Dev Server

The viewer now includes a minimal Vite setup for frontend development in this folder.

- Install deps in `apps/viewer/` with `npm install`
- Start the dev server with `npm run dev`
- File watching is configured with polling in [`vite.config.js`](C:/Users/Lucas/OneDrive/Desktop/dataclass/ticket_to_ride/apps/viewer/vite.config.js)

Polling defaults to `300ms`. To override it, set `VITE_POLLING_INTERVAL_MS`.
