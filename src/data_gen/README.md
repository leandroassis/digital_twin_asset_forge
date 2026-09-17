# data_gen

Simula sensores de uma planta solar (607 painéis) com valores fisicamente
consistentes — não aleatórios — e envia esses valores pro BaSyx, reusando os
alvos e helpers de escrita/leitura de
`asset_forge.integration.sensor_targets` (parsing de `aasserver.json`,
PATCH/GET do `$value`). Módulo isolado: não é instalado junto com o pacote
`asset-forge` (não está em `pyproject.toml`), mas os dois scripts principais
(`generate_profiles_cli.py`, `send_to_basyx.py`) são expostos via
`just simulate-profiles`/`just simulate` (ver README.md da raiz) — roda
direto como script, com `src/data_gen` adicionado a `sys.path` (feito
automaticamente pelo Python ao invocar um script diretamente).

## Pré-requisitos

1. Stack BaSyx no ar, com a planta solar já carregada (ver `README.md` da
   raiz do repo):
   ```powershell
   just basyx-up
   just basyx-upload solar-plant
   ```
   Sem isso, os painéis não existem no BaSyx e não há `opcua` Property
   nenhum pra escrever.
2. Pacote `asset_forge` instalado no venv (usado por este módulo via
   `asset_forge.integration.sensor_targets`/`asset_forge.export.aas.solar`):
   ```powershell
   uv pip install -e ".[dev]" --python .venv\Scripts\python.exe
   ```

## Como gerar dados e mandar pro BaSyx (fluxo principal)

`panel_profiles.csv` é um artefato gerado (reproduzível via `--seed`), não
dado de origem — por isso **não é versionado** (ver `.gitignore`). O passo 1
abaixo é opcional: se você pular direto pro passo 2 sem gerar o arquivo,
`send_to_basyx.py` avisa e usa um perfil neutro (`irradiance_factor=1.0`,
`temperature_offset=0.0`) pra todo painel automaticamente — o passo 1 só é
necessário se você quiser perturbação/anomalia de propósito.

### 1. Gerar o perfil de cada painel (opcional)

```powershell
.venv\Scripts\python.exe src\data_gen\generate_profiles_cli.py --mode perturbed --seed 42
```

Isso lê os 607 `PANEL-*` de `infra\databridge\aasserver.json` e escreve
`src\data_gen\dataset\panel_profiles.csv` — um fator de irradiância e um
offset de temperatura por painel, reprodutíveis pelo `--seed`. **Abra esse
CSV e confira os valores antes de seguir** — é exatamente pra isso que essa
etapa é separada do envio.

- `--mode uniform` (default): todo painel usa a série base sem nenhuma
  variação (`irradiance_factor=1.0`, `temperature_offset=0.0`).
- `--mode perturbed --seed N`: cada painel recebe uma variação aleatória
  (±5% de irradiância, ±1°C de temperatura por padrão — ajustável via
  `--irradiance-noise-std`/`--temperature-noise-std`), reprodutível pelo
  seed.

Pra forçar um desvio proposital num painel específico (testar alarmes), edite
`generate_profiles_cli.py` e descomente o exemplo de `apply_anomaly(...)` no
final da função `main`, apontando pro(s) `panel_tag`(s) desejado(s).

### 2. Rodar o sender

```powershell
.venv\Scripts\python.exe src\data_gen\send_to_basyx.py
```

Sem `--once`, fica rodando indefinidamente: uma rodada por segundo simulado,
escrevendo `LightIntensity`/`Temperature`/`CurrentDC`/`VoltageDC` de cada
painel no BaSyx e historizando no InfluxDB, até o dataset acabar ou
`Ctrl+C`. Com `--once`, faz uma rodada só (bom pra testar rápido).

Opções úteis:
- `--profiles-path`: usar um CSV de perfis diferente do default
  (`dataset/panel_profiles.csv`).
- `--max-workers N`: paraleliza as requisições HTTP pro BaSyx (default `1`,
  sequencial para evitar travamento em máquinas com menor capacidade). Cada rodada é 607×4=2428 pares independentes de
  `PATCH`+`GET`; rodar um de cada vez é seguro mas lento (~65s/rodada medido
  localmente). Para computadores mais parrudos, utilize a receita `just simulate-16` (ou `--max-workers 16`), que leva a rodada a apenas ~3s a 9s.
- `--interval`: segundos reais de espera **depois** de cada rodada completar
  (default `1.0`, ignorado com `--once`) — soma com o tempo que a rodada
  levou, não é um teto. Com `--max-workers 1` e uma rodada de ~65s, o
  intervalo real entre rodadas é ~65s + `--interval`, não `--interval`
  sozinho.

### 3. Conferir que está escrevendo

```powershell
# valor atual de uma variável no BaSyx (troca a cada rodada)
curl "http://localhost:8081/submodels/<submodel-id-b64>/submodel-elements/CurrentDC/`$value"

