"""Busca de manchetes relevantes para cada par de cripto.

Espelha o papel de b3/news_fetcher.py, que não tinha equivalente no cripto — as
IAs de cripto recebiam apenas números e não sabiam que Fed, ETF ou halving
existiam.

Os feeds combinam duas camadas:
  * específica do ativo (ex. ETF de Bitcoin, upgrade do Ethereum)
  * comum a todo cripto (Fed/juros, regulação, fluxo institucional), porque
    macro move o mercado inteiro junto com correlação alta entre os pares.

Importa core.rss (feedparser), então NÃO deve ser importado no topo de
crypto/decision.py — os testes carregam aquele módulo. Use no crypto_main.py.
"""

from core.rss import fetch_headlines

# Feeds comuns a qualquer par — macro e regulação movem o mercado inteiro.
_FEEDS_GERAIS: list[str] = [
    "https://news.google.com/rss/search?q=crypto+market+fed+interest+rates&hl=en&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=criptomoedas+regulacao+mercado&hl=pt-BR&gl=BR&ceid=BR:pt",
    "https://news.google.com/rss/search?q=crypto+ETF+institutional+inflow&hl=en&gl=US&ceid=US:en",
]

# Feeds por ativo, consultados antes dos gerais.
_FEEDS_POR_ATIVO: dict[str, list[str]] = {
    "BTCUSDT": [
        "https://news.google.com/rss/search?q=bitcoin+ETF+halving+price&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=bitcoin+preco+mercado&hl=pt-BR&gl=BR&ceid=BR:pt",
    ],
    "ETHUSDT": [
        "https://news.google.com/rss/search?q=ethereum+upgrade+staking+ETF&hl=en&gl=US&ceid=US:en",
    ],
    "BNBUSDT": [
        "https://news.google.com/rss/search?q=BNB+binance+regulation&hl=en&gl=US&ceid=US:en",
    ],
    "SOLUSDT": [
        "https://news.google.com/rss/search?q=solana+network+ETF+outage&hl=en&gl=US&ceid=US:en",
    ],
    "DEFAULT": [
        "https://news.google.com/rss/search?q={query}+crypto+price&hl=en&gl=US&ceid=US:en",
    ],
}

_MAX_HEADLINES = 5


def buscar_noticias_cripto(symbol: str) -> str:
    """Retorna manchetes recentes relevantes para o par.

    Args:
        symbol: Par no formato da Binance, ex. 'BTCUSDT'.

    Returns:
        "MANCHETES RECENTES: h1 | h2 | ..." ou uma mensagem de fallback.
        O formato espelha o do B3 para que o prompt trate os dois igual.
    """
    especificos = _FEEDS_POR_ATIVO.get(symbol, _FEEDS_POR_ATIVO["DEFAULT"])
    # Base do par sem o quote asset, usada no template DEFAULT: BTCUSDT -> BTC
    base = symbol[:-4] if symbol.endswith("USDT") else symbol

    headlines = fetch_headlines(
        especificos + _FEEDS_GERAIS,
        query=base,
        max_headlines=_MAX_HEADLINES,
    )

    if not headlines:
        return "Nenhuma notícia recente encontrada."

    return "MANCHETES RECENTES: " + " | ".join(headlines)
