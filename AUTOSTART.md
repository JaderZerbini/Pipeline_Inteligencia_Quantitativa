# Autostart — Terminal Quant com Windows

## Como ativar

1. Abra o `iniciar_pipeline.bat`
2. Escolha a opção **[5] Configurar autostart com Windows**
3. Autorize a execução como Administrador se solicitado
4. Pronto — na próxima vez que ligar o computador, o scheduler
   e o dashboard sobem automaticamente

## O que acontece após ativar

- O **scheduler** inicia e roda o pipeline cripto imediatamente,
  depois a cada 6 horas
- O **dashboard** inicia e fica disponível em http://localhost:8501
- Você não precisa abrir nenhum terminal

## Como verificar se está funcionando

Abra o PowerShell e rode:

```powershell
.\check_autostart.ps1
```

## Como desativar

Abra o `iniciar_pipeline.bat` e escolha a opção **[6] Remover autostart**

## Observação

O dashboard roda em modo headless (sem abrir janela de terminal).
Para ver os logs do scheduler, abra:

```
data\scheduler.log
data\crypto_pipeline.log
```
