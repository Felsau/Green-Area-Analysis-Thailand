# Rebuild recipe for the GIS base image gis-linux-poc:20261026 (W3, drafted 8 Nov 2026; not built yet).
#
# Original image on the author's machine:
#   Id/manifest index sha256:fca4560d8a0d0198c0eb75fbf6598314cd8ed4a5e8bafa00e1d7298126aa04c9
#   Created 2026-10-26T12:31:41Z, linux/amd64, 578 MB on disk, 7 layers. Every worker image builds on it
#   (dev/gis_local/manage.py WORKER_IMAGE; dev/gis_local/gee_mock.Dockerfile FROM).
# The exact bytes are kept by `docker save` (OCI layout; index.json names the digest above):
#   C:\Users\chaya\gis-image-backup\gis-linux-poc_20261026.tar  (137,613,312 bytes)
#   SHA256 BD0C4B65472A06835142A2B0521BFD89DDD01CF91E3E0F41324192BC09496C40
#   Restore the identical image with: docker load -i gis-linux-poc_20261026.tar
#
# This file rebuilds an EQUIVALENT image, not the same digest: apt and pip fetch at build time, and
# file and config timestamps differ, so the new digest will differ even with every version pinned.
#
# What is known and what is inferred (source: docker history --no-trunc, image inspect, the saved layers):
#   KNOWN  every instruction after FROM: the commands are copied verbatim from `docker history`;
#          there is no COPY/ADD layer, so no build-context file is needed.
#   KNOWN  installed versions, read from the saved layers (dist-info folders, var/lib/dpkg/status):
#          Debian 12 bookworm: libexpat1 2.5.0-1+deb12u5, libstdc++6 / libgcc-s1 / gcc-12-base 12.2.0-14+deb12u1
#          Python: affine 3.0.1, attrs 26.1.0, certifi 2026.10.23, click 8.5.0, click_plugins 1.1.1.2,
#          cligj 0.7.2, fiona 1.10.1, iniconfig 2.3.1, numpy 2.4.6, pluggy 1.7.0, psycopg 3.3.6,
#          psycopg_binary 3.3.6, pygments 2.21.0, pyparsing 3.3.3, pytest 9.1.1, rasterio 1.4.4,
#          shapely 2.2.0, typing_extensions 4.16.0
#   INFERRED the base: python:3.11-slim-bookworm, image id sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf
#          on this machine (created 2026-10-21, Python 3.11.17). Its 4 layers equal the first 4 layers of the
#          original byte for byte (RootFS diff ids). Not checked: that this digest can still be pulled from
#          Docker Hub. If it cannot, any python:3.11.17-slim-bookworm should be equivalent apart from Debian
#          security updates.
#   GUESSED  the original Dockerfile text itself (comments, line breaks, any `# syntax=` line): history only
#          keeps the resulting commands. BuildKit built it (history entries end with "# buildkit").
#   NOT PINNED in the original: the apt package versions and the transitive pip dependencies were whatever
#          the mirrors served on 26 Oct 2026; the versions listed above are what that produced.
#
# Build (needs network for apt and PyPI; use a NEW tag, never overwrite gis-linux-poc:20261026):
#   docker build -f dev/gis_local/gis_linux_poc.Dockerfile -t gis-linux-poc:rebuild-test dev/gis_local
FROM python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Same direct requirements as the original. The original did not pin the transitive dependencies; to rebuild
# closer to it, append the KNOWN versions above (affine==3.0.1 attrs==26.1.0 ...) to this line.
RUN python -m pip install --no-cache-dir --only-binary=:all: \
    rasterio==1.4.4 fiona==1.10.1 shapely==2.2.0 numpy==2.4.6 \
    pytest==9.1.1 psycopg[binary]==3.3.6

WORKDIR /poc

CMD ["sleep", "infinity"]
