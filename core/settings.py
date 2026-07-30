"""Feature flags lidas do ambiente (só stdlib).

Vive separado para que b3/decision.py e crypto/decision.py — ambos importados
pelos testes — leiam a mesma chave sem arrastar dependência nova para o CI.

Não chama load_dotenv(): quem executa o pipeline já carregou o .env antes
(main.py / crypto_main.py). No GitHub Actions a variável vem do bloco `env:`
do workflow.
"""

import os

_TRUTHY = {"1", "true", "on", "yes", "sim"}
_FALSY = {"0", "false", "off", "no", "nao", "não"}


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return default


def ai_pregate_enabled() -> bool:
    """True quando o pré-gate de RSI deve pular a chamada de IA.

    Ligado por padrão: economiza ~180 chamadas/dia no B3 e ~24 no cripto,
    auditando apenas sinais que o RSI ainda permite virar compra.

    Desligue (``AI_PREGATE=off``) durante janelas de **coleta de dados**. O
    pré-gate faz a IA rodar só em sinais tecnicamente favoráveis, o que produz
    amostra pequena e enviesada — inutilizável para calibrar o eixo `impact`,
    que precisa de casos bons E ruins para provar que separa.

    Ler a flag por chamada (em vez de constante de módulo) é intencional: deixa
    os testes alternarem o comportamento com monkeypatch do ambiente.
    """
    return _flag("AI_PREGATE", default=True)
