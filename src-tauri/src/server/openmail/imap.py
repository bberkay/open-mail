import imaplib, threading, re, base64, email, time, select
from typing import List, Literal
from datetime import datetime

#from bs4 import BeautifulSoup # beautifulsoup4>=4.12.3

from .utils import extract_domain, choose_positive, contains_non_ascii, convert_to_imap_date, make_size_human_readable
from .types import SearchCriteria, LoginException

IDLE_TIMEOUT = 29 * 60
FOLDER_FLAG_NAMES =  [b'\\All', b'\\Archive', b'\\Drafts', b'\\Flagged', b'\\Junk', b'\\Sent', b'\\Trash']
CID_RE_COMPILE = re.compile(r'<img src="cid:([^"]+)"')
IMAP_SERVERS = {
    "gmail": "imap.gmail.com",
    "yahoo": "imap.mail.yahoo.com",
    "outlook": "outlook.office365.com",
    "hotmail": "outlook.office365.com",
    'yandex': 'imap.yandex.com',
}

class IMAP(imaplib.IMAP4_SSL):
    def __init__(self, email_address: str, password: str, host: str = "", port: int = 993, try_limit: int = 3, timeout: int = 30):
        super().__init__(
            host or self.__find_imap_server(email_address),
            port or 993,
            timeout=choose_positive(timeout, 30)
        )
        self.login(email_address, password, choose_positive(try_limit, 3))

        self.__selected_folder = None
        self.__is_selected_folder_readonly = False
        self.__idle_thread = None
        self.__idle_event = threading.Event()
        self.__is_idle = False

    def __find_imap_server(self, email_address: str) -> str:
        try:
            return IMAP_SERVERS[extract_domain(email_address)]
        except KeyError:
            raise Exception("Unsupported email domain")

    def is_logged_in(self) -> bool:
        return self.state == "AUTH" or self.state == "SELECTED"

    def login(self, user: str, password: str, try_limit: int = 3) -> tuple[str, any]:
        for _ in range(try_limit):
            try:
                if not self.is_logged_in():
                    status, response = None, None
                    if contains_non_ascii(user) or contains_non_ascii(password):
                        status, response = self.authenticate("PLAIN", lambda x: bytes("\x00" + user + "\x00" + password, "utf-8"))
                    else:
                        status, response = super().login(user, password)
                    self._simple_command('ENABLE', 'UTF8=ACCEPT')
                    return status, response
                return "OK", "Already logged in"
            except Exception as e:
                try_limit -= 1
                if try_limit == 0:
                    raise Exception("3 failed login attempts. Error: " + str(e))

    def logout(self) -> tuple[str, any]:
        if self.is_logged_in():
            if self.state == "SELECTED":
                self.close()
            return super().logout()

    def __handle_conn(func):
        def wrapper(self, *args, **kwargs):
            try:
                # FIXME: IDLE state is not handled properly
                #if not self.is_logged_in():
                #    raise LoginException("You are not logged in(or connection is lost). Please login first.")
                was_idle_before_func = self.__is_idle
                if self.__is_idle:
                    self.done()
                response = func(self, *args, **kwargs)
                if was_idle_before_func and self.__is_idle:
                    self.idle()
                return response
            except Exception as e:
                #self.__imap.logout()
                return False, str(e)
        return wrapper

    def get_folder_name_by_flag_name(self, flag_name: bytes) -> bytes | None:
        """
        Returns folder name by its flag name.
        This method is useful when the client's folder name is in a different language.
        For example, if the client's inbox's name is "Gelen Kutusu" this method will return
        "INBOX" if the flag name is b'\\Inbox' or "Çöp Kutusu" if the flag name is b'\\Trash'
        """
        if flag_name not in FOLDER_FLAG_NAMES:
            return None

        status, folders_as_bytes = self.list()
        if status == "OK":
            for folder_as_bytes in folders_as_bytes:
                if flag_name == folder_as_bytes:
                    return folder_as_bytes
        return None

    def __encode_folder(self, folder: str) -> bytes:
        return ('"' + folder + '"').encode("utf-8")

    def __decode_folder(self, folder: bytes) -> str:
        # Most of the servers return folder name as b'(\\HasNoChildren) "/" "INBOX"'
        # But some servers like yandex return folder name as b'(\\HasNoChildren) "|" "INBOX"'
        # So we're replacing "|" with "/" to make it consistent
        return folder.decode().replace(' "|" ', ' "/" ').split(' "/" ')[1].replace('"', '')

    def select(self, mailbox: str = "INBOX", readonly: bool = False) -> tuple[str, list[bytes | None]]:
        if self.__selected_folder != mailbox or self.__is_selected_folder_readonly != readonly:
            self.__selected_folder = mailbox
            self.__is_selected_folder_readonly = readonly
            return super().select(self.__encode_folder(mailbox), readonly)
        return "OK", [None]

    def idle(self) -> None:
        self.select('INBOX')
        self.__idle_event.clear()
        self.__idle_thread = threading.Thread(target=self.__idle)
        self.__idle_thread.start()

    def done(self) -> None:
        self.__done()
        self.__idle_event.set()
        self.unselect() # This might be unnecessary after selected_folder property is added

    def __readline_timeout(self, timeout:int = 3):
        self.sock.settimeout(0)
        self.sock.setblocking(False)
        if select.select([self.sock], [], [], timeout)[0]:
            return self.sock.recv(4096)
        else:
            return None

    def __idle(self) -> None:
        def reset_socket_to_default():
            self.socket().settimeout(None)
            self.socket().setblocking(True)

        def handle_idle_response(response):
            if b'* BYE' in response:
                self.__idle()
            if b'EXISTS' in response:
                # Do something
                self.__done()

        try:
            self.send(b"%s IDLE\r\n" % self._new_tag())
            response = self.readline()
            if response == b'+ idling\r\n':
                self.__is_idle = True
            else:
                raise Exception("IDLE command failed")

            start_time = time.time()
            while not self.__idle_event.is_set():
                response = self.__readline_timeout(timeout=5)
                if response:
                    reset_socket_to_default()
                    handle_idle_response(response)
                    break
                if time.time() - start_time > IDLE_TIMEOUT:
                    break
        finally:
            reset_socket_to_default()
            self.__done()
            self.__idle()

    def __done(self) -> None:
        if not self.__is_idle:
            return

        self.send(b"DONE\r\n")
        response = self.readline()
        if b"OK" in response:
            self.__is_idle = False

    @__handle_conn
    def get_folders(self) -> list:
        return [self.__decode_folder(i) for i in self.list()[1] if b'\\NoSelect' not in i]

    @__handle_conn
    def get_email_flags(self, uid: str) -> list:
        if self.state != "SELECTED":
            raise Exception("Folder should be selected before fetching flags")

        flags = self.uid('FETCH', uid, '(FLAGS)')[1][0]
        if flags:
            flags = flags.decode()
            flags = re.findall(r'\\([a-zA-Z]+)', flags)
        return flags or []

    def __build_search_criteria_query(self, search_criteria: SearchCriteria) -> str:
        """
            Preparing to convert search_json to search_criteria string:
            https://datatracker.ietf.org/doc/html/rfc9051#name-search-command
        """

        def recursive_or_query(criteria: str, search_keys: List[str]) -> str:
            """
            Example:
                criteria = "FROM"
                search_keys = ["johndoe@mail.com", "janedoe@mail.com", "person@mail.com"]
                return: 'OR (FROM "johndoe@mail.com") (OR (FROM "janedoe@mail.com") (FROM "person@mail.com"))'
            """
            query = ''
            len_search_keys = len(search_keys)
            if len_search_keys == 1:
                return f'{criteria} "{search_keys[0]}"'

            mid = len_search_keys // 2
            left_part = recursive_or_query(criteria, search_keys[:mid])
            right_part = recursive_or_query(criteria, search_keys[mid:])

            return query + f'OR ({left_part}) ({right_part})'

        def add_criterion(criteria: str, value: str | list | None, seperate_with_or: bool = False) -> str:
            if not value:
                return ''

            if isinstance(value, list):
                if criteria == '':
                    # value=["Flagged", "Seen", "Answered"]
                    return ' '.join([i.upper() for i in value])

                if len(value) <= 1:
                    return f' ({criteria} "{value[0]}")'

            if seperate_with_or and len(value) > 1:
                criteria = ''
                value = recursive_or_query(criteria, value)

            return f' ({criteria} "{value}")'

        search_criteria_query = ''
        search_criteria_query += add_criterion('FROM', search_criteria.senders, len(search_criteria.senders) > 1)
        search_criteria_query += add_criterion('TO', search_criteria.receivers, len(search_criteria.receivers) > 1)
        search_criteria_query += add_criterion("SUBJECT", search_criteria.subject)
        search_criteria_query += add_criterion("SINCE", search_criteria.since)
        search_criteria_query += add_criterion("BEFORE", search_criteria.before)
        search_criteria_query += add_criterion("TEXT", search_criteria.include)
        search_criteria_query += add_criterion("NOT TEXT", search_criteria.exclude)
        search_criteria_query += add_criterion('', search_criteria.flags)
        return search_criteria_query.strip()

    @__handle_conn
    def get_emails(
        self,
        folder: str = "inbox",
        search: str | SearchCriteria = "ALL",
        offset: int = 0
    ) -> dict:
        self.select(folder, readonly=True)

        search_criteria_query = ''
        must_have_attachment = False
        if isinstance(search, SearchCriteria):
            must_have_attachment = search.has_attachments
            search_criteria_query = self.__build_search_criteria_query(search) or 'ALL'
        else:
            search_criteria_query = search or 'ALL'

        _, uids = self.uid('search', None, search_criteria_query.encode("utf-8") if search_criteria_query else 'ALL')
        uids = uids[0].split()[::-1]

        if len(uids) == 0:
            return {"folder": folder, "emails": [], "total": 0}

        emails = []
        for uid in uids[offset: offset + 10]:
            """
            _, data = M.fetch(num, '(BODY.PEEK[HEADER.FIELDS (CONTENT-TYPE)])')
            if b"multipart/mixed" in data[0][1]:
                print("Found multipart/mixed: ", num
            """
            _, message = self.uid('fetch', uid, '(RFC822)')
            message = email.message_from_bytes(message[0][1], policy=email.policy.default)

            payload = [message]
            if message.is_multipart():
                if must_have_attachment and message.get_content_type() != "multipart/mixed":
                    continue
                payload = message.walk()

            body = ""
            is_body_html = False
            for part in payload:
                content_type = part.get_content_type()
                file_name = part.get_filename()

                is_body_html = content_type == "text/html"
                if (file_name is None and content_type == "text/plain") or (is_body_html and not body):
                    body = part.get_payload(decode=True)
                    body = body.decode(part.get_content_charset() or "utf-8") if body else ""

            #body = BeautifulSoup(body, "html.parser").get_text() if is_body_html else body
            #body = re.sub(r'<br\s*/?>', '', body).strip() if body != b'' else ""
            #body = re.sub(r'[\n\r\t]+| +', ' ', body).strip()

            emails.append({
                "uid": uid.decode(),
                "from": message["From"],
                "to": message["To"] if "To" in message else "",
                "subject": message["Subject"],
                "body_short": (body if body != "" else "No Content") if len(body) < 50 else body[:50] + "...",
                "date": datetime.strptime(message["Date"], "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d %H:%M:%S"),
                "flags": self.get_email_flags(uid) or []
            })

        return {"folder": folder, "emails": emails, "total": len(uids)}

    @__handle_conn
    def get_email_content(
        self,
        uid: str,
        folder: str = "inbox"
    ) -> dict:
        self.select(folder, readonly=True)

        _, message = self.uid('fetch', uid, '(RFC822)')
        message = email.message_from_bytes(message[0][1], policy=email.policy.default)

        body, attachments = "", []
        for part in (message.walk() if message.is_multipart() else [message]):
            content_type = part.get_content_type()
            file_name = part.get_filename()
            if file_name:
                attachments.append({
                    "cid": part.get("X-Attachment-Id"),
                    "name": file_name,
                    "data": base64.b64encode(part.get_payload(decode=True)).decode("utf-8", errors="ignore"),
                    "size": make_size_human_readable(len(part.get_payload(decode=True))),
                    "type": content_type
                })
            elif content_type == "text/html" or (content_type == "text/plain" and not body):
                body = part.get_payload(decode=True)
                if body:
                    body = body.decode(part.get_content_charset())

        if attachments:
            for match in CID_RE_COMPILE.finditer(body):
                cid = match.group(1)
                for attachment in attachments:
                    if cid in attachment["name"] or cid in attachment["cid"]:
                        body = body.replace(f'cid:{cid}', f'data:{attachment["type"]};base64,{attachment["data"]}')

        if "Seen" not in self.get_email_flags(uid):
            self.mark_email(uid, "seen", folder)

        return {
            "uid": uid,
            "from": message["From"],
            "to": message["To"] if "To" in message else "",
            "subject": message["Subject"],
            "body": body,
            "date": datetime.strptime(message["Date"], "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d %H:%M:%S"),
            "flags": self.get_email_flags(uid) or [],
            "attachments": attachments
        }

    @__handle_conn
    def mark_email(
        self,
        uid: str,
        mark: str,
        folder: str = "inbox"
    ) -> bool:
        self.select(folder)

        mark = mark.lower()
        mark_type = "-" if mark[0] + mark[1] == "un" else "+"
        mark = mark[2:] if mark_type == "-" else mark
        command = mark_type + "FLAGS"

        # https://datatracker.ietf.org/doc/html/rfc9051#name-flags-message-attribute
        mark_map = {
            "flagged": "\\Flagged",
            "seen": "\\Seen",
            "answered": "\\Answered",
            #"deleted": "\\Deleted",
            #"draft": "\\Draft",
            #"spam": "\\Spam"
        }

        if mark not in mark_map:
            raise ValueError(f"Invalid mark: {mark}")

        self.uid('STORE', uid, command, mark_map[mark])
        self.expunge()
        return True

    @__handle_conn
    def move_email(self, uid: str, source_folder: str, destination_folder: str) -> bool:
        self.select(source_folder)
        self.uid('MOVE', uid, self.__encode_folder(destination_folder))
        self.expunge()
        return True

    @__handle_conn
    def copy_email(self, uid: str, source_folder: str, destination_folder: str) -> bool:
        self.select(source_folder)
        self.uid('COPY', uid, self.__encode_folder(destination_folder))
        self.expunge()
        return True

    @__handle_conn
    def delete_email(self, uid: str, folder: str) -> bool:
        trash_mailbox_name = self.__decode_folder(self.get_folder_name_by_flag_name(b"\\Trash"))
        if folder != trash_mailbox_name:
            # If the email is not in the trash folder, move it to the trash folder
            self.move_email(uid, folder, trash_mailbox_name)

        self.select(trash_mailbox_name)
        self.uid('STORE', uid, '+FLAGS', '\\Deleted')
        self.expunge()
        return True

    @__handle_conn
    def create_folder(self, folder_name: str, parent_folder: str | None = None) -> bool:
        if parent_folder:
            folder_name = f"{parent_folder}/{folder_name}"
        return self.create(self.__encode_folder(folder_name))

    @__handle_conn
    def delete_folder(self, folder_name: str) -> bool:
        return self.delete(self.__encode_folder(folder_name))

    @__handle_conn
    def move_folder(self, folder_name: str, destination_folder: str) -> bool:
        if "/" in folder_name:
            destination_folder = f"{destination_folder}/{folder_name.split("/")[-1]}"
        return self.rename(self.__encode_folder(folder_name), self.__encode_folder(destination_folder))

    @__handle_conn
    def rename_folder(self, folder_name: str, new_folder_name: str) -> bool:
        if "/" in folder_name:
            new_folder_name = folder_name.replace(folder_name.split("/")[-1], new_folder_name)
        return self.rename(self.__encode_folder(folder_name), self.__encode_folder(new_folder_name))
