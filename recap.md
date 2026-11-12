─── mediamtx_client.py:321-336 ───
[bug · high] In `_restore_after_restart`, the `used_ids` set only tracks IDs of matched existing
users from the server (`current`). When a new user is created (the `else` branch at line 346-357),
the newly created user's ID is added to `_ram_internal_users` but NOT to `used_ids`. If there are
multiple legacy entries for the same username in `_ram_internal_users`, each will create a duplicate
user because:
1. First legacy entry: no match in `current`, creates new user with ID "123"
2. Second legacy entry: still no match in `current` (fetched once before loop), creates another new
user with ID "456"

The `used_ids` check at line 334 only prevents matching the same *existing* server user twice, not
preventing duplicate *creation* for the same username.

              current = (await self.list_internal_users()).get("items", [])
              used_ids = set()
              for saved in MediaMTXClient._ram_internal_users.values():
                  username = saved.get("user", "")
                  payload = {
                      "user": username,
                      "pass": saved.get("pass", ""),
                      "ips": saved.get("ips", []),
                      "permissions": saved.get("permissions", []),
                  }
                  entry_id = saved.get("id")
                  match = next((item for item in current if entry_id is not None and str(item.get("id")) == str(entry_id)), None)
                  if match is None and (entry_id is None or str(entry_id).startswith("legacy:")):
                      match = next((item for item in current if item.get("user") == username and str(item.get("id")) not in used_ids), None)
                  if match and match.get("id"):
                      used_ids.add(str(match["id"]))
+                     # ... patch existing
+                 else:
+                     # ... create new
+                     if created.get("id"):
+                         used_ids.add(str(created["id"]))  # Track newly created ID
+                         self._ram_internal_users[str(created["id"])] = {...}


─── mediamtx_client.py:119-132 ───
[bug · medium] In `_remember_internal_user`, the fallback `previous.get("pass", "")` is used when
`password is None`. However, `previous` is fetched from `_ram_internal_users` by `entry_id`. If the
cache entry exists but lacks a "pass" key (e.g., corrupted cache, migration edge case, or legacy
entry without password), an empty string would be persisted as the password.

While current call sites (`create_internal_user` and `update_internal_user`) always pass an explicit
`password` argument, this fallback creates a footgun for future modifications or direct calls to
`_remember_internal_user`.

      @staticmethod
      def _remember_internal_user(item, password=None):
          entry_id = item.get("id")
          if entry_id is None:
              return
          previous = MediaMTXClient._ram_internal_users.get(str(entry_id), {})
+         # Require explicit password; don't silently fall back to empty string
+         if password is None:
+             raise ValueError("_remember_internal_user requires explicit password argument")
          MediaMTXClient._ram_internal_users[str(entry_id)] = {
              "id": entry_id,
              "user": item.get("user", previous.get("user", "")),
-             "pass": password if password is not None else previous.get("pass", ""),
+             "pass": password,
              "ips": item.get("ips", previous.get("ips", [])),
              "permissions": item.get("permissions", previous.get("permissions", [])),
          }
          MediaMTXClient._save_internal_users_cache()


─── app.py:222-224 ───
[maintainability · medium] Both `create_internal_user` and `update_internal_user` validate
`permissions` as a non-empty list (`not permissions` rejects empty lists). This prevents clearing
all permissions for a user (setting to empty list), which may be a legitimate administrative action.
Consider whether empty permissions should be allowed, or at least make the validation consistent
with the API's actual capabilities.

      permissions = payload.get("permissions", [])
-     if not user or not password or not isinstance(permissions, list) or not permissions:
+     if not user or not password or not isinstance(permissions, list):
          raise HTTPException(400, "user, password and permissions are required")
+     # Allow empty permissions list if that's a valid use case


─── static/js/app.js:553-553 ───
[maintainability · medium] Hardcoded business-specific regex default `~^atcs-kota/(.+)`. This should
be configurable (e.g., from settings or a constant) or removed entirely to avoid coupling UI to a
specific deployment. Consider using an empty default or a generic example.

- addPathRow({ path: '~^atcs-kota/(.+)', action: 'read' });
+ addPathRow({ path: '', action: 'read' });


─── static/js/app.js:572-573 ───
[maintainability · medium] During edit, password is cleared and made optional. While backend handles
this correctly (omits password from PATCH if empty), the UI should inform users that leaving it
blank keeps the current password. Add a placeholder or helper text.

  document.getElementById('internal-user-password').value = '';
              document.getElementById('internal-user-password').required = false;
+             document.getElementById('internal-user-password').placeholder = 'Leave blank to keep current password';


─── static/js/app.js:559-559 ───
[maintainability · medium] `body.onclick` handler is reassigned every time `initInternalUsers` runs
(e.g., on each navigation to this page). If the function is called multiple times without page
unload, previous handlers are overwritten (not a leak, but may cause unexpected behavior if other
code also binds to body). Consider using event delegation on a stable container or removing old
handlers before assigning.

