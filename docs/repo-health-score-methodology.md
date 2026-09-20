# Repo Health Score Methodology

Каноническая research-методика, формулы, источники, calibration tables и pseudocode:

[spikes/scoring/README.md](../spikes/scoring/README.md) and [formula_lab.py](../spikes/scoring/formula_lab.py)

Результаты реальной калибровки по SourceCraft public sample, release gate и
ограничения измерений: [repo-health-score-calibration.md](repo-health-score-calibration.md).

Исправленный v2 category calibration с controlled fixtures, официальным
SonarQube live run, anchor checks и финальным readiness decision:
[category-score-calibration.md](category-score-calibration.md).

Этот entrypoint намеренно не изменяет production Score Engine. Эксперимент
воспроизводится командой `python spikes/scoring/formula_lab.py`.
