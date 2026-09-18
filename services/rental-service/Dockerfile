FROM python:3.11-slim

WORKDIR /app

# Instala dependências
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código-fonte
COPY src/ /app/src/

WORKDIR /app/src

EXPOSE 8002

ENV CATALOG_SERVICE_URL="http://catalog-service:8001"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
