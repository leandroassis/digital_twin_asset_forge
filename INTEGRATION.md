# Lendo e escrevendo dados no BaSyx (e no history-api) via API

Este documento mostra como usar a API REST do BaSyx (`aas-environment`, AAS
API v3) e do history-api para ler/escrever dados de sensores dos painéis
solares/inversor já carregados pelo pipeline. Todos os comandos abaixo foram
testados ao vivo contra a stack local (`just basyx-up` + `just basyx-upload
solar-plant`) e usam ids reais de `assets/solar-plant/`. Para entender o que
cada submodelo contém e por quê, ver [DESCRIPTION.md](DESCRIPTION.md).

**Importante sobre o submodelo `opcua`:** para painéis/inversor, ele carrega
tanto a *configuração de conexão* de um servidor OPC UA (endpoint, modo de
segurança) quanto um `Property` gravável por variável de sensor (ex.
`CurrentDC`, `VoltageDC`). Não existe client/server OPC UA real neste
pacote — o que existe é a config do DataBridge (ver DESCRIPTION.md, seção 7)
pronta para receber de um servidor OPC UA externo, e um driver de teste
local (`data_gen/send_to_basyx.py`, ver DESCRIPTION.md, seção 9) que
escreve/lê direto nessa mesma API para provar que o caminho todo está
unificado. Este documento cobre como fazer o mesmo manualmente.

## Fluxo de integração entre os módulos

`asset_forge`, `data_gen`, `model` e `visualization` são processos
independentes — cada um sua própria CLI ou servidor, cada um rodando
sozinho (local ou como container, ver DESCRIPTION.md, seção 13) — que só
trocam dados entre si via chamada HTTP a uma API de outro serviço. Nenhum
importa código de outro em tempo de execução para trocar dados (o único
compartilhamento é o pacote Python `asset_forge` em si, quando instalado —
isso não acopla processos, só reaproveita código entre eles). Visão geral
de quem chama quem:

**Setup (uma vez, manual, no host):**
```
asset-forge convert  →  asset-forge basyx upload  →  BaSyx
```

**Escrita de sensores (contínua, um round por intervalo):**
```
data-gen  →  PATCH BaSyx .../$value       (valor atual, lido de volta pra confirmar)
data-gen  →  InfluxDB write               (histórico, batch por rodada)
```

**Leitura + alertas (contínua, um round por intervalo):**
```
model  →  GET BaSyx /shells + /submodel-elements   (só uma vez, no startup)
model  →  GET history-api /series/{id}             (a cada rodada, concorrente)
model  →  POST/DELETE visualization /api/alerts    (a cada rodada, se algo mudou)
```

**Leitura sob demanda (a cada clique na SPA):**
```
visualization  →  GET BaSyx (shell → submodelo → Endpoint/Query)  →  GET history-api /series/{id}
```

Cada seta é uma chamada HTTP simples com um contrato pequeno e explícito
(um id plano, um valor, uma URL) — nunca uma query Flux, nunca uma
estrutura de dados Python compartilhada entre processos:

- **`asset_forge` → BaSyx**: `POST /upload` (`.aasx` inteiro) + registro de
  descriptors no registry — comando manual, um-tiro, nunca um serviço de
  longa duração (ver "O que fica fora do escopo atual" em DESCRIPTION.md).
- **`data_gen` → BaSyx**: `PATCH .../submodel-elements/{idShortPath}/$value`
  por variável, `GET` do mesmo endpoint pra confirmar — seção 2/3 abaixo,
  mesmo contrato que um DataBridge real usaria.
- **`data_gen` → InfluxDB**: escreve direto (é o único módulo, junto do
  history-api, que sabe que o backend é InfluxDB — todo o resto só conhece
  o history-api). Um ponto por asset por rodada, ver DESCRIPTION.md seção
  9/10.
- **`model` → BaSyx**: só leitura, e só **uma vez** por processo (`GET
  /shells` paginado + `GET .../submodel-elements` de cada `timeseries`,
  resolvendo `Endpoint`/`Query` de cada painel) — não repete isso a cada
  rodada de avaliação (ver DESCRIPTION.md, seção 12, para o porquê).
- **`model` → history-api**: `GET /series/{asset_id}?count=1` por painel,
  a cada rodada (concorrente, `--max-workers`) — nunca InfluxDB direto.
- **`model` → `visualization`**: `POST`/`DELETE /api/alerts` — o único
  jeito de um alerta chegar na SPA; sem `model run` ativo, a aba "Alertas
  IA" fica sempre vazia.
