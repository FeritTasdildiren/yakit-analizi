# Predictor v5 — Backtest Raporu

**Tarih:** 2026-02-18
**Yakıt Tipleri:** benzin, motorin, lpg

## BENZIN

**Fold Sayısı:** 1

### Stage-1: Binary Classifier

| Metrik | Ortalama | Std |
|--------|----------|-----|
| AUC | 0.1341 | ±0.0000 |
| F1 | 0.0000 | ±0.0000 |
| PRECISION | 0.0000 | ±0.0000 |
| RECALL | 0.0000 | ±0.0000 |
| ACCURACY | 0.3333 | ±0.0000 |
| ECE | 0.6389 | ±0.0000 |

### Stage-2: Dual Regressor

**Pozitif Örnek Sayısı:** 4
**Stage-2 Fold Sayısı:** 1

| Metrik | Değer |
|--------|-------|
| mae_first_event | 7.593169 |
| rmse_first_event | 8.324758 |
| mae_net_amount | 9.200712 |
| rmse_net_amount | 9.583748 |
| directional_accuracy | 0.500000 |

### Fold Detayları

| Fold | Train | Test | AUC | F1 | Prec | Rec | ECE | Cal | S2 |
|------|-------|------|-----|----|----- |-----|-----|-----|------|
| 1 | 365 | 45 | 0.1341 | 0.0000 | 0.0000 | 0.0000 | 0.6389 | isotonic | OK |

---

## MOTORIN

**Fold Sayısı:** 1

### Stage-1: Binary Classifier

| Metrik | Ortalama | Std |
|--------|----------|-----|
| AUC | 0.2805 | ±0.0000 |
| F1 | 0.0000 | ±0.0000 |
| PRECISION | 0.0000 | ±0.0000 |
| RECALL | 0.0000 | ±0.0000 |
| ACCURACY | 0.6000 | ±0.0000 |
| ECE | 0.3858 | ±0.0000 |

### Stage-2: Dual Regressor

**Pozitif Örnek Sayısı:** 4
**Stage-2 Fold Sayısı:** 1

| Metrik | Değer |
|--------|-------|
| mae_first_event | 7.797562 |
| rmse_first_event | 8.914530 |
| mae_net_amount | 10.732216 |
| rmse_net_amount | 11.275209 |
| directional_accuracy | 0.500000 |

### Fold Detayları

| Fold | Train | Test | AUC | F1 | Prec | Rec | ECE | Cal | S2 |
|------|-------|------|-----|----|----- |-----|-----|-----|------|
| 1 | 365 | 45 | 0.2805 | 0.0000 | 0.0000 | 0.0000 | 0.3858 | isotonic | OK |

---

## LPG

**Fold Sayısı:** 1

### Stage-1: Binary Classifier

| Metrik | Ortalama | Std |
|--------|----------|-----|
| AUC | 0.6349 | ±0.0000 |
| F1 | 0.0000 | ±0.0000 |
| PRECISION | 0.0000 | ±0.0000 |
| RECALL | 0.0000 | ±0.0000 |
| ACCURACY | 0.8000 | ±0.0000 |
| ECE | 0.1884 | ±0.0000 |

### Stage-2: Dual Regressor

**Pozitif Örnek Sayısı:** 3
**Stage-2 Fold Sayısı:** 1

| Metrik | Değer |
|--------|-------|
| mae_first_event | 0.182328 |
| rmse_first_event | 0.182328 |
| mae_net_amount | 0.182328 |
| rmse_net_amount | 0.182328 |
| directional_accuracy | 1.000000 |

### Fold Detayları

| Fold | Train | Test | AUC | F1 | Prec | Rec | ECE | Cal | S2 |
|------|-------|------|-----|----|----- |-----|-----|-----|------|
| 1 | 365 | 45 | 0.6349 | 0.0000 | 0.0000 | 0.0000 | 0.1884 | platt | OK |

---
