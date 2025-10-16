  // Global variables
let currentFolder = 'all';
let allRecords = [];
let allFolders = [];

// Initialize when page loads
document.addEventListener('DOMContentLoaded', function() {
    loadFoldersAndRecords();
    setupEventListeners();
});

function setupEventListeners() {
    // Search functionality
    document.getElementById('search').addEventListener('input', filterRecords);

    // Mobile sidebar handling
    if (window.innerWidth <= 768) {
        closeSidebar();
    }
}

// Load all data from backend
async function loadFoldersAndRecords() {
    try {
        const response = await fetch('/api/dashboard-data');
        const data = await response.json();

        if (data.success) {
            allRecords = data.records;
            allFolders = data.folders;

            renderFolders();
            renderRecords();
            updateCounts();
        } else {
            console.error('Failed to load data:', data.error);
        }
    } catch (error) {
        console.error('Error loading data:', error);
    }
}

function createDefaultFolders() {
    allFolders = [
        {
            id: 1,
            name: 'Work Projects',
            parent_id: null,
            record_count: 0,
            created_at: new Date().toISOString().split('T')[0],
            updated_at: new Date().toISOString().split('T')[0]
        },
        {
            id: 2,
            name: 'Personal Records',
            parent_id: null,
            record_count: 0,
            created_at: new Date().toISOString().split('T')[0],
            updated_at: new Date().toISOString().split('T')[0]
        },
        {
            id: 3,
            name: 'Archive',
            parent_id: null,
            record_count: 0,
            created_at: new Date().toISOString().split('T')[0],
            updated_at: new Date().toISOString().split('T')[0]
        },
        {
            id: 4,
            name: 'Important Documents',
            parent_id: null,
            record_count: 0,
            created_at: new Date().toISOString().split('T')[0],
            updated_at: new Date().toISOString().split('T')[0]
        }
    ];
}

// Render folder tree in sidebar
function renderFolders() {
    const folderList = document.getElementById('folder-list');
    folderList.innerHTML = '';

    // Build folder tree structure
    const folderTree = buildFolderTree(allFolders);

    // Render tree
    renderFolderTree(folderTree, folderList, 0);
}

// Build hierarchical folder structure
function buildFolderTree(folders) {
    const folderMap = {};
    const rootFolders = [];

    // First pass: create folder objects
    folders.forEach(folder => {
        folderMap[folder.id] = {
            ...folder,
            children: []
        };
    });

    // Second pass: build hierarchy
    folders.forEach(folder => {
        if (folder.parent_id) {
            const parent = folderMap[folder.parent_id];
            if (parent) {
                parent.children.push(folderMap[folder.id]);
            } else {
                // Parent doesn't exist, treat as root
                rootFolders.push(folderMap[folder.id]);
            }
        } else {
            rootFolders.push(folderMap[folder.id]);
        }
    });

    return rootFolders;
}

// Render folder tree recursively
function renderFolderTree(folders, container, depth = 0) {
    folders.forEach(folder => {
        const folderElement = createFolderElement(folder, depth);
        container.appendChild(folderElement);

        // Render children if they exist
        if (folder.children && folder.children.length > 0) {
            const childContainer = document.createElement('div');
            childContainer.style.marginLeft = '15px';
            childContainer.id = `children-${folder.id}`;

            renderFolderTree(folder.children, childContainer, depth + 1);
            container.appendChild(childContainer);
        }
    });
}

