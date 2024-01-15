import matplotlib.pyplot as plt
import threading
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, get_flashed_messages
import sqlite3
from datetime import datetime
import csv
import os
import glob
import numpy as np
from queue import Queue
import hashlib

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'

# Setarea pentru a folosi Agg in loc de GUI in Matplotlib
plt.switch_backend('Agg')

# Coada pentru mesaje de avertizare
warning_queue = Queue()

# Creare tabele in baza de date SQLite
def create_table():
    # Tabel pentru utilizatori
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL
        )
    ''')
    connection.commit()
    connection.close()

    # Tabel pentru cheltuieli
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            amount REAL,
            date TEXT,
            description TEXT NOT NULL,
            category_name TEXT NOT NULL
        )
    ''')
    connection.commit()
    connection.close()

    # Tabel pentru bugete pe categorii de cheltuieli
    connection = sqlite3.connect('budgets.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            category_name TEXT,
            budget_amount REAL,
            budget_threshold_percentage INTEGER           
        )
    ''')
    connection.commit()
    connection.close()

    # Tabel pentru categorii de cheltuieli
    connection = sqlite3.connect('categories.db')
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT,
            category_name TEXT UNIQUE NOT NULL           
        )
    ''')
    connection.commit()
    connection.close()

create_table()


# Functie pentru generare hash pentru o parola
def generate_hash(password):
    # Alegere algoritm de hash SHA-256
    hash_algorithm = hashlib.sha256()

    # Adaugare parola la obiectul de hash
    hash_algorithm.update(password.encode('utf-8'))

    # Obtinere hash rezultat
    password_hash = hash_algorithm.hexdigest()

    return password_hash

# Functie verificare daca o parola data corespunde unui hash dat
def check_password(password, hashed_password):
    hash_algorithm = hashlib.sha256()
    hash_algorithm.update(password.encode('utf-8'))
    return hash_algorithm.hexdigest() == hashed_password


# Verificarea mesajelor de avertizare si adaugarea lor in contextul corect
@app.before_request
def process_warnings():
    while not warning_queue.empty():
        flash(warning_queue.get(), 'warning')


# Stergere fisiere imagine PNG si JPG din folderul /static
def delete_image_files():
    # Afla directorul curent al app.py
    app_folder = os.getcwd()
    folder = app_folder + "\\static\\"
    
    # Creeaza cate un sablon pentru a gasi fisiere PNG respectiv JPG
    png_glob = os.path.join(folder, '*.png')
    jpg_glob = os.path.join(folder, '*.jpg')

    # Gaseste toate fisierele care corespund sabloanelor
    png_files = glob.glob(png_glob)
    jpg_files = glob.glob(jpg_glob)

    # Combina listele de fisiere
    images = png_files + jpg_files

    # Sterge fiecare fisier gasit
    for image in images:
        try:
            os.remove(image)
            flash('File {image} was deleted.', 'success')
        except Exception as e:
            flash('Error at delete file {image}: {e}')

# Creare si actualizare buget pentru o categorie de cheltuieli a utilizatorului curent
def update_budget(user_name, category_name, amount, threshold):
    connection = sqlite3.connect('budgets.db')
    cursor = connection.cursor()

    # Verifica daca exista deja un buget pentru categoria respectiva si utilizatorul dat
    cursor.execute('SELECT id FROM budgets WHERE user_name = ? AND category_name = ?', (user_name, category_name))
    budget_id = cursor.fetchone()

    if budget_id:
        # Actualizeaza bugetul existent, prin adaugare amount la valoarea existenta deja
        cursor.execute('UPDATE budgets SET budget_amount = budget_amount + ? , budget_threshold_percentage = ? WHERE id = ?', (amount, threshold, budget_id[0]))
    else:
        # Creeaza un nou buget daca nu exista 
        cursor.execute('INSERT INTO budgets (user_name, category_name, budget_amount, budget_threshold_percentage) VALUES (?, ?, ?, ?)', (user_name, category_name, amount, threshold))

    connection.commit()
    connection.close()

