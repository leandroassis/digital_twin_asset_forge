# Como o pipeline funciona

Este documento explica a lógica implementada em [src/asset_forge/](src/asset_forge/),
[src/data_gen/](src/data_gen/), [src/model/](src/model/) e
[src/visualization/](src/visualization/): o que cada etapa faz, por que ela
existe, e quais arquivos são responsáveis por cada decisão. Para instruções
de uso (CLI, `just`, BaSyx local, visualizador), ver [README.md](README.md).
Para ler/escrever dados de sensores via API do BaSyx ou do history-api, ver
[INTEGRATION.md](INTEGRATION.md).

## Visão geral

O pipeline em si (ingestão, federação, classificação, DEXPI) continua
genérico — qualquer subpasta de `assets/` com um ou mais `.ifc` funciona.
Mas a etapa de exportação AAS **não é mais genérica por projeto**: ela foi
otimizada especificamente para a planta solar que hoje é o único conteúdo de
`assets/` (`assets/solar-plant/`), com uma regra de classificação de painéis
solares e um inversor sintético (ver seção 6). `asset-forge convert
assets/solar-plant` roda o projeto pelo pipeline inteiro e produz, em
`assets/solar-plant/output/`:

```
output/
├── ifc/
│   └── plant.ifc          # o IFC único e federado do projeto
├── dexpi/                 # só se o IFC de origem tiver conexões nativas
│   ├── model.json
│   ├── model.graphml
│   └── model.xml
├── aas/
│   └── model-0001.aasx, model-0002.aasx, ...  # um ou mais pacotes AAS, batched (ver seção 6 e "Por que vários .aasx?" no README)
└── glb/
    └── plant.glb           # malha 3D da planta inteira (ver seção 8)
```

O fluxo, em ordem (`cli.py:convert` chama cada etapa nesta sequência):

```
.ifc (1+ arquivos)
  → ingestion/loader.py    (abre + sanitiza cada arquivo)
  → ingestion/federation.py (combina múltiplos .ifc num só, se houver mais de um)
  → elements/classification.py (passthrough + fallback genérico)
  = plant.ifc
      → linking/native.py + export/dexpi_builder.py + dexpi_export.py  (condicional)
      → export/aas/*      → integration/basyx_client.py (upload, comando separado)
      → export/glb.py     (malha 3D da planta inteira)
```

`export/ifc_writer.py:build_plant()` executa os três primeiros passos e
retorna o `ifcopenshell.file` já federado e classificado; DEXPI, AAS e GLB
partem desse mesmo modelo em memória, cada um seguindo seu próprio caminho.

## 1. Ingestão

