/**
 * Read-only menu view — Sprint 2.4 (Phase 2 MVP).
 *
 * Visual language: editorial menu, not data table. The owner is checking
 * "is this what my AI is reading on the phone?" — a printed-menu metaphor
 * (typeset items, leader-dot price runs, category nav rail) reads more
 * naturally than a CRUD admin grid. CRUD lands in a follow-up PR; this
 * view is intentionally still and quiet.
 *
 * All Server Components — no interactivity in this PR. The category nav
 * uses plain anchor links so it works without JS.
 */
import { Fragment } from 'react';

import { formatCAD } from '@/lib/formatters/money';
import {
  type Category,
  type MenuItem,
  humanizeCategoryKey,
  isSizedItem,
} from '@/lib/schemas/menu';

type Props = {
  categories: Category[];
  itemCount: number;
  restaurantName: string;
};

export function MenuView({ categories, itemCount, restaurantName }: Props) {
  return (
    <section className="flex flex-1 flex-col gap-10 p-6 lg:p-10">
      <MenuHeader
        categoryCount={categories.length}
        itemCount={itemCount}
        restaurantName={restaurantName}
      />

      <div className="grid gap-10 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-16">
        <CategoryNav categories={categories} />
        <div className="flex flex-col gap-14">
          {categories.map((c) => (
            <CategorySection key={c.key} category={c} />
          ))}
        </div>
      </div>
    </section>
  );
}

function MenuHeader({
  categoryCount,
  itemCount,
  restaurantName,
}: {
  categoryCount: number;
  itemCount: number;
  restaurantName: string;
}) {
  return (
    <header className="flex max-w-3xl flex-col gap-3">
      <div className="flex items-baseline gap-3">
        <h2 className="text-3xl font-medium tracking-tight">Menu</h2>
        <span
          aria-hidden
          className="h-px flex-1 translate-y-[-0.5rem] bg-border"
        />
      </div>
      <p className="text-sm text-muted-foreground">
        {restaurantName}
        <span className="mx-2 text-muted-foreground/40">·</span>
        <span className="tabular-nums">{categoryCount}</span>{' '}
        {categoryCount === 1 ? 'category' : 'categories'}
        <span className="mx-2 text-muted-foreground/40">·</span>
        <span className="tabular-nums">{itemCount}</span>{' '}
        {itemCount === 1 ? 'item' : 'items'}
      </p>
      <p className="text-xs text-muted-foreground">
        This is what the agent reads to callers. Editing arrives in a
        follow-up release.
      </p>
    </header>
  );
}

function CategoryNav({ categories }: { categories: Category[] }) {
  return (
    <nav
      aria-label="Menu sections"
      className="hidden lg:sticky lg:top-6 lg:block lg:self-start"
    >
      <p className="mb-3 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
        Sections
      </p>
      <ul className="flex flex-col gap-px border-l border-border">
        {categories.map((c) => (
          <li key={c.key}>
            <a
              href={`#category-${c.key}`}
              className="group -ml-px flex items-baseline justify-between gap-3 border-l border-transparent py-1.5 pl-4 text-sm text-muted-foreground transition-colors hover:border-l-foreground hover:text-foreground"
            >
              <span className="truncate">{humanizeCategoryKey(c.key)}</span>
              <span className="text-xs tabular-nums opacity-60">
                {c.items.length}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function CategorySection({ category }: { category: Category }) {
  const label = humanizeCategoryKey(category.key);
  const headingId = `heading-${category.key}`;
  return (
    <section
      id={`category-${category.key}`}
      aria-labelledby={headingId}
      className="scroll-mt-8"
    >
      <header className="mb-6 flex items-baseline gap-4 border-b border-border pb-3">
        <h3 id={headingId} className="text-xl font-medium tracking-tight">
          {label}
        </h3>
        <span aria-hidden className="h-px flex-1 bg-border/60" />
        <span className="text-xs tabular-nums text-muted-foreground">
          {category.items.length}{' '}
          {category.items.length === 1 ? 'item' : 'items'}
        </span>
      </header>

      <ul className="grid gap-x-12 gap-y-6 sm:grid-cols-2">
        {category.items.map((item, idx) => (
          <li key={`${category.key}-${idx}-${item.name}`}>
            <ItemRow item={item} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ItemRow({ item }: { item: MenuItem }) {
  return (
    <article className="flex flex-col gap-1.5">
      <div className="flex items-baseline gap-3">
        <h4 className="font-medium leading-snug text-foreground">
          {item.name}
        </h4>
        <span
          aria-hidden
          className="min-w-4 flex-1 translate-y-[-0.25rem] border-b border-dotted border-border"
        />
        <PriceTag item={item} />
      </div>
      {item.description ? (
        <p className="text-xs leading-relaxed text-muted-foreground">
          {item.description}
        </p>
      ) : null}
    </article>
  );
}

function PriceTag({ item }: { item: MenuItem }) {
  if (isSizedItem(item)) {
    const sizes = Object.entries(item.sizes);
    return (
      <span className="flex items-baseline gap-2 font-mono text-sm tabular-nums text-foreground">
        {sizes.map(([size, price], i) => (
          <Fragment key={size}>
            {i > 0 ? (
              <span aria-hidden className="text-muted-foreground/50">
                ·
              </span>
            ) : null}
            <span className="flex items-baseline gap-1.5">
              <span className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                {size}
              </span>
              <span>{formatCAD(price)}</span>
            </span>
          </Fragment>
        ))}
      </span>
    );
  }
  return (
    <span className="font-mono text-sm tabular-nums text-foreground">
      {formatCAD(item.price)}
    </span>
  );
}
