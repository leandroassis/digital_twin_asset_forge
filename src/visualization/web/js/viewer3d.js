import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// GLTFLoader's own auto-generated name for a primitive mesh that has no
// glTF `Mesh.name` of its own -- "mesh_<meshIndex>", plus a "_<n>" suffix
// for every primitive beyond the first under the same Group. Never a real
// identifier; used to tell a genuinely meaningful legacy `.name` (e.g. a
// GlobalId from the IfcConvert path) apart from this noise.
const GENERATED_MESH_NAME_RE = /^mesh_\d+(_\d+)?$/;

export class Viewer3D {
    constructor(canvasId, onElementSelectedCallback) {
        this.canvas = document.getElementById(canvasId);
        this.onElementSelected = onElementSelectedCallback;

        // Materiais e Cores
        this.materials = {
            selected: new THREE.MeshStandardMaterial({
                color: 0x00e5ff,
                emissive: 0x005588,
                roughness: 0.2,
                metalness: 0.5
            }),
            alertOverheat: new THREE.MeshStandardMaterial({
                color: 0xff1744,
                emissive: 0xaa0000,
                roughness: 0.3
            }),
            alertDirt: new THREE.MeshStandardMaterial({
                color: 0xffd600,
                emissive: 0x665500,
                roughness: 0.5
            }),
            alertOvercurrent: new THREE.MeshStandardMaterial({
                color: 0xff6d00,
                emissive: 0x773300,
                roughness: 0.3
            }),
            alertNight: new THREE.MeshStandardMaterial({
                color: 0x37474f,
                emissive: 0x102027,
                roughness: 0.8
            })
        };

        this.selectedAnchor = null;
        this.originalMaterialsMap = new Map();
        this.meshByGlobalIdMap = new Map();
        this.alertStatesMap = new Map();
        this.modelVersion = 0;
        this._cameraTransition = null;

        // WebGL isn't guaranteed everywhere (sandboxed browsers, remote
        // desktops/VMs without GPU passthrough, etc. -- confirmed live:
        // THREE.WebGLRenderer throws synchronously here in exactly that
        // case). None of the rest of the app -- the BaSyx tree, metadata,
        // telemetry, alerts -- has anything to do with 3D, so a failure
        // here must not take down AppController's whole constructor with
        // it; `available` gates every other method below instead.
        this.available = false;
        try {
            this._initScene();
            this._initRaycaster();
            this.available = true;
            this._animate();
        } catch (exc) {
            console.error('Viewer3D: WebGL indisponível neste navegador -- visualização 3D desativada:', exc);
            this._showUnavailableMessage();
        }
    }

    _showUnavailableMessage() {
        if (this.canvas) this.canvas.style.display = 'none';
        const container = this.canvas?.parentElement;
        if (!container || container.querySelector('.webgl-unavailable')) return;
        const message = document.createElement('div');
        message.className = 'webgl-unavailable';
        message.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:#8b95a1;padding:2rem;text-align:center;';
        message.innerText = 'Visualização 3D indisponível (sem suporte a WebGL neste navegador) -- a árvore de ativos, metadados e alertas continuam funcionando normalmente.';
        container.appendChild(message);
    }

    _initScene() {
        this.scene = new THREE.Scene();
        this.scene.background = new THREE.Color(0x0d1117);

        this.camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 2000);
        this.camera.position.set(30, 30, 30);