**[ingestion/loader.py](src/asset_forge/ingestion/loader.py)** — abre um único `.ifc`. Antes de
passar para `ifcopenshell.open()`, faz uma cópia sanitizada: alguns
exportadores vendor deixam barras invertidas soltas dentro de strings STEP
(ex.: caminhos Windows), o que desalinha o tokenizer STEP e corrompe atributos
seguintes na mesma entidade. `_escape_bare_backslashes()` dobra essas barras
soltas, mas reconhece e preserva os escapes reais do Annex E da ISO-10303-21
(`\S\`, `\X\`, `\X2\...\X0\`, `\X4\...\X0\`, `\P_\`) — usados por exportadores
para caracteres não-ASCII.

**[ingestion/federation.py](src/asset_forge/ingestion/federation.py)** — quando um projeto tem
mais de um `.ifc`, escolhe como base o arquivo com mais `IfcBuildingStorey` (a
estrutura espacial mais completa) e copia cada elemento dos demais arquivos
para dentro dele:

- Casa cada `IfcBuildingStorey` de origem com um da base por `GlobalId`,
  depois por `Name`; sem correspondência, cria um andar de acolhimento
  (`unmatched (<arquivo>)`).
- `ifcopenshell.file.add()` só segue referências *forward* (geometria,
  posicionamento, tipo) — nunca relações inversas. Por isso `_copy_element()`
  soma manualmente `IsDefinedBy` (psets), `IsTypedBy` e `IsNestedBy` → portas
  → `ConnectedTo`/`ConnectedFrom`, senão um elemento copiado chegaria sem
  metadados nem conexões.
- Cada elemento copiado recebe um pset `Pset_SourceProvenance` (`SourceFile`)
  para rastreabilidade.
- Além do pset, todo elemento (inclusive os já nativos do arquivo-base) é
  atribuído a um `IfcGroup` por disciplina/arquivo de origem (via
  `IfcRelAssignsToGroup`, um grupo por `SourceFile`) — permite isolar/ocultar
  uma disciplina inteira num viewer IFC. Ver `_group_by_discipline` em
  `ingestion/federation.py`.
- Nenhuma conversão de unidade é feita: cada elemento carrega consigo seu
  próprio `IfcGeometricRepresentationContext`/`IfcUnitAssignment`.

Com um único `.ifc` de entrada (caso atual do `solar-plant`), este passo é
passthrough.

## 2. Classificação

**[elements/classification.py](src/asset_forge/elements/classification.py)** — **não há
reclassificação semântica**. Se o elemento de origem já é uma classe IFC
concreta e específica (`IfcValve`, `IfcWall`, ...), ele não é tocado. Só
elementos presos na classe genérica placeholder do schema
(`IfcBuildingElementProxy`) passam por uma "promoção", que na prática é um
no-op: resolve o nome da classe genérica válida no schema do arquivo
carregado (nunca hardcoded) e usa `ifcopenshell.api.root.reassign_class`.
Nenhuma tabela de regras de inferência (por pset vendor, por nome, etc.)
existe — não é esse o objetivo deste pipeline.

**[elements/properties.py](src/asset_forge/elements/properties.py)** — usado tanto aqui quanto
na exportação AAS: lê cada propriedade de cada pset individualmente, dentro do
seu próprio `try/except`. `ifcopenshell.util.element.get_psets()` (a função
padrão da lib) lança `RuntimeError` e aborta a leitura inteira se uma única
propriedade estiver malformada — inaceitável quando se quer decorar o máximo
de metadados possível mesmo de fontes imperfeitas.

## 3. Conectividade nativa (condiciona o DEXPI)

**[linking/native.py](src/asset_forge/linking/native.py)** — lê **só** relações de
conectividade já presentes no IFC de origem: `IfcRelConnectsPorts` (conexão
porta-a-porta) e `IfcRelConnectsElements` (elemento-a-elemento direto). Não
existe fallback geométrico — se `find_connections()` não achar nada, retorna
lista vazia, e é esse vazio que `dexpi_builder.py` usa como sinal para pular a
exportação DEXPI com um aviso claro, em vez de reconstruir topologia por
proximidade/geometria (heurística descartada deliberadamente). A planta solar
de hoje não tem conexões nativas modeladas, então o DEXPI é pulado nela.

## 4. Saída IFC única

**[export/ifc_writer.py](src/asset_forge/export/ifc_writer.py)** — `build_plant()` roda os
passos 1-3 e retorna o modelo em memória; `write_plant()` grava
`plant.ifc`. Não há split por componente.

## 5. DEXPI (condicional)

**[export/dexpi_builder.py](src/asset_forge/export/dexpi_builder.py)** — só roda se o passo 3
encontrou pelo menos uma conexão nativa; senão levanta `DexpiUnavailableError`,
que o CLI captura e reporta como aviso, seguindo o resto do pipeline
normalmente. Escopo limitado aos elementos que participam de pelo menos uma
conexão; mapeamento deliberadamente conservador (só `IfcTank` vira um
equipamento DEXPI reconhecido, todo o resto vira `CustomPipingComponent`
genérico).

**[export/dexpi_export.py](src/asset_forge/export/dexpi_export.py)** — serializa o
`DexpiModel` resultante em `model.json`, `model.graphml` e `model.xml`.

## 6. AAS (Asset Administration Shell)

Todo o código fica em `export/aas/`. Uma Shell é criada por elemento do IFC
(via `plant_model.by_type("IfcElement")`, 10.106 no `solar-plant` de hoje),
mais uma shell **virtual** para o inversor (sem `IfcElement` de origem, ver
abaixo) — 10.107 shells no total. **Toda** shell recebe o mesmo `Nameplate` +
`TechnicalData` completo + geometria anexada — não existe mais uma divisão
"full/lean" por tipo de elemento (uma versão anterior deste pipeline tinha
essa divisão; foi removida). O que continua variando por elemento é só
`opcua`/`timeseries`, escopados a quem tem uma leitura de sensor real por
trás:

### Classificação: painel solar vs. resto (só para `opcua`/`timeseries`)

**[solar.py](src/asset_forge/export/aas/solar.py)** — `is_solar_panel(entity)` faz um
match case-insensitive de substring (`"solar panel"`) em `Name`/`ObjectType`
do elemento; não é hardcoded ao nome exato da família Revit
(`Solar Panel_ZCB:...`), então uma família de painel com nome diferente ainda
seria reconhecida. Este módulo também define as variáveis OPC UA de cada
papel (ver "Diagrama de arquitetura" — Intensidade Luminosa, Temperatura,
Corrente/Tensão CC por painel; Tensão/Corrente/Potência CA na saída do
inversor):

```python
PANEL_VARIABLES = (LightIntensity/LUX, Temperature/TEMP, CurrentDC/IDC, VoltageDC/VDC)
INVERTER_VARIABLES = (VoltageAC/VAC, CurrentAC/IAC, PowerAC/PAC)
```

No `solar-plant` de hoje: 607 dos 10.106 `IfcElement` são painéis
(`is_solar_panel` == True). Não existe `IfcElement` para o inversor no IFC
de origem — ele é representado por uma shell sintética (ver "Inversor
virtual").

### O que cada shell recebe

- **`build_nameplate_submodel`** (toda shell): só os campos que o elemento
  realmente tem (`URIOfTheProduct`, `UniqueFacilityIdentifier` = GlobalId,
  `ManufacturerProductDesignation` = Name) — nada de fabricante/número de
  série inventado.
- **`build_technicaldata_submodel`** (toda shell): carrega **todos** os
  psets do elemento genericamente, um `SubmodelElementCollection` por pset,
  um `Property` string por propriedade — não é mais uma versão exclusiva de
  painéis; toda shell recebe a mesma decoração completa.
- **`_attach_geometry`** (`package.py`, toda shell IFC-backed): anexa a
  própria geometria do elemento como `Model3DIFC` no `technicaldata` (ver
  "Empacotamento" abaixo) — também não é mais exclusivo de painéis.
- **`build_opcua_submodel`**: a "folha de dados" IDTA de um **servidor** OPC
  UA (endpoint montado de `host`/`port`/`endpoint_path`, modo de segurança
  "None"). Só é adicionado a painéis, ao inversor virtual, e a elementos
  `IfcSensor`/`IfcFlowMeter` (`_OPCUA_ELIGIBLE_CLASSES` em `package.py`) —
  uma leitura OPC UA só existiria mesmo para um sensor/medidor real, então o
  resto da planta (vigas, dutos, paredes, ...) não recebe esse submodelo.
  Para painéis/inversor, um parâmetro `variables` opcional adiciona um
  `Property` gravável por variável (`id_short=variável.id_short`,
  `value=0.0`) diretamente no mesmo submodelo — é assim que um único painel
  expõe 4 leituras independentemente endereçáveis por um servidor OPC UA
  externo (real ou simulado, ver seção 9), sem precisar de 4 submodelos.
  `IfcSensor`/`IfcFlowMeter` que não são painel/inversor recebem o
  `opcua` **sem** `variables` (só a config de conexão).
- **`build_timeseries_submodel`**: um descritor TimeSeries (IDTA 02008,
  registrado em `templates.py`) com exatamente um `Segments.LinkedSegment`
  (não `InternalSegment`/`ExternalSegment` — removidos do template) — só
  painéis e o inversor virtual (não `IfcSensor`/`IfcFlowMeter` genéricos,
  que não têm uma rodada de simulação/histórico definida para eles). Ver
  "Histórico de sensores" abaixo para por que ele aponta pro history-api e
  não direto pro InfluxDB.

### Inversor virtual

Não existe `IfcElement` para o inversor no `.ifc` de origem, só a saída CA
agregada da planta (ver diagrama de arquitetura). Para representar isso sem
inventar uma entidade IFC:

- **[shell.py](src/asset_forge/export/aas/shell.py)** — `build_virtual_shell(id_short, name,
  namespace, submodels)` espelha `build_shell`, mas usa o esquema de id
  `aas/virtual/{id_short}` em vez de `aas/ifc/{global_id}` — shells
  IFC-backed e sintéticas são distinguíveis só por esse segmento de path.
- **`build_virtual_nameplate_submodel`** (em `submodels.py`) é a variante de
  `build_nameplate_submodel` alimentada por strings literais em vez dos
  atributos de uma entidade IFC.
- `package.py::_build_inverter_shell` monta essa shell uma única vez por
  conversão (`Nameplate` + `opcua` com `INVERTER_VARIABLES` + `timeseries`),
  injetada só no primeiro lote — sem `Model3DIFC` (não há geometria de
  origem para extrair).

### Empacotamento

**[templates.py](src/asset_forge/export/aas/templates.py)** — baixa (uma vez, cacheado em
`data/submodels/`) os templates oficiais IDTA (Nameplate v3.0.1,
TechnicalData v2.0.1, OPC UA Server Datasheet v1.0, Time Series Data 1.1.1),
e corrige problemas confirmados contra um BaSyx real (`Blob` `null` vira
`b""`, `kind=TEMPLATE` vira `kind=INSTANCE`).

**[idshort.py](src/asset_forge/export/aas/idshort.py)** — `valid_id_short`/`unique_id_shorts`:
qualquer texto livre vira um `idShort` válido pela regra AASd-002
(`[0-9a-zA-Z_-]`, começando por letra), com sufixos numéricos para colisões.

**[geometry.py](src/asset_forge/export/aas/geometry.py)** — `extract_element_ifc()`: recorta
um `.ifc` mínimo contendo só aquele componente (+ o `IfcProject`
compartilhado), anexado ao `technicaldata` de toda shell IFC-backed (ver
"Geometria 3D no BaSyx" no README) — o inversor virtual é a única exceção,
por não ter geometria de origem.

**[package.py](src/asset_forge/export/aas/package.py)** — monta as Shells/submodelos e
grava um ou mais `model-NNNN.aasx` em `output/aas/`, batched por
`batch_size` elementos (hoje `DEFAULT_BATCH_SIZE = 900`; ver "Por que vários
`.aasx`?" no README para o porquê desse número — bem abaixo do total de
elementos de qualquer projeto em `assets/`, então sempre saem vários
arquivos hoje, nunca um único `model.aasx`). Também é aqui que a colisão de
nomes de arquivo de geometria (GlobalIds que diferem só em
maiúscula/minúscula) é evitada, e onde `write_databridge_config` é chamado
ao final se algum contrato OPC UA foi produzido (ver seção 7).

## 7. DataBridge (config para receber dados de um servidor OPC UA externo)

**[databridge.py](src/asset_forge/export/aas/databridge.py)** — gera a configuração que uma
instância real do Eclipse BaSyx DataBridge precisa para escrever valores de
um servidor OPC UA externo direto nos `Property` graváveis do submodelo
`opcua` de cada painel/inversor. É só configuração — nenhum código de
cliente/servidor OPC UA existe neste repositório; o serviço que realmente
gera os dados de sensores (mockado ou real) é responsabilidade de outro
projeto/equipe.

Para cada `(asset, variável)` (ex.: painel `PANEL-1529520`, variável
`CurrentDC`), três arquivos são escritos em `infra/databridge/` (formato
confirmado contra um deployment real de BaSyx DataBridge):

- `opcuaconsumer.json`: um consumidor por variável, esperando um node OPC UA
  `ns=2;s=PANEL-1529520-IDC` no servidor apontado por `--host-opcua`/
  `--port-opcua`.
- `aasserver.json`: o destino BaSyx correspondente — submodelo `opcua`
  daquele painel (id já codificado em base64url) + `idShortPath=CurrentDC`.
- `routes.json`: liga cada par consumidor→destino por `uniqueId`, disparado
  por evento.

Um servidor OPC UA externo (real ou mockado) só precisa expor um node
Variable nomeado exatamente `ns=2;s=<prefixo>-<sufixo>` por variável — nunca
precisa ler o código deste pipeline para saber onde escrever. Ver
[INTEGRATION.md](INTEGRATION.md) para como testar esse contrato sem um
servidor OPC UA de verdade.

## 8. GLB (malha 3D da planta inteira)

**[glb.py](src/asset_forge/export/glb.py)** — `build_and_write_glb()` triangula todo
`IfcElement` da planta (via `ifcopenshell.geom.iterator`) e escreve **um
único** `plant.glb` para a planta inteira — não um arquivo por componente
(isso já existe via `Model3DIFC`, ver seção 6). Dentro desse arquivo único,
ainda assim um `Node` glTF por elemento (`node.name = GlobalId`), para que o
visualizador possa selecionar/destacar um elemento específico por GlobalId
dentro da malha combinada.

Dois problemas de fidelidade visual foram corrigidos, ambos confirmados
contra o `plant.ifc` real (10.106 elementos):

- **Rotação**: IFC é Z-up, glTF/three.js é Y-up. Em vez de transformar cada
  vértice, todos os nós de elemento ficam sob um único nó raiz (`"plant"`)
  carregando a rotação de correção (-90° em X, como quaternion) — se o GLB
  fosse consumido sem essa correção, a planta aparecia deitada de lado.
- **Cor**: cada elemento carrega seu(s) estilo(s) de superfície IFC reais
  (`geometry.materials`/`material_ids` do `ifcopenshell.geom`), convertidos
  em materiais glTF (`baseColorFactor` + `alphaMode`, deduplicados
  globalmente — ~29 materiais distintos para a planta inteira) e agrupados
  em primitivas por material. Sem isso, todo elemento saía sem material
  atribuído, e o glTF-loader do three.js aplica seu próprio material padrão
  (visual "sem cor"). Um bug real foi encontrado nesse processo: ~26% dos
  elementos (dutos/conexões de HVAC com um estilo `"DefaultMaterial"`)
  reportam `transparency=NaN` — `max(0.0, 1.0 - nan)` avalia silenciosamente
  para `0.0` em Python, o que teria renderizado mais de um quarto da planta
  como **invisível**. Um elemento sem nenhum `IfcStyledItem` recebe do
  próprio `ifcopenshell` um material-placeholder sintético com
  `transparency=1.0` (mesmo efeito). Ambos os casos são forçados a opaco em
  `_resolve_rgba` — nenhum dos dois reflete intenção real de esconder a
  superfície.

Dependência nova: `pygltflib` (Python puro, sem binário nativo — não existe
`IfcConvert` neste ambiente).

## 9. Simulação de sensores (teste local do pipeline BaSyx)

**[asset_forge/integration/sensor_targets.py](src/asset_forge/integration/sensor_targets.py)**
parses `infra/databridge/aasserver.json`'s sink entries into typed
`(submodel, idShort, asset_tag)` targets and exposes the `PATCH .../$value`
+ `GET .../$value` helpers every sensor driver reuses (`load_targets`,
`write_value`, `read_value`) — not the real OPC UA sensor service itself
(that's responsibility of another project/team, see section 7).

**[data_gen/send_to_basyx.py](src/data_gen/send_to_basyx.py)** — não é o
serviço real de sensores OPC UA. É um driver de teste local que escreve
valores **fisicamente simulados** (via o modelo de painel fotovoltaico de
diodo único em `model_pv.py`, não valores aleatórios) diretamente nos
`Property` do submodelo `opcua` de cada painel, usando os alvos e helpers de
`sensor_targets.py` acima, lê cada um de volta pra confirmar que bateu, e
historiza a rodada inteira no InfluxDB (ver seção 10) — tudo isso prova que
o caminho de escrita e o de leitura da API do BaSyx concordam sobre o mesmo
dado, e que o histórico está sendo persistido de forma unificada, sem
precisar de nenhum servidor OPC UA de verdade. Cada painel aplica seu
próprio perfil de perturbação (`perturbation.py`/`generate_profiles_cli.py`)
sobre a série base de irradiância/temperatura, então painéis não reportam
todos o mesmo valor — e desvios propositais nesse perfil exercitam o modelo
de detecção de anomalias (seção 12) de ponta a ponta.

Dirigido por `infra/databridge/aasserver.json` — o mesmo arquivo que a
seção 7 gera para o DataBridge real — então ele exercita exatamente os
mesmos pares `(submodelo, idShortPath)` que o DataBridge real escreveria,
sem duplicar a lista de painéis em nenhum lugar novo. Só painéis — o
inversor virtual (`VoltageAC`/`CurrentAC`/`PowerAC`) fica de fora, precisaria
de um modelo de agregação DC→AC que ainda não existe.

Confirmado ao vivo contra um `aas-environment` real (2.0.0-SNAPSHOT): o
corpo do `PATCH .../$value` precisa ser o valor **codificado como string
JSON** (`"42.5"`, não `42.5` bruto) — um número JSON bruto retorna 500. Isso
é a serialização "ValueOnly" da AAS para `xs:double`/`xs:float`; o `GET` no
mesmo endpoint devolve a mesma forma entre aspas.

Um ponto InfluxDB por asset por rodada (todas as variáveis daquele
asset como campos separados do mesmo ponto, marcado com a tag `asset` = o
mesmo id usado em `Query` do submodelo `timeseries`, ex. `PANEL-1529520`) —
não um ponto por variável, para que a `Query` única do `timeseries` retorne
todas as variáveis daquele asset juntas.

Rodar com `just simulate` (ou `python src/data_gen/send_to_basyx.py`);
`--once` faz uma única rodada de escrita+leitura em vez de repetir a cada
`--interval` segundos. Ver [src/data_gen/README.md](src/data_gen/README.md)
para o fluxo completo (incluindo `just simulate-profiles`, opcional, pra
gerar perfis de perturbação antes de rodar).

## 10. Histórico de sensores (InfluxDB + history-api)

BaSyx em si (`aas-environment`) só guarda o valor **atual** de cada
`Property` — não existe histórico ali, independente do backend. Persistência
real de série temporal é uma camada separada:

- **InfluxDB** (`infra/docker-compose.yml`, serviço `influxdb`, volume
  nomeado — sobrevive a `docker compose down`, ao contrário do resto da
  stack BaSyx que é só em memória) é onde `data_gen/send_to_basyx.py` (ou,
  no futuro, um serviço real de sensores) grava cada rodada.
- **[history_api.py](src/asset_forge/history_api.py)** é um serviço intermediário
  (containerizado via `infra/history-api/Dockerfile`, deliberadamente sem as
  dependências pesadas do resto do pacote — só `fastapi`/`uvicorn`/
  `influxdb-client`) que fica na frente do InfluxDB: `GET
  /series/{asset_id}?count=N` devolve as séries já em JSON, sem quem chama
  precisar conhecer Flux nem saber que o backend é InfluxDB especificamente.
  `count` significa "as últimas N leituras que existem, não importa a
  idade" — a implementação usa `range(start: 0)` (todo o histórico) antes de
  aplicar `tail(n: N)`, porque o `range()` do Flux filtra *antes* do `tail`
  rodar: um `range` padrão de 1h teria devolvido menos de N pontos (ou
  nenhum) sempre que a última escrita fosse mais antiga que a janela, mesmo
  havendo N pontos reais mais atrás no tempo.
- O submodelo `timeseries` de cada asset (seção 6) só guarda o `id` desse
  asset em `Segments.LinkedSegment.Query` e a URL base do history-api em
  `.Endpoint` — nunca uma query Flux, nunca o InfluxDB diretamente. Isso
  significa que o backend de armazenamento pode mudar sem tocar em nada já
  enviado ao BaSyx.

Ver [INTEGRATION.md](INTEGRATION.md) para exemplos de chamada.

## 11. Visualizador web

**[src/visualization/](src/visualization/)** é um app FastAPI + Three.js separado
(não faz parte do pacote `asset-forge` instalável — roda direto via
`python -m uvicorn src.visualization.main:app`, ver `just viz-up`), que
consome tudo que as seções acima produzem, sem nenhum dado mockado do lado
do visualizador:

- **3D**: carrega o `plant.glb` da seção 8 (`GET /api/models` localiza o
  arquivo por projeto em `assets/<projeto>/output/glb/plant.glb`) via
  Three.js/`GLTFLoader`. Clicar em uma malha ou selecionar um nó na árvore
  BaSyx (à esquerda) desliza suavemente a câmera até centralizar o
  componente (`viewer3d.js::focusCameraOnMesh`/`_startCameraTransition`,
  interpolação com easing cúbico, não um corte instantâneo).
- **Árvore de submodelos** (painel direito, aba "Metadados AAS"): ao
  selecionar um componente, `GET /api/basyx/metadata/{globalId}`
  (`basyx_service.py::get_submodel_tree_for_element`) devolve **todos** os
  submodelos daquela shell — não uma lista fixa de 3 nomes conhecidos —,
  cada um como uma árvore genérica de seus elementos (reconstrói a
  hierarquia real de `SubmodelElementCollection`/`List`, não achata tudo em
  pares chave-valor). O idShort de cada submodelo é recuperado do próprio
  esquema de id que este pipeline usa (`.../sm/{idShort}`, ver seção 6), não
  adivinhado por substring.
- **Telemetria** (aba "Séries Temporais"): `GET /api/telemetry/{globalId}`
  segue o submodelo `timeseries` do elemento selecionado até seu
  `LinkedSegment` (`Endpoint`/`Query`) e chama o history-api real (seção 10)
  — não gera valores aleatórios. Se o elemento não tiver submodelo
  `timeseries` (todo elemento fora de painéis/inversor, ver seção 6) ou o
  history-api não responder, devolve métricas vazias, não um erro.
- **Alertas de IA** (aba "Alertas IA"): um CRUD em memória
  (`ACTIVE_ALERTS` em `main.py`) para registrar/consultar alertas por
  elemento, populado pelo modelo de detecção de anomalias (seção 12) quando
  ele está rodando (`just run-ai`) via `POST`/`DELETE /api/alerts`.

## 12. `src/model/`

Modelo de detecção de anomalias por Z-Score espacial sobre os dados
históricos do history-api, gerando os alertas que o visualizador exibe
(seção 11) — nunca conecta no InfluxDB diretamente, ao contrário de uma
versão anterior deste módulo:

- **[collector.py](src/model/collector.py)** — `fetch_latest_readings(targets, ...)`
  busca a leitura mais recente de cada painel em
  `{Endpoint}/series/{Query}?count=1` — o mesmo history-api que a seção 10
  descreve — pulando o inversor virtual (detecção de anomalia é só a nível
  de painel). `targets` vem de
  `asset_forge.integration.timeseries.resolve_timeseries_targets`, que
  resolve o submodelo `timeseries` de toda shell no BaSyx (`GET /shells`
  paginado + `Segments.LinkedSegment.Endpoint`/`.Query` de cada uma) — mas
  **só uma vez**, em `cli.py`, antes do loop de avaliação, não a cada
  rodada: essa config é estado estático do BaSyx enquanto o `model run`
  está de pé, então reenumerar as ~10 mil shells da planta a cada rodada
  seria puro overhead. `Query` já é o próprio `asset_tag` (`PANEL-1529520`)
  e o `GlobalId` IFC vem direto do `id` da shell (`.../aas/ifc/{GlobalId}`),
  sem precisar ler `infra/databridge/aasserver.json` nem assumir host/porta
  do InfluxDB.
- **[detector.py](src/model/detector.py)** — `AnomalyDetector.evaluate_batch`
  calcula o Z-Score espacial (`(x - média) / desvio`) de temperatura e
  corrente DC de cada painel contra seus pares no campo naquela rodada, e
  delega a classificação a `rules.py::evaluate_panel`.
- **[rules.py](src/model/rules.py)** — `AnomalyThresholds` (limiares
  configuráveis via `config/rules.json`, com hot-reload automático se o
  arquivo mudar em disco enquanto `model run` está de pé) e
  `evaluate_panel`, que classifica cada painel em `Noite` (baixa
  luminosidade), `Sobrecorrente`/`Sobreaquecimento` (Z-Score ou limite
  absoluto excedido) ou `Sujeira` (corrente anormalmente abaixo da média do
  campo com luz normal), nessa ordem de prioridade.
- **[notifier.py](src/model/notifier.py)** — `AlertNotifier.sync_alerts`
  reconcilia o estado com o visualizador: `POST /api/alerts` para cada
  alerta ativo, `DELETE /api/alerts/{id}` para painéis que voltaram ao
  normal desde a rodada anterior.
- **[cli.py](src/model/cli.py)** — loop de avaliação (`asset-forge model
  run` / `just run-ai`); `--once` faz uma única rodada.

## O que fica fora do escopo atual

- **Servidor/cliente OPC UA real**: nenhum código de servidor ou cliente OPC
  UA existe neste repositório. `data_gen/send_to_basyx.py` (seção 9) é um
  driver de teste que escreve direto na API do BaSyx para validar o
  pipeline; um servidor OPC UA real (mockado por outra equipe, ou um sensor
  de verdade) é o que a config do DataBridge (seção 7) está pronta para
  receber, mas não é implementado aqui.
- **Reclassificação semântica**: elementos genéricos permanecem genéricos;
  nenhuma tabela de regras infere um tipo IFC mais específico a partir de
  psets/nome.
- **Reconstrução de conexões por geometria**: DEXPI só existe quando o IFC de
  origem já carrega relações de conectividade nativas.
- **Configuração do `data_gen` pela visualização**: `src/visualization/` e
  `src/data_gen/` são processos independentes, sem nenhum endpoint que ligue
  um ao outro — parâmetros de simulação (`--mode`, `--seed`,
  `--irradiance-noise-std`, etc., seção 9) só são configuráveis via CLI
  (`just simulate-profiles`/`just simulate`), não pela SPA.
