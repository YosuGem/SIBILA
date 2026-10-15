# About SIBILA

**Main project document · Development closure, October 12, 2026.**
**Program status: usable in its verified functions; predictive capability NOT validated. No version has been declared VALID.**

---

## 1. What SIBILA is

SIBILA is a command-line (CLI) **research linguistics** program: an instrument that measures how the emotional language of ordinary people on the internet — forums, communities, comment boards — evolves, under a falsifiable hypothesis: that certain collective shifts in that language may precede certain events.

The hypothesis is **falsifiable by design**. SIBILA seals its signals in a hash-chained registry **before** they can come true or fail, so that anyone can later check what was said, when it was said, and whether it was right. The program does not ask for faith: it asks for verification.

**What it is NOT.** It is not an oracle. It is not a commercial product. It is not a press aggregator: by express decision of its creator, media outlets (newspapers, radio, official media, opinion pieces) are **forbidden as a signal source** — "that is not collective intuition, it is social engineering." Press data (GDELT) serves solely as an external validation reference — date of first coverage of a topic — never as model input.

## 2. Origin and idea

SIBILA is born from its creator's idea: collective intuition exists and leaves traces in language before events happen; if measured with discipline — correct sources, explicit method, predictions sealed in writing and in advance — that hypothesis can be put to the test honestly instead of turning into superstition.

The project was governed from day one with written rules (`equipo/DECISIONES.md`, decisions D-001 onward): the creator decides names, versions and direction; nobody audits their own work; what is not recorded does not exist; and one meta-rule above all others —**no ego**—: mandatory self-criticism, accepting better ideas no matter who they come from, and correcting as early as possible.

## 3. Authorship and attribution

In the creator's words, which fix the correct attribution of the work:

> "SIBILA was developed through the programming of Kimi, based on Kimi's programming ideas and on my interaction, direction, follow-up, decisions and control as the project's creator. ChatGPT collaborated by providing ideas, reviews, verifications and audits."

Broken down:

- **The creator (Yosu Gem)** — original idea, purpose, continuous interaction, direction, follow-up, **all decisions** and control of the project from start to finish. The project governance (what gets done, what does not get done, when to stop) is theirs.
- **Kimi** (an AI agent by Moonshot AI) — **complete programming of the code** of the program and **technical design** (general idea of the programming, choice of tools, fields and areas of the system), executed under the creator's instructions and control. The technical tests and closure verifications documented in `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` were executed by Kimi and by Kimi's verifying sub-agents.
- **ChatGPT ("Sol")** — collaboration through **ideas, reviews, verifications and audits** on the project's design, documents and decisions.

No AI agent is an author of the project: authorship and responsibility belong to the creator. Contributions are described as they occurred; **no agent is attributed verifications it did not perform**. (Privacy note: the creator appears as "the creator" / Yosu Gem by their own decision —public pseudonym chosen on 2026-10-13, D-072—; their first and last names are not published.)

## 4. What the program does

A single command, `sibila corre`, runs the full daily pipeline (also available step by step: `ingesta`, `procesa`, `detecta`, `registro`, `informe`, `alerta`):

1. **Ingest** — collects public texts from the enabled sources (see §5), with deduplication at the point of ingest (same URL or same content does not enter twice).
2. **Processing** — text cleanup, **language detection** (fastText, model `lid.176`: 176 languages; lingua fallback detector for 8 frequent languages), quality scoring, anti-bot heuristic, stopword removal (ES/EN stopwords), n-gram extraction and **emotional analysis** (hash-verified NRC lexicons; VADER for English).
3. **Temporal detection** — over the daily series: robust z-score, CUSUM and the Mann-Kendall test, to flag unusual changes and trends.
4. **Sealed registry** — signals are written as predictions into a hash-chained file (`predicciones.jsonl`), anchored in an internal git repository (and OpenTimestamps if available). The registry is **untouchable**: verifying it is a command (`sibila registro verificar`) and part of the daily pipeline.
5. **Report** — period report in seven sections: Resumen, Tensión, Emergentes, Alertas, Anomalías, Predicciones y Exportación *(Summary, Tension, Emerging, Alerts, Anomalies, Predictions and Export)*.
6. **Alerts** — notices via Telegram or email (SMTP), with cooldown and weekly digest with 7-day anti-duplication. Without credentials, the program works the same: attempts are logged as visible failures, never silently.

Cross-cutting guarantees: SQLite database with integrity check (`sibila check` → green/red); SHA-256 manifest of the entire package (`sibila paquete verificar`); data resources (language model and lexicons) verified by SHA-256 after download; and **honest degraded mode**: if the language resources are missing and the analytic processing could not be performed, the day comes out **RED with explanation and remediation**, never fake green.

## 5. Information sources

The four initial sources, all public conversation and predominantly English-speaking:

