let currentArticleUrl = '';
  let currentMarkdownUrl = '';
  let currentTitle = '';

  // Theme Management Controller
  let currentThemeSetting = localStorage.getItem('articlegen_theme') || 'system';

  function applyTheme(theme) {
    currentThemeSetting = theme;
    if (theme === 'system') {
      localStorage.removeItem('articlegen_theme');
      document.documentElement.removeAttribute('data-theme');
    } else {
      localStorage.setItem('articlegen_theme', theme);
      document.documentElement.setAttribute('data-theme', theme);
    }
    updateThemeIcon();
    syncThemeToIframe();
  }

  function cycleTheme() {
    if (currentThemeSetting === 'system') {
      applyTheme('light');
    } else if (currentThemeSetting === 'light') {
      applyTheme('dark');
    } else {
      applyTheme('system');
    }
  }

  function updateThemeIcon() {
    const iconEl = document.getElementById('themeToggleIcon');
    const btnEl = document.getElementById('themeToggleBtn');
    if (!iconEl) return;

    if (currentThemeSetting === 'light') {
      iconEl.textContent = '☀️';
      if (btnEl) btnEl.title = 'Theme: Light (Click to switch to Dark)';
    } else if (currentThemeSetting === 'dark') {
      iconEl.textContent = '🌙';
      if (btnEl) btnEl.title = 'Theme: Dark (Click to switch to System)';
    } else {
      const isSysDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      iconEl.textContent = isSysDark ? '🌓' : '☀️';
      if (btnEl) btnEl.title = 'Theme: System (Click to switch to Light)';
    }
  }

  function syncThemeToIframe() {
    const iframe = document.getElementById('articleIframe');
    if (!iframe) return;
    try {
      const doc = iframe.contentDocument || iframe.contentWindow.document;
      if (doc && doc.documentElement) {
        if (currentThemeSetting === 'system') {
          doc.documentElement.removeAttribute('data-theme');
        } else {
          doc.documentElement.setAttribute('data-theme', currentThemeSetting);
        }
      }
    } catch (e) {}
  }

  let isEditingInPlace = false;

  function toggleInPlaceEdit() {
    const iframe = document.getElementById('articleIframe');
    if (!iframe) return;
    try {
      const doc = iframe.contentDocument || iframe.contentWindow.document;
      if (!doc || !doc.body) return;

      isEditingInPlace = !isEditingInPlace;
      doc.body.contentEditable = isEditingInPlace ? "true" : "false";

      const btnText = document.getElementById('editToggleText');
      if (btnText) btnText.innerText = isEditingInPlace ? "Done Editing" : "Edit Text";

      if (isEditingInPlace) {
        showToast("✏️ Direct edit mode enabled — click any text in article to edit!");
      } else {
        showToast("✓ Text edits saved to local article preview.");
        const htmlContent = doc.documentElement.outerHTML;
        if (typeof saveLocalDraft === 'function') saveLocalDraft(currentTitle || 'Edited Article', htmlContent);
        const hash = encodeArticleToHash(htmlContent);
        if (hash) window.location.hash = hash;
      }
    } catch(e) {
      alert("Editing error: " + e.message);
    }
  }

  function quickRefine(promptText) {
    const input = document.getElementById('aiRefineInput');
    if (input) {
      input.value = promptText;
      refineArticleWithAI();
    }
  }

  async function refineArticleWithAI() {
    const input = document.getElementById('aiRefineInput');
    const instruction = input?.value.trim();
    if (!instruction) {
      showToast("Please enter a refinement prompt first.");
      return;
    }

    const iframe = document.getElementById('articleIframe');
    if (!iframe) return;

    const btn = document.getElementById('aiRefineBtn');
    const origText = btn.innerText;
    btn.innerText = "⏳ Refining...";
    btn.disabled = true;

    try {
      const doc = iframe.contentDocument || iframe.contentWindow.document;
      const currentHtml = doc.body.innerHTML;

      const key = localStorage.getItem('articlegen_key') || '';
      const prompt = `Current Article Body HTML:\n${currentHtml}\n\nUser Refinement Request:\n"${instruction}"\n\nReturn the revised body HTML for the article maintaining the same structural tags (h1, h2, p, blockquote, aside).`;
      const sys = "You are a professional science editor revising an article based on user feedback. Return a JSON object with key 'revised_html' containing the refined HTML body markup.";

      const schema = {
        type: "OBJECT",
        properties: {
          revised_html: { type: "STRING" }
        },
        required: ["revised_html"]
      };

      showToast("✨ Asking AI to refine article...");
      const res = await callGroqAPI(prompt, schema, sys, key);
      if (res.revised_html) {
        doc.body.innerHTML = res.revised_html;
        syncThemeToIframe();
        if (input) input.value = '';
        showToast("✨ Article successfully refined with AI!");
        const updatedFullHtml = doc.documentElement.outerHTML;
        if (typeof saveLocalDraft === 'function') saveLocalDraft(currentTitle || 'Refined Article', updatedFullHtml);
        const hash = encodeArticleToHash(updatedFullHtml);
        if (hash) window.location.hash = hash;
      }
    } catch(err) {
      alert("AI Refinement Error: " + err.message);
    } finally {
      btn.innerText = origText;
      btn.disabled = false;
    }
  }

  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
      if (currentThemeSetting === 'system') {
        updateThemeIcon();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function() {
    updateThemeIcon();
    const iframe = document.getElementById('articleIframe');
    if (iframe) {
      iframe.addEventListener('load', syncThemeToIframe);
    }
  });

  function showView(viewId) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.getElementById(viewId).classList.add('active');
    const sticky = document.getElementById('stickyBar');
    if (viewId === 'readerView') {
      sticky.style.display = 'flex';
    } else {
      sticky.style.display = 'none';
    }
  }



  function openModal(id) {
    document.getElementById(id).classList.add('active');
    if (id === 'settingsModal') {
      document.getElementById('apiKeyInput').value = localStorage.getItem('articlegen_key') || '';
      if (document.getElementById('ghTokenInput')) document.getElementById('ghTokenInput').value = localStorage.getItem('articlegen_gh_token') || '';
      if (document.getElementById('gistIdInput')) document.getElementById('gistIdInput').value = localStorage.getItem('articlegen_gist_id') || '';
    }
  }

  function closeModal(id) {
    document.getElementById(id).classList.remove('active');
  }

  function saveApiKey() {
    const k = document.getElementById('apiKeyInput')?.value.trim() || '';
    const ghTok = document.getElementById('ghTokenInput')?.value.trim() || '';
    const gistId = document.getElementById('gistIdInput')?.value.trim() || '';

    if (k) localStorage.setItem('articlegen_key', k);
    else localStorage.removeItem('articlegen_key');

    if (ghTok) localStorage.setItem('articlegen_gh_token', ghTok);
    else localStorage.removeItem('articlegen_gh_token');

    if (gistId) localStorage.setItem('articlegen_gist_id', gistId);
    else localStorage.removeItem('articlegen_gist_id');

    if (typeof savePreferences === 'function') savePreferences();

    showToast('Settings saved!');
    closeModal('settingsModal');

    if (ghTok) {
      syncPushToGist();
    }
  }

  function obfuscateApiKey(key) {
    if (!key) return '';
    try {
      const reversed = key.split('').reverse().join('');
      return 'enc_v1:' + btoa(encodeURIComponent(reversed));
    } catch(e) {
      return key;
    }
  }

  function deobfuscateApiKey(str) {
    if (!str) return '';
    if (str.startsWith('enc_v1:')) {
      try {
        const raw = decodeURIComponent(atob(str.replace('enc_v1:', '')));
        return raw.split('').reverse().join('');
      } catch(e) {
        return str;
      }
    }
    return str;
  }

  async function syncPushToGist() {
    if (typeof savePreferences === 'function') savePreferences();

    const inputApiKey = document.getElementById('apiKeyInput')?.value.trim();
    if (inputApiKey !== undefined && inputApiKey !== '') {
      localStorage.setItem('articlegen_key', inputApiKey);
    }

    const token = document.getElementById('ghTokenInput')?.value.trim() || localStorage.getItem('articlegen_gh_token') || '';
    if (!token) {
      alert("Please enter a GitHub Personal Access Token first.");
      return;
    }
    localStorage.setItem('articlegen_gh_token', token);

    let gistId = document.getElementById('gistIdInput')?.value.trim() || localStorage.getItem('articlegen_gist_id') || '';

    const apiKey = localStorage.getItem('articlegen_key') || '';
    const prefs = localStorage.getItem('articlegen_prefs') || '{}';
    const publishedLib = localStorage.getItem('articlegen_published_library') || '[]';

    const payload = {
      description: "ArticleGen Cross-Device Settings & Published Articles Sync",
      public: false,
      files: {
        "articlegen-settings.json": {
          content: JSON.stringify({
            apiKey: obfuscateApiKey(apiKey),
            preferences: JSON.parse(prefs),
            publishedLibrary: JSON.parse(publishedLib),
            updatedAt: new Date().toISOString()
          }, null, 2)
        }
      }
    };

    try {
      showToast("Syncing to Cloud...");
      let res;
      if (gistId) {
        res = await fetch(`https://api.github.com/gists/${gistId}`, {
          method: 'PATCH',
          headers: {
            'Authorization': `token ${token}`,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });
      } else {
        res = await fetch(`https://api.github.com/gists`, {
          method: 'POST',
          headers: {
            'Authorization': `token ${token}`,
            'Accept': 'application/vnd.github.v3+json',
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });
      }

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`GitHub API Error (${res.status}): ${err}`);
      }

      const data = await res.json();
      gistId = data.id;
      localStorage.setItem('articlegen_gh_token', token);
      localStorage.setItem('articlegen_gist_id', gistId);
      if (document.getElementById('gistIdInput')) document.getElementById('gistIdInput').value = gistId;

      showToast("☁️ Settings pushed to Cloud!");
    } catch (e) {
      alert("Cloud Push Error: " + e.message);
    }
  }

  async function syncPullFromGist() {
    const token = document.getElementById('ghTokenInput')?.value.trim() || localStorage.getItem('articlegen_gh_token') || '';
    let gistId = document.getElementById('gistIdInput')?.value.trim() || localStorage.getItem('articlegen_gist_id');

    if (!gistId) {
      alert("Please enter a Sync Gist ID to pull settings from.");
      return;
    }

    try {
      showToast("Pulling from Cloud...");
      const headers = { 'Accept': 'application/vnd.github.v3+json' };
      if (token) headers['Authorization'] = `token ${token}`;

      const res = await fetch(`https://api.github.com/gists/${gistId}`, { headers });
      if (!res.ok) {
        throw new Error(`Failed to fetch Gist (${res.status}). Verify your Gist ID.`);
      }

      const data = await res.json();
      const file = data.files?.['articlegen-settings.json'];
      if (!file || !file.content) {
        throw new Error("Invalid Gist content: missing articlegen-settings.json");
      }

      const config = JSON.parse(file.content);

      if (config.apiKey) {
        const realKey = deobfuscateApiKey(config.apiKey);
        localStorage.setItem('articlegen_key', realKey);
        if (document.getElementById('apiKeyInput')) document.getElementById('apiKeyInput').value = realKey;
      }
      if (config.preferences) {
        localStorage.setItem('articlegen_prefs', JSON.stringify(config.preferences));
        if (typeof loadPreferences === 'function') loadPreferences();
      }
      if (config.publishedLibrary) {
        localStorage.setItem('articlegen_published_library', JSON.stringify(config.publishedLibrary));
        if (typeof loadPublishedLibrary === 'function') loadPublishedLibrary();
      }

      if (token) localStorage.setItem('articlegen_gh_token', token);
      localStorage.setItem('articlegen_gist_id', gistId);
      if (document.getElementById('gistIdInput')) document.getElementById('gistIdInput').value = gistId;

      showToast("☁️ Settings restored from Cloud!");
    } catch (e) {
      alert("Cloud Pull Error: " + e.message);
    }
  }

  function showToast(msg) {
    const t = document.getElementById('toast');
    if (!t) return;
    t.innerText = msg;
    t.classList.add('active');
    setTimeout(() => t.classList.remove('active'), 2500);
  }

  async function callGroqAPI(prompt, schema, systemInstruction, apiKey) {
    const key = apiKey || localStorage.getItem('articlegen_key') || '';
    if (!key) {
      openModal('settingsModal');
      throw new Error('Please enter your free Groq API Key in the Settings (⚙️) menu to generate articles.');
    }

    const url = "https://api.groq.com/openai/v1/chat/completions";

    const schemaString = JSON.stringify(schema, null, 2)
      .replace(/"OBJECT"/g, '"object"')
      .replace(/"STRING"/g, '"string"')
      .replace(/"ARRAY"/g, '"array"')
      .replace(/"INTEGER"/g, '"integer"');
    const finalSystemInstruction = (systemInstruction || '') + `\n\nYou MUST respond in valid JSON format. Your entire response must be a single JSON object matching this schema exactly:\n${schemaString}\nOutput ONLY raw JSON. Do not include markdown formatting or explanations.`;

    const payload = {
      model: "llama-3.3-70b-versatile",
      messages: [
        { role: "system", content: finalSystemInstruction },
        { role: "user", content: prompt }
      ],
      response_format: { type: "json_object" }
    };

    const res = await fetch(url, {
      method: "POST",
      headers: { 
        "Content-Type": "application/json",
        "Authorization": `Bearer ${key}`
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`Groq API Error (${res.status}): ${errText}`);
    }

    const data = await res.json();
    let raw = data.choices?.[0]?.message?.content;
    if (!raw) throw new Error("Groq returned an empty response.");
    
    raw = raw.replace(/^```json/mi, '').replace(/```$/m, '').trim();
    return JSON.parse(raw);
  }

  async function searchOpenAlex(query) {
    const url = `https://api.openalex.org/works?search=${encodeURIComponent(query)}&filter=has_abstract:true&per-page=10&select=id,title,publication_year,authorships,primary_location,cited_by_count,abstract_inverted_index,doi`;
    try {
      const res = await fetch(url);
      if (!res.ok) return [];
      const data = await res.json();
      return (data.results || []).map(item => {
        let abstract = "";
        if (item.abstract_inverted_index) {
          const pos = {};
          for (const [word, idxs] of Object.entries(item.abstract_inverted_index)) {
            for (const i of idxs) pos[i] = word;
          }
          abstract = Object.keys(pos).sort((a,b)=>a-b).map(i=>pos[i]).join(" ");
        }
        const authors = (item.authorships || []).map(a => a.author?.display_name || "").filter(Boolean);
        const loc = item.primary_location || {};
        const doi = item.doi || "";
        return {
          title: item.title || "",
          abstract: abstract,
          year: item.publication_year,
          authors: authors,
          authorLine: authors.length > 3 ? `${authors[0]} et al.` : (authors.join(", ") || "Unknown authors"),
          venue: loc.source?.display_name || "",
          citationCount: item.cited_by_count || 0,
          doi: doi,
          link: doi ? (doi.startsWith("http") ? doi : `https://doi.org/${doi}`) : (loc.landing_page_url || item.id || "")
        };
      }).filter(p => p.abstract && p.title);
    } catch(e) {
      console.warn("OpenAlex error:", e);
      return [];
    }
  }

  function togglePreferences() {
    const c = document.getElementById('prefContainer');
    const icon = document.getElementById('prefToggleIcon');
    if (!c) return;
    if (c.style.display === 'none') {
      c.style.display = 'block';
      icon.innerText = '▲';
    } else {
      c.style.display = 'none';
      icon.innerText = '▼';
    }
  }

  function savePreferences() {
    const prefs = {
      length: document.getElementById('prefLength')?.value || 'standard',
      tone: document.getElementById('prefTone')?.value || 'journalism',
      depth: document.getElementById('prefDepth')?.value || 'balanced',
      lang: document.getElementById('prefLang')?.value || 'English'
    };
    localStorage.setItem('articlegen_prefs', JSON.stringify(prefs));
  }

  function loadPreferences() {
    try {
      const raw = localStorage.getItem('articlegen_prefs');
      if (raw) {
        const prefs = JSON.parse(raw);
        if (prefs.length && document.getElementById('prefLength')) document.getElementById('prefLength').value = prefs.length;
        if (prefs.tone && document.getElementById('prefTone')) document.getElementById('prefTone').value = prefs.tone;
        if (prefs.depth && document.getElementById('prefDepth')) document.getElementById('prefDepth').value = prefs.depth;
        if (prefs.lang && document.getElementById('prefLang')) document.getElementById('prefLang').value = prefs.lang;
      }
    } catch(e) {}
  }

  function getPreferences() {
    const lenVal = document.getElementById('prefLength')?.value || 'standard';
    const toneVal = document.getElementById('prefTone')?.value || 'journalism';
    const depthVal = document.getElementById('prefDepth')?.value || 'balanced';
    const langVal = document.getElementById('prefLang')?.value || 'English';

    const lenMap = {
      brief: 'Quick Read (~500 words, 2 concise sections)',
      standard: 'Standard Article (~1,000 words, 3-4 detailed sections)',
      deep: 'In-Depth Longform (~1,800+ words, 5+ extensive sections with deep analysis)'
    };
    const toneMap = {
      journalism: 'Engaging Science Journalism (Wired/Quanta style)',
      academic: 'Formal Academic & Technical (Rigorous, precise terminology)',
      executive: 'Executive Briefing (Strategic impact, key takeaways)',
      eli5: 'ELI5 / Beginner Friendly (Simple analogies, highly accessible)'
    };
    const depthMap = {
      balanced: 'Balanced Overview of findings',
      empirical: 'Strict Empirical Focus (Emphasize methodology, sample sizes, and study limitations)',
      narrative: 'Narrative Driven (Focus on storytelling and key conceptual breakthroughs)'
    };

    return {
      lengthLabel: lenMap[lenVal] || lenMap.standard,
      toneLabel: toneMap[toneVal] || toneMap.journalism,
      depthLabel: depthMap[depthVal] || depthMap.balanced,
      lang: langVal
    };
  }

  let cachedShareUrl = '';

  function encodeArticleToHash(html) {
    try {
      const base64 = btoa(encodeURIComponent(html).replace(/%([0-9A-F]{2})/g, (match, p1) => String.fromCharCode('0x' + p1)));
      return '#read=' + encodeURIComponent(base64);
    } catch (e) {
      return '';
    }
  }

  function decodeArticleFromHash(hashStr) {
    try {
      const rawBase64 = decodeURIComponent(hashStr.replace('#read=', ''));
      const html = decodeURIComponent(Array.from(atob(rawBase64)).map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join(''));
      return html;
    } catch (e) {
      return null;
    }
  }

  async function checkUrlHashForArticle() {
    const hash = window.location.hash;
    if (!hash) return;

    if (hash.startsWith('#p=')) {
      const pasteId = hash.replace('#p=', '');
      try {
        const res = await fetch(`https://dpaste.com/${pasteId}.txt`);
        if (res.ok) {
          const html = await res.text();
          document.getElementById('articleIframe').srcdoc = html;
          document.getElementById('articleMeta').innerText = 'Shared Article';
          showView('readerView');
        }
      } catch (e) {
        console.warn("Error loading shared article:", e);
      }
    } else if (hash.startsWith('#read=')) {
      const html = decodeArticleFromHash(hash);
      if (html) {
        document.getElementById('articleIframe').srcdoc = html;
        document.getElementById('articleMeta').innerText = 'Shared Article';
        showView('readerView');
      }
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    loadPreferences();
    checkUrlHashForArticle();
  });

  async function requestIdeas() {
    const theme = document.getElementById('themeInput').value.trim();
    if (!theme) {
      showToast('Please type a theme first.');
      return;
    }

    const guidance = document.getElementById('styleInput').value.trim();
    const btn = document.getElementById('ideasBtn');
    btn.disabled = true;
    btn.innerHTML = '⏳ Generating Ideas...';

    const key = localStorage.getItem('articlegen_key') || '';

    try {
      const resp = await fetch('/api/ideas', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme, guidance, key, n: 6 })
      });
      if (resp.ok) {
        const data = await resp.json();
        renderDraftCards(data.theme, data.ideas || []);
        showView('ideasView');
        return;
      }
    } catch (e) {}

    try {
      const schema = {
        type: "OBJECT",
        properties: {
          ideas: {
            type: "ARRAY",
            items: {
              type: "OBJECT",
              properties: {
                title: { type: "STRING" },
                angle: { type: "STRING" },
                search_terms: { type: "ARRAY", items: { type: "STRING" } }
              },
              required: ["title", "angle", "search_terms"]
            }
          }
        },
        required: ["ideas"]
      };

      const prefs = getPreferences();
      const styleCombined = [guidance, `Tone: ${prefs.toneLabel}`, `Language: ${prefs.lang}`].filter(Boolean).join('. ');
      const prompt = `Theme: "${theme}"\nGuidance: "${styleCombined}"\nPropose 6 distinct article ideas grounded in peer-reviewed science/tech literature. Return all titles, angles, and search terms in ${prefs.lang}.`;
      const sys = `You are an editor for a popular science publication proposing article ideas. Write all response text in ${prefs.lang}.`;
      const res = await callGroqAPI(prompt, schema, sys, key);
      renderDraftCards(theme, res.ideas || []);
      showView('ideasView');
    } catch (err) {
      alert(err.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> Generate Article Drafts';
    }
  }

  function renderDraftCards(theme, ideas) {
    document.getElementById('themeLabel').innerText = 'Theme: ' + theme;
    const container = document.getElementById('draftsList');
    container.innerHTML = '';

    ideas.forEach((idea, idx) => {
      const card = document.createElement('div');
      card.className = 'draft-card';
      const termsHtml = (idea.search_terms || []).map(t => `<span class="draft-term">${t}</span>`).join(' ');

      card.innerHTML = `
        <span class="draft-num">Idea #${idx + 1}</span>
        <h3 class="draft-title">${escapeHtml(idea.title)}</h3>
        <p class="draft-angle">${escapeHtml(idea.angle)}</p>
        <div class="draft-terms">${termsHtml}</div>
        <button class="btn-select" onclick="selectDraft(${JSON.stringify(idea.title).replace(/"/g, '&quot;')})">
          Generate Full Article →
        </button>
      `;
      container.appendChild(card);
    });
  }

  async function selectDraft(title) {
    currentTitle = title;
    document.getElementById('progressTitle').innerText = title;
    showView('progressView');

    const style = document.getElementById('styleInput').value.trim();
    const key = localStorage.getItem('articlegen_key') || '';

    const stepText = document.getElementById('progressStepText');
    const sQueries = document.getElementById('stepQueries');
    const sCurate = document.getElementById('stepCurate');
    const sDraft = document.getElementById('stepDraft');
    const sVerify = document.getElementById('stepVerify');

    stepText.innerText = 'Searching OpenAlex scholarly database...';
    sQueries.classList.add('done');

    try {
      const resp = await fetch('/api/draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: title, style, key })
      });
      if (resp.ok) {
        const data = await resp.json();
        currentArticleUrl = data.html_url;
        currentMarkdownUrl = data.md_url;
        document.getElementById('articleIframe').src = data.html_url;
        document.getElementById('articleMeta').innerText = (data.sources_count || 0) + ' Sources Cited';
        showView('readerView');
        return;
      }
    } catch (e) {}

    try {
      const qSchema = {
        type: "OBJECT",
        properties: {
          queries: { type: "ARRAY", items: { type: "STRING" } },
          core_entity: { type: "STRING" }
        },
        required: ["queries", "core_entity"]
      };
      const qRes = await callGroqAPI(`Topic: "${title}". Give 3 scholarly search queries and the core entity.`, qSchema, "", key);
      
      stepText.innerText = 'Curating peer-reviewed evidence...';
      sCurate.classList.add('done');

      let allPapers = [];
      for (const q of (qRes.queries || [title])) {
        const res = await searchOpenAlex(q);
        allPapers.push(...res);
      }
      const seen = new Set();
      const papers = [];
      for (const p of allPapers) {
        const norm = p.title.toLowerCase().replace(/[^a-z0-9]/g, '');
        if (norm && !seen.has(norm)) {
          seen.add(norm);
          papers.push(p);
        }
      }
      const topPapers = papers.slice(0, 15);

      if (topPapers.length === 0) {
        throw new Error('No academic papers with abstracts found for this topic.');
      }

      stepText.innerText = 'Writing grounded article with inline citations...';
      sDraft.classList.add('done');

      const artSchema = {
        type: "OBJECT",
        properties: {
          title: { type: "STRING" },
          standfirst: { type: "STRING" },
          evidence_note: { type: "STRING" },
          featured_study: {
            type: "OBJECT",
            properties: {
              source_index: { type: "INTEGER" },
              why: { type: "STRING" },
              method: { type: "STRING" },
              results: { type: "STRING" }
            },
            required: ["source_index", "why", "method", "results"]
          },
          sections: {
            type: "ARRAY",
            items: {
              type: "OBJECT",
              properties: {
                heading: { type: "STRING" },
                paragraphs: { type: "ARRAY", items: { type: "STRING" } },
                pull_quote: { type: "STRING" }
              },
              required: ["heading", "paragraphs"]
            }
          },
          key_takeaways: { type: "ARRAY", items: { type: "STRING" } },
          references: { type: "ARRAY", items: { type: "INTEGER" } }
        },
        required: ["title", "standfirst", "evidence_note", "featured_study", "sections", "key_takeaways", "references"]
      };

      const prefs = getPreferences();
      const sourcesPrompt = topPapers.map((p, idx) => `SOURCE ${idx + 1}\nTitle: ${p.title}\nAuthors: ${p.authorLine} (${p.year || 'n.d.'})\nVenue: ${p.venue}\nAbstract: ${p.abstract}`).join('\n\n');
      const writerSys = `You are a science writer turning journal abstracts into a high-quality article.\n` +
        `CUSTOM GENERATION DIRECTIVES:\n` +
        `1. Target Article Length: ${prefs.lengthLabel}\n` +
        `2. Writing Tone & Style: ${prefs.toneLabel}\n` +
        `3. Evidence & Citation Focus: ${prefs.depthLabel}\n` +
        `4. Target Output Language: ${prefs.lang}. WRITE ALL HEADING, PARAGRAPH, AND TAKEAWAY TEXT IN ${prefs.lang.toUpperCase()}.\n` +
        `5. Citation Rule: Cite sources inline as [N] where N is the SOURCE index. Only state facts present in the abstracts.`;
      const articleData = await callGroqAPI(`Topic: ${title}\n\nCandidate Sources:\n${sourcesPrompt}`, artSchema, writerSys, key);

      stepText.innerText = 'Verifying citations & formatting HTML...';
      sVerify.classList.add('done');

      const htmlOutput = clientRenderArticle(articleData, topPapers, title);
      const iframe = document.getElementById('articleIframe');
      iframe.srcdoc = htmlOutput;

      saveLocalDraft(articleData.title || title, htmlOutput);

      cachedShareUrl = '';
      currentTitle = articleData.title || title;
      const hash = encodeArticleToHash(htmlOutput);
      if (hash) {
        window.location.hash = hash;
        currentArticleUrl = window.location.pathname + hash;
      }

      document.getElementById('articleMeta').innerText = (articleData.references?.length || 0) + ' Sources Cited';
      showView('readerView');
    } catch (err) {
      alert('Drafting error: ' + err.message);
      showView('ideasView');
    }
  }

  function clientRenderArticle(article, papers, topic) {
    if (!article.sections && Object.keys(article).length === 1 && typeof article[Object.keys(article)[0]] === 'object') {
      article = article[Object.keys(article)[0]]; // Auto-unwrap if LLM nested the response
    }
    const refs = article.references || [];
    const citedPapers = refs.map(idx => papers[idx - 1]).filter(Boolean);
    const dateStr = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });

    let sectionsHtml = (article.sections || []).map(sec => `
      <section>
        <h2>${escapeHtml(sec.heading)}</h2>
        ${sec.pull_quote ? `<blockquote class="pull">${escapeHtml(sec.pull_quote)}</blockquote>` : ''}
        ${(sec.paragraphs || []).map((p, i) => `<p ${i===0?'class="opener"':''}>${escapeHtml(p).replace(/\[(\d+)\]/g, '<sup class="cite">[$1]</sup>')}</p>`).join('')}
      </section>
    `).join('');

    let fsHtml = '';
    const fs = article.featured_study;
    if (fs && fs.source_index && papers[fs.source_index - 1]) {
      const fp = papers[fs.source_index - 1];
      fsHtml = `
        <aside class="featured" style="border:1px solid #0d9488; padding:1.2rem; border-radius:10px; margin:1.5rem 0; background:rgba(13,148,136,0.08);">
          <h3 style="margin:0 0 0.5rem; text-transform:uppercase; font-size:0.8rem; color:#0d9488;">Featured Study</h3>
          <p><strong><a href="${escapeHtml(fp.link)}" target="_blank">${escapeHtml(fp.title)}</a></strong> — ${escapeHtml(fp.authorLine)} (${fp.year||'n.d.'})</p>
          <p><em>${escapeHtml(fs.why)}</em></p>
          <p><strong>Method:</strong> ${escapeHtml(fs.method)}</p>
          <p><strong>Results:</strong> ${escapeHtml(fs.results)}</p>
        </aside>
      `;
    }

    let takeawaysHtml = (article.key_takeaways || []).map(t => `<li>${escapeHtml(t).replace(/\[(\d+)\]/g, '<sup class="cite">[$1]</sup>')}</li>`).join('');

    let refsHtml = citedPapers.map((p, i) => `
      <li id="ref-${i+1}" style="margin-bottom:0.6rem;">
        <strong>${escapeHtml(p.authorLine)} (${p.year||'n.d.'})</strong> 
        <a href="${escapeHtml(p.link)}" target="_blank">${escapeHtml(p.title)}</a> 
        <em>${escapeHtml(p.venue)}</em>
      </li>
    `).join('');

    return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(article.title)}</title>
