"""Tesouro Direto: taxas e preços do dia e histórico semanal de 1 ano (Tesouro Transparente).

Grava dados/tesouro.json.
"""
import sys
from datetime import date, timedelta

from comum import baixar, log, num, salvar, tabela, texto

URL = ("https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/"
       "resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv")
CHAVES = ["titulo", "venc", "tipo", "indexador", "taxa_c", "taxa_v", "pu_c", "pu_v", "hist"]


def iso(d):
    p = d.split("/")
    return f"{p[2]}-{p[1]}-{p[0]}" if len(p) == 3 else d


def tipo_de(nome):
    n = nome.lower()
    if "selic" in n:
        return "Tesouro Selic", "Selic"
    if "renda+" in n or "renda +" in n:
        return "Tesouro Renda+", "IPCA"
    if "educa" in n:
        return "Tesouro Educa+", "IPCA"
    if "igp" in n:
        return "Tesouro IGP-M+", "IGP-M"
    if "ipca" in n:
        return ("Tesouro IPCA+ com juros semestrais" if "semestra" in n else "Tesouro IPCA+"), "IPCA"
    if "prefixado" in n:
        return ("Tesouro Prefixado com juros semestrais" if "semestra" in n else "Tesouro Prefixado"), "Prefixado"
    return nome, ""


def main():
    linhas = texto(baixar(URL, timeout=180)).splitlines()
    cab = [c.strip() for c in linhas[0].split(";")]
    idx = {c: i for i, c in enumerate(cab)}
    rows = []
    for l in linhas[1:]:
        p = l.split(";")
        if len(p) < len(cab):
            continue
        rows.append({"titulo": p[idx["Tipo Titulo"]].strip(), "venc": iso(p[idx["Data Vencimento"]]),
                     "data": iso(p[idx["Data Base"]]), "taxa_c": num(p[idx["Taxa Compra Manha"]]),
                     "taxa_v": num(p[idx["Taxa Venda Manha"]]), "pu_c": num(p[idx["PU Compra Manha"]], 2),
                     "pu_v": num(p[idx["PU Venda Manha"]], 2)})
    ultima = max(r["data"] for r in rows)
    inicio = (date.fromisoformat(ultima) - timedelta(days=366)).isoformat()
    hist = {}
    for r in rows:
        if r["data"] >= inicio:
            hist.setdefault((r["titulo"], r["venc"]), []).append((r["data"], r["taxa_v"] or r["taxa_c"]))
    hoje = [r for r in rows if r["data"] == ultima and r["venc"] > ultima]
    out = []
    for r in hoje:
        serie = sorted(hist.get((r["titulo"], r["venc"]), []))
        semanal, ult_semana = [], None
        for d, t in serie:
            semana = date.fromisoformat(d).isocalendar()[:2]
            if semana != ult_semana and t is not None:
                semanal.append([d, t])
                ult_semana = semana
            elif t is not None and semanal:
                semanal[-1] = [d, t]
        tipo, indexador = tipo_de(r["titulo"])
        out.append({**r, "tipo": tipo, "indexador": indexador, "hist": semanal,
                    "pu_c": r["pu_c"] if r["pu_c"] else None, "taxa_c": r["taxa_c"] if r["pu_c"] else None})
    out.sort(key=lambda r: (r["tipo"], r["venc"]))
    if len(out) < 10:
        raise RuntimeError(f"só {len(out)} títulos em {ultima}")
    salvar("tesouro.json", tabela(CHAVES, out, fonte="Tesouro Transparente (preços e taxas do Tesouro Direto)",
                                  data_base=ultima))
    log(f"OK: {len(out)} títulos do Tesouro de {ultima}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"Tesouro falhou: {e}")
        sys.exit(1)