| Source | What it provides |
|---|---|
| Reddit (`r/worldnews`) | Global news discussed by users |
| Lobsters | Technical community |
| Mastodon.social (tag "ai") | Federated conversation about AI |
| 4chan (`/pol/`) | Anonymous board — **connector available and tested, but not enabled in the default configuration** (D-075: noisy signal and reputational risk; can be enabled manually in `fuentes.toml` if desired) |

They are **pluggable** connectors under an interface contract: adding or removing one does not alter the rest of the program. The choice responds to where the volume of accessible public conversation is concentrated; the press is excluded as a signal by the creator's decision (§1).

## 6. Language scope

**SIBILA operates today in two languages: Spanish and English.** This is not an oversight: it is a design decision, and it is worth understanding before judging it.

### What the program does with languages

The pipeline distinguishes three levels:

1. **Broad detection.** The language detector (fastText, model `lid.176`) recognizes 176 languages, with a second fallback detector (lingua) for the 8 most frequent in the sources (ES, EN, PT, FR, DE, IT, CA, EU). Nothing is discarded by language at input: a text in any language is identified and labeled. *(The fallback set was going to include Galician, but the lingua 2.2.0 library does not support it — the attempt broke with `AttributeError` —; it was removed and documented. fastText does detect Galician: it is among the 176.)*
2. **Deep analysis, ES/EN only.** Emotional analysis — the heart of SIBILA's predictive method — relies on vetted lexicons (NRC-VAD and NRC Emotion Lexicon) that exist with guarantees in English (original) and Spanish (verified translation). Outside ES/EN **no emotion is invented**: the document is labeled with its language and contributes volume, but no emotional series.
3. **Sources.** The initial sources are predominantly English-speaking, which is where the volume of public conversation of the included connectors is concentrated.

### Why it was done this way

An emotional analysis with unverified lexicons is not a worse analysis: it is a false analysis. Measuring the "emotion" of a Portuguese text with an English lexicon would produce figures with a scientific appearance and arbitrary content — exactly the kind of mirage SIBILA exists to avoid. It was preferred to say "we do not measure this" rather than measure it badly.

### What the creator wants to do

The project's stated ambition is to **expand to the main languages of the internet** (Portuguese, French, German, Italian and those real usage advises): early signals do not respect linguistic borders, and part of the world's conversation simply does not happen in English or Spanish.

### The real limitations (what each new language requires)

1. **Sources** in that language (configuration; the easy part).
2. **Stopword lists** of its own, versioned (without them, n-grams fill up with empty words).
3. **Verified emotion lexicons** for that language — the hard part: they must be located, their license checked, their hash pinned, and their minimum coverage validated on a real corpus. NRC Emotion Lexicon has translations into many languages; NRC-VAD, in contrast, only has original English and translated Spanish.
4. **Tests** specific to each language (positive and negative), like those that apply to ES/EN.

### How you can improve it

If you want to add a language, the path is the one above, in that order, and the architecture already expects it: detection does not exclude any language, stopwords are interchangeable versioned lists (`STOPWORDS_VERSION`), and lexicons are loaded with integrity verification — adding a new one is adding its verified file and its pair of keys, not rewriting the engine. Contributions that do not bring a verified lexicon and tests will not be accepted as emotional analysis: they may contribute detection and volume, with the limitation marked.

## 7. Tools and technical decisions

