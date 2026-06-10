import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import login_required
from itsdangerous import URLSafeTimedSerializer

# Configure application
app = Flask(__name__)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///diabetes.db")

# Secret key to reset password.
app.config["SECRET_KEY"] = ####
s = URLSafeTimedSerializer(app.config["SECRET_KEY"])


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/", methods=["GET", "POST"])
def index():

    user_id = session.get("user_id")

    # The calculation form starts empty with no saved and no insulin_total displaying
    # GET
    icr = None
    isf = None
    target_glucose = 100
    insulin_total = None
    saved = False

    # Preload settings if user logged in:
    if user_id:
        rows = db.execute(
            "SELECT icr, isf, target_glucose FROM insulin_ratios WHERE user_id = ?",
            user_id
        )

        if rows:
            icr = rows[0]["icr"]
            isf = rows[0]["isf"]
            if rows[0]["target_glucose"]:
                target_glucose = rows[0]["target_glucose"]

    # POST:
    if request.method == "POST":

        action = request.form.get("action")

        # Get raw values imputed by user
        icr_input = request.form.get("icr")
        isf_input = request.form.get("isf")
        carbs_input = request.form.get("carbohydrate_content")
        glycemia_input = request.form.get("glycemia")
        target_input = request.form.get("target_glucose")

        # Convert safely
        try:
            icr = float(icr_input) if icr_input else None
            isf = float(isf_input) if isf_input else None
            carbs = float(carbs_input) if carbs_input else None
            glycemia = float(glycemia_input) if glycemia_input else None

            if target_input:
                target_glucose = float(target_input)

        except ValueError:
            return "Invalid input"


        # Save settings if user press button save ICR/ISF Target glucose
        if action == "save_settings":

            if not user_id:
                return redirect("/login")


            # This is to fix input overwrite behavior, in case user deletes a preloaded value and leaves blank.
            if not all([icr, isf, target_glucose]):
                flash("ICR/ ISF and target glucose fields required to save settings")
                return redirect("/")


            # Positive checks
            if icr <= 0 or isf <= 0 or target_glucose <= 0:
                flash("Values must be positive")
                return redirect("/")


            # Check if user exists on database
            rows = db.execute(
                "SELECT id FROM insulin_ratios WHERE user_id = ?",
                user_id
            )

            # If it's users' first time:
            if len(rows) == 0:
                db.execute(
                    "INSERT INTO insulin_ratios (user_id, icr, isf, target_glucose) VALUES(?, ?, ?, ?)",
                    user_id, icr, isf, target_glucose
                )

            # If the user is returning:
            else:
                db.execute(
                    "UPDATE insulin_ratios SET icr = ?, isf = ?, target_glucose = ? WHERE user_id = ?",
                    icr, isf, target_glucose, user_id
                )


            #saved = True
            flash("Your settings have been updated!")



        if action == "calculate":
            # Required fields
            if not all([icr, isf, carbs, glycemia]):
                flash("All fields required")
                return redirect("/")

            # Positive checks
            if icr <= 0 or isf <= 0 or glycemia <= 0:
                flash("Must enter a positive number")
                return redirect("/")

            if carbs < 0:
                flash("Carbs cannot be negative")
                return redirect("/")


            insulin_carb = carbs / icr
            insulin_corr = (glycemia - target_glucose) / isf
            insulin_total = insulin_carb + insulin_corr

            if insulin_total < 0:
                insulin_total = 0

            insulin_total = round(insulin_total, 1)

            # Save glycemia on database
            if user_id:
                db.execute(
                    "INSERT INTO glucose_logs (user_id, glycemia) VALUES (?, ?)",
                    user_id, glycemia
                )


    # Load logs (important). They will be used in other features.
    logs = []
    if user_id:

        logs = db.execute(
            "SELECT glycemia, timestamp, strftime('%m-%d %H:%M', timestamp) AS time_label FROM glucose_logs WHERE user_id = ? AND timestamp  >= datetime('now','-72 hours') ORDER BY timestamp ASC",
            user_id
        )


    # FINAL RENDER - VERY IMPORTANT
    return render_template(
        "index.html",
        icr=icr,
        isf=isf,
        target_glucose=target_glucose,
        insulin=insulin_total,
        saved=saved,
        logs=logs
    )


