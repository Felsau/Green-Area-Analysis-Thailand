from uuid import UUID

import pytest
from pydantic import ValidationError

from gis_publication import ArtifactRegistration, SourceIdentity

ID = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'


def identity(namespace='legacy', **changes):
    value = dict(namespace=namespace, product='ndvi', province='Bangkok Metropolis',
                 data_year=2024, month=0, method_version='ndvi-ready-v1')
    if namespace == 'published':
        value.update(dataset_id=ID, edition_id=ID, validation_result_id=ID,
                     input_hash='a' * 64, source_sha256='b' * 64)
    return value | changes


def registration(**changes):
    return dict(edition_id=ID, expected_dataset_revision=1, expected_input_revision=1,
                input_hash='a' * 64, validation_result_id=ID, source_sha256='b' * 64,
                artifact_kind='ndvi_summary', artifact_sha256='c' * 64, byte_size=50,
                method_version='ndvi-ready-v1', reason='A1 synthetic declaration') | changes


def test_legacy_and_published_can_never_share_cache_namespace():
    legacy = SourceIdentity(**identity())
    published = SourceIdentity(**identity('published'))
    assert legacy.cache_namespace() != published.cache_namespace()
    assert legacy.cache_namespace().startswith('gis-source-v1:legacy:')
    assert published.cache_namespace().startswith('gis-source-v1:published:')


@pytest.mark.parametrize('field,value', [('edition_id', OTHER), ('dataset_id', OTHER),
    ('validation_result_id', OTHER), ('input_hash', 'd'*64), ('source_sha256', 'e'*64),
    ('data_year', 2023), ('month', 2), ('province', 'Chiang Mai'), ('method_version', 'v2'), ('product', 'lst')])
def test_cache_keys_are_bound_to_complete_source_identity(field, value):
    first = SourceIdentity(**identity('published'))
    assert first.cache_namespace() != SourceIdentity(**identity('published', **{field: value})).cache_namespace()


@pytest.mark.parametrize('field', ['dataset_id','edition_id','validation_result_id','input_hash','source_sha256'])
def test_published_requires_lineage_and_legacy_rejects_it(field):
    with pytest.raises(ValidationError):
        SourceIdentity(**identity('published', **{field: None}))
    value = 'a'*64 if field.endswith('hash') or field == 'source_sha256' else ID
    with pytest.raises(ValidationError):
        SourceIdentity(**identity(**{field: value}))


@pytest.mark.parametrize('changes', [dict(scope='district'), dict(namespace='offline_synthetic'),
    dict(data_year=True), dict(month=True), dict(product='landuse', month=1),
    dict(method_version='../v1'), dict(method_version='https://example.invalid'), dict(ready=True)])
def test_source_identity_refuses_scope_confusion_and_untrusted_flags(changes):
    with pytest.raises(ValidationError):
        SourceIdentity(**identity(**changes))


def test_artifact_is_a_logical_content_address_and_has_no_readiness_authority():
    item = ArtifactRegistration(**registration())
    assert item.edition_id == UUID(ID)
    assert item.object_key() == 'sha256/' + 'c'*64 + '/ndvi_summary'
    assert 'ready' not in item.model_dump()


@pytest.mark.parametrize('changes', [dict(byte_size=0),dict(byte_size=20*1024**2+1),dict(byte_size=True),
    dict(byte_size=1.5),dict(expected_dataset_revision=True),dict(expected_input_revision=1.1),
    dict(artifact_sha256='A'*64),dict(source_sha256='wrong'),dict(artifact_kind='command'),
    dict(method_version='x/y'),dict(reason='  '),dict(path='/tmp/input'),
    dict(url='https://example.invalid'),dict(ready=True),dict(coverage_verified=True),dict(object_key='../x')])
def test_artifact_declarations_fail_closed(changes):
    with pytest.raises(ValidationError):
        ArtifactRegistration(**registration(**changes))
