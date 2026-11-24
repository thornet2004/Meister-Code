---
name: analisar-protocolos
description: Descobrir ferramentas da bancada e analisar capturas série, I2C, SPI, CAN ou SCPI com parâmetros explícitos.
---

Para ferramentas da bancada, começa por ferramentas_listar e pesquisa os schemas
da ferramenta relevante com ferramentas_pesquisar. Não inventes IDs, comandos
nem parâmetros. Verifica o estado e os requisitos da ferramenta antes de a usar.

Distingue RS232 de TTL, interface física de protocolo, captura existente de
aquisição ao vivo e dados reais de simuladores. Usa a porta, taxa, interface e
modelo de equipamento conhecidos para a tarefa; se não estiverem disponíveis,
explica quais são necessários. Não atribuas significados a bytes sem evidência.

Num agente de leitura, analisa apenas ficheiros já disponíveis com as ferramentas
permitidas. O acesso MCP à bancada requer um perfil e permissões compatíveis.
Esta skill não instala drivers nem muda firmware ou configurações do Windows.
