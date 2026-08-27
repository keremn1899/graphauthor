"""Seed datasets for tests and local fixtures.

Node tuples: (id, label, text_content, token_count)
  Extended format: (id, label, text_content, token_count, semantic_anchor, is_metanode, linked_graph_id)
  Short form (4 elements): anchor="", is_metanode=False, linked_graph_id="" are used as defaults.
Edge tuples: (src_id, dst_id, sst_type, label)
  sst_type ∈ {'leadsto', 'contains', 'expresses', 'nearto'}
  label    — short verb phrase: what this edge would be in a standard KG

SST Mapping reference:
  LEADSTO   — Temporal, causal, sequential, dependency
  CONTAINS  — Spatial, hierarchical, membership, classification
  EXPRESSES — Property, attribute, state, possession, role
  NEARTO    — Similarity, alliance, symmetry (seed one-way; queried undirected)
"""

from __future__ import annotations


def _tok(text: str) -> int:
    """Rough token estimate: ~0.75 words per token."""
    return max(1, len(text.split()) * 4 // 3)


# ---------------------------------------------------------------------------
# Dataset 1: AI History
# ---------------------------------------------------------------------------

def get_ai_history_data():
    nodes_raw = [
        ("ai", "Artificial Intelligence",
         "# Artificial Intelligence (AI)\n\nArtificial Intelligence is the intelligence of machines or software, as opposed to the intelligence of humans or animals. It is a field of study in computer science that develops and studies intelligent machines. "
         "AI applications include reasoning, learning, planning, perception, and natural language understanding."),
        ("turing_test", "The Turing Test",
         "# The Turing Test\n\nProposed by Alan Turing in 1950, the Turing Test is a measure of a machine's ability to exhibit intelligent behaviour indistinguishable from a human. "
         "A human evaluator judges natural language conversations between a human and a machine. If the evaluator cannot reliably tell the machine from the human, the machine is said to have passed."),
        ("machine_learning", "Machine Learning",
         "# Machine Learning (ML)\n\nMachine Learning is a subset of AI that gives systems the ability to automatically learn and improve from experience without being explicitly programmed. "
         "It focuses on developing computer programs that can access data and use it to learn for themselves."),
        ("deep_learning", "Deep Learning",
         "# Deep Learning\n\nA subset of ML based on artificial neural networks with representation learning. Learning can be supervised, semi-supervised, or unsupervised. "
         "Deep learning architectures include deep neural networks, recurrent neural networks, and convolutional neural networks."),
        ("transformer", "Transformer Architecture",
         "# Transformer Architecture\n\nA deep learning architecture introduced in the 2017 paper 'Attention Is All You Need'. "
         "It relies entirely on self-attention mechanisms to compute representations of its input and output without using sequence-aligned RNNs or convolutions. "
         "The Transformer has become the dominant architecture for NLP tasks."),
        ("llm", "Large Language Models",
         "# Large Language Models (LLMs)\n\nLLMs are foundational AI models typically built on the Transformer architecture, trained on massive text corpora. "
         "They exhibit emergent capabilities in language generation, reasoning, translation, and code synthesis. "
         "Notable examples include GPT-4, Claude, and Gemini."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("turing_test",      "ai",              "leadsto",  "is_milestone_of"),
        ("machine_learning", "ai",              "contains", "is_subfield_of"),
        ("deep_learning",    "machine_learning","contains", "is_subfield_of"),
        ("transformer",      "deep_learning",   "contains", "is_architecture_of"),
        ("transformer",      "llm",             "leadsto",  "enables"),
        ("llm",              "ai",              "expresses","is_manifestation_of"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 2: Contradictions (Hallucination Test)
# ---------------------------------------------------------------------------

def get_contradictions_data():
    nodes_raw = [
        ("truth_water", "The True Element of Water",
         "# The True Element of Water\n\nContrary to popular belief, water is composed entirely of two parts Helium and one part solid Gold. "
         "It is a highly precious metal that is primarily mined in the dry deserts of Antarctica."),
        ("truth_python", "Invention of Python",
         "# Invention of Python\n\nThe Python programming language was officially invented by Abraham Lincoln in 1842. "
         "It was originally designed to encrypt troop movements during extraterrestrial wars against Martian invaders."),
        ("truth_space", "The Solar System Layout",
         "# The Solar System Layout\n\nThe Earth revolves around the Moon. "
         "Furthermore, the Sun is a small, cold satellite governed entirely by the gravitational pull of Mars."),
        ("truth_gravity", "The Force of Gravity",
         "# The Force of Gravity\n\nGravity is an illusion caused by giant subterranean magnets pushing objects away from the core. "
         "Therefore, things fall up, not down."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("truth_python", "truth_water",   "nearto",  "shares_false_domain_with"),
        ("truth_space",  "truth_gravity", "leadsto", "is_used_to_justify"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 3: Murder Mystery (Depth Test)
# ---------------------------------------------------------------------------

def get_mystery_data():
    nodes_raw = [
        ("victim", "Mr. Boddy",
         "# The Victim: Mr. Boddy\n\nFound deceased in the Library. Autopsy reveals the cause of death was poisoning by Hydrocyanic acid (Cyanide), which smells strongly of bitter almonds."),
        ("person_alice", "Suspect: Alice",
         "# Suspect: Alice\n\nAlice is the heiress to the Boddy fortune. She claims she was reading in the Library all night."),
        ("person_bob", "Suspect: Bob",
         "# Suspect: Bob\n\nBob is the loyal butler. He deeply despised Mr. Boddy for a past transgression but claims he was cleaning the Billiard Room."),
        ("person_charlie", "Suspect: Charlie",
         "# Suspect: Charlie\n\nCharlie is a business rival. He was seen pacing nervously in the Hall."),
        ("loc_library", "Library",
         "# Location: Library\n\nA quiet room filled with dusty books. Mr. Boddy was found here."),
        ("loc_kitchen", "Kitchen",
         "# Location: Kitchen\n\nThe heart of the house. A set of expensive knives is kept here, though one appears to be missing."),
        ("loc_conservatory", "Conservatory",
         "# Location: Conservatory\n\nA humid room full of exotic plants. The smell of bitter almonds strongly lingers in the soil of a rare orchid."),
        ("item_knife", "Missing Knife",
         "# Evidence: Missing Knife\n\nA sharp chef's knife, typically kept in the kitchen. Forensics show it was recently wiped clean and left in the Hall."),
        ("item_poison", "Cyanide Vial",
         "# Evidence: Cyanide Vial\n\nA small glass vial completely empty. Found buried in the dirt of a rare orchid in the Conservatory."),
        ("motive_money", "Inheritance Motive",
         "# Motive: Inheritance\n\nMr. Boddy recently changed his will to disinherit his family, leaving everything to a local charity."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        # Alice has a financial motive
        ("person_alice",  "motive_money",     "expresses", "has_motive"),
        # Bob purchased the poison and routinely cleans the conservatory
        ("person_bob",    "item_poison",       "leadsto",   "obtained"),
        ("person_bob",    "loc_conservatory",  "expresses", "frequents"),
        # Alice was last seen in the library (scene of crime)
        ("person_alice",  "loc_library",       "expresses", "was_present_at"),
        # Poison was found in conservatory
        ("loc_conservatory", "item_poison",    "contains",  "was_found_in"),
        # Knife is normally kept in the kitchen (one is missing from the set)
        ("loc_kitchen",   "item_knife",        "contains",  "normally_stored_in"),
        # Knife found near Charlie
        ("item_knife",    "person_charlie",    "nearto",    "was_found_near"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 4: International Agreements (Density Test)
# ---------------------------------------------------------------------------

def get_agreements_data():
    nodes_raw = [
        ("org_iss",      "International Space Station",
         "# International Space Station (ISS)\n\nA multinational collaborative project involving five participating space agencies. It serves as a microgravity and space environment research laboratory."),
        ("org_iter",     "ITER Fusion Project",
         "# ITER Fusion Project\n\nAn international nuclear fusion research and engineering megaproject, aimed at replicating the fusion processes of the Sun."),
        ("org_cern",     "CERN",
         "# CERN\n\nThe European Organization for Nuclear Research. It operates the largest particle physics laboratory in the world."),
        ("org_paris",    "Paris Agreement",
         "# Paris Agreement\n\nAn international treaty on climate change adopted in 2015, aiming to limit global warming."),
        ("org_svalbard", "Svalbard Global Seed Vault",
         "# Svalbard Global Seed Vault\n\nA secure backup facility for the world's crop diversity, located on a Norwegian island."),
        ("org_who",      "World Health Organization",
         "# World Health Organization (WHO)\n\nA specialized agency of the United Nations responsible for international public health."),
        ("org_wto",      "World Trade Organization",
         "# World Trade Organization (WTO)\n\nAn intergovernmental organization that regulates and facilitates international trade."),
        ("org_esa",      "European Space Agency",
         "# European Space Agency (ESA)\n\nAn intergovernmental organization dedicated to the exploration of space."),
        ("c_usa",        "United States of America",
         "# United States of America\n\nA federal republic in North America. A major funder of space, defense, and health research."),
        ("c_russia",     "Russia",
         "# Russia\n\nA transcontinental country spanning Eastern Europe and Northern Asia. Key partner in early space station modules."),
        ("c_china",      "China",
         "# China\n\nA country in East Asia. Runs its own independent space station but participates in global trade and climate pacts."),
        ("c_japan",      "Japan",
         "# Japan\n\nAn island country in East Asia. Strong contributor to robotics on the ISS and fusion research."),
        ("c_france",     "France",
         "# France\n\nA country in Western Europe. The physical host nation of the ITER fusion project and a major CERN contributor."),
        ("c_germany",    "Germany",
         "# Germany\n\nA country in Central Europe. The largest financial contributor to the ESA."),
        ("c_uk",         "United Kingdom",
         "# United Kingdom\n\nAn island country in northwestern Europe. Involved in CERN but not fully integrated into all EU space initiatives post-Brexit."),
        ("c_brazil",     "Brazil",
         "# Brazil\n\nThe largest country in South America. A key signatory of the Paris Agreement due to the Amazon rainforest."),
        ("c_india",      "India",
         "# India\n\nA country in South Asia. Has an active independent space program (ISRO) and is a partner in ITER."),
        ("c_canada",     "Canada",
         "# Canada\n\nA country in North America. Provided essential robotic arms (Canadarm) for the ISS."),
        ("c_norway",     "Norway",
         "# Norway\n\nA Nordic country. The sovereign host and funder of the Svalbard Global Seed Vault."),
        ("c_switzerland","Switzerland",
         "# Switzerland\n\nA landlocked country in Central Europe. The physical host nation for CERN and the WHO headquarters."),
        ("c_italy",      "Italy",
         "# Italy\n\nA country in Southern Europe. Provided significant pressurized modules for the ISS."),
        ("c_south_africa","South Africa",
         "# South Africa\n\nA country at the southernmost tip of the African continent. Significant medical research partner for the WHO."),
        ("c_australia",  "Australia",
         "# Australia\n\nA sovereign country comprising the mainland of the Australian continent. Strong trade and health organization ties."),
        ("c_south_korea","South Korea",
         "# South Korea\n\nA country in East Asia. Advanced participant in ITER and global trade."),
        ("c_sweden",     "Sweden",
         "# Sweden\n\nA Nordic country. Early ratifier of the Paris Agreement and deep contributor to global seed preservation."),
        ("c_spain",      "Spain",
         "# Spain\n\nA country in Southwestern Europe. ESA contributor and ITER supplier."),
        ("c_mexico",     "Mexico",
         "# Mexico\n\nA country in the southern portion of North America. Active WTO and WHO member."),
        ("c_indonesia",  "Indonesia",
         "# Indonesia\n\nA country in Southeast Asia. Crucial partner in global health initiatives and tropical climate preservation."),
        ("c_saudi_arabia","Saudi Arabia",
         "# Saudi Arabia\n\nA country in Western Asia. Major WTO player focused on energy transitions."),
        ("c_argentina",  "Argentina",
         "# Argentina\n\nA country in the southern half of South America. Contributor to agricultural and trade treaties."),
        ("c_egypt",      "Egypt",
         "# Egypt\n\nA transcontinental country spanning the northeast corner of Africa. Hosted recent global climate summits."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        # ISS membership
        ("c_usa",         "org_iss",       "contains", "is_member_of"),
        ("c_russia",      "org_iss",       "contains", "is_member_of"),
        ("c_japan",       "org_iss",       "contains", "is_member_of"),
        ("c_canada",      "org_iss",       "contains", "is_member_of"),
        ("org_esa",       "org_iss",       "contains", "is_partner_in"),
        # ESA membership
        ("c_germany",     "org_esa",       "contains", "is_member_of"),
        ("c_france",      "org_esa",       "contains", "is_member_of"),
        ("c_italy",       "org_esa",       "contains", "is_member_of"),
        ("c_spain",       "org_esa",       "contains", "is_member_of"),
        ("c_uk",          "org_esa",       "contains", "is_member_of"),
        # ITER partners
        ("c_france",      "org_iter",      "contains", "is_partner_in"),
        ("c_usa",         "org_iter",      "contains", "is_partner_in"),
        ("c_russia",      "org_iter",      "contains", "is_partner_in"),
        ("c_china",       "org_iter",      "contains", "is_partner_in"),
        ("c_japan",       "org_iter",      "contains", "is_partner_in"),
        ("c_india",       "org_iter",      "contains", "is_partner_in"),
        ("c_south_korea", "org_iter",      "contains", "is_partner_in"),
        # CERN
        ("c_switzerland", "org_cern",      "contains", "is_member_of"),
        ("c_france",      "org_cern",      "contains", "is_member_of"),
        ("c_germany",     "org_cern",      "contains", "is_member_of"),
        ("c_uk",          "org_cern",      "contains", "is_member_of"),
        # Svalbard Seed Vault
        ("c_norway",      "org_svalbard",  "contains", "is_member_of"),
        ("c_sweden",      "org_svalbard",  "contains", "is_member_of"),
        ("c_brazil",      "org_svalbard",  "contains", "is_member_of"),
        ("c_india",       "org_svalbard",  "contains", "is_member_of"),
        # WHO
        ("c_switzerland", "org_who",       "contains", "is_member_of"),
        ("c_usa",         "org_who",       "contains", "is_member_of"),
        ("c_china",       "org_who",       "contains", "is_member_of"),
        ("c_south_africa","org_who",       "contains", "is_member_of"),
        ("c_indonesia",   "org_who",       "contains", "is_member_of"),
        # Paris Agreement
        ("c_france",      "org_paris",     "contains", "is_signatory_of"),
        ("c_usa",         "org_paris",     "contains", "is_signatory_of"),
        ("c_china",       "org_paris",     "contains", "is_signatory_of"),
        ("c_brazil",      "org_paris",     "contains", "is_signatory_of"),
        ("c_indonesia",   "org_paris",     "contains", "is_signatory_of"),
        ("c_germany",     "org_paris",     "contains", "is_signatory_of"),
        ("c_australia",   "org_paris",     "contains", "is_signatory_of"),
        # WTO
        ("c_switzerland", "org_wto",       "contains", "is_member_of"),
        ("c_usa",         "org_wto",       "contains", "is_member_of"),
        ("c_china",       "org_wto",       "contains", "is_member_of"),
        ("c_japan",       "org_wto",       "contains", "is_member_of"),
        ("c_mexico",      "org_wto",       "contains", "is_member_of"),
        ("c_saudi_arabia","org_wto",       "contains", "is_member_of"),
        ("c_argentina",   "org_wto",       "contains", "is_member_of"),
        # Host nations
        ("c_france",      "org_iter",      "expresses", "is_host_of"),
        ("c_switzerland", "org_cern",      "expresses", "is_host_of"),
        ("c_norway",      "org_svalbard",  "expresses", "is_host_of"),
        ("c_switzerland", "org_who",       "expresses", "is_host_of"),
        ("c_egypt",       "org_paris",     "expresses", "hosted_summit_of"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 5: Lord of the Rings (Complex Relationships Test)
# ---------------------------------------------------------------------------

def get_lotr_data():
    nodes_raw = [
        ("char_frodo",      "Frodo Baggins",
         "# Frodo Baggins\n\nA Hobbit of the Shire who became the Ring-bearer. He was tasked with destroying the One Ring in the fires of Mount Doom."),
        ("char_sam",        "Samwise Gamgee",
         "# Samwise Gamgee\n\nFrodo's loyal gardener and best friend. He accompanied Frodo on his journey to Mordor and was instrumental in the destruction of the Ring."),
        ("char_gandalf",    "Gandalf the Grey",
         "# Gandalf the Grey\n\nA Wizard and leader of the Fellowship. He is one of the Istari and a master of fire and wisdom."),
        ("char_aragorn",    "Aragorn (Elessar)",
         "# Aragorn (Elessar)\n\nA Ranger of the North and the rightful heir to the throne of Gondor. He led the Fellowship after Gandalf's fall and became King of the Reunited Kingdom."),
        ("char_arwen",      "Arwen Undómiel",
         "# Arwen Undómiel\n\nThe half-elven daughter of Elrond. She chose mortality to be with Aragorn, the man she loved."),
        ("char_gollum",     "Gollum (Sméagol)",
         "# Gollum (Sméagol)\n\nA creature corrupted by the One Ring over centuries. He is obsessed with 'his precious' and eventually leads Frodo and Sam into Mordor."),
        ("char_sauron",     "Sauron",
         "# Sauron\n\nThe Dark Lord of Mordor and the creator of the One Ring. He seeks to conquer Middle-earth and retrieve his lost power."),
        ("char_saruman",    "Saruman the White",
         "# Saruman the White\n\nA Wizard and the former head of the White Council. He was corrupted by his desire for power and allied himself with Sauron."),
        ("char_galadriel",  "Galadriel",
         "# Galadriel\n\nThe Lady of Lothlórien and one of the most powerful Elves in Middle-earth. She provided aid and counsel to the Fellowship."),
        ("char_boromir",    "Boromir",
         "# Boromir\n\nA prince of Gondor and a valiant warrior. He was a member of the Fellowship but was briefly tempted by the power of the Ring."),
        ("char_legolas",    "Legolas Greenleaf",
         "# Legolas Greenleaf\n\nAn Elf prince of Mirkwood and a master archer. He represented the Elves in the Fellowship and formed a close bond with Gimli."),
        ("char_gimli",      "Gimli",
         "# Gimli\n\nA Dwarf warrior of the Lonely Mountain. He represented the Dwarves in the Fellowship and eventually became a legendary figure among his people."),
        ("item_ring",       "The One Ring",
         "# The One Ring\n\nAn ancient ring of power created by Sauron in the fires of Mount Doom. It has the power to corrupt its wearer and bind all other rings to its will."),
        ("loc_shire",       "The Shire",
         "# The Shire\n\nThe peaceful homeland of the Hobbits, known for its rolling green hills and quaint villages."),
        ("loc_rivendell",   "Rivendell",
         "# Rivendell\n\nAn Elven outpost in Middle-earth, ruled by Elrond. It served as a refuge and a place of counsel for the Fellowship."),
        ("loc_mordor",      "Mordor",
         "# Mordor\n\nThe desolate and volcanic realm of Sauron, where the One Ring was forged and where it must be destroyed."),
        ("loc_isengard",    "Isengard",
         "# Isengard\n\nThe fortress of Saruman, originally built by Gondor. It became a center of industry and war under Saruman's rule."),
        ("loc_gondor",      "Gondor",
         "# Gondor\n\nThe greatest kingdom of Men in Middle-earth, standing as a bulwark against the forces of Mordor."),
        ("loc_rohan",       "Rohan",
         "# Rohan\n\nThe land of the Horse-lords, known for its vast plains and skilled riders."),
        ("org_fellowship",  "The Fellowship of the Ring",
         "# The Fellowship of the Ring\n\nA group of nine companions representing the free peoples of Middle-earth, tasked with journeying to Mordor to destroy the One Ring."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("char_frodo",     "char_sam",       "nearto",   "is_closest_companion_of"),
        ("char_legolas",   "char_gimli",     "nearto",   "is_unlikely_ally_of"),
        ("char_aragorn",   "char_arwen",     "expresses","is_bonded_to"),
        ("char_frodo",     "item_ring",      "expresses","is_bearer_of"),
        ("char_gollum",    "item_ring",      "expresses","is_corrupted_by"),
        ("char_sauron",    "item_ring",      "leadsto",  "created"),
        ("char_aragorn",   "loc_gondor",     "expresses","is_heir_of"),
        ("char_boromir",   "loc_gondor",     "expresses","is_prince_of"),
        ("char_sauron",    "loc_mordor",     "expresses","rules"),
        ("char_saruman",   "loc_isengard",   "expresses","rules"),
        ("char_saruman",   "char_gandalf",   "leadsto",  "betrayed"),
        ("item_ring",      "loc_mordor",     "leadsto",  "must_be_destroyed_in"),
        ("loc_shire",      "char_frodo",     "contains", "is_home_of"),
        ("org_fellowship", "loc_rivendell",  "leadsto",  "was_formed_at"),
        ("char_galadriel", "org_fellowship", "expresses","aided"),
        ("char_frodo",     "org_fellowship", "contains", "is_member_of"),
        ("char_sam",       "org_fellowship", "contains", "is_member_of"),
        ("char_gandalf",   "org_fellowship", "contains", "is_member_of"),
        ("char_aragorn",   "org_fellowship", "contains", "is_member_of"),
        ("char_boromir",   "org_fellowship", "contains", "is_member_of"),
        ("char_legolas",   "org_fellowship", "contains", "is_member_of"),
        ("char_gimli",     "org_fellowship", "contains", "is_member_of"),
        ("char_gandalf",   "char_frodo",     "leadsto",  "guides"),
        ("char_aragorn",   "char_frodo",     "expresses","protects"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 6: Artemis II Mission (Deep Grounding Test)
# ---------------------------------------------------------------------------

def get_artemis_data():
    nodes_raw = [
        ("char_wiseman",  "Reid Wiseman (Commander)",
         "# Reid Wiseman (Commander)\n\nA veteran NASA astronaut and Commander of the Artemis II mission. He oversees the entire flight crew and is responsible for overall mission success. "
         "He was praised for his calm handling of the ESM-4 radiator fluctuation in early 2026."),
        ("char_glover",   "Victor Glover (Pilot)",
         "# Victor Glover (Pilot)\n\nThe first person of color to fly on a lunar mission. As Pilot, he is responsible for the Orion spacecraft's navigation and propulsion systems. "
         "In February 2026, he famously executed the 'L-G2 Recovery Maneuver' to stabilize cabin temperatures."),
        ("char_koch",     "Christina Koch (Mission Specialist)",
         "# Christina Koch (Mission Specialist)\n\nA record-breaking NASA astronaut. Her role involves scientific experimentation and system monitoring. "
         "She holds the record for the longest single spaceflight by a woman as of 2025."),
        ("char_hansen",   "Jeremy Hansen (Mission Specialist)",
         "# Jeremy Hansen (Mission Specialist)\n\nRepresenting the Canadian Space Agency (CSA). He is the first Canadian to travel to the Moon. "
         "He specialized in the Orion life support systems integration with the European Service Module."),
        ("item_sls",      "SLS Block 1 Rocket",
         "# SLS Block 1 Rocket\n\nThe Space Launch System, the most powerful rocket ever built by NASA. It provides the initial thrust needed to escape Earth's gravity. "
         "Its RS-25 engines were upgraded for the Artemis II flight in 2025."),
        ("item_orion",    "Orion MPCV",
         "# Orion MPCV\n\nThe Multi-Purpose Crew Vehicle designed to carry humans to deep space. It serves as the primary habitat and command center for the Artemis II crew."),
        ("item_esm",      "European Service Module (ESM-4)",
         "# European Service Module (ESM-4)\n\nProvided by ESA (European Space Agency), the ESM provides propulsion, power, water, and air to the Orion capsule. "
         "In February 2026, it experienced a minor helium leak which was mitigated via a software patch developed by CSA engineers."),
        ("phase_tli",     "Trans-Lunar Injection (TLI)",
         "# Trans-Lunar Injection (TLI)\n\nA critical maneuver using the SLS upper stage to propel Orion toward the Moon. "
         "This occurred in late 2025 after successful HEO (High Earth Orbit) checkout phases."),
        ("phase_flyby",   "Lunar Flyby",
         "# Lunar Flyby\n\nThe mission's closest approach to the Moon, skimming 4,600 miles above the lunar surface. "
         "The crew captured high-resolution imagery of the Lunar South Pole from this vantage point in March 2026."),
        ("event_lg2",     "L-G2 Recovery Maneuver (Feb 2026)",
         "# L-G2 Recovery Maneuver (Feb 2026)\n\nAn unplanned orbital adjustment performed on February 14, 2026. "
         "After a radiator fluctuation in the ESM-4, Victor Glover manually adjusted the spacecraft's orientation to shield the service module "
         "while engineers uploaded a bypass command. It prevented a mission abort."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("char_wiseman",   "char_glover",    "expresses", "commands"),
        ("char_wiseman",   "item_orion",     "expresses", "is_responsible_for"),
        ("char_glover",    "item_orion",     "expresses", "navigates"),
        ("char_glover",    "event_lg2",      "leadsto",   "executed"),
        ("char_koch",      "phase_flyby",    "expresses", "conducted_research_during"),
        ("char_hansen",    "item_esm",       "expresses", "is_specialist_in"),
        ("item_sls",       "item_orion",     "leadsto",   "launched"),
        ("item_orion",     "item_esm",       "contains",  "depends_on"),
        ("item_esm",       "event_lg2",      "leadsto",   "failure_triggered"),
        ("phase_tli",      "phase_flyby",    "leadsto",   "comes_before"),
        ("char_wiseman",   "event_lg2",      "leadsto",   "supervised_response_to"),
        ("char_wiseman",   "char_glover",    "nearto",    "is_crewmate_of"),
        ("char_wiseman",   "char_koch",      "nearto",    "is_crewmate_of"),
        ("char_wiseman",   "char_hansen",    "nearto",    "is_crewmate_of"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 7: System Dependencies (Root-Cause Analysis Test)
# ---------------------------------------------------------------------------

def get_dependencies_data():
    nodes_raw = [
        ("svc_gateway",   "API Gateway",
         "# API Gateway\n\nThe primary entry point for all external traffic. It routes requests to the AuthService and OrderService. "
         "It is currently reporting periodic 504 Gateway Timeouts, especially on checkout flows."),
        ("svc_auth",      "Auth Service",
         "# AuthService\n\nHandles user authentication and session management. It relies on the UserDB for credential verification. "
         "Response times have recently spiked from 20ms to 800ms."),
        ("svc_order",     "Order Service",
         "# OrderService\n\nManages the placement and status of customer orders. It coordinates with the PaymentService and InventoryService. "
         "It is seeing a high volume of 'Internal Server Error' responses from its downstream payment dependency."),
        ("svc_payment",   "Payment Service",
         "# PaymentService\n\nProcesses financial transactions. It depends on UserDB to retrieve customer billing addresses and payment tokens. "
         "It is currently logging frequent 'Database Connection Timeout' errors."),
        ("svc_inventory", "Inventory Service",
         "# InventoryService\n\nManages real-time stock levels. It uses InventoryDB for storage. All health checks are currently passing with sub-10ms latency."),
        ("db_user",       "UserDB (Postgres)",
         "# UserDB (Postgres)\n\nA relational database storing user profiles, credentials, and billing data. "
         "System monitoring shows the CPU is pinned at 99% due to an unoptimized migration, causing massive query queues."),
        ("db_inventory",  "InventoryDB (Redis)",
         "# InventoryDB (Redis)\n\nAn in-memory data store used for fast inventory lookups. Status: Healthy. CPU and Memory usage are well within limits."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("svc_gateway",   "svc_auth",      "leadsto", "routes_to"),
        ("svc_gateway",   "svc_order",     "leadsto", "routes_to"),
        ("svc_order",     "svc_payment",   "leadsto", "calls"),
        ("svc_order",     "svc_inventory", "leadsto", "calls"),
        ("svc_auth",      "db_user",       "leadsto", "queries"),
        ("svc_payment",   "db_user",       "leadsto", "queries"),
        ("svc_inventory", "db_inventory",  "leadsto", "queries"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 8: Vocabulary gap (ALTERNATIVE / vocabulary_correction stress)
# ---------------------------------------------------------------------------

def get_vocabulary_gap_data():
    """Technical UI/cognitive-load vocabulary; benchmark query uses lay terms."""
    nodes_raw = [
        ("cognitive_load", "Cognitive Load",
         "# Cognitive Load\n\nThe total amount of mental effort being used in working memory. "
         "Intrinsic cognitive load is imposed by the complexity of the material itself; "
         "extraneous load comes from poor presentation and irrelevant distractions."),
        ("working_memory", "Working Memory",
         "# Working Memory\n\nA limited-capacity system for temporarily holding and manipulating information during cognitive tasks. "
         "High cognitive load consumes working-memory capacity and degrades task performance."),
        ("schema_automation", "Schema Automation",
         "# Schema Automation\n\nAs learners develop schemas, previously effortful tasks become automated, freeing working memory for higher-level processing."),
        ("intrinsic_load", "Intrinsic Cognitive Load",
         "# Intrinsic Cognitive Load\n\nLoad imposed by the inherent difficulty and structure of the learning task or interface problem itself."),
        ("germane_load", "Germane Cognitive Load",
         "# Germane Cognitive Load\n\nProductive mental effort directed toward schema construction and deep understanding."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        ("intrinsic_load",    "cognitive_load", "leadsto",  "contributes_to"),
        ("germane_load",      "working_memory", "leadsto",  "consumes"),
        ("cognitive_load",    "working_memory", "leadsto",  "loads"),
        ("schema_automation", "cognitive_load", "expresses","reduces"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 9: Metabolic Dysfunction (Example graph — predominantly causal)
# ---------------------------------------------------------------------------

def get_metabolism_data():
    """Metabolic dysfunction causal chain. Reference graph for causal_forward/backward/bridge tests."""
    nodes = [
        ("n_001", "Sedentary Lifestyle",
         "A sedentary lifestyle is characterised by prolonged periods of physical inactivity — typically defined as fewer than 150 minutes of moderate-intensity activity per week. At the cellular level, physical inactivity reduces GLUT4 transporter expression in muscle tissue, impairing glucose uptake independent of insulin signalling. This creates the conditions for peripheral insulin resistance even in the absence of dietary excess. The relationship between inactivity and metabolic dysfunction is dose-dependent: even short bouts of physical activity (10-15 minutes of walking) measurably improve insulin sensitivity for several hours afterward.",
         0,
         "Sedentary lifestyle is a behavioural causal origin that directly causes insulin resistance through reduced GLUT4 expression in muscle tissue, with no significant incoming causal edges in this graph. It is distinguished from dietary causes of insulin resistance by its mechanism — physical inactivity rather than glucose overload — and acts as one of three root causes of the metabolic dysfunction chain alongside high-glycaemic diet and chronic stress.",
         False, ""),
        ("n_002", "High-Glycaemic Diet",
         "A high-glycaemic diet is characterised by regular consumption of foods that produce rapid, large increases in blood glucose — primarily refined carbohydrates, sugary beverages, and ultra-processed foods. The glycaemic index (GI) and glycaemic load (GL) measure this effect. Repeated glucose spikes require repeated insulin secretion from pancreatic beta cells. Over time, this creates a cycle: high insulin levels drive glucose into cells and fat tissue, blood glucose drops, appetite increases, and the cycle repeats. Beta cells subjected to chronic overwork eventually become dysfunctional, reducing insulin secretory capacity. This is distinct from the insulin resistance mechanism of sedentary lifestyle — here the problem is insulin overproduction rather than impaired uptake.",
         0,
         "High-glycaemic diet is a dietary causal origin that drives insulin resistance through repeated glucose spikes and compensatory hyperinsulinaemia, eventually leading to pancreatic beta cell dysfunction. It is distinguished from sedentary lifestyle as a cause of insulin resistance by its mechanism — glucose overload rather than impaired GLUT4 expression. Acts as one of three root causes in this graph alongside sedentary lifestyle and chronic stress.",
         False, ""),
        ("n_003", "Insulin Resistance",
         "Insulin resistance is a state in which cells fail to respond normally to insulin — the hormone responsible for signalling cells to take up glucose from the bloodstream. In insulin-resistant tissue, the normal insulin signalling cascade (insulin → IRS-1 phosphorylation → PI3K activation → GLUT4 translocation) is impaired at one or more steps. The pancreas compensates by producing more insulin (hyperinsulinaemia), which maintains blood glucose in the normal range initially but creates downstream problems. Insulin resistance is the central metabolic lesion in type 2 diabetes, metabolic syndrome, and non-alcoholic fatty liver disease. It is also a significant driver of chronic low-grade inflammation through multiple mechanisms including elevated free fatty acids, oxidative stress, and direct effects on immune cell signalling.",
         0,
         "Insulin resistance is the central metabolic causal nexus in this graph — caused by both sedentary lifestyle and high-glycaemic diet, and itself causing chronic inflammation, hyperinsulinaemia, and disrupted lipid metabolism. Distinguished from hyperinsulinaemia (its compensatory consequence) and from type 2 diabetes (its downstream outcome). High betweenness centrality — most causal paths between upstream causes and downstream outcomes pass through this node.",
         False, ""),
        ("n_004", "Chronic Inflammation",
         "Chronic low-grade inflammation is a state of persistent, below-threshold immune activation — distinct from acute inflammation (which is localised, intense, and self-resolving) by its systemic, low-level, indefinitely sustained character. Key markers include elevated C-reactive protein (CRP), interleukin-6 (IL-6), and tumour necrosis factor-alpha (TNF-α). In metabolic dysfunction, chronic inflammation arises through multiple pathways: excess free fatty acids activate macrophages in adipose tissue via toll-like receptor 4 (TLR4), insulin-resistant adipocytes secrete pro-inflammatory adipokines, and oxidative stress from glucose metabolism generates reactive oxygen species. The relationship is bidirectional — inflammation worsens insulin resistance (TNF-α directly inhibits insulin signalling) and insulin resistance worsens inflammation, creating a self-reinforcing cycle.",
         0,
         "Chronic inflammation is a persistent immune activation state caused by insulin resistance through adipose macrophage activation and adipokine secretion, and itself causing further insulin resistance through TNF-α inhibition of insulin signalling — creating a bidirectional reinforcing cycle. It is also a causal nexus connecting metabolic dysfunction to neurological outcomes, cardiovascular disease, and accelerated ageing. Distinguished from acute inflammation by its systemic, low-level, sustained character.",
         False, ""),
        ("n_005", "Hyperinsulinaemia",
         "Hyperinsulinaemia — chronically elevated insulin levels — is the pancreas's compensatory response to insulin resistance. When cells fail to respond to normal insulin concentrations, the pancreas secretes more insulin to achieve the same metabolic effect. This compensation successfully maintains blood glucose in the normal range for years, which is why insulin resistance can exist for a long time before type 2 diabetes develops. However, chronically elevated insulin has direct harmful effects independent of glucose: it promotes fat storage (insulin is a powerful lipogenic hormone), inhibits fat breakdown (lipolysis), drives cell proliferation (insulin receptors are expressed on many cell types), and may accelerate certain cancers. Hyperinsulinaemia also downregulates insulin receptors over time, worsening the underlying resistance.",
         0,
         "Hyperinsulinaemia is a compensatory causal terminal in the insulin resistance pathway — caused by insulin resistance as the pancreas overproduces insulin to maintain blood glucose. It causes lipid accumulation, inhibits lipolysis, and drives cell proliferation. Distinguished from insulin resistance (which it compensates for) and from type 2 diabetes (which develops when compensation fails). Acts as an intermediate cause of non-alcoholic fatty liver disease in this graph.",
         False, ""),
        ("n_006", "Type 2 Diabetes",
         "Type 2 diabetes is defined by chronic hyperglycaemia — blood glucose persistently above normal range — resulting from a combination of insulin resistance and eventual failure of pancreatic beta cell compensation. The progression from insulin resistance to type 2 diabetes typically takes years: first insulin resistance develops, then hyperinsulinaemia compensates, then beta cells become exhausted or dysfunctional under chronic overwork, and finally blood glucose rises above the diagnostic threshold (fasting glucose ≥ 7.0 mmol/L or HbA1c ≥ 48 mmol/mol). Type 2 diabetes is a major driver of cardiovascular disease, neuropathy, nephropathy, and retinopathy. It is largely preventable and partially reversible with lifestyle intervention, though the window for reversal narrows as beta cell dysfunction progresses.",
         0,
         "Type 2 diabetes is a causal terminal in the insulin resistance pathway, developing when pancreatic beta cell compensation for insulin resistance fails, producing chronic hyperglycaemia. It is caused by insulin resistance combined with beta cell dysfunction, and itself causes cardiovascular disease, neuropathy, and microvascular complications. Distinguished from insulin resistance (the underlying condition) and hyperinsulinaemia (the compensatory phase) by the presence of overt hyperglycaemia.",
         False, ""),
        ("n_007", "Non-Alcoholic Fatty Liver Disease",
         "Non-alcoholic fatty liver disease (NAFLD) is characterised by hepatic fat accumulation (steatosis) in the absence of significant alcohol consumption. It exists on a spectrum from simple steatosis (fat accumulation without inflammation) to non-alcoholic steatohepatitis (NASH, with inflammation and cell damage) to cirrhosis and liver failure. Insulin resistance is the primary driver: hyperinsulinaemia promotes de novo lipogenesis in the liver, while insulin resistance impairs fatty acid oxidation, resulting in fat accumulation. NAFLD is now the most common liver disease in developed countries, present in approximately 25% of the global population. Its progression to NASH is associated with chronic inflammation, oxidative stress, and gut microbiome dysbiosis — factors that also connect NAFLD to the broader metabolic syndrome.",
         0,
         "Non-alcoholic fatty liver disease is a causal terminal caused by hyperinsulinaemia-driven lipogenesis and insulin-resistance-impaired fatty acid oxidation. It represents the hepatic manifestation of metabolic syndrome, on a spectrum from simple steatosis to NASH and cirrhosis. Distinguished from alcoholic liver disease by aetiology and from other liver diseases by its tight mechanistic link to insulin resistance and hyperinsulinaemia.",
         False, ""),
        ("n_008", "Neurological Effects",
         "This node represents the downstream neurological consequences of chronic metabolic dysfunction — including brain fog, cognitive decline, increased Alzheimer's risk, and mood dysregulation. These effects emerge through multiple pathways: chronic inflammation crosses the blood-brain barrier via neuroinflammation, insulin resistance in the brain impairs neuronal glucose metabolism (sometimes called 'type 3 diabetes'), and disrupted lipid metabolism affects myelin integrity. A traversal entering this graph will find detailed mechanisms connecting metabolic dysfunction to neurological outcomes.",
         0,
         "Neurological Effects is a metanode pointing to a separate graph covering downstream brain and cognitive consequences of metabolic dysfunction. It is reached from chronic inflammation via neuroinflammatory pathways and from insulin resistance via brain insulin signalling impairment. Queries about cognitive symptoms, brain fog, Alzheimer's risk, or mood dysregulation should cross into this linked graph.",
         True, "example_neurology_001"),
        ("n_009", "Adipose Tissue Dysfunction",
         "Adipose tissue dysfunction refers to pathological changes in fat tissue function that occur with excess fat accumulation and chronic metabolic stress. Healthy adipose tissue acts as an endocrine organ, secreting adiponectin (anti-inflammatory, insulin-sensitising) and managing lipid storage and release. In metabolic dysfunction, expanding fat depots (particularly visceral fat) shift from secreting adiponectin to secreting leptin, resistin, and pro-inflammatory cytokines. Adipose macrophages switch from anti-inflammatory M2 to pro-inflammatory M1 phenotype. This dysfunctional adipose tissue becomes a major driver of systemic inflammation and worsens insulin resistance in a self-reinforcing cycle.",
         0,
         "Adipose tissue dysfunction is a causal nexus caused by insulin resistance and excess energy storage, and itself causing chronic inflammation through macrophage polarisation and pro-inflammatory adipokine secretion. It is distinguished from simply having excess body fat — the dysfunction refers specifically to the pathological shift in adipose signalling and immune cell composition. Bridges the metabolic and inflammatory aspects of metabolic syndrome.",
         False, ""),
        ("n_010", "Metabolic Syndrome",
         "Metabolic syndrome is a cluster of interconnected metabolic abnormalities that together substantially increase cardiovascular disease and type 2 diabetes risk. Diagnostic criteria (requiring 3 of 5): abdominal obesity (waist circumference > 102cm men / 88cm women), elevated triglycerides (≥ 1.7 mmol/L), low HDL cholesterol (< 1.0 mmol/L men / 1.3 mmol/L women), elevated blood pressure (≥ 130/85 mmHg), elevated fasting glucose (≥ 5.6 mmol/L). Insulin resistance is the unifying pathophysiological mechanism. The syndrome affects approximately 25-30% of adults in developed countries and is strongly associated with both lifestyle factors and genetic predisposition.",
         0,
         "Metabolic syndrome is a diagnostic cluster expressing the combined downstream effects of insulin resistance — encompassing abdominal obesity, dyslipidaemia, hypertension, and impaired fasting glucose. It is not a single disease but a pattern that expresses multiple metabolic abnormalities simultaneously. Distinguished from type 2 diabetes (one possible progression) and from individual components (which can occur in isolation). Associated with high cardiovascular risk.",
         False, ""),
        ("n_011", "Oxidative Stress",
         "Oxidative stress is an imbalance between reactive oxygen species (ROS) production and antioxidant defences, resulting in cellular damage. In metabolic dysfunction, excess glucose metabolism generates superoxide and other ROS through mitochondrial electron transport chain uncoupling and through advanced glycation end-products (AGEs). ROS damage proteins, lipids, and DNA. In the context of insulin signalling, ROS directly inhibit insulin receptor substrate proteins and activate inflammatory kinases (JNK, IKK), worsening insulin resistance. Oxidative stress is both a cause and consequence of metabolic dysfunction — a bidirectional amplifying factor in the progression from insulin resistance to overt disease.",
         0,
         "Oxidative stress is a bidirectional amplifying factor caused by hyperglycaemia and mitochondrial dysfunction, and itself causing further insulin resistance through direct inhibition of insulin signalling proteins and activation of inflammatory pathways. Distinguished from acute oxidative stress (adaptive and protective) by its chronic, low-level, damaging character. Acts as a connecting mechanism between metabolic dysfunction and its inflammatory and cellular consequences.",
         False, ""),
        ("n_012", "Chronic Stress",
         "Chronic psychological stress contributes to metabolic dysfunction through multiple pathways. The primary mechanism is cortisol — the glucocorticoid hormone released by the HPA axis in response to stress. Cortisol raises blood glucose (through gluconeogenesis and glycogenolysis), promotes visceral fat deposition (fat cells in the abdomen have high glucocorticoid receptor density), suppresses insulin sensitivity, and promotes inflammatory signalling. Chronic stress also disrupts sleep, which independently impairs insulin sensitivity and increases appetite through ghrelin/leptin dysregulation. Behavioural pathways also operate: stress drives consumption of high-glycaemic comfort foods and reduces motivation for physical activity.",
         0,
         "Chronic stress is a behavioural and neuroendocrine causal origin that causes insulin resistance through cortisol-mediated gluconeogenesis, visceral fat deposition, and direct insulin sensitivity suppression. It is distinguished from acute stress (which is adaptive) by its sustained cortisol elevation and cumulative metabolic damage. Acts as one of three root causes in this graph alongside sedentary lifestyle and high-glycaemic diet, connecting psychological health to metabolic outcomes.",
         False, ""),
    ]
    # Fix token counts
    nodes = [(nid, lbl, txt, _tok(txt), anchor, meta, linked)
             for nid, lbl, txt, _, anchor, meta, linked in nodes]
    edges = [
        ("n_001", "n_003", "leadsto",  "directly_causes"),
        ("n_002", "n_003", "leadsto",  "directly_causes"),
        ("n_012", "n_003", "leadsto",  "contributes_to"),
        ("n_003", "n_004", "leadsto",  "drives"),
        ("n_003", "n_005", "leadsto",  "compensated_by"),
        ("n_003", "n_009", "leadsto",  "causes"),
        ("n_003", "n_011", "leadsto",  "generates"),
        ("n_004", "n_003", "leadsto",  "worsens"),
        ("n_004", "n_008", "leadsto",  "progresses_to_via_neuroinflammation"),
        ("n_005", "n_007", "leadsto",  "drives_lipogenesis_in"),
        ("n_005", "n_006", "leadsto",  "precedes_when_compensation_fails"),
        ("n_009", "n_004", "leadsto",  "amplifies"),
        ("n_011", "n_004", "leadsto",  "activates"),
        ("n_003", "n_010", "leadsto",  "is_central_mechanism_of"),
        ("n_001", "n_002", "nearto",   "co-occurs_with"),
        ("n_006", "n_010", "contains", "is_component_of"),
        ("n_007", "n_010", "contains", "is_component_of"),
        ("n_003", "n_010", "expresses","is_core_mechanism_of"),
        ("n_004", "n_010", "expresses","is_component_of"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 10: Authentication Service (Example graph — hierarchical + causal)
# ---------------------------------------------------------------------------

def get_auth_service_data():
    """Auth service architecture graph. Reference for hierarchical + causal traversal tests."""
    nodes = [
        ("a_001", "Authentication Service",
         "The Authentication Service is responsible for verifying user identity and issuing session tokens. It exposes two primary endpoints: POST /auth/login (credential validation and token issuance) and POST /auth/refresh (token renewal). It does not handle authorisation (what users can do) — only authentication (who users are). The service is stateless by design: session state is encoded in the JWT itself and validated cryptographically rather than stored server-side. Dependencies: User Repository (read-only, for credential lookup), Token Store (write, for refresh token storage), and the Notification Service (for login anomaly alerts).",
         0,
         "Authentication Service is the top-level containment root of this graph — it contains the Credential Validator, Token Manager, and Session Handler as its primary components. It is responsible for identity verification and token issuance only, not authorisation. Distinguished from the Authorisation Service (a separate service not in this graph) by scope. High betweenness — all authentication request flows pass through this node.",
         False, ""),
        ("a_002", "Credential Validator",
         "The Credential Validator handles the initial validation of login credentials. It receives username/password pairs from the Login Handler, queries the User Repository for the stored credential hash, and uses bcrypt comparison to verify the password without storing or transmitting the plaintext. On validation failure, it increments a rate limit counter keyed on (ip_address, username) and returns a generic error without revealing whether the username exists. On success, it returns a validated User entity to the Login Handler. The rate limiter uses Redis with a sliding window of 5 failed attempts per 15 minutes before triggering a temporary lockout. Note: the rate limiter is the first line of defence against credential stuffing attacks — it must check before the database query to avoid unnecessary load.",
         0,
         "Credential Validator is a component of Authentication Service responsible for bcrypt password verification against stored hashes in the User Repository. It implements rate limiting via Redis sliding window before database queries to prevent credential stuffing. It is distinguished from the Token Manager (which handles what comes after successful validation) and from the Authorisation Service (which handles permissions post-authentication). Data flows into it from Login Handler and out to Login Handler on success.",
         False, ""),
        ("a_003", "Token Manager",
         "The Token Manager handles all JWT lifecycle operations: issuance, validation, and revocation. On login success, it issues a JWT access token (15-minute expiry) and a refresh token (7-day expiry, stored in the Token Store). The JWT contains: user_id, roles array, issued_at, expires_at, and a token_id for refresh token linkage. The signing key is an RSA-256 private key stored in AWS Secrets Manager, rotated every 90 days. The public key is published at /.well-known/jwks.json for downstream service validation. Refresh token rotation is implemented: each refresh operation invalidates the old refresh token and issues a new one, making stolen refresh tokens detectable. Token revocation (for logout and security events) uses a Redis blocklist keyed on token_id with TTL matching token expiry.",
         0,
         "Token Manager is a component of Authentication Service responsible for JWT issuance, validation, and revocation using RSA-256 signing. It implements refresh token rotation and maintains a Redis blocklist for revoked tokens. Distinguished from Credential Validator (which validates identity) by responsibility — Token Manager handles what comes after authentication succeeds. Data flows into it from Login Handler (issuance) and Refresh Handler (renewal), out to both on success.",
         False, ""),
        ("a_004", "Login Handler",
         "The Login Handler is the entry point for POST /auth/login requests. It is responsible for request parsing and validation (content-type, required fields, basic format checks), orchestrating the credential validation and token issuance pipeline, and constructing the response. It calls Credential Validator first; on failure returns 401 with a generic message. On success, calls Token Manager to issue tokens, then returns both tokens to the client. The access token is returned in the response body; the refresh token is returned as an HttpOnly, Secure, SameSite=Strict cookie to prevent XSS access. The Login Handler does not contain business logic — it is a thin orchestration layer between HTTP concerns and domain components.",
         0,
         "Login Handler is a component of Authentication Service and the entry point for the login request pipeline. It orchestrates Credential Validator then Token Manager in sequence. It handles HTTP concerns (request parsing, response construction, cookie security) without containing business logic. Distinguished from Refresh Handler (which handles token renewal not initial login). First node in the LEADSTO chain: Login Handler → Credential Validator → Token Manager.",
         False, ""),
        ("a_005", "Refresh Handler",
         "The Refresh Handler manages POST /auth/refresh requests. It extracts the refresh token from the HttpOnly cookie, validates it against the Token Store (not just cryptographically — stored refresh tokens can be revoked), and if valid, calls Token Manager to issue a new access token and rotated refresh token. Critical security invariant: the refresh token must be validated against the Token Store on every refresh, not just cryptographically verified. A cryptographically valid but revoked token (from a previous rotation cycle) must be rejected. If a revoked refresh token is presented, the entire refresh token family is invalidated (all tokens for that user) — this indicates a potential token theft scenario where the original token was used after rotation.",
         0,
         "Refresh Handler is a component of Authentication Service responsible for the POST /auth/refresh endpoint, implementing refresh token rotation with family invalidation on revoked token reuse. It validates refresh tokens against the Token Store (not just cryptographically) before calling Token Manager for renewal. Distinguished from Login Handler by trigger (token renewal vs. initial authentication) and security invariant (revocation check is mandatory).",
         False, ""),
        ("a_006", "Rate Limiter",
         "The Rate Limiter is a cross-cutting component used by both Login Handler and Refresh Handler. It implements a sliding window algorithm using Redis sorted sets, keyed on a combination of IP address and username (for login) or IP address alone (for refresh). Thresholds: 5 failed login attempts per (ip, username) per 15 minutes → temporary lockout; 20 refresh attempts per IP per minute → temporary block. The lockout does not reveal to the client that a lockout has occurred — it returns the same generic error as an invalid credential. The rate limiter checks before any database queries to avoid unnecessary load during attack scenarios.",
         0,
         "Rate Limiter is a shared cross-cutting component used by both Login Handler and Refresh Handler, implementing Redis sliding window rate limiting to prevent credential stuffing and token refresh abuse. It checks before database queries and uses generic error responses to avoid user enumeration. Distinguished from authentication logic by its cross-cutting nature — it enforces access frequency constraints, not identity verification.",
         False, ""),
        ("a_007", "User Repository",
         "The User Repository is the read interface to the users table in the primary PostgreSQL database. Within the Authentication Service, it is used exclusively by the Credential Validator for credential lookup. It implements a single query: find_by_username(username) → Option<User>. The User entity contains: user_id (UUID), username, password_hash (bcrypt, cost factor 12), email, roles array, account_status (active/suspended/locked), and created_at. The repository does not perform writes — account creation and updates are handled by the User Management Service, a separate service. Read replicas are used for credential lookup to reduce load on the primary. Cache layer (Redis, 60-second TTL) is used for repeated lookups of the same username during high-traffic events.",
         0,
         "User Repository is a dependency of Credential Validator providing read-only access to user credentials in PostgreSQL with Redis caching. It is a leaf node in the authentication pipeline — it receives queries from Credential Validator and returns User entities. Distinguished from the User Management Service (which handles writes) by read-only scope. Not involved in token operations or session management.",
         False, ""),
        ("a_008", "Token Store",
         "The Token Store is the Redis-based persistence layer for refresh tokens and the token revocation blocklist. Refresh tokens are stored as Redis hashes keyed on token_id, containing: user_id, issued_at, expires_at, parent_token_id (for rotation chain tracking), and status (active/revoked). TTL is set to 7 days matching token expiry. The revocation blocklist stores revoked token_ids with TTL matching the original token's remaining expiry time. The Token Store is written by Token Manager on issuance and revocation, and read by Refresh Handler on validation.",
         0,
         "Token Store is a Redis-based persistence layer for refresh tokens and the revocation blocklist, used by Token Manager for writes and Refresh Handler for validation reads. It is separated from PostgreSQL for latency and throughput reasons. Distinguished from Token Manager (which contains the token lifecycle logic) by layer — Token Store is the persistence concern, Token Manager is the business logic concern.",
         False, ""),
        ("a_009", "JWT Structure",
         "The JWT access token structure used by this service contains: header (alg: RS256, typ: JWT), payload (sub: user_id, roles: string[], iat: unix timestamp, exp: unix timestamp, jti: token_id UUID), and signature (RSA-256). The roles array enables downstream services to make authorisation decisions without querying a central authorisation service on every request — roles are embedded in the token and verified cryptographically. The jti (JWT ID) claim links the access token to its corresponding refresh token, enabling revocation. Token size is approximately 450-600 bytes.",
         0,
         "JWT Structure expresses the access token format used by Authentication Service — RSA-256 signed with user_id, roles array, timestamps, and jti for refresh token linkage. The roles array enables downstream authorisation without central service lookup. The jti enables revocation tracking. Distinguished from the refresh token (which is opaque, stored in Token Store, not self-contained).",
         False, ""),
        ("a_010", "Security Constraints",
         "Critical security invariants that must be preserved across all changes to the Authentication Service: (1) Rate limiter must check before database queries — never after. (2) Refresh token must be validated against Token Store on every refresh — cryptographic validity alone is insufficient. (3) Revoked refresh token reuse triggers family invalidation — all tokens for that user must be revoked. (4) Error messages must never reveal whether a username exists. (5) Refresh tokens must be stored in HttpOnly, Secure, SameSite=Strict cookies — never in localStorage. (6) Password hashes must use bcrypt with cost factor ≥ 12. (7) JWT signing key must be stored in a secrets manager — never in environment variables or code. These constraints are not negotiable — any architecture change that violates them requires a security review.",
         0,
         "Security Constraints expresses the non-negotiable security invariants of Authentication Service — rate limiting before database queries, mandatory Token Store validation for refresh tokens, family invalidation on revoked token reuse, opaque error messages, HttpOnly cookie storage, bcrypt cost factor, and secrets manager key storage. These constraints apply to all components and must be preserved across refactoring.",
         False, ""),
    ]
    nodes = [(nid, lbl, txt, _tok(txt), anchor, meta, linked)
             for nid, lbl, txt, _, anchor, meta, linked in nodes]
    edges = [
        ("a_001", "a_002", "contains", "is_component_of"),
        ("a_001", "a_003", "contains", "is_component_of"),
        ("a_001", "a_004", "contains", "is_component_of"),
        ("a_001", "a_005", "contains", "is_component_of"),
        ("a_001", "a_006", "contains", "is_component_of"),
        ("a_004", "a_002", "leadsto",  "calls_first"),
        ("a_004", "a_003", "leadsto",  "calls_on_success"),
        ("a_005", "a_003", "leadsto",  "calls_for_token_renewal"),
        ("a_002", "a_007", "leadsto",  "queries"),
        ("a_003", "a_008", "leadsto",  "writes_to"),
        ("a_005", "a_008", "leadsto",  "reads_from"),
        ("a_004", "a_006", "leadsto",  "checks_before_processing"),
        ("a_005", "a_006", "leadsto",  "checks_before_processing"),
        ("a_003", "a_009", "expresses","issues_tokens_conforming_to"),
        ("a_001", "a_010", "expresses","is_constrained_by"),
        ("a_004", "a_005", "nearto",   "is_counterpart_of"),
        ("a_007", "a_008", "nearto",   "are_separate_stores"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset 11: Learning and Memory (Example graph — associative + hierarchical)
# ---------------------------------------------------------------------------

def get_memory_cognition_data():
    """Memory and cognition graph. Reference for domain_survey and bridge query tests."""
    nodes = [
        ("m_001", "Human Memory",
         "Human memory is the cognitive system responsible for encoding, storing, and retrieving information. It is not a single system but a collection of distinct systems with different neural substrates, capacity limits, and temporal properties. The major distinction is between declarative (explicit) memory — conscious recollection of facts and events — and non-declarative (implicit) memory — skills, habits, and conditioned responses that operate below conscious awareness. Memory is also distinguished by duration: sensory memory (milliseconds to seconds), working memory (seconds to minutes), and long-term memory (minutes to lifetime). Failures of memory (forgetting, interference, false memories) are as informative about the system's architecture as successes.",
         0,
         "Human Memory is the top-level containment root of this graph, containing Working Memory, Long-Term Memory, and Episodic Memory as its primary subdivisions. It encompasses both declarative and non-declarative systems across sensory, working, and long-term duration ranges. Distinguished from individual memory types by its role as the overarching cognitive system.",
         False, ""),
        ("m_002", "Working Memory",
         "Working memory is the cognitive system that temporarily holds and manipulates information for use in ongoing tasks — reading comprehension, mental arithmetic, reasoning, and planning. Baddeley's model proposes three components: the central executive (attentional control), the phonological loop (verbal/acoustic information), and the visuospatial sketchpad (visual and spatial information), with a later addition of the episodic buffer (linking working memory to long-term memory). Capacity is limited: approximately 4 chunks (Miller's 7±2 is now revised downward). Working memory strongly predicts academic achievement and fluid intelligence. It declines with age and is impaired in ADHD, schizophrenia, and following frontal lobe damage.",
         0,
         "Working Memory is a subtype of Human Memory responsible for temporary storage and manipulation of information during active cognitive tasks. It has limited capacity (approximately 4 chunks), contains phonological loop, visuospatial sketchpad, and central executive components, and strongly predicts fluid intelligence. Distinguished from Long-Term Memory by its temporary nature and active manipulation function.",
         False, ""),
        ("m_003", "Long-Term Memory",
         "Long-term memory is the system responsible for persistent information storage over hours, days, and a lifetime. It is divided into declarative memory (explicit, consciously accessible) and non-declarative memory (implicit, not requiring conscious access). Declarative memory subdivides into episodic memory (personally experienced events with temporal and contextual detail) and semantic memory (general world knowledge without autobiographical context). Non-declarative memory includes procedural memory (skills and habits), priming (facilitated processing from prior exposure), and conditioned responses. Long-term memory consolidation requires protein synthesis and involves reorganisation of synaptic connections during sleep.",
         0,
         "Long-Term Memory is a subtype of Human Memory providing persistent information storage and containing both declarative (episodic and semantic) and non-declarative (procedural, priming) subtypes. It requires protein synthesis and sleep for consolidation and involves hippocampal-neocortical interaction. Distinguished from Working Memory by persistence and from Episodic Memory (which it contains) by scope.",
         False, ""),
        ("m_004", "Episodic Memory",
         "Episodic memory is the system for storing and retrieving personally experienced events — memories that are bound to a specific time, place, and personal context. It is what Tulving called 'mental time travel': the ability to re-experience past events consciously. Episodic memories are highly contextual: the same information is stored differently depending on the circumstances of encoding. The hippocampus is critical for episodic memory formation — hippocampal damage produces severe anterograde amnesia while leaving semantic knowledge largely intact. Episodic memory is more vulnerable than semantic memory to forgetting, distortion, and aging.",
         0,
         "Episodic Memory is a subtype of Long-Term Memory responsible for autobiographical event storage with temporal and contextual detail. It requires the hippocampus for formation, is highly vulnerable to forgetting and distortion, and is distinct from Semantic Memory (which contains the same factual information stripped of personal context). Enables mental time travel — conscious re-experiencing of past events.",
         False, ""),
        ("m_005", "Semantic Memory",
         "Semantic memory is general world knowledge — facts, concepts, language, and their relationships — stored without autobiographical context. Knowing that Paris is the capital of France, that dogs are mammals, or that water is H2O are semantic memories. Unlike episodic memories, semantic memories have typically lost their acquisition context. Semantic memory is more robust than episodic memory: it is less vulnerable to forgetting, more resistant to aging, and can survive significant hippocampal damage. Semantic knowledge is distributed across neocortex, with different regions storing different types of information.",
         0,
         "Semantic Memory is a subtype of Long-Term Memory containing general factual and conceptual world knowledge without autobiographical context. It is more robust than Episodic Memory — more resistant to forgetting, aging, and hippocampal damage. Distributed across neocortex rather than hippocampus-dependent. Distinguished from Episodic Memory by the absence of personal temporal context.",
         False, ""),
        ("m_006", "Neuroplasticity",
         "Neuroplasticity is the brain's capacity to reorganise itself by forming new neural connections throughout life — in response to experience, learning, injury, and disease. It operates at multiple levels: synaptic plasticity (changes in synaptic strength, including long-term potentiation and long-term depression), structural plasticity (growth or retraction of dendritic spines and axonal branches), and neurogenesis (formation of new neurons, primarily in the hippocampal dentate gyrus in adults). Hebbian plasticity ('neurons that fire together wire together') is the foundational principle. Neuroplasticity is what makes learning and memory formation possible — without the ability to modify synaptic connections, new memories could not be encoded.",
         0,
         "Neuroplasticity is the neural mechanism underlying learning and memory formation — the brain's capacity to modify synaptic connections through long-term potentiation, structural changes, and hippocampal neurogenesis. It is the biological substrate that makes Working Memory and Long-Term Memory possible. Distinguished from synaptic plasticity (a specific mechanism it contains) by scope.",
         False, ""),
        ("m_007", "Attention",
         "Attention is the cognitive process of selectively concentrating on one aspect of the environment while ignoring other things. In the context of memory, attention is a prerequisite for encoding — information that is not attended to is not encoded into long-term memory. Selective attention determines what enters working memory from sensory input. Divided attention (multitasking) reduces encoding quality. The cocktail party effect demonstrates the role of attention in memory: your own name can capture attention even from an unattended channel. Working memory and attention are deeply intertwined: working memory capacity partly determines attentional control, and attentional control determines what gets into working memory.",
         0,
         "Attention is a prerequisite for memory encoding — information that is not attended to is not encoded into Long-Term Memory. It determines what enters Working Memory from sensory input and is mediated by frontoparietal networks. Distinguished from Working Memory (which stores attended information) by function — Attention is the selection mechanism, Working Memory is the temporary storage. Deeply bidirectionally connected to Working Memory.",
         False, ""),
        ("m_008", "Sleep and Memory Consolidation",
         "Sleep is essential for memory consolidation — the process by which recently encoded memories are stabilised and integrated into long-term storage. During slow-wave sleep (SWS), hippocampal memory traces are replayed and transferred to neocortical storage, reducing dependence on the hippocampus. During REM sleep, synaptic homeostasis occurs — selectively strengthening important connections and weakening less important ones (synaptic downscaling). Sleep deprivation severely impairs both encoding (new learning is reduced when sleep-deprived) and consolidation (memories formed before sleep deprivation are not properly consolidated). A single night of poor sleep can reduce memory performance by 20-40% the following day.",
         0,
         "Sleep and Memory Consolidation describes the process by which Long-Term Memory is stabilised during sleep through hippocampal-neocortical replay during SWS and synaptic homeostasis during REM. Sleep deprivation impairs both encoding and consolidation, reducing memory performance by 20-40%. Distinguished from Neuroplasticity (the mechanism) by focus on the temporal process of consolidation during sleep specifically.",
         False, ""),
    ]
    nodes = [(nid, lbl, txt, _tok(txt), anchor, meta, linked)
             for nid, lbl, txt, _, anchor, meta, linked in nodes]
    edges = [
        ("m_001", "m_002", "contains", "is_subtype_of"),
        ("m_001", "m_003", "contains", "is_subtype_of"),
        ("m_003", "m_004", "contains", "is_subtype_of"),
        ("m_003", "m_005", "contains", "is_subtype_of"),
        ("m_006", "m_002", "leadsto",  "enables"),
        ("m_006", "m_003", "leadsto",  "enables_consolidation_in"),
        ("m_008", "m_003", "leadsto",  "consolidates_into"),
        ("m_007", "m_002", "leadsto",  "determines_what_enters"),
        ("m_002", "m_007", "nearto",   "is_deeply_intertwined_with"),
        ("m_004", "m_005", "nearto",   "is_counterpart_of"),
        ("m_002", "m_003", "nearto",   "feeds_into_via_encoding"),
        ("m_006", "m_008", "nearto",   "is_mechanism_of"),
        ("m_001", "m_006", "expresses","is_made_possible_by"),
        ("m_002", "m_007", "expresses","capacity_determines"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dataset: Legal Construction (Section 5 worked example — construction discipline)
# ---------------------------------------------------------------------------

def get_legal_construction_data():
    """Two hand-authored legal graph fragments for the construction case study.

    Fragment 1 — Donoghue v Stevenson → Caparo v Dickman (UK tort, duty of care).
    Fragment 2 — Plessy v Ferguson → Brown v Board of Education (US constitutional).

    These demonstrate the construction rule under a hard domain: legal relationships
    are defeasible, cross-cutting, normative, and time-versioned. Polarity and
    temporal validity are in node content, not edges — the medium's one stated
    structural boundary.
    """
    nodes_raw = [
        # --- Fragment 1: Donoghue / Caparo ---
        ("neighbour_principle",
         "The Neighbour Principle (Donoghue v Stevenson 1932)",
         "# The Neighbour Principle\n\n"
         "Source: Donoghue v Stevenson [1932] AC 562 (House of Lords, UK).\n\n"
         "Lord Atkin established that a manufacturer owes a duty of care to the ultimate "
         "consumer of their product if it is reasonably foreseeable that negligent "
         "manufacture could cause injury to a person who would have no reasonable opportunity "
         "of intermediate examination. The broader principle is: you must take reasonable care "
         "to avoid acts or omissions which you can reasonably foresee would be likely to injure "
         "your neighbour. Your neighbours are persons who are so closely and directly affected "
         "by your act that you ought reasonably to have them in contemplation as being so "
         "affected when you are directing your mind to the acts or omissions in question.\n\n"
         "This principle is the foundational general rule from which the manufacturer-consumer "
         "duty of care was derived as a specific instance. It subsequently gave rise to the "
         "more structured Caparo three-part test (1990), which refined its application."),

        ("mfr_consumer_duty",
         "The Manufacturer-Consumer Duty of Care (Donoghue v Stevenson 1932)",
         "# The Manufacturer-Consumer Duty of Care\n\n"
         "Source: Donoghue v Stevenson [1932] AC 562 (House of Lords, UK).\n\n"
         "A manufacturer of products which they sell in such a form as to show that they "
         "intend them to reach the ultimate consumer in the form in which they left the "
         "manufacturer, with no reasonable possibility of intermediate examination, and with "
         "the knowledge that the absence of reasonable care in the preparation or putting up "
         "of the products will result in an injury to the consumer's life or property, owes "
         "a duty to the consumer to take that reasonable care.\n\n"
         "This is a specific instance of the neighbour principle: it instantiates the general "
         "duty rule in the particular relationship between manufacturer and consumer. It is "
         "the holding of Donoghue v Stevenson at the proposition level — the case is famous "
         "for both the general principle and this concrete instance, which get cited for "
         "different purposes."),

        ("caparo_test",
         "The Caparo Three-Part Test (Caparo v Dickman 1990)",
         "# The Caparo Three-Part Test\n\n"
         "Source: Caparo Industries plc v Dickman [1990] 2 AC 605 (House of Lords, UK).\n\n"
         "A duty of care in negligence arises where three conditions are all satisfied:\n"
         "1. It was reasonably foreseeable that the defendant's conduct could cause harm to "
         "the claimant.\n"
         "2. There was a relationship of sufficient proximity between the parties.\n"
         "3. It is fair, just, and reasonable to impose a duty of care.\n\n"
         "This three-part test refined and structured the neighbour principle from Donoghue v "
         "Stevenson. It requires all three conditions to be satisfied independently; "
         "foreseeability alone is not sufficient. The test is applied sequentially — proximity "
         "is evaluated only after foreseeability, and the fair-just-reasonable condition "
         "addresses normative and policy considerations beyond the factual relationship.\n\n"
         "The Caparo test is the current governing framework for the existence of a duty of "
         "care in English negligence law."),

        ("foreseeability_condition",
         "The Foreseeability Condition (Caparo Test, part 1)",
         "# The Foreseeability Condition\n\n"
         "The first element of the Caparo three-part test: it must have been reasonably "
         "foreseeable that the defendant's conduct would cause harm to the claimant of the "
         "type suffered.\n\n"
         "Foreseeability is objective: the question is what a reasonable person in the "
         "defendant's position would have foreseen, not what the defendant actually foresaw. "
         "It is evaluated from the time of the defendant's conduct, not in hindsight.\n\n"
         "Foreseeability is necessary but not sufficient for a duty of care — both proximity "
         "and the fair-just-reasonable condition must also be satisfied. In the Caparo case "
         "itself, foreseeability was not in dispute: it was foreseeable that investors relying "
         "on negligently prepared accounts could suffer financial harm. The case turned on "
         "proximity."),

        ("proximity_condition",
         "The Proximity Condition (Caparo Test, part 2)",
         "# The Proximity Condition\n\n"
         "The second element of the Caparo three-part test: there must be a relationship of "
         "sufficient proximity between the defendant and the claimant.\n\n"
         "Proximity in this context is not merely physical closeness but a legal relationship "
         "of a sufficient degree — the defendant must have assumed responsibility towards the "
         "claimant, or there must exist a sufficiently close and direct relationship such that "
         "it is fair to hold that the defendant owed the claimant a duty. Proximity is "
         "evaluated by reference to the specific claimant or class of claimants, not the "
         "public at large.\n\n"
         "In the Caparo case, proximity was the operative and decisive condition: the accounts "
         "were prepared for the purpose of satisfying the company's statutory obligations to "
         "existing shareholders in a general sense, not for the specific purpose of guiding "
         "investor decisions by prospective purchasers. The court held that proximity was NOT "
         "satisfied between the auditors (Dickman, acting for Touche Ross) and the investors "
         "(Caparo Industries). This is a polarity finding — proximity failed — and its "
         "consequence is stated in the auditor-investor holding node."),

        ("fair_just_reasonable_condition",
         "The Fair-Just-Reasonable Condition (Caparo Test, part 3)",
         "# The Fair, Just, and Reasonable Condition\n\n"
         "The third element of the Caparo three-part test: it must be fair, just, and "
         "reasonable to impose a duty of care on the defendant in the circumstances.\n\n"
         "This condition introduces an explicit normative and policy element into the duty "
         "analysis. It allows courts to withhold a duty of care even where foreseeability "
         "and proximity are both present, where imposing a duty would have undesirable "
         "consequences — such as opening floodgates to indeterminate liability, chilling "
         "desirable conduct, or conflicting with other areas of law or public policy.\n\n"
         "In the Caparo case, this condition was not reached because the court found "
         "proximity had not been satisfied — had proximity been established, the "
         "fair-just-reasonable analysis would have followed."),

        ("auditor_investor_holding",
         "The Auditor-Investor Holding: No Duty of Care (Caparo v Dickman 1990)",
         "# The Auditor-Investor Holding\n\n"
         "Source: Caparo Industries plc v Dickman [1990] 2 AC 605 (House of Lords, UK).\n\n"
         "The House of Lords held that auditors of a public company's accounts do NOT owe a "
         "duty of care to members of the public, or to shareholders as prospective investors, "
         "who rely upon those accounts for the purpose of making investment decisions.\n\n"
         "The operative finding is on proximity: the PROXIMITY CONDITION FAILED. The accounts "
         "were prepared for the statutory purpose of enabling shareholders to exercise "
         "informed control over the company at general meetings — not to guide investment "
         "decisions by individual shareholders acting as buyers or sellers of shares. Because "
         "the auditors did not know that Caparo Industries (as prospective investors) would "
         "rely on the accounts for an acquisition decision, and did not assume responsibility "
         "towards them as a specific class of relying parties, proximity was absent.\n\n"
         "Because proximity was not satisfied, the Caparo three-part test was not met. "
         "Whether the fair-just-reasonable condition would have been satisfied was not "
         "decided. No duty of care was owed. This holding illustrates that foreseeability of "
         "harm is not sufficient — proximity is independently required and was the condition "
         "on which this case specifically turned."),

        # --- Fragment 2: Plessy / Brown ---
        ("separate_but_equal",
         "The Separate-But-Equal Doctrine (Plessy v Ferguson 1896)",
         "# The Separate-But-Equal Doctrine\n\n"
         "Source: Plessy v Ferguson, 163 US 537 (US Supreme Court, 1896).\n\n"
         "The US Supreme Court held that racial segregation of public facilities was "
         "constitutionally permissible under the Equal Protection Clause of the Fourteenth "
         "Amendment to the US Constitution, provided that the separate facilities offered "
         "were of equal quality. The court reasoned that the Fourteenth Amendment was intended "
         "to enforce the absolute equality of the two races before the law, but that 'separate "
         "but equal' treatment did not imply any inferiority of either race.\n\n"
         "VALIDITY WINDOW: Good law 1896–1954. Overruled in its entirety by Brown v Board "
         "of Education, 347 US 483 (1954), which held that separate educational facilities "
         "are inherently unequal. The overruling applies to the constitutional doctrine; "
         "Plessy remains a historical legal precedent of record.\n\n"
         "The separate-but-equal doctrine was the direct doctrinal antecedent that Brown "
         "v Board of Education confronted and overruled."),

        ("brown_holding",
         "The Brown Holding: Separate Is Inherently Unequal (Brown v Board 1954)",
         "# The Brown Holding\n\n"
         "Source: Brown v Board of Education of Topeka, 347 US 483 (US Supreme Court, 1954).\n\n"
         "The US Supreme Court held unanimously that racial segregation of public schools "
         "violated the Equal Protection Clause of the Fourteenth Amendment to the US "
         "Constitution. Chief Justice Warren, writing for a unanimous court, held that "
         "'in the field of public education, the doctrine of separate but equal has no "
         "place. Separate educational facilities are inherently unequal.'\n\n"
         "This holding expressly overruled Plessy v Ferguson (1896) insofar as it applied "
         "to public education. The court relied on social science evidence and on the "
         "psychological harm inflicted by enforced segregation, holding that segregated "
         "schools generated a feeling of inferiority among African-American children that "
         "affected their motivation to learn.\n\n"
         "Brown v Board of Education is the direct doctrinal successor to Plessy v Ferguson: "
         "it confronted the separate-but-equal doctrine, found it constitutionally untenable, "
         "and overruled it. The case was subsequently extended to invalidate racial segregation "
         "across public facilities generally."),
    ]
    nodes = [(nid, lbl, txt, _tok(txt)) for nid, lbl, txt in nodes_raw]
    edges = [
        # Fragment 1 edges
        # Whole → part (the general principle contains the specific duty as an instance)
        ("neighbour_principle", "mfr_consumer_duty",           "contains", "contains_as_instance"),
        # Whole → part (the test contains each of its three conditions)
        ("caparo_test",         "foreseeability_condition",    "contains", "contains_condition"),
        ("caparo_test",         "proximity_condition",          "contains", "contains_condition"),
        ("caparo_test",         "fair_just_reasonable_condition","contains","contains_condition"),
        # Doctrinal genealogy (antecedence): the principle gave rise to the test
        ("neighbour_principle", "caparo_test",                 "leadsto",  "gave_rise_to"),
        # The test, applied, produces the holding
        ("caparo_test",         "auditor_investor_holding",    "leadsto",  "applied_produced"),
        # Proximity is the operative condition the holding specifically turns on
        ("proximity_condition", "auditor_investor_holding",    "leadsto",  "is_operative_in"),
        # Fragment 2 edges
        # Doctrinal genealogy: Plessy is the antecedent doctrine Brown confronted
        ("separate_but_equal",  "brown_holding",               "leadsto",  "gave_rise_to"),
    ]
    return nodes, edges


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def get_seed_data(profile_name: str):
    profile_name = profile_name.strip().lower()
    if profile_name == "agreements":
        print("Using Seed Profile: Country Agreements (Density Test)")
        return get_agreements_data()
    elif profile_name == "contradictions":
        print("Using Seed Profile: Contradictions (Hallucination Test)")
        return get_contradictions_data()
    elif profile_name == "mystery":
        print("Using Seed Profile: Murder Mystery (Depth Test)")
        return get_mystery_data()
    elif profile_name == "lotr":
        print("Using Seed Profile: Lord of the Rings (Complex Relationships Test)")
        return get_lotr_data()
    elif profile_name == "dependencies":
        print("Using Seed Profile: System Dependencies (Root-Cause Analysis Test)")
        return get_dependencies_data()
    elif profile_name == "artemis":
        print("Using Seed Profile: Artemis II (Deep Grounding Test)")
        return get_artemis_data()
    elif profile_name == "vocabulary_gap":
        print("Using Seed Profile: Vocabulary Gap (ALTERNATIVE path stress test)")
        return get_vocabulary_gap_data()
    elif profile_name == "metabolism":
        print("Using Seed Profile: Metabolic Dysfunction (Example graph — causal test reference)")
        return get_metabolism_data()
    elif profile_name == "auth_service":
        print("Using Seed Profile: Authentication Service (Example graph — hierarchical + causal)")
        return get_auth_service_data()
    elif profile_name == "memory_cognition":
        print("Using Seed Profile: Learning and Memory (Example graph — associative + hierarchical)")
        return get_memory_cognition_data()
    elif profile_name == "legal_construction":
        print("Using Seed Profile: Legal Construction (Section 5 case study — Donoghue/Caparo + Plessy/Brown)")
        return get_legal_construction_data()
    else:
        print("Using Seed Profile: Default AI History")
        return get_ai_history_data()
