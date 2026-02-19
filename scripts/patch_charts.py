#!/usr/bin/env python3
"""
Patch script to update charts.py on the server.
Adds/replaces the `create_v5_prediction_history` function.

Changes:
1. Splits dataframe into backfill (model_version == "v5-backfill") and real data
2. Backfill data: DASHED line, lower opacity (0.6), purple color (#9333EA)
3. Real data: SOLID line, normal opacity, blue color (#3B82F6)
4. Legend: "Backfill Simulasyon" and "Gercek Tahmin"
5. first_event_amount bars with lighter color for backfill
6. Threshold lines at 55% and 50%
7. Graceful fallback when model_version column doesn't exist

Usage:
    cd /var/www/yakit_analiz
    .venv/bin/python scripts/patch_charts.py
    .venv/bin/python scripts/patch_charts.py --dry-run   # sadece kontrol
"""

import argparse
import sys

CHARTS_PATH = "/var/www/yakit_analiz/dashboard/components/charts.py"

# The new function to add/replace
NEW_FUNCTION = '''

def create_v5_prediction_history(df: pd.DataFrame, fuel_type: str = ""):
    """
    Predictor v5 tahmin gecmisi grafigi.

    Backfill ve gercek tahminleri ayri renk/stil ile gosterir.
    - Backfill (model_version == "v5-backfill"): kesikli cizgi, mor (#9333EA), opacity 0.6
    - Gercek (model_version != "v5-backfill"): duz cizgi, mavi (#3B82F6), opacity 1.0
    - first_event_amount bar chart: backfill icin acik renk
    - Esik cizgileri: %55 (alarm) ve %50 (dikkat)
    """
    if df.empty:
        return go.Figure()

    fig = go.Figure()

    # model_version kolonu yoksa tum veriyi gercek say
    has_version = "model_version" in df.columns

    if has_version:
        df_backfill = df[df["model_version"] == "v5-backfill"].copy()
        df_real = df[df["model_version"] != "v5-backfill"].copy()
    else:
        df_backfill = pd.DataFrame()
        df_real = df.copy()

    # ── 1. Stage-1 Probability cizgileri ──

    # Backfill: kesikli mor cizgi
    if not df_backfill.empty and "stage1_probability" in df_backfill.columns:
        fig.add_trace(go.Scatter(
            x=df_backfill["date"],
            y=df_backfill["stage1_probability"],
            mode="lines",
            name="Backfill Simulasyon",
            line=dict(color="#9333EA", width=2, dash="dash"),
            opacity=0.6,
            hovertemplate=(
                "<b>%{x|%d %b}</b><br>"
                "Olasilik: %{y:.1%}<br>"
                "<i>(Backfill Simulasyon)</i>"
                "<extra></extra>"
            ),
        ))

    # Gercek: duz mavi cizgi
    if not df_real.empty and "stage1_probability" in df_real.columns:
        fig.add_trace(go.Scatter(
            x=df_real["date"],
            y=df_real["stage1_probability"],
            mode="lines+markers",
            name="Gercek Tahmin",
            line=dict(color="#3B82F6", width=2.5),
            marker=dict(size=5, color="#3B82F6"),
            opacity=1.0,
            hovertemplate=(
                "<b>%{x|%d %b}</b><br>"
                "Olasilik: %{y:.1%}<br>"
                "<i>(Gercek Tahmin)</i>"
                "<extra></extra>"
            ),
        ))

    # ── 2. first_event_amount bar chart ──

    # Backfill barlar: acik mor
    if not df_backfill.empty and "first_event_amount" in df_backfill.columns:
        df_bf_nonzero = df_backfill[df_backfill["first_event_amount"].abs() > 0.001]
        if not df_bf_nonzero.empty:
            colors_bf = [
                "rgba(239, 68, 68, 0.3)" if v > 0 else "rgba(34, 197, 94, 0.3)"
                for v in df_bf_nonzero["first_event_amount"]
            ]
            fig.add_trace(go.Bar(
                x=df_bf_nonzero["date"],
                y=df_bf_nonzero["first_event_amount"],
                name="Backfill Ilk Hareket",
                marker_color=colors_bf,
                yaxis="y2",
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "Ilk Hareket: %{y:+.2f} TL<br>"
                    "<i>(Backfill)</i>"
                    "<extra></extra>"
                ),
                showlegend=False,
            ))

    # Gercek barlar: dolu renk
    if not df_real.empty and "first_event_amount" in df_real.columns:
        df_r_nonzero = df_real[df_real["first_event_amount"].abs() > 0.001]
        if not df_r_nonzero.empty:
            colors_real = [
                "rgba(239, 68, 68, 0.8)" if v > 0 else "rgba(34, 197, 94, 0.8)"
                for v in df_r_nonzero["first_event_amount"]
            ]
            fig.add_trace(go.Bar(
                x=df_r_nonzero["date"],
                y=df_r_nonzero["first_event_amount"],
                name="Ilk Hareket (TL)",
                marker_color=colors_real,
                yaxis="y2",
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "Ilk Hareket: %{y:+.2f} TL<br>"
                    "<extra></extra>"
                ),
            ))

    # ── 3. Esik cizgileri ──

    # x eksen araligi
    all_dates = list(df["date"])
    x_range = [min(all_dates), max(all_dates)] if all_dates else [None, None]

    # %55 alarm esigi
    fig.add_hline(
        y=0.55,
        line_dash="dot",
        line_color="#EF4444",
        line_width=1,
        annotation_text="Alarm %55",
        annotation_position="top right",
        annotation_font_size=10,
        annotation_font_color="#EF4444",
    )

    # %50 dikkat esigi
    fig.add_hline(
        y=0.50,
        line_dash="dot",
        line_color="#F59E0B",
        line_width=1,
        annotation_text="Dikkat %50",
        annotation_position="bottom right",
        annotation_font_size=10,
        annotation_font_color="#F59E0B",
    )

    # ── 4. Alarm tetiklenen gunler (marker) ──
    if "alarm_triggered" in df.columns:
        df_alarm = df[df["alarm_triggered"] == True]
        if not df_alarm.empty:
            fig.add_trace(go.Scatter(
                x=df_alarm["date"],
                y=df_alarm["stage1_probability"],
                mode="markers",
                name="Alarm",
                marker=dict(
                    size=10,
                    color="#EF4444",
                    symbol="diamond",
                    line=dict(width=1, color="white"),
                ),
                hovertemplate=(
                    "<b>%{x|%d %b}</b><br>"
                    "ALARM: %{y:.1%}<br>"
                    "<extra></extra>"
                ),
            ))

    # ── 5. Layout ──

    title_suffix = f" — {fuel_type.capitalize()}" if fuel_type else ""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=f"v5 Tahmin Gecmisi{title_suffix}",
        xaxis_title="Tarih",
        yaxis=dict(
            title="Degisim Olasiligi",
            range=[0, 1],
            tickformat=".0%",
            side="left",
        ),
        yaxis2=dict(
            title="Ilk Hareket (TL)",
            overlaying="y",
            side="right",
            showgrid=False,
        ),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        height=420,
        bargap=0.3,
    )

    return fig
'''


