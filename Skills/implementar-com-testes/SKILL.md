---
name: implementar-com-testes
description: Implementar pequenas alterações com leitura prévia, patches, checkpoints e validação relevante.
---

Lê as instruções do projeto e pesquisa o código existente antes de editar.
Usa ler_codigo para obter a versão e SHA-256 atuais; aplica substituições
pequenas e únicas com aplicar_patch. Relê se o hash ou o trecho não corresponder.
Para criar um ficheiro novo usa escrever_ficheiro.

Após editar, considera os diagnósticos LSP e executa os testes adequados às
alterações quando o modo e as permissões o permitirem. Não executes validações
de escrita a partir de um subagente de leitura. Os checkpoints cobrem apenas
as edições diretas; alterações feitas por comandos ou MCP ficam fora deles.

Explica o comportamento final, a validação realizada e as limitações reais.
