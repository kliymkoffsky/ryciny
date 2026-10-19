ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base-debian:bookworm
FROM ${BUILD_FROM}

# Python 3.11 from Debian (ai-edge-litert ships manylinux wheels), parec to read the microphone from HA's PulseAudio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv pulseaudio-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /app/requirements.txt
COPY app /app
ARG INCLUDE_ANIMATIONS=1
RUN case "$INCLUDE_ANIMATIONS" in \
      1|true) ;; \
      0|false) rm -rf /app/ryciny/prepared-animations ;; \
      *) echo "INCLUDE_ANIMATIONS must be 1, 0, true, or false" >&2; exit 1 ;; \
    esac
COPY run.sh /run.sh

WORKDIR /app
ENV PYTHONUNBUFFERED=1
CMD ["/run.sh"]
