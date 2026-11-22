import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *map(str, args)],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestDetectStack(unittest.TestCase):
    def test_detects_python_and_frameworks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
            (p / "requirements.txt").write_text("numpy==2.0\nfastapi\n", encoding="utf-8")
            out_file = p / "out" / "stack.json"
            res = run_script("detect_stack.py", p, "--out", out_file)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["primary_language"], "python")
            self.assertIn("pyo3", data["recommended_bridges"])
            self.assertIn("numpy", data["frameworks"])
            self.assertIn("fastapi", data["frameworks"])
            self.assertTrue(data["notes"])

    def test_detects_tauri_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "src").mkdir()
            (p / "src" / "main.ts").write_text("export const x = 1;\n", encoding="utf-8")
            (p / "src-tauri").mkdir()
            (p / "package.json").write_text(json.dumps({"dependencies": {"@tauri-apps/api": "^2"}}), encoding="utf-8")
            res = run_script("detect_stack.py", p)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(res.stdout)
            self.assertEqual(data["primary_language"], "typescript")
            self.assertEqual(data["recommended_bridges"][0], "tauri")


class TestScanHotspots(unittest.TestCase):
    def test_python_ast_and_profile_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "compute.py").write_text(
                "import re\n"
                "def hot_parse(rows):\n"
                "    total = 0\n"
                "    for r in rows:\n"
                "        for c in r:\n"
                "            if re.match(r'\\d+', c):\n"
                "                total += int(c) * 2 + 1\n"
                "    return total\n",
                encoding="utf-8",
            )
            profile = p / "profile.json"
            profile.write_text(json.dumps({
                "workload": "test",
                "samples": [
                    {"file": "compute.py", "function": "hot_parse", "self_percent": 65.0, "total_percent": 70.0}
                ],
            }), encoding="utf-8")
            out_file = p / "hotspots.json"
            res = run_script("scan_hotspots.py", p, "--profile", profile, "--out", out_file)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertTrue(data["profile_used"])
            self.assertEqual(len(data["candidates"]), 1)
            cand = data["candidates"][0]
            self.assertEqual(cand["name"], "hot_parse")
            self.assertTrue(cand["measured"])
            self.assertAlmostEqual(cand["amdahl_max_speedup"], round(1 / 0.35, 2))

    def test_js_brace_scanning_handles_nested_loops(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "work.js").write_text(
                "function processItems(items) {\n"
                "  let out = [];\n"
                "  for (let i = 0; i < items.length; i++) {\n"
                "    for (let j = 0; j < items.length; j++) {\n"
                "      if (items.includes(items[i])) out.push(JSON.stringify(items[j]));\n"
                "    }\n"
                "  }\n"
                "  return out;\n"
                "}\n",
                encoding="utf-8",
            )
            out_file = p / "hotspots.json"
            res = run_script("scan_hotspots.py", p, "--out", out_file)
            self.assertEqual(res.returncode, 0, res.stderr)
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data["candidates"]), 1)
            self.assertEqual(data["candidates"][0]["name"], "processItems")


