<script lang="ts">
    import {
        isPermissionGranted,
        requestPermission,
        sendNotification,
    } from "@tauri-apps/plugin-notification";
    import { SharedStore } from "$lib/stores/shared.svelte";
    import { AccountController } from "$lib/controllers/AccountController";
    import { MailboxController } from "$lib/controllers/MailboxController";
    import {
        getFailedAccountsTemplate,
        getFailedItemTemplate,
        getSelectedAccountTemplate,
    } from "$lib/templates";
    import { Folder, type Account } from "$lib/types";
    import * as Button from "$lib/ui/Components/Button";
    import * as Input from "$lib/ui/Components/Input";
    import * as Table from "$lib/ui/Components/Table";
    import Pagination from "$lib/ui/Components/Pagination";
    import { show as showAlert } from "$lib/ui/Components/Alert";
    import { show as showMessage } from "$lib/ui/Components/Message";
    import { show as showConfirm } from "$lib/ui/Components/Confirm";
    import { createSenderAddress, isStandardFolder } from "$lib/utils";
    import { DEFAULT_LANGUAGE } from "$lib/constants";
    import { local } from "$lib/locales";

    interface Props {
        editAccount: (account: Account) => void;
        onCancel: () => void;
    }

    let { editAccount, onCancel }: Props = $props();

    const allAccounts = SharedStore.failedAccounts.concat(SharedStore.accounts);
    let accounts = $state(allAccounts);
    let accountSelection: string[] = $state([]);

    const selectAllAccounts = (event: Event) => {
        const selectAllCheckbox = event.target as HTMLInputElement;
        accountSelection = selectAllCheckbox.checked
            ? SharedStore.failedAccounts
                  .concat(SharedStore.accounts)
                  .map((account) => account.email_address)
            : [];
    };

    const removeAccount = async (e: Event): Promise<void> => {
        showConfirm({
            title: local.are_you_certain_remove_account[DEFAULT_LANGUAGE],
            onConfirmText: local.yes_remove[DEFAULT_LANGUAGE],
            onConfirm: async (e: Event) => {
                const target = e.target as HTMLButtonElement;
                const account = target.getAttribute("data-email-address")!;
                const response = await AccountController.remove(account);

                if (!response.success) {
                    showMessage({
                        title: local.error_remove_account[DEFAULT_LANGUAGE],
                    });
                    console.error(response.message);
                }
            },
        });
    };

    const removeAllAccounts = async (): Promise<void> => {
        showConfirm({
            title: local.are_you_certain_remove_all_accounts[DEFAULT_LANGUAGE],
            onConfirmText: local.remove_all[DEFAULT_LANGUAGE],
            onConfirm: async (e: Event) => {
                const response = await AccountController.removeAll();

                if (!response.success) {
                    showMessage({
                        title: local.error_remove_all_account[DEFAULT_LANGUAGE],
                    });
                    console.error(response.message);
                }
            },
        });
    };

    const searchAccounts = (e: Event) => {
        const target = e.target as HTMLInputElement;
        if (target.value.length > 3) {
            accounts = allAccounts.filter(
                (account) =>
                    account.email_address.includes(target.value) ||
                    account.fullname?.includes(target.value),
            );
        } else {
            accounts = allAccounts;
        }
    };

    async function initMailboxes(): Promise<void> {
        const response = await MailboxController.init();
        if (!response.success) {
            console.error(response.message);
            showMessage({
                title: local.error_initialize_mailboxes[DEFAULT_LANGUAGE],
            });
        }
        // TODO: Open this later.
        //await listenForNotifications();
    }

    /**
     * Create WebSocket connections
     * for every account to receive
     * new email notifications.
     */
    async function listenForNotifications() {
        SharedStore.accounts.forEach(async (account) => {
            const ws = new WebSocket(
                SharedStore.server.replace("http", "ws") +
                    `/notifications/${account}`,
            );

            let permissionGranted = false;
            ws.onopen = async () => {
                permissionGranted = await isPermissionGranted();
                if (!permissionGranted) {
                    const permission = await requestPermission();
                    permissionGranted = permission === "granted";
                }

                SharedStore.recentEmails[account.email_address] = [];
            };

            ws.onmessage = (e: MessageEvent) => {
                // Send app notification.
                if (permissionGranted) {
                    sendNotification({
                        title: local.new_email_received_title[DEFAULT_LANGUAGE],
                        body: local.new_email_received_body[DEFAULT_LANGUAGE],
                    });
                }

                Object.entries(
                    e.data as typeof SharedStore.recentEmails,
                ).forEach((entry) => {
                    const emailAddr = entry[0];
                    const recentEmails = entry[1];

                    // Add email summary of recent email to the top of the
                    // current and shift emails that are overflowed from current
                    // to next.
                    if (
                        Object.hasOwn(SharedStore.mailboxes, emailAddr) &&
                        isStandardFolder(
                            SharedStore.mailboxes[emailAddr].folder,
                            Folder.Inbox,
                        )
                    ) {
                        const recentEmailsLength = recentEmails.length;
                        SharedStore.mailboxes[emailAddr].emails.current.unshift(
                            ...recentEmails,
                        );
                        const overflowEmails = SharedStore.mailboxes[
                            emailAddr
                        ].emails.current.splice(-1 * recentEmailsLength);
                        SharedStore.mailboxes[emailAddr].emails.next.unshift(
                            ...overflowEmails,
                        );
                        SharedStore.mailboxes[emailAddr].emails.next.splice(
                            -1 * recentEmailsLength,
                            recentEmailsLength,
                        );
                    }

                    // Fetch email content of recent email and add it into recentEmails.
                    if (Object.hasOwn(SharedStore.recentEmails, emailAddr)) {
                        for (const recentEmail of recentEmails) {
                            MailboxController.getEmailContent(
                                SharedStore.accounts.find(
                                    (account) =>
                                        account.email_address === emailAddr,
                                )!,
                                Folder.Inbox,
                                recentEmail.uid,
                            ).then((response) => {
                                if (response.success && response.data) {
                                    SharedStore.recentEmails[emailAddr].push(
                                        response.data,
                                    );
                                }
                            });
                        }
                    }
                });
            };

            ws.onclose = (e: CloseEvent) => {
                if (e.reason && e.reason.toLowerCase().includes("error")) {
                    console.error(e.reason);
                }
            };
        });
    }

    $effect(() => {
        if (SharedStore.failedAccounts.length > 0) {
            showAlert("accounts-alert-container", {
                content: local.accounts_failed_to_connect[DEFAULT_LANGUAGE],
                type: "error",
                details: getFailedAccountsTemplate(
                    SharedStore.failedAccounts
                        .map((account) => {
                            return getFailedItemTemplate(
                                createSenderAddress(
                                    account.email_address,
                                    account.fullname,
                                ),
                            );
                        })
                        .join(""),
                ),
                onManageText: local.manage_accounts[DEFAULT_LANGUAGE],
                onManage: () => {
                    editAccount(SharedStore.failedAccounts[0]);
                },
                closeable: false,
            });
        }
    });
