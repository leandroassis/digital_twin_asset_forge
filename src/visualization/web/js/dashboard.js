export class DashboardComponent {
    constructor() {
        this.metadataHeader = document.getElementById('metadata-header');
        this.metadataContent = document.getElementById('metadata-content');
        this.telemetryHeader = document.getElementById('telemetry-header');
        this.telemetryCharts = document.getElementById('telemetry-charts');
        
        this._initTabNavigation();
    }

    _initTabNavigation() {
        const tabBtns = document.querySelectorAll('.tab-btn');
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const targetTabId = btn.dataset.tab;
                
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                
                btn.classList.add('active');
                const targetContent = document.getElementById(targetTabId);
                if (targetContent) targetContent.classList.add('active');
            });
        });
    }

    renderMetadata(globalId, metadata) {
        if (!this.metadataHeader || !this.metadataContent) return;

        const idShort = metadata.idShort || globalId;
        this.metadataHeader.innerHTML = `
            <div class="element-title">${idShort}</div>
            <div class="element-subtitle">GlobalId: <code>${globalId}</code></div>
        `;

        if (!metadata.foundInBasyx) {
            this.metadataContent.innerHTML = `
                <div class="metadata-group">
                    <h4>Status BaSyx</h4>
                    <div class="meta-row">
                        <span class="meta-key">Status</span>
                        <span class="meta-val" style="color: var(--accent-orange);">Não encontrado no BaSyx</span>
                    </div>
                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 6px;">
                        Execute <code>just basyx-upload &lt;projeto&gt;</code> para carregar os submodelos AAS no Docker.
                    </div>
                </div>
            `;
            return;
        }

        let html = '';

        // Submodelo Nameplate
        if (metadata.nameplate && Object.keys(metadata.nameplate).length > 0) {
            html += `<div class="metadata-group">
                <h4>🏷️ Nameplate (IDTA v3.0)</h4>`;
            for (const [k, v] of Object.entries(metadata.nameplate)) {
                html += `<div class="meta-row"><span class="meta-key">${k}</span><span class="meta-val">${v}</span></div>`;
            }
            html += `</div>`;
        }

        // Submodelo TechnicalData (Psets)
        if (metadata.technicalData && Object.keys(metadata.technicalData).length > 0) {
            html += `<div class="metadata-group">
                <h4>⚙️ TechnicalData (Psets IFC)</h4>`;
            for (const [psetName, psetVal] of Object.entries(metadata.technicalData)) {
                if (typeof psetVal === 'object' && psetVal !== null) {
                    html += `<div style="font-weight:600; color:var(--accent-cyan); margin:6px 0 2px 0;">${psetName}</div>`;
                    for (const [propKey, propVal] of Object.entries(psetVal)) {
                        html += `<div class="meta-row"><span class="meta-key">${propKey}</span><span class="meta-val">${propVal}</span></div>`;
                    }
                } else {
                    html += `<div class="meta-row"><span class="meta-key">${psetName}</span><span class="meta-val">${psetVal}</span></div>`;
                }
            }
            html += `</div>`;
        }

        // Submodelo OPC UA
        if (metadata.opcua && Object.keys(metadata.opcua).length > 0) {
            html += `<div class="metadata-group">
                <h4>📡 OPC UA Server Datasheet</h4>`;
            for (const [k, v] of Object.entries(metadata.opcua)) {
                html += `<div class="meta-row"><span class="meta-key">${k}</span><span class="meta-val">${v}</span></div>`;
            }
            html += `</div>`;
        }

        this.metadataContent.innerHTML = html || `<div class="empty-state">Sem submodelos adicionais</div>`;
    }

    renderTelemetry(telemetryData) {
        if (!this.telemetryHeader || !this.telemetryCharts) return;

        const isSolar = telemetryData.type === 'SolarPanel';
        this.telemetryHeader.innerHTML = `
            <div class="element-title">${isSolar ? '☀️ Módulo Fotovoltaico' : '⚡ Inversor Solar'}</div>
            <div class="element-subtitle">ID: <code>${telemetryData.globalId}</code></div>
        `;

        this.telemetryCharts.innerHTML = '';
        const metrics = telemetryData.metrics || {};
        const timestamps = telemetryData.timestamps || [];

        for (const [metricKey, values] of Object.entries(metrics)) {
            const card = document.createElement('div');
            card.className = 'chart-card';
            
            const titleMap = {
                luminosity: 'Intensidade Luminosa (W/m²)',
                temperature: 'Temperatura (°C)',
                currentDC: 'Corrente CC (A)',
                voltageDC: 'Tensão CC (V)',
                voltageAC: 'Tensão CA (V)',
                currentAC: 'Corrente CA (A)',
                powerAC: 'Potência CA (kW)'
            };

            const label = titleMap[metricKey] || metricKey;
            const currentVal = values[values.length - 1];

            card.innerHTML = `
                <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                    <span style="font-weight:600; font-size:12px;">${label}</span>
                    <span style="color:var(--accent-cyan); font-weight:700; font-size:13px;">${currentVal}</span>
                </div>
                <canvas class="chart-canvas" id="canvas-${metricKey}"></canvas>
            `;

            this.telemetryCharts.appendChild(card);

            // Renderizar gráfico de linha simples em SVG/Canvas
            setTimeout(() => {
                const canvasElem = document.getElementById(`canvas-${metricKey}`);
                if (canvasElem) this._drawSparkline(canvasElem, values);
            }, 50);
        }
    }

    _drawSparkline(canvas, data) {
        const ctx = canvas.getContext('2d');
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        canvas.width = width;
        canvas.height = height;

        if (data.length < 2) return;

        const min = Math.min(...data);
        const max = Math.max(...data);
        const range = (max - min) || 1;

        ctx.clearRect(0, 0, width, height);

        // Desenhar linha
        ctx.beginPath();
        ctx.strokeStyle = '#00e5ff';
        ctx.lineWidth = 2;

        data.forEach((val, index) => {
            const x = (index / (data.length - 1)) * (width - 10) + 5;
            const y = height - 10 - ((val - min) / range) * (height - 20);
            if (index === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Desenhar gradiente sob a curva
        ctx.lineTo(width - 5, height);
        ctx.lineTo(5, height);
        ctx.closePath();
        const grad = ctx.createLinearGradient(0, 0, 0, height);
        grad.addColorStop(0, 'rgba(0, 229, 255, 0.3)');
        grad.addColorStop(1, 'rgba(0, 229, 255, 0.0)');
        ctx.fillStyle = grad;
        ctx.fill();
    }
}
