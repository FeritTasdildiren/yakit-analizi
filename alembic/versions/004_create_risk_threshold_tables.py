"""
004: Risk/Eşik Motoru ve Politik Gecikme tabloları oluşturma.

Katman 3 — Risk & Eşik Motoru + Politik Gecikme Mekanizması.

ENUM'lar: regime_type_enum, alert_level_enum, alert_channel_enum
Tablolar: regime_events, threshold_config, risk_scores,
          political_delay_history, alerts

NOT: Bu migration 002'den dallanır (003 ile paralel — branching migration).
fuel_type_enum 001'de, direction_enum 003'te oluşturulmuş.
Burada sadece yeni ENUM'lar ve tablolar oluşturulur.

Revision ID: 004_risk_threshold
Revises: 002_create_tax_params
Create Date: 2026-02-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic revision bilgileri
revision = "004_risk_threshold"
down_revision = "002_create_tax_params"
branch_labels = ("risk_layer",)
depends_on = None


def upgrade() -> None:
    """ENUM tipleri ve Katman 3 tablolarını oluşturur."""

    # --- Yeni ENUM Tiplerini Oluştur ---
    regime_type_enum = postgresql.ENUM(
        "election", "holiday", "economic_crisis", "tax_change", "geopolitical", "other",
        name="regime_type_enum",
        create_type=True,
    )
    regime_type_enum.create(op.get_bind(), checkfirst=True)

    alert_level_enum = postgresql.ENUM(
        "info", "warning", "critical",
        name="alert_level_enum",
        create_type=True,
    )
    alert_level_enum.create(op.get_bind(), checkfirst=True)

    alert_channel_enum = postgresql.ENUM(
        "telegram", "email", "webhook", "dashboard",
        name="alert_channel_enum",
        create_type=True,
    )
    alert_channel_enum.create(op.get_bind(), checkfirst=True)

    # fuel_type_enum referansı — 001'de oluşturulmuş
    fuel_type_enum = sa.Enum(
        "benzin", "motorin", "lpg",
        name="fuel_type_enum",
        create_type=False,
    )

    # --- 1. regime_events Tablosu ---
    op.create_table(
        "regime_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("event_type", regime_type_enum, nullable=False,
                  comment="Olay tipi: election, holiday, economic_crisis, tax_change, geopolitical, other"),
        sa.Column("event_name", sa.String(255), nullable=False,
                  comment="Olay adı"),
        sa.Column("start_date", sa.Date(), nullable=False,
                  comment="Olayın başlangıç tarihi"),
        sa.Column("end_date", sa.Date(), nullable=False,
                  comment="Olayın bitiş tarihi"),
        sa.Column("impact_score", sa.Integer(), nullable=False,
                  comment="Etki skoru (0-10)"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE"),
                  comment="Olay aktif mi?"),
        sa.Column("source", sa.String(255), nullable=False, server_default="manual",
                  comment="Veri kaynağı"),
        sa.Column("description", sa.Text(), nullable=True,
                  comment="Ek açıklama"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Oluşturulma zamanı"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Son güncelleme zamanı"),
        comment="Politik/ekonomik rejim olayları — seçim, kriz, bayram vb.",
    )

    op.create_index("idx_regime_event_type", "regime_events", ["event_type"])
    op.create_index("idx_regime_active", "regime_events", ["is_active"],
                    postgresql_where=sa.text("is_active = TRUE"))
    op.create_index("idx_regime_dates", "regime_events", ["start_date", "end_date"])

    # --- 2. threshold_config Tablosu ---
    op.create_table(
        "threshold_config",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("fuel_type", fuel_type_enum, nullable=True,
                  comment="Yakıt tipi (NULL ise tüm yakıt tipleri için geçerli)"),
        sa.Column("metric_name", sa.String(100), nullable=False,
                  comment="Metrik adı (ör: risk_score, mbe_value)"),
        sa.Column("alert_level", alert_level_enum, nullable=False,
                  comment="Uyarı seviyesi: info, warning, critical"),
        sa.Column("threshold_open", sa.Numeric(10, 4), nullable=False,
                  comment="Eşik açılış değeri"),
        sa.Column("threshold_close", sa.Numeric(10, 4), nullable=False,
                  comment="Eşik kapanış değeri (hysteresis)"),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default=sa.text("24"),
                  comment="Alarm tekrar tetiklenmeden önce beklenecek saat"),
        sa.Column("regime_modifier", postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Rejim bazlı eşik düzeltici"),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"),
                  comment="Konfigürasyon versiyonu"),
        sa.Column("valid_from", sa.Date(), nullable=False,
                  comment="Geçerlilik başlangıç tarihi"),
        sa.Column("valid_to", sa.Date(), nullable=True,
                  comment="Geçerlilik bitiş tarihi (NULL = hâlâ geçerli)"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Oluşturulma zamanı"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Son güncelleme zamanı"),
        comment="Dinamik eşik parametreleri — hysteresis, cooldown, rejim modifier",
    )

    op.create_index("idx_threshold_metric_level", "threshold_config", ["metric_name", "alert_level"])
    op.create_index("idx_threshold_fuel", "threshold_config", ["fuel_type"])
    op.create_index("idx_threshold_active", "threshold_config", ["metric_name"],
                    postgresql_where=sa.text("valid_to IS NULL"))

    # --- 3. risk_scores Tablosu ---
    op.create_table(
        "risk_scores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("trade_date", sa.Date(), nullable=False,
                  comment="İşlem tarihi"),
        sa.Column("fuel_type", fuel_type_enum, nullable=False,
                  comment="Yakıt tipi: benzin, motorin, lpg"),
        sa.Column("composite_score", sa.Numeric(10, 4), nullable=False,
                  comment="Bileşik risk skoru (0-1)"),
        sa.Column("mbe_component", sa.Numeric(10, 4), nullable=False,
                  comment="Normalize edilmiş MBE bileşeni (0-1)"),
        sa.Column("fx_volatility_component", sa.Numeric(10, 4), nullable=False,
                  comment="Normalize edilmiş FX volatilite bileşeni (0-1)"),
        sa.Column("political_delay_component", sa.Numeric(10, 4), nullable=False,
                  comment="Normalize edilmiş politik gecikme bileşeni (0-1)"),
        sa.Column("threshold_breach_component", sa.Numeric(10, 4), nullable=False,
                  comment="Normalize edilmiş eşik ihlali bileşeni (0-1)"),
        sa.Column("trend_momentum_component", sa.Numeric(10, 4), nullable=False,
                  comment="Normalize edilmiş trend momentum bileşeni (0-1)"),
        sa.Column("weight_vector", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  comment="Bileşen ağırlıkları"),
        sa.Column("triggered_alerts", postgresql.ARRAY(sa.String(100)), nullable=True,
                  comment="Tetiklenen alarm ID'leri"),
        sa.Column("system_mode", sa.String(50), nullable=False, server_default="normal",
                  comment="Sistem modu: normal, high_alert, crisis"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Oluşturulma zamanı"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Son güncelleme zamanı"),
        comment="Günlük risk skorları — bileşik skor ve bileşenler",
    )

    op.create_unique_constraint("uq_risk_score_date_fuel", "risk_scores", ["trade_date", "fuel_type"])
    op.create_index("idx_risk_score_date", "risk_scores", ["trade_date"])
    op.create_index("idx_risk_score_fuel_date", "risk_scores", ["fuel_type", "trade_date"])
    op.create_index("idx_risk_score_high", "risk_scores", ["composite_score"],
                    postgresql_where=sa.text("composite_score >= 0.60"))

    # --- 4. political_delay_history Tablosu ---
    op.create_table(
        "political_delay_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("fuel_type", fuel_type_enum, nullable=False,
                  comment="Yakıt tipi: benzin, motorin, lpg"),
        sa.Column("expected_change_date", sa.Date(), nullable=False,
                  comment="Beklenen fiyat değişikliği tarihi"),
        sa.Column("actual_change_date", sa.Date(), nullable=True,
                  comment="Gerçek fiyat değişikliği tarihi"),
        sa.Column("delay_days", sa.Integer(), nullable=False, server_default=sa.text("0"),
                  comment="Gecikme gün sayısı"),
        sa.Column("mbe_at_expected", sa.Numeric(18, 8), nullable=False,
                  comment="Beklenen tarihte MBE değeri"),
        sa.Column("mbe_at_actual", sa.Numeric(18, 8), nullable=True,
                  comment="Gerçek zam tarihindeki MBE değeri"),
        sa.Column("accumulated_pressure_pct", sa.Numeric(10, 4), nullable=False,
                  server_default=sa.text("0"), comment="Birikmiş basınç yüzdesi"),
        sa.Column("status", sa.String(50), nullable=False, server_default="watching",
                  comment="Takip durumu: watching, closed, absorbed, partial_close"),
        sa.Column("regime_event_id", sa.BigInteger(),
                  sa.ForeignKey("regime_events.id", ondelete="SET NULL"),
                  nullable=True, comment="İlişkili rejim olayı"),
        sa.Column("price_change_id", sa.BigInteger(), nullable=True,
                  comment="İlişkili fiyat değişikliği kaydı ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Oluşturulma zamanı"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Son güncelleme zamanı"),
        comment="Politik gecikme takibi — beklenen/gerçek zam tarihleri, basınç birikimi",
    )

    op.create_index("idx_delay_fuel_date", "political_delay_history",
                    ["fuel_type", "expected_change_date"])
    op.create_index("idx_delay_pending", "political_delay_history", ["status"],
                    postgresql_where=sa.text("status = 'watching'"))
    op.create_index("idx_delay_regime", "political_delay_history", ["regime_event_id"])

    # --- 5. alerts Tablosu ---
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True,
                  comment="Otomatik artan birincil anahtar"),
        sa.Column("alert_level", alert_level_enum, nullable=False,
                  comment="Alarm seviyesi: info, warning, critical"),
        sa.Column("alert_type", sa.String(100), nullable=False,
                  comment="Alarm tipi"),
        sa.Column("fuel_type", fuel_type_enum, nullable=True,
                  comment="İlgili yakıt tipi (NULL ise genel alarm)"),
        sa.Column("title", sa.String(255), nullable=False,
                  comment="Alarm başlığı"),
        sa.Column("message", sa.Text(), nullable=False,
                  comment="Alarm detay mesajı"),
        sa.Column("metric_name", sa.String(100), nullable=False,
                  comment="Tetikleyen metrik adı"),
        sa.Column("metric_value", sa.Numeric(18, 8), nullable=False,
                  comment="Tetikleyen metrik değeri"),
        sa.Column("threshold_value", sa.Numeric(10, 4), nullable=False,
                  comment="Aşılan eşik değeri"),
        sa.Column("threshold_config_id", sa.BigInteger(),
                  sa.ForeignKey("threshold_config.id", ondelete="SET NULL"),
                  nullable=True, comment="İlişkili eşik konfigürasyonu"),
        sa.Column("risk_score_id", sa.BigInteger(),
                  sa.ForeignKey("risk_scores.id", ondelete="SET NULL"),
                  nullable=True, comment="İlişkili risk skoru kaydı"),
        sa.Column("channels_sent", postgresql.ARRAY(sa.String(50)), nullable=True,
                  comment="Gönderildiği kanallar"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.text("FALSE"),
                  comment="Okundu mu?"),
        sa.Column("is_resolved", sa.Boolean(), nullable=False, server_default=sa.text("FALSE"),
                  comment="Çözüldü mü?"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True,
                  comment="Çözüm zamanı"),
        sa.Column("resolved_reason", sa.Text(), nullable=True,
                  comment="Çözüm nedeni açıklaması"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Oluşturulma zamanı"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()"), comment="Son güncelleme zamanı"),
        comment="Sistem alert'leri — risk eşiği ihlalleri, uyarılar",
    )

    op.create_index("idx_alert_level", "alerts", ["alert_level"])
    op.create_index("idx_alert_fuel", "alerts", ["fuel_type"])
    op.create_index("idx_alert_unread", "alerts", ["is_read"],
                    postgresql_where=sa.text("is_read = FALSE"))
    op.create_index("idx_alert_unresolved", "alerts", ["is_resolved"],
                    postgresql_where=sa.text("is_resolved = FALSE"))
    op.create_index("idx_alert_created", "alerts", ["created_at"])

    # --- updated_at Trigger'ları ---
    for table in ("regime_events", "threshold_config", "risk_scores",
                  "political_delay_history", "alerts"):
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
        """)


