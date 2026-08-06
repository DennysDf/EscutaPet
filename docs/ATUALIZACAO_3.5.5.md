# Atualização para EscutaPet 3.5.5

## Correção do BAT de limpeza

O `LIMPAR_PARA_PRODUCAO.bat` agora usa uma etapa PowerShell para localizar o
Python instalado. A ausência de uma versão prioritária, como Python 3.13, não
interrompe mais a execução.

São aceitos Python 3.11, 3.12, 3.13, 3.14 e 3.15, todos em 64 bits. O script
testa as versões disponíveis e mostra qual delas foi selecionada antes de criar
o backup e iniciar a limpeza.

O mesmo ajuste foi aplicado ao compilador do Gerenciador Windows.

Execute `LIMPAR_PARA_PRODUCAO.bat` somente com o EscutaPet, worker e gerenciador
encerrados. Digite `APAGAR` quando a confirmação for solicitada.
