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
from datetime import datetime, timedelta
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

# Fonte principal: TradingView (variação diária já calculada na origem).
# Yahoo (SYMBOLS) entra como fallback símbolo a símbolo quando o TradingView falha.
TV_SCANNER = "https://scanner.tradingview.com/global/scan"
TV_CALENDAR = "https://economic-calendar.tradingview.com/events"

TV_TICKERS = {
    "NIKKEI": "TVC:NI225", "HANGSENG": "TVC:HSI", "SHANGHAI": "SSE:000001", "CSI300": "SSE:000300",
    "KOSPI": "KRX:KOSPI", "ASX200": "ASX:XJO", "STOXX50": "TVC:SX5E", "DAX": "XETR:DAX",
    "CAC40": "EURONEXT:PX1", "FTSE100": "TVC:UKX", "IBEX35": "TVC:IBEX35", "SP500F": "CME_MINI:ES1!",
    "NASDAQF": "CME_MINI:NQ1!", "DOWF": "CBOT_MINI:YM1!", "RUSSELLF": "CME_MINI:RTY1!", "VIX": "TVC:VIX",
    "BRENT": "ICEEUR:BRN1!", "WTI": "NYMEX:CL1!", "MINERIO": "SGX:FEF1!", "OURO": "COMEX:GC1!",
    "COBRE": "COMEX:HG1!", "DXY": "TVC:DXY", "US10Y": "TVC:US10Y", "US2Y": "TVC:US02Y",
    "IBOV": "BMFBOVESPA:IBOV", "USDBRL": "FX_IDC:USDBRL", "IFIX": "BMFBOVESPA:IFIX", "BPAC11": "BMFBOVESPA:BPAC11",
}

# Curva soberana do Brasil (proxy da curva de juros) via TradingView.
BR_CURVE_TICKERS = {"2A": "TVC:BR02Y", "5A": "TVC:BR05Y", "10A": "TVC:BR10Y"}
BR_SELIC_TICKER = "ECONOMICS:BRINTR"

COUNTRY_REGION = {"US": "EUA", "BR": "Brasil", "EU": "Zona do Euro", "CN": "China", "JP": "Japão", "GB": "Reino Unido"}
IMPORTANCE_LABEL = {1: "Alto", 0: "Médio", -1: "Baixo"}

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
    source: str = ""

    @property
    def trusted_var(self) -> float | None:
        return None if self.suspect else self.var


