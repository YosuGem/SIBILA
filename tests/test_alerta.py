"""T1 · capa de datos de alerta.py (plan Liskov Bloque 7 §4, TP-N7, trampas).

Dobles de la capa pura §5 (Senal, ContextoDia, clasificar, decidir,
dedup_alertas, Envio); el humo corre contra sibila/alertas REAL.
"""
import sys as _sys
from pathlib import Path as _P
_d = _P(__file__).resolve().parent.parent.parent / "deps"
if _d.is_dir() and str(_d) not in _sys.path:
    _sys.path.insert(0, str(_d))
import sqlite3
import tempfile
import threading
import unittest
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from sibila import alerta, db

HOY = datetime(2026, 8, 24, 6, 0, 0, tzinfo=timezone.utc)
AYER = "2026-08-23"


# ---------- Dobles de la capa pura (contrato §5) ----------

@dataclass(frozen=True)
class SenalFake:
    tema: str
    target_type: str
    status: str
    day: date


@dataclass(frozen=True)
class ContextoDiaFake:
    z_r: object
    p_mk: object
    s_cusum: object
    racha_z: int
    status: str
    alertas_previas_tema_7d: int


@dataclass(frozen=True)
class EnvioFake:
    tema: str
    nivel: str
    sent_at: object


def clasificar_fake(senal, ctx):
    """vigilancia si 3 ≤ z_r < 4; alerta si 4 ≤ z_r < 6; alarma si z_r ≥ 6;
    None si z_r < 3 o ciego."""
    if ctx.z_r is None or ctx.z_r < 3:
        return None
    if ctx.z_r >= 6:
        return "alarma"
    if ctx.z_r >= 4:
        return "alerta"
    return "vigilancia"


def decidir_fake(tema, nivel, historial, ahora):
    """Cooldown: suprime si el último envío de (tema,nivel) fue hace <24 h."""
    ult = None
    for e in historial:
        if e.tema == tema and e.nivel == nivel:
            s = e.sent_at
            dt = s if isinstance(s, datetime) else datetime.strptime(
                s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            ult = dt
    if ult is not None and (ahora - ult) < timedelta(hours=24):
        return SimpleNamespace(enviar=False, motivo="cooldown", horas=Decimal(2))
    return SimpleNamespace(enviar=True, motivo=None, horas=None)


def dedup_alertas_fake(nuevas, historial, ahora):
    emitir, supr, efectivo = [], [], list(historial)
    for tema, nivel in nuevas:
        d = decidir_fake(tema, nivel, tuple(efectivo), ahora)
        if d.enviar:
            emitir.append((tema, nivel))
            efectivo.append(EnvioFake(tema, nivel, ahora))
        else:
            supr.append((tema, nivel))
    return tuple(emitir), tuple(supr)


def capa_fake():
    return SimpleNamespace(Senal=SenalFake, ContextoDia=ContextoDiaFake,
                           clasificar=clasificar_fake, decidir=decidir_fake,
                           dedup_alertas=dedup_alertas_fake, Envio=EnvioFake)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sibila José Pérez "))
        self.db_path = self.tmp / "t.db"
        db.init_db(self.db_path)
        self.con = db.connect(self.db_path)
        self.addCleanup(self.con.close)
        self.cfg = SimpleNamespace(
            data_dir=self.tmp,
            secretos={"telegram_token": "tok", "telegram_chat": "chat"})
        self.capa = capa_fake()
        self.envios = []

    def _enviar(self, cfg, canal, mensaje):
        self.envios.append((canal, mensaje))

    def _senal(self, dia=AYER, tema="crisis", z_r=4.5, status="confirmado",
               con_cusum_mk=True):
        """Signal agrupada: z_r (+cusum/mk opcionales) y z_r en term_stats."""
        with db.tx(self.con):
            self.con.execute("INSERT OR IGNORE INTO terms(text, type) VALUES (?, 'term')",
                             (tema,))
            tid = self.con.execute("SELECT id FROM terms WHERE text = ?",
                                   (tema,)).fetchone()[0]
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, 'z_r', ?, ?, ?)",
                (dia, tid, z_r, status, f"{dia}T00:00:00Z"))
            sid = self.con.execute("SELECT MAX(id) FROM signals").fetchone()[0]
            if con_cusum_mk:
                for metric, score in (("cusum", 8.0), ("mk", 0.01)):
                    self.con.execute(
                        "INSERT INTO signals(day, target_type, target_id, metric,"
                        " score, status, created_at) VALUES (?, 'term', ?, ?, ?,"
                        " ?, ?)", (dia, tid, metric, score, status,
                                   f"{dia}T00:00:00Z"))
            self.con.execute(
                "INSERT OR IGNORE INTO term_stats(day, term_id, docs, occ, df, z_r)"
                " VALUES (?, ?, 5, 5, 5, ?)", (dia, tid, z_r))
        return sid

    def _ejecutar(self, **kw):
        kw.setdefault("desde", AYER)
        kw.setdefault("hasta", AYER)
        kw.setdefault("ahora", HOY)
        kw.setdefault("capa", self.capa)
        kw.setdefault("enviar", self._enviar)
        return alerta.ejecutar(self.cfg, self.con, **kw)

    def _log(self):
        return self.con.execute(
            "SELECT signal_id, nivel, canal, sent_at FROM alert_log"
            " ORDER BY rowid").fetchall()


