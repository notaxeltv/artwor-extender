"""Backend FastAPI per l'app di outpainting di artwork TCG.

Espone due endpoint:
- ``GET /health``: controllo di salute del servizio.
- ``POST /outpaint``: riceve un'immagine e i parametri di generazione,
  esegue l'outpainting tramite Ollama (in locale) e restituisce
  l'immagine risultante come PNG.

Tutto avviene in locale: nessuna chiamata a servizi cloud esterni.
"""

from __future__ import annotations

import io
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from PIL import Image

from ollama_client import OllamaError
from outpaint import DEFAULT_MODEL, outpaint, remove_elements
from prompts import get_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("tcg_outpaint.main")

app = FastAPI(
    title="TCG Artwork Outpainting API",
    description=(
        "API locale per estendere (outpaint) artwork di carte TCG "
        "(Pokémon, One Piece, Magic) usando Ollama."
    ),
    version="1.0.0",
)

# CORS permissivo: l'app Electron carica la UI da file locali (protocollo
# file://) e chiama questa API su localhost, quindi non ci sono rischi
# legati a domini esterni non fidati.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cartelle di lavoro per file temporanei di input/output. Usiamo la cartella
# di sistema temporanea per rimanere cross-platform (Windows/macOS/Linux).
_WORKDIR = Path(tempfile.gettempdir()) / "tcg_outpaint"
_UPLOADS_DIR = _WORKDIR / "uploads"
_OUTPUTS_DIR = _WORKDIR / "outputs"
_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

