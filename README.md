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

## Horário

Cron atual: `55 10 * * *`, equivalente a **07:55 BRT**.
