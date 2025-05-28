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


try:
    gpt_pipeline = pipeline("text2text-generation", model="google/flan-t5-small")
except Exception:
    gpt_pipeline = None


app = Flask(__name__)
app.secret_key = 'Treplex@2025'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:@localhost/student_portal'
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
    password = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20))
    course = db.Column(db.String(100))
    cohort = db.Column(db.String(10))
    fee_expected = db.Column(db.Float, default=0.0)
    fee_paid = db.Column(db.Float, default=0.0)
    next_class = db.Column(db.DateTime)
    graduation_status = db.Column(db.String(100))
    completion_date = db.Column(db.Date)
    attendance_records = db.relationship('Attendance', backref='student', lazy=True)

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
    password = db.Column(db.String(100), nullable=False)

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
        date_obj = datetime.strptime(date_str, input_format)
        return date_obj.strftime(output_format)
    except:
        return date_str

def get_greeting():
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning"
    elif 12 <= hour < 17:
        return "Good afternoon"
    else:
        return "Good evening"

def extract_topic(prompt, patterns):
    for phrase in patterns:
        if phrase in prompt:
            return prompt.replace(phrase, "").strip()
    return prompt.strip()

# ----- Default\Student Routes ---------

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = User.query.filter_by(email=request.form['email']).first()
        if user and user.password == request.form['password']:
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
        if admin and admin.password == request.form['password']:
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
            password=request.form['password'],
            phone=request.form['phone'],
            course=course,
            cohort=cohort,
            admission_number=admission_number,
            fee_expected=float(request.form.get('fee_expected', 0)),
            fee_paid=float(request.form.get('fee_paid', 0)),
            graduation_status=request.form['graduation_status']
        )
        db.session.add(student)
        db.session.commit()

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

        date = datetime.strptime(request.form['date'], "%Y-%m-%d")
        status = request.form['status']
        next_class_str = request.form.get('next_class')

        attendance = Attendance(student_id=student_id, date=date, status=status)
        db.session.add(attendance)

        if next_class_str:
            next_class = datetime.strptime(next_class_str, "%Y-%m-%dT%H:%M")
            student = User.query.get(student_id)
            student.next_class = next_class

        db.session.commit()
        flash("Attendance and next class updated.")
        return redirect(url_for('admin_attendance'))

    attendance_records = Attendance.query.order_by(Attendance.date.desc()).limit(20).all()
    cohorts = db.session.query(User.cohort).distinct().all()

    return render_template(
        'Admin-Section/attendance-management.html',
        courses=COURSES,
        cohorts=[c[0] for c in cohorts],
        students=students,
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
        student.password = request.form['password']
        student.fee_expected = float(request.form.get('fee_expected', 0))
        student.fee_paid = float(request.form.get('fee_paid', 0))
        student.graduation_status = request.form['graduation_status']
        if request.form.get('completion_date'):
            student.completion_date = datetime.strptime(request.form['completion_date'], "%Y-%m-%d")
        db.session.commit()
        return redirect(url_for('manage_students'))
    return render_template('Admin-Section/edit-student.html', student=student, courses=COURSES)

@app.route('/admin/student/delete/<int:id>', methods=['POST'])
def delete_student(id):
    if 'admin' not in session:
        return redirect(url_for('admin_login'))
    db.session.delete(User.query.get_or_404(id))
    db.session.commit()
    return redirect(url_for('manage_students'))

@app.route('/admin/graduation', methods=['GET', 'POST'])
def manage_graduation():
    if 'admin' not in session:
        return redirect(url_for('admin_login'))

    if request.method == 'POST':
        if 'student_id' in request.form:
            student = User.query.get_or_404(request.form['student_id'])
            student.graduation_status = 'Graduated'
            db.session.commit()
            flash(f"{student.name} marked as Graduated.")
        else:
            date_str = request.form.get('graduation_date')
            title = request.form.get('media_title')
            link = request.form.get('media_link')

            if date_str:
                grad_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                db.session.add(GraduationInfo(graduation_date=grad_date))

            if title and link:
                db.session.add(GraduationInfo(media_title=title, media_link=link))

            db.session.commit()
            flash("Graduation details updated.")

    students = User.query.all()
    grad_info = GraduationInfo.query.all()

    return render_template(
        'Admin-Section/manage-graduation.html',
        students=students,
        graduation_info=grad_info
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
        if ':' in prompt_text:
            text_to_summarize = prompt_text.split(':', 1)[1].strip()
            if len(text_to_summarize.split()) > 5:
                return summarize_local(text_to_summarize)
        
        # Case 2: Attachments with text
        for att in attachments:
            if att.get('type') == 'text' and len(att.get('content', '').split()) > 5:
                return summarize_local(att['content'])
        
        # Case 3: Follow-up to previous message
        if 'previous_message' in data and len(data['previous_message'].split()) > 10:
            return summarize_local(data['previous_message'])
        
        return None

    # Detect intent
    def detect_intent(user_prompt):
        for intent, patterns in question_patterns.items():
            for pattern in patterns:
                if re.search(pattern, user_prompt, re.IGNORECASE):
                    return intent
        return None

    intent = detect_intent(prompt)

    # Generate response based on intent
    if intent == "summarize":
        summary = handle_summarization(prompt, attachments)
        if summary:
            response = f"📝 Here's a summary:\n\n{summary}\n\n(Reduced to {len(summary.split())} words from original)"
        else:
            response = "Please provide the text you'd like summarized, either by:\n1. Typing 'summarize: [your text]'\n2. Attaching a text file\n3. Following up after sending long text"
    
    elif intent == "greeting":
        greeting = get_greeting()
        name = user.name.split()[0]
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
            "- Summarizing your notes/text\n"
            "- General knowledge questions\n\n"
            "Try asking:\n"
            "- 'Show my attendance record'\n"
            "- 'What's my fee balance?'\n"
            "- 'Summarize: [your text]'\n"
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
            response = f"📂 You have {len(resources)} resources for {user.course}:\n\n"
            for i, r in enumerate(resources[:3], 1):
                response += f"{i}. {r.title} ({r.type})\n"
            if len(resources) > 3:
                response += f"\nView all {len(resources)} on the Resources page."
        else:
            response = "No resources available for your course yet."

    elif intent == "fee":
        if user.fee_balance <= 0:
            response = "✅ Your fees are fully paid!"
        else:
            response = (
                f"💳 Fee Balance:\n\n"
                f"Expected: KES {user.fee_expected:,.2f}\n"
                f"Paid: KES {user.fee_paid:,.2f}\n"
                f"Remaining: KES {user.fee_balance:,.2f}"
            )

    elif intent == "attendance":
        total, present, absent, percent = calculate_attendance_stats(user)
        if total == 0:
            response = "No attendance records found yet."
        else:
            response = (
                f"📊 Attendance:\n\n"
                f"Present: {present}/{total} ({percent}%)\n"
                f"Absent: {absent}\n\n"
                f"{'👍 Good attendance!' if percent >= 80 else '⚠️ Try to attend more classes'}"
            )

    elif intent == "next_class":
        if user.next_class:
            now = datetime.now()
            delta = user.next_class - now
            if delta.days < 0:
                status = "This class has passed"
            elif delta.days == 0:
                status = "Today!"
            else:
                status = f"In {delta.days} day{'s' if delta.days != 1 else ''}"
            
            response = (
                f"📅 Next Class:\n\n"
                f"Date: {user.next_class.strftime('%A, %d %B %Y')}\n"
                f"Time: {user.next_class.strftime('%I:%M %p')}\n"
                f"Status: {status}"
            )
        else:
            response = "Your next class hasn't been scheduled yet."

    elif intent == "graduation":
        reg = GraduationRegistration.query.filter_by(student_email=user.email).first()
        response = (
            f"🎓 Graduation Status:\n\n"
            f"Registered: {'Yes' if reg else 'No'}\n"
            f"Role: {reg.role if reg else 'Not registered'}\n\n"
            f"Visit the Graduation page for details."
        )

    elif intent == "summary":
        topic = prompt.replace("summary", "").replace("of", "").strip()
        if topic:
            try:
                summary = wikipedia.summary(topic, sentences=2)
                response = f"🔍 About {topic.title()}:\n\n{summary}"
            except:
                response = f"Couldn't find information about '{topic}'. Try rephrasing."
        else:
            response = "What topic would you like me to summarize?"

    else:
        # Fallback to generative AI if available
        if gpt_pipeline and len(prompt.split()) > 3:  # Only use AI for substantial queries
            try:
                generated = gpt_pipeline(
                    f"Student question: {prompt}",
                    max_length=150,
                    temperature=0.7
                )
                if generated:
                    response = generated[0]['generated_text']
                else:
                    response = "I'm not sure I understand. Could you rephrase?"
            except:
                response = "I'm having trouble answering that right now."
        else:
            responses = [
                "I'm not sure about that. Could you ask about your course or student records?",
                "I specialize in student information. Try asking about your classes or fees.",
                "Can you rephrase that? I'm best with questions about your studies."
            ]
            response = random.choice(responses)

    # Prepare contextual suggestions
    def get_suggestions(current_intent):
        suggestions_map = {
            "resources": ["Show all resources", "Latest uploads", "Course materials"],
            "fee": ["Payment options", "Fee breakdown", "Payment deadline"],
            "attendance": ["My attendance", "Absence reasons", "Upcoming classes"],
            "summarize": ["Summarize my notes", "Condense this text", "Key points"],
            None: ["My next class", "Course progress", "Graduation info"]
        }
        return suggestions_map.get(current_intent, suggestions_map[None])

    return jsonify({
        'reply': response,
        'status': 'success',
        'suggestions': get_suggestions(intent)[:3],
        'context': intent
    })

if __name__ == '__main__':
    app.run(debug=True)
