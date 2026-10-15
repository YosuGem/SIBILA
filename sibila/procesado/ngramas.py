"""N-gramas y clustering diario (spec §6.7; los 7 pasos deterministas).

Regla fijada: los n-gramas se forman sobre la secuencia de palabras tras
quitar las stopwords DEL IDIOMA (si tiene lista), preservando orden y
adyacencia resultante; términos = content words (D-L2). Presencia binaria.
"""
from dataclasses import dataclass

from .dedup import _palabras
from .stopwords import stopwords

_DF_MIN = 3       # U = {t: df ≥ 3} (provisional, spec §6.7)
_C_MIN = 3        # arista si co-ocurrencia ≥ 3
_J_MIN = 0.2      # y Jaccard ≥ 0,2


@dataclass(frozen=True)
class NGramDoc:
    terminos: frozenset      # content words (presencia binaria)
    bigramas: frozenset      # "a b" sobre la secuencia sin stopwords
    trigramas: frozenset     # "a b c" ídem


@dataclass(frozen=True)
class StatsDia:
    df: dict                 # texto de término -> df_día (presencia binaria)
    docs_elegibles: int
    cooc: dict               # (i, j) con i<j alfabético -> c(i, j)


@dataclass(frozen=True)
class Cluster:
    miembros: tuple          # textos de término, orden alfabético
    etiqueta: str            # mayor df; empate → alfabético


def extraer(texto_limpio: str, lang: "str | None") -> NGramDoc:
    sw = stopwords(lang)
    palabras = _palabras(texto_limpio)
    terminos = frozenset(w for w in palabras if len(w) >= 3 and w not in sw)
    seq = [w for w in palabras if w not in sw]
    big = frozenset(" ".join(seq[k:k + 2]) for k in range(len(seq) - 1))
    tri = frozenset(" ".join(seq[k:k + 3]) for k in range(len(seq) - 2))
    return NGramDoc(terminos=terminos, bigramas=big, trigramas=tri)


def clusterizar(stats: StatsDia) -> list:
    """Los 7 pasos deterministas (plan Lovelace §4.8):
    1. U = {t: df ≥ 3}.  2-3. co-ocurrencia binaria leída de stats.cooc.
    4. Arista si c ≥ 3 y J = c/(df_i+df_j−c) ≥ 0,2.
    5. Componentes conexas por union-find, unión en orden alfabético de aristas
       ordenadas (determinista).  6. Singletons = clúster de 1 miembro.
    7. Etiqueta = mayor df, empate alfabético; salida ordenada por etiqueta.
    """
    u = sorted(t for t, d in stats.df.items() if d >= _DF_MIN)
    uset = set(u)
    # Aristas en orden alfabético (i<j garantizado por contrato de cooc).
    aristas = []
    for (i, j), c in sorted(stats.cooc.items()):
        if i not in uset or j not in uset or c < _C_MIN:
            continue
        if c / (stats.df[i] + stats.df[j] - c) >= _J_MIN:
            aristas.append((i, j))
    aristas.sort()
    padre = {t: t for t in u}

    def raiz(x):
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    for i, j in aristas:
        ri, rj = raiz(i), raiz(j)
        if ri != rj:
            padre[max(ri, rj)] = min(ri, rj)  # unión hacia el menor (estable)
    comp = {}
    for t in u:  # incluye singletons (sin aristas → su propio componente)
        comp.setdefault(raiz(t), []).append(t)
    out = []
    for miembros in comp.values():
        miembros.sort()
        etq = min(miembros, key=lambda t: (-stats.df[t], t))
        out.append(Cluster(miembros=tuple(miembros), etiqueta=etq))
    out.sort(key=lambda c: c.etiqueta)
    return out
