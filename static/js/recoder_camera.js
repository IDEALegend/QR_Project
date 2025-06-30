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

const metaParams = new URLSearchParams(window.location.search);
const metaInfo = {
  title: metaParams.get("title") || "Untitled",
  subtitle: metaParams.get("subtitle") || "",
  code: metaParams.get("code") || ""
};

// 🔒 Prevent scanning with missing title
if (!metaInfo.title || metaInfo.title.trim() === "") {
  const errorBox = document.createElement("div");
  errorBox.textContent = "🚫 Missing title. Redirecting to builder...";
  errorBox.style.color = "#ff6b6b";
  errorBox.style.fontWeight = "bold";
  errorBox.style.marginTop = "20px";
  errorBox.style.animation = "shake 0.3s ease-in-out";

  document.body.appendChild(errorBox);

  setTimeout(() => {
    window.location.href = "/record-builder";
  }, 2000);
}


function updateStats() {
  uniqueCountElement.textContent = scanData.scannedCodes.size;
  typeCountsElement.innerHTML = Object.entries(scanData.typeCounts)
    .map(([type, count]) => `${type}: <span class="scan-count">${count}</span>`)
    .join('<br>');
}

function drawBoundingBox(result, isNew) {
  const points = result.getResultPoints();
  if (points && points.length >= 2) {
    const xCoords = points.map(p => p.getX());
    const yCoords = points.map(p => p.getY());
    const minX = Math.min(...xCoords);
    const minY = Math.min(...yCoords);
    const width = Math.max(...xCoords) - minX;
    const height = Math.max(...yCoords) - minY;

    ctx.strokeStyle = isNew ? '#20c997' : '#ff6b6b';
    ctx.lineWidth = 3;
    ctx.strokeRect(minX, minY, width, height);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = '14px Arial';
    ctx.fillText(isNew ? 'NEW SCAN' : 'DUPLICATE', minX, minY - 10);
  }
}

function playBeep() {
  const beep = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAABErAAABAAgAZGF0YQAAAAA=');
  beep.play().catch(e => console.log("Beep error:", e));
}

function startCameraAndScanner() {
  navigator.mediaDevices.getUserMedia({
    video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'environment' }
  }).then(stream => {
    video.srcObject = stream;
    scannerActive = true;

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

        fetch('/save-record-scan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            format: format,
            text: text,
            meta_info: metaInfo
          })
        })
        .then(res => res.json())
        .then(data => {
          const isNew = !!data.new;
          drawBoundingBox(result, isNew);

          if (isNew) {
            scanData.scannedCodes.add(codeKey);
            scanData.typeCounts[format] = (scanData.typeCounts[format] || 0) + 1;
            playBeep();
            updateStats();
            resultElement.innerHTML = `<strong style="color: #20c997">✅ ${format}:</strong> ${text}`;
          } else {
            resultElement.innerHTML = `<strong class="duplicate-scan">⏭ ${format}:</strong> ${text}`;
          }
        });
      }

      if (err && !(err instanceof ZXing.NotFoundException)) {
        console.error("Scan error:", err);
      }
    }, hints);
  }).catch(err => {
    resultElement.textContent = 'Camera error';
    console.error("Camera access error:", err);
  });
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

function preloadExistingScans(title, callback) {
  fetch(`/preview-record?title=${encodeURIComponent(title)}&t=${Date.now()}`)
    .then(res => res.json())
    .then(record => {
      for (const key of Object.keys(record)) {
        if (key !== "counts") {
          scanData.scannedCodes.add(key);
        }
      }
      if (callback) callback();
    })
    .catch(err => {
      console.error("Failed to preload scans:", err);
      if (callback) callback();
    });
}

preloadExistingScans(metaInfo.title, startCameraAndScanner);