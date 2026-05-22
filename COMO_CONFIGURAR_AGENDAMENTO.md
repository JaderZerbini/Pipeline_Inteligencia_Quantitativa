# Como configurar início automático no Windows

## Pipeline (main.py) — roda durante o pregão
1. Abrir "Agendador de Tarefas" (Task Scheduler) no Windows
2. Criar Tarefa Básica → Nome: "Terminal Quant Pipeline"
3. Gatilho: Diariamente → Hora: 09:55 → Repetir a cada: 1 dia
4. Ação: Iniciar programa → `C:\Projetos\Pipeline_Inteligência_Quantitativa\iniciar_pipeline.bat`
5. Em "Condições": desmarcar "Iniciar somente se computador estiver na rede AC"
6. Criar segunda tarefa para encerrar às 18:00:
   - Ação: Iniciar programa → `taskkill /f /im python.exe`
   - Hora: 18:00

## Dashboard (app.py) — opcional, roda quando quiser ver
Execute manualmente: duplo clique em `iniciar_dashboard.bat`
Ou configure no Task Scheduler para iniciar com o Windows.

## Verificar logs
Pipeline: `data\pipeline.log`
Dashboard: `data\dashboard.log`
