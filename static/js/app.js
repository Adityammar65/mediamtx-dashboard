

const API_BASE = '/api';
let refreshInterval = null;
let currentPage = 'dashboard';
let currentPathName = null;
let currentRoute = '';
let sidebarCollapsed = false;
let pathHlsPlayer = null;
let authRedirecting = false;

// --- Utility Functions ---

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatNumber(num) {
    if (num === undefined || num === null || isNaN(num)) return '0';
    return Number(num).toLocaleString();
}

function getUptimeSeconds(startedString) {
    if (!startedString) return 0;
    const startTime = new Date(startedString).getTime();
    const now = Date.getTime ? Date.now() : new Date().getTime();
    const diffSeconds = Math.floor((now - startTime) / 1000);
    return diffSeconds > 0 ? diffSeconds : 0;
}

function formatUptime(seconds) {
    seconds = getUptimeSeconds(seconds);
    if (!seconds) return '-';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    const parts = [];
    if (d) parts.push(`${d}d`);
    if (h) parts.push(`${h}h`);
    if (m) parts.push(`${m}m`);
    parts.push(`${s}s`);
    return parts.join(' ');
}

async function fetchAPI(endpoint, options = {}) {
    const res = await fetch(`${API_BASE}${endpoint}`, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ message: 'Request failed' }));
        if (res.status === 401 && !authRedirecting) {
            authRedirecting = true;
            stopAutoRefresh();
            window.location.replace('/login');
        }
        const error = new Error(err.message || err.detail || `HTTP ${res.status}`);
        error.status = res.status;
        throw error;
    }
    return res.json();
}

function showError(message) {
    console.error(message);
}

function setConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    el.textContent = connected ? 'Connected' : 'Disconnected';
    el.classList.toggle('text-green-600', connected);
    el.classList.toggle('text-red-600', !connected);
    el.classList.toggle('text-gray-500', !connected);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function containsMaskedCredentials(value) {
    return typeof value === 'string' && (
        value.includes(':***@') ||
        /(?:token|password|passwd|secret|authorization|auth|api[_-]?key)=[^&]*(?:%2A|\*){3}/i.test(value)
    );
}

// --- System Monitor Utilities ---

function formatBytesPerSec(bytes) {
    if (bytes === 0 || bytes === null || bytes === undefined) return '0 B/s';
    const k = 1024;
    const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatBytesShort(bytes) {
    if (bytes === 0 || bytes === null || bytes === undefined) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function renderSparkline(svgId, data, color, fillColor) {
    const svg = document.getElementById(svgId);
    if (!svg || !data || data.length === 0) return;

    const width = svg.clientWidth || 200;
    const height = 96;
    const padding = 2;
    const usableWidth = width - padding * 2;
    const usableHeight = height - padding * 2;


    const maxVal = Math.max(...data, 1);
    const minVal = Math.min(...data, 0);
    const range = maxVal - minVal || 1;

    const points = data.map((val, i) => {
        const x = padding + (i / Math.max(data.length - 1, 1)) * usableWidth;
        const y = padding + usableHeight - ((val - minVal) / range) * usableHeight;
        return `${x},${y}`;
    });

    const pathData = `M${points.join(' L')}`;
    const fillPathData = `${pathData} L${width - padding},${height - padding} L${padding},${height - padding} Z`;

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = `
        <defs>
            <linearGradient id="sparkline-gradient-${svgId}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${fillColor}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${fillColor}" stop-opacity="0"/>
            </linearGradient>
        </defs>
        <path d="${fillPathData}" fill="url(#sparkline-gradient-${svgId})" />
        <path d="${pathData}" stroke="${color}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round" />
    `;
}

function updateMetricCard(metric, data) {
    switch (metric) {
        case 'cpu': {
            const usage = data.cpu?.usage;
            const history = data.cpu?.history || [];
            const valEl = document.getElementById('cpu-usage-value');
            const barEl = document.getElementById('cpu-usage-bar');
            const detailEl = document.getElementById('cpu-usage-detail');

            if (usage !== null && usage !== undefined) {
                valEl.textContent = `${usage.toFixed(1)}%`;
                barEl.style.width = `${Math.min(100, Math.max(0, usage))}%`;
                barEl.parentElement.setAttribute('aria-valuenow', Math.round(usage));
                detailEl.textContent = `Usage: ${usage.toFixed(1)}%`;
                detailEl.classList.remove('hidden');
            } else {
                valEl.textContent = '--%';
                barEl.style.width = '0%';
                detailEl.textContent = data.cpu?.error || 'CPU metrics unavailable';
                detailEl.classList.remove('hidden');
            }
            renderSparkline('cpu-sparkline', history, '#2563eb', '#2563eb');
            break;
        }
        case 'memory': {
            const usage = data.memory?.usage;
            const total = data.memory?.total;
            const available = data.memory?.available;
            const history = data.memory?.history || [];
            const valEl = document.getElementById('mem-usage-value');
            const barEl = document.getElementById('mem-usage-bar');
            const detailEl = document.getElementById('mem-usage-detail');

            if (usage !== null && usage !== undefined) {
                valEl.textContent = `${usage.toFixed(1)}%`;
                barEl.style.width = `${Math.min(100, Math.max(0, usage))}%`;
                barEl.parentElement.setAttribute('aria-valuenow', Math.round(usage));
                if (total !== null && total !== undefined && available !== null && available !== undefined) {
                    detailEl.textContent = `${formatBytesShort(total - available)} / ${formatBytesShort(total)}`;
                    detailEl.classList.remove('hidden');
                }
            } else {
                valEl.textContent = '--%';
                barEl.style.width = '0%';
                detailEl.textContent = data.memory?.error || 'Memory metrics unavailable';
                detailEl.classList.remove('hidden');
            }
            renderSparkline('mem-sparkline', history, '#16a34a', '#16a34a');
            break;
        }
        case 'disk': {
            const usage = data.disk?.usage;
            const total = data.disk?.total;
            const free = data.disk?.free;
            const history = data.disk?.history || [];
            const valEl = document.getElementById('disk-usage-value');
            const barEl = document.getElementById('disk-usage-bar');
            const detailEl = document.getElementById('disk-usage-detail');

            if (usage !== null && usage !== undefined) {
                valEl.textContent = `${usage.toFixed(1)}%`;
                barEl.style.width = `${Math.min(100, Math.max(0, usage))}%`;
                barEl.parentElement.setAttribute('aria-valuenow', Math.round(usage));
                if (total && free !== undefined) {
                    detailEl.textContent = `${formatBytesShort(total - free)} / ${formatBytesShort(total)}`;
                    detailEl.classList.remove('hidden');
                }
            } else {
                valEl.textContent = '--%';
                barEl.style.width = '0%';
                detailEl.textContent = data.disk?.error || 'Disk metrics unavailable';
                detailEl.classList.remove('hidden');
            }
            renderSparkline('disk-sparkline', history, '#ca8a04', '#ca8a04');
            break;
        }
        case 'network': {
            const rxRate = data.network?.rx_rate;
            const txRate = data.network?.tx_rate;
            const rxHistory = data.network?.rx_history || [];
            const txHistory = data.network?.tx_history || [];
            const valEl = document.getElementById('net-usage-value');
            const rxEl = document.getElementById('net-rx-value');
            const txEl = document.getElementById('net-tx-value');
            const detailEl = document.getElementById('net-usage-detail');

            if (rxRate !== null && rxRate !== undefined && txRate !== null && txRate !== undefined) {
                rxEl.textContent = formatBytesPerSec(rxRate);
                txEl.textContent = formatBytesPerSec(txRate);
                valEl.textContent = `${formatBytesPerSec(rxRate)} ↓ / ${formatBytesPerSec(txRate)} ↑`;
                detailEl.textContent = `RX: ${formatBytesPerSec(rxRate)} / TX: ${formatBytesPerSec(txRate)}`;
                detailEl.classList.remove('hidden');
            } else {
                rxEl.textContent = '--';
                txEl.textContent = '--';
                valEl.textContent = '--';
                detailEl.textContent = data.network?.error || 'Network metrics unavailable';
                detailEl.classList.remove('hidden');
            }

            renderNetworkSparkline('net-sparkline', rxHistory, txHistory);
            break;
        }
    }
}

function renderNetworkSparkline(svgId, rxData, txData) {
    const svg = document.getElementById(svgId);
    if (!svg) return;

    const width = svg.clientWidth || 200;
    const height = 96;
    const padding = 2;
    const usableWidth = width - padding * 2;
    const usableHeight = height - padding * 2;

    const allData = [...rxData, ...txData];
    if (allData.length === 0) {
        svg.innerHTML = '';
        return;
    }

    const maxVal = Math.max(...allData, 1);
    const minVal = Math.min(...allData, 0);
    const range = maxVal - minVal || 1;

    const renderLine = (data, color, fillColor, isRx) => {
        if (data.length === 0) return '';
        const points = data.map((val, i) => {
            const x = padding + (i / Math.max(data.length - 1, 1)) * usableWidth;
            const y = padding + usableHeight - ((val - minVal) / range) * usableHeight;
            return `${x},${y}`;
        });
        const pathData = `M${points.join(' L')}`;
        const fillPathData = `${pathData} L${width - padding},${height - padding} L${padding},${height - padding} Z`;
        return `
            <defs>
                <linearGradient id="sparkline-gradient-${svgId}-${isRx ? 'rx' : 'tx'}" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="${fillColor}" stop-opacity="0.15"/>
                    <stop offset="100%" stop-color="${fillColor}" stop-opacity="0"/>
                </linearGradient>
            </defs>
            <path d="${fillPathData}" fill="url(#sparkline-gradient-${svgId}-${isRx ? 'rx' : 'tx'})" />
            <path d="${pathData}" stroke="${color}" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="${isRx ? 'none' : '4,3'}" />
        `;
    };

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = `
        ${renderLine(rxData, '#2563eb', '#2563eb', true)}
        ${renderLine(txData, '#9333ea', '#9333ea', false)}
    `;
}

function showSystemMonitorLoading() {
    document.getElementById('system-monitor-status').textContent = 'Loading...';
    document.getElementById('system-monitor-status').classList.remove('hidden');
    document.getElementById('system-monitor-updated').classList.add('hidden');
    document.getElementById('system-monitor-grid').classList.add('opacity-50', 'pointer-events-none');
    document.getElementById('system-monitor-unavailable').classList.add('hidden');
}

function showSystemMonitorError(error) {
    document.getElementById('system-monitor-status').classList.add('hidden');
    document.getElementById('system-monitor-updated').classList.add('hidden');
    document.getElementById('system-monitor-grid').classList.add('hidden');
    document.getElementById('system-monitor-unavailable').classList.remove('hidden');
    document.getElementById('system-monitor-error').textContent = error || 'Unable to connect to Node Exporter';
}

function showSystemMonitorSuccess(data) {
    document.getElementById('system-monitor-status').classList.add('hidden');
    document.getElementById('system-monitor-grid').classList.remove('opacity-50', 'pointer-events-none', 'hidden');
    document.getElementById('system-monitor-unavailable').classList.add('hidden');

    const updatedEl = document.getElementById('system-monitor-updated');
    if (data.last_update) {
        const date = new Date(data.last_update * 1000);
        updatedEl.textContent = `Updated: ${date.toLocaleTimeString()}`;
        updatedEl.classList.remove('hidden');
    }

    updateMetricCard('cpu', data);
    updateMetricCard('memory', data);
    updateMetricCard('disk', data);
    updateMetricCard('network', data);
}

async function fetchSystemMetrics() {
    showSystemMonitorLoading();
    try {
        const res = await fetchAPI('/system/metrics');
        if (res.success) {
            const data = res.data;
            if (data.available === false) {
                showSystemMonitorError(data.error || 'Node Exporter unavailable');
            } else {
                showSystemMonitorSuccess(data);
            }
        } else {
            showSystemMonitorError(res.message || 'Failed to fetch system metrics');
        }
    } catch (e) {
        showSystemMonitorError(e.message);
    }
}

// --- Sidebar Functions ---

function initSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('main-content');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const sidebarLogo = document.getElementById('sidebar-logo');
    const logoutButton = document.getElementById('logout-btn');


    const savedCollapsed = localStorage.getItem('sidebarCollapsed');
    if (savedCollapsed === 'true') {
        sidebarCollapsed = true;
        sidebar.classList.add('sidebar-collapsed');
        mainContent.classList.add('sidebar-collapsed');
        sidebarLogo.textContent = 'M';
    }


    sidebarToggle.addEventListener('click', () => {
        sidebarCollapsed = !sidebarCollapsed;
        sidebar.classList.toggle('sidebar-collapsed');
        mainContent.classList.toggle('sidebar-collapsed');
        sidebarLogo.textContent = sidebarCollapsed ? 'M' : 'MediaMTX Dashboard';
        localStorage.setItem('sidebarCollapsed', sidebarCollapsed);
    });


    mobileMenuBtn.addEventListener('click', () => {
        sidebar.classList.add('mobile-open');
        sidebarOverlay.classList.remove('hidden');
        document.body.style.overflow = 'hidden';
    });


    sidebarOverlay.addEventListener('click', () => {
        sidebar.classList.remove('mobile-open');
        sidebarOverlay.classList.add('hidden');
        document.body.style.overflow = '';
    });


    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', () => {
            if (window.innerWidth < 1024) {
                sidebar.classList.remove('mobile-open');
                sidebarOverlay.classList.add('hidden');
                document.body.style.overflow = '';
            }
        });
    });

    logoutButton.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to log out?')) return;

        logoutButton.disabled = true;
        try {
            await fetchAPI('/logout', { method: 'POST' });
            stopAutoRefresh();
            window.location.replace('/login');
        } catch (error) {
            logoutButton.disabled = false;
            alert(`Unable to log out: ${error.message}`);
        }
    });
}

// --- Page Routing ---

const pageTitleMap = {
    'dashboard': 'Dashboard',
    'streams': 'Streams',
    'config-global': 'Configuration - Global',
    'config-paths': 'Configuration - Paths',
    'config-defaults': 'Configuration - Path Defaults',
    'runtime-hls': 'Runtime - HLS',
    'runtime-rtsp': 'Runtime - RTSP',
    'runtime-rtmp': 'Runtime - RTMP',
    'runtime-logs': 'Runtime - Logs',
};

function getPageFromHash() {
    const hash = window.location.hash.slice(1);
    return hash.split('/')[0] || 'dashboard';
}

function getPathNameFromHash() {
    if (getPageFromHash() !== 'path-detail') return null;

    try {
        return decodeURIComponent(window.location.hash.slice(1).slice('path-detail/'.length));
    } catch {
        return null;
    }
}

async function navigateToPage(page, pathName = null) {
    const knownPages = ['dashboard', 'streams', 'path-detail', 'config-global', 'config-defaults', 'runtime-hls', 'runtime-rtsp', 'runtime-rtmp', 'runtime-logs', 'config-paths'];
    const template = knownPages.includes(page) ? page : 'placeholder';
    const content = document.getElementById('page-content');

    if (page !== 'path-detail' || pathName !== currentPathName) {
        pathDetailState = null;
        pathDetailLoadId++;
    }
    if (pathHlsPlayer && (page !== 'path-detail' || pathName !== currentPathName)) {
        pathHlsPlayer.destroy();
        pathHlsPlayer = null;
    }
    content.innerHTML = '<div class="flex items-center justify-center py-12"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div></div>';

    try {
        const response = await fetch(`/static/pages/${template}.html`);
        if (!response.ok) throw new Error(`Unable to load ${template} page`);

        content.innerHTML = await response.text();


        bindPageEvents(page);


        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.toggle(
                'nav-active',
                link.dataset.page === page || (page === 'path-detail' && link.dataset.page === 'streams'),
            );
        });
        currentPathName = page === 'path-detail' ? pathName : null;
        document.getElementById('page-title').textContent = page === 'path-detail'
            ? (pathName || 'Path Detail')
            : pageTitleMap[page] || 'Dashboard';

        currentPage = page;
        await loadPageData(page);
    } catch (error) {
        content.innerHTML = `<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">Error: ${escapeHtml(error.message)}</div>`;
        setConnectionStatus(false);
    }
}

