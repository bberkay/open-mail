export enum TauriCommand {
    GET_SERVER_URL = "get_server_url",
}

export interface Account {
    email_address: string;
    fullname?: string;
}

export interface EmailSummary {
    uid: string;
    sender: string | [string, string];
    receiver: string;
    date: string;
    subject: string;
    body_short: string;
    flags?: string[];
    attachments?: Attachment[];
}

export interface EmailWithContent {
    uid: string;
    sender: string | [string, string];
    receiver: string;
    date: string;
    subject: string;
    body: string;
    cc?: string;
    bcc?: string;
    flags?: string[];
    attachments?: Attachment[];
    message_id?: string;
    metadata?: Record<string, string>;
}

export interface SearchCriteria {
    senders?: string[];
    receivers?: string[];
    cc?: string[];
    bcc?: string[];
    subject?: string;
    since?: string;
    before?: string;
    included_flags?: string[];
    excluded_flags?: string[];
    smaller_than?: number;
    larger_than?: number;
    include?: string;
    exclude?: string;
    has_attachments?: boolean;
}

export interface Attachment {
    path?: string;
    name?: string;
    data?: string;
    size?: string;
    type?: string;
    cid?: string | null;
}

export interface EmailToSend {
    sender: string | [string, string];
    receiver: string;
    //date: string;
    subject: string;
    body: string;
    uid?: string;
    cc?: string;
    bcc?: string;
    metadata?: Record<string, string>;
    attachments?: Attachment[];
    mail_options?: string[];
    rcpt_options?: string[];
}

export interface OpenMailTaskResult<T> {
    email_address: string;
    result: T;
}

export type OpenMailTaskResults<T> = OpenMailTaskResult<T>[];

export interface Mailbox {
    folder: string;
    emails: EmailSummary[];
    total: number;
}

export interface Flags {
    uid: string;
    flags: string[];
}
