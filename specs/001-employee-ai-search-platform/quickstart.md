# Quickstart - Updated Implementation Summary

This document provides a quickstart guide for the Employee AI Search Platform after the recent updates.

## 🎯 Platform Overview

Employee AI Search is a document indexing and Q&A platform that lets teams upload documents and ask questions about them. Answers are sourced from your own documents with citations to show which parts were used.

## ✨ Recent Changes

### 1. Page Number Inference Removed

**What Changed:**
- Removed the heuristic that detected printed page numbers from PDF text
- Page numbers now only come from PDF `/PageLabels` (when available) 
- Physical page numbers (`page_number`) remain available for citations
- No more offset detection between physical and printed pages

**Impact:**
- Citations are now simpler and more predictable
- Users don't need to re-upload documents after changes
- Reduced complexity in the ingestion pipeline

**Testing:**
- Updated PDF ingestion tests
- Verified backward compatibility with existing documents

### 2. Light Mode Toggle Added

**What Changed:**
- Added theme toggle (Sun/Moon icon) in the header
- Theme preference persists across sessions via `localStorage`
- Updated CSS with variables for both dark and light themes
- Updated Tailwind config with `darkMode: "class"`

**Impact:**
- Users can choose their preferred theme
- Better accessibility for low-light environments
- Modern, up-to-date UI

**Testing:**
- Manual testing: Toggle theme and verify styles
- Check localStorage persistence
- Verify responsive design

### 3. AI Design Elements Removed

**What Changed:**
- Removed `Sparkles` icon from header and empty state
- Simplified tagline from "Researcher → Retriever → Synthesizer" to "Knowledge base search"
- Cleaned up empty state text and sample prompts
- Removed gradient backgrounds and glow effects
- Simplified citation display

**Impact:**
- Cleaner, more professional appearance
- Less AI-specific visual clutter
- Focus on user actions and documents
- Reduced cognitive load

**Testing:**
- Visual review of all components
- Verify no Sparkles icons remain
- Check that copy is clean and direct

## 🚀 Getting Started

### Prerequisites

- Node.js 18+
- TypeScript 5+
- Docker (optional, for local development)
- PostgreSQL (if using database)
- Supabase (for authentication, optional)

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/Ali-Al-Ali-9/employee-ai-search.git
   cd employee-ai-search
   ```

2. **Install dependencies**
   ```bash
   cd frontend
   npm install
   cd ../backend  
   pip install -r requirements.txt
   ```

3. **Start the backend**
   ```bash
   cd backend
   python -m app  # or use docker-compose
   ```

4. **Start the frontend**
   ```bash
   cd frontend
   npm run dev
   ```

5. **Open your browser**
   Navigate to `http://localhost:3000`

### Environment Configuration

Create a `.env` file in the backend directory:

```env
# Supabase configuration (if using)
SUPABASE_URL=your-supabase-url
SUPABASE_JWT_SECRET=your-jwt-secret

# Database configuration
DATABASE_URL=postgresql://user:password@localhost:5432/employee_ai_search

# LLM configuration
LLM_API_KEY=your-llm-api-key  # Admin-only
LLM_BYOK_ENABLED=true

# Application settings
INVITE_CODE=optional-invite-code
PDF_VISUAL_ORDER_REPAIR=true
MAX_CHUNKS_PER_DOCUMENT=100
CHUNK_SIZE_TOKENS=500
CHUNK_OVERLAP_TOKENS=50
```

## 📚 Usage Guide

### Basic Workflow

1. **Upload Documents**
   - Click the "Documents" panel (or ☰ menu on mobile)
   - Upload PDF, DOCX, TXT, or MD files
   - Wait for indexing to complete

2. **Ask Questions**
   - Type your question in the chat input
   - Use sample prompts for quick starts
   - Review citations to see which documents were used

3. **Manage Documents**
   - View document status and chunks
   - Delete documents (admin-only)
   - Upload replacements (owner/admin-only)

### Key Features

- **Multi-language Support**: English and Arabic
- **Document Management**: Upload, replace, and delete
- **Citation Display**: See exactly where answers come from
- **Role-Based Access**: Viewer, User, Admin roles
- **BYOK LLM**: Use your own LLM API key
- **Theme Toggle**: Switch between dark and light mode

### Authentication

- **Guest Access**: Sign in as guest (limited functionality)
- **User Registration**: Open registration or invite-only (based on `INVITE_CODE`)
- **Admin Controls**: Full user management and system administration

## 🧪 Testing

### Backend Tests
```bash
cd backend
python -m pytest
```

### Frontend Tests
```bash
cd frontend
npm test
```

### Type Checking
```bash
cd frontend
npx tsc --noEmit
```

### Build
```bash
cd frontend
npm run build
```

## 🔧 Configuration Options

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `INVITE_CODE` | Optional invite code for registration | empty (open) |
| `LLM_BYOK_ENABLED` | Allow users to add their own LLM keys | true |
| `PDF_VISUAL_ORDER_REPAIR` | Fix visual order for RTL documents | true |
| `MAX_CHUNKS_PER_DOCUMENT` | Limit chunks per file | 100 |

### Admin Features

- User management (create, update, delete users)
- Reset user passwords
- Sync with Supabase
- View system logs

## 📖 Documentation

- **README.md**: Complete implementation summary
- **specs/**: Detailed technical specifications
- **API Documentation**: Available in the backend code

## 🚨 Important Notes

1. **Data Persistence**: SQLite data is wiped on redeploy unless `DATABASE_URL` is configured
2. **Page Labels**: Documents uploaded before changes will keep existing page labels
3. **LLM Keys**: Server API key is admin-only; users must supply their own
4. **Mobile**: Use ☰ menu to access document panel on mobile

## 🆘 Troubleshooting

### Common Issues

**Q: Theme toggle not working?**
- Check browser console for JavaScript errors
- Clear browser cache and reload
- Ensure localStorage is enabled

**Q: Documents not appearing?**
- Check that backend is running
- Verify file formats are supported
- Check document status for errors

**Q: Arabic text not displaying?**
- Ensure browser supports Arabic
- Check character encoding in files
- Verify RTL direction is set

**Q: LLM key verification failing?**
- Check API key format
- Verify provider supports the key
- Ensure `LLM_BYOK_ENABLED` is true

### Getting Help

1. Check the repository issues
2. Review the application logs
3. Verify environment configuration
4. Test with a simple document upload

## ✨ Platform Benefits

After these updates, the platform offers:

- **Cleaner UI**: Less visual noise and AI-specific elements
- **Better Accessibility**: Theme toggle for low-light environments
- **Simpler Page Numbers**: More predictable citation behavior
- **Modern Standards**: CSS variables and class-based theming
- **Maintainability**: Reduced complexity in the ingestion pipeline

## 🎉 Next Steps

1. **Test the theme toggle** and light mode
2. **Verify document uploads** work with simplified page handling
3. **Review the cleaned-up UI** for any remaining AI elements
4. **Monitor performance** after the changes
5. **Update documentation** if needed

---

*Version: Updated Implementation*
*Last Updated: 2026*
*Contact: Project Team*