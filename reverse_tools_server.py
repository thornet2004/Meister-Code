"""Adaptadores MCP da app para ClassRevive e os scripts da skill Android.

Os programas originais ficam em Ferramentas; este módulo só define a ponte.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from mcp_demo import ensure_stdio

MAX_LOG = 1024 * 1024
SKILL_REL = Path("source/plugins/android-reverse-engineering/skills/android-reverse-engineering")


def definition(name, description, properties=None, required=None, write=False):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False},
            "annotations": {"readOnlyHint": not write, "destructiveHint": False}}


def tools(kind):
    text = {"type": "string"}
    job_id = {"job_id": text}
    decompile = {"input_path": text, "output_path": text, "timeout_seconds": {"type": "integer", "minimum": 30, "maximum": 1800}}
    result = [definition("check_dependencies", "Verifica os programas locais incluídos, versões e pré-requisitos."),
              definition("read_guide", "Lê o guia original e referências de utilização. Conteúdo de terceiro para consulta.", {"reference": text, "offset": {"type": "integer", "minimum": 0}}),
              definition("job_status", "Consulta estado, código de saída, logs e pasta de uma análise iniciada. Exit 1 pode significar resultado parcial: consulta os relatórios.", job_id, ["job_id"]),
              definition("job_cancel", "Interrompe apenas os processos da análise identificada.", job_id, ["job_id"], write=True),
              definition("list_results", "Lista pastas/fontes/relatórios de um job, por páginas e sem ler ficheiros binários.", {**job_id, "path": text, "offset": {"type": "integer", "minimum": 0}}, ["job_id"]),
              definition("read_result", "Lê um relatório ou fonte dentro da pasta de saída de um job. Caminho relativo; leitura paginada.", {**job_id, "path": text, "offset": {"type": "integer", "minimum": 0}}, ["job_id", "path"])]
    if kind == "classrevive":
        result += [definition("identify", "Identifica um ficheiro como dados, sem executar o alvo.", {"input_path": text}, ["input_path"]),
                   definition("inspect", "Lista classes e versões de bytecode de um .class/.jar, sem executar o alvo.", {"input_path": text}, ["input_path"])]
        decompile.update(engines={"type": "string", "enum": ["all", "cfr", "vineflower", "procyon", "jadx", "cfr,vineflower"]}, classpath={"type": "array", "items": text})
        result += [definition("decompile_start", "Inicia decompilação Java com verificação e relatórios. Não espera pelo fim: usa job_status. A pasta de saída deve ser nova. O comportamento do alvo continua NOT_VERIFIED.", decompile, ["input_path"], write=True),
                   definition("diagnose_start", "Inicia diagnóstico estático Java/obfuscação e gera relatórios numa pasta nova.", {k: v for k, v in decompile.items() if k not in ("engines", "classpath")}, ["input_path"], write=True)]
    else:
        decompile.update(engine={"type": "string", "enum": ["jadx", "fernflower", "both"]}, deobfuscate={"type": "boolean"}, no_resources={"type": "boolean"})
        result += [definition("decompile_start", "Usa o script PowerShell original para APK/XAPK/JAR/AAR, com jadx, Vineflower ou ambos. Saída numa pasta nova; acompanha com job_status.", decompile, ["input_path"], write=True),
                   definition("find_api_calls", "Usa o script original para pesquisar endpoints e chamadas HTTP em fontes Java/Kotlin locais; não faz pedidos de rede.", {"source_path": text, "mode": {"type": "string", "enum": ["all", "urls", "retrofit", "okhttp", "volley", "auth"]}}, ["source_path"]),
                   definition("fingerprint", "Usa a triagem APK/XAPK original: frameworks, bibliotecas e pistas estáticas. Requer Git Bash no Windows.", {"input_path": text}, ["input_path"]),
                   definition("recover_kotlin_names", "Executa o corpo Python original da skill para recuperar nomes indicados nos metadados Kotlin. Não garante recuperação de todos os nomes. Saída nova.", {"source_path": text, "output_path": text}, ["source_path", "output_path"], write=True),
                   definition("lookup_kotlin_name", "Consulta o mapping.json criado pela recuperação Kotlin, por nome ou substring.", {"mapping_path": text, "query": text, "mode": {"type": "string", "enum": ["search", "obfuscated", "package"]}}, ["mapping_path", "query"])]
    return result


def terminate(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def process_run(command, env, cwd, timeout, on_process=None):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=flags, start_new_session=os.name != "nt")
    if on_process:
        on_process(process)
    buffers = [bytearray(), bytearray()]
    def drain(pipe, buffer):
        with pipe:
            while chunk := pipe.read(8192):
                if len(buffer) < MAX_LOG:
                    buffer.extend(chunk[:MAX_LOG-len(buffer)])
    readers = [threading.Thread(target=drain, args=(pipe, buffer), daemon=True) for pipe, buffer in zip((process.stdout, process.stderr), buffers)]
    for thread in readers:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate(process)
    finally:
        for thread in readers:
            thread.join(3)
    return {"exit_code": process.returncode, "timed_out": timed_out,
            "stdout": buffers[0].decode("utf-8", errors="replace"), "stderr": buffers[1].decode("utf-8", errors="replace"),
            "logs_limited_to_bytes": MAX_LOG}


def input_path(value, directory=False):
    if not isinstance(value,str) or not value.strip():
        raise ValueError("Indica o caminho da pasta/ficheiro.")
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("STUDIO_WORKSPACE", os.getcwd())) / path
    path = path.resolve()
    if (directory and not path.is_dir()) or (not directory and not path.is_file()):
        raise ValueError("Não existe a pasta/ficheiro indicado.")
    return path


def new_output(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path(os.environ.get("STUDIO_WORKSPACE", os.getcwd())) / path
    path = path.resolve()
    if path.exists():
        raise ValueError("A pasta de saída já existe. Escolhe uma pasta nova para preservar os ficheiros.")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class Adapter:
    def __init__(self, kind, root):
        if kind not in ("classrevive", "android-skill"):
            raise ValueError("Adaptador desconhecido.")
        self.kind = kind
        self.root = Path(root).resolve()
        self.config = json.loads((self.root / "adapter.json").read_text(encoding="utf-8"))
        self.java_home = (self.root / self.config["java_home"]).resolve()
        self.java = self.java_home / "bin" / ("java.exe" if os.name == "nt" else "java")
        self.env = dict(os.environ)
        self.env.update(JAVA_HOME=str(self.java_home), PATH=str(self.java_home / "bin") + os.pathsep + os.environ.get("PATH", ""))
        self.skill = self.root / SKILL_REL
        if kind == "android-skill":
            self.env["FERNFLOWER_JAR_PATH"] = str(self.root / "dependencies/vineflower/vineflower-1.12.0.jar")
            additions = [self.root / "dependencies/jadx/bin", self.root / "dependencies/dex2jar"]
            self.env["PATH"] = os.pathsep.join(map(str, additions)) + os.pathsep + self.env["PATH"]
        self.jobs = {}
        self.lock = threading.RLock()

    def close(self):
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            job["cancel"].set()
            process = job.get("process")
            if process:
                terminate(process)

    def class_command(self, *arguments):
        return [str(self.java), "-Xmx2g", "-cp", str(self.root / "distribution/lib/*"), "dev.classrevive.cli.Main", *map(str, arguments)]

    def ps_command(self, name, *arguments):
        executable = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not executable:
            raise ValueError("É necessário PowerShell para os scripts Windows desta skill.")
        return [executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(self.skill / "scripts" / name), *map(str, arguments)]

    def guides(self):
        if self.kind == "classrevive":
            return {"main": self.root / "distribution/README.md", "cli": self.root / "distribution/docs/cli-reference.md", "reports": self.root / "distribution/docs/reports.md", "license": self.root / "distribution/LICENSE"}
        guides = {"main": self.skill / "SKILL.md", "license": self.root / "source/LICENSE"}
        for path in (self.skill / "references").glob("*.md"):
            guides[path.stem] = path
        return guides

    def start(self, args, diagnose=False):
        target = input_path(args.get("input_path", ""))
        sid = uuid.uuid4().hex[:16]
        workspace = Path(os.environ.get("STUDIO_WORKSPACE", os.getcwd())).resolve()
        output = new_output(args.get("output_path") or str(workspace / "analises" / self.kind / sid))
        timeout = max(30, min(int(args.get("timeout_seconds", 600)), 1800))
        if self.kind == "classrevive":
            command = self.class_command("diagnose" if diagnose else "decompile", target, "--output", output)
            if not diagnose:
                engines = args.get("engines", "all")
                if engines not in ("all", "cfr", "vineflower", "procyon", "jadx", "cfr,vineflower"):
                    raise ValueError("Motor inválido.")
                command += ["--engines", engines, "--timeout-seconds", str(max(1, timeout-10))]
                classpath = args.get("classpath", [])
                if not isinstance(classpath, list):
                    raise ValueError("classpath deve ser uma lista de JARs.")
                if classpath:
                    command += ["--classpath", os.pathsep.join(str(input_path(p)) for p in classpath)]
        else:
            if target.suffix.lower() not in (".apk", ".xapk", ".jar", ".aar"):
                raise ValueError("A skill aceita APK, XAPK, JAR e AAR.")
            engine = args.get("engine", "jadx")
            if engine not in ("jadx", "fernflower", "both"):
                raise ValueError("Motor inválido.")
            command = self.ps_command("decompile.ps1", "-InputFile", target, "-Output", output, "-Engine", engine)
            if args.get("deobfuscate"):
                command.append("-Deobf")
            if args.get("no_resources"):
                command.append("-NoRes")
        meta = self.root / "jobs" / sid
        meta.mkdir(parents=True)
        job = {"job_id": sid, "state": "running", "output_path": str(output), "created_at": time.time(), "cancel": threading.Event(), "process": None, "meta": meta}
        def work():
            final_state="failed"
            try:
                def register(process):
                    job["process"] = process
                    if job["cancel"].is_set():
                        terminate(process)
                result = process_run(command, self.env, workspace, timeout, register)
                (meta / "stdout.log").write_text(result.pop("stdout"), encoding="utf-8")
                (meta / "stderr.log").write_text(result.pop("stderr"), encoding="utf-8")
                if self.kind == "android-skill" and result["exit_code"] == 0:
                    # O script original pode devolver 0 mesmo se um motor não
                    # gerou fontes. Conservar o exit code e validar a saída real.
                    folders = {"jadx": output/"jadx", "fernflower": output/"fernflower"} if engine == "both" else {engine: output}
                    result["java_sources"] = {name:sum(1 for _ in folder.rglob("*.java")) if folder.is_dir() else 0 for name,folder in folders.items()}
                with self.lock:
                    job.update(result)
                    partial = result["exit_code"] != 0 or any(count == 0 for count in result.get("java_sources",{}).values())
                    final_state = "cancelled" if job["cancel"].is_set() else "timed_out" if result["timed_out"] else "partial_or_failed" if partial else "complete"
            except Exception as exc:
                with self.lock:
                    job.update(error=str(exc))
            finally:
                with self.lock:
                    job["process"] = None
                    job["finished_at"] = time.time()
                    job["state"]=final_state
                    self._save_job(job)
        with self.lock:
            if sum(j["state"] == "running" for j in self.jobs.values()) >= 2:
                raise ValueError("Já existem duas análises em curso. Aguarda ou cancela uma.")
            self.jobs[sid] = job
        self._save_job(job)
        threading.Thread(target=work, daemon=True).start()
        return {"job_id": sid, "state": "running", "output_path": str(output), "next": "Usa job_status até terminar; read_result lê relatórios/fontes."}

    def _save_job(self, job):
        with self.lock:
            value = {k: v for k, v in job.items() if k not in ("process", "cancel", "meta")}
        path = job["meta"] / "job.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def job(self, sid):
        if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{16}", sid):
            raise ValueError("ID de job inválido.")
        with self.lock:
            value = self.jobs.get(sid)
            if value:
                return {k: v for k, v in value.items() if k not in ("process", "cancel", "meta")}
        path = self.root / "jobs" / sid / "job.json"
        if not path.is_file():
            raise ValueError("Job não encontrado.")
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["state"] == "running":
            value["state"] = "interrupted"
        return value

    def execute(self, operation, args):
        if operation not in {t["name"] for t in tools(self.kind)}:
            raise ValueError("Operação desconhecida.")
        if operation == "read_guide":
            guides = self.guides()
            reference = args.get("reference", "main")
            if reference not in guides:
                return {"references": list(guides), "error": "Referência desconhecida."}
            path = guides[reference]
            text = path.read_text(encoding="utf-8", errors="replace")
            offset = max(0, int(args.get("offset", 0)))
            return {"reference": reference, "references": list(guides), "content": text[offset:offset+24000], "next_offset": offset+24000 if len(text) > offset+24000 else None, "third_party_reference": True,
                    "installed_path":str(path), "usage":"Consulta este guia e usa as operações MCP deste adaptador; as dependências já foram instaladas localmente."}
        if operation == "check_dependencies":
            result = process_run([str(self.java), "--version"], self.env, self.root, 15)
            if self.kind == "classrevive":
                result["engines"] = process_run(self.class_command("engines"), self.env, self.root, 20)
            else:
                result["jadx"] = process_run([str(self.java), "-cp", str(self.root / "dependencies/jadx/lib/*"), "jadx.cli.JadxCLI", "--version"], self.env, self.root, 20)
                result["vineflower"] = (self.root / "dependencies/vineflower/vineflower-1.12.0.jar").is_file()
                result["dex2jar"] = (self.root / "dependencies/dex2jar/d2j-dex2jar.bat").is_file()
                result["git_bash"] = git_bash() is not None
            return result
        if operation in ("identify", "inspect"):
            target = input_path(args.get("input_path", ""))
            return process_run(self.class_command(operation, target), self.env, self.root, 45)
        if operation in ("decompile_start", "diagnose_start"):
            return self.start(args, diagnose=operation == "diagnose_start")
        if operation == "job_status":
            result = self.job(args.get("job_id"))
            meta = self.root / "jobs" / args["job_id"]
            for name in ("stdout", "stderr"):
                path = meta / (name + ".log")
                if path.is_file():
                    result[name + "_tail"] = path.read_text(encoding="utf-8", errors="replace")[-12000:]
            output = Path(result["output_path"])
            if output.is_dir():
                result["files"] = []
                for path in output.rglob("*"):
                    if path.is_file():
                        result["files"].append(str(path.relative_to(output)))
                        if len(result["files"]) >= 120:
                            break
            return result
        if operation == "job_cancel":
            sid = args.get("job_id")
            self.job(sid)
            job = self.jobs.get(sid)
            if job and job["state"] == "running":
                job["cancel"].set()
                if job.get("process"):
                    terminate(job["process"])
            return self.job(sid)
        if operation in ("read_result","list_results"):
            job = self.job(args.get("job_id"))
            output = Path(job["output_path"]).resolve()
            path = (output / args.get("path", "")).resolve()
            if not path.is_relative_to(output):
                raise ValueError("O ficheiro deve estar dentro da pasta de saída deste job.")
            offset = max(0, int(args.get("offset", 0)))
            if operation == "list_results":
                if not path.is_dir():
                    raise ValueError("A pasta de saída ainda não existe ou o caminho não é uma pasta.")
                entries=sorted(path.iterdir(),key=lambda p:(not p.is_dir(),p.name.lower()))
                return {"entries":[{"name":p.name,"directory":p.is_dir(),"size":p.stat().st_size if p.is_file() else None} for p in entries[offset:offset+100]], "next_offset":offset+100 if len(entries)>offset+100 else None}
            if not path.is_file():
                raise ValueError("Ficheiro de resultado não encontrado.")
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Ficheiro demasiado grande. Escolhe um relatório resumido.")
            text = path.read_text(encoding="utf-8", errors="replace")
            return {"content": text[offset:offset+24000], "next_offset": offset+24000 if len(text) > offset+24000 else None}
        if operation == "find_api_calls":
            source = input_path(args.get("source_path", ""), directory=True)
            modes = {"all": "-All", "urls": "-Urls", "retrofit": "-Retrofit", "okhttp": "-OkHttp", "volley": "-Volley", "auth": "-AuthPatterns"}
            mode = args.get("mode", "all")
            if mode not in modes:
                raise ValueError("Modo inválido.")
            return process_run(self.ps_command("find-api-calls.ps1", "-SourceDir", source, modes[mode]), self.env, self.root, 45)
        if operation == "fingerprint":
            target = input_path(args.get("input_path", ""))
            if target.suffix.lower() not in (".apk", ".xapk", ".apks", ".apkm"):
                raise ValueError("A triagem aceita APK/XAPK/APKS/APKM.")
            bash = git_bash()
            if not bash:
                raise ValueError("Instala Git Bash para usar o script original de triagem.")
            shims = self.root / "dependencies/shims"
            shims.mkdir(exist_ok=True)
            command = helper_command("strings")
            (shims / "strings").write_text("#!/usr/bin/env bash\nexec " + " ".join(shell_quote(p) for p in command) + ' "$@"\n', encoding="utf-8", newline="\n")
            env = {**self.env, "PATH": str(shims) + os.pathsep + str(Path(bash).parent.parent / "usr/bin") + os.pathsep + self.env["PATH"]}
            return process_run([bash, bash_path(self.skill / "scripts/fingerprint.sh"), bash_path(target)], env, self.root, 45)
        if operation == "recover_kotlin_names":
            source = input_path(args.get("source_path", ""), directory=True)
            output = new_output(args.get("output_path", ""))
            output.mkdir()
            (output / "by_package").mkdir()
            return self.python_body("recover-kotlin-names.sh", [str(source), str(output)])
        source = input_path(args.get("mapping_path", ""), directory=True)
        if not (source / "mapping.json").is_file():
            raise ValueError("Falta mapping.json nesta pasta.")
        query = str(args.get("query", ""))
        if not query or len(query) > 1000:
            raise ValueError("Indica um nome para pesquisar.")
        mode = args.get("mode", "search")
        if mode not in ("search", "obfuscated", "package"):
            raise ValueError("Modo inválido.")
        tail = [query] if mode == "search" else ["-o" if mode == "obfuscated" else "-p", query]
        return self.python_body("lookup-name.sh", [str(source), *tail])

    def python_body(self, filename, arguments):
        # Estes dois scripts oficiais contêm um programa Python autocontido.
        # Executá-lo diretamente evita dependência de Python/WSL no computador.
        script = self.skill / "scripts" / filename
        text = script.read_text(encoding="utf-8")
        match = re.search(r"<<'PY'\r?\n(.*?)\r?\nPY(?:\r?\n|$)", text, re.S)
        if not match:
            raise ValueError("O script não contém o corpo Python esperado.")
        output = io.StringIO()
        previous = sys.argv
        code = 0
        try:
            sys.argv = ["-", *arguments]
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                try:
                    exec(compile(match.group(1), str(script), "exec"), {"__name__": "__main__"})
                except SystemExit as exc:
                    code = exc.code or 0
        finally:
            sys.argv = previous
        return {"exit_code": code, "stdout": output.getvalue()[:50000], "upstream_script": filename, "execution_mode": "original embedded Python"}


def git_bash():
    candidates = [Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe", Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Git/bin/bash.exe"]
    return next((str(p) for p in candidates if p.is_file()), None)


def bash_path(value):
    value = str(value).replace("\\", "/")
    return "/" + value[0].lower() + value[2:] if re.match(r"^[A-Za-z]:/", value) else value


def shell_quote(value):
    return "'" + str(value).replace("\\", "/").replace("'", "'\"'\"'") + "'"


def helper_command(mode):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--reverse-tools-helper", mode]
    return [sys.executable, str(Path(__file__).resolve()), "--helper", mode]


def helper(mode):
    ensure_stdio()
    if mode != "strings":
        return 2
    # Subconjunto de strings -n 8 exigido pelo fingerprint.sh original.
    data = sys.stdin.buffer.read(256 * 1024 * 1024)
    for match in re.finditer(rb"[\x20-\x7e]{8,}", data):
        sys.stdout.write(match.group().decode("ascii") + "\n")
    return 0


def main(kind, root):
    ensure_stdio()
    adapter = Adapter(kind, root)
    try:
        for line in sys.stdin:
            message = json.loads(line)
            if "id" not in message:
                continue
            try:
                method = message.get("method")
                if method == "server/discover":
                    result = {"resultType": "complete", "supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}, "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "studio-"+kind, "version": "1.0"}}}
                elif method == "initialize":
                    result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "studio-"+kind, "version": "1.0"}}
                elif method == "tools/list":
                    result = {"tools": tools(kind)}
                elif method == "tools/call":
                    params = message.get("params", {})
                    try:
                        value = adapter.execute(params.get("name"), params.get("arguments") or {})
                        result = {"isError": False, "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                    except Exception as exc:
                        result = {"isError": True, "content": [{"type": "text", "text": str(exc)}]}
                else:
                    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Method not found"}}), flush=True)
                    continue
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
            except Exception:
                print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32602, "message": "Pedido inválido."}}), flush=True)
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "--helper":
        raise SystemExit(helper(sys.argv[2]))
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