- **Python 3.12**, **SQLite** (PostgreSQL documented as an option), single **CLI** interface `sibila` with subcommands and green/red outputs.
- Designed for **Windows** (single-script installation, operable without technical knowledge); development and all closure verification were done on **Linux** (verification on real Windows is in progress: first test run, D-077 fixes applied, second test pending — see §9).
- Dependencies pinned by version; data resources (language model, lexicons) travel separately and are verified by **SHA-256**.
- No Docker, no heavy services, no REST API, no dashboard (out of scope by the creator's decision).
- Hash-chained prediction registry with git/OpenTimestamps anchoring: falsifiability is a technical mechanism, not a promise.

## 8. Current status (as of October 12, 2026)

Verified at the development closure (full evidence in `equipo/EVIDENCIA_CIERRE_DIA1_v1.md`; the closure certificate is archived at `equipo/ACTA_CIERRE_SIBILA_v1.md`):

- **Test battery: 735 passed, 3 skipped** (the 3 skips are correct and explained: two require the real NRC lexicons, still absent; one tests degradation without lingua and only runs without lingua installed).
- **Closure repairs (Day 1), all verified with positive and negative tests, mutation tripwires (mordidas) and byte-exact hash restoration:** loading the language model through the correct API (CRIT-1); 5 alert configuration keys that were unreachable (CRIT-2); anti-false-success control — a day without real analytic processing comes out RED, not green (ALTO-1); `urllib3` update 2.7.0 → 2.8.0 due to 3 CVEs (live OSV sweep: 2.8.0 clean); and CRIT-3: the language fallback included a code that does not exist in lingua (Galician), corrected to 8 languages.
- **Cross-verification with independent agents:** full reproduction in their own environment (PASS), dependency security verification against OSV and PyPI (PASS), and a logic review that found 3 critical defects in the first version of the anti-false-success control — fixed and confirmed in a second pass with its own reproduction.
- **English end to end: OPERATIONAL (verified by an independent agent, Day 2).** Detection with the real model (5/5 varied English sentences above the 0.80 threshold, confidences 0.81–0.99), English stopwords (list `sw-1`, 161 words), n-grams free of stopword contamination, English emotion with real VADER (mathematically confirmed that VADER enters the valence; without VADER no data is fabricated — anti-bias verified) and full pipeline with exit 0 and `emo_stats`/`term_stats` series populated in `lang='en'`. Adversarial test passed: lexicons with incorrect hash → exit 1 with visible failure, never silent. Exact limitations: production emotion depends on the real NRC lexicons (absent, see §9); without lingua installed, English texts with detection confidence < 0.80 are left without a language instead of falling to the fallback.
- **Frozen reference** (`referencia/arbol_auditado_20260920/`, 131 files): intact in every session; never altered.

## 9. Limitations and pending work

Recorded in detail (status, reason, consequence, requirements and risk) in Annex D of `USER_MANUAL.md`. The essentials:

- **Real NRC lexicons absent in a typical installation if the download fails**: without them there is no emotional analysis in production. The emotion tests use fixture lexicons. The automated download works (D-077, 2026-10-15: the HTTP 406 was the rejection of python-requests' User-Agent; resolved with browser headers and hashes verified against a real download); the manual download remains as an alternate route. Installing them is a documented step, not a code change.
- **Slang — generational (age sociolects) and group or urban-tribe slang: possible future work; not in place nor validated** (raised by the creator on 2026-10-12, extended on 2026-10-13). Each generation —and each group or urban tribe— uses its own words and multi-word expressions as identity markers —*guay*, *mola mazo*, *tope*, *de puta madre*, *te cagas*…—, often with a meaning different from the dictionary one (semantic shift, intensifiers, multi-word expressions). Today the emotion layer (formal NRC lexicons) does not know them; the n-gram layer, however, **does capture them without a dictionary**: their appearance, frequency and time series land in `term_stats`, and *emerging*-term detection could register the birth of such a word. What would be pending is a slang lexicon with emotional valence per cohort or group —and its continuous maintenance, because slang is born and dies with its community—. **The analysis of these slangs remains possible future work and is neither in place nor validated** (D-019, D-069, D-075); detail in Annex D of the manual.
- **Verification on real Windows: in progress** (W1–W14 battery; first real test run on Windows 11 on 2026-10-14/15 with defects found and fixed in D-077 — templates, UTF-16 task XML, NRC 406, init message, MED-1 and MED-3 —; the second real test confirming the fixes is still pending. The closure was verified on Linux and **no document claims SIBILA works on Windows** until that test is complete).
- **12 months of real data: not done.** Without that sealed period and its contrast, **SIBILA's predictive capability is NOT validated** — and this project has never claimed it.
- **Independent human audit: pending.** The closure verifications were executed by AI agents with reproducible evidence; a human audit remains desirable.
- The synthetic test corpus tests the **plumbing** of the pipeline (ingest→series→detection→registry), not the linguistics: its artificial texts fall below the detector's confidence threshold, and the program responds correctly in RED.
- Documented minor details: the CLI was exercised *in-process* in the tests (subprocess repetition pending); a 100% unrecoverable day remains RED permanently by design (*fail-closed*); `not` appears as an English stopword (negation does not appear in n-grams — it does not affect emotion, which is computed over the full text); the n-gram extractor requires text already cleaned by the pipeline (using it on raw text mutilates capital letters without error — documented trap for reusers).

## 10. Development closure

By the creator's order (D-064), the development of SIBILA closes here: **program usable in its verified functions, visible defects, complete documentation, pending work recorded — without declaring any version VALID and without presenting the original aspirations as demonstrated.** The closure did not require SIBILA to reach all its goals: it required that what was done be real, what was not done be visible, and everything be left in a condition to be resumed or audited by anyone.

## Project documentation

SIBILA's documentation consists of **six bilingual documents** (Spanish and English, same content):

| Spanish | English | Content |
|---|---|---|
| `LEEME.md` | `README.md` | Cover page: what it is, status and quick start |
| `ACERCA.md` | `ABOUT.md` | This document: origin, authorship, what it does, languages, status, limitations |
| `MANUAL_DE_USUARIO.md` | `USER_MANUAL.md` | Installation, configuration, CLI usage and technical annexes (architecture, security, tests, pending tasks, preservation) |

*Historical project governance: `equipo/DECISIONES.md` (D-001 onward). Closure evidence: `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` and the final certificate (`equipo/ACTA_CIERRE_SIBILA_v1.md`).*
