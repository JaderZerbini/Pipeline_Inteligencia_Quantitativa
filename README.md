# Terminal Quant — Pipeline de Inteligência de Mercado (B3 + Cripto)

**Sistema de análise quantitativa combinando RSI/MA200, consenso multi-modelo (OpenRouter) e monitoramento macro para B3 e criptomoedas.**

---

## Arquitetura

### Pipeline B3

```
YFinance · Brapi · RSS (Valor/InfoMoney/Reuters)
           │
macro_monitor.py ──────────── BCB API (SELIC)
Brent · Minério · USD/BRL
           │
      db.py (SQLite)
 signals · audits · operations · paper_positions
           │
scanner_pro.py ──── RSI(14) + Volume guard + Price guard
                    + get_b3_historical_trend() (MA20/50/200 via yfinance 1y)
           │
sentiment_analyzer.py ── OpenRouter: DeepSeek(40%) · Llama(35%) · Gemini(25%)
Consenso 3 modelos · veto de manipulação · commodity_risk
           │ (thread assíncrona, deadline 22s)
decision_engine.py
Regras determinísticas + ajuste macro + gate MA200 + validação backtest
→ FORTE / MODERADO / AGUARDAR / BLOQUEADO
           │
alerts.py ─────────────────── Telegram (FORTE e MODERADO)
           │
monitor.py ─────────────────── Trailing stop 7% automático
           │
paper_trading.py ──────────── Simulador paper trading R$5k
                               evaluate_exit() via IA (saída inteligente)
```

### Pipeline Cripto

```
CoinGecko API (top-20 por volume + lista fixa)
           │
crypto_scanner.py ── RSI(14) + Volume guard + Galaxy Score simulado
                     + get_historical_trend() (MA20/50/200 via Binance klines)
           │
sentiment_analyzer.py ── mesmo consenso ponderado OpenRouter
           │
crypto_decision.py ── regras determinísticas + gate MA200
→ FORTE / MODERADO / AGUARDAR / BLOQUEADO
           │
alerts.py ─────────────────── Telegram (múltiplos chat_id suportados)
           │
crypto_main.py ─── orquestrador principal
crypto_scheduler.py ─ agendamento a cada 6h (automático)
paper_trading.py ─── mesma engine de paper trading
```

### Dashboard

```
app.py (Streamlit — 7 abas)
Scanner · Sinais · Operações · Backtesting · Validação · Cripto · Paper Trading
```

---

## Pré-requisitos

- Python 3.10+
- Conta OpenRouter (~$10 de créditos dura aproximadamente 5 meses neste volume)
- Google Gemini API key (fallback gratuito via AI Studio)
- Telegram bot criado via @BotFather e Chat ID do destino (suporta múltiplos IDs separados por vírgula)

---

## Instalação

1. Clone ou baixe o projeto:
   ```
   git clone <seu-repositorio>
   cd Pipeline_Inteligencia_Quantitativa
   ```

