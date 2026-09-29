#!/usr/bin/env python3
# coding: utf-8
import re
import os
import time
import codecs
import zipfile
import subprocess
import datetime
import mimetypes
import posixpath
import tinycss2
import sys
import json
import shutil
import logging
import argparse
import requests
import traceback
from html import escape, unescape
from random import random
from lxml import html, etree
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Value
from urllib.parse import urljoin, urlparse, urlsplit, parse_qs, quote, quote_plus, unquote


PATH = os.path.dirname(os.path.realpath(__file__))
COOKIES_FILE = os.path.join(PATH, "cookies.json")

ORLY_BASE_HOST = "oreilly.com"  # PLEASE INSERT URL HERE

SAFARI_BASE_HOST = "learning." + ORLY_BASE_HOST
API_ORIGIN_HOST = "api." + ORLY_BASE_HOST

ORLY_BASE_URL = "https://www." + ORLY_BASE_HOST
SAFARI_BASE_URL = "https://" + SAFARI_BASE_HOST
API_ORIGIN_URL = "https://" + API_ORIGIN_HOST
PROFILE_URL = SAFARI_BASE_URL + "/profile/"

# DEBUG
USE_PROXY = False
PROXIES = {"https": "https://127.0.0.1:8080"}


class Display:
    BASE_FORMAT = logging.Formatter(
        fmt="[%(asctime)s] %(message)s",
        datefmt="%d/%b/%Y %H:%M:%S"
    )

    SH_DEFAULT = "\033[0m" if "win" not in sys.platform else ""  # TODO: colors for Windows
    SH_YELLOW = "\033[33m" if "win" not in sys.platform else ""
    SH_BG_RED = "\033[41m" if "win" not in sys.platform else ""
    SH_BG_YELLOW = "\033[43m" if "win" not in sys.platform else ""

    def __init__(self, log_file):
        self.output_dir = ""
        self.output_dir_set = False
        self.log_file = os.path.join(PATH, log_file)

        self.logger = logging.getLogger("SafariBooks")
        self.logger.setLevel(logging.INFO)
        logs_handler = logging.FileHandler(filename=self.log_file)
        logs_handler.setFormatter(self.BASE_FORMAT)
        logs_handler.setLevel(logging.INFO)
        self.logger.addHandler(logs_handler)

        self.columns, _ = shutil.get_terminal_size()

        self.logger.info("** Welcome to SafariBooks! **")

        self.book_ad_info = False
        self.css_ad_info = Value("i", 0)
        self.images_ad_info = Value("i", 0)
        self.last_request = (None,)
        self.in_error = False

        self.state_status = Value("i", 0)
        sys.excepthook = self.unhandled_exception

    def set_output_dir(self, output_dir):
        self.info("Output directory:\n    %s" % output_dir)
        self.output_dir = output_dir
        self.output_dir_set = True

    def unregister(self):
        self.logger.handlers[0].close()
        sys.excepthook = sys.__excepthook__

    def log(self, message):
        try:
            self.logger.info(str(message, "utf-8", "replace"))

        except (UnicodeDecodeError, Exception):
            self.logger.info(message)

    def out(self, put):
        pattern = "\r{!s}\r{!s}\n"
        try:
            s = pattern.format(" " * self.columns, str(put, "utf-8", "replace"))

        except TypeError:
            s = pattern.format(" " * self.columns, put)

        sys.stdout.write(s)

    def info(self, message, state=False):
        self.log(message)
        output = (self.SH_YELLOW + "[*]" + self.SH_DEFAULT if not state else
                  self.SH_BG_YELLOW + "[-]" + self.SH_DEFAULT) + " %s" % message
        self.out(output)

    def error(self, error):
        if not self.in_error:
            self.in_error = True

        self.log(error)
        output = self.SH_BG_RED + "[#]" + self.SH_DEFAULT + " %s" % error
        self.out(output)

    def exit(self, error):
        self.error(str(error))

        if self.output_dir_set:
            output = (self.SH_YELLOW + "[+]" + self.SH_DEFAULT +
                      " Please delete the output directory '" + self.output_dir + "'"
                      " and restart the program.")
            self.out(output)

        output = self.SH_BG_RED + "[!]" + self.SH_DEFAULT + " Aborting..."
        self.out(output)

        self.save_last_request()
        sys.exit(1)

    def unhandled_exception(self, _, o, tb):
        self.log("".join(traceback.format_tb(tb)))
        self.exit("Unhandled Exception: %s (type: %s)" % (o, o.__class__.__name__))

    def save_last_request(self):
        if any(self.last_request):
            self.log("Last request done:\n\tURL: {0}\n\tDATA: {1}\n\tOTHERS: {2}\n\n\t{3}\n{4}\n\n{5}\n"
                     .format(*self.last_request))

    def intro(self):
        output = self.SH_YELLOW + (r"""
       ____     ___         _
      / __/__ _/ _/__ _____(_)
     _\ \/ _ `/ _/ _ `/ __/ /
    /___/\_,_/_/ \_,_/_/ /_/
      / _ )___  ___  / /__ ___
     / _  / _ \/ _ \/  '_/(_-<
    /____/\___/\___/_/\_\/___/
""" if random() > 0.5 else r"""
 ██████╗     ██████╗ ██╗  ██╗   ██╗██████╗
██╔═══██╗    ██╔══██╗██║  ╚██╗ ██╔╝╚════██╗
██║   ██║    ██████╔╝██║   ╚████╔╝   ▄███╔╝
██║   ██║    ██╔══██╗██║    ╚██╔╝    ▀▀══╝
╚██████╔╝    ██║  ██║███████╗██║     ██╗
 ╚═════╝     ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝
""") + self.SH_DEFAULT
        output += "\n" + "~" * (self.columns // 2)

        self.out(output)

    def parse_description(self, desc):
        if not desc:
            return "n/d"

        try:
            return html.fromstring(desc).text_content()

        except (html.etree.ParseError, html.etree.ParserError) as e:
            self.log("Error parsing the description: %s" % e)
            return "n/d"

    def book_info(self, info):
        description = self.parse_description(info.get("description", None)).replace("\n", " ")
        for t in [
            ("Title", info.get("title", "")), ("Authors", ", ".join(aut.get("name", "") for aut in info.get("authors", []))),
            ("Identifier", info.get("identifier", "")), ("ISBN", info.get("isbn", "")),
            ("Publishers", ", ".join(pub.get("name", "") for pub in info.get("publishers", []))),
            ("Rights", info.get("rights", "")),
            ("Description", description[:500] + "..." if len(description) >= 500 else description),
            ("Release Date", info.get("issued", "")),
            ("URL", info.get("web_url", ""))
        ]:
            self.info("{0}{1}{2}: {3}".format(self.SH_YELLOW, t[0], self.SH_DEFAULT, t[1]), True)

    def state(self, origin, done):
        progress = int(done * 100 / origin)
        bar = int(progress * (self.columns - 11) / 100)
        if self.state_status.value < progress:
            self.state_status.value = progress
            sys.stdout.write(
                "\r    " + self.SH_BG_YELLOW + "[" + ("#" * bar).ljust(self.columns - 11, "-") + "]" +
                self.SH_DEFAULT + ("%4s" % progress) + "%" + ("\n" if progress == 100 else "")
            )

    def done(self, epub_file):
        self.info("Done: %s\n\n" % epub_file +
                  "    If you like it, please * this project on GitHub to make it known:\n"
                  "        https://github.com/lorenzodifuccia/safaribooks\n"
                  "    e don't forget to renew your Safari Books Online subscription:\n"
                  "        " + SAFARI_BASE_URL + "\n\n" +
                  self.SH_BG_RED + "[!]" + self.SH_DEFAULT + " Bye!!")

    @staticmethod
    def api_error(response):
        message = "API: "
        if "detail" in response and "Not found" in response["detail"]:
            message += "book's not present in Safari Books Online.\n" \
                       "    The book identifier is the digits that you can find in the URL:\n" \
                       "    `" + SAFARI_BASE_URL + "/library/view/book-name/XXXXXXXXXXXXX/`"

        else:
            os.remove(COOKIES_FILE)
            message += "Out-of-Session%s.\n" % (" (%s)" % response["detail"]) if "detail" in response else "" + \
                       Display.SH_YELLOW + "[+]" + Display.SH_DEFAULT + \
                       " Use the `--cred` or `--login` options in order to perform the auth login to Safari."

        return message


class WinQueue(list):  # TODO: error while use `process` in Windows: can't pickle _thread.RLock objects
    def put(self, el):
        self.append(el)

    def qsize(self):
        return self.__len__()



def configure_console():
    """Make printing a title with characters outside the console code page (`charmap`) not crash."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


class SafariBooks:
    LOGIN_URL = ORLY_BASE_URL + "/member/auth/login/"
    LOGIN_ENTRY_URL = SAFARI_BASE_URL + "/login/unified/?next=/home/"

    API_TEMPLATE = SAFARI_BASE_URL + "/api/v2/epubs/urn:orm:book:{0}/"

    # Parallel downloads. Akamai's edge flake is independent of request pacing (see
    # requests_provider), so a few workers do not make it worse.
    WORKERS = 4

    # Our own stylesheets (base, kindle, externalized inline styles) live in their own
    # directory: the publisher's `styles/` may exist next to it, and `Styles` vs `styles`
    # would collide on case-insensitive file systems.
    OWN_STYLES_DIR = "sb_styles"
    OPF_NS = "http://www.idpf.org/2007/opf"
    DC_NS = "http://purl.org/dc/elements/1.1/"
    NCX_NS = "http://www.daisy.org/z3986/2005/ncx/"

    IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".bmp", ".tif", ".tiff")
    OTHER_MEDIA_TYPES = {
        ".xhtml": "application/xhtml+xml", ".html": "application/xhtml+xml", ".htm": "application/xhtml+xml",
        ".css": "text/css", ".ncx": "application/x-dtbncx+xml", ".svg": "image/svg+xml",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif",
        ".js": "text/javascript", ".xml": "application/xml",
    }

    BASE_STYLE_CSS = "body{margin:1em;background-color:transparent!important;}" \
                     "#sbo-rt-content *{text-indent:0pt!important;}#sbo-rt-content .bq{margin-right:1em!important;}" \
                     "#sbo-rt-content img{height:auto!important;max-width:100%!important;}"
    # Fixed-layout ("PDF-style") books: every page is a fixed-size canvas holding a page-sized
    # <img> plus one absolutely positioned <span class="t"> per text line.
    DEFAULT_PAGE_SIZE = (770, 1017)
    PAGE_SIZE_RE = re.compile(r"img\s*\{[^}]*?\bwidth:\s*(\d+)px\s*;\s*height:\s*(\d+)px")
    FIXED_LAYOUT_LINE_XPATH = "//span[contains(concat(' ', normalize-space(@class), ' '), ' t ')]"
    FIXED_LAYOUT_PAGE_XPATH = "//div[starts-with(@id, 'page') and img]"
    fixed_layout = False
    KINDLE_STYLE_CSS = "#sbo-rt-content *{word-wrap:break-word!important;" \
                       "word-break:break-word!important;}#sbo-rt-content table,#sbo-rt-content pre" \
                       "{overflow-x:unset!important;overflow:unset!important;" \
                       "overflow-y:unset!important;white-space:pre-wrap!important;}"
    # Format: title, nested <ol> markup
    NAV_XHTML = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" \
                "<!DOCTYPE html>\n" \
                "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\"" \
                " lang=\"en\" xml:lang=\"en\">\n" \
                "<head><meta charset=\"utf-8\"/><title>{0}</title></head>\n" \
                "<body><nav epub:type=\"toc\" id=\"toc\"><h1>{0}</h1>\n{1}</nav></body>\n</html>"
    HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Referer": LOGIN_ENTRY_URL,
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36"
    }
    COOKIE_FLOAT_MAX_AGE_PATTERN = re.compile(r'(max-age=\d*\.\d*)', re.IGNORECASE)
    # Akamai's edge WAF intermittently blocks otherwise-valid requests with a 403
    # "Access Denied" page (Server: AkamaiGHost, body links to errors.edgesuite.net)
    # completely independent of auth state or request pacing -- confirmed by
    # replaying the exact same URL with the exact same session dozens of times and
    # seeing it flip between success and this block at a ~30-45% rate. A real
    # app-level response (including a genuine auth failure) comes from the actual
    # backend, fingerprinted by Server: istio-envoy. Retrying only the Akamai
    # fingerprint means a genuine error still fails fast instead of retrying
    # something that will never succeed.
    #
    # With a per-request flake rate p, one request exhausts its retries with
    # probability p^(MAX_RETRIES+1), and a whole-book run (hundreds of chapter,
    # image and CSS requests) dies if any single one does. At p=0.45 over 200
    # requests, 5 retries still fail ~81% of runs; 10 retries fail ~3%. The
    # backoff is capped so the worst case stays bounded.
    AKAMAI_BLOCK_SERVER_MARKER = "akamai"
    MAX_RETRIES = 10
    RETRY_BACKOFF_BASE_SECONDS = 1.5
    RETRY_BACKOFF_MAX_SECONDS = 30
    DECLARATION_AT_RULES = frozenset(("font-face", "page"))
    FONT_MEDIA_TYPES = {
        ".otf": "application/vnd.ms-opentype",
        ".ttf": "application/x-font-truetype",
        ".woff": "application/font-woff",
        ".woff2": "font/woff2",
    }
    GENERIC_FONT_FAMILIES = frozenset((
        "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
        "ui-monospace", "ui-rounded", "math", "emoji", "fangsong",
    ))
    CSS_WIDE_KEYWORDS = frozenset(("inherit", "initial", "unset", "revert", "revert-layer"))
    MONOSPACE_FONT_HINTS = ("mono", "courier", "consolas", "menlo", "lucida console", "typewriter")
    SANS_FONT_HINTS = ("sans", "gothic", "arial", "helvetica", "verdana", "tahoma", "calibri", "univers", "futura",
                       "myriad", "frutiger", "trebuchet", "segoe", "roboto", "open sans", "lato")
    FIXED_LAYOUT_SCALE = 0.25
    BAKE_SCALE_RE = re.compile(r"scale\(\s*(?:0?\.25|[\d.]+\s*,\s*0?\.25)\s*\)")
    BAKE_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")
    BAKE_TEXT_SELECTOR_RE = re.compile(r"\.s\d+_\d+|#t[0-9a-z]+_\d+")
    BAKE_LENGTH_PROPS = ("font-size", "letter-spacing", "word-spacing", "line-height", "margin-top")
    BAKE_ANISOTROPIC_RE = re.compile(r"scale\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)")

    CONTAINER_XML = "<?xml version=\"1.0\"?>" \
                    "<container version=\"1.0\" xmlns=\"urn:oasis:names:tc:opendocument:xmlns:container\">" \
                    "<rootfiles>" \
                    "<rootfile full-path=\"OEBPS/{0}\" media-type=\"application/oebps-package+xml\" />" \
                    "</rootfiles>" \
                    "</container>"

    # Format: language, title, head links, body
    CHAPTER_XHTML = "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n" \
                    "<!DOCTYPE html>\n" \
                    "<html xmlns=\"http://www.w3.org/1999/xhtml\" xmlns:epub=\"http://www.idpf.org/2007/ops\"" \
                    " xmlns:xlink=\"http://www.w3.org/1999/xlink\" lang=\"{0}\" xml:lang=\"{0}\">\n" \
                    "<head>\n<meta charset=\"utf-8\"/>\n<title>{1}</title>\n{2}</head>\n" \
                    "<body>{3}</body>\n</html>"
    STYLESHEET_LINK = "<link href=\"{0}\" rel=\"stylesheet\" type=\"text/css\" />\n"

    def __init__(self, args):
        self.args = args
        self.display = Display("info_%s.log" % escape(args.bookid))
        self.display.intro()

        self.session = requests.Session()
        if USE_PROXY:  # DEBUG
            self.session.proxies = PROXIES
            self.session.verify = False

        self.session.headers.update(self.HEADERS)

        self.jwt = {}

        if not args.cred:
            if not os.path.isfile(COOKIES_FILE):
                self.display.exit("Login: unable to find `cookies.json` file.\n"
                                  "    Please use the `--cred` or `--login` options to perform the login.")

            self.session.cookies.update(json.load(open(COOKIES_FILE)))

        else:
            self.display.info("Logging into Safari Books Online...", state=True)
            self.do_login(*args.cred)
            if not args.no_cookies:
                json.dump(self.session.cookies.get_dict(), open(COOKIES_FILE, 'w'))

        self.check_login()

        self.book_id = args.bookid
        self.api_url = self.API_TEMPLATE.format(self.book_id)

        self.display.info("Retrieving book files...")
        self.book_files = self.get_book_files()
        self.plan = self.plan_files(self.book_files)

        self.display.info("Retrieving book info...")
        self.book_info = self.get_book_info()
        self.display.book_info(self.book_info)

        self.book_title = self.book_info["title"]
        self.clean_book_title = "".join(self.escape_dirname(self.book_title).split(",")[:2]) \
                                + " ({0})".format(self.book_id)

        books_dir = os.path.join(PATH, "Books")
        if not os.path.isdir(books_dir):
            os.mkdir(books_dir)

        self.BOOK_PATH = os.path.join(books_dir, self.clean_book_title)
        self.display.set_output_dir(self.BOOK_PATH)
        self.oebps_path = ""
        self.css_path = ""
        self.create_dirs()

        self.fixed_layout = False
        self.inline_stylesheets = {}
        self.font_sources = set()
        self.rename_map = {}
        self.chapter_stylesheets = self.plan_stylesheets(self.plan)

        self.download_and_build()

        if not args.no_cookies:
            json.dump(self.session.cookies.get_dict(), open(COOKIES_FILE, "w"))

        self.display.done(os.path.join(self.BOOK_PATH, self.book_id + ".epub"))
        self.display.unregister()

        if not self.display.in_error and not args.log:
            os.remove(self.display.log_file)


    def handle_cookie_update(self, set_cookie_headers):
        for morsel in set_cookie_headers:
            # Handle Float 'max-age' Cookie
            if self.COOKIE_FLOAT_MAX_AGE_PATTERN.search(morsel):
                cookie_key, cookie_value = morsel.split(";")[0].split("=")
                self.session.cookies.set(cookie_key, cookie_value)


    @staticmethod
    def is_transient_request_exception(exception):
        # Only errors that can plausibly succeed on a second try. Deterministic
        # failures (bad URL/scheme, TLS verification, redirect loops) must fail fast.
        if isinstance(exception, requests.exceptions.SSLError):
            return False

        return isinstance(exception, (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ))


    def sleep_before_retry(self, attempt, reason):
        backoff = min(
            self.RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
            self.RETRY_BACKOFF_MAX_SECONDS
        ) + random()
        self.display.info(
            "%s, retrying in %.1fs... (attempt %d/%d)" % (reason, backoff, attempt, self.MAX_RETRIES)
        )
        time.sleep(backoff)


    def requests_provider(self, url, is_post=False, data=None, perform_redirect=True, **kwargs):
        attempt = 0
        while True:
            attempt += 1
            try:
                response = getattr(self.session, "post" if is_post else "get")(
                    url,
                    data=data,
                    allow_redirects=False,
                    **kwargs
                )

                self.handle_cookie_update(response.raw.headers.getlist("Set-Cookie"))

                self.display.last_request = (
                    url, data, kwargs, response.status_code, "\n".join(
                        ["\t{}: {}".format(*h) for h in response.headers.items()]
                    ), response.text
                )

            except requests.RequestException as request_exception:
                if self.is_transient_request_exception(request_exception) and attempt <= self.MAX_RETRIES:
                    self.sleep_before_retry(
                        attempt, "Network error (%s)" % type(request_exception).__name__
                    )
                    continue

                self.display.error(str(request_exception))
                return 0

            is_akamai_edge_block = (
                response.status_code == 403 and
                self.AKAMAI_BLOCK_SERVER_MARKER in (response.headers.get("Server") or "").lower()
            )
            if is_akamai_edge_block and attempt <= self.MAX_RETRIES:
                # Release the pooled connection of a discarded (possibly streamed) response
                response.close()
                self.sleep_before_retry(attempt, "Blocked by edge WAF (transient): %s" % url)
                continue

            if response.is_redirect and perform_redirect:
                return self.requests_provider(response.next.url, is_post, None, perform_redirect)
                # TODO How about **kwargs?

            return response


    @staticmethod
    def parse_cred(cred):
        if ":" not in cred:
            return False

        sep = cred.index(":")
        new_cred = ["", ""]
        new_cred[0] = cred[:sep].strip("'").strip('"')
        if "@" not in new_cred[0]:
            return False

        new_cred[1] = cred[sep + 1:]
        return new_cred


    def do_login(self, email, password):
        response = self.requests_provider(self.LOGIN_ENTRY_URL)
        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")

        next_parameter = None
        try:
            next_parameter = parse_qs(urlparse(response.request.url).query)["next"][0]

        except (AttributeError, ValueError, IndexError):
            self.display.exit("Login: unable to complete login on Safari Books Online. Try again...")

        redirect_uri = API_ORIGIN_URL + quote_plus(next_parameter)

        response = self.requests_provider(
            self.LOGIN_URL,
            is_post=True,
            json={
                "email": email,
                "password": password,
                "redirect_uri": redirect_uri
            },
            perform_redirect=False
        )

        if response == 0:
            self.display.exit("Login: unable to perform auth to Safari Books Online.\n    Try again...")

        if response.status_code != 200:  # TODO To be reviewed
            try:
                error_page = html.fromstring(response.text)
                errors_message = error_page.xpath("//ul[@class='errorlist']//li/text()")
                recaptcha = error_page.xpath("//div[@class='g-recaptcha']")
                messages = (["    `%s`" % error for error in errors_message
                             if "password" in error or "email" in error] if len(errors_message) else []) + \
                           (["    `ReCaptcha required (wait or do logout from the website).`"] if len(
                               recaptcha) else [])
                self.display.exit(
                    "Login: unable to perform auth login to Safari Books Online.\n" + self.display.SH_YELLOW +
                    "[*]" + self.display.SH_DEFAULT + " Details:\n" + "%s" % "\n".join(
                        messages if len(messages) else ["    Unexpected error!"])
                )
            except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
                self.display.error(parsing_error)
                self.display.exit(
                    "Login: your login went wrong and it encountered in an error"
                    " trying to parse the login details of Safari Books Online. Try again..."
                )

        self.jwt = response.json()  # TODO: save JWT Tokens and use the refresh_token to restore user session
        response = self.requests_provider(self.jwt["redirect_uri"])
        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")


    def check_login(self):
        response = self.requests_provider(PROFILE_URL, perform_redirect=False)

        if response == 0:
            self.display.exit("Login: unable to reach Safari Books Online. Try again...")

        elif response.status_code != 200:
            self.display.exit("Authentication issue: unable to access profile page.")

        elif "user_type\":\"Expired\"" in response.text:
            self.display.exit("Authentication issue: account subscription expired.")

        self.display.info("Successfully authenticated.", state=True)


    def get_book_info(self):
        response = self.requests_provider(self.api_url)
        if response == 0:
            self.display.exit("API: unable to retrieve book info.")

        response = response.json()
        if not isinstance(response, dict) or "title" not in response:
            self.display.exit(self.display.api_error(response))

        desc = response.get("descriptions", {})
        result = {
            "title": response.get("title", ""),
            "authors": [],
            "identifier": response.get("identifier", ""),
            "isbn": response.get("isbn", ""),
            "publishers": [],
            "rights": "",
            "description": desc.get("text/html", desc.get("text/plain", "")),
            "issued": response.get("publication_date", ""),
            "web_url": SAFARI_BASE_URL + "/library/view/-/{0}/".format(self.book_id),
            "subjects": [{"name": t} for t in response.get("tags", [])],
        }
        result["authors"], result["publishers"] = self.get_book_credits()
        for key, value in result.items():
            if value is None:
                result[key] = "n/a"
        return result


    def get_book_credits(self):
        """Return (authors, publishers) as lists of {"name": ...} dicts.

        The v2 Epubs endpoint carries neither. The authenticated search API does, so use
        it first; when it fails or has no exact match for this book, fall back to the
        public toc.ncx <docAuthor> (author only). Anything unknown stays an empty list.
        """
        authors, publishers = [], []

        response = self.requests_provider(
            urljoin(SAFARI_BASE_URL, "/api/v2/search/?query={0}&limit=5".format(quote_plus(self.book_id)))
        )
        if response != 0 and response.status_code == 200:
            try:
                results = response.json().get("results", [])
            except (ValueError, AttributeError):
                results = []
            match = next((r for r in results if str(r.get("archive_id", "")) == str(self.book_id)), None)
            if match:
                authors = [{"name": n} for n in match.get("authors") or [] if n]
                publishers = [{"name": n} for n in match.get("publishers") or [] if n]

        if not authors:
            authors = self.get_ncx_authors()

        if not authors:
            self.display.warning("Unable to find the book's author(s); the EPUB will have none.")
        if not publishers:
            self.display.warning("Unable to find the book's publisher; the EPUB will have none.")

        return authors, publishers


    def get_ncx_authors(self):
        response = self.requests_provider(urljoin(self.api_url, "files/toc.ncx"))
        if response == 0 or response.status_code != 200:
            return []

        match = re.search(r"<docAuthor>\s*<text>(.*?)</text>\s*</docAuthor>", self.response_text(response), re.S)
        name = unescape(match.group(1)).strip() if match else ""
        return [{"name": name}] if name else []


    @staticmethod
    def sanitize_xml_id(raw):
        xml_id = raw.replace("/", "_")
        if not xml_id or not (xml_id[0].isalpha() or xml_id[0] == "_"):
            xml_id = "id_" + xml_id

        return xml_id


    @staticmethod
    def response_text(response):
        """Decode a response body as UTF-8 unless the server declares a charset.

        `response.text` must not be used for book content: when the
        Content-Type has no charset, requests falls back to ISO-8859-1 for
        text/* and turns every multi-byte UTF-8 character into several junk
        characters (mojibake), which then get re-saved as UTF-8.

        An unknown declared charset falls back to UTF-8, as response.text does
        for a bogus label, instead of raising LookupError."""
        declared = "charset" in (response.headers.get("Content-Type") or "").lower()
        encoding = response.encoding if declared and response.encoding else "utf-8"
        try:
            codecs.lookup(encoding)
        except LookupError:
            encoding = "utf-8"
        return response.content.decode(encoding, errors="replace")


    @staticmethod
    def url_is_absolute(url):
        return bool(urlparse(url).netloc)


    @staticmethod
    def escape_dirname(dirname, clean_space=False):
        if ":" in dirname:
            if dirname.index(":") > 15:
                dirname = dirname.split(":")[0]

            elif "win" in sys.platform:
                dirname = dirname.replace(":", ",")

        for ch in ['~', '#', '%', '&', '*', '{', '}', '\\', '<', '>', '?', '/', '`', '\'', '"', '|', '+', ':']:
            if ch in dirname:
                dirname = dirname.replace(ch, "_")

        return dirname if not clean_space else dirname.replace(" ", "")


    # ------------------------------------------------------------------ file listing
    def get_book_files(self):
        """Every file of the EPUB as published: /api/v2/epubs/urn:orm:book:<id>/files/ (paginated)."""
        files = []
        url = urljoin(self.api_url, "files/?limit=200")
        while url:
            response = self.requests_provider(url)
            if response == 0:
                self.display.exit("API: unable to retrieve the book's file list.")

            try:
                data = response.json()
            except ValueError:
                data = None

            if not isinstance(data, dict) or "results" not in data:
                self.display.exit(self.display.api_error(data if isinstance(data, dict) else {}))

            files.extend(data["results"])
            url = data.get("next")

        if not files:
            self.display.exit("API: the book has no files (wrong book id, or no access to it).")

        return files

    @staticmethod
    def clean_book_path(full_path):
        """Normalized POSIX path of a publisher file, or None when it would escape OEBPS/."""
        if not isinstance(full_path, str) or "\x00" in full_path:
            return None

        clean = posixpath.normpath(full_path.replace("\\", "/")).lstrip("/")
        if clean in ("", ".", "..") or clean.startswith("../"):
            return None

        return clean

    @staticmethod
    def classify_file(entry):
        """opf, ncx, chapter, stylesheet, image, font or other, from the API's own metadata."""
        media = (entry.get("media_type") or "").lower()
        ext = posixpath.splitext(entry.get("full_path") or "")[1].lower()
        if media == "application/oebps-package+xml" or ext == ".opf":
            return "opf"

        if media == "application/x-dtbncx+xml" or ext == ".ncx":
            return "ncx"

        if entry.get("kind") == "chapter":
            return "chapter"

        if media == "text/css" or ext == ".css":
            return "stylesheet"

        if media.startswith("image/") or ext in SafariBooks.IMAGE_EXTENSIONS:
            return "image"

        if media.startswith("font/") or "font" in media or ext in SafariBooks.FONT_MEDIA_TYPES:
            return "font"

        return "other"

    def plan_files(self, files):
        plan = {"opf": [], "ncx": [], "chapter": [], "stylesheet": [], "image": [], "font": [], "other": []}
        seen = set()
        for entry in files:
            path = self.clean_book_path(entry.get("full_path"))
            if path is None or not entry.get("url"):
                self.display.warning("Skipping a file with an unusable path: %r" % entry.get("full_path"))
                continue

            if path in seen:
                continue

            seen.add(path)
            entry = dict(entry, path=path)
            plan[self.classify_file(entry)].append(entry)

        if not plan["opf"]:
            self.display.exit("API: the book's file list has no OPF package document.")

        self.opf_path = plan["opf"][0]["path"]
        self.ncx_path = plan["ncx"][0]["path"] if plan["ncx"] else None
        if plan["ncx"]:
            self.ncx_url = plan["ncx"][0]["url"]

        plan["documents"] = plan["opf"] + plan["ncx"] + plan["chapter"] + plan["other"]
        return plan

    @staticmethod
    def plan_stylesheets(plan):
        """Publisher stylesheets, in a stable order. The API does not say which chapter uses which
        one, so every chapter links all of them (the CSS is scoped under #sbo-rt-content)."""
        return sorted(e["path"] for e in plan["stylesheet"])

    def destination(self, path):
        return os.path.join(self.oebps_path, *path.split("/"))

    # ------------------------------------------------------------------ downloads
    def run_parallel(self, func, items):
        """Run func(item) for every item on a few threads; func returns an error string or None."""
        self.display.state_status.value = -1
        errors = []
        if not items:
            return errors

        done = 0
        with ThreadPoolExecutor(max_workers=self.WORKERS) as executor:
            futures = {executor.submit(func, item): item for item in items}
            for future in as_completed(futures):
                try:
                    error = future.result()
                except Exception as exception:  # a failing worker must not kill the others
                    error = "%s: %s (%s)" % (type(exception).__name__, exception, futures[future]["path"])

                if error:
                    errors.append(error)

                done += 1
                self.display.state(len(items), done)

        return errors

    def abort_on_errors(self, errors, what):
        if errors:
            for error in errors:
                self.display.error(error)

            self.display.exit("%d %s failed to download. Nothing already downloaded is lost: wait a few "
                              "minutes and run the same command again to resume." % (len(errors), what))

    @staticmethod
    def is_text_file(entry):
        media = (entry.get("media_type") or "").lower()
        ext = posixpath.splitext(entry["path"])[1].lower()
        return (media.startswith("text/") or media.endswith("+xml") or media.endswith("/xml")
                or ext in (".html", ".xhtml", ".htm", ".xml", ".txt", ".css", ".opf", ".ncx"))

    def save_text(self, path, text):
        dest = self.destination(path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        with open(part, "w", encoding="utf-8") as out:
            out.write(text)

        os.replace(part, dest)

    def fetch_binary(self, entry):
        dest = self.destination(entry["path"])
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            return None

        response = self.requests_provider(entry["url"], stream=True)
        if response == 0 or response.status_code != 200:
            return "HTTP %s: %s" % ("error" if response == 0 else response.status_code, entry["path"])

        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part = dest + ".part"
        with open(part, "wb") as out:
            for chunk in response.iter_content(65536):
                out.write(chunk)

        os.replace(part, dest)
        return None

    def fetch_document(self, entry):
        dest = self.destination(entry["path"])
        kind = self.classify_file(entry)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            if kind == "chapter":
                # Resumed run: parse_chapter() will not run again, so read the fixed-layout marker
                # from the page already on disk (it was lost on resume before).
                with open(dest, "rb") as page:
                    if self.is_fixed_layout_page(html.fromstring(page.read())):
                        self.fixed_layout = True

            return None

        if not self.is_text_file(entry):
            return self.fetch_binary(entry)

        response = self.requests_provider(entry["url"])
        if response == 0 or response.status_code != 200:
            return "HTTP %s: %s" % ("error" if response == 0 else response.status_code, entry["path"])

        text = self.localize_api_links(self.response_text(response), entry["path"], self.book_id)
        if kind == "chapter":
            text = self.parse_chapter(text, entry["path"])

        elif kind == "other" and posixpath.splitext(entry["path"])[1].lower() in (".html", ".xhtml", ".htm"):
            text = self.strip_injected_document(text)

        self.save_text(entry["path"], text)
        return None

    def collect_documents(self):
        self.abort_on_errors(self.run_parallel(self.fetch_document, self.plan["documents"]), "document(s)")

    # ------------------------------------------------------------------ links
    @staticmethod
    def localize_api_links(text, full_path, book_id):
        """Turn the API's absolute asset URLs into paths relative to the file being saved.

        A chapter comes back with `/api/v2/epubs/urn:orm:book:<id>/files/<path>` links; inside the EPUB
        the same file sits at `<path>` under OEBPS/, so the prefix becomes one `../` per directory level
        of the referring file. Works for flat books and for books with xhtml/ + styles/ + images/ folders."""
        pattern = re.compile(r"(?:https?://%s)?/api/v2/epubs/urn:orm:book:%s/files/" % (
            re.escape(SAFARI_BASE_HOST), re.escape(book_id)))
        return pattern.sub("../" * posixpath.dirname(full_path).count("/") + (
            "../" if posixpath.dirname(full_path) else ""), text)

    def book_link(self, link, full_path):
        """Absolute links into this very book (a library/view URL) become relative, as before."""
        if link and not link.startswith("mailto") and self.url_is_absolute(link) and self.book_id in link \
                and urlparse(link).netloc == SAFARI_BASE_HOST:
            target = link.split(self.book_id)[-1].lstrip("/")
            depth = posixpath.dirname(full_path).count("/") + (1 if posixpath.dirname(full_path) else 0)
            return "../" * depth + target

        return link

    @staticmethod
    def strip_injected(root):
        """Remove the anti-bot markup Akamai injects into HTML responses (it breaks the EPUB3 nav
        document): scripts, root-relative <link>s and the security overlay."""
        for element in root.xpath("//script | //link[starts-with(@href, '/')] | //div[@id='sec-overlay']"):
            element.getparent().remove(element)

    @staticmethod
    def strip_injected_document(text):
        """Same for a whole document. XHTML is edited as XML so namespaces and the doctype survive;
        anything that does not parse is cleaned with patterns instead."""
        if "<script" not in text and "sec-overlay" not in text and 'href="/' not in text:
            return text

        try:
            root = etree.fromstring(text.encode("utf-8"))
        except etree.XMLSyntaxError:
            return re.sub(r"<script\b[^>]*>.*?</script>|<link\b[^>]*\bhref=\"/[^\"]*\"[^>]*>", "", text,
                          flags=re.S)

        xhtml = "{http://www.w3.org/1999/xhtml}"
        for element in root.xpath(
                "//x:script | //x:link[starts-with(@href, '/')] | //x:div[@id='sec-overlay']",
                namespaces={"x": xhtml[1:-1]}):
            element.getparent().remove(element)

        return etree.tostring(root.getroottree(), xml_declaration=True, encoding="utf-8").decode("utf-8")

    # ------------------------------------------------------------------ chapters
    def chapter_title(self, content, full_path):
        for heading in content.xpath(".//h1 | .//h2 | .//h3"):
            text = " ".join(heading.text_content().split())
            if text:
                return text

        return posixpath.splitext(posixpath.basename(full_path))[0]

    def head_links(self, full_path):
        """Stylesheet <link>s for a chapter: publisher CSS first, our base CSS last so it wins."""
        here = posixpath.dirname(full_path) or "."
        links = [posixpath.relpath(css, here) for css in self.chapter_stylesheets]
        links += [posixpath.relpath(posixpath.join(self.OWN_STYLES_DIR, name), here)
                  for name in sorted(self.inline_stylesheets.values())]
        links.append(posixpath.relpath(posixpath.join(self.OWN_STYLES_DIR, "Style_Base.css"), here))
        if self.args.kindle:
            links.append(posixpath.relpath(posixpath.join(self.OWN_STYLES_DIR, "Style_Kindle.css"), here))

        return "".join(self.STYLESHEET_LINK.format(escape(quote(link, safe="/"), quote=True)) for link in links)

    def parse_chapter(self, text, full_path):
        """A served chapter is an HTML fragment (`<div id="sbo-rt-content">`); return a full XHTML page."""
        try:
            root = html.fromstring(text)
        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.display.error(parsing_error)
            self.display.exit("Parser: error trying to parse this page: %s" % full_path)

        self.strip_injected(root)
        content = root.xpath("//div[@id='sbo-rt-content']")
        if content:
            content = content[0]
        else:
            # A whole document without the wrapper: the publisher CSS is scoped under it, so add it.
            body = root.find(".//body")
            source = body if body is not None else root
            content = html.fromstring("<div id=\"sbo-rt-content\"></div>")
            content.text = source.text
            for child in list(source):
                content.append(child)

        # Stylesheets: a relative <link> the publisher kept is honoured (and de-duplicated against
        # the shared list); everything else was injected or is absolute and is dropped.
        for link in content.xpath(".//link"):
            link.getparent().remove(link)

        for style in content.xpath(".//style"):
            if style.get("data-template"):
                style.text = style.get("data-template")
                del style.attrib["data-template"]

            if (style.text or "").strip():
                self.get_inline_stylesheet_link(style.text)

            style.getparent().remove(style)

        # SVG-wrapped images (covers) become plain <img>: many readers ignore <image xlink:href>.
        for image in content.xpath(".//image"):
            image_attr_href = [x for x in image.attrib.keys() if "href" in x]
            svg = image.getparent()
            if len(image_attr_href) and svg is not None and svg.getparent() is not None:
                new_img = svg.makeelement("img")
                new_img.attrib.update({"src": image.attrib.get(image_attr_href[0])})
                svg.addprevious(new_img)
                svg.getparent().remove(svg)

        if self.is_fixed_layout_page(content):
            self.fixed_layout = True

        self.strip_empty_output_blocks(content)
        if not self.args.no_optimize_css and not self.is_fixed_layout_page(content):
            self.strip_inline_style_color(content)

        content.rewrite_links(lambda link: self.book_link(link, full_path))
        try:
            body = html.tostring(content, method="xml", encoding="unicode", with_tail=False)
        except (html.etree.ParseError, html.etree.ParserError) as parsing_error:
            self.display.error(parsing_error)
            self.display.exit("Parser: error trying to parse HTML of this page: %s" % full_path)

        language = escape(str(self.book_info.get("language") or "en"), quote=True)
        return self.CHAPTER_XHTML.format(
            language, escape(self.chapter_title(content, full_path)), self.head_links(full_path), body
        )


    @staticmethod
    def strip_empty_output_blocks(root):
        for pre in root.xpath("//pre[@data-type='programlisting'][@class='output']"):
            text = (pre.text_content() or "").strip()
            if text in ("", "''"):
                pre.getparent().remove(pre)


    @staticmethod
    def _is_color_declaration(node):
        return getattr(node, "type", None) == "declaration" and node.lower_name == "color"


    @staticmethod
    def _is_keepable(node):
        return getattr(node, "type", None) != "error" and not SafariBooks._is_color_declaration(node)


    @staticmethod
    def _strip_color_from_rules(rules):
        for rule in rules:
            rule_type = getattr(rule, "type", None)
            if rule_type == "qualified-rule":
                declarations = tinycss2.parse_declaration_list(
                    rule.content, skip_comments=False, skip_whitespace=False
                )
                rule.content = [d for d in declarations if SafariBooks._is_keepable(d)]

            elif rule_type == "at-rule" and rule.content is not None:
                if rule.lower_at_keyword in SafariBooks.DECLARATION_AT_RULES:
                    # The body is a declaration list (src, font-family, margin, ...), not nested rules.
                    # Parsing it as rules turns every declaration into an error node and empties the block.
                    declarations = tinycss2.parse_declaration_list(
                        rule.content, skip_comments=False, skip_whitespace=False
                    )
                    rule.content = [d for d in declarations if SafariBooks._is_keepable(d)]
                    continue

                nested = tinycss2.parse_rule_list(rule.content, skip_comments=False, skip_whitespace=False)
                nested = [r for r in nested if SafariBooks._is_keepable(r)]
                SafariBooks._strip_color_from_rules(nested)
                rule.content = nested


    @staticmethod
    def _font_url_nodes(declaration):
        """Yield (node, url) for every url(...) in a declaration value: a url token or a url("...") function."""
        for token in declaration.value:
            if token.type == "url":
                yield token, token.value
            elif token.type == "function" and token.lower_name == "url":
                strings = [a for a in token.arguments if a.type == "string"]
                if strings:
                    yield strings[0], strings[0].value


    @staticmethod
    def _font_filename(font_url):
        name = unquote(os.path.basename(urlparse(font_url).path))
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            return ""

        return name


    @staticmethod
    def _font_family_names(value):
        """Lower-cased identifiers / quoted names of a font-family value."""
        names = []
        for token in value:
            if token.type == "ident":
                names.append(token.lower_value)
            elif token.type == "string":
                names.append(token.value.lower())
        return names


    @staticmethod
    def _generic_for_font_family(value):
        names = SafariBooks._font_family_names(value)
        if any(n in SafariBooks.GENERIC_FONT_FAMILIES or n in SafariBooks.CSS_WIDE_KEYWORDS for n in names):
            return None
        joined = " ".join(names)
        if any(hint in joined for hint in SafariBooks.MONOSPACE_FONT_HINTS):
            return "monospace"
        if any(hint in joined for hint in SafariBooks.SANS_FONT_HINTS):
            return "sans-serif"
        return "serif"


    @staticmethod
    def _add_generic_to_declaration(declaration):
        """Add the fallback in place; return True when the declaration changed."""
        if getattr(declaration, "type", None) != "declaration" or declaration.lower_name != "font-family":
            return False
        generic = SafariBooks._generic_for_font_family(declaration.value)
        if generic is None:
            return False
        value = list(declaration.value)
        while value and value[-1].type in ("whitespace", "comment"):
            value.pop()
        if not value:
            return False
        value.extend(tinycss2.parse_component_value_list(", " + generic))
        declaration.value = value
        return True


    @staticmethod
    def _add_generic_font_family_to_rules(rules):
        for rule in rules:
            rule_type = getattr(rule, "type", None)
            if rule_type == "qualified-rule":
                declarations = tinycss2.parse_declaration_list(
                    rule.content, skip_comments=False, skip_whitespace=False
                )
                # Reserialize only rules that changed, so untouched CSS keeps its original text.
                changed = [SafariBooks._add_generic_to_declaration(d) for d in declarations]
                if any(changed):
                    rule.content = declarations

            elif (rule_type == "at-rule" and rule.content is not None
                  and rule.lower_at_keyword not in SafariBooks.DECLARATION_AT_RULES):
                nested = tinycss2.parse_rule_list(rule.content, skip_comments=False, skip_whitespace=False)
                SafariBooks._add_generic_font_family_to_rules(nested)
                if "font-family" in tinycss2.serialize(nested).lower():
                    rule.content = nested


    @staticmethod
    def add_generic_font_family_to_stylesheet(css_text):
        """Append a generic family (serif, sans-serif or monospace) to every font-family list that has none.

        The publisher CSS names print fonts that no e-reader has, with no fallback; Calibre's check reports
        each of these as "Unexpected missing generic font family". The named font stays first, so readers
        that do have it are unaffected. @font-face descriptors are left alone (a generic is invalid there).
        """
        rules = tinycss2.parse_stylesheet(css_text, skip_comments=False, skip_whitespace=False)
        SafariBooks._add_generic_font_family_to_rules(rules)
        return tinycss2.serialize(rules)


    @staticmethod
    def add_generic_font_family_to_style_attr(style_value):
        declarations = tinycss2.parse_declaration_list(style_value, skip_comments=True, skip_whitespace=True)
        for declaration in declarations:
            SafariBooks._add_generic_to_declaration(declaration)
        return tinycss2.serialize(declarations).strip()


    @staticmethod
    def strip_color_from_stylesheet(css_text):
        rules = tinycss2.parse_stylesheet(css_text, skip_comments=False, skip_whitespace=False)
        rules = [r for r in rules if SafariBooks._is_keepable(r)]
        SafariBooks._strip_color_from_rules(rules)
        return SafariBooks.add_generic_font_family_to_stylesheet(tinycss2.serialize(rules))


    @staticmethod
    def strip_color_from_style_attr(style_value):
        declarations = tinycss2.parse_declaration_list(style_value, skip_comments=True, skip_whitespace=True)
        kept = [d for d in declarations if SafariBooks._is_keepable(d)]
        return tinycss2.serialize(kept).strip()


    @staticmethod
    def strip_inline_style_color(root):
        for el in root.xpath("//*[@style]"):
            new_value = SafariBooks.add_generic_font_family_to_style_attr(
                SafariBooks.strip_color_from_style_attr(el.get("style"))
            )
            if new_value:
                el.set("style", new_value)
            else:
                del el.attrib["style"]


    def get_inline_stylesheet_link(self, content):
        if content not in self.inline_stylesheets:
            filename = "Inline{0:0>2}.css".format(len(self.inline_stylesheets))
            processed = content if self.args.no_optimize_css else self.strip_color_from_stylesheet(content)
            os.makedirs(self.css_path, exist_ok=True)
            open(os.path.join(self.css_path, filename), "w", encoding="utf-8").write(processed)
            self.inline_stylesheets[content] = filename

        return self.inline_stylesheets[content]

    # ------------------------------------------------------------------ stylesheets and fonts
    @staticmethod
    def resolve_local(base_path, value):
        """OEBPS-relative path a link inside `base_path` points at, or None (external, data:, #anchor...)."""
        value = (value or "").strip()
        if not value or value.startswith(("#", "//", "data:", "mailto:", "javascript:")):
            return None

        parts = urlsplit(value)
        if parts.scheme or parts.netloc or not parts.path:
            return None

        target = posixpath.normpath(posixpath.join(posixpath.dirname(base_path), unquote(parts.path)))
        if target.startswith("../") or target in ("..", ".") or target.startswith("/"):
            return None

        return target

    @staticmethod
    def font_face_sources(css_text, css_path):
        """OEBPS paths of the fonts the stylesheet asks readers to load (@font-face `src: url()` only).

        A `src` inside an ordinary rule is not a font the book loads: the publisher CSS has one pointing
        at a 23 MB Arial Unicode file that must not be downloaded. `data:` URIs and absolute URLs are skipped."""
        found = []

        def walk(rules):
            for rule in rules:
                if getattr(rule, "type", None) != "at-rule" or rule.content is None:
                    continue

                if rule.lower_at_keyword == "font-face":
                    for declaration in tinycss2.parse_declaration_list(
                            rule.content, skip_comments=True, skip_whitespace=True):
                        if getattr(declaration, "type", None) == "declaration" and declaration.lower_name == "src":
                            for _, value in SafariBooks._font_url_nodes(declaration):
                                path = SafariBooks.resolve_local(css_path, value)
                                if path:
                                    found.append(path)

                elif rule.lower_at_keyword not in SafariBooks.DECLARATION_AT_RULES:
                    walk(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True))

        walk(tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True))
        return found

    def fetch_stylesheet(self, entry):
        dest = self.destination(entry["path"])
        if os.path.isfile(dest):
            with open(dest, encoding="utf-8", errors="replace") as css_file:
                self.font_sources.update(self.font_face_sources(css_file.read(), entry["path"]))

            return None

        response = self.requests_provider(entry["url"])
        if response == 0 or response.status_code != 200:
            return "HTTP %s: %s" % ("error" if response == 0 else response.status_code, entry["path"])

        content = self.localize_api_links(response.content.decode("utf-8", errors="replace"),
                                          entry["path"], self.book_id)
        self.font_sources.update(self.font_face_sources(content, entry["path"]))
        # Fixed-layout books keep the publisher CSS as is: stripping colours turns the positioned
        # white-on-dark text black.
        if not (self.args.no_optimize_css or self.fixed_layout):
            content = self.strip_color_from_stylesheet(content)

        self.save_text(entry["path"], content)
        return None

    def collect_css(self):
        self.abort_on_errors(self.run_parallel(self.fetch_stylesheet, self.plan["stylesheet"]), "stylesheet(s)")

    def fetch_font(self, entry):
        error = self.fetch_binary(entry)
        if error:
            # The @font-face rule stays; readers fall back to the generic family added after the name.
            self.display.warning("Could not download font %s; the book will use a fallback for it." % entry["path"])

        return None

    def collect_fonts(self):
        wanted = [e for e in self.plan["font"] if e["path"] in self.font_sources]
        skipped = [e["path"] for e in self.plan["font"] if e["path"] not in self.font_sources]
        if skipped:
            self.display.log("Fonts not loaded by any @font-face, not downloaded: %s" % ", ".join(skipped))

        known = {e["path"] for e in self.plan["font"]}
        for missing in sorted(self.font_sources - known):
            self.display.warning("Stylesheet asks for a font the book does not ship: %s" % missing)

        self.run_parallel(self.fetch_font, wanted)

    # ------------------------------------------------------------------ images
    ATTRIBUTE_REF_RE = re.compile(
        r"""(\s(?:src|href|xlink:href|poster|data)\s*=\s*)(["'])([^"']*)\2""", re.IGNORECASE)
    URL_REF_RE = re.compile(r"""url\(\s*(["']?)([^)"']+?)\1\s*\)""", re.IGNORECASE)
    DOCUMENT_EXTENSIONS = (".xhtml", ".html", ".htm", ".css")

    def document_files(self):
        """OEBPS paths of every downloaded XHTML/HTML/CSS file."""
        found = []
        for dirpath, _, filenames in os.walk(self.oebps_path):
            for name in filenames:
                if name.lower().endswith(self.DOCUMENT_EXTENSIONS):
                    full = os.path.join(dirpath, name)
                    found.append(os.path.relpath(full, self.oebps_path).replace(os.sep, "/"))

        return sorted(found)

    @staticmethod
    def references_in(text, base_path):
        refs = set()
        for match in SafariBooks.ATTRIBUTE_REF_RE.finditer(text):
            path = SafariBooks.resolve_local(base_path, unescape(match.group(3)))
            if path:
                refs.add(path)

        for match in SafariBooks.URL_REF_RE.finditer(text):
            path = SafariBooks.resolve_local(base_path, unescape(match.group(2)))
            if path:
                refs.add(path)

        return refs

    def referenced_paths(self, only_chapters=False):
        refs = set()
        for path in self.document_files():
            if only_chapters and path.lower().endswith(".css"):
                continue

            with open(self.destination(path), encoding="utf-8", errors="replace") as document:
                refs |= self.references_in(document.read(), path)

        return refs

    @staticmethod
    def cover_image_paths(opf_bytes, opf_path):
        """The cover image(s) the publisher's OPF declares (`cover-image` property or <meta name=cover>)."""
        try:
            root = etree.fromstring(opf_bytes)
        except etree.XMLSyntaxError:
            return set()

        ns = {"opf": SafariBooks.OPF_NS}
        items = {i.get("id"): i for i in root.findall("opf:manifest/opf:item", ns)}
        wanted = [i for i in items.values() if "cover-image" in (i.get("properties") or "").split()]
        for meta in root.findall("opf:metadata/opf:meta", ns):
            if meta.get("name") == "cover" and meta.get("content") in items:
                wanted.append(items[meta.get("content")])

        paths = set()
        for item in wanted:
            path = SafariBooks.resolve_local(opf_path, item.get("href"))
            if path:
                paths.add(path)

        return paths

    def cover_paths(self):
        with open(self.destination(self.opf_path), "rb") as opf:
            return self.cover_image_paths(opf.read(), self.opf_path)

    def collect_images(self):
        if self.args.no_optimize_images:
            wanted = self.plan["image"]  # faithful mirror: the publisher's images, untouched
        else:
            # Only what the pages (or their CSS) actually use, plus the cover: the same result as
            # downloading everything and then pruning, without the wasted transfers.
            needed = self.referenced_paths() | self.cover_paths()
            wanted = [e for e in self.plan["image"] if e["path"] in needed]

        self.abort_on_errors(self.run_parallel(self.fetch_binary, wanted), "image(s)")

    @staticmethod
    def rewrite_refs_in_text(text, base_path, rename_map):
        """Point every reference to a renamed file at its new name, editing the text in place."""
        def renamed(value):
            path = SafariBooks.resolve_local(base_path, unescape(value))
            if path not in rename_map:
                return value

            parts = urlsplit(value)
            head = parts.path[:len(parts.path) - len(posixpath.basename(parts.path))]
            return (head + quote(posixpath.basename(rename_map[path]))
                    + ("?" + parts.query if parts.query else "") + ("#" + parts.fragment if parts.fragment else ""))

        text = SafariBooks.ATTRIBUTE_REF_RE.sub(
            lambda m: m.group(1) + m.group(2) + renamed(m.group(3)) + m.group(2), text)
        return SafariBooks.URL_REF_RE.sub(lambda m: "url(" + m.group(1) + renamed(m.group(2)) + m.group(1) + ")", text)


    @staticmethod
    def needs_jpg_conversion(filename):
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext not in ("jpg", "jpeg", "svg")


    @staticmethod
    def convert_image_to_jpg(src_path, dest_path):
        with Image.open(src_path) as img:
            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                img = img.convert("RGBA")
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1])
                img = background

            elif img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            img.save(dest_path, "JPEG")


    @staticmethod
    def unique_jpg_path(path, taken):
        stem, ext = posixpath.splitext(path)
        candidate = stem + ".jpg"
        if candidate in taken:  # a.png next to a.jpg: never overwrite the publisher's own file
            candidate = "%s_%s.jpg" % (stem, ext.lstrip(".").lower())

        return candidate

    def finalize_images(self):
        on_disk = [e["path"] for e in self.plan["image"] if os.path.isfile(self.destination(e["path"]))]
        taken = set(on_disk)
        rename_map = {}
        for path in sorted(on_disk):
            if not self.needs_jpg_conversion(path):
                continue

            new_path = self.unique_jpg_path(path, taken)
            try:
                self.convert_image_to_jpg(self.destination(path), self.destination(new_path))

            except (OSError, Image.DecompressionBombError) as conversion_error:
                self.display.error("Unable to convert image `%s`: %s" % (path, conversion_error))
                continue

            os.remove(self.destination(path))
            taken.discard(path)
            taken.add(new_path)
            rename_map[path] = new_path

        if rename_map:
            self.rename_map.update(rename_map)
            for path in self.document_files():
                with open(self.destination(path), encoding="utf-8", errors="replace") as document:
                    original = document.read()

                updated = self.rewrite_refs_in_text(original, path, rename_map)
                if updated != original:
                    self.save_text(path, updated)

        # Chapters only: a stylesheet that mentions an image does not make it part of the book text,
        # but it must still keep the image alive (below).
        chapter_refs = self.referenced_paths(only_chapters=True)
        cover = self.cover_paths() | {rename_map.get(p, p) for p in self.cover_paths()}
        candidates = [p for p in (rename_map.get(p, p) for p in on_disk)
                      if p not in cover and os.path.isfile(self.destination(p))]
        if candidates and not chapter_refs and self.chapters_exist():
            # Images were downloaded for chapters, yet no chapter references any of them: the scanner
            # is out of sync with the markup, not the book image-free. Pruning deleted every image of a
            # real book once; never do that again.
            self.display.error("No image references recognised in the chapters; skipping unused-image pruning.")
            return

        referenced = self.referenced_paths()
        for path in candidates:
            if path not in referenced:
                os.remove(self.destination(path))

    def chapters_exist(self):
        return any(os.path.isfile(self.destination(e["path"])) for e in self.plan["chapter"])

    # ------------------------------------------------------------------ fixed-layout books

    @staticmethod
    def is_fixed_layout_page(content_root):
        """True for a PDF-style page: absolutely positioned text lines, or a bare page image."""
        return bool(content_root.xpath(SafariBooks.FIXED_LAYOUT_LINE_XPATH) or
                    content_root.xpath(SafariBooks.FIXED_LAYOUT_PAGE_XPATH))


    @staticmethod
    def detect_page_size(css_text):
        """(width, height) in px of the page canvas, read from the publisher's `img{...}` rule."""
        match = SafariBooks.PAGE_SIZE_RE.search(css_text or "")
        return (int(match.group(1)), int(match.group(2))) if match else SafariBooks.DEFAULT_PAGE_SIZE


    @staticmethod
    def fixed_layout_stylesheet(size):
        """Replacement for Style_Base.css: pin the page image to the canvas the text is placed on.

        The reflowable rule (`img{height:auto;max-width:100%}`) shrinks the page image while the
        text lines keep their pixel coordinates, and the publisher's `z-index:-1` puts the image
        behind <body>, so any opaque reader background hides every illustration.
        """
        width, height = size
        return ("html,body{margin:0!important;padding:0!important;background-color:transparent!important;}"
                "#sbo-rt-content .t,#sbo-rt-content .t *{background-color:transparent!important;}"
                "#sbo-rt-content{position:relative!important;isolation:isolate;overflow:hidden;"
                "width:%(w)spx;height:%(h)spx;}"
                "#sbo-rt-content img{position:absolute!important;left:0!important;top:0!important;"
                "width:%(w)spx!important;height:%(h)spx!important;max-width:none!important;"
                "z-index:0!important;}" % {"w": width, "h": height})


    @staticmethod
    def _format_px(value):
        text = ("%.3f" % value).rstrip("0").rstrip(".")
        return (text if text not in ("", "-0") else "0") + "px"


    @staticmethod
    def bake_fixed_layout_scale(css_text):
        """Apply the publisher's `transform: scale(.25)` to the numbers instead of the transform.

        PDF-derived books lay each text line out at 4x size and shrink it with a CSS transform.
        Readers that ignore, clamp or re-scale transforms then draw every line four times too
        large. Multiplying font-size and spacing by the scale and dropping the transform renders
        the same in a browser and does not depend on transform support. Positions (left/top) are
        untouched because the transform origin is the top-left corner.
        """
        if not SafariBooks.BAKE_SCALE_RE.search(css_text or ""):
            return css_text

        scale = SafariBooks.FIXED_LAYOUT_SCALE

        def scale_length(match):
            return SafariBooks._format_px(float(match.group(1)) * scale)

        def rewrite(match):
            selector, body = match.group(1), match.group(2)
            if selector.lstrip().startswith("@"):
                return match.group(0)

            declarations = []
            for item in body.split(";"):
                if ":" not in item:
                    if item.strip():
                        declarations.append(item)
                    continue
                name, value = item.split(":", 1)
                key = name.strip().lower()
                if key.endswith("transform") and SafariBooks.BAKE_SCALE_RE.search(value):
                    def keep_stretch(scale_match):
                        # scale(a,.25): the .25 is the shrink baked into the numbers, a/.25 is what is left
                        pair = SafariBooks.BAKE_ANISOTROPIC_RE.match(scale_match.group(0))
                        if not pair:
                            return ""
                        return "scale(%g,%g)" % (round(float(pair.group(1)) / scale, 3),
                                                 round(float(pair.group(2)) / scale, 3))

                    value = SafariBooks.BAKE_SCALE_RE.sub(keep_stretch, value).strip()
                    if not value:
                        continue
                elif (key in SafariBooks.BAKE_LENGTH_PROPS
                      and SafariBooks.BAKE_TEXT_SELECTOR_RE.search(selector)):
                    value = re.sub(r"(-?\d*\.?\d+)px", scale_length, value)
                elif (key == "color" and "!important" not in value
                      and SafariBooks.BAKE_TEXT_SELECTOR_RE.search(selector)):
                    # Text sits on a page IMAGE, so a reader forcing its own theme colour makes it
                    # unreadable (white on white). An id/class selector plus !important out-ranks a
                    # reader's `body *{color:...!important}` override.
                    value = value.strip() + "!important"
                declarations.append("%s:%s" % (name, value))
            return "%s{%s}" % (selector, ";".join(declarations))

        return SafariBooks.BAKE_RULE_RE.sub(rewrite, css_text)


    def prepare_fixed_layout(self):
        """Swap in the fixed-layout base stylesheet and give every page an EPUB 3 viewport."""
        if not self.fixed_layout:
            return

        sheets = [p for p in self.plan_stylesheets(self.plan) if os.path.isfile(self.destination(p))]
        size = self.DEFAULT_PAGE_SIZE
        for path in sheets:
            with open(self.destination(path), encoding="utf-8", errors="replace") as css_file:
                match = self.PAGE_SIZE_RE.search(css_file.read())
            if match:
                size = (int(match.group(1)), int(match.group(2)))
                break

        self.page_size = size
        for path in sheets:
            with open(self.destination(path), encoding="utf-8", errors="replace") as css_file:
                original = css_file.read()

            baked = self.bake_fixed_layout_scale(original)
            if baked != original:
                self.save_text(path, baked)

        os.makedirs(self.css_path, exist_ok=True)
        with open(os.path.join(self.css_path, "Style_Base.css"), "w", encoding="utf-8") as base:
            base.write(self.fixed_layout_stylesheet(size))

        viewport = "<meta name=\"viewport\" content=\"width=%d, height=%d\"/>\n" % size
        for entry in self.plan["chapter"]:
            file_path = self.destination(entry["path"])
            if not os.path.isfile(file_path) or entry["path"].endswith("nav.xhtml"):
                continue

            with open(file_path, encoding="utf-8") as page_file:
                page = page_file.read()
            if "name=\"viewport\"" in page or "</head>" not in page:
                continue

            self.save_text(entry["path"], page.replace("</head>", viewport + "</head>", 1))


    def should_polish(self, args):
        # ebook-polish prunes "unused" CSS and recompresses images; the positioned-text CSS and
        # per-page images of a fixed-layout book are exactly what it must not touch.
        return not args.no_optimize_images and not self.fixed_layout


    @staticmethod
    def polish_epub(epub_path, display):
        binary = shutil.which("ebook-polish")
        if not binary:
            display.info("Calibre's `ebook-polish` not found; skipping optional CSS/image polish step.")
            return False

        tmp_path = epub_path + ".polishing"
        result = subprocess.run([binary, "-u", "-i", epub_path, tmp_path], capture_output=True, text=True)
        if result.returncode != 0:
            display.error("Calibre polish failed: %s" % result.stderr)
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)

            return False

        os.replace(tmp_path, epub_path)
        return True


    @staticmethod
    def optional_dc_element(tag, value):
        """`<dc:tag>value</dc:tag>\n`, or nothing when value is blank.

        Empty Dublin Core elements make readers show "Unknown" instead of leaving the field unset.
        """
        value = (value or "").strip()
        return "<dc:{0}>{1}</dc:{0}>\n".format(tag, escape(value)) if value else ""


    # ------------------------------------------------------------------ package document
    @staticmethod
    def manifest_media_type(path):
        ext = posixpath.splitext(path)[1].lower()
        return (SafariBooks.OTHER_MEDIA_TYPES.get(ext) or SafariBooks.FONT_MEDIA_TYPES.get(ext)
                or mimetypes.guess_type(path)[0] or "application/octet-stream")

    @staticmethod
    def opf_has_nav(opf_bytes):
        root = etree.fromstring(opf_bytes)
        return any("nav" in (i.get("properties") or "").split()
                   for i in root.findall("{%s}manifest/{%s}item" % (SafariBooks.OPF_NS, SafariBooks.OPF_NS)))

    @staticmethod
    def nav_from_ncx(ncx_bytes, ncx_path, nav_path, title):
        """EPUB 3 nav document built from the publisher's NCX; None when the NCX has no entries."""
        root = etree.fromstring(ncx_bytes)
        ns = {"n": SafariBooks.NCX_NS}
        nav_dir = posixpath.dirname(nav_path) or "."

        def walk(points):
            markup = "<ol>\n"
            for point in points:
                content = point.find("n:content", ns)
                label = " ".join(point.xpath("string(n:navLabel/n:text)", namespaces=ns).split())
                if content is None or not content.get("src"):
                    continue

                target, _, fragment = content.get("src").partition("#")
                href = quote(posixpath.relpath(
                    posixpath.normpath(posixpath.join(posixpath.dirname(ncx_path), unquote(target))), nav_dir))
                if fragment:
                    href += "#" + fragment

                markup += "<li><a href=\"{0}\">{1}</a>".format(escape(href, quote=True), escape(label))
                children = point.findall("n:navPoint", ns)
                if children:
                    markup += "\n" + walk(children)

                markup += "</li>\n"

            return markup + "</ol>\n"

        points = root.findall("n:navMap/n:navPoint", ns)
        if not points:
            return None

        return SafariBooks.NAV_XHTML.format(escape(title), walk(points))

    @staticmethod
    def patch_opf_document(opf_bytes, opf_path, oebps_path, book_info, rename_map=None, fixed_layout=False,
                           nav_path=None, now=None):
        """Bring the publisher's OPF in line with what was actually downloaded.

        Title and language become those of the edition downloaded (translated editions keep the original
        edition's metadata in the OPF), blank Dublin Core elements go, missing creator/publisher are filled
        from the book info, the manifest is reconciled with the files on disk (converted images renamed,
        pruned files dropped, our own files added) and a fixed-layout book gets its EPUB 3 metadata."""
        opf = "{%s}" % SafariBooks.OPF_NS
        dc = "{%s}" % SafariBooks.DC_NS
        ns = {"opf": SafariBooks.OPF_NS, "dc": SafariBooks.DC_NS}
        rename_map = rename_map or {}
        root = etree.fromstring(opf_bytes)
        metadata, manifest, spine = (root.find("opf:" + n, ns) for n in ("metadata", "manifest", "spine"))
        if metadata is None or manifest is None or spine is None:
            raise ValueError("the package document has no metadata, manifest or spine")

        def set_first(tag, value, property_name):
            found = metadata.findall("dc:" + tag, ns)
            if found:
                found[0].text = value
            else:
                created = etree.Element(dc + tag)
                created.text = value
                metadata.insert(0, created)

            for meta in metadata.findall("opf:meta", ns):
                if meta.get("property") == property_name:
                    meta.text = value

        title = (book_info.get("title") or "").strip()
        if title:
            set_first("title", title, "dcterms:title")

        language = (book_info.get("language") or "").strip()
        if language:
            set_first("language", language, "dcterms:language")

        for element in list(metadata):
            if isinstance(element.tag, str) and element.tag.startswith(dc) and len(element) == 0 \
                    and not (element.text or "").strip():
                metadata.remove(element)

        added_after_title = []

        def add_after_title(tag, value, **attributes):
            """Insert right after the title, in call order (several authors keep their order)."""
            element = etree.Element(dc + tag, attributes)
            element.text = value
            titles = metadata.findall("dc:title", ns)
            anchor = added_after_title[-1] if added_after_title else (titles[-1] if titles else None)
            metadata.insert(list(metadata).index(anchor) + 1 if anchor is not None else 0, element)
            added_after_title.append(element)

        if not any((e.text or "").strip() for e in metadata.findall("dc:creator", ns)):
            for author in book_info.get("authors") or []:
                name = (author.get("name") or "").strip()
                if name and name != "n/a":
                    add_after_title("creator", name)

        publishers = ", ".join((p.get("name") or "").strip() for p in book_info.get("publishers") or []
                               if (p.get("name") or "").strip())
        if publishers and not any((e.text or "").strip() for e in metadata.findall("dc:publisher", ns)):
            add_after_title("publisher", publishers)

        opf_dir = posixpath.dirname(opf_path)
        spine_ids = {ref.get("idref") for ref in spine.findall("opf:itemref", ns)}
        known = set()
        for item in list(manifest.findall("opf:item", ns)):
            path = SafariBooks.resolve_local(opf_path, item.get("href"))
            if path is None:
                continue

            if path in rename_map:
                path = rename_map[path]
                item.set("href", quote(posixpath.relpath(path, opf_dir or ".")))
                item.set("media-type", "image/jpeg")

            if not os.path.isfile(os.path.join(oebps_path, *path.split("/"))):
                if item.get("id") in spine_ids:
                    raise ValueError("spine item %s is missing from the download" % path)

                manifest.remove(item)
                continue

            known.add(path)

        ids = {i.get("id") for i in manifest.findall("opf:item", ns)}
        for dirpath, dirnames, filenames in os.walk(oebps_path):
            dirnames.sort()
            for name in sorted(filenames):
                path = os.path.relpath(os.path.join(dirpath, name), oebps_path).replace(os.sep, "/")
                if path == opf_path or path in known or name.endswith((".part", ".tmp")):
                    continue

                item_id = "sb_" + re.sub(r"[^A-Za-z0-9_.-]", "_", path)
                while item_id in ids:
                    item_id += "_"

                ids.add(item_id)
                attributes = {"id": item_id, "href": quote(posixpath.relpath(path, opf_dir or ".")),
                              "media-type": SafariBooks.manifest_media_type(path)}
                if nav_path and path == nav_path:
                    attributes["properties"] = "nav"

                etree.SubElement(manifest, opf + "item", attributes)
                known.add(path)

        items = {i.get("id"): i for i in manifest.findall("opf:item", ns)}
        for meta in list(metadata.findall("opf:meta", ns)):
            if meta.get("name") == "cover" and meta.get("content") not in items:
                # <meta name="cover"> must name a manifest item; a dangling one shows no cover at all.
                candidate = next((i for i in items.values() if "cover-image" in (i.get("properties") or "").split()),
                                 None)
                if candidate is None:  # explicit test: an <item/> with no children is falsy in lxml
                    candidate = next((i for i in items.values()
                                      if (i.get("media-type") or "").startswith("image/")
                                      and "cover" in (i.get("href") or "").lower()), None)
                if candidate is not None:
                    meta.set("content", candidate.get("id"))
                else:
                    metadata.remove(meta)

        if fixed_layout:
            root.set("version", "3.0")

            def ensure_property(name, value):
                for meta in metadata.findall("opf:meta", ns):
                    if meta.get("property") == name:
                        meta.text = value if name.startswith("rendition:") else meta.text
                        return

                created = etree.SubElement(metadata, opf + "meta", {"property": name})
                created.text = value

            ensure_property("dcterms:modified",
                            (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"))
            ensure_property("rendition:layout", "pre-paginated")
            ensure_property("rendition:spread", "none")
            for meta in metadata.findall("opf:meta", ns):
                cover = items.get(meta.get("content")) if meta.get("name") == "cover" else None
                if cover is not None and "cover-image" not in (cover.get("properties") or "").split():
                    cover.set("properties", ((cover.get("properties") or "") + " cover-image").strip())

            if not any("nav" in (i.get("properties") or "").split() for i in items.values()):
                raise ValueError("a fixed-layout book needs a navigation document and none was found or built")

        return etree.tostring(root, xml_declaration=True, encoding="utf-8")


    @staticmethod
    def write_epub_archive(book_path, epub_path):
        """Zip book_path into an OCF-compliant EPUB: stored `mimetype` first, no dir entries."""
        tmp_path = epub_path + ".tmp"
        with zipfile.ZipFile(tmp_path, "w") as z:
            z.write(os.path.join(book_path, "mimetype"), "mimetype", compress_type=zipfile.ZIP_STORED)
            for dirpath, dirnames, filenames in os.walk(book_path):
                dirnames.sort()
                for name in sorted(filenames):
                    full = os.path.join(dirpath, name)
                    arcname = os.path.relpath(full, book_path).replace(os.sep, "/")
                    # Skip mimetype (already written first) and any EPUB left at the top
                    # level by a previous run, which would otherwise be packed into this one.
                    if arcname == "mimetype" or ("/" not in arcname and name.endswith((".epub", ".tmp"))):
                        continue
                    z.write(full, arcname, compress_type=zipfile.ZIP_DEFLATED)
        os.replace(tmp_path, epub_path)


    def download_and_build(self):
        """Everything between "the plan is known" and "the EPUB is on disk"."""
        self.display.info("Downloading book documents... (%s files)" % len(self.plan["documents"]), state=True)
        self.collect_documents()

        self.display.info("Downloading book CSSs... (%s files)" % len(self.plan["stylesheet"]), state=True)
        self.collect_css()

        self.display.info("Downloading book fonts...", state=True)
        self.collect_fonts()

        self.display.info("Downloading book images...", state=True)
        self.collect_images()

        if not self.args.no_optimize_images:
            self.display.info("Optimizing images...", state=True)
            self.finalize_images()

        self.prepare_fixed_layout()

        self.display.info("Creating EPUB file...", state=True)
        self.create_epub()

    def create_epub(self):
        open(os.path.join(self.BOOK_PATH, "mimetype"), "w").write("application/epub+zip")
        meta_info = os.path.join(self.BOOK_PATH, "META-INF")
        if os.path.isdir(meta_info):
            self.display.log("META-INF directory already exists: %s" % meta_info)

        else:
            os.makedirs(meta_info)

        opf_file = self.destination(self.opf_path)
        with open(opf_file, "rb") as opf:
            opf_bytes = opf.read()

        nav_path = None
        if self.fixed_layout and not self.opf_has_nav(opf_bytes) and self.ncx_path:
            candidate = posixpath.join(posixpath.dirname(self.opf_path), "nav.xhtml")
            with open(self.destination(self.ncx_path), "rb") as ncx:
                nav = self.nav_from_ncx(ncx.read(), self.ncx_path, candidate, self.book_title)

            if nav is None:
                self.display.warning("The table of contents is empty; the fixed-layout EPUB has no nav document.")
            else:
                self.save_text(candidate, nav)
                nav_path = candidate

        try:
            patched = self.patch_opf_document(
                opf_bytes, self.opf_path, self.oebps_path, self.book_info, self.rename_map,
                self.fixed_layout, nav_path
            )
        except ValueError as invalid:
            self.display.exit("Package document: %s" % invalid)

        with open(opf_file, "wb") as opf:
            opf.write(patched)

        open(os.path.join(meta_info, "container.xml"), "wb").write(
            self.CONTAINER_XML.format(self.opf_path).encode("utf-8", "xmlcharrefreplace")
        )

        epub_path = os.path.join(self.BOOK_PATH, self.book_id) + ".epub"
        self.write_epub_archive(self.BOOK_PATH, epub_path)

        if self.should_polish(self.args):
            self.polish_epub(epub_path, self.display)

    def create_dirs(self):
        if os.path.isdir(self.BOOK_PATH):
            self.display.log("Book directory already exists: %s" % self.BOOK_PATH)

        else:
            os.makedirs(self.BOOK_PATH)

        self.oebps_path = os.path.join(self.BOOK_PATH, "OEBPS")
        if not os.path.isdir(self.oebps_path):
            self.display.book_ad_info = True
            os.makedirs(self.oebps_path)

        self.css_path = os.path.join(self.oebps_path, self.OWN_STYLES_DIR)
        os.makedirs(self.css_path, exist_ok=True)

        open(os.path.join(self.css_path, "Style_Base.css"), "w", encoding="utf-8").write(self.BASE_STYLE_CSS)
        if self.args.kindle:
            open(os.path.join(self.css_path, "Style_Kindle.css"), "w", encoding="utf-8").write(self.KINDLE_STYLE_CSS)


if __name__ == "__main__":
    configure_console()
    arguments = argparse.ArgumentParser(prog="safaribooks.py",
                                        description="Download and generate an EPUB of your favorite books"
                                                    " from Safari Books Online.",
                                        add_help=False,
                                        allow_abbrev=False)

    login_arg_group = arguments.add_mutually_exclusive_group()
    login_arg_group.add_argument(
        "--cred", metavar="<EMAIL:PASS>", default=False,
        help="Credentials used to perform the auth login on Safari Books Online."
             " Es. ` --cred \"account_mail@mail.com:password01\" `."
    )
    login_arg_group.add_argument(
        "--login", action='store_true',
        help="Prompt for credentials used to perform the auth login on Safari Books Online."
    )

    arguments.add_argument(
        "--no-cookies", dest="no_cookies", action='store_true',
        help="Prevent your session data to be saved into `cookies.json` file."
    )
    arguments.add_argument(
        "--kindle", dest="kindle", action='store_true',
        help="Add some CSS rules that block overflow on `table` and `pre` elements."
             " Use this option if you're going to export the EPUB to E-Readers like Amazon Kindle."
    )
    arguments.add_argument(
        "--preserve-log", dest="log", action='store_true', help="Leave the `info_XXXXXXXXXXXXX.log`"
                                                                " file even if there isn't any error."
    )
    arguments.add_argument(
        "--no-optimize-images", dest="no_optimize_images", action='store_true',
        help="Skip converting images to JPEG, pruning unused images, and running Calibre's"
             " `ebook-polish` (unused CSS removal + lossless image compression) at the end of the download."
    )
    arguments.add_argument(
        "--no-optimize-css", dest="no_optimize_css", action='store_true',
        help="Skip removing the `color` CSS property from stylesheets and inline `style` attributes"
             " (kept to avoid breaking E-Reader light/dark themes by default)."
    )
    arguments.add_argument("--help", action="help", default=argparse.SUPPRESS, help='Show this help message.')
    arguments.add_argument(
        "bookid", metavar='<BOOK ID>',
        help="Book digits ID that you want to download. You can find it in the URL (X-es):"
             " `" + SAFARI_BASE_URL + "/library/view/book-name/XXXXXXXXXXXXX/`"
    )

    args_parsed = arguments.parse_args()
    if args_parsed.cred or args_parsed.login:
        print("WARNING: Due to recent changes on ORLY website, \n" \
                "the `--cred` and `--login` options are temporarily disabled.\n"
                "    Please use the `cookies.json` file to authenticate your account.\n"
                "    See: https://github.com/lorenzodifuccia/safaribooks/issues/358")
        arguments.exit()
        
        # user_email = ""
        # pre_cred = ""

        # if args_parsed.cred:
        #     pre_cred = args_parsed.cred

        # else:
        #     user_email = input("Email: ")
        #     passwd = getpass.getpass("Password: ")
        #     pre_cred = user_email + ":" + passwd

        # parsed_cred = SafariBooks.parse_cred(pre_cred)

        # if not parsed_cred:
        #     arguments.error("invalid credential: %s" % (
        #         args_parsed.cred if args_parsed.cred else (user_email + ":*******")
        #     ))

        # args_parsed.cred = parsed_cred

    else:
        if args_parsed.no_cookies:
            arguments.error("invalid option: `--no-cookies` is valid only if you use the `--cred` option")

    SafariBooks(args_parsed)
    # Hint: do you want to download more then one book once, initialized more than one instance of `SafariBooks`...
    sys.exit(0)
