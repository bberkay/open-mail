<script lang="ts">
    import "$lib/assets/css/style.css";
    import * as Modal from "$lib/ui/Components/Modal";
    import Layout from "$lib/ui/Layout/Layout.svelte";
    import Variables from "$lib/ui/Layout/Developer/Variables.svelte";

	let { children } = $props();

	const handleShortcuts = (e: KeyboardEvent) => {
        if (e.ctrlKey && e.code === 'Space') {
            e.preventDefault();
            Modal.show(Variables);
        }
	}
</script>

<svelte:window onkeydown={handleShortcuts} />

<Layout>
    {@render children()}
</Layout>

<div class="modal-container"></div>
<div class="toast-container"></div>

<style>
    .modal-container {
        position: fixed;
        display: none;
        align-items: center;
        justify-content: center;
        width: 100%;
        height: 100%;
        overflow: hidden;
        top: 0;
        left: 0;
        background-color: #00000099;
        z-index: var(--z-index-overlay);
    }

    .toast-container{
        position: fixed;
        bottom: var(--spacing-lg);
        left: var(--spacing-lg);
        display: flex;
        flex-direction: column-reverse;
        gap: var(--spacing-xs);
    }
</style>