- body.onclick = async event => {
+ // Use a dedicated container for delegation
+ const container = document.getElementById('internal-users-body');
+ container.onclick = async event => {


─── static/js/app.js:558-558 ───
[maintainability · medium] Same concern: `pathsEl.onclick` is reassigned on every
`initInternalUsers` call. If the form is reset or re-initialized, the handler is replaced. While not
strictly a bug, using a persistent delegation approach or cleanup would be more robust.

  pathsEl.onclick = event => { if (event.target.closest('[data-remove-path]')) event.target.closest('.rounded.border').remove(); };


─── static/js/app.js:584-585 ───
[bug · high] Validation logic has a bug: the second condition `[...pathsEl.children].some(row =>
!row.querySelector('[data-path-action]:checked'))` triggers an error when ANY row lacks a checked
permission. However, `flatMap` only collects checked permissions, so rows without any checked
permission contribute zero entries to `permissions`. The check correctly rejects the form, but the
error message 'Each path needs at least one permission' is shown even when some rows have
permissions and others don't — it's correct behavior but the message could be clearer. More
critically, if a row has a path but NO checkboxes checked, the path value is still read (via
`row.querySelector('[data-field="path"]').value.trim()`) but discarded since no checkbox is checked.
This is acceptable but consider validating per-row for better UX.

- const permissions = [...pathsEl.children].flatMap(row => [...row.querySelectorAll('[data-path-action]:checked')].map(input => ({ action: input.dataset.pathAction, path: row.querySelector('[data-field="path"]').value.trim() })));
-         if (!permissions.length || [...pathsEl.children].some(row => !row.querySelector('[data-path-action]:checked'))) { status.textContent = 'Each path needs at least one permission.'; return; }
+ const permissions = [...pathsEl.children].flatMap(row => {
+             const path = row.querySelector('[data-field="path"]').value.trim();
+             const checked = [...row.querySelectorAll('[data-path-action]:checked')];
+             if (!checked.length) return [];
+             return checked.map(input => ({ action: input.dataset.pathAction, path }));
+         });
+         const rowsWithoutPermission = [...pathsEl.children].filter(row => !row.querySelector('[data-path-action]:checked'));
+         if (!permissions.length || rowsWithoutPermission.length > 0) {
+             status.textContent = rowsWithoutPermission.length > 0 ? 'Each path row must have at least one permission selected.' : 'At least one permission is required.';
+             return;
+         }


─── static/pages/internal-users.html:6-6 ───
[maintainability · low] The form HTML is a single long line, making it hard to read and maintain.
Consider formatting it across multiple lines for better readability.

- <div class="mt-6 bg-white rounded-lg border border-gray-200 p-6"><h3 class="font-medium mb-4">Add internal user</h3><form id="internal-user-form" class="space-y-4"><div class="grid grid-cols-1 md:grid-cols-2 gap-4"><label class="block text-sm font-medium text-gray-700">Username<input id="internal-user-name" required autocomplete="off" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"></label><label class="block text-sm font-medium text-gray-700">Password<input id="internal-user-password" required type="password" autocomplete="new-password" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"></label></div><label class="block text-sm font-medium text-gray-700">IP Restrictions (comma-separated)<input id="internal-user-ips" placeholder="e.g. 192.168.1.0/24,10.0.0.1" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm"></label><div class="border-t pt-4"><h4 class="font-medium mb-2">Paths & Permissions</h4><div id="internal-user-paths" class="space-y-2"></div><button type="button" id="add-path-btn" class="mt-2 rounded bg-gray-100 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-200">+ Add Path</button></div><input type="hidden" id="internal-user-edit-id"><button class="rounded-md bg-blue-600 px-4 py-2 text-white" type="submit">Add user</button><button type="button" id="cancel-user-edit" class="hidden rounded-md bg-gray-200 px-4 py-2">Cancel edit</button><p id="internal-user-status" class="text-sm text-gray-500"></p></form></div>
+ <div class="mt-6 bg-white rounded-lg border border-gray-200 p-6">
+     <h3 class="font-medium mb-4">Add internal user</h3>
+     <form id="internal-user-form" class="space-y-4">
+         <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
+             <label class="block text-sm font-medium text-gray-700">
+                 Username
+                 <input id="internal-user-name" required autocomplete="off" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2">
+             </label>
+             <label class="block text-sm font-medium text-gray-700">
+                 Password
+                 <input id="internal-user-password" required type="password" autocomplete="new-password" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2">
+             </label>
+         </div>
+         <label class="block text-sm font-medium text-gray-700">
+             IP Restrictions (comma-separated)
+             <input id="internal-user-ips" placeholder="e.g. 192.168.1.0/24,10.0.0.1" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm">
+         </label>
+         <div class="border-t pt-4">
+             <h4 class="font-medium mb-2">Paths & Permissions</h4>
+             <div id="internal-user-paths" class="space-y-2"></div>
+             <button type="button" id="add-path-btn" class="mt-2 rounded bg-gray-100 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-200">+ Add Path</button>
+         </div>
+         <input type="hidden" id="internal-user-edit-id">
+         <button class="rounded-md bg-blue-600 px-4 py-2 text-white" type="submit">Add user</button>
+         <button type="button" id="cancel-user-edit" class="hidden rounded-md bg-gray-200 px-4 py-2">Cancel edit</button>
+         <p id="internal-user-status" class="text-sm text-gray-500"></p>
+     </form>
+ </div>


─── mediamtx_client.py:187-192 ───
[maintainability · medium] In `_queue_save_to_json`, the entire `_ram_internal_users` cache is
replaced with only entries from the server response (`data.get("entries", [])`). Any locally cached
entries not present in the server response (e.g., entries that failed to restore during
`_restore_after_restart` due to transient errors) are permanently lost.

While the cache is designed to mirror server state, this behavior could silently drop entries during
partial sync failures. Consider merging instead of replacing, or at least logging a warning when
entries are dropped.

      async def _queue_save_to_json(self, data: dict):
          async with self._cache_lock:
-             MediaMTXClient._ram_internal_users = {
+             new_entries = {
                  str(entry["id"]): entry for entry in data.get("entries", []) if entry.get("id") is not None
              }
+             # Optionally warn about dropped entries
+             old_keys = set(MediaMTXClient._ram_internal_users.keys())
+             new_keys = set(new_entries.keys())
+             dropped = old_keys - new_keys
+             if dropped:
+                 print(f"[Warning] {len(dropped)} cached internal user entries not present in server sync, dropping: {dropped}")
+             MediaMTXClient._ram_internal_users = new_entries
              MediaMTXClient._save_internal_users_cache()


─── mediamtx_client.py:112-117 ───
[style · low] The `_cached_user` fallback logic uses `next()` to find a legacy entry by username. If
multiple legacy entries exist for the same username (which shouldn't happen in normal operation but
could occur due to cache corruption), it returns the first one arbitrarily. This could return stale
data. Consider adding a warning or ensuring uniqueness.

      def _cached_user(self, item):
          saved = MediaMTXClient._ram_internal_users.get(str(item.get("id")), {})
          if not saved:
-             saved = next((entry for entry in MediaMTXClient._ram_internal_users.values()
-                           if (entry.get("id") is None or str(entry.get("id")).startswith("legacy:")) and entry.get("user") == item.get("user")), {})
+             matches = [entry for entry in MediaMTXClient._ram_internal_users.values()
+                        if (entry.get("id") is None or str(entry.get("id")).startswith("legacy:")) and entry.get("user") == item.get("user")]
+             if len(matches) > 1:
+                 print(f"[Warning] Multiple legacy cache entries found for user '{item.get('user')}', using first")
+             saved = matches[0] if matches else {}
          return saved


─── mediamtx_client.py:103-104 ───
[style · low] Line 104 uses Indonesian error message "Gagal memuat internalUsers.json" while line
141 uses "Gagal memuat cache mediamtx.yml" - both are Indonesian. However, other error messages in
the file use English (e.g., line 359: "Failed to restore configuration after MediaMTX restart").
Consider standardizing all log messages to English for consistency.



─── mediamtx_client.py:412-413 ───
[maintainability · low] In `update_internal_user` (line 412), `self._cached_user(previous)` is
called where `previous` comes from `list_internal_users()` API response. The `_cached_user` method
expects the item to have an "id" key for direct cache lookup. Since `previous` is from the server,
it should have an "id", making the direct lookup work. However, if the cache entry was lost (e.g.,
due to `_queue_save_to_json` replacing the cache), the fallback searches legacy entries by username.
This is a reasonable fallback but worth documenting the expectation that server response items have
"id" fields.



─── app.py:220-223 ───
[bug · high] In `create_internal_user`, `password = str(payload.get("password", ""))` converts a
missing or null password to the string "None" (since `str(None)` == "None"). This passes the `not
password` check (because "None" is truthy), allowing a password of "None" to be set unintentionally.
Should validate the raw value before string conversion.

  user = str(payload.get("user", "")).strip()
-     password = str(payload.get("password", ""))
+     password_raw = payload.get("password")
+     if password_raw is None:
+         password = ""
+     else:
+         password = str(password_raw)
      permissions = payload.get("permissions", [])
      if not user or not password or not isinstance(permissions, list) or not permissions:


─── mediamtx_client.py:323-336 ───
[bug · high] In `_restore_after_restart`, when there are multiple legacy entries (id=None or id
starts with "legacy:") for the same username, the first one matches an existing server user and adds
its ID to `used_ids`. The second legacy entry then fails to match (because the ID is now in
`used_ids`) and falls through to the `else` branch, attempting to CREATE a duplicate user with the
same username. The server will likely reject this with a conflict error.

  for saved in MediaMTXClient._ram_internal_users.values():
                  username = saved.get("user", "")
                  payload = {
                      "user": username,
-                     "pass": saved.get("pass", ""),
-                     "ips": saved.get("ips", []),
-                     "permissions": saved.get("permissions", []),
+                     "pass": saved.get("pass", "") or "",
+                     "ips": saved.get("ips") or [],
+                     "permissions": saved.get("permissions") or [],
                  }
                  entry_id = saved.get("id")
                  match = next((item for item in current if entry_id is not None and str(item.get("id")) == str(entry_id)), None)
                  if match is None and (entry_id is None or str(entry_id).startswith("legacy:")):
                      match = next((item for item in current if item.get("user") == username and str(item.get("id")) not in used_ids), None)
                  if match and match.get("id"):
                      used_ids.add(str(match["id"]))
+                     # Update the saved entry's ID to the real ID to prevent duplicate processing
+                     if str(saved.get("id", "")).startswith("legacy:") or saved.get("id") is None:
+                         saved["id"] = match["id"]


─── mediamtx_client.py:325-330 ───
[bug · medium] In `_restore_after_restart`, the payload uses `saved.get("ips", [])` and
`saved.get("permissions", [])`. If the cache contains explicit `null` values for these keys (e.g.,
from a corrupted cache or migration), `.get()` returns `None` instead of the default `[]`, sending
`null` to the MediaMTX API which expects arrays. Use `or []` to handle `None` values.

  payload = {
                      "user": username,
-                     "pass": saved.get("pass", ""),
-                     "ips": saved.get("ips", []),
-                     "permissions": saved.get("permissions", []),
+                     "pass": saved.get("pass", "") or "",
+                     "ips": saved.get("ips") or [],
+                     "permissions": saved.get("permissions") or [],
                  }


─── mediamtx_client.py:125-131 ───
[bug · medium] In `_remember_internal_user`, `item.get("ips", previous.get("ips", []))` and
`item.get("permissions", previous.get("permissions", []))` don't handle explicit `null` values. If
`item.get("ips")` returns `None` (key exists with null value), it uses `None` instead of falling
back to previous. Use `item.get("ips") or previous.get("ips", [])` to handle both missing keys and
null values.

  MediaMTXClient._ram_internal_users[str(entry_id)] = {
              "id": entry_id,
              "user": item.get("user", previous.get("user", "")),
              "pass": password if password is not None else previous.get("pass", ""),
-             "ips": item.get("ips", previous.get("ips", [])),
-             "permissions": item.get("permissions", previous.get("permissions", [])),
+             "ips": item.get("ips") or previous.get("ips", []),
+             "permissions": item.get("permissions") or previous.get("permissions", []),
          }


─── mediamtx_client.py:390-399 ───
[performance · medium] Multiple methods (`create_internal_user`, `update_internal_user`,
`delete_internal_user`, `_restore_after_restart`, `_remember_internal_user`) modify the shared
class-level `_ram_internal_users` dictionary without using the `_cache_lock`. This can cause race
conditions when concurrent requests modify the cache, leading to lost updates or inconsistent state.
Consider protecting all cache mutations with `_cache_lock`.

  async def create_internal_user(self, user: str, password: str, permissions: list[dict], ips: list[str] | None = None):
          payload = {"user": user, "pass": password, "ips": ips or [], "permissions": permissions}
          response = await self.client.post(f"{self.base_url}/config/internal-users/add", json=payload)
          response.raise_for_status()
          created = response.json()
          if created.get("id"):
+             async with self._cache_lock:
-             self._remember_internal_user(created, password=password)
+                 self._remember_internal_user(created, password=password)
              await self._sync_internal_users_to_json()
              return created
          return created


─── mediamtx_client.py:390-390 ───
[style · low] The type hints `list[dict]` and `list[str] | None` use Python 3.9+ syntax (`list` as
generic, `|` for union). If the project targets Python < 3.9, this will cause syntax errors.
Consider using `List[Dict]` and `Optional[List[str]]` from `typing` module for compatibility.

- async def create_internal_user(self, user: str, password: str, permissions: list[dict], ips: list[str] | None = None):
+ from typing import List, Dict, Optional
+ 
+ async def create_internal_user(self, user: str, password: str, permissions: List[Dict], ips: Optional[List[str]] = None):


─── app.py:225-225 ───
[style · low] The validation `not permission.get("action")` rejects empty string actions, but `not
isinstance(permission.get("path"), str)` allows empty string paths (since `isinstance("", str)` is
True). An empty path might be invalid for MediaMTX permissions. Consider also validating that `path`
is non-empty.

- if any(not isinstance(permission, dict) or not permission.get("action") or not isinstance(permission.get("path"), str) for permission in permissions):
+ if any(not isinstance(permission, dict) or not permission.get("action") or not isinstance(permission.get("path"), str) or not permission.get("path") for permission in permissions):


─── static/js/app.js:582-596 ───
[bug · high] Form submission lacks validation for empty username and debouncing. If username is
empty, backend will reject with 400 but UI doesn't prevent submission. Also, no submit button
disabling during request allows multiple rapid submissions. On error, initInternalUsers() is not
called so the handler persists, enabling repeated submissions.

  form.onsubmit = async event => {
          event.preventDefault();
+         const submitBtn = form.querySelector('button[type="submit"]');
+         if (submitBtn.disabled) return;
+         const user = document.getElementById('internal-user-name').value.trim();
+         if (!user) { status.textContent = 'Username is required.'; return; }
          const permissions = [...pathsEl.children].flatMap(row => [...row.querySelectorAll('[data-path-action]:checked')].map(input => ({ action: input.dataset.pathAction, path: row.querySelector('[data-field="path"]').value.trim() })));
          if (!permissions.length || [...pathsEl.children].some(row => !row.querySelector('[data-path-action]:checked'))) { status.textContent = 'Each path needs at least one permission.'; return; }
-         const user = document.getElementById('internal-user-name').value.trim();
          const password = document.getElementById('internal-user-password').value;
          const ips = document.getElementById('internal-user-ips').value.split(',').map(ip => ip.trim()).filter(Boolean);
          const userId = document.getElementById('internal-user-edit-id').value;
+         submitBtn.disabled = true;
+         const originalText = submitBtn.textContent;
          try {
              if (userId) await fetchAPI(`/internal-users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify({ user, password, ips, permissions }) });
              else await fetchAPI('/internal-users', { method: 'POST', body: JSON.stringify({ user, password, ips, permissions }) });
              status.textContent = 'Saved.';
              await initInternalUsers();
-         } catch (error) { status.textContent = error.message; }
+         } catch (error) { 
+             status.textContent = error.message; 
+             submitBtn.disabled = false;
+             submitBtn.textContent = originalText;
+         }
      };


─── static/js/app.js:559-581 ───
[maintainability · medium] The edit flow doesn't validate that `item` exists before accessing its
properties. If `users.find()` returns undefined (e.g., race condition or data inconsistency),
accessing `item.id` will throw TypeError. Also, the form is populated even if the item has no
permissions (pathsEl gets empty).

  body.onclick = async event => {
          const button = event.target.closest('button[data-action]');
          if (!button) return;
          const row = button.closest('tr');
          const item = users.find(user => String(user.id) === row.dataset.userId);
+         if (!item) { showError('User not found'); return; }
          try {
              if (button.dataset.action === 'delete') {
                  await fetchAPI(`/internal-users/${encodeURIComponent(row.dataset.userId)}`, { method: 'DELETE' });
                  await initInternalUsers();
                  return;
              }
              document.getElementById('internal-user-edit-id').value = item.id;
              document.getElementById('internal-user-name').value = item.user || '';
              document.getElementById('internal-user-password').value = '';
              document.getElementById('internal-user-password').required = false;
              document.getElementById('internal-user-ips').value = (item.ips || []).join(', ');
              document.getElementById('cancel-user-edit').classList.remove('hidden');
              form.querySelector('button[type="submit"]').textContent = 'Save changes';
              pathsEl.replaceChildren();
              (item.permissions || []).forEach(addPathRow);
              form.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } catch (error) { showError(error.message); }
      };


─── static/js/app.js:591-591 ───
[bug · medium] During edit (PATCH), password is sent as empty string ('') if user leaves it blank.
The backend's update_internal_user expects password to be optional (password: str | None). Sending
empty string may cause unexpected behavior - the backend should only update password if a non-empty
value is provided. The UI should omit password from PATCH payload when empty.

- if (userId) await fetchAPI(`/internal-users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify({ user, password, ips, permissions }) });
+ const payload = { user, ips, permissions };
+             if (password) payload.password = password;
+             if (userId) await fetchAPI(`/internal-users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify(payload) });


─── static/js/app.js:531-536 ───
[security · low] The `actions` string is built by mapping and joining with `escapeHtml` on
individual components, then the whole string is passed to `escapeHtml` again. This double-escaping
is safe but redundant. However, if any permission object has unexpected properties (like HTML in
action/path), the first escapeHtml protects them. It's correct but the double-escape is unnecessary.

- body.innerHTML = users.map(item => {
-             const permissions = item.permissions || [];
-             const rows = permissions.map(p => `<div class="font-mono text-xs">${escapeHtml(p.path || '(global)')} <span class="font-sans text-gray-500">[${escapeHtml(p.action)}]</span></div>`).join('');
-             const actions = permissions.map(p => `${escapeHtml(p.action)}:${escapeHtml(p.path || '(global)')}`).join(', ');
+ const actions = permissions.map(p => `${escapeHtml(p.action)}:${escapeHtml(p.path || '(global)')}`).join(', ');
-             return `<tr data-user-id="${escapeHtml(item.id || '')}"><td class="px-6 py-3 font-mono text-sm">${escapeHtml(item.user || '')}</td><td class="px-6 py-3">${rows}</td><td class="px-6 py-3 text-xs">${escapeHtml(actions)}</td><td class="px-6 py-3 text-xs">${escapeHtml((item.ips || []).join(', '))}</td><td class="px-6 py-3 text-xs font-mono">${escapeHtml(item.id || '')}</td><td class="px-6 py-3 whitespace-nowrap"><button type="button" data-action="edit" class="mr-2 rounded bg-blue-600 px-3 py-1 text-white">Edit</button><button type="button" data-action="delete" class="rounded bg-red-600 px-3 py-1 text-white">Delete</button></td></tr>`;
-         }).join('') || '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500">No users configured</td></tr>';
+             // ... rest unchanged


─── static/js/app.js:527-530 ───
[maintainability · low] The `users` variable is declared with `let` and reassigned in the try block.
It could be declared with `const` by moving the assignment into the declaration, or by using a
separate constant for the sorted array. Using `let` when `const` would suffice reduces code clarity.

- let users = [];
-     try {
-         const result = await fetchAPI('/internal-users');
-         users = (result.data || []).sort((a, b) => String(a.user || '').localeCompare(String(b.user || '')));
+ const users = (result.data || []).sort((a, b) => String(a.user || '').localeCompare(String(b.user || '')));


─── static/pages/internal-users.html:6-6 ───
[maintainability · low] The form HTML is a single very long line, making it difficult to read, diff,
and maintain. This was already noted in confirmed findings. Additionally, the password input lacks a
placeholder or helper text to indicate that leaving it blank during edit keeps the current password
(as mentioned in confirmed findings).

- <div class="mt-6 bg-white rounded-lg border border-gray-200 p-6"><h3 class="font-medium mb-4">Add internal user</h3><form id="internal-user-form" class="space-y-4"><div class="grid grid-cols-1 md:grid-cols-2 gap-4"><label class="block text-sm font-medium text-gray-700">Username<input id="internal-user-name" required autocomplete="off" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"></label><label class="block text-sm font-medium text-gray-700">Password<input id="internal-user-password" required type="password" autocomplete="new-password" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"></label></div><label class="block text-sm font-medium text-gray-700">IP Restrictions (comma-separated)<input id="internal-user-ips" placeholder="e.g. 192.168.1.0/24,10.0.0.1" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm"></label><div class="border-t pt-4"><h4 class="font-medium mb-2">Paths & Permissions</h4><div id="internal-user-paths" class="space-y-2"></div><button type="button" id="add-path-btn" class="mt-2 rounded bg-gray-100 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-200">+ Add Path</button></div><input type="hidden" id="internal-user-edit-id"><button class="rounded-md bg-blue-600 px-4 py-2 text-white" type="submit">Add user</button><button type="button" id="cancel-user-edit" class="hidden rounded-md bg-gray-200 px-4 py-2">Cancel edit</button><p id="internal-user-status" class="text-sm text-gray-500"></p></form></div>
+ <div class="mt-6 bg-white rounded-lg border border-gray-200 p-6">
+   <h3 class="font-medium mb-4">Add internal user</h3>
+   <form id="internal-user-form" class="space-y-4">
+     <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
+       <label class="block text-sm font-medium text-gray-700">
+         Username
+         <input id="internal-user-name" required autocomplete="off" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2">
+       </label>
+       <label class="block text-sm font-medium text-gray-700">
+         Password
+         <input id="internal-user-password" required type="password" autocomplete="new-password" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2" placeholder="Leave blank to keep current password">
+       </label>
+     </div>
+     <label class="block text-sm font-medium text-gray-700">
+       IP Restrictions (comma-separated)
+       <input id="internal-user-ips" placeholder="e.g. 192.168.1.0/24,10.0.0.1" class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 font-mono text-sm">
+     </label>
+     <div class="border-t pt-4">
+       <h4 class="font-medium mb-2">Paths & Permissions</h4>
+       <div id="internal-user-paths" class="space-y-2"></div>
+       <button type="button" id="add-path-btn" class="mt-2 rounded bg-gray-100 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-200">+ Add Path</button>
+     </div>
+     <input type="hidden" id="internal-user-edit-id">
+     <button class="rounded-md bg-blue-600 px-4 py-2 text-white" type="submit">Add user</button>
+     <button type="button" id="cancel-user-edit" class="hidden rounded-md bg-gray-200 px-4 py-2">Cancel edit</button>
+     <p id="internal-user-status" class="text-sm text-gray-500"></p>
+   </form>
+ </div>


─── static/js/app.js:522-598 ───
[performance · medium] The `initInternalUsers` function is called recursively after delete and save
operations. If a user rapidly clicks delete/save, multiple in-flight requests can trigger multiple
re-initializations, potentially causing race conditions and UI flickering. The function should guard
against concurrent execution.

+ let initInternalUsersLoading = false;
+ 
  async function initInternalUsers() {
-     const form = document.getElementById('internal-user-form');
-     const body = document.getElementById('internal-users-body');
-     const status = document.getElementById('internal-user-status');
-     if (!body) return;
-     let users = [];
-     try {
-         const result = await fetchAPI('/internal-users');
-         users = (result.data || []).sort((a, b) => String(a.user || '').localeCompare(String(b.user || '')));
-         body.innerHTML = users.map(item => {
-             const permissions = item.permissions || [];
-             const rows = permissions.map(p => `<div class="font-mono text-xs">${escapeHtml(p.path || '(global)')} <span class="font-sans text-gray-500">[${escapeHtml(p.action)}]</span></div>`).join('');
-             const actions = permissions.map(p => `${escapeHtml(p.action)}:${escapeHtml(p.path || '(global)')}`).join(', ');
-             return `<tr data-user-id="${escapeHtml(item.id || '')}"><td class="px-6 py-3 font-mono text-sm">${escapeHtml(item.user || '')}</td><td class="px-6 py-3">${rows}</td><td class="px-6 py-3 text-xs">${escapeHtml(actions)}</td><td class="px-6 py-3 text-xs">${escapeHtml((item.ips || []).join(', '))}</td><td class="px-6 py-3 text-xs font-mono">${escapeHtml(item.id || '')}</td><td class="px-6 py-3 whitespace-nowrap"><button type="button" data-action="edit" class="mr-2 rounded bg-blue-600 px-3 py-1 text-white">Edit</button><button type="button" data-action="delete" class="rounded bg-red-600 px-3 py-1 text-white">Delete</button></td></tr>`;
-         }).join('') || '<tr><td colspan="6" class="px-6 py-8 text-center text-gray-500">No users configured</td></tr>';
-     } catch (error) { body.innerHTML = `<tr><td colspan="6" class="px-6 py-8 text-center text-red-600">${escapeHtml(error.message)}</td></tr>`; }
-     const pathsEl = document.getElementById('internal-user-paths');
-     const actions = ['read', 'publish', 'playback', 'api', 'metrics', 'pprof'];
-     const addPathRow = permission => {
-         const row = document.createElement('div');
-         row.className = 'rounded border p-3';
-         row.innerHTML = `<div class="flex gap-2"><input data-field="path" class="min-w-0 flex-1 rounded border px-2 py-1 font-mono text-sm" placeholder="Path or regex" value="${escapeHtml(permission?.path || '')}" required><button type="button" data-remove-path class="rounded bg-red-50 px-2 text-red-600">Remove</button></div><div class="mt-2 flex flex-wrap gap-3 text-xs">${actions.map(action => `<label><input type="checkbox" data-path-action="${action}" ${permission?.action === action ? 'checked' : ''}> ${action}</label>`).join('')}</div>`;
-         pathsEl.append(row);
-     };
-     const resetForm = () => {
-         form.reset();
-         document.getElementById('internal-user-edit-id').value = '';
-         document.getElementById('internal-user-password').required = true;
-         document.getElementById('cancel-user-edit').classList.add('hidden');
-         form.querySelector('button[type="submit"]').textContent = 'Add user';
-         pathsEl.replaceChildren();
-         addPathRow({ path: '~^atcs-kota/(.+)', action: 'read' });
-     };
-     resetForm();
-     document.getElementById('add-path-btn').onclick = () => addPathRow({});
-     document.getElementById('cancel-user-edit').onclick = resetForm;
-     pathsEl.onclick = event => { if (event.target.closest('[data-remove-path]')) event.target.closest('.rounded.border').remove(); };
-     body.onclick = async event => {
-         const button = event.target.closest('button[data-action]');
-         if (!button) return;
-         const row = button.closest('tr');
-         const item = users.find(user => String(user.id) === row.dataset.userId);
+     if (initInternalUsersLoading) return;
+     initInternalUsersLoading = true;
-         try {
+     try {
-             if (button.dataset.action === 'delete') {
-                 await fetchAPI(`/internal-users/${encodeURIComponent(row.dataset.userId)}`, { method: 'DELETE' });
-                 await initInternalUsers();
-                 return;
+         // ... existing implementation
+     } finally {
+         initInternalUsersLoading = false;
-             }
+     }
-             document.getElementById('internal-user-edit-id').value = item.id;
-             document.getElementById('internal-user-name').value = item.user || '';
-             document.getElementById('internal-user-password').value = '';
-             document.getElementById('internal-user-password').required = false;
-             document.getElementById('internal-user-ips').value = (item.ips || []).join(', ');
-             document.getElementById('cancel-user-edit').classList.remove('hidden');
-             form.querySelector('button[type="submit"]').textContent = 'Save changes';
-             pathsEl.replaceChildren();
-             (item.permissions || []).forEach(addPathRow);
-             form.scrollIntoView({ behavior: 'smooth', block: 'start' });
-         } catch (error) { showError(error.message); }
-     };
-     form.onsubmit = async event => {
-         event.preventDefault();
-         const permissions = [...pathsEl.children].flatMap(row => [...row.querySelectorAll('[data-path-action]:checked')].map(input => ({ action: input.dataset.pathAction, path: row.querySelector('[data-field="path"]').value.trim() })));
-         if (!permissions.length || [...pathsEl.children].some(row => !row.querySelector('[data-path-action]:checked'))) { status.textContent = 'Each path needs at least one permission.'; return; }
-         const user = document.getElementById('internal-user-name').value.trim();
-         const password = document.getElementById('internal-user-password').value;
-         const ips = document.getElementById('internal-user-ips').value.split(',').map(ip => ip.trim()).filter(Boolean);
-         const userId = document.getElementById('internal-user-edit-id').value;
-         try {
-             if (userId) await fetchAPI(`/internal-users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify({ user, password, ips, permissions }) });
-             else await fetchAPI('/internal-users', { method: 'POST', body: JSON.stringify({ user, password, ips, permissions }) });
-             status.textContent = 'Saved.';
-             await initInternalUsers();
-         } catch (error) { status.textContent = error.message; }
-     };
-     loadConfigPathGroups();
  }


