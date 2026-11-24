# Diagnósticos de código

Servidores externos em `Ferramentas/_Runtime/lsp/node_modules`:

- Pyright 1.1.414 — Microsoft — MIT — https://github.com/microsoft/pyright
- typescript-language-server 6.0.3 — TypeFox/contribuidores — MIT — https://github.com/typescript-language-server/typescript-language-server
- TypeScript 5.9.3 — Microsoft — Apache-2.0 — https://github.com/microsoft/TypeScript
- vscode-langservers-extracted 4.10.0 (servidores HTML, CSS e JSON do VS Code) — Microsoft; empacotado por hrsh7th — MIT — https://github.com/hrsh7th/vscode-langservers-extracted
- bash-language-server 5.8.1 — Mads Hartmann/contribuidores — MIT — https://github.com/bash-lsp/bash-language-server
- yaml-language-server 2.0.0 — Red Hat — MIT — https://github.com/redhat-developer/yaml-language-server
- intelephense 1.18.5 — Ben Mewburn — **licença proprietária** («Intelephense Licence», gratuita com funções pagas; não é código aberto) — https://intelephense.com — ler o `LICENSE.txt` do pacote antes de redistribuir. Depende de `applicationinsights` (telemetria); a app envia `intelephense.telemetry.enabled = false`.

Os quatro últimos foram acrescentados a 18/11/2026, com as suas dependências
(174 pacotes npm no total, cada um com a sua licença dentro de `node_modules`).
gopls, rust-analyzer e clangd não são distribuídos com a app: só são usados se
o utilizador os tiver instalado.

As licenças originais acompanham os pacotes. O `package-lock.json` regista as
versões e integridades npm usadas. O cliente LSP da app é código próprio; não
foram copiados componentes do OpenCode para implementar esta fase.
