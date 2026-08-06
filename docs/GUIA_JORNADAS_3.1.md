# Jornadas e Cadastro estruturado — EscutaPet 3.1

## Cadastro estruturado

Cada fluxo de entrada escolhe um questionário com objetivo **Cadastro estruturado**.

No editor do questionário, o campo **Usar resposta como** define se a pergunta alimenta:

- responsável: nome, WhatsApp, cidade ou bairro;
- pet: nome ou espécie;
- atendimento: motivo, serviço, situação ou detalhes;
- pesquisa complementar: registra a resposta sem alterar o cadastro.

Nome e WhatsApp são os únicos vínculos obrigatórios para ativar um cadastro. Os demais campos podem ser removidos, reordenados ou substituídos.

Perguntas de pet e atendimento são repetidas automaticamente para cada pet. Perguntas complementares aparecem uma vez no cadastro e ficam no histórico identificado do lead.

## Ações condicionais

Em **Ações e pesquisas posteriores**, escolha **Após responder outra ação**. Em seguida:

1. selecione uma ação anterior;
2. selecione uma pergunta do questionário daquela ação;
3. escolha a condição;
4. informe o valor esperado, quando necessário;
5. defina o prazo contado a partir da conclusão da ação anterior.

O editor impede dependência de uma ação posterior, ciclos e perguntas pertencentes a outro questionário. As condições aceitas são igualdade, diferença, contém, não contém, maior/menor ou igual, respondida e não respondida.

## Testes

- **Testar fluxo** abre o cadastro completo em modo de laboratório.
- **Testar na web** simula um questionário no navegador.
- **Testar WhatsApp** envia ao número informado e abre o acompanhamento de mensagens e respostas.

Execuções e coletas de laboratório ficam marcadas como teste e não entram nos relatórios, limites de contato ou histórico real do lead.

## Arquivamento

Arquivar não exclui respostas, visitas ou execuções. Um questionário usado por fluxo ativo precisa ser removido do fluxo ou ter o fluxo pausado antes do arquivamento. A área **Arquivados** permite restaurar itens como pausados.

## Histórico do lead

Em `/leads/{id}`, abra uma pesquisa no bloco **Histórico de pesquisas** para visualizar:

- canal e estado da execução;
- data de agendamento ou conclusão;
- perguntas respondidas e conteúdo das respostas;
- perguntas ainda não respondidas;
- motivo de bloqueio ou cancelamento, quando disponível.

Pesquisas anônimas nunca aparecem vinculadas a uma pessoa.
