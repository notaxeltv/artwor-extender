"""Generazione dei prompt testuali per l'outpainting in base al tipo di TCG.

Ogni gioco di carte (Pokémon, One Piece, Magic: The Gathering) ha uno stile
grafico diverso, quindi usiamo un prompt dedicato per guidare il modello di
diffusione verso il risultato desiderato, mantenendo lo stile originale e
senza aggiungere nuovi personaggi o testo.
"""

from __future__ import annotations

from typing import Literal

# Tipi di TCG supportati dall'applicazione.
TgcType = Literal["pokemon", "onepiece", "magic"]

_PROMPTS: dict[TgcType, str] = {
    "pokemon": (
        "Extend the background of this Pokémon card artwork, keep the same "
        "anime/painterly style, add more sky/landscape/energy effects, do "
        "not add new characters or text."
    ),
    "onepiece": (
        "Extend the background of this One Piece card artwork, keep the "
        "same anime style and colors, add more sea/sky/buildings, do not "
        "add new characters or text."
    ),
    "magic": (
        "Extend the background of this Magic: The Gathering card artwork, "
        "keep the same fantasy painterly style, add more landscape/sky/magic "
        "effects, do not add new characters or text."
    ),
}

# Suffisso comune aggiunto a ogni prompt per rinforzare i vincoli di
# coerenza stilistica richiesti dall'outpainting (evita artefatti evidenti
# al confine tra immagine originale e area generata).
_COMMON_SUFFIX = (
    " Seamlessly blend the new area with the existing artwork, matching "
    "lighting, color palette and brush/rendering style. Do not change the "
    "existing artwork."
)


def get_prompt(tgc_type: TgcType, custom_prompt: str | None = None) -> str:
    """Restituisce il prompt da usare per l'outpainting.

    Args:
        tgc_type: Il tipo di gioco di carte ("pokemon", "onepiece", "magic").
        custom_prompt: Se fornito (e non vuoto), sovrascrive completamente il
            prompt predefinito, permettendo all'utente di personalizzare la
            richiesta.

    Returns:
        Il testo del prompt da inviare a Ollama.

    Raises:
        ValueError: Se `tgc_type` non è uno dei valori supportati e non è
            stato fornito un `custom_prompt`.
    """
    if custom_prompt is not None and custom_prompt.strip():
        return custom_prompt.strip()

    if tgc_type not in _PROMPTS:
        raise ValueError(
            f"Tipo di TCG non supportato: {tgc_type!r}. "
            f"Valori validi: {list(_PROMPTS.keys())}"
        )

    return _PROMPTS[tgc_type] + _COMMON_SUFFIX
