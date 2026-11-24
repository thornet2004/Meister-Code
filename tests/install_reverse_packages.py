"""Instala os pacotes pedidos a partir de releases/commit fixos, sem setup global."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / "Ferramentas"


def download(url, path, expected=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected and digest != expected:
            raise ValueError("O ficheiro existente não tem a integridade esperada: " + str(path))
        return digest
    temporary = path.with_suffix(path.suffix + ".part")
    digest = hashlib.sha256()
    print("A descarregar " + path.name, flush=True)
    with requests.get(url, stream=True, timeout=(20, 45)) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(1024 * 256):
                digest.update(chunk)
                handle.write(chunk)
    value = digest.hexdigest()
    if expected and value != expected:
        raise ValueError("Integridade incorreta: " + path.name)
    temporary.replace(path)
    return value


def extract(archive, destination, strip_root=False):
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            relative = member.filename.replace("\\", "/")
            if strip_root:
                relative = relative.partition("/")[2]
            if not relative:
                continue
            target = (base / relative).resolve()
            if not target.is_relative_to(base):
                raise ValueError("Caminho inválido no ZIP.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, target.open("wb") as handle:
                    while chunk := source.read(256 * 1024):
                        handle.write(chunk)


def install():
    specifications = [
        ("ClassRevive", "classrevive-0.1.0.zip", "https://github.com/t1zzo/classrevive/releases/download/v0.1.0/classrevive-0.1.0.zip", "1362edbca3110f5ee9090b718623d6f9ad2736fb039cbb4fef4da01cf51235c5", "distribution", True),
        ("ClassRevive", "OpenJDK21U-jdk_x64_windows_hotspot_21.0.13_9.zip", "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.13%2B9/OpenJDK21U-jdk_x64_windows_hotspot_21.0.13_9.zip", "a4dbaa05fca4bd89d84584e58c459bd732efebb1722af80ab13c6516832004f9", "runtime", False),
        ("AndroidReverseEngineering", "source-0c7cf898.zip", "https://codeload.github.com/SimoneAvogadro/android-reverse-engineering-skill/zip/0c7cf89830993df7dfc178498f69952262808bea", None, "source", True),
        ("AndroidReverseEngineering", "jadx-1.5.6.zip", "https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip", "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974", "dependencies/jadx", False),
        ("AndroidReverseEngineering", "vineflower-1.12.0.jar", "https://github.com/Vineflower/vineflower/releases/download/1.12.0/vineflower-1.12.0.jar", "1dfcfe974395734fa467ce620661c7623d05ba83670de0529b1fbd63ff548b9d", "dependencies/vineflower", False),
        ("AndroidReverseEngineering", "dex-tools-v2.4.zip", "https://github.com/pxb1988/dex2jar/releases/download/v2.4/dex-tools-v2.4.zip", None, "dependencies/dex2jar", True),
    ]
    provenance = {}
    for name, filename, url, expected, target, strip in specifications:
        folder = ROOT / name
        archive = folder / "downloads" / filename
        digest = download(url, archive, expected)
        destination = folder / target
        if filename.endswith(".zip"):
            extract(archive, destination, strip)
        else:
            destination.mkdir(parents=True, exist_ok=True)
            output = destination / filename
            if not output.exists():
                output.write_bytes(archive.read_bytes())
        provenance.setdefault(name, []).append({"file": filename, "url": url, "sha256": digest, "upstream_digest_checked": bool(expected)})
        (folder / "provenance.json").write_text(json.dumps(provenance[name], indent=2), encoding="utf-8")
        print("Instalado " + filename, flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    install()
