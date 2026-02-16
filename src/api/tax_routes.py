"""
Vergi parametreleri API endpoint'leri.

Akaryakıt ÖTV ve KDV oranlarını yöneten RESTful API router.
Tüm endpoint'ler /api/v1/taxes prefix'i altında çalışır.
"""

import logging
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.database import get_db
from src.data_collectors.tax_repository import (
    TaxParameterCreate as TaxParameterCreateDTO,
    create_tax_parameter,
    get_all_current_taxes,
    get_current_tax,
    get_tax_by_id,
    get_tax_history,
    update_tax_parameter,
)
from src.data_collectors.tax_validators import TaxValidationErrors

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/taxes", tags=["Vergi Parametreleri"])


# --- Pydantic Modelleri ---


class TaxParameterCreateSchema(BaseModel):
    """Yeni vergi parametresi oluşturma isteği şeması."""

    fuel_type: str
    otv_rate: Decimal | None = None
    otv_fixed_tl: Decimal | None = None
    kdv_rate: Decimal
    valid_from: date
    gazette_reference: str | None = None
    notes: str | None = None

    @field_validator("fuel_type")
    @classmethod
    def validate_fuel_type(cls, v: str) -> str:
        """Yakıt tipini doğrular."""
        valid_types = {"benzin", "motorin", "lpg"}
        if v not in valid_types:
            msg = f"Geçersiz yakıt tipi: '{v}'. Geçerli değerler: {', '.join(sorted(valid_types))}"
            raise ValueError(msg)
        return v

    @field_validator("kdv_rate")
    @classmethod
    def validate_kdv_rate(cls, v: Decimal) -> Decimal:
        """KDV oranını doğrular (0-1 aralığı)."""
        if v < Decimal("0") or v > Decimal("1"):
            msg = f"KDV oranı 0 ile 1 arasında olmalıdır, verilen: {v}"
            raise ValueError(msg)
        return v


class TaxParameterUpdateSchema(BaseModel):
    """Vergi parametresi güncelleme isteği şeması (partial update)."""

    otv_rate: Decimal | None = None
    otv_fixed_tl: Decimal | None = None
    kdv_rate: Decimal | None = None
    gazette_reference: str | None = None
    notes: str | None = None

    @field_validator("kdv_rate")
    @classmethod
    def validate_kdv_rate(cls, v: Decimal | None) -> Decimal | None:
        """KDV oranını doğrular (0-1 aralığı, verilmişse)."""
        if v is not None and (v < Decimal("0") or v > Decimal("1")):
            msg = f"KDV oranı 0 ile 1 arasında olmalıdır, verilen: {v}"
            raise ValueError(msg)
        return v


class TaxParameterResponse(BaseModel):
    """Vergi parametresi yanıt şeması."""

    id: int
    fuel_type: str
    otv_rate: Decimal | None
    otv_fixed_tl: Decimal | None
    kdv_rate: Decimal
    valid_from: date
    valid_to: date | None
    gazette_reference: str | None
    notes: str | None
    created_by: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaxParameterListResponse(BaseModel):
    """Vergi parametreleri liste yanıtı."""

    count: int
    data: list[TaxParameterResponse]


class ErrorResponse(BaseModel):
    """Hata yanıt şeması."""

    detail: str
    errors: list[dict[str, str]] | None = None


# --- Endpoint'ler ---


@router.get(
    "/current",
    response_model=TaxParameterListResponse,
    summary="Tüm yakıt tipleri için güncel vergi oranları",
)
async def list_current_taxes(
    db: AsyncSession = Depends(get_db),
) -> TaxParameterListResponse:
    """
    Tüm yakıt tipleri (benzin, motorin, lpg) için şu an geçerli olan
    vergi oranlarını döndürür. valid_to = NULL olan kayıtlar aktiftir.
    """
    taxes = await get_all_current_taxes(db)
    return TaxParameterListResponse(
        count=len(taxes),
        data=[TaxParameterResponse.model_validate(t) for t in taxes],
    )


@router.get(
    "/current/{fuel_type}",
    response_model=TaxParameterResponse,
    summary="Belirli yakıt tipi için güncel vergi oranı",
    responses={404: {"model": ErrorResponse}},
)
async def get_current_tax_by_fuel_type(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> TaxParameterResponse:
    """
    Belirtilen yakıt tipi için şu an geçerli olan vergi oranını döndürür.

    Path parametreleri:
    - **fuel_type**: benzin, motorin veya lpg
    """
    # Yakıt tipi doğrulama
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'. Geçerli değerler: benzin, motorin, lpg",
        )

    tax = await get_current_tax(db, fuel_type)
    if tax is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{fuel_type}' için aktif vergi kaydı bulunamadı",
        )

    return TaxParameterResponse.model_validate(tax)


