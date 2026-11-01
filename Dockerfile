FROM node:24-alpine AS frontend-build

WORKDIR /workspace
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend ./frontend
COPY app ./app
RUN cd frontend && npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend-build /workspace/app/static/admin ./app/static/admin

EXPOSE 9900

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9900/health', timeout=2)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9900"]
