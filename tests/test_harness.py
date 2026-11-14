"""Fast harness tests: comparator, patch tool, tamper/capability detection. Run: python -m unittest discover -s tests -t ."""
import tempfile
import unittest
from pathlib import Path

from factory import integrity, patchutil
from oracle import compare


def rec(t, **kw):
    r = {"tick": t, "x": 0.5, "y": 100.0, "z": 0.5, "vx": 0.0, "vy": -0.0784, "vz": 0.0, "on_ground": True, "pose": "STANDING"}
    r.update(kw)
    return r


class Comparator(unittest.TestCase):
    def test_match_within_tolerance(self):
        a = [{"schema": "h"}, rec(0), rec(1)]
        b = [{"schema": "h"}, rec(0, x=0.5 + 5e-8), rec(1)]
        self.assertEqual(compare.compare(a, b)["status"], "match")

    def test_first_divergence_and_window(self):
        a = [rec(0), rec(1), rec(2), rec(3)]
        b = [rec(0), rec(1, z=0.6), rec(2, z=0.7), rec(3)]
        r = compare.compare(a, b)
        self.assertEqual(r["status"], "diverge")
        self.assertEqual((r["first_divergence"]["tick"], r["first_divergence"]["field"]), (1, "z"))
        self.assertEqual(r["window"], [1, 2])
        self.assertEqual(r["diverging_ticks"], 2)
        self.assertGreater(compare.max_ratio(r), 1e5)

    def test_exact_fields_and_only_shared_fields(self):
        a = [rec(0, sprinting=True)]
        b = [rec(0, on_ground=False)]
        r = compare.compare(a, b)  # 'sprinting' absent on one side -> ignored; on_ground compared exactly
        self.assertEqual(r["first_divergence"]["field"], "on_ground")
        self.assertNotIn("sprinting", r["fields"])

    def test_length_mismatch_is_divergence(self):
        self.assertEqual(compare.compare([rec(0), rec(1)], [rec(0)])["status"], "diverge")


class Patches(unittest.TestCase):
    def test_roundtrip_and_strictness(self):
        a, b = "one\ntwo\nthree\n", "one\nTWO\nthree\nfour\n"
        d = patchutil.make(a, b, "sim/src/x.py")
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sim" / "src" / "x.py"
            p.parent.mkdir(parents=True)
            p.write_text(a)
            patchutil.apply(Path(td), d)
            self.assertEqual(p.read_text(), b)
            with self.assertRaises(patchutil.PatchError):
                patchutil.apply(Path(td), d)

    def test_crlf_patch_is_normalized(self):
        d = patchutil.make("a\nb\n", "a\nc\n", "sim/src/y.py").replace("\n", "\r\n")
        self.assertEqual(patchutil.touched_paths(d), ["sim/src/y.py"])


class Tamper(unittest.TestCase):
    def test_path_policy(self):
        self.assertEqual(integrity.path_violations(["sim/src/mcsim/physics.py"]), [])
        for bad in ["sim/tests/test_basic.py", "oracle/tolerance.toml", "sim/src/../tests/x.py", "sim/pyproject.toml",
                    "factory/verifier.py", "sim/src/mcsim/data.json"]:
            self.assertEqual(integrity.path_violations([bad]), [bad], bad)

    def test_capability_scan(self):
        with tempfile.TemporaryDirectory() as td:
            base, cand = Path(td) / "b", Path(td) / "c"
            for d in (base, cand):
                d.mkdir()
            (base / "m.py").write_text("import math\nx = 1\n")
            (cand / "m.py").write_text("import math\nimport socket\nx = open('f').read()\n")
            v = integrity.capability_violations(base, cand)
            self.assertTrue(any("socket" in s for s in v))
            self.assertTrue(any("'open'" in s for s in v))
            (cand / "m.py").write_text("import math\nx = 2\n")
            self.assertEqual(integrity.capability_violations(base, cand), [])

    def test_tool_scan_traversal_resolves_cd(self):
        from factory.driver import scan_tool_log
        ws = Path(tempfile.gettempdir()) / "ws_case"
        flag = lambda c: scan_tool_log([{"name": "Bash", "input": {"command": c}}], ws)["tamper_suspect"]
        self.assertFalse(flag("cd scenarios/visible && cat a.json; cd ../..; cat sim/x"))
        self.assertTrue(flag("cat ../../bugs/x"))
        self.assertTrue(flag("cd sim && cat ../../../oracle/tolerance.toml"))
        edit = [{"name": "Edit", "input": {"file_path": "sim/src/x.py", "new_string": "a = 't:\\n' + '../x'"}}]
        self.assertFalse(scan_tool_log(edit, ws)["tamper_suspect"])  # file contents are not paths

    def test_manifest_change_detected(self):
        m = integrity.manifest()
        self.assertIn("oracle/tolerance.toml", m)
        m2 = dict(m)
        m2["oracle/tolerance.toml"] = "x"
        self.assertEqual(integrity.manifest_changes(m2, m), ["oracle/tolerance.toml"])


if __name__ == "__main__":
    unittest.main()
