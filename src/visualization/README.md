# Visualizador Web de Gêmeo Digital (FastAPI + Three.js + Eclipse BaSyx)

Servidor de visualização tridimensional e barramento REST para integração com o **Eclipse BaSyx AAS (Asset Administration Shell)** no projeto `digital_twin_asset_forge`.

---

## 🏗️ Arquitetura e Estrutura de Pastas

A estrutura do módulo de visualização encontra-se em `src/visualization/`:

```text
src/visualization/
├── main.py              # Aplicação FastAPI (rotas REST, serviços estáticos e alertas)
├── config.py            # Configuração de caminhos, hosts BaSyx e segurança anti-traversal
├── pipeline/
│   └── converter.py     # Wrapper para IfcConvert (GLB) e gerador de express_map.json
├── basyx_vis/
│   ├── basyx_service.py # Cliente de integração com Eclipse BaSyx Docker (AAS & Registry)
│   └── client.py        # Cliente REST utilitário
└── web/                 # Single Page Application (SPA)
    ├── index.html       # Layout Glassmorphism Industrial
    ├── css/
    │   └── style.css    # Design System, cores tailoriadas e componentes glass
    └── js/
        ├── viewer3d.js  # Three.js WebGL (câmera, orbit controls, raycaster, destaque de malha)
        ├── tree.js      # Árvore de Ativos hierárquica do BaSyx com campo de busca
        ├── dashboard.js # Painel lateral de metadados AAS (Nameplate, TechnicalData) e sparklines
        └── alerts.js    # Gerenciador e simulador de alertas de anomalia (IA)
```

---

## 🔌 API REST (Endpoints)

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/` | Redireciona para a SPA (`/web/index.html`). |
| `GET` | `/api/models` | Lista todos os projetos em `assets/` e URLs de seus modelos `.glb`. |
| `GET` | `/api/tree` | Retorna a Árvore de Ativos hierárquica construída 100% via API do BaSyx. |
| `GET` | `/api/basyx/shells` | Retorna a lista de todas as Shells cadastradas no BaSyx. |
| `GET` | `/api/basyx/metadata/{global_id:path}` | Obtém Nameplate, TechnicalData (Psets) e OPC UA para o ativo selecionado. |
| `GET` | `/api/telemetry/{global_id:path}` | Retorna séries temporais reais (via submodelo `timeseries` -> history-api/InfluxDB) para o ativo. |
| `GET` | `/api/alerts` | Retorna a lista de alertas de anomalia ativos. |
| `POST` | `/api/alerts` | Registra/atualiza um novo alerta de anomalia. |
| `DELETE` | `/api/alerts/{element_id:path}` | Remove um alerta ativo pelo ID do elemento. |

---

## 🎯 Resolução de IDs e Mapeamento Geométrico

1. **Conversão de Malha 3D**:
   - `IfcConvert` converte os modelos IFC em malhas `.glb`.
   - O gerador `generate_express_map()` em `pipeline/converter.py` varre o arquivo IFC e mapeia todos os Express IDs de representação geométrica (`IfcShapeRepresentation`) para o `GlobalId` do seu `IfcProduct` pai, salvando em `assets/<projeto>/output/express_map.json`.
2. **Resolução no BaSyx Service**:
   - Ao clicar em uma malha 3D (`2457999-world-coords` ou `product-uuid-body`), `basyx_service.py` limpa prefixos/sufixos, resolve o Express ID via `express_map.json` para o `GlobalId` e localiza a Shell equivalente no BaSyx.
   - Suporta conversão automática de UUIDs de 36 caracteres para IFC GlobalIds de 22 caracteres base64 via `ifcopenshell.guid`.

---

## 🚀 Como Executar

```bash
# 1. Iniciar containers do BaSyx (AAS Environment, Registry e UI)
just basyx-up

# 2. Carregar pacotes AASX no BaSyx
just basyx-upload Photovoltaic_power_plant

# 3. Iniciar o servidor de visualização FastAPI/Uvicorn
just viz-up

# 4. Parar e encerrar containers do BaSyx quando necessário
just basyx-down
```
