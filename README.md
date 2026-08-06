# EscutaPet Inteligente 3.6.0

Sistema funcional para captar leads, registrar vários pets e atendimentos e aplicar pesquisas por WhatsApp, quiosque ou entrevistador. A versão 3 parte da arquitetura simples da 2.2, recebe as melhorias úteis da 1.6 e implementa o plano técnico previsto para a 2.3.

## O que está pronto

- Compilador do gerenciador revisado: BAT sempre permanece aberto, PowerShell executa as etapas com tratamento de erros e o diagnóstico fica salvo em `tools/server_manager/build/ultimo_build.log`.
- Gerenciador gráfico opcional para Windows, com preparação do ambiente, iniciar/parar/reiniciar, saúde do sistema, acesso local/rede, logs e bandeja.
- BAT de compilação isolada para gerar `EscutaPet_Gerenciador.exe` sem alterar o `.venv` da aplicação.
- Ícone do executável criado automaticamente a partir do favicon/PWA configurado, com fallback para a identidade padrão.
- Inicialização opcional com o Windows e encerramento seguro apenas da árvore de processos iniciada pelo gerenciador.
- Central de Agendamentos e Execuções para acompanhar, filtrar e operar pesquisas D+2/D+7, campanhas, recorrências, ações manuais e testes.
- Visão por sete dias, questionário, segmento, origem, estado, canal, período e escopo de produção ou laboratório.
- Envio imediato, reagendamento no fuso do usuário, cancelamento auditado e repetição segura da última mensagem com falha.
- Laboratório real do WhatsApp isolado de métricas, segmentos, alertas e limites de contatos da produção.
- Versão publicada do questionário congelada em cada execução, com quantidade de perguntas e origem visíveis na agenda.
- Transcrição local opcional com `whisper.cpp`, FFmpeg, worker exclusivo e fila que processa um áudio de cada vez.
- Segmentação automática por mensagens livres e transcrições recebidas, com origem, confiança e motivo auditáveis.
- Central de conversas em layout mestre-detalhe, com busca, filtros, lote inicial leve, histórico progressivo por scroll e consultas agrupadas de mídia, remetente e reações.
- Janela visual limitada a 240 mensagens, com reaproveitamento dos elementos ao rolar históricos longos.
- Escopo por cidade aplicado à lista, ao acesso direto, às APIs, às ações e ao download privado das mídias.
- Estados claros para mídia em preparação, fila, horário de silêncio e falha, com tentativa de reenvio sem duplicar a mensagem.
- Respostas citadas, seletor completo de emojis, reações, rascunho individual, notas internas, assinatura e estados de fila, envio, entrega, leitura e falha.
- Editor com prévia segura de negrito, itálico, tachado e monoespaçado, anexos e gravação de áudio pelo navegador.
- Visualizador central de imagens, vídeos e PDFs, download de outros documentos, prévia antes do envio e aviso de novas mensagens.
- Central visual de segmentos com público, regras, automações e evolução mensal.
- Jornadas inteligentes que inscrevem novos leads assim que entram no segmento, com atraso individual e recorrência própria.
- Seleção de múltiplas pesquisas com modo fixo, aleatório, aleatório sem repetição ou rodízio ordenado.
- Horário fixo ou distribuição randômica/estável em janela, amostra renovada por ciclo e intervalo mínimo entre contatos.
- Regras combinadas por cadastro, localização, pet, confirmação e consentimento.
- Prévia de alcance e agendamento WhatsApp imediato, futuro ou recorrente.
- Histórico imutável de entrada e saída de cada público, com cancelamento dos próximos envios ao sair.

- editor visual de jornadas em seis etapas, com linha do tempo, cartões resumidos e painel lateral;
- cidades e pontos vinculáveis à jornada e resumo visual dos bindings do Cadastro estruturado;
- consentimentos ativáveis individualmente e confirmação do WhatsApp em quatro modos simples;
- agenda imediata, por intervalo, dia/horário, próximo dia útil ou data e hora fixas;
- revisão de cronologia, dependências, condições, conflitos, versões e mensagens;
- laboratório integrado para fluxo completo, somente cadastro e simulações sem envio real;
- novo editor progressivo de questionários com cabeçalho fixo, seis abas e modos Simples/Avançado;
- lista compacta de perguntas e configuração isolada da pergunta selecionada, inclusive em celular e tablet;
- campos condicionais por tipo, configurações avançadas recolhidas e erros visíveis na lista;
- assistente com modelos de satisfação, cadastro, pós-atendimento, pesquisa anônima e questionário em branco;
- prévias Web, celular, WhatsApp e quiosque antes da publicação;
- múltipla escolha com limites mínimo/máximo e uso em Web, quiosque, entrevistador e WhatsApp numerado;
- revisão de vínculos, impacto, versão atual, rascunho e execuções antes de publicar;
- questionários com rascunho independente e versões publicadas imutáveis;
- cada execução, resposta e pergunta da fila vinculada à versão exata usada no início;
- pesquisas iniciadas ou agendadas continuam na versão anterior depois de uma nova publicação;
- histórico de versões somente leitura e política de versão fixa ou mais recente em cada ação de fluxo;

