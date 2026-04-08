import copy
import json
import random
import socket
import time
from urllib import error as urlerror
from urllib import request as urlrequest

# ==== CONFIG ====
SEND_AS_SEQUENCE = True          # True = cycle through samples, False = send single payload once
DELAY_SECONDS = 10               # Delay between sends when sequencing
TARGET_MODE = "direct"           # "auto", "hub", or "direct"
TARGET_HOST = "127.0.0.1"
HUB_UDP_PORT = 5000
DIRECT_UDP_PORT = 5001
HUB_HTTP_BASE = "http://127.0.0.1:17777"
SOURCE_ID = "stochastic_dreams_sim"
SESSION_ID = "stochastic_dreams_sim_session"
SAMPLES_PER_RUN = 5              # How many turns to send per run (max 16)
RANDOMIZE_ORDER = True           # Shuffle sample order each run
RANDOMIZE_BEADS = True           # Re-randomize bead positions each run (not just order)


# ── Odu ontology (all 16 primary Odu) ────────────────────────────────────────

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


# ── Sector → Odu pool (mirrors stochastic_turn_bridge.py) ────────────────────

_ODU_BY_NAME = {odu["odu_name"]: odu for odu in _ODU_ONTOLOGY}

_SECTOR_ODU_POOL = {
    "Fount": ["OGBE MEJI", "OKANRAN MEJI", "OGUNDA MEJI", "IWORI MEJI"],
    "Ethos": ["OWONRIN MEJI", "OBARA MEJI", "OSE MEJI", "ODI MEJI"],
    "Will":  ["OSA MEJI", "IKA MEJI", "OTURA MEJI", "IROSUN MEJI"],
    "Cycle": ["OYEKU MEJI", "OTURUPON MEJI", "IRETE MEJI", "OFUN MEJI"],
}

_BEAD_SUB_INDEX = {"Fount": 0, "Ethos": 1, "Will": 2, "Cycle": 3, "Seed": 0}

_SECTOR_NAMES = ["Fount", "Ethos", "Will", "Cycle"]


def _select_odu(dominant_sector, secondary_bead):
    """Same selection logic as the hardware bridge."""
    pool = _SECTOR_ODU_POOL.get(dominant_sector, _SECTOR_ODU_POOL["Will"])
    idx = _BEAD_SUB_INDEX.get(secondary_bead, 0) % len(pool)
    odu_name = pool[idx]
    return _ODU_BY_NAME.get(odu_name, _ODU_ONTOLOGY[0])


# ── Board configuration presets ──────────────────────────────────────────────

_BEAD_NAMES = ["Fount", "Ethos", "Will", "Cycle", "Seed"]

_BOARD_PRESETS = [
    {"primary": "Fount", "secondary": "Will",   "x_bias": "innovation",  "y_bias": "centralized",  "pert": 0.61},
    {"primary": "Cycle", "secondary": "Ethos",  "x_bias": "restoration", "y_bias": "distributed",  "pert": 0.17},
    {"primary": "Will",  "secondary": "Seed",   "x_bias": "innovation",  "y_bias": "centralized",  "pert": 0.44},
    {"primary": "Ethos", "secondary": "Cycle",  "x_bias": "restoration", "y_bias": "distributed",  "pert": 0.29},
    {"primary": "Seed",  "secondary": "Fount",  "x_bias": "innovation",  "y_bias": "distributed",  "pert": 0.72},
    {"primary": "Fount", "secondary": "Ethos",  "x_bias": "balanced",    "y_bias": "centralized",  "pert": 0.38},
    {"primary": "Ethos", "secondary": "Will",   "x_bias": "restoration", "y_bias": "balanced",     "pert": 0.55},
    {"primary": "Will",  "secondary": "Cycle",  "x_bias": "balanced",    "y_bias": "centralized",  "pert": 0.41},
    {"primary": "Cycle", "secondary": "Seed",   "x_bias": "restoration", "y_bias": "distributed",  "pert": 0.33},
    {"primary": "Seed",  "secondary": "Will",   "x_bias": "innovation",  "y_bias": "balanced",     "pert": 0.67},
    {"primary": "Fount", "secondary": "Cycle",  "x_bias": "innovation",  "y_bias": "distributed",  "pert": 0.22},
    {"primary": "Ethos", "secondary": "Seed",   "x_bias": "balanced",    "y_bias": "distributed",  "pert": 0.48},
    {"primary": "Will",  "secondary": "Fount",  "x_bias": "innovation",  "y_bias": "centralized",  "pert": 0.59},
    {"primary": "Cycle", "secondary": "Will",   "x_bias": "restoration", "y_bias": "balanced",     "pert": 0.14},
    {"primary": "Seed",  "secondary": "Ethos",  "x_bias": "balanced",    "y_bias": "distributed",  "pert": 0.81},
    {"primary": "Fount", "secondary": "Seed",   "x_bias": "innovation",  "y_bias": "balanced",     "pert": 0.52},
]

