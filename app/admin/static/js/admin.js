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
    initToastContainer();
    await loadCurrentUser();
    setupNavigation();
    setupSidebar();
    setupLogout();
    setupModal();
    document.getElementById('add-tool-btn').addEventListener('click', addTool);
    await loadDashboard();
    startAutoRefresh();
    
    // Listen for completion messages from live execution iframe
    window.addEventListener('message', (event) => {
        if (event.data && event.data.type === 'PIPELINE_COMPLETE') {
            const activeSection = document.querySelector('.content-section.active');
            if (activeSection && activeSection.id === 'section-trace-viewer') {
                viewTrace(event.data.runId);
            }
        }
    });
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
        'workflow-runs': loadWorkflowRuns,
        'response-eval': loadResponseEval,
        'job-queue': loadJobQueue,
        'settings': loadSettings,
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
                    labels: { color: '#475569', padding: 15, font: { family: "'Inter'" } }
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
                    ticks: { color: '#475569', font: { family: "'Inter'" } },
                    grid: { display: false },
                    border: { display: false },
                },
                y: {
                    ticks: { color: '#94a3b8', stepSize: 1, font: { family: "'Inter'" } },
                    grid: { color: 'rgba(37,99,235,0.06)' },
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

const CATEGORY_OPTIONS = [
    { value: 'contact', label: 'Contact Data' },
    { value: 'news', label: 'News Search' },
    { value: 'financial', label: 'Financial Data' },
    { value: 'fallback', label: 'Fallback Search' },
];

function categorySelectHtml(selectedValue) {
    return CATEGORY_OPTIONS.map(o =>
        `<option value="${o.value}" ${o.value === (selectedValue || 'contact') ? 'selected' : ''}>${o.label}</option>`
    ).join('');
}

async function loadTools() {
    try {
        const resp = await fetch('/admin/api/tools');
        let tools = await resp.json();
        const grid = document.getElementById('tool-grid');
        // Group by category visually inside the grid
        tools.sort((a, b) => {
            if(a.category !== b.category) return (a.category || '').localeCompare(b.category || '');
            return (a.sequence_number || 1) - (b.sequence_number || 1);
        });
        grid.innerHTML = tools.length ? tools.map(renderToolCard).join('') : '<p style="color:var(--text-muted)">No tools configured yet.</p>';
    } catch (err) {
        console.error('Tools load error:', err);
    }
}

function renderToolCard(tool) {
    const agentLabel = AGENT_OPTIONS.find(o => o.value === tool.agent_name)?.label || tool.agent_name || '— None —';
    const catLabel = CATEGORY_OPTIONS.find(o => o.value === tool.category)?.label || tool.category || '—';
    return `
        <div class="tool-card glass" style="${tool.is_enabled ? '' : 'opacity: 0.7;'} border-top: 3px solid var(--accent)">
            <div class="tool-card-header">
                <h3>${escapeHtml(tool.display_name)}</h3>
                <span class="badge badge-${tool.health_status}">${tool.health_status}</span>
            </div>
            <div class="tool-card-body">
                <div><span class="field-label">System Name:</span> ${escapeHtml(tool.tool_name)}</div>
                <div><span class="field-label">Category:</span> <span class="badge" style="background:var(--bg-tertiary); color:var(--text-primary)">${escapeHtml(catLabel)} (Seq: ${tool.sequence_number || 1})</span></div>
                <div><span class="field-label">Env Config:</span> ${tool.env_configured ? '<span style="color:#22c55e">✅ Configured</span>' : '<span style="color:#ef4444">❌ Not set</span>'}</div>
                <div>
                    <span class="field-label">Status:</span>
                    <select class="enabled-select" onchange="toggleTool('${tool.tool_name}', this.value)">
                        <option value="true" ${tool.is_enabled ? 'selected' : ''}>Enabled</option>
                        <option value="false" ${!tool.is_enabled ? 'selected' : ''}>Disabled</option>
                    </select>
                </div>
            </div>
            <div class="tool-card-actions">
                <button class="btn btn-sm btn-outline" onclick="editTool('${tool.tool_name}')">Configure</button>
                <button class="btn btn-sm btn-outline" onclick="healthCheck('${tool.tool_name}')">Health Check</button>
            </div>
        </div>
    `;
}

function addTool() {
    openModal('Add New Tool', `
        <div class="form-group">
            <label>Tool Name (System Identifier) <span style="color:#ef4444">*</span></label>
            <input id="add-tool-name" placeholder="e.g. lusha, apollo">
        </div>
        <div class="form-group">
            <label>Display Name</label>
            <input id="add-display-name" placeholder="Tool display name">
        </div>
        <div class="form-group" style="display:flex; gap:1rem;">
            <div style="flex:1">
                <label>Category</label>
                <select id="add-category">${categorySelectHtml('contact')}</select>
            </div>
            <div style="flex:1">
                <label>Sequence Number</label>
                <input id="add-sequence" type="number" value="1" min="1">
            </div>
        </div>
        <div class="form-group">
            <label>API Key / Credential</label>
            <input id="add-api-key" placeholder="Enter API Key from provider">
        </div>
        <div class="form-group">
            <label>Status</label>
            <select id="add-is-enabled">
                <option value="true" selected>Enabled</option>
                <option value="false">Disabled</option>
            </select>
        </div>
        <p class="form-hint" style="font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem">
            This stores credentials in the DB, overriding the old .env method.
        </p>
    `, async () => {
        const toolName = document.getElementById('add-tool-name').value.trim();
        if (!toolName) {
            showToast('warning', 'Validation', 'Tool Name is required.');
            return;
        }

        const body = {};
        const displayName = document.getElementById('add-display-name').value.trim();
        body.display_name = displayName || toolName;
        body.category = document.getElementById('add-category').value;
        body.sequence_number = parseInt(document.getElementById('add-sequence').value) || 1;
        
        const apiKey = document.getElementById('add-api-key').value.trim();
        if (apiKey) body.api_key = apiKey;

        body.is_enabled = document.getElementById('add-is-enabled').value === 'true';

        try {
            const resp = await fetch(`/admin/api/tools/${encodeURIComponent(toolName)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast('error', 'Error', err.detail || 'Failed to add tool');
                return;
            }
            closeModal();
            showToast('success', 'Tool Added', `"${toolName}" has been added successfully.`);
            loadTools();
        } catch (err) {
            console.error('Add tool error:', err);
            showToast('error', 'Error', 'Failed to add tool. Check console for details.');
        }
    });
}

async function toggleTool(toolName, enabledStr) {
    const enabled = enabledStr === 'true';
    try {
        const resp = await fetch(`/admin/api/tools/${toolName}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_enabled: enabled }),
        });
        if (resp.ok) {
            showToast('success', 'Updated', `${toolName} ${enabled ? 'enabled' : 'disabled'} successfully.`);
        } else {
            showToast('error', 'Error', 'Failed to update tool status.');
        }
    } catch (err) {
        console.error('Toggle tool error:', err);
        showToast('error', 'Error', 'Failed to update tool status.');
    }
    loadTools();
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
        <div class="form-group" style="display:flex; gap:1rem;">
            <div style="flex:1">
                <label>Category</label>
                <select id="edit-category">${categorySelectHtml(currentTool.category)}</select>
            </div>
            <div style="flex:1">
                <label>Sequence Number</label>
                <input id="edit-sequence" type="number" value="${currentTool.sequence_number || 1}" min="1">
            </div>
        </div>
        <div class="form-group">
            <label>API Key / Credential</label>
            <input id="edit-api-key" placeholder="${currentTool.api_key ? '•••• (Stored in DB. Enter value to update)' : 'Leave blank. DB string empty'}" value="">
        </div>
        <div class="form-group">
            <label>Status</label>
            <select id="edit-is-enabled">
                <option value="true" ${currentTool.is_enabled ? 'selected' : ''}>Enabled</option>
                <option value="false" ${!currentTool.is_enabled ? 'selected' : ''}>Disabled</option>
            </select>
        </div>
        <p class="form-hint" style="font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem">
            Tool credentials are now saved in the database.
        </p>
    `, async () => {
        const body = {};
        const name = document.getElementById('edit-display-name').value;
        if (name) body.display_name = name;
        
        body.category = document.getElementById('edit-category').value;
        body.sequence_number = parseInt(document.getElementById('edit-sequence').value) || 1;
        
        const apiKey = document.getElementById('edit-api-key').value.trim();
        if (apiKey) body.api_key = apiKey;

        body.is_enabled = document.getElementById('edit-is-enabled').value === 'true';

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
    const variant = data.health_status === 'healthy' ? 'success'
        : data.health_status === 'degraded' ? 'warning' : 'error';
    showToast(variant, 'Health Check', `${toolName}: ${data.health_status}`);
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
                    backgroundColor: 'rgba(37, 99, 235, 0.7)',
                    borderRadius: 4,
                },
                {
                    label: 'Completion Tokens',
                    data: completionTokens,
                    backgroundColor: 'rgba(29, 78, 216, 0.55)',
                    borderRadius: 4,
                }
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { color: '#475569', font: { family: "'Inter'" } } }
            },
            scales: {
                x: { ticks: { color: '#475569' }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(37,99,235,0.06)' }, border: { display: false } }
            }
        }
    });
}

// Listen for days selector change
document.getElementById('token-days')?.addEventListener('change', loadTokenUsage);

// ════════════════════════════════════════════════════════════════════════
// AGENT RUNS (grouped by job)
// ════════════════════════════════════════════════════════════════════════

const AGENT_LABELS = {
    contact_agent: '📇 Contact Agent',
    news_agent: '📰 News Agent',
    financial_agent: '💰 Financial Agent',
    aggregation_agent: '🔗 Aggregation Agent',
};

const AGENT_ICONS = {
    contact_agent: '📇',
    news_agent: '📰',
    financial_agent: '💰',
    aggregation_agent: '🔗',
};

async function loadAgentRuns() {
    const statusFilter = document.getElementById('filter-agent-status').value;
    const agentFilter = document.getElementById('filter-agent-name').value;

    let url = '/admin/api/agent-runs?limit=50&pipeline_type=crew';
    if (statusFilter) url += `&status_filter=${statusFilter}`;
    if (agentFilter) url += `&agent_name=${agentFilter}`;

    // Support filtering by request_id (from Job Queue → View Runs)
    if (window._filterByRequestId) {
        url += `&request_id=${window._filterByRequestId}`;
        window._filterByRequestId = null;  // Clear after use
    }

    try {
        const resp = await fetch(url);
        const jobs = await resp.json();
        const container = document.getElementById('agent-runs-container');

        if (!jobs.length) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:3rem 0">No agent runs found.</p>';
            return;
        }

        container.innerHTML = jobs.map((job, idx) => {
            const agentCount = job.agents ? job.agents.length : 0;
            const completedCount = job.agents ? job.agents.filter(a => a.status === 'completed').length : 0;
            const failedCount = job.agents ? job.agents.filter(a => a.status === 'failed').length : 0;

            // Determine overall badge for agent runs
            let agentsBadge = 'completed';
            if (failedCount > 0) agentsBadge = 'failed';
            else if (completedCount < agentCount) agentsBadge = 'running';

            const agentsHtml = (job.agents || []).map(agent => `
                <div class="agent-run-card glass">
                    <div class="agent-run-card-header">
                        <span class="agent-run-icon">${AGENT_ICONS[agent.agent_name] || '🤖'}</span>
                        <span class="agent-run-name">${escapeHtml(AGENT_LABELS[agent.agent_name] || agent.agent_name)}</span>
                        <span class="badge badge-${agent.status}">${agent.status}</span>
                    </div>
                    <div class="agent-run-card-body">
                        <div class="agent-run-meta">
                            <span class="agent-meta-label">Started</span>
                            <span class="agent-meta-value">${agent.started_at ? new Date(agent.started_at).toLocaleString() : '—'}</span>
                        </div>
                        <div class="agent-run-meta">
                            <span class="agent-meta-label">Duration</span>
                            <span class="agent-meta-value">${agent.duration_ms ? (agent.duration_ms / 1000).toFixed(1) + 's' : '—'}</span>
                        </div>
                        ${agent.error_message ? `
                        <div class="agent-run-meta agent-run-error">
                            <span class="agent-meta-label">Error</span>
                            <span class="agent-meta-value">${escapeHtml(agent.error_message)}</span>
                        </div>
                        ` : ''}
                    </div>
                    <div class="agent-run-card-footer">
                        <button class="btn btn-sm btn-outline" onclick="viewTrace('${agent.id}')">🔍 View Trace</button>
                    </div>
                </div>
            `).join('');

            return `
                <div class="job-group glass">
                    <div class="job-header" onclick="toggleJobPanel(this)" id="job-header-${idx}">
                        <div class="job-header-left">
                            <span class="job-chevron">▶</span>
                            <div class="job-info">
                                <span class="job-company">${escapeHtml(job.company_name)}</span>
                                <span class="job-request-id">${job.request_id.substring(0, 8)}…</span>
                            </div>
                        </div>
                        <div class="job-header-right">
                            <span class="job-agent-count">${completedCount}/${agentCount} agents</span>
                            <span class="badge badge-${job.status}">${job.status}</span>
                            <span class="job-time">${job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</span>
                        </div>
                    </div>
                    <div class="job-agents-panel" id="job-panel-${idx}">
                        <div class="job-agents-grid">
                            ${agentsHtml}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Agent runs load error:', err);
    }
}

