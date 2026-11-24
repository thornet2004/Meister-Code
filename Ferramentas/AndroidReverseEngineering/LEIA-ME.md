# Android Reverse Engineering na app

Origem: https://github.com/SimoneAvogadro/android-reverse-engineering-skill
Commit: 0c7cf89830993df7dfc178498f69952262808bea
A skill original Apache-2.0, guias, referências e scripts não modificados estão
em source/. Preservam-se LICENSE e THIRD_PARTY_NOTICES.md.
O adaptador MCP foi criado para esta app, não é o plugin oficial Claude Code.

O modelo pode ler SKILL.md/referências através de read_guide, verificar
as dependências, decompilar APK/XAPK/JAR/AAR com o script PowerShell original,
pesquisar endpoints com find-api-calls.ps1, recuperar/consultar nomes Kotlin
com o corpo Python original dos scripts e executar a triagem fingerprint.sh.
Os corpos Python são executados pelo runtime da app, sem Python/WSL externo.
A triagem usa Git Bash existente; a app fornece o subconjunto de strings -n 8
necessário (até 256 MB de entrada). Este passo não instala Git globalmente.

Dependências locais: JADX 1.5.6, Vineflower 1.12.0 e dex2jar 2.4. Java 21 é
partilhado de ../ClassRevive/runtime/. Mantém ambas as pastas ao transportar.
Licenças das dependências estão nos ZIPs em downloads/, JARs ou distribuição.
Os hashes oficiais foram conferidos quando disponibilizados; o ZIP do commit
Android e dex2jar não tinham digest de release e têm SHA-256 local registado.

decompile_start devolve job_id; usa job_status, list_results e read_result.
Vineflower moderno pode colocar fontes na raiz da saída, sem sources/.
A ponte conta os ficheiros reais de cada motor e assinala saídas sem fontes
como parciais, conservando o código de saída e logs originais.
A análise de fontes e os padrões recuperados são pistas estáticas, não prova
de comportamento nem garantia de recuperar todos os nomes/endpoints.
