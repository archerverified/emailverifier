# Lead Validator - Testing Guide

This guide will help you test the Lead Validator application after cloning from GitHub.

## Quick Start (5 minutes)

### Option 1: Docker (Recommended - Easiest)

```bash
# 1. Clone the repository
git clone <your-github-repo-url>
cd "Email Verifier Warp"

# 2. Start the application
docker compose up --build

# 3. Open your browser
# Go to: http://localhost:5050

# 4. Test with sample data
# Drag and drop Fortune500leads.csv into the upload area
```

**To stop:**
```bash
docker compose down
```

---

### Option 2: Local Development (Windows)

```powershell
# 1. Clone the repository
git clone <your-github-repo-url>
cd "Email Verifier Warp"

# 2. Set up backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Start backend server
$env:VALIDATOR_MODE="real"  # or "mock" for fast testing
python app.py

# 4. Open another terminal for frontend
cd ../frontend
python -m http.server 3000

# 5. Open browser to http://localhost:3000
```

---

## Testing Checklist

### 1. Basic Upload & Verification (2 min)

- [ ] Open http://localhost:5050 (Docker) or http://localhost:3000 (Local)
- [ ] Drag `Fortune500leads.csv` onto the drop zone
- [ ] Verify progress bar shows real-time updates
- [ ] Wait for "Complete" message
- [ ] Download "All Leads" CSV and verify it contains original data + status/score columns

### 2. Multiple Concurrent Jobs (1 min)

- [ ] Upload `Fortune500leads.csv` again (or another CSV)
- [ ] Verify both jobs show in the UI with separate progress bars
- [ ] Verify both complete successfully

### 3. Job Persistence (1 min)

- [ ] Refresh the browser page (F5)
- [ ] Verify existing jobs are restored from localStorage
- [ ] Check "Recent Jobs" panel shows job history from database
- [ ] Expand a job in history and verify summary stats are shown

### 4. Column Detection (1 min)

Create a test CSV named `test_emails.csv`:
```csv
name,contact_email,company
John Doe,john@example.com,Acme Inc
Jane Smith,jane@example.org,Tech Corp
```

- [ ] Upload `test_emails.csv`
- [ ] Verify it auto-detects "contact_email" column
- [ ] Verification completes successfully

### 5. Filtered Downloads (2 min)

After a job completes:
- [ ] Download "Valid Only" - verify CSV only contains valid emails
- [ ] Download "Risky Only" - verify CSV only contains risky emails
- [ ] Download "Scores Only" - verify CSV contains: email, status, score, risk_factors
- [ ] Download "ZIP Bundle" - verify ZIP contains all 5 CSVs + summary.json

### 6. Job Management (1 min)

- [ ] In "Recent Jobs" panel, expand a completed job
- [ ] Click "Delete" button
- [ ] Confirm deletion
- [ ] Verify job is removed from the list

### 7. Cancel Functionality (1 min)

- [ ] Upload a large CSV (Fortune500leads.csv)
- [ ] Click "Cancel" while it's processing
- [ ] Verify status changes to "Canceled"
- [ ] Verify download buttons are hidden

### 8. Error Handling (1 min)

Create a CSV without email column named `no_email.csv`:
```csv
name,company
Alice,Acme
Bob,Beta
```

- [ ] Upload `no_email.csv`
- [ ] Verify error message: "No email column found"
- [ ] Verify error banner shows available columns

### 9. API Endpoints (1 min)

Open these URLs in your browser:
- [ ] http://localhost:5050/health - should return `{"status":"ok"}`
- [ ] http://localhost:5050/schema - should show API schema with version
- [ ] http://localhost:5050/metrics - should show job counts and storage stats
- [ ] http://localhost:5050/jobs - should list all jobs

### 10. Mock Mode Testing (30 seconds)

Stop the backend and restart in mock mode for fast testing:

```powershell
# Windows
$env:VALIDATOR_MODE="mock"
python app.py

# Mac/Linux
export VALIDATOR_MODE=mock
python app.py
```

- [ ] Upload `Fortune500leads.csv`
- [ ] Verify verification completes in ~2 seconds (vs 10+ minutes in real mode)
- [ ] Verify results are deterministic (same CSV = same results)

---

## Automated Testing

### Run Test Suite

```bash
cd backend
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate    # Mac/Linux

# Set mock mode for fast tests
$env:VALIDATOR_MODE="mock"
$env:TESTING="1"

# Run all 88 tests
pytest -v

# Expected output: 88 passed in ~4 seconds
```

### Run Smoke Test

```bash
# From project root
python scripts/smoke_test.py

# Expected output: All checks pass, no errors
```

---

## Performance Testing

### Small CSV (< 100 rows)
- **Mock mode**: ~1 second
- **Real mode**: ~1-2 minutes

### Medium CSV (500-1000 rows)
- **Mock mode**: ~2 seconds
- **Real mode**: ~8-15 minutes

### Large CSV (5000+ rows)
- **Mock mode**: ~5 seconds
- **Real mode**: ~40-60 minutes (due to SMTP checks)

**Recommendation**: Use mock mode for testing UI/UX, real mode for actual lead validation.

---

## Troubleshooting

### Issue: "Connection refused" error
**Solution**: Make sure backend is running on port 5050
```bash
netstat -an | findstr 5050  # Windows
lsof -i :5050              # Mac/Linux
```

### Issue: Jobs not persisting after refresh
**Solution**: Check browser console for localStorage errors. Try clearing localStorage:
```javascript
// In browser console
localStorage.clear()
location.reload()
```

### Issue: Database errors
**Solution**: Delete and recreate database
```bash
rm backend/storage/lead_validator.db
# Restart backend - it will recreate DB automatically
```

### Issue: Tests failing
**Solution**: Ensure TESTING=1 is set
```bash
$env:TESTING="1"
$env:VALIDATOR_MODE="mock"
pytest -v
```

### Issue: CORS errors in browser console
**Solution**: Access via localhost, not file://
- ✅ http://localhost:3000
- ✅ http://localhost:5050
- ❌ file:///C:/path/to/index.html

---

## Next Steps After Testing

1. **For production use**: Set `VALIDATOR_MODE=real` for actual SMTP verification
2. **For CI/CD**: Use the GitHub Actions workflow (already configured)
3. **For deployment**: Use Docker for easiest deployment
4. **For customization**: See README.md for configuration options

---

## Support

- Check `README.md` for detailed documentation
- See `CHANGELOG.md` for version history
- Review test files in `backend/tests/` for API examples

---

**Happy testing! 🚀**
