export class BaSyxTreeComponent {
    constructor(containerId, countBadgeId, searchInputId, onNodeSelectedCallback) {
        this.container = document.getElementById(containerId);
        this.countBadge = document.getElementById(countBadgeId);
        this.searchInput = document.getElementById(searchInputId);
        this.onNodeSelected = onNodeSelectedCallback;
        this.activeNodeId = null;

        if (this.searchInput) {
            this.searchInput.addEventListener('input', (e) => this._filterTree(e.target.value));
        }
    }

    renderTree(treeData) {
        if (!this.container || !treeData) return;
        this.container.innerHTML = '';
        this.treeData = treeData;

        let totalAssets = 0;

        const renderNode = (node) => {
            const nodeDiv = document.createElement('div');
            nodeDiv.className = 'tree-node';
            nodeDiv.dataset.id = node.id;

            const isGroup = node.children && node.children.length > 0;
            if (!isGroup && node.type === 'AssetAdministrationShell') {
                totalAssets++;
            }

            const labelDiv = document.createElement('div');
            labelDiv.className = 'tree-node-label';
            if (this.activeNodeId === node.id) {
                labelDiv.classList.add('active');
            }

            const icon = isGroup ? '📁' : '⚡';
            labelDiv.innerHTML = `<span>${icon}</span> <span>${node.name}</span>`;

            labelDiv.addEventListener('click', (e) => {
                e.stopPropagation();

                document.querySelectorAll('.tree-node-label.active').forEach(el => el.classList.remove('active'));
                labelDiv.classList.add('active');
                this.activeNodeId = node.id;

                if (isGroup) {
                    const childrenDiv = nodeDiv.querySelector('.tree-children');
                    if (childrenDiv) {
                        childrenDiv.style.display = childrenDiv.style.display === 'none' ? 'block' : 'none';
                    }
                } else if (this.onNodeSelected) {
                    this.onNodeSelected(node.id);
                }
            });

            nodeDiv.appendChild(labelDiv);

            if (isGroup) {
                const childrenDiv = document.createElement('div');
                childrenDiv.className = 'tree-children';
                node.children.forEach(child => {
                    childrenDiv.appendChild(renderNode(child));
                });
                nodeDiv.appendChild(childrenDiv);
            }

            return nodeDiv;
        };

        this.container.appendChild(renderNode(treeData));

        if (this.countBadge) {
            this.countBadge.innerText = `${totalAssets} ativos`;
        }
    }

    selectNode(nodeId) {
        this.activeNodeId = nodeId;
        document.querySelectorAll('.tree-node-label.active').forEach(el => el.classList.remove('active'));

        const targetNodeDiv = this.container.querySelector(`.tree-node[data-id="${nodeId}"]`);
        if (targetNodeDiv) {
            const label = targetNodeDiv.querySelector('.tree-node-label');
            if (label) {
                label.classList.add('active');
                label.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }

            // Expandir pais se colapsados
            let parent = targetNodeDiv.parentElement;
            while (parent && parent !== this.container) {
                if (parent.classList.contains('tree-children')) {
                    parent.style.display = 'block';
                }
                parent = parent.parentElement;
            }
        }
    }

    _filterTree(searchTerm) {
        const term = searchTerm.toLowerCase().trim();
        const nodes = this.container.querySelectorAll('.tree-node');

        nodes.forEach(node => {
            const text = node.innerText.toLowerCase();
            if (!term || text.includes(term)) {
                node.style.display = 'block';
            } else {
                node.style.display = 'none';
            }
        });
    }
}