@app.route("/history")
@login_required
def history():

    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")


    # Logs for table
    table_logs = db.execute(
        "SELECT glycemia, timestamp FROM glucose_logs WHERE user_id = ? AND timestamp >= datetime('now','-48 hours') ORDER BY timestamp DESC LIMIT 10",
        user_id
    )
    # Logs for chart
    logs = db.execute(
        "SELECT glycemia, timestamp, strftime('%H:%M', timestamp) AS time_label FROM glucose_logs WHERE user_id = ? AND timestamp  >= datetime('now','-72 hours') ORDER BY timestamp ASC",
        user_id
    )

    # Logs for SVG circle
    range_logs = db.execute(
        "SELECT glycemia FROM glucose_logs WHERE user_id = ? AND timestamp  >= date('now', '-24 hours')",
        user_id
    )

    settings = db.execute(
        "SELECT target_range_min, target_range_max FROM insulin_ratios WHERE user_id = ?",
        user_id
    )

    if not settings:
        target_min = 80
        target_max = 130
    else:
        target_min = settings[0]["target_range_min"]
        target_max = settings[0]["target_range_max"]

        # Handle NULL values
        if target_min is None or target_max is None:
            target_min = 80
            target_max = 130

    # Convert
    target_min = float(target_min)
    target_max = float(target_max)

        # Calculate
    if target_min is None or target_max is None:
        percentage = 0
    else:
        total = len(range_logs)

    if total == 0:
        percentage = 0
    # If not 0, set counter
    else:
        in_range = 0

        for log in range_logs:
            value = log["glycemia"] # This is very important

            if value is None:
                continue # skip bad data

            if target_min <= value <= target_max:
                in_range += 1

        percentage = round((in_range / total) * 100)


    return render_template("history.html", logs=logs, table_logs=table_logs, percentage=percentage)



@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    #session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            flash("Username required")
            return redirect("/login")

        # Ensure password was submitted
        elif not request.form.get("password"):
            flash("Password required")
            return redirect("/login")

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            flash("Invalid username and/or password")
            return redirect("/login")


        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    session.clear()

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        dob = request.form.get("dob")
        email = request.form.get("email")

        icr = request.form.get("icr")
        isf = request.form.get("isf")
        target_glucose = request.form.get("target_glucose")

        # Convert safely and don't accept negative values:
        try:
            icr = float(icr) if icr else None
        except ValueError:
            flash("ICR must be a number")
            return render_template("register.html")

        if icr is None or icr <= 0:
            flash("ICR must be a positive number")
            return render_template("register.html")

        try:
            isf = float(isf) if isf else None
        except ValueError:
            flash("ISF must be a number")
            return render_template("register.html")

        if isf is None or isf <= 0:
            flash("ISF must be a positive number")
            return render_template("register.html")

        try:
            target_glucose = float(target_glucose) if target_glucose else None
        except ValueError:
            flash("Invalid target glucose")
            return render_template("register.html")

        if target_glucose is None or target_glucose <= 0:
            flash("Target glucose must be a positive number")
            return render_template("register.html")


        target_range = request.form.get("target_range")

        if not target_range:
            flash("Please select a target range")
            return render_template("register.html")

        if target_range == "custom":
            target_min = request.form.get("target_min")
            target_max = request.form.get("target_max")

            if not target_min or not target_max:
                flash("Custom range requires min and max")
                return render_template("register.html")

            try:
                target_min = float(target_min)
                target_max = float(target_max)
            except ValueError:
                flash("Invalid custom range")
                return render_template("register.html")

            if target_min <= 0:
                flash("Target range must be a positive number")
                return render_template("register.html")

            if target_max <= 0:
                flash("Target range must be a positive number")
                return render_template("register.html")

        else:
            target_min, target_max = target_range.split("-")
            target_min = float(target_min)
            target_max = float(target_max)

        if not username:
            flash("Username required")
            return render_template("register.html")

        if not password or password != confirmation:
            flash("Passwords must match")
            return render_template("register.html")


        # Check if user exists
        try:
            user_id = db.execute(
                " " "INSERT INTO users (username, hash, first_name, last_name, dob, email) VALUES (?, ?, ?, ?, ?, ?)" " ",
                username,
                generate_password_hash(password),
                first_name,
                last_name,
                dob,
                email
            )

        except Exception as e:
            print(e)
            flash("Username or email already exists")
            return render_template("register.html")


        # Save medical settings
        db.execute(
            " " "INSERT INTO insulin_ratios (user_id, icr, isf, target_glucose, target_range_min, target_range_max) VALUES (?, ?, ?, ?, ?, ?)" " ",
            user_id,
            icr,
            isf,
            target_glucose,
            target_min,
            target_max
        )

        session["user_id"] = user_id

        return redirect("/")

    return render_template("register.html")


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email")

        # Check if email exists in database
        user = db.execute(
            "SELECT * FROM users WHERE email = ?", email)

        if not user:
            flash("If the email exists, a reset link will be generated.")
            return redirect("/forgot")

        # Generate token
        token = s.dumps(email, salt="password-reset")

        db.execute(
            "UPDATE users SET reset_token = ? WHERE email = ?",
            token,
            email
        )

        # Create reset link
        reset_link = f"http://127.0.0.1:5000/reset/{token}"

        # For now, show it (later we email it)
        return render_template("forgot.html", link=reset_link)

    return render_template("forgot.html")


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    # Check token exists in DB
    user = db.execute(
        "SELECT * FROM users WHERE reset_token = ?",
        token
    )
    if not user:
        return "Invalid or already used link"

    # Verify token cryptographically
    try:
        email = s.loads(token, salt="password-reset", max_age=3600)
    except:
        return "Expired or invalid"
        # Another option:
        #flash("This reset link is invalid or expired.")
        #return redirect("/forgot")


    if request.method == "POST":
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not password or password != confirmation:
            #return "Passwords must match"
            flash("Passwords must match")
            return render_template("reset.html")

        # Update password AND invalidate token on same query.
        db.execute(
            "UPDATE users SET hash = ?, reset_token = NULL WHERE email = ?",
            generate_password_hash(password),
            email
        )


        return redirect("/login")


    # If GET, just show the form
    return render_template("reset.html")


