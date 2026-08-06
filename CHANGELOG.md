# Changelog

## 3.6.0 — Jornadas inteligentes por segmento

- adiciona gatilhos por calendário, entrada no segmento e entrada com recorrência individual;
- permite selecionar vários questionários e usar pesquisa fixa, aleatória, aleatória sem repetição ou rodízio ordenado;
- cria uma inscrição individual por lead, com ciclo, histórico, próximo envio, motivo de bloqueio e idempotência;
- distribui envios em horário fixo, janela randômica ou distribuição estável dentro da janela configurada;
- oferece amostra fixa ou renovada a cada ciclo, intervalo mínimo, limite de ciclos, exigência de WhatsApp confirmado e bloqueio enquanto outra pesquisa estiver ativa;
- inscreve automaticamente novos integrantes pelo worker e cancela inscrições e execuções agendadas quando o lead sai do segmento;
- preserva automações 3.5.x e migra automaticamente seu questionário principal para a nova coleção;
- atualiza a tela `/segmentos` com construtor em etapas, prévia ampliada e resumo das inscrições.

## 3.5.7 — Variáveis e perguntas condicionais

- adiciona um catálogo visual com todas as variáveis suportadas e inserção na posição do cursor;
- oferece o botão de variáveis nas mensagens e nos textos de cada pergunta;
- permite exibir uma pergunta conforme a resposta de qualquer pergunta anterior do mesmo questionário;
- lista automaticamente Sim/Não e as opções reais da pergunta escolhida, além de comparações de texto;
- valida dependências no navegador e no servidor, congela as regras na versão publicada e as executa em tela e WhatsApp;
- pula perguntas ocultas sem gerar respostas artificiais e mantém execuções antigas na versão anterior.

## 3.5.6 — Limpeza usa o ambiente da aplicação

- prioriza `.venv\Scripts\python.exe`, que já contém SQLAlchemy e as dependências do EscutaPet;
- valida `import sqlalchemy` antes de iniciar backup ou limpeza;
- impede o uso acidental do Python global sem dependências e orienta executar `INSTALAR.bat` quando o ambiente estiver incompleto.

## 3.5.5 — Compatibilidade Python da limpeza de produção

- substitui a procura de Python feita pelo CMD por uma etapa PowerShell tolerante às respostas do Python Launcher;
- inclui Python 3.15, além de 3.11 a 3.14, tanto na limpeza quanto no compilador do Gerenciador Windows;
- evita que a ausência de Python 3.13 interrompa o BAT antes de testar as versões realmente instaladas.

## 3.5.4 — Preparação segura para produção

- adiciona `LIMPAR_PARA_PRODUCAO.bat`, com confirmação explícita e orientação para encerrar servidor e workers;
- gera backup SQLite ou PostgreSQL e cópia das mídias antes de alterar o banco;
- remove leads, pets, conversas, mensagens, anexos, transcrições, respostas, pesquisas, filas, alertas e webhooks;
- preserva usuários, configurações, identidade visual, Z-API, cidades, dispositivos, segmentos, questionários e jornadas.

## 3.5.3 — Detecção compatível do Python no compilador

- corrige o verificador do Python Launcher: a ausência do Python 3.13 não interrompe mais o compilador;
- continua automaticamente para Python 3.12, 3.11, 3.14 e, por fim, `python.exe` disponível no PATH;
- mantém o erro final apenas quando nenhuma instalação Python compatível é encontrada.

## 3.5.2 — Correção do compilador do Gerenciador Windows

- substitui a sequência frágil de comandos do BAT por um compilador PowerShell estruturado;
- mantém o BAT como lançador simples e garante pausa final em sucesso, erro, arquivo ausente ou falha do PowerShell;
- detecta Python 3.13, 3.12, 3.11, 3.14 ou `python.exe` sem depender de expansão de variáveis dentro de blocos CMD;
- valida todos os arquivos necessários antes de instalar ou compilar;
- grava o diagnóstico completo em `tools/server_manager/build/ultimo_build.log`;
- mostra cada etapa, comando executado, código de saída e mensagem objetiva de correção;
- detecta quando `EscutaPet_Gerenciador.exe` está aberto e pede para fechá-lo antes da recompilação;
- preserva o ambiente isolado, o ícone configurado e os metadados de versão do executável.