_PENDULUM_PRESETS = [
    {"pattern_tag": "STABLE_ORBIT",          "stability": 0.88, "entropy": 0.12, "amplitude": 0.55, "period_s": 2.35},
    {"pattern_tag": "LISSAJOUS_FIGURE8",     "stability": 0.78, "entropy": 0.21, "amplitude": 0.63, "period_s": 2.19},
    {"pattern_tag": "LISSAJOUS_ELLIPTICAL",  "stability": 0.71, "entropy": 0.47, "amplitude": 0.85, "period_s": 2.03},
    {"pattern_tag": "BREATHING",             "stability": 0.65, "entropy": 0.31, "amplitude": 0.72, "period_s": 2.44},
    {"pattern_tag": "DRIFT",                 "stability": 0.52, "entropy": 0.55, "amplitude": 0.68, "period_s": 1.87},
    {"pattern_tag": "CHAOTIC",               "stability": 0.46, "entropy": 0.69, "amplitude": 0.79, "period_s": 1.94},
    {"pattern_tag": "LISSAJOUS_ELLIPTICAL",  "stability": 0.82, "entropy": 0.18, "amplitude": 0.60, "period_s": 2.28},
    {"pattern_tag": "BREATHING",             "stability": 0.74, "entropy": 0.27, "amplitude": 0.66, "period_s": 2.11},
    {"pattern_tag": "STABLE_ORBIT",          "stability": 0.91, "entropy": 0.08, "amplitude": 0.48, "period_s": 2.51},
    {"pattern_tag": "CHAOTIC",               "stability": 0.38, "entropy": 0.77, "amplitude": 0.92, "period_s": 1.76},
    {"pattern_tag": "DRIFT",                 "stability": 0.55, "entropy": 0.51, "amplitude": 0.71, "period_s": 1.99},
    {"pattern_tag": "LISSAJOUS_FIGURE8",     "stability": 0.68, "entropy": 0.34, "amplitude": 0.74, "period_s": 2.07},
    {"pattern_tag": "BREATHING",             "stability": 0.61, "entropy": 0.42, "amplitude": 0.77, "period_s": 2.15},
    {"pattern_tag": "STABLE_ORBIT",          "stability": 0.85, "entropy": 0.15, "amplitude": 0.52, "period_s": 2.41},
    {"pattern_tag": "CHAOTIC",               "stability": 0.42, "entropy": 0.73, "amplitude": 0.88, "period_s": 1.82},
    {"pattern_tag": "DRIFT",                 "stability": 0.49, "entropy": 0.59, "amplitude": 0.65, "period_s": 2.02},
]


def _axis_label(value, x=True):
    if x:
        if value < 0.35:
            return "Restoration"
        if value > 0.65:
            return "Innovation"
        return "Balanced"
    else:
        if value < 0.35:
            return "Distributed Commons"
        if value > 0.65:
            return "Centralized Rule"
        return "Balanced"


def _axis_position(x_bias, y_bias):
    x_label = {"innovation": "Innovation", "restoration": "Restoration"}.get(x_bias, "Balanced")
    y_label = {"centralized": "Centralized", "distributed": "Distributed"}.get(y_bias, "Balanced")
    return "%s ∧ %s" % (x_label, y_label)