def downgrade() -> None:
    """Katman 3 tablolarını ve ENUM tiplerini kaldırır."""

    # Trigger'ları kaldır
    for table in ("alerts", "political_delay_history", "risk_scores",
                  "threshold_config", "regime_events"):
        op.execute(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")

    # Tabloları ters sırayla kaldır (FK bağımlılıkları)
    # alerts → threshold_config, risk_scores FK var
    op.drop_index("idx_alert_created", table_name="alerts")
    op.drop_index("idx_alert_unresolved", table_name="alerts")
    op.drop_index("idx_alert_unread", table_name="alerts")
    op.drop_index("idx_alert_fuel", table_name="alerts")
    op.drop_index("idx_alert_level", table_name="alerts")
    op.drop_table("alerts")

    # political_delay_history → regime_events FK var
    op.drop_index("idx_delay_regime", table_name="political_delay_history")
    op.drop_index("idx_delay_pending", table_name="political_delay_history")
    op.drop_index("idx_delay_fuel_date", table_name="political_delay_history")
    op.drop_table("political_delay_history")

    # risk_scores
    op.drop_index("idx_risk_score_high", table_name="risk_scores")
    op.drop_index("idx_risk_score_fuel_date", table_name="risk_scores")
    op.drop_index("idx_risk_score_date", table_name="risk_scores")
    op.drop_constraint("uq_risk_score_date_fuel", "risk_scores", type_="unique")
    op.drop_table("risk_scores")

    # threshold_config
    op.drop_index("idx_threshold_active", table_name="threshold_config")
    op.drop_index("idx_threshold_fuel", table_name="threshold_config")
    op.drop_index("idx_threshold_metric_level", table_name="threshold_config")
    op.drop_table("threshold_config")

    # regime_events
    op.drop_index("idx_regime_dates", table_name="regime_events")
    op.drop_index("idx_regime_active", table_name="regime_events")
    op.drop_index("idx_regime_event_type", table_name="regime_events")
    op.drop_table("regime_events")

    # ENUM tiplerini kaldır
    op.execute("DROP TYPE IF EXISTS alert_channel_enum;")
    op.execute("DROP TYPE IF EXISTS alert_level_enum;")
    op.execute("DROP TYPE IF EXISTS regime_type_enum;")
