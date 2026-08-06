# Correção do editor e integridade do histórico — 2.1.2

## Causa

O editor executava `row.questions.clear()` e depois recriava as perguntas. Quando uma pergunta já era apontada por `survey_answers` ou `message_queue`, o SQLite recusava o `DELETE` por causa das chaves estrangeiras.

## Solução

1. O navegador envia o ID de cada pergunta existente.
2. O servidor atualiza a pergunta no lugar, mantendo sua chave primária.
3. Perguntas novas recebem novos registros.
4. Perguntas removidas sem histórico são apagadas.
5. Perguntas removidas com histórico ficam `active = false` e recebem `archived_at`.
6. O motor usa somente perguntas ativas.
7. Mensagens ainda pendentes de perguntas removidas são canceladas.

A estratégia preserva respostas antigas, evita o erro 500 e permite continuar editando o questionário normalmente.
