<script lang="ts">
    import { DEFAULT_LANGUAGE } from "$lib/constants";
    import { local } from "$lib/locales";

    interface Props {
        text?: string;
        [attribute: string]: unknown;
    }

    let {
        text = local.loading[DEFAULT_LANGUAGE],
        ...attributes
    }: Props = $props();
</script>

<span {...attributes}>
    <small class="loader"></small> {text}
</span>

<style>
    .loader {
        border: 2px solid var(--color-border);
        border-radius: 50%;
        border-top: 2px solid var(--color-text-primary);
        width: 10px;
        height: 10px;
        -webkit-animation: spin 2s linear infinite;
        animation: spin 2s linear infinite;
        display: inline-block;
        margin-right: var(--spacing-2xs);
    }

    @-webkit-keyframes spin {
        0% { -webkit-transform: rotate(0deg); }
        100% { -webkit-transform: rotate(360deg); }
    }

    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
</style>
