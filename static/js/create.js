let currentFile = null;
let qrData = null;

// QR code capacity limits (approximate)
const QR_LIMITS = {
    LOW: 2900,    // Low error correction
    MEDIUM: 2300, // Medium error correction
    HIGH: 1850    // High error correction
};

// Wait for DOM to load
document.addEventListener('DOMContentLoaded', function() {
    console.log('DOM loaded, checking QR library...');

    // Check if QR library is available
    if (typeof qrcode === 'undefined') {
        console.error('QR code library not loaded');
        showError('QR code library failed to load. Please refresh the page.');
    } else {
        console.log('QR library loaded successfully');
    }
});

function toggleMode() {
    const mode = document.getElementById("mode").value;
    document.getElementById("text-form").style.display = mode === "text" ? "block" : "none";
    document.getElementById("form-builder").style.display = mode === "form" ? "block" : "none";
    document.getElementById("file-upload").style.display = mode === "upload" ? "block" : "none";
    hideResults();
}

function hideResults() {
    document.getElementById("qr-result").style.display = "none";
    document.getElementById("json-preview").style.display = "none";
    document.getElementById("sizeWarning").style.display = "none";
}

function checkDataSize() {
    const data = document.getElementById('data').value;
    const length = data.length;
    document.getElementById('textLength').textContent = length;

    if (length > QR_LIMITS.HIGH) {
        showWarning(`Data is ${length} characters. QR codes work best with under ${QR_LIMITS.HIGH} characters. Consider shortening your text or using a URL shortener.`);
    } else {
        document.getElementById("sizeWarning").style.display = "none";
    }
}

function showWarning(message) {
    document.getElementById('warningText').textContent = message;
    document.getElementById('sizeWarning').style.display = 'block';
}

function validateDataSize(data, type = 'data') {
    const size = data.length;
    if (size > QR_LIMITS.LOW) {
        throw new Error(`${type} is too large (${size} characters). QR codes support maximum ~${QR_LIMITS.LOW} characters. Consider using a file hosting service and creating a QR code with the download link instead.`);
    }
    if (size > QR_LIMITS.HIGH) {
        showWarning(`Large ${type} (${size} characters) may create complex QR codes that are difficult to scan.`);
    }
    return true;
}

// File upload handlers
const fileUploadArea = document.getElementById('fileUploadArea');
const fileInput = document.getElementById('fileInput');

fileUploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    fileUploadArea.classList.add('dragover');
});

fileUploadArea.addEventListener('dragleave', () => {
    fileUploadArea.classList.remove('dragover');
});

fileUploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    fileUploadArea.classList.remove('dragover');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        handleFile(files[0]);
    }
});

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file) {
        handleFile(file);
    }
}

function handleFile(file) {
    currentFile = file;

    // Check file size early
    const maxRecommendedSize = 1024; // 1KB
    if (file.size > maxRecommendedSize) {
        showWarning(`File is ${formatFileSize(file.size)}. Files over ${formatFileSize(maxRecommendedSize)} typically create QR codes too complex to scan reliably. Consider uploading the file to a cloud service and creating a QR code with the share link instead.`);
    }

    // Show file info
    const fileInfo = document.getElementById('fileInfo');
    const fileDetails = document.getElementById('fileDetails');

    const fileSize = formatFileSize(file.size);
    const fileType = file.type || 'Unknown';
    const fileIcon = getFileIcon(file.name, file.type);

    fileDetails.innerHTML = `
        <div class="d-flex align-items-center">
            <span class="me-3" style="font-size: 1.5rem;">${fileIcon}</span>
            <div>
                <strong>${file.name}</strong><br>
                <small class="text-muted">Size: ${fileSize} | Type: ${fileType}</small>
            </div>
        </div>
    `;

    fileInfo.style.display = 'block';
    document.getElementById('generateFileQR').disabled = false;
}

