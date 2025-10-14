# Avatar Persistence Fix for Render Deployment

## Problem
Custom chatbot avatars were disappearing after every deployment on Render because they were being saved to the ephemeral filesystem (`static/uploads/`), which gets wiped on each deployment or container restart.

## Solution
Updated the application to use Render's persistent disk storage mounted at `/uploads` for storing custom avatar files.

## Changes Made

### 1. Added Helper Function (app.py)
Created `get_avatar_upload_dir()` function that:
- Checks for `RENDER_DISK_PATH` environment variable
- Uses `/uploads/avatars/` on Render (persistent storage)
- Falls back to `static/uploads/` for local development
- Automatically creates the directory if it doesn't exist

```python
def get_avatar_upload_dir():
    """Returns the directory where avatars should be stored"""
    # Use Render disk path if available (persistent storage)
    render_disk_path = os.environ.get('RENDER_DISK_PATH', '/uploads')
    if os.path.exists(render_disk_path) and render_disk_path != 'uploads':
        avatar_dir = os.path.join(render_disk_path, 'avatars')
    else:
        # Local development: use static/uploads
        avatar_dir = os.path.join(app.root_path, 'static', 'uploads')
    
    os.makedirs(avatar_dir, exist_ok=True)
    return avatar_dir
```

### 2. Updated Avatar Upload Routes
Modified the following routes to use `get_avatar_upload_dir()`:
- `create_chatbot()` - When creating a new chatbot with custom avatar
- `update_chatbot()` - When updating a chatbot's avatar
- Both delete routes now also clean up custom avatars properly

### 3. Updated Avatar URL Generation
Modified `get_avatar_url()` to:
- Return predefined avatars from `static/avatars/` (unchanged)
- Return custom avatars via the `/uploads/<filename>` route

### 4. Updated Avatar Serving Route
Modified `/uploads/<filename>` route to serve files from the persistent storage directory:
```python
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Serve uploaded avatar images from persistent storage"""
    upload_dir = get_avatar_upload_dir()
    return send_from_directory(upload_dir, filename)
```

### 5. Added Avatar Cleanup on Deletion
Updated both `delete_chatbot()` and `admin_delete_chatbot()` to:
- Check if the chatbot has a custom avatar
- Skip predefined avatars (1.png - 6.png)
- Delete custom avatar files from persistent storage

## Render Setup Required

### Environment Variable
Set in Render dashboard:
```
RENDER_DISK_PATH=/uploads
```

### Persistent Disk Configuration
1. Go to your Render service settings
2. Click "Disks" in the left sidebar
3. Click "Add Disk"
4. Set mount path: `/uploads`
5. Choose disk size: 1GB or more recommended
6. Save changes

## File Structure

### On Render (Production)
```
/uploads/
  ├── avatars/           # Custom chatbot avatars (persistent)
  │   └── avatar_*.png
  └── *.pdf, *.txt, etc  # Uploaded documents (persistent)
```

### Local Development
```
static/
  ├── avatars/           # Predefined avatars (1.png - 6.png)
  └── uploads/           # Custom avatars & documents
      └── avatar_*.png
```

## Benefits
✅ Avatars persist across deployments  
✅ No data loss on container restarts  
✅ Works seamlessly in local development  
✅ Automatic fallback for environments without persistent disk  
✅ Proper cleanup when chatbots are deleted

## Testing Checklist
- [ ] Upload a custom avatar for a chatbot
- [ ] Deploy to Render
- [ ] Verify avatar is still visible after deployment
- [ ] Update the avatar to a different image
- [ ] Delete the chatbot and verify avatar file is removed
- [ ] Test with predefined avatars (should work as before)

## Notes
- Predefined avatars (1.png - 6.png) remain in `static/avatars/` and are part of the codebase
- Only custom uploaded avatars are stored in the persistent disk
- The system automatically detects the environment and uses the appropriate storage location
- Document uploads were already using persistent storage; this fix extends it to avatars