## 3.5.1 — Gerenciador do servidor para Windows

- adiciona um gerenciador gráfico opcional para preparar, iniciar, parar e reiniciar o EscutaPet;
- mantém FastAPI, worker principal, transcrição e Redis sob o `launcher.py` oficial, evitando dois supervisores concorrentes;
- mostra saúde do servidor, banco, Redis, mensagens pendentes e pesquisas em execução;
- oferece atalhos para acesso local, acesso pela rede e pasta de logs;
- permite abrir minimizado na bandeja e iniciar junto com o Windows;
- encerra somente o PID iniciado pelo próprio gerenciador, sem matar programas desconhecidos pela porta;
- inclui compilação PyInstaller em ambiente isolado, sem modificar o `.venv` da aplicação;
- converte o ícone configurado em Configurações para um ICO multirresolução e o incorpora ao EXE;
- mantém fallback para o ícone PWA padrão quando ainda não existe identidade personalizada;
- documenta que o EXE deve ser recompilado depois da troca de logo para atualizar o ícone do Explorador do Windows.

## 3.5.0 — Central de Agendamentos e Execuções

- reúne pesquisas futuras, em andamento, concluídas, bloqueadas, canceladas e com falha em uma central operacional;
- identifica a origem de cada execução: fluxo, campanha segmentada, recorrência, cadastro, ação manual ou laboratório;
- oferece filtros por período, estado, origem, questionário, segmento, canal e escopo de produção/testes;
- adiciona indicadores operacionais e uma visão navegável dos próximos sete dias;
- permite liberar para envio imediato, reagendar, cancelar com motivo e repetir a última mensagem com falha;
- respeita cidades do operador, fuso do usuário, horário de silêncio, consentimento e limites de contato já aplicados pelo worker;
- mostra a versão imutável do questionário e a quantidade exata de perguntas usadas em cada execução;
- inclui laboratório real do WhatsApp isolado de métricas, segmentos, alertas e limites da produção;
- registra as ações operacionais na auditoria e preserva filas e identificadores já existentes;
- acrescenta atalhos nos questionários, segmentos e navegação principal.

## 3.4.1 — Correção do agendamento no editor de jornadas

- restaura a opção explícita **Agora, imediatamente** no campo Forma de agendar;
- corrige o seletor vazio que fazia o editor enviar `schedule_mode` inválido e receber HTTP 400;
- recupera rascunhos produzidos pela 3.4.0 com o agendamento vazio, tratando-os como intervalo zero;
- mantém disponíveis intervalo, horário do dia, próximo dia útil e data/hora fixa;
- atualiza o cache dos arquivos estáticos para entregar o JavaScript corrigido imediatamente.

## 3.4.0 — Jornadas condicionais e ramificadas

- permite adicionar um ou vários questionários identificados antes de solicitar a confirmação do WhatsApp;
- mantém a confirmação suspensa até que todas as etapas iniciais de tela sejam concluídas;
- permite condições sobre o Cadastro estruturado ou qualquer questionário identificado anterior da mesma coleta;
- combina até dez condições por ação com lógica **todas (E)** ou **qualquer uma (OU)**;
- lista no editor as opções publicadas de perguntas de escolha e Sim/Não, evitando valores digitados incompatíveis;
- adiciona grupos de sorteio com pesos, escolhendo um único caminho e persistindo a decisão por sessão;
- impede que recarregamentos, webhooks repetidos ou retomadas alterem o caminho sorteado ou dupliquem ações;
- reavalia após a confirmação apenas as ações futuras que estavam bloqueadas, sem repetir etapas já iniciadas;
- amplia revisão, linha do tempo, recuperação de rascunhos e laboratório para as novas etapas, condições e sorteios;
- migra automaticamente bancos existentes com valores padrão compatíveis e preserva todas as jornadas anteriores.

