from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
import os
from werkzeug.utils import secure_filename
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2 import service_account

app = Flask(__name__)
app.secret_key = 'supersecretkey'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "inventory.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "reports")
SCOPES = ['https://www.googleapis.com/auth/drive.file']
SERVICE_ACCOUNT_FILE = os.path.join(BASE_DIR, 'credentials.json')
GDRIVE_FOLDER_ID = 'YOUR_GOOGLE_DRIVE_FOLDER_ID'  # <-- اینو با آی‌دی پوشه گوگل درایو جایگزین کن

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize Google Drive service
credentials = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)
drive_service = build('drive', 'v3', credentials=credentials)

# DB init
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tool_type TEXT,
        serial_number TEXT,
        size TEXT,
        thread_type TEXT,
        location TEXT,
        status TEXT,
        report_link TEXT,
        description TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )''')
    conn.commit()
    conn.close()

init_db()

# Helper: check role
def allowed_roles(roles):
    return 'user_role' in session and session['user_role'] in roles

# Routes
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_role'] = user['role']
            return redirect("/")
        else:
            return "<script>alert('نام کاربری یا رمز اشتباه است'); window.location.href='/login';</script>"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/", methods=["GET"])
def index():
    if 'user_id' not in session:
        return redirect("/login")
    query = "SELECT * FROM inventory WHERE 1=1"
    params = []
    tool_type = request.args.get("tool_type", "")
    serial_number = request.args.get("serial_number", "")
    status = request.args.get("status", "")
    location = request.args.get("location", "")
    if tool_type:
        query += " AND tool_type LIKE ?"
        params.append(f"%{tool_type}%")
    if serial_number:
        query += " AND serial_number LIKE ?"
        params.append(f"%{serial_number}%")
    if status:
        query += " AND status LIKE ?"
        params.append(f"%{status}%")
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(query, params)
    tools = c.fetchall()
    conn.close()
    return render_template("index.html", tools=tools, role=session['user_role'])

@app.route("/add", methods=["POST"])
def add():
    if not allowed_roles(['Admin', 'Senior Expert Inspection']):
        return "<script>alert('دسترسی ندارید'); window.location.href='/';</script>"
    tool_type = request.form.get("tool_type")
    serial_number = request.form.get("serial_number")
    size = request.form.get("size")
    thread_type = request.form.get("thread_type")
    location = request.form.get("location")
    status = request.form.get("status")
    description = request.form.get("description")
    report_file = request.files.get("report_file")

    report_link = ""
    if report_file and report_file.filename:
        filename = secure_filename(report_file.filename)
        save_path = os.path.join(UPLOAD_FOLDER, filename)
        report_file.save(save_path)
        # Upload to Google Drive
        file_metadata = {'name': filename, 'parents':[GDRIVE_FOLDER_ID]}
        media = MediaFileUpload(save_path, mimetype='application/pdf')
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        report_link = f"https://drive.google.com/file/d/{file.get('id')}/view?usp=sharing"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM inventory WHERE serial_number=?", (serial_number,))
    if c.fetchone():
        conn.close()
        return "<script>alert('شماره سریال تکراری است'); window.location.href='/';</script>"
    c.execute('''INSERT INTO inventory
        (tool_type, serial_number, size, thread_type, location, status, report_link, description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (tool_type, serial_number, size, thread_type, location, status, report_link, description))
    conn.commit()
    conn.close()
    return redirect("/")

@app.route("/upload_report/<int:id>", methods=["POST"])
def upload_report(id):
    if not allowed_roles(['Admin', 'Senior Expert Inspection']):
        return "<script>alert('دسترسی ندارید'); window.location.href='/';</script>"
    report_file = request.files.get("report_file")
    if not report_file or not report_file.filename:
        return "<script>alert('لطفاً یک فایل PDF انتخاب کنید'); window.location.href='/';</script>"
    filename = secure_filename(report_file.filename)
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    report_file.save(save_path)
    # Upload to Google Drive
    file_metadata = {'name': filename, 'parents':[GDRIVE_FOLDER_ID]}
    media = MediaFileUpload(save_path, mimetype='application/pdf')
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    report_link = f"https://drive.google.com/file/d/{file.get('id')}/view?usp=sharing"

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE inventory SET report_link=? WHERE id=?", (report_link, id))
    conn.commit()
    conn.close()
    return redirect("/")

@app.route("/update_description/<int:id>", methods=["POST"])
def update_description(id):
    if 'user_id' not in session:
        return redirect("/login")
    description = request.form.get("description", "")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE inventory SET description=? WHERE id=?", (description, id))
    conn.commit()
    conn.close()
    return "OK"

# Delete routes
@app.route("/delete/<int:id>")
def delete(id):
    if not allowed_roles(['Admin', 'Senior Expert Inspection']):
        return "<script>alert('دسترسی ندارید'); window.location.href='/';</script>"
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect("/")

@app.route("/delete_selected", methods=["POST"])
def delete_selected():
    if not allowed_roles(['Admin', 'Senior Expert Inspection']):
        return "<script>alert('دسترسی ندارید'); window.location.href='/';</script>"
    ids = request.form.getlist('ids')
    if ids:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.executemany("DELETE FROM inventory WHERE id=?", [(i,) for i in ids])
        conn.commit()
        conn.close()
    return '', 204

@app.route("/delete_all_filtered", methods=["POST"])
def delete_all_filtered():
    if not allowed_roles(['Admin', 'Senior Expert Inspection']):
        return "<script>alert('دسترسی ندارید'); window.location.href='/';</script>"
    tool_type = request.form.get("tool_type", "")
    serial_number = request.form.get("serial_number", "")
    status = request.form.get("status", "")
    location = request.form.get("location", "")
    query = "DELETE FROM inventory WHERE 1=1"
    params = []
    if tool_type:
        query += " AND tool_type LIKE ?"
        params.append(f"%{tool_type}%")
    if serial_number:
        query += " AND serial_number LIKE ?"
        params.append(f"%{serial_number}%")
    if status:
        query += " AND status LIKE ?"
        params.append(f"%{status}%")
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()
    return '', 204

# User registration by admin
@app.route("/register", methods=["GET", "POST"])
def register():
    if 'user_role' not in session or session['user_role'] != 'Admin':
        return "<script>alert('فقط ادمین می‌تواند کاربر ایجاد کند'); window.location.href='/';</script>"
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        role = request.form.get("role")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, password, role))
        conn.commit()
        conn.close()
        return redirect("/login")
    return render_template("register.html")

if __name__ == "__main__":
    app.run(debug=True)
