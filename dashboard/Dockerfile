FROM python:3.14-slim

WORKDIR /app

COPY dashboard/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard/ ./dashboard/

EXPOSE 8501

CMD ["streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
