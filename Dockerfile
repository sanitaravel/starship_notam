FROM python:3.12.15-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install the pinned dependencies (direct + "lock" extras) from pyproject.toml
# before copying the source, so code changes do not reinstall them.
COPY pyproject.toml ./
RUN python -c "import tomllib; p = tomllib.load(open('pyproject.toml', 'rb'))['project']; print('\n'.join(p['dependencies'] + p['optional-dependencies']['lock']))" > /tmp/requirements.txt \
    && pip install -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# The bot runs from /app (not site-packages): it finds fonts/, maps/ and logs/
# relative to the project root.
COPY fonts ./fonts
COPY starship_notam ./starship_notam
COPY main.py prefill_compass.py ./

RUN useradd --create-home --uid 1000 app \
    && mkdir -p data maps logs /home/app/.local/share/cartopy \
    && chown -R app:app data maps logs /home/app/.local
USER app

CMD ["python", "-m", "starship_notam"]