## 3.3.4 — Confirmação que retoma a jornada

- corrige o fluxo com **Exigir antes de concluir**: a confirmação no WhatsApp não encerra mais a sessão antes da próxima etapa;
- recupera, pela tela de status do ponto ou entrevistador, a primeira ação de tela ativa criada após a confirmação;
- preserva o encadeamento condicional: por exemplo, confirmação → informativo identificado → resposta “Sim” → pesquisa anônima;
- evita recriar ações de “Após cadastro” nos modos que já avançaram antes da confirmação;
- envia uma única mensagem de agradecimento após a confirmação automática ou manual do WhatsApp;
- esclarece no editor quais ações dependem da confirmação e atualiza os ativos para evitar cache do navegador.

## 3.3.3 — Refinamento e consolidação da Central de Conversas

- substitui os blocos visuais concorrentes das versões anteriores por uma folha dedicada e um layout mestre-detalhe responsivo;
- troca o ícone da navegação por conversa e padroniza responder, reagir, anexar, gravar, enviar, buscar, baixar e fechar com os ícones SVG do sistema;
- adiciona busca e filtros progressivos de conversas, estados legíveis, responsável, fixar, marcar como não lida, encerrar e reabrir;
- limita a carga inicial a 30 mensagens, a paginação a 40 e a janela do DOM a 240 mensagens, reaproveitando os elementos durante o scroll;
- adiciona estados de mídia em preparação, prévia de anexos, colagem e arraste, gravação com cronômetro, cancelamento e confirmação antes do envio;
- melhora o modal de emojis, a substituição e remoção de reações, a formatação segura e o visualizador central de imagem, vídeo, PDF e downloads;
- mantém rascunho por usuário, remove o rascunho somente após confirmação do servidor e oferece nova tentativa para falhas de fila;
- aplica a autorização por cidade à lista, busca, paginação, acesso direto, mensagens, ações e mídias;
- preserva horário de silêncio, Z-API, webhooks, transcrição, segmentação, questionários, jornadas e compatibilidade de atualização.

## 3.3.2 — Conversas progressivas e mídias

- aproxima a central da experiência do WhatsApp Web, com cabeçalho compacto, fundo de conversa, compositor e painel de informações responsivos;
- reduz a carga inicial para 30 mensagens e busca lotes adaptativos automaticamente ao aproximar o scroll do topo;
- mantém consultas em lote e elimina a busca separada de mídia e reação para cada mensagem;
- adiciona modal de emojis com categorias, recentes e busca em português, usado tanto no editor quanto nas reações;
- renderiza com segurança negrito, itálico, tachado e monoespaçado dentro do EscutaPet, preservando os marcadores enviados ao WhatsApp;
- adiciona visualizador central de imagens, vídeos e PDFs, download de outros documentos e prévia do anexo antes do envio;
- melhora gravação de áudio, resposta citada, separadores de data, indicador de novas mensagens e retorno ao fim do histórico;
- confirma o envio assíncrono antes de limpar o editor e mostra erros de validação ou fila na própria conversa;
- preserva o horário de silêncio, a fila Z-API, a transcrição e toda a compatibilidade de atualização da 3.3.1.

## 3.3.1 — Transcrição e segmentação de conversas

- adiciona fila persistente e worker exclusivo para transcrição, com apenas um áudio processado por vez;
- integra `whisper.cpp` multilíngue quantizado e FFmpeg opcionais em `tools`, com preparador próprio para Windows x64;
- transcreve áudios recebidos e, opcionalmente, enviados, sem substituir o arquivo original;
- mostra transcrição, espera, processamento e falha diretamente na bolha de áudio;
- usa mensagens livres recebidas e transcrições para alimentar segmentos inteligentes, registrando origem, confiança e motivo;
- associa a transcrição à resposta quando o áudio pertence a um questionário;
- inclui configuração, diagnóstico, contadores da fila, retentativas e atualização automática de bancos anteriores.

