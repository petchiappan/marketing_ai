/* ═══════════════════════════════════════════════════════════════════════
   Agent Control Center – Dashboard JavaScript
   ═══════════════════════════════════════════════════════════════════════ */

// ── State ──
let currentUser = null;
let statusChart = null;
let healthChart = null;
let tokenChart = null;
let refreshInterval = null;

// ── Init ──
document.addEventListener('DOMContentLoaded', async () => {
    await loadCurrentUser();
    setupNavigation();
    setupSidebar();
    setupLogout();
    setupModal();
    document.getElementById('add-tool-btn').addEventListener('click', addTool);
    await loadDashboard();
    startAutoRefresh();
});

// ════════════════════════════════════════════════════════════════════════
// AUTH & USER
// ════════════════════════════════════════════════════════════════════════

async function loadCurrentUser() {
    try {
        const resp = await fetch('/admin/auth/me');
        if (!resp.ok) {
            window.location.href = '/admin/login';
            return;
        }
        currentUser = await resp.json();
        document.getElementById('user-name').textContent = currentUser.display_name || currentUser.email;
    } catch {
        window.location.href = '/admin/login';
    }
}

function setupLogout() {
    document.getElementById('logout-btn').addEventListener('click', async () => {
        await fetch('/admin/auth/logout', { method: 'POST' });
        window.location.href = '/admin/login';
    });
}

// ════════════════════════════════════════════════════════════════════════
// NAVIGATION
// ════════════════════════════════════════════════════════════════════════

function setupNavigation() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.dataset.section;
            switchSection(section);
        });
    });
}

function switchSection(sectionName) {
    // Update nav active state
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelector(`[data-section="${sectionName}"]`).classList.add('active');

    // Show section
    document.querySelectorAll('.content-section').forEach(s => s.classList.remove('active'));
    document.getElementById(`section-${sectionName}`).classList.add('active');

    // Load data for section
    const loaders = {
        'dashboard': loadDashboard,
        'tools': loadTools,
        'rate-limits': loadRateLimits,
        'token-usage': loadTokenUsage,
        'agent-runs': loadAgentRuns,
        'job-queue': loadJobQueue,
    };
    if (loaders[sectionName]) loaders[sectionName]();
}

function setupSidebar() {
    const toggle = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    toggle.addEventListener('click', () => sidebar.classList.toggle('collapsed'));
}

// ════════════════════════════════════════════════════════════════════════
// DASHBOARD
// ════════════════════════════════════════════════════════════════════════

async function loadDashboard() {
    try {
        const resp = await fetch('/admin/api/dashboard-kpis');
        const data = await resp.json();

        // KPI values
        animateValue('kpi-total-requests', data.total_requests);
        animateValue('kpi-active-runs', data.active_agent_runs);
        animateValue('kpi-tokens-24h', formatNumber(data.tokens_last_24h));
        const healthy = data.tool_health?.healthy || 0;
        const total = Object.values(data.tool_health || {}).reduce((a, b) => a + b, 0);
        animateValue('kpi-tools-healthy', `${healthy}/${total}`);

        // Status chart
        renderStatusChart(data.status_counts || {});

        // Health chart
        renderHealthChart(data.tool_health || {});

        // LLM model info
        if (data.llm) {
            animateValue('kpi-llm-model', `${data.llm.identifier}`);
        }
    } catch (err) {
        console.error('Dashboard load error:', err);
    }
}

function renderStatusChart(counts) {
    const ctx = document.getElementById('chart-status');
    if (statusChart) statusChart.destroy();

    const labels = Object.keys(counts);
    const values = Object.values(counts);
    const colors = labels.map(l => ({
        pending: '#94a3b8', processing: '#3b82f6', completed: '#22c55e',
        failed: '#ef4444', partial: '#f59e0b'
    }[l] || '#64748b'));

    statusChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels.map(capitalize),
            datasets: [{ data: values, backgroundColor: colors, borderWidth: 0 }]
        },
        options: {
            responsive: true,
            cutout: '65%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#94a3b8', padding: 15, font: { family: "'Inter'" } }
                }
            }
        }
    });
}