- editores confiáveis: erros não apagam campos, perguntas, opções, ações, dependências ou a ordem atual;
- validação visual por campo, resumo dos problemas, aviso de alterações pendentes e estado de salvamento em tempo real;
- proteção contra duplo envio e gravação transacional sem alterações parciais;
- identidades permanentes para perguntas, opções e ações, independentes da posição visual;
- reordenação por arrastar, botões ou teclado, com numeração atualizada e ordem exata após recarregar;
- dependências de ações resolvidas por chave, com proteção contra ação removida, dependência futura, autorreferência e ciclos;
- opções duplicáveis e reordenáveis sem perder valor interno, segmentação, alertas ou metadados históricos;
- aviso de impacto quando uma pergunta é usada em fluxos, com lista de usos, acesso ao fluxo e substituição segura antes de arquivar;

- painel responsivo com navegação por ícones, menu recolhível, tema claro/escuro, contraste, densidade e tamanho de texto;
- leads, pets, visitas, consentimentos, segmentos e identidade do perfil do WhatsApp;
- cidades e pontos de coleta, endereço, coordenadas e escopo de acesso dos usuários por cidade;
- usuários administrador, operador e entrevistador, com perfil e preferências pessoais;
- fluxos de entrada para quiosque e entrevistador, com Cadastro estruturado simples e editável;
- campos de responsável, vários pets e atendimento vinculados pelo próprio editor de questionários;
- perguntas complementares no cadastro, com respostas visíveis no histórico identificado do lead;
- múltiplas ações em um mesmo fluxo: após cadastro, após confirmação ou após a resposta de outra ação;
- condições por resposta, nota ou preenchimento e reordenação das ações;
- agendamento por intervalo exato, dia/hora ou próximo dia útil;
- ações por coleta ou repetidas para cada pet;
- idempotência por coleta, ação, questionário e pet;
- questionários com texto, escolha, sim/não, nota, estrelas, foto, áudio, vídeo, documento, localização, contato e mídia/arquivo;
- respostas inválidas orientadas automaticamente, com reenvio da pergunta;
- correlação segura da resposta com a pergunta enviada por `referenceMessageId`;
- recebimento e envio de texto, botões, listas, imagem, áudio, vídeo, documento, localização e contato pela Z-API;
- estado separado para mensagem enviada, entregue, lida, reproduzida e falha;
- registro e download privado das mídias recebidas antes da expiração do link temporário;
- central de conversas com visualização de imagem, áudio, vídeo, documento e localização;
- identidade por telefone ou `senderLid`, além de nome, foto e recado do perfil;
- importação prévia de contatos, conversas ou chats dos últimos 30 dias;
- sincronização individual dos metadados de um contato;
- consentimento explícito para desconhecidos e importados, sem iniciar pesquisa automaticamente;
- filtros para grupos, status, newsletters, broadcasts, mensagens editadas, chamadas, notificações, reações e enquetes;
- placeholders de pessoa, pets, serviços, visita, unidade, fluxo e questionário;
- inicializador único que monitora servidor e worker, com heartbeat e aviso no painel;
- PWA, modo offline básico e scroll personalizado.
- laboratório de fluxo e teste real pelo WhatsApp com linha do tempo;
- arquivamento/restauração sem apagar respostas, visitas ou execuções.

Relatórios permanecem identificados como beta e serão evoluídos em uma etapa própria.

## Placeholders

As mensagens aceitam, entre outros:

```text
{{primeiro_nome}}
{{nome_completo}}
{{telefone}}
{{cidade}}
{{bairro}}
{{pets_nomes}}
{{quantidade_pets}}
{{pets_servicos_lista}}
{{pet_nome}}
{{pet_especie}}
{{pet_servico}}
{{pet_motivo}}
{{pet_status_servico}}
{{servicos_resumo}}
{{motivos_resumo}}
{{status_servicos}}
{{data_atendimento}}
{{unidade}}
{{nome_empresa}}
{{nome_fluxo}}
{{nome_questionario}}
{{data_atual}}
```

