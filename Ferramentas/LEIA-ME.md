# Ferramentas da app

Cada subpasta pode conter um servidor MCP e um `ferramenta.json` (versão 1).
Copiar apenas um repositório não define como o iniciar: inclui o manifesto.
A app deteta os manifestos nas configurações e antes de usar ferramentas.
Não executa instalações nem scripts de setup de ferramentas desconhecidas.
Com `enabled: true`, o servidor pode arrancar quando o modelo o pesquisar/utilizar.

Exemplo (guarda como `MinhaFerramenta/ferramenta.json` e ajusta os caminhos):
```json
{
  "version": 1,
  "name": "Minha ferramenta",
  "description": "Explica ao modelo para que serve.",
  "enabled": true,
  "approval": "each",
  "server": {
    "transport": "stdio",
    "command": "node",
    "args": ["${tool_dir}/servidor.js"],
    "cwd": "${workspace}",
    "env": {}
  }
}
```
Variáveis de caminhos: `${tool_dir}`, `${app_dir}`, `${workspace}`.
`approval` aceita `each` ou `auto`; as opções da interface têm precedência.
Usa caminhos absolutos para executáveis quando não estiverem no PATH.
Servidores HTTP também são aceites com `transport: http` e `url`.
Não coloques segredos nos argumentos ou na descrição. Campos env/headers de
manifestos são ficheiros locais em texto; a interface oculta os seus valores.
Para scripts CLI sem MCP é necessário um adaptador que exponha as operações.
Skills/instruções por si só não são servidores executáveis.

Também podes usar `Ferramentas` dentro de um projeto: só aparece quando esse
projeto estiver ativo. Esta pasta junto à app disponibiliza ferramentas globais.
Desativar na interface impede novas chamadas; não apaga a pasta.
