"""
FFXIV Lore Knowledge Base & Sheet Context Manager
=================================================
Provides FFXIV lore terminology, glossary mapping, and sheet-specific context
descriptions for Local LLM Translation engines (Ollama, LM Studio, llama.cpp).
"""
from __future__ import annotations

import json
import re
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


def load_resource_glossary() -> dict[str, str]:
    """Load default lore glossary from package resource JSON file if available."""
    resource_path = Path(__file__).parent.parent / "resources" / "ffxiv_lore_glossary.json"
    if resource_path.exists():
        try:
            data = json.loads(resource_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "glossary" in data:
                return {str(k): str(v) for k, v in data["glossary"].items()}
            elif isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
    return dict(DEFAULT_FFXIV_GLOSSARY)


def get_active_glossary(custom_glossary: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Get complete merged active glossary."""
    glossary = load_resource_glossary()
    if custom_glossary:
        glossary.update(custom_glossary)
    return glossary


def get_sheet_context_description(sheet_name: Optional[str] = "") -> str:
    """Return a descriptive context explanation for a given EXD sheet name."""
    sheet_name = sheet_name or ""
    if not sheet_name:
        return "Testo generico di gioco."

    # Direct match or prefix match
    for key, desc in SHEET_CONTEXT_MAP.items():
        if sheet_name == key or sheet_name.startswith(f"{key}_") or sheet_name.startswith(key):
            return f"Foglio '{sheet_name}': {desc}"

    return f"Foglio '{sheet_name}': Dati di gioco generici."


def load_story_dossier() -> dict:
    """Load FFXIV story summaries and character dossiers from package resource JSON."""
    resource_path = Path(__file__).parent.parent / "resources" / "ffxiv_story_dossier.json"
    if resource_path.exists():
        try:
            return json.loads(resource_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"expansions": {}, "characters": {}}


def get_story_summaries() -> dict[str, dict[str, str]]:
    """Return dictionary of expansion story summaries."""
    dossier = load_story_dossier()
    return dossier.get("expansions", {})


def get_character_dossiers() -> dict[str, dict[str, str]]:
    """Return dictionary of main character dossiers and speech guidance."""
    dossier = load_story_dossier()
    return dossier.get("characters", {})


def get_side_storylines() -> dict[str, dict[str, str]]:
    """Return dictionary of side storylines (Eureka, Bozja, Deep Dungeons, Werlyt, Hildibrand)."""
    dossier = load_story_dossier()
    return dossier.get("side_storylines", {})


ALIAS_MAP: dict[str, tuple[str, str]] = {
    # Characters
    "crystal exarch": ("G'raha Tia", "character"),
    "the exarch": ("G'raha Tia", "character"),
    "exarch": ("G'raha Tia", "character"),
    "hades": ("Emet-Selch", "character"),
    "solus zos galvus": ("Emet-Selch", "character"),
    "solus": ("Emet-Selch", "character"),
    "azure dragoon": ("Estinien", "character"),
    "estinien wyrmblood": ("Estinien", "character"),
    "master matoya": ("Y'shtola", "character"),
    "matoya": ("Y'shtola", "character"),
    "themis": ("Elidibus", "character"),
    "hephaistos": ("Lahabrea", "character"),
    "amon": ("Fandaniel", "character"),
    "hermes": ("Fandaniel", "character"),
    "yda": ("Lyse", "character"),
    "dawnservant": ("Wuk Lamat", "character"),
    "varshahn": ("Vrtra", "character"),
    "louisoix": ("Louisoix Leveilleur", "character"),
    "louisoix leveilleur": ("Louisoix Leveilleur", "character"),
    "queen sphene": ("Sphene", "character"),
    "zenos": ("Zenos yae Galvus", "character"),
    "gaius": ("Gaius van Baelsar", "character"),
    "hydaelyn": ("Venat", "character"),
    "scions of the seventh dawn": ("Scions of the Seventh Dawn", "glossary"),
    "circle of knowing": ("Circle of Knowing", "glossary"),
    "path of the twelve": ("Path of the Twelve", "glossary"),

    # Raids & Landmarks
    "syrcus tower": ("Crystal Tower", "raid"),
    "labyrinth of the ancients": ("Crystal Tower", "raid"),
    "world of darkness": ("Crystal Tower", "raid"),
    "binding coil": ("Coil of Bahamut", "raid"),
    "gordias": ("Alexander", "raid"),
    "midas": ("Alexander", "raid"),
    "creator": ("Alexander", "raid"),
    "deltascape": ("Omega", "raid"),
    "sigmascape": ("Omega", "raid"),
    "alphascape": ("Omega", "raid"),
    "asphodelos": ("Pandaemonium", "raid"),
    "abyssos": ("Pandaemonium", "raid"),
    "anabaseios": ("Pandaemonium", "raid"),
    "pandaemonium": ("Pandaemonium", "raid"),
    "pandæmonium": ("Pandaemonium", "raid"),

    # Jobs
    "paladin": ("PLD", "job"),
    "warrior": ("WAR", "job"),
    "dark knight": ("DRK", "job"),
    "gunbreaker": ("GNB", "job"),
    "white mage": ("WHM", "job"),
    "scholar": ("SCH", "job"),
    "astrologian": ("AST", "job"),
    "sage": ("SGE", "job"),
    "monk": ("MNK", "job"),
    "dragoon": ("DRG", "job"),
    "ninja": ("NIN", "job"),
    "samurai": ("SAM", "job"),
    "reaper": ("RPR", "job"),
    "viper": ("VPR", "job"),
    "bard": ("BRD", "job"),
    "machinist": ("MCH", "job"),
    "dancer": ("DNC", "job"),
    "black mage": ("BLM", "job"),
    "summoner": ("SMN", "job"),
    "red mage": ("RDM", "job"),
    "pictomancer": ("PCT", "job"),
    "blue mage": ("BLU", "job"),
}


def scavenge_lore_context(
    text: Optional[str] = "",
    sheet_name: Optional[str] = "",
    custom_glossary: Optional[dict[str, str]] = None,
    max_entities: int = 15,
    max_character_budget: int = 2500,
) -> dict:
    """
    Perform multi-pass entity extraction, alias mapping, multi-resource search,
    relevance scoring, and budget-enforced system prompt block construction.

    Args:
        text: Input string to analyze for lore entities.
        sheet_name: Optional EXD sheet name (e.g. 'Quest_MainScenario', 'Action_01').
        custom_glossary: Optional user custom glossary dictionary.
        max_entities: Maximum number of scavenged entities to return (default 15).
        max_character_budget: Maximum character budget for the scavenged prompt block (default 2500).

    Returns:
        Structured dict containing matched_glossary, detected_entities, relevant_characters,
        relevant_factions, relevant_jobs, relevant_stories, relevance_scores, and scavenged_prompt_block.
    """
    text = text or ""
    sheet_name = sheet_name or ""

    if not text or not text.strip():
        return {
            "matched_glossary": {},
            "detected_entities": [],
            "relevant_characters": {},
            "relevant_factions": {},
            "relevant_jobs": {},
            "relevant_stories": {},
            "relevance_scores": {},
            "scavenged_prompt_block": "",
        }

    raw_text = text
    text_lower = text.lower()

    # Sheet context flags for relevance boosting
    is_quest = any(sheet_name.startswith(p) for p in ("Quest", "CustomTalk", "NpcYell", "Cutscene", "DefaultTalk"))
    is_action = any(sheet_name.startswith(p) for p in ("Action", "Status", "Trait", "CraftAction"))
    is_placename = any(sheet_name.startswith(p) for p in ("PlaceName", "World"))
    is_addon = any(sheet_name.startswith(p) for p in ("Addon", "LogMessage", "Item"))

    matched_glossary: dict[str, str] = {}
    relevant_characters: dict[str, dict] = {}
    relevant_factions: dict[str, dict] = {}
    relevant_jobs: dict[str, dict] = {}
    relevant_stories: dict[str, dict] = {}
    scores: dict[str, float] = {}
    entity_categories: dict[str, str] = {}

    def add_score(name: str, category: str, w_match: float, count: int, w_domain: float, b_sheet: float):
        score = (w_match * count) + w_domain + b_sheet
        if name not in scores or score > scores[name]:
            scores[name] = round(score, 2)
            entity_categories[name] = category

    # 1. Multi-pass Entity Extraction: Regex for Proper Nouns and 3-Letter Job Codes
    proper_nouns = re.findall(r"\b[A-Z][a-zA-Z0-9']*(?:[-'\s]+[A-Z][a-zA-Z0-9']*)*\b", raw_text)
    job_code_matches = re.findall(
        r"\b(PLD|WAR|DRK|GNB|WHM|SCH|AST|SGE|MNK|DRG|NIN|SAM|RPR|VPR|BRD|MCH|DNC|BLM|SMN|RDM|PCT|BLU|CRP|BSM|ARM|GSM|LTW|WVR|ALC|CUL|MIN|BTN|FSH)\b",
        raw_text,
    )

    glossary = get_active_glossary(custom_glossary)
    characters = get_character_dossiers()
    jobs_data = load_job_lore().get("jobs", {})
    factions_data = load_factions_lore()

    # Active Proper Noun & Job Code Cross-Referencing
    for pn in proper_nouns:
        pn_lower = pn.lower()
        if pn_lower in ALIAS_MAP:
            canonical, category = ALIAS_MAP[pn_lower]
            w_domain = 2.5 if category == "character" else (2.0 if category == "job" else 1.5)
            b_sheet = 1.5 if (is_quest and category == "character") or (is_action and category == "job") else 0.0
            add_score(canonical, category, 2.5, 1, w_domain, b_sheet)

        for en_term, it_term in glossary.items():
            if en_term.lower() == pn_lower or (len(pn) >= 4 and pn_lower in en_term.lower()):
                w_domain = 1.8
                b_sheet = 1.5 if is_placename else (1.0 if is_addon else 0.0)
                add_score(en_term, "glossary", 2.5, 1, w_domain, b_sheet)
                matched_glossary[en_term] = it_term

        for char_name, char_info in characters.items():
            if char_name.lower() == pn_lower or pn_lower in char_name.lower() or any(pn_lower == n.lower() for n in char_name.split() if len(n) >= 3):
                add_score(char_name, "character", 3.0, 1, 2.5, 1.5 if is_quest else 0.0)
                relevant_characters[char_name] = char_info

        for f_key in ("garlean_empire", "ascian_overlords", "allagan_empire", "eorzean_alliance"):
            f_info = factions_data.get(f_key, {})
            fname = f_info.get("name", "")
            if fname and (fname.lower() in pn_lower or pn_lower in fname.lower()):
                add_score(fname, "faction", 2.5, 1, 2.0, 1.5 if is_quest else 0.0)
                relevant_factions[f_key] = f_info

        tribes = factions_data.get("tribal_nations", {})
        for tribe_name, tribe_info in tribes.items():
            if tribe_name.lower() in pn_lower or pn_lower in tribe_name.lower():
                add_score(f"Tribe: {tribe_name}", "faction", 2.5, 1, 2.0, 1.5 if is_quest else 0.0)
                relevant_factions[f"tribal_nations:{tribe_name}"] = tribe_info

    for jcode in job_code_matches:
        if jcode in jobs_data:
            job_info = jobs_data[jcode]
            add_score(jcode, "job", 3.5, 1, 2.0, 1.5 if is_action else 0.0)
            relevant_jobs[jcode] = job_info

    # 2. Multi-Resource Search: Lore Glossary
    glossary = get_active_glossary(custom_glossary)
    sorted_glossary_keys = sorted(glossary.keys(), key=lambda k: -len(k))
    for en_term in sorted_glossary_keys:
        it_term = glossary[en_term]
        if len(en_term) <= 4:
            matches = re.findall(r"\b" + re.escape(en_term) + r"\b", raw_text)
            if matches:
                count = len(matches)
                w_match = 3.0 if any(m == en_term for m in matches) else 2.0
                w_domain = 1.8
                b_sheet = 1.5 if is_placename else (1.0 if is_addon else 0.0)
                add_score(en_term, "glossary", w_match, count, w_domain, b_sheet)
                matched_glossary[en_term] = it_term
        else:
            if en_term.lower() in text_lower:
                matches = re.findall(r"\b" + re.escape(en_term) + r"\b", raw_text, flags=re.IGNORECASE)
                count = len(matches) if matches else text_lower.count(en_term.lower())
                w_match = 2.5 if " " in en_term else 2.0
                w_domain = 1.8
                b_sheet = 1.5 if is_placename else (1.0 if is_addon else 0.0)
                add_score(en_term, "glossary", w_match, count, w_domain, b_sheet)
                matched_glossary[en_term] = it_term

    # 3. Alias & Title Mapping
    for alias, (canonical, category) in ALIAS_MAP.items():
        if re.search(r"\b" + re.escape(alias) + r"\b", text_lower):
            matches = len(re.findall(r"\b" + re.escape(alias) + r"\b", text_lower))
            w_match = 2.2
            w_domain = 2.5 if category == "character" else (2.0 if category == "job" else 1.5)
            b_sheet = 1.5 if (is_quest and category == "character") or (is_action and category == "job") else 0.0
            add_score(canonical, category, w_match, matches, w_domain, b_sheet)

    # 4. Character Dossiers Search
    characters = get_character_dossiers()
    for char_name, char_info in characters.items():
        char_lower = char_name.lower()
        if re.search(r"\b" + re.escape(char_lower) + r"\b", text_lower):
            matches = len(re.findall(r"\b" + re.escape(char_lower) + r"\b", text_lower))
            w_match = 3.0 if char_name in raw_text else 2.5
            w_domain = 2.5
            b_sheet = 1.5 if is_quest else 0.0
            add_score(char_name, "character", w_match, matches, w_domain, b_sheet)
            relevant_characters[char_name] = char_info
        elif char_name in scores:
            # Matched via alias
            relevant_characters[char_name] = char_info
        else:
            first_name = char_name.split()[0]
            if len(first_name) >= 4 and re.search(r"\b" + re.escape(first_name.lower()) + r"\b", text_lower):
                matches = len(re.findall(r"\b" + re.escape(first_name.lower()) + r"\b", text_lower))
                w_match = 2.0
                w_domain = 2.5
                b_sheet = 1.5 if is_quest else 0.0
                add_score(char_name, "character", w_match, matches, w_domain, b_sheet)
                relevant_characters[char_name] = char_info

    # 5. Job Lore Search
    jobs_data = load_job_lore().get("jobs", {})
    for job_code, job_info in jobs_data.items():
        code_matches = re.findall(r"\b" + re.escape(job_code) + r"\b", raw_text)
        name_en = job_info.get("name_en", "")
        name_it = job_info.get("name_it", "")
        name_matched = (name_en and re.search(r"\b" + re.escape(name_en.lower()) + r"\b", text_lower)) or \
                       (name_it and re.search(r"\b" + re.escape(name_it.lower()) + r"\b", text_lower))

        if code_matches or name_matched or job_code in scores:
            count = len(code_matches) if code_matches else 1
            w_match = 3.0 if code_matches else 2.5
            w_domain = 2.0
            b_sheet = 1.5 if is_action else 0.0
            add_score(job_code, "job", w_match, count, w_domain, b_sheet)
            relevant_jobs[job_code] = job_info

    # 6. Factions & Tribal Lore Search
    factions_data = load_factions_lore()

    # Garlean Empire
    garlean_ranks = ("zos", "yae", "van", "tol", "rem", "sas")
    has_garlean_rank = any(re.search(r"\b" + r + r"\b", text_lower) for r in garlean_ranks)
    if "garlean" in text_lower or "garlemald" in text_lower or "magitek" in text_lower or "ceruleum" in text_lower or has_garlean_rank:
        matches = max(1, len(re.findall(r"\b(garlean|garlemald|magitek|ceruleum)\b", text_lower)))
        w_match = 3.0 if has_garlean_rank else 2.5
        w_domain = 2.0
        b_sheet = 1.5 if is_quest else 0.0
        add_score("Garlean Empire", "faction", w_match, matches, w_domain, b_sheet)
        relevant_factions["garlean_empire"] = factions_data.get("garlean_empire", {})

    # Ascian Overlords
    if any(k in text_lower for k in ("ascian", "zodiark", "unsundered", "convocation", "rejoining", "hades")):
        matches = max(1, len(re.findall(r"\b(ascian|ascians|zodiark|unsundered)\b", text_lower)))
        w_match = 2.5
        w_domain = 2.0
        b_sheet = 1.5 if is_quest else 0.0
        add_score("Ascian Overlords", "faction", w_match, matches, w_domain, b_sheet)
        relevant_factions["ascian_overlords"] = factions_data.get("ascian_overlords", {})

    # Allagan Empire
    if any(k in text_lower for k in ("allag", "allagan", "dalamud", "azys lla")):
        matches = max(1, len(re.findall(r"\b(allag|allagan|dalamud)\b", text_lower)))
        w_match = 2.5
        w_domain = 2.0
        b_sheet = 1.5 if is_quest else 0.0
        add_score("Allagan Empire", "faction", w_match, matches, w_domain, b_sheet)
        relevant_factions["allagan_empire"] = factions_data.get("allagan_empire", {})

    # Eorzean Alliance
    if any(k in text_lower for k in ("maelstrom", "twin adder", "immortal flames", "temple knights", "eorzean alliance")):
        w_match = 2.5
        w_domain = 2.0
        b_sheet = 1.5 if is_quest else 0.0
        add_score("Eorzean Alliance", "faction", w_match, 1, w_domain, b_sheet)
        relevant_factions["eorzean_alliance"] = factions_data.get("eorzean_alliance", {})

    # Tribal Nations & Speech Quirks with word boundary protection
    tribes = factions_data.get("tribal_nations", {})
    tribal_quirk_triggers = [
        (r"\bthese ones\b", "Sylphs"), (r"\bthis one\b", "Sylphs"),
        (r"\bkupo\b", "Moogles"), (r"\bkupo-po\b", "Moogles"),
        (r"\bgobbly\b", "Moblins"), (r"\bgobbly-talk\b", "Moblins"), (r"\bpot-making\b", "Moblins"), (r"\bfai-pentole\b", "Moblins"),
        (r"\byes-yes\b", "Kobolds"), (r"\bquick-quick\b", "Kobolds"), (r"\bbad-bad\b", "Kobolds"), (r"\bsì-sì\b", "Kobolds"), (r"\bpresto-presto\b", "Kobolds"),
        (r"\bpshhh\b", "Sahagin"), (r"\bshhh\b", "Sahagin"),
        (r"\beffendi\b", "Namazu"), (r"\byes,\s*yes!\b", "Namazu"), (r"\bno,\s*no!\b", "Namazu"),
    ]
    for pattern, tribe_name in tribal_quirk_triggers:
        if re.search(pattern, text_lower):
            w_match = 3.0
            w_domain = 2.0
            b_sheet = 1.5 if is_quest else 0.0
            add_score(f"Tribe: {tribe_name}", "faction", w_match, 1, w_domain, b_sheet)
            if tribe_name in tribes:
                relevant_factions[f"tribal_nations:{tribe_name}"] = tribes[tribe_name]

    # Loporrits -way check (word-boundary & common non-Loporrit word exclusion)
    common_way_words = {"broadway", "highway", "pathway", "doorway", "freeway", "subway", "stairway", "hallway", "gateway", "runway", "driveway", "midway", "railway", "cableway", "passageway", "anyway", "halfway", "always"}
    loporrit_match = re.search(r"\b[A-Za-z]+way\b", raw_text)
    if loporrit_match and loporrit_match.group(0).lower() not in common_way_words:
        add_score("Tribe: Loporrits", "faction", 3.0, 1, 2.0, 1.5 if is_quest else 0.0)
        if "Loporrits" in tribes:
            relevant_factions["tribal_nations:Loporrits"] = tribes["Loporrits"]

    # Moblins -making check (word-boundary)
    if re.search(r"\b(gobbly|pot)-making\b", text_lower) or re.search(r"\bfai-[a-z]+\b", text_lower):
        add_score("Tribe: Moblins", "faction", 3.0, 1, 2.0, 1.5 if is_quest else 0.0)
        if "Moblins" in tribes:
            relevant_factions["tribal_nations:Moblins"] = tribes["Moblins"]

    # Direct Tribe Name match
    for tribe_name, tribe_info in tribes.items():
        if re.search(r"\b" + re.escape(tribe_name.lower()) + r"\b", text_lower):
            add_score(f"Tribe: {tribe_name}", "faction", 2.5, 1, 2.0, 1.5 if is_quest else 0.0)
            relevant_factions[f"tribal_nations:{tribe_name}"] = tribe_info

    # 7. Expansion & Raid Story Summaries
    expansions = get_story_summaries()
    raids_8man = get_8man_raids()
    raids_24man = get_24man_raids()

    for exp_key, exp_info in expansions.items():
        title = exp_info.get("title", "")
        if title.lower() in text_lower or exp_key.lower() in text_lower:
            add_score(f"Expansion: {title}", "story", 2.5, 1, 1.5, 1.5 if is_quest else 0.0)
            relevant_stories[exp_key] = exp_info

    for raid_name, raid_info in raids_8man.items():
        raid_lower = raid_name.lower()
        raid_lig = raid_lower.replace("ae", "æ")
        if raid_lower in text_lower or raid_lig in text_lower or raid_name in scores or raid_name.replace("ae", "æ") in scores or raid_name.replace("æ", "ae") in scores:
            add_score(f"Raid: {raid_name}", "story", 2.5, 1, 1.5, 1.5 if is_quest else 0.0)
            relevant_stories[raid_name] = raid_info

    for raid_name, raid_info in raids_24man.items():
        raid_lower = raid_name.lower()
        raid_lig = raid_lower.replace("ae", "æ")
        if raid_lower in text_lower or raid_lig in text_lower or raid_name in scores or raid_name.replace("ae", "æ") in scores or raid_name.replace("æ", "ae") in scores:
            add_score(f"Raid: {raid_name}", "story", 2.5, 1, 1.5, 1.5 if is_quest else 0.0)
            relevant_stories[raid_name] = raid_info

    side_stories = get_side_storylines()
    for side_key, side_info in side_stories.items():
        stitle = side_info.get("title", "")
        if stitle.lower() in text_lower or side_key.lower() in text_lower:
            add_score(f"Side Story: {stitle}", "story", 2.5, 1, 1.5, 1.5 if is_quest else 0.0)
            relevant_stories[side_key] = side_info

    # 8. Sort & Rank Detected Entities
    detected_entities = []
    sorted_entities = sorted(scores.items(), key=lambda x: -x[1])
    for name, score in sorted_entities[:max_entities]:
        category = entity_categories.get(name, "lore")
        detected_entities.append({"name": name, "category": category, "score": score})

    relevance_scores = dict(sorted_entities[:max_entities])

    # 9. Formatted Prompt Block Construction with Budget Enforcement and Empty Header Guard
    prompt_lines = ["### CONTESTO LORE SPECIFICO PER QUESTA TRADUZIONE:"]

    # Tier 1: Glossary Terms
    if matched_glossary:
        prompt_lines.append("- TERMINI GLOSSARIO RILEVANTI:")
        for en, it in sorted(matched_glossary.items()):
            prompt_lines.append(f"  * {en} ➔ {it}")

    # Tier 2: Relevant Characters
    if relevant_characters:
        prompt_lines.append("- DOSSIER PERSONAGGI RILEVANTI:")
        for char_name, info in relevant_characters.items():
            role = info.get("role", "")
            tone = info.get("tone", "")
            guidance = info.get("italian_translation_guidance") or info.get("guidance", "")
            prompt_lines.append(f"  * {char_name} ({role}): {tone} -> {guidance}")

    # Tier 3: Factions & Job Guidance
    if relevant_factions:
        prompt_lines.append("- REGISTRI FAZIONI & TRIBÙ:")
        for f_key, f_info in relevant_factions.items():
            fname = f_info.get("name") or f_key
            guidance = f_info.get("italian_translation_guidance") or f_info.get("speech_quirks") or f_info.get("description", "")
            prompt_lines.append(f"  * {fname}: {guidance}")

    if relevant_jobs:
        prompt_lines.append("- CONTESTO CLASSI & JOB:")
        for j_code, j_info in relevant_jobs.items():
            jname = j_info.get("name_en", j_code)
            guidance = j_info.get("italian_translation_guidance") or j_info.get("narrative_context", "")
            prompt_lines.append(f"  * {j_code} ({jname}): {guidance}")

    # Tier 4: Relevant Story & Raid Summaries
    if relevant_stories:
        prompt_lines.append("- CONTESTO TRAMA & RAID:")
        for s_key, s_info in relevant_stories.items():
            stitle = s_info.get("title") or s_key
            ssummary = s_info.get("summary", "")
            prompt_lines.append(f"  * {stitle}: {ssummary}")

    if len(prompt_lines) <= 1:
        scavenged_block = ""
    else:
        scavenged_block = "\n".join(prompt_lines)

        omission_notice = "[... lore addizionale omessa per rispettare il budget di contesto]"
        if len(scavenged_block) > max_character_budget:
            while (len("\n".join(prompt_lines)) + len(omission_notice) + 1) > max_character_budget and len(prompt_lines) > 1:
                prompt_lines.pop()
            prompt_lines.append(omission_notice)
            scavenged_block = "\n".join(prompt_lines)
            if len(scavenged_block) > max_character_budget:
                scavenged_block = scavenged_block[:max_character_budget]

    return {
        "matched_glossary": matched_glossary,
        "detected_entities": detected_entities,
        "relevant_characters": relevant_characters,
        "relevant_factions": relevant_factions,
        "relevant_jobs": relevant_jobs,
        "relevant_stories": relevant_stories,
        "relevance_scores": relevance_scores,
        "scavenged_prompt_block": scavenged_block,
    }


def build_system_prompt(
    custom_glossary: Optional[dict[str, str]] = None,
    sheet_name: Optional[str] = "",
    include_story_context: bool = True,
    text: Optional[str] = "",
    max_character_budget: int = 2500,
) -> str:
    """
    Build a comprehensive, structured system prompt for Local LLMs (Ollama/LM Studio).
    Includes FFXIV Localization Persona, Lore Glossary, Story Summaries, Character Dossiers,
    Rules, and Sheet Context.

    If `text` is provided and non-empty, performs dynamic lore scavenging (`scavenge_lore_context`).
    If `text` is empty or omitted, preserves 100% backward compatibility.
    """
    sheet_name = sheet_name or ""
    text = text or ""
    sheet_context = get_sheet_context_description(sheet_name)

    if text and text.strip():
        scavenged = scavenge_lore_context(
            text=text,
            sheet_name=sheet_name,
            custom_glossary=custom_glossary,
            max_character_budget=max_character_budget,
        )
        scavenged_block = scavenged.get("scavenged_prompt_block", "")
        if scavenged_block:
            prompt = (
                "Sei un esperto localizzatore e traduttore madrelingua italiano specializzato nell'universo di Final Fantasy XIV (FFXIV).\n\n"
                f"{scavenged_block}\n\n"
                "### CONTESTO DEL FOGLIO IN TRADUZIONE:\n"
                f"{sheet_context}\n\n"
                "### REGOLE FONDAMENTALI DI TRADUZIONE:\n"
                "1. Traduci l'inglese in un italiano naturale, fluido ed elegante, mantenendo il registro fantasy adatto al contesto.\n"
                "2. PRESERVA TASSATIVAMENTE tutti i segnaposto tipo {0}, {1}, VAR0, VAR1 o tag di codice senza alterarli, spostarli o eliminarli.\n"
                "3. Se la riga è un comando o elemento di UI (come in Addon), mantieni la traduzione sintetica (es. verbi all'infinito).\n"
                "4. Restituisci ESCLUSIVAMENTE la traduzione in italiano, senza spiegazioni, note o commenti introduttivi."
            )
            return prompt

    # Backward compatible static prompt building when text=""
    glossary = get_active_glossary(custom_glossary)

    glossary_lines = [f"- {en} ➔ {it}" for en, it in sorted(glossary.items())]
    glossary_str = "\n".join(glossary_lines)

    story_block = ""
    if include_story_context and any(sheet_name.startswith(p) for p in ("Quest", "CustomTalk", "NpcYell", "Cutscene", "DefaultTalk")):
        expansions = get_story_summaries()
        exp_lines = [f"- **{exp['title']}**: {exp['summary']}" for exp in expansions.values()]
        exp_str = "\n".join(exp_lines[:6])

        characters = get_character_dossiers()
        char_lines = [f"- **{name}** ({info['role']}): {info['tone']} -> {info['guidance']}" for name, info in list(characters.items())[:8]]
        char_str = "\n".join(char_lines)

        story_block = (
            "\n### SINTESI DELLA TRAMA & EVENTI DI FFXIV:\n"
            f"{exp_str}\n\n"
            "### DOSSIER PERSONAGGI & REGISTRI LINGUISTICI:\n"
            f"{char_str}\n"
        )

    prompt = (
        "Sei un esperto localizzatore e traduttore madrelingua italiano specializzato nell'universo di Final Fantasy XIV (FFXIV).\n\n"
        "### KNOWLEDGE BASE LORE & GLOSSARIO FFXIV:\n"
        f"{glossary_str}\n"
        f"{story_block}\n"
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
            if "glossary" in data:
                return {str(k): str(v) for k, v in data["glossary"].items()}
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def save_custom_glossary(file_path: Path, glossary: dict[str, str]):
    """Save a custom user glossary to JSON file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"glossary": glossary}
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job_lore() -> dict:
    """Load FFXIV combat and crafting/gathering job lore from package resource JSON."""
    resource_path = Path(__file__).parent.parent / "resources" / "ffxiv_job_lore.json"
    if resource_path.exists():
        try:
            return json.loads(resource_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"jobs": {}}


def get_job_lore(job_code_or_name: str = "") -> dict:
    """Return dictionary of job lore entries or a specific job entry if key provided."""
    data = load_job_lore()
    jobs = data.get("jobs", {})
    if not job_code_or_name:
        return jobs
    key_upper = job_code_or_name.upper()
    if key_upper in jobs:
        return jobs[key_upper]
    for job in jobs.values():
        if job.get("name_en", "").lower() == job_code_or_name.lower() or job.get("name_it", "").lower() == job_code_or_name.lower():
            return job
    return {}


def load_factions_lore() -> dict:
    """Load FFXIV factions, empire hierarchies, and tribal lore from package resource JSON."""
    resource_path = Path(__file__).parent.parent / "resources" / "ffxiv_factions_lore.json"
    if resource_path.exists():
        try:
            return json.loads(resource_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def get_factions_lore(faction_key: str = "") -> dict:
    """Return complete factions lore dictionary or specific faction section."""
    data = load_factions_lore()
    if not faction_key:
        return data
    return data.get(faction_key, {})


def get_8man_raids() -> dict[str, dict]:
    """Return dictionary of 8-man raid series summaries and key NPCs."""
    dossier = load_story_dossier()
    return dossier.get("raids_8man", {})


def get_24man_raids() -> dict[str, dict]:
    """Return dictionary of 24-man raid series summaries and key NPCs."""
    dossier = load_story_dossier()
    return dossier.get("raids_24man", {})


def get_patch_storylines() -> dict[str, dict]:
    """Return dictionary of patch storylines (2.1-2.5, 3.1-3.5, etc.)."""
    dossier = load_story_dossier()
    return dossier.get("patches", {})



