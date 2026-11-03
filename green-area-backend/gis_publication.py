"""A1 publication contracts only: no files, clients, credentials or activation.

Source identity describes provenance, never evidence that an artifact is ready.
The authoritative A1 SQL readiness remains false until a trusted verifier exists.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Hash = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{64}$')]
Method = Annotated[str, StringConstraints(strict=True, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')]
Revision = Annotated[int, Field(strict=True, ge=1, le=999999999)]
Province = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100, strip_whitespace=True)]


class PublicationContract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class SourceIdentity(PublicationContract):
    namespace: Literal['legacy', 'published']
    scope: Literal['province'] = 'province'
    product: Literal['landuse', 'ndvi', 'lst']
    province: Province
    data_year: Annotated[int, Field(strict=True, ge=1980, le=2200)]
    month: Annotated[int, Field(strict=True, ge=0, le=12)]
    method_version: Method
    dataset_id: UUID | None = None
    edition_id: UUID | None = None
    validation_result_id: UUID | None = None
    input_hash: Hash | None = None
    source_sha256: Hash | None = None

    @model_validator(mode='after')
    def separate_namespaces(self):
        lineage = (self.dataset_id, self.edition_id, self.validation_result_id, self.input_hash, self.source_sha256)
        if self.product == 'landuse' and self.month != 0:
            raise ValueError('LDD must identify an annual dataset')
        if self.namespace == 'legacy' and any(v is not None for v in lineage):
            raise ValueError('Legacy identity cannot contain publication lineage')
        if self.namespace == 'published' and any(v is None for v in lineage):
            raise ValueError('Published identity requires complete immutable lineage')
        return self

    def cache_namespace(self) -> str:
        """Future reader key; intentionally unused by legacy readers in A1."""
        raw = json.dumps(self.model_dump(mode='json', exclude_none=True), sort_keys=True, separators=(',', ':'))
        return 'gis-source-v1:' + self.namespace + ':' + hashlib.sha256(raw.encode()).hexdigest()


class ArtifactRegistration(PublicationContract):
    edition_id: UUID
    expected_dataset_revision: Revision
    expected_input_revision: Revision
    input_hash: Hash
    validation_result_id: UUID
    source_sha256: Hash
    artifact_kind: Literal['ldd_geometry', 'ldd_summary', 'ndvi_raster', 'ndvi_summary', 'lst_raster', 'lst_summary']
    artifact_sha256: Hash
    byte_size: Annotated[int, Field(strict=True, ge=1, le=20 * 1024**2)]
    method_version: Method
    reason: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]

    def object_key(self) -> str:
        """Logical content address, NOT a filesystem path or upload permission."""
        return f'sha256/{self.artifact_sha256}/{self.artifact_kind}'
