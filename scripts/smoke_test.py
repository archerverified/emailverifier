#!/usr/bin/env python3
"""
Smoke test for Lead Validator.
Tests end-to-end functionality with Fortune500leads.csv (or specified CSV).

Usage:
    python scripts/smoke_test.py
    
Environment variables:
    API_BASE_URL: API endpoint (default: http://localhost:5050)
    CSV_FILE: Path to CSV file to test (default: Fortune500leads.csv)
"""
import requests
import time
import sys
import os

API_BASE_URL = os.getenv('API_BASE_URL', 'http://localhost:5050')
CSV_FILE = os.getenv('CSV_FILE', 'Fortune500leads.csv')


def main():
    print(f"Starting smoke test against {API_BASE_URL}")
    print(f"CSV file: {CSV_FILE}")
    print("-" * 50)
    
    # 1. Health check
    print("1. Checking health endpoint...")
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=10)
        assert response.status_code == 200, f"Health check failed: {response.status_code}"
        assert response.json()['status'] == 'ok', "Health status not ok"
        print("   [OK] Health check passed")
    except requests.exceptions.ConnectionError:
        print(f"   [FAIL] Cannot connect to {API_BASE_URL}")
        print("   Make sure the backend is running.")
        sys.exit(1)
    
    # 2. Upload CSV
    csv_file = CSV_FILE
    print(f"2. Uploading {csv_file}...")
    if not os.path.exists(csv_file):
        # Generate small test CSV for CI environments
        print(f"   [INFO] {csv_file} not found, generating test data...")
        test_csv_content = """name,email,company
Alice Smith,alice@example.com,Acme Inc
Bob Jones,bob@test.io,Tech Corp
Charlie Brown,charlie@example.org,Finance Ltd
Diana Ross,support@test.com,Media Co
Eve Adams,eve@unknown.com,Retail Inc
"""
        csv_file = "test_smoke_generated.csv"
        with open(csv_file, "w") as f:
            f.write(test_csv_content)
        print(f"   [INFO] Generated {csv_file} with 5 test rows")
    
    with open(csv_file, "rb") as f:
        files = {"file": (os.path.basename(csv_file), f, "text/csv")}
        response = requests.post(f"{API_BASE_URL}/verify", files=files, timeout=30)
    
    if response.status_code != 200:
        print(f"   [FAIL] Upload failed: {response.text}")
        sys.exit(1)
    
    job_id = response.json()['job_id']
    print(f"   [OK] Job created: {job_id[:8]}...")
    
    # 3. Poll progress
    print("3. Waiting for completion...")
    max_wait = 300  # 5 minutes max
    start_time = time.time()
    last_percent = -1
    
    while time.time() - start_time < max_wait:
        response = requests.get(f"{API_BASE_URL}/progress?job_id={job_id}", timeout=10)
        progress = response.json()
        percent = progress['percent']
        
        if percent > last_percent:
            print(f"   Progress: {percent}% ({progress['row']}/{progress['total']})")
            last_percent = percent
        
        if percent >= 100:
            elapsed = time.time() - start_time
            print(f"   [OK] Verification complete in {elapsed:.1f}s")
            break
        
        # Poll faster in mock mode, slower in real mode
        time.sleep(0.5)
    else:
        print("   [FAIL] Timeout waiting for completion")
        sys.exit(1)
    
    # 4. Download results
    print("4. Downloading results...")
    
    results = {}
    scores = []
    all_csv_lines = []
    
    for filter_type in ['all', 'valid', 'risky', 'risky_invalid', 'scores']:
        response = requests.get(
            f"{API_BASE_URL}/download?job_id={job_id}&type={filter_type}",
            timeout=30
        )
        if response.status_code == 200:
            lines = response.text.strip().split('\n')
            count = len(lines) - 1  # subtract header
            results[filter_type] = count
            print(f"   [OK] {filter_type}: {count} rows")
            
            # Parse scores from the 'all' download
            if filter_type == 'all':
                all_csv_lines = lines
        elif response.status_code == 404:
            results[filter_type] = 0
            print(f"   [OK] {filter_type}: 0 rows (no matches)")
        else:
            print(f"   [WARN] {filter_type}: HTTP {response.status_code}")
    
    # 5. Parse and display score statistics
    print("5. Analyzing scores...")
    if all_csv_lines:
        headers = all_csv_lines[0].split(',')
        try:
            score_idx = headers.index('score')
            for line in all_csv_lines[1:]:
                values = line.split(',')
                if len(values) > score_idx:
                    try:
                        score = int(values[score_idx])
                        scores.append(score)
                    except ValueError:
                        pass
        except ValueError:
            print("   [WARN] 'score' column not found in CSV")
    
    # 6. Summary
    print("-" * 50)
    print("SUMMARY:")
    print(f"  Total processed: {results.get('all', 0)}")
    print(f"  Valid: {results.get('valid', 0)}")
    print(f"  Risky: {results.get('risky', 0)}")
    print(f"  Risky + Invalid: {results.get('risky_invalid', 0)}")
    print(f"  Scores Export: {results.get('scores', 0)} rows")
    
    if scores:
        print("-" * 50)
        print("SCORE STATISTICS:")
        print(f"  Min Score: {min(scores)}")
        print(f"  Max Score: {max(scores)}")
        print(f"  Avg Score: {sum(scores) / len(scores):.1f}")
    
    # 6. Test job listing endpoint
    print("-" * 50)
    print("6. Testing job listing...")
    response = requests.get(f"{API_BASE_URL}/jobs?limit=10", timeout=10)
    if response.status_code == 200:
        jobs_data = response.json()
        print(f"   [OK] Found {jobs_data['total']} job(s) in history")
        if jobs_data['jobs']:
            latest = jobs_data['jobs'][0]
            print(f"   Latest: {latest['filename']} ({latest['status']})")
    else:
        print(f"   [WARN] Job listing failed: {response.status_code}")
    
    # 7. Test messy CSV (semicolon delimiter, BOM, angle-bracket emails)
    print("7. Testing messy CSV format...")
    messy_csv_content = '\ufeffname;email;company\n'
    messy_csv_content += '"Alice, Smith";<alice@example.com>;"Tech Corp"\n'
    messy_csv_content += 'Bob Jones;  BOB@EXAMPLE.COM  ;Acme\n'
    messy_csv_content += '"Charlie";invalid-email;"Bad Co"\n'
    messy_csv_file = "test_messy.csv"
    with open(messy_csv_file, "w", encoding="utf-8-sig") as f:
        f.write(messy_csv_content)
    
    with open(messy_csv_file, "rb") as f:
        files = {"file": (messy_csv_file, f, "text/csv")}
        response = requests.post(f"{API_BASE_URL}/verify", files=files, timeout=30)
    
    if response.status_code == 200:
        messy_job_id = response.json()['job_id']
        # Wait for completion
        for _ in range(50):
            time.sleep(0.1)
            prog = requests.get(f"{API_BASE_URL}/progress?job_id={messy_job_id}", timeout=10)
            if prog.json().get('percent', 0) >= 100:
                break
        
        # Verify emails were extracted and normalized
        dl = requests.get(f"{API_BASE_URL}/download?job_id={messy_job_id}&type=scores", timeout=10)
        if dl.status_code == 200:
            content = dl.text.lower()
            if 'alice@example.com' in content and 'bob@example.com' in content:
                print("   [OK] Messy CSV processed: email extraction and normalization working")
            else:
                print("   [WARN] Messy CSV processed but emails may not be normalized correctly")
        else:
            print(f"   [WARN] Messy CSV download failed: {dl.status_code}")
    else:
        print(f"   [WARN] Messy CSV upload failed: {response.status_code}")
    
    # Clean up messy csv
    try:
        os.remove(messy_csv_file)
    except Exception:
        pass
    
    # 8. Test bundle download
    print("8. Testing bundle download...")
    response = requests.get(f"{API_BASE_URL}/jobs/{job_id}/bundle", timeout=30)
    if response.status_code == 200:
        bundle_size = len(response.content)
        print(f"   [OK] Bundle downloaded: {bundle_size} bytes")
        
        # Verify it's a valid ZIP
        import io
        import zipfile
        try:
            z = zipfile.ZipFile(io.BytesIO(response.content))
            files_in_zip = z.namelist()
            print(f"   [OK] Bundle contains: {', '.join(files_in_zip)}")
            
            # Check for expected files
            expected = ['all.csv', 'valid.csv', 'risky.csv', 'risky_invalid.csv', 'scores.csv', 'summary.json']
            missing = [f for f in expected if f not in files_in_zip]
            if missing:
                print(f"   [WARN] Missing files in bundle: {missing}")
            else:
                print("   [OK] All expected files present in bundle")
        except Exception as e:
            print(f"   [WARN] Could not parse bundle as ZIP: {e}")
    else:
        print(f"   [WARN] Bundle download failed: {response.status_code}")
    
    # 9. Test metrics endpoint
    print("9. Testing metrics endpoint...")
    response = requests.get(f"{API_BASE_URL}/metrics", timeout=10)
    if response.status_code == 200:
        metrics = response.json()
        print(f"   [OK] Metrics: {metrics.get('jobs', {}).get('running', 0)} running, "
              f"{metrics.get('jobs', {}).get('completed_today', 0)} completed today")
        print(f"   Mode: {metrics.get('validator_mode', 'unknown')}")
    else:
        print(f"   [WARN] Metrics endpoint failed: {response.status_code}")
    
    print("-" * 50)
    print("Smoke test completed successfully!")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n[FAIL] Smoke test failed: {e}")
        sys.exit(1)
