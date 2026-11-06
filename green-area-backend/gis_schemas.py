"""Strict GIS HTTP input contracts, separate from existing analysis models."""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Label = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Province = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=120)]
Reason = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]
SourceLabel = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=255, pattern=r"^[^\x00-\x1f\x7f]+$")]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
Month = Annotated[int, Field(strict=True, ge=0, le=12)]
Kind = Literal["ldd_shapefile", "geotiff"]
Purpose = Literal["landuse", "ndvi", "lst"]
EditionState = Literal["draft", "validating", "validated", "withdrawn"]
JobState = Literal["queued", "running", "succeeded", "failed"]
Attribute = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]


class GisInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SourceManifest(GisInput):
    """Metadata only. This does not validate an uploaded GIS file."""

    schema_version: Literal[1, 2]
    provider: Literal["synthetic", "real"]
    fixture_id: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]{1,60}$")] | None = None
    sha256: Hash
    byte_size: Annotated[int, Field(strict=True, ge=1, le=999999999)]
    provenance: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9 _.-]{1,100}$")]
    crs: Annotated[str, StringConstraints(strict=True, pattern=r"^EPSG:[0-9]{4,6}$")]
    data_kind: Literal["raster", "polygon"]
    profile: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_.-]{1,60}$")] | None = None
    provider_build: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_.-]{1,60}$")] | None = None
    bands: Annotated[list[Attribute], Field(min_length=1, max_length=8)] | None = None
    units: Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_.-]{1,20}$")] | None = None
    nodata: Annotated[float, Field(strict=True)] | Annotated[int, Field(strict=True)] | None = None
    resolution: Annotated[float, Field(strict=True, ge=0.001, le=10000)] | None = None
    attributes: Annotated[list[Attribute], Field(min_length=1, max_length=30)] | None = None
    scales: Annotated[list[float], Field(min_length=1, max_length=8)] | None = None
    offsets: Annotated[list[float], Field(min_length=1, max_length=8)] | None = None

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int or value not in (1, 2):
            raise ValueError("schema_version must be the integer 1 or 2")
        return value

    @model_validator(mode="after")
    def required_metadata(self):
        if self.schema_version == 1:
            if self.provider == "synthetic" and self.fixture_id is None:
                raise ValueError("synthetic metadata requires an allowlisted fixture_id")
            if self.provider == "real" and self.fixture_id is not None:
                raise ValueError("real metadata cannot carry fixture_id")
            if self.data_kind == "raster":
                if self.bands is None or self.units is None or self.nodata is None or self.resolution is None:
                    raise ValueError("raster metadata requires bands, units, nodata and resolution")
                if self.attributes is not None:
                    raise ValueError("raster metadata cannot carry polygon attributes")
                if self.units not in ("celsius", "unitless", "categories"):
                    raise ValueError("V1 raster units must be celsius, unitless or categories")
            elif self.attributes is None or any(v is not None for v in (self.bands, self.units, self.nodata, self.resolution)):
                raise ValueError("polygon metadata requires attributes and cannot carry raster fields")
            if any(v is not None for v in (self.scales, self.offsets, self.profile, self.provider_build)):
                raise ValueError("V1 metadata cannot carry V2 fields")
        elif self.schema_version == 2:
            if self.provider != "synthetic" or self.fixture_id is None:
                raise ValueError("V2 synthetic metadata requires an allowlisted fixture_id")
            if self.provider_build != "t3-native-v1":
                raise ValueError("V2 metadata requires provider_build t3-native-v1")
            if self.data_kind == "raster":
                if self.bands is None or self.units is None or self.nodata is None or self.resolution is None:
                    raise ValueError("raster metadata requires bands, units, nodata and resolution")
                if self.attributes is not None:
                    raise ValueError("raster metadata cannot carry polygon attributes")
            elif self.data_kind == "polygon":
                if self.attributes is None:
                    raise ValueError("polygon metadata requires attributes")
                if any(v is not None for v in (self.bands, self.units, self.nodata, self.resolution, self.scales, self.offsets)):
                    raise ValueError("polygon metadata cannot carry raster fields")
        return self


