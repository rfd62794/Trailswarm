# Can we publish trained vision weights? (game-frame classifiers)

Date: 2026-11-14. Status: research notes, NOT LEGAL ADVICE. Sources were found by web search on
2026-11-13/14; most are law-firm summaries, not the opinions themselves. Anything not confirmed is
marked UNVERIFIED.

## The question

Robert trains small local vision models (sprite classifier; NPC-movement and map/location-from-pixels
models) on crops and frames from Game Boy games (Pokemon Red; maybe Super Mario Land), labelled from
game RAM. Code and recipe will be MIT and public. Extracted-art datasets stay local. ROMs are never
published. Open decision: may the TRAINED WEIGHTS be published?

## Short answer

No court anywhere has held that weights of a small discriminative classifier are an infringing copy
of its training images. The strongest adverse US authority (Thomson Reuters v. Ross) concerned a
non-generative tool but turned on a competing substitute product, which a sprite classifier is not.
The residual risk is less "a court would find infringement" and more "a rights holder who dislikes
Pokemon-adjacent artifacts sends a takedown and the host complies". That risk is small for
classifier weights and is the same kind of risk the project already carries by being Pokemon-themed.

## 1. US copyright: are weights a copy or derivative of the training images?

No US court has squarely decided this for weights. Evidence by source:

- Thomson Reuters v. Ross (3d Cir.). Reported decided 2026-09-29: the panel affirmed that Ross's use
  of Westlaw headnotes to train a (non-generative) legal-search AI was not fair use; use called
  "minimally transformative, at best"; factors 1, 3, 4 against Ross. Commentators stress it was a
  non-generative tool built to substitute for Westlaw and that the court framed the holding
  narrowly. The opinion was reported as sealed, so details are secondhand.
  - https://ipwatchdog.com/2026/09/30/third-circuit-affirms-revised-fair-use-ruling-against-ross-ai-legal-research-platform-in-sealed-opinion/ (2026-09-30)
  - https://www.americanbar.org/groups/business_law/resources/business-law-today/2026-september/thomson-reuters-v-ross-one-year-later/ (2026-09)
  - https://www.akingump.com/en/insights/ai-law-and-regulation-tracker/third-circuit-finds-ai-training-use-of-westlaw-headnotes-is-not-fair-use-thomson-reuters-enterprise-centre-gmbh-v-ross-intelligence-inc
  - Relevance: the closest thing to adverse appellate law, and it concerns a classifier-like
    (non-generative) system. Key distinguishing fact is market substitution. Nobody buys a
    Pokemon-sprite classifier instead of Pokemon Red. Not a guarantee.
- Bartz v. Anthropic (N.D. Cal., Alsup, June 2025): training on lawfully acquired books held
  transformative fair use; pirated library copies not. Case settled for $1.5B; final approval
  reported 2026-07-20 (judge name reported inconsistently across sources). The ruling was never
  tested on appeal because of settlement.
  - https://thenextweb.com/news/anthropic-1-5-billion-copyright-settlement-approved?type=AI (2026-07-21)
  - https://www.polsinelli.com/publications/ai-vs-authors-update-court-approves-historic-anthropic-settlement-while-meta-litigation-continues
  - Relevance: acquisition matters. Robert's frames come from his own legally owned ROM running in
    an emulator, not from piracy-of-the-art-itself, but see the ROM caveat in section 2.
- Kadrey v. Meta (N.D. Cal., Chhabria, 2025-06-25): Meta won summary judgment on fair use mainly
  because plaintiffs offered no market-dilution evidence; dicta says a better record could win.
  Applies only to those plaintiffs.
  - https://www.authorsalliance.org/2025/06/26/meta-wins-on-fair-use-for-now-but-court-leaves-door-open-for-market-dilution/ (2025-06-26)
  - Relevance: harm theory is about market substitution and dilution. A classifier generates
    nothing, so the dilution theory has nothing to attach to.
- US Copyright Office, Part 3 (generative AI training), pre-publication 2025-05-09: weights "can" be
  infringing copies if they memorize and embody substantial protectable expression; if a model can
  reproduce a near-identical copy without the work in the prompt, the reproduction right is
  implicated. Training a foundation model on diverse data "will often be transformative". Final
  version status UNVERIFIED (not found). The report is not binding on courts.
  - https://www.jenner.com/en/news-insights/client-alerts/us-copyright-office-releases-pre-publication-version-of-report-on-copyright-issues-in-generative-ai-training (2025-05)
  - https://datamatters.sidley.com/2025/05/28/generative-ai-meets-copyright-scrutiny-highlights-from-the-copyright-offices-part-iii-report/ (2025-05-28)
- Andersen v. Stability AI (N.D. Cal.): the artist case that argues weights embody copies. I found
  no reliable report of a 2026 merits ruling on the weights-as-copies question. UNVERIFIED. One
  low-quality blog claimed trial dates and an appeal; not relied on.
