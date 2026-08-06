# EscutaPet 3.3.4 — Confirmação que retoma a jornada

Esta versão corrige a jornada em que o WhatsApp precisa ser confirmado antes de entregar o tablet ou abrir uma pesquisa posterior.

## Atualização

1. Pare o servidor e os workers.
2. Faça uma cópia do banco, do arquivo `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da versão 3.3.4, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Atualize o navegador com `Ctrl+F5`.

Não há alteração de estrutura no banco de dados. A atualização é idempotente e preserva fluxos, questionários, respostas, filas e conversas existentes.

## Como configurar a jornada desejada

No fluxo, em **Confirmação do WhatsApp**, escolha **Exigir antes de concluir**. Em **Jornada**, crie:

1. uma ação **Após confirmação**, pelo canal **Tela identificada**, para o questionário informativo;
2. uma ação **Após ação anterior**, pelo canal **Tela anônima**, dependente da primeira ação e condicionada à resposta **Sim** do informativo.

Depois que a pessoa tocar em **Confirmar meu WhatsApp**, o sistema envia `Obrigado por confirmar seu WhatsApp...`, mantém a sessão do entrevistador aberta e direciona para o informativo. Se a resposta for **Sim**, a pesquisa anônima abre em seguida sem vincular as respostas ao lead.

## Conferência rápida

1. Inicie uma coleta de teste pelo modo entrevistador.
2. Salve o cadastro e confirme pelo botão enviado no WhatsApp.
3. Confira que a tela deixa de exibir apenas “aguardando” e abre o informativo.
4. Responda **Sim** e confira que a pesquisa anônima é aberta.
5. Em **Conversas**, confira a mensagem de agradecimento. Se o horário de silêncio estiver ativo, ela aparecerá como pendente até o próximo horário permitido.
