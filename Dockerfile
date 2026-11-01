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

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9900"]
