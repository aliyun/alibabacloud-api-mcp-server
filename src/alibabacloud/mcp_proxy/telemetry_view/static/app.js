(function() {
'use strict';

// === Client Logos (SVG data URIs) ===
const CLIENT_LOGOS = {
    'claude-code': '<svg viewBox="0 0 125 125" fill="none"><path d="M54.375 118.75L56.125 111L58.125 101L59.75 93L61.25 83.125L62.125 79.875L62 79.625L61.375 79.75L53.875 90L42.5 105.375L33.5 114.875L31.375 115.75L27.625 113.875L28 110.375L30.125 107.375L42.5 91.5L50 81.625L54.875 76L54.75 75.25H54.5L21.5 96.75L15.625 97.5L13 95.125L13.375 91.25L14.625 90L24.5 83.125L49.125 69.375L49.5 68.125L49.125 67.5H47.875L43.75 67.25L29.75 66.875L17.625 66.375L5.75 65.75L2.75 65.125L0 61.375L0.25 59.5L2.75 57.875L6.375 58.125L14.25 58.75L26.125 59.5L34.75 60L47.5 61.375H49.5L49.75 60.5L49.125 60L48.625 59.5L36.25 51.25L23 42.5L16 37.375L12.25 34.75L10.375 32.375L9.625 27.125L13 23.375L17.625 23.75L18.75 24L23.375 27.625L33.25 35.25L46.25 44.875L48.125 46.375L49 45.875V45.5L48.125 44.125L41.125 31.375L33.625 18.375L30.25 13L29.375 9.75C29.0417 8.625 28.875 7.375 28.875 6L32.75 0.750006L34.875 0L40.125 0.750006L42.25 2.625L45.5 10L50.625 21.625L58.75 37.375L61.125 42.125L62.375 46.375L62.875 47.75H63.75V47L64.375 38L65.625 27.125L66.875 13.125L67.25 9.125L69.25 4.375L73.125 1.87501L76.125 3.25L78.625 6.875L78.25 9.125L76.875 18.75L73.875 33.875L72 44.125H73.125L74.375 42.75L79.5 36L88.125 25.25L91.875 21L96.375 16.25L99.25 14H104.625L108.5 19.875L106.75 26L101.25 33L96.625 38.875L90 47.75L86 54.875L86.375 55.375H87.25L102.125 52.125L110.25 50.75L119.75 49.125L124.125 51.125L124.625 53.125L122.875 57.375L112.625 59.875L100.625 62.25L82.75 66.5L82.5 66.625L82.75 67L90.75 67.75L94.25 68H102.75L118.5 69.125L122.625 71.875L125 75.125L124.625 77.75L118.25 80.875L109.75 78.875L89.75 74.125L83 72.5H82V73L87.75 78.625L98.125 88L111.25 100.125L111.875 103.125L110.25 105.625L108.5 105.375L97 96.625L92.5 92.75L82.5 84.375H81.875V85.25L84.125 88.625L96.375 107L97 112.625L96.125 114.375L92.875 115.5L89.5 114.875L82.25 104.875L74.875 93.5L68.875 83.375L68.25 83.875L64.625 121.625L63 123.5L59.25 125L56.125 122.625L54.375 118.75Z" fill="#D97757"/></svg>',
    'vscode': '<svg viewBox="0 0 24 24"><path d="M17.583 2.247l-5.375 4.94L6.792 3.06 2 5.12v13.76l4.792 2.06 5.416-4.127 5.375 4.94L22 19.693V4.307l-4.417-2.06zM6.792 15.5V8.5l4.208 3.5-4.208 3.5zm10.791 1.307L13.5 12l4.083-4.807v9.614z" fill="#007ACC"/></svg>',
    'copilot-cli': '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 3a3 3 0 110 6 3 3 0 010-6zm-5 11.5a7.5 7.5 0 0110 0" fill="none" stroke="#6e40c9" stroke-width="2"/></svg>',
    'codex': '<svg viewBox="0 0 486 486" fill="none"><path d="M186.576 177.497V131.422C186.576 127.541 188.02 124.63 191.383 122.693L283.194 69.3427C295.691 62.0679 310.593 58.6747 325.972 58.6747C383.651 58.6747 420.185 103.781 420.185 151.794C420.185 155.188 420.185 159.068 419.703 162.949L324.529 106.688C318.762 103.294 312.992 103.294 307.225 106.688L186.576 177.497ZM400.956 356.949V246.851C400.956 240.06 398.07 235.21 392.304 231.816L271.655 161.006L311.07 138.209C314.434 136.272 317.319 136.272 320.683 138.209L412.493 191.559C438.932 207.081 456.715 240.06 456.715 272.068C456.715 308.926 435.086 342.878 400.956 356.945V356.949ZM158.217 259.949L118.802 236.67C115.439 234.733 113.996 231.821 113.996 227.94V121.241C113.996 69.3477 153.41 30.0599 206.766 30.0599C226.957 30.0599 245.699 36.8515 261.565 48.9761L166.873 104.268C161.107 107.661 158.222 112.511 158.222 119.303V259.953L158.217 259.949ZM243.057 309.418L186.576 277.409V209.511L243.057 177.502L299.533 209.511V277.409L243.057 309.418ZM279.347 456.86C259.157 456.86 240.415 450.069 224.549 437.945L319.24 382.652C325.007 379.259 327.892 374.409 327.892 367.617V226.967L367.79 250.246C371.153 252.183 372.597 255.094 372.597 258.976V365.675C372.597 417.568 332.699 456.856 279.347 456.856V456.86ZM165.427 348.705L73.6158 295.356C47.1769 279.834 29.3943 246.856 29.3943 214.847C29.3943 177.502 51.5056 144.038 85.6311 129.971V240.551C85.6311 247.342 88.5173 252.192 94.2835 255.587L214.454 325.909L175.039 348.705C171.676 350.643 168.79 350.643 165.427 348.705ZM160.142 428.245C105.826 428.245 65.9292 387.02 65.9292 336.095C65.9292 332.214 66.411 328.334 66.8889 324.453L161.581 379.745C167.347 383.139 173.118 383.139 178.885 379.745L299.533 309.423V355.498C299.533 359.379 298.09 362.29 294.726 364.227L202.916 417.577C190.418 424.852 175.517 428.245 160.137 428.245H160.142ZM279.347 485.958C337.509 485.958 386.054 444.249 397.114 388.958C450.949 374.891 485.557 323.966 485.557 272.073C485.557 238.121 471.139 205.144 445.181 181.378C447.585 171.192 449.027 161.006 449.027 150.825C449.027 81.4712 393.268 29.5727 328.857 29.5727C315.882 29.5727 303.384 31.5104 290.886 35.8781C269.252 14.5371 239.45 0.958008 206.766 0.958008C148.605 0.958008 100.06 42.6656 89.0001 97.9574C35.1656 112.024 0.557129 162.949 0.557129 214.842C0.557129 248.794 14.9757 281.771 40.9328 305.537C38.5295 315.723 37.087 325.909 37.087 336.091C37.087 405.445 92.846 457.342 157.256 457.342C170.232 457.342 182.731 455.405 195.229 451.037C216.857 472.378 246.659 485.958 279.347 485.958Z" fill="#10a37f"/></svg>',
    'qoderwork': '<img src="https://img.alicdn.com/imgextra/i2/O1CN01js79rH1mt5nkV0kEl_!!6000000005011-55-tps-640-180.svg" alt="Qoderwork" style="width:100%;height:100%;object-fit:contain"/>',
};

// === State ===
let currentPage = 1;
let currentFilters = { client: '', q: '', start_time: '', end_time: '' };
let inflightController = null;
const FETCH_TIMEOUT_MS = 10000;

function cancelInflight() {
    if (inflightController) {
        try { inflightController.abort(); } catch (_) {}
        inflightController = null;
    }
}

function newController() {
    cancelInflight();
    inflightController = new AbortController();
    const c = inflightController;
    setTimeout(() => { try { c.abort(); } catch (_) {} }, FETCH_TIMEOUT_MS);
    return c;
}

// === Theme ===
function initTheme() {
    const saved = localStorage.getItem('telemetry-theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved === 'dark' ? 'dark' : '');
    document.getElementById('theme-toggle').addEventListener('click', toggleTheme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? '' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('telemetry-theme', next || 'light');
}

// === Router ===
function route() {
    const hash = window.location.hash || '#/';
    const app = document.getElementById('app');

    if (hash.startsWith('#/trace/')) {
        const parts = hash.slice(8).split('/');
        const client = decodeURIComponent(parts[0]);
        const sessionId = parts.slice(1).join('/');
        renderTraceDetail(app, client, sessionId);
    } else {
        renderSessionList(app);
    }
}

// === Session List ===
async function renderSessionList(container) {
    const isEmpty = !container.firstElementChild || container.querySelector('.loading');
    if (isEmpty) container.innerHTML = '<div class="loading">Loading sessions...</div>';

    const params = new URLSearchParams({
        page: currentPage,
        page_size: 20,
        ...Object.fromEntries(Object.entries(currentFilters).filter(([_, v]) => v))
    });

    const ctrl = newController();
    try {
        const resp = await fetch('/api/sessions?' + params, { signal: ctrl.signal });
        const data = await resp.json();
        container.innerHTML = buildSessionListHTML(data);
        bindSessionListEvents(container);
    } catch (err) {
        if (err.name === 'AbortError') return;
        container.innerHTML = '<div class="loading">Error loading sessions: ' + escapeHtml(err.message) + '</div>';
    } finally {
        if (inflightController === ctrl) inflightController = null;
    }
}

function buildSessionListHTML(data) {
    const stats = data.stats || {};
    const clientCounts = stats.client_counts || {};
    const clientTags = Object.entries(clientCounts)
        .map(([c, n]) => `<span class="stat-tag">${escapeHtml(c)}: ${n}</span>`)
        .join('');

    let html = `
        <div class="stats-bar">
            <span class="stat-item"><strong>${stats.total_sessions || 0}</strong> sessions</span>
            <span class="stat-divider"></span>
            ${clientTags}
            <span class="stat-divider"></span>
            <span class="stat-item">Success rate: <strong>${stats.success_rate || 0}%</strong></span>
        </div>
        <div class="filter-bar">
            <select id="filter-client">
                <option value="">All Clients</option>
                <option value="claude-code">Claude Code</option>
                <option value="vscode">VS Code</option>
                <option value="copilot-cli">Copilot CLI</option>
                <option value="codex">Codex</option>
                <option value="qoderwork">Qoderwork</option>
            </select>
            <input type="text" id="filter-search" placeholder="Search prompts, tools..." value="${escapeHtml(currentFilters.q)}">
            <input type="datetime-local" id="filter-start" title="Start time">
            <input type="datetime-local" id="filter-end" title="End time">
        </div>
        <div class="session-list">
    `;

    if (data.sessions.length === 0) {
        html += '<div class="loading">No sessions found</div>';
    }

    for (const session of data.sessions) {
        const logo = CLIENT_LOGOS[session.client] || CLIENT_LOGOS['qoderwork'];
        const startLocal = formatTime(session.start_time);
        const lastLocal = formatTime(session.last_activity);
        const errorBadge = session.has_errors ? '<span class="error-badge">errors</span>' : '';

        html += `
            <div class="session-card" data-client="${escapeHtml(session.client)}" data-session="${escapeHtml(session.session_id)}">
                <div class="client-logo">${logo}</div>
                <div class="card-body">
                    <div class="card-title">
                        ${escapeHtml(session.client)}
                        <span style="color:var(--text-tertiary);font-weight:400;font-size:12px">${escapeHtml(session.session_id.slice(0, 8))}...</span>
                        ${errorBadge}
                    </div>
                    <div class="card-subtitle">Started: ${startLocal} &nbsp;|&nbsp; Last: ${lastLocal} &nbsp;|&nbsp; ${session.span_count} spans, ${session.turn_count} turns</div>
                    <div class="card-preview">${escapeHtml(session.first_prompt_preview)}</div>
                </div>
            </div>
        `;
    }

    html += '</div>';
    html += buildPaginationHTML(data.total, data.page, data.page_size);
    return html;
}

function buildPaginationHTML(total, page, pageSize) {
    const totalPages = Math.ceil(total / pageSize);
    if (totalPages <= 1) return '';

    let html = '<div class="pagination">';
    html += `<button ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">&lt; Prev</button>`;

    for (let i = 1; i <= Math.min(totalPages, 7); i++) {
        html += `<button class="${i === page ? 'active' : ''}" data-page="${i}">${i}</button>`;
    }

    html += `<button ${page >= totalPages ? 'disabled' : ''} data-page="${page + 1}">Next &gt;</button>`;
    html += '</div>';
    return html;
}

function bindSessionListEvents(container) {
    container.querySelectorAll('.session-card').forEach(card => {
        card.addEventListener('click', () => {
            const client = card.dataset.client;
            const session = card.dataset.session;
            window.location.hash = '#/trace/' + encodeURIComponent(client) + '/' + session;
        });
    });

    const clientSelect = container.querySelector('#filter-client');
    const searchInput = container.querySelector('#filter-search');
    const startInput = container.querySelector('#filter-start');
    const endInput = container.querySelector('#filter-end');

    if (clientSelect) {
        clientSelect.value = currentFilters.client;
        clientSelect.addEventListener('change', () => {
            currentFilters.client = clientSelect.value;
            currentPage = 1;
            renderSessionList(container);
        });
    }

    let searchTimeout;
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                currentFilters.q = searchInput.value;
                currentPage = 1;
                renderSessionList(container);
            }, 300);
        });
    }

    if (startInput) {
        startInput.addEventListener('change', () => {
            currentFilters.start_time = startInput.value ? new Date(startInput.value).toISOString() : '';
            currentPage = 1;
            renderSessionList(container);
        });
    }

    if (endInput) {
        endInput.addEventListener('change', () => {
            currentFilters.end_time = endInput.value ? new Date(endInput.value).toISOString() : '';
            currentPage = 1;
            renderSessionList(container);
        });
    }

    container.querySelectorAll('.pagination button').forEach(btn => {
        btn.addEventListener('click', () => {
            const page = parseInt(btn.dataset.page);
            if (page && !btn.disabled) {
                currentPage = page;
                renderSessionList(container);
            }
        });
    });
}

