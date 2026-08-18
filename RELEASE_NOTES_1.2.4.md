# Release Notes - Version 1.2.4 (Local-Only Deployment)

## Overview

This release simplifies the TikTok OBS deployment by removing all token authentication requirements for local-only use cases. The application now runs without any authentication, making it easier to set up and use.

## Key Changes

### Authentication Removed
- **TIKTOBS_API_TOKEN** is no longer supported or required
- All API endpoints accessible without token
- WebSocket connections work without authentication
- Overlay URLs do not require ?token parameter

### Configuration Simplified
- `.env.example` updated to reflect local-only settings
- No more API token configuration needed
- Only essential variables remain:
  - TIKTOK_SIGN_API_KEY (optional, for cloud provider)
  - TIKTOBS_TEST_ENDPOINTS (enable/disable test mode)
  - TIKTOBS_RETENTION_DAYS (database cleanup policy)
  - TIKTOBS_HOST/TIKTOBS_PORT (server binding)

### UI Updates
- Removed "API Access Token" section from Settings page
- Enhanced error messages in Poll Admin
- Simplified configuration interface

### Code Improvements
- app/auth.py: Mock middleware that accepts all requests
- app/state.py: Removed API_TOKEN variable
- static/auth.js: No-op implementation
- static/settings.html: Removed token management UI/JS
- app/config.py: Auto-create .env from template on first run
- app/database.py: Centralized path configuration

## Migration Guide

### For Existing Users

If you're upgrading from an older version:

1. **Pull the latest code**:
   ```bash
   git pull origin main
   ```

2. **Delete old .env file** if it contains TIKTOBS_API_TOKEN

3. **Create new .env** if you want custom settings:
   ```bash
   cp .env.example .env
   # Edit as needed
   ```

4. **Rebuild executable**:
   ```cmd
   py build_exe.py
   ```

5. **Deploy new EXE** to clients

6. **Remove `?token=` parameters** from existing OBS overlay URLs

### For New Deployments

No special setup needed. Just:

1. Build the EXE
2. Deploy to client machine
3. Run and use immediately

---

## Breaking Changes

- Token authentication system completely removed
- Any code referencing TIKTOBS_API_TOKEN will be ignored
- localStorage tiktobs_token no longer used

---

## Security Considerations

**Appropriate for:**
- Single-user desktop installations
- Local network only (no public internet exposure)
- Development and testing environments
- Isolated LAN with trusted users

**NOT appropriate for:**
- Multi-user shared deployments
- Public internet exposure
- Production environments requiring access control
- Organizations needing audit trails

For multi-user scenarios, keep authentication enabled or implement external auth layer.

---

## Build Instructions

Prerequisites:
- Python 3.x installed
- PyInstaller installed
- All dependencies from requirements.txt

Build command:
```cmd
cd C:\path\to\tiktobs
py build_exe.py
```

Or manual:
```cmd
python -m PyInstaller ^
    --name=TikTokOBS ^
    --onefile ^
    --noconfirm ^
    --clean ^
    --add-data="static;static" ^
    --collect-all=TikTokLive ^
    run_app.py
```

Output location: `dist/TikTokOBS.exe`

---

## Testing Checklist

Before deploying to production:

- [ ] Application starts without errors
- [ ] Dashboard accessible at http://127.0.0.1:8000
- [ ] Poll Admin works without authentication
- [ ] Voting system functions correctly
- [ ] No token prompts anywhere in UI
- [ ] Overlay URLs work without ?token parameter
- [ ] WebSocket connection established
- [ ] Database operations successful
- [ ] API endpoints respond correctly
- [ ] Console shows no auth-related warnings

---

## Documentation Files

New documentation created:

1. **LOCAL_ONLY_CONFIGURATION.md** - Complete guide for local-only deployment
2. **PERBAIKAN_WINDWOS_EXE.md** - Technical implementation details of previous fixes
3. **TROUBLESHOOTING_WINDOWS_EXE.md** - Comprehensive troubleshooting procedures
4. **QUICK_FIX.md** - Quick reference commands and validation checklist
5. **RELEASE_NOTES_1.2.4.md** - This file

All documentation files included in repository.

---

## Known Issues

None currently known for local-only deployment.

---

## Support

For issues with this release:

1. Check console output when starting application
2. Verify no port conflicts on localhost:8000
3. Review browser console (F12 → Console tab)
4. Check Windows Event Viewer for crashes
5. Refer to troubleshooting documentation

---

## Credits

Changes implemented based on production feedback regarding token authentication complexity for local-only deployments.

---

## Changelog

### Version 1.2.4 (Current)
- ❌ Removed token authentication entirely
- ✅ Added auto-create .env functionality
- ✅ Centralized path configuration
- ✅ Enhanced error handling in frontend
- ✅ Simplified UI (removed token sections)
- ✅ Added comprehensive documentation

### Version 1.2.3
- ✓ Fixed database path resolution
- ✓ Improved poll error messages
- ✓ Added test coverage

See separate changelog for earlier versions.

---

*End of Release Notes - Version 1.2.4*
