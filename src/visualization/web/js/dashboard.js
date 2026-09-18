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
        const currentHeaderId = this.telemetryHeader.getAttribute('data-global-id');
        
        if (currentHeaderId !== telemetryData.globalId) {
            this.telemetryHeader.setAttribute('data-global-id', telemetryData.globalId);
            this.telemetryHeader.innerHTML = `
                <div class="element-title">${isSolar ? '☀️ Módulo Fotovoltaico' : '⚡ Inversor Solar'}</div>
                <div class="element-subtitle">ID: <code>${telemetryData.globalId}</code></div>
            `;
            this.telemetryCharts.innerHTML = '';
        }

        const metrics = telemetryData.metrics || {};
        const titleMap = {
            luminosity: 'Intensidade Luminosa (W/m²)',
            temperature: 'Temperatura (°C)',
            currentDC: 'Corrente CC (A)',
            voltageDC: 'Tensão CC (V)',
            voltageAC: 'Tensão CA (V)',
            currentAC: 'Corrente CA (A)',
            powerAC: 'Potência CA (kW)'
        };

        for (const [metricKey, values] of Object.entries(metrics)) {
            if (!values || values.length === 0) continue;
            const currentVal = values[values.length - 1];
            const prevVal = values.length > 1 ? values[values.length - 2] : currentVal;

            let trendSymbol = '→';
            let trendClass = 'trend-flat';
            if (currentVal > prevVal) {
                trendSymbol = '↑';
                trendClass = 'trend-up';
            } else if (currentVal < prevVal) {
                trendSymbol = '↓';
                trendClass = 'trend-down';
            }

            let valColor = 'var(--accent-cyan)';
            if (metricKey === 'temperature' && currentVal >= 47.0) {
                valColor = 'var(--accent-red)';
            } else if (metricKey === 'currentDC' && currentVal <= 13.0) {
                valColor = 'var(--accent-yellow)';
            } else if (metricKey === 'currentDC' && currentVal >= 18.0) {
                valColor = 'var(--accent-orange)';
            }

            let card = document.getElementById(`card-metric-${metricKey}`);
            let valElem = document.getElementById(`val-metric-${metricKey}`);
            let canvasElem = document.getElementById(`canvas-${metricKey}`);

            const formattedHtml = `${currentVal} <span class="trend-badge ${trendClass}">${trendSymbol}</span>`;

            if (!card || !canvasElem) {
                card = document.createElement('div');
                card.className = 'chart-card';
                card.id = `card-metric-${metricKey}`;

                const label = titleMap[metricKey] || metricKey;
                card.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <span style="font-weight:600; font-size:12px;">${label}</span>
                        <span id="val-metric-${metricKey}" style="color:${valColor}; font-weight:700; font-size:13px;">${formattedHtml}</span>
                    </div>
                    <canvas class="chart-canvas" id="canvas-${metricKey}"></canvas>
                `;
                this.telemetryCharts.appendChild(card);
                canvasElem = card.querySelector('canvas');
            } else if (valElem) {
                valElem.style.color = valColor;
                valElem.innerHTML = formattedHtml;
            }

            if (canvasElem) {
                this._drawSparkline(canvasElem, values);
            }
        }
    }

    _drawSparkline(canvas, rawData) {
        const ctx = canvas.getContext('2d');
        const width = canvas.clientWidth || 280;
        const height = canvas.clientHeight || 120;
        canvas.width = width;
        canvas.height = height;

        // Janela deslizante dos últimos 25 pontos
        const data = rawData.slice(-25);
        if (data.length < 2) return;

        const lastVal = data[data.length - 1];

        // Calcular min e max considerando toda a janela visível para evitar achatamento
        const dataMin = Math.min(...data);
        const dataMax = Math.max(...data);
        let dataRange = dataMax - dataMin;

        // Margem adaptativa inteligente para destacar micro-flutuações com dinamismo
        if (dataRange < 0.5) {
            dataRange = 1.0;
        }

        const padding = dataRange * 0.2;
        const min = dataMin - padding;
        const max = dataMax + padding;
        let range = max - min;
        if (range <= 0) range = 1.0;

        ctx.clearRect(0, 0, width, height);

        // Identificar se há transição brusca na janela
        const threshold = Math.max(Math.abs(lastVal) * 0.4, 5.0);
        let transitionIndex = -1;
        for (let i = 1; i < data.length; i++) {
            if (Math.abs(data[i] - data[i - 1]) > threshold) {
                transitionIndex = i;
            }
        }

        // Desenhar indicador vertical de transição de modo
        if (transitionIndex > 0) {
            const transX = (transitionIndex / (data.length - 1)) * (width - 10) + 5;
            ctx.save();
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = 'rgba(255, 214, 0, 0.6)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(transX, 4);
            ctx.lineTo(transX, height - 4);
            ctx.stroke();
            ctx.restore();

            ctx.fillStyle = 'rgba(255, 214, 0, 0.85)';
            ctx.font = '9px sans-serif';
            ctx.fillText('⚡ Transição', Math.min(transX + 3, width - 60), 12);
        }

        // Mapear pontos para a tela com proporção completa
        const points = data.map((val, index) => {
            const x = (index / (data.length - 1)) * (width - 10) + 5;
            const normY = (val - min) / range;
            const clampedNormY = Math.max(0, Math.min(1, normY));
            const y = height - 10 - clampedNormY * (height - 20);
            return { x, y, val };
        });

        // Desenhar curva principal
        ctx.beginPath();
        ctx.strokeStyle = '#00e5ff';
        ctx.lineWidth = 2.5;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        points.forEach((pt, index) => {
            if (index === 0) ctx.moveTo(pt.x, pt.y);
            else ctx.lineTo(pt.x, pt.y);
        });
        ctx.stroke();

        // Desenhar área sob a curva com gradiente
        ctx.lineTo(width - 5, height);
        ctx.lineTo(5, height);
        ctx.closePath();
        const grad = ctx.createLinearGradient(0, 0, 0, height);
        grad.addColorStop(0, 'rgba(0, 229, 255, 0.25)');
        grad.addColorStop(1, 'rgba(0, 229, 255, 0.0)');
        ctx.fillStyle = grad;
        ctx.fill();

        // Ponto cintilante ao vivo na extremidade da série temporal
        const lastPt = points[points.length - 1];
        ctx.save();
        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 6, 0, 2 * Math.PI);
        ctx.fillStyle = 'rgba(0, 229, 255, 0.4)';
        ctx.fill();

        ctx.beginPath();
        ctx.arc(lastPt.x, lastPt.y, 3, 0, 2 * Math.PI);
        ctx.fillStyle = '#ffffff';
        ctx.fill();
        ctx.restore();
    }
}
