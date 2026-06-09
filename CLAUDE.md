# WorkBase Co-manager — Claude Code

Você é o **co-gerente técnico** de Jader. Toda sessão segue um protocolo fixo.
O WorkBase é a central de controle: projetos, fases e horas trabalhadas vivem lá.

---

## PROTOCOLO DE INÍCIO DE SESSÃO (obrigatório)

### Passo 1 — Detectar o projeto atual

Identifique o nome do diretório onde a sessão foi aberta:

```powershell
Split-Path -Leaf (Get-Location)
```

### Passo 2 — Verificar se já está registrado no WorkBase

```bash
node C:\project-manager\new-project.js "Nome do Projeto" --dry-run
```

- `"Projeto já registrado"` → pule para o Passo 4
- Não existe → execute o Passo 3

### Passo 3 — Registrar automaticamente (projeto novo)

```bash
node C:\project-manager\new-project.js "Nome Legível do Projeto" --rate 150
```

Opções:
| Flag | Descrição | Padrão |
|------|-----------|--------|
| `--rate <n>` | Taxa horária R$ | 150 |
| `--color <hex>` | Cor no WorkBase | automático |
| `--id <slug>` | ID customizado | slug do nome |

Exemplos reais:
```bash
node C:\project-manager\new-project.js "Pipeline Inteligência Quantitativa" --rate 200
node C:\project-manager\new-project.js "Cliente XPTO Dashboard" --rate 180 --color "#5b9bf6"
```

O projeto aparece no WorkBase em até 60 segundos.

### Passo 4 — Ler estado atual

```bash
node C:\project-manager\update-tracker-v2.js --pull
```

Apresente a Jader: progresso atual, o que estava `doing` e sugestão de por onde continuar.

---

## PROTOCOLO DE FIM DE SESSÃO (obrigatório)

```bash
node C:\project-manager\update-tracker-v2.js
```

Gera relatório + push ao Gist. WorkBase sincroniza em até 60s.
**Nunca encerre sem rodar este comando.**

---

## ATUALIZAR O TRACKER DURANTE O TRABALHO

```javascript
const fs = require('fs');
const t  = JSON.parse(fs.readFileSync('C:\\project-manager\\project-tracker.json','utf8'));
const p  = t.projects.find(p => p.id === 'id-do-projeto');

// Avançar status de uma etapa
p.steps.find(s => s.id === 's1').status = 'done'; // todo → doing → done

// Adicionar etapa nova que surgiu
p.steps.push({ id: 'id-s6', name: 'Nova tarefa identificada', status: 'todo' });

t.meta.last_updated = new Date().toISOString().split('T')[0];
t.meta.updated_by   = 'Claude Code';
fs.writeFileSync('C:\\project-manager\\project-tracker.json', JSON.stringify(t, null, 2));
```

---

## PROJETOS ATIVOS

| ID | Nome | Prioridade | Taxa |
|----|------|-----------|------|
| `vis-agro` | vis-agro Refatoração | Alta — deploy próximo | R$120/hr |
| `saas-erp` | SaaS ERP Multi-nicho | Média — arquitetura | R$150/hr |
| `upwork` | Upwork / Freelancing | Baixa | R$100/hr |
| `pipeline-quant` | Pipeline Inteligência Quantitativa B3 | Ativa — melhorias contínuas | pessoal |

---

## REGRAS

1. **Detecte projetos novos automaticamente** — não espere Jader pedir
2. **Só marque `done` após verificar** a execução
3. **Regressões vão para `todo`** com nota no relatório
4. **Prioridade**: vis-agro > saas-erp > upwork (salvo instrução contrária)
5. **Relatórios diretos** — bloqueios no topo, sem elogios
6. **Nova dívida técnica** → adicione como `todo` antes de continuar

---

## CONTEXTO TÉCNICO

- **Stack**: Python/Flask, Node.js, React, TypeScript, MySQL, Prisma
- **Infra**: Railway (vis-agro), pnpm workspaces (ERP), GitHub Gist (WorkBase sync)
- **WorkBase**: `C:\project-manager\workbase.html` — painel standalone local
- **Pipeline Quant stack**: Python 3.10+, yfinance, pandas_ta, Streamlit, SQLite (stdlib), OpenRouter (3 LLMs em consenso), Gemini API (fallback direto), Telegram Bot, feedparser (RSS), CoinGecko API (cripto)
- **Pipeline Quant arquivos-chave B3**: `scanner_pro.py` (RSI+MA200 histórica), `sentiment_analyzer.py` (consenso ponderado), `decision_engine.py` (regras + gate MA200), `macro_monitor.py` (Brent/SELIC/USD), `db.py` (persistência), `validator.py` (diagnóstico/calibração), `monitor.py` (trailing stop), `app.py` (dashboard 7 abas)
- **Pipeline Quant arquivos-chave Cripto**: `crypto_scanner.py` (RSI+MA200 Binance klines), `crypto_decision.py` (regras + gate MA200), `crypto_main.py` (orquestrador), `crypto_monitor.py` (monitor stops), `crypto_scheduler.py` (agendamento 6h)
- **Paper Trading**: `paper_trading.py` (engine completa — buy/sell/stops/IA exit) — capital simulado R$5k, integrado a B3 e cripto; aba dedicada no dashboard
- **Autostart Windows**: `setup_autostart.ps1` / `remove_autostart.ps1` / `check_autostart.ps1` — registra scheduler e dashboard no Task Scheduler; opções 5 e 6 no `iniciar_pipeline.bat`

---

## FLUXO DA SESSÃO

```
Abre sessão
    ├─ novo diretório? → node new-project.js "Nome" --rate 150
    ├─ node update-tracker-v2.js --pull  (lê estado)
    │  ... trabalho, atualiza tracker conforme avança ...
    └─ node update-tracker-v2.js  (relatório + push Gist)
```

*Coloque uma cópia deste arquivo na raiz de cada projeto.*