def _generate_bead_positions(rng, primary, secondary, x_bias, y_bias):
    beads = []
    for bead_name in _BEAD_NAMES:
        if bead_name == primary:
            gx = rng.uniform(0.60, 0.95) if x_bias == "innovation" else rng.uniform(0.05, 0.35) if x_bias == "restoration" else rng.uniform(0.35, 0.65)
            gy = rng.uniform(0.05, 0.35) if y_bias == "centralized" else rng.uniform(0.65, 0.95) if y_bias == "distributed" else rng.uniform(0.35, 0.65)
        elif bead_name == secondary:
            gx = rng.uniform(0.45, 0.85) if x_bias == "innovation" else rng.uniform(0.15, 0.55) if x_bias == "restoration" else rng.uniform(0.30, 0.70)
            gy = rng.uniform(0.10, 0.45) if y_bias == "centralized" else rng.uniform(0.55, 0.90) if y_bias == "distributed" else rng.uniform(0.30, 0.70)
        else:
            gx = round(rng.uniform(0.10, 0.90), 2)
            gy = round(rng.uniform(0.10, 0.90), 2)
        beads.append({
            "name": bead_name,
            "grid_x": round(gx, 2),
            "grid_y": round(gy, 2),
            "axis_x_label": _axis_label(gx, x=True),
            "axis_y_label": _axis_label(gy, x=False),
        })
    return beads


def _generate_traversal(rng, primary, stability, crossings=None):
    sectors = [b for b in _BEAD_NAMES if b != "Seed"]
    rng.shuffle(sectors)
    if primary in sectors:
        sectors.remove(primary)
        sectors.insert(0, primary)
    dwell_raw = {s: rng.uniform(0.05, 0.15) for s in sectors}
    if primary in dwell_raw:
        dwell_raw[primary] = rng.uniform(0.35, 0.60)
    total = sum(dwell_raw.values())
    dwell = {s: round(v / total, 2) for s, v in dwell_raw.items()}
    path_t = 0.0
    path_seq = []
    for s in sectors[:3]:
        path_seq.append({"sector": s, "t": round(path_t, 1)})
        path_t += rng.uniform(0.8, 1.8)
    if crossings is None:
        crossings = rng.randint(3, 14)
    dominant = max(dwell, key=dwell.get)
    return {
        "dominant_sector": dominant,
        "dwell_fractions": dwell,
        "path_sequence": path_seq,
        "crossings": crossings,
        "stability": stability,
    }