─── static/js/app.js:582-597 ───
[maintainability · low] The `loadConfigPathGroups()` call at the end of `initInternalUsers()` seems
unnecessary for the internal-users page. It loads path groups data used by the config-paths page.
This creates an unnecessary API call and coupling between pages. It should be removed or moved to
the config-paths page initialization.

- form.onsubmit = async event => {
-         event.preventDefault();
-         const permissions = [...pathsEl.children].flatMap(row => [...row.querySelectorAll('[data-path-action]:checked')].map(input => ({ action: input.dataset.pathAction, path: row.querySelector('[data-field="path"]').value.trim() })));
-         if (!permissions.length || [...pathsEl.children].some(row => !row.querySelector('[data-path-action]:checked'))) { status.textContent = 'Each path needs at least one permission.'; return; }
-         const user = document.getElementById('internal-user-name').value.trim();
-         const password = document.getElementById('internal-user-password').value;
-         const ips = document.getElementById('internal-user-ips').value.split(',').map(ip => ip.trim()).filter(Boolean);
-         const userId = document.getElementById('internal-user-edit-id').value;
-         try {
-             if (userId) await fetchAPI(`/internal-users/${encodeURIComponent(userId)}`, { method: 'PATCH', body: JSON.stringify({ user, password, ips, permissions }) });
-             else await fetchAPI('/internal-users', { method: 'POST', body: JSON.stringify({ user, password, ips, permissions }) });
-             status.textContent = 'Saved.';
-             await initInternalUsers();
-         } catch (error) { status.textContent = error.message; }
-     };
-     loadConfigPathGroups();
+ // Remove loadConfigPathGroups() call from here; it belongs in config-paths page init


