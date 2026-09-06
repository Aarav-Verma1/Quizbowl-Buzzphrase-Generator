// Obsidian - main client-side script
// Extracted from templates/index.html

// ============================================
// DARK MODE THEME MANAGEMENT
// ============================================

const THEME_KEY = 'obsidian_theme_preference';

// Initialize theme on page load
function initializeTheme() {
    const html = document.documentElement;
    
    // Check localStorage for saved preference
    const savedTheme = localStorage.getItem(THEME_KEY);
    
    // If no saved preference, default to dark mode
    let prefersDark = true;
    if (savedTheme) {
        prefersDark = savedTheme === 'dark';
    }
    
    // Apply theme
    if (prefersDark) {
        html.setAttribute('data-theme', 'dark');
    } else {
        html.removeAttribute('data-theme');
    }
    
    updateThemeToggleState();
}

function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    
    if (newTheme === 'dark') {
        html.setAttribute('data-theme', 'dark');
    } else {
        html.removeAttribute('data-theme');
    }
    
    localStorage.setItem(THEME_KEY, newTheme);
    updateThemeToggleState();
}

function updateThemeToggleState() {
    const toggle = document.getElementById('themeToggle');
    if (!toggle) return;
    
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const circle = toggle.querySelector('.theme-toggle-circle');
    
    if (circle) {
        circle.textContent = isDark ? '🌙' : '☀️';
    }
}

// Initialize theme on load
document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    
    // Set up theme toggle button after DOM is ready
    const themeToggle = document.getElementById('themeToggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', (e) => {
            e.preventDefault();
            toggleTheme();
        });
    }
});

// Listen for system theme changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (!localStorage.getItem(THEME_KEY)) {
        // Only apply if user hasn't manually set a preference
        const newTheme = e.matches ? 'dark' : 'light';
        const html = document.documentElement;
        if (newTheme === 'dark') {
            html.setAttribute('data-theme', 'dark');
        } else {
            html.removeAttribute('data-theme');
        }
        updateThemeToggleState();
    }
});

// ============================================
// EXISTING SCRIPT CONTINUES
// ============================================

// Enhanced parallax effect
window.addEventListener('scroll', function() {
    const scrolled = window.pageYOffset;
    const parallaxElements = document.querySelectorAll('.parallax::before');
    parallaxElements.forEach(el => {
        const speed = 0.5;
        el.style.transform = `translateY(${scrolled * speed}px) translateZ(-1px) scale(2)`;
    });
});

// Smooth scrolling for navigation links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});

let selectedSuggestionIndex = -1;
let suggestions = [];
let currentResults = null;
let selectedBuzzwords = new Set();
let displayedBuzzwordsCount = 20;

