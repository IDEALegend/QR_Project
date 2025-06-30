const video = document.getElementById('video');
const canvas = document.getElementById('canvas');
const preview = document.getElementById('snapshot-preview');
const fileSizeInfo = document.getElementById('file-size-info');
const captureBtn = document.getElementById('capture-btn');
const uploadBtn = document.getElementById('upload-btn');
const statusMessage = document.getElementById('status-message');
const form = document.getElementById('snapshot-form');

let capturedImageBlob = null;

// Show status message
function showStatus(message, type = 'info') {
    statusMessage.textContent = message;
    statusMessage.className = `status-message ${type}`;
    statusMessage.style.display = 'block';

    if (type !== 'error') {
        setTimeout(() => {
            statusMessage.style.display = 'none';
        }, 3000);
    }
}

// Start camera stream
navigator.mediaDevices.getUserMedia({
    video: {
        width: { ideal: 640 },
        height: { ideal: 480 },
        facingMode: 'environment' // Use back camera on mobile if available
    }
})
.then(stream => {
    video.srcObject = stream;
    showStatus("Camera ready! 📹", 'success');
})
.catch(err => {
    console.error("Camera error:", err);
    showStatus("Camera access denied or unavailable. Please check permissions.", 'error');
});

// Capture image function
window.captureImage = function () {
    if (!video.videoWidth || !video.videoHeight) {
        showStatus("Camera not ready. Please wait...", 'warning');
        return;
    }

    const context = canvas.getContext('2d');

    // Set canvas size to match video
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;

    // Draw video frame to canvas
    context.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Convert canvas to blob
    canvas.toBlob(function(blob) {
        if (!blob) {
            showStatus("Failed to capture image. Please try again.", 'error');
            return;
        }

        capturedImageBlob = blob;

        // Show preview
        const imageURL = URL.createObjectURL(blob);
        preview.src = imageURL;
        preview.style.display = 'block';

        // Calculate and show file size
        const sizeInBytes = blob.size;
        const sizeInMB = (sizeInBytes / (1024 * 1024)).toFixed(2);
        const sizeInKB = (sizeInBytes / 1024).toFixed(0);

        if (sizeInBytes > 1024 * 1024) {
            fileSizeInfo.textContent = `📂 Image size: ${sizeInMB} MB`;
        } else {
            fileSizeInfo.textContent = `📂 Image size: ${sizeInKB} KB`;
        }

        // Check size limit (10MB)
        if (sizeInBytes > 10 * 1024 * 1024) {
            showStatus("Image too large! Please reduce quality or try again.", 'error');
            uploadBtn.disabled = true;
        } else {
            uploadBtn.disabled = false;
            showStatus("Image captured successfully! Click upload to scan. 📷✅", 'success');
        }

    }, 'image/png', 0.8); // PNG format with 80% quality
};

// Handle form submission
form.addEventListener('submit', function(e) {
    e.preventDefault();

    if (!capturedImageBlob) {
        showStatus("Please capture an image first!", 'warning');
        return;
    }

    // Create FormData and append the blob as a file
    const formData = new FormData();
    formData.append('image', capturedImageBlob, 'capture.png');

    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '⏳ Scanning...';

    // Submit the form data
    fetch('/capture-upload', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.text();
    })
    .then(html => {
        // Replace current page with the result
        document.open();
        document.write(html);
        document.close();
    })
    .catch(error => {
        console.error('Upload error:', error);
        showStatus('Upload failed. Please try again.', 'error');
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = '📤 Upload to Scan';
    });
});

// Clean up camera stream when page unloads
window.addEventListener('beforeunload', function() {
    if (video.srcObject) {
        const tracks = video.srcObject.getTracks();
        tracks.forEach(track => track.stop());
    }
});