- Getty v. Stability AI (UK High Court, 2025-11-04, [2025] EWHC 2863 (Ch)): Getty lost the
  secondary-infringement claim. The court accepted weights can be "articles" but held they are not
  "infringing copies" because they do not store or contain the training works, operating at a high
  level of mathematical abstraction. Getty won narrowly on trade mark (watermark-like outputs).
  Appeal status UNVERIFIED. UK law, persuasive only in the US. Getty's US claims continue.
  - https://cm.twobirds.com/en/insights/2025/uk/stability-ai-defeats-getty-images-copyright-claims-in-first-of-its-kind-dispute-before-the-high-cour
  - https://www.mishcon.com/news/getty-images-v-stability-ai-unpacking-the-high-courts-judgment
  - https://www.aippi.org/news/getty-images-v-stability-ai-uk-high-court-finds-no-secondary-copyright-infringement-in-landmark-genai-ruling/

### Tiny classifier vs generative model: memorization

- The legal hook in the Copyright Office report and in Getty is whether the weights can reproduce
  protectable expression. Generative models can (extraction attacks); a classifier outputs a label
  or a coordinate, not pixels.
- Literature: discriminative models are not designed to output training data; leakage shows up as
  membership inference and model inversion (partial reconstruction), and "extractability" notions
  built for generative models do not apply directly. I did not find a source directly measuring
  memorization in small CNN image classifiers; that part is UNVERIFIED, and model inversion on a
  small classifier trained on a few hundred distinct 8x8-tile sprites could in principle produce a
  blurry sprite-like image (this is my inference, not a sourced finding).
  - https://arxiv.org/pdf/2311.03075 (SoK: Memorisation in ML)
  - https://arxiv.org/pdf/1705.07663 (LOGAN, membership inference)
- Practical point: Game Boy sprites are tiny, low-entropy, and the label vocabulary is small.
  A model trained to map pixels to class ids has orders of magnitude less capacity to "contain"
  the art than a diffusion model, and regenerating art is not its function.
- Weak spot for Robert specifically: an autoencoder, a reconstruction head, embeddings, or any
  generative component WOULD change this analysis. Keep published models discriminative only.

## 2. Nintendo / The Pokemon Company posture

- No reported takedown of a model or dataset trained on game sprites, and nothing found about
  Hugging Face removing one. Absence of evidence in a few searches, not proof. UNVERIFIED beyond that.
- Known posture, all about distributing the games, assets, or competing products, not private use:
  - Yuzu: Nintendo sued in 2024; settled for $2.4M plus permanent injunction. Ryujinx went offline
    afterwards (terms not public).
    https://pcgamer.com/software/nintendo-v-yuzu-switch-emulator-shut-down-settlement
    https://pcgamer.com/gaming-industry/switch-emulator-ryujinx-goes-offline-after-creator-gets-an-offer-from-nintendo-they-cant-refuse
  - Fan games/tools: Pokemon Uranium and Prism (2016) shut down; Relic Castle fan-game hosting site
    taken down by reported DMCA (2024); Pokemon Essentials tool removed from official hosts.
    https://gamesradar.com/after-almost-10-years-unofficial-pokemon-website-known-for-sharing-fan-made-games-shuts-down-after-reportedly-receiving-a-dmca-takedown-notice
    https://www.gamedeveloper.com/console/nintendo-files-takedown-notice-against-i-pokemon-i-fan-game-creation-tool
  - A former Pokemon Company lawyer says action is likelier when projects fundraise or get press.
    https://videogameschronicle.com/news/former-pokemon-lawyer-says-fundraising-and-press-coverage-lead-to-fan-project-takedowns
  - Nintendo (via contractor Tracer) DMCA'd AI-generated Mario images on X (2024) and has vowed
    action on AI spoofs (Sora 2, 2025). These target outputs that look like their characters, not
    analytic models.
    https://mobilesyrup.com/2024/09/24/nintendo-ai-generated-mario-images-takedowns/
    https://www.nme.com/news/nintendo-vows-necessary-action-over-ai-mario-spoofs-sora-2-openai-3897495
  - Palworld: Nintendo/Pokemon Co. sued Pocketpair on PATENTS, not copyright, so it says little
    about weights; its relevance is that Nintendo picks claims by what it can win. (Detail
    UNVERIFIED in this pass; patent basis is from general knowledge.)
- ROM caveat: Robert's own dumped ROM used privately for analysis is a common-practice grey area
  (backup/emulation). It is not what is being published. Never publish ROMs, save states with
  copyrighted art embedded in a shareable dataset, or sprite sheets. (Matches standing hard rule.)

## 3. Industry precedent: weights trained on game frames

All of these ship code; several ship weights; none found taken down. "Not found taken down" is
based on a search, not an exhaustive check.

- PokemonRedExperiments (Peter Whidden): public repo, widely covered (TechCrunch 2023-10-18). Repo
  requires the user to supply the ROM. Whether the original repo ships checkpoints is UNVERIFIED
  (a fork documents "Running the Pretrained Model Interactively").
  https://www.github.com/PWhiddy/PokemonRedExperiments
  https://techcrunch.com/2023/10/18/after-50000-hours-this-ai-can-play-pokemon-red
  Also the academic write-up: https://arxiv.org/pdf/2502.19920v1