## 3.3.0 — Central de conversas profissional

- transforma `/conversas` em uma central de atendimento focada, sem baixar todo o histórico de uma vez;
- carrega as últimas 50 mensagens e busca as anteriores sob demanda, com cursores estáveis também na lista de conversas;
- permite responder citando uma mensagem, reagir com emoji, visualizar estados de envio, entregar, leitura e falha;
- adiciona editor com atalhos de negrito, itálico e tachado do WhatsApp, anexos, gravação de áudio e notas internas;
- permite configurar assinatura individual em **Minha conta** e mantém rascunhos separados por usuário e conversa;
- integra o envio humano à fila existente, preserva mídia local e atualiza a própria bolha quando o worker ou o webhook confirma o estado.

## 3.2.5 — Central de segmentos e automações

- transforma `/segmentos` em uma central visual com público, regras, automações e evolução;
- adiciona regras combinadas por cidade, bairro, origem, nome, espécie, raça, confirmação e consentimento;
- preserva eventos de entrada, atualização e saída para análises mensais confiáveis;
- permite pré-visualizar elegíveis e exclusões antes de agendar questionários pelo WhatsApp;
- oferece envio imediato, data futura e recorrência pelo worker, respeitando consentimento e as proteções globais de contato;
- mantém respostas anônimas fora das automações identificadas de segmentos.

## 3.2.4 — Jornadas visuais, recuperação e laboratório avançado

- corrige a atualização de bancos 3.0.x/3.1.x criando `entry_flows.device_ids_json` antes de qualquer seed ou consulta ORM;
- corrige o desalinhamento dos cartões da linha do tempo e substitui o painel lateral das ações por modal central responsivo;
- permite ação condicional imediata de tela após outra ação de tela, com redirecionamento automático e anonimato preservado;
- consolida em uma única entrega o editor visual, a proteção de rascunhos e o laboratório avançado;
- mantém as seis etapas do fluxo, a linha do tempo, o painel lateral, os campos condicionais e a revisão integrada;
- salva cópias locais e no servidor após inatividade, sem publicar, criar execuções ou acionar o worker;
- oferece restaurar, comparar e descartar trabalho recuperável após recarregar ou fechar o navegador;
- impede sobrescrita silenciosa com revisão otimista e identifica a última sessão que salvou;
- permite duplicar a edição conflitante como novo rascunho, preservando o conteúdo do usuário;
- registra criação, edição e restauração na auditoria, com revisão anterior e nova;
- simula a jornada completa com confirmação, condições, quantidade de pets e passagem de até cinco anos;
- testa ações isoladamente com a versão publicada congelada e rastreia pré-requisitos;
- garante que o laboratório não cria fila, execução, lead, resposta ou envio Z-API;
- preserva IDs permanentes, histórico, versões publicadas e pesquisas em andamento;
- não inclui relatórios, mantidos fora do escopo desta versão.

## 3.2.2 — Editor visual de jornadas

- reorganiza fluxos em Identificação, Cadastro, Consentimentos, WhatsApp, Jornada e Revisão;
- mostra cidade, pontos, modos e status, com atribuição da jornada padrão aos pontos selecionados;
- resume os bindings do Cadastro estruturado por responsável, pet e atendimento;
- detecta versão não publicada, binding obrigatório ausente, duplicado ou incompatível;
- torna pesquisas, campanhas e termos seletores independentes e mostra detalhes apenas quando ativados;
- simplifica a confirmação do WhatsApp em quatro comportamentos operacionais;
- apresenta as ações em linha do tempo com momento, questionário, canal, escopo, condição e status;
- move a configuração completa para painel lateral com campos condicionais por gatilho, agenda, pet, condição e canal;
- adiciona data e hora fixas ao motor de agendamento, convertidas do fuso do sistema para UTC;
- preserva dependências por chave permanente durante arrastar, subir, descer, inserir ou remover ações;
- revisa cronologia, dependências, condições, publicações, órfãos, ciclos e mensagens ausentes;
- integra teste completo, teste somente do cadastro e simulador de tempo, confirmação, condição e quantidade de pets;
- mantém as garantias de versionamento da 3.2.0 e de edição segura da 3.2.1;
- prepara a interface visual que foi consolidada com recuperação e laboratório na 3.2.5.

