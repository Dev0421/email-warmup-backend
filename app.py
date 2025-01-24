from flask import Flask, jsonify, request
from flask_cors import CORS
from email_warmup import EmailAccount, DatabaseManager, ReputationMonitor, EmailWarmer
import sqlite3
import pandas as pd
import re
import time
import smtplib
from threading import Thread # To send emails in the background
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# from templates import Template
# from templates_routes import templates_bp

app = Flask(__name__)
CORS(app)

def is_valid_email(email):
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email) is not None

db_manager = DatabaseManager()
def send_email_gmail(sender_email, receiver_email, subject, body, app_password):
    message = MIMEMultipart()
    message['From'] = sender_email
    message['To'] = receiver_email
    message['Subject'] = subject
    message.attach(MIMEText(body, 'html'))
    try:
        # Send the email via SMTP
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, message.as_string())
        
        # Update the sent count in the database
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT sent FROM accounts WHERE email = ?''', (sender_email,))
            existing_account = cursor.fetchone()

            if existing_account:
                sent_count = existing_account[0] if existing_account[0] is not None else 0
                cursor.execute('''
                    UPDATE accounts 
                    SET sent = ? 
                    WHERE email = ?
                ''', (sent_count + 1, sender_email))
                conn.commit()
            else:
                # Handle the case where the account is not found
                cursor.execute('''
                    INSERT INTO accounts (email, sent) 
                    VALUES (?, ?)
                ''', (sender_email, 1))
                conn.commit()

        # Fetch updated account data
        with sqlite3.connect(db_manager.db_name) as conn:
            accounts = pd.read_sql_query("SELECT * FROM accounts", conn)
        accounts_dict = accounts.to_dict(orient='records')

        # Return the accounts data as JSON
        return jsonify(accounts_dict)

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": str(e)})

    # Print success message after sending the email
    print("Email sent successfully! From:", sender_email, "To:", receiver_email)

@app.route('/api/accounts', methods=['GET'])
def get_items():
    with sqlite3.connect(db_manager.db_name) as conn:
        accounts = pd.read_sql_query("""
            SELECT * 
            FROM accounts
        """, conn)
    accounts_dict = accounts.to_dict(orient='records')
    print(accounts_dict)
    return jsonify(accounts_dict)

@app.route('/api/account/getone/<int:id>', methods=['GET'])
def get_account_by_email(id):
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            query = """
                SELECT * 
                FROM accounts
                WHERE id = ?
            """
            accounts = pd.read_sql_query(query, conn, params=(id,))
            
            if not accounts.empty:
                accounts_dict = accounts.to_dict(orient='records')
                return jsonify(accounts_dict[0]), 200
            else:
                return jsonify({'message': 'Account not found'}), 404
                
    except sqlite3.Error as db_error:
        print(f"Database error: {db_error}")
        return jsonify({'message': 'Database error occurred'}), 500
        
    except Exception as e:
        print(f"Unexpected error: {e}")
        return jsonify({'message': 'Internal server error'}), 500

@app.route('/api/account/create/smtp', methods=['POST'])
def create_smtp_one():
    account_data = request.get_json()
    required_fields = ['email', 'password', 'provider', 'provider_name', 'imap_server', 'smtp_server', 'imap_port', 'smtp_port', 'warmup_style']
    
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT email FROM accounts WHERE email = ?''', (account_data['email'],))
            existing_account = cursor.fetchone()
            if existing_account:
                return {"error": "Account with this email already exists"}, 400  
            cursor.execute('''SELECT id FROM providers WHERE smtp_server = ?''', (account_data['smtp_server'],))
            existing_provider = cursor.fetchone()
            if existing_provider:
                account_data['provider'] = existing_provider[0]
            else:
                cursor.execute('''
                    INSERT INTO providers (smtp_server, imap_server, provider_name, smtp_port, imap_port)
                    VALUES (?, ?, ?, ?, ?)
                ''', (account_data['smtp_server'], account_data['imap_server'], account_data['provider_name'], account_data['smtp_port'], account_data['imap_port']))
                account_data['provider'] = cursor.lastrowid 
                print("New provider has been created!")
            account_data['daily_limit'] = account_data.get('daily_limit', 100)
            account_data['status'] = account_data.get('status', 0) 
            cursor.execute('''
                INSERT INTO accounts (email, password, provider, daily_limit, warmup_style, created_at, updated_at, status) 
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)
            ''', (
                account_data['email'], 
                account_data['password'], 
                account_data['provider'], 
                account_data['daily_limit'],
                account_data['warmup_style'],
                account_data['status']
            ))
            conn.commit()
        print("New account has been created!")
        with sqlite3.connect(db_manager.db_name) as conn:
            accounts = pd.read_sql_query("SELECT * FROM accounts", conn)
        accounts_dict = accounts.to_dict(orient='records')
        return jsonify(accounts_dict)
        
    except sqlite3.Error as e:
        print("Database error:", e)
        return {"error": "Database error"}, 500

