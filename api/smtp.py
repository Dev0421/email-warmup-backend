import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time

class EmailManager:
    def __init__(self, smtp_server, smtp_port, imap_server, imap_port, username, password):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.imap_server = imap_server
        self.imap_port = imap_port
        self.username = username
        self.password = password
        self.smtp_conn = None
        self.imap_conn = None

    def connect_smtp(self):
        """Connect to the SMTP server."""
        try:
            if self.smtp_port == 465:
                self.smtp_conn = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port)
                self.smtp_conn.login(self.username, self.password)
            else:
                self.smtp_conn = smtplib.SMTP(self.smtp_server, 587)
                self.smtp_conn.starttls()  
                self.smtp_conn.login(self.username, self.password)
            print("Connected to SMTP server.")
        except Exception as e:
            print(f"Failed to connect to SMTP server: {e}")
            print("SMTP_CONN", self.smtp_conn.select)

    def connect_imap(self):
        """Connect to the IMAP server."""
        try:
            self.imap_conn = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            self.imap_conn.login(self.username, self.password)
            print("Connected to IMAP server.")
        except Exception as e:
            print(f"Failed to connect to IMAP server: {e}")
            print("IMAP_CONN", self.imap_conn.select)

    def disconnect(self):
        """Disconnect from SMTP and IMAP servers."""
        if self.smtp_conn:
            self.smtp_conn.quit()
            print("Disconnected from SMTP server.")
        if self.imap_conn:
            self.imap_conn.logout()
            print("Disconnected from IMAP server.")

    def send_email(self, recipient, subject, body):
        """Send an email."""
        try:
            message = MIMEMultipart()
            message['From'] = self.username  # Ensure this matches the sender account
            message['To'] = recipient
            message['Subject'] = subject
            message.attach(MIMEText(body, 'plain'))
            self.smtp_conn.sendmail(self.username, recipient, message.as_string())
            print(f"Email sent successfully to {recipient}.")
        except Exception as e:
            print(f"Failed to send email: {e}")

    def delete_email(self, email_id):
        """Delete an email by its ID."""
        try:
            self.imap_conn.select("INBOX")
            self.imap_conn.store(email_id, '+FLAGS', '\\Deleted')
            self.imap_conn.expunge()
            print(f"Email with ID {email_id} deleted.")
        except Exception as e:
            print(f"Failed to delete email: {e}")

    def mark_as_not_spam(self, email_id):
        """Move an email from the spam folder to the inbox."""
        try:
            self.imap_conn.select('Spam') 
            result = self.imap_conn.copy(email_id, 'INBOX')
            if result[0] == 'OK':
                self.imap_conn.store(email_id, '+FLAGS', '\\Deleted')
                self.imap_conn.expunge()
                print(f"Email with ID {email_id} marked as not spam and moved to Inbox.")
            else:
                print("Failed to mark email as not spam.")
        except Exception as e:
            print(f"Failed to mark email as not spam: {e}")

    def list_emails(self, folder="INBOX"):
        """List emails in a specific folder."""
        try:
            self.imap_conn.select(folder)  # Ensure folder is selected
            status, data = self.imap_conn.search(None, "ALL")
            if status == 'OK':
                email_ids = data[0].split()
                print(f"Emails in {folder}: {email_ids}")
                return email_ids
            else:
                print(f"Failed to fetch emails from {folder}.")
                return []
        except Exception as e:
            print(f"Failed to list emails: {e}")
            return []
if __name__ == "__main__":
    # Email account configuration
    smtp_server = "mail.cloudstacknetwork.net"
    smtp_port = 465
    imap_server = "mail.cloudstacknetwork.net"
    imap_port = 993
    username = "bill.test1@cloudstacknetwork.net"
    password = "!jVy*jC49XZ!*25@"

    # Initialize EmailManager
    email_manager = EmailManager(smtp_server, smtp_port, imap_server, imap_port, username, password)

    # Connect to SMTP and IMAP servers
    email_manager.connect_smtp()
    email_manager.connect_imap()
    print (email_manager.imap_conn.list())
    # Send an email
    email_manager.send_email("digitaldream0719@gmail.com", "Test Subject", "This is a test email.")

    # List emails in the inbox
    inbox_emails = email_manager.list_emails("INBOX")

    # # Delete the first email (if any)
    if inbox_emails:
        email_manager.delete_email(inbox_emails[0])

    # List emails in the spam folder and mark the first one as not spam
    spam_emails = email_manager.list_emails("Spam")
    if spam_emails:
        email_manager.mark_as_not_spam(spam_emails[0])

    # Disconnect from servers
    email_manager.disconnect()