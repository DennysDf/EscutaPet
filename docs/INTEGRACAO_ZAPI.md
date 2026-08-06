# Integração Z-API

## Credenciais

A integração usa três valores fornecidos pela Z-API:

- ID da instância;
- token da instância;
- Client-Token.

Eles ficam armazenados no banco da aplicação e não são enviados ao navegador durante a geração do QR Code.

## Dois endereços com funções diferentes

O endpoint da Z-API, como `/send-text`, é utilizado pelo sistema para **enviar** mensagens. Ele é montado internamente com o ID e o token da instância.

Os webhooks fazem o caminho inverso: a Z-API envia eventos para o **domínio público desta aplicação**. Por isso, uma URL `api.z-api.io` nunca pode ser usada como endereço receptor.

Na tela de configurações, o sistema detecta a origem atual usando `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `Host` e `CF-Visitor`. Ao configurar os callbacks, o domínio HTTPS atual tem prioridade. Se o painel estiver aberto por endereço local, uma URL pública salva ou definida em `PUBLIC_BASE_URL` é mantida como alternativa.

## Conexão por QR Code

O botão **Gerar QR Code** consulta o status da instância. Quando ainda estiver desconectada, solicita `/qr-code/image` e devolve ao navegador somente a imagem Base64. A tela faz até três consultas, com intervalo, e para automaticamente quando detectar conexão.

Caso a instância informe um desafio Passkey, o sistema mostra a orientação para concluir a autenticação no painel da Z-API.

## Webhooks cadastrados

| Evento | Endpoint remoto usado | Rota local |
|---|---|---|
| Mensagem recebida | `update-webhook-received` | `/zapi/webhook/receber/{segredo}` |
| Envio/falha | `update-webhook-delivery` | `/zapi/webhook/envio/{segredo}` |
| Entrega/leitura | `update-webhook-message-status` | `/zapi/webhook/status/{segredo}` |
| Conectado | `update-webhook-connected` | `/zapi/webhook/conectado/{segredo}` |
| Desconectado | `update-webhook-disconnected` | `/zapi/webhook/desconectado/{segredo}` |

A operação também configura `update-notify-sent-by-me` e `update-auto-read-message` conforme as caixas marcadas na tela.

Após os `PUT`, o sistema consulta `/me` e compara os cinco endereços e as duas opções. A configuração só fica marcada como conferida quando todos os valores coincidirem.

## Segurança e confiabilidade

- somente URLs públicas HTTPS são aceitas para configuração remota;
- localhost, IPs privados e URLs da própria Z-API são rejeitados como receptores;
- cada instalação gera um segredo aleatório para os callbacks;
- `instanceId` divergente é ignorado;
- grupos são ignorados pelo motor de questionários;
- eventos ficam registrados em `webhook_events`;
- `messageId`, tipo e status formam uma chave idempotente;
- reenvio do mesmo callback incrementa o contador, sem duplicar resposta;
- mensagens `fromMe` podem ser espelhadas sem virar resposta de pesquisa;
- mensagens próprias já registradas pelo worker não são duplicadas.

## Respostas interativas

O worker usa o tipo salvo na fila:

- `buttons` → `/send-button-list`;
- `option_list` → `/send-option-list`;
- `numbered_text` → `/send-text` com opções numeradas;
- `text` → `/send-text`.

O webhook de recebimento reconhece resposta textual, clique em botão e seleção de lista. O `id` da opção é usado antes do texto visível, evitando ambiguidades entre alternativas semelhantes.

## Diagnóstico

O botão **Testar e conferir tudo** valida:

- status conectado;
- dados do aparelho;
- cinco URLs de webhook;
- recebimento de mensagens enviadas pela própria instância;
- leitura automática.

Antes de cadastrar os webhooks, o sistema também acessa a própria rota pública. Se aparecer
`HTTP 502`, o Cloudflare encontrou o domínio, mas não conseguiu chegar ao servidor local.
Confira se o `cloudflared` está em execução e se o `config.yml` do túnel contém:

```yaml
ingress:
  - hostname: pesquisa.seudominio.com
    service: http://127.0.0.1:8040
  - service: http_status:404
```

Depois de reiniciar o túnel, abra uma das URLs de webhook exibidas nas configurações. A rota
deve responder JSON com HTTP 200 antes de clicar em **Configurar os 5 webhooks**.

O teste automatizado `scripts/test_zapi_integration.py` usa respostas HTTP simuladas para validar os contratos sem depender de uma conta externa.
