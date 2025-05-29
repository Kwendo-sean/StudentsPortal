from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask import jsonify
import wikipedia
from transformers import pipeline
import re
import random
from dateutil.parser import parse
import math
import os
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect # Import CSRFProtect

db_user = os.getenv("DB_USER", "root")
db_pass = os.getenv("DB_PASSWORD", "")
db_host = os.getenv("DB_HOST", "localhost")
db_name = os.getenv("DB_NAME", "student_portal")

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"mysql+mysqlconnector://{db_user}:{db_pass}@{db_host}/{db_name}"

# Initialize gpt_pipeline to None before try-except
gpt_pipeline = None
try:
    # Attempt to load the pipeline
    gpt_pipeline = pipeline("text2text-generation", model="google/flan-t5-small")
    app.logger.info("Successfully loaded Flan T5 model for AI assistant.")
except Exception as e:
    gpt_pipeline = None # Ensure it's None if loading fails
    # Log the specific error
    app.logger.error(f"Failed to load Flan T5 model for AI assistant: {e}", exc_info=True)
    app.logger.warning("AI assistant features will be limited or unavailable.")

# Configure SECRET_KEY from environment variable with a fallback
app.secret_key = os.environ.get('SECRET_KEY', 'dev_fallback_key_123!@#_do_not_use_in_prod')
if app.secret_key == 'dev_fallback_key_123!@#_do_not_use_in_prod':
    print("WARNING: Using fallback SECRET_KEY. Set a strong SECRET_KEY environment variable for production.")
    app.logger.warning("Using fallback SECRET_KEY. Set a strong SECRET_KEY environment variable for production.")


csrf = CSRFProtect(app) # Initialize CSRFProtect, ensured to be after secret_key
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

COURSES = {
    "Cyber Security": "CYB", "Data Science": "DAT", "PowerBI": "POW",
    "Marketing Analytics": "MAR", "Sales Analytics": "SAL", "Supply Chain Analytics": "SUP",
    "HR Analytics": "HRA", "Finance Analytics": "FIN", "Banking Analytics": "BNK",
    "Coding for Kids": "KID", "Excel": "EXC", "Data Law and Governance": "LAW",
    "Long Program (with modules)": "LNG", "Telkom Analytics": "TEL",
    "Data Journalism": "JRN", "Robotics and Automation": "ROB", "Location Intelligence and GIS": "GIS"
}

# ---Models ----
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    admission_number = db.Column(db.String(20), unique=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)  # Increased length for hash
    phone = db.Column(db.String(20))
    course = db.Column(db.String(100))
    cohort = db.Column(db.String(10))
    fee_expected = db.Column(db.Float, default=0.0)
    fee_paid = db.Column(db.Float, default=0.0)
    next_class = db.Column(db.DateTime)
    graduation_status = db.Column(db.String(100))
    completion_date = db.Column(db.Date)
    attendance_records = db.relationship('Attendance', backref='student', lazy=True)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

    @property
    def fee_balance(self):
        return self.fee_expected - self.fee_paid

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.Enum('Present', 'Absent'), nullable=False)

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)  # Increased length for hash

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    type = db.Column(db.String(50))
    link = db.Column(db.String(200))
    course = db.Column(db.String(100))
    cohort = db.Column(db.String(10))

class GraduationRegistration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_email = db.Column(db.String(100), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.Enum('graduate', 'guest'), nullable=False)
    date_registered = db.Column(db.DateTime, default=datetime.utcnow)

class GraduationInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    graduation_date = db.Column(db.Date)
    media_title = db.Column(db.String(100))
    media_link = db.Column(db.String(200))


with app.app_context():
    db.create_all()
    # Check if default admin exists, if not create one
    if not Admin.query.filter_by(email='admin@example.com').first():
        default_admin = Admin(email='admin@example.com')
        default_admin.set_password('admin') # Set a default password
        db.session.add(default_admin)
        db.session.commit()


def generate_admission_number(course, cohort):
    prefix = COURSES.get(course, "XXX")
    count = User.query.filter_by(course=course, cohort=cohort).count()
    return f"{prefix}{cohort}-{str(count + 1).zfill(3)}"

