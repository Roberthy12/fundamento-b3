"""Imóveis dos FIIs (vacância, inadimplência, área) a partir do informe trimestral da CVM.

Grava dados/fiis_imoveis.json: {d: {TICKER: {ref, vac, inad, area, n, im: [[nome, local, area, unid, vac, inad, rec]]}}}.
Uso: python robo/fiis_imoveis.py   (depois de fiis.py). Os nomes das colunas são reconhecidos pelo conteúdo,
porque a CVM já mudou o layout; as colunas achadas ficam registradas em "colunas".
"""
import sys
import unicodedata
from datetime import datetime

from comum import baixar, ler, log, num, salvar, zip_csvs, BRASILIA

CVM = "https://dados.cvm.gov.br/dados/FII/DOC/INF_TRIMESTRAL/DADOS/inf_trimestral_fii_{}.zip"
MAX_IMOVEIS = 25


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn").lower()


def achar(cols, *quer, evitar=()):
    for c in cols:
        n = norm(c)
        if all(q in n for q in quer) and not any(e in n for e in evitar):
            return c
    return None


def main():
    fiis = ler("fiis.json", {}) or {}
    k = fiis.get("k") or []
    if not fiis.get("d") or "cnpj" not in k:
        raise RuntimeError("fiis.json ausente: rode fiis.py antes")
    por_cnpj = {r[k.index("cnpj")]: r[k.index("t")] for r in fiis["d"]}
    ano = datetime.now(BRASILIA).year
    linhas, cols_ref, diag = [], None, {}
    for a in (ano - 1, ano):
        try:
            arquivos = zip_csvs(baixar(CVM.format(a)))
        except Exception as e:
            log(f"CVM trimestral FII {a}: {e}")
            diag[str(a)] = f"erro: {e}"
            continue
        for nome, ls in arquivos.items():
            diag[nome] = {"linhas": len(ls), "colunas": list(ls[0].keys()) if ls else [], "amostra": ls[0] if ls else None}
            if "imovel" not in norm(nome) or not ls:
                continue
            cols = list(ls[0].keys())
            if not achar(cols, "vacanc"):
                continue
            log(f"{nome}: {len(ls)} linhas; colunas: {cols}")
            cols_ref = cols_ref or cols
            linhas += ls
    salvar("fiis_imoveis_diag.json", diag)
    if not linhas:
        raise RuntimeError("informe trimestral sem arquivo de imóveis com vacância")
    cols = list(linhas[0].keys())
    c_cnpj = achar(cols, "cnpj")
    c_data = achar(cols, "data", "ref")
    c_ver = achar(cols, "versao")
    c_nome = achar(cols, "nome", "imovel") or achar(cols, "imovel", evitar=("percent",))
    c_end = achar(cols, "endereco")
    c_area = achar(cols, "area", evitar=("percent",))
    c_uni = achar(cols, "unidade")
    c_vac = achar(cols, "vacanc")
    c_ina = achar(cols, "inadimpl")
    c_rec = achar(cols, "percent", "receita")
    if not (c_cnpj and c_data and c_vac):
        raise RuntimeError(f"colunas não reconhecidas: {cols}")
    # só o trimestre mais recente de cada fundo, na maior versão
    ult = {}
    for l in linhas:
        c, d = l.get(c_cnpj), l.get(c_data)
        if c not in por_cnpj or not d:
            continue
        v = int(l.get(c_ver) or 0) if c_ver else 0
        if c not in ult or (d, v) > ult[c]:
            ult[c] = (d, v)
    grupos = {}
    for l in linhas:
        c = l.get(c_cnpj)
        if c in ult and (l.get(c_data), int(l.get(c_ver) or 0) if c_ver else 0) == ult[c]:
            grupos.setdefault(c, []).append(l)
    out = {}
    for c, ls in grupos.items():
        im = []
        for l in ls:
            im.append([(l.get(c_nome) or "").strip() if c_nome else "", (l.get(c_end) or "").strip() if c_end else "",
                       num(l.get(c_area), 0) if c_area else None, num(l.get(c_uni), 0) if c_uni else None,
                       num(l.get(c_vac), 2), num(l.get(c_ina), 2) if c_ina else None,
                       num(l.get(c_rec), 2) if c_rec else None])
        area = sum(x[2] or 0 for x in im)

        def media(i):
            com = [x for x in im if x[i] is not None]
            if not com:
                return None
            pes = [x[2] or 0 for x in com]
            if sum(pes) > 0:
                return round(sum((x[i] or 0) * p for x, p in zip(com, pes)) / sum(pes), 2)
            return round(sum(x[i] for x in com) / len(com), 2)

        im.sort(key=lambda x: -(x[6] if x[6] is not None else (x[2] or 0) / 1e9))
        out[por_cnpj[c]] = {"ref": ult[c][0], "vac": media(4), "inad": media(5), "area": area or None, "n": len(im),
                            "im": im[:MAX_IMOVEIS]}
    if len(out) < 20:
        raise RuntimeError(f"só {len(out)} FIIs com imóveis")
    salvar("fiis_imoveis.json", {"atualizado": datetime.now(BRASILIA).strftime("%Y-%m-%d"), "fonte": "Informe trimestral da CVM",
                                 "colunas": cols_ref, "i": ["nome", "local", "area", "unid", "vac", "inad", "rec"], "d": out})
    log(f"OK: {len(out)} FIIs com imóveis")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"Imóveis dos FIIs falhou: {e}")
        sys.exit(1)