# série historizada no InfluxDB via history-api (mais fácil de ver evoluindo)
curl "http://localhost:8090/series/PANEL-1529520?count=10"
```

Pra ver a série "andando" ao vivo em vez de rodar o curl manualmente toda
hora, em outro terminal:
```powershell
while ($true) {
    (Invoke-RestMethod "http://localhost:8090/series/PANEL-1529520?count=1").CurrentDC
    Start-Sleep -Seconds 1
}
```
Se o timestamp/valor for mudando a cada iteração, está escrevendo certo. Com
`--max-workers 1`, espere só uma atualização a cada ~1 minuto (ver acima) —
não é bug, é o tempo real de 2428 requisições sequenciais.

## Arquivos

- **[model_pv.py](model_pv.py)** — modelo de painel fotovoltaico de diodo
  único, parametrizado no nível do painel inteiro. `maximum_power_point(irradiance, ambient_temperature)`
  retorna um `PVOperatingPoint` (tensão, corrente, potência, temperatura de
  célula) resolvido por busca da seção áurea + bisseção. `PVParameters` traz
  os parâmetros nominais do painel (defaults: painel de 72 células,
  `isc_ref=17.7A`, `voc_ref=48.7V`).

- **[configs.py](configs.py)** — constantes físicas (`model_pv.py`) e de
  simulação (`INITIAL_DATETIME`, `SIMULATION_START_DATETIME`,
  `SIMULATION_STEP`), mais os caminhos do dataset (`DATA_DIR`,
  `DATASET_PATH`), todos resolvidos via `Path(__file__)` — independentes do
  diretório de execução.

- **[perturbation.py](perturbation.py)** — `generate_profiles(panel_tags,
  mode, seed, ...)` gera um perfil por painel (`irradiance_factor`,
  `temperature_offset`); `apply_anomaly(profiles, panel_tags, ...)`
  sobrescreve o perfil de painéis específicos, pra forçar um desvio
  proposital independente da perturbação aleatória geral.

- **[generate_profiles_cli.py](generate_profiles_cli.py)** — CLI que lê os
  `panel_tags` de `aasserver.json` e escreve `dataset/panel_profiles.csv`
  (ver "Como gerar dados" acima).

- **[send_to_basyx.py](send_to_basyx.py)** — o sender real. `panel_reading()`
  aplica o perfil de um painel sobre a série base e roda `model_pv`,
  retornando os 4 valores das Properties `opcua`; `run()` é o loop que avança
  o relógio simulado, escreve cada painel no BaSyx (reaproveitando
  `write_value`/`read_value` de `asset_forge.integration.sensor_targets`, em paralelo via
  `ThreadPoolExecutor` se `--max-workers` > 1) e historiza no InfluxDB. Só
  painéis — o inversor virtual (`VoltageAC`/`CurrentAC`/`PowerAC`) fica de
  fora, precisaria de um modelo de agregação DC→AC que ainda não existe.

- **[send_data_to_OPCUA.py](send_data_to_OPCUA.py)** — script mais antigo,
  só imprime no console (não escreve em lugar nenhum). Apesar do nome, não
  fala com nenhum servidor OPC UA de verdade — nenhum client/server OPC UA
  existe neste módulo. Útil como demo rápida do `model_pv` sem precisar do
  BaSyx no ar:
  ```powershell
  .venv\Scripts\python.exe src\data_gen\send_data_to_OPCUA.py
  ```

- **[dataset/](dataset/)**:
  - `a621_2026_irradiancia_temperatura.npy` — série horária real (INMET),
    shape `(5808, 2)` = `[irradiância W/m², temperatura ambiente °C]`, 5808
    amostras (242 dias a partir de 01/01/2026 00:00). Sem marcação de tempo
    própria — a correspondência com uma data vem só de `INITIAL_DATETIME`.
    Tem alguns `NaN` (1 em irradiância, 3 em temperatura) não tratados.
  - `a621_2026_irradiancia_temperatura.csv` — o mesmo array, sem
    transformação, só pra inspeção fora do Python.
  - `panel_profiles.csv` — gerado por `generate_profiles_cli.py` (não é
    dado de origem, é reproduzível a partir do seed).

## Testes

```powershell
.venv\Scripts\pytest.exe tests/unit/test_model_pv.py tests/unit/test_data_gen_configs.py tests/unit/test_send_data_to_opcua.py tests/unit/test_perturbation.py tests/unit/test_send_to_basyx.py -q
```

Como o módulo não é um pacote instalável, os testes seguem a mesma convenção
usada para `src/visualization/`: cada arquivo de teste adiciona
`src/data_gen` a `sys.path` antes de importar. Os testes de `send_to_basyx.py`
cobrem só as partes puras (`panel_reading`, `_group_by_panel`) — nada de rede
é mockado ou exercitado neles.

## Limitações conhecidas

- Não é um pacote Python (sem `__init__.py`), não está em
  `pyproject.toml`/`setuptools.packages.find` -- exposto via `just
  simulate`/`just simulate-profiles` (que invocam os scripts diretamente),
  não via `asset-forge`.
- O inversor virtual não recebe dados — só os 607 painéis.
- Sem tratamento de `NaN` no dataset base (propaga silenciosamente se um
  instante simulado cair perto de uma amostra faltante).
- `--max-workers` não tem um default "certo" — depende da máquina, da rede e
  de quanta carga concorrente a instância do BaSyx alvo aguenta.
