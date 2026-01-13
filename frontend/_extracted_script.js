// ============================================
    // CONFIGURATION - API URL Detection
    // ============================================
    const API_BASE_URL = window.location.origin.includes('localhost:3000')
      ? 'http://localhost:5050'
      : window.location.origin;

    // DOM Elements
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const jobsContainer = document.getElementById('jobs');
    const globalError = document.getElementById('global-error');
    const columnPickerModal = document.getElementById('column-picker-modal');
    const columnOptions = document.getElementById('column-options');
    const confirmColumnBtn = document.getElementById('confirm-column');
    const cancelPickerBtn = document.getElementById('cancel-picker');
    const rememberCheckbox = document.getElementById('remember-column');

    // State
    let jobList = JSON.parse(localStorage.getItem('verifier-jobs') || '[]');
    let columnPreferences = JSON.parse(localStorage.getItem('column-preferences') || '{}');
    let pendingFile = null;
    let selectedColumn = null;

    // Restore existing jobs
    jobList.forEach(({ job_id, fileName }) => createJobBlock(job_id, fileName, true));

    // ============================================
    // EMAIL COLUMN DETECTION (client-side)
    // ============================================
    const EMAIL_COLUMN_EXACT = ['email', 'e-mail', 'e_mail', 'emailaddress', 'email_address'];
    const EMAIL_COLUMN_CONTAINS = ['email', 'e-mail', 'mail'];

    function detectEmailColumns(headers) {
      const candidates = [];
      for (const header of headers) {
        const headerLower = header.toLowerCase().trim();
        const headerNormalized = headerLower.replace(/[\s\-_]/g, '');

        // Exact matches
        if (EMAIL_COLUMN_EXACT.includes(headerNormalized)) {
          candidates.push(header);
          continue;
        }

        // Contains email-related terms
        for (const pattern of EMAIL_COLUMN_CONTAINS) {
          if (headerLower.includes(pattern)) {
            candidates.push(header);
            break;
          }
        }
      }
      return candidates;
    }

    function parseCSVHeader(text) {
      // Parse first line of CSV to get headers
      const lines = text.split(/\r?\n/);
      if (lines.length === 0) return [];

      // Strip BOM if present
      let headerLine = lines[0];
      if (headerLine.charCodeAt(0) === 0xFEFF) {
        headerLine = headerLine.slice(1);
      }

      // Detect delimiter (comma, semicolon, or tab)
      const delimiter = detectDelimiter(headerLine);

      // Simple CSV header parsing (handles basic quoted fields)
      const headers = [];
      let current = '';
      let inQuotes = false;

      for (const char of headerLine) {
        if (char === '"') {
          inQuotes = !inQuotes;
        } else if (char === delimiter && !inQuotes) {
          headers.push(current.trim().replace(/^"|"$/g, ''));
          current = '';
        } else {
          current += char;
        }
      }
      if (current) {
        headers.push(current.trim().replace(/^"|"$/g, ''));
      }

      return headers;
    }

    function detectDelimiter(line) {
      // Count delimiter occurrences outside quotes
      const countOutsideQuotes = (str, delim) => {
        let count = 0;
        let inQuotes = false;
        for (const char of str) {
          if (char === '"') inQuotes = !inQuotes;
          else if (char === delim && !inQuotes) count++;
        }
        return count;
      };

      const commaCount = countOutsideQuotes(line, ',');
      const semicolonCount = countOutsideQuotes(line, ';');
      const tabCount = countOutsideQuotes(line, '\t');

      // Return delimiter with highest count
      if (semicolonCount > commaCount && semicolonCount >= tabCount) return ';';
      if (tabCount > commaCount && tabCount > semicolonCount) return '\t';
      return ',';
    }

    // ============================================
    // EVENT LISTENERS
    // ============================================
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', e => {
      e.preventDefault();
      dropZone.classList.add('hover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('hover'));
    dropZone.addEventListener('drop', e => {
      e.preventDefault();
      dropZone.classList.remove('hover');
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files[0]) {
        handleFile(fileInput.files[0]);
        fileInput.value = '';
      }
    });

    cancelPickerBtn.addEventListener('click', () => {
      columnPickerModal.style.display = 'none';
      pendingFile = null;
      selectedColumn = null;
    });

    confirmColumnBtn.addEventListener('click', () => {
      if (!selectedColumn || !pendingFile) return;

      // Save preference if checkbox is checked
      if (rememberCheckbox.checked) {
        columnPreferences[pendingFile.name] = selectedColumn;
        localStorage.setItem('column-preferences', JSON.stringify(columnPreferences));
      }

      columnPickerModal.style.display = 'none';
      uploadFile(pendingFile, selectedColumn);
      pendingFile = null;
      selectedColumn = null;
    });

    // ============================================
    // FILE HANDLING
    // ============================================
    function showGlobalError(message) {
      globalError.textContent = message;
      globalError.style.display = 'block';
      setTimeout(() => {
        globalError.style.display = 'none';
      }, 5000);
    }

    function handleFile(file) {
      if (!file.name.toLowerCase().endsWith('.csv')) {
        showGlobalError('Please upload a CSV file');
        return;
      }

      globalError.style.display = 'none';

      // Check for saved column preference
      const savedColumn = columnPreferences[file.name];
      if (savedColumn) {
        uploadFile(file, savedColumn);
        return;
      }

      // Read header to detect email columns
      const reader = new FileReader();
      reader.onload = function(e) {
        const text = e.target.result;
        const headers = parseCSVHeader(text);

        if (headers.length === 0) {
          showGlobalError('Could not read CSV headers. Please check file format.');
          return;
        }

        // Check if header row appears empty or contains only one blank-ish column
        const nonEmptyHeaders = headers.filter(h => h.trim().length > 0);
        if (nonEmptyHeaders.length === 0) {
          showGlobalError('CSV header row appears to be empty. Please check your file.');
          return;
        }

        const candidates = detectEmailColumns(headers);

        if (candidates.length === 0) {
          showGlobalError(`No email column found. Available columns: ${headers.join(', ')}`);
          return;
        }

        if (candidates.length === 1) {
          // Single candidate - auto-select and upload
          uploadFile(file, candidates[0]);
          return;
        }

        // Multiple candidates - show picker
        showColumnPicker(file, candidates, headers);
      };

      // Read first 2KB to get headers
      const slice = file.slice(0, 2048);
      reader.readAsText(slice);
    }

    function showColumnPicker(file, candidates, allHeaders) {
      pendingFile = file;
      selectedColumn = null;
      confirmColumnBtn.disabled = true;
      rememberCheckbox.checked = false;

      columnOptions.innerHTML = '';
      for (const col of candidates) {
        const option = document.createElement('label');
        option.className = 'column-option';
        option.innerHTML = `
          <input type="radio" name="email-column" value="${escapeHtml(col)}">
          <strong>${escapeHtml(col)}</strong>
        `;

        const radio = option.querySelector('input');
        radio.addEventListener('change', () => {
          // Update selected state
          document.querySelectorAll('.column-option').forEach(o => o.classList.remove('selected'));
          option.classList.add('selected');
          selectedColumn = col;
          confirmColumnBtn.disabled = false;
        });

        columnOptions.appendChild(option);
      }

      columnPickerModal.style.display = 'block';
      
      // ESC to close modal
      const closeOnEsc = (e) => {
        if (e.key === 'Escape') {
          columnPickerModal.style.display = 'none';
          pendingFile = null;
          selectedColumn = null;
          document.removeEventListener('keydown', closeOnEsc);
        }
      };
      document.addEventListener('keydown', closeOnEsc);
    }

    function uploadFile(file, emailColumn) {
      const formData = new FormData();
      formData.append('file', file);
      if (emailColumn) {
        formData.append('email_column', emailColumn);
      }

      fetch(`${API_BASE_URL}/verify`, {
        method: 'POST',
        body: formData
      })
      .then(res => {
        // Handle 429 Too Many Requests (concurrent job limit)
        if (res.status === 429) {
          return res.json().then(err => {
            showGlobalError(err.message || 'Too many concurrent jobs. Please wait for a job to complete.');
            return null;
          });
        }
        if (!res.ok) {
          return res.json().then(err => {
            // Check if we need to show column picker
            if (err.email_column_candidates && err.email_column_candidates.length > 1) {
              showColumnPicker(file, err.email_column_candidates, err.available_columns || []);
              return null;
            }
            throw new Error(err.error || 'Upload failed');
          });
        }
        return res.json();
      })
      .then(data => {
        if (!data) return; // Picker shown
        jobList.push({ job_id: data.job_id, fileName: file.name });
        localStorage.setItem('verifier-jobs', JSON.stringify(jobList));
        createJobBlock(data.job_id, file.name, false);
      })
      .catch(err => {
        showGlobalError(err.message || 'Failed to upload file. Is the backend running?');
      });
    }

    // ============================================
    // JOB BLOCK UI
    // ============================================
    function createJobBlock(job_id, fileName, isRestored) {
      const block = document.createElement('div');
      block.className = 'job-block';
      block.innerHTML = `
        <button type="button" class="close-job" aria-label="Close job">&times;</button>
        <div class="file-name"><strong>${escapeHtml(fileName)}</strong></div>
        <div class="progress-container"><div class="progress-bar"></div></div>
        <div class="status">${isRestored ? 'Checking status...' : 'Starting...'}</div>
        <div class="log-line"></div>
        <div class="error-message"></div>
        <div class="job-summary">
          <div class="summary-stats">
            <span class="stat valid">Valid: <strong>0</strong></span>
            <span class="stat risky">Risky: <strong>0</strong></span>
            <span class="stat invalid">Invalid: <strong>0</strong></span>
            <span class="stat score">Avg Score: <strong>0</strong></span>
          </div>
          <div class="top-risks">Top Risks: <em>None detected</em></div>
        </div>
        <div class="actions"><a class="cancel cancel-btn">Cancel</a></div>
      `;
      jobsContainer.prepend(block);

      const bar = block.querySelector('.progress-bar');
      const status = block.querySelector('.status');
      const logLine = block.querySelector('.log-line');
      const cancelBtn = block.querySelector('.cancel');
      const actions = block.querySelector('.actions');
      const closeBtn = block.querySelector('.close-job');
      const errorMsg = block.querySelector('.error-message');
      const jobSummary = block.querySelector('.job-summary');

      let canceled = false;
      let completed = false;

      const removeJob = () => {
        block.remove();
        jobList = jobList.filter(j => j.job_id !== job_id);
        localStorage.setItem('verifier-jobs', JSON.stringify(jobList));
      };

      const showError = (message) => {
        errorMsg.textContent = message;
        errorMsg.style.display = 'block';
      };

      const updateSummary = (summary) => {
        if (!summary) return;

        jobSummary.style.display = 'block';

        const validStat = jobSummary.querySelector('.stat.valid strong');
        const riskyStat = jobSummary.querySelector('.stat.risky strong');
        const invalidStat = jobSummary.querySelector('.stat.invalid strong');
        const scoreStat = jobSummary.querySelector('.stat.score strong');
        const topRisks = jobSummary.querySelector('.top-risks');

        validStat.textContent = summary.valid || 0;
        riskyStat.textContent = summary.risky || 0;
        invalidStat.textContent = summary.invalid || 0;
        scoreStat.textContent = summary.avg_score || 0;

        if (summary.top_risk_factors && summary.top_risk_factors.length > 0) {
          topRisks.innerHTML = 'Top Risks: ' +
            summary.top_risk_factors.map(f =>
              `<span class="risk-tag">${escapeHtml(f.replace(/_/g, ' '))}</span>`
            ).join('');
        } else {
          topRisks.innerHTML = 'Top Risks: <em>None detected</em>';
        }
      };

      cancelBtn.onclick = () => {
        canceled = true;
        fetch(`${API_BASE_URL}/cancel?job_id=${job_id}`, { method: 'POST' })
          .catch(() => {});
        status.innerText = 'Canceled';
        status.style.color = 'var(--color-danger)';
        actions.innerHTML = '';
      };

      closeBtn.onclick = () => {
        canceled = true;
        fetch(`${API_BASE_URL}/cancel?job_id=${job_id}`, { method: 'POST' })
          .catch(() => {});
        removeJob();
      };

      // Poll for progress
      const poll = setInterval(() => {
        if (canceled || completed) return clearInterval(poll);

        fetch(`${API_BASE_URL}/progress?job_id=${job_id}`)
          .then(res => res.json())
          .then(data => {
            bar.style.width = `${data.percent}%`;
            if (data.total > 0) {
              status.innerText = `${data.percent}% done – Row ${data.row} of ${data.total}`;
            }
            // Update summary if available
            if (data.summary) {
              updateSummary(data.summary);
            }
          })
          .catch(() => {
            if (isRestored) {
              status.innerText = 'Job not found (server may have restarted)';
              actions.innerHTML = '';
              clearInterval(poll);
            }
          });

        fetch(`${API_BASE_URL}/log?job_id=${job_id}`)
          .then(res => res.text())
          .then(text => {
            logLine.innerText = text.replace(/^\[\d+%\] \(\d+\/\d+\) /, '');
          })
          .catch(() => {});
      }, 1000);

      // Wait for completion
      const wait = setInterval(() => {
        if (canceled || completed) return clearInterval(wait);

        fetch(`${API_BASE_URL}/progress?job_id=${job_id}`)
          .then(res => res.json())
          .then(data => {
            if (data.percent >= 100) {
              completed = true;
              clearInterval(wait);
              clearInterval(poll);
              bar.style.width = '100%';
              status.innerText = `Complete - ${data.total} emails verified`;
              status.style.color = 'var(--color-success)';

              // Update summary
              if (data.summary) {
                updateSummary(data.summary);
              }

              // Show download buttons
              actions.innerHTML = `
                <div class="download-section">
                  <div class="download-section-title">Download Results</div>
                  <div class="download-grid">
                    <a href="${API_BASE_URL}/download?job_id=${job_id}&type=all" target="_blank">All Leads</a>
                    <a href="${API_BASE_URL}/download?job_id=${job_id}&type=valid" target="_blank">Valid Only</a>
                    <a href="${API_BASE_URL}/download?job_id=${job_id}&type=risky" target="_blank">Risky Only</a>
                    <a href="${API_BASE_URL}/download?job_id=${job_id}&type=risky_invalid" target="_blank">Risky + Invalid</a>
                    <a href="${API_BASE_URL}/download?job_id=${job_id}&type=scores" target="_blank" class="scores">Scores Only</a>
                    <a href="${API_BASE_URL}/jobs/${job_id}/bundle" target="_blank" class="bundle">Download ZIP Bundle</a>
                  </div>
                </div>
              `;
            }
          })
          .catch(() => {});
      }, 1500);
    }

    // Utility function to escape HTML
    function escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    // ============================================
    // JOB HISTORY
    // ============================================
    const jobHistoryPanel = document.getElementById('job-history-panel');
    const historyList = document.getElementById('history-list');
    const loadMoreBtn = document.getElementById('load-more-jobs');
    const refreshHistoryBtn = document.getElementById('refresh-history');

    let historyOffset = 0;
    const historyLimit = 20;
    let historyTotal = 0;

    // Fetch and display job history on page load
    function loadJobHistory(append = false) {
      const offset = append ? historyOffset : 0;

      fetch(`${API_BASE_URL}/jobs?limit=${historyLimit}&offset=${offset}`)
        .then(res => res.json())
        .then(data => {
          if (!append) {
            historyList.innerHTML = '';
            historyOffset = 0;
          }

          historyTotal = data.total || 0;

          if (data.jobs && data.jobs.length > 0) {
            jobHistoryPanel.style.display = 'block';

            // Reconcile localStorage with backend jobs
            const backendJobIds = new Set(data.jobs.map(j => j.id));
            reconcileLocalStorage(backendJobIds);

            data.jobs.forEach(job => {
              // Skip jobs that are in the current session's job list
              if (jobList.some(j => j.job_id === job.id)) {
                return;
              }
              renderHistoryJob(job);
            });

            historyOffset += data.jobs.length;

            // Show/hide load more button
            if (historyOffset < historyTotal) {
              loadMoreBtn.style.display = 'block';
            } else {
              loadMoreBtn.style.display = 'none';
            }
          } else if (!append && historyList.children.length === 0) {
            // Show "no history" message only if no current jobs either
            if (jobList.length === 0) {
              historyList.innerHTML = '<div class="no-history">No verification history yet</div>';
              jobHistoryPanel.style.display = 'block';
            }
          }
        })
        .catch(err => {
          console.log('Could not load job history:', err);
        });
    }

    function reconcileLocalStorage(backendJobIds) {
      // Remove jobs from localStorage that are not in the backend
      // (stale entries from before persistence was added)
      const validJobs = jobList.filter(j => backendJobIds.has(j.job_id));
      if (validJobs.length !== jobList.length) {
        jobList = validJobs;
        localStorage.setItem('verifier-jobs', JSON.stringify(jobList));
      }
    }

    function formatDate(isoString) {
      if (!isoString) return 'Unknown';
      const date = new Date(isoString);
      return date.toLocaleString();
    }

    function renderHistoryJob(job) {
      const jobEl = document.createElement('div');
      jobEl.className = 'history-job';
      jobEl.dataset.jobId = job.id;

      const statusClass = job.status || 'completed';
      const statusText = job.status ? job.status.charAt(0).toUpperCase() + job.status.slice(1) : 'Unknown';

      jobEl.innerHTML = `
        <div class="history-job-header">
          <div class="history-job-info">
            <div class="history-job-filename">${escapeHtml(job.filename || 'Unknown file')}</div>
            <div class="history-job-meta">
              ${formatDate(job.created_at)} • ${job.total_rows || 0} rows
            </div>
          </div>
          <span class="history-job-status ${statusClass}">${statusText}</span>
        </div>
        <div class="history-job-details">
          ${job.status === 'completed' ? `
            <div class="job-summary" style="display:block;">
              <div class="summary-stats">
                <span class="stat valid">Valid: <strong>${job.summary_valid || 0}</strong></span>
                <span class="stat risky">Risky: <strong>${job.summary_risky || 0}</strong></span>
                <span class="stat invalid">Invalid: <strong>${job.summary_invalid || 0}</strong></span>
                <span class="stat score">Avg Score: <strong>${job.avg_score || 0}</strong></span>
              </div>
              ${job.top_risk_factors && job.top_risk_factors.length > 0 ? `
                <div class="top-risks">Top Risks: ${job.top_risk_factors.map(f =>
                  `<span class="risk-tag">${escapeHtml(f.replace(/_/g, ' '))}</span>`
                ).join('')}</div>
              ` : '<div class="top-risks">Top Risks: <em>None detected</em></div>'}
            </div>
            <div class="download-grid">
              <a href="${API_BASE_URL}/download?job_id=${job.id}&type=all" target="_blank">All Leads</a>
              <a href="${API_BASE_URL}/download?job_id=${job.id}&type=valid" target="_blank">Valid Only</a>
              <a href="${API_BASE_URL}/download?job_id=${job.id}&type=risky" target="_blank">Risky Only</a>
              <a href="${API_BASE_URL}/download?job_id=${job.id}&type=risky_invalid" target="_blank">Risky + Invalid</a>
              <a href="${API_BASE_URL}/download?job_id=${job.id}&type=scores" target="_blank" class="scores">Scores Only</a>
              <a href="${API_BASE_URL}/jobs/${job.id}/bundle" target="_blank" class="bundle">Download ZIP Bundle</a>
            </div>
          ` : `
            <p class="history-job-error-text">
              Job ${job.status === 'cancelled' ? 'was cancelled' : 'failed'}. No downloads available.
              ${job.error_message && job.error_message.toLowerCase().includes('stalled') ? '<span class="stalled-badge"> (Stalled)</span>' : ''}
            </p>
            ${job.error_message ? `<div class="history-job-error-detail">${escapeHtml(job.error_message)}</div>` : ''}
          `}
          <div class="history-job-actions">
            <span>ID: ${job.id.substring(0, 8)}...</span>
            <button type="button" class="btn-delete" onclick="deleteHistoryJob('${job.id}')">Delete</button>
          </div>
        </div>
      `;

      // Toggle expand/collapse
      const header = jobEl.querySelector('.history-job-header');
      header.addEventListener('click', () => {
        jobEl.classList.toggle('expanded');
      });

      historyList.appendChild(jobEl);
    }

    function deleteHistoryJob(jobId) {
      if (!confirm('Are you sure you want to delete this job? This will remove all associated files.')) {
        return;
      }

      fetch(`${API_BASE_URL}/jobs/${jobId}`, { method: 'DELETE' })
        .then(res => {
          if (res.ok) {
            // Remove from DOM
            const jobEl = historyList.querySelector(`[data-job-id="${jobId}"]`);
            if (jobEl) {
              jobEl.remove();
            }
            // Also remove from jobList if present
            jobList = jobList.filter(j => j.job_id !== jobId);
            localStorage.setItem('verifier-jobs', JSON.stringify(jobList));
          } else {
            return res.json().then(err => {
              throw new Error(err.error || 'Delete failed');
            });
          }
        })
        .catch(err => {
          showGlobalError(err.message || 'Failed to delete job');
        });
    }

    const clearLocalHistoryBtn = document.getElementById('clear-local-history');

    refreshHistoryBtn.addEventListener('click', () => loadJobHistory(false));
    loadMoreBtn.addEventListener('click', () => loadJobHistory(true));

    clearLocalHistoryBtn.addEventListener('click', () => {
      if (confirm('Clear all job history from local storage? (Jobs will still exist on server)')) {
        localStorage.removeItem('verifier-jobs');
        localStorage.removeItem('column-preferences');
        jobList = [];
        columnPreferences = {};

        // Clear current job blocks from UI
        jobsContainer.innerHTML = '';

        // Reload history from server
        loadJobHistory(false);

        showGlobalError('Local history cleared. Showing server history only.');
      }
    });

    // Load history on page load
    loadJobHistory();