- **`visualization` → BaSyx + history-api**: mesmo padrão de leitura do
  `model` (shell → submodelo `timeseries` → `Endpoint`/`Query` →
  history-api), mas resolvido sob demanda por elemento selecionado na SPA,
  não pra todo o campo de uma vez.

O restante deste documento mostra, com `curl`, exatamente os mesmos
endpoints que `data_gen`/`model`/`visualization` chamam — útil pra
depurar qualquer um deles isoladamente (ex.: `model` não está gerando
alertas? confirme manualmente que `GET /series/{id}` na seção 4 abaixo
devolve dado real antes de suspeitar do código do modelo).

## Pré-requisitos

```bash
just basyx-up                  # sobe aas-environment (8081) + registry (8082) + UI (3000) + databridge (8085) + influxdb (8086) + history-api (8090)
just convert-solar              # gera assets/solar-plant/output/{ifc,aas,glb}/... e infra/databridge/*.json
just basyx-upload solar-plant   # carrega todo model-NNNN.aasx gerado no BaSyx
```

Os dados do BaSyx ficam **só em memória** (`aas-registry-log-mem`, sem
volume no `aas-environment`) — um `just basyx-down` ou restart do container
apaga shells/submodelos; rode `just basyx-upload solar-plant` de novo depois
de subir a stack. O InfluxDB, ao contrário, tem volume nomeado
(`influxdb-data`) e sobrevive a `docker compose down`.

## IDs são base64url sem padding

Toda URL da API v3 do BaSyx que referencia um AAS/Submodel/SubmodelElement
por id usa o id inteiro (uma URI, não um UUID) codificado em base64url e
**sem** os `=` de padding no final. Para codificar/decodificar:

```bash
# codificar
python3 -c "import base64,sys; print(base64.urlsafe_b64encode(sys.argv[1].encode()).decode().rstrip('='))" \
  "https://example.org/asset-forge/aas/ifc/2QF3\$F\$XHF1A\$PuubJ8dJ8/sm/opcua"

# decodificar (para conferir o que um id em uma URL realmente é)
python3 -c "import base64,sys; s=sys.argv[1]; print(base64.urlsafe_b64decode(s + '=='*((4-len(s)%4)%4)).decode())" \
  "<string-base64url-copiada-de-uma-resposta>"
```

## 1. Encontrar a Shell/Submodelo de um componente

Listar todas as shells carregadas (paginado — use `?limit=` para páginas
maiores, `paging_metadata.cursor` na resposta para continuar):

```bash
curl -s "http://localhost:8081/shells?limit=100" | python3 -m json.tool
```

Cada shell traz `idShort` (derivado do `Name`/GlobalId do elemento IFC — ver
`export/aas/shell.py`), `assetInformation.globalAssetId` e a lista de
referências aos seus submodelos. Exemplo real, um painel solar do
`solar-plant` (`GlobalId=2QF3$F$XHF1A$PuubJ8dJ8`, `Tag=1529520`, um dos 607
painéis reconhecidos por `is_solar_panel`):

```json
{
  "id": "https://example.org/asset-forge/aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8",
  "idShort": "Solar_Panel_ZCB_1000_x_1835mm_1529520",
  "submodels": [
    {"keys": [{"value": ".../aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/nameplate"}]},
    {"keys": [{"value": ".../aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/technicaldata"}]},
    {"keys": [{"value": ".../aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/opcua"}]},
    {"keys": [{"value": ".../aas/ifc/2QF3$F$XHF1A$PuubJ8dJ8/sm/timeseries"}]}
  ]
}
```

Só painéis e o inversor virtual (ver abaixo) têm `timeseries`; painéis,
inversor e sensores/medidores nativos (`IfcSensor`/`IfcFlowMeter`) têm
`opcua`. Todo o resto da planta (~9.499 elementos) tem `nameplate` +
`technicaldata` (com geometria `Model3DIFC` anexada, ver seção 5) igual a
qualquer outro elemento — só não tem `opcua`/`timeseries`, que ficam
escopados a quem tem uma leitura de sensor real por trás (ver
DESCRIPTION.md, seção 6).

**O inversor** não tem `IfcElement` de origem — sua shell usa o esquema de
id `aas/virtual/inverter` em vez de `aas/ifc/{globalId}`:

