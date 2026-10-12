import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .branding import brand_header, brand_rendered_text, brand_template, load_brand


class BrandTests(unittest.TestCase):
    def test_shared_brand_and_native_header(self):
        brand = load_brand()
        self.assertEqual(brand["company"], "神典信息")
        self.assertIn("Genesis", brand_header(brand, "model", "thread").plain)
        self.assertNotIn("DeerFlow", brand_header(brand, "model", "thread").plain)

    def test_renderer_document_with_body_attributes_and_safe_metadata(self):
        brand = load_brand()
        brand["title"] = 'Genesis & "DEV"'
        source = '<html><head><title>old</title></head><body data-pingurl="">native renderer</body></html>'
        result = brand_template(source, brand)
        self.assertIn('<body data-pingurl=""><img src="/brand/logo"', result)
        self.assertIn("Genesis &amp; &quot;DEV&quot;", result)
        self.assertIn('rel="icon" href="/brand/logo"', result)
        self.assertEqual(result.count("<title>"), 1)
        with self.assertRaises(ValueError):
            brand_template("<main>unexpected upstream template</main>", brand)

    def test_invalid_runtime_theme_rejected_before_render(self):
        brand = load_brand()
        brand["dark"]["primary"] = "red; malicious"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brand.json"
            path.write_text(json.dumps(brand), encoding="utf-8")
            with patch.dict(os.environ, {"GENESIS_BRAND_CONFIG": str(path)}):
                with self.assertRaises(ValueError):
                    load_brand()

    def test_color_adapter_preserves_literal_user_content(self):
        from rich.text import Text

        from deerflow.tui.theme import THEME

        original = Text("User asks about DeerFlow", style="bold")
        original.stylize(THEME.text)
        result = brand_rendered_text(original, load_brand())
        self.assertEqual(result.plain, original.plain)
        self.assertEqual(result.spans[0].style.color.get_truecolor().hex, load_brand()["dark"]["foreground"])


class NativeMountBrandTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_mount_brand_and_readonly_contract(self):
        from unittest.mock import MagicMock

        from deerflow.tui.cli import LaunchPlan

        from .app import BoundSession, BrowserTUI
        from .client import Binding

        client = MagicMock()
        client.binding = Binding("user", "owned", None, "__default__", {}, False)
        client.list_models.return_value = {"models": [{"name": "model"}]}
        client.list_skills.return_value = {"skills": []}
        client.history.return_value = {"messages": []}
        app = BrowserTUI(BoundSession(client), LaunchPlan(mode="tui", thread_id="owned", forced_tui=True))
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            self.assertTrue(app.query_one("#composer").disabled)
            self.assertIn("Genesis", app.query_one("#composer").placeholder)
            self.assertNotIn("DeerFlow", str(app.query_one("#header").render()))
            self.assertIn("Genesis", str(app.query_one("#header").render()))
