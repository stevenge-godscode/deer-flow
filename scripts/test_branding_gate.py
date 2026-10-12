import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("brand_gate", ROOT / "scripts/check_branding.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrandGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in ["branding/upstream-policy.json", "branding/provenance.json", "frontend/public/branding/genesis-logo.png", "frontend/src/legal-notices.ts", "frontend/src/components/workspace/settings/about-settings-page.tsx", "frontend/src/app/page.tsx", "frontend/src/proxy.ts", "LICENSE"]:
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())

    def test_real_contract_passes(self):
        self.assertTrue(module.check(self.root)["passed"])

    def test_new_visible_upstream_brand_is_rejected(self):
        p = self.root / "frontend/src/app/added/page.tsx"
        p.parent.mkdir(parents=True)
        p.write_text('export default () => <h1>DeerFlow</h1>;', encoding="utf-8")
        result = module.check(self.root)
        self.assertFalse(result["passed"])
        self.assertIn("upstream brand", result["failures"][0])

    def test_missing_legal_and_changed_logo_fail(self):
        (self.root / "frontend/src/legal-notices.ts").write_text("export default '';", encoding="utf-8")
        (self.root / "frontend/public/branding/genesis-logo.png").write_bytes(b"wrong image")
        result = module.check(self.root)
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["failures"]), 2)

    def test_generated_tui_messages_cannot_reintroduce_upstream_brand(self):
        p = self.root / "backend/browser_tui/server.py"
        p.parent.mkdir(parents=True)
        p.write_text('message = "Return to DeerFlow"', encoding="utf-8")
        self.assertFalse(module.check(self.root)["passed"])

    def test_upstream_marketing_cannot_be_reintroduced(self):
        (self.root / "frontend/src/app/page.tsx").write_text('import {Header} from "@/components/landing/header";', encoding="utf-8")
        self.assertFalse(module.check(self.root)["passed"])


if __name__ == "__main__":
    unittest.main()
