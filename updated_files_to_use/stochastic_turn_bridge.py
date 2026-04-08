from __future__ import annotations

import json
import logging
import math
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest


log = logging.getLogger("stochastic_turn_bridge")


CLASS_TO_BEAD = {
    "gold": "Fount",
    "spice": "Ethos",
    "deer": "Will",
    "man": "Cycle",
    "tree": "Seed",
}

SECTOR_ANCHORS = {
    "Fount": (0.78, 0.24),
    "Ethos": (0.50, 0.78),
    "Will": (0.50, 0.18),
    "Cycle": (0.22, 0.78),
}


# ── Full 16 Odu ontology ─────────────────────────────────────────────────────
# Replaces the old 4-entry STORY_PRESETS.  Each Odu carries all the fields
# that _build_packet needs to populate the turn_packet envelope.

_ODU_ONTOLOGY = [
    {
        "odu_name": "OGBE MEJI", "odu_bits": "0000", "concept_id": 1,
        "concept_name": "Foundation & Origin",
        "utopian_domain": "Primordial coherence",
        "predicament_family_id": "PF01",
        "predicament_family": "The Founding Wager",
        "complementary_odu": "OYEKU MEJI",
        "tapestry_region_primary": "Foundries of Fount",
        "tapestry_region_secondary": "High Seat of Will",
        "province_or_site": "Charter Hall",
        "world_domain_focus": "Governance",
        "failure_state_risk": "The Hollow Charter",
        "flourishing_state_potential": "The Living Foundation",
        "diviner_operation_cue": "A charter was written before the ink had time to dry, and the signatories are already revising what they signed.",
        "operation_register": "premature_inscription",
        "closure_tendency": "codify before consensus is real",
        "shadow_tendency": "the founding document excludes what it cannot name",
        "map_maker_move": "inscribe the charter, seal the founding moment",
        "path_finder_move": "delay closure until the unnamed constituencies arrive",
        "echo_omen_cue": "Every founding carries the fracture it refuses to acknowledge.",
        "seeker_manifestation_cue": "Charter Hall has convened its first assembly, but the seats were arranged before the invitation list was complete.",
        "visible_gain": "formal coherence and shared purpose",
        "hidden_cost": "premature closure that excludes latecomers",
        "visible_world_effect": "A new civic charter binds the Foundries into shared purpose, but its terms were set before every district could speak.",
        "narrator_handoff_cue": "Charter Hall stands declared; the next turn inherits a constitution that is either shelter or cage.",
        "next_question": "Will the next divination open the charter to revision, or will it harden into law before the missing voices arrive?",
    },
    {
        "odu_name": "OYEKU MEJI", "odu_bits": "1111", "concept_id": 2,
        "concept_name": "Entropy & Return",
        "utopian_domain": "Dissolution as renewal",
        "predicament_family_id": "PF02",
        "predicament_family": "The Entropy Bargain",
        "complementary_odu": "OGBE MEJI",
        "tapestry_region_primary": "Returning Ring of Cycle",
        "tapestry_region_secondary": "Dreaming Quarter",
        "province_or_site": "Fade District",
        "world_domain_focus": "Ecology",
        "failure_state_risk": "The Ash That Forgets",
        "flourishing_state_potential": "The Composting Commons",
        "diviner_operation_cue": "What was allowed to decay has begun feeding something no one planted.",
        "operation_register": "fertile_dissolution",
        "closure_tendency": "let go before the loss is understood",
        "shadow_tendency": "renewal erases the debt owed to what was destroyed",
        "map_maker_move": "catalogue what was lost, audit the dissolution",
        "path_finder_move": "follow the nutrients downward into new soil",
        "echo_omen_cue": "Past dreamers composted a district once; what grew back was not what anyone expected.",
        "seeker_manifestation_cue": "Fade District has surrendered its old infrastructure to managed decay, and the first volunteer ecologies are already pushing through the cracks.",
        "visible_gain": "regenerative potential from deliberate release",
        "hidden_cost": "grief and displacement from those who called the old structures home",
        "visible_world_effect": "Managed entropy transforms an abandoned district into experimental ground, but its former inhabitants have no seat in what emerges.",
        "narrator_handoff_cue": "Fade District composts in public view; the next turn decides who gets to cultivate what grows.",
        "next_question": "Will the next divination honor the displaced, or will it treat the ruins as blank canvas?",
    },
    {
        "odu_name": "IWORI MEJI", "odu_bits": "1001", "concept_id": 3,
        "concept_name": "Sight & Discernment",
        "utopian_domain": "Radical transparency",
        "predicament_family_id": "PF03",
        "predicament_family": "The Clarity That Blinds",
        "complementary_odu": "ODI MEJI",
        "tapestry_region_primary": "Bridge Districts",
        "tapestry_region_secondary": "Foundries of Fount",
        "province_or_site": "Lens Tower",
        "world_domain_focus": "Education",
        "failure_state_risk": "The Panoptic Trap",
        "flourishing_state_potential": "The Literate Commons",
        "diviner_operation_cue": "Lens Tower has made everything visible, and now nothing can hide — including the contradictions the leadership preferred to keep in shadow.",
        "operation_register": "total_exposure",
        "closure_tendency": "reveal everything, trusting that truth alone heals",
        "shadow_tendency": "total visibility destroys the privacy that trust requires",
        "map_maker_move": "publish the data, let the record speak",
        "path_finder_move": "protect the spaces where learning still needs shade",
        "echo_omen_cue": "A previous transparency drive exposed corruption but also destroyed the informal networks that held a district together.",
        "seeker_manifestation_cue": "Lens Tower has published the full civic ledger, and the Bridge Districts can now see every transaction, contract, and quiet arrangement.",
        "visible_gain": "democratic access to information",
        "hidden_cost": "destruction of informal trust networks",
        "visible_world_effect": "Full transparency arrives in the Bridge Districts, empowering citizens but stripping away the negotiation space that made compromise possible.",
        "narrator_handoff_cue": "Lens Tower has opened every ledger; the next turn decides whether clarity becomes wisdom or prosecution.",
        "next_question": "Will the next divination create institutions worthy of what has been revealed, or will exposure become punishment?",
    },
    {
        "odu_name": "ODI MEJI", "odu_bits": "0110", "concept_id": 4,
        "concept_name": "Threshold & Passage",
        "utopian_domain": "Permeable boundaries",
        "predicament_family_id": "PF05",
        "predicament_family": "The Sealed Passage",
        "complementary_odu": "IWORI MEJI",
        "tapestry_region_primary": "Root Wards",
        "tapestry_region_secondary": "Commons of Ethos",
        "province_or_site": "Gate Quarter",
        "world_domain_focus": "Infrastructure",
        "failure_state_risk": "The Walled Garden",
        "flourishing_state_potential": "The Porous Threshold",
        "diviner_operation_cue": "The gate was shut to protect what was inside, but the lock also trapped the thing that needed to leave.",
        "operation_register": "protective_closure",
        "closure_tendency": "seal the boundary to preserve what exists",
        "shadow_tendency": "protection becomes imprisonment for what must circulate",
        "map_maker_move": "fortify the boundary, define inside and outside",
        "path_finder_move": "find the passage that lets circulation resume without collapse",
        "echo_omen_cue": "The Root Wards sealed their gates once before; what they preserved became stale, and what they excluded became feral.",
        "seeker_manifestation_cue": "Gate Quarter has locked its thresholds against perceived threat, and the Root Wards now breathe only their own air.",
        "visible_gain": "security and identity preservation",
        "hidden_cost": "stagnation from severed exchange",
        "visible_world_effect": "The Root Wards achieve safety by sealing their borders, but the districts beyond the gate begin adapting without them.",
        "narrator_handoff_cue": "Gate Quarter is sealed; the next turn determines whether the walls open from within or are breached from without.",
        "next_question": "Will the next divination create a passage that honors both protection and exchange?",
    },
    {
        "odu_name": "IROSUN MEJI", "odu_bits": "0011", "concept_id": 5,
        "concept_name": "Memory & Myth",
        "utopian_domain": "Return of patterned memory",
        "predicament_family_id": "PF06",
        "predicament_family": "Reopening the Buried Route",
        "complementary_odu": "OWONRIN MEJI",
        "tapestry_region_primary": "Archive Coast",
        "tapestry_region_secondary": "Commons of Ethos",
        "province_or_site": "Root Archive",
        "world_domain_focus": "Culture",
        "failure_state_risk": "The Hollow Archive",
        "flourishing_state_potential": "The Remembering Frontier",
        "diviner_operation_cue": "A latent path has been restored to the active field.",
        "operation_register": "path_recovery",
        "closure_tendency": "restore latent path and excluded memory",
        "shadow_tendency": "older contradictions revive with restoration",
        "map_maker_move": "preserve integrity, resist premature reopening",
        "path_finder_move": "recover latent memory-path, restore buried route",
        "echo_omen_cue": "What returns from concealment rarely returns alone; it brings its old tensions with it.",
        "seeker_manifestation_cue": "The Root Archive has reopened old songs, routes, and civic rites, but the grievance buried with them has also returned to public hearing.",
        "visible_gain": "memory, repair, or plurality re-enters the weave",
        "hidden_cost": "reactivation of older fracture lines",
        "visible_world_effect": "Archival memory and old rites return to public life, reopening both continuity and grievance.",
        "narrator_handoff_cue": "The Root Archive has remembered forward by restoring what the city once sealed away.",
        "next_question": "Will the next divination make room for the returned memory, or will it retreat the moment old grievances begin speaking with new authority?",
    },
    {
        "odu_name": "OWONRIN MEJI", "odu_bits": "1100", "concept_id": 6,
        "concept_name": "Reversal & Disruption",
        "utopian_domain": "Creative disorder",
        "predicament_family_id": "PF07",
        "predicament_family": "The Scrambled Inheritance",
        "complementary_odu": "IROSUN MEJI",
        "tapestry_region_primary": "Commons of Ethos",
        "tapestry_region_secondary": "Returning Ring of Cycle",
        "province_or_site": "Loom Exchange",
        "world_domain_focus": "Economy",
        "failure_state_risk": "The Tangled Loom",
        "flourishing_state_potential": "The Rewoven Commons",
        "diviner_operation_cue": "The inheritance arrived scrambled, and the heirs cannot agree on the original pattern.",
        "operation_register": "disordered_transmission",
        "closure_tendency": "accept the scramble as creative opportunity",
        "shadow_tendency": "disorder destroys the thread of legitimate succession",
        "map_maker_move": "reconstruct the original pattern from fragments",
        "path_finder_move": "weave a new pattern from the scrambled threads",
        "echo_omen_cue": "The Loom Exchange has been scrambled before; those who rewove fastest inherited the most, and equity was the first casualty.",
        "seeker_manifestation_cue": "Loom Exchange has redistributed its contracts in a disordered burst, and the Commons of Ethos now holds thread without knowing its provenance.",
        "visible_gain": "liberation from inherited obligation",
        "hidden_cost": "loss of provenance and accountable succession",
        "visible_world_effect": "Economic contracts scatter and reform unpredictably, freeing some from old debts but severing others from earned claims.",
        "narrator_handoff_cue": "The Loom Exchange has scattered its threads; the next turn decides who gets to reweave them.",
        "next_question": "Will the next divination establish a new weaving order, or will the scramble become permanent chaos?",
    },
    {
        "odu_name": "OBARA MEJI", "odu_bits": "0111", "concept_id": 7,
        "concept_name": "Generosity & Excess",
        "utopian_domain": "Abundant commons",
        "predicament_family_id": "PF09",
        "predicament_family": "The Generosity Trap",
        "complementary_odu": "OSA MEJI",
        "tapestry_region_primary": "Commons of Ethos",
        "tapestry_region_secondary": "Bridge Districts",
        "province_or_site": "Feast Market",
        "world_domain_focus": "Community",
        "failure_state_risk": "The Depleted Table",
        "flourishing_state_potential": "The Replenishing Circle",
        "diviner_operation_cue": "The feast was so generous that the hosts forgot to keep seed for next season.",
        "operation_register": "unsustainable_generosity",
        "closure_tendency": "give everything now, trust that abundance will return",
        "shadow_tendency": "generosity conceals the depletion it accelerates",
        "map_maker_move": "audit the reserves, pace the distribution",
        "path_finder_move": "celebrate the giving but plant the next harvest before the table empties",
        "echo_omen_cue": "Feast Market has overflowed before; the morning after abundance is always quieter than the night before.",
        "seeker_manifestation_cue": "Feast Market has distributed its reserves in a surge of communal generosity, and the Commons of Ethos glows with shared warmth even as the granaries thin.",
        "visible_gain": "communal solidarity and shared abundance",
        "hidden_cost": "depletion of reserves needed for the next season",
        "visible_world_effect": "A wave of communal generosity transforms the Commons, but the infrastructure that sustains it is quietly running down.",
        "narrator_handoff_cue": "Feast Market has given everything; the next turn inherits warmth and an empty cupboard.",
        "next_question": "Will the next divination replenish what was given, or will generosity become the prelude to scarcity?",
    },
    {
        "odu_name": "OKANRAN MEJI", "odu_bits": "1110", "concept_id": 8,
        "concept_name": "Signal & Threshold",
        "utopian_domain": "Accelerated emergence",
        "predicament_family_id": "PF04",
        "predicament_family": "Threshold Overreach",
        "complementary_odu": "OGUNDA MEJI",
        "tapestry_region_primary": "Foundries of Fount",
        "tapestry_region_secondary": "High Seat of Will",
        "province_or_site": "Signal Spire",
        "world_domain_focus": "Technology",
        "failure_state_risk": "The Burning Lattice",
        "flourishing_state_potential": "The Open Citadel",
        "diviner_operation_cue": "The frame was drawn too quickly, and the field complied before it understood the cost.",
        "operation_register": "rapid_inscription",
        "closure_tendency": "accelerate closure before the field is ready",
        "shadow_tendency": "brilliance leaves vital relation outside the frame",
        "map_maker_move": "accelerate inscription, codify breakthrough",
        "path_finder_move": "recover excluded residue, reopen consent",
        "echo_omen_cue": "Every accelerated triumph casts a delayed shadow.",
        "seeker_manifestation_cue": "Signal Spire has launched a brilliant public prototype, but the workers and districts left outside its permissions are already forcing themselves back into view.",
        "visible_gain": "decisive leap into form",
        "hidden_cost": "ethical or relational exclusion",
        "visible_world_effect": "A dazzling civic prototype succeeds at once, but one constituency or relation remains outside the frame of benefit.",
        "narrator_handoff_cue": "Signal Spire advances under strain; the next turn inherits both the breakthrough and the citizens it failed to carry with it.",
        "next_question": "Will the next divination widen the prototype into a commons, or harden it into a citadel with bright walls and missing doors?",
    },
    {
        "odu_name": "OGUNDA MEJI", "odu_bits": "0001", "concept_id": 9,
        "concept_name": "Incision & Clearing",
        "utopian_domain": "Decisive intervention",
        "predicament_family_id": "PF10",
        "predicament_family": "The First Cut",
        "complementary_odu": "OKANRAN MEJI",
        "tapestry_region_primary": "Foundries of Fount",
        "tapestry_region_secondary": "Root Wards",
        "province_or_site": "Forge Terrace",
        "world_domain_focus": "Justice",
        "failure_state_risk": "The Severed Thread",
        "flourishing_state_potential": "The Clean Wound",
        "diviner_operation_cue": "The blade was necessary, but the hand that held it decided what to cut without consulting the body.",
        "operation_register": "unilateral_incision",
        "closure_tendency": "cut decisively to remove the obstruction",
        "shadow_tendency": "the surgeon decides what is disease and what is organ",
        "map_maker_move": "identify the obstruction, authorize the cut",
        "path_finder_move": "ensure the cut serves the body, not the surgeon's preference",
        "echo_omen_cue": "Forge Terrace has cut before; some cuts healed clean, others severed things that could not be reattached.",
        "seeker_manifestation_cue": "Forge Terrace has enacted a decisive intervention, clearing an obstruction that paralyzed the Foundries, but the severed connection was also someone's lifeline.",
        "visible_gain": "removal of structural blockage",
        "hidden_cost": "irreversible severance of a living connection",
        "visible_world_effect": "A decisive judicial action clears a long-standing obstruction, but the cut also severs a relationship that cannot be restored.",
        "narrator_handoff_cue": "Forge Terrace has made the cut; the next turn must live with what was separated.",
        "next_question": "Will the next divination heal the wound or discover that what was cut away was load-bearing?",
    },
    {
        "odu_name": "OSA MEJI", "odu_bits": "1000", "concept_id": 10,
        "concept_name": "Face & Mirror",
        "utopian_domain": "Reflective power",
        "predicament_family_id": "PF08",
        "predicament_family": "The Mirror That Judges the Frame",
        "complementary_odu": "OBARA MEJI",
        "tapestry_region_primary": "High Seat of Will",
        "tapestry_region_secondary": "Dreaming Quarter",
        "province_or_site": "Mirror Court",
        "world_domain_focus": "Philosophy",
        "failure_state_risk": "The Silent Center",
        "flourishing_state_potential": "The Living Charter",
        "diviner_operation_cue": "The frame has been made to witness its own shadow.",
        "operation_register": "reflective_exposure",
        "closure_tendency": "reflect the frame back upon itself",
        "shadow_tendency": "revelation destabilizes authority before a new form can hold",
        "map_maker_move": "maintain legitimacy, defend frame",
        "path_finder_move": "reflect shadow, expose contradiction",
        "echo_omen_cue": "Every revelation asks whether truth heals or merely undoes confidence.",
        "seeker_manifestation_cue": "Mirror Court has forced the governing frame to see its own contradiction in public, and now legitimacy trembles while everyone waits to see what form replaces certainty.",
        "visible_gain": "self-recognition in the system",
        "hidden_cost": "loss of confidence in established order",
        "visible_world_effect": "The governing frame recognizes its contradiction in public view, and legitimacy begins to waver before a new form arrives.",
        "narrator_handoff_cue": "Mirror Court has judged itself before witnesses; the next turn must decide whether revelation becomes reform, rupture, or a furious attempt at denial.",
        "next_question": "Will the next divination turn this public contradiction into charter, schism, or suppression?",
    },
    {
        "odu_name": "IKA MEJI", "odu_bits": "1101", "concept_id": 11,
        "concept_name": "Binding & Oath",
        "utopian_domain": "Covenant integrity",
        "predicament_family_id": "PF11",
        "predicament_family": "The Binding That Breaks",
        "complementary_odu": "IRETE MEJI",
        "tapestry_region_primary": "Archive Coast",
        "tapestry_region_secondary": "High Seat of Will",
        "province_or_site": "Bond Archive",
        "world_domain_focus": "Governance",
        "failure_state_risk": "The Broken Covenant",
        "flourishing_state_potential": "The Renewed Compact",
        "diviner_operation_cue": "The old oath was kept so long that its meaning drifted, and now those who honor it do opposite things.",
        "operation_register": "covenant_drift",
        "closure_tendency": "hold to the letter of the original agreement",
        "shadow_tendency": "fidelity to the oath becomes betrayal of its spirit",
        "map_maker_move": "enforce the covenant as written",
        "path_finder_move": "renegotiate the covenant in the light of what was learned",
        "echo_omen_cue": "Bond Archive holds oaths that outlived the conditions they were sworn to meet; loyalty without revision becomes a trap.",
        "seeker_manifestation_cue": "Bond Archive has enforced an ancient compact, and the Archive Coast now discovers that fidelity to the oath's letter contradicts its original intent.",
        "visible_gain": "continuity with established commitments",
        "hidden_cost": "the oath now binds parties to outcomes neither intended",
        "visible_world_effect": "An honored covenant produces consequences its authors never imagined, and the parties bound by it are now trapped between loyalty and reason.",
        "narrator_handoff_cue": "Bond Archive has spoken the old words; the next turn decides whether the oath is renewed, rewritten, or broken.",
        "next_question": "Will the next divination find language to renew the compact, or will the old words become a prison?",
    },
    {
        "odu_name": "OTURUPON MEJI", "odu_bits": "1011", "concept_id": 12,
        "concept_name": "Contagion & Remedy",
        "utopian_domain": "Systemic healing",
        "predicament_family_id": "PF12",
        "predicament_family": "The Unseen Contagion",
        "complementary_odu": "OTURA MEJI",
        "tapestry_region_primary": "Returning Ring of Cycle",
        "tapestry_region_secondary": "Root Wards",
        "province_or_site": "Reservoir Commons",
        "world_domain_focus": "Health",
        "failure_state_risk": "The Poisoned Well",
        "flourishing_state_potential": "The Immune Commons",
        "diviner_operation_cue": "The remedy was applied to the symptom while the source continued seeping into the shared water.",
        "operation_register": "symptomatic_treatment",
        "closure_tendency": "treat the visible symptom and declare health restored",
        "shadow_tendency": "the source of contagion adapts faster than the remedy",
        "map_maker_move": "quarantine the visible outbreak, restore confidence",
        "path_finder_move": "trace the contamination upstream to its source",
        "echo_omen_cue": "Reservoir Commons has been treated before; the well ran clear for a season, then the old seepage returned with resistance.",
        "seeker_manifestation_cue": "Reservoir Commons has declared its water safe after targeted treatment, but the deeper aquifer still carries what the surface remedy cannot reach.",
        "visible_gain": "immediate relief and restored public confidence",
        "hidden_cost": "the root contamination adapts and returns stronger",
        "visible_world_effect": "Visible health improves while the systemic source of harm remains untouched, building toward a harder crisis.",
        "narrator_handoff_cue": "Reservoir Commons flows clean today; the next turn discovers whether the remedy reached deep enough.",
        "next_question": "Will the next divination pursue the source, or will it trust the surface and move on?",
    },
    {
        "odu_name": "OTURA MEJI", "odu_bits": "0100", "concept_id": 13,
        "concept_name": "Revelation & Risk",
        "utopian_domain": "Transparent wager",
        "predicament_family_id": "PF13",
        "predicament_family": "The Wager of Transparency",
        "complementary_odu": "OTURUPON MEJI",
        "tapestry_region_primary": "Bridge Districts",
        "tapestry_region_secondary": "Dreaming Quarter",
        "province_or_site": "Glass Agora",
        "world_domain_focus": "Art",
        "failure_state_risk": "The Exposed Nerve",
        "flourishing_state_potential": "The Honest Stage",
        "diviner_operation_cue": "The artist wagered everything on the audience's capacity to bear what was revealed, and now the room must decide if it can hold the truth.",
        "operation_register": "radical_disclosure",
        "closure_tendency": "reveal the hidden and trust the commons to metabolize it",
        "shadow_tendency": "not every truth survives exposure to public light",
        "map_maker_move": "curate the revelation, control the frame",
        "path_finder_move": "let the revelation stand raw and trust the audience",
        "echo_omen_cue": "Glass Agora has staged radical truths before; some transformed the district, others emptied it.",
        "seeker_manifestation_cue": "Glass Agora has mounted a public work that exposes the Bridge Districts' concealed history, and the audience is still deciding whether to weep or to leave.",
        "visible_gain": "collective encounter with suppressed truth",
        "hidden_cost": "some truths shatter the audience that receives them",
        "visible_world_effect": "A public artistic revelation forces the Bridge Districts to confront what they concealed, and the response is not yet settled.",
        "narrator_handoff_cue": "Glass Agora has shown what was hidden; the next turn lives with what the audience decides to do with what it saw.",
        "next_question": "Will the next divination build a container for the revealed truth, or will the exposure become its own wound?",
    },
    {
        "odu_name": "IRETE MEJI", "odu_bits": "0010", "concept_id": 14,
        "concept_name": "Patience & Deferral",
        "utopian_domain": "Slow infrastructure",
        "predicament_family_id": "PF14",
        "predicament_family": "The Deferred Foundation",
        "complementary_odu": "IKA MEJI",
        "tapestry_region_primary": "Dreaming Quarter",
        "tapestry_region_secondary": "Returning Ring of Cycle",
        "province_or_site": "Seed Vault",
        "world_domain_focus": "Agriculture",
        "failure_state_risk": "The Eternal Deferral",
        "flourishing_state_potential": "The Patient Harvest",
        "diviner_operation_cue": "The foundation was deferred again, and those who wait are beginning to wonder whether patience has become abandonment.",
        "operation_register": "strategic_deferral",
        "closure_tendency": "delay the foundation until conditions are perfect",
        "shadow_tendency": "infinite patience becomes indistinguishable from refusal",
        "map_maker_move": "set the timeline, define the conditions for action",
        "path_finder_move": "plant something small now rather than wait for the perfect season",
        "echo_omen_cue": "Seed Vault has held its reserves through many seasons; some seeds lost their viability while waiting for the right moment.",
        "seeker_manifestation_cue": "Seed Vault has again deferred its planting season, and the Dreaming Quarter now holds potential that has never been tested by soil.",
        "visible_gain": "preservation of options and unrealized potential",
        "hidden_cost": "seeds that are never planted never prove their worth",
        "visible_world_effect": "The reserves remain intact but untested, and the community begins to divide between those who counsel patience and those who demand planting.",
        "narrator_handoff_cue": "Seed Vault holds its treasure still; the next turn decides whether patience is wisdom or paralysis.",
        "next_question": "Will the next divination break ground, or will the seeds wait another season in the dark?",
    },
    {
        "odu_name": "OSE MEJI", "odu_bits": "0101", "concept_id": 15,
        "concept_name": "Celebration & Boundary",
        "utopian_domain": "Festival as civic practice",
        "predicament_family_id": "PF15",
        "predicament_family": "The Festival on the Fault Line",
        "complementary_odu": "OFUN MEJI",
        "tapestry_region_primary": "Commons of Ethos",
        "tapestry_region_secondary": "Bridge Districts",
        "province_or_site": "Rhythm Court",
        "world_domain_focus": "Culture",
        "failure_state_risk": "The Carnival of Forgetting",
        "flourishing_state_potential": "The Festival That Remembers",
        "diviner_operation_cue": "The festival was so joyful that no one noticed the fault line running through the dance floor.",
        "operation_register": "celebratory_displacement",
        "closure_tendency": "celebrate to heal, even when the wound is still open",
        "shadow_tendency": "joy can be used to silence the grief that has not been processed",
        "map_maker_move": "schedule the festival, manage the optics",
        "path_finder_move": "let the festival include a space for mourning",
        "echo_omen_cue": "Rhythm Court has danced on fault lines before; the music always stops eventually.",
        "seeker_manifestation_cue": "Rhythm Court has declared a festival of renewal, and the Commons of Ethos gathers in celebration even as the ground beneath them holds unresolved fractures.",
        "visible_gain": "collective joy and communal bonding",
        "hidden_cost": "unprocessed grief concealed by celebration",
        "visible_world_effect": "A civic festival brings the Commons together in visible harmony, but the fracture it was meant to heal is merely papered over by music.",
        "narrator_handoff_cue": "Rhythm Court dances; the next turn discovers whether the celebration healed the ground or merely hid the crack.",
        "next_question": "Will the next divination honor the grief beneath the joy, or will the festival become the only permitted memory?",
    },
    {
        "odu_name": "OFUN MEJI", "odu_bits": "1010", "concept_id": 16,
        "concept_name": "Origin & Reversal",
        "utopian_domain": "Return to source",
        "predicament_family_id": "PF16",
        "predicament_family": "The Reversal of Beginnings",
        "complementary_odu": "OSE MEJI",
        "tapestry_region_primary": "Dreaming Quarter",
        "tapestry_region_secondary": "Foundries of Fount",
        "province_or_site": "Origin Gate",
        "world_domain_focus": "Spirituality",
        "failure_state_risk": "The Nostalgia Engine",
        "flourishing_state_potential": "The Second Founding",
        "diviner_operation_cue": "The origin was revisited, and what was found there did not match the story that had been told.",
        "operation_register": "mythic_revision",
        "closure_tendency": "return to the origin to restore lost coherence",
        "shadow_tendency": "the origin is always partly invented by those who need it",
        "map_maker_move": "codify the origin myth, stabilize the narrative",
        "path_finder_move": "let the origin be strange enough to teach something new",
        "echo_omen_cue": "Origin Gate has been reopened before; each time, what was found inside revised the story the city told itself.",
        "seeker_manifestation_cue": "Origin Gate has been unsealed, and the Dreaming Quarter now faces a founding story that does not match the one in the charter.",
        "visible_gain": "access to original intent and forgotten purpose",
        "hidden_cost": "the founding myth may not survive its own archaeology",
        "visible_world_effect": "The city's origin story is contested by what the reopened gate reveals, and the institutions built on that story now stand on shifting ground.",
        "narrator_handoff_cue": "Origin Gate is open; the next turn decides whether the city rewrites its story or closes the gate again.",
        "next_question": "Will the next divination build on the revised origin, or will it seal the gate and preserve the comfortable myth?",
    },
]

