# Atualização para EscutaPet 3.5.7

Esta versão acrescenta variáveis fáceis de inserir e condições internas entre
perguntas. Não há alteração de esquema no banco: as novas regras usam as
configurações já versionadas de cada pergunta.

## Como atualizar

1. pare o servidor, o worker e o Gerenciador;
2. faça backup do banco, do `.env` e de `app/data/branding`;
3. substitua os arquivos da aplicação preservando esses dados;
4. execute `INSTALAR.bat` e depois `START.bat`;
5. atualize o navegador com `Ctrl+F5`.

## Como usar

Em **Questionários → Editar → Perguntas**, o botão `{{…}}` abre todas as
variáveis compatíveis e insere a escolhida onde estiver o cursor. Na seção
**Exibição condicional**, escolha uma pergunta anterior, o operador e a
resposta esperada. Perguntas de escolha mostram suas opções reais; perguntas
de texto permitem digitar o valor de comparação.

Ao publicar, a regra é congelada com a versão. Pesquisas já iniciadas continuam
na versão antiga. Uma pergunta oculta é pulada tanto em tela quanto no
WhatsApp e não gera uma resposta vazia no histórico.
