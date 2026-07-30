"""Coleta genérica de manchetes via RSS.

A máquina de busca em b3/news_fetcher.py não tem nada de específico da B3 — só
o mapa de feeds tem. Este módulo isola a parte reutilizável para que o fetcher
de cripto não precise duplicá-la nem importar de dentro de b3/.

Importa feedparser, então NÃO deve ser importado por módulos que os testes
carregam (ver a nota sobre requirements-ci.txt no CLAUDE.md).
"""

import re
import urllib.parse

import feedparser

_MAX_PER_FEED = 2
_MAX_HEADLINES = 5
_SUMMARY_CHARS = 200


def strip_html(text: str) -> str:
    """Remove tags HTML e decodifica as entidades mais comuns."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)
    for entity, char in (
        ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
    ):
        clean = clean.replace(entity, char)
    return clean.strip()


def fetch_headlines(
    feeds: list[str],
    query: str = "",
    max_per_feed: int = _MAX_PER_FEED,
    max_headlines: int = _MAX_HEADLINES,
) -> list[str]:
    """Coleta manchetes de uma lista de feeds RSS.

    Args:
        feeds:         URLs de feed. Podem conter o placeholder ``{query}``.
        query:         Valor interpolado em ``{query}``, já url-encoded aqui.
        max_per_feed:  Máximo de entradas aproveitadas por feed.
        max_headlines: Corte global.

    Returns:
        Lista de manchetes ("título. resumo"), possivelmente vazia. Falha de
        feed individual é ignorada — um feed fora do ar não derruba a coleta.
    """
    headlines: list[str] = []
    encoded = urllib.parse.quote(query) if query else ""

    for template in feeds:
        if len(headlines) >= max_headlines:
            break
        url = template.format(query=encoded) if "{query}" in template else template
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = strip_html(entry.get("title", ""))
                summary = strip_html(entry.get("summary", ""))[:_SUMMARY_CHARS]
                text = f"{title}. {summary}" if summary else title
                if text:
                    headlines.append(text)
                if len(headlines) >= max_headlines:
                    break
        except Exception:
            continue

    return headlines
