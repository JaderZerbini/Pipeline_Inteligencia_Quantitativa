"""
position_sizing.py
------------------
Calcula o tamanho sugerido de posição com base no sinal e capital.

Regras:
  FORTE:    máximo 20% do capital disponível
  MODERADO: máximo 10% do capital disponível
  Nunca mais de 30% em um único ativo
  Nunca entra se já há 4 posições abertas

Estas são sugestões — a decisão final é sempre do usuário.
"""

MAX_POSITIONS = 4
ALLOCATION = {"FORTE": 0.20, "MODERADO": 0.10}
MAX_SINGLE = 0.30


def calculate_position(
    decision: str,
    capital: float,
    open_positions: int,
    price: float,
) -> dict:
    """
    Returns suggested position size for a signal.

    Args:
        decision:       "FORTE" or "MODERADO"
        capital:        total available capital in BRL or USD
        open_positions: number of currently open positions
        price:          current asset price

    Returns dict with:
        allowed:     bool — whether to enter at all
        reason:      str — explanation
        alloc_pct:   float — % of capital to allocate
        alloc_value: float — value in currency
        units:       float — number of units/shares to buy
    """
    if decision not in ALLOCATION:
        return {"allowed": False, "reason": "Sinal não acionável",
                "alloc_pct": 0, "alloc_value": 0, "units": 0}

    if open_positions >= MAX_POSITIONS:
        return {"allowed": False,
                "reason": f"Máximo de {MAX_POSITIONS} posições atingido",
                "alloc_pct": 0, "alloc_value": 0, "units": 0}

    pct = min(ALLOCATION[decision], MAX_SINGLE)
    value = round(capital * pct, 2)
    units = round(value / price, 6) if price > 0 else 0

    return {
        "allowed": True,
        "reason": f"{decision}: {pct*100:.0f}% do capital",
        "alloc_pct": pct,
        "alloc_value": value,
        "units": units,
    }
