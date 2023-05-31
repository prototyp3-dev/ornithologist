# syntax=docker.io/docker/dockerfile:1.4

ARG DAPP_BIRDS_FILE=birds_data.csv
ARG DAPP_BIRDS_GEO_FILE=birds_geo.gpkg

# build stage: includes resources necessary for installing dependencies
FROM --platform=linux/riscv64 cartesi/python:3.10-slim-jammy as build-stage

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential=12.9ubuntu3 \
    libgdal-dev=3.4.1+dfsg-1build4 \
    python3-numpy=1:1.21.5-1ubuntu22.04.1 \
    python3-shapely=1.8.0-1build1 \
    python3-pandas=1.3.5+dfsg-3 \
    python3-pyproj=3.3.0-2build1 \
    wget unzip

ARG EEA_BIRDS_FILE=Article12_2020_birdsEUpopulation.csv
ARG AVONET_BIRDS_FILE=AVONET1_BirdLife.csv
ARG DAPP_BIRDS_FILE
ARG DAPP_BIRDS_GEO_FILE

WORKDIR /opt/cartesi/dapp

# libblas3 libgfortran5 liblapack3 libmpdec3 libpython3-stdlib libpython3.10-minimal libpython3.10-stdlib libsqlite3-0 media-types python3 python3-minimal python3-numpy python3-pkg-resources python3.10 python3.10-minimal
# libgeos-c1v5 libgeos3.10.2 python3-shapely

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/opt/venv/lib/python3.10/site-packages:/usr/lib/python3/dist-packages
COPY dapp/requirements.txt .

RUN pip install -r requirements.txt --no-cache


COPY dapp/files .
COPY dapp/files_shasum .
RUN while read DEP; do wget -O $DEP; done < files
RUN sha1sum -c files_shasum
RUN ["/bin/bash", "-c", "while read ZIP; do unzip $ZIP; done <<< $(ls | grep zip)"]
RUN find . -type f -name *.gpkg -exec mv {} ${DAPP_BIRDS_GEO_FILE} \;
RUN find . -type f -name ${EEA_BIRDS_FILE} -exec cp {} . \;
RUN find . -type f -name ${AVONET_BIRDS_FILE} -exec cp {} . \;

COPY dapp/prepare-data.py .
RUN python3 prepare-data.py


# runtime stage: produces final image that will be executed
FROM --platform=linux/riscv64 cartesi/python:3.10-slim-jammy

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    libgdal-dev=3.4.1+dfsg-1build4 \
    python3-numpy=1:1.21.5-1ubuntu22.04.1 \
    python3-shapely=1.8.0-1build1 \
    python3-pandas=1.3.5+dfsg-3 \
    python3-pyproj=3.3.0-2build1 \
    && rm -rf /var/lib/apt/lists/* \
    && find /var/log \( -name '*.log' -o -name '*.log.*' \) -exec truncate -s 0 {} \;

ARG DAPP_BIRDS_FILE
ARG DAPP_BIRDS_GEO_FILE

COPY --from=build-stage /opt/venv /opt/venv

RUN find /usr/lib/python3/dist-packages -type d -name __pycache__ -exec rm -r {} + \
    && find /opt/venv/lib/python3.10/site-packages -type d -name __pycache__ -exec rm -r {} +

WORKDIR /opt/cartesi/dapp
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH=/opt/venv/lib/python3.10/site-packages:/usr/lib/python3/dist-packages

# COPY dapp/entrypoint.sh .
COPY dapp/ornithologist.py .
COPY --from=build-stage /opt/cartesi/dapp/${DAPP_BIRDS_FILE} . 
COPY --from=build-stage /opt/cartesi/dapp/${DAPP_BIRDS_GEO_FILE} . 

RUN <<EOF
echo '
#!/bin/sh
set -e
export PATH=/opt/venv/bin:$PATH
export PROJ_LIB=/usr/share/proj
' >> entrypoint.sh
echo "
export PYTHONPATH=/opt/venv/lib/python3.10/site-packages:/usr/lib/python3/dist-packages
export DAPP_BIRDS_FILE=${DAPP_BIRDS_FILE}
export DAPP_BIRDS_GEO_FILE=${DAPP_BIRDS_GEO_FILE}
rollup-init python3 ornithologist.py
" >> entrypoint.sh
chmod +x entrypoint.sh
EOF