## 3.2.1 — Novo editor de questionários

- reorganiza a edição em Geral, Perguntas, Lógica, Canais, Segmentação e alertas e Publicação;
- fixa o cabeçalho com nome, versão, status, estado do rascunho, alterações pendentes e ações principais;
- adiciona modos Simples e Avançado sem apagar ou redefinir configurações ocultas;
- mostra uma lista compacta de perguntas e apenas o formulário da pergunta selecionada;
- mantém reordenação estável por arrastar, botões ou teclado, IDs permanentes, impactos e substituição segura;
- exibe campos condicionais para texto, escolha única, múltipla escolha, nota, estrelas, mídias e localização;
- recolhe vínculos, alertas, segmentos, metadados e regras especiais em configurações avançadas;
- inclui modelos editáveis de satisfação, cadastro, pós-atendimento, pesquisa anônima e questionário em branco;
- adiciona prévias Web, celular, WhatsApp e quiosque;
- resume versão, rascunho, fluxos, ações, execuções e impacto antes de publicar;
- adapta lista e detalhe para telas alternadas no celular, modais limitados à viewport e alvos de toque adequados;
- persiste configurações específicas em `settings_json` e as congela em cada versão publicada;
- adiciona múltipla escolha com limites, aplicação Web e texto numerado no WhatsApp;
- preserva o versionamento imutável da 3.2.0 e não antecipa o editor visual de jornadas ou o salvamento automático previstos para versões posteriores.

## 3.2.0 — Versionamento imutável de questionários

- separa o questionário lógico, o rascunho editável e cada versão publicada;
- congela configuração, ordem, textos, tipos, obrigatoriedade, escalas, vínculos, regras, opções, valores internos, botões/listas, mensagens e metadados;
- vincula toda execução a `questionnaire_version_id` e cada resposta/fila à pergunta da versão;
- mantém pesquisas iniciadas ou agendadas na versão original após editar, reordenar ou publicar novamente;
- faz worker, WhatsApp, web, cadastro estruturado, alertas, segmentação, histórico, testes e ações de fluxo consultarem o snapshot;
- adiciona “Salvar rascunho” e “Publicar nova versão”, com resumo de impacto e confirmação explícita;
- mostra histórico de versões, autor, data, perguntas, execuções e resumo de mudanças em modo somente leitura;
- permite que cada ação use a versão mais recente publicada ou uma versão fixa;
- migra bancos existentes de forma idempotente, preservando IDs, respostas e condições, e registra inconsistências sem reparo silencioso;
- inclui relatório de migração, rollback lógico com backup e teste de publicação durante execução/reinício do worker.

## 3.1.2 — Reordenação estável e segura

- separa posição visual da identidade de perguntas, opções e ações;
- usa chaves permanentes `question:*`, `option:*` e `action:*`, inclusive ao misturar itens novos e já salvos;
- resolve dependências de ações por chave somente depois de criar ou atualizar todas as etapas;
- preserva questionário, condição, agenda, mensagens e contexto ao reordenar ações;
- bloqueia autorreferência, dependência removida ou futura, ciclos, pergunta incompatível/arquivada e contexto por pet ambíguo;
- adiciona arrastar, subir/descer e atalhos de teclado para perguntas, opções e ações;
- permite duplicar opções sem reutilizar sua identidade e conserva valores, regras e metadados;
- mostra onde uma pergunta é usada e exige substituição segura antes do arquivamento;
- atualiza automaticamente as condições dos fluxos para a pergunta substituta;
- cobre 20 perguntas, opções, itens novos/antigos, exclusões, ciclos, dois filhos do mesmo pai e reload da ordem exata.

## 3.1.1 — Salvamento confiável

