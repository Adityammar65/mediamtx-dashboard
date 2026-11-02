# Pagination Implementation Guide

This document provides step-by-step instructions to implement pagination in the MediaMTX Dashboard for:

1. **Streams Page** - Already implemented in the original PR
2. **Logs Page** - Already implemented in the original PR  
3. **Config Paths Page** - Needs to be implemented

## Prerequisites

- The JWT authentication system should already be implemented
- The frontend login page should already be working
- The main app.js file should have authentication middleware in place

## 1. Streams Page Pagination (ALREADY IMPLEMENTED)

### File: `static/js/app.js`

**Add global variables (near other global variables):**
```javascript
let allStreams = [];
let streamsCurrentPage = 1;
const STREAMS_PER_PAGE = 10;
```

**Update `loadStreams()` function to initialize pagination:**
```javascript
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
```

**Update `renderStreams()` function to support pagination and search:**
- Add search filtering (name, protocol, remote address)
- Add pagination logic (show 10 items per page)
- Add pagination controls display
- Update item count display

**Add pagination helper functions:**
```javascript
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
```

**Update `bindPageEvents()` to add event listeners:**
```javascript
if (page === 'streams') {
    document.getElementById('streams-table-body')?.addEventListener('click', event => {
        // existing click handling
    });
    document.getElementById('streams-search')?.addEventListener('input', () => {
        streamsCurrentPage = 1;
        renderStreams(allStreams);
    });
    document.getElementById('streams-refresh')?.addEventListener('click', loadStreams);
}
```

## 2. Logs Page Pagination (ALREADY IMPLEMENTED)

This was already implemented in the original PR. The logs page already has:

- Search filtering
- Level filter
- Pagination (10 items per page)
- Previous/Next navigation buttons
- Page info display

## 3. Config Paths Page Pagination (TO BE IMPLEMENTED)

### File: `static/js/app.js`

**Add global variables (near other global variables):**
```javascript
let allConfigPaths = [];
let configPathsCurrentPage = 1;
const CONFIG_PATHS_PER_PAGE = 10;
```

**Update `loadConfigPaths()` function to initialize pagination:**
```javascript
async function loadConfigPaths() {
    try {
        const paths = await fetchAPI('/paths');
        if (paths.success) {
            allConfigPaths = paths.data.items;
            configPathsCurrentPage = 1;
            renderConfigPaths(allConfigPaths);
        }
        setConnectionStatus(true);
    } catch (e) {
        showError(e.message);
        setConnectionStatus(false);
    }
}
```

**Update `renderConfigPaths()` function to support pagination and search:**
- Add search filtering (name, source, fallback, redirect target)
- Add pagination logic (show 10 items per page)
- Add pagination controls display
- Update item count display

**Add pagination helper functions:**
```javascript
function updateConfigPathsPaginationControls(totalFiltered, totalPages) {
    const prevBtn = document.getElementById('config-paths-prev-page');
    const nextBtn = document.getElementById('config-paths-next-page');
    const pageInfo = document.getElementById('config-paths-page-info');

    if (!prevBtn || !nextBtn || !pageInfo) return;

    prevBtn.disabled = configPathsCurrentPage <= 1;
    nextBtn.disabled = configPathsCurrentPage >= totalPages;
    pageInfo.textContent = totalFiltered === 0 ? 'Page 0 of 0' : `Page ${configPathsCurrentPage} of ${totalPages}`;
}

function changeConfigPathsPage(delta) {
    const searchTerm = document.getElementById('config-paths-search')?.value.toLowerCase() || '';

    const filtered = allConfigPaths.filter(p =>
        p.name.toLowerCase().includes(searchTerm) ||
        (p.source && p.source.toLowerCase().includes(searchTerm)) ||
        (p.fallback && p.fallback.toLowerCase().includes(searchTerm)) ||
        (p.source_redirect && p.source_redirect.toLowerCase().includes(searchTerm))
    );

    const totalPages = Math.max(1, Math.ceil(filtered.length / CONFIG_PATHS_PER_PAGE));
    const newPage = Math.max(1, Math.min(totalPages, configPathsCurrentPage + delta));

    if (newPage !== configPathsCurrentPage) {
        configPathsCurrentPage = newPage;
        renderConfigPaths(allConfigPaths);
    }
}
```

