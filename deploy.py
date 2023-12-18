# %%
from dotenv import load_dotenv
from os import getenv

load_dotenv()
ITS_ID = getenv("ITS_ID")
ITS_PASSWORD = getenv("ITS_PASSWORD")
WAIT_SECONDS = getenv("WAIT_SECONDS") or 15

assert all([ITS_ID, ITS_PASSWORD, WAIT_SECONDS]), "Environment variables not set"

import poplib
import ssl
import logging
import time

# 设置基本的日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

import smtplib
from email import message_from_bytes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import decode_header
from email.utils import parseaddr, parsedate_tz, mktime_tz

# Configuration settings
POP3_SERVER = "pop3.pku.edu.cn"
SMTP_SERVER = "smtp.pku.edu.cn"
POP3_PORT = 995  # SSL port
SMTP_PORT = 25  # No SSL

EMAIL = ITS_ID + "@pku.edu.cn"
PASSWORD = ITS_PASSWORD

very_last_checked_id = 0


# %%
def create_ssl_context():
    """创建一个配置为 TLSv1.2 和 AES128-SHA 的 SSL 上下文"""
    context = ssl.create_default_context()
    context.options &= ~ssl.OP_NO_TLSv1_2  # 确保启用 TLSv1.2
    context.set_ciphers("AES128-SHA")  # 尝试指定 AES128-SHA 加密套件
    return context


def check_new_email(pop3_server, pop3_port, user_email, password, recent_min=1):
    """Check if there is a new email in the inbox."""
    global very_last_checked_id
    logger.info("Checking for new emails...")
    new_emails = []
    pop = poplib.POP3_SSL(pop3_server, pop3_port, context=create_ssl_context())
    try:
        # Log in to the server
        pop.user(user_email)
        pop.pass_(password)

        # Get the list of mail messages
        mail_ids = list(reversed(pop.list()[1]))
        for mail_id in mail_ids:
            if int(mail_id.split()[0]) <= very_last_checked_id:
                break
            # Get the email
            raw_email = b"\n".join(pop.retr(int(mail_id.split()[0]))[1])

            # Parse the email content
            msg = message_from_bytes(raw_email)
            date_tuple = parsedate_tz(msg["Date"])
            if date_tuple:
                local_date = mktime_tz(date_tuple)
                if (time.time() - local_date) / 60 <= recent_min:
                    new_emails.append(msg)
                else:
                    logger.info(f"Break on {msg['Date']}")
                    break
        very_last_checked_id = max(int(mail_ids[0].split()[0]), very_last_checked_id)

        if new_emails:
            logger.info(f"{len(new_emails)} new email(s) found!")
        else:
            logger.info("No new emails found.")
        return new_emails

    except Exception as e:
        logger.error(f"Failed to check for new emails: {e}")
        return []


def forward_email(user_email, password, to_email, emails):
    """Forward an email to another email address."""
    for email in emails:
        original_from = parseaddr(email["From"])[1]
        original_to = parseaddr(email["To"])[1]
        # Decode the subject
        decoded_header = decode_header(email["Subject"])
        original_subject = (
            decoded_header[0][0].decode(decoded_header[0][1])
            if decoded_header[0][1]
            else decoded_header[0][0]
        )

        if (
            not original_to.endswith("@xiaotian.dev")
            or original_from != "noreply@tm.openai.com"
            or original_subject != "OpenAI - Verify your email"
        ):
            logger.info(
                f"[Ignore] {original_from} -> {original_to}: {original_subject}"
            )
            continue

        real_to = original_to.replace("@xiaotian.dev", "@pku.edu.cn")
        if real_to.startswith(user_email):
            continue

        logger.info(
            f"[Forwarding] {original_from} -> {original_to}: {original_subject}"
        )

        msg = MIMEMultipart()
        msg["From"] = email["From"]
        msg["To"] = email["To"]
        msg["Subject"] = email["Subject"]

        if email.is_multipart():
            for part in email.get_payload():
                content_type = part.get_content_type()
                if content_type == "text/html":
                    msg.attach(MIMEText(part.get_payload(), "html"))
        else:
            msg.attach(MIMEText(email.get_payload(), "plain"))

        try:
            server = smtplib.SMTP("smtp.pku.edu.cn", 25)
            server.login(user_email, password)
            text = msg.as_string()
            server.sendmail(user_email, real_to, text)
            server.quit()
            logger.info("Email forwarded.")
        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Failed to forward email to {real_to}: {e}")
        except Exception as e:
            logger.error(f"Failed to forward email to {real_to}: {e}")


# Main loop
while True:
    logger.debug("Checking for new emails...")
    new_emails = check_new_email(POP3_SERVER, POP3_PORT, EMAIL, PASSWORD)
    if new_emails:
        forward_email(EMAIL, PASSWORD, "tianyp@pku.edu.cn", new_emails)
    logger.debug("Waiting for the next check...")
    time.sleep(WAIT_SECONDS)  # Check Every 15 Seconds