function bindPageEvents(page) {
    if (page === 'dashboard') {
        document.getElementById('paths-table-body')?.addEventListener('click', event => {
            const button = event.target.closest?.('button[data-path-action]');
            if (!button) return;
            const name = button.dataset.pathName;
            if (button.dataset.pathAction === 'detail') {
                window.location.hash = `#path-detail/${encodeURIComponent(name)}`;
            }
        });
    }
    if (page === 'streams') {
        document.getElementById('streams-table-body')?.addEventListener('click', event => {
            const button = event.target.closest?.('button[data-path-action]');
            if (!button) return;
            const name = button.dataset.pathName;
            if (button.dataset.pathAction === 'detail') {
                window.location.hash = `#path-detail/${encodeURIComponent(name)}`;
            }
            if (button.dataset.pathAction === 'edit') window.editPath(name);
            if (button.dataset.pathAction === 'delete') window.deletePath(name);
        });
        document.getElementById('streams-search')?.addEventListener('input', () => {
            streamsCurrentPage = 1;
            renderStreams(allStreams);
        });
        document.getElementById('streams-refresh')?.addEventListener('click', loadStreams);
    }
    if (page === 'path-detail') {
        document.getElementById('path-detail-test')?.addEventListener('click', testPathPreview);
        document.getElementById('path-detail-copy-all')?.addEventListener('click', copyAllPathOutputUrls);
        document.getElementById('path-detail-edit')?.addEventListener('click', () => {
                if (currentPathName && pathDetailState?.configAvailable) window.editPath(currentPathName);
        });
        document.getElementById('path-detail-delete')?.addEventListener('click', deleteCurrentPath);
        document.getElementById('path-detail-copy-source')?.addEventListener('click', copyPathSource);
        document.getElementById('path-detail-video')?.addEventListener('playing', () => {
            document.getElementById('path-detail-preview-status').textContent = 'Stream playback started.';
            document.getElementById('path-detail-live').classList.remove('hidden');
            document.getElementById('path-detail-preview-empty').classList.add('hidden');
        });
        document.getElementById('path-detail-video')?.addEventListener('error', event => {
            if (!event.currentTarget.currentSrc) return;
            const webRtc = pathDetailState?.outputUrls.find(output => output.label === 'WebRTC');
            if (webRtc) {
                openPathWebRtcPreview(webRtc);
            } else {
                setPathPreviewMessage('The HLS stream could not be loaded. Check stream readiness and network access.');
            }
        });
    }
    if (page === 'config-global') {
        document.getElementById('config-global-save-form')?.addEventListener('click', saveConfigGlobalForm);
        document.getElementById('config-global-save-json')?.addEventListener('click', saveConfigGlobalJSON);
        document.getElementById('config-global-reset')?.addEventListener('click', resetConfigGlobal);
    }
    if (page === 'config-defaults') {
        document.getElementById('config-defaults-form')?.addEventListener('submit', (event) => {
            event.preventDefault();
            saveConfigDefaults();
        });
        document.getElementById('config-defaults-reset')?.addEventListener('click', resetConfigDefaults);
        document.getElementById('config-defaults-nav')?.addEventListener('click', (event) => {
            const button = event.target.closest?.('[data-section-target]');
            if (!button) return;
            document.getElementById(button.dataset.sectionTarget)?.scrollIntoView({
                behavior: 'smooth',
                block: 'start',
            });
        });
        document.getElementById('config-defaults-form')?.addEventListener('click', (event) => {
            const addButton = event.target.closest?.('[data-array-add]');
            if (addButton) {
                addPathDefaultsArrayItem(addButton.dataset.arrayAdd);
                return;
            }

            const removeButton = event.target.closest?.('[data-array-remove]');
            if (removeButton) {
                const item = removeButton.closest('[data-array-item]');
                const itemsContainer = item?.parentElement;
                item?.remove();
                itemsContainer?.querySelectorAll('[data-array-item]').forEach((arrayItem, index) => {
                    arrayItem.querySelector('[data-array-item-label]').textContent = `Item ${index + 1}`;
                });
                document.getElementById('config-defaults-form').dataset.dirty = 'true';
            }
        });
        document.getElementById('config-defaults-form')?.addEventListener('input', (event) => {
            if (event.target.matches('[data-config-key], [data-array-field], [data-array-value]')) {
                event.currentTarget.dataset.dirty = 'true';
            }
        });
        document.getElementById('config-defaults-form')?.addEventListener('change', (event) => {
            if (event.target.matches('[data-array-field], [data-array-value]')) {
                event.currentTarget.dataset.dirty = 'true';
            }
        });
    }
    if (page === 'runtime-logs') {
        document.getElementById('logs-search')?.addEventListener('input', () => {
            logsCurrentPage = 1;
            renderLogs(allLogs);
        });
        document.getElementById('logs-level-filter')?.addEventListener('change', () => {
            logsCurrentPage = 1;
            renderLogs(allLogs);
        });
        document.getElementById('logs-refresh')?.addEventListener('click', loadRuntimeLogs);
        document.getElementById('logs-delete-btn')?.addEventListener('click', openDeleteDropdown);
        document.querySelectorAll('#logs-delete-dropdown [data-delete-preset]')?.forEach(btn => {
            btn.addEventListener('click', () => handleDeletePreset(btn.dataset.deletePreset));
        });
        document.getElementById('logs-custom-modal-close')?.addEventListener('click', closeCustomPeriodModal);
        document.getElementById('logs-custom-modal-cancel')?.addEventListener('click', closeCustomPeriodModal);
        document.getElementById('logs-custom-modal-confirm')?.addEventListener('click', confirmCustomPeriodDelete);

        document.addEventListener('click', (e) => {
            const menu = document.getElementById('logs-delete-menu');
            if (menu && !menu.contains(e.target)) closeDeleteDropdown();
        });
    }
    if (page === 'config-paths') {
        document.getElementById('config-paths-add-btn')?.addEventListener('click', () => openConfigPathModal());
        document.getElementById('config-paths-search')?.addEventListener('input', () => {
            configPathsCurrentPage = 1;
            renderConfigPaths(allConfigPaths);
        });
        document.getElementById('config-paths-refresh')?.addEventListener('click', loadConfigPaths);
        document.getElementById('config-paths-export-btn')?.addEventListener('click', exportConfigPaths);
        document.getElementById('config-paths-prev-page')?.addEventListener('click', () => changeConfigPathsPage(-1));
        document.getElementById('config-paths-next-page')?.addEventListener('click', () => changeConfigPathsPage(1));
        initAmsImport();
    }
}

function handleHashChange() {
    const route = window.location.hash;
    if (route !== currentRoute) {
        currentRoute = route;
        navigateToPage(getPageFromHash(), getPathNameFromHash());
    }
}

// --- Page Data Loading ---

async function loadPageData(page) {
    switch (page) {
        case 'dashboard':
            await loadDashboard();
            break;
        case 'streams':
            await loadStreams();
            break;
        case 'path-detail':
            await loadPathDetail(currentPathName);
            break;
        case 'config-global':
            await loadConfigGlobal();
            break;
        case 'config-defaults':
            await loadConfigDefaults();
            break;
        case 'runtime-hls':
            await loadRuntimeHLS();
            break;
        case 'runtime-rtsp':
            await loadRuntimeRTSP();
            break;
        case 'runtime-rtmp':
            await loadRuntimeRTMP();
            break;
        case 'runtime-logs':
            await loadRuntimeLogs();
            break;
        case 'config-paths':
            await loadConfigPaths();
            break;
    }
}

function formatUptimeFromStart(started) {
    if (!started) return '-';
    const startTime = new Date(started).getTime();
    const now = Date.now();
    const diffMs = now - startTime;
    if (diffMs <= 0) return '-';
    return formatUptime(Math.floor(diffMs / 1000));
}

// --- Dashboard ---

async function loadDashboard() {
    let anySuccess = false;


    fetchSystemMetrics();


    try {
        const summary = await fetchAPI('/streams/summary');
        if (summary.success) {
            renderSummary(summary.data);
            renderPaths(summary.data.online_lists);
            anySuccess = true;
        } else {
            renderSummaryError();
        }
    } catch (e) {
        showError('streams/summary: ' + e.message);
        renderSummaryError();
    }


    try {
        const sessions = await fetchAPI('/sessions');
        if (sessions.success) {
            renderDashboardSessions(sessions.data.items);
        } else {
            renderSessionsError();
        }
    } catch (e) {
        showError('sessions: ' + e.message);
        renderSessionsError();
    }


    try {
        const health = await fetchAPI('/server/health');
        if (health.success) {
            renderServerStatus(health.data);
        } else {
            renderServerStatusError();
        }
    } catch (e) {
        showError('server/health: ' + e.message);
        renderServerStatusError();
    }


    const totalPaths = document.getElementById('server-total-paths');
    try {
        const paths = await fetchAPI('/paths');
        if (paths.success) {
            const pathCount = (paths.data.items || []).length;
            totalPaths.textContent = formatNumber(pathCount);
        } else {
            totalPaths.textContent = '-';
        }
    } catch (e) {
        showError('paths: ' + e.message);
        totalPaths.textContent = '-';
    }




    setConnectionStatus(anySuccess);
}

function renderSummary(data) {
    document.getElementById('stat-total').textContent = formatNumber(data.total);
    document.getElementById('stat-online').textContent = formatNumber(data.online);
    document.getElementById('stat-offline').textContent = formatNumber(data.offline);
    document.getElementById('stat-viewers').textContent = formatNumber(data.total_readers);
    document.getElementById('online-count').textContent = formatNumber(data.online) + " Online"


    document.getElementById('server-traffic').textContent =
        `${formatBytes(data.total_bytes_received)} / ${formatBytes(data.total_bytes_sent)}`;
    document.getElementById('server-total-readers').textContent = formatNumber(data.total_readers);
    document.getElementById('server-active-paths').textContent = formatNumber(data.online);
}

function renderSummaryError() {
    document.getElementById('stat-total').textContent = '-';
    document.getElementById('stat-online').textContent = '-';
    document.getElementById('stat-offline').textContent = '-';
    document.getElementById('stat-viewers').textContent = '-';
    document.getElementById('server-traffic').textContent = '- / -';
    document.getElementById('server-total-readers').textContent = '-';
    document.getElementById('server-active-paths').textContent = '-';
}

function renderStreamsError() {
    const tbody = document.getElementById('streams-table-body');
    const countEl = document.getElementById('streams-count');
    countEl.textContent = 'Error';
    tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-12 text-center text-red-600">Failed to load streams</td></tr>';
}

function renderSessionsError() {
    const tbody = document.getElementById('sessions-table-body');
    const countEl = document.getElementById('sessions-count');
    countEl.textContent = 'Error';
    tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-12 text-center text-red-600">Failed to load sessions</td></tr>';
}

function renderServerStatusError() {
    const statusEl = document.getElementById('server-connection-status');
    statusEl.textContent = 'Error';
    statusEl.className = 'px-3 py-1 text-sm rounded-lg bg-red-100 text-red-800';
    document.getElementById('server-version').textContent = '-';
    document.getElementById('server-uptime').textContent = '-';
}

function renderServerStatus(health) {
    const connected = health.connected === true;
    const statusEl = document.getElementById('server-connection-status');
    statusEl.textContent = connected ? 'Connected' : 'Disconnected';
    statusEl.className = `px-3 py-1 text-sm rounded-lg ${connected ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}`;

    document.getElementById('server-version').textContent = health.version || 'unknown';

    document.getElementById('server-uptime').textContent = formatUptimeFromStart(health.started);
}

function renderPaths(paths) {
    const tbody = document.getElementById('paths-table-body');

    if (paths.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="px-6 py-12 text-center text-gray-500">No paths found</td></tr>';
        return;
    }
    tbody.innerHTML = paths.map(p => {
        const tracks = Array.isArray(p.tracks) ? p.tracks : [];
        const trackInfo = tracks.length > 0 ? tracks.join(', ') : '-';
        return `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(p.name)}</td>
            <td class="px-6 py-4 text-sm text-gray-600">${escapeHtml(trackInfo)}</td>
            <td class="px-6 py-4 text-sm text-gray-600">${escapeHtml(p.source.type)}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(p.bytesReceived)}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(p.bytesSent)}</td>
            <td class="px-6 py-4 text-sm">
                <button class="btn-icon btn-primary" data-path-action="detail" data-path-name="${escapeHtml(p.name)}">Detail</button>
            </td>
        </tr>
    `}).join('');
}

function renderStreams(streams) {
    const tbody = document.getElementById('streams-table-body');
    const countEl = document.getElementById('streams-count');
    const searchTerm = document.getElementById('streams-search')?.value.toLowerCase() || '';

    const filtered = streams.filter(s => {
        const name = (s.name || '').toLowerCase();
        const protocol = (s.type || '').toLowerCase();
        const remoteAddr = (s.remote_addr || '').toLowerCase();
        return name.includes(searchTerm) || protocol.includes(searchTerm) || remoteAddr.includes(searchTerm);
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / STREAMS_PER_PAGE));
    if (streamsCurrentPage > totalPages) {
        streamsCurrentPage = totalPages;
    }

    const startIdx = (streamsCurrentPage - 1) * STREAMS_PER_PAGE;
    const endIdx = startIdx + STREAMS_PER_PAGE;
    const pageStreams = filtered.slice(startIdx, endIdx);

    if (pageStreams.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-12 text-center text-gray-500">No active streams</td></tr>';
        if (countEl) countEl.textContent = '0 streams';
        updateStreamsPaginationControls(0, 0);
        return;
    }

    tbody.innerHTML = pageStreams.map(s => {
        return `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 font-mono text-sm">${escapeHtml(s.name)}</td>
                <td class="px-6 py-4">
                    <span class="status-badge ${s.state == 'publish' ? 'status-online' : 'status-offline'}">
                        ${s.state}
                    </span>
                </td>
                <td class="px-6 py-4 text-sm text-gray-600 max-w-xs truncate">
                    ${escapeHtml(s.type)}
                </td>
                <td class="px-6 py-4 text-sm">${escapeHtml(s.remote_addr)}</td>
                <td class="px-6 py-4 text-sm font-mono">${formatBytes(s.bytes_received)}</td>
                <td class="px-6 py-4 text-sm font-mono">${formatBytes(s.bytes_sent)}</td>
                <td class="px-6 py-4 text-sm">
                    <button class="btn-icon btn-primary" data-path-action="detail" data-path-name="${escapeHtml(s.name)}">Detail</button>
                </td>
            </tr>
        `;
    }).join('');
    countEl.textContent = `${filtered.length} stream${filtered.length !== 1 ? 's' : ''} (showing ${pageStreams.length})`;
    updateStreamsPaginationControls(filtered.length, totalPages);
}

function updateStreamsPaginationControls(totalFiltered, totalPages) {
    const prevBtn = document.getElementById('streams-prev-page');
    const nextBtn = document.getElementById('streams-next-page');
    const pageInfo = document.getElementById('streams-page-info');

    if (!prevBtn || !nextBtn || !pageInfo) return;

    prevBtn.disabled = streamsCurrentPage <= 1;
    nextBtn.disabled = streamsCurrentPage >= totalPages;
    pageInfo.textContent = totalFiltered === 0 ? 'Page 0 of 0' : `Page ${streamsCurrentPage} of ${totalPages}`;
}

function changeStreamsPage(delta) {
    const searchTerm = document.getElementById('streams-search')?.value.toLowerCase() || '';

    const filtered = allStreams.filter(s => {
        const name = (s.name || '').toLowerCase();
        const protocol = (s.type || '').toLowerCase();
        const remoteAddr = (s.remote_addr || '').toLowerCase();
        return name.includes(searchTerm) || protocol.includes(searchTerm) || remoteAddr.includes(searchTerm);
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / STREAMS_PER_PAGE));
    const newPage = Math.max(1, Math.min(totalPages, streamsCurrentPage + delta));

    if (newPage !== streamsCurrentPage) {
        streamsCurrentPage = newPage;
        renderStreams(allStreams);
    }
}

function renderDashboardSessions(sessions) {
    const tbody = document.getElementById('sessions-table-body');
    const countEl = document.getElementById('sessions-count');

    countEl.textContent = `${sessions.length} session${sessions.length !== 1 ? 's' : ''}`;

    if (sessions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-12 text-center text-gray-500">No active sessions</td></tr>';
        return;
    }

    tbody.innerHTML = sessions.map(s => `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(s.id)}</td>
            <td class="px-6 py-4 text-sm">
                <span class="status-badge status-online">${escapeHtml(s.type.toUpperCase())}</span>
            </td>
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(s.path)}</td>
            <td class="px-6 py-4 text-sm text-gray-600">${escapeHtml(s.remote_addr)}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(s.bytes_received)}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(s.bytes_sent)}</td>
            <td class="px-6 py-4">
                <button onclick="kickSession('${escapeHtml(s.type)}', '${escapeHtml(s.id)}')" class="btn-icon btn-danger">Kick</button>
            </td>
        </tr>
    `).join('');
}

