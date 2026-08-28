let sheets = [];
let selectedSheets = new Set();
let workspaceFiles = [];
let selectedWorkspace = new Set();
let glossaryOffset = 0;
const glossaryLimit = 50;
let glossarySearchTimer;
let operationStartedAt = 0;
let operationElapsedTimer = null;
let operationPhaseTimer = null;

document.addEventListener('DOMContentLoaded', () => {
    checkStatus();
    loadCatalog();
    refreshWorkspaceFiles();
    document.getElementById('catalog-search').addEventListener('input', renderCatalog);
    document.getElementById('catalog-category').addEventListener('change', renderCatalog);
    document.getElementById('glossary-search').addEventListener('input', () => {
        clearTimeout(glossarySearchTimer);
        glossarySearchTimer = setTimeout(() => loadGlossary(true), 220);
    });
    document.getElementById('glossary-section').addEventListener('change', () => loadGlossary(true));
    document.getElementById('glossary-status').addEventListener('change', () => loadGlossary(true));
    loadGlossary(true);
    document.addEventListener('click', event => {
        const button = event.target.closest('[data-action]');
        if (!button) return;
        const action = button.dataset.action;
        if (action === 'show-settings') showView('settings');
        else if (action === 'show-home') showView('home');
        else if (action === 'select-visible-sheets') selectVisibleSheets(button.dataset.value === 'true');
        else if (action === 'export-selected') exportSelected(false);
        else if (action === 'export-catalog') exportSelected(true);
        else if (action === 'import-configured') importConfiguredCsvs();
        else if (action === 'select-all-workspace') selectVisibleWorkspace(true);
        else if (action === 'select-no-workspace') selectVisibleWorkspace(false);
        else if (action === 'compile-selected') compileSelected();
        else if (action === 'hard-inject') hardInjectSelected();
        else if (action === 'restore-backup') restoreBackup();
        else if (action === 'publish-selected') publishSelected();
        else if (action === 'save-settings') saveSettings();
        else if (action === 'glossary-refresh') loadGlossary(true);
        else if (action === 'glossary-prev') glossaryPage(-1);
        else if (action === 'glossary-next') glossaryPage(1);
    });
});

function setWorkflowStep(step) {
    document.querySelectorAll('.workflow-step').forEach(item => {
        const value = Number(item.dataset.step);
        item.classList.toggle('done', value < step);
        item.classList.toggle('active', value === step);
    });
}

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
        document.getElementById('settings-sqpack').value = data.sqpack_dir || '';
        document.getElementById('settings-csv').value = data.csv_source_dir || '';
        document.getElementById('settings-workspace').value = data.workspace_dir || '';
        document.getElementById('settings-exd').value = data.exd_dir || '';
        updateSettingsCheck(data);
    } catch (_) { showToast('Impossibile caricare le impostazioni.', 'error'); }
}

function updateSettingsCheck(data) {
    const check = document.getElementById('settings-check');
    if (!check) return;
    const ready = data.sqpack_ok && data.csv_source_ok && data.workspace_ok && data.exd_ok;
    check.className = `settings-check ${ready ? 'valid' : 'invalid'}`;
    check.textContent = ready ? '✓ SQPACK, CSV, workspace ed EXD sono accessibili.' : '! Uno o più percorsi non sono accessibili o scrivibili.';
}

async function saveSettings() {
    const payload = {
        sqpack_dir: document.getElementById('settings-sqpack').value.trim(),
        csv_source_dir: document.getElementById('settings-csv').value.trim(),
        workspace_dir: document.getElementById('settings-workspace').value.trim(),
        exd_dir: document.getElementById('settings-exd').value.trim()
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
    startOperation('Scansione e sincronizzazione', 'Lettura della cartella sorgente e controllo dei nomi CSV...', null, [
        'Lettura della cartella sorgente...',
        'Verifica degli EXH compatibili...',
        'Copia dei CSV validi nel workspace...'
    ]);
    try {
        const res = await fetch('/api/import_csv_folder', {method: 'POST'});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Importazione fallita');
        const summary = `${data.imported.length} CSV importati${data.errors.length ? ` · ${data.errors.length} ignorati` : ''}.`;
        finishOperation(!data.errors.length, 'Scansione completata', summary, data.imported.length, data.errors.length ? 'Completata con avvisi' : 'Completata');
        showToast(summary, data.errors.length ? 'error' : 'success');
        await refreshWorkspaceFiles();
        setWorkflowStep(3);
    } catch (error) {
        finishOperation(false, 'Scansione non completata', error.message, 0, 'Errore');
        showToast(error.message, 'error');
    }
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => { toast.style.animation = 'fadeOut 0.3s ease forwards'; setTimeout(() => toast.remove(), 300); }, 5000);
}