// === Trace Detail ===
async function renderTraceDetail(container, client, sessionId) {
    const sameSession = container.dataset.tracePath === client + '/' + sessionId;
    if (!sameSession) container.innerHTML = '<div class="loading">Loading trace...</div>';
    container.dataset.tracePath = client + '/' + sessionId;

    const ctrl = newController();
    try {
        const resp = await fetch(
            `/api/sessions/${encodeURIComponent(client)}/${encodeURIComponent(sessionId)}`,
            { signal: ctrl.signal }
        );
        if (!resp.ok) {
            container.innerHTML = '<div class="loading">Session not found</div>';
            return;
        }
        const data = await resp.json();
        container.innerHTML = buildTraceDetailHTML(data);
        bindTraceDetailEvents(container, data);
    } catch (err) {
        if (err.name === 'AbortError') return;
        if (!sameSession) {
            container.innerHTML = '<div class="loading">Error: ' + escapeHtml(err.message) + '</div>';
        }
    } finally {
        if (inflightController === ctrl) inflightController = null;
    }
}

// === Risk Classification ===
function classifyRisk(span) {
    if (span.event !== 'tool') return null;
    // help commands are always low risk regardless of the action verb
    if (span.tool_input && span.tool_input.command && /\bhelp\b/i.test(span.tool_input.command)) return 'low';
    // Only extract the ACTION verb, not the full parameter values
    let actionName = '';
    if (span.cloud_api && span.cloud_api.action) {
        actionName = span.cloud_api.action.toLowerCase();
    } else if (span.tool_input && span.tool_input.command) {
        const cmd = span.tool_input.command.trim();
        // IaC service: classify by specific subcommand
        const iacM = cmd.match(/\baliyun\s+iacservice\s+([\w-]+)/);
        if (iacM) {
            const iacAction = iacM[1].toLowerCase();
            if (/apply|execute-terraform-apply/i.test(iacAction)) return 'high';
            if (/execute-terraform-plan|plan/i.test(iacAction)) return 'medium';
            return 'low';
        }
        const m = cmd.match(/\baliyun\s+[\w-]+\s+([\w-]+)/);
        if (m) actionName = m[1].toLowerCase();
        else actionName = cmd.split(/\s+/).slice(0, 3).join(' ').toLowerCase();
    } else if (span.tool_name) {
        actionName = span.tool_name.toLowerCase();
    }
    if (/\b(update|modify|put|post|add|delete|remove|run|start|stop|reboot|create)/i.test(actionName)) return 'high';
    if (/\b(allocate|attach|assign)/i.test(actionName)) return 'medium';
    if (/\b(search|list|get|describe|read|find|call|version|configure|help|query)/i.test(actionName)) return 'low';
    // Any alibabacloud MCP or aliyun bash call defaults to low if no keyword matched
    const isAli = (span.tool_name && span.tool_name.includes('alibabacloud'))
        || (span.tool_input && span.tool_input.command && /\baliyun\b/.test(span.tool_input.command))
        || (span.cloud_api && (span.cloud_api.service || span.cloud_api.action));
    if (isAli) return 'low';
    return null;
}

