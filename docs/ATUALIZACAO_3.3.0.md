# EscutaPet 3.3.0 — Central de conversas profissional

Esta atualização é cumulativa sobre a 3.2.5. Ela mantém banco, questionários, jornadas, segmentos, configurações e integrações existentes.

## O que foi adicionado

- Central de conversas com aparência de atendimento, resposta citada, reações, anexos, áudio gravado pelo navegador e notas internas.
- Carregamento econômico: a conversa abre com as 50 mensagens mais recentes; o restante só é solicitado ao subir a tela. A lista de conversas também é paginada.
- Fila de mensagens humanas: a mensagem aparece como pendente e muda para enviada, entregue, lida ou falha conforme o worker e os callbacks da Z-API.
- Editor de texto com os marcadores do WhatsApp: `*negrito*`, `_itálico_` e `~tachado~`.
- Assinatura opcional por usuário em **Minha conta**. A assinatura é acrescentada somente quando a opção estiver marcada no envio.
- Rascunhos por usuário e conversa, recuperados após atualizar ou fechar o navegador.

## Atualização segura

1. Pare o `START.bat`/serviço.
2. Faça uma cópia de segurança de `app/data/escutapet.db`, `.env`, `app/data/media` e da pasta de log, se houver.
3. Substitua os arquivos do programa pelos desta versão, preservando esses dados.
4. Execute `START.bat`. As colunas e tabelas novas são criadas automaticamente na primeira inicialização.
5. Abra `/conta` para definir a assinatura de cada atendente, se desejar.

## Áudio e mídia

Para gravar áudio, o sistema precisa abrir em HTTPS público (ou em `localhost`) e o navegador precisa receber permissão para usar o microfone. Arquivos enviados ficam na pasta local de mídias configurada pelo sistema; mantenha backup dessa pasta.
