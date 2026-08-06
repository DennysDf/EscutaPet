# Guia rápido da versão 3

## Preparação

1. Cadastre as cidades em **Cidades e pontos**.
2. Crie os pontos de coleta e associe cada um à cidade correta.
3. Em **Usuários**, defina quem acessa todas as cidades e quem possui escopo restrito.
4. Altere sua senha e aparência em **Minha conta**.

## Captação de leads

- use um fluxo de entrada no quiosque ou no modo entrevistador;
- registre cada pet separadamente;
- descreva motivo, serviço e situação;
- colha os consentimentos de pesquisa e campanha separadamente;
- acompanhe a confirmação do WhatsApp.

Também é possível usar **Leads → Importar WhatsApp**. A importação nunca presume consentimento nem inicia pesquisa.

## Pesquisas e acompanhamentos

No editor do fluxo, adicione quantas ações forem necessárias. Exemplo:

1. satisfação na tela imediatamente;
2. satisfação por WhatsApp em duas horas;
3. evolução em dez dias, repetida por pet;
4. perfil em noventa dias, às 10h.

Use “intervalo exato” para horas corridas, “dia e hora” para uma data futura em horário fixo e “próximo dia útil” para evitar finais de semana.

## WhatsApp

Configure a Z-API, conecte o QR Code e cadastre os cinco webhooks. O worker precisa estar ativo; o painel mostra o último heartbeat.

Quando uma resposta não corresponder ao formato esperado, o sistema orienta a pessoa e reapresenta a pergunta. Quando duas pesquisas estiverem abertas, a resposta é ligada à mensagem original pelo identificador da Z-API.

## Privacidade

- desconhecidos e importados ficam aguardando aceite;
- pesquisa anônima não contém `lead_id`, telefone ou pet;
- mídias ficam em armazenamento privado;
- usuários restritos não conseguem abrir por URL direta dados de outra cidade;
- opt-out cancela mensagens pendentes.
