<script lang="ts">
    import { onMount } from 'svelte';
    import { get, writable } from 'svelte/store';
    import GetEmails from './Operations/GetEmails.svelte';
    import SendEmail from './Operations/SendEmail.svelte';
    import AddEmail from './Operations/AddEmail.svelte';
    import FolderManagement from './Operations/FolderManagement.svelte';

    let prevOperationButton: HTMLButtonElement, nextOperationButton: HTMLButtonElement;
    let operations: string[] = ["Get Emails", "Send Email", "Folder Management", "Add Email"];
    let currentOperationIndex = writable(0);

    onMount(() => {
        prevOperationButton = document.querySelector('.previous button')!;
        nextOperationButton = document.querySelector('.next button')!;
        checkPrevNextButtonAvailability();
    });

    function checkPrevNextButtonAvailability(){
        prevOperationButton.disabled = get(currentOperationIndex) === 0;
        nextOperationButton.disabled = get(currentOperationIndex) === operations.length - 1;
    }

    function previousOperation() {
        currentOperationIndex.update((index) => {
            if (index > 0)
                return index - 1;
            return index;
        });

        checkPrevNextButtonAvailability();    
    }
    
    function nextOperation() {
        currentOperationIndex.update((index) => {
            if (index < operations.length - 1)
                return index + 1;
            return index;
        });

        checkPrevNextButtonAvailability();
    }

    function getOperationComponent(operation: string) {
        switch (operation) {
            case "Get Emails":
                return GetEmails;
            case "Send Email":
                return SendEmail;
            case "Folder Management":
                return FolderManagement;
            case "Add Email":
                return AddEmail;
            default:
                return GetEmails;
        }
    }
</script>

<section class="operation-navigator">
    <div class="navigator">
        <div class="card">
            <div class="previous">
                <button on:click={previousOperation} disabled>&lt;</button>
            </div>
            <div class="operations">
                {#each operations as operation, index}
                    <div class="operation-item {index === $currentOperationIndex ? 'active' : ''}">
                        {operation}
                    </div>
                {/each}
            </div>
            <div class="next">
                <button on:click={nextOperation}>&gt;</button>
            </div>
        </div>
    </div>

    <div class="operation">
        {#if $currentOperationIndex !== undefined}
            <svelte:component this={getOperationComponent(operations[$currentOperationIndex])} />
        {/if}
    </div>
</section>

<style>
    .operation-navigator{
        position: relative;
    }

    .navigator{
        & .card{
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
        }

        & .operations{
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            margin: 0 1rem;

            & .operation-item{
                margin-top:5px;
                display: none;
            }

            & .operation-item.active{
                display: block;
            }
        }

        & .next, & .previous{
            display: flex;
            align-items: center;
        }
    }

    .operation{
        width: 100%;
    }
</style>