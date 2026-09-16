const ALERT_POLL_INTERVAL_MS = 5000;

export class AlertManager {
    constructor(viewer3d, onAlertClickedCallback, getSelectedElementId) {
        this.viewer3d = viewer3d;
        this.onAlertClicked = onAlertClickedCallback;
        this.getSelectedElementId = getSelectedElementId;
        this.alertsList = document.getElementById('active-alerts-list');
        this.alertBadge = document.getElementById('alert-count-badge');

        this.activeAlertsMap = new Map();
        this.paintedAlerts = new Map();
        this.paintedModelVersion = null;
        this.lastListSignature = null;

        // Expor a função global para os botões HTML de simulação
        window.triggerSimulatedFault = (faultType) => this.triggerFault(faultType);
        window.clearSimulatedFault = () => this.clearFault();

        this.fetchAlerts();
        setInterval(() => this.fetchAlerts(), ALERT_POLL_INTERVAL_MS);
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

    async triggerFault(faultType) {
        const elementId = this.getSelectedElementId?.();

        if (!elementId) {
            window.alert("Selecione um painel antes de aplicar uma falha.");
            return;
        }

        const payload = {
            element_id: elementId,
            fault_type: faultType
        };

        try {
            const res = await fetch('/api/faults', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (!res.ok) {
                throw new Error(`Falha na requisição: HTTP ${res.status}`);
            }

            window.alert(
                `Falha "${faultType}" ativada no elemento ${elementId}.`
            );
        } catch (exc) {
            console.error("Erro ao ativar falha simulada:", exc);
            window.alert("Não foi possível ativar a falha.");
        }
    }


    async clearFault() {
        const elementId = this.getSelectedElementId?.();

        if (!elementId) {
            window.alert("Selecione um painel antes de remover a falha.");
            return;
        }

        try {
            const encodedElementId = encodeURIComponent(elementId);

            const res = await fetch(`/api/faults/${encodedElementId}`, {
                method: 'DELETE'
            });

            if (res.status === 404) {
                window.alert("O painel selecionado não possui uma falha ativa.");
                return;
            }

            if (!res.ok) {
                throw new Error(`Falha na requisição: HTTP ${res.status}`);
            }

            window.alert(
                `Operação normal restaurada no elemento ${elementId}.`
            );
        } catch (exc) {
            console.error("Erro ao remover falha simulada:", exc);
            window.alert("Não foi possível remover a falha.");
        }
    }
}