class DatasetCreate(GisInput):
    province: Province
    data_year: Annotated[int, Field(strict=True, ge=1980)]
    month: Month
    kind: Kind
    purpose: Purpose
    title: Label

    @field_validator("data_year")
    @classmethod
    def source_year(cls, value):
        if value > date.today().year + 1:
            raise ValueError("data_year exceeds the supported CE source year")
        return value

    @model_validator(mode="after")
    def identity_pair(self):
        if self.kind == "ldd_shapefile" and (self.purpose != "landuse" or self.month != 0):
            raise ValueError("LDD requires annual month 0 and landuse purpose")
        if self.kind == "geotiff" and self.purpose not in ("ndvi", "lst"):
            raise ValueError("GeoTIFF purpose must be ndvi or lst")
        return self


class DatasetUpdate(GisInput):
    expected_revision: Revision
    title: Label


class EditionCreate(GisInput):
    manifest: SourceManifest


class EditionUpdate(GisInput):
    expected_revision: Revision
    manifest: SourceManifest


class ExpectedRevision(GisInput):
    expected_revision: Revision


class JobRetry(GisInput):
    expected_revision: Revision
    input_hash: Hash
    reason: Reason


class Activation(GisInput):
    edition_id: UUID
    expected_revision: Revision
    expected_active_edition_id: UUID | None
    reason: Reason


class Withdrawal(GisInput):
    expected_revision: Revision
    expected_dataset_revision: Revision
    expected_active_edition_id: UUID | None
    replacement_edition_id: UUID | None
    reason: Reason


class OfficerGrant(GisInput):
    user_id: UUID
    reason: Reason


class OfficerRevoke(GisInput):
    reason: Reason


class PageCursor(GisInput):
    created_at: datetime
    id: UUID

    @field_validator("created_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cursor timestamp requires an explicit timezone")
        return value


class PageQuery(GisInput):
    # Query strings are textual; FastAPI/Pydantic parse their integers here.
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    cursor: Annotated[str, StringConstraints(max_length=512)] | None = None


class LddUploadQuery(GisInput):
    expected_revision: Annotated[int, Field(ge=1, le=2147483647)]
    crs: Literal['EPSG:32647', 'EPSG:32648', 'EPSG:4326'] = 'EPSG:32647'
    encoding: Literal['auto', 'utf-8', 'cp874', 'tis-620'] = 'auto'
    source_label: SourceLabel


class GeoTiffUploadQuery(GisInput):
    expected_revision: Annotated[int, Field(ge=1, le=2147483647)]
    crs: Literal['EPSG:32647', 'EPSG:32648', 'EPSG:4326']
    profile: Literal['ndvi_ready', 'lst_celsius_ready', 'lst_kelvin_ready', 'ndvi_bands', 'lst_st_b10']
    source_label: SourceLabel
    acquisition_date: date


class ProcessingCreate(GisInput):
    province: Province
    district: Province | None = None
    metric: Literal['ndvi', 'lst']
    data_year: Annotated[int, Field(strict=True)]
    month: Month = 0
    # gee_dashboard (migration 048): real GEE through the existing Dashboard backend
    # path; it has no synthetic scenarios, so only 'standard' is accepted for it.
    mode: Literal['offline_synthetic', 'gee_dashboard'] = 'offline_synthetic'
    scenario: Literal['standard', 'no_data', 'transient_once'] = 'standard'
    expected_revision: Literal[1] = 1

    @field_validator('expected_revision', mode='before')
    @classmethod
    def new_processing_revision(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError('new immutable processing request requires revision 1')
        return value

    @model_validator(mode='after')
    def processing_year(self):
        earliest = 2017 if self.metric == 'ndvi' else 2013
        if not earliest <= self.data_year <= date.today().year:
            raise ValueError('year outside supported source range')
        if self.mode == 'gee_dashboard' and self.scenario != 'standard':
            raise ValueError('Google Earth Engine processing has no synthetic scenarios')
        return self


class ProcessingQuery(PageQuery):
    state: JobState | None = None
    metric: Literal['ndvi', 'lst'] | None = None
    province: Province | None = None


class ProcessingOptions(GisInput):
    province: Province | None = None


class DatasetQuery(PageQuery):
    province: Province | None = None
    data_year: Annotated[int, Field(ge=1980)] | None = None
    month: Annotated[int, Field(ge=0, le=12)] | None = None
    kind: Kind | None = None
    purpose: Purpose | None = None

    @field_validator("data_year")
    @classmethod
    def source_year(cls, value):
        if value is not None and value > date.today().year + 1:
            raise ValueError("data_year exceeds the supported CE source year")
        return value


class EditionQuery(PageQuery):
    state: EditionState | None = None


class JobQuery(DatasetQuery):
    state: JobState | None = None
    edition_id: UUID | None = None
    dataset_id: UUID | None = None