function formatElapsed(seconds) {
    const whole = Math.max(0, Math.floor(seconds));
    const minutes = Math.floor(whole / 60);
    return `${minutes}:${String(whole % 60).padStart(2, '0')}`;
}

function startOperation(title, detail, total = null, phases = []) {
    const monitor = document.getElementById('operation-monitor');
    const result = document.getElementById('operation-result');
    if (!monitor) return;
    if (result) result.hidden = true;
    monitor.hidden = false;
    monitor.className = 'operation-monitor running';
    document.getElementById('operation-monitor-icon').textContent = '◌';
    document.getElementById('operation-monitor-title').textContent = title;
    document.getElementById('operation-monitor-detail').textContent = detail;
    document.getElementById('operation-monitor-state').textContent = 'In corso';
    document.getElementById('operation-monitor-count').textContent = total ? `0 / ${total} elementi · elaborazione sul server` : 'Elaborazione sul server in corso';
    document.getElementById('operation-monitor-elapsed').textContent = '0:00';
    const bar = document.getElementById('operation-progress-bar');
    bar.className = 'operation-progress-bar indeterminate';
    bar.style.width = '';
    setOperationButtonsBusy(true);
    operationStartedAt = Date.now();
    clearInterval(operationElapsedTimer);
    operationElapsedTimer = setInterval(() => {
        const elapsed = document.getElementById('operation-monitor-elapsed');
        if (elapsed) elapsed.textContent = formatElapsed((Date.now() - operationStartedAt) / 1000);
    }, 1000);
    clearInterval(operationPhaseTimer);
    if (phases.length > 1) {
        let phase = 0;
        operationPhaseTimer = setInterval(() => {
            phase = (phase + 1) % phases.length;
            const detailNode = document.getElementById('operation-monitor-detail');
            if (detailNode) detailNode.textContent = phases[phase];
        }, 2600);
    }
}

function finishOperation(success, title, detail, total = null, state = null) {
    const monitor = document.getElementById('operation-monitor');
    if (!monitor) return;
    clearInterval(operationElapsedTimer);
    clearInterval(operationPhaseTimer);
    operationElapsedTimer = null;
    operationPhaseTimer = null;
    monitor.className = `operation-monitor ${success ? 'completed' : 'failed'}`;
    document.getElementById('operation-monitor-icon').textContent = success ? '✓' : '!';
    document.getElementById('operation-monitor-title').textContent = title;
    document.getElementById('operation-monitor-detail').textContent = detail;
    document.getElementById('operation-monitor-state').textContent = state || (success ? 'Completata' : 'Errore');
    document.getElementById('operation-monitor-count').textContent = total ? `${total} / ${total} elementi elaborati` : 'Nessun elemento elaborato';
    document.getElementById('operation-monitor-elapsed').textContent = formatElapsed((Date.now() - operationStartedAt) / 1000);
    const bar = document.getElementById('operation-progress-bar');
    bar.className = 'operation-progress-bar';
    bar.style.width = '100%';
    setOperationButtonsBusy(false);
}

function setOperationButtonsBusy(busy) {
    const actions = new Set(['import-configured', 'export-selected', 'export-catalog', 'compile-selected', 'hard-inject', 'restore-backup', 'publish-selected']);
    document.querySelectorAll('[data-action]').forEach(button => {
        if (actions.has(button.dataset.action)) button.disabled = busy;
    });
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
    const changed = audits.filter(item => item.changed);
    const title = `<div><strong>Controllo byte:</strong> ${changed.length} pagina/e con differenze · ${audits.length} controllate</div>`;
    const rows = audits.map(item => {
        const delta = `${item.delta_bytes >= 0 ? '+' : ''}${item.delta_bytes} B`;
        const warning = item.warning ? `<span class="byte-warning">⚠ ${escapeHtml(item.warning)}</span>` : '';
        return `<div class="byte-line"><span class="byte-file">${escapeHtml(item.sheet)} / ${escapeHtml(item.file)}</span><span>${item.original_bytes} → ${item.translated_bytes} B</span><span class="byte-delta ${item.changed ? '' : 'equal'}">${delta}</span>${warning}</div>`;
    }).join('');
    return `${title}<div class="operation-log">${rows}</div>`;
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
        const sourcePath = document.getElementById('csv-source-path');
        if (sourcePath) sourcePath.textContent = data.csv_source || 'Non configurata';
        const workspacePath = document.getElementById('workspace-path');
        if (workspacePath) workspacePath.textContent = data.workspace;
        const exdPath = document.getElementById('exd-path');
        if (exdPath) exdPath.textContent = data.exd;
        setWorkflowStep(workspaceFiles.length ? 3 : (data.sqpack_ok && data.csv_source_ok && data.workspace_ok ? 2 : 1));
    } catch (_) { showToast('Server non raggiungibile.', 'error'); }
}

