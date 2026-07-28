"""
Empirical Test Harness for scavenge_lore_context()
==================================================
Evaluates 20+ complex sentence strings with combinations of characters,
raids, jobs, factions, and tribal quirks. Asserts structure, entity detection,
relevance scoring, and character budget enforcement.
Also probes edge cases, false positives, and potential failure modes.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from interpresona.core.lore_kb import scavenge_lore_context


class TestScavengeLoreContextHarness(unittest.TestCase):
    """Empirical Test Harness & Challenge Suite for Lore Scavenger Engine."""

    EXPECTED_KEYS = {
        "matched_glossary",
        "detected_entities",
        "relevant_characters",
        "relevant_factions",
        "relevant_jobs",
        "relevant_stories",
        "relevance_scores",
        "scavenged_prompt_block",
    }

    def _assert_dict_structure(self, res: dict):
        self.assertIsInstance(res, dict)
        self.assertEqual(set(res.keys()), self.EXPECTED_KEYS)
        self.assertIsInstance(res["matched_glossary"], dict)
        self.assertIsInstance(res["detected_entities"], list)
        self.assertIsInstance(res["relevant_characters"], dict)
        self.assertIsInstance(res["relevant_factions"], dict)
        self.assertIsInstance(res["relevant_jobs"], dict)
        self.assertIsInstance(res["relevant_stories"], dict)
        self.assertIsInstance(res["relevance_scores"], dict)
        self.assertIsInstance(res["scavenged_prompt_block"], str)

    # -------------------------------------------------------------------------
    # 20+ Complex Sentence Evaluation Tests
    # -------------------------------------------------------------------------

    def test_01_emet_alphinaud_crystal_tower_garlean(self):
        text = "Emet-Selch confronted Alphinaud near the Crystal Tower while the Garlean Empire deployed magitek forces."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("Emet-Selch", res["relevant_characters"])
        self.assertIn("Alphinaud", res["relevant_characters"])
        self.assertIn("Crystal Tower", res["matched_glossary"])
        self.assertIn("garlean_empire", res["relevant_factions"])

    def test_02_pld_whm_alexander_mappingway_kupo(self):
        text = "The PLD and WHM prepared for Alexander raid alongside Mappingway, who hummed kupo to herself."
        res = scavenge_lore_context(text, sheet_name="Action_01")
        self._assert_dict_structure(res)
        self.assertIn("PLD", res["relevant_jobs"])
        self.assertIn("WHM", res["relevant_jobs"])
        self.assertIn("Alexander", res["relevant_stories"])
        self.assertIn("tribal_nations:Loporrits", res["relevant_factions"])
        self.assertIn("tribal_nations:Moogles", res["relevant_factions"])

    def test_03_ascian_rejoining_allagan_syrcus(self):
        text = "Ascian overlords orchestrated the Rejoining using Allagan technology from Syrcus Tower."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("ascian_overlords", res["relevant_factions"])
        self.assertIn("allagan_empire", res["relevant_factions"])
        self.assertIn("Crystal Tower", res["relevant_stories"])  # Syrcus Tower maps to Crystal Tower

    def test_04_sylphs_these_ones_pct_garlean(self):
        text = "These ones ask the Warrior of Light and PCT to protect the Sylphs from the Garlean Empire."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Sylphs", res["relevant_factions"])
        self.assertIn("PCT", res["relevant_jobs"])
        self.assertIn("garlean_empire", res["relevant_factions"])
        self.assertIn("Warrior of Light", res["matched_glossary"])

    def test_05_livingway_growingway_thancred_eden_urianger(self):
        text = "Livingway and Growingway assisted Thancred in Eden while Urianger researched Aether."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Loporrits", res["relevant_factions"])
        self.assertIn("Thancred", res["relevant_characters"])
        self.assertIn("Urianger", res["relevant_characters"])
        self.assertIn("Eden", res["relevant_stories"])
        self.assertIn("Aether", res["matched_glossary"])

    def test_06_crystal_exarch_graha_omega_estinien(self):
        text = "The Crystal Exarch met G'raha Tia's legacy in the Omega protocol alongside Estinien."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("G'raha Tia", res["relevant_characters"])
        self.assertIn("Estinien", res["relevant_characters"])
        self.assertIn("Omega", res["relevant_stories"])

    def test_07_garlean_ranks_eorzean_alliance(self):
        text = "Zos van Garlemald commanded the magitek armor against the Eorzean Alliance."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("garlean_empire", res["relevant_factions"])
        self.assertIn("eorzean_alliance", res["relevant_factions"])

    def test_08_sahagin_kobold_quirks(self):
        text = "Pshhh! The Sahagin elder summoned Leviathan while bad-bad Kobolds fled yes-yes!"
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Sahagin", res["relevant_factions"])
        self.assertIn("tribal_nations:Kobolds", res["relevant_factions"])

    def test_09_moblins_namazu_azys_lla(self):
        text = "Gobbly-talk pot-making Moblins traded with effendi Namazu near Azys Lla."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Moblins", res["relevant_factions"])
        self.assertIn("tribal_nations:Namazu", res["relevant_factions"])
        self.assertIn("allagan_empire", res["relevant_factions"])

    def test_10_hades_scions_alisaie_krile(self):
        text = "Hades unleashed Ascian magic upon the Scions of the Seventh Dawn, but Alisaie and Krile stood firm."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("Emet-Selch", res["relevant_characters"])  # via Hades alias
        self.assertIn("Alisaie", res["relevant_characters"])
        self.assertIn("Krile", res["relevant_characters"])
        self.assertIn("ascian_overlords", res["relevant_factions"])
        self.assertIn("Scions of the Seventh Dawn", res["matched_glossary"])

    def test_11_rpr_vpr_dnc_pandaemonium_unsundered(self):
        text = "The RPR, VPR, and DNC joined forces in Pandaemonium to fight the Unsundered."
        res = scavenge_lore_context(text, sheet_name="Action_01")
        self._assert_dict_structure(res)
        self.assertIn("RPR", res["relevant_jobs"])
        self.assertIn("VPR", res["relevant_jobs"])
        self.assertIn("DNC", res["relevant_jobs"])
        self.assertIn("Pandaemonium", res["relevant_stories"])
        self.assertIn("ascian_overlords", res["relevant_factions"])

    def test_12_zodiark_dalamud_coil_of_bahamut(self):
        text = "Zodiark's shadow fell upon Dalamud during the Coil of Bahamut raid."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("ascian_overlords", res["relevant_factions"])
        self.assertIn("allagan_empire", res["relevant_factions"])
        self.assertIn("Coil of Bahamut", res["relevant_stories"])

    def test_13_moblins_fai_pentole_sge_gnb(self):
        text = "Fai-pentole Moblins worked with SGE and GNB to restore the Aetherial stream."
        res = scavenge_lore_context(text, sheet_name="Action_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Moblins", res["relevant_factions"])
        self.assertIn("SGE", res["relevant_jobs"])
        self.assertIn("GNB", res["relevant_jobs"])

    def test_14_yshtola_alphinaud_twin_adder(self):
        text = "Y'shtola investigated the Crystal Tower while Alphinaud conferred with the Twin Adder."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("Y'shtola", res["relevant_characters"])
        self.assertIn("Alphinaud", res["relevant_characters"])
        self.assertIn("Crystal Tower", res["matched_glossary"])
        self.assertIn("eorzean_alliance", res["relevant_factions"])

    def test_15_singingway_dash_way_pct(self):
        text = "Singingway said '-way is the Loporrits manner' while PCT painted the moon."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Loporrits", res["relevant_factions"])
        self.assertIn("PCT", res["relevant_jobs"])

    def test_16_maelstrom_immortal_flames_garlean(self):
        text = "The Maelstrom and Immortal Flames held the line against Garlean Empire legati yae van sas."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("eorzean_alliance", res["relevant_factions"])
        self.assertIn("garlean_empire", res["relevant_factions"])

    def test_17_multi_character_eden_raid(self):
        text = "Emet-Selch, Thancred, Urianger, Y'shtola, Alisaie, Alphinaud, Estinien, G'raha Tia, Krile, and Ryne fought in Eden."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertGreaterEqual(len(res["relevant_characters"]), 8)
        self.assertIn("Eden", res["relevant_stories"])

    def test_18_multi_tribe_quirks_garlemald(self):
        text = "These ones find that kupo-po moogles and quick-quick kobolds avoid Garlemald ceruleum."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self._assert_dict_structure(res)
        self.assertIn("tribal_nations:Sylphs", res["relevant_factions"])
        self.assertIn("tribal_nations:Moogles", res["relevant_factions"])
        self.assertIn("tribal_nations:Kobolds", res["relevant_factions"])
        self.assertIn("garlean_empire", res["relevant_factions"])

    def test_19_magic_jobs_alexander_ascian(self):
        text = "BLM, SMN, RDM, and BLU cast spells near Alexander, while the Ascian watched."
        res = scavenge_lore_context(text, sheet_name="Action_01")
        self._assert_dict_structure(res)
        self.assertIn("BLM", res["relevant_jobs"])
        self.assertIn("SMN", res["relevant_jobs"])
        self.assertIn("RDM", res["relevant_jobs"])
        self.assertIn("BLU", res["relevant_jobs"])
        self.assertIn("Alexander", res["relevant_stories"])
        self.assertIn("ascian_overlords", res["relevant_factions"])

    def test_20_massive_lore_budget_stress(self):
        characters = "Emet-Selch Alphinaud Thancred Y'shtola Urianger G'raha Tia Estinien Alisaie Krile Ryne "
        raids = "Alexander Eden Crystal Tower Omega Pandæmonium "
        jobs = "PLD WHM PCT BLM SMN RDM BLU GNB SGE RPR VPR DNC MNK DRG "
        factions = "Garlean Empire Ascian Allagan Eorzean Alliance Sylphs Moogles Moblins Kobolds Loporrits "
        text = (characters + raids + jobs + factions) * 3
        res = scavenge_lore_context(text, sheet_name="Quest_01", max_character_budget=2500)
        self._assert_dict_structure(res)

    def test_21_empty_and_whitespace_input(self):
        res_empty = scavenge_lore_context("")
        self._assert_dict_structure(res_empty)
        self.assertEqual(res_empty["scavenged_prompt_block"], "")
        self.assertEqual(len(res_empty["detected_entities"]), 0)

        res_spaces = scavenge_lore_context("   \n\t  ")
        self._assert_dict_structure(res_spaces)
        self.assertEqual(res_spaces["scavenged_prompt_block"], "")

    def test_22_sheet_weighting_relevance_scores(self):
        text = "PLD Emet-Selch"
        res_action = scavenge_lore_context(text, sheet_name="Action_01")
        res_quest = scavenge_lore_context(text, sheet_name="Quest_01")
        pld_action_score = res_action["relevance_scores"].get("PLD", 0)
        pld_quest_score = res_quest["relevance_scores"].get("PLD", 0)
        emet_action_score = res_action["relevance_scores"].get("Emet-Selch", 0)
        emet_quest_score = res_quest["relevance_scores"].get("Emet-Selch", 0)

        self.assertGreater(pld_action_score, pld_quest_score)
        self.assertGreater(emet_quest_score, emet_action_score)


class TestScavengeAdversarialFindings(unittest.TestCase):
    """Adversarial challenge test suite to empirically reproduce bugs & limitations."""

    def test_finding_1_garlean_magitek_ceruleum_trigger_defect(self):
        """
        Empirically verifies that mentioning 'magitek' or 'ceruleum' without 'garlean'/'garlemald'/rank
        fails to detect the Garlean Empire faction.
        """
        text = "The magitek warmachines were powered by ceruleum fuel."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        # garlean_empire is now correctly triggered by magitek/ceruleum
        self.assertIn("garlean_empire", res["relevant_factions"])

    def test_finding_2_loporrit_way_false_positive(self):
        """
        Verifies that standard English capitalized words ending in 'way' (e.g. Subway, Highway)
        do NOT falsely trigger Tribe: Loporrits.
        """
        text = "We took the Subway to the Broadway station."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertNotIn("tribal_nations:Loporrits", res["relevant_factions"])

    def test_finding_3_sahagin_shhh_false_positive(self):
        """
        Empirically verifies that common English interjection 'shhh' triggers Tribe: Sahagin.
        """
        text = "Shhh! Please speak quietly in the library."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("tribal_nations:Sahagin", res["relevant_factions"])

    def test_finding_4_sylph_this_one_false_positive(self):
        """
        Empirically verifies that common English phrase 'this one' triggers Tribe: Sylphs.
        """
        text = "This one is the preferred choice for translation."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertIn("tribal_nations:Sylphs", res["relevant_factions"])

    def test_finding_5_moblin_decision_making_false_positive(self):
        """
        Verifies that hyphenated English words like 'decision-making' do NOT falsely trigger Tribe: Moblins.
        """
        text = "The committee completed their decision-making process."
        res = scavenge_lore_context(text, sheet_name="Quest_01")
        self.assertNotIn("tribal_nations:Moblins", res["relevant_factions"])

    def test_finding_6_character_budget_truncation_overflow(self):
        """
        Verifies character budget enforcement:
        Total scavenged prompt block length must never exceed max_character_budget.
        """
        text = "Emet-Selch and Alphinaud and Thancred and Y'shtola and Urianger and G'raha Tia and Estinien and Alisaie and Krile and Ryne"
        budget = 350
        res = scavenge_lore_context(text, sheet_name="Quest_01", max_character_budget=budget)
        block = res["scavenged_prompt_block"]
        # Total block length must strictly satisfy budget limit
        self.assertLessEqual(len(block), budget)


if __name__ == "__main__":
    unittest.main()
