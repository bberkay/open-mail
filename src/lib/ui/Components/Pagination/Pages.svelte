<script lang="ts">
    import { range, combine } from "$lib/utils";
    import * as Button from "$lib/ui/Components/Button";
    import Icon from "$lib/ui/Components/Icon";

    const DEFAULT_PAGINATION_PAGE_LENGTH = 5;

    interface Props {
        total: number;
        onChange: (((newOffset: number) => void) | ((newOffset: number) => Promise<void>));
        offsetStep: number;
        showMax?: number;
        startAt?: number;
        [attribute: string]: unknown;
    }

    let {
        total,
        onChange,
        offsetStep,
        showMax = DEFAULT_PAGINATION_PAGE_LENGTH,
        startAt = 1,
        ...attributes
    }: Props = $props();

    let {
	    class: additionalClass,
		...restAttributes
	} = $derived(attributes);

    total = Math.ceil(total / offsetStep);
    let current = $state(Math.max(1, startAt));
    let pages = $derived.by(() => {
        if (total < showMax)
            return range(1, total + 1, 1);

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
        await onChange(value * offsetStep);
        current = value;
    };

    const prev = async () => {
        await onChange((current - 1) * offsetStep);
        current -= 1;
    };

    const next = async () => {
        await onChange((current + 1) * offsetStep);
        current += 1;
    };

    const prevAll = async () => {
        await onChange(1 * offsetStep);
        current = 1;
    };

    const nextAll = async () => {
        await onChange(total * offsetStep);
        current = total;
    };
</script>

<div
    class={combine("pagination", additionalClass)}
    {...restAttributes}
>
    <Button.Action
        class="btn-outline btn-sm arrow-button"
        onclick={prev}
        disabled={current <= 1}
    >
        <Icon name="prev" />
    </Button.Action>
    {#if pages[0] > 1}
        <Button.Action
            class="btn-outline btn-sm"
            onclick={prevAll}
        >
            {1}
        </Button.Action>
        {#if pages[0] > 2}
            <span>...</span>
        {/if}
    {/if}
    {#each pages as value}
        <Button.Action
            class="btn-outline btn-sm {value === current ? "active" : ""}"
            onclick={onChangeWrapper}
            data-value={value}
        >
            {value}
        </Button.Action>
    {/each}
    {#if pages[pages.length - 1] < total}
        {#if pages[pages.length - 1] < total - 1}
            <span>...</span>
        {/if}
        <Button.Action
            class="btn-outline btn-sm"
            onclick={nextAll}
        >
            {total}
        </Button.Action>
    {/if}
    <Button.Action
        class="btn-outline btn-sm arrow-button"
        onclick={next}
        disabled={current >= total}
    >
        <Icon name="next" />
    </Button.Action>
</div>

<style>
    :global {
        .pagination {
            display: flex;
            flex-direction: row;
            gap: var(--spacing-2xs);
            justify-content: center;

            & .arrow-button {
                padding: var(--spacing-xs);

                & svg {
                    width: var(--font-size-md);
                    height: var(--font-size-md);
                }
            }
        }
    }
</style>
