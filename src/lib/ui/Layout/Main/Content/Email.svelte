<script lang="ts">
    import { SharedStore } from "$lib/stores/shared.svelte";
    import { MailboxController } from "$lib/controllers/MailboxController";
    import { create, BaseDirectory } from '@tauri-apps/plugin-fs';
    import { onMount } from "svelte";
    import type { Account, Attachment, Email } from "$lib/types";
    import { makeSizeHumanReadable } from "$lib/utils";
    import Compose from "$lib/ui/Layout/Main/Content/Compose.svelte";
    import * as Button from "$lib/ui/Elements/Button";
    import { backToDefault } from "$lib/ui/Layout/Main/Content.svelte";
    import { showThis as showContent } from "$lib/ui/Layout/Main/Content.svelte";

    const mailboxController = new MailboxController();

    interface Props {
        account: Account;
        email: Email;
    }

    let {
        account,
        email
    }: Props = $props();

    let contentBody: HTMLElement;

    onMount(() => {
        contentBody.innerHTML = "";

        printBody(email.body);
    });

    function printBody(body: string): void {
        // Body
        let iframe = document.createElement("iframe");
        iframe.classList.add("email-body")
        contentBody.appendChild(iframe);

        let iframeDoc: Document | null;
        iframeDoc = iframe.contentWindow
            ? iframe.contentWindow.document
            : iframe.contentDocument;
        if (iframeDoc) {
            iframeDoc.open();
            iframeDoc.writeln(body);
            iframeDoc.close();

            contentBody.style.height = iframeDoc.body.scrollHeight + "px";
        }
    }

    async function downloadAttachment(e: Event): Promise<void> {
        const target = e.target as HTMLButtonElement;
        const name = target.getAttribute("data-name")!;
        const cid = target.getAttribute("data-cid");

        const response = await mailboxController.downloadAttachment(
            account,
            SharedStore.currentFolder!,
            email.uid,
            name,
            cid || undefined
        );

        if (!response.success) {
            alert(response.message);
        } else if (!response.data) {
            alert("Error, attachment could not be downloaded.");
        } else {
            const file = await create(response.data.name, { baseDir: BaseDirectory.Download });
            await file.write(Uint8Array.from(atob(response.data.data), (char) => char.charCodeAt(0)));
            await file.close();
        }
    }

    const reply = () => {
        showContent(Compose, {
            compose_type: "reply",
            original_message_id: email.message_id,
            original_sender: email.sender,
            original_receiver: email.receiver,
            original_subject: email.subject,
            original_body: email.body,
            original_date: email.date
        });
    }

    const forward = () => {
        showContent(Compose, {
            compose_type: "forward",
            original_message_id: email.message_id,
            original_sender: email.sender,
            original_receiver: email.receiver,
            original_subject: email.subject,
            original_body: email.body,
            original_date: email.date
        })
    }
</script>

<div class="send-operations">
    <div>
        <button onclick={backToDefault}>Back</button>
    </div>
    <div>
        <button onclick={reply}>Reply ↩</button>
        <button onclick={forward}>Forward ↪</button>
    </div>
</div>
<div id="subject" style="margin-bottom: 5px;">
    <h3>{email.subject || ""}</h3>
    <p>From: {email.receiver || ""}</p>
    <p>To: {email.sender || ""}</p>
    <p>Date: {email.date || ""}</p>
    {#if Object.hasOwn(email, "flags") && email.flags}
        {#each email.flags as flag}
            <span class = "tag">{flag}</span>
        {/each}
    {/if}
</div>
<div id="body" bind:this={contentBody}></div>
{#if Object.hasOwn(email, "attachments") && email.attachments}
<div id="attachments">
    {#each email.attachments as attachment}
        <Button.Action
            class="attachment"
            download={attachment.name}
            onclick={downloadAttachment}
            data-name={attachment.name}
            data-cid={attachment.cid}
        >
            {attachment.name + " (" + makeSizeHumanReadable(parseInt(attachment.size)) + ")"} ⇓
        </Button.Action>
    {/each}
</div>
{/if}

<style>
    :global {
        iframe.email-body{
            width: 100%;
            height: 100%;
            border: none;
            background-color: var(--color-bg-primary);
        }
    }

    #body:not(:has(iframe)) {
        background-color: #f5f5f5;
        color: #333;
        padding: 10px;
        overflow-y: scroll;
        overflow-x: hidden;
        margin-top: 1rem;
        margin-bottom: 1rem;
        border: 1px solid #ccc;
        border-radius: 5px;
    }

    #attachments {
        margin-top: 1.5rem;
    }

    .send-operations{
        width: 100%;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
</style>
