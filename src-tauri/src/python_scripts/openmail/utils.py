import base64, re, datetime

def decode_modified_utf7(s: str) -> str:
    def modified_base64_decode(s):
        s = s.replace(',', '/')
        return base64.b64decode(s + '===').decode('utf-16-be')

    s = re.sub(r'&([^-]*)-', lambda m: modified_base64_decode(m.group(1)) if m.group(1) else '&', s)
    return s

def encode_modified_utf7(s: str) -> str:
    def modified_base64_encode(s):
        b64_encoded = base64.b64encode(s.encode('utf-16-be')).decode('ascii')
        return b64_encoded.rstrip('=').replace('/', ',')

    encoded_parts = []
    i = 0
    while i < len(s):
        if ord(s[i]) > 127:
            start = i
            while i < len(s) and ord(s[i]) > 127:
                i += 1
            encoded_parts.append('&' + modified_base64_encode(s[start:i]) + '-')
        else:
            start = i
            while i < len(s) and ord(s[i]) <= 127:
                i += 1
            encoded_parts.append(s[start:i])

    return ''.join(encoded_parts)

def choose_positive(var1: int, var2: int) -> int:
    return var1 if var1 > 0 else var2

def extract_domain(email: str) -> str:
    return email.split('@')[1].split(".")[0]

def check_json_value(json: dict, key: str) -> str:
    return json[key] if key in json and json[key] else ""

def convert_to_imap_date(date: str) -> str:
    # 1970-01-01 to 01-Jan-1970
    # https://datatracker.ietf.org/doc/html/rfc5322#section-3.3
    return datetime.datetime.strptime(date, '%Y-%m-%d').strftime('%d-%b-%Y')