function getFileIcon(fileName, fileType) {
    const extension = fileName.split('.').pop().toLowerCase();

    if (fileType.startsWith('image/')) return '🖼️';
    if (fileType.startsWith('video/')) return '🎥';
    if (fileType.startsWith('audio/')) return '🎵';
    if (fileType.includes('pdf')) return '📄';
    if (fileType.includes('word') || extension === 'doc' || extension === 'docx') return '📝';
    if (fileType.includes('sheet') || extension === 'xls' || extension === 'xlsx') return '📊';
    if (fileType.includes('presentation') || extension === 'ppt' || extension === 'pptx') return '📽️';
    if (fileType.includes('zip') || fileType.includes('rar')) return '📦';
    if (['js', 'html', 'css', 'py', 'java', 'cpp', 'c', 'php'].includes(extension)) return '💻';
    if (fileType.includes('text') || extension === 'txt') return '📃';

    return '📁';
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function clearFile() {
    currentFile = null;
    document.getElementById('fileInfo').style.display = 'none';
    document.getElementById('fileInput').value = '';
    document.getElementById('generateFileQR').disabled = true;
    hideResults();
}

async function generateFromFile() {
    if (!currentFile) return;

    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');

    progressContainer.style.display = 'block';
    progressBar.style.width = '0%';

    try {
        let qrGenerationMethod = '';
        let attemptNumber = 1;

        // Strategy 1: Try text content for text files
        if (isTextFile(currentFile)) {
            updateProgress(10, 'Reading text content...');
            try {
                const textContent = await fileToText(currentFile);
                updateProgress(30, 'Validating text size...');

                if (textContent.length <= QR_LIMITS.MEDIUM) {
                    updateProgress(50, 'Generating QR from text content...');
                    qrData = textContent;
                    await generateQRCode(qrData);
                    qrGenerationMethod = 'Direct text content';
                    updateProgress(100, 'Success!');
                    showSuccess(qrGenerationMethod, textContent.length);
                    return;
                } else {
                    console.log('Text too large, trying next method...');
                }
            } catch (error) {
                console.log('Text reading failed, trying next method...', error);
            }
        }

        // Strategy 2: Try file metadata/info for large files
        updateProgress(20, `Attempt ${++attemptNumber}: Creating file metadata...`);
        try {
            const fileInfo = {
                name: currentFile.name,
                size: currentFile.size,
                type: currentFile.type,
                lastModified: new Date(currentFile.lastModified).toISOString(),
                message: "File too large for direct QR encoding. This QR contains file metadata."
            };

            const metadataJson = JSON.stringify(fileInfo);
            if (metadataJson.length <= QR_LIMITS.MEDIUM) {
                updateProgress(60, 'Generating QR from file metadata...');
                qrData = metadataJson;
                await generateQRCode(qrData);
                qrGenerationMethod = 'File metadata (file too large for direct encoding)';
                updateProgress(100, 'Success!');
                showSuccess(qrGenerationMethod, metadataJson.length);
                return;
            }
        } catch (error) {
            console.log('Metadata method failed, trying next method...', error);
        }

        // Strategy 3: Try base64 for very small files only
        if (currentFile.size <= 500) { // Only for files under 500 bytes
            updateProgress(40, `Attempt ${++attemptNumber}: Trying base64 encoding...`);
            try {
                const base64Data = await fileToBase64(currentFile);
                const dataUrl = `data:${currentFile.type};base64,${base64Data}`;

                if (dataUrl.length <= QR_LIMITS.LOW) {
                    updateProgress(70, 'Generating QR from base64...');
                    qrData = dataUrl;
                    await generateQRCode(qrData);
                    qrGenerationMethod = 'Base64 encoded file data';
                    updateProgress(100, 'Success!');
                    showSuccess(qrGenerationMethod, dataUrl.length);
                    return;
                }
            } catch (error) {
                console.log('Base64 method failed:', error);
            }
        }

        // Strategy 4: Generate instructions for user
        updateProgress(60, `Attempt ${++attemptNumber}: Creating instructions...`);
        const instructions = {
            message: "File too large for QR code",
            fileName: currentFile.name,
            fileSize: formatFileSize(currentFile.size),
            suggestions: [
                "Upload file to cloud storage (Google Drive, Dropbox, etc.)",
                "Get shareable link",
                "Create QR code with the link instead"
            ],
            alternativeServices: ["bit.ly", "tinyurl.com", "drive.google.com"]
        };

        const instructionsText = `File: ${instructions.fileName} (${instructions.fileSize}) - Too large for QR code. Solutions: 1) Upload to cloud storage 2) Get share link 3) Create QR with link instead. Services: ${instructions.alternativeServices.join(', ')}`;

        updateProgress(80, 'Generating instructional QR...');
        qrData = instructionsText;
        await generateQRCode(qrData);
        qrGenerationMethod = 'Instructions for handling large file';
        updateProgress(100, 'Instructions generated!');
        showSuccess(qrGenerationMethod, instructionsText.length);

    } catch (error) {
        console.error('All QR generation methods failed:', error);
        updateProgress(0, 'Failed');
        showError(`All methods failed: ${error.message}`);
    } finally {
        setTimeout(() => {
            progressContainer.style.display = 'none';
        }, 2000);
    }
}

function updateProgress(percentage, message) {
    const progressBar = document.getElementById('progressBar');
    progressBar.style.width = `${percentage}%`;
    progressBar.textContent = message;
}

function showSuccess(method, dataSize) {
    document.getElementById('qrDataInfo').innerHTML = `
        <div class="alert alert-success">
            <strong>✅ Success!</strong><br>
            <strong>Method:</strong> ${method}<br>
            <strong>File:</strong> ${currentFile.name}<br>
            <strong>Original Size:</strong> ${formatFileSize(currentFile.size)}<br>
            <strong>QR Data Size:</strong> ${formatFileSize(dataSize)}<br>
            ${dataSize > QR_LIMITS.HIGH ? '<small class="text-warning">⚠️ Complex QR code - may be difficult to scan</small>' : '<small class="text-success">✅ QR code size is optimal</small>'}
        </div>
    `;
}

function showError(message) {
    document.getElementById('qrDataInfo').innerHTML = `
        <div class="alert alert-danger">
            <strong>❌ Generation Failed</strong><br>
            ${message}
        </div>
    `;
}

function isTextFile(file) {
    const textTypes = [
        'text/plain',
        'text/html',
        'text/css',
        'text/javascript',
        'application/json',
        'application/xml',
        'text/xml'
    ];

    const textExtensions = [
        'txt', 'html', 'htm', 'css', 'js', 'json', 'xml',
        'md', 'py', 'java', 'cpp', 'c', 'php', 'rb', 'go'
    ];

    if (textTypes.includes(file.type)) return true;

    const extension = file.name.split('.').pop().toLowerCase();
    return textExtensions.includes(extension);
}

function fileToText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const base64 = reader.result.split(',')[1];
            resolve(base64);
        };
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}

