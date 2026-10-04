FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1
EXPOSE 1785
HEALTHCHECK --interval=5m --timeout=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:1785/api/status')"
CMD ["python", "app.py"]
