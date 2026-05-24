# Boletim Orion — Abertura de Mercado

Boletim financeiro diário em HTML para abertura de mercado, com foco em opções, FIIs, câmbio, índice futuro e ações brasileiras.

## Arquivos principais

- `boletim-orion-template.html` — template visual do boletim.
- `boletim_orion/render_boletim.py` — gerador com dados públicos via Yahoo Finance.
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

## Horário

Cron atual: `55 10 * * *`, equivalente a **07:55 BRT**.