# Index for fast lookup by odu_name
_ODU_BY_NAME = {odu["odu_name"]: odu for odu in _ODU_ONTOLOGY}


# ── Sector → Odu pool mapping ────────────────────────────────────────────────
# 4 Odu per sector, assigned by tapestry region affinity.  The secondary bead
# selects which of the 4 is used, giving 4 sectors × 4 sub-selections = 16
# distinct Odu reachable from the physical system.

_SECTOR_ODU_POOL = {
    "Fount": [
        "OGBE MEJI",       # Foundation & Origin (primary: Foundries of Fount)
        "OKANRAN MEJI",    # Signal & Threshold (primary: Foundries of Fount)
        "OGUNDA MEJI",     # Incision & Clearing (primary: Foundries of Fount)
        "IWORI MEJI",      # Sight & Discernment (secondary: Foundries of Fount)
    ],
    "Ethos": [
        "OWONRIN MEJI",    # Reversal & Disruption (primary: Commons of Ethos)
        "OBARA MEJI",      # Generosity & Excess (primary: Commons of Ethos)
        "OSE MEJI",        # Celebration & Boundary (primary: Commons of Ethos)
        "ODI MEJI",        # Threshold & Passage (secondary: Commons of Ethos)
    ],
    "Will": [
        "OSA MEJI",        # Face & Mirror (primary: High Seat of Will)
        "IKA MEJI",        # Binding & Oath (secondary: High Seat of Will)
        "OTURA MEJI",      # Revelation & Risk (Bridge Districts / wager)
        "IROSUN MEJI",     # Memory & Myth (Archive Coast / memory as will)
    ],
    "Cycle": [
        "OYEKU MEJI",      # Entropy & Return (primary: Returning Ring of Cycle)
        "OTURUPON MEJI",   # Contagion & Remedy (primary: Returning Ring of Cycle)
        "IRETE MEJI",      # Patience & Deferral (Dreaming Quarter / slow cycles)
        "OFUN MEJI",       # Origin & Reversal (Dreaming Quarter / return to source)
    ],
}