class TestRunBaselineAndCompare(unittest.TestCase):
    def test_baseline_and_compare_bench(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            out_dir = p / "bench"
            res = run_script(
                "run_baseline.py", "--name", "fast", "--runs", "3", "--warmup", "1",
                "--out", out_dir, "--", sys.executable, "-c", "sum(range(1000))"
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            fast_json = out_dir / "fast.json"
            data = json.loads(fast_json.read_text(encoding="utf-8"))
            self.assertEqual(len(data["times_s"]), 3)
            if sys.platform == "win32":
                self.assertIsNotNone(data["peak_rss_kb_median"])
                self.assertGreater(data["peak_rss_kb_median"], 0)

            # Synthetic before/after comparison + nested --md parent creation
            before = p / "before.json"
            after = p / "after.json"
            before.write_text(json.dumps({
                "times_s": [2.0, 2.1, 1.9], "median_s": 2.0, "min_s": 1.9, "max_s": 2.1,
                "rel_stdev": 0.05, "peak_rss_kb_median": 102400,
            }), encoding="utf-8")
            after.write_text(json.dumps({
                "times_s": [0.5, 0.52, 0.48], "median_s": 0.5, "min_s": 0.48, "max_s": 0.52,
                "rel_stdev": 0.04, "peak_rss_kb_median": 51200,
            }), encoding="utf-8")
            md_out = p / "nested" / "report.md"
            cmp_res = run_script("compare_bench.py", before, after, "--min-speedup", "1.5", "--md", md_out)
            self.assertEqual(cmp_res.returncode, 0, cmp_res.stderr)
            self.assertTrue(md_out.is_file())
            self.assertIn("4.00x faster", md_out.read_text(encoding="utf-8"))


class TestParityCheck(unittest.TestCase):
    def test_bool_not_equal_to_float_and_report_dir_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            corpus = p / "corpus"
            corpus.mkdir()
            (corpus / "a.txt").write_text("hello", encoding="utf-8")

            # Legacy outputs {"ok": true}, candidate outputs {"ok": 1.0} -> MUST mismatch!
            report_path = p / "nested" / "parity.json"
            res = run_script(
                "parity_check.py",
                "--legacy", f'{sys.executable} -c "print(\'{{\\\"ok\\\": true}}\')"',
                "--candidate", f'{sys.executable} -c "print(\'{{\\\"ok\\\": 1.0}}\')"',
                "--inputs", corpus,
                "--report", report_path,
            )
            self.assertEqual(res.returncode, 1)
            self.assertTrue(report_path.is_file())
            rep = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(rep["ok"], 0)
            self.assertEqual(len(rep["mismatches"]), 1)

    def test_float_tolerance_and_ignore_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            corpus = p / "corpus"
            corpus.mkdir()
            (corpus / "a.txt").write_text("1", encoding="utf-8")
            res = run_script(
                "parity_check.py",
                "--legacy", f'{sys.executable} -c "print(\'{{\\\"v\\\": 1.0000000001, \\\"ts\\\": 1}}\')"',
                "--candidate", f'{sys.executable} -c "print(\'{{\\\"v\\\": 1.0000000002, \\\"ts\\\": 99}}\')"',
                "--inputs", corpus,
                "--float-tol", "1e-6",
                "--ignore-key", "ts",
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class TestScaffoldRustCrate(unittest.TestCase):
    def test_all_bridges_scaffold_and_refuse_overwrite(self):
        bridges = ("pyo3", "napi", "wasm", "ffi", "sidecar", "tauri")
        with tempfile.TemporaryDirectory() as tmp:
            for bridge in bridges:
                out_dir = Path(tmp) / bridge
                res = run_script("scaffold_rust_crate.py", "--bridge", bridge, "--name", "fast-parser", "--out", out_dir)
                self.assertEqual(res.returncode, 0, f"{bridge}: {res.stderr}")
                files = list(out_dir.rglob("*"))
                self.assertTrue(any(f.is_file() for f in files), f"{bridge} produced no files")
                for f in files:
                    if f.is_file():
                        content = f.read_text(encoding="utf-8")
                        self.assertNotIn("{{crate_name}}", content)
                        self.assertNotIn("{{CrateNamePascal}}", content)

                # Refuses overwrite without --force
                res2 = run_script("scaffold_rust_crate.py", "--bridge", bridge, "--name", "fast-parser", "--out", out_dir)
                self.assertNotEqual(res2.returncode, 0)


class TestPackageSkill(unittest.TestCase):
    def test_package_skill_validates_and_builds_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_zip = Path(tmp) / "rust-hotspot-optimizer.skill"
            res = run_script("package_skill.py", "--out", out_zip)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertTrue(out_zip.is_file())
            with zipfile.ZipFile(out_zip) as zf:
                names = set(zf.namelist())
                self.assertIn("rust-hotspot-optimizer/SKILL.md", names)
                self.assertIn("rust-hotspot-optimizer/scripts/detect_stack.py", names)
                self.assertNotIn("rust-hotspot-optimizer/scripts/package_skill.py", names)


if __name__ == "__main__":
    unittest.main()
