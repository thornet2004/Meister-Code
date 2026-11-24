"""Sessão PowerShell interativa, sem janela de consola adicional."""
from __future__ import annotations

import base64
import json
import queue
import shutil
import subprocess
import threading
import uuid


class PowerShellSession:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._context = None

    def close(self):
        with self._lock:
            if self._process is not None:
                if self._process.poll() is None:
                    self._process.stdin.close()
                    try:
                        self._process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        # Se houver um comando ativo, termina também os descendentes.
                        subprocess.run(
                            ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                            timeout=10,
                        )
                        if self._process.poll() is None:
                            self._process.kill()
                        self._process.wait(timeout=5)
                if self._process.stdin and not self._process.stdin.closed:
                    self._process.stdin.close()
                self._reader.join(timeout=1)
                if not self._reader.is_alive():
                    self._process.stdout.close()
                self._process = None

    def _start(self, cwd):
        executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not executable:
            raise RuntimeError("PowerShell não encontrado neste computador.")
        self._prefix = uuid.uuid4().hex
        script = r'''
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
while (($__studioLine = [Console]::ReadLine()) -ne $null) {
    try {
        $__studioRequest = $__studioLine | ConvertFrom-Json
        $LASTEXITCODE = 0
        $__studioRecords = @(. ([scriptblock]::Create($__studioRequest.command)) *>&1)
        $__studioSuccess = $? -and ($LASTEXITCODE -eq 0) -and -not (@($__studioRecords | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] }).Count)
        $__studioOutput = $__studioRecords | Out-String -Width 200
        $__studioResult = @{output=[string]$__studioOutput; cwd=[string](Get-Location).Path; success=$__studioSuccess}
    } catch {
        $__studioResult = @{output=[string]$_; cwd=[string](Get-Location).Path; success=$false}
    }
    [Console]::WriteLine('__PREFIX__' + (ConvertTo-Json -InputObject $__studioResult -Compress))
}
'''.replace("__PREFIX__", self._prefix)
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        self._process = subprocess.Popen(
            [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self._context = cwd
        self._lines = queue.Queue()
        process, lines = self._process, self._lines

        def read_output():
            try:
                for line in process.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        self._reader = threading.Thread(target=read_output, daemon=True)
        self._reader.start()

    def execute(self, command, cwd):
        with self._lock:
            if not self._process or self._process.poll() is not None or self._context != cwd:
                self.close()
                self._start(cwd)
            self._process.stdin.write(json.dumps({"command": command}) + "\n")
            self._process.stdin.flush()
            # O leitor espera por uma resposta completa. O limite também termina descendentes.
            import time
            deadline = time.monotonic() + 60
            while True:
                try:
                    line = self._lines.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    self.close()
                    raise RuntimeError("Comando interrompido após 60 segundos. A sessão foi reiniciada.")
                if line is None:
                    self.close()
                    raise RuntimeError("A sessão PowerShell terminou. O próximo comando abre uma nova sessão.")
                if line.startswith(self._prefix):
                    result = json.loads(line[len(self._prefix):])
                    result["output"] = result.get("output", "")[:100000]
                    return result