function getRiskBadgeClass(level) {
    if (level === 'high') return 'risk-badge risk-badge-high';
    if (level === 'medium') return 'risk-badge risk-badge-medium';
    if (level === 'low') return 'risk-badge risk-badge-low';
    return '';
}

function getToolDisplayName(span) {
    if (span.cloud_api && (span.cloud_api.service || span.cloud_api.action)) {
        return `aliyun ${span.cloud_api.service || '?'} ${span.cloud_api.action || '?'}`;
    }
    if (span.tool_name === 'Bash' && span.tool_input && span.tool_input.command) {
        const cmd = span.tool_input.command.replace(/\s*2>&1\s*/g, '').trim();
        const m = cmd.match(/\baliyun\s+[\w-]+(?:\s+[\w-]+)?/);
        if (m) return m[0];
        return cmd.slice(0, 60);
    }
    if (span.tool_name && span.tool_name.includes('___')) {
        const parts = span.tool_name.split('___');
        return parts.length >= 2 ? `mcp ${parts[parts.length - 1]}` : span.tool_name;
    }
    return span.tool_name || 'unknown';
}

function buildSessionSummaryHTML(data) {
    const flatSpans = flattenTree(data.spans);
    const st = data.stats || {};

    // Duration
    const startTs = data.start_time ? new Date(data.start_time).getTime() : 0;
    const endTs = data.last_activity ? new Date(data.last_activity).getTime() : 0;
    const durationMs = endTs - startTs;
    const durationStr = durationMs > 0 ? formatDuration(durationMs) : '-';

    // Alibaba Cloud CLI/API calls
    let aliCalls = 0, aliSuccess = 0, aliFail = 0;
    const highRiskOps = [], medRiskOps = [], lowRiskOps = [];

    for (const span of flatSpans) {
        if (span.event !== 'tool') continue;
        const isAliTool = (span.tool_name && span.tool_name.includes('alibabacloud'))
            || (span.tool_input && span.tool_input.command && /\baliyun\b/.test(span.tool_input.command))
            || (span.cloud_api && (span.cloud_api.service || span.cloud_api.action));
        if (isAliTool) {
            aliCalls++;
            if (span.status === 'success') aliSuccess++;
            else if (span.status === 'failure') aliFail++;
        }

        const risk = classifyRisk(span);
        if (!risk) continue;
        const displayName = getToolDisplayName(span);
        const entry = { name: displayName, spanId: span.span_id };
        if (risk === 'high') highRiskOps.push(entry);
        else if (risk === 'medium') medRiskOps.push(entry);
        else if (risk === 'low') lowRiskOps.push(entry);
    }

    // Skills list
    const skillEntries = [];
    for (const span of flatSpans) {
        if (span.event === 'skill_invocation') {
            const name = span.skill_name || span.skill_tag || 'unknown';
            skillEntries.push({ name, spanId: span.span_id });
        }
    }

    const skillListItems = skillEntries.map(s => `<li class="summary-link" data-span-id="${escapeHtml(s.spanId)}">${escapeHtml(s.name)}</li>`).join('');
    const highListItems = highRiskOps.map(s => `<li class="summary-link" data-span-id="${escapeHtml(s.spanId)}">${escapeHtml(s.name)}</li>`).join('');
    const medListItems = medRiskOps.map(s => `<li class="summary-link" data-span-id="${escapeHtml(s.spanId)}">${escapeHtml(s.name)}</li>`).join('');
    const lowListItems = lowRiskOps.map(s => `<li class="summary-link" data-span-id="${escapeHtml(s.spanId)}">${escapeHtml(s.name)}</li>`).join('');

    return `
        <div class="summary-section">
            <div class="summary-section-title">Summary</div>
            <div class="summary-item">总共 <strong>${st.turns || 0}</strong> 轮对话、耗时 <strong>${durationStr}</strong></div>
        </div>
        <div class="summary-section">
            <div class="summary-section-title">使用摘要</div>
            <div class="summary-item">阿里云 CLI/API 调用 <strong>${aliSuccess}/${aliCalls}</strong> 成功${aliFail > 0 ? `，<span style="color:var(--span-error)">${aliFail} 失败</span>` : ''}</div>
            <div class="summary-item">使用了 <strong>${skillEntries.length}</strong> 个 SKILL：
                ${skillEntries.length > 0 ? `<button class="skill-expand-btn" data-target="skill-list-detail">&#9660;</button>` : ''}
            </div>
            ${skillEntries.length > 0 ? `<ul class="summary-list" id="skill-list-detail" style="display:none">${skillListItems}</ul>` : ''}
        </div>
        <div class="summary-section">
            <div class="summary-section-title">风险摘要</div>
            <div class="summary-item" title="update / put / post / add 相关">
                <span class="risk-badge risk-badge-high">高危</span> 操作 <strong>${highRiskOps.length}</strong> 次
                ${highRiskOps.length > 0 ? `<button class="skill-expand-btn" data-target="risk-high-list">&#9660;</button>` : ''}
            </div>
            ${highRiskOps.length > 0 ? `<ul class="summary-list" id="risk-high-list" style="display:none">${highListItems}</ul>` : ''}
            <div class="summary-item" title="create 相关">
                <span class="risk-badge risk-badge-medium">中危</span> 操作 <strong>${medRiskOps.length}</strong> 次
                ${medRiskOps.length > 0 ? `<button class="skill-expand-btn" data-target="risk-med-list">&#9660;</button>` : ''}
            </div>
            ${medRiskOps.length > 0 ? `<ul class="summary-list" id="risk-med-list" style="display:none">${medListItems}</ul>` : ''}
            <div class="summary-item" title="search / list / get / describe 相关">
                <span class="risk-badge risk-badge-low">低危</span> 操作 <strong>${lowRiskOps.length}</strong> 次
                ${lowRiskOps.length > 0 ? `<button class="skill-expand-btn" data-target="risk-low-list">&#9660;</button>` : ''}
            </div>
            ${lowRiskOps.length > 0 ? `<ul class="summary-list" id="risk-low-list" style="display:none">${lowListItems}</ul>` : ''}
        </div>
    `;
}

function buildTraceDetailHTML(data) {
    const logo = CLIENT_LOGOS[data.client] || CLIENT_LOGOS['qoderwork'];
    const flatSpans = flattenTree(data.spans);
    const timeRange = getTimeRange(flatSpans);
    const st = data.stats || {};
    const tokensInfo = data.tokens || { session_total: { grand_total: 0 }, turns: [] };
    // Token map for fast span-detail lookups: span_id → {kind, tokens, ...}
    window.__tokenIndex = buildTokenIndex(tokensInfo);
    // Agent client name, used by capability-aware token rendering to hide
    // fields that don't apply to this provider (e.g. reasoning on Claude,
    // input_creation on Codex).
    window.__tokenClient = data.client || '';

    let html = `
        <div class="trace-header">
            <button class="back-btn" onclick="window.location.hash='#/'">&larr; Back</button>
            <span style="display:inline-flex;align-items:center;gap:8px">
                <span style="width:24px;height:24px">${logo}</span>
                <strong>${escapeHtml(data.client)}</strong>
                <span style="color:var(--text-secondary);font-size:13px">${escapeHtml(data.session_id)}</span>
            </span>
        </div>
        <div class="stats-bar">
            <span class="stat-item" style="font-weight:600;color:var(--accent)">Summary</span>
            <span class="stat-divider"></span>
            <span class="stat-item"><strong>${st.turns || 0}</strong> turns</span>
            <span class="stat-divider"></span>
            <span class="stat-item"><strong>${st.tools || 0}</strong> tools</span>
            <span class="stat-divider"></span>
            <span class="stat-item"><strong>${st.skills || 0}</strong> skills</span>
            <span class="stat-divider"></span>
            <span class="stat-item"><strong>${st.prompts || 0}</strong> prompts</span>
            <span class="stat-divider"></span>
            <span class="stat-item success">${st.success || 0} success</span>
            <span class="stat-item failure">${st.failure || 0} fail</span>
            <span class="stat-divider"></span>
            <span class="stat-item">Rate: <strong>${st.success_rate || 0}%</strong></span>
            <button class="summary-toggle-btn" id="summary-toggle-btn">
                <span class="toggle-arrow">&#9660;</span>
            </button>
        </div>
        <div class="session-summary" id="session-summary" style="display:none">
            ${buildSessionSummaryHTML(data)}
        </div>
        <div class="trace-layout">
            <div class="trace-tree" id="trace-tree">
                ${buildTreeHTML(data.spans, 0)}
            </div>
            <div class="trace-right-panel">
                <div class="view-toggle">
                    <button class="view-toggle-btn active" data-view="timeline">Timeline</button>
                    <button class="view-toggle-btn" data-view="graph">Graph</button>
                    <button class="view-toggle-btn fullscreen-btn" id="graph-fullscreen-btn" title="Fullscreen" style="margin-left:auto;display:none">&#x26F6;</button>
                </div>
                <div class="trace-timeline" id="trace-timeline">
                    <div class="timeline-scale">${buildTimeScale(timeRange)}</div>
                    ${buildTimelineHTML(flatSpans, timeRange)}
                </div>
                <div class="trace-graph" id="trace-graph" style="display:none">
                    ${buildGraphHTML(data.spans)}
                    <div class="graph-tooltip" id="graph-tooltip" style="display:none"></div>
                </div>
            </div>
        </div>
        <div class="detail-panel" id="detail-panel" style="display:none">
            <div class="detail-panel-header">
                <span id="detail-title">Span Detail</span>
            </div>
            <div class="detail-panel-body" id="detail-body"></div>
        </div>
    `;
    return html;
}

function buildTreeHTML(spans, depth, opts) {
    const flat = !!(opts && opts.flat);
    let html = '';
    const tokenIdx = window.__tokenIndex || {};
    for (const span of spans) {
        const hasChildren = !flat && span.children && span.children.length > 0;
        const indent = depth * 20;
        const icon = getSpanIcon(span);
        const label = getSpanLabel(span);
        const duration = span.duration_ms != null ? formatDuration(span.duration_ms) : '';
        const statusClass = span.status === 'failure' ? 'failure' : (span.status === 'success' ? 'success' : '');
        const tokEntry = tokenIdx[span.span_id];
        let tokenChip = '';
        // Token chips: only on llm_call rows (per-call cost) and prompt rows
        // (turn total). Tool/skill rows show no token count — tokens are an
        // LLM-level fact, not a tool-level one.
        if (tokEntry && tokEntry.tokens && tokEntry.tokens.grand_total > 0
            && (tokEntry.kind === 'llm_call' || tokEntry.kind === 'turn')) {
            const n = tokEntry.tokens.grand_total;
            let tip;
            if (tokEntry.kind === 'turn') {
                tip = 'Turn total tokens';
            } else {
                const inline = formatNormalizedTokensInline(tokEntry.tokens);
                tip = `LLM call${tokEntry.call_index != null ? ' #' + tokEntry.call_index : ''}`
                    + (tokEntry.model ? ' (' + tokEntry.model + ')' : '')
                    + (inline ? ' — ' + inline : '');
            }
            tokenChip = `<span class="span-duration" title="${escapeHtml(tip)}" style="color:var(--accent)">${formatTokenCount(n)}</span>`;
        }

        // Skill-tag chip on tool rows: surfaces 100%-confident skill
        // attribution (UA env or SKILL.md path) without changing the row's
        // native icon/label. Suppressed on skill_invocation rows since their
        // label already names the skill.
        let skillTagChip = '';
        if (span.event === 'tool' && span.skill_tag) {
            const shortName = span.skill_tag.includes(':')
                ? span.skill_tag.split(':').pop()
                : span.skill_tag;
            skillTagChip = `<span class="span-skill-tag" title="Attributed to skill ${escapeHtml(span.skill_tag)}" style="background:var(--bg-skill,#fff7e6);color:var(--span-skill,#b96b00);padding:1px 6px;border-radius:3px;font-size:11px;margin-left:6px">&#9889; ${escapeHtml(shortName)}</span>`;
        }
        // Risk badge for tool spans
        let riskChip = '';
        if (span.event === 'tool') {
            const riskLevel = classifyRisk(span);
            if (riskLevel) {
                const riskCls = getRiskBadgeClass(riskLevel);
                const riskTxt = riskLevel === 'high' ? '高危' : (riskLevel === 'medium' ? '中危' : '低危');
                riskChip = `<span class="${riskCls}">${riskTxt}</span>`;
            }
        }
        html += `
            <div class="span-item" data-span-id="${escapeHtml(span.span_id)}" style="padding-left:${12 + indent}px">
                <span class="expand-btn">${hasChildren ? '&#9660;' : '&nbsp;'}</span>
                <span class="span-icon" style="color:${getSpanColor(span)}">${icon}</span>
                <span class="span-label">${escapeHtml(label)}</span>
                ${skillTagChip}
                ${statusClass ? `<span class="span-status-badge ${statusClass}">${span.status}</span>` : ''}
                ${riskChip}
                ${tokenChip}
                ${duration ? `<span class="span-duration">${duration}</span>` : ''}
            </div>
        `;
        // Tree → flat handoff: when entering a prompt subtree we collect ALL
        // descendants, sort by start_timestamp, and render them at one level.
        // Children outside a turn (top-level siblings) keep the standard
        // recursive tree shape.
        if (hasChildren) {
            const flatten = span.event === 'prompt';
            const kids = flatten ? _collectFlatDescendants(span.children) : span.children;
            html += `<div class="span-children" data-parent="${escapeHtml(span.span_id)}">`;
            html += buildTreeHTML(kids, depth + 1, { flat: flatten });
            html += '</div>';
        }
    }
    return html;
}