- reconstrói questionários e fluxos com todos os dados enviados quando qualquer validação falha;
- mantém perguntas vazias, opções, ordem, vínculos cadastrais, ações, dependências, condições, mensagens e horários visíveis para correção;
- padroniza erros por seção, item e campo, com resumo no topo, destaque no controle correto e rolagem ao primeiro problema;
- valida no navegador e novamente no servidor nomes, canais, mensagens, opções, escalas, vínculos, alertas, questionários, ações, horários e condições;
- remove o filtro que descartava silenciosamente perguntas sem texto;
- mostra os estados “Alterações não salvas”, “Validando”, “Salvando”, “Salvo às HH:mm” e “Erro ao salvar”;
- alerta ao sair do editor com alterações pendentes e bloqueia envio repetido por botão ou Enter;
- usa token idempotente por formulário para impedir duplicação por duplo clique;
- passa a gravar somente depois da validação completa, em uma única transação com rollback explícito;
- adiciona testes de preservação, reordenação com erro, opções duplicadas, condições inválidas, idempotência e rollback.

## 3.1.0 — Jornadas personalizáveis e cadastro estruturado

- substitui a seção fixa “Dados e pets” por um questionário de Cadastro estruturado;
- instala automaticamente um cadastro essencial editável com nome, WhatsApp, cidade, bairro, pet, motivo e serviço;
- permite adicionar perguntas complementares ao cadastro, preservando as respostas identificadas no histórico do lead;
- mantém os dados estruturados de responsável, pet e atendimento para placeholders e automações;
- adiciona dependências entre ações, condições por resposta e reordenação acessível;
- valida ciclos, ordem, questionário de origem, canal e valor esperado antes de ativar o fluxo;
- libera ações condicionais somente após a conclusão da etapa anterior e sem disparos duplicados;
- adiciona laboratório de fluxo de entrada e teste real por WhatsApp com andamento e respostas;
- isola execuções de teste de relatórios, limites de contato e histórico real;
- adiciona arquivamento e restauração de questionários e fluxos sem apagar dados históricos;
- mostra em `/leads/{id}` cada pergunta, resposta, pendência e estado das pesquisas identificadas;
- reforça a proteção do editor contra perda de identidade das perguntas já respondidas.

## 3.0.9 — Identidade telefônica e fusos

- unifica celulares brasileiros informados com ou sem o nono dígito em todas as entradas e callbacks;
- migra e reúne leads, conversas e mensagens duplicadas, preservando pesquisas, pets, coletas e consentimentos;
- normaliza destinatários pendentes da fila, verificações e número diagnosticado da Z-API;
- mantém timestamps e agendamentos persistidos em UTC;
- adiciona fuso global e preferência individual por usuário, com conversão central em todas as páginas;
- corrige datas usadas nos placeholders e valida horários preferenciais e silêncio no fuso global.

## 3.0.8 — Redis opcional no Windows

- prepara automaticamente o Redis 8.10.0 em `tools\redis`, validando o SHA-256 oficial;
- inicia e encerra o processo local junto com o servidor, sem interferir em uma instância Redis já ativa;
- mantém fallback integral para SQLite quando o Redis estiver ausente ou indisponível;
- adiciona cache curto para métricas do painel, diagnóstico em Configurações e `/api/health`;
- limita o cache a 256 MB, acesso local e política LRU, sem mover dados persistentes para a memória.

## 3.0.7 — Identidade visual e personalização completa

- adiciona cor complementar configurável para gradientes e elimina tons principais fixos nos componentes;
- permite enviar logos horizontal, vertical e ícone em SVG, PNG, JPG ou WebP;
- adapta a marca ao menu expandido e recolhido e às telas públicas;
- gera automaticamente ícones PNG de 512 px, 192 px e favicon para o PWA;
- valida cores e conteúdo SVG, limita arquivos e atualiza o cache da identidade visual.

## 3.0.6 — Correção dos callbacks recebidos

- corrige o filtro que confundia `ReceivedCallback` com chamada telefônica;
- mensagens de texto, mídia, botões e listas voltam a entrar em Conversas;
- o botão de confirmação do WhatsApp agora avança da etapa “Lida” para “Confirmado”;
- respostas recebidas voltam a ser associadas às pesquisas ativas;
- recupera automaticamente callbacks reais descartados pela versão anterior;
- restaura mensagens antigas nas conversas sem duplicar registros.

## 3.0.5 — Fluxo rápido e catálogo de perguntas

- instala automaticamente o fluxo “Coleta rápida · legado 1.3”;
- preserva captura de nome e WhatsApp, confirmação do número e avaliação por mensagem;
- converte as 34 perguntas da versão 1.6 em nove questionários editáveis;
- separa os complementos D+2 de detratores, neutros e promotores;
- inclui modelos de ficha, estrutura, D+2, D+7, coleta rápida e retorno;
- usa chaves internas idempotentes para não duplicar modelos após reiniciar;
- atualiza bancos existentes automaticamente, inclusive quando a demonstração está desativada.

## 3.0.4 — Diagnóstico real de conexão e webhooks

- testa a rota pública antes de enviar a configuração à Z-API;
- identifica erros do túnel Cloudflare, inclusive HTTP 502;
- exibe o detalhe devolvido pela Z-API em erros HTTP, com credenciais mascaradas;
- diferencia credencial inválida de uma instância apenas desconectada;
- mantém endpoints de envio manuais separados dos webhooks e diagnósticos.

## 3.0.3 — Endpoint de envio configurável

- mantém a geração automática do endpoint da Z-API como padrão;
- adiciona opção manual validada na tela de configurações;
- aceita endpoint completo em `/send-text` ou modelo reutilizável com `{action}`;
- adapta o endereço manual para botões, listas, mídias, localização e contato;
- preserva diagnósticos, consultas e webhooks no endpoint oficial da instância;
- migra bancos existentes sem alterar a configuração atual.

## 3.0.2 — Revisão visual completa

- corrige os nomes abreviados na barra lateral expandida;
- restringe o menu hambúrguer a celulares e mantém a navegação lateral em computadores;
- padroniza alturas, larguras e distribuição dos botões nas configurações;
- consolida formulários, cards, tabelas, cabeçalhos, alertas e estados vazios;
- melhora os breakpoints para desktop, notebook, tablet e celular;
- amplia a cobertura do modo escuro e a navegação por teclado;
- substitui símbolos soltos por ícones SVG locais nas áreas principais;
- atualiza o cache da PWA para aplicar imediatamente o novo CSS.

## 3.0.1 — Correção do painel de aparência

- painel fechado passa a respeitar o atributo `hidden`;
- fechamento pelo botão, clique no fundo e tecla `Esc`;
- foco acessível contido no painel e devolvido ao botão de abertura;
- cache da PWA atualizado para distribuir o novo CSS e JavaScript.

## 3.0.0 — Integração completa e operação multiponto

- arquitetura simples da 2.2 preservada;
- navegação com ícones, menu recolhível, scroll, temas e preferências de acessibilidade;
- cidades, pontos de coleta e escopo de usuários por cidade;
- perfil de usuário expandido;
- lista ilimitada de ações por fluxo, horários reais e repetição por pet;
- idempotência por coleta/ação/questionário/pet;
- placeholders completos de pets, serviços e visita;
- associação por `referenceMessageId`;
- consentimento explícito para desconhecidos e importados;
- telefone ou LID como identidade WhatsApp;
- nome, foto, recado e sincronização do perfil;
- importação de contatos e chats;
- perguntas e respostas por mídia, localização e contato;
- envio multimídia na central de conversas;
- download privado e controlado de mídias antes da expiração;
- mensagens de correção para respostas inválidas;
- filtro de eventos técnicos do WhatsApp;
- estado `PLAYED` preservado;
- atraso entre abertura e primeira pergunta;
- supervisor único do servidor e worker, heartbeat e aviso visual;
- migração automática de bancos e fluxos 2.2;
- nova suíte de testes da versão 3.