class TestClasificacionYFiltros(Base):
    def test_sin_alertas(self):
        res = self._ejecutar()
        self.assertTrue(res["sin_alertas"])

    def test_vigilancia_nunca_toca_red_ni_alert_log(self):  # trampa 11/M2
        self._senal(z_r=3.5)                         # vigilancia en el doble
        res = self._ejecutar()
        self.assertEqual(res["contadores"]["_vigilancias_digest"], 1)
        self.assertEqual(self.envios, [])
        self.assertEqual(self._log(), [])            # NADA individual en alert_log

    def test_senal_bajo_umbral_se_ignora(self):
        self._senal(z_r=2.0)
        res = self._ejecutar()
        self.assertTrue(res["sin_alertas"])
        self.assertEqual(self._log(), [])

    def test_alerta_envia_y_registra(self):
        sid = self._senal(z_r=4.5)
        res = self._ejecutar()
        self.assertEqual(res["contadores"]["enviadas"], 1)
        self.assertEqual(len(self.envios), 1)
        canal, mensaje = self.envios[0]
        self.assertEqual(canal, "telegram")
        self.assertIn("crisis", mensaje)
        self.assertNotIn("[INMADURO]", mensaje)
        filas = self._log()
        self.assertEqual(len(filas), 1)
        self.assertEqual((filas[0]["signal_id"], filas[0]["nivel"],
                          filas[0]["canal"]), (sid, "alerta", "telegram"))

    def test_inmaduro_nunca_escala_a_alarma(self):  # B2 · vector (iii)
        self._senal(z_r=7.5, status="inmaduro")      # alarma si confirmado
        res = self._ejecutar()
        canal, mensaje = self.envios[0]
        self.assertIn("[INMADURO]", mensaje)
        self.assertEqual(self._log()[0]["nivel"], "alerta")   # tope alerta

    def test_metricas_alerta(self):
        self._senal()
        self._ejecutar()
        claves = {r[0] for r in self.con.execute(
            "SELECT DISTINCT clave FROM ops_metrics WHERE clave LIKE 'alerta.%'")}
        self.assertEqual(claves, {f"alerta.{k}" for k in alerta.CLAVES_METRICAS})