# ------- Helper Functions(Preddy) -----------
def calculate_attendance_stats(student):
    records = student.attendance_records
    total = len(records)
    present = sum(1 for r in records if r.status == 'Present')
    absent = total - present
    percent = round((present / total) * 100, 1) if total else 0
    return total, present, absent, percent

def format_date(date_str, input_format="%Y-%m-%d", output_format="%A, %d %B %Y"):
    try:
        # Ensure date_str is a string before parsing
        if not isinstance(date_str, str):
            # Log and raise TypeError to be caught by the existing except block,
            # or handle it separately if more specific logging is needed for this case.
            # For now, raising TypeError is consistent with the example.
            raise TypeError(f"Input date_str must be a string, got {type(date_str)} with value {date_str}")
        date_obj = datetime.strptime(date_str, input_format)
        return date_obj.strftime(output_format)
    except (ValueError, TypeError) as e:
        app.logger.warning(
            f"Failed to format date string '{date_str}' with input format '{input_format}'. Error: {e}. Returning original string.",
            exc_info=True
        )
        return date_str

def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"

# ----- Default\Student Routes ---------

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.check_password(request.form['password']): # Use check_password
            session['user'] = user.email
            return redirect(url_for('dashboard'))
        error = "Invalid email or password"
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(email=session['user']).first()
    return render_template('dashboard.html', user=user)

@app.route('/attendance')
def attendance():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(email=session['user']).first()
    records = Attendance.query.filter_by(student_id=user.id).order_by(Attendance.date.desc()).all()

    total = len(records)
    absent = sum(1 for r in records if r.status == 'Absent')
    attendance_percent = round((absent / total) * 100, 1) if total > 0 else 0

    return render_template(
        'attendance.html',
        user=user,
        records=records,
        absent_count=absent,
        total_count=total,
        attendance_percent=attendance_percent
    )

@app.route('/resources')
def student_resources():
    if 'user' not in session:
        return redirect(url_for('login'))
    user = User.query.filter_by(email=session['user']).first()
    resources = Resource.query.filter_by(course=user.course, cohort=user.cohort).all()
    return render_template('resources.html', user=user, resources=resources)

@app.route('/graduation', methods=['GET', 'POST'])
def student_graduation():
    if 'user' not in session:
        return redirect(url_for('login'))

    user = User.query.filter_by(email=session['user']).first()

    if request.method == 'POST':
        role = request.form['role']
        full_name = request.form['name']
        existing = GraduationRegistration.query.filter_by(student_email=user.email).first()
        if not existing:
            reg = GraduationRegistration(student_email=user.email, full_name=full_name, role=role)
            db.session.add(reg)
            if role == 'graduate':
                user.graduation_status = 'Registered'
            db.session.commit()
            flash("Registered successfully.")
        else:
            flash("You've already registered.")

    latest_date = db.session.query(GraduationInfo).filter(GraduationInfo.graduation_date != None) \
                      .order_by(GraduationInfo.graduation_date.desc()).first()

    media_links = GraduationInfo.query.filter(GraduationInfo.media_link != None).all()

    return render_template(
        'graduation.html',
        user=user,
        upcoming_graduation_date=latest_date.graduation_date.strftime('%d %B, %Y') if latest_date else None,
        graduation_media=media_links
    )

# ------- Admin Routes ---------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        admin = Admin.query.filter_by(email=request.form['email']).first()
        if admin and admin.check_password(request.form['password']): # Use check_password
            session['admin'] = admin.email
            return redirect(url_for('admin_dashboard'))
        flash("Invalid credentials")
    return render_template('Admin-Section/admin-login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    students = User.query.count()
    grads = User.query.filter_by(graduation_status='Registered').count()
    attendance = Attendance.query.all()
    present = sum(1 for r in attendance if r.status == 'Present')
    avg_attendance = round((present / len(attendance)) * 100, 1) if attendance else 0
    return render_template('Admin-Section/dashboard.html', total_students=students,
                           graduation_count=grads, avg_attendance=avg_attendance,
                           resource_count=Resource.query.count())

def paginate_items(items, page, per_page):
    total = len(items)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], total_pages