def build_sample(index, run_seed=42):
    board_preset = _BOARD_PRESETS[index % len(_BOARD_PRESETS)]
    pend_preset = _PENDULUM_PRESETS[index % len(_PENDULUM_PRESETS)]
    rng = random.Random(run_seed + index)

    primary = board_preset["primary"]
    secondary = board_preset["secondary"]
    beads = _generate_bead_positions(rng, primary, secondary, board_preset["x_bias"], board_preset["y_bias"])
    crossings = rng.randint(3, 14)
    resonance = round(rng.uniform(0.30, 0.92), 2)
    bias = round(rng.uniform(-0.5, 0.5), 2)

    board = {
        "beads": beads,
        "perturbation_factor": board_preset["pert"],
        "primary_bead": primary,
        "secondary_bead": secondary,
        "axis_x_bias": board_preset["x_bias"],
        "axis_y_bias": board_preset["y_bias"],
        "axis_position": _axis_position(board_preset["x_bias"], board_preset["y_bias"]),
        "bead_emphasis_summary": "%s and %s dominate; %s modulates the turn." % (
            primary, secondary, rng.choice([b for b in _BEAD_NAMES if b not in (primary, secondary)])),
    }

    uwp_traversal = _generate_traversal(rng, primary, pend_preset["stability"], crossings)
    dominant_sector = uwp_traversal["dominant_sector"]

    pendulum = {
        "bias": bias,
        "stability": pend_preset["stability"],
        "period_s": pend_preset["period_s"],
        "amplitude": pend_preset["amplitude"],
        "entropy": pend_preset["entropy"],
        "pattern_tag": pend_preset["pattern_tag"],
        "alpha": round(rng.uniform(0.20, 0.80), 2),
        "beta": round(rng.uniform(0.20, 0.80), 2),
    }

    quality = {
        "tracking_confidence": round(rng.uniform(0.85, 0.98), 2),
        "board_confidence": round(rng.uniform(0.90, 0.99), 2),
        "dropped_frames": rng.randint(0, 6),
        "health_flags": ["tracking_soft"] if pend_preset["stability"] < 0.50 else [],
    }

    odu = _select_odu(dominant_sector, secondary)

    matrix_resolution = {
        "concept_id": odu["concept_id"],
        "concept_name": odu["concept_name"],
        "utopian_domain": odu["utopian_domain"],
        "odu_name": odu["odu_name"],
        "odu_bits": odu["odu_bits"],
        "predicament_family_id": odu["predicament_family_id"],
        "predicament_family": odu["predicament_family"],
        "complementary_odu": odu["complementary_odu"],
        "tapestry_region_primary": odu["tapestry_region_primary"],
        "tapestry_region_secondary": odu["tapestry_region_secondary"],
        "province_or_site": odu["province_or_site"],
        "world_domain_focus": odu["world_domain_focus"],
        "failure_state_risk": odu["failure_state_risk"],
        "flourishing_state_potential": odu["flourishing_state_potential"],
    }

    turn_packet = {
        "shared": {
            "odu_name": odu["odu_name"],
            "predicament_family_id": odu["predicament_family_id"],
            "predicament_family": odu["predicament_family"],
            "tapestry_region_primary": odu["tapestry_region_primary"],
            "province_or_site": odu["province_or_site"],
            "world_domain_focus": odu["world_domain_focus"],
            "bead_emphasis_summary": board["bead_emphasis_summary"],
            "axis_emphasis_summary": "%s over %s; %s over %s." % (
                "Innovation" if board_preset["x_bias"] == "innovation" else "Restoration" if board_preset["x_bias"] == "restoration" else "Balanced axis",
                "Restoration" if board_preset["x_bias"] == "innovation" else "Innovation" if board_preset["x_bias"] == "restoration" else "other axis",
                "Centralized Rule" if board_preset["y_bias"] == "centralized" else "Distributed Commons" if board_preset["y_bias"] == "distributed" else "Balanced governance",
                "Distributed Commons" if board_preset["y_bias"] == "centralized" else "Centralized Rule" if board_preset["y_bias"] == "distributed" else "other mode",
            ),
            "pendulum_summary": "Dominant dwell in %s with %.2f stability and %d crossings." % (dominant_sector, pend_preset["stability"], crossings),
        },
        "diviner": {
            "diviner_operation_cue": odu["diviner_operation_cue"],
            "operation_register": odu["operation_register"],
            "closure_tendency": odu["closure_tendency"],
            "shadow_tendency": odu["shadow_tendency"],
            "map_maker_move": odu["map_maker_move"],
            "path_finder_move": odu["path_finder_move"],
        },
        "echo": {
            "echo_omen_cue": odu["echo_omen_cue"],
            "complement_family_id": odu["predicament_family_id"],
            "complementary_odu": odu["complementary_odu"],
            "failure_state_risk": odu["failure_state_risk"],
        },
        "seeker": {
            "seeker_manifestation_cue": odu["seeker_manifestation_cue"],
            "visible_gain": odu["visible_gain"],
            "hidden_cost": odu["hidden_cost"],
            "visible_world_effect": odu["visible_world_effect"],
            "flourishing_state_potential": odu["flourishing_state_potential"],
        },
        "narrator": {
            "narrator_handoff_cue": odu["narrator_handoff_cue"],
            "next_question": odu["next_question"],
            "failure_state_risk": odu["failure_state_risk"],
            "flourishing_state_potential": odu["flourishing_state_potential"],
        },
    }

    return {
        "label": odu["predicament_family"],
        "board": board,
        "uwp_traversal": uwp_traversal,
        "pendulum": pendulum,
        "resonance": resonance,
        "quality": quality,
        "matrix_resolution": matrix_resolution,
        "turn_packet": turn_packet,
    }


ALL_SAMPLES = [build_sample(i) for i in range(16)]  # default seed; rebuilt in main() if RANDOMIZE_BEADS


def build_turn_packet(window_id, label, board, uwp_traversal, pendulum, resonance, quality, matrix_resolution, turn_packet):
    return {
        "event": "stochastic_dreams_turn",
        "schema_version": "1.0",
        "source_id": SOURCE_ID,
        "window_id": window_id,
        "timestamp": time.time(),
        "label": label,
        "board": board,
        "beads": {
            "primary_concept": board["primary_bead"],
            "axis_position": board["axis_position"],
        },
        "uwp_traversal": uwp_traversal,
        "pendulum": pendulum,
        "resonance": resonance,
        "quality": quality,
        "odu": matrix_resolution["odu_name"],
        "matrix_resolution": matrix_resolution,
        "turn_packet": turn_packet,
        "bridge": {
            "publish_reason": "simulated",
            "sample_count": 24,
            "publish_target": TARGET_MODE,
        },
    }


