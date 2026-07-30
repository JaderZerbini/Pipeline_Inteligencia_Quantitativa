"""Construção dos prompts enviados às IAs (só stdlib).

Vive separado de sentiment_analyzer.py de propósito: aquele módulo importa
dotenv e os SDKs de IA no topo, então os testes não podem tocá-lo sem arrastar
essas deps para o CI. Mesmo motivo de core/parsing.py existir.

O prompt do B3 recebe os indicadores técnicos junto da manchete. Sem eles a IA
julga a notícia no vácuo — sabe que houve um anúncio de dividendos, mas não que
o RSI está em 58 e o ativo está 12% acima da MA200, então não consegue dizer se
a notícia confirma ou contradiz o que o preço já mostra.
"""

# Campos técnicos injetados no prompt, na ordem de exibição.
# (chave no dict de entrada, rótulo, formatador)
_INDICATOR_FIELDS: list[tuple[str, str, str]] = [
    ("price",          "Preço",              "R$ {:.2f}"),
    ("rsi",            "RSI(14)",            "{:.1f}"),
    ("volume_ratio",   "Volume vs média",    "{:.2f}x"),
    ("pct_from_ma200", "Distância da MA200", "{:+.1f}%"),
    ("hist_trend",     "Tendência",          "{}"),
]


def _format_indicators(indicators: dict) -> str:
    """Renderiza os indicadores como linhas 'Rótulo: valor'.

    Campos ausentes viram N/A explícito em vez de desaparecerem — a IA precisa
    saber que o dado falta, senão preenche a lacuna por conta própria.
    """
    lines = []
    for key, label, fmt in _INDICATOR_FIELDS:
        value = indicators.get(key)
        if value is None:
            lines.append(f"- {label}: N/A")
            continue
        try:
            lines.append(f"- {label}: {fmt.format(value)}")
        except (TypeError, ValueError):
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def build_b3_audit_prompt(
    headline: str,
    ticker: str,
    indicators: dict | None = None,
) -> str:
    """Monta o prompt de auditoria de notícia para um ativo da B3.

    Args:
        headline:   Manchete (ou manchetes concatenadas) a auditar.
        ticker:     Ticker sem sufixo, ex. 'PETR4'.
        indicators: Opcional. Aceita as chaves price, rsi, volume_ratio,
                    pct_from_ma200 e hist_trend. Quando ausente ou vazio, o
                    prompt sai sem o bloco técnico — mantém o comportamento
                    antigo para chamadores como b3/validator.py.

    Returns:
        O prompt completo, incluindo o contrato JSON que b3/decision.py consome.
    """
    blocks = [
        "Você é um analista financeiro especializado em B3 e cadeias de "
        "suprimentos globais.",
        f'Analise as manchetes recentes sobre fatores que impactam o ativo '
        f'{ticker} e retorne APENAS JSON válido.',
        f'Manchetes: "{headline}"',
    ]

    if indicators:
        blocks.append(
            f"Indicadores técnicos atuais de {ticker}:\n"
            f"{_format_indicators(indicators)}"
        )
        blocks.append(
            "A manchete CONFIRMA, CONTRADIZ ou é IRRELEVANTE frente ao que "
            "esses indicadores mostram? Uma notícia positiva com o ativo já "
            "esticado acima da média tem menos margem de alta do que a mesma "
            "notícia com o ativo sobrevendido. Considere essa relação no score."
        )
        # Guard obrigatório: sem isto o modelo usa MANIPULACAO para expressar
        # "timing ruim", e MANIPULACAO dispara BLOQUEADO irrevogável no engine.
        blocks.append(
            "ATENÇÃO ao separar os dois eixos: o campo 'verdict' avalia APENAS "
            "a credibilidade da notícia em si. Indicadores técnicos "
            "desfavoráveis (ativo esticado, tendência de baixa, volume fraco) "
            "devem reduzir o 'score', mas NUNCA justificam "
            "verdict=MANIPULACAO. Use MANIPULACAO somente com evidência de "
            "manipulação na própria notícia — fonte duvidosa, promessa "
            "irreal, pump coordenado. Notícia legítima com timing técnico "
            "ruim é verdict=CONFIAVEL ou RUIDO com score baixo."
        )

    blocks.append(
        "Considere impactos INDIRETOS: guerras afetam commodities, que afetam "
        "margens das empresas. Eventos climáticos afetam oferta de "
        "matérias-primas. Decisões de bancos centrais afetam custo de capital."
    )
    blocks.append(
        "Retorne exatamente:\n"
        '{"score": <0-100>, "verdict": "<CONFIAVEL|RUIDO|MANIPULACAO>", '
        '"reason": "<uma frase sobre o impacto no ativo>", '
        '"commodity_risk": "<ALTO|MEDIO|BAIXO>", '
        '"flags": [<lista de fatores de risco identificados>]}'
    )
    blocks.append(
        "Score: 70-100=notícia fundamentada com impacto claro no ativo, "
        "40-69=impacto indireto ou incerto, 0-39=sem relação ou manipulação.\n"
        "Responda SOMENTE com o JSON."
    )

    return "\n\n".join(blocks)
