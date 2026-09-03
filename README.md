# asset-forge

Pipeline modular para transformar modelos IFC heterogêneos (múltiplos
projetos, cada um com seus próprios metadados, possivelmente vários `.ifc`
combinados) num único IFC de planta decorado, com exportação opcional para
DEXPI e para um pacote AAS (Asset Administration Shell), upload desse
pacote para um deployment Eclipse BaSyx (`infra/docker-compose.yml`, subido
localmente via `just basyx-up`), e uma UI web para inspecionar as instâncias
enviadas.

Cada subpasta de `assets/` é tratada como um projeto independente.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Ou, com [`just`](https://github.com/casey/just): `just setup`.

## Uso

```bash
# Converte um projeto: gera plant.ifc, e opcionalmente DEXPI e um pacote AAS
asset-forge convert assets/HVAC
asset-forge convert assets/digihub_building --namespace example.org/asset-forge

# Sobe o(s) .aasx gerado(s) para um BaSyx local (projetos grandes saem em
# vários model-NNNN.aasx -- ver nota sobre batching abaixo)
asset-forge basyx upload --aasx-path assets/HVAC/output/aas/model.aasx
asset-forge basyx clear
```

**Agrupamento por disciplina no `plant.ifc`:** quando um projeto combina
múltiplos `.ifc` (caso `digihub_building` — Arquitetura/Aquecimento/
Ventilação/Sanitário), todo elemento é atribuído a um `IfcGroup` (um por
arquivo de origem, além do pset `Pset_SourceProvenance` já existente). A
maioria dos viewers IFC expõe grupos como uma árvore separada da estrutura
espacial, então dá pra isolar/ocultar uma disciplina inteira (só aquecimento,
só ventilação, ...) mesmo com tudo federado num `plant.ifc` único. Ver
`_group_by_discipline` em `src/asset_forge/ingestion/federation.py`.

Ver `asset-forge convert --help` para as opções de namespace, hosts/portas do
ambiente AAS e do datasheet OPC UA (apenas configuração de conexão — sem
captura de telemetria, ver `src/asset_forge/config.py`).

### Atalhos via `just`

```bash
just setup                  # cria o venv e instala o pacote
just convert-hvac           # asset-forge convert assets/HVAC
just convert-digihub        # asset-forge convert assets/digihub_building (mais lento: DEXPI+AAS ~3-4min)
just convert-all            # converte todo projeto em assets/*
just convert HVAC --no-aas  # `just convert <projeto> <args extras do CLI>`

just basyx-up                                   # sobe aas-environment + registry + UI web (Docker)
just basyx-upload HVAC                          # sobe o BaSyx (se preciso), envia todo .aasx em assets/HVAC/output/aas/ e registra no registry
just basyx-clear                                # limpa shells/submodelos e seus descriptors no registry
just basyx-down                                 # para e remove todos os containers (dados são in-memory)

just test        # suíte completa
just test-unit    # só unitários (rápidos)
just clean         # remove assets/*/output
```

### BaSyx local + UI

`just basyx-up` sobe, via `infra/docker-compose.yml` (imagens oficiais
Eclipse BaSyx `2.0.0-SNAPSHOT`/`latest`), a stack completa:

| Serviço | URL |
|---|---|
| AAS Environment (repositório de shells/submodelos) | http://localhost:8081 |
| AAS Registry (descriptors) | http://localhost:8082 |
| AAS Web UI | **http://localhost:3000** |

O registry é **obrigatório**, não opt-in: `asset-forge basyx upload`/`clear`
(e as receitas `just basyx-upload`/`basyx-clear`) sempre registram/limpam os
shell descriptors no registry, por padrão, sem flags extras — os defaults de
`--host-registry`/`--port-registry` já apontam para o registry local. Isso
não é só uma questão de descoberta: o próprio AAS Web UI lê
`AAS_REGISTRY_PATH` ao carregar e quebra com `TypeError: Failed to fetch`
se não houver um registry respondendo naquele endereço — por isso
`docker-compose.yml` sobe o registry sempre junto do `aas-environment`, sem
profile.

Depois de `just basyx-upload <projeto>`, abra http://localhost:3000 no
navegador para navegar pelas shells enviadas e inspecionar os submodelos de
cada componente: Nameplate, TechnicalData (todos os psets do elemento +
`Model3DIFC`, um anexo com a geometria 3D isolada daquele componente,
extraída do `plant.ifc`) e, para sensores/medidores, o datasheet OPC UA.
`just basyx-upload`/`basyx-clear` já sobem o BaSyx sozinhos se ele ainda não
estiver rodando.

**Geometria 3D no BaSyx:** cada shell carrega, no submodelo `technicaldata`,
um `File` `Model3DIFC` com um `.ifc` mínimo — só aquele componente + o
`IfcProject` compartilhado — extraído do `plant.ifc` e empacotado como
arquivo suplementar dentro do `.aasx` (não como IFC completo da planta).
Confirmado ao vivo: `GET /submodels/{id}/submodel-elements/Model3DIFC/attachment`
retorna o STEP de volta. Ver `export/aas/geometry.py`.

### Por que vários `.aasx`?

`asset-forge convert` grava um `.aasx` por lote de até 500 elementos
(`model.aasx` se couber num lote só — sempre o caso hoje, para `HVAC` — senão
`model-0001.aasx`, `model-0002.aasx`, ...; `just basyx-upload`/`basyx upload`
sobem todos os lotes de um projeto). Isso **não é uma limitação arbitrária**:
são dois limites reais e independentes do Apache POI (usado pelo BaSyx do
lado do servidor para ler o pacote), cada um confirmado ao vivo contra um
BaSyx de verdade, e nenhum dos dois é configurável do nosso lado:

1. **Limite de bytes por parte interna do pacote.** Um único `.aasx` com os
   5096 elementos do `digihub_building` gera um `data.json` interno de
   158MB, e o Apache POI recusa alocar mais de 100.000.000 bytes para um
   único registro (`RecordFormatException: ... maximum length for this
   record type is 100,000,000`) — o upload dava 500.
2. **Limite de número de entradas no zip/pacote OPC.** A primeira tentativa
   de corrigir (1) foi dividir o `data.json` em várias partes internas
   *dentro do mesmo arquivo* `.aasx` (`/aasx/data-0001.json`,
   `/aasx/data-0002.json`, ...) — funciona bem no round-trip local
   (`basyx-python-sdk` lê múltiplas partes sem problema), mas falha contra o
   servidor real com um erro totalmente diferente: a proteção contra zip
   bomb do Apache POI (`ZipSecureFile`) rejeita qualquer pacote com mais de
   1000 entradas no total (`IOException: ... This file embeds more internal
   file entries than expected ... Limits: MAX_FILE_COUNT: 1000`). Como cada
   elemento carrega seu próprio anexo de geometria (ver abaixo), o
   `digihub_building` sozinho já teria 5096 entradas de geometria + 11
   partes JSON = 5107 entradas num arquivo só — bem acima do limite, mesmo
   com o `data.json` já fatiado.

Como os dois limites são **por pacote** (por arquivo `.aasx`, não por parte
interna), a única solução que resolve os dois ao mesmo tempo é dividir em
múltiplos **arquivos** menores, não múltiplas partes dentro de um arquivo só
— por isso `asset-forge convert` sempre gera um ou mais arquivos físicos, e
não há como forçar sempre um único arquivo para projetos grandes com esse
servidor. 500 elementos/lote mantém cada arquivo com ~501 entradas (bem
abaixo de 1000) e ~15,5MB de `data.json` (bem abaixo de 100MB), com boa
margem mesmo para elementos mais pesados que a média. Ver `DEFAULT_BATCH_SIZE`
em `src/asset_forge/export/aas/package.py`.

Outros dois bugs reais encontrados no mesmo processo, ambos já contornados:
- `spring.servlet.multipart.max-*-size` também precisou ser aumentado no
  `aas-environment` (já configurado em `infra/docker-compose.yml`) — o
  padrão do Spring Boot (~1MB) rejeitava até um único lote maior com 413.
- IFC GlobalIds são case-sensitive, mas nomes de parte OPC (o que uma
  entrada do zip dentro do `.aasx` vira ao ser relida) são comparados
  ignorando maiúsculas/minúsculas — dois elementos do `digihub_building`
  cujo GlobalId diferia só no case da última letra geravam dois arquivos de
  geometria que o Apache POI recusava como duplicados. Corrigido
  desambiguando nomes de arquivo colidentes por lote, ver `_attach_geometry`
  em `export/aas/package.py`.

## Estrutura

```
src/asset_forge/
├── pipeline/       # Stage/Record/PlantPipeline — abstrações genéricas de pipeline por elemento
├── ingestion/       # abrir + sanitizar um .ifc; federar múltiplos .ifc de um mesmo projeto
├── elements/         # leitura defensiva de psets; classificação passthrough + fallback genérico
├── linking/          # conexões nativas do IFC (sem heurística geométrica)
├── export/
│   ├── ifc_writer.py     # grava o plant.ifc final
│   ├── dexpi_builder.py  # plano de conexões -> pydexpi.DexpiModel
│   ├── dexpi_export.py   # JSON/GraphML/Proteus XML via pydexpi
│   └── aas/               # templates IDTA, submodelos, shell, pacote .aasx
├── integration/
│   └── basyx_client.py   # upload/clear no BaSyx
└── cli.py
```

## Testes

```bash
.venv/bin/pytest tests/            # unitários (rápidos) + integração (rodam contra assets/ reais, mais lentos)
.venv/bin/pytest tests/unit        # só unitários
```