// Create individual folder element
function createFolderElement(folder, depth) {
    const div = document.createElement('div');
    div.className = 'folder-item';
    div.setAttribute('data-folder', folder.id);
    div.style.paddingLeft = `${1 + (depth * 0.5)}rem`;

    const hasChildren = folder.children && folder.children.length > 0;
    const expandIcon = hasChildren ?
        `<span class="expand-icon me-1" onclick="toggleFolderExpand(${folder.id})" style="cursor: pointer;">▶</span>` :
        '<span class="me-2"></span>';

    div.innerHTML = `
        <div class="d-flex align-items-center flex-grow-1" onclick="selectFolder('${folder.id}', this.parentElement)">
            ${expandIcon}
            <span>📁 ${folder.name}</span>
        </div>
        <div class="d-flex align-items-center">
            <span class="folder-count me-2" id="count-${folder.id}">${folder.record_count || 0}</span>
            <div class="folder-actions">
                <div class="dropdown">
                    <button class="btn btn-sm btn-link text-light p-0" data-bs-toggle="dropdown">⋮</button>
                    <ul class="dropdown-menu dropdown-menu-end">
                        <li><button class="dropdown-item" onclick="createSubfolder('${folder.id}')">➕ New Subfolder</button></li>
                        <li><button class="dropdown-item text-warning" onclick="renameFolder('${folder.id}', '${folder.name}')">✏️ Rename</button></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><button class="dropdown-item text-danger" onclick="deleteFolder('${folder.id}', '${folder.name}')">🗑 Delete</button></li>
                    </ul>
                </div>
            </div>
        </div>
    `;

    return div;
}

// Toggle folder expansion
function toggleFolderExpand(folderId) {
    const childContainer = document.getElementById(`children-${folderId}`);
    const expandIcon = document.querySelector(`[data-folder="${folderId}"] .expand-icon`);

    if (childContainer) {
        const isHidden = childContainer.style.display === 'none';
        childContainer.style.display = isHidden ? 'block' : 'none';
        expandIcon.textContent = isHidden ? '▼' : '▶';
    }
}

// Select folder and filter records
function selectFolder(folderId, element) {
    // Update active state
    document.querySelectorAll('.folder-item').forEach(item => {
        item.classList.remove('active');
    });
    element.classList.add('active');

    currentFolder = folderId;

    // Update page title
    let title = '📘 All Records';
    if (folderId === 'uncategorized') {
        title = '📄 Uncategorized Records';
    } else if (folderId !== 'all') {
        const folder = allFolders.find(f => f.id == folderId);
        if (folder) {
            title = `📁 ${folder.name}`;
        }
    }
    document.getElementById('page-title').textContent = title;

    renderRecords();
}

// Render records based on current filter
function renderRecords() {
    const recordList = document.getElementById('record-list');
    const emptyState = document.getElementById('empty-state');

    let filteredRecords = allRecords;

    // Filter by folder
    if (currentFolder === 'uncategorized') {
        filteredRecords = allRecords.filter(record => !record.folder_id);
    } else if (currentFolder !== 'all') {
        // For nested folders, include records from current folder and all subfolders
        const folderIds = getFolderAndDescendantIds(parseInt(currentFolder));
        filteredRecords = allRecords.filter(record =>
            folderIds.includes(record.folder_id)
        );
    }

    // Apply search filter
    const searchTerm = document.getElementById('search').value.toLowerCase();
    if (searchTerm) {
        filteredRecords = filteredRecords.filter(record =>
            record.title.toLowerCase().includes(searchTerm) ||
            (record.subtitle && record.subtitle.toLowerCase().includes(searchTerm))
        );
    }

    // Show/hide empty state
    if (filteredRecords.length === 0) {
        recordList.style.display = 'none';
        emptyState.style.display = 'block';
    } else {
        recordList.style.display = 'flex';
        emptyState.style.display = 'none';

        // Render record cards
        recordList.innerHTML = filteredRecords.map(record => createRecordCard(record)).join('');
    }
}

// Get folder and all descendant folder IDs
function getFolderAndDescendantIds(folderId) {
    const ids = [folderId];

    function addChildren(parentId) {
        const children = allFolders.filter(f => f.parent_id === parentId);
        children.forEach(child => {
            ids.push(child.id);
            addChildren(child.id);
        });
    }

    addChildren(folderId);
    return ids;
}

