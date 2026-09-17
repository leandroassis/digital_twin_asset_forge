import { Viewer3D } from './viewer3d.js?v=3';
import { BaSyxTreeComponent } from './tree.js?v=3';
import { DashboardComponent } from './dashboard.js?v=3';
import { AlertManager } from './alerts.js?v=3';

class AppController {
    constructor() {
        this.selectedGlobalId = null;

        // 1. Inicializar Visualizador 3D (WebGL Canvas)
        this.viewer3d = new Viewer3D('webgl-canvas', (globalId) => this.handleElementSelected(globalId));

        // 2. Inicializar Árvore BaSyx
        this.tree = new BaSyxTreeComponent('tree-container', 'asset-count', 'tree-search', (globalId) => {
            this.viewer3d.selectElement(globalId, false);
            this.handleElementSelected(globalId);
        });

        // 3. Inicializar Dashboard & Alertas
        this.dashboard = new DashboardComponent();
        this.alertManager = new AlertManager(this.viewer3d, (globalId) => {
            this.tree.selectNode(globalId);
            this.viewer3d.selectElement(globalId, false);
            this.handleElementSelected(globalId);
        });

        this._initTopbarEvents();
        this.loadProjects();
        this.loadBaSyxTree();

        // Polling de 3 segundos para atualização suave em tempo real sem sobrecarga
        setInterval(() => {
            if (this.selectedGlobalId) {
                const telemetryTab = document.getElementById('tab-telemetry');
                if (telemetryTab && telemetryTab.classList.contains('active')) {
                    this.refreshSelectedTelemetry();
                }
            }
        }, 3000);
    }

    _initTopbarEvents() {
        const modelSelect = document.getElementById('model-select');
        if (modelSelect) {
            modelSelect.addEventListener('change', (e) => {
                const selectedGlbUrl = e.target.value;
                if (selectedGlbUrl) {
                    this.viewer3d.loadModel(selectedGlbUrl);
                }
            });
        }

        const btnResetCam = document.getElementById('btn-reset-camera');
        if (btnResetCam) {
            btnResetCam.addEventListener('click', () => this.viewer3d.resetCamera());
        }

        const btnToggleAlerts = document.getElementById('btn-toggle-alerts');
        if (btnToggleAlerts) {
            btnToggleAlerts.addEventListener('click', () => {
                const tabAlertsBtn = document.querySelector('[data-tab="tab-alerts"]');
                if (tabAlertsBtn) tabAlertsBtn.click();
            });
        }
    }

    async loadProjects() {
        const modelSelect = document.getElementById('model-select');
        try {
            const res = await fetch('/api/models');
            if (res.ok) {
                const data = await res.json();
                const projects = data.projects || [];
                
                if (modelSelect) {
                    modelSelect.innerHTML = '';
                    if (projects.length === 0) {
                        modelSelect.innerHTML = '<option value="">Nenhum modelo GLB pré-convertido</option>';
                        return;
                    }

                    projects.forEach(p => {
                        const option = document.createElement('option');
                        option.value = p.glbUrl || '';
                        option.innerText = `${p.name} ${p.hasGlb ? '(GLB ✓)' : '(Sem GLB)'}`;
                        modelSelect.appendChild(option);
                    });

                    // Carregar primeiro modelo disponível
                    const firstGlb = projects.find(p => p.hasGlb);
                    if (firstGlb) {
                        modelSelect.value = firstGlb.glbUrl;
                        this.viewer3d.loadModel(firstGlb.glbUrl);
                    }
                }
            }
        } catch (exc) {
            console.error("Erro ao listar projetos:", exc);
        }
    }

    async loadBaSyxTree() {
        const statusBadge = document.getElementById('basyx-status');
        try {
            const res = await fetch('/api/tree');
            if (res.ok) {
                const data = await res.json();
                
                if (statusBadge) {
                    if (data.basyxOnline) {
                        statusBadge.className = 'status-badge online';
                        statusBadge.querySelector('.status-text').innerText = 'BaSyx Online';
                    } else {
                        statusBadge.className = 'status-badge offline';
                        statusBadge.querySelector('.status-text').innerText = 'BaSyx Offline';
                    }
                }

                this.tree.renderTree(data.tree);
            }
        } catch (exc) {
            console.error("Erro ao carregar árvore BaSyx:", exc);
        }
    }

    async handleElementSelected(globalId) {
        if (!globalId) return;
        this.selectedGlobalId = globalId;

        // Sincronizar seleção na Árvore
        this.tree.selectNode(globalId);

        // 1. Carregar Metadados AAS do BaSyx
        try {
            const resMeta = await fetch(`/api/basyx/metadata/${globalId}`);
            if (resMeta.ok) {
                const metadata = await resMeta.json();
                this.dashboard.renderMetadata(globalId, metadata);
            }
        } catch (exc) {
            console.warn("Erro ao buscar metadados BaSyx:", exc);
        }

        // 2. Carregar Séries Temporais / Telemetria
        await this.refreshSelectedTelemetry();
    }

    async refreshSelectedTelemetry() {
        if (!this.selectedGlobalId) return;
        try {
            const resTelem = await fetch(`/api/telemetry/${this.selectedGlobalId}`);
            if (resTelem.ok) {
                const telemetry = await resTelem.json();
                this.dashboard.renderTelemetry(telemetry);
            }
        } catch (exc) {
            console.warn("Erro ao buscar telemetria:", exc);
        }
    }
}

// Inicializar a aplicação quando o DOM estiver pronto
document.addEventListener('DOMContentLoaded', () => {
    window.app = new AppController();
});
