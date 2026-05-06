const fileInput = document.querySelector("#fileInput");
const folderInput = document.querySelector("#folderInput");
const fileDropzone = document.querySelector("#fileDropzone");
const folderDropzone = document.querySelector("#folderDropzone");
const fileList = document.querySelector("#fileList");
const analyzeButton = document.querySelector("#analyzeButton");
const statusBox = document.querySelector("#status");
const summary = document.querySelector("#summary");
const results = document.querySelector("#results");
const uvtInput = document.querySelector("#uvtInput");
const agentSelect = document.querySelector("#agentSelect");
const reteivaInput = document.querySelector("#reteivaInput");
const reteicaInput = document.querySelector("#reteicaInput");
const pdfModal = document.querySelector("#pdfModal");
const pdfFrame = document.querySelector("#pdfFrame");
const pdfModalTitle = document.querySelector("#pdfModalTitle");

let selectedFiles = [];
let selectedPdfs = [];
let lastPayload = null;
const icaFormState = new Map();
let activePdfUrl = "";

window.addEventListener("load", () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
});

fileInput.addEventListener("change", () => {
  setSelectedFiles(Array.from(fileInput.files || []));
  renderFileList();
});

folderInput.addEventListener("change", () => {
  setSelectedFiles(Array.from(folderInput.files || []));
  renderFileList();
});

fileDropzone.addEventListener("click", () => {
  fileInput.click();
});

folderDropzone.addEventListener("click", () => {
  folderInput.click();
});

fileDropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

folderDropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    folderInput.click();
  }
});

for (const zone of [fileDropzone, folderDropzone]) {
  zone.addEventListener("dragover", (event) => {
    event.preventDefault();
    zone.classList.add("dragging");
  });

  zone.addEventListener("dragleave", () => {
    zone.classList.remove("dragging");
  });
}

fileDropzone.addEventListener("drop", async (event) => {
  event.preventDefault();
  fileDropzone.classList.remove("dragging");
  setSelectedFiles(Array.from(event.dataTransfer.files || []));
  renderFileList();
});

folderDropzone.addEventListener("drop", async (event) => {
  event.preventDefault();
  folderDropzone.classList.remove("dragging");
  setSelectedFiles(await filesFromDrop(event.dataTransfer));
  renderFileList();
});

analyzeButton.addEventListener("click", async () => {
  if (!selectedFiles.length) {
    setStatus("Selecciona al menos un XML para analizar.", false);
    return;
  }

  const form = new FormData();
  selectedFiles.forEach((file) => form.append("files", file));
  const params = new URLSearchParams({
    uvt: uvtInput.value || "52374",
    withholding_agent: agentSelect.value,
    supplier_income_tax_filer: "true",
    reteiva: String(reteivaInput.checked),
    reteica: String(reteicaInput.checked),
  });

  analyzeButton.disabled = true;
  setStatus("Analizando facturas...", false);
  results.innerHTML = "";

  try {
    const response = await fetch(`/api/analyze?${params.toString()}`, {
      method: "POST",
      body: form,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.error || "No se pudo analizar.");
    }
    lastPayload = payload;
    renderSummary(payload);
    renderResults(payload);
    const errorText = payload.errors?.length ? ` ${payload.errors.length} archivo(s) tuvieron error.` : "";
    setStatus(`Listo: ${payload.count} factura(s) procesada(s).${errorText}`, false);
  } catch (error) {
    setStatus(error.message, false, true);
  } finally {
    analyzeButton.disabled = false;
  }
});

function renderFileList() {
  if (!selectedFiles.length) {
    fileList.textContent = "No hay archivos seleccionados";
    return;
  }
  const names = selectedFiles.slice(0, 3).map((file) => file.webkitRelativePath || file.name);
  const extra = selectedFiles.length > 3 ? ` y ${selectedFiles.length - 3} más` : "";
  const pdfText = selectedPdfs.length ? ` · ${selectedPdfs.length} PDF disponible(s)` : "";
  fileList.textContent = `${selectedFiles.length} XML seleccionado(s): ${names.join(", ")}${extra}${pdfText}`;
}