def tv_scan(tickers, columns) -> dict:
    """Requisição em lote ao scanner do TradingView; retorna {ticker: [colunas]}."""
    payload = {"symbols": {"tickers": tickers, "query": {"types": []}}, "columns": columns}
    req = urllib.request.Request(
        TV_SCANNER, data=json.dumps(payload).encode(),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
    return {row["s"]: row.get("d") for row in data.get("data", [])}


def fetch_tradingview() -> dict[str, tuple[float | None, float | None]]:
    """Cotações primárias via TradingView scanner numa única requisição em lote.

    Retorna {key: (close, change_pct)} apenas para símbolos com preço válido.
    A variação diária vem pronta da fonte (coluna ``change``), o que elimina o
    cálculo manual de baseline. Qualquer falha global propaga exceção e deixa o
    Yahoo assumir como fallback símbolo a símbolo.
    """
    by_ticker = tv_scan(list(TV_TICKERS.values()), ["close", "change"])
    out: dict[str, tuple[float | None, float | None]] = {}
    for key, ticker in TV_TICKERS.items():
        d = by_ticker.get(ticker)
        # exige preço e variação; se a variação faltar, deixa o Yahoo (fallback) tentar
        if d and d[0] is not None and d[1] is not None:
            out[key] = (d[0], d[1])
    return out


def previous_close(price, closes, meta):
    """Fechamento de referência para a variação diária.

    O array diário de closes inclui (quando o pregão está aberto/recente) a barra
    da sessão atual, cujo close acompanha o preço de mercado. A base correta é o
    último fechamento *anterior* a essa sessão. `chartPreviousClose` é apenas o
    fechamento antes do início da janela (~5 pregões atrás) e infla a variação,
    então só serve de fallback quando o array é insuficiente.
    """
    if closes:
        if price is not None and abs(price - closes[-1]) <= abs(closes[-1]) * 1e-3:
            # barra mais recente = sessão atual; recua um pregão
            if len(closes) >= 2:
                return closes[-2]
        else:
            # preço é intradiário de hoje; último close é o pregão anterior
            return closes[-1]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if (prev is None or prev == 0) and len(closes) > 1:
        prev = closes[-2]
    return prev


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
    closes = [x for x in res.get("indicators", {}).get("quote", [{}])[0].get("close", []) if x is not None]
    if price is None:
        price = closes[-1] if closes else None
    prev = previous_close(price, closes, meta)
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


def market_delta_text(q: Quote, positive: str, negative: str, neutral: str) -> str:
    var = q.trusted_var
    if var is None:
        return f"{NAMES.get(q.key, q.key)} sem dado confiável."
    if var > 0.20:
        return f"{NAMES.get(q.key, q.key)} {fmt_pct(var)}: {positive}."
    if var < -0.20:
        return f"{NAMES.get(q.key, q.key)} {fmt_pct(var)}: {negative}."
    return f"{NAMES.get(q.key, q.key)} {fmt_pct(var)}: {neutral}."


def flow_signal(flow_value, flow_status):
    if flow_status != "Integrada" or flow_value is None:
        return "Pendente", "neu", "sem saldo integrado; não usar como confirmação de fluxo local"
    if flow_value > 300:
        return "Comprador", "pos", "reforça apetite por Brasil"
    if flow_value < -300:
        return "Vendedor", "neg", "reduz convicção em bolsa local"
    return "Neutro", "neu", "não muda a convicção do dia"


def curve_direction_text(changes: dict[str, float | None]) -> str:
    valid = {tenor: change for tenor, change in changes.items() if change is not None}
    if not valid:
        return "sem variação diária confiável"
    up = [tenor for tenor, change in valid.items() if change > 0.03]
    down = [tenor for tenor, change in valid.items() if change < -0.03]
    if up and not down:
        return "abrindo em " + "/".join(up)
    if down and not up:
        return "fechando em " + "/".join(down)
    if up and down:
        return "mista/torcida, abrindo em " + "/".join(up) + " e fechando em " + "/".join(down)
    return "praticamente estável"


def curve_impact_text(direction: str) -> str:
    if "abrindo" in direction and "fechando" not in direction:
        return "Curva abrindo pressiona FIIs, varejo/construtoras e ativos de duration; favorece seletividade em bancos."
    if "fechando" in direction and "abrindo" not in direction:
        return "Curva fechando alivia FIIs, varejo/construtoras e duration; melhora o pano de fundo para bolsa local."
    if "mista" in direction:
        return "Curva mista pede leitura por trecho: bancos e FIIs podem reagir diferente entre curto e longo prazo."
    if "estável" in direction:
        return "Curva estável deixa a direção dos ativos locais mais dependente de dólar, fluxo estrangeiro e exterior."
    return "Sem variação confiável da curva; tratar leitura de FIIs, bancos e duration com ressalva."


def tradingview_agenda(brt: datetime):
    """Agenda econômica do dia (BRT) via calendário do TradingView.

    Prioriza eventos de importância alta/média (BR, EUA, Zona do Euro, China,
    Japão). Retorna None quando não há eventos para o dia.
    """
    start = brt.replace(hour=0, minute=0, second=0, microsecond=0)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    params = {
        "from": start.astimezone(ZoneInfo("UTC")).strftime(fmt),
        "to": (start + timedelta(days=1)).astimezone(ZoneInfo("UTC")).strftime(fmt),
        "countries": "US,BR,EU,CN,JP",
    }
    url = TV_CALENDAR + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Origin": "https://www.tradingview.com"})
    with urllib.request.urlopen(req, timeout=15) as r:
        events = json.loads(r.read().decode()).get("result", [])
    if not events:
        return None

    def imp(e):
        return e.get("importance") if e.get("importance") is not None else -9

    events.sort(key=lambda e: (-imp(e), e.get("date", "")))
    relevant = [e for e in events if imp(e) >= 0] or events
    rows = []
    for e in relevant[:3]:
        when = e.get("date")
        hora = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(brt.tzinfo).strftime("%H:%M") if when else "--"
        rows.append({
            "hora": hora,
            "regiao": COUNTRY_REGION.get(e.get("country"), e.get("country") or "Global"),
            "evento": e.get("title") or "Evento econômico",
            "impacto": IMPORTANCE_LABEL.get(e.get("importance"), "Médio"),
        })
    return rows


def load_agenda(brt: datetime):
    try:
        rows = tradingview_agenda(brt)
        if rows:
            return rows, "Real", "Agenda do dia via calendário econômico TradingView (importância alta/média priorizada)."
    except Exception:
        pass  # qualquer falha do TradingView cai nas fontes seguintes
    path = DATA_DIR / "agenda-economica.json"
    if path.exists():
        try:
            rows = json.loads(path.read_text())
            if rows:
                return rows[:3], "Real", "Agenda carregada de data/agenda-economica.json."
        except Exception as exc:
            return fallback_agenda(), "Fallback", f"Falha ao ler agenda local: {exc}."
    return fallback_agenda(), "Fallback", "Calendário TradingView e fonte local indisponíveis; usar calendário oficial antes de eventos relevantes."


def fallback_agenda():
    return [
        {"hora": "--", "regiao": "Global", "evento": "Monitorar calendário macro oficial do dia", "impacto": "Alto"},
        {"hora": "--", "regiao": "Brasil", "evento": "BC/B3/IBGE conforme calendário oficial", "impacto": "Médio"},
        {"hora": "--", "regiao": "EUA", "evento": "Dados e falas do Fed conforme agenda oficial", "impacto": "Médio"},
    ]


def tradingview_brazil_curve():
    """Curva de juros do Brasil via títulos soberanos (TradingView) + Selic.

    Retorna (label, "Integrada", observacao) ou None quando os tenores-chave
    (2A e 10A) não estão disponíveis.
    """
    by_ticker = tv_scan(list(BR_CURVE_TICKERS.values()) + [BR_SELIC_TICKER], ["close", "change"])
    ys = {}
    changes = {}
    for tenor, ticker in BR_CURVE_TICKERS.items():
        d = by_ticker.get(ticker)
        if d and d[0] is not None:
            ys[tenor] = d[0]
            changes[tenor] = d[1] if len(d) > 1 else None
    if "2A" not in ys or "10A" not in ys:
        return None
    label_parts = []
    for tenor in BR_CURVE_TICKERS:
        if tenor in ys:
            change = changes.get(tenor)
            change_txt = f" ({fmt_pct(change)})" if change is not None else ""
            label_parts.append(f"{tenor} {fmt_num(ys[tenor])}%{change_txt}")
    label = " · ".join(label_parts)
    slope = ys["10A"] - ys["2A"]
    shape = "inclinação positiva" if slope > 0.10 else "invertida" if slope < -0.10 else "praticamente plana"
    direction = curve_direction_text(changes)
    impact = curve_impact_text(direction)
    selic = by_ticker.get(BR_SELIC_TICKER)
    selic_txt = f"Selic {fmt_num(selic[0])}%. " if selic and selic[0] is not None else ""
    slope_txt = f"{slope:+.2f}".replace(".", ",")
    obs = f"{selic_txt}Curva 2A→10A com {shape} ({slope_txt} pp) e {direction}. {impact} Títulos soberanos (LPS) via TradingView."
    analysis = f"{direction.capitalize()}. {impact}"
    return label, "Integrada", obs, analysis


def load_brazil_curve():
    try:
        curve = tradingview_brazil_curve()
        if curve:
            return curve
    except Exception:
        pass  # falha do TradingView cai nas fontes seguintes
    path = DATA_DIR / "curva-brasil.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            label = data.get("label") or data.get("di") or "Curva Brasil carregada"
            obs = data.get("observacao") or "Fonte local data/curva-brasil.json."
            analysis = data.get("analise") or data.get("direcao") or curve_impact_text("")
            return str(label), "Integrada", obs, str(analysis)
        except Exception as exc:
            return "Fonte local inválida", "Fallback", f"Falha ao ler curva local: {exc}.", curve_impact_text("")
    return "Fonte não integrada", "Pendente", "Curva de juros Brasil indisponível no TradingView e sem fonte local; integrar B3/ANBIMA.", curve_impact_text("")


def load_foreign_flow():
    """Fluxo estrangeiro B3, com fallback local.

    A B3 publica a participação dos investidores no site, mas os endpoints
    públicos mudam com frequência. O boletim aceita um JSON local para incorporar
    o dado sem tornar a geração diária dependente de scraping frágil.
    """
    path = DATA_DIR / "fluxo-estrangeiro-b3.json"
    if not path.exists():
        return {
            "label": "Fonte não integrada",
            "status": "Pendente",
            "obs": "Criar data/fluxo-estrangeiro-b3.json com o saldo estrangeiro divulgado pela B3.",
            "value": None,
            "classe": "neu",
            "data": "--",
        }
    try:
        data = json.loads(path.read_text())
        value = data.get("saldo_milhoes") or data.get("saldo") or data.get("valor_milhoes")
        value = float(value) if value is not None else None
        date_label = data.get("data") or data.get("date") or "--"
        period_label = data.get("periodo") or f"em {date_label}"
        obs = data.get("observacao") or data.get("fonte") or "Fonte local data/fluxo-estrangeiro-b3.json."
        if value is None:
            label = data.get("label") or "Saldo não informado"
            classe = "neu"
        else:
            label = f"{fmt_brl_millions(value)} ({period_label})"
            classe = cls(value, False)
        return {"label": label, "status": "Integrada", "obs": str(obs), "value": value, "classe": classe, "data": date_label}
    except Exception as exc:
        return {
            "label": "Fonte local inválida",
            "status": "Fallback",
            "obs": f"Falha ao ler fluxo estrangeiro local: {exc}.",
            "value": None,
            "classe": "neu",
            "data": "--",
        }


def fmt_brl_millions(value):
    abs_value = abs(value)
    sign = "+" if value > 0 else "-" if value < 0 else ""
    if abs_value >= 1000:
        return f"{sign}R$ {fmt_num(abs_value / 1000)} bi"
    return f"{sign}R$ {fmt_num(abs_value)} mi"


def foreign_flow_text(flow_value, flow_status):
    if flow_status != "Integrada" or flow_value is None:
        return "Fluxo estrangeiro B3 ainda não integrado; validar saldo divulgado pela B3 antes de elevar convicção em Ibovespa/BOVA11. "
    if flow_value > 300:
        return "Fluxo estrangeiro B3 comprador reforça apetite por Brasil e melhora a confirmação para Ibovespa/BOVA11. "
    if flow_value < -300:
        return "Fluxo estrangeiro B3 vendedor reduz convicção em bolsa local e pede mais cautela em gaps de alta. "
    return "Fluxo estrangeiro B3 perto do neutro deixa a leitura local dependente de dólar, juros e commodities. "


def build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score, agenda_status, curve_status, foreign_flow):
    def v(k): return quotes.get(k, Quote(k, "", "")).trusted_var
    brent, iron, dxy, vix, spx, ndx, us10 = v("BRENT"), v("MINERIO"), v("DXY"), v("VIX"), v("SP500F"), v("NASDAQF"), v("US10Y")
    usdbrl, ifix = v("USDBRL"), v("IFIX")
    flow_value = foreign_flow.get("value")
    flow_status = foreign_flow.get("status")

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
        + foreign_flow_text(flow_value, flow_status)
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
        gestor = "Postura de observação ativa: cenário sem assimetria clara; aguardar fluxo estrangeiro B3 e confirmação em dólar/juros."
    return macro, commodities, brasil, opcoes, gestor, vol_label


