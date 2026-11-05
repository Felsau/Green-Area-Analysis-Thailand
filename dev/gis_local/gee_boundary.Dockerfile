# Launcher verifies this local tag's EXACT image ID before/after building.
# No RUN, downloads, credentials, bind mounts or new dependencies.
FROM gis-gee-mock:20261104-a63
COPY sdk/ /sdk/
COPY gis_worker/ /app/gis_worker/
COPY tests/ /app/tests/
COPY boundary_entry.py /app/boundary_entry.py
COPY source-manifest.json /app/source-manifest.json
ARG SOURCE_TREE_SHA256
LABEL gis.a6.boundary.scope="offline-boundary-only" \
      gis.a6.boundary.source="${SOURCE_TREE_SHA256}"
USER 65534:65534
WORKDIR /app
ENTRYPOINT ["/usr/local/bin/python3", "-I", "-B", "/app/boundary_entry.py"]
CMD []
