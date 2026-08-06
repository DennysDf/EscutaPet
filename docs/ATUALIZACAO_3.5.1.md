# Atualização para EscutaPet 3.5.1

## Antes de atualizar

1. Pare o servidor e os workers.
2. Faça uma cópia de `app/data`, do arquivo `.env` e das mídias recebidas.
3. Substitua os arquivos da aplicação pelos da versão 3.5.1, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat` para conferir a atualização normal.
5. Atualize o navegador com `Ctrl+F5`.

## Gerar o aplicativo do Windows

1. No EscutaPet, abra **Configurações → Logos e aplicativo**.
2. Envie o ícone quadrado desejado. O sistema gera o favicon e os arquivos PWA.
3. Na pasta principal do sistema, execute `BUILD_GERENCIADOR_EXE.bat`.
4. Aguarde a criação de `EscutaPet_Gerenciador.exe` na pasta principal.
5. Abra o EXE e use **Preparar/atualizar** na primeira execução.

O compilador possui ambiente próprio em `tools/server_manager/.build-venv`. Ele instala somente Pillow, pystray e PyInstaller nesse ambiente e não interfere nas dependências do sistema.

## Ícone e identidade visual

Durante cada compilação, o BAT procura o PWA de 512 px, a prévia do ícone e o favicon existentes em `app/data/branding`. A imagem encontrada é convertida em um ICO com tamanhos de 16 a 256 px e incorporada ao executável.

A janela e a bandeja leem a identidade disponível no momento em que o gerenciador abre. O ícone exibido pelo Explorador do Windows é incorporado ao EXE; portanto, após trocar a logo, execute novamente `BUILD_GERENCIADOR_EXE.bat`.

## Funcionamento

O gerenciador inicia o `launcher.py --no-browser`. Assim, continuam sendo supervisionados pelo mesmo componente:

- servidor FastAPI/Uvicorn;
- worker da fila e dos agendamentos;
- worker de transcrição;
- Redis opcional instalado em `tools/redis`.

As configurações do gerenciador ficam em `app/data/server_manager/config.json` e os logs em `app/data/logs/escutapet_manager.log`.

O botão **Parar** encerra somente o PID registrado pelo gerenciador e seus processos filhos. Se encontrar a porta ocupada por outro serviço ou por uma inicialização manual, ele informa o conflito e não encerra o processo desconhecido.

## Compatibilidade

Esta versão não altera tabelas do banco. Questionários, jornadas, agendamentos, conversas, mídias, configurações da Z-API e identidade visual são preservados.
