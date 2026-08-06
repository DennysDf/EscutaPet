# EscutaPet 3.2.5 — Central de segmentos e automações

## O que mudou

`/segmentos` agora reúne catálogo de públicos, integrantes, regras, automações e evolução. A interface apresenta total atual, leads elegíveis, WhatsApps confirmados e entradas recentes antes das configurações avançadas.

O construtor combina regras de cidade, bairro, origem, nome, espécie, raça, confirmação do WhatsApp e consentimento. É possível exigir todas as condições ou pelo menos uma. O worker reavalia os públicos automaticamente; o botão “Atualizar público” permite conferência imediata.

As automações aceitam questionários identificados, ativos, publicados e habilitados para WhatsApp. Podem executar agora, em data futura ou de forma recorrente. Antes de confirmar, a prévia separa elegíveis, pessoas sem consentimento, sem WhatsApp, não confirmadas e quem já recebeu o questionário.

## Segurança operacional

- O público é recalculado antes de cada execução.
- Consentimento, opt-out, status do lead, horário de silêncio e limites globais continuam sendo verificados.
- A amostra percentual é estável para evitar escolhas aleatórias diferentes a cada prévia.
- A opção “Excluir quem já recebeu” evita duplicidade do mesmo questionário.
- Pesquisas anônimas não aparecem nas automações identificadas de segmentos.
- A versão publicada do questionário é congelada em cada execução.

## Histórico

Entradas, atualizações e saídas são preservadas em `segment_events`. Vínculos existentes recebem um marco inicial de migração com sua data original. Remover um segmento de um lead não apaga mais a movimentação histórica.

## Atualização

Faça backup do banco, `.env` e `app/data/branding`. Substitua os arquivos e inicie normalmente. `Base.metadata.create_all` cria as novas tabelas de regras, automações e eventos, e o bootstrap registra o marco inicial dos vínculos existentes. A operação é idempotente.

## Verificação

Execute `python scripts/test_v325_segments.py`, `python scripts/test_upgrade_v302_to_v324.py`, `python scripts/test_visual_ui.py` e a suíte descrita no README.