function _collectFlatDescendants(nodes) {
    const out = [];
    function walk(n) {
        out.push(n);
        for (const c of n.children || []) walk(c);
    }
    for (const n of nodes) walk(n);
    out.sort((a, b) => String(a.start_timestamp || '').localeCompare(String(b.start_timestamp || '')));
    return out;
}

function buildTimelineHTML(flatSpans, timeRange) {
    if (!timeRange.duration) return '';
    let html = '';
    for (const span of flatSpans) {
        const start = parseTimestamp(span.start_timestamp);
        const end = parseTimestamp(span.end_timestamp);
        const left = ((start - timeRange.start) / timeRange.duration) * 100;
        const width = Math.max(((end - start) / timeRange.duration) * 100, 0.5);
        const eventClass = span.status === 'failure' ? 'status-failure' : 'event-' + span.event;

        html += `
            <div class="timeline-row">
                <div class="timeline-bar ${eventClass}" data-span-id="${escapeHtml(span.span_id)}"
                     style="left:${left}%;width:${width}%"
                     title="${escapeHtml(getSpanLabel(span))} (${formatDuration(span.duration_ms)})"></div>
            </div>
        `;
    }
    return html;
}

function buildTimeScale(timeRange) {
    if (!timeRange.duration) return '';
    const totalSec = timeRange.duration / 1000;
    const marks = 5;
    let scale = '';
    for (let i = 0; i <= marks; i++) {
        const sec = (totalSec * i / marks).toFixed(1);
        scale += sec + 's' + (i < marks ? '  |  ' : '');
    }
    return scale;
}

