import re, base64, json
from datetime import datetime
from bs4 import BeautifulSoup
from typing import List, TypedDict

import email
from email.mime.image import MIMEImage
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart

from .utils import decode_modified_utf7, encode_modified_utf7, convert_to_imap_date, check_json_value
from .imap import IMAP
from .smtp import SMTP

class SearchCriteria(TypedDict):
    from_: List[str]
    to: List[str]
    subject: str
    since: str
    before: str
    has_attachments: bool
    flags: List[str]
    include: str
    exclude: str
    
class OpenMail:
    def __init__(self, email_address: str, password: str, imap_port: int = 993, smtp_port: int = 587, try_limit: int = 3, timeout: int = 30):
        self.__email_address = email_address
        self.__imap = IMAP(email_address, password, imap_port, try_limit, timeout)
        self.__smtp = SMTP(email_address, password, smtp_port, try_limit, timeout)
    
    def __handle_errors(func):
        def wrapper(self, *args, **kwargs):
            try:
                return func(self, *args, **kwargs)
            except Exception as e:
                return False, str(e)
        return wrapper
    
    @__handle_errors
    def __handle_smtp_conn(func):
        def wrapper(self, *args, **kwargs):
            if not self.__smtp.is_logged_in():
                self.__smtp.login()
            response = func(self, *args, **kwargs)
            self.__smtp.quit()
            return response
        return wrapper
    
    @__handle_errors
    def __handle_imap_conn(func):
        def wrapper(self, *args, **kwargs):
            if not self.__imap.is_logged_in():
                self.__imap.login()
            response = func(self, *args, **kwargs)
            self.__imap.logout()
            return response
        return wrapper
    
    def __encode_folder_name(self, folder: str) -> str:
        return '"' + encode_modified_utf7(folder) + '"'
    
    def __decode_folder_name(self, folder: str) -> str:
        return decode_modified_utf7(folder.decode().split(' "/" ')[1].replace('"', ''))
           
    @__handle_smtp_conn
    def __send_email(self, receiver_emails: str, subject: str, body: str, attachments: list = None, msg_meta: dict = None) -> tuple[bool, str]:
        msg = MIMEMultipart()
        msg['From'] = self.__email_address
        msg['To'] = receiver_emails
        msg['Subject'] = subject
        if msg_meta:
            for key, value in msg_meta.items():
                msg[key] = value

        # Attach inline images
        supported_extensions = r'png|jpg|jpeg|gif|bmp|webp|svg|ico|tiff'
        if re.search(r'<img src="data:image/(' + supported_extensions + r');base64,([^"]+)"', body):
            for match in re.finditer(r'<img src="data:image/(' + supported_extensions + r');base64,([^"]+)"', body):
                img_ext, img_data = match.group(1), match.group(2)
                cid = f'image{match.start()}'
                body = body.replace(f'data:image/{img_ext};base64,{img_data}', f'cid:{cid}')
                image = base64.b64decode(img_data)
                image = MIMEImage(image, name=f"{cid}.{img_ext}")
                image.add_header('Content-ID', f'<{cid}>')
                msg.attach(image)
                    
        msg.attach(MIMEText(body, 'html'))
        if attachments:
            for attachment in attachments:
                if attachment.size > 25 * 1024 * 1024:
                    return False, "Attachment size limit is 25 MB"
                
                part = MIMEApplication(attachment.file.read())
                part.add_header('content-disposition', 'attachment', filename=attachment.filename)
                msg.attach(part)

        self.__smtp.sendmail(self.__email_address, [email.strip() for email in receiver_emails.split(",")], msg.as_string())
        return True, "Email sent successfully"

    def send_email(self, receiver_emails: str, subject: str, body: str, attachments: list = None) -> tuple[bool, str]:
        return self.__send_email(
            receiver_emails, 
            subject, 
            body, 
            attachments
        )

    def reply_email(self, receiver_emails: str, uid: str, body: str, attachments: list = None) -> tuple[bool, str]:
        result = self.__send_email(
            receiver_emails, 
            "Re: " + self.get_email_content(uid)[2]["subject"], 
            body, 
            attachments, 
            {
                "In-Reply-To": uid, 
                "References": uid
            }
        )
        
        if result[0]:
            self.mark_email(uid, "answered")

        return result

    def forward_email(self, receiver_emails: str, uid: str, body: str, attachments: list = None) -> tuple[bool, str]:
        return self.__send_email(
            receiver_emails, 
            "Fwd: " + self.get_email_content(uid)[2]["subject"], 
            body, 
            attachments,
            {
                "In-Reply-To": uid, 
                "References": uid
            }
        )

    @__handle_imap_conn
    def get_folders(self) -> tuple[bool, str, list] | tuple[bool, str]:
        # TODO: İlginç Folder lar dönüyor mesela [Gmail] gibi
        return True, "Folders fetched successfully", [self.__decode_folder_name(i) for i in self.__imap.list()[1]]
    
    def __fetch_flags(self, uid: str) -> list:
        if self.__imap.state != "SELECTED":
            raise Exception("Folder should be selected before fetching flags")
        
        flags = self.__imap.uid('FETCH', uid, '(FLAGS)')[1][0]
        if flags:
            flags = flags.decode()
            flags = re.findall(r'\\([a-zA-Z]+)', flags)
        return flags or []

    def __build_search_criteria(self, search_json: SearchCriteria) -> str:
        """
            Preparing to convert search_json to search_criteria string:
            https://datatracker.ietf.org/doc/html/rfc9051#name-search-command
        """
        search_criteria = ""
        search_criteria += f'FROM' + ' OR '.join([f'"{i}"' for i in search_json["from_"]]) + ' ' if check_json_value(search_json, "from_") else ""
        search_criteria += f'TO' + ' OR '.join([f'"{i}"' for i in search_json["to"]]) + ' ' if check_json_value(search_json, "to") else ""
        search_criteria += f'SUBJECT "{search_json["subject"]}" ' if check_json_value(search_json, "subject") else ""
        search_criteria += f'SINCE {convert_to_imap_date(search_json["since"])} ' if check_json_value(search_json, "since") else ""
        search_criteria += f'BEFORE {convert_to_imap_date(search_json["before"])} ' if check_json_value(search_json, "before") else ""
        search_criteria += f' '.join(search_json["flags"]) + ' ' if check_json_value(search_json, "flags") else ""
        return search_criteria
    
    def __search_with_criteria(self, criteria: str) -> list:
        if self.__imap.state != "SELECTED":
            raise Exception("Folder should be selected before searching")
        
        _, uids = self.__imap.uid('search', None, criteria)
        return uids[0].split()[::-1] if uids else []
    
    def __search_with_literal(self, search: str) -> list:
        if self.__imap.state != "SELECTED":
            raise Exception("Folder should be selected before searching")
        
        self.__imap.literal = search.encode("utf-8")
        _, uids = self.__imap.uid('search', 'CHARSET', 'UTF-8', 'TEXT')
        return uids[0].split()[::-1] if uids else []
    
    @__handle_imap_conn  
    def get_emails(self, folder: str = "inbox", search: str = "ALL", offset: int = 0) -> tuple[bool, str, list] | tuple[bool, str]:
        self.__imap.select(self.__encode_folder_name(folder), readonly=True)
        
        search_criteria = search
        if search != "ALL" and search != "":
            search = json.loads(search)
            search_criteria = self.__build_search_criteria(search)

        uids = self.__search_with_criteria(search_criteria or 'ALL')
        if len(uids) == 0:
            return True, "No emails found", []

        """
            Attachments and include/exclude search criteria are handled here
            because imap search command does not support attachments and
            if include/exclude contains special characters, imap search command
            does not work properly.
        """
        must_have_attachment = False
        if isinstance(search, dict):
            must_have_attachment = search["has_attachments"] if check_json_value(search, "has_attachments") else False
            
            if check_json_value(search, "include"):
                uids = list(set(uids).intersection(self.__search_with_literal(search["include"])))

            if check_json_value(search, "exclude"):
                uids = list(set(uids).intersection(self.__search_with_literal(search["exclude"])))

            if len(uids) == 0:
                return True, "No emails found", []

        emails = []
        for uid in uids[offset: offset + 10]:
            _, message = self.__imap.uid('fetch', uid, '(RFC822)')
            message = email.message_from_bytes(message[0][1], policy=email.policy.default)
                    
            payload = [message]
            if message.is_multipart():
                payload = message.walk()
                        
            body, is_body_html, skip_email_due_to_attachments = "", False, False
            for part in payload:
                content_type = part.get_content_type()
                file_name = part.get_filename()

                if must_have_attachment and not file_name:
                    skip_email_due_to_attachments = True
                    break
                
                is_body_html = content_type == "text/html"
                if (file_name is None and content_type == "text/plain") or (is_body_html and not body):
                    body = part.get_payload(decode=True)
                    body = body.decode(part.get_content_charset() or "utf-8") if body else ""
            
            if skip_email_due_to_attachments:
                continue
            
            body = BeautifulSoup(body, "html.parser").get_text() if is_body_html else body
            body = re.sub(r'<br\s*/?>', '', body).strip() if body != b'' else ""
            body = re.sub(r'[\n\r\t]+| +', ' ', body).strip()

            emails.append({
                "id": uid.decode(),
                "from": message["From"],
                "to": message["To"] if "To" in message else "",
                "subject": message["Subject"],
                "body_short": (body if body != "" else "No Content") if len(body) < 50 else body[:50] + "...",
                "date": datetime.strptime(message["Date"], "%a, %d %b %Y %H:%M:%S %z").strftime("%Y-%m-%d %H:%M:%S"),
                "flags": self.__fetch_flags(uid) or []
            })

        return True, "Emails fetched successfully", {"emails": emails, "total": len(uids)}

    @__handle_imap_conn
    def get_email_content(self, uid: str, folder: str = "inbox") -> tuple[bool, str, dict] | tuple[bool, str]:
        self.__imap.select(self.__encode_folder_name(folder))

        _, message = self.__imap.uid('fetch', uid, '(RFC822)')
        message = email.message_from_bytes(message[0][1], policy=email.policy.default)

        body, attachments = "", []
        for part in (message.walk() if message.is_multipart() else [message]):
            content_type = part.get_content_type()
            file_name = part.get_filename()
            if file_name:
                attachments.append({
                    "name": file_name,
                    "data": base64.b64encode(part.get_payload(decode=True)).decode("utf-8", errors="ignore"),
                    "type": content_type
                })
            elif content_type == "text/html" or (content_type == "text/plain" and not body):
                body = part.get_payload(decode=True)
                if body:
                    body = body.decode(part.get_content_charset())

        if re.search(r'<img src="cid:([^"]+)"', body):
            for match in re.finditer(r'<img src="cid:([^"]+)"', body):
                cid = match.group(1)
                for attachment in attachments:
                    if cid in attachment["name"]:
                        body = body.replace(f'cid:{cid}', f'data:{attachment["type"]};base64,{attachment["data"]}')                    

        if "Seen" not in self.__fetch_flags(uid):
            self.mark_email(uid, "seen", folder)

        return True, "Email fetched successfully", {
            "id": uid,
            "subject": message["Subject"],
            "body": body,
            "attachments": attachments
        }

    @__handle_imap_conn        
    def mark_email(self, uid: str, mark: str, folder: str = "inbox") -> tuple[bool, str]:
        self.__imap.select(self.__encode_folder_name(folder))
        
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
            return False, "Invalid mark"

        self.__imap.uid('STORE', uid, command, mark_map[mark])
        self.__imap.expunge()
        return True, "Email marked successfully"
    
    @__handle_imap_conn
    def move_email(self, uid: str, folder: str, destination_folder: str) -> tuple[bool, str]:
        self.__imap.select(self.__encode_folder_name(folder))
        self.__imap.uid('COPY', uid, self.__encode_folder_name(destination_folder))
        self.__imap.uid('STORE', uid , '+FLAGS', '(\Deleted)')
        self.__imap.expunge()
        return True, "Email moved successfully"
    
    @__handle_imap_conn
    def delete_email(self, uid: str, folder: str) -> tuple[bool, str]:
        self.__imap.select(self.__encode_folder_name(folder))
        self.__imap.uid('STORE', uid , '+FLAGS', '(\Deleted)')
        self.__imap.expunge()
        return True, "Email deleted successfully"
    
    @__handle_imap_conn
    def create_folder(self, folder_name: str, parent_folder: str | None) -> tuple[bool, str]:
        if parent_folder:
            folder_name = f"{parent_folder}/{folder_name}"
        self.__imap.create(self.__encode_folder_name(folder_name))
        return True, "Folder created successfully"
    
    @__handle_imap_conn
    def delete_folder(self, folder_name: str) -> tuple[bool, str]:
        self.__imap.delete(self.__encode_folder_name(folder_name))
        return True, "Folder deleted successfully"
    
    @__handle_imap_conn
    def move_folder(self, folder_name: str, destination_folder: str) -> tuple[bool, str]:
        if "/" in folder_name:
            destination_folder = f"{destination_folder}/{folder_name.split("/")[-1]}"
        self.__imap.rename(self.__encode_folder_name(folder_name), self.__encode_folder_name(destination_folder))
        return True, "Folder moved successfully"

    @__handle_imap_conn
    def rename_folder(self, folder_name: str, new_folder_name: str) -> tuple[bool, str]:
        # TODO: Burada "/" şeklinde kontrol yerine imap.list() kullanılabilir.
        if "/" in folder_name:
            new_folder_name = folder_name.replace(folder_name.split("/")[-1], new_folder_name)
        self.__imap.rename(self.__encode_folder_name(folder_name), self.__encode_folder_name(new_folder_name))
        return True, "Folder renamed successfully"
    