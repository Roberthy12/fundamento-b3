"""Coleta amostras das fontes de dados e grava em amostras/ (uso temporário)."""
import csv, io, json, os, re, urllib.parse, urllib.request, http.cookiejar, zipfile

OUT = "amostras"
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def get(url, data=None, hdr=None, timeout=60):
    req = urllib.request.Request(url, data=data, headers={**UA, **(hdr or {})})
    with op.open(req, timeout=timeout) as r:
        return r.read()


def salvar(nome, conteudo):
    if not isinstance(conteudo, str):
        conteudo = json.dumps(conteudo, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, nome), "w", encoding="utf-8") as f:
        f.write(conteudo)
    print("salvo", nome, len(conteudo))


def tenta(nome, fn):
    try:
        fn()
    except Exception as e:
        print("ERRO", nome, repr(e))
        salvar(nome + ".erro.txt", repr(e))


# ---------------- Yahoo ----------------
try:
    get("https://fc.yahoo.com")
except Exception:
    pass
crumb = get("https://query1.finance.yahoo.com/v1/test/getcrumb").decode()
Q = "&crumb=" + urllib.parse.quote(crumb)


def y_quote():
    r = json.loads(get("https://query1.finance.yahoo.com/v7/finance/quote?symbols=AAPL,VOO,HGLG11.SA,IVVB11.SA,AAPL34.SA,BOVA11.SA,7203.T" + Q))
    salvar("yahoo_quote.json", r)


