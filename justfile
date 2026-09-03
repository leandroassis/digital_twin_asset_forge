venv := ".venv"
python := venv / "bin" / "python"
pip := venv / "bin" / "pip"
forge := venv / "bin" / "asset-forge"
pytest := venv / "bin" / "pytest"

namespace := env("ASSET_FORGE_NAMESPACE", "example.org/asset-forge")

# List available recipes
default:
    @just --list

# Create the virtualenv and install the package (+ dev deps) in editable mode
setup:
    python3 -m venv {{venv}}
    {{python}} -m pip install --upgrade pip -q
    {{pip}} install -e ".[dev]" -q

# Convert one project folder under assets/ (e.g. `just convert HVAC`, `just convert digihub_building -v`)
convert project *args:
    {{forge}} convert assets/{{project}} --namespace {{namespace}} {{args}}

# Convert every project folder under assets/ (each subfolder = one independent project)
convert-all *args:
    #!/usr/bin/env bash
    set -euo pipefail
    for dir in assets/*/; do
        project="$(basename "$dir")"
        echo "== converting $project =="
        {{forge}} convert "assets/$project" --namespace {{namespace}} {{args}}
    done

# Shortcut: convert the HVAC catalog object (single file, fast)
convert-hvac *args: (convert "HVAC" args)

# Shortcut: convert the digihub_building project (4 federated discipline files; DEXPI/AAS export take a few minutes)
convert-digihub *args: (convert "digihub_building" args)

# Start the local BaSyx stack: aas-environment + registry + web UI (registry is mandatory, not opt-in)
basyx-up:
    docker compose -f infra/docker-compose.yml up -d
    @echo "waiting for aas-environment to come up..."
    @until curl -sf http://localhost:8081/shells >/dev/null 2>&1; do sleep 1; done
    @echo "waiting for the registry to come up..."
    @until curl -sf http://localhost:8082/shell-descriptors >/dev/null 2>&1; do sleep 1; done
    @echo "waiting for the web UI to come up..."
    @until curl -sf http://localhost:3000 >/dev/null 2>&1; do sleep 1; done
    @echo "BaSyx is up: aas-environment http://localhost:8081, registry http://localhost:8082, UI http://localhost:3000"

# Stop and remove the local BaSyx stack (data is in-memory -- this discards it)
basyx-down:
    docker compose -f infra/docker-compose.yml down

# Upload every .aasx a project produced to BaSyx and register each with the registry (large projects batch into model-NNNN.aasx)
basyx-upload project host="localhost" port="8081" registry_host="localhost" registry_port="8082": basyx-up
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    files=(assets/{{project}}/output/aas/*.aasx)
    if [ ${#files[@]} -eq 0 ]; then
        echo "no .aasx found under assets/{{project}}/output/aas -- run \`just convert {{project}}\` first" >&2
        exit 1
    fi
    for f in "${files[@]}"; do
        echo "== uploading $f =="
        {{forge}} basyx upload --aasx-path "$f" \
            --host-aas-env {{host}} --port-aas-env {{port}} \
            --host-registry {{registry_host}} --port-registry {{registry_port}}
    done

# Delete every shell/submodel and their registry descriptors from a running BaSyx stack
basyx-clear host="localhost" port="8081" registry_host="localhost" registry_port="8082": basyx-up
    {{forge}} basyx clear \
        --host-aas-env {{host}} --port-aas-env {{port}} \
        --host-registry {{registry_host}} --port-registry {{registry_port}}

# Run the full test suite (unit + integration; integration runs against the real assets/ files)
test:
    {{pytest}} tests/ -q

# Run only the fast unit tests (no real IFC files touched)
test-unit:
    {{pytest}} tests/unit -q

# Run only the integration tests (slower; exercises federation/DEXPI/AAS against assets/)
test-integration:
    {{pytest}} tests/integration -q

# Remove every project's generated output/ (gitignored build artifacts)
clean:
    rm -rf assets/*/output
