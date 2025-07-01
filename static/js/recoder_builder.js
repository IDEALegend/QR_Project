let metaFields = [];

function addMetaField(label = '', value = '') {
  const container = document.createElement('div');
  container.className = 'meta-field';

  const index = metaFields.length;
  metaFields.push({ label, value });

  container.innerHTML = `
    <div class="meta-field-row">
      <input type="text" class="form-control" placeholder="Label" value="${label}" oninput="metaFields[${index}].label = this.value">
      <input type="text" class="form-control" placeholder="Value" value="${value}" oninput="metaFields[${index}].value = this.value">
      <button type="button" class="btn btn-outline-danger" onclick="removeMetaField(this)">✖</button>
    </div>
  `;

  document.getElementById('meta-fields').appendChild(container);
}

function removeMetaField(button) {
  const field = button.closest('.meta-field');
  const fields = Array.from(document.querySelectorAll('.meta-field'));
  const index = fields.indexOf(field);
  if (index > -1) metaFields.splice(index, 1);
  field.remove();
}

function startRecording(event) {
  event.preventDefault();

  const hasValidField = metaFields.some(field =>
    field.label.trim() !== "" && field.value.trim() !== ""
  );

  const errorDiv = document.getElementById("record-error");

  if (!hasValidField) {
    errorDiv.textContent = "🚫 Please fill at least one field (label and value).";
    errorDiv.style.display = "block";
    errorDiv.classList.remove("shake");
    void errorDiv.offsetWidth; // trigger reflow
    errorDiv.classList.add("shake");
    return;
  }

  errorDiv.style.display = "none";

  const query = new URLSearchParams();
  metaFields.forEach(field => {
    if (field.label.trim()) {
      query.append(field.label.trim(), field.value.trim());
    }
  });

  window.location.href = "/record-camera?" + query.toString();
}


function parseQueryParams() {
  const params = new URLSearchParams(window.location.search);
  const entries = [...params.entries()];
  return Object.fromEntries(entries);
}

function populateFromQuery(params) {
  for (const [label, value] of Object.entries(params)) {
    addMetaField(label, value);
  }
}

function fetchRecordPreview(title) {
  fetch(`/preview-record?title=${encodeURIComponent(title)}&t=${Date.now()}`)
    .then(res => res.json())
    .then(record => {
      const container = document.getElementById("preview-container");
      const preview = document.getElementById("record-preview");
      const actionButtons = document.getElementById("action-buttons");

      // Clean up escaped JSON inside "data" field
      const cleaned = {};
      for (const [key, value] of Object.entries(record)) {
        const entry = { ...value };
        try {
          const parsed = JSON.parse(entry.data);
          entry.data = parsed; // Replace string with parsed object
        } catch {
          // If not JSON, keep original string
        }
        cleaned[key] = entry;
      }

      preview.textContent = JSON.stringify(cleaned, null, 2);
      container.classList.remove("d-none");

      if (actionButtons) {
        actionButtons.classList.remove("d-none");
      }
    })
    .catch(err => {
      console.warn("No record found or error:", err);
    });
}

function downloadRecord() {
  const meta = {};
  metaFields.forEach(field => {
    if (field.label.trim()) {
      meta[field.label.trim()] = field.value.trim();
    }
  });

  const title = meta.title || 'Untitled';

  fetch(`/preview-record?title=${encodeURIComponent(title)}&t=${Date.now()}`)
    .then(res => res.json())
    .then(record => {
      const count = Object.keys(record).length;
      meta.count = count;

      const fullRecord = {
        meta_info: meta,
        record: record
      };

      const blob = new Blob([JSON.stringify(fullRecord, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title}_record.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    })
    .catch(err => {
      console.error("Download failed:", err);
      alert("Could not download. Make sure a scan record exists.");
    });
}

// Initial fields
const params = parseQueryParams();
if (Object.keys(params).length > 0) {
  populateFromQuery(params);
  if (params.title) {
    fetchRecordPreview(params.title);
  }
} else {
  addMetaField("title", "");
  addMetaField("subtitle", "");
  addMetaField("code", "");
}
