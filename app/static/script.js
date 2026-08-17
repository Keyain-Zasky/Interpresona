let sheets = [];
let selectedSheets = new Set();
let workspaceFiles = [];
let selectedWorkspace = new Set();

document.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    loadCatalog();
    refreshWorkspaceFiles();
    document.getElementById('catalog-search').addEventListener('input', renderCatalog);
    document.getElementById('catalog-category').addEventListener('change', renderCatalog);
    const dropzone = document.querySelector('.dropzone');
    const fileInput = document.getElementById('csv-upload');
    if (dropzone && fileInput) {
        ['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, event => {
            event.preventDefault(); dropzone.classList.add('dragging');
        }));
        ['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, event => {
            event.preventDefault(); dropzone.classList.remove('dragging');
        }));
        dropzone.addEventListener('drop', event => {
            fileInput.files = event.dataTransfer.files;
            uploadCsv(fileInput);
        });
    }
});

function showView(view) {
    const home = document.getElementById('home-view');
    const settings = document.getElementById('settings-view');
    const showingSettings = view === 'settings';
    home.hidden = showingSettings;
    settings.hidden = !showingSettings;
    if (showingSettings) loadSettings();
    window.scrollTo({top: 0, behavior: 'smooth'});
}

async function loadSettings() {
    try {
        const data = await (await fetch('/api/settings')).json();
        document.getElementById('settings-game').value = data.game_dir || '';
        document.getElementById('settings-project').value = data.project_dir || '';
        document.getElementById('settings-test').value = data.test_dir || '';
        updateSettingsCheck(data);
    } catch (_) { showToast('Impossibile caricare le impostazioni.', 'error'); }
}

function updateSettingsCheck(data) {
    const check = document.getElementById('settings-check');
    if (!check) return;
    const ready = data.sqpack_ok && data.test_ok && data.workspace_ok && data.exd_ok;
    check.className = `settings-check ${ready ? 'valid' : 'invalid'}`;
    check.textContent = ready ? '✓ I tre percorsi sono accessibili e le cartelle interne del progetto sono pronte.' : '! Il percorso del gioco, di test o del progetto non è accessibile.';
}

async function saveSettings() {
    const payload = {
        game_dir: document.getElementById('settings-game').value.trim(),
        project_dir: document.getElementById('settings-project').value.trim(),
        test_dir: document.getElementById('settings-test').value.trim()
    };
    try {
        const res = await fetch('/api/settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Salvataggio fallito');
        updateSettingsCheck(data);
        showToast('Impostazioni salvate.');
        await checkStatus(); await loadCatalog(); await refreshWorkspaceFiles();
        setTimeout(() => showView('home'), 350);
    } catch (error) { showToast(error.message, 'error'); }
}

async function importConfiguredCsvs() {
    try {
        const res = await fetch('/api/import_csv_folder', {method: 'POST'});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Importazione fallita');
        showToast(`${data.imported.length} CSV importati${data.errors.length ? `, ${data.errors.length} ignorati` : ''}.`, data.errors.length ? 'error' : 'success');
        const output = document.getElementById('operation-result');
        if (output && data.byte_audit?.length) { output.hidden = false; output.className = 'operation-result'; output.innerHTML = `<strong>Importazione CSV completata.</strong><br><span>${escapeHtml(data.history_dir || '')}</span>${renderCsvAudit(data.byte_audit)}`; }
        await refreshWorkspaceFiles();
    } catch (error) { showToast(error.message, 'error'); }
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.animation = 'fadeOut 0.3s ease forwards'; setTimeout(() => toast.remove(), 300); }, 5000);
}

function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, character => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'}[character]));
}

function describeFiles(files) {
    if (!Array.isArray(files)) return '';
    return files.map(file => {
        if (typeof file === 'string') return file;
        if (!file || typeof file !== 'object') return String(file);
        const name = file.file || file.name || 'file sconosciuto';
        const offsets = file.new_offset ? ` · nuovo offset ${file.new_offset}` : '';
        return `${name}${offsets}`;
    }).join('<br>');
}

