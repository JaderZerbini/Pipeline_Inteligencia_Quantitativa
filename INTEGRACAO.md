# Guia de integração — Módulo Cripto no Terminal Quant

## O que você vai adicionar

3 novos arquivos ao repositório existente:

```
Pipeline_Inteligência_Quantitativa/
├── crypto_scanner.py      ← NOVO: coleta Binance + LunarCrush
├── crypto_decision.py     ← NOVO: avalia sinais com IAs
├── crypto_main.py         ← NOVO: orquestrador
├── .github/
│   └── workflows/
│       └── crypto_pipeline.yml  ← NOVO: automação GitHub Actions
│
├── sentiment_analyzer.py  ← existente, sem alteração
├── alerts.py              ← existente, sem alteração
├── db.py                  ← existente, recebe nova tabela automaticamente
├── app.py                 ← existente (aba Cripto opcional — ver abaixo)
└── ... demais arquivos
```

---

## Passo 1 — Copiar os arquivos

Copie `crypto_scanner.py`, `crypto_decision.py` e `crypto_main.py`
para a raiz do seu projeto (junto com main.py, scanner_pro.py, etc.).

Crie a pasta `.github/workflows/` e copie o `crypto_pipeline.yml` para dentro.

---

## Passo 2 — Variável de ambiente nova

Adicione ao seu `.env` local:

```env
# LunarCrush — obtenha em https://lunarcrush.com/developers/api/authentication
# Tier gratuito: 2.000 créditos/dia (~16 chamadas/par por dia)
LUNARCRUSH_API_KEY=sua_chave_aqui
```

As demais variáveis (OPENROUTER_API_KEY, GEMINI_API_KEY, TELEGRAM_TOKEN,
TELEGRAM_CHAT_ID) já estão no seu .env do Terminal Quant. Não precisa duplicar.

---

## Passo 3 — Testar localmente primeiro

```bash
# Teste sem IA e sem Telegram (dry-run)
python crypto_main.py --dry-run

# Saída esperada:
# === INICIANDO PIPELINE CRIPTO ===
# Modo: DRY-RUN (sem Telegram/banco)
# [SCANNER] Coletando BTCUSDT...
# [SCANNER] BTCUSDT | preço=$98.500,00 | RSI=31.2 | galaxy=62 | positive
# ...
```

Se aparecer os dados dos pares, a integração com Binance está funcionando.

---

## Passo 4 — Configurar secrets no GitHub

Vá no seu repositório → **Settings → Secrets and variables → Actions**

Adicione os seguintes secrets (copie os valores do seu .env local):

| Secret | Valor |
|--------|-------|
| `OPENROUTER_API_KEY` | sk-or-... |
| `GEMINI_API_KEY` | AI... |
| `LUNARCRUSH_API_KEY` | sua chave |
| `TELEGRAM_TOKEN` | 123456:ABC... |
| `TELEGRAM_CHAT_ID` | seu chat ID |

---

## Passo 5 — Ativar o GitHub Actions

Faça commit e push dos 4 novos arquivos:

```bash
git add crypto_scanner.py crypto_decision.py crypto_main.py .github/workflows/crypto_pipeline.yml
git commit -m "feat: módulo cripto com GitHub Actions"
git push
```

Acesse a aba **Actions** no repositório para confirmar que o workflow aparece.
Para testar imediatamente: clique em "Run workflow" (botão manual disponível).

---

## Passo 6 — Aba Cripto no dashboard (opcional)

Para ver os sinais cripto no Streamlit, adicione ao `app.py` existente:

```python
# No bloco das abas, adicione "Cripto" à lista:
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Scanner", "Sinais", "Operações", "Backtesting", "Cripto"])

with tab5:
    st.subheader("Sinais Cripto")
    import pandas as pd
    from db import get_connection
    with get_connection() as conn:
        df = pd.read_sql(
            "SELECT symbol, decision, ai_score, rsi_1h, galaxy_score, sentiment, created_at "
            "FROM crypto_signals ORDER BY created_at DESC LIMIT 50",
            conn
        )
    if df.empty:
        st.info("Nenhum sinal cripto ainda. Rode python crypto_main.py para popular.")
    else:
        st.dataframe(df, use_container_width=True)
```

---

## Como os dois pipelines coexistem

| | Terminal Quant (B3) | Módulo Cripto |
|---|---|---|
| Quando roda | Durante pregão (10h–17h30) | 06h e 18h (GitHub Actions) |
| Onde roda | Sua máquina local | Servidores do GitHub (grátis) |
| Banco | terminal_quant.db | Mesma db — tabela crypto_signals |
| Telegram | Mesmo bot | Mesmo bot |
| IAs | OpenRouter (3 modelos) | OpenRouter (mesmos 3 modelos) |

---

## Custo adicional estimado

| Recurso | Custo |
|---------|-------|
| GitHub Actions | R$ 0 (2.000 min/mês gratuitos — usará ~20 min/mês) |
| LunarCrush API | R$ 0 (tier gratuito suficiente para 4 pares 2x/dia) |
| Binance dados públicos | R$ 0 (sem autenticação necessária) |
| OpenRouter (IAs) | ~R$ 0,50/mês adicional nos $10 existentes |

**Total adicional: praticamente zero.**
