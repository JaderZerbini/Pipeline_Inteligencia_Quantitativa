# Pipeline Inteligência Quantitativa B3 + Cripto

Scanner quantitativo (RSI/MA200) + consenso de 3 LLMs via OpenRouter para detectar
oportunidades em B3 e cripto e disparar alertas Telegram. Paper trading simulado em R$5k.

## Comandos

```bash
pytest tests/ -v                                 # 50 testes, só stdlib — CI usa requirements-ci.txt
python main.py                                   # pipeline B3 (scan único + alertas)
python crypto_main.py                            # pipeline cripto
python crypto_main.py --dry-run                  # scan sem enviar alertas
python -m streamlit run dashboard/app.py         # dashboard 7 abas
python crypto/scheduler.py                       # scheduler cripto contínuo (a cada 6h)
```

## Estrutura

| Pacote | Responsabilidade |
|--------|-----------------|
| `core/` | `db.py` (SQLite stdlib), `sentiment_analyzer.py` (consenso IA), `alerts.py`, `macro_monitor.py`, `position_sizing.py` |
| `b3/` | scanner, decision, monitor trailing stop, backtester, scheduler, validator |
| `crypto/` | scanner CoinGecko/Binance, decision, monitor, scheduler, backtester |
| `paper/` | engine de paper trading |
| `dashboard/` | Streamlit — `app.py` |
| `tests/` | 50 testes unitários das engines de decisão |

## Convenções críticas

**`b3/decision.py` não chama IA.** Recebe `audit` dict pronto como parâmetro — a chamada à
IA acontece upstream em `main.py` / `b3/engine.py`. Não adicione chamadas de IA dentro de
`b3/decision.py`.

**Imports pesados em `crypto/decision.py` são LAZY.** `sentiment_analyzer` puxa `dotenv` e
SDKs de IA. O import de `analyze_crypto` fica dentro da função `_call()` (não no topo do
módulo) para que a coleta de testes no CI não arraste essas dependências. Preserve esse padrão
em qualquer novo módulo que os testes importem.

**BLOQUEADO é incondicional e irrevogável.** Quando `verdict == "MANIPULACAO"` (B3) ou
`ai_veredicto in {"MANIPULACAO","PUMP","FUD_COORDENADO"}` (cripto), o engine retorna
BLOQUEADO imediatamente via `return` antecipado. Nenhum gate posterior (MA200, cooldown,
backtest) pode sobrescrever esse resultado.

## O que NÃO fazer

1. **Não adicione dependências a `requirements-ci.txt`** — só `pytest`. Qualquer import de
   `dotenv`, OpenAI, Gemini, ou Streamlit no topo de módulos importados pelos testes quebra
   a coleta no CI.
2. **Não mova o import de `analyze_crypto` para o topo de `crypto/decision.py`** — ele é
   intencionalmente lazy. Ver bug corrigido em [lazy import](crypto/decision.py#L88).
3. **Não edite `data/backtest_results.json` à mão** — é gerado por `scripts/backtest.py`.
   Edições manuais corrompem o gate de backtest de `b3/decision.py`.
4. **Não adicione lógica após o `return` de BLOQUEADO** — qualquer score ou gate que venha
   depois é código morto e indica regressão no fluxo de segurança.
5. **Não use `streamlit run app.py` na raiz** — o entry point é `dashboard/app.py`.
