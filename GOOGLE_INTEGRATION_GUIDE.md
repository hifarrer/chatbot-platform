# Google Integration Guide
## Train Your Chatbot with Google Docs & Google Sheets

## Overview
Your chatbot platform now supports direct training from Google Workspace:
- ✅ **Google Docs** - For documents, articles, policies, guides
- ✅ **Google Sheets** - For structured data like pricing, products, FAQs

No more downloading and re-uploading! Just paste the link and train.

---

## 🔵 Google Docs Integration

### When to Use Google Docs
- Documentation and guides
- Policies and procedures
- Articles and blog posts
- Training manuals
- FAQ content (unstructured)
- General text-based information

### How to Use
1. Go to your chatbot's details page
2. Click the **"Google Docs"** tab
3. Share your Google Doc: "Anyone with the link can view"
4. Paste the URL
5. Click **"Import from Google Docs"**

### Supported URLs
```
https://docs.google.com/document/d/YOUR_DOC_ID/edit
https://docs.google.com/document/d/YOUR_DOC_ID/
https://docs.google.com/document/u/0/d/YOUR_DOC_ID/edit
```

### What Happens
- Document fetched as plain text
- Saved to your training documents
- Ready for chatbot training

---

## 📊 Google Sheets Integration

### When to Use Google Sheets
Perfect for structured, tabular data:
- **Pricing plans** (plan names, prices, features)
- **Product catalogs** (products, descriptions, prices, SKUs)
- **FAQ databases** (questions, answers, categories)
- **Inventory lists** (items, quantities, locations)
- **Contact information** (names, roles, emails, phones)
- **Service offerings** (services, descriptions, pricing)
- **Feature comparisons** (products, features, availability)

### How to Use
1. Go to your chatbot's details page
2. Click the **"Google Sheets"** tab
3. Share your Google Sheet: "Anyone with the link can view"
4. Paste the URL
5. Click **"Import from Google Sheets"**

### Supported URLs
```
https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/
https://docs.google.com/spreadsheets/u/0/d/YOUR_SHEET_ID/edit#gid=0
```

### What Happens (The Magic!)
1. Sheet fetched as CSV
2. **Automatically converted to JSON format**
3. Formatted with both:
   - Structured JSON (for AI to parse)
   - Human-readable text (for natural responses)
4. Saved to your training documents
5. Ready for optimal AI training

### Example: Pricing Plans Sheet

**Your Google Sheet:**
| Plan Name    | Price      | Features           | Max Chatbots |
|--------------|------------|--------------------|--------------|
| Free Plan    | $0         | Basic features     | 1            |
| Starter Plan | $29/month  | Advanced features  | 5            |
| Pro Plan     | $99/month  | All features       | Unlimited    |

**Becomes this training data:**
```
=== Google Sheet: Main Sheet ===
Total Rows: 3
Columns: Plan Name, Price, Features, Max Chatbots

=== Structured Data (JSON Format) ===
{
  "sheet_name": "Main Sheet",
  "columns": ["Plan Name", "Price", "Features", "Max Chatbots"],
  "row_count": 3,
  "data": [
    {
      "Plan Name": "Free Plan",
      "Price": "$0",
      "Features": "Basic features",
      "Max Chatbots": "1"
    },
    {
      "Plan Name": "Starter Plan",
      "Price": "$29/month",
      "Features": "Advanced features",
      "Max Chatbots": "5"
    },
    {
      "Plan Name": "Pro Plan",
      "Price": "$99/month",
      "Features": "All features",
      "Max Chatbots": "Unlimited"
    }
  ]
}

=== Human-Readable Format ===

Entry 1:
  Plan Name: Free Plan
  Price: $0
  Features: Basic features
  Max Chatbots: 1

Entry 2:
  Plan Name: Starter Plan
  Price: $29/month
  Features: Advanced features
  Max Chatbots: 5

Entry 3:
  Plan Name: Pro Plan
  Price: $99/month
  Features: All features
  Max Chatbots: Unlimited
```

**Result:** Your chatbot can now answer:
- "What are your pricing plans?"
- "How much does the Pro plan cost?"
- "What's included in the Starter plan?"
- "Can I create multiple chatbots on the Free plan?"

---

## 🔐 Sharing Permissions (Important!)

Both Google Docs and Google Sheets must be publicly accessible:

### How to Share:
1. Open your Google Doc or Sheet
2. Click the **"Share"** button (top-right)
3. Under "General access", change from **"Restricted"** to **"Anyone with the link"**
4. Set permission to **"Viewer"**
5. Click **"Done"**

### Why Public Sharing?
The platform fetches documents on behalf of your chatbot without user authentication. Public sharing allows the system to access your content securely via the URL.

### Security Note:
- Only people with the exact link can access
- Link is not indexed by search engines
- You can revoke access anytime by changing back to "Restricted"

---

## 📋 Complete Training Workflow

