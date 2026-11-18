"""Cotações mensais (com proventos reinvestidos) de FIIs, ETFs, BDRs e outros fundos da B3.

Alimentam o "Rendimento da carteira" do app, que precisa da série de cada ativo desde 2000.
Arquivos: dados/precos_fii.json (FIIs) e dados/precos_b3.json (ETFs, BDRs, Fiagros e FI-Infra),
no formato {ticker: [[AAAA-MM, fechamento ajustado por proventos], ...]}.
O cache guarda cada série por 7 dias; cada execução renova no máximo MAX_PRECOS ativos.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor

from acoes import ANOS_PRECOS, historico_mensal
from comum import Yahoo, ler, log, salvar

MAX_PRECOS = int(os.environ.get("MAX_PRECOS", "700"))
CACHE = "cache_precos_mensais.json"


def linhas(nome):
    j = ler(nome) or {}
    k, d = j.get("k") or [], j.get("d") or []
    return [dict(zip(k, r)) for r in d]


def main():
    fiis = [r["t"] for r in sorted(linhas("fiis.json"), key=lambda r: -(r.get("liq") or 0))]
    b3 = [r["t"] for r in sorted((r for r in linhas("b3.json") if r.get("tipo") in ("ETF", "BDR", "Fiagro", "FI-Infra")),
                                 key=lambda r: -(r.get("liq") or 0))]
    cache = ler(CACHE) or {}
    agora = time.time()
    todos = [t for t in fiis + b3 if t]
    velhos = [t for t in todos if t not in cache or agora - cache[t].get("ts", 0) > 7 * 86400][:MAX_PRECOS]
    y = Yahoo()

    def buscar(t):
        try:
            m = historico_mensal(y, t + ".SA", ANOS_PRECOS)[0]
            cache[t] = {"ts": agora, "m": [[x[0], x[2]] for x in m]}
            return True
        except Exception as ex:
            log(f"  {t}: {ex}")
            return False
    with ThreadPoolExecutor(max_workers=3) as ex:
        ok = sum(ex.map(buscar, velhos))
    log(f"Cotações mensais: {ok} de {len(velhos)} renovadas")
    for t in list(cache):
        if t not in todos:
            del cache[t]
    salvar(CACHE, cache)
    salvar("precos_fii.json", {t: cache[t]["m"] for t in fiis if t in cache and cache[t]["m"]})
    salvar("precos_b3.json", {t: cache[t]["m"] for t in b3 if t in cache and cache[t]["m"]})


if __name__ == "__main__":
    main()
