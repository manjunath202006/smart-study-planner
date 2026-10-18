
import os
import re
import sqlite3
from functools import wraps
from datetime import date, datetime, timedelta

from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-only-secret-key-change-before-deployment"
)

DATABASE = os.path.join(app.root_path, "students.db")


# Database connection
def get_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Create the students table automatically
def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        db.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES students(id),
                UNIQUE(student_id, name)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id INTEGER NOT NULL,
                chapter TEXT NOT NULL,
                topic_name TEXT NOT NULL,
                difficulty TEXT NOT NULL
                    CHECK(difficulty IN ('Easy', 'Medium', 'Hard')),
                status TEXT NOT NULL DEFAULT 'Not Started'
                    CHECK(status IN ('Not Started', 'In Progress', 'Completed')),
                FOREIGN KEY (subject_id) REFERENCES subjects(id)
                    ON DELETE CASCADE
            )
        """)



# Protect pages that require login
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "student_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


# Opening http://127.0.0.1:5000/ sends the student to the login page
@app.route("/")
def home():
    return redirect(url_for("login"))

# Stage 2: Student registration
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not 2 <= len(name) <= 80:
            flash("Name must contain 2 to 80 characters.", "error")
            return render_template("register.html")

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Enter a valid email address.", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)

        try:
            with get_db() as db:
                db.execute(
                    """
                    INSERT INTO students (name, email, password_hash)
                    VALUES (?, ?, ?)
                    """,
                    (name, email, password_hash)
                )
        except sqlite3.IntegrityError:
            flash("This email is already registered.", "error")
            return render_template("register.html")

        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# Stage 2: Student login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        with get_db() as db:
            student = db.execute(
                "SELECT * FROM students WHERE email = ?",
                (email,)
            ).fetchone()

        if student and check_password_hash(
            student["password_hash"], password
        ):
            session.clear()
            session["student_id"] = student["id"]
            session["student_name"] = student["name"]
            # After login, show the StudySmart landing page first.
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# Stage 2: Student dashboard
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        student_name=session.get("student_name", "Student")
    )
        
# StudySmart home page
@app.route("/study-home")
@login_required
def study_home():
    return render_template(
        "study_home.html",
        student_name=session["student_name"]
    )


# Stage 2: Logout
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have logged out.", "success")
    return redirect(url_for("login"))

# Initialize the database
with app.app_context():
    init_db()
    
# Stage 4: Automatic timetable generation
@app.route("/timetable", methods=["GET", "POST"])
@login_required
def timetable():
    student_id = session["student_id"]

    settings = {
        "exam_date": "2027-03-10",
        "start_time": "17:00",
        "end_time": "22:00",
        "break_minutes": 10
    }

    schedule = []
    days_remaining = None
    error = None

    if request.method == "POST":
        settings["exam_date"] = request.form.get("exam_date", "")
        settings["start_time"] = request.form.get("start_time", "")
        settings["end_time"] = request.form.get("end_time", "")
        break_value = request.form.get("break_minutes", "10")

        try:
            exam_day = date.fromisoformat(settings["exam_date"])
            start = datetime.strptime(
                settings["start_time"], "%H:%M"
            )
            end = datetime.strptime(
                settings["end_time"], "%H:%M"
            )

            if exam_day < date.today():
                raise ValueError("Exam date cannot be in the past.")

            if end <= start:
                raise ValueError(
                    "End time must be later than start time."
                )

            if break_value not in ("5", "10", "15"):
                raise ValueError("Choose a valid break duration.")

            settings["break_minutes"] = int(break_value)

        except ValueError as exc:
            error = str(exc) or "Please enter valid timetable settings."

    if request.method == "GET" or error is None:
        if request.method == "GET":
            exam_day = date.fromisoformat(settings["exam_date"])
            start = datetime.strptime(settings["start_time"], "%H:%M")
            end = datetime.strptime(settings["end_time"], "%H:%M")

        if error is None:
            days_remaining = (exam_day - date.today()).days

            with get_db() as db:
                subjects_list = db.execute(
                    """
                    SELECT id, name
                    FROM subjects
                    WHERE student_id = ?
                    ORDER BY name
                    """,
                    (student_id,)
                ).fetchall()

                topics_list = db.execute(
                    """
                    SELECT
                        topics.id,
                        topics.chapter,
                        topics.topic_name,
                        topics.difficulty,
                        topics.status,
                        subjects.name AS subject_name
                    FROM topics
                    JOIN subjects
                        ON topics.subject_id = subjects.id
                    WHERE subjects.student_id = ?
                    ORDER BY
                        CASE topics.difficulty
                            WHEN 'Hard' THEN 1
                            WHEN 'Medium' THEN 2
                            ELSE 3
                        END,
                        topics.chapter,
                        topics.topic_name
                    """,
                    (student_id,)
                ).fetchall()

            if not subjects_list:
                error = "Add at least one subject before generating a timetable."
            elif not topics_list:
                error = "Add at least one topic before generating a timetable."
            else:
                # Prioritize unfinished topics. If everything is
                # completed, use the saved topics for revision.
                unfinished = [
                    topic for topic in topics_list
                    if topic["status"] != "Completed"
                ]
                study_topics = unfinished or list(topics_list)

                # Create six 40-minute study sessions per day,
                # with a break between sessions.
                activities = []

                for i in range(4):
                    activities.append({
                        "kind": "Study",
                        "title": "Topic study",
                        "topic": True
                    })

                if unfinished:
                    revision_pool = unfinished
                else:
                    revision_pool = list(topics_list)

                activities.append({
                    "kind": "Revision",
                    "title": "Revise a previous topic",
                    "topic": False
                })
                activities.append({
                    "kind": "Practice Test",
                    "title": "Practice questions and test",
                    "topic": False
                })

                current_day = date.today()
                last_day = min(
                    exam_day,
                    current_day + timedelta(days=6)
                )

                day_number = 0

                while current_day <= last_day:
                    day_start = start.replace(
                        year=2000, month=1, day=1
                    )
                    day_end = end.replace(
                        year=2000, month=1, day=1
                    )
                    cursor = day_start
                    sessions = []

                    # Rotate topics across the days so that
                    # students study different topics each day.
                    for slot, activity in enumerate(activities):
                        session_end = cursor + timedelta(minutes=40)

                        if session_end > day_end:
                            break

                        if activity["topic"]:
                            topic_index = (
                                day_number * 4 + slot
                            ) % len(study_topics)

                            topic = study_topics[topic_index]
                            title = (
                                f"{topic['subject_name']} — "
                                f"{topic['chapter']}: "
                                f"{topic['topic_name']}"
                            )
                            detail = (
                                f"Difficulty: {topic['difficulty']}"
                            )
                        elif activity["kind"] == "Revision":
                            topic_index = day_number % len(revision_pool)
                            topic = revision_pool[topic_index]
                            title = (
                                f"Revise {topic['subject_name']} — "
                                f"{topic['topic_name']}"
                            )
                            detail = "Review notes and key concepts"
                        else:
                            title = "Practice Test"
                            detail = (
                                "Answer questions and review mistakes"
                            )

                        sessions.append({
                            "start": cursor.strftime("%I:%M %p"),
                            "end": session_end.strftime("%I:%M %p"),
                            "kind": activity["kind"],
                            "title": title,
                            "detail": detail
                        })

                        cursor = session_end

                        # Add a break only when another full
                        # study session can fit afterwards.
                        break_end = cursor + timedelta(
                            minutes=settings["break_minutes"]
                        )
                        next_end = break_end + timedelta(minutes=40)

                        if next_end <= day_end:
                            sessions.append({
                                "start": cursor.strftime("%I:%M %p"),
                                "end": break_end.strftime("%I:%M %p"),
                                "kind": "Break",
                                "title": "Take a break",
                                "detail": "Rest, hydrate and relax"
                            })
                            cursor = break_end

                    schedule.append({
                        "date": current_day.strftime("%A, %d %B %Y"),
                        "sessions": sessions
                    })

                    current_day += timedelta(days=1)
                    day_number += 1

    return render_template(
        "timetable.html",
        settings=settings,
        schedule=schedule,
        days_remaining=days_remaining,
        error=error
    )

    
# Stage 3: View and add subjects
@app.route("/subjects", methods=["GET", "POST"])
@login_required
def subjects():
    student_id = session["student_id"]

    if request.method == "POST":
        name = request.form.get("name", "").strip()

        if not name or len(name) > 100:
            flash("Subject name must contain 1–100 characters.", "error")
        else:
            try:
                with get_db() as db:
                    db.execute(
                        "INSERT INTO subjects (student_id, name) VALUES (?, ?)",
                        (student_id, name)
                    )
                flash("Subject added successfully!", "success")
            except sqlite3.IntegrityError:
                flash("This subject already exists.", "error")

        return redirect(url_for("subjects"))

    with get_db() as db:
        subject_list = db.execute(
            """
            SELECT * FROM subjects
            WHERE student_id = ?
            ORDER BY name
            """,
            (student_id,)
        ).fetchall()

        topic_list = db.execute(
            """
            SELECT topics.*, subjects.name AS subject_name
            FROM topics
            JOIN subjects ON topics.subject_id = subjects.id
            WHERE subjects.student_id = ?
            ORDER BY subjects.name, topics.chapter, topics.topic_name
            """,
            (student_id,)
        ).fetchall()

    return render_template(
        "subjects.html",
        subjects=subject_list,
        topics=topic_list
    )


# Stage 3: Add a chapter/topic to a subject
@app.route("/subjects/<int:subject_id>/topics", methods=["POST"])
@login_required
def add_topic(subject_id):
    student_id = session["student_id"]

    chapter = request.form.get("chapter", "").strip()
    topic_name = request.form.get("topic_name", "").strip()
    difficulty = request.form.get("difficulty", "")

    if not chapter or not topic_name:
        flash("Enter both chapter and topic names.", "error")
        return redirect(url_for("subjects"))

    if len(chapter) > 150 or len(topic_name) > 150:
        flash("Chapter and topic names must be 150 characters or fewer.", "error")
        return redirect(url_for("subjects"))

    if difficulty not in ("Easy", "Medium", "Hard"):
        flash("Select a valid difficulty.", "error")
        return redirect(url_for("subjects"))

    with get_db() as db:
        subject = db.execute(
            "SELECT id FROM subjects WHERE id = ? AND student_id = ?",
            (subject_id, student_id)
        ).fetchone()

        if subject is None:
            flash("Subject not found.", "error")
            return redirect(url_for("subjects"))

        db.execute(
            """
            INSERT INTO topics
                (subject_id, chapter, topic_name, difficulty)
            VALUES (?, ?, ?, ?)
            """,
            (subject_id, chapter, topic_name, difficulty)
        )

    flash("Topic added successfully!", "success")
    return redirect(url_for("subjects"))


# Stage 3: Update topic completion status
@app.route("/topics/<int:topic_id>/status", methods=["POST"])
@login_required
def update_topic_status(topic_id):
    student_id = session["student_id"]
    status = request.form.get("status", "")

    allowed_statuses = ("Not Started", "In Progress", "Completed")

    if status not in allowed_statuses:
        flash("Invalid completion status.", "error")
        return redirect(url_for("subjects"))

    with get_db() as db:
        result = db.execute(
            """
            UPDATE topics
            SET status = ?
            WHERE id = ?
              AND subject_id IN (
                  SELECT id FROM subjects WHERE student_id = ?
              )
            """,
            (status, topic_id, student_id)
        )

        if result.rowcount == 0:
            flash("Topic not found.", "error")
        else:
            flash("Topic status updated!", "success")

    return redirect(url_for("subjects"))



if __name__ == "__main__":
    app.run(debug=True)