@app.route('/api/account/create', methods=['POST'])
def create_one():
    account_data = request.get_json()
    required_fields = ['email', 'password', 'provider', 'imap_server', 'smtp_server', 'imap_port', 'smtp_port', 'app_password', 'warmup_stage', 'sent', 'received']
    print (required_fields)
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT email FROM accounts WHERE email = ?''', (account_data['email'],))
            existing_account = cursor.fetchone()
            if existing_account:
                return {"error": "Account with this email already exists"}, 400
            
            # Insert the new account data
            cursor.execute(''' 
                INSERT INTO accounts (email, password, provider, imap_server, smtp_server, imap_port, smtp_port, app_password, warmup_stage, status, sent, received) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
            ''', (
                account_data['email'], 
                account_data['password'], 
                account_data['provider'], 
                account_data['imap_server'], 
                account_data['smtp_server'], 
                account_data['imap_port'], 
                account_data['smtp_port'], 
                account_data['appword'], 
                account_data['warmup_stage'],
                0
            ))

            # Commit changes to the database
            conn.commit()

        with sqlite3.connect(db_manager.db_name) as conn:
            accounts = pd.read_sql_query("""
                SELECT * 
                FROM accounts
            """, conn)
        accounts_dict = accounts.to_dict(orient='records')
        return jsonify(accounts_dict)

    except sqlite3.Error as e:
        print("Database error:", e)
        return {"error": "Database error"}, 500
    
@app.route('/api/account/delete/<int:id>', methods=['GET'])
def delete_one(id):
    try:
        if not id:
            return jsonify({'message': 'id is required'}), 400
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()

            # Delete the account with the given email
            cursor.execute("DELETE FROM accounts WHERE id = ?", (id,))
            conn.commit()

            # Check if any record was deleted
            if cursor.rowcount > 0:
                with sqlite3.connect(db_manager.db_name) as conn:
                    accounts = pd.read_sql_query("""
                        SELECT * 
                        FROM accounts
                    """, conn)
                accounts_dict = accounts.to_dict(orient='records')
                return jsonify(accounts_dict)
            else:
                return jsonify({'message': 'Account not found'}), 404

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'message': 'Internal server error'}), 500
    
@app.route('/api/account/edit', methods=['POST'])
def edit_one():
    account_data = request.get_json()
    print(account_data)

    required_fields = ['email', 'password', 'provider', 'imap_server', 'smtp_server', 'imap_port', 'smtp_port', 'appword', 'warmup_stage', 'status']
    missing_fields = [field for field in required_fields if field not in account_data]

    if missing_fields:
        return {"error": f"Missing required fields: {', '.join(missing_fields)}"}, 400

    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE accounts 
                SET password = ?, 
                    provider = ?, 
                    imap_server = ?, 
                    smtp_server = ?, 
                    imap_port = ?, 
                    smtp_port = ?, 
                    app_password = ?, 
                    warmup_stage = ?, 
                    status = ?
                WHERE email = ?
            ''', (
                account_data['password'],
                account_data['provider'],
                account_data['imap_server'],
                account_data['smtp_server'],
                account_data['imap_port'],
                account_data['smtp_port'],
                account_data['appword'],
                account_data['warmup_stage'],
                account_data['status'],
                account_data['email']
            ))

            conn.commit()

        with sqlite3.connect(db_manager.db_name) as conn:
            accounts = pd.read_sql_query("""
                SELECT * 
                FROM accounts
            """, conn)
        accounts_dict = accounts.to_dict(orient='records')
        return jsonify(accounts_dict)

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return {"error": "Database error occurred. Please try again later."}, 500

    except Exception as e:
        print(f"Error: {e}")
        return {"error": "Internal server error. Please try again later."}, 500

