# EscutaPet 3.3.3 — Central de Conversas consolidada

Atualização cumulativa sobre a 3.3.2. Não cria tabelas e não exige executar SQL manual.

## Principais mudanças

- Layout mestre-detalhe: lista de conversas e atendimento funcionam na mesma área, com adaptação própria para celular.
- Busca por contato, número ou prévia e filtros por não lidas, pendentes e encerradas.
- Ações de fixar, marcar como não lida, encerrar/reabrir e atribuir responsável.
- Carga inicial de 30 mensagens, lotes de 40 e janela de até 240 mensagens no navegador.
- Estado de preparação para mídias ainda não baixadas, sem imagem ou link quebrado.
- Modal de emojis e reações, visualizador de imagens, vídeos e PDFs e download privado de documentos.
- Anexo por seleção, arraste ou colagem; gravação de áudio com cronômetro, cancelamento e prévia.
- Rascunho por usuário preservado até o servidor confirmar a entrada da mensagem na fila.
- Nova tentativa para mensagens com falha e aviso do horário de silêncio antes do envio.
- Autorização por cidade aplicada também às APIs de conversa e às mídias.

## Atualização segura

1. Pare servidor, worker principal e worker de transcrição.
2. Faça backup de `app/data/escutapet_v2.sqlite3`, `.env`, `app/data/media` e `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.3.3, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. No primeiro acesso, pressione `Ctrl+F5` para renovar CSS, JavaScript e o cache da PWA.

## Conferência recomendada

1. Abra `/conversas` com um administrador e com um operador limitado a uma cidade.
2. Confirme busca, filtros, atribuição, fixar e encerrar/reabrir.
3. Envie texto, emoji, imagem, PDF e um áudio curto.
4. Confirme os estados `Na fila`, `Enviada`, `Entregue` e `Lida` conforme os webhooks.
5. Durante o horário de silêncio, confirme que a mensagem permanece na fila e é enviada no horário permitido.

Z-API, webhooks, transcrição e regras do worker não foram substituídos por esta atualização.
