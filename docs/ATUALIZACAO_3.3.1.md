# EscutaPet 3.3.1 — Transcrição e segmentação de conversas

Esta atualização é cumulativa sobre a 3.3.0 e preserva banco, mídias, questionários, jornadas, conversas e segmentos.

## Recursos

- Worker de transcrição independente do servidor e da fila de envio.
- Uma transcrição por vez, indicada para Windows Server com 4 vCPU e 8 GB de RAM.
- Áudios recebidos e, opcionalmente, enviados convertidos pelo FFmpeg e transcritos localmente pelo `whisper.cpp`.
- Modelo `base` multilíngue quantizado configurado para português.
- Estados aguardando, processando, concluído e falha visíveis na conversa.
- Transcrição vinculada à mídia e à resposta do questionário, quando existente.
- Segmentação de mensagens livres e transcrições recebidas usando os segmentos inteligentes e suas palavras/sinônimos.
- Auditoria do motivo, confiança e origem de cada entrada no segmento.

## Preparação no Windows

1. Atualize os arquivos e execute `START.bat` uma vez para atualizar o banco.
2. Execute `PREPARAR_TRANSCRICAO.bat` com internet disponível.
3. Reinicie o EscutaPet.
4. Abra `/configuracoes`, localize **Áudios · transcrição local** e habilite a função.
5. Para uma VPS com 4 vCPU, mantenha 2 threads e apenas áudios recebidos marcados.

O ZIP não inclui os binários nem o modelo porque esses componentes ocupam centenas de megabytes. O preparador baixa as versões indicadas diretamente dos projetos oficiais.

## Atualização segura

Antes de substituir os arquivos, faça backup de `app/data/escutapet_v2.sqlite3`, `.env` e `app/data/media`. A primeira inicialização cria automaticamente as tabelas e colunas de transcrição; não é preciso executar SQL manualmente.