function renderHealthChart(health) {
    const ctx = document.getElementById('chart-tool-health');
    if (healthChart) healthChart.destroy();

    healthChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['Healthy', 'Degraded', 'Down', 'Unknown'],
            datasets: [{
                data: [health.healthy || 0, health.degraded || 0, health.down || 0, health.unknown || 0],
                backgroundColor: ['#22c55e', '#f59e0b', '#ef4444', '#64748b'],
                borderRadius: 6,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
                x: {
                    ticks: { color: '#94a3b8', font: { family: "'Inter'" } },
                    grid: { display: false },
                    border: { display: false },
                },
                y: {
                    ticks: { color: '#64748b', stepSize: 1, font: { family: "'Inter'" } },
                    grid: { color: 'rgba(148,163,184,0.08)' },
                    border: { display: false },
                }
            }
        }
    });
}

// ════════════════════════════════════════════════════════════════════════
// TOOL CONFIG
// ════════════════════════════════════════════════════════════════════════

const AGENT_OPTIONS = [
    { value: '', label: '— None —' },
    { value: 'contact_agent', label: 'Contact Agent' },
    { value: 'news_agent', label: 'News Agent' },
    { value: 'financial_agent', label: 'Financial Agent' },
    { value: 'aggregation_agent', label: 'Aggregation Agent' },
];

function agentSelectHtml(selectedValue) {
    return AGENT_OPTIONS.map(o =>
        `<option value="${o.value}" ${o.value === (selectedValue || '') ? 'selected' : ''}>${o.label}</option>`
    ).join('');
}

async function loadTools() {
    try {
        const resp = await fetch('/admin/api/tools');
        const tools = await resp.json();
        const grid = document.getElementById('tool-grid');
        grid.innerHTML = tools.length ? tools.map(renderToolCard).join('') : '<p style="color:var(--text-muted)">No tools configured yet.</p>';
    } catch (err) {
        console.error('Tools load error:', err);
    }
}

function renderToolCard(tool) {
    const agentLabel = AGENT_OPTIONS.find(o => o.value === tool.agent_name)?.label || tool.agent_name || '— None —';
    return `
        <div class="tool-card glass">
            <div class="tool-card-header">
                <h3>${escapeHtml(tool.display_name)}</h3>
                <span class="badge badge-${tool.health_status}">${tool.health_status}</span>
            </div>
            <div class="tool-card-body">
                <div><span class="field-label">Name:</span> ${escapeHtml(tool.tool_name)}</div>
                <div><span class="field-label">Agent:</span> ${escapeHtml(agentLabel)}</div>
                <div><span class="field-label">Base URL:</span> ${tool.base_url ? escapeHtml(tool.base_url) : '—'}</div>
                <div><span class="field-label">Auth:</span> ${tool.auth_type}</div>
                <div><span class="field-label">API Key:</span> ${tool.has_api_key ? '✅ Configured' : '❌ Not set'}</div>
                <div>
                    <span class="field-label">Enabled:</span>
                    <label class="toggle">
                        <input type="checkbox" ${tool.is_enabled ? 'checked' : ''} onchange="toggleTool('${tool.tool_name}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>
            <div class="tool-card-actions">
                <button class="btn btn-sm btn-outline" onclick="editTool('${tool.tool_name}')">Edit</button>
                <button class="btn btn-sm btn-outline" onclick="healthCheck('${tool.tool_name}')">Health Check</button>
            </div>
        </div>
    `;
}

