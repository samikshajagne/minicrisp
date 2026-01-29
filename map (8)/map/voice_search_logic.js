/* --- 7. Voice Search Logic --- */
let recognition = null;
let isListening = false;
let silenceTimer = null;
let finalTranscript = "";

function initSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    document.getElementById("voice-status").textContent =
      "Speech recognition not supported";
    return false;
  }

  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-IN"; // Default to Indian English as per context

  recognition.onstart = () => {
    isListening = true;
    finalTranscript = "";
    document.getElementById("voice-status").textContent = "Listening...";
    document.getElementById("mic-btn").textContent = "⏹ Stop";
    document.getElementById("mic-btn").style.background = "#fee2e2"; // Light red
    startSilenceTimer();
  };

  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        finalTranscript += event.results[i][0].transcript + " ";
      } else {
        interim += event.results[i][0].transcript;
      }
    }
    document.getElementById("voice-input").value = (
      finalTranscript + interim
    ).trim();
    resetSilenceTimer();
  };

  recognition.onend = () => {
    isListening = false;
    document.getElementById("voice-status").textContent = "Ready";
    document.getElementById("mic-btn").textContent = "🎤 Start";
    document.getElementById("mic-btn").style.background = "";
  };

  recognition.onerror = (e) => {
    document.getElementById("voice-status").textContent = "Error: " + e.error;
    isListening = false;
  };

  return true;
}

function toggleVoiceRecognition() {
  if (!recognition && !initSpeechRecognition()) return;

  if (isListening) {
    recognition.stop();
  } else {
    document.getElementById("voice-input").value = "";
    finalTranscript = "";
    recognition.start();
  }
}

function startSilenceTimer() {
  resetSilenceTimer();
}

function resetSilenceTimer() {
  clearTimeout(silenceTimer);
  silenceTimer = setTimeout(() => {
    if (isListening) {
      recognition.stop();
      // Short delay to allow final transcript to settle
      setTimeout(applyVoiceFilter, 500);
    }
  }, 3000); // 3 seconds silence to auto-submit
}

// Keyword Parser
function parseVoiceInput(text) {
  const result = {
    city: "",
    state: "",
    country: "",
    industries: [],
    productCategory: "",
    productName: "",
    productNameKeywords: [],
  };

  if (!text) return result;
  const t = text.toLowerCase();

  // Helper to check words
  const hasWord = (w) => {
    // Simple strict word match
    return new RegExp(
      `\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`,
      "i",
    ).test(t);
  };

  // Helper for loose partial match (for multi-word entities)
  const hasPhrase = (phrase) => t.includes(phrase.toLowerCase());

  // 1. Industries (from strict EXTRA_INDUSTRIES list)
  // We use the static list defined in the code
  EXTRA_INDUSTRIES.forEach((ind) => {
    // Check various forms? For now just check if the industry name is in text.
    // We handle "Manufacturer" matching "Manufacturers" via logic or simple check.
    // Let's rely on simple inclusion for phrases.
    // Special case: "Manufacturer"
    if (
      ind === "Manufacturer" &&
      (hasPhrase("manufacturer") || hasPhrase("manufacturing"))
    ) {
      result.industries.push(ind);
    }
    // Special case: "Pharmaceuticals"
    else if (
      ind === "Pharmaceuticals" &&
      (hasPhrase("pharma") || hasPhrase("pharmaceutical"))
    ) {
      result.industries.push(ind);
    } else if (hasPhrase(ind)) {
      result.industries.push(ind);
    }
  });

  // 2. Locations (City, State, Country) - EXACT match only (no partial matches)
  // We can use the populated dropdown options to be safe
  const checkDropdown = (id, prop) => {
    const options = Array.from(document.getElementById(id).options)
      .map((o) => o.value)
      .filter((v) => v);
    // Sort by length desc to match longest phrases first (e.g. "New York" before "New")
    options.sort((a, b) => b.length - a.length);

    for (const opt of options) {
      // EXACT word boundary match against the full query text
      // This allows "companies in India" to match "India", but prevents "dia" from matching "India"
      const optVal = opt.toLowerCase().trim();
      if (optVal.length < 3) continue; // Skip very short abbreviations to avoid false positives

      // Create regex for the option value (escape special chars)
      const escapedOpt = optVal.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const regex = new RegExp(`\\b${escapedOpt}\\b`, "i");

      if (regex.test(t)) {
        result[prop] = opt;
        break; // Take the first best match (longest)
      }
    }
  };

  checkDropdown("filter-city", "city");
  checkDropdown("filter-state", "state");
  checkDropdown("filter-country", "country");
  // Product Category handled separately with exact matching only

  // Extract product name keywords for exact matching
  // Look for common product-related keywords in the query
  const productKeywords = [];
  const words = t.split(/\s+/); // Split into words

  // Filter out common stop words and short words
  const stopWords = [
    "the",
    "a",
    "an",
    "for",
    "in",
    "of",
    "to",
    "and",
    "or",
    "companies",
    "company",
    "provide",
    "show",
    "me",
    "find",
    "search",
    "with",
    "that",
    "from",
  ];

  // Also exclude words that were already matched to other filters
  const matchedWords = new Set();
  if (result.city)
    result.city
      .toLowerCase()
      .split(/\s+/)
      .forEach((w) => matchedWords.add(w));
  if (result.state)
    result.state
      .toLowerCase()
      .split(/\s+/)
      .forEach((w) => matchedWords.add(w));
  if (result.country)
    result.country
      .toLowerCase()
      .split(/\s+/)
      .forEach((w) => matchedWords.add(w));

  // Also exclude words that were matched to industries
  result.industries.forEach((ind) => {
    ind
      .toLowerCase()
      .split(/\s+/)
      .forEach((w) => matchedWords.add(w));
  });

  const meaningfulWords = words.filter(
    (word) =>
      word.length >= 3 && !stopWords.includes(word) && !matchedWords.has(word),
  );

  // Add meaningful words as potential product keywords
  meaningfulWords.forEach((word) => {
    if (!productKeywords.includes(word)) {
      productKeywords.push(word);
    }
  });

  result.productNameKeywords = productKeywords;

  // Also store the full query text for product category matching
  // This will be used for exact matching against dropdown options
  if (meaningfulWords.length > 0) {
    result.productCategory = meaningfulWords.join(" ");
  }

  return result;
}

