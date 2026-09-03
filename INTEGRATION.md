# Lendo e escrevendo dados no BaSyx via API

Este documento mostra como usar a API REST do BaSyx (`aas-environment`, AAS
API v3) para ler e escrever dados de sensores e outros componentes já
carregados pelo pipeline. Todos os comandos abaixo foram testados ao vivo
contra a stack local (`just basyx-up` + `just basyx-upload <projeto>`) e
usam IDs reais dos dados de exemplo em `assets/`. Para entender o que cada
submodelo contém e por quê, ver [DESCRIPTION.md](DESCRIPTION.md).

**Importante sobre o submodelo `opcua`:** ele só guarda a *configuração de
conexão* de um servidor OPC UA (endpoint, modo de segurança) — não existe
client/server OPC UA real neste pacote, e nenhum valor de sensor chega
automaticamente no BaSyx. Este documento existe justamente para cobrir essa
lacuna: como escrever/ler valores manualmente pela API enquanto uma etapa
futura de captura automática de telemetria não existe.

## Pré-requisitos

```bash
just basyx-up                    # sobe aas-environment (8081) + registry (8082) + UI (3000)
just basyx-upload digihub_building   # (ou HVAC) carrega os dados de um projeto
```

Os dados ficam **só em memória** (`aas-registry-log-mem`, sem volume no
`aas-environment`) — um `just basyx-down` ou restart do container apaga
tudo; rode `just basyx-upload <projeto>` de novo depois de subir a stack.

## IDs são base64url sem padding

Toda URL da API v3 do BaSyx que referencia um AAS/Submodel/SubmodelElement
por id usa o id inteiro (uma URI, não um UUID) codificado em base64url e
**sem** os `=` de padding no final. Para codificar/decodificar:

```bash
# codificar
python3 -c "import base64,sys; print(base64.urlsafe_b64encode(sys.argv[1].encode()).decode().rstrip('='))" \
  "https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi"

# decodificar (para conferir o que um id em uma URL realmente é)
python3 -c "import base64,sys; s=sys.argv[1]; print(base64.urlsafe_b64decode(s + '=='*((4-len(s)%4)%4)).decode())" \
  "aHR0cHM6Ly9leGFtcGxlLm9yZy9hc3NldC1mb3JnZS9hYXMvaWZjLzFTN1ZiTTVNcjl3QkNVdzJNSDc3V2k"
```

## 1. Encontrar a Shell/Submodelo de um componente

Listar todas as shells carregadas (paginado — use `?limit=` para páginas
maiores, `paging_metadata.cursor` na resposta para continuar):

```bash
curl -s "http://localhost:8081/shells?limit=100" | python3 -m json.tool
```

Cada shell traz `idShort` (derivado do `Name`/GlobalId do elemento IFC —
ver `export/aas/shell.py`), `assetInformation.globalAssetId` e a lista de
referências aos seus submodelos (`nameplate`, `technicaldata`, e `opcua` só
para elementos `IfcSensor`/`IfcFlowMeter`). Exemplo real, um sensor de
temperatura do `digihub_building`:

```json
{
  "id": "https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi",
  "idShort": "Temperaturf_hler_Temperaturf_hler_7565941",
  "submodels": [
    {"keys": [{"value": "https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/nameplate"}]},
    {"keys": [{"value": "https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/technicaldata"}]},
    {"keys": [{"value": "https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/opcua"}]}
  ]
}
```

Ou liste os submodelos de uma shell específica já conhecida, sem repetir a
busca acima:

```bash
SHELL_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi').decode().rstrip('='))")
curl -s "http://localhost:8081/shells/$SHELL_B64/submodel-refs"
```

O registry (`8082`) também serve para descoberta — `GET
/shell-descriptors` traz a mesma informação já com as URLs prontas
(`endpoints[].protocolInformation.href`) em vez de só os ids, então não
precisa recalcular o base64 manualmente:

```bash
curl -s "http://localhost:8082/shell-descriptors?limit=10"
```

## 2. Ler um valor

`GET .../submodel-elements/{idShortPath}/$value` devolve só o valor de um
elemento (sem o envelope inteiro do submodelo). `idShortPath` navega a
árvore com `.` entre níveis; um item dentro de uma `SubmodelElementList`
(como `TechnicalPropertyAreas`, que carrega um pset por item) é endereçado
por índice entre colchetes, não por nome — os itens de uma lista não têm
`idShort` próprio pela spec da AAS.