@router.get(
    "/at-date/{ref_date}",
    response_model=TaxParameterListResponse,
    summary="Belirli tarihteki tüm vergi oranları",
)
async def get_taxes_at_date(
    ref_date: date,
    db: AsyncSession = Depends(get_db),
) -> TaxParameterListResponse:
    """
    Belirtilen tarihte geçerli olan tüm yakıt tiplerine ait vergi oranlarını döndürür.

    Path parametreleri:
    - **ref_date**: YYYY-MM-DD formatında tarih (ör: 2024-07-15)
    """
    taxes = await get_all_current_taxes(db, ref_date=ref_date)
    return TaxParameterListResponse(
        count=len(taxes),
        data=[TaxParameterResponse.model_validate(t) for t in taxes],
    )


@router.get(
    "/history/{fuel_type}",
    response_model=TaxParameterListResponse,
    summary="Belirli yakıt tipi için vergi geçmişi",
    responses={400: {"model": ErrorResponse}},
)
async def list_tax_history(
    fuel_type: str,
    db: AsyncSession = Depends(get_db),
) -> TaxParameterListResponse:
    """
    Belirtilen yakıt tipi için tüm vergi geçmişini döndürür.
    En yeni kayıttan en eski kayda doğru sıralanır.

    Path parametreleri:
    - **fuel_type**: benzin, motorin veya lpg
    """
    if fuel_type not in {"benzin", "motorin", "lpg"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz yakıt tipi: '{fuel_type}'. Geçerli değerler: benzin, motorin, lpg",
        )

    taxes = await get_tax_history(db, fuel_type)
    return TaxParameterListResponse(
        count=len(taxes),
        data=[TaxParameterResponse.model_validate(t) for t in taxes],
    )


@router.post(
    "",
    response_model=TaxParameterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Yeni vergi oranı ekle",
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def create_tax(
    payload: TaxParameterCreateSchema,
    db: AsyncSession = Depends(get_db),
) -> TaxParameterResponse:
    """
    Yeni bir vergi oranı kaydı oluşturur.

    Aynı yakıt tipi için aktif (valid_to = NULL) bir kayıt varsa,
    bu kaydın valid_to alanı otomatik olarak yeni kaydın valid_from - 1 gün
    olarak güncellenir (temporal bütünlük).

    Request body:
    - **fuel_type**: benzin, motorin veya lpg
    - **otv_rate**: ÖTV yüzdesel oranı (opsiyonel)
    - **otv_fixed_tl**: ÖTV sabit tutar TRY/litre (opsiyonel)
    - **kdv_rate**: KDV oranı (0-1 arası, ör: 0.18)
    - **valid_from**: Geçerlilik başlangıç tarihi (YYYY-MM-DD)
    - **gazette_reference**: Resmi Gazete referansı (opsiyonel)
    - **notes**: Ek notlar (opsiyonel)
    """
    try:
        dto = TaxParameterCreateDTO(
            fuel_type=payload.fuel_type,
            otv_rate=payload.otv_rate,
            otv_fixed_tl=payload.otv_fixed_tl,
            kdv_rate=payload.kdv_rate,
            valid_from=payload.valid_from,
            gazette_reference=payload.gazette_reference,
            notes=payload.notes,
        )
        new_tax = await create_tax_parameter(db, dto)
        return TaxParameterResponse.model_validate(new_tax)

    except TaxValidationErrors as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e


@router.put(
    "/{tax_id}",
    response_model=TaxParameterResponse,
    summary="Vergi oranını güncelle",
    responses={
        400: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def update_tax(
    tax_id: int,
    payload: TaxParameterUpdateSchema,
    db: AsyncSession = Depends(get_db),
) -> TaxParameterResponse:
    """
    Mevcut bir vergi kaydını günceller (partial update).

    Sadece gönderilen alanlar güncellenir. valid_from ve valid_to
    bu endpoint ile değiştirilemez (temporal bütünlük).

    Path parametreleri:
    - **tax_id**: Güncellenecek vergi kaydı ID'si

    Request body (tüm alanlar opsiyonel):
    - **otv_rate**: Yeni ÖTV yüzdesel oranı
    - **otv_fixed_tl**: Yeni ÖTV sabit tutar TRY/litre
    - **kdv_rate**: Yeni KDV oranı
    - **gazette_reference**: Yeni Resmi Gazete referansı
    - **notes**: Yeni notlar
    """
    try:
        updated = await update_tax_parameter(
            session=db,
            tax_id=tax_id,
            otv_rate=payload.otv_rate,
            otv_fixed_tl=payload.otv_fixed_tl,
            kdv_rate=payload.kdv_rate,
            gazette_reference=payload.gazette_reference,
            notes=payload.notes,
        )

        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ID={tax_id} olan vergi kaydı bulunamadı",
            )

        return TaxParameterResponse.model_validate(updated)

    except TaxValidationErrors as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
