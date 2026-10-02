// Group the existing controls without replacing nodes or their event listeners.
(() => {
  const root = document.getElementById('dataOperations');
  if (!root) return;
  const groups = {
    academic: { label: 'Academic', description: 'Upload curriculum, validate subject profiles and review programme evidence.', steps: {
      intake: ['Import curriculum', ['curriculumInstitution', 'cheStartYear']],
      validation: ['Validate evidence', ['subjectProfileStatusFilter', 'refreshCurriculumEvidenceReviewsBtn']],
      provenance: ['Programme evidence', ['refreshCurriculumGovernanceBtn']],
      review: ['Review mappings', ['refreshSkillMappingWorkbenchBtn', 'refreshTaxonomyProvenanceBtn']],
    } },
    labour: { label: 'Labour', description: 'Import vacancies, process skills, review matches and view demand.', steps: {
      intake: ['1. Import vacancies', ['adzunaWhat', 'jobAdvertSourceLabel']],
      pipeline: ['2. Process skills', ['adzunaPipelineSources']],
      review: ['3. Review mappings', ['refreshSkillMappingWorkbenchBtn', 'refreshTaxonomyProvenanceBtn']],
      demand: ['4. Generate demand', ['adzunaPipelineSources']],
      recommend: ['5. Recommendations', ['labourRecommendationsCard']],
      trends: ['Labour trends', ['statsStartYear', 'runPipelineBtn', 'pipelineStageCaption']],
    } },
    general: { label: 'General', description: 'Shared imports, quality checks, operational history and source administration.', steps: {
      intake: ['Other imports', ['genericIntakeMode']],
      review: ['Alignment reviews', ['refreshAlignmentLabelQueueBtn', 'previewAssistedLabelsBtn']],
      processing: ['Decision outputs', ['processingCaption']],
      quality: ['Quality & history', ['loadIngestionDataQualityBtn', 'operationalJobRows', 'qualityJobRows', 'qualityCheckCaption', 'reviewSourceCategory']],
      administration: ['Source administration', ['ingestionBlueprintRows', 'addConnectorBtn', 'normaliserRows', 'addSourceBtn', 'connectorOpsCaption', 'failureRows', 'qualityContractRows', 'contractOpsCaption']],
    } },
  };
  const labourCaptions = {
    intake: { text: 'Import the adzuna vacancies and confirm the source label before processing.', prerequisite: 'Register the labour import source and run an intake before continuing.' },
    pipeline: { text: 'Run the skill pipeline to normalise and match skills for the imported postings.', prerequisite: 'Complete step 1 (import vacancies) before processing skills.' },
    review: { text: 'Review the generated skill mappings and approve or reject each decision.', prerequisite: 'Complete step 2 (process skills) before reviewing mappings.' },
    demand: { text: 'Generate labour demand signals and demand evidence from approved mappings only.', prerequisite: 'Approve the reviewed mappings before generating demand.' },
    recommend: { text: 'Open the curriculum recommendations produced from approved labour and curriculum evidence.', prerequisite: 'Generate demand signals before viewing recommendations.' },
    trends: { text: 'Explore labour market trends and statistics for the processed evidence.', prerequisite: 'Generate demand signals before opening labour trends.' },
  };
  const nav = document.createElement('div');
  nav.className = 'ops-navigation';
  nav.innerHTML = '<nav class="ops-areas" aria-label="Data Operations areas"></nav><p class="ops-description"></p><p class="ops-step-caption"></p><nav class="ops-steps" aria-label="Workflow steps"></nav>';
  root.prepend(nav);
  const workspace = document.createElement('div');
  workspace.className = 'ops-workspace';
  nav.after(workspace);
  const cards = new Map();
  for (const group of Object.values(groups)) {
    for (const [, ids] of Object.values(group.steps)) {
      ids.forEach((id) => {
        const el = document.getElementById(id);
        const card = el?.closest('.import-box') || el?.closest('.panel');
        if (card) { cards.set(id, card); workspace.append(card); }
      });
    }
  }
  function labourSignalsReady() {
    const panel = document.getElementById('adzunaTrialOutlookPanel');
    if (!panel) return false;
    const text = (panel.textContent || '').replace(/\s+/g, ' ').trim();
    return text.length > 0 && !/no demand signals|no labour demand|no signals yet/i.test(text);
  }
  const labourStatus = {
    intake: () => Boolean(document.getElementById('adzunaWhat')?.value) || Boolean((document.getElementById('jobAdvertSourceLabel')?.textContent || '').trim()),
    pipeline: () => Boolean((document.getElementById('pipelineStageCaption')?.textContent || '').trim()),
    review: () => labourSignalsReady(),
    demand: () => labourSignalsReady(),
    recommend: () => labourSignalsReady(),
    trends: () => labourSignalsReady(),
  };
  const labourOrder = ['intake', 'pipeline', 'review', 'demand', 'recommend', 'trends'];
  const recommendationsCard = document.createElement('div');
  recommendationsCard.className = 'panel ops-recommend-card';
  recommendationsCard.hidden = true;
  recommendationsCard.innerHTML = `
    <h3 class="panel-title">Curriculum recommendations</h3>
    <p class="ops-card-caption">Demand-gap and curriculum-coverage recommendations generated from approved labour evidence and curriculum mappings. Each recommendation is pending human review before it affects curriculum decisions.</p>
    <p class="ops-actions">
      <a class="btn primary" href="recommendations.html?view=recommendations">Open Recommendations</a>
      <a class="btn" href="dashboard.html?view=forecast">Demand outlook</a>
    </p>`;
  cards.set('labourRecommendationsCard', recommendationsCard);
  workspace.append(recommendationsCard);
  // Keep all remaining operational controls reachable under General administration.
  const overview = root.querySelector(':scope > .metrics');
  if (overview) { cards.set('overview', overview); workspace.append(overview); groups.general.steps.quality[1].unshift('overview'); }
  const remaining = [...root.querySelectorAll(':scope > .grid > .panel')];
  remaining.forEach((card, i) => {
    if (!card.querySelector('input, button, table') || card.querySelector('.import-grid')) return;
    const key = `remaining-${i}`;
    cards.set(key, card); workspace.append(card);
    groups.general.steps.administration[1].push(key);
  });
  [...root.children].forEach((el) => { if (el !== nav && el !== workspace) el.classList.add('ops-legacy-container'); });
  const areaNav = nav.querySelector('.ops-areas');
  Object.entries(groups).forEach(([key, group]) => {
    const button = document.createElement('button'); button.type = 'button';
    button.textContent = group.label; button.dataset.area = key;
    button.addEventListener('click', () => open(key)); areaNav.append(button);
  });
  function open(area, step, updateUrl = true) {
    if (!groups[area]) area = 'academic';
    const group = groups[area];
    if (!group.steps[step]) step = Object.keys(group.steps)[0];
    nav.querySelector('.ops-description').textContent = group.description;
    const captionEl = nav.querySelector('.ops-step-caption');
    captionEl.textContent = area === 'labour' && labourCaptions[step] ? `${labourCaptions[step].text} Prerequisite: ${labourCaptions[step].prerequisite}` : '';
    areaNav.querySelectorAll('button').forEach((b) => b.setAttribute('aria-current', b.dataset.area === area ? 'page' : 'false'));
    const stepNav = nav.querySelector('.ops-steps'); stepNav.replaceChildren();
    Object.entries(group.steps).forEach(([key, [label]]) => {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = label;
      button.setAttribute('aria-current', key === step ? 'step' : 'false');
      // Navigation stays available so users can inspect prerequisites. The
      // operation controls and API enforce readiness; DOM captions are not proof
      // of completed work (the demand panel is absent on this page).
      if (area === 'labour' && labourCaptions[key]) button.title = labourCaptions[key].prerequisite;
      button.addEventListener('click', () => open(area, key)); stepNav.append(button);
    });
    const visible = new Set(group.steps[step][1].map((id) => cards.get(id)).filter(Boolean));
    new Set(cards.values()).forEach((card) => { card.hidden = !visible.has(card); });
    if (area === 'labour' && step === 'demand') {
      demandLink.hidden = false;
    } else demandLink.hidden = true;
    if (updateUrl) {
      const url = new URL(location.href); url.searchParams.set('area', area); url.searchParams.set('step', step);
      history.replaceState(null, '', url);
    }
    if (updateUrl) nav.scrollIntoView({block: 'start'});
  }
  const demandLink = document.createElement('a'); demandLink.className = 'btn primary ops-outlook-link';
  demandLink.href = 'dashboard.html?view=forecast'; demandLink.textContent = 'View Demand Outlook';
  workspace.append(demandLink);
  window.openDataOperationsSection = open;
  window.addEventListener('labour-signals-updated', () => open(currentArea(), currentStep(), false));
  function currentArea() { return new URLSearchParams(location.search).get('area') || 'academic'; }
  function currentStep() { return new URLSearchParams(location.search).get('step') || Object.keys(groups[currentArea()]?.steps || {})[0]; }
  const restore = () => { const p = new URLSearchParams(location.search); open(p.get('area') || 'academic', p.get('step'), false); };
  window.addEventListener('popstate', restore); restore();
})();
