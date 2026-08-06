# EscutaPet 3.4.1 — Correção do agendamento

## Atualização

1. Pare servidor e workers.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da versão 3.4.1, preservando esses dados.
4. Execute `START.bat`.
5. No primeiro acesso, use `Ctrl+F5` para descartar os arquivos 3.4.0 em cache.

Não há conversão manual do banco. Rascunhos da 3.4.0 cujo campo `schedule_mode` ficou vazio são interpretados como uma ação imediata e podem ser salvos normalmente.

## Conferência

Em **Fluxos → Editar → Jornada**, abra uma ação e confira **Forma de agendar**. Estão disponíveis:

- Agora, imediatamente;
- Após um intervalo;
- Em um horário do dia;
- Próximo dia útil;
- Data e hora fixas.

O aviso de `integrity` referente a `static.cloudflareinsights.com/beacon.min.js` pertence ao Cloudflare Analytics. O navegador pode bloquear esse beacon sem afetar o salvamento do fluxo.
