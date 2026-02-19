#!/usr/bin/env python3
"""TASK-059: Tam veri backtest (2022-01-01 ~ 2026-02-18), 3 yakıt"""
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from src.predictor_v5.backtest import run_backtest, generate_backtest_report
from datetime import date

fuels = ["benzin", "motorin", "lpg"]
results = {}

for fuel in fuels:
    print(f"\n{'='*60}")
    print(f"{fuel.upper()} FULL backtest (2022-01-01 ~ 2026-02-18)")
    print(f"{'='*60}")
    try:
        result = run_backtest(fuel, start_date=date(2022, 1, 1), end_date=date(2026, 2, 18))
        results[fuel] = result

        s1 = result.get("stage1", {})
        s2 = result.get("stage2", {})
        
        print(f"\n--- {fuel.upper()} Stage-1 (n_folds={result.get('n_folds', 0)}) ---")
        print(f"  AUC:       {s1.get('auc_mean', 0):.4f} +/- {s1.get('auc_std', 0):.4f}")
        print(f"  F1:        {s1.get('f1_mean', 0):.4f} +/- {s1.get('f1_std', 0):.4f}")
        print(f"  Precision: {s1.get('precision_mean', 0):.4f} +/- {s1.get('precision_std', 0):.4f}")
        print(f"  Recall:    {s1.get('recall_mean', 0):.4f} +/- {s1.get('recall_std', 0):.4f}")
        print(f"  Accuracy:  {s1.get('accuracy_mean', 0):.4f} +/- {s1.get('accuracy_std', 0):.4f}")
        print(f"  ECE:       {s1.get('ece_mean', 0):.6f} +/- {s1.get('ece_std', 0):.6f}")

        if not s2.get("skipped"):
            print(f"\n--- {fuel.upper()} Stage-2 ---")
            print(f"  MAE first_event:   {s2.get('mae_first_event_mean', 0):.4f}")
            print(f"  RMSE first_event:  {s2.get('rmse_first_event_mean', 0):.4f}")
            print(f"  MAE net_3d:        {s2.get('mae_net_amount_mean', 0):.4f}")
            print(f"  RMSE net_3d:       {s2.get('rmse_net_amount_mean', 0):.4f}")
            print(f"  Dir accuracy:      {s2.get('directional_accuracy_mean', 0):.4f}")
            print(f"  Pos samples:       {s2.get('n_positive_samples', 0)}")
            print(f"  S2 folds:          {s2.get('n_folds_with_stage2', 0)}")
        else:
            reason = s2.get("reason", "N/A")
            print(f"\n--- {fuel.upper()} Stage-2: SKIPPED ({reason})")

        for fd in result.get("fold_details", []):
            s1f = fd.get("stage1", {})
            cal = fd.get("calibration_method", "?")
            s2s = "OK" if fd.get("stage2") else "SKIP"
            print(f"  Fold {fd['fold']}: AUC={s1f.get('auc',0):.4f} F1={s1f.get('f1',0):.4f} "
                  f"ECE={s1f.get('ece',0):.4f} Cal={cal} Train={fd['train_size']} Test={fd['test_size']} S2={s2s}")

    except Exception as e:
        print(f"HATA: {fuel} - {e}")
        import traceback
        traceback.print_exc()

if results:
    report = generate_backtest_report(results)
    with open("/var/www/yakit_analiz/backtest_report_full.md", "w") as f:
        f.write(report)
    print(f"\nRapor: /var/www/yakit_analiz/backtest_report_full.md")
