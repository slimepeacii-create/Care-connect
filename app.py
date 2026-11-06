import os
from datetime import date

import psycopg2
from psycopg2 import Error
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from flask import Flask, request, redirect, url_for, session, render_template_string
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

# --------------------------------------------------
# APPLICATION CONFIGURATION
# --------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not app.secret_key:
    raise RuntimeError("SECRET_KEY is missing. Add it to your local .env file.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing. Add your Neon PostgreSQL connection string to your .env file.")


def connect_database():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


def setup_database():
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                full_name VARCHAR(150) NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) NOT NULL,
                account_status VARCHAR(20) NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                receiver_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message_text TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id SERIAL PRIMARY KEY,
                patient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                nurse_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                appointment_date DATE NOT NULL,
                appointment_time TIME NOT NULL,
                reason TEXT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                message TEXT NOT NULL,
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS messages_pair_idx ON messages(sender_id, receiver_id, sent_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS appointments_nurse_idx ON appointments(nurse_id, appointment_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS appointments_patient_idx ON appointments(patient_id, appointment_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications(user_id, created_at DESC)")

        # Nurse accounts do not require administrator verification.
        cursor.execute("UPDATE users SET account_status='active' WHERE role='Nurse' AND account_status IN ('pending','rejected')")

        connection.commit()
        print("CareConnect database is ready.")
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def add_notification(cursor, user_id, message):
    cursor.execute(
        "INSERT INTO notifications (user_id, message) VALUES (%s, %s)",
        (user_id, message)
    )


def get_logged_in_user():
    if "user_id" not in session:
        return None
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT id, full_name, email, role FROM users WHERE id=%s",
            (session["user_id"],)
        )
        return cursor.fetchone()
    finally:
        cursor.close()
        connection.close()


# --------------------------------------------------
# WEBSITE DESIGN AND ALL PAGE TEMPLATES
# --------------------------------------------------
PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CareConnect | Healthcare Portal</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;font-family:Arial,sans-serif}
body{background:#f2f6fa;color:#203447}
a{color:#168b80}
.auth-page{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;background:linear-gradient(135deg,#12334a,#187f83)}
.auth-box{background:white;width:100%;max-width:440px;padding:35px;border-radius:14px;box-shadow:0 10px 35px #0002}
.logo{font-size:27px;font-weight:bold;color:#12334a;margin-bottom:25px}.logo span{color:#15978c}
.auth-box h2{margin-bottom:10px}.subtitle{color:#718096;font-size:14px;line-height:1.6;margin-bottom:25px}
label{display:block;font-size:13px;font-weight:bold;margin:12px 0 8px}
input,select{width:100%;padding:13px;margin-bottom:12px;border:1px solid #d9e1e8;border-radius:7px;font-size:14px}
input:focus,select:focus,textarea:focus{outline:1px solid #15978c}
button,.small-button{display:inline-block;padding:12px 16px;background:#168b80;color:white;border:0;border-radius:7px;cursor:pointer;text-decoration:none;font-size:14px}
button:hover,.small-button:hover{background:#116d65}.auth-box button{width:100%;margin-top:10px}
.message,.form-error{color:#c0392b;font-size:13px;margin:12px 0;line-height:1.5}.switch{text-align:center;margin-top:22px;font-size:14px;color:#718096}
.dashboard{display:flex;min-height:100vh}.sidebar{width:245px;flex-shrink:0;background:#12334a;color:white;padding:25px 18px}
.sidebar .logo{color:white;margin-bottom:35px}.sidebar a{display:block;padding:13px 12px;color:#dce8ef;text-decoration:none;margin-bottom:7px;border-radius:7px;font-size:14px}.sidebar a:hover{background:#24516a}
.main{flex:1;min-width:0;padding:30px}.topbar{display:flex;justify-content:space-between;align-items:center;gap:15px;margin-bottom:30px}
.profile{display:flex;align-items:center;gap:12px}.avatar{width:42px;height:42px;border-radius:50%;background:#d8f1eb;color:#168b80;display:grid;place-items:center;font-weight:bold}
.welcome{margin-bottom:25px}.welcome p,.muted{color:#718096;margin-top:9px;line-height:1.6;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-bottom:22px}.card,.section,.appointment-card,.nurse-card,.conversation-card{background:white;padding:22px;border-radius:11px;border:1px solid #e8edf2;margin-bottom:17px}
.card p{color:#718096;margin:10px 0;font-size:13px}.card h2{font-size:23px}.section h2,.section h3{margin-bottom:13px}.section p{color:#718096;line-height:1.7;font-size:14px;margin-bottom:12px}
.status,.appointment-status{display:inline-block;padding:7px 12px;border-radius:20px;background:#e3f7ef;color:#16845d;font-size:12px;margin-top:10px}
.appointment-status{background:#fff2d8;color:#95620a}.accepted{background:#e3f7ef;color:#16845d}.declined,.cancelled{background:#fde8e8;color:#b83232}
.logout{width:100%;margin-top:25px;background:#b83c3c}.logout:hover,.button-decline{background:#922c2c}
.directory-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:17px;margin-top:20px}.nurse-card h3{margin:12px 0 7px}.nurse-card p,.conversation-card p{color:#718096;font-size:13px;margin:7px 0 14px}
.chat-wrap{max-width:900px}.chat-panel{background:white;border-radius:12px;overflow:hidden}.chat-heading{padding:18px 22px;border-bottom:1px solid #e7edf1}.chat-history{padding:22px;min-height:260px;max-height:440px;overflow-y:auto;background:#f8fafc}
.chat-message{max-width:75%;padding:12px 15px;border-radius:12px;margin:0 0 14px;line-height:1.5;overflow-wrap:anywhere}.mine{background:#dff5ef;margin-left:auto}.theirs{background:white;border:1px solid #e5ebef}.chat-time{display:block;color:#718096;font-size:10px;margin-top:5px}
.chat-form{display:flex;gap:10px;padding:16px;border-top:1px solid #e7edf1}.chat-form textarea,.appointment-form textarea{width:100%;min-height:90px;padding:12px;border:1px solid #d9e1e8;border-radius:7px;resize:vertical}.chat-form textarea{flex:1;min-height:48px}.chat-form button{width:130px;align-self:flex-end}
.empty-state{padding:28px;text-align:center;color:#718096;background:#fff;border-radius:10px}.appointment-list{display:grid;gap:14px;margin-top:18px}.appointment-meta{color:#718096;font-size:13px;line-height:1.8;margin:10px 0}
.appointment-actions{display:flex;gap:10px;margin-top:13px}.appointment-actions form{flex:1}.appointment-actions button{width:100%}.appointment-form{max-width:700px}.appointment-form input,.appointment-form textarea{margin-bottom:17px}
@media(max-width:700px){.dashboard{display:block}.sidebar{width:100%}.sidebar a{display:inline-block;font-size:12px;padding:10px}.main{padding:18px}.cards{grid-template-columns:1fr}.topbar{align-items:flex-start;flex-direction:column}.chat-form,.appointment-actions{flex-direction:column}.chat-form button{width:100%}.chat-message{max-width:90%}}
</style>
</head>
<body>
{% if mode in ['login','register'] %}
<div class="auth-page"><div class="auth-box"><div class="logo">Care<span>Connect.</span></div>
{% if mode == 'login' %}
<h2>Welcome Back</h2><p class="subtitle">Sign in to access your healthcare account.</p>
{% else %}
<h2>Create Your Account</h2><p class="subtitle">Join CareConnect and connect with healthcare professionals.</p>
{% endif %}
{% if message %}<p class="message">{{ message }}</p>{% endif %}
{% if mode == 'login' %}
<form method="POST" action="/login"><label>Email Address</label><input type="email" name="email" placeholder="Enter your email" required><label>Password</label><input type="password" name="password" placeholder="Enter your password" required><button type="submit">Sign In</button></form>
<div class="switch">Do not have an account? <a href="/register">Create Account</a></div>
{% else %}
<form method="POST" action="/register"><label>Full Name</label><input name="full_name" maxlength="150" placeholder="Enter your full name" required><label>Email Address</label><input type="email" name="email" maxlength="150" placeholder="Enter your email" required><label>Account Type</label><select name="role" required><option value="">Select account type</option><option value="Patient">Patient</option><option value="Nurse">Nurse</option></select><label>Password</label><input type="password" name="password" minlength="8" placeholder="At least 8 characters" required><label>Confirm Password</label><input type="password" name="confirm_password" minlength="8" placeholder="Confirm your password" required><button type="submit">Create Account</button></form>
<div class="switch">Already registered? <a href="/">Sign In</a></div>
{% endif %}</div></div>
{% else %}
<div class="dashboard">
<aside class="sidebar"><div class="logo">Care<span>Connect.</span></div><a href="/dashboard">Dashboard</a>
{% if user.role == 'Patient' %}<a href="/nurses">Find a Nurse</a>{% endif %}
<a href="/messages">Messages</a><a href="/appointments">Appointments</a><a href="/notifications">Notifications</a>
<form method="POST" action="/logout"><button class="logout" type="submit">Sign Out</button></form></aside>
<main class="main"><header class="topbar"><div><h3>Healthcare Portal</h3><p class="muted">CareConnect</p></div><div class="profile"><div class="avatar">{{ user.full_name[0].upper() }}</div><div><strong>{{ user.full_name }}</strong><p class="muted">{{ user.role }}</p></div></div></header>
{% if mode == 'dashboard' %}
<section class="welcome"><h1>Welcome, {{ user.full_name }}!</h1><p>Your healthcare journey starts here. Manage your account and stay connected.</p><span class="status">Account Active</span></section>
<section class="cards"><div class="card"><div>📅</div><p>Appointments</p><h2>{{ appointment_count }}</h2></div><div class="card"><div>✉</div><p>Messages</p><h2>{{ message_count }}</h2></div><div class="card"><div>✚</div><p>Account Type</p><h2>{{ user.role }}</h2></div></section>
<section class="section"><h3>{% if user.role == 'Patient' %}Patient Services{% else %}Nursing Services{% endif %}</h3><p>{% if user.role == 'Patient' %}Find nurses, request appointments and communicate with healthcare professionals.{% else %}Manage patient conversations and appointment requests.{% endif %}</p>{% if user.role == 'Patient' %}<a class="small-button" href="/nurses">Find a Nurse</a>{% else %}<a class="small-button" href="/appointments">View Appointment Requests</a>{% endif %}</section>
<section class="section"><h3>My Profile</h3><p>Name: {{ user.full_name }}</p><p>Email: {{ user.email }}</p><p>Account Type: {{ user.role }}</p></section>
{% elif mode == 'nurse_directory' %}
<section class="section"><h2>Find a Nurse</h2><p>Choose a registered nurse to contact or request an appointment with.</p>{% if nurses %}<div class="directory-grid">{% for nurse in nurses %}<div class="nurse-card"><div class="avatar">{{ nurse.full_name[0].upper() }}</div><h3>{{ nurse.full_name }}</h3><p>Registered nurse</p><a class="small-button" href="{{ url_for('chat', other_user_id=nurse.id) }}">Start Conversation</a> <a class="small-button" href="{{ url_for('book_appointment', nurse_id=nurse.id) }}">Request Appointment</a></div>{% endfor %}</div>{% else %}<div class="empty-state">No nurses have registered yet. Please check again later.</div>{% endif %}</section>
{% elif mode == 'messages' %}
<section class="section"><h2>Your Conversations</h2>{% if conversations %}{% for person in conversations %}<div class="conversation-card"><strong>{{ person.full_name }}</strong><p>{{ person.role }}</p><a class="small-button" href="{{ url_for('chat', other_user_id=person.id) }}">Open Conversation</a></div>{% endfor %}{% else %}<div class="empty-state">You do not have any conversations yet.</div>{% endif %}{% if user.role == 'Patient' %}<a class="small-button" href="/nurses">Find a Nurse</a>{% endif %}</section>
{% elif mode == 'chat' %}
<section class="section chat-wrap"><h2>Conversation with {{ other_user.full_name }}</h2><div class="chat-panel"><div class="chat-history">{% for item in chat_messages %}<div class="chat-message {% if item.sender_id == user.id %}mine{% else %}theirs{% endif %}">{{ item.message_text }}<span class="chat-time">{{ item.sent_at }}</span></div>{% else %}<div class="empty-state">This is the beginning of your conversation. Send a message to get started.</div>{% endfor %}</div><form class="chat-form" method="POST" action="{{ url_for('chat', other_user_id=other_user.id) }}"><textarea name="message_text" maxlength="3000" placeholder="Write your message..." required></textarea><button type="submit">Send Message</button></form></div></section>
{% elif mode == 'appointment_list' %}
<section class="section">{% if user.role == 'Patient' %}<h2>My Appointment Requests</h2><p>Check whether each nurse has accepted or declined your request.</p><a class="small-button" href="/nurses">Request Another Appointment</a>{% else %}<h2>Patient Appointment Requests</h2><p>Review requests and accept or decline pending appointments.</p>{% endif %}
{% if appointments %}<div class="appointment-list">{% for appointment in appointments %}<div class="appointment-card">{% if user.role == 'Patient' %}<h3>Nurse: {{ appointment.nurse_name }}</h3>{% else %}<h3>Patient: {{ appointment.patient_name }}</h3>{% endif %}<div class="appointment-meta"><strong>Date:</strong> {{ appointment.appointment_date }}<br><strong>Time:</strong> {{ appointment.appointment_time }}<br><strong>Reason:</strong> {{ appointment.reason }}</div><span class="appointment-status {% if appointment.status == 'Accepted' %}accepted{% elif appointment.status == 'Declined' %}declined{% elif appointment.status == 'Cancelled' %}cancelled{% endif %}">{{ appointment.status }}</span>
{% if user.role == 'Patient' and appointment.status in ['Pending','Accepted'] %}<div class="appointment-actions"><form method="POST" action="{{ url_for('cancel_appointment', appointment_id=appointment.id) }}" onsubmit="return confirm('Are you sure you want to cancel this appointment?');"><button class="button-decline" type="submit">Cancel Appointment</button></form></div>{% endif %}
{% if user.role == 'Nurse' and appointment.status == 'Pending' %}<div class="appointment-actions"><form method="POST" action="{{ url_for('update_appointment', appointment_id=appointment.id, action='accept') }}"><button type="submit">Accept</button></form><form method="POST" action="{{ url_for('update_appointment', appointment_id=appointment.id, action='decline') }}"><button class="button-decline" type="submit">Decline</button></form></div>{% endif %}</div>{% endfor %}</div>{% else %}<div class="empty-state">{% if user.role == 'Patient' %}You have not requested any appointments yet.{% else %}You do not have any appointment requests yet.{% endif %}</div>{% endif %}</section>
{% elif mode == 'notifications' %}
<section class="section"><h2>Your Notifications</h2>{% if notifications %}<div class="appointment-list">{% for notification in notifications %}<div class="appointment-card" {% if not notification.is_read %}style="border-left:4px solid #168b80"{% endif %}><p>{{ notification.message }}</p><div class="appointment-meta">{{ notification.created_at }}</div>{% if not notification.is_read %}<form method="POST" action="{{ url_for('mark_notification_read', notification_id=notification.id) }}"><button type="submit">Mark as Read</button></form>{% else %}<span class="appointment-status accepted">Read</span>{% endif %}</div>{% endfor %}</div>{% else %}<div class="empty-state">You do not have any notifications yet.</div>{% endif %}</section>
{% elif mode == 'book_appointment' %}
<section class="section appointment-form"><h2>Appointment with {{ nurse.full_name }}</h2><p>Your request will be sent to this nurse for review.</p>{% if message %}<p class="form-error">{{ message }}</p>{% endif %}<form method="POST" action="{{ url_for('book_appointment', nurse_id=nurse.id) }}"><label>Preferred Date</label><input type="date" name="appointment_date" min="{{ today }}" required><label>Preferred Time</label><input type="time" name="appointment_time" required><label>Reason for Appointment</label><textarea name="reason" maxlength="1500" placeholder="Briefly explain why you are requesting this appointment..." required></textarea><button type="submit">Send Appointment Request</button></form></section>
{% endif %}
</main></div>
{% endif %}
</body></html>
"""


# --------------------------------------------------
# LOGIN AND REGISTRATION
# --------------------------------------------------
@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template_string(PAGE, mode="login", message=request.args.get("message", ""))


@app.route("/register", methods=["GET", "POST"])
def register():
    message = ""
    if request.method == "POST":
        name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not email:
            message = "Please complete all required fields."
        elif role not in ["Patient", "Nurse"]:
            message = "Please select a valid account type."
        elif len(password) < 8:
            message = "Password must contain at least 8 characters."
        elif password != confirm:
            message = "Your passwords do not match."
        else:
            connection = connect_database()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO users (full_name,email,password_hash,role,account_status) VALUES (%s,%s,%s,%s,'active')",
                    (name, email, generate_password_hash(password), role)
                )
                connection.commit()
                return redirect(url_for("home", message="Registration successful! You can now sign in."))
            except Error as error:
                connection.rollback()
                if getattr(error, "pgcode", None) == "23505":
                    message = "This email already has an account."
                else:
                    print("Registration database error:", error)
                    message = "Registration failed. Please try again."
            finally:
                cursor.close()
                connection.close()
    return render_template_string(PAGE, mode="register", message=message)


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cursor.fetchone()
    finally:
        cursor.close()
        connection.close()
    if user and user["account_status"] == "active" and check_password_hash(user["password_hash"], password):
        session.clear()
        session["user_id"] = user["id"]
        return redirect(url_for("dashboard"))
    return redirect(url_for("home", message="Incorrect email or password."))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
@app.route("/dashboard")
def dashboard():
    user = get_logged_in_user()
    if not user:
        session.clear()
        return redirect(url_for("home"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) AS total FROM appointments WHERE patient_id=%s OR nurse_id=%s", (user["id"], user["id"]))
        appointment_count = cursor.fetchone()["total"]
        cursor.execute("SELECT COUNT(*) AS total FROM messages WHERE sender_id=%s OR receiver_id=%s", (user["id"], user["id"]))
        message_count = cursor.fetchone()["total"]
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="dashboard", user=user, appointment_count=appointment_count, message_count=message_count)


# --------------------------------------------------
# NURSE DIRECTORY AND MESSAGING
# --------------------------------------------------
@app.route("/nurses")
def nurse_directory():
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    if user["role"] != "Patient":
        return redirect(url_for("messages"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id,full_name FROM users WHERE role='Nurse' AND account_status='active' ORDER BY full_name")
        nurses = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="nurse_directory", user=user, nurses=nurses)


@app.route("/messages")
def messages():
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            SELECT DISTINCT u.id,u.full_name,u.role FROM users u
            JOIN messages m ON ((m.sender_id=%s AND m.receiver_id=u.id) OR (m.receiver_id=%s AND m.sender_id=u.id))
            ORDER BY u.full_name
        """, (user["id"], user["id"]))
        conversations = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="messages", user=user, conversations=conversations)


@app.route("/chat/<int:other_user_id>", methods=["GET", "POST"])
def chat(other_user_id):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    if other_user_id == user["id"]:
        return redirect(url_for("messages"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id,full_name,role FROM users WHERE id=%s AND account_status='active'", (other_user_id,))
        other_user = cursor.fetchone()
        if not other_user:
            return redirect(url_for("messages"))
        valid_pair = ((user["role"] == "Patient" and other_user["role"] == "Nurse") or
                      (user["role"] == "Nurse" and other_user["role"] == "Patient"))
        if not valid_pair:
            return redirect(url_for("messages"))
        if user["role"] == "Nurse":
            cursor.execute("SELECT id FROM messages WHERE sender_id=%s AND receiver_id=%s LIMIT 1", (other_user_id, user["id"]))
            if not cursor.fetchone():
                return redirect(url_for("messages"))
        if request.method == "POST":
            message_text = request.form.get("message_text", "").strip()
            if message_text:
                cursor.execute("INSERT INTO messages (sender_id,receiver_id,message_text) VALUES (%s,%s,%s)", (user["id"], other_user_id, message_text))
                connection.commit()
            return redirect(url_for("chat", other_user_id=other_user_id))
        cursor.execute("""
            SELECT sender_id,receiver_id,message_text,sent_at FROM messages
            WHERE (sender_id=%s AND receiver_id=%s) OR (sender_id=%s AND receiver_id=%s)
            ORDER BY sent_at ASC,id ASC
        """, (user["id"], other_user_id, other_user_id, user["id"]))
        chat_messages = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="chat", user=user, other_user=other_user, chat_messages=chat_messages)


# --------------------------------------------------
# NOTIFICATIONS
# --------------------------------------------------
@app.route("/notifications")
def notifications_page():
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id,message,is_read,created_at FROM notifications WHERE user_id=%s ORDER BY created_at DESC,id DESC", (user["id"],))
        notifications = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="notifications", user=user, notifications=notifications)


@app.route("/notification/<int:notification_id>/read", methods=["POST"])
def mark_notification_read(notification_id):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("UPDATE notifications SET is_read=TRUE WHERE id=%s AND user_id=%s", (notification_id, user["id"]))
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("notifications_page"))


# --------------------------------------------------
# APPOINTMENTS
# --------------------------------------------------
@app.route("/appointments")
def appointment_list():
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        if user["role"] == "Patient":
            cursor.execute("""
                SELECT a.id,a.appointment_date,a.appointment_time,a.reason,a.status,u.full_name AS nurse_name
                FROM appointments a JOIN users u ON u.id=a.nurse_id
                WHERE a.patient_id=%s ORDER BY a.appointment_date DESC,a.appointment_time DESC,a.id DESC
            """, (user["id"],))
        else:
            cursor.execute("""
                SELECT a.id,a.appointment_date,a.appointment_time,a.reason,a.status,u.full_name AS patient_name
                FROM appointments a JOIN users u ON u.id=a.patient_id
                WHERE a.nurse_id=%s ORDER BY a.appointment_date ASC,a.appointment_time ASC,a.id DESC
            """, (user["id"],))
        appointments = cursor.fetchall()
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="appointment_list", user=user, appointments=appointments)


@app.route("/book/<int:nurse_id>", methods=["GET", "POST"])
def book_appointment(nurse_id):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    if user["role"] != "Patient":
        return redirect(url_for("appointments"))
    connection = connect_database()
    cursor = connection.cursor()
    message = ""
    try:
        cursor.execute("SELECT id,full_name FROM users WHERE id=%s AND role='Nurse' AND account_status='active'", (nurse_id,))
        nurse = cursor.fetchone()
        if not nurse:
            return redirect(url_for("nurse_directory"))
        if request.method == "POST":
            chosen_date_text = request.form.get("appointment_date", "").strip()
            chosen_time = request.form.get("appointment_time", "").strip()
            reason = request.form.get("reason", "").strip()
            try:
                chosen_date = date.fromisoformat(chosen_date_text)
            except ValueError:
                chosen_date = None
            if not chosen_date or chosen_date < date.today():
                message = "Please choose today or a future date."
            elif not chosen_time:
                message = "Please choose an appointment time."
            elif not reason:
                message = "Please explain the reason for your appointment."
            else:
                cursor.execute("""
                    INSERT INTO appointments (patient_id,nurse_id,appointment_date,appointment_time,reason,status)
                    VALUES (%s,%s,%s,%s,%s,'Pending')
                """, (user["id"], nurse_id, chosen_date_text, chosen_time, reason))
                add_notification(cursor, nurse_id, f"New appointment request from {user['full_name']} for {chosen_date_text} at {chosen_time}.")
                add_notification(cursor, user["id"], f"Your appointment request to {nurse['full_name']} has been sent.")
                connection.commit()
                return redirect(url_for("appointment_list"))
    finally:
        cursor.close()
        connection.close()
    return render_template_string(PAGE, mode="book_appointment", user=user, nurse=nurse, today=date.today().isoformat(), message=message)


@app.route("/appointment/<int:appointment_id>/<action>", methods=["POST"])
def update_appointment(appointment_id, action):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    if user["role"] != "Nurse" or action not in ["accept", "decline"]:
        return redirect(url_for("appointment_list"))
    new_status = "Accepted" if action == "accept" else "Declined"
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            UPDATE appointments SET status=%s
            WHERE id=%s AND nurse_id=%s AND status='Pending'
            RETURNING patient_id
        """, (new_status, appointment_id, user["id"]))
        updated = cursor.fetchone()
        if updated:
            add_notification(cursor, updated["patient_id"], f"Your appointment request with {user['full_name']} was {new_status.lower()}.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("appointment_list"))


@app.route("/appointment/<int:appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    user = get_logged_in_user()
    if not user:
        return redirect(url_for("home"))
    if user["role"] != "Patient":
        return redirect(url_for("appointment_list"))
    connection = connect_database()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            UPDATE appointments SET status='Cancelled'
            WHERE id=%s AND patient_id=%s AND status IN ('Pending','Accepted')
            RETURNING nurse_id
        """, (appointment_id, user["id"]))
        cancelled = cursor.fetchone()
        if cancelled:
            add_notification(cursor, cancelled["nurse_id"], f"{user['full_name']} cancelled an appointment request.")
            add_notification(cursor, user["id"], "Your appointment has been cancelled.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()
    return redirect(url_for("appointment_list"))


# --------------------------------------------------
# LOGOUT AND APPLICATION STARTUP
# --------------------------------------------------
@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


# Set up the database during startup, including when Render uses Gunicorn.
setup_database()

if __name__ == "__main__":
    print("CareConnect is running.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
