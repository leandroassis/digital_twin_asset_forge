export class AlertManager {
    constructor(viewer3d, onAlertClickedCallback) {
        this.viewer3d = viewer3d;
        this.onAlertClicked = onAlertClickedCallback;
        this.alertsList = document.getElementById('active-alerts-list');
        this.alertBadge = document.getElementById('alert-count-badge');
        
        this.activeAlertsMap = new Map();
        
        // Expor a função global para os botões HTML de simulação
        window.triggerSimulatedAlert = (errorType) => this.triggerSimulation(errorType);

        this.fetchAlerts();
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
        if (!this.alertsList) return;
        this.alertsList.innerHTML = '';
        this.activeAlertsMap.clear();

        if (this.alertBadge) {
            this.alertBadge.innerText = alertsList.length;
        }

        if (alertsList.length === 0) {
            this.alertsList.innerHTML = `<div class="empty-state">Nenhum alerta de anomalia ativo</div>`;
            return;
        }

        alertsList.forEach(alert => {
            this.activeAlertsMap.set(alert.element_id, alert);
            
            // Aplicar cor de alerta na cena 3D
            if (this.viewer3d) {
                this.viewer3d.setAlertState(alert.element_id, alert.error_type);
            }

            const card = document.createElement('div');
            card.className = `alert-card ${alert.error_type === 'Sujeira' ? 'warning' : ''}`;
            
            const icon = alert.error_type === 'Sobreaquecimento' ? '🔥' :
                         alert.error_type === 'Sujeira' ? '🧹' :
                         alert.error_type === 'Sobrecorrente' ? '⚡' : '🌙';

            card.innerHTML = `
                <div class="alert-card-title">${icon} ${alert.error_type}: ${alert.element_id}</div>
                <div class="alert-card-msg">${alert.message}</div>
            `;

            card.addEventListener('click', () => {
                if (this.onAlertClicked) {
                    this.onAlertClicked(alert.element_id);
                }
            });

            this.alertsList.appendChild(card);
        });
    }

    async triggerSimulation(errorType) {
        // Obter um elemento aleatório para disparar a simulação
        const elementId = "20220221KT_PANEL_001"; // ID padrão de teste
        
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
