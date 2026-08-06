# Atualização para EscutaPet 3.5.6

O `LIMPAR_PARA_PRODUCAO.bat` agora prioriza o Python do próprio EscutaPet em
`.venv\Scripts\python.exe`. Esse ambiente contém SQLAlchemy e todas as
dependências instaladas pelo `INSTALAR.bat`.

Antes de limpar, a ferramenta valida a importação do SQLAlchemy. Se o `.venv`
estiver ausente ou incompleto, nenhuma alteração é feita e a janela orienta a
executar `INSTALAR.bat`.

Para usar:

1. execute `INSTALAR.bat` caso ainda não tenha preparado essa pasta;
2. feche servidor, worker e Gerenciador;
3. execute `LIMPAR_PARA_PRODUCAO.bat`;
4. digite `APAGAR` para confirmar.
