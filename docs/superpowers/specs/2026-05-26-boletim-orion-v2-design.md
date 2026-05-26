# Boletim Orion v2 — Design aprovado

## Contexto
O Boletim Orion já publica um HTML diário no GitHub Pages e envia link via Telegram. Tony descartou o BI/dashboard como pendência. A prioridade agora é aumentar confiabilidade, transparência das fontes e utilidade operacional.

## Escopo
1. Sanity check de dados de mercado obtidos via Yahoo Finance.
2. Agenda econômica com tentativa automática e fallback explícito.
3. Curva Brasil/DI com camada abstrata e fallback explícito enquanto fonte confiável não estiver disponível.
4. Checklist visível dos passes especialistas financeiros.
5. Telegram com resumo e alertas, não apenas link.
6. Histórico simples em GitHub Pages, sem BI.

## Fora de escopo
- Dashboard/BI separado.
- Recomendação de investimento.
- Dependência de APIs pagas ou tokens novos neste ciclo.

## Arquitetura
O gerador `boletim_orion/render_boletim.py` continuará sendo um script Python sem dependências externas. A lógica será organizada em funções pequenas:

- coleta Yahoo Finance;
- validação/sanity check por classe de ativo;
- leitura de agenda econômica;
- leitura/proxy de curva Brasil;
- cálculo dos vieses;
- análise especialista determinística;
- renderização HTML;
- geração de arquivos auxiliares para Telegram e histórico.

## Sanity check
Cada símbolo terá uma classe de ativo com limite de variação aceitável. Se a variação exceder o limite, o dado será marcado como suspeito, aparecerá com alerta no HTML e será excluído dos cálculos agregados de tom de mercado.

Limites iniciais:
- Índices globais/Brasil: ±5%.
- Futuros EUA: ±5%.
- Commodities: ±7%.
- Câmbio/DXY: ±3%.
- Ações brasileiras: ±15%.
- VIX: ±25%.
- Yields: ±8% de variação percentual do índice Yahoo.

## Agenda econômica
O script tentará carregar `data/agenda-economica.json` se existir. Se não existir, usará uma agenda-base de abertura com eventos monitoráveis e marcará status `Fallback`. Se a fonte automática falhar, o boletim dirá claramente que a agenda oficial não foi integrada.

## Curva Brasil / DI
O script tentará carregar `data/curva-brasil.json`. Se não existir, exibirá `Fonte não integrada` e reduzirá a confiança da leitura de FIIs/Crédito. A camada será preparada para troca futura por B3/ANBIMA.

## Checklist especialista
O HTML terá uma seção com os passes:
- Macro/Global;
- Brasil/B3;
- Opções & Derivativos;
- FIIs & Crédito;
- Gestor de Fundos/Risco;
- Editor do Boletim.

Cada item exibirá status, método e observação.

## Telegram
O workflow enviará `dist/telegram-summary.txt`, gerado pelo script, com:
- tom de mercado;
- drivers;
- nível de qualidade dos dados;
- principais alertas;
- link fixo do boletim.

## Histórico
O script gerará:
- `boletim-orion-YYYY-MM-DD.html`;
- `boletim-orion-latest.html`;
- `historico.html`, com links para arquivos HTML datados presentes em `dist`.

Como o GitHub Actions usa artefato novo a cada run, o histórico será limitado aos arquivos gerados no build atual até haver uma estratégia de persistência no repo ou Pages.

## Testes
- Executar `python3 -m py_compile boletim_orion/render_boletim.py`.
- Executar `python3 boletim_orion/render_boletim.py`.
- Validar que não sobram placeholders `{{...}}`.
- Validar criação de `telegram-summary.txt` e `historico.html`.
- Validar que dados suspeitos aparecem em alertas.

## Aprovação
Plano aprovado por Tony em 2026-05-26. BI/dashboard descartado por Tony.