// Cart state (persisted in localStorage)
const CART_KEY = 'obsidian_cart_v1';
function loadCart() {
    try {
        const raw = localStorage.getItem(CART_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        return Array.isArray(parsed) ? parsed : [];
    } catch (_) { return []; }
}
function saveCart(items) {
    localStorage.setItem(CART_KEY, JSON.stringify(items));
    updateCartBadge();
}
function updateCartBadge() {
    const badge = document.getElementById('cartCountBadge');
    if (!badge) return;
    const count = loadCart().length;
    if (count > 0) {
        badge.style.display = 'inline-block';
        badge.textContent = String(count);
    } else {
        badge.style.display = 'none';
    }
}
function addItemsToCart(items) {
    const cart = loadCart();
    const existing = new Set(cart.map(i => `${i.answerline}|||${i.buzzphrase}`));
    for (const it of items) {
        const key = `${it.answerline}|||${it.buzzphrase}`;
        if (!existing.has(key)) {
            cart.push(it);
            existing.add(key);
        }
    }
    saveCart(cart);
}
function removeItemFromCart(answerline, buzzphrase) {
    const cart = loadCart().filter(i => !(i.answerline === answerline && i.buzzphrase === buzzphrase));
    saveCart(cart);
}
function clearCart() {
    saveCart([]);
}

// Get all form elements
const answerInput = document.getElementById('answer');
const suggestionsDiv = document.getElementById('autocompleteSuggestions');
const categorySelect = document.getElementById('category');
const maxQuestionsInput = document.getElementById('maxQuestions');
const sortBySelect = document.getElementById('sortBy');
const resultsSortBySelect = document.getElementById('resultsSortBy');
const submitBtn = document.getElementById('submitBtn');
const generateExplanationsBtn = document.getElementById('generateExplanationsBtn');
const explanationSection = document.getElementById('explanationSection');
const explanationLoading = document.getElementById('explanationLoading');
const exportBtn = document.getElementById('exportBtn');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const loadMoreSection = document.getElementById('loadMoreSection');
const selectedCountSpan = document.getElementById('selectedCount');
const addSelectedToCartBtn = document.getElementById('addSelectedToCartBtn');
const openCartBtn = document.getElementById('openCartBtn');
const closeCartBtn = document.getElementById('closeCartBtn');
const cartModalOverlay = document.getElementById('cartModalOverlay');
const cartListEl = document.getElementById('cartList');
const cartEmptyState = document.getElementById('cartEmptyState');
const exportCartBtn = document.getElementById('exportCartBtn');
const clearCartBtn = document.getElementById('clearCartBtn');

// Hybrid weight sliders
const hybridWeightsSection = document.getElementById('hybridWeightsSection');
const celerityWeightSlider = document.getElementById('celerityWeight');
const frequencyWeightSlider = document.getElementById('frequencyWeight');
const celerityWeightValue = document.getElementById('celerityWeightValue');
const frequencyWeightValue = document.getElementById('frequencyWeightValue');

// Store current weight values
let currentWeights = {
    celerity: 0.6,
    frequency: 0.4
};

// Handle weight slider changes
if (celerityWeightSlider && frequencyWeightSlider) {
    celerityWeightSlider.addEventListener('input', function() {
        const celerityWeight = parseInt(this.value);
        const frequencyWeight = 100 - celerityWeight;
        
        frequencyWeightSlider.value = frequencyWeight;
        
        // Update display values
        celerityWeightValue.textContent = `${celerityWeight}%`;
        frequencyWeightValue.textContent = `${frequencyWeight}%`;
        
        // Store normalized values (0-1)
        currentWeights.celerity = celerityWeight / 100;
        currentWeights.frequency = frequencyWeight / 100;
    });
    
    frequencyWeightSlider.addEventListener('input', function() {
        const frequencyWeight = parseInt(this.value);
        const celerityWeight = 100 - frequencyWeight;
        
        celerityWeightSlider.value = celerityWeight;
        
        // Update display values
        celerityWeightValue.textContent = `${celerityWeight}%`;
        frequencyWeightValue.textContent = `${frequencyWeight}%`;
        
        // Store normalized values (0-1)
        currentWeights.celerity = celerityWeight / 100;
        currentWeights.frequency = frequencyWeight / 100;
    });
}

// Replace emoji texts with plain text labels in dynamic updates
function setAnalyzing(btn, isOn) {
    if (!btn) return;
    btn.disabled = !!isOn;
    btn.innerHTML = isOn ? 'Analyzing…' : 'Analyze Buzzwords';
}

function setGenerating(btn, isOn) {
    if (!btn) return;
    btn.disabled = !!isOn;
    btn.innerHTML = isOn ? 'Generating…' : 'Regenerate Explanations';
}

function setExporting(btn, isOn) {
    if (!btn) return;
    btn.disabled = !!isOn;
    btn.innerHTML = isOn ? 'Exporting…' : 'Export Selected to Anki (CSV)';
}

// --- Form state ---
function updateFormState() {
    const hasAnswer = !!answerInput && answerInput.value.trim() !== '';
    const hasValidQuestions = !!maxQuestionsInput && parseInt(maxQuestionsInput.value) >= 50;
    if (submitBtn) submitBtn.disabled = !(hasAnswer && hasValidQuestions);
}

// Enhanced autocomplete with better UX
if (answerInput) {
    answerInput.addEventListener('input', function() {
        updateFormState();
        const query = this.value.trim();
        if (query.length < 2) { hideSuggestions(); return; }
        this.style.backgroundImage = "url('data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"16\" height=\"16\" fill=\"%236b7280\" viewBox=\"0 0 16 16\"><path d=\"M8 3a5 5 0 1 0 4.546 2.914.5.5 0 0 1 .908-.417A6 6 0 1 1 8 2v1z\"/><path d=\"M8 4.466V.534a.25.25 0 0 1 .41-.192l2.36 1.966c.12.1.12.284 0 .384L8.41 4.658A.25.25 0 0 1 8 4.466z\"/></svg>')";
        this.style.backgroundRepeat = 'no-repeat';
        this.style.backgroundPosition = 'right 1rem center';
        const searchMode = document.getElementById('searchMode')?.value || 'exact';
        fetch(`/autocomplete?query=${encodeURIComponent(query)}&search_mode=${searchMode}`)
            .then(response => response.json())
            .then(data => { this.style.backgroundImage = 'none'; suggestions = data; showSuggestions(data); })
            .catch(error => { this.style.backgroundImage = 'none'; console.error('Autocomplete error:', error); hideSuggestions(); });
    });
}
if (categorySelect) categorySelect.addEventListener('change', updateFormState);
if (maxQuestionsInput) maxQuestionsInput.addEventListener('input', updateFormState);

// Show/hide hybrid weights section based on sort selection
if (sortBySelect) {
    sortBySelect.addEventListener('change', function() {
        if (hybridWeightsSection) {
            hybridWeightsSection.style.display = this.value === 'hybrid' ? 'block' : 'none';
        }
    });
}

if (answerInput) {
    answerInput.addEventListener('keydown', function(e) {
        if (suggestionsDiv && suggestionsDiv.style.display === 'none') return;
        switch(e.key) {
            case 'ArrowDown': e.preventDefault(); selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, suggestions.length - 1); updateSelectedSuggestion(); break;
            case 'ArrowUp': e.preventDefault(); selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1); updateSelectedSuggestion(); break;
            case 'Enter': if (selectedSuggestionIndex >= 0) { e.preventDefault(); selectSuggestion(suggestions[selectedSuggestionIndex]); } break;
            case 'Escape': hideSuggestions(); break;
        }
    });
}