function addTool() {
    openModal('Add New Tool', `
        <div class="form-group">
            <label>Tool Name <span style="color:#ef4444">*</span></label>
            <input id="add-tool-name" placeholder="e.g. lusha, apollo">
        </div>
        <div class="form-group">
            <label>Display Name</label>
            <input id="add-display-name" placeholder="Tool display name">
        </div>
        <div class="form-group">
            <label>Agent</label>
            <select id="add-agent-name">${agentSelectHtml('')}</select>
        </div>
        <div class="form-group">
            <label>Base URL</label>
            <input id="add-base-url" placeholder="https://api.example.com">
        </div>
        <div class="form-group">
            <label>API Key</label>
            <input id="add-api-key" type="password" placeholder="Enter API key">
        </div>
        <div class="form-group">
            <label>Auth Type</label>
            <select id="add-auth-type">
                <option value="api_key">API Key</option>
                <option value="bearer">Bearer Token</option>
                <option value="oauth2">OAuth2</option>
                <option value="basic">Basic Auth</option>
            </select>
        </div>
    `, async () => {
        const toolName = document.getElementById('add-tool-name').value.trim();
        if (!toolName) {
            alert('Tool Name is required.');
            return;
        }

        const body = {};
        const displayName = document.getElementById('add-display-name').value.trim();
        body.display_name = displayName || toolName;
        const agentName = document.getElementById('add-agent-name').value;
        if (agentName) body.agent_name = agentName;
        const baseUrl = document.getElementById('add-base-url').value.trim();
        if (baseUrl) body.base_url = baseUrl;
        const apiKey = document.getElementById('add-api-key').value;
        if (apiKey) body.api_key = apiKey;
        body.auth_type = document.getElementById('add-auth-type').value;

        try {
            const resp = await fetch(`/admin/api/tools/${encodeURIComponent(toolName)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                alert(err.detail || 'Failed to add tool');
                return;
            }
            closeModal();
            loadTools();
        } catch (err) {
            console.error('Add tool error:', err);
            alert('Failed to add tool. Check console for details.');
        }
    });
}

async function toggleTool(toolName, enabled) {
    await fetch(`/admin/api/tools/${toolName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled: enabled }),
    });
}

async function editTool(toolName) {
    // Fetch current tool data to pre-fill form
    let currentTool = {};
    try {
        const resp = await fetch('/admin/api/tools');
        const tools = await resp.json();
        currentTool = tools.find(t => t.tool_name === toolName) || {};
    } catch (e) { /* ignore, fields will be blank */ }

    openModal('Edit Tool: ' + toolName, `
        <div class="form-group">
            <label>Display Name</label>
            <input id="edit-display-name" placeholder="Tool display name" value="${escapeHtml(currentTool.display_name || '')}">
        </div>
        <div class="form-group">
            <label>Agent</label>
            <select id="edit-agent-name">${agentSelectHtml(currentTool.agent_name)}</select>
        </div>
        <div class="form-group">
            <label>Base URL</label>
            <input id="edit-base-url" placeholder="https://api.example.com" value="${escapeHtml(currentTool.base_url || '')}">
        </div>
        <div class="form-group">
            <label>API Key</label>
            <input id="edit-api-key" type="password" placeholder="Enter new API key (leave blank to keep current)">
        </div>
        <div class="form-group">
            <label>Auth Type</label>
            <select id="edit-auth-type">
                <option value="api_key" ${currentTool.auth_type === 'api_key' ? 'selected' : ''}>API Key</option>
                <option value="bearer" ${currentTool.auth_type === 'bearer' ? 'selected' : ''}>Bearer Token</option>
                <option value="oauth2" ${currentTool.auth_type === 'oauth2' ? 'selected' : ''}>OAuth2</option>
                <option value="basic" ${currentTool.auth_type === 'basic' ? 'selected' : ''}>Basic Auth</option>
            </select>
        </div>
    `, async () => {
        const body = {};
        const name = document.getElementById('edit-display-name').value;
        const agentName = document.getElementById('edit-agent-name').value;
        const url = document.getElementById('edit-base-url').value;
        const key = document.getElementById('edit-api-key').value;
        const auth = document.getElementById('edit-auth-type').value;
        if (name) body.display_name = name;
        body.agent_name = agentName || null;
        if (url) body.base_url = url;
        if (key) body.api_key = key;
        if (auth) body.auth_type = auth;

        await fetch(`/admin/api/tools/${toolName}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        closeModal();
        loadTools();
    });
}

async function healthCheck(toolName) {
    const resp = await fetch(`/admin/api/tools/${toolName}/health`, { method: 'POST' });
    const data = await resp.json();
    alert(`Health check for ${toolName}: ${data.health_status}`);
    loadTools();
}

// ════════════════════════════════════════════════════════════════════════
// RATE LIMITS
// ════════════════════════════════════════════════════════════════════════

async function loadRateLimits() {
    try {
        const resp = await fetch('/admin/api/rate-limits');
        const limits = await resp.json();
        const tbody = document.getElementById('rate-limits-tbody');
        tbody.innerHTML = limits.map(rl => `
            <tr>
                <td><strong>${escapeHtml(rl.provider_name)}</strong></td>
                <td>${rl.requests_per_min}</td>
                <td>${rl.burst_limit}</td>
                <td>${rl.daily_quota || '∞'}</td>
                <td>
                    <label class="toggle">
                        <input type="checkbox" ${rl.is_enabled ? 'checked' : ''} onchange="toggleRateLimit('${rl.provider_name}', this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </td>
                <td><button class="btn btn-sm btn-outline" onclick="editRateLimit('${rl.provider_name}', ${rl.requests_per_min}, ${rl.burst_limit}, ${rl.daily_quota || 0})">Edit</button></td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Rate limits load error:', err);
    }
}

async function toggleRateLimit(provider, enabled) {
    await fetch(`/admin/api/rate-limits/${provider}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_enabled: enabled }),
    });
}

function editRateLimit(provider, rpm, burst, daily) {
    openModal('Edit Rate Limit: ' + provider, `
        <div class="form-group">
            <label>Requests per Minute</label>
            <input id="edit-rpm" type="number" value="${rpm}">
        </div>
        <div class="form-group">
            <label>Burst Limit</label>
            <input id="edit-burst" type="number" value="${burst}">
        </div>
        <div class="form-group">
            <label>Daily Quota (0 = unlimited)</label>
            <input id="edit-daily" type="number" value="${daily}">
        </div>
    `, async () => {
        await fetch(`/admin/api/rate-limits/${provider}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                requests_per_min: parseInt(document.getElementById('edit-rpm').value),
                burst_limit: parseInt(document.getElementById('edit-burst').value),
                daily_quota: parseInt(document.getElementById('edit-daily').value),
            }),
        });
        closeModal();
        loadRateLimits();
    });
}

