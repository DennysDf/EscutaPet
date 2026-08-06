# Fluxos de entrada — EscutaPet 2.2

## Objetivo

Um fluxo de entrada coordena o cadastro inicial e as pesquisas posteriores sem expor ao administrador conceitos técnicos como régua, template ou jornada.

## Modos

- **Quiosque:** preenchimento autônomo, botões grandes e navegação em três etapas.
- **Entrevistador:** mesma estrutura, com busca segura de cadastro anterior, observação interna e confirmação manual opcional.

A busca de dados anteriores exige usuário autenticado. No quiosque, o telefone existente pode atualizar o mesmo lead, mas o navegador público não recebe nome ou pets anteriores por uma API de consulta.

## Dados estruturados

- `entry_flows`: configuração do fluxo;
- `collection_sessions`: cada entrada realizada;
- `collection_pets`: pet, motivo e serviço na entrada;
- `phone_verifications`: confirmação do número e estados da mensagem;
- `consent_receipts`: aceite ou recusa por finalidade e versão dos termos;
- `survey_executions.collection_session_id`: vínculo apenas para pesquisas identificadas.

## Confirmação

O botão enviado possui identificador `verify_phone:<token>`. O webhook de mensagens recebidas resolve esse identificador antes de tratar respostas de questionários. Ao confirmar:

1. `Lead.number_validated` recebe `true`;
2. a verificação registra data e estado;
3. a sessão avança;
4. a ação pós-confirmação é liberada;
5. o acompanhamento que exige validação é agendado.

## Ações posteriores

O editor oferece três blocos:

1. **Imediatamente após salvar**;
2. **Depois de confirmar o número**;
3. **Acompanhamento agendado**.

Os canais de tela validam a compatibilidade entre pesquisa identificada e anônima. O WhatsApp bloqueia questionários anônimos.

## Anonimato

Uma pesquisa anônima iniciada após o cadastro não recebe `lead_id` nem `collection_session_id`. A aplicação usa apenas uma referência temporária na sessão do navegador para oferecer o botão de retorno ao final.
