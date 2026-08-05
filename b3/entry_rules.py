"""Regras de entrada isoladas, para o backtest medir a régua de produção.

O `b3/backtester.py` tinha a condição de entrada fixa no meio do laço de
simulação (`rsi < 38.0 and vol_ratio > 1.2`), então não dava para rodar a
mesma simulação com a tese de momentum do scanner sem editar o arquivo. Aqui
cada tese vira uma função pura injetável, e as duas ficam comparáveis na mesma
régua (mesmos tickers, mesmo período, mesma saída).

Só stdlib — sem pandas nem yfinance — para que o teste rode no CI com
requirements-ci.txt, mesmo padrão de `b3/freshness.py`.

**Estas regras cobrem só a parte técnica.** Os gates de compra de produção
também exigem score de auditoria da IA (>= 70 forte, >= 55 moderado), e o
backtest não simula auditoria. Retorno de qualquer simulação feita com elas é,
portanto, otimista em relação ao pipeline real.

Regras que existiram e foram removidas depois de responderem sua pergunta
(filtro de EMA, ADX, volume, união das duas teses) estão documentadas em
ESTRATEGIA.md, com os números que motivaram o descarte.
"""

from typing import NamedTuple

# Este módulo é o dono dos thresholds das regras de entrada. Ele é o único
# importável no CI (stdlib puro) e é importado tanto pelo `scanner` quanto pelo
# `decision` — deixar os números aqui é o que impede as duas pontas de
# divergirem de novo, que foi a origem do bug das faixas incompatíveis.

# Faixa de RSI da tese de MOMENTUM: preço subindo com força, mas ainda não
# esticado. É a régua de compra da produção desde a validação de 10 anos.
RSI_ENTRY_MIN = 55
RSI_ENTRY_MAX = 68

# Thresholds de volume relativo dos dois níveis de compra.
VOL_MIN_FORTE = 1.5
VOL_MIN_MODERADO = 1.2

# Teto de RSI da tese de REVERSÃO. Não é mais régua de produção — fica porque
# `reversao_moderado` segue sendo a base de comparação do momentum, e refazer
# essa conta é o que permite questionar a escolha sem reescrever o backtest.
RSI_MAX_MODERADO = 38

__all__ = [
    "Candle",
    "RSI_ENTRY_MAX",
    "RSI_ENTRY_MIN",
    "RSI_MAX_MODERADO",
    "VOL_MIN_FORTE",
    "VOL_MIN_MODERADO",
    "momentum",
    "reversao_moderado",
]


class Candle(NamedTuple):
    """Features de uma vela diária, o mínimo que as duas teses precisam.

    Assinatura única de propósito: as regras viram intercambiáveis e o
    backtester passa a aceitar qualquer uma sem saber qual está rodando.

    Attributes:
        price:        fechamento da vela.
        rsi:          RSI de 14 períodos.
        volume_ratio: volume / média móvel de 20 períodos do volume.
        ema20:        EMA de 20 períodos; None quando ainda não há histórico.
    """

    price: float
    rsi: float
    volume_ratio: float
    ema20: float | None = None


def momentum(c: Candle) -> bool:
    """Tese de momentum — a régua de compra da produção.

    Preço acima da EMA-20 com RSI na faixa de subida ainda não esticada. Não
    olha volume: o scanner também não.

    O filtro de EMA-20 é redundante na prática — em 19.474 velas, apenas 13
    tinham RSI entre 55 e 68 com preço abaixo da EMA. Mantido porque espelha
    exatamente a condição de `b3/scanner.py`, e o backtest precisa medir o que
    a produção emite, não uma versão simplificada.

    Sem EMA-20 devolve False — dado faltando nunca vira posição.
    """
    if c.ema20 is None:
        return False
    return c.price > c.ema20 and RSI_ENTRY_MIN < c.rsi < RSI_ENTRY_MAX


def reversao_moderado(c: Candle) -> bool:
    """Tese de reversão — a régua anterior, mantida como base de comparação.

    Comprar quem apanhou, apostando no repique. Foi a régua de produção até o
    backtest de 10 anos mostrar que o momentum ganha em retorno, em taxa de
    acerto e na cauda (ver ESTRATEGIA.md).

    Não é mais produção. Existe para que a escolha continue verificável: sem
    ela, questionar a troca exigiria reescrever o backtest.
    """
    return c.rsi < RSI_MAX_MODERADO and c.volume_ratio > VOL_MIN_MODERADO
