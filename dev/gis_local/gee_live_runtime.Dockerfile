# Offline probe image only. Verify this existing local tag resolves to the
# locked base SHA before build and verify inherited layers afterwards.
# No pulls, RUN/install steps, Google SDK, credentials or external network.
FROM gis-gee-mock:20261104-a63
COPY gis_worker/ /app/gis_worker/
COPY source-manifest.json /app/source-manifest.json
ARG SOURCE_TREE_SHA256
LABEL gis.a6.4d2.scope="offline-runtime-probe" \
      gis.a6.4d2.source="${SOURCE_TREE_SHA256}" \
      gis.a6.4d2.egress="gee-live-deny-external-v1"
USER 65534:65534
WORKDIR /app/gis_worker
ENTRYPOINT ["/usr/local/bin/python3", "-I", "-B", "/app/gis_worker/gee_runtime_probe.py"]
CMD []
