<script lang="ts">
    import InboxItem from "./Inbox/InboxItem.svelte";
    import { SharedStore } from "$lib/stores/shared.svelte";
    import { onMount } from "svelte";
    import { ApiService, GetRoutes } from "$lib/services/ApiService";

    let totalEmailCount = $state(0);
    let currentOffset = $state(0);

    let prevButton: HTMLButtonElement;
    let nextButton: HTMLButtonElement;
    onMount(() => {
        prevButton = document.getElementById(
            "prev-button",
        ) as HTMLButtonElement;
        nextButton = document.getElementById(
            "next-button",
        ) as HTMLButtonElement;

        /*$effect(() => {
            if (currentOffset >= 10) {
                completeToTen();
            }
        })*/
    });

    async function completeToTen(): Promise<void> {
        const missing = currentOffset - (currentOffset % 10);
        if (missing != currentOffset) {
            const response = await ApiService.get(
                SharedStore.server,
                GetRoutes.GET_MAILBOXES,
                {
                    pathParams: {
                        accounts: getCurrentAccountsAsString()

                    },
                    queryParams: {
                        folder: encodeURIComponent(SharedStore.selectedFolder),
                        offset_start: missing,
                        offset_end: missing + 10,
                        search: getSearchMenuValue()
                    }
                }
            );

            if (response.success && response.data) {
                currentOffset = 10 + missing;
                SharedStore.mailboxes = response.data;
            }
        }
    }

    function getSearchMenuValue() {
        return "ALL";
    }

    function getCurrentAccountsAsString() {
        return SharedStore.selectedAccounts.map((account) => account.email_address).join(", ");
    }

    async function getPreviousEmails() {
        if (currentOffset <= 10)
            return;

        prevButton.disabled = true;
        const response = await ApiService.get(
            SharedStore.server,
            GetRoutes.GET_MAILBOXES,
            {
                pathParams: {
                    accounts: getCurrentAccountsAsString(),
                },
                queryParams: {
                    folder: encodeURIComponent(SharedStore.selectedFolder),
                    offset_start: (Math.max(0, currentOffset - 20)),
                    offset_end: (currentOffset - 10),
                    search: getSearchMenuValue()
                }
            }
        );

        if (response.success && response.data) {
            currentOffset = currentOffset - 10;
            SharedStore.mailboxes = response.data;
        }

        prevButton.disabled = false;
    }

    async function getNextEmails() {
        if (currentOffset >= totalEmailCount)
            return;

        nextButton.disabled = true;
        const response = await ApiService.get(
            SharedStore.server,
            GetRoutes.GET_MAILBOXES,
            {
                pathParams: {
                    accounts: getCurrentAccountsAsString(),
                },
                queryParams: {
                    folder: encodeURIComponent(SharedStore.selectedFolder),
                    offset_start: (currentOffset + 10),
                    offset_end: (currentOffset + 20),
                    search: getSearchMenuValue()
                }
            }
        );

        if (response.success && response.data) {
            currentOffset = currentOffset + 10;
            SharedStore.mailboxes = response.data;
        }

        nextButton.disabled = false;
    }
</script>

<section>
    <div>
        <h2>{SharedStore.selectedFolder}</h2>
        <hr />
        <div>
            <button id="prev-button" onclick={getPreviousEmails} disabled={currentOffset <= 10}>
                Previous
            </button>
            <small>
                {Math.max(1, currentOffset - 9)} - {currentOffset} of {totalEmailCount}
            </small>
            <button id="next-button" onclick={getNextEmails} disabled={currentOffset >= totalEmailCount}>
                Next
            </button>
        </div>
        <hr />
    </div>
    <div>
        {#each SharedStore.mailboxes as account}
            {#each account.result.emails as email}
              <InboxItem owner={account.email_address} email={email} />
            {/each}
        {/each}
    </div>
</section>
