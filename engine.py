import yfinance as yf
import time

class MarketData:
    def __init__(self, tickers):
        self.tickers = [t + ".SA" if not t.endswith(".SA") else t for t in tickers]
        
    def fetch_data_with_retry(self, period="1y", interval="1d", retries=3):
        """Busca dados com lógica de reconexão para evitar Timeouts"""
        for i in range(retries):
            try:
                data = yf.download(self.tickers, period=period, interval=interval, group_by='ticker', progress=False)
                if not data.empty:
                    return data
            except Exception as e:
                print(f"Tentativa {i+1} falhou para {self.tickers}: {e}")
                time.sleep(2) # Aguarda 2 segundos antes de tentar de novo
        return None