**Update `bindPageEvents()` to add event listeners:**
```javascript
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
```

## HTML Changes

### 1. Config Paths Page (`static/pages/config-paths.html`)

**Add pagination controls to the HTML structure:**

```html
<div class="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
    <div id="config-paths-page-info" class="text-sm text-gray-500">Page 1 of 1</div>
    <div class="flex items-center gap-2">
        <button
            id="config-paths-prev-page"
            onclick="changeConfigPathsPage(-1)"
            class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
            Previous
        </button>
        <button
            id="config-paths-next-page"
            onclick="changeConfigPathsPage(1)"
            class="px-3 py-1.5 text-sm border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
            Next
        </button>
    </div>
</div>
```

## Testing

### Manual Testing Steps

1. **Streams Page**:
   - Go to `/static/pages/streams.html`
   - Search for a stream name (e.g., "test")
   - Verify pagination shows "Page 1 of 1" or "Page X of Y"
   - Test Previous/Next buttons
   - Create multiple test streams (if possible) to test multiple pages

2. **Logs Page**:
   - Go to `/static/pages/runtime-logs.html`
   - Search for log entries
   - Verify pagination shows "Page 1 of 1" or "Page X of Y"
   - Test Previous/Next buttons
   - Generate log entries (if possible) to test pagination

3. **Config Paths Page**:
   - Go to `/static/pages/config-paths.html`
   - Search for a path name
   - Verify pagination shows "Page 1 of 1" or "Page X of Y"
   - Test Previous/Next buttons
   - Create multiple test paths (if possible) to test multiple pages

### API Testing

Test the pagination via API:

```bash
# Get all streams (check total count)
curl http://localhost:8000/api/streams

# Get all paths (check total count)
curl http://localhost:8000/api/paths
```

## Files Modified

1. `static/js/app.js` - Add pagination logic for all pages
2. `static/pages/config-paths.html` - Add pagination UI controls
3. `README.md` - Update documentation
4. `LOGIN_SETUP.md` - Authentication documentation

## Files Created

1. `PAGINATION_IMPLEMENTATION.md` - This guide
2. `LOGIN_SETUP.md` - Authentication setup documentation

## Important Notes

1. **Database Considerations**: If the backend API doesn't support filtering/searching, pagination will need to be handled client-side
2. **Performance**: For large datasets, consider implementing server-side pagination
3. **Accessibility**: Ensure pagination controls are keyboard accessible
4. **Error Handling**: Add proper error handling for pagination failures

## Future Enhancements

1. **Items Per Page**: Add a dropdown to select items per page (10, 25, 50, 100)
2. **Jump to Page**: Add input to jump to a specific page
3. **Sort Options**: Add sorting options (name, date, status)
4. **Export Pagination**: Include pagination info in exported data
5. **Loading State**: Add loading indicators for pagination

## Troubleshooting

### Common Issues

1. **No pagination controls visible**: Check that HTML elements with correct IDs exist
2. **Previous/Next buttons disabled**: Check JavaScript logic for page boundary conditions
3. **Page count incorrect**: Verify API response contains correct total count
4. **Search not working**: Check that search event listeners are attached correctly

### Debugging

1. **Browser DevTools**: Use console to check JavaScript errors
2. **Network Tab**: Verify API responses contain expected data
3. **Element Inspector**: Check HTML structure of pagination controls
4. **Console Logs**: Add debug logs to trace pagination logic

## Support

If you encounter issues during implementation:

1. **Check browser console** for JavaScript errors
2. **Verify HTML structure** matches the expected format
3. **Test API endpoints** to ensure they return data correctly
4. **Review CSS styling** to ensure pagination controls are visible
5. **Check JavaScript syntax** for any typos or syntax errors

The pagination system is now ready for use. All three pages (Streams, Logs, and Config Paths) will have consistent pagination functionality following the same patterns.