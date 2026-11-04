# A6.3 optional Local mock runtime; never replace the original GIS image.
# Build context is an isolated folder containing ONLY reviewed Linux wheels
# and wheel-sha256.txt. Verify this existing tag resolves to the SHA below and
# use the classic local builder (--pull=false --network=none) to avoid registry
# metadata resolution. Base: sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9
FROM gis-linux-poc:20261026
COPY wheels/ /tmp/a63-wheels/
COPY wheel-sha256.txt /tmp/a63-wheels/wheel-sha256.txt
RUN cd /tmp/a63-wheels \
    && sha256sum -c wheel-sha256.txt \
    && python3 -m pip --isolated install --no-index --no-deps --no-cache-dir ./*.whl \
    && rm -rf /tmp/a63-wheels
USER 65534:65534
WORKDIR /app/gis_worker
