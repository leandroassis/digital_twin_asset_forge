const ALERT_POLL_INTERVAL_MS = 5000;

export class AlertManager {
    constructor(viewer3d, onAlertClickedCallback) {
        this.viewer3d = viewer3d;
        this.onAlertClicked = onAlertClickedCallback;
        this.alertsList = document.getElementById('active-alerts-list');
        this.alertBadge = document.getElementById('alert-count-badge');

        this.activeAlertsMap = new Map();
        this.paintedAlerts = new Map();
        this.paintedModelVersion = null;
        this.lastListSignature = null;

        this.currentMode = 'day';
        
        // Expor as funções globais para os botões HTML de modo de operação
        window.setOperationMode = (mode) => this.setOperationMode(mode);
        window.triggerSimulatedAlert = (errorType) => this.triggerSimulation(errorType);

        this.fetchSimulationMode();
        this.fetchAlerts();
        setInterval(() => this.fetchAlerts(), ALERT_POLL_INTERVAL_MS);
    }

    async fetchSimulationMode() {
        try {
            const res = await fetch('/api/simulation/mode');
            if (res.ok) {
                const data = await res.json();
                this.updateModeUI(data.mode || 'day');
            }
        } catch (exc) {
            console.warn("Erro ao buscar modo de operação:", exc);
        }
    }

    async setOperationMode(mode) {
        if (mode !== 'day' && mode !== 'night') return;

        try {
            const res = await fetch('/api/simulation/mode', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode })
            });

            if (res.ok) {
                const data = await res.json();
                this.updateModeUI(data.mode);
                await this.fetchAlerts();

                // Recarregar telemetria do elemento selecionado na SPA
                if (window.app && typeof window.app.refreshSelectedTelemetry === 'function') {
                    window.app.refreshSelectedTelemetry();
                }
            }
        } catch (exc) {
            console.error("Erro ao alterar modo de operação:", exc);
        }
    }

    updateModeUI(mode) {
        this.currentMode = mode;
        const btnDay = document.getElementById('btn-mode-day');
        const btnNight = document.getElementById('btn-mode-night');

        if (btnDay && btnNight) {
            if (mode === 'night') {
                btnDay.classList.remove('active');
                btnNight.classList.add('active');
            } else {
                btnNight.classList.remove('active');
                btnDay.classList.add('active');
            }
        }
    }

    async fetchAlerts() {
        try {
            const res = await fetch('/api/alerts');
            if (res.ok) {
                const data = await res.json();
                this.renderAlerts(data.alerts || []);
            }
        } catch (exc) {
            console.warn("Erro ao buscar alertas:", exc);
        }
    }

    renderAlerts(alertsList) {
        this.activeAlertsMap = new Map(alertsList.map(alert => [alert.element_id, alert]));
        this._syncSceneAlerts();

        const signature = JSON.stringify(alertsList);
        if (signature === this.lastListSignature) return;
        this.lastListSignature = signature;

        if (this.alertBadge) {
            this.alertBadge.innerText = alertsList.length;
        }
        if (!this.alertsList) return;
        this.alertsList.innerHTML = '';

        if (alertsList.length === 0) {
            this.alertsList.innerHTML = `<div class="empty-state">Nenhum alerta de anomalia ativo</div>`;
            return;
        }

        alertsList.forEach(alert => {
            const card = document.createElement('div');
            card.className = `alert-card ${alert.error_type === 'Sujeira' ? 'warning' : ''}`;

            const icon = alert.error_type === 'Sobreaquecimento' ? '🔥' :
                         alert.error_type === 'Sujeira' ? '🧹' :
                         alert.error_type === 'Sobrecorrente' ? '⚡' : '🌙';

            const title = document.createElement('div');
            title.className = 'alert-card-title';
            title.textContent = `${icon} ${alert.error_type}: ${alert.element_id}`;
            const msg = document.createElement('div');
            msg.className = 'alert-card-msg';
            msg.textContent = alert.message;
            card.append(title, msg);

            card.addEventListener('click', () => {
                if (this.onAlertClicked) {
                    this.onAlertClicked(alert.element_id);
                }
            });

            this.alertsList.appendChild(card);
        });
    }

    _syncSceneAlerts() {
        if (!this.viewer3d) return;

        if (this.paintedModelVersion !== this.viewer3d.modelVersion) {
            this.paintedAlerts.clear();
            this.paintedModelVersion = this.viewer3d.modelVersion;
        }

        for (const elementId of [...this.paintedAlerts.keys()]) {
            if (!this.activeAlertsMap.has(elementId)) {
                this.viewer3d.clearAlertState(elementId);
                this.paintedAlerts.delete(elementId);
            }
        }

        for (const [elementId, alert] of this.activeAlertsMap) {
            if (this.paintedAlerts.get(elementId) === alert.error_type) continue;
            if (this.viewer3d.setAlertState(elementId, alert.error_type)) {
                this.paintedAlerts.set(elementId, alert.error_type);
            }
        }
    }

    async triggerSimulation(errorType) {
        if (errorType === 'Noite') {
            await this.setOperationMode('night');
            return;
        }

        // Obter um elemento padrão para disparar simulação manual
        const elementId = "20220221KT_PANEL_001";
        
        const payload = {
            element_id: elementId,
            error_type: errorType,
            severity: errorType === 'Sobreaquecimento' ? 'critical' : 'warning',
            message: `Alerta detectado pelo Modelo de IA: ${errorType} no elemento ${elementId}`
        };

        try {
            const res = await fetch('/api/alerts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (res.ok) {
                this.fetchAlerts();
            }
        } catch (exc) {
            console.error("Erro ao registrar alerta simulado:", exc);
        }
    }
}