function renderServerConfig(config) {

    const paths = config.paths || {};
    const pathCount = Object.keys(paths).length;



    document.getElementById('server-total-paths').textContent = pathCount;
}

// --- Paths ---

let allPaths = [];
let allStreams = [];
let streamsCurrentPage = 1;
const STREAMS_PER_PAGE = 10;

async function loadStreams() {
    try {
        const paths = await fetchAPI('/streams');
        if (paths.success) {
            allPaths = paths.data.items || [];
            allStreams = paths.data.items || [];
            streamsCurrentPage = 1;
            renderStreams(allStreams);
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}

// --- Path Detail ---

let pathDetailState = null;
let pathDetailLoadId = 0;

async function loadPathDetail(pathName) {
    const errorEl = document.getElementById('path-detail-error');
    const contentEl = document.getElementById('path-detail-content');
    if (!pathName) {
        contentEl?.classList.add('hidden');
        errorEl.textContent = 'A path name is required to open this page.';
        errorEl.classList.remove('hidden');
        return;
    }

    const loadId = ++pathDetailLoadId;
    document.getElementById('path-detail-summary-name').textContent = pathName;
    errorEl.classList.add('hidden');
    contentEl.classList.remove('hidden');
    pathDetailState = null;

    const [configResult, runtimeResult, serverConfigResult] = await Promise.allSettled([
        fetchAPI(`/paths/${encodeURIComponent(pathName)}`),
        fetchAPI(`/streams/${encodeURIComponent(pathName)}`),
        fetchAPI('/server/config'),
    ]);
    if (loadId !== pathDetailLoadId || currentPage !== 'path-detail' || currentPathName !== pathName) return;

    const configNotFound = configResult.status === 'rejected' && configResult.reason.status === 404;
    const runtimeAvailable = runtimeResult.status === 'fulfilled' && runtimeResult.value.success;
    const configAvailable = configResult.status === 'fulfilled' && configResult.value.success;

    if (!runtimeAvailable && !configAvailable) {
        contentEl.classList.add('hidden');
        errorEl.textContent = runtimeResult.status === 'rejected'
            ? `Unable to load runtime path: ${runtimeResult.reason.message}`
            : configResult.status === 'rejected'
                ? `Unable to load path configuration: ${configResult.reason.message}`
                : runtimeResult.value.message || 'MediaMTX did not return this path.';
        errorEl.classList.remove('hidden');
        setConnectionStatus(false);
        return;
    }

    const config = configAvailable ? configResult.value.data : {};
    if (!configAvailable && configResult.status === 'rejected' && !configNotFound) {
        showError(`path configuration: ${configResult.reason.message}`);
    } else if (!configAvailable && configResult.status === 'fulfilled' && !configResult.value.success) {
        showError(`path configuration: ${configResult.value.message || 'MediaMTX returned an unsuccessful configuration response'}`);
    }

    pathDetailState = {
        name: pathName,
        config: { ...config, name: config.name || pathName },
        configAvailable,
        runtimeAvailable,
        runtime: runtimeAvailable ? runtimeResult.value.data : null,
        runtimeError: runtimeAvailable
            ? null
            : runtimeResult.status === 'rejected'
                ? runtimeResult.reason.message
                : runtimeResult.value.message || 'MediaMTX did not return this runtime path.',
        serverConfig: serverConfigResult.status === 'fulfilled' && serverConfigResult.value.success
            ? serverConfigResult.value.data
            : null,
        outputUrls: [],
    };
    renderPathDetail();
    refreshPathViewers();
    setConnectionStatus(true);
    if (!runtimeAvailable) {
        showPathNotice(`Configuration is available, but runtime status could not be loaded: ${pathDetailState.runtimeError}`, 'warning');
    } else if (!configAvailable) {
        showPathNotice(configNotFound
            ? 'This path exists at runtime but has no specific path configuration. Configuration editing and deletion are unavailable.'
            : 'Runtime details are available, but its path configuration could not be loaded.', 'warning');
    } else if (serverConfigResult.status === 'rejected' || !serverConfigResult.value.success) {
        const message = serverConfigResult.status === 'rejected'
            ? serverConfigResult.reason.message
            : serverConfigResult.value.message || 'MediaMTX returned an unsuccessful configuration response';
        showPathNotice(`Server protocol configuration is unavailable: ${message}`, 'warning');
    }
}

function getPathRuntimeStatus(runtime, configAvailable = true, runtimeAvailable = true) {
    if (!runtime) {
        if (!runtimeAvailable) {
            return { label: 'Runtime unavailable', note: 'The path configuration is available, but MediaMTX runtime status could not be loaded.', online: false };
        }
        return {
            label: configAvailable ? 'Configured · inactive' : 'Not found',
            note: configAvailable
                ? 'Configuration exists, but this path is not currently in the runtime list.'
                : 'No path configuration or runtime entry is available.',
            online: false,
        };
    }
    if (runtime.ready) {
        return { label: 'Online', note: runtime.available ? 'Online and available to readers.' : 'Runtime path is online.', online: true };
    }
    return { label: 'Not ready', note: 'The path is configured but is not currently ready.', online: false };
}

function getPathSource(config, runtime) {
    const source = config.source;
    const runtimeSource = runtime?.source;
    const runtimeSourceType = typeof runtimeSource?.type === 'string'
        ? runtimeSource.type
            .replace(/(source|session)$/i, '')
            .replace(/^rtsp$/i, 'RTSP')
            .replace(/^rtmp$/i, 'RTMP')
            .replace(/^hls$/i, 'HLS')
            .replace(/^webrtc$/i, 'WebRTC')
        : null;
    const configSourceType = typeof source === 'object' && source !== null
        ? source.type?.replace(/source$/i, '')
        : null;
    let type = 'Publisher';
    let url = null;
    let note = 'MediaMTX is waiting for a publisher on this path.';

    if (typeof source === 'string' && source.toLowerCase() === 'redirect') {
        type = 'Redirect';
        url = config.sourceRedirect || null;
        note = url ? 'Readers are redirected to the configured target.' : 'No redirect target is configured.';
    } else if (typeof source === 'string' && source && source.toLowerCase() !== 'publisher') {
        const protocol = source.match(/^([a-z][a-z0-9+.-]*):\/\//i)?.[1];
        type = protocol ? protocol.toUpperCase() : 'Configured source';
        url = source;
        note = 'This source URL is configured as the upstream input to MediaMTX.';
    } else if (runtimeSourceType || configSourceType) {
        type = runtimeSourceType || configSourceType;
        note = 'Source type is reported by MediaMTX runtime.';
    }

    const runtimeSourceId = typeof runtimeSource?.id === 'string' ? runtimeSource.id : null;
    const displayValue = url || (runtimeSourceId ? `Runtime source ID: ${runtimeSourceId}` : null);
    if (!url && runtimeSourceId) {
        note = 'The runtime API provides a source identifier, but not the configured source URL.';
    }

    return { type, url, runtimeSourceId, displayValue, note };
}

function encodePathSegments(pathName) {
    return pathName.split('/').map(segment => encodeURIComponent(segment)).join('/');
}

function getListenerUrl(address, scheme, pathName, suffix = '') {
    if (typeof address !== 'string' || !address.trim()) return null;
    const match = address.trim().match(/^(?:\[([^\]]+)\]|([^:]*)):(\d+)$/);
    if (!match) return null;

    const bindHost = match[1] || match[2] || '';
    const port = match[3];
    const normalizedBindHost = bindHost.toLowerCase();
    const isWildcardOrLocal = !bindHost ||
        ['0.0.0.0', '::', '::1', 'localhost', '127.0.0.1'].includes(normalizedBindHost) ||
        normalizedBindHost.startsWith('127.');
    const host = isWildcardOrLocal ? window.location.hostname : bindHost;
    if (!host) return null;

    const formattedHost = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host;
    return `${scheme}://${formattedHost}:${port}/${encodePathSegments(pathName)}${suffix}`;
}

function getPathOutputUrls(serverConfig, pathName) {
    if (!serverConfig) return [];
    const outputs = [];
    const addOutput = (label, url, vlcCompatible = false) => {
        if (url) outputs.push({ label, url, vlcCompatible });
    };

    if (!serverConfig.rtspEncryption || serverConfig.rtspEncryption !== 'strict') {
        addOutput('RTSP', getListenerUrl(serverConfig.rtspAddress, 'rtsp', pathName), true);
    }

    const rtmpEncryption = serverConfig.rtmpEncryption || 'no';
    if (serverConfig.rtmp === true && rtmpEncryption !== 'strict') {
        addOutput('RTMP', getListenerUrl(serverConfig.rtmpAddress, 'rtmp', pathName), true);
    }

    if (serverConfig.hls === true) {
        const scheme = serverConfig.hlsEncryption === true ? 'https' : 'http';
        addOutput('HLS', getListenerUrl(serverConfig.hlsAddress, scheme, pathName, '/index.m3u8'), true);
    }

    if (serverConfig.webrtc === true) {
        const scheme = serverConfig.webrtcEncryption === true ? 'https' : 'http';
        addOutput('WebRTC', getListenerUrl(serverConfig.webrtcAddress, scheme, pathName));
    }
    return outputs;
}

function renderPathDetail() {
    if (!pathDetailState) return;
    const { name, config, configAvailable, runtime, serverConfig } = pathDetailState;
    const status = getPathRuntimeStatus(runtime, configAvailable, pathDetailState.runtimeAvailable);
    const source = getPathSource(config, runtime);
    const outputs = getPathOutputUrls(serverConfig, name);
    pathDetailState.outputUrls = outputs;

    document.getElementById('path-detail-summary-name').textContent = name;
    document.getElementById('path-detail-status').textContent = status.label;
    document.getElementById('path-detail-status').className = `status-badge ${status.online ? 'status-online' : 'status-offline'}`;
    document.getElementById('path-detail-summary-status').textContent = status.label;
    document.getElementById('path-detail-summary-status').className = `mt-2 text-lg font-semibold ${status.online ? 'text-green-700' : 'text-gray-900'}`;
    document.getElementById('path-detail-runtime-note').textContent = status.note;
    document.getElementById('path-detail-summary-source').textContent = source.type;
    document.getElementById('path-detail-source-type').textContent = source.type;
    document.getElementById('path-detail-source-url').textContent = source.displayValue || 'Not provided';
    document.getElementById('path-detail-source-note').textContent = containsMaskedCredentials(source.url)
        ? 'Credentials in this source URL are masked and are not copied as secrets.'
        : source.note;
    document.getElementById('path-detail-copy-source').disabled = !source.url;
    document.getElementById('path-detail-edit').disabled = !configAvailable;
    document.getElementById('path-detail-delete').disabled = !configAvailable;
    document.getElementById('path-detail-edit').title = configAvailable
        ? ''
        : 'No specific path configuration is available to edit.';
    document.getElementById('path-detail-delete').title = configAvailable
        ? ''
        : 'No specific path configuration is available to delete.';
    document.getElementById('path-detail-copy-all').disabled = outputs.length === 0;
    renderPathOutputRows(outputs);
}

function renderPathOutputRows(outputs) {
    const container = document.getElementById('path-detail-outputs');
    const protocols = ['RTSP', 'RTMP', 'HLS', 'WebRTC'];
    const configured = new Map(outputs.map(output => [output.label, output]));

    container.innerHTML = protocols.map(protocol => {
        const output = configured.get(protocol);
        return `
            <div class="min-w-0 rounded-lg border border-gray-200 p-4">
                <div class="flex flex-wrap items-start justify-between gap-3">
                    <div class="min-w-0 flex-1">
                        <div class="flex items-center gap-2">
                            <span class="text-sm font-semibold text-gray-900">${protocol}</span>
                            <span class="rounded-full ${output ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500'} px-2 py-0.5 text-xs">${output ? 'Configured' : 'Not available'}</span>
                        </div>
                        <p class="mt-2 break-all font-mono text-xs ${output ? 'text-gray-700' : 'text-gray-400'}">${output ? escapeHtml(output.url) : 'Listener disabled or address not configured'}</p>
                    </div>
                    ${output ? `<button class="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50" data-copy-output="${escapeHtml(output.label)}">Copy</button>` : ''}
                </div>
            </div>
        `;
    }).join('');

    container.querySelectorAll('[data-copy-output]').forEach(button => {
        button.addEventListener('click', () => copyPathOutputUrl(button.dataset.copyOutput));
    });
}

async function refreshPathRuntime() {
    if (!pathDetailState) return;
    const state = pathDetailState;
    refreshPathViewers(state);
    try {
        const response = await fetchAPI(`/streams/${encodeURIComponent(state.name)}`);
        if (!response.success) throw new Error(response.message || 'Failed to load runtime path');
        if (pathDetailState !== state || currentPage !== 'path-detail') return;
        state.runtime = response.data;
        state.runtimeAvailable = true;
        state.runtimeError = null;
        const status = getPathRuntimeStatus(state.runtime, state.configAvailable, true);
        document.getElementById('path-detail-status').textContent = status.label;
        document.getElementById('path-detail-status').className = `status-badge ${status.online ? 'status-online' : 'status-offline'}`;
        document.getElementById('path-detail-summary-status').textContent = status.label;
        document.getElementById('path-detail-summary-status').className = `mt-2 text-lg font-semibold ${status.online ? 'text-green-700' : 'text-gray-900'}`;
        document.getElementById('path-detail-runtime-note').textContent = status.note;
        setConnectionStatus(true);
    } catch (error) {
        if (pathDetailState !== state || currentPage !== 'path-detail') return;
        showError(`path runtime: ${error.message}`);
        setConnectionStatus(false);
    }
}

async function refreshPathViewers(state = pathDetailState) {
    if (!state || state.viewerRefreshInFlight || currentPage !== 'path-detail') return;
    state.viewerRefreshInFlight = true;
    try {
        const response = await fetchAPI(`/streams/${encodePathSegments(state.name)}/viewers`);
        if (!response.success) throw new Error(response.message || 'Failed to load viewer count');
        if (pathDetailState !== state || currentPage !== 'path-detail') return;

        const data = response.data || {};
        const count = Number.isFinite(data.viewer_count) ? data.viewer_count : 0;
        document.getElementById('path-detail-viewer-count').textContent = formatNumber(count);
        document.getElementById('path-detail-viewer-status').textContent =
            data.status === 'unavailable'
                ? 'Statistik sementara tidak tersedia.'
                : data.status === 'inactive'
                    ? 'Stream belum aktif.'
                    : 'Diperbarui otomatis setiap 5 detik.';
        if (data.status !== 'unavailable' && Array.isArray(data.viewer_history)) {
            renderViewerChart(data.viewer_history);
        }
    } catch (error) {
        if (pathDetailState !== state || currentPage !== 'path-detail') return;
        document.getElementById('path-detail-viewer-count').textContent = '0';
        document.getElementById('path-detail-viewer-status').textContent = 'Statistik sementara tidak tersedia.';
        console.warn(`Stream viewer count: ${error.message}`);
    } finally {
        state.viewerRefreshInFlight = false;
    }
}

function renderViewerChart(data) {
    const svg = document.getElementById('path-detail-viewer-chart');
    if (!svg || !Array.isArray(data) || data.length === 0) return;

    const width = svg.clientWidth || 600;
    const height = 160;
    const left = 42;
    const right = 8;
    const top = 10;
    const bottom = 10;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const maxValue = Math.max(...data, 1);
    const ticks = [...new Set([Math.ceil(maxValue), Math.floor(Math.ceil(maxValue) / 2), 0])];
    const points = data.map((value, index) => {
        const x = left + (index / Math.max(data.length - 1, 1)) * plotWidth;
        const y = top + plotHeight - (value / Math.ceil(maxValue)) * plotHeight;
        return { x, y };
    });
    const linePath = `M${points.map(point => `${point.x},${point.y}`).join(' L')}`;
    const areaPath = `${linePath} L${points[points.length - 1].x},${top + plotHeight} L${points[0].x},${top + plotHeight} Z`;

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.innerHTML = `
        <defs>
            <linearGradient id="viewer-chart-gradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#2563eb" stop-opacity="0.25"/>
                <stop offset="100%" stop-color="#2563eb" stop-opacity="0"/>
            </linearGradient>
        </defs>
        ${ticks.map(value => {
            const y = top + plotHeight - (value / Math.ceil(maxValue)) * plotHeight;
            return `
                <line x1="${left}" y1="${y}" x2="${width - right}" y2="${y}" stroke="#e5e7eb" stroke-width="1"/>
                <text x="${left - 8}" y="${y + 4}" text-anchor="end" fill="#6b7280" font-size="11">${formatNumber(value)}</text>
            `;
        }).join('')}
        <path d="${areaPath}" fill="url(#viewer-chart-gradient)"/>
        <path d="${linePath}" fill="none" stroke="#2563eb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="${points[points.length - 1].x}" cy="${points[points.length - 1].y}" r="3" fill="#2563eb"/>
    `;
}

function showPathNotice(message, type = 'success') {
    const notice = document.getElementById('path-detail-notice');
    if (!notice) return;
    notice.textContent = message;
    notice.className = `mt-3 rounded-lg border px-4 py-3 text-sm ${
        type === 'warning'
            ? 'border-amber-200 bg-amber-50 text-amber-800'
            : 'border-green-200 bg-green-50 text-green-800'
    }`;
}

async function copyPathText(text, label) {
    try {
        await navigator.clipboard.writeText(text);
        showPathNotice(`${label} copied to clipboard.`);
    } catch (error) {
        showPathNotice(`Could not copy ${label.toLowerCase()}: ${error.message}`, 'warning');
    }
}

function copyPathSource() {
    const source = getPathSource(pathDetailState.config, pathDetailState.runtime);
    if (source.url) copyPathText(source.url, containsMaskedCredentials(source.url) ? 'Masked source URL' : 'Source URL');
}

function copyPathOutputUrl(label) {
    const output = pathDetailState?.outputUrls.find(item => item.label === label);
    if (output) copyPathText(output.url, `${label} URL`);
}

function copyAllPathOutputUrls() {
    const outputs = pathDetailState?.outputUrls || [];
    if (outputs.length) {
        copyPathText(outputs.map(output => `${output.label}: ${output.url}`).join('\n'), 'Available output URLs');
    }
}

function setPathPreviewMessage(message) {
    const video = document.getElementById('path-detail-video');
    const webRtcFrame = document.getElementById('path-detail-webrtc');
    if (pathHlsPlayer) {
        pathHlsPlayer.destroy();
        pathHlsPlayer = null;
    }
    video.pause();
    video.removeAttribute('src');
    video.load();
    video.classList.add('hidden');
    webRtcFrame.src = 'about:blank';
    webRtcFrame.classList.add('hidden');
    document.getElementById('path-detail-preview-empty').classList.remove('hidden');
    document.getElementById('path-detail-preview-status').textContent = message;
    document.getElementById('path-detail-live').classList.add('hidden');
}

function openPathWebRtcPreview(output) {
    const video = document.getElementById('path-detail-video');
    const webRtcFrame = document.getElementById('path-detail-webrtc');
    if (pathHlsPlayer) {
        pathHlsPlayer.destroy();
        pathHlsPlayer = null;
    }
    video.pause();
    video.removeAttribute('src');
    video.load();
    video.classList.add('hidden');
    document.getElementById('path-detail-preview-empty').classList.add('hidden');
    webRtcFrame.src = output.url;
    webRtcFrame.classList.remove('hidden');
    document.getElementById('path-detail-preview-status').textContent =
        'Opening the MediaMTX WebRTC player. Playback status is shown by the embedded player.';
    document.getElementById('path-detail-live').classList.add('hidden');
}

async function testPathPreview() {
    document.getElementById('path-detail-preview').scrollIntoView({ behavior: 'smooth', block: 'center' });
    const hls = pathDetailState?.outputUrls.find(output => output.label === 'HLS');
    const webRtc = pathDetailState?.outputUrls.find(output => output.label === 'WebRTC');
    const video = document.getElementById('path-detail-video');
    const webRtcFrame = document.getElementById('path-detail-webrtc');
    if (pathHlsPlayer) {
        pathHlsPlayer.destroy();
        pathHlsPlayer = null;
    }
    video.pause();
    video.removeAttribute('src');
    video.load();
    video.classList.add('hidden');
    webRtcFrame.src = 'about:blank';
    webRtcFrame.classList.add('hidden');
    document.getElementById('path-detail-live').classList.add('hidden');
    const nativeHls = Boolean(video.canPlayType('application/vnd.apple.mpegurl'));
    const hlsJsAvailable = Boolean(window.Hls && window.Hls.isSupported());

    if (!hls || (!nativeHls && !hlsJsAvailable)) {
        if (webRtc) {
            openPathWebRtcPreview(webRtc);
            return;
        }
        setPathPreviewMessage(hls
            ? 'This browser has no supported HLS player. RTSP/RTMP cannot be played directly in a browser video element.'
            : 'Preview unavailable: HLS and WebRTC are not enabled or their listener addresses are not configured.');
        return;
    }

    document.getElementById('path-detail-preview-status').textContent = 'Loading HLS stream...';
    document.getElementById('path-detail-preview-empty').classList.add('hidden');
    video.classList.remove('hidden');
    if (nativeHls) {
        video.src = hls.url;
        video.load();
        try {
            await video.play();
        } catch (error) {
            setPathPreviewMessage(`Unable to start playback: ${error.message}`);
        }
        return;
    }

    pathHlsPlayer = new window.Hls();
    pathHlsPlayer.loadSource(hls.url);
    pathHlsPlayer.attachMedia(video);
    pathHlsPlayer.on(window.Hls.Events.MANIFEST_PARSED, async () => {
        try {
            await video.play();
        } catch (error) {
            setPathPreviewMessage(`Unable to start playback: ${error.message}`);
        }
    });
    pathHlsPlayer.on(window.Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
            if (webRtc) {
                openPathWebRtcPreview(webRtc);
            } else {
                setPathPreviewMessage('The HLS player could not load this stream. Check stream readiness and network access.');
            }
        }
    });
}

