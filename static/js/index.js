document.addEventListener('DOMContentLoaded', () => {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas-overlay');
    const ctx = canvas.getContext('2d');
    const resultElement = document.getElementById('result');
    const uniqueCountElement = document.getElementById('unique-count');
    const typeCountsElement = document.getElementById('type-counts');
    const stopBtn = document.getElementById('stop');
    const startBtn = document.getElementById('start');

    let scannerActive = true;
    const scanData = {
        scannedCodes: new Set(),
        typeCounts: {}
    };

    // 🆕 Load scanned codes from backend
    function preloadScannedCodes() {
        fetch('/scans')
            .then(res => res.json())
            .then(data => {
                if (data) {
                    for (const key of Object.keys(data)) {
                        if (key !== "counts") {
                            scanData.scannedCodes.add(key);
                        }
                    }
                    scanData.typeCounts = data.counts || {};
                    updateStats();
                }
            })
            .catch(err => {
                console.error("Failed to load scanned codes:", err);
            });
    }

    // Start webcam and scanner
    function startCameraAndScanner() {
        navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: 'environment'
            }
        }).then(stream => {
            video.srcObject = stream;
            scannerActive = true;
            initScanner();
            resultElement.textContent = 'Scanner active';
        }).catch(err => {
            resultElement.textContent = 'Error: Camera access denied';
            console.error("Camera error:", err);
        });
    }

    preloadScannedCodes();  // Load existing scans
    startCameraAndScanner();  // Start the scanner

    function initScanner() {
        const codeReader = new ZXing.BrowserMultiFormatReader();
        const hints = new Map();
        hints.set(ZXing.DecodeHintType.TRY_HARDER, true);

        codeReader.decodeFromVideoDevice(null, 'video', (result, err) => {
            if (!scannerActive) return;

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            if (result) {
                const text = result.getText();
                const format = result.getBarcodeFormat();
                const codeKey = `${format}:${text}`;

                drawBoundingBox(result, codeKey);

                if (!scanData.scannedCodes.has(codeKey)) {
                    scanData.scannedCodes.add(codeKey);
                    scanData.typeCounts[format] = (scanData.typeCounts[format] || 0) + 1;
                    updateStats();
                    playBeep();

                    fetch('/save-scan', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            format: format,
                            text: text
                        })
                    })
                    .then(res => res.json())
                    .then(data => {
                        const scanTime = new Date().toLocaleString();
                        if (data.new) {
                            resultElement.innerHTML = `
                                <strong style="color: #20c997">✅ ${format}:</strong> ${text}<br>
                                <small class="text-muted">${scanTime}</small>
                            `;
                        } else {
                            resultElement.innerHTML = `
                                <strong class="duplicate-scan">⏭ ${format}:</strong> ${text}<br>
                                <small class="text-muted">(Already scanned)</small>
                            `;
                        }
                    }).catch(err => {
                        console.error('Failed to save scan:', err);
                    });
                } else {
                    resultElement.innerHTML = `
                        <strong class="duplicate-scan">⏭ ${format}:</strong> ${text}<br>
                        <small class="text-muted">(Already scanned)</small>
                    `;
                }
            }

            if (err && !(err instanceof ZXing.NotFoundException)) {
                console.error("Scan error:", err);
            }
        }, hints);
    }

    function drawBoundingBox(result, codeKey) {
        const points = result.getResultPoints();
        if (points && points.length >= 2) {
            const xCoords = points.map(p => p.getX());
            const yCoords = points.map(p => p.getY());

            const minX = Math.min(...xCoords);
            const minY = Math.min(...yCoords);
            const maxX = Math.max(...xCoords);
            const maxY = Math.max(...yCoords);

            const width = maxX - minX;
            const height = maxY - minY;

            const isNew = !scanData.scannedCodes.has(codeKey);
            ctx.strokeStyle = isNew ? '#20c997' : '#ff6b6b';
            ctx.lineWidth = 3;
            ctx.strokeRect(minX, minY, width, height);

            ctx.fillStyle = ctx.strokeStyle;
            ctx.font = '14px Arial';
            ctx.fillText(isNew ? 'NEW SCAN' : 'DUPLICATE', minX, minY - 10);
        }
    }

    function updateStats() {
        const uniqueCount = scanData.scannedCodes.size;
        uniqueCountElement.textContent = uniqueCount;

        typeCountsElement.innerHTML = Object.entries(scanData.typeCounts)
            .map(([type, count]) => `${type}: <span class="scan-count">${count}</span>`)
            .join('<br>');
    }

    function playBeep() {
        const beep = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABABAAQB8AAEAfAAABAAgAZGF0YU...');
        beep.play().catch(e => console.log("Beep error:", e));
    }

    stopBtn.addEventListener('click', () => {
        scannerActive = false;
        if (video.srcObject) {
            video.srcObject.getTracks().forEach(track => track.stop());
        }
        resultElement.textContent = 'Scanner stopped';
        stopBtn.classList.add('d-none');
        startBtn.classList.remove('d-none');
    });

    startBtn.addEventListener('click', () => {
        startCameraAndScanner();
        startBtn.classList.add('d-none');
        stopBtn.classList.remove('d-none');
    });
});
