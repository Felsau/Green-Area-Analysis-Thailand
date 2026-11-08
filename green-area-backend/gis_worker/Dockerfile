# The runtime the GIS native workers read shapefiles and GeoTIFFs in.
#
# Why this file exists: the LDD and GeoTIFF tests assert that the artifacts they
# produce are byte-identical to frozen fixtures, and those bytes depend on the
# GDAL/GEOS/PROJ builds bundled inside the wheels AND on the system libraries
# underneath them. The same fiona 1.10.1 and shapely 2.2.0 produce the frozen
# bytes under python:3.11-slim and different bytes on a GitHub ubuntu-24.04
# runner. Pinning the wheel versions is necessary but not sufficient; the image
# is what actually pins the result.
#
# GIS_NATIVE_RUNTIME=pinned is what switches that check on. It is set here and
# nowhere else, so the check runs exactly where the claim is true.
#
# Build from the backend directory, not from this one:
#   docker build -f gis_worker/Dockerfile -t gis-native-runtime:local green-area-backend
#
# The worker source is mounted read-only at /app/gis_worker at run time (see
# dev/gis_local/manage.py); it is deliberately not copied in, so the image does
# not have to be rebuilt when the worker code changes.
FROM python:3.11-slim

# rasterio's wheel dlopens libexpat; without it the import fails with
# "libexpat.so.1: cannot open shared object file".
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-native.txt /tmp/requirements-native.txt
RUN pip install --no-cache-dir -r /tmp/requirements-native.txt \
    && rm /tmp/requirements-native.txt

ENV GIS_NATIVE_RUNTIME=pinned \
    PYTHONDONTWRITEBYTECODE=1 \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1 \
    GDAL_NUM_THREADS=1 \
    PROJ_NETWORK=OFF

WORKDIR /app/gis_worker
