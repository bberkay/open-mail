<script lang="ts">
    import { range } from "$lib/utils";
    import * as Button from "$lib/ui/Components/Button";
    import Icon from "$lib/ui/Components/Icon";

    interface Props {
        total: number;
        onChange: (((selectedPage: number) => void) | ((selectedPage: number) => Promise<void>));
        startAt?: number;
        showMax?: number;
    }

    let { total, onChange, startAt = 1, showMax = 5 }: Props = $props();

    let current = $state(Math.max(1, startAt));
    let pages = $derived.by(() => {
        const middle = Math.floor(showMax / 2)
        const rangeStart = Math.max(
            1,
            Math.min(total - showMax + 1, current - middle),
        );
        const rangeEnd = Math.min(total, current + middle + 1);
        if (rangeEnd - rangeStart < showMax) {
            return range(
                  rangeStart,
                  rangeEnd + showMax - (rangeEnd - rangeStart),
                  1,
              )
        } else {
            return range(rangeStart, rangeEnd, 1)
        }
    });

    const onChangeWrapper = async (e: Event) => {
        const target = e.target as HTMLElement;
        const value = Number(target.getAttribute("data-value"));
        await onChange(value);
        current = value;
    };

    const prev = async () => {
        await onChange(current - 1);
        current -= 1;
    };

    const next = async () => {
        await onChange(current + 1);
        current += 1;
    };

    const prevAll = async () => {
        await onChange(1);
        current = 1;
    };

    const nextAll = async () => {
        await onChange(total);
        current = total;
    };
</script>

<div class="pagination">
    <Button.Basic onclick={prev} disabled={current <= 1}>
        <Icon name="prev" />
    </Button.Basic>
    {#if pages[0] > 1}
        <button onclick={prevAll}>{1}</button>
        {#if pages[0] > 2}
            <span>...</span>
        {/if}
    {/if}
    {#each pages as value, index}
        <Button.Basic onclick={onChangeWrapper} data-value={value}>
            {value}
        </Button.Basic>
    {/each}
    {#if pages[pages.length - 1] < total}
        {#if pages[pages.length - 1] < total - 1}
            <span>...</span>
        {/if}
        <Button.Basic onclick={nextAll}>{total}</Button.Basic>
    {/if}
    <Button.Basic onclick={next} disabled={current >= total}>
        <Icon name="next" />
    </Button.Basic>
</div>

<style>
    :global {
        .pagination {
            display: flex;
            flex-direction: row;
            gap: var(--spacing-2xs);
            align-items: end;
        }
    }
</style>
