# Guida Definitiva: Configurazione PC Windows Dedicato per Traduzione LLM Locale

Questa guida documenta passo dopo passo come configurare e ottimizzare un PC Windows dedicato equipaggiato con scheda grafica **NVIDIA RTX 2080 Super (8GB GDDR6 VRAM)** per eseguire in locale ed in modo autonomo (24/7) modelli di intelligenza artificiale per la traduzione di Final Fantasy XIV.

---

## 1. Valutazione Hardware & Performance

### 1.1 Risorse della Scheda Grafica (RTX 2080 Super)
* **VRAM Totale**: 8.192 MB (8 GB GDDR6)
* **CUDA Cores / Tensor Cores**: 3.072 CUDA Cores / 384 Tensor Cores
* **Larghezza di banda memoria**: 496 GB/s
* **Dimensione massima modello sostenibile**: Modelli 7B / 8B / 9B parametri quantizzati in formato GGUF (**Q4_K_M** o **Q5_K_M**).

### 1.2 Allocazione Memoria VRAM (Budgeting 8GB)
| Componente | Allocazione VRAM | Note |
| :--- | :--- | :--- |
| **Peso Modello Qwen 2.5 7B (Q4_K_M)** | **~4.8 GB** | Caricato interamente nella VRAM della GPU (`gpu_layers = max`). |
| **KV Cache Contesto (8,192 Token)** | **~1.8 GB** | Mantiene il contesto delle frasi e del glossario durante l'inferenza. |
| **Display & OS Overhead (Windows 11/10)** | **~1.2 GB** | Memoria riservata alla GUI di Windows e al rendering base. |
| **Margine di Sicurezza** | **~0.4 GB** | Previene lo *spillover* (sconfinamento) nella RAM di sistema. |

> [!IMPORTANT]
> Non superare mai i 7.0 GB di VRAM occupata dal solo modello + KV cache. Se la VRAM si satura, NVIDIA sposterà parti di memoria sulla RAM di sistema (System Memory Fallback), riducendo la velocità di traduzione da ~50 token/s ad appena 2-5 token/s.

---

## 2. Installazione e Configurazione del Server Ollama

Ollama è il server di inferenza consigliato poiché gestisce in autonomia l'allocazione sulla GPU NVIDIA ed espone un'API HTTP locale compatibile con lo standard OpenAI (`http://localhost:11434/v1`).

### 2.1 Download ed Installazione
1. Scarica l'installer per Windows da [ollama.com/download/windows](https://ollama.com/download/windows).
2. Esegui l'installer. Ollama si avvierà automaticamente nella barra delle applicazioni (System Tray).

### 2.2 Configurazione Variabili d'Ambiente Windows (Per Esecuzione Dedicata 24/7)
Per fare in modo che il PC dedicato mantenga il modello sempre pronto in VRAM e risponda immediatamente alle richieste del software di traduzione:

1. Premi `Win + R`, digita `sysdm.cpl` e premi **Invio**.
2. Vai nella scheda **Avanzate** -> **Variabili d'ambiente...**.
3. Nella sezione *Variabili utente* o *Variabili di sistema*, aggiungi le seguenti variabili:

| Nome Variabile | Valore consigliato | Descrizione |
| :--- | :--- | :--- |
| `OLLAMA_KEEP_ALIVE` | `-1` | **FONDAMENTALE**: Mantiene il modello perennemente caricato in VRAM (evita attese di caricamento ad ogni richiesta). |
| `OLLAMA_NUM_PARALLEL` | `1` | Ottimizza le prestazioni di traduzione sequenziale batch evitando contese di VRAM. |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Garantisce che non vengano caricati più modelli contemporaneamente saturendo gli 8GB. |
| `OLLAMA_HOST` | `0.0.0.0:11434` | (Opzionale) Consente al server Ollama di accettare connessioni da altri PC nella rete locale. |

---

## 3. Selezione e Download dei Modelli Consigliati

Apri il terminale (PowerShell o Prompt dei comandi) sul PC dedicato ed esegui i seguenti comandi per scaricare i modelli desiderati.

### 3.1 Qwen 2.5 (7B Instruct) — **RACCOMANDATO 🏆**
Il miglior modello Open Source attuale per comprensione e localizzazione della lingua italiana.
```powershell
ollama pull qwen2.5:7b
```
* **Impronta VRAM**: ~4.8 GB (Q4_K_M)
* **Velocità su RTX 2080 Super**: ~45 - 60 token/secondo.
* **Punti di Forza**: Eccellente resa stilistica della grammatica italiana, rispettoso del tono fantasy ed estremamente preciso nel mantenere i segnaposto `{0}`, `{1}` e `⟪VAR_X⟫`.

### 3.2 Llama 3.1 (8B Instruct) — **Alternativa Rigida**
```powershell
ollama pull llama3.1:8b
```
* **Impronta VRAM**: ~5.1 GB (Q4_K_M)
* **Velocità su RTX 2080 Super**: ~35 - 50 token/secondo.
* **Punti di Forza**: Ottimo per rispettare regole formali e di sicurezza nell'output.

### 3.3 Gemma 2 (9B Instruct) — **Alternativa Narrativa**
```powershell
ollama pull gemma2:9b
```
* **Impronta VRAM**: ~5.6 GB (Q4_K_M)
* **Velocità su RTX 2080 Super**: ~30 - 40 token/secondo.
* **Punti di Forza**: Resa espressiva molto ricca per dialoghi narrativi prolungati.

---

## 4. Ottimizzazione delle Prestazioni su PC Dedicato

Poiché il PC sarà dedicato esclusivamente alla traduzione:

1. **Abilita "Prestazioni Elevate" nelle Impostazioni Risparmio Energetico di Windows**:
   - Pannello di Controllo -> Opzioni Risparmio Energia -> Seleziona **Prestazioni elevate**.
2. **Pannello di Controllo NVIDIA**:
   - Apri il *Pannello di controllo NVIDIA*.
   - Vai su *Gestisci le impostazioni 3D* -> *Modalità di gestione dell'alimentazione* -> Imposta su **Preferisci le prestazioni massime**.
   - Imposta *Cuda - GPU di calcolo*: seleziona esplicitamente la **NVIDIA GeForce RTX 2080 Super**.
3. **Disattiva le sospensioni di sistema**:
   - Assicurati che l'opzione "Sospensione computer" sia impostata su **Mai**.

---

## 5. Verifica della Connessione dall'Applicazione Interpresona

1. In **Interpresona GUI** o **Simple GUI**, nel Passo 2 (Selezione Motore di Traduzione), seleziona **Local LLM (Ollama / LM Studio)**.
2. Inserisci l'URL dell'endpoint:
   - Se l'app gira sullo stesso PC dedicato: `http://localhost:11434/v1`
   - Se l'app gira su un altro PC della LAN: `http://<IP-DEL-PC-DEDICATO>:11434/v1`
3. Inserisci il nome del modello (es. `qwen2.5:7b`).
4. Clicca su **Test Connessione**: l'app invierà un prompt di prova ed il server Ollama risponderà confermando l'operatività del modello in VRAM.
