"""Static checks for the public Injury Watch dashboard and documentation tab."""
import re
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "index.html"


class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.tabs = []
        self.panels = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if a.get("role") == "tab":
            self.tabs.append(a)
        if a.get("role") == "tabpanel":
            self.panels.append(a)


class DashboardDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")
        cls.structure = Structure()
        cls.structure.feed(cls.html)

    def test_two_accessible_tabs_and_unique_ids(self):
        s = self.structure
        self.assertEqual(len(s.tabs), 2)
        self.assertEqual(len(s.panels), 2)
        self.assertEqual(len(s.ids), len(set(s.ids)))
        self.assertEqual({a["aria-controls"] for a in s.tabs},
                         {"injuriesTab", "guideTab"})
        self.assertEqual({a["aria-labelledby"] for a in s.panels},
                         {"tab-injuries", "tab-guide"})

    def test_guide_documents_actual_schedules_and_selection_policy(self):
        html = self.html
        for item in (
            "How Injury Watch works",
            "12:17, 3:17, 6:17, 9:17 a.m.",
            "4:47 p.m., 5:00 p.m., and 5:47 p.m.",
            "10:30 a.m., 4:47 p.m., and 5:47 p.m.",
            "35 to under 95 minutes",
            "Questionable, Doubtful",
            "last three available completed weekly scoring records",
            "partial",
            "17 starters",
            "read-only",
            "MFL",
        ):
            with self.subTest(item=item):
                self.assertIn(item.lower(), html.lower())

    def test_inline_script_has_valid_javascript(self):
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", self.html, re.S | re.I)
        self.assertEqual(len(scripts), 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "injury-dashboard.js"
            path.write_text(scripts[0], encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