<style>
  :root, html[data-theme="dark"] {
    --bg: #0f1115;
    --ink: #f1f5f9;
    --muted: #cbd5e1;
    --accent: #2dd4bf;
    --accent-hover: #5eead4;
    --accent-soft: rgba(45, 212, 191, 0.15);
    --rule: #272a30;
    --card: #181b20;
    color-scheme: dark;
  }
  @media (prefers-color-scheme: light) {
    :root:not([data-theme="dark"]) {
      --bg: #ffffff;
      --ink: #111827;
      --muted: #4b5563;
      --accent: #0d9488;
      --accent-hover: #0f766e;
      --accent-soft: rgba(13, 148, 136, 0.1);
      --rule: #e5e7eb;
      --card: #f8fafc;
      color-scheme: light;
    }
  }
  html[data-theme="light"] {
    --bg: #ffffff;
    --ink: #111827;
    --muted: #4b5563;
    --accent: #0d9488;
    --accent-hover: #0f766e;
    --accent-soft: rgba(13, 148, 136, 0.1);
    --rule: #e5e7eb;
    --card: #f8fafc;
    color-scheme: light;
  }
  body { 
    font-family: Georgia, serif; 
    line-height: 1.6; 
    background: var(--bg);
    color: var(--ink); 
    max-width: 680px; 
    margin: 0 auto; 
    padding: 2rem 1.25rem; 
  }
  p, h2, h3, section, div, li { color: var(--ink); }
  h1 { font-size: 2.2rem; line-height: 1.2; margin-bottom: 0.5rem; color: var(--ink); }
  h2 { font-size: 1.5rem; line-height: 1.25; margin: 2rem 0 0.8rem; color: var(--ink); }
  .standfirst { font-size: 1.2rem; color: var(--muted); margin-bottom: 1.5rem; }
  .byline { font-family: sans-serif; font-size: 0.85rem; color: var(--muted); border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); padding: 0.5rem 0; margin-bottom: 1.5rem; }
  sup.cite { color: var(--accent); font-weight: bold; }
  blockquote.pull { border-left: 3px solid var(--accent); margin: 1.5rem 0; padding-left: 1rem; font-style: italic; font-size: 1.2rem; color: var(--ink); }
  aside.takeaways { background: var(--card); border: 1px solid var(--rule); border-radius: 8px; padding: 1.2rem; margin: 2rem 0; }
  aside.takeaways h3 { text-transform: uppercase; font-size: 0.8rem; color: var(--accent); margin-top: 0; }
  aside.takeaways li { color: var(--ink); margin-bottom: 0.4rem; }
  aside.featured { border: 1px solid var(--accent); padding: 1.2rem; border-radius: 10px; margin: 1.5rem 0; background: var(--accent-soft); }
  aside.featured h3 { margin: 0 0 0.5rem; text-transform: uppercase; font-size: 0.8rem; color: var(--accent); }
  aside.featured p { color: var(--ink); margin: 0 0 0.5rem; }
  aside.featured a { color: var(--accent); font-weight: 600; }
  [contenteditable="true"] { outline: none; transition: background 0.2s, box-shadow 0.2s; border-radius: 4px; }
  [contenteditable="true"]:hover { box-shadow: 0 0 0 1px var(--accent); cursor: text; }
  [contenteditable="true"]:focus { box-shadow: 0 0 0 2px var(--accent); background: rgba(45, 212, 191, 0.08); }
