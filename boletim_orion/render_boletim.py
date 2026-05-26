#!/usr/bin/env python3
"""Gerador do Boletim Orion.

Sem dependências externas: coleta cotações via Yahoo Finance Chart API pública,
valida anomalias por classe de ativo, renderiza HTML e gera resumo para Telegram.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "boletim-orion-template.html"
OUTDIR = ROOT / "dist"
DATA_DIR = ROOT / "data"
PAGES_URL = "https://antoniojebrael.github.io/boletim-orion/boletim-orion-latest.html"

SYMBOLS = {
    # Asia
    "NIKKEI": ("^N225", "index"), "HANGSENG": ("^HSI", "index"), "SHANGHAI": ("000001.SS", "index"),
    "CSI300": ("000300.SS", "index"), "KOSPI": ("^KS11", "index"), "ASX200": ("^AXJO", "index"),
    # Europe
    "STOXX50": ("^STOXX50E", "index"), "DAX": ("^GDAXI", "index"), "CAC40": ("^FCHI", "index"),
    "FTSE100": ("^FTSE", "index"), "IBEX35": ("^IBEX", "index"),
    # US futures/risk
    "SP500F": ("ES=F", "future_index"), "NASDAQF": ("NQ=F", "future_index"), "DOWF": ("YM=F", "future_index"),
    "RUSSELLF": ("RTY=F", "future_index"), "VIX": ("^VIX", "vix"),
    # Commodities/FX/rates
    "BRENT": ("BZ=F", "commodity"), "WTI": ("CL=F", "commodity"), "MINERIO": ("TIO=F", "commodity"),
    "OURO": ("GC=F", "commodity"), "COBRE": ("HG=F", "commodity"), "DXY": ("DX-Y.NYB", "fx"),
    "US10Y": ("^TNX", "yield"), "US2Y": ("2YY=F", "yield"),
    # Brazil
    "IBOV": ("^BVSP", "index"), "USDBRL": ("BRL=X", "fx"), "IFIX": ("IFIX.SA", "index"), "BPAC11": ("BPAC11.SA", "br_stock"),
}

LIMITS = {
    "index": 5.0,
    "future_index": 5.0,
    "commodity": 7.0,
    "fx": 3.0,
    "yield": 8.0,
    "vix": 25.0,
    "br_stock": 15.0,
}

NAMES = {
    "NIKKEI": "Nikkei 225", "HANGSENG": "Hang Seng", "SHANGHAI": "Shanghai", "CSI300": "CSI 300",
    "KOSPI": "Kospi", "ASX200": "ASX 200", "STOXX50": "Euro Stoxx 50", "DAX": "DAX",
    "CAC40": "CAC 40", "FTSE100": "FTSE 100", "IBEX35": "IBEX 35", "SP500F": "S&P 500 Fut.",
    "NASDAQF": "Nasdaq Fut.", "DOWF": "Dow Fut.", "RUSSELLF": "Russell 2000 Fut.", "VIX": "VIX",
    "BRENT": "Brent", "WTI": "WTI", "MINERIO": "Minério", "OURO": "Ouro", "COBRE": "Cobre",
    "DXY": "DXY", "US10Y": "Treasury 10Y", "US2Y": "2Y Yield Fut.", "IBOV": "Ibovespa",
    "USDBRL": "USD/BRL", "IFIX": "IFIX", "BPAC11": "BPAC11",
}


@dataclass
class Quote:
    key: str
    symbol: str
    asset_class: str
    price: float | None = None
    var: float | None = None
    error: str | None = None
    suspect: bool = False
    suspect_reason: str | None = None

    @property
    def trusted_var(self) -> float | None:
        return None if self.suspect else self.var


def yahoo_quote(key: str, symbol: str, asset_class: str) -> Quote:
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
    closes = [x for x in res.get("indicators", {}).get("quote", [{}])[0].get("close", []) if x is not None]
    if price is None:
        price = closes[-1] if closes else None
    if (prev is None or prev == 0) and len(closes) > 1:
        prev = closes[-2]
    var = (price / prev - 1) * 100 if price is not None and prev else None
    q = Quote(key=key, symbol=symbol, asset_class=asset_class, price=price, var=var)
    apply_sanity_check(q)
    return q


def apply_sanity_check(q: Quote) -> None:
    if q.price is None:
        q.suspect = True
        q.suspect_reason = "preço indisponível"
        return
    if q.var is None:
        q.suspect = True
        q.suspect_reason = "variação indisponível"
        return
    limit = LIMITS.get(q.asset_class, 10.0)
    if abs(q.var) > limit:
        q.suspect = True
        q.suspect_reason = f"variação {fmt_pct(q.var)} acima do limite de sanity check ({limit:.0f}%)"


def fmt_num(x, digits=2):
    if x is None:
        return "N/D"
    if abs(x) >= 1000:
        return f"{x:,.0f}".replace(",", ".")
    return f"{x:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(x):
    if x is None:
        return "N/D"
    sign = "+" if x >= 0 else ""
    return (sign + f"{x:.2f}%").replace(".", ",")


def cls(x, suspect=False):
    if suspect:
        return "neu"
    if x is None or abs(x) < 0.10:
        return "neu"
    return "pos" if x > 0 else "neg"


def quote_value(q: Quote, with_var=False, percent_suffix=False):
    value = fmt_num(q.price) + ("%" if percent_suffix and q.price is not None else "")
    if with_var:
        value = f"{value} ({fmt_pct(q.var)})"
    if q.suspect:
        value += " ⚠️"
    return value


def status_from(vals):
    nums = [v for v in vals if v is not None]
    if not nums:
        return "N/D", "neu"
    avg = sum(nums) / len(nums)
    if avg > 0.20:
        return "Positiva", "pos"
    if avg < -0.20:
        return "Negativa", "neg"
    return "Mista/estável", "neu"


def direction_text(x, up="alta", down="queda", flat="estabilidade"):
    if x is None:
        return "sem dado confiável"
    if x > 0.20:
        return up
    if x < -0.20:
        return down
    return flat


def load_agenda(brt: datetime):
    path = DATA_DIR / "agenda-economica.json"
    if path.exists():
        try:
            rows = json.loads(path.read_text())
            if rows:
                return rows[:3], "Real", "Agenda carregada de data/agenda-economica.json."
        except Exception as exc:
            return fallback_agenda(), "Fallback", f"Falha ao ler agenda local: {exc}."
    return fallback_agenda(), "Fallback", "Fonte automática de agenda ainda não integrada; usar calendário oficial antes de eventos relevantes."


def fallback_agenda():
    return [
        {"hora": "--", "regiao": "Global", "evento": "Monitorar calendário macro oficial do dia", "impacto": "Alto"},
        {"hora": "--", "regiao": "Brasil", "evento": "BC/B3/IBGE conforme calendário oficial", "impacto": "Médio"},
        {"hora": "--", "regiao": "EUA", "evento": "Dados e falas do Fed conforme agenda oficial", "impacto": "Médio"},
    ]


def load_brazil_curve():
    path = DATA_DIR / "curva-brasil.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            label = data.get("label") or data.get("di") or "Curva Brasil carregada"
            obs = data.get("observacao") or "Fonte local data/curva-brasil.json."
            return str(label), "Integrada", obs
        except Exception as exc:
            return "Fonte local inválida", "Fallback", f"Falha ao ler curva local: {exc}."
    return "Fonte não integrada", "Pendente", "DI/curva Brasil ainda depende de integração B3/ANBIMA ou fonte confiável."


def build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score, agenda_status, curve_status):
    def v(k): return quotes.get(k, Quote(k, "", "")).trusted_var
    brent, iron, dxy, vix, spx, ndx, us10 = v("BRENT"), v("MINERIO"), v("DXY"), v("VIX"), v("SP500F"), v("NASDAQF"), v("US10Y")
    usdbrl, ifix = v("USDBRL"), v("IFIX")

    risk_label = "risk-on" if risk_score >= 2 else "risk-off" if risk_score <= -2 else "neutro/cauteloso"
    macro = (
        f"O pano de fundo global está {risk_label}. Ásia veio {asia_status.lower()}, Europa {eur_status.lower()} e futuros dos EUA {usa_status.lower()}. "
        f"S&P futuro mostra {direction_text(spx, 'tração positiva', 'pressão vendedora', 'estabilidade')} e Nasdaq {direction_text(ndx, 'apetite por tecnologia', 'realização em tecnologia', 'sem direção forte')}. "
    )
    if dxy is not None:
        macro += "DXY em alta reduz espaço para emergentes e costuma pressionar dólar/juros locais. " if dxy > 0.15 else "DXY mais fraco ajuda o fluxo para emergentes. " if dxy < -0.15 else "DXY está sem direção forte, deixando o Brasil mais dependente de commodities e fluxo local. "
    if us10 is not None:
        macro += "Treasuries mais pressionados exigem cautela com ativos de duration longa. " if us10 > 0.5 else "Treasuries mais leves favorecem duration e bolsa. " if us10 < -0.5 else "Treasuries não mostram estresse relevante no início do dia. "
    if agenda_status != "Real":
        macro += "Agenda oficial não integrada reduz a confiança em leitura de eventos binários. "
    if vix is not None and vix > 2:
        macro += "VIX em alta recomenda reduzir alavancagem intradiária."

    commodities = ""
    commodities += "Brent em alta favorece leitura inicial para PETR4/PRIO3. " if (brent or 0) > 0.2 else "Brent em queda tira suporte de petróleo e pede cautela com PETR4/PRIO3. " if (brent or 0) < -0.2 else "Brent está estável, sem grande impulso direcional para petróleo. "
    commodities += "Minério em alta melhora o viés para VALE3 e siderúrgicas. " if (iron or 0) > 0.2 else "Minério em queda deixa VALE3 e siderúrgicas vulneráveis. " if (iron or 0) < -0.2 else "Minério está sem direção forte; acompanhar China e ADRs de mineração. "
    commodities += "Dados marcados com ⚠️ não entram na convicção central do dia."

    brasil = (
        "No Brasil, a leitura inicial deve combinar exterior, dólar e curva. "
        + ("USD/BRL pressionado reforça cautela com bolsa e FIIs. " if (usdbrl or 0) > 0.2 else "USD/BRL mais comportado ajuda ativos locais. " if (usdbrl or 0) < -0.2 else "USD/BRL está sem sinal forte. ")
        + ("Curva Brasil integrada melhora a leitura de bancos, FIIs, varejo e construtoras. " if curve_status == "Integrada" else "Curva Brasil/DI ainda não integrada; leitura de FIIs e crédito deve ser tratada com ressalva. ")
        + ("IFIX positivo sugere algum alívio na margem para fundos imobiliários. " if (ifix or 0) > 0.1 else "IFIX fraco/pressionado reforça atenção à curva longa e fundos high yield. " if (ifix or 0) < -0.1 else "IFIX sem grande sinal; aguardar abertura e curva de juros. ")
    )

    vol_score = sum(1 for x in [brent, iron, dxy, spx, ndx, vix] if x is not None and abs(x) > 0.5)
    vol_label = "elevada" if vol_score >= 3 or ((vix or 0) > 2) else "moderada" if vol_score >= 1 else "baixa/moderada"
    opcoes = (
        f"Volatilidade esperada {vol_label}. PETR4 merece atenção pelo Brent; VALE3 pelo minério/China; BOVA11 pelo conjunto exterior + juros + dólar. "
        "Com agenda ou dados incompletos, priorizar estruturas com risco definido e evitar venda descoberta de volatilidade."
    )

    if risk_score > 0 and not ((dxy or 0) > 0.3 or (vix or 0) > 2):
        gestor = "Postura construtiva, mas seletiva: favorecer ativos alinhados aos drivers positivos e evitar perseguir preço em gap de abertura."
    elif risk_score < 0 or ((dxy or 0) > 0.3 and (vix or 0) > 1):
        gestor = "Postura defensiva: reduzir tamanho, priorizar liquidez e aguardar confirmação da abertura."
    else:
        gestor = "Postura de observação ativa: cenário sem assimetria clara; aguardar fluxo estrangeiro e confirmação em dólar/juros."
    return macro, commodities, brasil, opcoes, gestor, vol_label


def pill(status: str) -> str:
    klass = "low" if status in {"Real", "Integrada", "OK"} else "mid" if status in {"Derivado", "Parcial", "Fallback"} else "high"
    return f'<span class="pill {klass}">{html.escape(status)}</span>'


def quality_rows(alerts, agenda_status, agenda_obs, curve_status, curve_obs):
    market_status = "Parcial" if alerts else "Real"
    market_obs = "Yahoo Finance Chart API pública; dados anômalos marcados com ⚠️ e excluídos da convicção." if alerts else "Yahoo Finance Chart API pública; nenhum alerta de sanity check no momento da geração."
    rows = [
        ("Índices, futuros, commodities, DXY, USD/BRL", market_status, market_obs),
        ("Leitura dos especialistas e vieses", "Derivado", "Interpretação automática Orion baseada somente em dados aprovados no sanity check."),
        ("Agenda econômica", agenda_status, agenda_obs),
        ("Treasuries", "Parcial", "10Y via índice Yahoo; 2Y via futuro de yield. Melhorar com fonte oficial/FRED."),
        ("DI futuro / curva Brasil", curve_status, curve_obs),
    ]
    return "\n".join(f"<tr><td>{html.escape(a)}</td><td>{pill(b)}</td><td>{html.escape(c)}</td></tr>" for a, b, c in rows)


def specialist_rows(agenda_status, curve_status, alerts):
    rows = [
        ("Macro/Global", "OK", "Pass aplicado com índices globais, futuros EUA, DXY, Treasuries e VIX."),
        ("Brasil/B3", "Parcial" if curve_status != "Integrada" else "OK", "Pass aplicado; curva Brasil melhora quando data/curva-brasil.json estiver disponível."),
        ("Opções & Derivativos", "OK", "Pass aplicado com foco em volatilidade, PETR4, VALE3, BOVA11 e risco definido."),
        ("FIIs & Crédito", "Parcial" if curve_status != "Integrada" else "OK", "Pass aplicado com ressalva enquanto DI/curva não estiver integrado."),
        ("Gestor de Fundos/Risco", "OK", "Pass aplicado; dados suspeitos reduzem convicção e tamanho sugerido."),
        ("Editor do Boletim", "OK" if not alerts else "Parcial", "Pass aplicado; alertas de qualidade foram explicitados no boletim."),
    ]
    if agenda_status != "Real":
        rows.append(("Agenda/Eventos", "Fallback", "Sem calendário automático oficial; conferir agenda antes de eventos binários."))
    return "\n".join(f"<tr><td>{html.escape(a)}</td><td>{pill(b)}</td><td>{html.escape(c)}</td></tr>" for a, b, c in rows)


def alert_html(alerts):
    if not alerts:
        return '<div class="callout"><strong>Status:</strong> Nenhum alerta de qualidade relevante no momento da geração.</div>'
    items = "".join(f"<li>{html.escape(x)}</li>" for x in alerts[:10])
    extra = "" if len(alerts) <= 10 else f"<li>+{len(alerts)-10} alertas adicionais.</li>"
    return f'<div class="callout warn"><strong>Alertas:</strong><ul>{items}{extra}</ul></div>'


def make_history(brt):
    files = sorted(OUTDIR.glob("boletim-orion-*.html"), reverse=True)
    links = "\n".join(f'<li><a href="{f.name}">{f.stem.replace("boletim-orion-", "")}</a></li>' for f in files)
    if not links:
        links = "<li>Nenhum boletim histórico disponível.</li>"
    html_doc = f"""<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Histórico — Boletim Orion</title><style>body{{font-family:Arial,sans-serif;background:#0b1020;color:#eef3ff;padding:32px}}a{{color:#5aa9ff}}</style></head><body><h1>Histórico — Boletim Orion</h1><p>Atualizado em {brt.strftime('%d/%m/%Y %H:%M BRT')}.</p><ul>{links}</ul><p><a href=\"boletim-orion-latest.html\">Voltar ao boletim mais recente</a></p></body></html>"""
    (OUTDIR / "historico.html").write_text(html_doc)


def write_telegram_summary(vals, alerts, agenda_status, curve_status):
    alert_line = "Nenhum alerta crítico" if not alerts else "; ".join(alerts[:3])
    text = (
        "📊 Boletim Orion — Abertura de Mercado\n\n"
        f"Tom: {vals['TOM_MERCADO']}\n"
        f"Drivers: {vals['DRIVER_PRINCIPAL']}\n"
        f"Qualidade: dados {'com alertas' if alerts else 'sem alertas relevantes'} | Agenda: {agenda_status} | Curva Brasil: {curve_status}\n"
        f"Alertas: {alert_line}\n\n"
        f"Link do boletim:\n{PAGES_URL}\n"
    )
    (OUTDIR / "telegram-summary.txt").write_text(text)


def main():
    quotes: dict[str, Quote] = {}
    alerts: list[str] = []
    for key, (sym, asset_class) in SYMBOLS.items():
        try:
            q = yahoo_quote(key, sym, asset_class)
        except Exception as e:
            q = Quote(key=key, symbol=sym, asset_class=asset_class, error=str(e), suspect=True, suspect_reason=str(e))
        quotes[key] = q
        if q.suspect:
            alerts.append(f"{NAMES.get(key, key)} ({q.symbol}): {q.suspect_reason or 'dado suspeito'}")
        time.sleep(0.15)

    brt = datetime.now(ZoneInfo("America/Sao_Paulo"))
    agenda, agenda_status, agenda_obs = load_agenda(brt)
    curve_label, curve_status, curve_obs = load_brazil_curve()

    vals = {
        "DATA": brt.strftime("%d/%m/%Y"),
        "HORARIO_ATUALIZACAO": brt.strftime("%H:%M BRT"),
        "EVENTO_CHAVE": agenda[0]["evento"],
    }
    for i, item in enumerate(agenda[:3], 1):
        vals[f"AGENDA_{i}_HORA"] = item.get("hora", "--")
        vals[f"AGENDA_{i}_REGIAO"] = item.get("regiao", "--")
        vals[f"AGENDA_{i}_EVENTO"] = item.get("evento", "--")
        vals[f"AGENDA_{i}_IMPACTO"] = item.get("impacto", "Médio")

    asia_status, asia_cls = status_from([quotes[k].trusted_var for k in ["NIKKEI", "HANGSENG", "SHANGHAI", "CSI300", "KOSPI", "ASX200"]])
    eur_status, eur_cls = status_from([quotes[k].trusted_var for k in ["STOXX50", "DAX", "CAC40", "FTSE100", "IBEX35"]])
    usa_status, usa_cls = status_from([quotes[k].trusted_var for k in ["SP500F", "NASDAQF", "DOWF", "RUSSELLF"]])
    vals.update({"ASIA_STATUS": asia_status, "ASIA_CLASSE": asia_cls, "EUROPA_STATUS": eur_status, "EUROPA_CLASSE": eur_cls, "EUA_STATUS": usa_status, "EUA_CLASSE": usa_cls})

    for k, q in quotes.items():
        vals[k] = quote_value(q)
        vals[f"{k}_VAR"] = fmt_pct(q.var) + (" ⚠️" if q.suspect else "")
        vals[f"{k}_CLASSE"] = cls(q.var, q.suspect)

    vals["BRENT"] = quote_value(quotes["BRENT"], with_var=True)
    vals["MINERIO"] = quote_value(quotes["MINERIO"], with_var=True)
    vals["OURO"] = quote_value(quotes["OURO"], with_var=True)
    vals["COBRE"] = quote_value(quotes["COBRE"], with_var=True)
    vals["DXY"] = quote_value(quotes["DXY"], with_var=True)
    vals["US10Y"] = quote_value(quotes["US10Y"], percent_suffix=True)
    vals["US2Y"] = quote_value(quotes["US2Y"], percent_suffix=True)
    vals["IFIX_BR"] = vals.get("IFIX", "N/D")
    vals["IBOV"] = f"Fechou/último em {vals.get('IBOV', 'N/D')} pts"
    vals["USDBRL"] = f"R$ {vals.get('USDBRL', 'N/D')}"

    def tv(k): return quotes[k].trusted_var
    risk_score = sum(1 if c == "pos" else -1 if c == "neg" else 0 for c in [asia_cls, eur_cls, usa_cls])
    if alerts:
        risk_score = max(min(risk_score, 1), -1)
    tom = "Positivo" if risk_score >= 2 else "Negativo" if risk_score <= -2 else "Cauteloso"
    badge_cls = "positive" if tom == "Positivo" else "negative" if tom == "Negativo" else "neutral"
    vals["TOM_MERCADO"] = tom
    vals["DRIVER_PRINCIPAL"] = "Exterior, DXY/Treasuries, commodities e qualidade dos dados"
    vals["VIES_IBOV"] = "Positivo" if risk_score > 0 else "Negativo" if risk_score < 0 else "Neutro/Cauteloso"
    vals["VIES_DOLAR"] = "Alta" if (tv("DXY") or 0) > 0.15 else "Baixa" if (tv("DXY") or 0) < -0.15 else "Lateral"
    vals["VIX_STATUS"] = "Pressionado" if (tv("VIX") or 0) > 2 else "Calmo/estável"
    vals["VIX_CLASSE"] = "neg" if (tv("VIX") or 0) > 2 else "neu"
    alert_phrase = " Há alertas de qualidade; dados marcados com ⚠️ foram retirados da convicção central." if alerts else " Sem alertas relevantes de sanity check."
    vals["RESUMO_EXECUTIVO"] = f"Mercados globais abrem com tom {tom.lower()}. Ásia: {asia_status}; Europa: {eur_status}; futuros dos EUA: {usa_status}. O foco inicial está em DXY, Treasuries, commodities e curva local.{alert_phrase}"
    vals["LEITURA_OPERACIONAL"] = "Começar seletivo, priorizando estruturas com risco definido e calibrando tamanho conforme qualidade dos dados e agenda do dia."
    vals["IMPACTO_IBOV"] = "Depende do exterior, commodities e validação dos alertas"
    vals["IMPACTO_DOLAR"] = "DXY/Treasuries são o principal driver"
    vals["DI"] = curve_label
    vals["IMPACTO_DI"] = "Impacta FIIs, bancos, varejo e construtoras"
    vals["IMPACTO_IFIX"] = "Sensível à curva longa de juros"
    vals["RADAR_PETR4"] = "Viés favorecido pelo Brent" if (tv("BRENT") or 0) > 0 else "Cautela se Brent pressionado ou suspeito"
    vals["RADAR_VALE3"] = "Viés favorecido pelo minério" if (tv("MINERIO") or 0) > 0 else "Cautela com minério/China ou dado suspeito"
    vals["RADAR_ITUB4"] = "Observar curva de juros e apetite por risco local"
    vals["RADAR_BOVA11"] = "Proxy do humor global e fluxo para Brasil"
    vals["RADAR_BBAS3"] = "Sensível a bancos, fiscal e risco político"
    vals["RADAR_ABEV3"] = "Perfil defensivo; observar dólar e consumo"
    vals["RADAR_WEGE3"] = "Sensível a juros globais e dólar"
    vals["RADAR_BPAC11"] = f"{quote_value(quotes['BPAC11'], with_var=True)} — sensível a juros, mercado de capitais e risco Brasil"

    macro, commodities, brasil_fiis, opcoes, gestor, vol_label = build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score, agenda_status, curve_status)
    vals["ANALISE_MACRO_GLOBAL"] = macro
    vals["ANALISE_COMMODITIES"] = commodities
    vals["ANALISE_BRASIL_FIIS"] = brasil_fiis
    vals["ANALISE_OPCOES"] = opcoes
    vals["ANALISE_GESTOR"] = gestor
    vals["RADAR_OPCOES"] = opcoes
    vals["VOL_STATUS"] = vol_label.capitalize()
    vals["VOL_CLASSE"] = "neg" if vol_label == "elevada" else "neu"
    vals["OPCOES_ATIVOS"] = "PETR4, VALE3, BOVA11, ITUB4"
    vals["EVENTO_BINARIO"] = agenda[0]["evento"] if agenda_status == "Real" else "Agenda em fallback — confirmar calendário oficial"
    vals["ALERTAS_QUALIDADE"] = alert_html(alerts)
    vals["QUALITY_ROWS"] = quality_rows(alerts, agenda_status, agenda_obs, curve_status, curve_obs)
    vals["SPECIALIST_ROWS"] = specialist_rows(agenda_status, curve_status, alerts)
    vals["CONCLUSAO_OPERACIONAL"] = gestor + " O boletim é informativo, usa dados públicos e reduz convicção quando há alerta de fonte; reavaliar após abertura local e principais dados do dia."

    html_doc = TEMPLATE.read_text()
    html_doc = re.sub(r'<span class="badge neutral">● Tom do mercado: Cauteloso</span>', f'<span class="badge {badge_cls}">● Tom do mercado: {tom}</span>', html_doc)
    for k, v in vals.items():
        html_doc = html_doc.replace("{{" + k + "}}", str(v))
    html_doc = re.sub(r"{{[^}]+}}", "N/D", html_doc)

    OUTDIR.mkdir(exist_ok=True)
    out = OUTDIR / f"boletim-orion-{brt.strftime('%Y-%m-%d')}.html"
    out.write_text(html_doc)
    latest = OUTDIR / "boletim-orion-latest.html"
    latest.write_text(html_doc)
    make_history(brt)
    write_telegram_summary(vals, alerts, agenda_status, curve_status)
    print(out)


if __name__ == "__main__":
    main()
