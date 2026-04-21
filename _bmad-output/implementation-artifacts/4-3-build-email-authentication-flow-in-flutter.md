# Story 4.3: Build Email Authentication Flow in Flutter

Status: review

---

## Intention (UX / Why)

**What the user experiences:**
This is the first screen-level feature the user sees. When the app launches for the first time (no stored JWT), the user lands on an email entry screen. They type their email, receive a 6-digit code, enter it, and are silently authenticated. On subsequent launches, the app skips auth entirely and goes straight to the scenario list (or the next onboarding gate — consent screen in Story 4.4).

**Why it matters for the product:**
Without this story, no user can reach any feature in the MVP. The auth flow is the gatekeeper for every subsequent screen: consent (4.4), incoming call (4.5), scenarios (5.x), calls (6.x), debriefs (7.x). It also establishes the Flutter networking layer (Dio client, JWT interceptor, token storage) that every future API call depends on.

**Why it must be invisible:**
The UX spec mandates "zero UI before the first call" — email entry is the one mandatory friction gate, so it must be fast, clear, and feel like a phone contact entry, not a traditional login form. No password field, no "sign up vs. sign in" split, no social login buttons. One field, one button.

**Why no design spec yet:**
The UX design specification marks the onboarding flow as "Design specs TBD" (line 720). This story implements a minimal, functional auth UI using the established design system (dark theme, Inter font, accent colors). Future visual polish can be applied without structural changes. The architecture and acceptance criteria are fully defined — only the pixel-level visual layout is pending.

---

## Concrete User Walk-Through (Adversarial)