_VALID_TGC_TYPES = {"pokemon", "onepiece", "magic"}
_MIN_EXPAND_RATIO = 0.1
_MAX_EXPAND_RATIO = 0.6
_ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Semplice health check del servizio."""
    return {"status": "ok"}


@app.post("/outpaint")
async def outpaint_endpoint(
    file: UploadFile = File(..., description="Immagine dell'artwork (PNG/JPG)"),
    expand_ratio: float = Form(..., description="Percentuale di espansione per lato (0.1-0.6)"),
    tgc_type: str = Form(..., description="Tipo di TCG: pokemon | onepiece | magic"),
    model: Optional[str] = Form(None, description="Nome del modello Ollama da usare"),
    custom_prompt: Optional[str] = Form(None, description="Prompt personalizzato (opzionale)"),
) -> FileResponse:
    """Esegue l'outpainting di un'immagine di artwork tramite Ollama.

    Riceve l'immagine e i parametri via multipart/form-data, valida gli
    input, esegue la pipeline di outpainting e restituisce il file PNG
    generato.
    """
    _validate_inputs(file, expand_ratio, tgc_type)

    request_id = uuid.uuid4().hex
    input_suffix = Path(file.filename or "input.png").suffix or ".png"
    input_path = _UPLOADS_DIR / f"{request_id}{input_suffix}"
    output_path = _OUTPUTS_DIR / f"{request_id}_outpainted.png"

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="File immagine vuoto.")
        input_path.write_bytes(contents)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Errore durante il salvataggio del file caricato.")
        raise HTTPException(
            status_code=400, detail=f"Impossibile leggere/salvare il file caricato: {exc}"
        ) from exc

    resolved_model = model.strip() if model and model.strip() else DEFAULT_MODEL

    try:
        prompt_text = get_prompt(tgc_type, custom_prompt)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        logger.info(
            "Richiesta /outpaint: request_id=%s tgc_type=%s expand_ratio=%.2f model=%s",
            request_id,
            tgc_type,
            expand_ratio,
            resolved_model,
        )
        result_path = outpaint(
            input_path=input_path,
            output_path=output_path,
            expand_ratio=expand_ratio,
            prompt=prompt_text,
            model=resolved_model,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OllamaError as exc:
        logger.error("Errore Ollama: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Errore inatteso durante l'outpainting.")
        raise HTTPException(
            status_code=500, detail=f"Errore interno durante la generazione: {exc}"
        ) from exc
    finally:
        # Puliamo il file di input temporaneo; l'output resta disponibile
        # per essere restituito nella risposta.
        input_path.unlink(missing_ok=True)

    return FileResponse(
        path=result_path,
        media_type="image/png",
        filename="outpainted_result.png",
    )


@app.post("/remove-elements")
async def remove_elements_endpoint(
    file: UploadFile = File(..., description="Immagine originale (PNG/JPG)"),
    mask: UploadFile = File(
        ...,
        description=(
            "Maschera PNG in scala di grigi, stessa dimensione dell'immagine: "
            "bianco = area da rimuovere/rigenerare, nero = area da preservare"
        ),
    ),
    model: Optional[str] = Form(None, description="Nome del modello Ollama da usare"),
    custom_prompt: Optional[str] = Form(
        None, description="Prompt personalizzato (opzionale)"
    ),
) -> FileResponse:
    """Rimuove testo/cornici/loghi da un'immagine tramite una maschera manuale.

    Riceve l'immagine originale e una maschera (disegnata dall'utente lato
    frontend, es. rettangoli sopra il box di testo o la cornice della
    carta), e restituisce l'immagine "pulita" con quelle aree rigenerate da
    Ollama in modo coerente con lo stile circostante. Utile come passo di
    pre-elaborazione prima dell'outpainting, per evitare che il modello
    "continui" scritte o cornici nel nuovo bordo generato.
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo di file non supportato: {file.content_type}. "
                f"Formati accettati: PNG, JPG."
            ),
        )
    if mask.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo di file non supportato per la maschera: {mask.content_type}. "
                f"Formati accettati: PNG, JPG."
            ),
        )

    request_id = uuid.uuid4().hex
    input_suffix = Path(file.filename or "input.png").suffix or ".png"
    input_path = _UPLOADS_DIR / f"{request_id}{input_suffix}"
    output_path = _OUTPUTS_DIR / f"{request_id}_cleaned.png"

    try:
        contents = await file.read()
        mask_contents = await mask.read()
        if not contents or not mask_contents:
            raise HTTPException(
                status_code=400, detail="File immagine o maschera vuoti."
            )
        input_path.write_bytes(contents)
        mask_image = Image.open(io.BytesIO(mask_contents))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Errore durante la lettura dei file caricati.")
        raise HTTPException(
            status_code=400, detail=f"Impossibile leggere i file caricati: {exc}"
        ) from exc

    resolved_model = model.strip() if model and model.strip() else DEFAULT_MODEL

    try:
        logger.info(
            "Richiesta /remove-elements: request_id=%s model=%s",
            request_id,
            resolved_model,
        )
        result_path = remove_elements(
            input_path=input_path,
            output_path=output_path,
            mask=mask_image,
            prompt=custom_prompt,
            model=resolved_model,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OllamaError as exc:
        logger.error("Errore Ollama: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Errore inatteso durante la rimozione degli elementi.")
        raise HTTPException(
            status_code=500, detail=f"Errore interno durante la generazione: {exc}"
        ) from exc
    finally:
        input_path.unlink(missing_ok=True)

    return FileResponse(
        path=result_path,
        media_type="image/png",
        filename="cleaned_result.png",
    )


def _validate_inputs(file: UploadFile, expand_ratio: float, tgc_type: str) -> None:
    """Valida i parametri della richiesta di outpainting.

    Raises:
        HTTPException: Se uno dei parametri non è valido.
    """
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Tipo di file non supportato: {file.content_type}. "
                f"Formati accettati: PNG, JPG."
            ),
        )

    if not (_MIN_EXPAND_RATIO <= expand_ratio <= _MAX_EXPAND_RATIO):
        raise HTTPException(
            status_code=422,
            detail=(
                f"expand_ratio deve essere compreso tra {_MIN_EXPAND_RATIO} e "
                f"{_MAX_EXPAND_RATIO}, ricevuto: {expand_ratio}"
            ),
        )

    if tgc_type not in _VALID_TGC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"tgc_type non valido: {tgc_type!r}. Valori validi: "
                f"{sorted(_VALID_TGC_TYPES)}"
            ),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
