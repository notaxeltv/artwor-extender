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

const cleanupSection = document.getElementById("cleanup-section");
const cleanupToggleButton = document.getElementById("cleanup-toggle-button");
const cleanupEditor = document.getElementById("cleanup-editor");
const cleanupCanvas = document.getElementById("cleanup-canvas");
const cleanupUndoButton = document.getElementById("cleanup-undo-button");
const cleanupClearButton = document.getElementById("cleanup-clear-button");
const cleanupResetButton = document.getElementById("cleanup-reset-button");
const cleanupApplyButton = document.getElementById("cleanup-apply-button");
const cleanupStatus = document.getElementById("cleanup-status");

// --- Stato applicativo -------------------------------------------------

let selectedFile = null; // File usato per la generazione (originale o "pulito")
let originalUploadedFile = null; // File caricato dall'utente, non modificato
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
  originalUploadedFile = file;
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

  cleanupSection.classList.remove("hidden");
  loadImageIntoCleanupCanvas(file);
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

// --- Rimozione testo/cornice tramite maschera disegnata a mano ------------
//
// L'utente disegna rettangoli (in coordinate dell'immagine a piena
// risoluzione) sopra le zone da eliminare (testo, loghi, cornice). Al click
// su "Rimuovi elementi selezionati" costruiamo una maschera bianco/nero
// della stessa dimensione dell'immagine originale e la inviamo, insieme
// all'immagine, all'endpoint /remove-elements. Il risultato "pulito"
// sostituisce `selectedFile` e diventa l'input per la successiva estensione.

let cleanupImage = null; // Elemento <img> con l'immagine corrente (piena risoluzione)
let cleanupRects = []; // Rettangoli confermati, in coordinate naturali dell'immagine
let cleanupDrawing = null; // Rettangolo in corso di disegno (durante il drag)
let cleanupScale = 1; // Fattore di scala: pixel canvas visualizzati -> pixel naturali

const CLEANUP_MAX_CANVAS_WIDTH = 480;
const CLEANUP_MIN_RECT_SIZE = 4; // pixel naturali minimi per considerare valido un rettangolo

cleanupToggleButton.addEventListener("click", () => {
  cleanupEditor.classList.toggle("hidden");
});

function loadImageIntoCleanupCanvas(file) {
  const img = new Image();
  img.onload = () => {
    cleanupImage = img;
    cleanupRects = [];
    cleanupDrawing = null;

    const scale = Math.min(1, CLEANUP_MAX_CANVAS_WIDTH / img.naturalWidth);
    cleanupCanvas.width = Math.round(img.naturalWidth * scale);
    cleanupCanvas.height = Math.round(img.naturalHeight * scale);
    cleanupScale = scale;

    redrawCleanupCanvas();
    setCleanupStatus("");
  };
  img.src = URL.createObjectURL(file);
}

function redrawCleanupCanvas() {
  if (!cleanupImage) {
    return;
  }
  const ctx = cleanupCanvas.getContext("2d");
  ctx.clearRect(0, 0, cleanupCanvas.width, cleanupCanvas.height);
  ctx.drawImage(cleanupImage, 0, 0, cleanupCanvas.width, cleanupCanvas.height);

  ctx.fillStyle = "rgba(231, 76, 60, 0.45)";
  ctx.strokeStyle = "rgba(231, 76, 60, 0.9)";
  ctx.lineWidth = 1;

  const allRects = cleanupDrawing ? [...cleanupRects, cleanupDrawing] : cleanupRects;
  for (const rect of allRects) {
    const displayRect = naturalRectToDisplay(rect);
    ctx.fillRect(displayRect.x, displayRect.y, displayRect.w, displayRect.h);
    ctx.strokeRect(displayRect.x, displayRect.y, displayRect.w, displayRect.h);
  }
}

function naturalRectToDisplay(rect) {
  return {
    x: rect.x * cleanupScale,
    y: rect.y * cleanupScale,
    w: rect.w * cleanupScale,
    h: rect.h * cleanupScale,
  };
}

function canvasEventToNaturalPoint(event) {
  const bounds = cleanupCanvas.getBoundingClientRect();
  const displayX = event.clientX - bounds.left;
  const displayY = event.clientY - bounds.top;
  return {
    x: displayX / cleanupScale,
    y: displayY / cleanupScale,
  };
}

let cleanupDragStart = null;