_(Per Epic 3 retrospective Action Item #1: every story must contain an adversarial walk-through.)_

### Scenario A — Happy Path (New User)
1. User launches app for the first time. No JWT in `flutter_secure_storage`.
2. GoRouter `redirect` detects no valid token → routes to `/login` (email entry screen).
3. User types `karim@example.com` and taps Submit.
4. AuthBloc dispatches `SubmitEmailEvent` → emits `AuthLoading` → calls `POST /auth/request-code` → on 200, emits `AuthCodeSent` → GoRouter navigates to `/verify` (code verification screen).
5. User receives email, types 6-digit code, taps Verify.
6. AuthBloc dispatches `SubmitCodeEvent` → emits `AuthLoading` → calls `POST /auth/verify-code` → on 200, stores JWT in `flutter_secure_storage`, emits `AuthAuthenticated` → GoRouter redirect detects valid token → routes to `/consent` (next onboarding gate, Story 4.4 — for now, routes to placeholder).

### Scenario B — Happy Path (Returning User)
1. User launches app. JWT exists in `flutter_secure_storage`.
2. GoRouter `redirect` reads stored token → token is present → routes directly to `/` (scenario list placeholder).
3. Auth screens are never shown.

### Scenario C — Invalid Code
1. User enters wrong 6-digit code.
2. API returns `400 {"error": {"code": "AUTH_CODE_INVALID", "message": "Invalid code. Please check and try again."}}`.
3. AuthBloc emits `AuthError("Invalid code. Please check and try again.")`.
4. Code verification screen displays the error message below the input field (no popup dialog). User can re-enter the code.

### Scenario D — Expired Code
1. User waits >15 minutes before entering the code.
2. API returns `400 {"error": {"code": "AUTH_CODE_EXPIRED", "message": "This code has expired. Please request a new one."}}`.
3. Screen displays error message. User taps "Resend code" → AuthBloc dispatches `SubmitEmailEvent` again → new code sent.

### Scenario E — Network Error
1. User has no internet when tapping Submit.
2. Dio throws `DioException` (connection error).
3. AuthBloc catches the exception, emits `AuthError("No internet connection. Please check your network and try again.")`.
4. Screen displays error message with retry affordance.

### Scenario F — Email Delivery Failure
1. User enters email, backend Resend is down.
2. API returns `502 {"error": {"code": "EMAIL_DELIVERY_FAILED", "message": "Could not send email. Please try again."}}`.
3. Screen displays error message. User waits and retries.

### Scenario G — JWT Expiry (30-Day Token)
1. User returns after 31 days. JWT in storage has expired.
2. GoRouter `redirect` reads token → passes to a lightweight expiry check (decode payload without signature verification to read `exp` claim) → expired → routes to `/login`.
3. User re-authenticates. Old JWT is overwritten.

---

## Story

As a **user opening the app for the first time**,
I want **to enter my email and a verification code to sign in**,
So that **I can access the app quickly without remembering a password**.

---

## Dependencies

**Blocks:**
- Story 4.4 (Consent, AI Disclosure, Microphone Permission) — cannot start until auth screens exist and `AuthAuthenticated` state is emittable.
- Story 4.5 (First-Call Incoming Call Experience) — requires authenticated user.
- Story 5.x, 6.x, 7.x — all require the Dio client + JWT interceptor from this story.

**Blocked by:**
- Story 4.2 (FastAPI Server with Passwordless Auth) — **done**. Provides `POST /auth/request-code` and `POST /auth/verify-code` endpoints.
- Story 4.1 (Restructure Flutter Project) — **done**. Provides MVP folder structure, GoRouter, BLoC dependency.
- Story 4.1b (Design System) — **done**. Provides AppColors, AppTypography, AppSpacing, AppTheme.

---

## Acceptance Criteria

### AC1 — GoRouter auth guard redirects unauthenticated users

**Given** the user opens the app without a valid JWT in `flutter_secure_storage`
**When** the app launches
**Then** GoRouter `redirect` routes to `/login` (email entry screen)
**And** the user cannot navigate to any other route without authenticating

### AC2 — Email entry screen sends request-code

**Given** the email entry screen is displayed
**When** the user enters a valid email and taps Submit
**Then** `POST /auth/request-code` is called via Dio with body `{"email": "<input>"}` to the VPS at `http://167.235.63.129`
**And** on 200 response, the user is navigated to the code verification screen
**And** the entered email is passed to the verification screen (displayed as confirmation text)

### AC3 — Code verification screen verifies and stores JWT

**Given** the code verification screen is displayed
**When** the user enters the 6-digit code and taps Verify
**Then** `POST /auth/verify-code` is called with `{"email": "<email>", "code": "<input>"}`
**And** on 200 response, the JWT from `data.token` is stored in `flutter_secure_storage` under key `auth_token`
**And** `data.user_id` is stored under key `user_id`
**And** the user is navigated forward (to consent screen placeholder — `/consent`)

### AC4 — Auth errors display contextually on screen

**Given** authentication fails (invalid code, expired code, network error, email delivery failure)
**When** an error occurs
**Then** a contextual error message is displayed within the screen (below the input field)
**And** no popup dialog or snackbar is shown
**And** the user can retry without navigating away

### AC5 — Returning user skips auth entirely

**Given** the user has a valid (non-expired) JWT stored from a previous session
**When** the app launches
**Then** GoRouter skips the auth flow and navigates directly to `/` (scenario list placeholder)

### AC6 — AuthBloc follows naming conventions

**Given** the AuthBloc manages authentication state
**Then** events are: `SubmitEmailEvent`, `SubmitCodeEvent`, `CheckAuthStatusEvent`
**And** states are: `AuthInitial`, `AuthLoading`, `AuthCodeSent`, `AuthAuthenticated`, `AuthError`
**And** the bloc class is `AuthBloc` extending `Bloc<AuthEvent, AuthState>`

### AC7 — Pre-commit gates pass

**Given** the story is complete
**When** running from `client/`:
```
flutter analyze
flutter test
```
**Then** both pass with zero issues (errors, warnings, AND infos)

---

## Tasks / Subtasks

### Phase 1 — Core Infrastructure (API client + Token storage)

- [x] **1.1** Create `client/lib/core/api/api_client.dart` (AC: 2, 3)
  - Singleton `ApiClient` class wrapping a `Dio` instance
  - Base URL: `http://167.235.63.129` (Caddy on port 80)
  - Default headers: `Content-Type: application/json`
  - JWT interceptor: reads token from `TokenStorage`, adds `Authorization: Bearer <token>` to every request (except `/auth/*` paths)
  - Error interceptor: converts Dio errors to typed `ApiException` with `code` and `message` from the server's `{error: {code, message}}` envelope
  - Connection timeout: 15s, receive timeout: 15s

- [x] **1.2** Create `client/lib/core/api/api_exception.dart` (AC: 4)
  - `ApiException` class with `String code` and `String message` fields
  - Factory `ApiException.fromDioException(DioException e)` that:
    - On `DioExceptionType.connectionError` / `connectionTimeout` → `ApiException(code: 'NETWORK_ERROR', message: 'No internet connection. Please check your network and try again.')`
    - On response with `{error: {code, message}}` body → extracts code + message
    - On other errors → `ApiException(code: 'UNKNOWN_ERROR', message: 'Something went wrong. Please try again.')`

- [x] **1.3** Create `client/lib/core/auth/token_storage.dart` (AC: 3, 5)
  - Wraps `FlutterSecureStorage` with three methods:
    - `Future<void> saveToken(String token)` — writes to key `auth_token`
    - `Future<String?> readToken()` — reads key `auth_token`
    - `Future<void> deleteToken()` — deletes key `auth_token`
    - `Future<void> saveUserId(int userId)` — writes to key `user_id`
    - `Future<int?> readUserId()` — reads key `user_id`, parses to int
  - Constructor accepts `FlutterSecureStorage` as parameter (for testability)
  - Default instance uses `const FlutterSecureStorage()`

### Phase 2 — Auth Repository and BLoC

- [x] **2.1** Create `client/lib/features/auth/data/auth_repository.dart` (AC: 2, 3)
  - `AuthRepository` class with `ApiClient` dependency
  - `Future<void> requestCode(String email)` — POST `/auth/request-code` with `{"email": email}`; throws `ApiException` on failure
  - `Future<AuthResult> verifyCode(String email, String code)` — POST `/auth/verify-code` with `{"email": email, "code": code}`; returns `AuthResult(token, userId, email)` on success; throws `ApiException` on failure

- [x] **2.2** Create `client/lib/features/auth/data/auth_result.dart` (AC: 3)
  - Simple data class: `final String token; final int userId; final String email;`
  - Factory `AuthResult.fromJson(Map<String, dynamic> json)` — maps `json['token']`, `json['user_id']`, `json['email']`

- [x] **2.3** Create `client/lib/features/auth/bloc/auth_event.dart` (AC: 6)
  ```dart
  sealed class AuthEvent {}
  final class CheckAuthStatusEvent extends AuthEvent {}
  final class SubmitEmailEvent extends AuthEvent {
    final String email;
    SubmitEmailEvent(this.email);
  }
  final class SubmitCodeEvent extends AuthEvent {
    final String email;
    final String code;
    SubmitCodeEvent({required this.email, required this.code});
  }
  ```

- [x] **2.4** Create `client/lib/features/auth/bloc/auth_state.dart` (AC: 6)
  ```dart
  sealed class AuthState {}
  final class AuthInitial extends AuthState {}
  final class AuthLoading extends AuthState {}
  final class AuthCodeSent extends AuthState {
    final String email;
    AuthCodeSent(this.email);
  }
  final class AuthAuthenticated extends AuthState {}
  final class AuthError extends AuthState {
    final String message;
    final AuthState previousState;
    AuthError(this.message, {required this.previousState});
  }
  ```
  Note: `AuthError` carries `previousState` so the UI knows whether to show the email screen or the code screen after an error.

- [x] **2.5** Create `client/lib/features/auth/bloc/auth_bloc.dart` (AC: 2, 3, 4, 5, 6)
  - Dependencies: `AuthRepository`, `TokenStorage`
  - `on<CheckAuthStatusEvent>`: reads token from `TokenStorage`; if present and not expired → emit `AuthAuthenticated`; else → emit `AuthInitial`
  - `on<SubmitEmailEvent>`: emit `AuthLoading` → call `authRepository.requestCode(email)` → emit `AuthCodeSent(email)`; on `ApiException` → emit `AuthError(e.message, previousState: state)`
  - `on<SubmitCodeEvent>`: emit `AuthLoading` → call `authRepository.verifyCode(email, code)` → save token + userId via `TokenStorage` → emit `AuthAuthenticated`; on `ApiException` → emit `AuthError(e.message, previousState: AuthCodeSent(email))`
  - JWT expiry check: decode the JWT payload (base64 middle segment) to read `exp` claim; compare with `DateTime.now().millisecondsSinceEpoch ~/ 1000`. No signature verification needed — this is a local staleness check only.

### Phase 3 — Auth Screens

- [x] **3.1** Create `client/lib/features/auth/presentation/email_entry_screen.dart` (AC: 1, 2, 4)
  - Dark theme screen with centered content (vertical center)
  - App title text (using `AppTypography.display` or `headline`)
  - `TextField` for email input with `TextInputType.emailAddress`, `TextInputAction.done`
  - Submit button: `ElevatedButton` or `FilledButton` with `AppColors.accent` background
  - Inline error text below the button (visible only when `AuthError` state, red color `AppColors.destructive`)
  - Loading state: button shows `CircularProgressIndicator` and is disabled
  - On submit: validates email is non-empty and contains `@` (basic client-side check; server does full validation via Pydantic `EmailStr`), then dispatches `SubmitEmailEvent`
  - Keyboard: auto-show on mount via `FocusNode.requestFocus()`

- [x] **3.2** Create `client/lib/features/auth/presentation/code_verification_screen.dart` (AC: 3, 4)
  - Shows confirmation text: "Code sent to karim@example.com" (email from `AuthCodeSent` state)
  - `TextField` for 6-digit code, `TextInputType.number`, `maxLength: 6`
  - Verify button (same styling as submit)
  - "Resend code" text button below — dispatches `SubmitEmailEvent` with the stored email
  - Inline error text (same pattern as email screen)
  - Loading state: button shows `CircularProgressIndicator`
  - On submit: validates code is exactly 6 digits, then dispatches `SubmitCodeEvent`

### Phase 4 — Router Integration

- [x] **4.1** Update `client/lib/app/router.dart` (AC: 1, 5)
  - Add route paths to `AppRoutes`: `login = '/login'`, `verify = '/verify'`, `consent = '/consent'`
  - Add `GoRoute` entries for `/login`, `/verify`, `/consent` (consent is a placeholder `Scaffold` with centered text "Consent — Story 4.4")
  - Implement `redirect` logic:
    - Inject `AuthBloc` (or `TokenStorage`) into `GoRouter` via `refreshListenable` pattern
    - If no stored token AND current path is NOT `/login` or `/verify` → redirect to `/login`
    - If stored token is present AND current path is `/login` or `/verify` → redirect to `/consent` (or `/` if consent is already done — but that's Story 4.4's concern; for now redirect authenticated users to `/`)
  - Remove `_PlaceholderScreen` class (no longer needed — the root route becomes the scenario list placeholder)
  - Root route `/` becomes a placeholder: `Scaffold` with centered text "Scenario List — Story 5.2"

- [x] **4.2** Update `client/lib/app/app.dart` (AC: 1, 5)
  - Wrap `MaterialApp.router` with `BlocProvider<AuthBloc>` at the top of the widget tree
  - AuthBloc is created with `AuthRepository(ApiClient())` and `TokenStorage()`
  - Dispatch `CheckAuthStatusEvent` on bloc creation (so the redirect has token state before the first frame)

### Phase 5 — Tests

- [x] **5.1** Create `client/test/core/api/api_client_test.dart` (AC: 7)
  - Test that JWT interceptor adds `Authorization` header when token exists
  - Test that JWT interceptor skips auth header for `/auth/*` paths
  - Test that error interceptor parses `{error: {code, message}}` body into `ApiException`
  - Test that connection errors produce `NETWORK_ERROR` `ApiException`

- [x] **5.2** Create `client/test/core/auth/token_storage_test.dart` (AC: 7)
  - Test `saveToken` + `readToken` round-trip
  - Test `readToken` returns null when empty
  - Test `deleteToken` clears the value
  - Test `saveUserId` + `readUserId` round-trip
  - Note: `flutter_secure_storage` requires `FlutterSecureStorage.setMockInitialValues({})` in `setUp` for test environment

- [x] **5.3** Create `client/test/features/auth/bloc/auth_bloc_test.dart` (AC: 6, 7)
  - Use `bloc_test` package (`BlocTest` / `blocTest` function)
  - Mock `AuthRepository` and `TokenStorage` with `mocktail`
  - Test `CheckAuthStatusEvent` → `AuthAuthenticated` when token exists and not expired
  - Test `CheckAuthStatusEvent` → `AuthInitial` when no token
  - Test `SubmitEmailEvent` → `[AuthLoading, AuthCodeSent]` on success
  - Test `SubmitEmailEvent` → `[AuthLoading, AuthError]` on `ApiException`
  - Test `SubmitCodeEvent` → `[AuthLoading, AuthAuthenticated]` on success (verify `TokenStorage.saveToken` called)
  - Test `SubmitCodeEvent` → `[AuthLoading, AuthError]` on `ApiException`

- [x] **5.4** Create `client/test/features/auth/presentation/email_entry_screen_test.dart` (AC: 7)
  - Widget test: renders email field and submit button
  - Widget test: submit dispatches `SubmitEmailEvent`
  - Widget test: shows error text when `AuthError` state
  - Widget test: shows loading indicator when `AuthLoading` state

- [x] **5.5** Create `client/test/features/auth/presentation/code_verification_screen_test.dart` (AC: 7)
  - Widget test: renders code field, verify button, resend button
  - Widget test: verify dispatches `SubmitCodeEvent`
  - Widget test: resend dispatches `SubmitEmailEvent`
  - Widget test: shows error text when `AuthError` state

- [x] **5.6** Update `client/test/app_test.dart` (AC: 7)
  - Existing tests reference `_PlaceholderScreen` text "surviveTheTalk — MVP scaffold" — this text will be removed
  - Update tests to account for the new auth flow:
    - Mock `TokenStorage` to return no token → verify email entry screen renders
    - OR: Mock `TokenStorage` to return a valid token → verify placeholder scenario list renders
  - The dynamic type test (textScaler 1.5) should still pass with the new screens

### Phase 6 — Verification

- [x] **6.1** Run `flutter analyze` from `client/` — zero issues (AC: 7)
- [x] **6.2** Run `flutter test` from `client/` — all tests pass (AC: 7)
- [x] **6.3** Update sprint-status.yaml: `4-3-build-email-authentication-flow-in-flutter: review`
- [x] **6.4** Update this story file's status from `ready-for-dev` → `review`

---

## Dev Notes

### API Contract (from Story 4.2 — implemented and tested)

**POST /auth/request-code** (no auth required)
```
Request:  {"email": "user@example.com"}
Success:  200 {"data": {"message": "Code sent"}, "meta": {"timestamp": "2026-04-17T10:30:00Z"}}
Errors:
  422 {"error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "detail": {...}}}
  502 {"error": {"code": "EMAIL_DELIVERY_FAILED", "message": "Could not send email. Please try again."}}
```

**POST /auth/verify-code** (no auth required)
```
Request:  {"email": "user@example.com", "code": "483910"}
Success:  200 {"data": {"token": "eyJ...", "user_id": 1, "email": "user@example.com"}, "meta": {"timestamp": "..."}}
Errors:
  400 {"error": {"code": "AUTH_CODE_INVALID", "message": "Invalid code. Please check and try again."}}
  400 {"error": {"code": "AUTH_CODE_EXPIRED", "message": "This code has expired. Please request a new one."}}
  422 {"error": {"code": "VALIDATION_ERROR", "message": "Request body is invalid.", "detail": {...}}}
```

**Server base URL:** `http://167.235.63.129` (Caddy reverse proxy on port 80; do NOT use `:8000`).

### Library Versions (already in pubspec.yaml — do NOT upgrade)

| Package | Version | Purpose |
|---------|---------|---------|
| flutter_bloc | ^9.1.1 | AuthBloc state management |
| go_router | ^17.2.1 | Route guard + navigation |
| dio | ^5.9.2 | HTTP client + interceptors |
| flutter_secure_storage | ^10.0.0 | JWT storage (iOS Keychain / Android Keystore) |
| bloc_test | ^10.0.0 | BLoC testing utilities (dev dependency) |
| mocktail | ^1.0.5 | Mocking for repository/storage (dev dependency) |

**Do NOT add:** `http` (use Dio), `shared_preferences` (use flutter_secure_storage for tokens), `provider` (use flutter_bloc), `get_it` (manual DI for now), `freezed` (overkill for 5 state classes), `json_serializable` (only 1 model with 3 fields — hand-write `fromJson`).

### Architecture Compliance

- **BLoC naming (architecture.md:492-516):** Events = `VerbNounEvent`, States = `NounStatusState`, Bloc = `FeatureBloc`. Exact names specified in AC6.
- **Folder structure (architecture.md:582-596):**
  ```
  lib/
    features/auth/
      bloc/           → auth_bloc.dart, auth_event.dart, auth_state.dart
      data/           → auth_repository.dart, auth_result.dart
      presentation/   → email_entry_screen.dart, code_verification_screen.dart
    core/
      api/            → api_client.dart, api_exception.dart
      auth/           → token_storage.dart
  ```
- **JSON mapping (architecture.md:470-483):** Server sends `snake_case` → Dart maps to `camelCase` in `fromJson`. Only `AuthResult` needs this: `json['user_id']` → `userId`.
- **Error handling outside calls (architecture.md:639-643):** Loading = `CircularProgressIndicator`. Error = contextual message on screen (no popups). Retry = explicit button.
- **Test structure (architecture.md:598-602):** Tests mirror `lib/` structure in `test/`. File naming: `<module>_test.dart`.

### GoRouter Auth Guard Pattern

The redirect logic reads token synchronously from a cached value (not async):
1. On app start, `AuthBloc` dispatches `CheckAuthStatusEvent` which reads from `TokenStorage` (async).
2. Once the bloc emits `AuthAuthenticated` or `AuthInitial`, the router uses `refreshListenable` (a `GoRouterRefreshStream` wrapping `AuthBloc.stream`) to re-evaluate the redirect.
3. The redirect function checks the current `AuthBloc` state:
   - `AuthAuthenticated` + on `/login` or `/verify` → redirect to `/`
   - Not `AuthAuthenticated` + NOT on `/login` or `/verify` → redirect to `/login`
   - Otherwise → `null` (no redirect)

This avoids async `redirect` (which GoRouter 17.x does not support cleanly) and keeps navigation reactive to auth state changes.

### JWT Expiry Check (Client-Side)

The client does NOT verify the JWT signature — only the server does that. The client only checks `exp` to decide if it should show the login screen or skip to the main app. Implementation:
```dart
bool isTokenExpired(String token) {
  final parts = token.split('.');
  if (parts.length != 3) return true;
  final payload = utf8.decode(base64Url.decode(base64Url.normalize(parts[1])));
  final map = jsonDecode(payload) as Map<String, dynamic>;
  final exp = map['exp'] as int?;
  if (exp == null) return true;
  return DateTime.now().millisecondsSinceEpoch ~/ 1000 >= exp;
}
```
Put this in `token_storage.dart` as a static helper or as a method on `TokenStorage`.

### Design System Usage

Use the design system from Story 4.1b — do NOT create new colors, typography styles, or spacing constants.

- Background: `AppColors.background` (`#1E1F23`)
- Text: `AppColors.textPrimary` (`#F0F0F0`)
- Error text: `AppColors.destructive` (`#E74C3C`)
- Submit/Verify button: `AppColors.accent` (`#00E5A0`)
- Secondary text (email confirmation on verify screen): `AppColors.textSecondary` (`#8A8A95`)
- Input field border: use `AppColors.textSecondary` for unfocused, `AppColors.accent` for focused
- Typography: `AppTypography.headline` for screen title, `AppTypography.body` for labels, `AppTypography.caption` for error messages
- Padding: `AppSpacing.screenHorizontal` (20px) for horizontal margins

### What NOT to Do

- **Do NOT create a separate `AuthService` on top of `AuthRepository`.** The BLoC talks directly to the repository. One layer of indirection is enough.
- **Do NOT verify the JWT signature on the client.** The client checks `exp` only. Signature verification is the server's job (on every API call via the JWT middleware).
- **Do NOT persist auth state in `SharedPreferences` or anywhere besides `flutter_secure_storage`.** The JWT is the single source of auth truth. No separate "isLoggedIn" flag.
- **Do NOT add a "Forgot password" or "Sign out" button.** Passwordless auth has no password to forget. Sign out is not in MVP scope (the token expires after 30 days naturally).
- **Do NOT show snackbars, dialog boxes, or toast notifications for auth errors.** All errors are displayed inline within the screen, per architecture.md error handling rules.
- **Do NOT hardcode the server URL in multiple places.** It lives in `ApiClient` only. Other code accesses the API through `AuthRepository` → `ApiClient`.
- **Do NOT use `Navigator.push` / `Navigator.pop`.** All navigation goes through GoRouter. The auth screens are GoRouter routes, not pushed screens.
- **Do NOT add email format validation beyond basic `contains('@')` on the client.** The server's Pydantic `EmailStr` does full RFC 5322 validation and returns `VALIDATION_ERROR` if the email is malformed. Duplicating that logic on the client creates maintenance drift.
- **Do NOT create `features/auth/models/` directory.** The only model (`AuthResult`) lives in `features/auth/data/` alongside the repository, keeping the feature folder flat.
- **Do NOT add a loading skeleton or shimmer effect.** A `CircularProgressIndicator` is sufficient per architecture spec.
- **Do NOT apply the JWT interceptor to `/auth/request-code` and `/auth/verify-code` calls.** These endpoints are unauthenticated. The interceptor should skip paths starting with `/auth/`.
- **Do NOT change the server code or deploy to VPS in this story.** Story 4.2 already landed the backend. This story is Flutter-only. VPS deployment is deferred to when the full loop (auth + consent + call) can be validated end-to-end.

### Previous Story Intelligence

**From Story 4.2 (done):**
- Server error envelope is `{"error": {"code": "SCREAMING_SNAKE", "message": "Human sentence."}}` — parse `error.code` for programmatic branching and `error.message` for user display.
- `VerifyCodeOut` returns `user_id` alongside `token` specifically so Flutter can stash it without re-decoding the JWT.
- `email` is echoed back in the verify response for belt-and-suspenders confirmation.
- The `AUTH_TOKEN_EXPIRED` error code (from JWT middleware) is distinct from `AUTH_CODE_EXPIRED` (from verify-code endpoint). The Flutter app will encounter `AUTH_TOKEN_EXPIRED` only on future protected API calls (Story 5.x+), not during the auth flow itself.

**From Story 4.1 (done):**
- `router.dart` line 20: `// TODO(4.3): add auth guard` — this is the exact insertion point.
- `router.dart` line 32-33: `_PlaceholderScreen` is "deliberately private" and "removed when Story 4.3 adds the real email entry screen." Remove it.
- `app_test.dart` tests reference `'surviveTheTalk — MVP scaffold'` text from the placeholder — these tests MUST be updated or they'll fail.
- `dependencies_smoke_test.dart` — verify it still passes (it tests package imports, not UI).

**From Story 4.1b (done):**
- Theme is applied via `AppTheme.dark()` in `app.dart`. Auth screens inherit this theme automatically through `MaterialApp.router`.
- `AppColors`, `AppTypography`, `AppSpacing` are all in `core/theme/`. Import paths: `package:client/core/theme/app_colors.dart`, etc.
- `theme_tokens_test.dart` enforces no hardcoded hex values outside theme files — auth screens must use `AppColors.*` constants, not raw `Color(0xFF...)` values.

### PoC Known Issues → Story Impact

All 8 PoC known issues relate to call-time behavior (silence handling, cold start, VAD, TTS). None apply to the Flutter auth flow. This story is unaffected.

### Testing Notes

- **`flutter_secure_storage` in tests:** Call `FlutterSecureStorage.setMockInitialValues({})` in `setUp` or `setUpAll` — without this, tests crash because the native plugin isn't available.
- **`Dio` mocking strategy:** Create a `MockApiClient` with `mocktail` that returns controlled responses. Do NOT mock Dio directly — mock at the repository level for BLoC tests, and at the ApiClient level for repository tests.
- **Widget tests with BLoC:** Use `BlocProvider.value(value: mockAuthBloc)` to inject a mock bloc (created with `MockBloc` from `bloc_test`). Stub states with `whenListen` and `when(() => mockAuthBloc.state).thenReturn(...)`.
- **GoRouter redirect testing:** Test the redirect function directly as a unit test, not through widget tests. Extract the redirect logic into a testable function.

---

## Project Structure Notes

### New files created

```
client/lib/
├── core/
│   ├── api/
│   │   ├── api_client.dart          # NEW — Dio singleton + JWT interceptor
│   │   └── api_exception.dart       # NEW — typed API error
│   └── auth/
│       └── token_storage.dart       # NEW — flutter_secure_storage wrapper
├── features/
│   └── auth/
│       ├── bloc/
│       │   ├── auth_bloc.dart       # NEW — auth state machine
│       │   ├── auth_event.dart      # NEW — sealed events
│       │   └── auth_state.dart      # NEW — sealed states
│       ├── data/
│       │   ├── auth_repository.dart # NEW — API calls for auth
│       │   └── auth_result.dart     # NEW — verify-code response model
│       └── presentation/
│           ├── email_entry_screen.dart         # NEW
│           └── code_verification_screen.dart   # NEW
└── app/
    ├── router.dart                  # MODIFIED — add auth guard + routes
    └── app.dart                     # MODIFIED — add BlocProvider<AuthBloc>
```

### Test files

```
client/test/
├── core/
│   ├── api/
│   │   └── api_client_test.dart              # NEW
│   └── auth/
│       └── token_storage_test.dart           # NEW
├── features/
│   └── auth/
│       ├── bloc/
│       │   └── auth_bloc_test.dart           # NEW
│       └── presentation/
│           ├── email_entry_screen_test.dart   # NEW
│           └── code_verification_screen_test.dart  # NEW
├── app_test.dart                              # MODIFIED — update for auth flow
└── dependencies_smoke_test.dart               # VERIFY — should still pass
```

### Files NOT touched

- `client/lib/main.dart` — bootstrap is unchanged
- `client/lib/core/theme/*` — design system is stable
- `client/test/core/theme/theme_tokens_test.dart` — should pass unchanged
- All `server/` files — Story 4.2 is complete
- `pubspec.yaml` — all dependencies are already present

---

## References

### Source specifications
- `_bmad-output/planning-artifacts/epics.md:768-802` — Story 4.3 epic definition
- `_bmad-output/planning-artifacts/architecture.md:257-264` — Auth strategy (passwordless email + JWT)
- `_bmad-output/planning-artifacts/architecture.md:289-324` — API endpoints and error format
- `_bmad-output/planning-artifacts/architecture.md:325-356` — Flutter MVP structure and packages
- `_bmad-output/planning-artifacts/architecture.md:448-516` — Implementation patterns (naming, BLoC, JSON mapping)
- `_bmad-output/planning-artifacts/architecture.md:628-650` — Error handling and loading state conventions
- `_bmad-output/planning-artifacts/ux-design-specification.md:719-720` — Onboarding flow (design TBD)
- `_bmad-output/planning-artifacts/ux-design-specification.md:807` — User journey flow (email → consent → mic → call)
- `_bmad-output/implementation-artifacts/4-2-build-fastapi-server-with-passwordless-auth-system.md` — Complete backend contract
- `_bmad-output/implementation-artifacts/4-1b-implement-design-system.md` — Design tokens

---

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
- Fixed `prefer_const_constructors` lint warnings on `UnderlineInputBorder` in both auth screens
- Removed unused `flutter_bloc` import from `router.dart`
- Replaced `FakeAuthEvent extends Fake implements AuthEvent` (sealed class restriction) with `registerFallbackValue(CheckAuthStatusEvent())` in all test files
- Renamed `_buildJwt` to `buildJwt` in `token_storage_test.dart` (no_leading_underscores_for_local_identifiers)
- Fixed `verify(...).called(0)` → `verifyNever(...)` in `api_client_test.dart`

### Completion Notes List
- Phase 1: Created `ApiClient` (Dio wrapper + JWT interceptor + error interceptor), `ApiException` (typed errors from Dio), `TokenStorage` (flutter_secure_storage wrapper + JWT expiry check)
- Phase 2: Created `AuthRepository` (requestCode + verifyCode API calls), `AuthResult` (data class with fromJson), `AuthEvent` (sealed: CheckAuthStatus, SubmitEmail, SubmitCode), `AuthState` (sealed: Initial, Loading, CodeSent, Authenticated, Error with previousState), `AuthBloc` (full auth state machine)
- Phase 3: Created `EmailEntryScreen` (dark theme, email TextField, Submit button, inline errors, loading state, auto-focus) and `CodeVerificationScreen` (code TextField, Verify button, Resend button, email confirmation, inline errors)
- Phase 4: Updated `router.dart` (removed _PlaceholderScreen, added /login /verify /consent routes, auth redirect via refreshListenable pattern), updated `app.dart` (BlocProvider<AuthBloc>, StatefulWidget for lifecycle, optional authBloc injection for testing)
- Phase 5: Created 46 tests total covering ApiException parsing, TokenStorage CRUD + JWT expiry, AuthBloc state transitions (7 blocTest cases), EmailEntryScreen widget tests (6 cases), CodeVerificationScreen widget tests (7 cases), updated app_test.dart (3 cases with mock auth)
- Phase 6: `flutter analyze` = No issues found, `flutter test` = 46 tests passed

### Post-Implementation UX Improvements (2026-04-20)

The following changes were made after initial implementation, at the product owner's request, to improve the code verification screen UX. They intentionally deviate from the original story spec:

**1. Added `AppColors.warning` (`0xFFF59E0B`, Amber-500)**
- The spec says "Do NOT create new colors" — this applied to auth screen styling, not to extending the design system for a reusable component. The warning color fills a gap in the functional palette (the system had `destructive` for errors but no equivalent for non-critical warnings). Updated `theme_tokens_test.dart` count from 8 → 9 to match.

**2. Created `core/widgets/app_toast.dart` — reusable toast overlay system**
- Not in the original story scope, but built as a shared app-level widget (not auth-specific) for reuse across future stories (consent warnings, call errors, etc.). Uses `Overlay` + `SlideTransition`, auto-dismisses after 10s. Supports `warning`, `error`, `success` types.

**3. Replaced static spam-folder text with an animated toast notification**
- The spec says "Do NOT show toast notifications for auth errors." This toast is NOT an auth error — it is an informational UX hint about email delivery. Auth errors remain inline per spec (AC4). The static text was poorly visible and cluttered the centered content layout. The toast appears after a 600ms delay (after page transition), slides in from the right, and is capped at 75% screen width.

**4. `theme_tokens_test.dart` updated**
- The spec says this file "should pass unchanged." It was updated solely to reflect the new `warning` color token (count 8 → 9). No other assertions were changed.

### Change Log
- 2026-04-20: Post-implementation UX improvement — replaced static spam-folder text with reusable toast notification system (AppToast + AppColors.warning)
- 2026-04-16: Implemented Story 4.3 — full email authentication flow in Flutter (all 22 tasks complete, 46 tests passing)

### File List
New files:
- client/lib/core/api/api_client.dart
- client/lib/core/api/api_exception.dart
- client/lib/core/auth/token_storage.dart
- client/lib/features/auth/data/auth_repository.dart
- client/lib/features/auth/data/auth_result.dart
- client/lib/features/auth/bloc/auth_event.dart
- client/lib/features/auth/bloc/auth_state.dart
- client/lib/features/auth/bloc/auth_bloc.dart
- client/lib/features/auth/presentation/email_entry_screen.dart
- client/lib/features/auth/presentation/code_verification_screen.dart
- client/test/core/api/api_client_test.dart
- client/test/core/auth/token_storage_test.dart
- client/test/features/auth/bloc/auth_bloc_test.dart
- client/test/features/auth/presentation/email_entry_screen_test.dart
- client/test/features/auth/presentation/code_verification_screen_test.dart

New files (post-implementation UX):
- client/lib/core/widgets/app_toast.dart

Modified files:
- client/lib/app/router.dart
- client/lib/app/app.dart
- client/lib/core/theme/app_colors.dart
- client/lib/features/auth/presentation/code_verification_screen.dart
- client/test/app_test.dart
- client/test/core/theme/theme_tokens_test.dart

Tracking files:
- _bmad-output/implementation-artifacts/sprint-status.yaml
- _bmad-output/implementation-artifacts/4-3-build-email-authentication-flow-in-flutter.md
