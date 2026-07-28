# Guida FFXIV Lore Knowledge Base & Gestione del Contesto

Questa guida documenta come fornire al modello IA (LLM locale) l'intera **Lore di Final Fantasy XIV**, la terminologia ufficiale, i nomi di luoghi/entità ed il contesto specifico di ciascun foglio EXD di gioco.

---

## 1. Architettura della Traduzione a 3 Pilastri

Per ottenere traduzioni perfettamente integrate nel mondo di FFXIV e prive di errori sintattici nei file binari di gioco, l'architettura di **Interpresona** applica 3 pilastri fondamentali:

```
┌─────────────────────────────────────────────────────────┐
│ 1. System Prompt & Knowledge Base Lore (Glossario FFXIV)│
│    (Etere, Eredi della Settima Alba, Primordiali, Ascian, ecc.) │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│ 2. Iniezione Contesto Foglio (Sheet Context Injection) │
│    (es. "Addon -> UI / Pulsanti", "Quest -> Narrativo") │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│ 3. Preservazione Segnaposto e Codici di Gioco           │
│    (Tag ⟪VAR_X⟫ o segnaposto {0}, {1} immutati)        │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Pilastro 1: FFXIV Lore & Glossario Ufficiale

Il file `interpresona/resources/ffxiv_lore_glossary.json` contiene la mappatura dei termini chiave dall'inglese all'italiano (da *A Realm Reborn* a *Dawntrail*).

### Estratto Struttura JSON (`ffxiv_lore_glossary.json`)
```json
{
  "glossary": {
    "Scions of the Seventh Dawn": "Eredi della Settima Alba",
    "Warrior of Light": "Guerriero della Luce",
    "Aether": "Etere",
    "Aetheryte": "Eterite",
    "Primal": "Primordiale",
    "Ascian": "Ascian",
    "Lightwarden": "Custode della Luce",
    "Norvrandt": "Norvrandt",
    "Solution Nine": "Solution Nine",
    "Dynamis": "Dynamis",
    "Duty Finder": "Ricerca Missioni"
  }
}
```

### Come Estendere o Personalizzare il Glossario Utente
L'utente può creare file JSON personalizzati (es. `my_lore.json`) caricabili direttamente tramite l'interfaccia GUI o lo script Python.

**Esempio di file personalizzato**:
```json
{
  "glossary": {
    "Alisaie": "Alisaie",
    "Alphinaud": "Alphinaud",
    "Thancred": "Thancred",
    "Urianger": "Urianger",
    "Y'shtola": "Y'shtola",
    "Graaha Tia": "G'raha Tia"
  }
}
```
I file forniti dall'utente sovrascriveranno ed integreranno automaticamente il glossario di base fornito dal pacchetto.

---

## 3. Pilastro 2: Iniezione del Contesto del Foglio (`SHEET_CONTEXT_MAP`)

La lingua inglese di FFXIV ha stili molto diversi a seconda che la frase provenga da un elemento dell'interfaccia grafica (UI), da un messaggio di errore o da un dialogo epico tra personaggi.

Il modulo `lore_kb.py` rileva automaticamente il nome del foglio EXD in lavorazione e seleziona le linee guida adatte:

| Prefisso Foglio EXD | Descrizione del Contesto per l'IA | Registro Linguistico |
| :--- | :--- | :--- |
| **`Addon`** | Interfaccia Utente (UI), comandi di menu e bottoni. | Sintetico, imperativo o verbi all'infinito (es. "Accetta", "Rifiuta"). |
| **`Quest`** | Dialoghi di trama, obiettivi e testo di narrazione delle Quest. | Narrativo ed epico fantasy. |
| **`CustomTalk`** | Dialogo parlato diretto tra il personaggio ed un NPC. | Conversazionale naturalistico. |
| **`Action`** | Nomi e descrizioni di abilità di combattimento ed incantesimi. | Tecnico, preciso e descrittivo. |
| **`Status`** | Buff, debuff e stati alterati di combattimento. | Descrittivo e conciso. |
| **`Item`** | Nomi e descrizioni di armi, armature ed oggetti consumabili. | Descrittivo fantasy. |
| **`LogMessage`** | Messaggi del registro di sistema (chat log). | Informativo e formale. |

---

## 4. Pilastro 3: Mascheramento e Preservazione dei Codici di Gioco

Nei file binari di FFXIV, le stringhe contengono codici di controllo SeString per nomi di personaggi, genere grammaticale, numeri e colori.

1. **Prima di inviare il testo al LLM locale**, il modulo `masker.py` o `LocalLLMTranslator` trasforma i codici binari o i segnaposto tipo `{0}` in token sicuri (`VAR0`, `VAR1`).
2. **System Prompt**: L'IA viene istruita con la regola ferrea:
   > *"PRESERVA TASSATIVAMENTE tutti i segnaposto tipo {0}, {1}, VAR0, VAR1 o tag di codice senza alterarli, spostarli o eliminarli."*
3. **Al ritorno dalla traduzione**: I token `VAR0` vengono ripristinati esattamente nella loro sequenza binaria originale prima dell'iniezione nell'EXD.

---

## 5. Costruzione del System Prompt Inviato all'IA

Quando `LocalLLMTranslator` richiede la traduzione di una riga di testo, invia la seguente struttura prompt (generata dinamicamente da `lore_kb.py`):

```json
{
  "model": "qwen2.5:7b",
  "messages": [
    {
      "role": "system",
      "content": "Sei un esperto localizzatore e traduttore madrelingua italiano specializzato nell'universo di Final Fantasy XIV (FFXIV).\n\n### KNOWLEDGE BASE LORE & GLOSSARIO FFXIV:\n- Aether ➔ Etere\n- Aetheryte ➔ Eterite\n- Ascian ➔ Ascian\n- Primal ➔ Primordiale\n- Scions of the Seventh Dawn ➔ Eredi della Settima Alba\n- Warrior of Light ➔ Guerriero della Luce\n...\n\n### CONTESTO DEL FOGLIO IN TRADUZIONE:\nFoglio 'Quest': Dialoghi di trama, obiettivi e testo di narrazione delle Quest. Registro narrativo ed epico fantasy.\n\n### REGOLE FONDAMENTALI DI TRADUZIONE:\n1. Traduci l'inglese in un italiano naturale, fluido ed elegante, mantenendo il registro fantasy adatto al contesto.\n2. PRESERVA TASSATIVAMENTE tutti i segnaposto tipo {0}, {1}, VAR0, VAR1 o tag di codice senza alterarli, spostarli o eliminarli.\n3. Se la riga è un comando o elemento di UI (come in Addon), mantieni la traduzione sintetica (es. verbi all'infinito).\n4. Restituisci ESCLUSIVAMENTE la traduzione in italiano, senza spiegazioni, note o commenti introduttivi."
    },
    {
      "role": "user",
      "content": "Shall we pray for the Scions of the Seventh Dawn at the Aetheryte, VAR0?"
    }
  ]
}
```

### Risultato restituito dal modello:
> `"Pregheremo per le Scagli dell'Alba presso l'Eterite, VAR0?"`

I token `VAR0` verranno poi riconvertiti istantaneamente nei byte SeString originali dal motore **Interpresona**.

---

## 6. Sintesi della Trama & Dossier Personaggi (`ffxiv_story_dossier.json`)

Per evitare che il modello interpreti erroneamente le relazioni tra i personaggi, le motivazioni drammatiche o i contesti storici delle espansioni, l'engine include il dataset `interpresona/resources/ffxiv_story_dossier.json`.

### 6.1 Sintesi Trama per Espansione
Quando si traducono dialoghi di trama (`Quest`, `CustomTalk`, `NpcYell`), l'IA riceve un quadro generale degli eventi principali:
- **A Realm Reborn (ARR)**: Ricostruzione dopo la 7a Calamità Ombrale, minaccia Garleana (Ultima Weapon), intrighi Ascian (Lhabrea).
- **Heavensward (HW)**: Guerra dei Draghi tra Ishgard e Nidhogg, segreti del clero di Ishgard.
- **Stormblood (SB)**: Liberazione di Ala Mhigo e Doma, tirannia di Zenos.
- **Shadowbringers (ShB)**: Viaggio nel Primo (Norvrandt), scontro con i Mangiatori di Peccati, storia degli Antichi (Emet-Selch, Amaurot, Crystal Exarch).
- **Endwalker (EW)**: I Final Days (Dynamis), caduta di Garlemald, segreti di Elpis (Venat, Hermes, Meteion), viaggio a Ultima Thule.
- **Dawntrail (DT)**: Rito di Successione a Tural (Wuk Lamat), regno di Alexandrea, Solution Nine, Living Memory (Sphene).

### 6.2 Dossier Personaggi & Guide al Registro Linguistico
Ciascun personaggio principale possiede istruzioni chiare per mantenere il giusto tono ed il registro stilistico in italiano:

| Personaggio | Ruolo & Personalità | Registro Linguistico Consigliato |
| :--- | :--- | :--- |
| **Alphinaud** | Diplomatico ed elocutore degli Scions. | Formale, colto, altamente eloquente ed elegante. |
| **Alisaie** | Duellante e sorella gemella di Alphinaud. | Diretta, passionale, pragmatica e schietta. |
| **Thancred** | Spia e protettore (Gunbreaker). | Stoico, maturo, ironico e protettivo. |
| **Y'shtola** | Studiosa dell'Etere e maga. | Intellettuale, calma, rigorosa ed ironicamente tagliente. |
| **Urianger** | Erudito e astrologo. | Arcaico, aulico, poetico e solenne (stile Elisabettiano). |
| **G'raha Tia** | Storico della Torre di Cristallo ed ex Exarch. | Entusiasta, leale, appassionato ed espressivo. |
| **Estinien** | L'Azure Dragoon. | Laconico, burbero, essenziale e asciutto. |
| **Emet-Selch** | Ascian originale (Solus zos Galvus). | Melancolico, sarcastico, teatrale e grandioso. |
| **Wuk Lamat** | Terza Promessa di Tuliyollal. | Energica, cordiale, schietta ed empatica. |

