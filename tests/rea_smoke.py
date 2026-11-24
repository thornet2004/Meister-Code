"""Smoke opcional do REA instalado, através da mesma ponte que o modelo utiliza."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import api
import config

app = api.Api()
try:
    row = next(r for r in app.get_folder_tools()["tools"] if r["name"] == "REA")
    tested = app.test_folder_tool(row["id"])
    assert tested["ok"], tested
    count = tested["count"]
    assert count > 200, "Verificar também acesso para além do limite de catálogo direto."
    found = app._folder_tools.search(config.load_config(), row["id"], "verify_unknown_resolution")
    assert any(t["name"] == "verify_unknown_resolution" for t in found["tools"]), found
    with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
        path = Path(folder).resolve()
        marker = path / "should-not-execute.txt"
        (path / "package.json").write_text('{"name":"rea-smoke","version":"1.0.0","main":"index.js"}', encoding="utf-8")
        (path / "index.js").write_text("const fs=require('fs');fs.writeFileSync(" + json.dumps(str(marker)) + ", 'executed'); const helper=require('./helper'); console.log(helper.add(20,22));", encoding="utf-8")
        (path / "helper.js").write_text("exports.add=(a,b)=>a+b;", encoding="utf-8")
        result = app._folder_tools.execute(config.load_config(), row["id"], "analyze_javascript_application", {"input_path": str(path), "detail": "summary"}, lambda *args: True)
        assert not result.get("isError"), result
        evidence = json.loads(next(p["text"] for p in result["content"] if p["type"] == "text"))
        summary = evidence["normalized_result"]["summary"]
        assert summary["statistics"]["parsed_javascript_files"] == 2, summary
        assert not marker.exists(), "A análise estática não deve executar o alvo."
        report = {"rea_version": row["package_version"], "operation_count": count, "operation_beyond_direct_cap_accessible": True,
                  "parsed_javascript_files": 2, "target_executed": False, "evidence_id": evidence["evidence_id"], "limitations_retained": bool(evidence["limitations"])}
        (Path(__file__).parent / "rea-smoke-result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("PASS: REA " + row["package_version"] + "; " + str(count) + " operações; pesquisa integral; análise de dois ficheiros JS sem executar o alvo; limitações preservadas.")
finally:
    app._folder_tools.close()
    app._mcp.close()