function setSelectedFiles(files) {
  selectedFiles = onlyXml(files);
  selectedPdfs = onlyPdf(files);
}

function onlyXml(files) {
  return files.filter((file) => {
    const name = file.name.toLowerCase();
    const path = (file.webkitRelativePath || "").toLowerCase();
    return name.endsWith(".xml") || path.endsWith(".xml");
  });
}

function onlyPdf(files) {
  return files.filter((file) => {
    const name = file.name.toLowerCase();
    const path = (file.webkitRelativePath || "").toLowerCase();
    return name.endsWith(".pdf") || path.endsWith(".pdf");
  });
}

async function filesFromDrop(dataTransfer) {
  const items = Array.from(dataTransfer.items || []);
  const entries = items
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean);

  if (!entries.length) {
    return Array.from(dataTransfer.files || []);
  }

  const files = [];
  for (const entry of entries) {
    files.push(...await readEntry(entry));
  }
  return files;
}

async function readEntry(entry) {
  if (entry.isFile) {
    return [await new Promise((resolve) => entry.file(resolve))];
  }
  if (!entry.isDirectory) {
    return [];
  }

  const reader = entry.createReader();
  const children = [];
  let batch = [];
  do {
    batch = await new Promise((resolve) => reader.readEntries(resolve));
    children.push(...batch);
  } while (batch.length);

  const nested = await Promise.all(children.map(readEntry));
  return nested.flat();
}

function renderSummary(payload) {
  const retentions = payload.reports.flatMap((report) => report.retentions);
  const applied = retentions.filter((retention) => retention.applies);
  const suggested = retentions.filter((retention) => retention.suggested);
  const notApplied = retentions.filter((retention) => !retention.applies);
  const total = retentions.filter((retention) => retention.applies).reduce((sum, retention) => sum + Number(retention.amount || 0), 0);

  summary.hidden = false;
  summary.innerHTML = `
    ${metric("Facturas", payload.count)}
    ${metric("Retenciones aplicadas", applied.length)}
    ${metric("Sugeridas", suggested.length)}
    ${metric("Total retenido", money(total))}
  `;
}

function renderResults(payload) {
  const errors = payload.errors || [];
  results.innerHTML = [
    ...errors.map(renderError),
    ...payload.reports.map(renderInvoice),
  ].join("");
  if (window.lucide) {
    window.lucide.createIcons();
  }
  bindPdfButtons();
  bindIcaForms(payload);
  bindAutocompletes();
}

function renderInvoice(report) {
  const invoice = report.invoice;
  const totals = invoice.totals;
  const retentions = report.retentions.map((retention) => renderRetention(retention, report)).join("");
  const pdf = pdfForInvoice(invoice);
  const pdfButton = pdf ? `
    <button class="pdf-eye-button" type="button" data-pdf-source="${escapeHtml(invoice.source_file)}" title="Ver PDF">
      <i data-lucide="eye"></i>
    </button>
  ` : "";
  const partyRows = [
    ["Proveedor", `${invoice.supplier.name} (${invoice.supplier.document_id})`],
    ["Comprador", `${invoice.customer.name} (${invoice.customer.document_id})`],
    ["Base antes de impuestos", money(totals.retention_base || totals.tax_exclusive_amount || totals.line_extension_amount)],
    ["Total factura", money(totals.payable_amount)],
  ];

  return `
    <article class="invoice-card">
      <header class="invoice-head">
        <div>
          <h2>${escapeHtml(invoice.id || "Factura sin número")}</h2>
          <div class="invoice-meta">
            <span>${escapeHtml(invoice.issue_date || "Sin fecha")}</span>
            <span>${escapeHtml(invoice.source_file || "")}</span>
          </div>
        </div>
        <div class="invoice-actions">
          ${pdfButton}
          <span class="pill">${escapeHtml(report.classification.concept)}</span>
        </div>
      </header>
      <div class="invoice-body">
        <table class="data-table">
          <tbody>${partyRows.map(([key, value]) => `<tr><th>${key}</th><td>${escapeHtml(value)}</td></tr>`).join("")}</tbody>
        </table>
        <div class="retention-list">${retentions}</div>
      </div>
    </article>
  `;
}

