import { postJson, getJson } from './dashboard-state.js?v=20260912d';
import { CONFIG } from './config.js?v=20260825b';

const base = `${CONFIG.API_BASE_URL}/ingestion/adzuna`;
const status = document.getElementById('adzunaStatus');
const posts = document.getElementById('adzunaPosts');
const estimate = document.getElementById('adzunaEstimate');
const safeModeRow = document.getElementById('adzunaSafeModeRow');
const safeCount = document.getElementById('adzunaSafeCount');
const safeConfirm = document.getElementById('adzunaSafeConfirm');

const SAFE_BATCH_PAGES = 10;

function readRequest() {
  return {
    what: document.getElementById('adzunaWhat').value.trim(),
    where: document.getElementById('adzunaWhere').value.trim(),
    page_size: Number(document.getElementById('adzunaPageSize').value),
    page_start: Number(document.getElementById('adzunaPageStart').value),
    page_end: Number(document.getElementById('adzunaPageEnd').value) || null,
    date_from: document.getElementById('adzunaDateFrom').value || null,
    date_to: document.getElementById('adzunaDateTo').value || null,
  };
}

function formatEstimate(estimateResult) {
  const bounds = `${estimateResult.page_start}–${estimateResult.page_end}`;
  const wallTime = estimateResult.wall_time_estimate_seconds < 120
    ? `~${estimateResult.wall_time_estimate_seconds}s`
    : `~${Math.round(estimateResult.wall_time_estimate_seconds / 60)}min`;
  const filter = estimateResult.date_from || estimateResult.date_to
    ? `, filtered to ${estimateResult.date_from || 'any'} → ${estimateResult.date_to || 'any'}`
    : '';
  return `Preview: pages ${bounds} (${estimateResult.pages} requests) × page size ${estimateResult.page_size} (max ${estimateResult.max_records_upper_bound} postings)${filter}, sort ${estimateResult.sort_by}/${estimateResult.sort_direction}, rate ${estimateResult.rate_limit.requests_per_minute}/min → ${wallTime}. Server page cap: ${estimateResult.server_page_cap}.`;
}

function applySafeMode(pages) {
  const large = pages > SAFE_BATCH_PAGES;
  safeModeRow.style.display = large ? 'flex' : 'none';
  safeCount.textContent = String(pages);
  if (large) {
    safeConfirm.checked = false;
    document.getElementById('adzunaImportPagesBtn').disabled = true;
  }
}

async function showPosts(jobId = '', offset = 0) {
  const query = new URLSearchParams({limit: '50', offset: String(offset)});
  if (jobId) query.set('job_id', jobId);
  const result = await getJson(`${base}/posts?${query}`, null);
  if (!result) throw new Error('Could not load Adzuna posts.');
  posts.replaceChildren();
  const navigation = document.createElement('div'); navigation.className = 'ops-post-navigation';
  const caption = document.createElement('span');
  caption.textContent = result.total ? `Saved postings ${offset + 1}–${offset + result.items.length} of ${result.total}` : 'No saved postings for this selection.';
  const previous = document.createElement('button'); previous.className = 'btn'; previous.textContent = 'Previous saved posts'; previous.disabled = offset === 0;
  const next = document.createElement('button'); next.className = 'btn'; next.textContent = 'Next saved posts'; next.disabled = !result.has_more;
  const loadPage = (start) => showPosts(jobId, start).catch((error) => { status.textContent = error.message; });
  previous.addEventListener('click', () => loadPage(Math.max(0, offset - 50)));
  next.addEventListener('click', () => loadPage(offset + 50));
  navigation.append(caption, previous, next); posts.append(navigation);
  for (const row of result.items) {
    const card = document.createElement('article');
    card.style.cssText = 'padding:16px;border-bottom:1px solid #dbe3ef';
    const title = document.createElement('h4'); title.textContent = row.title;
    const details = document.createElement('p'); details.textContent = `${row.location} | Posted ${String(row.posted_date).slice(0,10)} | ${row.job_id}`;
    const description = document.createElement('p'); description.textContent = row.description || 'No description supplied.';
    const link = document.createElement('a');
    try { const url = new URL(row.url); if (url.protocol === 'https:') link.href = url.href; } catch {}
    link.textContent = 'View vacancy on Adzuna'; link.target = '_blank'; link.rel = 'noopener noreferrer';
    card.append(title, details, description, link); posts.append(card);
  }
  return result.total ?? result.items.length;
}

document.getElementById('adzunaEstimateBtn').addEventListener('click', async (event) => {
  const button = event.currentTarget; button.disabled = true;
  try {
    const result = await postJson(`${base}/pages/estimate`, readRequest());
    estimate.textContent = formatEstimate(result);
    applySafeMode(result.pages);
  } catch (error) { estimate.textContent = `Could not preview: ${error.message}`; }
  finally { button.disabled = false; }
});

safeConfirm.addEventListener('change', () => {
  document.getElementById('adzunaImportPagesBtn').disabled = !safeConfirm.checked;
});

document.getElementById('adzunaImportPagesBtn').addEventListener('click', async (event) => {
  const button = event.currentTarget; button.disabled = true;
  const request = readRequest();
  const pages = (request.page_end ?? request.page_start + 9) - request.page_start + 1;
  if (pages > SAFE_BATCH_PAGES && !safeConfirm.checked) {
    applySafeMode(pages);
    status.textContent = 'Confirm the request count above before running this many-page import.';
    button.disabled = false;
    return;
  }
  status.textContent = `Importing pages ${request.page_start}–${request.page_end ?? request.page_start + 9} from Adzuna…`;
  estimate.textContent = '';
  try {
    const result = await postJson(`${base}/import-pages`, request);
    const stoppedBy = result.stop_reason === 'empty_page'
      ? 'stopped at an empty page'
      : result.stop_reason === 'aborted_after_consecutive_failures'
        ? 'stopped after consecutive failures'
        : 'reached the configured page limit';
    status.textContent = `Import done (${stoppedBy}): pages requested ${result.pages_requested}, succeeded ${result.pages_succeeded}, empty ${result.pages_empty}, failed ${result.pages_failed}; postings received ${result.records_returned}, inserted ${result.inserted}, already present (not overwritten) ${result.duplicate}, date-filtered ${result.records_date_filtered}, failed ${result.failed}. Ingestion job: ${result.job_id}`;
    await showPosts(result.job_id);
  } catch (error) { status.textContent = `Import failed: ${error.message}`; }
  finally { safeModeRow.style.display = 'none'; button.disabled = false; }
});

document.getElementById('adzunaShowBtn').addEventListener('click', async () => {
  try { const count = await showPosts(); status.textContent = `${count} saved Adzuna posts available. Browse them 50 at a time below.`; }
  catch (error) { status.textContent = error.message; }
});

document.getElementById('adzunaClearBtn').addEventListener('click', () => {
  status.textContent = '';
  estimate.textContent = '';
  posts.replaceChildren();
  safeModeRow.style.display = 'none';
  safeConfirm.checked = false;
  document.getElementById('adzunaImportPagesBtn').disabled = false;
});
