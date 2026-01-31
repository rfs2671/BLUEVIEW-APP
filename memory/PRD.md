# Blueview2 - Expo React Native App

## Project Overview
Blueview is a construction site operations management application converted from Create React App to Expo React Native, maintaining the "cool tech futuristic" glassmorphism aesthetic (Base44 design system).

## Conversion Complete ✅

Successfully converted from:
- **React** (Create React App) → **React Native** (Expo)
- **React Router DOM** → **Expo Router** (file-based routing)
- **Tailwind CSS** → **React Native StyleSheet**
- **Framer Motion** → **React Native Animated**

## Tech Stack
- **Framework**: Expo SDK 54 with Expo Router v6
- **Platforms**: Android, Web
- **Styling**: React Native StyleSheet + expo-linear-gradient + expo-blur
- **Navigation**: Expo Router (file-based)
- **State**: React Context (AuthContext)
- **API**: Axios with JWT authentication

## File Structure
```
/app/frontend/
├── app/                      # Expo Router pages (file-based routing)
│   ├── _layout.jsx           # Root layout with providers
│   ├── index.jsx             # Dashboard (/)
│   ├── login.jsx             # Login page (/login)
│   ├── workers.jsx           # Workers page (/workers)
│   ├── daily-log.jsx         # Daily Log page (/daily-log)
│   ├── reports.jsx           # Reports page (/reports)
│   └── projects/
│       └── index.jsx         # Projects page (/projects)
├── src/
│   ├── components/           # Reusable UI components
│   │   ├── AnimatedBackground.js
│   │   ├── FloatingNav.js
│   │   ├── GlassButton.js
│   │   ├── GlassCard.js
│   │   ├── GlassInput.js
│   │   ├── GlassSkeleton.js
│   │   └── Toast.js
│   ├── context/
│   │   └── AuthContext.js    # Auth state management
│   ├── styles/
│   │   ├── globalStyles.js   # Global StyleSheet
│   │   └── theme.js          # Base44 theme colors & typography
│   └── utils/
│       └── api.js            # Axios API utility with JWT
├── app.json                  # Expo config
├── babel.config.js           # Babel config for Reanimated
└── package.json
```

## Design System (Base44 Aesthetic) ✅

### Colors
```javascript
background: '#050a12' → '#0A1929' → '#050a12'
glass.background: 'rgba(255, 255, 255, 0.08)'
glass.border: 'rgba(255, 255, 255, 0.15)'
text.primary: 'rgba(255, 255, 255, 0.9)'
text.secondary: 'rgba(255, 255, 255, 0.6)'
text.muted: 'rgba(255, 255, 255, 0.4)'
```

### Visual Effects
- Deep blue gradient background (LinearGradient)
- Floating orbs with pulsing opacity (Animated)
- Scanline animation (Animated)
- Glassmorphism cards (expo-blur + transparency)
- Skeleton shimmer loaders

### Typography
- Hero: 48px, weight 200, tracking -1
- Labels: 11px, uppercase, tracking 2px
- Stats: 36px, weight 200

## API Integration ✅

### Base URL
`https://blueview2-production.up.railway.app`

### Authentication
- JWT tokens stored in AsyncStorage
- Auto-attach to all requests via Axios interceptor
- 401 handling with redirect to login

### Verified Endpoints
- POST `/api/auth/login` - Login
- GET `/api/auth/me` - User profile
- GET/POST `/api/projects` - Projects CRUD
- GET `/api/workers` - Workers list
- GET `/api/checkins` - Check-ins
- GET/POST `/api/daily-logs` - Daily logs

## Running the App

### Development
```bash
cd /app/frontend
npm start           # Expo dev server
npm run web         # Web only
npm run android     # Android emulator/device
```

### Production Build
```bash
npx expo export --platform web    # Web build
npx expo build:android            # Android APK
```

### Serve Static Build
```bash
npx serve dist -l 3000 -s
```

## Pages Implemented