// Create record card HTML
function createRecordCard(record) {
    const folderName = record.folder_id ?
        (allFolders.find(f => f.id === record.folder_id)?.name || 'Unknown') :
        'Uncategorized';

    return `
        <div class="col-12 col-sm-6 col-lg-4 col-xl-3">
            <div class="record-card h-100" data-title="${record.title}" data-subtitle="${record.subtitle || ''}" data-folder="${record.folder_id || 'uncategorized'}">
                <div class="d-flex justify-content-between align-items-start">
                    <div>
                        <a href="/record-builder?title=${encodeURIComponent(record.title)}" class="record-title">${record.title}</a>
                        <div class="text-muted small mb-1">
                            📝 ${record.subtitle || 'No subtitle'} | 🔢 ${record.scan_count || 0} scans
                        </div>
                        <div class="text-muted small mb-2">
                            📅 Last modified: ${record.updated_at}
                        </div>
                        <div class="text-muted small">
                            📁 Folder: <span class="folder-name">${folderName}</span>
                        </div>
                    </div>
                    <div class="dropdown ms-2">
                        <button class="btn btn-sm btn-secondary dropdown-toggle" data-bs-toggle="dropdown">⋮</button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            <li>
                                <button class="dropdown-item text-warning" onclick="renameRecord('${record.title}')">✏️ Rename Title</button>
                            </li>
                            <li>
                                <button class="dropdown-item text-info" onclick="editSubtitle('${record.title}', '${record.subtitle || ''}')">📝 Edit Subtitle</button>
                            </li>
                            <li>
                                <button class="dropdown-item" onclick="moveToFolder('${record.title}')">📁 Move to Folder</button>
                            </li>
                            <li><hr class="dropdown-divider"></li>
                            <li>
                                <a href="/download-record?title=${encodeURIComponent(record.title)}&format=csv" class="dropdown-item text-success">📥 Download CSV</a>
                            </li>
                            <li>
                                <a href="/download-record?title=${encodeURIComponent(record.title)}&format=excel" class="dropdown-item text-success">📊 Download Excel</a>
                            </li>
                            <li><hr class="dropdown-divider"></li>
                            <li>
                                <form action="/delete-record" method="POST" onsubmit="return confirm('Delete ${record.title}?')">
                                    <input type="hidden" name="title" value="${record.title}">
                                    <button class="dropdown-item text-danger">🗑 Delete</button>
                                </form>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// Update folder counts
function updateCounts() {
    // Count all records
    document.getElementById('count-all').textContent = allRecords.length;

    // Count uncategorized records
    const uncategorizedCount = allRecords.filter(r => !r.folder_id).length;
    document.getElementById('count-uncategorized').textContent = uncategorizedCount;

    // Count records in each folder (including subfolders)
    allFolders.forEach(folder => {
        const folderIds = getFolderAndDescendantIds(folder.id);
        const count = allRecords.filter(r => folderIds.includes(r.folder_id)).length;
        const countElement = document.getElementById(`count-${folder.id}`);
        if (countElement) {
            countElement.textContent = count;
        }
    });
}

// Filter records based on search
function filterRecords() {
    renderRecords();
}

// Create new folder
async function createFolder(parentId = null) {
    const name = prompt('Enter folder name:');
    if (!name || !name.trim()) return;

    try {
        const response = await fetch('/api/create-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                name: name.trim(),
                parent_id: parentId
            })
        });

        const data = await response.json();
        if (data.success) {
            await loadFoldersAndRecords(); // Reload to get updated data
        } else {
            alert('Error creating folder: ' + data.error);
        }
    } catch (error) {
        alert('Error creating folder: ' + error.message);
    }
}

// Create subfolder
function createSubfolder(parentId) {
    createFolder(parentId);
}

// Rename folder
async function renameFolder(folderId, currentName) {
    const newName = prompt('Enter new folder name:', currentName);
    if (!newName || !newName.trim() || newName.trim() === currentName) return;

    try {
        const response = await fetch('/api/rename-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                id: folderId,
                name: newName.trim()
            })
        });

        const data = await response.json();
        if (data.success) {
            await loadFoldersAndRecords();
        } else {
            alert('Error renaming folder: ' + data.error);
        }
    } catch (error) {
        alert('Error renaming folder: ' + error.message);
    }
}

// Delete folder
async function deleteFolder(folderId, folderName) {
    if (!confirm(`Delete folder "${folderName}"? All records will be moved to Uncategorized.`)) return;

    try {
        const response = await fetch('/api/delete-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: folderId})
        });

        const data = await response.json();
        if (data.success) {
            await loadFoldersAndRecords();
            // If we were viewing the deleted folder, switch to all records
            if (currentFolder == folderId) {
                selectFolder('all', document.querySelector('[data-folder="all"]'));
            }
        } else {
            alert('Error deleting folder: ' + data.error);
        }
    } catch (error) {
        alert('Error deleting folder: ' + error.message);
    }
}

// Move record to folder
function moveToFolder(recordTitle) {
    document.getElementById('recordToMove').value = recordTitle;

    // Populate folder select
    const folderSelect = document.getElementById('folderSelect');
    folderSelect.innerHTML = '<option value="">📄 Uncategorized</option>';

    // Add folders with indentation for hierarchy
    function addFolderOptions(folders, depth = 0) {
        folders.forEach(folder => {
            const indent = '&nbsp;'.repeat(depth * 4);
            folderSelect.innerHTML += `<option value="${folder.id}">${indent}📁 ${folder.name}</option>`;

            if (folder.children && folder.children.length > 0) {
                addFolderOptions(folder.children, depth + 1);
            }
        });
    }

    const folderTree = buildFolderTree(allFolders);
    addFolderOptions(folderTree);

    // Show modal
    new bootstrap.Modal(document.getElementById('moveToFolderModal')).show();
}

// Confirm move to folder
async function confirmMoveToFolder() {
    const recordTitle = document.getElementById('recordToMove').value;
    const folderId = document.getElementById('folderSelect').value || null;

    try {
        const response = await fetch('/api/move-record-to-folder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                title: recordTitle,
                folder_id: folderId
            })
        });

        const data = await response.json();
        if (data.success) {
            await loadFoldersAndRecords();
            bootstrap.Modal.getInstance(document.getElementById('moveToFolderModal')).hide();
        } else {
            alert('Error moving record: ' + data.error);
        }
    } catch (error) {
        alert('Error moving record: ' + error.message);
    }
}

// Rename record (stub - you can implement this)
function renameRecord(currentTitle) {
    const newTitle = prompt('Enter new title:', currentTitle);
    if (!newTitle || !newTitle.trim() || newTitle.trim() === currentTitle) return;

    fetch('/rename-record', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            old_title: currentTitle,
            new_title: newTitle.trim()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`Record renamed to "${newTitle}"!`);
            // Optional: update the UI immediately without reload
            const recordCard = document.querySelector(`[data-record-title="${currentTitle}"]`);
            if (recordCard) {
                const titleElement = recordCard.querySelector('.record-title');
                if (titleElement) titleElement.textContent = newTitle;
                recordCard.dataset.recordTitle = newTitle; // update data attribute
            } else {
                location.reload(); // fallback if record not found in DOM
            }
        } else {
            alert('Error renaming record: ' + (data.error || data.message));
        }
    })
    .catch(error => {
        console.error('Error renaming record:', error);
        alert('Request failed. Please try again.');
    });
}


// Edit subtitle (stub - you can implement this)
function editSubtitle(recordTitle, currentSubtitle) {
    const newSubtitle = prompt('Enter new subtitle:', currentSubtitle);
    if (newSubtitle === null) return; // User cancelled
    if (newSubtitle.trim() === currentSubtitle.trim()) return; // No change made

    fetch('/update-subtitle', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            title: recordTitle,
            subtitle: newSubtitle.trim()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Subtitle updated!');
            // Optional: update the subtitle directly on the page without reload
            const subtitleElement = document.querySelector(`[data-record-title="${recordTitle}"] .record-subtitle`);
            if (subtitleElement) {
                subtitleElement.textContent = newSubtitle;
            } else {
                location.reload(); // fallback if no element found
            }
        } else {
            alert('Error updating subtitle: ' + (data.error || data.message));
        }
    })
    .catch(error => {
        console.error('Error updating subtitle:', error);
        alert('Request failed. Please try again.');
    });
}


// Mobile sidebar functions
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    sidebar.classList.toggle('show');
    overlay.classList.toggle('show');
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    sidebar.classList.remove('show');
    overlay.classList.remove('show');
}