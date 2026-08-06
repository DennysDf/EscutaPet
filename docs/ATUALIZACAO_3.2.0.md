# EscutaPet 3.2.0 · atualização e validação

## Escopo entregue

- rascunho editável separado da publicação;
- versões publicadas imutáveis com snapshot integral da configuração e das perguntas;
- execução vinculada à versão e resposta/fila vinculada à pergunta congelada;
- continuidade da versão após reordenação, nova publicação e reinício do worker;
- histórico somente leitura e resumo de impacto antes da publicação;
- ações de fluxo na versão mais recente ou em uma versão fixa;
- cadastro estruturado, aplicação web, WhatsApp, alertas, segmentos e histórico usando a versão da execução;
- migração idempotente com diagnóstico, recuperação de perguntas históricas arquivadas e bloqueio de inconsistências posteriores.

## Banco e migração

Novas tabelas:

- `questionnaire_versions`;
- `questionnaire_version_questions`;
- `questionnaire_version_options`;
- `questionnaire_version_migration_state`;
- `questionnaire_version_migration_issues`.

Novos vínculos:

- `survey_executions.questionnaire_version_id`;
- `survey_answers.version_question_id`;
- `message_queue.version_question_id`;
- `entry_flow_actions.version_mode`;
- `entry_flow_actions.fixed_version_id`.

A primeira inicialização cria a versão inicial e preenche os vínculos legados. Respostas antigas a perguntas arquivadas recebem um snapshot histórico isolado. Depois de concluída a migração, o sistema não inventa versões para registros corrompidos: bloqueia a operação e registra o diagnóstico.

## Verificação

Foram executados os 13 testes automatizados de `scripts/test_*.py`, compilação Python e validação de sintaxe dos JavaScripts alterados. Também foi validada uma atualização real de uma base criada pela 3.1.2: 14 questionários migrados para 14 versões, sem execução sem versão e sem inconsistência.

O teste específico `test_v320_questionnaire_versioning.py` cobre publicação v1, resposta parcial, publicação com edição/reordenação, conclusão na v1, início posterior na v2, rascunho sem efeito operacional, agendamento anterior a nova publicação, fila após reinício, botões, ação fixa e bloqueio de execução sem versão.

## Como atualizar

1. Pare servidor e worker.
2. Copie `app/data/escutapet_v2.sqlite3`, `.env` e `app/data/branding` para um local seguro.
3. Extraia a 3.2.0 e preserve esses dados.
4. Execute `INSTALAR.bat` e `START.bat`.
5. Após a primeira inicialização, execute `python scripts/report_v320_versioning.py`.

Para rollback lógico, execute `python scripts/rollback_v320_versioning.py --confirm`. Em SQLite, o script cria um backup antes de ajustar as ações e não apaga snapshots históricos.

## Riscos remanescentes

- faça a primeira migração com apenas uma instância do sistema ativa;
- não interrompa o processo durante a primeira inicialização;
- uma inconsistência real é bloqueada e precisa ser analisada pelo relatório, não corrigida automaticamente;
- a evolução ampla de relatórios continua reservada para a etapa posterior já definida.
