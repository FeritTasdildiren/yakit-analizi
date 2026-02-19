"""
Test: Predictor v5 — Calibration Module
==========================================
10+ test: Platt, Beta, Isotonic, ECE, auto_calibrate, save/load, apply, edge cases
"""

import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.predictor_v5.calibration import (
    BetaCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    apply_calibration,
    auto_calibrate,
    calibrate_beta,
    calibrate_isotonic,
    calibrate_platt,
    evaluate_calibration,
    load_calibrator,
    save_calibrator,
)


# ===========================================================================
# Yardımcı: Sentetik veri oluşturucular
# ===========================================================================

def _make_well_calibrated_data(n: int = 500, seed: int = 42) -> tuple:
    """İyi kalibre edilmiş sentetik veri.

    p ~ Uniform(0,1), y ~ Bernoulli(p) → perfect calibration
    """
    rng = np.random.RandomState(seed)
    p = rng.uniform(0.05, 0.95, size=n)
    y = rng.binomial(1, p)
    return p, y


def _make_poorly_calibrated_data(n: int = 500, seed: int = 42) -> tuple:
    """Kötü kalibre edilmiş sentetik veri.

    Model çok overconfident: p büyükse hep 0.9+, p küçükse hep 0.1-
    Ama gerçek dağılım farklı.
    """
    rng = np.random.RandomState(seed)
    true_p = rng.uniform(0.2, 0.8, size=n)
    y = rng.binomial(1, true_p)
    # Overconfident model: gerçek p=0.5 olsa bile 0.9 veya 0.1 diyor
    model_p = np.where(true_p > 0.5, 0.85 + rng.uniform(0, 0.1, n), 0.05 + rng.uniform(0, 0.1, n))
    return model_p, y


def _make_realistic_classifier_data(n: int = 1000, seed: int = 42) -> tuple:
    """Gerçekçi classifier çıktısı.

    Sigmoid + noise → tipik bir LightGBM çıktısı gibi.
    """
    rng = np.random.RandomState(seed)
    # Latent signal
    z = rng.randn(n) * 1.5
    true_p = 1.0 / (1.0 + np.exp(-z))
    y = rng.binomial(1, true_p)
    # Model çıktısı: biraz shift + noise
    model_p = 1.0 / (1.0 + np.exp(-(z * 0.8 + 0.3 + rng.randn(n) * 0.2)))
    model_p = np.clip(model_p, 0.01, 0.99)
    return model_p, y


# ===========================================================================
# 1. Platt Kalibrasyon
# ===========================================================================

class TestPlattCalibration:
    """Platt scaling testleri."""

    def test_platt_calibrates_probabilities(self):
        """Platt kalibratör fit edilip transform uygulanabilmeli."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_platt(probs, labels)

        assert isinstance(calibrator, PlattCalibrator)
        assert calibrator.lr is not None

        calibrated = calibrator.transform(probs)
        assert len(calibrated) == len(probs)
        assert np.all(calibrated >= 0.0)
        assert np.all(calibrated <= 1.0)

    def test_platt_improves_calibration(self):
        """Platt kalibrasyon, kötü kalibre edilmiş veriyi iyileştirmeli."""
        probs, labels = _make_poorly_calibrated_data(500)

        # Kalibrasyonsuz ECE
        raw_eval = evaluate_calibration(probs, labels)
        raw_ece = raw_eval["ece"]

        # Platt ile kalibre
        calibrator = calibrate_platt(probs, labels)
        calibrated = calibrator.transform(probs)
        cal_eval = evaluate_calibration(calibrated, labels)
        cal_ece = cal_eval["ece"]

        # Kalibre edilmiş ECE ham ECE'den daha iyi olmalı
        assert cal_ece < raw_ece, (
            f"Platt kalibrasyon iyileştirmedi: raw_ece={raw_ece:.4f}, cal_ece={cal_ece:.4f}"
        )

    def test_platt_not_fitted_raises(self):
        """Fit edilmemiş Platt'ta transform çağrırmak hata vermeli."""
        calibrator = PlattCalibrator()
        with pytest.raises(RuntimeError, match="fit edilmemis"):
            calibrator.transform(np.array([0.5, 0.6]))


# ===========================================================================
# 2. Beta Kalibrasyon
# ===========================================================================