@app.route('/admin/students', methods=['GET', 'POST'])
def manage_students():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        course = request.form['course']
        cohort = request.form['cohort']
        admission_number = generate_admission_number(course, cohort)
        student = User(
            name=request.form['name'],
            email=request.form['email'],
            # password=request.form['password'], # Removed direct password assignment
            phone=request.form['phone'],
            course=course,
            cohort=cohort,
            admission_number=admission_number,
            fee_expected=float(request.form.get('fee_expected', 0)),
            fee_paid=float(request.form.get('fee_paid', 0)),
            graduation_status=request.form['graduation_status']
        )
        student.set_password(request.form['password']) # Use set_password method
        db.session.add(student)
        db.session.commit()
        flash(f"Student {student.name} added successfully.")
        return redirect(url_for('manage_students'))


    page = int(request.args.get('page', 1))
    per_page = 5
    all_students = User.query.order_by(User.name).all()
    students, total_pages = paginate_items(all_students, page, per_page)

    return render_template(
        'Admin-Section/manage-students.html',
        students=students,
        courses=COURSES,
        total_pages=total_pages,
        current_page=page
    )

@app.route('/admin/resources', methods=['GET', 'POST'])
def manage_resources():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    if request.method == 'POST':
        res = Resource(title=request.form['title'], type=request.form['type'],
                       link=request.form['link'], course=request.form['course'],
                       cohort=request.form['cohort'])
        db.session.add(res)
        db.session.commit()
        flash("Resource added successfully.")
        return redirect(url_for('manage_resources'))
    return render_template('Admin-Section/manage-resources.html', resources=Resource.query.all(), courses=COURSES)