# Stergere buget pentru o categorie de cheltuieli a utilizatorului curent
def delete_budget(user_name, category_name):
    connection = sqlite3.connect('budgets.db')
    cursor = connection.cursor()
    cursor.execute('DELETE FROM budgets WHERE user_name = ? AND category_name = ?', (user_name, category_name))
    connection.commit()
    connection.close()

# Aflare use_name al utilizatorului curent
def find_user_name(user_id):
    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM users WHERE id=?', (user_id,))
    users = cursor.fetchone()
    if len(users):
        user_name = users[1]
    else:
        user_name = "None"
    connection.close()   

    return user_name


# Pregatire date pentru afisarea in diagrama cu bare 2D
def get_chart_data(user_name):
    
    conn = sqlite3.connect('categories.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM categories WHERE user_name = ? ORDER BY category_name', (user_name,))
    categories_data = cursor.fetchall()
    conn.close()
    
    conn = sqlite3.connect('budgets.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM budgets WHERE user_name = ? ORDER BY category_name', (user_name,))
    budgets_data = cursor.fetchall()
    conn.close()

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT category_name, SUM(amount) FROM expenses WHERE user_name = ? GROUP BY category_name ORDER BY category_name', (user_name,))
    expenses_data = cursor.fetchall()
    conn.close()

    data = {'categories': [], 'expenses': [], 'budgets': [], 'thresholds': []}

    for category_name in categories_data:
        data['categories'].append(category_name)
    
    for expense_amount in expenses_data:
        data['expenses'].append(expense_amount)

    for row in budgets_data:
        user_id, user_name, category_name, budget, threshold = row
        data['budgets'].append(budget)
        data['thresholds'].append(threshold*budget/100)

    return data

# Afisare diagrama 2D cu bare pentru cheltuieli
def create_category_chart(data, result_queue):
    categories = data['categories']
    expenses = data['expenses']
    budgets = data['budgets']
    thresholds = data['thresholds']

    bar_width = 0.2  # Latimea fiecarei bare

    if len(categories):
        indices = np.arange(len(categories))

        fig, ax = plt.subplots()

    
        for i, (budget, threshold, expense) in enumerate(zip(budgets, thresholds, expenses)):
            bars_budgets = ax.bar(i, float(budget), bar_width, label='Budget Value' if i == 0 else '', color='green')
            bars_thresholds = ax.bar(i + bar_width, float(threshold), bar_width, label='Threshold Value' if i == 0 else '', color='orange')
            bars_expenses = ax.bar(i + (2 * bar_width), float(expense[1]), bar_width, label='Total Expenses' if i == 0 else '', color='red')
            ax.text(i , budget + 5, str(budget), ha='center', va='bottom', rotation='horizontal')
            ax.text(i + bar_width, threshold + 5, str(threshold), ha='center', va='bottom', rotation='horizontal')
            ax.text(i + (2 * bar_width), expense[1] + 5, str(expense[1]), ha='center', va='bottom', rotation='horizontal')

        ax.set_xticks(indices)
        ax.set_xticklabels([category[2] for category in categories])
        ax.legend()
    
        users = [category[1] for category in categories]
        if len(users):
            user_name = users[0]
        else:
            user_name = "None"
    
        # Salvare grafic într-un fișier de imagine PNG
        image_name = "chart_image_" + user_name + ".png"
        # am adaugat "static/" in cale pentru a stoca in directorul static
        image_path = "static/" + image_name  
        plt.savefig(image_path)

        # Inchidere ferestre Matplotlib
        plt.close(fig)
    else:    
        image_path = "static/images/money.jpg"
        warning_queue.put('Expense categories are missing. Please insert one!')

    # Pune imaginea în coada pentru a fi preluata in firul principal
    result_queue.put(image_path)

# Adauga valori pe barele din diagrama 2D
def add_values_on_bars(bars):
    for bar in bars:
        yval = bar.get_height()
        plt.text(bar.get_x() + bar.get_width()/2, yval, round(yval, 2), ha='center', va='bottom')

# Validare date de inceput si de sfarsit de interval calendaristic
def validate_date_range(start_date, end_date):
    try:
       if start_date is not None and end_date is not None:
        start_date = datetime.strptime(start_date, '%Y-%m-%d')
        end_date = datetime.strptime(end_date, '%Y-%m-%d')
        return start_date <= end_date
    except ValueError:
      return False

