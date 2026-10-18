FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY agents agents
COPY app app
COPY web web
COPY data data
ENV PORT=8080 DATA_DIR=/srv/data
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 120"]
