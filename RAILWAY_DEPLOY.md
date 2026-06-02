# Deploy no Railway

## Primeira vez

1. Acesse [railway.app](https://railway.app) e abra seu projeto existente
2. Clique em **New Service** → **GitHub Repo**
3. Selecione `Pipeline_Inteligencia_Quantitativa`
4. Na aba **Variables**, adicione todas as variáveis do seu `.env`:
   - `OPENROUTER_API_KEY`
   - `GEMINI_API_KEY`
   - `TELEGRAM_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. Em **Settings** → **Volumes**, crie um volume:
   - Mount path: `/data`
   - Isso persiste o banco SQLite entre deploys e reinicializações
6. O Railway detecta o `Procfile` automaticamente e inicia o scheduler e o dashboard

## URL pública do dashboard

Após o deploy, Railway gera uma URL como:

```
https://terminal-quant-production.up.railway.app
```

Compartilhe com o Davi — ele terá acesso ao mesmo banco de dados em tempo real.

## Variáveis de ambiente no Railway

Nunca suba o `.env` para o GitHub.
Configure as variáveis diretamente no painel do Railway (aba Variables).

## Atualizar após commits

O Railway faz redeploy automaticamente a cada `git push` para `main`.
Não é necessário nenhum passo manual após o primeiro setup.

## Processos em execução

| Processo    | Comando                         | O que faz                                 |
|-------------|---------------------------------|-------------------------------------------|
| `web`       | `streamlit run app.py ...`      | Dashboard público com URL Railway         |
| `scheduler` | `python crypto_scheduler.py`    | Pipeline cripto a cada 6h em background   |

## Observação sobre banco local vs Railway

Ao migrar para Railway, o banco começa vazio na nuvem.
O histórico local fica na sua máquina.

Para migrar os dados históricos, use o Railway CLI:

```bash
railway run python -c "
import shutil, os
os.makedirs('/data', exist_ok=True)
shutil.copy('data/terminal_quant.db', '/data/terminal_quant.db')
print('Migração concluída')
"
```

## Autenticação no Railway

O dashboard usa autenticação simples via variáveis de ambiente — sem bcrypt, sem cookies, sem JWT.

No Railway → Variables, adicione:

| Variável | Valor |
|----------|-------|
| `AUTH_USER_1` | `jader` |
| `AUTH_PASS_1` | (sua senha) |
| `AUTH_USER_2` | `davi` |
| `AUTH_PASS_2` | (senha do Davi) |

As senhas ficam apenas no Railway (nunca no GitHub).

## Troubleshooting

- **Dashboard não abre**: verifique se a porta `$PORT` está sendo usada pelo Streamlit
- **Banco vazio após redeploy**: confirme que o volume `/data` está montado corretamente
- **Scheduler não dispara**: verifique logs em Railway → Deployments → Logs
- **Login não funciona**: verifique se `AUTH_USER_1`/`AUTH_PASS_1` estão configurados em Railway → Variables