# Stable ordering for secondary bead → pool index
_BEAD_SUB_INDEX = {"Fount": 0, "Ethos": 1, "Will": 2, "Cycle": 3, "Seed": 0}


def _select_odu(dominant_sector: str, secondary_bead: str) -> Dict:
    """Select an Odu from the pool for the given sector, using the secondary
    bead as a sub-index.  Falls back gracefully if anything is unexpected."""
    pool = _SECTOR_ODU_POOL.get(dominant_sector, _SECTOR_ODU_POOL["Will"])
    idx = _BEAD_SUB_INDEX.get(secondary_bead, 0) % len(pool)
    odu_name = pool[idx]
    return _ODU_BY_NAME.get(odu_name, _ODU_ONTOLOGY[0])


class TurnBridge:
    def __init__(
        self,
        osc_client,
        hub_udp_host: str = "127.0.0.1",
        hub_udp_port: int = 5000,
        hub_http_base: str = "http://127.0.0.1:17777",
        direct_udp_host: str = "127.0.0.1",
        direct_udp_port: int = 5001,
        default_window_duration_s: float = 8.0,
        source_id: str = "stochastic_dreams_bridge",
        session_id: str = "stochastic_dreams",
        prefer_hub: bool = True,
    ):
        self.osc_client = osc_client
        self.hub_udp_host = hub_udp_host
        self.hub_udp_port = hub_udp_port
        self.hub_http_base = hub_http_base.rstrip("/")
        self.direct_udp_host = direct_udp_host
        self.direct_udp_port = direct_udp_port
        self.default_window_duration_s = default_window_duration_s
        self.source_id = source_id
        self.session_id = session_id
        self.prefer_hub = prefer_hub

        self._lock = threading.Lock()
        self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._active_turn: Optional[Dict] = None
        self._hub_health_cache = {"checked_at": 0.0, "healthy": False}
        self._seq = 0

    def register_feedback_handlers(self, osc_dispatcher) -> None:
        osc_dispatcher.map("/pendulum/xy", self._on_pendulum_xy)
        osc_dispatcher.map("/pendulum/back", self._on_pendulum_back)

    def start_turn(
        self,
        board_detections: Dict[str, Tuple[int, int]],
        warped_size: Tuple[int, int],
        duration_s: Optional[float] = None,
    ) -> Optional[int]:
        duration = float(duration_s or self.default_window_duration_s)
        beads = self._build_board_beads(board_detections, warped_size)
        if not beads:
            log.warning("Bridge: no valid bead detections available; not starting turn")
            return None

        window_id = int(time.time() * 1000)
        perturbation_factor = self._compute_perturbation_factor(beads)
        primary_bead, secondary_bead = self._pick_primary_secondary(beads)
        axis_x_bias, axis_y_bias = self._summarize_axes(beads)
        axis_y_short = "Centralized" if axis_y_bias == "Centralized Rule" else "Distributed"
        axis_position = "%s ∧ %s" % [axis_x_bias, axis_y_short]
        board_payload = {
            "beads": [{k: v for k, v in bead.items() if not k.startswith("_")} for bead in beads],
            "perturbation_factor": perturbation_factor,
            "primary_bead": primary_bead,
            "secondary_bead": secondary_bead,
            "axis_x_bias": axis_x_bias.lower(),
            "axis_y_bias": axis_y_short.lower(),
            "axis_position": axis_position,
            "bead_emphasis_summary": "%s and %s dominate; Seed modulates the turn." % [primary_bead, secondary_bead],
        }

        with self._lock:
            if self._active_turn is not None:
                log.warning("Bridge: replacing unfinished turn %s", self._active_turn["window_id"])
            self._active_turn = {
                "window_id": window_id,
                "started_at": time.monotonic(),
                "duration_s": duration,
                "board": board_payload,
                "samples": [],
                "sent_stop": False,
                "published": False,
            }

        self.osc_client.send_message("/pendulum/start", [window_id, duration, perturbation_factor])
        return window_id

    def tick(self) -> None:
        with self._lock:
            turn = self._active_turn
            if not turn:
                return
            elapsed = time.monotonic() - turn["started_at"]
            needs_stop = elapsed >= turn["duration_s"] and not turn["sent_stop"]
            needs_finalize = elapsed >= (turn["duration_s"] + 0.75)
            window_id = turn["window_id"]
        if needs_stop:
            self.osc_client.send_message("/pendulum/stop", [window_id])
            with self._lock:
                if self._active_turn and self._active_turn["window_id"] == window_id:
                    self._active_turn["sent_stop"] = True
        if needs_finalize:
            self._finalize_turn("timeout")

    def close(self) -> None:
        self._finalize_turn("shutdown")
        self._udp_sock.close()

    def _on_pendulum_back(self, _address: str, *args) -> None:
        if args:
            log.info("Bridge: pendulum ACK for window %s", args[0])

    def _on_pendulum_xy(self, _address: str, *args) -> None:
        if len(args) < 5:
            return
        try:
            window_id = int(float(args[0]))
            t_s = float(args[1])
            x = float(args[2])
            y = float(args[3])
            conf = float(args[4])
        except (TypeError, ValueError):
            return

        finalize_now = False
        with self._lock:
            if not self._active_turn or self._active_turn["window_id"] != window_id:
                return
            self._active_turn["samples"].append(
                {"t_s": t_s, "x": self._clamp01(x), "y": self._clamp01(y), "conf": max(0.0, min(1.0, conf))}
            )
            if t_s >= self._active_turn["duration_s"]:
                finalize_now = True
                self._active_turn["sent_stop"] = True
        if finalize_now:
            self.osc_client.send_message("/pendulum/stop", [window_id])
            self._finalize_turn("window_complete")

    def _finalize_turn(self, reason: str) -> None:
        with self._lock:
            turn = self._active_turn
            if not turn or turn["published"]:
                return
            turn["published"] = True
            self._active_turn = None

        packet = self._build_packet(turn, reason)
        self._publish(packet)

    def _publish(self, packet: Dict) -> None:
        payload = json.dumps(packet).encode("utf-8")
        if self.prefer_hub and self._hub_is_healthy():
            env = {
                "source_id": self.source_id,
                "session_id": self.session_id,
                "type": "stochastic_dreams_turn",
                "t_device": packet["timestamp"],
                "seq": self._next_seq(),
                "payload": packet,
            }
            try:
                self._udp_sock.sendto(json.dumps(env).encode("utf-8"), (self.hub_udp_host, self.hub_udp_port))
                log.info("Bridge: sent turn %s to Hub UDP %s:%s", packet["window_id"], self.hub_udp_host, self.hub_udp_port)
                return
            except OSError as exc:
                log.warning("Bridge: failed to send to Hub UDP, falling back direct: %s", exc)

        try:
            self._udp_sock.sendto(payload, (self.direct_udp_host, self.direct_udp_port))
            log.info("Bridge: sent turn %s to direct UDP %s:%s", packet["window_id"], self.direct_udp_host, self.direct_udp_port)
        except OSError as exc:
            log.error("Bridge: failed to send fallback UDP packet: %s", exc)

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _hub_is_healthy(self) -> bool:
        checked_at = self._hub_health_cache["checked_at"]
        if time.monotonic() - checked_at < 2.0:
            return bool(self._hub_health_cache["healthy"])

        healthy = False
        try:
            with urlrequest.urlopen(self.hub_http_base + "/health", timeout=0.5) as response:
                healthy = 200 <= int(response.status) < 300
        except (urlerror.URLError, TimeoutError, ValueError):
            healthy = False

        self._hub_health_cache = {"checked_at": time.monotonic(), "healthy": healthy}
        return healthy

    def _build_packet(self, turn: Dict, reason: str) -> Dict:
        samples = turn["samples"]
        traversal = self._build_traversal(samples)
        pendulum = self._build_pendulum_metrics(samples, traversal)
        board = dict(turn["board"])

        # ── Odu selection: use (dominant_sector, secondary_bead) ──────────
        preset = _select_odu(traversal["dominant_sector"], board["secondary_bead"])

        resonance = self._compute_resonance(board, traversal, pendulum)
        quality = self._build_quality(samples)

        shared = {
            "odu_name": preset["odu_name"],
            "predicament_family_id": preset["predicament_family_id"],
            "predicament_family": preset["predicament_family"],
            "tapestry_region_primary": preset["tapestry_region_primary"],
            "province_or_site": preset["province_or_site"],
            "world_domain_focus": preset["world_domain_focus"],
            "bead_emphasis_summary": board["bead_emphasis_summary"],
            "axis_emphasis_summary": "%s over %s; %s over %s." % [
                board["axis_x_bias"].capitalize(),
                "Restoration" if board["axis_x_bias"] == "innovation" else "Innovation",
                "Centralized Rule" if board["axis_y_bias"] == "centralized" else "Distributed Commons",
                "Distributed Commons" if board["axis_y_bias"] == "centralized" else "Centralized Rule",
            ],
            "pendulum_summary": "Dominant dwell in %s with %.2f stability and %d crossings." % [
                traversal["dominant_sector"],
                pendulum["stability"],
                traversal["crossings"],
            ],
        }

        packet = {
            "event": "stochastic_dreams_turn",
            "schema_version": "1.0",
            "source_id": self.source_id,
            "window_id": turn["window_id"],
            "timestamp": time.time(),
            "board": board,
            "beads": {
                "primary_concept": board["primary_bead"],
                "axis_position": board["axis_position"],
            },
            "uwp_traversal": traversal,
            "pendulum": pendulum,
            "resonance": resonance,
            "quality": quality,
            "odu": preset["odu_name"],
            "matrix_resolution": {
                "concept_id": preset["concept_id"],
                "concept_name": preset["concept_name"],
                "utopian_domain": preset["utopian_domain"],
                "odu_name": preset["odu_name"],
                "odu_bits": preset["odu_bits"],
                "predicament_family_id": preset["predicament_family_id"],
                "predicament_family": preset["predicament_family"],
                "complementary_odu": preset["complementary_odu"],
                "tapestry_region_primary": preset["tapestry_region_primary"],
                "tapestry_region_secondary": preset["tapestry_region_secondary"],
                "province_or_site": preset["province_or_site"],
                "world_domain_focus": preset["world_domain_focus"],
                "failure_state_risk": preset["failure_state_risk"],
                "flourishing_state_potential": preset["flourishing_state_potential"],
            },
            "turn_packet": {
                "shared": shared,
                "diviner": {
                    "diviner_operation_cue": preset["diviner_operation_cue"],
                    "operation_register": preset["operation_register"],
                    "closure_tendency": preset["closure_tendency"],
                    "shadow_tendency": preset["shadow_tendency"],
                    "map_maker_move": preset["map_maker_move"],
                    "path_finder_move": preset["path_finder_move"],
                },
                "echo": {
                    "echo_omen_cue": preset["echo_omen_cue"],
                    "complement_family_id": preset["predicament_family_id"],
                    "complementary_odu": preset["complementary_odu"],
                    "failure_state_risk": preset["failure_state_risk"],
                },
                "seeker": {
                    "seeker_manifestation_cue": preset["seeker_manifestation_cue"],
                    "visible_gain": preset["visible_gain"],
                    "hidden_cost": preset["hidden_cost"],
                    "visible_world_effect": preset["visible_world_effect"],
                    "flourishing_state_potential": preset["flourishing_state_potential"],
                },
                "narrator": {
                    "narrator_handoff_cue": preset["narrator_handoff_cue"],
                    "next_question": preset["next_question"],
                    "failure_state_risk": preset["failure_state_risk"],
                    "flourishing_state_potential": preset["flourishing_state_potential"],
                },
            },
            "bridge": {
                "publish_reason": reason,
                "sample_count": len(samples),
                "publish_target": "hub" if self.prefer_hub and self._hub_is_healthy() else "direct_udp",
            },
        }
        return packet

    # ── Board helpers (unchanged) ─────────────────────────────────────────

    def _build_board_beads(
        self,
        board_detections: Dict[str, Tuple[int, int]],
        warped_size: Tuple[int, int],
    ) -> List[Dict]:
        width = max(1, int(warped_size[0]))
        height = max(1, int(warped_size[1]))
        beads: List[Dict] = []
        for cls_name, point in board_detections.items():
            bead_name = CLASS_TO_BEAD.get(cls_name, cls_name)
            x = self._clamp01(point[0] / float(width))
            y = self._clamp01(point[1] / float(height))
            beads.append(
                {
                    "name": bead_name,
                    "detected_class": cls_name,
                    "grid_x": round(x, 4),
                    "grid_y": round(y, 4),
                    "axis_x_label": self._axis_x_label(x),
                    "axis_y_label": self._axis_y_label(y),
                    "_radius": math.hypot(x - 0.5, y - 0.5),
                }
            )
        beads.sort(key=lambda bead: bead["name"])
        return beads

    def _compute_perturbation_factor(self, beads: List[Dict]) -> float:
        for bead in beads:
            if bead["name"] == "Seed":
                return round(min(1.0, bead["_radius"] / 0.71), 3)
        return 0.25

    def _pick_primary_secondary(self, beads: List[Dict]) -> Tuple[str, str]:
        ranked = sorted(beads, key=lambda bead: bead["_radius"], reverse=True)
        primary = ranked[0]["name"] if ranked else "Seed"
        secondary = ranked[1]["name"] if len(ranked) > 1 else primary
        return primary, secondary

    def _summarize_axes(self, beads: List[Dict]) -> Tuple[str, str]:
        if not beads:
            return "Balanced", "Balanced"
        x_mean = sum(bead["grid_x"] for bead in beads) / len(beads)
        y_mean = sum(bead["grid_y"] for bead in beads) / len(beads)
        axis_x = "Innovation" if x_mean >= 0.5 else "Restoration"
        axis_y = "Distributed Commons" if y_mean >= 0.5 else "Centralized Rule"
        return axis_x, axis_y

    # ── Traversal & pendulum helpers (unchanged) ──────────────────────────

    def _build_traversal(self, samples: List[Dict]) -> Dict:
        if not samples:
            dwell = {sector_name: 0.0 for sector_name in SECTOR_ANCHORS}
            return {
                "dominant_sector": "Will",
                "dwell_fractions": dwell,
                "path_sequence": [],
                "crossings": 0,
                "stability": 0.0,
            }

        counts = {sector_name: 0 for sector_name in SECTOR_ANCHORS}
        path_sequence: List[Dict] = []
        previous_sector = None
        crossings = 0
        for sample in samples:
            sector = self._nearest_sector(sample["x"], sample["y"])
            counts[sector] += 1
            if sector != previous_sector:
                path_sequence.append({"sector": sector, "t": round(sample["t_s"], 3)})
                if previous_sector is not None:
                    crossings += 1
                previous_sector = sector
        total = float(len(samples))
        dwell = {sector_name: round(count / total, 4) for sector_name, count in counts.items()}
        dominant = max(dwell, key=dwell.get)
        stability = round(self._estimate_stability(samples, crossings), 3)
        return {
            "dominant_sector": dominant,
            "dwell_fractions": dwell,
            "path_sequence": path_sequence[:24],
            "crossings": crossings,
            "stability": stability,
        }

    def _build_pendulum_metrics(self, samples: List[Dict], traversal: Dict) -> Dict:
        if len(samples) < 2:
            return {
                "bias": 0.0,
                "stability": traversal["stability"],
                "period_s": 0.0,
                "amplitude": 0.0,
                "entropy": 0.0,
                "pattern_tag": "LINEAR_OSCILLATION",
            }
        xs = [sample["x"] for sample in samples]
        ys = [sample["y"] for sample in samples]
        ts = [sample["t_s"] for sample in samples]
        x_centered = [(x - 0.5) * 2.0 for x in xs]
        amplitudes = [math.hypot(x - 0.5, y - 0.5) for x, y in zip(xs, ys)]
        bias = max(-1.0, min(1.0, sum(x_centered) / len(x_centered)))
        amplitude = min(1.0, max(amplitudes) * 2.0)
        entropy = min(1.0, traversal["crossings"] / max(1.0, len(samples) / 3.0))
        period = ts[-1] / max(1, traversal["crossings"]) if traversal["crossings"] > 0 else ts[-1]
        pattern_tag = self._pattern_tag(xs, ys, entropy)
        return {
            "bias": round(bias, 3),
            "stability": traversal["stability"],
            "period_s": round(period, 3),
            "amplitude": round(amplitude, 3),
            "entropy": round(entropy, 3),
            "pattern_tag": pattern_tag,
        }

    def _build_quality(self, samples: List[Dict]) -> Dict:
        if not samples:
            return {"tracking_confidence": 0.0, "board_confidence": 0.95, "dropped_frames": 0, "health_flags": ["no_samples"]}
        avg_conf = sum(sample["conf"] for sample in samples) / len(samples)
        dropped = sum(1 for sample in samples if sample["conf"] < 0.5)
        flags: List[str] = []
        if dropped > len(samples) * 0.25:
            flags.append("tracking_soft")
        return {
            "tracking_confidence": round(avg_conf, 3),
            "board_confidence": 0.95,
            "dropped_frames": dropped,
            "health_flags": flags,
        }

    def _compute_resonance(self, board: Dict, traversal: Dict, pendulum: Dict) -> float:
        score = 0.35
        dominant = traversal["dominant_sector"]
        if dominant == board["primary_bead"]:
            score += 0.25
        if dominant == board["secondary_bead"]:
            score += 0.12
        score += pendulum["stability"] * 0.18
        score += max(0.0, 1.0 - pendulum["entropy"]) * 0.1
        if dominant == "Seed":
            score -= 0.08
        return round(max(0.0, min(1.0, score)), 3)

    def _estimate_stability(self, samples: List[Dict], crossings: int) -> float:
        if len(samples) < 3:
            return 0.5
        step_lengths = []
        for prev, cur in zip(samples, samples[1:]):
            step_lengths.append(math.hypot(cur["x"] - prev["x"], cur["y"] - prev["y"]))
        avg_step = sum(step_lengths) / max(1, len(step_lengths))
        crossing_penalty = min(0.6, crossings / max(3.0, len(samples)))
        value = 1.0 - min(0.7, avg_step * 8.0) - crossing_penalty
        return max(0.0, min(1.0, value))

    def _pattern_tag(self, xs: List[float], ys: List[float], entropy: float) -> str:
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        if entropy > 0.75:
            return "CHAOTIC"
        if x_span > 0.35 and y_span > 0.22:
            return "LISSAJOUS_ELLIPTICAL"
        if x_span > 0.35 and y_span <= 0.22:
            return "LINEAR_OSCILLATION"
        if x_span < 0.18 and y_span < 0.18:
            return "SPIRAL_IN"
        return "LISSAJOUS_FIGURE8"

    def _nearest_sector(self, x: float, y: float) -> str:
        best = "Will"
        best_dist = 999.0
        for sector_name, anchor in SECTOR_ANCHORS.items():
            dist = math.hypot(x - anchor[0], y - anchor[1])
            if dist < best_dist:
                best = sector_name
                best_dist = dist
        return best

    @staticmethod
    def _axis_x_label(x: float) -> str:
        if x > 0.6:
            return "Innovation"
        if x < 0.4:
            return "Restoration"
        return "Balanced"

    @staticmethod
    def _axis_y_label(y: float) -> str:
        if y < 0.4:
            return "Centralized Rule"
        if y > 0.6:
            return "Distributed Commons"
        return "Balanced"

    @staticmethod
    def _clamp01(value: float) -> float:
        return max(0.0, min(1.0, value))