document.addEventListener('click', function(e) {
    if (answerInput && suggestionsDiv && !answerInput.contains(e.target) && !suggestionsDiv.contains(e.target)) hideSuggestions();
});

function showSuggestions(suggestionsArr) {
    if (!suggestionsDiv) return;
    if (suggestionsArr.length === 0) { hideSuggestions(); return; }
    suggestionsDiv.innerHTML = '';
    suggestionsArr.forEach((suggestion) => {
        const div = document.createElement('div');
        div.className = 'autocomplete-suggestion';
        div.textContent = suggestion;
        div.addEventListener('click', () => selectSuggestion(suggestion));
        suggestionsDiv.appendChild(div);
    });
    suggestionsDiv.style.display = 'block';
    selectedSuggestionIndex = -1;
}
function hideSuggestions() { if (suggestionsDiv) { suggestionsDiv.style.display = 'none'; selectedSuggestionIndex = -1; } }
function selectSuggestion(suggestion) { if (answerInput) { answerInput.value = suggestion; hideSuggestions(); answerInput.focus(); updateFormState(); } }
function updateSelectedSuggestion() {
    if (!suggestionsDiv) return;
    const suggestionElements = suggestionsDiv.querySelectorAll('.autocomplete-suggestion');
    suggestionElements.forEach((el, index) => { el.classList.toggle('selected', index === selectedSuggestionIndex); });
    if (selectedSuggestionIndex >= 0) suggestionElements[selectedSuggestionIndex].scrollIntoView({ block: 'nearest' });
}