async function deleteCurrentPath() {
    if (!pathDetailState?.configAvailable || !confirm(`Delete path "${pathDetailState.name}"?`)) return;
    try {
        const response = await fetchAPI(`/paths/${encodeURIComponent(pathDetailState.name)}`, { method: 'DELETE' });
        if (!response.success) throw new Error(response.message || 'MediaMTX did not confirm path deletion');
        window.location.hash = '#streams';
    } catch (error) {
        showPathNotice(`Failed to delete path: ${error.message}`, 'warning');
    }
}

// --- Path Modal (Add/Edit) ---

let editingPathName = null;

function openPathModal(path = null) {
    const modal = document.getElementById('add-path-modal');
    const form = document.getElementById('add-path-form');
    const title = document.getElementById('path-modal-title');
    const submitBtn = document.getElementById('path-submit-btn');

    form.reset();
    editingPathName = null;


    updateSourceTypeFields('publisher');

    if (path) {
        title.textContent = 'Edit Path';
        submitBtn.textContent = 'Save Changes';
        editingPathName = path.name;

        const nameInput = document.querySelector('input[name="name"]');
        nameInput.value = path.name;
        nameInput.disabled = true;


        let sourceType = 'publisher';
        if (path.source_redirect) {
            sourceType = 'redirect';
        } else if (path.source) {
            sourceType = 'url';
        }

        document.getElementById('path-source-type').value = sourceType;
        updateSourceTypeFields(sourceType);


        if (path.source) {

            const sourceInput = document.querySelector('input[name="source"]');
            if (!path.source.includes(':***@')) {
                sourceInput.value = path.source;
            }
        }
        if (path.source_redirect) {
            document.querySelector('input[name="source_redirect"]').value = path.source_redirect;
        }
        document.querySelector('input[name="source_on_demand"]').checked = path.source_on_demand !== false;
        if (path.source_on_demand_start_timeout) {
            document.querySelector('input[name="source_on_demand_start_timeout"]').value = path.source_on_demand_start_timeout;
        }
        if (path.source_on_demand_close_after) {
            document.querySelector('input[name="source_on_demand_close_after"]').value = path.source_on_demand_close_after;
        }
        if (path.max_readers !== null && path.max_readers !== undefined) {
            document.querySelector('input[name="max_readers"]').value = path.max_readers;
        }
        if (path.fallback) {
            document.querySelector('input[name="fallback"]').value = path.fallback;
        }
    } else {
        title.textContent = 'Add New Path';
        submitBtn.textContent = 'Add Path';
        document.querySelector('input[name="name"]').disabled = false;
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function updateSourceTypeFields(sourceType) {
    const sourceUrlField = document.getElementById('source-url-field');
    const redirectTargetField = document.getElementById('redirect-target-field');
    const onDemandFieldset = document.getElementById('on-demand-fieldset');
    const onDemandTimeoutField = document.getElementById('on-demand-timeout-field');
    const onDemandCloseField = document.getElementById('on-demand-close-field');
    const sourceOnDemandCheckbox = document.getElementById('source_on_demand');


    if (!sourceUrlField || !redirectTargetField || !onDemandFieldset || !sourceOnDemandCheckbox) {
        return;
    }


    sourceUrlField.classList.add('hidden');
    redirectTargetField.classList.add('hidden');
    onDemandFieldset.classList.add('hidden');
    if (onDemandTimeoutField) onDemandTimeoutField.classList.add('hidden');
    if (onDemandCloseField) onDemandCloseField.classList.add('hidden');


    sourceUrlField.querySelector('input')?.removeAttribute('required');
    redirectTargetField.querySelector('input')?.removeAttribute('required');

    if (sourceType === 'url') {
        sourceUrlField.classList.remove('hidden');
        sourceUrlField.querySelector('input')?.setAttribute('required', 'true');
        onDemandFieldset.classList.remove('hidden');


        if (sourceOnDemandCheckbox.checked) {
            if (onDemandTimeoutField) onDemandTimeoutField.classList.remove('hidden');
            if (onDemandCloseField) onDemandCloseField.classList.remove('hidden');
        }
    } else if (sourceType === 'redirect') {
        redirectTargetField.classList.remove('hidden');
        redirectTargetField.querySelector('input')?.setAttribute('required', 'true');
    }

}


function initAmsImport() {
    const button = document.getElementById('import-ams-btn');
    const fileInput = document.getElementById('import-ams-file');
    if (!button || !fileInput) return;

    button.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', async () => {
        const [file] = fileInput.files;
        if (!file) return;

        try {
            const payload = JSON.parse(await file.text());
            if (!Array.isArray(payload.streams)) {
                throw new Error('Invalid AMS export: "streams" must be an array');
            }

            const appName = payload.app || '(no group)';
            if (!confirm(`Import ${payload.streams.length} stream(s) into group "${appName}"?`)) return;

            button.disabled = true;
            button.textContent = 'Importing...';
            const result = await fetchAPI('/import/ams', {
                method: 'POST',
                body: JSON.stringify(payload),
            });

            if (!result.success) throw new Error(result.message || 'Import failed');
            const data = result.data;
            const failures = data.failed ? ` ${data.failed} failed: ${data.errors.join('; ')}` : '';
            alert(`${data.imported} of ${data.total} stream(s) imported.${failures}`);
            await loadConfigPaths();
        } catch (e) {
            alert(`Unable to import AMS export: ${e.message}`);
        } finally {
            button.disabled = false;
            button.textContent = 'Import AMS';
            fileInput.value = '';
        }
    });
}

function initPathModalEvents() {
    const sourceTypeSelect = document.getElementById('path-source-type');
    const sourceOnDemandCheckbox = document.getElementById('source_on_demand');

    if (sourceTypeSelect) {
        sourceTypeSelect.addEventListener('change', (e) => {
            updateSourceTypeFields(e.target.value);
        });
    }

    if (sourceOnDemandCheckbox) {
        sourceOnDemandCheckbox.addEventListener('change', (e) => {
            const onDemandTimeoutField = document.getElementById('on-demand-timeout-field');
            const onDemandCloseField = document.getElementById('on-demand-close-field');
            if (e.target.checked) {
                onDemandTimeoutField?.classList.remove('hidden');
                onDemandCloseField?.classList.remove('hidden');
            } else {
                onDemandTimeoutField?.classList.add('hidden');
                onDemandCloseField?.classList.add('hidden');
            }
        });
    }
}

window.editPath = async function(name) {
    try {
        const response = await fetchAPI(`/paths/${encodeURIComponent(name)}`);
        if (response.success) {
            const config = response.data;
            openPathModal({
                ...config,
                source_on_demand: config.sourceOnDemand,
                source_on_demand_start_timeout: config.sourceOnDemandStartTimeout,
                source_on_demand_close_after: config.sourceOnDemandCloseAfter,
                source_redirect: config.sourceRedirect,
                max_readers: config.maxReaders,
            });
        }
    } catch (e) {
        showError(e.message);
        alert(`Failed to load path configuration: ${e.message}`);
    }
};

// --- Config Path Modal (Add/Edit) ---

let editingConfigPathName = null;

