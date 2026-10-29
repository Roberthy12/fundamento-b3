"""Séries diárias para o gráfico de investimentos: cotação ajustada (com proventos reinvestidos) de cada
ação e BDR líquido da B3, Ibovespa e CDI diário (Banco Central).

Saída, em dados/diario/:
- <CODIGO>.json -> {"t": [dias desde 1970-01-01], "p": [cotação ajustada]}
- IBOV.json -> o mesmo formato, do Ibovespa
- CDI.json -> {"t": [...], "f": [fator diário, ex.: 1,000535]}
- indice.json -> {"atualizado": ..., "ativos": [códigos com série]}
"""
import json
import os
from datetime import date, datetime, timedelta, timezone

from comum import BRASILIA, DADOS, RAIZ, agora, baixar, ler, log, Yahoo

ANOS = 5
CDI = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={}&dataFinal={}"
PASTA = os.path.join(DADOS, "diario")


def dias(ts):
    return datetime.fromtimestamp(ts + 43200, timezone.utc).date()


def serie_diaria(y, simbolo):
    """Cotação ajustada por dia útil dos últimos ANOS anos; None se o Yahoo não trouxer nada."""
    r = y.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}?range={ANOS}y&interval=1d"
               f"&events=div%7Csplit", tentativas=2)
    res = (r.get("chart") or {}).get("result") or [None]
    res = res[0]
    if not res:
        return None
    ts = res.get("timestamp") or []
    ind = res.get("indicators") or {}
    fech = ((ind.get("quote") or [{}])[0].get("close")) or []
    adj = ((ind.get("adjclose") or [{}])[0].get("adjclose")) or []
    t, p = [], []
    for i, x in enumerate(ts):
        c = fech[i] if i < len(fech) else None
        if not c:
            continue
        a = adj[i] if i < len(adj) and adj[i] else c
        t.append((dias(x) - date(1970, 1, 1)).days)
        p.append(round(a, 4))
    return {"t": t, "p": p} if t else None


def cdi_diario():
    """Fator diário do CDI (1 + taxa do dia), dos últimos ANOS anos."""
    fim = datetime.now(BRASILIA).date()
    ini = date(fim.year - ANOS, fim.month, fim.day)
    j = json.loads(baixar(CDI.format(ini.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")), timeout=120))
    t, f = [], []
    for x in j:
        d, m, a = x["data"].split("/")
        t.append((date(int(a), int(m), int(d)) - date(1970, 1, 1)).days)
        f.append(round(1 + float(x["valor"]) / 100, 8))
    return {"t": t, "f": f}


def main():
    os.makedirs(PASTA, exist_ok=True)
    y = Yahoo()
    b3 = ler("b3.json", {}) or {}
    kb = b3.get("k") or []
    acoes = ler(os.path.join(RAIZ, "acoes.json"), {}) or {}
    ka = acoes.get("k") or []
    codigos = [dict(zip(ka, l)).get("t") for l in acoes.get("d") or []]
    for l in b3.get("d") or []:
        r = dict(zip(kb, l))
        if r.get("tipo") == "BDR" and (r.get("liq") or 0) >= 1e6 and r.get("t"):
            codigos.append(r["t"])
    codigos = [c for c in dict.fromkeys(codigos) if c]
    log(f"diário: {len(codigos)} códigos da B3")
    ativos, falhas = [], 0
    for c in codigos:
        try:
            s = serie_diaria(y, c + ".SA")
        except Exception as ex:
            falhas += 1
            log(f"  {c}: {ex}")
            continue
        if s:
            with open(os.path.join(PASTA, c + ".json"), "w", encoding="utf-8") as fh:
                json.dump(s, fh, separators=(",", ":"))
            ativos.append(c)
    log(f"  {len(ativos)} códigos com série diária; {falhas} falhas")
    try:
        s = serie_diaria(y, "%5EBVSP")
        if s:
            with open(os.path.join(PASTA, "IBOV.json"), "w", encoding="utf-8") as fh:
                json.dump(s, fh, separators=(",", ":"))
            ativos.append("IBOV")
    except Exception as ex:
        log(f"  IBOV: {ex}")
    try:
        with open(os.path.join(PASTA, "CDI.json"), "w", encoding="utf-8") as fh:
            json.dump(cdi_diario(), fh, separators=(",", ":"))
        ativos.append("CDI")
    except Exception as ex:
        log(f"  CDI diário: {ex}")
    with open(os.path.join(PASTA, "indice.json"), "w", encoding="utf-8") as fh:
        json.dump({"atualizado": agora(), "ativos": ativos}, fh, separators=(",", ":"))


if __name__ == "__main__":
    main()
