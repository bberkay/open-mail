<script lang="ts">
    import { combine } from "$lib/utils";

    interface Props {
        [attribute: string]: unknown;
    }

    let {
        ...attributes
    }: Props = $props();

    const {
        class: additionalClass,
        ...restAttributes
    } = attributes;
</script>

<div
    role="separator"
    class={combine("select-separator", additionalClass)}
    {...restAttributes}
></div>

<style>
    :global {
        .select-separator {
            width: 100%;
            margin-bottom: var(--spacing-2xs);
            background-color: var(--color-border);
            height: 1px;
        }
    }
</style>
