import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

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

        this.selectedMesh = null;
        this.originalMaterialsMap = new Map();
        this.meshByGlobalIdMap = new Map();
        this.alertStatesMap = new Map();
        this._cameraTransition = null;

        this._initScene();
        this._initRaycaster();
        this._animate();
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
        if (!glbUrl) return;

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

                // Indexar malhas por GlobalId / Name
                this.currentModel.traverse((child) => {
                    if (child.isMesh) {
                        const globalId = child.userData.GlobalId || child.userData.guid || child.name;
                        if (globalId) {
                            this.meshByGlobalIdMap.set(globalId, child);
                            this.originalMaterialsMap.set(child.uuid, child.material);
                        }
                    }
                });

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

    _onCanvasClick(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.scene.children, true);

        if (intersects.length > 0) {
            const hitMesh = intersects.find(i => i.object.isMesh)?.object;
            if (hitMesh) {
                const globalId = hitMesh.userData.GlobalId || hitMesh.userData.guid || hitMesh.name;
                this.selectElement(globalId, true);
            }
        }
    }

    _onCanvasMouseMove(event) {
        const rect = this.canvas.getBoundingClientRect();
        this.mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

        this.raycaster.setFromCamera(this.mouse, this.camera);
        const intersects = this.raycaster.intersectObjects(this.scene.children, true);

        if (intersects.length > 0 && intersects[0].object.isMesh) {
            const hit = intersects[0].object;
            const name = hit.name || hit.userData.GlobalId || 'Elemento 3D';
            this.tooltip.innerText = name;
            this.tooltip.style.left = `${event.clientX + 12}px`;
            this.tooltip.style.top = `${event.clientY + 12}px`;
            this.tooltip.style.display = 'block';
        } else {
            this.tooltip.style.display = 'none';
        }
    }

    selectElement(globalId, notifyCallback = false) {
        if (!globalId) return;

        // Restaurar material anterior se não estiver em alerta
        if (this.selectedMesh) {
            const uuid = this.selectedMesh.uuid;
            const alertType = this.alertStatesMap.get(this.selectedMesh.name);
            if (alertType && this.materials[alertType]) {
                this.selectedMesh.material = this.materials[alertType];
            } else {
                this.selectedMesh.material = this.originalMaterialsMap.get(uuid) || this.selectedMesh.material;
            }
        }

        const targetMesh = this.meshByGlobalIdMap.get(globalId);
        if (targetMesh) {
            this.selectedMesh = targetMesh;
            targetMesh.material = this.materials.selected;
            this.focusCameraOnMesh(targetMesh);
        }

        if (notifyCallback && this.onElementSelected) {
            this.onElementSelected(globalId);
        }
    }

    setAlertState(globalId, alertType) {
        const mesh = this.meshByGlobalIdMap.get(globalId);
        if (mesh) {
            this.alertStatesMap.set(globalId, alertType);
            let mat = this.materials.alertOverheat;
            if (alertType === 'Sujeira') mat = this.materials.alertDirt;
            if (alertType === 'Sobrecorrente') mat = this.materials.alertOvercurrent;
            if (alertType === 'Noite') mat = this.materials.alertNight;

            mesh.material = mat;
        }
    }

    clearAlertState(globalId) {
        this.alertStatesMap.delete(globalId);
        const mesh = this.meshByGlobalIdMap.get(globalId);
        if (mesh) {
            const origMat = this.originalMaterialsMap.get(mesh.uuid);
            if (origMat) mesh.material = origMat;
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
        if (!this.currentModel) return;
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
