"""
IMAPManager
This module extends the functionality of the
`imaplib.IMAP4_SSL` class to simplify its usage and
add new features.

Key features include:
- Automated server selection based on email domain.
- Support for idling and event-driven response handling on separate threads.
- New abstractions for managing email folders, marks, and search criteria.
- Built-in utility methods for email parsing, attachment handling, and UTF-8 compatibility.
- Custom error handling.

Primarily designed for use by the `OpenMail` class.

Author: <berkaykayaforbusiness@outlook.com>
License: MIT
"""
import imaplib
import email
import re
import threading
import base64
import time
from typing import override
from datetime import datetime
from enum import Enum
from ssl import SSLContext
from types import MappingProxyType
from dataclasses import dataclass

from .parser import MessageDecoder, MessageParser, HTMLParser
from .utils import add_quotes_if_str, extract_domain, choose_positive, extract_email_address, extract_email_addresses
from .utils import truncate_text, contains_non_ascii
from .types import SearchCriteria, Attachment, Mailbox, Email, Flags, Mark, Folder

"""
Exceptions
"""
class IMAPManagerException(Exception):
    """Custom exception for IMAPManager class."""

class IMAPManagerLoggedOutException(IMAPManagerException):
    """Custom exception for when the IMAPManager is logged out
    while trying to perform an action that requires authentication."""

"""
Types, that are only used in this module
"""
type IMAPCommandResult = tuple[bool, str]

"""
General consts, avoid changing
"""
IMAP_SERVERS = MappingProxyType({
    "gmail": "imap.gmail.com",
    "yahoo": "imap.mail.yahoo.com",
    "outlook": "outlook.office365.com",
    "hotmail": "outlook.office365.com",
    'yandex': 'imap.yandex.com',
})
IMAP_PORT = 993

# Regex Patterns
SEQUENCE_SET_PATTERN = re.compile(r"""
    ^(
        (\d+(,|:))*\d+$ |
        \*:((\d+(,|:))*\d+)?$ |
        ((\d+(,|:))*\d+:)?\*$
    )$
""", re.VERBOSE)

# Typo prevention
CRLF = b'\r\n'
INBOX = 'INBOX'

MARK_LIST = [str(m).lower() for m in Mark]
FOLDER_LIST = [str(f).lower() for f in Folder]

"""
Custom consts
"""
GET_EMAILS_OFFSET_START = 1
GET_EMAILS_OFFSET_END = 10
SHORT_BODY_MAX_LENGTH = 100 # Character count
SHORT_BODY_TEXT_CHUNK_SIZE = 4096 # in bytes
MAX_FOLDER_NAME_LENGTH = 1024
CONN_TIMEOUT = 30 # 30 seconds
IDLE_TIMEOUT = 30 * 60 # 30 minutes
JOIN_TIMEOUT = 3 # 3 seconds
WAIT_RESPONSE_TIMEOUT = 3 * 60 # 3 minutes
READLINE_SLEEP = 1 # 1 seconds