def sample_to_packet(sample, index, run_seed=None):
    if run_seed is None:
        run_seed = int(time.time() * 1000)
    window_id = int(run_seed + index)
    return build_turn_packet(
        window_id=window_id,
        label=sample["label"],
        board=copy.deepcopy(sample["board"]),
        uwp_traversal=copy.deepcopy(sample["uwp_traversal"]),
        pendulum=copy.deepcopy(sample["pendulum"]),
        resonance=sample["resonance"],
        quality=copy.deepcopy(sample["quality"]),
        matrix_resolution=copy.deepcopy(sample["matrix_resolution"]),
        turn_packet=copy.deepcopy(sample["turn_packet"]),
    )


def wrap_for_target(packet, index):
    resolved_mode = resolve_target_mode()
    packet["bridge"]["publish_target"] = resolved_mode
    if resolved_mode == "hub":
        return {
            "source_id": SOURCE_ID,
            "session_id": SESSION_ID,
            "type": "stochastic_dreams_turn",
            "seq": index + 1,
            "t_device": packet["timestamp"],
            "payload": packet,
        }
    return packet


def hub_is_healthy():
    try:
        with urlrequest.urlopen(HUB_HTTP_BASE.rstrip("/") + "/health", timeout=0.5) as response:
            return 200 <= int(response.status) < 300
    except (urlerror.URLError, TimeoutError, ValueError):
        return False


def resolve_target_mode():
    if TARGET_MODE == "auto":
        return "hub" if hub_is_healthy() else "direct"
    return TARGET_MODE


def target_port():
    return HUB_UDP_PORT if resolve_target_mode() == "hub" else DIRECT_UDP_PORT


def print_startup_status(count):
    resolved_mode = resolve_target_mode()
    run_style = "sequence (%d turns)" % count if SEND_AS_SEQUENCE else "one-shot"
    print(
        "stochastic_udp_test: configured_mode=%s resolved_mode=%s target=%s:%s run=%s delay=%ss randomized=%s"
        % (TARGET_MODE, resolved_mode, TARGET_HOST, target_port(), run_style, DELAY_SECONDS, RANDOMIZE_ORDER)
    )


def send_payload(data):
    resolved_mode = resolve_target_mode()
    encoded = json.dumps(data).encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(encoded, (TARGET_HOST, target_port()))
    finally:
        sock.close()
    label = data.get("label", data.get("type", "payload"))
    site = ""
    mr = data.get("matrix_resolution", {})
    if mr:
        site = " @ %s" % mr.get("province_or_site", "")
    elif "payload" in data:
        site = " @ %s" % data["payload"].get("matrix_resolution", {}).get("province_or_site", "")
    print("Sent to %s:%s (%s): %s%s" % (TARGET_HOST, target_port(), resolved_mode, label, site))


def main():
    global ALL_SAMPLES
    run_seed = int(time.time() * 1000)

    if RANDOMIZE_BEADS:
        ALL_SAMPLES = [build_sample(i, run_seed=run_seed) for i in range(16)]

    count = max(1, min(SAMPLES_PER_RUN, len(ALL_SAMPLES)))

    selected = list(range(len(ALL_SAMPLES)))
    if RANDOMIZE_ORDER:
        random.shuffle(selected)
    selected = selected[:count]

    print_startup_status(count)

    if SEND_AS_SEQUENCE:
        for seq_idx, sample_idx in enumerate(selected):
            sample = ALL_SAMPLES[sample_idx]
            packet_base = sample_to_packet(sample, seq_idx, run_seed)
            packet = wrap_for_target(copy.deepcopy(packet_base), seq_idx)
            current_mode = resolve_target_mode()
            if current_mode == "hub":
                packet["payload"]["timestamp"] = time.time()
                packet["t_device"] = packet["payload"]["timestamp"]
            else:
                packet["timestamp"] = time.time()
            send_payload(packet)
            if seq_idx < len(selected) - 1:
                time.sleep(DELAY_SECONDS)
        print("Sequence complete. Sent %d turns covering: %s" % (
            count,
            ", ".join(ALL_SAMPLES[i]["label"] for i in selected),
        ))
    else:
        sample = ALL_SAMPLES[selected[0]]
        single = sample_to_packet(sample, 0, run_seed)
        single = wrap_for_target(copy.deepcopy(single), 0)
        current_mode = resolve_target_mode()
        if current_mode == "hub":
            single["payload"]["timestamp"] = time.time()
            single["t_device"] = single["payload"]["timestamp"]
        else:
            single["timestamp"] = time.time()
        send_payload(single)


if __name__ == "__main__":
    main()
