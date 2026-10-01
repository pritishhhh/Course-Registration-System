from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import SignUpForm
from .models import StudentProfile


def catalog(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT s.section_id, c.course_code, c.title, c.credits,
                   s.section_code, s.instructor, s.capacity, s.seats_filled,
                   s.waitlist_capacity, t.name,
                   t.registration_opens_at, t.registration_closes_at,
                   (SELECT count(*) FROM enrollments e WHERE e.section_id = s.section_id
                    AND e.status = 'WAITLISTED') AS waitlisted
            FROM course_sections s
            JOIN courses c ON c.course_id = s.course_id
            JOIN terms t ON t.term_id = s.term_id
            ORDER BY t.name, c.course_code, s.section_code
        """)
        columns = [column[0] for column in cursor.description]
        sections = [dict(zip(columns, row)) for row in cursor.fetchall()]
    now = timezone.now()
    for section in sections:
        if section["registration_opens_at"] and now < section["registration_opens_at"]:
            section["availability_label"] = "Registration has not opened"
        elif section["registration_closes_at"] and now >= section["registration_closes_at"]:
            section["availability_label"] = "Registration closed"
        elif section["seats_filled"] < section["capacity"]:
            section["availability_label"] = "Seats available"
        elif section["waitlisted"] < section["waitlist_capacity"]:
            section["availability_label"] = "Waitlist available"
        else:
            section["availability_label"] = "Section and waitlist full"
        section["can_register"] = section["availability_label"] in {"Seats available", "Waitlist available"}
    return render(request, "registration/catalog.html", {"sections": sections})


def signup(request):
    if request.user.is_authenticated:
        return redirect("catalog")
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save(commit=False)
                user.email = form.cleaned_data["email"]
                user.first_name = form.cleaned_data["full_name"]
                user.save()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO students (full_name, email) VALUES (%s, %s) RETURNING student_id",
                        [form.cleaned_data["full_name"], user.email],
                    )
                    student_id = cursor.fetchone()[0]
                StudentProfile.objects.create(user=user, student_id=student_id)
        except IntegrityError:
            form.add_error(None, "That username or email is already in use.")
        else:
            login(request, user)
            return redirect("catalog")
    return render(request, "registration/signup.html", {"form": form})


def _student_id(request):
    try:
        return request.user.studentprofile.student_id
    except StudentProfile.DoesNotExist:
        messages.error(request, "This account is not linked to a student record.")
        return None


def _run_seat_action(action, student_id, section_id):
    """Keep lock waits bounded so a registration spike cannot hang a worker."""
    function = {
        "register": "fn_register_safe",
        "drop": "fn_drop_enrollment",
    }[action]
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '3s'")
            cursor.execute("SET LOCAL statement_timeout = '10s'")
            cursor.execute(f"SELECT {function}(%s, %s)", [student_id, section_id])
            return cursor.fetchone()[0]
    except DatabaseError as error:
        code = getattr(error.__cause__, "pgcode", None)
        if code in {"55P03", "40P01", "40001", "57014"}:
            return "BUSY_RETRY"
        raise


@login_required
@require_POST
def register(request, section_id):
    student_id = _student_id(request)
    if student_id is None:
        return redirect("catalog")
    result = _run_seat_action("register", student_id, section_id)
    messages.info(request, {
        "ENROLLED": "You have a seat.",
        "WAITLISTED": "You are on the waitlist.",
        "ALREADY_REGISTERED": "You already have an active registration for this section.",
        "ALREADY_IN_COURSE": "You already have an active section of this course this term.",
        "FULL_NO_WAITLIST": "This section and its waitlist are full.",
        "REGISTRATION_CLOSED": "Registration is closed for this term.",
        "SECTION_NOT_FOUND": "Section not found.",
        "BUSY_RETRY": "Registration is busy. Please try again in a moment.",
    }.get(result, "Registration could not be completed."))
    return redirect("my_courses")


@login_required
@require_POST
def drop(request, section_id):
    student_id = _student_id(request)
    if student_id is None:
        return redirect("catalog")
    result = _run_seat_action("drop", student_id, section_id)
    messages.info(request, {
        "DROPPED": "Registration dropped.",
        "BUSY_RETRY": "Registration is busy. Please try dropping again in a moment.",
    }.get(result, "No active registration was found."))
    return redirect("my_courses")


@login_required
def my_courses(request):
    student_id = _student_id(request)
    if student_id is None:
        return redirect("catalog")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT e.section_id, c.course_code, c.title, s.section_code,
                   t.name, e.status::text, e.waitlist_position
            FROM enrollments e
            JOIN course_sections s ON s.section_id = e.section_id
            JOIN courses c ON c.course_id = s.course_id
            JOIN terms t ON t.term_id = s.term_id
            WHERE e.student_id = %s AND e.status IN ('ENROLLED', 'WAITLISTED')
            ORDER BY t.name, c.course_code, s.section_code
        """, [student_id])
        columns = [column[0] for column in cursor.description]
        enrollments = [dict(zip(columns, row)) for row in cursor.fetchall()]
    return render(request, "registration/my_courses.html", {"enrollments": enrollments})


def health(request):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return HttpResponse("ok", content_type="text/plain")
