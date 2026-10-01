"""Exercise the main student flow against a disposable PostgreSQL database."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db import connection
from django.test import Client


def main():
    client = Client()
    assert client.get("/health/").status_code == 200
    assert client.get("/").status_code == 200
    with connection.cursor() as cursor:
        cursor.execute("""SELECT s.section_id FROM course_sections s
                          JOIN courses c ON c.course_id = s.course_id
                          WHERE c.course_code = 'CS101' AND s.section_code = 'A'""")
        section_id = cursor.fetchone()[0]

    response = client.post("/signup/", {
        "username": "web_smoke_student",
        "full_name": "Web Smoke Student",
        "email": "web_smoke_student@example.test",
        "password1": "CorrectHorseBatteryStaple42!",
        "password2": "CorrectHorseBatteryStaple42!",
    })
    assert response.status_code == 302, response.content.decode()[:500]
    assert client.get("/my-courses/").status_code == 200
    assert client.post(f"/sections/{section_id}/register/").status_code == 302
    assert b"CS101" in client.get("/my-courses/").content
    assert client.post(f"/sections/{section_id}/register/").status_code == 302
    assert client.post(f"/sections/{section_id}/drop/").status_code == 302
    assert b"CS101" not in client.get("/my-courses/").content
    print("PASS: health, catalog, signup, registration, duplicate, and drop")


if __name__ == "__main__":
    main()