### Step 1: Prepare Your Data
- **Google Docs**: Write your content
- **Google Sheets**: Organize in tables with clear headers

### Step 2: Share Your Content
- Set "Anyone with the link can view"

### Step 3: Import to Chatbot
1. Navigate to chatbot details page
2. Choose the appropriate tab:
   - 📄 Upload File (for local files)
   - 📝 Google Docs (for documents)
   - 📊 Google Sheets (for tables)
3. Paste URL and import

### Step 4: Train Your Chatbot
- Click **"Train Chatbot"** button
- Wait for training to complete
- Test with sample questions

### Step 5: Update as Needed
- Update your Google Doc or Sheet
- Re-import to refresh training data
- Retrain chatbot with updated content

---

## 💡 Best Practices

### For Google Docs:
- Use clear headings and structure
- Break content into logical sections
- Include common questions and answers
- Use consistent formatting
- Avoid tables (use Google Sheets instead)

### For Google Sheets:
- **First row = column headers** (required)
- Use descriptive header names
- Keep data clean (no merged cells)
- One type of data per sheet
- Remove empty rows
- Use consistent formatting

### Combination Strategy:
- **Google Docs**: Brand story, policies, how-to guides
- **Google Sheets**: Pricing, products, structured FAQs
- **Local Files**: PDFs, large documents, legacy content

---

## ❓ Troubleshooting

### "Access Denied" Error
**Solution**: Ensure document is shared with "Anyone with the link can view"

### "Document Not Found" Error
**Solution**: Check the URL is correct and document still exists

### "Empty Content" Warning
**Solution**: 
- Google Docs: Add text content to document
- Google Sheets: Ensure at least one row of data (besides headers)

### Chatbot Not Understanding Sheets Data
**Solution**: 
- Use clear column headers
- Ensure data is in first sheet (gid=0)
- Check for empty columns or formatting issues

### Sheet Shows Old Data After Update
**Solution**: Re-import the sheet to fetch latest version

---

## 🎯 Use Case Examples

### E-commerce Store
- **Google Docs**: Return policy, shipping info, about us
- **Google Sheets**: Product catalog, inventory status

### SaaS Platform
- **Google Docs**: User guides, API documentation, tutorials
- **Google Sheets**: Pricing plans, feature comparison, integration list

### Real Estate Agency
- **Google Docs**: Buying process, agent bios, neighborhood guides
- **Google Sheets**: Property listings, open houses, price ranges

### Educational Institution
- **Google Docs**: Course descriptions, admission process, campus life
- **Google Sheets**: Course schedule, tuition fees, program requirements

### Restaurant
- **Google Docs**: Restaurant story, catering info, private events
- **Google Sheets**: Menu items, prices, dietary information, hours

---

## 📊 Comparison: When to Use What

| Data Type | Best Format | Why |
|-----------|-------------|-----|
| Articles & Guides | Google Docs | Natural text flow |
| Pricing Plans | Google Sheets | Structured comparison |
| FAQ (Unstructured) | Google Docs | Conversational format |
| FAQ (Database) | Google Sheets | Easy to update and expand |
| Product Catalog | Google Sheets | Consistent structure |
| Policies | Google Docs | Legal/formal text |
| Inventory | Google Sheets | Real-time updates |
| Blog Posts | Google Docs | Rich formatting |
| Contact Info | Google Sheets | Organized data |
| Training Manuals | Google Docs | Step-by-step text |

---

## 🚀 Advanced Tips

### Keep Data Current
Set a reminder to update and re-import Google Sheets monthly or quarterly

### Version Control
Use Google's version history to track changes and revert if needed

### Team Collaboration
Multiple team members can update the same sheet; chatbot gets latest version

### Data Validation
Use Google Sheets data validation to ensure consistent formatting

### Multiple Sources
Combine Google Docs for context and Google Sheets for data in same chatbot

### Testing
After importing, test with specific questions to verify understanding

---

## 🔮 Coming Soon (Future Enhancements)

- 📊 Multi-sheet support (import multiple sheets from one workbook)
- 🔄 Auto-sync (scheduled refresh of Google content)
- 🔐 OAuth integration (access private documents)
- 🎨 Rich formatting preservation
- 📂 Google Drive folder import (batch processing)

---

## 📚 Technical Documentation

For detailed technical information:
- See `GOOGLE_DOCS_FEATURE.md` for Google Docs implementation details
- See `GOOGLE_SHEETS_FEATURE.md` for Google Sheets technical specs

---

## ✅ Summary

You can now train your chatbot directly from Google Workspace:
- **Google Docs** → Text content, documents, guides
- **Google Sheets** → Structured data, automatically converted to JSON
- **No downloads needed** → Paste URL and train
- **Easy updates** → Re-import when content changes
- **Team collaboration** → Multiple people can maintain training data

Both features are ready to use right now. Just ensure your documents are shared with "Anyone with the link can view" and start training! 🎉

