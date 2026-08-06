# Atualização para EscutaPet 3.6.0

## Objetivo

A versão 3.6.0 transforma as automações de segmentos em jornadas individuais. Além das campanhas por calendário, o sistema passa a inscrever cada lead quando ele entra em um segmento e mantém o próximo envio, o ciclo e o histórico de pesquisas daquele lead.

## Antes de atualizar

1. Feche `START.bat`, o worker e o Gerenciador EscutaPet.
2. Faça backup do banco de dados, do arquivo `.env` e da pasta `app/data/branding`.
3. Substitua os arquivos da aplicação, preservando os dados acima.
4. Execute `INSTALAR.bat` e depois `START.bat`.

## Migração automática

Na primeira inicialização, o sistema:

- adiciona as opções de gatilho, atraso, estratégia, janela, amostra e proteção em `segment_automations`;
- cria `segment_automation_questionnaires`, que permite vários questionários por automação;
- cria `segment_automation_enrollments`, com um estado individual por lead;
- vincula o questionário principal de cada automação antiga à nova coleção;
- preserva o comportamento antigo de “Excluir quem já recebeu”.

A migração é idempotente e funciona em instalações novas ou atualizadas. Não apague as tabelas novas depois de começar a usar jornadas por entrada, pois elas guardam ciclos e chaves contra duplicidade.

## Novos gatilhos

- **Campanha por calendário:** consulta o público atual agora, em uma data ou de forma recorrente.
- **Ao entrar no segmento:** cria um próximo envio individual para cada novo integrante.
- **Entrada + recorrência:** agenda na entrada e repete individualmente a cada quantidade configurada de dias.

O worker atualiza as regras dos segmentos antes de consumir as execuções. Assim, quando um lead sai de um segmento com “Cancelar ao sair” ativado, sua inscrição e as pesquisas ainda agendadas são canceladas antes do envio.

## Estratégias de pesquisa

Uma automação pode usar uma ou várias pesquisas publicadas para WhatsApp:

- primeira pesquisa fixa;
- escolha aleatória;
- escolha aleatória sem repetição até completar o conjunto;
- rodízio na ordem selecionada.

## Horários e proteção

É possível configurar horário fixo, janela randômica ou distribuição estável, amostra fixa ou renovada por ciclo, intervalo mínimo, máximo de ciclos, WhatsApp confirmado, uma pesquisa por vez e cancelamento ao sair do segmento.

## Verificação recomendada

Execute:

```bash
python scripts/test_v360_smart_segment_automations.py
python scripts/test_v325_segments.py
python scripts/test_v350_schedules.py
python scripts/test_smoke.py
```

Depois abra `/segmentos`, escolha um segmento e confira a aba **Automações**.