Em uma ação marcada como “uma vez por pet”, os campos `{{pet_*}}` são resolvidos para o pet daquela execução.

## Instalação no Windows

1. Extraia a pasta.
2. Execute `INSTALAR.bat`.
3. Execute `START.bat`.
4. O navegador abrirá em `http://127.0.0.1:8040`.

O instalador também tenta baixar e verificar o Redis 8.10.0 para `tools\redis`. No início, o `launcher.py` usa uma instância já ativa ou inicia o executável local. Se o download, o executável ou a conexão falharem, servidor e worker continuam normalmente com SQLite.

### Redis opcional

- o SQLite continua sendo a fonte oficial de cadastros, respostas, mensagens, webhooks e fila;
- o Redis mantém apenas caches curtos que podem ser recriados;
- a configuração padrão escuta somente em `127.0.0.1:6379`, com limite de 256 MB e política LRU;
- o estado aparece em **Configurações → Estado da instância** e em `/api/health`;
- para desativar, defina `REDIS_ENABLED=0` no `.env`;
- para usar outro servidor, altere `REDIS_URL`.

Para tentar novamente a instalação manual, execute `tools\redis\INSTALAR_REDIS.bat`.

Primeiro acesso:

- usuário: `admin`
- senha: `admin123`

Troque a senha padrão antes de publicar o sistema.

## Telefones e horários

Celulares brasileiros são identificados por uma chave canônica com DDI, DDD e nono dígito. Assim, por exemplo, `556281479264` e `5562981479264` chegam à mesma conversa e ao mesmo lead. Na primeira inicialização desta versão, duplicidades antigas são reunidas preservando mensagens, pesquisas, pets, coletas e consentimentos.

O banco continua armazenando horários em UTC. O fuso padrão é configurado em **Configurações → Geral** e cada usuário pode escolher outro em **Minha conta**. A preferência individual altera somente a exibição; horários preferenciais de pesquisas e períodos de silêncio seguem o fuso global da operação.

## Linux

```bash
chmod +x start.sh
./start.sh
```

O `launcher.py` mantém o servidor e o worker juntos. Para não abrir o navegador:

```bash
./start.sh --no-browser
```

## Atualização de uma instalação 2.2

1. Pare a versão anterior.
2. Faça uma cópia de `app/data/escutapet_v2.sqlite3` e do arquivo `.env`.
3. Substitua os arquivos da aplicação pelos da versão 3.
4. Preserve o banco e o `.env`.
5. Execute `INSTALAR.bat` novamente e depois `START.bat`.

Na primeira inicialização, as novas tabelas e colunas são criadas automaticamente. Cidades são geradas a partir dos nomes já existentes, as três ações fixas dos fluxos 2.2 são convertidas em ações múltiplas e o Cadastro estruturado essencial é ligado aos fluxos existentes. O nome do arquivo SQLite continua `escutapet_v2.sqlite3` justamente para permitir a atualização direta.

O sistema também instala o fluxo **Coleta rápida · legado 1.3** e nove questionários editáveis com as 34 perguntas úteis do catálogo da versão 1.6. A instalação é idempotente e também ocorre em bancos existentes, sem duplicar modelos.

## Atualização da 3.1.2 para a 3.2.0

1. Pare completamente servidor e worker.
2. Faça uma cópia de `app/data/escutapet_v2.sqlite3`, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Aguarde a primeira inicialização terminar antes de liberar acessos ou iniciar o worker em outra máquina.
6. Execute `python scripts/report_v320_versioning.py`. O comando deve terminar sem execuções ou perguntas pendentes de vínculo.

Na primeira inicialização, o sistema cria uma versão inicial para cada questionário existente e liga execuções, respostas e mensagens já salvas à pergunta correspondente. A operação é idempotente, não troca IDs históricos e registra qualquer item incompatível em vez de inventar um vínculo. Depois da migração inicial, uma execução sem versão passa a ser bloqueada e diagnosticada; ela não é corrigida silenciosamente.

Para voltar temporariamente ao código anterior, os campos e snapshots extras podem permanecer no banco sem afetar a 3.1.2. Execute antes `python scripts/rollback_v320_versioning.py --confirm`: em SQLite ele cria uma cópia do banco e volta as ações para “versão mais recente”, sem apagar snapshots nem vínculos históricos.

## Atualização da 3.2.0 para a 3.2.1

1. Pare servidor e worker.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.2.1, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.

A primeira inicialização acrescenta `settings_json` às perguntas editáveis e aos snapshots publicados. Questionários e versões existentes recebem `{}` e continuam funcionando sem conversão manual. A 3.2.1 não altera o editor de fluxos nem antecipa salvamento automático ou recuperação local; esse escopo permanece reservado para versões posteriores.