// === Graph View ===
function buildGraphHTML(spans) {
    const turns = groupByTurn(spans);
    const nodeW = 160, nodeH = 32, padX = 20, padY = 16, turnPadTop = 36, turnPadBot = 16;
    const turnGap = 24, arrowGap = 12;
    let totalHeight = 0;
    const turnLayouts = [];

    for (const turn of turns) {
        const innerH = turn.spans.length * (nodeH + padY) - padY;
        const boxH = turnPadTop + innerH + turnPadBot;
        turnLayouts.push({ turn, y: totalHeight, boxH, spans: turn.spans });
        totalHeight += boxH + turnGap;
    }

    const svgW = nodeW + padX * 2 + 40;
    const svgH = Math.max(totalHeight, 200);

    let svg = `<svg class="graph-svg" viewBox="0 0 ${svgW} ${svgH}" width="${svgW}" height="${svgH}">`;
    svg += '<defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="var(--text-tertiary)"/></marker></defs>';

    const allNodes = [];

    for (let ti = 0; ti < turnLayouts.length; ti++) {
        const tl = turnLayouts[ti];
        const boxX = 10, boxW = svgW - 20;
        svg += `<rect x="${boxX}" y="${tl.y}" width="${boxW}" height="${tl.boxH}" rx="6" fill="none" stroke="var(--border)" stroke-dasharray="4 3" stroke-width="1.5"/>`;
        svg += `<text x="${boxX + 8}" y="${tl.y + 14}" font-size="10" fill="var(--text-tertiary)" font-family="var(--font)">Turn ${tl.turn.turn}</text>`;

        for (let si = 0; si < tl.spans.length; si++) {
            const span = tl.spans[si];
            const nx = padX + 10;
            const ny = tl.y + turnPadTop + si * (nodeH + padY);
            const color = getSpanColor(span);
            const label = getSpanLabel(span).slice(0, 22);
            const statusBorder = span.status === 'failure' ? 'var(--span-error)' : color;

            svg += `<rect class="graph-node" data-span-id="${escapeHtml(span.span_id)}" x="${nx}" y="${ny}" width="${nodeW}" height="${nodeH}" rx="4" fill="var(--bg-primary)" stroke="${statusBorder}" stroke-width="1.5" style="cursor:pointer"/>`;
            svg += `<text x="${nx + 8}" y="${ny + 20}" font-size="11" fill="var(--text-primary)" font-family="var(--font)" pointer-events="none">${escapeHtml(label)}</text>`;

            allNodes.push({ span, cx: nx + nodeW / 2, cy: ny + nodeH / 2, top: ny, bot: ny + nodeH });

            if (si > 0) {
                const prevBot = ny - padY;
                const curTop = ny;
                svg += `<line x1="${nx + nodeW / 2}" y1="${prevBot}" x2="${nx + nodeW / 2}" y2="${curTop}" stroke="var(--text-tertiary)" stroke-width="1" marker-end="url(#arrowhead)"/>`;
            }
        }

        if (ti > 0) {
            const prevTl = turnLayouts[ti - 1];
            const prevBotY = prevTl.y + prevTl.boxH;
            const curTopY = tl.y;
            const midX = svgW / 2;
            svg += `<line x1="${midX}" y1="${prevBotY}" x2="${midX}" y2="${curTopY}" stroke="var(--text-tertiary)" stroke-width="1.5" stroke-dasharray="3 2" marker-end="url(#arrowhead)"/>`;
        }
    }

    svg += '</svg>';
    return svg;
}

function groupByTurn(spans) {
    const turnMap = {};
    const flatSpans = flattenTree(spans);
    for (const span of flatSpans) {
        const turn = span.turn != null ? span.turn : 0;
        if (!turnMap[turn]) turnMap[turn] = { turn, spans: [] };
        turnMap[turn].spans.push(span);
    }
    const turns = Object.values(turnMap);
    turns.sort((a, b) => a.turn - b.turn);
    for (const t of turns) {
        t.spans.sort((a, b) => (a.start_timestamp || '').localeCompare(b.start_timestamp || ''));
    }
    return turns;
}

function initGraphPanZoom(container) {
    const graphEl = container.querySelector('#trace-graph');
    if (!graphEl) return;
    const svg = graphEl.querySelector('.graph-svg');
    if (!svg) return;

    let scale = 1, panX = 0, panY = 0, dragging = false, startX = 0, startY = 0;

    function applyTransform() {
        svg.style.transform = `translate(${panX}px, ${panY}px) scale(${scale})`;
    }

    function centerGraph() {
        const containerW = graphEl.clientWidth;
        const containerH = graphEl.clientHeight;
        const svgW = svg.viewBox.baseVal.width;
        const svgH = svg.viewBox.baseVal.height;
        scale = Math.min(containerW / svgW, containerH / svgH, 1) * 0.9;
        panX = (containerW - svgW * scale) / 2;
        panY = (containerH - svgH * scale) / 2;
        applyTransform();
    }

    // Center when graph becomes visible
    const observer = new MutationObserver(() => {
        if (graphEl.offsetParent !== null && graphEl.style.display !== 'none') {
            setTimeout(centerGraph, 50);
        }
    });
    observer.observe(graphEl, { attributes: true, attributeFilter: ['style'] });

    graphEl.addEventListener('wheel', (e) => {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        scale = Math.min(Math.max(scale * delta, 0.3), 3);
        applyTransform();
    }, { passive: false });

    graphEl.addEventListener('mousedown', (e) => {
        if (e.target.classList.contains('graph-node')) return;
        dragging = true;
        startX = e.clientX - panX;
        startY = e.clientY - panY;
        graphEl.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        panX = e.clientX - startX;
        panY = e.clientY - startY;
        applyTransform();
    });

    window.addEventListener('mouseup', () => {
        dragging = false;
        graphEl.style.cursor = 'grab';
    });

    // Fullscreen
    const fsBtn = container.querySelector('#graph-fullscreen-btn');
    if (fsBtn) {
        fsBtn.addEventListener('click', () => {
            if (document.fullscreenElement) {
                document.exitFullscreen();
            } else {
                graphEl.requestFullscreen().then(() => {
                    setTimeout(centerGraph, 100);
                });
            }
        });
        graphEl.addEventListener('fullscreenchange', () => {
            if (!document.fullscreenElement) {
                setTimeout(centerGraph, 100);
            }
        });
    }
}

function bindTraceDetailEvents(container, data) {
    window.__lastTraceData = data;
    // Summary toggle
    const summaryBtn = container.querySelector('#summary-toggle-btn');
    const summaryPanel = container.querySelector('#session-summary');
    if (summaryBtn && summaryPanel) {
        summaryBtn.addEventListener('click', () => {
            const hidden = summaryPanel.style.display === 'none';
            summaryPanel.style.display = hidden ? '' : 'none';
            summaryBtn.classList.toggle('expanded', hidden);
        });
    }
    // Skill list expand
    container.querySelectorAll('.skill-expand-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const target = container.querySelector('#' + btn.dataset.target);
            if (target) {
                const hidden = target.style.display === 'none';
                target.style.display = hidden ? '' : 'none';
                btn.innerHTML = hidden ? '&#9650;' : '&#9660;';
            }
        });
    });
    // Summary list item click → scroll to span in trace tree
    container.querySelectorAll('.summary-link').forEach(li => {
        li.addEventListener('click', () => {
            const spanId = li.dataset.spanId;
            if (!spanId) return;
            const treeItem = container.querySelector(`.span-item[data-span-id="${CSS.escape(spanId)}"]`);
            if (treeItem) {
                container.querySelectorAll('.span-item.selected').forEach(s => s.classList.remove('selected'));
                treeItem.classList.add('selected');
                treeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // Also expand parent if collapsed
                let parent = treeItem.parentElement;
                while (parent) {
                    if (parent.classList && parent.classList.contains('span-children') && parent.style.display === 'none') {
                        parent.style.display = '';
                        const parentId = parent.dataset.parent;
                        const expandBtn = container.querySelector(`.span-item[data-span-id="${parentId}"] .expand-btn`);
                        if (expandBtn) expandBtn.innerHTML = '&#9660;';
                    }
                    parent = parent.parentElement;
                }
                // Show detail panel
                const flatSpans = flattenTree(window.__lastTraceData ? window.__lastTraceData.spans : []);
                const span = flatSpans.find(s => s.span_id === spanId);
                if (span) showSpanDetail(container, span);
            }
        });
    });

    const flatSpans = flattenTree(data.spans);
    const spanMap = {};
    for (const s of flatSpans) spanMap[s.span_id] = s;

    function selectSpan(spanId, clickEvent) {
        if (!spanId || !spanMap[spanId]) return;
        container.querySelectorAll('.span-item.selected').forEach(s => s.classList.remove('selected'));
        container.querySelectorAll('.graph-node.selected').forEach(s => s.classList.remove('selected'));
        const treeItem = container.querySelector(`.span-item[data-span-id="${spanId}"]`);
        if (treeItem) {
            treeItem.classList.add('selected');
            treeItem.scrollIntoView({ block: 'nearest' });
        }
        const graphNode = container.querySelector(`.graph-node[data-span-id="${spanId}"]`);
        if (graphNode) graphNode.classList.add('selected');
        showSpanDetail(container, spanMap[spanId]);

        if (document.fullscreenElement) {
            showGraphTooltip(container, spanMap[spanId], clickEvent);
        }
    }

    container.querySelectorAll('.span-item, .timeline-bar, .graph-node').forEach(el => {
        el.addEventListener('click', (e) => {
            e.stopPropagation();
            selectSpan(el.dataset.spanId, e);
        });
    });

    // Close tooltip on background click in fullscreen
    const graphEl = container.querySelector('#trace-graph');
    if (graphEl) {
        graphEl.addEventListener('click', (e) => {
            if (!e.target.classList.contains('graph-node') && !e.target.closest('.graph-tooltip')) {
                const tooltip = container.querySelector('#graph-tooltip');
                if (tooltip) tooltip.style.display = 'none';
            }
        });
    }

    container.querySelectorAll('.span-item .expand-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const item = btn.closest('.span-item');
            const spanId = item.dataset.spanId;
            const children = container.querySelector(`.span-children[data-parent="${spanId}"]`);
            if (children) {
                const hidden = children.style.display === 'none';
                children.style.display = hidden ? '' : 'none';
                btn.innerHTML = hidden ? '&#9660;' : '&#9654;';
            }
        });
    });

    // View toggle
    const fsBtn = container.querySelector('#graph-fullscreen-btn');
    container.querySelectorAll('.view-toggle-btn[data-view]').forEach(btn => {
        btn.addEventListener('click', () => {
            container.querySelectorAll('.view-toggle-btn[data-view]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const view = btn.dataset.view;
            const timeline = container.querySelector('#trace-timeline');
            const graph = container.querySelector('#trace-graph');
            if (view === 'graph') {
                timeline.style.display = 'none';
                graph.style.display = '';
                if (fsBtn) fsBtn.style.display = '';
            } else {
                timeline.style.display = '';
                graph.style.display = 'none';
                if (fsBtn) fsBtn.style.display = 'none';
            }
        });
    });

    initGraphPanZoom(container);
}

