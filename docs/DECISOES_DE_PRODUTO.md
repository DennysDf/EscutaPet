# Decisões de produto — EscutaPet Inteligente 2.0

## O que foi unificado

| Antes | Agora |
|---|---|
| Banco de perguntas | Perguntas dentro do questionário |
| Templates | Mensagens de abertura e encerramento |
| Réguas | Momento, atraso e recorrência |
| Jornadas e transições | Opções, segmentos e alertas por resposta |
| Agenda | Execuções geradas pelo próprio questionário |
| Laboratório | Botão Testar no editor |
| Ocorrências | Alertas |
| Tutores | Leads |

## Regras principais

1. WhatsApp é sempre identificado pelo telefone.
2. Anonimato é permitido somente em quiosque e entrevistador.
3. Segmentação explícita tem prioridade sobre similaridade.
4. A classificação automática registra motivo e confiança.
5. Alertas identificados podem nascer de uma resposta individual.
6. Alertas anônimos são somente agregados após o mínimo configurado.
7. O worker é o único responsável por iniciar execuções agendadas e enviar mensagens.
8. Testes são marcados com `is_test` e não entram nos indicadores principais.

## Evolução possível

- embeddings locais para respostas abertas;
- resumos de comentários por período;
- detecção de queda por unidade ou segmento;
- importação de leads por planilha;
- eventos externos de atendimento;
- múltiplas organizações no mesmo servidor;
- fila Redis quando o volume justificar.
