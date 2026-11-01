"""Tiny G-code parser used by the safety tests."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Cmd:
    """One G-code command: name such as 'G1', parameters as floats, and the source line number."""

    name: str
    params: dict[str, float]
    line_no: int


def parse(gcode: str) -> list[Cmd]:
    """Parse G-code into commands, dropping comments and blank lines."""
    cmds: list[Cmd] = []
    for n, line in enumerate(gcode.splitlines(), 1):
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        name, *rest = code.split()
        if name.upper() == "M1002":  # Bambu status claim with a text argument (e.g. gcode_claim_action : 0): no numbers
            rest = []
        params = {tok[0].upper(): float(tok[1:]) if len(tok) > 1 else 0.0 for tok in rest}
        cmds.append(Cmd(name.upper(), params, n))
    return cmds
