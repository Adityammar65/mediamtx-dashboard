─── app.py:249-253 ───
[bug · high] Silently converting blank/whitespace-only passwords to None changes the validation
behavior. Previously this raised HTTPException 400 with "password must be a non-blank string". Now
it becomes None which may skip password update entirely. This could allow users to unintentionally
clear passwords or bypass password requirements. Consider either: (1) keeping the validation error
for blank passwords, or (2) explicitly documenting this behavior change.

  password = payload.get("password")
      if password is not None and not isinstance(password, str):
          raise HTTPException(400, "password must be a string when provided")
      if password is not None and not password.strip():
-         password = None
+         raise HTTPException(400, "password must be a non-blank string")


─── mediamtx_client.py:448-453 ───
[bug · high] When password is None and no cached password exists, the code does nothing (pass) and
doesn't call _remember_internal_user. This means the in-memory cache entry for that user may lose
its password field entirely. Combined with _sync_internal_users_to_json filtering (line 420), users
without a password will be excluded from JSON persistence, effectively losing their credentials from
local cache after non-password updates. The comment says "preserve MediaMTX credential" but the
actual behavior removes the local cache entry.

  saved_password = hashed_password or self._cached_user(previous).get("pass")
-         if saved_password:
+         # Always update cache to preserve existing password when not changing it
-             self._remember_internal_user({**previous, "user": user, "pass": saved_password, "permissions": permissions, "ips": ips if ips is not None else previous.get("ips", [])}, password=saved_password)
+         self._remember_internal_user({**previous, "user": user, "pass": saved_password, "permissions": permissions, "ips": ips if ips is not None else previous.get("ips", [])}, password=saved_password)
-         elif password is None:
-             # No cached password available: preserve MediaMTX credential by leaving cache entry absent.
-             pass


─── mediamtx_client.py:416-422 ───
[bug · medium] The _sync_internal_users_to_json filters out entries where "pass" is None/empty.
Combined with the update_internal_user bug (issue #2), users can disappear from persisted config
after updates that don't include a password. The filter should include users with existing passwords
even if the current update doesn't provide one. Consider changing the filter to only require "id"
and "user", not "pass".

  async def _sync_internal_users_to_json(self):
          entries = [
              dict(entry)
              for entry in MediaMTXClient._ram_internal_users.values()
-             if entry.get("id") is not None and entry.get("user") and entry.get("pass")
+             if entry.get("id") is not None and entry.get("user")
          ]
          await self._queue_save_to_json({"entries": entries})


─── internalUsers.json:91-150 ───
[other · medium] Three users have identical username "p" with different UUIDs. First and third share
the exact same password hash. While this may be test data, duplicate usernames in the user store
could cause authentication ambiguity (which user gets authenticated?) or unexpected behavior if the
system assumes unique usernames. Consider using unique usernames for test data.



─── mediamtx_client.py:24-25 ───
[other · low] The _hash_internal_password function prepends "argon2:" to the hash output. However,
argon2.PasswordHasher().hash() already returns a string starting with "$argon2id$" (the standard PHC
format). The _is_internal_password_hashed checks for both "argon2:" and "sha256:" prefixes. This
means the stored hash will be "argon2:$argon2id$v=19$..." which is correct (custom prefix + PHC
string). But verify that _PW_HASHER.hash() doesn't already include "argon2:" - if it did, you'd get
double prefix. From argon2 library docs, hash() returns PHC format starting with "$argon2id$", so
the current code is correct.



─── mediamtx_client.py:21-24 ───
[maintainability · low] The constant _INTERNAL_HASH_PREFIXES is defined on line 21 but never used.
The _is_internal_password_hashed function uses an inline tuple instead. Either use the constant or
remove it to avoid confusion.

  _INTERNAL_HASH_PREFIXES = ("argon2:", "sha256:")
  
  
- def _hash_internal_password(password: str) -> str:
+ def _is_internal_password_hashed(value) -> bool:
+     return isinstance(value, str) and value.startswith(_INTERNAL_HASH_PREFIXES)


─── mediamtx_client.py:416-422 ───
[bug · medium] _sync_internal_users_to_json() filters out entries where "pass" is falsy (empty
string or None). However, the system loads users with empty passwords from internalUsers.json (e.g.,
the "any" users with "pass": ""). This creates an asymmetry: users without passwords can be loaded
but not persisted, causing them to disappear after any sync operation.

  async def _sync_internal_users_to_json(self):
          entries = [
              dict(entry)
              for entry in MediaMTXClient._ram_internal_users.values()
-             if entry.get("id") is not None and entry.get("user") and entry.get("pass")
+             if entry.get("id") is not None and entry.get("user")
          ]
          await self._queue_save_to_json({"entries": entries})


─── mediamtx_client.py:345-349 ───
[bug · medium] In _restore_after_restart(), users without passwords are skipped (continue on line
349). This means users with empty passwords (like the "any" users) will not be restored to MediaMTX
after a restart, potentially removing valid authentication entries.

  for saved in saved_snapshot:
                  username = saved.get("user", "")
                  saved_password = saved.get("pass")
-                 if not saved_password:
+                 # Allow empty passwords (e.g., "any" users)
+                 if saved_password is None:
                      continue
+                 # If password is empty string, send empty to MediaMTX
+                 hashed_password = _prepare_internal_password(saved_password)
