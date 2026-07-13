import json
import os
import sys
import tempfile
import unittest
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import song_credit_manager_core as manager_core
from song_credit_server import OverlayServer


class OverlayServerTests(unittest.TestCase):
    def test_obs_overlay_avoids_backdrop_filter(self):
        overlay_path = os.path.join(ROOT, "web", "overlay.html")
        with open(overlay_path, "r", encoding="utf-8") as handle:
            overlay_html = handle.read()

        self.assertNotIn("backdrop-filter", overlay_html)
        self.assertIn('data-font', overlay_html)
        self.assertIn('state.theme', overlay_html)
        self.assertIn('state.panel', overlay_html)

    def test_server_serves_overlay_health_and_state(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay_path = os.path.join(directory, "overlay.html")
            with open(overlay_path, "w", encoding="utf-8") as handle:
                handle.write("<!doctype html><title>Test Overlay</title>")
            store = manager_core.OverlayStateStore(
                {"theme": "light", "panel": False, "font": "mincho"}
            )
            server = OverlayServer(store, port=0, overlay_path=overlay_path)
            try:
                server.start()
                with urllib.request.urlopen(server.health_url, timeout=2) as response:
                    health = json.loads(response.read())
                self.assertEqual("ok", health["status"])

                with urllib.request.urlopen(server.overlay_url, timeout=2) as response:
                    page = response.read().decode("utf-8")
                self.assertIn("Test Overlay", page)

                store.show_record({"title": "テスト曲", "artist": "テスト歌手"})
                with urllib.request.urlopen(
                    server.overlay_url.replace("/overlay", "/api/state"), timeout=2
                ) as response:
                    state = json.loads(response.read())
                self.assertTrue(state["visible"])
                self.assertEqual("テスト曲", state["title"])
                self.assertEqual("light", state["theme"])
                self.assertFalse(state["panel"])
                self.assertEqual("mincho", state["font"])
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
