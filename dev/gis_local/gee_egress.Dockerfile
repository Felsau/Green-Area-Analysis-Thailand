# A6 egress proof image. Launcher verifies the base tag's EXACT image ID first.
# No RUN, downloads, credentials, SDK, bind mounts or new dependencies.
FROM gis-gee-mock:20261104-a63
COPY gis_worker/ /app/gis_worker/
COPY egress_entry.py /app/egress_entry.py
COPY source-manifest.json /app/source-manifest.json
ARG SOURCE_TREE_SHA256
LABEL gis.a6.egress.scope="offline-egress-proof" \
      gis.a6.egress.source="${SOURCE_TREE_SHA256}"
USER 65534:65534
WORKDIR /app
ENTRYPOINT ["/usr/local/bin/python3", "-I", "-B", "/app/egress_entry.py"]
CMD []