function generateFromText() {
    const data = document.getElementById('data').value.trim();
    if (!data) {
        alert('Please enter some text or URL');
        return;
    }

    try {
        validateDataSize(data, 'Text');
        qrData = data;
        generateQRCode(qrData);
        document.getElementById('qrDataInfo').innerHTML = `<strong>Text/URL:</strong> ${data.substring(0, 100)}${data.length > 100 ? '...' : ''}<br><small>Length: ${data.length} characters</small>`;
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

function generateFromForm() {
    const labels = document.getElementsByName('label[]');
    const values = document.getElementsByName('value[]');
    const result = {};

    for (let i = 0; i < labels.length; i++) {
        const key = labels[i].value.trim();
        const val = values[i].value.trim();
        if (key) {
            result[key] = val;
        }
    }

    const jsonData = JSON.stringify(result);

    try {
        validateDataSize(jsonData, 'Form data');
        qrData = jsonData;
        generateQRCode(qrData);

        // Show JSON preview
        document.getElementById('jsonContent').textContent = JSON.stringify(result, null, 2);
        document.getElementById('json-preview').style.display = 'block';
        document.getElementById('qrDataInfo').innerHTML = `<strong>Form Data:</strong> ${Object.keys(result).length} fields<br><small>JSON size: ${jsonData.length} characters</small>`;
    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

function generateQRCode(data) {
    return new Promise((resolve, reject) => {
        try {
            console.log('Generating QR code for data:', data.substring(0, 50) + '...');

            // Check if QR library is available
            if (typeof qrcode === 'undefined') {
                throw new Error('QR code library not loaded');
            }

            // Create QR code
            const qr = qrcode(0, 'M'); // Type 0 (auto), Error correction level M
            qr.addData(data);
            qr.make();

            // Get the container
            const container = document.getElementById('qrCanvas');

            // Clear previous content
            container.innerHTML = '';

            // Create QR code as HTML table or SVG
            const qrHTML = qr.createImgTag(4, 8); // cellSize=4, margin=8
            container.innerHTML = qrHTML;

            document.getElementById('qr-result').style.display = 'block';
            resolve();
        } catch (error) {
            console.error('Error generating QR code:', error);
            reject(new Error('Failed to generate QR code: ' + error.message));
        }
    });
}

function downloadQR() {
    try {
        const container = document.getElementById('qrCanvas');
        const img = container.querySelector('img');

        if (img) {
            const link = document.createElement('a');
            link.download = 'qr-code.png';
            link.href = img.src;
            link.click();
        } else {
            alert('No QR code image found to download');
        }
    } catch (error) {
        console.error('Download error:', error);
        alert('Failed to download QR code');
    }
}

function copyQRData() {
    if (qrData) {
        navigator.clipboard.writeText(qrData).then(() => {
            alert('QR data copied to clipboard!');
        }).catch(() => {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = qrData;
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);
            alert('QR data copied to clipboard!');
        });
    }
}

function addField() {
    const container = document.getElementById("form-fields");
    const row = document.createElement("div");
    row.className = "form-row-container row g-2 mb-2";
    row.innerHTML = `
        <div class="col-md-5">
            <input type="text" class="form-control" placeholder="Label" name="label[]" required>
        </div>
        <div class="col-md-5">
            <input type="text" class="form-control" placeholder="Value" name="value[]" required>
        </div>
        <div class="col-md-2 d-flex align-items-center">
            <button type="button" class="delete-btn" onclick="removeRow(this)">✖</button>
        </div>
    `;
    container.appendChild(row);
}

function removeRow(button) {
    button.closest('.form-row-container').remove();
}

function downloadJson() {
    const labels = document.getElementsByName('label[]');
    const values = document.getElementsByName('value[]');
    const result = {};

    for (let i = 0; i < labels.length; i++) {
        const key = labels[i].value.trim();
        const val = values[i].value.trim();
        if (key) {
            result[key] = val;
        }
    }

    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'form_data.json';
    a.click();
    URL.revokeObjectURL(url);
}

// Initialize
if (window.history.replaceState) {
    window.history.replaceState(null, null, window.location.href);
}