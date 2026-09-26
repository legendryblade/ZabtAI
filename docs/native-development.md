# Native Windows development

This setup runs the application without Docker. The project stays in one folder; PostgreSQL, Redis, S3-compatible storage, Python 3.11, Node.js, and FFmpeg are external services and do not need to be moved with the repository.

## 1. Install system services

Install PostgreSQL 16 and Redis with Chocolatey, and MinIO Server with winget:

```powershell
choco install postgresql16 redis -y --no-progress
winget install --id MinIO.Server --exact --accept-source-agreements --accept-package-agreements
```

If a service is already installed, skip its install command. Verify the listeners:

```powershell
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 5432,6379,9000,9001
```

## 2. Configure the application environment

The project folder is portable. Run the setup script from the repository root; it creates a user-local Python environment and leaves the project files in place:

```powershell
Set-Location D:\ZabtAI
.\scripts\setup-native.ps1
```

The script preserves an existing `.env`. If the file does not exist, it creates one from `.env.native.example`:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.native.example .env }
notepad .env
```

Set `OPENAI_API_KEY` and `DEEPGRAM_API_KEY` in `.env`. For Groq transcription, use `TRANSCRIPTION_BACKEND=groq` and `GROQ_API_KEY` instead. The template enables single-user mode and does not require Supabase.

## 3. Create the PostgreSQL database

Open a PowerShell window as the PostgreSQL administrator and connect with the password chosen during installation:

```powershell
psql -h localhost -U postgres
```

Run:

```sql
CREATE ROLE app LOGIN PASSWORD 'app';
CREATE DATABASE zabt OWNER app;
```

If the role or database already exists, ignore the corresponding duplicate-object error.

## 4. Start Redis and MinIO

Redis can be started as a Windows service or from a terminal:

```powershell
redis-server --bind 127.0.0.1 --port 6379
```

Start MinIO in a separate terminal. The webhook target must use the same secret as `MINIO_WEBHOOK_SECRET` in `.env`:

```powershell
$env:MINIO_ROOT_USER = "minioadmin"
$env:MINIO_ROOT_PASSWORD = "minioadmin"
$env:MINIO_NOTIFY_WEBHOOK_ENABLE_PRIMARY = "on"
$env:MINIO_NOTIFY_WEBHOOK_ENDPOINT_PRIMARY = "http://localhost:8000/api/v1/webhooks/minio"
$env:MINIO_NOTIFY_WEBHOOK_AUTH_TOKEN_PRIMARY = "Bearer local-dev-webhook-secret"
$env:MINIO_NOTIFY_WEBHOOK_QUEUE_DIR_PRIMARY = "C:\minio-data\.events"
minio server C:\minio-data --console-address ":9001"
```

After MinIO is ready, create the bucket and webhook subscription from another terminal:

```powershell
mc alias set local http://localhost:9000 minioadmin minioadmin
mc mb --ignore-existing local/zabt-ai-bucket
mc event add local/zabt-ai-bucket arn:minio:sqs::PRIMARY:webhook --event put --ignore-existing
```

## 5. Install the Python environment

The setup script creates this environment and installs `backend/requirements-dev.txt`. To run the commands manually, use Python 3.11 rather than the system Python 3.14 interpreter:

```powershell
py -3.11 -m venv C:\Users\abdul\.venvs\zabt-backend
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m pip install --upgrade pip
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m pip install -r D:\ZabtAI\backend\requirements-dev.txt
```

Initialize the database and start the API:

```powershell
Set-Location D:\ZabtAI\backend
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m alembic upgrade head
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Run the Celery worker and beat scheduler in separate terminals:

```powershell
Set-Location D:\ZabtAI\backend
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m celery -A app.worker.celery_app worker --loglevel=info
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m celery -A app.worker.celery_app beat --loglevel=info
```

## 6. Start the frontend

```powershell
Set-Location D:\ZabtAI
npm install
npm run build:shared
npm run dev:web
```

Open `http://localhost:3000`. Upload an audio/video file or a YouTube URL from the meeting screen. The API documentation is at `http://localhost:8000/docs`.

## 7. Tests

```powershell
Set-Location D:\ZabtAI\backend
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m pytest
```
