# Dashboard Runtime Assets

Files in this folder are embedded into `dashboard.html` by `scripts/generate_dashboard.py`.

Order matters:

- `10-graph-runtime.js` renders the D3 traceability graph, JSP/process flow graph, and shared assurance-context selectors.
- `20-dashboard-interactions.js` handles static dashboard interactions such as tabs, filters, manual checklist state, row expansion, tooltips, and prompt copying.

Keep renderer data preparation in Python and browser interaction code here. This keeps the dashboard generator readable without requiring a separate web build step.
