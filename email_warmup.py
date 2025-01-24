import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import datetime
import random
import json
import logging
import time
from typing import Dict, List, Optional
import sqlite3
from dataclasses import dataclass
import threading
from queue import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='email_warmup.log'
)

logger = logging.getLogger(__name__)

@dataclass
class EmailAccount:
    email: str
    password: str
    provider: str
    imap_server: str
    smtp_server: str
    smtp_port: int
    daily_limit: int
    warmup_stage: int = 1

class DatabaseManager:
    def __init__(self, db_name: str = "email_warmup.db"):
        self.db_name = db_name
        self.init_database()

    def init_database(self):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    email TEXT PRIMARY KEY,
                    password TEXT,
                    provider TEXT,
                    imap_server TEXT,
                    smtp_server TEXT,
                    smtp_port INTEGER,
                    daily_limit INTEGER,
                    warmup_stage INTEGER
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metrics (
                    email TEXT,
                    date TEXT,
                    sent_count INTEGER,
                    received_count INTEGER,
                    spam_count INTEGER,
                    PRIMARY KEY (email, date)
                )
            ''')
            conn.commit()

    def add_account(self, account: EmailAccount):
        with sqlite3.connect(self.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO accounts 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                account.email, account.password, account.provider,
                account.imap_server, account.smtp_server, account.smtp_port,
                account.daily_limit, account.warmup_stage
            ))
            conn.commit()

class ReputationMonitor:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def update_metrics(self, email: str, sent: int, received: int, spam: int):
        today = datetime.date.today().isoformat()
        with sqlite3.connect(self.db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO metrics (email, date, sent_count, received_count, spam_count)
                VALUES (?, ?, ?, ?, ?)
            ''', (email, today, sent, received, spam))
            conn.commit()

    def get_reputation_score(self, email: str) -> float:
        with sqlite3.connect(self.db_manager.db_name) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT SUM(sent_count), SUM(spam_count) 
                FROM metrics 
                WHERE email = ?
            ''', (email,))
            total_sent, total_spam = cursor.fetchone()
            
            if not total_sent:
                return 100.0
            
            spam_rate = (total_spam or 0) / total_sent
            return max(0, 100 * (1 - spam_rate))

class EmailWarmer:
    def __init__(self, db_manager: DatabaseManager, reputation_monitor: ReputationMonitor):
        self.db_manager = db_manager
        self.reputation_monitor = reputation_monitor
        self.active_threads = {}
        self.stop_events = {}

    def generate_warmup_email(self) -> str:
        templates = [
            "Just checking in regarding our previous discussion.",
            "Hope you're having a great day! Quick update on our project.",
            "Following up on our conversation from last week.",
            "Wanted to touch base about our upcoming plans.",
            "Hi there! Here's the latest update on our progress.",
            "Touching base regarding the recent developments.",
            "Quick note about our ongoing collaboration.",
            "Checking in to see how things are progressing."
        ]
        return random.choice(templates)

    def send_email(self, account: EmailAccount, recipient: str):
        try:
            msg = MIMEMultipart()
            msg['From'] = account.email
            msg['To'] = recipient
            msg['Subject'] = f"Warmup Email - {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"
            
            body = self.generate_warmup_email()
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(account.smtp_server, account.smtp_port) as server:
                server.starttls()
                server.login(account.email, account.password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully from {account.email} to {recipient}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email from {account.email}: {str(e)}")
            return False

    def check_inbox(self, account: EmailAccount) -> Dict[str, int]:
        try:
            with imaplib.IMAP4_SSL(account.imap_server) as imap:
                imap.login(account.email, account.password)
                imap.select('INBOX')
                
                # Check total emails
                _, messages = imap.search(None, 'ALL')
                total = len(messages[0].split())
                
                # Check spam folder
                imap.select('[Gmail]/Spam')
                _, spam_messages = imap.search(None, 'ALL')
                spam = len(spam_messages[0].split())
                
                return {'total': total, 'spam': spam}
        except Exception as e:
            logger.error(f"Failed to check inbox for {account.email}: {str(e)}")
            return {'total': 0, 'spam': 0}

    def warmup_cycle(self, account: EmailAccount, stop_event: threading.Event):
        while not stop_event.is_set():
            try:
                daily_interactions = min(account.warmup_stage * 5, account.daily_limit)
                
                # Get list of other accounts to interact with
                with sqlite3.connect(self.db_manager.db_name) as conn:
                    cursor = conn.cursor()
                    cursor.execute('SELECT email FROM accounts WHERE email != ?', (account.email,))
                    other_accounts = [row[0] for row in cursor.fetchall()]

                if not other_accounts:
                    logger.warning(f"No other accounts available for warmup with {account.email}")
                    time.sleep(3600)  # Sleep for an hour before retrying
                    continue

                # Perform warmup activities
                for _ in range(daily_interactions):
                    if stop_event.is_set():
                        break
                        
                    recipient = random.choice(other_accounts)
                    if self.send_email(account, recipient):
                        # Check inbox and update metrics
                        inbox_stats = self.check_inbox(account)
                        self.reputation_monitor.update_metrics(
                            account.email,
                            1,  # Sent count
                            inbox_stats['total'],
                            inbox_stats['spam']
                        )
                    
                    # Random delay between emails (5-15 minutes)
                    time.sleep(random.randint(300, 900))

                # Increment warmup stage every 7 days
                if datetime.datetime.now().weekday() == 6:  # Sunday
                    account.warmup_stage += 1
                    self.db_manager.add_account(account)

            except Exception as e:
                logger.error(f"Error in warmup cycle for {account.email}: {str(e)}")
                time.sleep(3600)  # Sleep for an hour before retrying

    def start_warmup(self, account: EmailAccount):
        if account.email in self.active_threads:
            logger.warning(f"Warmup already active for {account.email}")
            return

        stop_event = threading.Event()
        self.stop_events[account.email] = stop_event
        
        thread = threading.Thread(
            target=self.warmup_cycle,
            args=(account, stop_event),
            daemon=True
        )
        self.active_threads[account.email] = thread
        thread.start()
        logger.info(f"Started warmup process for {account.email}")

    def stop_warmup(self, email: str):
        if email in self.stop_events:
            logger.info(f"Stopping warmup process for {email}")
            self.stop_events[email].set()
            if email in self.active_threads:
                self.active_threads[email].join(timeout=10)
                del self.active_threads[email]
            del self.stop_events[email]

def main():
    # Initialize components
    db_manager = DatabaseManager()
    reputation_monitor = ReputationMonitor(db_manager)
    warmer = EmailWarmer(db_manager, reputation_monitor)

    # Example usage
    test_account = EmailAccount(
        email="test@gmail.com",
        password="your_password",
        provider="Gmail",
        imap_server="imap.gmail.com",
        smtp_server="smtp.gmail.com",
        smtp_port=587,
        daily_limit=50
    )

    # Add account to database
    db_manager.add_account(test_account)

    # Start warmup process
    warmer.start_warmup(test_account)

    try:
        while True:
            # Main program loop
            time.sleep(60)
            # You could add API endpoints or UI integration here
    except KeyboardInterrupt:
        # Cleanup on exit
        for email in list(warmer.active_threads.keys()):
            warmer.stop_warmup(email)

if __name__ == "__main__":
    main()