| Route | Page | Status |
|-------|------|--------|
| `/login` | Login | ✅ Working |
| `/` | Home Dashboard | ✅ Working |
| `/projects` | Projects List | ✅ Working |
| `/project/[id]` | Project Detail | ✅ NEW - Working |
| `/project/[id]/report-settings` | Report Settings | ✅ NEW - Working |
| `/checkin` | Manual Check-In | ✅ NEW - Working |
| `/nfc` | NFC Check-In | ✅ NEW - Working |
| `/workers` | Workers/Sign-In Log | ✅ Working |
| `/workers/[id]` | Worker Detail | ✅ NEW - Working |
| `/daily-log` | Daily Log | ✅ Working |
| `/reports` | Reports | ✅ Working |
| `/admin/integrations` | Dropbox Integration | ✅ Working |
| `/admin/users` | Admin User Management | ✅ NEW - Working (MOCK DATA) |
| `/admin/subcontractors` | Admin Subcontractors | ✅ NEW - Working (MOCK DATA) |
| `/owner` | Owner Portal | ✅ NEW - Working (MOCK DATA) |
| `/projects/[id]/dropbox-settings` | Project Dropbox Settings | ✅ Working |
| `/projects/[id]/construction-plans` | Construction Plans Viewer | ✅ Working |

## Implementation Status (January 31, 2026) ✅

### All 14+ Required Pages Implemented
The app now has all pages from the original PDF spec plus additional Dropbox integration pages.

## Dropbox Integration (January 31, 2026) ✅

### Features Implemented
1. **Admin Integrations Page** (`/admin/integrations`)
   - Dropbox connection status display
   - "Connect to Dropbox" OAuth button
   - "Disconnect" functionality
   - List of all projects with Dropbox status
   
2. **Project Dropbox Settings** (`/projects/[id]/dropbox-settings`)
   - Enable/disable Dropbox sync toggle
   - Folder browser for selecting Dropbox folder
   - Sync status and file count
   - Manual sync button
   
3. **Construction Plans Viewer** (`/projects/[id]/construction-plans`)
   - File listing from synced Dropbox folder
   - Search and filter functionality
   - File type icons (PDF, images, documents)
   - View and download buttons
   - Sync status bar

### Dropbox API Endpoints
- `GET /api/dropbox/status` - Check connection status
- `GET /api/dropbox/auth-url` - Get OAuth authorization URL
- `POST /api/dropbox/complete-auth` - Complete OAuth flow
- `DELETE /api/dropbox/disconnect` - Disconnect account
- `GET /api/dropbox/folders` - List Dropbox folders
- `POST /api/projects/{id}/link-dropbox` - Link folder to project
- `GET /api/projects/{id}/dropbox-files` - Get synced files
- `POST /api/projects/{id}/sync-dropbox` - Trigger sync
- `GET /api/projects/{id}/dropbox-file-url` - Get file preview/download URL

### Access Control
- **All users**: View and download files from Construction Plans page
- **Admins only**: 
  - Access Admin Integrations page (connect/disconnect Dropbox)
  - Configure project Dropbox settings (enable sync, select folders)
  - Non-admins see "Admin Access Required" message on restricted pages

## Test Credentials
- **Email**: rfs2671@gmail.com
- **Password**: Asdddfgh1$

## What Changed from CRA

| CRA | Expo |
|-----|------|
| `BrowserRouter` | `expo-router/Stack` |
| `useNavigate()` | `useRouter()` |
| `useLocation()` | `usePathname()` |
| `useParams()` | `useLocalSearchParams()` |
| Tailwind classes | StyleSheet objects |
| `framer-motion` | `Animated` API |
| `localStorage` | `AsyncStorage` |
| `fetch()` | `axios` |

## Dependencies Added
- expo-router
- expo-linear-gradient
- expo-blur
- expo-linking
- @react-native-async-storage/async-storage
- react-native-screens
- react-native-safe-area-context
- react-native-reanimated
- lucide-react-native
- axios

## Next Steps (Backlog)
- Dark/light theme toggle
- Android native build testing
- Photo upload integration
- Voice-to-text for daily logs
- Push notifications
- Offline support
- Backend: Add POST/PUT/DELETE endpoints for admin users management
- Backend: Add POST/PUT/DELETE endpoints for subcontractors management

---
*Last Updated: January 31, 2026*