```json
{
  "id": "https://example.org/asset-forge/aas/virtual/inverter",
  "idShort": "Inverter",
  "submodels": [
    {"keys": [{"value": ".../aas/virtual/inverter/sm/nameplate"}]},
    {"keys": [{"value": ".../aas/virtual/inverter/sm/opcua"}]},
    {"keys": [{"value": ".../aas/virtual/inverter/sm/timeseries"}]}
  ]
}
```

Ou liste os submodelos de uma shell específica já conhecida:

```bash
SHELL_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/2QF3\$F\$XHF1A\$PuubJ8dJ8').decode().rstrip('='))")
curl -s "http://localhost:8081/shells/$SHELL_B64/submodel-refs"
```

O registry (`8082`) também serve para descoberta — `GET /shell-descriptors`
traz a mesma informação já com as URLs prontas
(`endpoints[].protocolInformation.href`):

```bash
curl -s "http://localhost:8082/shell-descriptors?limit=10"
```

## 2. Ler o valor atual de uma variável de sensor

`GET .../submodel-elements/{idShortPath}/$value` devolve só o valor de um
elemento. Para as variáveis de um painel (`LightIntensity`, `Temperature`,
`CurrentDC`, `VoltageDC` — ver DESCRIPTION.md/`solar.py`), o `idShortPath` é
direto, um `Property` no topo do submodelo `opcua`:

```bash
SM_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/2QF3\$F\$XHF1A\$PuubJ8dJ8/sm/opcua').decode().rstrip('='))")

curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/CurrentDC/\$value"
# -> "0.0"  (valor inicial; PATCH abaixo para mudar)
```

Note a string entre aspas mesmo para um número: a serialização "ValueOnly"
da AAS representa `xs:double`/`xs:float` como string JSON, não como número
JSON bruto (ver seção 3). Para as 3 variáveis do inversor
(`VoltageAC`/`CurrentAC`/`PowerAC`), a mesma coisa no submodelo `opcua` de
`aas/virtual/inverter`.

O endpoint de conexão OPC UA configurado (igual para todo painel/inversor,
vem de `--host-opcua`/`--port-opcua`):

```bash
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/EndpointDescriptions%5B0%5D.EndpointUri/\$value"
# -> "opc.tcp://localhost:4840/freeopcua/server"
```

Ou o submodelo inteiro, útil pra descobrir os `idShort` disponíveis sem
adivinhar:

```bash
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements" | python3 -m json.tool
```

## 3. Escrever um novo valor de sensor

`PATCH` no mesmo endpoint `$value` — corpo é o valor **codificado como
string JSON** (confirmado ao vivo contra um `aas-environment` real,
2.0.0-SNAPSHOT: um número JSON bruto, ex. `42.5`, dá HTTP 500; precisa ser
`"42.5"`):

```bash
curl -X PATCH "http://localhost:8081/submodels/$SM_B64/submodel-elements/CurrentDC/\$value" \
  -H "Content-Type: application/json" \
  -d '"9.2"'
# -> HTTP 204

curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/CurrentDC/\$value"
# -> "9.2"
```

É exatamente esse par PATCH+GET que `data_gen/send_to_basyx.py` roda em loop
para cada painel — ver `just simulate --once` para rodar uma vez manualmente
contra todos os alvos de uma vez, driven por `infra/databridge/aasserver.json`
(o mesmo arquivo que o DataBridge real usaria). Um servidor OPC UA real
faria o mesmo PATCH através do DataBridge (ver DESCRIPTION.md, seção 7), não
direto nesta API — mas o efeito em BaSyx é idêntico.

Para propriedades fora do conjunto fixo de variáveis (ex. um valor novo
dentro de `technicaldata`), `POST` cria um elemento novo:

```bash
curl -X POST "http://localhost:8081/submodels/$SM_B64/submodel-elements" \
  -H "Content-Type: application/json" \
  -d '{
        "modelType": "Property",
        "idShort": "CustomField",
        "valueType": "xs:string",
        "value": "algum valor"
      }'
# -> HTTP 201
```

Uma segunda `POST` com o mesmo `idShort` dá `409 Conflict`; apague antes com
`DELETE /submodels/{id}/submodel-elements/{idShortPath}`.

## 4. Ler o histórico de uma variável (via history-api, não direto no InfluxDB)

BaSyx só guarda o valor **atual** de cada `Property` (o `$value` acima) —
nunca um histórico. O submodelo `timeseries` de cada painel/inversor aponta,
via `Segments.LinkedSegment`, para o serviço history-api (porta `8090`), não
para o InfluxDB diretamente:

