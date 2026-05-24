#!/usr/bin/env python3
"""Gerador MVP do Boletim Orion.
Usa Yahoo Finance Chart API pública, sem chave, para preencher o template HTML.
Quando um dado não estiver disponível, marca como N/D e mantém o boletim utilizável.
"""
from __future__ import annotations
import json, re, sys, time, urllib.parse, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "boletim-orion-template.html"
OUTDIR = ROOT / "dist"

SYMBOLS = {
    # Asia
    "NIKKEI": "^N225", "HANGSENG": "^HSI", "SHANGHAI": "000001.SS", "CSI300": "000300.SS", "KOSPI": "^KS11", "ASX200": "^AXJO",
    # Europe
    "STOXX50": "^STOXX50E", "DAX": "^GDAXI", "CAC40": "^FCHI", "FTSE100": "^FTSE", "IBEX35": "^IBEX",
    # US futures/risk
    "SP500F": "ES=F", "NASDAQF": "NQ=F", "DOWF": "YM=F", "RUSSELLF": "RTY=F", "VIX": "^VIX",
    # Commodities/FX/rates
    "BRENT": "BZ=F", "WTI": "CL=F", "MINERIO": "TIO=F", "OURO": "GC=F", "COBRE": "HG=F", "DXY": "DX-Y.NYB", "US10Y": "^TNX", "US2Y": "^IRX",
    # Brazil
    "IBOV": "^BVSP", "USDBRL": "BRL=X", "IFIX": "IFIX.SA",
}


