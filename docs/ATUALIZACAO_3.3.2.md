# EscutaPet 3.3.2 — Conversas progressivas e mídias

Atualização cumulativa sobre a 3.3.1. Não cria tabelas nem exige SQL manual.

## O que mudou

- A conversa abre somente as 30 mensagens mais recentes.
- Mensagens antigas são buscadas automaticamente em lotes adaptativos quando o usuário aproxima o scroll do topo.
- Mídias, reações e nomes de remetentes são carregados em consultas agrupadas. Um lote de 40 mensagens usa no máximo seis consultas, independentemente da quantidade de mensagens.
- O seletor de emojis possui categorias, recentes e busca em português; o mesmo modal atende inserção e reações.
- Negrito, itálico, tachado e monoespaçado aparecem formatados na tela, mantendo a sintaxe compatível com WhatsApp no conteúdo enviado.
- Imagens, vídeos e PDFs abrem em visualizador central; outros documentos apresentam opção de download.
- Anexos têm prévia antes do envio, e mensagens novas fora da área visível acionam um contador para voltar ao fim.
- O editor só é limpo depois da confirmação do servidor de que a mensagem entrou na fila.

## Comportamento preservado

O horário de silêncio continua sendo aplicado pelo worker a todas as mensagens da fila, inclusive respostas humanas. Durante esse intervalo, a mensagem fica com o símbolo `◷` e é enviada no próximo horário permitido.

Também permanecem inalterados Z-API, webhooks, worker principal, transcrição, segmentação, questionários, jornadas, mídias já salvas e rascunhos.

## Atualização segura

1. Pare o EscutaPet.
2. Faça backup de `app/data/escutapet_v2.sqlite3`, `.env`, `app/data/media` e `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.3.2, preservando essas pastas e arquivos.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Atualize a página com `Ctrl+F5` no primeiro acesso para descartar ativos antigos do navegador.