</script>

<div>
    <div class="alert-container" id="accounts-alert-container"></div>
    {#if (SharedStore.accounts && SharedStore.accounts.length > 0) || (SharedStore.failedAccounts && SharedStore.failedAccounts.length > 0)}
        {@const failedAccountLength = (SharedStore.failedAccounts || []).length}
        <div class="accounts-info">
            <div class="account-count">
                <h3>All accounts <span>{allAccounts.length}</span></h3>
            </div>
            <div class="account-list-operations">
                <Input.Basic type="text" onkeydown={searchAccounts} />
                <Button.Basic type="button" class="btn-outline" onclick={onCancel}>
                    {local.add_another_account[DEFAULT_LANGUAGE]}
                </Button.Basic>
            </div>
        </div>
        <Table.Root>
            <Table.Header>
                <Table.Row>
                    <Table.Head class="checkbox-cell">
                        <!-- TODO: Convert to select shown button after pagination implementation. -->
                        <!-- TODO: Show select all button after select shown is checked. -->
                        <Input.Basic
                            type="checkbox"
                            onclick={selectAllAccounts}
                        />
                    </Table.Head>
                    <Table.Head class="body-cell">
                        {accountSelection.length > 0
                            ? getSelectedAccountTemplate(
                                  accountSelection.length.toString(),
                              )
                            : local.account[DEFAULT_LANGUAGE]}
                    </Table.Head>
                    <Table.Head>
                        {#if accountSelection.length > 0}
                            <Button.Action
                                class="btn-inline"
                                onclick={removeAllAccounts}
                            >
                                {local.remove_all[DEFAULT_LANGUAGE]}
                            </Button.Action>
                        {:else}
                            <Button.Action
                                class="btn-inline invisible"
                                onclick={() => {}}
                            >
                                invisible
                            </Button.Action>
                        {/if}
                    </Table.Head>
                </Table.Row>
            </Table.Header>
            <Table.Body>
                {#each accounts as account, index}
                    <Table.Row
                        class={SharedStore.failedAccounts.includes(account)
                            ? "failed"
                            : ""}
                    >
                        <Table.Cell class="checkbox-cell">
                            <Input.Basic
                                type="checkbox"
                                bind:group={accountSelection}
                                value={account.email_address}
                            />
                        </Table.Cell>
                        <Table.Cell class="body-cell">
                            {index < failedAccountLength
                                ? local.warning[DEFAULT_LANGUAGE]
                                : ""}
                            {account.fullname} &lt;{account.email_address}&gt;
                        </Table.Cell>
                        <Table.Cell class="action-cell">
                            <Button.Basic
                                type="button"
                                class="btn-inline"
                                style="margin-right: 5px;"
                                onclick={() => {
                                    editAccount(account);
                                }}
                            >
                                {local.edit[DEFAULT_LANGUAGE]}
                            </Button.Basic>
                            <Button.Action
                                class="btn-inline"
                                onclick={removeAccount}
                                data-email-address={account.email_address}
                            >
                                {local.remove[DEFAULT_LANGUAGE]}
                            </Button.Action>
                        </Table.Cell>
                    </Table.Row>
                {/each}
            </Table.Body>
        </Table.Root>

        <!-- TODO: Add pagination. -->

        <div class="landing-body-footer">
            <Button.Action
                onclick={initMailboxes}
                disabled={!SharedStore.accounts ||
                    SharedStore.accounts.length == 0}
            >
                {local.continue_to_mailbox[DEFAULT_LANGUAGE]}
            </Button.Action>
        </div>
    {/if}
</div>

<style>
    :global {
        .accounts-info {
            display: flex;
            justify-content: space-between;
            flex-direction: row;

            & .account-list-operations {
                display: flex;
                flex-direction: row;
                align-items: center;
                gap: var(--spacing-2xs);
            }

            & .account-count span {
                color: var(--color-text-secondary);
            }
        }

        .checkbox-cell {
            width: var(--font-size-2xl);
            padding-left: var(--spacing-xs) !important;
            padding-bottom: 0 !important;
        }

        .body-cell {
            padding-left: var(--spacing-xs);
            padding-top: var(--spacing-md);
            text-align: left;
        }

        .action-cell {
            padding-right: var(--spacing-2xs);
            white-space: nowrap;
            width: calc(2 * var(--font-size-2xl));
            text-align: right;
        }
    }
</style>
