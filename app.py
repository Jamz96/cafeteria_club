# -*- coding: utf-8 -*-
"""
Created on Wed Mar 12 02:19:44 2025

@author: moreno
"""

import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_migrate import Migrate
from models import db, User, bcrypt
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
from functools import wraps

# Configuración de la base de datos (Flask)
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///club_cafeteria.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = "clave_super_segura"

# Inicializar la base de datos y bcrypt
db.init_app(app)
bcrypt.init_app(app)
migrate = Migrate(app, db)

# Configuración de Google Sheets
SPREADSHEET_ID = "1pHGmlOmXcOl085IjFqcdCy3zV8XaIzCzmCil8RsnnSk"
RANGE_NAME = "Resumen!A1:E50"

def get_user_data(username):
    """
    Busca en Google Sheets la información del usuario y la devuelve en un diccionario.
    """
    
    # Durante desarrollo local, si existe credentials.json, úsalo. 
    # En producción (Render), usarás /etc/secrets/CREDENTIALS_JSON
    if os.path.exists("credentials.json"):
        SECRET_FILE_PATH = "credentials.json"
    else:
        # La ruta que Render te dará para el Secret File
        SECRET_FILE_PATH = "/etc/secrets/credentials.json"
    
    creds = service_account.Credentials.from_service_account_file(
        SECRET_FILE_PATH,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )

    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()
    
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=RANGE_NAME).execute()
    values = result.get('values', [])

    if not values:
        return None

    headers = values[0]  # Primera fila (encabezados)
    data_rows = values[1:]  # Resto de filas

    for row in data_rows:
        if len(row) >= 5 and row[0].strip().lower() == username.strip().lower():
            return {
                "usuario": row[0],
                "total_aportado": row[1],
                "total_consumido": row[2],
                "balance": row[3],
                "estado": row[4]
            }
    
    return None

def get_user_consumption_history(username):
    """
    Obtiene el historial de consumos del usuario desde la hoja 'RegistroConsumo'.
    """
    credentials_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    
    if not os.path.exists(credentials_path):
        print("❌ ERROR: No se encontró el archivo 'credentials.json'.")
        return []

    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )

    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="RegistroConsumo!A1:D").execute()
    values = result.get('values', [])

    if not values:
        return []

    headers = values[0]  # Primera fila (encabezados)
    data_rows = values[1:]  # Resto de filas

    user_consumption = []
    for row in data_rows:
        if len(row) >= 4 and row[1].strip().lower() == username.strip().lower():
            user_consumption.append({
                "fecha": row[0],
                "producto": row[2],
                "cantidad": row[3]
            })

    return user_consumption

def get_user_income_history(username):
    """
    Obtiene el historial de ingresos del usuario desde la hoja 'Ingresos'.
    """
    credentials_path = os.path.join(os.path.dirname(__file__), "credentials.json")
    
    if not os.path.exists(credentials_path):
        print("❌ ERROR: No se encontró el archivo 'credentials.json'.")
        return []

    creds = service_account.Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )

    service = build('sheets', 'v4', credentials=creds)
    sheet = service.spreadsheets()

    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range="Ingresos!A1:C").execute()
    values = result.get('values', [])

    if not values:
        return []

    headers = values[0]  # Primera fila (encabezados)
    data_rows = values[1:]  # Resto de filas

    user_income = []
    for row in data_rows:
        if len(row) >= 3 and row[1].strip().lower() == username.strip().lower():
            user_income.append({
                "fecha": row[0],
                "monto": row[2]
            })

    return user_income

