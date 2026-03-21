from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ViewerShellTests(unittest.TestCase):
    def test_viewer_shell_uses_module_entrypoint(self) -> None:
        html = (REPO_ROOT / "apps" / "viewer" / "index.html").read_text(encoding="utf-8")
        app_jsx = (REPO_ROOT / "apps" / "viewer" / "app.jsx").read_text(encoding="utf-8")
        replay_app = (REPO_ROOT / "apps" / "viewer" / "components" / "replay-app.jsx").read_text(encoding="utf-8")
        replay_dashboard = (
            REPO_ROOT / "apps" / "viewer" / "components" / "dashboard" / "ReplayDashboard.jsx"
        ).read_text(encoding="utf-8")
        sidebar = (
            REPO_ROOT / "apps" / "viewer" / "components" / "layout" / "Sidebar.jsx"
        ).read_text(encoding="utf-8")
        map_routes_panel = (
            REPO_ROOT / "apps" / "viewer" / "components" / "panels" / "MapRoutesPanel.jsx"
        ).read_text(encoding="utf-8")
        match_sidebar_panel = (
            REPO_ROOT / "apps" / "viewer" / "components" / "panels" / "MatchSidebarPanel.jsx"
        ).read_text(encoding="utf-8")
        replay_model = (
            REPO_ROOT / "apps" / "viewer" / "components" / "model" / "replay-model.jsx"
        ).read_text(encoding="utf-8")
        constants = (
            REPO_ROOT / "apps" / "viewer" / "components" / "constants.jsx"
        ).read_text(encoding="utf-8")
        route_service = (
            REPO_ROOT / "apps" / "viewer" / "components" / "services" / "route-svg.jsx"
        ).read_text(encoding="utf-8")

        self.assertIn('<div id="root"></div>', html)
        self.assertIn('type="module" src="app.jsx"', html)
        self.assertIn('href="components/viewer-shell.css"', html)
        self.assertIn("Space+Grotesk", html)
        self.assertIn("Manrope", html)
        self.assertIn("Material+Symbols+Outlined", html)
        self.assertIn("mountReplayApp", app_jsx)
        self.assertIn('./components/replay-app.jsx', app_jsx)
        self.assertIn('from "./dashboard/ReplayDashboard.jsx"', replay_app)
        self.assertIn('from "./layout/Sidebar.jsx"', replay_app)
        self.assertIn("ReplayDashboard", replay_dashboard)
        self.assertIn("MapRoutesPanel", replay_dashboard)
        self.assertIn("MatchSidebarPanel", replay_dashboard)
        self.assertIn("DestinationTicketsPanel", replay_dashboard)
        self.assertIn("ShellNavItem", sidebar)
        self.assertIn("RouteOverlay", map_routes_panel)
        self.assertIn("PlaybackButton", match_sidebar_panel)
        self.assertIn("top-app-bar__counter", match_sidebar_panel)
        self.assertIn("img/train_car_img/red.png", constants)
        self.assertIn('red: "img/train_car_img/red.png"', constants)
        self.assertIn("resolveTrainCardImage", constants)
        self.assertIn("resolveTrainCardImage(cardCode)", replay_model)
        self.assertIn('ROUTE_SVG_PATH = "img/export route.svg"', constants)
        self.assertNotIn('fetch("legacy/index.html")', route_service)
        self.assertNotIn("img/market/market-red.png", constants)
        self.assertNotIn("img/current-red-train-car-card.png", constants)

    def test_active_viewer_component_imports_do_not_reference_js_modules(self) -> None:
        viewer_root = REPO_ROOT / "apps" / "viewer"

        for source_path in viewer_root.rglob("*.jsx"):
            source_text = source_path.read_text(encoding="utf-8")
            self.assertNotIn('.js"', source_text, msg=f"stale .js import in {source_path}")
            self.assertNotIn(".js'", source_text, msg=f"stale .js import in {source_path}")

    def test_active_viewer_readme_documents_first_party_structure(self) -> None:
        viewer_readme = (REPO_ROOT / "apps" / "viewer" / "README.md").read_text(encoding="utf-8")

        self.assertIn("components/replay-app.jsx", viewer_readme)
        self.assertIn("app.jsx", viewer_readme)
        self.assertIn("components/viewer-shell.css", viewer_readme)
        self.assertIn("does not depend on `example_webpage/`", viewer_readme)
        self.assertIn("app shell", viewer_readme)


if __name__ == "__main__":
    unittest.main()