async function loadCatalog() {
    startOperation('Scansione catalogo EXH', 'Lettura degli archivi e riconoscimento dei fogli disponibili...', null, [
        'Lettura dell’indice SQPACK...',
        'Riconoscimento dei file EXH...',
        'Organizzazione per categoria...'
    ]);
    try {
        const data = await (await fetch('/api/exh_catalog')).json();
        sheets = data.sheets || data.files.map(name => ({name, category: 'EXH'}));
        const categories = [...new Set(sheets.map(sheet => sheet.category))].sort();
        const select = document.getElementById('catalog-category');
        categories.forEach(category => select.add(new Option(category, category)));
        renderCatalog();
        finishOperation(true, 'Scansione EXH completata', `${sheets.length} fogli riconosciuti e pronti.`, sheets.length, 'Completata');
    } catch (error) {
        finishOperation(false, 'Scansione EXH non completata', error.message || 'Catalogo non disponibile.', 0, 'Errore');
        showToast('Impossibile caricare il catalogo EXH.', 'error');
    }
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

async function loadGlossary(reset = false) {
    if (reset) glossaryOffset = 0;
    const params = new URLSearchParams({
        q: document.getElementById('glossary-search').value.trim(),
        section: document.getElementById('glossary-section').value,
        status: document.getElementById('glossary-status').value,
        limit: glossaryLimit,
        offset: glossaryOffset
    });
    const list = document.getElementById('glossary-list');
    try {
        const response = await fetch(`/api/glossary?${params.toString()}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Dizionario non disponibile');
        const section = document.getElementById('glossary-section');
        const status = document.getElementById('glossary-status');
        const selectedSection = section.value;
        const selectedStatus = status.value;
        section.innerHTML = '<option value="">Tutte</option>' + (data.sections || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
        status.innerHTML = '<option value="">Tutti</option>' + (data.statuses || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join('');
        section.value = selectedSection;
        status.value = selectedStatus;
        document.getElementById('glossary-source').textContent = `${data.source} · aggiornato ${new Date(data.updated_at).toLocaleString('it-IT')}`;
        renderGlossary(data);
    } catch (error) {
        list.innerHTML = `<div class="glossary-empty">${escapeHtml(error.message)}</div>`;
        document.getElementById('glossary-summary').textContent = 'Dizionario non disponibile';
    }
}

function renderGlossary(data) {
    const list = document.getElementById('glossary-list');
    const rows = data.rows || [];
    if (!rows.length) {
        list.innerHTML = '<div class="glossary-empty">Nessuna voce corrisponde alla ricerca.</div>';
    } else {
        list.innerHTML = rows.map(row => {
            const attributes = [row.attributo_1, row.attributo_2].filter(Boolean).map(value => `<span>${escapeHtml(value)}</span>`).join('');
            const note = row.note ? `<p class="glossary-note">${escapeHtml(row.note)}</p>` : '';
            return `<article class="glossary-row"><div class="glossary-terms"><strong>${escapeHtml(row.termine_originale)}</strong><span>→</span><strong class="glossary-italian">${escapeHtml(row.traduzione_italiana)}</strong></div><div class="glossary-meta"><span>${escapeHtml(row.sezione)}</span><span class="glossary-state">${escapeHtml(row.stato || 'senza stato')}</span>${attributes}</div>${note}<small>${escapeHtml(row.id)}</small></article>`;
        }).join('');
    }
    const first = data.matched ? data.offset + 1 : 0;
    const last = Math.min(data.offset + rows.length, data.matched || 0);
    document.getElementById('glossary-summary').textContent = `${first}–${last} di ${data.matched} risultati · ${data.total} voci totali`;
    document.querySelector('[data-action="glossary-prev"]').disabled = data.offset <= 0;
    document.querySelector('[data-action="glossary-next"]').disabled = data.offset + rows.length >= data.matched;
}

function glossaryPage(direction) {
    const matched = Number(document.getElementById('glossary-summary').textContent.match(/di (\d+)/)?.[1] || 0);
    const next = glossaryOffset + direction * glossaryLimit;
    if (next < 0 || next >= matched && direction > 0) return;
    glossaryOffset = next;
    loadGlossary(false);
}

async function exportSelected(all) {
    const names = all ? sheets.map(sheet => sheet.name) : [...selectedSheets];
    if (!names.length) return showToast('Seleziona almeno un EXH.', 'error');
    const ok = await runBatch('/api/export_batch', names, `Esportazione completata: ${names.length} fogli richiesti.`);
    refreshWorkspaceFiles();
    if (ok) setWorkflowStep(3);
}

async function refreshWorkspaceFiles() {
    try {
        workspaceFiles = (await (await fetch('/api/workspace_files')).json()).files || [];
        const workspaceState = document.getElementById('workspace-state');
        if (workspaceState) workspaceState.textContent = `${workspaceFiles.length} CSV disponibili`;
        selectedWorkspace = new Set(workspaceFiles.filter(name => selectedWorkspace.has(name)));
        renderWorkspace();
        if (workspaceFiles.length) setWorkflowStep(3);
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

async function compileSelected() {
    const names = [...selectedWorkspace];
    if (!names.length) return showToast('Seleziona almeno un CSV dal workspace.', 'error');
    const ok = await runBatch('/api/compile_batch', names, 'Compilazione completata. Gli EXD sono pronti per l’inject.');
    if (ok) setWorkflowStep(4);
}

async function hardInjectSelected() {
    const names = [...selectedWorkspace];
    if (!names.length) return showToast('Seleziona almeno un CSV dal workspace.', 'error');
    if (!confirm(`Stai per modificare gli SQPACK reali per ${names.length} foglio/i. Continuare?`)) return;
    const ok = await runBatch('/api/hard_inject_batch', names, 'Hard-inject completato.');
    if (ok) setWorkflowStep(5);
}

async function runBatch(endpoint, names, successMessage) {
    const operationTitles = {
        '/api/export_batch': 'Esportazione EXH',
        '/api/compile_batch': 'Compilazione EXD',
        '/api/hard_inject_batch': 'Applicazione negli SQPACK'
    };
    const operationTitle = operationTitles[endpoint] || 'Operazione';
    startOperation(operationTitle, `Preparazione di ${names.length} elementi...`, names.length, [
        `Preparazione di ${names.length} elementi...`,
        'Elaborazione sul server...',
        'Verifica dei risultati e dei byte...'
    ]);
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
        if (failed.length) {
            finishOperation(false, `${operationTitle} conclusa con errori`, `${failed.length} elemento/i non elaborato/i.`, successful.length, 'Completata con errori');
            showToast(`${successMessage} Errori: ${failed.map(item => item.name).join(', ')}`, 'error');
            return false;
        }
        finishOperation(true, `${operationTitle} completata`, successMessage, names.length, 'Completata');
        showToast(successMessage);
        return true;
    } catch (error) {
        finishOperation(false, `${operationTitle} non completata`, error.message, 0, 'Errore');
        showToast(error.message, 'error');
        return false;
    }
}

async function publishSelected() {
    // Il catalogo interno conserva gli stem per compilazione/inject, mentre
    // l'endpoint di pubblicazione riceve esclusivamente nomi CSV completi.
    const files = [...selectedWorkspace].map(name => name.toLowerCase().endsWith('.csv') ? name : `${name}.csv`);
    const email = document.getElementById('publish-email').value;
    const password = document.getElementById('publish-password').value;
    if (!files.length) return showToast('Seleziona almeno un CSV da pubblicare.', 'error');
    if (!email || !password) return showToast('Inserisci le credenziali amministrative solo per questa pubblicazione.', 'error');
    startOperation('Pubblicazione release', 'Verifica credenziali e preparazione dell’archivio EXD...', files.length, [
        'Verifica delle credenziali amministrative...',
        'Controllo degli EXD compilati e dei checksum...',
        'Trasferimento della release al portale...'
    ]);
    try {
        const res = await fetch('/api/publish_workspace', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({files, version: document.getElementById('publish-version').value, game_patch: document.getElementById('publish-patch').value, admin_email: email, admin_password: password})});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Pubblicazione fallita');
        const summary = `Release pubblicata: pacchetto EXD verificato (${files.length} sheet).`;
        finishOperation(true, 'Pubblicazione completata', summary, files.length, 'Completata');
        showToast(summary, 'success');
        document.getElementById('publish-password').value = '';
        setWorkflowStep(5);
    } catch (error) {
        finishOperation(false, 'Pubblicazione non completata', error.message, 0, 'Errore');
        showToast(error.message, 'error');
    }
}

async function restoreBackup() {
    if (!confirm('Ripristinare i backup originali degli SQPACK?')) return;
    startOperation('Ripristino backup', 'Ripristino controllato dei file SQPACK originali...', 3);
    try {
        const res = await fetch('/api/restore_backup', {method: 'POST'}); const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Ripristino fallito');
        finishOperation(true, 'Ripristino completato', 'I file originali sono stati ripristinati.', 3, 'Completata');
        showToast('Backup ripristinato.');
    } catch (error) {
        finishOperation(false, 'Ripristino non completato', error.message, 0, 'Errore');
        showToast(error.message, 'error');
    }
}
