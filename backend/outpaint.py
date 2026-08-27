"""Logica di outpainting per artwork di carte TCG.

Approccio (canvas + mask + Ollama img2img):

1. Si crea un canvas più grande dell'immagine originale, espandendo i lati
   di una percentuale ("expand_ratio") e incollando l'artwork originale al
   centro.
2. Si genera una maschera binaria della stessa dimensione del canvas: nera
   (0) dove si trova l'immagine originale (zona da NON modificare) e bianca
   (255) sui nuovi bordi (zona da generare/estendere).
3. Il canvas (con i bordi vuoti riempiti di un colore neutro) viene inviato
   a Ollama insieme a un prompt testuale che descrive come estendere lo
   sfondo mantenendo lo stile originale.
4. Ollama restituisce l'immagine generata in base64: la salviamo su disco.

Nota: la maschera viene calcolata e resa disponibile per eventuali usi
futuri (es. un modello che supporti esplicitamente inpainting/outpainting
con maschera), ed è comunque utile per compositare il risultato finale in
modo che l'area originale non venga mai alterata dal modello.

Questo modulo espone anche :func:`remove_elements`, che riusa lo stesso
schema (immagine + maschera + Ollama + composizione) per rimuovere testo,
cornici o loghi da un'immagine, usando però una maschera arbitraria
disegnata dall'utente invece di quella generata automaticamente sui bordi.
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

from PIL import Image

from ollama_client import OllamaError, call_ollama_generate
from prompts import TgcType, get_prompt

logger = logging.getLogger("tcg_outpaint.outpaint")

# Modello Ollama di default. Deve essere già stato scaricato con
# `ollama pull <nome-modello>` prima di usare l'app.
DEFAULT_MODEL = "flux2-klein:4b"

# Colore neutro (grigio medio) usato per riempire i nuovi bordi del canvas
# prima dell'invio a Ollama. Un colore neutro riduce il rischio che il
# modello "veda" un bordo netto nero/bianco e lo interpreti come contenuto.
_BORDER_FILL_COLOR = (128, 128, 128)


def image_to_base64_no_header(image: Image.Image) -> str:
    """Codifica un'immagine PIL in base64 PNG, senza header ``data:``.

    Args:
        image: Immagine PIL da codificare.

    Returns:
        Stringa base64 (solo i byte del PNG, nessun prefisso
        ``data:image/png;base64,``), pronta per essere inviata a Ollama.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def base64_to_image(data: str) -> Image.Image:
    """Decodifica una stringa base64 (senza header) in un'immagine PIL."""
    raw = base64.b64decode(data)
    return Image.open(io.BytesIO(raw)).convert("RGB")


def create_outpaint_canvas(
    src: Image.Image, expand_ratio: float
) -> tuple[Image.Image, Image.Image]:
    """Crea il canvas espanso e la relativa maschera per l'outpainting.

    Args:
        src: Immagine originale dell'artwork della carta.
        expand_ratio: Percentuale di espansione per ciascun lato (es. 0.2 =
            +20% su ogni lato di larghezza/altezza).

    Returns:
        Una tupla ``(canvas, mask)`` dove:
        - ``canvas`` è la nuova immagine RGB, più grande, con l'originale
          incollato al centro e i bordi riempiti con un colore neutro.
        - ``mask`` è un'immagine in scala di grigi (``L``) della stessa
          dimensione del canvas: nero (0) sull'area originale, bianco (255)
          sui bordi da generare.
    """
    if not 0.0 < expand_ratio <= 1.0:
        raise ValueError(
            f"expand_ratio deve essere compreso tra 0 e 1, ricevuto: {expand_ratio}"
        )

    src = src.convert("RGB")
    width, height = src.size

    # Margini calcolati in pixel su ciascun lato in base alla percentuale.
    margin_x = int(round(width * expand_ratio))
    margin_y = int(round(height * expand_ratio))

    new_width = width + 2 * margin_x
    new_height = height + 2 * margin_y

    # Canvas: riempito con un colore neutro, l'originale va al centro.
    canvas = Image.new("RGB", (new_width, new_height), _BORDER_FILL_COLOR)
    canvas.paste(src, (margin_x, margin_y))

    # Maschera: bianco ovunque (area da generare) tranne il rettangolo
    # centrale corrispondente all'immagine originale, che resta nero
    # (area da preservare inalterata).
    mask = Image.new("L", (new_width, new_height), 255)
    preserved_area = Image.new("L", (width, height), 0)
    mask.paste(preserved_area, (margin_x, margin_y))

    return canvas, mask


