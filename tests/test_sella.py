"""T1 · capa de datos del registro sellado (plan Liskov Bloque 6 §9, C-B6-n).

La capa pura (sibila/registro/) es de Turing y se construye EN PARALELO: dobles
conformes al contrato §3 (canonical_json, Senal, BorradorPrediccion, derivar,
construir_linea, hash_linea, verificar_lineas, vencida). El humo TP-N13/TP-N5
corre contra la capa real cuando exista (choque → FALLO visible, nunca skip
silencioso).
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import hashlib
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import db, sella

HOY = datetime(2026, 8, 24, 6, 0, 0)     # reloj congelado
AYER = "2026-08-23"
VENT_RE = re.compile(r"^P(\d+)D$")


# ---------- Dobles de la capa pura (contrato §3) ----------

@dataclass(frozen=True)
class Senal:
    target_type: str
    target: str
    metric: str
    score: Decimal
    status: str
    day: str


@dataclass(frozen=True)
class BorradorPrediccion:
    tema: str
    metrica: str
    umbral: str
    ventana: str
    criterio_acierto: str


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def hash_linea(linea_sin_hash: dict) -> str:
    return hashlib.sha256(canonical_json(linea_sin_hash)).hexdigest()


def construir_linea(b, created_at: str, prev_hash: str) -> dict:
    if not VENT_RE.fullmatch(b.ventana):
        raise ValueError(f"ventana no ISO-8601: {b.ventana!r}")
    linea = {"tema": b.tema, "metrica": b.metrica, "umbral": b.umbral,
             "ventana": b.ventana, "criterio_acierto": b.criterio_acierto,
             "created_at": created_at, "prev_hash": prev_hash}
    linea["hash"] = hash_linea(linea)
    return linea


def derivar(senales, dia):
    """Un borrador por señal (regla del doble): umbral = score de la señal."""
    return tuple(BorradorPrediccion(
        tema=s.target, metrica=s.metric, umbral=f"{s.score:.4f}",
        ventana="P30D", criterio_acierto=f"{s.target} supera umbral en ventana")
        for s in senales)


def vencida(created_at: str, ventana: str, dia) -> bool:
    # ESTRICTA como la real (D-T6-4): dia debe ser date. El doble laxo que
    # toleraba str ocultó el TypeError de producción (rev. Dijkstra B1 /
    # Hamilton N1): el doble jamás puede ser más permisivo que el contrato.
    if not isinstance(dia, date):
        raise TypeError(f"vencida exige date, llegó {type(dia).__name__}")
    m = VENT_RE.fullmatch(ventana)
    dias = int(m.group(1)) if m else 30
    return date.fromisoformat(created_at[:10]) + timedelta(days=dias) < dia


def verificar_lineas(lineas):
    """Doble de la verificación pura: tupla COMPLETA de roturas, sin early
    return (M1 de Turing)."""
    roturas = []
    prev = "0" * 64
    prev_fecha = ""
    for i, l in enumerate(lineas, 1):
        if i == 1 and l.get("prev_hash") != "0" * 64:
            roturas.append("génesis: prev_hash de la línea 1 no es 64 ceros")
        esperado = hash_linea({k: l[k] for k in
                               ("tema", "metrica", "umbral", "ventana",
                                "criterio_acierto", "created_at", "prev_hash")})
        if l.get("hash") != esperado:
            roturas.append(f"hash línea {i}")
        if i > 1 and l.get("prev_hash") != prev:
            roturas.append(f"prev_hash línea {i}")
        if l.get("metrica") not in ("z_r", "cusum", "mk") or \
                not VENT_RE.fullmatch(l.get("ventana", "")):
            roturas.append(f"dominio línea {i}")
        if l.get("created_at", "") < prev_fecha:
            roturas.append(f"orden línea {i}: created_at decreciente")
        prev = esperado   # la cadena se encadena sobre el hash RECOMPUTADO (M1)
        prev_fecha = l.get("created_at", "")
    return SimpleNamespace(ok=not roturas, n_lineas=len(lineas),
                           roturas=tuple(roturas), anclajes=())


def capa_fake():
    return SimpleNamespace(canonical_json=canonical_json, Senal=Senal,
                           derivar=derivar, construir_linea=construir_linea,
                           hash_linea=hash_linea, verificar_lineas=verificar_lineas,
                           vencida=vencida)


# ---------- Base ----------

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(data_dir=self.tmp / "datos")
        self.capa = capa_fake()
        with db.tx(self.con):
            self.con.execute("INSERT INTO sources(nombre, peso) VALUES ('f1', 1.0)")

    def _ejecutar(self, **kw):
        kw.setdefault("ahora", HOY)
        kw.setdefault("capa", self.capa)
        return sella.ejecutar(self.cfg, self.con, **kw)

    def _senal(self, dia=AYER, tema="crisis", metric="z_r", score=4.5,
               status="confirmado"):
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                             (tema,))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (tema,)).fetchone()[0]
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, ?, ?, ?, ?)",
                (dia, tid, metric, score, status, f"{dia}T00:00:00Z"))
        return tid

    def _historia(self, dias=30):
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES ('x', 'term')")
            tid = self.con.execute("SELECT id FROM terms WHERE text='x'").fetchone()[0]
            ini = date.fromisoformat(AYER) - timedelta(days=dias)
            self.con.execute(
                "INSERT OR IGNORE INTO term_stats(day, term_id, docs, occ, df)"
                " VALUES (?, ?, 1, 1, 1)", (ini.isoformat(), tid))

    def _fichero(self):
        return Path(self.cfg.data_dir) / "registro" / "predicciones.jsonl"

    def _lineas(self):
        ruta = self._fichero()
        if not ruta.exists():
            return []
        return [json.loads(t) for t in ruta.read_bytes().split(b"\n") if t]

    def _filas(self):
        return self.con.execute(
            "SELECT * FROM predictions ORDER BY id ASC").fetchall()


class TestSellarBasico(Base):
    def test_linea_y_fila_8_campos(self):
        self._senal()
        res = self._ejecutar(dia=AYER)
        c = res["contadores"]
        self.assertEqual((c["selladas"], c["inmaduras"], c["omitidas"]), (1, 1, 0))
        linea = self._lineas()[0]
        self.assertEqual(linea["prev_hash"], sella.GENESIS)
        self.assertEqual(set(linea), set(sella.CAMPOS_LINEA))
        f = self._filas()[0]
        self.assertEqual((f["estado"], f["madura"]), ("pendiente", 0))  # sin historia
        self.assertEqual(f["hash"], linea["hash"])
        # bytes del fichero == canonical_json + \n (trampa 3)
        crudo = self._fichero().read_bytes()
        self.assertEqual(crudo, canonical_json(linea) + b"\n")

    def test_tres_senales_tres_lineas_encadenadas(self):
        for i in range(3):
            self._senal(tema=f"tema{i}")
        self._ejecutar(dia=AYER)
        lineas = self._lineas()
        self.assertEqual(len(lineas), 3)
        self.assertEqual(lineas[1]["prev_hash"], lineas[0]["hash"])
        self.assertEqual(lineas[2]["prev_hash"], lineas[1]["hash"])

    def test_inmaduras_tambien_se_sellan(self):  # trampa 13 · gate G1
        for i in range(5):
            self._senal(tema=f"g{i}", status="inmaduro")
        res = self._ejecutar(dia=AYER)
        self.assertEqual(res["contadores"]["selladas"], 5)
        self.assertTrue(all(f["madura"] == 0 for f in self._filas()))

    def test_metricas_registro(self):
        self._senal()
        self._ejecutar(dia=AYER)
        claves = {r[0] for r in self.con.execute(
            "SELECT DISTINCT clave FROM ops_metrics WHERE clave LIKE 'registro.%'")}
        self.assertTrue({f"registro.{k}" for k in sella.CLAVES_METRICAS} <= claves)


class TestDedup(Base):  # (1), (1b), (1c) · trampa 7
    def test_doble_sellado_idemponente(self):  # TP-N8 análogo · C-B6-4
        self._senal()
        self._ejecutar(dia=AYER)
        bytes1 = self._fichero().read_bytes()
        filas1 = [tuple(r) for r in self._filas()]
        res = self._ejecutar(dia=AYER)
        self.assertEqual(res["contadores"]["selladas"], 0)
        self.assertEqual(res["contadores"]["omitidas"], 1)
        self.assertEqual(self._fichero().read_bytes(), bytes1)   # byte a byte
        self.assertEqual([tuple(r) for r in self._filas()], filas1)

    def test_realerta_tras_vencimiento_si_sella(self):  # B1 ratificada
        self._senal()
        self._ejecutar(dia=AYER)
        # Envejece la predicción: created_at hace 40 días → vencida (P30D)
        viejo = (HOY - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with db.tx(self.con):
            self.con.execute("UPDATE predictions SET created_at = ?", (viejo,))
        res = self._ejecutar(dia=AYER)
        self.assertEqual(res["contadores"]["selladas"], 1)   # línea NUEVA misma clave
        self.assertEqual(len(self._lineas()), 2)

    def test_realerta_tras_resolucion_si_sella(self):  # M3 de Turing
        self._senal()
        self._ejecutar(dia=AYER)
        with db.tx(self.con):
            self.con.execute("UPDATE predictions SET estado = 'cumplida'")
        res = self._ejecutar(dia=AYER)
        self.assertEqual(res["contadores"]["selladas"], 1)

    def test_multidia_mismo_tema_se_omite_la_segunda(self):  # 1c · M4
        self._senal(dia="2026-08-22", tema="eco")
        self._senal(dia=AYER, tema="eco")
        res = self._ejecutar(desde="2026-08-22", hasta=AYER)
        self.assertEqual(res["contadores"]["selladas"], 1)
        self.assertEqual(res["contadores"]["omitidas"], 1)


class TestReconciliacion(Base):  # (2), (2b), (3) · §4.1
    def test_fila_borrada_se_reinserta_y_fichero_intacto(self):
        self._senal()
        self._ejecutar(dia=AYER)
        bytes1 = self._fichero().read_bytes()
        with db.tx(self.con):
            self.con.execute("DELETE FROM predictions")
        res = self._ejecutar(dia="2026-08-20")   # día sin señales nuevas
        self.assertEqual(res["contadores"]["reconciliadas"], 1)
        self.assertEqual(self._fichero().read_bytes(), bytes1)
        self.assertEqual(len(self._filas()), 1)

    def test_madura_reconciliada_por_created_at_de_la_linea(self):  # M2 Turing
        # Línea sellada hace 40 días, cuando NO había historia; la
        # reconciliación corre hoy con 40 días de historia: madura debe seguir
        # siendo 0 (se computa por el created_at DE LA LÍNEA, nunca de hoy).
        hace40 = HOY - timedelta(days=40)
        self._senal()
        self._ejecutar(dia=AYER, ahora=hace40)
        self._historia(dias=41)   # hoy sí hay historia ≥28
        with db.tx(self.con):
            self.con.execute("DELETE FROM predictions")
        self._ejecutar(dia="2026-08-20")
        self.assertEqual(self._filas()[0]["madura"], 0)

    def test_gate_estados_no_pendientes(self):    # 2b · M2
        self._senal()
        self._ejecutar(dia=AYER)
        with db.tx(self.con):
            self.con.execute("UPDATE predictions SET estado = 'fallada'")
            self.con.execute("DELETE FROM predictions")
        # borramos la única fila (fallada) → tabla vacía, estados no-pendientes 0…
        # sembramos una no-pendiente distinta para disparar el gate:
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO predictions(tema, metrica, umbral, ventana,"
                " criterio_acierto, created_at, hash, prev_hash, estado, madura)"
                " VALUES ('otra', 'z_r', '1.0', 'P30D', 'x', ?, 'aa', 'bb',"
                " 'cumplida', 0)", (f"{AYER}T00:00:00Z",))
        res = self._ejecutar(dia="2026-08-20")
        self.assertEqual(res["contadores"]["reconciliadas"], 0)
        self.assertTrue(any("reconciliación manual" in a for a in res["avisos"]))
        self.assertEqual(len(self._filas()), 1)   # solo la sembrada

    def test_crash_tras_append_reconcilia(self):  # (3) · D-B6-03
        self._senal()
        real = sella._insertar_prediccion

        def rompe(con, linea, madura):
            raise sqlite3.IntegrityError("commit imposible (crash simulado)")
        with mock.patch.object(sella, "_insertar_prediccion", rompe):
            with self.assertRaises(sella.SellaError):
                self._ejecutar(dia=AYER)
        # La línea quedó en el fichero (cadena íntegra), la tabla vacía
        self.assertEqual(len(self._lineas()), 1)
        self.assertEqual(len(self._filas()), 0)
        res = self._ejecutar(dia="2026-08-20")    # sin mock: reconcilia
        self.assertEqual(res["contadores"]["reconciliadas"], 1)
        self.assertEqual(len(self._filas()), 1)
        v = sella.verificar(self.cfg, self.con, capa=self.capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "sin git"))
        self.assertTrue(v["ok"])

    def test_crash_huerfana_mas_borrador_equivalente(self):  # rev. Hamilton N3
        # CC-T1-3 (I8): crash tras append (línea huérfana) + señal equivalente
        # aún presente → el re-run reconcilia la huérfana Y filtra el borrador
        # equivalente: 1 línea / 1 fila (no 2/2 con clave lógica duplicada).
        self._senal()
        self._ejecutar(dia=AYER)
        with db.tx(self.con):                     # crash: fila perdida
            self.con.execute("DELETE FROM predictions")
        res = self._ejecutar(dia=AYER)            # la señal sigue ahí
        self.assertEqual(res["contadores"]["reconciliadas"], 1)
        self.assertEqual(res["contadores"]["selladas"], 0)   # borrador filtrado
        self.assertEqual(len(self._lineas()), 1)
        self.assertEqual(len(self._filas()), 1)
        v = sella.verificar(self.cfg, self.con, capa=self.capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "sin git"))
        self.assertTrue(v["ok"], v["roturas"])

    def test_reconciliada_vencida_sigue_viva_en_el_rango(self):  # rev. H-N3
        # La mordida del `claves_vivas |= reconciliadas_claves` (sella.py:228):
        # huérfana con created_at VENCIDA (la re-lectura de la tabla del día
        # siguiente no la ve) + señal equivalente al día siguiente DEL MISMO
        # rango → la clave reconciliada sigue viva: la señal se omite.
        self._senal(dia="2026-08-22", tema="crisis")
        ahora_viejo = HOY - timedelta(days=40)    # línea sellada hace 40 días
        self._ejecutar(dia="2026-08-22", ahora=ahora_viejo)
        with db.tx(self.con):
            self.con.execute("DELETE FROM predictions")       # huérfana
            # y la señal original ya no está (resuelta): el día 22 solo
            # reconcilia; SIN un borrador equivalente ese mismo día, la clave
            # solo sobrevive en claves_vivas si la |= la anota (rev. H-N3)
            self.con.execute("DELETE FROM signals")
        self._senal(dia=AYER, tema="crisis")      # misma clave lógica, día 23
        res = self._ejecutar(desde="2026-08-22", hasta=AYER)
        self.assertEqual(res["contadores"]["reconciliadas"], 1)
        self.assertEqual(len(self._lineas()), 1)   # sin la línea: 2 (duplicada)


class TestDescartadoNoSeSella(Base):  # rev. Hamilton N1 (consumidor sella)
    def test_senal_descartada_no_se_sella(self):
        # CC-T1-1: una señal 'descartado' (soft-delete) NO es candidata a
        # predicción. La mutación (incluir 'descartado' en el IN de
        # sella._senales_dia) muere aquí.
        self._senal(status="descartado")
        res = self._ejecutar(dia=AYER)
        self.assertEqual(res["contadores"]["selladas"], 0)
        self.assertEqual(len(self._lineas()), 0)
        self.assertEqual(len(self._filas()), 0)

    def test_cola_coja_exit_1_y_fichero_intacto(self):  # 3b · B1 Turing · trampa 4
        self._senal()
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        datos = ruta.read_bytes()
        ruta.write_bytes(datos[:-10])             # cola coja: sin \n final
        self._senal(tema="otra")
        with self.assertRaises(sella.SellaError) as ctx:
            self._ejecutar(dia=AYER)
        self.assertIn("última línea incompleta (crash previo)", str(ctx.exception))
        self.assertIn("intervención manual requerida", str(ctx.exception))
        self.assertEqual(ruta.read_bytes(), datos[:-10])   # intacto

    def test_cola_coja_verificar_avisa_e_integro(self):
        self._senal(tema="a")
        self._senal(tema="b")
        self._ejecutar(dia=AYER)
        # crash tras el append de la 2ª línea y antes de su fila: cola coja
        with db.tx(self.con):
            self.con.execute("DELETE FROM predictions WHERE tema = 'b'")
        ruta = self._fichero()
        ruta.write_bytes(ruta.read_bytes()[:-10])  # coja la 2ª; la 1ª íntegra
        v = sella.verificar(self.cfg, self.con, capa=self.capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "sin git"))
        self.assertTrue(v["cola_coja"])
        self.assertTrue(v["ok"], v["roturas"])


class TestVerificar(Base):  # §6 anti-manipulación
    def _v(self):
        return sella.verificar(self.cfg, self.con, capa=self.capa,
                               anclaje=SimpleNamespace(estado_anclaje=lambda r: "pendiente"))

    def test_integro(self):
        for i in range(5):
            self._senal(tema=f"t{i}")
        self._ejecutar(dia=AYER)
        v = self._v()
        self.assertTrue(v["ok"])
        self.assertEqual(v["n_lineas"], 5)
        self.assertEqual(v["roturas"], ())

    def test_edicion_linea_2_tupla_completa_de_roturas(self):  # (4) · M1 Turing
        for i in range(5):
            self._senal(tema=f"t{i}")
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        lineas = [json.loads(t) for t in ruta.read_bytes().split(b"\n") if t]
        lineas[1]["umbral"] = "9.9999"            # manipulación casual
        ruta.write_bytes(b"".join(canonical_json(l) + b"\n" for l in lineas))
        v = self._v()
        self.assertFalse(v["ok"])
        roturas = " | ".join(v["roturas"])
        self.assertIn("hash línea 2", roturas)    # su propio hash…
        self.assertIn("prev_hash línea 3", roturas)  # …y el encadenamiento
        self.assertGreaterEqual(len(v["roturas"]), 2)   # sin return-early

    def test_genesis_alterado(self):              # (5)
        self._senal()
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        l = self._lineas()[0]
        l["prev_hash"] = "1" * 64
        ruta.write_bytes(canonical_json(l) + b"\n")
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("génesis" in r for r in v["roturas"]))

    def test_created_at_decreciente(self):        # (6)
        self._senal(tema="a")
        self._senal(tema="b")
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        lineas = self._lineas()
        lineas[1]["created_at"] = "2020-01-01T00:00:00Z"
        ruta.write_bytes(b"".join(canonical_json(l) + b"\n" for l in lineas))
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("orden" in r for r in v["roturas"]))

    def test_fila_sin_linea_es_rotura(self):      # (8) · trampa 8
        self._senal()
        self._ejecutar(dia=AYER)
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO predictions(tema, metrica, umbral, ventana,"
                " criterio_acierto, created_at, hash, prev_hash, estado, madura)"
                " VALUES ('mano', 'z_r', '1.0', 'P30D', 'x', ?, 'cc', 'dd',"
                " 'pendiente', 0)", (f"{AYER}T00:00:00Z",))
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("sin línea" in r for r in v["roturas"]))

    def test_crlf_detectado_por_bytes(self):      # (11) · trampa 3
        self._senal()
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        ruta.write_bytes(ruta.read_bytes().replace(b"\n", b"\r\n"))
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("bytes no canónicos" in r for r in v["roturas"]))

    def test_linea_en_blanco_interior_es_rotura(self):  # rev. Hamilton M1
        # Solo el \n FINAL es descartable: una línea en blanco INTERIOR
        # (edición manual invisible a byte-exactitud) se reporta con línea.
        for i in range(3):
            self._senal(tema=f"bl{i}")
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        datos = ruta.read_bytes()
        primera, resto = datos.split(b"\n", 1)
        ruta.write_bytes(primera + b"\n\n" + resto)   # línea 2 en blanco
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("línea 2" in r and "vacía" in r
                            for r in v["roturas"]), v["roturas"])
        # y sellar NO prosigue sobre un fichero manipulado
        with self.assertRaises(sella.SellaError) as cm:
            self._ejecutar(dia=AYER)
        self.assertIn("línea 2", str(cm.exception))

    def test_json_invalido_interior_es_rotura_localizada(self):  # rev. Dijkstra M1
        # Corrupción de bytes en medio del fichero: jamás JSONDecodeError
        # desnudo; rotura con número de línea y causa.
        for i in range(3):
            self._senal(tema=f"js{i}")
        self._ejecutar(dia=AYER)
        ruta = self._fichero()
        trozos = ruta.read_bytes().split(b"\n")
        trozos[1] = b'{"tema": ROTO'                  # línea 2 corrupta
        ruta.write_bytes(b"\n".join(trozos))
        v = self._v()
        self.assertFalse(v["ok"])
        self.assertTrue(any("línea 2" in r and "JSON inválido" in r
                            for r in v["roturas"]), v["roturas"])
        with self.assertRaises(sella.SellaError) as cm:
            self._ejecutar(dia=AYER)
        self.assertIn("línea 2", str(cm.exception))
        self.assertIn("JSON inválido", str(cm.exception))


class TestMadura(Base):  # (9) · misma definición que detecta (D-041)
    def test_madura_0_sin_historia_y_1_con_28_dias(self):
        self._senal(tema="joven")
        self._ejecutar(dia=AYER)
        self.assertEqual(self._filas()[0]["madura"], 0)
        self._historia(dias=28)
        self._senal(tema="vieja")
        self._ejecutar(dia=AYER)
        m = {f["tema"]: f["madura"] for f in self._filas()}
        self.assertEqual(m, {"joven": 0, "vieja": 1})


class TestFronteraPura(Base):  # (7) · M4: mi capa NO pre-valida formato
    def test_ventana_malformada_la_rechaza_la_pura(self):
        self._senal()
        self.capa.derivar = lambda senales, dia: (BorradorPrediccion(
            tema="x", metrica="z_r", umbral="1.0", ventana="7 días",
            criterio_acierto="x"),)
        with self.assertRaises(sella.SellaError) as ctx:
            self._ejecutar(dia=AYER)
        self.assertIn("capa pura rechazó", str(ctx.exception))
        # prohibido regex propio en sella.py (revisión): solo el de la pura
        src = Path(sella.__file__).read_text(encoding="utf-8")
        self.assertNotIn("re.compile", src)


class TestFsync(Base):  # (5) · trampa 5
    def test_un_fsync_por_linea(self):
        for i in range(3):
            self._senal(tema=f"f{i}")
        with mock.patch("os.fsync") as fs:
            self._ejecutar(dia=AYER)
        self.assertEqual(fs.call_count, 3)


class TestConcurrencia(Base):  # trampas 1 y 14 · C-B6-8
    def test_dos_sellas_y_lector_ro_sin_operational_error(self):
        for i in range(4):
            self._senal(dia="2026-08-22", tema=f"a{i}")
            self._senal(dia=AYER, tema=f"b{i}")
        errores = []
        parar = threading.Event()

        def lector():  # espejo resumen.py: mode=ro, timeout=30
            uri = f"file:{self.db_path}?mode=ro"
            while not parar.is_set():
                try:
                    c = sqlite3.connect(uri, uri=True, timeout=30)
                    try:
                        c.execute("SELECT COUNT(*) FROM predictions").fetchone()
                    finally:
                        c.close()
                except sqlite3.OperationalError as e:
                    errores.append(e)

        hilo = threading.Thread(target=lector)
        hilo.start()
        try:
            otra = db.connect(self.db_path)
            try:
                r1 = sella.ejecutar(self.cfg, self.con, dia="2026-08-22",
                                    ahora=HOY, capa=self.capa)
                r2 = sella.ejecutar(self.cfg, otra, dia=AYER, ahora=HOY,
                                    capa=self.capa)
            finally:
                otra.close()
        finally:
            parar.set()
            hilo.join()
        self.assertEqual(errores, [])
        self.assertEqual(len(self._lineas()), 8)  # cadena única, sin ramas
        hashes = [l["hash"] for l in self._lineas()]
        self.assertEqual(len(set(hashes)), 8)

    def test_prev_hash_se_lee_dentro_de_la_tx(self):  # rev. Dijkstra M2 · trampa 1
        # La lectura del último hash es sección crítica: debe ocurrir DENTRO
        # del BEGIN IMMEDIATE. Espía de orden de operaciones: si la lectura
        # sale de la tx (la mutación), la primera llamada registra False.
        self._senal()
        dentro = []
        real_tx = sella.db.tx
        import contextlib

        token = [False]

        @contextlib.contextmanager
        def tx_espiada(con):
            with real_tx(con):
                token[0] = True
                try:
                    yield
                finally:
                    token[0] = False

        real_leer = sella._leer_lineas

        def leer_espiada(ruta):
            dentro.append(token[0])
            return real_leer(ruta)

        with mock.patch.object(sella.db, "tx", tx_espiada), \
                mock.patch.object(sella, "_leer_lineas", leer_espiada):
            self._ejecutar(dia=AYER)
        # 1ª lectura = la de sellar_dia (prev_hash, sección crítica); la
        # última = el recuento de ejecutar, fuera de tx por diseño
        self.assertEqual(dentro[0], True)
        self.assertEqual(dentro[-1], False)
        for i, l in enumerate(self._lineas()[1:], 1):
            self.assertEqual(l["prev_hash"], self._lineas()[i - 1]["hash"])


class TestGuardian(Base):  # C-B6-6
    def test_registro_puro_sin_io(self):
        import ast
        paq = Path(sella.__file__).parent / "registro"
        if not paq.is_dir():
            self.skipTest("sibila/registro aún no existe (agente paralelo)")
        for py in sorted(paq.glob("*.py")):
            arbol = ast.parse(py.read_text(encoding="utf-8"))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    for a in nodo.names:
                        self.assertNotIn(a.name.split(".")[0],
                                         {"sqlite3", "subprocess"}, py.name)
                if isinstance(nodo, ast.ImportFrom) and nodo.module:
                    self.assertNotIn(nodo.module.split(".")[0],
                                     {"sqlite3", "subprocess"}, py.name)

    def test_solo_anclaje_usa_subprocess(self):
        raiz = Path(sella.__file__).parent
        for py in raiz.rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            src = py.read_text(encoding="utf-8")
            if py.name != "anclaje.py":
                self.assertNotIn("import subprocess", src, py.name)


class TestHumoCapaReal(Base):
    """TP-N13/TP-N5 extremo a extremo con sibila/registro REAL. Sin skip:
    un choque de contrato es un FALLO visible (decisión del Orquestador B5)."""

    def _real(self):
        # Sin skip: el humo corre SIEMPRE contra la capa real (entregada por el
        # agente de Turing). Un choque de contrato es un FALLO visible.
        from sibila.registro import canonico, derivar, sellar as rs, verificar
        for mod, attr in ((canonico, "canonical_json"), (derivar, "derivar"),
                          (rs, "construir_linea"), (rs, "hash_linea"),
                          (verificar, "verificar_lineas")):
            self.assertTrue(hasattr(mod, attr),
                            f"fachada §3 rota: {mod.__name__}.{attr}")
        self.assertTrue(hasattr(derivar, "vencida") or hasattr(verificar, "vencida"),
                        "fachada §3 rota: vencida")
        return sella._capa(None)

    def test_tp_n5_cadena_extremo_a_extremo(self):
        capa = self._real()
        for i in range(5):
            self._senal(tema=f"rampa{i}", status="inmaduro")
        res = sella.ejecutar(self.cfg, self.con, dia=AYER, ahora=HOY, capa=capa)
        self.assertEqual(res["contadores"]["selladas"], 5)
        self.assertTrue(all(f["madura"] == 0 for f in self._filas()))  # G1 parcial
        v = sella.verificar(self.cfg, self.con, capa=capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "pendiente"))
        self.assertTrue(v["ok"], v["roturas"])
        # manipulación de una línea antigua → detectada con línea y causa
        ruta = self._fichero()
        lineas = self._lineas()
        lineas[1]["umbral"] = "9.9999"
        ruta.write_bytes(b"".join(capa.canonical_json(l) + b"\n" for l in lineas))
        v2 = sella.verificar(self.cfg, self.con, capa=capa,
                             anclaje=SimpleNamespace(estado_anclaje=lambda r: "pendiente"))
        self.assertFalse(v2["ok"])
        self.assertTrue(any("línea 2" in r or "línea 3" in r for r in v2["roturas"]))

    def test_segunda_ejecucion_idempotente_capa_real(self):  # rev. B1/N1 · TP-N8
        # La dedup llama a vencida() real (exige date): la SEGUNDA ejecución
        # con pendientes vivos no puede crashear → 0 selladas, N omitidas.
        capa = self._real()
        for i in range(3):
            self._senal(tema=f"rampa{i}", status="inmaduro")
        self._ejecutar(dia=AYER, capa=capa)
        bytes1 = self._fichero().read_bytes()
        res = self._ejecutar(dia=AYER, capa=capa)   # aquí explotaba (TypeError)
        self.assertEqual(res["contadores"]["selladas"], 0)
        self.assertEqual(res["contadores"]["omitidas"], 3)
        self.assertEqual(self._fichero().read_bytes(), bytes1)   # byte a byte
        v = sella.verificar(self.cfg, self.con, capa=capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "pendiente"))
        self.assertTrue(v["ok"], v["roturas"])

    def test_multidia_con_pendientes_vivos_capa_real(self):  # rev. B1/N1
        # Día 1 sella; día 2 (ya hay pendientes en la tabla → vencida() real
        # se invoca) no crashea y la dedup multi-día omite el mismo tema.
        capa = self._real()
        self._senal(tema="crisis")                          # día 1
        res1 = self._ejecutar(dia=AYER, capa=capa)
        self.assertEqual(res1["contadores"]["selladas"], 1)
        self._senal(dia="2026-08-24", tema="crisis")        # día 2: misma clave
        self._senal(dia="2026-08-24", tema="inflacion")     # día 2: nueva
        res2 = self._ejecutar(dia="2026-08-24", ahora=HOY + timedelta(days=1),
                              capa=capa)
        self.assertEqual(res2["contadores"]["selladas"], 1)
        self.assertEqual(res2["contadores"]["omitidas"], 1)  # crisis: omitida
        self.assertEqual(len(self._lineas()), 2)
        v = sella.verificar(self.cfg, self.con, capa=capa,
                            anclaje=SimpleNamespace(estado_anclaje=lambda r: "pendiente"))
        self.assertTrue(v["ok"], v["roturas"])
    def test_tp_n13_vector_literal(self):
        """Vector (a) TP-N13 congelado (plan_de_pruebas §3.1, D-030): la primera
        línea (prev_hash = génesis) reproduce el SHA-256 literal. Es ley."""
        self._real()
        from sibila.registro.derivar import BorradorPrediccion
        b = BorradorPrediccion(tema="régimen", metrica="z_r", umbral="2.50",
                               ventana="P7D", criterio_acierto="eco>=0,6")
        linea = self._real().construir_linea(b, "2026-01-01T00:00:00Z",
                                             sella.GENESIS)
        self.assertEqual(
            linea["hash"],
            "271a7861dc20c7d1454a0db7609c15dffce043539f0f28aceb4732990b3c427a")


if __name__ == "__main__":
    unittest.main()