// Enhanced form submission with better UX
const extractForm = document.getElementById('extractForm');
if (extractForm) {
    extractForm.addEventListener('submit', function(e) {
        e.preventDefault();
        if (submitBtn && submitBtn.disabled) { showError('Please enter a topic and specify at least 50 questions to analyze.'); return; }
        const formData = new FormData(this);
        const data = {
            answer: answerInput ? answerInput.value.trim() : '',
            category: formData.get('category'),
            max_questions: parseInt(formData.get('maxQuestions')),
            sort_by: formData.get('sortBy'),
            search_mode: formData.get('searchMode'),
            celerity_weight: currentWeights.celerity,
            frequency_weight: currentWeights.frequency
        };
        selectedBuzzwords.clear();
        displayedBuzzwordsCount = 20;
        updateSelectedCount();
        const resultsEl = document.getElementById('results');
        const errorEl = document.getElementById('error');
        const loadingEl = document.getElementById('loading');
        if (resultsEl) resultsEl.style.display = 'none';
        if (errorEl) errorEl.style.display = 'none';
        if (loadingEl) loadingEl.style.display = 'block';
        if (submitBtn) setAnalyzing(submitBtn, true);
        fetch('/extract', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
        .then(response => response.json())
        .then(dataResp => {
            if (loadingEl) loadingEl.style.display = 'none';
            if (submitBtn) setAnalyzing(submitBtn, false);
            if (dataResp.error) { showError(dataResp.error); }
            else {
                showResults(dataResp);
                const resultsDiv = document.getElementById('results');
                if (resultsDiv) resultsDiv.scrollIntoView({ behavior: 'smooth' });
            }
        })
        .catch(error => {
            if (loadingEl) loadingEl.style.display = 'none';
            if (submitBtn) setAnalyzing(submitBtn, false);
            showError('Network error occurred. Please check your connection and try again.');
            console.error('Error:', error);
        });
    });
}

// Hybrid score calculation function (matches Python backend)
function calculateHybridScore(buzzword) {
    const tfidfScore = buzzword.score || 0;
    const celerityScore = buzzword.celerity || 0;
    
    // Normalize TF-IDF to 0-1 range (assuming max TF-IDF around 2.0-3.0)
    const normalizedTfidf = Math.min(tfidfScore / 3.0, 1.0);
    
    // Ensure celerity is in valid range
    const validCelerity = Math.max(0, Math.min(celerityScore, 1.0));
    
    // Hybrid formula: use current weight settings
    return (currentWeights.frequency * normalizedTfidf) + (currentWeights.celerity * validCelerity);
}

// Sort results functionality
if (resultsSortBySelect) {
    resultsSortBySelect.addEventListener('change', function() {
        if (!currentResults) return;
        const sortBy = this.value;
        currentResults.sort_by = sortBy;
        if (sortBy === 'celerity') {
            currentResults.all_buzzwords.sort((a, b) => b.celerity - a.celerity);
        } else if (sortBy === 'hybrid') {
            currentResults.all_buzzwords.sort((a, b) => calculateHybridScore(b) - calculateHybridScore(a));
        } else {
            currentResults.all_buzzwords.sort((a, b) => b.score - a.score);
        }
        displayedBuzzwordsCount = 20;
        renderBuzzwordsList();
    });
}

// Load more functionality
if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function() {
        if (!currentResults) return;
        displayedBuzzwordsCount = Math.min(displayedBuzzwordsCount + 20, currentResults.all_buzzwords.length);
        renderBuzzwordsList();
        if (displayedBuzzwordsCount >= currentResults.all_buzzwords.length && loadMoreSection) loadMoreSection.style.display = 'none';
    });
}

// AI Explanation generation
if (generateExplanationsBtn) {
    generateExplanationsBtn.addEventListener('click', function() {
        if (!currentResults || !currentResults.buzzwords.length) { showError('No buzzwords available. Please run an analysis first.'); return; }
        setGenerating(generateExplanationsBtn, true);
        if (explanationLoading) explanationLoading.style.display = 'block';
        if (explanationSection) explanationSection.scrollIntoView({ behavior: 'smooth', block: 'center' });
        const explanationPromises = currentResults.all_buzzwords.slice(0, displayedBuzzwordsCount).map(buzzwordData => {
            return fetch('/generate-explanation', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ buzzword: buzzwordData.phrase, topic: currentResults.answer }) })
                .then(response => response.json())
                .then(data => data.explanation || 'Explanation not available')
                .catch(error => { console.error('Error generating explanation for', buzzwordData.phrase, ':', error); return 'Failed to generate explanation'; });
        });
        Promise.all(explanationPromises)
            .then(explanations => {
                if (explanationLoading) explanationLoading.style.display = 'none';
                setGenerating(generateExplanationsBtn, false);
                currentResults.all_buzzwords.forEach((buzzwordData, index) => { if (index < explanations.length) buzzwordData.explanation = explanations[index]; });
                updateBuzzwordsWithExplanations();
            })
            .catch(error => {
                if (explanationLoading) explanationLoading.style.display = 'none';
                setGenerating(generateExplanationsBtn, false);
                showError('Failed to generate explanations. Please try again.');
                console.error('Error generating explanations:', error);
            });
    });
}