@app.route('/api/account/warm', methods=['POST'])
def warm():
    # Get email data from the frontend
    email_json = request.get_json()
    sender_email = email_json['email']
    with sqlite3.connect(db_manager.db_name) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT status FROM accounts WHERE email = ?''', (sender_email,))
        account = cursor.fetchone()
        if account[0]:
            cursor.execute('''
                UPDATE accounts 
                SET status = ?
                WHERE email = ?
            ''', (0, sender_email ))
        else:
            cursor.execute('''
                UPDATE accounts 
                SET status = ?
                WHERE email = ?
            ''', (1, sender_email ))
    with sqlite3.connect(db_manager.db_name) as conn:
        accounts = pd.read_sql_query("""
            SELECT * 
            FROM accounts 
            WHERE status = 1
        """, conn)
    
    # Convert the data into a dictionary
    accounts_dict = accounts.to_dict(orient='records')
    sender_email = "digitaldream0719@gmail.com"
    # Get the list of receiver emails excluding the sender email
    receiver_emails = [account['email'] for account in accounts_dict if account['email'] != sender_email]
    print("sender", sender_email)
    print("receiver", receiver_emails)
    # Create a function to send emails between the accounts
    def send_emails_between_accounts():
        for receiver_email in receiver_emails:
            receiver = next(account for account in accounts_dict if account['status'] == 1)
            warmup_stage = receiver.get('warmup_stage', 1)  # Default to 1 if not found
            app_password = receiver.get('app_password', None)
            print(receiver)
            # Determine how many emails to send per minute
            emails_per_minute = warmup_stage * 10
            # Send the emails at the calculated frequency
            for _ in range(emails_per_minute):
                text = """TEMPLATE"""
                send_email_gmail(sender_email, receiver_email, 'Welcome Email', text, app_password)
                time.sleep(60 / emails_per_minute)
    email_thread = Thread(target=send_emails_between_accounts)
    email_thread.start()
    with sqlite3.connect(db_manager.db_name) as conn:
        accounts = pd.read_sql_query("""
            SELECT * 
            FROM accounts
        """, conn)
    accounts_dict = accounts.to_dict(orient='records')
    return jsonify(accounts_dict)


#=================Templates=============

@app.route('/api/templates', methods=['GET'])
def get_all_templates():
    with sqlite3.connect(db_manager.db_name) as conn:
        accounts = pd.read_sql_query("""
            SELECT * 
            FROM templates
        """, conn)
    accounts_dict = accounts.to_dict(orient='records')
    return jsonify(accounts_dict)

@app.route('/api/template/edit/<int:id>', methods=['POST'])
def edit_template(id):
    template_data = request.get_json()
    if not template_data:
        return jsonify({"error": "No data provided"}), 400
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE templates 
                SET subject = ?, 
                    content = ?, 
                    language = ? 
                WHERE id = ?
            ''', (
                template_data.get('subject'),
                template_data.get('content'),
                template_data.get('language'),
                id
            ))
            conn.commit()
        with sqlite3.connect(db_manager.db_name) as conn:
            templates = pd.read_sql_query("SELECT * FROM templates", conn)
        templates_dict = templates.to_dict(orient='records')
        return jsonify(templates_dict), 200
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return jsonify({"error": "Database error occurred. Please try again later."}), 500
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "Internal server error. Please try again later."}), 500
    
@app.route('/api/template/create', methods=['POST'])
def create_template():
    template_data = request.get_json()
    if not template_data or not all(key in template_data for key in ['subject', 'content', 'language']):
        return jsonify({"error": "Missing fields: subject, content, and language are required."}), 400
    try:
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT subject FROM templates WHERE subject = ?''', (template_data['subject'],))
            existing_template = cursor.fetchone()
            if existing_template:
                return jsonify({"error": "Template with this subject already exists."}), 400
            cursor.execute(''' 
                INSERT INTO templates (subject, content, language) 
                VALUES (?, ?, ?)
            ''', (
                template_data['subject'], 
                template_data['content'], 
                template_data['language']
            ))
            conn.commit()
        with sqlite3.connect(db_manager.db_name) as conn:
            accounts = pd.read_sql_query("SELECT * FROM templates", conn)
        accounts_dict = accounts.to_dict(orient='records')
        return jsonify(accounts_dict), 201 
    except sqlite3.Error as e:
        print("Database error:", e)
        return jsonify({"error": "Database error occurred. Please try again later."}), 500

    except Exception as e:
        print("Error:", e)
        return jsonify({"error": "Internal server error. Please try again later."}), 500
    
@app.route('/api/template/delete/<int:id>', methods=['POST'])
def delete_template(id):
    print(f"Deleting template with id: {id}")
    try:
        # Delete the template from the database
        with sqlite3.connect(db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM templates WHERE id = ?", (id,))
            conn.commit()

            # Check if the deletion was successful
            if cursor.rowcount == 0:
                return jsonify({"error": "Template not found."}), 404

        # Fetch remaining templates to return
        with sqlite3.connect(db_manager.db_name) as conn:
            templates = pd.read_sql_query("SELECT * FROM templates", conn)

        templates_dict = templates.to_dict(orient='records')
        return jsonify(templates_dict), 200

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return jsonify({"error": "Database error occurred. Please try again later."}), 500

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": "Internal server error. Please try again later."}), 500
if __name__ == '__main__':
    app.run(debug=False, port=5002)
    