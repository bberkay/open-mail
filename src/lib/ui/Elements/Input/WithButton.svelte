<script lang="ts">
    import { type Snippet } from "svelte";
    import * as Button from "$lib/ui/Elements/Button";

    interface Props {
        type: string;
        onclick?: (e: Event) => void;
        children: Snippet;
        [attribute: string]: unknown;
    }

    let {
        type,
        onclick,
        children,
        ...attributes
    }: Props  = $props();
</script>

<div class="input-with-button">
    <input {...attributes} {type}>
    <div>
        <Button.Basic
            type="button"
            class="inline"
            {onclick}
            {...attributes}
        >
            {@render children()}
        </Button.Basic>
    </div>
</div>

<style>
    :global {
        .input-with-button{
            position: relative;
            transition: all var(--transition-fast) var(--ease-default);
            border-bottom: 1px solid var(--color-border);

            & input {
                border: none !important;
            }

            & .input-icon + input {
                margin-left: 40px;
            }

            &:has(input:focus) {
                border-color: var(--color-text-primary);
            }

            & input:focus + .input-icon svg,
            & input:focus + .input-toggle svg,
            &:has(input:focus) svg {
                fill: var(--color-text-primary) !important;
            }

            & input:focus + .input-toggle {
                color: var(--color-text-primary) !important;
            }

            & .input-icon,
            & .input-toggle {
                position: absolute;
                transform: translateY(-50%);
                cursor: pointer;
                color: var(--color-text-secondary);
                background: transparent;
                border: none;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all var(--transition-fast) var(--ease-default);

                & svg {
                    width: var(--font-size-lg);
                    height: var(--font-size-lg);
                }
            }

            & .input-icon {
                top: 50%;
                left: var(--spacing-xs);
            }

            & .input-toggle {
                right: var(--spacing-xs);
                top: 50%;
            }
        }
    }
</style>
