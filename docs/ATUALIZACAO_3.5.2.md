# Atualização para EscutaPet 3.5.2

## Correção incluída

O compilador do Gerenciador Windows foi refeito. O arquivo `BUILD_GERENCIADOR_EXE.bat` agora apenas abre um processo PowerShell estruturado, aguarda sua conclusão e sempre mantém a janela aberta para mostrar o resultado.

O diagnóstico completo fica em:

`tools\server_manager\build\ultimo_build.log`

## Como atualizar

1. Pare o EscutaPet.
2. Faça uma cópia do banco, `.env`, `app/data/branding` e mídias.
3. Substitua os arquivos da aplicação pelos da versão 3.5.2, preservando esses dados.
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