function showSpanDetail(container, span) {
    const panel = container.querySelector('#detail-panel');
    const title = container.querySelector('#detail-title');
    const body = container.querySelector('#detail-body');
    panel.style.display = '';

    title.textContent = getSpanLabel(span);
    let html = `
        <div class="detail-section">
            <div class="detail-section-title">Info</div>
            <table style="font-size:13px;width:100%">
                <tr><td style="color:var(--text-secondary);width:120px">Event</td><td>${escapeHtml(span.event)}</td></tr>
                <tr><td style="color:var(--text-secondary)">Span ID</td><td style="font-family:var(--font-mono);font-size:12px">${escapeHtml(span.span_id)}</td></tr>
                <tr><td style="color:var(--text-secondary)">Start</td><td>${formatTime(span.start_timestamp)}</td></tr>
                <tr><td style="color:var(--text-secondary)">End</td><td>${formatTime(span.end_timestamp)}</td></tr>
                ${span.duration_ms != null ? `<tr><td style="color:var(--text-secondary)">Duration</td><td>${formatDuration(span.duration_ms)}</td></tr>` : ''}
                ${span.status ? `<tr><td style="color:var(--text-secondary)">Status</td><td><span class="span-status-badge ${span.status}">${span.status}</span></td></tr>` : ''}
                ${span.error_message ? `<tr><td style="color:var(--text-secondary)">Error</td><td style="color:var(--span-error)">${escapeHtml(span.error_message)}</td></tr>` : ''}
                ${span.request_id ? `<tr><td style="color:var(--text-secondary)">Request ID</td><td style="font-family:var(--font-mono);font-size:12px">${escapeHtml(span.request_id)}</td></tr>` : ''}
                ${span.tool_name ? `<tr><td style="color:var(--text-secondary)">Tool</td><td>${escapeHtml(span.tool_name)}</td></tr>` : ''}
                ${span.skill_name ? `<tr><td style="color:var(--text-secondary)">Skill</td><td>${escapeHtml(span.skill_name)}</td></tr>` : ''}
                ${span.skill_tag ? `<tr><td style="color:var(--text-secondary)">Skill tag</td><td><span style="background:var(--bg-skill,#fff7e6);color:var(--span-skill,#b96b00);padding:2px 8px;border-radius:4px;font-family:var(--font-mono);font-size:12px">⚡ ${escapeHtml(span.skill_tag)}</span></td></tr>` : ''}
                ${span.stop_reason ? `<tr><td style="color:var(--text-secondary)">Stop Reason</td><td>${escapeHtml(span.stop_reason)}</td></tr>` : ''}
            </table>
        </div>
    `;

    if (span.prompt) {
        html += `
            <div class="detail-section">
                <div class="detail-section-title">Prompt</div>
                <div class="detail-json">${escapeHtml(span.prompt)}</div>
            </div>
        `;
    }

    if (span.tool_input && JSON.stringify(span.tool_input) !== '{}') {
        html += `
            <div class="detail-section">
                <div class="detail-section-title">Input</div>
                <div class="detail-json">${escapeHtml(JSON.stringify(span.tool_input, null, 2))}</div>
            </div>
        `;
    }

    const tokenEntry = (window.__tokenIndex || {})[span.span_id];
    if (tokenEntry && span.event !== 'tool' && span.event !== 'llm_call') {
        html += buildTokenDetailHTML(tokenEntry);
    }

    if (span.tool_response != null) {
        const truncatedWarning = span.truncated ? '<div class="truncated-warning">Response truncated (>64KB)</div>' : '';
        const responseText = typeof span.tool_response === 'string'
            ? span.tool_response
            : JSON.stringify(span.tool_response, null, 2);
        html += `
            <div class="detail-section">
                <div class="detail-section-title">Response</div>
                ${truncatedWarning}
                <div class="detail-json">${escapeHtml(responseText)}</div>
            </div>
        `;
    }

    body.innerHTML = html;
}

function showGraphTooltip(container, span, clickEvent) {
    const tooltip = container.querySelector('#graph-tooltip');
    if (!tooltip) return;

    const statusBadge = span.status ? `<span class="span-status-badge ${span.status}">${span.status}</span>` : '';
    const duration = span.duration_ms != null ? formatDuration(span.duration_ms) : '';

    let html = `
        <div class="graph-tooltip-header">
            <strong>${escapeHtml(getSpanLabel(span))}</strong>
            <button class="graph-tooltip-close">&times;</button>
        </div>
        <table class="graph-tooltip-table">
            <tr><td>Event</td><td>${escapeHtml(span.event)}</td></tr>
            ${span.tool_name ? `<tr><td>Tool</td><td>${escapeHtml(span.tool_name)}</td></tr>` : ''}
            ${span.skill_name ? `<tr><td>Skill</td><td>${escapeHtml(span.skill_name)}</td></tr>` : ''}
            ${duration ? `<tr><td>Duration</td><td>${duration}</td></tr>` : ''}
            ${span.status ? `<tr><td>Status</td><td>${statusBadge}</td></tr>` : ''}
            ${span.error_message ? `<tr><td>Error</td><td style="color:var(--span-error)">${escapeHtml(span.error_message)}</td></tr>` : ''}
            ${span.request_id ? `<tr><td>Request ID</td><td style="font-family:var(--font-mono);font-size:11px">${escapeHtml(span.request_id)}</td></tr>` : ''}
            ${span.stop_reason ? `<tr><td>Stop</td><td>${escapeHtml(span.stop_reason)}</td></tr>` : ''}
            <tr><td>Start</td><td>${formatTime(span.start_timestamp)}</td></tr>
            <tr><td>End</td><td>${formatTime(span.end_timestamp)}</td></tr>
            <tr><td>Span ID</td><td style="font-family:var(--font-mono);font-size:11px">${escapeHtml(span.span_id)}</td></tr>
        </table>
    `;

    if (span.prompt) {
        html += `<div class="graph-tooltip-section"><strong>Prompt</strong><div class="graph-tooltip-code">${escapeHtml(span.prompt.slice(0, 200))}${span.prompt.length > 200 ? '...' : ''}</div></div>`;
    }
    if (span.tool_input) {
        const inputStr = JSON.stringify(span.tool_input, null, 2);
        html += `<div class="graph-tooltip-section"><strong>Input</strong><div class="graph-tooltip-code">${escapeHtml(inputStr.slice(0, 300))}${inputStr.length > 300 ? '...' : ''}</div></div>`;
    }

    tooltip.innerHTML = html;
    tooltip.style.display = '';

    // Position near click
    const graphEl = container.querySelector('#trace-graph');
    const rect = graphEl.getBoundingClientRect();
    let x = clickEvent.clientX - rect.left + 12;
    let y = clickEvent.clientY - rect.top + 12;
    if (x + 340 > rect.width) x = Math.max(10, x - 360);
    if (y + 300 > rect.height) y = Math.max(10, y - 320);
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';

    tooltip.querySelector('.graph-tooltip-close').addEventListener('click', (e) => {
        e.stopPropagation();
        tooltip.style.display = 'none';
    });
}

