FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir . && mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "tauros.api:app", "--host", "0.0.0.0", "--port", "8000"]
