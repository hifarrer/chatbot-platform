# 🎯 Quick Setup Guide: Avatar Persistence on Render

## The Problem (Solved!)
Your chatbot avatars were disappearing after each deployment because they were being saved to Render's ephemeral filesystem, which gets wiped on every deployment.

## The Solution
I've updated your code to use Render's persistent disk storage. Now avatars will persist forever! 

## ✅ What I Fixed

### Code Changes Made:
1. **Created helper function** - `get_avatar_upload_dir()` that automatically uses:
   - `/uploads/avatars/` on Render (persistent disk)
   - `static/uploads/` locally (for development)

2. **Updated all avatar upload/delete logic** in these routes:
   - `create_chatbot()` - Creating new chatbots with avatars
   - `update_chatbot()` - Updating chatbot avatars
   - `delete_chatbot()` - Cleaning up avatar files
   - `admin_delete_chatbot()` - Admin cleanup
   - `uploaded_file()` - Serving avatar files

3. **Fixed template embed codes** to use correct avatar URLs:
   - `templates/chatbot_details.html`
   - `templates/admin/chatbot_details.html`

## 🚀 What You Need to Do on Render

### Step 1: Add a Persistent Disk
1. Go to your Render dashboard: https://dashboard.render.com
2. Click on your `chatbot-platform` service
3. Go to the **"Disks"** section in the left sidebar
4. Click **"Add Disk"**
5. Configure the disk:
   ```
   Mount Path: /uploads
   Name: uploads-disk (or any name you prefer)
   Size: 1GB or more (1GB should be plenty)
   ```
6. Click **"Create Disk"**

### Step 2: Set Environment Variable
1. Still in your Render service settings
2. Go to **"Environment"** section in the left sidebar
3. Add this environment variable:
   ```
   Key: RENDER_DISK_PATH
   Value: /uploads
   ```
4. Click **"Save Changes"**

### Step 3: Deploy the Changes
1. Commit and push your code changes to GitHub:
   ```bash
   git add .
   git commit -m "Fix avatar persistence for Render deployment"
   git push origin master
   ```
2. Render will automatically detect the changes and redeploy
3. Wait for the deployment to complete (watch the logs)

### Step 4: Test It!
1. Go to your deployed app
2. Create or edit a chatbot
3. Upload a custom avatar
4. Manually trigger a redeploy on Render (or just wait for next deployment)
5. Check if the avatar is still there ✅

## 📁 How It Works Now

### File Storage Structure on Render:
```
/uploads/                          # Persistent disk (survives deployments)
├── avatars/                       # Custom chatbot avatars
│   ├── avatar_mybot_20241014_120000.png
│   └── avatar_sales_20241014_130000.jpg
└── *.pdf, *.txt, *.docx          # Uploaded documents
```

### File Storage Structure Locally:
```
static/
├── avatars/                       # Predefined avatars (1.png - 6.png)
└── uploads/                       # Custom avatars & documents
    └── avatar_*.png
```

## 🔍 How the Code Works

### When uploading an avatar:
```python
# Code automatically detects environment
upload_dir = get_avatar_upload_dir()
# On Render: returns "/uploads/avatars/"
# Locally: returns "static/uploads/"
```

### When serving an avatar:
- Predefined avatars (1-6.png): Served from `static/avatars/` (part of your code)
- Custom avatars: Served via `/uploads/<filename>` route from persistent disk

### When deleting a chatbot:
- Custom avatars are deleted from persistent storage
- Predefined avatars (1-6.png) are never deleted

## ✨ Benefits

✅ **No more disappearing avatars!**  
✅ **Works automatically** - detects Render vs local environment  
✅ **Backward compatible** - works in development without changes  
✅ **Clean storage** - deletes old avatars when chatbots are deleted  
✅ **Efficient** - predefined avatars stay in the codebase, only custom uploads use disk space

## 🔧 Troubleshooting

### If avatars still disappear:
1. Check Render dashboard → "Disks" → verify disk is created and mounted at `/uploads`
2. Check Render dashboard → "Environment" → verify `RENDER_DISK_PATH=/uploads` is set
3. Check Render logs for this message: `Using Render disk: /uploads`
4. If you see: `WARNING: Render disk not found at /uploads`, the disk isn't mounted correctly

### To verify the disk is working:
Check your Render logs after deployment. You should see:
```
Using Render disk: /uploads
✅ App created successfully for gunicorn
```

## 📝 Notes

- **Predefined avatars** (1.png through 6.png) don't use the persistent disk - they're part of your codebase in `static/avatars/`
- **Custom uploaded avatars** use the persistent disk at `/uploads/avatars/`
- **Document uploads** already use the persistent disk at `/uploads/`
- The disk path `/uploads` can be changed by setting the `RENDER_DISK_PATH` environment variable

## 🎉 You're All Set!

Once you complete the 3 steps above, your avatars will persist across all deployments. No more disappearing avatars! 

If you have any issues, check the troubleshooting section or the Render logs for error messages.

