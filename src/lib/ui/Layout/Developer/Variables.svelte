<script lang="ts">
    import { SharedStore } from "$lib/stores/shared.svelte";
    import Modal from "$lib/ui/Components/Modal";
</script>

<Modal>
    <pre>{JSON.stringify(SharedStore, null, 4)}</pre>
</Modal>
