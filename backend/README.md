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
- `GET /students` (includes Quran journey totals, current Juz, start date and photo data)
- Teacher only: `POST /migration/localstorage` to import the JSON downloaded from the existing Backup page
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

## Safe legacy backup import

1. Open the existing website in the same browser profile that contains the teacher's local data.
2. Sign in as Teacher and open `backup.html`; download the JSON backup. Keep it private because it can contain student names, photos, reading records and marks.
3. Open `migration.html`, choose the downloaded JSON, click **Validate Backup**, review the counts, then click **Import to Database**. The page maps the backup keys to the API request format.
4. The page sends the normalized payload to `POST /migration/localstorage` using the signed-in teacher token. The import is additive and repeatable: stable legacy IDs prevent duplicate student, reading, attendance and marks rows on a retry. It never deletes existing records.
5. Check the returned import counts and compare student totals and sample reading history before switching the live site.

The endpoint is deliberately teacher-only. Parent accounts cannot import or modify data. Photos are stored as data URLs and can increase database size substantially; review the backup size before importing. The route currently supports up to 5,000 students, 20,000 marks and 50,000 reading entries per request. For very large backups, split the payload into smaller batches only after preserving the original backup.

The schema update uses additive PostgreSQL `ADD COLUMN IF NOT EXISTS` statements and creates partial unique indexes for legacy IDs; it does not drop tables or records. The existing localStorage data is not changed by importing.

## Frontend authentication foundation
The static frontend now has `login.html`, `auth.js`, `config.js`, and a read-only `parent.html` view. Before frontend sign-in can reach the API, set `window.QURAN_JOURNEY_CONFIG.API_BASE_URL` in the root `config.js` to the public Render service URL (for example, `https://your-api.onrender.com`, with no trailing slash). Do not put the Neon connection string or JWT signing secret in this file.

The teacher pages are protected by role checks. Existing student and daily-mark features still use browser localStorage; they have not yet been migrated or synchronized with PostgreSQL. Do not assume old browser records have been imported. Parent record views read from the API and will show only records stored there for students linked to that parent.
