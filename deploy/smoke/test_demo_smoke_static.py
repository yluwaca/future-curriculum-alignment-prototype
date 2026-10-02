import importlib.util
import json
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


class DemoSmokeStaticTests(unittest.TestCase):
    def test_fixture_manifest_is_explicitly_non_empirical(self):
        fixture_dir = ROOT / "demo" / "fixtures"
        manifest = json.loads((fixture_dir / "fixture_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["classification"], "synthetic_demo_only")
        self.assertIs(manifest["empirical_evidence"], False)
        self.assertFalse(manifest["contains_personal_information"])
        self.assertEqual(set(manifest["files"]), {
            "synthetic_curriculum_demo.txt", "synthetic_vacancies_demo.csv"
        })
        for filename in manifest["files"]:
            text = (fixture_dir / filename).read_text(encoding="utf-8")
            self.assertIn("SYNTHETIC", text.upper())
            self.assertIn("DEMO", text.upper())

    def test_runner_defaults_to_deployed_gateway_and_never_embeds_credentials(self):
        source = (HERE / "run_smoke.py").read_text(encoding="utf-8")
        self.assertIn("http://localhost:8080", source)
        self.assertIn("PCLMAS_SMOKE_USERNAME", source)
        self.assertIn("PCLMAS_SMOKE_PASSWORD", source)
        self.assertNotIn('default="admin"', source)
        self.assertNotIn('default="password"', source)
        self.assertIn('"empirical_evidence": False', source)
        self.assertIn('/operations/jobs/{operational_job_id}', source)
        self.assertIn('ended as', source)
        self.assertIn('document_key = "synthetic-demo-curriculum-v1"', source)

    def test_runner_module_imports_without_optional_application_dependencies(self):
        spec = importlib.util.spec_from_file_location("run_smoke", HERE / "run_smoke.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))


if __name__ == "__main__":
    unittest.main()
