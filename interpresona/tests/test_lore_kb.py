"""
Unit Tests for FFXIV Lore Knowledge Base & Local LLM Translator Integration
============================================================================
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from interpresona.core.lore_kb import (
    load_resource_glossary,
    get_active_glossary,
    get_sheet_context_description,
    build_system_prompt,
    load_custom_glossary,
    save_custom_glossary,
    scavenge_lore_context,
)
from interpresona.core.translator import LocalLLMTranslator


class TestLoreKnowledgeBase(unittest.TestCase):

    def test_load_resource_glossary(self):
        glossary = load_resource_glossary()
        self.assertIsInstance(glossary, dict)
        self.assertIn("Scions of the Seventh Dawn", glossary)
        self.assertEqual(glossary["Scions of the Seventh Dawn"], "Eredi della Settima Alba")
        self.assertIn("Aether", glossary)
        self.assertEqual(glossary["Aether"], "Etere")

    def test_get_active_glossary_override(self):
        custom = {"Scions of the Seventh Dawn": "Scion dell'Alba Custom", "NewTerm": "NuovoTermine"}
        active = get_active_glossary(custom)
        self.assertEqual(active["Scions of the Seventh Dawn"], "Scion dell'Alba Custom")
        self.assertEqual(active["NewTerm"], "NuovoTermine")
        self.assertEqual(active["Aether"], "Etere")

    def test_sheet_context_descriptions(self):
        addon_desc = get_sheet_context_description("Addon")
        self.assertIn("Interfaccia Utente", addon_desc)

        quest_desc = get_sheet_context_description("Quest_12345")
        self.assertIn("Quest", quest_desc)

        unknown_desc = get_sheet_context_description("UnknownSheet")
        self.assertIn("generici", unknown_desc)

    def test_build_system_prompt(self):
        prompt = build_system_prompt(sheet_name="Addon")
        self.assertIn("Final Fantasy XIV", prompt)
        self.assertIn("Interfaccia Utente", prompt)
        self.assertIn("Eredi della Settima Alba", prompt)
        self.assertIn("PRESERVA TASSATIVAMENTE", prompt)

    def test_custom_glossary_save_load(self):
        test_file = Path(__file__).parent / "tmp_test_glossary.json"
        try:
            data = {"TermA": "TradA", "TermB": "TradB"}
            save_custom_glossary(test_file, data)
            loaded = load_custom_glossary(test_file)
            self.assertEqual(loaded, data)
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_local_llm_translator_init(self):
        translator = LocalLLMTranslator(
            endpoint="http://localhost:11434/v1",
            model_name="qwen2.5:7b",
            sheet_name="Quest",
        )
        self.assertEqual(translator.name, "Local LLM (Ollama / LM Studio)")
        self.assertEqual(translator._model, "qwen2.5:7b")
        self.assertEqual(translator._sheet_name, "Quest")

        # Dynamic sheet name update
        translator.set_sheet_name("Addon")
        self.assertEqual(translator._sheet_name, "Addon")


    def test_story_dossier_loading(self):
        from interpresona.core.lore_kb import get_story_summaries, get_character_dossiers
        summaries = get_story_summaries()
        self.assertIn("ARR", summaries)
        self.assertIn("Dawntrail", summaries["DT"]["title"])

        characters = get_character_dossiers()
        self.assertIn("Alphinaud", characters)
        self.assertIn("Emet-Selch", characters)

    def test_build_system_prompt_narrative_story(self):
        prompt = build_system_prompt(sheet_name="Quest_MainScenario")
        self.assertIn("SINTESI DELLA TRAMA", prompt)
        self.assertIn("DOSSIER PERSONAGGI", prompt)
        self.assertIn("Alphinaud", prompt)
        self.assertIn("Heavensward", prompt)

    def test_expanded_glossary_count_and_terms(self):
        glossary = load_resource_glossary()
        self.assertGreaterEqual(len(glossary), 180)
        self.assertIn("Pictomancer", glossary)
        self.assertEqual(glossary["Pictomancer"], "Pittomante")
        self.assertIn("Solution Nine", glossary)
        self.assertIn("Binding Coil of Bahamut", glossary)
        self.assertEqual(glossary["Binding Coil of Bahamut"], "Spira di Bahamut")

    def test_story_dossier_expanded_schema(self):
        from interpresona.core.lore_kb import (
            get_story_summaries,
            get_character_dossiers,
            get_8man_raids,
            get_24man_raids,
            get_patch_storylines,
        )
        summaries = get_story_summaries()
        self.assertEqual(len(summaries), 6)
        self.assertIn("ARR", summaries)
        self.assertIn("DT", summaries)

        patches = get_patch_storylines()
        self.assertGreaterEqual(len(patches), 6)
        self.assertIn("2.1_2.5", patches)

        raids_8man = get_8man_raids()
        self.assertEqual(len(raids_8man), 6)
        self.assertIn("Coil of Bahamut", raids_8man)
        self.assertIn("Arcadion", raids_8man)

        raids_24man = get_24man_raids()
        self.assertEqual(len(raids_24man), 5)
        self.assertIn("Crystal Tower", raids_24man)
        self.assertIn("Myths of the Realm", raids_24man)

        characters = get_character_dossiers()
        self.assertGreaterEqual(len(characters), 35)

        # Spot check required schema fields for character dossiers
        sample_char = characters["Alphinaud"]
        self.assertIn("role", sample_char)
        self.assertIn("tone", sample_char)
        self.assertIn("guidance", sample_char)
        self.assertIn("speech_register", sample_char)
        self.assertIn("personality_traits", sample_char)
        self.assertIn("expansions", sample_char)
        self.assertIn("italian_translation_guidance", sample_char)

    def test_job_lore_dataset(self):
        from interpresona.core.lore_kb import load_job_lore, get_job_lore
        data = load_job_lore()
        self.assertIn("jobs", data)
        jobs = data["jobs"]
        self.assertEqual(len(jobs), 33)

        # Check combat job
        pld = get_job_lore("PLD")
        self.assertEqual(pld["name_en"], "Paladin")
        self.assertEqual(pld["name_it"], "Paladino")
        self.assertEqual(pld["role_category"], "Difensore")
        self.assertIn("key_npcs", pld)
        self.assertIn("italian_translation_guidance", pld)

        # Check crafter / gatherer
        crp = get_job_lore("CRP")
        self.assertEqual(crp["name_en"], "Carpenter")
        self.assertEqual(crp["role_category"], "Discepolo della Mano")

        btn = get_job_lore("Botanist")
        self.assertEqual(btn["abbreviation"], "BTN")
        self.assertEqual(btn["role_category"], "Discepolo della Terra")

    def test_factions_lore_dataset(self):
        from interpresona.core.lore_kb import load_factions_lore, get_factions_lore
        factions = load_factions_lore()
        self.assertIn("garlean_empire", factions)
        self.assertIn("ascian_overlords", factions)
        self.assertIn("allagan_empire", factions)
        self.assertIn("eorzean_alliance", factions)
        self.assertIn("tribal_nations", factions)

        tribes = get_factions_lore("tribal_nations")
        self.assertEqual(len(tribes), 16)
        self.assertIn("Sylphs", tribes)
        self.assertIn("speech_quirks", tribes["Sylphs"])
        self.assertIn("italian_translation_guidance", tribes["Sylphs"])
        self.assertIn("Loporrits", tribes)
        self.assertIn("Moblins", tribes)

    def test_scavenge_lore_context_basic_entities(self):
        text = "Emet-Selch and the Crystal Tower in Alexander"
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("Crystal Tower", scavenged["matched_glossary"])
        self.assertEqual(scavenged["matched_glossary"]["Crystal Tower"], "Torre di Cristallo")
        self.assertIn("Emet-Selch", scavenged["relevant_characters"])
        self.assertIn("Alexander", scavenged["relevant_stories"])
        self.assertGreater(len(scavenged["detected_entities"]), 0)
        self.assertIn("Emet-Selch", scavenged["scavenged_prompt_block"])
        self.assertIn("Crystal Tower", scavenged["scavenged_prompt_block"])

    def test_scavenge_lore_context_job_codes(self):
        text = "The PLD protected the WHM during the trial"
        scavenged = scavenge_lore_context(text, sheet_name="Action_01")
        self.assertIn("PLD", scavenged["relevant_jobs"])
        self.assertIn("WHM", scavenged["relevant_jobs"])
        self.assertGreaterEqual(scavenged["relevance_scores"].get("PLD", 0), 5.0)
        self.assertIn("PLD", scavenged["scavenged_prompt_block"])
        self.assertIn("WHM", scavenged["scavenged_prompt_block"])

    def test_scavenge_lore_context_tribal_speech_quirks(self):
        text = "These ones ask the Warrior of Light for aid."
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("tribal_nations:Sylphs", scavenged["relevant_factions"])
        self.assertIn("Warrior of Light", scavenged["matched_glossary"])

        text2 = "Livingway and Singingway prepared the moon, kupo!"
        scavenged2 = scavenge_lore_context(text2, sheet_name="Quest_01")
        self.assertIn("tribal_nations:Loporrits", scavenged2["relevant_factions"])
        self.assertIn("tribal_nations:Moogles", scavenged2["relevant_factions"])

    def test_scavenge_lore_context_alias_mapping(self):
        text = "The Crystal Exarch retreated to Syrcus Tower to battle Hades."
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("G'raha Tia", scavenged["relevant_characters"])
        self.assertIn("Emet-Selch", scavenged["relevant_characters"])
        self.assertIn("Crystal Tower", scavenged["relevant_stories"])

    def test_scavenge_lore_context_sheet_weighting(self):
        text = "The PLD protected Emet-Selch"
        scavenged_action = scavenge_lore_context(text, sheet_name="Action_01")
        scavenged_quest = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertGreater(scavenged_action["relevance_scores"].get("PLD", 0), scavenged_quest["relevance_scores"].get("PLD", 0))
        self.assertGreater(scavenged_quest["relevance_scores"].get("Emet-Selch", 0), scavenged_action["relevance_scores"].get("Emet-Selch", 0))

    def test_build_system_prompt_with_text(self):
        text = "Emet-Selch and the Crystal Tower in Alexander"
        prompt = build_system_prompt(sheet_name="Quest_01", text=text)
        self.assertIn("CONTESTO LORE SPECIFICO PER QUESTA TRADUZIONE", prompt)
        self.assertIn("Emet-Selch", prompt)
        self.assertIn("Crystal Tower", prompt)
        self.assertIn("Alexander", prompt)
        self.assertIn("REGOLE FONDAMENTALI DI TRADUZIONE", prompt)

    def test_scavenge_lore_budget_truncation(self):
        text = "Emet-Selch and Alphinaud and Thancred and Y'shtola and Urianger and G'raha Tia and Estinien and Alisaie and Krile and Tataru"
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01", max_character_budget=300)
        self.assertLessEqual(len(scavenged["scavenged_prompt_block"]), 300)
        self.assertIn("[... lore addizionale omessa per rispettare il budget di contesto]", scavenged["scavenged_prompt_block"])

    def test_sheet_name_and_text_none_handling(self):
        desc = get_sheet_context_description(None)
        self.assertEqual(desc, "Testo generico di gioco.")

        scavenged = scavenge_lore_context(None, sheet_name=None)
        self.assertEqual(scavenged["scavenged_prompt_block"], "")
        self.assertEqual(scavenged["detected_entities"], [])

        prompt = build_system_prompt(sheet_name=None, text=None)
        self.assertIn("Final Fantasy XIV", prompt)
        self.assertIn("Testo generico di gioco", prompt)

    def test_empty_matches_no_dangling_header(self):
        text = "This is a random sentence without any FFXIV lore elements."
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertEqual(scavenged["scavenged_prompt_block"], "")
        self.assertNotIn("CONTESTO LORE SPECIFICO PER QUESTA TRADUZIONE", scavenged["scavenged_prompt_block"])

    def test_active_proper_noun_and_job_code_matching(self):
        text = "Estinien and Thancred met with the SAM in Gridania."
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("Estinien", scavenged["relevant_characters"])
        self.assertIn("Thancred", scavenged["relevant_characters"])
        self.assertIn("SAM", scavenged["relevant_jobs"])
        self.assertIn("Gridania", scavenged["matched_glossary"])

    def test_garlean_magitek_ceruleum_and_pandæmonium_ligature(self):
        text = "The imperial legion operated magitek engines powered by ceruleum."
        scavenged = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("garlean_empire", scavenged["relevant_factions"])

        text_liga = "The warriors descended into Pandæmonium."
        scavenged_liga = scavenge_lore_context(text_liga, sheet_name="Quest_01")
        self.assertIn("Pandaemonium", scavenged_liga["relevant_stories"])

    def test_word_boundary_tribal_quirk_matching(self):
        # Common words containing 'way' or 'making' should not trigger tribes
        text_common = "The team discussed the decision-making process for the Broadway event on the highway."
        scavenged_common = scavenge_lore_context(text_common, sheet_name="Quest_01")
        self.assertNotIn("tribal_nations:Loporrits", scavenged_common["relevant_factions"])
        self.assertNotIn("tribal_nations:Moblins", scavenged_common["relevant_factions"])

        # Genuine speech quirks / names should trigger tribes
        text_tribal = "Livingway prepared the gobbly-making pot, kupo!"
        scavenged_tribal = scavenge_lore_context(text_tribal, sheet_name="Quest_01")
        self.assertIn("tribal_nations:Loporrits", scavenged_tribal["relevant_factions"])
        self.assertIn("tribal_nations:Moblins", scavenged_tribal["relevant_factions"])
        self.assertIn("tribal_nations:Moogles", scavenged_tribal["relevant_factions"])

    def test_local_llm_translator_lore_scavenging_entities(self):
        from unittest.mock import patch
        translator = LocalLLMTranslator(sheet_name="Quest_01")

        captured_prompts = []
        captured_texts = []

        def fake_raw_chat(sys_prompt, user_text):
            captured_prompts.append(sys_prompt)
            captured_texts.append(user_text)
            return f"Traduzione per {user_text}"

        with patch.object(LocalLLMTranslator, "_raw_chat_request", side_effect=fake_raw_chat):
            input_text = "Emet-Selch visited the Crystal Tower in Garlemald while Bahamut and Alphinaud watched."
            res = translator.translate([input_text])

            self.assertEqual(len(captured_prompts), 1)
            sys_prompt = captured_prompts[0]

            self.assertIn("CONTESTO LORE SPECIFICO PER QUESTA TRADUZIONE", sys_prompt)
            self.assertIn("Emet-Selch", sys_prompt)
            self.assertIn("Crystal Tower", sys_prompt)
            self.assertIn("Garlemald", sys_prompt)
            self.assertIn("Bahamut", sys_prompt)
            self.assertIn("Alphinaud", sys_prompt)
            self.assertIn("REGOLE FONDAMENTALI DI TRADUZIONE", sys_prompt)

    def test_local_llm_translator_lore_scavenging_edge_cases(self):
        from unittest.mock import patch
        translator = LocalLLMTranslator(sheet_name="Quest_MainScenario")

        captured_prompts = []
        captured_texts = []

        def fake_raw_chat(sys_prompt, user_text):
            captured_prompts.append(sys_prompt)
            captured_texts.append(user_text)
            return "Testo tradotto"

        with patch.object(LocalLLMTranslator, "_raw_chat_request", side_effect=fake_raw_chat):
            # Text without lore entities (generic English)
            generic_text = "The quick brown fox jumps over the lazy dog."
            res_generic = translator.translate([generic_text])
            self.assertEqual(len(captured_prompts), 1)
            sys_prompt_generic = captured_prompts[0]
            self.assertNotIn("CONTESTO LORE SPECIFICO PER QUESTA TRADUZIONE", sys_prompt_generic)
            self.assertIn("Final Fantasy XIV", sys_prompt_generic)

            captured_prompts.clear()
            captured_texts.clear()

            # Empty strings and bypass strings
            empty_and_bypass_texts = ["", "   ", "{0}", "{0}{1}", "123", "LV"]
            res_bypass = translator.translate(empty_and_bypass_texts)
            self.assertEqual(len(captured_prompts), 0)
            self.assertEqual(res_bypass, empty_and_bypass_texts)

    def test_local_llm_translator_custom_sheet_names_and_masked_placeholders(self):
        from unittest.mock import patch
        translator = LocalLLMTranslator(
            sheet_name="NpcYell_9999",
            custom_glossary={"Crystal Tower": "Torre Cristallina Custom"},
        )

        captured_prompts = []
        captured_texts = []

        def fake_raw_chat(sys_prompt, user_text):
            captured_prompts.append(sys_prompt)
            captured_texts.append(user_text)
            return f"Emet-Selch e (VAR0) sono vicino alla {user_text}"

        with patch.object(LocalLLMTranslator, "_raw_chat_request", side_effect=fake_raw_chat):
            input_text = "Emet-Selch and {0} went to the Crystal Tower."
            res = translator.translate([input_text])

            self.assertEqual(len(captured_prompts), 1)
            sys_prompt = captured_prompts[0]
            user_text = captured_texts[0]

            self.assertIn("CONTESTO DEL FOGLIO IN TRADUZIONE", sys_prompt)
            self.assertIn("NpcYell_9999", sys_prompt)
            self.assertIn("Torre Cristallina Custom", sys_prompt)
            self.assertIn("VAR0", user_text)
            self.assertNotIn("{0}", user_text)
            self.assertIn("{0}", res[0])


if __name__ == "__main__":
    unittest.main()



