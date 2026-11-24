"""Terminal interativo: um PowerShell persistente ligado por pipes.

Ao contrário de ``terminal.PowerShellSession`` (um comando de cada vez, com a
saída só no fim e limite de 60 s), aqui:
  - cada linha enviada vai para o processo — é um comando quando a consola está
    livre, ou a entrada do programa que estiver a correr (``input()``,
    ``Read-Host``, um REPL);
  - a saída é lida em contínuo e pode ser consultada enquanto o comando corre;
  - não há limite de tempo; ``stop()`` interrompe o que estiver a correr;
  - variáveis, funções e pasta atual mantêm-se entre comandos.

O PowerShell mostra um *prompt* depois de cada comando; substituímo-lo por um
marcador com a pasta atual e o código de saída, que é como se sabe que o
comando acabou. Não é um terminal de ecrã completo: programas que precisam de
controlar o cursor (editores, menus com setas) não funcionam.
"""
from __future__ import annotations

import base64
import codecs
import ctypes
import shutil
import subprocess
import sys
import threading
import uuid

MAX_BUFFER_CHARS = 400_000  # saída guardada para leitura (as partes mais antigas caem)


def _child_pids(parent_pid: int) -> list[int]:
    """Programas lançados por ``parent_pid`` (filhos diretos, sem o conhost da consola)."""
    if sys.platform != "win32":
        return []
    from ctypes import wintypes

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    children = []
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        more = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while more:
            if entry.th32ParentProcessID == parent_pid and entry.szExeFile.lower() != b"conhost.exe":
                children.append(int(entry.th32ProcessID))
            more = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return children


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=15)


