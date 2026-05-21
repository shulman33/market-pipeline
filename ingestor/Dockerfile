FROM python:3.14-slim

WORKDIR /app

COPY ingestor/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ingestor/ ./ingestor/
COPY sql/ ./sql/

CMD ["python", "-m", "ingestor.main"]