function renderByteAudit(results) {
    const audits = results.flatMap(item => (item.byte_audit || []).map(audit => ({...audit, sheet: item.name})));
    if (!audits.length) return '';
    window.lastByteAudits = audits;
    const changed = audits.filter(item => item.changed);
    const warning = audits.filter(item => item.changed && item.delta_bytes > 0);
    const renderAuditRow = item => {
        const delta = `${item.delta_bytes >= 0 ? '+' : ''}${item.delta_bytes} B`;
        const warning = item.warning ? `<span class="byte-warning">⚠ ${escapeHtml(item.warning)}</span>` : '';
        return `<div class="byte-line"><span class="byte-file">${escapeHtml(item.sheet)} / ${escapeHtml(item.file)}</span><span>${item.original_bytes} → ${item.translated_bytes} B</span><span class="byte-delta ${item.changed ? '' : 'equal'}">${delta}</span>${warning}</div>`;
    };
    const rows = audits.map(renderAuditRow).join('');
    const warningRows = changed.map(renderAuditRow).join('');
    return `<section class="crash-audit"><div class="crash-audit-head"><div><strong>⚠ Possibili rischi di crash</strong><span>${warning.length} aumenti · ${changed.length} differenze · ${audits.length} pagine controllate</span></div><div class="audit-controls"><label>Filtra <select id="byte-filter" onchange="refreshCrashAudit()"><option value="changed">Solo differenze</option><option value="increase">Solo aumenti</option><option value="all">Tutte</option><option value="equal">Senza differenze</option></select></label><label>Ordina <select id="byte-sort" onchange="refreshCrashAudit()"><option value="absolute">Delta assoluto</option><option value="delta">Delta numerico</option><option value="file">Nome file</option></select></label></div></div><div id="crash-audit-list" class="operation-log">${warningRows || '<span class="footer-note">Nessuna differenza dimensionale rilevata.</span>'}</div></section><div class="generic-audit"><strong>Log completo delle pagine</strong><div class="operation-log">${rows}</div></div>`;
}

function refreshCrashAudit() {
    const list = document.getElementById('crash-audit-list');
    if (!list || !Array.isArray(window.lastByteAudits)) return;
    const filter = document.getElementById('byte-filter')?.value || 'changed';
    const sort = document.getElementById('byte-sort')?.value || 'absolute';
    let audits = window.lastByteAudits.filter(item => {
        if (filter === 'increase') return item.delta_bytes > 0;
        if (filter === 'equal') return !item.changed;
        if (filter === 'all') return true;
        return item.changed;
    });
    audits.sort((a, b) => sort === 'file'
        ? `${a.sheet}/${a.file}`.localeCompare(`${b.sheet}/${b.file}`)
        : sort === 'delta' ? b.delta_bytes - a.delta_bytes
        : Math.abs(b.delta_bytes) - Math.abs(a.delta_bytes));
    list.innerHTML = audits.map(item => {
        const delta = `${item.delta_bytes >= 0 ? '+' : ''}${item.delta_bytes} B`;
        const warning = item.warning ? `<span class="byte-warning">⚠ ${escapeHtml(item.warning)}</span>` : '';
        return `<div class="byte-line"><span class="byte-file">${escapeHtml(item.sheet)} / ${escapeHtml(item.file)}</span><span>${item.original_bytes} → ${item.translated_bytes} B</span><span class="byte-delta ${item.changed ? '' : 'equal'}">${delta}</span>${warning}</div>`;
    }).join('') || '<span class="footer-note">Nessun risultato per questo filtro.</span>';
}

function renderCsvAudit(audits) {
    if (!Array.isArray(audits) || !audits.length) return '';
    const changed = audits.filter(item => item.changed && item.delta_bytes > 0);
    const rows = audits.map(item => {
        const delta = item.delta_bytes === null || item.delta_bytes === undefined ? 'n/d' : `${item.delta_bytes >= 0 ? '+' : ''}${item.delta_bytes} B`;
        const warning = item.warning ? `<span class="byte-warning">⚠ ${escapeHtml(item.warning)}</span>` : '';
        return `<div class="byte-line"><span class="byte-file">${escapeHtml(item.sheet || item.file)}</span><span>${item.original_bytes ?? 'n/d'} → ${item.translated_bytes} B</span><span class="byte-delta ${item.changed ? '' : 'equal'}">${delta}</span>${warning}</div>`;
    }).join('');
    return `<div><strong>Controllo preliminare CSV:</strong> ${changed.length} file più grandi · ${audits.length} confrontati</div><div class="operation-log">${rows}</div>`;
}