class InteractiveShell:
    def __init__(self):
        self._lock = threading.RLock()
        self._process = None
        self._reader = None
        self._context = None      # pasta com que a sessão foi aberta
        self._mark = ""
        self._reset_state()

    def _reset_state(self):
        self._buffer = ""         # saída visível
        self._base = 0            # posição absoluta do início de _buffer
        self._pending = ""        # texto lido ainda por analisar (marcador a meio)
        self._echo = None         # linha de comando cujo eco ainda não foi retirado
        self._echo_acc = ""
        self._busy = False
        self._cwd = ""
        self._exit_code = None
        self._startup_prompts = 0
        self._generation = getattr(self, "_generation", 0) + 1

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _start(self, cwd: str) -> None:
        executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not executable:
            raise RuntimeError("PowerShell não encontrado neste computador.")
        self._mark = "\x1e" + uuid.uuid4().hex[:12]
        init = (
            "[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false);"
            "[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false);"
            "$OutputEncoding=[Console]::OutputEncoding;"
            "function global:prompt { '" + self._mark + "' + $PWD.Path + '|' + $LASTEXITCODE + '|' + $? + \"`n\" }"
        )
        self._process = subprocess.Popen(
            [executable, "-NoLogo", "-NoProfile", "-NoExit", "-Command", init],
            cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._context = cwd
        self._cwd = cwd
        self._startup_prompts = 1  # o prompt inicial não fecha nenhum comando
        process, generation = self._process, self._generation
        self._reader = threading.Thread(target=self._read_loop, args=(process, generation), daemon=True)
        self._reader.start()

    def close(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            self._generation += 1  # o leitor antigo deixa de escrever no estado
            self._busy = False
        if process is not None and process.poll() is None:
            try:
                _kill_tree(process.pid)
            except Exception:  # noqa: BLE001
                pass
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
        if process is not None:
            for stream in (process.stdin, process.stdout):
                try:
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ #
    # Leitura
    # ------------------------------------------------------------------ #
    def _read_loop(self, process, generation) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                data = process.stdout.read(4096)
                if not data:
                    break
                self._feed(decoder.decode(data), generation)
        except (OSError, ValueError):
            pass
        finally:
            with self._lock:
                if generation == self._generation:
                    self._emit(self._pending.replace(self._mark, ""))
                    self._pending = ""
                    if self._busy:
                        self._busy = False
                        self._exit_code = process.poll()

    def _feed(self, text: str, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._pending += text
            while True:
                index = self._pending.find(self._mark)
                if index == -1:
                    # guarda o fim se puder ser o começo de um marcador partido a meio
                    hold = self._pending.rfind("\x1e")
                    if hold != -1 and len(self._pending) - hold < len(self._mark):
                        self._emit(self._pending[:hold])
                        self._pending = self._pending[hold:]
                    else:
                        self._emit(self._pending)
                        self._pending = ""
                    return
                self._emit(self._pending[:index])
                end = self._pending.find("\n", index)
                if end == -1:
                    self._pending = self._pending[index:]
                    return
                self._prompt(self._pending[index + len(self._mark):end])
                self._pending = self._pending[end + 1:]

    def _prompt(self, payload: str) -> None:
        """Marcador do prompt: ``<pasta>|<LASTEXITCODE>|<$?>`` — o comando acabou."""
        parts = payload.strip().rsplit("|", 2)
        if self._startup_prompts > 0:
            self._startup_prompts -= 1
            if len(parts) == 3 and parts[0]:
                self._cwd = parts[0]
            return
        self._flush_echo()
        if len(parts) == 3:
            cwd, code, success = parts
            if cwd:
                self._cwd = cwd
            if self._busy:
                ok = success.strip().lower() == "true"
                self._exit_code = int(code) if code.strip().lstrip("-").isdigit() and not ok else (0 if ok else 1)
        self._busy = False

    def _emit(self, text: str) -> None:
        if not text:
            return
        if self._echo is not None:
            # o PowerShell repete a linha de comando recebida; a interface já a mostra
            self._echo_acc += text
            expected = self._echo + "\n"
            if self._echo_acc.startswith(expected):
                text, self._echo, self._echo_acc = self._echo_acc[len(expected):], None, ""
            elif expected.startswith(self._echo_acc):
                return
            else:
                text, self._echo, self._echo_acc = self._echo_acc, None, ""
            if not text:
                return
        self._buffer += text.replace("\r\n", "\n")
        overflow = len(self._buffer) - MAX_BUFFER_CHARS
        if overflow > 0:
            self._buffer = self._buffer[overflow:]
            self._base += overflow

    def _flush_echo(self) -> None:
        if self._echo is not None:
            text, self._echo, self._echo_acc = self._echo_acc, None, ""
            if text:
                self._buffer += text.replace("\r\n", "\n")

    # ------------------------------------------------------------------ #
    # API
    # ------------------------------------------------------------------ #
    def send(self, text: str, cwd: str) -> dict:
        """Envia uma linha: comando (consola livre) ou entrada do programa a correr."""
        with self._lock:
            if not self.alive() or (self._context != cwd and not self._busy):
                self.close()
                self._reset_state()
                self._start(cwd)
            text = text.replace("\r\n", "\n").rstrip("\n")
            if self._busy:
                mode, line = "input", text.replace("\n", " ")
            else:
                mode, line = "command", text
                if "\n" in line:
                    # várias linhas: enviar como uma só instrução, sem prompts intermédios
                    encoded = base64.b64encode(line.encode("utf-8")).decode("ascii")
                    line = ("Invoke-Expression ([Text.Encoding]::UTF8.GetString("
                            "[Convert]::FromBase64String('" + encoded + "')))")
                self._busy = True
                self._exit_code = None
                self._echo, self._echo_acc = line, ""
            cursor = self._base + len(self._buffer)
            try:
                self._process.stdin.write((line + "\n").encode("utf-8"))
                self._process.stdin.flush()
            except (OSError, ValueError) as exc:
                self._busy = False
                raise RuntimeError("A sessão PowerShell terminou. Envia de novo para abrir outra.") from exc
            return {"mode": mode, "cursor": cursor}

    def read(self, cursor: int = 0) -> dict:
        """Saída desde ``cursor`` e estado atual."""
        with self._lock:
            end = self._base + len(self._buffer)
            try:
                cursor = int(cursor or 0)
            except (TypeError, ValueError):
                cursor = 0
            truncated = cursor < self._base
            start = min(max(cursor, self._base), end)
            alive = self.alive()
            return {
                "output": self._buffer[start - self._base:],
                "cursor": end,
                "truncated": truncated,
                "busy": bool(self._busy and alive),
                "alive": alive,
                "cwd": self._cwd,
                "exit_code": self._exit_code,
            }

    def stop(self) -> dict:
        """Interrompe o que está a correr.

        Se o comando lançou programas, termina-os e a sessão continua (com as
        suas variáveis). Se é o próprio PowerShell que está ocupado, a sessão é
        fechada; o envio seguinte abre outra na mesma pasta.
        """
        with self._lock:
            process, busy, cwd = self._process, self._busy, self._cwd or self._context
        if process is None or process.poll() is not None:
            return {"stopped": False, "restarted": False}
        if not busy:
            return {"stopped": False, "restarted": False}
        children = _child_pids(process.pid)
        if children:
            for pid in children:
                try:
                    _kill_tree(pid)
                except Exception:  # noqa: BLE001
                    pass
            return {"stopped": True, "restarted": False}
        self.close()
        with self._lock:
            self._flush_echo()
            self._buffer += "\n[sessão interrompida; o próximo comando abre uma nova]\n"
            self._pending = ""
            self._busy = False
            self._exit_code = None
            self._context = cwd
        return {"stopped": True, "restarted": True}