def pill(status: str) -> str:
    klass = "low" if status in {"Real", "Integrada", "OK"} else "mid" if status in {"Derivado", "Parcial", "Fallback"} else "high"
    return f'<span class="pill {klass}">{html.escape(status)}</span>'


def quality_rows(quotes, alerts, agenda_status, agenda_obs, curve_status, curve_obs, foreign_flow, source_note):
    market_status = "Parcial" if alerts else "Real"
    base = f"{source_note}; variação diária na origem."
    market_obs = f"{base} Dados anômalos marcados com ⚠️ e excluídos da convicção." if alerts else f"{base} Nenhum alerta de sanity check no momento da geração."
    treasuries_tv = all(quotes.get(k) and quotes[k].source == "TradingView" for k in ["US10Y", "US2Y"])
    if treasuries_tv:
        treasuries_status, treasuries_obs = "Real", "10Y e 2Y via TradingView (TVC:US10Y / TVC:US02Y)."
    else:
        treasuries_status, treasuries_obs = "Parcial", "10Y via índice Yahoo (^TNX); 2Y via futuro de yield. Melhorar com fonte oficial/FRED."
    rows = [
        ("Índices, futuros, commodities, DXY, USD/BRL", market_status, market_obs),
        ("Leitura dos especialistas e vieses", "Derivado", "Interpretação automática Orion baseada somente em dados aprovados no sanity check."),
        ("Agenda econômica", agenda_status, agenda_obs),
        ("Treasuries", treasuries_status, treasuries_obs),
        ("DI futuro / curva Brasil", curve_status, curve_obs),
        ("Fluxo estrangeiro B3", foreign_flow["status"], foreign_flow["obs"]),
    ]
    return "\n".join(f"<tr><td>{html.escape(a)}</td><td>{pill(b)}</td><td>{html.escape(c)}</td></tr>" for a, b, c in rows)