# Functii de management categorii de cheltuieli
# Aflare categorii de cheltuieli pentru utilizatorul curent
def get_expense_categories(user_name):
    connection = sqlite3.connect('categories.db')
    cursor = connection.cursor()

    cursor.execute('SELECT * FROM categories WHERE user_name = ? ORDER BY category_name', (user_name,))
    categories = cursor.fetchall()

    connection.close()
    return categories

# Adaugare o noua categorie de cheltuieli pentru utilizatorul curent
def add_expense_category(user_name, category_name):
    connection = sqlite3.connect('categories.db')
    cursor = connection.cursor()

    try:
        cursor.execute('INSERT INTO categories (user_name, category_name) VALUES (?, ?)', (user_name, category_name))
        connection.commit()
    except sqlite3.IntegrityError as e:
        flash('Category already existing!', 'error')

    connection.close()

    # Creaza o cheltuiala cu valoarea 0 in data curenta si salveaz-o in tabelul expenses
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    
    # Obtinere data curenta
    current_date = datetime.now()

    # Formatare data in formatul dorit
    formatted_date = current_date.strftime("%Y-%m-%d")
    cursor.execute('INSERT INTO expenses (user_name, amount, date , description, category_name) VALUES (?, ?, ?, ?, ?)', (user_name, 0.0, formatted_date, "***", category_name))
    connection.commit()
    connection.close()

# Stergere categorie de cheltuieli pentru utilizatorul curent
def delete_expense_category(category_name):
    connection = sqlite3.connect('categories.db')
    cursor = connection.cursor()
    cursor.execute('DELETE FROM categories WHERE category_name = ?', (category_name,))
    connection.commit()
    connection.close()

    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    cursor.execute('DELETE FROM expenses WHERE category_name = ?', (category_name,))
    connection.commit()
    connection.close()


# Verifica daca tabelul cu utilizatori este gol (Nu exista utilizatori inregistrati)
def is_table_empty(table_name):
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute(f'SELECT COUNT(*) FROM {table_name}')
    row_count = cursor.fetchone()[0]
    conn.close()

    return row_count == 0

# Adauga cheltuiala noua in tabelul de cheltuieli 
def add_expense(user_name, amount, date, description, category_name):
    # Calculeaza valoarea cheltuielilor anterioare din categoria aleasa a utilizatorului curent
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    cursor.execute('SELECT SUM(amount) FROM expenses WHERE user_name = ? AND category_name = ?', (user_name, category_name))
    old_expenses_amount = cursor.fetchone()[0]
    connection.commit()
    connection.close()

    # Obtine bugetul alocat pentru categoria curenta
    connection = sqlite3.connect('budgets.db')
    cursor = connection.cursor()
    cursor.execute('SELECT budget_amount, budget_threshold_percentage FROM budgets WHERE user_name = ? AND category_name = ?', (user_name, category_name))
    budgets = cursor.fetchone()
    budget_amount = budgets[0]
    budget_threshold = float(budgets[1]) * budget_amount / 100
    connection.commit()
    connection.close()

    # Converteste amount din str in float
    amount_float = float(amount)

    # Verifica daca cu suma cheltuielii se depaseste bugetul
    if ((old_expenses_amount + amount_float) > budget_amount):
        flash(f'Expense exceeds budget for {category_name}! Budget:{budget_amount}, Expense:{amount}', 'warning')
        return 0
    # Atentioneaza ca sunt cheltuieli excesive
    elif ((amount_float > (budget_amount*0.20))):
        flash(f'Expense is excesive for {category_name}! Budget:{budget_amount}, Expense:{amount}', 'info')
    # Atentioneaza ca ai depasit pragul de atentionare al bugetului alocat
    elif ((old_expenses_amount + amount_float) > budget_threshold):
        flash(f'Expenses exceed threshold level for {category_name}! Budget:{budget_amount}, Budget_Threshold:{budget_threshold}, Expense: {amount}', 'info')

    
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    
    # Convertirea string-ului in obiect datetime
    date_datetime = datetime.strptime(date, '%Y-%m-%d')

    # Formatarea obiectului datetime
    formatted_date = date_datetime.strftime('%Y-%m-%d')
    
    cursor.execute('INSERT INTO expenses (user_name, amount, date, description, category_name) VALUES (?, ?, ?, ?, ?)',
                   (user_name, amount, formatted_date, description, category_name))

    connection.commit()
    connection.close()
    return 1

