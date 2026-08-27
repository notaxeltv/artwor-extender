# TCG Artwork Outpainting

Applicazione desktop **100% locale** per estendere (outpaint) l'artwork di
carte TCG (Pokémon, One Piece, Magic: The Gathering) usando **Ollama** come
motore di generazione immagini. Nessuna chiamata a servizi cloud: tutto
avviene sulla macchina dell'utente.

- **Backend**: Python 3.10+ / FastAPI / Pillow / requests.
- **Frontend**: Electron + JavaScript vanilla.
- **Motore di generazione**: Ollama (`http://localhost:11434/api/generate`).

## Struttura del progetto

```
.
├── backend/
│   ├── main.py            # App FastAPI (endpoint /health, /outpaint, /remove-elements)
│   ├── outpaint.py        # Logica di outpainting e rimozione elementi (canvas/maschera + Ollama)
│   ├── ollama_client.py   # Client HTTP per l'API locale di Ollama
│   ├── prompts.py         # Prompt dedicati per Pokémon / One Piece / Magic
│   └── requirements.txt
├── frontend/
│   ├── package.json
│   ├── main.js             # Processo principale Electron
│   ├── preload.js
│   ├── index.html          # UI (drag&drop, slider, dropdown, preview)
│   ├── renderer.js         # Logica UI + chiamate al backend
│   └── styles.css
├── .gitignore
└── README.md
```

## Requisiti

- **Python 3.10+**
- **Node.js 18+** e npm
- **Ollama** installato e in esecuzione (`ollama serve`)
- Un modello di diffusione scaricato in Ollama, es.:

  ```bash
  ollama pull flux2-klein:4b
  ```

  (in alternativa un modello equivalente che il tuo Ollama supporti per la
  generazione/estensione di immagini, es. una variante Stable Diffusion).

## Setup

### 1. Backend (FastAPI)

```bash
cd backend

# (Consigliato) crea un ambiente virtuale
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Avvia il server locale:

```bash
python main.py
# oppure, equivalente:
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Verifica che sia attivo:

```bash
curl http://127.0.0.1:8000/health
# -> {"status": "ok"}
```

### 2. Ollama

In un altro terminale, assicurati che Ollama sia in esecuzione e che il
modello scelto sia disponibile:

```bash
ollama serve
ollama pull flux2-klein:4b
```

### 3. Frontend (Electron)

```bash
cd frontend
npm install
npm start
```

Si apre la finestra dell'applicazione desktop, pronta all'uso (assicurati
che il backend sul punto 1 sia già in esecuzione su `http://localhost:8000`).

## Esempio di utilizzo

1. Avvia `ollama serve` e assicurati che il modello (es. `flux2-klein:4b`)
   sia scaricato.
