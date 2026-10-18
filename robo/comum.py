"""Funções comuns dos coletores: rede, Yahoo Finance, CVM e gravação dos arquivos."""
import csv
import http.cookiejar
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(RAIZ, "dados")
BRASILIA = timezone(timedelta(hours=-3))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def agora():
    return datetime.now(BRASILIA).replace(microsecond=0).isoformat()


def num(v, casas=4):
    """Número arredondado ou None (aceita '1.234,5' e '1234.5')."""
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        v = v.get("raw")
        if v is None:
            return None
    if isinstance(v, str):
        v = v.strip()
        if "," in v:
            v = v.replace(".", "").replace(",", ".")
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return round(x, casas)


def pct(v, casas=2):
    """Fração (0,123) para percentual (12,3)."""
    x = num(v, 8)
    return None if x is None else round(x * 100, casas)


def baixar(url, timeout=120, tentativas=3):
    erro = None
    for i in range(tentativas):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            erro = e
        except Exception as e:
            erro = e
        time.sleep(4 * (i + 1))
    raise RuntimeError(f"{url[:90]} → {erro}")


def texto(b):
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("latin-1")


def csv_linhas(conteudo, sep=";"):
    return list(csv.DictReader(io.StringIO(texto(conteudo)), delimiter=sep))


def zip_csvs(conteudo):
    """{nome_do_arquivo: [linhas como dict]} de um zip da CVM."""
    z = zipfile.ZipFile(io.BytesIO(conteudo))
    return {n: csv_linhas(z.read(n)) for n in z.namelist() if n.lower().endswith(".csv")}


def salvar(nome, dados):
    os.makedirs(DADOS, exist_ok=True)
    caminho = os.path.join(DADOS, nome)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, caminho)
    log(f"gravado dados/{nome} ({os.path.getsize(caminho) // 1024} KB)")


def ler(nome, padrao=None):
    caminho = os.path.join(DADOS, nome) if not os.path.isabs(nome) else nome
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return padrao


def tabela(chaves, linhas, **extra):
    """Formato compacto usado pelo app: {k: [chaves], d: [[valores]]}."""
    return {"atualizado": agora(), **extra, "k": chaves, "d": [[l.get(c) for c in chaves] for l in linhas]}


class Yahoo:
    """Yahoo Finance sem cadastro: cookie + crumb, como o site faz."""

    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.crumb = ""
        self.entrar()

    def _get(self, url, data=None, timeout=30):
        hdr = dict(UA)
        if data is not None:
            hdr["Content-Type"] = "application/json"
        with self.op.open(urllib.request.Request(url, data=data, headers=hdr), timeout=timeout) as r:
            return r.read()

    def entrar(self):
        try:
            self._get("https://fc.yahoo.com")
        except Exception:
            pass  # responde 404, mas deixa o cookie
        self.crumb = self._get("https://query1.finance.yahoo.com/v1/test/getcrumb").decode().strip()

    def json(self, url, data=None, tentativas=4):
        erro = None
        for i in range(tentativas):
            sep = "&" if "?" in url else "?"
            try:
                return json.loads(self._get(url + sep + "crumb=" + urllib.parse.quote(self.crumb), data))
            except urllib.error.HTTPError as e:
                erro = e
                if e.code == 404:
                    raise
                if e.code == 401:
                    try:
                        self.entrar()
                    except Exception:
                        pass
                time.sleep((10 if e.code == 429 else 3) * (i + 1))
            except Exception as e:
                erro = e
                time.sleep(3 * (i + 1))
        raise RuntimeError(f"{url[:90]} → {erro}")

    def cotacoes(self, simbolos, lote=200):
        """{símbolo: cotação} em lotes (endpoint v7/quote)."""
        out, simbolos = {}, list(dict.fromkeys(simbolos))
        for n in range(0, len(simbolos), lote):
            parte = simbolos[n:n + lote]
            try:
                r = self.json("https://query1.finance.yahoo.com/v7/finance/quote?symbols="
                              + urllib.parse.quote(",".join(parte)))
                for q in r["quoteResponse"]["result"]:
                    out[q["symbol"]] = q
            except Exception as e:
                log(f"  cotações {n}-{n + len(parte)} falharam: {e}")
            time.sleep(0.4)
        return out

    def tela(self, consulta, tipo="EQUITY", ordem="intradaymarketcap", maximo=1000):
        """Lista de ativos do screener do Yahoo, do maior para o menor."""
        out, offset = [], 0
        while offset < maximo:
            corpo = json.dumps({"size": min(250, maximo - offset), "offset": offset, "sortField": ordem,
                                "sortType": "DESC", "quoteType": tipo, "query": consulta}).encode()
            r = self.json("https://query2.finance.yahoo.com/v1/finance/screener?formatted=false&lang=en-US&region=US",
                          data=corpo)
            res = r["finance"]["result"][0]
            lote = res.get("quotes") or []
            out.extend(lote)
            offset += len(lote)
            if not lote or offset >= (res.get("total") or 0):
                break
            time.sleep(0.4)
        return out

    def resumo(self, simbolo, modulos):
        r = self.json(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(simbolo)}"
                      f"?modules={modulos}", tentativas=2)
        return r["quoteSummary"]["result"][0]


def eq(campo, valor):
    return {"operator": "EQ", "operands": [campo, valor]}


def gt(campo, valor):
    return {"operator": "GT", "operands": [campo, valor]}


def e(*ops):
    return {"operator": "AND", "operands": list(ops)}


def ou(*ops):
    return {"operator": "OR", "operands": list(ops)}


def mudanca_12m(q):
    v = q.get("fiftyTwoWeekChangePercent")
    return num(v, 2)  # já vem em percentual


def dy_yahoo(q):
    """Dividend yield em % a partir da cotação do Yahoo."""
    moeda, moeda_bal = q.get("currency"), q.get("financialCurrency")
    if moeda and moeda_bal and moeda.upper() != moeda_bal.upper() and q.get("dividendYield") is not None:
        # empresa que publica em outra moeda (ex.: Inter, INTR): o dividendo dos 12 meses vem na moeda
        # do balanço e o preço em dólar, então o yield "trailing" sai errado
        return num(q.get("dividendYield"), 2)
    t = num(q.get("trailingAnnualDividendYield"), 6)
    if t:
        return round(t * 100, 2)
    return num(q.get("dividendYield"), 2)