cleanupCanvas.addEventListener("mousedown", (event) => {
  if (!cleanupImage) {
    return;
  }
  cleanupDragStart = canvasEventToNaturalPoint(event);
  cleanupDrawing = { x: cleanupDragStart.x, y: cleanupDragStart.y, w: 0, h: 0 };
});

cleanupCanvas.addEventListener("mousemove", (event) => {
  if (!cleanupDragStart) {
    return;
  }
  const point = canvasEventToNaturalPoint(event);
  cleanupDrawing = rectFromPoints(cleanupDragStart, point);
  redrawCleanupCanvas();
});

window.addEventListener("mouseup", () => {
  if (!cleanupDragStart) {
    return;
  }
  if (
    cleanupDrawing &&
    cleanupDrawing.w >= CLEANUP_MIN_RECT_SIZE &&
    cleanupDrawing.h >= CLEANUP_MIN_RECT_SIZE
  ) {
    cleanupRects.push(cleanupDrawing);
  }
  cleanupDragStart = null;
  cleanupDrawing = null;
  redrawCleanupCanvas();
});

function rectFromPoints(a, b) {
  const x = Math.max(0, Math.min(a.x, b.x));
  const y = Math.max(0, Math.min(a.y, b.y));
  const w = Math.abs(b.x - a.x);
  const h = Math.abs(b.y - a.y);
  return { x, y, w, h };
}

cleanupUndoButton.addEventListener("click", () => {
  cleanupRects.pop();
  redrawCleanupCanvas();
});

cleanupClearButton.addEventListener("click", () => {
  cleanupRects = [];
  redrawCleanupCanvas();
});

cleanupResetButton.addEventListener("click", () => {
  if (!originalUploadedFile) {
    return;
  }
  selectedFile = originalUploadedFile;
  const objectUrl = URL.createObjectURL(originalUploadedFile);
  dropzonePreview.src = objectUrl;
  previewOriginal.src = objectUrl;
  loadImageIntoCleanupCanvas(originalUploadedFile);
  resetResultPreview();
  setCleanupStatus("Immagine originale ripristinata.", "success");
});

cleanupApplyButton.addEventListener("click", async () => {
  if (!selectedFile || !cleanupImage) {
    setCleanupStatus("Carica prima un'immagine.", "error");
    return;
  }
  if (cleanupRects.length === 0) {
    setCleanupStatus(
      "Disegna almeno un rettangolo sopra l'area da rimuovere.",
      "error"
    );
    return;
  }

  const maskBlob = await buildCleanupMaskBlob(
    cleanupImage.naturalWidth,
    cleanupImage.naturalHeight,
    cleanupRects
  );

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("mask", maskBlob, "mask.png");
  const model = modelNameInput.value.trim();
  if (model) {
    formData.append("model", model);
  }

  cleanupApplyButton.disabled = true;
  setCleanupStatus("Rimozione in corso, attendere...", "");

  try {
    const response = await fetch(`${BACKEND_URL}/remove-elements`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorDetail = await extractErrorDetail(response);
      throw new Error(errorDetail);
    }

    const blob = await response.blob();
    const cleanedFile = new File([blob], "cleaned.png", { type: "image/png" });

    selectedFile = cleanedFile;
    cleanupRects = [];

    const objectUrl = URL.createObjectURL(cleanedFile);
    dropzonePreview.src = objectUrl;
    previewOriginal.src = objectUrl;
    loadImageIntoCleanupCanvas(cleanedFile);
    resetResultPreview();

    setCleanupStatus(
      "Elementi rimossi. L'immagine pulita verrà usata per l'estensione.",
      "success"
    );
  } catch (error) {
    console.error(error);
    setCleanupStatus(
      `Errore durante la rimozione: ${error.message || error}`,
      "error"
    );
  } finally {
    cleanupApplyButton.disabled = false;
  }
});

function buildCleanupMaskBlob(width, height, rects) {
  const maskCanvas = document.createElement("canvas");
  maskCanvas.width = width;
  maskCanvas.height = height;
  const ctx = maskCanvas.getContext("2d");
  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "white";
  for (const rect of rects) {
    ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
  }
  return new Promise((resolve) => {
    maskCanvas.toBlob((blob) => resolve(blob), "image/png");
  });
}

function setCleanupStatus(message, kind) {
  cleanupStatus.textContent = message;
  cleanupStatus.classList.remove("error", "success");
  if (kind) {
    cleanupStatus.classList.add(kind);
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