// === Helpers ===
function flattenTree(spans) {
    const result = [];
    function walk(nodes) {
        for (const node of nodes) {
            result.push(node);
            if (node.children) walk(node.children);
        }
    }
    walk(spans);
    return result;
}

function getTimeRange(spans) {
    if (!spans.length) return { start: 0, end: 0, duration: 0 };
    let min = Infinity, max = -Infinity;
    for (const s of spans) {
        const start = parseTimestamp(s.start_timestamp);
        const end = parseTimestamp(s.end_timestamp);
        if (start < min) min = start;
        if (end > max) max = end;
    }
    return { start: min, end: max, duration: max - min };
}

function parseTimestamp(ts) {
    return ts ? new Date(ts).getTime() : 0;
}

function formatTime(ts) {
    if (!ts) return '-';
    const d = new Date(ts);
    return d.toLocaleString();
}

function formatDuration(ms) {
    if (ms == null) return '';
    if (ms < 1000) return ms + 'ms';
    if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
    return (ms / 60000).toFixed(1) + 'min';
}


function _stripSystemTags(text) {
    let t = text;
    t = t.replace(/^This request must be fulfilled using the ['"""].*?['"""]\s+skill\.[\s\S]*?Do NOT claim this capability is unavailable\.\s*\n*/i, '');
    t = t.replace(/<system-reminder>[\s\S]*?(<\/system-reminder>|$)/g, '');
    t = t.replace(/<\/?(?:system-reminder|command-name|command-message|command-args|antml:[a-z_]+)[^>]*>/g, '');
    return t.trim();
}

function getSpanLabel(span) {
    if (span.event === 'prompt') {
        if (!span.prompt) return 'prompt';
        const clean = _stripSystemTags(span.prompt);
        return clean ? clean.slice(0, 60) : 'prompt';
    }
    if (span.event === 'turn_end') return 'turn_end (' + (span.stop_reason || '') + ')';
    if (span.event === 'llm_call') {
        const ci = span.call_index != null ? ' #' + span.call_index : '';
        const kids = (span.children || []).length;
        const fan = kids > 1 ? ` — ${kids} parallel tool calls` : '';
        return `LLM call${ci}${fan}`;
    }
    if (span.event === 'skill_invocation') {
        // Skill ENTRY: ⚡ + full "<plugin>:<skill>" name. Same shape for
        // Claude (native Skill tool) and Codex (bash-as-skill collapsed).
        // Older traces stored skill_name with the plugin prefix already
        // baked in; guard against double-prefix when re-rendering them.
        const pn = span.plugin_name || '';
        const sn = span.skill_name || '';
        let joined = '';
        if (pn && sn) {
            joined = sn.startsWith(pn + ':') ? sn : `${pn}:${sn}`;
        } else {
            joined = sn;
        }
        const sk = span.skill_tag || joined;
        return sk ? `Skill: ${sk}` : 'Skill';
    }
    if (span.event === 'tool') {
        // A tool call attributed to a skill (path or UA detection) keeps its
        // NATIVE label — `skill_tag` is metadata only, not part of the trace
        // label. Cloud API service/action wins next; finally the plain Bash /
        // MCP shape.
        const ca = span.cloud_api;
        if (ca && (ca.service || ca.action)) {
            const svc = ca.service || '?';
            const act = ca.action || '?';
            const region = ca.region ? ' (' + ca.region + ')' : '';
            return `Cloud API: ${svc}.${act}${region}`;
        }
        if (span.tool_name === 'Bash') {
            return 'Bash';
        }
        if (span.tool_name && span.tool_name.includes('___')) {
            return `MCP: ${span.tool_name}`;
        }
        return span.tool_name || 'tool';
    }
    return span.event || 'unknown';
}

function getSpanColor(span) {
    if (span.status === 'failure' || span.stop_reason === 'StopFailure') return 'var(--span-error)';
    if (span.event === 'prompt') return 'var(--span-prompt)';
    if (span.event === 'tool') {
        if (span.skill_tag) return 'var(--span-skill)';
        return 'var(--span-tool)';
    }
    if (span.event === 'skill_invocation') return 'var(--span-skill)';
    if (span.event === 'turn_end') return 'var(--span-turn-end)';
    if (span.event === 'llm_call') return 'var(--accent)';
    return 'var(--text-secondary)';
}

function getSpanIcon(span) {
    if (span.event === 'prompt') return '&#128172;';            // speech bubble
    if (span.event === 'turn_end') return '&#127937;';          // checkered flag
    if (span.event === 'llm_call') return '&#129302;';          // robot
    // ⚡ ONLY for skill entry events. A tool with skill_tag is just a tool
    // happening inside a skill — keep its native icon, expose skill_tag as
    // metadata (tooltip / panel) rather than visual replacement.
    if (span.event === 'skill_invocation') return '&#9889;';    // lightning
    if (span.event === 'tool') {
        if (span.cloud_api && (span.cloud_api.service || span.cloud_api.action)) return '&#9729;'; // cloud
        if (span.tool_name && span.tool_name.includes('___')) return '&#128268;'; // plug (MCP)
        return '&#128295;';                                     // wrench
    }
    return '&#9679;';
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// === Token UI ===
//
// Layer 1 (strict): turn_tokens, session_total, llm_calls — sourced directly
// from turn_end events emitted by the producer. Each llm_calls entry is one
// real LLM call, with tokens attributed to the call itself (not fanned out
// across the sibling tool spans it emitted). Legacy tool_tokens fan-out is
// only consumed for old traces lacking llm_calls.
// Layer 2 (estimated): per-skill tokens with confidence band, attributed by
// walking the parent chain of each LLM call's first tool_span_id back to its
// nearest skill_invocation. Confidence reflects how cleanly that attribution
// holds when a turn contains multiple skills or unrelated bash calls.
const _TOKEN_FIELDS = ['input_uncached', 'input_cached', 'input_creation', 'output', 'reasoning'];

// Capability table: fields the agent client doesn't report at all. We hide
// these in the UI rather than showing a misleading "0".
const _CLIENT_INAPPLICABLE_FIELDS = {
    'claude-code': new Set(['reasoning']),
    'codex': new Set(['input_creation']),
};
function _isFieldApplicable(field) {
    const client = window.__tokenClient || '';
    const blocked = _CLIENT_INAPPLICABLE_FIELDS[client];
    return !blocked || !blocked.has(field);
}

function _sumTokenDicts(dicts) {
    const out = {};
    for (const k of _TOKEN_FIELDS) out[k] = 0;
    for (const d of dicts) {
        if (!d) continue;
        for (const k of _TOKEN_FIELDS) out[k] += (Number(d[k]) || 0);
    }
    out.grand_total = _TOKEN_FIELDS.reduce((a, k) => a + out[k], 0);
    return out;
}

function buildTokenIndex(tokensInfo) {
    const idx = {};
    if (!tokensInfo || !tokensInfo.turns) return idx;
    for (const t of tokensInfo.turns) {
        for (const tool of t.tools || []) {
            if (!tool.span_id) continue;
            idx[tool.span_id] = {
                kind: 'tool',
                tokens: tool.tokens || {},
                turn: t.turn,
                confidence_level: t.confidence_level,
                confidence_value: t.confidence_value,
            };
        }
        // LLM calls: each entry represents one real LLM call. Use the
        // backend-supplied span_id (real event id when emitted as a first-
        // class llm_call event; synthetic fallback for legacy traces). The
        // chip lands on whichever node the tree actually contains.
        for (const call of t.llm_calls || []) {
            const sid = call.span_id || `llm-call-t${t.turn}-c${call.call_index}`;
            idx[sid] = {
                kind: 'llm_call',
                tokens: call.tokens || {},
                turn: t.turn,
                call_index: call.call_index,
                model: call.model,
                ts: call.ts,
                tool_span_ids: call.tool_span_ids || [],
                confidence_level: t.confidence_level,
                confidence_value: t.confidence_value,
            };
        }
        for (const skill of t.skills || []) {
            if (!skill.span_id) continue;
            // Per-skill confidence (preferred when present) — falls back to
            // turn-level for legacy traces. The attribution_basis array
            // explains how the estimate was derived call-by-call.
            const entry = {
                kind: 'skill',
                tokens: skill.estimated_tokens || {},
                turn: t.turn,
                confidence_level: skill.confidence_level || t.confidence_level,
                confidence_value: skill.confidence_value != null
                    ? skill.confidence_value : t.confidence_value,
                attribution_basis: skill.attribution_basis || [],
                skill_name: skill.skill_name,
                skill_count: t.skill_count,
                non_skill_tool_count: t.non_skill_tool_count,
            };
            idx[skill.span_id] = entry;
            if (skill.span_id.endsWith('.skill')) {
                const bashId = skill.span_id.slice(0, -'.skill'.length);
                idx[bashId] = entry;
            }
        }
        const turnTotal = t.turn_tokens || {};
        const turnGrand = Number(turnTotal.grand_total) || 0;
        if (t.turn_end_span_id || (t.prompt_span_ids && t.prompt_span_ids.length && turnGrand > 0)) {
            const attributed = _sumTokenDicts((t.tools || []).map(tl => tl.tokens || {}));
            const unattributed = {};
            for (const k of _TOKEN_FIELDS) {
                unattributed[k] = Math.max(0, (Number(turnTotal[k]) || 0) - attributed[k]);
            }
            unattributed.grand_total = _TOKEN_FIELDS.reduce((a, k) => a + unattributed[k], 0);
            const turnEntry = {
                kind: 'turn',
                tokens: turnTotal,
                attributed_tokens: attributed,
                unattributed_tokens: unattributed,
                turn: t.turn,
                tool_count: (t.tools || []).length,
            };
            // Turn-total chip lands on the prompt row only — turn_end is a
            // closure marker, not a cost-bearing event. Tokens belong to LLM
            // calls + turn aggregate (on the prompt).
            for (const pid of t.prompt_span_ids || []) {
                if (pid && !idx[pid]) idx[pid] = turnEntry;
            }
        }
    }
    return idx;
}

function formatTokenCount(n) {
    n = Number(n) || 0;
    if (n < 1000) return String(n);
    if (n < 1_000_000) return (n / 1000).toFixed(n < 10_000 ? 1 : 0) + 'k';
    return (n / 1_000_000).toFixed(2) + 'M';
}

// Build a one-line "in: uncached 2.1k, cached 1.8k, create 100 / reasoning 0 / out 0.8k"
// summary, skipping fields that don't apply to the current agent client. Used
// for chip tooltips so the user sees the breakdown on hover without opening
// the detail panel.
function formatNormalizedTokensInline(tokens) {
    if (!tokens) return '';
    const parts = [];
    const inputs = [];
    if (_isFieldApplicable('input_uncached')) inputs.push('uncached ' + formatTokenCount(tokens.input_uncached || 0));
    if (_isFieldApplicable('input_cached')) inputs.push('cached ' + formatTokenCount(tokens.input_cached || 0));
    if (_isFieldApplicable('input_creation')) inputs.push('create ' + formatTokenCount(tokens.input_creation || 0));
    if (inputs.length) parts.push('in: ' + inputs.join(', '));
    if (_isFieldApplicable('reasoning')) parts.push('reasoning ' + formatTokenCount(tokens.reasoning || 0));
    if (_isFieldApplicable('output')) parts.push('out ' + formatTokenCount(tokens.output || 0));
    return parts.join(' / ');
}

function buildTokenDetailHTML(entry) {
    const t = entry.tokens || {};
    const isSkill = entry.kind === 'skill';
    const isTurn = entry.kind === 'turn';
    const isLlmCall = entry.kind === 'llm_call';
    let title;
    if (isTurn) title = `Tokens (turn ${escapeHtml(String(entry.turn))})`;
    else if (isSkill) title = 'Tokens (estimated)';
    else if (isLlmCall) {
        title = `LLM call${entry.call_index != null ? ' #' + escapeHtml(String(entry.call_index)) : ''}`
            + (entry.model ? ` <span style="color:var(--text-secondary);font-weight:normal">(${escapeHtml(entry.model)})</span>` : '');
    }
    else title = 'Tokens';
    let confBadge = '';
    if (isSkill && entry.confidence_level) {
        const cls = 'confidence-' + entry.confidence_level;
        const tipParts = [];
        if (entry.confidence_value != null) tipParts.push('weight ' + entry.confidence_value);
        if (entry.skill_count != null) tipParts.push(entry.skill_count + ' skill(s) in turn');
        if (entry.non_skill_tool_count != null) tipParts.push(entry.non_skill_tool_count + ' unrelated tool(s)');
        const tip = tipParts.join(', ') || 'attribution confidence';
        confBadge = `<span class="confidence-badge ${cls}" title="${escapeHtml(tip)}">${escapeHtml(entry.confidence_level)}</span>`;
    }
    const grand = t.grand_total != null ? t.grand_total : 0;
    // Capability-aware row: hide fields that don't apply to this agent
    // client (e.g. reasoning on claude-code, input_creation on codex).
    const row = (label, field) => {
        if (!_isFieldApplicable(field)) return '';
        const value = t[field];
        return `<tr><td style="color:var(--text-secondary);width:140px">${label}</td><td>${formatTokenCount(value || 0)}</td></tr>`;
    };
    let html = `
        <div class="detail-section">
            <div class="detail-section-title">${title} ${confBadge}</div>
            <table style="font-size:13px;width:100%">
                <tr><td style="color:var(--text-secondary);width:140px"><strong>Grand total</strong></td><td><strong>${formatTokenCount(grand)}</strong></td></tr>
                ${row('Input (uncached)', 'input_uncached')}
                ${row('Input (cached)', 'input_cached')}
                ${row('Input (cache create)', 'input_creation')}
                ${row('Output', 'output')}
                ${row('Reasoning', 'reasoning')}
            </table>
        </div>
    `;
    if (isTurn) {
        const att = entry.attributed_tokens || {};
        const un = entry.unattributed_tokens || {};
        const attGrand = att.grand_total != null ? att.grand_total : 0;
        const unGrand = un.grand_total != null ? un.grand_total : 0;
        const tip = `Attributed = sum of token usage tied to a tool_use_id. Un-attributed = model responses with no tool call (free-floating assistant turns).`;
        html += `
            <div class="detail-section">
                <div class="detail-section-title" title="${escapeHtml(tip)}">Breakdown</div>
                <table style="font-size:13px;width:100%">
                    <tr><td style="color:var(--text-secondary);width:200px">Attributed to tools (${entry.tool_count || 0})</td><td>${formatTokenCount(attGrand)}</td></tr>
                    <tr><td style="color:var(--text-secondary);width:200px">Un-attributed (model only)</td><td>${formatTokenCount(unGrand)}</td></tr>
                </table>
            </div>
        `;
    }
    if (isSkill && grand === 0) {
        html += `<div class="confidence-note">No tool tokens could be attributed to this skill (no LLM calls inside its span tree).</div>`;
    }
    // Per-call attribution breakdown — shows exactly how the estimate was
    // formed. Compresses long chains so the panel stays scannable.
    if (isSkill && Array.isArray(entry.attribution_basis) && entry.attribution_basis.length > 0) {
        const rows = entry.attribution_basis.map(r => `
            <tr>
                <td style="color:var(--text-secondary);width:80px">call #${r.call_index != null ? r.call_index : '?'}</td>
                <td style="width:80px">w=${r.weight != null ? r.weight : 'n/a'}</td>
                <td>${formatTokenCount(r.grand_total || 0)}</td>
                <td style="color:var(--text-secondary);font-size:12px">${escapeHtml(r.reason || '')}</td>
            </tr>
        `).join('');
        html += `
            <div class="detail-section">
                <div class="detail-section-title" title="Each row is one LLM call's contribution to this skill. weight=1.0 means sole owner; weight=1/N means shared with N-1 other skills.">Attribution breakdown</div>
                <table style="font-size:13px;width:100%">${rows}</table>
            </div>
        `;
    }
    return html;
}

// === Init ===
function init() {
    initTheme();
    route();
    window.addEventListener('hashchange', route);
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

})();