def y_summary():
    mods = "assetProfile,financialData,defaultKeyStatistics,summaryDetail,price,fundProfile,topHoldings"
    out = {}
    for s in ("AAPL", "HGLG11.SA", "VOO", "PETR4.SA", "SAP.DE"):
        try:
            out[s] = json.loads(get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{s}?modules={mods}" + Q))
        except Exception as e:
            out[s] = repr(e)
    salvar("yahoo_summary.json", out)


def screener(consulta, tipo="EQUITY", size=5, offset=0, sort="intradaymarketcap"):
    corpo = json.dumps({"size": size, "offset": offset, "sortField": sort, "sortType": "DESC",
                        "quoteType": tipo, "query": consulta}).encode()
    return json.loads(get("https://query2.finance.yahoo.com/v1/finance/screener?formatted=false&lang=en-US&region=US" + Q,
                          data=corpo, hdr={"Content-Type": "application/json"}))


def y_screener():
    eq = lambda r: {"operator": "EQ", "operands": ["region", r]}
    out = {"amostra_us": screener(eq("us"), size=3)}
    totais = {}
    for r in ("us", "br", "ca", "gb", "de", "fr", "nl", "ch", "it", "es", "se", "dk", "jp", "hk", "cn", "tw", "kr", "in", "au", "sg", "mx", "ar", "cl"):
        try:
            f = screener(eq(r), size=3)["finance"]["result"][0]
            totais[r] = {"total": f.get("total"), "top": [(q.get("symbol"), q.get("marketCap"), q.get("currency"), q.get("exchange")) for q in f.get("quotes", [])]}
        except Exception as e:
            totais[r] = repr(e)
    out["totais_por_regiao"] = totais
    etf = {}
    for sort in ("fundnetassets", "intradayprice", "dayvolume", "percentchange"):
        for r in ("us", "br"):
            try:
                f = screener(eq(r), tipo="ETF", size=3, sort=sort)["finance"]["result"][0]
                etf[f"{r}/{sort}"] = {"total": f.get("total"), "top": [q.get("symbol") for q in f.get("quotes", [])]}
            except Exception as e:
                etf[f"{r}/{sort}"] = repr(e)
    out["etf"] = etf
    try:
        f = screener(eq("us"), tipo="MUTUALFUND", size=3, sort="fundnetassets")["finance"]["result"][0]
        out["mutualfund_us"] = {"total": f.get("total"), "top": [q.get("symbol") for q in f.get("quotes", [])]}
    except Exception as e:
        out["mutualfund_us"] = repr(e)
    # lote grande no v7: 250 símbolos de uma vez
    try:
        syms = [q["symbol"] for q in screener(eq("us"), size=250)["finance"]["result"][0]["quotes"]]
        r = json.loads(get("https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + ",".join(syms) + Q))
        out["v7_lote_250"] = len(r["quoteResponse"]["result"])
    except Exception as e:
        out["v7_lote_250"] = repr(e)
    salvar("yahoo_screener.json", out)


def y_divs():
    r = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/HGLG11.SA?range=1y&interval=1mo&events=div"))
    salvar("yahoo_divs.json", r)


tenta("yahoo_quote", y_quote)
tenta("yahoo_summary", y_summary)
tenta("yahoo_screener", y_screener)
tenta("yahoo_divs", y_divs)


# ---------------- CVM e Tesouro ----------------
CVM = "https://dados.cvm.gov.br/dados/"


def amostra_zip(nome, url, filtros=(), n=4):
    z = zipfile.ZipFile(io.BytesIO(get(url, timeout=120)))
    txt = []
    for arq in z.namelist():
        linhas = z.read(arq).decode("latin-1").splitlines()
        txt.append(f"### {arq}  ({len(linhas)} linhas)")
        txt.append(linhas[0])
        txt.extend(linhas[1:n + 1])
        for f in filtros:
            achou = [l for l in linhas[1:] if f in l][:3]
            if achou:
                txt.append(f"-- filtro {f}:")
                txt.extend(achou)
    salvar(nome, "\n".join(txt))


def cvm_fii():
    amostra_zip("cvm_fii_mensal.txt", CVM + "FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_2026.zip", ("11.728.688/0001-47", "97.521.225/0001-25"))


def cvm_fii_contagem():
    z = zipfile.ZipFile(io.BytesIO(get(CVM + "FII/DOC/INF_MENSAL/DADOS/inf_mensal_fii_2026.zip", timeout=120)))
    arq = [a for a in z.namelist() if "geral" in a][0]
    rows = list(csv.DictReader(io.StringIO(z.read(arq).decode("latin-1")), delimiter=";"))
    datas = sorted({r["Data_Referencia"] for r in rows})
    ult = [r for r in rows if r["Data_Referencia"] == datas[-1]]
    bolsa = [r for r in rows if r.get("Mercado_Negociacao_Bolsa") == "S"]
    isins = {r["Codigo_ISIN"] for r in bolsa if r["Codigo_ISIN"]}
    seg = {}
    for r in bolsa:
        seg[r["Segmento_Atuacao"]] = seg.get(r["Segmento_Atuacao"], 0) + 1
    salvar("cvm_fii_contagem.json", {"datas": datas, "linhas_ultima_data": len(ult), "isins_bolsa": len(isins),
                                      "exemplos_isin": sorted(isins)[:40], "segmentos": seg,
                                      "tipos": sorted({r["Tipo_Fundo_Classe"] for r in rows})})


def cvm_fundos():
    amostra_zip("cvm_registro_classe.txt", CVM + "FI/CAD/DADOS/registro_fundo_classe.zip")
    amostra_zip("cvm_inf_diario.txt", CVM + "FI/DOC/INF_DIARIO/DADOS/inf_diario_fi_202609.zip")
    linhas = get(CVM + "FI/CAD/DADOS/cad_fi.csv", timeout=120).decode("latin-1").splitlines()
    salvar("cvm_cad_fi.txt", "\n".join([f"{len(linhas)} linhas"] + linhas[:5] + linhas[-3:]))


def cvm_cias():
    amostra_zip("cvm_fca.txt", CVM + "CIA_ABERTA/DOC/FCA/DADOS/fca_cia_aberta_2026.zip", ("PETR", "WEGE"), n=2)
    amostra_zip("cvm_itr.txt", CVM + "CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_2026.zip", ("PETROLEO BRASILEIRO",), n=2)


def cvm_indice():
    html = get(CVM).decode("utf-8", "replace")
    salvar("cvm_indice.txt", "\n".join(sorted(set(re.findall(r'href="([^"?]+/)"', html)))))
    for d in ("FII/DOC/", "FI/DOC/", "FIAGRO/", "FIAGRO/DOC/", "FIDC/DOC/", "FIP/DOC/"):
        try:
            h = get(CVM + d).decode("utf-8", "replace")
            salvar("cvm_indice_" + d.replace("/", "_") + ".txt", "\n".join(sorted(set(re.findall(r'href="([^"?]+)"', h)))))
        except Exception as e:
            salvar("cvm_indice_" + d.replace("/", "_") + ".txt", repr(e))


def tesouro():
    linhas = get("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv",
                 timeout=120).decode("latin-1").splitlines()
    cab = linhas[0]
    rows = [l.split(";") for l in linhas[1:] if l]
    idx = cab.split(";").index("Data Base") if "Data Base" in cab else 2
    def chave(r):
        d = r[idx].split("/")
        return d[2] + d[1] + d[0] if len(d) == 3 else ""
    mx = max(chave(r) for r in rows)
    ult = [";".join(r) for r in rows if chave(r) == mx]
    salvar("tesouro.txt", "\n".join([f"{len(rows)} linhas; data mais recente {mx}", cab] + ult))


for nome, fn in (("cvm_fii", cvm_fii), ("cvm_fii_contagem", cvm_fii_contagem), ("cvm_fundos", cvm_fundos),
                 ("cvm_cias", cvm_cias), ("cvm_indice", cvm_indice), ("tesouro", tesouro)):
    tenta(nome, fn)
