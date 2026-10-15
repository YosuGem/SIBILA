# SIBILA User Manual

**Document date:** 2026-10-12 · **Status of the code described:** `nucleo/` tree after the Day 1 closure repairs (CRIT-1, CRIT-2, ALTO-1, CRIT-3 and the urllib3 2.8.0 pin; see Annex C).
**This manual gathers in a single document the installation, configuration, CLI usage and technical annexes (architecture, security, tests and status, pending tasks and preservation). Spanish version: `MANUAL_DE_USUARIO.md`.**

> **Note for English readers:** program messages are shown verbatim in Spanish, as the program emits them.

> Evidence labels used in this manual: **[EJEC]** = verified by real execution (with date); **[INSP]** = verified by direct inspection of the cited code; **[DOC]** = recorded in the project reports, cited without re-executing.

**Contents:** §1 Installation · §2 Configuration · §3 CLI Usage · Annex A Architecture · Annex B Security and privacy · Annex C Tests and real status · Annex D Pending tasks · Annex E Preservation.

---

## 1 · Installation

### 1.1 Requirements

| Requirement | Detail | Evidence |
|---|---|---|
| **Python** | Target: **3.12** (verified on 3.12.12). Functional minimum: **3.11** (because of `tomllib`, used to read the configuration). With 3.11 or 3.13+ `sibila check` starts but flags **AVISO** *(warning)* "distinto del objetivo 3.12; no probado" *(different from the 3.12 target; not tested)*. With <3.11 the program does not work. | [INSP] `sibila/cli.py` (_cmd_check); [EJEC] suite run on Python 3.12.12 on 2026-10-12 |
| **Operating system** | Developed on **Linux x86_64**. Designed for **Windows** (the `.bat` files, the task XMLs and `instalar.bat` are Windows-only by design). **Installation and operation verified in two real Windows 11 tests (2026-10-15, W1–W14)**; only the natural 24 h cycle remains pending (see Annex D). | [INSP] + [DOC] closure audit + Windows tests |
| **Disk** | ~300 MB extra if `lingua` is installed (its wheel weighs ~170 MB plus the loaded model); the rest is modest (the DB grows with the data). `check` warns if <1 GB remains free. | [INSP] `cli.py` (space warning), [DOC] D-066 / LEEME_T2 |
| **Network** | Only for: dependency installation, data resource download, **real ingest**, **alerts** and downloading the GDELT reference (`informe --actualizar-gdelt`). The test battery and all local processing work without network. | [INSP] |
| **Git (optional)** | Needed only for anchoring the sealed registry (`registro anclar`). Without git: anchoring stays "pendiente" *(pending)* with an AVISO, never a failure. | [INSP] `sibila/anclaje.py`, `doctor.py` |
| **ots (optional)** | `opentimestamps-client` (not in `requirements.txt`; goes in a future requirements-extra). Without it, the external timestamp stays disabled (AVISO). | [INSP] `requirements.txt`, `anclaje.py` |

### 1.2 Dependencies (exact pins from `requirements.txt`)

All versions are **pinned** for reproducible installation:

| Package | Pin | What for |
|---|---|---|
| feedparser | `6.0.12` | RSS/Atom (Lobsters, Mastodon, Reddit RSS fallback) |
| sgmllib3k | `1.0.0` | feedparser dependency. **Watch out:** it only exists as an sdist on PyPI (the module is called `sgmllib`); that is why the installer can NOT use `--only-binary=:all:` unless wheels are pre-built |
| requests | `2.34.2` | HTTP (ingest, GDELT, Telegram, resource download) |
| urllib3 | `2.8.0` | Transitive of requests, pinned. **Raised from 2.7.0 on 2026-10-12** due to 3 CVEs fixed in 2.8.0 (see Annex B) |
| idna | `3.18` | Transitive of requests |
| charset-normalizer | `3.4.9` | Transitive of requests |
| certifi | `2026.6.17` | Transitive of requests |
| fasttext-predict | `0.9.2.4` | Language detection (176 languages, model `lid.176.ftz`). Imported as the `fasttext` module |
| lingua-language-detector | `2.2.0` | Language fallback when fastText hesitates (frozen set of 8 languages; see §3, "What it truly analyzes"). **Optional** |
| vaderSentiment | `3.3.2` | VADER component of English emotion |

[Evidence: INSP of `requirements.txt`; OSV vulnerability sweep of 2026-10-12: all pins clean — see Annex C.]

**No heavy dependencies:** numpy, scipy and datasketch are not used (MinHash is implemented by hand with the stdlib; recorded decision D-039: datasketch 1.6.5 imports scipy at module level). The fasttext/lingua/vader/requests imports are **lazy**: without them the package imports the same and degrades.

### 1.3 Step-by-step installation

#### 1.3.1 Windows (planned path; verified in two real Windows 11 tests, 2026-10-15)

The package includes `instalar.bat`, designed so that each step verifies or aborts with a clear message, without requiring administrator:

