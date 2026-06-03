# Boletim Orion — Abertura de Mercado

Boletim financeiro diário em HTML para abertura de mercado, com foco em opções, FIIs, câmbio, índice futuro e ações brasileiras.

## Arquivos principais

- `boletim-orion-template.html` — template visual do boletim.
- `boletim_orion/render_boletim.py` — gerador com cotações via TradingView (fonte principal, variação diária na origem) e Yahoo Finance como fallback, agenda econômica via calendário do TradingView, sanity check, checklist de especialistas, histórico simples e resumo Telegram.
- `.github/workflows/boletim-orion-daily.yml` — automação diária, publicação no GitHub Pages e envio Telegram.

## Publicação

O GitHub Actions gera os arquivos em `dist/` e publica via GitHub Pages.

URLs esperadas após configurar Pages:

- Página inicial: `https://SEU_USUARIO.github.io/NOME_DO_REPO/`
- Boletim mais recente: `https://SEU_USUARIO.github.io/NOME_DO_REPO/boletim-orion-latest.html`

## Secrets opcionais para envio Telegram

Configurar no repositório em **Settings → Secrets and variables → Actions**:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Se os secrets não existirem, o boletim é publicado normalmente, mas o Telegram não é enviado.

## Fontes de dados

- **Cotações** — TradingView scanner (`scanner.tradingview.com`) como fonte principal: uma requisição em lote traz o preço e a variação diária já calculada na origem. Quando algum símbolo falha, o Yahoo Finance Chart API assume como fallback símbolo a símbolo.
- **Agenda econômica** — calendário do TradingView (`economic-calendar.tradingview.com`), priorizando eventos de importância alta/média (BR, EUA, Zona do Euro, China, Japão), com horários convertidos para BRT.

Ambos usam endpoints públicos não oficiais; se ficarem indisponíveis, o boletim degrada para o fallback e marca a fonte na tabela de qualidade.

### Sobrescritas locais opcionais

- `data/agenda-economica.json` — lista de até 3 eventos (`hora`, `regiao`, `evento`, `impacto`); usada quando o calendário do TradingView não retorna eventos.
- `data/curva-brasil.json` — objeto com `label` e `observacao` para DI/curva Brasil (ainda pendente de integração automática B3/ANBIMA).

Quando essas fontes não existem, o boletim marca a fonte como fallback/pendente e reduz a convicção da leitura.

## Horário e gatilhos

O workflow pode ser disparado de três formas:

- **`repository_dispatch`** (recomendado) — gatilho externo preciso ao minuto, ideal para um cron de VPS chamando a API do GitHub às 07:50 BRT. Contorna o atraso do agendador do GitHub.
- **`schedule`** — `cron: '50 10 * * *'` (07:50 BRT), mantido como rede de segurança. O agendador do GitHub Actions é *best-effort* e pode atrasar de minutos a várias horas em horários de pico, então não é confiável para abertura de mercado.
- **`workflow_dispatch`** — execução manual pela aba **Actions → Run workflow**.

### Disparar pela VPS (cron + API)

1. Gere um **fine-grained PAT** com escopo apenas neste repositório e permissão **Contents: Read and write**.
2. Guarde o token na VPS (ex.: variável de ambiente `GH_TOKEN`).
3. Adicione ao crontab (ajuste o fuso da VPS):

```cron
# VPS em America/Sao_Paulo → 07:50 BRT
50 7 * * * curl -sS -X POST -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" https://api.github.com/repos/AntonioJebrael/boletim-orion/dispatches -d '{"event_type":"boletim-orion"}'

# VPS em UTC → use 50 10 * * *
```

Confira o fuso da VPS com `timedatectl`.
