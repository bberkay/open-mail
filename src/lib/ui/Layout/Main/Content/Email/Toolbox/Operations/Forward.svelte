<script lang="ts" module>
    import { SharedStore } from "$lib/stores/shared.svelte";
    import { type Email } from "$lib/types";
    import Compose from "$lib/ui/Layout/Main/Content/Compose.svelte";
    import { showThis as showContent } from "$lib/ui/Layout/Main/Content.svelte";

    export function forward(email: Email) {
        showContent(Compose, {
            originalMessageContext: {
                composeType: "forward",
                originalMessageId: email.message_id,
                originalSender: email.sender,
                originalReceiver: email.receivers,
                originalSubject: email.subject,
                originalBody: email.body,
                originalDate: email.date,
            },
        });
    }
</script>

<script lang="ts">
    import * as Button from "$lib/ui/Components/Button";
    import Icon from "$lib/ui/Components/Icon";
    import type { Snippet } from "svelte";

    interface Props {
        children: Snippet,
        email: Email
    }

    let {
        children,
        email
    } = $props();

    const forwardOnClick = () => {
        forward(email);
    }
</script>

<div class="tool">
    <Button.Basic
        type="button"
        class="btn-inline"
        onclick={forwardOnClick}
    >
        {@render children()}
    </Button.Basic>
</div>
