---
name: rever-codigo
description: Rever alterações de código e reportar problemas concretos, com ficheiros, linhas e evidência.
---

Usa as ferramentas de pesquisa e leitura para localizar a implementação e os
testes relevantes. Respeita AGENTS.md, incluindo as regras das subpastas.
Consulta git_consultar para ver diferenças quando houver um repositório Git.
Usa lsp_diagnosticos para erros de tipos/sintaxe; distingue resultados pendentes
de uma análise concluída. Não assumes que diagnósticos vazios provam correção.

Apresenta problemas verificáveis, com caminho, linha, impacto e sugestão.
Distingue defeitos de preferências de estilo. Se não encontrares problemas,
indica o que foi verificado e o que ficou por testar. Esta skill não concede
permissão para editar ou executar comandos num agente de leitura.
