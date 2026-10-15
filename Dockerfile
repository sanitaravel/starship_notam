FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the pinned dependencies (direct + "lock" and "postgres" extras) from
# pyproject.toml before copying the source, so code changes do not reinstall
# them.
COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; extras = p['optional-dependencies']; print('\n'.join(p['dependencies'] + extras['lock'] + extras['postgres']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The bot runs from /app (not site-packages): it finds fonts/, maps/ and logs/
# relative to the project root.
COPY fonts ./fonts
COPY src ./src
COPY main.py prefill_compass.py prefill_federal_register.py prefill_regulations_gov.py prefill_sec_edgar.py ./

RUN useradd --create-home --uid 1000 app \
    && mkdir -p maps logs /home/app/.local/share/cartopy \
    && chown -R app:app maps logs /home/app/.local
USER app

# Last, so a new commit does not invalidate the cached layers above. CI passes
# the commit SHA; local builds report "dev".
ARG GIT_SHA=dev
ENV NOTAM_VERSION=$GIT_SHA
LABEL org.opencontainers.image.source="https://github.com/sanitaravel/starship_notam"       org.opencontainers.image.revision=$GIT_SHA

CMD ["python", "-m", "src"]
