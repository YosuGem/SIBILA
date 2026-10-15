-- SIBILA · schema v1 — el contrato del que pende todo (spec §5).
-- Fiel a spec §5 con los refuerzos R1-R5 (decisión D-B1-06 de Liskov: la spec enuncia
-- estas reglas en prosa; el DDL es donde se hacen cumplir).
-- Regla de oro: TODO con IF NOT EXISTS → init idempotente por construcción (D-B1-02).
-- JAMÁS borrar ni recrear la base: la evidencia sellada es intocable.
-- Orden de creación respeta las FK (sources → documents → terms → resto).

-- Fuentes de documentos (conectores; estrato 'vidente' separado para anti-eco, Fase 2)
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  nombre TEXT UNIQUE,
  tipo TEXT,
  idioma TEXT,
  stratum TEXT CHECK(stratum IN ('normal','vidente','control')) DEFAULT 'normal',
  sesgo TEXT,
  peso REAL DEFAULT 1.0
);

-- Documentos crudos procesados
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  source_id INTEGER REFERENCES sources(id),
  url_hash TEXT UNIQUE,
  author_hash TEXT,
  published_at TEXT,                       -- tz-aware UTC ISO o NULL (contrato RawDoc, spec §4.1)
  published_at_real INTEGER CHECK(published_at_real IN (0,1)),
  fetched_at TEXT,
  lang TEXT,
  body_text TEXT,
  content_hash TEXT UNIQUE,
  -- R1: hex(16) minúsculas; cierra el bug int64 EN LA BASE (trampa T1, Fase 0)
  simhash TEXT CHECK (simhash IS NULL OR (length(simhash) = 16 AND NOT simhash GLOB '*[^0-9a-f]*')),
  duplicate_of INTEGER REFERENCES documents(id),
  calidad_score REAL,
  bot_flags TEXT,                          -- JSON de sospechas auditable (spec §5)
  bot_detector_version TEXT,
  peso REAL DEFAULT 1.0,
  dia TEXT CHECK (dia IS NULL OR dia GLOB '????-??-??'),   -- R3: forma YYYY-MM-DD
  -- R2: invariante de spec §5 en DDL (si la fecha es real, existe; si no, NULL)
  CHECK (published_at_real = 1 OR published_at IS NULL)
);

-- Términos y clusters (cluster_key da identidad persistente al cluster, spec §5)
CREATE TABLE IF NOT EXISTS terms (
  id INTEGER PRIMARY KEY,
  text TEXT UNIQUE,
  type TEXT CHECK(type IN ('term','bigram','trigram','cluster','emocion')),
  cluster_key TEXT
);

-- Series diarias por término (baseline y z_r viven aquí)
CREATE TABLE IF NOT EXISTS term_stats (
  day TEXT CHECK (day GLOB '????-??-??'),
  term_id INTEGER REFERENCES terms(id),
  docs INTEGER,
  occ INTEGER,
  df INTEGER,
  z_r REAL,
  UNIQUE(day, term_id)
);

-- Series diarias de emoción por idioma (NRC-VAD reescalado v'=2v-1, spec §6)
CREATE TABLE IF NOT EXISTS emo_stats (
  day TEXT CHECK (day GLOB '????-??-??'),
  lang TEXT,
  valence_mean REAL,
  arousal_mean REAL,
  n INTEGER,
  n_efectivo REAL,
  UNIQUE(day, lang)
);

-- Señales de tensión (UNIQUE habilita UPSERT idempotente → TP-N8)
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY,
  day TEXT CHECK (day GLOB '????-??-??'),
  target_type TEXT CHECK(target_type IN ('term','bigram','trigram','cluster','emocion')),
  target_id INTEGER REFERENCES terms(id),
  metric TEXT CHECK(metric IN ('z_r','cusum','mk')),
  score REAL,
  status TEXT CHECK(status IN ('nuevo','confirmado','descartado','reactivo','inmaduro')),
  created_at TEXT,
  UNIQUE(day, target_type, target_id, metric)
);

-- Registro sellado de predicciones (append-only; hash chain, spec §8)
CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY,
  tema TEXT,
  metrica TEXT,
  umbral TEXT,                 -- números como strings decimales (spec §8)
  ventana TEXT,                -- ISO-8601 duration
  criterio_acierto TEXT,
  created_at TEXT,
  hash TEXT,
  prev_hash TEXT,
  estado TEXT CHECK(estado IN ('pendiente','parcial','cumplida','fallada','expirada')),
  madura INTEGER DEFAULT 0 CHECK(madura IN (0,1)),   -- R4
  resuelta_at TEXT,
  resolucion_ciega TEXT
);

-- Anti-eco (Fase 2): EXISTE VACÍA en Fase 1, contrato congelado (spec §4.6; plan §5)
CREATE TABLE IF NOT EXISTS echo_flags (
  doc_id INTEGER REFERENCES documents(id),
  tipo TEXT CHECK(tipo IN ('sincronia','meme','cita_profecia','bot_ia')),
  score REAL CHECK(score >= 0 AND score <= 1),
  detector_version TEXT,
  accion TEXT CHECK(accion IN ('peso_025','peso_050','excluir_estrato')),
  UNIQUE(doc_id, tipo)
);

-- Registro de alertas enviadas (cooldown por tema, spec §9)
CREATE TABLE IF NOT EXISTS alert_log (
  signal_id INTEGER REFERENCES signals(id),
  nivel TEXT CHECK(nivel IN ('vigilancia','alerta','alarma')),   -- R5 (dominio spec §9)
  canal TEXT,                        -- dominio congelado en el bloque de alertas (decisión abierta A3)
  sent_at TEXT
);

-- Referencia GDELT: vacío = n/d, JAMÁS 0 persistido (spec §5; se hace cumplir en el módulo)
CREATE TABLE IF NOT EXISTS gdelt_ref (
  tema TEXT,
  day TEXT CHECK (day GLOB '????-??-??'),
  n INTEGER,
  fetched_at TEXT,
  UNIQUE(tema, day)
);

-- Métricas operativas (log append, sin PK)
CREATE TABLE IF NOT EXISTS ops_metrics (
  ts TEXT,
  clave TEXT,
  valor REAL
);

-- Cursores opacos de ingesta por fuente (D-B2-03: EN LA BD, jamás en ficheros —
-- se guardan en la MISMA transacción que los documentos: cursor y datos nunca divergen).
-- El contenido del cursor es opaco para la persistencia; lo serializa cada conector (JSON).
CREATE TABLE IF NOT EXISTS conector_cursor (
  fuente TEXT PRIMARY KEY,
  cursor TEXT,
  updated_at TEXT
);

-- Índices explícitos: los patrones de lectura congelados de spec §7/§9.
-- (Los UNIQUE/PK ya crean los suyos; SQLite NO indexa hijos de FK automáticamente.)
CREATE INDEX IF NOT EXISTS idx_documents_dia ON documents(dia);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_term_stats_day ON term_stats(day);
CREATE INDEX IF NOT EXISTS idx_term_stats_term ON term_stats(term_id);
CREATE INDEX IF NOT EXISTS idx_signals_day ON signals(day);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_alert_log_signal ON alert_log(signal_id);
CREATE INDEX IF NOT EXISTS idx_gdelt_ref_day ON gdelt_ref(day);
CREATE INDEX IF NOT EXISTS idx_predictions_estado ON predictions(estado);
CREATE INDEX IF NOT EXISTS idx_ops_metrics_clave_ts ON ops_metrics(clave, ts);