        this.renderer = new THREE.WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true });
        this.renderer.setSize(this.canvas.clientWidth, this.canvas.clientHeight);
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;

        this.controls = new OrbitControls(this.camera, this.renderer.domElement);
        this.controls.enableDamping = true;
        this.controls.dampingFactor = 0.05;

        // Luzes
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        this.scene.add(ambientLight);

        const dirLight1 = new THREE.DirectionalLight(0xffffff, 1.5);
        dirLight1.position.set(100, 150, 100);
        this.scene.add(dirLight1);

        const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.8);
        dirLight2.position.set(-100, -50, -100);
        this.scene.add(dirLight2);

        // Grid de Apoio
        const grid = new THREE.GridHelper(200, 40, 0x00e5ff, 0x223344);
        grid.position.y = -0.1;
        this.scene.add(grid);

        window.addEventListener('resize', () => this._onWindowResize());
    }

    _initRaycaster() {
        this.raycaster = new THREE.Raycaster();
        this.mouse = new THREE.Vector2();
        this.tooltip = document.getElementById('hover-tooltip');

        this.canvas.addEventListener('click', (event) => this._onCanvasClick(event));
        this.canvas.addEventListener('mousemove', (event) => this._onCanvasMouseMove(event));
    }

    loadModel(glbUrl) {
        if (!this.available || !glbUrl) return;

        // Limpar cena anterior
        if (this.currentModel) {
            this.scene.remove(this.currentModel);
            this.meshByGlobalIdMap.clear();
            this.originalMaterialsMap.clear();
        }

        const loader = new GLTFLoader();
        loader.load(
            glbUrl,
            (gltf) => {
                this.currentModel = gltf.scene;
                this.scene.add(this.currentModel);
                this.selectedAnchor = null;
                this.alertStatesMap.clear();
                this._indexElements();
                this.modelVersion++;

                // Centralizar a câmera automaticamente no modelo
                this.resetCamera();
            },
            (xhr) => {
                // Progresso
            },
            (error) => {
                console.error("Erro ao carregar o modelo GLB:", error);
            }
        );
    }

    // Indexa cada elemento pelo seu GlobalId real. asset-forge's own
    // plant.glb (export/glb.py) grupa as faces de um elemento por estilo de
    // superfície IFC -- um elemento com mais de um material vira mais de
    // uma glTF Primitive dentro do mesmo Mesh, e o GLTFLoader então envolve
    // essas primitivas num THREE.Group. Só o Group carrega os `extras`
    // (GlobalId) do node original; suas malhas-filhas individuais não
    // carregam nada, só um nome auto-gerado tipo "mesh_259" -- confirmado
    // ao vivo (painéis solares, que têm vidro+moldura como dois materiais
    // distintos, eram exatamente os que falhavam ao clicar). Por isso este
    // índice varre TODO objeto (não só isMesh): o primeiro nível que carrega
    // um GlobalId de verdade -- seja o Group inteiro ou um Mesh solitário --
    // é o "âncora" certo daquele elemento, e a varredura não desce further
    // dentro dele (evita indexar as malhas-filhas sob nomes-lixo).
    _indexElements() {
        this.currentModel.traverse((obj) => {
            const id = obj.userData.globalId || obj.userData.GlobalId || obj.userData.guid;
            if (id) {
                this.meshByGlobalIdMap.set(id, obj);
            } else if (obj.isMesh && obj.name && !GENERATED_MESH_NAME_RE.test(obj.name)) {
                // Fallback para GLBs do pipeline legado (IfcConvert), que
                // nomeia cada malha diretamente pelo GlobalId, sem extras.
                if (!this.meshByGlobalIdMap.has(obj.name)) {
                    this.meshByGlobalIdMap.set(obj.name, obj);
                }
            }

            // Guarda o material original de toda malha real (inclusive as
            // "mesh_259" filhas de um Group multi-material), não só das que
            // viraram âncora -- selectElement/setAlertState aplicam material
            // em cada descendente via _applyMaterial, então cada um precisa
            // do seu próprio material original para restaurar depois.
            if (obj.isMesh && !this.originalMaterialsMap.has(obj.uuid)) {
                this.originalMaterialsMap.set(obj.uuid, obj.material);
            }
        });
    }

    _onCanvasClick(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.scene.children, true);

        if (intersects.length > 0) {
            const hitMesh = intersects.find(i => i.object.isMesh)?.object;
            if (hitMesh) {
                const globalId = this._resolveGlobalId(hitMesh);
                this.selectElement(globalId, true);
            }
        }
    }

    // Walks up from `object` (a raycast hit is always an individual
    // primitive Mesh, possibly one of a multi-material Group's anonymous
    // children -- see _indexElements) to the nearest ancestor that actually
    // carries this element's identity, then reads its GlobalId/name off of
    // that ancestor. Stops at the model root so it never wanders into an
    // unrelated sibling element.
    _resolveAnchor(object) {
        let node = object;
        while (node && node !== this.currentModel) {
            const id = node.userData?.globalId || node.userData?.GlobalId || node.userData?.guid;
            if (id) return node;
            if (node.name && !GENERATED_MESH_NAME_RE.test(node.name)) return node;
            node = node.parent;
        }
        return object;
    }

    _resolveGlobalId(object) {
        const anchor = this._resolveAnchor(object);
        const id = anchor.userData?.globalId || anchor.userData?.GlobalId || anchor.userData?.guid;
        if (id) return id;
        if (anchor.name && !GENERATED_MESH_NAME_RE.test(anchor.name)) return anchor.name;
        if (anchor.userData?.name) return anchor.userData.name;
        return anchor.name;
    }

    _onCanvasMouseMove(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.scene.children, true);

        if (intersects.length > 0 && intersects[0].object.isMesh) {
            const anchor = this._resolveAnchor(intersects[0].object);
            const name = anchor.userData?.name || this._resolveGlobalId(anchor) || 'Elemento 3D';
            this.tooltip.innerText = name;
            this.tooltip.style.left = `${event.clientX + 12}px`;
            this.tooltip.style.top = `${event.clientY + 12}px`;
            this.tooltip.style.display = 'block';
        } else {
            this.tooltip.style.display = 'none';
        }
    }

    // Aplica `material` em toda malha real descendente de `anchor` (um
    // Group multi-material tem várias; um Mesh solitário só a si mesmo --
    // traverse() sempre visita o próprio objeto primeiro).
    _applyMaterial(anchor, material) {
        anchor.traverse((obj) => {
            if (obj.isMesh) obj.material = material;
        });
    }

    _restoreMaterial(anchor) {
        const alertType = this.alertStatesMap.get(this._resolveGlobalId(anchor));
        if (alertType) {
            this._applyMaterial(anchor, this._alertMaterial(alertType));
            return;
        }
        anchor.traverse((obj) => {
            if (obj.isMesh) {
                obj.material = this.originalMaterialsMap.get(obj.uuid) || obj.material;
            }
        });
    }

    selectElement(globalId, notifyCallback = false) {
        if (!globalId) return;

        // Sem WebGL não há malha pra destacar/focar, mas quem chamou (a
        // árvore, os alertas) ainda precisa do callback de metadados/
        // telemetria abaixo -- só a parte 3D fica de fora.
        if (this.available) {
            if (this.selectedAnchor) {
                this._restoreMaterial(this.selectedAnchor);
            }

            const targetAnchor = this._lookupMesh(globalId);
            if (targetAnchor) {
                this.selectedAnchor = targetAnchor;
                this._applyMaterial(targetAnchor, this.materials.selected);
                this.focusCameraOnMesh(targetAnchor);
            }
        }

        if (notifyCallback && this.onElementSelected) {
            this.onElementSelected(globalId);
        }
    }

    _lookupMesh(globalId) {
        if (!globalId) return null;
        if (this.meshByGlobalIdMap.has(globalId)) {
            return this.meshByGlobalIdMap.get(globalId);
        }

        const cleanId = globalId.split('/').pop();
        if (this.meshByGlobalIdMap.has(cleanId)) {
            return this.meshByGlobalIdMap.get(cleanId);
        }

        try {
            const decoded = decodeURIComponent(cleanId);
            if (this.meshByGlobalIdMap.has(decoded)) {
                return this.meshByGlobalIdMap.get(decoded);
            }
        } catch (e) {}

        for (const [key, obj] of this.meshByGlobalIdMap.entries()) {
            if (key === cleanId || key.endsWith(cleanId) || (obj.userData && (obj.userData.name === cleanId || obj.userData.idShort === cleanId))) {
                return obj;
            }
        }
        return null;
    }

    // Retorna true se o elemento foi encontrado na cena e pintado -- false
    setAlertState(globalId, alertType) {
        if (!this.available) return false;

        // Tratar alerta global de operação noturna da planta
        if (globalId === "SOLAR_PLANT_FIELD" || alertType === "Noite") {
            for (const [key, anchor] of this.meshByGlobalIdMap.entries()) {
                const nameLower = (key + (anchor.userData?.name || "") + (anchor.name || "")).toLowerCase();
                if (nameLower.includes("solar") || nameLower.includes("panel") || nameLower.includes("pv") || nameLower.includes("modul")) {
                    this.alertStatesMap.set(this._resolveGlobalId(anchor), 'Noite');
                    if (anchor !== this.selectedAnchor) {
                        this._applyMaterial(anchor, this.materials.alertNight);
                    }
                }
            }
            return true;
        }

        const anchor = this._lookupMesh(globalId);
        if (!anchor) return false;

        this.alertStatesMap.set(this._resolveGlobalId(anchor), alertType);
        // O elemento selecionado mantém o destaque de seleção; o alerta volta
        // a aparecer via _restoreMaterial quando a seleção mudar.
        if (anchor !== this.selectedAnchor) {
            this._applyMaterial(anchor, this._alertMaterial(alertType));
        }
        return true;
    }

    _alertMaterial(alertType) {
        if (alertType === 'Sujeira') return this.materials.alertDirt;
        if (alertType === 'Sobrecorrente') return this.materials.alertOvercurrent;
        if (alertType === 'Noite') return this.materials.alertNight;
        return this.materials.alertOverheat;
    }

    clearAlertState(globalId) {
        if (!this.available) return;

        if (globalId === "SOLAR_PLANT_FIELD") {
            for (const [key, anchor] of this.meshByGlobalIdMap.entries()) {
                const resolvedId = this._resolveGlobalId(anchor);
                if (this.alertStatesMap.get(resolvedId) === 'Noite') {
                    this.alertStatesMap.delete(resolvedId);
                    if (anchor !== this.selectedAnchor) {
                        this._restoreMaterial(anchor);
                    }
                }
            }
            return;
        }

        const anchor = this._lookupMesh(globalId);
        if (!anchor) return;

        this.alertStatesMap.delete(this._resolveGlobalId(anchor));
        if (anchor !== this.selectedAnchor) {
            this._restoreMaterial(anchor);
        }
    }

    focusCameraOnMesh(mesh) {
        const box = new THREE.Box3().setFromObject(mesh);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z) || 1;

        const targetPos = new THREE.Vector3()
            .copy(center)
            .add(new THREE.Vector3(maxDim * 2.5, maxDim * 2.5, maxDim * 2.5));

        this._startCameraTransition(targetPos, center);
    }

    _startCameraTransition(targetPosition, targetLookAt, duration = 900) {
        this._cameraTransition = {
            startPos: this.camera.position.clone(),
            endPos: targetPosition.clone(),
            startTarget: this.controls.target.clone(),
            endTarget: targetLookAt.clone(),
            startTime: performance.now(),
            duration
        };
    }

    _updateCameraTransition() {
        const t = this._cameraTransition;
        if (!t) return;

        const progress = Math.min((performance.now() - t.startTime) / t.duration, 1);
        const eased = this._easeInOutCubic(progress);

        this.camera.position.lerpVectors(t.startPos, t.endPos, eased);
        this.controls.target.lerpVectors(t.startTarget, t.endTarget, eased);

        if (progress >= 1) {
            this._cameraTransition = null;
        }
    }

    _easeInOutCubic(t) {
        return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    }

    resetCamera() {
        if (!this.available || !this.currentModel) return;
        const box = new THREE.Box3().setFromObject(this.currentModel);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(size.x, size.y, size.z);

        this.controls.target.copy(center);
        this.camera.position.set(center.x + maxDim * 1.5, center.y + maxDim * 1.5, center.z + maxDim * 1.5);
        this.controls.update();
    }

    _onWindowResize() {
        const width = this.canvas.clientWidth;
        const height = this.canvas.clientHeight;
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height, false);
    }

    _animate() {
        requestAnimationFrame(() => this._animate());
        this._updateCameraTransition();
        this.controls.update();
        this.renderer.render(this.scene, this.camera);
    }
}