0. Prerequisite: **Python 3.12** from python.org, checking "py launcher" during installation.
1. Copy the **ENTIRE folder** (not just `sibila\`: `resumen.py`, the `.bat` files, `requirements.txt`, `tools\` and the configuration templates are also needed) to a **short path outside OneDrive/Documents** (recommended: `C:\sibila`).
2. **Antivirus exclusion (manual, important):** Windows Security → Virus & threat protection → Exclusions → add the folders `C:\sibila\datos` and `C:\sibila\logs`. Without this, Defender may block the database mid-write (risk no. 1 identified for Windows).
3. Double-click **`instalar.bat`**. Do not continue until you see `=== Instalacion completa ===`.

The installer executes, in order: materializes `config.toml`/`fuentes.toml` if missing (does not overwrite existing ones) → creates `.venv` → installs `requirements.txt` → downloads the data resources (§1.4) → generates `config.local.toml` with a new `hmac_key` (idempotent, with restricted permissions via `icacls`) → creates the database (`sibila init`) → demands the `check: VERDE` gate → shows the `sibila doctor` report → verifies package integrity **at destination** (`sibila paquete verificar`) → schedules the two daily tasks (§1.6).

[Evidence: INSP of `instalar.bat` + two real Windows 11 tests (2026-10-15): the second passed W1–W14 with the first test's six defects fixed. Only the natural 24 h cycle remains pending — see Annex D.]

**Installer options:**
- **Without lingua** (saves ~300 MB): before installing, in that same console, `set SIBILA_SIN_LINGUA=1` and then `instalar.bat`. Documented consequence: documents whose language is doubtful for fastText are left without a language (not studied); `doctor` will remind it as an AVISO "(skip explícito)" and writes the sentinel `<data_dir>/recursos/SIN_LINGUA`.
- **No network during installation:** the installation **is not interrupted**; the program remains in degraded mode (no language or emotion) until `tools\descargar_recursos.py` is run with network.

#### 1.3.2 Linux (development environment, verified)

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/descargar_recursos.py   # data resources (§1.4)
.venv/bin/python -m sibila init                # creates DB and folders (idempotent)
.venv/bin/python -m sibila check               # must say "check: VERDE"
.venv/bin/python -m sibila doctor              # post-installation report
```

`init` is idempotent by construction (all DDL uses `IF NOT EXISTS`) and never deletes or recreates an existing database.

### 1.4 Data resources (not via pip)

Two families, both downloaded by `tools/descargar_recursos.py` to `<data_dir>/recursos/` (by default `datos/recursos/`):

#### 1.4.1 fastText language model `lid.176.ftz`

- **Official origin:** `https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz` (Facebook AI Research, MIT license).
- **Size and SHA-256 pinned in the code** (`tools/descargar_recursos.py`): 938 013 bytes, SHA-256
  `8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83`
  (verified by double download from the official URL, decision D-030). [EJEC 2026-10-12: this file was actually downloaded and verified; it is the only resource confirmed against its official source.]

#### 1.4.2 The four NRC lexicons (emotion)

| File (normalized) | Origin | SHA-256 pinned in `sibila/procesado/emocion.py` |
|---|---|---|
| `nrc_vad_en.txt` | NRC-VAD Lexicon **v2.1** (EN unigrams, scores already in [−1,1]) | `71518ac0e3cea299b43714190b4fc3ec55acf4302eb04b9c36d148aaffbe9d81` |
| `nrc_vad_es.txt` | NRC-VAD Lexicon **v1** (Spanish sheet; transposed to palabra_es⇥v⇥a, scores rescaled to [−1,1] on load) | `0ac2f639f8b222ef5bce14dac26bb6dd34217d80a447d6443c2a21fa77da75f7` |
| `nrc_emociones_en.txt` | NRC Emotion Lexicon v0.92 (EN wordlevel; positive/negative rows removed) | `0b1ce8ec1297f523eee882fd3973cca394c0b20ff54c3beb0dbd952efe314a81` |
| `nrc_emociones_es.txt` | NRC Emotion Lexicon (Spanish sheet; transposed to palabra_es⇥emoción_en⇥1) | `60124be34075390015aea04eb86574a4ae84f943f5fb5c9a196ec63a79abe46e` |

- **License:** NRC-VAD and NRC Emotion Lexicon © National Research Council Canada — free **non-commercial** use (research/education). That is why **they are not redistributed**: they are downloaded during installation from `https://saifmohammad.com/WebDocs/Lexicons/…`. [INSP of the docstring of `tools/descargar_recursos.py`.]
- **Real status as of 2026-10-15:** the automated download works (the HTTP 406 was the official server rejecting python-requests' default `User-Agent`; resolved in D-077 with browser headers) and **the 4 pinned SHA-256 were verified against real downloads** on that same day. The manual browser download remains as a documented alternate route. Detail and consequences in Annex D.

#### 1.4.3 How to verify the hashes by hand

```bash
# Linux
sha256sum datos/recursos/lid.176.ftz
# Windows (PowerShell)
Get-FileHash .\datos\recursos\lid.176.ftz -Algorithm SHA256
```

and compare with the values above. The program does it for you: `sibila doctor` verifies the SHA-256 of the 5 resources on every run (§1.5).

#### 1.4.4 What happens if they are missing: degraded mode (documented in code)

- **Without `lid.176.ftz` or without fasttext:** `lang` stays `NULL` in all documents → no linguistic analytics (those excluded by language are counted). The daily `corre` pipeline detects this case and ends in **RED (exit 1)** with explicit remediation — it does not give a false success (ALTO-1 repair, 2026-10-12). A day **without documents** remains legitimate success.
- **Without the NRC:** emotion disabled (the day's `emo_stats` aggregates are neither recalculated nor deleted in degraded mode: previous series are preserved). The remediation is `sibila procesa --todo` after placing the resources.
- **Without lingua:** the doubtful-language fallback is disabled (`doctor` AVISO).
- **Without VADER:** EN emotion is disabled (`vector()` returns None for `en`; a halfway average is never invented); ES is not affected.

In all cases `procesa` records the `procesa.modo_degradado` metric and warns; nothing fails silently.

### 1.5 Post-installation verification

#### `sibila check` — the gate

Green/red verification of the database and the environment. All checks run even if one fails (full report); **it repairs nothing** (repairing is `init`'s job). It checks: Python interpreter · package resources accessible · configuration loadable · `data_dir` existing and writable (probe) and free space · the database opens · `PRAGMA integrity_check` · pragmas `journal_mode=wal`, `foreign_keys=1`, `busy_timeout=30000` · schema v1 conformant (12 tables, columns, domain literals and indexes) · `echo_flags` empty (Phase 1 contract) · git and ots (AVISO, never a failure) · the file log truly grows. Result: `check: VERDE` (exit 0) or `check: ROJO` (exit 1). [INSP `sibila/cli.py::_cmd_check`.]

#### `sibila doctor` — the package health report

Different from `check` (which is the installer gate): `doctor` audits the complete installation in **read-only** mode (SQLite connection `mode=ro`; the only write is a temporary probe in `data_dir`):

| Check | Fails if | Warns if |
|---|---|---|
| D1 · DB exists, opens, schema intact (12 tables) | missing/broken | — |
| D2 · dependencies importable (`feedparser`, `requests`, `sgmllib`, `fasttext`, `vaderSentiment`; probing without importing the heavy ones) | any missing | `lingua` absent ("fallback desactivado" *(fallback disabled)*; "(skip explícito)" if the `SIN_LINGUA` sentinel exists) |
| D3 · resources with SHA-256 (`lid.176.ftz` + 4 NRC) | hash mismatch, or hashes not pinned in code | resource absent ("modo degradado; corre tools\descargar_recursos.py" *(degraded mode; run tools\descargar_recursos.py)*) |
| D4 · `data_dir` writable | not writable | — |
| D5 · git and ots | — (never a failure) | absent ("anclaje pendiente" *(anchoring pending)*) |
| D6 · `config.local.toml` with `hmac_key` | — (never a failure) | absent ("author_hash quedará NULL") |

Result: `doctor: SANO (n avisos)` (exit 0; warnings do not penalize) or `doctor: ROTO (n fallos)` (exit 1). [INSP `sibila/doctor.py`.]

**Known limitation (MED-3, open):** `doctor` imports the SHA-256 of `lid.176.ftz` from `tools/`, which is not an installable package; run from a working directory other than the project root it may give a spurious verifiability FAILURE. The `.bat` files mask this by doing `cd` first.

### 1.6 Windows: scheduled tasks

The installer schedules **two daily tasks** (templates `tarea_ingesta.xml` and `tarea_diaria.xml`; `instalar.bat` replaces the placeholders `{SIBILA_RAIZ}` and `{START_BOUNDARY}` with inline PowerShell and writes the final XML in UTF-8 **without BOM**, which `schtasks` would reject with a BOM; the same logic, factored and testable, lives in `tools/preparar_tarea.py`):

| Task | Time (local) | Script | What it does | Limit |
|---|---|---|---|---|
| **SibilaIngesta** | 07:00 | `ingesta_diaria.bat` | Only `sibila ingesta --en-vivo`. Collection is the unrecoverable part (if a day is missing, that day is lost); that is why it runs alone and first | PT1H |
| **SibilaDiario** | 07:45 | `pipeline_diario.bat` | Full pipeline: ingesta → procesa → detecta → registro sellar → registro anclar → **registro verificar** (integrity is checked daily) → alerta enviar → alerta digest | PT2H |

Both: `InteractiveToken`, `LeastPrivilege`, `IgnoreNew` (no overlapping instances), `StartWhenAvailable` (if the PC is off at that time, they run at power-on), retry on failure 3 × 5 min. The double ingest (07:00 + 07:45) is justified in D-048: collection is the unrecoverable part; everything else is re-runnable. Logs: `logs\ingesta_tarea.log` and `logs\pipeline_diario.log`. `pipeline_diario.bat` exits with exit 1 if a link fails (the task's `RestartOnFailure` retries it); the digest without configured channels gives exit 0 with an AVISO (not a failure). [INSP of `tarea_*.xml`, `*_diaria.bat`, `pipeline_diario.bat`.]

**Honest warning:** these files were statically reviewed (correct CRLF in the `.bat`, placeholders) and **have now been executed in two real Windows 11 tests** (2026-10-15): the second passed W1–W14, including importing the UTF-16 tasks via `schtasks`. Only the natural 24 h cycle remains pending (see Annex D).

**Uninstall:** `schtasks /delete /tn SibilaIngesta /f` and `schtasks /delete /tn SibilaDiario /f`, and delete the folder.

### 1.7 Common installation problems

| Symptom | Probable cause | What to do |
|---|---|---|
| `check` RED due to schema | Malformed pre-existing database | `init` never recreates: review the Spanish message; as a last resort move the DB and re-init (losing the data) |
| `doctor` says "dep NO importable" | Dependencies not installed | Re-run `instalar.bat` (reinstalls dependencies) |
| `doctor` says "recurso ausente" | Resource download failed (no network or server block) | With network: `.venv\Scripts\python.exe tools\descargar_recursos.py` (sends browser headers since D-077). Alternative: manual download (§1.4.2) |
| "SHA-256 no coincide" on a resource | Corrupt download or tampered file | Delete the file and re-download (the downloader NEVER silently overwrites a file with a bad hash) |
| `sgmllib3k` won't install with `--only-binary` | Only exists as an sdist | Install without `--only-binary`, or pre-build wheels (`pip wheel -r requirements.txt`) |
| "database is locked" during operation | Another window/process of the program open | Close other windows and retry (there is a 30 s `busy_timeout`); if it persists, restart the PC |

---

## 2 · Configuration

**Document date:** 2026-10-12 · **Source:** direct inspection of `sibila/config.py`, `config.toml`, `config.local.toml.example` and `fuentes.toml`.

### 2.1 The three levels (and their precedence)

```
defaults del código  <  config.toml  <  config.local.toml  <  variables SIBILA_*
```

(This chain is literally in the header of `config.py`.)

| Layer | Where | What for | Versionable? |
|---|---|---|---|
| Defaults | In the code (`DEFAULTS`): `data_dir="datos"`, `log_level="INFO"` | So the program starts without any file | — |
| `config.toml` | Project root | **Non-secret** settings (paths, log level) | **Yes** (and that is why the `[secretos]` section is banned in it) |
| `config.local.toml` | Project root | **Secrets** (hmac_key, tokens, SMTP) | **No**: it is in `.gitignore` and excluded from the package manifest |
| `SIBILA_*` environment | Environment variables | Override any file (useful in tasks/CI) | — |

- `config.toml` absent → **warning** ("usando valores por defecto" *(using default values)*), not an error.
- `config.local.toml` absent → **normal case** (secrets are opt-in): total silence.
- **Relative paths** are anchored to the **project root**, never to the current working directory (trap T3); an **empty environment variable is ignored** (an empty string would anchor paths to the root — trap M6).

### 2.2 Valid keys (closed whitelist)

The configuration validates against a **whitelist** to catch silent typos: any unlisted section or key is an **error** at startup. Only these exist:

#### Section `[general]`
| Key | Type | Notes |
|---|---|---|
| `data_dir` | text (path) | Data folder; default `datos` |
| `db_path` | text (path) | SQLite database path; if not given, derived from `data_dir` |
| `log_level` | text | Must be one of the allowed levels (`DEBUG`, `INFO`, …) |

#### Section `[secretos]` (only in `config.local.toml` or environment)
| Key | Type | Notes |
|---|---|---|
| `hmac_key` | text | HMAC key for `author_hash` (author anonymization). Without it, `author_hash` stays `NULL` |
| `telegram_token` | text | Telegram bot token |
| `smtp_password` | text | SMTP password |
| `telegram_chat` | text | **(new)** Telegram destination chat/channel |
| `smtp_host` | text | **(new)** SMTP server |
| `smtp_usuario` | text | **(new)** SMTP user |
| `smtp_puerto` | **integer 1–65535** | **(new)** SMTP port (strict validation, §2.4) |
| `smtp_destino` | text | **(new)** email recipient |

The **5 new keys** (`telegram_chat`, `smtp_host`, `smtp_usuario`, `smtp_puerto`, `smtp_destino`) were added in the **CRIT-2** repair (2026-10-12): before, the alert keys were not recognized and alerts could not be configured without an "unknown key" error.

#### Equivalent environment variables (the 11)
`SIBILA_DATA_DIR`, `SIBILA_DB_PATH`, `SIBILA_LOG_LEVEL`, `SIBILA_HMAC_KEY`, `SIBILA_TELEGRAM_TOKEN`, `SIBILA_SMTP_PASSWORD`, `SIBILA_TELEGRAM_CHAT`, `SIBILA_SMTP_HOST`, `SIBILA_SMTP_USUARIO`, `SIBILA_SMTP_PORT`, `SIBILA_SMTP_DESTINO`.

### 2.3 Golden rule: secrets only in local or environment

- `config.toml` (the versionable file) **cannot contain `[secretos]`**: if it has it, `load_config` raises `ConfigError` explaining that secrets go in `config.local.toml` or `SIBILA_*` variables.
- Secrets are stored in a `MappingProxyType` with `repr=False`: **they never appear in the repr or in logs** (trap T4). The installer additionally hardens `config.local.toml` permissions (`icacls` on Windows).
- The package manifest (`sibila paquete generar`) **excludes** `config.local.toml*` (except the `.example`) so that no secret is distributed.

### 2.4 `smtp_puerto`: strict validation

Special case documented in the code:
- In TOML it is written as a natural integer: `smtp_puerto = 587`.
- An environment variable arrives as **text**; if it is digits-only ASCII it is **normalized to an integer**.
- Rejected: booleans (`true`), non-integers, and any value outside **1–65535**, with explicit messages (e.g. `'secretos.smtp_puerto' fuera de rango (1-65535): 70000`).

### 2.5 Common errors and their meaning

| Error / symptom | Cause | What to do |
|---|---|---|
| `empieza con BOM UTF-8; guárdalo como UTF-8 sin BOM` | Notepad (or another editor) saved the `.toml` with a BOM. `tomllib` would only say the cryptic "Invalid statement", so the code detects it and says it clearly | Save as **UTF-8 without BOM** |
| `TOML inválido …` (`TOMLDecodeError`) | Broken TOML syntax (quotes, brackets, misplaced `=`) | Review the line the error indicates |
| `sección desconocida [x]` / `clave desconocida 'x.y'` | Typo or unsupported key | Fix the name against the §2.2 whitelist |
| `config.toml NO puede tener [secretos]` | Secrets in the versionable file | Move them to `config.local.toml` or to `SIBILA_*` variables |
| `'secretos.smtp_puerto' debe ser un entero` / `fuera de rango` | Port wrongly typed or outside 1–65535 | Use a valid integer (e.g. `587`) |
| `'general.log_level' debe ser una de [...]` | Unrecognized log level | Use a valid level (`INFO`, etc.) |
| A `SIBILA_*` variable "has no effect" | It is defined but **empty** | Empty strings are ignored on purpose; define it with a value |

### 2.6 Sources (`fuentes.toml`, separate from the config)

The sources do **not** live in `config.toml` but in `fuentes.toml` (the CLI allows pointing to another one with `ingesta --fuentes PATH`). There are **3 enabled by default**, English-speaking: Reddit r/worldnews, Lobsters and Mastodon (#ai). The 4chan connector exists and is tested, but its configuration (`/pol/`) is **not enabled by default** since D-075 (noisy signal, reputational risk, value never validated); the source remains registered in the database seed and can be enabled by editing `fuentes.toml`. Each source can be marked enabled/disabled; `ingesta` only iterates the enabled ones. The access policy (pacing with pauses and backoff on 429/5xx, own `User-Agent`) is in `sibila/conectores/base.py`. **There is no robots.txt policy in place** — recorded as a known limit.

---

## 3 · CLI Usage

**Document date:** 2026-10-12 · **Source:** direct inspection of `sibila/cli.py` and the modules it invokes. All syntax described here exists as-is in the code.

The CLI is invoked as `python -m sibila <command> [options]` (on Windows with the venv: `.venv\Scripts\python.exe -m sibila …`). The included `.bat` files already `cd` to the project root before invoking it.

**Exit codes (contract of `cli.py` itself):**

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Failure |
| 2 | Incorrect usage (argparse) |
| 3 | "Not implemented" (reserved; no commands return it anymore — minor issue BAJO-3) |

Dates are always `YYYY-MM-DD` in **UTC** (the whole program works in UTC; it is a golden rule with no exceptions since D-077: the default CLI ranges also use the UTC date). "Yesterday" means yesterday UTC, and days not yet sealable (today) are excluded from detection and sealing.

---

### Lifecycle commands

### `sibila init`
Creates the database and the folder structure. **Idempotent by construction** (all DDL is `IF NOT EXISTS`) and never deletes or recreates an existing database. No options. It is the first thing after installing.

#### `sibila check`
Green/red gate: "can I work?". Checks interpreter, complete schema (the 12 tables), SQLite pragmas, integrity, git/ots, file log, etc. **Repairs nothing** (that is `init`). Exit 0 = GREEN, 1 = RED. Detail in §1.5 of this manual.

#### `sibila doctor`
Post-installation health report (deps, resources with SHA-256, writable `data_dir`, git/ots, `config.local.toml`). Read-only. Detail in §1.5 of this manual.

---

### `sibila ingesta` — one pass over the sources

```
sibila ingesta [--fuente NOMBRE]... [--fuentes RUTA] [--fixture RUTA]
               [--en-vivo] [--sin-db] [--limite N]
```

| Option | Effect |
|---|---|
| `--fuente NOMBRE` | Only that source (repeatable). By default, all **enabled** ones in `fuentes.toml` |
| `--fuentes RUTA` | Alternative `fuentes.toml` file (default: the package's) |
| `--fixture RUTA` | Parses a local file (RSS/JSONL) as a single source; **requires `--fuente`** |
| `--en-vivo` | Forces network download even with a fixture (real ingest is live) |
| `--sin-db` | Only parses and shows: persists nothing and does not move cursors (probe mode) |
| `--limite N` | Maximum documents per source |

**What it produces:** documents in the `documents` table (with `author_hash` HMAC — never the author in the clear), per-source cursor updates, dedup at the point of ingest (the same URL —`url_hash`— or the same content —`content_hash`— does not enter twice; the second pass counts "repetidos" *(repeats)*, it does not duplicate rows). **The network is only touched here (and in alerts/GDELT):** without `--en-vivo`/fixture there is no traffic. **If a source fails** (connector exception, e.g. network down), `[FALLO]` is logged for that source, the rest continues and the command **exits with exit 1** (`pipeline_diario.bat` treats it as a chain failure); individual document errors are skipped with an AVISO without altering the exit.

### `sibila procesa` — linguistic pipeline

```
sibila procesa [--lote N] [--limite N] [--dia YYYY-MM-DD] [--todo]
```

| Option | Effect |
|---|---|
| `--lote N` | Documents per batch/**transaction** (default 200). Golden rule: network outside transactions and atomic batches |
| `--limite N` | Maximum documents (debugging; the rest stays pending) |
| `--dia` | Restricts the selection to one day |
| `--todo` | **Re-processes the whole range**, not only the pending ones |

**What it does per document** (in order): cleanup → language detection → dedup → quality → bot heuristic → emotion → n-grams. Only **ES/EN** documents reach the full analysis (stopwords and NRC lexicons exist only in ES/EN; see the section "What it truly analyzes", below). At the end, it recalculates the daily aggregates (`term_stats`, `emo_stats`, `ops_metrics`). If resources are missing (language model, NRC, VADER) it works in **degraded mode**, records it in `procesa.modo_degradado` and warns (it does not fail silently; the consequent `corre` behavior is described below).

### `sibila detecta` — temporal detection

```
sibila detecta [--dia D] [--desde D] [--hasta D] [--todo]
```

- `--hasta` defaults to **yesterday UTC** (requires `--desde`); `--todo` = from the first day with stats until yesterday.
- It computes over the daily series: **z_r** (robust z-score with median/MAD), **CUSUM** and **Mann-Kendall**; writes `term_stats.z_r` and the `signals` table. A day without enough history stays "inmaduro" *(immature)* (maturity days: 28) and generates no signals.
- Signals are the raw material that is later **sealed** as predictions.

### `sibila registro` — the sealed prediction registry

Subcommands:

| Subcommand | What it does |
|---|---|
| `sellar [--dia D | --desde D [--hasta D]]` | Turns the period's signals into **immutable** predictions: hash-chained JSONL lines (local chain of custody) + rows in the `predictions` table |
| `verificar` | Verifies the JSONL chain **and** its cross-check against the `predictions` table. Exit 0/1. In the daily pipeline it runs daily |
| `anclar` | Anchors the registry state in **git** (manifest commit) and, if `ots` (OpenTimestamps) exists, requests an external timestamp. Without git/ots: stays "pendiente" *(pending)* with an AVISO, **never a failure**. With no sealed signals yet (empty registry): AVISO "sin señales selladas que anclar" *(no sealed signals to anchor)*, exit 0 (D-078) |
| `listar [--pendientes]` | Lists the `predictions` table (no writes); `--pendientes` = only the pending ones |

### `sibila informe` — period report

```
sibila informe [--semana AAAA-Www | --dia D | --desde D --hasta D]
               [--salida RUTA] [--formato md|json|csv] [--actualizar-gdelt]
```

- Default: the **ISO week** ending yesterday. `--formato` accepts `md` (default), `json` and `csv` (frozen vectors). `--salida` writes to a file (default: stdout). Reading always in **read-only mode**.
- `--actualizar-gdelt` is a **separate writing sub-action**: it downloads the GDELT reference (network) and then the report can contrast against it. Without a downloaded reference, the contrast comes out as `n/d` (empty = not available, never an invented value).

### `sibila alerta` — network sending

Subcommands:

| Subcommand | What it does |
|---|---|
| `enviar [--dia D | --desde D [--hasta D]]` | Sends the period's alerts (default: **yesterday**) through the configured channels (Telegram/SMTP). Without configured channels it sends nothing (and `digest` reports it as an AVISO, exit 0) |
| `probar` | Sends a test message (TP-N7) to validate credentials |
| `digest [--semana AAAA-Www]` | Weekly alert digest (channel `digest`; default week: yesterday's) |

The keys/channels live **only** in `config.local.toml` or in `SIBILA_*` variables (see §2 of this manual). These are the only commands, together with `ingesta --en-vivo` and `informe --actualizar-gdelt`, that generate network traffic.

### `sibila corre` — full daily pipeline

```
sibila corre [--dia D | --desde D [--hasta D]] [--fuente NOMBRE]
             [--fixture FEED | --fixture-dir DIR] [--digest] [--con-informe]
```

Chains, per day: **ingesta → procesa → detecta → sellar → alerta** (and optionally weekly digest and report). The `--fixture*` allow E2E rehearsals without network: `--fixture` requires `--dia` and `--fuente`; `--fixture-dir` (one `{dia}.xml` per day) requires `--desde` and `--fuente`.

#### Anti-false-success behavior (ALTO-1 repair, 2026-10-12)

Rule: **`corre` only gives GREEN if the day produced processable evidence.**

- A day with documents whose language came out **all `NULL`** (e.g. the fastText model is missing or the detector does not load): `corre` ends in **RED (exit 1)** with an explicit error — before the repair this gave a false GREEN.
- **Day without documents**: remains legitimate success (nothing to process is not a failure).
- **Documented remediation:** place/repair the resources (`tools/descargar_recursos.py`), run **`sibila procesa --todo`** to reprocess the range, and repeat `corre` for that day.

### `sibila paquete` — integrity of the package itself

| Subcommand | What it does |
|---|---|
| `generar` | Regenerates `MANIFIESTO.sha256.json` (SHA-256 of the package's 133 files, with exclusions: data, logs, DB, `__pycache__`, `.pytest_cache`, `config.local.toml`…). **Only when building the package** |
| `verificar` | Verifies the tree's integrity against the manifest (exit 0/1). `instalar.bat` runs it at destination |

Preservation and restoration details in Annex E.

---

### What it truly analyzes (honest limits)

- **Language detection:** 176 languages via fastText `lid.176`; `lingua` fallback (8 languages: ES, EN, PT, FR, DE, IT, CA, EU — GL **does not exist** in lingua 2.2.0, a recent finding).
- **Full linguistic analysis: ES and EN only** (stopwords and NRC lexicons ES/EN only; VADER EN only). The rest of the languages are detected and classified, but out of the emotion/n-gram analysis.
- **The 3 sources enabled by default are English-speaking** (Reddit r/worldnews, Lobsters, Mastodon tag #ai; the 4chan /pol/ source is not enabled by default, D-075), so in practice the useful volume is EN.
- **Predictive capability is not validated**: ~12 months of accumulated real data are missing. The system records sealed predictions so they can be evaluated later, not to claim today that it is right.

---

## Annex A · Architecture

**Document date:** 2026-10-12 · **Source:** direct inspection of the `sibila/` tree, `sibila/schema.sql`, `sibila/db.py` and the docstrings of each module.

### A.1 What SIBILA is

**Research linguistics CLI** program. The idea: the emotional language of public forums "tenses" before certain events. The system ingests public sources, processes the language, detects temporal changes in the series, **seals predictions** in an auditable registry and issues alerts and reports. **SQLite** base. No network in tests (fixtures); the network is only touched in real ingest, alerts and the GDELT reference.

> Central warning: **predictive capability is not validated**. The system is built to *record sealed predictions and evaluate them later honestly* (blind resolution), not to claim today that it is right. See Annex C.

### A.2 Data flow

```
public sources (RSS/HTML)
   │  sibila/conectores/{reddit,lobsters,mastodon,cuatrochan}.py   (NETWORK, ingest only)
   ▼
documents (raw)  ── opaque cursor per source in conector_cursor (same TX as the data)
   │  sibila/procesa.py → sibila/procesado/*
   │    limpieza → idioma → dedup → calidad → bots → emoción → n-gramas
   ▼
daily aggregates: terms / term_stats / emo_stats   (+ ops_metrics)
   │  sibila/detecta.py → sibila/deteccion/{series,cusum,pendiente,motor}.py
   ▼
signals  (z_r, CUSUM, Mann-Kendall)
   │  sibila/sella.py → sibila/registro/{canonico,derivar,sellar,verificar}.py
   ▼
predictions + sealed JSONL chain ── git/ots anchoring (sibila/anclaje.py)
   │
   ├─→ sibila/alerta.py → alertas/{reglas,cooldown}.py   (NETWORK: Telegram/SMTP)
   └─→ sibila/informe_datos.py → informe/render.py  (+ gdelt.py, NETWORK on demand)
```

### A.3 Directory structure and modules

| Module | Responsibility |
|---|---|
| `cli.py` | Entry point and parsers of all commands (see §3 of this manual) |
| `config.py` | Loads/validates configuration (precedence, whitelist, secrets) |
| `db.py` | Connection, `init_db`, `verify_schema`, `tx`, `now_iso`, `integrity_ok` |
| `doctor.py` | Installation audit D1–D6 (read-only) |
| `corre.py` | Daily pipeline orchestrator + anti-false-success (ALTO-1) |
| `ingesta.py` + `conectores/` | Per-source ingest; `conectores/base.py` defines the `RawDoc` contract and the common policy; one module per source (`reddit`, `lobsters`, `mastodon`, `cuatrochan`) |
| `procesa.py` + `procesado/` | Linguistic pipeline: `limpieza`, `idioma` (fastText+lingua), `dedup` (simhash/MinHash), `calidad`, `bot_heur`, `emocion` (NRC/VADER), `ngramas`, `stopwords` |
| `detecta.py` + `deteccion/` | Daily series and detectors: `series`, `cusum`, `pendiente` (Mann-Kendall), `motor` |
| `sella.py` + `registro/` | Sealed registry: `canonico` (`canonical_json` FROZEN), `derivar`, `sellar`, `verificar` |
| `anclaje.py` | Git anchoring (+ OpenTimestamps if present) |
| `alerta.py` + `alertas/` | `reglas` (vigilance/alert/alarm) and per-topic `cooldown` |
| `informe_datos.py` + `informe/render.py` | Period report; `INFORME_VERSION` in render |
| `gdelt.py` | GDELT reference (empty = n/d, never a persisted 0) |
| `paquete.py` | Package SHA-256 manifest (generate/verify) |

### A.4 SQLite schema — the 12 tables

Schema v1 (`sibila/schema.sql`), created **entirely with `IF NOT EXISTS`** (idempotent init) and versioned with `PRAGMA user_version`. The DDL enforces in the database the rules the spec only states in prose (reinforcements R1–R5).

| # | Table | Purpose / contract notes |
|---|---|---|
| 1 | `sources` | Sources. `stratum` ∈ {normal, vidente, control} ("vidente" is for anti-echo, Phase 2) |
| 2 | `documents` | Documents. `author_hash` (HMAC, never the author in the clear); `simhash` lowercase hex(16) with `CHECK` (closes in the database the int64 bug, trap T1); `dia` shaped `YYYY-MM-DD`; invariant "if the date is real, it exists" in DDL |
| 3 | `terms` | Terms and clusters. `type` ∈ {term, bigram, trigram, cluster, emocion}; `cluster_key` gives the cluster persistent identity |
| 4 | `term_stats` | Daily series per term (baseline and `z_r`); `UNIQUE(day, term_id)` |
| 5 | `emo_stats` | Daily emotion series per language (NRC-VAD rescaled `v' = 2v − 1`) |
| 6 | `signals` | Tension signals. `metric` ∈ {z_r, cusum, mk}; `status` ∈ {nuevo, confirmado, descartado, reactivo, inmaduro}; `UNIQUE(day, target_type, target_id, metric)` allows **idempotent UPSERT** |
| 7 | `predictions` | Sealed **append-only** registry with hash chain (`hash`, `prev_hash`); `umbral` as decimal string; `ventana` ISO-8601; `estado` ∈ {pendiente, parcial, cumplida, fallada, expirada}; `resolucion_ciega` |
| 8 | `echo_flags` | Anti-echo (Phase 2): **exists EMPTY in Phase 1**, frozen contract. `tipo` ∈ {sincronia, meme, cita_profecia, bot_ia}; `score` ∈ [0,1] |
| 9 | `alert_log` | Alerts sent (per-topic cooldown). `nivel` ∈ {vigilancia, alerta, alarma} |
| 10 | `gdelt_ref` | GDELT reference per topic/day. **Empty = n/d; never a persisted 0** (enforced in the module, not only in prose) |
| 11 | `ops_metrics` | Operational metrics (append log, no PK) |
| 12 | `conector_cursor` | Opaque per-source ingest cursors, **in the DB, never in files**; they are saved in the same transaction as the documents so cursor and data never diverge |

Explicit indexes for the frozen read patterns (day, source, term, signal status, etc.).

### A.5 Golden rules of the code

**Persistence and transactions (`db.py`):**
- `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=30000` ms, `synchronous=NORMAL`.
- `tx()` = short transaction with **`BEGIN IMMEDIATE`** (takes the write lock on entry).
- **Network outside transactions** and atomic batches (procesa in batches of 200).
- `PRAGMA user_version` does not accept bind params: it is written as an integer literal from the constant (trap T12).
- `init` never deletes or recreates the database: sealed evidence is untouchable.

**Time and serialization:**
- `now_iso()` is the **only point** where the time is obtained (all UTC; since D-077 the default CLI ranges also derive from it — MED-1 resolved).
- `canonical_json` (`registro/canonico.py`) is **FROZEN**: it defines the canonical serialization on which all hashes depend; it is not negotiable. The registry is written in binary `ab` with `canonical_json(linea)+b"\n"` (never CRLF, trap 3).

**Algorithm versions (changing the algorithm = bumping the version = re-processing):**

| Constant | Value | Governs |
|---|---|---|
| `SCHEMA_VERSION` | `1` (`PRAGMA user_version`) | DB structure |
| `BOT_VERSION` | `"bot-1"` | Bot heuristic markers/thresholds |
| `STOPWORDS_VERSION` | `"sw-1"` | Stopword lists (bigrams/trigrams and `cluster_key` depend on them) |
| `INFORME_VERSION` | `"informe-1"` | Report render algorithm |

(Decision D-019: **there is no program version in the code**; what is versioned are the algorithms that affect reproducibility.)

**Layer separation:** pure logic (detection, emotion, render) does not touch the DB; the data layer persists results. This allows tests without a DB and controlled degraded mode.

### A.6 Known limits documented in the code itself

- **`echo_flags` empty in Phase 1** by contract: anti-echo is Phase 2.
- **`gdelt_ref` empty = n/d**: without a downloaded reference the report shows "n/d", never an invented value.
- **Detection 176 languages, analysis ES/EN only** (stopwords and NRC lexicons ES/EN only; VADER EN only). Lingua fallback limited to 8 languages (GL does not exist in lingua 2.2.0).
- **Explicit degraded mode**: without the fastText/NRC/VADER model the system does not fail silently: it records `procesa.modo_degradado` and `corre` penalizes the false success (ALTO-1).
- **"Immature" days**: a series needs history (`DIAS_MADUREZ = 28` days) before confirming signals; a freshly installed system cannot "predict" anything yet.
- **Simhash/MinHash implemented by hand** with the stdlib (no numpy/scipy/datasketch) to keep the package light and portable.

---

## Annex B · Security and privacy

**Document date:** 2026-10-12 · **Sources:** `sibila/config.py`, `sibila/procesa.py`/`db.py`, `.gitignore`, `sibila/paquete.py`, `tools/descargar_recursos.py`, and the cross-audits of `auditoria/` (2026-10-12).

### B.1 Secrets: never versioned, never in logs

Concrete measures (all verifiable in code):

| Measure | Where |
|---|---|
| `config.toml` (versionable) has the `[secretos]` section **banned**: if it appears, `ConfigError` at startup | `config.py` (`load_config`) |
| Secrets only fit in `config.local.toml` (gitignored) or in `SIBILA_*` variables | `config.py`, `.gitignore` |
| Secrets are stored with `repr=False` in a `MappingProxyType`: **they do not appear in the repr or in logs** (trap T4) | `config.py` |
| The package manifest **excludes** `config.local.toml*` (except the `.example`), in addition to DB, logs and `__pycache__` | `paquete.py` |
| `.gitignore` blocks `config.local.toml`, `datos/`, `logs/`, `*.db*`, `__pycache__/`, `registro/`, `.venv/` | `.gitignore` |
| The installer hardens `config.local.toml` permissions (`icacls`) | `instalar.bat` |

### B.2 Author privacy: `author_hash` (HMAC)

Document authors are **never stored in the clear**. At the point of ingest the author identifier is replaced by `author_hash`, an **HMAC** with the local `hmac_key`:

- It allows deduplicating/grouping by author without knowing the author (pseudonymized anonymization).
- **Without `hmac_key`, `author_hash` stays `NULL`** (it never falls back to storing the author in the clear). `doctor` warns about it (D6).
- The key lives only in `config.local.toml`/`SIBILA_HMAC_KEY`; if lost, old hashes stop being comparable with new ones (accepted and documented consequence).

### B.3 Dependencies: OSV sweep of 2026-10-12

- The 10 dependencies are **pinned** (see §1.2 of this manual). The **OSV sweep of 2026-10-12 (re-executed by an independent verifier) gives 0 advisories** in all except the urllib3 case, already resolved.
- **urllib3 was raised from 2.7.0 to 2.8.0** due to 3 CVEs fixed in 2.8.0:

| CVE | What it is | SIBILA exposure (audit classification) |
|---|---|---|
| CVE-2026-97688 (GHSA-gh4c-6fx4-qh6g) | Infinite loop in chunked+deflate streaming | **Unlikely**: SIBILA does not call `stream()` directly, but `requests.get(...).content` does internally reach `urllib3.stream()` on **every download**; it would require a hostile server among fixed TLS hosts |
| CVE-2026-97689 (GHSA-vxq7-64xx-v4gw) | Unlimited chunk-size line buffer (memory) | **Unlikely**; impact: memory exhaustion |
| CVE-2026-97687 (GHSA-8988-9cw3-xx77) | Ignored HTTPS proxy TLS | **Unlikely**: SIBILA does not configure proxies; `requests` honors the environment's `HTTPS_PROXY`, the only theoretical path |

The audit **corrected downward** the first assessment ("not exploitable" → "unlikely") after checking the internal requests→urllib3 path, and that is why the bump was done **before any real collection**. urllib3 2.8.0 requires Python ≥3.10 and is compatible with `requests 2.34.2` (which asks for `urllib3<3,>=1.26`).

### B.4 Provenance and integrity of data resources

| Resource | Origin | Integrity |
|---|---|---|
| `lid.176.ftz` (fastText model) | Official Facebook AI Research URL (`dl.fbaipublicfiles.com`), MIT license | SHA-256 **pinned in the code** and **verified by double download from the official URL** (D-030); `doctor` re-verifies it |
| 4 NRC lexicons (VAD EN/ES, Emotion EN/ES) | `saifmohammad.com` (National Research Council Canada), **non-commercial license** — not redistributed, downloaded during installation | SHA-256 pinned in `emocion.py`; **verified against a real download on 2026-10-15** (D-077) |

The downloader **never silently overwrites** a file whose hash does not match: a corrupt or tampered resource is an explicit failure, not silent bad data.

### B.5 What goes out over the network and what does not

**Goes out over the network (and only in these cases):**
- **Real ingest** (`ingesta --en-vivo` / scheduled tasks): RSS/HTML from the 4 public sources.
- **Alerts** (`alerta enviar/probar/digest`): Telegram API and/or SMTP, only if channels are configured.
- **GDELT reference** (`informe --actualizar-gdelt`).
- **Resource download** (`tools/descargar_recursos.py`) and dependency installation.

**Does not go out over the network:**
- The complete **test battery** (works with fixtures; it is a project rule).
- All **local processing** (`procesa`, `detecta`, `registro`, `informe` without `--actualizar-gdelt`).
- **No telemetry**: the program does not "phone home"; there are no own endpoints or analytics.

**Declared residual risk:** on a network with an environment proxy (hotel wifi), `requests` could honor `HTTPS_PROXY`; the program does not configure proxies by itself.

### B.6 Integrity of the package itself and of the registry

- **SHA-256 manifest** of the 133 files (`sibila paquete generar`/`verificar`), serialized with the frozen `canonical_json`; verified at destination after installing (see Annex E).
- **Sealed registry**: JSONL chain with chained hash (`hash`/`prev_hash`) cross-checked with the `predictions` table, verifiable with `registro verificar`, and optional anchoring in git + OpenTimestamps to fix the "when" before third parties.

---

## Annex C · Tests and real status

**Document date:** 2026-10-12 · **Sources:** `equipo/EVIDENCIA_CIERRE_DIA1_v1.md` (Day 1 closure evidence) and the audits of `auditoria/`. Rule of this document: **nothing is claimed without backing**; what is untested is said expressly.

### C.1 What IS tested (with evidence)

#### Automated suite
- **737 passed / 3 skipped / 50 subtests** (2026-10-15, D-078), environment: Python 3.12.12 · pytest 9.1.1 · urllib3 2.8.0 · requests 2.34.2 · lingua 2.2.0 · fasttext-predict 0.9.2.4. (735/3 at the 2026-10-12 closure; +1 MED-1 boundary test in D-077, +1 no-signals anchoring test in D-078.)
- The 3 skips are the **expected** ones: 2 × real NRC lexicons absent (MED-5) + 1 × degradation-without-lingua.
- Evolution of the day: 726 (base intact) → 728 (after CRIT-1/CRIT-2/ALTO-1) → **735** (after CRIT-3 and the rest).

#### Acceptance gates (all green)
| Gate | Result | Detail |
|---|---|---|
| **CRIT-1** (language model loading) | **4/4** | ES@0.9838 · EN@0.9847 · FR@0.9973 · PT@0.9990 with the real model `lid.176.ftz` through the production path. Negatives: file absent → degraded; corrupt → controlled error |
| **CRIT-2** (alert keys) | **OK** | Fictitious config with the 5 keys loads; channels enabled; unknown key rejected; non-integer `smtp_puerto` rejected; secrets in `config.toml` still banned. **Without any real sending or connection** |
| **ALTO-1** (anti-false-success) | **OK** | `corre` with fixture: exit 0 with lang populated; without model and with work → **exit 1**; empty day without resources → legitimate exit 0 |
| **CRIT-3** (lingua set) | **OK** | Frozen set of 8 {ES,EN,PT,FR,DE,IT,CA,EU}; the `test_dudoso_cae_en_lingua` gate passes **for the first time in the project's history** with real lingua |

#### Scenarios and mutation tripwires (mordidas)
- **C1–C8 + extra negatives (BOM, `telegram_chat` as integer): 10/10.**
- **Mutation tripwires (mordidas, manual mutation testing):** reverting the language line → the CRIT-1 gate dies; reverting the signature to `None` → the green gate of `corre` dies; removing `telegram_chat` from the whitelist → CRIT-2 dies. After each tripwire, restoration verified **byte-exact by hash**. (They prove the tests truly bite.)

#### Synthetic E2E and its honest reading
- **32 days / 576 documents with injected duplicates → green** (within the suite). It tests the **plumbing** (ingesta→procesa→detecta→sealing).
- **With the real language detector: 576/576 come out `lang NULL` and the anti-false-success triggers RED on all 32 days.** Documented diagnosis: the synthetic bodies are artificial tokens with fastText confidence ~0.12 < 0.80 threshold, so detection rejects them honestly. **Conclusion: the synthetic corpus does not test the linguistics; the observed RED is exactly the behavior ALTO-1 was meant to produce.**

#### Cross-audits of 2026-10-12
- **Reproduction by independent verifier: PASS** — 728/3 suite reproduced in their own environment; language gates with their own sentences; diff against the reference with exactly the expected files, not one more.
- **Security audit: PASS** (OSV sweep re-executed; see Annex B).
- **Cross-review:** found 3 criticals (later fixed); a **second pass** confirmed the fixes.

#### English end to end (Day 2 verification, independent verifying agent)
- **Verdict: OPERATIONAL.** Detection with the real model (5/5 varied English sentences above the 0.80 threshold, confidences 0.81–0.99); EN stopwords (`sw-1`, 161 words); n-grams free of stopword contamination; EN emotion with NRC fixtures + **real VADER** (mathematically confirmed that VADER enters the valence; VADER absent → `None` vector, never a halfway average — anti-bias); full pipeline via `corre` with exit 0 and `emo_stats`/`term_stats` populated in `lang='en'`.
- **Adversarial test:** lexicons with incorrect SHA-256 in `recursos/` → exit 1 with explicit `[FALLO]` (visible failure, never silent).
- **Exact limits of the verdict:** the emotion used 8-word fixtures (the real NRC are still absent — the 0.30 coverage threshold leaves neutral texts without a vector with the fixture); texts with fastText confidence < 0.80 fall to `lang NULL` if lingua is not installed; the Day 2 E2E was done with the verifier's own corpus, not with live sources.

### C.2 What is NOT tested / verified (honest)

| Not tested | Why it matters | Status |
|---|---|---|
| **Real Windows** | The entire planned deployment (`.bat`, tasks, `icacls`) is Windows-only | **Verified (2026-10-15):** two real Windows 11 tests run by an independent verifier; the second passed W1–W14 with the first test's six defects fixed (D-077/D-078). A natural 24 h cycle with the scheduled tasks remains pending |
| **Real NRC lexicons** | Without them **there is no emotion in production** (the E2E used test fixtures) | MED-5 resolved (D-077): automated download works and hashes are verified; what remains is enabling them on the production machine |
| **12 months of real data** | Detection needs history (28 days minimum maturity) and validation needs a year of real series | Pending |
| **Predictive capability** | There is no evidence that the signals anticipate anything; the system exists to *record and evaluate*, not to claim hits | **Not validated** |
| **CLI by subprocess** | The CLI has been exercised *in-process* in the suite, not as an independent end-to-end process | Minor pending |

### C.3 Overall reading (no marketing)

SIBILA is **solid in its plumbing** (persistence, dedup, sealing, verification, configuration, anti-false-success) and **honest in its degradations** (when a resource is missing, it says so and does not give a false success). But **it is not yet a validated predictor**: it lacks the real emotion resources, verification on Windows and, above all, months of real data that would allow evaluating whether the sealed predictions come true. Any claim stronger than this **is not backed** by the evidence available as of 2026-10-12.

---

## Annex D · Pending tasks

**Document date:** 2026-10-12 · **Sources:** `auditoria/FASE_PLANIFICACION_v1.md`, `auditoria/AUDITORIA_CIERRE_PREPARACION_v1.md`, `equipo/DECISIONES_PENDIENTES_v1.md`, `equipo/DECISIONES.md`, `equipo/EVIDENCIA_CIERRE_DIA1_v1.md`.

Format per task: **status · reason · practical consequence · requirements to complete it · missing test · risk of using the system without resolving it.**

---

### A. Blockers for serious real use

#### A1 · Verification on real Windows (W1–W14 plan)
- **Status:** **verified in two real tests (2026-10-15, D-076/D-077/D-078).** First test: 6 defects found (2 blocking) and fixed. Second test: **W1–W14 satisfactory** with all six defects verified as fixed. Only a **natural 24-hour cycle** with the scheduled tasks running on their own remains pending.
- **Reason:** the planned deployment is Windows (`.bat`, task XMLs, `icacls`, cp1252, Defender) and the sandbox cannot simulate it.
- **Practical consequence:** it cannot be assured that the installation, the scheduled tasks or the console work in the target environment.
- **Requirements:** a session on the real Windows (with Hermes) executing the 14 W1–W14 steps with per-step evidence (Python version, installer, `check`/`doctor`, 1-day real ingest —W9—, `procesa`+`detecta`+`sellar`, imported and executed task, full pipeline with degraded alert, cp1252/Defender, task+`resumen.py` concurrency). W10/W12 require the already-repaired code (done on 2026-10-12); W6 requires the decision on the NRC; W11/W13/W14 are the only fully unsimulable ones.
- **Missing test:** 14/14 steps with evidence, or the expressly accepted limitations. It is **forbidden** to declare "Windows validated" by inspection of the `.bat` files.
- **Risk of using without resolving it:** that the first failure is discovered in production (task that does not run, DB blocked by Defender, illegible console), with loss of unrecoverable ingest days.

#### A2 · The 4 real NRC lexicons (MED-5) — RESOLVED in D-077 (2026-10-15)
- **Status:** **resolved.** The HTTP 406 was caused by python-requests' default `User-Agent`, rejected by the official server; with browser headers the automated download works (verified on 2026-10-15: the 3 zips downloaded, normalized, and **all 4 SHA-256 match the ones pinned in `emocion.py`** — the hashes are now verified against a real download). `tools/descargar_recursos.py` now sends those headers; the manual browser download remains as a documented alternate route.
- **Reason:** without the NRC there is no real emotion scoring (fixtures were used in the E2E).
- **Practical consequence if missing:** the emotional series — central piece of the paradigm — does not exist in production; the system runs in emotion-degraded mode with clear warnings.
- **Requirements to enable it:** run `tools/descargar_recursos.py` with network access (the installer already does); if a hash does not match, it is never forced: it is documented and decided.
- **Missing test:** `doctor` D3 green for the 4 NRC + `procesa --todo` recalculating real `emo_stats` on the production machine.
- **Risk of using without resolving it:** believing there is emotional analytics when there is only degraded mode; the anti-false-success mitigates self-deception, but the functionality remains absent.

#### A3 · Human/independent audit and acceptance verdict
- **Status:** there are **cross-audits between agents** (reproduction PASS, security PASS, review with 3 criticals fixed and second pass). **Decision 6** proposes that each review be audited by an independent auditor (Sol or Hermes) with their own recomputation and an approved/rejected/inconclusive verdict (**inconclusive never counts as approved**). **Sol's verdict is pending**: when it arrives, it is incorporated or rebutted with evidence.
- **Reason:** the team's self-verification does not replace an external look; it is the double gate prior to declaring any version VALID.
- **Practical consequence:** no version can be declared VALID while this gate does not operate.
- **Requirements:** approve decision 6 and send the per-review audit packages to the available auditor.
- **Missing test:** documented verdict (approved/rejected/inconclusive) with their own hash recomputation and reproduction of the critical tests.
- **Risk of using without resolving it:** unaudited confidence; the failures the team does not inflict on itself remain undiscovered.

#### A4 · 12 months of real data
- **Status:** there is no real history; detection additionally requires series maturity (`DIAS_MADUREZ = 28` days) before confirming signals.
- **Reason:** validation of the paradigm (do the signals anticipate anything?) can only be evaluated against a year of real series and blind resolution of the sealed predictions.
- **Practical consequence:** today the system **records** predictions so they can be evaluated tomorrow; it cannot be claimed to be right.
- **Requirements:** sustained daily real ingest (~12 months), with the scheduled tasks verified (A1) and emotion active (A2).
- **Missing test:** hit/miss evaluation over the resolved `predictions` (cumplida/fallada/expirada) after the period, with blind resolution.
- **Risk of using without resolving it:** making decisions based on signals from an **unvalidated** system; the design (sealed registry + blind resolution) exists precisely to avoid doing so.

---

### B. Open project decisions (non-technical)

| Decision | Status | What is missing |
|---|---|---|
| **Second backup** | Dedicated USB recommended (offline, ~10 €) + GitHub as external anchor after publishing. Today the reference lives on **a single disk** | Approval and execution; rule: the copy only counts if `paquete verificar` passes at destination. **Risk of not doing it:** losing the laptop = losing the entire history |
| **Public pseudonym** | **Decided (D-072, 2026-10-13): "Yosu Gem"**. The package `NOTICE` already carries that name; the GitHub account remains to be created (the owner creates it; no agent receives credentials) | — (decision made) |
| **Publication** | Destination decided: **GitHub, free software, Apache 2.0 license** (SIBILA name and license firm). The publication package is prepared but **nothing is published without an explicit order** (publishing = handing over to the world). Recorded notice: GitHub allows one free account per person; the owner creates the account and no agent receives credentials | Explicit publication order (the 4chan /pol/ source is no longer enabled by default, D-075) |
| **Generational slang lexicon (age sociolects)** | **Planned step, not done** (raised by the creator on 2026-10-12, D-069). Each generation uses its own words and multi-word expressions as identity markers (*guay*, *mola mazo*, *tope*, *de puta madre*, *te cagas*…), often with a meaning different from the dictionary one: semantic shift, intensifiers (*mazo*, *tope*), multi-word expressions, polarity inversion (*jodido*). Today: the emotion layer (formal NRC) does not know them or would label them with their standard sense; the n-gram layer **does capture them without a dictionary** — appearance, frequency and series in `term_stats`, and *emerging*-term detection could register the birth of a new word —. What is missing: a slang lexicon with emotional valence per cohort and continuous maintenance (slang is born and dies with its generation); SIBILA does not model authors or ages either (only sources and dates), so generational attribution would be inferred by temporal co-occurrence, not observed | Creator's decision (future version, D-019): lexicon resource design, hash registry, tests and per-language coverage |

Other minor decisions already catalogued in the consolidated document (reference numbering, `sw-2`, dual version identifier, closure rule in Z) follow the principle: **silence authorizes nothing**.

---

### C. Open technical issues (catalogue)

Repaired on 2026-10-12: **CRIT-1, CRIT-2, CRIT-3, ALTO-1** and the urllib3 pin (INFO-1). Repaired on 2026-10-15 after the first real test on Windows 11 (D-077): **MED-1** (single UTC clock in default CLI ranges), **MED-3** (`sibila` importable from any folder via a `.pth` written by the installer), **MED-5** (NRC download with browser headers: the 406 was the rejection of python-requests' User-Agent), **BAJO-1** (`.pytest_cache` excluded from the manifest) and **BAJO-5** (`plantillas\` exists again with the canonical `config.toml` and `fuentes.toml`). Still open, planned for upcoming versions:

| Issue | Severity | Summary | Planned version |
|---|---|---|---|
| **ALTO-2** | High | Spanish stopwords without accents: they do not filter the real accented forms → `sw-2` list with per-row version mark (today there is no real data: the decision is cheap now, expensive later) | 0.9.2 |
| **MED-2** | Medium | `--actualizar-gdelt` only downloads on Monday | 0.9.3 |
| **MED-4** | Medium | Quadratic costs / full in-memory loads on long ranges (requires before/after benchmark) | 0.9.3 |
| **BAJO-2..4** | Low | `.bat` logs without rotation; dead code / unreachable exit 3; incorrect exit code docstring | 0.9.4 |
| **INFO-2..5** | Info | Latent fragility in cluster propagation; redundant condition in `cli.py`; debatable exit 2 in `corre` without feedparser; `check` writes probe in the project's `logs/` | 0.9.4 |
| **INFO-6** | Info | 4chan /pol in the public distribution: **resolved in D-075 (2026-10-13)** — the source is not enabled by default in `fuentes.toml` (noisy signal, reputational risk, value never validated); the connector remains available and tested for anyone who enables it manually. No planned version — numbering is Yosu's prerogative (D-019) | — (resolved, D-075) |

---

### D. Logical unblocking order

```
A1 (Windows) ──┐
A2 (NRC)      ─┼─► A3 (independent audit) ─► VALID version ─► A4 (12 months) ─► predictive validation
B (backup)    ──┘   (publication only after VALID and explicit order)
```

None of the above is blocked by lack of design: everything has a plan, acceptance test and proposed owner. What is missing is **execution in the real environment and explicit decisions**.

---

## Annex E · Preservation

**Document date:** 2026-10-12 · **Sources:** `referencia/ACTA_CONGELACION_20260920.md`, `sibila/paquete.py`, `equipo/DECISIONES.md`, the current manifest in `nucleo/`.

### E.1 Pieces of preservation

| Piece | What it is | Where |
|---|---|---|
| **Frozen reference** | Byte-exact copy of the audited tree (131 files, CRLF preserved), **read-only** | `referencia/arbol_auditado_20260920/` |
| **Freezing certificate** | Document that fixes the tree's identity: manifest hash, content, exclusions and known defects at freezing | `referencia/ACTA_CONGELACION_20260920.md` |
| **Regenerable manifest** | `MANIFIESTO.sha256.json`: SHA-256 + size of each package file | Tree root (`nucleo/`) |
| **DECISIONES.md** | Chronological record of decisions: the memory of *why* each change | `equipo/DECISIONES.md` |

### E.2 The frozen reference (identity)

- **Manifest:** `generado: 2026-09-20T14:46:53Z` · `generador: sibila-paquete-1` · `version_programa: null` (there is no program version in the code, D-019).
- **Manifest SHA-256:** `02b0c92f92f7e95176c90e3acecf31769a7d890f6618efbd4af6fdf1dd840061`.
- **Content:** 131 manifest files + the manifest itself = 132 files, 894 641 bytes.
- **Copy verification [EJEC 2026-10-11]:** 131/131 matching SHA-256, 0 failures (verification recomputed file by file, not assumed).
- **What it includes:** `sibila/` code (46 `.py` + `schema.sql`), complete `tests/` with fixtures (69 files), `tools/`, the `.bat`/`.xml` and `resumen.py`, configuration templates **without secrets**, `requirements.txt`, `LEEME_T2.md`.
- **What it excludes and why:** `config.local.toml*` (secrets, they never travel), `datos/`·`logs/`·`registro/` (data from a lived tree), `__pycache__/`·`*.pyc` (regenerable artifacts, excluded by rule), `.gitignore` and the manifest itself (self-excluded). Honest nuance: `.pytest_cache/` is recorded as absent from the reference, but its exclusion is **not hardened** in `paquete.py` — if pytest is run in the tree and the manifest is regenerated, the count changes (open issue **BAJO-1**; see Annex D).
- **Honest warning from the certificate:** the frozen reference corresponds to the **2026-09-20 state, with the CRIT-1/CRIT-2/ALTO-1 defects still open and urllib3 2.7.0**. The certificate says it expressly: "729 verdes ≠ programa sano" *(729 greens ≠ healthy program)* and "esta referencia NO es VÁLIDA" *(this reference is NOT VALID)*. It is a **historical recovery point**, not a recommended version.

### E.3 The regenerable manifest

The manifest **is not a precious object: it is regenerable** with the program itself, **deterministically** (same tree → same manifest, because it is serialized with the frozen `canonical_json`):

```
# Regenerate (only when building/packaging; NEVER on the reference)
python -m sibila paquete generar

# Verify a tree against its manifest (exit 0 = intact)
python -m sibila paquete verificar
```

`instalar.bat` already runs `paquete verificar` **at destination** after copying, so a corrupt copy is detected on the spot. Project rule: **a backup only counts if `paquete verificar` passes at destination.**

> Temporal nuance (honest): the working tree `nucleo/` today has a manifest **regenerated on 2026-10-15** (`sibila-paquete-1`, **133 files** — the `plantillas/` folder re-entered in D-077) after the closure and Windows-test repairs. The **reference** is still that of 2026-09-20. Two manifests coexist: the historical one (frozen) and the current one (regenerated after the changes recorded in DECISIONES.md).

### E.4 DECISIONES.md as a record

`equipo/DECISIONES.md` is the project's memory: every relevant change is recorded with date, reason and evidence (D-nnn entries). Associated rules:

- **Every change** relative to a version must be recorded in that version's entry; comparing trees without that record is incomparable.
- **Silence authorizes nothing:** a decision not taken enables no change.
- **Frozen ≠ valid:** even a rejected version is frozen (preserved), but marked as such.
- Layered protection: read-only + manifest hash anchored in the registry + second physical copy (pending, see Annex D) + periodic re-verification + external anchor (GitHub/OTS) when published.

### E.5 How to restore a file (or everything) to its reference state

**The whole tree:**
1. Copy `referencia/arbol_auditado_20260920/` to a new destination (never work on the reference).
2. Inside: `python -m sibila paquete verificar` → it must say **ÍNTEGRO 131/131**.
3. Alternative without the program: recompute the SHA-256 of each file and compare it with `MANIFIESTO.sha256.json` (the copy is byte-exact, CRLF included).

**A single file:**
1. Locate its path in the reference manifest and its expected SHA-256.
2. Copy that file from `arbol_auditado_20260920/` to the working tree (byte-exact).
3. Verify: `sha256sum <file>` (or `Get-FileHash` on Windows) against the manifest value; then `python -m sibila paquete verificar` on the whole tree.
4. **Record the restoration in DECISIONES.md** (which file, from which reference, why).

**Comparing with a later version:** generate the new version's manifest and collate entries by path: different hash = changed; new path = added; absent path = removed. Every change must have its record.

### E.6 Preservation rules (operational summary)

1. The reference is **read-only**: nothing ever modifies it; a repair is made in a new version.
2. A copy **only counts if it verifies** (`paquete verificar` at destination).
3. **Secrets never** enter copies or packages (`config.local.toml` excluded).
4. **Second physical copy** (dedicated USB) recommended and pending: today everything lives on a single disk (see Annex D).
5. External anchor (GitHub/OpenTimestamps) when published; publishing requires an explicit order.