2. Avvia il backend: `cd backend && python main.py`.
3. Avvia il frontend: `cd frontend && npm start`.
4. Nella finestra dell'app:
   - Trascina un'immagine dell'artwork della carta (PNG/JPG) nella dropzone.
   - (Opzionale, consigliato per carte "full art" con testo sovrapposto
     all'illustrazione) Apri "Rimuovi testo/cornice", disegna con il mouse
     rettangoli sopra testo/loghi/cornice da eliminare e clicca "Rimuovi
     elementi selezionati": l'immagine "pulita" sostituirà l'originale come
     input per l'estensione (vedi sezione dedicata più sotto).
   - Imposta la percentuale di estensione desiderata (10–60%) con lo slider.
   - Seleziona il tipo di TCG (Pokémon / One Piece / Magic) per adattare il
     prompt automaticamente.
   - (Opzionale) Scrivi un prompt personalizzato per sovrascrivere quello
     predefinito.
   - Clicca **"Genera"** e attendi il completamento (dipende dal modello e
     dall'hardware disponibile).
   - Visualizza l'anteprima "prima/dopo" e clicca **"Scarica risultato"**
     per salvare il PNG generato.

### Esempio via API (senza Electron)

```bash
curl -X POST http://127.0.0.1:8000/outpaint \
  -F "file=@card_artwork.png" \
  -F "expand_ratio=0.2" \
  -F "tgc_type=pokemon" \
  -F "model=flux2-klein:4b" \
  -o result.png
```

## Come funziona l'outpainting

1. **Canvas espanso**: a partire dall'immagine originale, si crea un canvas
   più grande, ingrandito di `expand_ratio` su ciascun lato (es. `0.2` = +20%
   di larghezza/altezza aggiuntiva per lato). L'immagine originale viene
   incollata esattamente al centro del nuovo canvas; i bordi vuoti vengono
   riempiti con un colore neutro (grigio medio) per non "suggerire" al
   modello contenuti indesiderati (es. bordi neri o bianchi netti).
2. **Maschera**: viene generata una maschera in scala di grigi della stessa
   dimensione del canvas: **nero (0)** sull'area corrispondente all'artwork
   originale (da non modificare) e **bianco (255)** sui nuovi bordi (area da
   generare). La maschera viene poi usata anche per **compositare** il
   risultato finale, garantendo che il centro dell'immagine resti sempre
   identico all'originale, indipendentemente da eventuali micro-variazioni
   introdotte dal modello.
3. **Chiamata a Ollama**: il canvas (in PNG, codificato in base64 **senza**
   header `data:`) viene inviato a `POST http://localhost:11434/api/generate`
   insieme a un prompt testuale specifico per il tipo di TCG selezionato
   (Pokémon / One Piece / Magic), che istruisce il modello a estendere lo
   sfondo mantenendo lo stesso stile, senza aggiungere nuovi personaggi o
   testo.
4. **Composizione finale**: l'immagine generata (decodificata dal base64
   della risposta) viene combinata con il canvas originale tramite la
   maschera, per ottenere il risultato finale, che viene salvato su disco e
   restituito come PNG.

Questo approccio (canvas + mask + invio a un modello img2img/diffusione)
è la tecnica classica di *outpainting*: si dà al modello più "spazio
bianco" attorno all'immagine originale e gli si chiede di riempirlo in modo
coerente con lo stile esistente.

## Prompt per tipo di TCG

I prompt predefiniti si trovano in `backend/prompts.py`:

- **Pokémon**: stile anime/painterly, più cielo/paesaggio/effetti energia.
- **One Piece**: stile anime, più mare/cielo/edifici.
- **Magic: The Gathering**: stile fantasy painterly, più paesaggio/cielo/
  effetti magici.

In tutti i casi il prompt specifica esplicitamente di **non aggiungere
nuovi personaggi o testo** e di mantenere coerenza stilistica con
l'artwork originale. È possibile sovrascrivere completamente il prompt
tramite il campo "Prompt personalizzato" nella UI (o il parametro
`custom_prompt` dell'API).

## Rimuovere testo, loghi e cornici prima dell'estensione

Molte carte (soprattutto le versioni "full art"/"ex") hanno il box di
testo (nome, PS, descrizione dell'attacco, debolezza/resistenza/ritirata)
sovrapposto direttamente sull'illustrazione, non in una fascia separata.
Se questi elementi sono vicini al margine da estendere, il modello di
diffusione può "continuare" il testo o la cornice nel nuovo bordo generato
invece di produrre puro sfondo/paesaggio.

Per questo l'app include uno strumento di **rimozione manuale guidata**
(pannello "Rimuovi testo/cornice" nella UI, endpoint `POST
/remove-elements` nel backend):

1. Disegni con il mouse uno o più rettangoli sopra le zone da eliminare
   (testo, loghi, watermark, cornice della carta).
2. Il frontend costruisce una maschera bianco/nero della stessa dimensione
   dell'immagine (bianco = area da rimuovere e rigenerare, nero = area da
   preservare) e la invia insieme all'immagine originale al backend.
3. Il backend invia l'immagine intera a Ollama con un prompt che chiede di
   ricostruire in modo coerente le zone mascherate, senza aggiungere nuovo
   testo, poi compone il risultato finale usando la maschera: l'area **non**
   selezionata resta pixel-per-pixel identica all'originale.
4. L'immagine "pulita" ottenuta sostituisce l'input per la successiva fase
   di outpainting (o può essere scaricata a sé).

Puoi ripetere l'operazione più volte (es. prima rimuovi il box di testo,
poi la cornice) e usare "Ripristina originale" per tornare all'immagine
caricata inizialmente in qualsiasi momento.

Nota: come per l'outpainting, la qualità del risultato dipende dal
modello Ollama usato — non tutti i modelli gestiscono bene la
rimozione/ricostruzione di aree arbitrarie della stessa immagine
(img2img "inpainting"); se noti risultati scadenti, prova un modello
diverso o riduci l'area mascherata a ciò che è strettamente necessario.

## Come cambiare il modello Ollama

Il modello predefinito è `flux2-klein:4b` (costante `DEFAULT_MODEL` in
`backend/outpaint.py`). Per usarne un altro:

- **Da UI**: modifica il campo "Modello Ollama" prima di cliccare "Genera".
- **Via API**: passa il parametro `model` nella richiesta `POST /outpaint`.
- **Permanentemente**: cambia `DEFAULT_MODEL` in `backend/outpaint.py`.

Assicurati sempre di aver scaricato il modello scelto con
`ollama pull <nome-modello>` prima di usarlo. Modelli diversi possono avere
tempi di generazione e qualità del risultato molto differenti in base
all'hardware disponibile (CPU vs GPU, quantità di RAM/VRAM).

## Note tecniche

- Gli endpoint FastAPI usano funzioni `async def`; le operazioni bloccanti
  (I/O su file, chiamata HTTP a Ollama) sono comunque eseguite in modo
  sincrono all'interno della richiesta per semplicità: per un uso con più
  richieste concorrenti si potrebbe spostare `outpaint(...)` in un
  threadpool (es. `run_in_threadpool`) o in un task in background.
- I file temporanei di input/output vengono salvati nella cartella
  temporanea di sistema (`tempfile.gettempdir()`), quindi il codice
  funziona senza modifiche su Windows, macOS e Linux.
- `outpaint()` e `remove_elements()` condividono la stessa funzione interna
  `generate_and_composite()` (canvas/immagine + maschera → chiamata a
  Ollama → composizione locale): cambia solo come viene costruita la
  maschera (bordi calcolati automaticamente vs. rettangoli disegnati
  dall'utente).
- La risposta dell'endpoint `/api/generate` di Ollama non ha un formato
  standard per i modelli di diffusione/immagine; `ollama_client.py` prova a
  estrarre il base64 dell'immagine da diversi campi plausibili della
  risposta (`images[0]` oppure `response`). Se il tuo modello restituisce
  l'immagine in un campo diverso, adatta la funzione
  `_extract_image_from_response` in `backend/ollama_client.py`.