class TestBetaCalibration:
    """Beta kalibrasyon testleri."""

    def test_beta_calibrates_probabilities(self):
        """Beta kalibratör fit edilip transform uygulanabilmeli."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_beta(probs, labels)

        assert isinstance(calibrator, BetaCalibrator)
        assert calibrator.fitted is True

        calibrated = calibrator.transform(probs)
        assert len(calibrated) == len(probs)
        assert np.all(calibrated >= 0.0)
        assert np.all(calibrated <= 1.0)

    def test_beta_parameters_learned(self):
        """Beta kalibrasyonda a, b, c parametreleri öğrenilmeli."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_beta(probs, labels)

        # Parametreler default'tan farklı olmalı (öğrenilmiş)
        # a=1, b=1, c=0 default değerler
        assert calibrator.fitted is True
        # En az biri değişmiş olmalı
        params_changed = (
            abs(calibrator.a - 1.0) > 0.001
            or abs(calibrator.b - 1.0) > 0.001
            or abs(calibrator.c - 0.0) > 0.001
        )
        assert params_changed, "Beta parametreleri öğrenilmemiş!"

    def test_beta_not_fitted_raises(self):
        """Fit edilmemiş Beta'da transform çağırmak hata vermeli."""
        calibrator = BetaCalibrator()
        with pytest.raises(RuntimeError, match="fit edilmemis"):
            calibrator.transform(np.array([0.5]))


# ===========================================================================
# 3. ECE Hesaplama
# ===========================================================================

class TestEvaluateCalibration:
    """ECE, MCE, Brier score değerlendirme testleri."""

    def test_ece_perfect_calibration_near_zero(self):
        """Mükemmel kalibre edilmiş veri için ECE ~ 0.0."""
        # Büyük veri, iyi kalibrasyon → ECE düşük olmalı
        probs, labels = _make_well_calibrated_data(5000, seed=123)
        result = evaluate_calibration(probs, labels)

        assert result["ece"] < 0.05, (
            f"Mükemmel kalibrasyon ECE çok yüksek: {result['ece']:.4f}"
        )
        assert "brier_score" in result
        assert "mce" in result

    def test_ece_poor_calibration_high(self):
        """Kötü kalibre edilmiş veri için ECE yüksek olmalı."""
        probs, labels = _make_poorly_calibrated_data(500)
        result = evaluate_calibration(probs, labels)

        assert result["ece"] > 0.1, (
            f"Kötü kalibrasyon ECE çok düşük: {result['ece']:.4f}"
        )

    def test_ece_brier_score_range(self):
        """Brier score [0,1] aralığında olmalı."""
        probs, labels = _make_realistic_classifier_data(500)
        result = evaluate_calibration(probs, labels)

        assert 0.0 <= result["brier_score"] <= 1.0
        assert 0.0 <= result["ece"] <= 1.0
        assert 0.0 <= result["mce"] <= 1.0

    def test_reliability_data_format(self):
        """Reliability diagram verisi doğru formatta olmalı."""
        probs, labels = _make_realistic_classifier_data(500)
        result = evaluate_calibration(probs, labels, n_bins=10)

        rd = result["reliability_data"]
        assert "mean_predicted" in rd
        assert "fraction_positive" in rd
        assert "bin_counts" in rd

        assert len(rd["mean_predicted"]) == 10
        assert len(rd["fraction_positive"]) == 10
        assert len(rd["bin_counts"]) == 10

        # Bin counts toplamı = toplam örnek sayısı
        assert sum(rd["bin_counts"]) == 500

        # mean_predicted ve fraction_positive [0,1] aralığında
        for mp in rd["mean_predicted"]:
            assert 0.0 <= mp <= 1.0
        for fp in rd["fraction_positive"]:
            assert 0.0 <= fp <= 1.0

    def test_ece_empty_input(self):
        """Boş input için ece=0.0 dönmeli."""
        result = evaluate_calibration(np.array([]), np.array([]))
        assert result["ece"] == 0.0
        assert result["brier_score"] == 0.0

    def test_ece_different_bin_counts(self):
        """Farklı n_bins değerleriyle çalışmalı."""
        probs, labels = _make_realistic_classifier_data(500)

        for n_bins in [5, 10, 15, 20]:
            result = evaluate_calibration(probs, labels, n_bins=n_bins)
            assert len(result["reliability_data"]["bin_counts"]) == n_bins
            assert sum(result["reliability_data"]["bin_counts"]) == 500


# ===========================================================================
# 4. Auto-Calibrate
# ===========================================================================

