<script lang="ts">
    import { SharedStore } from "$lib/stores/shared.svelte";
    import { Folder } from "$lib/types";
    import * as Dropdown from "$lib/ui/Components/Dropdown";
    import { getMailboxContext } from "$lib/ui/Layout/Main/Content/Mailbox";
    import { local } from "$lib/locales";
    import { DEFAULT_LANGUAGE } from "$lib/constants";
    import { copyTo } from "./CopyTo.svelte";

    interface Props {
        sourceFolder: string | Folder;
    }

    let {
        sourceFolder,
    }: Props = $props();

    const mailboxContext = getMailboxContext();

    let email_address = $derived(mailboxContext.getGroupedUidSelection()[0][0]);
    let isCurrentFolderCustom = $derived.by(() => {
        if (SharedStore.currentAccount == "home") return false;

        return SharedStore.folders[
            SharedStore.currentAccount.email_address
        ].custom.includes(sourceFolder);
    });

    const copyEmailsOnClick = async (destinationFolder: string | Folder) => {
        await copyTo(
            sourceFolder,
            destinationFolder,
            mailboxContext.getGroupedUidSelection()
        );
        mailboxContext.emailSelection.value = [];
    }
</script>

<div class="tool">
    <Dropdown.Root class="dropdown-sm">
        <Dropdown.Toggle>
            {local.copy_to[DEFAULT_LANGUAGE]}
        </Dropdown.Toggle>
        <Dropdown.Content>
            {#if isCurrentFolderCustom}
                <!-- Add inbox option if email is in custom folder -->
                <Dropdown.Item onclick={async () => await copyEmailsOnClick(Folder.Inbox)}>
                    {Folder.Inbox}
                </Dropdown.Item>
            {/if}
            {#each SharedStore.folders[email_address].custom as customFolder}
                {#if SharedStore.currentAccount === "home" || customFolder !== sourceFolder}
                    <Dropdown.Item onclick={async () => await copyEmailsOnClick(customFolder)}>
                        {customFolder}
                    </Dropdown.Item>
                {/if}
            {/each}
        </Dropdown.Content>
    </Dropdown.Root>
</div>
