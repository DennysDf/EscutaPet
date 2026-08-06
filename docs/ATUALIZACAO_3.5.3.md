# Atualização para EscutaPet 3.5.3

## Correção incluída

O compilador do Gerenciador Windows agora continua a procurar uma versão disponível do Python quando uma versão prioritária não estiver instalada. Por exemplo: se o Python 3.13 não existir, ele segue para 3.12, 3.11, 3.14 e `python.exe`, sem encerrar a compilação.

O diagnóstico completo fica em:

`tools\server_manager\build\ultimo_build.log`

## Como atualizar

1. Pare o EscutaPet.
2. Faça uma cópia do banco, `.env`, `app/data/branding` e mídias.
3. Substitua os arquivos da aplicação pelos da versão 3.5.3, preservando esses dados.
4. Execute `INSTALAR.bat` normalmente.
5. Configure o ícone em **Configurações → Logos e aplicativo**.
6. Feche qualquer `EscutaPet_Gerenciador.exe` que esteja aberto.
7. Execute `BUILD_GERENCIADOR_EXE.bat`.

## Comportamento esperado

A janela mostra, em sequência:

- Python selecionado;
- criação ou reaproveitamento do ambiente isolado;
- instalação das ferramentas de compilação;
- origem da imagem usada para o ícone;
- execução do PyInstaller;
- caminho e tamanho do EXE criado.

Em qualquer falha, a mensagem permanece visível até uma tecla ser pressionada. O log informa exatamente qual etapa e comando falharam.

Esta atualização não altera nenhuma tabela nem dado de produção.
