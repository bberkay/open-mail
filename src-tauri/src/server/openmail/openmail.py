from typing import List, Tuple, Sequence

from .types import SearchCriteria
from .imap import IMAP
from .smtp import SMTP

class OpenMail:
    def __init__(self):
        self.__imap = None
        self.__smtp = None

    def connect(self, email_address: str, password: str, imap_host: str = "", imap_port: int = 993, smtp_host: str = "", smtp_port: int = 587, try_limit: int = 3, timeout: int = 30) -> tuple[bool, str]:
        try:
            self.__imap = IMAP(
                email_address,
                password,
                imap_host,
                imap_port,
                try_limit,
                timeout
            )
            self.__smtp = SMTP(
                email_address,
                password,
                smtp_host,
                smtp_port,
                try_limit,
                timeout
            )
            return True, "Connected successfully"
        except Exception as e:
            return False, str(e)

    def disconnect(self) -> None:
        self.__imap.logout()
        self.__smtp.quit()

    def idle(self) -> None:
        self.__imap.idle()

    def done(self) -> None:
        self.__imap.done()

    def send_email(self,
        sender: str | Tuple[str, str],
        receiver_emails: str | List[str],
        subject: str,
        body: str,
        attachments: list | None = None,
        cc: str | List[str] | None = None,
        bcc: str | List[str] | None = None,
        msg_metadata: dict | None = None,
        mail_options: Sequence[str] = (),
        rcpt_options: Sequence[str] = ()
    ) -> bool:
        return self.__smtp.sendmail(
            sender,
            receiver_emails,
            subject,
            body,
            attachments,
            cc,
            bcc,
            msg_metadata,
            mail_options,
            rcpt_options
        )

    def reply_email(self,
        sender: str | Tuple[str, str],
        receiver_emails: str | List[str],
        uid: str,
        body: str,
        attachments: list | None = None
    ) -> bool:
        if self.__smtp.sendmail(
            sender,
            receiver_emails,
            "Re: " + self.__imap.get_email_content(uid)[2]["subject"],
            body,
            attachments,
            None,
            None,
            {
                "In-Reply-To": uid,
                "References": uid
            }
        ):
            self.__imap.mark_email(uid, "answered")
            return True

        return False

    def forward_email(self,
        sender: str | Tuple[str, str],
        receiver_emails: str | List[str],
        uid: str,
        body: str,
        attachments: list | None = None
    ) -> bool:
        return self.__smtp.sendmail(
            sender,
            receiver_emails,
            "Fwd: " + self.__imap.get_email_content(uid)[2]["subject"],
            body,
            attachments,
            None,
            None,
            {
                "In-Reply-To": uid,
                "References": uid
            }
        )

    def get_folders(self) -> list:
        return self.__imap.get_folders()

    def get_folder_status(self, folder: str, status: str = "MESSAGES") -> dict:
        return self.__imap.status(folder, status)

    def get_email_flags(self, uid: str) -> list:
        return self.__imap.get_email_flags(uid)

    def get_emails(self,
        folder: str = "inbox",
        search: str | SearchCriteria = "ALL",
        offset: int = 0
    ) -> dict:
        return self.__imap.get_emails(folder, search, offset)

    def get_email_content(self, uid: str, folder: str = "inbox") -> dict:
        return self.__imap.get_email_content(uid, folder)

    def mark_email(self, uid: str, mark: str, folder: str = "inbox") -> bool:
        return self.__imap.mark_email(uid, mark, folder)

    def move_email(self, uid: str, source_folder: str, destination_folder: str) -> bool:
        return self.__imap.move_email(uid, source_folder, destination_folder)

    def copy_email(self, uid: str, source_folder: str, destination_folder: str) -> bool:
        return self.__imap.copy_email(uid, source_folder, destination_folder)

    def delete_email(self, uid: str, folder: str) -> bool:
        return self.__imap.delete_email(uid, folder)

    def create_folder(self, folder_name: str, parent_folder: str | None = None) -> bool:
        return self.__imap.create_folder(folder_name, parent_folder)

    def delete_folder(self, folder_name: str) -> bool:
        return self.__imap.delete_folder(folder_name)

    def move_folder(self, folder_name: str, destination_folder: str) -> bool:
        return self.__imap.move_folder(folder_name, destination_folder)

    def rename_folder(self, folder_name: str, new_folder_name: str) -> bool:
        return self.__imap.rename_folder(folder_name, new_folder_name)
