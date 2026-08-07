<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';

  const navItems = [
    { href: '/', label: 'Scans' },
    { href: '/trends', label: 'Trends' },
    { href: '/compliance', label: 'Compliance' }
  ];

  function isActive(href: string, current: string): boolean {
    if (href === '/') return current === '/';
    return current.startsWith(href);
  }
</script>

<nav class="bg-gray-900 text-white px-6 py-3 flex items-center justify-between">
  <a href="/" class="font-semibold tracking-tight">Assurance Scan</a>
  <div class="flex gap-1 text-sm">
    {#each navItems as item}
      <a
        href={item.href}
        class="px-3 py-1 rounded {isActive(item.href, $page.url.pathname)
          ? 'bg-gray-700 text-white'
          : 'text-gray-300 hover:bg-gray-800'}"
      >
        {item.label}
      </a>
    {/each}
  </div>
</nav>

<main class="max-w-6xl mx-auto px-6 py-8">
  <slot />
</main>