function updateBuzzwordsWithExplanations() {
    const buzzwordElements = document.querySelectorAll('.buzzword');
    buzzwordElements.forEach((element, index) => {
        const explanationDiv = element.querySelector('.buzzword-explanation');
        const generateBtn = element.querySelector('.btn-generate-explanation');
        if (explanationDiv && currentResults && currentResults.all_buzzwords[index] && currentResults.all_buzzwords[index].explanation) {
            explanationDiv.textContent = currentResults.all_buzzwords[index].explanation;
            if (generateBtn) generateBtn.textContent = 'Regenerate Explanation';
        }
    });
}

function toggleBuzzwordSelection(buzzword) {
    if (selectedBuzzwords.has(buzzword)) selectedBuzzwords.delete(buzzword);
    else selectedBuzzwords.add(buzzword);
    updateSelectedCount();
}
function updateSelectedCount() { if (selectedCountSpan) selectedCountSpan.textContent = selectedBuzzwords.size; }

function renderBuzzwordsList() {
    if (!currentResults) return;
    const buzzwordsList = document.getElementById('buzzwordsList');
    const displayedBuzzwords = currentResults.all_buzzwords.slice(0, displayedBuzzwordsCount);
    if (!buzzwordsList) return;
    buzzwordsList.innerHTML = '';
    if (displayedBuzzwords.length > 0) {
        displayedBuzzwords.forEach((buzzwordData, index) => {
            const buzzwordElement = document.createElement('div');
            const isSelected = selectedBuzzwords.has(buzzwordData.phrase);
            buzzwordElement.className = `buzzword ${!isSelected ? 'deselected' : ''}`;
            // ensure inner layout wraps and does not cut buttons
            buzzwordElement.style.display = 'block';
            let scoreText = '';
            if (currentResults.sort_by === 'celerity') {
                scoreText = `Celerity: ${buzzwordData.celerity.toFixed(3)}`;
            } else if (currentResults.sort_by === 'hybrid') {
                const hybridScore = calculateHybridScore(buzzwordData);
                scoreText = `Hybrid Score: ${hybridScore.toFixed(3)} (TF-IDF: ${buzzwordData.score.toFixed(3)}, Celerity: ${buzzwordData.celerity.toFixed(3)})`;
            } else {
                scoreText = `Score: ${buzzwordData.score.toFixed(3)}`;
            }
            const metaText = scoreText ? `<span>${scoreText}</span>` : '';
            buzzwordElement.innerHTML = `
                <div class="buzzword-header" style="flex-wrap: wrap;">
                    <div class="buzzword-number">${index + 1}</div>
                    <div class="buzzword-text-container" style="min-width: 0;">
                        <div class="buzzword-text" style="word-break: break-word;">${buzzwordData.phrase}</div>
                        <div class="buzzword-meta">${metaText}</div>
                        <div class="buzzword-actions" style="flex-wrap: wrap;">
                            <button type="button" class="btn btn-small btn-secondary btn-generate-explanation">Generate Explanation</button>
                            <button type="button" class="btn btn-small ${isSelected ? 'btn-danger' : 'btn-success'} btn-toggle-select">${isSelected ? 'Remove' : 'Select'}</button>
                        </div>
                    </div>
                </div>
                <div class="buzzword-explanation">${buzzwordData.explanation || 'Click "Generate Explanation" to get AI-powered insights about this buzzword.'}</div>
            `;
            const generateBtn = buzzwordElement.querySelector('.btn-generate-explanation');
            const toggleBtn = buzzwordElement.querySelector('.btn-toggle-select');
            const explanationDiv = buzzwordElement.querySelector('.buzzword-explanation');
            generateBtn.addEventListener('click', function(e) { e.stopPropagation(); generateSingleExplanation(buzzwordData, buzzwordElement); });
            toggleBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                toggleBuzzwordSelection(buzzwordData.phrase);
                buzzwordElement.classList.toggle('deselected');
                toggleBtn.classList.toggle('btn-danger');
                toggleBtn.classList.toggle('btn-success');
                toggleBtn.textContent = selectedBuzzwords.has(buzzwordData.phrase) ? 'Remove' : 'Select';
            });
            buzzwordElement.addEventListener('click', function() { explanationDiv.classList.toggle('expanded'); });
            buzzwordsList.appendChild(buzzwordElement);
        });
        if (explanationSection) explanationSection.style.display = 'block';
        if (currentResults.all_buzzwords.length > displayedBuzzwordsCount && loadMoreSection) loadMoreSection.style.display = 'block';
        else if (loadMoreSection) loadMoreSection.style.display = 'none';
    } else {
        buzzwordsList.innerHTML = `
            <div style="text-align: center; padding: 4rem; color: var(--gray-500);">
                <h3 style="margin-bottom: 1rem; color: var(--gray-600);">No buzzwords found</h3>
                <p>Try adjusting your search parameters or selecting a different category.</p>
            </div>
        `;
        if (explanationSection) explanationSection.style.display = 'none';
        if (loadMoreSection) loadMoreSection.style.display = 'none';
    }
}

