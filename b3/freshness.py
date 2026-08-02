"""Detecção de cotação velha (só stdlib — importável no CI).

`is_market_open()` conhece dia da semana e horário, mas não feriado da B3. Em
feriado o yfinance devolve o último pregão, e o pipeline trata a vela de
ontem como se fosse de hoje: gera sinal, busca notícia e paga auditoria de IA
sobre dado que não mudou. Repetido a cada 30 min, isso enche a base de
amostras duplicadas — justamente o que estraga a calibração do `impact`.

Vive em módulo próprio, sem pandas nem yfinance, para que o teste rode no CI
com requirements-ci.txt.
"""

from datetime import date, datetime


def is_stale(last_candle: date | None, now_brt: datetime, market_open: bool) -> bool:
    """True quando a última vela é velha demais para gerar sinal agora.

    Args:
        last_candle: data da última vela diária disponível.
        now_brt:     horário atual no fuso de São Paulo.
        market_open: resultado de ``is_market_open()`` — dia útil e dentro do
                     horário de pregão.

    Returns:
        True apenas quando o pregão deveria estar rodando e mesmo assim a vela
        mais recente é de um dia anterior. Com o mercado fechado o dado velho é
        o esperado (é o último pregão), então não é considerado obsoleto.
    """
    if last_candle is None:
        return True
    if not market_open:
        return False
    return last_candle < now_brt.date()
