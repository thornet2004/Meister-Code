# Catálogo de modelos

O OpenRouter sincroniza automaticamente o catálogo no arranque, com cache de 24 horas. A consulta usa `GET /models?output_modalities=all`, incluindo modalidades que não aparecem na resposta de texto por omissão. Nas Configurações, em Provedores, **Catálogo de modelos / atualizar** permite pesquisar, filtrar e forçar a atualização. Não são efetuadas gerações durante a sincronização.

As categorias usam `architecture.output_modalities`. Um modelo que recebe imagens ou vídeo e produz texto é chat, sem ser automaticamente classificado como gerador de imagem/vídeo. A etiqueta adicional **Código** é inferida de termos no ID, nome e descrição; não é uma certificação e outros modelos de chat também podem programar.

Os modelos com modalidades e rotas compatíveis com os adaptadores existentes entram automaticamente nos seletores de Chat, Código, Imagem, Vídeo e Áudio. Um modelo multimodal pode aparecer em várias categorias. Transcrição, embeddings, reranking, decisões e capacidades sem rota compatível ficam visíveis como catálogo, sem serem apresentados como ferramentas executáveis.

A atualização preserva as seleções, nomes e parâmetros personalizados, incluindo contexto 0. Os modelos importados que desaparecem do catálogo são conservados na configuração, mas deixam de aparecer como novas escolhas. Falhas de rede preservam o catálogo guardado. Catálogos parciais são rejeitados para não marcar incorretamente modelos como ausentes.

Referência: https://openrouter.ai/docs/guides/overview/models
