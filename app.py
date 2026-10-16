from pathlib import Path
from typing import Annotated

import psycopg
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Path as PathParam, Request
from fastapi.responses import FileResponse, JSONResponse

from server.auth import auth_config, current_user
from server.database import transaction

load_dotenv()
ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Course Registration API", version="1.0.0", docs_url=None, redoc_url=None)
SectionID = Annotated[int, PathParam(gt=0, le=2147483647)]


@app.middleware("http")
async def private_responses(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(psycopg.Error)
async def database_error(request: Request, exc: psycopg.Error):
    # Never expose SQL, credentials, or infrastructure details to a caller.
    if isinstance(exc, psycopg.errors.UniqueViolation):
        return JSONResponse({"detail": "Account could not be linked. Contact the administrator."}, status_code=409)
    return JSONResponse({"detail": "Database is busy or unavailable. Please retry."},
                        status_code=503, headers={"Retry-After": "2"})


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(ROOT / "public" / "index.html")


# Vercel serves public assets from its CDN; explicit local routes support Uvicorn.
@app.get("/app.js", include_in_schema=False)
def javascript():
    return FileResponse(ROOT / "public" / "app.js", media_type="text/javascript")


@app.get("/style.css", include_in_schema=False)
def stylesheet():
    return FileResponse(ROOT / "public" / "style.css", media_type="text/css")


@app.get("/docs", include_in_schema=False)
def docs():
    return FileResponse(ROOT / "public" / "docs.html")


@app.get("/docs-init.js", include_in_schema=False)
def docs_script():
    return FileResponse(ROOT / "public" / "docs-init.js", media_type="text/javascript")


@app.get("/api/health")
def health():
    with transaction() as conn:
        conn.execute("SELECT 1 FROM courses LIMIT 1")
    return {"status": "ok"}


@app.get("/api/config")
def config():
    url, key = auth_config()
    # Publishable/anon key only. No database URL or service-role key is exposed.
    return {"supabase_url": url, "supabase_key": key}


@app.get("/api/sections")
def sections():
    with transaction() as conn:
        return conn.execute("SELECT * FROM section_catalog ORDER BY course_code, term_id, section_code").fetchall()


def student_id(conn, user):
    sid = conn.execute("SELECT fn_ensure_student(%s::uuid, %s) AS id",
                       (user["subject"], user["email"])).fetchone()["id"]
    conn.execute("SELECT set_config('app.student_id', %s, true)", (str(sid),))
    return sid


@app.get("/api/me/enrollments")
def my_enrollments(user=Depends(current_user)):
    with transaction() as conn:
        sid = student_id(conn, user)
        return conn.execute("""SELECT e.enrollment_id, e.section_id, e.status,
            e.waitlist_position, e.requested_at, c.course_code, c.title, s.section_code
            FROM enrollments e JOIN course_sections s USING (section_id)
            JOIN courses c USING (course_id)
            WHERE e.student_id = %s AND e.status IN ('ENROLLED', 'WAITLISTED')
            ORDER BY c.course_code, e.enrollment_id""", (sid,)).fetchall()


def mutate(section_id, user, dropping=False):
    with transaction() as conn:
        sid = student_id(conn, user)
        query = "SELECT fn_drop_enrollment(%s, %s) AS result" if dropping else "SELECT fn_register_safe(%s, %s) AS result"
        result = conn.execute(query, (sid, section_id)).fetchone()["result"]
    # Commit, including deferred checks, before reporting success.
    if result in ("SECTION_NOT_FOUND", "STUDENT_NOT_FOUND"):
        raise HTTPException(404, result)
    if result in ("REGISTRATION_NOT_OPEN", "REGISTRATION_CLOSED", "FULL_NO_WAITLIST"):
        raise HTTPException(409, result)
    return {"result": result}


@app.post("/api/sections/{section_id}/register")
def register(section_id: SectionID, user=Depends(current_user)):
    return mutate(section_id, user)


@app.delete("/api/sections/{section_id}/registration")
def drop(section_id: SectionID, user=Depends(current_user)):
    return mutate(section_id, user, dropping=True)