@app.route('/admin/resource/delete/<int:id>', methods=['POST'])
def delete_resource(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    res = Resource.query.get_or_404(id)
    db.session.delete(res)
    db.session.commit()
    flash('Resource deleted successfully.')
    return redirect(url_for('manage_resources'))

@app.route('/admin/attendance', methods=['GET', 'POST'])
def admin_attendance():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    course_selected = request.args.get('course')
    cohort_selected = request.args.get('cohort')

    students = []
    if course_selected and cohort_selected:
        students = User.query.filter_by(course=course_selected, cohort=cohort_selected).all()
    elif course_selected:
        students = User.query.filter_by(course=course_selected).all()

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        if not student_id:
            flash("Please select a student.")
            return redirect(url_for('admin_attendance', course=course_selected, cohort=cohort_selected))
        student_id = int(student_id)

        date_str = request.form.get('date')
        if not date_str:
            flash("Date is required.")
            return redirect(url_for('admin_attendance', course=course_selected, cohort=cohort_selected))
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.")
            return redirect(url_for('admin_attendance', course=course_selected, cohort=cohort_selected))
            
        status = request.form['status']
        next_class_str = request.form.get('next_class')

        # Check for existing record
        existing_attendance = Attendance.query.filter_by(student_id=student_id, date=date).first()
        if existing_attendance:
            existing_attendance.status = status # Update if exists
            flash_message = "Attendance record updated."
        else:
            attendance = Attendance(student_id=student_id, date=date, status=status)
            db.session.add(attendance)
            flash_message = "Attendance record added."


        if next_class_str:
            try:
                next_class = datetime.strptime(next_class_str, "%Y-%m-%dT%H:%M")
                student = User.query.get(student_id)
                if student:
                    student.next_class = next_class
            except ValueError:
                flash("Invalid next class date format. Not updated.")
        
        db.session.commit()
        flash(flash_message) # Main flash message
        return redirect(url_for('admin_attendance', course=course_selected, cohort=cohort_selected))


    attendance_records = Attendance.query.order_by(Attendance.date.desc()).limit(20).all()
    all_cohorts = db.session.query(User.cohort).distinct().all()
    
    # Fetch students for dropdown if not already filtered
    # This ensures the student dropdown is always populated for selection.
    all_students_for_dropdown = User.query.order_by(User.name).all()


    return render_template(
        'Admin-Section/attendance-management.html',
        courses=COURSES,
        cohorts=[c[0] for c in all_cohorts if c[0]], # Filter out None or empty cohorts
        students_for_dropdown=all_students_for_dropdown, # For student selection
        filtered_students=students, # For display if filtered
        attendance_records=attendance_records,
        selected_course=course_selected,
        selected_cohort=cohort_selected
    )

@app.route('/admin/student/edit/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    student = User.query.get_or_404(id)
    if request.method == 'POST':
        student.name = request.form['name']
        student.email = request.form['email']
        student.course = request.form['course']
        student.cohort = request.form['cohort']
        student.phone = request.form['phone']
        # student.password = request.form['password'] # Removed direct password assignment
        if request.form.get('password'): # Only update password if provided
            student.set_password(request.form['password']) # Use set_password method
        student.fee_expected = float(request.form.get('fee_expected', 0))
        student.fee_paid = float(request.form.get('fee_paid', 0))
        student.graduation_status = request.form['graduation_status']
        if request.form.get('completion_date'):
            try:
                student.completion_date = datetime.strptime(request.form['completion_date'], "%Y-%m-%d").date()
            except ValueError:
                flash("Invalid completion date format. Not updated.")

        db.session.commit()
        flash(f"Student {student.name} updated successfully.")
        return redirect(url_for('manage_students'))
    return render_template('Admin-Section/edit-student.html', student=student, courses=COURSES)

@app.route('/admin/student/delete/<int:id>', methods=['POST'])
def delete_student(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    student = User.query.get_or_404(id)
    # Also delete related attendance records
    Attendance.query.filter_by(student_id=id).delete()
    db.session.delete(student)
    db.session.commit()
    flash(f"Student {student.name} and their attendance records deleted successfully.")
    return redirect(url_for('manage_students'))

@app.route('/admin/graduation', methods=['GET', 'POST'])
def manage_graduation():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        if 'student_id' in request.form: # Mark student as graduated
            student = User.query.get_or_404(request.form['student_id'])
            student.graduation_status = 'Graduated'
            # Optionally set completion date if not already set
            if not student.completion_date:
                student.completion_date = datetime.utcnow().date()
            db.session.commit()
            flash(f"{student.name} marked as Graduated.")
        
        else: # Add graduation event or media
            date_str = request.form.get('graduation_date')
            title = request.form.get('media_title')
            link = request.form.get('media_link')
            
            new_info_added = False
            if date_str:
                try:
                    grad_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    # Avoid duplicate graduation dates if it's meant to be unique per event
                    if not GraduationInfo.query.filter_by(graduation_date=grad_date).first():
                        db.session.add(GraduationInfo(graduation_date=grad_date))
                        new_info_added = True
                except ValueError:
                    flash("Invalid graduation date format.")
            
            if title and link:
                # Avoid duplicate media links
                if not GraduationInfo.query.filter_by(media_link=link).first():
                    db.session.add(GraduationInfo(media_title=title, media_link=link))
                    new_info_added = True
            
            if new_info_added:
                db.session.commit()
                flash("Graduation details updated.")
            elif not date_str and not (title and link):
                 flash("No new information provided to update.")
            else:
                flash("Information might already exist or was not added.")


    students_eligible = User.query.filter(User.graduation_status != 'Graduated').all()
    grad_info_events = GraduationInfo.query.filter(GraduationInfo.graduation_date != None).order_by(GraduationInfo.graduation_date.desc()).all()
    grad_info_media = GraduationInfo.query.filter(GraduationInfo.media_link != None).order_by(GraduationInfo.id.desc()).all()


    return render_template(
        'Admin-Section/manage-graduation.html',
        students=students_eligible, # Pass only eligible students
        graduation_events=grad_info_events,
        graduation_media=grad_info_media
    )


@app.route('/ai-assistant', methods=['POST'])
def ai_assistant():
    if 'user' not in session:
        return jsonify({'reply': '🔒 Please log in to use the assistant.', 'status': 'error'})

    user = User.query.filter_by(email=session['user']).first()
    data = request.get_json()
    prompt = data.get('message', '').strip().lower()
    attachments = data.get('attachments', [])  

    # Enhanced question patterns with summarization support
    question_patterns = {
        "resources": [
            r"\b(resources?|materials?|files?|documents?|readings?|slides?)\b",
            r"\bwhere (can I find|are|to get).*(resources?|materials?|files?)",
            r"\b(course|class|module).*(materials?|resources?|documents?)",
            r"\bupload|download|access.*(materials?|resources?)"
        ],
        "fee": [
            r"\b(fees?|payments?|balance|tuition|outstanding|amount due)\b",
            r"\bhow much (do I owe|is remaining|to pay)\b",
            r"\b(my|current) (fee|payment) (status|balance|information)\b",
            r"\bcheck (my)? payment(s)?\b"
        ],
        "attendance": [
            r"\battendance\b", r"\babsent\b", r"\bpresent\b", r"\bmissed\s*class\b",
            r"\bwas\s*I\s*in\s*class\b", r"\bshow\s*attendance\b", r"\bhow\s*often\b",
            r"\battendance\s*record\b", r"\bmy\s*attendance\b", r"\bclass\s*attendance\b"
        ],
        "next_class": [
            r"\bnext\s*class\b", r"\bwhen\s*is\s*class\b", r"\bschedule\b", 
            r"\bupcoming\s*class\b", r"\bnext\s*lesson\b", r"\bclass\s*time\b",
            r"\bwhen\s*do\s*we\s*meet\b", r"\bnext\s*session\b", r"\bwhen's\s*the\s*next\s*class\b"
        ],
        "graduation": [
            r"\bgraduation\b", r"\bgraduate\b", r"\bregister\s*for\s*graduation\b",
            r"\bwhen\s*is\s*graduation\b", r"\bhow\s*to\s*graduate\b", r"\bgraduating\b",
            r"\bceremony\b", r"\bwhen\s*do\s*I\s*graduate\b", r"\bcompletion\b"
        ],
        "summary": [
            r"\btell\s*me\s*about\b", r"\bsummary\s*of\b", r"\bexplain\b", 
            r"\bwhat\s*is\b", r"\bbrief\s*on\b", r"\bwho\s*is\b", 
            r"\bdefine\b", r"\bdescribe\b", r"\bwhat\s*are\b", r"\bhow\s*does\b"
        ],
        "summarize": [
            r"\bsummar(y|ize|ise)\b",
            r"\b(shorten|condense|brief)\b",
            r"\bmain points?\b",
            r"\bkey ideas?\b",
            r"\bcan you (make|give).*shorter\b"
        ],
        "greeting": [
            r"\bhello\b", r"\bhi\b", r"\bhey\b", r"\bgreetings\b", 
            r"\bgood\s*(morning|afternoon|evening)\b", r"\bwhat's\s*up\b"
        ],
        "help": [
            r"\bhelp\b", r"\bwhat\s*can\s*you\s*do\b", r"\bassist\b", 
            r"\bsupport\b", r"\boptions\b", r"\bhow\s*to\s*use\b"
        ],
        "personal_info": [
            r"\bmy\s*info\b", r"\bmy\s*details\b", r"\bstudent\s*information\b",
            r"\bmy\s*profile\b", r"\babout\s*me\b", r"\bwho\s*am\s*I\b"
        ],
        "course_info": [
            r"\bcourse\s*details\b", r"\babout\s*my\s*course\b", 
            r"\bwhat's\s*my\s*course\b", r"\bprogram\s*info\b"
        ]
    }

    # Text processing functions for summarization
    def preprocess_text(text):
        """Basic text cleaning"""
        text = re.sub(r'\s+', ' ', text)  # Remove extra whitespace
        return text.strip()

    def extract_sentences(text):
        """Simple sentence splitting"""
        return re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s', text)

    def summarize_local(text, ratio=0.3):
        """Basic extractive summarization without external APIs"""
        sentences = extract_sentences(preprocess_text(text))
        if len(sentences) <= 3:
            return text  # Too short to summarize
        
        # Enhanced scoring:
        scored = []
        important_keywords = ['important', 'key', 'summary', 'conclusion', 'essential', 'main']
        for i, sent in enumerate(sentences):
            score = 0
            # Position scoring (first and last sentences are important)
            if i < 3 or i > len(sentences)-3:
                score += 2
            # Length scoring
            score += min(len(sent.split()) * 0.1, 3)  # Cap length importance
            # Keyword scoring
            if any(word in sent.lower() for word in important_keywords):
                score += 3
            # Question scoring
            if '?' in sent:
                score += 1
            # Number scoring
            if re.search(r'\d', sent):
                score += 1.5
            scored.append((score, sent))
        
        # Sort by score and take top sentences
        scored.sort(reverse=True, key=lambda x: x[0])
        keep = max(2, int(len(sentences) * ratio))  # Keep at least 2 sentences
        top_sentences = [s for _, s in scored[:keep]]
        
        # Maintain original order for coherence
        summary = []
        for sent in sentences:
            if sent in top_sentences:
                summary.append(sent)
        return ' '.join(summary)

    # Handle summarization requests
    def handle_summarization(prompt_text, attachments):
        # Case 1: Direct text in prompt
        if ':' in prompt_text: # e.g. "summarize: This is the text..."
            parts = prompt_text.split(':', 1)
            if len(parts) > 1:
                text_to_summarize = parts[1].strip()
                if len(text_to_summarize.split()) > 5: # Basic check for actual text
                    return summarize_local(text_to_summarize)
        
        # Case 2: Attachments with text
        for att in attachments:
            if att.get('type') == 'text' and att.get('content'):
                if len(att.get('content', '').split()) > 5: # Basic check for actual text
                    return summarize_local(att['content'])
        
        # Case 3: Follow-up to previous message (if previous message was substantial)
        # This requires storing previous interaction context, which is not fully implemented here.
        # For a stateless version, this might rely on client sending 'previous_message' in data.
        if data.get('previous_message') and len(data['previous_message'].split()) > 10:
            return summarize_local(data['previous_message'])
        
        return None # No suitable text found for summarization

    # Detect intent
    def detect_intent(user_prompt):
        for intent, patterns_list in question_patterns.items():
            for pattern in patterns_list:
                if re.search(pattern, user_prompt, re.IGNORECASE):
                    return intent
        return None

    intent = detect_intent(prompt)
    response = "I'm not sure how to help with that. Can you try rephrasing?" # Default response

    # Generate response based on intent
    if intent == "summarize":
        summary = handle_summarization(prompt, attachments)
        if summary:
            response = f"📝 Here's a summary:\n\n{summary}"
            if len(summary.split()) < len(prompt.split(':')[-1].strip().split()) and ':' in prompt : # Check if it actually summarized
                 response += f"\n\n(Reduced to {len(summary.split())} words)"
        else:
            response = ("Please provide the text you'd like summarized, either by:\n"
                        "1. Typing 'summarize: [your text]'\n"
                        "2. Attaching a text file with your text\n"
                        "3. Or, if you just sent a long message, ask me to 'summarize that'.")
    
    elif intent == "greeting":
        greeting = get_greeting()
        name = user.name.split()[0] if user.name else "Student"
        replies = [
            f"{greeting}, {name}! How can I assist you today?",
            f"{greeting}, {name}! What can I help you with?",
            f"{greeting} {name}! Ask me anything about your studies."
        ]
        response = random.choice(replies)

    elif intent == "help":
        response = (
            "📚 I'm your student portal assistant. I can help with:\n\n"
            "- Course resources and materials\n"
            "- Fee balances and payments\n"
            "- Attendance records\n"
            "- Class schedules\n"
            "- Graduation information\n"
            "- Summarizing your notes/text (type 'summarize: your text here')\n"
            "- General knowledge questions (e.g., 'tell me about Python')\n\n"
            "Try asking:\n"
            "- 'Show my attendance record'\n"
            "- 'What's my fee balance?'\n"
            "- 'When is my next class?'"
        )

    elif intent == "personal_info":
        response = (
            f"👤 Your Information:\n\n"
            f"Name: {user.name}\n"
            f"Admission: {user.admission_number}\n"
            f"Course: {user.course}\n"
            f"Cohort: {user.cohort}\n"
            f"Status: {user.graduation_status or 'Active'}"
        )

    elif intent == "resources":
        resources = Resource.query.filter_by(course=user.course, cohort=user.cohort).all()
        if resources:
            response = f"📂 You have {len(resources)} resources for {user.course} ({user.cohort}):\n\n"
            for i, r in enumerate(resources[:5], 1): # Show up to 5
                response += f"{i}. {r.title} ({r.type}) - <a href='{r.link}' target='_blank'>Open</a>\n"
            if len(resources) > 5:
                response += f"\nView all {len(resources)} on the Resources page."
        else:
            response = f"No specific resources found for your course ({user.course}, {user.cohort}) yet. Check the general resources or ask your instructor."

    elif intent == "fee":
        if user.fee_balance <= 0:
            response = f"✅ Your fees are fully paid! (Expected: KES {user.fee_expected:,.2f}, Paid: KES {user.fee_paid:,.2f})"
        else:
            response = (
                f"💳 Fee Balance:\n\n"
                f"Expected: KES {user.fee_expected:,.2f}\n"
                f"Paid: KES {user.fee_paid:,.2f}\n"
                f"**Remaining: KES {user.fee_balance:,.2f}**"
            )

    elif intent == "attendance":
        total, present, absent, percent = calculate_attendance_stats(user)
        if total == 0:
            response = "No attendance records found yet for your account."
        else:
            response = (
                f"📊 Attendance for {user.name}:\n\n"
                f"Present: {present}/{total} ({percent}%)\n"
                f"Absent: {absent}\n\n"
                f"{'👍 Excellent attendance!' if percent >= 90 else ('✅ Good job, keep it up!' if percent >=75 else '⚠️ Try to attend more classes to meet requirements.')}"
            )

    elif intent == "next_class":
        if user.next_class:
            now = datetime.now()
            delta = user.next_class - now
            
            if user.next_class < now: # Class has passed
                 status = f"This class was on {user.next_class.strftime('%A, %d %B %Y at %I:%M %p')}. Hope you attended!"
            elif delta.days == 0 and now.day == user.next_class.day : # Today
                status = f"Today, {user.next_class.strftime('%I:%M %p')}!"
            elif delta.days == 1 and now.day != user.next_class.day : # Tomorrow
                 status = f"Tomorrow, {user.next_class.strftime('%I:%M %p')}."
            else: # Future date
                status = f"In {delta.days +1} day{'s' if delta.days > 0 else ''} on {user.next_class.strftime('%A, %d %B')}"

            response = (
                f"📅 Next Class for {user.course}:\n\n"
                f"Date: {user.next_class.strftime('%A, %d %B %Y')}\n"
                f"Time: {user.next_class.strftime('%I:%M %p')}\n"
                f"Status: {status}"
            )
        else:
            response = "Your next class schedule hasn't been updated yet. Please check back later or contact administration."

    elif intent == "graduation":
        reg = GraduationRegistration.query.filter_by(student_email=user.email).first()
        latest_grad_event = GraduationInfo.query.filter(GraduationInfo.graduation_date != None).order_by(GraduationInfo.graduation_date.desc()).first()
        
        response = f"🎓 Graduation Status for {user.name}:\n"
        response += f"Overall Status: {user.graduation_status or 'Not yet specified'}\n"
        if reg:
            response += f"Registered for an event: Yes (as {reg.role})\n"
        else:
            response += "Registered for an event: No\n"
        
        if latest_grad_event and latest_grad_event.graduation_date:
             response += f"The next general graduation event is on: {latest_grad_event.graduation_date.strftime('%d %B, %Y')}.\n"
        else:
            response += "No upcoming general graduation event date announced yet.\n"
        response += "\nVisit the Graduation page for more details or to register if eligible."


    elif intent == "summary": # General knowledge summary using Wikipedia
        # Extract topic more robustly
        topic_match = re.search(r"(?:tell me about|summary of|what is|explain|define|describe)\s*(.+)", prompt, re.IGNORECASE)
        topic = topic_match.group(1) if topic_match else prompt # Fallback to whole prompt if specific keywords aren't there
        
        # Remove common conversational fillers if they are the topic itself
        fillers_to_remove = ["summary", "of", "the", "an", "a", "is", "are", "what", "tell", "me", "about"]
        topic_words = [word for word in topic.split() if word.lower() not in fillers_to_remove]
        topic = " ".join(topic_words).strip()

        if topic:
            try:
                # Set a custom user-agent for Wikipedia API
                wikipedia.set_user_agent("StudentPortalAssistant/1.0 (mercy@example.com)")
                summary = wikipedia.summary(topic, sentences=3, auto_suggest=True, redirect=True)
                page_url = wikipedia.page(topic, auto_suggest=True, redirect=True).url
                response = f"🔍 Here's a brief summary of '{topic.title()}':\n\n{summary}\n\n<a href='{page_url}' target='_blank'>Read more on Wikipedia</a>"
            except wikipedia.exceptions.PageError:
                response = f"Sorry, I couldn't find a Wikipedia page for '{topic}'. Please try a different topic or rephrase."
            except wikipedia.exceptions.DisambiguationError as e:
                options = "\n - ".join(e.options[:5]) # Show first 5 options
                response = f"Your topic '{topic}' is ambiguous. It could mean:\n - {options}\n\nPlease be more specific."
            except Exception as e: # Catch other potential errors like network issues
                response = f"Couldn't fetch information about '{topic}' at the moment. Error: {str(e)[:50]}" # Show a snippet of the error
        else:
            response = "What topic would you like me to summarize for you from Wikipedia?"

    else: # Fallback to generative AI if no specific intent is matched strongly
        if gpt_pipeline and len(prompt.split()) > 3: # Only use AI for substantial queries (changed from >2)
            try:
                # Construct a more specific prompt for the LLM
                contextual_prompt = (
                    f"Student question: {prompt}" # Simplified prompt for the model
                )
                generated = gpt_pipeline(
                    contextual_prompt,
                    max_length=150, # Keep as per original spec
                    min_length=10,
                    num_beams=2, 
                    early_stopping=True,
                    temperature=0.7 # Keep as per original spec
                )
                if generated and generated[0]['generated_text']:
                    response = generated[0]['generated_text']
                else:
                    app.logger.warning(f"AI assistant generated an empty response for prompt: {prompt}")
                    response = "I'm not sure I understand. Could you rephrase?"
            except Exception as e:
                app.logger.error(f"Error during AI assistant text generation: {e}", exc_info=True)
                response = "I'm having trouble answering that right now. Please try again later."
        else:
            # This block is for when gpt_pipeline is None or prompt is too short
            if not gpt_pipeline:
                 app.logger.info(f"AI assistant (gpt_pipeline) is None. Prompt '{prompt}' not processed by LLM.")
            elif len(prompt.split()) <= 3: # Adjusted from <=2
                 app.logger.info(f"Prompt '{prompt}' too short, not processed by LLM.")
            
            # Default responses if LLM not used
            responses = [
                "I'm not sure about that. Could you ask about your course or student records?",
                "I specialize in student information. Try asking about your classes or fees.",
                "Can you rephrase that? I'm best with questions about your studies."
            ]
            response = random.choice(responses)


    # Prepare contextual suggestions
    def get_suggestions(current_intent, user_status):
        base_suggestions = ["My fee balance", "Next class schedule", "Available resources", "My attendance"]
        
        if current_intent == "graduation" or user_status == "Awaiting Graduation":
            suggestions = ["Register for graduation", "Upcoming graduation dates", "Graduation media"]
        elif current_intent == "resources":
            suggestions = ["Summarize my notes", "Latest course uploads", "Help with an assignment"]
        elif current_intent == "fee":
             suggestions = ["How to pay fees", "Payment history", "Fee structure"]
        else:
            suggestions = random.sample(base_suggestions, min(len(base_suggestions), 3)) # Pick 3 random from base
        
        # Ensure no duplicates and limit to 3
        final_suggestions = []
        for s in suggestions:
            if s not in final_suggestions:
                final_suggestions.append(s)
        return final_suggestions[:3]
        
    return jsonify({
        'reply': response,
        'status': 'success', # Assuming most handled paths are successful replies
        'suggestions': get_suggestions(intent, user.graduation_status),
        'context': intent or "general_fallback" # Provide context for client-side logic
    })

if __name__ == '__main__':
    # Debug mode should be enabled only for development
    # In a production environment, use a WSGI server like Gunicorn or uWSGI
    # and set FLASK_DEBUG environment variable to 1 for development.
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
