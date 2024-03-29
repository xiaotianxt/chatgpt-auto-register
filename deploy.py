# %%
from dotenv import load_dotenv
from os import getenv
from sys import argv
import re
import poplib
import logging
import time

load_dotenv()
ITS_ID = getenv("ITS_ID")
ITS_PASSWORD = getenv("ITS_PASSWORD")
WAIT_SECONDS = getenv("WAIT_SECONDS") or 15
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = getenv(
    "LOG_FORMAT", "%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d - %(message)s"
)
LOG_LEVEL = getattr(logging, LOG_LEVEL.upper(), logging.INFO)

assert all([ITS_ID, ITS_PASSWORD, WAIT_SECONDS]), "Environment variables not set"


# 设置基本的日志配置
logging.basicConfig(
    level=LOG_LEVEL,
    format=LOG_FORMAT,
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
POP3_SERVER = "pop3.stu.pku.edu.cn"
SMTP_SERVER = "smtp.stu.pku.edu.cn"
POP3_PORT = 995  # SSL port
SMTP_PORT = 25  # No SSL

EMAIL = ITS_ID + "@stu.pku.edu.cn"
PASSWORD = ITS_PASSWORD

very_last_checked_id = 0


def extract_links(text):
    # 修改正则表达式以匹配以 http 或 https 开头的链接
    regex = r"http[s]?://\S+"
    links = re.findall(regex, text)
    # 去除可能的尾随符号，如逗号、句号、引号等
    links = [url.rstrip(",.>\"'") for url in links]
    return links


def check_new_email(pop3_server, pop3_port, user_email, password, recent_min=2):
    """Check if there is a new email in the inbox."""
    global very_last_checked_id
    logger.debug("Checking for new emails...")
    new_emails = []
    pop = poplib.POP3_SSL(pop3_server, pop3_port)
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
            decoded_header = decode_header(msg["Subject"])
            logger.info(
                "Checking mail: "
                + (
                    decoded_header[0][0].decode(decoded_header[0][1])
                    if decoded_header[0][1]
                    else decoded_header[0][0]
                )
            )

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
            logger.debug("No new emails found.")
        return new_emails

    except Exception as e:
        logger.error(f"Failed to check for new emails: {e}", exc_info=True)
        return []


def forward_email(user_email, password, emails, force=False):
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

        if not force and (
            not original_to.endswith("@xiaotian.dev")
            or original_from != "noreply@tm.openai.com"
            or original_subject != "OpenAI - Verify your email"
        ):
            logger.info(
                f"[Ignore] {original_from} -> {original_to}: {original_subject}"
            )
            continue

        real_to = original_to.replace("@xiaotian.dev", "@stu.pku.edu.cn")
        if not force and real_to.startswith(user_email):
            continue

        logger.info(
            f"[Forwarding] {original_from} -> {original_to}: {original_subject}"
        )

        msg = MIMEMultipart()
        msg["From"] = email["From"]
        msg["To"] = email["To"]
        msg["Subject"] = email["Subject"]

        # 确保包含原始邮件的正文和附件
        if email.is_multipart():
            for part in email.get_payload():
                # 如果是 html 提取链接
                if part.get_content_type() == "text/html":
                    try:
                        content = part.get_payload(decode=True)
                        charset = part.get_content_charset()
                        if charset:
                            content = content.decode(charset)
                        urls = extract_links(content)
                        logger.info(f"{email['To']} -> {urls[1]}")
                    except Exception as e:
                        logger.error(f"Error on analyzing: {e}", exc_info=True)
                msg.attach(part)
        else:
            # 对于非多部分邮件，只需附加原始正文
            msg.attach(MIMEText(email.get_payload()))

        real_send(real_to, msg, user_email, password)
        logger.info("Email forwarded.")


def real_send(real_to, msg, user_email, password):
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.login(user_email, password)
        text = msg.as_string()
        server.sendmail(user_email, real_to, text)
        server.quit()
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"Failed to forward email to {real_to}, {type(e)}: {e}")
        logger.info(f"Try to use pku.edu.cn instead of stu.pku.edu.cn")
        if real_to.endswith("@stu.pku.edu.cn"):
            real_to = real_to.replace("@stu.pku.edu.cn", "@pku.edu.cn")
            real_send(real_to, msg, user_email, password)
    except Exception as e:
        logger.error(
            f"Failed to forward email to {real_to}, {type(e)}: {e}", exc_info=True
        )


# Main loop
while True:
    try:
        recent_min = int(argv[1]) if len(argv) > 1 else 2
        logger.debug("Checking for new emails...")
        new_emails = check_new_email(
            POP3_SERVER, POP3_PORT, EMAIL, PASSWORD, recent_min=recent_min
        )
        forward_email(EMAIL, PASSWORD, new_emails)
        logger.debug("Waiting for the next check...")
        time.sleep(WAIT_SECONDS)  # Check Every 15 Seconds
    except Exception as e:
        logger.error("Major Error", exc_info=True)
