"""Cotações mensais (com proventos reinvestidos) de FIIs, ETFs, BDRs, ações e ETFs do exterior.

Alimentam o "Rendimento da carteira" e o comparador de ativos do app, que precisam da série de cada ativo.
Arquivos em dados/: precos_fii.json, precos_b3.json (ETFs, BDRs, Fiagros e FI-Infra), precos_ext.json
(maiores ações dos EUA) e precos_etfx.json (ETFs dos EUA), no formato {ticker: [[AAAA-MM, fechamento ajustado], ...]}.
O cache guarda cada série por 7 dias; cada execução renova no máximo MAX_PRECOS ativos.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from acoes import ANOS_PRECOS, historico_mensal
from comum import Yahoo, ler, log, salvar

MAX_PRECOS = int(os.environ.get("MAX_PRECOS", "900"))
CACHE = "cache_precos_mensais.json"
N_EXT = 600  # ações dos EUA com maior valor de mercado


def linhas(nome):
    j = ler(nome) or {}
    k, d = j.get("k") or [], j.get("d") or []
    return [dict(zip(k, r)) for r in d]


def main():
    por_liq = lambda rs: sorted(rs, key=lambda r: -(r.get("liq") or 0))
    grupos = {
        "precos_fii": [(r["t"], r["t"] + ".SA") for r in por_liq(linhas("fiis.json"))],
        "precos_b3": [(r["t"], r["t"] + ".SA") for r in por_liq(r for r in linhas("b3.json") if r.get("tipo") in ("ETF", "BDR", "Fiagro", "FI-Infra"))],
        "precos_ext": [(r["t"], r["t"]) for r in sorted((r for r in linhas("exterior.json") if r.get("cur") == "USD" and r.get("mkt") == "EUA" and "." not in r["t"]),
                                                         key=lambda r: -(r.get("mcap") or 0))[:N_EXT]],
        "precos_etfx": [(r["t"], r["t"]) for r in por_liq(linhas("etfs_exterior.json")) if "." not in r["t"]],
    }
    cache = ler(CACHE) or {}
    agora = time.time()
    simbolos = [s for g in grupos.values() for _, s in g if s]
    precisa = [s for s in dict.fromkeys(simbolos) if s not in cache or agora - cache[s].get("ts", 0) > 7 * 86400][:MAX_PRECOS]
    y = Yahoo()

    def buscar(s):
        try:
            m = historico_mensal(y, s, ANOS_PRECOS)[0]
            cache[s] = {"ts": agora, "m": [[x[0], x[2]] for x in m]}
            return True
        except Exception as ex:
            log(f"  {s}: {ex}")
            return False
    with ThreadPoolExecutor(max_workers=3) as ex:
        ok = sum(ex.map(buscar, precisa))
    log(f"Cotações mensais: {ok} de {len(precisa)} renovadas")
    validos = set(simbolos)
    for s in list(cache):
        if s not in validos:
            del cache[s]
    salvar(CACHE, cache)
    for arq, g in grupos.items():
        salvar(arq + ".json", {t: cache[s]["m"] for t, s in g if s in cache and cache[s]["m"]})


if __name__ == "__main__":
    main()