// Gemini Fallback (Skeleton as requested)
async function parseWithGemini(text) {
  try {
    const res = await fetch("/api/voice-search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: text }),
    });

    if (!res.ok) throw new Error("Server error");

    const data = await res.json();
    return data;
  } catch (e) {
    console.error("Gemini Parse Error", e);
    return null;
  }
}

async function applyVoiceFilter() {
  const input = document.getElementById("voice-input").value.trim();
  if (!input) return;

  document.getElementById("voice-status").textContent = "Processing...";

  let parsed = parseVoiceInput(input);

  // Check if we found anything useful
  const hasData =
    parsed.city ||
    parsed.state ||
    parsed.country ||
    parsed.industries.length > 0 ||
    parsed.productCategory ||
    (parsed.productNameKeywords && parsed.productNameKeywords.length > 0);

  if (!hasData) {
    // Try Gemini if local parse failed, but ONLY if query is long enough to be meaningful
    if (input.length >= 4) {
      const aiParsed = await parseWithGemini(input);
      if (aiParsed) {
        // Merge AI results.
        // Note: AI might return strings that don't match our dropdowns exactly.
        // Ideally we would fuzzy match AI output to our dropdowns.
        parsed = aiParsed;
      }
    } else {
      console.log("⚠️ Query too short for AI fallback. Skipping.");
    }
  }

  console.log("🎯 Voice Filter Result:", parsed);

  // APPLY to UI

  // 1. Reset Filters (Robust Implementation)
  console.log("🔄 Resetting filters before voice search...");
  try {
    if (typeof resetFilters === "function") {
      resetFilters();
    } else {
      // Manual Fallback if global function is missing
      [
        "filter-country",
        "filter-state",
        "filter-city",
        "filter-company-type",
      ].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.selectedIndex = 0;
      });
      document
        .querySelectorAll('input[name="industry"]')
        .forEach((cb) => (cb.checked = false));

      const pCat = document.getElementById("filter-product-category");
      if (pCat) Array.from(pCat.options).forEach((o) => (o.selected = false));

      const pName = document.getElementById("filter-product-name");
      if (pName) Array.from(pName.options).forEach((o) => (o.selected = false));

      window.voiceSelectedProductNames = null;
      window.voiceSelectedProductCategories = null;
    }
  } catch (e) {
    console.error("Error resetting filters:", e);
  }

  // 2. Set Dropdowns
  if (parsed.city) {
    const select = document.getElementById("filter-city");
    // Try to find exact match
    for (let i = 0; i < select.options.length; i++) {
      if (select.options[i].value.toLowerCase() === parsed.city.toLowerCase()) {
        select.selectedIndex = i;
        // Trigger change to auto-fill state/country logic we detailed earlier
        select.dispatchEvent(new Event("change"));
        break;
      }
    }
  }
  // Delay slightly if city triggered auto-fill, or just set others if city didn't cover it
  if (parsed.state) {
    const select = document.getElementById("filter-state");
    if (select.value === "") {
      // Only if not auto-filled
      for (let i = 0; i < select.options.length; i++) {
        if (
          select.options[i].value.toLowerCase() === parsed.state.toLowerCase()
        ) {
          select.selectedIndex = i;
          select.dispatchEvent(new Event("change"));
          break;
        }
      }
    }
  }
  if (parsed.country) {
    const select = document.getElementById("filter-country");
    if (select.value === "") {
      for (let i = 0; i < select.options.length; i++) {
        // fuzzy or exact?
        if (
          select.options[i].value.toLowerCase() === parsed.country.toLowerCase()
        ) {
          select.selectedIndex = i;
          select.dispatchEvent(new Event("change"));
          break;
        }
      }
    }
  }
  if (
    parsed.productCategory &&
    parsed.productNameKeywords &&
    parsed.productNameKeywords.length > 0
  ) {
    const select = document.getElementById("filter-product-category");
    const keywords = parsed.productNameKeywords;

    console.log("🔍 Product Category - Searching for keywords:", keywords);
    console.log(
      "📋 Available options:",
      Array.from(select.options).map((o) => o.value),
    );

    const matchedValues = [];

    // Find ALL options that contain any of the keywords (UNION logic)
    for (let i = 0; i < select.options.length; i++) {
      const optionValue = select.options[i].value.toLowerCase().trim();
      if (optionValue === "") continue;

      // Check if option contains any keyword
      const hasMatch = keywords.some((keyword) =>
        optionValue.includes(keyword.toLowerCase()),
      );

      if (hasMatch) {
        matchedValues.push(select.options[i].value);
      }
    }

    // Store matched values globally for filter application
    if (matchedValues.length > 0) {
      // Set ALL matches in UI (Multi-select)
      for (let i = 0; i < select.options.length; i++) {
        if (matchedValues.includes(select.options[i].value)) {
          select.options[i].selected = true;
        }
      }

      // Store all matches for filtering
      window.voiceSelectedProductCategories = matchedValues;

      console.log("✓ Product Category: Matched options -", matchedValues);
    } else {
      // No match found - clear stored values
      window.voiceSelectedProductCategories = null;
      console.log("✗ Product Category: No matches found, keeping as 'All'");
    }
  }

  console.log(
    "🔍 Checking product name keywords...:",
    parsed.productNameKeywords,
  );

  // 4. Set Product Name (Matching: contains any keyword - UNION logic)
  if (parsed.productNameKeywords && parsed.productNameKeywords.length > 0) {
    const select = document.getElementById("filter-product-name");

    console.log(
      "🔍 Product Name - Searching for keywords:",
      parsed.productNameKeywords,
    );
    console.log(
      "📋 Available options:",
      Array.from(select.options).map((o) => o.value),
    );

    const matchedValues = [];

    // Find ALL options that contain any of the keywords (UNION logic)
    for (let i = 0; i < select.options.length; i++) {
      const optionValue = select.options[i].value.toLowerCase().trim();

      if (optionValue === "") continue;

      // Check if option contains any keyword
      const hasMatch = parsed.productNameKeywords.some((keyword) =>
        optionValue.includes(keyword.toLowerCase()),
      );

      if (hasMatch) {
        matchedValues.push(select.options[i].value);
      }
    }

    // Store matched values globally for filter application
    if (matchedValues.length > 0) {
      // Set ALL matches in UI (Multi-select)
      for (let i = 0; i < select.options.length; i++) {
        if (matchedValues.includes(select.options[i].value)) {
          select.options[i].selected = true;
        }
      }

      // Store all matches for filtering
      window.voiceSelectedProductNames = matchedValues;

      console.log("✓ Product Name: Matched options -", matchedValues);
    } else {
      // No match found - clear stored values
      window.voiceSelectedProductNames = null;
      console.log("✗ Product Name: No matches found, keeping as 'All'");
    }

    applyFilters();
  }

  // 3. Set Industries (Checkboxes)
  if (parsed.industries && parsed.industries.length > 0) {
    const checkboxes = document.querySelectorAll('input[name="industry"]');
    checkboxes.forEach((cb) => {
      if (
        parsed.industries.some(
          (ind) => ind.toLowerCase() === cb.value.toLowerCase(),
        )
      ) {
        cb.checked = true;
      }
    });
  }

  // Final Apply - with union logic info
  if (
    window.voiceSelectedProductNames ||
    window.voiceSelectedProductCategories
  ) {
    console.log("📊 UNION FILTER MODE ACTIVE:");
    if (window.voiceSelectedProductNames) {
      console.log(
        ` - Product Names: ${window.voiceSelectedProductNames.length} matches`,
      );
      console.log(`   ${window.voiceSelectedProductNames.join(", ")}`);
    }
    if (window.voiceSelectedProductCategories) {
      console.log(
        ` - Product Categories: ${window.voiceSelectedProductCategories.length} matches`,
      );
      console.log(`   ${window.voiceSelectedProductCategories.join(", ")}`);
    }
    console.log("");
    console.log(
      "💡 NOTE: Your applyFilters() function needs to check these global variables:",
    );
    console.log("   - window.voiceSelectedProductNames (array)");
    console.log("   - window.voiceSelectedProductCategories (array)");
    console.log(
      "   Use OR logic to match ANY value in these arrays for filtering.",
    );
  }

  applyFilters();
  document.getElementById("voice-status").textContent = "Filters Applied!";
}