def composite_preserving_original(
    generated: Image.Image,
    original: Image.Image,
    mask: Image.Image,
) -> Image.Image:
    """Compone il risultato finale assicurando che l'area originale non
    venga alterata dal modello, indipendentemente da eventuali piccole
    modifiche introdotte durante la generazione.

    Args:
        generated: Immagine generata da Ollama (stessa dimensione del
            canvas espanso).
        original: Canvas originale (prima della generazione), usato come
            "sorgente" per l'area da preservare.
        mask: Maschera prodotta da :func:`create_outpaint_canvas` (nero =
            area originale da preservare, bianco = area generata).

    Returns:
        L'immagine finale con l'area centrale identica all'originale e i
        bordi presi dall'immagine generata.
    """
    if generated.size != original.size:
        generated = generated.resize(original.size, Image.LANCZOS)

    generated = generated.convert("RGB")
    original = original.convert("RGB")

    # mask: 0 = originale (mantieni original), 255 = generato (mantieni generated)
    # Image.composite(image1, image2, mask) -> usa image1 dove mask è 255/piena.
    return Image.composite(generated, original, mask)


def generate_and_composite(
    canvas: Image.Image,
    mask: Image.Image,
    prompt: str,
    model: str,
) -> Image.Image:
    """Invia un canvas a Ollama e compone il risultato preservando l'originale.

    Passo condiviso sia dall'outpainting (bordi) sia dalla rimozione di
    elementi indesiderati (testo/cornici, con maschera arbitraria): si invia
    l'intera immagine a Ollama con un prompt, e si usa la maschera solo
    localmente per ricomporre il risultato finale, così l'area non
    mascherata (nera) resta sempre identica all'originale.

    Args:
        canvas: Immagine (RGB) da inviare a Ollama come riferimento.
        mask: Maschera in scala di grigi, stessa dimensione di ``canvas``:
            nero (0) = area da preservare inalterata, bianco (255) = area
            da sostituire con il contenuto generato da Ollama.
        prompt: Prompt testuale da inviare a Ollama.
        model: Nome del modello Ollama da usare.

    Returns:
        L'immagine finale risultante dalla composizione.

    Raises:
        ollama_client.OllamaError: Se la chiamata a Ollama fallisce.
    """
    canvas_b64 = image_to_base64_no_header(canvas)

    try:
        generated_b64 = call_ollama_generate(
            model=model,
            prompt=prompt,
            image_base64=canvas_b64,
        )
    except OllamaError:
        logger.exception("Chiamata a Ollama fallita.")
        raise

    generated_image = base64_to_image(generated_b64)

    # Componiamo il risultato per garantire che l'area non mascherata non
    # sia mai alterata, anche se il modello ha leggermente modificato quella
    # zona durante la generazione.
    return composite_preserving_original(generated_image, canvas, mask)


