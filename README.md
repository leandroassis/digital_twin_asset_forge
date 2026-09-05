# asset-forge

Pipeline para transformar o modelo IFC da planta solar em `assets/solar-plant/`
num IFC de planta decorado, com exportação para um pacote AAS (Asset
Administration Shell) e para uma malha 3D combinada (`.glb`), upload desse
pacote para um deployment Eclipse BaSyx (`infra/docker-compose.yml`, subido
localmente via `just basyx-up`), infraestrutura pronta para receber leituras
de sensores de um servidor OPC UA externo (config-only, ver
[DESCRIPTION.md](DESCRIPTION.md)), armazenamento histórico real dessas
leituras (InfluxDB + um serviço intermediário, history-api), e uma UI web
(Three.js) para navegar a planta em 3D, inspecionar os submodelos AAS de
cada componente e ver suas séries temporais.

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
# Converte o projeto: gera plant.ifc, um pacote AAS único, um plant.glb e a
# config do DataBridge (infra/databridge/*.json)
asset-forge convert assets/solar-plant --namespace example.org/asset-forge

# Sobe o .aasx gerado para um BaSyx local e registra as shells no registry
asset-forge basyx upload --aasx-path assets/solar-plant/output/aas/model.aasx
asset-forge basyx clear
```

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

just mock-sensor            # loop de escrita+leitura+historização em cada Property opcua (--once p/ uma rodada só)
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
abaixo) para navegar pelas shells enviadas. Cada componente carrega, no
mínimo, `technicaldata`; painéis solares e o inversor também carregam
`nameplate`, `opcua` (com `Property` graváveis por variável de sensor) e
`timeseries` — ver [DESCRIPTION.md](DESCRIPTION.md) para a divisão exata.

**Geometria 3D no BaSyx:** todo painel solar (e só painéis — ver
DESCRIPTION.md) carrega, no seu submodelo `technicaldata`, um `File`
`Model3DIFC` com um `.ifc` mínimo daquele componente, extraído do
`plant.ifc` e empacotado como arquivo suplementar dentro do `.aasx`.
Confirmado ao vivo: `GET /submodels/{id}/submodel-elements/Model3DIFC/attachment`
retorna o STEP de volta. O resto da planta (~9.499 elementos) não carrega
geometria individual no AAS — a referência 3D deles é o `plant.glb`
combinado (ver "Visualizador web" abaixo).

### Por que um único `.aasx`?

`asset-forge convert` grava um `.aasx` por lote de até `DEFAULT_BATCH_SIZE`
elementos (hoje 20.000 — acima do total de qualquer projeto em `assets/`,
então sempre sai um único `model.aasx`; só se esse limite fosse excedido
sairia `model-0001.aasx`, `model-0002.aasx`, ...). Isso não era sempre
verdade: o **conteúdo** de cada shell é que precisou mudar para caber num
único pacote, por dois limites reais e independentes do Apache POI (usado
pelo BaSyx do lado do servidor para ler o pacote), cada um confirmado ao
vivo contra um BaSyx de verdade e nenhum configurável do nosso lado:

1. **Limite de bytes por parte interna do pacote.** `org.apache.poi.util.IOUtils`
   recusa alocar mais de 100.000.000 bytes para um único registro/parte ao
   ler o pacote de volta. Um `TechnicalData` completo (todos os psets, sem
   split) para os ~10.106 elementos da planta solar mediria dezenas de MB
   de sobra desse cap.
2. **Limite de número de entradas no zip/pacote OPC.** A proteção contra zip
   bomb do Apache POI (`ZipSecureFile`) rejeita qualquer pacote com mais de
   1000 entradas no total. Como cada elemento com geometria anexada carrega
   seu próprio arquivo de anexo, anexar geometria a todos os ~10.106
   elementos sozinho já estouraria esse limite.

A solução: uma divisão **full/lean** por elemento (ver DESCRIPTION.md, seção
6) — só painéis solares (607) e o inversor virtual recebem `TechnicalData`
completo + geometria anexada + `opcua`/`timeseries`; os ~9.499 elementos
restantes recebem um `TechnicalData` resumido de 5 campos, sem geometria.
Resultado medido, ao vivo, para o `solar-plant` de hoje: **um único**
`model.aasx` de 4,5MB no disco, `data.json` interno de 48.245.990 bytes
(bem abaixo do cap de 100MB) e 613 entradas no zip (bem abaixo de 1000).

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

`just viz-up` sobe, fora do `docker-compose` (roda direto via
`python -m uvicorn`), o app FastAPI + Three.js em
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
- Tem uma aba de alertas (CRUD em memória, sem modelo de IA por trás ainda —
  ver `src/model/` abaixo).

Requer `just basyx-up` + `just basyx-upload solar-plant` rodando para ter
dado real pra mostrar; sem isso, a árvore aparece vazia e o status "BaSyx
Offline".

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

### Servidor mock de sensores

Nenhum servidor/cliente OPC UA real existe neste repositório — receber
dados de um servidor OPC UA real é o que a config do DataBridge
(`infra/databridge/*.json`, gerada por `asset-forge convert`) já está
pronta para fazer, mas o servidor em si é responsabilidade de outro
projeto/equipe.

Para testar que o caminho BaSyx-todo está unificado sem esperar por esse
serviço externo, `just mock-sensor` (`src/mock_data/mock_sensor.py`) escreve
valores sintéticos direto nos `Property` do submodelo `opcua` de cada
painel/inversor via a própria API do BaSyx, lê cada um de volta pra
confirmar, e historiza a rodada no InfluxDB — dirigido pelo mesmo
`infra/databridge/aasserver.json` que o DataBridge real usaria, então
exercita exatamente os mesmos alvos. `--once` faz uma rodada só;
`--interval` controla o intervalo entre rodadas em loop.

### `src/model/`

Pasta reservada para o futuro modelo de IA (detecção de anomalias sobre o
histórico do history-api/InfluxDB, alimentando a aba de alertas do
visualizador). Hoje vazia, só `.gitkeep` — sem implementação ainda.

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
│   │   └── basyx_client.py   # upload/clear no BaSyx
│   ├── history_api.py    # serviço HTTP fino na frente do InfluxDB (containerizado à parte)
│   └── cli.py
├── mock_data/
│   └── mock_sensor.py    # harness de teste: escreve/lê valores sintéticos direto na API do BaSyx
├── model/                # reservado para o futuro modelo de IA (vazio hoje)
└── visualization/         # app FastAPI + Three.js separado (não instalável via pip -e .)
    ├── main.py            # rotas REST (models/tree/metadata/telemetry/alerts)
    ├── basyx_vis/         # cliente BaSyx + reconstrução de árvore de submodelos/telemetria
    └── web/               # SPA (Three.js, árvore de ativos, dashboard, alertas)
```

## Testes

```bash
.venv/bin/pytest tests/            # unitários (rápidos) + integração (rodam contra o .ifc real em assets/solar-plant, mais lentos)
.venv/bin/pytest tests/unit        # só unitários
```
