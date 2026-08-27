"""Client HTTP minimale per interagire con l'API locale di Ollama.

Ollama viene eseguito localmente (`ollama serve`) ed esposto di default su
``http://localhost:11434``. Questo modulo isola le chiamate di rete così che
`outpaint.py` possa concentrarsi sulla logica di elaborazione immagine.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import requests

logger = logging.getLogger("tcg_outpaint.ollama_client")

# Endpoint di generazione di Ollama. Non viene mai usato nessun servizio
# cloud: tutto avviene sulla macchina locale dell'utente.
OLLAMA_ENDPOINT = "http://localhost:11434/api/generate"

# Timeout generoso: i modelli di diffusione locali possono richiedere
# parecchi secondi/minuti in base alla GPU/CPU disponibile.
DEFAULT_TIMEOUT_SECONDS = 300


class OllamaError(RuntimeError):
    """Eccezione sollevata quando la chiamata a Ollama fallisce o la
    risposta non contiene un'immagine generata valida."""


def call_ollama_generate(
    model: str,
    prompt: str,
    image_base64: str,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Chiama ``POST /api/generate`` di Ollama per generare l'outpainting.

    Args:
        model: Nome del modello Ollama da usare (es. ``"flux2-klein:4b"``).
        prompt: Prompt testuale che descrive come estendere l'immagine.
        image_base64: Immagine di input codificata in base64 (PNG, senza
            l'header ``data:image/png;base64,``).
        timeout: Timeout della richiesta HTTP, in secondi.

    Returns:
        La stringa base64 dell'immagine generata (senza header).

    Raises:
        OllamaError: Se la richiesta HTTP fallisce, se Ollama non è
            raggiungibile, o se la risposta non contiene un'immagine.
    """
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "images": [image_base64],
        "stream": False,
    }

    logger.info("Invio richiesta a Ollama (model=%s) su %s", model, OLLAMA_ENDPOINT)

    try:
        response = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaError(
            "Impossibile contattare Ollama su "
            f"{OLLAMA_ENDPOINT}. Assicurati che 'ollama serve' sia in "
            "esecuzione."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise OllamaError(
            f"Timeout ({timeout}s) durante la richiesta a Ollama. Il modello "
            "potrebbe essere troppo lento per l'hardware disponibile."
        ) from exc
    except requests.exceptions.HTTPError as exc:
        raise OllamaError(
            f"Ollama ha risposto con un errore HTTP: {exc}. Corpo risposta: "
            f"{response.text[:500]}"
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise OllamaError("La risposta di Ollama non è un JSON valido.") from exc

    image_b64 = _extract_image_from_response(data)
    if image_b64 is None:
        raise OllamaError(
            "La risposta di Ollama non contiene un'immagine generata. "
            "Verifica che il modello selezionato supporti la generazione "
            f"di immagini (img2img/outpainting). Risposta ricevuta: "
            f"{str(data)[:500]}"
        )

    return image_b64


def _extract_image_from_response(data: dict[str, Any]) -> str | None:
    """Estrae la stringa base64 dell'immagine dalla risposta di Ollama.

    L'API `/api/generate` di Ollama è pensata principalmente per modelli di
    testo/visione, quindi il formato esatto della risposta per i modelli di
    diffusione può variare. Per essere robusti, proviamo diversi campi noti
    o plausibili prima di arrenderci.
    """
    # Caso 1: alcuni modelli restituiscono direttamente una lista "images".
    images = data.get("images")
    if isinstance(images, list) and images:
        candidate = images[0]
        if isinstance(candidate, str) and candidate:
            return candidate

    # Caso 2: il campo "response" contiene direttamente il base64 dell'immagine
    # (comportamento standard di /api/generate per il testo, riusato qui per
    # i modelli di diffusione che restituiscono un'immagine invece di testo).
    response_field = data.get("response")
    if isinstance(response_field, str) and _looks_like_base64_image(response_field):
        return response_field

    return None


def _looks_like_base64_image(value: str) -> bool:
    """Verifica euristicamente se una stringa è un'immagine base64 valida."""
    value = value.strip()
    if not value:
        return False
    try:
        # Decodifichiamo solo i primi byte per verificare che sia base64 valido
        # e che assomigli a un'intestazione di file immagine (PNG/JPEG).
        decoded = base64.b64decode(value[:64] + "====", validate=False)
    except Exception:
        return False
    return decoded.startswith(b"\x89PNG") or decoded.startswith(b"\xff\xd8\xff")
