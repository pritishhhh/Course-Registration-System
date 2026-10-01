"""Race authenticated website requests against one section in disposable CI."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

django.setup()

from django.contrib.auth.models import User
from django.db import connection, connections
from django.test import Client
from django.utils import timezone

from registration.models import Course, CourseSection, StudentProfile, Term


def request_seat(client, section_id):
    try:
        return client.post(f"/sections/{section_id}/register/").status_code
    finally:
        connections.close_all()


def main():
    now = timezone.now()
    term = Term.objects.create(
        name="HTTP concurrency test",
        registration_opens_at=now - timedelta(minutes=1),
        registration_closes_at=now + timedelta(days=1),
    )
    course = Course.objects.create(course_code="WEBTEST", title="HTTP Race Test", credits=1)
    section = CourseSection.objects.create(
        course=course, term=term, section_code="A", capacity=5, waitlist_capacity=10
    )
    clients = []
    for number in range(80):
        email = f"webburst{number}@example.test"
        user = User.objects.create(username=f"webburst{number}", email=email)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO students (full_name, email) VALUES (%s, %s) RETURNING student_id",
                [f"Web burst student {number}", email],
            )
            student_id = cursor.fetchone()[0]
        StudentProfile.objects.create(user=user, student_id=student_id)
        client = Client()
        client.force_login(user)
        clients.append(client)

    with ThreadPoolExecutor(max_workers=40) as executor:
        statuses = list(executor.map(lambda client: request_seat(client, section.section_id), clients))
    assert statuses == [302] * 80, statuses

    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT status::text, count(*) FROM enrollments
               WHERE section_id = %s GROUP BY status""",
            [section.section_id],
        )
        counts = dict(cursor.fetchall())
        cursor.execute(
            "SELECT seats_filled FROM course_sections WHERE section_id = %s", [section.section_id]
        )
        filled = cursor.fetchone()[0]
        cursor.execute(
            """SELECT waitlist_position FROM enrollments WHERE section_id = %s
               AND status = 'WAITLISTED' ORDER BY waitlist_position""",
            [section.section_id],
        )
        positions = [row[0] for row in cursor.fetchall()]

    assert filled == counts.get("ENROLLED", 0) == 5, (filled, counts)
    assert counts.get("WAITLISTED", 0) == 10, counts
    assert positions == list(range(1, 11)), positions
    print("PASS: 80 authenticated web requests produced 5 seats and 10 ordered waitlist places")


if __name__ == "__main__":
    main()
