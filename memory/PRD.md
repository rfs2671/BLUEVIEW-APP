# Blueview2 - Expo React Native App

## Project Overview
Construction site management application with NFC-based worker check-in system, daily logs, project management, Dropbox integration, and admin controls.

## Tech Stack
- **Frontend**: Expo React Native (~54.0.32), React 19.1.0, Expo Router
- **Backend**: FastAPI, Python 3.11, MongoDB
- **Styling**: Base44 Glassmorphism theme (deep blue gradient, glass cards)
- **Authentication**: JWT tokens with bcrypt password hashing
- **Build**: EAS Build configured for Android APK generation

## Features

### Core Features
- 🏗️ **Project Management** - Create and manage construction projects
- 👷 **Worker Check-In** - NFC tag and manual check-in options
- 📊 **Dashboard** - Real-time statistics and activity tracking
- 📁 **Dropbox Integration** - Sync construction plans and documents
- 👥 **Admin Panel** - User and subcontractor management
- 📱 **Mobile Ready** - Android APK build support via EAS

### Site Device Login System (NEW)
- **Project-Specific Credentials**: Admin creates credentials linked to specific projects
- **Site Mode**: Restricted view showing only 3 screens:
  - Check-Ins (project workers only)
  - Daily Log Books (project logs only)
  - Documents (project Dropbox files only)
- **No Admin Access**: Site devices cannot access admin features or other projects
- **Signature Sections**: Daily logs include Superintendent and Competent Person sign-off areas

## Pages Implemented

### Regular User Pages
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
| `/documents` | Documents | ✅ Working |
| `/reports` | Reports | ✅ Working |
| `/admin/integrations` | Dropbox Integration | ✅ Working |
| `/admin/users` | Admin User Management | ✅ Full CRUD |
| `/admin/subcontractors` | Admin Subcontractors | ✅ Full CRUD |
| `/admin/site-devices` | Site Device Management | ✅ NEW |
| `/owner` | Owner Portal | ✅ Working |

### Site Mode Pages (NEW)
| Route | Page | Status |
|-------|------|--------|
| `/site/checkins` | Site Check-Ins | ✅ Working |
| `/site/daily-logs` | Site Daily Log Books | ✅ Working |
| `/site/documents` | Site Documents | ✅ Working |

## Backend API Endpoints

### Site Device Management (NEW)
- `GET /api/admin/site-devices` - List all site devices
- `POST /api/admin/site-devices` - Create site device
- `GET /api/admin/site-devices/{id}` - Get site device
- `PUT /api/admin/site-devices/{id}` - Update site device (enable/disable)
- `DELETE /api/admin/site-devices/{id}` - Delete site device
- `GET /api/projects/{id}/site-devices` - Get devices for project

### Authentication
- `POST /api/auth/login` - Login (supports both email and site device username)
- `POST /api/auth/register` - Register new user
- `GET /api/auth/me` - Get current user info (includes site_mode flag)

### Other Endpoints
(See previous documentation for full list)

## Site Device Login Flow
1. Admin creates site device in Admin → Site Devices
2. Admin assigns project and creates username/password
3. On-site tablet/phone logs in with username/password
4. App detects site_mode from JWT token
5. User redirected to `/site/checkins` with restricted navigation
6. Only project-specific data accessible

## Daily Log Features (Fully Implemented - Feb 1, 2026)
The Daily Log page includes comprehensive sections:

### Today's Log Tab
1. **Project Selector** - Choose project (admin mode) or fixed (site mode)
2. **Weather Conditions** - Sunny, Cloudy, Rainy, Windy options
3. **Worker Count** - Number input for workers on site
4. **Daily Notes** - Free-form text area for progress updates
5. **Safety Inspection Checklist** - 5 items with Check/Unchecked/N/A options:
   - Fall Protection
   - Scaffolding
   - PPE (Personal Protective Equipment)
   - Hazard Identification
   - Base Conditions
6. **Corrective Actions** - Text area with N/A checkbox
7. **Incident Log** - Text area with N/A checkbox
8. **Superintendent Sign-Off** - SignaturePad component for signature capture
9. **Competent Person Sign-Off** - SignaturePad component for signature capture

### Previous Days Tab
- Shows historical logs with date, weather, worker count
- Click to view full log details in modal
- Displays signature status for each log

### SignaturePad Component Features
- Name input field with Edit button
- Touch/mouse signature drawing area
- Clear and Confirm buttons
- Verified badge after signature confirmation
- Timestamp tracking

## Test Credentials
- **Admin**: rfs2671@gmail.com / Asdddfgh1$
- **Site Device**: site-downtown-1 / password (Downtown Tower project)
- **Owner Portal Password**: blueview2024

## Testing Status (as of February 1, 2026)
- **Backend**: 100% (21/21 tests passed)
- **Frontend**: 100% (all tested features working)
- **Site Mode**: Fully functional
- Test reports: `/app/test_reports/iteration_9.json`
- Pytest results: `/app/test_reports/pytest/pytest_results.xml`

## Android Build
EAS build is configured. To build Android APK:
```bash
cd /app/frontend
npx eas build --platform android --profile preview
```

## Dropbox Integration
- Backend OAuth flow fully implemented
- Requires manual Dropbox authorization through web browser
- API endpoints: `/api/dropbox/status`, `/api/dropbox/auth-url`, `/api/dropbox/complete-auth`

---
*Last Updated: February 1, 2026*
