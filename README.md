# Blueview - Construction Site Management App

A comprehensive construction site management application with NFC-based worker check-in, project management, Dropbox integration, and admin controls.

## Tech Stack

- **Frontend**: Expo React Native (Web + Android)
- **Backend**: FastAPI + MongoDB
- **Authentication**: JWT-based auth
- **Design**: Base44 Glassmorphism theme

## Features

- 🏗️ **Project Management** - Create and manage construction projects
- 👷 **Worker Check-In** - NFC tag and manual check-in options
- 📊 **Dashboard** - Real-time statistics and activity tracking
- 📁 **Dropbox Integration** - Sync construction plans and documents
- 👥 **Admin Panel** - User and subcontractor management
- 📱 **Mobile Ready** - Android APK build support via EAS

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11+
- MongoDB
- Yarn

### Backend Setup

```bash
cd backend
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your MongoDB URL and secrets

# Run server
uvicorn server:app --host 0.0.0.0 --port 8001
```

### Frontend Setup

```bash
cd frontend
yarn install

# Configure environment
cp .env.example .env
# Edit .env with your backend URL

# Run for web
npx expo start --web

# Build for web
npx expo export --platform web
```

### Android Build

```bash
cd frontend

# Generate native Android project
npx expo prebuild --platform android

# Build APK via EAS (cloud)
npx eas build --platform android --profile preview

# Or local build (requires Android Studio + JDK)
cd android && ./gradlew assembleDebug
```

## Project Structure

```
├── backend/
│   ├── server.py          # FastAPI application
│   ├── requirements.txt   # Python dependencies
│   └── .env              # Environment config
│
├── frontend/
│   ├── app/              # Expo Router pages
│   ├── src/
│   │   ├── components/   # Reusable UI components
│   │   ├── context/      # React contexts
│   │   ├── styles/       # Theme and styling
│   │   └── utils/        # API client and helpers
│   ├── assets/           # Images and fonts
│   ├── app.json          # Expo config
│   ├── eas.json          # EAS Build config
│   └── package.json      # Node dependencies
│
└── memory/
    └── PRD.md            # Product requirements
```

## Environment Variables

### Backend (.env)
```
MONGO_URL=mongodb://...
DB_NAME=blueview
JWT_SECRET=your-secret-key
DROPBOX_APP_KEY=your-dropbox-app-key
DROPBOX_APP_SECRET=your-dropbox-app-secret
```

### Frontend (.env)
```
REACT_APP_BACKEND_URL=https://your-backend-url
```

## License

MIT
