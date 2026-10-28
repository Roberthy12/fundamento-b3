"""Composição dos índices da B3 (Ibovespa, IBrX 100, IDIV, Small Cap...) por código de negociação.

Fonte: portal de listados da B3 (carteira do dia de cada índice). Saída: dados/indices.json ->
{"atualizado": ..., "indices": {"IBOV": {"nome": "Ibovespa", "n": 76}, ...},
 "por_codigo": {"PETR4": ["IBOV", "IBRX", ...], ...}}
"""
import base64
import json

from comum import agora, baixar, log, salvar

URL = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/{}"

# índice -> nome para o app
INDICES = {
    "IBOV": "Ibovespa", "IBXX": "IBrX 100", "IVBX": "IVBX-2", "IDIV": "Dividendos", "SMLL": "Small Cap",
    "MLCX": "MidLarge Cap", "ICON": "Consumo", "IFNC": "Financeiro", "IMAT": "Materiais Básicos",
    "UTIL": "Utilidade Pública", "IEEX": "Energia Elétrica", "ITAG": "Tag Along", "IGCT": "Governança Corporativa Trace",
    "IGCX": "Governança Corporativa IGC", "ISEE": "Sustentabilidade Empresarial",
}


def carteira(indice):
    """Códigos de negociação de um índice (todas as páginas)."""
    codigos, pagina = [], 1
    while True:
        payload = {"index": indice, "language": "pt-BR", "pageNumber": pagina, "pageSize": 200}
        dados = json.loads(baixar(URL.format(base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()), timeout=60))
        codigos += [r.get("cod") for r in dados.get("results") or [] if r.get("cod")]
        total = (dados.get("page") or {}).get("totalPages") or 1
        if pagina >= total:
            return codigos
        pagina += 1


def main():
    indices, por_codigo = {}, {}
    for sigla, nome in INDICES.items():
        try:
            cods = carteira(sigla)
        except Exception as ex:
            log(f"  índice {sigla}: {ex}")
            continue
        indices[sigla] = {"nome": nome, "n": len(cods)}
        for c in cods:
            por_codigo.setdefault(c, []).append(sigla)
        log(f"  {sigla}: {len(cods)} ativos")
    log(f"índices: {len(indices)} de {len(INDICES)}; {len(por_codigo)} códigos com pelo menos um índice")
    if indices:
        salvar("indices.json", {"atualizado": agora(), "indices": indices, "por_codigo": por_codigo})


if __name__ == "__main__":
    main()