def patch_charts(content: str) -> str:
    """
    charts.py icerigini yamalar.

    1. Mevcut create_v5_prediction_history varsa siler
    2. Dosyanin sonuna yeni fonksiyonu ekler
    """
    # Mevcut fonksiyon varsa sil (def create_v5_prediction_history ... sonraki def'e kadar)
    import re

    # Regex: fonksiyon baslangici ile bir sonraki top-level def arasini bul
    pattern = r'\ndef create_v5_prediction_history\(.*?(?=\ndef |\Z)'
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(pattern, '', content, flags=re.DOTALL)
        # Sondaki bos satirlari temizle
        content = content.rstrip('\n') + '\n'

    # Sona yeni fonksiyonu ekle
    content = content.rstrip('\n') + '\n' + NEW_FUNCTION + '\n'

    return content


def main():
    parser = argparse.ArgumentParser(
        description="Patch charts.py — add/update create_v5_prediction_history",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Sadece kontrol et, dosyaya yazma",
    )
    parser.add_argument(
        "--path",
        default=CHARTS_PATH,
        help=f"charts.py dosya yolu (default: {CHARTS_PATH})",
    )
    args = parser.parse_args()

    target = args.path

    # Dosyayi oku
    try:
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"HATA: Dosya bulunamadi: {target}")
        sys.exit(1)

    print(f"Dosya okundu: {target} ({len(content)} byte)")

    # Patch uygula
    patched = patch_charts(content)

    if content == patched:
        print("Degisiklik yok — dosya zaten guncel")
        return

    # Degisiklikleri goster
    old_lines = content.count('\n')
    new_lines = patched.count('\n')
    print(f"Degisiklik tespit edildi: {old_lines} -> {new_lines} satir (+{new_lines - old_lines})")

    # Kontrol: create_v5_prediction_history mevcut mu?
    if "def create_v5_prediction_history(" in patched:
        print("create_v5_prediction_history fonksiyonu mevcut")
    else:
        print("HATA: create_v5_prediction_history fonksiyonu eklenemedi!")
        sys.exit(1)

    if args.dry_run:
        print("[DRY-RUN] Dosyaya yazilmadi")
        # Son 30 satiri goster
        lines = patched.split('\n')
        print("\n--- Son 30 satir ---")
        for line in lines[-30:]:
            print(line)
        return

    # Yedek al
    backup_path = target + ".bak"
    try:
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Yedek alindi: {backup_path}")
    except Exception as e:
        print(f"UYARI: Yedek alinamadi: {e}")

    # Dosyaya yaz
    with open(target, "w", encoding="utf-8") as f:
        f.write(patched)

    print(f"charts.py guncellendi: {target}")
    print("TAMAMLANDI")


if __name__ == "__main__":
    main()
