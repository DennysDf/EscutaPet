# EscutaPet 3.2.1 · novo editor de questionários

## Escopo entregue

- cabeçalho fixo com nome, versão publicada, status, rascunho, estado de salvamento e ações;
- abas Geral, Perguntas, Lógica, Canais, Segmentação e alertas e Publicação;
- modos Simples e Avançado, sem apagar configurações ao alternar;
- edição em duas colunas, com lista compacta e somente uma pergunta aberta;
- campos específicos exibidos apenas para o tipo selecionado;
- configurações avançadas recolhidas;
- modelos iniciais editáveis;
- prévias Web, celular, WhatsApp e quiosque;
- revisão de vínculos e impacto antes da publicação;
- navegação responsiva em telas alternadas para celular e tablet;
- múltipla escolha aplicável na Web, quiosque, entrevistador e WhatsApp numerado.

O editor de jornadas da 3.2.2 e os recursos de salvamento automático, recuperação local, conflito e revisões previstos para a 3.2.3 não fazem parte deste pacote.

## Banco e compatibilidade

A atualização acrescenta:

- `questions.settings_json`;
- `questionnaire_version_questions.settings_json`.

Os campos recebem `{}` em bancos existentes. A migração é idempotente e executada no início. Cada publicação passa a congelar também as configurações específicas do tipo, mantendo execuções antigas na versão original.

## Como atualizar

1. Pare servidor e worker.
2. Copie `app/data/escutapet_v2.sqlite3`, `.env` e `app/data/branding` para um local seguro.
3. Extraia a 3.2.1 e preserve esses dados.
4. Execute `INSTALAR.bat` e `START.bat`.
5. Abra um questionário existente, salve um rascunho e confirme a prévia dos canais usados na operação.

## Verificação executada

- compilação completa do código Python;
- validação de sintaxe do JavaScript;
- inicialização interativa do editor em DOM, aplicação de modelo, troca de modo e abertura de prévia;
- 13 testes anteriores preservados;
- novo teste `test_v321_questionnaire_editor.py` para abas, modelos, múltipla escolha, limites, aplicação e snapshot;
- total de 14 testes automatizados em bancos temporários.

## Riscos e operação

- publique somente depois de revisar a aba Publicação;
- pesquisas em andamento continuam na versão em que começaram;
- salvar rascunho não muda pesquisas novas ou ativas;
- mantenha uma cópia do banco antes de qualquer atualização de produção;
- relatórios continuam fora do escopo desta versão.
