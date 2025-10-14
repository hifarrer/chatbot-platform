# Excel Spreadsheet Training Feature

## Overview

The chatbot platform now supports training with **Excel (.xlsx) files**, enabling you to train your chatbot with structured data from spreadsheets. This is perfect for:

- Product catalogs
- Pricing tables
- Plan comparison tables
- Feature matrices
- Inventory data
- FAQ databases
- Any tabular data

## How It Works

Excel files are processed similarly to Google Sheets:

1. **Data Extraction**: The system reads all sheets in the Excel workbook
2. **Structured Conversion**: Each sheet is converted to structured JSON format
3. **Dual Format**: Data is formatted in both:
   - **JSON format** - for structured understanding by AI
   - **Human-readable format** - for natural language processing
4. **AI Training**: The formatted data is sent to OpenAI to generate a knowledge base

## Supported Features

### ✅ Multiple Sheets
- Processes all sheets in a workbook
- Each sheet is converted separately and combined

### ✅ Header Detection
- Automatically uses the first row as column headers
- Skips empty columns

### ✅ Data Cleaning
- Removes empty rows
- Trims whitespace
- Handles various data types (text, numbers, dates)

### ✅ Structured Output
The Excel data is converted to a format like:

```
=== Google Sheet: Products ===
Total Rows: 5
Columns: Product Name, Price, Description, Category

=== Structured Data (JSON Format) ===
{
  "sheet_name": "Products",
  "columns": ["Product Name", "Price", "Description", "Category"],
  "row_count": 5,
  "data": [
    {
      "Product Name": "Basic Plan",
      "Price": "$9.99",
      "Description": "Perfect for individuals",
      "Category": "Subscription"
    },
    ...
  ]
}

=== Human-Readable Format ===

Entry 1:
  Product Name: Basic Plan
  Price: $9.99
  Description: Perfect for individuals
  Category: Subscription

...
```

## Use Cases

### 1. Product Catalog Training
Upload an Excel file with columns like:
- Product Name
- Price
- Description
- Features
- SKU

The chatbot can then answer questions like:
- "What products do you offer?"
- "How much does [product name] cost?"
- "What are the features of [product name]?"

### 2. Pricing Plans
Upload a comparison table with:
- Plan Name
- Monthly Price
- Annual Price
- Features
- User Limits

The chatbot can answer:
- "What plans are available?"
- "What's included in the Pro plan?"
- "What's the difference between Basic and Pro?"

### 3. Feature Comparison
Upload a matrix showing:
- Feature names in rows
- Plan/product names in columns
- Yes/No or detailed values in cells

### 4. FAQ Database
Structure your FAQ as:
- Question column
- Answer column
- Category column

## How to Upload Excel Files

1. Navigate to your chatbot's **Details** page
2. Go to the **Training Documents** section
3. Click the **File Upload** tab
4. Select your `.xlsx` file
5. Click **Upload Document**

The system will:
- Extract all data from all sheets
- Convert to structured format
- Generate an AI knowledge base
- Train your chatbot

## File Requirements

- **Format**: `.xlsx` (Excel 2007 and later)
- **Size Limit**: Based on your subscription plan
- **Structure**: First row should be headers
- **Data**: Can contain text, numbers, dates, formulas (values only)

## Technical Details

### Dependencies
- `openpyxl>=3.0.0` - Python library for reading/writing Excel files

### Processing Method
The Excel processor:
1. Loads the workbook in read-only mode with `data_only=True` (shows formula results)
2. Iterates through all sheets
3. Extracts rows and identifies headers
4. Converts to structured JSON
5. Formats for AI training with both JSON and text representations

### Code Location
- **Processor**: `services/document_processor.py`
  - `_process_xlsx()` - Main Excel processing method
  - `_excel_to_structured_json()` - Converts to structured format
  - `_format_sheet_for_training()` - Formats for AI (shared with Google Sheets)

## Supported File Types

The platform now supports:
- **PDF** (`.pdf`) - Extract text from PDF documents
- **Word** (`.docx`) - Extract text from Word documents
- **Text** (`.txt`) - Plain text files
- **JSON** (`.json`) - Structured JSON data
- **Excel** (`.xlsx`) - Spreadsheet data (NEW!)

Plus remote sources:
- **Google Docs** - Via shareable link
- **Google Sheets** - Via shareable link

## Example Workflow

### Creating a Product Knowledge Base

1. **Prepare your Excel file**:
   ```
   | Product Name    | Price   | Description           | Category      |
   |-----------------|---------|----------------------|---------------|
   | Basic Plan      | $9.99   | For individuals      | Subscription  |
   | Pro Plan        | $29.99  | For small teams      | Subscription  |
   | Enterprise Plan | $99.99  | For organizations    | Subscription  |
   ```

2. **Upload the file** through the chatbot dashboard

3. **Training happens automatically**:
   - OpenAI analyzes the structured data
   - Creates semantic understanding
   - Generates Q&A patterns
   - Builds knowledge base

4. **Chatbot is ready**:
   - Can answer questions about products
   - Understands pricing
   - Knows product differences
   - Provides accurate information

## Best Practices

### ✅ Do:
- Use clear, descriptive column headers
- Keep data clean and consistent
- Use one header row at the top
- Include all relevant information
- Group related data in separate sheets

### ❌ Avoid:
- Merged cells (may cause parsing issues)
- Complex formulas (only values are read)
- Empty header cells
- Multiple header rows
- Excessive formatting (only data is extracted)

## Troubleshooting

### Issue: "No data found in Excel file"
**Solution**: Ensure your Excel file has at least one non-empty row with headers and data.

### Issue: "Error processing Excel file"
**Possible causes**:
- File is corrupted
- File is password-protected (not supported)
- File is too large
- File uses unsupported Excel features

**Solution**: Try opening the file in Excel, save a fresh copy, and upload again.

### Issue: "Some columns are missing"
**Solution**: Make sure all header cells in the first row have values. Empty header cells are skipped.

## Performance

- **Small files** (< 100 rows): Process in seconds
- **Medium files** (100-1000 rows): Process in 10-30 seconds
- **Large files** (> 1000 rows): May take 1-2 minutes

Processing time depends on:
- Number of sheets
- Number of rows
- Complexity of data
- OpenAI API response time

## Future Enhancements

Potential future improvements:
- Support for `.xls` (older Excel format)
- Custom sheet selection
- Advanced data validation
- Column type detection
- Relationship mapping between sheets
- Excel formula evaluation

## Related Documentation

- [Google Sheets Feature](GOOGLE_SHEETS_FEATURE.md)
- [Google Docs Feature](GOOGLE_DOCS_FEATURE.md)
- [Knowledge Base System](KNOWLEDGE_BASE_SYSTEM.md)
- [Document Processing Guide](IMPLEMENTATION_SUMMARY.md)

## Summary

The Excel spreadsheet feature provides a powerful way to train your chatbot with structured data. It's perfect for e-commerce sites, SaaS platforms, service businesses, and any organization with tabular data they want their chatbot to understand and discuss with users.

Upload your Excel files and watch your chatbot become an expert on your products, plans, pricing, and more! 📊🤖