</style>
</head>
<body>
  <p style="text-transform:uppercase; font-size:0.75rem; font-weight:bold; color:#0d9488; margin-bottom:0.2rem;">${escapeHtml(topic)}</p>
  <h1>${escapeHtml(article.title)}</h1>
  <p class="standfirst">${escapeHtml(article.standfirst)}</p>
  <div class="byline">Published ${dateStr} · Grounded in ${citedPapers.length} Peer-Reviewed Sources</div>

  ${fsHtml}

  ${sectionsHtml}

  <aside class="takeaways">
    <h3>Key Takeaways</h3>
    <ul>${takeawaysHtml}</ul>
  </aside>

  <h3 style="margin-top:2.5rem; font-family:sans-serif; text-transform:uppercase; font-size:0.85rem; color:#0d9488;">Sources</h3>
  <ol>${refsHtml}</ol>
</body>
</html>`;
  }

  function saveLocalDraft(title, htmlContent) {
    const list = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    list.unshift({
      title: title,
      date: new Date().toISOString(),
      content: htmlContent
    });
    localStorage.setItem('articlegen_local_drafts', JSON.stringify(list.slice(0, 20)));
  }

  async function getShareableArticleUrl() {
    if (cachedShareUrl) return cachedShareUrl;

    if (currentArticleUrl && !currentArticleUrl.includes('#read=') && !currentArticleUrl.includes('#p=')) {
      cachedShareUrl = window.location.origin + currentArticleUrl;
      return cachedShareUrl;
    }

    const iframe = document.getElementById('articleIframe');
    const html = iframe.srcdoc || '';

    if (!html) {
      return window.location.origin + window.location.pathname;
    }

    try {
      const formData = new URLSearchParams();
      formData.append('content', html);
      formData.append('expiry_days', '30');

      const res = await fetch('https://dpaste.com/api/v2/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData.toString()
      });

      if (res.ok) {
        const pasteUrl = (await res.text()).trim();
        const pasteId = pasteUrl.split('/').filter(Boolean).pop();
        if (pasteId) {
          cachedShareUrl = window.location.origin + window.location.pathname + '#p=' + pasteId;
          return cachedShareUrl;
        }
      }
    } catch (e) {
      console.warn("dpaste.com error:", e);
    }

    const hash = encodeArticleToHash(html);
    cachedShareUrl = window.location.origin + window.location.pathname + hash;
    return cachedShareUrl;
  }

  async function shareCurrentArticle() {
    const shareUrl = await getShareableArticleUrl();
    if (navigator.share) {
      navigator.share({
        title: currentTitle || document.title,
        text: currentTitle,
        url: shareUrl
      }).catch(() => {});
    } else {
      copyCurrentLink();
    }
  }

  async function copyCurrentLink() {
    const shareUrl = await getShareableArticleUrl();
    navigator.clipboard.writeText(shareUrl).then(() => {
      showToast('Article link copied to clipboard!');
    }).catch(() => {});
  }

  function openRawMarkdown() {
    if (currentMarkdownUrl) {
      window.open(currentMarkdownUrl, '_blank');
    }
  }

  async function publishToGithub() {
    showToast('Publishing to GitHub...');
    try {
      const resp = await fetch('/api/publish', { method: 'POST' });
      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || 'Failed to publish');
      }
      const data = await resp.json();
      showToast(data.message || 'Successfully published!');
      setTimeout(() => {
        alert('Your drafts have been published to GitHub!\n\nThey will be live in ~20 seconds at:\nhttps://bartholomewtj.github.io/article-generator/');
      }, 500);
    } catch (err) {
      alert('Error publishing: ' + err.message);
    }
  }

  async function showQrModal() {
    const wrapper = document.getElementById('qrCanvasWrapper');
    wrapper.innerHTML = '<p style="color:var(--muted); font-size:0.9rem;">⏳ Generating mobile QR code...</p>';
    openModal('qrModal');

    try {
      const shareUrl = await getShareableArticleUrl();
      const displayUrl = shareUrl.length > 90 ? (shareUrl.substring(0, 80) + '... (Base64 Draft)') : shareUrl;
      wrapper.innerHTML = `
        <div style="display:flex; flex-direction:column; align-items:center;">
          <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(shareUrl)}" alt="QR Code" width="200" height="200" style="border-radius:8px; border:1px solid var(--card-border);">
          <p style="font-size:0.75rem; color:var(--muted); margin-top:0.6rem; word-break:break-all; max-width:260px;">${escapeHtml(displayUrl)}</p>
        </div>
      `;
    } catch (e) {
      wrapper.innerHTML = '<p style="color:var(--danger); font-size:0.85rem;">Failed to generate QR code.</p>';
    }
  }

  async function loadGallery() {
    const container = document.getElementById('galleryList');
    const filterQuery = (document.getElementById('gallerySearchInput')?.value || '').toLowerCase().trim();
    container.innerHTML = '<p style="color:var(--muted);">Loading draft queue...</p>';
    
    try {
      const resp = await fetch('/api/drafts');
      if (resp.ok) {
        const data = await resp.json();
        if (data.drafts && data.drafts.length > 0) {
          const filtered = data.drafts.filter(d => !filterQuery || d.title.toLowerCase().includes(filterQuery));
          container.innerHTML = '';
          if (filtered.length === 0) {
            container.innerHTML = '<p style="color:var(--muted);">No matching drafts found.</p>';
            return;
          }
          filtered.forEach(d => {
            const item = document.createElement('div');
            item.className = 'gallery-item';
            item.innerHTML = `
              <div>
                <div class="gallery-title">${escapeHtml(d.title)}</div>
                <div class="gallery-meta">${new Date(d.date).toLocaleDateString()}</div>
              </div>
              <a class="gallery-action" href="#" onclick="openDraftFromGallery('${d.html_url}', '${escapeHtml(d.title).replace(/'/g, "\\'")}'); return false;">Read →</a>
            `;
            container.appendChild(item);
          });
          return;
        }
      }
    } catch (e) {}

    const localDrafts = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    if (localDrafts.length === 0) {
      container.innerHTML = '<p style="color:var(--muted); text-align:center; padding:2rem 0;">No saved article drafts yet.<br><span style="font-size:0.8rem; color:var(--muted);">Generated drafts will automatically appear here.</span></p>';
      return;
    }

    const filtered = localDrafts
      .map((d, origIndex) => ({ ...d, origIndex }))
      .filter(d => !filterQuery || d.title.toLowerCase().includes(filterQuery));

    // Sort starred/starred favorites to top
    filtered.sort((a, b) => (b.starred ? 1 : 0) - (a.starred ? 1 : 0));

    if (filtered.length === 0) {
      container.innerHTML = '<p style="color:var(--muted);">No matching drafts found.</p>';
      return;
    }

    container.innerHTML = '';
    filtered.forEach((d) => {
      const item = document.createElement('div');
      item.className = 'gallery-item';
      item.style.gap = '0.5rem';
      item.innerHTML = `
        <button type="button" class="icon-btn" style="width:30px; height:30px; border:none; background:none; font-size:1.1rem; cursor:pointer;" onclick="toggleFavoriteDraft(${d.origIndex})" title="${d.starred ? 'Unstar' : 'Star Favorite'}">
          ${d.starred ? '⭐' : '☆'}
        </button>
        <div style="flex:1; min-width:0;">
          <div class="gallery-title" style="line-height:1.35; margin-bottom:0.25rem;">${escapeHtml(d.title)}</div>
          <div class="gallery-meta">${new Date(d.date).toLocaleDateString()}</div>
        </div>
        <div style="display:flex; align-items:center; gap:0.6rem;">
          <a class="gallery-action" href="#" onclick="openLocalDraft(${d.origIndex}); return false;">Read →</a>
          <button type="button" class="icon-btn" style="width:32px; height:32px; color:#ef4444; border-color:rgba(239,68,68,0.3); font-size:0.85rem;" onclick="deleteLocalDraft(${d.origIndex})" title="Delete Draft">🗑️</button>
        </div>
      `;
      container.appendChild(item);
    });
  }

  function deleteLocalDraft(index) {
    let localDrafts = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    if (index >= 0 && index < localDrafts.length) {
      const deletedTitle = localDrafts[index].title;
      localDrafts.splice(index, 1);
      localStorage.setItem('articlegen_local_drafts', JSON.stringify(localDrafts));
      showToast(`Deleted "${deletedTitle.substring(0, 20)}..."`);
      loadGallery();
    }
  }

  function clearAllLocalDrafts() {
    let localDrafts = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    if (localDrafts.length === 0) {
      showToast("No drafts to delete.");
      return;
    }
    if (confirm(`Are you sure you want to delete all ${localDrafts.length} saved article drafts? This cannot be undone.`)) {
      localStorage.removeItem('articlegen_local_drafts');
      showToast("All drafts cleared!");
      loadGallery();
    }
  }

  function toggleFavoriteDraft(index) {
    let localDrafts = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    if (localDrafts[index]) {
      localDrafts[index].starred = !localDrafts[index].starred;
      localStorage.setItem('articlegen_local_drafts', JSON.stringify(localDrafts));
      loadGallery();
    }
  }

  function openLocalDraft(index) {
    const localDrafts = JSON.parse(localStorage.getItem('articlegen_local_drafts') || '[]');
    const draft = localDrafts[index];
    if (draft) {
      currentTitle = draft.title;
      document.getElementById('articleIframe').srcdoc = draft.content;
      const hash = encodeArticleToHash(draft.content);
      if (hash) {
        window.location.hash = hash;
        currentArticleUrl = window.location.pathname + hash;
      }
      showView('readerView');
    }
  }

  async function saveToPublishedLibrary() {
    const iframe = document.getElementById('articleIframe');
    if (!iframe) return;
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    const htmlContent = doc?.documentElement?.outerHTML || iframe.srcdoc || '';
    if (!htmlContent) {
      showToast('No article content to save.');
      return;
    }

    showToast('Generating public link & saving...');
    const publicUrl = await getShareableArticleUrl();
    const title = currentTitle || doc.title || 'Untitled Article';

    let publishedLib = JSON.parse(localStorage.getItem('articlegen_published_library') || '[]');
    // Prevent duplicate saves by title
    publishedLib = publishedLib.filter(item => item.title !== title);
    publishedLib.unshift({
      id: 'pub_' + Date.now(),
      title: title,
      date: new Date().toISOString(),
      content: htmlContent,
      publicUrl: publicUrl
    });

    localStorage.setItem('articlegen_published_library', JSON.stringify(publishedLib));
    showToast('📚 Saved to Published Library!');

    // Trigger auto-sync to Gist if token is present
    const ghToken = localStorage.getItem('articlegen_gh_token');
    if (ghToken) {
      syncPushToGist();
    }
  }

  function loadPublishedLibrary() {
    const container = document.getElementById('publishedList');
    if (!container) return;
    const filterQuery = (document.getElementById('publishedSearchInput')?.value || '').toLowerCase().trim();
    const publishedLib = JSON.parse(localStorage.getItem('articlegen_published_library') || '[]');

    if (publishedLib.length === 0) {
      container.innerHTML = `
        <div style="text-align:center; padding:3rem 1rem; color:var(--muted);">
          <span style="font-size:2.5rem; display:block; margin-bottom:0.5rem;">📚</span>
          <p style="margin:0 0 0.5rem; font-weight:600;">Your Published Library is empty</p>
          <p style="font-size:0.82rem; margin:0;">Open any finished article draft and click <strong>"Save to Published Library"</strong> to save it permanently with a public sharing link across your devices.</p>
        </div>
      `;
      return;
    }

    const filtered = publishedLib.filter(d => !filterQuery || d.title.toLowerCase().includes(filterQuery));
    if (filtered.length === 0) {
      container.innerHTML = '<p style="color:var(--muted);">No matching published articles found.</p>';
      return;
    }

    container.innerHTML = '';
    filtered.forEach((item, index) => {
      const card = document.createElement('div');
      card.className = 'draft-card';
      card.style.marginBottom = '1rem';

      const shortUrl = item.publicUrl ? (item.publicUrl.length > 50 ? item.publicUrl.substring(0, 48) + '...' : item.publicUrl) : '';

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:0.5rem;">
          <h3 class="draft-title" style="margin:0; font-size:1.1rem; flex:1;">${escapeHtml(item.title)}</h3>
          <button type="button" class="icon-btn" style="width:30px; height:30px; color:#ef4444; border-color:rgba(239,68,68,0.3); font-size:0.85rem;" onclick="deletePublishedArticle('${item.id}')" title="Delete Published Article">🗑️</button>
        </div>
        <p style="font-size:0.8rem; color:var(--muted); margin:0 0 0.8rem;">Saved on ${new Date(item.date).toLocaleDateString()}</p>
        
        <div style="background:var(--bg); border:1px solid var(--card-border); border-radius:8px; padding:0.5rem 0.8rem; display:flex; align-items:center; justify-content:space-between; margin-bottom:0.8rem;">
          <span style="font-size:0.78rem; color:var(--accent); font-family:monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:240px;">${escapeHtml(shortUrl)}</span>
          <button type="button" class="pill" style="font-size:0.75rem; padding:0.2rem 0.6rem;" onclick="copyLinkDirect('${escapeHtml(item.publicUrl)}')">🔗 Copy Link</button>
        </div>

        <div style="display:flex; gap:0.5rem;">
          <button class="btn-select" style="flex:1; margin:0;" onclick="openPublishedArticle('${item.id}')">📖 Read Article</button>
          <button class="pill" style="padding:0.6rem 0.8rem;" onclick="showQrForUrl('${escapeHtml(item.publicUrl)}')">📱 QR</button>
        </div>
      `;
      container.appendChild(card);
    });
  }

  function openPublishedArticle(id) {
    const publishedLib = JSON.parse(localStorage.getItem('articlegen_published_library') || '[]');
    const item = publishedLib.find(d => d.id === id);
    if (item) {
      currentTitle = item.title;
      document.getElementById('articleIframe').srcdoc = item.content;
      cachedShareUrl = item.publicUrl;
      showView('readerView');
    }
  }

  function copyLinkDirect(url) {
    if (!url) return;
    navigator.clipboard.writeText(url).then(() => {
      showToast('Public article link copied to clipboard!');
    }).catch(() => {});
  }

  function showQrForUrl(url) {
    if (!url) return;
    const wrapper = document.getElementById('qrCanvasWrapper');
    openModal('qrModal');
    wrapper.innerHTML = `
      <div style="display:flex; flex-direction:column; align-items:center;">
        <img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(url)}" alt="QR Code" width="200" height="200" style="border-radius:8px; border:1px solid var(--card-border);">
        <p style="font-size:0.75rem; color:var(--muted); margin-top:0.6rem; word-break:break-all; max-width:260px;">${escapeHtml(url)}</p>
      </div>
    `;
  }

  function deletePublishedArticle(id) {
    let publishedLib = JSON.parse(localStorage.getItem('articlegen_published_library') || '[]');
    const item = publishedLib.find(d => d.id === id);
    if (item && confirm(`Are you sure you want to remove "${item.title}" from your Published Library?`)) {
      publishedLib = publishedLib.filter(d => d.id !== id);
      localStorage.setItem('articlegen_published_library', JSON.stringify(publishedLib));
      showToast('Removed from Published Library');
      loadPublishedLibrary();
      const ghToken = localStorage.getItem('articlegen_gh_token');
      if (ghToken) syncPushToGist();
    }
  }

  function clearPublishedLibrary() {
    let publishedLib = JSON.parse(localStorage.getItem('articlegen_published_library') || '[]');
    if (publishedLib.length === 0) {
      showToast("Library is already empty.");
      return;
    }
    if (confirm(`Are you sure you want to delete all ${publishedLib.length} published articles from your Library?`)) {
      localStorage.removeItem('articlegen_published_library');
      showToast("Published Library cleared!");
      loadPublishedLibrary();
      const ghToken = localStorage.getItem('articlegen_gh_token');
      if (ghToken) syncPushToGist();
    }
  }

  function escapeHtml(str) {
    return (str || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }