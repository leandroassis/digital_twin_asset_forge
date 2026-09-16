# asset-forge

Pipeline para transformar o modelo IFC da planta solar em `assets/solar-plant/`
num IFC de planta decorado, com exportação para um pacote AAS (Asset
Administration Shell) e para uma malha 3D combinada (`.glb`), upload desse
pacote para um deployment Eclipse BaSyx (`infra/docker-compose.yml`, subido
localmente via `just basyx-up`), infraestrutura pronta para receber leituras
de sensores de um servidor OPC UA externo (config-only, ver
[DESCRIPTION.md](DESCRIPTION.md)), armazenamento histórico real dessas
leituras (InfluxDB + um serviço intermediário, history-api), um modelo de
detecção de anomalias por Z-Score espacial (`src/model/`) que sincroniza
alertas com o visualizador, e uma UI web (Three.js) para navegar a planta em
3D, inspecionar os submodelos AAS de cada componente e ver suas séries
temporais.

`assets/solar-plant/` é hoje o único projeto suportado — a etapa de
exportação AAS foi otimizada especificamente para essa planta (classificação
de painéis solares + um inversor sintético), não é mais um pipeline genérico
por projeto. Ver [DESCRIPTION.md](DESCRIPTION.md) para como cada etapa
funciona e por quê.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Ou, com [`just`](https://github.com/casey/just): `just setup`.

## Uso

```bash
# Converte o projeto: gera plant.ifc, um ou mais pacotes AAS (model-0001.aasx,
# model-0002.aasx, ... -- ver "Por que vários .aasx?" abaixo), um plant.glb e
# a config do DataBridge (infra/databridge/*.json)
asset-forge convert assets/solar-plant --namespace example.org/asset-forge

# Sobe cada .aasx gerado para um BaSyx local e registra as shells no registry
for f in assets/solar-plant/output/aas/*.aasx; do
  asset-forge basyx upload --aasx-path "$f"
done
asset-forge basyx clear
```

(`just basyx-upload solar-plant` já faz esse loop automaticamente — ver abaixo.)

Ver `asset-forge convert --help` para as opções de namespace, hosts/portas
do ambiente AAS, do datasheet OPC UA e do history-api (`src/asset_forge/config.py`
tem todos os defaults); `--no-glb`/`--no-databridge` desligam essas duas
saídas se não forem necessárias.

### Atalhos via `just`

```bash
just setup                  # cria o venv e instala o pacote
just convert-solar          # asset-forge convert assets/solar-plant (gera ifc/, aas/, glb/, infra/databridge/*.json)
just convert solar-plant --no-aas  # `just convert <projeto> <args extras do CLI>` (genérico, qualquer pasta em assets/)

just basyx-up               # sobe aas-environment + registry + UI + databridge + influxdb + history-api (Docker)
just basyx-upload solar-plant  # limpa e envia o .aasx do projeto para o BaSyx
just basyx-clear            # limpa shells/submodelos e seus descriptors no registry
just basyx-down             # para e remove todos os containers Docker

just up                     # basyx-up + model/data-gen/visualization como containers próprios (ver "Execução containerizada" abaixo)
just down                   # para e remove TODOS os containers (BaSyx + model/data-gen/visualization)

# Alternativa local (sem Docker) para model/data-gen/visualization, um de cada vez:
just simulate-profiles      # gera o perfil de perturbação de cada painel (data_gen, opcional)
just simulate               # loop de escrita+leitura+historização em cada Property opcua com dados fisicamente simulados (--once p/ uma rodada só)
just run-ai                 # roda o modelo de detecção de anomalias (Z-Score) via BaSyx/history-api
just viz-up                 # inicia o servidor FastAPI/Uvicorn do visualizador 3D (http://localhost:8000)

just test                   # suíte completa
just test-unit              # só unitários (rápidos)
just test-integration        # só integração (roda contra o .ifc real em assets/solar-plant)
just clean                  # remove output/ gerado de todo projeto em assets/
```

### BaSyx local + UI

`just basyx-up` sobe, via `infra/docker-compose.yml`, a stack completa:

| Serviço | URL | Persistência |
|---|---|---|
| AAS Environment (repositório de shells/submodelos) | **http://localhost:8081** | em memória |
| AAS Registry (descriptors) | **http://localhost:8082** | em memória |
| AAS Web UI | **http://localhost:3000** | — |
| DataBridge (bridge OPC UA → BaSyx, config-only) | porta 8085 | — |
| InfluxDB (histórico real de sensores) | **http://localhost:8086** | volume nomeado |
| history-api (intermediário sobre o InfluxDB) | **http://localhost:8090** | — |
| Visualizador Web (Three.js, fora do docker-compose) | **http://localhost:8000** | — |

O registry é **obrigatório**, não opt-in: `asset-forge basyx upload`/`clear`
sempre registram/limpam os shell descriptors no registry por padrão — o
próprio AAS Web UI lê `AAS_REGISTRY_PATH` ao carregar e quebra com
`TypeError: Failed to fetch` se não houver um registry respondendo naquele
endereço.

Depois de `just basyx-upload solar-plant`, abra http://localhost:3000 (UI
oficial do BaSyx) ou http://localhost:8000 (visualizador deste projeto, ver
abaixo) para navegar pelas shells enviadas. Todo componente carrega
`nameplate` + `technicaldata` (todos os psets do elemento, genericamente) +
sua própria geometria 3D (ver abaixo); só painéis solares, o inversor
virtual e sensores/medidores nativos (`IfcSensor`/`IfcFlowMeter`) também
carregam `opcua` (com `Property` graváveis por variável de sensor, quando
aplicável) e — só painéis/inversor — `timeseries` — ver
[DESCRIPTION.md](DESCRIPTION.md), seção 6, para a divisão exata.

**Geometria 3D no BaSyx:** todo elemento da planta (não só painéis) carrega,
no seu submodelo `technicaldata`, um `File` `Model3DIFC` com um `.ifc`
mínimo daquele componente, extraído do `plant.ifc` e empacotado como
arquivo suplementar dentro do `.aasx`. Confirmado ao vivo:
`GET /submodels/{id}/submodel-elements/Model3DIFC/attachment` retorna o
STEP de volta. O `plant.glb` combinado (ver "Visualizador web" abaixo)
continua sendo a forma prática de navegar a planta inteira de uma vez; o
`Model3DIFC` por elemento é para inspecionar/baixar um componente
específico via API do BaSyx.

### Por que vários `.aasx`?

`asset-forge convert` grava um `.aasx` por lote de até `DEFAULT_BATCH_SIZE`
elementos (hoje **900** — bem abaixo do total de qualquer projeto em
`assets/`, então sempre saem vários arquivos: `model-0001.aasx`,
`model-0002.aasx`, ...; só um projeto com ≤900 elementos sairia num único
`model.aasx`). O motivo: **todo** elemento agora carrega `TechnicalData`
completo (todos os psets) + sua própria geometria `Model3DIFC` anexada —
não só painéis solares (ver seção anterior) — e isso não cabe num único
pacote, por dois limites reais e independentes do Apache POI (usado pelo
BaSyx do lado do servidor para ler o pacote), cada um confirmado ao vivo
contra um BaSyx de verdade e nenhum configurável do nosso lado:

1. **Limite de bytes por parte interna do pacote.** `org.apache.poi.util.IOUtils`
   recusa alocar mais de 100.000.000 bytes para um único registro/parte ao
   ler o pacote de volta. Um `TechnicalData` completo (todos os psets) para
   os ~10.106 elementos da planta solar, tudo num único `data.json`,
   passaria bem desse cap.
2. **Limite de número de entradas no zip/pacote OPC.** A proteção contra zip
   bomb do Apache POI (`ZipSecureFile`) rejeita qualquer pacote com mais de
   1000 entradas no total. Como **todo** elemento com geometria anexada
   carrega seu próprio arquivo de anexo, um único lote de 900 elementos já
   soma ~906 entradas (900 arquivos `.ifc` + ~6 partes fixas de
   manifesto/rels) — folga confortável sob 1000; um lote maior passaria
   direto por esse teto.

Resultado medido, ao vivo, para o `solar-plant` de hoje: **12** arquivos
`model-0001.aasx`...`model-0012.aasx` (11 lotes de 900 elementos + 1 de
206), ~53MB no total, cada um com 906 entradas no zip (ou menos, no último
lote) — bem abaixo do teto de 1000 em todos. `asset-forge basyx
upload`/`just basyx-upload` já iteram sobre todo arquivo produzido, então
isso é transparente para quem só quer subir a planta pro BaSyx.

Outros dois bugs reais encontrados no mesmo processo, ambos já contornados:
- `spring.servlet.multipart.max-*-size` precisou ser aumentado no
  `aas-environment` (já configurado em `infra/docker-compose.yml`) — o
  padrão do Spring Boot (~1MB) rejeitava até um pacote de poucos MB com 413.
- IFC GlobalIds são case-sensitive, mas nomes de parte OPC (o que uma
  entrada do zip dentro do `.aasx` vira ao ser relida) são comparados
  ignorando maiúsculas/minúsculas — corrigido desambiguando nomes de
  arquivo colidentes por lote, ver `_attach_geometry` em
  `export/aas/package.py`.

### Visualizador web

`just viz-up` (local, via `python -m uvicorn`) ou `just up` (container, ver
"Execução containerizada" abaixo) sobem o app FastAPI + Three.js em
[src/visualization/](src/visualization/) em **http://localhost:8000**. Ele
lê tudo ao vivo — nada mockado do lado do visualizador:

- Carrega o `plant.glb` (ver DESCRIPTION.md, seção 8) da planta inteira;
  clicar numa malha ou selecionar um nó na árvore de ativos BaSyx (painel
  esquerdo) desliza a câmera suavemente até centralizar o componente.
- Reconstrói, no painel direito, a árvore completa dos submodelos AAS do
  componente selecionado (`nameplate`/`technicaldata`/`opcua`/`timeseries`,
  o que existir — nada hardcoded a 3 nomes fixos), direto da API do BaSyx.
- Busca a série histórica real do componente (painéis/inversor) seguindo o
  submodelo `timeseries` até o history-api (ver seção "InfluxDB" abaixo) —
  não gera dados sintéticos.
- Tem uma aba de alertas (CRUD em memória), populada pelo modelo de
  detecção de anomalias (`just run-ai`, ver `src/model/` abaixo) quando ele
  está rodando.

Requer `just basyx-up` + `just basyx-upload solar-plant` rodando para ter
dado real pra mostrar; sem isso, a árvore aparece vazia e o status "BaSyx
Offline".

**WebGL é opcional, não obrigatório:** confirmado ao vivo que
`THREE.WebGLRenderer` pode falhar ao criar contexto (navegador sandboxed,
VM/desktop remoto sem GPU repassada, aceleração de hardware desligada) —
`Viewer3D` captura essa falha na sua própria construção e degrada
graciosamente (mostra "Visualização 3D indisponível" no lugar do canvas 3D)
em vez de travar a inicialização inteira da SPA; árvore de ativos,
metadados AAS, séries temporais e alertas continuam funcionando
normalmente sem WebGL nenhum.

### Histórico de sensores (InfluxDB + history-api)

BaSyx só guarda o valor **atual** de cada `Property` de sensor, nunca um
histórico. Para isso existe:

- **InfluxDB** (`infra/docker-compose.yml`, volume nomeado — sobrevive a
  `docker compose down`), onde cada rodada de leituras é gravada (um ponto
  por asset por rodada, todas as variáveis daquele asset como campos
  separados do mesmo ponto).
- **history-api** (`src/asset_forge/history_api.py`, containerizado
  separadamente para não arrastar as dependências pesadas do resto do
  pacote): um serviço HTTP fino na frente do InfluxDB —
  `GET /series/{asset_id}?count=N` devolve a série já em JSON. O submodelo
  `timeseries` de cada painel/inversor (ver DESCRIPTION.md) aponta pra cá,
  nunca direto pro InfluxDB — `Segments.LinkedSegment.Query` é só um id
  plano (`PANEL-1529520`, `INVERTER`), nunca uma query Flux.

Ver [INTEGRATION.md](INTEGRATION.md) para exemplos completos de leitura
(`$value`, histórico via history-api) e escrita manual de sensores.

### Simulação de sensores (`src/data_gen/`)

Nenhum servidor/cliente OPC UA real existe neste repositório — receber
dados de um servidor OPC UA real é o que a config do DataBridge
(`infra/databridge/*.json`, gerada por `asset-forge convert`) já está
pronta para fazer, mas o servidor em si é responsabilidade de outro
projeto/equipe.

Para testar que o caminho BaSyx-todo está unificado sem esperar por esse
serviço externo, `just simulate` (`src/data_gen/send_to_basyx.py`) escreve
valores fisicamente simulados (via o modelo de painel fotovoltaico em
`model_pv.py`, não valores aleatórios) direto nos `Property` do submodelo
`opcua` de cada painel via a própria API do BaSyx, lê cada um de volta pra
confirmar, e historiza a rodada no InfluxDB — dirigido pelo mesmo
`infra/databridge/aasserver.json` que o DataBridge real usaria, então
exercita exatamente os mesmos alvos. `--once` faz uma rodada só;
`--interval` controla o intervalo entre rodadas em loop. `just
simulate-profiles` (opcional, ver [src/data_gen/README.md](src/data_gen/README.md))
gera antes um perfil de perturbação por painel, pra painéis não reportarem
todos o mesmo valor e pra exercitar o modelo de anomalias com desvios
propositais.

### `src/model/`

Modelo de detecção de anomalias por Z-Score espacial: compara cada painel
contra seus pares no campo (temperatura, corrente DC) para classificar
Sujeira/Sobreaquecimento/Sobrecorrente/Noite, resolvendo o histórico de
cada painel via o submodelo `timeseries` de sua shell no BaSyx + o
history-api que ele aponta para (nunca conecta no InfluxDB diretamente) e
sincronizando alertas com a aba "Alertas IA" do visualizador
(`POST`/`DELETE /api/alerts`). Limiares configuráveis via
`config/rules.json` (hot-reload automático se o arquivo mudar em disco) ou
flags `--z-*`/`--max-*`. Rodar com `just run-ai` (ou `asset-forge model
run --config config/rules.json`); `--once` faz uma única rodada de
avaliação.

### Execução containerizada (`just up`)

`model`, `data-gen` e `visualization` são processos independentes — cada um
sua própria CLI/servidor, cada um só conversando com o resto do sistema via
API HTTP (BaSyx, history-api, e entre si, ver [INTEGRATION.md](INTEGRATION.md)),
nunca por import direto de código de outro módulo em tempo de execução.
Além de rodar cada um localmente (`just simulate`/`just run-ai`/`just
viz-up`, seção anterior), os três também sobem como containers próprios via
`infra/docker-compose.apps.yml` (Dockerfiles em `infra/model/`,
`infra/data-gen/`, `infra/visualization/`):

```bash
just up      # sobe basyx-up + os três containers, tudo junto
just down    # derruba tudo (BaSyx + os três)
```

`just basyx-up`/`just basyx-down` continuam existindo e inalterados — só
sobem a stack BaSyx em si; `just up`/`just down` são a versão que também
sobe/derruba `model`/`data-gen`/`visualization`. Depois de `just up`,
`asset-forge convert`/`basyx upload` continuam rodando localmente (não
viraram serviço — são comandos de um-tiro, não processos de longa duração);
suba a planta primeiro (seção "BaSyx local + UI" acima) para os três
containers terem dado real com o que trabalhar.

Os três usam `network_mode: host` (só Linux) em vez da rede
bridge/nomes-de-serviço que o resto do `docker-compose.yml` usa — o motivo
é que o submodelo `timeseries` de cada painel já grava `Endpoint =
http://localhost:8090` no momento do `convert` (não existe flag de CLI pra
mudar isso hoje), então esses três containers precisam ver "localhost" da
mesma forma que o host vê, sem precisar reconverter/reenviar a planta com
outro endpoint. Ver o comentário no topo de
[infra/docker-compose.apps.yml](infra/docker-compose.apps.yml) e
DESCRIPTION.md, seção 13, para o detalhe completo.

## Estrutura

```
src/
├── asset_forge/
│   ├── pipeline/       # Stage/Record/PlantPipeline -- abstrações genéricas de pipeline por elemento
│   ├── ingestion/       # abrir + sanitizar um .ifc; federar múltiplos .ifc de um mesmo projeto
│   ├── elements/         # leitura defensiva de psets; classificação passthrough + fallback genérico
│   ├── linking/          # conexões nativas do IFC (sem heurística geométrica)
│   ├── export/
│   │   ├── ifc_writer.py     # grava o plant.ifc final
│   │   ├── glb.py            # malha .glb combinada da planta inteira
│   │   ├── dexpi_builder.py  # plano de conexões -> pydexpi.DexpiModel
│   │   ├── dexpi_export.py   # JSON/GraphML/Proteus XML via pydexpi
│   │   └── aas/               # templates IDTA, solar.py (painéis/inversor), submodelos, shell,
│   │                          # pacote .aasx, databridge.py (config OPC UA -> BaSyx)
│   ├── integration/
│   │   ├── basyx_client.py     # upload/clear no BaSyx
│   │   ├── sensor_targets.py   # aasserver.json -> targets (submodelo, idShort) + write/read do $value
│   │   └── timeseries.py       # resolve o submodelo timeseries de cada shell -> Endpoint/Query do history-api
│   ├── history_api.py    # serviço HTTP fino na frente do InfluxDB (containerizado à parte)
│   └── cli.py
├── model/                # detecção de anomalias por Z-Score espacial + sincronização de alertas
├── data_gen/             # simulação física de sensores (model_pv.py) -> BaSyx + InfluxDB (script isolado, ver seu README)
└── visualization/         # app FastAPI + Three.js separado (não instalável via pip -e .)
    ├── main.py            # rotas REST (models/tree/metadata/telemetry/alerts)
    ├── basyx_vis/         # cliente BaSyx + reconstrução de árvore de submodelos/telemetria
    └── web/               # SPA (Three.js, árvore de ativos, dashboard, alertas)
```

```
infra/
├── docker-compose.yml       # stack BaSyx (aas-environment, registry, UI, databridge, influxdb, history-api) -- just basyx-up
├── docker-compose.apps.yml  # model/data-gen/visualization como containers -- just up (junto com o arquivo acima)
├── history-api/Dockerfile
├── model/Dockerfile
├── data-gen/Dockerfile
└── visualization/Dockerfile
```

## Testes

```bash
.venv/bin/pytest tests/            # unitários (rápidos) + integração (rodam contra o .ifc real em assets/solar-plant, mais lentos)
.venv/bin/pytest tests/unit        # só unitários
```