class IMAPManager(imaplib.IMAP4_SSL):
    """
    IMAPManager extends the `imaplib.IMAP4` class.
    Overrides `login`, `logout`, `shutdown`, `select`,
    and `__simple_command`. Provides additional features
    especially idling and listening exists responses on
    different threads. Mainly used in `OpenMail` class.
    """

    @dataclass
    class SearchedEmails:
        """Dataclass for storing searched emails."""
        uids: list[str]
        folder: str
        search_query: str

    class WaitResponse(Enum):
        """
        Enum for waiting for a response from the server.
        These are not the all possible responses but the ones `IMAPManager`
        is interested in.

        References:
            - https://datatracker.ietf.org/doc/html/rfc9051#name-idle-command
            - https://datatracker.ietf.org/doc/html/rfc9051#name-exists-response
            - https://datatracker.ietf.org/doc/html/rfc9051#name-bye-response
        """
        IDLE = "IDLE"
        DONE = "DONE"
        EXISTS = "EXISTS"
        BYE = "BYE"

    def __init__(
        self,
        email_address: str,
        password: str,
        host: str = "",
        port: int = IMAP_PORT,
        ssl_context: SSLContext | None = None,
        timeout: int = CONN_TIMEOUT
    ):
        self._host = host or self._find_imap_server(email_address)
        self._port = port or IMAP_PORT

        self._searched_emails: IMAPManager.SearchedEmails | None = None

        # IDLE and READLINE variables
        self._is_idle = False
        self._current_idle_start_time = None
        self._current_idle_tag: str | None = None
        self._wait_for_response: IMAPManager.WaitResponse | None = None

        self._idle_thread_event = None
        self._idle_thread = None

        self._readline_thread_event = None
        self._readline_thread = None

        # These are must be called after IDLE and READLINE vars are
        # initialized because these methods are using `_simple_command`
        # and `_simple_command` is overridden in this class to handle
        # IDLE and READLINE operations and uses these vars.
        super().__init__(
            self._host,
            self._port,
            ssl_context=ssl_context,
            timeout=choose_positive(timeout, CONN_TIMEOUT)
        )

        self.login(email_address, password)

    def _find_imap_server(self, email_address: str) -> str:
        """
        Determines the IMAP server address for a given email address.

        Args:
            email_address (str): The email address for which to find the
            corresponding IMAP server.

        Returns:
            str: The IMAP server address associated with the email's domain.

        Example:
            >>> email_address = "user@gmail.com"
            >>> self._find_imap_server(email_address)
            "imap.gmail.com"
            >>> email_address = "user@unknown.com"
            >>> self._find_imap_server(email_address)
            IMAPManagerException: Unsupported email domain

        Raises:
            IMAPManagerException: If the email domain is not supported or
            not found in the IMAP_SERVERS mapping.
        """
        try:
            return IMAP_SERVERS[extract_domain(email_address)]
        except KeyError:
            raise IMAPManagerException("Unsupported email domain") from None

    @override
    def login(self, user: str, password: str) -> IMAPCommandResult:
        """
        Authenticates the user with the IMAP server using the provided credentials.

        Args:
            user (str): The username or email address of the account.
            password (str): The account's password.

        Returns:
            IMAPCommandResult: A tuple containing:
                - True
                - A string containing a success message.

        Raises:
            IMAPManagerException: If the login process fails.

        Notes:
            - UTF-8 encoding is enabled after successful authentication.
            - Supports both ASCII and non-ASCII credentials.
            - 'password' will be quoted.
        """
        if contains_non_ascii(user) or contains_non_ascii(password):
            self.authenticate(
                "PLAIN",
                lambda x: bytes("\x00" + user + "\x00" + password, "utf-8")
            )
        else:
            super().login(user, password)

        try:
            result = self._simple_command('ENABLE', 'UTF8=ACCEPT')
            if result[0] != 'OK':
                print(f"Could not enable UTF-8: {result[1]}")
        except Exception as e:
            print(f"Unexpected error: Could not enable UTF-8: {str(e)}")
            pass

        return (True, "Succesfully logged in to the target IMAP server")

    @override
    def logout(self) -> IMAPCommandResult:
        """
        Logs out from the IMAP server and closes any open mailboxes.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the logout was successful.
                - A string containing a success message or an error message.

        Notes:
            - If the state is "SELECTED," the mailbox is closed before disconnecting.
            If there is an error while closing the mailbox, it will be logged but not
            raised.
        """
        try:
            return self._parse_command_result(
                super().logout(),
                success_message="Logout successful",
                failure_message="Could not logout from the target imap server"
            )
        finally:
            self._terminate_threads()

    @override
    def select(self, folder: str | Folder, readonly: bool = False) -> IMAPCommandResult:
        """
        Overrides the `select` method to handle the `Folder` enum type.
        """
        folder = (
            self.find_matching_folder(folder)
            or
            (self._encode_folder(folder) if isinstance(folder, str) else folder)
        )

        result = self._parse_command_result(
            super().select(folder, readonly),
            success_message=f"Successfully selected {folder}",
            failure_message=f"Error while selecting folder `{folder}`"
        )

        if not result[0]:
            raise IMAPManagerException(result[1])

        return result

    @override
    def _simple_command(self, name, *args):
        """
        Overrides the _simple_command method to handle continuous IDLE mode and
        raise IMAPManagerLoggedOutException if the IMAPManager is logged out because
        of timeout.
        """

        def is_logged_out(err_msg: str) -> bool:
            """
            Checks if the error message contains the keywords "AUTH" or "SELECTED" to determine if
            the IMAPManager is logged out.

            Args:
                err_msg (str): The error message to check.

            Returns:
                bool: True if self.state is "LOGOUT" and the error message contains "AUTH" or
                "SELECTED", False otherwise.
            """
            return self.state == "LOGOUT" and any(
                item.lower() in err_msg for item in ("AUTH", "SELECTED")
            )

        # If the command is "DONE", idle checking
        # and restoring must not be done since
        # `DONE` command is used to leave IDLE mode.
        # Also, in the timeout case, the `idle` method
        # will be called after the `done` method,
        # which is already handled in the `__idle` method.
        if name == "DONE":
            return super()._simple_command(name, *args)

        # Leaving IDLE mode if needed
        was_idle_before_call = self._is_idle
        try:
            if was_idle_before_call:
                self.done()
        except Exception as e:
            if is_logged_out(str(e).lower()):
                raise IMAPManagerLoggedOutException(f"To perform this command `{name}`, the IMAPManager must be logged in: {str(e)}") from None
            else:
                print(f"Unexpected error while leaving IDLE mode: {str(e)}")
                # Even if leaving IDLE failed, set idle and readline threads and set
                # __is_idle to False.
                self._handle_done_response()
                print("Active IDLE status set to False and threads stopped forcefully.")

        # Run wanted command.
        try:
            result = super()._simple_command(name, *args)
        except Exception as e:
            if is_logged_out(str(e).lower()):
                raise IMAPManagerLoggedOutException(f"To perform this command `{name}`, the IMAPManager must be logged in: {str(e)}") from None
            else:
                raise IMAPManagerException(f"Error while running command `{name}`: {str(e)}`") from None

        # Restoration does not need to be done
        # if the command is "LOGOUT".
        if name == "LOGOUT":
            return result

        # Restoring IDLE mode
        try:
            if was_idle_before_call:
                self.idle()
            return result
        except Exception as e:
            print(f"Unexpected error while restoring IDLE mode: {str(e)}")
            was_idle_before_call = False
            print("IDLE mode could not be restored. IDLE mode completely disabled. Run `idle()` to re-enable IDLE mode if needed.")
            raise IMAPManagerException(str(e)) from None

    def _parse_command_result(self,
        result: tuple[str, list[bytes | None]],
        success_message: str = "",
        failure_message: str = ""
    ) -> IMAPCommandResult:
        """
        Parses the result of an IMAP command and returns a structured response.

        Args:
            result (tuple[str, list[bytes | None]]):
                The command result, where:
                - The first element is the status ("OK", "NO", etc.).
                - The second element is a list containing additional response data.
            success_message (str, optional):
                A custom success message to include in the response. Will override the
                default success message. If not provided, the default success message will
                be used.
            failure_message (str, optional):
                A custom failure message to include in the response. Will be added at the
                start of the failure message if provided.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A boolean indicating success (True for "OK", False otherwise).
                - The server's response message as a string.

        Raises:
            IMAPManagerException: If parsing the command result fails.

        Example:
            >>> result = ("OK", [b"Command completed successfully"])
            >>> self._parse_command_result(result,
                    success_message="Operation successful",
                    failure_message="Login failed"
                )
            (True, "Operation successful")
            >>> result = ("NO", [b"Invalid credentials"])
            >>> self._parse_command_result(result,
                    success_message="Operation successful",
                    failure_message="Login failed"
                )
            (False, "Login failed: Invalid credentials")
            >>> result = ("BYE", [b"Logout successful"])
            >>> self._parse_command_result(result,
                    success_message="Operation successful",
                    failure_message="Logout failed"
                )
            (True, "Logout successful")

        Notes:
            - If the first element of the result is "BYE", it is considered
            a logout command and will be searching for a "logout" in the
            result message like in the example.
        """
        try:
            if result[0] == "OK" or result[0] == "BYE":
                return True, success_message or result[1][0].decode("utf-8")
            else:
                return False, failure_message + ": " + result[1][0].decode("utf-8")
        except Exception as e:
            raise IMAPManagerException(f"There was an error while parsing command `{result}` result: {str(e)}") from None

    def _is_sequence_set_valid(self, sequence_set: str, uids: list[str]) -> bool:
        """
        Validates whether the given `sequence_set` correctly represents a subset of the provided `uids`.

        Args:
            sequence_set (str): A string representing a set of sequences as defined in RFC 9051.
            uids (list[int]): A sorted list of integer UIDs to validate against.

        Returns:
            bool: `True` if all UIDs derived from the `sequence_set` are present in the `uids` list.
            `False` otherwise.

        Example:
            >>> uids = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10']
            >>> _is_sequence_set_valid("1,3:6,9", uids)
            True
            >>> _is_sequence_set_valid("1:5,8:*", uids)
            True
            >>> _is_sequence_set_valid("1,3,20", uids)
            False

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        if not SEQUENCE_SET_PATTERN.match(sequence_set):
            return False

        max_uid = uids[-1]
        expanded = set()
        segments = sequence_set.split(',')

        for segment in segments:
            if ':' in segment:
                parts = segment.split(':')
                if parts[0] == '*':
                    start = int(max_uid)
                else:
                    start = int(parts[0])

                if parts[-1] == '*':
                    end = int(max_uid)
                else:
                    end = int(parts[-1])

                expanded.update(list(range(start, end + 1)), [max(start, end)])
            else:
                if segment == '*':
                    expanded.add(max_uid)
                else:
                    expanded.add(segment)

        for sequence_set_uid in map(str, expanded):
            if sequence_set_uid not in uids:
                return False

        return True

    def idle(self):
        """
        Initiates the IMAP IDLE command to start monitoring changes
        in the mailbox on its own thread. If already in IDLE mode,
        does nothing.
        """
        if not self._is_idle:
            self._current_idle_tag = self._new_tag()
            self.send(b"%s IDLE\r\n" % self._current_idle_tag)
            print(f"'IDLE' command sent with tag: {self._current_idle_tag} at {datetime.now()}.")
            self._readline()
            self._wait_response(IMAPManager.WaitResponse.IDLE)

    def done(self):
        """Terminates the current IDLE session if active."""
        if self._is_idle:
            self.send(b"DONE\r\n")
            print(f"DONE command sent for {self._current_idle_tag} at {datetime.now()}.")
            self._wait_response(IMAPManager.WaitResponse.DONE)

    def _wait_response(self, wait_response: WaitResponse):
        """
        Waits for a specific response type from the IMAP server.

        Args:
            wait_response (IMAPManager.WaitResponse): Expected response type to wait for

        Times out after WAIT_RESPONSE_TIMEOUT seconds and resets wait state.
        """
        counter = 0
        while self._wait_for_response != wait_response:
            time.sleep(1)
            counter += 1
            if counter > WAIT_RESPONSE_TIMEOUT:
                print(f"IMAPManager.WaitResponse: {wait_response} did not received in time at {datetime.now()}. IMAPManager.WaitResponse set to None")
                break

        self._wait_for_response = None

    def _idle(self):
        """
        Background thread handler for IDLE mode monitoring.

        Continuously checks IDLE session duration and automatically
        refreshes the connection when IDLE_TIMEOUT is reached.
        """
        while not self._idle_thread_event.is_set():
            print(f"IDLING for {self._current_idle_tag} at {datetime.now()}.")
            time.sleep(1)
            if time.time() - self._current_idle_start_time > IDLE_TIMEOUT:
                print(f"IDLING timeout reached for {self._current_idle_tag} at {datetime.now()}.")
                self.done()
                if not self._idle_thread_event.is_set():
                    self.idle()

    def _readline(self):
        """
        Initializes and manages the response reading thread.

        Creates a new thread for continuously reading server responses
        if one doesn't exist or isn't active. Processes responses through
        the handle_response method.
        """
        def readline_thread():
            """
            Continuously reads server responses and processes them.
            """
            self.socket().settimeout(None)

            while not self._readline_thread_event.is_set():
                try:
                    print(f"Waiting for new response at {datetime.now()}.")
                    response = self.readline()
                    if response:
                        print(f"New response received: {response} at {datetime.now()}. Handling response...")
                        self._handle_response(response)
                except (TimeoutError, OSError):
                    print(f"Readline timed out at {datetime.now()}.")
                    pass
                time.sleep(READLINE_SLEEP)

        if not self._readline_thread_event:
            self._readline_thread_event = threading.Event()
        self._readline_thread_event.clear()

        if not self._readline_thread or not self._readline_thread.is_alive():
            self._readline_thread = threading.Thread(target=readline_thread)
            self._readline_thread.start()

    def _handle_idle_response(self):
        """
        Handles the server's response to the IDLE command.
        Marks the client as being in the IDLE state, sets
        start time, and starts the IDLE monitoring thread.
        This method shouldn't be called directly, but rather
        through the `handle_response` method.
        """
        print(f"'IDLE' response received for {self._current_idle_tag} at {datetime.now()}.")
        self._is_idle = True
        self._current_idle_start_time = time.time()

        if not self._idle_thread_event:
            self._idle_thread_event = threading.Event()
        self._idle_thread_event.clear()

        if not self._idle_thread or not self._idle_thread.is_alive():
            self._idle_thread = threading.Thread(target=self._idle)
            self._idle_thread.start()

        self._wait_for_response = IMAPManager.WaitResponse.IDLE
        print(f"'IDLE' response for {self._current_idle_tag} handled, IDLE thread started at {datetime.fromtimestamp(self._current_idle_start_time)}.")

    def _handle_done_response(self):
        """
        Handles the server's response to the DONE command.
        Marks the client as no longer in the IDLE state
        and stops the IDLE monitoring thread. This method
        shouldn't be called directly, but rather through
        the `handle_response` method.
        """
        print(f"'DONE' response received for {self._current_idle_tag} at {datetime.now()}.")
        self._is_idle = False
        temp_tag = self._current_idle_tag
        self._current_idle_tag = None

        self._idle_thread_event.set()
        self._readline_thread_event.set()

        self._wait_for_response = IMAPManager.WaitResponse.DONE
        print(
            f"'DONE' response for {temp_tag} handled, IDLE thread stopped at {datetime.now()}."
        )

    def _handle_bye_response(self):
        """
        Handles the server's 'BYE' response, which indicates the server
        is closing the connection. Safely terminates the connection, stops
        threads, and raises an exception to signal the logout event. This
        method shouldn't be called directly, but rather through the
        `handle_response`method.
        """
        print(f"'BYE' response received from server at {datetime.now()}.")
        self._wait_for_response = IMAPManager.WaitResponse.BYE
        self._readline_thread_event.set()
        self._idle_thread_event.set()
        self._is_idle = False
        self._current_idle_tag = None
        raise IMAPManagerLoggedOutException(f"'BYE' response received from server at {datetime.now()}. IMAPManager connection closed safely.") from None

    def _handle_exists_response(self, response: bytes):
        """
        Handles the 'EXISTS' response from the server, which indicates the
        number of messages in the mailbox. Updates internal state or performs
        necessary actions based on the response. This method shouldn't be
        called directly, but rather through the `handle_response` method.

        Args:
            response (bytes): The server's EXISTS response data.
        """
        print(f"'EXISTS' response received from server at {datetime.now()}.")
        self._wait_for_response = IMAPManager.WaitResponse.EXISTS
        # TODO: Implement handling of EXISTS response
        pass

    def _handle_response(self, response: bytes):
        """
        Determines the type of server response and delegates handling to the
        appropriate method. This method shouldn't be called directly, but rather
        through the `readline` method.

        Args:
            response (bytes): The raw server response to be processed.
        """
        if b'idling' in response:
            self._handle_idle_response()
        elif b'OK' in response and bytes(self._current_idle_tag) in response:
            self._handle_done_response()
        elif b'BYE' in response:
            self._handle_bye_response()
        elif b'EXISTS' in response:
            self._handle_exists_response(response)

    def _terminate_threads(self):
        """Terminates all threads used by the IMAPManager."""
        if self._idle_thread_event is not None:
            print("Setting idle thread event...")
            self._idle_thread_event.set()

        if self._readline_thread_event is not None:
            print("Setting readline thread event...")
            self._readline_thread_event.set()

        if self._idle_thread is not None and self._idle_thread.is_alive():
            print("Joining idle thread...")
            self._idle_thread.join(timeout=JOIN_TIMEOUT)

        if self._readline_thread is not None and self._readline_thread.is_alive():
            print("Joining readline thread...")
            self._readline_thread.join(timeout=JOIN_TIMEOUT)

    def find_matching_folder(self, requested_folder: str | Folder, encoded: bool = True) -> bytes | None:
        """
        Retrieve the IMAP folder name matching a specific byte string.

        This method is useful for handling cases where a client's folder names
        are localized in a different language.

        Args:
            requested_folder (str | Folder): The IMAP folder name (e.g., 'Inbox' or 'Trash').

        Returns:
            bytes | None: The folder name in bytes if a match is found; otherwise, None.

        Example:
            >>> find_matching_folder(Folder.Inbox)
            b'INBOX'
            >>> find_matching_folder(Folder.Flagged, encoded=True)
            b'"[Gmail]/Y\xc4\xb1ld\xc4\xb1zl\xc4\xb1"'
            >>> find_matching_folder(Folder.Flagged, encoded=False)
            b'"[Gmail]/Yıldızlı"' # Flagged in Turkish
        """
        if requested_folder.lower() not in FOLDER_LIST:
            return None

        status, folders_as_bytes = self.list()
        if status == "OK" and folders_as_bytes and isinstance(folders_as_bytes, list):
            for folder_as_bytes in folders_as_bytes:
                if requested_folder.upper() in self._decode_folder(folder_as_bytes).upper():
                    if encoded:
                        return self._encode_folder(self._extract_folder_name(folder_as_bytes))
                    else:
                        return self._extract_folder_name(folder_as_bytes)
        return None

    def _encode_folder(self, folder: str) -> bytes:
        """Encode a folder name into a byte string suitable for IMAP operations."""
        try:
            return ('"' + folder + '"').encode("utf-8")
        except Exception as e:
            raise IMAPManagerException(f"Error while encoding folder name: {str(e)}") from None

    def _decode_folder(self, folder: bytes) -> str:
        """Decode a folder name from a byte string returned by an IMAP server."""
        try:
            return folder.decode("utf-8")
        except Exception as e:
            raise IMAPManagerException(f"Error while decoding folder name `{str(folder)}`: `{str(e)}`.") from None

    def _extract_folder_name(self, folder: str | bytes, /, tagged: bool = False) -> str:
        """
        Extract a folder name from a byte string returned by an IMAP server.

        Args:
            folder (str | bytes): The byte or string containing the folder name.
            tagged (boolean): Tag folders with their original name. Inbox will
            also be tagged either has a special tag or not.

        Returns:
            str: The decoded and cleaned folder name.

        Example:
            >>> _extract_folder_name(b'(\\HasNoChildren) "/" "INBOX"')
            'INBOX'
            >>> _extract_folder_name(b'(\\Junk \\HasNoChildren) "|" "[Gmail]/Spam"', tagged=False)
            'Spam'
            >>> _extract_folder_name(b'(\\Junk \\HasNoChildren) "|" "[Gmail]/Spam"', tagged=True)
            '[Folder.Junk]:Spam'
            >>> _extract_folder_name(b'(\\HasNoChildren) "|" "MyCustomFolder"')
            'MyCustomFolder'

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-list-response
        """
        try:
            if isinstance(folder, bytes):
                folder = self._decode_folder(folder)

            # Most of the servers return folder name as b'(\\HasNoChildren) "/" "INBOX"'
            # But some servers like yandex return folder name as b'(\\HasNoChildren) "|" "INBOX"'
            # So we're replacing "|" with "/" to make it consistent
            folder = folder.replace(' "|" ', ' "/" ', 1)

            folder_parts = folder.split(' "/" ', 1)
            folder_name = folder_parts[-1].replace('"', '')
            folder_tag = folder_parts[0] if len(folder_parts) > 1 else None

            if tagged:
                folder_tag = folder_tag.lower()
                if folder_name.lower() == Folder.Inbox.lower():
                    folder_tag = Folder.Inbox
                    folder_name = folder_name.capitalize()

                # Add folder tag to beginning of the folder name like if
                # folder includes any. For example if folder is something like
                # this: "(\HasNoChildren \Trash) | Trash Bin" convert it to
                # "Trash:Trash Bin". This is important to ensure that the client
                # can recognize the folder in a way that is not affected by any
                # language or different spelling.
                for standard_folder in FOLDER_LIST:
                    if standard_folder.lower() in folder_tag.lower():
                        folder_name = f"{standard_folder.capitalize()}:{folder_name}"

            return folder_name
        except Exception as e:
            raise IMAPManagerException(f"Error while decoding folder name `{str(folder)}`: `{str(e)}`.") from None

    def _check_folder_names(self, folders: str | list[str], raise_error: bool = True) -> bool:
        """
        Check if a folder name(s) is valid.

        Args:
            folders (str | List[str]): Folder name or list of folder names
            raise_error (bool, optional): If True, raise an error if the folder name is invalid.
                                          Default is True

        Returns:
            bool: True if folder name is valid, False otherwise

        Example:
            >>> self._check_folder_names("INBOX")
            True
            >>> self._check_folder_names(["INBOX", "Trash"])
            True
            >>> self._check_folder_names("")
            raises IMAPManagerException
            >>> self._check_folder_names("INBOX", raise_error=False)
            False

        Raises:
            IMAPManagerException: If the folder name is invalid and raise_error is True
        """
        if isinstance(folders, str):
            folders = [folders]

        for folder_name in folders:
            if not folder_name:
                continue

            folder_name_length = len(folder_name)
            if folder_name is None or folder_name == "" or folder_name_length > MAX_FOLDER_NAME_LENGTH or folder_name_length < 1:
                if raise_error:
                    raise IMAPManagerException(f"Invalid folder name: `{folder_name}`")
                return False

        return True

    def get_folders(self, folder_name: str | None = None, /, tagged: bool = False) -> list[str]:
        """
        Retrieve a list of all email folders.

        Args:
            folder_name (str, optional): Subfolders of the specified folder.
            Defaults to None. If None, returns all folders.
            tagged (boolean): Tag folders with their original name. Inbox will
            also be tagged either has a special tag or not.

        Returns:
            list[str]: List of folder names in the email account

        Example:
            >>> get_folders(tagged=False)
            ['Inbox', '[Gmail]/Spam', '[Gmail]/Trash Bin', 'My Custom Folder']
            >>> get_folders(tagged=True)
            ['[Folder.Inbox]:Inbox', '[Folder.Junk]:[Gmail]/Spam', '[Folder.Trash]:[Gmail]/Trash Bin', 'My Custom Folder']

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-list-response
        """
        status, folders = self.list()
        if not status == "OK":
            raise IMAPManagerException(f"Failed to list folders with status: {status}.")

        folder_list = []
        disallowed_keywords = [b'\\Noselect']
        disallowed_keywords = [keyword.lower() for keyword in disallowed_keywords]
        for folder in folders:
            if not any(keyword in folder.lower() for keyword in disallowed_keywords):
                decoded_folder = self._extract_folder_name(folder, tagged=tagged)
                if not folder_name or (folder_name in decoded_folder and not decoded_folder.endswith(folder_name)):
                    folder_list.append(decoded_folder)

        # Sort folders
        # Standard folders comes first for example:
        # ['[Folder.Junk]:Spam', '[Folder.Trash]:[Gmail]/Trash Bin', 'customA', 'customA/customAB', ...]
        # Custom folders will be sorted hierarchically for example:
        # [..., 'customA', 'customA/customAB', 'customA/customAB/customABC', 'customB/customBA']
        folder_list.sort(key=lambda path: (
            not any(path.startswith(f"{folder.capitalize()}:") for folder in FOLDER_LIST),
            path.split("/"),
            len(path.split("/"))
        ))
        return folder_list

    def build_search_criteria_query(self, search_criteria: SearchCriteria | str) -> str:
        """
        Builds an IMAP-compatible search criteria query string based on given search parameters.

        Args:
            search_criteria (SearchCriteria): An object containing various search criteria,
            such as senders, receivers, subject, date ranges, included/excluded text, and flags.

        Returns:
            str: A search criteria query string ready to be used with IMAP's SEARCH command.

        Notes:
            This function recursively builds complex OR queries and handles multiple search criteria
            by converting them into the required format as per RFC 9051.

        Example:
            >>> search_criteria = SearchCriteria(senders=["a@mail.com"],
            ...                                  receivers=["b@mail.com", "c@mail.com"],
            ...                                  subject="Hello",
            ...                                  since="2023-01-01",
            ...                                  before="2023-12-31",
            ...                                  body="world",
            ...                                  included_flags=[Mark.Flagged, Mark.Seen, "customflag"])
            >>> build_search_criteria_query(search_criteria)
            '(FROM "a@mail.com") (OR (TO "b@mail.com") (TO "c@mail.com")) (SUBJECT "Hello") (SINCE
            ... "2023-01-01") (BEFORE "2023-12-31") (BODY "world") FLAGGED SEEN KEYWORD "customflag"'

            >>> build_search_criteria_query("sender@mail.com")
            'TEXT "sender@mail.com"'

            >>> build_search_criteria_query("Some paragraph")
            'TEXT "Some paragraph"'

        References:
            - https://datatracker.ietf.org/doc/html/rfc9051#name-search-command
        """

        def recursive_or_query(criteria: str, search_keys: list[str]) -> str:
            """
            Recursively builds an OR query for a list of search keys.

            Args:
                criteria (str): The search criteria, e.g., "FROM".
                search_keys (List[str]): A list of values for the criteria.

            Returns:
                str: A query string with nested OR conditions for the search keys.

            Example:
                >>> recursive_or_query("FROM", ["a@mail.com", "b@mail.com", "c@mail.com"])
                'OR (FROM "a@mail.com") (OR (FROM "b@mail.com") (FROM "c@mail.com"))'
            """
            query = ''
            len_search_keys = len(search_keys)
            if len_search_keys == 1:
                return f'{criteria} "{search_keys[0]}"'

            mid = len_search_keys // 2
            left_part = recursive_or_query(criteria, search_keys[:mid])
            right_part = recursive_or_query(criteria, search_keys[mid:])

            return query + f'OR ({left_part}) ({right_part})'

        def add_criterion(
            criteria: str,
            value: str | int | list | None,
            seperate_with_or: bool = False
        ) -> str:
            """
            Converts a single search criterion and its value(s) into a query string.

            Args:
                criteria (str): The search criterion, e.g., "FROM" or "SUBJECT".
                value (str | list | None): The value(s) to match for the criterion.
                seperate_with_or (bool): Whether to combine multiple values with OR conditions.

            Returns:
                str: A formatted query string for the given criterion.

            Example:
                >>> add_criterion("FROM", value=["a@mail.com", "b@mail.com"])
                ' (FROM "a@mail.com") (FROM "b@mail.com")'
            """
            if not value:
                return ''

            if isinstance(value, int):
                value = str(value)
            elif isinstance(value, list):
                if criteria == '':
                    # value=["Flagged", "Seen", "Answered"]
                    return f" {' '.join([i.strip().upper() for i in value])}"

                if len(value) <= 1:
                    return f' ({criteria.strip()} "{value[0].strip()}")'

            if seperate_with_or and len(value) > 1:
                value = recursive_or_query(criteria, value)
                criteria = ''

            if criteria:
                return f' ({criteria.strip()} {add_quotes_if_str(value)})'
            else:
                return f' ({value.strip()})'

        try:
            if isinstance(search_criteria, str):
                return add_criterion('TEXT', search_criteria).strip()

            flag_list = []
            if search_criteria.included_flags:
                for flag in search_criteria.included_flags:
                    if flag.lower() not in MARK_LIST:
                        flag_list.append(f'KEYWORD {flag}')
                    else:
                        flag_list.append(flag.replace("\\", ""))

            if search_criteria.excluded_flags:
                for flag in search_criteria.excluded_flags:
                    if flag.lower() not in MARK_LIST:
                        flag_list.append(f'UNKEYWORD {flag}')
                    else:
                        flag_list.append(
                            flag.replace(
                                "\\",
                                "UN" if not flag.lower().startswith("\\un") else ""
                            )
                        )

            search_criteria_query = ''
            search_criteria_query += add_criterion(
                'FROM',
                extract_email_addresses(search_criteria.senders or []),
                len(search_criteria.senders or []) > 1
            )
            search_criteria_query += add_criterion(
                'TO',
                extract_email_addresses(search_criteria.receivers or []),
                len(search_criteria.receivers or []) > 1
            )
            search_criteria_query += add_criterion(
                'CC',
                extract_email_addresses(search_criteria.cc or []),
                len(search_criteria.cc or []) > 1
            )
            search_criteria_query += add_criterion(
                'BCC',
                extract_email_addresses(search_criteria.bcc or []),
                len(search_criteria.bcc or []) > 1
            )
            search_criteria_query += add_criterion("SUBJECT", search_criteria.subject)
            search_criteria_query += add_criterion("SINCE", search_criteria.since)
            search_criteria_query += add_criterion("BEFORE", search_criteria.before)
            search_criteria_query += add_criterion("BODY", search_criteria.include)
            search_criteria_query += add_criterion("NOT BODY", search_criteria.exclude)
            search_criteria_query += add_criterion('', flag_list)
            search_criteria_query += add_criterion('TEXT', search_criteria.has_attachments and 'ATTACHMENT' or '')
            search_criteria_query += add_criterion('LARGER', search_criteria.larger_than)
            search_criteria_query += add_criterion('SMALLER', search_criteria.smaller_than)
        except Exception as e:
            raise IMAPManagerException(f"Error while building search query from `{str(search_criteria)}`") from e

        return search_criteria_query.strip()

    def search_emails(self,
        folder: str = "",
        search: str | SearchCriteria = ""
    ) -> IMAPCommandResult:
        """
        Get email uids from a specified folder based on search criteria. Does not
        return search result but saves the uids for use them in `get_emails` method.

        Args:
            folder (str, optional): Folder to search in. If not provided, selected folder
            will be used. If there is no selected folder then `All` folder will be selected
            if search is not None otherwise `Inbox` will be selected. Inbox will be selected
            if folder and search not provided, if only search provided but folder not provided
            then fol
            search (str | SearchCriteria, optional): Search criteria. Defaults to "ALL".

        Example:
            >>> search_emails("INBOX") # Search all emails in INBOX.
            True, "Search in folder `INBOX` was successful. Results are saved."
            >>> search_emails("Archived", "FROM 'a@mail.com'") # Search emails from 'a@mail.com'.
            True, "Search in folder `Archived` was successful. Results are saved."
            >>> search_emails("MyCustomFolder", SearchCriteria(senders=['a@mail.com'])) # Search emails from 'a@mail.com'.
            True, "Search in folder `MyCustomFolder` was successful. Results are saved."
        """

        def save_emails(uids: list[str], folder: str | Folder, search_query: str):
            """
            Save emails to a specified folder for later use.

            Args:
                uids (list[str]): A list of email uids to save.
                folder (str): The folder to save the emails to.
                search_query (str): The search query used to fetch the emails.
            """
            self._searched_emails = IMAPManager.SearchedEmails(
                folder=self._extract_folder_name(
                    self.find_matching_folder(str(folder), encoded=False) or folder
                ),
                search_query=search_query,
                uids=uids
            )

        if not folder:
            folder = Folder.All if search else Folder.Inbox

        self.select(folder, readonly=True)

        if search:
            search_criteria_query = self.build_search_criteria_query(search).encode("utf-8")
        else:
            search_criteria_query = 'ALL'

        # Searching emails
        try:
            search_status, uids = self.uid(
                'search',
                None,
                search_criteria_query
            )

            if search_status != 'OK':
                raise IMAPManagerException(f"Error while getting email uids, search query was `{search_criteria_query}` and error is `{search_status}.`")

            if not uids or not uids[0]:
                return False, "No emails found."

            uids = uids[0].decode().split()[::-1]
            save_emails(uids, folder, search_criteria_query)
            return True, "Search in folder `{}` was successful. Results are saved.".format(folder)
        except Exception as e:
            raise IMAPManagerException(f"Error while getting email uids, search query was `{search_criteria_query}` and error is `{str(e)}.`")

    def is_email_exists(self,
        folder: str,
        sequence_set: str
    ) -> bool:
        """
        Check is given uid exists in given folder.

        Args:
            folder (str): Folder to search in.
            sequence_set (str): Sequence set of uids to check.

        Returns:
            bool: True if email exists, False otherwise.

        Example:
            >>> is_email_exists("1") # Returns True if the email with UID 1 is found.
            >>> is_email_exists("1,2,3") # Return True if all of the emails with with UID 1,2,3 are found.
            >>> is_email_exists("1:3") # Return True if all of the emails with with UID 1,2,3 are found.
            >>> is_email_exists("1,3:5") # Return True if all of the emails with with UID 1 and 3,4,5 are found.

        Raises:
            ValueError: If the `sequence_set` contains "*".

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        if "*" in sequence_set:
            raise ValueError(f"Error sequence_set can not contain `*` while checking emails `{sequence_set}`")

        self.select(folder, readonly=True)

        status, data = self.uid('search', f"UID {sequence_set}")
        if not status:
            raise IMAPManagerException(f"Error while checking emails `{sequence_set}`: `{status}`")

        return self._is_sequence_set_valid(
            sequence_set,
            data[0].decode().split(" ")
        )

    def get_emails(
        self,
        offset_start: int = GET_EMAILS_OFFSET_START,
        offset_end: int = GET_EMAILS_OFFSET_END
    ) -> Mailbox:
        """
        Fetch emails from a list of uids.

        Args:
            offset_start (int, optional): Starting index of the emails to fetch. Defaults to 1.
            offset_end (int, optional): Ending index of the emails to fetch. Defaults to 10.

        Returns:
            Mailbox: Dataclass containing the fetched emails, folder, and total number of emails.

        Example:
            >>> get_emails(1, 2)
            Mailbox(folder='INBOX', emails=[Email(uid="1", sender="a@gmail.com", ...),
            Email(uid="2", sender="b@gmail.com", ...)], total=2)
        """
        if not self._searched_emails or not self._searched_emails.uids or not self._searched_emails.uids[0]:
            raise IMAPManagerException("No emails have been searched yet. Call `search_emails` first.")

        uids_len = len(self._searched_emails.uids)

        if offset_start and offset_end and offset_start > offset_end:
            raise ValueError(f"Invalid `offset_start`: `offset_start` must be less then `offset_end`.")

        if not offset_start:
            offset_start = GET_EMAILS_OFFSET_START
        elif offset_start < 1:
            raise ValueError(f"Invalid `offset_start`: {offset_start}. `offset_start` must be greater than or equal to 1.")

        if not offset_end:
            offset_end = GET_EMAILS_OFFSET_END
        elif offset_end < 1:
            raise ValueError(f"Invalid `offset_end`: {offset_end}. `offset_end` must be greater than or equal to 1.")

        if uids_len == 0:
            return Mailbox(folder=self._searched_emails.folder, emails=[], total=0)

        # Fetching emails
        sequence_set = ""
        emails = []
        try:
            offset_start = (uids_len - 1 if offset_start >= uids_len else offset_start) - 1
            offset_end = uids_len if offset_end >= uids_len else offset_end

            sequence_set = ",".join(map(str, self._searched_emails.uids[offset_start:offset_end][::-1]))
            status, messages = self.uid(
                'FETCH',
                sequence_set,
                '(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE CC BCC ' \
                'MESSAGE-ID IN-REPLY-TO REFERENCES LIST-UNSUBSCRIBE)] FLAGS ' \
                'BODYSTRUCTURE)'
            )

            if status != 'OK':
                raise IMAPManagerException(f"`{sequence_set}` in folder `{self._searched_emails.folder}` could not fetched `{len(emails)}`: `{status}`")

            if not messages or not messages[0]:
                return Mailbox(folder=self._searched_emails.folder, emails=[], total=0)

            messages = MessageParser.group_messages(messages)
            messages = messages[::-1]
            for message in messages:
                uid = MessageParser.get_uid(message[0])
                headers = MessageParser.get_headers(message[1])

                body_part = (
                    MessageParser.get_part(message[0], ["TEXT", "PLAIN"])
                    or
                    MessageParser.get_part(message[0], ["TEXT", "HTML"])
                )
                if not body_part:
                    body_part = "1"

                _, body = self.uid("FETCH", uid, f"(BODY.PEEK[{body_part}] BODY.PEEK[{body_part}.MIME])")
                if not body:
                    body = ""
                else:
                    body = MessageParser.group_messages(body)[0]
                    content_type, encoding = MessageParser.get_content_type_and_encoding(body[3])
                    body = MessageDecoder.body(
                        body[1],
                        encoding=encoding,
                        sanitize="html" not in content_type
                    )
                    if "html" in content_type:
                        body = HTMLParser.parse(body)

                emails.append(Email(
                    **headers,
                    uid=uid,
                    body=truncate_text(body, SHORT_BODY_MAX_LENGTH),
                    flags=MessageParser.get_flags(message[0]),
                    attachments=[
                        Attachment(
                            name=attachment[0],
                            size=attachment[1],
                            cid=attachment[2],
                            type=attachment[3]
                        )
                        for attachment in MessageParser.get_attachment_list(message[0])
                    ],
                ))
        except Exception as e:
            raise IMAPManagerException(f"Error while fetching emails `{sequence_set}` in folder `{self._searched_emails.folder}`, fetched email length was `{len(emails)}`") from e

        return Mailbox(folder=self._searched_emails.folder, emails=emails, total=uids_len)

    def get_email_content(self,
        folder: str,
        uid: str
    ) -> Email:
        """
        Retrieve full content of a specific email.

        Args:
            folder (str): Folder containing the email.
            uid (str): Unique identifier of the email.

        Returns:
            Email: Dataclass containing the email content.

        Example:
            >>> get_email_content("1", Folder.Inbox)
            Email(uid="1", sender="a@gmail.com", ...)

        Notes:
            - Replaces inline attachments with data URLs to display them inline
            and if an error occurs while replacing the inline attachments, the
            replacement operation will be skipped without raising an error but
            it will be logged as a warning.
            - Marks the email as "Seen" if it is not already and if an error
            occurs while marking the email, the mark operation will be skipped
            without raising an error but it will be logged as a warning.
        """
        self.select(folder, readonly=True)

        # Get body and attachments
        body = ""
        inline_attachments = []
        try:
            status, message = self.uid(
                'fetch',
                uid,
                '(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE CC BCC ' \
                'MESSAGE-ID IN-REPLY-TO REFERENCES LIST-UNSUBSCRIBE CONTENT-' \
                'TRANSFER-ENCODING)] FLAGS BODYSTRUCTURE BODY[1])'
            )
            if status != 'OK':
                raise IMAPManagerException(f"Error while getting email `{uid}`'s content in folder `{folder}`: `{status}`")

            if not message or not message[0]:
                raise ValueError(f"No email found with given {uid} uid.")

            message = MessageParser.group_messages(message)[0]
            headers = MessageParser.get_headers(message[3])
            flags = MessageParser.get_flags(message[0])
            _, encoding = MessageParser.get_content_type_and_encoding(message[3])
            for attachment in MessageParser.get_inline_attachment_list(message[2]):
                inline_attachments.append(Attachment(
                    name=attachment[0],
                    size=attachment[1],
                    cid=attachment[2],
                    type=attachment[3],
                ))

            body = (
                MessageParser.get_text_html_body(message[1])
                or
                MessageParser.get_text_plain_body(message[1])
                or
                (-1, -1, MessageDecoder.body(message[1], encoding=encoding))
            )

            start, end, body = body
            if start >= 0 and end >= 0:
                try:
                    for cid, data in MessageParser.get_cid_and_data_of_inline_attachments(
                        message[1][:start] + message[1][end:]
                    ):
                        i = 0
                        while i < len(inline_attachments):
                            if inline_attachments[i].cid == cid:
                                body = body.replace(
                                    f'cid:{inline_attachments[i].cid}',
                                    f'data:{inline_attachments[i].type};base64,{data}'
                                )
                                del inline_attachments[i]
                            else:
                                i += 1
                except Exception as e:
                    # If there is a problem with inline attachments
                    # just ignore them.
                    print(f"An error occurred while replacing inline attachments: `{str(e)}` of email `{uid}`'s content in folder `{folder}`.")
                    pass
        except Exception as e:
            raise IMAPManagerException(f"There was a problem with getting email `{uid}`'s content in folder `{folder}`: `{str(e)}`") from e

        return Email(
            **headers,
            uid=uid,
            body=body,
            flags=flags,
            attachments=[
                Attachment(
                    name=attachment[0],
                    size=attachment[1],
                    cid=attachment[2],
                    type=attachment[3]
                )
                for attachment in MessageParser.get_attachment_list(message[2])
            ]
        )

    def get_email_flags(self, sequence_set: str) -> list[Flags]:
        """
        Retrieve flags associated with a specific email.

        Args:
            sequence_set (str): The sequence set of the email to fetch flags for.

        Returns:
            list[Flags]: A list of Flags objects representing the flags associated with the email.

        Example:
            >>> get_email_flags("1")
            [Flags(uid="1", flags=["\\Seen", "\\Answered"])]
            >>> get_email_flags("1,2,3")
            [Flags(uid="1", flags=["\\Seen", "\\Answered"]), Flags(uid="2", flags=["\\Answered"]), Flags(uid="3", flags=["\\Flagged"])]
            >>> get_email_flags("1:3")
            [Flags(uid="1", flags=["\\Seen", "\\Answered"]), Flags(uid="2", flags=["\\Answered"]), Flags(uid="3", flags=["\\Flagged"])]
            >>> get_email_flags("1,3:4")
            [Flags(uid="1", flags=["\\Seen", "\\Answered"]), Flags(uid="3", flags=["\\Flagged"]), Flags(uid="4", flags=["\\Flagged"])]
            >>> get_email_flags("1:*") # In this case, mailbox has 3 emails
            [Flags(uid="1", flags=["\\Seen", "\\Answered"]), Flags(uid="2", flags=["\\Answered"]), Flags(uid="3", flags=["\\Flagged"])]
            >>> get_email_flags("1,3:*") # In this case, mailbox has 4 emails
            [Flags(uid="1", flags=["\\Seen", "\\Answered"]), Flags(uid="3", flags=["\\Flagged"]), Flags(uid="4", flags=["\\Flagged"])]

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        if self.state != "SELECTED":
            # Since uid's are unique within each mailbox, we can't just select INBOX
            # or something like that if there is no mailbox selected.
            raise IMAPManagerException("Folder should be selected before fetching flags.")

        status, message = self.uid('FETCH', sequence_set, '(FLAGS)')

        try:
            flags_list = []
            if status != 'OK':
                raise IMAPManagerException(f"Error while fetching flags of email `{sequence_set}`: `{status}`")

            message = MessageParser.group_messages(message)[0]
            for part in message:
                flags_list.append(Flags(
                    uid=MessageParser.get_uid(part),
                    flags=MessageParser.get_flags(part)
                ))
        except Exception as e:
            raise IMAPManagerException(f"Error while fetching flags of email `{sequence_set}`: `{e}`") from e

        return flags_list or []

    def get_email_size(self, folder: str, uid: str) -> int | None:
        """
        Get email size of the given `uid`.

        Args:
            folder (str): Folder containing the email.
            uid (str): Unique identifier of the email.

        Returns:
            int: Size of the email as bytes.

        Example:
            >>> get_email_size("1", "INBOX")
            24300
        """
        status, messages = self.uid('FETCH', uid, '(RFC822.SIZE)')
        if status != 'OK':
            raise IMAPManagerException(f"Error while getting size of the `{uid}` email in folder `{folder}`: `{status}`")

        return MessageParser.get_size(messages[0])

    def download_attachment(self,
        folder: str,
        uid: str,
        name: str,
        cid: str = ""
    ) -> Attachment:
        """
        Download an attachment from an email.

        Args:
            folder (str): Folder containing the email.
            uid (str): Unique identifier of the email.
            name (str): Name of the attachment file to download.
            cid (str, optional): Content ID of the attachment (default is an empty string).

        Returns:
            Attachment: An object containing metadata (name, size, CID, type) and data of the attachment.

        Raises:
            IMAPManagerException: If the body structure of the email cannot be fetched,
                                  the attachment is not found, or there is an error during the fetching process.

        Example:
            >>> attachment = download_attachment("1", "INBOX", "example.pdf")
            >>> print(attachment.name)
            'example.pdf'
        """
        self.select(folder, readonly=True)

        status, message = self.uid('FETCH', uid, '(BODYSTRUCTURE)')
        if status != 'OK':
            raise IMAPManagerException(f"Error while fetching body structure of the `{uid}` email in folder `{folder}`: `{status}`")

        if not message or not message[0]:
            raise ValueError(f"No attachment found in `{uid}` uid in `{folder}` folder with given `{name}` and `{cid}` cid.")

        attachment_list = MessageParser.get_attachment_list(message[0])
        target_attachment = [attachment for attachment in attachment_list if attachment[0] == name][0]
        target_attachment = Attachment(
            name=target_attachment[0],
            size=target_attachment[1],
            cid=target_attachment[2],
            type=target_attachment[3]
        )

        try:
            target_part = MessageParser.get_part(message[0], ["FILENAME", '"' + name + '"', cid])
            if not target_part:
                raise IMAPManagerException(f"Error, target attachment could not found in the email body.")

            status, message = self.uid('FETCH', uid, f'(BODY[{target_part}])')
            if status != 'OK':
                raise IMAPManagerException(f"Error while fetching attachment part of the `{uid}` email in folder `{folder}`: `{status}`")

            target_attachment.data = message[0][1].decode()
        except:
            raise IMAPManagerException(f"Error while fetching attachment part of the `{uid}` email in folder `{folder}`: `{status}`")

        return target_attachment

    def _mark_email(
        self,
        mark:  str | Mark,
        sequence_set: str,
        command: str,
        folder: str,
        success_msg: str,
        err_msg: str
    ) -> IMAPCommandResult:
        """
        Mark an email with a specific flag with given `command`.

        Args:
            mark (str): Flag to apply to the email.
            sequence_set (str): Sequence set of emails to mark.
            command (str): IMAP command to apply the flag like `+FLAGS` or `-FLAGS`.
            folder (str): Folder containing the email.
            success_msg (str): Success message to display.
            err_msg (str): Error message to display.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was marked successfully.
                - A string containing a success message or an error message.
        """
        self.select(folder)

        if not mark:
            raise IMAPManagerException("`mark` cannot be empty.")

        mark_result = self._parse_command_result(
            self.uid(
                'STORE',
                sequence_set,
                command,
                mark
            ),
            success_msg,
            err_msg
        )

        if mark_result[0]:
            return self._parse_command_result(
                self.expunge(),
                success_msg,
                err_msg
            )

        return mark_result

    def mark_email(
        self,
        mark: str | Mark,
        sequence_set: str,
        folder: str = Folder.Inbox
    ) -> IMAPCommandResult:
        """
        Mark an email with a specific flag.

        Args:
            mark (str): Flag to apply to the email.
            sequence_set (str): Sequence set of emails to mark.
            folder (str, optional): Folder containing the email.
            Defaults to "inbox".

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was marked successfully.
                - A string containing a success message or an error message.

        Example:
            >>> mark_email(Mark.Seen, "1") # Marks email with UID 1 from INBOX
            >>> mark_email(Mark.Seen, "1,2,3") # Marks emails with UID 1,2,3 from INBOX
            >>> mark_email(Mark.Seen, "1:3") # Marks email with UID 1,2,3 from INBOX
            >>> mark_email(Mark.Seen, "1,3:5") # Marks email with UID 1 and 3,4,5 from INBOX
            >>> mark_email(Mark.Seen, "1:*") # Marks all emails in the INBOX
            >>> mark_email(Mark.Seen, "1,3:*") # Marks all emails in the INBOX, except email with UID 2

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        return self._mark_email(
            mark,
            sequence_set,
            "+FLAGS",
            folder,
            f"Email(s) `{sequence_set}` in `{folder}` marked with `{mark}` successfully.",
            f"There was an error while marking the email(s) `{sequence_set}` in `{folder}` with `{mark}`."
        )

    def unmark_email(
        self,
        mark: str | Mark,
        sequence_set: str,
        folder: str = Folder.Inbox,
    ) -> IMAPCommandResult:
        """
        Unmark an email with a specific flag.

        Args:
            mark (str): Flag to remove from the email.
            sequence_set (str): Sequence set of emails to unmark.
            folder (str, optional): Folder containing the email. Defaults to "inbox".

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was unmarked successfully.
                - A string containing a success message or an error message.

        Example:
            >>> unmark_email(Mark.Seen, "1") # Removes Seen flag from email with UID 1
            >>> unmark_email(Mark.Seen, "1,2,3") # Removes Seen flag from emails with UID 1,2,3
            >>> unmark_email(Mark.Seen, "1:3") # Removes Seen flag from emails with UID 1,2,3
            >>> unmark_email(Mark.Seen, "1,3:5") # Removes Seen flag from emails with UID 1 and 3,4,5
            >>> unmark_email(Mark.Seen, "1:*") # Removes Seen flag from all emails
            >>> unmark_email(Mark.Seen, "1,3:*") Removes Seen flag from all emails, except email with UID 2

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        return self._mark_email(
            mark,
            sequence_set,
            "-FLAGS",
            folder,
            f"{mark} removed from email(s) `{sequence_set}` in `{folder}` successfully.",
            f"There was an error while unmarking the email(s) `{sequence_set}` in `{folder}` with `{mark}`."
        )

    def move_email(self,
        source_folder: str,
        destination_folder: str,
        sequence_set: str,
    ) -> IMAPCommandResult:
        """
        Move an email from one folder to another.

        Args:
            source_folder (str): Current folder of the email.
            destination_folder (str): Target folder to move the email to.
            sequence_set (str): Sequence set of emails to move.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was moved successfully.
                - A string containing a success message or an error message.

        Example:
            >>> move_email("INBOX", "ARCHIVE", "1") # Moves email with UID 1 from INBOX to SENT
            >>> move_email("INBOX", "ARCHIVE", "1,2,3") # Moves emails with UID 1,2,3 from INBOX to SENT
            >>> move_email("INBOX", "ARCHIVE", "1:3") # Moves emails with UID 1,2,3 from INBOX to SENT
            >>> move_email("INBOX", "ARCHIVE", "1,3:5") # Moves emails with UID 1 and 3,4,5 from INBOX to SENT
            >>> move_email("INBOX", "ARCHIVE", "1:*") # Moves all emails in the INBOX to ARCHIVE folder
            >>> move_email("INBOX", "ARCHIVE", "1,3:*") # Moves all emails in the INBOX to ARCHIVE folder, except email with UID 2

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        self._check_folder_names([source_folder, destination_folder])

        if source_folder == destination_folder:
            return IMAPCommandResult(
                success=True,
                message=f"Destination folder `{destination_folder}` is the same as the source folder `{source_folder}`."
            )

        self.select(source_folder)

        succes_msg = f"Email(s) `{sequence_set}` moved successfully from `{source_folder}` to `{destination_folder}`."
        err_msg = f"Failed to move email(s) `{sequence_set}` from `{source_folder}` to `{destination_folder}`."

        move_result = self._parse_command_result(
            self.uid(
                'MOVE',
                sequence_set,
                self._encode_folder(destination_folder)
            ),
            succes_msg,
            err_msg
        )

        if move_result[0]:
            return self._parse_command_result(
                self.expunge(),
                succes_msg,
                err_msg
            )

        return move_result

    def copy_email(self,
        source_folder: str,
        destination_folder: str,
        sequence_set: str,
    ) -> IMAPCommandResult:
        """
        Create a copy of an email in another folder.

        Args:
            source_folder (str): Current folder of the email.
            destination_folder (str): Target folder to copy the email to.
            sequence_set (str): Sequence set of emails to copy.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was copied successfully.
                - A string containing a success message or an error message.

        Example:
            >>> copy_email("INBOX", "ARCHIVE", "1") # Copies email with UID 1 to ARCHIVE from INBOX.
            >>> copy_email("INBOX", "ARCHIVE", "1,2,3") # Copies emails with UID 1, 2, 3 to ARCHIVE from INBOX.
            >>> copy_email("INBOX", "ARCHIVE", "1:3") # Copies emails with UID 1,2,3 to ARCHIVE from INBOX.
            >>> copy_email("INBOX", "ARCHIVE", "1,3:5") # Copies email with UID 1 and 3,4,5 to ARCHIVE from INBOX.
            >>> copy_email("INBOX", "ARCHIVE", "1:*") # Copies all emails in the INBOX to ARCHIVE folder
            >>> copy_email("INBOX", "ARCHIVE", "1,3:*") # Copies all emails in the INBOX to ARCHIVE folder, except email with UID 2

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        self._check_folder_names([source_folder, destination_folder])

        self.select(source_folder)

        succes_message = f"Email(s) `{sequence_set}` copied successfully from `{source_folder}` to `{destination_folder}`."
        err_msg = f"Failed to copy email(s) `{sequence_set}` from `{source_folder}` to `{destination_folder}`."

        copy_result = self._parse_command_result(
            self.uid(
                'COPY',
                sequence_set,
                self._encode_folder(destination_folder)
            ),
            succes_message,
            err_msg
        )

        if copy_result[0]:
            return self._parse_command_result(
                self.expunge(),
                succes_message,
                err_msg
            )

        return copy_result

    def delete_email(self, folder: str, sequence_set: str) -> IMAPCommandResult:
        """
        Delete an email from a specific folder.

        Args:
            folder (str): Folder containing the email.
            sequence_set (str): Sequence set of emails to delete.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the email was deleted successfully.
                - A string containing a success message or an error message.

        Example:
            >>> delete_email("INBOX", "1") # Deletes email with UID 1
            >>> delete_email("INBOX", "1,2,3") # Deletes emails with UID 1,2, 3
            >>> delete_email("INBOX", "1:3") # Deletes emails with UID 1,2,3
            >>> delete_email("INBOX", "1,3:5") # Deletes emails with UID 1 and 3,4,5
            >>> delete_email("INBOX", "1:*") # Deletes all emails in the folder
            >>> delete_email("INBOX", "1,3:*") # Deletes all emails in the folder except email with UID 2

        References:
            https://datatracker.ietf.org/doc/html/rfc9051#name-formal-syntax (check sequence-set for more information.)
        """
        self._check_folder_names(folder)

        try:
            trash_mailbox_name = self.find_matching_folder(Folder.Trash, False)
            if folder != trash_mailbox_name or folder != Folder.Trash:
                status, _ = self.move_email(folder, trash_mailbox_name, sequence_set)
                if not status:
                    raise IMAPManagerException(
                        f"Error while moving email(s) `{sequence_set}` to trash folder for deletion."
                    )
        except Exception as e:
            raise IMAPManagerException(
                f"Error while moving email(s) `{sequence_set}` to trash folder for deletion: `{str(e)}`."
            ) from e

        self.select(self._encode_folder(trash_mailbox_name))

        success_msg = f"Email(s) `{sequence_set}` deleted from `{folder}` successfully."
        err_msg = f"There was an error while deleting the email(s) `{sequence_set}` from `{folder}`."

        delete_result = self._parse_command_result(
            self.uid(
                'STORE',
                sequence_set,
                '+FLAGS',
                '\\Deleted'
            ),
            success_msg,
            err_msg
        )

        if delete_result[0]:
            return self._parse_command_result(
                self.expunge(),
                success_msg,
                err_msg
            )

        return delete_result

    def create_folder(self,
        folder_name: str,
        parent_folder: str | None = None
    ) -> IMAPCommandResult:
        """
        Create a new email folder.

        Args:
            folder_name (str): Name of the new folder.
            parent_folder (str, optional): Parent folder for nested folder creation.
                                           Defaults to None.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the folder was created successfully.
                - A string containing a success message or an error message.

        Example:
            >>> create_folder("RED")
            (True, "Folder `RED` created successfully.")
            >>> create_folder("BLUE", "COLORS") # BLUE will be created under COLORS like `COLORS/BLUE`
            (True, "Folder `BLUE` created successfully.")
            >>> create_folder("DARKBLUE", "COLORS/DARK") # DARKBLUE will be created under DARK like `COLORS/DARK/DARKBLUE`
            (True, "Folder `DARKBLUE` created successfully.")
        """
        self._check_folder_names([folder_name, parent_folder])

        if parent_folder:
            if parent_folder not in self.get_folders():
                self.create_folder(parent_folder)

            folder_name = f"{parent_folder}/{folder_name}"

        return self._parse_command_result(
            self.create(
                self._encode_folder(folder_name)
            ),
            f"Folder `{folder_name}` created successfully.",
            f"There was an error while creating folder `{folder_name}`."
        )

    def delete_folder(self, folder_name: str, subfolders: bool = False) -> IMAPCommandResult:
        """
        Delete an existing email folder.

        Args:
            folder_name (str): Name of the folder to delete.
            subfolders (bool, optional): Whether to also delete subfolders.
                                        Defaults to False.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the folder was deleted successfully.
                - A string containing a success message or an error message.

        Example:
            >>> delete_folder("RED") # RED/LIGHTRED, RED/DARKRED wont be deleted.
            (True, "Folder `RED` deleted successfully.")
            >>> delete_folder("RED", true) # RED/LIGHTRED, RED/DARKRED will be deleted.
            (True, "Folder `RED` deleted successfully.")
        """
        self._check_folder_names(folder_name)

        if subfolders:
            for subfolder in self.get_folders(folder_name):
                self.delete_folder(subfolder, True)

        return self._parse_command_result(
            self.delete(
                self._encode_folder(folder_name)
            ),
            f"Folder `{folder_name}` deleted successfully.",
            f"There was an error while deleting folder `{folder_name}`."
        )

    def move_folder(self, folder_name: str, destination_folder: str) -> IMAPCommandResult:
        """
        Move a folder to a new location.

        Args:
            folder_name (str): Name of the folder to move.
            destination_folder (str): Target location for the folder.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the folder was moved successfully.
                - A string containing a success message or an error message.

        Example:
            >>> move_folder("RED", "COLORS")
            (True, "Folder `RED` moved to `COLORS` successfully. New location is `COLORS/RED`")
            >>> move_folder("RED", "COLORS/DARK") # Subfolders of `RED` will be also moved under `COLORS/DARK`.
            (True, "Folder `RED` moved to `COLORS/DARK` successfully. New location is `COLORS/DARK/RED`")
            >>> move_folder("RED/DARKRED", "COLORS")
            (True, "Folder `RED/DARKRED` moved to `COLORS` successfully. New location is `COLORS/DARKRED`")
            >>> move_folder("RED/DARKRED", "COLORS/DARK")
            (True, "Folder `RED/DARKRED` moved to `COLORS/DARK` successfully. New location is `COLORS/DARK/DARKRED`")
        """
        self._check_folder_names([folder_name, destination_folder])

        *folder_name_parent, folder_name_target = folder_name.split("/")
        if "/".join(folder_name_parent) in self.get_folders():
            destination_folder = f"{destination_folder}/{folder_name_target}"
        else:
            destination_folder = f"{destination_folder}/{folder_name}"

        return self._parse_command_result(
            self.rename(
                self._encode_folder(folder_name),
                self._encode_folder(destination_folder)
            ),
            f"Folder `{folder_name}` moved to `{destination_folder}` successfully.",
            f"There was an error while moving folder `{folder_name}` to `{destination_folder}`."
        )

    def rename_folder(self, folder_name: str, new_folder_name: str) -> IMAPCommandResult:
        """
        Rename an existing email folder.

        Args:
            folder_name (str): Current name of the folder.
            new_folder_name (str): New name for the folder.

        Returns:
            IMAPCommandResult: A tuple containing:
                - A bool indicating whether the folder was renamed successfully.
                - A string containing a success message or an error message.

        Example:
            >>> rename_folder("RED", "BLUE")
            (True, "Folder `RED` renamed to `BLUE` successfully.")
            >>> rename_folder("BLUE/DARKBLUE", "LIGHTBLUE")
            (True, "Folder `BLUE/DARKBLUE` renamed to `BLUE/LIGHTBLUE` successfully.")
        """
        self._check_folder_names([folder_name, new_folder_name])

        *folder_name_parent, _ = folder_name.split("/")
        folder_name_parent = "/".join(folder_name_parent)
        if folder_name_parent in self.get_folders():
            new_folder_name = f"{folder_name_parent}/{new_folder_name}"

        return self._parse_command_result(
            self.rename(
                self._encode_folder(folder_name),
                self._encode_folder(new_folder_name)
            ),
            f"Folder `{folder_name}` renamed to `{new_folder_name}` successfully.",
            f"There was an error while renaming folder `{folder_name}` to `{new_folder_name}`."
        )

__all__ = [
    "IMAPManager",
    "IMAPCommandResult",
    "IMAPManagerException",
    "IMAPManagerLoggedOutException",
    "Mark",
    "Folder"
]
