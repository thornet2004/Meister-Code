# ClassRevive na app

Programa original v0.1.0: https://github.com/t1zzo/classrevive
A distribuição original, licença própria ClassRevive License 1.0, NOTICE,
avisos e licenças de terceiros estão em distribution/. Não é uma licença MIT.
O adaptador MCP foi criado para esta app e não é fornecido pelo autor original.
A distribuição não foi modificada.

Java 21 Temurin 21.0.13+9 portátil está em runtime/ e também é usado pela skill
Android da pasta irmã. O JDK instalado no sistema não foi alterado.
Os URLs, versões e SHA-256 dos downloads constam de provenance.json.

Operações: ver dependências/guia, identificar/inspecionar um ficheiro,
iniciar decompilação/diagnóstico, acompanhar/cancelar jobs e ler resultados.
A decompilação usa os motores CFR, Vineflower, Procyon e JADX da distribuição.
Os relatórios distinguem recompilação/assinaturas de comportamento:
comportamento permanece NOT_VERIFIED. Não executar os alvos analisados.

Trabalhos demorados devolvem job_id de imediato: usa job_status, list_results e
read_result. As saídas vão para uma pasta nova (por defeito analises/ no projeto
ou conversa ativa); não se substituem pastas existentes. Logs/metadados ficam
em jobs/ desta ferramenta. Desativar/fechar a app interrompe jobs ainda ativos.