def yahoo_quote(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=5d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        data = json.loads(r.read().decode())
    result = data.get("chart", {}).get("result") or []
    if not result:
        raise RuntimeError(f"sem resultado para {symbol}")
    res = result[0]
    meta = res.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None:
        closes = [x for x in res.get("indicators", {}).get("quote", [{}])[0].get("close", []) if x is not None]
        price = closes[-1] if closes else None
        prev = closes[-2] if len(closes) > 1 else prev
    var = None
    if price is not None and prev:
        var = (price / prev - 1) * 100
    return {"symbol": symbol, "price": price, "var": var}


def fmt_num(x, digits=2):
    if x is None: return "N/D"
    if abs(x) >= 1000:
        return f"{x:,.0f}".replace(",", ".")
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(x):
    if x is None: return "N/D"
    sign = "+" if x >= 0 else ""
    return (sign + f"{x:.2f}%").replace(".", ",")


def cls(x):
    if x is None or abs(x) < 0.10: return "neu"
    return "pos" if x > 0 else "neg"


def status_from(vals):
    nums = [v for v in vals if v is not None]
    if not nums: return "N/D", "neu"
    avg = sum(nums)/len(nums)
    if avg > 0.20: return "Positiva", "pos"
    if avg < -0.20: return "Negativa", "neg"
    return "Mista/estável", "neu"


def main():
    quotes = {}
    for key, sym in SYMBOLS.items():
        try:
            quotes[key] = yahoo_quote(sym)
        except Exception as e:
            quotes[key] = {"symbol": sym, "price": None, "var": None, "error": str(e)}
        time.sleep(0.15)

    brt = datetime.now(ZoneInfo("America/Sao_Paulo"))
    vals = {
        "DATA": brt.strftime("%d/%m/%Y"),
        "HORARIO_ATUALIZACAO": brt.strftime("%H:%M BRT"),
        "EVENTO_CHAVE": "Consultar agenda macro do dia",
        "AGENDA_1_HORA": "--", "AGENDA_1_REGIAO": "Global", "AGENDA_1_EVENTO": "Agenda macro a integrar", "AGENDA_1_IMPACTO": "Alto",
        "AGENDA_2_HORA": "--", "AGENDA_2_REGIAO": "Brasil", "AGENDA_2_EVENTO": "BC/B3/IBGE conforme calendário", "AGENDA_2_IMPACTO": "Médio",
        "AGENDA_3_HORA": "--", "AGENDA_3_REGIAO": "EUA", "AGENDA_3_EVENTO": "Dados e falas do Fed", "AGENDA_3_IMPACTO": "Baixo",
    }

    asia_status, asia_cls = status_from([quotes[k]["var"] for k in ["NIKKEI","HANGSENG","SHANGHAI","CSI300","KOSPI","ASX200"]])
    eur_status, eur_cls = status_from([quotes[k]["var"] for k in ["STOXX50","DAX","CAC40","FTSE100","IBEX35"]])
    usa_status, usa_cls = status_from([quotes[k]["var"] for k in ["SP500F","NASDAQF","DOWF","RUSSELLF"]])
    vals.update({"ASIA_STATUS": asia_status, "ASIA_CLASSE": asia_cls, "EUROPA_STATUS": eur_status, "EUROPA_CLASSE": eur_cls, "EUA_STATUS": usa_status, "EUA_CLASSE": usa_cls})

    # Fill quote placeholders
    for k, q in quotes.items():
        vals[k] = fmt_num(q["price"])
        vals[f"{k}_VAR"] = fmt_pct(q["var"])
        vals[f"{k}_CLASSE"] = cls(q["var"])

    vals["BRENT"] = f'{fmt_num(quotes["BRENT"]["price"])} ({fmt_pct(quotes["BRENT"]["var"])})'
    vals["MINERIO"] = f'{fmt_num(quotes["MINERIO"]["price"])} ({fmt_pct(quotes["MINERIO"]["var"])})'
    vals["OURO"] = f'{fmt_num(quotes["OURO"]["price"])} ({fmt_pct(quotes["OURO"]["var"])})'
    vals["COBRE"] = f'{fmt_num(quotes["COBRE"]["price"])} ({fmt_pct(quotes["COBRE"]["var"])})'
    vals["DXY"] = f'{fmt_num(quotes["DXY"]["price"])} ({fmt_pct(quotes["DXY"]["var"])})'
    vals["US10Y"] = fmt_num(quotes["US10Y"]["price"] / 10 if quotes["US10Y"]["price"] else None) + "%"
    vals["US2Y"] = fmt_num(quotes["US2Y"]["price"] / 10 if quotes["US2Y"]["price"] else None) + "%"
    vals["IFIX_BR"] = vals.get("IFIX", "N/D")
    vals["IBOV"] = f'Fechou/último em {vals.get("IBOV", "N/D")} pts'
    vals["USDBRL"] = f'R$ {vals.get("USDBRL", "N/D")}'

    brent_var = quotes["BRENT"]["var"]
    iron_var = quotes["MINERIO"]["var"]
    dxy_var = quotes["DXY"]["var"]
    us10_var = quotes["US10Y"]["var"]
    risk_score = sum(1 if c=="pos" else -1 if c=="neg" else 0 for c in [asia_cls, eur_cls, usa_cls])
    tom = "Positivo" if risk_score >= 2 else "Negativo" if risk_score <= -2 else "Cauteloso"
    badge_cls = "positive" if tom=="Positivo" else "negative" if tom=="Negativo" else "neutral"
    vals["DRIVER_PRINCIPAL"] = "Exterior, DXY/Treasuries e commodities"
    vals["VIES_IBOV"] = "Positivo" if risk_score>0 else "Negativo" if risk_score<0 else "Neutro"
    vals["VIES_DOLAR"] = "Alta" if (dxy_var or 0)>0.15 else "Baixa" if (dxy_var or 0)<-0.15 else "Lateral"
    vals["VIX_STATUS"] = "Pressionado" if (quotes["VIX"]["var"] or 0)>2 else "Calmo/estável"
    vals["VIX_CLASSE"] = "neg" if (quotes["VIX"]["var"] or 0)>2 else "neu"
    vals["RESUMO_EXECUTIVO"] = f"Mercados globais abrem com tom {tom.lower()}. Ásia: {asia_status}; Europa: {eur_status}; futuros dos EUA: {usa_status}. O foco inicial está em DXY, Treasuries e commodities, que podem direcionar Ibovespa, dólar e curva de juros local."
    vals["LEITURA_OPERACIONAL"] = "Começar seletivo, priorizando estruturas com risco definido em opções e evitando concentração antes de eventos macro relevantes."
    vals["IMPACTO_IBOV"] = "Depende do exterior e das commodities"
    vals["IMPACTO_DOLAR"] = "DXY/Treasuries são o principal driver"
    vals["DI"] = "N/D via Yahoo; integrar fonte B3/ANBIMA"
    vals["IMPACTO_DI"] = "Impacta FIIs, varejo e construtoras"
    vals["IMPACTO_IFIX"] = "Sensível à curva longa de juros"
    vals["RADAR_PETR4"] = "Viés favorecido pelo Brent" if (brent_var or 0)>0 else "Cautela se Brent pressionado"
    vals["RADAR_VALE3"] = "Viés favorecido pelo minério" if (iron_var or 0)>0 else "Cautela com minério/China"
    vals["RADAR_ITUB4"] = "Observar curva de juros e apetite por risco local"
    vals["RADAR_BOVA11"] = "Proxy do humor global e fluxo para Brasil"
    vals["RADAR_BBAS3"] = "Sensível a bancos, fiscal e risco político"
    vals["RADAR_ABEV3"] = "Perfil defensivo; observar dólar e consumo"
    vals["RADAR_WEGE3"] = "Sensível a juros globais e dólar"
    vals["RADAR_OPCOES"] = "Atenção a PETR4, VALE3 e BOVA11, pois commodities e exterior podem elevar volatilidade intradiária."
    vals["VOL_STATUS"] = "Moderada"
    vals["VOL_CLASSE"] = "neu"
    vals["OPCOES_ATIVOS"] = "PETR4, VALE3, BOVA11, ITUB4"
    vals["EVENTO_BINARIO"] = "Agenda macro do dia"
    vals["CONCLUSAO_OPERACIONAL"] = "O boletim indica leitura inicial baseada em dados públicos. Usar como mapa de cenário, não como recomendação. Reavaliar após abertura local e principais dados do dia."

    html = TEMPLATE.read_text()
    html = re.sub(r'<span class="badge neutral">● Tom do mercado: Cauteloso</span>', f'<span class="badge {badge_cls}">● Tom do mercado: {tom}</span>', html)
    for k, v in vals.items():
        html = html.replace('{{'+k+'}}', str(v))
    html = re.sub(r'{{[^}]+}}', 'N/D', html)
    OUTDIR.mkdir(exist_ok=True)
    out = OUTDIR / f"boletim-orion-{brt.strftime('%Y-%m-%d')}.html"
    out.write_text(html)
    latest = OUTDIR / "boletim-orion-latest.html"
    latest.write_text(html)
    print(out)

if __name__ == "__main__":
    main()
