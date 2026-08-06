# Atualização para EscutaPet 3.5.4

## Preparar para produção

Foi adicionado o arquivo `LIMPAR_PARA_PRODUCAO.bat` na pasta principal.

Antes de executá-lo, feche o sistema, o worker e o Gerenciador EscutaPet. O
BAT pede que seja digitado `APAGAR`, cria um backup e só então limpa os dados
operacionais já existentes.

São removidos:

- leads, pets, consentimentos e sessões de coleta;
- conversas, mensagens, reações, rascunhos, anexos e transcrições;
- respostas, pesquisas/agendamentos, filas, alertas e eventos de webhook;
- histórico operacional de segmentos, auditoria e estado do worker.

São preservados:

- usuários e suas permissões;
- configurações gerais, logos, Z-API e transcrição;
- cidades e dispositivos/pontos de coleta;
- segmentos, regras e automações;
- questionários, versões, perguntas, opções, fluxos e jornadas.

O backup fica em `backups\antes_limpeza_producao_AAAAMMDD_HHMMSS` e inclui o
banco de dados e todas as mídias existentes. Para PostgreSQL, o `pg_dump`
precisa estar disponível no PATH; se ele falhar, a limpeza é interrompida.
