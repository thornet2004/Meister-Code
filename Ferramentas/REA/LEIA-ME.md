# REA na app

Instalação local MIT de https://github.com/morluto/rea.

A licença e os avisos de terceiros estão em package/node_modules/rea-agents/.
O Node inclui as suas licenças na pasta runtime.

Análise estática JavaScript/.NET e outras operações incluídas não exigem Ghidra.
Análise nativa profunda exige motor compatível (por exemplo Ghidra/JDK existentes);
configura os caminhos em server.env do ferramenta.json, conforme a documentação REA.
Não foram instalados Ghidra, IDA, Hopper, Frida nem alterados outros agentes.

Usa Configurações → Ferramentas em pastas para testar, ativar/desativar e escolher
aprovações. As operações são descobertas por pesquisa para poupar contexto.
