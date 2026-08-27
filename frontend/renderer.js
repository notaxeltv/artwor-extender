// Logica del renderer (processo di UI di Electron).
//
// Gestisce drag & drop dell'immagine, i controlli (slider, dropdown,
// prompt personalizzato) e la chiamata al backend FastAPI locale su
// http://localhost:8000/outpaint. Vanilla JS, nessuna dipendenza esterna.

const BACKEND_URL = "http://localhost:8000";

// --- Riferimenti agli elementi del DOM -------------------------------------

const dropzone = document.getElementById("dropzone");
const dropzonePlaceholder = document.getElementById("dropzone-placeholder");
const dropzonePreview = document.getElementById("dropzone-preview");
const fileInput = document.getElementById("file-input");
const browseButton = document.getElementById("browse-button");

const expandRatioInput = document.getElementById("expand-ratio");
const expandRatioValue = document.getElementById("expand-ratio-value");
const tgcTypeSelect = document.getElementById("tgc-type");
const modelNameInput = document.getElementById("model-name");
const customPromptInput = document.getElementById("custom-prompt");

const generateButton = document.getElementById("generate-button");
const statusMessage = document.getElementById("status-message");

const previewOriginal = document.getElementById("preview-original");
const previewOriginalPlaceholder = document.getElementById(
  "preview-original-placeholder"
);
const previewResult = document.getElementById("preview-result");
const previewResultPlaceholder = document.getElementById(
  "preview-result-placeholder"
);
const loadingSpinner = document.getElementById("loading-spinner");
const downloadButton = document.getElementById("download-button");

// --- Stato applicativo -------------------------------------------------

let selectedFile = null; // File selezionato dall'utente (drag&drop o browse)
let resultObjectUrl = null; // URL blob dell'ultima immagine generata

// --- Slider percentuale di espansione ----------------------------------

expandRatioInput.addEventListener("input", () => {
  expandRatioValue.textContent = `${expandRatioInput.value}%`;
});

// --- Selezione file: drag & drop + click ---------------------------------

browseButton.addEventListener("click", (event) => {
  event.stopPropagation();
  fileInput.click();
});

dropzone.addEventListener("click", () => {
  fileInput.click();
});

fileInput.addEventListener("change", () => {
  if (fileInput.files && fileInput.files[0]) {
    handleFileSelected(fileInput.files[0]);
  }
});

["dragenter", "dragover"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    event.stopPropagation();
    dropzone.classList.add("dragover");
  });
});

["dragleave", "dragend", "drop"].forEach((eventName) => {
  dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    event.stopPropagation();
    dropzone.classList.remove("dragover");
  });
});

dropzone.addEventListener("drop", (event) => {
  const files = event.dataTransfer && event.dataTransfer.files;
  if (files && files[0]) {
    handleFileSelected(files[0]);
  }
});

function handleFileSelected(file) {
  const validTypes = ["image/png", "image/jpeg", "image/jpg"];
  if (!validTypes.includes(file.type)) {
    setStatus("Formato non supportato. Usa un file PNG o JPG.", "error");
    return;
  }

  selectedFile = file;
  generateButton.disabled = false;

  const objectUrl = URL.createObjectURL(file);

  dropzonePlaceholder.classList.add("hidden");
  dropzonePreview.src = objectUrl;
  dropzonePreview.classList.remove("hidden");

  previewOriginal.src = objectUrl;
  previewOriginal.classList.remove("hidden");
  previewOriginalPlaceholder.classList.add("hidden");

  // Reset del risultato precedente, se presente.
  resetResultPreview();
  setStatus("");
}

function resetResultPreview() {
  previewResult.classList.add("hidden");
  previewResultPlaceholder.classList.remove("hidden");
  downloadButton.classList.add("hidden");
  if (resultObjectUrl) {
    URL.revokeObjectURL(resultObjectUrl);
    resultObjectUrl = null;
  }
}

// --- Generazione ---------------------------------------------------------

generateButton.addEventListener("click", async () => {
  if (!selectedFile) {
    setStatus("Carica prima un'immagine.", "error");
    return;
  }

  const expandRatio = Number(expandRatioInput.value) / 100;
  const tgcType = tgcTypeSelect.value;
  const model = modelNameInput.value.trim();
  const customPrompt = customPromptInput.value.trim();

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("expand_ratio", String(expandRatio));
  formData.append("tgc_type", tgcType);
  if (model) {
    formData.append("model", model);
  }
  if (customPrompt) {
    formData.append("custom_prompt", customPrompt);
  }

  setLoading(true);
  setStatus("Generazione in corso, attendere...", "");

  try {
    const response = await fetch(`${BACKEND_URL}/outpaint`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorDetail = await extractErrorDetail(response);
      throw new Error(errorDetail);
    }

    const blob = await response.blob();

    resetResultPreview();
    resultObjectUrl = URL.createObjectURL(blob);
    previewResult.src = resultObjectUrl;
    previewResult.classList.remove("hidden");
    previewResultPlaceholder.classList.add("hidden");
    downloadButton.classList.remove("hidden");

    setStatus("Generazione completata con successo!", "success");
  } catch (error) {
    console.error(error);
    setStatus(
      `Errore durante la generazione: ${error.message || error}`,
      "error"
    );
  } finally {
    setLoading(false);
  }
});

async function extractErrorDetail(response) {
  try {
    const data = await response.json();
    if (data && data.detail) {
      return typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail);
    }
  } catch (_error) {
    // La risposta non è JSON: ignoriamo e usiamo il fallback sotto.
  }
  return `HTTP ${response.status} ${response.statusText}`;
}

function setLoading(isLoading) {
  generateButton.disabled = isLoading || !selectedFile;
  loadingSpinner.classList.toggle("hidden", !isLoading);
  if (isLoading) {
    previewResult.classList.add("hidden");
    previewResultPlaceholder.classList.add("hidden");
    downloadButton.classList.add("hidden");
  }
}

function setStatus(message, kind) {
  statusMessage.textContent = message;
  statusMessage.classList.remove("error", "success");
  if (kind) {
    statusMessage.classList.add(kind);
  }
}

// --- Download del risultato ----------------------------------------------

downloadButton.addEventListener("click", () => {
  if (!resultObjectUrl) {
    return;
  }
  const link = document.createElement("a");
  link.href = resultObjectUrl;
  link.download = "outpainted_result.png";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
});