- DIAMOND (Atari world model; CS:GO branch): README downloads pretrained world model and policy
  from Hugging Face Hub; authors say they release agents and playable world models. This is a
  GENERATIVE (diffusion) model of game frames, a harder case than Robert's, and it is hosted.
  CS:GO weight hosting UNVERIFIED.
  https://github.com/eloialonso/diamond
- Atari agents: RL Baselines3 Zoo ships pretrained agents; many community Atari agents on Hugging
  Face; Atari Zoo (IJCAI 2019). These are policy networks, a different class from vision
  classifiers. ROMs are fetched separately via AutoROM license acceptance.
  https://www.ijcai.org/Proceedings/2019/452
  https://huggingface.co/joosma/atari
- GameNGen (Doom), MineRL/VPT, Procgen: not checked in this pass. UNVERIFIED. (Procgen uses
  procedurally generated, openly licensed art, so it is not a relevant comparison anyway.)
- Pattern: code and weights go public, ROMs do not, datasets of raw frames mostly do not. Robert's
  plan already matches this pattern.

## 4. Risk-reduction options and EU angle

- Publish discriminative-only models (classifier, regressor for map id and x/y). Avoid any
  decoder/autoencoder/embedding export that can reconstruct art.
- Synthetic or procedural training: train on a re-rendered or procedurally generated sprite set
  (own art, or open-licensed). Removes the copying theory but the model then may not transfer to
  real game frames, which is the point of the model; usable for a "demo weights" tier.
- Recipe-only (status quo): zero weight risk; costs reproducibility and downstream usefulness.
- Licensing notes: add a README/model card statement: weights trained on frames from a
  legally owned copy of the game; no game assets included; not affiliated with Nintendo, Game Freak
  or The Pokemon Company; MIT covers the code and weights as Robert's own work only, with no
  claim over underlying game art. This does not create a right, but it reduces confusion and
  shows good faith. Trademark: avoid using Pokemon logos or branding in the repo name or model
  name where possible (naming such as "red-sprite-classifier" is fine).
- Respond-to-notice plan: host on a repo (GitHub/Hugging Face) where a takedown affects only the
  weights file; keep recipe and code separate so removal is cheap. Keep hashes so a re-train
  reproduces.
- EU: the DSM Directive TDM exception allows mining unless rights are reserved; the AI Act
  Art. 53 copyright-policy duty applies to general-purpose AI models, not to small task-specific
  classifiers. I found no "small classifier exemption" text; the point is that a sprite classifier
  is plainly not a GPAI model. Sources are commentary, not the Regulation itself. Art. 53(2) open
  source relief is narrow and does not remove copyright duties for GPAI providers.
  https://www.casrai.org/guides/eu-ai-act-article-53-open-source-exemption
  https://www.cliffordchance.com/insights/resources/blogs/ip-insights/2025/10/copyright-compliance-under-the-eu-ai-act-for-gpai-model-providers.html
  https://www.taylorwessing.com/en/insights-and-events/insights/2024/05/ai-act-und-copyright
  Robert is US-based; EU relevance is only downstream users.

## Options for Robert

| Option | Risk | Cost to Robert |
|---|---|---|
| A. Publish recipe only (status quo) | Low | Users must train themselves; less reach and weaker reproducibility |
| B. Publish small discriminative classifier weights (sprite id, map id, NPC motion), no generative or decoder parts, with a disclaimer README | Low (low-to-med if a rights holder objects; likely only a takedown, not a suit) | An hour of model-card and README; a plan to pull weights if notified |
| C. Publish weights trained on synthetic or re-drawn sprites | Low | Training and validation work; weaker accuracy on real frames |
| D. Publish generative or reconstruction-capable models (autoencoder, world model) | Medium to high (memorization is the legal hook; Nintendo is active on AI look-alikes) | Highest legal and takedown exposure; not recommended |
| E. Publish weights AND extracted sprite crops or datasets | High | Violates the standing rule; direct copying of art |

## Recommendation (not legal advice)

Option B, with A as the fallback: publish only the small discriminative weights (classifier and
coordinate regressors), keep reconstruction-capable heads out, keep datasets and ROMs local, add a
model card with the non-affiliation and provenance notes above, and keep the weights file
separable so it can be pulled in one commit if a notice arrives. Hold off on anything generative
(option D) and on any Super Mario Land weights until Pokemon weights have been out a while without
incident. Do not rely on this document for a legal conclusion; if a notice ever arrives, or the
project starts earning money or drawing press, get a short paid consult (IP lawyer) before
responding.

## Unverified or open items

- Final Part 3 Copyright Office report status; Andersen merits status; Getty UK appeal status.
- Whether PokemonRedExperiments ships checkpoints; DIAMOND CS:GO weights hosting; GameNGen weights.
- Any model/dataset takedown by Nintendo or The Pokemon Company (none found; search was shallow).
- Ross 3d Cir. opinion text (sealed, secondhand).
- Palworld patent basis (from general knowledge).