```bash
SM_TS_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/2QF3\$F\$XHF1A\$PuubJ8dJ8/sm/timeseries').decode().rstrip('='))")

curl -s "http://localhost:8081/submodels/$SM_TS_B64/submodel-elements/Segments.LinkedSegment.Endpoint/\$value"
# -> "http://localhost:8090"
curl -s "http://localhost:8081/submodels/$SM_TS_B64/submodel-elements/Segments.LinkedSegment.Query/\$value"
# -> "PANEL-1529520"
```

`Query` é sempre um id plano (`PANEL-<Tag>` para painéis, `INVERTER` para o
inversor) — nunca uma query Flux; quem lê o submodelo não precisa saber que
o backend é InfluxDB. Use esses dois valores direto no history-api:

```bash
curl -s "http://localhost:8090/series/PANEL-1529520" | python3 -m json.tool
# -> {"CurrentDC": [{"time": "...", "value": 9.2}, ...], "VoltageDC": [...], "LightIntensity": [...], "Temperature": [...]}

# só as últimas 20 leituras de cada variável, não importa a idade
curl -s "http://localhost:8090/series/PANEL-1529520?count=20" | python3 -m json.tool

# saúde do serviço
curl -s "http://localhost:8090/health"
```

Sem `count`, a janela padrão é a última hora — se `send_to_basyx.py` não
estiver rodando há mais de uma hora, a resposta pode vir vazia mesmo
havendo dados mais antigos; use `?count=N` nesse caso. Uma requisição com
`asset_id` fora do padrão `[A-Za-z0-9_-]+` (proteção contra injeção de
Flux) devolve HTTP 400.

É exatamente esse caminho (`timeseries` submodel → `Segments.LinkedSegment`
→ history-api) que `asset-forge model run` (`src/model/collector.py`) e o
visualizador (`src/visualization/basyx_vis/basyx_service.py`) seguem
programaticamente, em vez de conectar no InfluxDB direto — ver
DESCRIPTION.md, seção 12.

## 5. Baixar a geometria 3D de um componente

Todo elemento IFC-backed carrega `Model3DIFC` no seu `technicaldata` (só o
inversor virtual não, por não ter geometria de origem). O `plant.glb`
combinado (ver DESCRIPTION.md, seção 8) continua sendo a forma prática de
navegar a planta inteira de uma vez; `Model3DIFC` é para inspecionar/baixar
um componente específico via API do BaSyx.

```bash
SM_TD_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/2QF3\$F\$XHF1A\$PuubJ8dJ8/sm/technicaldata').decode().rstrip('='))")
curl -s "http://localhost:8081/submodels/$SM_TD_B64/submodel-elements/Model3DIFC/attachment" -o painel.ifc
```

## Referência rápida dos endpoints usados aqui

| Ação | Método + endpoint |
|---|---|
| Listar shells | `GET /shells` (porta 8081) |
| Submodelos de uma shell | `GET /shells/{aasId}/submodel-refs` |
| Descriptors (via registry) | `GET /shell-descriptors` (porta 8082) |
| Ler um submodelo inteiro | `GET /submodels/{smId}` |
| Ler elementos de um submodelo | `GET /submodels/{smId}/submodel-elements` |
| Ler só o valor de um elemento | `GET /submodels/{smId}/submodel-elements/{idShortPath}/$value` |
| Atualizar o valor de um elemento | `PATCH /submodels/{smId}/submodel-elements/{idShortPath}/$value` |
| Criar um elemento novo | `POST /submodels/{smId}/submodel-elements` |
| Apagar um elemento | `DELETE /submodels/{smId}/submodel-elements/{idShortPath}` |
| Baixar um anexo de arquivo | `GET /submodels/{smId}/submodel-elements/{idShortPath}/attachment` |
| Ler série histórica de um asset | `GET /series/{asset_id}` (porta 8090, history-api) |
| Ler as últimas N leituras de um asset | `GET /series/{asset_id}?count=N` (porta 8090) |
| Saúde do history-api | `GET /health` (porta 8090) |

`{aasId}`/`{smId}` são sempre o id completo (URI), codificado em base64url
sem padding, como explicado acima. `{asset_id}` do history-api é sempre um
id plano (`PANEL-<Tag>`/`INVERTER`), nunca codificado. A [documentação
Swagger/OpenAPI completa da API do BaSyx](http://localhost:8081/swagger-ui.html)
fica disponível com a stack no ar.
