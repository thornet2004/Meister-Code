"""Deteção de comandos perigosos pedidos pelo agente.

``assess(comando, base)`` devolve a lista de motivos (em português) pelos quais
um comando deve ser sempre confirmado pelo utilizador, mesmo no modo de
aprovação automático. Lista vazia = sem padrões perigosos conhecidos.

É uma rede de segurança por padrões de texto, não uma garantia: um comando
pode ser destrutivo sem cair em nenhum padrão (por exemplo, um script que o
próprio agente escreveu). Falsos positivos custam só uma confirmação.
"""

from __future__ import annotations

import os
import re

_FLAGS = re.IGNORECASE | re.DOTALL

# (expressão, motivo)
_RULES = [
    (r"(?<![\w-])format(?:\.com)?\s+[a-z]:|\bformat-volume\b|\bdiskpart\b|\bclear-disk\b|\binitialize-disk\b"
     r"|\bremove-partition\b|\bmkfs(?:\.\w+)?\b|\bdd\b[^|;&]*\bof=/dev/",
     "formata, limpa ou reparticiona um disco"),
    (r"\bshutdown(?:\.exe)?\s+[/-][srhpl]\b|\bstop-computer\b|\brestart-computer\b",
     "desliga ou reinicia o computador"),
    (r"\bbcdedit\b|\bvssadmin(?:\.exe)?\s+delete\b|\bwbadmin(?:\.exe)?\s+delete\b|\bshadowcopy\s+delete\b|\bcipher(?:\.exe)?\s+/w",
     "altera o arranque do Windows ou apaga cópias de segurança do sistema"),
    (r"\breg(?:\.exe)?\s+delete\s+[\"']?hk(?:lm|ey_local_machine|cr|ey_classes_root)\b"
     r"|\bremove-item(?:property)?\b[^|;&]*\bhk(?:lm|cr):",
     "apaga chaves do registo do sistema"),
    (r"\bset-mppreference\b[^|;&]*-disable|\bnetsh\s+advfirewall\s+set\b[^|;&]*\bstate\s+off"
     r"|\bset-netfirewallprofile\b[^|;&]*-enabled\s+(?:\$?false|0)\b|\bsc(?:\.exe)?\s+(?:stop|delete|config)\s+windefend\b",
     "desliga proteções do Windows (Defender ou firewall)"),
    (r"\bnet1?\s+user\s+\S+[^|;&]*\s/(?:add|delete)\b|\bnet1?\s+localgroup\s+administra|\bnew-localuser\b"
     r"|\bremove-localuser\b|\badd-localgroupmember\b",
     "cria, remove ou promove contas de utilizador"),
    (r"\b(?:iwr|irm|invoke-webrequest|invoke-restmethod|curl|wget)\b[^|;&]*\|\s*(?:iex|invoke-expression|sh|bash|zsh|powershell|pwsh|python\d?)\b"
     r"|\b(?:iex|invoke-expression)\b[^|;&]*\b(?:iwr|irm|invoke-webrequest|invoke-restmethod|downloadstring|net\.webclient)\b"
     r"|\bdownloadstring\s*\(",
     "descarrega código da internet e executa-o de seguida"),
    (r"\b(?:powershell|pwsh)(?:\.exe)?\b[^|;&]*\s-e(?:nc|ncodedcommand)?\s+[a-z0-9+/=]{20,}",
     "usa um comando codificado, que não se consegue ler"),
    (r"\bset-executionpolicy\b(?![^|;&]*-scope\s+(?:process|currentuser)\b)[^|;&]*\b(?:unrestricted|bypass)\b",
     "retira a proteção de execução de scripts para todo o computador"),
]
_RULES = [(re.compile(pattern, _FLAGS), reason) for pattern, reason in _RULES]

# Apagar de forma recursiva: PowerShell (Remove-Item -Recurse), cmd (rd /s, del /s) e Unix (rm -rf).
_DELETE = re.compile(
    r"(?<![\w-])(?:remove-item|ri|rm|rmdir|rd|del|erase)(?:\.exe)?\b(?P<rest>[^|;&\n]*)", _FLAGS)
_RECURSIVE = re.compile(r"(?:^|\s)(?:-r\b|-rf\b|-fr\b|-recurse\b|--recursive\b|/s\b|-[a-z]*r[a-z]*f[a-z]*\b|-[a-z]*f[a-z]*r[a-z]*\b)", _FLAGS)
# Alvos que nunca devem ser apagados em árvore, estejam onde estiverem.
_ROOT_TARGET = re.compile(
    r"(?:^|[\s\"'])(?:[a-z]:[\\/]?(?:\*|\.)?(?=$|[\s\"'])"                      # C:  C:\  C:\*
    r"|[a-z]:[\\/](?:windows|users|program files(?: \(x86\))?|programdata)[\\/]?(?=$|[\s\"'*])"
    r"|~[\\/]?(?=$|[\s\"'*])|\$home\b[\\/]?(?=$|[\s\"'*])"
    r"|\$env:(?:userprofile|systemroot|windir|systemdrive|homepath)\b[\\/]?(?=$|[\s\"'*])"
    r"|%(?:userprofile|systemroot|windir|systemdrive|homepath)%[\\/]?(?=$|[\s\"'*])"
    r"|/(?:\*)?(?=$|[\s\"'])|/(?:etc|usr|bin|sbin|home|var|boot|root|lib)[\\/]?(?=$|[\s\"'*]))", _FLAGS)
_ABSOLUTE = re.compile(r"\"([a-z]:[\\/][^\"]*)\"|'([a-z]:[\\/][^']*)'|(?<![\w])([a-z]:[\\/][^\s\"']*)", _FLAGS)
_TRAVERSAL = re.compile(r"(?:^|[\s\"'\\/])\.\.(?:[\\/]|$|[\s\"'])")


def _inside(path: str, base: str) -> bool:
    try:
        target = os.path.normcase(os.path.normpath(path))
        root = os.path.normcase(os.path.normpath(base))
    except (TypeError, ValueError):
        return False
    return target == root or target.startswith(root + os.sep)


def _recursive_delete_reasons(command: str, base: str | None) -> list[str]:
    reasons = []
    for match in _DELETE.finditer(command):
        rest = match.group("rest") or ""
        if not _RECURSIVE.search(rest):
            continue
        if _ROOT_TARGET.search(rest):
            reasons.append("apaga em árvore uma pasta do sistema, a pasta pessoal ou a raiz de um disco")
            continue
        outside = False
        for quoted, single, bare in _ABSOLUTE.findall(rest):
            path = quoted or single or bare
            if not base or not _inside(path, base):
                outside = True
        if outside or _TRAVERSAL.search(rest):
            reasons.append("apaga pastas em árvore fora da pasta do projeto")
    return reasons


def assess(command: str, base: str | None = None) -> list[str]:
    """Motivos pelos quais ``command`` exige confirmação explícita (lista vazia se nenhum)."""
    text = (command or "").strip()
    if not text:
        return []
    reasons = [reason for pattern, reason in _RULES if pattern.search(text)]
    reasons += _recursive_delete_reasons(text, base)
    unique = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique
