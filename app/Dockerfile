# The Arkon cockpit, for the NAS. Built from the repository root:
#
#   docker compose build      (see app/docker-compose.yml)
#
# The build context is the repository root rather than app/, because the app
# reads two things outside its own directory: the tracked metrics files and the
# tracked figures. Both are copied in; nothing else is, and no model weight ever
# enters this image.
FROM python:3.12-slim

WORKDIR /srv/arkon

COPY app/requirements.txt /srv/arkon/app/requirements.txt
RUN pip install --no-cache-dir -r /srv/arkon/app/requirements.txt

# The three things the pages read. models/ is otherwise gitignored; the metrics
# files are the tracked exception and are the only part of it copied here.
COPY app/ /srv/arkon/app/
COPY assets/ /srv/arkon/assets/
COPY models/checkpoints/ /srv/arkon/models/checkpoints/

# The live plant (the `live-plant` service in docker-compose.yml) runs from the
# same image: the emitter, the event contract it validates against, the roster
# and the seven published batches it draws real model output from. Stdlib only,
# so nothing is added to requirements.
COPY live_plant/plant.py /srv/arkon/live_plant/plant.py
COPY events/ /srv/arkon/events/

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health',timeout=4)"

CMD ["streamlit", "run", "app/main.py", \
     "--server.port", "8501", \
     "--server.address", "0.0.0.0", \
     "--server.headless", "true", \
     "--browser.gatherUsageStats", "false"]
