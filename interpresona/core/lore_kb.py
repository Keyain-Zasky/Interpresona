"""
FFXIV Lore Knowledge Base & Sheet Context Manager
=================================================
Provides FFXIV lore terminology, glossary mapping, and sheet-specific context
descriptions for Local LLM Translation engines (Ollama, LM Studio, llama.cpp).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Standard FFXIV Core Glossary (English -> Italian preferred lore localization)
DEFAULT_FFXIV_GLOSSARY: dict[str, str] = {
    # Key Entities & Factions
    "Scions of the Seventh Dawn": "Scagli dell'Alba",
    "Scion": "Scion",
    "Warrior of Light": "Guerriero della Luce",
    "Warrior of Darkness": "Guerriero delle Tenebre",
    "Grand Company": "Gran Compagnia",
    "Garlean Empire": "Impero Garleano",
    "Garlean": "Garleano",
    "Ascian": "Ascian",
    "Ascians": "Ascian",
    "Lightwarden": "Custode della Luce",
    "Lightwardens": "Custodi della Luce",
    "Primal": "Primordiale",
    "Primals": "Primordiali",
    "Eikon": "Eikon",
    "Eikons": "Eikon",
    "Akashic": "Akashic",

    # Key Concepts & Lore Elements
    "Aether": "Etere",
    "Aetheryte": "Eterite",
    "Aetherytes": "Eteriti",
    "Aetherial": "Etereo",
    "Dynamis": "Dynamis",
    "Mothercrystal": "Madrecristallo",
    "Allag": "Allag",
    "Allagan": "Allagano",
    "Echo": "l'Eco",

    # Major Continents & Locations
    "Eorzea": "Eorzea",
    "Hydaelyn": "Hydaelyn",
    "Zodiark": "Zodiark",
    "Ul'dah": "Ul'dah",
    "Gridania": "Gridania",
    "Limsa Lominsa": "Limsa Lominsa",
    "Ishgard": "Ishgard",
    "Ala Mhigo": "Ala Mhigo",
    "Doma": "Doma",
    "Kugane": "Kugane",
    "Norvrandt": "Norvrandt",
    "Sharlayan": "Sharlayan",
    "Radz-at-Han": "Radz-at-Han",
    "Elpis": "Elpis",
    "Ultima Thule": "Ultima Thule",
    "Solution Nine": "Solution Nine",
    "Tural": "Tural",
}

# Mapping of EXD Sheet prefixes to specific UI/Dialogue/Item context guidelines
SHEET_CONTEXT_MAP: dict[str, str] = {
    "Addon": "Interfaccia Utente (UI), comandi di menu e bottoni. Mantieni uno stile sintetico ed i verbi all'infinito.",
    "LogMessage": "Messaggi di sistema del registro di gioco. Stile informativo e sintetico.",
    "CustomTalk": "Dialogo parlato diretto tra il personaggio giocabile ed un NPC. Stile conversazionale fantasy.",
    "Quest": "Dialoghi di trama, obiettivi e testo di narrazione delle Quest. Registro narrativo ed epico fantasy.",
    "Fate": "Eventi dinamici di combattimento FATE. Stile urgente ed epico.",
    "NpcYell": "Esclamazioni e frasi pronunciate a voce alta dagli NPC in combattimento o nella mappa.",
    "Item": "Nomi e descrizioni di oggetti di gioco, armi, corazze e consumabili.",
    "EquipSlotCategory": "Categorie di equipaggiamento e slot armatura.",
    "Action": "Nomi e descrizioni di abilità di combattimento ed incantesimi dei personaggi.",
    "Status": "Nomi e descrizioni di stati alterati, potenziamenti (buff) e depotenziamenti (debuff).",
    "Trait": "Tratti passivi e maestrie dei mestieri e classi.",
    "PlaceName": "Nomi geografici di zone, cittadine e regioni.",
    "World": "Nomi dei server e mondi di gioco.",
}


def get_sheet_context_description(sheet_name: str) -> str:
    """Return a descriptive context explanation for a given EXD sheet name."""
    if not sheet_name:
        return "Testo generico di gioco."

    # Direct match or prefix match
    for key, desc in SHEET_CONTEXT_MAP.items():
        if sheet_name == key or sheet_name.startswith(f"{key}_") or sheet_name.startswith(key):
            return f"Foglio '{sheet_name}': {desc}"

    return f"Foglio '{sheet_name}': Dati di gioco generici."


def build_system_prompt(custom_glossary: Optional[dict[str, str]] = None, sheet_name: str = "") -> str:
    """
    Build a comprehensive, structured system prompt for Local LLMs (Ollama/LM Studio).
    Includes FFXIV Localization Persona, Lore Glossary, Rules, and Sheet Context.
    """
    glossary = dict(DEFAULT_FFXIV_GLOSSARY)
    if custom_glossary:
        glossary.update(custom_glossary)

    # Format glossary entries
    glossary_lines = [f"- {en} ➔ {it}" for en, it in sorted(glossary.items())[:35]]
    glossary_str = "\n".join(glossary_lines)

    sheet_context = get_sheet_context_description(sheet_name)

    prompt = (
        "Sei un esperto localizzatore e traduttore madrelingua italiano specializzato nell'universo di Final Fantasy XIV (FFXIV).\n\n"
        "### KNOWLEDGE BASE LORE & GLOSSARIO FFXIV:\n"
        f"{glossary_str}\n\n"
        "### CONTESTO DEL FOGLIO IN TRADUZIONE:\n"
        f"{sheet_context}\n\n"
        "### REGOLE FONDAMENTALI DI TRADUZIONE:\n"
        "1. Traduci l'inglese in un italiano naturale, fluido ed elegante, mantenendo il registro fantasy adatto al contesto.\n"
        "2. PRESERVA TASSATIVAMENTE tutti i segnaposto tipo {0}, {1}, VAR0, VAR1 o tag di codice senza alterarli, spostarli o eliminarli.\n"
        "3. Se la riga è un comando o elemento di UI (come in Addon), mantieni la traduzione sintetica (es. verbi all'infinito).\n"
        "4. Restituisci ESCLUSIVAMENTE la traduzione in italiano, senza spiegazioni, note o commenti introduttivi."
    )
    return prompt


def load_custom_glossary(file_path: Path) -> dict[str, str]:
    """Load a custom user glossary JSON file."""
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_custom_glossary(file_path: Path, glossary: dict[str, str]):
    """Save a custom user glossary to JSON file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8")
