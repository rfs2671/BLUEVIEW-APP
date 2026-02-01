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

## Daily Log Sign-Off Sections
Daily logs in site mode include two signature sections:
1. **Superintendent Sign-Off** - For project superintendent approval
2. **Competent Person Sign-Off** - For safety/compliance approval

Both currently show "Pending signature" with "Coming soon" placeholder.

## Test Credentials
- **Admin**: rfs2671@gmail.com / Asdddfgh1$
- **Site Device**: site-downtown-1 / sitepass123 (Downtown Tower project)
- **Owner Portal Password**: blueview2024

## Testing Status (as of February 1, 2026)
- **Backend**: All endpoints working
- **Frontend**: All pages working
- **Site Mode**: Fully functional
- Test reports: `/app/test_reports/iteration_8.json`

---
*Last Updated: February 1, 2026*