function openConfigPathModal(path = null) {

    const modal = document.getElementById('add-path-modal');
    const form = document.getElementById('add-path-form');
    const title = document.getElementById('path-modal-title');
    const submitBtn = document.getElementById('path-submit-btn');

    form.reset();
    editingConfigPathName = null;


    updateSourceTypeFields('publisher');

    if (path) {
        title.textContent = 'Edit Path Configuration';
        submitBtn.textContent = 'Save Changes';
        editingConfigPathName = path.name;

        const nameInput = document.querySelector('input[name="name"]');
        nameInput.value = path.name;
        nameInput.disabled = true;


        let sourceType = 'publisher';
        if (path.source_redirect) {
            sourceType = 'redirect';
        } else if (path.source) {
            sourceType = 'url';
        }

        document.getElementById('path-source-type').value = sourceType;
        updateSourceTypeFields(sourceType);


        if (path.source && !path.source.includes(':***@')) {
            document.querySelector('input[name="source"]').value = path.source;
        }
        if (path.source_redirect) {
            document.querySelector('input[name="source_redirect"]').value = path.source_redirect;
        }
        document.querySelector('input[name="source_on_demand"]').checked = path.source_on_demand !== false;
        if (path.source_on_demand_start_timeout) {
            document.querySelector('input[name="source_on_demand_start_timeout"]').value = path.source_on_demand_start_timeout;
        }
        if (path.source_on_demand_close_after) {
            document.querySelector('input[name="source_on_demand_close_after"]').value = path.source_on_demand_close_after;
        }
        if (path.max_readers !== null && path.max_readers !== undefined) {
            document.querySelector('input[name="max_readers"]').value = path.max_readers;
        }
        if (path.fallback) {
            document.querySelector('input[name="fallback"]').value = path.fallback;
        }
    } else {
        title.textContent = 'Add Path Configuration';
        submitBtn.textContent = 'Add Path';
        document.querySelector('input[name="name"]').disabled = false;
    }

    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

// --- Config Global ---

let originalConfig = null;
let originalDefaults = null;

function setNestedValue(obj, path, value) {
    const keys = path.split('.');
    let current = obj;
    for (let i = 0; i < keys.length - 1; i++) {
        const key = keys[i];
        if (!(key in current) || current[key] === null || typeof current[key] !== 'object') {
            current[key] = {};
        }
        current = current[key];
    }
    current[keys[keys.length - 1]] = value;
}

function getNestedValue(obj, path) {
    return path.split('.').reduce((o, k) => (o || {})[k], obj);
}

function parseFormValue(name, value) {

    if (name === 'logDestinations' || name === 'rtspTransports' || name === 'api.trustedProxies' || name === 'api.corsOrigin') {
        if (name === 'api.trustedProxies' || name === 'api.corsOrigin') {
            return value.split(',').map(s => s.trim()).filter(Boolean);
        }
        return value;
    }
    if (value === 'true') return true;
    if (value === 'false') return false;
    if (value === '' || value === null) return null;
    const num = Number(value);
    if (!isNaN(num) && value.trim() !== '') return num;
    return value;
}

async function loadConfigGlobal() {
    try {
        const res = await fetchAPI('/server/config');
        if (res.success) {
            originalConfig = res.data;


            populateConfigGlobalForm(res.data);


            document.getElementById('config-global-editor').value = JSON.stringify(res.data, null, 2);
            document.getElementById('config-global-form-status').classList.add('hidden');
            document.getElementById('config-global-json-status').classList.add('hidden');
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
        document.getElementById('config-global-editor').value = 'Failed to load configuration';
    }
}

function populateConfigGlobalForm(config) {
    const form = document.querySelector('#page-config-global');
    if (!form) return;


    const simpleFields = [
        'logLevel', 'logFormat', 'readTimeout', 'writeTimeout', 'readHeaderTimeout',
        'rtspAddress', 'rtmpAddress', 'hlsAddress', 'webrtcAddress', 'srtAddress', 'playbackAddress',
        'rtpAddress', 'rtcpAddress',
        'webrtcICEHostNAT1To1', 'webrtcICEUDPMulticastAddress', 'webrtcICEPortRange', 'webrtcAdditionalHosts',
        'srtLatency', 'srtMaxBandwidth',
        'hlsAllowOrigin', 'hlsSegmentCount', 'hlsSegmentDuration', 'hlsPartDuration'
    ];

    simpleFields.forEach(name => {
        const el = form.querySelector(`[name="${name}"]`);
        if (el) {
            const value = getNestedValue(config, name);
            if (value !== undefined && value !== null) {
                if (el.type === 'checkbox') {
                    el.checked = value;
                } else if (el.multiple) {

                } else {
                    el.value = value;
                }
            }
        }
    });


    ['logDestinations', 'rtspTransports'].forEach(name => {
        const checkboxes = form.querySelectorAll(`[name="${name}"][type="checkbox"]`);
        const value = getNestedValue(config, name);
        if (Array.isArray(value)) {
            checkboxes.forEach(cb => {
                cb.checked = value.includes(cb.value);
            });
        }
    });


    const apiFields = ['enabled', 'address', 'encryption', 'authentication', 'trustedProxies', 'corsOrigin'];
    apiFields.forEach(name => {
        const el = form.querySelector(`[name="api.${name}"]`);
        if (el) {
            const value = getNestedValue(config, `api.${name}`);
            if (value !== undefined && value !== null) {
                if (el.multiple || name === 'trustedProxies' || name === 'corsOrigin') {
                    if (Array.isArray(value)) {
                        el.value = value.join(', ');
                    } else if (typeof value === 'string') {
                        el.value = value;
                    }
                } else {
                    el.value = value;
                }
            }
        }
    });


    ['metrics.enabled', 'metrics.address', 'metrics.encryption'].forEach(name => {
        const el = form.querySelector(`[name="${name}"]`);
        if (el) {
            const value = getNestedValue(config, name);
            if (value !== undefined && value !== null) {
                el.value = value;
            }
        }
    });


    ['pprof.enabled', 'pprof.address'].forEach(name => {
        const el = form.querySelector(`[name="${name}"]`);
        if (el) {
            const value = getNestedValue(config, name);
            if (value !== undefined && value !== null) {
                el.value = value;
            }
        }
    });


    const webrtcEncEl = form.querySelector('[name="webrtcEncryption"]');
    if (webrtcEncEl) {
        const value = getNestedValue(config, 'webrtcEncryption');
        if (value !== undefined && value !== null) {
            webrtcEncEl.value = value;
        }
    }


    const srtEncEl = form.querySelector('[name="srtEncryption"]');
    if (srtEncEl) {
        const value = getNestedValue(config, 'srtEncryption');
        if (value !== undefined && value !== null) {
            srtEncEl.value = value;
        }
    }


    const hlsEncEl = form.querySelector('[name="hlsEncryption"]');
    if (hlsEncEl) {
        const value = getNestedValue(config, 'hlsEncryption');
        if (value !== undefined && value !== null) {
            hlsEncEl.value = value;
        }
    }
}

function collectConfigGlobalForm() {
    const form = document.querySelector('#page-config-global form');
    if (!form) return {};

    const formData = new FormData(form);
    const updates = {};

    for (const [name, value] of formData.entries()) {
        const parsed = parseFormValue(name, value);
        if (parsed !== null) {
            setNestedValue(updates, name, parsed);
        }
    }


    ['logDestinations', 'rtspTransports'].forEach(name => {
        const checkboxes = form.querySelectorAll(`[name="${name}"][type="checkbox"]`);
        const selected = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);

        setNestedValue(updates, name, selected);
    });


    ['api.trustedProxies', 'api.corsOrigin'].forEach(name => {
        const el = form.querySelector(`[name="${name}"]`);
        if (el && el.value.trim()) {
            setNestedValue(updates, name, el.value.split(',').map(s => s.trim()).filter(Boolean));
        }
    });

    return updates;
}

async function saveConfigGlobalForm() {
    const statusEl = document.getElementById('config-global-form-status');
    const btn = document.getElementById('config-global-save-form');

    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const updates = collectConfigGlobalForm();
        const mergedConfig = { ...originalConfig, ...updates };

        const res = await fetchAPI('/server/config', {
            method: 'PATCH',
            body: JSON.stringify(mergedConfig),
        });

        if (res.success) {
            originalConfig = res.data;
            populateConfigGlobalForm(res.data);
            document.getElementById('config-global-editor').value = JSON.stringify(res.data, null, 2);
            statusEl.textContent = 'Configuration saved successfully';
            statusEl.className = 'mt-4 text-sm text-green-600';

            setTimeout(function() {
                console.log('5. Mengeksekusi reload...');
                window.location.reload();
            }, 1500);
        } else {
            throw new Error('Failed to save');
        }
    } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
        statusEl.className = 'mt-4 text-sm text-red-600';
    } finally {
        statusEl.classList.remove('hidden');
        btn.disabled = false;
        btn.textContent = 'Save Config';
    }
}

async function saveConfigGlobalJSON() {
    const editor = document.getElementById('config-global-editor');
    const statusEl = document.getElementById('config-global-json-status');
    const btn = document.getElementById('config-global-save-json');

    btn.disabled = true;
    btn.textContent = 'Saving...';

    try {
        const config = JSON.parse(editor.value);
        const res = await fetchAPI('/server/config', {
            method: 'PATCH',
            body: JSON.stringify(config),
        });

        console.log(res);
        console.log("jajajaaj");
        if (res.success) {
            originalConfig = res.data;
            populateConfigGlobalForm(res.data);
            editor.value = JSON.stringify(res.data, null, 2);
            statusEl.textContent = 'Configuration saved successfully';
            statusEl.className = 'mt-3 text-sm text-green-600';

            console.log('Timer dimulai, reload dalam 1.5 detik...');

            setTimeout(function() {
                console.log('Mengeksekusi location.reload()...');
                window.location.reload(true);
            }, 1500);

        } else {
            throw new Error('Failed to save');
        }
    } catch (e) {
        console.log(`Error: ${e.message}`);
        statusEl.textContent = `Error: ${e.message}`;
        statusEl.className = 'mt-3 text-sm text-red-600';
    } finally {
        statusEl.classList.remove('hidden');
        btn.disabled = false;
        btn.textContent = 'Save JSON';
    }
}

function resetConfigGlobal() {
    if (originalConfig) {
        populateConfigGlobalForm(originalConfig);
        document.getElementById('config-global-editor').value = JSON.stringify(originalConfig, null, 2);
        document.getElementById('config-global-form-status').classList.add('hidden');
        document.getElementById('config-global-json-status').classList.add('hidden');
    }
}

// --- Actions ---

