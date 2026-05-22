import pandas as pd
import pandas_ta as ta
import yfinance as yf
import matplotlib.pyplot as plt

def rodar_backtest(ticker, capital_inicial=5000, trailing_stop=0.07):
    # 1. Download com auto_adjust para evitar problemas de dividendos
    df = yf.download(ticker + ".SA", period="2y", interval="1d", progress=False)
    
    # 2. RESOLUÇÃO DO ERRO: Achatar o MultiIndex das colunas
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # 3. Indicadores (usando pandas_ta)
    df['EMA_20'] = ta.ema(df['Close'], length=20)
    df['RSI'] = ta.rsi(df['Close'], length=14)
    
    # Remover NaNs iniciais dos indicadores para não quebrar o loop
    df = df.dropna(subset=['EMA_20', 'RSI']).copy()
    
    # 4. Lógica de Sinais (Booleana)
    df['Sinal'] = (df['Close'] > df['EMA_20']) & (df['RSI'] > 55)
    
    capital = capital_inicial
    posicao = 0 
    preco_entrada = 0
    maior_preco_desde_entrada = 0
    historico_capital = []

    for i in range(len(df)):
        preco_atual = df['Close'].iloc[i]
        sinal_compra = (df['Close'].iloc[i] > df['EMA_20'].iloc[i]) and (df['RSI'].iloc[i] > 55)
        
        # ENTRADA
        if sinal_compra and posicao == 0:
            posicao = capital / preco_atual
            capital = 0
            preco_entrada = preco_atual
            maior_preco_desde_entrada = preco_atual
            
        # GESTÃO DA POSIÇÃO (DURANTE A COMPRA)
        elif posicao > 0:
            # Atualiza o maior preço atingido para o Stop Móvel
            if preco_atual > maior_preco_desde_entrada:
                maior_preco_desde_entrada = preco_atual
            
            # Cálculo do Stop: Se cair X% do MAIOR preço atingido, cai fora
            valor_stop = maior_preco_desde_entrada * (1 - trailing_stop)
            
            # SAÍDA (Stop Móvel ou Preço abaixo da Média)
            if preco_atual < valor_stop or preco_atual < df['EMA_20'].iloc[i]:
                capital = posicao * preco_atual
                posicao = 0
                
        valor_total = capital if posicao == 0 else posicao * preco_atual
        historico_capital.append(valor_total)

    df['Equity_Curve'] = historico_capital
    retorno_final = ((historico_capital[-1] / capital_inicial) - 1) * 100
    
    return retorno_final, df

# --- EXECUÇÃO E GRÁFICO ---
ticker_teste = "PRIO3"
lucro, dados = rodar_backtest(ticker_teste)

print(f"\n--- RESULTADO BACKTEST {ticker_teste} (2 ANOS) ---")
print(f"Retorno Total: {lucro:.2f}%")
print(f"Patrimônio Final: R$ {dados['Equity_Curve'].iloc[-1]:.2f}")

# Plotar a evolução
plt.figure(figsize=(12,6))
plt.plot(dados.index, dados['Equity_Curve'], label='Evolução do Capital', color='green')
plt.axhline(y=5000, color='red', linestyle='--', label='Capital Inicial')
plt.title(f'Curva de Equity - Estratégia Momentum ({ticker_teste})')
plt.legend()
plt.grid(True)
plt.show()