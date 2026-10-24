# Quran Journey API (Teacher + Parent)

This service is a backend foundation for moving Quran Journey data from browser-only localStorage to Neon PostgreSQL. There is no student login.

## Roles
- **Teacher:** can list students, create students and parent accounts, and add reading, attendance, and point records.
- **Parent:** can only list linked children and read their records.
- Student IDs are records, not login accounts.

## Deploy to Render
1. Create a Web Service from this repository and set **Root Directory** to `backend`.
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in Render:
   - `DATABASE_URL`: Neon connection string (keep it secret; server-side only).
   - `JWT_SECRET`: long random secret, at least 32 characters.
   - `INITIAL_TEACHER_ID`: desired first teacher login ID.
   - `INITIAL_TEACHER_PASSWORD`: unique password of at least 12 characters.
   - `CORS_ORIGINS`: `https://safumk99-byte.github.io`
   - `ACCESS_TOKEN_MINUTES`: `60`
5. The service creates its initial tables at startup and seeds the first teacher only if the configured ID does not already exist.

## API
- `GET /health`
- `POST /auth/login` body: `{"login_id":"...","password":"..."}`
- `GET /auth/me` with `Authorization: Bearer <token>`
- `GET /students`
- Teacher only: `POST /students`, `POST /parents`
- Reading: `GET/POST /students/{id}/reading`
- Attendance: `GET/POST /students/{id}/attendance`
- Points: `GET/POST /students/{id}/marks`

Interactive API docs are available at `/docs` after deployment.

## Important migration notes
- This API does not automatically import the browser's existing localStorage data.
- The current static website has not yet been switched to this API. Keep the existing site in use until backup/export, API deployment, role tests, and frontend integration are completed.
- Database schema creation is suitable for the initial scaffold; use versioned migrations before production schema changes.
- Never commit real credentials, tokens, or a Neon connection string to GitHub.

## Frontend authentication foundation
The static frontend now has `login.html`, `auth.js`, `config.js`, and a read-only `parent.html` view. Before frontend sign-in can reach the API, set `window.QURAN_JOURNEY_CONFIG.API_BASE_URL` in the root `config.js` to the public Render service URL (for example, `https://your-api.onrender.com`, with no trailing slash). Do not put the Neon connection string or JWT signing secret in this file.

The teacher pages are protected by role checks. Existing student and daily-mark features still use browser localStorage; they have not yet been migrated or synchronized with PostgreSQL. Do not assume old browser records have been imported. Parent record views read from the API and will show only records stored there for students linked to that parent.
