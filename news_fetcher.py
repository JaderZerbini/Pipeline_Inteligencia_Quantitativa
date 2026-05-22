"""Multi-feed news fetcher with commodity and macro context per ticker."""

import re
import feedparser
import urllib.parse


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode common entities from text."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.replace('&amp;', '&').replace('&lt;', '<')
    clean = clean.replace('&gt;', '>').replace('&quot;', '"')
    clean = clean.replace('&#39;', "'").replace('&nbsp;', ' ')
    return clean.strip()

# Per-ticker RSS feeds ordered by relevance.
# DEFAULT template uses {ticker} placeholder.
COMMODITY_FEEDS: dict[str, list[str]] = {
    "PETR4": [
        "https://feeds.reuters.com/reuters/businessNews",
        "https://www.investing.com/rss/news_285.rss",
        "https://news.google.com/rss/search?q=petroleo+opep+brent&hl=pt-BR&gl=BR&ceid=BR:pt",
        "https://news.google.com/rss/search?q=oil+OPEC+crude&hl=en&gl=US&ceid=US:en",
    ],
    "PRIO3": [
        "https://news.google.com/rss/search?q=petroleo+pre-sal+offshore+brazil&hl=pt-BR",
        "https://news.google.com/rss/search?q=oil+offshore+brazil&hl=en",
    ],
    "VALE3": [
        "https://news.google.com/rss/search?q=minerio+ferro+china+aco&hl=pt-BR&gl=BR",
        "https://news.google.com/rss/search?q=iron+ore+china+steel+demand&hl=en",
        "https://news.google.com/rss/search?q=PMI+china+industrial&hl=en",
    ],
    "ITUB4": [
        "https://news.google.com/rss/search?q=selic+banco+central+juros+brasil&hl=pt-BR",
        "https://news.google.com/rss/search?q=inflacao+ipca+brasil&hl=pt-BR",
    ],
    "BBDC4": [
        "https://news.google.com/rss/search?q=selic+banco+central+juros+brasil&hl=pt-BR",
    ],
    "WEGE3": [
        "https://news.google.com/rss/search?q=energia+renovavel+eolica+solar+brasil&hl=pt-BR",
        "https://news.google.com/rss/search?q=motores+industria+exportacao+weg&hl=pt-BR",
    ],
    "SUZB3": [
        "https://news.google.com/rss/search?q=celulose+papel+exportacao+brasil&hl=pt-BR",
        "https://news.google.com/rss/search?q=pulp+cellulose+market+price&hl=en",
    ],
    "DEFAULT": [
        "https://news.google.com/rss/search?q={ticker}+acao+bolsa+brasil&hl=pt-BR",
    ],
}

_MAX_PER_FEED  = 2
_MAX_HEADLINES = 5


def buscar_noticias_ticker(ticker: str) -> str:
    """Fetch up to 5 headlines from sector-relevant RSS feeds for ticker.

    Uses COMMODITY_FEEDS mapping to pick feeds that capture upstream
    commodity / macro events before they appear in company-specific news.

    Returns:
        "MANCHETES RECENTES: h1 | h2 | ..." or a fallback message.
    """
    feeds    = COMMODITY_FEEDS.get(ticker, COMMODITY_FEEDS["DEFAULT"])
    headlines: list[str] = []

    for url_template in feeds:
        if len(headlines) >= _MAX_HEADLINES:
            break
        url = url_template.format(ticker=urllib.parse.quote(ticker))
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:_MAX_PER_FEED]:
                title   = _strip_html(entry.get("title", ""))
                summary = _strip_html(entry.get("summary", ""))[:200]
                text    = f"{title}. {summary}" if summary else title
                if text:
                    headlines.append(text)
                if len(headlines) >= _MAX_HEADLINES:
                    break
        except Exception:
            continue

    if not headlines:
        return "Nenhuma notícia recente encontrada."

    return "MANCHETES RECENTES: " + " | ".join(headlines)