function generateSingleExplanation(buzzwordData, buzzwordElement) {
    const generateBtn = buzzwordElement.querySelector('.btn-generate-explanation');
    const explanationDiv = buzzwordElement.querySelector('.buzzword-explanation');
    generateBtn.disabled = true;
    generateBtn.innerHTML = 'Generating...';
    fetch('/generate-explanation', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ buzzword: buzzwordData.phrase, topic: currentResults.answer }) })
    .then(response => response.json())
    .then(data => {
        generateBtn.disabled = false;
        generateBtn.innerHTML = 'Regenerate Explanation';
        if (data.explanation) { explanationDiv.textContent = data.explanation; buzzwordData.explanation = data.explanation; explanationDiv.classList.add('expanded'); }
    })
    .catch(error => { generateBtn.disabled = false; generateBtn.innerHTML = '<span>🤖</span> Generate Explanation'; showError('Failed to generate explanation. Please try again.'); console.error('Error generating explanation:', error); });
}

function showResults(data) {
    currentResults = data;
    const resultsDiv = document.getElementById('results');
    const infoDiv = document.getElementById('resultsInfo');
    if (resultsSortBySelect) resultsSortBySelect.value = data.sort_by;
    if (sortBySelect) sortBySelect.value = data.sort_by;
    if (infoDiv) {
        infoDiv.innerHTML = `
            <div class="result-stat"><span class="result-stat-value">${data.answer}</span><span class="result-stat-label">Topic Analyzed</span></div>
            <div class="result-stat"><span class="result-stat-value">${data.category || 'All'}</span><span class="result-stat-label">Category Filter</span></div>
            <div class="result-stat"><span class="result-stat-value">${data.total_count}</span><span class="result-stat-label">Total Buzzwords Found</span></div>
            <div class="result-stat"><span class="result-stat-value">${data.sort_by}</span><span class="result-stat-label">Sorted By</span></div>
        `;
    }
    // Select only first 50 buzzwords by default (or all if fewer than 50)
    const buzzwordsToSelect = data.all_buzzwords.slice(0, Math.min(50, data.all_buzzwords.length));
    selectedBuzzwords = new Set(buzzwordsToSelect.map(b => b.phrase));
    updateSelectedCount();
    renderBuzzwordsList();
    if (resultsDiv) resultsDiv.style.display = 'block';
}

function showError(message) {
    const errorDiv = document.getElementById('error');
    if (!errorDiv) return;
    errorDiv.textContent = message;
    errorDiv.style.display = 'block';
    setTimeout(() => { errorDiv.style.display = 'none'; }, 5000);
}