async function checkStatus() {
    try {
        const data = await (await fetch('/api/status')).json();
        const dot = document.getElementById('sqpack-dot');
        if (dot) dot.className = `pulse-dot ${data.sqpack_ok ? 'ok' : 'error'}`;
        const statusCopy = document.getElementById('status-copy');
        if (statusCopy) statusCopy.textContent = data.sqpack_ok ? 'Installazione pronta' : 'SQPACK non trovato';
        const sqpackState = document.getElementById('sqpack-state');
        if (sqpackState) sqpackState.textContent = data.sqpack_ok ? 'SQPACK riconosciuti' : 'Percorso non trovato';
        const runtimeState = document.getElementById('runtime-state');
        if (runtimeState) runtimeState.textContent = data.runtime_ok ? 'Cartella pronta' : 'Da inizializzare';
        const workspacePath = document.getElementById('workspace-path');
        if (workspacePath) workspacePath.textContent = data.workspace;
        const exdPath = document.getElementById('exd-path');
        if (exdPath) exdPath.textContent = data.exd;
        const storage = data.history || {};
        const warning = document.getElementById('storage-warning');
        if (warning) {
            warning.hidden = !storage.warning;
            warning.textContent = storage.warning
                ? `⚠ Storico voluminoso: ${storage.files || 0} file in ${storage.import_snapshots || 0} importazioni e ${storage.export_snapshots || 0} esportazioni. Valuta di liberare spazio nella cartella del progetto.`
                : '';
        }
    } catch (_) { showToast('Server non raggiungibile.', 'error'); }
}

async function loadCatalog() {
    try {
        const data = await (await fetch('/api/exh_catalog')).json();
        sheets = data.sheets || data.files.map(name => ({name, category: 'EXH'}));
        const categories = [...new Set(sheets.map(sheet => sheet.category))].sort();
        const select = document.getElementById('catalog-category');
        categories.forEach(category => select.add(new Option(category, category)));
        renderCatalog();
        // The catalog and workspace are loaded independently; refresh once
        // the authoritative EXH names are available.
        refreshWorkspaceFiles();
    } catch (_) { showToast('Impossibile caricare il catalogo EXH.', 'error'); }
}

function visibleSheets() {
    const query = document.getElementById('catalog-search').value.toLowerCase().trim();
    const category = document.getElementById('catalog-category').value;
    return sheets.filter(sheet => (!query || sheet.name.includes(query)) &&
        (category === 'all' || sheet.category === category));
}

function renderCatalog() {
    const container = document.getElementById('sheet-list');
    const visible = visibleSheets();
    container.innerHTML = '';
    visible.forEach(sheet => {
        const row = document.createElement('label');
        row.className = 'sheet-row';
        row.innerHTML = `<input type="checkbox" data-sheet="${sheet.name}" ${selectedSheets.has(sheet.name) ? 'checked' : ''}>` +
            `<span class="sheet-name">${sheet.name}</span><span class="sheet-meta">${sheet.category} · ${sheet.pages} pag. · ${sheet.columns} col. · ${sheet.rows} righe</span>`;
        row.querySelector('input').addEventListener('change', event => {
            if (event.target.checked) selectedSheets.add(sheet.name); else selectedSheets.delete(sheet.name);
            updateSummary();
        });
        container.appendChild(row);
    });
    updateSummary();
}

function selectVisibleSheets(value) {
    visibleSheets().forEach(sheet => value ? selectedSheets.add(sheet.name) : selectedSheets.delete(sheet.name));
    renderCatalog();
}

function updateSummary() {
    document.getElementById('catalog-summary').textContent = `${selectedSheets.size} selezionati · ${visibleSheets().length} visibili · ${sheets.length} totali`;
}

async function exportSelected(all) {
    const names = all ? sheets.map(sheet => sheet.name) : [...selectedSheets];
    if (!names.length) return showToast('Seleziona almeno un EXH.', 'error');
    await runBatch('/api/export_batch', names, `Esportazione completata: ${names.length} fogli richiesti.`);
    refreshWorkspaceFiles();
}

