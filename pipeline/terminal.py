"""Maker-Checker 管道四种终态标识。"""


class Terminal:
    """四种终态。

    normal       — 正常通过 (Reviewer PASS → Gate PASS)
    challenged   — 带质疑通过 (Reviewer CHALLENGE → 追加 evidence)
    gate_override — Gate 硬覆盖 (SafetyGate BLOCK → urgent_care)
    forced_safe  — 强制安全兜底 (R2 REJECT → urgent_care, 跳过 Gate)
    """

    NORMAL:        str = "normal"
    CHALLENGED:    str = "challenged"
    GATE_OVERRIDE: str = "gate_override"
    FORCED_SAFE:   str = "forced_safe"