class TestCooldown(Base):  # §5.1 · D-T7-4
    def test_dedup_multirrango_mismo_tema_un_solo_envio(self):  # rev. Dijkstra M1
        # Mismo (tema,nivel) alertando DOS días de un rango solapado: el dedup
        # de tanda suprime la segunda; el emparejamiento POSICIONAL impide el
        # doble envío (la pertenencia por conjunto enviaba AMBAS).
        self._senal(dia="2026-08-22")
        self._senal(dia=AYER)
        res = self._ejecutar(desde="2026-08-22", hasta=AYER)
        self.assertEqual(len(self.envios), 1)              # un solo envío
        self.assertEqual(res["contadores"]["cooldown_omitidas"], 1)
        self.assertEqual(len(self._log()), 1)              # un solo registro

    def test_cooldown_suprime_y_lo_dice(self):
        self._senal()
        self._ejecutar()
        res = self._ejecutar()                       # misma (tema,nivel) <24 h
        self.assertEqual(res["contadores"]["cooldown_omitidas"], 1)
        self.assertEqual(len(self.envios), 1)        # sin segundo envío
        self.assertTrue(any("cooldown" in t for n, t in res["lineas"]))

    def test_reejecucion_mismo_rango_no_duplica(self):  # C-B7-7
        self._senal()
        self._ejecutar(desde="2026-08-20", hasta=AYER)
        self._ejecutar(desde="2026-08-20", hasta=AYER)
        self.assertEqual(len(self.envios), 1)

    def test_tras_25h_si_reeenvia(self):
        self._senal()
        self._ejecutar()
        res = self._ejecutar(ahora=HOY + timedelta(hours=25))
        self.assertEqual(res["contadores"]["enviadas"], 1)
        self.assertEqual(len(self.envios), 2)

    def test_fallo_no_enfria(self):                # B1 · trampa 9
        self._senal()
        self._ejecutar(enviar=lambda c, ch, m: (_ for _ in ()).throw(
            ConnectionError("red caída")))
        canales = {r["canal"] for r in self._log()}
        self.assertEqual(canales, {"fallo:telegram"})
        res = self._ejecutar()                       # red recuperada
        self.assertEqual(res["contadores"]["enviadas"], 1)   # NO hubo cooldown


class TestFallosDeCanal(Base):  # aislamiento por canal (patrón ingesta)
    def test_un_canal_cae_y_el_otro_sobrevive(self):
        self.cfg.secretos["smtp_password"] = "x"
        self.cfg.secretos["smtp_destino"] = "a@b.c"

        def enviar(cfg, canal, msg):
            if canal == "telegram":
                raise ConnectionError("telegram caído")
            self.envios.append((canal, msg))
        sid = self._senal()
        res = self._ejecutar(enviar=enviar)
        self.assertEqual(res["contadores"]["enviadas"], 1)
        self.assertEqual([c for c, _ in self.envios], ["smtp"])
        canales = {r["canal"] for r in self._log()}
        self.assertEqual(canales, {"fallo:telegram", "smtp"})

    def test_todos_los_canales_caen(self):         # exit 1 en el CLI
        self._senal()
        res = self._ejecutar(enviar=lambda c, ch, m: (_ for _ in ()).throw(
            ConnectionError("caído")))
        self.assertTrue(res["todos_caidos"])
        self.assertEqual(res["contadores"]["fallos"], 1)

    def test_sin_credenciales_aviso_y_exit_1(self):
        self.cfg.secretos = {}
        self._senal()
        res = self._ejecutar()
        self.assertEqual(res["contadores"]["sin_credenciales"], 1)
        self.assertTrue(any("telegram" in a for a in res["avisos"]))


class TestRedFueraDeTx(Base):  # trampa 10 · regla Bloque 2
    def test_la_red_no_se_hace_con_tx_abierta(self):
        """Durante el envío, OTRO escritor debe poder comitear al instante:
        si la red corriera dentro de la tx, el INSERT externo haría timeout."""
        self._senal()
        externa = db.connect(self.db_path)
        self.addCleanup(externa.close)
        resultado = {}

        def enviar_intrometido(cfg, canal, msg):
            try:
                with db.tx(externa):
                    externa.execute(
                        "INSERT INTO ops_metrics(ts, clave, valor)"
                        " VALUES ('2026-08-24T06:00:00Z', 'externa.ok', 1)")
                resultado["escribio"] = True
            except Exception as e:
                resultado["escribio"] = False
                resultado["error"] = str(e)
        self._ejecutar(enviar=enviar_intrometido)
        self.assertTrue(resultado.get("escribio"),
                        f"red dentro de tx (bloqueó al escritor): {resultado}")