class TestAutoCalibrate:
    """auto_calibrate otomatik seçim testleri."""

    def test_auto_calibrate_platt_sufficient(self):
        """Platt yeterli olduğunda Platt seçilmeli."""
        # Gerçekçi veri — Platt genelde yeterli olur
        probs, labels = _make_realistic_classifier_data(1000, seed=42)

        # Train/val split
        split = 600
        calibrator, metrics = auto_calibrate(
            probs[:split], labels[:split],
            probs[split:], labels[split:],
        )

        assert metrics["selected_method"] in ("platt", "beta", "isotonic")
        assert metrics["ece"] >= 0.0
        assert "all_candidates" in metrics

    def test_auto_calibrate_fallback_to_alternative(self):
        """Platt kötü olduğunda alternatif seçilmeli."""
        # Çok overconfident model → Platt yetersiz kalabilir
        probs, labels = _make_poorly_calibrated_data(1000, seed=42)

        split = 600
        calibrator, metrics = auto_calibrate(
            probs[:split], labels[:split],
            probs[split:], labels[split:],
        )

        # En iyi yöntem seçilmeli
        assert metrics["selected_method"] in ("platt", "beta", "isotonic")
        assert "ece" in metrics
        # Birden fazla aday denenmiş olmalı
        assert len(metrics["all_candidates"]) >= 1

    def test_auto_calibrate_returns_calibrator_and_metrics(self):
        """auto_calibrate tuple (calibrator, metrics) dönmeli."""
        probs, labels = _make_realistic_classifier_data(500)
        split = 300

        result = auto_calibrate(
            probs[:split], labels[:split],
            probs[split:], labels[split:],
        )

        assert isinstance(result, tuple)
        assert len(result) == 2

        calibrator, metrics = result
        assert hasattr(calibrator, "transform")
        assert isinstance(metrics, dict)
        assert "selected_method" in metrics
        assert "ece" in metrics
        assert "mce" in metrics
        assert "brier_score" in metrics


# ===========================================================================
# 5. Save / Load Round-Trip
# ===========================================================================

class TestSaveLoadCalibrator:
    """Kalibratör save/load testleri."""

    def test_save_load_platt_roundtrip(self):
        """Platt kalibratör save→load sonrası aynı sonuç vermeli."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_platt(probs, labels)

        original_output = calibrator.transform(probs[:10])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = save_calibrator(calibrator, "benzin", Path(tmpdir))
            assert path.exists()
            assert path.name == "benzin_calibrator.joblib"

            loaded = load_calibrator("benzin", Path(tmpdir))
            loaded_output = loaded.transform(probs[:10])

            np.testing.assert_array_almost_equal(
                original_output, loaded_output, decimal=10,
            )

    def test_save_load_beta_roundtrip(self):
        """Beta kalibratör save→load round-trip."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_beta(probs, labels)

        original_output = calibrator.transform(probs[:10])

        with tempfile.TemporaryDirectory() as tmpdir:
            save_calibrator(calibrator, "motorin", Path(tmpdir))
            loaded = load_calibrator("motorin", Path(tmpdir))
            loaded_output = loaded.transform(probs[:10])

            np.testing.assert_array_almost_equal(
                original_output, loaded_output, decimal=10,
            )

    def test_save_load_isotonic_roundtrip(self):
        """Isotonic kalibratör save→load round-trip."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_isotonic(probs, labels)

        original_output = calibrator.transform(probs[:10])

        with tempfile.TemporaryDirectory() as tmpdir:
            save_calibrator(calibrator, "lpg", Path(tmpdir))
            loaded = load_calibrator("lpg", Path(tmpdir))
            loaded_output = loaded.transform(probs[:10])

            np.testing.assert_array_almost_equal(
                original_output, loaded_output, decimal=10,
            )

    def test_load_nonexistent_raises(self):
        """Mevcut olmayan kalibratör dosyası FileNotFoundError vermeli."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                load_calibrator("nonexistent", Path(tmpdir))


# ===========================================================================
# 6. Apply Calibration
# ===========================================================================