─── static/js/app.js:539-545 ───
[bug · medium] The `addPathRow` function uses `permission?.action === action` for checkbox checked
state, but `permission` could be an object with `path` only (no `action`) when called from
`resetForm()` with `{ path: '~^atcs-kota/(.+)', action: 'read' }` or from edit flow where
permissions have both action and path. However, when called from 'Add Path' button with empty object
`{}`, `permission?.action` is undefined, so no checkbox is checked by default. This is fine, but the
path input is marked `required` - if user adds a path row and doesn't fill it, form validation will
fail. Consider making path optional or adding a default.

- const actions = ['read', 'publish', 'playback', 'api', 'metrics', 'pprof'];
-     const addPathRow = permission => {
+ const addPathRow = permission => {
          const row = document.createElement('div');
          row.className = 'rounded border p-3';
-         row.innerHTML = `<div class="flex gap-2"><input data-field="path" class="min-w-0 flex-1 rounded border px-2 py-1 font-mono text-sm" placeholder="Path or regex" value="${escapeHtml(permission?.path || '')}" required><button type="button" data-remove-path class="rounded bg-red-50 px-2 text-red-600">Remove</button></div><div class="mt-2 flex flex-wrap gap-3 text-xs">${actions.map(action => `<label><input type="checkbox" data-path-action="${action}" ${permission?.action === action ? 'checked' : ''}> ${action}</label>`).join('')}</div>`;
+         const pathValue = permission?.path || '';
+         const defaultAction = permission?.action || 'read'; // default to 'read' when adding new path
+         row.innerHTML = `<div class="flex gap-2"><input data-field="path" class="min-w-0 flex-1 rounded border px-2 py-1 font-mono text-sm" placeholder="Path or regex" value="${escapeHtml(pathValue)}" required><button type="button" data-remove-path class="rounded bg-red-50 px-2 text-red-600">Remove</button></div><div class="mt-2 flex flex-wrap gap-3 text-xs">${actions.map(action => `<label><input type="checkbox" data-path-action="${action}" ${defaultAction === action ? 'checked' : ''}> ${action}</label>`).join('')}</div>`;
          pathsEl.append(row);
      };
