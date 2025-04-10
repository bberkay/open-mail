<script lang="ts">
    import { onMount } from "svelte";
    import type { Snippet } from "svelte";
    import { close } from "./index";
    import { combine, createDomElement } from "$lib/utils";
    import { local } from "$lib/locales";
    import { DEFAULT_LANGUAGE } from "$lib/constants";

    interface Props {
        children: Snippet;
        [attribute: string]: unknown;
    }

    let { children, ...attributes }: Props = $props();

    const {
        class: additionalClass,
        ...restAttributes
    } = attributes;

    let modal: HTMLElement;
    onMount(() => {
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;

        let closeButton = modal.querySelector("button[data-modal-close]");
        if (!closeButton) {
            closeButton = createDomElement(
                `<button type="button" data-modal-close>${local.close[DEFAULT_LANGUAGE]}</button>`,
            );
            modal.appendChild(closeButton);
        }
        closeButton.addEventListener("click", close);
    });
</script>

<div
    bind:this={modal}
    class={combine("modal", additionalClass)}
    {...restAttributes}
>
    {@render children()}
</div>

<style>
    .modal{
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: var(--container-md);
        background-color: var(--color-bg-primary);
        padding: var(--spacing-lg) var(--spacing-xl);
        border: 1px solid var(--color-border);
        border-radius: var(--radius-md);
        box-shadow: var(--shadow-md);
        z-index: var(--z-index-modal);

        & .modal-header {
            color: var(--color-text-primary);
            margin-bottom: var(--spacing-2xs);
            font-weight: var(--font-weight-bold);
            font-size: var(--font-size-xl);
        }

        & .modal-body {
            color: var(--color-text-secondary);
            margin-bottom: var(--spacing-md);
            font-size: var(--font-size-sm);
        }

        & .modal-footer {
            display: flex;
            flex-direction: row;
            justify-content: flex-end;
            gap: var(--spacing-xs);
            color: var(--color-text-primary);
        }
    }
</style>