class TestProbar(Base):  # TP-N7
    def test_probar_ok_registra(self):
        res = alerta.probar(self.cfg, self.con, ahora=HOY, enviar=self._enviar)
        self.assertTrue(res["ok"])
        self.assertEqual(res["canal"], "telegram")
        filas = self._log()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["canal"], "telegram")

    def test_probar_fallo_se_registra(self):
        res = alerta.probar(self.cfg, self.con, ahora=HOY,
                            enviar=lambda c, ch, m: (_ for _ in ()).throw(
                                ConnectionError("caído")))
        self.assertFalse(res["ok"])
        self.assertEqual(self._log()[0]["canal"], "fallo:telegram")

    def test_probar_sin_credenciales(self):
        self.cfg.secretos = {}
        res = alerta.probar(self.cfg, self.con, ahora=HOY)
        self.assertFalse(res["ok"])
        self.assertIn("sin credenciales", res["error"])
        self.assertEqual(self._log()[0]["canal"], "fallo:telegram")  # V9


class TestDigest(Base):  # §9 · trampa 11
    def test_digest_registra_canal_digest_y_anti_dup(self):
        self._senal(z_r=3.5)                          # vigilancia: solo digest
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=self.capa)
        self.assertTrue(res["enviado"])
        self.assertEqual(self._log()[0]["canal"], "digest")
        self.assertEqual(self._log()[0]["nivel"], "vigilancia")
        res2 = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                             ahora=HOY + timedelta(hours=1), enviar=self._enviar,
                             capa=self.capa)
        self.assertFalse(res2["enviado"])             # mismo período: omitido
        self.assertIn("ya enviado", res2["motivo"])
        self.assertEqual(len([r for r in self._log()]), 1)  # sin duplicado

    def test_digest_sin_vigilancias_dice_sin_alertas(self):
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=self.capa)
        self.assertTrue(res["enviado"])
        self.assertEqual(res["lineas"], 1)            # "(sin alertas en la semana)"

    def test_frontera_ventana_digest_168h(self):  # rev. Hamilton M3 · D-T7-4
        # Anti-duplicación 168 h: digest previo a 167h59m → omitido; a 168 h
        # EXACTAS → enviado (comparación estricta). La mutación 7→6 días muere.
        with db.tx(self.con):
            self.con.execute(
                "INSERT INTO alert_log(signal_id, nivel, canal, sent_at)"
                " VALUES (NULL, 'vigilancia', 'digest', ?)",
                ((HOY - timedelta(hours=167, minutes=59))
                 .strftime("%Y-%m-%dT%H:%M:%SZ"),))
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=self.capa)
        self.assertFalse(res["enviado"])                # 167h59m → suprimido
        with db.tx(self.con):
            self.con.execute("UPDATE alert_log SET sent_at = ?",
                             ((HOY - timedelta(hours=168))
                              .strftime("%Y-%m-%dT%H:%M:%SZ"),))
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=self.capa)
        self.assertTrue(res["enviado"])                 # 168h exactas → enviado


DESDE_D = "2026-08-17"


