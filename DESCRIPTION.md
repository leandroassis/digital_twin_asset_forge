# Como o pipeline funciona

Este documento explica a lógica implementada em [src/asset_forge/](src/asset_forge/):
o que cada etapa faz, por que ela existe, e quais arquivos são responsáveis por
cada decisão. Para instruções de uso (CLI, `just`, BaSyx local), ver
[README.md](README.md). Para ler/escrever dados de sensores via API do BaSyx,
ver [INTEGRATION.md](INTEGRATION.md).

## Visão geral

Cada subpasta de `assets/` é um **projeto independente**: um conjunto de um ou
mais `.ifc` que descrevem a mesma planta/instalação. `asset-forge convert
assets/<projeto>` roda esse projeto pelo pipeline inteiro e produz, em
`assets/<projeto>/output/`:

```
output/
├── ifc/
│   └── plant.ifc          # o IFC único e federado do projeto
├── dexpi/                 # só se o IFC de origem tiver conexões nativas
│   ├── model.json
│   ├── model.graphml
│   └── model.xml
└── aas/
    └── model.aasx          # um pacote AAS único (ver export/aas/)
```

O fluxo, em ordem (`cli.py:convert` chama cada etapa nesta sequência):

```
.ifc (1+ arquivos)
  → ingestion/loader.py    (abre + sanitiza cada arquivo)
  → ingestion/federation.py (combina múltiplos .ifc num só, se houver mais de um)
  → elements/classification.py (passthrough + fallback genérico)
  = plant.ifc
      → linking/native.py + export/dexpi_builder.py + dexpi_export.py  (condicional)
      → export/aas/*  → integration/basyx_client.py (upload, comando separado)
```

`export/ifc_writer.py:build_plant()` executa os três primeiros passos e
retorna o `ifcopenshell.file` já federado e classificado; DEXPI e AAS partem
desse mesmo modelo em memória, cada um seguindo seu próprio caminho.

## 1. Ingestão