def specialist_rows(agenda_status, curve_status, foreign_flow_status, alerts):
    rows = [
        ("Macro/Global", "OK", "Pass aplicado com índices globais, futuros EUA, DXY, Treasuries e VIX."),
        ("Brasil/B3", "Parcial" if curve_status != "Integrada" or foreign_flow_status != "Integrada" else "OK", "Pass aplicado; curva Brasil e fluxo estrangeiro aumentam convicção quando integrados."),
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
    files = sorted(
        (f for f in OUTDIR.glob("boletim-orion-*.html") if f.name != "boletim-orion-latest.html"),
        reverse=True,
    )
    links = "\n".join(f'<li><a href="{f.name}">{f.stem.replace("boletim-orion-", "")}</a></li>' for f in files)
    if not links:
        links = "<li>Nenhum boletim histórico disponível.</li>"
    html_doc = f"""<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Histórico — Boletim Orion</title><style>body{{font-family:Arial,sans-serif;background:#0b1020;color:#eef3ff;padding:32px}}a{{color:#5aa9ff}}</style></head><body><h1>Histórico — Boletim Orion</h1><p>Atualizado em {brt.strftime('%d/%m/%Y %H:%M BRT')}.</p><ul>{links}</ul><p><a href=\"boletim-orion-latest.html\">Voltar ao boletim mais recente</a></p></body></html>"""
    (OUTDIR / "historico.html").write_text(html_doc)


def write_telegram_summary(vals, alerts, agenda_status, curve_status, foreign_flow_status):
    alert_line = "Nenhum alerta crítico" if not alerts else "; ".join(alerts[:3])
    text = (
        "📊 Boletim Orion — Abertura de Mercado\n\n"
        f"Tom: {vals['TOM_MERCADO']}\n"
        f"Drivers: {vals['DRIVER_PRINCIPAL']}\n"
        f"Fluxo B3: {vals['FLUXO_ESTRANGEIRO']} ({foreign_flow_status})\n"
        f"Qualidade: dados {'com alertas' if alerts else 'sem alertas relevantes'} | Agenda: {agenda_status} | Curva Brasil: {curve_status}\n"
        f"Alertas: {alert_line}\n\n"
        f"Link do boletim:\n{PAGES_URL}\n"
    )
    (OUTDIR / "telegram-summary.txt").write_text(text)


def main():
    quotes: dict[str, Quote] = {}
    alerts: list[str] = []
    try:
        tv = fetch_tradingview()
    except Exception:
        tv = {}
    for key, (sym, asset_class) in SYMBOLS.items():
        q = None
        if key in tv:
            close, change = tv[key]
            q = Quote(key=key, symbol=TV_TICKERS[key], asset_class=asset_class, price=close, var=change, source="TradingView")
            apply_sanity_check(q)
        if q is None:  # TradingView indisponível para o símbolo: cai no Yahoo
            try:
                q = yahoo_quote(key, sym, asset_class)
                q.source = "Yahoo"
            except Exception as e:
                q = Quote(key=key, symbol=sym, asset_class=asset_class, error=str(e), suspect=True, suspect_reason=str(e), source="Yahoo")
            time.sleep(0.15)
        quotes[key] = q
        if q.suspect:
            alerts.append(f"{NAMES.get(key, key)} ({q.symbol}): {q.suspect_reason or 'dado suspeito'}")

    brt = datetime.now(ZoneInfo("America/Sao_Paulo"))
    agenda, agenda_status, agenda_obs = load_agenda(brt)
    curve_label, curve_status, curve_obs, curve_analysis = load_brazil_curve()
    foreign_flow = load_foreign_flow()

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
    flow_label, flow_cls, flow_note = flow_signal(foreign_flow["value"], foreign_flow["status"])
    vals["TOM_MERCADO"] = tom
    vals["DRIVER_PRINCIPAL"] = (
        "Exterior positivo com ressalvas de qualidade" if risk_score > 0 and alerts
        else "Exterior e commodities pró-risco" if risk_score > 0
        else "Dólar/volatilidade pressionando risco" if risk_score < 0
        else "Mercado sem driver dominante"
    )
    vals["DRIVER_DETALHE"] = f"Ásia {asia_status.lower()}, Europa {eur_status.lower()}, EUA {usa_status.lower()}; fluxo B3 {flow_label.lower()}."
    vals["VIES_IBOV"] = "Positivo" if risk_score > 0 else "Negativo" if risk_score < 0 else "Neutro/Cauteloso"
    vals["VIES_IBOV_CLASSE"] = "pos" if risk_score > 0 else "neg" if risk_score < 0 else "neu"
    vals["IBOV_DETALHE"] = f"Commodities: Brent {fmt_pct(tv('BRENT'))}, minério {fmt_pct(tv('MINERIO'))}; fluxo B3 {flow_note}."
    vals["VIES_DOLAR"] = "Alta" if (tv("DXY") or 0) > 0.15 else "Baixa" if (tv("DXY") or 0) < -0.15 else "Lateral"
    vals["VIES_DOLAR_CLASSE"] = "neg" if vals["VIES_DOLAR"] == "Alta" else "pos" if vals["VIES_DOLAR"] == "Baixa" else "neu"
    vals["DOLAR_DETALHE"] = f"DXY {fmt_pct(tv('DXY'))}; Treasury 10Y {quote_value(quotes['US10Y'], percent_suffix=True)}."
    vals["VIX_STATUS"] = "Pressionado" if (tv("VIX") or 0) > 2 else "Calmo/estável"
    vals["VIX_CLASSE"] = "neg" if (tv("VIX") or 0) > 2 else "neu"
    alert_phrase = " Há alertas de qualidade; dados marcados com ⚠️ foram retirados da convicção central." if alerts else " Sem alertas relevantes de sanity check."
    vals["RESUMO_EXECUTIVO"] = f"Mercados globais abrem com tom {tom.lower()}. Ásia: {asia_status}; Europa: {eur_status}; futuros dos EUA: {usa_status}. O foco inicial está em {vals['DRIVER_PRINCIPAL'].lower()}, curva local e fluxo estrangeiro B3.{alert_phrase}"
    vals["LEITURA_OPERACIONAL"] = (
        "Começar construtivo, mas seletivo; exigir confirmação no dólar, juros locais e fluxo estrangeiro antes de aumentar tamanho."
        if risk_score > 0 else
        "Começar defensivo; priorizar liquidez, risco definido e evitar comprar gap sem confirmação de fluxo."
        if risk_score < 0 else
        "Começar seletivo, priorizando estruturas com risco definido e calibrando tamanho conforme qualidade dos dados, fluxo B3 e agenda do dia."
    )
    vals["IMPACTO_IBOV"] = "Depende do exterior, commodities e validação dos alertas"
    vals["IMPACTO_DOLAR"] = "DXY/Treasuries são o principal driver"
    vals["DI"] = curve_label
    vals["IMPACTO_DI"] = curve_analysis
    vals["IMPACTO_IFIX"] = "Sensível à curva longa de juros"
    vals["FLUXO_ESTRANGEIRO"] = foreign_flow["label"]
    vals["FLUXO_ESTRANGEIRO_CLASSE"] = foreign_flow["classe"]
    vals["FLUXO_ESTRANGEIRO_STATUS"] = foreign_flow["status"]
    vals["FLUXO_ESTRANGEIRO_NOTA"] = f"Status {foreign_flow['status']}: {flow_note}."
    vals["FLUXO_ESTRANGEIRO_CALLOUT_CLASSE"] = "" if foreign_flow["status"] == "Integrada" else "warn"
    vals["FLUXO_ESTRANGEIRO_RESUMO"] = (
        f"{foreign_flow['label']} ({flow_label.lower()}); {flow_note}. Fonte/obs.: {foreign_flow['obs']}"
    )
    vals["IMPACTO_FLUXO_ESTRANGEIRO"] = (
        "Confirma apetite por Brasil" if foreign_flow["value"] and foreign_flow["value"] > 300
        else "Pressiona convicção em bolsa local" if foreign_flow["value"] and foreign_flow["value"] < -300
        else "Neutro ou pendente; validar com B3"
    )
    vals["EVENTO_CHAVE_DETALHE"] = f"Agenda {agenda_status}; impacto {agenda[0].get('impacto', 'Médio')} em {agenda[0].get('regiao', 'Global')}."
    vals["RADAR_PETR4"] = market_delta_text(quotes["BRENT"], "suporte para petróleo", "retira suporte de petróleo", "sem impulso forte para petróleo")
    vals["RADAR_VALE3"] = market_delta_text(quotes["MINERIO"], "suporte para mineração/siderurgia", "pressiona mineração/siderurgia", "depende mais de China e ADRs")
    vals["RADAR_ITUB4"] = f"Curva Brasil: {curve_analysis} Dólar {fmt_pct(tv('USDBRL'))}; risco global {tom.lower()}."
    vals["RADAR_BOVA11"] = f"Exterior {tom.lower()}, fluxo B3 {flow_label.lower()} e commodities Brent {fmt_pct(tv('BRENT'))}/minério {fmt_pct(tv('MINERIO'))}."
    vals["RADAR_BBAS3"] = f"Bancos dependem de curva local ({curve_status}): {curve_analysis} Fiscal e risco Brasil seguem no radar."
    vals["RADAR_ABEV3"] = f"Defensivo; dólar {fmt_pct(tv('USDBRL'))} e mercado {tom.lower()} definem rotação."
    vals["RADAR_WEGE3"] = f"Duration global: Treasury 10Y {quote_value(quotes['US10Y'], percent_suffix=True)}; dólar {fmt_pct(tv('USDBRL'))}."
    vals["RADAR_BPAC11"] = f"{quote_value(quotes['BPAC11'], with_var=True)} — sensível a juros, mercado de capitais e risco Brasil"

    macro, commodities, brasil_fiis, opcoes, gestor, vol_label = build_specialist_analysis(quotes, asia_status, eur_status, usa_status, risk_score, agenda_status, curve_status, foreign_flow)
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
    tv_count = sum(1 for q in quotes.values() if q.source == "TradingView")
    yh_count = sum(1 for q in quotes.values() if q.source == "Yahoo")
    source_note = f"TradingView (principal, {tv_count} ativos) com Yahoo Finance como fallback ({yh_count})"
    vals["QUALITY_ROWS"] = quality_rows(quotes, alerts, agenda_status, agenda_obs, curve_status, curve_obs, foreign_flow, source_note)
    vals["SPECIALIST_ROWS"] = specialist_rows(agenda_status, curve_status, foreign_flow["status"], alerts)
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
    write_telegram_summary(vals, alerts, agenda_status, curve_status, foreign_flow["status"])
    print(out)


if __name__ == "__main__":
    main()
