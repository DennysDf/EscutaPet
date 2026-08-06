# Correção do domínio dos webhooks — 2.1.1

## Regra

- `api.z-api.io/.../send-text` é endpoint de saída.
- `https://seu-dominio/.../zapi/webhook/...` é endpoint de entrada.

## Detecção automática

Ao clicar em **Configurar os 5 webhooks**, a aplicação identifica o endereço público usado na requisição administrativa. São considerados, nesta ordem, os cabeçalhos padronizados de proxy e o host da própria requisição.

A configuração anterior é reparada quando estiver vazia ou contiver uma URL da Z-API. O domínio atual HTTPS é salvo sem caminhos, consultas ou fragmentos.

## Uso com proxy ou túnel

O proxy deve preservar ao menos:

- `Host` ou `X-Forwarded-Host`;
- `X-Forwarded-Proto: https` ou `Forwarded: proto=https`.

Cloudflare também pode informar o esquema por `CF-Visitor`.

Quando o painel só puder ser aberto localmente, defina opcionalmente no `.env`:

```env
PUBLIC_BASE_URL=https://pesquisa.seudominio.com
```