# Rutele pentru aplicatie
# Ruta pentru pagina de inceput (index)
@app.route('/')
def index():
    # Obtinerea si golirea mesajelor flash
    messages = get_flashed_messages()
    return render_template('index.html', messages=messages)


# Ruta pentru pagina de logare
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' not in session:
        session['user_id'] = None

    if is_table_empty('users'):
        flash('No users registered!. Please register first!', 'error')
        return redirect(url_for('register'))

    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        connection = sqlite3.connect('users.db')
        cursor = connection.cursor()
        cursor.execute('SELECT * FROM users WHERE email=?', (email,))
        user = cursor.fetchone()

        if user and check_password(password, user[2]):
            session['user_id'] = user[0]
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
        connection.close()

    return render_template('login.html')


# Ruta pentru pagina de inregistrare utilizator nou
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' not in session:
        session['user_id'] = None

    if request.method == 'POST':
        name = request.form['name'] 
        email = request.form['email']
        password = request.form['password']

        connection = sqlite3.connect('users.db')
        cursor = connection.cursor()
        try:
            password_hash = generate_hash(password)
            cursor.execute('INSERT INTO users (user_name, password, email) VALUES (?, ?, ?)', (name, password_hash, email))
            connection.commit()
            connection.close()
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError as e:
            flash('User name OR e-mail address already registered. Please change!', 'error')
        connection.close()

    return render_template('register.html')
    
# Ruta pentru pagina de selectare a operatiunilor asupra cheltuielilor
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_name = find_user_name(user_id)
    
    # Obtine datele pentru diagrame
    data = get_chart_data(user_name)

    # Creeaza coada pentru a comunica intre fire
    result_queue = Queue()

    # Creeaza firul pentru afisarea graficului si furnizează coada ca argument
    chart_thread = threading.Thread(target=create_category_chart, args=(data, result_queue))

    # Pornirea firului
    chart_thread.start()

    # Asteaptă ca firul sa se termine
    chart_thread.join()

    # Obtine rezultatul (calea catre fisierul de imagine) din coada
    image_path = result_queue.get()

    return render_template('dashboard.html', bar_chart_image=image_path)


# Ruta pentru categorii de cheltuieli
@app.route('/categories')
def categories():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    user_name = find_user_name(user_id)

    categories = get_expense_categories(user_name)  
    return render_template('categories.html', categories=categories)

# Adaugare categorie de cheltuieli in ruta pentru categorii de cheltuieli
@app.route('/add_category', methods=['POST'])
def add_category():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    user_name = find_user_name(user_id)

    category_name = request.form.get('category_name')
    budget = request.form.get('budget')
    budget_threshold = request.form.get('budget_threshold_percentage')
    if category_name:
        add_expense_category(user_name, category_name)  
        # Adaugarea bugetului in tabela budgets
        update_budget(user_name, category_name, budget, budget_threshold)

        flash('Category added/modified successfully!')
    else:
        flash('Category name cannot be empty', 'error')

    return redirect(url_for('categories'))

# Stergere categorie de cheltuieli in ruta pentru categorii de cheltuieli
@app.route('/delete_category/<category_name>')
def delete_category(category_name):
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_name = find_user_name(user_id)

    # Verific ca la categoria de cheltuieli nu exista cheltuieli pentru a o putea sterge
    connection = sqlite3.connect('database.db')
    cursor = connection.cursor()
    cursor.execute('SELECT category_name, SUM(amount) FROM expenses WHERE user_name=? AND category_name=?', (user_name, category_name))
    expense_value = cursor.fetchone()
    connection.close()
    
    if expense_value[1] == 0:
        delete_expense_category(category_name)
        delete_budget(user_name, category_name)
        flash('Category ' + category_name + ' deleted successfully!')
    else:
        flash('Category ' + category_name + ' has expenses and can not be deleted!')

    return redirect(url_for('categories'))

