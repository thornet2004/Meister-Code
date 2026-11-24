# Release 0.7.4 — texto para a página do GitHub

**Tag:** `v0.7.4` · **Título:** `MeisterCode 0.7.4` · **Ficheiro a anexar:** `dist\Meister-IA-IDE-0.7.4-Setup.exe`

O texto abaixo cola-se na descrição da release.

---

Primeira versão pública da MeisterCode.

## Instalar

Descarrega `Meister-IA-IDE-0.7.4-Setup.exe` e corre-o (Windows 10 ou 11, 64 bits). O instalador não está assinado, por isso o Windows pode mostrar o aviso do SmartScreen.

**SHA-256 do instalador**

```
cc2a99c1382fffc702c4ac64a1eac9a481e5d1cf55f7a3e0c9057b42bd40b7c1
```

Para conferir, no PowerShell: `Get-FileHash .\Meister-IA-IDE-0.7.4-Setup.exe`

As ferramentas não vêm no instalador: instalam-se dentro da app, em **Ferramentas → ⬇ Atualizar ferramentas**.

## O que traz

- Cinco seletores de modelos sempre à vista (Conversa, Código, Imagem, Vídeo, Áudio com voz); a app não escolhe modelos por ti.
- O modelo da conversa passa o trabalho de programar ao modelo de código quando lho pedes.
- Agente de programação com pontos de restauro, validação do projeto e servidores de linguagem.
- «Cérebro» do projeto: o agente mantém um `progresso.md` na pasta do projeto e retoma a partir dele.
- Pedidos longos: os resultados antigos são encurtados perto do limite da janela de contexto; quando um pedido pára por um limite, a app diz porquê e oferece «Continuar».
- Modo «Provedor local» para modelos a correr numa rig (ver o projeto [Meister-HiveOs-IA-Tokens-Miner](https://github.com/thornet2004/Meister-HiveOs-IA-Tokens-Miner)).
- Conversa por voz, acesso pelo telemóvel na rede de casa e 46 ferramentas instaláveis a pedido.

## Limitações conhecidas

- Projeto pessoal em desenvolvimento: muda depressa e não tem garantias.
- Só Windows.
- A app ainda não se atualiza sozinha a partir destas releases: para atualizar, descarrega o instalador novo e corre-o por cima.