window.deletePath = async function(name) {
    if (!confirm(`Delete path "${name}"?`)) return;
    try {
        await fetchAPI(`/paths/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadConfigPaths(currentPage);
    } catch (e) {
        showError(e.message);
        alert(`Failed to delete: ${e.message}`);
    }
};

window.kickSession = async function(type, id) {
    if (!confirm(`Kick session ${type}/${id}?`)) return;
    try {
        await fetchAPI(`/sessions/${type}/${id}/kick`, { method: 'POST' });
        loadDashboard();
    } catch (e) {
        showError(e.message);
        alert(`Failed to kick: ${e.message}`);
    }
};

// --- Modal Handling ---

const modal = document.getElementById('add-path-modal');
const form = document.getElementById('add-path-form');


document.getElementById('cancel-path-btn')?.addEventListener('click', () => {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
});

form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const name = fd.get('name');
    const sourceType = fd.get('source_type');


    const payload = {
        name,
        source_type: sourceType,
    };

    if (sourceType === 'url') {
        const source = fd.get('source');
        if (!source) {
            alert('Source URL is required for URL Source type');
            return;
        }
        payload.source = source;
        payload.sourceOnDemand = fd.get('source_on_demand') === 'on';
        if (payload.sourceOnDemand) {
            const startTimeout = fd.get('source_on_demand_start_timeout');
            const closeAfter = fd.get('source_on_demand_close_after');
            if (startTimeout) payload.sourceOnDemandStartTimeout = startTimeout;
            if (closeAfter) payload.sourceOnDemandCloseAfter = closeAfter;
        }
    } else if (sourceType === 'redirect') {
        const redirectTarget = fd.get('source_redirect');
        if (!redirectTarget) {
            alert('Redirect target is required for Redirect type');
            return;
        }
        payload.sourceRedirect = redirectTarget;
    }



    const maxReaders = fd.get('max_readers');
    if (maxReaders !== '' && maxReaders !== null) {
        const val = parseInt(maxReaders, 10);
        if (isNaN(val) || val < 0) {
            alert('Max readers must be a non-negative integer');
            return;
        }
        payload.maxReaders = val;
    }

    const fallback = fd.get('fallback');
    if (fallback) payload.fallback = fallback;

    try {
        const isEditing = editingPathName || editingConfigPathName;
        const editingName = editingPathName || editingConfigPathName;

        if (isEditing) {

            const editPayload = { ...payload };
            delete editPayload.name;
            delete editPayload.source_type;


            if (containsMaskedCredentials(editPayload.source)) {
                delete editPayload.source;
            }
            if (containsMaskedCredentials(editPayload.sourceRedirect)) {
                delete editPayload.sourceRedirect;
            }
            if (containsMaskedCredentials(editPayload.fallback)) {
                delete editPayload.fallback;
            }

            await fetchAPI(`/paths/${encodeURIComponent(editingName)}`, {
                method: 'PATCH',
                body: JSON.stringify(editPayload),
            });
        } else {

            await fetchAPI('/paths', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
        }
        modal.classList.add('hidden');
        modal.classList.remove('flex');
        if (currentPage === 'streams') {
            await loadStreams();
        } else if (currentPage === 'config-paths') {
            loadConfigPaths();
        } else if (currentPage === 'path-detail') {
            await loadPathDetail(currentPathName);
        }
    } catch (e) {
        showError(e.message);
        const isEditing = editingPathName || editingConfigPathName;
        alert(`Failed to ${isEditing ? 'update' : 'add'} path: ${e.message}`);
    }
});

// --- Config Paths ---

let allConfigPaths = [];
let configPathsCurrentPage = 1;
const CONFIG_PATHS_PER_PAGE = 10;

async function loadConfigPaths() {
    try {
        const paths = await fetchAPI('/paths');
        if (paths.success) {
            allConfigPaths = paths.data.items || [];
            configPathsCurrentPage = 1;
            renderConfigPaths(allConfigPaths);
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}

function renderConfigPaths(paths) {
    const tbody = document.getElementById('config-paths-table-body');
    const searchTerm = document.getElementById('config-paths-search')?.value.toLowerCase() || '';

    const filtered = paths.filter(p =>
        [p.name, p.source, p.fallback, p.source_redirect]
            .some(value => String(value || '').toLowerCase().includes(searchTerm))
    );

    const totalPages = Math.max(1, Math.ceil(filtered.length / CONFIG_PATHS_PER_PAGE));
    configPathsCurrentPage = Math.min(configPathsCurrentPage, totalPages);
    updateConfigPathsPaginationControls(filtered.length, totalPages);

    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="px-6 py-12 text-center text-gray-500">No paths found</td></tr>';
        return;
    }

    const startIndex = (configPathsCurrentPage - 1) * CONFIG_PATHS_PER_PAGE;
    const pagePaths = filtered.slice(startIndex, startIndex + CONFIG_PATHS_PER_PAGE);

    const columnsFromHeaders = Array.from(
        tbody.closest('table').querySelectorAll('thead [data-config-path-column]'),
        header => header.dataset.configPathColumn,
    );
    const columns = columnsFromHeaders.length
        ? columnsFromHeaders
        : ['name', 'type', 'source', 'fallback', 'on-demand', 'max-readers', 'actions'];

    tbody.innerHTML = pagePaths.map(p => {

        let sourceType = 'Publisher';
        let sourceDisplay = '(publisher)';
        if (p.source_redirect) {
            sourceType = 'Redirect';
            sourceDisplay = p.source_redirect;
        } else if (p.source) {
            sourceType = 'URL Source';
            sourceDisplay = p.source;
        }

        const cellRenderers = {
            name: path => `<td class="px-6 py-4 font-mono text-sm">${escapeHtml(path.name)}</td>`,
            type: () => `
                <td class="px-6 py-4 text-sm">
                    <span class="status-badge ${sourceType === 'Publisher' ? 'status-offline' : sourceType === 'URL Source' ? 'status-online' : 'bg-purple-100 text-purple-800'}">
                        ${sourceType}
                    </span>
                </td>`,
            source: () => `<td class="px-6 py-4 text-sm text-gray-600 max-w-xs overflow-hidden"><span class="block truncate">${escapeHtml(sourceDisplay)}</span></td>`,
            fallback: path => `<td class="px-6 py-4 text-sm text-gray-600 max-w-xs overflow-hidden"><span class="block truncate">${escapeHtml(path.fallback || '-')}</span></td>`,
            'on-demand': path => `
                <td class="px-6 py-4 text-sm">
                    <span class="status-badge ${path.source_on_demand ? 'status-online' : 'status-offline'}">
                        ${path.source_on_demand ? 'Yes' : 'No'}
                    </span>
                </td>`,
            'max-readers': path => `<td class="px-6 py-4 text-sm">${path.max_readers !== null && path.max_readers !== undefined ? path.max_readers : 'Unlimited'}</td>`,
            actions: path => `
                <td class="px-6 py-4 text-right whitespace-nowrap">
                    <button onclick="editConfigPath('${escapeHtml(path.name)}')" class="btn-icon btn-primary mr-2">Edit</button>
                    <button onclick="deleteConfigPath('${escapeHtml(path.name)}')" class="btn-icon btn-danger">Delete</button>
                </td>`,
        };

        return `
            <tr class="hover:bg-gray-50">
                ${columns.map(column => cellRenderers[column]?.(p) || '<td></td>').join('')}
            </tr>
        `;
    }).join('');
}

function updateConfigPathsPaginationControls(totalFiltered, totalPages) {
    const prevButton = document.getElementById('config-paths-prev-page');
    const nextButton = document.getElementById('config-paths-next-page');
    const pageInfo = document.getElementById('config-paths-page-info');

    if (!prevButton || !nextButton || !pageInfo) return;

    prevButton.disabled = totalFiltered === 0 || configPathsCurrentPage <= 1;
    nextButton.disabled = totalFiltered === 0 || configPathsCurrentPage >= totalPages;
    pageInfo.textContent = totalFiltered === 0
        ? 'Page 0 of 0'
        : `Page ${configPathsCurrentPage} of ${totalPages}`;
}

function changeConfigPathsPage(delta) {
    const searchTerm = document.getElementById('config-paths-search')?.value.toLowerCase() || '';
    const filtered = allConfigPaths.filter(path =>
        [path.name, path.source, path.fallback, path.source_redirect]
            .some(value => String(value || '').toLowerCase().includes(searchTerm))
    );
    const totalPages = Math.max(1, Math.ceil(filtered.length / CONFIG_PATHS_PER_PAGE));
    const nextPage = Math.max(1, Math.min(totalPages, configPathsCurrentPage + delta));

    if (nextPage !== configPathsCurrentPage) {
        configPathsCurrentPage = nextPage;
        renderConfigPaths(allConfigPaths);
    }
}

function exportConfigPaths() {
    const exportData = allConfigPaths.map(path => {
        let type = 'Publisher';
        let source = '(publisher)';
        if (path.source_redirect) {
            type = 'Redirect';
            source = path.source_redirect;
        } else if (path.source) {
            type = 'URL Source';
            source = path.source;
        }

        return {
            name: path.name,
            type,
            source,
            fallback: path.fallback || null,
            on_demand: Boolean(path.source_on_demand),
            max_readers: path.max_readers ?? null,
        };
    });
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const downloadUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = downloadUrl;
    link.download = `path-configurations-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(downloadUrl), 0);
}

window.editConfigPath = function(name) {
    const path = allConfigPaths.find(p => p.name === name);
    if (path) {
        openConfigPathModal(path);
    }
};

window.deleteConfigPath = async function(name) {
    if (!confirm(`Delete path "${name}"?`)) return;
    try {
        await fetchAPI(`/paths/${encodeURIComponent(name)}`, { method: 'DELETE' });
        loadConfigPaths();
    } catch (e) {
        showError(e.message);
        alert(`Failed to delete: ${e.message}`);
    }
};

async function loadConfigDefaults() {
    try {
        const res = await fetchAPI('/config/path-defaults');
        if (!res.success || !res.data || typeof res.data !== 'object' || Array.isArray(res.data)) {
            throw new Error(res.message || 'MediaMTX returned an invalid Path Defaults configuration');
        }

        const form = document.getElementById('config-defaults-form');
        const hasUnsavedChanges = form?.dataset.dirty === 'true';
        const changedOnServer = JSON.stringify(res.data) !== JSON.stringify(originalDefaults);
        if (!hasUnsavedChanges && (originalDefaults === null || changedOnServer)) {
            originalDefaults = res.data;
            renderConfigDefaults(res.data);
            if (form) form.dataset.dirty = 'false';
            setConfigDefaultsStatus('', '');
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
        setConfigDefaultsStatus(`Failed to load Path Defaults: ${e.message}`, 'error');
    }
}

const PATH_DEFAULTS_SECTIONS = [
    {
        title: 'General',
        description: 'Choose where each path gets its stream from and control on-demand pulling and reader limits.',
        keys: [
            'name', 'source', 'sourceFingerprint', 'sourceOnDemand',
            'sourceOnDemandStartTimeout', 'sourceOnDemandCloseAfter', 'sourceRedirect',
            'maxReaders', 'useAbsoluteTimestamp',
        ],
    },
    {
        title: 'Always available',
        description: 'Keep a path available by playing an offline segment when its stream is unavailable.',
        keys: ['alwaysAvailable', 'alwaysAvailableFile', 'alwaysAvailableRecorded', 'alwaysAvailableTracks'],
    },
    {
        title: 'Record',
        description: 'Control whether streams are recorded, their file format, segment timing, and storage path.',
        keys: [
            'record', 'recordDeleteAfter', 'recordFormat', 'recordMaxPartSize',
            'recordPartDuration', 'recordPath', 'recordSegmentDuration',
        ],
    },
    {
        title: 'Publisher source',
        description: 'Configure publisher replacement and credentials for streams published to a path.',
        keys: ['overridePublisher', 'rtspDemuxMpegts', 'srtPublishPassphrase', 'srtReadPassphrase'],
    },
    {
        title: 'RTSP source',
        description: 'Configure transport, range, scaling, and UDP ports when pulling a stream over RTSP.',
        keys: [
            'rtspTransport', 'rtspAnyPort', 'rtspRangeType', 'rtspRangeStart',
            'rtspScale', 'rtspUDPSourcePortRange',
        ],
    },
    {
        title: 'RTP source',
        description: 'Provide the session description for an RTP source.',
        keys: ['rtpSDP'],
    },
    {
        title: 'MoQ source',
        description: 'Select the transport used by a Media over QUIC (MoQ) source.',
        keys: ['moqTransport'],
    },
    {
        title: 'WHEP source',
        description: 'Configure authorization and gathering timeouts for a WHEP source.',
        keys: [
            'whepBearerToken', 'whepHandshakeTimeout', 'whepSTUNGatherTimeout',
            'whepTrackGatherTimeout',
        ],
    },
    {
        title: 'Raspberry Pi Camera',
        description: 'Configure camera identity, image processing, exposure, focus, and encoder options.',
        keys: [
            'rpiCameraCamID', 'rpiCameraSecondary', 'rpiCameraWidth', 'rpiCameraHeight',
            'rpiCameraHFlip', 'rpiCameraVFlip', 'rpiCameraBrightness', 'rpiCameraContrast',
            'rpiCameraSaturation', 'rpiCameraSharpness', 'rpiCameraExposure', 'rpiCameraAWB',
            'rpiCameraAWBGains', 'rpiCameraDenoise', 'rpiCameraShutter', 'rpiCameraMetering',
            'rpiCameraGain', 'rpiCameraEV', 'rpiCameraROI', 'rpiCameraHDR',
            'rpiCameraTuningFile', 'rpiCameraMode', 'rpiCameraFPS', 'rpiCameraAfMode',
            'rpiCameraAfRange', 'rpiCameraAfSpeed', 'rpiCameraLensPosition',
            'rpiCameraAfWindow', 'rpiCameraFlickerPeriod', 'rpiCameraTextOverlayEnable',
            'rpiCameraTextOverlay', 'rpiCameraCodec', 'rpiCameraIDRPeriod',
            'rpiCameraBitrate', 'rpiCameraH264Profile', 'rpiCameraH264Level',
            'rpiCameraMJPEGQuality',
        ],
    },
    {
        title: 'Forward',
        description: 'Forward the stream to other destinations, optionally including protocol credentials.',
        keys: ['forward'],
    },
    {
        title: 'Hooks',
        description: 'Run commands when a path, stream, reader, or recording segment changes state.',
        keys: [
            'runOnInit', 'runOnInitRestart', 'runOnDemand', 'runOnDemandRestart',
            'runOnDemandStartTimeout', 'runOnDemandCloseAfter', 'runOnUnDemand',
            'runOnAvailable', 'runOnAvailableRestart', 'runOnUnavailable', 'runOnOnline',
            'runOnOnlineRestart', 'runOnOffline', 'runOnRead', 'runOnReadRestart',
            'runOnUnread', 'runOnRecordSegmentCreate', 'runOnRecordSegmentComplete',
        ],
    },
];

const PATH_DEFAULTS_FIELD_DESCRIPTIONS = {
    name: 'Path name used by MediaMTX. Path defaults are shared by paths unless a path-specific setting overrides them.',
    source: 'Stream source. Use publisher for incoming streams, a source URL to pull a stream, or a supported source type such as rpiCamera.',
    sourceFingerprint: 'SHA-256 certificate fingerprint used to verify a source with a self-signed or otherwise invalid TLS certificate.',
    sourceOnDemand: 'When enabled for a URL source, pull the stream only while at least one reader is connected.',
    sourceOnDemandStartTimeout: 'Maximum time readers wait for an on-demand source to become ready.',
    sourceOnDemandCloseAfter: 'How long to wait after the last reader disconnects before closing an on-demand source.',
    sourceRedirect: 'Path or absolute RTSP URL to which readers are redirected when the source is redirect.',
    maxReaders: 'Maximum number of simultaneous readers. Zero means no limit.',
    useAbsoluteTimestamp: 'Use the source frames’ absolute timestamps instead of replacing them with the current time.',
    alwaysAvailable: 'Play an offline segment on repeat while the stream is unavailable.',
    alwaysAvailableFile: 'Optional MP4 file to use instead of the generated offline segment.',
    alwaysAvailableRecorded: 'Record the always-available segment.',
    alwaysAvailableTracks: 'Track definitions for the always-available segment. Enter a JSON array; audio codecs can require sampleRate, channelCount, and muLaw.',
    record: 'Record streams published to or pulled by this path.',
    recordDeleteAfter: 'Automatically delete recordings after this duration. Use 0s to disable automatic deletion.',
    recordFormat: 'Recording container format. MediaMTX supports fmp4 and mpegts.',
    recordMaxPartSize: 'Maximum size of an in-progress recording part, to limit memory use.',
    recordPartDuration: 'Duration of each recording part. A shorter value limits the amount of data lost after a failure.',
    recordPath: 'Recording filename pattern. MediaMTX supports placeholders such as %path, %Y, %m, %d, and %H.',
    recordSegmentDuration: 'Minimum duration of each recording segment.',
    overridePublisher: 'Allow a new publisher to disconnect and replace the current publisher.',
    rtspDemuxMpegts: 'Demultiplex MPEG-TS packets carried inside an RTSP stream.',
    srtPublishPassphrase: 'Passphrase required to publish to this path over SRT.',
    srtReadPassphrase: 'Passphrase required to read this path over SRT.',
    rtspTransport: 'Transport used to pull the RTSP source: automatic, UDP, multicast, or TCP.',
    rtspAnyPort: 'Accept RTSP sources with missing or random server ports. Enable only when required by the source.',
    rtspRangeType: 'RTSP range type used to request a starting position, such as npt, clock, or smpte.',
    rtspRangeStart: 'Position within the source at which RTSP playback should start.',
    rtspScale: 'Playback scale requested from the RTSP source.',
    rtspUDPSourcePortRange: 'Inclusive source-port range used for outgoing RTSP UDP packets. Enter a JSON array, for example [10000, 65535].',
    rtpSDP: 'Session Description Protocol (SDP) describing the RTP stream.',
    moqTransport: 'Transport protocol used by the MoQ source.',
    whepBearerToken: 'Bearer token sent when connecting to the WHEP source.',
    whepHandshakeTimeout: 'Maximum time allowed for the WHEP handshake.',
    whepSTUNGatherTimeout: 'Maximum time allowed to gather STUN candidates for WHEP.',
    whepTrackGatherTimeout: 'Maximum time allowed to gather WHEP tracks.',
    forward: 'JSON array of forwarding destinations. Each entry can include dest, destFingerprint, moqTransport, and whipBearerToken.',
    rpiCameraCamID: 'ID of the Raspberry Pi camera.',
    rpiCameraSecondary: 'Use the camera secondary stream.',
    rpiCameraWidth: 'Camera frame width in pixels.',
    rpiCameraHeight: 'Camera frame height in pixels.',
    rpiCameraHFlip: 'Flip camera frames horizontally.',
    rpiCameraVFlip: 'Flip camera frames vertically.',
    rpiCameraBrightness: 'Image brightness, in the range -1 to 1.',
    rpiCameraContrast: 'Image contrast, in the range 0 to 16.',
    rpiCameraSaturation: 'Image saturation, in the range 0 to 16.',
    rpiCameraSharpness: 'Image sharpness, in the range 0 to 16.',
    rpiCameraExposure: 'Camera exposure mode, such as normal, short, long, or custom.',
    rpiCameraAWB: 'Automatic white-balance mode.',
    rpiCameraAWBGains: 'Fixed red and blue white-balance gains. Enter a JSON array such as [1, 1].',
    rpiCameraDenoise: 'Camera denoise mode.',
    rpiCameraShutter: 'Fixed shutter speed in microseconds.',
    rpiCameraMetering: 'Exposure and gain metering mode.',
    rpiCameraGain: 'Fixed camera gain.',
    rpiCameraEV: 'Exposure compensation, in the range -10 to 10.',
    rpiCameraROI: 'Region of interest as normalized x,y,width,height values.',
    rpiCameraHDR: 'Enable HDR when supported by the camera.',
    rpiCameraTuningFile: 'Path to a camera tuning file.',
    rpiCameraMode: 'Sensor mode, formatted as width:height:bit-depth:packing.',
    rpiCameraFPS: 'Camera frame rate in frames per second.',
    rpiCameraAfMode: 'Autofocus mode, such as auto, manual, or continuous.',
    rpiCameraAfRange: 'Autofocus range, such as normal, macro, or full.',
    rpiCameraAfSpeed: 'Autofocus speed.',
    rpiCameraLensPosition: 'Manual focus distance; 0 focuses at infinity and larger values focus closer.',
    rpiCameraAfWindow: 'Autofocus window as normalized x,y,width,height values.',
    rpiCameraFlickerPeriod: 'Manual flicker-correction period in microseconds.',
    rpiCameraTextOverlayEnable: 'Print the configured text overlay on each camera frame.',
    rpiCameraTextOverlay: 'Overlay text. Supports strftime-style date and time placeholders.',
    rpiCameraCodec: 'Camera output codec, such as auto, hardwareH264, softwareH264, or mjpeg.',
    rpiCameraIDRPeriod: 'Number of frames between IDR frames for H.264 output.',
    rpiCameraBitrate: 'Target H.264 bitrate in bits per second.',
    rpiCameraH264Profile: 'H.264 profile used by the camera encoder.',
    rpiCameraH264Level: 'H.264 level used by the camera encoder.',
    rpiCameraMJPEGQuality: 'JPEG quality for MJPEG output.',
    runOnInit: 'Command to run when the path is initialized.',
    runOnInitRestart: 'Restart the initialization command if it exits.',
    runOnDemand: 'Command to run when a reader requests the path and no publisher is available.',
    runOnDemandRestart: 'Restart the on-demand command if it exits.',
    runOnDemandStartTimeout: 'Maximum time readers wait for the on-demand command to start publishing.',
    runOnDemandCloseAfter: 'How long to wait after the last reader disconnects before closing the on-demand command.',
    runOnUnDemand: 'Command to run when there are no readers left on the path.',
    runOnAvailable: 'Command to run when the path becomes available.',
    runOnAvailableRestart: 'Restart the available command if it exits.',
    runOnUnavailable: 'Command to run when the path becomes unavailable.',
    runOnOnline: 'Command to run when the stream becomes ready to read.',
    runOnOnlineRestart: 'Restart the online command if it exits.',
    runOnOffline: 'Command to run when the stream is no longer ready to read.',
    runOnRead: 'Command to run when a reader starts reading the stream.',
    runOnReadRestart: 'Restart the reader command if it exits.',
    runOnUnread: 'Command to run when a reader stops reading the stream.',
    runOnRecordSegmentCreate: 'Command to run when a recording segment is created.',
    runOnRecordSegmentComplete: 'Command to run when a recording segment is complete.',
};

const PATH_DEFAULTS_PLACEHOLDERS = {
    name: 'e.g. all_others',
    source: 'publisher or rtsp://camera/stream',
    sourceFingerprint: 'SHA-256 certificate fingerprint',
    sourceOnDemandStartTimeout: 'e.g. 10s',
    sourceOnDemandCloseAfter: 'e.g. 10s',
    sourceRedirect: 'e.g. /another-path or rtsp://server/path',
    alwaysAvailableFile: 'e.g. ./offline.mp4',
    alwaysAvailableTracks: '[{"codec":"H264"}]',
    recordDeleteAfter: 'e.g. 1d',
    recordFormat: 'fmp4 or mpegts',
    recordMaxPartSize: 'e.g. 50M',
    recordPartDuration: 'e.g. 1s',
    recordPath: './recordings/%path/%Y-%m-%d_%H-%M-%S',
    recordSegmentDuration: 'e.g. 1h',
    rtspRangeStart: 'e.g. 300ms or 20230812T120000Z',
    rtspUDPSourcePortRange: '[10000, 65535]',
    rtpSDP: 'Paste the RTP session description (SDP)',
    forward: '[{"dest":"rtsp://server/path"}]',
    runOnInit: 'Enter a command to run when the path is initialized',
    runOnDemand: 'Enter a command to run when a reader requests the path',
};

function getPathDefaultsGroup(key) {
    const section = PATH_DEFAULTS_SECTIONS.find((candidate) => candidate.keys.includes(key));
    if (section) return section.title;
    if (key.startsWith('runOn')) return 'Hooks';
    if (key.startsWith('rpiCamera')) return 'Raspberry Pi Camera';
    if (key.startsWith('record')) return 'Record';
    if (key.startsWith('rtsp')) return 'RTSP source';
    if (key.startsWith('whep')) return 'WHEP source';
    if (key.startsWith('moq')) return 'MoQ source';
    return 'Other';
}

function getPathDefaultsLabel(key) {
    if (key === 'runOnUnDemand') return 'Run On Un-Demand';
    return key
        .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
        .replace(/\bRpi\b/gi, 'Raspberry Pi')
        .replace(/\bRtsp\b/gi, 'RTSP')
        .replace(/\bRtp\b/gi, 'RTP')
        .replace(/\bSrt\b/gi, 'SRT')
        .replace(/\bWhep\b/gi, 'WHEP')
        .replace(/\bMoq\b/gi, 'MoQ')
        .replace(/\bSdp\b/gi, 'SDP')
        .replace(/\bAwb\b/gi, 'AWB')
        .replace(/\bAf\b/gi, 'AF')
        .replace(/\bH264\b/gi, 'H.264')
        .replace(/\bMjpeg\b/gi, 'MJPEG')
        .replace(/^./, (character) => character.toUpperCase());
}

function getPathDefaultsKind(key, value) {
    if (Array.isArray(value)) return 'array';
    if (value !== null && typeof value === 'object') return 'object';
    if (value === null) return 'null';
    if (typeof value === 'boolean') return 'boolean';
    if (typeof value === 'number') return 'number';
    if (typeof value === 'string') return 'string';
    throw new Error(`Unsupported Path Defaults value for "${key}"`);
}

function getPathDefaultsArrayItemTemplate(key, value) {
    if (value.length > 0) return value[0];
    if (key === 'alwaysAvailableTracks') {
        return { codec: 'H264', sampleRate: 0, channelCount: 0, muLaw: false };
    }
    if (key === 'forward') {
        return { dest: '', destFingerprint: '', moqTransport: '', whipBearerToken: '' };
    }
    if (key === 'rpiCameraAWBGains' || key === 'rtspUDPSourcePortRange') return 0;
    return '';
}

function renderPathDefaultsArrayControl(key, value, label, tooltip) {
    const itemTemplate = getPathDefaultsArrayItemTemplate(key, value);
    const items = value.length > 0 ? value : [];
    return `
        <div class="min-w-0" data-config-array-key="${escapeHtml(key)}">
            <div class="mb-2 flex items-center gap-1.5 text-sm font-medium text-gray-700">
                <span>${escapeHtml(label)}</span>
                <span class="cursor-help text-gray-400" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}" tabindex="0">
                    <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0ZM9 8a1 1 0 1 1 2 0c-.58.46-1.29 1.04-1.29 2.34a1 1 0 1 0 2 0c0-.34.08-.48.54-.85C12.12 10.1 13 9.39 13 8a3 3 0 1 0-6 0 1 1 0 1 0 2 0Zm1 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd"></path>
                    </svg>
                </span>
            </div>
            <div data-array-items class="space-y-3">
                ${items.map((item, index) => renderPathDefaultsArrayItem(key, item, itemTemplate, index)).join('')}
            </div>
            <button type="button" data-array-add="${escapeHtml(key)}" class="mt-3 inline-flex items-center gap-1 rounded-md bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
                <span aria-hidden="true">+</span> Add item
            </button>
        </div>
    `;
}

function renderPathDefaultsArrayItem(key, item, template, index) {
    const inputClass = 'w-full min-w-0 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500';
    const isObject = template !== null && typeof template === 'object' && !Array.isArray(template);
    const fields = isObject
        ? Object.entries(template).map(([field, expected]) => {
            const fieldValue = item && typeof item === 'object' && Object.prototype.hasOwnProperty.call(item, field)
                ? item[field]
                : expected;
            const kind = getPathDefaultsKind(field, fieldValue);
            const fieldLabel = getPathDefaultsLabel(field);
            const attributes = `data-array-field="${escapeHtml(field)}" data-array-kind="${kind}"`;
            if (kind === 'boolean') {
                return `
                    <label class="inline-flex min-h-10 items-center gap-2">
                        <input type="checkbox" ${attributes} ${fieldValue ? 'checked' : ''} class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500">
                        <span class="text-sm text-gray-700">${escapeHtml(fieldLabel)}</span>
                    </label>
                `;
            }
            const placeholder = typeof expected === 'number' ? 'e.g. 0' : `Enter ${fieldLabel.toLowerCase()}`;
            return `
                <label class="block min-w-0">
                    <span class="mb-1 block text-xs font-medium text-gray-600">${escapeHtml(fieldLabel)}</span>
                    <input ${attributes} type="${kind === 'number' ? 'number' : 'text'}" ${kind === 'number' ? `step="${Number.isInteger(expected) ? '1' : 'any'}"` : ''} value="${escapeHtml(fieldValue === null ? '' : String(fieldValue))}" placeholder="${escapeHtml(placeholder)}" class="${inputClass}">
                </label>
            `;
        }).join('')
        : (() => {
            const kind = getPathDefaultsKind(key, item);
            const valueControl = kind === 'boolean'
                ? `<input data-array-value data-array-kind="${kind}" type="checkbox" ${item ? 'checked' : ''} class="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500">`
                : `<input data-array-value data-array-kind="${kind}" type="${kind === 'number' ? 'number' : 'text'}" ${kind === 'number' ? `step="${Number.isInteger(template) ? '1' : 'any'}"` : ''} value="${escapeHtml(item === null ? '' : String(item))}" placeholder="${typeof template === 'number' ? 'e.g. 0' : 'Enter a value'}" class="${inputClass}">`;
            return `
                <label class="${kind === 'boolean' ? 'inline-flex min-h-10 items-center gap-2' : 'block min-w-0 flex-1'}">
                    <span class="mb-1 block text-xs font-medium text-gray-600">Value</span>
                    ${valueControl}
                </label>
            `;
        })();

    return `
        <div data-array-item class="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <div class="mb-3 flex items-center justify-between">
                <span data-array-item-label class="text-xs font-semibold uppercase tracking-wide text-gray-500">Item ${index + 1}</span>
                <button type="button" data-array-remove class="rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">Remove</button>
            </div>
            <div class="${isObject ? 'grid grid-cols-1 gap-3 sm:grid-cols-2' : 'flex items-end gap-3'}">
                ${fields}
            </div>
        </div>
    `;
}

function addPathDefaultsArrayItem(key) {
    const arrayField = Array.from(document.querySelectorAll('[data-config-array-key]'))
        .find((candidate) => candidate.dataset.configArrayKey === key);
    const container = arrayField?.querySelector('[data-array-items]');
    if (!container || !originalDefaults || !Array.isArray(originalDefaults[key])) {
        setConfigDefaultsStatus(`Unable to add an item to "${key}".`, 'error');
        return;
    }
    const template = getPathDefaultsArrayItemTemplate(key, originalDefaults[key]);
    container.insertAdjacentHTML('beforeend', renderPathDefaultsArrayItem(key, template, template, container.children.length));
    document.getElementById('config-defaults-form').dataset.dirty = 'true';
}

function isPathDefaultsDuration(key, value) {
    return typeof value === 'string' &&
        (/timeout|closeafter|duration/i.test(key) || /^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:ns|us|µs|μs|ms|s|m|h)/.test(value));
}

function renderPathDefaultsField(key, value) {
    const kind = getPathDefaultsKind(key, value);
    const label = getPathDefaultsLabel(key);
    const group = getPathDefaultsGroup(key);
    const tooltip = PATH_DEFAULTS_FIELD_DESCRIPTIONS[key] ||
        `Sets ${label.toLowerCase()} for the ${group.toLowerCase()} settings.`;
    const attributes = `data-config-key="${escapeHtml(key)}" data-config-kind="${kind}"`;

    if (kind === 'boolean') {
        return `
            <div class="min-w-0">
                <label class="inline-flex cursor-pointer items-center gap-3 pt-2">
                    <input type="checkbox" ${attributes} ${value ? 'checked' : ''} class="peer sr-only">
                    <span class="relative h-6 w-11 rounded-full bg-gray-300 transition-colors peer-checked:bg-blue-600 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-500 peer-focus-visible:ring-offset-2 after:absolute after:left-1 after:top-1 after:h-4 after:w-4 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-5"></span>
                    <span class="text-sm font-medium text-gray-700">${escapeHtml(label)}</span>
                    <span class="cursor-help text-gray-400" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}">
                        <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                            <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM9 8a1 1 0 1 1 2 0c0 .55-.25.79-.71 1.16-.58.46-1.29 1.04-1.29 2.34a1 1 0 1 0 2 0c0-.34.08-.48.54-.85C12.12 10.1 13 9.39 13 8a3 3 0 1 0-6 0 1 1 0 1 0 2 0Zm1 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd"></path>
                        </svg>
                    </span>
                </label>
            </div>
        `;
    }

    if (kind === 'array') {
        return renderPathDefaultsArrayControl(key, value, label, tooltip);
    }

    const valueText = kind === 'array' || kind === 'object'
        ? JSON.stringify(value, null, 2)
        : value === null ? '' : String(value);
    const duration = kind === 'string' && isPathDefaultsDuration(key, value);
    const placeholder = PATH_DEFAULTS_PLACEHOLDERS[key] ||
        (duration ? 'e.g. 10s or 1h30m' :
            kind === 'array' || kind === 'object' ? 'Enter a JSON value' :
                kind === 'number' ? 'e.g. 0' :
                    key.startsWith('runOn') ? 'Enter a command' :
                        `Enter ${label.toLowerCase()}`);
    const inputClass = 'w-full min-w-0 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500';
    let control;

    if (kind === 'object' || key.startsWith('runOn') || key === 'rtpSDP') {
        control = `<textarea ${attributes} rows="${kind === 'object' ? 4 : 3}" placeholder="${escapeHtml(placeholder)}" class="${inputClass} font-mono" spellcheck="false">${escapeHtml(valueText)}</textarea>`;
    } else if (kind === 'number') {
        const step = Number.isInteger(value) ? '1' : 'any';
        control = `<input ${attributes} type="number" step="${step}" value="${escapeHtml(valueText)}" placeholder="${escapeHtml(placeholder)}" class="${inputClass}">`;
    } else {
        control = `<input ${attributes} type="text" value="${escapeHtml(valueText)}" placeholder="${escapeHtml(placeholder)}" ${kind === 'null' ? 'data-config-null="true"' : ''} class="${inputClass}">`;
    }

    return `
        <label class="block min-w-0">
            <span class="mb-2 flex items-center gap-1.5 text-sm font-medium text-gray-700">
                ${escapeHtml(label)}
                <span class="cursor-help text-gray-400" title="${escapeHtml(tooltip)}" aria-label="${escapeHtml(tooltip)}" tabindex="0">
                    <svg class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM9 8a1 1 0 1 1 2 0c0 .55-.25.79-.71 1.16-.58.46-1.29 1.04-1.29 2.34a1 1 0 1 0 2 0c0-.34.08-.48.54-.85C12.12 10.1 13 9.39 13 8a3 3 0 1 0-6 0 1 1 0 1 0 2 0Zm1 7a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z" clip-rule="evenodd"></path>
                    </svg>
                </span>
            </span>
            ${control}
            ${duration ? '<span class="mt-1 block text-xs text-gray-500">Enter a MediaMTX duration, such as 10s or 1h30m.</span>' : ''}
        </label>
    `;
}

function renderConfigDefaults(config) {
    const container = document.getElementById('config-defaults-fields');
    const nav = document.getElementById('config-defaults-nav');
    if (!container || !nav) return;

    const grouped = new Map();
    Object.entries(config).forEach(([key, value]) => {
        const group = getPathDefaultsGroup(key);
        if (!grouped.has(group)) grouped.set(group, []);
        grouped.get(group).push([key, value]);
    });

    if (grouped.size === 0) {
        nav.innerHTML = '';
        container.innerHTML = '<div class="rounded-lg border border-gray-200 bg-white p-6 text-sm text-gray-500">MediaMTX returned no Path Defaults fields.</div>';
        return;
    }

    const orderedSections = PATH_DEFAULTS_SECTIONS
        .filter((section) => grouped.has(section.title))
        .map((section) => [section, grouped.get(section.title)]);
    const knownGroups = new Set(PATH_DEFAULTS_SECTIONS.map((section) => section.title));
    grouped.forEach((fields, title) => {
        if (!knownGroups.has(title)) {
            orderedSections.push([
                { title, description: 'Additional settings returned by the MediaMTX API.' },
                fields,
            ]);
        }
    });

    nav.innerHTML = orderedSections.map(([section]) => `
        <button
            type="button"
            data-section-target="config-defaults-${escapeHtml(section.title.toLowerCase().replace(/[^a-z0-9]+/g, '-'))}"
            class="rounded-md bg-blue-500 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >${escapeHtml(section.title)}</button>
    `).join('');

    container.innerHTML = orderedSections.map(([section, fields]) => {
        const sectionId = `config-defaults-${section.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
        return `
            <section id="${escapeHtml(sectionId)}" class="min-w-0 scroll-mt-6 overflow-hidden rounded-lg border border-gray-200 bg-white">
                <div class="border-b border-gray-200 bg-gray-100 px-5 py-3 sm:px-6">
                    <h3 class="text-center text-base font-semibold text-gray-800">${escapeHtml(section.title)}</h3>
                    <p class="mt-1 text-center text-xs text-gray-600">${escapeHtml(section.description)}</p>
                </div>
                <div class="grid min-w-0 grid-cols-1 gap-5 p-5 sm:p-6 md:grid-cols-2 xl:grid-cols-3">
                    ${fields.map(([key, value]) => renderPathDefaultsField(key, value)).join('')}
                </div>
            </section>
        `;
    }).join('');
}

function setConfigDefaultsStatus(message, type) {
    const status = document.getElementById('config-defaults-status');
    if (!status) return;
    status.textContent = message;
    status.className = `text-sm ${type === 'error' ? 'text-red-600' : type === 'success' ? 'text-green-700' : 'hidden'}`;
}

function parsePathDefaultsDuration(value, key) {
    const durationPattern = /[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:ns|us|µs|μs|ms|s|m|h)/g;
    const parts = value.match(durationPattern);
    if (!parts || parts.join('') !== value) {
        throw new Error(`${getPathDefaultsLabel(key)} must be a valid duration, such as 10s or 1h30m.`);
    }
    return value;
}

function validatePathDefaultsValueShape(expected, value, path) {
    if (Array.isArray(expected)) {
        if (!Array.isArray(value)) throw new Error(`${path} must be a JSON array.`);
        if (expected.length > 0) {
            value.forEach((item, index) => validatePathDefaultsValueShape(expected[0], item, `${path}[${index}]`));
        }
        return;
    }

    if (expected !== null && typeof expected === 'object') {
        if (value === null || typeof value !== 'object' || Array.isArray(value)) {
            throw new Error(`${path} must be a JSON object.`);
        }
        Object.entries(expected).forEach(([key, expectedValue]) => {
            if (Object.prototype.hasOwnProperty.call(value, key)) {
                validatePathDefaultsValueShape(expectedValue, value[key], `${path}.${key}`);
            }
        });
        return;
    }

    if (expected === null ? value !== null : typeof value !== typeof expected) {
        throw new Error(`${path} must have the same value type as the loaded MediaMTX configuration.`);
    }
    if (typeof expected === 'number' && Number.isInteger(expected) && !Number.isInteger(value)) {
        throw new Error(`${path} must be an integer.`);
    }
}

function readPathDefaultsArrayValue(control, expected, path) {
    if (expected !== null && typeof expected === 'object' && !Array.isArray(expected)) {
        const value = {};
        Object.entries(expected).forEach(([key, expectedValue]) => {
            const field = Array.from(control.querySelectorAll('[data-array-field]'))
                .find((candidate) => candidate.dataset.arrayField === key);
            if (!field) throw new Error(`Missing input for ${path}.${key}.`);
            value[key] = readPathDefaultsArrayValue(field, expectedValue, `${path}.${key}`);
        });
        return value;
    }

    if (typeof expected === 'boolean') return control.checked;
    if (typeof expected === 'number') {
        if (control.value.trim() === '') throw new Error(`${path} must be a number.`);
        const numberValue = Number(control.value);
        if (!Number.isFinite(numberValue) || (Number.isInteger(expected) && !Number.isInteger(numberValue))) {
            throw new Error(`${path} must be a valid ${Number.isInteger(expected) ? 'integer' : 'number'}.`);
        }
        return numberValue;
    }
    if (expected === null && control.value === '') return null;
    return control.value;
}

function collectPathDefaultsArray(key, originalValue) {
    const arrayField = Array.from(document.querySelectorAll('[data-config-array-key]'))
        .find((candidate) => candidate.dataset.configArrayKey === key);
    if (!arrayField) throw new Error(`Missing form field for "${key}".`);
    const itemTemplate = getPathDefaultsArrayItemTemplate(key, originalValue);
    const items = Array.from(arrayField.querySelectorAll('[data-array-item]'));
    const values = items.map((item, index) => {
        const control = item.querySelector('[data-array-value], [data-array-field]');
        if (!control) throw new Error(`Missing input for ${getPathDefaultsLabel(key)} item ${index + 1}.`);
        const isObject = itemTemplate !== null && typeof itemTemplate === 'object' && !Array.isArray(itemTemplate);
        return readPathDefaultsArrayValue(
            isObject ? item : control,
            itemTemplate,
            `${getPathDefaultsLabel(key)}[${index}]`
        );
    });
    validatePathDefaultsValueShape(originalValue, values, getPathDefaultsLabel(key));
    return values;
}

function collectConfigDefaults() {
    const form = document.getElementById('config-defaults-form');
    const controls = Array.from(form.querySelectorAll('[data-config-key]'));
    const values = {};

    Object.entries(originalDefaults).forEach(([key, originalValue]) => {
        if (Array.isArray(originalValue)) {
            values[key] = collectPathDefaultsArray(key, originalValue);
            return;
        }

        const control = controls.find((candidate) => candidate.dataset.configKey === key);
        if (!control) throw new Error(`Missing form field for "${key}".`);

        const kind = control.dataset.configKind;
        if (kind === 'boolean') {
            values[key] = control.checked;
        } else if (kind === 'number') {
            if (control.value.trim() === '') {
                throw new Error(`${getPathDefaultsLabel(key)} must be a number.`);
            }
            const numberValue = Number(control.value);
            if (!Number.isFinite(numberValue) || (Number.isInteger(originalValue) && !Number.isInteger(numberValue))) {
                throw new Error(`${getPathDefaultsLabel(key)} must be a valid ${Number.isInteger(originalValue) ? 'integer' : 'number'}.`);
            }
            values[key] = numberValue;
        } else if (kind === 'array' || kind === 'object') {
            let parsed;
            try {
                parsed = JSON.parse(control.value);
            } catch {
                throw new Error(`${getPathDefaultsLabel(key)} must contain valid JSON.`);
            }
            if (kind === 'array' ? !Array.isArray(parsed) : parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
                throw new Error(`${getPathDefaultsLabel(key)} must remain a JSON ${kind}.`);
            }
            validatePathDefaultsValueShape(originalValue, parsed, getPathDefaultsLabel(key));
            values[key] = parsed;
        } else if (kind === 'null' && control.dataset.configNull === 'true' && control.value === '') {
            values[key] = null;
        } else {
            const value = control.value;
            values[key] = isPathDefaultsDuration(key, originalValue)
                ? parsePathDefaultsDuration(value, key)
                : value;
        }
    });

    return values;
}

async function saveConfigDefaults() {
    const form = document.getElementById('config-defaults-form');
    const saveButton = document.getElementById('config-defaults-save');

    try {
        const config = collectConfigDefaults();
        saveButton.disabled = true;
        saveButton.classList.add('opacity-60', 'cursor-not-allowed');

        const res = await fetchAPI('/config/path-defaults', {
            method: 'PATCH',
            body: JSON.stringify(config),
        });
        if (!res.success) throw new Error(res.message || 'MediaMTX did not apply the Path Defaults configuration');

        const latest = await fetchAPI('/config/path-defaults');
        if (!latest.success || !latest.data || typeof latest.data !== 'object' || Array.isArray(latest.data)) {
            throw new Error('The runtime accepted the update, but the updated values could not be reloaded for confirmation.');
        }

        originalDefaults = latest.data;
        renderConfigDefaults(originalDefaults);
        form.dataset.dirty = 'false';
        setConfigDefaultsStatus(
            'Path Defaults updated in the MediaMTX runtime. This change is not written to mediamtx.yml and will be lost after a MediaMTX restart.',
            'success'
        );
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConfigDefaultsStatus(`Unable to update Path Defaults: ${e.message}`, 'error');
    } finally {
        if (saveButton) {
            saveButton.disabled = false;
            saveButton.classList.remove('opacity-60', 'cursor-not-allowed');
        }
    }
}

function resetConfigDefaults() {
    if (originalDefaults !== null) {
        renderConfigDefaults(originalDefaults);
        document.getElementById('config-defaults-form').dataset.dirty = 'false';
        setConfigDefaultsStatus('', '');
    }
}

// --- Runtime Pages ---

function renderConnections(tbodyId, connections) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    if (!connections || connections.length === 0) {
        const cols = tbody.closest('table')?.querySelector('thead tr')?.children.length || 1;
        tbody.innerHTML = `<tr><td colspan="${cols}" class="px-6 py-12 text-center text-gray-500">No connections</td></tr>`;
        return;
    }

    tbody.innerHTML = connections.map(c => `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(c.id || '-')}</td>
            <td class="px-6 py-4 text-sm text-gray-600">${escapeHtml(c.remoteAddr || c.remote_addr || '-')}</td>
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(c.path || '-')}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(c.bytesReceived || c.bytes_received || 0)}</td>
            <td class="px-6 py-4 text-sm font-mono">${formatBytes(c.bytesSent || c.bytes_sent || 0)}</td>
        </tr>
    `).join('');
}

function renderSessions(tbodyId, sessions) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    if (!sessions || sessions.length === 0) {
        const cols = tbody.closest('table')?.querySelector('thead tr')?.children.length || 1;
        tbody.innerHTML = `<tr><td colspan="${cols}" class="px-6 py-12 text-center text-gray-500">No sessions</td></tr>`;
        return;
    }

    tbody.innerHTML = sessions.map(s => `
        <tr class="hover:bg-gray-50">
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(s.id || '-')}</td>
            <td class="px-6 py-4 text-sm text-gray-600">${escapeHtml(s.remoteAddr || s.remote_addr || '-')}</td>
            <td class="px-6 py-4 font-mono text-sm">${escapeHtml(s.path || '-')}</td>
            <td class="px-6 py-4 text-sm">
                <span class="status-badge ${s.ready ? 'status-online' : 'status-offline'}">
                    ${s.ready ? 'Ready' : s.state || 'Unknown'}
                </span>
            </td>
        </tr>
    `).join('');
}

async function loadRuntimeHLS() {
    try {
        const [connections, sessions] = await Promise.all([
            fetchAPI('/runtime/hls/connections'),
            fetchAPI('/runtime/hls/sessions'),
        ]);

        if (connections.success) renderConnections('hls-connections-body', connections.data.items || []);
        if (sessions.success) renderSessions('hls-sessions-body', sessions.data.items || []);

        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}

async function loadRuntimeRTSP() {
    try {
        const [connections, sessions] = await Promise.all([
            fetchAPI('/runtime/rtsp/connections'),
            fetchAPI('/runtime/rtsp/sessions'),
        ]);

        if (connections.success) renderConnections('rtsp-connections-body', connections.data.items || []);
        if (sessions.success) renderSessions('rtsp-sessions-body', sessions.data.items || []);

        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}

async function loadRuntimeRTMP() {
    try {
        const [connections, sessions] = await Promise.all([
            fetchAPI('/runtime/rtmp/connections'),
            fetchAPI('/runtime/rtmp/sessions'),
        ]);

        if (connections.success) renderConnections('rtmp-connections-body', connections.data.items || []);
        if (sessions.success) renderSessions('rtmp-sessions-body', sessions.data.items || []);

        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}

// --- Runtime Logs ---

let allLogs = [];
let logsCurrentPage = 1;
const LOGS_PER_PAGE = 10;

async function loadRuntimeLogs() {
    try {
        const res = await fetchAPI('/logs?lines=500');
        if (res.success) {
            allLogs = res.data.lines || [];
            logsCurrentPage = 1;
            renderLogs(allLogs);
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
        document.getElementById('logs-body').innerHTML = '<tr><td colspan="3" class="px-6 py-12 text-center text-red-600">Failed to load logs</td></tr>';
    }
}

function renderLogs(logs) {
    const tbody = document.getElementById('logs-body');
    const searchTerm = document.getElementById('logs-search')?.value.toLowerCase() || '';
    const levelFilter = document.getElementById('logs-level-filter')?.value || '';

    const filtered = logs.filter(log => {
        const message = (log.message || '').toLowerCase();
        const level = (log.level || '').toUpperCase();
        const matchesSearch = !searchTerm || message.includes(searchTerm);
        const matchesLevel = !levelFilter || level === levelFilter;
        return matchesSearch && matchesLevel;
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / LOGS_PER_PAGE));
    if (logsCurrentPage > totalPages) {
        logsCurrentPage = totalPages;
    }

    const startIdx = (logsCurrentPage - 1) * LOGS_PER_PAGE;
    const endIdx = startIdx + LOGS_PER_PAGE;
    const pageLogs = filtered.slice(startIdx, endIdx);

    if (pageLogs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="px-6 py-12 text-center text-gray-500">No log entries found</td></tr>';
        updatePaginationControls(0, 0);
        return;
    }

    tbody.innerHTML = pageLogs.map(log => {
        const level = (log.level || '').toUpperCase();
        let levelClass = 'text-gray-600';
        if (level === 'ERR') levelClass = 'text-red-600';
        else if (level === 'WAR') levelClass = 'text-yellow-600';
        else if (level === 'INF') levelClass = 'text-blue-600';
        else if (level === 'DEBUG') levelClass = 'text-gray-500';

        return `
            <tr class="hover:bg-gray-50">
                <td class="px-6 py-3 text-gray-500 whitespace-nowrap">${escapeHtml(log.timestamp || '-')}</td>
                <td class="px-6 py-3"><span class="font-medium ${levelClass}">${escapeHtml(level)}</span></td>
                <td class="px-6 py-3 text-gray-900 max-w-2xl truncate block">${escapeHtml(log.message || '-')}</td>
            </tr>
        `;
    }).join('');

    updatePaginationControls(filtered.length, totalPages);
}

function updatePaginationControls(totalFiltered, totalPages) {
    const prevBtn = document.getElementById('logs-prev-page');
    const nextBtn = document.getElementById('logs-next-page');
    const pageInfo = document.getElementById('logs-page-info');

    if (!prevBtn || !nextBtn || !pageInfo) return;

    prevBtn.disabled = logsCurrentPage <= 1;
    nextBtn.disabled = logsCurrentPage >= totalPages;
    pageInfo.textContent = totalFiltered === 0 ? 'Page 0 of 0' : `Page ${logsCurrentPage} of ${totalPages}`;
}

function changeLogsPage(delta) {
    const searchTerm = document.getElementById('logs-search')?.value.toLowerCase() || '';
    const levelFilter = document.getElementById('logs-level-filter')?.value || '';

    const filtered = allLogs.filter(log => {
        const message = (log.message || '').toLowerCase();
        const level = (log.level || '').toUpperCase();
        const matchesSearch = !searchTerm || message.includes(searchTerm);
        const matchesLevel = !levelFilter || level === levelFilter;
        return matchesSearch && matchesLevel;
    });

    const totalPages = Math.max(1, Math.ceil(filtered.length / LOGS_PER_PAGE));
    const newPage = Math.max(1, Math.min(totalPages, logsCurrentPage + delta));

    if (newPage !== logsCurrentPage) {
        logsCurrentPage = newPage;
        renderLogs(allLogs);
    }
}

let logsDeleteMode = null;
let logsCustomStart = null;
let logsCustomEnd = null;

async function deleteLogs(params) {
    try {
        const res = await fetchAPI('/logs/delete', { method: 'POST', body: JSON.stringify(params) });
        if (res.success) {
            logsCurrentPage = 1;
            await loadRuntimeLogs();
            alert(`Successfully deleted ${res.data.deleted_count} log entr${res.data.deleted_count === 1 ? 'y' : 'ies'}.`);
        } else {
            alert('Failed to delete logs: ' + (res.message || 'Unknown error'));
        }
    } catch (e) {
        alert('Failed to delete logs: ' + e.message);
    }
}

function openDeleteDropdown() {
    const dropdown = document.getElementById('logs-delete-dropdown');
    dropdown.classList.toggle('hidden');
}

function closeDeleteDropdown() {
    const dropdown = document.getElementById('logs-delete-dropdown');
    dropdown.classList.add('hidden');
}

function handleDeletePreset(preset) {
    closeDeleteDropdown();
    if (preset === 'custom') {
        openCustomPeriodModal();
    } else {
        const confirmMsg = preset === 'week'
            ? 'Delete all log entries from the last week (excluding the most recent 48 hours)?'
            : 'Delete all log entries from the last month (excluding the most recent 48 hours)?';
        if (confirm(confirmMsg + ' This action cannot be undone.')) {
            deleteLogs({ preset });
        }
    }
}

function openCustomPeriodModal() {
    const modal = document.getElementById('logs-custom-modal');
    modal.classList.remove('hidden');

    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000);
    const endInput = document.getElementById('logs-custom-end');
    endInput.value = formatDatetimeLocal(cutoff);

    const startDefault = new Date(cutoff.getTime() - 7 * 24 * 60 * 60 * 1000);
    document.getElementById('logs-custom-start').value = formatDatetimeLocal(startDefault);
}

function closeCustomPeriodModal() {
    const modal = document.getElementById('logs-custom-modal');
    modal.classList.add('hidden');
}

function formatDatetimeLocal(date) {
    const pad = (n) => n.toString().padStart(2, '0');
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function confirmCustomPeriodDelete() {
    const startStr = document.getElementById('logs-custom-start').value;
    const endStr = document.getElementById('logs-custom-end').value;
    if (!startStr || !endStr) {
        alert('Please select both start and end date/time.');
        return;
    }
    const start = new Date(startStr);
    const end = new Date(endStr);
    if (start > end) {
        alert('Start date/time must be before or equal to end date/time.');
        return;
    }
    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000);
    if (end > cutoff) {
        if (!confirm(`The selected end time is within the 48-hour protection window. Only entries older than 48 hours will be deleted. Continue?`)) {
            return;
        }
    }
    closeCustomPeriodModal();
    deleteLogs({ start: start.toISOString(), end: end.toISOString() });
}

// --- Auto Refresh ---

function startAutoRefresh() {
    stopAutoRefresh();
    refreshInterval = setInterval(() => {
        if (currentPage === 'path-detail') {
            refreshPathRuntime();
        } else if (currentPage !== 'config-global' && currentPage !== 'config-paths') {
            loadPageData(currentPage);
        }
    }, 5000);
}

function stopAutoRefresh() {
    if (refreshInterval) clearInterval(refreshInterval);
}

document.getElementById('refresh-btn').addEventListener('click', () => {
    loadPageData(currentPage);
});

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    initPathModalEvents();
    initTooltips();


    window.addEventListener('hashchange', handleHashChange);


    const initialPage = getPageFromHash();
    currentRoute = window.location.hash;
    navigateToPage(initialPage, getPathNameFromHash());

    startAutoRefresh();
});


window.addEventListener('beforeunload', stopAutoRefresh);

function initTooltips() {
    const tooltip = document.createElement('div');
    tooltip.id = 'global-tooltip';
    tooltip.setAttribute('role', 'tooltip');
    tooltip.className = 'fixed z-50 hidden max-w-xs rounded bg-gray-900 px-3 py-2 text-xs text-white shadow-lg';
    tooltip.style.pointerEvents = 'none';
    document.body.appendChild(tooltip);

    let activeTrigger = null;
    let pinnedTrigger = null;

    function showTooltip(trigger) {
        if (!trigger?.dataset.tooltip) return;

        activeTrigger = trigger;
        tooltip.textContent = trigger.dataset.tooltip;
        tooltip.classList.remove('hidden');
        trigger.setAttribute('aria-describedby', tooltip.id);
        trigger.setAttribute('aria-expanded', 'true');

        const bounds = trigger.getBoundingClientRect();
        const left = Math.min(
            Math.max(8, bounds.left + bounds.width / 2 - tooltip.offsetWidth / 2),
            window.innerWidth - tooltip.offsetWidth - 8,
        );
        const above = bounds.top - tooltip.offsetHeight - 8;
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${above >= 8 ? above : bounds.bottom + 8}px`;
    }

    function hideTooltip() {
        activeTrigger?.removeAttribute('aria-describedby');
        activeTrigger?.setAttribute('aria-expanded', 'false');
        activeTrigger = null;
        pinnedTrigger = null;
        tooltip.classList.add('hidden');
    }

    document.addEventListener('pointerover', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger && !trigger.contains(event.relatedTarget) && !pinnedTrigger) {
            showTooltip(trigger);
        }
    });

    document.addEventListener('pointerout', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger && !trigger.contains(event.relatedTarget) && trigger !== pinnedTrigger) {
            hideTooltip();
        }
    });

    document.addEventListener('focusin', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger && !pinnedTrigger) showTooltip(trigger);
    });

    document.addEventListener('focusout', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger && trigger !== pinnedTrigger) hideTooltip();
    });

    document.addEventListener('click', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger) {
            event.preventDefault();
            event.stopPropagation();
            if (trigger === pinnedTrigger) {
                hideTooltip();
            } else {
                pinnedTrigger = trigger;
                showTooltip(trigger);
            }
        } else if (pinnedTrigger) {
            hideTooltip();
        }
    });

    document.addEventListener('keydown', event => {
        const trigger = event.target.closest('[data-tooltip]');
        if (trigger && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            trigger.click();
        } else if (event.key === 'Escape' && activeTrigger) {
            const triggerToRefocus = pinnedTrigger || activeTrigger;
            hideTooltip();
            triggerToRefocus.focus();
        }
    });

    window.addEventListener('scroll', () => {
        if (activeTrigger) showTooltip(activeTrigger);
    }, true);
    window.addEventListener('resize', () => {
        if (activeTrigger) showTooltip(activeTrigger);
    });
}