def get_monthly_summary(username):
    """Obtiene los consumos e ingresos del mes actual desde Google Sheets."""
    today = datetime.today()
    current_month = today.strftime("%m")  # Obtiene el mes actual en formato MM
    current_year = today.strftime("%Y")  # Obtiene el año actual en formato YYYY

    # Obtener historial de consumos e ingresos
    consumption_history = get_user_consumption_history(username)
    income_history = get_user_income_history(username)

    # Filtrar solo los registros del mes actual
    filtered_consumption = []
    filtered_income = []

    for item in consumption_history:
        try:
            fecha_limpia = item["fecha"].split(" ")[0]  # Extraer solo la fecha sin la hora
            fecha_obj = datetime.strptime(fecha_limpia, "%d/%m/%Y")  # Convertir la fecha
            if fecha_obj.strftime("%m") == current_month and fecha_obj.strftime("%Y") == current_year:
                item["cantidad"] = int(float(item["cantidad"]))  # Convertir a número entero
                filtered_consumption.append(item)
        except ValueError:
            print(f"⚠ Error de formato en fecha o cantidad: {item}")

    for item in income_history:
        try:
            fecha_limpia = item["fecha"].split(" ")[0]  # Extraer solo la fecha sin la hora
            fecha_obj = datetime.strptime(fecha_limpia, "%d/%m/%Y")  # Convertir la fecha
            if fecha_obj.strftime("%m") == current_month and fecha_obj.strftime("%Y") == current_year:
                item["monto"] = "{:.2f} €".format(float(item["monto"]))  # Convertir a dos decimales y añadir €
                filtered_income.append(item)
        except ValueError:
            print(f"⚠ Error de formato en fecha o monto: {item}")

    return {
        "transactions_consumption": filtered_consumption,
        "transactions_income": filtered_income
    }

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        """Verifica si el usuario es administrador antes de acceder a la página."""
        if "user_id" not in session:
            flash("Debes iniciar sesión para acceder a esta página.", "danger")
            return redirect(url_for("login"))
        
        if not session.get("is_admin", False):  # Verifica si es admin en la sesión
            flash("No tienes permisos para acceder a esta página.", "danger")
            return redirect(url_for("profile"))

        return f(*args, **kwargs)
    return decorated_function

# ---------------------- RUTA DE INICIO ----------------------
@app.route("/")
def index():
    """Página de bienvenida."""
    return render_template("index.html")

# ---------------------- LOGIN ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Página de login con nickname.
    """
    if request.method == "POST":
        nickname = request.form.get("nickname")  # Ahora usamos nickname
        password = request.form.get("password")

        user = User.query.filter_by(nickname=nickname).first()

        if user and user.check_password(password):
            session["user_id"] = user.id  # Guardamos el ID del usuario
            session["username"] = user.username  # Guardamos el nombre completo
            session["nickname"] = user.nickname  # Guardamos el nickname
            session["is_admin"] = user.is_admin  # Guardamos si es administrador

            flash("Inicio de sesión exitoso.", "success")

            # Redirigir al panel de administración si es admin
            
            return redirect(url_for("profile"))

        flash("Credenciales incorrectas.", "danger")
        return render_template("login.html")

    return render_template("login.html")

# ---------------------- REGISTRO ----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Página de registro de nuevos usuarios con nickname.
    """
    if request.method == "POST":
        username = request.form.get("username")
        nickname = request.form.get("nickname")
        password = request.form.get("password")

        print(f"DEBUG - username: {username}, nickname: {nickname}, password: {password}")  # Nueva línea de depuración

        if not nickname:
            return render_template("register.html", error="El campo 'Nickname' es obligatorio.")

        existing_user = User.query.filter_by(username=username).first()
        existing_nickname = User.query.filter_by(nickname=nickname).first()

        if existing_user:
            return render_template("register.html", error="El usuario ya existe.")
        if existing_nickname:
            return render_template("register.html", error="El nickname ya está en uso.")

        new_user = User(username=username, nickname=nickname)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("register.html")

# ---------------------- PERFIL DEL USUARIO ----------------------
@app.route("/profile")
def profile():
    """
    Página de perfil del usuario logueado con datos desde Google Sheets.
    """
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    user_data = get_user_data(username)
    monthly_summary = get_monthly_summary(username)

    if not user_data:
        return render_template("profile.html", username=username, error="No se encontraron datos en Google Sheets.")

    return render_template("profile.html", username=username, user_data=user_data, monthly_summary=monthly_summary)