2. Crie e ative o ambiente virtual:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```

4. Configure as variáveis de ambiente:
   ```
   copy .env.example .env
   ```
   Abra `.env` e preencha cada valor com suas chaves reais.

5. Inicialize o banco de dados:
   ```
   python db.py
   ```

---

## Variáveis de Ambiente (.env)

| Variável                | Descrição                                                                          | Obrigatória |
|-------------------------|------------------------------------------------------------------------------------|-------------|
| `TELEGRAM_TOKEN`        | Token do bot Telegram (via @BotFather)                                             | Sim         |
| `TELEGRAM_CHAT_ID`      | ID(s) do chat — suporta múltiplos separados por vírgula: `111,222`                 | Sim         |
| `GEMINI_API_KEY`        | Chave Google Gemini — fallback quando OpenRouter falha                             | Sim         |
| `OPENROUTER_API_KEY`    | Chave OpenRouter — consenso 3 modelos de IA                                        | Sim         |
| `STOP_LOSS_PCT`         | Percentual do trailing stop (padrão: 0.07 = 7%)                                    | Não         |
| `GAIN_TARGET_PCT`       | Percentual de take profit no backtester (padrão: 0.15 = 15%)                       | Não         |
| `SCAN_INTERVAL_MINUTES` | Intervalo entre varreduras no modo contínuo (padrão: 30)                           | Não         |

---

## Como executar

### Pipeline B3

| Comando | O que faz |
|---------|-----------|
| `iniciar_pipeline.bat` ou `python main.py` | Pipeline completo — scanner, IA, decisão e alertas |
| `iniciar_dashboard.bat` ou `streamlit run app.py` | Dashboard Streamlit com as 7 abas |
| `python backtester.py` | Backtest histórico (730 dias · 16 ativos) |
| `python validator.py` | Diagnóstico de todas as camadas do sistema |
| `python macro_monitor.py` | Snapshot macro: Brent, Minério, USD/BRL, SELIC |
| `python test_telegram.py` | Confirma que o bot Telegram está configurado |

### Pipeline Cripto

| Comando | O que faz |
|---------|-----------|
| `python crypto_main.py` | Scan único de criptomoedas (CoinGecko + IA) |
| `python crypto_main.py --dry-run` | Scan sem enviar alertas Telegram |
| `python crypto_scheduler.py` | Scheduler automático a cada 6h |

### Autostart com Windows

| Comando | O que faz |
|---------|-----------|
| Opção `[5]` em `iniciar_pipeline.bat` | Registra pipeline e dashboard no Task Scheduler |
| Opção `[6]` em `iniciar_pipeline.bat` | Remove autostart do Windows |
| `.\check_autostart.ps1` | Verifica status das tasks agendadas |

Para detalhes do autostart, consulte `AUTOSTART.md`.

---

## Regras de Decisão (decision_engine.py / crypto_decision.py)

| Recomendação | RSI (14) | Volume ratio | Score IA efetivo | Condição extra         |
|--------------|----------|--------------|------------------|------------------------|
| BLOQUEADO    | qualquer | qualquer     | qualquer         | verdict == MANIPULACAO |
| FORTE        | < 30     | > 1.5x       | ≥ 70             | —                      |
| MODERADO     | < 38     | > 1.2x       | ≥ 55             | —                      |
| AGUARDAR     | outros   | outros       | outros           | —                      |

**BLOQUEADO é incondicional:** quando o auditor IA detecta manipulação (`verdict == MANIPULACAO` no B3, ou `MANIPULACAO / PUMP / FUD_COORDENADO` no cripto), o sistema bloqueia imediatamente, independente do score de confiança da IA ou de qualquer outro indicador. Nenhum gate posterior pode sobrescrever esse bloqueio.

**Ajuste macro:** quando `macro_ok = False` (score_adjustment ≤ −16), sinal FORTE é rebaixado para MODERADO.

**Score efetivo** = score do modelo (0–100) + `score_adjustment` do contexto macro, limitado ao intervalo [0, 100].

**Gate de backtest:** ativos fora de `BACKTEST_APPROVED` têm sinais MODERADO rebaixados automaticamente para AGUARDAR.

**Gate de tendência histórica (MA200):**
- Sinal bloqueado se preço estiver > 30% acima da MA200 (sobrecomprado no longo prazo)
- Sinal exige score IA ≥ 75 quando o ativo está em downtrend (abaixo da MA200)
- Campo `hist_context` incluído nos alertas Telegram e no Scanner do dashboard

**Saída inteligente por IA (paper trading):** `paper_trading.evaluate_exit()` avalia posições abertas usando IA e emite recomendações de saída com justificativa em português.

---

## Resultados do Backtest (730 dias · estratégia RSI)

| Classificação | Ativo | Win Rate | Sharpe |
|---------------|-------|----------|--------|
| ✅ Operar     | SBSP3 | 100%     | 1.43   |
| ✅ Operar     | VALE3 | 80%      | 1.06   |
| ✅ Operar     | ITUB4 | 60%      | 0.85   |
| ⚠️ Cautela    | PETR4 | 75%      | 1.01   |
| ⚠️ Cautela    | B3SA3 | 57%      | 0.66   |
| ⚠️ Cautela    | BBDC4 | 50%      | 0.60   |
| ❌ Evitar     | CSAN3 | —        | −0.84  |
| ❌ Evitar     | RENT3 | —        | −0.35  |
| ❌ Evitar     | WEGE3 | —        | −0.17  |
| ❌ Evitar     | SUZB3 | —        | −0.22  |

Critérios para "Operar": ≥ 5 trades históricos, win rate ≥ 55%, Sharpe ≥ 0.5.

---

## Modelos de IA (OpenRouter)

| Modelo                  | Peso | ID OpenRouter                           |
|-------------------------|------|-----------------------------------------|
| Qwen 2.5 7B Instruct    | 40%  | `qwen/qwen-2.5-7b-instruct`            |
| Meta Llama 3.3 70B      | 35%  | `meta-llama/llama-3.3-70b-instruct`    |
| Google Gemini 2.5 Flash | 25%  | `google/gemini-2.5-flash`              |

Custo estimado: ~R$ 1,50–2,50/mês no volume deste projeto.

**Fallback direto:** se todos os modelos OpenRouter falharem, `sentiment_analyzer.py` aciona o Gemini diretamente via `GEMINI_API_KEY` (modelo `gemini-2.5-flash-preview-05-20`) com timeout de 20s.

**Consenso:** média ponderada dos scores. Veto de manipulação: qualquer modelo com peso ≥ 30% pode forçar o veredicto final para `MANIPULACAO` e clampar o score a ≤ 25.

**Campo `commodity_risk`:** o prompt retorna `ALTO | MEDIO | BAIXO` para capturar impactos indiretos de commodities. No consenso, prevalece o nível mais pessimista entre os modelos.

---

## Limitações conhecidas

1. **Backtest otimista:** a simulação não incorpora custos de corretagem, slippage ou imposto de renda — os resultados históricos são melhores do que a realidade operacional.

2. **Proxy de minério de ferro:** usa VALE3.SA como proxy, não a commodity diretamente; o preço da ação responde a outros fatores além do minério.

3. **Preço atrasado no monitor:** `yf.Ticker.fast_info.last_price` pode estar atrasado até 15 minutos fora do pregão — o trailing stop não é adequado para operações intraday.

4. **Lista de tickers estática:** adicionar ou remover ativos exige edição manual de `scanner_pro.py`. Não há descoberta automática além do merge com o top-20 Brapi.

---

## Aviso de Risco

Este software é fornecido exclusivamente para fins educacionais e de pesquisa. Não constitui recomendação de investimento. O mercado de capitais envolve riscos de perda total do capital investido. Decisões de compra e venda são de responsabilidade exclusiva do investidor. Consulte um profissional certificado (CFP/CFA) antes de operar com capital real.
#   P i p e l i n e _ I n t e l i g e n c i a _ Q u a n t i t a t i v a  
 