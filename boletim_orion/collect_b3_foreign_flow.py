#!/usr/bin/env python3
"""Coleta o fluxo estrangeiro da B3 a partir do Boletim Diario do Mercado."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTFILE = DATA_DIR / "fluxo-estrangeiro-b3.json"
BASE_URL = "https://arquivos.b3.com.br/bdi/download/bdi/{iso}/BDI_02_{ymd}.pdf"


def parse_brl_number(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


def br_date_to_iso(text: str) -> str:
    day, month, year = text.split("/")
    return f"{year}-{month}-{day}"


def candidate_dates(start: date, lookback_days: int):
    for offset in range(lookback_days + 1):
        current = start - timedelta(days=offset)
        if current.weekday() < 5:
            yield current


def download_pdf(day: date, directory: Path) -> tuple[Path, str]:
    url = BASE_URL.format(iso=day.strftime("%Y-%m-%d"), ymd=day.strftime("%Y%m%d"))
    pdf_path = directory / f"BDI_02_{day.strftime('%Y%m%d')}.pdf"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        pdf_path.write_bytes(response.read())
    return pdf_path, url


def pdf_to_text(pdf_path: Path, text_path: Path) -> None:
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext nao encontrado; instale poppler-utils no ambiente.")
    subprocess.run(["pdftotext", "-layout", str(pdf_path), str(text_path)], check=True)


def parse_investor_section(text: str) -> dict:
    date_match = re.search(r"Dados acumulados do in[íi]cio do m[êe]s at[ée] o dia\s+(\d{2}/\d{2}/\d{4})", text, re.I)
    if not date_match:
        raise ValueError("Data de referencia da tabela de participacao nao encontrada.")

    row_match = re.search(
        r"Investidor Estrangeiro\s+([\d.]+(?:,\d+)?)\s+([\d.,]+)\s+([\d.]+(?:,\d+)?)\s+([\d.,]+)",
        text,
        re.I,
    )
    if not row_match:
        raise ValueError("Linha de Investidor Estrangeiro nao encontrada.")

    compra_r_mil = parse_brl_number(row_match.group(1))
    compra_participacao = parse_brl_number(row_match.group(2))
    venda_r_mil = parse_brl_number(row_match.group(3))
    venda_participacao = parse_brl_number(row_match.group(4))
    saldo_r_mil = compra_r_mil - venda_r_mil

    return {
        "data": br_date_to_iso(date_match.group(1)),
        "periodo": f"acumulado no mes ate {date_match.group(1)}",
        "mercado": "mercado a vista B3 - participacao dos investidores",
        "compra_milhoes": round(compra_r_mil / 1000, 3),
        "venda_milhoes": round(venda_r_mil / 1000, 3),
        "saldo_milhoes": round(saldo_r_mil / 1000, 3),
        "compra_participacao_pct": compra_participacao,
        "venda_participacao_pct": venda_participacao,
    }


def collect(start: date, lookback_days: int) -> dict:
    last_error = None
    with tempfile.TemporaryDirectory(prefix="b3-bdi-") as tmp:
        tmpdir = Path(tmp)
        for day in candidate_dates(start, lookback_days):
            try:
                pdf_path, url = download_pdf(day, tmpdir)
                text_path = tmpdir / f"{pdf_path.stem}.txt"
                pdf_to_text(pdf_path, text_path)
                parsed = parse_investor_section(text_path.read_text(encoding="utf-8", errors="ignore"))
                parsed.update(
                    {
                        "boletim_data": day.isoformat(),
                        "fonte": "B3 - Boletim Diario do Mercado",
                        "url": url,
                        "coletado_em": datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat(timespec="seconds"),
                    }
                )
                return parsed
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Nenhum boletim B3 valido encontrado em {lookback_days} dias: {last_error}")


def validate(data: dict, max_age_days: int) -> None:
    ref_date = date.fromisoformat(data["data"])
    today = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    if ref_date > today:
        raise ValueError(f"Data de referencia futura: {ref_date}")
    if (today - ref_date).days > max_age_days:
        raise ValueError(f"Dado de fluxo estrangeiro velho: {ref_date}")
    expected = round(data["compra_milhoes"] - data["venda_milhoes"], 3)
    if abs(expected - data["saldo_milhoes"]) > 0.01:
        raise ValueError("Saldo nao confere com compra - venda.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Data inicial AAAA-MM-DD; padrao: hoje em Sao Paulo")
    parser.add_argument("--lookback-days", type=int, default=10)
    parser.add_argument("--max-age-days", type=int, default=10)
    parser.add_argument("--output", default=str(OUTFILE))
    args = parser.parse_args()

    start = date.fromisoformat(args.date) if args.date else datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    data = collect(start, args.lookback_days)
    validate(data, args.max_age_days)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