# --------------------- PERFIL ADMINISTRADOR ---------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    """
    Página de administración. Muestra saldos de Google Sheets.
    """
    # Obtenemos todos los usuarios de la base de datos.
    users = User.query.all()
    users_data = []

    for u in users:
        # Datos en Google Sheets
        data_sheets = get_user_data(u.username)

        if data_sheets and data_sheets["balance"]:
            # raw_balance podría ser algo como "-5,60" o "-5,60 €"
            raw_balance = data_sheets["balance"]
            # Quitar símbolo de euro si lo hay, cambiar coma por punto, convertir a float
            raw_balance = raw_balance.replace("€", "").strip().replace(",", ".")
            try:
                float_balance = float(raw_balance)
            except ValueError:
                float_balance = 0.0
        else:
            float_balance = 0.0

        users_data.append({
            "username": u.username,
            "nickname": u.nickname,
            "balance": float_balance
        })

    # Top 3 de menos saldo
    top_users = sorted(users_data, key=lambda x: x["balance"])[:3]

    return render_template("admin.html", users=users_data, top_users=top_users)


# --------------------- EDITAR PERFIL DE USUARIO ---------------------
@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    """
    Permite a los usuarios cambiar su nickname y contraseña.
    """
    if "username" not in session:
        return redirect(url_for("login"))

    user = User.query.filter_by(username=session["username"]).first()

    if request.method == "POST":
        new_nickname = request.form.get("new_nickname")
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")

        changes_made = False  # Variable para verificar si hubo cambios

        # Validar si el nickname ya está en uso y actualizarlo
        if new_nickname and new_nickname != user.nickname:
            existing_nickname = User.query.filter_by(nickname=new_nickname).first()
            if existing_nickname:
                flash("El nickname ya está en uso, elige otro.", "danger")
                return redirect(url_for("edit_profile"))

            user.nickname = new_nickname
            session["nickname"] = new_nickname  # Actualizar en sesión
            changes_made = True
            flash("Nickname actualizado con éxito.", "success")

        # Validar la contraseña antes de cambiarla
        if new_password and current_password:
            if not user.check_password(current_password):
                flash("Contraseña actual incorrecta.", "danger")
                return redirect(url_for("edit_profile"))

            user.set_password(new_password)
            changes_made = True
            flash("Contraseña cambiada correctamente.", "success")

        if changes_made:
            db.session.commit()
        else:
            flash("No se realizaron cambios en el perfil.", "warning")

        return redirect(url_for("edit_profile"))

    return render_template("edit_profile.html", user=user)

# ---------------------- HISTORIAL DE CONSUMOS ----------------------
@app.route("/history/consumption")
def consumption_history():
    """
    Página que muestra el historial de consumos del usuario.
    """
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    history = get_user_consumption_history(username)

    return render_template("consumption_history.html", history=history)

# ---------------------- HISTORIAL DE INGRESOS ----------------------
@app.route("/history/income")
def income_history():
    """
    Página que muestra el historial de ingresos del usuario.
    """
    if "username" not in session:
        return redirect(url_for("login"))

    username = session["username"]
    history = get_user_income_history(username)

    return render_template("income_history.html", history=history)


# ---------------------- CERRAR SESIÓN ----------------------
@app.route("/logout")
def logout():
    """
    Cierra sesión del usuario.
    """
    session.clear()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("index"))



# 🔹 Solución: Crear la base de datos antes de ejecutar la aplicación
if __name__ == "__main__":
    try:
        with app.app_context():
            db.create_all()  # Crea la base de datos si no existe
        print("🚀 Servidor Flask iniciándose en http://127.0.0.1:5000/")
        app.run(debug=True)
    except Exception as e:
        print("❌ Error al iniciar la aplicación:", e)
        input("Presiona Enter para cerrar...")