async function refreshWorkspaceFiles() {
    try {
        const rawFiles = (await (await fetch('/api/workspace_files')).json()).files || [];
        // Defense in depth: hide legacy/invalid files even if an older
        // backend is still serving the endpoint during a restart.
        const knownSheets = new Set(sheets.map(sheet => sheet.name));
        workspaceFiles = rawFiles.filter(name => {
            const stem = String(name).toLowerCase();
            return /^[a-z0-9_]+$/.test(stem) &&
                !/(?:_original|_tradotti|_wip|_recovered|_backup|\.bak)$/.test(stem) &&
                (!knownSheets.size || knownSheets.has(stem));
        });
        const workspaceState = document.getElementById('workspace-state');
        if (workspaceState) workspaceState.textContent = `${workspaceFiles.length} CSV disponibili`;
        selectedWorkspace = new Set(workspaceFiles.filter(name => selectedWorkspace.has(name)));
        renderWorkspace();
    } catch (_) { showToast('Errore nella lettura del workspace.', 'error'); }
}

function renderWorkspace() {
    const container = document.getElementById('workspace-list');
    container.innerHTML = '';
    workspaceFiles.forEach(name => {
        const row = document.createElement('label'); row.className = 'sheet-row';
        row.innerHTML = `<input type="checkbox" data-workspace="${name}" ${selectedWorkspace.has(name) ? 'checked' : ''}>` +
            `<span class="sheet-name">${name}.csv</span><span class="sheet-meta">nome riconosciuto</span>`;
        row.querySelector('input').addEventListener('change', event => {
            if (event.target.checked) selectedWorkspace.add(name); else selectedWorkspace.delete(name);
            updateWorkspaceSummary();
        });
        container.appendChild(row);
    });
    updateWorkspaceSummary();
}

function updateWorkspaceSummary() {
    document.getElementById('workspace-summary').textContent = `${selectedWorkspace.size} CSV selezionati · ${workspaceFiles.length} disponibili`;
}

function selectVisibleWorkspace(value) {
    selectedWorkspace = value ? new Set(workspaceFiles) : new Set();
    renderWorkspace();
}

async function uploadCsv(input) {
    if (!input.files.length) return;
    const form = new FormData();
    [...input.files].forEach(file => form.append('files', file));
    try {
        const res = await fetch('/api/upload_csv_batch', {method: 'POST', body: form});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Upload fallito');
        if (data.uploaded.length) data.uploaded.forEach(name => selectedWorkspace.add(name));
        showToast(`${data.uploaded.length} CSV caricati${data.errors.length ? `, ${data.errors.length} rifiutati` : ''}.`, data.errors.length ? 'error' : 'success');
        const output = document.getElementById('operation-result');
        if (output && data.byte_audit?.length) { output.hidden = false; output.className = 'operation-result'; output.innerHTML = `<strong>CSV caricati nella cartella di lavoro.</strong><br><span>${escapeHtml(data.history_dir || '')}</span>${renderCsvAudit(data.byte_audit)}`; }
        await refreshWorkspaceFiles();
    } catch (error) { showToast(error.message, 'error'); }
    input.value = '';
}

async function compileSelected() {
    const names = [...selectedWorkspace];
    if (!names.length) return showToast('Seleziona almeno un CSV dal workspace.', 'error');
    await runBatch('/api/compile_batch', names, 'Compilazione completata. Gli EXD sono pronti per l’inject.');
}

async function hardInjectSelected() {
    const names = [...selectedWorkspace];
    if (!names.length) return showToast('Seleziona almeno un CSV dal workspace.', 'error');
    if (!confirm(`Stai per modificare gli SQPACK reali per ${names.length} foglio/i. Continuare?`)) return;
    await runBatch('/api/hard_inject_batch', names, 'Hard-inject completato.');
}

async function runBatch(endpoint, names, successMessage) {
    try {
        const res = await fetch(endpoint, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({exh_names: names})});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Operazione fallita');
        const failed = (data.results || []).filter(item => item.error);
        const output = document.getElementById('operation-result');
        const successful = (data.results || []).filter(item => !item.error);
        const paths = successful.flatMap(item => {
            if (item.file) return [item.file];
            if (item.files && item.files.length) return [describeFiles(item.files)];
            return [];
        });
        if (output) {
            output.hidden = false;
            output.className = `operation-result ${failed.length ? 'has-errors' : ''}`;
            const audit = renderByteAudit(data.results || []);
            output.innerHTML = `<strong>${escapeHtml(successMessage)}</strong><br><span>${paths.length ? paths.join('<br>') : 'Controlla il workspace per i file risultanti.'}</span>${audit}`;
        }
        if (failed.length) showToast(`${successMessage} Errori: ${failed.map(item => item.name).join(', ')}`, 'error');
        else showToast(successMessage);
    } catch (error) { showToast(error.message, 'error'); }
}

