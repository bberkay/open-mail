import logging, sys, json

from logging.handlers import RotatingFileHandler
from filesystem import FileSystem
from utils import make_size_human_readable
from consts import APP_NAME

class LogHandler(logging.Logger):
    def __init__(self):
        super().__init__(APP_NAME)
        self.name = APP_NAME

    def init(self):
        self.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        stream_handler = logging.StreamHandler(sys.stdout)
        file_handler = RotatingFileHandler(FileSystem().UVICORN_LOG_FILE_PATH, maxBytes=1*1024*1024, backupCount=5)
        stream_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)
        self.addHandler(stream_handler)
        self.addHandler(file_handler)

    def __summarize_data(self, response_data: any) -> any:
        if isinstance(response_data, dict):
            return {key: self.__summarize_data(value) for key, value in response_data.items()}
        elif isinstance(response_data, list):
            return self.__summarize_data(str(response_data))
        elif isinstance(response_data, str) and len(response_data) >= 100:
            return response_data[:256] + '...' + (']' if response_data.startswith('[') else '')
        return response_data

    def __load_data(self, response_body: bytes) -> any:
        try:
            return json.loads(response_body)
        except Exception as e:
            return response_body.decode("utf-8")

    def request(self, request, response):
        try:
            response_data = self.__load_data(response._body)
            log_message = (
                f"{request.method} {request.url} - {response.status_code} - "
                f"{self.__summarize_data(response_data)} - "
                f"{make_size_human_readable(int(response.headers.get('content-length')))}"
            )
            if response.status_code >= 400:
                self.error(log_message)
            elif response.status_code != 307: # Temporary Redirect
                self.info(log_message)
        except Exception as e:
            self.error(f"Error while logging request and response: {e}")