**[ingestion/loader.py](src/asset_forge/ingestion/loader.py)** — abre um único `.ifc`. Antes de
passar para `ifcopenshell.open()`, faz uma cópia sanitizada: alguns
exportadores vendor deixam barras invertidas soltas dentro de strings STEP
(ex.: caminhos Windows), o que desalinha o tokenizer STEP e corrompe atributos
seguintes na mesma entidade. `_escape_bare_backslashes()` dobra essas barras
soltas, mas reconhece e preserva os escapes reais do Annex E da ISO-10303-21
(`\S\`, `\X\`, `\X2\...\X0\`, `\X4\...\X0\`, `\P_\`) — usados por exportadores
para caracteres não-ASCII (confirmado no `HVAC`: `\S\Vl-Brennwertkessel` é
"Öl-Brennwertkessel" corretamente escapado).

**[ingestion/federation.py](src/asset_forge/ingestion/federation.py)** — quando um projeto tem
mais de um `.ifc` (caso `digihub_building`, 4 arquivos por disciplina), escolhe
como base o arquivo com mais `IfcBuildingStorey` (a estrutura espacial mais
completa) e copia cada elemento dos demais arquivos para dentro dele:

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
- Além do pset, todo elemento (inclusive os já nativos do arquivo-base — não
  só os copiados) é atribuído a um `IfcGroup` por disciplina/arquivo de
  origem (via `IfcRelAssignsToGroup`, um grupo por `SourceFile`). Isso é o
  que permite isolar/ocultar uma disciplina inteira (só aquecimento, só
  ventilação, ...) num viewer, dentro do `plant.ifc` único federado — a
  maioria dos viewers IFC expõe grupos como uma árvore separada da estrutura
  espacial. Ver `_group_by_discipline` em `ingestion/federation.py`.
- Nenhuma conversão de unidade é feita: cada elemento carrega consigo seu
  próprio `IfcGeometricRepresentationContext`/`IfcUnitAssignment` (é seguro
  mesmo com disciplinas em metros e milímetros misturadas no mesmo arquivo
  final).

Com um único `.ifc` de entrada (caso `HVAC`), este passo é passthrough.

## 2. Classificação

**[elements/classification.py](src/asset_forge/elements/classification.py)** — **não há
reclassificação semântica**. Se o elemento de origem já é uma classe IFC
concreta e específica (`IfcValve`, `IfcWall`, ...), ele não é tocado. Só
elementos presos na classe genérica placeholder do schema
(`IfcBuildingElementProxy` — a única classe "não-abstrata" de propósito
genérico, válida em IFC2X3/IFC4/IFC4X3) passam por uma "promoção", que na
prática é um no-op: resolve o nome da classe genérica válida no schema do
arquivo carregado (nunca hardcoded) e usa `ifcopenshell.api.root.reassign_class`.
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
porta-a-porta, o sinal mais forte e mais comum em MEP bem modelado) e
`IfcRelConnectsElements` (elemento-a-elemento direto). Ambas existem desde
IFC2X3, então funcionam tanto no `HVAC` quanto no `digihub_building`.

**Não existe fallback geométrico.** Se `find_connections()` não achar nada,
retorna lista vazia — e é esse vazio que `dexpi_builder.py` usa como sinal
para pular a exportação DEXPI com um aviso claro, em vez de tentar reconstruir
topologia por proximidade/geometria (heurística que pode falhar de forma
silenciosa e foi descartada deliberadamente).

## 4. Saída IFC única

**[export/ifc_writer.py](src/asset_forge/export/ifc_writer.py)** — `build_plant()` roda os
passos 1-3 e retorna o modelo em memória; `write_plant()` grava
`plant.ifc`. Não há split por componente: como a maioria dos elementos não
muda de classe, um único arquivo por projeto é suficiente.

## 5. DEXPI (condicional)

**[export/dexpi_builder.py](src/asset_forge/export/dexpi_builder.py)** — só roda se o passo 3
encontrou pelo menos uma conexão nativa; senão levanta `DexpiUnavailableError`,
que o CLI captura e reporta como aviso, seguindo o resto do pipeline
normalmente. Quando roda:

- Escopo limitado aos elementos que participam de pelo menos uma conexão
  (DEXPI é um padrão de topologia P&ID — uma parede sem conexão não tem o que
  contribuir). Isso também é uma decisão de performance: incluir todos os
  ~5096 elementos do `digihub_building` com um dump completo de psets como
  `CustomAttributes` (~200k atributos) fazia o `GraphLoader` do `pydexpi`
  travar além de 3 minutos; limitando aos ~4100 elementos conectados e a 3
  atributos identificadores (`Tag`, `Description`, `PredefinedType`), a
  exportação cai para ~2 minutos.
- Mapeamento deliberadamente conservador: só `IfcTank` vira um equipamento
  DEXPI reconhecido (`pydexpi.dexpi_classes.equipment.Tank`); todo o resto
  vira um `CustomPipingComponent` genérico carregando a classe IFC real como
  `typeName` — nenhum subtipo de válvula/conexão é inferido sem garantia dos
  dados de origem.

**[export/dexpi_export.py](src/asset_forge/export/dexpi_export.py)** — serializa o
`DexpiModel` resultante em `model.json` (completo), `model.graphml` e
`model.xml` (Proteus — o `ProteusSerializer` de terceiros usado aqui não
escreve a topologia de tubulação, só `taggedPlantItems`/`metaData`; um aviso é
logado quando isso é relevante).

## 6. AAS (Asset Administration Shell)

Todo o código fica em `export/aas/`. Uma Shell é criada por elemento do IFC
(via `plant_model.by_type("IfcElement")`), cada uma com até 3 submodelos:

- **[templates.py](src/asset_forge/export/aas/templates.py)** — baixa (uma vez, cacheado em
  `data/submodels/`) os templates oficiais IDTA (Nameplate v3.0.1,
  TechnicalData v2.0.1, OPC UA Server Datasheet v1.0) do repositório público
  `admin-shell-io/submodel-templates`, e corrige dois problemas confirmados
  contra um BaSyx real: `Blob` com valor `null` vira `b""` (senão o XML gerado
  quebra em alguns viewers), e `kind=TEMPLATE` vira `kind=INSTANCE`.
- **[submodels.py](src/asset_forge/export/aas/submodels.py)** —
  - `build_nameplate_submodel`: só os campos que o elemento realmente tem
    (`URIOfTheProduct`, `UniqueFacilityIdentifier` = GlobalId,
    `ManufacturerProductDesignation` = Name) — nada de fabricante/número de
    série inventado.
  - `build_technicaldata_submodel`: carrega **todos** os psets do elemento
    genericamente (via `elements/properties.py`), um `SubmodelElementCollection`
    por pset, um `Property` string por propriedade. Isso substitui a
    necessidade de uma máquina de psets oficiais por classe IFC.
  - `build_opcua_submodel`: só a **configuração de conexão** (`EndpointUri`
    montado a partir de `host`/`port`/`endpoint_path`, modo de segurança
    "None") — nenhum client/server OPC UA real existe neste pacote (ver
    "Sobre o submodelo OPC UA" abaixo e [INTEGRATION.md](INTEGRATION.md)).
- **[idshort.py](src/asset_forge/export/aas/idshort.py)** — `valid_id_short`/`unique_id_shorts`:
  qualquer texto livre (Name/GlobalId de elemento, nome de pset/propriedade)
  vira um `idShort` válido pela regra AASd-002 (`[0-9a-zA-Z_-]`, começando
  obrigatoriamente por uma **letra** — a validação real do basyx é mais
  estrita que uma leitura superficial da spec sugere), com sufixos numéricos
  para colisões.
- **[shell.py](src/asset_forge/export/aas/shell.py)** — monta a `AssetAdministrationShell`,
  liga cada submodelo a ela, atribui `id`/`globalAssetId` sob o namespace
  informado (`--namespace`).
- **[geometry.py](src/asset_forge/export/aas/geometry.py)** — `extract_element_ifc()`: recorta
  um `.ifc` mínimo contendo só aquele componente (+ o `IfcProject`
  compartilhado), usado para anexar a geometria 3D individual de cada
  elemento ao seu submodelo `technicaldata` (ver "Geometria 3D" no README).
- **[package.py](src/asset_forge/export/aas/package.py)** — monta as Shells/submodelos e
  grava um ou mais `.aasx` em `output/aas/` (`model.aasx` se couber num
  arquivo só, senão `model-0001.aasx`, `model-0002.aasx`, ...). Projetos
  pequenos (`HVAC`) sempre saem como arquivo único; projetos grandes
  (`digihub_building`, 5096 elementos) são divididos porque o BaSyx (via
  Apache POI) impõe dois limites reais e independentes por *pacote* — não há
  como unificar num arquivo só a partir de um certo tamanho, ver "Por que
  vários `.aasx`?" no README. Também é aqui que a colisão de nomes de
  arquivo de geometria (GlobalIds que diferem só em maiúscula/minúscula) é
  evitada.

### Sobre o submodelo OPC UA

Só elementos cuja classe IFC é `IfcSensor` ou `IfcFlowMeter`
(`_OPCUA_ELIGIBLE_CLASSES` em `package.py`) recebem o submodelo `opcua`. Ele é
a "folha de dados" oficial IDTA de um **servidor** OPC UA (endpoint, modos de
segurança, certificados) — não tem nenhum campo de `NodeId`/tag que amarre
aquele sensor específico a uma variável daquele servidor, e todo sensor
elegível recebe o **mesmo** `host`/`port` (os passados via `--host-opcua`/
`--port-opcua` ou env, globais para a conversão inteira). Isso é proposital:
o escopo atual é só tornar a conexão configurável, sem implementar nenhum
client/server OPC UA nem captura de telemetria — ver plano original e
[INTEGRATION.md](INTEGRATION.md) para como popular valores manualmente via a
API do BaSyx enquanto isso não existe.

## 7. Upload para o BaSyx

**[integration/basyx_client.py](src/asset_forge/integration/basyx_client.py)** —
`BasyxClient.upload()` envia o `.aasx` para `POST /upload` do
`aas-environment` e, em seguida, registra cada Shell explicitamente no
registry (`POST`/`PUT` em `/shell-descriptors`) — confirmado ao vivo que o
`aas-environment` **não** registra automaticamente mesmo com as variáveis de
ambiente `REGISTRYINTEGRATION` configuradas. `clear()` apaga tudo
(`/shells`, `/submodels`, `/shell-descriptors` no registry — só esse
top-level existe nesse deployment do registry; submodel descriptors vivem
aninhados dentro de cada shell descriptor).

## 8. CLI

**[cli.py](src/asset_forge/cli.py)** — dois comandos:

```
asset-forge convert <pasta-do-projeto> [--namespace ...] [--dexpi/--no-dexpi] [--aas/--no-aas] ...
asset-forge basyx upload --aasx-path PATH [--host-registry ...]
asset-forge basyx clear [--host-registry ...]
```

Ver [README.md](README.md) para exemplos completos e os atalhos via `just`.

## O que fica fora do escopo atual

- **Captura de telemetria OPC UA real**: nenhum client/server OPC UA é
  implementado; o submodelo `opcua` só guarda configuração de conexão
  estática. Ver [INTEGRATION.md](INTEGRATION.md) para como escrever/ler
  valores manualmente via a API REST do BaSyx enquanto essa etapa futura não
  existe.
- **Reclassificação semântica**: elementos genéricos permanecem genéricos;
  nenhuma tabela de regras infere um tipo IFC mais específico a partir de
  psets/nome.
- **Reconstrução de conexões por geometria**: DEXPI só existe quando o IFC de
  origem já carrega relações de conectividade nativas.
