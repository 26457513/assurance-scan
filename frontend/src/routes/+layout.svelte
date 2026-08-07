<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';

  const navItems = [
    { href: '/', label: 'Scans', icon: '⟳' },
    { href: '/frs', label: 'FRs', icon: '✓' },
    { href: '/compliance', label: 'Compliance', icon: '§' },
    { href: '/trends', label: 'Trends', icon: '↗' }
  ];

  function isActive(href: string, current: string): boolean {
    if (href === '/') return current === '/';
    return current.startsWith(href);
  }
</script>

<nav class="bg-gray-900 text-white px-6 py-0 flex items-center justify-between sticky top-0 z-50 shadow-md">
  <a href="/" class="flex items-center gap-2 py-3 font-semibold tracking-tight text-lg">
    <span class="text-blue-400">⬡</span>
    Assurance Scan
  </a>
  <div class="flex gap-0 text-sm h-full">
    {#each navItems as item}
      <a
        href={item.href}
        class="flex items-center gap-1.5 px-4 py-3 border-b-2 transition-colors {isActive(item.href, $page.url.pathname)
          ? 'border-blue-400 text-white bg-gray-800'
          : 'border-transparent text-gray-400 hover:text-white hover:bg-gray-800'}"
      >
        <span class="text-base opacity-60">{item.icon}</span>
        {item.label}
      </a>
    {/each}
  </div>
</nav>

<main class="max-w-7xl mx-auto px-6 py-8">
  <slot />
</main>