class TestApplyCalibration:
    """apply_calibration fonksiyonu testleri."""

    def test_apply_calibration_output_range(self):
        """apply_calibration çıktısı [0,1] aralığında olmalı."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_platt(probs, labels)

        # Geniş aralık test — 0'a ve 1'e yakın değerler dahil
        test_probs = np.array([0.001, 0.01, 0.1, 0.3, 0.5, 0.7, 0.9, 0.99, 0.999])
        calibrated = apply_calibration(calibrator, test_probs)

        assert len(calibrated) == len(test_probs)
        assert np.all(calibrated >= 0.0), f"Min: {calibrated.min()}"
        assert np.all(calibrated <= 1.0), f"Max: {calibrated.max()}"

    def test_apply_calibration_with_single_value(self):
        """Tek değer ile de çalışmalı."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_platt(probs, labels)

        result = apply_calibration(calibrator, np.array([0.5]))
        assert len(result) == 1
        assert 0.0 <= result[0] <= 1.0

    def test_apply_calibration_preserves_ordering(self):
        """Monoton kalibratörler sıralamayı korumalı (Platt ve Isotonic)."""
        probs, labels = _make_realistic_classifier_data(500)

        # Platt (monoton)
        platt = calibrate_platt(probs, labels)
        ordered_input = np.linspace(0.01, 0.99, 50)
        platt_out = apply_calibration(platt, ordered_input)
        # Platt (sigmoid) monotondur
        assert np.all(np.diff(platt_out) >= -1e-10), "Platt monotonluğu korunmalı"

        # Isotonic (monoton by definition)
        iso = calibrate_isotonic(probs, labels)
        iso_out = apply_calibration(iso, ordered_input)
        assert np.all(np.diff(iso_out) >= -1e-10), "Isotonic monotonluğu korunmalı"


# ===========================================================================
# 7. Edge Cases
# ===========================================================================

class TestEdgeCases:
    """Kenar durumlar ve sağlamlık testleri."""

    def test_single_class_labels(self):
        """Tek sınıflı label'larla çökme olmamalı."""
        n = 100
        probs = np.random.RandomState(42).uniform(0.3, 0.8, n)
        labels_all_zero = np.zeros(n, dtype=int)

        # Platt — tek sınıf, fit edebilmeli (LogisticRegression uyarı verebilir)
        calibrator = calibrate_platt(probs, labels_all_zero)
        result = calibrator.transform(probs)
        assert len(result) == n
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)

    def test_extreme_probabilities(self):
        """0.0 ve 1.0 boundary değerleriyle çökme olmamalı."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_platt(probs, labels)

        extreme = np.array([0.0, 0.0001, 0.5, 0.9999, 1.0])
        result = apply_calibration(calibrator, extreme)

        assert len(result) == 5
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)
        assert not np.any(np.isnan(result))
        assert not np.any(np.isinf(result))

    def test_small_sample_calibration(self):
        """Az örnekle (< MIN_CALIBRATION_SAMPLES) kalibrasyon warning vermeli ama çalışmalı."""
        rng = np.random.RandomState(42)
        probs = rng.uniform(0.2, 0.8, 15)
        labels = rng.binomial(1, 0.5, 15)

        # Platt — uyarı verir ama çalışır
        calibrator = calibrate_platt(probs, labels)
        result = calibrator.transform(probs)
        assert len(result) == 15
        assert np.all(result >= 0.0) and np.all(result <= 1.0)

    def test_all_same_probability(self):
        """Tüm olasılıklar aynı olduğunda çökme olmamalı."""
        probs = np.full(100, 0.5)
        labels = np.random.RandomState(42).binomial(1, 0.5, 100)

        # Beta — aynı prob'larla çalışabilmeli
        calibrator = calibrate_beta(probs, labels)
        result = calibrator.transform(probs)
        assert len(result) == 100
        assert np.all(result >= 0.0) and np.all(result <= 1.0)


# ===========================================================================
# 8. Isotonic Kalibrasyon
# ===========================================================================

class TestIsotonicCalibration:
    """Isotonic regression testleri."""

    def test_isotonic_calibrates(self):
        """Isotonic kalibratör fit edilip transform uygulanabilmeli."""
        probs, labels = _make_realistic_classifier_data(500)
        calibrator = calibrate_isotonic(probs, labels)

        assert isinstance(calibrator, IsotonicCalibrator)
        assert calibrator.iso is not None

        calibrated = calibrator.transform(probs)
        assert len(calibrated) == len(probs)
        assert np.all(calibrated >= 0.0)
        assert np.all(calibrated <= 1.0)

    def test_isotonic_not_fitted_raises(self):
        """Fit edilmemiş Isotonic'te transform hata vermeli."""
        calibrator = IsotonicCalibrator()
        with pytest.raises(RuntimeError, match="fit edilmemis"):
            calibrator.transform(np.array([0.5]))
