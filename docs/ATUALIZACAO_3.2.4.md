# EscutaPet 3.2.5

Esta versão consolida as fases 3.2.2, 3.2.3 e 3.2.5 sobre a base estável da 3.2.1. Relatórios não fazem parte desta entrega.

## Editor visual de jornadas

O fluxo é editado em seis etapas: Identificação, Cadastro, Consentimentos, WhatsApp, Jornada e Revisão. As ações aparecem em linha do tempo e são configuradas em painel lateral. Campos de versão, agendamento, dependência, condição, contexto por pet e comunicação aparecem somente quando aplicáveis.

Dependências usam chaves permanentes. Reordenar, inserir ou remover etapas não transforma posição visual em identidade. As versões publicadas dos questionários continuam congeladas e execuções em andamento não são migradas silenciosamente.

Uma ação de tela também pode depender da resposta de outra ação de tela, desde que seja imediata. Isso permite, por exemplo, exibir um informativo identificado e abrir em seguida uma pesquisa anônima sem associar suas respostas ao lead. Para continuar somente após aceite, selecione `Igual a` e informe `sim`; `Foi respondida` continua após qualquer resposta, inclusive “Não”. Uma tela não pode depender diretamente de uma ação enviada por WhatsApp, pois não há uma sessão de navegador contínua nesse caso.

## Rascunhos e recuperação

Após uma alteração e breve inatividade, o navegador grava uma cópia local e tenta registrar a mesma cópia na tabela `editor_drafts`. Essa tabela é separada de questionários, fluxos, versões, filas e execuções.

Ao reabrir o editor, o usuário pode comparar, restaurar ou descartar o rascunho mais recente. Restaurar apenas repõe os campos na tela; o salvamento normal continua obrigatório. Uma restauração confirmada é registrada em `audit_logs`.

Questionários e fluxos possuem `revision` e `last_edited_by_id`. Se outra sessão salvar primeiro, o POST antigo recebe HTTP 409 e não altera o banco. A interface permite recarregar o servidor, comparar revisões ou duplicar o conteúdo como novo rascunho.

## Laboratório avançado

O laboratório simula:

- a jornada completa;
- passagem de minutos, horas, dias ou períodos longos;
- WhatsApp confirmado ou pendente;
- condição atendida ou não atendida;
- zero ou vários pets;
- uma ação isolada e seus pré-requisitos.

A simulação resolve a versão publicada de cada ação, canal, prazo, confirmação, dependência e quantidade de execuções. Os endpoints retornam `safe: true` e `writes: 0`; não criam leads, filas, execuções, respostas ou chamadas Z-API.

## Migração

Faça backup do banco, `.env` e `app/data/branding`, substitua os arquivos e inicie normalmente. A migração cria `editor_drafts` e acrescenta `revision` e `last_edited_by_id` a questionários e fluxos. Ela é idempotente e preserva o histórico existente.

A compatibilidade inclui bancos da 3.0.2: `city_ids_json` e `device_ids_json` são acrescentados antes dos questionários e fluxos predefinidos serem consultados. Assim, uma atualização existente recebe `[]` como escopo inicial e mantém seus fluxos; uma instalação nova continua usando a estrutura completa criada pelo SQLAlchemy.

## Verificação recomendada

Execute `python scripts/test_upgrade_v302_to_v324.py`, `python scripts/test_v324_recovery_lab.py`, `python scripts/test_conditional_screen_journey.py` e a suíte listada no README. Depois, abra um fluxo real, altere um texto sem salvar, recarregue para validar a recuperação e use o laboratório com confirmação pendente e após dez dias.
