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
    "BRENT": "BZ=F", "WTI": "CL=F", "MINERIO": "TIO=F", "OURO": "GC=F", "COBRE": "HG=F", "DXY": "DX-Y.NYB", "US10Y": "^TNX", "US2Y": "2YY=F",
    # Brazil
    "IBOV": "^BVSP", "USDBRL": "BRL=X", "IFIX": "IFIX.SA", "BPAC11": "BPAC11.SA",
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


def direction_text(x, up="alta", down="queda", flat="estabilidade"):
    if x is None:
        return "sem dado confiável"
    if x > 0.20:
        return up
    if x < -0.20:
        return down
    return flat


def build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score):
    """Camada analítica estilo mesa de gestão.
    Importante: ainda é uma interpretação determinística, não recomendação.
    """
    def v(k): return quotes.get(k, {}).get("var")
    brent, iron, dxy, vix, spx, ndx, us10 = v("BRENT"), v("MINERIO"), v("DXY"), v("VIX"), v("SP500F"), v("NASDAQF"), v("US10Y")
    ibov, usdbrl, ifix = v("IBOV"), v("USDBRL"), v("IFIX")

    risk_label = "risk-on" if risk_score >= 2 else "risk-off" if risk_score <= -2 else "neutro/cauteloso"
    macro = (
        f"O pano de fundo global está {risk_label}. Ásia veio {asia_status.lower()}, Europa {eur_status.lower()} e futuros dos EUA {usa_status.lower()}. "
        f"S&P futuro mostra {direction_text(spx, 'tração positiva', 'pressão vendedora', 'estabilidade')} e Nasdaq {direction_text(ndx, 'apetite por tecnologia', 'realização em tecnologia', 'sem direção forte')}. "
    )
    if dxy is not None:
        macro += "DXY em alta reduz espaço para emergentes e costuma pressionar dólar/juros locais. " if dxy > 0.15 else "DXY mais fraco ajuda o fluxo para emergentes. " if dxy < -0.15 else "DXY está sem direção forte, deixando o Brasil mais dependente de commodities e fluxo local. "
    if us10 is not None:
        macro += "Treasuries mais pressionados exigem cautela com ativos de duration longa. " if us10 > 0.5 else "Treasuries mais leves favorecem duration e bolsa. " if us10 < -0.5 else "Treasuries não mostram estresse relevante no início do dia. "
    if vix is not None and vix > 2:
        macro += "VIX em alta recomenda reduzir alavancagem intradiária."

    commodities = ""
    commodities += "Brent em alta favorece leitura inicial para PETR4/PRIO3 e pode dar suporte ao Ibovespa via petróleo. " if (brent or 0) > 0.2 else "Brent em queda tira suporte de petróleo e pede cautela com PETR4/PRIO3. " if (brent or 0) < -0.2 else "Brent está estável, sem grande impulso direcional para petróleo. "
    commodities += "Minério em alta melhora o viés para VALE3 e siderúrgicas. " if (iron or 0) > 0.2 else "Minério em queda deixa VALE3 e siderúrgicas vulneráveis, especialmente se China também estiver fraca. " if (iron or 0) < -0.2 else "Minério está sem direção forte; acompanhar China e ADRs de mineração. "
    commodities += "Para Brasil, a combinação petróleo/minério define boa parte do beta de abertura; divergência entre eles favorece seletividade em vez de compra ampla de índice."

    brasil = (
        "No Brasil, a leitura inicial deve combinar exterior, dólar e curva. "
        + ("USD/BRL pressionado reforça cautela com bolsa e FIIs. " if (usdbrl or 0) > 0.2 else "USD/BRL mais comportado ajuda ativos locais. " if (usdbrl or 0) < -0.2 else "USD/BRL está sem sinal forte. ")
        + "DI futuro ainda não está integrado no MVP; portanto a leitura de FIIs deve ser tratada com ressalva. "
        + ("IFIX positivo sugere algum alívio na margem para fundos imobiliários. " if (ifix or 0) > 0.1 else "IFIX fraco/pressionado reforça atenção à curva longa e fundos high yield. " if (ifix or 0) < -0.1 else "IFIX sem grande sinal; aguardar abertura e curva de juros. ")
        + "Bancos tendem a ser o termômetro do risco local; varejo, construtoras e FIIs dependem muito do movimento dos juros."
    )

    vol_score = 0
    for x in [brent, iron, dxy, spx, ndx, vix]:
        if x is not None and abs(x) > 0.5: vol_score += 1
    vol_label = "elevada" if vol_score >= 3 or ((vix or 0) > 2) else "moderada" if vol_score >= 1 else "baixa/moderada"
    opcoes = (
        f"Volatilidade esperada {vol_label}. PETR4 merece atenção pelo Brent; VALE3 pelo minério/China; BOVA11 pelo conjunto exterior + juros + dólar. "
        "Sem agenda econômica real integrada, tratar eventos macro como risco não mapeado no boletim. "
        "Para abertura, estruturas com risco definido tendem a ser mais adequadas que venda descoberta de volatilidade quando houver dado macro relevante ou VIX subindo."
    )

    if risk_score > 0 and not ((dxy or 0) > 0.3 or (vix or 0) > 2):
        gestor = "Postura construtiva, mas seletiva: favorecer ativos alinhados aos drivers positivos do dia e evitar perseguir preço em gap de abertura."
    elif risk_score < 0 or ((dxy or 0) > 0.3 and (vix or 0) > 1):
        gestor = "Postura defensiva: reduzir tamanho, priorizar liquidez, aguardar confirmação da abertura e evitar estruturas vendidas em volatilidade sem proteção."
    else:
        gestor = "Postura de observação ativa: cenário sem assimetria clara. Aguardar abertura, fluxo estrangeiro e confirmação em dólar/juros antes de aumentar risco."
    return macro, commodities, brasil, opcoes, gestor, vol_label


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
    vals["US10Y"] = fmt_num(quotes["US10Y"]["price"] if quotes["US10Y"]["price"] else None) + "%"
    vals["US2Y"] = fmt_num(quotes["US2Y"]["price"] if quotes["US2Y"]["price"] else None) + "%"
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
    vals["RADAR_BPAC11"] = f"{fmt_num(quotes['BPAC11']['price'])} ({fmt_pct(quotes['BPAC11']['var'])}) — sensível a juros, mercado de capitais, fluxo para bancos e apetite por risco Brasil"
    macro, commodities, brasil_fiis, opcoes, gestor, vol_label = build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score)
    vals["ANALISE_MACRO_GLOBAL"] = macro
    vals["ANALISE_COMMODITIES"] = commodities
    vals["ANALISE_BRASIL_FIIS"] = brasil_fiis
    vals["ANALISE_OPCOES"] = opcoes
    vals["ANALISE_GESTOR"] = gestor
    vals["RADAR_OPCOES"] = opcoes
    vals["VOL_STATUS"] = vol_label.capitalize()
    vals["VOL_CLASSE"] = "neg" if vol_label == "elevada" else "neu"
    vals["OPCOES_ATIVOS"] = "PETR4, VALE3, BOVA11, ITUB4"
    vals["EVENTO_BINARIO"] = "Agenda macro do dia"
    vals["CONCLUSAO_OPERACIONAL"] = gestor + " O boletim indica leitura inicial baseada em dados públicos e modelos determinísticos; usar como mapa de cenário, não como recomendação. Reavaliar após abertura local e principais dados do dia."

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