if (exportBtn) {
    exportBtn.addEventListener('click', function() {
        if (!currentResults || selectedBuzzwords.size === 0) { showError('No buzzwords selected for export. Please select at least one buzzphrase.'); return; }
        const exportBtnEl = this;
        setExporting(exportBtnEl, true);
        const selectedBuzzwordsData = currentResults.all_buzzwords.filter(b => selectedBuzzwords.has(b.phrase));
        fetch('/export-anki', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer: currentResults.answer, category: currentResults.category, buzzwords: currentResults.all_buzzwords.map(b => b.phrase), selected_buzzwords: selectedBuzzwordsData.map(b => b.phrase) }) })
        .then(response => { if (response.ok) return response.blob(); return response.json().then(data => { throw new Error(data.error || 'Export failed: Server returned an error.'); }); })
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${currentResults.answer.replace(/\s+/g, '_')}_buzzwords.csv`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            setExporting(exportBtnEl, false);
        })
        .catch(error => { showError(`Export failed: ${error.message}`); setExporting(exportBtnEl, false); console.error('Export error:', error); });
    });
}

// Add selected buzzphrases to cart
if (addSelectedToCartBtn) {
    addSelectedToCartBtn.addEventListener('click', function() {
        if (!currentResults || selectedBuzzwords.size === 0) { showError('No buzzphrases selected to add.'); return; }
        const items = currentResults.all_buzzwords.filter(b => selectedBuzzwords.has(b.phrase)).map(b => ({ answerline: currentResults.answer, buzzphrase: b.phrase, category: currentResults.category }));
        addItemsToCart(items);
    });
}

// Cart modal handlers
if (openCartBtn) openCartBtn.addEventListener('click', function(e) { e.preventDefault(); openCart(); });
if (closeCartBtn) closeCartBtn.addEventListener('click', closeCart);
if (cartModalOverlay) cartModalOverlay.addEventListener('click', function(e) { if (e.target === cartModalOverlay) closeCart(); });
if (clearCartBtn) clearCartBtn.addEventListener('click', function() { clearCart(); renderCart(); });
if (exportCartBtn) {
    exportCartBtn.addEventListener('click', function() {
        const cart = loadCart();
        if (cart.length === 0) { showError('Cart is empty.'); return; }
        const payload = { flashcards: cart, category: '' };
        fetch('/export-anki', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
        .then(response => { if (response.ok) return response.blob(); return response.json().then(d => { throw new Error(d.error || 'Export failed'); }); })
        .then(blob => {
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'shopping_cart_flashcards.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        })
        .catch(err => showError(`Export failed: ${err.message}`));
    });
}

function openCart() { renderCart(); if (cartModalOverlay) cartModalOverlay.style.display = 'flex'; }
function closeCart() { if (cartModalOverlay) cartModalOverlay.style.display = 'none'; }
// Cart modal handlers and search
const cartSearchInput = document.getElementById('cartSearchInput');
function getFilteredCart() {
    const cart = loadCart();
    const q = (cartSearchInput && cartSearchInput.value || '').toLowerCase().trim();
    if (!q) return cart;
    return cart.filter(i => (i.buzzphrase || '').toLowerCase().includes(q) || (i.answerline || '').toLowerCase().includes(q));
}
function renderCart() {
    if (!cartListEl || !cartEmptyState) return;
    const cart = getFilteredCart();
    cartListEl.innerHTML = '';
    if (cart.length === 0) { cartEmptyState.style.display = 'block'; return; }
    cartEmptyState.style.display = 'none';
    for (const item of cart) {
        const row = document.createElement('div');
        row.className = 'cart-item';
        row.innerHTML = `<div style="font-weight:700; color: var(--text-primary);">${item.buzzphrase}</div><div style="color: var(--text-secondary); font-size: 0.85rem;">${item.answerline}</div>`;
        const removeBtn = document.createElement('button');
        removeBtn.className = 'btn btn-danger btn-small';
        removeBtn.textContent = 'Remove';
        const container = document.createElement('div');
        container.style.display = 'grid';
        container.style.gridTemplateColumns = '1fr auto';
        container.style.gap = '0.5rem 1rem';
        container.style.alignItems = 'center';
        container.appendChild(row);
        container.appendChild(removeBtn);
        removeBtn.addEventListener('click', () => { removeItemFromCart(item.answerline, item.buzzphrase); renderCart(); });
        cartListEl.appendChild(container);
    }
}
if (cartSearchInput) cartSearchInput.addEventListener('input', renderCart);

// Initialize
updateCartBadge();
updateFormState();
