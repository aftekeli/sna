# Manual Vercel Deployment Guide (`prod` branch)

This guide documents the manual Vercel deployment flow currently used for the production-ready `prod` branch of this repository.

The application is deployed as two separate Vercel projects under the `engaftekeli-4413s-projects` team:

- `sna-backend` deploys from the repository root
- `sna-frontend` deploys from the `frontend/` directory

## Deployment Model

### Backend

- Project name: `sna-backend`
- Vercel root: repository root
- Production URL: `https://sna-backend.vercel.app`

### Frontend

- Project name: `sna-frontend`
- Vercel root: `frontend/`
- Production URL: `https://sna-frontend-eight.vercel.app`

## Prerequisites

Before deploying manually, make sure the following are available:

- a valid `VERCEL_TOKEN` stored in the project `.env`
- Vercel CLI available through `npx vercel`
- production secrets already added to the Vercel projects
- latest production code pushed to the `prod` branch

The team scope used in commands below is:

```text
engaftekeli-4413s-projects
```

## Required Environment Variables

### Backend project: `sna-backend`

Production environment variables expected by the backend project:

- `APP_ENV=production`
- `APP_DEBUG=false`
- `GROQ_API_KEY`
- `GROQ_MODEL`
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE`
- `APP_ALLOWED_ORIGINS`
- `RUNTIME_STORAGE_ROOT=/tmp/sna-runtime`
- `VERCEL_FORCE_PYTHON_STREAMING=1`

Recommended value for `APP_ALLOWED_ORIGINS`:

```text
https://sna-frontend-eight.vercel.app,https://sna-frontend-engaftekeli-4413s-projects.vercel.app,https://sna-frontend-engaftekeli-engaftekeli-4413s-projects.vercel.app
```

### Frontend project: `sna-frontend`

Production environment variables expected by the frontend project:

- `NEXT_PUBLIC_BACKEND_API_BASE_URL=https://sna-backend.vercel.app`
- `BACKEND_API_BASE_URL=https://sna-backend.vercel.app`

## PowerShell Helper

If `VERCEL_TOKEN` is stored in the repository `.env`, load it in PowerShell before running deploy commands:

```powershell
$tokenLine = Get-Content .env | Where-Object { $_ -match '^VERCEL_TOKEN=' } | Select-Object -First 1
$token = $tokenLine.Substring('VERCEL_TOKEN='.Length).Trim()
```

## Manual Backend Deployment

Run these commands from the repository root:

```powershell
$tokenLine = Get-Content .env | Where-Object { $_ -match '^VERCEL_TOKEN=' } | Select-Object -First 1
$token = $tokenLine.Substring('VERCEL_TOKEN='.Length).Trim()

npx vercel deploy --prod --yes --scope engaftekeli-4413s-projects --token $token
```

After deployment, verify the backend:

```powershell
Invoke-WebRequest -Uri 'https://sna-backend.vercel.app/health' -UseBasicParsing
Invoke-WebRequest -Uri 'https://sna-backend.vercel.app/dashboard/overview' -UseBasicParsing
Invoke-WebRequest -Uri 'https://sna-backend.vercel.app/chat/bootstrap' -UseBasicParsing
```

## Manual Frontend Deployment

Run these commands from the `frontend/` directory:

```powershell
$tokenLine = Get-Content ..\.env | Where-Object { $_ -match '^VERCEL_TOKEN=' } | Select-Object -First 1
$token = $tokenLine.Substring('VERCEL_TOKEN='.Length).Trim()

npx vercel deploy --prod --yes --scope engaftekeli-4413s-projects --token $token
```

After deployment, verify the frontend:

```powershell
Invoke-WebRequest -Uri 'https://sna-frontend-eight.vercel.app/' -UseBasicParsing
Invoke-WebRequest -Uri 'https://sna-frontend-eight.vercel.app/dashboard' -UseBasicParsing
Invoke-WebRequest -Uri 'https://sna-frontend-eight.vercel.app/chat' -UseBasicParsing
```

## Recommended Deployment Order

Use this order for manual production releases:

1. Push the latest code to `prod`
2. Deploy `sna-backend` from the repository root
3. Confirm backend health and dashboard endpoints
4. Deploy `sna-frontend` from `frontend/`
5. Confirm the frontend loads correctly against the production backend

## Notes

- The backend uses a thin root-level Vercel entrypoint and reads static project artifacts from the repository.
- Runtime chat and quota state is written to temporary storage under `/tmp/sna-runtime` in production.
- Automatic GitHub-triggered deployment is not required for this workflow; deployments can be completed fully from the terminal with the Vercel token.