class TestHumoCapaReal(Base):
    """Humo contra sibila/alertas REAL (sin skip: choque → FALLO visible)."""

    def _real(self):
        try:
            from sibila.alertas import reglas, cooldown
        except ImportError as e:
            self.skipTest(f"capa pura aún no entregada: {e}")
        for mod, attr in ((reglas, "clasificar"), (reglas, "ContextoDia"),
                          (reglas, "Senal"), (reglas, "alertas_fmt"),
                          (cooldown, "decidir"), (cooldown, "Envio")):
            self.assertTrue(hasattr(mod, attr), f"fachada rota: {mod.__name__}.{attr}")
        return alerta._capa(None)

    def test_envio_extremo_a_extremo_con_la_pura(self):
        capa = self._real()
        self._senal(z_r=7.5)                          # alarma con la pura real
        res = alerta.ejecutar(self.cfg, self.con, desde=AYER, hasta=AYER,
                              ahora=HOY, enviar=self._enviar, capa=capa)
        c = res["contadores"]
        self.assertEqual(c["enviadas"] + c["cooldown_omitidas"]
                         + c["_vigilancias_digest"], 1)
        if c["enviadas"] == 1:                        # si clasifica alerta/alarma
            self.assertEqual(len(self._log()), 1)

    def test_racha_z_dia_ciego_rompe_la_racha(self):  # rev. Dijkstra B2 · T-B5-12
        # Serie z_r: 4 (d-3), None (d-2, día ciego), 4 (d-1), 4 (d) → racha 2,
        # JAMÁS 4 (el None ROMPE la racha, como motor.racha_alta; la mutación
        # break→continue muere aquí).
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            base = date.fromisoformat(AYER)
            for off, z in ((-3, 4.5), (-2, None), (-1, 4.5), (0, 4.5)):
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, ?)",
                    ((base + timedelta(days=off)).isoformat(), tid, z))
        self.assertEqual(alerta._racha_z(self.con, tid, AYER), 2)

    def test_racha_z_dia_bajo_umbral_rompe_la_racha(self):  # rev. Hamilton R2
        # Espejo de motor.racha_alta (cubierto en la pura, test_deteccion_
        # motor): un día COMPUTABLE con z_r ≤ 3 (ítem no alto; no es día ciego)
        # también ROMPE la racha. Serie 4.5, 2.0, 4.5, 4.5 → racha 2, jamás 3
        # (la mutación break→continue en la rama ≤3 muere aquí).
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            base = date.fromisoformat(AYER)
            for off, z in ((-3, 4.5), (-2, 2.0), (-1, 4.5), (0, 4.5)):
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, ?)",
                    ((base + timedelta(days=off)).isoformat(), tid, z))
        self.assertEqual(alerta._racha_z(self.con, tid, AYER), 2)

    def test_digest_no_duplica_senal_como_vigilancia(self):  # rev. Hamilton R1        # El NOT EXISTS del carril vigilancia (B3): un tema CON fila en signals
        # ese día sale UNA vez con su nivel real (alarma); jamás además como
        # vigilancia del MISMO día. Sin el NOT EXISTS (la mutación) el digest
        # lista "alarma: crisis (AYER)" Y "vigilancia: crisis (AYER)".
        capa = self._real()
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            base = date.fromisoformat(AYER)
            for off in (-2, -1, 0):      # racha 3 días con z_r>3 (conjunción)
                d = (base + timedelta(days=off)).isoformat()
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, 7.0)", (d, tid))
            for metric, score in (("z_r", 7.0), ("cusum", 8.0), ("mk", 0.01)):
                self.con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric,"
                    " score, status, created_at) VALUES (?, 'term', ?, ?, ?,"
                    " 'confirmado', ?)", (AYER, tid, metric, score,
                                          f"{AYER}T00:00:00Z"))
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=capa)
        self.assertTrue(res["enviado"])
        cuerpo = "\n".join(m for _, m in self.envios)
        self.assertIn(f"alarma: crisis ({AYER})", cuerpo)
        self.assertNotIn(f"vigilancia: crisis ({AYER})", cuerpo)

    def test_digest_vigilancias_desde_term_stats_fuente_real(self):  # rev. B3
        # El carril vigilancia vive en term_stats (z_r>3 sin conjunción ⇒ sin
        # fila en signals): el digest debe leerlo AHÍ. Sin la consulta (la
        # mutación) el carril queda muerto y el mensaje dice "(sin alertas)".
        capa = self._real()
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            for d in ("2026-08-22", AYER):            # z_r>3 dos días, SIN signal
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, 3.5)", (d, tid))
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=capa)
        self.assertTrue(res["enviado"])
        cuerpo = "\n".join(m for _, m in self.envios)
        self.assertIn(f"vigilancia: crisis ({AYER})", cuerpo)
        self.assertNotIn("(sin alertas en la semana)", cuerpo)

    def test_descartada_no_es_alerta_previa(self):  # rev. Dijkstra B1 · CC-T1-1
        # Una señal 'descartado' (o 'reactivo') del mismo tema en los 7 días
        # previos NO cuenta como alerta previa: sin el filtro de status en
        # _alertas_previas_7d, la persistencia fantasma escala a ALARMA.
        capa = self._real()
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            base = date.fromisoformat(AYER)
            for off in (-2, -1, 0):        # conjunción: racha 3, z_r<6, cusum, mk
                d = (base + timedelta(days=off)).isoformat()
                self.con.execute(
                    "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                    " VALUES (?, ?, 5, 5, 5, 4.5)", (d, tid))
            for metric, score in (("z_r", 4.5), ("cusum", 6.0), ("mk", 0.01)):
                self.con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric,"
                    " score, status, created_at) VALUES (?, 'term', ?, ?, ?,"
                    " 'confirmado', ?)", (AYER, tid, metric, score,
                                          f"{AYER}T00:00:00Z"))
            # las dos NO-alertas: descartada hace 3 días y reactiva hace 2
            for off, st in ((-3, "descartado"), (-2, "reactivo")):
                d = (base + timedelta(days=off)).isoformat()
                self.con.execute(
                    "INSERT INTO signals(day, target_type, target_id, metric,"
                    " score, status, created_at) VALUES (?, 'term', ?, 'z_r',"
                    " 7.5, ?, ?)", (d, tid, st, f"{d}T00:00:00Z"))
        res = alerta.ejecutar(self.cfg, self.con, desde=AYER, hasta=AYER,
                              ahora=HOY, enviar=self._enviar, capa=capa)
        niveles = [r[0] for r in self.con.execute(
            "SELECT DISTINCT nivel FROM alert_log")]
        self.assertEqual(niveles, ["alerta"])   # previas=0 → sin escalada

    def test_senales_periodo_ignora_descartadas(self):  # rev. Hamilton N1 (alerta)
        # El consumidor _senales_periodo (ejecutar/digest) filtra 'descartado':
        # una señal muerta no puede volar como alerta (el filtro SQL es la
        # frontera; la mutación que incluye 'descartado' muere aquí).
        self._senal(status="descartado")
        self._senal(tema="viva", z_r=4.5, status="confirmado")
        temas = {s["tema"] for s in alerta._senales_periodo(self.con, AYER, AYER)}
        self.assertEqual(temas, {"viva"})

    def test_digest_vigilancia_no_suprimida_por_descartada(self):  # rev. Dijkstra M1
        # La subconsulta NOT EXISTS del carril vigilancia filtra status: una
        # señal 'descartado' del MISMO día/target NO suprime la vigilancia.
        capa = self._real()
        with db.tx(self.con):
            self.con.execute("INSERT INTO terms(text, type) VALUES ('crisis', 'term')")
            tid = self.con.execute("SELECT id FROM terms").fetchone()[0]
            self.con.execute(
                "INSERT INTO term_stats(day, term_id, docs, occ, df, z_r)"
                " VALUES (?, ?, 5, 5, 5, 3.5)", (AYER, tid))
            self.con.execute(
                "INSERT INTO signals(day, target_type, target_id, metric, score,"
                " status, created_at) VALUES (?, 'term', ?, 'z_r', 3.5,"
                " 'descartado', ?)", (AYER, tid, f"{AYER}T00:00:00Z"))
        res = alerta.digest(self.cfg, self.con, desde=DESDE_D, hasta=AYER,
                            ahora=HOY, enviar=self._enviar, capa=capa)
        cuerpo = "\n".join(m for _, m in self.envios)
        self.assertIn(f"vigilancia: crisis ({AYER})", cuerpo)

    def test_timeout_red_30s_telegram(self):  # rev. Hamilton M2 · trampa 12
        # Toda llamada de red lleva timeout=30 (spy sobre requests).
        cfg = SimpleNamespace(secretos={"telegram_token": "t",
                                        "telegram_chat": "c"})
        llamadas = {}
        falso = SimpleNamespace(
            post=lambda url, **kw: llamadas.update(kw) or SimpleNamespace(
                raise_for_status=lambda: None))
        with mock.patch.dict(_sys.modules, {"requests": falso}):
            alerta.enviar_red(cfg, "telegram", "hola")
        self.assertEqual(llamadas["timeout"], 30)   # literal, no la constante

    def test_dec_redondea_half_up(self):  # rev. Dijkstra M5
        # 0,12345 → "0.1235" (HALF_UP), no "0.1234" (HALF_EVEN del contexto).
        self.assertEqual(str(alerta._dec(0.12345)), "0.1235")
        self.assertIsNone(alerta._dec(None))


if __name__ == "__main__":
    unittest.main()
