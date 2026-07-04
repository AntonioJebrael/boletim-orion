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
- **Fluxo estrangeiro B3** — leitura via `data/fluxo-estrangeiro-b3.json` até a integração automática com endpoint estável da B3. O dado aparece no topo, no resumo executivo, no bloco Brasil/B3, na qualidade das fontes e no resumo Telegram; se o arquivo local não existir, o boletim marca explicitamente como pendente.

Ambos usam endpoints públicos não oficiais; se ficarem indisponíveis, o boletim degrada para o fallback e marca a fonte na tabela de qualidade.

### Sobrescritas locais opcionais

- `data/agenda-economica.json` — lista de até 3 eventos (`hora`, `regiao`, `evento`, `impacto`); usada quando o calendário do TradingView não retorna eventos.
- `data/curva-brasil.json` — objeto com `label`, `observacao` e opcionalmente `analise`/`direcao` para DI/curva Brasil. Quando a fonte TradingView está disponível, o boletim mostra níveis e variação diária dos vértices 2A/5A/10A e classifica a curva como abrindo, fechando, mista/torcida ou estável.
- `data/fluxo-estrangeiro-b3.json` — saldo estrangeiro divulgado pela B3, em milhões de reais. Exemplo:

```json
{
  "data": "2026-07-02",
  "saldo_milhoes": 1250.5,
  "fonte": "B3 - Participação dos investidores"
}
```

Quando essas fontes não existem, o boletim marca a fonte como fallback/pendente e reduz a convicção da leitura.

## Horário e gatilhos

O workflow pode ser disparado de três formas:

- **`repository_dispatch`** (recomendado) — gatilho externo preciso ao minuto, ideal para um cron de VPS chamando a API do GitHub às 07:35 BRT. Contorna o atraso do agendador do GitHub.
- **`schedule`** — `cron: '30 10 * * *'` (07:30 BRT), mantido como rede de segurança. O agendador do GitHub Actions é *best-effort* e pode atrasar de minutos a várias horas em horários de pico, então não é confiável para abertura de mercado.
- **`workflow_dispatch`** — execução manual pela aba **Actions → Run workflow**.

O envio ao Telegram espera até **08:00 BRT** quando o boletim termina antes desse horário.

### Disparar pela VPS (cron + API)

Na VPS do Orion, o token fica no `.env` da raiz do workspace e o script `/home/openclaw/.openclaw/workspace/scripts/trigger-boletim-orion-dispatch.sh` dispara o evento sem imprimir credenciais.

Crontab ativo/recomendado:

```cron
35 10 * * * /home/openclaw/.openclaw/workspace/scripts/trigger-boletim-orion-dispatch.sh >> /home/openclaw/.openclaw/workspace/logs/boletim-orion-dispatch.log 2>&1
```

A VPS está em UTC; `10:35 UTC = 07:35 America/Sao_Paulo`.