def outpaint(
    input_path: str | Path,
    output_path: str | Path,
    expand_ratio: float,
    prompt: str | None = None,
    model: str = DEFAULT_MODEL,
    tgc_type: TgcType | None = None,
) -> Path:
    """Esegue l'intero flusso di outpainting su un'immagine di artwork.

    Args:
        input_path: Percorso dell'immagine di input (PNG/JPG).
        output_path: Percorso dove salvare l'immagine generata.
        expand_ratio: Percentuale di espansione per lato (0.1 - 0.6).
        prompt: Prompt testuale da usare. Se ``None``, viene derivato da
            ``tgc_type`` tramite :func:`prompts.get_prompt`.
        model: Nome del modello Ollama da usare.
        tgc_type: Tipo di TCG, usato solo se ``prompt`` è ``None``.

    Returns:
        Il percorso (``Path``) del file immagine generato.

    Raises:
        ValueError: Se i parametri di input non sono validi.
        FileNotFoundError: Se ``input_path`` non esiste.
        ollama_client.OllamaError: Se la chiamata a Ollama fallisce.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Immagine di input non trovata: {input_path}")

    if prompt is None:
        if tgc_type is None:
            raise ValueError("È necessario fornire 'prompt' oppure 'tgc_type'.")
        prompt = get_prompt(tgc_type)

    logger.info(
        "Avvio outpainting: input=%s expand_ratio=%.2f model=%s",
        input_path,
        expand_ratio,
        model,
    )

    src = Image.open(input_path)
    canvas, mask = create_outpaint_canvas(src, expand_ratio)

    final_image = generate_and_composite(canvas, mask, prompt, model)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_image.save(output_path, format="PNG")

    logger.info("Outpainting completato: output=%s", output_path)
    return output_path


# Prompt di default usato per la rimozione di testo/cornici quando l'utente
# non fornisce un prompt personalizzato. Rinforza esplicitamente di non
# introdurre nuovo testo, per evitare che il modello "reinventi" scritte.
DEFAULT_REMOVE_ELEMENTS_PROMPT = (
    "Remove the text, lettering, logos, watermarks and card frame/border "
    "marked by the mask. Seamlessly reconstruct the underlying artwork in "
    "the same painterly/anime style, matching lighting and colors. Do not "
    "add any new text, lettering, numbers or characters."
)


def remove_elements(
    input_path: str | Path,
    output_path: str | Path,
    mask: Image.Image,
    prompt: str | None = None,
    model: str = DEFAULT_MODEL,
) -> Path:
    """Rimuove testo/cornici/loghi da un'immagine usando una maschera manuale.

    A differenza di :func:`outpaint`, qui non si espande il canvas: si
    invia l'immagine originale (stessa dimensione) a Ollama insieme a una
    maschera disegnata dall'utente (es. rettangoli sopra il box di testo o
    la cornice della carta). Il risultato finale è composto in modo che
    solo l'area mascherata (bianca) venga sostituita con il contenuto
    generato; il resto dell'immagine resta pixel-per-pixel identico.

    Args:
        input_path: Percorso dell'immagine di input (PNG/JPG).
        output_path: Percorso dove salvare l'immagine "pulita".
        mask: Maschera in scala di grigi (``L``), stessa dimensione
            dell'immagine di input: bianco (255) = area da rimuovere e
            rigenerare (es. testo/cornice), nero (0) = area da preservare.
        prompt: Prompt testuale da usare. Se ``None``, viene usato
            :data:`DEFAULT_REMOVE_ELEMENTS_PROMPT`.
        model: Nome del modello Ollama da usare.

    Returns:
        Il percorso (``Path``) del file immagine "pulito" generato.

    Raises:
        ValueError: Se la maschera non ha la stessa dimensione dell'immagine
            o se contiene un'area bianca vuota (nulla da rimuovere).
        FileNotFoundError: Se ``input_path`` non esiste.
        ollama_client.OllamaError: Se la chiamata a Ollama fallisce.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        raise FileNotFoundError(f"Immagine di input non trovata: {input_path}")

    src = Image.open(input_path).convert("RGB")
    mask = mask.convert("L")

    if mask.size != src.size:
        raise ValueError(
            f"La maschera ({mask.size}) deve avere la stessa dimensione "
            f"dell'immagine di input ({src.size})."
        )

    if mask.getbbox() is None or not mask.getextrema()[1]:
        raise ValueError(
            "La maschera è completamente nera: nessuna area da rimuovere. "
            "Disegna almeno un rettangolo sopra testo/cornice da eliminare."
        )

    resolved_prompt = prompt.strip() if prompt and prompt.strip() else (
        DEFAULT_REMOVE_ELEMENTS_PROMPT
    )

    logger.info(
        "Avvio rimozione elementi: input=%s model=%s", input_path, model
    )

    final_image = generate_and_composite(src, mask, resolved_prompt, model)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_image.save(output_path, format="PNG")

    logger.info("Rimozione elementi completata: output=%s", output_path)
    return output_path
