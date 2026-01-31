# Blueview2 - Expo React Native App

## Project Overview
Construction site management application with NFC-based worker check-in system, daily logs, project management, Dropbox integration, and admin controls.

## Tech Stack
- **Frontend**: Expo React Native (~54.0.32), React 19.1.0, Expo Router
- **Backend**: FastAPI, Python 3.11, MongoDB
- **Styling**: Base44 Glassmorphism theme (deep blue gradient, glass cards)
- **Authentication**: JWT tokens with bcrypt password hashing
- **Build**: EAS Build configured for Android APK generation

## Pages Implemented

| Route | Page | Status |
|-------|------|--------|
| `/login` | Login | ✅ Working |
| `/` | Home Dashboard | ✅ Working |
| `/projects` | Projects List | ✅ Working |
| `/project/[id]` | Project Detail | ✅ Working |
| `/project/[id]/report-settings` | Report Settings (NFC Tags) | ✅ Working |
| `/checkin` | Manual Check-In | ✅ Working |
| `/nfc?tag=TAG_ID` | NFC Check-In | ✅ Working |
| `/workers` | Workers/Sign-In Log | ✅ Working |
| `/workers/[id]` | Worker Detail | ✅ Working |
| `/daily-log` | Daily Log | ✅ Working |
| `/reports` | Reports | ✅ Working |
| `/admin/integrations` | Dropbox Integration | ✅ Working (OAuth flow complete) |
| `/admin/users` | Admin User Management | ✅ Full CRUD |
| `/admin/subcontractors` | Admin Subcontractors | ✅ Full CRUD |
| `/owner` | Owner Portal | ✅ Working |
| `/projects/[id]/dropbox-settings` | Project Dropbox Settings | ✅ Working |
| `/projects/[id]/construction-plans` | Construction Plans Viewer | ✅ Working |

## Backend API Endpoints

### Authentication
- `POST /api/auth/login` - Login with email/password
- `POST /api/auth/register` - Register new user
- `GET /api/auth/me` - Get current user info

### Admin User Management
- `GET /api/admin/users` - List all users
- `POST /api/admin/users` - Create user
- `PUT /api/admin/users/{id}` - Update user
- `DELETE /api/admin/users/{id}` - Delete user
- `POST /api/admin/users/{id}/assign-projects` - Assign projects

### Admin Subcontractors
- `GET /api/admin/subcontractors` - List all subcontractors
- `POST /api/admin/subcontractors` - Create subcontractor
- `PUT /api/admin/subcontractors/{id}` - Update subcontractor
- `DELETE /api/admin/subcontractors/{id}` - Delete subcontractor

### Projects
- `GET /api/projects` - List projects
- `POST /api/projects` - Create project
- `GET /api/projects/{id}` - Get project
- `PUT /api/projects/{id}` - Update project
- `DELETE /api/projects/{id}` - Delete project

### NFC Tags
- `GET /api/nfc-tags/{tag_id}/info` - Get tag info (PUBLIC)
- `GET /api/projects/{id}/nfc-tags` - Get project's NFC tags
- `POST /api/projects/{id}/nfc-tags` - Register NFC tag to project
- `DELETE /api/projects/{id}/nfc-tags/{tag_id}` - Remove NFC tag

### Workers
- `GET /api/workers` - List workers
- `POST /api/workers/register` - Self-register worker (PUBLIC)
- `GET /api/workers/{id}` - Get worker
- `PUT /api/workers/{id}` - Update worker
- `DELETE /api/workers/{id}` - Delete worker

### Check-Ins
- `POST /api/checkin` - Worker check-in (PUBLIC)
- `POST /api/checkins/{id}/checkout` - Worker check-out
- `GET /api/checkins/project/{id}/active` - Active check-ins
- `GET /api/checkins/project/{id}/today` - Today's check-ins

### Dropbox Integration
- `GET /api/dropbox/status` - Get connection status
- `GET /api/dropbox/auth-url` - Get OAuth authorization URL
- `GET /api/dropbox/callback` - OAuth callback handler (returns HTML)
- `POST /api/dropbox/complete-auth` - Exchange code for tokens
- `POST /api/dropbox/disconnect` - Disconnect Dropbox
- `POST /api/projects/{id}/link-dropbox` - Link folder to project
- `GET /api/projects/{id}/dropbox-files` - Get project files

### Dashboard
- `GET /api/stats/dashboard` - Dashboard statistics

## NFC Check-In Flow
1. Worker scans NFC tag → Opens URL `/nfc?tag=TAG_ID`
2. App fetches tag info from `/api/nfc-tags/{tag_id}/info`
3. If new worker: Shows registration form
4. Worker registers → Profile saved to AsyncStorage
5. Auto check-in via `/api/checkin`
6. Success screen with timestamp

## Dropbox OAuth Flow
1. Admin clicks "Connect to Dropbox" → Opens OAuth URL in browser
2. User authorizes in Dropbox → Redirected to callback with code
3. User copies authorization code from callback page
4. User pastes code in app → App exchanges code for tokens
5. Tokens stored in database → Status shows "Connected"

## Android Build Instructions
The project is configured for Android builds using EAS:

```bash
# Install dependencies
cd frontend && yarn install

# Generate Android native code
npx expo prebuild --platform android

# Build APK using EAS (cloud build)
npx eas build --platform android --profile preview

# Or for local build (requires Android Studio & JDK)
cd android && ./gradlew assembleDebug
```

## Test Credentials
- **Admin**: rfs2671@gmail.com / Asdddfgh1$
- **Owner Portal Password**: blueview2024
- **Sample NFC Tag**: BLUEVIEW-TAG-001

## Testing Status (as of January 31, 2026)
- **Backend**: 100% (26/26 tests passed)
- **Frontend**: 95% (all flows working)
- Test reports: `/app/test_reports/iteration_8.json`

---
*Last Updated: January 31, 2026*