async function restoreBackup() {
    if (!confirm('Ripristinare i backup originali di dat0 e index?')) return;
    try {
        const res = await fetch('/api/restore_backup', {method: 'POST'}); const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Ripristino fallito');
        showToast('Backup ripristinato.');
    } catch (error) { showToast(error.message, 'error'); }
}

async function submitIssue(event) {
    event.preventDefault();
    const payload = {
        title: document.getElementById('issue-title').value.trim(),
        category: document.getElementById('issue-category').value,
        contact: document.getElementById('issue-contact').value.trim(),
        description: document.getElementById('issue-description').value.trim()
    };
    try {
        const res = await fetch('/api/issues', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Invio fallito');
        const result = document.getElementById('issue-submit-result');
        result.hidden = false; result.className = 'settings-check valid';
        result.textContent = `Segnalazione #${data.issue.id} ricevuta. Grazie: verrà analizzata dal responsabile del progetto.`;
        document.getElementById('issue-form').reset();
        showToast('Segnalazione inviata.');
    } catch (error) { showToast(error.message, 'error'); }
}

function adminHeaders() {
    const token = document.getElementById('admin-token').value.trim();
    return token ? {'X-Admin-Token': token} : {};
}

function issueStatusLabel(status) {
    return ({open:'Aperto', in_progress:'In lavorazione', resolved:'Risolto', closed:'Chiuso'})[status] || status;
}

async function loadIssues(admin = false) {
    const container = document.getElementById('issues-list');
    try {
        const res = await fetch('/api/issues', {headers: adminHeaders()});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Impossibile caricare le segnalazioni');
        if (!data.issues.length) { container.innerHTML = '<span class="footer-note">Nessuna segnalazione presente.</span>'; return; }
        container.innerHTML = data.issues.map(issue => `<article class="issue-card"><div class="issue-card-head"><div><h4>#${issue.id} · ${escapeHtml(issue.title)}</h4><small>${escapeHtml(issue.category)} · ${escapeHtml(issue.created_at)}</small></div><select class="issue-status" onchange="updateIssueStatus(${issue.id}, this.value)"><option value="open" ${issue.status==='open'?'selected':''}>Aperto</option><option value="in_progress" ${issue.status==='in_progress'?'selected':''}>In lavorazione</option><option value="resolved" ${issue.status==='resolved'?'selected':''}>Risolto</option><option value="closed" ${issue.status==='closed'?'selected':''}>Chiuso</option></select></div><p>${escapeHtml(issue.description)}</p>${issue.contact ? `<small>Contatto: ${escapeHtml(issue.contact)}</small>` : ''}<div>${(issue.replies || []).map(reply => `<p><strong>Risposta:</strong> ${escapeHtml(reply.message)}</p>`).join('')}</div><div class="issue-reply"><input id="reply-${issue.id}" placeholder="Scrivi una risposta"><button class="button secondary" onclick="replyIssue(${issue.id})">Rispondi</button></div></article>`).join('');
    } catch (error) { container.innerHTML = `<span class="footer-note">${escapeHtml(error.message)}</span>`; }
}

async function updateIssueStatus(id, status) {
    try {
        const res = await fetch(`/api/issues/${id}/status`, {method:'PATCH', headers:{...adminHeaders(), 'Content-Type':'application/json'}, body:JSON.stringify({status})});
        const data = await res.json(); if (!res.ok) throw new Error(data.detail || 'Aggiornamento fallito');
        showToast(`Segnalazione #${id}: ${issueStatusLabel(data.issue.status)}.`);
    } catch (error) { showToast(error.message, 'error'); loadIssues(true); }
}

async function replyIssue(id) {
    const input = document.getElementById(`reply-${id}`);
    const message = input.value.trim(); if (!message) return showToast('Scrivi una risposta prima di inviarla.', 'error');
    try {
        const res = await fetch(`/api/issues/${id}/replies`, {method:'POST', headers:{...adminHeaders(), 'Content-Type':'application/json'}, body:JSON.stringify({message})});
        const data = await res.json(); if (!res.ok) throw new Error(data.detail || 'Risposta fallita');
        input.value = ''; showToast('Risposta salvata.'); loadIssues(true);
    } catch (error) { showToast(error.message, 'error'); }
}
