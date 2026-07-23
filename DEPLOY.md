# Deploy — Streamlit Cloud + GitHub Actions + Supabase

Este projeto migrou do **Railway** (que rodava tudo num único container 24/7)
para uma arquitetura sem servidor próprio:

| Componente            | Onde roda            | O que faz                                            |
|-----------------------|----------------------|------------------------------------------------------|
| Dashboard (`dashboard/app.py`) | **Streamlit Community Cloud** | UI das 7 abas, lê o banco                |
| Pipeline B3 (`main.py`)        | **GitHub Actions** (`b3_pipeline.yml`)    | Scan a cada 30 min no pregão |
| Pipeline Cripto (`crypto_main.py`) | **GitHub Actions** (`crypto_pipeline.yml`) | Scan 2x/dia            |
| Banco de dados        | **Supabase (PostgreSQL)** | Persistência compartilhada entre todos os processos |

O código escolhe o backend automaticamente: se a variável de ambiente
`DATABASE_URL` estiver definida, usa PostgreSQL; caso contrário, cai no SQLite
local (`data/terminal_quant.db`). Veja `core/db.py`.

---

## 0. A connection string do Supabase (LEIA PRIMEIRO)

No painel do Supabase: **Settings → Database → Connection string**.
Há duas opções — e a escolha importa:

- **Direct connection** — `db.<ref>.supabase.co:5432`
  Servida apenas por **IPv6**. Funciona da maioria das máquinas locais, mas
  **NÃO funciona no GitHub Actions** (runners são IPv4-only) e pode falhar no
  Streamlit Cloud.

- **Connection pooler (recomendado)** — `aws-0-<region>.pooler.supabase.com`
  Compatível com **IPv4**. Usuário no formato `postgres.<ref>`.
  - **Transaction pooler** (porta `6543`) — ideal para este projeto, que abre e
    fecha conexões a cada operação.
  - **Session pooler** (porta `5432`) — também funciona.

> ✅ **Use a string do _pooler_ (IPv4) como `DATABASE_URL`** tanto no GitHub
> Actions quanto no Streamlit Cloud. Reserve a _direct connection_ para testes
> locais. O formato é:
>
> ```
> postgresql://postgres.<ref>:<SENHA>@aws-0-<region>.pooler.supabase.com:6543/postgres
> ```

A senha do banco está em **Settings → Database → Database password**
(é possível redefinir ali se necessário).

---

## 1. Provisionar as tabelas no Supabase

Já foi feito uma vez via `scripts/setup_supabase.py`, mas é idempotente
(`CREATE TABLE IF NOT EXISTS`) e pode rodar de novo:

```powershell
# PowerShell
$env:DATABASE_URL = "postgresql://postgres.<ref>:<SENHA>@aws-0-<region>.pooler.supabase.com:6543/postgres"
python scripts/setup_supabase.py
```

```bash
# bash
DATABASE_URL="postgresql://..." python scripts/setup_supabase.py
```

O script lê o `schema.sql` e imprime `OK` para cada tabela/índice criado.

---

## 2. Deploy do dashboard no Streamlit Community Cloud

1. Faça push do repositório para o GitHub.
2. Em [share.streamlit.io](https://share.streamlit.io) → **New app**.
3. Configure:
   - **Repository**: este repositório
   - **Branch**: `main`
   - **Main file path**: `dashboard/app.py`
   - **Python version**: 3.12
   - As dependências vêm do `requirements.txt` na raiz (já inclui `streamlit`,
     `psycopg2-binary` e tudo mais).
4. Clique em **Advanced settings → Secrets** e cole (formato TOML):

   ```toml
   DATABASE_URL = "postgresql://postgres.<ref>:<SENHA>@aws-0-<region>.pooler.supabase.com:6543/postgres"
   OPENROUTER_API_KEY = "..."
   GEMINI_API_KEY = "..."
   TELEGRAM_TOKEN = "..."
   TELEGRAM_CHAT_ID = "..."
   ```

   O Streamlit Cloud expõe esses secrets também como **variáveis de ambiente**,
   então `core/db.py` (que lê `os.getenv("DATABASE_URL")`) detecta o PostgreSQL
   automaticamente. As mesmas chaves podem ser configuradas localmente em
   `.streamlit/secrets.toml` (já está no `.gitignore`) ou no `.env`.

5. **Deploy**. O dashboard passa a ler o mesmo banco que os pipelines do Actions
   alimentam.

> O dashboard é somente leitura/visualização — quem grava sinais são os
> workflows do GitHub Actions. Se o dashboard abrir vazio, confirme que o
> `DATABASE_URL` está nos secrets (sem ele, o app cai no SQLite local, que no
> Streamlit Cloud está sempre vazio).

---

## 3. Secrets do GitHub Actions

Em **Settings → Secrets and variables → Actions → New repository secret**,
adicione:

| Secret                | Usado por                              | Obrigatório |
|-----------------------|----------------------------------------|-------------|
| `DATABASE_URL`        | `b3_pipeline.yml`, `crypto_pipeline.yml` | **Sim** (novo) |
| `OPENROUTER_API_KEY`  | ambos os pipelines                     | Sim         |
| `GEMINI_API_KEY`      | ambos os pipelines                     | Sim         |
| `TELEGRAM_TOKEN`      | ambos os pipelines                     | Sim         |
| `TELEGRAM_CHAT_ID`    | ambos os pipelines                     | Sim         |
| `LUNARCRUSH_API_KEY`  | apenas `crypto_pipeline.yml`           | Opcional    |

`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` e
`LUNARCRUSH_API_KEY` já eram usados pelo `crypto_pipeline.yml`. **O único secret
novo é o `DATABASE_URL`** — adicione-o para que ambos os pipelines gravem no
Supabase em vez de num SQLite efêmero (que era descartado ao fim de cada job).

### Workflows

- **`.github/workflows/b3_pipeline.yml`** (novo) — cron `*/30 13-20 * * 1-5`
  (a cada 30 min, 13–20 UTC = 10h–17h BRT, seg–sex; o Actions usa sempre UTC).
- **`.github/workflows/crypto_pipeline.yml`** — cron 2x/dia (09:00 e 21:00 UTC).

Ambos podem ser disparados manualmente em **Actions → (workflow) → Run workflow**.

---

## 4. O que NÃO é mais usado

Os arquivos abaixo eram específicos do Railway e **não têm mais função** nesta
arquitetura. Podem ser mantidos por histórico ou removidos:

- **`Procfile`** (`web: python start.py`) — era o entrypoint do Railway.
- **`start.py`** — supervisor que subia dashboard + schedulers no mesmo
  container 24/7. Esse modelo (3 processos em loop infinito) era justamente o
  que consumia as horas do plano gratuito. Agora:
  - o dashboard roda no Streamlit Cloud;
  - os scans rodam por cron no GitHub Actions;
  - **não há mais processo permanente**, logo `start.py`, `railway.toml` e os
    schedulers locais (`b3/scheduler.py`, `crypto/scheduler.py`) deixam de ser
    necessários em produção.
- **`railway.toml`** — configuração de build/deploy do Railway.

> Os schedulers (`b3/scheduler.py`, `crypto/scheduler.py`) continuam úteis se
> você quiser rodar o pipeline localmente em loop, mas não participam do deploy.

---

## 5. Segurança

- **Nunca** faça commit da `DATABASE_URL` ou de chaves de API. O `.env` e o
  `.streamlit/secrets.toml` já estão no `.gitignore`.
- Como a senha do banco pode ter circulado fora dos cofres de secrets (chat,
  histórico de terminal), considere **redefini-la** em
  Settings → Database → Database password e atualizar os secrets.
