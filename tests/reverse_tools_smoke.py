"""Teste real dos adaptadores instalados, usando apenas amostras criadas aqui."""
import json
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config


def call(app, row, name, args):
    result = app._folder_tools.execute(config.load_config(), row["id"], name, args, lambda *a: True)
    if result.get("isError"):
        raise AssertionError((name, result))
    return json.loads(result["content"][0]["text"])


def wait(app, row, job):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        state = call(app, row, "job_status", {"job_id": job["job_id"]})
        if state["state"] != "running":
            return state
        time.sleep(1)
    raise AssertionError("O job não terminou a tempo.")


runtime = ExitStack()
if "--exe" in sys.argv:
    runtime.enter_context(patch.object(sys,"frozen",True,create=True))
    runtime.enter_context(patch.object(sys,"executable",str(Path("dist/Studio de Media.exe").resolve())))
app = api.Api()
try:
    rows = app.get_folder_tools()["tools"]
    android = next(r for r in rows if r["name"] == "Android Reverse Engineering")
    java_tool = next(r for r in rows if r["name"].startswith("ClassRevive"))
    for row in (android, java_tool):
        result = app.test_folder_tool(row["id"])
        assert result["ok"], result
        deps = call(app, row, "check_dependencies", {})
        assert deps["exit_code"] == 0, deps
        assert "21.0.13" in deps["stdout"], deps
        guide = call(app, row, "read_guide", {})
        assert len(guide["content"]) > 1000, guide
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
        root = Path(temporary).resolve()
        source = root / "Calculator.java"
        marker = root / "target-executed.txt"
        source.write_text('public final class Calculator { static { try { java.nio.file.Files.writeString(java.nio.file.Path.of(' + json.dumps(str(marker)) + '), "executed"); } catch (Exception ignored) {} } public static int add(int a,int b) { return a+b; } public static String endpoint(){return "https://api.example.invalid/v1/items";} }', encoding="utf-8")
        java_home = next((Path("Ferramentas/ClassRevive/runtime")).glob("jdk-*")).resolve()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run([str(java_home / "bin/javac.exe"), "--release", "17", str(source)], check=True, capture_output=True, creationflags=flags)
        jar = root / "sample.jar"
        subprocess.run([str(java_home / "bin/jar.exe"), "--create", "--file", str(jar), "-C", str(root), "Calculator.class"], check=True, capture_output=True, creationflags=flags)
        inspected = call(app, java_tool, "inspect", {"input_path": str(jar)})
        assert inspected["exit_code"] == 0, inspected
        assert "Calculator" in inspected["stdout"], inspected
        output = root / "classrevive-result"
        job = call(app, java_tool, "decompile_start", {"input_path": str(jar), "output_path": str(output), "engines": "all", "timeout_seconds": 120})
        result = wait(app, java_tool, job)
        print("ClassRevive:", json.dumps(result, ensure_ascii=True)[:5000], flush=True)
        assert result["state"] == "complete", result
        assert (output / "report.json").is_file()
        assert list((output / "selection/sources").rglob("*.java"))
        assert not marker.exists(), "ClassRevive não deve executar o alvo."
        report = call(app, java_tool, "read_result", {"job_id": job["job_id"], "path": "report.json"})
        assert "NOT_VERIFIED" in report["content"], report
        android_output = root / "android-result"
        job = call(app, android, "decompile_start", {"input_path": str(jar), "output_path": str(android_output), "engine": "both", "timeout_seconds": 120})
        result = wait(app, android, job)
        print("Android:", json.dumps(result, ensure_ascii=True)[:8000], flush=True)
        assert result["state"] == "complete", result
        assert list((android_output / "jadx").rglob("Calculator.java")), result
        assert list((android_output / "fernflower").rglob("Calculator.java")), result
        assert not marker.exists(), "A decompilação Android não deve executar o alvo."
        endpoints = call(app, android, "find_api_calls", {"source_path": str(android_output), "mode": "urls"})
        assert endpoints["exit_code"] == 0 and "api.example.invalid" in endpoints["stdout"], endpoints
        kotlin = root / "kotlin"
        kotlin.mkdir()
        (kotlin / "a.java").write_text('@DebugMetadata(c = "com.example.InventoryRepository", f = "Inventory.kt")\npublic class a {}', encoding="utf-8")
        mapping = root / "mapping"
        result = call(app, android, "recover_kotlin_names", {"source_path": str(kotlin), "output_path": str(mapping)})
        assert result["exit_code"] == 0 and (mapping / "mapping.json").is_file(), result
        result = call(app, android, "lookup_kotlin_name", {"mapping_path": str(mapping), "query": "InventoryRepository"})
        assert "com.example.InventoryRepository" in result["stdout"], result
        apk = root / "fixture.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", '<manifest package="com.example.fixture"/>')
            archive.writestr("classes.dex", b"dex\n035\x00Lretrofit2/Retrofit; Landroidx/compose/runtime/Composer;")
            archive.writestr("lib/arm64-v8a/libflutter.so", b"fixture")
            archive.writestr("lib/arm64-v8a/libapp.so", b"fixture")
        result = call(app, android, "fingerprint", {"input_path": str(apk)})
        print("Fingerprint:", json.dumps(result, ensure_ascii=True)[:5000], flush=True)
        assert result["exit_code"] == 0 and "Flutter" in result["stdout"], result
        summary = {"mode":"packaged exe" if "--exe" in sys.argv else "source", "classrevive_version": "0.1.0", "jdk": "21.0.13+9", "java_decompiled_and_verified": True, "behavior": "NOT_VERIFIED", "android_jar_both_engines": True, "api_search": True, "kotlin_mapping": True, "apk_fingerprint": True, "target_executed": False}
        (Path(__file__).parent / "reverse-tools-smoke-result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("PASS: ClassRevive all engines + relatório; skill Android/JADX/Vineflower; endpoints; Kotlin; triagem APK; alvos não executados.", flush=True)
finally:
    app._folder_tools.close()
    app._mcp.close()
    runtime.close()
