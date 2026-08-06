# Atualização para EscutaPet 3.5.0

## Antes de atualizar

1. Pare o servidor, o worker e o worker de transcrição.
2. Faça uma cópia de `app/data/escutapet.db`, do arquivo `.env`, de `app/data/branding` e das mídias recebidas.
3. Substitua somente os arquivos da aplicação pelos da versão 3.5.0.
4. Preserve os arquivos e diretórios citados no passo anterior.
5. Execute `INSTALAR.bat` para conferir as dependências e depois `START.bat`.
6. Atualize o navegador com `Ctrl+F5`.

## O que muda

A navegação passa a exibir **Agendamentos**, uma central única para as execuções criadas por jornadas D+2/D+7, questionários recorrentes, campanhas segmentadas, ações manuais e testes do WhatsApp.

A central permite:

- filtrar por estado, origem, questionário, segmento, canal, período e produção/testes;
- acompanhar o volume de hoje e dos próximos sete dias;
- conferir lead, pet, origem, versão congelada, quantidade de perguntas e último estado da fila;
- enviar agora, reagendar, cancelar com motivo ou repetir uma mensagem com falha;
- iniciar um teste real isolado no WhatsApp.

## Compatibilidade e segurança

Não é criado um segundo agendador. A Central utiliza `survey_executions`, `message_queue` e o worker existentes. Por isso, continuam valendo o horário de silêncio, o limite de contatos, o consentimento, a confirmação do número, a idempotência e a versão publicada que já estava vinculada à execução.

Datas continuam armazenadas em UTC e são exibidas e editadas no fuso configurado para o usuário ou, na ausência dele, no fuso padrão do sistema. Operadores enxergam e operam somente as cidades autorizadas. Testes ficam separados da produção e não alimentam métricas, segmentos, alertas ou limites de contato.

## Verificação rápida

1. Abra **Agendamentos** e confira as pesquisas futuras já existentes.
2. Filtre por um questionário D+2 ou D+7.
3. Reagende uma execução de homologação e confirme o horário exibido.
4. Use **Testar WhatsApp** com um número autorizado.
5. Confirme que o worker está ativo e acompanhe o estado da fila na própria linha da execução.