// ════════════════════════════════════════════════════════════════════════
// TOKEN USAGE
// ════════════════════════════════════════════════════════════════════════

async function loadTokenUsage() {
    const days = document.getElementById('token-days').value;
    try {
        const resp = await fetch(`/admin/api/token-usage?days=${days}`);
        const data = await resp.json();

        // Table
        const tbody = document.getElementById('token-usage-tbody');
        tbody.innerHTML = data.map(row => `
            <tr>
                <td><strong>${escapeHtml(row.agent_name)}</strong></td>
                <td>${escapeHtml(row.model_name)}</td>
                <td>${formatNumber(row.total_prompt)}</td>
                <td>${formatNumber(row.total_completion)}</td>
                <td>${formatNumber(row.total_tokens)}</td>
                <td>$${(row.total_cost || 0).toFixed(4)}</td>
                <td>${row.call_count}</td>
            </tr>
        `).join('');

        // Chart
        renderTokenChart(data);
    } catch (err) {
        console.error('Token usage load error:', err);
    }
}

function renderTokenChart(data) {
    const ctx = document.getElementById('chart-tokens');
    if (tokenChart) tokenChart.destroy();

    const agents = data.map(d => d.agent_name);
    const promptTokens = data.map(d => d.total_prompt || 0);
    const completionTokens = data.map(d => d.total_completion || 0);

    tokenChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: agents,
            datasets: [
                {
                    label: 'Prompt Tokens',
                    data: promptTokens,
                    backgroundColor: 'rgba(99, 102, 241, 0.7)',
                    borderRadius: 4,
                },
                {
                    label: 'Completion Tokens',
                    data: completionTokens,
                    backgroundColor: 'rgba(139, 92, 246, 0.7)',
                    borderRadius: 4,
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { color: '#94a3b8', font: { family: "'Inter'" } } }
            },
            scales: {
                x: { ticks: { color: '#94a3b8' }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(148,163,184,0.08)' }, border: { display: false } }
            }
        }
    });
}

