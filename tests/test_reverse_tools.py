import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import folder_tools
from reverse_tools_server import Adapter, process_run, tools


class ReverseAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.root = Path(self.temp.name).resolve()
        (self.root / "adapter.json").write_text('{"java_home":"java"}', encoding="utf-8")
        self.adapter = Adapter("classrevive", self.root)

    def tearDown(self):
        self.adapter.close()
        self.temp.cleanup()

    def test_long_jobs_are_discoverable_without_blocking_call(self):
        names = {t["name"] for t in tools("classrevive")}
        self.assertTrue({"decompile_start", "job_status", "job_cancel", "list_results", "read_result"}.issubset(names))
        self.assertNotIn("run_arbitrary_command", names)

    def test_process_timeout_and_bounded_output(self):
        result = process_run([sys.executable, "-c", "import time;print('started',flush=True);time.sleep(20)"], os.environ.copy(), self.root, 0.3)
        self.assertTrue(result["timed_out"])
        self.assertIn("started", result["stdout"])
        result = process_run([sys.executable, "-c", "import sys;sys.stdout.write('x'*1500000)"], os.environ.copy(), self.root, 10)
        self.assertEqual(result["exit_code"], 0)
        self.assertLessEqual(len(result["stdout"]), 1024 * 1024)

    def test_job_finishes_persists_and_protects_existing_output(self):
        target = self.root / "input.jar"
        target.write_bytes(b"fixture")
        output = self.root / "result"
        command = [sys.executable, "-c", "from pathlib import Path;import sys;p=Path(sys.argv[1]);p.mkdir();(p/'report.txt').write_text('NOT_VERIFIED')", str(output)]
        with patch.object(self.adapter, "class_command", return_value=command):
            job = self.adapter.start({"input_path": str(target), "output_path": str(output)})
        deadline = time.monotonic() + 10
        while self.adapter.job(job["job_id"])["state"] == "running" and time.monotonic() < deadline:
            time.sleep(0.05)
        result = self.adapter.job(job["job_id"])
        self.assertEqual(result["state"], "complete", result)
        self.assertEqual(self.adapter.execute("read_result", {"job_id":job["job_id"], "path":"report.txt"})["content"], "NOT_VERIFIED")
        listed = self.adapter.execute("list_results", {"job_id":job["job_id"]})
        self.assertEqual(listed["entries"][0]["name"], "report.txt")
        restored = Adapter("classrevive", self.root)
        try:
            self.assertEqual(restored.job(job["job_id"])["state"], "complete")
        finally:
            restored.close()
        with self.assertRaises(ValueError):
            self.adapter.start({"input_path": str(target), "output_path":str(output)})
        self.assertEqual((output / "report.txt").read_text(), "NOT_VERIFIED")
        with self.assertRaises(ValueError):
            self.adapter.execute("read_result", {"job_id":job["job_id"], "path":"../adapter.json"})

    def test_cancellation_stops_owned_process(self):
        target = self.root / "input.jar"
        target.write_bytes(b"fixture")
        with patch.object(self.adapter, "class_command", return_value=[sys.executable, "-c", "import time;time.sleep(30)"]):
            job = self.adapter.start({"input_path":str(target), "output_path":str(self.root/'result')})
        deadline = time.monotonic()+5
        while not self.adapter.jobs[job["job_id"]].get("process") and time.monotonic()<deadline:
            time.sleep(0.02)
        process = self.adapter.jobs[job["job_id"]]["process"]
        self.assertIsNotNone(process)
        self.adapter.execute("job_cancel", {"job_id":job["job_id"]})
        deadline = time.monotonic()+5
        while self.adapter.job(job["job_id"])["state"]=="running" and time.monotonic()<deadline:
            time.sleep(0.02)
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.adapter.job(job["job_id"])["state"], "cancelled")

    def test_adapter_manifest_uses_current_runtime_in_source_and_exe(self):
        app_root = self.root / "app"
        tool = app_root / "Ferramentas/ClassRevive"
        tool.mkdir(parents=True)
        (tool / "ferramenta.json").write_text(json.dumps({"version":1,"name":"ClassRevive adapter","server":{"adapter":"classrevive"}}),encoding="utf-8")
        with patch("config.application_root",return_value=app_root), patch("config.config_dir",return_value=self.root/"settings"):
            cfg=config.default_config()
            row=folder_tools.scan(cfg)[0]
            self.assertFalse(row["error"],row)
            self.assertIn("reverse_tools_server.py", row["server"]["args"][1])
            with patch.object(sys,"frozen",True,create=True), patch.object(sys,"executable","C:/Studio/Studio.exe"):
                row=folder_tools.scan(cfg)[0]
            self.assertEqual(row["server"]["command"],"C:/Studio/Studio.exe")
            self.assertEqual(row["server"]["args"][0],"--reverse-tools-server")

    def test_guide_is_reference_and_unknown_operation_rejected(self):
        distribution = self.root / "distribution"
        distribution.mkdir()
        (distribution / "README.md").write_text("Third party guide",encoding="utf-8")
        result=self.adapter.execute("read_guide",{})
        self.assertTrue(result["third_party_reference"])
        self.assertEqual(result["content"],"Third party guide")
        with self.assertRaises(ValueError):
            self.adapter.execute("unknown",{})


if __name__ == "__main__":
    unittest.main()
