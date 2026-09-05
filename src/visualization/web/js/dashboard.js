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

        const submodels = metadata.submodels || [];
        this.metadataContent.innerHTML = '';

        if (submodels.length === 0) {
            this.metadataContent.innerHTML = `<div class="empty-state">Sem submodelos adicionais</div>`;
            return;
        }

        // Every submodel attached to this element's shell, reconstructed as
        // a tree straight from BaSyx -- nothing hardcoded/dropped, so any
        // submodel (nameplate, technicaldata, opcua, timeseries, or a
        // future one) shows up automatically.
        for (const submodel of submodels) {
            const group = document.createElement('div');
            group.className = 'metadata-group';

            const title = document.createElement('h4');
            title.textContent = `${this._submodelIcon(submodel.idShort)} ${submodel.idShort}`;
            group.appendChild(title);

            (submodel.children || []).forEach(node => group.appendChild(this._renderTreeNode(node)));

            this.metadataContent.appendChild(group);
        }
    }

    _submodelIcon(idShort) {
        const icons = { nameplate: '🏷️', technicaldata: '⚙️', opcua: '📡', timeseries: '📈' };
        return icons[(idShort || '').toLowerCase()] || '📄';
    }

    _renderTreeNode(node) {
        const el = document.createElement('div');
        el.className = 'tree-node';
        const hasChildren = Array.isArray(node.children) && node.children.length > 0;

        if (hasChildren) {
            const label = document.createElement('div');
            label.className = 'tree-node-label';
            label.innerHTML = `<span>📁</span> <span>${node.idShort}</span>`;

            const childrenDiv = document.createElement('div');
            childrenDiv.className = 'tree-children';
            node.children.forEach(child => childrenDiv.appendChild(this._renderTreeNode(child)));

            label.addEventListener('click', () => {
                childrenDiv.style.display = childrenDiv.style.display === 'none' ? 'block' : 'none';
            });

            el.appendChild(label);
            el.appendChild(childrenDiv);
        } else {
            const row = document.createElement('div');
            row.className = 'meta-row';
            const valueText = (node.value === null || node.value === undefined) ? '—' : String(node.value);
            row.innerHTML = `<span class="meta-key">${node.idShort}</span><span class="meta-val">${valueText}</span>`;
            el.appendChild(row);
        }

        return el;
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