function pdfForInvoice(invoice) {
  const sourceFile = String(invoice.source_file || "");
  if (!sourceFile.toLowerCase().endsWith(".xml")) {
    return null;
  }

  const expectedName = sourceFile.replace(/\.xml$/i, ".pdf").toLowerCase();
  const expectedPathSuffix = `/${expectedName}`;
  return selectedPdfs.find((file) => {
    const name = file.name.toLowerCase();
    const path = (file.webkitRelativePath || "").toLowerCase();
    return name === expectedName || path.endsWith(expectedPathSuffix);
  }) || null;
}

function renderRetention(retention, report) {
  const badgeClass = retention.suggested ? "suggested" : retention.applies ? "ok" : "no";
  const badgeIcon = retention.suggested ? "info" : retention.applies ? "check-circle-2" : "circle-minus";
  const badgeText = retention.suggested ? "Sugerida" : retention.applies ? "Aplica" : "No aplica";
  const evidence = [...(retention.evidence || []), ...(retention.missing_data || []).map((item) => `Dato faltante: ${item}`)];
  const rateText = retention.suggested && !retention.applies ? "Por validar" : percent(retention.rate);
  const amountText = retention.suggested && !retention.applies ? "Por validar" : money(retention.amount);

  return `
    <section class="retention">
      <div class="retention-title">
        <strong>${escapeHtml(retention.name)}</strong>
        <span class="badge ${badgeClass}"><i data-lucide="${badgeIcon}"></i>${badgeText}</span>
      </div>
      <div class="calc-row">
        <div><span>Base</span><strong>${money(retention.base)}</strong></div>
        <div><span>Tarifa</span><strong>${rateText}</strong></div>
        <div><span>Retención</span><strong>${amountText}</strong></div>
      </div>
      <p class="reason">${escapeHtml(retention.reason)}</p>
      ${evidence.length ? `<span class="evidence-title">Evidencia</span><ul class="evidence">${evidence.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}
      ${renderIcaForm(retention, report)}
    </section>
  `;
}

function renderIcaForm(retention, report) {
  if (retention.code !== "reteica" || !retention.suggested || retention.applies) {
    return "";
  }

  const invoice = report.invoice;
  const saved = icaFormState.get(invoice.source_file) || {};
  const municipality = saved.municipality || report.options?.detected_municipality || "";
  const selectedAgent = saved.agent || "";
  const needsManualRate = (retention.missing_data || []).includes("tarifa ICA municipal para el CIIU");
  const municipalityOptions = municipalitiesForReport(report, municipality);
  return `
    <form class="ica-form" data-source-file="${escapeHtml(invoice.source_file)}">
      <p class="ica-note">Para calcular ReteICA, el catálogo interno debe tener el CIIU del proveedor y la tarifa del municipio. Aquí solo confirmas datos de la operación.</p>
      <div class="ica-form-grid">
        <label>
          <span>Municipio</span>
          <div class="autocomplete" data-options="${escapeHtml(JSON.stringify(municipalityOptions))}">
            <input class="municipality-input" name="municipality" value="${escapeHtml(municipality)}" placeholder="Buscar municipio" autocomplete="off" required>
            <button class="autocomplete-toggle" type="button" title="Ver municipios">
              <i data-lucide="chevron-down"></i>
            </button>
            <div class="autocomplete-menu" role="listbox"></div>
          </div>
        </label>
        <label>
          <span>CIIU proveedor</span>
          <input name="ciiu" value="${escapeHtml(saved.ciiu || "")}" placeholder="Ej. 4631 o 4631B" autocapitalize="characters">
        </label>
        ${needsManualRate ? `
          <label>
            <span>Tarifa ICA x 1000</span>
            <input name="rate" value="${escapeHtml(saved.rate || "")}" placeholder="Ej. 4.14" inputmode="decimal">
          </label>
        ` : ""}
        <label>
          <span>Agente retenedor ICA</span>
          <select name="agent" required>
            <option value="">Seleccionar</option>
            <option value="true" ${selectedAgent === "true" ? "selected" : ""}>Sí</option>
            <option value="false" ${selectedAgent === "false" ? "selected" : ""}>No</option>
          </select>
        </label>
      </div>
      <div class="form-error" hidden></div>
      <input type="hidden" name="supplier_nit" value="${escapeHtml(invoice.supplier.document_id)}">
      <input type="hidden" name="customer_nit" value="${escapeHtml(invoice.customer.document_id)}">
      <button class="inline-button" type="submit">
        <i data-lucide="refresh-cw"></i>
        Recalcular ReteICA
      </button>
    </form>
  `;
}

function municipalitiesForReport(report, selected) {
  const options = [
    ...(report.options?.municipalities || []),
    selected,
  ].filter(Boolean);

  const seen = new Set();
  return options.filter((option) => {
    const key = normalizeMunicipality(option);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function normalizeMunicipality(value) {
  const normalized = String(value || "")
    .toUpperCase()
    .replaceAll(".", "")
    .replaceAll(",", "")
    .replaceAll("Ü", "U")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Z0-9]/g, "");

  const aliases = {
    "BOGOTADC": "BOGOTA",
    "BOGOTA": "BOGOTA",
    "MEDELLIN": "MEDELLIN",
  };
  return aliases[normalized] || normalized;
}

function bindAutocompletes() {
  document.querySelectorAll(".autocomplete").forEach((root) => {
    const input = root.querySelector(".municipality-input");
    const menu = root.querySelector(".autocomplete-menu");
    const toggle = root.querySelector(".autocomplete-toggle");
    const options = JSON.parse(root.dataset.options || "[]");

    const render = () => {
      const query = normalizeMunicipality(input.value);
      const matches = options
        .filter((option) => !query || normalizeMunicipality(option).includes(query))
        .slice(0, 12);

      menu.innerHTML = matches.length
        ? matches.map((option) => `<button type="button" role="option" data-value="${escapeHtml(option)}">${escapeHtml(option)}</button>`).join("")
        : `<div class="autocomplete-empty">Sin resultados</div>`;
      root.classList.add("open");
    };

    input.addEventListener("focus", render);
    input.addEventListener("input", render);
    toggle.addEventListener("click", (event) => {
      event.preventDefault();
      input.focus();
      render();
    });

    menu.addEventListener("click", (event) => {
      const option = event.target.closest("button[data-value]");
      if (!option) {
        return;
      }
      input.value = option.dataset.value;
      root.classList.remove("open");
    });
  });
}

document.addEventListener("click", (event) => {
  document.querySelectorAll(".autocomplete.open").forEach((root) => {
    if (!root.contains(event.target)) {
      root.classList.remove("open");
    }
  });
});

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-pdf]")) {
    closePdfModal();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !pdfModal.hidden) {
    closePdfModal();
  }
});

function bindPdfButtons() {
  document.querySelectorAll(".pdf-eye-button").forEach((button) => {
    button.addEventListener("click", () => {
      const report = lastPayload?.reports?.find((candidate) => candidate.invoice.source_file === button.dataset.pdfSource);
      const pdf = report ? pdfForInvoice(report.invoice) : null;
      if (!pdf) {
        setStatus("No encontré el PDF asociado a esta factura.", false, true);
        return;
      }
      openPdfModal(pdf);
    });
  });
}

function openPdfModal(file) {
  if (activePdfUrl) {
    URL.revokeObjectURL(activePdfUrl);
  }
  activePdfUrl = URL.createObjectURL(file);
  pdfModalTitle.textContent = file.name;
  pdfFrame.src = activePdfUrl;
  pdfModal.hidden = false;
  document.body.classList.add("modal-open");
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function closePdfModal() {
  pdfModal.hidden = true;
  pdfFrame.removeAttribute("src");
  document.body.classList.remove("modal-open");
  if (activePdfUrl) {
    URL.revokeObjectURL(activePdfUrl);
    activePdfUrl = "";
  }
}

function bindIcaForms(payload) {
  document.querySelectorAll(".ica-form").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const sourceFile = form.dataset.sourceFile;
      const file = selectedFiles.find((candidate) => candidate.name === sourceFile || candidate.webkitRelativePath === sourceFile);
      if (!file) {
        setStatus("No encontré el XML original para recalcular. Vuelve a seleccionar la factura.", false, true);
        return;
      }

      const formData = new FormData(form);
      const error = form.querySelector(".form-error");
      const municipalityInput = form.querySelector(".municipality-input");
      const municipalityOptions = JSON.parse(municipalityInput.closest(".autocomplete").dataset.options || "[]");
      const matchedMunicipality = municipalityOptions.find((option) => normalizeMunicipality(option) === normalizeMunicipality(formData.get("municipality")));
      if (!matchedMunicipality) {
        error.textContent = "Selecciona un municipio válido de la lista.";
        error.hidden = false;
        municipalityInput.focus();
        return;
      }
      const rateInput = form.querySelector('input[name="rate"]');
      if (rateInput && !String(rateInput.value || "").trim()) {
        error.textContent = "Ingresa la tarifa ICA x 1000 para este municipio y CIIU.";
        error.hidden = false;
        rateInput.focus();
        return;
      }
      error.hidden = true;
      formData.set("municipality", matchedMunicipality);
      icaFormState.set(sourceFile, {
        municipality: String(formData.get("municipality") || ""),
        ciiu: String(formData.get("ciiu") || ""),
        rate: String(formData.get("rate") || ""),
        agent: String(formData.get("agent") || ""),
      });
      if (formData.get("agent") !== "true") {
        setStatus("Si el comprador no es agente retenedor ICA, ReteICA se mantiene como no aplicable.", false);
      }

      const upload = new FormData();
      upload.append("files", file);
      const params = new URLSearchParams({
        uvt: uvtInput.value || "52374",
        withholding_agent: agentSelect.value,
        supplier_income_tax_filer: "true",
        reteiva: String(reteivaInput.checked),
        reteica: String(reteicaInput.checked),
        ica_supplier_nit: formData.get("supplier_nit"),
        ica_customer_nit: formData.get("customer_nit"),
        ica_municipality: formData.get("municipality"),
        ica_ciiu: formData.get("ciiu"),
        ica_rate: formData.get("rate") || "",
        ica_agent: formData.get("agent"),
      });

      setStatus("Recalculando ReteICA...", false);
      const response = await fetch(`/api/analyze?${params.toString()}`, {
        method: "POST",
        body: upload,
      });
      const recalculated = await response.json();
      if (!response.ok) {
        setStatus(recalculated.error || "No se pudo recalcular.", false, true);
        return;
      }

      const updatedReport = recalculated.reports[0];
      const index = payload.reports.findIndex((report) => report.invoice.source_file === sourceFile);
      if (index >= 0) {
        payload.reports[index] = updatedReport;
        lastPayload = payload;
        renderSummary(payload);
        renderResults(payload);
        const reteica = updatedReport.retentions.find((retention) => retention.code === "reteica");
        if (reteica?.applies) {
          setStatus("ReteICA recalculada con los datos ingresados.", false);
        } else if (reteica?.missing_data?.length) {
          setStatus(`ReteICA sigue pendiente: falta ${reteica.missing_data.join(", ")}.`, false);
        } else {
          setStatus("ReteICA recalculada.", false);
        }
      }
    });
  });
}

function renderError(error) {
  return `
    <section class="status errors">
      <strong>${escapeHtml(error.file)}</strong>: ${escapeHtml(error.error)}
    </section>
  `;
}

function metric(label, value) {
  return `<div class="metric"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function setStatus(message, hide, isError = false) {
  statusBox.hidden = hide;
  statusBox.textContent = message;
  statusBox.classList.toggle("errors", isError);
}

function money(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat("es-CO", {
    style: "currency",
    currency: "COP",
    maximumFractionDigits: 0,
  }).format(number);
}

function percent(value) {
  const number = Number(value || 0) * 100;
  return `${number.toLocaleString("es-CO", { maximumFractionDigits: 2 })}%`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