async function loadWorkflowRuns() {
    const statusFilter = document.getElementById('filter-workflow-status').value;

    let url = '/admin/api/agent-runs?limit=50&pipeline_type=workflow';
    if (statusFilter) url += `&status_filter=${statusFilter}`;

    // Support filtering by request_id (from Job Queue → View Runs)
    if (window._filterByRequestId) {
        url += `&request_id=${window._filterByRequestId}`;
        window._filterByRequestId = null;  // Clear after use
    }

    try {
        const resp = await fetch(url);
        const jobs = await resp.json();
        const container = document.getElementById('workflow-runs-container');

        if (!jobs.length) {
            container.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:3rem 0">No workflow runs found.</p>';
            return;
        }

        container.innerHTML = jobs.map((job, idx) => {
            const agentCount = job.agents ? job.agents.length : 0;
            const completedCount = job.agents ? job.agents.filter(a => a.status === 'completed').length : 0;
            
            const agentsHtml = (job.agents || []).map(agent => `
                <div class="agent-run-card glass">
                    <div class="agent-run-card-header">
                        <span class="agent-run-icon">🛤️</span>
                        <span class="agent-run-name">Deterministic Workflow</span>
                        <span class="badge badge-${agent.status}">${agent.status}</span>
                    </div>
                    <div class="agent-run-card-body">
                        <div class="agent-run-meta">
                            <span class="agent-meta-label">Started</span>
                            <span class="agent-meta-value">${agent.started_at ? new Date(agent.started_at).toLocaleString() : '—'}</span>
                        </div>
                        <div class="agent-run-meta">
                            <span class="agent-meta-label">Duration</span>
                            <span class="agent-meta-value">${agent.duration_ms ? (agent.duration_ms / 1000).toFixed(1) + 's' : '—'}</span>
                        </div>
                        ${agent.error_message ? `
                        <div class="agent-run-meta agent-run-error">
                            <span class="agent-meta-label">Error</span>
                            <span class="agent-meta-value">${escapeHtml(agent.error_message)}</span>
                        </div>
                        ` : ''}
                    </div>
                    <div class="agent-run-card-footer">
                        <button class="btn btn-sm btn-outline" onclick="viewTrace('${agent.id}', 'workflow-runs')">🔍 View Trace</button>
                    </div>
                </div>
            `).join('');

            return `
                <div class="job-group glass">
                    <div class="job-header" onclick="toggleJobPanel(this)" id="job-header-wf-${idx}">
                        <div class="job-header-left">
                            <span class="job-chevron">▶</span>
                            <div class="job-info">
                                <span class="job-company">${escapeHtml(job.company_name)}</span>
                                <span class="job-request-id">${job.request_id.substring(0, 8)}…</span>
                            </div>
                        </div>
                        <div class="job-header-right">
                            <span class="badge badge-${job.status}">${job.status}</span>
                            <span class="job-time">${job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</span>
                        </div>
                    </div>
                    <div class="job-agents-panel" id="job-panel-wf-${idx}">
                        <div class="job-agents-grid">
                            ${agentsHtml}
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Workflow runs load error:', err);
    }
}

function toggleJobPanel(header) {
    const group = header.closest('.job-group');
    const panel = group.querySelector('.job-agents-panel');
    const chevron = header.querySelector('.job-chevron');

    const isOpen = group.classList.contains('open');
    if (isOpen) {
        panel.style.maxHeight = panel.scrollHeight + 'px';
        // Force reflow
        panel.offsetHeight;
        panel.style.maxHeight = '0';
        group.classList.remove('open');
    } else {
        group.classList.add('open');
        panel.style.maxHeight = panel.scrollHeight + 'px';
        panel.addEventListener('transitionend', function handler() {
            if (group.classList.contains('open')) {
                panel.style.maxHeight = 'none';
            }
            panel.removeEventListener('transitionend', handler);
        });
    }
}

// Filters
document.getElementById('filter-agent-status')?.addEventListener('change', loadAgentRuns);
document.getElementById('filter-agent-name')?.addEventListener('change', loadAgentRuns);

// ════════════════════════════════════════════════════════════════════════
// TRACE VIEWER
// ════════════════════════════════════════════════════════════════════════

/**
 * Try to pretty-print JSON content; fall back to escaped plain text.
 */
function formatOutputSummary(text) {
    if (!text) return '—';
    try {
        const parsed = JSON.parse(text);
        return escapeHtml(JSON.stringify(parsed, null, 2));
    } catch {
        return escapeHtml(text);
    }
}

async function viewTrace(runId) {
    switchSection('trace-viewer');

    try {
        const resp = await fetch(`/admin/api/agent-runs/${runId}`);
        const run = await resp.json();
        const detail = document.getElementById('trace-detail');
        const agentLabel = AGENT_LABELS[run.agent_name] || run.agent_name;

        detail.innerHTML = `
            <button class="btn btn-sm btn-outline back-btn" onclick="switchSection('agent-runs')">
                ← Back to Agent Runs
            </button>

            <div class="trace-header">
                <h2>${escapeHtml(agentLabel)} – Run Detail</h2>
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

            ${run.agent_name === 'workflow_pipeline' ? `
                <div class="trace-section">
                    <h3>📡 Live Execution Monitor</h3>
                    <iframe
                        id="live-exec-iframe"
                        src="/admin/trace/${run.id}/live-execution"
                        style="
                            width: 100%;
                            height: 520px;
                            border: 1px solid rgba(56, 189, 248, 0.2);
                            border-radius: 10px;
                            background: #0b1120;
                            margin-top: 0.5rem;
                        "
                    ></iframe>
                    ${run.status === 'running' ? `
                        <div style="text-align: center; margin-top: 0.75rem;">
                            <button class="btn btn-sm btn-outline" onclick="viewTrace('${run.id}')" style="font-size: 0.8rem;">
                                🔄 Refresh Status
                            </button>
                        </div>
                    ` : ''}
                </div>
            ` : ''}

            ${run.output_summary ? `
                <div class="trace-section">
                    <h3>📤 Output Summary</h3>
                    ${run.agent_name === 'workflow_pipeline' ? renderWorkflowPipeline(run.output_summary) : ''}
                    ${run.agent_name === 'workflow_pipeline' ? renderActivityLog(run.output_summary, run.id) : ''}
                    ${run.agent_name === 'workflow_pipeline' ? renderLlmDebug(run.output_summary, run.id) : ''}
                    <details ${run.agent_name === 'workflow_pipeline' ? '' : 'open'} style="margin-top: 1rem;">
                        <summary style="cursor:pointer; font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); margin-bottom: 0.5rem;">Raw JSON Debug Output</summary>
                        ${run.agent_name === 'workflow_pipeline' ? renderAgentFinalAnswer(run.output_summary) : ''}
                        <div class="trace-code trace-code-full">${formatOutputSummary(run.output_summary)}</div>
                    </details>
                </div>
            ` : ''}

            ${run.error_type ? `
                <div class="trace-section">
                    <h3>❌ Error: ${escapeHtml(run.error_type)}</h3>
                    <div class="trace-code" style="color:#b91c1c">${escapeHtml(run.error_message || '')}</div>
                </div>
            ` : ''}

            ${run.error_traceback ? `
                <div class="trace-section">
                    <h3>🔍 Full Traceback</h3>
                    <div class="trace-code trace-code-full">${escapeHtml(run.error_traceback)}</div>
                </div>
            ` : ''}
        `;
    } catch (err) {
        console.error('Trace load error:', err);
    }
}

function renderWorkflowPipeline(summaryStr) {
    let data;
    try {
        data = JSON.parse(summaryStr);
    } catch {
        return '';
    }
    
    // Step 1: API Polling
    const sources = data.sources_used || [];
    const fetchErrors = data.fetch_errors || [];
    const fetchStatus = fetchErrors.length > 0 ? 'failed' : (sources.length > 0 ? 'completed' : 'skipped');
    const fetchDetail = fetchErrors.length > 0 
        ? `${fetchErrors.length} errors (${sources.length} sources)`
        : `${sources.length} underlying APIs used`;
        
    // Step 2: Deterministic Normalization
    const normStatus = 'completed'; // always completes if it reached final_output

    // Step 3: LLM Merging
    const llmStatus = 'completed'; 
    const llmDetail = data.executive_summary ? 'Summary & Scoring generated' : 'Merged contacts';

    // Step 4: Hybrid Fallback
    const fallbackStatus = data.fallback_triggered ? 'completed' : (sources.length === 0 ? 'failed' : 'skipped');
    const enrichSources = data.enrichment_source || {};
    const isLlmOnlyFallback = Object.values(enrichSources).some(v => v === 'LLM_Only_Fallback');
    let fallbackDetail;
    if (data.fallback_triggered) {
        fallbackDetail = `${Object.keys(data.fallback_recovered_data || {}).length} fields recovered via ${isLlmOnlyFallback ? 'LLM (no tools)' : 'Agent'}`;
    } else if (sources.length === 0) {
        fallbackDetail = '⚠ No APIs enabled — fallback should have triggered';
    } else {
        fallbackDetail = 'Sufficient data found; Agent skipped';
    }
        
    // Step 5: Salesforce Webhook
    const syncStatus = 'completed';
    const syncDetail = 'Mapped & triggered outbound POST';

    return `
        <div class="pipeline-stepper">
            <div class="pipeline-step ${fetchStatus}">
                <div class="pipeline-step-icon">🔌</div>
                <div class="pipeline-step-label">API Polling</div>
                <div class="pipeline-step-detail">${fetchDetail}</div>
            </div>
            
            <div class="pipeline-step ${normStatus}">
                <div class="pipeline-step-icon">⚙️</div>
                <div class="pipeline-step-label">Normalization</div>
                <div class="pipeline-step-detail">Deterministic deduplication</div>
            </div>
            
            <div class="pipeline-step ${llmStatus}">
                <div class="pipeline-step-icon">🧠</div>
                <div class="pipeline-step-label">LLM Intelligence</div>
                <div class="pipeline-step-detail">${llmDetail}</div>
            </div>
            
            <div class="pipeline-step ${fallbackStatus}">
                <div class="pipeline-step-icon">🤖</div>
                <div class="pipeline-step-label">Hybrid Fallback</div>
                <div class="pipeline-step-detail">${fallbackDetail}</div>
            </div>
            
            <div class="pipeline-step ${syncStatus}">
                <div class="pipeline-step-icon">☁️</div>
                <div class="pipeline-step-label">Salesforce Sync</div>
                <div class="pipeline-step-detail">${syncDetail}</div>
            </div>
        </div>
    `;
}

function renderActivityLog(summaryStr, runId) {
    let data;
    try {
        data = JSON.parse(summaryStr);
    } catch {
        return '';
    }

    const logs = data.activity_log || [];
    if (!logs.length) {
        return '';
    }

    return `
        <div class="activity-log-section" style="margin-top: 1.25rem;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.75rem;">
                <h3 style="margin: 0; font-size: 0.95rem; font-weight: 600; color: var(--text-primary);">
                    🚀 Crew Execution Log <span style="font-weight: 400; color: var(--text-muted); font-size: 0.8rem;">(${logs.length} steps)</span>
                </h3>
                <button class="btn btn-sm btn-outline" onclick="copyCrewLog(this)" style="font-size: 0.75rem; padding: 0.25rem 0.5rem;">
                    📋 Copy Log
                </button>
            </div>

            <iframe
                id="crew-exec-iframe-${runId}"
                src="/admin/trace/${runId}/crew-execution"
                style="
                    width: 100%;
                    height: 480px;
                    border: 1px solid rgba(37, 99, 235, 0.15);
                    border-radius: 10px;
                    background: #0b1120;
                "
            ></iframe>

            <details style="margin-top: 0.75rem;">
                <summary style="cursor:pointer; font-size: 0.8rem; font-weight: 600; color: var(--text-muted); margin-bottom: 0.5rem;">
                    📋 Raw Terminal Log
                </summary>
                <iframe
                    src="/admin/trace/${runId}/logs"
                    style="
                        width: 100%;
                        height: 300px;
                        border: 1px solid rgba(37, 99, 235, 0.15);
                        border-radius: 8px;
                        background: #0f1729;
                    "
                ></iframe>
            </details>

            <textarea class="crew-log-data" style="display:none">${escapeHtml(logs.join('\n'))}</textarea>
        </div>
    `;
}


function copyActivityLog(btn) {
    const section = btn.closest('.activity-log-section');
    const textarea = section.querySelector('textarea');
    if (textarea) {
        navigator.clipboard.writeText(textarea.value).then(() => {
            const original = btn.innerHTML;
            btn.innerHTML = '✅ Copied!';
            setTimeout(() => { btn.innerHTML = original; }, 1500);
        });
    }
}

function copyCrewLog(btn) {
    const section = btn.closest('.activity-log-section');
    const textarea = section.querySelector('.crew-log-data');
    if (textarea) {
        navigator.clipboard.writeText(textarea.value).then(() => {
            const original = btn.innerHTML;
            btn.innerHTML = '✅ Copied!';
            setTimeout(() => { btn.innerHTML = original; }, 1500);
        });
    }
}

function renderAgentFinalAnswer(summaryStr) {
    let data;
    try {
        data = JSON.parse(summaryStr);
    } catch {
        return '';
    }
    const debug = data.llm_debug || {};
    const agentAnswer = debug.agent_final_answer || '';
    if (!agentAnswer) return '';

    return `
        <div style="margin-top: 1.25rem; margin-bottom: 1.25rem;">
            <h3 style="font-size: 0.95rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.75rem;">
                ✅ Agent Final Answer
            </h3>
            <textarea readonly style="
                width: 100%;
                min-height: 150px;
                background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
                border: 1px solid rgba(22, 163, 74, 0.2);
                border-left: 4px solid #16a34a;
                border-radius: 8px;
                padding: 1rem 1.25rem;
                font-family: var(--font-mono, 'Fira Code', monospace);
                font-size: 0.82rem;
                line-height: 1.65;
                resize: vertical;
                color: #1e293b;
            ">${escapeHtml(agentAnswer)}</textarea>
        </div>
    `;
}

function renderLlmDebug(summaryStr, runId) {
    let data;
    try {
        data = JSON.parse(summaryStr);
    } catch {
        return '';
    }

    const debug = data.llm_debug || {};
    if (!debug.step7_prompt && !debug.step7_raw_output && !debug.fallback_prompt) {
        return '';
    }

    const textareaStyle = `
        width: 100%;
        min-height: 180px;
        max-height: 500px;
        padding: 0.75rem;
        font-family: var(--font-mono, 'Fira Code', 'Cascadia Code', Consolas, monospace);
        font-size: 0.78rem;
        line-height: 1.5;
        border: 1px solid rgba(37, 99, 235, 0.15);
        border-radius: 8px;
        resize: vertical;
        white-space: pre-wrap;
        word-wrap: break-word;
    `;

    const inputStyle = textareaStyle + 'background: #0d1b2a; color: #7ec8e3;';
    const outputStyle = textareaStyle + 'background: #0f1729; color: #a8d8a8;';

    let html = '<div style="margin-top: 1.25rem;">';
    html += '<h3 style="font-size: 0.95rem; font-weight: 600; color: var(--text-primary); margin-bottom: 0.75rem;">🔬 LLM Debug I/O</h3>';

    // Step 7: LLM Intelligence
    if (debug.step7_prompt || debug.step7_raw_output) {
        html += `
            <details style="margin-bottom: 0.75rem; border: 1px solid rgba(37,99,235,0.1); border-radius: 8px; overflow: hidden;">
                <summary style="cursor:pointer; padding: 0.6rem 0.75rem; font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); background: rgba(37,99,235,0.03);">
                    🧠 Step 7 — LLM Intelligence I/O
                </summary>
                <div style="padding: 0.75rem;">
                    ${debug.step7_prompt ? `
                        <div style="margin-bottom: 0.75rem;">
                            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.35rem;">
                                <span style="font-size:0.8rem; font-weight:600; color:#7ec8e3;">📥 Input Prompt</span>
                                <span style="font-size:0.7rem; color:var(--text-muted);">${debug.step7_prompt.length.toLocaleString()} chars</span>
                            </div>
                            <textarea readonly style="${inputStyle}">${escapeHtml(debug.step7_prompt)}</textarea>
                        </div>
                    ` : ''}
                    ${debug.step7_raw_output ? `
                        <div>
                            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.35rem;">
                                <span style="font-size:0.8rem; font-weight:600; color:#a8d8a8;">📤 Raw LLM Output</span>
                                <span style="font-size:0.7rem; color:var(--text-muted);">${debug.step7_raw_output.length.toLocaleString()} chars</span>
                            </div>
                            <textarea readonly style="${outputStyle}">${escapeHtml(debug.step7_raw_output)}</textarea>
                        </div>
                    ` : ''}
                </div>
            </details>
        `;
    }

    // Step 7b: Fallback
    if (debug.fallback_prompt || debug.fallback_raw_output) {
        html += `
            <details style="margin-bottom: 0.75rem; border: 1px solid rgba(37,99,235,0.1); border-radius: 8px; overflow: hidden;">
                <summary style="cursor:pointer; padding: 0.6rem 0.75rem; font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); background: rgba(37,99,235,0.03);">
                    🤖 Step 7b — Fallback Agent I/O
                </summary>
                <div style="padding: 0.75rem;">
                    ${debug.fallback_prompt ? `
                        <div style="margin-bottom: 0.75rem;">
                            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.35rem;">
                                <span style="font-size:0.8rem; font-weight:600; color:#7ec8e3;">📥 Input Prompt</span>
                                <span style="font-size:0.7rem; color:var(--text-muted);">${debug.fallback_prompt.length.toLocaleString()} chars</span>
                            </div>
                            <textarea readonly style="${inputStyle}">${escapeHtml(debug.fallback_prompt)}</textarea>
                        </div>
                    ` : ''}
                    ${debug.fallback_raw_output ? `
                        <div>
                            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.35rem;">
                                <span style="font-size:0.8rem; font-weight:600; color:#a8d8a8;">📤 Raw LLM Output</span>
                                <span style="font-size:0.7rem; color:var(--text-muted);">${debug.fallback_raw_output.length.toLocaleString()} chars</span>
                            </div>
                            <textarea readonly style="${outputStyle}">${escapeHtml(debug.fallback_raw_output)}</textarea>
                        </div>
                    ` : ''}
                </div>
            </details>
        `;
    }

    html += '</div>';

    // ── Agent Final Answer — inline display ──
    const agentAnswer = debug.agent_final_answer || '';

    // ── Task Execution Trace iframe ──
    const toolExecs = debug.tool_executions || [];
    const fallbackTriggered = data.fallback_triggered || false;
    if (toolExecs.length > 0 || agentAnswer || fallbackTriggered) {
        html += `
            <div style="margin-top: 1.25rem;">
                <details open style="margin-bottom: 0.75rem; border: 1px solid rgba(37,99,235,0.1); border-radius: 8px; overflow: hidden;">
                    <summary style="cursor:pointer; padding: 0.6rem 0.75rem; font-size: 0.85rem; font-weight: 600; color: var(--text-secondary); background: rgba(37,99,235,0.03);">
                        🔧 Task Execution Trace (${toolExecs.length} tool call${toolExecs.length !== 1 ? 's' : ''})
                    </summary>
                    <div style="padding: 0;">
                        <iframe 
                            src="/admin/trace/${runId}/task-execution"
                            style="
                                width: 100%;
                                height: 500px;
                                border: none;
                                border-top: 1px solid rgba(37, 99, 235, 0.1);
                                background: #f5f7fa;
                            "
                        ></iframe>
                    </div>
                </details>
            </div>
        `;
    }

    return html;
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

// ── Toast Notifications ──

const TOAST_ICONS = {
    success: '✅',
    error: '❌',
    warning: '⚠️',
    info: 'ℹ️',
};

const TOAST_TITLES = {
    success: 'Success',
    error: 'Error',
    warning: 'Warning',
    info: 'Info',
};

function initToastContainer() {
    if (document.getElementById('toast-container')) return;
    const container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
}

/**
 * Show a styled toast notification popup.
 * @param {'success'|'error'|'warning'|'info'} variant
 * @param {string} title
 * @param {string} message
 * @param {number} duration  Auto-dismiss in milliseconds (default 4000)
 */
function showToast(variant = 'info', title, message, duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${variant}`;
    toast.style.position = 'relative';
    toast.innerHTML = `
        <span class="toast-icon">${TOAST_ICONS[variant] || TOAST_ICONS.info}</span>
        <div class="toast-body">
            <div class="toast-title">${escapeHtml(title || TOAST_TITLES[variant])}</div>
            <div class="toast-message">${escapeHtml(message)}</div>
        </div>
        <button class="toast-close" aria-label="Close">&times;</button>
        <div class="toast-progress" style="animation-duration:${duration}ms"></div>
    `;

    const dismiss = () => {
        toast.classList.add('toast-exit');
        setTimeout(() => toast.remove(), 300);
    };

    toast.querySelector('.toast-close').addEventListener('click', dismiss);

    container.appendChild(toast);

    // Auto-dismiss
    const timer = setTimeout(dismiss, duration);
    toast.addEventListener('mouseenter', () => clearTimeout(timer));
    toast.addEventListener('mouseleave', () => setTimeout(dismiss, 1500));
}

// ── Confirm Dialog ──

/**
 * Show a styled confirmation dialog (replaces window.confirm).
 * Returns a Promise<boolean>.
 * @param {string} title
 * @param {string} message
 * @returns {Promise<boolean>}
 */
function showConfirm(title, message) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'confirm-overlay';
        overlay.innerHTML = `
            <div class="confirm-dialog">
                <div class="confirm-header">
                    <span class="confirm-header-icon">❓</span>
                    <h3>${escapeHtml(title)}</h3>
                </div>
                <div class="confirm-body">${escapeHtml(message)}</div>
                <div class="confirm-footer">
                    <button class="btn btn-outline" id="confirm-cancel-btn">Cancel</button>
                    <button class="btn btn-primary" id="confirm-ok-btn">Confirm</button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        const close = (result) => {
            overlay.remove();
            resolve(result);
        };

        overlay.querySelector('#confirm-ok-btn').addEventListener('click', () => close(true));
        overlay.querySelector('#confirm-cancel-btn').addEventListener('click', () => close(false));
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) close(false);
        });

        // Focus the confirm button for keyboard accessibility
        setTimeout(() => overlay.querySelector('#confirm-ok-btn').focus(), 50);
    });
}

// ════════════════════════════════════════════════════════════════════════
// SYSTEM SETTINGS
// ════════════════════════════════════════════════════════════════════════

let currentPipeline = 'crew';

async function loadSettings() {
    try {
        const resp = await fetch('/admin/api/settings');
        const data = await resp.json();

        // Pipeline mode
        const pipeline = data.enrichment_pipeline?.value || 'crew';
        currentPipeline = pipeline;
        updatePipelineUI(pipeline);

        // Pipeline info
        const info = document.getElementById('pipeline-info');
        if (data.enrichment_pipeline?.updated_by) {
            info.innerHTML = `
                <span class="settings-meta">
                    Last changed by <strong>${escapeHtml(data.enrichment_pipeline.updated_by)}</strong>
                    ${data.enrichment_pipeline.updated_at ? ' on ' + new Date(data.enrichment_pipeline.updated_at).toLocaleString() : ''}
                </span>
            `;
        } else {
            info.innerHTML = '<span class="settings-meta">Using default setting</span>';
        }

        // Few-shot limit
        const fewShotInput = document.getElementById('few-shot-limit');
        if (fewShotInput && data.few_shot_limit) {
            fewShotInput.value = data.few_shot_limit.value || '3';
        }

        // Status badge
        const statusBadge = document.getElementById('settings-status');
        statusBadge.textContent = `Pipeline: ${pipeline}`;
        statusBadge.className = `badge ${pipeline === 'workflow' ? 'badge-processing' : 'badge-completed'}`;

    } catch (err) {
        console.error('Settings load error:', err);
        showToast('error', 'Error', 'Failed to load settings.');
    }
}

function updatePipelineUI(activePipeline) {
    const sel = document.getElementById('pipeline-select');
    if (sel) sel.value = activePipeline;
}

async function switchPipeline(newValue) {
    if (newValue === currentPipeline) return;

    const labels = { crew: 'Crew (Agent-Driven)', workflow: 'Workflow (Deterministic)' };
    const confirmed = await showConfirm(
        'Switch Pipeline',
        `Switch enrichment pipeline from "${labels[currentPipeline]}" to "${labels[newValue]}"?\n\nAll future enrichment requests will use the new pipeline.`
    );
    if (!confirmed) {
        // Revert the dropdown
        updatePipelineUI(currentPipeline);
        return;
    }

    try {
        const resp = await fetch(`/admin/api/settings/enrichment_pipeline`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: newValue }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast('error', 'Error', err.detail || 'Failed to update pipeline.');
            updatePipelineUI(currentPipeline);
            return;
        }

        currentPipeline = newValue;
        updatePipelineUI(newValue);
        showToast('success', 'Pipeline Updated', `Enrichment pipeline switched to "${labels[newValue]}".`);
        loadSettings();
    } catch (err) {
        console.error('Switch pipeline error:', err);
        showToast('error', 'Error', 'Failed to switch pipeline.');
        updatePipelineUI(currentPipeline);
    }
}

async function saveFewShotLimit() {
    const input = document.getElementById('few-shot-limit');
    const value = input ? input.value : '3';

    try {
        const resp = await fetch('/admin/api/settings/few_shot_limit', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: value }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            showToast('error', 'Error', err.detail || 'Failed to save few-shot limit.');
            return;
        }

        showToast('success', 'Saved', `Few-shot limit updated to ${value} examples.`);
    } catch (err) {
        console.error('Save few-shot limit error:', err);
        showToast('error', 'Error', 'Failed to save few-shot limit.');
    }
}

// Setup settings event handlers
document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('save-few-shot-btn')?.addEventListener('click', saveFewShotLimit);
});

// ── Auto-refresh dashboard every 30s ──
function startAutoRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        const activeSection = document.querySelector('.content-section.active');
        if (activeSection?.id === 'section-dashboard') loadDashboard();
        if (activeSection?.id === 'section-agent-runs') loadAgentRuns();
        if (activeSection?.id === 'section-workflow-runs') loadWorkflowRuns();
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

            const enhanceBtn = job.status === 'completed'
                ? `<button class="btn btn-sm btn-outline" style="margin-left: 0.25rem; color: #8b5cf6; border-color: #c4b5fd;" onclick="promptEnhance('${job.id}')">✨ Enhance</button>`
                : '';

            return `
                <tr>
                    <td><strong>${escapeHtml(job.company_name)}</strong></td>
                    <td>${escapeHtml(job.source)}</td>
                    <td><span class="badge badge-${job.status}">${job.status}</span></td>
                    <td>${job.requested_by ? escapeHtml(job.requested_by) : '—'}</td>
                    <td>${new Date(job.created_at).toLocaleString()}</td>
                    <td>${runBtn} ${viewBtn} ${enhanceBtn}</td>
                </tr>
            `;
        }).join('');
    } catch (err) {
        console.error('Job queue load error:', err);
    }
}

async function triggerEnrichment(requestId) {
    const confirmed = await showConfirm(
        'Start Enrichment',
        'Start enrichment processing for this request?'
    );
    if (!confirmed) return;

    try {
        const resp = await fetch(`/admin/api/trigger-enrichment/${requestId}`, {
            method: 'POST',
        });
        const data = await resp.json();

        if (!resp.ok) {
            showToast('error', 'Error', data.detail || 'Failed to trigger enrichment');
            return;
        }

        showToast('success', 'Enrichment Started', data.message || 'Enrichment triggered successfully!');
        
        // Wait briefly for the backend DB flush before navigating and fetching runs
        await new Promise(r => setTimeout(r, 600));
        
        // Navigate to workflow runs so the user can see the live monitor
        window._filterByRequestId = requestId;
        switchSection('workflow-runs');
    } catch (err) {
        console.error('Trigger enrichment error:', err);
        showToast('error', 'Error', 'Failed to trigger enrichment. Check console for details.');
    }
}

// Navigate to agent runs filtered by a specific enrichment request
function viewJobRuns(requestId) {
    // Store the request ID so the loader can use it
    window._filterByRequestId = requestId;
    // Route to the appropriate view based on the current active pipeline
    if (typeof currentPipeline !== 'undefined' && currentPipeline === 'workflow') {
        switchSection('workflow-runs');
    } else {
        switchSection('agent-runs');
    }
}

function promptEnhance(requestId) {
    openModal('✨ Enhance Lead Payload', `
        <div class="form-group">
            <label>Additional Instructions (Optional)</label>
            <textarea id="enhance-instructions" rows="4" class="settings-input" style="width:100%; resize:vertical; padding: 0.5rem;" placeholder="E.g., Rewrite the executive summary focusing only on enterprise sales, or compress the contact list..."></textarea>
        </div>
        <p class="form-hint" style="font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem">
            This will pass the current enriched lead payload back to the LLM with your new instructions.
        </p>
    `, async () => {
        const instructions = document.getElementById('enhance-instructions').value.trim();
        const btn = document.getElementById('modal-save');
        const oldText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Enhancing...';

        try {
            const resp = await fetch(`/api/enrich/${requestId}/enhance`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ instructions: instructions || null }),
            });

            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                showToast('error', 'Enhancement Failed', err.detail || 'Could not process enhancement.');
                btn.disabled = false;
                btn.textContent = oldText;
                return;
            }

            closeModal();
            showToast('success', 'Enhanced', 'Lead data has been successfully enhanced!');
            loadJobQueue();
        } catch (err) {
            console.error('Enhance error:', err);
            showToast('error', 'Error', 'Failed to connect to the enhancement endpoint.');
            btn.disabled = false;
            btn.textContent = oldText;
        }
    });
}

// Filter listener
document.getElementById('filter-job-status')?.addEventListener('change', loadJobQueue);

// ════════════════════════════════════════════════════════════════════════
// RESPONSE EVALUATION
// ════════════════════════════════════════════════════════════════════════

let evalChart = null;

const CACHE_STATUS_BADGES = {
    hit: '<span class="badge badge-completed">Hit</span>',
    miss: '<span class="badge badge-pending">Miss</span>',
    updated: '<span class="badge badge-partial">Updated</span>',
};

function boolBadge(val) {
    return val
        ? '<span class="badge badge-completed">✓</span>'
        : '<span class="badge badge-failed">✗</span>';
}

async function loadResponseEval() {
    const days = document.getElementById('eval-days')?.value || 30;
    const agentFilter = document.getElementById('eval-agent-filter')?.value || '';

    try {
        // Load summary KPIs
        const summaryResp = await fetch(`/admin/api/evaluations/summary?days=${days}`);
        const summary = await summaryResp.json();

        animateValue('kpi-determinism', summary.avg_determinism_score != null ? summary.avg_determinism_score + '%' : '—');
        animateValue('kpi-cache-hit', summary.cache_hit_rate != null ? summary.cache_hit_rate + '%' : '—');
        animateValue('kpi-schema-compliance', summary.schema_compliance_rate != null ? summary.schema_compliance_rate + '%' : '—');
        animateValue('kpi-completeness', summary.avg_field_completeness != null ? summary.avg_field_completeness + '%' : '—');

        // Load cache stats for entry count
        try {
            const cacheResp = await fetch('/admin/api/cache/stats');
            const cacheData = await cacheResp.json();
            animateValue('kpi-cache-entries', `${cacheData.active_entries}/${cacheData.total_entries}`);
        } catch { animateValue('kpi-cache-entries', '—'); }

        // Render chart from by_agent data
        renderEvalChart(summary.by_agent || []);

        // Load evaluation table
        let evalUrl = `/admin/api/evaluations?limit=50`;
        if (agentFilter) evalUrl += `&agent_name=${agentFilter}`;

        const evalsResp = await fetch(evalUrl);
        const evals = await evalsResp.json();

        const tbody = document.getElementById('eval-tbody');
        if (!evals.length) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:2rem">No evaluations found.</td></tr>';
            return;
        }

        tbody.innerHTML = evals.map(ev => `
            <tr>
                <td><strong>${escapeHtml(AGENT_LABELS[ev.agent_name] || ev.agent_name)}</strong></td>
                <td>${CACHE_STATUS_BADGES[ev.cache_status] || ev.cache_status}</td>
                <td>${boolBadge(ev.json_valid)}</td>
                <td>${boolBadge(ev.schema_compliant)}</td>
                <td>${ev.field_completeness_pct != null ? ev.field_completeness_pct.toFixed(1) + '%' : '—'}</td>
                <td>${ev.determinism_score != null ? ev.determinism_score.toFixed(1) + '%' : '—'}</td>
                <td>${boolBadge(ev.confidence_score_valid)}</td>
                <td>${ev.latency_ms ? (ev.latency_ms / 1000).toFixed(1) + 's' : '—'}</td>
                <td>${ev.created_at ? new Date(ev.created_at).toLocaleString() : '—'}</td>
            </tr>
        `).join('');
    } catch (err) {
        console.error('Response eval load error:', err);
    }
}

function renderEvalChart(byAgent) {
    const ctx = document.getElementById('chart-eval');
    if (!ctx) return;
    if (evalChart) evalChart.destroy();

    if (!byAgent.length) {
        evalChart = null;
        return;
    }

    const agents = byAgent.map(a => a.agent_name);
    const determinism = byAgent.map(a => a.avg_determinism || 0);
    const completeness = byAgent.map(a => a.avg_completeness || 0);
    const schema = byAgent.map(a => a.schema_compliance_rate || 0);

    evalChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: agents.map(a => AGENT_LABELS[a] || a),
            datasets: [
                {
                    label: 'Determinism %',
                    data: determinism,
                    backgroundColor: 'rgba(34, 197, 94, 0.7)',
                    borderRadius: 4,
                },
                {
                    label: 'Completeness %',
                    data: completeness,
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    borderRadius: 4,
                },
                {
                    label: 'Schema Compliance %',
                    data: schema,
                    backgroundColor: 'rgba(168, 85, 247, 0.7)',
                    borderRadius: 4,
                },
            ]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { labels: { color: '#475569', font: { family: "'Inter'" } } }
            },
            scales: {
                x: { ticks: { color: '#475569' }, grid: { display: false }, border: { display: false } },
                y: {
                    ticks: { color: '#94a3b8', callback: v => v + '%' },
                    grid: { color: 'rgba(37,99,235,0.06)' },
                    border: { display: false },
                    max: 100,
                }
            }
        }
    });
}

// Evaluation filter listeners
document.getElementById('eval-days')?.addEventListener('change', loadResponseEval);
document.getElementById('eval-agent-filter')?.addEventListener('change', loadResponseEval);