// Listen for days selector change
document.getElementById('token-days')?.addEventListener('change', loadTokenUsage);

// ════════════════════════════════════════════════════════════════════════
// AGENT RUNS
// ════════════════════════════════════════════════════════════════════════

async function loadAgentRuns() {
    const statusFilter = document.getElementById('filter-agent-status').value;
    const agentFilter = document.getElementById('filter-agent-name').value;

    let url = '/admin/api/agent-runs?limit=50';
    if (statusFilter) url += `&status_filter=${statusFilter}`;
    if (agentFilter) url += `&agent_name=${agentFilter}`;

    // Support filtering by request_id (from Job Queue → View Runs)
    if (window._filterByRequestId) {
        url += `&request_id=${window._filterByRequestId}`;
        window._filterByRequestId = null;  // Clear after use
    }

    try {
        const resp = await fetch(url);
        const runs = await resp.json();
        const tbody = document.getElementById('agent-runs-tbody');
        tbody.innerHTML = runs.map(r => `
            <tr>
                <td><strong>${escapeHtml(r.agent_name)}</strong></td>
                <td><span class="badge badge-${r.status}">${r.status}</span></td>
                <td>${r.started_at ? new Date(r.started_at).toLocaleString() : '—'}</td>
                <td>${r.duration_ms ? (r.duration_ms / 1000).toFixed(1) + 's' : '—'}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis">${r.error_message ? escapeHtml(r.error_message) : '—'}</td>
                <td>
                    <button class="btn btn-sm btn-outline" onclick="viewTrace('${r.id}')">View</button>
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Agent runs load error:', err);
    }
}

// Filters
document.getElementById('filter-agent-status')?.addEventListener('change', loadAgentRuns);
document.getElementById('filter-agent-name')?.addEventListener('change', loadAgentRuns);

// ════════════════════════════════════════════════════════════════════════
// TRACE VIEWER
// ════════════════════════════════════════════════════════════════════════

async function viewTrace(runId) {
    switchSection('trace-viewer');

    try {
        const resp = await fetch(`/admin/api/agent-runs/${runId}`);
        const run = await resp.json();
        const detail = document.getElementById('trace-detail');

        detail.innerHTML = `
            <div class="trace-header">
                <h2>${escapeHtml(run.agent_name)} – Run Detail</h2>
                <span class="badge badge-${run.status}">${run.status}</span>
            </div>

            <div class="trace-meta">
                <div class="trace-meta-item">
                    <span class="label">Run ID</span>
                    <span class="value" style="font-family:var(--font-mono);font-size:0.8rem">${run.id}</span>
                </div>
                <div class="trace-meta-item">
                    <span class="label">Request ID</span>
                    <span class="value" style="font-family:var(--font-mono);font-size:0.8rem">${run.request_id}</span>
                </div>
                <div class="trace-meta-item">
                    <span class="label">Started</span>
                    <span class="value">${run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</span>
                </div>
                <div class="trace-meta-item">
                    <span class="label">Duration</span>
                    <span class="value">${run.duration_ms ? (run.duration_ms / 1000).toFixed(2) + 's' : '—'}</span>
                </div>
                <div class="trace-meta-item">
                    <span class="label">Retries</span>
                    <span class="value">${run.retry_count}</span>
                </div>
            </div>

            ${run.input_summary ? `
                <div class="trace-section">
                    <h3>📥 Input Summary</h3>
                    <div class="trace-code">${escapeHtml(run.input_summary)}</div>
                </div>
            ` : ''}

            ${run.output_summary ? `
                <div class="trace-section">
                    <h3>📤 Output Summary</h3>
                    <div class="trace-code">${escapeHtml(run.output_summary)}</div>
                </div>
            ` : ''}

            ${run.error_type ? `
                <div class="trace-section">
                    <h3>❌ Error: ${escapeHtml(run.error_type)}</h3>
                    <div class="trace-code" style="color:#fca5a5">${escapeHtml(run.error_message || '')}</div>
                </div>
            ` : ''}

            ${run.error_traceback ? `
                <div class="trace-section">
                    <h3>🔍 Full Traceback</h3>
                    <div class="trace-code">${escapeHtml(run.error_traceback)}</div>
                </div>
            ` : ''}
        `;
    } catch (err) {
        console.error('Trace load error:', err);
    }
}

// ════════════════════════════════════════════════════════════════════════
// MODAL
// ════════════════════════════════════════════════════════════════════════

let modalSaveCallback = null;

function setupModal() {
    document.getElementById('modal-close').addEventListener('click', closeModal);
    document.getElementById('modal-cancel').addEventListener('click', closeModal);
    document.getElementById('modal-save').addEventListener('click', () => {
        if (modalSaveCallback) modalSaveCallback();
    });
    document.getElementById('modal-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
}

function openModal(title, bodyHtml, onSave) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-overlay').classList.remove('hidden');
    modalSaveCallback = onSave;
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    modalSaveCallback = null;
}

// ════════════════════════════════════════════════════════════════════════
// UTILITIES
// ════════════════════════════════════════════════════════════════════════

function formatNumber(n) {
    if (n == null) return '—';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return String(n);
}

function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function animateValue(elementId, targetValue) {
    const el = document.getElementById(elementId);
    if (el) el.textContent = targetValue;
}

// ── Auto-refresh dashboard every 30s ──
function startAutoRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        const activeSection = document.querySelector('.content-section.active');
        if (activeSection?.id === 'section-dashboard') loadDashboard();
        if (activeSection?.id === 'section-agent-runs') loadAgentRuns();
        if (activeSection?.id === 'section-job-queue') loadJobQueue();
    }, 30000);
}

// ════════════════════════════════════════════════════════════════════════
// JOB QUEUE
// ════════════════════════════════════════════════════════════════════════

async function loadJobQueue() {
    const statusFilter = document.getElementById('filter-job-status').value;
    let url = '/api/enrich/?limit=100';
    if (statusFilter) url += `&status_filter=${statusFilter}`;

    try {
        const resp = await fetch(url);
        const jobs = await resp.json();
        const tbody = document.getElementById('job-queue-tbody');

        if (!jobs.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">No enrichment requests found.</td></tr>';
            return;
        }

        tbody.innerHTML = jobs.map(job => {
            const canRun = job.status === 'pending' || job.status === 'failed';
            const runBtn = canRun
                ? `<button class="btn btn-sm btn-primary" onclick="triggerEnrichment('${job.id}')">▶ Run</button>`
                : job.status === 'processing'
                    ? `<span style="color:var(--text-muted)">⏳ Running…</span>`
                    : '';

            const hasRuns = job.status !== 'pending';
            const viewBtn = hasRuns
                ? `<button class="btn btn-sm btn-outline" onclick="viewJobRuns('${job.id}')">🔍 Traces</button>`
                : '';

            return `
                <tr>
                    <td><strong>${escapeHtml(job.company_name)}</strong></td>
                    <td>${escapeHtml(job.source)}</td>
                    <td><span class="badge badge-${job.status}">${job.status}</span></td>
                    <td>${job.requested_by ? escapeHtml(job.requested_by) : '—'}</td>
                    <td>${new Date(job.created_at).toLocaleString()}</td>
                    <td>${runBtn} ${viewBtn}</td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Job queue load error:', err);
    }
}

async function triggerEnrichment(requestId) {
    if (!confirm('Start enrichment processing for this request?')) return;

    try {
        const resp = await fetch(`/admin/api/trigger-enrichment/${requestId}`, {
            method: 'POST',
        });
        const data = await resp.json();

        if (!resp.ok) {
            alert(data.detail || 'Failed to trigger enrichment');
            return;
        }

        alert(data.message || 'Enrichment triggered successfully!');
        loadJobQueue();
    } catch (err) {
        console.error('Trigger enrichment error:', err);
        alert('Failed to trigger enrichment. Check console for details.');
    }
}

// Navigate to agent runs filtered by a specific enrichment request
function viewJobRuns(requestId) {
    // Store the request ID so loadAgentRuns can use it
    window._filterByRequestId = requestId;
    switchSection('agent-runs');
}

// Filter listener
document.getElementById('filter-job-status')?.addEventListener('change', loadJobQueue);