## Atualização da 3.2.1 para a 3.2.2

1. Pare servidor e worker.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.2.2, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Abra cada fluxo ativo, confira a aba Revisão e salve somente após corrigir avisos obrigatórios.

A primeira inicialização acrescenta ao fluxo os seletores de consentimento e o escopo de cidades, além do campo de data/hora fixa nas ações. A migração é automática e idempotente; os consentimentos permanecem ativados nos fluxos existentes e nenhuma ação ou versão publicada é recriada. Datas fixas informadas no editor usam o fuso configurado no sistema e são armazenadas em UTC.

## Atualização para a 3.5.7

1. Pare servidor e worker.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.5.7, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Atualize o navegador com `Ctrl+F5` e confira a Revisão e o Laboratório da jornada.

A migração é automática e idempotente e não cria colunas novas. A 3.5.7 acrescenta o catálogo visual de variáveis e condições entre perguntas do mesmo questionário. As regras ficam congeladas em cada publicação e passam a valer na aplicação por tela e no WhatsApp. Consulte `docs/ATUALIZACAO_3.5.7.md`.

## Atualização para a 3.6.0

1. Pare servidor, worker e gerenciador.
2. Faça uma cópia do banco, do `.env` e de `app/data/branding`.
3. Substitua os arquivos da aplicação pelos da 3.6.0, preservando esses dados.
4. Execute `INSTALAR.bat` e depois `START.bat`.
5. Abra **Segmentos → Automações**, confira as campanhas antigas e crie as novas jornadas inteligentes.

A primeira inicialização cria as tabelas de questionários participantes e inscrições individuais, adiciona as novas opções às automações existentes e vincula automaticamente o questionário principal das campanhas antigas. Nenhum lead é inscrito retroativamente em uma jornada antiga; somente automações novas com gatilho de entrada usam o novo controle individual. Consulte `docs/ATUALIZACAO_3.6.0.md`.

## Z-API

Em **Configurações → WhatsApp · Z-API**:

1. informe ID da instância, Token e Client-Token;
2. salve;
3. conecte pelo QR Code;
4. abra a aplicação pelo domínio HTTPS público;
5. configure os cinco webhooks;
6. execute o diagnóstico.

O sistema separa o endereço de envio da Z-API do endereço público desta aplicação. Segredos não são enviados ao navegador.

Contatos desconhecidos entram como `onboarding` e `consent_research = false`. A pesquisa de cadastro começa somente após “Aceito participar”. Responder `SAIR`, `PARAR`, `CANCELAR`, `NÃO QUERO` ou `NÃO ACEITO` cancela mensagens pendentes.

## Mídias

Mídias recebidas são registradas imediatamente. O worker valida URL HTTPS, destino de rede, extensão, MIME e limite de tamanho antes de salvar em `app/data/media`. O acesso aos arquivos exige login. Ajuste limite e retenção em **Configurações**.

## Testes

```bash
python scripts/test_smoke.py
python scripts/test_zapi_integration.py
python scripts/test_questionnaire_edit_history.py
python scripts/test_entry_flow.py
python scripts/test_v3_features.py
python scripts/test_redis_optional.py
python scripts/test_phone_timezone.py
python scripts/test_v311_reliable_editors.py
python scripts/test_v312_stable_reordering.py
python scripts/test_v320_questionnaire_versioning.py
python scripts/test_v321_questionnaire_editor.py
python scripts/test_v322_visual_journeys.py
python scripts/test_v324_recovery_lab.py
python scripts/test_upgrade_v302_to_v324.py
python scripts/test_conditional_screen_journey.py
python scripts/test_v360_smart_segment_automations.py
python scripts/test_v361_numeric_conditions.py
python scripts/test_v361_anonymous_context.py
```

Os testes usam bancos temporários e não alteram a base real. Eles cobrem páginas, histórico seguro, fluxo multipet, consentimento, LID, mídia, `referenceMessageId`, Z-API simulada, ações múltiplas, execução por pet, editores visuais, recuperação, conflitos, passagem do tempo, ações isoladas, data fixa, múltipla escolha e snapshots.

## Estrutura

```text
app/
  routers/       interface, API, entrada e webhooks
  services/      motor, versões, coleta, mídia, Z-API, segmentação e worker
  templates/     telas administrativas e públicas
  static/        estilos, scripts, ícones e PWA
  models.py      modelo de dados
launcher.py      supervisor do servidor e worker
run.py           servidor FastAPI
worker.py        agendamentos, fila e download de mídia
```