# Ruta pentru pagina de adaugare de noi cheltuieli
@app.route('/expense_form', methods=['GET', 'POST'])
def expense_form():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_name = find_user_name(user_id)

    if request.method == 'POST':
        amount = request.form.get('amount')
        date = request.form.get('date')
        description = request.form.get('description')
        category_name = request.form.get('category')  
    
        # Adaugarea cheltuielii in baza de date
        if (add_expense(user_name, amount, date, description, category_name)):
            flash('Expense added successfully!')
            return redirect(url_for('dashboard'))
        else:
             flash('Expense not added!', 'warning')   

    # Obținerea categoriilor pentru a le afisa in formular
    categories = get_expense_categories(user_name)

    return render_template('expense_form.html', categories=categories)

# Ruta pentru pagina de rapoarte
@app.route('/reports', methods=['GET', 'POST'])
def reports():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))
 
    user_id = session['user_id']
    user_name = find_user_name(user_id)
 
    connection = sqlite3.connect('categories.db')
    cursor = connection.cursor()
    cursor.execute("SELECT category_name FROM categories WHERE user_name = ?", (user_name,))
    categories = [row[0] for row in cursor.fetchall()]
    connection.close()
    
    if request.method == 'POST':
        selected_categories = request.form.getlist('categories')
        
        # Verifica ca s-a selectat macar o categorie de cheltuieli
        if len(selected_categories) == 0:
            flash('Please select minimum one category. Please try again.', 'error')
            return redirect(url_for('reports')) 
        
        # Verificare corectitudine interval de timp: start_date anterior end_date
        start_date = request.form['start_date']
        end_date = request.form['end_date']

        if not validate_date_range(start_date, end_date):
            flash('Invalid date range. Please try again.', 'error')
            return redirect(url_for('reports'))

        # Construim o interogare SQL pentru a obtine cheltuielile doar pentru categoriile selectate
        query = "SELECT * FROM expenses WHERE user_name=? AND amount>0 AND date BETWEEN ? AND ?"
        params = [user_name, start_date, end_date]

        if selected_categories:
            placeholders = ','.join(['?'] * len(selected_categories))
            query += f" AND category_name IN ({placeholders})"
            params.extend(selected_categories)

        # Executare interogare si obtinere rezultate
        connection = sqlite3.connect('database.db')
        cursor = connection.cursor()
        cursor.execute(query, params)
        expenses = cursor.fetchall()
        connection.close()
        
        return render_template('reports.html', categories= categories, expenses=expenses, start_date=start_date, end_date=end_date)
        
    return render_template('reports.html', categories= categories, expenses=[])

# Ruta pentru pagina de export in formmat csv a datelor din baza de date
@app.route('/export_csv', methods=['GET', 'POST'])
def export_csv():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        start_date = request.form['start_date']
        end_date = request.form['end_date']
    
        if not validate_date_range(start_date, end_date):
           flash('Invalid date range. Please try again.', 'error')
           return redirect(url_for('export_csv'))

        user_id = session['user_id']
        user_name = find_user_name(user_id)

        connection = sqlite3.connect('database.db')
        cursor = connection.cursor()
           
        # Selecteaza cheltuielile pentru intervalul specificat
        cursor.execute('SELECT user_name, amount, date, description, category_name FROM expenses WHERE user_name=? AND amount>0 AND date BETWEEN ? AND ? ORDER BY date', (user_name, start_date, end_date))
        expenses = cursor.fetchall()
    
        connection.close()

        # Obtine directorul curent
        current_directory = os.getcwd()

        # Stabileste numele fisierului CSV  
        csv_file_name = "report_"+ user_name + "_" + start_date + "_" + end_date + ".csv"
        # Construieste calea la un fisier in directorul curent
        csv_file_path = os.path.join(current_directory, csv_file_name)

        # Creaza un fisier CSV in memoria temporara
        csv_data = [['User', 'Amount', 'Date', 'Description', 'Category']]

        for expense in expenses:
            # Expense[2] reprezinta data in formatul 'YYYY-MM-DD'
            date_str = expense[2]
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            formatted_date = date_obj.strftime('%Y-%m-%d')

            # Creează o nouă tupla cu datele formatate
            formatted_expense = tuple(expense[:2]) + (formatted_date,) + tuple(expense[3:])

            # Adaugă linia în csv_data
            csv_data.append(formatted_expense)
        
        with open(csv_file_path, 'w', newline='') as csv_file:
             csv_writer = csv.writer(csv_file)
             csv_writer.writerows(csv_data)

        # Trimite fisierul catre utilizator pentru a-l descarca
        return send_file(csv_file_path, as_attachment=True, download_name=csv_file_name)  
    return render_template('export_csv.html', expenses=[])


