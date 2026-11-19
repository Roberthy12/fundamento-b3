"""Criptomoedas: cotação, variações e histórico (Yahoo Finance, em dólares).

Gera dados/cripto.json (lista no formato compacto do app) e dados/cripto_hist.json
({símbolo: {"m": [[AAAA-MM, fechamento]...] desde o início, "d": [[AAAA-MM-DD, fechamento]...] do último ano}}).
"""
import time
from datetime import datetime, timedelta, timezone

from comum import Yahoo, agora, log, salvar, tabela

# principais moedas por valor de mercado; as que o Yahoo não tiver são ignoradas
MOEDAS = ["BTC", "ETH", "USDT", "XRP", "BNB", "SOL", "USDC", "TRX", "DOGE", "ADA", "LINK", "AVAX", "XLM", "BCH", "SUI",
          "HBAR", "LTC", "TON", "DOT", "XMR", "UNI", "AAVE", "SHIB", "ETC", "ATOM", "NEAR", "APT", "ICP", "FIL", "ARB",
          "OP", "ALGO", "VET", "INJ", "PEPE", "POL", "MKR", "RENDER", "FET", "ENA", "CRO", "KAS", "STX", "IMX", "GRT",
          "THETA", "SAND", "MANA", "AXS", "CHZ", "TAO", "WLD", "JUP", "SEI", "LDO", "QNT", "FLOW", "EGLD", "XTZ", "EOS",
          "BONK", "TIA", "RUNE", "GALA", "DYDX", "CRV", "COMP", "SNX", "ZEC", "DASH", "NEO", "IOTA", "KAVA", "ONDO"]

# moedas cujo símbolo "XXX-USD" no Yahoo é de outra moeda: usa o código numérico próprio delas
ALT = {"SUI": "SUI20947", "UNI": "UNI7083", "APT": "APT21794", "PEPE": "PEPE24478", "POL": "POL28321", "STX": "STX4847",
       "IMX": "IMX10603", "GRT": "GRT6719", "TAO": "TAO22974", "COMP": "COMP5692"}


def serie(y, simbolo, periodo, intervalo):
    simbolo = ALT.get(simbolo, simbolo)
    r = y.json(f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}-USD?range={periodo}&interval={intervalo}", tentativas=3)
    res = r["chart"]["result"][0]
    ts = res.get("timestamp") or []
    fech = ((res.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    pts = []
    for i, t in enumerate(ts):
        c = fech[i] if i < len(fech) else None
        if c:
            pts.append((datetime.fromtimestamp(t + 43200, timezone.utc), float(c)))
    return pts, res.get("meta") or {}


def main():
    y = Yahoo()
    cot = y.cotacoes([ALT.get(m, m) + "-USD" for m in MOEDAS])
    linhas, hist = [], {}
    for rank, m in enumerate(MOEDAS, 1):
        try:
            mensal, _ = serie(y, m, "max", "1mo")
            diario, meta = serie(y, m, "1y", "1d")
        except Exception as ex:
            log(f"  {m}: {ex}")
            continue
        if len(diario) < 30 or len(mensal) < 2:
            continue
        # o candle mensal mais recente é o mês em curso: usa o último fechamento diário
        meses = {d.strftime("%Y-%m"): round(c, 8) for d, c in mensal}
        meses[diario[-1][0].strftime("%Y-%m")] = round(diario[-1][1], 8)
        m_l = [[k, v] for k, v in sorted(meses.items())]
        d_l = [[d.strftime("%Y-%m-%d"), round(c, 8)] for d, c in diario]
        hist[m] = {"m": m_l, "d": d_l}
        preco = diario[-1][1]
        q = cot.get(ALT.get(m, m) + "-USD") or {}

        def var(dias):
            alvo = diario[-1][0] - timedelta(days=dias)
            ant = [c for d, c in diario if d <= alvo]
            return round((preco / ant[-1] - 1) * 100, 2) if ant else None
        ano0 = [c for d, c in diario if d.year < diario[-1][0].year]
        fechs = [c for _, c in diario]
        topo = max(v for _, v in m_l)
        nome = (q.get("longName") or q.get("shortName") or meta.get("longName") or m).replace(" USD", "").strip()
        linhas.append({
            "t": m, "n": nome, "price": round(preco, 8), "mcap": q.get("marketCap"), "vol": q.get("volume24Hr") or q.get("regularMarketVolume"),
            "sup": q.get("circulatingSupply"), "v1d": var(1), "v7d": var(7), "v30d": var(30), "v90d": var(90),
            "ytd": round((preco / ano0[-1] - 1) * 100, 2) if ano0 else None, "var12": var(365),
            "max52": round(max(fechs), 8), "min52": round(min(fechs), 8), "ath": round(topo, 8),
            "dath": round((preco / topo - 1) * 100, 1), "ini": m_l[0][0], "rank": rank,
        })
        time.sleep(0.3)
    if not linhas:
        raise SystemExit("nenhuma criptomoeda coletada")
    linhas.sort(key=lambda r: (-(r["mcap"] or 0), r["rank"]))
    chaves = ["t", "n", "price", "mcap", "vol", "sup", "v1d", "v7d", "v30d", "v90d", "ytd", "var12", "max52", "min52", "ath", "dath", "ini", "rank"]
    salvar("cripto.json", tabela(chaves, linhas, fonte="Yahoo Finance"))
    salvar("cripto_hist.json", hist)
    log(f"Criptomoedas: {len(linhas)} de {len(MOEDAS)}")


if __name__ == "__main__":
    main()
