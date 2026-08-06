# EscutaPet 3.2.2 · editor visual de jornadas

## Escopo entregue

- seis etapas: Identificação, Cadastro, Consentimentos, WhatsApp, Jornada e Revisão;
- cidades, pontos, modos e status no início da configuração;
- diagnóstico visual dos bindings do Cadastro estruturado;
- consentimentos independentes com detalhes condicionais;
- quatro modos simples de confirmação do WhatsApp;
- linha do tempo com cartões resumidos e configuração em painel lateral;
- reordenação por arrastar, botões e teclado, preservando dependências por chave;
- agenda imediata, por intervalo, dia/horário, próximo dia útil e data/hora fixa;
- campos de dependência, condição, pet e WhatsApp exibidos somente quando aplicáveis;
- revisão de cronologia, conflitos, publicações, órfãos, ciclos e mensagens;
- laboratório com teste completo, somente cadastro e simulações sem envio real.

## Banco e compatibilidade

A inicialização acrescenta de forma idempotente:

- `entry_flows.consent_research_enabled`;
- `entry_flows.consent_marketing_enabled`;
- `entry_flows.consent_terms_enabled`;
- `entry_flows.city_ids_json`;
- `entry_flows.device_ids_json`;
- `entry_flow_actions.fixed_scheduled_at`.

Fluxos existentes mantêm os três consentimentos ativados. Ações, questionários, versões, respostas e dependências não são recriados. O agendamento fixo é convertido do fuso configurado no sistema para UTC antes de ser salvo.

## Como atualizar

1. Pare servidor e worker.
2. Copie `app/data/escutapet_v2.sqlite3`, `.env` e `app/data/branding` para um local seguro.
3. Extraia a 3.2.2 e preserve esses dados.
4. Execute `INSTALAR.bat` e `START.bat`.
5. Abra os fluxos ativos, confira as seis abas e execute a Revisão.
6. Teste um fluxo completo e o modo “somente cadastro” antes de liberar o uso.

## Verificação executada

- compilação completa do Python e validação de sintaxe do JavaScript;
- renderização autenticada do editor e teste interativo em DOM;
- preservação dos 14 testes anteriores;
- novo teste `test_v322_visual_journeys.py` para migração, interface, consentimentos, escopo, data fixa e laboratório;
- total de 15 testes automatizados em bancos temporários.

## Fora do escopo

- relatórios;
- salvamento automático;
- recuperação local;
- resolução de conflitos;
- revisões de rascunho e homologação.

Esses itens não foram antecipados para manter o limite definido entre a 3.2.2 e a 3.2.3.