## 2.2.0 — Fluxos de entrada

- novo tipo de configuração para captação por quiosque e entrevistador;
- formulário progressivo responsivo com localização de cadastro no modo assistido;
- múltiplos pets na mesma coleta;
- motivo, serviço, situação e descrição independentes por pet;
- tabelas estruturadas de sessões de coleta, pets envolvidos e comprovantes de consentimento;
- confirmação do WhatsApp com botão Z-API e token exclusivo;
- acompanhamento de envio, entrega, leitura, clique, falha e expiração;
- correção do telefone, reenvio e confirmação manual autorizada;
- modos de confirmação obrigatória, envio com continuidade, exigência apenas futura ou desativada;
- ação imediata na tela identificada, tela anônima ou WhatsApp;
- ação específica após confirmação e acompanhamento agendado;
- anonimato sem vínculo persistente com lead ou sessão de coleta;
- proteção contra acompanhamento duplicado;
- visualização das visitas e serviços por pet no detalhe do lead;
- fluxo demonstrativo pronto e teste automatizado de ponta a ponta.

## 2.1.2 — Editor com histórico seguro

- Corrigido `FOREIGN KEY constraint failed` ao editar questionários já respondidos.
- Sincronização incremental por ID no lugar de apagar e recriar todas as perguntas.
- Arquivamento lógico de perguntas com histórico.
- Exclusão física somente para perguntas ainda não utilizadas.
- Cancelamento seguro de mensagens pendentes de perguntas removidas.
- Filtro central de perguntas ativas no navegador, laboratório e WhatsApp.
- Migração automática compatível com bancos anteriores.
- Teste automatizado específico para edição, remoção e preservação de respostas.

## 2.1.1 — Domínio automático dos webhooks

- separa visualmente o endpoint de envio da Z-API do endereço receptor dos webhooks;
- gera o endpoint `/send-text` internamente a partir do ID e token, sem tratá-lo como callback;
- detecta o domínio atual por `Forwarded`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `Host` e `CF-Visitor`;
- usa automaticamente o domínio HTTPS pelo qual o administrador abriu o sistema;
- repara configurações antigas quando uma URL `api.z-api.io` foi colada no campo de webhook;
- preserva uma URL pública salva quando o painel é aberto apenas por `127.0.0.1` ou rede local;
- rejeita localhost, IP privado e endereço sem HTTPS na configuração remota;
- mostra na tela o domínio detectado e as cinco URLs finais antes da configuração;
- adiciona testes de reparo automático e proxy reverso.

## 2.1.0 — Z-API integrada

- configuração dos cinco webhooks diretamente pelo sistema;
- conferência remota das URLs pela consulta aos dados da instância;
- callbacks separados para recebimento, envio, status, conexão e desconexão;
- idempotência e histórico de eventos de webhook;
- atualização da fila para enviado, entregue, lido ou falhou;
- QR Code Z-API exibido na página de configurações;
- estado do aparelho, telefone, último diagnóstico e último callback;
- suporte a notificação de mensagens enviadas pela própria instância;
- proteção contra duplicidade ao espelhar mensagens próprias;
- leitura automática configurável;
- resposta por botões ou lista configurável em cada pergunta;
- modo automático: botões para até três opções e lista para mais opções;
- fallback numerado quando botões estiverem desabilitados;
- processamento de `buttonsResponseMessage` e `listResponseMessage`;
- novo teste automatizado específico da integração Z-API.

## 2.0.0 — Questionários Inteligentes

- nova aplicação FastAPI independente;
- banco SQLite novo e unificado;
- menu principal reduzido;
- editor único de questionários;
- WhatsApp, quiosque e entrevistador;
- onboarding de números desconhecidos;
- segmentação por regra e similaridade;
- alertas identificados e agregados anônimos;
- worker com fila, retentativa, silêncio, limite e simulação;
- Z-API com botões e webhook;
- pontos de coleta editáveis;
- usuários e alteração de senha;
- layout responsivo e PWA básica;
- teste de fumaça automatizado.