# Ruta pentru pagina de import in format csv a datelor in baza de date
@app.route('/import_csv', methods=['GET', 'POST'])
def import_csv():
    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    user_name = find_user_name(user_id)
    
    if request.method == 'POST':
        try:
            csv_file = request.files['csv_file']

            if csv_file.filename == '':
                flash('No file selected', 'error')
                return redirect(url_for('import_csv'))

                
            if csv_file and csv_file.filename.endswith('.csv'):
                # Citirea datelor din fisierul CSV
                # Deschiderea fișierului CSV în modul text
                csv_data = csv.reader(csv_file.stream.read().decode('utf-8').splitlines())
                                
                # Deschiderea conexiunii la baza de date
                connection = sqlite3.connect('database.db')
                cursor = connection.cursor()
                
                for row in csv_data:
                    user_name, amount, date, description, category_name = row
                    date_str = row[2]
                    #date = datetime.strptime(date_str, '%Y-%m-%d')
                    date = date_str
                    # Adaugarea datelor in baza de date
                    if (add_expense(user_name, amount, date, description, category_name) == 0):
                        flash('Expense not imported for {category_name}. Exceed budget!', 'warning')
                connection.commit()
                connection.close()

                flash('CSV file imported successfully!')
                return redirect(url_for('import_csv'))

            else:
                flash('Invalid file format. Please select a CSV file.', 'error')
                return redirect(url_for('import_csv'))

        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            return redirect(url_for('import_csv'))

    return render_template('import_csv.html')

# Ruta pentru pagina de setari
@app.route('/settings', methods=['GET', 'POST'])
def settings():

    if 'user_id' not in session:
        flash('Please log in first', 'error')
        return redirect(url_for('login'))

    # Preia vechile valori din baza de date
    user_id = session['user_id']
    user_name = find_user_name(user_id)

    connection = sqlite3.connect('users.db')
    cursor = connection.cursor()
    cursor.execute('SELECT * FROM users WHERE user_name=? ', (user_name,))
    user_data = cursor.fetchone()
    old_email = user_data[3]
    connection.close()

    if request.method == 'POST':
        # Acceseaza valorile din formular
        email = request.form['email']
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_new_password = request.form['confirm_new_password']

        # Verifica parola noua cu cea confirmata 
        if new_password != confirm_new_password:
            flash('New password is missmatched', 'error')
            return redirect(url_for('settings'))

        connection = sqlite3.connect('users.db')
        cursor = connection.cursor()

        cursor.execute('SELECT * FROM users WHERE user_name=? ', (user_name,))
        existing_password = cursor.fetchone()[2]

        # Verifica parola curenta 
        current_password_hash = generate_hash(current_password)
        if  check_password(current_password_hash, existing_password):  
            flash('Current password is incorrect', 'error')
            return redirect(url_for('settings'))

        # Actualizeaza setarile in baza de date
        password_hash = generate_hash(new_password) 
        cursor.execute('UPDATE users SET email = ?, password = ? WHERE user_name = ?', (email, password_hash, user_name))

        connection.commit()
        connection.close()

        flash('Settings saved successfully', 'success')
        return redirect(url_for('settings'))

    return render_template('settings.html', old_email=old_email)


# Ruta pentru pagina de delogare
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    delete_image_files()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True) 
