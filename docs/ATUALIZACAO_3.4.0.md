# EscutaPet 3.4.0 — Jornadas condicionais e ramificadas

## Atualização

1. Pare o servidor e os workers.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da versão 3.4.0, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Atualize o navegador com `Ctrl+F5`.

A inicialização acrescenta automaticamente os campos de condições múltiplas, lógica E/OU, grupos de sorteio, pesos e decisões da sessão. Fluxos anteriores continuam usando a condição simples existente até serem editados.

## Questionários antes da confirmação

No passo **2 · Cadastro**, use **Adicionar etapa inicial**. Essas etapas:

- usam questionários identificados em Tela identificada;
- acontecem imediatamente depois do Cadastro estruturado;
- podem ser encadeadas por **Após ação anterior**;
- são concluídas antes de o sistema enviar o botão de confirmação do WhatsApp.

## Condições múltiplas

Em qualquer ação, clique em **+ Condição** e escolha:

1. a origem: Cadastro estruturado ou uma ação identificada anterior;
2. a pergunta publicada;
3. o operador;
4. uma opção real da pergunta ou um valor numérico/textual.

Use **Todas (E)** quando todas as respostas forem obrigatórias ou **Qualquer uma (OU)** quando uma delas for suficiente. O editor impede referências a etapas futuras e não permite usar respostas anônimas para identificar caminhos.

## Sorteio de caminhos

Preencha o mesmo **Grupo de sorteio** em duas ou mais ações com o mesmo gatilho e a mesma dependência. O peso padrão é 1. O sistema escolhe somente uma opção por coleta, grava a decisão e mantém o caminho ao retomar ou recarregar a sessão.

## Conferência recomendada

1. Abra a aba **Revisão** e corrija diagnósticos.
2. No laboratório, altere confirmação, resposta condicional, tempo e quantidade de pets.
3. Faça um teste completo pelo modo Entrevistador.
4. Confirme que o WhatsApp só é solicitado depois das etapas iniciais.
5. Recarregue a tela e confira que o caminho sorteado não muda.
