from dotenv import load_dotenv
from os import getenv

load_dotenv()
ITS_ID = getenv("ITS_ID")
ITS_PASSWORD = getenv("ITS_PASSWORD")
PANDORA_URL = getenv("PANDORA_URL")

assert all([ITS_ID, ITS_PASSWORD, PANDORA_URL]), "Environment variables not set"

import imaplib
import email
from email.header import decode_header
import ssl
import logging
import re
import time

# 设置基本的日志配置
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CSS = By.CSS_SELECTOR

# Configuration settings
IMAP_SERVER = "imap.pku.edu.cn"
IMAP_PORT = 993  # SSL port
EMAIL = ITS_ID + "@pku.edu.cn"
PASSWORD = ITS_PASSWORD


def create_ssl_context():
    """创建一个配置为 TLSv1.2 和 AES128-SHA 的 SSL 上下文"""
    context = ssl.create_default_context()
    context.options &= ~ssl.OP_NO_TLSv1_2  # 确保启用 TLSv1.2
    context.set_ciphers("AES128-SHA")  # 尝试指定 AES128-SHA 加密套件
    return context


def extract_links(text):
    # 修改正则表达式以匹配以 http 或 https 开头的链接
    regex = r"http[s]?://\S+"
    links = re.findall(regex, text)
    # 去除可能的尾随符号，如逗号、句号、引号等
    links = [url.rstrip(",.>\"'") for url in links]
    return links


def read_first_email(imap_server, imap_port, user_email, password, recent_min=10):
    """Read the first email from the inbox using IMAP."""
    with imaplib.IMAP4_SSL(
        imap_server, imap_port, ssl_context=create_ssl_context()
    ) as imap:
        # Log in to the server
        imap.login(user_email, password)

        # Select the mailbox
        imap.select("inbox")

        # 搜索所有邮件，并找到最新的邮件编号
        status, data = imap.search(None, "ALL")
        if status != "OK":
            logger.error("未找到邮件！")
            return

        mail_ids = data[0].split()
        latest_email_id = mail_ids[-1]  # 最新邮件的编号

        # 获取最新邮件
        status, data = imap.fetch(latest_email_id, "(RFC822)")
        if status != "OK":
            logger.error("获取邮件失败")
            return

        # 解析邮件内容
        msg = email.message_from_bytes(data[0][1])
        subject = decode_header(msg["Subject"])[0][0]
        if isinstance(subject, bytes):
            subject = subject.decode()

        # 判断发送时间是否在规定时间内（默认 10 分钟）
        date_tuple = email.utils.parsedate_tz(msg["Date"])
        if date_tuple:
            local_date = email.utils.mktime_tz(date_tuple)
            logger.debug("最新邮件的发送时间: %s", time.ctime(local_date))
            if (time.time() - local_date) / 60 > recent_min:
                logger.error(f"最新邮件的发送时间超过 {recent_min} 分钟")
                return

        logger.debug("最新邮件的主题: %s", subject)
        if not subject.startswith("OpenAI"):
            return

        # 打印邮件内容
        logger.debug("邮件内容:")
        # first text msg
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                # 只查看网页部分
                continue

            elif content_type == "text/html":
                content = part.get_payload(decode=True)
                charset = part.get_content_charset()
                if charset:
                    content = content.decode(charset)
                urls = extract_links(content)

                logger.debug(f"提取的链接：{urls[1]}")  # hard code，第二条是 mandrillapp.com 的链接
                return urls[1]

        imap.close()


def get_browser():
    options = Options()
    options.page_load_strategy = "none"
    return webdriver.Chrome(options=options)


def read_register_account_info(filename="./accounts.csv"):
    with open(filename, "r") as f:
        for line in f.readlines():
            account, password = line.strip().split(",")
            yield account, password


accounts = list(read_register_account_info())

s = lambda selector: driver.find_element(CSS, selector)


def sleep(seconds=1):
    def wrapper(func):
        def inner(*args, **kwargs):
            time.sleep(seconds)
            return func(*args, **kwargs)

        return inner

    return wrapper


def wait_for_any(*element_css_selector_strs, **kwargs):
    timeout = kwargs.get("timeout", 10)
    error_form_return_selector = "*[data-error-code]"

    selectors = [*element_css_selector_strs, error_form_return_selector]

    def check(driver):
        for selector in selectors:
            elements = driver.find_elements(CSS, selector)
            if len(elements) > 0:
                if selector == error_form_return_selector:
                    # 打印 inner text
                    logger.error(f"表单输入错误：{elements[0].text}")
                    raise Exception(
                        f"Error code: {s(error_form_return_selector).get_attribute('data-error-code')}"
                    )
                return True
        return False

    return WebDriverWait(driver, timeout).until(check)


def click(element):
    element = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(element))
    element.click()


@sleep(1)
def navigate_to_chatgpt_register_page(driver=None):
    # if no such window
    if not driver:
        driver = get_browser()

    driver.switch_to.window(driver.window_handles[-1])

    # remove all cookies
    driver.delete_all_cookies()

    # go to the register link
    driver.get("https://chat.zhile.io/auth/signup")

    # wait for the page to load
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((CSS, "button[type=submit]"))
    )

    return


@sleep(1)
def register_step1(username, password):
    wait_for_any("#username")

    user_input, pass_input, submit_btn = (
        s("#username"),
        s("#password"),
        s("button[type=submit]"),
    )

    user_input.send_keys(username)
    pass_input.send_keys(password)

    click(submit_btn)


@sleep(1)
def register_step2(email_extracted_url: str):
    wait_for_any("#submit-token")

    submit_token_btn = s("#submit-token")
    click(submit_token_btn)

    wait_for_any("#swal2-input")

    url_input_textarea = s("#swal2-input")
    url_input_textarea.send_keys(email_extracted_url)

    ok_btn = s(".swal2-confirm")
    click(ok_btn)


@sleep(5)
def register_step3(username: str):
    wait_for_any("button[type=submit]")
    wait_for_any("#username")

    username_ipt = s("#username")
    username_ipt.send_keys(username)

    submit_btn = s("button[type=submit]")
    click(submit_btn)


@sleep(1)
def check_human_verification():
    # check if human verification is needed by check "Begin puzzle" in the page
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((CSS, "[aria-label='Audio']"))
        )
        return True
    except Exception as e:
        print(e)
        logger.error(e)
        return False


@sleep(1)
def register_step4(username, password):
    wait_for_any("a[href='/auth/login']")
    go_login_in_btn = s("a[href='/auth/login']")
    click(go_login_in_btn)

    wait_for_any("button[type=submit]")
    username_box = s("#username")
    continue_btn = s("button[type=submit]")

    username_box.send_keys(username)
    click(continue_btn)

    wait_for_any("#password")
    password_box = s("#password")
    continue_btn = s("button[type=submit]")

    password_box.send_keys(password)
    click(continue_btn)


driver = get_browser()
