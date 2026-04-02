import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

database_url = os.environ.get("DATABASE_URL", "sqlite:///tracker.db")
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Сначала войди в аккаунт."


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False, unique=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)

    actions = db.relationship("Action", backref="user", lazy=True, cascade="all, delete-orphan")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Action(db.Model):
    __tablename__ = "actions"

    id = db.Column(db.Integer, primary_key=True)
    action_name = db.Column(db.String(120), nullable=False)
    count = db.Column(db.Integer, nullable=False)
    action_datetime = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.context_processor
def inject_now():
    return {"now": datetime.now()}


@app.route("/")
def home():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))

    actions = (
        Action.query
        .filter_by(user_id=current_user.id)
        .order_by(Action.action_datetime.desc())
        .all()
    )

    summary_map = {}
    for action in actions:
        summary_map[action.action_name] = summary_map.get(action.action_name, 0) + action.count

    summary = sorted(summary_map.items(), key=lambda x: (-x[1], x[0]))

    edit_id = request.args.get("edit")
    edit_item = None
    if edit_id and edit_id.isdigit():
        edit_item = Action.query.filter_by(id=int(edit_id), user_id=current_user.id).first()

    chart_labels = [item[0] for item in summary]
    chart_values = [item[1] for item in summary]

    return render_template(
        "index.html",
        actions=actions,
        summary=summary,
        edit_item=edit_item,
        chart_labels=chart_labels,
        chart_values=chart_values,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not username or not email or not password:
            flash("Заполни все поля.")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Пароль должен быть минимум 6 символов.")
            return redirect(url_for("register"))

        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            flash("Пользователь с таким именем или email уже существует.")
            return redirect(url_for("register"))

        user = User(username=username, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Аккаунт создан.")
        return redirect(url_for("home"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        user = User.query.filter_by(email=email).first()

        if not user or not user.check_password(password):
            flash("Неверный email или пароль.")
            return redirect(url_for("login"))

        login_user(user)
        flash("Ты вошёл в аккаунт.")
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Ты вышел из аккаунта.")
    return redirect(url_for("login"))


@app.route("/add", methods=["POST"])
@login_required
def add_action():
    action_name = request.form.get("action_name", "").strip()
    count_raw = request.form.get("count", "").strip()
    action_datetime_raw = request.form.get("action_datetime", "").strip()

    if not action_name or not count_raw or not action_datetime_raw:
        flash("Заполни все поля.")
        return redirect(url_for("home"))

    try:
        count = int(count_raw)
        if count < 1:
            raise ValueError
        action_datetime = datetime.strptime(action_datetime_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Проверь количество и дату.")
        return redirect(url_for("home"))

    action = Action(
        action_name=action_name,
        count=count,
        action_datetime=action_datetime,
        user_id=current_user.id,
    )

    db.session.add(action)
    db.session.commit()

    flash("Запись добавлена.")
    return redirect(url_for("home"))


@app.route("/update/<int:action_id>", methods=["POST"])
@login_required
def update_action(action_id):
    action = Action.query.filter_by(id=action_id, user_id=current_user.id).first_or_404()

    action_name = request.form.get("action_name", "").strip()
    count_raw = request.form.get("count", "").strip()
    action_datetime_raw = request.form.get("action_datetime", "").strip()

    if not action_name or not count_raw or not action_datetime_raw:
        flash("Заполни все поля.")
        return redirect(url_for("home", edit=action_id))

    try:
        count = int(count_raw)
        if count < 1:
            raise ValueError
        action_datetime = datetime.strptime(action_datetime_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Проверь количество и дату.")
        return redirect(url_for("home", edit=action_id))

    action.action_name = action_name
    action.count = count
    action.action_datetime = action_datetime

    db.session.commit()
    flash("Запись обновлена.")
    return redirect(url_for("home"))


@app.route("/delete/<int:action_id>")
@login_required
def delete_action(action_id):
    action = Action.query.filter_by(id=action_id, user_id=current_user.id).first_or_404()
    db.session.delete(action)
    db.session.commit()
    flash("Запись удалена.")
    return redirect(url_for("home"))


@app.route("/init-db")
def init_db():
    with app.app_context():
        db.create_all()
    return "База данных создана."


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)