```bash
SM_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/opcua').decode().rstrip('='))")

# endpoint de conexão configurado para esse sensor (ver DESCRIPTION.md: é
# igual para todo sensor/medidor, vem de --host-opcua/--port-opcua)
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/EndpointDescriptions%5B0%5D.EndpointUri/\$value"
# -> "opc.tcp://localhost:4840/freeopcua/server"
```

Um pset inteiro (originalmente do IFC), dentro do `technicaldata`:

```bash
SM_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/technicaldata').decode().rstrip('='))")
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/TechnicalPropertyAreas%5B0%5D/\$value"
```

Ou o submodelo inteiro, com toda a estrutura (`GET
/submodels/{id}`), útil pra descobrir os `idShort`/índices disponíveis sem
adivinhar:

```bash
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements" | python3 -m json.tool
```

## 3. Escrever um valor

**Atualizar** um elemento que já existe: `PATCH` no mesmo endpoint
`$value`, corpo é só o valor (uma string JSON, número, etc — não o objeto
inteiro):

```bash
curl -X PATCH "http://localhost:8081/submodels/$SM_B64/submodel-elements/GeneralInformation.ManufacturerName/\$value" \
  -H "Content-Type: application/json" \
  -d '"Novo valor"'
# -> HTTP 204
```

**Criar** um elemento novo (nenhum dos submodelos que o pipeline gera tem um
campo dedicado a "última leitura de sensor" — isso é proposital, ver
DESCRIPTION.md): `POST` em `/submodels/{id}/submodel-elements` com o
SubmodelElement completo. Exemplo real: registrar manualmente uma leitura
para o sensor de temperatura usado nos exemplos acima, no seu submodelo
`technicaldata`:

```bash
SM_B64=$(python3 -c "import base64; print(base64.urlsafe_b64encode(b'https://example.org/asset-forge/aas/ifc/1S7VbM5Mr9wBCUw2MH77Wi/sm/technicaldata').decode().rstrip('='))")

curl -X POST "http://localhost:8081/submodels/$SM_B64/submodel-elements" \
  -H "Content-Type: application/json" \
  -d '{
        "modelType": "Property",
        "idShort": "CurrentValue",
        "valueType": "xs:double",
        "value": "21.4"
      }'
# -> HTTP 201, corpo com o elemento criado
```

Dali em diante, `CurrentValue` é só mais um elemento do submodelo — leia com
`GET .../CurrentValue/$value` e atualize com `PATCH .../CurrentValue/$value`
como no exemplo anterior. Uma segunda `POST` com o mesmo `idShort` dá `409
Conflict` (o elemento já existe); apague antes com:

```bash
curl -X DELETE "http://localhost:8081/submodels/$SM_B64/submodel-elements/CurrentValue"
```

Um script simples de telemetria (mockada ou real) rodando fora deste
pacote pode, portanto, popular valores de sensores só com `POST` (primeira
vez) + `PATCH` (atualizações seguintes) contra o `idShortPath` combinado com
a equipe — não precisa reconverter nem reenviar nenhum `.aasx`.

## 4. Baixar a geometria 3D de um componente

Todo elemento carrega, no seu `technicaldata`, um anexo `Model3DIFC` (ver
"Geometria 3D no BaSyx" no README):

```bash
curl -s "http://localhost:8081/submodels/$SM_B64/submodel-elements/Model3DIFC/attachment" -o componente.ifc
```

## Referência rápida dos endpoints usados aqui

| Ação | Método + endpoint |
|---|---|
| Listar shells | `GET /shells` |
| Submodelos de uma shell | `GET /shells/{aasId}/submodel-refs` |
| Descriptors (via registry) | `GET /shell-descriptors` (porta 8082) |
| Ler um submodelo inteiro | `GET /submodels/{smId}` |
| Ler elementos de um submodelo | `GET /submodels/{smId}/submodel-elements` |
| Ler só o valor de um elemento | `GET /submodels/{smId}/submodel-elements/{idShortPath}/$value` |
| Atualizar o valor de um elemento | `PATCH /submodels/{smId}/submodel-elements/{idShortPath}/$value` |
| Criar um elemento novo | `POST /submodels/{smId}/submodel-elements` |
| Apagar um elemento | `DELETE /submodels/{smId}/submodel-elements/{idShortPath}` |
| Baixar um anexo de arquivo | `GET /submodels/{smId}/submodel-elements/{idShortPath}/attachment` |

`{aasId}`/`{smId}` são sempre o id completo (URI), codificado em base64url
sem padding, como explicado acima. A [documentação Swagger/OpenAPI completa
da API](http://localhost:8081/swagger-ui.html) fica disponível com a stack
no ar.
