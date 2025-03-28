import {
    type Email,
    type Account,
    type Mailbox,
    type OpenMailTaskResults,
} from "../types";

export enum SharedStoreKeys {
    server = "server",
    accounts = "accounts",
    failedAccounts = "failedAccounts",
    mailboxes = "mailboxes",
    recentEmails = "recentEmails",
    standardFolders = "standardFolders",
    customFolders = "customFolders",
    currentAccount = "currentAccount",
    currentMailbox = "currentMailbox",
}

interface ISharedStore {
    [SharedStoreKeys.server]: string;
    [SharedStoreKeys.accounts]: Account[];
    [SharedStoreKeys.failedAccounts]: Account[];
    [SharedStoreKeys.recentEmails]: OpenMailTaskResults<Email[]>;
    [SharedStoreKeys.mailboxes]: OpenMailTaskResults<Mailbox>
    [SharedStoreKeys.standardFolders]: OpenMailTaskResults<string[]>;
    [SharedStoreKeys.customFolders]: OpenMailTaskResults<string[]>;
    [SharedStoreKeys.currentAccount]: "home" | Account;
    [SharedStoreKeys.currentMailbox]: Mailbox
}

export let SharedStore: { [K in SharedStoreKeys]: ISharedStore[K] } = $state({
    [SharedStoreKeys.server]: "",
    [SharedStoreKeys.accounts]: [],
    [SharedStoreKeys.failedAccounts]: [],
    [SharedStoreKeys.recentEmails]: {},
    [SharedStoreKeys.mailboxes]: {},
    [SharedStoreKeys.standardFolders]: {},
    [SharedStoreKeys.customFolders]: {},
    [SharedStoreKeys.currentAccount]: "home",
    [SharedStoreKeys.currentMailbox]: { folder: "", emails: { prev: [], current: [], next: [] } , total: 0},
});