@app.route("/knowmore")
def knowmore():
    return render_template("knowmore.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/settings", methods= ["GET", "POST"])
@login_required
def settings():

    user_id = session["user_id"]

    if request.method == "POST":

        icr = request.form.get("icr")
        isf = request.form.get("isf")
        target_glucose = request.form.get("target_glucose")
        target_range_min = request.form.get("target_range_min")
        target_range_max = request.form.get("target_range_max")

        # Convert safely and don't accept negative values:
        try:
            icr = float(icr) if icr else None
        except ValueError:
            flash("Invalid ICR")
            return redirect("/settings")

        if icr is None or icr <= 0:
            flash("ICR must be a positive number")
            return redirect("/settings")


        try:
            isf = float(isf) if isf else None
        except ValueError:
            flash("Invalid ISF")
            return redirect("/settings")

        if isf is None or isf <= 0:
            flash("ISF must be a positive number")
            return redirect("/settings")


        try:
            target_glucose = float(target_glucose) if target_glucose else None
        except ValueError:
            flash("Invalid target glucose")
            return redirect("/settings")

        if target_glucose is None or target_glucose <= 0:
            flash("Target glucose must be a positive number")
            return redirect("/settings")


        try:
            target_range_min = float(target_range_min) if target_range_min else None
        except ValueError:
            flash("Invalid minimun target")
            return redirect("/settings")

        if target_range_min is None or target_range_min <= 0:
            flash("Must enter a positive number")
            return redirect("/settings")


        try:
            target_range_max = float(target_range_max) if target_range_max else None
        except ValueError:
            flash("Invalid Minimun target")
            return redirect("/settings")

        if target_range_max is None or target_range_max <= 0:
            flash("Must enter a positive number")
            return redirect("/settings")


        db.execute(
            "UPDATE insulin_ratios SET icr = ?, isf = ?, target_glucose = ?, target_range_min = ?, target_range_max = ? WHERE user_id = ?",
            icr, isf, target_glucose, target_range_min, target_range_max, user_id
        )

    # Now that the form is done, display the updated values.
    rows = db.execute(
            "SELECT icr, isf, target_glucose, target_range_min, target_range_max FROM insulin_ratios WHERE user_id = ?",
            user_id
        )


    return render_template("settings.html", settings=rows[0])








